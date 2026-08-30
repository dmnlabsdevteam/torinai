#!/usr/bin/env python3
"""
Slack Communication Tools
=========================
Context-aware tools for Torin to communicate with Dominion Labs team via Slack.

IMPORTANT: Only escalates internal operations to Slack, NOT external user interactions.
"""

import logging
from typing import Optional, Dict, Any, List

from core.integration.slack_notifier import get_slack_notifier, SlackChannel

logger = logging.getLogger(__name__)

# Team member mapping
TEAM_MEMBERS = {
    "stefan": {"name": "Stefan Ragland", "title": "Co-founder, CEO, Chairman, Head of R&D"},
    "abel": {"name": "Abel Gonzalez", "title": "Co-founder, CFO, Director"},
    "yunior": {"name": "Yunior Cordero", "title": "COO, Director"}
}


def should_escalate_to_slack(context: Dict[str, Any]) -> bool:
    """
    Determine if uncertainty should be escalated to Dominion Labs Slack.

    Only escalate when:
    - Working on internal TorinAI operations
    - Autonomous task execution
    - System maintenance/diagnostics

    Do NOT escalate when:
    - Chatting with external users
    - Handling customer support queries
    - Operating in AgentSO for client SOC operations
    """
    source_type = context.get("source_type", context.get("_source_type", "unknown"))
    agent_type = context.get("agent_type", "chat")
    user_type = context.get("user_type", "external")

    # NEVER escalate external user interactions
    if user_type == "external":
        logger.debug("Escalation blocked: external user interaction")
        return False

    # NEVER escalate AgentSO client operations (unless it's Dominion Labs testing)
    if agent_type == "agentso" and source_type != "dominion_labs":
        logger.debug("Escalation blocked: AgentSO client operation")
        return False

    # Only escalate internal operations
    internal_contexts = [
        "autonomous_coordinator",
        "system_maintenance",
        "singleton",
        "internal_task",
        "dominion_labs",
        "internal"
    ]

    is_internal = source_type in internal_contexts or user_type == "internal"

    if not is_internal:
        logger.debug(f"Escalation blocked: not internal context (source={source_type}, user={user_type})")

    return is_internal


