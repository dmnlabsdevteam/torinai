#!/usr/bin/env python3
"""
Directive A/B Testing

A/B test infrastructure for directive variants:
- Create A/B tests (control + variants)
- Track applications per variant
- Calculate statistical significance
- Determine winning variant
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

# Statistical analysis
try:
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("scipy not available - statistical analysis will be limited")
    SCIPY_AVAILABLE = False

from core.database import get_unified_db

logger = logging.getLogger(__name__)


class TestStatus(Enum):
    """A/B test status"""
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class VariantMetrics:
    """Metrics for a single variant"""
    variant_id: str
    applications: int
    mean_outcome: float
    std_dev: float
    confidence_interval: Tuple[float, float]
    sample_size: int


@dataclass
class ABTestResult:
    """Result of A/B test"""
    test_id: str
    winning_variant: Optional[str]
    confidence_level: float
    variant_metrics: Dict[str, VariantMetrics]
    p_value: float
    effect_size: float
    sufficient_data: bool
    recommendation: str


class DirectiveABTesting:
    """
    Directive A/B Testing System

    Scientific validation of directive improvements:

    Process:
    1. Create test with control + variants
    2. Track applications per variant
    3. Collect performance metrics
    4. Calculate statistical significance (p < 0.05)
    5. Determine winner (confidence >= 0.90)
    6. Promote winning variant

    Statistical Analysis:
    - Two-sample t-test for significance
    - Effect size (Cohen's d)
    - Confidence intervals
    - Minimum sample size per variant

    Default Parameters:
    - Duration: 168 hours (1 week)
    - Min applications per variant: 50
    - Required confidence: 0.90 (90%)
    """

    def __init__(self, db = None):
        """
        Initialize A/B testing system

        Args:
            db: Database for persistence (will use singleton if not provided)
        """
        self.db = db  # Will be set in initialize() if None
        self.initialized = False

        # Active tests (test_id -> test data)
        self.active_tests: Dict[str, Dict[str, Any]] = {}

        # Variant performance tracking (test_id -> variant_id -> metrics)
        self.variant_data: Dict[str, Dict[str, List[float]]] = {}

        # Metrics
        self.metrics = {
            'total_tests': 0,
            'running_tests': 0,
            'completed_tests': 0,
            'winning_variants_promoted': 0,
            'insufficient_data_tests': 0
        }

        logger.info("Directive A/B testing system initialized")

    async def initialize(self) -> bool:
        """Initialize database connection"""
        if not self.initialized:
            if self.db is None:
                self.db = await get_unified_db()
            self.initialized = True
            logger.info("DirectiveABTesting database initialized")
        return True

    async def create_test(
        self,
        test_name: str,
        control_directive_id: str,
        variant_directive_ids: List[str],
        duration_hours: int = 168,
        min_applications_per_variant: int = 50,
        required_confidence: float = 0.90
    ) -> str:
        """
        Create new A/B test

        Args:
            test_name: Test name
            control_directive_id: Control directive ID
            variant_directive_ids: List of variant directive IDs
            duration_hours: Test duration (default 168 = 1 week)
            min_applications_per_variant: Min samples per variant (default 50)
            required_confidence: Required confidence level (default 0.90)

        Returns:
            test_id
        """
        test_id = f"abtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        test_data = {
            'test_id': test_id,
            'test_name': test_name,
            'control_directive_id': control_directive_id,
            'variant_directives': variant_directive_ids,
            'duration_hours': duration_hours,
            'min_applications_per_variant': min_applications_per_variant,
            'required_confidence': required_confidence,
            'status': TestStatus.RUNNING.value,
            'started_at': datetime.now(),
            'ended_at': None,
            'winning_variant': None,
            'confidence_level': None
        }

        # Store test
        self.active_tests[test_id] = test_data

        # Initialize variant data tracking
        self.variant_data[test_id] = {
            control_directive_id: [],
            **{v_id: [] for v_id in variant_directive_ids}
        }

        # Update metrics
        self.metrics['total_tests'] += 1
        self.metrics['running_tests'] += 1

        logger.info(
            f"Created A/B test {test_id}: {test_name} "
            f"(control + {len(variant_directive_ids)} variants, {duration_hours}h)"
        )

        return test_id

    async def record_application(
        self,
        test_id: str,
        variant_id: str,
        outcome_quality: float
    ) -> None:
        """
        Record directive application result

        Args:
            test_id: Test identifier
            variant_id: Variant directive ID
            outcome_quality: Outcome quality score [0.0-1.0]
        """
        if test_id not in self.active_tests:
            logger.warning(f"Test {test_id} not found")
            return

        if test_id not in self.variant_data:
            logger.warning(f"Variant data for test {test_id} not initialized")
            return

        if variant_id not in self.variant_data[test_id]:
            logger.warning(f"Variant {variant_id} not in test {test_id}")
            return

        # Record outcome
        self.variant_data[test_id][variant_id].append(outcome_quality)

        logger.debug(
            f"Recorded application for test {test_id}, variant {variant_id}: "
            f"outcome={outcome_quality:.3f}"
        )

    async def check_test_completion(self, test_id: str) -> Optional[ABTestResult]:
        """
        Check if test has enough data for completion

        Args:
            test_id: Test identifier

        Returns:
            ABTestResult if test complete, None otherwise
        """
        if test_id not in self.active_tests:
            logger.warning(f"Test {test_id} not found")
            return None

        test_data = self.active_tests[test_id]

        # Check if test duration exceeded
        started_at = test_data['started_at']
        duration_hours = test_data['duration_hours']
        elapsed = (datetime.now() - started_at).total_seconds() / 3600

        if elapsed < duration_hours:
            # Test still running, check if we have enough data
            min_apps = test_data['min_applications_per_variant']

            # Check if all variants have minimum applications
            all_sufficient = all(
                len(data) >= min_apps
                for data in self.variant_data[test_id].values()
            )

            if not all_sufficient:
                return None  # Not enough data yet

        # Perform statistical analysis
        result = await self._analyze_test(test_id)

        # Mark test complete if we have sufficient data
        if result and result.sufficient_data:
            test_data['status'] = TestStatus.COMPLETED.value
            test_data['ended_at'] = datetime.now()
            test_data['winning_variant'] = result.winning_variant
            test_data['confidence_level'] = result.confidence_level

            self.metrics['running_tests'] -= 1
            self.metrics['completed_tests'] += 1

            logger.info(
                f"Test {test_id} completed: "
                f"winner={result.winning_variant}, "
                f"confidence={result.confidence_level:.3f}"
            )
        elif elapsed >= duration_hours:
            # Duration exceeded but insufficient data
            test_data['status'] = TestStatus.INSUFFICIENT_DATA.value
            test_data['ended_at'] = datetime.now()

            self.metrics['running_tests'] -= 1
            self.metrics['insufficient_data_tests'] += 1

            logger.warning(f"Test {test_id} completed with insufficient data")

        return result

    async def _analyze_test(self, test_id: str) -> Optional[ABTestResult]:
        """
        Perform statistical analysis on test

        Args:
            test_id: Test identifier

        Returns:
            ABTestResult with statistical analysis
        """
        if test_id not in self.active_tests or test_id not in self.variant_data:
            return None

        test_data = self.active_tests[test_id]
        variant_data = self.variant_data[test_id]
        min_apps = test_data['min_applications_per_variant']

        # Check if we have enough data
        variant_samples = {
            v_id: len(data)
            for v_id, data in variant_data.items()
        }

        sufficient_data = all(n >= min_apps for n in variant_samples.values())

        if not sufficient_data:
            return ABTestResult(
                test_id=test_id,
                winning_variant=None,
                confidence_level=0.0,
                variant_metrics={},
                p_value=1.0,
                effect_size=0.0,
                sufficient_data=False,
                recommendation="Insufficient data - continue test"
            )

        # Calculate metrics for each variant
        variant_metrics = {}

        for variant_id, outcomes in variant_data.items():
            if len(outcomes) == 0:
                continue

            mean = np.mean(outcomes)
            std_dev = np.std(outcomes, ddof=1)
            n = len(outcomes)

            # Calculate confidence interval (95%)
            if SCIPY_AVAILABLE and n > 1:
                ci = stats.t.interval(
                    0.95,
                    n - 1,
                    loc=mean,
                    scale=std_dev / np.sqrt(n)
                )
            else:
                # Approximate CI without scipy
                margin = 1.96 * (std_dev / np.sqrt(n))
                ci = (mean - margin, mean + margin)

            variant_metrics[variant_id] = VariantMetrics(
                variant_id=variant_id,
                applications=n,
                mean_outcome=mean,
                std_dev=std_dev,
                confidence_interval=ci,
                sample_size=n
            )

        # Find winning variant (highest mean)
        winning_variant = max(
            variant_metrics.keys(),
            key=lambda v: variant_metrics[v].mean_outcome
        )

        # Calculate statistical significance
        control_id = test_data['control_directive_id']

        if SCIPY_AVAILABLE and control_id in variant_data and winning_variant in variant_data:
            # Perform t-test
            control_outcomes = variant_data[control_id]
            winner_outcomes = variant_data[winning_variant]

            if len(control_outcomes) > 1 and len(winner_outcomes) > 1:
                t_stat, p_value = stats.ttest_ind(winner_outcomes, control_outcomes)

                # Calculate effect size (Cohen's d)
                pooled_std = np.sqrt(
                    (
                        (len(control_outcomes) - 1) * np.std(control_outcomes, ddof=1)**2 +
                        (len(winner_outcomes) - 1) * np.std(winner_outcomes, ddof=1)**2
                    ) / (len(control_outcomes) + len(winner_outcomes) - 2)
                )

                effect_size = (
                    np.mean(winner_outcomes) - np.mean(control_outcomes)
                ) / pooled_std if pooled_std > 0 else 0.0
            else:
                p_value = 1.0
                effect_size = 0.0
        else:
            # Without scipy, use simple comparison
            p_value = 0.05  # Assume significant if no scipy
            effect_size = 0.0

        # Calculate confidence level
        confidence_level = 1.0 - p_value

        # Determine if winner is significantly better
        required_confidence = test_data['required_confidence']
        significant_improvement = (
            confidence_level >= required_confidence and
            p_value < 0.05
        )

        # Generate recommendation
        if significant_improvement:
            recommendation = f"Promote {winning_variant} - statistically significant improvement"
        else:
            recommendation = "No significant improvement detected - keep control"

        return ABTestResult(
            test_id=test_id,
            winning_variant=winning_variant if significant_improvement else None,
            confidence_level=confidence_level,
            variant_metrics=variant_metrics,
            p_value=p_value,
            effect_size=effect_size,
            sufficient_data=sufficient_data,
            recommendation=recommendation
        )

    async def get_test_status(self, test_id: str) -> Optional[Dict[str, Any]]:
        """
        Get test status

        Args:
            test_id: Test identifier

        Returns:
            Test status dict
        """
        if test_id not in self.active_tests:
            return None

        test_data = self.active_tests[test_id]

        # Get variant sample counts
        variant_samples = {}
        if test_id in self.variant_data:
            variant_samples = {
                v_id: len(data)
                for v_id, data in self.variant_data[test_id].items()
            }

        # Calculate elapsed time
        elapsed_hours = (
            (datetime.now() - test_data['started_at']).total_seconds() / 3600
        )

        return {
            'test_id': test_id,
            'test_name': test_data['test_name'],
            'status': test_data['status'],
            'control_directive_id': test_data['control_directive_id'],
            'variant_count': len(test_data['variant_directives']),
            'variant_samples': variant_samples,
            'duration_hours': test_data['duration_hours'],
            'elapsed_hours': elapsed_hours,
            'min_applications_per_variant': test_data['min_applications_per_variant'],
            'required_confidence': test_data['required_confidence'],
            'started_at': test_data['started_at'].isoformat(),
            'ended_at': test_data['ended_at'].isoformat() if test_data['ended_at'] else None,
            'winning_variant': test_data['winning_variant'],
            'confidence_level': test_data['confidence_level']
        }

    async def cancel_test(self, test_id: str) -> bool:
        """
        Cancel running test

        Args:
            test_id: Test identifier

        Returns:
            True if cancelled successfully
        """
        if test_id not in self.active_tests:
            return False

        test_data = self.active_tests[test_id]

        if test_data['status'] != TestStatus.RUNNING.value:
            logger.warning(f"Test {test_id} not running, cannot cancel")
            return False

        test_data['status'] = TestStatus.CANCELLED.value
        test_data['ended_at'] = datetime.now()

        self.metrics['running_tests'] -= 1

        logger.info(f"Cancelled test {test_id}")
        return True

    async def get_metrics(self) -> Dict[str, Any]:
        """Get A/B testing metrics"""
        return {
            'metrics': self.metrics.copy(),
            'active_tests': len([
                t for t in self.active_tests.values()
                if t['status'] == TestStatus.RUNNING.value
            ]),
            'scipy_available': SCIPY_AVAILABLE
        }
