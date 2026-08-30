"""
Unified Governance Trigger System

Evaluates actions across all 8 action categories and determines if governance is required.
Implements tiered approval routing (ROUTINE/IMPORTANT/CRITICAL) and integrates with
context classification and commitment contracts.

Action Categories:
1. TOOL_EXECUTION
2. MEMORY_OPERATIONS
3. RESOURCE_ALLOCATION
4. LEARNING_PARAMETERS
5. CONFIGURATION_CHANGES
6. EXTERNAL_INTEGRATIONS
7. TASK_CREATION
8. CURIOSITY_EXPLORATION
"""

import json
import re
import logging
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ActionCategory(Enum):
    """8 action categories requiring governance evaluation"""
    TOOL_EXECUTION = "TOOL_EXECUTION"
    MEMORY_OPERATIONS = "MEMORY_OPERATIONS"
    RESOURCE_ALLOCATION = "RESOURCE_ALLOCATION"
    LEARNING_PARAMETERS = "LEARNING_PARAMETERS"
    CONFIGURATION_CHANGES = "CONFIGURATION_CHANGES"
    EXTERNAL_INTEGRATIONS = "EXTERNAL_INTEGRATIONS"
    TASK_CREATION = "TASK_CREATION"
    CURIOSITY_EXPLORATION = "CURIOSITY_EXPLORATION"


class EnforcementMode(Enum):
    """How to enforce governance triggers"""
    LOG_ONLY = "LOG_ONLY"  # Log but don't block (shadow mode)
    RECOMMEND_GOVERNANCE = "RECOMMEND_GOVERNANCE"  # Recommend governance but allow override
    MUST_BLOCK = "MUST_BLOCK"  # Block action until governance decision


#: What a matched rule MEANS, decided in one place.
#:
#: Safety here is not a bouncer -- the Singleton keeps full tool autonomy, and
#: the layer exists to produce deterministic signals about its own actions and
#: hand them back as context. So the question is not "is this dangerous"
#: (everything interesting is) but "could we still be wrong about it
#: afterwards". An action that can be undone is one the system can be wrong
#: about and recover from; an irreversible one is not, and that is the whole
#: boundary.
#:
#: THIS REPLACES THE `enforcement_mode` FIELD ON EACH TRIGGER. 44 of 56 rules
#: declared MUST_BLOCK there and NOTHING read it -- when the enforcement
#: manager was attached, the category-level mode replaced the rule's own
#: declaration outright. Two owners of "does this block", and the one that won
#: ignored what the rules said. Derived here, there is one.
#:
#: WIDENING IS ONE LINE. Adding MOSTLY_IRREVERSIBLE would additionally block
#: `sudo rm /etc/passwd`, `mv /etc /tmp`, `kill -9 1` and `shutdown` -- all
#: measured as MOSTLY_IRREVERSIBLE + CRITICAL today. They are currently scored
#: critical, recorded and monitored rather than denied.
BLOCKING_IRREVERSIBILITY = frozenset({"IRREVERSIBLE"})
BLOCKING_SAFETY_RISK = frozenset({"CRITICAL"})


#: Magnitude bands for a trigger that declares its risk VARIES. Read from the
#: same `risk_tiers` block the config already carries, rather than restated.
_MAGNITUDE_KEYS = ("percent_change", "magnitude_percent", "change_percent")


