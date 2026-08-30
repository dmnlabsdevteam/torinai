#!/usr/bin/env python3
"""Deriving a procedure from what it must produce, not from being shown how.

`RuleInducer` acquires ONE rule from demonstrations of a transition: it is
shown the action and generalizes what the action does. That is how the
substrate learns an instruction set. It cannot answer a different question --
WHICH instructions, in what order, under what condition -- because nobody
demonstrated the composition.

This does. The evidence is input/output pairs and nothing else: a list and the
number the procedure must produce. No trace, no hint, no demonstration of the
algorithm. A candidate is accepted only if it produces the required answer on
every example, and it is built out of operators the substrate has already
learned, so it can never do anything it has not learned to do.

WHY NOT THE PLANNER. `plan_for_state_goal` searches ground action sequences
toward a goal in ONE state, and its answer is the length of that problem. A
fold has no fixed length. What is searched here is the space of PROCEDURES --
guard/operator pairs valid across every example at once -- and the planner has
no representation for that. The two are complementary: this derives the loop, a
plan composes procedures whose count is known in advance.

A POLICY, NOT A PROGRAM ENUMERATION. Enumerating guarded programs is
exponential in the flags, so it collapses exactly as the substrate grows more
operators and observations -- the opposite of what a lifelong learner needs.
Instead the search is over a POLICY: an assignment of one operator to each
abstract state (the subset of guards that hold there). All examples are run
under the policy at once, so a wrong assignment breaks SOME example and is
rejected globally -- the same reason a mislabelled rule cannot survive. The
distinct abstract states the examples visit are few and do not multiply with
depth, so cost is polynomial in operators x flags x example-length. A committed
register value is never destructively overwritten, which keeps the readings
canonical, and the policy is then generalised to the fewest guarded rules that
reproduce it.

ALL OF THEM. Every consistent policy is generalised and the results are
deduplicated BY BEHAVIOUR: two that take the same steps on every example are
the same procedure written twice. What survives is genuine underdetermination
-- reported as MULTIPLE_PROCEDURES rather than resolved by picking one, for the
same reason `MULTIPLE_HYPOTHESES` exists in the induction owner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from core.execution.procedure import (Actuator, Operator, Procedure, RunStatus,
                                      Step)
from core.learning.learning_policy import guard_learning
from core.learning.rule_induction import Fact

logger = logging.getLogger(__name__)

#: Ceiling on procedure size. A procedure is a decision list with one operator
#: per guard, so this is also the number of distinct conditions it may branch
#: on. Reported when reached, never silently applied: NO_PROCEDURE under a
#: bound is "none this small", not "none exists".
DEFAULT_MAX_RULES = 5


class SynthesisStatus(Enum):
    PROCEDURE_DERIVED = "procedure_derived"
    MULTIPLE_PROCEDURES = "multiple_procedures"
    NO_PROCEDURE = "no_procedure"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class IOExample:
    """One input the procedure must handle, and what it must produce.

    `build` returns a FRESH actuator every time: a candidate that ran halfway
    and stopped has left the world in a state its successor must not inherit.
    """

    label: str
    build: Callable[[], Actuator]
    #: Every term of the required answer, not only the first. A procedure that
    #: produces a STRUCTURE -- a reading with a subject and an object -- was
    #: scored on its first argument alone, so a procedure that got the subject
    #: right and the object wrong counted as correct.
    expected: Tuple[str, ...]
    max_steps: int

    def __post_init__(self):
        if isinstance(self.expected, str):
            object.__setattr__(self, "expected", (self.expected,))
        else:
            object.__setattr__(self, "expected", tuple(self.expected))


@dataclass
class SynthesisResult:
    status: SynthesisStatus
    procedures: List[Procedure] = field(default_factory=list)
    size: Optional[int] = None
    candidates_run: int = 0
    detail: str = ""

    @property
    def procedure(self) -> Optional[Procedure]:
        """The derived procedure, and only when the evidence determined one."""
        return (self.procedures[0]
                if self.status is SynthesisStatus.PROCEDURE_DERIVED else None)


def _registers(state: FrozenSet[Fact]) -> Dict[str, Tuple[str, ...]]:
    """Single-valued observations -- a register holds one value: predicate -> args.

    A predicate seen with two values in one state is not a register here and is
    left out, so the write-once rule never fires on a genuinely multi-valued
    observation."""
    reg: Dict[str, Tuple[str, ...]] = {}
    multi: Set[str] = set()
    for f in state:
        if len(f.args) != 1:
            continue
        if f.predicate in reg and reg[f.predicate] != f.args:
            multi.add(f.predicate)
        reg[f.predicate] = f.args
    for pred in multi:
        reg.pop(pred, None)
    return reg


def _cursor_predicates(example: "IOExample", operators: Sequence[Operator]) -> FrozenSet[str]:
    """Registers advanced by MOST operators -- cursors/counters that move every
    step by design, so the write-once rule must not apply to them. A value
    register is written by the one or two operators that bind it; a cursor is
    moved by nearly all of them, which tells them apart without naming either."""
    counts: Dict[str, int] = {}
    applicable = 0
    for op in operators:
        m = example.build()
        before = _registers(m.observe() or frozenset())
        if not m.perform(op.action):
            continue
        applicable += 1
        for pred, val in _registers(m.observe() or frozenset()).items():
            if before.get(pred) != val:
                counts[pred] = counts.get(pred, 0) + 1
    if applicable == 0:
        return frozenset()
    return frozenset(p for p, c in counts.items() if c * 2 > applicable)


def _destructive(before: FrozenSet[Fact], after: FrozenSet[Fact],
                 initial: Dict[str, Tuple[str, ...]], cursors: FrozenSet[str]) -> bool:
    """Did the step OVERWRITE a committed VALUE register with an unrelated value?

    A register may be set from its unset value (a bind) or grown so the new
    value still carries the old (an extend). Replacing a committed value with
    one that does not build on it is destructive -- the wasted earlier write is
    the redundant path that makes trace choice ambiguous. Cursors are exempt."""
    rb, ra = _registers(before), _registers(after)
    for pred, old in rb.items():
        if pred in cursors:
            continue
        new = ra.get(pred)
        if new is None or new == old:
            continue
        if old == initial.get(pred):
            continue
        old_tokens = "_".join(old).split("_")
        new_tokens = "_".join(new).split("_")
        if all(tok in new_tokens for tok in old_tokens):
            continue
        return True
    return False


def _terminal_fact(state: FrozenSet[Fact], terminal: str) -> Optional[Fact]:
    return next((f for f in sorted(state) if f.predicate == terminal), None)


# ---- the policy CSP: one operator per abstract state ----------------------
def _run_under_policy(example, policy, by_name, terminal, guard_set,
                      initial, cursors):
    """Follow the policy deterministically. Returns 'ok' / 'wrong' / 'dead', or
    ('need', guard_subset, applicable) -- a state the policy has not decided."""
    expected = tuple(example.expected)
    act = example.build()
    for _ in range(example.max_steps + 1):
        state = act.observe()
        if state is None:
            return "dead"
        ans = _terminal_fact(state, terminal)
        if ans is not None:
            return "ok" if tuple(ans.args) == expected else "wrong"
        gs = frozenset(g for g in guard_set if g in state)
        if gs not in policy:
            applicable = tuple(name for name, op in by_name.items()
                               if op.instances(state) is not None)
            return ("need", gs, applicable)
        op = by_name[policy[gs]]
        if op.instances(state) is None:
            return "dead"
        before = state
        if not act.perform(op.action):
            return "dead"
        after = act.observe()
        if after is None or after == before:
            return "dead"
        if _destructive(before, after, initial, cursors):
            return "dead"
    return "dead"


def _search_policies(examples, by_name, terminal, guard_set, max_policies, stats):
    """Backtracking over guard-state -> operator. Collects up to `max_policies`
    distinct consistent policies so underdetermination survives."""
    prep = [( _registers(e.build().observe() or frozenset()),
              _cursor_predicates(e, list(by_name.values())) ) for e in examples]
    found: List[Dict[FrozenSet[Fact], str]] = []
    seen: Set[frozenset] = set()

    def recurse(policy):
        if len(found) >= max_policies:
            return
        need = None
        for example, (initial, cursors) in zip(examples, prep):
            stats["runs"] += 1
            r = _run_under_policy(example, policy, by_name, terminal, guard_set,
                                  initial, cursors)
            if r == "ok":
                continue
            if isinstance(r, tuple):
                need = r
                break
            return  # 'wrong' / 'dead'
        if need is None:
            sig = frozenset(policy.items())
            if sig not in seen:
                seen.add(sig)
                found.append(dict(policy))
            return
        _, gs, applicable = need
        for op_name in applicable:
            policy[gs] = op_name
            recurse(policy)
            del policy[gs]
            if len(found) >= max_policies:
                return

    recurse({})
    return found


# ---- generalise a policy to the fewest guarded rules ----------------------
class _Point:
    __slots__ = ("present", "applicable", "chosen")

    def __init__(self, present, applicable, chosen):
        self.present, self.applicable, self.chosen = present, applicable, chosen


def _points_under_policy(examples, policy, by_name, terminal, guard_set):
    points: List[_Point] = []
    for example in examples:
        act = example.build()
        for _ in range(example.max_steps + 1):
            state = act.observe()
            if state is None or _terminal_fact(state, terminal) is not None:
                break
            gs = frozenset(g for g in guard_set if g in state)
            if gs not in policy:
                break
            applicable = frozenset(name for name, op in by_name.items()
                                   if op.instances(state) is not None)
            points.append(_Point(gs, applicable, policy[gs]))
            act.perform(by_name[policy[gs]].action)
    return points


def _rule_eligible(guard, op_name, p) -> bool:
    return op_name in p.applicable and all(g in p.present for g in guard)


def _greedy_guard(op_name, remaining, guard_pool):
    """The most general guard under which every eligible point chose op_name.

    Built by GREEDY separation instead of enumerating 2**flags subsets: start
    unguarded, and while the rule would misfire (cover a point that chose a
    different operator), add the one flag that is present in every op_name point
    and excludes the most misfiring ones. Polynomial in flags, so the flag
    vocabulary can grow without the generalisation blowing up. Returns
    (guard, covered_points) or None when the flags cannot separate it."""
    guard: Tuple[Fact, ...] = ()
    while True:
        covered = [p for p in remaining if _rule_eligible(guard, op_name, p)]
        good = [p for p in covered if p.chosen == op_name]
        bad = [p for p in covered if p.chosen != op_name]
        if not good:
            return None
        if not bad:
            return guard, good
        # Add the flag that excludes the most misfiring points while keeping some
        # of this operator's points. Dropping some good points is FINE -- they
        # are picked up by a later rule for the same operator under a different
        # guard, which is how one operator that fires in two conditions becomes
        # two rules. For a consistent policy good and bad points always differ in
        # a flag, so a separator always exists.
        best_flag, best_score = None, None
        for flag in guard_pool:
            if flag in guard:
                continue
            kept_good = sum(1 for p in good if flag in p.present)
            excluded_bad = sum(1 for p in bad if flag not in p.present)
            if kept_good == 0 or excluded_bad == 0:
                continue
            score = (excluded_bad, kept_good)
            if best_score is None or score > best_score:
                best_score, best_flag = score, flag
        if best_flag is None:
            return None  # flags cannot separate these (should not happen here)
        guard = guard + (best_flag,)


def _induce_decision_list(points, by_name, guards, max_rules):
    """Ordered rules so at every point the FIRST eligible rule's operator is the
    one chosen. Sequential covering with greedy guard construction -- most
    general first, refined only where it would misfire."""
    guard_pool = list(guards)
    remaining = list(points)
    order: List[Step] = []
    while remaining:
        if len(order) > max_rules:
            return None
        best = None  # (coverage, -guard_len, op_name, guard, covered)
        for op_name in by_name:
            found = _greedy_guard(op_name, remaining, guard_pool)
            if found is None:
                continue
            guard, covered = found
            score = (len(covered), -len(guard))
            if best is None or score > best[:2]:
                best = (len(covered), -len(guard), op_name, guard, covered)
        if best is None:
            return None
        _, _, op_name, guard, covered = best
        order.append(Step(guard=tuple(guard), operator=by_name[op_name]))
        ids = {id(p) for p in covered}
        remaining = [p for p in remaining if id(p) not in ids]
    return order if len(order) <= max_rules else None


def _order_steps(steps: List[Step]) -> Tuple[Step, ...]:
    guarded = [s for s in steps if s.is_guarded]
    plain = [s for s in steps if not s.is_guarded]
    return tuple(guarded + plain)


def _verify(procedure: Procedure, examples) -> bool:
    for example in examples:
        outcome = procedure.run(example.build(), example.max_steps)
        if outcome.status is not RunStatus.COMPLETED or outcome.contradictions:
            return False
        if outcome.answer is None or tuple(outcome.answer.args) != tuple(example.expected):
            return False
    return True


def derive_procedure(
    operators: Sequence[Operator],
    guards: Sequence[Fact],
    examples: Sequence[IOExample],
    terminal: str = "RESULT",
    max_rules: int = DEFAULT_MAX_RULES,
    max_policies: int = 8,
) -> SynthesisResult:
    """Derive a length-general procedure from input/output evidence alone."""
    guard_learning("procedure synthesis")

    if len(examples) < 2:
        return SynthesisResult(
            status=SynthesisStatus.INSUFFICIENT_EVIDENCE,
            detail=(f"{len(examples)} example(s); a procedure that must hold across "
                    f"inputs needs at least 2 to be constrained by more than one"))
    if not operators:
        return SynthesisResult(
            status=SynthesisStatus.INSUFFICIENT_EVIDENCE,
            detail="no learned operators were offered; nothing could be composed")

    by_name: Dict[str, Operator] = {op.action.predicate: op for op in operators}
    guard_set = tuple(guards)
    stats = {"runs": 0}

    policies = _search_policies(examples, by_name, terminal, guard_set,
                                max_policies, stats)
    if not policies:
        return SynthesisResult(
            status=SynthesisStatus.NO_PROCEDURE, candidates_run=stats["runs"],
            detail=("no assignment of one operator per abstract state reads every "
                    f"example with the {len(operators)} operator(s) offered"))

    kept: List[Procedure] = []
    signatures: Set[Tuple] = set()
    size: Optional[int] = None
    for policy in policies:
        points = _points_under_policy(examples, policy, by_name, terminal, guard_set)
        steps = _induce_decision_list(points, by_name, guard_set, max_rules)
        if steps is None:
            continue
        procedure = Procedure(steps=_order_steps(steps), terminal=terminal)
        if not _verify(procedure, examples):
            continue
        sig = tuple((e.label, tuple(procedure.run(e.build(), e.max_steps).trace))
                    for e in examples)
        if sig in signatures:
            continue
        signatures.add(sig)
        kept.append(procedure)
        size = len(steps) if size is None else min(size, len(steps))

    if not kept:
        return SynthesisResult(
            status=SynthesisStatus.NO_PROCEDURE, candidates_run=stats["runs"],
            detail=(f"a consistent policy exists but none states within {max_rules} "
                    f"rule(s); the bound was reached, not proven insufficient"))
    if len(kept) == 1:
        return SynthesisResult(status=SynthesisStatus.PROCEDURE_DERIVED,
                               procedures=kept, size=size,
                               candidates_run=stats["runs"])
    return SynthesisResult(
        status=SynthesisStatus.MULTIPLE_PROCEDURES, procedures=kept, size=size,
        candidates_run=stats["runs"],
        detail=(f"{len(kept)} procedures take different routes to the required "
                f"answers on every example; an input separating them would decide"))


__all__ = ["IOExample", "SynthesisResult", "SynthesisStatus", "derive_procedure",
           "DEFAULT_MAX_RULES"]
