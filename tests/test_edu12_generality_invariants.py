#!/usr/bin/env python3
"""EDU-12's generality invariants, kept in the suite.

EDU-12's entire claim is that ONE unchanged architecture was taught four
different subjects. That claim rests on three mechanical checks, so those
checks belong where they will run again rather than only in the experiment that
first reported them.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

EDU12 = Path(__file__).resolve().parents[1] / "experiments" / "edu" / "EDU-12"
sys.path.insert(0, str(EDU12))

from attempt import assert_subject_agnostic  # noqa: E402
from exam_seal import contamination, seal  # noqa: E402
from exam_validity import validate  # noqa: E402
from generality import (architecture_fingerprint, check_subject_purity,  # noqa: E402
                        substrate_file_count)

BLOCKS = ("mathematics", "programming", "causal_science", "language")
EXAMS = ("PRETEST", "POSTTEST", "TRANSFER")


def load(name):
    spec = importlib.util.spec_from_file_location(name, EDU12 / "subjects" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", BLOCKS)
def test_a_subject_is_data_and_never_code(name):
    """A fingerprint over core/ is trivially satisfied by moving the
    domain-specific cleverness into the subject file instead. So a subject may
    declare content and tool NAMES, and may not define a function, a class, a
    lambda, or import the substrate."""
    violations = check_subject_purity(EDU12 / "subjects" / f"{name}.py")
    assert not violations, [f"{v.kind}: {v.detail}" for v in violations]


def test_the_attempt_path_cannot_name_a_subject():
    """The other place domain-specific code could hide."""
    assert not assert_subject_agnostic(BLOCKS)


@pytest.mark.parametrize("name", BLOCKS)
def test_every_exam_item_is_answerable_from_its_own_evidence(name):
    """The stage-1 defect: four items named a condition that was present in
    every observation, so the answer was not identifiable and the substrate's
    correct minimal reading was scored as a 50% false-confidence rate."""
    subject = load(name)
    problems = []
    for exam in EXAMS:
        problems += validate(getattr(subject, exam))
    assert not problems, [f"{p.item_id}: {p.reason} :: {p.detail}" for p in problems]


@pytest.mark.parametrize("name", BLOCKS)
def test_no_exam_item_is_a_copy_of_a_lesson(name):
    subject = load(name)
    leaks = contamination(list(subject.POSTTEST) + list(subject.TRANSFER),
                          subject.LESSONS)
    assert not leaks, leaks


@pytest.mark.parametrize("name", BLOCKS)
def test_exams_are_disjoint_from_each_other(name):
    """A posttest that reuses pretest items measures memory of the pretest."""
    subject = load(name)
    pre = {i["id"] for i in subject.PRETEST}
    post = {i["id"] for i in subject.POSTTEST}
    transfer = {i["id"] for i in subject.TRANSFER}
    assert not (pre & post) and not (pre & transfer) and not (post & transfer)
    # Compared on SUBSTANCE, not prompt text. A causal item's prompt is a
    # generic instruction ("which conditions are required") and the item IS its
    # observations, so identical prompts across exams are correct there while
    # identical DATA would be contamination.
    import json
    substance = [json.dumps({k: v for k, v in item.items() if k != "id"},
                            sort_keys=True, default=str)
                 for item in subject.PRETEST + subject.POSTTEST + subject.TRANSFER]
    assert len(substance) == len(set(substance)), "an exam item is repeated verbatim"


def test_the_fingerprint_is_deterministic_and_covers_the_substrate():
    assert architecture_fingerprint() == architecture_fingerprint()
    assert substrate_file_count() > 200


def test_the_fingerprint_changes_when_anything_changes(tmp_path, monkeypatch):
    """A hash that never moves is indistinguishable from one that is not
    computed. Verified on a temporary tree so core/ is never touched."""
    import generality

    root = tmp_path / "core"
    (root / "sub").mkdir(parents=True)
    (root / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(generality, "SUBSTRATE_ROOT", root)

    first = generality.architecture_fingerprint()
    (root / "a.py").write_text("x = 2\n")
    assert generality.architecture_fingerprint() != first, "content change went unnoticed"

    (root / "a.py").write_text("x = 1\n")
    assert generality.architecture_fingerprint() == first
    (root / "sub" / "b.py").write_text("")
    assert generality.architecture_fingerprint() != first, "added file went unnoticed"


def test_transfer_items_declare_what_they_compose():
    """A transfer item must require combining taught pieces, and must say which
    -- otherwise "transfer" is an unfalsifiable label on a hard question."""
    for name in BLOCKS:
        subject = load(name)
        concepts = {lesson["concept"] for lesson in subject.LESSONS}
        for item in subject.TRANSFER:
            composed = item.get("composes")
            assert composed and len(composed) >= 2, f"{item['id']} composes nothing"
            unknown = set(composed) - concepts
            assert not unknown, f"{item['id']} composes untaught concepts {unknown}"


def test_seal_detects_a_changed_exam():
    original = [{"id": "a", "answer": 1}]
    assert seal(original) == seal([{"id": "a", "answer": 1}])
    assert seal(original) != seal([{"id": "a", "answer": 2}])


# ---- the freeze -----------------------------------------------------------

def test_the_frozen_baseline_still_holds():
    """The substrate must be byte-identical to what the admissible S0 measured.

    If this fails, either the substrate was edited during the educational phase
    -- which destroys the distinction between "Torin learned" and "we upgraded
    Torin while teaching it" -- or the freeze needs to be deliberately re-taken
    with a new baseline. It must never be quietly updated to match.
    """
    from generality import check_freeze

    violation = check_freeze(EDU12 / "FROZEN.json")
    assert violation is None, violation.message


def test_the_freeze_check_actually_detects_a_change(tmp_path, monkeypatch):
    """A guard that cannot fail is not a guard. Verified on a temporary tree so
    the real substrate is never touched."""
    import json

    import generality

    root = tmp_path / "core"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(generality, "SUBSTRATE_ROOT", root)

    freeze = tmp_path / "FROZEN.json"
    freeze.write_text(json.dumps({
        "architecture_fingerprint": generality.architecture_fingerprint(),
        "substrate_files": generality.substrate_file_count()}))
    assert generality.check_freeze(freeze) is None

    (root / "a.py").write_text("x = 2\n")
    violation = generality.check_freeze(freeze)
    assert violation is not None
    assert "changed since the baseline was frozen" in violation.message


def test_the_freeze_records_what_may_and_may_not_be_repaired():
    """The rule is part of the record, not folklore."""
    import json

    frozen = json.loads((EDU12 / "FROZEN.json").read_text())
    assert frozen["freeze_id"].startswith("EDU-12_S0_ADMISSIBLE")
    assert "may not expand Torin's cognitive implementation" in frozen["rule"]

    # A RE-FREEZE MUST BE DELIBERATE AND TRACEABLE. The guard failing is what
    # is supposed to happen when the substrate changes; quietly updating the
    # fingerprint to match would turn the guard into a rubber stamp.
    if frozen["freeze_id"] != "EDU-12_S0_ADMISSIBLE":
        assert "supersedes" in frozen, "a re-freeze must name what it replaced"
        assert frozen["why_refrozen"], "a re-freeze must record why"
        superseded = EDU12 / frozen["supersedes"]["record"]
        assert superseded.exists(), "the superseded freeze must be kept"
        assert (frozen["architecture_fingerprint"]
                != frozen["supersedes"]["fingerprint"])
    assert any("synthes" in item for item in frozen["may_not_be_repaired"])
    assert any("bypasses the production ingress" in item
               for item in frozen["may_be_repaired"])