def resolve_risk(trigger: dict, parameters: dict) -> str:
    """A concrete safety_risk for a trigger that declares a variable one.

    `learning_001` and `learning_003` declare `safety_risk:
    "VARIES_BY_MAGNITUDE"` / `"VARIES_BY_PARAM"` and carry a `risk_tiers`
    block saying what varies with what. NOTHING READ IT -- grep for VARIES_BY
    across the package returned the config and no code -- so the literal string
    travelled all the way to the composition, where it matched no known risk
    and fell to a default. A model weight change declared IRREVERSIBLE could
    not block at any magnitude, and the tier table describing when it should
    was documentation.

    Returns the declared value unchanged where it is already concrete, so this
    is inert for the other fifty-four rules.
    """
    declared = str(trigger.get("safety_risk") or "")
    if not declared.startswith("VARIES_BY"):
        return declared

    # A parameter the trigger itself names as safety-critical outranks any
    # magnitude: a 1% change to `safety_threshold` is not a small change.
    critical_params = {str(p).lower()
                       for p in trigger.get("safety_critical_params", [])}
    named = str((parameters or {}).get("parameter_name") or "").lower()
    if named and named in critical_params:
        return "CRITICAL"

    magnitude = None
    for key in _MAGNITUDE_KEYS:
        value = (parameters or {}).get(key)
        if value is not None:
            try:
                magnitude = abs(float(value))
                break
            except (TypeError, ValueError):
                continue
    if magnitude is None:
        # Undeclared magnitude is not a small one. Guessing LOW here would make
        # "the caller forgot to say how big this is" indistinguishable from
        # "this is negligible", and only one of those is safe to allow.
        return "CRITICAL"

    if magnitude > 25:
        return "CRITICAL"
    if magnitude >= 10:
        return "HIGH"
    if magnitude >= 1:
        return "MEDIUM"
    return "LOW"


def blocking_mode(irreversibility: "IrreversibilityClass",
                  safety_risk: str) -> "EnforcementMode":
    """MUST_BLOCK where the action cannot be undone AND the risk is critical.

    Everything else is RECOMMEND_GOVERNANCE: scored, persisted to
    `safety_assessments`, executed with monitoring. A high score that changes
    nothing is still the signal this layer exists to produce.
    """
    if (irreversibility.value in BLOCKING_IRREVERSIBILITY
            and str(safety_risk).upper() in BLOCKING_SAFETY_RISK):
        return EnforcementMode.MUST_BLOCK
    return EnforcementMode.RECOMMEND_GOVERNANCE


class IrreversibilityClass(Enum):
    """Classification of action reversibility"""
    FULLY_REVERSIBLE = "FULLY_REVERSIBLE"  # Can be easily undone
    MOSTLY_REVERSIBLE = "MOSTLY_REVERSIBLE"  # Can be undone with some effort
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"  # Some effects are permanent
    MOSTLY_IRREVERSIBLE = "MOSTLY_IRREVERSIBLE"  # Very difficult to undo
    IRREVERSIBLE = "IRREVERSIBLE"  # Cannot be undone


class DecisionTier(Enum):
    """Tiered approval mechanism"""
    ROUTINE = "ROUTINE"  # Auto-approve with logging
    IMPORTANT = "IMPORTANT"  # Notification approval
    CRITICAL = "CRITICAL"  # Full governance session


@dataclass
class GovernanceTriggerEvaluation:
    """Result of evaluating an action against governance triggers"""
    action_id: str
    action_category: ActionCategory
    action_type: str
    triggered: bool
    trigger_id: Optional[str]
    trigger_name: Optional[str]
    escalation_category: Optional[str]
    irreversibility_class: IrreversibilityClass
    impact_level: str  # LOW, MEDIUM, HIGH
    safety_risk: str  # LOW, MODERATE, HIGH, CRITICAL
    enforcement_mode: EnforcementMode
    decision_tier: DecisionTier
    rationale: Optional[str]
    human_only_approval: bool
    approval_expiration_days: Optional[int]
    evaluated_at: datetime
    matched_conditions: Dict[str, Any]



