#!/usr/bin/env python3
"""Acquiring an executable rule from demonstrations, without a model.

The capability this exists to add: the substrate can already *execute* symbolic
knowledge with zero model calls, and could not previously *acquire* any. The
only thing here called induction before was lexical -- premises grouped by
Jaccard overlap, "pattern" being whichever words appeared in 70% of them --
which cannot yield anything executable.

Deliberately separate from LogicalInferenceEngine. That engine executes
accepted rules; this one proposes candidates. Merging them would let the
executor become its own source of epistemic truth, so a rule it invented would
be indistinguishable from one the evidence forced.

The algorithm is Plotkin's least general generalization over positive examples,
pruned by negatives and then minimized. It is deterministic: the same
demonstrations in any order produce the same rule, which is what makes a failed
experiment diagnosable rather than merely disappointing.

Representation is ground-term (predicate + argument tuple) rather than the
LogicalFormulaParser's AST, which returns ('atom', 'VEX(a,b)') -- a single
opaque string. That is right for a propositional backend and useless for
generalization, which has to align argument positions across examples. Facts
render back to that surface syntax via to_formula(), so a learned rule stays
consumable by the existing inference machinery.

No arithmetic and no numeric sorts: a first-order relational language keeps a
failed test attributable to the learner rather than to term typing, state
mutation or SMT encoding all at once.
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from core.learning.learning_policy import guard_learning
from core.reasoning.unification import VARIABLE_PREFIX as _VARIABLE_PREFIX
from core.reasoning.unification import (is_variable, match_body, match_literal,
                                        unify)
from core.reasoning.value_authority import (arity, catalogue, evaluate,
                                            is_commutative)

logger = logging.getLogger(__name__)

#: Unification is a primitive BELOW both owners -- the learning authority
#: (`learning_authority.SubstrateLearning`) and the reasoning subsystem -- so it
#: belongs to neither. `core/reasoning/unification.py` is the single
#: implementation; these names are re-exported because many callers already
#: import them from here.
#:
#: Duplicating the algorithm is what let a substring-matching "deduction"
#: coexist with this one and disagree with it about whether a rule applies.
VARIABLE_PREFIX = _VARIABLE_PREFIX

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: TERMS MAY BE NUMBERS. Arithmetic was deferred on purpose while relational
#: induction was proved -- admitting typed terms and numeric sorts early would
#: have given a failed induction test six possible explanations instead of one.
#: That proof is done (EDU-01 through EDU-11), so the restriction is lifted
#: HERE, in the induction owner, rather than by standing a second numeric
#: pattern-learner beside it: "what has Torin generalized" must keep exactly
#: one answer.
#:
#: The language stays FUNCTION-FREE. A number is a constant term, not an
#: operator, so arithmetic enters as background RELATIONS (PLUS(2,3,5)) and a
#: learned rule remains a Horn clause over literals.
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


def is_number(term: str) -> bool:
    return bool(_NUMBER.match(str(term)))


def canonical_term(term: str) -> str:
    """One spelling per value, so 5, 5.0 and 05 are the same term.

    Without this a rule learned over `5` would not unify with a fact stating
    `5.0`, and two identical rules would carry different semantic fingerprints.
    """
    text = str(term)
    if not is_number(text):
        return text
    value = float(text)
    return str(int(value)) if value.is_integer() else repr(value)


class InductionStatus(Enum):
    """What the evidence supported. Not every outcome is a rule.

    A learner that always returns something cannot express "these
    demonstrations do not determine an answer", and an experiment built on it
    cannot distinguish a rule that was learned from one that was guessed.
    """

    RULE_LEARNED = "rule_learned"
    MULTIPLE_HYPOTHESES = "multiple_hypotheses"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    NO_RULE = "no_rule"


@dataclass(frozen=True, order=True)
class Fact:
    """A ground or variabilized relational atom: VEX(a, b), VEX(?X, ?Y)."""

    predicate: str
    args: Tuple[str, ...] = ()

    def __post_init__(self):
        if not _IDENT.match(self.predicate):
            raise ValueError(f"predicate {self.predicate!r} is not an identifier")
        canonical = []
        for arg in self.args:
            if is_variable(arg):
                if not _IDENT.match(arg[len(VARIABLE_PREFIX):]):
                    raise ValueError(f"variable {arg!r} is not named by an identifier")
                canonical.append(arg)
                continue
            if is_number(arg):
                canonical.append(canonical_term(arg))
                continue
            if not _IDENT.match(str(arg)):
                raise ValueError(
                    f"term {arg!r} is neither an identifier, a number, nor a variable")
            canonical.append(str(arg))
        object.__setattr__(self, "args", tuple(canonical))

    @property
    def arity(self) -> int:
        return len(self.args)

    @property
    def signature(self) -> Tuple[str, int]:
        return (self.predicate, self.arity)

    @property
    def is_ground(self) -> bool:
        return not any(is_variable(a) for a in self.args)

    @property
    def variables(self) -> Set[str]:
        return {a for a in self.args if is_variable(a)}

    def substitute(self, bindings: Dict[str, str]) -> "Fact":
        return Fact(self.predicate, tuple(bindings.get(a, a) for a in self.args))

    def to_formula(self) -> str:
        """Surface syntax accepted by LogicalFormulaParser."""
        return f"{self.predicate}({', '.join(self.args)})" if self.args else self.predicate

    @classmethod
    def parse(cls, text: str) -> "Fact":
        text = text.strip()
        if "(" not in text:
            return cls(text)
        if not text.endswith(")"):
            raise ValueError(f"unbalanced parentheses in {text!r}")
        predicate, _, rest = text.partition("(")
        args = [a.strip() for a in rest[:-1].split(",")] if rest[:-1].strip() else []
        return cls(predicate.strip(), tuple(args))

    def __str__(self) -> str:
        return self.to_formula()


@dataclass
class TrainingExample:
    """One demonstration: a state, an action taken in it, and the state after.

    ``label`` is the teacher's verdict, not the learner's. A negative example is
    a demonstration that the action did NOT have the consequent -- the only
    thing that can refute an overgeneral rule.
    """

    before: Tuple[Fact, ...]
    action: Optional[Fact] = None
    after: Tuple[Fact, ...] = ()
    positive: bool = True
    evidence_id: Optional[str] = None

    def __post_init__(self):
        self.before = tuple(self.before)
        self.after = tuple(self.after)
        for fact in (*self.before, *self.after, *((self.action,) if self.action else ())):
            if not fact.is_ground:
                raise ValueError(f"demonstrations must be ground: {fact}")

    @property
    def antecedent(self) -> FrozenSet[Fact]:
        """Everything true when the action was taken, the action included."""
        return frozenset(self.before) | ({self.action} if self.action else frozenset())

    @property
    def observed_effects(self) -> "RuleEffects":
        """What the action changed, in both directions.

        Symmetric by construction: a fact present after and not before was
        added, one present before and not after was retracted. Deriving both
        from the same difference is what keeps a demonstration a description of
        a state change rather than of a monotonic accumulation.
        """
        before, after = frozenset(self.before), frozenset(self.after)
        return RuleEffects(add=after - before, delete=before - after)


@dataclass(frozen=True)
class RuleEffects:
    """What a rule asserts happens: facts added, facts retracted.

    Delete effects are represented from the outset even while most learned
    rules carry none. Without them a chained transition is theorem
    accumulation -- an entity ends up in two rooms at once -- and retrofitting
    them later would mean migrating every rule already persisted.
    """

    add: FrozenSet[Fact] = frozenset()
    delete: FrozenSet[Fact] = frozenset()

    def __post_init__(self):
        object.__setattr__(self, "add", frozenset(self.add))
        object.__setattr__(self, "delete", frozenset(self.delete))

    def __bool__(self) -> bool:
        return bool(self.add or self.delete)

    @property
    def facts(self) -> FrozenSet[Fact]:
        return self.add | self.delete

    @property
    def variables(self) -> Set[str]:
        return set().union(*(f.variables for f in self.facts)) if self.facts else set()

    def substitute(self, bindings: Dict[str, str]) -> "RuleEffects":
        return RuleEffects(
            add=frozenset(f.substitute(bindings) for f in self.add),
            delete=frozenset(f.substitute(bindings) for f in self.delete),
        )


class BindingOrigin(Enum):
    """How a variable in an operator came to have a value.

    Range restriction was never the problem; the definition of "grounded" was.
    A rule may still not conclude about a term that came from nowhere -- that
    is what UNBOUND exists to refuse -- but a value the ACTION produces has a
    provenance, and pretending it does not is what made computation
    inexpressible. A STRIPS operator moves facts around; it cannot say that
    dividing twenty by four yields a five that no fact mentioned beforehand.

    Every one of these is a traceable account of where a value came from, which
    is also what makes a derivation explainable afterwards: 5 <- q <- DIVIDE
    output <- numerator 20, denominator 4.
    """

    STATE = "state"                  # bound by matching a body literal
    ACTION_INPUT = "action_input"    # bound by an argument of the action
    ACTION_OUTPUT = "action_output"  # produced by the action; value not predictable
    DERIVED = "derived"              # computed from already-grounded terms
    UNBOUND = "unbound"              # nothing accounts for it -- never executable


@dataclass(frozen=True)
class OutputBinding:
    """A value the action creates, and the account of where it comes from.

    DELIBERATELY NOT A PRECONDITION. "I need this fact in order to act" and
    "acting will produce this value" are different claims, and the body held
    both. Collapsing them meant an operator could only ever conclude about
    values the world had already published -- so a divider had to announce its
    quotient before being asked for it, which is to say the answer had to exist
    before the question.

    DERIVED is the stronger claim and the falsifiable one: it names a function
    and its inputs, so the value is predictable and a plan through it can be
    proved. ACTION_OUTPUT says only that acting yields a value -- true of a
    network read, and unfalsifiable about WHICH value -- so a plan through it
    is conditional and can never prove an exact-value goal.
    """

    variable: str
    origin: "BindingOrigin"
    producer: Optional[str] = None
    function: Optional[str] = None
    inputs: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "inputs", tuple(self.inputs))
        if not is_variable(self.variable):
            raise ValueError(f"an output binds a variable; {self.variable!r} is not one")
        if self.origin is BindingOrigin.DERIVED:
            if arity(self.function or "") != len(self.inputs):
                raise ValueError(
                    f"{self.function!r} does not take {len(self.inputs)} argument(s); "
                    f"the value authority is what knows, and it was not asked")
        elif self.origin is BindingOrigin.ACTION_OUTPUT:
            if not self.producer:
                raise ValueError("an action output must name the action that produces it")
        else:
            raise ValueError(f"{self.origin} does not produce a value")

    @property
    def is_predictable(self) -> bool:
        """Whether the value can be known before the action runs."""
        return self.origin is BindingOrigin.DERIVED

    def substitute(self, bindings: Dict[str, str]) -> "OutputBinding":
        return OutputBinding(
            variable=bindings.get(self.variable, self.variable),
            origin=self.origin, producer=self.producer, function=self.function,
            inputs=tuple(bindings.get(i, i) for i in self.inputs))

    def __str__(self) -> str:
        if self.origin is BindingOrigin.DERIVED:
            return f"{self.variable} := {self.function}({', '.join(self.inputs)})"
        return f"{self.variable} := {self.producer}()"


@dataclass(frozen=True)
class CandidateRule:
    """A range-restricted function-free rule: body -> add / delete effects.

    ``action`` names which body literal is the thing the agent DOES, as opposed
    to a condition that merely holds. Both are body literals and both must be
    satisfied, so this changes nothing about when the rule fires -- but without
    it a planner cannot enumerate the actions available to it, because MOVE and
    OPEN are indistinguishable. It is None for rules learned from observation
    with no action taken.
    """

    body: FrozenSet[Fact]
    effects: RuleEffects
    action: Optional[Fact] = None
    outputs: Tuple[OutputBinding, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "outputs", tuple(self.outputs))
        if self.action is not None and self.action not in self.body:
            raise ValueError(
                f"action {self.action} is not among the rule's preconditions; "
                f"an action the rule does not require cannot have produced its "
                f"effects"
            )
        bound = set().union(*(f.variables for f in self.body)) if self.body else set()
        seen: Set[str] = set()
        for output in self.outputs:
            if output.variable in bound:
                raise ValueError(
                    f"{output.variable} is already bound by the body; an output is a "
                    f"value the action CREATES, not one it reads")
            if output.variable in seen:
                raise ValueError(f"{output.variable} is produced twice")
            seen.add(output.variable)

    @property
    def preconditions(self) -> FrozenSet[Fact]:
        """Body literals that are conditions rather than the action itself."""
        return self.body - ({self.action} if self.action else frozenset())

    def binding_origins(self) -> Dict[str, "BindingOrigin"]:
        """Where every variable in this operator gets its value.

        The order is the order of provenance: the action's own arguments, then
        what matching the body binds, then what the action produces. An output
        may be DERIVED only from terms already grounded above it, so a chain of
        derivations cannot close on itself.
        """
        origins: Dict[str, BindingOrigin] = {}
        if self.action is not None:
            for arg in self.action.args:
                if is_variable(arg):
                    origins[arg] = BindingOrigin.ACTION_INPUT
        for fact in self.body:
            for variable in fact.variables:
                origins.setdefault(variable, BindingOrigin.STATE)
        for output in self.outputs:
            if output.origin is BindingOrigin.DERIVED and any(
                is_variable(i) and origins.get(i) in (None, BindingOrigin.UNBOUND)
                for i in output.inputs
            ):
                origins[output.variable] = BindingOrigin.UNBOUND
                continue
            origins[output.variable] = output.origin
        for variable in self.effects.variables:
            origins.setdefault(variable, BindingOrigin.UNBOUND)
        return origins

    @property
    def is_range_restricted(self) -> bool:
        """Every effect variable has an account of where its value comes from.

        RANGE RESTRICTION WITH VALUE PROVENANCE, NOT RELAXED RANGE RESTRICTION.
        `P(?x) -> MAGIC(?y)` is still refused: nothing accounts for ?y. What
        changed is that "bound by the body" is no longer the only account
        available -- an action's declared output is one too, and a term derived
        from already-grounded terms is another.

        The old definition made computation unrepresentable rather than
        unlearnable. An action that divides a total by a count produces a value
        no pre-state fact names, so under "every effect variable appears in the
        body" the correct rule was inexpressible, and induction reported
        NO_RULE -- correctly, for a language that could not say it.
        """
        origins = self.binding_origins()
        return all(origins.get(v) not in (None, BindingOrigin.UNBOUND)
                   for v in self.effects.variables)

    def to_formula(self) -> str:
        """A projection for reading and for the existing inference machinery.

        Never the canonical form: the structure is, so that adding negation,
        typing or richer terms does not mean re-parsing learned cognition out
        of a string it was trapped in.
        """
        antecedent = " ∧ ".join(f.to_formula() for f in sorted(self.body))
        consequent = " ∧ ".join(f.to_formula() for f in sorted(self.effects.add))
        retracted = " ∧ ".join(f.to_formula() for f in sorted(self.effects.delete))
        rendered = f"{antecedent} → {consequent}" if consequent else antecedent
        if retracted:
            rendered = f"{rendered} ⊖ {retracted}"
        if self.outputs:
            produced = ", ".join(str(o) for o in self.outputs)
            rendered = f"{rendered} ⟨{produced}⟩"
        return rendered

    def __str__(self) -> str:
        return self.to_formula()


@dataclass
class InductionResult:
    """What was learned, what supported it, and what it was tested against."""

    status: InductionStatus
    candidates: List[CandidateRule] = field(default_factory=list)
    positive_coverage: int = 0
    negative_coverage: int = 0
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def rule(self) -> Optional[CandidateRule]:
        """The learned rule, and only when the evidence determined one."""
        return self.candidates[0] if self.status is InductionStatus.RULE_LEARNED else None


# --------------------------------------------------------------------------
# Matching: does a rule apply to a state, and under what binding?
# --------------------------------------------------------------------------

def arithmetic_background(values: Sequence[Any]) -> FrozenSet[Fact]:
    """The arithmetic relating each consecutive pair of `values`.

    ARITHMETIC AS BACKGROUND RELATIONS, NOT AS FUNCTIONS. A learned rule stays
    a function-free Horn clause -- `PLUS(?X, 4, ?Y)` is a literal like any
    other, so unification, canonical form and the semantic fingerprint need no
    special case for it. Adding `+` as an operator instead would have meant
    typed terms and numeric sorts throughout, which is exactly what the
    original deferral was avoiding.

    CONSECUTIVE PAIRS ONLY, AND THIS IS NOT AN OPTIMISATION. Supplying every
    pair among the values put four PLUS literals in each state, and Plotkin's
    LGG pairs every same-predicate literal with every other -- four against
    four gives sixteen, and the generalisation came back with a 22-literal body
    that blew MAX_BODY_LITERALS and induced nothing. Measured. The relations a
    demonstration carries are the ones that hold ACROSS ITS OWN TRANSITION.

    It supplies both the additive and (when exact) the multiplicative relation
    and does not choose between them. Which one generalises -- which keeps a
    CONSTANT second argument across examples -- is what induction is for.
    """
    numbers = [canonical_term(str(v)) for v in values]
    if any(not is_number(n) for n in numbers):
        return frozenset()

    facts = set()
    for left, right in zip(numbers, numbers[1:]):
        a, b = float(left), float(right)
        facts.add(Fact("PLUS", (left, canonical_term(str(b - a)), right)))
        if abs(a) > 1e-12:
            ratio = b / a
            if abs(ratio - round(ratio)) < 1e-12:
                facts.add(Fact("TIMES", (left, canonical_term(str(ratio)), right)))
    return frozenset(facts)


def _extend(bindings: Dict[str, str], pattern: Fact, ground: Fact) -> Optional[Dict[str, str]]:
    """Retained name; the algorithm is `unification.unify`. Note the argument
    order differs -- `unify` takes the bindings last, as an optional extension."""
    return unify(pattern, ground, bindings)


def resolve_outputs(
    rule: CandidateRule, bindings: Dict[str, str]
) -> Optional[Dict[str, str]]:
    """Extend a body binding with the values the action produces.

    A DERIVED output is computed by asking the value authority, so the answer
    is the same one the planner and the world will get. None when it refuses --
    a division by zero is not a zero, and an operator resting on it does not
    apply.

    An ACTION_OUTPUT is left as a variable ON PURPOSE. The rule does not claim
    to know what a network read returns, and substituting anything for it would
    be inventing the value.
    """
    resolved = dict(bindings)
    for output in rule.outputs:
        if output.origin is not BindingOrigin.DERIVED:
            continue
        value = evaluate(output.function or "",
                         [resolved.get(i, i) for i in output.inputs])
        if value is None:
            return None
        resolved[output.variable] = value
    return resolved


def derives(rule: CandidateRule, example: TrainingExample) -> bool:
    """Whether what the rule asserts actually happened in this demonstration.

    A MATCH, NOT A SUBSET. The two are the same test while every asserted
    effect is ground, and they differ exactly where an ACTION_OUTPUT leaves a
    variable in the consequent: `TEXT(?X0)` is a subset of no world, so a rule
    that says "reading produces some text" was contradicted by every
    demonstration of reading producing text.

    THE ONE PLACE THIS IS DECIDED. Induction asks it of the demonstrations that
    proposed a rule and the rule store asks it of the held-out ones that judge
    it. Two copies is how a rule came to be learnable and unvalidatable at the
    same time.
    """
    instances = applies(rule, example)
    if not instances:
        return False
    observed = example.observed_effects
    return all(match_body(i.add, observed.add) and match_body(i.delete, observed.delete)
               for i in instances)


def contradicted_by(rule: CandidateRule, example: TrainingExample) -> bool:
    """Whether the rule asserts a change this demonstration showed did not happen."""
    after = frozenset(example.after)
    for asserted in applies(rule, example):
        if not match_body(asserted.add, after):
            return True
        if any(match_literal(f, after) for f in asserted.delete):
            return True
    return False


def applies(rule: CandidateRule, example: TrainingExample) -> List[RuleEffects]:
    """The effect instances this rule asserts for the example's antecedent."""
    instances = []
    for bindings in match_body(rule.body, example.antecedent):
        resolved = resolve_outputs(rule, bindings)
        if resolved is None:
            continue
        instances.append(rule.effects.substitute(resolved))
    return instances


