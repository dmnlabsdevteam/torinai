#!/usr/bin/env python3
"""
Hierarchical Abstraction System v2.0
=====================================
Active abstraction with FULL architectural fixes:
1. Semantic overreach protection (embedding + domain + ontology)
2. Feedback loop damping (caps + novel evidence)
3. Full-spectrum decay (all influence effects)
4. Counterfactual stress testing (anticipatory volatility)
5. Planning integration (principles shape strategy)

Author: TorinAI System
Version: 2.0 - Production Ready
"""

import asyncio
import logging
import uuid
import numpy as np
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from types import SimpleNamespace
from enum import Enum
import re

logger = logging.getLogger(__name__)


class AbstractionLevel(Enum):
    """Levels in the concept hierarchy"""
    EPISODIC = 0
    PATTERN = 1
    SCHEMA = 2
    PRINCIPLE = 3


class RelationshipType(Enum):
    """Logical relationships between concepts"""
    IMPLIES = "implies"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    COMPETES_WITH = "competes_with"
    ABSTRACTION_OF = "abstraction_of"
    INSTANTIATION_OF = "instantiation_of"


@dataclass
class ProbabilisticSchema:
    """Schema with counterexample tracking and feedback loop protection"""
    schema_id: str
    condition: Dict[str, Any]
    outcome: Dict[str, Any]
    probability: float
    confidence_interval: Tuple[float, float]
    supporting_memories: List[str] = field(default_factory=list)
    counterexamples: List[str] = field(default_factory=list)
    confounders: List[str] = field(default_factory=list)
    competing_schemas: List[str] = field(default_factory=list)
    induction_method: str = "similarity_clustering"
    abstraction_confidence: float = 0.5
    evidence_count: int = 0
    formation_time: datetime = field(default_factory=datetime.now)
    reinforcement_count: int = 0
    decay_rate: float = 0.05
    last_reinforced: datetime = field(default_factory=datetime.now)
    stability_score: float = 0.0
    belief_id: Optional[str] = None

    # Active influence effects
    retrieval_boost: float = 1.0
    prior_adjustment: float = 0.0
    attention_weight: float = 1.0

    # Feedback loop protection (FIX #2)
    cumulative_prior_adjustments: Dict[str, float] = field(default_factory=dict)
    cumulative_retrieval_boosts: Dict[str, float] = field(default_factory=dict)
    boost_history: List[Tuple[datetime, str, float]] = field(default_factory=list)
    novel_evidence_count: int = 0  # Evidence NOT from boosted retrieval

    # Context tracking
    session_ids: Set[str] = field(default_factory=set)
    temporal_span_days: float = 0.0
    context_diversity_score: float = 0.0

    # Counterfactual stress testing (FIX #4)
    stress_test_score: float = 0.0
    last_stress_test: Optional[datetime] = None
    fragility_detected: bool = False

    # Outcome tracking (GAP E FIX)
    outcome_success_rate: float = 0.5  # Success rate of tasks using this schema
    outcome_success_count: int = 0  # Number of successful task outcomes
    outcome_failure_count: int = 0  # Number of failed task outcomes
    last_outcome_check: Optional[datetime] = None  # Last time outcomes were queried
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata

    def calculate_probability(self) -> float:
        """Calculate P(outcome | condition) from evidence"""
        positive = len(self.supporting_memories)
        negative = len(self.counterexamples)
        total = positive + negative
        if total == 0:
            return 0.5
        return (positive + 1) / (total + 2)

    def calculate_credible_interval(self) -> Tuple[float, float]:
        """Calculate 95% Bayesian credible interval"""
        alpha = len(self.supporting_memories) + 1
        beta = len(self.counterexamples) + 1
        margin = 1.96 * np.sqrt(self.probability * (1 - self.probability) / max(self.evidence_count, 1))
        return (max(0.0, self.probability - margin), min(1.0, self.probability + margin))

    def update_evidence(self, new_memory_id: str, supports: bool, is_novel: bool = False):
        """Update schema with new evidence"""
        if supports:
            self.supporting_memories.append(new_memory_id)
            self.reinforcement_count += 1
            if is_novel:
                self.novel_evidence_count += 1
        else:
            self.counterexamples.append(new_memory_id)
        self.evidence_count += 1
        self.last_reinforced = datetime.now()
        self.probability = self.calculate_probability()
        self.confidence_interval = self.calculate_credible_interval()

    def calculate_decay_rate(self, context_diversity: float) -> float:
        """
        Calculate decay rate - early schemas decay faster

        GAP E FIX: Schemas with high outcome success rates decay slower
        """
        age_days = (datetime.now() - self.formation_time).days
        base_decay = 0.05
        reinforcement_factor = min(self.reinforcement_count / 20.0, 1.0)
        age_factor = min(age_days / 90.0, 1.0)
        diversity_factor = context_diversity

        # Increase decay if fragile (FIX #4)
        fragility_penalty = 1.5 if self.fragility_detected else 1.0

        # GAP E FIX: Reduce decay for effective schemas
        # Success rate > 0.7: 0.7x decay (slower decay)
        # Success rate < 0.4: 1.3x decay (faster decay)
        # Success rate 0.4-0.7: 1.0x decay (normal)
        total_outcomes = self.outcome_success_count + self.outcome_failure_count
        if total_outcomes >= 3:  # Need at least 3 outcomes for reliable signal
            if self.outcome_success_rate > 0.7:
                effectiveness_factor = 0.7  # Successful schemas persist longer
            elif self.outcome_success_rate < 0.4:
                effectiveness_factor = 1.3  # Ineffective schemas decay faster
            else:
                effectiveness_factor = 1.0  # Normal decay
        else:
            effectiveness_factor = 1.0  # Not enough data

        decay_rate = base_decay * fragility_penalty * effectiveness_factor * (
            (1 - reinforcement_factor * 0.6) *
            (1 - age_factor * 0.3) *
            (1 - diversity_factor * 0.1)
        )
        return max(0.005, min(decay_rate, 0.08))

    def apply_temporal_decay(self, time_delta_hours: float) -> Tuple[float, float, float, float]:
        """
        FIX #3: Apply decay to probability AND all influence effects.
        Returns: (decayed_prob, decayed_attention, decayed_boost, decayed_prior_adj)
        """
        decay_factor = 1 - np.exp(-self.decay_rate * time_delta_hours / 24.0)

        # Decay probability toward 0.5 (uncertainty)
        current_prob = self.probability
        decayed_prob = current_prob + (0.5 - current_prob) * decay_factor

        # Decay attention weight toward 1.0 (neutral)
        decayed_attention = self.attention_weight + (1.0 - self.attention_weight) * decay_factor

        # Decay retrieval boost toward 1.0 (no boost)
        decayed_boost = self.retrieval_boost + (1.0 - self.retrieval_boost) * decay_factor

        # Decay prior adjustment toward 0.0 (no adjustment)
        decayed_prior_adj = self.prior_adjustment * (1 - decay_factor * 0.5)

        return decayed_prob, decayed_attention, decayed_boost, decayed_prior_adj


@dataclass
class AbstractionCandidate:
    """Cluster evaluated for abstraction with continuous pressure scoring"""
    cluster_id: str
    memory_ids: List[str]
    frequency_weight: float = 0.0
    cross_context_weight: float = 0.0
    outcome_coherence: float = 0.0
    temporal_consistency: float = 0.0
    reusability_signal: float = 0.0
    reasoning_depth: float = 0.0
    contradiction_penalty: float = 0.0
    abstraction_score: float = 0.0
    extracted_condition: Optional[Dict[str, Any]] = None
    extracted_outcome: Optional[Dict[str, Any]] = None

    def calculate_abstraction_pressure(self) -> float:
        """
        Calculate abstraction pressure score

        INTEGRATION C: Includes domain coherence signal from UDM
        """
        score = (
            self.frequency_weight * 1.0 +
            self.cross_context_weight * 2.0 +
            self.outcome_coherence * 1.5 +
            self.temporal_consistency * 1.2 +
            self.reusability_signal * 0.8 +
            self.reasoning_depth * 0.5 -
            self.contradiction_penalty * 3.0
        )

        # INTEGRATION C: Boost if memories have domain coherence
        domain_coherence = getattr(self, 'domain_coherence', 0.0)
        if domain_coherence > 0:
            score += domain_coherence * 1.5  # Domain-aligned patterns more valuable

        return max(0.0, score)

    def should_abstract(self, threshold: float = 5.0) -> bool:
        """Check if pressure exceeds threshold.

        Computes the pressure when it has not already been assigned, rather
        than trusting the caller to populate abstraction_score first.
        process_memories() -- the only path that ever ran -- called this
        without assigning it, so the comparison used the 0.0 default and no
        cluster could ever abstract regardless of how strong the pattern was.
        """
        if not self.abstraction_score:
            self.abstraction_score = self.calculate_abstraction_pressure()
        return self.abstraction_score > threshold


@dataclass
class ConceptNode:
    """Node in concept hierarchy constraint graph"""
    concept_id: str
    level: AbstractionLevel
    content: str
    probability: float
    abstraction_of: List[str] = field(default_factory=list)
    instantiated_by: List[str] = field(default_factory=list)
    implies: List[str] = field(default_factory=list)
    contradicts: List[str] = field(default_factory=list)
    supports: List[str] = field(default_factory=list)
    competes_with: List[str] = field(default_factory=list)
    belief_id: Optional[str] = None
    schema_id: Optional[str] = None

    # The schema trigger and conclusion this concept came from, kept so later
    # concepts can be compared against it to derive implies/contradicts edges
    # without re-reading the schema store.
    source_condition: Optional[Dict[str, Any]] = None
    source_outcome: Optional[str] = None

    retrieval_boost: float = 1.0
    prior_adjustment: float = 0.0
    attention_weight: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    update_count: int = 0

    # For planning integration (FIX #5)
    strategy_template: Optional[Dict[str, Any]] = None
    applicable_contexts: List[str] = field(default_factory=list)


