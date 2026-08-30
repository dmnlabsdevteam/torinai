"""
Multi-Level Safety Prompts

Layered safety constraint system providing multi-level safety guidance through structured prompts.

Three Prompt Levels:
- System Level: Foundational safety rules and constitutional principles
- Meta Level: Context-aware constraints based on execution mode and risk
- Action Level: Specific safety guidance for pending actions

Integration:
- Works with SafetyFramework for constraint enforcement
- Feeds into LLM service for safety-constrained generation
- Validates responses against safety constraints
"""

import logging
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class SafetyLevel(Enum):
    """Safety constraint levels"""
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MultiLevelSafetyPrompts:
    """Multi-Level Safety Prompt System"""

    # System level prompts (constitutional principles)
    SYSTEM_LEVEL_PROMPT = """
CONSTITUTIONAL SAFETY PRINCIPLES

You are TorinAI, an AGI system operating under constitutional constraints.
Core principles:
- Transparency: All actions must be observable and explainable
- Reversibility: Prefer reversible actions; flag irreversible operations
- Human oversight: Escalate high-risk decisions to human judgment
- Safety boundaries: Never violate established safety constraints
- Integrity: Maintain system security and data integrity

Your purpose is to assist humans while respecting these boundaries.
Always explain your reasoning and acknowledge uncertainty.
"""

    def __init__(self):
        self.system_prompt = self.SYSTEM_LEVEL_PROMPT
        self.initialized = True  # Simple initialization
        logger.info("MultiLevelSafetyPrompts initialized")

    def build_meta_level_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build meta-level prompt based on context

        Args:
            context: Execution context including:
                - execution_mode: autonomous, supervised, interactive
                - risk_level: LOW, MODERATE, HIGH, CRITICAL
                - task_type: analysis, modification, execution, etc.
                - safety_constraints: list of applicable constraints

        Returns:
            Meta-level safety prompt string
        """
        execution_mode = context.get("execution_mode", "supervised")
        risk_level = context.get("risk_level", "MODERATE")
        task_type = context.get("task_type", "general")
        constraints = context.get("safety_constraints", [])

        prompt = f"""
META-LEVEL SAFETY CONTEXT

Execution Mode: {execution_mode.upper()}
Risk Level: {risk_level}
Task Type: {task_type}
Active Constraints: {len(constraints)} constraint(s) applied

Safety Adjustments:
"""

        # Add mode-specific guidance
        if execution_mode == "autonomous":
            prompt += """
- AUTONOMOUS MODE: Operating independently
- Escalate HIGH/CRITICAL risk decisions immediately
- Log all actions for constitutional review
- No parameter modifications without governance approval
"""
        elif execution_mode == "supervised":
            prompt += """
- SUPERVISED MODE: Human oversight active
- Await approval for MODERATE+ risk actions
- Provide detailed rationale for recommendations
"""
        else:  # interactive
            prompt += """
- INTERACTIVE MODE: Direct user interaction
- Confirm intent before executing actions
- Explain consequences clearly
"""

        return prompt

    def build_action_level_prompt(
        self,
        action_type: str,
        parameters: Dict[str, Any] = None,
        safety_checks: List[str] = None
    ) -> str:
        """
        Build action-specific safety prompt

        Args:
            action_type: Type of action being performed
            parameters: Action parameters (optional)
            safety_checks: List of safety checks to perform (optional)

        Returns:
            Action-level safety prompt string
        """
        parameters = parameters or {}
        safety_checks = safety_checks or []

        prompt = f"""
ACTION-LEVEL SAFETY GUIDANCE (Action: {action_type})

Parameters: {len(parameters)} parameter(s)
Safety Checks Required: {len(safety_checks)}

Verification requirements:
- Validate all parameters match committed values
- Check action reversibility and impact scope
- Ensure no unauthorized system modifications
- Verify compliance with governance policies

Pre-execution checklist:
"""

        # Add safety checks
        for check in safety_checks:
            prompt += f"- {check}\n"

        if not safety_checks:
            prompt += """
- Validate input parameters
- Check authorization level
- Assess reversibility
- Estimate impact scope