def successor_state(
    state: FrozenSet[Fact], effects: Iterable[RuleEffects]
) -> FrozenSet[Fact]:
    """Apply ground effects to a state. Deletes resolve before adds.

    The order matters for a rule that retracts and re-asserts the same
    predicate: applying adds first would let the delete undo the effect the
    rule exists to produce.
    """
    resulting = set(state)
    for effect in effects:
        resulting -= effect.delete
    for effect in effects:
        resulting |= effect.add
    return frozenset(resulting)


# --------------------------------------------------------------------------
# Anti-unification (Plotkin's LGG)
# --------------------------------------------------------------------------

class _Generalizer:
    """Shared substitution table across one generalization.

    The table is what makes the result a generalization rather than a rename:
    the same pair of constants must map to the same variable everywhere it
    occurs, so NAL(a)/NAL(c) and VEX(a,b)/VEX(c,d) agree that a/c is ?X.
    """

    def __init__(self):
        self._pairs: Dict[Tuple[str, str], str] = {}

    def term(self, left: str, right: str) -> str:
        if left == right:
            return left
        key = (left, right)
        if key not in self._pairs:
            self._pairs[key] = f"{VARIABLE_PREFIX}V{len(self._pairs)}"
        return self._pairs[key]

    def fact(self, left: Fact, right: Fact) -> Optional[Fact]:
        if left.signature != right.signature:
            return None
        return Fact(
            left.predicate,
            tuple(self.term(a, b) for a, b in zip(left.args, right.args)),
        )


