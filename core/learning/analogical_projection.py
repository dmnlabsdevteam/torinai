#!/usr/bin/env python3
"""Project a learned rule into another domain through a grounded mapping.

ANALOGY CAN PROPOSE KNOWLEDGE. ONLY TARGET-DOMAIN EVIDENCE CAN AUTHORIZE IT.

That single line is the whole design. This module takes a rule validated in a
source domain and a structural mapping the substrate has already GROUNDED, and
emits a target-vocabulary rule as a CANDIDATE carrying its provenance. It does
not decide whether the rule is true, and it has no way to make it true: it
never touches evidence counts, never sets SUPPORTED or VALIDATED, and never
manufactures an observation. The target world decides, exactly as it does for a
rule induced there from scratch.

Structural similarity is not causal truth. A mapping says two domains share a
shape; whether the source's consequences also hold in the target is a question
about the target, and only the target can answer it.

INCOMPLETE PROJECTION IS NAMED, NEVER QUIETLY WEAKENED. If a delete effect has
no mapped counterpart, the honest result is PARTIAL_PROJECTION with that gap
recorded -- not a rule that silently forgot to retract anything, which would
look like a deliberate design choice to every later reader.
"""

from __future__ import annotations

import hashlib
import json
import itertools
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Mapping, Optional, Tuple

from core.learning.rule_induction import CandidateRule, Fact, RuleEffects

logger = logging.getLogger(__name__)


class ProjectionOutcome(Enum):
    """What the projection could actually build."""
    FULL_PROJECTION = "full_projection"
    #: Some component had no mapped counterpart. The gap is listed; the caller
    #: decides whether a partial operator is worth proposing.
    PARTIAL_PROJECTION = "partial_projection"
    #: The mapping covered nothing the rule needs.
    NO_PROJECTION = "no_projection"
    #: A source predicate mapped to more than one target predicate. Refused
    #: rather than resolved: picking one would invent the correspondence the
    #: mapping failed to establish.
    AMBIGUOUS_MAPPING = "ambiguous_mapping"


@dataclass(frozen=True)
class ElementProvenance:
    """Where one piece of the target rule came from.

    Kept per ELEMENT so that a later contradiction can be attributed to the
    specific correspondence that was wrong, instead of discarding the whole
    analogy as opaque.
    """
    target: str
    source: str
    role: str          # precondition | action | add | delete
    mapping_edge: str


@dataclass
class ProjectionResult:
    outcome: ProjectionOutcome
    source_rule_id: str
    source_domain: str
    target_domain: str
    mapping_id: str

    rule: Optional[CandidateRule] = None
    provenance: List[ElementProvenance] = field(default_factory=list)
    #: Source components with no counterpart, as (role, fact).
    unmapped: List[Tuple[str, str]] = field(default_factory=list)
    detail: str = ""

    @property
    def is_proposable(self) -> bool:
        """Only a complete projection is worth putting to the target world.

        A partial operator would be tested, and whatever the world said would
        be attributed to a rule the analogy never actually claimed.
        """
        return self.outcome is ProjectionOutcome.FULL_PROJECTION and self.rule is not None


def mapping_id(source_rule_id: str, correspondences: Mapping[str, str]) -> str:
    """Stable id for one correspondence set, so a candidate can name its cause."""
    payload = json.dumps(
        {"source_rule": source_rule_id, "map": dict(sorted(correspondences.items()))},
        sort_keys=True, separators=(",", ":"))
    return "map_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _rewritten_identity(source_rule: CandidateRule,
                        correspondence: Mapping[str, str]) -> Optional[str]:
    """The identity of the rule this correspondence would produce, or None if
    it does not cover the whole rule."""
    from core.learning.rule_identity import semantic_fingerprint

    def rewrite(fact: Fact) -> Optional[Fact]:
        target = correspondence.get(fact.predicate)
        return Fact(target, fact.args) if target else None

    action = rewrite(source_rule.action) if source_rule.action else None
    parts = [rewrite(f) for f in source_rule.preconditions]
    adds = [rewrite(f) for f in source_rule.effects.add]
    deletes = [rewrite(f) for f in source_rule.effects.delete]
    if any(f is None for f in parts + adds + deletes) or (
            source_rule.action is not None and action is None):
        return None
    body = frozenset(parts) | ({action} if action else frozenset())
    try:
        return semantic_fingerprint(CandidateRule(
            body=body,
            effects=RuleEffects(add=frozenset(adds), delete=frozenset(deletes)),
            action=action, outputs=source_rule.outputs))
    except ValueError:
        return None


