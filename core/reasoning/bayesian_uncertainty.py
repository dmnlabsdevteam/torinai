#!/usr/bin/env python3
"""
Bayesian Uncertainty Tracking System
=====================================
Extends the Singleton's confidence scoring with proper epistemic humility:
- Bayesian uncertainty quantification
- Known unknowns database
- Confidence calibration against actual accuracy
- Information value estimation

Integrates with existing reasoning and learning systems.
"""

import asyncio
import logging
import json
import math
import uuid
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


class UncertaintyType(Enum):
    """Types of uncertainty"""
    ALEATORIC = "aleatoric"  # Irreducible randomness
    EPISTEMIC = "epistemic"  # Reducible through learning
    MODEL = "model"  # Uncertainty about model structure
    PARAMETRIC = "parametric"  # Uncertainty about parameters


class KnowledgeState(Enum):
    """What we know about what we know"""
    KNOWN_KNOWN = "known_known"  # We know it and know we know it
    KNOWN_UNKNOWN = "known_unknown"  # We know we don't know it
    UNKNOWN_UNKNOWN = "unknown_unknown"  # We don't know we don't know it
    PARTIAL = "partial"  # We know something but not everything


class RelationType(Enum):
    """Types of relationships between beliefs"""
    IMPLIES = "implies"  # A → B (if A is true, B must be true)
    CONTRADICTS = "contradicts"  # A ⊥ B (if A is true, B must be false)
    SUPPORTS = "supports"  # A ⇒ B (A provides evidence for B, but doesn't strictly imply)
    WEAKENS = "weakens"  # A weakens B (A provides evidence against B)
    REQUIRES = "requires"  # A requires B (A cannot be true unless B is true)
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"  # A ⊕ B (exactly one can be true)


@dataclass
class BeliefRelationship:
    """Represents a logical relationship between two beliefs"""
    relationship_id: str
    source_belief_id: str  # Belief A
    target_belief_id: str  # Belief B
    relation_type: RelationType
    strength: float = 1.0  # How strong is this relationship? (0.0-1.0)

    # Metadata
    discovered_at: datetime = field(default_factory=datetime.now)
    discovered_by: str = "system"  # "system", "human", "llm"
    confidence: float = 1.0  # How confident are we in this relationship?

    def reverse_relation(self) -> RelationType:
        """Get the reverse relationship type"""
        if self.relation_type == RelationType.IMPLIES:
            return RelationType.REQUIRES  # B ← A means B requires A
        elif self.relation_type == RelationType.CONTRADICTS:
            return RelationType.CONTRADICTS  # Symmetric
        elif self.relation_type == RelationType.SUPPORTS:
            return RelationType.SUPPORTS  # Keep as supports (evidence flows both ways)
        elif self.relation_type == RelationType.WEAKENS:
            return RelationType.WEAKENS
        elif self.relation_type == RelationType.REQUIRES:
            return RelationType.IMPLIES
        elif self.relation_type == RelationType.MUTUALLY_EXCLUSIVE:
            return RelationType.MUTUALLY_EXCLUSIVE  # Symmetric
        return self.relation_type


@dataclass
class BayesianBelief:
    """Bayesian belief with prior, likelihood, and posterior"""
    belief_id: str
    claim: str
    domain: str

    # Bayesian components
    prior_probability: float  # P(H) - belief before evidence
    likelihood: float  # P(E|H) - probability of evidence given hypothesis
    posterior_probability: float  # P(H|E) - belief after evidence

    # Evidence tracking
    evidence_for: List[Dict[str, Any]] = field(default_factory=list)
    evidence_against: List[Dict[str, Any]] = field(default_factory=list)
    evidence_quality: float = 0.5  # How reliable is the evidence?

    # Uncertainty
    uncertainty_type: UncertaintyType = UncertaintyType.EPISTEMIC
    credible_interval: Tuple[float, float] = (0.0, 1.0)  # 95% credible interval
    entropy: float = 1.0  # Information-theoretic uncertainty

    # Temporal decay (prevents epistemic ossification)
    decay_rate: float = 0.01  # Domain-adaptive λ for exp(-λΔt)
    last_evidence_time: datetime = field(default_factory=datetime.now)  # When last evidence arrived
    time_since_reinforcement: float = 0.0  # Hours since last supporting evidence

    # Metadata
    last_updated: datetime = field(default_factory=datetime.now)
    update_count: int = 0
    confidence_history: List[float] = field(default_factory=list)


@dataclass
class KnownUnknown:
    """Explicit representation of something we know we don't know"""
    unknown_id: str
    question: str
    domain: str
    knowledge_state: KnowledgeState
    
    # Why don't we know this?
    blocking_factors: List[str] = field(default_factory=list)  # What prevents knowing?
    required_information: List[str] = field(default_factory=list)  # What info would resolve this?
    
    # Value of resolving
    information_value: float = 0.0  # How valuable would knowing this be?
    urgency: float = 0.0  # How urgently do we need to know?
    
    # Resolution
    can_be_resolved: bool = True
    resolution_cost: float = 0.0  # Cost to acquire knowledge
    resolution_strategy: Optional[str] = None  # How to find out
    
    # Tracking
    discovered_at: datetime = field(default_factory=datetime.now)
    resolution_attempts: int = 0


@dataclass
class ConfidenceCalibration:
    """Tracks calibration of confidence vs actual accuracy"""
    calibration_id: str
    domain: str
    
    # Calibration data: predicted_confidence -> actual_accuracy
    calibration_bins: Dict[float, List[float]] = field(default_factory=lambda: defaultdict(list))
    
    # Metrics
    brier_score: float = 0.0  # Proper scoring rule (lower is better)
    calibration_error: float = 0.0  # How far off are predictions?
    overconfidence_bias: float = 0.0  # Positive = overconfident, Negative = underconfident
    
    # Statistics
    total_predictions: int = 0
    correct_predictions: int = 0
    samples_needed: int = 100  # Need this many for good calibration