def _canonical(
    body: Iterable[Fact], effects: RuleEffects, action: Optional[Fact] = None,
    outputs: Sequence[OutputBinding] = (),
) -> CandidateRule:
    """Rename variables by first appearance so equal rules compare equal.

    Effects are renamed before the body so the naming is driven by what the
    rule concludes, not by the incidental sort order of its preconditions.
    Without this, two identical rules learned from examples in a different
    order carry different variable names and the version space never collapses.
    """
    order: Dict[str, str] = {}

    def rename(fact: Fact) -> Fact:
        args = []
        for arg in fact.args:
            if is_variable(arg):
                args.append(order.setdefault(arg, f"{VARIABLE_PREFIX}X{len(order)}"))
            else:
                args.append(arg)
        return Fact(fact.predicate, tuple(args))

    renamed_effects = RuleEffects(
        add=frozenset(rename(f) for f in sorted(effects.add)),
        delete=frozenset(rename(f) for f in sorted(effects.delete)),
    )
    renamed_body = frozenset(rename(f) for f in sorted(body))
    # The action is renamed under the same table, and retained only while it is
    # still one of the preconditions -- a minimization that drops it is the
    # hypothesis that the effect occurs without the agent acting.
    renamed_action = rename(action) if action is not None else None
    if renamed_action is not None and renamed_action not in renamed_body:
        renamed_action = None
    # Outputs last, under the completed table: an output's variable is named by
    # the effect that consumes it and its inputs by the body that binds them,
    # so both halves must already have been renamed.
    renamed_outputs = tuple(
        o.substitute({k: v for k, v in order.items()}) for o in outputs)
    return CandidateRule(
        body=renamed_body, effects=renamed_effects, action=renamed_action,
        outputs=renamed_outputs,
    )


