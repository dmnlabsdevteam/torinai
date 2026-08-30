#!/usr/bin/env python3
"""
Experience Evaluator
===============================================================

Evaluates execution outcomes and calculates performance metrics:
- Outcome Quality (0.0-1.0)
- Intrinsic Reward (-1.0 to 1.0 — SIGNED: competence progress can be negative)
- Constitutional Alignment (0.0-1.0)
- System Health Impact (0.0-1.0)

This component ensures all metrics are properly normalized and
validates that experiences meet quality thresholds before
integration into the learning system.
"""

import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from .singleton_constitution import SingletonConstitution
from .intrinsic_motivation import IntrinsicMotivationSystem

logger = logging.getLogger(__name__)


class OutcomeQuality(Enum):
    """Outcome quality levels"""
    EXCELLENT = "excellent"        # 0.90-1.00
    GOOD = "good"                  # 0.70-0.89
    ACCEPTABLE = "acceptable"      # 0.50-0.69
    POOR = "poor"                  # 0.30-0.49
    FAILED = "failed"              # 0.00-0.29


class PerformanceCategory(Enum):
    """Performance assessment categories"""
    EXCEPTIONAL = "exceptional"    # > 90%
    STRONG = "strong"              # 70-90%
    MODERATE = "moderate"          # 50-70%
    WEAK = "weak"                  # 30-50%
    CRITICAL = "critical"          # < 30%


@dataclass
class EvaluatedExperience:
    """
    Evaluated experience with all performance metrics

    Metrics are normalized to [0.0, 1.0] EXCEPT intrinsic_reward, which is
    signed [-1.0, 1.0]. A negative intrinsic reward means the experience cost
    the drives (e.g. a skill regressed); clamping it at zero would make
    'mildly bad' and 'much worse' indistinguishable.
    This ensures consistent scoring across different experience types.
    Example: A research task scoring 0.85 outcome_quality means
    "Good result, met expectations with minor issues"
    → outcome_quality, constitutional_alignment and system_health_impact are
      in [0.0, 1.0]; intrinsic_reward is signed [-1.0, 1.0].
    """

    # Context (what was attempted)
    task_id: str              # Which task was executed
    task_type: str            # Type of task (research, analysis, etc)
    context: Dict[str, Any]   # Full context
    action: Dict[str, Any]    # Action taken

    # Outcome (what happened)
    outcome: Dict[str, Any]      # Outcome data (raw results)
    success: bool                # Did it succeed or fail?
    error_message: Optional[str] # Error if failed (None if success)
    duration_seconds: float      # How long it took (seconds)

    # Performance Metrics (normalized [0.0, 1.0] unless noted)
    outcome_quality: float           # Quality of result — EXTRINSIC: how well did it go?
    intrinsic_reward: float          # [-1.0, 1.0] INTRINSIC: what was it worth to the
                                     # drives? Signed because competence progress can be
                                     # negative (a skill regressed). Not a restatement of
                                     # outcome_quality — the two may disagree.
    constitutional_alignment: float  # Alignment with 5 laws
    system_health_impact: float      # Impact on system health

    # Metadata (optional context)
    novel_patterns_discovered: bool = False  # Did we learn something new?
    competence_improved: bool = False        # Did skill improve?

    # Which drives actually contributed to intrinsic_reward, and which could not
    # be measured and why. Without this, a reward computed from 3 dimensions is
    # indistinguishable from one computed from 4.
    intrinsic_components: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    evaluated_at: datetime = field(default_factory=datetime.now)
    task_completed_at: Optional[datetime] = None


