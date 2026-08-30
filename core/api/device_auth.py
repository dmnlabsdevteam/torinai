#!/usr/bin/env python3
"""One device. No second door.

The companion channel is Stefan's personal connection to the substrate, and the
requirement is exact: only the R1 device may use it, nothing may override it,
and no other device may connect through that point.

A bearer token cannot satisfy that. A bearer token is, by definition, usable by
whoever holds it — the R1 currently stores one base64'd in device storage, and
copying that string to any other machine grants full access. So this replaces
bearer auth rather than sitting beside it. **There is deliberately no fallback
path**: an alternative way in is the thing that gets used to get in.

How the binding works:

  * The device generates a NON-EXTRACTABLE keypair (WebCrypto
    `generateKey(..., extractable=false)`). The private key cannot be exported
    by anything, including JavaScript running on the device itself, so the
    credential cannot be copied to a second device. That is what makes this
    device-bound rather than secret-bound.
  * Exactly ONE public key is ever enrolled. A request signed by any other key
    is rejected — there is no "additional device" flow.
  * Enrollment is one-shot and gated by a code that must be read off the HOST
    machine, so it cannot be driven remotely. Once bound, enrollment is closed;
    re-enrolling requires deliberate operator action on the host, never a
    network request.
  * Every request is signed over method + path + body digest + timestamp +
    nonce. Signature verification happens HERE, inside the substrate — not at
    the tunnel or proxy — so a compromised edge still cannot forge a request.
  * Timestamp window plus a nonce cache make captured requests unreplayable.

Honest limit, stated because it matters: this binds to the device. If the R1
itself is compromised at the OS level, code on that device could ask the key to
sign — it still cannot extract the key or use it from anywhere else. No design
available to a webview client gives more than that.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Optional, Tuple
from collections import deque

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

# State lives on the host filesystem, not in the database: binding the device
# must not depend on a service that can be down or reachable over the network.
_STATE_PATH = Path(
    os.getenv("TORIN_DEVICE_BINDING_PATH")
    or Path(__file__).resolve().parents[2] / "data" / "device_binding.json"
)

# Requests older than this are refused outright.
_MAX_SKEW_SECONDS = 60
# Nonces remembered inside the skew window; bounded so it cannot grow forever.
_NONCE_CACHE_MAX = 4096
# A short enrollment code that survives unlimited guesses is not a secret.
_MAX_ENROLLMENT_ATTEMPTS = 5


class DeviceAuthError(Exception):
    """Refusal. Carries a reason for the log, never for the client."""


@dataclass
class DeviceBinding:
    device_id: str
    public_key_b64: str
    enrolled_at: float
    label: str = "r1"
    # The device declares which primitive it can actually do.
    #
    # Not generality for its own sake: the R1's WebView is Chromium
    # 133.0.6943.137 (verified over adb), and WebCrypto Ed25519 only became
    # available by default around Chromium 137. ECDSA P-256 has universal
    # support and is the safe default; Ed25519 is accepted for devices that
    # have it. Guessing wrong here would mean a security path that silently
    # cannot be used by the one device it exists for.
    algorithm: str = "ecdsa-p256"

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "public_key_b64": self.public_key_b64,
            "enrolled_at": self.enrolled_at,
            "label": self.label,
            "algorithm": self.algorithm,
        }


class DeviceChannel:
    """The single-device gate for the companion channel."""

    def __init__(self, state_path: Path = _STATE_PATH):
        self.state_path = Path(state_path)
        self._binding: Optional[DeviceBinding] = None
        self._enrollment_code: Optional[str] = None
        self._failed_enrollments: int = 0
        self._seen_nonces: Deque[str] = deque(maxlen=_NONCE_CACHE_MAX)
        self._nonce_set = set()
        self._load()

    # ---------------------------------------------------------------- state

    def _load(self) -> None:
        try:
            if self.state_path.exists():
                d = json.loads(self.state_path.read_text())
                self._binding = DeviceBinding(**d)
                logger.info(
                    f"companion channel bound to device {self._binding.device_id} "
                    f"({self._binding.label}) — enrollment closed"
                )
        except Exception as e:
            # A corrupt binding must NOT silently fail open.
            logger.error(f"device binding unreadable ({e}); channel stays closed")
            self._binding = None

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._binding.to_dict(), indent=2))
        tmp.replace(self.state_path)
        try:
            os.chmod(self.state_path, 0o600)
        except OSError:
            pass

    # ----------------------------------------------------------- enrollment

    @property
    def is_bound(self) -> bool:
        return self._binding is not None

    def open_enrollment(self) -> str:
        """Begin enrollment. HOST-ONLY: the code must be read off this machine.

        Refuses if a device is already bound. Rebinding is deliberate operator
        action (`reset_binding`), never something a request can trigger.
        """
        if self._binding is not None:
            raise DeviceAuthError("a device is already bound; enrollment is closed")
        self._enrollment_code = secrets.token_hex(4).upper()
        logger.warning(f"ENROLLMENT OPEN — code {self._enrollment_code} (expires on use)")
        return self._enrollment_code

    @staticmethod
    def _load_public_key(public_key_b64: str, algorithm: str):
        """Public key from what the device can actually export.

        WebCrypto exports raw 32-byte Ed25519 keys, and P-256 as either raw
        (65-byte uncompressed point) or SPKI. Accept all three shapes so the
        client is not forced into a format its runtime will not produce.
        """
        raw = base64.b64decode(public_key_b64)
        alg = (algorithm or "").lower()
        if alg == "ed25519":
            if len(raw) == 32:
                return ed25519.Ed25519PublicKey.from_public_bytes(raw)
            return serialization.load_der_public_key(raw)
        if alg in ("ecdsa-p256", "ecdsa", "p-256"):
            if len(raw) == 65 and raw[0] == 0x04:
                return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
            return serialization.load_der_public_key(raw)
        raise DeviceAuthError(f"unsupported algorithm '{algorithm}'")

    def enroll(self, device_id: str, public_key_b64: str, code: str, label: str = "r1",
               algorithm: str = "ecdsa-p256") -> DeviceBinding:
        """Bind the one device. Consumes the code."""
        if self._binding is not None:
            raise DeviceAuthError("already bound")
        if not self._enrollment_code:
            raise DeviceAuthError("enrollment is not open")
        # Constant-time: an enrollment code must not be discoverable by timing.
        if not hmac.compare_digest(code.strip().upper(), self._enrollment_code):
            # A wrong guess costs an attempt. Without this the code is a short
            # secret that survives unlimited tries, which is a way in.
            self._failed_enrollments += 1
            remaining = _MAX_ENROLLMENT_ATTEMPTS - self._failed_enrollments
            if remaining <= 0:
                self._enrollment_code = None
                self._failed_enrollments = 0
                logger.error("enrollment CLOSED after repeated bad codes — reopen on the host")
                raise DeviceAuthError("too many bad codes; enrollment closed")
            raise DeviceAuthError(f"enrollment code mismatch ({remaining} attempts left)")
        try:
            raw = base64.b64decode(public_key_b64)
            self._load_public_key(public_key_b64, algorithm)
        except DeviceAuthError:
            raise
        except Exception as e:
            raise DeviceAuthError(f"not a valid {algorithm} public key: {e}")

        self._binding = DeviceBinding(
            device_id=device_id,
            public_key_b64=base64.b64encode(raw).decode(),
            enrolled_at=time.time(),
            label=label,
            algorithm=(algorithm or "ecdsa-p256").lower(),
        )
        self._enrollment_code = None
        self._save()
        logger.warning(f"DEVICE BOUND: {device_id} ({label}) — enrollment now closed")
        return self._binding

    def reset_binding(self) -> None:
        """Unbind. Operator action on the host; never reachable from a request."""
        self._binding = None
        self._enrollment_code = None
        try:
            if self.state_path.exists():
                self.state_path.unlink()
        except OSError:
            pass
        logger.warning("device binding cleared — channel closed until re-enrolled")

    # --------------------------------------------------------- verification

    @staticmethod
    def canonical(method: str, path: str, body: bytes, timestamp: str, nonce: str) -> bytes:
        """Exactly what the device signs. Body is digested, not echoed."""
        digest = hashlib.sha256(body or b"").hexdigest()
        return "\n".join([method.upper(), path, digest, timestamp, nonce]).encode()

    def verify(
        self,
        method: str,
        path: str,
        body: bytes,
        device_id: str,
        timestamp: str,
        nonce: str,
        signature_b64: str,
    ) -> None:
        """Raise DeviceAuthError unless this is THE device, now, once."""
        if self._binding is None:
            raise DeviceAuthError("no device is bound; channel is closed")

        if not hmac.compare_digest(str(device_id), self._binding.device_id):
            raise DeviceAuthError("device id is not the bound device")

        try:
            ts = float(timestamp)
        except (TypeError, ValueError):
            raise DeviceAuthError("malformed timestamp")
        skew = abs(time.time() - ts)
        if skew > _MAX_SKEW_SECONDS:
            raise DeviceAuthError(f"timestamp outside {_MAX_SKEW_SECONDS}s window (skew {skew:.0f}s)")

        if not nonce or nonce in self._nonce_set:
            raise DeviceAuthError("replayed or missing nonce")

        try:
            pub = self._load_public_key(
                self._binding.public_key_b64, self._binding.algorithm
            )
            message = self.canonical(method, path, body, timestamp, nonce)
            sig = base64.b64decode(signature_b64)
            if isinstance(pub, ed25519.Ed25519PublicKey):
                pub.verify(sig, message)
            else:
                # WebCrypto ECDSA emits raw r||s; `cryptography` expects DER.
                if len(sig) == 64:
                    r = int.from_bytes(sig[:32], "big")
                    s = int.from_bytes(sig[32:], "big")
                    sig = encode_dss_signature(r, s)
                pub.verify(sig, message, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            raise DeviceAuthError("signature does not verify against the bound device key")
        except Exception as e:
            raise DeviceAuthError(f"signature check failed: {e}")

        # Only record the nonce once the signature is good, so an attacker
        # cannot burn valid nonces with forged requests.
        if len(self._seen_nonces) == self._seen_nonces.maxlen:
            self._nonce_set.discard(self._seen_nonces[0])
        self._seen_nonces.append(nonce)
        self._nonce_set.add(nonce)


_channel: Optional[DeviceChannel] = None


def get_device_channel() -> DeviceChannel:
    global _channel
    if _channel is None:
        _channel = DeviceChannel()
    return _channel


__all__ = ["DeviceChannel", "DeviceBinding", "DeviceAuthError", "get_device_channel"]
