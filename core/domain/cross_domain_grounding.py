#!/usr/bin/env python3
"""Cross-domain grounding — what Torin has grounds to believe, not what it can say.

    Cross-domain reasoning is the substrate-grounded recognition and transfer of
    structural knowledge from a previously learned domain to a new or
    incompletely understood situation, with explicit evidence for why the
    correspondence applies.

The model and the substrate have different jobs and must not share an output:

    LLM        expands the hypothesis space — may notice a correspondence no
               deterministic search would find
    SUBSTRATE  determines what Torin actually has grounds to reuse

Both can produce the same sentence. Only the second is Torin knowing something,
and a design where they are indistinguishable downstream is the wrapper problem
one level up from extraction.

FOUR outcomes, because collapsing any two destroys information:

    GROUNDED       a learned structure matches, with the edges and evidence
                   that make it apply
    PROPOSED       a model or heuristic suggested a correspondence and the
                   substrate cannot ground it — a hypothesis, never knowledge
    NO_MATCH       the search RAN over N learned structures and none fit
    INDETERMINATE  the search could not be conducted; coverage or the
                   observation itself was too thin to decide

NO_MATCH and INDETERMINATE are the pair that matters most. "23 structures
searched, nothing fits" is a finding. "the unfamiliar thing has one observable
property" is not a finding about the substrate at all. Unmeasured is not
negative — the same rule that governs evidence here governs search.

This module does NOT acquire evidence. A failure to ground emits an EpistemicGap
and stops. Letting cross-domain reasoning research until it can manufacture an
answer would make UNKNOWN unreachable, and an UNKNOWN that never occurs carries
no information when it does.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)


class GroundingOutcome(Enum):
    GROUNDED = "grounded"
    PROPOSED = "proposed"
    NO_MATCH = "no_match"
    INDETERMINATE = "indeterminate"


class ProposalSource(Enum):
    """Where a correspondence came from. Never collapsed into the outcome."""
    SUBSTRATE_SEARCH = "substrate_search"
    MODEL_PRIOR = "model_prior"


@dataclass(frozen=True)
class StructuralObservation:
    """An unfamiliar situation described by STRUCTURE, not identity.

    Elements are opaque role labels. Naming them `valve` or `pressure` would
    hand the answer to the matcher through the input, which is how a control
    stops being a control.
    """
    observation_id: str
    elements: Tuple[str, ...]
    #: (subject_element, relation, object_element)
    relations: Tuple[Tuple[str, str, str], ...]
    description: str = ""

    #: Below this the observation cannot discriminate between learned
    #: structures, and a failed search says nothing about the substrate.
    MIN_RELATIONS_TO_SEARCH: int = 2

    @property
    def is_searchable(self) -> bool:
        return len(self.relations) >= self.MIN_RELATIONS_TO_SEARCH


@dataclass(frozen=True)
class ElementCorrespondence:
    """One observed element mapped to one learned concept, with its warrant."""
    element: str
    concept_id: str
    #: Edges in the learned graph that carried the match.
    supporting_edges: Tuple[Tuple[str, str, str], ...]
    evidence_ids: Tuple[str, ...]


@dataclass(frozen=True)
class EpistemicGap:
    """A recorded absence of grounds. Input to a learning policy, not an action.

    Cross-domain reasoning detects that learning may be warranted; it does not
    decide to learn, and it does not go and do it.
    """
    gap_id: str
    observation_id: str
    structures_searched: int
    best_support: float
    required_support: float
    reason: str
    unmatched_elements: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GroundingResult:
    outcome: GroundingOutcome
    observation_id: str

    correspondences: Tuple[ElementCorrespondence, ...] = ()
    proposal_source: Optional[ProposalSource] = None

    #: Search accounting. Without it NO_MATCH is an assertion rather than a
    #: measurement, and cannot be told apart from a search that never ran.
    structures_searched: int = 0
    candidates_scored: int = 0
    best_support: float = 0.0
    required_support: float = 0.0

    #: Which domains the search was allowed to consider. An empty tuple means
    #: "every learned domain". Recorded because a GROUNDED result means
    #: something different when the search could see one domain than when it
    #: could see all of them, and a reader cannot tell from the outcome alone.
    searched_domains: Tuple[str, ...] = ()

    relation_class_match: str = "UNMEASURED"
    epistemic_gap: Optional[EpistemicGap] = None
    note: str = ""

    def __post_init__(self):
        if self.outcome is GroundingOutcome.GROUNDED:
            if not self.correspondences:
                raise ValueError("GROUNDED with no correspondences")
            if self.proposal_source is None:
                raise ValueError("GROUNDED must record how it was reached")
        if self.outcome is GroundingOutcome.PROPOSED and self.correspondences:
            raise ValueError(
                "PROPOSED must not carry correspondences: a model suggestion the "
                "substrate could not ground is a hypothesis, and storing it "
                "beside grounded mappings is how a prior becomes knowledge")
        if self.outcome is GroundingOutcome.NO_MATCH and self.structures_searched == 0:
            raise ValueError(
                "NO_MATCH with nothing searched is INDETERMINATE: a search that "
                "did not run is not evidence that nothing fits")

    @property
    def is_usable_for_transfer(self) -> bool:
        return self.outcome is GroundingOutcome.GROUNDED


class CrossDomainGrounder:
    """Searches Torin's LEARNED structure for something the observation fits."""

    #: Fraction of observed relations that must be matched by one learned
    #: structure. A POLICY threshold, not a measured error rate.
    REQUIRED_SUPPORT = 0.6

    #: Structures below this size cannot support a correspondence claim.
    MIN_STRUCTURE_EDGES = 2

    def __init__(self, db):
        self.db = db

    async def _learned_structures(
        self,
        exclude_domains: Sequence[str] = (),
        restrict_to_domains: Sequence[str] = (),
    ) -> Dict[str, List[Tuple[str, str, str]]]:
        """Learned subgraphs, keyed by hub concept.

        A 'structure' is a concept together with its outgoing canonical edges.
        Only edges with a RESOLVED endpoint participate: a dangling edge names
        something Torin has not learned, so it cannot support a claim that a
        learned structure applies.
        """
        rows = await self.db.execute_query(
            """SELECT source_concept_id, relation, target_concept_id
               FROM unified.concept_relations
               WHERE target_concept_id IS NOT NULL
               ORDER BY source_concept_id""", fetch_all=True) or []
        # EXCLUDING THE SOURCE IS WHAT MAKES IT TRANSFER. An observation
        # derived from a learned structure will always match that structure
        # perfectly; grounding it on itself measures identity, not transfer.
        # The excluded set is stated by the caller and reported in the result
        # so a reader can see what the search was denied.
        # RESTRICTING IS THE COUNTERPART OF EXCLUDING, and it is what makes an
        # ablation sound. Removing one domain's edges proves nothing while the
        # search may satisfy the observation from a different domain that
        # learned the same structure independently -- which is exactly what
        # happened to EDU-04: its ablation deleted the kite17 rule's edges and
        # the target still grounded, via `archive:relocate`, taught 39 minutes
        # after that control was frozen. Scoping the search to one domain makes
        # "this rule is necessary" a claim the ablation can actually test.
        excluded = {d.lower() for d in exclude_domains}
        restricted = {d.lower() for d in restrict_to_domains}
        if excluded & restricted:
            raise ValueError(
                f"domains named as both restricted and excluded: "
                f"{sorted(excluded & restricted)}; the search scope would be "
                f"contradictory")

        out: Dict[str, List[Tuple[str, str, str]]] = {}
        for r in rows:
            hub = r["source_concept_id"]
            domain = hub.split(":", 1)[0].lower()
            if domain in excluded:
                continue
            if restricted and domain not in restricted:
                continue
            out.setdefault(hub, []).append(
                (hub, r["relation"], r["target_concept_id"]))
        return {k: v for k, v in out.items() if len(v) >= self.MIN_STRUCTURE_EDGES}

    async def ground(
        self,
        observation: StructuralObservation,
        model_proposal: Optional[Dict[str, str]] = None,
        exclude_domains: Sequence[str] = (),
        restrict_to_domains: Sequence[str] = (),
    ) -> GroundingResult:
        """Can any learned structure carry this observation?

        `model_proposal` maps observed elements to concept ids and may come from
        an LLM. It is treated as a HINT ordering the search, never as a result:
        a proposal the substrate cannot ground returns PROPOSED with no
        correspondences.
        """
        if not observation.is_searchable:
            return GroundingResult(
                outcome=GroundingOutcome.INDETERMINATE,
                observation_id=observation.observation_id,
                required_support=self.REQUIRED_SUPPORT,
                note=(f"observation carries {len(observation.relations)} relation(s); "
                      f"at least {observation.MIN_RELATIONS_TO_SEARCH} are needed before "
                      f"a failed search means anything about the substrate"))

        structures = await self._learned_structures(
            exclude_domains, restrict_to_domains)
        # What the search was actually allowed to see, reported on every
        # result below so a GROUNDED is never read without its scope.
        scope = tuple(sorted({hub.split(":", 1)[0] for hub in structures})) \
            if structures else tuple(sorted(d for d in restrict_to_domains))
        if not structures:
            return GroundingResult(
                searched_domains=scope,
                outcome=GroundingOutcome.INDETERMINATE,
                observation_id=observation.observation_id,
                required_support=self.REQUIRED_SUPPORT,
                note=("the substrate holds no learned structure of sufficient size; "
                      "absence of a match here is a statement about coverage, not "
                      "about the observation"))

        obs_relations = [rel for _s, rel, _o in observation.relations]
        best_hub, best_support, best_edges = None, 0.0, []
        scored = 0

        for hub, edges in structures.items():
            scored += 1
            learned_relations = [rel for _s, rel, _o in edges]
            # RAW relation labels. Relation-class normalisation is deliberately
            # not applied, so its contribution can be measured later rather than
            # baked into the baseline.
            matched = []
            pool = list(learned_relations)
            for rel in obs_relations:
                if rel in pool:
                    pool.remove(rel)
                    matched.append(rel)
            support = len(matched) / len(obs_relations)
            if support > best_support:
                best_hub, best_support, best_edges = hub, support, edges

        if best_support < self.REQUIRED_SUPPORT:
            gap = EpistemicGap(
                gap_id=f"gap_{uuid.uuid4().hex[:12]}",
                observation_id=observation.observation_id,
                structures_searched=scored,
                best_support=best_support,
                required_support=self.REQUIRED_SUPPORT,
                reason="no learned structure reached the required support",
                unmatched_elements=observation.elements)
            if model_proposal:
                return GroundingResult(
                    searched_domains=scope,
                    outcome=GroundingOutcome.PROPOSED,
                    observation_id=observation.observation_id,
                    proposal_source=ProposalSource.MODEL_PRIOR,
                    structures_searched=scored, candidates_scored=scored,
                    best_support=best_support, required_support=self.REQUIRED_SUPPORT,
                    epistemic_gap=gap,
                    note=("a correspondence was proposed but the substrate holds no "
                          "structure supporting it; this is a hypothesis, not "
                          "knowledge Torin may reuse"))
            return GroundingResult(
                searched_domains=scope,
                outcome=GroundingOutcome.NO_MATCH,
                observation_id=observation.observation_id,
                structures_searched=scored, candidates_scored=scored,
                best_support=best_support, required_support=self.REQUIRED_SUPPORT,
                epistemic_gap=gap,
                note=f"searched {scored} learned structures; best support {best_support:.2f}")

        correspondences = await self._build_correspondences(observation, best_edges)
        return GroundingResult(
            searched_domains=scope,
            outcome=GroundingOutcome.GROUNDED,
            observation_id=observation.observation_id,
            correspondences=tuple(correspondences),
            proposal_source=(ProposalSource.MODEL_PRIOR if model_proposal
                             else ProposalSource.SUBSTRATE_SEARCH),
            structures_searched=scored, candidates_scored=scored,
            best_support=best_support, required_support=self.REQUIRED_SUPPORT,
            note=f"grounded on the learned structure around {best_hub}")

    async def _build_correspondences(
        self, observation: StructuralObservation,
        edges: Sequence[Tuple[str, str, str]],
    ) -> List[ElementCorrespondence]:
        """Attach each observed element to a concept, carrying its evidence."""
        by_relation: Dict[str, List[Tuple[str, str, str]]] = {}
        for e in edges:
            by_relation.setdefault(e[1], []).append(e)

        out: List[ElementCorrespondence] = []
        used: Set[str] = set()
        for subj, rel, obj in observation.relations:
            cands = [e for e in by_relation.get(rel, []) if e[2] not in used]
            if not cands:
                continue
            edge = cands[0]
            used.add(edge[2])
            for element, concept_id in ((subj, edge[0]), (obj, edge[2])):
                if any(c.element == element for c in out):
                    continue
                ev = await self.db.execute_query(
                    "SELECT DISTINCT root_evidence_id FROM unified.concept_evidence "
                    "WHERE concept_id = $1", (concept_id,), fetch_all=True) or []
                out.append(ElementCorrespondence(
                    element=element, concept_id=concept_id,
                    supporting_edges=(edge,),
                    evidence_ids=tuple(r["root_evidence_id"] for r in ev)))
        return out


__all__ = [
    "GroundingOutcome", "ProposalSource", "StructuralObservation",
    "ElementCorrespondence", "EpistemicGap", "GroundingResult",
    "CrossDomainGrounder",
]