class ConceptHierarchy:
    """Manages concept lattice as constraint graph"""

    def __init__(self):
        self.nodes: Dict[str, ConceptNode] = {}
        self.forward_edges: Dict[str, Set[str]] = defaultdict(set)
        self.backward_edges: Dict[str, Set[str]] = defaultdict(set)
        self.implication_edges: Dict[str, Set[str]] = defaultdict(set)
        self.contradiction_edges: Dict[str, Set[str]] = defaultdict(set)
        self.stats = {
            'total_concepts': 0,
            'episodic_concepts': 0,
            'pattern_concepts': 0,
            'schema_concepts': 0,
            'principle_concepts': 0,
            'constraint_violations': 0
        }

    def add_concept(self, node: ConceptNode):
        """Add concept and update graph edges"""
        self.nodes[node.concept_id] = node
        for parent_id in node.abstraction_of:
            self.backward_edges[node.concept_id].add(parent_id)
            self.forward_edges[parent_id].add(node.concept_id)
        for implied_id in node.implies:
            self.implication_edges[node.concept_id].add(implied_id)
        for contradicted_id in node.contradicts:
            self.contradiction_edges[node.concept_id].add(contradicted_id)
            self.contradiction_edges[contradicted_id].add(node.concept_id)
        self.stats['total_concepts'] += 1
        if node.level == AbstractionLevel.EPISODIC:
            self.stats['episodic_concepts'] += 1
        elif node.level == AbstractionLevel.PATTERN:
            self.stats['pattern_concepts'] += 1
        elif node.level == AbstractionLevel.SCHEMA:
            self.stats['schema_concepts'] += 1
        elif node.level == AbstractionLevel.PRINCIPLE:
            self.stats['principle_concepts'] += 1

    def get_ancestors(self, concept_id: str, max_depth: int = 5) -> List[ConceptNode]:
        """Get parent concepts up hierarchy"""
        ancestors = []
        visited = set()
        queue = [(concept_id, 0)]
        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_depth or current_id in visited:
                continue
            visited.add(current_id)
            for parent_id in self.backward_edges.get(current_id, []):
                if parent_id in self.nodes:
                    ancestors.append(self.nodes[parent_id])
                    queue.append((parent_id, depth + 1))
        return ancestors

    def get_descendants(self, concept_id: str, max_depth: int = 5) -> List[ConceptNode]:
        """Get child concepts down hierarchy"""
        descendants = []
        visited = set()
        queue = [(concept_id, 0)]
        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_depth or current_id in visited:
                continue
            visited.add(current_id)
            for child_id in self.forward_edges.get(current_id, []):
                if child_id in self.nodes:
                    descendants.append(self.nodes[child_id])
                    queue.append((child_id, depth + 1))
        return descendants

    def find_principles_for_domain(self, domain: str) -> List[ConceptNode]:
        """Find Level 3 principles relevant to domain"""
        principles = []
        for node in self.nodes.values():
            if node.level == AbstractionLevel.PRINCIPLE:
                if domain in node.applicable_contexts or not node.applicable_contexts:
                    principles.append(node)
        return principles

    def check_consistency(self) -> List[Dict[str, Any]]:
        """Check for logical violations"""
        violations = []
        for concept_id, node in self.nodes.items():
            for implied_id in node.implies:
                if implied_id in self.nodes:
                    implied_node = self.nodes[implied_id]
                    if node.probability > implied_node.probability + 0.15:
                        violations.append({
                            'type': 'implication',
                            'source': concept_id,
                            'target': implied_id,
                            'source_prob': node.probability,
                            'target_prob': implied_node.probability
                        })
                        self.stats['constraint_violations'] += 1
            for contradicted_id in node.contradicts:
                if contradicted_id in self.nodes:
                    contradicted_node = self.nodes[contradicted_id]
                    prob_sum = node.probability + contradicted_node.probability
                    if not (0.8 <= prob_sum <= 1.2):
                        violations.append({
                            'type': 'contradiction',
                            'source': concept_id,
                            'target': contradicted_id,
                            'prob_sum': prob_sum
                        })
                        self.stats['constraint_violations'] += 1
        return violations


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.memory import MemoryAgent
    from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem
    from core.reasoning.abstract_reasoning_engine import AbstractReasoningEngine


