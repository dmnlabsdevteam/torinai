#!/usr/bin/env python3
"""
Learning Adapter - Experience integration and learning
Processes execution results and updates knowledge base
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass

from .shared_types import LearningData
from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


@dataclass
class LearningMetrics:
    """Metrics for learning system performance"""
    experiences_processed: int = 0
    successful_integrations: int = 0
    failed_integrations: int = 0
    patterns_discovered: int = 0
    average_confidence: float = 0.0


class LearningAdapter:
    """
    Learning Adapter - Integrate experiences and update knowledge

    Processes execution results and learns from:
    - Successful task completions
    - Failed attempts
    - Novel situations
    - Pattern recognition
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        # Learning state
        self.experiences: List[LearningData] = []
        self.patterns: Dict[str, Any] = {}
        self.metrics = LearningMetrics()

        # Database
        self.db = TorinUnifiedDatabase()

        # Integration points (set by coordinator)
        self.governance_system = None
        self.security_audit_worker = None
        self.monitoring_coordinator = None

        # Configuration
        self.experience_buffer_size = self.config.get("experience_buffer_size", 100)
        self.min_confidence_threshold = self.config.get("min_confidence", 0.3)
        self.pattern_discovery_enabled = self.config.get("pattern_discovery", True)

        logger.info("Learning adapter initialized")

    async def initialize(self) -> bool:
        """Initialize the learning adapter"""
        try:
            await self.db.initialize()
            self.active = True
            logger.info("Learning adapter ready")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize learning adapter: {e}")
            return False

    async def shutdown(self) -> None:
        """Shutdown the learning adapter"""
        try:
            if self.experiences:
                logger.info(f"Processing {len(self.experiences)} buffered experiences")
                await self._batch_process_experiences()
            self.active = False
            logger.info("Learning adapter shutdown")
        except Exception as e:
            logger.error(f"Error during learning adapter shutdown: {e}")

    def set_governance_system(self, governance_system):
        """Set the shared governance system instance"""
        self.governance_system = governance_system
        logger.info("Learning adapter connected to shared governance system")

    def set_security_audit_worker(self, security_audit_worker):
        """Set the security audit worker instance"""
        self.security_audit_worker = security_audit_worker
        logger.info("Learning adapter connected to security audit worker")

    def set_monitoring_coordinator(self, monitoring_coordinator):
        """Set the monitoring coordinator instance"""
        self.monitoring_coordinator = monitoring_coordinator
        logger.info("Learning adapter connected to monitoring coordinator")

    async def get_recommendations(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return learning recommendations based on observed patterns.

        This is used by the autonomous coordinator's learning phase.

        Recommendations are derived from the internal pattern table and
        basic metrics, so they are grounded in actual past experiences
        (success/failure counts and confidence).
        """
        if not self.active:
            return []

        recommendations: List[Dict[str, Any]] = []

        # The coordinator's applier understands three verbs --
        # adjust_cycle_interval, prioritize_task_type, allocate_resources --
        # and reads its target from action["task_type"]. This emitted the bare
        # action name as the verb, which matched no branch, so the learning
        # phase could apply nothing however much evidence accumulated.
        MIN_TRIALS = 3
        MIN_SUCCESS_RATE = 0.6

        try:
            # One recommendation per task type, aggregated across contexts.
            # The applier boosts a whole type by one priority level, so
            # emitting per-context patterns would boost the same type
            # repeatedly within a single pass.
            by_type: Dict[str, Dict[str, int]] = {}
            for pattern in self.patterns.values():
                action_type = pattern.get("action_type", "unknown")
                agg = by_type.setdefault(
                    action_type, {"successes": 0, "failures": 0, "contexts": 0}
                )
                agg["successes"] += pattern.get("successes", 0)
                agg["failures"] += pattern.get("failures", 0)
                agg["contexts"] += 1

            for action_type, agg in by_type.items():
                successes = agg["successes"]
                failures = agg["failures"]
                total = successes + failures

                # Require a minimum amount of signal
                if total < MIN_TRIALS:
                    continue

                success_rate = successes / total

                # Prioritising a task type that mostly fails is not a
                # recommendation, it is an amplifier for the failure.
                if success_rate < MIN_SUCCESS_RATE:
                    continue

                recommendations.append({
                    "action": {
                        "type": "prioritize_task_type",
                        "task_type": action_type,
                        "priority_boost": round(success_rate * 0.4, 4),
                        "successes": successes,
                        "failures": failures,
                        "contexts": agg["contexts"],
                    },
                    "confidence": success_rate,
                    "source": "learning_adapter",
                    "context": {
                        "experiences_processed": self.metrics.experiences_processed,
                        "average_confidence": self.metrics.average_confidence,
                        "requested_context": context,
                    },
                })

            # Sort recommendations by descending confidence
            recommendations.sort(key=lambda r: r.get("confidence", 0.0), reverse=True)

        except Exception as e:
            logger.error(f"Failed to generate learning recommendations: {e}")

        return recommendations

    async def integrate_experience(self, learning_data: LearningData) -> bool:
        """Integrate a learning experience"""
        if not self.active:
            return False

        try:
            if learning_data.confidence < self.min_confidence_threshold:
                return False

            self.experiences.append(learning_data)
            self.metrics.experiences_processed += 1

            success = await self._process_experience(learning_data)
            if success:
                self.metrics.successful_integrations += 1
            else:
                self.metrics.failed_integrations += 1

            self._update_average_confidence(learning_data.confidence)

            if len(self.experiences) >= self.experience_buffer_size:
                await self._batch_process_experiences()

            if self.pattern_discovery_enabled and self.metrics.experiences_processed % 10 == 0:
                await self._discover_patterns()

            return success
        except Exception as e:
            logger.error(f"Failed to integrate experience: {e}")
            return False

    @staticmethod
    def _action_type(action: Any) -> str:
        """Action label, whether it arrives as a string or a structured dict.

        LearningData.action is typed str, but this read it as a dict via
        .get("type"), so every reinforce/failure path raised
        "'str' object has no attribute 'get'".
        """
        if isinstance(action, dict):
            return str(action.get("type", "unknown"))
        return str(action) if action else "unknown"

    def _update_average_confidence(self, confidence: float) -> None:
        """Fold one experience's confidence into the running mean.

        Called by integrate_experience but never defined, so every call raised
        AttributeError. The surrounding try/except reported that as a failed
        integration while the success counter had already been incremented --
        the metrics and the return value disagreed.
        """
        processed = max(1, self.metrics.experiences_processed)
        previous = self.metrics.average_confidence
        self.metrics.average_confidence = (
            (previous * (processed - 1)) + float(confidence)
        ) / processed

    async def _discover_patterns(self) -> int:
        """Promote repeated action/context outcomes into recorded patterns.

        Also never defined. Because the AttributeError above fired first,
        neither this nor _batch_process_experiences was ever reached.
        """
        discovered = 0
        for pattern in self.patterns.values():
            total = pattern.get("successes", 0) + pattern.get("failures", 0)
            if total < 3:
                continue
            if pattern.get("discovered"):
                continue
            pattern["discovered"] = True
            discovered += 1

        if discovered:
            self.metrics.patterns_discovered += discovered
            logger.info(f"Discovered {discovered} learning pattern(s)")
        return discovered

    async def _process_experience(self, learning_data: LearningData) -> bool:
        """Process a single learning experience"""
        try:
            learning_record = {
                "timestamp": learning_data.timestamp,
                "context": learning_data.context,
                "action": learning_data.action,
                "outcome": learning_data.outcome,
                "success": learning_data.success,
                "confidence": learning_data.confidence
            }

            if learning_data.success:
                await self._reinforce_success(learning_record)
            else:
                await self._learn_from_failure(learning_record)

            return True
        except Exception as e:
            logger.error(f"Failed to process experience: {e}")
            return False

    async def _reinforce_success(self, learning_record: Dict[str, Any]) -> None:
        """Reinforce successful patterns"""
        try:
            action_type = self._action_type(learning_record["action"])
            context_hash = str(hash(str(learning_record["context"])))
            pattern_key = f"{action_type}_{context_hash}"

            if pattern_key not in self.patterns:
                self.patterns[pattern_key] = {
                    "action_type": action_type,
                    "successes": 0,
                    "failures": 0,
                    "confidence": 0.5
                }

            self.patterns[pattern_key]["successes"] += 1
            total = self.patterns[pattern_key]["successes"] + self.patterns[pattern_key]["failures"]
            self.patterns[pattern_key]["confidence"] = self.patterns[pattern_key]["successes"] / total
        except Exception as e:
            logger.error(f"Failed to reinforce success: {e}")

    async def _learn_from_failure(self, learning_record: Dict[str, Any]) -> None:
        """Learn from failed attempts"""
        try:
            action_type = self._action_type(learning_record["action"])
            context_hash = str(hash(str(learning_record["context"])))
            pattern_key = f"{action_type}_{context_hash}"

            if pattern_key not in self.patterns:
                self.patterns[pattern_key] = {
                    "action_type": action_type,
                    "successes": 0,
                    "failures": 0,
                    "confidence": 0.5
                }

            self.patterns[pattern_key]["failures"] += 1
            total = self.patterns[pattern_key]["successes"] + self.patterns[pattern_key]["failures"]
            self.patterns[pattern_key]["confidence"] = self.patterns[pattern_key]["successes"] / total
        except Exception as e:
            logger.error(f"Failed to learn from failure: {e}")

    async def _batch_process_experiences(self) -> None:
        """Process buffered experiences in batch"""
        try:
            if not self.experiences:
                return
            logger.debug(f"Batch processing {len(self.experiences)} experiences")
            self.experiences.clear()
        except Exception as e:
            logger.error(f"Batch processing failed: {e}")

    async def get_learning_insights(self) -> Dict[str, Any]:
        """Return high-level learning insights for system status.

        This is used by the autonomous coordinator when building
        system status snapshots. Insights are grounded in internal
        metrics and discovered patterns rather than heuristics.
        """
        try:
            total_experiences = len(self.experiences)
            total_attempts = (
                self.metrics.successful_integrations
                + self.metrics.failed_integrations
            )
            success_rate = (
                self.metrics.successful_integrations / total_attempts
                if total_attempts > 0
                else 0.0
            )

            top_patterns: List[Dict[str, Any]] = []
            for key, pattern in self.patterns.items():
                top_patterns.append({
                    "pattern_key": key,
                    "action_type": pattern.get("action_type", "unknown"),
                    "successes": pattern.get("successes", 0),
                    "failures": pattern.get("failures", 0),
                    "confidence": pattern.get("confidence", 0.0),
                })

            # Sort patterns by confidence and take top 5
            top_patterns.sort(key=lambda p: p.get("confidence", 0.0), reverse=True)
            top_patterns = top_patterns[:5]

            insights: Dict[str, Any] = {
                "total_experiences": total_experiences,
                "success_rate": success_rate,
                "top_patterns": top_patterns,
                "statistics": {
                    "experiences_processed": self.metrics.experiences_processed,
                    "successful_integrations": self.metrics.successful_integrations,
                    "failed_integrations": self.metrics.failed_integrations,
                    "patterns_discovered": self.metrics.patterns_discovered,
                    "average_confidence": self.metrics.average_confidence,
                },
            }

            return insights
        except Exception as e:
            logger.error(f"Failed to generate learning insights: {e}")
            return {}

    # ---- RECOVERED FROM DEAD CODE -------------------------------------
    #
    # These were indented into get_learning_adapter(), after its `return`.
    # Syntactically valid, never executed, never attached to the class --
    # so `LearningAdapter` had no `update_config` at all and the
    # human-only approval rule for learner config changes could not be
    # enforced because the code enforcing it was unreachable.

    #: Config keys that __init__ also caches on the instance. A change to one
    #: of these must move BOTH, or the adapter keeps using the old value while
    #: reporting the new one.
    _CONFIG_ATTRIBUTES = {
        "experience_buffer_size": "experience_buffer_size",
        "min_confidence": "min_confidence_threshold",
    }

    async def update_config(
        self,
        parameter_name: str,
        new_value: Any,
        approval_signature: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Update learner configuration (GOVERNANCE-ENABLED - HUMAN-ONLY).

        Phase 4: Learner config changes require HUMAN-ONLY approval.
        AI judges CANNOT vote on learner config (prevents policy drift).
        Learner CANNOT approve its own config changes (prevents self-modification).

        Args:
            parameter_name: Name of config parameter to update
            new_value: New value for the parameter
            approval_signature: Human-only approval signature (required)

        Returns:
            Dict with update result and governance decision

        Raises:
            PermissionError: If approval signature invalid, AI judge vote, or learner self-approval
        """
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )

        # Phase 4: Evaluate governance BEFORE any config update
        # Use injected governance singleton or get singleton
        if self.governance_system:
            governance = self.governance_system
        else:
            from core.governance import get_unified_governance
            governance = get_unified_governance()
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.LEARNING_PARAMETERS,
            action_type="propose_learner_config_change",
            parameters={
                "parameter_name": parameter_name,
                "new_value": new_value,
                "current_value": self.config.get(parameter_name)
            },
            context={
                "source": "LearningAdapter",  # CRITICAL: Must be in context, not parameters
                "component": "learning_adapter"
            }
        )

        # CRITICAL: Learner config changes require HUMAN-ONLY approval
        if evaluation.decision_tier.name in ["CRITICAL", "IMPORTANT"]:
            # Validate HUMAN-ONLY approval signature
            if not self._validate_human_only_approval(approval_signature):
                return {
                    "success": False,
                    "error": "GOVERNANCE_REQUIRED",
                    "message": f"Learner config changes require HUMAN-ONLY approval. Triggered: {evaluation.trigger_id}",
                    "trigger_id": evaluation.trigger_id,
                    "action_id": evaluation.action_id,
                    "approval_required": True,
                    "human_only_approval": True,
                }

        # If we reach here, approval is valid
        try:
            # Update config. The live attribute, not just the config dict:
            # __init__ reads experience_buffer_size and min_confidence out of
            # config ONCE, so writing only the dict left the adapter running on
            # the old value while reporting the change as applied.
            attribute = self._CONFIG_ATTRIBUTES.get(parameter_name)
            old_value = (getattr(self, attribute) if attribute
                         else self.config.get(parameter_name))
            self.config[parameter_name] = new_value
            if attribute:
                setattr(self, attribute, new_value)

            logger.info(
                f"Learner config updated: {parameter_name}={new_value} "
                f"(was {old_value}), "
                f"approved_by={approval_signature.get('voter_id') if approval_signature else 'NONE'}"
            )

            return {
                "success": True,
                "parameter_name": parameter_name,
                "old_value": old_value,
                "new_value": new_value,
                "trigger_id": evaluation.trigger_id,
                "action_id": evaluation.action_id,
                "approved_by": approval_signature.get("voter_id") if approval_signature else None,
                "human_only_approval": True,
                "expiration_days": 90
            }

        except Exception as e:
            logger.error(f"Learner config update failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _validate_human_only_approval(self, signature: Optional[Dict[str, Any]]) -> bool:
        """
        Validate HUMAN-ONLY approval signature for learner config changes.

        Phase 4: CRITICAL security checks
        - REJECT AI judge votes (policy drift prevention)
        - REJECT learner self-approval (AI self-modification prevention)
        - REQUIRE voter_type == "human"
        - REQUIRE cryptographic signature
        - REQUIRE valid timestamp (not expired)

        Args:
            signature: Approval signature dict

        Returns:
            True if valid human-only approval, False otherwise

        Raises:
            PermissionError: If AI judge vote or learner self-approval detected
        """
        if not signature:
            logger.warning("No approval signature provided for learner config change")
            return False

        # CRITICAL: Reject AI judge votes (policy drift prevention)
        voter_type = signature.get("voter_type", "")
        if voter_type != "human":
            raise PermissionError(
                f"AI judge votes NOT ALLOWED for learner config changes. "
                f"This prevents policy drift via indirect path. "
                f"voter_type must be 'human', got '{voter_type}'"
            )

        # CRITICAL: Reject learner self-approval (AI self-modification prevention)
        voter_id = signature.get("voter_id", "")
        learner_patterns = ["learner", "learning_adapter", "learning_system"]
        if any(pattern in voter_id.lower() for pattern in learner_patterns):
            raise PermissionError(
                f"Learner cannot approve its own config changes. "
                f"This prevents direct AI self-modification. "
                f"voter_id '{voter_id}' matches learner pattern"
            )

        # CRITICAL: Require cryptographic signature
        crypto_signature = signature.get("signature")
        if not crypto_signature:
            logger.warning("Missing cryptographic signature for learner config change")
            return False

        # CRITICAL: Validate timestamp (90-day expiration)
        approved_at = signature.get("approved_at")
        if approved_at:
            from datetime import datetime, timedelta
            try:
                if isinstance(approved_at, str):
                    approved_time = datetime.fromisoformat(approved_at)
                else:
                    approved_time = approved_at

                # Check if expired (90 days)
                if datetime.now() - approved_time > timedelta(days=90):
                    logger.warning(
                        f"Approval signature expired (>90 days old): "
                        f"approved_at={approved_at}"
                    )
                    return False
            except Exception as e:
                logger.error(f"Failed to validate approval timestamp: {e}")
                return False

        # Block known non-human system identifiers
        blocked_voter_patterns = ["governance_agent", "system", "autonomous"]
        if any(pattern in voter_id.lower() for pattern in blocked_voter_patterns):
            raise PermissionError(
                f"Non-human system cannot approve learner config changes. "
                f"voter_id '{voter_id}' matches blocked pattern"
            )

        # All checks passed
        logger.info(
            f"Valid HUMAN-ONLY approval signature: voter_id={voter_id}, "
            f"voter_type={voter_type}"
        )
        return True

    async def get_learning_state(self) -> Dict[str, Any]:
        """Get current learning state"""
        return {
            "active": self.active,
            "experiences_buffered": len(self.experiences),
            "patterns_discovered": len(self.patterns),
            "metrics": {
                "experiences_processed": self.metrics.experiences_processed,
                "successful_integrations": self.metrics.successful_integrations,
                "average_confidence": self.metrics.average_confidence
            }
        }


# ============================================================================
# Singleton accessor
# ============================================================================

_learning_adapter_singleton: Optional[LearningAdapter] = None


def get_learning_adapter(
    config: Optional[Dict[str, Any]] = None,
) -> LearningAdapter:
    """Get global LearningAdapter instance (singleton).

    The first caller may provide configuration; later calls ignore
    config overrides and return the existing instance.
    """
    global _learning_adapter_singleton

    if _learning_adapter_singleton is None:
        _learning_adapter_singleton = LearningAdapter(config=config)
    else:
        if config:
            logger.debug(
                "get_learning_adapter called with config after initialization; "
                "ignoring override and returning existing singleton"
            )

    return _learning_adapter_singleton

