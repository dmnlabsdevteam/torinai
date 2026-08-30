"""
Enforcement Mode Manager

Manages the transition from shadow mode (LOG_ONLY) to enforcement mode (MUST_BLOCK)
with phased rollout capabilities. Supports per-category and per-trigger enforcement
configuration with persistence and rollback capabilities.

Rollout Stages:
1. Shadow Mode (LOG_ONLY): All actions allowed, triggers logged
2. Critical Only: CRITICAL tier actions blocked, others in shadow mode
3. Full Enforcement: All tiers enforced according to configuration

Rollback Capability:
- Automatic rollback if false positive rate exceeds threshold
- Manual rollback for debugging or tuning
- Rollback preserves shadow mode data for analysis
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from collections import defaultdict

from core.governance.unified_governance_trigger_system import (
    ActionCategory,
    EnforcementMode,
    DecisionTier
)

logger = logging.getLogger(__name__)


@dataclass
class EnforcementConfig:
    """Per-category enforcement mode configuration"""
    category: ActionCategory
    enforcement_mode: EnforcementMode  # Global mode for this category
    override_triggers: Dict[str, str]  # trigger_id -> enforcement_mode (as string)
    enabled: bool  # Master enable/disable switch
    rollout_stage: int  # 1 = shadow, 2 = critical only, 3 = full enforcement
    last_updated: datetime
    updated_by: str  # Who made the change


@dataclass
class EnforcementRollbackEvent:
    """Record of an enforcement rollback"""
    category: ActionCategory
    reason: str
    previous_mode: EnforcementMode
    rollback_to_mode: EnforcementMode
    timestamp: datetime
    triggered_by: str  # "automatic" or user_id
    metrics_snapshot: Dict  # Metrics at time of rollback


class EnforcementModeManager:
    """
    Manages enforcement mode transitions and phased rollout.

    Responsibilities:
    - Enable/disable enforcement per category
    - Override enforcement for specific triggers
    - Persist enforcement configuration
    - Rollback to shadow mode if issues detected
    - Track rollback events for audit
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize enforcement mode manager.

        Args:
            config_path: Path to enforcement config file (default: config/enforcement_config.json)
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "enforcement_config.json"

        self.config_path = config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Category configurations
        self.configs: Dict[ActionCategory, EnforcementConfig] = {}

        # Rollback history
        self.rollback_events: List[EnforcementRollbackEvent] = []

        # Initialize all categories to shadow mode
        self._initialize_default_configs()

        # Note: To load persisted config, call await manager.load_enforcement_config() after initialization

        logger.info(f"EnforcementModeManager initialized, config: {self.config_path}")

    #: Rules that block regardless of what the derivation says, seeded at
    #: construction rather than by a call somewhere at startup.
    #:
    #: `blocking_mode` asks whether an action can be undone, and by that test
    #: `config_001` is FULLY_REVERSIBLE -- a safety threshold can be set back.
    #: What cannot be undone is every evaluation made while it was wrong: the
    #: rule corrupts the instrument the other fifty-five rules are measured
    #: with, so it is not in the same category as the actions it governs.
    #:
    #: It WAS set only inside `activate_production_enforcement`, which the
    #: coordinator calls on startup. A guarantee that holds only after
    #: something else runs is not a guarantee -- any process constructing the
    #: manager directly got a version where the one unconditional block was
    #: absent, and nothing said so.
    ALWAYS_BLOCK = {
        ActionCategory.CONFIGURATION_CHANGES: {
            "config_001": EnforcementMode.MUST_BLOCK,
        },
    }

    def _initialize_default_configs(self) -> None:
        """Initialize all categories with shadow mode defaults"""
        for category in ActionCategory:
            self.configs[category] = EnforcementConfig(
                category=category,
                # ENFORCING, NOT SHADOWING. Shadow existed because 44 rules
                # declared MUST_BLOCK and switching them on at once would have
                # denied most of what the agent does. What a rule means is now
                # derived from whether the action can be undone, which blocks
                # five of fifty-six -- so there is nothing left for shadow to
                # protect against, and a gate that has never been switched on
                # is indistinguishable from no gate.
                # `disable_enforcement()` remains the way back to observing.
                enforcement_mode=EnforcementMode.RECOMMEND_GOVERNANCE,
                override_triggers={
                    trigger_id: mode.value for trigger_id, mode
                    in self.ALWAYS_BLOCK.get(category, {}).items()
                },
                enabled=True,
                rollout_stage=2,
                last_updated=datetime.now(),
                updated_by="system"
            )

    async def enable_enforcement(
        self,
        category: ActionCategory,
        mode: EnforcementMode,
        updated_by: str = "system",
        rollout_stage: int = 3
    ) -> None:
        """
        Enable enforcement for a category.

        Args:
            category: Action category to enable enforcement for
            mode: Enforcement mode (LOG_ONLY, RECOMMEND_GOVERNANCE, MUST_BLOCK)
            updated_by: Who is making this change
            rollout_stage: Rollout stage (1=shadow, 2=critical only, 3=full)
        """
        if category not in self.configs:
            self.configs[category] = EnforcementConfig(
                category=category,
                enforcement_mode=mode,
                override_triggers={},
                enabled=True,
                rollout_stage=rollout_stage,
                last_updated=datetime.now(),
                updated_by=updated_by
            )
        else:
            config = self.configs[category]
            config.enforcement_mode = mode
            config.enabled = True
            config.rollout_stage = rollout_stage
            config.last_updated = datetime.now()
            config.updated_by = updated_by

        logger.info(
            f"Enforcement enabled: {category.value} → {mode.value} "
            f"(stage {rollout_stage}) by {updated_by}"
        )

        # Persist changes
        await self.save_enforcement_config()

    async def disable_enforcement(
        self,
        category: ActionCategory,
        updated_by: str = "system"
    ) -> None:
        """
        Disable enforcement for a category (sets to shadow mode).

        Args:
            category: Action category to disable enforcement for
            updated_by: Who is making this change
        """
        if category in self.configs:
            config = self.configs[category]
            config.enabled = False
            config.enforcement_mode = EnforcementMode.LOG_ONLY
            config.last_updated = datetime.now()
            config.updated_by = updated_by

            logger.info(f"Enforcement disabled: {category.value} by {updated_by}")

            # Persist changes
            await self.save_enforcement_config()

    async def set_trigger_override(
        self,
        category: ActionCategory,
        trigger_id: str,
        mode: EnforcementMode,
        updated_by: str = "system"
    ) -> None:
        """
        Override enforcement mode for a specific trigger.

        Args:
            category: Action category
            trigger_id: Trigger ID to override
            mode: Enforcement mode for this trigger
            updated_by: Who is making this change
        """
        if category not in self.configs:
            self._initialize_default_configs()

        config = self.configs[category]
        config.override_triggers[trigger_id] = mode.value
        config.last_updated = datetime.now()
        config.updated_by = updated_by

        logger.info(
            f"Trigger override set: {category.value}/{trigger_id} → {mode.value} "
            f"by {updated_by}"
        )

        # Persist changes
        await self.save_enforcement_config()

    async def get_enforcement_mode(
        self,
        category: ActionCategory,
        trigger_id: Optional[str] = None
    ) -> EnforcementMode:
        """
        Get effective enforcement mode for a category/trigger.

        Args:
            category: Action category
            trigger_id: Optional trigger ID (checks for override)

        Returns:
            Effective enforcement mode
        """
        if category not in self.configs:
            return EnforcementMode.LOG_ONLY

        config = self.configs[category]

        if not config.enabled:
            return EnforcementMode.LOG_ONLY

        # Check for trigger-specific override
        if trigger_id and trigger_id in config.override_triggers:
            override_mode_str = config.override_triggers[trigger_id]
            return EnforcementMode(override_mode_str)

        # Return category-level mode
        return config.enforcement_mode

    def trigger_override(
        self,
        category: ActionCategory,
        trigger_id: Optional[str] = None
    ) -> Optional[EnforcementMode]:
        """An explicit per-trigger decision, or None where there is none.

        An override is a deliberate statement about ONE rule and outranks
        everything derived. `config_001` is the only one set: modifying safety
        thresholds corrupts the evaluation system itself, so it cannot be
        permitted however reversible it looks.
        """
        config = self.configs.get(category)
        if not config or not trigger_id:
            return None
        mode = config.override_triggers.get(trigger_id)
        return EnforcementMode(mode) if mode else None

    def in_shadow(self, category: ActionCategory) -> bool:
        """Whether this category is still observing rather than enforcing.

        Shadow is a ROLLOUT state, not a description of what the rules mean --
        that is derived from irreversibility in the trigger system. Conflating
        the two is what made 44 MUST_BLOCK declarations inert.
        """
        config = self.configs.get(category)
        if config is None:
            return True
        return not config.enabled or config.enforcement_mode == EnforcementMode.LOG_ONLY

    async def rollback_to_shadow(
        self,
        category: ActionCategory,
        reason: str,
        triggered_by: str = "automatic",
        metrics_snapshot: Optional[Dict] = None
    ) -> None:
        """
        Rollback to shadow mode if issues detected.

        Args:
            category: Action category to rollback
            reason: Reason for rollback
            triggered_by: "automatic" or user_id
            metrics_snapshot: Optional metrics at time of rollback
        """
        if category not in self.configs:
            logger.warning(f"Cannot rollback {category.value}: not configured")
            return

        config = self.configs[category]
        previous_mode = config.enforcement_mode

        # Create rollback event
        rollback_event = EnforcementRollbackEvent(
            category=category,
            reason=reason,
            previous_mode=previous_mode,
            rollback_to_mode=EnforcementMode.LOG_ONLY,
            timestamp=datetime.now(),
            triggered_by=triggered_by,
            metrics_snapshot=metrics_snapshot or {}
        )

        self.rollback_events.append(rollback_event)

        # Rollback to shadow mode
        config.enforcement_mode = EnforcementMode.LOG_ONLY
        config.rollout_stage = 1  # Shadow mode
        config.last_updated = datetime.now()
        config.updated_by = triggered_by

        logger.warning(
            f"ROLLBACK: {category.value} {previous_mode.value} → LOG_ONLY. "
            f"Reason: {reason}. Triggered by: {triggered_by}"
        )

        # Persist changes
        await self.save_enforcement_config()

    async def get_enforcement_config(
        self,
        category: ActionCategory
    ) -> Optional[EnforcementConfig]:
        """
        Get current enforcement configuration for a category.

        Args:
            category: Action category

        Returns:
            EnforcementConfig or None if not configured
        """
        return self.configs.get(category)

    async def get_all_configs(self) -> Dict[ActionCategory, EnforcementConfig]:
        """Get all enforcement configurations"""
        return self.configs.copy()

    async def save_enforcement_config(self) -> None:
        """Persist enforcement config to disk"""
        config_data = {
            "configs": {},
            "rollback_events": [],
            "last_saved": datetime.now().isoformat()
        }

        # Serialize configs
        for category, config in self.configs.items():
            config_data["configs"][category.value] = {
                "category": config.category.value,
                "enforcement_mode": config.enforcement_mode.value,
                "override_triggers": config.override_triggers,
                "enabled": config.enabled,
                "rollout_stage": config.rollout_stage,
                "last_updated": config.last_updated.isoformat(),
                "updated_by": config.updated_by
            }

        # Serialize rollback events
        for event in self.rollback_events:
            config_data["rollback_events"].append({
                "category": event.category.value,
                "reason": event.reason,
                "previous_mode": event.previous_mode.value,
                "rollback_to_mode": event.rollback_to_mode.value,
                "timestamp": event.timestamp.isoformat(),
                "triggered_by": event.triggered_by,
                "metrics_snapshot": event.metrics_snapshot
            })

        # Write to file
        with open(self.config_path, 'w') as f:
            json.dump(config_data, f, indent=2)

        logger.debug(f"Enforcement config saved to {self.config_path}")

    async def load_enforcement_config(self) -> None:
        """Load enforcement config from disk"""
        if not self.config_path.exists():
            logger.warning(f"Enforcement config not found: {self.config_path}")
            return

        with open(self.config_path, 'r') as f:
            config_data = json.load(f)

        # Load configs
        for category_str, config_dict in config_data.get("configs", {}).items():
            category = ActionCategory(category_str)
            self.configs[category] = EnforcementConfig(
                category=category,
                enforcement_mode=EnforcementMode(config_dict["enforcement_mode"]),
                override_triggers=config_dict["override_triggers"],
                enabled=config_dict["enabled"],
                rollout_stage=config_dict["rollout_stage"],
                last_updated=datetime.fromisoformat(config_dict["last_updated"]),
                updated_by=config_dict["updated_by"]
            )

        # Load rollback events
        for event_dict in config_data.get("rollback_events", []):
            self.rollback_events.append(EnforcementRollbackEvent(
                category=ActionCategory(event_dict["category"]),
                reason=event_dict["reason"],
                previous_mode=EnforcementMode(event_dict["previous_mode"]),
                rollback_to_mode=EnforcementMode(event_dict["rollback_to_mode"]),
                timestamp=datetime.fromisoformat(event_dict["timestamp"]),
                triggered_by=event_dict["triggered_by"],
                metrics_snapshot=event_dict.get("metrics_snapshot", {})
            ))

        logger.info(
            f"Enforcement config loaded: {len(self.configs)} categories, "
            f"{len(self.rollback_events)} rollback events"
        )

    async def check_rollback_triggers(
        self,
        category: ActionCategory,
        false_positive_rate: Optional[float] = None,
        queue_wait_time_p95: Optional[float] = None,
        commitment_violation_rate: Optional[float] = None
    ) -> bool:
        """
        Check if automatic rollback should be triggered.

        Args:
            category: Action category to check
            false_positive_rate: Optional false positive rate (0.0-1.0)
            queue_wait_time_p95: Optional p95 queue wait time in seconds
            commitment_violation_rate: Optional commitment violation rate (0.0-1.0)

        Returns:
            True if rollback was triggered, False otherwise
        """
        rollback_needed = False
        reason = None

        # Check false positive rate (>30% triggers rollback)
        if false_positive_rate is not None and false_positive_rate > 0.30:
            rollback_needed = True
            reason = f"High false positive rate: {false_positive_rate*100:.1f}% (>30%)"

        # Check queue wait time (>10 min for IMPORTANT tier triggers rollback)
        elif queue_wait_time_p95 is not None and queue_wait_time_p95 > 600:
            rollback_needed = True
            reason = f"High queue wait time: {queue_wait_time_p95:.1f}s (>10 min)"

        # Check commitment violation rate (>5% triggers review)
        elif commitment_violation_rate is not None and commitment_violation_rate > 0.05:
            rollback_needed = True
            reason = f"High commitment violation rate: {commitment_violation_rate*100:.1f}% (>5%)"

        if rollback_needed:
            metrics_snapshot = {
                "false_positive_rate": false_positive_rate,
                "queue_wait_time_p95": queue_wait_time_p95,
                "commitment_violation_rate": commitment_violation_rate
            }

            await self.rollback_to_shadow(
                category=category,
                reason=reason,
                triggered_by="automatic",
                metrics_snapshot=metrics_snapshot
            )

            return True

        return False

    async def get_rollout_status(self) -> Dict:
        """
        Get current rollout status across all categories.

        Returns:
            Summary of enforcement status
        """
        status = {
            "total_categories": len(ActionCategory),
            "shadow_mode_count": 0,
            "enforcement_enabled_count": 0,
            "critical_only_count": 0,
            "full_enforcement_count": 0,
            "categories": {}
        }

        for category, config in self.configs.items():
            category_status = {
                "enforcement_mode": config.enforcement_mode.value,
                "enabled": config.enabled,
                "rollout_stage": config.rollout_stage,
                "override_count": len(config.override_triggers),
                "last_updated": config.last_updated.isoformat()
            }

            status["categories"][category.value] = category_status

            # Count by stage
            if not config.enabled or config.enforcement_mode == EnforcementMode.LOG_ONLY:
                status["shadow_mode_count"] += 1
            elif config.rollout_stage == 2:
                status["critical_only_count"] += 1
            elif config.rollout_stage == 3:
                status["full_enforcement_count"] += 1

            if config.enabled and config.enforcement_mode != EnforcementMode.LOG_ONLY:
                status["enforcement_enabled_count"] += 1

        status["rollback_event_count"] = len(self.rollback_events)

        return status

    async def get_rollback_history(
        self,
        category: Optional[ActionCategory] = None,
        limit: int = 10
    ) -> List[EnforcementRollbackEvent]:
        """
        Get rollback history.

        Args:
            category: Optional category filter
            limit: Maximum number of events to return

        Returns:
            List of rollback events (most recent first)
        """
        events = self.rollback_events

        # Filter by category if specified
        if category:
            events = [e for e in events if e.category == category]

        # Sort by timestamp (most recent first)
        events = sorted(events, key=lambda e: e.timestamp, reverse=True)

        # Limit results
        return events[:limit]

    async def activate_production_enforcement(
        self,
        updated_by: str = "system_init"
    ) -> None:
        """
        Transition all categories out of LOG_ONLY shadow mode.

        Enforcement model:
          ALL categories → RECOMMEND_GOVERNANCE (evaluative baseline, rollout_stage=2)

          Nothing is unconditionally blocked by category. Every action goes through
          the full ASI 5-stage pipeline; the resulting risk_score and reasoning
          determine the outcome:
            - Low/moderate risk, solid reasoning  → allowed
            - High risk (score >= 0.6)            → recorded as an elevated-risk
              signal and executed with monitoring. It is NOT queued for
              approval: the governance-session model that would have judged it
              is retired, and describing a path that no longer exists is how a
              reviewer concludes a gate is present when nothing gates.
            - Governance integrity violation       → GovernanceBlockError (see below)

          MUST_BLOCK trigger override (category-level override is NOT used here):
            config_001 — "Safety Threshold Modification"
              Modifying safety thresholds would corrupt the ASI evaluation system
              itself, making all downstream evaluations unreliable. This is the
              only action unconditionally blocked without evaluation.

        Per-trigger MUST_BLOCK rules in governance_triggers.json (learning_001-005,
        mem_ops_001-007, resource_001-004, etc.) remain governed by the ASI pipeline
        and decision_tier (CRITICAL), not by category-level enforcement mode.
        """
        # Step 1: All categories → RECOMMEND_GOVERNANCE (evaluative, not auto-block)
        for category in ActionCategory:
            await self.enable_enforcement(
                category=category,
                mode=EnforcementMode.RECOMMEND_GOVERNANCE,
                updated_by=updated_by,
                rollout_stage=2,
            )

        # Step 2: Single MUST_BLOCK trigger override — safety threshold modification only.
        # Corrupting safety thresholds would make ASI evaluation untrustworthy,
        # so this cannot be permitted even with compelling reasoning.
        await self.set_trigger_override(
            category=ActionCategory.CONFIGURATION_CHANGES,
            trigger_id="config_001",
            mode=EnforcementMode.MUST_BLOCK,
            updated_by=updated_by,
        )

        logger.info(
            f"EnforcementModeManager: production enforcement activated by '{updated_by}'. "
            f"All categories=RECOMMEND_GOVERNANCE (evaluative). "
            f"MUST_BLOCK trigger override: config_001 (safety threshold modification)."
        )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_enforcement_manager: Optional[EnforcementModeManager] = None


def get_enforcement_mode_manager() -> EnforcementModeManager:
    """Get or create the global EnforcementModeManager singleton."""
    global _enforcement_manager
    if _enforcement_manager is None:
        _enforcement_manager = EnforcementModeManager()
    return _enforcement_manager
