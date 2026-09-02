#!/usr/bin/env python3
"""What may be inferred from a chain of typed relations, and what may NOT.

    THE TYPER SAYS WHAT A RELATION IS. THIS SAYS WHAT FOLLOWS FROM IT.

Graph reachability over relation edges is unsound: it will happily chain
`oak MADE_OF wood` into `oak MADE_OF plant` into `oak ISA animal`, deriving that
an oak is an animal from edges that never licensed it. Inference over a typed
graph must instead compose relations only where the composition is LICENSED for
those types. This is that licence, and nothing else in the substrate is allowed
to walk relation edges to conclusions -- reachability is not entailment.

Licensed derivations, all conservative and all PROVENANCE-TAGGED:

    TRANSITIVITY   A -r-> B -r-> C   |=  A -r-> C
                   only when r is ALWAYS-transitive (ISA), or ONTOLOGY_DEFINED
                   AND a context explicitly licenses r (PART_OF, LOCATED_IN,
                   CAUSES ... never chain on their own).

    INHERITANCE    A -ISA-> B -r-> C |=  A -r-> C   when r is inheritable
                   (a kind's generic properties pass to its subkinds).

    INVERSE        A -r-> B          |=  B -r'-> A  when r has an inverse
                   (HAS_PART -> PART_OF). The inverse is DERIVED, never recorded
                   as an observation -- the evidence architecture must be able to
                   tell "seen" from "inferred".

    plus the single special case INSTANCE_OF ∘ ISA |= INSTANCE_OF.

Every other pairing composes to NOTHING. Isolation is the default. And the whole
engine is OPEN-WORLD: a query it cannot derive is UNKNOWN, never FALSE. FALSE is
reserved for an explicit contradiction. "A zorble has wings" with no evidence is
`unknown`, not `false` -- the distinction an honest epistemic substrate must keep.

NO MODEL IS INVOLVED. This is a finite algebra over enum types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from core.semantics.relation_types import (
    SemanticRelation, Transitivity, get_spec)

logger = logging.getLogger(__name__)

ISA = SemanticRelation.ISA
INSTANCE_OF = SemanticRelation.INSTANCE_OF

# Derivation rules, recorded on every derived edge so an inference is never
# confused with an observation and can always say WHY it holds.
TRANSITIVITY = "transitivity"
INHERITANCE = "inheritance"
INSTANCE_RIDE = "instance_of_rides_isa"
INVERSE = "inverse_of_relation"


def compose(r1: SemanticRelation, r2: SemanticRelation, *,
            context_licenses: FrozenSet[SemanticRelation] = frozenset()
            ) -> Optional[Tuple[SemanticRelation, str]]:
    """The relation entailed by A -r1-> B -r2-> C and the RULE that licensed it,
    or None. None is the default: a composition is licensed only by an explicit
    rule, never by two relations merely sharing a middle term.

    `context_licenses` names the ONTOLOGY_DEFINED relations a caller's context
    permits to chain (e.g. PART_OF within an anatomy ontology). Empty by default,
    so ontology-defined relations do NOT chain unless a context says so."""
    if r1 is INSTANCE_OF and r2 is ISA:
        return INSTANCE_OF, INSTANCE_RIDE
    if r1 is ISA and get_spec(r2).inheritable:
        return r2, INHERITANCE
    if r1 is r2:
        t = get_spec(r1).transitivity
        if t is Transitivity.ALWAYS:
            return r1, TRANSITIVITY
        if t is Transitivity.ONTOLOGY_DEFINED and r1 in context_licenses:
            return r1, TRANSITIVITY
    return None


def is_licensed(r1: SemanticRelation, r2: SemanticRelation, *,
                context_licenses: FrozenSet[SemanticRelation] = frozenset()) -> bool:
    return compose(r1, r2, context_licenses=context_licenses) is not None


def inverse(r: SemanticRelation) -> Optional[SemanticRelation]:
    return get_spec(r).inverse


@dataclass(frozen=True)
class Edge:
    """A typed relation between two concepts."""
    subject: str
    relation: SemanticRelation
    obj: str


@dataclass(frozen=True)
class Derivation:
    """An entailed edge and the observed path that licensed it, with the rule
    used at each step. DERIVED -- never confused with an observation."""
    edge: Edge
    path: Tuple[Edge, ...]
    rules: Tuple[str, ...]

    @property
    def hops(self) -> int:
        return len(self.path)


def _index(edges: Sequence[Edge]) -> Dict[str, List[Edge]]:
    out: Dict[str, List[Edge]] = {}
    for e in edges:
        out.setdefault(e.subject, []).append(e)
    return out


def inverse_edges(edges: Sequence[Edge]) -> List[Derivation]:
    """Every inverse edge DERIVABLE from the observed ones. Each is one hop and
    tagged INVERSE, so `flippers PART_OF zorble` from `zorble HAS_PART flippers`
    is stored as derived, with provenance, not asserted as seen."""
    out = []
    for e in edges:
        inv = get_spec(e.relation).inverse
        if inv is None:
            continue
        out.append(Derivation(Edge(e.obj, inv, e.subject), (e,), (INVERSE,)))
    return out


def derive_from(subject: str, edges: Sequence[Edge], *,
                context_licenses: FrozenSet[SemanticRelation] = frozenset(),
                include_inverse: bool = True,
                max_hops: int = 8) -> List[Derivation]:
    """Every edge ENTAILED from `subject`, breadth-first over licensed steps.

    Only licensed compositions extend a path, so an unlicensed relation stops the
    chain rather than leaking a conclusion. Optionally seeds the search with
    inverse edges (so an inverse can then participate in further inference).
    Returns DERIVED edges only; the observed ones are the input."""
    working: List[Edge] = list(edges)
    seed_inverse: Dict[Tuple[str, SemanticRelation, str], Derivation] = {}
    if include_inverse:
        for d in inverse_edges(edges):
            key = (d.edge.subject, d.edge.relation, d.edge.obj)
            seed_inverse[key] = d
            working.append(d.edge)   # let inverses participate in chaining

    by_subject = _index(working)
    observed: Set[Tuple[str, SemanticRelation, str]] = {
        (e.subject, e.relation, e.obj) for e in edges}
    results: Dict[Tuple[str, SemanticRelation, str], Derivation] = dict(
        {k: v for k, v in seed_inverse.items() if k[0] == subject})

    frontier: List[Tuple[str, SemanticRelation, Tuple[Edge, ...], Tuple[str, ...]]] = []
    seen_state: Set[Tuple[str, SemanticRelation]] = set()
    for e in by_subject.get(subject, []):
        rule0 = (INVERSE,) if (e.subject, e.relation, e.obj) in seed_inverse else ()
        frontier.append((e.obj, e.relation, (e,), rule0))

    while frontier:
        node, acc_rel, path, rules = frontier.pop(0)
        if len(path) >= max_hops:
            continue
        for nxt in by_subject.get(node, []):
            step = compose(acc_rel, nxt.relation, context_licenses=context_licenses)
            if step is None:
                continue
            composed, rule = step
            new_path = path + (nxt,)
            new_rules = rules + (rule,)
            key = (subject, composed, nxt.obj)
            state = (nxt.obj, composed)
            if state in seen_state:
                continue
            seen_state.add(state)
            if key not in observed and key not in results:
                results[key] = Derivation(Edge(subject, composed, nxt.obj),
                                          new_path, new_rules)
            frontier.append((nxt.obj, composed, new_path, new_rules))

    return list(results.values())


# ─────────────────────────────── answering ───────────────────────────────

TRUE, FALSE, UNKNOWN = "true", "false", "unknown"
OBSERVED, DERIVED, NONE = "observed", "derived", "none"


@dataclass(frozen=True)
class Answer:
    """An honest, open-world answer. `verdict` is true / false / unknown;
    `basis` is observed / derived / none. UNKNOWN is NOT false -- the substrate
    was simply never told and could not derive it."""
    verdict: str
    basis: str
    derivation: Optional[Derivation] = None

    def __bool__(self) -> bool:
        return self.verdict == TRUE


def answer(subject: str, relation: SemanticRelation, obj: str,
           edges: Sequence[Edge], *,
           context_licenses: FrozenSet[SemanticRelation] = frozenset(),
           negatives: Sequence[Edge] = ()) -> Answer:
    """Is `subject relation obj` true, false, or unknown, given what is observed?

    OPEN-WORLD: an edge that is neither observed nor derivable is UNKNOWN, never
    false. FALSE is returned only when an explicit negative (a denied
    observation) contradicts it -- absence of evidence is not evidence of
    absence."""
    if any(n.subject == subject and n.relation is relation and n.obj == obj
           for n in negatives):
        return Answer(FALSE, OBSERVED)
    if (subject, relation, obj) in {(e.subject, e.relation, e.obj) for e in edges}:
        return Answer(TRUE, OBSERVED)
    for d in derive_from(subject, edges, context_licenses=context_licenses):
        if d.edge.relation is relation and d.edge.obj == obj:
            return Answer(TRUE, DERIVED, d)
    return Answer(UNKNOWN, NONE)


def entails(subject: str, relation: SemanticRelation, obj: str,
            edges: Sequence[Edge], *,
            context_licenses: FrozenSet[SemanticRelation] = frozenset(),
            max_hops: int = 8) -> Optional[Derivation]:
    """The derivation of `subject relation obj` if it is DERIVABLE (not observed),
    else None. Kept for the isolation tests, which assert non-derivability."""
    for d in derive_from(subject, edges, context_licenses=context_licenses,
                         max_hops=max_hops):
        if d.edge.relation is relation and d.edge.obj == obj:
            return d
    return None


def would_contaminate(r1: SemanticRelation, r2: SemanticRelation,
                      forbidden: SemanticRelation) -> bool:
    """Negative-control helper: does composing r1,r2 yield `forbidden`?"""
    step = compose(r1, r2)
    return step is not None and step[0] is forbidden


__all__ = ["Edge", "Derivation", "Answer", "compose", "is_licensed", "inverse",
           "inverse_edges", "derive_from", "answer", "entails",
           "would_contaminate", "TRUE", "FALSE", "UNKNOWN",
           "OBSERVED", "DERIVED", "TRANSITIVITY", "INHERITANCE", "INVERSE",
           "INSTANCE_RIDE"]