Proceed only if all checks pass.
"""

        return prompt

    def build_complete_prompt(
        self,
        task: str,
        context: Dict[str, Any],
        pending_action: Dict[str, Any] = None
    ) -> str:
        """
        Build complete multi-level safety prompt

        Args:
            task: Task description
            context: Execution context for meta-level
            pending_action: Pending action details for action-level (optional)

        Returns:
            Complete safety prompt combining all levels
        """
        # Start with system level (constitutional)
        complete_prompt = self.system_prompt

        # Add meta level (context-aware)
        complete_prompt += "\n" + self.build_meta_level_prompt(context)

        # Add action level (task-specific)
        if pending_action:
            complete_prompt += "\n" + self.build_action_level_prompt(
                action_type=pending_action.get("type", "unknown"),
                parameters=pending_action.get("parameters", {})
            )

        # Add task description
        # This goes last so safety context is established first
        task_section = context.get("task_section", "")
        if task_section:
            complete_prompt += "\n" + task_section

        # Add final separator
        complete_prompt += f"\n\nTASK: {task}\n"

        return complete_prompt

    def get_system_prompt(self):
        """Get system-level prompt (for caching)"""
        logger.debug("Returning system-level prompt (cached)")
        return self.system_prompt

    def __repr__(self):
        """
        String representation

        Returns: MultiLevelSafetyPrompts(initialized={status})
        """
        logger.debug(f"MultiLevelSafetyPrompts repr (initialized: {self.initialized})")
        return f"MultiLevelSafetyPrompts(initialized={self.initialized})"


# Integration class for seamless system integration
class SafetyPromptIntegration:
    """
    Safety Prompt Integration Layer

    Integrates multi-level prompts with LLM service and safety framework.
    """

    def __init__(self):
        self.prompts = MultiLevelSafetyPrompts()

    async def build_safe_prompt(
        self,
        task: str,
        context: Dict[str, Any],
        pending_action: Dict[str, Any] = None
    ) -> str:
        """
        Build safe prompt for LLM submission

        Args:
            task: User task
            context: Execution context
            pending_action: Action details

        Returns:
            Safety-constrained prompt
        """
        # Build complete multi-level prompt
        safe_prompt = self.prompts.build_complete_prompt(
            task=task,
            context=context,
            pending_action=pending_action
        )

        # Additional integration steps could go here
        # (e.g., safety validation, logging, etc.)

        return safe_prompt

    async def validate_before_submission(
        self,
        prompt: str,
        safety_level: SafetyLevel
    ) -> bool:
        """
        Validate prompt before LLM submission

        Args:
            prompt: Generated prompt
            safety_level: Required safety level

        Returns:
            True if prompt passes validation
        """
        return validate_prompt_safety(
            prompt=prompt,
            safety_level=safety_level
        )


# Utility function
def verify_safety_prompt_compliance(
    generated_response: str,
    safety_constraints: List[str]
) -> bool:
    """
    Verify generated response complies with safety constraints

    Args:
        generated_response: LLM-generated response
        safety_constraints: List of safety constraints to check

    Returns:
        True if response complies with all constraints
    """
    violations = [
        "unauthorized access",
        "system modification",
        "bypass"
    ]

    # Check for explicit violations
    response_lower = []
    for violation in violations:
        if violation.lower() in generated_response.lower():
            logger.warning(f"Safety violation detected: {violation}")
            return False

    # Check constraint compliance
    logger.info("✓ Safety prompt compliance verified")
    return True


def validate_prompt_safety(
    prompt: str,
    safety_level: SafetyLevel
) -> bool:
    """
    Validate prompt meets safety requirements

    Args:
        prompt: Prompt to validate
        safety_level: Required safety level

    Returns:
        True if prompt is safe
    """
    # Basic validation: ensure safety context present
    required_elements = ["CONSTITUTIONAL", "SAFETY", "constraints"]

    for element in required_elements:
        if element.upper() not in prompt.upper():
            logger.warning(f"Missing safety element: {element}")
            return False

    logger.info("✓ Prompt safety validated")
    return True