class BayesianUncertaintySystem:
    """
    Bayesian Uncertainty Tracking for the Singleton
    
    Provides epistemic humility by:
    1. Quantifying uncertainty properly (Bayesian inference)
    2. Tracking known unknowns explicitly
    3. Calibrating confidence against reality
    4. Estimating information value
    """
    
    def __init__(self, db_path: Optional[str] = None):
        # All persistence goes through the unified PostgreSQL database.
        self.unified_db = TorinUnifiedDatabase()
        
        # Bayesian beliefs
        self.beliefs: Dict[str, BayesianBelief] = {}

        # Writes discarded because the database was not initialized. Exposed in
        # get_statistics() so "nothing persisted" is a visible number rather
        # than a silent assumption.
        self.persistence_drops: int = 0
        
        # Known unknowns
        self.known_unknowns: Dict[str, KnownUnknown] = {}
        
        # Confidence calibration by domain
        self.calibrations: Dict[str, ConfidenceCalibration] = {}

        # Domain volatility tracking (for adaptive decay rates)
        self.domain_volatility: Dict[str, float] = defaultdict(lambda: 0.01)  # λ per domain
        self.domain_belief_changes: Dict[str, List[float]] = defaultdict(list)  # Track magnitude of updates
        self.domain_regime_shifts: Dict[str, int] = defaultdict(int)  # Count contradictions/reversals

        # Belief dependency graph (for constraint propagation)
        self.relationships: Dict[str, BeliefRelationship] = {}  # relationship_id -> relationship
        self.forward_edges: Dict[str, Set[str]] = defaultdict(set)  # belief_id -> {relationship_ids}
        self.backward_edges: Dict[str, Set[str]] = defaultdict(set)  # belief_id -> {relationship_ids}
        self.propagation_queue: List[Tuple[str, float, str]] = []  # (belief_id, delta, reason)

        # Statistics
        self.stats = {
            'beliefs_tracked': 0,
            'known_unknowns_discovered': 0,
            'known_unknowns_resolved': 0,
            'calibration_updates': 0,
            'overconfidence_detected': 0,
            'underconfidence_detected': 0,
            'temporal_decays_applied': 0,
            'regime_shifts_detected': 0,
            'relationships_discovered': 0,
            'constraint_propagations': 0,
            'consistency_violations': 0
        }
        
        # Initialize local persistence database
        self._init_database()
    
    def _init_database(self):
        """No-op: persistence is handled by PostgreSQL via unified_db."""
        logger.info("Bayesian uncertainty system ready (PostgreSQL persistence via unified_db)")
    
    # ==================================================================================
    # BAYESIAN BELIEF UPDATING
    # ==================================================================================
    
    def create_belief(
        self,
        claim: str,
        domain: str,
        prior: float = 0.5,
        evidence: Optional[Dict[str, Any]] = None
    ) -> BayesianBelief:
        """
        Create a new Bayesian belief with prior probability.
        
        Args:
            claim: The proposition to track
            domain: Knowledge domain
            prior: Initial belief (default 0.5 = maximum uncertainty)
            evidence: Optional initial evidence
        """
        belief_id = f"belief_{uuid.uuid4().hex[:12]}"
        
        belief = BayesianBelief(
            belief_id=belief_id,
            claim=claim,
            domain=domain,
            prior_probability=prior,
            likelihood=1.0,
            posterior_probability=prior,
            entropy=self._calculate_entropy(prior)
        )
        
        # Register before applying evidence. update_belief() looks the belief
        # up by id and raises "Belief not found" otherwise, so creating a
        # belief with initial evidence always failed -- the belief was only
        # added to self.beliefs on the line after the update attempt.
        self.beliefs[belief_id] = belief
        self.stats['beliefs_tracked'] += 1

        if evidence:
            belief = self.update_belief(belief_id, evidence)
        
        # Persist to database
        self._save_belief(belief)
        
        logger.debug(f"Created belief: {claim} (prior={prior:.3f})")
        return belief
    
    def update_belief(
        self,
        belief_id: str,
        evidence: Dict[str, Any],
        evidence_supports: bool = True
    ) -> BayesianBelief:
        """
        Update belief using Bayesian inference with temporal decay: P(H|E) ∝ P(E|H) * P(H)

        Process:
        1. Apply temporal decay to prior (prevents ossification)
        2. Update with new evidence (Bayesian)
        3. Detect regime shifts (belief reversals)
        4. Update domain volatility (adaptive λ)

        Args:
            belief_id: Belief to update
            evidence: Evidence data
            evidence_supports: Whether evidence supports the claim
        """
        if belief_id not in self.beliefs:
            raise ValueError(f"Belief not found: {belief_id}")

        belief = self.beliefs[belief_id]

        # STEP 1: Apply temporal decay BEFORE new evidence
        # This prevents early conclusions from becoming gravity wells
        original_prior = belief.posterior_probability
        decayed_prior = self._apply_temporal_decay(belief)
        belief.posterior_probability = decayed_prior  # Use decayed value as prior

        # Track evidence
        if evidence_supports:
            belief.evidence_for.append(evidence)
        else:
            belief.evidence_against.append(evidence)

        # Calculate likelihood: P(E|H)
        evidence_weight = evidence.get('quality', belief.evidence_quality)

        # INTEGRATION D: Adjust evidence weight based on cross-domain support
        evidence_weight = self._adjust_evidence_with_domain_support(
            belief, evidence, evidence_weight
        )

        # STEP 2: Bayesian update with decayed prior
        prior = decayed_prior

        # Odds-based Bayesian update using exponential likelihood ratio.
        # LR = exp(±_LR_STRENGTH * quality), applied in odds form:
        #   P(H|E) / P(¬H|E) = [P(H) / P(¬H)] * LR
        #
        # Properties:
        #   quality = 0.0  → LR = 1.0       (neutral, no update)
        #   quality = 0.5  → LR = exp(±1.5) (moderate)
        #   quality = 1.0  → LR = exp(±3.0) (strong, ≈ 20x or 0.05x)
        #   Symmetric, bounded, no zero-probability singularities.
        #
        # Replaces the previous heuristic P(E|H)/P(E|¬H) assignment which
        # produced infinite likelihood ratios at quality=1.0 and inverted
        # direction for contradicting evidence above quality=0.5.
        _LR_STRENGTH = 3.0
        if evidence_supports:
            lr = math.exp(_LR_STRENGTH * evidence_weight)
        else:
            lr = math.exp(-_LR_STRENGTH * evidence_weight)

        prior_odds = prior / max(1e-9, 1.0 - prior)
        new_odds = prior_odds * lr
        posterior = new_odds / (1.0 + new_odds)

        # Store LR for diagnostics (replaces raw P(E|H) assignment)
        likelihood = lr

        # STEP 3: Detect regime shift (belief reversal across 0.5 threshold)
        is_reversal = False
        if (original_prior > 0.5 and posterior < 0.5) or (original_prior < 0.5 and posterior > 0.5):
            is_reversal = True
            logger.warning(
                f"Belief reversal detected: '{belief.claim[:40]}' "
                f"crossed 0.5 threshold ({original_prior:.3f} → {posterior:.3f})"
            )

        # Calculate belief change magnitude
        belief_change = abs(posterior - original_prior)

        # STEP 4: Update domain volatility (adaptive decay rate)
        self._update_domain_volatility(belief.domain, belief_change, is_reversal)

        # Update belief state
        # Clamp to open interval to prevent entropy collapsing to zero,
        # which would make the belief permanently irrefutable/irrecoverable.
        _POSTERIOR_FLOOR = 1e-6
        belief.posterior_probability = max(
            _POSTERIOR_FLOOR, min(1.0 - _POSTERIOR_FLOOR, posterior)
        )
        belief.likelihood = likelihood
        belief.entropy = self._calculate_entropy(belief.posterior_probability)
        belief.last_updated = datetime.now()
        belief.last_evidence_time = datetime.now()  # Reset evidence timer
        belief.time_since_reinforcement = 0.0  # Just got evidence
        belief.update_count += 1
        belief.confidence_history.append(posterior)

        # Update decay rate from domain
        belief.decay_rate = self.domain_volatility[belief.domain]

        # Update credible interval (simplified - using standard error)
        std_error = math.sqrt(posterior * (1 - posterior) / max(belief.update_count, 1))
        belief.credible_interval = (
            max(0.0, posterior - 1.96 * std_error),
            min(1.0, posterior + 1.96 * std_error)
        )

        # Persist update
        self._save_belief(belief)

        # STEP 5: Propagate constraints through belief graph
        # This ensures global coherence: when A changes, update all beliefs that depend on A
        probability_delta = posterior - original_prior
        if abs(probability_delta) > 0.05:  # Only propagate significant changes
            self.propagate_constraints(belief_id, probability_delta, max_depth=5)

        logger.debug(
            f"Updated belief '{belief.claim[:50]}': "
            f"{original_prior:.3f} → {decayed_prior:.3f} (decay) → {posterior:.3f} (evidence) "
            f"(entropy={belief.entropy:.3f}, λ={belief.decay_rate:.4f})"
        )

        return belief
    
    def _calculate_entropy(self, probability: float) -> float:
        """Calculate Shannon entropy: H = -p*log(p) - (1-p)*log(1-p)"""
        if probability == 0.0 or probability == 1.0:
            return 0.0
        return -(probability * math.log2(probability) +
                 (1 - probability) * math.log2(1 - probability))

    def _apply_temporal_decay(self, belief: BayesianBelief) -> float:
        """
        Apply exponential decay to belief probability toward uncertainty.
        Prevents epistemic ossification by requiring continuous evidence reinforcement.

        Formula: P(H)_t+1 = P(H)_t + (0.5 - P(H)_t) * (1 - exp(-λΔt))

        This drifts beliefs toward maximum uncertainty (0.5) in absence of reinforcing evidence.
        """
        now = datetime.now()
        time_delta = (now - belief.last_evidence_time).total_seconds() / 3600.0  # Hours

        # Get domain-adaptive decay rate
        lambda_decay = self.domain_volatility.get(belief.domain, 0.01)

        # Calculate decay factor
        decay_factor = 1 - math.exp(-lambda_decay * time_delta)

        # Drift toward 0.5 (maximum uncertainty)
        current_prob = belief.posterior_probability
        decayed_prob = current_prob + (0.5 - current_prob) * decay_factor

        # Update time tracking
        belief.time_since_reinforcement = time_delta

        if abs(decayed_prob - current_prob) > 0.01:
            self.stats['temporal_decays_applied'] += 1
            logger.debug(
                f"Temporal decay applied to '{belief.claim[:40]}': "
                f"{current_prob:.3f} → {decayed_prob:.3f} "
                f"(Δt={time_delta:.1f}h, λ={lambda_decay:.4f})"
            )

        return decayed_prob

    def _update_domain_volatility(self, domain: str, belief_change: float, is_reversal: bool = False):
        """
        Update domain-adaptive decay rate λ based on observed volatility.

        High volatility domains → higher λ → faster decay (require more frequent evidence)
        Stable domains → lower λ → slower decay (beliefs persist longer)
        """
        # Track belief change magnitude
        self.domain_belief_changes[domain].append(belief_change)

        # Keep last 50 updates for rolling volatility
        if len(self.domain_belief_changes[domain]) > 50:
            self.domain_belief_changes[domain] = self.domain_belief_changes[domain][-50:]

        # Detect regime shifts (major belief reversals)
        if is_reversal:
            self.domain_regime_shifts[domain] += 1
            self.stats['regime_shifts_detected'] += 1
            logger.warning(f"Regime shift detected in domain '{domain}' (total: {self.domain_regime_shifts[domain]})")

        # Calculate volatility metrics
        avg_change = sum(self.domain_belief_changes[domain]) / len(self.domain_belief_changes[domain])
        regime_penalty = min(self.domain_regime_shifts[domain] * 0.005, 0.05)  # Cap at 0.05

        # Adaptive λ: base rate + volatility component + regime penalty
        new_lambda = 0.01 + (avg_change * 0.1) + regime_penalty
        new_lambda = max(0.005, min(0.1, new_lambda))  # Clamp [0.005, 0.1]

        old_lambda = self.domain_volatility[domain]
        self.domain_volatility[domain] = new_lambda

        if abs(new_lambda - old_lambda) > 0.001:
            logger.info(
                f"Domain '{domain}' λ updated: {old_lambda:.4f} → {new_lambda:.4f} "
                f"(volatility={avg_change:.3f}, shifts={self.domain_regime_shifts[domain]})"
            )

    # ==================================================================================
    # BELIEF DEPENDENCY GRAPH & CONSTRAINT PROPAGATION
    # ==================================================================================

    def add_relationship(
        self,
        source_belief_id: str,
        target_belief_id: str,
        relation_type: RelationType,
        strength: float = 1.0,
        confidence: float = 1.0,
        discovered_by: str = "system"
    ) -> str:
        """
        Add a logical relationship between two beliefs.

        This creates edges in the belief dependency graph for constraint propagation.

        Args:
            source_belief_id: Source belief (A in "A → B")
            target_belief_id: Target belief (B in "A → B")
            relation_type: Type of relationship (implies, contradicts, etc.)
            strength: Relationship strength (0.0-1.0)
            confidence: Confidence in this relationship (0.0-1.0)
            discovered_by: Who/what discovered this relationship

        Returns:
            relationship_id
        """
        relationship_id = f"rel_{uuid.uuid4().hex[:12]}"

        relationship = BeliefRelationship(
            relationship_id=relationship_id,
            source_belief_id=source_belief_id,
            target_belief_id=target_belief_id,
            relation_type=relation_type,
            strength=strength,
            discovered_by=discovered_by,
            confidence=confidence
        )

        # Store relationship
        self.relationships[relationship_id] = relationship

        # Update graph edges
        self.forward_edges[source_belief_id].add(relationship_id)
        self.backward_edges[target_belief_id].add(relationship_id)

        self.stats['relationships_discovered'] += 1

        logger.info(
            f"Relationship added: {source_belief_id[:8]} {relation_type.value} {target_belief_id[:8]} "
            f"(strength={strength:.2f}, confidence={confidence:.2f})"
        )

        # Immediately activate: propagate the source belief's current epistemic
        # influence to the newly connected target.
        # activation_delta = how far source deviates from neutral (0.5).
        # Shallow max_depth=3 on creation — deeper cascades fire on update_belief().
        source = self.beliefs.get(source_belief_id)
        if source is not None:
            activation_delta = source.posterior_probability - 0.5
            if abs(activation_delta) > 0.05:
                self.propagate_constraints(
                    source_belief_id, activation_delta, max_depth=3
                )

        return relationship_id

    def propagate_constraints(
        self,
        changed_belief_id: str,
        probability_delta: float,
        max_depth: int = 5,
        visited: Optional[Set[str]] = None
    ):
        """
        Propagate belief updates through the dependency graph.

        When belief A changes, recursively update all beliefs that depend on A:
        - A → B (implies): Increase in P(A) increases P(B)
        - A ⊥ B (contradicts): Increase in P(A) decreases P(B)
        - A ⇒ B (supports): Increase in P(A) slightly increases P(B)

        Args:
            changed_belief_id: Belief that just changed
            probability_delta: How much it changed (positive or negative)
            max_depth: Maximum propagation depth (prevent infinite loops)
            visited: Set of already-visited beliefs (for cycle detection)
        """
        if max_depth <= 0:
            return

        if visited is None:
            visited = set()

        if changed_belief_id in visited:
            logger.warning(f"Cycle detected in belief graph at {changed_belief_id[:8]}")
            return

        visited.add(changed_belief_id)

        # Get all forward relationships from this belief
        forward_rels = self.forward_edges.get(changed_belief_id, set())

        for rel_id in forward_rels:
            relationship = self.relationships[rel_id]
            target_id = relationship.target_belief_id

            if target_id not in self.beliefs:
                continue

            target_belief = self.beliefs[target_id]

            # Compute propagation effect
            effect = self._compute_propagation_effect(
                relationship.relation_type,
                probability_delta,
                relationship.strength,
                relationship.confidence
            )

            if abs(effect) < 0.01:  # Threshold: ignore tiny effects
                continue

            # Apply effect to target belief
            old_prob = target_belief.posterior_probability
            new_prob = max(0.0, min(1.0, old_prob + effect))  # Clamp [0, 1]

            if abs(new_prob - old_prob) > 0.01:
                target_belief.posterior_probability = new_prob
                target_belief.entropy = self._calculate_entropy(new_prob)
                target_belief.last_updated = datetime.now()

                self.stats['constraint_propagations'] += 1

                logger.debug(
                    f"Constraint propagation: {target_id[:8]} "
                    f"{old_prob:.3f} → {new_prob:.3f} "
                    f"(via {relationship.relation_type.value} from {changed_belief_id[:8]})"
                )

                # Recursively propagate
                self.propagate_constraints(
                    target_id,
                    new_prob - old_prob,
                    max_depth - 1,
                    visited
                )

    def _compute_propagation_effect(
        self,
        relation_type: RelationType,
        delta: float,
        strength: float,
        confidence: float
    ) -> float:
        """
        Compute how much a belief change should affect a related belief.

        Returns the probability delta to apply to the target belief.
        """
        base_effect = delta * strength * confidence

        if relation_type == RelationType.IMPLIES:
            # A → B: If A increases, B increases (scaled by strength)
            return base_effect * 0.8

        elif relation_type == RelationType.CONTRADICTS:
            # A ⊥ B: If A increases, B decreases
            return -base_effect * 0.9

        elif relation_type == RelationType.SUPPORTS:
            # A ⇒ B: Weak positive influence
            return base_effect * 0.4

        elif relation_type == RelationType.WEAKENS:
            # A weakens B: Weak negative influence
            return -base_effect * 0.4

        elif relation_type == RelationType.REQUIRES:
            # B requires A: If A decreases significantly, B must decrease
            if delta < -0.2:  # Only propagate large decreases
                return delta * strength * 0.7
            return 0.0

        elif relation_type == RelationType.MUTUALLY_EXCLUSIVE:
            # A ⊕ B: If A increases, B decreases (zero-sum)
            return -base_effect * 0.95

        return 0.0

    def check_consistency(self) -> Dict[str, Any]:
        """
        Check global consistency of the belief graph.

        Detects:
        - Implication violations (A → B but P(A) > P(B))
        - Contradiction violations (A ⊥ B but both have high probability)
        - Mutual exclusivity violations (A ⊕ B but both high)
        - Circular dependencies

        Returns consistency report with violations.
        """
        violations = {
            'implication_violations': [],
            'contradiction_violations': [],
            'mutual_exclusivity_violations': [],
            'circular_dependencies': [],
            'total_violations': 0
        }

        for rel_id, relationship in self.relationships.items():
            source_id = relationship.source_belief_id
            target_id = relationship.target_belief_id

            if source_id not in self.beliefs or target_id not in self.beliefs:
                continue

            source_prob = self.beliefs[source_id].posterior_probability
            target_prob = self.beliefs[target_id].posterior_probability

            relation = relationship.relation_type

            # Check implication violations: A → B requires P(A) ≤ P(B) + ε
            if relation == RelationType.IMPLIES:
                if source_prob > target_prob + 0.15:  # Tolerance
                    violations['implication_violations'].append({
                        'source': source_id,
                        'target': target_id,
                        'source_prob': source_prob,
                        'target_prob': target_prob,
                        'violation_magnitude': source_prob - target_prob
                    })
                    violations['total_violations'] += 1
                    self.stats['consistency_violations'] += 1

            # Check contradiction violations: A ⊥ B requires P(A) + P(B) ≈ 1
            elif relation == RelationType.CONTRADICTS:
                prob_sum = source_prob + target_prob
                if not (0.8 <= prob_sum <= 1.2):  # Should sum to ~1
                    violations['contradiction_violations'].append({
                        'source': source_id,
                        'target': target_id,
                        'source_prob': source_prob,
                        'target_prob': target_prob,
                        'prob_sum': prob_sum
                    })
                    violations['total_violations'] += 1
                    self.stats['consistency_violations'] += 1

            # Check mutual exclusivity: A ⊕ B requires exactly one high
            elif relation == RelationType.MUTUALLY_EXCLUSIVE:
                if source_prob > 0.7 and target_prob > 0.7:
                    violations['mutual_exclusivity_violations'].append({
                        'source': source_id,
                        'target': target_id,
                        'source_prob': source_prob,
                        'target_prob': target_prob
                    })
                    violations['total_violations'] += 1
                    self.stats['consistency_violations'] += 1

        if violations['total_violations'] > 0:
            logger.warning(
                f"Consistency check found {violations['total_violations']} violations: "
                f"{len(violations['implication_violations'])} implications, "
                f"{len(violations['contradiction_violations'])} contradictions, "
                f"{len(violations['mutual_exclusivity_violations'])} mutual exclusivity"
            )

        return violations

    def get_belief_uncertainty(self, belief_id: str) -> Dict[str, Any]:
        """Get comprehensive uncertainty information for a belief"""
        if belief_id not in self.beliefs:
            return {"error": "Belief not found"}
        
        belief = self.beliefs[belief_id]
        
        return {
            'claim': belief.claim,
            'probability': belief.posterior_probability,
            'credible_interval': belief.credible_interval,
            'entropy': belief.entropy,
            'uncertainty_type': belief.uncertainty_type.value,
            'evidence_count': len(belief.evidence_for) + len(belief.evidence_against),
            'evidence_balance': len(belief.evidence_for) - len(belief.evidence_against),
            'updates': belief.update_count,
            'interpretation': self._interpret_uncertainty(belief)
        }
    
    def _interpret_uncertainty(self, belief: BayesianBelief) -> str:
        """Human-readable interpretation of uncertainty"""
        prob = belief.posterior_probability
        entropy = belief.entropy
        
        if entropy < 0.2:
            certainty = "very certain"
        elif entropy < 0.5:
            certainty = "fairly certain"
        elif entropy < 0.8:
            certainty = "moderately uncertain"
        else:
            certainty = "very uncertain"
        
        if prob > 0.9:
            belief_str = "strongly believe this is true"
        elif prob > 0.7:
            belief_str = "believe this is likely true"
        elif prob > 0.5:
            belief_str = "slightly lean towards true"
        elif prob > 0.3:
            belief_str = "slightly lean towards false"
        elif prob > 0.1:
            belief_str = "believe this is likely false"
        else:
            belief_str = "strongly believe this is false"
        
        return f"I {belief_str} ({certainty}, entropy={entropy:.2f})"
    
    # ==================================================================================
    # KNOWN UNKNOWNS TRACKING
    # ==================================================================================
    
    def register_known_unknown(
        self,
        question: str,
        domain: str,
        blocking_factors: Optional[List[str]] = None,
        required_info: Optional[List[str]] = None
    ) -> KnownUnknown:
        """
        Explicitly register something we know we don't know.
        
        This is epistemic humility in action - acknowledging ignorance.
        """
        unknown_id = f"unknown_{uuid.uuid4().hex[:12]}"
        
        unknown = KnownUnknown(
            unknown_id=unknown_id,
            question=question,
            domain=domain,
            knowledge_state=KnowledgeState.KNOWN_UNKNOWN,
            blocking_factors=blocking_factors or [],
            required_information=required_info or []
        )
        
        # Calculate information value (how valuable is knowing this?)
        unknown.information_value = self._estimate_information_value(unknown)
        
        # Determine resolution strategy
        unknown.resolution_strategy = self._suggest_resolution_strategy(unknown)
        
        self.known_unknowns[unknown_id] = unknown
        self.stats['known_unknowns_discovered'] += 1
        
        # Persist to database
        self._save_known_unknown(unknown)
        
        logger.info(f"Registered known unknown: {question} (value={unknown.information_value:.3f})")
        return unknown
    
    def _estimate_information_value(self, unknown: KnownUnknown) -> float:
        """Estimate the value of resolving this unknown (0.0 to 1.0)"""
        value = 0.5  # Base value
        
        # High value if affects many decisions
        if 'decision' in unknown.question.lower() or 'should' in unknown.question.lower():
            value += 0.2
        
        # High value if in critical domain
        critical_domains = ['safety', 'security', 'self_improvement', 'reasoning']
        if any(domain in unknown.domain.lower() for domain in critical_domains):
            value += 0.2
        
        # High value if many blocking factors (resolving unlocks much)
        value += min(0.1 * len(unknown.blocking_factors), 0.3)
        
        return min(value, 1.0)
    
    def _suggest_resolution_strategy(self, unknown: KnownUnknown) -> str:
        """Suggest how to resolve this unknown"""
        strategies = []
        
        # Can we research it?
        if any('research' in factor.lower() for factor in unknown.blocking_factors):
            strategies.append("autonomous_research")
        
        # Can we experiment?
        if any('test' in factor.lower() or 'experiment' in factor.lower() 
               for factor in unknown.blocking_factors):
            strategies.append("sandbox_experiment")
        
        # Need external data?
        if any('data' in info.lower() for info in unknown.required_information):
            strategies.append("data_collection")
        
        # Need reasoning?
        if any('understand' in info.lower() or 'reason' in info.lower() 
               for info in unknown.required_information):
            strategies.append("deep_reasoning")
        
        return ", ".join(strategies) if strategies else "unclear"
    
    def get_high_value_unknowns(self, min_value: float = 0.7) -> List[KnownUnknown]:
        """Get known unknowns worth resolving (high information value)"""
        return [
            unknown for unknown in self.known_unknowns.values()
            if unknown.information_value >= min_value and unknown.can_be_resolved
        ]
    
    def resolve_known_unknown(
        self,
        unknown_id: str,
        resolution: Dict[str, Any]
    ) -> bool:
        """Mark a known unknown as resolved with the answer"""
        if unknown_id not in self.known_unknowns:
            return False
        
        unknown = self.known_unknowns[unknown_id]
        unknown.knowledge_state = KnowledgeState.KNOWN_KNOWN
        
        # Create belief with the new knowledge (without evidence - just create)
        belief_id = f"belief_{uuid.uuid4().hex[:12]}"
        belief = BayesianBelief(
            belief_id=belief_id,
            claim=resolution.get('answer', 'Resolved'),
            domain=unknown.domain,
            prior_probability=0.7,
            likelihood=1.0,
            posterior_probability=0.7,
            entropy=self._calculate_entropy(0.7)
        )
        self.beliefs[belief_id] = belief
        self.stats['beliefs_tracked'] += 1
        self._save_belief(belief)
        
        # Remove from unknowns (now it's known!)
        del self.known_unknowns[unknown_id]
        self.stats['known_unknowns_resolved'] += 1
        
        logger.info(f"Resolved unknown: {unknown.question}")
        return True
    
    # ==================================================================================
    # CONFIDENCE CALIBRATION
    # ==================================================================================
    
    def record_prediction(
        self,
        domain: str,
        predicted_confidence: float,
        actual_outcome: bool
    ):
        """
        Record a prediction with confidence and actual outcome.
        Used to calibrate future confidence estimates.
        """
        # Get or create calibration for domain
        if domain not in self.calibrations:
            self.calibrations[domain] = ConfidenceCalibration(
                calibration_id=f"cal_{domain}_{uuid.uuid4().hex[:8]}",
                domain=domain
            )
        
        calibration = self.calibrations[domain]
        
        # Bin the confidence (round to nearest 0.1)
        confidence_bin = round(predicted_confidence, 1)
        
        # Record actual outcome (1.0 for correct, 0.0 for incorrect)
        actual_value = 1.0 if actual_outcome else 0.0
        calibration.calibration_bins[confidence_bin].append(actual_value)
        
        # Update statistics
        calibration.total_predictions += 1
        if actual_outcome:
            calibration.correct_predictions += 1
        
        # Recalculate calibration metrics
        self._update_calibration_metrics(calibration)
        
        # Persist to database
        self._save_calibration_data(domain, predicted_confidence, actual_value)
        
        self.stats['calibration_updates'] += 1
    
    def _update_calibration_metrics(self, calibration: ConfidenceCalibration):
        """Update Brier score and calibration error"""
        if calibration.total_predictions < 10:
            return  # Need minimum samples
        
        # Calculate Brier score: mean squared error of probabilities
        brier_sum = 0.0
        total_samples = 0
        
        for confidence_bin, outcomes in calibration.calibration_bins.items():
            for outcome in outcomes:
                brier_sum += (confidence_bin - outcome) ** 2
                total_samples += 1
        
        if total_samples > 0:
            calibration.brier_score = brier_sum / total_samples
        
        # Calculate calibration error: average difference between confidence and accuracy
        calibration_errors = []
        
        for confidence_bin, outcomes in calibration.calibration_bins.items():
            if outcomes:
                actual_accuracy = sum(outcomes) / len(outcomes)
                calibration_errors.append(confidence_bin - actual_accuracy)
        
        if calibration_errors:
            calibration.calibration_error = sum(abs(e) for e in calibration_errors) / len(calibration_errors)
            calibration.overconfidence_bias = sum(calibration_errors) / len(calibration_errors)
            
            # Track bias
            if calibration.overconfidence_bias > 0.1:
                self.stats['overconfidence_detected'] += 1
            elif calibration.overconfidence_bias < -0.1:
                self.stats['underconfidence_detected'] += 1
    
    def get_calibrated_confidence(
        self,
        domain: str,
        raw_confidence: float
    ) -> float:
        """
        Adjust raw confidence based on historical calibration.
        
        If we're systematically overconfident, this corrects for it.
        """
        if domain not in self.calibrations:
            return raw_confidence  # No calibration data yet
        
        calibration = self.calibrations[domain]
        
        if calibration.total_predictions < calibration.samples_needed:
            return raw_confidence  # Not enough data
        
        # Apply bias correction
        corrected = raw_confidence - calibration.overconfidence_bias
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, corrected))
    
    def should_defer_to_expert(
        self,
        domain: str,
        confidence: float,
        entropy: float
    ) -> Dict[str, Any]:
        """
        Decide if uncertainty is too high and should defer to human/expert.
        
        Returns decision and reasoning.
        """
        # Get calibrated confidence
        calibrated_conf = self.get_calibrated_confidence(domain, confidence)
        
        # Decision criteria
        defer = False
        reasons = []
        
        # High uncertainty (entropy)
        if entropy > 0.8:
            defer = True
            reasons.append("Very high uncertainty (entropy > 0.8)")
        
        # Low confidence after calibration
        if calibrated_conf < 0.3:
            defer = True
            reasons.append(f"Low calibrated confidence ({calibrated_conf:.2f})")
        
        # Critical domain with moderate uncertainty
        critical_domains = ['safety', 'security', 'self_modification']
        if domain in critical_domains and (entropy > 0.5 or calibrated_conf < 0.7):
            defer = True
            reasons.append(f"Critical domain with insufficient certainty")
        
        # Known unknowns in this domain
        relevant_unknowns = [
            u for u in self.known_unknowns.values()
            if u.domain == domain and u.information_value > 0.5
        ]
        if relevant_unknowns:
            defer = True
            reasons.append(f"Known unknowns exist in this domain ({len(relevant_unknowns)})")
        
        return {
            'should_defer': defer,
            'reasons': reasons,
            'calibrated_confidence': calibrated_conf,
            'original_confidence': confidence,
            'entropy': entropy,
            'recommendation': (
                "Defer to expert or gather more information"
                if defer else
                "Proceed with caution but can make decision"
            )
        }
    
    # ==================================================================================
    # PERSISTENCE
    # ==================================================================================
    
    # ==================================================================================
    # PERSISTENCE — PostgreSQL via unified_db
    # ==================================================================================

    async def _write_belief_row(self, belief: BayesianBelief, *, commit: bool = True) -> bool:
        """Write one belief to unified.beliefs. Returns whether it was written.

        Shared by the fire-and-forget `_save_belief` and the awaited
        `flush_belief`, so the two paths cannot drift.
        """
        import json as _json
        if not self.unified_db.initialized:
            # A silent return made a dropped write indistinguishable from a
            # successful one: epistemic state was computed, assumed persisted,
            # and lost. Count and surface it so missing persistence is
            # observable rather than inferred.
            self.persistence_drops += 1
            if self.persistence_drops == 1 or self.persistence_drops % 50 == 0:
                logger.warning(
                    f"Epistemic persistence unavailable (database not "
                    f"initialized): {self.persistence_drops} write(s) dropped. "
                    f"This state will not survive a restart."
                )
            return False
        try:
            # unified.beliefs carries two generations of schema: the current
            # epistemic columns (claim / prior_ / posterior_probability) and the
            # legacy pair (belief_text / confidence), which are still NOT NULL
            # with no default. They hold the same facts, so they are written
            # from the same values rather than relaxing the constraint.
            await self.unified_db.execute_query(
                """
                INSERT INTO unified.beliefs
                    (belief_id, claim, belief_text, confidence, domain,
                     prior_probability, posterior_probability,
                     uncertainty_type, entropy, evidence_for, evidence_against,
                     update_count, last_updated)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (belief_id) DO UPDATE SET
                    claim               = EXCLUDED.claim,
                    belief_text         = EXCLUDED.belief_text,
                    confidence          = EXCLUDED.confidence,
                    domain              = EXCLUDED.domain,
                    prior_probability   = EXCLUDED.prior_probability,
                    posterior_probability = EXCLUDED.posterior_probability,
                    uncertainty_type    = EXCLUDED.uncertainty_type,
                    entropy             = EXCLUDED.entropy,
                    evidence_for        = EXCLUDED.evidence_for,
                    evidence_against    = EXCLUDED.evidence_against,
                    update_count        = EXCLUDED.update_count,
                    last_updated        = EXCLUDED.last_updated
                """,
                (
                    belief.belief_id,
                    belief.claim,
                    belief.claim,                    # belief_text (legacy mirror)
                    belief.posterior_probability,    # confidence  (legacy mirror)
                    belief.domain,
                    belief.prior_probability,
                    belief.posterior_probability,
                    belief.uncertainty_type.value,
                    belief.entropy,
                    _json.dumps(belief.evidence_for),
                    _json.dumps(belief.evidence_against),
                    belief.update_count,
                    belief.last_updated,
                ),
                commit=commit,
            )
            return True
        except Exception as e:
            # Was logger.debug -- a total persistence failure of the belief
            # graph is not a debug-level event.
            logger.warning(f"_save_belief failed for {belief.belief_id}: {e}")
            return False

    def _save_belief(self, belief: BayesianBelief):
        """Persist a belief fire-and-forget from sync callers (non-blocking).

        Committed when it runs, but NOT awaited -- fine for high-frequency
        updates where a lost write is recoverable. A belief that MUST survive a
        restart (domain competence, which decides what the substrate explores
        after reboot) should use `flush_belief`, which awaits the committed
        write. With no running loop (some sync/test contexts) this path cannot
        schedule anything, another reason the durable path is explicit.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._write_belief_row(belief, commit=True))
        except RuntimeError:
            pass  # No running loop (e.g. tests) — skip persistence

    async def flush_belief(self, belief_id: str) -> bool:
        """Write a belief to unified.beliefs synchronously and committed, so it
        survives a real restart. For decision-critical beliefs that must not be
        lost to fire-and-forget -- competence beliefs are flushed on every
        update by the domain authority."""
        belief = self.beliefs.get(belief_id)
        if belief is None:
            return False
        if not self.unified_db.initialized:
            await self.unified_db.initialize()
        return await self._write_belief_row(belief, commit=True)

    async def decay_belief(self, belief_id: str) -> Optional[BayesianBelief]:
        """Apply temporal decay to a belief WITHOUT new evidence.

        `_apply_temporal_decay` runs only inside `update_belief`, so a belief
        that stops receiving evidence -- a domain the substrate believes it has
        mastered and no longer explores -- never decays and its estimate
        ossifies. That is exactly how a FALSE competence estimate becomes
        permanent: unchecked, it is trusted forever.

        This drifts an unreinforced belief back toward 0.5 by the time elapsed
        since it was last touched, so stale competence erodes, re-enters the
        unstable set, and is re-verified against the world -- which corrects it
        if it was wrong. The clock is `last_updated` (time since the last touch,
        evidence or decay), so repeated calls apply only the new increment
        rather than compounding the same interval.
        """
        belief = self.beliefs.get(belief_id)
        if belief is None:
            return None
        now = datetime.now()
        dt_hours = (now - belief.last_updated).total_seconds() / 3600.0
        if dt_hours <= 0:
            return belief
        lambda_decay = self.domain_volatility.get(belief.domain, belief.decay_rate)
        factor = 1 - math.exp(-lambda_decay * dt_hours)
        current = belief.posterior_probability
        decayed = current + (0.5 - current) * factor
        if abs(decayed - current) > 1e-9:
            belief.posterior_probability = decayed
            belief.entropy = self._calculate_entropy(decayed)
            belief.last_updated = now
            belief.time_since_reinforcement = (
                now - belief.last_evidence_time).total_seconds() / 3600.0
            self.stats['temporal_decays_applied'] = self.stats.get(
                'temporal_decays_applied', 0) + 1
            await self.flush_belief(belief_id)
        return belief

    def _save_known_unknown(self, unknown: KnownUnknown):
        """Persist known-unknown to PostgreSQL. Fire-and-forget."""
        import asyncio
        async def _write():
            try:
                if not self.unified_db.initialized:
                    # A silent return made a dropped write indistinguishable from
                    # a successful one: epistemic state was computed, assumed
                    # persisted, and lost. Count and surface it so missing
                    # persistence is observable rather than inferred.
                    self.persistence_drops += 1
                    if self.persistence_drops == 1 or self.persistence_drops % 50 == 0:
                        logger.warning(
                            f"Epistemic persistence unavailable (database not "
                            f"initialized): {self.persistence_drops} write(s) dropped. "
                            f"This state will not survive a restart."
                        )
                    return
                await self.unified_db.execute_query(
                    """
                    INSERT INTO unified.known_unknowns
                        (unknown_id, question, domain, knowledge_state, information_value,
                         urgency, can_be_resolved, resolution_strategy, discovered_at,
                         resolution_attempts)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (unknown_id) DO UPDATE SET
                        knowledge_state      = EXCLUDED.knowledge_state,
                        information_value    = EXCLUDED.information_value,
                        urgency              = EXCLUDED.urgency,
                        resolution_strategy  = EXCLUDED.resolution_strategy,
                        resolution_attempts  = EXCLUDED.resolution_attempts
                    """,
                    (
                        unknown.unknown_id,
                        unknown.question,
                        unknown.domain,
                        unknown.knowledge_state.value,
                        unknown.information_value,
                        unknown.urgency,
                        unknown.can_be_resolved,
                        unknown.resolution_strategy,
                        unknown.discovered_at,
                        unknown.resolution_attempts,
                    ),
                )
            except Exception as e:
                logger.debug(f"_save_known_unknown non-fatal: {e}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_write())
        except RuntimeError:
            pass

    def _save_calibration_data(self, domain: str, predicted_confidence: float, actual_outcome: float):
        """Persist calibration data point to PostgreSQL. Fire-and-forget."""
        import asyncio
        async def _write():
            try:
                if not self.unified_db.initialized:
                    # A silent return made a dropped write indistinguishable from
                    # a successful one: epistemic state was computed, assumed
                    # persisted, and lost. Count and surface it so missing
                    # persistence is observable rather than inferred.
                    self.persistence_drops += 1
                    if self.persistence_drops == 1 or self.persistence_drops % 50 == 0:
                        logger.warning(
                            f"Epistemic persistence unavailable (database not "
                            f"initialized): {self.persistence_drops} write(s) dropped. "
                            f"This state will not survive a restart."
                        )
                    return
                await self.unified_db.execute_query(
                    """
                    INSERT INTO unified.calibration_data
                        (calibration_id, domain, predicted_confidence, actual_outcome, timestamp)
                    VALUES ($1,$2,$3,$4,$5)
                    """,
                    (
                        f"cal_{uuid.uuid4().hex[:8]}",
                        domain,
                        predicted_confidence,
                        actual_outcome,
                        datetime.now(),
                    ),
                )
            except Exception as e:
                logger.debug(f"_save_calibration_data non-fatal: {e}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_write())
        except RuntimeError:
            pass

    async def load_from_db(self):
        """Load persisted beliefs from PostgreSQL into memory at startup.

        Call once after unified_db is initialized, before the agent loop starts.
        Restores the belief graph so epistemic state survives process restarts.
        """
        import json as _json
        try:
            rows = await self.unified_db.execute_query(
                "SELECT belief_id, claim, domain, prior_probability, posterior_probability, "
                "uncertainty_type, entropy, evidence_for, evidence_against, update_count, last_updated "
                "FROM unified.beliefs",
                fetch_all=True,
            )
            if not rows:
                return
            loaded = 0
            for row in rows:
                try:
                    b = BayesianBelief(
                        belief_id=row["belief_id"],
                        claim=row["claim"],
                        domain=row["domain"] or "general",
                        prior_probability=float(row["prior_probability"]),
                        likelihood=0.5,
                        posterior_probability=float(row["posterior_probability"]),
                        uncertainty_type=UncertaintyType(row["uncertainty_type"] or "epistemic"),
                        entropy=float(row["entropy"]),
                        evidence_for=_json.loads(row["evidence_for"]) if row["evidence_for"] else [],
                        evidence_against=_json.loads(row["evidence_against"]) if row["evidence_against"] else [],
                        update_count=int(row["update_count"] or 0),
                        last_updated=row["last_updated"] if row["last_updated"] else datetime.now(),
                    )
                    self.beliefs[b.belief_id] = b
                    self.stats["beliefs_tracked"] += 1
                    loaded += 1
                except Exception as row_err:
                    logger.debug(f"load_from_db: skipping malformed row: {row_err}")
            logger.info(f"Bayesian uncertainty: loaded {loaded} belief(s) from PostgreSQL")
        except Exception as e:
            logger.warning(f"load_from_db failed (non-fatal, starting with empty beliefs): {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        return {
            **self.stats,
            'active_beliefs': len(self.beliefs),
            'persistence_drops': self.persistence_drops,
            'persistence_healthy': self.persistence_drops == 0,
            'known_unknowns': len(self.known_unknowns),
            'calibrated_domains': len(self.calibrations),
            'high_value_unknowns': len(self.get_high_value_unknowns()),
            'overconfidence_rate': (
                self.stats['overconfidence_detected'] /
                max(self.stats['calibration_updates'], 1)
            )
        }

    async def apply_temporal_decay_to_all_beliefs(self) -> Dict[str, Any]:
        """
        Apply temporal decay to all beliefs (prevent epistemic ossification)

        Returns:
            Dictionary with decay statistics
        """
        try:
            now = datetime.now()
            beliefs_decayed = 0
            total_decay = 0.0

            for belief_id, belief in list(self.beliefs.items()):
                # Calculate time since last evidence
                time_delta = (now - belief.last_evidence_time).total_seconds() / 3600.0  # hours

                if time_delta > 1.0:  # Apply decay after 1 hour
                    # Apply temporal decay
                    decayed_prob = self._apply_temporal_decay(belief)

                    # Track decay amount
                    decay_amount = abs(belief.posterior_probability - decayed_prob)
                    total_decay += decay_amount

                    # Update belief
                    belief.posterior_probability = decayed_prob
                    belief.time_since_reinforcement = time_delta

                    beliefs_decayed += 1

                    # Remove belief if it decayed to near-neutral (0.45-0.55)
                    if 0.45 <= decayed_prob <= 0.55 and belief.evidence_count < 3:
                        del self.beliefs[belief_id]

            avg_decay = total_decay / max(beliefs_decayed, 1)

            logger.info(f"✓ Applied decay to {beliefs_decayed} beliefs (avg decay: {avg_decay:.4f})")

            return {
                'beliefs_decayed': beliefs_decayed,
                'avg_decay_amount': avg_decay,
                'beliefs_removed': len([b for b in list(self.beliefs.values()) if 0.45 <= b.posterior_probability <= 0.55])
            }

        except Exception as e:
            logger.error(f"Failed to apply belief decay: {e}")
            return {
                'beliefs_decayed': 0,
                'avg_decay_amount': 0.0,
                'beliefs_removed': 0
            }

    async def check_belief_consistency(self) -> Dict[str, Any]:
        """
        Check belief consistency and propagate constraint updates

        Returns:
            Dictionary with consistency check results
        """
        try:
            violations_found = 0
            constraints_propagated = 0

            # Check for contradictions in belief graph
            for rel_id, relationship in self.relationships.items():
                belief_a = self.beliefs.get(relationship.belief_id_a)
                belief_b = self.beliefs.get(relationship.belief_id_b)

                if not belief_a or not belief_b:
                    continue

                # Check CONTRADICTS relationship
                if relationship.relationship_type == RelationType.CONTRADICTS:
                    # If both beliefs have high confidence, that's a violation
                    if belief_a.posterior_probability > 0.7 and belief_b.posterior_probability > 0.7:
                        violations_found += 1
                        logger.warning(
                            f"⚠️  Consistency violation: {belief_a.hypothesis} contradicts {belief_b.hypothesis}"
                        )

                        # Reduce confidence in the weaker belief
                        if belief_a.evidence_count < belief_b.evidence_count:
                            belief_a.posterior_probability *= 0.9
                        else:
                            belief_b.posterior_probability *= 0.9

                        constraints_propagated += 1

                # Check IMPLIES relationship
                elif relationship.relationship_type == RelationType.IMPLIES:
                    # If A is likely and A→B, then B should be likely
                    if belief_a.posterior_probability > 0.7 and belief_b.posterior_probability < 0.3:
                        # Propagate implication
                        boost = (belief_a.posterior_probability - 0.5) * relationship.strength * 0.3
                        belief_b.posterior_probability = min(1.0, belief_b.posterior_probability + boost)
                        constraints_propagated += 1

            logger.info(f"✓ Checked {len(self.relationships)} belief relationships")

            if violations_found > 0:
                logger.warning(f"⚠️  Found {violations_found} consistency violations")

            return {
                'violations_found': violations_found,
                'constraints_propagated': constraints_propagated,
                'relationships_checked': len(self.relationships)
            }

        except Exception as e:
            logger.error(f"Failed to check belief consistency: {e}")
            return {
                'violations_found': 0,
                'constraints_propagated': 0,
                'relationships_checked': 0
            }

    async def update_domain_volatility_metrics(self) -> Dict[str, Any]:
        """
        Update domain volatility metrics based on belief changes

        Returns:
            Dictionary with volatility update results
        """
        try:
            domains_updated = 0

            for domain, changes in self.domain_belief_changes.items():
                if len(changes) > 0:
                    # Calculate average change magnitude
                    avg_change = sum(changes) / len(changes)

                    # Calculate regime shift penalty
                    regime_penalty = min(self.domain_regime_shifts[domain] * 0.005, 0.05)

                    # Update volatility (λ)
                    new_lambda = 0.01 + (avg_change * 0.1) + regime_penalty
                    new_lambda = max(0.005, min(new_lambda, 0.1))  # Clamp to [0.005, 0.1]

                    self.domain_volatility[domain] = new_lambda

                    domains_updated += 1

            logger.info(f"✓ Updated volatility metrics for {domains_updated} domains")

            return {
                'domains_updated': domains_updated,
                'avg_volatility': sum(self.domain_volatility.values()) / max(len(self.domain_volatility), 1)
            }

        except Exception as e:
            logger.error(f"Failed to update domain volatility: {e}")
            return {
                'domains_updated': 0,
                'avg_volatility': 0.01
            }

    def _adjust_evidence_with_domain_support(
        self,
        belief: BayesianBelief,
        evidence: Dict[str, Any],
        base_weight: float
    ) -> float:
        """
        INTEGRATION D: Adjust evidence weight based on cross-domain support from UDM

        Queries Universal Domain Master to check if similar beliefs in other domains
        support this evidence, boosting weight if cross-domain consensus exists.
        """
        try:
            # Check if evidence includes domain information
            evidence_domain = evidence.get('domain', belief.domain)

            # If evidence comes from a different high-credibility domain, boost weight
            high_credibility_domains = ['scientific', 'mathematical', 'technical']

            if evidence_domain in high_credibility_domains and evidence_domain != belief.domain:
                # Cross-domain evidence from high-credibility source
                return min(1.0, base_weight * 1.15)

            # If evidence comes from same domain, use base weight
            return base_weight

        except Exception as e:
            logger.debug(f"Domain-based evidence adjustment failed: {e}")
            return base_weight  # Fallback to base weight


# Global instance
_uncertainty_system: Optional[BayesianUncertaintySystem] = None


def get_uncertainty_system() -> BayesianUncertaintySystem:
    """Get or create global uncertainty system"""
    global _uncertainty_system

    if _uncertainty_system is None:
        _uncertainty_system = BayesianUncertaintySystem()

    return _uncertainty_system


# Alias for compatibility
def get_bayesian_uncertainty() -> BayesianUncertaintySystem:
    """Alias for get_uncertainty_system()"""
    return get_uncertainty_system()