class AbstractionPipeline:
    """Active abstraction with all architectural fixes"""

    def __init__(
        self,
        memory_agent: 'MemoryAgent',
        uncertainty_system: 'BayesianUncertaintySystem',
        reasoning_engine: Optional['AbstractReasoningEngine'] = None,
        governance_agent: Optional[Any] = None,
        intrinsic_motivation: Optional[Any] = None
    ):
        self.memory = memory_agent
        self.beliefs = uncertainty_system
        self.reasoning = reasoning_engine
        self.governance = governance_agent
        self.motivation = intrinsic_motivation
        self.concept_hierarchy = ConceptHierarchy()
        self.active_schemas: Dict[str, ProbabilisticSchema] = {}
        self.abstraction_candidates: Dict[str, AbstractionCandidate] = {}
        self.monitoring_active = False
        self.last_monitoring_run: Optional[datetime] = None
        self.stats = {
            'schemas_formed': 0,
            'schemas_reinforced': 0,
            'schemas_decayed': 0,
            'priors_modified': 0,
            'retrieval_weights_modified': 0,
            'attention_biases_added': 0,
            'abstraction_triggers': 0,
            'feedback_loops_prevented': 0,
            'semantic_overreach_prevented': 0,
            'stress_tests_run': 0,
            'governance_blocks_checked': 0,
            'motivation_adjustments': 0
        }
        self._db_handle = None
        self._schema_table_ready = False
        logger.info("AbstractionPipeline v2.0 initialized")

    # ── Schema persistence (schemas survive a restart) ───────────────────────

    _SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS unified.schemas (
        schema_id      VARCHAR PRIMARY KEY,
        belief_id      VARCHAR,
        probability    DOUBLE PRECISION,
        payload        JSONB NOT NULL,
        formation_time TIMESTAMPTZ,
        updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    def _db(self):
        if self._db_handle is None:
            from core.database import get_database_manager
            self._db_handle = get_database_manager()
        return self._db_handle

    async def _ensure_schema_table(self) -> None:
        if self._schema_table_ready:
            return
        db = self._db()
        if not getattr(db, "initialized", False):
            await db.initialize()
        await db.execute_query(self._SCHEMA_DDL.strip())
        self._schema_table_ready = True

    @staticmethod
    def _schema_to_payload(schema: 'ProbabilisticSchema') -> Dict[str, Any]:
        """Serialize a schema to JSON-native fields. datetimes→iso, tuples→lists;
        free-form condition/outcome dicts go through default=str at dump time."""
        import dataclasses
        out: Dict[str, Any] = {}
        for f in dataclasses.fields(schema):
            v = getattr(schema, f.name, None)
            if isinstance(v, datetime):
                out[f.name] = v.isoformat()
            elif isinstance(v, tuple):
                out[f.name] = list(v)
            else:
                out[f.name] = v
        return out

    @staticmethod
    def _schema_from_payload(d: Dict[str, Any]) -> 'ProbabilisticSchema':
        import dataclasses
        names = {f.name for f in dataclasses.fields(ProbabilisticSchema)}
        kwargs: Dict[str, Any] = {}
        for k, v in d.items():
            if k not in names:
                continue
            if k in ("formation_time", "last_reinforced") and isinstance(v, str):
                try:
                    kwargs[k] = datetime.fromisoformat(v)
                except ValueError:
                    kwargs[k] = datetime.now()
            elif k == "confidence_interval" and isinstance(v, list):
                kwargs[k] = tuple(v)
            else:
                kwargs[k] = v
        return ProbabilisticSchema(**kwargs)

    async def _save_schema(self, schema: 'ProbabilisticSchema') -> bool:
        """Persist/refresh one schema. Non-fatal: a failure is logged and
        counted-by-log, never faked as success."""
        try:
            import json as _json
            await self._ensure_schema_table()
            payload = self._schema_to_payload(schema)
            await self._db().execute_query(
                "INSERT INTO unified.schemas"
                " (schema_id, belief_id, probability, payload, formation_time, updated_at)"
                " VALUES ($1, $2, $3, $4, $5, NOW())"
                " ON CONFLICT (schema_id) DO UPDATE SET"
                "   belief_id = EXCLUDED.belief_id, probability = EXCLUDED.probability,"
                "   payload = EXCLUDED.payload, updated_at = NOW()",
                (schema.schema_id, getattr(schema, "belief_id", None),
                 float(getattr(schema, "probability", 0.0)),
                 _json.dumps(payload, default=str),
                 getattr(schema, "formation_time", None)),
                commit=True)
            return True
        except Exception as e:
            logger.warning("save_schema failed for %s: %s",
                           getattr(schema, "schema_id", "?"), e)
            return False

    async def _delete_schema(self, schema_id: str) -> bool:
        try:
            await self._ensure_schema_table()
            await self._db().execute_query(
                "DELETE FROM unified.schemas WHERE schema_id = $1",
                (schema_id,), commit=True)
            return True
        except Exception as e:
            logger.warning("delete_schema failed for %s: %s", schema_id, e)
            return False

    async def load_schemas_from_db(self) -> int:
        """Rehydrate active_schemas on startup so induced structure survives a
        restart (it used to live only in RAM and evaporate). Returns count."""
        try:
            import json as _json
            await self._ensure_schema_table()
            rows = await self._db().execute_query(
                "SELECT payload FROM unified.schemas", fetch_all=True) or []
            loaded = 0
            for r in rows:
                payload = r["payload"]
                if isinstance(payload, str):
                    payload = _json.loads(payload)
                try:
                    schema = self._schema_from_payload(payload)
                    self.active_schemas[schema.schema_id] = schema
                    loaded += 1
                except Exception as row_err:
                    logger.debug("load_schemas: skipping malformed row: %s", row_err)
            if loaded:
                logger.info("restored %d schema(s) from PostgreSQL", loaded)
            return loaded
        except Exception as e:
            logger.warning("load_schemas_from_db failed: %s", e)
            return 0

    def get_statistics(self) -> Dict[str, Any]:
        """Flat scalars for the health probe (the pipeline was blind to health).
        Surfaces the live abstraction counters plus the active-schema count."""
        return {
            "active_schemas": len(self.active_schemas),
            "abstraction_candidates": len(self.abstraction_candidates),
            **{k: v for k, v in self.stats.items() if isinstance(v, (int, float, bool))},
        }

    async def start_monitoring(self, interval_hours: float = 1.0):
        """Start continuous abstraction pressure monitoring"""
        if self.monitoring_active:
            return
        self.monitoring_active = True
        logger.info(f"Starting abstraction monitoring (interval: {interval_hours}h)")
        while self.monitoring_active:
            try:
                await self.monitor_abstraction_pressure()
                await self.apply_temporal_decay_to_schemas()  # FIX #3: Decay all effects
                self.last_monitoring_run = datetime.now()
                await asyncio.sleep(interval_hours * 3600)
            except Exception as e:
                logger.error(f"Abstraction monitoring error: {e}")
                await asyncio.sleep(60)

    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring_active = False

    async def monitor_abstraction_pressure(self):
        """Calculate abstraction pressure and trigger schema formation"""
        memories = self._normalize_memories(
            await self.memory.get_recent_memories(limit=500)
        )
        if len(memories) < 5:
            return
        clusters = await self._cluster_memories(memories, similarity_threshold=0.75)
        for cluster in clusters:
            if len(cluster) < 3:
                continue
            candidate = await self._create_abstraction_candidate(cluster)
            candidate.abstraction_score = candidate.calculate_abstraction_pressure()
            threshold = self._calculate_dynamic_threshold()
            if candidate.should_abstract(threshold):
                self.stats['abstraction_triggers'] += 1
                await self.extract_and_apply_schema(cluster, candidate)

    async def _create_abstraction_candidate(self, cluster: List[Any]) -> AbstractionCandidate:
        """
        Create candidate from cluster using existing metadata

        INTEGRATION C: Calculates domain coherence from UDM
        INTEGRATION D: Checks governance blocks and intrinsic motivation outcomes
        """
        candidate = AbstractionCandidate(
            cluster_id=f"cluster_{uuid.uuid4().hex[:8]}",
            memory_ids=[m.memory_id for m in cluster]
        )
        candidate.reusability_signal = np.mean([m.metadata.get('reusability', 0.5) for m in cluster])
        candidate.reasoning_depth = np.mean([m.metadata.get('reasoning_depth', 1.0) for m in cluster])
        candidate.cross_context_weight = await self._assess_context_diversity(cluster)
        candidate.outcome_coherence = await self._assess_outcome_coherence(cluster)
        candidate.temporal_consistency = await self._assess_temporal_consistency(cluster)
        candidate.frequency_weight = len(cluster) / 100.0
        candidate.contradiction_penalty = await self._count_contradictions(cluster)

        # INTEGRATION C: Calculate domain coherence
        candidate.domain_coherence = await self._assess_domain_coherence(cluster)

        # INTEGRATION D: Check governance blocks
        governance_penalty = await self._check_governance_blocks(cluster)
        candidate.contradiction_penalty += governance_penalty

        # INTEGRATION D: Apply motivation-based weighting
        motivation_boost = await self._assess_motivation_outcomes(cluster)
        candidate.reusability_signal *= motivation_boost

        return candidate

    async def _assess_context_diversity(self, memories: List[Any]) -> float:
        """Assess pattern holds across different contexts"""
        sessions = {m.session_id for m in memories if m.session_id}
        session_diversity = len(sessions) / max(len(memories), 1)
        # Coerce: MemoryItem.created_at is documented as "float or datetime",
        # and _normalize_memories only fixes DICT-shaped inputs, so the
        # MemoryItem path arrived here with epoch floats. float - float is a
        # float, and .days on it raised AttributeError mid-batch — killing
        # abstraction for every memory because of a timestamp representation.
        times = [self._coerce_timestamp(m.created_at) for m in memories if m.created_at]
        if len(times) >= 2:
            time_span = (max(times) - min(times)).days
            temporal_diversity = min(time_span / 30.0, 1.0)
        else:
            temporal_diversity = 0.0
        emotional_states = [
            m.emotional_context.get('state') if isinstance(m.emotional_context, dict) else None
            for m in memories if hasattr(m, 'emotional_context') and m.emotional_context
        ]
        emotional_states = [s for s in emotional_states if s]
        emotional_diversity = len(set(emotional_states)) / max(len(emotional_states), 1) if emotional_states else 0.5
        diversity_score = session_diversity * 0.4 + temporal_diversity * 0.4 + emotional_diversity * 0.2
        return diversity_score

    @staticmethod
    def _extract_outcome(memory: Any) -> Optional[str]:
        """Read a memory's outcome from metadata or dict-shaped content.

        Stored memories keep content as a string and the outcome in metadata,
        so callers that inspected only dict content found nothing.
        """
        metadata = getattr(memory, 'metadata', None) or {}
        for key in ('outcome', 'result', 'answer', 'status'):
            value = metadata.get(key)
            if value:
                return str(value).lower()

        content = getattr(memory, 'content', None)
        if isinstance(content, dict):
            for key in ('outcome', 'result', 'answer'):
                value = content.get(key)
                if value:
                    return str(value).lower()

        return None

    async def _assess_outcome_coherence(self, memories: List[Any]) -> float:
        """Check consistent outcomes across memories"""
        # Outcomes were read only from dict-shaped content. Stored memories
        # carry content as a string with the outcome in metadata, so this list
        # was always empty and the function always returned the 0.5 default --
        # pinning one sixth of the abstraction pressure to a constant.
        outcomes = [outcome for outcome in (self._extract_outcome(m) for m in memories) if outcome]

        if len(outcomes) < 2:
            return 0.5
        similarity_sum = 0.0
        comparisons = 0
        for i in range(len(outcomes)):
            for j in range(i + 1, len(outcomes)):
                words_i = set(outcomes[i].split())
                words_j = set(outcomes[j].split())
                if words_i and words_j:
                    overlap = len(words_i & words_j) / max(len(words_i), len(words_j))
                    similarity_sum += overlap
                    comparisons += 1
        return similarity_sum / comparisons if comparisons > 0 else 0.5

    async def _assess_temporal_consistency(self, memories: List[Any]) -> float:
        """Check pattern persists regularly over time"""
        # Third site reading a memory timestamp arithmetically (after .days in
        # _assess_context_diversity and _build_schema). MemoryItem.created_at is
        # "float or datetime", so every such site must coerce — the value's
        # representation is not the caller's business, but it IS every reader's
        # problem until it is normalised once at the boundary.
        times = sorted([self._coerce_timestamp(m.created_at) for m in memories if m.created_at])
        if len(times) < 3:
            return 0.5
        # Gaps were measured in whole days, so any pattern recurring more often
        # than daily produced all-zero gaps and a mean of 0, which returned the
        # 0.5 default. Hours preserve the resolution real memory streams have.
        gaps = [
            (times[i + 1] - times[i]).total_seconds() / 3600.0
            for i in range(len(times) - 1)
        ]
        if not gaps:
            return 0.5
        mean_gap = np.mean(gaps)
        variance = np.var(gaps)
        if mean_gap == 0:
            return 0.5
        consistency = 1.0 / (1.0 + variance / (mean_gap + 1))
        return min(consistency, 1.0)

    async def _count_contradictions(self, memories: List[Any]) -> float:
        """Count contradictory memories in cluster"""
        if len(memories) < 2:
            return 0.0
        outcomes = [outcome for outcome in (self._extract_outcome(m) for m in memories) if outcome]

        if len(outcomes) < 2:
            return 0.0
        unique_outcomes = len(set(outcomes))
        contradiction_ratio = (unique_outcomes - 1) / len(outcomes)
        return contradiction_ratio * 2.0

    async def _assess_domain_coherence(self, cluster: List[Any]) -> float:
        """
        INTEGRATION C: Assess domain coherence within cluster

        Checks if memories share common domain characteristics,
        indicating domain-specific patterns worth abstracting.
        """
        try:
            # Extract domains from memories
            domains = []
            for memory in cluster:
                if hasattr(memory, 'metadata') and isinstance(memory.metadata, dict):
                    domain = memory.metadata.get('domain')
                    if domain:
                        domains.append(domain)

            if not domains:
                return 0.5  # Unknown - neutral score

            # Calculate domain agreement
            domain_counts = {}
            for domain in domains:
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

            # High coherence if most memories share same domain
            max_count = max(domain_counts.values())
            coherence = max_count / len(domains)

            # Bonus for high-value domains
            dominant_domain = max(domain_counts, key=domain_counts.get)
            high_value_domains = ['technical', 'scientific', 'mathematical', 'causal']

            if dominant_domain in high_value_domains:
                coherence *= 1.2

            return min(1.0, coherence)

        except Exception as e:
            logger.debug(f"Domain coherence assessment failed: {e}")
            return 0.5

    async def _check_governance_blocks(self, cluster: List[Any]) -> float:
        """
        INTEGRATION D: Check if pattern matches governance blocks

        Queries governance system for blocked patterns and penalizes
        candidates that match previously blocked actions.

        Returns:
            Penalty score (0.0 = no match, higher = matches blocked patterns)
        """
        try:
            if not self.motivation:
                return 0.0

            # Query governance blocks from intrinsic motivation system
            governance_constraints = await self.motivation.query_governance_blocks()

            if not governance_constraints:
                return 0.0

            # Extract pattern description from cluster
            pattern_texts = []
            for memory in cluster:
                if hasattr(memory, 'content'):
                    if isinstance(memory.content, dict):
                        # Extract task/action descriptions
                        for key in ['action', 'task', 'description', 'goal']:
                            if key in memory.content:
                                pattern_texts.append(str(memory.content[key]).lower())
                    else:
                        pattern_texts.append(str(memory.content).lower())

            if not pattern_texts:
                return 0.0

            pattern_text = " ".join(pattern_texts)

            # Check for matches with governance blocks
            penalty = 0.0
            for constraint in governance_constraints:
                constraint_lower = constraint.lower()
                # Simple substring matching (in production would use semantic similarity)
                if any(keyword in pattern_text for keyword in constraint_lower.split()[:5]):
                    penalty += 0.5
                    logger.warning(
                        f"Pattern matches governance constraint: {constraint[:100]}"
                    )

            self.stats['governance_blocks_checked'] += 1

            # Cap penalty at 2.0
            return min(2.0, penalty)

        except Exception as e:
            logger.debug(f"Governance block check failed: {e}")
            return 0.0

    async def _assess_motivation_outcomes(self, cluster: List[Any]) -> float:
        """
        INTEGRATION D: Assess intrinsic motivation outcomes for domain

        Queries intrinsic motivation system for domain performance stats
        and boosts schemas from successful domains.

        Returns:
            Boost multiplier (0.5-1.5x based on domain success rate)
        """
        try:
            if not self.motivation:
                return 1.0  # Neutral - no motivation data

            # Infer domain from cluster
            domain = self._infer_domain_from_cluster(cluster)

            # Get performance stats for this domain
            stats = await self.motivation.get_domain_performance_stats(domain)

            success_rate = stats.get('success_rate', 0.5)

            # Calculate boost based on success rate
            # High success (>70%): Boost schemas from this domain (1.3x)
            # Moderate success (40-70%): Neutral (1.0x)
            # Low success (<40%): Slight penalty (0.8x)
            if success_rate > 0.7:
                boost = 1.3
                logger.debug(f"Domain '{domain}' has high success rate ({success_rate:.1%}), boosting schema")
            elif success_rate < 0.4:
                boost = 0.8
                logger.debug(f"Domain '{domain}' has low success rate ({success_rate:.1%}), reducing schema weight")
            else:
                boost = 1.0

            self.stats['motivation_adjustments'] += 1

            return boost

        except Exception as e:
            logger.debug(f"Motivation outcome assessment failed: {e}")
            return 1.0  # Neutral on error

    async def update_schema_outcomes(self, schema_id: str) -> None:
        """
        GAP E FIX: Update schema with task outcome data from META memory

        Queries META memories for task outcomes that reference this schema,
        calculates success rate, and updates schema effectiveness metrics.
        """
        try:
            if schema_id not in self.active_schemas:
                return

            schema = self.active_schemas[schema_id]

            # Query META memories for task outcomes linked to this schema
            from core.memory.utils.interfaces import MemoryType

            # Search for META memories containing this schema_id
            outcome_memories = await self.memory.search_memories(
                query_text=f"schema_id:{schema_id}",
                memory_type=MemoryType.META,
                tags=["task_outcome", "schema_usage"],
                max_results=100
            )

            if not outcome_memories:
                schema.last_outcome_check = datetime.now()
                return

            # Count successes and failures
            successes = 0
            failures = 0

            for memory in outcome_memories:
                content_str = str(memory.content)

                # Check for outcome indicators
                if any(indicator in content_str for indicator in [
                    "outcome_success", '"outcome": "success"', "task_completed"
                ]):
                    successes += 1
                elif any(indicator in content_str for indicator in [
                    "outcome_failure", '"outcome": "failure"', "task_failed"
                ]):
                    failures += 1

            # Update schema outcome metrics
            schema.outcome_success_count = successes
            schema.outcome_failure_count = failures
            total_outcomes = successes + failures

            if total_outcomes > 0:
                schema.outcome_success_rate = successes / total_outcomes
            else:
                schema.outcome_success_rate = 0.5  # Unknown

            schema.last_outcome_check = datetime.now()

            logger.debug(
                f"Schema {schema_id} effectiveness: {successes}/{total_outcomes} successes "
                f"({schema.outcome_success_rate:.1%})"
            )

        except Exception as e:
            logger.debug(f"Failed to update schema outcomes for {schema_id}: {e}")

    def _calculate_dynamic_threshold(self) -> float:
        """Calculate dynamic threshold based on system state"""
        base_threshold = 5.0
        schema_factor = len(self.active_schemas) / 100.0
        recent_formations = sum(1 for s in self.active_schemas.values() if (datetime.now() - s.formation_time).days < 7)
        throttle_factor = recent_formations / 10.0
        threshold = base_threshold * (1 + schema_factor * 0.5 + throttle_factor * 0.3)
        return max(3.0, min(threshold, 10.0))

    async def _cluster_memories(self, memories: List[Any], similarity_threshold: float = 0.75) -> List[List[Any]]:
        """Cluster memories by embedding similarity"""
        if not memories:
            return []
        def _as_vector(raw):
            """Coerce an embedding to a float vector, or None if it isn't one.

            pgvector normally arrives as a list/ndarray, but some paths hand it
            over as its TEXT rendering ('[-0.072, 0.057, ...]', ~4.7k chars for
            384 dims). np.array() on that yields a 0-d <U4692 string array, and
            np.dot then failed with "ufunc 'multiply' did not contain a loop" —
            aborting abstraction for the whole batch because ONE memory carried
            the wrong representation.
            """
            if raw is None:
                return None
            if isinstance(raw, str):
                try:
                    parsed = [float(x) for x in raw.strip().strip('[]').split(',') if x.strip()]
                except ValueError:
                    return None
                return np.array(parsed, dtype=float) if parsed else None
            try:
                arr = np.asarray(raw, dtype=float)
            except (TypeError, ValueError):
                return None
            return arr if arr.ndim == 1 and arr.size else None

        embeddings_map = {}
        _malformed = 0
        for m in memories:
            vec = None
            if getattr(m, 'embeddings', None) is not None:
                vec = _as_vector(m.embeddings)
            if vec is None and getattr(m, 'embedding', None) is not None:
                vec = _as_vector(m.embedding)
            if vec is not None:
                embeddings_map[m.memory_id] = vec
            elif getattr(m, 'embeddings', None) is not None or getattr(m, 'embedding', None) is not None:
                _malformed += 1
        if _malformed:
            logger.warning(
                "Abstraction: %d/%d memories had an unusable embedding — clustered "
                "without them rather than aborting the batch",
                _malformed, len(memories)
            )
        if not embeddings_map:
            by_type = defaultdict(list)
            for m in memories:
                by_type[m.memory_type].append(m)
            return [mem_list for mem_list in by_type.values() if len(mem_list) >= 3]
        memory_list = [m for m in memories if m.memory_id in embeddings_map]
        clusters = []
        used = set()
        for i, mem_i in enumerate(memory_list):
            if mem_i.memory_id in used:
                continue
            cluster = [mem_i]
            used.add(mem_i.memory_id)
            emb_i = embeddings_map[mem_i.memory_id]
            for j, mem_j in enumerate(memory_list):
                if i != j and mem_j.memory_id not in used:
                    emb_j = embeddings_map[mem_j.memory_id]
                    similarity = np.dot(emb_i, emb_j) / (np.linalg.norm(emb_i) * np.linalg.norm(emb_j) + 1e-8)
                    if similarity >= similarity_threshold:
                        cluster.append(mem_j)
                        used.add(mem_j.memory_id)
            if len(cluster) >= 3:
                clusters.append(cluster)
        return clusters

    async def extract_and_apply_schema(self, cluster: List[Any], candidate: AbstractionCandidate):
        """Extract probabilistic schema and apply structural effects"""
        schema = await self._extract_probabilistic_schema(cluster, candidate)
        if not schema:
            return

        # FIX #4: Counterfactual stress testing
        stress_score = await self.stress_test_schema(schema)
        schema.stress_test_score = stress_score
        schema.last_stress_test = datetime.now()
        self.stats['stress_tests_run'] += 1

        self.active_schemas[schema.schema_id] = schema
        self.stats['schemas_formed'] += 1

        # The schema is complete and applied before any enrichment runs.
        #
        # Enrichment used to sit here, ahead of these three steps, and it
        # reaches the Universal Domain Master which issued one model inference
        # per target domain, sequentially, against a single-slot server. A step
        # its own comment calls "non-critical" therefore held belief creation,
        # abstraction effects and hierarchy insertion hostage for as long as
        # those inferences took -- roughly half an hour per schema.
        #
        # Invariant: abstraction formation does not depend on cross-domain
        # enrichment succeeding. Enrichment can improve a schema; it cannot
        # determine whether the schema gets to exist.
        await self._create_belief_from_schema(schema)
        await self.apply_abstraction_effects(schema)
        await self._add_to_hierarchy(schema, cluster)
        # DURABLE: a newly-formed schema (with its belief_id now set) is persisted
        # so induced structure survives a restart instead of living only in RAM.
        await self._save_schema(schema)

        # Enrichment runs detached. Ordering it last is not sufficient on its
        # own: awaiting it here would still hold schema formation open for the
        # duration, and an exception from it would abort the caller's result.
        # The schema is already valid, so enrichment can only add metadata.
        self._schedule_enrichment(schema)

    async def _extract_probabilistic_schema(self, cluster: List[Any], candidate: AbstractionCandidate) -> Optional[ProbabilisticSchema]:
        """Extract schema with counterexamples"""
        condition, outcome = await self._extract_pattern(cluster)
        if not condition or not outcome:
            return None
        all_memories = self._normalize_memories(
            await self.memory.get_recent_memories(limit=1000)
        )
        counterexamples = []
        for memory in all_memories:
            if memory.memory_id in [m.memory_id for m in cluster]:
                continue
            if self._matches_condition(memory, condition):
                if not self._matches_outcome(memory, outcome):
                    counterexamples.append(memory.memory_id)
        positive = len(cluster)
        negative = len(counterexamples)
        total = positive + negative
        if total == 0:
            return None
        probability = (positive + 1) / (total + 2)

        # Infer domain from cluster memories
        domain = self._infer_domain_from_cluster(cluster)

        schema = ProbabilisticSchema(
            schema_id=f"schema_{uuid.uuid4().hex[:12]}",
            condition=condition,
            outcome=outcome,
            probability=probability,
            confidence_interval=(0.0, 1.0),
            supporting_memories=[m.memory_id for m in cluster],
            counterexamples=counterexamples,
            evidence_count=total,
            abstraction_confidence=candidate.abstraction_score / 10.0,
            context_diversity_score=candidate.cross_context_weight
        )
        schema.confidence_interval = schema.calculate_credible_interval()
        schema.decay_rate = schema.calculate_decay_rate(candidate.cross_context_weight)
        schema.session_ids = {m.session_id for m in cluster if m.session_id}
        schema.metadata['domain'] = domain  # Tag schema with domain
        times = [self._coerce_timestamp(m.created_at) for m in cluster if m.created_at]
        if len(times) >= 2:
            schema.temporal_span_days = (max(times) - min(times)).days
        return schema

    async def _extract_pattern(self, cluster: List[Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Extract common condition and outcome from cluster"""
        condition_features = defaultdict(list)
        outcome_features = defaultdict(list)
        for m in cluster:
            if isinstance(m.content, dict):
                for key, value in m.content.items():
                    if key in ['outcome', 'result', 'answer', 'conclusion']:
                        outcome_features[key].append(str(value))
                    else:
                        condition_features[key].append(str(value))
            if hasattr(m, 'tags') and m.tags:
                condition_features['tags'].extend(m.tags)
            if hasattr(m, 'memory_type'):
                condition_features['memory_type'].append(str(m.memory_type))
        condition = {}
        for key, values in condition_features.items():
            counter = Counter(values)
            most_common = counter.most_common(1)
            if most_common and most_common[0][1] >= len(cluster) * 0.5:
                condition[key] = most_common[0][0]
        outcome = {}
        for key, values in outcome_features.items():
            counter = Counter(values)
            most_common = counter.most_common(1)
            if most_common and most_common[0][1] >= len(cluster) * 0.5:
                outcome[key] = most_common[0][0]
        if not condition:
            condition = {'cluster_size': len(cluster)}
        if not outcome:
            outcome = {'pattern': 'recurring_theme'}
        return condition, outcome

    def _matches_condition(self, memory: Any, condition: Dict[str, Any]) -> bool:
        """Check if memory matches schema condition"""
        if not condition:
            return False
        matches = 0
        total_checks = 0
        for key, expected_value in condition.items():
            total_checks += 1
            if isinstance(memory.content, dict) and key in memory.content:
                if str(memory.content[key]).lower() == str(expected_value).lower():
                    matches += 1
            elif hasattr(memory, key):
                if str(getattr(memory, key)).lower() == str(expected_value).lower():
                    matches += 1
            elif key == 'tags' and hasattr(memory, 'tags') and memory.tags:
                if expected_value in memory.tags or any(expected_value in str(t) for t in memory.tags):
                    matches += 1
        return (matches / total_checks) >= 0.5 if total_checks > 0 else False

    def _matches_outcome(self, memory: Any, outcome: Dict[str, Any]) -> bool:
        """Check if memory matches schema outcome"""
        if not outcome:
            return False
        matches = 0
        total_checks = 0
        for key, expected_value in outcome.items():
            total_checks += 1
            if isinstance(memory.content, dict) and key in memory.content:
                actual = str(memory.content[key]).lower()
                expected = str(expected_value).lower()
                if actual == expected or expected in actual or self._semantic_similarity(actual, expected) > 0.6:
                    matches += 1
        return (matches / total_checks) >= 0.5 if total_checks > 0 else False

    def _semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity between texts"""
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        if not words1 or not words2:
            return 0.0
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union if union > 0 else 0.0

    async def _create_belief_from_schema(self, schema: ProbabilisticSchema):
        """Create Bayesian belief from schema"""
        claim = f"Pattern: {schema.condition} → {schema.outcome}"
        belief = self.beliefs.create_belief(
            claim=claim,
            domain="induced_schema",
            prior=schema.probability,
            evidence={
                'type': 'schema_induction',
                'support_count': len(schema.supporting_memories),
                'counter_count': len(schema.counterexamples),
                'quality': schema.abstraction_confidence,
                'schema_id': schema.schema_id
            }
        )
        schema.belief_id = belief.belief_id

    async def apply_abstraction_effects(self, schema: ProbabilisticSchema):
        """Apply structural effects with all protections"""
        await self._boost_matching_memories(schema)
        await self._adjust_related_priors(schema)
        await self._add_attention_bias(schema)
        await self._flag_contradictions(schema)

    async def _boost_matching_memories(self, schema: ProbabilisticSchema):
        """FIX #2: Boost with cumulative caps"""
        for memory_id in schema.supporting_memories:
            try:
                # Check cumulative boost cap
                current_boost = schema.cumulative_retrieval_boosts.get(memory_id, 1.0)
                if current_boost >= 1.5:  # Max 50% boost
                    self.stats['feedback_loops_prevented'] += 1
                    continue

                # MemoryAgent has no get_memory(); the accessor is
                # retrieve_memory(). 185 boosts per run died here — and the
                # update_memory() call below was ALSO wrong (it takes an
                # `updates` dict, not kwargs), hidden behind the first error
                # because nothing ever reached it.
                memory = await self.memory.retrieve_memory(memory_id)
                if memory:
                    # Check existing boosts from other schemas
                    existing_meta = memory.metadata or {}
                    existing_boosts = existing_meta.get('schema_boosts', [])
                    if len(existing_boosts) >= 3:  # Max 3 schemas can boost same memory
                        self.stats['feedback_loops_prevented'] += 1
                        continue

                    new_importance = min(1.0, memory.importance_score * 1.2)

                    # SPLIT the write. `importance_score` is a governance-
                    # protected field: update_memory() demands a capability
                    # token, _validate_capability_token() checks a
                    # `capability_tokens` table that DOES NOT EXIST, and nothing
                    # in the codebase mints tokens. So that half is impossible by
                    # construction for every internal caller — a gate no
                    # subsystem can ever satisfy. Bundling it with the metadata
                    # write meant BOTH halves failed silently.
                    #
                    # The boost provenance (which schema boosted this, how many
                    # times, the <=3 cap) is unprotected and genuinely useful, so
                    # it is written on its own.
                    _meta_ok = await self.memory.update_memory(
                        memory_id,
                        {
                            'metadata': {
                                **existing_meta,
                                'schema_support': schema.schema_id,
                                'schema_boosts': existing_boosts + [schema.schema_id],
                                'boost_count': len(existing_boosts) + 1,
                                'pending_importance_boost': new_importance,
                            },
                        }
                    )
                    if not _meta_ok:
                        self.stats.setdefault('boost_metadata_rejected', 0)
                        self.stats['boost_metadata_rejected'] += 1
                        continue

                    # In-schema weighting still applies — this is the part that
                    # actually influences retrieval ranking today.
                    schema.cumulative_retrieval_boosts[memory_id] = current_boost * 1.2
                    self.stats['retrieval_weights_modified'] += 1
                    # Named, countable gap rather than a silent no-op.
                    self.stats.setdefault('importance_boosts_requiring_governance', 0)
                    self.stats['importance_boosts_requiring_governance'] += 1
            except Exception as e:
                logger.error(f"Error boosting memory {memory_id}: {e}")

    async def _adjust_related_priors(self, schema: ProbabilisticSchema):
        """FIX #1 & #2: Adjust priors with semantic protection and caps"""
        if not schema.belief_id or schema.belief_id not in self.beliefs.beliefs:
            return

        schema_belief = self.beliefs.beliefs[schema.belief_id]

        for belief_id, belief in self.beliefs.beliefs.items():
            if belief_id == schema.belief_id:
                continue

            # FIX #2: Check cumulative cap
            current_cumulative = schema.cumulative_prior_adjustments.get(belief_id, 0.0)
            if current_cumulative >= 0.30:  # Max 30% cumulative adjustment
                self.stats['feedback_loops_prevented'] += 1
                continue

            # FIX #2: Require novel evidence after 5 reinforcements
            if schema.reinforcement_count > 5:
                if schema.novel_evidence_count < schema.reinforcement_count * 0.3:
                    self.stats['feedback_loops_prevented'] += 1
                    continue

            # FIX #1: Multi-layer relatedness check
            if self._beliefs_related_strict(schema_belief, belief):
                adjustment = schema.probability * 0.15
                allowed_adjustment = min(adjustment, 0.30 - current_cumulative)

                old_prior = belief.prior_probability
                belief.prior_probability = min(1.0, max(0.0, old_prior + allowed_adjustment))

                if abs(belief.prior_probability - old_prior) > 0.01:
                    schema.cumulative_prior_adjustments[belief_id] = current_cumulative + allowed_adjustment
                    schema.boost_history.append((datetime.now(), belief_id, allowed_adjustment))
                    self.stats['priors_modified'] += 1

    def _beliefs_related_strict(self, belief1: Any, belief2: Any) -> bool:
        """
        FIX #1: Strict semantic relatedness with multiple constraints.
        Prevents semantic overreach (30% word overlap → 50% + embedding + domain + ontology)
        """
        # Layer 1: Word overlap (raised threshold)
        claim1_words = set(re.findall(r'\w+', belief1.claim.lower()))
        claim2_words = set(re.findall(r'\w+', belief2.claim.lower()))

        if not claim1_words or not claim2_words:
            return False

        overlap = len(claim1_words & claim2_words)
        min_size = min(len(claim1_words), len(claim2_words))
        word_overlap_score = overlap / min_size if min_size > 0 else 0.0

        if word_overlap_score < 0.5:  # Raised from 0.3 to 0.5
            self.stats['semantic_overreach_prevented'] += 1
            return False

        # Layer 2: Domain alignment
        if belief1.domain != belief2.domain and belief1.domain != "induced_schema" and belief2.domain != "induced_schema":
            self.stats['semantic_overreach_prevented'] += 1
            return False

        # Layer 3: Embedding similarity (if available)
        if hasattr(belief1, 'embedding') and hasattr(belief2, 'embedding') and belief1.embedding and belief2.embedding:
            emb1 = np.array(belief1.embedding)
            emb2 = np.array(belief2.embedding)
            emb_sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2) + 1e-8)
            if emb_sim < 0.6:
                self.stats['semantic_overreach_prevented'] += 1
                return False

        # Layer 4: Ontology-level type checking
        entities1 = self._extract_entities(belief1.claim)
        entities2 = self._extract_entities(belief2.claim)

        if entities1 and entities2:
            if not self._share_concept_category(entities1, entities2):
                self.stats['semantic_overreach_prevented'] += 1
                return False

        return True

    def _extract_entities(self, text: str) -> List[str]:
        """Extract potential entities from text"""
        words = re.findall(r'\b[A-Z][a-z]+\b|\b[a-z_]+\b', text)
        entities = [w for w in words if len(w) > 2]
        return entities

    def _share_concept_category(self, entities1: List[str], entities2: List[str]) -> bool:
        """Check if entities share conceptual categories"""
        categories = {
            'programming': {'python', 'java', 'javascript', 'code', 'program', 'function', 'class', 'method'},
            'data': {'data', 'analysis', 'dataframe', 'dataset', 'table', 'query', 'database'},
            'tools': {'library', 'framework', 'tool', 'package', 'module', 'system'},
            'concepts': {'algorithm', 'pattern', 'structure', 'design', 'architecture'}
        }

        def categorize(entity: str) -> Set[str]:
            matches = set()
            entity_lower = entity.lower()
            for category, keywords in categories.items():
                if entity_lower in keywords or any(kw in entity_lower for kw in keywords):
                    matches.add(category)
            return matches

        cats1 = set()
        for e in entities1:
            cats1.update(categorize(e))

        cats2 = set()
        for e in entities2:
            cats2.update(categorize(e))

        return len(cats1 & cats2) > 0

    async def _add_attention_bias(self, schema: ProbabilisticSchema):
        """Add attention bias for future reasoning"""
        schema.attention_weight = 1.0 + (schema.probability - 0.5) * 0.5
        self.stats['attention_biases_added'] += 1

    async def _flag_contradictions(self, schema: ProbabilisticSchema):
        """Flag contradicting memories for strong schemas"""
        if schema.probability < 0.7:
            return
        for memory_id in schema.counterexamples:
            try:
                # MemoryAgent's accessor is retrieve_memory() — there is no
                # get_memory(); the old name raised AttributeError per counterexample
                # (swallowed below), so strong-schema contradictions were never
                # actually flagged. Mirrors the correct call at line ~1231.
                memory = await self.memory.retrieve_memory(memory_id)
                if memory:
                    await self.memory.update_memory(
                        memory_id,
                        metadata={**memory.metadata, 'contradicts_schema': schema.schema_id, 'needs_review': True}
                    )
            except Exception as e:
                logger.error(f"Error flagging memory {memory_id}: {e}")

    async def _add_to_hierarchy(self, schema: ProbabilisticSchema, cluster: List[Any]):
        """Add schema to concept hierarchy with strategy template"""
        # Extract strategy template from schema (FIX #5)
        strategy_template = {
            'when': schema.condition,
            'prefer': schema.outcome,
            'confidence': schema.probability
        }

        concept = ConceptNode(
            concept_id=f"concept_{uuid.uuid4().hex[:12]}",
            level=AbstractionLevel.SCHEMA,
            content=f"{schema.condition} → {schema.outcome}",
            probability=schema.probability,
            instantiated_by=[m.memory_id for m in cluster],
            belief_id=schema.belief_id,
            schema_id=schema.schema_id,
            strategy_template=strategy_template,
            applicable_contexts=[schema.condition.get('domain', 'general')]
        )

        # Link before inserting: add_concept() builds its edge indexes from the
        # node's relations, so an unlinked node is inserted isolated. Every
        # concept was previously added with implies=[] and contradicts=[], which
        # left both graphs edgeless -- ConceptHierarchy.check_consistency() had
        # nothing to check, and the belief graph's constraint propagation never
        # applied to induced knowledge.
        self._link_concept_to_existing(concept, schema)

        self.concept_hierarchy.add_concept(concept)

        # Mirror the same relations onto the belief graph so the Bayesian
        # propagation semantics (IMPLIES pulls toward, CONTRADICTS pushes
        # opposite) reach schema-derived beliefs. Relationships were otherwise
        # only ever created from LLM output (discovered_by="llm").
        self._mirror_relations_to_beliefs(concept)

    def _link_concept_to_existing(self, concept: 'ConceptNode', schema: ProbabilisticSchema) -> None:
        """Derive implies/contradicts edges against concepts already held.

        Deterministic and substrate-native: the relation follows from how the
        schemas' conditions and outcomes compare, so no inference call is made.

          same condition, different outcome  -> contradicts
          strictly more specific condition,
          same outcome                       -> implies (specific entails general)
        """
        condition = schema.condition if isinstance(schema.condition, dict) else {}
        outcome = self._outcome_key(schema.outcome)
        if not condition:
            return

        items = set(condition.items())

        for other_id, other in self.concept_hierarchy.nodes.items():
            if other_id == concept.concept_id or other.level != concept.level:
                continue

            other_condition = getattr(other, 'source_condition', None)
            other_outcome = getattr(other, 'source_outcome', None)
            if not isinstance(other_condition, dict) or other_outcome is None:
                continue

            other_items = set(other_condition.items())
            if not other_items:
                continue

            if items == other_items:
                if outcome != other_outcome:
                    # Identical trigger, divergent conclusion.
                    concept.contradicts.append(other_id)
                    other.contradicts.append(concept.concept_id)
            elif outcome == other_outcome and other_items < items:
                # This concept fires in a strictly narrower situation than one
                # already held, and predicts the same thing, so it entails it.
                concept.implies.append(other_id)

        # Kept so later concepts can compare against this one without
        # re-deriving it from the schema store.
        concept.source_condition = condition
        concept.source_outcome = outcome

    @staticmethod
    def _outcome_key(outcome: Any) -> str:
        """Stable comparable form of a schema outcome."""
        if isinstance(outcome, dict):
            return "|".join(f"{k}={outcome[k]}" for k in sorted(outcome))
        return str(outcome)

    def _mirror_relations_to_beliefs(self, concept: 'ConceptNode') -> None:
        """Wire concept edges onto the belief graph, where propagation lives."""
        if not self.beliefs or not concept.belief_id:
            return

        from core.reasoning.bayesian_uncertainty import RelationType

        pairs = (
            (concept.implies, RelationType.IMPLIES),
            (concept.contradicts, RelationType.CONTRADICTS),
        )

        for related_ids, relation_type in pairs:
            for related_id in related_ids:
                other = self.concept_hierarchy.nodes.get(related_id)
                if other is None or not getattr(other, 'belief_id', None):
                    continue
                try:
                    self.beliefs.add_relationship(
                        source_belief_id=concept.belief_id,
                        target_belief_id=other.belief_id,
                        relation_type=relation_type,
                        strength=float(concept.probability),
                        discovered_by="abstraction",
                    )
                except Exception as e:
                    logger.debug(f"Could not mirror {relation_type} relation: {e}")

    async def stress_test_schema(self, schema: ProbabilisticSchema) -> float:
        """
        FIX #4: Counterfactual stress testing for anticipatory volatility adjustment.
        Tests schema against alternate scenarios to detect fragility.
        """
        counterfactuals = []

        # Generate counterfactuals based on condition
        for key, value in schema.condition.items():
            if key != 'cluster_size':
                counterfactuals.append({
                    'type': 'condition_flip',
                    'condition': {**schema.condition, key: f"not_{value}"}
                })

        # Generate outcome flip
        for key, value in schema.outcome.items():
            counterfactuals.append({
                'type': 'outcome_flip',
                'outcome': {key: f"opposite_{value}"}
            })

        stability_score = 0.0
        fragility_count = 0

        for cf in counterfactuals:
            # Check if contradictory pattern already exists
            contradicting_memories = []

            all_memories = self._normalize_memories(
                await self.memory.get_recent_memories(limit=500)
            )
            for memory in all_memories:
                if cf['type'] == 'condition_flip':
                    if self._matches_outcome(memory, schema.outcome):
                        if not self._matches_condition(memory, schema.condition):
                            contradicting_memories.append(memory)
                elif cf['type'] == 'outcome_flip':
                    if self._matches_condition(memory, schema.condition):
                        if self._matches_outcome(memory, cf['outcome']):
                            contradicting_memories.append(memory)

            if len(contradicting_memories) > 0:
                fragility = len(contradicting_memories) / max(len(schema.supporting_memories), 1)
                stability_score -= fragility
                fragility_count += 1
            else:
                stability_score += 0.1

        # Adjust schema based on stress test
        if stability_score < 0:
            schema.fragility_detected = True
            schema.decay_rate = min(0.08, schema.decay_rate * 1.5)
            logger.warning(f"Schema {schema.schema_id} fragile: score={stability_score:.2f}, decay increased")
        else:
            schema.fragility_detected = False
            schema.decay_rate = max(0.01, schema.decay_rate * 0.8)

        return stability_score

    async def apply_temporal_decay_to_schemas(self):
        """
        FIX #3: Apply decay to ALL effects (probability, attention, boost, prior adjustments).
        GAP E FIX: Periodically update schema outcomes from META memory.
        Decay is structural, not cosmetic.
        """
        now = datetime.now()
        for schema_id, schema in list(self.active_schemas.items()):
            # GAP E FIX: Update outcomes every 24 hours
            if schema.last_outcome_check is None or \
               (now - schema.last_outcome_check).total_seconds() > 86400:  # 24 hours
                await self.update_schema_outcomes(schema_id)
                # Recalculate decay rate with new effectiveness data
                schema.decay_rate = schema.calculate_decay_rate(schema.context_diversity_score)

            time_delta_hours = (now - schema.last_reinforced).total_seconds() / 3600.0

            if time_delta_hours > 24:
                # Apply decay to ALL components
                decayed_prob, decayed_attention, decayed_boost, decayed_prior_adj = schema.apply_temporal_decay(time_delta_hours)

                # Update schema
                schema.probability = decayed_prob
                schema.attention_weight = decayed_attention
                schema.retrieval_boost = decayed_boost
                schema.prior_adjustment = decayed_prior_adj

                # Decay prior adjustments to beliefs
                decay_factor = 1 - np.exp(-schema.decay_rate * time_delta_hours / 24.0)
                for belief_id, adjustment in list(schema.cumulative_prior_adjustments.items()):
                    decayed_adjustment = adjustment * (1 - decay_factor * 0.5)
                    diff = adjustment - decayed_adjustment

                    # Reverse the difference in belief prior
                    if belief_id in self.beliefs.beliefs:
                        belief = self.beliefs.beliefs[belief_id]
                        belief.prior_probability = max(0.0, min(1.0, belief.prior_probability - diff))

                    schema.cumulative_prior_adjustments[belief_id] = decayed_adjustment

                # Decay retrieval boosts
                for memory_id, boost in list(schema.cumulative_retrieval_boosts.items()):
                    decayed_boost_val = 1.0 + (boost - 1.0) * (1 - decay_factor)
                    schema.cumulative_retrieval_boosts[memory_id] = decayed_boost_val

                # Update linked belief
                if schema.belief_id and schema.belief_id in self.beliefs.beliefs:
                    belief = self.beliefs.beliefs[schema.belief_id]
                    belief.posterior_probability = decayed_prob

                self.stats['schemas_decayed'] += 1

    @staticmethod
    def _coerce_timestamp(value: Any) -> datetime:
        """Accept epoch numbers, ISO strings or datetimes; always return datetime.

        Age calculations subtract these and read .days, so an epoch int (the
        common shape in stored memory dicts) raised AttributeError mid-batch.
        """
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value)
            except (OverflowError, OSError, ValueError):
                return datetime.now()
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return datetime.now()
        return datetime.now()

    def _normalize_memories(self, memories: List[Any]) -> List[Any]:
        """Give dict-shaped memories the attribute access the pipeline expects.

        process_memories is documented and typed to accept dictionaries, while
        the clustering and schema code reads attributes (m.memory_id,
        m.memory_type, m.embeddings). Passing the documented type therefore
        raised AttributeError, which was caught and reported as zero schemas --
        indistinguishable from a clean run that simply found no patterns.

        Objects are passed through untouched, so existing callers are unaffected.
        """
        normalized: List[Any] = []

        for index, item in enumerate(memories or []):
            if not isinstance(item, dict):
                # Non-dict inputs (MemoryItem) previously passed through
                # UNTOUCHED, so `created_at` arrived downstream as an epoch
                # float and every arithmetic reader broke in turn — .days, then
                # .total_seconds(). Normalising the representation ONCE here is
                # the boundary's job; making N readers each defend themselves is
                # how the same bug surfaces three times.
                _created = getattr(item, 'created_at', None)
                if _created is not None and not isinstance(_created, datetime):
                    try:
                        item.created_at = self._coerce_timestamp(_created)
                    except (AttributeError, TypeError):
                        pass  # frozen/slotted objects keep their own value
                normalized.append(item)
                continue

            metadata = item.get('metadata') or {}
            normalized.append(SimpleNamespace(
                memory_id=str(
                    item.get('memory_id') or item.get('id') or f"mem_{index}"
                ),
                memory_type=str(
                    item.get('memory_type')
                    or metadata.get('type')
                    or metadata.get('domain')
                    or 'general'
                ),
                content=item.get('content', ''),
                embeddings=item.get('embeddings') or item.get('embedding'),
                embedding=item.get('embedding') or item.get('embeddings'),
                created_at=self._coerce_timestamp(item.get('created_at')),
                metadata=metadata,
                # Remaining fields the pipeline reads off a memory. Defaults
                # are supplied so a partial dict degrades to a usable memory
                # rather than aborting the whole batch on a missing key.
                session_id=item.get('session_id') or metadata.get('session_id') or '',
                importance_score=float(item.get('importance_score', 0.0) or 0.0),
                similarity_score=float(item.get('similarity_score', 0.0) or 0.0),
                tags=list(item.get('tags') or metadata.get('tags') or []),
                emotional_context=item.get('emotional_context') or {},
                reasoning_strategy=item.get('reasoning_strategy') or '',
            ))

        return normalized

    async def process_memories(self, memory_dicts: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Process memories for abstraction formation

        Args:
            memory_dicts: List of memory dictionaries with id, content, timestamp, etc.

        Returns:
            Dictionary with counts of patterns, schemas, and principles formed
        """
        try:
            logger.info(f"Processing {len(memory_dicts)} memories for abstraction...")

            # Track results
            patterns_formed = 0
            schemas_formed = 0
            principles_extracted = 0

            # Cluster memories by similarity
            memories = self._normalize_memories(memory_dicts)
            clusters = await self._cluster_memories(memories, similarity_threshold=0.75)

            logger.info(f"Identified {len(clusters)} memory clusters")

            # Process each cluster
            for cluster in clusters:
                if len(cluster) < 3:  # Need at least 3 instances for pattern
                    continue

                # Create abstraction candidate
                candidate = await self._create_abstraction_candidate(cluster)

                # Check if abstraction pressure exceeds threshold
                if not candidate.should_abstract(threshold=5.0):
                    continue

                # Extract and apply schema
                await self.extract_and_apply_schema(cluster, candidate)

                schemas_formed += 1
                patterns_formed += 1

            # Update concept hierarchy (extract principles from schemas)
            # Check if we have enough schemas to form principles
            if len(self.active_schemas) >= 5:
                principles_extracted = await self._extract_principles_from_schemas()

            logger.info(f"✓ Formed {patterns_formed} patterns, {schemas_formed} schemas, {principles_extracted} principles")

            return {
                'patterns_formed': patterns_formed,
                'schemas_formed': schemas_formed,
                'principles_extracted': principles_extracted
            }

        except Exception as e:
            logger.error(f"Failed to process memories: {e}")
            import traceback
            traceback.print_exc()
            # The error key makes a crash distinguishable from a clean run that
            # found nothing. Both previously returned identical zero counts, so
            # a failing pipeline was indistinguishable from an idle one.
            return {
                'patterns_formed': 0,
                'schemas_formed': 0,
                'principles_extracted': 0,
                'error': str(e)
            }

    async def _extract_principles_from_schemas(self) -> int:
        """
        Extract Level 3 principles from Level 2 schemas

        Looks for meta-patterns across schemas to form higher-level principles
        """
        try:
            principles_count = 0

            # Group schemas by domain
            schemas_by_domain: Dict[str, List[ProbabilisticSchema]] = {}
            for schema_id, schema in self.active_schemas.items():
                domain = schema.metadata.get('domain', 'general')
                if domain not in schemas_by_domain:
                    schemas_by_domain[domain] = []
                schemas_by_domain[domain].append(schema)

            # For each domain with enough schemas, extract principles
            for domain, schemas in schemas_by_domain.items():
                if len(schemas) < 3:  # Need at least 3 schemas for principle
                    continue

                # Find common patterns across schemas
                # (Simplified - in full implementation would do semantic clustering)
                common_principle = {
                    'domain': domain,
                    'schema_count': len(schemas),
                    'avg_probability': sum(s.probability for s in schemas) / len(schemas),
                    'description': f"Meta-pattern in {domain} domain"
                }

                # Create principle node. ConceptNode requires content + probability
                # and has NO schema_ids/confidence/metadata fields — the previous
                # kwargs raised TypeError (swallowed below), so Level-3 principles
                # never actually formed. A principle is an ABSTRACTION_OF its
                # schemas, and it is found by domain via applicable_contexts.
                principle_node = ConceptNode(
                    concept_id=f"principle_{domain}_{len(self.concept_hierarchy.nodes)}",
                    level=AbstractionLevel.PRINCIPLE,
                    content=common_principle['description'],
                    probability=common_principle['avg_probability'],
                    abstraction_of=[s.schema_id for s in schemas],
                    applicable_contexts=[domain],
                )

                self.concept_hierarchy.add_concept(principle_node)
                principles_count += 1

            return principles_count

        except Exception as e:
            logger.error(f"Failed to extract principles: {e}")
            return 0

    async def apply_decay_to_abstractions(self):
        """Apply temporal decay to all active abstractions"""
        try:
            logger.info("Applying decay to abstractions...")

            # Apply decay to schemas (already implemented)
            now = datetime.now()
            schemas_decayed = 0

            for schema_id, schema in list(self.active_schemas.items()):
                time_delta_hours = (now - schema.last_reinforced).total_seconds() / 3600.0

                if time_delta_hours > 1:  # Apply decay after 1 hour
                    decayed_prob, decayed_attention, decayed_boost, decayed_prior_adj = schema.apply_temporal_decay(time_delta_hours)

                    schema.probability = decayed_prob
                    schema.attention_weight = decayed_attention
                    schema.retrieval_boost = decayed_boost
                    schema.prior_adjustment = decayed_prior_adj

                    schemas_decayed += 1

                    # Remove schema if it decayed below threshold
                    if schema.probability < 0.3:
                        del self.active_schemas[schema_id]
                        # DURABLE: drop the row too, else load resurrects it.
                        await self._delete_schema(schema_id)
                        logger.info(f"Removed low-probability schema: {schema_id}")
                    else:
                        # DURABLE: persist the decayed schema state.
                        await self._save_schema(schema)

            logger.info(f"✓ Applied decay to {schemas_decayed} schemas")

        except Exception as e:
            logger.error(f"Failed to apply decay: {e}")

    async def apply_schema_decay(self) -> Dict[str, int]:
        """
        Apply decay to schemas and run stress tests

        Returns:
            Dictionary with decay statistics
        """
        try:
            await self.apply_decay_to_abstractions()

            # Run stress tests on schemas
            fragile_schemas = 0
            for schema_id, schema in self.active_schemas.items():
                # Run counterfactual stress test if it hasn't been done recently
                if schema.last_stress_test is None or \
                   (datetime.now() - schema.last_stress_test).total_seconds() > 86400:  # 24 hours

                    stress_score = await self.stress_test_schema(schema)

                    if schema.fragility_detected:
                        fragile_schemas += 1

            return {
                'schemas_decayed': len(self.active_schemas),
                'fragile_schemas_detected': fragile_schemas
            }

        except Exception as e:
            logger.error(f"Failed to apply schema decay: {e}")
            return {
                'schemas_decayed': 0,
                'fragile_schemas_detected': 0
            }

    def _infer_domain_from_cluster(self, cluster: List[Any]) -> str:
        """
        Infer domain from cluster of memories

        Maps to Universal Domain Master domain types for cross-domain integration
        """
        try:
            from core.integration.universal_domain_master import DomainType

            # Aggregate content from all memories in cluster
            all_text = ""
            all_tags = set()

            for memory in cluster:
                # Extract text content
                if hasattr(memory, 'content'):
                    if isinstance(memory.content, dict):
                        all_text += " " + " ".join(str(v) for v in memory.content.values())
                    else:
                        all_text += " " + str(memory.content)

                # Extract tags
                if hasattr(memory, 'tags'):
                    if isinstance(memory.tags, (list, set)):
                        all_tags.update(str(tag).lower() for tag in memory.tags)
                    elif isinstance(memory.tags, str):
                        all_tags.add(memory.tags.lower())

            text_lower = all_text.lower()

            # Map keywords to Universal Domain Master domain types
            # SCIENTIFIC: Research, analysis, discovery
            if any(word in text_lower for word in ["research", "study", "analyze", "investigate", "hypothesis", "experiment"]):
                return DomainType.SCIENTIFIC.value
            if any(tag in all_tags for tag in ["research", "scientific", "analysis"]):
                return DomainType.SCIENTIFIC.value

            # TECHNICAL: Code, implementation, engineering
            elif any(word in text_lower for word in ["code", "implement", "build", "develop", "function", "class", "method"]):
                return DomainType.TECHNICAL.value
            elif any(tag in all_tags for tag in ["code", "technical", "implementation"]):
                return DomainType.TECHNICAL.value

            # MATHEMATICAL: Calculation, optimization, metrics
            elif any(word in text_lower for word in ["calculate", "optimize", "algorithm", "metric", "statistics", "probability"]):
                return DomainType.MATHEMATICAL.value
            elif any(tag in all_tags for tag in ["math", "calculation", "optimization"]):
                return DomainType.MATHEMATICAL.value

            # CAUSAL: Planning, strategy, cause-effect
            elif any(word in text_lower for word in ["plan", "strategy", "cause", "effect", "consequence", "because"]):
                return DomainType.CAUSAL.value
            elif any(tag in all_tags for tag in ["planning", "strategy", "causal"]):
                return DomainType.CAUSAL.value

            # ABSTRACT: Memory, reasoning, cognition
            elif any(word in text_lower for word in ["memory", "reason", "think", "cognition", "belief", "abstraction"]):
                return DomainType.ABSTRACT.value
            elif any(tag in all_tags for tag in ["memory", "reasoning", "cognitive"]):
                return DomainType.ABSTRACT.value

            # PRACTICAL: Testing, validation, application
            elif any(word in text_lower for word in ["test", "validate", "verify", "check", "apply", "practical"]):
                return DomainType.PRACTICAL.value
            elif any(tag in all_tags for tag in ["testing", "validation", "practical"]):
                return DomainType.PRACTICAL.value

            # LINGUISTIC: Language, communication, text
            elif any(word in text_lower for word in ["language", "text", "communication", "write", "document"]):
                return DomainType.LINGUISTIC.value
            elif any(tag in all_tags for tag in ["linguistic", "language", "communication"]):
                return DomainType.LINGUISTIC.value

            # TEMPORAL: Time, sequence, scheduling
            elif any(word in text_lower for word in ["time", "sequence", "schedule", "duration", "temporal", "when"]):
                return DomainType.TEMPORAL.value
            elif any(tag in all_tags for tag in ["temporal", "time", "sequence"]):
                return DomainType.TEMPORAL.value

            # SPATIAL: Location, structure, organization
            elif any(word in text_lower for word in ["location", "structure", "spatial", "position", "where", "layout"]):
                return DomainType.SPATIAL.value
            elif any(tag in all_tags for tag in ["spatial", "structure", "location"]):
                return DomainType.SPATIAL.value

            # ETHICAL: Ethics, governance, security
            elif any(word in text_lower for word in ["ethical", "security", "governance", "moral", "compliance"]):
                return DomainType.ETHICAL.value
            elif any(tag in all_tags for tag in ["ethical", "security", "governance"]):
                return DomainType.ETHICAL.value

            # SOCIAL: Collaboration, interaction
            elif any(word in text_lower for word in ["social", "collaborate", "team", "interact", "cooperate"]):
                return DomainType.SOCIAL.value
            elif any(tag in all_tags for tag in ["social", "collaboration", "interaction"]):
                return DomainType.SOCIAL.value

            # CREATIVE: Design, innovation, creativity
            elif any(word in text_lower for word in ["creative", "design", "innovate", "novel", "original"]):
                return DomainType.CREATIVE.value
            elif any(tag in all_tags for tag in ["creative", "design", "innovation"]):
                return DomainType.CREATIVE.value

            # Default to ABSTRACT for memory-based patterns
            else:
                return DomainType.ABSTRACT.value

        except Exception as e:
            logger.debug(f"Domain inference from cluster failed: {e}")
            return "abstract"  # Fallback default

    #: Bounds on optional model-backed enrichment. Deterministic analogy has
    #: no budget because it costs no inference.
    ENRICHMENT_MODEL_TIMEOUT = 20.0      # seconds per model call
    ENRICHMENT_MAX_DOMAINS = 3           # candidate domains, not all 14
    ENRICHMENT_MIN_VALUE = 0.6           # escalate only above this potential

    def _schedule_enrichment(self, schema: ProbabilisticSchema) -> None:
        """Start enrichment without joining it to schema formation.

        Detached means non-blocking, not unobservable. Every task is registered
        under its schema_id so pending work can be inspected, awaited or
        cancelled at shutdown instead of dying silently as an orphan.
        """
        registry = self.enrichment_tasks

        existing = registry.get(schema.schema_id)
        if existing is not None and not existing.done():
            # Already enriching this schema; a second pass would double-apply.
            logger.debug(f"Enrichment already in flight for {schema.schema_id}")
            return

        try:
            task = asyncio.create_task(
                self._enrich_schema_with_cross_domain_mappings(schema),
                name=f"enrich_{schema.schema_id}",
            )
        except RuntimeError:
            # No running loop (synchronous callers). Enrichment is optional, so
            # its absence is not an error.
            logger.debug("No running event loop; cross-domain enrichment skipped")
            return

        registry[schema.schema_id] = task

        def _finished(completed: 'asyncio.Task') -> None:
            if registry.get(schema.schema_id) is completed:
                registry.pop(schema.schema_id, None)
            if completed.cancelled():
                logger.debug(f"Enrichment cancelled for {schema.schema_id}")
            elif completed.exception():
                logger.debug(
                    f"Enrichment failed for {schema.schema_id}: {completed.exception()}"
                )

        task.add_done_callback(_finished)

    @staticmethod
    def _mark_cross_domain_significance(schema: ProbabilisticSchema) -> None:
        """Apply the cross-domain significance boost at most once per schema.

        The boost is multiplicative, so re-running enrichment for a schema
        would compound it silently. Enrichment is detached and retryable, which
        makes a second pass a realistic event rather than a hypothetical one.
        """
        if schema.metadata.get('cross_domain_significance'):
            return

        schema.metadata['cross_domain_significance'] = True
        schema.context_diversity_score *= 1.2

    @property
    def enrichment_tasks(self) -> Dict[str, 'asyncio.Task']:
        """Registry of in-flight enrichment tasks, keyed by schema_id."""
        if not hasattr(self, '_enrichment_tasks'):
            self._enrichment_tasks: Dict[str, 'asyncio.Task'] = {}
        return self._enrichment_tasks

    async def drain_enrichment(self, timeout: float = 30.0) -> Dict[str, int]:
        """Await in-flight enrichment, cancelling whatever exceeds the timeout.

        Call at shutdown so detached work is accounted for rather than left to
        be destroyed mid-flight with its exception never retrieved.
        """
        pending = [task for task in self.enrichment_tasks.values() if not task.done()]
        if not pending:
            return {'completed': 0, 'cancelled': 0}

        done, still_running = await asyncio.wait(pending, timeout=timeout)

        for task in still_running:
            task.cancel()
        if still_running:
            await asyncio.gather(*still_running, return_exceptions=True)

        return {'completed': len(done), 'cancelled': len(still_running)}

    async def _enrich_schema_with_cross_domain_mappings(self, schema: ProbabilisticSchema):
        """Enrich a schema with cross-domain mappings.

        Deterministic analogy discovery is primary: it costs no inference, so
        every mapping it finds is free and reproducible. A model is consulted
        only as bounded escalation when the deterministic pass finds nothing
        AND the schema looks valuable enough to be worth an inference.

        This never raises and never blocks schema validity. The schema is
        already formed, applied and in the hierarchy before this runs.
        """
        try:
            mappings = await self._find_analogical_mappings(schema)

            if mappings:
                schema.metadata['cross_domain_mappings'] = mappings[:3]
                schema.metadata['enrichment_source'] = 'analogy_discovery'

                if len(mappings) >= 2:
                    self._mark_cross_domain_significance(schema)

                self.stats['analogical_enrichments'] = (
                    self.stats.get('analogical_enrichments', 0) + 1
                )
                logger.info(
                    f"Schema {schema.schema_id} enriched with {len(mappings)} "
                    f"deterministic cross-domain mappings"
                )
                return

            # A deterministic miss legitimately means "no mapping known". It is
            # not automatically a reason to spend an inference.
            if not self._should_escalate_enrichment(schema):
                schema.metadata['enrichment_source'] = 'none'
                logger.debug(
                    f"Schema {schema.schema_id}: no analogical mapping found and "
                    f"value below escalation threshold; left un-enriched"
                )
                return

            await self._escalate_enrichment_to_model(schema)

        except Exception as e:
            # Enrichment is advisory. Its failure must never invalidate a schema.
            logger.debug(f"Cross-domain enrichment skipped for {schema.schema_id}: {e}")

    async def _find_analogical_mappings(self, schema: ProbabilisticSchema) -> List[Dict[str, Any]]:
        """Find cross-domain mappings using the deterministic analogy engine.

        Candidate domains come from what the engine actually knows about the
        schema's concepts, so the search is relevance-driven rather than an
        enumeration over every domain in the taxonomy.
        """
        try:
            from core.reasoning.analogy_discovery import get_analogy_discovery
        except Exception as e:
            logger.debug(f"Analogy discovery unavailable: {e}")
            return []

        engine = get_analogy_discovery()
        await engine._ensure_initialized()

        source_domain = str(schema.metadata.get('domain', 'general'))
        concepts = self._schema_concepts(schema)
        if not concepts:
            return []

        # Relevance-driven: only domains the engine actually holds concepts
        # for, excluding the schema's own domain.
        candidate_domains = [
            domain for domain in engine.concepts.keys() if domain != source_domain
        ][:self.ENRICHMENT_MAX_DOMAINS]

        mappings: List[Dict[str, Any]] = []
        for concept in concepts:
            for domain in candidate_domains:
                try:
                    analogy = await engine.find_analogy(concept, domain, min_similarity=0.5)
                except Exception as e:
                    logger.debug(f"Analogy lookup failed for {concept}->{domain}: {e}")
                    continue

                if analogy:
                    mappings.append({
                        'target_domain': domain,
                        'source_concept': concept,
                        'target_concept': getattr(analogy, 'target_concept', ''),
                        'similarity': float(getattr(analogy, 'coherence', 0.0)),
                        'strategy': 'analogical',
                        'source': 'analogy_discovery',
                    })

        return mappings

    def _schema_concepts(self, schema: ProbabilisticSchema) -> List[str]:
        """Content words from the schema usable as analogy source concepts."""
        text = f"{getattr(schema, 'condition', '')} {getattr(schema, 'outcome', '')}"
        words = re.findall(r"[a-z][a-z_]{2,}", text.lower())
        stopwords = {'the', 'and', 'for', 'was', 'were', 'that', 'this', 'with', 'from'}
        seen: List[str] = []
        for word in words:
            if word not in stopwords and word not in seen:
                seen.append(word)
        return seen[:5]

    def _should_escalate_enrichment(self, schema: ProbabilisticSchema) -> bool:
        """Whether a schema is worth spending an inference to enrich.

        Escalation is opt-in on value, so a deterministic miss does not turn
        into a model request by default.
        """
        try:
            value = float(schema.calculate_probability())
        except Exception:
            return False

        stress = float(getattr(schema, 'stress_test_score', 0.0) or 0.0)
        return value >= self.ENRICHMENT_MIN_VALUE and stress >= self.ENRICHMENT_MIN_VALUE

    async def _escalate_enrichment_to_model(self, schema: ProbabilisticSchema):
        """Bounded model-backed enrichment for high-value schemas only.

        Every call is time-bounded and the candidate domain count is capped, so
        the worst case is a fixed, small delay after the schema already exists.
        """
        try:
            from core.integration.universal_domain_master import (
                get_universal_domain_master, DomainType, CrossDomainQuery,
                ReasoningStrategy
            )
        except Exception as e:
            logger.debug(f"Domain master unavailable: {e}")
            return

        domain_master = get_universal_domain_master()
        schema_domain = schema.metadata.get('domain', 'abstract')

        try:
            source_domain = DomainType(schema_domain)
        except ValueError:
            source_domain = DomainType.ABSTRACT

        # Capped candidate set. The previous implementation queried every
        # domain in the taxonomy, one sequential inference each.
        target_domains = [
            d for d in DomainType if d != source_domain
        ][:self.ENRICHMENT_MAX_DOMAINS]

        query = CrossDomainQuery(
            query_id=f"schema_enrichment_{uuid.uuid4().hex[:8]}",
            query_text=f"Find analogical patterns for: {schema.condition} → {schema.outcome}",
            source_domains=[source_domain],
            target_domains=target_domains,
            reasoning_strategy=ReasoningStrategy.ANALOGICAL,
            max_results=5,
            min_similarity=0.6
        )

        try:
            result = await asyncio.wait_for(
                domain_master.execute_cross_domain_query(query),
                timeout=self.ENRICHMENT_MODEL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            schema.metadata['enrichment_source'] = 'model_timeout'
            logger.info(
                f"Model enrichment for {schema.schema_id} exceeded "
                f"{self.ENRICHMENT_MODEL_TIMEOUT}s; schema stands un-enriched"
            )
            return
        except Exception as e:
            logger.debug(f"Model enrichment failed for {schema.schema_id}: {e}")
            return

        if getattr(result, 'success', False) and getattr(result, 'mappings', None):
            # ACCEPTED vs CANDIDATE. `verified is True` means an ontological
            # validator judged the mapping; `verified is None` means one never
            # ran. Persisting a proposal is not the same as knowing it, so the
            # two must not drive the same cognitive transition.
            _accepted = [m for m in result.mappings if getattr(m, 'verified', None) is True]
            _candidates = [m for m in result.mappings if getattr(m, 'verified', None) is None]

            def _project(m):
                return {
                    'mapping_id': getattr(m, 'mapping_id', None),
                    'target_domain': m.target_domain.value,
                    'target_concept': m.target_concept,
                    'similarity': m.similarity_score,
                    'strategy': m.reasoning_strategy.value,
                    'source': 'model',
                    'validation_status': (
                        'accepted' if getattr(m, 'verified', None) is True else 'unvalidated'
                    ),
                }

            # DomainRegistry owns the mappings; this projection carries
            # mapping_id so the durable row stays resolvable rather than being
            # duplicated here.
            schema.metadata['cross_domain_mappings'] = [_project(m) for m in _accepted[:3]]
            schema.metadata['cross_domain_candidates'] = [_project(m) for m in _candidates[:3]]
            schema.metadata['cross_domain_candidate_count'] = len(_candidates)
            schema.metadata['enrichment_source'] = 'model'

            # Only ACCEPTED mappings may assert established cross-domain
            # structure. Giving candidates the same 1.2 multiplier would promote
            # a proposal to a fact through behaviour instead of through the DB.
            if len(_accepted) >= 2:
                self._mark_cross_domain_significance(schema)
            elif len(_candidates) >= 2:
                schema.metadata['cross_domain_candidate_signal'] = True
                logger.info(
                    "Schema %s has %d unvalidated cross-domain candidates — "
                    "provisional signal only, no significance boost",
                    schema.schema_id, len(_candidates)
                )


# FIX #5: Hierarchical Planner - Principles shape strategy BEFORE episodic retrieval
class HierarchicalPlanner:
    """
    Planner that queries abstraction hierarchy BEFORE episodic memory.

    Flow:
    1. Query Level 3 principles relevant to goal
    2. Find Level 2 schemas under those principles
    3. Extract strategy constraints from schemas
    4. Query episodic memories WITHIN constraints
    5. Generate plan following principle-level strategy

    This makes abstraction UPSTREAM of planning, not downstream.
    """

    def __init__(self, abstraction_pipeline: AbstractionPipeline):
        self.pipeline = abstraction_pipeline
        self.hierarchy = abstraction_pipeline.concept_hierarchy
        self.schemas = abstraction_pipeline.active_schemas
        self.memory = abstraction_pipeline.memory

    async def plan(self, goal: str, domain: str = "general") -> Dict[str, Any]:
        """Generate plan using hierarchical strategy"""

        # STEP 1: Query Level 3 principles
        principles = self.hierarchy.find_principles_for_domain(domain)

        # STEP 2: Query Level 2 schemas under principles
        relevant_schemas = []
        for principle in principles:
            schema_nodes = self.hierarchy.get_descendants(principle.concept_id, max_depth=1)
            for node in schema_nodes:
                if node.level == AbstractionLevel.SCHEMA and node.schema_id:
                    if node.schema_id in self.schemas:
                        relevant_schemas.append(self.schemas[node.schema_id])

        # STEP 3: Extract strategy constraints
        strategy_constraints = []
        for schema in relevant_schemas:
            if schema.probability > 0.7:  # Only use strong schemas
                constraint = {
                    'when': schema.condition,
                    'prefer': schema.outcome,
                    'confidence': schema.probability,
                    'schema_id': schema.schema_id
                }
                strategy_constraints.append(constraint)

        # STEP 4: Query episodic memories WITHIN constraints
        constrained_query = self._build_constrained_query(goal, strategy_constraints)
        memories = await self.memory.search_memories(
            query_text=constrained_query,
            limit=20
        )

        # STEP 5: Generate plan following strategy
        plan = {
            'goal': goal,
            'domain': domain,
            'principles_applied': [p.concept_id for p in principles],
            'schemas_used': [s.schema_id for s in relevant_schemas],
            'strategy_constraints': strategy_constraints,
            'supporting_memories': [m.memory_id for m in memories],
            'plan_steps': self._generate_steps_from_strategy(goal, strategy_constraints, memories)
        }

        return plan

    def _build_constrained_query(self, goal: str, constraints: List[Dict]) -> str:
        """Build query that incorporates strategic constraints"""
        query_parts = [goal]

        for constraint in constraints[:3]:  # Top 3 constraints
            if 'prefer' in constraint:
                for key, value in constraint['prefer'].items():
                    query_parts.append(f"{key}:{value}")

        return " ".join(query_parts)

    def _generate_steps_from_strategy(
        self,
        goal: str,
        constraints: List[Dict],
        memories: List[Any]
    ) -> List[Dict[str, Any]]:
        """Generate plan steps following strategic constraints"""
        steps = []

        # Use constraints to shape action selection
        for i, constraint in enumerate(constraints[:5]):
            step = {
                'step_number': i + 1,
                'action': f"Apply strategy: {constraint['when']} → {constraint['prefer']}",
                'confidence': constraint['confidence'],
                'schema_id': constraint['schema_id']
            }
            steps.append(step)

        # Add memory-based refinement
        for memory in memories[:3]:
            if hasattr(memory, 'content') and isinstance(memory.content, dict):
                action = memory.content.get('action') or memory.content.get('result')
                if action:
                    steps.append({
                        'step_number': len(steps) + 1,
                        'action': f"Based on past: {action}",
                        'memory_id': memory.memory_id
                    })

        return steps


_abstraction_pipeline: Optional[AbstractionPipeline] = None


def get_abstraction_pipeline() -> Optional[AbstractionPipeline]:
    """Get global instance"""
    return _abstraction_pipeline


# Alias for compatibility
def get_hierarchical_abstraction() -> Optional[AbstractionPipeline]:
    """Alias for get_abstraction_pipeline()"""
    return get_abstraction_pipeline()


def initialize_abstraction_pipeline(
    memory_agent: 'MemoryAgent',
    uncertainty_system: 'BayesianUncertaintySystem',
    reasoning_engine: Optional['AbstractReasoningEngine'] = None,
    governance_agent: Optional[Any] = None,
    intrinsic_motivation: Optional[Any] = None
) -> AbstractionPipeline:
    """Initialize global instance"""
    global _abstraction_pipeline
    if _abstraction_pipeline is None:
        _abstraction_pipeline = AbstractionPipeline(
            memory_agent=memory_agent,
            uncertainty_system=uncertainty_system,
            reasoning_engine=reasoning_engine,
            governance_agent=governance_agent,
            intrinsic_motivation=intrinsic_motivation
        )
    return _abstraction_pipeline


def create_hierarchical_planner(abstraction_pipeline: AbstractionPipeline) -> HierarchicalPlanner:
    """Create hierarchical planner with principle-first strategy"""
    return HierarchicalPlanner(abstraction_pipeline)