class UnifiedGovernanceTriggerSystem:
    """
    Universal governance trigger evaluation system.

    Evaluates actions across all 8 action categories and determines:
    1. Should governance be triggered?
    2. What decision tier (ROUTINE/IMPORTANT/CRITICAL)?
    3. What enforcement mode (LOG_ONLY/RECOMMEND/MUST_BLOCK)?
    """

    def __init__(self, config_path: Optional[Path] = None, enforcement_manager=None):
        """
        Initialize governance trigger system.

        Args:
            config_path: Path to governance_triggers.json (defaults to config/governance_triggers.json)
            enforcement_manager: Optional EnforcementModeManager for enforcement mode overrides
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "governance_triggers.json"

        self.config_path = config_path
        self.internal_config = self._load_config()
        self.config = self.internal_config  # Backwards compatibility
        self.trigger_cache = self._build_trigger_cache()
        self.enforcement_manager = enforcement_manager

        logger.info(f"Initialized UnifiedGovernanceTriggerSystem with {len(self.trigger_cache)} triggers")

    def _load_config(self) -> Dict[str, Any]:
        """Load governance triggers configuration"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Loaded governance triggers config version {config.get('schema_version')}")
            return config
        except Exception as e:
            logger.error(f"Failed to load governance config: {e}")
            raise

    def _build_trigger_cache(self) -> Dict[ActionCategory, List[Dict[str, Any]]]:
        """Build fast lookup cache of triggers by action category"""
        cache = {}
        for category_name, category_data in self.config["action_categories"].items():
            try:
                category = ActionCategory[category_name]
                cache[category] = category_data["triggers"]
            except KeyError:
                logger.warning(f"Unknown action category: {category_name}")
        return cache

    async def evaluate_action(
        self,
        action_category: ActionCategory,
        action_type: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        source_type: str = "internal",
        external_governance_config: Optional[Dict[str, Any]] = None
    ) -> GovernanceTriggerEvaluation:
        """
        Universal action evaluation across all 8 action categories.

        Args:
            action_category: Which of the 8 action categories
            action_type: Specific action being attempted
            parameters: Action parameters
            context: Additional context (execution_mode, reasoning, etc.)
            source_type: "internal" for TorinAI operations, "external" for external systems like AgentSO
            external_governance_config: Custom governance config for external systems (if source_type="external")

        Returns:
            GovernanceTriggerEvaluation with decision tier and enforcement mode
        """
        context = context or {}
        action_id = context.get("action_id", f"action_{datetime.now().timestamp()}")

        # Store source_type in context for tier handlers to use
        context["_source_type"] = source_type

        # Determine which config to use
        if source_type == "external" and external_governance_config:
            active_config = external_governance_config
            # Build trigger cache for external config
            triggers = active_config.get("action_categories", {}).get(action_category.value, {}).get("triggers", [])
        else:
            active_config = self.internal_config
            triggers = self.trigger_cache.get(action_category, [])

        # Evaluate each trigger
        for trigger in triggers:
            if self._matches_trigger(action_type, parameters, trigger, context):
                # Trigger matched - extract decision parameters
                irreversibility = IrreversibilityClass[trigger["irreversibility_class"]]
                impact_level = trigger["impact_level"]
                safety_risk = resolve_risk(trigger, parameters)
                if impact_level.startswith("VARIES_BY"):
                    impact_level = safety_risk

                # WHAT THE RULE MEANS, THEN WHETHER ENFORCEMENT IS SWITCHED ON.
                # Those are two different questions and used to be answered by
                # one value, which is why the rules' own declarations were
                # silently discarded. The meaning is derived; the manager only
                # says whether this category is live and carries explicit
                # per-trigger overrides, which win outright.
                enforcement_mode = blocking_mode(irreversibility, safety_risk)

                # SELF-MODIFICATION IS NOT SCORED, IT IS REFUSED.
                #
                # `learning_003` and `learning_003b` match only when the source
                # IS the learner proposing a change to its own configuration,
                # and both declare `learner_self_approval_always_blocked: true`.
                # Nothing read that key -- zero readers package-wide -- so the
                # one rule stopping a component from rewriting the parameters
                # that govern it was a line of JSON.
                #
                # It cannot be derived from reversibility: a config change is
                # PARTIALLY_REVERSIBLE and would score as ordinary. What makes
                # it different is not the size of the effect but who is asking.
                if trigger.get("learner_self_approval_always_blocked"):
                    enforcement_mode = EnforcementMode.MUST_BLOCK

                if self.enforcement_manager:
                    override = self.enforcement_manager.trigger_override(
                        action_category, trigger["trigger_id"])
                    if override is not None:
                        enforcement_mode = override
                    elif self.enforcement_manager.in_shadow(action_category):
                        enforcement_mode = EnforcementMode.LOG_ONLY

                # Determine decision tier based on risk profile
                decision_tier = self._determine_decision_tier(
                    irreversibility,
                    impact_level,
                    safety_risk
                )

                return GovernanceTriggerEvaluation(
                    action_id=action_id,
                    action_category=action_category,
                    action_type=action_type,
                    triggered=True,
                    trigger_id=trigger["trigger_id"],
                    trigger_name=trigger["name"],
                    escalation_category=trigger["escalation_category"],
                    irreversibility_class=irreversibility,
                    impact_level=impact_level,
                    safety_risk=safety_risk,
                    enforcement_mode=enforcement_mode,
                    decision_tier=decision_tier,
                    rationale=trigger["rationale"],
                    human_only_approval=trigger.get("human_only_approval", False),
                    approval_expiration_days=trigger.get("approval_expiration_days"),
                    evaluated_at=datetime.now(),
                    matched_conditions=trigger["conditions"]
                )

        # No trigger matched - action does not require governance
        return GovernanceTriggerEvaluation(
            action_id=action_id,
            action_category=action_category,
            action_type=action_type,
            triggered=False,
            trigger_id=None,
            trigger_name=None,
            escalation_category=None,
            irreversibility_class=IrreversibilityClass.FULLY_REVERSIBLE,
            impact_level="LOW",
            safety_risk="LOW",
            enforcement_mode=EnforcementMode.LOG_ONLY,
            decision_tier=DecisionTier.ROUTINE,
            rationale="No governance triggers matched",
            human_only_approval=False,
            approval_expiration_days=None,
            evaluated_at=datetime.now(),
            matched_conditions={}
        )

    def _matches_trigger(
        self,
        action_type: str,
        parameters: Dict[str, Any],
        trigger: Dict[str, Any],
        context: Dict[str, Any]
    ) -> bool:
        """
        Check if action matches trigger conditions.

        Supports:
        - Exact matches
        - Regex patterns ({"matches": "pattern"})
        - Numeric comparisons ({">=": 7}, {">": 20})
        - List contains ({"contains_any": ["item1", "item2"]})
        - Negation ({"not_matches": "pattern"})
        """
        conditions = trigger["conditions"]

        # Check action_type match
        if "action_type" in conditions:
            if not self._matches_condition(action_type, conditions["action_type"]):
                return False

        # Check tool_name match (for TOOL_EXECUTION category)
        if "tool_name" in conditions:
            tool_name = parameters.get("tool_name")
            if not self._matches_condition(tool_name, conditions["tool_name"]):
                return False

        # Check source match (for learning system)
        if "source" in conditions:
            source = context.get("source")
            if not self._matches_condition(source, conditions["source"]):
                return False

        # Check parameter conditions
        if "parameters" in conditions:
            param_conditions = conditions["parameters"]
            for param_name, param_condition in param_conditions.items():
                param_value = parameters.get(param_name)

                if not self._matches_condition(param_value, param_condition):
                    return False

        return True

    def _matches_condition(self, value: Any, condition: Any) -> bool:
        """
        Flexible condition matching.

        Supports:
        - Exact match: condition = "value"
        - Regex: condition = {"matches": "pattern"}
        - Negation: condition = {"not_matches": "pattern"}
        - Numeric: condition = {">": 10}, {">=": 5}, etc.
        - Contains: condition = {"contains_any": ["item1", "item2"]}
        """
        # Exact match
        if isinstance(condition, (str, int, float, bool)):
            return value == condition

        # Dictionary-based conditions
        if isinstance(condition, dict):
            # Regex match
            if "matches" in condition:
                pattern = condition["matches"]
                if isinstance(value, str):
                    return bool(re.search(pattern, value, re.IGNORECASE))
                return False

            # Negation
            if "not_matches" in condition:
                pattern = condition["not_matches"]
                # AN ABSENT VALUE CANNOT SATISFY A NEGATION. You cannot assert
                # that a pattern is absent from something that does not exist.
                #
                # Returning True here made a missing parameter equivalent to a
                # parameter that passed, and the two rules in
                # CONFIGURATION_CHANGES are a matched pair over one key:
                # config_001 fires when `config_key` names a safety threshold,
                # config_002 when it does not. Omit `config_key` and the first
                # could not match while the second matched on nothing -- so a
                # safety threshold change scored LOW, through the one rule the
                # system designates as its unconditional block.
                #
                # The numeric comparisons below already refuse None for the
                # same reason.
                if value is None:
                    return False
                if isinstance(value, str):
                    return not bool(re.search(pattern, value, re.IGNORECASE))
                return True  # a non-string value genuinely contains no pattern

            # Numeric comparisons
            if ">" in condition:
                if value is None:
                    return False
                return value > condition[">"]
            if ">=" in condition:
                if value is None:
                    return False
                return value >= condition[">="]
            if "<" in condition:
                if value is None:
                    return False
                return value < condition["<"]
            if "<=" in condition:
                if value is None:
                    return False
                return value <= condition["<="]

            # Contains any
            if "contains_any" in condition:
                if isinstance(value, (list, tuple)):
                    return any(item in value for item in condition["contains_any"])
                if isinstance(value, str):
                    return any(item in value for item in condition["contains_any"])
                return False

        return False

    def _determine_decision_tier(
        self,
        irreversibility_class: IrreversibilityClass,
        impact_level: str,
        safety_risk: str
    ) -> DecisionTier:
        """
        Automatically assign decision tier based on action characteristics.

        CRITICAL tier: Irreversible or very high-impact actions
        IMPORTANT tier: Moderate risk, reversible but significant
        ROUTINE tier: Low risk, fully reversible
        """
        # CRITICAL tier: Irreversible or very high-impact actions
        if irreversibility_class == IrreversibilityClass.IRREVERSIBLE:
            return DecisionTier.CRITICAL

        if irreversibility_class == IrreversibilityClass.MOSTLY_IRREVERSIBLE and impact_level in ["HIGH", "CRITICAL"]:
            return DecisionTier.CRITICAL

        if safety_risk in ["CRITICAL", "HIGH"] and impact_level in ["HIGH", "CRITICAL"]:
            return DecisionTier.CRITICAL

        # IMPORTANT tier: Moderate risk, reversible but significant
        if irreversibility_class in [
            IrreversibilityClass.PARTIALLY_REVERSIBLE,
            IrreversibilityClass.MOSTLY_REVERSIBLE
        ]:
            if impact_level == "CRITICAL":
                return DecisionTier.CRITICAL  # CRITICAL impact always escalates
            if impact_level in ["MEDIUM", "HIGH"]:
                return DecisionTier.IMPORTANT

        if safety_risk == "MODERATE" and impact_level == "MEDIUM":
            return DecisionTier.IMPORTANT

        # ROUTINE tier: Low risk, fully reversible
        if irreversibility_class == IrreversibilityClass.FULLY_REVERSIBLE and impact_level == "LOW":
            return DecisionTier.ROUTINE

        # Default to IMPORTANT for safety
        return DecisionTier.IMPORTANT


    async def escalate_security_event(
        self,
        event_type: str,
        findings: List[Any]
    ):
        """
        Escalate security event to governance system

        Args:
            event_type: Type of security event (e.g., "critical_findings")
            findings: List of security findings to escalate
        """
        try:
            logger.info(f"Escalating security event to governance: {event_type} ({len(findings)} findings)")

            # Build security event context
            finding_details = []
            for finding in findings:
                finding_details.append({
                    'id': getattr(finding, 'finding_id', 'unknown'),
                    'title': getattr(finding, 'title', 'Unknown Finding'),
                    'severity': str(getattr(finding, 'severity', 'UNKNOWN')),
                    'category': str(getattr(finding, 'category', 'UNKNOWN')),
                    'description': getattr(finding, 'description', ''),
                })

            # Evaluate as security configuration change
            evaluation = await self.evaluate_action(
                action_category=ActionCategory.CONFIGURATION_CHANGES,
                action_type="security_event_escalation",
                parameters={
                    'event_type': event_type,
                    'finding_count': len(findings),
                    'findings': finding_details
                },
                context={
                    'component': 'security_audit',
                    'requires_review': True
                }
            )

            # `evaluation.approved` does not exist on GovernanceTriggerEvaluation —
            # reading it raised AttributeError here, which the outer except
            # swallowed, making every security escalation a silent no-op.
            logger.info(
                f"Security event escalation evaluated: "
                f"tier={evaluation.decision_tier.value} triggered={evaluation.triggered} "
                f"trigger={evaluation.trigger_name or evaluation.trigger_id or 'none'}"
            )

            # If critical tier, notify via Slack
            if evaluation.decision_tier == DecisionTier.CRITICAL and hasattr(self, 'slack_notifier') and self.slack_notifier:
                try:
                    await self.slack_notifier.send_security_alert(
                        alert_title=f"Governance: {event_type}",
                        alert_message=f"Security event escalated to governance: {len(findings)} findings require review",
                        severity="HIGH",
                        metadata={
                            'event_type': event_type,
                            'findings_count': len(findings),
                            'governance_tier': evaluation.decision_tier.value
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to send governance escalation notification: {e}")

        except Exception as e:
            logger.error(f"Security event escalation failed: {e}")


# Singleton instance (global variable)
_unified_governance_instance: Optional[UnifiedGovernanceTriggerSystem] = None


def get_unified_governance() -> UnifiedGovernanceTriggerSystem:
    """
    Get singleton instance of unified governance trigger system.

    This ensures ONE governance instance across the entire system, providing:
    - Consistent enforcement modes
    - Shared shadow mode learning
    - Coordinated approval state
    - Unified metrics and audit trail

    Returns:
        The singleton UnifiedGovernanceTriggerSystem instance
    """
    global _unified_governance_instance
    if _unified_governance_instance is None:
        # ATTACH ENFORCEMENT AT THE ONE CONSTRUCTION POINT.
        #
        # The system takes an enforcement_manager (see __init__) and consults it
        # in evaluate_action to resolve the effective enforcement mode for a
        # category. Constructing it with the default None meant that lookup was
        # skipped on every evaluation: triggers matched and classified, and
        # nothing enforced the result -- while this factory's own docstring
        # promised "Consistent enforcement modes".
        #
        # It belongs here rather than in a caller because this is the singleton
        # everything resolves through; attaching it anywhere else would leave
        # whichever caller ran first deciding whether governance enforces.
        #
        # Imported inside the function: enforcement_mode_manager imports the
        # ActionCategory/EnforcementMode enums from this module, so a top-level
        # import would be circular.
        from core.governance.enforcement_mode_manager import get_enforcement_mode_manager

        _unified_governance_instance = UnifiedGovernanceTriggerSystem(
            enforcement_manager=get_enforcement_mode_manager()
        )
        logger.info("✅ Created singleton UnifiedGovernanceTriggerSystem instance "
                    "with enforcement manager attached")
    return _unified_governance_instance


def get_governance_system() -> UnifiedGovernanceTriggerSystem:
    """
    Alias for get_unified_governance() for backward compatibility.

    Returns:
        The singleton UnifiedGovernanceTriggerSystem instance
    """
    return get_unified_governance()