def derive_correspondence(
    source_rule: CandidateRule,
    observations,
) -> Tuple[Dict[str, str], str]:
    """Discover a predicate correspondence from observed target transitions.

    The mapping must be DISCOVERED from the target, not supplied, or the
    experiment is measuring the experimenter. What a transition licenses:

        the action invoked        <-> the source rule's action
        the predicate ADDED       <-> the source rule's added predicate
        the predicate RETRACTED   <-> the source rule's retracted predicate

    Those three come free, because a state change names its own participants.

    EVIDENCE NARROWS THE REST. A predicate absent from any transition where the
    law fired cannot be one of its preconditions, so the candidates are the
    predicates common to every firing transition. One transition rules nothing
    out and this used to take only one -- a property varying independently of
    the law stayed a candidate forever, and the derivation refused.

    AND AN AMBIGUITY THAT CHANGES NOTHING IS NOT ONE. Where several candidate
    mappings remain, they are compared by the rule they would produce. Two
    preconditions of the same arity that the source rule uses symmetrically --
    `ACT(?x) AND P(?x) AND Q(?x)` -- map either way to the same rule, so there
    is nothing to choose and refusing was refusing to notice. Where the
    candidates really do give different rules, it still refuses.

    Accepts one transition or many. Returns (correspondence, reason); an empty
    correspondence means the evidence licensed nothing.
    """
    transitions = ([observations] if hasattr(observations, "observed_effects")
                   else list(observations))
    firing = [t for t in transitions
              if t.action is not None and t.observed_effects.add]
    if not firing:
        return {}, "no transition invoked an action and changed anything"

    correspondence: Dict[str, str] = {}
    for source_side, target_of, label in (
        (source_rule.effects.add, lambda t: t.observed_effects.add, "add"),
        (source_rule.effects.delete, lambda t: t.observed_effects.delete, "delete"),
    ):
        source_preds = {f.predicate for f in source_side}
        target_preds = {f.predicate for t in firing for f in target_of(t)}
        if len(source_preds) == 1 and len(target_preds) == 1:
            correspondence[next(iter(source_preds))] = next(iter(target_preds))
        elif source_preds and target_preds:
            return {}, f"{label} effects do not pair one-to-one across the transitions"

    actions = {t.action.predicate for t in firing}
    if len(actions) != 1:
        return {}, "the transitions invoked different actions"
    if source_rule.action is not None:
        correspondence[source_rule.action.predicate] = next(iter(actions))

    # Candidates: present in EVERY firing transition, and not already mapped.
    mapped_targets = set(correspondence.values())
    common = set.intersection(*({f.predicate for f in t.before} for t in firing))
    arity_of = {f.predicate: f.arity for t in firing for f in t.before}
    target_remaining = {p: arity_of[p] for p in common if p not in mapped_targets}

    source_remaining = {f.predicate: f.arity for f in source_rule.preconditions
                        if f.predicate not in correspondence}

    undecided: Dict[str, List[str]] = {}
    for predicate, arity in sorted(source_remaining.items()):
        candidates = [p for p, a in sorted(target_remaining.items()) if a == arity]
        if not candidates:
            return {}, (f"{predicate}/{arity} has no target predicate of that arity "
                        f"present throughout")
        if len(candidates) == 1:
            correspondence[predicate] = candidates[0]
            target_remaining.pop(candidates[0])
            continue
        undecided[predicate] = candidates

    if not undecided:
        return correspondence, f"derived from {len(firing)} observed transition(s)"

    predicates = sorted(undecided)
    pool = sorted({c for candidates in undecided.values() for c in candidates})
    identities: Dict[str, Dict[str, str]] = {}
    for assignment in itertools.permutations(pool, len(predicates)):
        if any(target not in undecided[predicate]
               for predicate, target in zip(predicates, assignment)):
            continue
        candidate = {**correspondence, **dict(zip(predicates, assignment))}
        identity = _rewritten_identity(source_rule, candidate)
        if identity is not None:
            identities.setdefault(identity, candidate)

    if len(identities) == 1:
        return (next(iter(identities.values())),
                f"derived from {len(firing)} observed transition(s); "
                f"{len(predicates)} predicate(s) map several ways to the same rule")
    return {}, (f"{', '.join(predicates)} map to {len(identities)} different rules; "
                f"ambiguous, refusing to choose")


