#!/usr/bin/env python3
"""Prove the key was born in this device's secure hardware.

Enrollment without attestation is a promise: the client sends a public key and
the server takes its word that the private half lives somewhere safe. That is
exactly the gap that makes a bearer credential weak — and the R1's current
credentials are worse than a promise, they are static strings compiled into the
APK (`BuildConfig.TOKEN`, `CF_ID`, `CF_SECRET`), recoverable by pulling the APK
off the device and unzipping it.

Android Key Attestation replaces the promise with evidence. When the app
generates a key in the TEE with `setAttestationChallenge()`, the hardware emits
an X.509 chain:

    leaf (attestation cert, carries the challenge + security level)
      -> intermediate(s)
        -> Google Hardware Attestation Root

Each link signs the next, and the root is a key Google controls and publishes.
So a valid chain proves: this key was generated inside genuine, Google-certified
secure hardware, the challenge WE issued was present at generation time (so the
chain is not replayed from another enrollment), and the key material never left
that hardware.

The device this was written for reports `android.hardware.hardware_keystore=41`
(KeyMint 4.1, TEE-backed) and has no StrongBox, so TRUSTED_ENVIRONMENT is the
realistic ceiling and STRONG_BOX is accepted but not required.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import List, Optional

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

# The key-attestation extension Android stamps on the leaf certificate.
ATTESTATION_OID = x509.ObjectIdentifier("1.3.6.1.4.1.11129.2.1.17")

# SecurityLevel values from the attestation schema.
SECURITY_LEVELS = {0: "SOFTWARE", 1: "TRUSTED_ENVIRONMENT", 2: "STRONG_BOX"}

# Anything at SOFTWARE level is a key held by the OS, which is precisely what
# we are refusing to trust.
ACCEPTABLE_SECURITY_LEVELS = {"TRUSTED_ENVIRONMENT", "STRONG_BOX"}


# Google's hardware attestation roots, fetched from
# https://developer.android.com/privacy-and-security/security-key-attestation
#
# Pinned by PUBLIC KEY, not by certificate: root certs are reissued when they
# expire, but the key underneath persists, so pinning the cert would break on a
# routine rotation and pinning the key does not. Two roots are live — the long
# standing RSA root and the newer "Key Attestation CA1" EC root — and a device
# may chain to either.
GOOGLE_ATTESTATION_ROOT_SPKI_B64 = [
    # RSA root — 2.5.4.5=f92009e853b6b045
    # sha256(spki) = feb2ea7551ee316ed4bb443c8293b884dbfdea40b603ee3e4f4a897e4580fbae
    (
        "MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAr7bHgiuxpwHsK7Qui8xUFmOr75gv"
        "Msd/dTEDDJdSSxtf6An7xyqpRR90PL2abxM1dEqlXnf2tqw1Ne4Xwl5jlRfdnJLmN0pTy/4l"
        "j4/7tv0Sk3iiKkypnEUtR6WfMgH0QZfKHM1+di+y9TFRtv6y//0rb+T+W8a9nsNL/ggjnar8"
        "6461qO0rOs2cXjp3kOG1FEJ5MVmFmBGtnrKpa73XpXyTqRxB/M0n1n/W9nGqC4FSYa04T6N5"
        "RIZGBN2z2MT5IKGbFlbC8UrW0DxW7AYImQQcHtGl/m00QLVWutHQoVJYnFPlXTcHYvASLu+R"
        "hhsbDmxMgJJ0mcDpvsC4PjvB+TxywElgS70vE0XmLD+OJtvsBslHZvPBKCOdT0MS+tgSOIfg"
        "a+z1Z1g7+DVagf7quvmag8jfPioyKvxnK/EgsTUVi2ghzq8wm27ud/mIM7AY2qEORR8Go3TV"
        "B4HzWQgpZrt3i5MIlCaY504LzSRiigHCzAPlHws+W0rB5N+er5/2pJKnfBSDiCiFAVtCLOZ7"
        "gLiMm0jhO2B6tUXHI/+MRPjy02i59lINMRRev56GKtcd9qO/0kUJWdZTdA2XoS82ixPvZtXQ"
        "pUpuL12ab+9EaDK8Z4RHJYYfCT3Q5vNAXaiWQ+8PTWm2QgBR/bkwSWc+NpUFgNPN9PvQi8WE"
        "g5UmAGMCAwEAAQ=="
    ),
    # EC root — C=US,O=Google LLC,OU=Android,CN=Key Attestation CA1
    # sha256(spki) = 3ee44512a1af2beb39c889490c60ea3f82e43f5d5a5532f5ab9419f676cd07ec
    (
        "MHYwEAYHKoZIzj0CAQYFK4EEACIDYgAEI9ojcU7fPlsFCjxy6IRqzgeOoK0b+YsV9FPQywiy"
        "w8EQRTkJ9u3qwfnI4DGoSLlBqClTXJfgfCcZvs60FikNMHnu4fkRzObfgDkU2KNXezT9/RQ+"
        "XvNslxPHrHCowhGr"
    ),
]


class AttestationError(Exception):
    """Refusal, with a reason for the log."""


@dataclass
class AttestationResult:
    challenge: bytes
    attestation_security_level: str
    keymaster_security_level: str
    chain_length: int
    root_subject: str

    def to_dict(self) -> dict:
        return {
            "attestation_security_level": self.attestation_security_level,
            "keymaster_security_level": self.keymaster_security_level,
            "chain_length": self.chain_length,
            "root_subject": self.root_subject,
        }


# ---------------------------------------------------------------- ASN.1 (minimal)

def _read_tlv(buf: bytes, pos: int):
    """One DER TLV. Returns (tag, content_bytes, next_pos).

    A deliberately small reader rather than a dependency: this parses one
    well-known Google extension, and pulling in an ASN.1 library for it would
    add supply-chain surface to a security path for no gain.
    """
    if pos >= len(buf):
        raise AttestationError("truncated DER")
    tag = buf[pos]
    pos += 1
    if pos >= len(buf):
        raise AttestationError("truncated DER length")
    first = buf[pos]
    pos += 1
    if first & 0x80:
        n = first & 0x7F
        if n == 0 or n > 4 or pos + n > len(buf):
            raise AttestationError("bad DER length")
        length = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
    else:
        length = first
    end = pos + length
    if end > len(buf):
        raise AttestationError("DER length overruns buffer")
    return tag, buf[pos:end], end


def _seq_items(content: bytes) -> List[tuple]:
    items, pos = [], 0
    while pos < len(content):
        tag, val, pos = _read_tlv(content, pos)
        items.append((tag, val))
    return items


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big") if b else 0


def parse_attestation_extension(der: bytes) -> AttestationResult:
    """Pull the challenge and security levels out of the extension.

    KeyDescription ::= SEQUENCE {
        attestationVersion INTEGER, attestationSecurityLevel ENUMERATED,
        keymasterVersion INTEGER,   keymasterSecurityLevel  ENUMERATED,
        attestationChallenge OCTET_STRING, uniqueId OCTET_STRING,
        softwareEnforced AuthorizationList, teeEnforced AuthorizationList }
    """
    tag, content, _ = _read_tlv(der, 0)
    if tag != 0x30:
        raise AttestationError("attestation extension is not a SEQUENCE")
    items = _seq_items(content)
    if len(items) < 6:
        raise AttestationError(f"KeyDescription has {len(items)} fields, expected >= 6")

    att_level = SECURITY_LEVELS.get(_int(items[1][1]), "UNKNOWN")
    km_level = SECURITY_LEVELS.get(_int(items[3][1]), "UNKNOWN")
    challenge = items[4][1]
    return AttestationResult(
        challenge=challenge,
        attestation_security_level=att_level,
        keymaster_security_level=km_level,
        chain_length=0,
        root_subject="",
    )


# ---------------------------------------------------------------- chain

def _verify_signed_by(child: x509.Certificate, parent: x509.Certificate) -> None:
    pub = parent.public_key()
    try:
        if isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(child.signature, child.tbs_certificate_bytes,
                       ec.ECDSA(child.signature_hash_algorithm))
        elif isinstance(pub, rsa.RSAPublicKey):
            pub.verify(child.signature, child.tbs_certificate_bytes,
                       padding.PKCS1v15(), child.signature_hash_algorithm)
        else:
            raise AttestationError(f"unsupported issuer key type {type(pub).__name__}")
    except InvalidSignature:
        raise AttestationError(
            f"chain broken: '{child.subject.rfc4514_string()}' is not signed by "
            f"'{parent.subject.rfc4514_string()}'"
        )


def verify_attestation(
    chain_der: List[bytes],
    expected_challenge: bytes,
    trusted_root_pubkeys_der: Optional[List[bytes]] = None,
    require_hardware: bool = True,
) -> AttestationResult:
    """Verify the chain and the challenge, or raise.

    `trusted_root_pubkeys_der` pins the Google attestation root. When it is not
    supplied the chain is still verified link-by-link and the challenge is still
    checked, but the ROOT IS NOT PINNED — which means a self-generated chain
    would pass. That is a real difference, so it is logged loudly rather than
    quietly accepted.
    """
    # Pin by default. Passing an explicit list overrides (tests use synthetic
    # roots); passing [] disables pinning and is logged as unverified.
    if trusted_root_pubkeys_der is None:
        trusted_root_pubkeys_der = [base64.b64decode(k) for k in GOOGLE_ATTESTATION_ROOT_SPKI_B64]

    if not chain_der:
        raise AttestationError("empty attestation chain")

    certs = []
    for i, der in enumerate(chain_der):
        try:
            certs.append(x509.load_der_x509_certificate(der))
        except Exception as e:
            raise AttestationError(f"certificate {i} is not valid DER: {e}")

    # leaf -> ... -> root, each signed by the next.
    for i in range(len(certs) - 1):
        _verify_signed_by(certs[i], certs[i + 1])

    root = certs[-1]
    if trusted_root_pubkeys_der:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        root_spki = root.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        if root_spki not in trusted_root_pubkeys_der:
            raise AttestationError(
                "attestation root is not the pinned Google hardware attestation root"
            )
    else:
        logger.error(
            "ATTESTATION ROOT NOT PINNED — chain and challenge verified, but the root "
            "is unverified, so a self-generated chain would pass. Supply the Google "
            "hardware attestation root before trusting this as proof of hardware."
        )

    leaf = certs[0]
    try:
        ext = leaf.extensions.get_extension_for_oid(ATTESTATION_OID)
    except x509.ExtensionNotFound:
        raise AttestationError(
            "leaf certificate carries no key-attestation extension — the key was not "
            "generated with setAttestationChallenge(), so nothing is proven about it"
        )

    result = parse_attestation_extension(ext.value.public_bytes())
    result.chain_length = len(certs)
    result.root_subject = root.subject.rfc4514_string()

    if result.challenge != expected_challenge:
        raise AttestationError(
            "attestation challenge mismatch — this chain was produced for a different "
            "enrollment and is being replayed"
        )

    if require_hardware and result.attestation_security_level not in ACCEPTABLE_SECURITY_LEVELS:
        raise AttestationError(
            f"attestation security level is {result.attestation_security_level}; "
            f"a SOFTWARE key is held by the OS and is exactly what hardware binding refuses"
        )

    logger.warning(
        f"attestation OK: level={result.attestation_security_level} "
        f"keymaster={result.keymaster_security_level} chain={result.chain_length} "
        f"root={result.root_subject}"
    )
    return result


__all__ = ["verify_attestation", "parse_attestation_extension",
           "AttestationError", "AttestationResult", "ATTESTATION_OID"]