async def send_slack_message(
    message: str,
    urgent: bool = False,
    channel: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send a message to Dominion Labs team via Slack (INTERNAL OPERATIONS ONLY).

    Args:
        message: The message to send
        urgent: Mark as urgent
        channel: Optional channel ("activity", "alerts", "decisions")
        context: Context dict to check if this should be escalated

    Returns:
        dict: {"success": bool, "message": str}
    """
    try:
        # Context check - only escalate internal operations
        if context and not should_escalate_to_slack(context):
            logger.info("Slack escalation blocked - external user interaction")
            return {
                "success": False,
                "message": "Escalation blocked: This is an external user interaction, not an internal operation"
            }

        slack = get_slack_notifier()

        channel_map = {
            "activity": SlackChannel.ACTIVITY,
            "alerts": SlackChannel.ALERTS,
            "decisions": SlackChannel.DECISIONS,
            "governance": SlackChannel.GOVERNANCE,
            "upgrades": SlackChannel.UPGRADES
        }

        slack_channel = channel_map.get(channel, SlackChannel.ACTIVITY) if channel else SlackChannel.ACTIVITY

        severity = "warning" if urgent else "info"
        title = "🚨 Torin Urgent Help Needed" if urgent else "🤖 Torin Needs Guidance"

        # force=True: this is a DELIBERATE tool send, not an automatic
        # notification. The event notifier is disabled globally, but the tool
        # the substrate invokes on purpose must still reach Slack.
        success = await slack.send_notification(
            message=message,
            title=title,
            channel=slack_channel,
            severity=severity,
            force=True,
        )

        if success:
            logger.info(f"Slack message sent (urgent={urgent}, internal operation)")
            return {"success": True, "message": "Message sent to Dominion Labs team"}
        else:
            logger.error("Failed to send Slack message")
            return {"success": False, "message": "Failed to send message to Slack"}

    except Exception as e:
        logger.error(f"Error sending Slack message: {e}", exc_info=True)
        return {"success": False, "message": f"Error: {str(e)}"}


async def ask_for_clarification(
    question: str,
    what_tried: Optional[List[str]] = None,
    task: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Ask Dominion Labs team for clarification (INTERNAL OPERATIONS ONLY).

    Only use this for internal TorinAI tasks, NOT external user conversations.

    Args:
        question: The question you need answered
        what_tried: List of things already tried
        task: What internal task you're working on
        context: Context dict

    Returns:
        dict: {"success": bool, "message": str}
    """
    try:
        # Context check
        if context and not should_escalate_to_slack(context):
            return {
                "success": False,
                "message": "Cannot escalate: This appears to be an external user interaction"
            }

        message = f"**Question:** {question}"

        if task:
            message = f"**Internal Task:** {task}\n\n{message}"

        if what_tried:
            message += "\n\n**What I've tried:**"
            for i, item in enumerate(what_tried, 1):
                message += f"\n{i}. {item}"

        return await send_slack_message(
            message=message,
            urgent=False,
            context=context or {"source_type": "internal"}
        )

    except Exception as e:
        logger.error(f"Error asking for clarification: {e}")
        return {"success": False, "message": f"Error: {str(e)}"}


async def report_security_finding(
    finding_type: str,
    description: str,
    severity: str = "MEDIUM",
    affected_user: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    notify_who: str = "stefan"
) -> Dict[str, Any]:
    """
    Report a security finding to leadership team.

    Use this for security concerns, especially those related to employees
    or internal systems.

    Args:
        finding_type: Type of finding
        description: Detailed description
        severity: LOW, MEDIUM, HIGH, or CRITICAL
        affected_user: Username/email of affected user
        evidence: Evidence/metadata
        notify_who: Who to notify ("stefan", "abel", or "both")

    Returns:
        dict: {"success": bool, "message": str}
    """
    try:
        slack = get_slack_notifier()

        message = f"**Finding Type:** {finding_type}\n"
        message += f"**Severity:** {severity}\n"

        if affected_user:
            message += f"**Affected User:** {affected_user}\n"

        message += f"\n**Description:**\n{description}\n"

        if evidence:
            message += "\n**Evidence:**\n"
            for key, value in evidence.items():
                message += f"• {key}: {value}\n"

        # Add notification routing
        if notify_who in ["stefan", "both"]:
            message += f"\n📧 **Notified:** {TEAM_MEMBERS['stefan']['name']} ({TEAM_MEMBERS['stefan']['title']})"
        if notify_who in ["abel", "both"]:
            message += f"\n📧 **Notified:** {TEAM_MEMBERS['abel']['name']} ({TEAM_MEMBERS['abel']['title']})"

        await slack.send_security_alert(
            alert_title=f"Security Finding: {finding_type}",
            alert_message=message,
            severity=severity,
            metadata={
                'finding_type': finding_type,
                'affected_user': affected_user,
                'notify_who': notify_who,
                'evidence': evidence or {}
            }
        )

        logger.info(f"Security finding reported: {finding_type} (severity: {severity})")

        return {"success": True, "message": f"Security finding reported to {notify_who}"}

    except Exception as e:
        logger.error(f"Error reporting security finding: {e}", exc_info=True)
        return {"success": False, "message": f"Error: {str(e)}"}


async def notify_team(
    notification: str,
    title: Optional[str] = None,
    importance: str = "normal",
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send a notification to the team (INTERNAL OPERATIONS ONLY).

    Args:
        notification: The notification message
        title: Optional title
        importance: "low", "normal", "high", or "critical"
        context: Context dict

    Returns:
        dict: {"success": bool, "message": str}
    """
    try:
        # Context check
        if context and not should_escalate_to_slack(context):
            return {
                "success": False,
                "message": "Cannot notify: This appears to be an external operation"
            }

        return await send_slack_message(
            message=notification,
            urgent=(importance in ["high", "critical"]),
            context=context or {"source_type": "internal"}
        )

    except Exception as e:
        logger.error(f"Error notifying team: {e}")
        return {"success": False, "message": f"Error: {str(e)}"}


# =============================================================================
# TOOL REGISTRY INTEGRATION
# =============================================================================
# Import Tool base classes for registry integration
try:
    from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
    from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel

    class AskForClarificationTool(Tool):
        """Ask Dominion Labs team for clarification on internal tasks"""

        def __init__(self):
            super().__init__()
            self.name = "ask_for_clarification"
            self.description = "Ask Dominion Labs team for clarification when stuck on INTERNAL TorinAI tasks (NOT for external user conversations)"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.MODERATE
            self.parameters = [
                ToolParameter(
                    name="question",
                    type="string",
                    description="The question you need answered",
                    required=True
                ),
                ToolParameter(
                    name="what_tried",
                    type="array",
                    description="List of things already tried",
                    required=False
                ),
                ToolParameter(
                    name="task",
                    type="string",
                    description="What internal task you're working on",
                    required=False
                ),
                ToolParameter(
                    name="context",
                    type="object",
                    description="Context dict (will be auto-filled by the system)",
                    required=False
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="ask_for_clarification",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.ASK_HUMAN,
                        description="AskForClarification capability"
                    ),
                    CapabilityMetadata(
                        capability=Capability.REQUEST_CLARIFICATION,
                        description="Request clarification from human operators",
                        input_types=["question", "context"],
                        output_types=["clarification_response"],
                        latency="high",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=9
                    ),
                    CapabilityMetadata(
                        capability=Capability.LEARN_FROM_HUMAN,
                        description="Learn from human feedback and guidance",
                        input_types=["question", "what_tried"],
                        output_types=["learned_knowledge"],
                        latency="high",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=8
                    ),
                    CapabilityMetadata(
                        capability=Capability.RECEIVE_FEEDBACK,
                        description="Receive feedback from human operators",
                        input_types=["question", "task"],
                        output_types=["feedback"],
                        latency="high",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=8
                    ),
                    CapabilityMetadata(
                        capability=Capability.REQUEST_EXPERTISE,
                        description="Request expert knowledge from human team",
                        input_types=["question", "context"],
                        output_types=["expert_guidance"],
                        latency="high",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=7
                    ),
                    CapabilityMetadata(
                        capability=Capability.REQUEST_OVERSIGHT,
                        description="Request human oversight for decisions requiring approval",
                        input_types=["question", "task"],
                        output_types=["oversight_response"],
                        latency="high",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.MEDIUM,
                        priority=9
                    )
                ]
            )

        async def execute(self, question: str, what_tried: Optional[List[str]] = None,
                         task: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> ToolResult:
            try:
                result = await ask_for_clarification(
                    question=question,
                    what_tried=what_tried,
                    task=task,
                    context=context
                )

                return ToolResult(
                    success=result["success"],
                    output=result,
                    error=None if result["success"] else result["message"]
                )
            except Exception as e:
                logger.error(f"Error in ask_for_clarification tool: {e}")
                return ToolResult(success=False, output=None, error=str(e))


    class ReportSecurityFindingTool(Tool):
        """Report security findings to leadership team"""

        def __init__(self):
            super().__init__()
            self.name = "report_security_finding"
            self.description = "Report security findings (especially employee-related) to Stefan or Abel"
            self.category = ToolCategory.SECURITY
            self.safety_level = ToolSafety.CRITICAL
            self.parameters = [
                ToolParameter(
                    name="finding_type",
                    type="string",
                    description="Type of security finding",
                    required=True
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Detailed description of the finding",
                    required=True
                ),
                ToolParameter(
                    name="severity",
                    type="string",
                    description="Severity level",
                    required=False,
                    default="MEDIUM",
                    enum=["LOW", "MEDIUM", "HIGH", "CRITICAL"]
                ),
                ToolParameter(
                    name="affected_user",
                    type="string",
                    description="Username/email of affected user",
                    required=False
                ),
                ToolParameter(
                    name="evidence",
                    type="object",
                    description="Evidence metadata",
                    required=False
                ),
                ToolParameter(
                    name="notify_who",
                    type="string",
                    description="Who to notify",
                    required=False,
                    default="stefan",
                    enum=["stefan", "abel", "both"]
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="report_security_finding",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.SEND_MESSAGE,
                        description="ReportSecurityFinding capability"
                    ),
                    CapabilityMetadata(
                        capability=Capability.REQUEST_OVERSIGHT,
                        description="Request human oversight for security decisions",
                        input_types=["context"],
                        output_types=["oversight_request"],
                        latency="high",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=9
                    )
                ]
            )

        async def execute(self, finding_type: str, description: str, severity: str = "MEDIUM",
                         affected_user: Optional[str] = None, evidence: Optional[Dict[str, Any]] = None,
                         notify_who: str = "stefan") -> ToolResult:
            try:
                result = await report_security_finding(
                    finding_type=finding_type,
                    description=description,
                    severity=severity,
                    affected_user=affected_user,
                    evidence=evidence,
                    notify_who=notify_who
                )

                return ToolResult(
                    success=result["success"],
                    output=result,
                    error=None if result["success"] else result["message"]
                )
            except Exception as e:
                logger.error(f"Error in report_security_finding tool: {e}")
                return ToolResult(success=False, output=None, error=str(e))


    class NotifyDominionLabsTeamTool(Tool):
        """Send notifications to Dominion Labs team about internal operations"""

        def __init__(self):
            super().__init__()
            self.name = "notify_dominion_labs_team"
            self.description = "Send notifications to Dominion Labs team about INTERNAL operations (NOT for external user interactions)"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.MODERATE
            self.parameters = [
                ToolParameter(
                    name="notification",
                    type="string",
                    description="The notification message",
                    required=True
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="Optional title",
                    required=False
                ),
                ToolParameter(
                    name="importance",
                    type="string",
                    description="Importance level",
                    required=False,
                    default="normal",
                    enum=["low", "normal", "high", "critical"]
                ),
                ToolParameter(
                    name="context",
                    type="object",
                    description="Context dict (will be auto-filled by the system)",
                    required=False
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="notify_dominion_labs_team",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.SEND_MESSAGE,
                        description="NotifyDominionLabsTeam capability"
                    ),
                    CapabilityMetadata(
                        capability=Capability.EXPLAIN_TO_HUMAN,
                        description="Explain system operations and findings to human team",
                        input_types=["notification", "context"],
                        output_types=["delivery_confirmation"],
                        latency="medium",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=8
                    ),
                    CapabilityMetadata(
                        capability=Capability.TEACH_CONCEPT,
                        description="Communicate conceptual information to team members",
                        input_types=["notification", "title"],
                        output_types=["delivery_confirmation"],
                        latency="medium",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=6
                    )
                ]
            )

        async def execute(self, notification: str, title: Optional[str] = None,
                         importance: str = "normal", context: Optional[Dict[str, Any]] = None) -> ToolResult:
            try:
                result = await notify_team(
                    notification=notification,
                    title=title,
                    importance=importance,
                    context=context
                )

                return ToolResult(
                    success=result["success"],
                    output=result,
                    error=None if result["success"] else result["message"]
                )
            except Exception as e:
                logger.error(f"Error in notify_dominion_labs_team tool: {e}")
                return ToolResult(success=False, output=None, error=str(e))

except ImportError:
    # Tool registry not available - this is OK, tools will just be callable as functions
    logger.info("Tool registry not available - slack_tools will work as functions only")


# Export functions
__all__ = [
    'send_slack_message',
    'ask_for_clarification',
    'report_security_finding',
    'notify_team',
    'should_escalate_to_slack',
    'TEAM_MEMBERS'
]
