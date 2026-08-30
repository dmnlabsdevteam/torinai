#!/usr/bin/env python3
"""An exam item must be answerable from what the item supplies.

Stage 1 produced a 50% false-confidence rate in causal science, and every one
of those "errors" was the substrate being right. Two items asked which
conditions were required while holding one of those conditions PRESENT IN EVERY
OBSERVATION -- so "requires spark" and "does not require spark" predicted
identically, the evidence could not separate them, and the minimal consistent
structure the learner returned was the correct reading of the data.

An item like that does not measure competence. It measures whether the learner
will assert something its evidence does not support, and rewards the failure
this whole ladder is built to prevent.

So exam items are validated before the exam is sealed: every causal item's
stated answer must be UNIQUELY RECOVERABLE from its own observations. An item
that fails is a defect in the exam, not a hard question.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.learning.learning_authority import get_learning_authority  # noqa: E402

#: The stated answer must lead the runner-up by this factor. A MARGIN, not an
#: absolute mass: the hypothesis space is 3^n, so absolute posterior mass shrinks
#: with the number of conditions and says nothing about whether the item is
#: determined. An earlier absolute threshold of 0.20 rejected a perfectly fair
#: item whose stated answer was already the unique best.
IDENTIFIABILITY_MARGIN = 1.2


@dataclass
class InvalidItem:
    item_id: str
    reason: str
    detail: str


def _unvarying(observations: Sequence[Dict[str, Any]]) -> List[str]:
    """Conditions that never change across observations cannot be assessed."""
    if not observations:
        return []
    sets = [set(o.get("conditions", [])) for o in observations]
    everywhere = set.intersection(*sets)
    return sorted(everywhere)


def validate(exam: Sequence[Dict[str, Any]]) -> List[InvalidItem]:
    problems: List[InvalidItem] = []
    for item in exam:
        if item.get("kind") != "causal_structure":
            continue
        observations = item.get("observations", [])
        answer = item.get("answer", {})
        claimed = set(answer.get("requires", [])) | set(answer.get("forbids", []))

        constant = set(_unvarying(observations))
        unidentifiable = sorted(claimed & constant)
        if unidentifiable:
            problems.append(InvalidItem(
                str(item.get("id")), "answer names a condition that never varies",
                f"{unidentifiable} present in every observation"))
            continue

        # The learning authority owns induction; validation asks it the same
        # question the exam will, so an item cannot be validated by one
        # learner and answered by another.
        space = get_learning_authority().induce_causal_structure(observations)
        if space is None:
            problems.append(InvalidItem(str(item.get("id")), "no observations", ""))
            continue
        stated = (frozenset(answer.get("requires", [])),
                  frozenset(answer.get("forbids", [])))
        best, best_mass = space.most_probable()
        if (best.requires, best.forbids) != stated:
            problems.append(InvalidItem(
                str(item.get("id")), "stated answer is not what the evidence supports",
                f"evidence best supports requires={sorted(best.requires)} "
                f"forbids={sorted(best.forbids)} at {best_mass:.3f}"))
            continue
        posterior = sorted(space.posterior(), reverse=True)
        runner_up = posterior[1] if len(posterior) > 1 else 0.0
        if runner_up > 0.0 and best_mass / runner_up < IDENTIFIABILITY_MARGIN:
            problems.append(InvalidItem(
                str(item.get("id")), "evidence does not determine a single answer",
                f"best {best_mass:.3f} vs runner-up {runner_up:.3f}"))
    return problems


__all__ = ["validate", "InvalidItem", "IDENTIFIABILITY_MARGIN"]
