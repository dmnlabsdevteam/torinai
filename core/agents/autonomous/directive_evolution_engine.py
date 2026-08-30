#!/usr/bin/env python3
"""
Directive Evolution Engine

Tracks directive evolution over time:
- Log all directive changes
- Track version lineage
- Calculate improvement scores
- Detect drift
- Maintain audit trail
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from core.database import get_unified_db

logger = logging.getLogger(__name__)


class EvolutionType(Enum):
    """Types of directive evolution"""
    CREATED = "created"
    MODIFIED = "modified"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"
    AB_TEST_STARTED = "ab_test_started"
    AB_TEST_WINNER = "ab_test_winner"


@dataclass
class DirectiveEvolution:
    """Record of directive evolution"""
    evolution_id: str
    directive_id: str
    evolution_type: EvolutionType
    previous_version: Optional[int]
    new_version: int
    changes: Dict[str, Any]
    improvement_score: Optional[float]
    trigger_reason: str
    performance_metrics: Optional[Dict[str, Any]] = None
    evolved_at: datetime = field(default_factory=datetime.now)


@dataclass
class EvolutionChain:
    """Evolution chain for a directive"""
    directive_id: str
    total_evolutions: int
    evolution_history: List[DirectiveEvolution]
    creation_date: datetime
    latest_version: int
    cumulative_improvement: float
    drift_detected: bool


class DirectiveEvolutionEngine:
    """
    Directive Evolution Tracking Engine

    Tracks how directives evolve over time:

    Evolution Types:
    - CREATED: New directive created
    - MODIFIED: Parameters updated
    - PROMOTED: Performance threshold exceeded
    - DEPRECATED: Replaced by better variant
    - AB_TEST_STARTED: Testing initiated
    - AB_TEST_WINNER: Variant promoted

    Drift Detection:
    - Cumulative change > 30% triggers alert
    - Tracks deviation from original directive
    - Helps identify when directive has evolved significantly

    Metrics:
    - Version lineage (parent_directive_id)
    - Improvement scores per evolution
    - Cumulative improvement over time
    - Evolution frequency
    """

    def __init__(
        self,
        db = None,
        drift_threshold: float = 0.30
    ):
        """
        Initialize evolution engine

        Args:
            db: Database for persistence (will use singleton if not provided)
            drift_threshold: Threshold for drift detection (default 0.30 = 30%)
        """
        self.db = db  # Will be set in initialize() if None
        self.drift_threshold = drift_threshold
        self.initialized = False

        # Evolution tracking (directive_id -> evolution chain)
        self.evolution_chains: Dict[str, EvolutionChain] = {}

        # Metrics
        self.metrics = {
            'total_evolutions': 0,
            'by_type': {
                'created': 0,
                'modified': 0,
                'promoted': 0,
                'deprecated': 0,
                'ab_test_started': 0,
                'ab_test_winner': 0
            },
            'drift_alerts': 0,
            'avg_improvement_per_evolution': 0.0
        }

        logger.info(
            f"Directive evolution engine initialized "
            f"(drift_threshold: {drift_threshold})"
        )

    async def initialize(self) -> bool:
        """Initialize database connection"""
        if not self.initialized:
            if self.db is None:
                self.db = await get_unified_db()
            self.initialized = True
            logger.info("DirectiveEvolutionEngine database initialized")
        return True

    async def log_evolution(
        self,
        directive_id: str,
        evolution_type: EvolutionType,
        previous_version: Optional[int],
        new_version: int,
        changes: Dict[str, Any],
        trigger_reason: str,
        improvement_score: Optional[float] = None,
        performance_metrics: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Log directive evolution

        Args:
            directive_id: Directive identifier
            evolution_type: Type of evolution
            previous_version: Previous version number
            new_version: New version number
            changes: Changes made
            trigger_reason: Why evolution occurred
            improvement_score: Optional improvement score [0.0-1.0]
            performance_metrics: Optional performance metrics

        Returns:
            evolution_id
        """
        evolution_id = f"evo_{directive_id}_{new_version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        evolution = DirectiveEvolution(
            evolution_id=evolution_id,
            directive_id=directive_id,
            evolution_type=evolution_type,
            previous_version=previous_version,
            new_version=new_version,
            changes=changes,
            improvement_score=improvement_score,
            trigger_reason=trigger_reason,
            performance_metrics=performance_metrics
        )

        # Update evolution chain
        if directive_id not in self.evolution_chains:
            self.evolution_chains[directive_id] = EvolutionChain(
                directive_id=directive_id,
                total_evolutions=0,
                evolution_history=[],
                creation_date=datetime.now(),
                latest_version=new_version,
                cumulative_improvement=0.0,
                drift_detected=False
            )

        chain = self.evolution_chains[directive_id]
        chain.evolution_history.append(evolution)
        chain.total_evolutions += 1
        chain.latest_version = new_version

        # Update cumulative improvement
        if improvement_score is not None:
            chain.cumulative_improvement += improvement_score

        # Check for drift
        if chain.cumulative_improvement > self.drift_threshold:
            if not chain.drift_detected:
                chain.drift_detected = True
                self.metrics['drift_alerts'] += 1

                logger.warning(
                    f"DRIFT DETECTED for directive {directive_id}: "
                    f"cumulative improvement = {chain.cumulative_improvement:.1%} "
                    f"(threshold: {self.drift_threshold:.1%})"
                )

        # Update metrics
        self.metrics['total_evolutions'] += 1
        self.metrics['by_type'][evolution_type.value] += 1

        if improvement_score is not None:
            # Update average improvement
            total_improvement = (
                self.metrics['avg_improvement_per_evolution'] *
                (self.metrics['total_evolutions'] - 1)
            )
            total_improvement += improvement_score
            self.metrics['avg_improvement_per_evolution'] = (
                total_improvement / self.metrics['total_evolutions']
            )

        logger.info(
            f"Logged evolution {evolution_id}: {directive_id} "
            f"v{previous_version}→v{new_version} ({evolution_type.value})"
        )

        return evolution_id

    async def get_evolution_history(
        self,
        directive_id: str,
        limit: Optional[int] = None
    ) -> List[DirectiveEvolution]:
        """
        Get evolution history for directive

        Args:
            directive_id: Directive identifier
            limit: Optional limit on number of evolutions to return

        Returns:
            List of DirectiveEvolution (most recent first)
        """
        if directive_id not in self.evolution_chains:
            return []

        chain = self.evolution_chains[directive_id]
        history = chain.evolution_history[::-1]  # Reverse to get most recent first

        if limit:
            history = history[:limit]

        return history

    async def get_evolution_chain(self, directive_id: str) -> Optional[EvolutionChain]:
        """
        Get complete evolution chain for directive

        Args:
            directive_id: Directive identifier

        Returns:
            EvolutionChain or None if not found
        """
        return self.evolution_chains.get(directive_id)

    async def calculate_improvement(
        self,
        directive_id: str,
        baseline_metrics: Dict[str, float],
        current_metrics: Dict[str, float]
    ) -> float:
        """
        Calculate improvement score

        Args:
            directive_id: Directive identifier
            baseline_metrics: Baseline performance metrics
            current_metrics: Current performance metrics

        Returns:
            Improvement score [0.0-1.0] or negative for degradation
        """
        # Calculate weighted improvement across metrics
        improvements = []

        for metric_key in baseline_metrics.keys():
            if metric_key in current_metrics:
                baseline = baseline_metrics[metric_key]
                current = current_metrics[metric_key]

                if baseline > 0:
                    improvement = (current - baseline) / baseline
                    improvements.append(improvement)

        if not improvements:
            return 0.0

        # Average improvement
        avg_improvement = sum(improvements) / len(improvements)

        # Clamp to [-1.0, 1.0]
        return max(-1.0, min(1.0, avg_improvement))

    async def detect_drift(
        self,
        directive_id: str,
        alert_threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Detect if directive has drifted significantly

        Args:
            directive_id: Directive identifier
            alert_threshold: Optional custom threshold (default: self.drift_threshold)

        Returns:
            Dict with drift analysis
        """
        threshold = alert_threshold or self.drift_threshold

        if directive_id not in self.evolution_chains:
            return {
                'drift_detected': False,
                'reason': 'No evolution history'
            }

        chain = self.evolution_chains[directive_id]

        # Calculate cumulative change magnitude
        cumulative_change = chain.cumulative_improvement

        drift_detected = cumulative_change > threshold

        return {
            'directive_id': directive_id,
            'drift_detected': drift_detected,
            'cumulative_improvement': cumulative_change,
            'threshold': threshold,
            'total_evolutions': chain.total_evolutions,
            'latest_version': chain.latest_version,
            'recommendation': (
                "Consider creating new baseline directive"
                if drift_detected else
                "Within acceptable drift limits"
            )
        }

    async def get_version_lineage(
        self,
        directive_id: str,
        max_depth: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get version lineage for directive

        Args:
            directive_id: Directive identifier
            max_depth: Maximum depth to traverse

        Returns:
            List of version info (newest first)
        """
        if directive_id not in self.evolution_chains:
            return []

        chain = self.evolution_chains[directive_id]
        lineage = []

        for evolution in chain.evolution_history[::-1]:  # Newest first
            if len(lineage) >= max_depth:
                break

            lineage.append({
                'version': evolution.new_version,
                'evolution_type': evolution.evolution_type.value,
                'improvement_score': evolution.improvement_score,
                'trigger_reason': evolution.trigger_reason,
                'evolved_at': evolution.evolved_at.isoformat(),
                'changes': evolution.changes
            })

        return lineage

    async def get_evolution_summary(
        self,
        directive_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get evolution summary

        Args:
            directive_id: Optional specific directive, or all if None

        Returns:
            Evolution summary dict
        """
        if directive_id:
            # Summary for specific directive
            if directive_id not in self.evolution_chains:
                return {'error': f'Directive {directive_id} not found'}

            chain = self.evolution_chains[directive_id]

            # Count evolutions by type
            type_counts = {}
            for evolution in chain.evolution_history:
                etype = evolution.evolution_type.value
                type_counts[etype] = type_counts.get(etype, 0) + 1

            return {
                'directive_id': directive_id,
                'total_evolutions': chain.total_evolutions,
                'latest_version': chain.latest_version,
                'cumulative_improvement': chain.cumulative_improvement,
                'drift_detected': chain.drift_detected,
                'creation_date': chain.creation_date.isoformat(),
                'evolution_types': type_counts,
                'recent_evolutions': [
                    {
                        'version': e.new_version,
                        'type': e.evolution_type.value,
                        'reason': e.trigger_reason,
                        'improvement': e.improvement_score
                    }
                    for e in chain.evolution_history[-5:]  # Last 5
                ]
            }
        else:
            # Summary for all directives
            total_directives = len(self.evolution_chains)
            drift_count = sum(
                1 for chain in self.evolution_chains.values()
                if chain.drift_detected
            )

            return {
                'total_directives_tracked': total_directives,
                'total_evolutions': self.metrics['total_evolutions'],
                'evolutions_by_type': self.metrics['by_type'].copy(),
                'drift_alerts': self.metrics['drift_alerts'],
                'avg_improvement_per_evolution': self.metrics['avg_improvement_per_evolution'],
                'directives_with_drift': drift_count,
                'drift_percentage': (
                    (drift_count / total_directives * 100)
                    if total_directives > 0 else 0.0
                )
            }

    async def get_metrics(self) -> Dict[str, Any]:
        """Get evolution engine metrics"""
        return {
            'metrics': self.metrics.copy(),
            'tracked_directives': len(self.evolution_chains),
            'drift_threshold': self.drift_threshold
        }