def _generalize_facts(
    gen: "_Generalizer", left: Iterable[Fact], right: Iterable[Fact]
) -> Set[Fact]:
    """Plotkin's pairwise generalization of two literal sets."""
    out: Set[Fact] = set()
    for a, b in itertools.product(sorted(left), sorted(right)):
        generalized = gen.fact(a, b)
        if generalized is not None:
            out.add(generalized)
    return out


def generalize(left: CandidateRule, right: CandidateRule) -> Optional[CandidateRule]:
    """The least general rule subsuming both, or None if the effects disagree.

    Body and effects share one substitution table, so an entity generalized in
    the conclusion is the same variable in the precondition that bound it.
    """
    gen = _Generalizer()
    add = _generalize_facts(gen, left.effects.add, right.effects.add)
    delete = _generalize_facts(gen, left.effects.delete, right.effects.delete)
    if bool(add) != bool(left.effects.add and right.effects.add):
        return None
    if not add and not delete:
        return None

    body = _generalize_facts(gen, left.body, right.body)

    # Generalized under the same table, so the action's arguments agree with the
    # preconditions that bound them. Two demonstrations that took different
    # actions have no common action, and the rule keeps none.
    action = None
    if left.action is not None and right.action is not None:
        action = gen.fact(left.action, right.action)

    return _canonical(body, RuleEffects(add=add, delete=delete), action)


