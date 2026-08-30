"""
Governance Module

Unified governance trigger system for autonomous AI safety.

Main Components:
- UnifiedGovernanceTriggerSystem: Evaluates actions across 8 action categories
- ContextClassifier: Non-destructive context labeling for governance quality

Usage:
    from core.governance import UnifiedGovernanceTriggerSystem, ActionCategory

    trigger_system = UnifiedGovernanceTriggerSystem()

    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="execute_tool",
        parameters={"tool_name": "ChaosTestingTool", "target": "production"}
    )

    if evaluation.triggered:
        decision = await trigger_system.trigger_governance_session(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters=parameters,
            evaluation_result=evaluation,
            context=context
        )
"""

from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    ActionCategory,
    EnforcementMode,
    IrreversibilityClass,
    DecisionTier,
    GovernanceTriggerEvaluation,
    get_unified_governance,
    get_governance_system
)

from core.governance.context_classifier import (
    ContextClassifier,
    ContextLabel,
    ClassifiedContext,
    verify_no_data_loss
)

__all__ = [
    # Unified Governance Trigger System
    "UnifiedGovernanceTriggerSystem",
    "ActionCategory",
    "EnforcementMode",
    "IrreversibilityClass",
    "DecisionTier",
    "GovernanceTriggerEvaluation",

    # Singleton getters
    "get_unified_governance",
    "get_governance_system",

    # Context Classifier
    "ContextClassifier",
    "ContextLabel",
    "ClassifiedContext",
    "verify_no_data_loss",
]
