#!/usr/bin/env python3
"""Sandboxed verification of the digital footprint scrubber.

This module deletes accounts, files legal takedowns, purges CDN caches and
submits data-broker opt-outs across 50+ real platforms. It is IRREVERSIBLE and
outward-facing, so "verify it works" cannot mean running it: a test suite that
proved the scrubber functional by scrubbing things would be the most
destructive test in the repository.

What is verified here instead:

  * the locally-computable components actually compute (patterns, signing)
  * NO NETWORK IS TOUCHED by any of it
  * nothing reports success for work it did not do

The last is the one that matters for a privacy tool. A false "removed" is worse
than a failure, because the user stops worrying about data that is still there.

NOT VERIFIED, and deliberately: whether an opt-out request is accepted by any
real broker, whether a deletion actually deletes, or whether a takedown
succeeds. Those require live destructive calls against third parties.
"""

import inspect

import pytest

from core.security.digital_footprint import (AggressiveDataBrokerAttacker,
                                             AggressivePatternDetector,
                                             CryptographicSigner,
                                             EnhancedBackgroundCheckRemover)


def _remover():
    """The class that actually implements removal and verification."""
    return EnhancedBackgroundCheckRemover(CryptographicSigner())


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any outbound HTTP during these tests is a test-design failure."""
    import aiohttp

    def forbidden(*args, **kwargs):
        raise AssertionError("a sandboxed test attempted a real network call")

    monkeypatch.setattr(aiohttp.ClientSession, "get", forbidden)
    monkeypatch.setattr(aiohttp.ClientSession, "post", forbidden)


# ---- the parts that are locally computable ------------------------------

def test_the_pattern_detector_actually_detects():
    detector = AggressivePatternDetector()
    findings = detector.detect(
        "contact me at alice@example.com or 555-123-4567, key AKIAIOSFODNN7EXAMPLE",
        platform="test")
    assert findings, "the detector found nothing in text full of identifiers"
    kinds = {str(getattr(f, "pattern_type", getattr(f, "type", ""))) for f in findings}
    assert kinds, "findings carry no classification"


def test_the_pattern_detector_does_not_invent_findings():
    """A detector that fires on anything is as useless as one that fires on
    nothing, and far more misleading."""
    detector = AggressivePatternDetector()
    assert not detector.detect("the weather today is mild and the sky is clear",
                               platform="test")


@pytest.mark.asyncio
async def test_cryptographic_signing_produces_verifiable_headers():
    signer = CryptographicSigner()
    await signer.initialize()
    headers = signer.generate_signed_headers({"action": "opt_out", "broker": "x"})
    assert headers, "signing produced no headers"
    assert any("sign" in k.lower() or "auth" in k.lower() for k in headers), headers
    # A different payload must not produce the same signature.
    other = signer.generate_signed_headers({"action": "delete", "broker": "y"})
    assert headers != other, "the signature does not depend on the payload"


# ---- the failure mode that matters --------------------------------------

@pytest.mark.asyncio
async def test_removal_is_never_reported_as_confirmed_without_evidence():
    """THE DEFECT THIS FILE EXISTS FOR.

    `verify_removal` searched nothing and returned True unconditionally, and
    its caller recorded that as "{broker}_verified" -- telling the user their
    personal data had been confirmed removed from Spokeo, Whitepages,
    PeopleFinder and TruePeopleSearch when no check had occurred.
    """
    attacker = _remover()
    result = await attacker.verify_removal("spokeo", {"name": "A Person"})

    assert isinstance(result, dict), "a bool cannot express 'not checked'"
    assert result["confirmed_removed"] is not True, (
        "removal was reported as confirmed with no search performed")
    assert result["status"] == "unverified"
    assert "cannot be confirmed" in result["reason"]


@pytest.mark.asyncio
async def test_an_unknown_broker_is_distinguished_from_an_unverified_one():
    attacker = _remover()
    result = await attacker.verify_removal("not-a-real-broker", {"name": "x"})
    assert result["status"] == "unknown_broker"
    assert result["confirmed_removed"] is None


def test_no_broker_definition_claims_a_search_capability_it_lacks():
    """Verification depends on a per-broker search endpoint. None are defined,
    which is exactly why the status is UNVERIFIED rather than a guess."""
    attacker = _remover()
    for name, broker in attacker.data_brokers.items():
        if "search_url" in broker:
            assert broker["search_url"], f"{name} declares an empty search_url"


def test_the_removal_tool_calls_methods_that_exist_on_the_class_it_builds():
    """It built `AggressiveDataBrokerAttacker(signer)` -- missing that class's
    required `brute_force_engine` argument -- and then called
    `_remove_from_broker` and `verify_removal`, neither of which exists on it.
    The tool raised TypeError on its first line every time it ran, so no opt-out
    was ever submitted through it."""
    import inspect

    import core.tools.security_tools as security_tools
    from core.security.digital_footprint import EnhancedBackgroundCheckRemover

    source = inspect.getsource(security_tools)
    assert "EnhancedBackgroundCheckRemover(signer)" in source
    for method in ("_remove_from_broker", "verify_removal", "initialize", "cleanup"):
        assert hasattr(EnhancedBackgroundCheckRemover, method), method

    # And the class that was being built genuinely lacks them.
    from core.security.digital_footprint import AggressiveDataBrokerAttacker
    assert not hasattr(AggressiveDataBrokerAttacker, "_remove_from_broker")


def test_the_caller_records_a_status_rather_than_a_bare_boolean():
    import core.tools.security_tools as security_tools

    source = inspect.getsource(security_tools)
    assert "_verification\"] = verification" in source or \
           "_verification'] = verification" in source
    assert "_verified\"] = verified" not in source


# ---- a stated gap, recorded rather than papered over --------------------

def test_the_module_still_has_no_rehearsal_mode():
    """5,879 lines of irreversible outward-facing operations with no dry-run,
    test_mode or simulate flag anywhere. Recorded as a finding: it means the
    only way to exercise the destructive paths is to perform them, which is why
    this file verifies the local components and refuses to verify the rest."""
    import core.security.digital_footprint as footprint

    source = inspect.getsource(footprint)
    has_rehearsal = any(flag in source for flag in
                        ("dry_run", "dry-run", "simulate=", "test_mode"))
    assert not has_rehearsal, (
        "a rehearsal mode now exists -- update this test and use it to verify "
        "the destructive paths properly")