# --------------------------------------------------------------------------
# The learner
# --------------------------------------------------------------------------

def _subsumes(general: FrozenSet[Fact], specific: FrozenSet[Fact]) -> bool:
    """Whether `general` θ-subsumes `specific`: some renaming maps it inside.

    Uses the canonical unifier, treating the specific body as the ground-ish
    state a pattern must match. A variable may bind to another variable, which
    is exactly what makes this modulo renaming.
    """
    if not general:
        return True
    if len(general) > len(specific):
        return False
    return bool(match_body(general, specific))


class RuleInducer:
    """Learns function-free Horn rules from state-action-state demonstrations.

    Proposes only. Nothing here decides that a candidate is fit to execute;
    that judgement belongs to whatever holds the rule store, which weighs
    held-out evidence this class never sees.
    """

    #: A body large enough to be a transcript of one demonstration rather than
    #: a generalization of several. Reached only when examples share almost
    #: nothing, and enumeration of its subsets would not terminate usefully.
    #: Bounds the subset enumeration in `_minimal_hypotheses`, which is 2**n.
    #:
    #: NOT a claim about how large a real rule may be. At 12 a third
    #: demonstration could push the LGG to 14 literals and induction returned
    #: INSUFFICIENT_EVIDENCE -- more evidence made learning fail, reported as a
    #: shortage of shared structure. Plotkin's LGG is multiplicative, so bodies
    #: grow with each demonstration before minimization shrinks them again.
    #:
    #: A greedy reduction was tried here and REVERTED: it picks one minimal body
    #: and discards the competing ones, so underdetermined demonstrations came
    #: back RULE_LEARNED instead of MULTIPLE_HYPOTHESES. Manufacturing certainty
    #: to fit under a performance bound is the worst possible trade, and the
    #: version-space tests caught it.
    #:
    #: 16 keeps the enumeration at 65_536 subsets, which is affordable.
    MAX_BODY_LITERALS = 16

    def induce(
        self,
        examples: Sequence[TrainingExample],
        target_predicate: Optional[str] = None,
    ) -> InductionResult:
        guard_learning("rule induction")

        positives = [e for e in examples if e.positive]
        negatives = [e for e in examples if not e.positive]

        if len(positives) < 2:
            return InductionResult(
                status=InductionStatus.INSUFFICIENT_EVIDENCE,
                detail=(
                    f"{len(positives)} positive demonstration(s); generalization "
                    f"needs at least 2 to have anything to align"
                ),
                supporting_evidence=self._ids(positives),
            )

        seeds, conflict = self._seed_rules(positives, target_predicate)
        if conflict:
            return InductionResult(
                status=InductionStatus.CONTRADICTORY_EVIDENCE,
                detail=conflict,
                supporting_evidence=self._ids(positives),
            )
        if not seeds:
            return InductionResult(
                status=InductionStatus.NO_RULE,
                detail="no demonstration produced an effect to explain",
                supporting_evidence=self._ids(positives),
            )

        lgg = seeds[0]
        for seed in seeds[1:]:
            generalized = generalize(lgg, seed)
            if generalized is None:
                return InductionResult(
                    status=InductionStatus.CONTRADICTORY_EVIDENCE,
                    detail=(
                        f"demonstrations assert different consequents "
                        f"({lgg.to_formula()} vs {seed.to_formula()})"
                    ),
                    supporting_evidence=self._ids(positives),
                )
            lgg = generalized

        if len(lgg.body) > self.MAX_BODY_LITERALS:
            return InductionResult(
                status=InductionStatus.INSUFFICIENT_EVIDENCE,
                detail=(
                    f"generalization retained {len(lgg.body)} literals — the "
                    f"demonstrations share too little structure to separate the "
                    f"rule from its examples"
                ),
                supporting_evidence=self._ids(positives),
            )

        # WHERE DID THAT VALUE COME FROM? An effect may carry a term no body
        # literal binds because the action COMPUTED it. Which computation is
        # not asserted here and is not hand-written per action: the value
        # authority is searched for a function over already-grounded terms that
        # accounts for the observed value in EVERY demonstration.
        lgg, ambiguous = self._explain_outputs(lgg, positives)
        if ambiguous:
            return InductionResult(
                status=InductionStatus.MULTIPLE_HYPOTHESES,
                candidates=[],
                positive_coverage=len(positives),
                supporting_evidence=self._ids(positives),
                detail="; ".join(
                    f"{variable} is explained equally well by "
                    + " and ".join(str(o) for o in options)
                    for variable, options in ambiguous),
            )

        # RANGE RESTRICTION IS CHECKED HERE, ON THE WHOLE GENERALIZATION,
        # because its failure has a cause worth naming. Every subset of a body
        # binds no more than the body does, so if the LGG concludes about a
        # term nothing in it binds, no minimization can rescue it -- and
        # `_minimal_hypotheses` would discard all of them silently and return
        # empty, which the caller reads as "refuted by a counter-demonstration".
        #
        # Those are different findings. Refutation says the hypothesis is
        # wrong. This says the demonstrations show the world producing a value
        # nothing in the state named beforehand, and a function-free rule
        # cannot predict a value it must compute. Reporting the first for the
        # second sent a diagnosis to the wrong place: observed on TAKE_COUNT,
        # whose effect includes a quotient the divider only publishes once its
        # operands are loaded.
        if not lgg.is_range_restricted:
            bound = set().union(*(f.variables for f in lgg.body)) if lgg.body else set()
            unbound = sorted(lgg.effects.variables - bound)
            return InductionResult(
                status=InductionStatus.NO_RULE,
                detail=(
                    f"the generalization concludes about {', '.join(unbound)}, "
                    f"which nothing in its body binds — the demonstrations show a "
                    f"value the state did not name before the action, and a "
                    f"function-free rule cannot predict a value it must compute"),
                supporting_evidence=self._ids(positives),
                positive_coverage=len(positives),
            )

        surviving = self._minimal_hypotheses(lgg, positives, negatives)
        if not surviving:
            return InductionResult(
                status=InductionStatus.NO_RULE,
                detail=(
                    "every generalization of these demonstrations also covers a "
                    "counter-demonstration"
                ),
                supporting_evidence=self._ids(positives),
                contradicting_evidence=self._ids(negatives),
                negative_coverage=len(negatives),
            )

        status = (
            InductionStatus.RULE_LEARNED if len(surviving) == 1
            else InductionStatus.MULTIPLE_HYPOTHESES
        )
        detail = "" if len(surviving) == 1 else (
            f"{len(surviving)} rules explain these demonstrations equally well; "
            f"a demonstration separating them would decide"
        )
        return InductionResult(
            status=status,
            candidates=surviving,
            positive_coverage=len(positives),
            negative_coverage=0,
            supporting_evidence=self._ids(positives),
            contradicting_evidence=self._ids(negatives),
            detail=detail,
        )

    # -------------------------------------------------------------- internals

    @staticmethod
    def _ids(examples: Sequence[TrainingExample]) -> List[str]:
        """Evidence identities, deduplicated.

        Ten derived copies of one demonstration are one root observation, so a
        repeated evidence_id must not inflate support.
        """
        seen: List[str] = []
        for example in examples:
            if example.evidence_id and example.evidence_id not in seen:
                seen.append(example.evidence_id)
        return seen

    def _seed_rules(
        self, positives: Sequence[TrainingExample], target_predicate: Optional[str]
    ) -> Tuple[List[CandidateRule], str]:
        """One maximally-specific rule per demonstration: its own antecedent."""
        seeds: List[CandidateRule] = []
        for example in positives:
            observed = example.observed_effects
            if target_predicate is not None:
                observed = RuleEffects(
                    add=frozenset(f for f in observed.add if f.predicate == target_predicate),
                    delete=frozenset(f for f in observed.delete if f.predicate == target_predicate),
                )
            if not observed:
                continue
            seeds.append(_canonical(example.antecedent, observed, example.action))

        signatures = {
            (frozenset(f.signature for f in s.effects.add),
             frozenset(f.signature for f in s.effects.delete))
            for s in seeds
        }
        if len(signatures) > 1:
            return [], (
                "demonstrations assert unrelated consequents: "
                + "; ".join(
                    sorted(
                        "+" + ",".join(sorted(p for p, _ in add))
                        + ("/-" + ",".join(sorted(p for p, _ in dele)) if dele else "")
                        for add, dele in signatures
                    )
                )
            )
        return seeds, ""

    def _explain_outputs(
        self, lgg: CandidateRule, positives: Sequence[TrainingExample]
    ) -> Tuple[CandidateRule, List[Tuple[str, List[OutputBinding]]]]:
        """Account for effect terms the body does not bind.

        Returns the rule with its outputs attached, and any variable the
        evidence explains in more than one way. Two functions that both
        reproduce every observed value are a genuine ambiguity -- 4/2 and 4-2
        are both 2 -- and demonstrations with different numbers separate them.

        A variable no function explains becomes an ACTION_OUTPUT, but only
        where an action was taken. That is the weaker hypothesis and it is
        chosen only when the stronger one is unavailable, which is not the same
        as choosing between rivals: a DERIVED binding predicts WHICH value
        appears and an ACTION_OUTPUT predicts only that one does, so the first
        entails the second. Preferring it keeps the falsifiable claim, and the
        next demonstration can still refute it. Where nothing acted, nothing
        produced the value and the rule stays unlearnable.
        """
        origins = lgg.binding_origins()
        unexplained = sorted(v for v in lgg.effects.variables
                             if origins.get(v) in (None, BindingOrigin.UNBOUND))
        if not unexplained:
            return lgg, []

        tables = []
        for example in positives:
            table = self._term_bindings(lgg, example)
            if table is None:
                return lgg, []
            tables.append(table)

        grounded = sorted(v for v, origin in origins.items()
                          if origin in (BindingOrigin.STATE, BindingOrigin.ACTION_INPUT))
        outputs: List[OutputBinding] = []
        ambiguous: List[Tuple[str, List[OutputBinding]]] = []

        for variable in unexplained:
            if any(variable not in table for table in tables):
                continue
            explanations = [
                OutputBinding(variable, BindingOrigin.DERIVED,
                              function=function, inputs=inputs)
                for function in catalogue()
                for inputs in itertools.product(grounded, repeat=arity(function) or 0)
                # One spelling per hypothesis for a commutative function; see
                # the value authority on why the mirror image is not a rival.
                if not (is_commutative(function) and list(inputs) != sorted(inputs))
                if all(evaluate(function, [table[i] for i in inputs]) == table[variable]
                       for table in tables)
            ]
            if len(explanations) == 1:
                outputs.append(explanations[0])
            elif explanations:
                ambiguous.append((variable, explanations))
            elif lgg.action is not None:
                outputs.append(OutputBinding(variable, BindingOrigin.ACTION_OUTPUT,
                                             producer=lgg.action.predicate))

        if ambiguous or not outputs:
            return lgg, ambiguous
        return CandidateRule(body=lgg.body, effects=lgg.effects, action=lgg.action,
                             outputs=tuple(outputs)), []

    @staticmethod
    def _term_bindings(
        lgg: CandidateRule, example: TrainingExample
    ) -> Optional[Dict[str, str]]:
        """What every variable of the rule stood for in this demonstration.

        None where the demonstration does not settle it. A body or an effect
        that matches two ways leaves the variable's value ambiguous, and an
        explanation fitted to one of two readings is fitted to a coin toss.
        """
        solutions = match_body(lgg.body, example.antecedent)
        if len(solutions) != 1:
            return None
        bindings = solutions[0]
        observed = example.observed_effects
        for facts, against in ((sorted(lgg.effects.add), observed.add),
                               (sorted(lgg.effects.delete), observed.delete)):
            for fact in facts:
                extended = match_literal(fact, against, bindings)
                if len(extended) != 1:
                    return None
                bindings = extended[0]
        return bindings

    def _minimal_hypotheses(
        self,
        lgg: CandidateRule,
        positives: Sequence[TrainingExample],
        negatives: Sequence[TrainingExample],
    ) -> List[CandidateRule]:
        """Every subset-minimal body that keeps the positives and excludes the
        negatives.

        More than one surviving hypothesis is a real finding rather than a
        failure to choose: it means the demonstrations underdetermine the rule,
        and picking one arbitrarily would manufacture a confidence the evidence
        does not support.
        """
        literals = sorted(lgg.body)
        survivors: List[CandidateRule] = []

        for size in range(len(literals) + 1):
            for subset in itertools.combinations(literals, size):
                # The outputs travel with every subset, and a subset that drops
                # the literal binding a derived output's input makes that output
                # UNBOUND -- so the range-restriction check below removes it
                # without minimization needing to know what an output is.
                candidate = _canonical(subset, lgg.effects, lgg.action, lgg.outputs)
                if not candidate.is_range_restricted:
                    continue
                # Minimality is θ-SUBSUMPTION, NOT SET INCLUSION.
                #
                # A survivor is more general when its body maps into the
                # candidate's under SOME renaming of its variables. Comparing
                # literal sets misses that: `EXCEEDING(?X1, ?X2, ?X0)` and
                # `EXCEEDING(?X1, ?X4, ?X0)` are the same constraint and are
                # not set-equal, so every alpha-variant superset survived as a
                # separate "hypothesis".
                #
                # Measured: a single correct rule came back as 22 candidates --
                # the right one plus twenty-one copies of itself carrying extra
                # literals that bind nothing -- and the version space could
                # never collapse. Rule IDENTITY was already made
                # renaming-invariant; subsumption had not been.
                if any(_subsumes(s.body, candidate.body) for s in survivors):
                    continue
                if not self._explains(candidate, positives):
                    continue
                if self._refuted(candidate, negatives):
                    continue
                survivors.append(candidate)

        return survivors

    @staticmethod
    def _explains(rule: CandidateRule, positives: Sequence[TrainingExample]) -> bool:
        """Derives the observed change in every positive demonstration.

        Both directions are checked: a rule that predicts the right addition
        while retracting something the demonstration kept has not explained it.
        """
        return all(derives(rule, example) for example in positives)

    @staticmethod
    def _refuted(rule: CandidateRule, negatives: Sequence[TrainingExample]) -> bool:
        """Asserts a change a counter-demonstration showed did not happen."""
        return any(contradicted_by(rule, example) for example in negatives)


_inducer: Optional[RuleInducer] = None


def get_rule_inducer() -> RuleInducer:
    global _inducer
    if _inducer is None:
        _inducer = RuleInducer()
    return _inducer
