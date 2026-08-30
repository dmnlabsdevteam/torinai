#!/usr/bin/env python3
"""Task work must be scored against the family it actually belongs to.

WHAT THIS PINS. `_LEARNING_TYPE_TO_TASK_FAMILY` covered 6 of LearningType's 10
members and was read with a `.get(learning_type, TaskFamily.CLASSIFICATION)`
default. Combined with callers that stated no family, 10,601 of 11,720 recorded
decisions were scored against the classification arms without anything deciding
they were classification problems -- and the three CONTROL arms, which exist to
choose between remediation APPROACHES, were never selected once.

These tests are structural: they read the maps and the enums, so they need no
database and write nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.agents.autonomous.shared_types import TaskType            # noqa: E402
from core.learning.learning_interfaces import LearningType          # noqa: E402
from core.learning.meta_learning import (                           # noqa: E402
    TASK_TYPE_TO_FAMILY, TaskFamily, task_family_for_task_type)
from core.learning.unified_learning_system import (                 # noqa: E402
    _LEARNING_TYPE_TO_TASK_FAMILY)

#: Acting on the system and verifying the effect. These are what the CONTROL
#: arms (direct_remediation, diagnose_then_act, verify_first) choose between.
CONTROL_TASK_TYPES = {"execution", "planning", "security_remediation"}


def test_every_task_type_has_a_family():
    """An unmapped task type must be a test failure, not a silent default."""
    missing = [t.value for t in TaskType if task_family_for_task_type(t) is None]
    assert not missing, f"TaskTypes with no TaskFamily: {missing}"


def test_control_work_maps_to_control():
    """Remediation is CONTROL work; it must not land in another family."""
    for name in CONTROL_TASK_TYPES:
        assert task_family_for_task_type(name) is TaskFamily.CONTROL, (
            f"{name} must map to CONTROL, got {task_family_for_task_type(name)}")


def test_unknown_task_type_is_none_not_a_guess():
    """None means unknown. A default here is what mis-filed 10,601 decisions."""
    assert task_family_for_task_type("not_a_task_type") is None
    assert task_family_for_task_type(None) is None


def test_one_authority_for_the_translation():
    """The coordinator must delegate rather than hold a second copy.

    Two tables that can disagree about what family a task belongs to is the
    duplicate-authority defect; the coordinator's copy is the one that was
    unreachable from UnifiedLearningSystem.
    """
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = AutonomousCoordinator.__new__(AutonomousCoordinator)
    for task_type in TaskType:
        assert coordinator._task_family_for(task_type) is \
            task_family_for_task_type(task_type), (
                f"coordinator and module disagree about {task_type}")


def test_substrate_learning_types_are_mapped():
    """The four substrate types were all silently filed as classification."""
    for name, expected in (("induction", TaskFamily.REASONING),
                           ("synthesis", TaskFamily.GENERATION),
                           ("causal", TaskFamily.REASONING)):
        learning_type = LearningType(name)
        assert _LEARNING_TYPE_TO_TASK_FAMILY.get(learning_type) is expected, (
            f"{name} must map to {expected}, got "
            f"{_LEARNING_TYPE_TO_TASK_FAMILY.get(learning_type)}")


def test_contribution_is_deliberately_unmapped():
    """Admitting a proposal is not a problem with strategy alternatives.

    Mapping it anyway would credit a strategy for an event no strategy
    influenced. It must be absent, and the absence must be handled rather than
    defaulted -- which the caller does by returning 'unmapped_learning_type'.
    """
    assert LearningType.CONTRIBUTION not in _LEARNING_TYPE_TO_TASK_FAMILY


def test_no_learning_type_falls_through_to_classification():
    """Only genuinely-classification types may resolve to CLASSIFICATION."""
    classification = {lt.value for lt, fam in _LEARNING_TYPE_TO_TASK_FAMILY.items()
                      if fam is TaskFamily.CLASSIFICATION}
    assert classification == {"supervised", "transfer"}, (
        f"unexpected types filed as classification: {classification}")