def project(
    source_rule: CandidateRule,
    correspondences: Mapping[str, str],
    *,
    source_rule_id: str,
    source_domain: str,
    target_domain: str,
) -> ProjectionResult:
    """Rewrite `source_rule` in the target vocabulary. Proposes; proves nothing.

    `correspondences` maps SOURCE predicate -> TARGET predicate. Variables are
    carried through unchanged: the mapping is about what the predicates mean,
    not about which objects fill them.
    """
    mid = mapping_id(source_rule_id, correspondences)
    base = dict(outcome=ProjectionOutcome.NO_PROJECTION,
                source_rule_id=source_rule_id, source_domain=source_domain,
                target_domain=target_domain, mapping_id=mid)

    # A source predicate reaching two target predicates is not a correspondence.
    seen: Dict[str, str] = {}
    for source_pred, target_pred in correspondences.items():
        if source_pred in seen and seen[source_pred] != target_pred:
            return ProjectionResult(
                **{**base, "outcome": ProjectionOutcome.AMBIGUOUS_MAPPING},
                detail=(f"{source_pred} maps to both {seen[source_pred]} and "
                        f"{target_pred}; refusing to choose"))
        seen[source_pred] = target_pred

    provenance: List[ElementProvenance] = []
    unmapped: List[Tuple[str, str]] = []

    def rewrite(fact: Fact, role: str) -> Optional[Fact]:
        target_pred = correspondences.get(fact.predicate)
        if target_pred is None:
            unmapped.append((role, str(fact)))
            return None
        mapped = Fact(target_pred, fact.args)
        provenance.append(ElementProvenance(
            target=str(mapped), source=str(fact), role=role,
            mapping_edge=f"{fact.predicate}->{target_pred}"))
        return mapped

    action = rewrite(source_rule.action, "action") if source_rule.action else None
    preconditions = [f for f in (rewrite(p, "precondition")
                                 for p in sorted(source_rule.preconditions, key=str))
                     if f is not None]
    adds = [f for f in (rewrite(a, "add") for a in sorted(source_rule.effects.add, key=str))
            if f is not None]
    deletes = [f for f in (rewrite(d, "delete")
                           for d in sorted(source_rule.effects.delete, key=str))
               if f is not None]

    if not provenance:
        return ProjectionResult(**base, unmapped=unmapped,
                                detail="the mapping covered nothing this rule uses")

    if unmapped:
        # NAMED, not silently dropped. A rule missing its delete effect looks
        # deliberate to every later reader.
        return ProjectionResult(
            **{**base, "outcome": ProjectionOutcome.PARTIAL_PROJECTION},
            provenance=provenance, unmapped=unmapped,
            detail=(f"{len(unmapped)} component(s) had no counterpart: "
                    + "; ".join(f"{role} {fact}" for role, fact in unmapped)))

    body = frozenset(preconditions) | ({action} if action else frozenset())
    # OUTPUTS CROSS VERBATIM. A mapping renames predicates, never variables or
    # arithmetic: dividing is dividing in the target domain too. Dropping them
    # here would project a rule that computes a value into one that concludes
    # about a term nothing accounts for -- not a weaker analogy, an invalid
    # rule, and one this module's own "named, not silently dropped" discipline
    # would have had no record of.
    rule = CandidateRule(
        body=body,
        effects=RuleEffects(add=frozenset(adds), delete=frozenset(deletes)),
        action=action,
        outputs=source_rule.outputs,
    )
    logger.info("projected %s (%s) into %s as %s via %s",
                source_rule_id, source_domain, target_domain, rule.to_formula(), mid)
    return ProjectionResult(
        **{**base, "outcome": ProjectionOutcome.FULL_PROJECTION},
        rule=rule, provenance=provenance,
        detail="every precondition, the action and both effect sets were mapped")


__all__ = ["ProjectionOutcome", "ProjectionResult", "ElementProvenance",
           "project", "mapping_id", "derive_correspondence"]