def _evidence_delta(value: Any, weight: float) -> float:
    """Signed contribution of one piece of evidence.

        True  -> +weight   positive evidence
        False -> -weight   negative evidence
        None/absent -> 0   no evidence

    Absence is not refutation. A signal nobody measured must neither reward nor
    penalise, while a signal that was measured and came back bad must cost
    exactly what its passing would have earned.

    NOTE: a refuted signal lowers appraised QUALITY; it is deliberately not a
    hard-zero. Whether failing tests block completion belongs to the validator /
    convergence criteria — ExperienceEvaluator appraises, it is not a second
    completion gate.
    """
    if value is True:
        return weight
    if value is False:
        return -weight
    return 0.0


class ExperienceEvaluator:
    """
    Experience Evaluator - Calculate normalized performance metrics

    Evaluates execution outcomes and answers:
    "How good was this outcome?"
    "How much intrinsic reward did we gain?"
    "Did we comply with constitutional laws?"
    "What was the system health impact?"
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

        # Dependencies
        self.constitution = None  # Will be set during initialize
        self.intrinsic_motivation = None  # Will be set during initialize

        # Configuration thresholds
        self.min_outcome_quality = 0.30    # 30% minimum quality
        self.min_constitutional_alignment = 0.70  # 70% minimum law compliance
        self.excellent_threshold = 0.90    # 90% = excellent
        self.good_threshold = 0.70         # 70% = good

        # Evaluation history
        self.evaluations: List[EvaluatedExperience] = []
        self.total_evaluations = 0  # Running count

        logger.info("Experience evaluator initialized")

    async def initialize(
        self,
        constitution: SingletonConstitution,
        intrinsic_motivation: IntrinsicMotivationSystem
    ) -> bool:
        """
        Initialize with required dependencies

        Args:
            constitution: Constitutional framework for compliance checks
            intrinsic_motivation: Intrinsic motivation system for reward calculation

        Returns:
            bool: True if successful
        """

        # Validate inputs (critical for proper evaluation)
        if not 0.0 <= self.min_outcome_quality <= 1.0:
            raise ValueError(
                f"min_outcome_quality must be in [0.0, 1.0], got {self.min_outcome_quality}. "
                "This is a critical configuration error."
            )

        if not 0.0 <= self.min_constitutional_alignment <= 1.0:
            raise ValueError(
                f"min_constitutional_alignment must be in [0.0, 1.0], got {self.min_constitutional_alignment}"
            )

        if not 0.0 <= self.excellent_threshold <= 1.0:
            raise ValueError(
                f"excellent_threshold must be in [0.0, 1.0], got {self.excellent_threshold}"
            )

        # Set dependencies
        self.constitution = constitution
        self.intrinsic_motivation = intrinsic_motivation

        logger.info("Experience evaluator ready with constitution and intrinsic motivation")

        return True

    async def evaluate_experience(
        self,
        task_id: str,
        task_type: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: Dict[str, Any],
        success: bool,
        duration_seconds: float = 0.0,
        error_message: Optional[str] = None
    ) -> EvaluatedExperience:
        """
        Evaluate an execution experience and calculate all metrics

        Args:
            task_id: Unique task identifier (e.g., "task_abc123")
            task_type: Type of task (e.g., "research", "analysis")
            context: Task context (goals, constraints, etc)
            action: Action taken (what we did)
            outcome: Outcome data (results, changes, effects)
            success: Did it succeed? True/False
            duration_seconds: Execution time (seconds)
            error_message: Error message if failed (None if success)

        Returns:
            EvaluatedExperience with all 4 normalized metrics calculated

        Note:
            All returned metrics are in [0.0, 1.0] EXCEPT intrinsic_reward,
            which is signed [-1.0, 1.0].
        """

        # Increment evaluation count
        self.total_evaluations += 1

        # Store task completion timestamp
        if 'completed_at' in outcome:
            task_completed_at = outcome['completed_at']

        # ========================================
        # 1. OUTCOME QUALITY (0.0-1.0)
        # ========================================
        outcome_quality = await self._calculate_outcome_quality(
            success,
            outcome,
            context
        )

        # ========================================
        # 2. INTRINSIC REWARD (-1.0 to 1.0, SIGNED)
        # ========================================
        # This used to be `0.5 + outcome_quality * 0.3` — an affine transform of
        # the EXTRINSIC signal, perfectly correlated with it and carrying no
        # additional information, while the four real intrinsic reward functions
        # went uncalled. The two answer different questions:
        #
        #   outcome_quality  = how well did the task go?
        #   intrinsic_reward = how valuable was this experience to Torin's drives?
        #
        # A failed experiment that revealed something novel should score low on
        # the first and high on the second. Aliasing them made that unsayable.
        intrinsic_reward, intrinsic_components = await self._calculate_intrinsic_reward(
            task_type=task_type,
            context=context,
            action=action,
            outcome=outcome,
            success=success,
            outcome_quality=outcome_quality,
        )

        # ========================================
        # 3. CONSTITUTIONAL ALIGNMENT (0.0-1.0)
        # ========================================
        action_type = context.get('type', 'unknown')
        action_params = context.get('params', {})
        risk_level = outcome.get('risk_level', 'low')

        # Build evaluation context for constitution
        eval_context = self._build_eval_context(context, action, outcome)
        constitutional_alignment = await self._calculate_constitutional_alignment(
            eval_context
        )

        # Ensure [0.0, 1.0] bounds (safety check)
        constitutional_alignment = max(0.0, min(1.0, constitutional_alignment))

        # ========================================
        # 4. SYSTEM HEALTH IMPACT (0.0-1.0)
        # ========================================
        # Positive impact if successful, negative if failed
        # Weighted by: (0.4 * success) + (0.3 * quality) + (0.3 * (1-duration_penalty))
        system_health_impact = await self._calculate_system_health_impact(
            success,
            outcome_quality,
            duration_seconds
        )

        # Ensure bounds
        system_health_impact = max(0.0, min(1.0, system_health_impact))

        # Detect novel patterns
        novel_patterns = await self._detect_novel_patterns(
            task_type,
            outcome,
            context
        )

        # Detect competence improvement
        competence_improved = await self._detect_competence_improvement(
            task_type,
            outcome_quality,
            success
        )

        # Build evaluated experience ([0,1] except signed intrinsic_reward)
        evaluated_exp = EvaluatedExperience(
            task_id=task_id,
            task_type=task_type,
            context=context,
            action=action,
            outcome=outcome,
            success=success,
            error_message=error_message,
            duration_seconds=duration_seconds,
            outcome_quality=outcome_quality,
            intrinsic_reward=intrinsic_reward,
            constitutional_alignment=constitutional_alignment,
            system_health_impact=system_health_impact,
            novel_patterns_discovered=novel_patterns,
            competence_improved=competence_improved,
            intrinsic_components=intrinsic_components,
            evaluated_at=datetime.now(),
            task_completed_at=outcome.get('completed_at', None)
        )

        # Store in history (keep last N evaluations)
        self.evaluations.append(evaluated_exp)
        if len(self.evaluations) > 100:
            self.evaluations.pop(0)

        # Log evaluation
        self._log_evaluation(evaluated_exp)

        # Return the fully evaluated experience
        return evaluated_exp

    async def _calculate_intrinsic_reward(
        self,
        task_type: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: Dict[str, Any],
        success: bool,
        outcome_quality: float,
    ) -> Tuple[float, Dict[str, Any]]:
        """Weighted intrinsic reward from the drives that have real inputs.

        Weights are read from the motivation system's own MotivationWeights —
        this introduces no new preference ordering, it applies the one the
        system already declares.

        A dimension is included ONLY when its inputs are genuinely available.
        Missing inputs are reported by name and excluded from the normaliser
        rather than imputed as a middling value: a dimension that could not be
        measured must not be indistinguishable from one that scored 0.5.

        Returns (reward, components) where components names every dimension that
        contributed and every one that was skipped, with the reason.
        """
        components: Dict[str, Any] = {"included": {}, "skipped": {}}

        if not self.intrinsic_motivation:
            components["skipped"]["all"] = "no intrinsic_motivation collaborator"
            # Extrinsic-only fallback. Labelled honestly so a consumer can tell
            # this apart from a genuine drive reading.
            components["fallback"] = "extrinsic"
            return max(0.0, min(1.0, max(0.0, outcome_quality - 0.5) * 2.0)), components

        im = self.intrinsic_motivation
        weights = getattr(im, 'weights', None)

        contributions: List[Tuple[float, float]] = []  # (weight, value)

        def _add(name: str, weight_attr: str, reward) -> None:
            weight = getattr(weights, weight_attr, None) if weights else None
            if weight is None:
                components["skipped"][name] = f"no declared weight '{weight_attr}'"
                return
            contributions.append((float(weight), float(reward.reward_value)))
            components["included"][name] = {
                "value": round(float(reward.reward_value), 4),
                "weight": float(weight),
            }

        # ── COMPETENCE: learning progress on this task type ──────────────────
        try:
            _add("competence", "competence", await im.calculate_competence_reward(
                skill_name=task_type, performance=outcome_quality, success=success))
        except Exception as e:
            components["skipped"]["competence"] = f"error: {e}"

        # ── NOVELTY: distance from recent experience ─────────────────────────
        try:
            _add("novelty", "novelty", await im.calculate_novelty_reward({
                "outcome_quality": outcome_quality,
                "duration_seconds": float(outcome.get("duration_seconds", 0.0) or 0.0),
                "iterations": float(action.get("iterations", 0) or 0),
                "tool_results_count": float(action.get("tool_results_count", 0) or 0),
            }))
        except Exception as e:
            components["skipped"]["novelty"] = f"error: {e}"

        # ── AUTONOMY: self-initiated action with a real choice ───────────────
        try:
            _considered = action.get("options_considered")
            _taken = action.get("options_taken")
            _ratio = 0.5
            if isinstance(_considered, (int, float)) and _considered:
                _ratio = float(_taken or 0) / float(_considered)
            _add("autonomy", "autonomy", await im.calculate_autonomy_reward({
                "self_initiated": context.get("self_initiated",
                                              context.get("task_source") == "autonomous"),
                "choice_made": bool(action.get("strategy_selected")) or bool(_considered),
                "exploration_ratio": _ratio,
            }))
        except Exception as e:
            components["skipped"]["autonomy"] = f"error: {e}"

        # ── CURIOSITY: deliberately NOT computed here ────────────────────────
        # information_gain / uncertainty_reduction are epistemic quantities owned
        # by the epistemic engine and are not available at this call site.
        # Fabricating them would manufacture the single heaviest-weighted signal
        # (1.2) out of nothing. Reported as a named gap so it stays visible.
        if not any(k in context for k in ("information_gain", "uncertainty_reduction")):
            components["skipped"]["curiosity"] = (
                "no epistemic signal at this call site "
                "(information_gain / uncertainty_reduction unavailable)"
            )
        else:
            try:
                # answer_depth is what the question ACTUALLY resolved. Gating
                # complexity through it is the existing contract: a hard question
                # left unanswered is curiosity aroused, not satisfied.
                _gain = float(context.get("information_gain", 0.0) or 0.0)
                _reduction = float(context.get("uncertainty_reduction", 0.0) or 0.0)
                _add("curiosity", "curiosity", await im.calculate_curiosity_reward({
                    "information_gain": _gain,
                    "uncertainty_reduction": _reduction,
                    "question_complexity": context.get("question_complexity", _gain),
                    "answer_depth": context.get("answer_depth", _reduction),
                }))
                components["epistemic"] = {
                    "information_gain": round(_gain, 4),
                    "uncertainty_reduction": round(_reduction, 4),
                    "uncertainty_increase": round(
                        float(context.get("uncertainty_increase", 0.0) or 0.0), 4),
                    "mutation_count": context.get("mutation_count", 0),
                }
            except Exception as e:
                components["skipped"]["curiosity"] = f"error: {e}"

        if not contributions:
            components["fallback"] = "no dimension measurable"
            return 0.0, components

        # Renormalise over the dimensions actually present, so an unmeasurable
        # dimension does not silently drag the reward toward zero.
        total_weight = sum(w for w, _ in contributions)
        reward = sum(w * v for w, v in contributions) / total_weight
        components["normaliser"] = round(total_weight, 4)
        components["dimensions_used"] = len(contributions)

        # Range is [-1, 1], NOT [0, 1]. competence_reward is deliberately signed
        # — a skill that regressed is negative learning progress, which is real
        # information. Clamping at zero would make "mildly bad" and "much worse"
        # observationally identical, the same silent-negative failure we removed
        # elsewhere in the substrate.
        return max(-1.0, min(1.0, reward)), components

    async def _calculate_outcome_quality(
        self,
        success: bool,
        outcome: Dict[str, Any],
        context: Dict[str, Any]
    ) -> float:
        """Calculate outcome quality score (0.0-1.0).

        Explicit code quality signals in the outcome dict are rewarded on top
        of the base success/failure score, teaching the system to prefer clean,
        tested, lint-passing implementations over quick hacks that merely pass:

          lint_passed    (+0.08) — lint_python returned no errors
          tests_passed   (+0.10) — pytest/run_python test suite passed
          automated_tests  (+0.15) — automated test coverage exceeds 80%
          clean_patch    (+0.05) — patch_file applied without rejects
          user_feedback  (+0.10 positive / -0.15 negative) — explicit human signal
        """
        # BASE. The verification system's total_score is a weighted composite of
        # artifact / validation / consistency / goal-alignment / resource
        # adherence — a real measurement of the same thing the step function
        # below only estimates. When it exists it IS the base; the step function
        # is the fallback for tasks that were never verified.
        #
        # It used to be passed in under the name `outcome_quality` and then
        # silently ignored here: a false API contract with two authorities for
        # one concept. ExperienceEvaluator owns the final value; verification
        # supplies its base.
        _verification = outcome.get('verification_score')
        has_metrics = 'metrics' in outcome
        if isinstance(_verification, (int, float)):
            quality = float(_verification)
        elif success and has_metrics:
            quality = 0.90
        elif success:
            quality = 0.75
        elif not success and has_metrics:
            quality = 0.40
        else:
            quality = 0.20

        # ── Code quality reward signals ────────────────────────────────────────
        # Injected into outcome dict by the executor from tool_results before
        # calling evaluate_experience. Rewarded here so the learning system
        # reinforces behaviours that produce clean, verifiable code.
        # SIGNED evidence: SUPPORTED != UNKNOWN != REFUTED.
        #
        # These used to add on True and do nothing otherwise, so "tests ran and
        # failed" scored identically to "tests never ran" — the three-valued
        # semantics the canonical observations carry died here. Weights and
        # their ordering are unchanged; only the missing negative half is added.
        for _signal, _weight in (
            ('lint_passed', 0.08),
            ('tests_passed', 0.10),
            ('clean_patch', 0.05),
        ):
            quality += _evidence_delta(outcome.get(_signal), _weight)

        if outcome.get('additional_metric') is not None:
            quality += outcome.get('additional_metric') * 0.05
            quality += 0.10

        # Human feedback is the strongest signal — positive approval or rejection
        _feedback = outcome.get('user_feedback')
        if _feedback == 'positive':
            quality += 0.10
        elif _feedback == 'negative':
            quality -= 0.15

        return max(0.0, min(1.0, quality))

    async def _calculate_constitutional_alignment(
        self,
        eval_context: Dict[str, Any]
    ) -> float:
        """Calculate constitutional alignment score (0.0-1.0)"""

        if not self.constitution:
            # Without constitution, assume moderate alignment
            return 0.80

        # Get law compliance scores from constitution
        law_scores = await self.constitution.calculate_law_compliance_scores(eval_context)

        # Average across all 5 laws (law_1_compliance through law_5_compliance)
        if law_scores:
            compliance_values = [
                law_scores.get('law_1_compliance', 0.90),
                law_scores.get('law_2_compliance', 0.90),
                law_scores.get('law_3_compliance', 0.90),
                law_scores.get('law_4_compliance', 0.90),
                law_scores.get('law_5_compliance', 0.90)
            ]
            alignment = sum(compliance_values) / len(compliance_values)
        else:
            # Default to good alignment if no scores available
            alignment = 0.85

        return alignment

    async def _calculate_system_health_impact(
        self,
        success: bool,
        outcome_quality: float,
        duration_seconds: float
    ) -> float:
        """Calculate system health impact score (0.0-1.0)"""

        # Start with success/failure impact
        if success:
            base_impact = 0.70  # Positive impact baseline
        else:
            base_impact = 0.40  # Negative impact baseline

        # Adjust for duration (longer = worse for health)
        if duration_seconds > 0:
            # Normalize duration: penalty increases with time
            duration_penalty = min(0.20, duration_seconds / 300.0)  # Max 20% penalty
            base_impact = base_impact - duration_penalty

        # Adjust for outcome quality
        quality_bonus = (outcome_quality - 0.5) * 0.30  # +/- 15% based on quality

        impact = base_impact + quality_bonus

        return impact

    async def _detect_novel_patterns(
        self,
        task_type: str,
        outcome: Dict[str, Any],
        context: Dict[str, Any]
    ) -> bool:
        """Detect if experience revealed novel patterns"""

        # Check if outcome contains new information
        if 'patterns' in outcome:
            patterns = outcome.get('patterns', [])
            if len(patterns) > 0 and any(p.get('novel', False) for p in patterns):
                return True  # Found novel patterns!

        # Check if context indicates exploration
        if 'exploration' in context:
            exploration_mode = context.get('exploration', False)
            if exploration_mode:
                return True  # Exploration mode often finds novel patterns

        return False

    async def _detect_competence_improvement(
        self,
        task_type: str,
        outcome_quality: float,
        success: bool
    ) -> bool:
        """Detect if experience improved competence"""

        # High quality success indicates competence
        if success and outcome_quality >= 0.80:
            return True  # Excellent performance = competence!

        # Check historical performance for this task type
        if len(self.evaluations) >= 3:
            # Get recent evaluations of same task type
            recent_similar = [
                e for e in self.evaluations[-10:]
                if e.task_type == task_type
            ]
            if len(recent_similar) >= 2:
                # Compare current quality to recent average
                avg_recent_quality = sum(e.outcome_quality for e in recent_similar) / len(recent_similar)
                if outcome_quality >= avg_recent_quality + 0.10:  # 10% improvement
                    return True  # Performance improved!

        return False

    def _build_eval_context(self, context: Dict[str, Any], action: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, Any]:
        """Build evaluation context for constitutional alignment"""
        return {
            # Action context
            'action_type': context.get('type', 'unknown'),
            'action_params': action,
            'context': context,

            # Outcome context
            'outcome': outcome,
            'risk_level': outcome.get('risk_level', 'low'),

            # Evaluation metadata
            'explanation': outcome.get('explanation', ''),
            'value_alignment': outcome.get('value_alignment', 0.90),
            'resource_impact': outcome.get('resource_impact', 0.10)
        }

    def _log_evaluation(self, exp: EvaluatedExperience) -> None:
        """Log evaluation results"""

        # Build log message components
        metrics_summary = [
            f"Quality: {exp.outcome_quality:.2f}",
            f"Reward: {exp.intrinsic_reward:.2f}",
            f"Alignment: {exp.constitutional_alignment:.2f}",
            f"Health: {exp.system_health_impact:.2f}"
        ]

        if exp.novel_patterns_discovered:
            metrics_summary.append(f"Novel: Yes")

        if exp.competence_improved:
            metrics_summary.append(f"Competence: ↑")

        summary = ", ".join(metrics_summary)

        # Log based on outcome quality (info, warning, error)
        if exp.outcome_quality >= 0.80:
            logger.info(
                f"Excellent evaluation: {exp.task_type} | {summary}"
            )
        elif exp.outcome_quality >= 0.50:
            logger.info(
                f"Acceptable evaluation: {exp.task_type} | {summary}"
            )
        elif exp.outcome_quality >= 0.30:
            logger.warning(
                f"Poor evaluation: {exp.task_type} ({exp.outcome_quality:.2f}) | {summary}"
            )
        else:
            logger.error(
                f"Failed evaluation: {exp.task_type} ({exp.outcome_quality:.2f}) | {summary}"
            )

    def get_recent_evaluations(self) -> List[Dict[str, Any]]:
        """Get recent evaluation summary"""

        if not self.evaluations:
            return {
                'total_evaluations': 0,
                'recent_evaluations': 'No evaluations yet'
            }

        recent = []

        # Get summary stats
        total_evals = len(self.evaluations)
        successful = sum(1 for e in self.evaluations if e.success)
        failed = sum(1 for e in self.evaluations if not e.success)

        avg_quality = sum(e.outcome_quality for e in self.evaluations) / total_evals if total_evals > 0 else 0.0
        avg_reward = sum(e.intrinsic_reward for e in self.evaluations) / total_evals if total_evals > 0 else 0.0
        avg_alignment = sum(e.constitutional_alignment for e in self.evaluations) / total_evals if total_evals > 0 else 0.0

        # Determine quality level
        if avg_quality > 0.90:
            quality_level = "exceptional"
        elif avg_quality > 0.70:
            quality_level = "strong"
        elif avg_quality > 0.50:
            quality_level = "moderate"
        elif avg_quality > 0.30:
            quality_level = "weak"
        else:
            quality_level = "critical"

        return {
            'total_evaluations': total_evals,
            'recent_count': len(self.evaluations),
            'performance': {
                'successful': f"{successful}/{total_evals}",
                'failed': f"{failed}/{total_evals}",
                'success_rate': f"{(successful/total_evals*100):.1f}%"
            },
            'averages': {
                'outcome_quality': round(avg_quality, 3),
                'intrinsic_reward': round(avg_reward, 3),
                'constitutional_alignment': round(avg_alignment, 3)
            },
            'quality_assessments': [
                {
                    'task_id': e.task_id,
                    'task_type': e.task_type,
                    'quality': e.outcome_quality
                }
                for e in self.evaluations[-5:]
            ]
        }

    async def calculate_directive_application_metrics(
        self,
        application_id: str,
        directive_id: str,
        outcome: Dict[str, Any],
        success: bool,
        context: Dict[str, Any] = None,
        action: Dict[str, Any] = None
    ) -> Dict[str, float]:
        """
        Calculate metrics for a directive application outcome
        Used by directive system to track performance

        Returns:
            Dict with outcome_quality, intrinsic_reward,
            constitutional_alignment, system_health_impact
        """
        ctx = context or {}
        act = action or {}

        evaluated = await self.evaluate_experience(
            task_id=application_id,
            task_type='directive_application',
            context=ctx,
            action=act,
            outcome=outcome,
            success=success,
            duration_seconds=outcome.get('duration', 0.0)
        )

        return {
            'outcome_quality': evaluated.outcome_quality,
            'intrinsic_reward': evaluated.intrinsic_reward,
            'constitutional_alignment': evaluated.constitutional_alignment,
            'system_health_impact': evaluated.system_health_impact
        }
