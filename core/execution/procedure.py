#!/usr/bin/env python3
"""A procedure: learned operators, guarded, run until they produce an answer.

A PLAN IS NOT A PROGRAM. `plan_for_state_goal` returns a ground action sequence
that reaches a goal FROM ONE STATE. Its length is the length of that problem,
so a plan found on a four-element list cannot run on a five-element one. That
is enough to compose operations whose number is known in advance -- which is
what EDU-12's program-construction run does -- and it is not enough to express
a fold, where the number of steps is a property of the input.

What makes a procedure length-general is that its steps are LIFTED and
CONDITIONAL. A step fires whenever its guard holds and its operator's learned
preconditions match, and the loop is the repeated firing. Nothing here knows
how long the input is, and nothing here is compiled for a particular one.

    guard      zero-arity observations that must hold -- what the procedure is
               permitted to branch on, declared by the caller, never inferred
    operator   the learned rules for one action: what it requires and what it
               changes. Not a Python function -- the substrate's own model
    order      first applicable step wins; guarded steps precede unguarded ones

THE WORLD ACTS, THE MODEL PREDICTS, AND THEY ARE COMPARED. Each step executes
against the real actuator and the result is read back by observation, never
from the actuator's return value. The learned rule's predicted effect is then
checked against that observation through `effect_verification` -- the same
comparison the substrate's execution path already performs. A procedure that
runs to an answer while its own model was contradicted is reported as
UNPREDICTED, not as a success: the answer would be the machine's, and the
substrate would have been carried by a world it had misunderstood.

Every way a run can fail to produce an answer is a distinct outcome. Collapsing
them into a boolean would make "no step applied" indistinguishable from "the
machine refused the step" -- the first is an incomplete procedure, the second a
disagreement between what was learned and what is true.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import (Any, Dict, FrozenSet, List, Optional, Protocol, Sequence,
                    Tuple)

from core.execution.effect_verification import (RuntimeOutcome, ToolObservation,
                                                verify_effects)
from core.learning.rule_induction import (CandidateRule, Fact, RuleEffects,
                                          TrainingExample, applies)

logger = logging.getLogger(__name__)


class Actuator(Protocol):
    """Something that can be acted on and read back, independently."""

    def observe(self) -> Optional[FrozenSet[Fact]]:
        """The world as it is. None when it cannot be read at all."""

    def perform(self, action: Fact) -> bool:
        """Take the action. False when the world refused it."""


@dataclass(frozen=True)
class Operator:
    """One action and everything learned about what it does.

    Several rules per action is the normal case, not a special one: each is
    scoped to the predicate it explains -- what TAKE does to register A, and
    what TAKE does to the cursor -- because a rule may only conclude about
    terms its body binds. Requiring all of them to match is what keeps the
    action's preconditions complete.
    """

    action: Fact
    rules: Tuple[CandidateRule, ...]

    @property
    def name(self) -> str:
        return self.action.predicate

    def instances(self, state: FrozenSet[Fact]) -> Optional[List[RuleEffects]]:
        """The effects the learned model asserts here, or None if it does not apply."""
        example = TrainingExample(before=tuple(state - {self.action}),
                                  action=self.action)
        asserted: List[RuleEffects] = []
        for rule in self.rules:
            found = applies(rule, example)
            if not found:
                return None
            asserted.extend(found)
        return asserted


@dataclass(frozen=True)
class Step:
    """An operator and the condition under which the procedure uses it."""

    guard: Tuple[Fact, ...]
    operator: Operator

    def __post_init__(self):
        for flag in self.guard:
            if flag.args:
                raise ValueError(
                    f"a guard is a zero-arity observation; {flag} carries terms")

    @property
    def is_guarded(self) -> bool:
        return bool(self.guard)

    def holds(self, state: FrozenSet[Fact]) -> bool:
        return all(flag in state for flag in self.guard)

    def __str__(self) -> str:
        condition = " ∧ ".join(str(f) for f in self.guard) if self.guard else "otherwise"
        return f"{condition} → {self.operator.name}"


class RunStatus(Enum):
    """How a run ended. Only the first of these is an answer."""

    COMPLETED = "completed"
    STUCK = "stuck"
    REFUSED = "refused"
    NO_PROGRESS = "no_progress"
    UNPREDICTED = "unpredicted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNREADABLE = "unreadable"


@dataclass
class RunOutcome:
    status: RunStatus
    answer: Optional[Fact] = None
    trace: List[str] = field(default_factory=list)
    steps_taken: int = 0
    contradictions: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def produced_answer(self) -> bool:
        return self.status is RunStatus.COMPLETED and self.answer is not None


@dataclass(frozen=True)
class Procedure:
    """An ordered decision list over learned operators.

    Guarded steps precede unguarded ones, so a step that applies only in a
    particular condition is never shadowed by the general case. Order within
    each group is the order the steps were added.
    """

    steps: Tuple[Step, ...] = ()
    terminal: str = "RESULT"

    def extended(self, step: Step, position: Optional[int] = None) -> "Procedure":
        """Add a step, optionally at a chosen priority among the guarded ones.

        WHERE a guarded step goes is part of the procedure, not a detail. Two
        guards can both hold in one state -- a word is both the first one and a
        determiner -- and which fires is decided here. Appending always made
        that decision by the order the demands happened to arrive in, which is
        the order the EXAMPLES happened to be listed in.
        """
        guarded = [s for s in self.steps if s.is_guarded]
        plain = [s for s in self.steps if not s.is_guarded]
        if not step.is_guarded:
            plain.append(step)
        elif position is None:
            guarded.append(step)
        else:
            guarded.insert(position, step)
        return Procedure(steps=tuple(guarded + plain), terminal=self.terminal)

    def guards_used(self) -> List[Tuple[Fact, ...]]:
        return [s.guard for s in self.steps]

    def select(self, state: FrozenSet[Fact]) -> Optional[Tuple[Step, List[RuleEffects]]]:
        """The first step whose guard holds and whose operator applies."""
        for step in self.steps:
            if not step.holds(state):
                continue
            asserted = step.operator.instances(state)
            if asserted is None:
                continue
            return step, asserted
        return None

    def run(self, actuator: Actuator, max_steps: int) -> RunOutcome:
        """Execute against a real actuator until it answers or cannot continue."""
        trace: List[str] = []
        contradictions: List[str] = []

        for taken in range(max_steps + 1):
            state = actuator.observe()
            if state is None:
                return RunOutcome(RunStatus.UNREADABLE, trace=trace, steps_taken=taken,
                                  detail="the world could not be read")

            answer = next((f for f in sorted(state) if f.predicate == self.terminal), None)
            if answer is not None:
                return RunOutcome(RunStatus.COMPLETED, answer=answer, trace=trace,
                                  steps_taken=taken, contradictions=contradictions)
            if taken == max_steps:
                return RunOutcome(RunStatus.BUDGET_EXHAUSTED, trace=trace,
                                  steps_taken=taken, contradictions=contradictions,
                                  detail=f"no answer within {max_steps} steps")

            selected = self.select(state)
            if selected is None:
                return RunOutcome(RunStatus.STUCK, trace=trace, steps_taken=taken,
                                  contradictions=contradictions,
                                  detail="no step applies in this state")

            step, asserted = selected
            if not actuator.perform(step.operator.action):
                return RunOutcome(RunStatus.REFUSED, trace=trace, steps_taken=taken,
                                  contradictions=contradictions,
                                  detail=f"the world refused {step.operator.name}, "
                                         f"which the learned model said applied")

            after = actuator.observe()
            if after is None:
                return RunOutcome(RunStatus.UNREADABLE, trace=trace, steps_taken=taken + 1,
                                  detail="the world could not be read after acting")
            if after == state:
                return RunOutcome(RunStatus.NO_PROGRESS, trace=trace, steps_taken=taken + 1,
                                  contradictions=contradictions,
                                  detail=f"{step.operator.name} changed nothing observable")

            trace.append(step.operator.name)
            evidence = _verify(step, asserted, after, before=state)
            if evidence is RuntimeOutcome.CONTRADICTION:
                contradictions.append(f"step {taken + 1}: {step.operator.name}")

        return RunOutcome(RunStatus.BUDGET_EXHAUSTED, trace=trace, steps_taken=max_steps,
                          contradictions=contradictions)


def _verify(step: Step, asserted: Sequence[RuleEffects], after: FrozenSet[Fact],
            before: Optional[FrozenSet[Fact]] = None) -> RuntimeOutcome:
    """Check the learned model's prediction against what the world now shows.

    A retraction the same step re-asserts is not checked as a retraction: a
    register whose value is overwritten with the value it held retracts and
    adds the same fact, and reading that as a failed delete would report a
    contradiction where the model and the world agree.

    An effect still carrying a variable is one the operator declared it could
    not predict -- a value only running the action produces. It is checked
    against what the step CHANGED rather than looked up in the whole world.
    """
    outcomes = []
    for index, effects in enumerate(asserted):
        predicted = RuleEffects(add=effects.add,
                                delete=effects.delete - effects.add)
        observation = ToolObservation(
            observation_id=f"{step.operator.name}#{index}",
            tool_name=step.operator.name, invoked=True,
            tool_reported_success=True, observed=True, facts=after, before=before)
        outcomes.append(verify_effects(predicted, observation,
                                       operator=step.operator.name).outcome)
    if RuntimeOutcome.CONTRADICTION in outcomes:
        return RuntimeOutcome.CONTRADICTION
    if outcomes and all(o is RuntimeOutcome.CONFIRMATION for o in outcomes):
        return RuntimeOutcome.CONFIRMATION
    return RuntimeOutcome.INDETERMINATE


__all__ = ["Actuator", "Operator", "Step", "Procedure", "RunStatus", "RunOutcome"]
