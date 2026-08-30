#!/usr/bin/env python3
"""Teach KITE-17 from demonstrations, then persist and validate what was learned.

The acquisition half of the experiment. Two rules are taught because the
evaluation suite has to exercise both a static derivation and a state
transition with a retraction -- a rule that only ever adds facts cannot show
that chaining produces changing world states rather than accumulating theorems.

Nothing here is asserted by the teacher. The teacher supplies before / action /
after triples; every generalization is the learner's, and every promotion to
executable is the store's, on evidence the learner never saw.

Run with the model policy already strict:
    TORIN_MODEL_POLICY=strict_model_free python3 experiments/kite_teach.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.domain.concept_ingestion import EvidenceSourceType  # noqa: E402
from core.domain.evidence_producers import submit_demonstration  # noqa: E402
from core.learning.rule_induction import Fact, TrainingExample, get_rule_inducer  # noqa: E402
from core.learning.rule_store import get_rule_store, to_json  # noqa: E402
from core.model_policy import assert_model_free, model_telemetry  # noqa: E402

DOMAIN = "kite17"
F = Fact.parse


def zor_positive(x, y, evidence_id):
    before = (F(f"NAL({x})"), F(f"VEX({x},{y})"), F(f"TOR({y})"))
    return TrainingExample(before=before, action=F(f"KEM({x},{y})"),
                           after=before + (F(f"ZOR({x},{y})"),), evidence_id=evidence_id)


def zor_negative(before, action, evidence_id):
    return TrainingExample(before=before, action=action, after=before,
                           positive=False, evidence_id=evidence_id)


def move(who, a, b, evidence_id, opened=True, path=True, acted=True,
         at_source=True):
    """A transition that retracts the origin, so a delete effect is observable.

    `at_source` exists because its absence was a real gap in the teaching set.
    There were negatives for a closed destination, a missing path and no action
    taken -- but none for the object simply not being where the move starts. So
    nothing in the evidence forced AT(X,A) into the rule body, LGG had no reason
    to keep it, and the learned operator concluded AT(X,B) from a source it
    never checked.

    The cost was a planner that produced a one-step plan for AT(z,VAULT) from a
    world where z was in HALL: MOVE(z,LAB,VAULT) satisfies the learned rule,
    because the rule never asked whether z was in LAB. The plan was valid for
    the rule and impossible in the world.
    """
    before = [F(f"AT({who},{a})")] if at_source else []
    if path:
        before.append(F(f"PATH({a},{b})"))
    if opened:
        before.append(F(f"OPEN({b})"))
    before = tuple(before)
    ok = opened and path and acted and at_source
    after = (
        tuple(f for f in before if f != F(f"AT({who},{a})")) + (F(f"AT({who},{b})"),)
        if ok else before
    )
    return TrainingExample(
        before=before, action=F(f"MOVE({who},{a},{b})") if acted else None,
        after=after, positive=ok, evidence_id=evidence_id,
    )


ZOR_TEACHING = [
    zor_positive("a", "b", "zor_d1"),
    zor_positive("c", "d", "zor_d2"),
    zor_negative((F("VEX(e,f)"), F("TOR(f)")), F("KEM(e,f)"), "zor_no_NAL"),
    zor_negative((F("NAL(g)"), F("TOR(h)")), F("KEM(g,h)"), "zor_no_VEX"),
    zor_negative((F("NAL(i)"), F("VEX(i,j)")), F("KEM(i,j)"), "zor_no_TOR"),
    zor_negative((F("NAL(k)"), F("VEX(k,l)"), F("TOR(l)")), None, "zor_no_KEM"),
]
ZOR_HELD_OUT = [zor_positive("m", "n", "zor_h1"), zor_positive("p", "q", "zor_h2")]

MOVE_TEACHING = [
    move("ma", "R1", "R2", "mv_d1"), move("mb", "R3", "R4", "mv_d2"),
    move("mc", "R5", "R6", "mv_no_OPEN", opened=False),
    move("md", "R7", "R8", "mv_no_PATH", path=False),
    move("me", "R9", "R10", "mv_no_ACTION", acted=False),
    # The object is not at the origin: everything else holds and the move still
    # does not happen. This is what makes AT(X,A) a precondition rather than an
    # incidental fact that happened to be true in every positive example.
    move("mh", "R15", "R16", "mv_no_AT_SOURCE", at_source=False),
]
MOVE_HELD_OUT = [move("mf", "R11", "R12", "mv_h1"), move("mg", "R13", "R14", "mv_h2")]


async def record_demonstrations(examples):
    """Record each demonstration as a ROOT observation before anything reads it.

    The teacher is the observer here, so this is where the evidence chain gets
    its floor. Everything the learner produces from these -- the induced rule,
    the operator projected into the concept graph, any correspondence grounded
    on it -- declares these ids as ancestors, and a derivative whose ancestors
    are unrecorded is refused rather than treated as a root of its own.

    Idempotent: envelope ids are the demonstrations' own ids and the insert is
    ON CONFLICT DO NOTHING, so re-teaching does not manufacture a second root
    for one observation.
    """
    for example in examples:
        result = await submit_demonstration(
            example, domain_id=DOMAIN,
            source_type=EvidenceSourceType.USER_SUPPLIED,
            producer="kite_teacher")
        if not result.read_successfully:
            raise RuntimeError(
                f"{example.evidence_id}: {result.extraction_failures}")
    return len(examples)


async def teach(name, teaching, held_out):
    recorded = await record_demonstrations(list(teaching) + list(held_out))
    print(f"[{name}] recorded {recorded} demonstration(s) as evidence")
    result = get_rule_inducer().induce(teaching)
    print(f"[{name}] induction: {result.status.value}")
    if result.rule is None:
        print(f"[{name}] ABORT: {result.detail}")
        for candidate in result.candidates:
            print(f"[{name}]   candidate: {candidate}")
        return None

    store = get_rule_store()
    stored = (await store.record_induction(
        result, teaching, domain_id=DOMAIN, rule_kind=name))[0]
    print(f"[{name}] persisted {stored.rule_id} as {stored.status.value} "
          f"(executable={stored.is_executable})")

    outcome = await store.validate(stored, held_out)
    print(f"[{name}] validation: {outcome.status.value} "
          f"confirmed={outcome.confirmed} contradicted={outcome.contradicted} "
          f"independent_roots={outcome.independent_roots}")
    print(f"[{name}] rule: {stored.rule}")

    digest = hashlib.sha256(
        json.dumps(to_json(stored.rule), sort_keys=True).encode()
    ).hexdigest()
    print(f"[{name}] canonical_json_sha256: {digest}")
    return {
        "rule_id": stored.rule_id, "rule_kind": name,
        "status": stored.status.value, "formula": stored.rule.to_formula(),
        "canonical_json_sha256": digest,
        "canonical_json": to_json(stored.rule),
        "induction_roots": sorted({e.evidence_id for e in teaching if e.evidence_id}),
        "validation_roots": sorted({e.evidence_id for e in held_out if e.evidence_id}),
    }


async def main() -> int:
    taught = []
    for name, teaching, held_out in (
        ("zor", ZOR_TEACHING, ZOR_HELD_OUT),
        ("move", MOVE_TEACHING, MOVE_HELD_OUT),
    ):
        record = await teach(name, teaching, held_out)
        if record is None:
            return 1
        taught.append(record)

    assert_model_free("teaching")
    telemetry = model_telemetry()
    print(f"\nmodel: attempts={telemetry['attempts']} "
          f"executed={telemetry['executed']} policy={telemetry['policy']}")

    manifest = Path(__file__).resolve().parent / "baselines" / "kite_taught.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"domain": DOMAIN, "rules": taught}, indent=2))
    print(f"manifest -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
