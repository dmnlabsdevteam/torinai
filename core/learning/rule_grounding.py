#!/usr/bin/env python3
"""Turning learned rules into operators a state planner can search over.

Learned rules are lifted -- MOVE(?X0,?X2,?X1) with variables. The planner is
propositional: its actions carry ground condition strings. Bridging them is
grounding, and it is the only thing standing between "Torin learned a
transition rule" and "Torin can compose learned transitions toward a goal".

Two admissibility rules, both consequences of work already done rather than new
policy:

  VALIDATED only. CANDIDATE, SUPPORTED and REFUTED rules are not executable
  cognition. The KITE-17 ablation established that this gate causally controls
  derivation, so planning must not quietly widen it.

  An action is required. A rule with action=None records that something
  followed from conditions, not that the agent can bring it about. Offering it
  as an operator would let the planner "achieve" a goal by asserting that the
  world happens to change. Rules stored before `action` existed read back with
  None and are correctly excluded.

Grounding enumerates variable assignments over the constants present in the
problem. That is exponential in the number of variables per rule, so the bound
is explicit and a run that hits it says so rather than returning a quietly
partial operator set -- a planner that silently lost operators would report
UNREACHABLE for a goal it simply was not given the means to reach.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
from dataclasses import dataclass, field
from typing import (Any, Dict, FrozenSet, Iterable, List, Optional, Sequence,
                    Set, Tuple)

from core.learning.rule_induction import (BindingOrigin, CandidateRule, Fact,
                                          is_variable)
from core.reasoning.value_authority import evaluate

logger = logging.getLogger(__name__)

#: Ceiling on grounded operators. Reached only by rules with several variables
#: over a large constant universe; reported, never silently truncated.
DEFAULT_MAX_OPERATORS = 5000

#: How many times the producible-term closure may widen before it is called
#: unconverged. Each pass admits the values produced by the pass before it, so
#: this is the longest chain of runtime-produced values a plan may thread --
#: read a file, parse what it held, compute from that, is three.
DEFAULT_CLOSURE_PASSES = 6


@dataclass(frozen=True)
class GroundOperator:
    """One concrete action, and the learned rule it came from."""

    name: str
    preconditions: Tuple[str, ...]
    effects: Tuple[str, ...]
    deletes: Tuple[str, ...]
    rule_id: Optional[str] = None
    bindings: Tuple[Tuple[str, str], ...] = ()
    #: True when some argument could only be filled by a term an action invents
    #: at runtime. Such an operator is offered PARTIALLY ground: the planner
    #: binds the rest by matching the state it is actually in.
    #:
    #: Enumerating those arguments here is impossible on purpose -- the term
    #: does not exist yet -- and minting one placeholder per ground action would
    #: give every occurrence of the action the same unknown, so two reads of a
    #: file would be one answer and the search would dedupe the second away.
    open_slots: Tuple[str, ...] = ()
    #: The values this action produces, unresolved. Resolved per APPLICATION, so
    #: each occurrence yields its own unknown and a value computable from the
    #: terms then in hand is computed rather than deferred.
    outputs: Tuple[Dict[str, Any], ...] = ()

    def to_action(self) -> Dict[str, Any]:
        """The shape TemporalReasoningSystem searches over."""
        return {
            "name": self.name,
            "preconditions": list(self.preconditions),
            "effects": list(self.effects),
            "deletes": list(self.deletes),
            "rule_id": self.rule_id,
            "bindings": dict(self.bindings),
            "open": bool(self.open_slots),
            "open_slots": list(self.open_slots),
            "outputs": [dict(o) for o in self.outputs],
        }


@dataclass
class GroundingReport:
    """What was offered to the planner, and what was withheld."""

    operators: List[GroundOperator] = field(default_factory=list)
    truncated: bool = False
    rules_used: List[str] = field(default_factory=list)
    rules_skipped: Dict[str, str] = field(default_factory=dict)
    rules_unreachable: Dict[str, str] = field(default_factory=dict)
    constants: List[str] = field(default_factory=list)
    closure_converged: bool = True

    def to_actions(self) -> List[Dict[str, Any]]:
        return [operator.to_action() for operator in self.operators]

    @property
    def complete(self) -> bool:
        """False when the operator set is known to be partial.

        A planner given a partial set can still find a plan, but its
        UNREACHABLE verdict is no longer a proof.

        This was `not self.truncated`, which accounts only for the operator
        LIMIT. Rules skipped for any other reason did not count -- so a
        grounding that discarded EVERY rule it was given and produced zero
        operators still reported complete, and the planner's UNREACHABLE was
        certified as a proof of impossibility over an empty operator set.

        Observed: both validated rules skipped as "no action recorded", 0
        operators, complete=True, planner UNREACHABLE. "I know of no way to do
        this" was being presented as "this cannot be done".

        `rules_unreachable` closes the second way the same claim can be false.
        Counting only DROPPED rules assumes an offered rule can fire, and a
        rule whose precondition names a predicate that nothing in the problem
        supplies and no operator produces cannot fire in any state the search
        can construct.

        Observed again, on the composition of two derived folds: three rules
        in, three used, none skipped, 48 operators, complete=True, planner
        UNREACHABLE -- while the world reached the goal in three steps. DIVIDE
        required QUOTIENT, the divider publishes QUOTIENT only after its
        operands are loaded, and no learned rule could predict it. The model
        was blind to a fact the world produces, and the verdict built on it was
        being certified as a proof of impossibility.
        """
        return (not self.truncated and not self.rules_skipped
                and not self.rules_unreachable and self.closure_converged)


def constants_in(facts: Iterable[Fact]) -> Set[str]:
    """Every ground term mentioned. Variables are not constants."""
    return {arg for fact in facts for arg in fact.args if not is_variable(arg)}


def invented_positions(rules: Sequence[Any]) -> Set[Tuple[str, int]]:
    """Argument positions that can hold a term some action invents at runtime.

    A value an action produces has no term until the action runs, so no amount
    of enumeration reaches it and every consumer of one has to bind it by
    matching instead. Which consumers those are is decidable here: a position
    is reachable by an invented term if some rule asserts an output variable
    there, or asserts a variable it bound from a position already reachable.

    The fixpoint is over predicate positions, of which there are finitely many
    and few, rather than over terms -- which is why it settles immediately
    where a closure over the terms themselves cannot settle at all.
    """
    reachable: Set[Tuple[str, int]] = set()
    for _ in range(len(list(rules)) + 1):
        grew = False
        for stored in rules:
            rule = getattr(stored, "rule", stored)
            produced = {o.variable for o in rule.outputs}
            carried = {
                argument
                for fact in rule.preconditions
                for position, argument in enumerate(fact.args)
                if (fact.predicate, position) in reachable and is_variable(argument)
            }
            unknown = produced | carried
            for fact in rule.effects.add:
                for position, argument in enumerate(fact.args):
                    key = (fact.predicate, position)
                    if argument in unknown and key not in reachable:
                        reachable.add(key)
                        grew = True
        if not grew:
            break
    return reachable


def supply_from(facts: Iterable[Fact]) -> Dict[Tuple[str, int], Set[str]]:
    """Which terms can stand at each argument position of each predicate.

    A variable in `NUMBER(?n)` can only ever be a term some `NUMBER` fact
    holds. Enumerating every constant of the problem for it instead is what
    made grounding exponential -- and, once actions began producing values,
    unbounded: every pass minted an operator per candidate answer, and each of
    those widened the universe for the next pass, so the closure never settled.
    Measured: chains of four actions produced thousands of operators and the
    planner exhausted its node bound without leaving the first two steps.

    This is the value half of the supplier graph, at the resolution that makes
    it useful: not "which predicates can exist" but "which terms can appear
    where".
    """
    supply: Dict[Tuple[str, int], Set[str]] = {}
    for fact in facts:
        for position, argument in enumerate(fact.args):
            supply.setdefault((fact.predicate, position), set()).add(argument)
    return supply


def ground_rule(
    rule: CandidateRule,
    supply: Dict[Tuple[str, int], Set[str]],
    universe: Sequence[str] = (),
    rule_id: Optional[str] = None,
    limit: int = DEFAULT_MAX_OPERATORS,
    invented: Optional[Set[Tuple[str, int]]] = None,
) -> Tuple[List[GroundOperator], bool]:
    """Every instantiation of one rule that could ever apply. (operators, truncated).

    THREE KINDS OF ARGUMENT, AND ONLY ONE OF THEM IS ENUMERATED.

      supplied   a term the problem holds or an action puts there. Enumerated,
                 and only over the terms that can stand where it stands.
      invented   a term some action will produce at runtime. Left OPEN: it has
                 no name yet, so the planner binds it against the state it is
                 actually in, and every occurrence of the action gets its own.
      produced   a value THIS action makes. Neither enumerated nor open --
                 resolved per application, by computing it or by minting an
                 unknown for that occurrence.

    Enumerating the second would mean inventing candidate answers and letting
    the planner keep whichever reached the goal. Enumerating the third would be
    the same mistake one step earlier.
    """
    if rule.action is None:
        return [], False

    invented = invented or set()
    origins = rule.binding_origins()
    variables = sorted(v for v, origin in origins.items()
                       if origin in (BindingOrigin.STATE, BindingOrigin.ACTION_INPUT))

    # THE PRECONDITIONS CONSTRAIN, THE ACTION DOES NOT. What terms may stand in
    # the action literal is the question grounding exists to answer: no state
    # contains MOVE(z, HALL, LAB) before anything offers it. So the action's
    # arguments are narrowed by the preconditions they also appear in, and a
    # variable that appears nowhere else is genuinely unconstrained.
    positions: Dict[str, List[Tuple[str, int]]] = {v: [] for v in variables}
    for fact in rule.preconditions:
        for position, argument in enumerate(fact.args):
            if argument in positions:
                positions[argument].append((fact.predicate, position))

    open_slots = sorted(v for v in variables
                        if any(key in invented for key in positions[v]))
    closed = [v for v in variables if v not in open_slots]

    candidates: List[List[str]] = []
    for variable in closed:
        constrained = [supply.get(key, set()) for key in positions[variable]]
        terms = set.intersection(*constrained) if constrained else set(universe)
        if not terms:
            return [], False
        candidates.append(sorted(terms))

    produced = tuple({
        "variable": output.variable,
        "origin": output.origin.value,
        "function": output.function,
        "producer": output.producer,
        "inputs": list(output.inputs),
    } for output in rule.outputs)

    operators: List[GroundOperator] = []
    for assignment in itertools.product(*candidates):
        if len(operators) >= limit:
            return operators, True

        bindings = dict(zip(closed, assignment))
        action = rule.action.substitute(bindings)
        operators.append(GroundOperator(
            name=action.to_formula(),
            preconditions=tuple(sorted(
                f.substitute(bindings).to_formula() for f in rule.preconditions
            )),
            effects=tuple(sorted(
                f.substitute(bindings).to_formula() for f in rule.effects.add
            )),
            deletes=tuple(sorted(
                f.substitute(bindings).to_formula() for f in rule.effects.delete
            )),
            rule_id=rule_id,
            bindings=tuple(sorted(bindings.items())),
            open_slots=tuple(open_slots),
            outputs=produced,
        ))
    return operators, False


def ground_for_problem(
    rules: Sequence[Any],
    state: Iterable[Fact],
    goal: Iterable[Fact] = (),
    limit: int = DEFAULT_MAX_OPERATORS,
) -> GroundingReport:
    """Ground admissible rules over the terms this problem can produce.

    `rules` are StoredRule records; each is checked for executability here
    rather than trusted, so a caller cannot widen the gate by passing a
    candidate.
    """
    from core.learning.rule_store import EpistemicStatus

    state_facts = list(state)
    goal_facts = list(goal)
    report = GroundingReport(
        constants=sorted(constants_in(state_facts) | constants_in(goal_facts)))
    if not report.constants:
        return report

    # WHAT THIS PROBLEM CAN EVER CONTAIN: what it starts with, plus what some
    # rule asserts. A precondition outside that set is one no state reachable
    # in the search will satisfy.
    #
    # Effect predicates cover values an action produces as well as facts it
    # moves: an output is a term inside an effect, so a rule that computes a
    # quotient supplies QUOTIENT here exactly as a rule that copies one does.
    supplied = {f.predicate for f in state_facts} | {
        f.predicate
        for stored in rules
        for f in getattr(stored, "rule", stored).effects.add
    }

    invented = invented_positions(rules)

    def build(supply) -> GroundingReport:
        built = GroundingReport(constants=list(report.constants))
        remaining = limit
        for stored in rules:
            rule = getattr(stored, "rule", stored)
            rule_id = getattr(stored, "rule_id", None)
            status = getattr(stored, "status", None)

            if status is not None and status is not EpistemicStatus.VALIDATED:
                built.rules_skipped[rule_id or str(rule)] = (
                    f"not executable: {status.value}")
                continue
            if rule.action is None:
                built.rules_skipped[rule_id or str(rule)] = (
                    "no action recorded; the rule describes what follows, not what "
                    "the agent can do")
                continue

            unsatisfiable = sorted(
                {f.predicate for f in rule.preconditions} - supplied)
            if unsatisfiable:
                built.rules_unreachable[rule_id or str(rule)] = (
                    f"requires {', '.join(unsatisfiable)}, which the problem does not "
                    f"supply and no rule asserts; this rule cannot fire in any state "
                    f"the search can reach")

            operators, truncated = ground_rule(rule, supply, report.constants,
                                               rule_id, remaining, invented=invented)
            built.operators.extend(operators)
            built.rules_used.append(rule_id or str(rule))
            remaining -= len(operators)
            if truncated or remaining <= 0:
                built.truncated = True
                logger.warning(
                    "grounding hit the %d-operator bound; the operator set is "
                    "partial and an UNREACHABLE verdict from it is not a proof",
                    limit)
                break
        return built

    # THE CLOSURE OVER PRODUCIBLE TERMS.
    #
    # An action that moves a term puts it somewhere the problem did not have
    # it: nothing starts with AT(z, LAB), and the operator that would use it
    # cannot be enumerated until the term reaches that position. So what one
    # pass produces is admitted to the next, and grounding repeats until
    # nothing new appears.
    #
    # This closes over terms that ALREADY EXIST. Terms an action invents are
    # not admitted here and cannot be: they have no name until the action runs,
    # which is what `open_slots` is for.
    supply = supply_from(state_facts)
    report_body = build(supply)
    for _ in range(DEFAULT_CLOSURE_PASSES):
        widened = supply_from(
            Fact.parse(effect)
            for operator in report_body.operators for effect in operator.effects
            if not operator.open_slots)
        if all(terms <= supply.get(key, set()) for key, terms in widened.items()):
            break
        for key, terms in widened.items():
            supply.setdefault(key, set()).update(terms)
        report_body = build(supply)
    else:
        report_body.closure_converged = False
        logger.warning(
            "the producible-term closure did not settle in %d pass(es); the "
            "operator set may be missing consumers of terms produced late, so "
            "UNREACHABLE from it is not a proof", DEFAULT_CLOSURE_PASSES)

    report_body.constants = report.constants
    report = report_body

    # SAY WHAT THE PLANNER WAS ACTUALLY GIVEN.
    #
    # Grounding returning zero operators is indistinguishable, downstream, from
    # a world in which nothing is possible -- and the planner's verdict
    # inherits that ambiguity silently. Stated here so any UNREACHABLE can be
    # read against the operator set it came from.
    if report.rules_unreachable:
        logger.warning(
            "Grounding: %d rule(s) can never fire — the operator set cannot "
            "predict part of this world, so UNREACHABLE from it is not a proof. "
            "%s",
            len(report.rules_unreachable),
            "; ".join(f"{rid}: {why}" for rid, why in report.rules_unreachable.items()))

    if not report.operators:
        logger.warning(
            "Grounding produced NO operators from %d rule(s) — the planner "
            "cannot reach any goal from an empty operator set, so UNREACHABLE "
            "means 'nothing was offered', not 'nothing is possible'. Skipped: %s",
            len(rules),
            "; ".join(f"{rid}: {why}" for rid, why in report.rules_skipped.items())
            or "no reason recorded")
    else:
        logger.info(
            "Grounding: %d rule(s) in, %d used, %d skipped, %d operator(s), "
            "complete=%s%s",
            len(rules), len(report.rules_used), len(report.rules_skipped),
            len(report.operators), report.complete,
            "" if not report.rules_skipped else " | skipped: " + "; ".join(
                f"{rid}: {why}" for rid, why in report.rules_skipped.items()))

    return report
