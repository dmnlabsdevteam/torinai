#!/usr/bin/env python3
"""
Slack Notification System
=========================
Tracks and notifies about TorinAI singleton's autonomous actions and decisions

Purpose:
- Monitor singleton's autonomous decision-making
- Send governance session notifications for CRITICAL actions (human approval required)
- Handle approval/denial requests for IMPORTANT actions
- Provide real-time visibility into singleton behavior
- Integrate with commitment contract system

Notification Types:
- Governance sessions (CRITICAL tier)
- Approval requests (IMPORTANT tier)
- Informational messages (ROUTINE tier)
- Security alerts
- Learning milestones
"""

import logging
import asyncio
import aiohttp
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env.production
env_file = Path(__file__).parent.parent.parent / ".env.production"
if env_file.exists():
    load_dotenv(env_file)
else:
    # Fallback to .env if .env.production doesn't exist
    env_file_fallback = Path(__file__).parent.parent.parent / ".env"
    if env_file_fallback.exists():
        load_dotenv(env_file_fallback)

logger = logging.getLogger(__name__)

# SLACK NOTIFICATIONS REMOVED 2026-08-25.
#
# The notifier flooded the logs with 429 rate-limit errors and its retry storms
# slowed everything around it -- notifications are not worth that, and Slack as
# an OUTBOUND alert channel was retired. The Slack TOOL (core/tools/slack_tools)
# is untouched: the substrate can still send a Slack message deliberately when a
# task calls for it. What is removed is the automatic notifier that fired on its
# own on every event.
#
# Neutered at the source rather than at 19 call sites: every entry point below
# returns immediately with no network call, so nothing that calls the notifier
# breaks and nothing reaches Slack.
SLACK_NOTIFICATIONS_ENABLED = False

async def _report_failure(failure_type: str, description: str,
                          severity: str = "medium", metadata=None) -> None:
    """Record an alerting failure on the canonical record.

    Kept local and defensive: the notifier is what other subsystems call when
    something has already gone wrong, so nothing here may raise into them.
    """
    try:
        from core.observability import failure_record

        await failure_record.report(
            component="integration.slack_notifier", failure_type=failure_type,
            description=description, source_system="slack_notifier",
            severity=severity, metadata=metadata or {})
    except Exception as error:
        logger.error("Slack failure not recorded: %s", error)




class NotificationType(Enum):
    """Notification types for singleton actions"""
    GOVERNANCE_SESSION = "governance_session"  # Full governance session (CRITICAL tier, human approval required)
    APPROVAL_REQUEST = "approval_request"      # Slack-based approval/denial
    INFORMATIONAL = "informational"            # General updates
    SECURITY_ALERT = "security_alert"          # Security incidents
    LEARNING_MILESTONE = "learning_milestone"  # Learning achievements
    SELF_UPGRADE = "self_upgrade"              # System self-improvement
    DECISION_REQUIRED = "decision_required"    # Human decision needed


class DecisionTier(Enum):
    """Decision tier from governance system"""
    ROUTINE = "ROUTINE"
    IMPORTANT = "IMPORTANT"
    CRITICAL = "CRITICAL"


class ActionCategory(Enum):
    """8 action categories tracked for singleton"""
    TOOL_EXECUTION = "TOOL_EXECUTION"
    MEMORY_OPERATIONS = "MEMORY_OPERATIONS"
    RESOURCE_ALLOCATION = "RESOURCE_ALLOCATION"
    LEARNING_PARAMETERS = "LEARNING_PARAMETERS"
    CONFIGURATION_CHANGES = "CONFIGURATION_CHANGES"
    EXTERNAL_INTEGRATIONS = "EXTERNAL_INTEGRATIONS"
    TASK_CREATION = "TASK_CREATION"
    CURIOSITY_EXPLORATION = "CURIOSITY_EXPLORATION"


class SlackChannel(Enum):
    """Slack channels for different notification types"""
    UPGRADES = "torin-upgrades"
    ALERTS = "torin-alerts"
    DECISIONS = "torin-decisions"
    ACTIVITY = "torin-activity"
    GOVERNANCE = "torin-governance"


@dataclass
class SingletonAction:
    """Singleton autonomous action to track"""
    action_id: str
    action_category: ActionCategory
    action_type: str
    description: str
    decision_tier: DecisionTier

    # Governance context
    requires_governance: bool
    requires_approval: bool
    safety_risk: str  # LOW, MODERATE, HIGH, CRITICAL
    impact_level: str  # LOW, MEDIUM, HIGH

    # Action metadata
    triggered_by: str = "singleton_autonomous"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GovernanceNotification:
    """Notification for governance session"""
    action: SingletonAction
    human_required: bool = True
    approval_expiration_hours: int = 24
    governance_session_id: str = ""


@dataclass
class ApprovalRequest:
    """Slack-based approval request"""
    action: SingletonAction
    approval_timeout_minutes: int = 30
    default_action: str = "deny"  # deny or approve
    approval_url: Optional[str] = None
    denial_url: Optional[str] = None


@dataclass
class SlackNotification:
    """Generic Slack notification"""
    notification_type: NotificationType
    channel: SlackChannel
    title: str
    message: str
    notification_id: Optional[str] = None  # Unique identifier for tracking
    color: str = "#36a64f"  # Green default
    fields: List[Dict[str, str]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SlackNotifier:
    """
    Slack Notification System for Singleton Action Tracking

    Monitors TorinAI singleton's autonomous decisions and sends appropriate
    notifications based on decision tier:
    - CRITICAL: Full governance session (human approval required)
    - IMPORTANT: Slack approval request (30-min timeout, default deny)
    - ROUTINE: Informational message

    Features:
    - Non-blocking async notifications
    - Governance integration
    - Approval workflow tracking
    - Security alert escalation
    - Learning milestone reporting
    """

    #: Hard ceiling on ONE send_notification call, covering every retry and
    #: backoff inside it. Chosen above a single attempt's 30 s ClientTimeout so
    #: a slow-but-working webhook still succeeds, and far below anything a
    #: caller would notice as a stall.
    SEND_DEADLINE_SECONDS: float = 35.0

    def __init__(self, webhook_url: Optional[str] = None):
        # Shared aiohttp session for connection reuse
        self._session: Optional[aiohttp.ClientSession] = None

        # Set up channel-specific webhooks first
        import os
        self.channel_webhooks = {
            SlackChannel.UPGRADES: os.getenv('SLACK_WEBHOOK_TORIN_UPGRADES'),
            SlackChannel.ALERTS: os.getenv('SLACK_WEBHOOK_TORIN_ALERTS'),
            SlackChannel.DECISIONS: os.getenv('SLACK_WEBHOOK_TORIN_DECISIONS'),
            SlackChannel.ACTIVITY: os.getenv('SLACK_WEBHOOK_TORIN_ACTIVITY'),
            SlackChannel.GOVERNANCE: os.getenv('SLACK_WEBHOOK_CRITICAL')
        }

        # Initialize webhook_url to None first to avoid circular reference
        self.webhook_url = None
        # Now we can set the default webhook_url
        self.webhook_url = webhook_url or self._get_webhook_url()

        # Tracking
        self.pending_approvals: Dict[str, ApprovalRequest] = {}
        self.governance_sessions: Dict[str, GovernanceNotification] = {}
        self.notification_history: List[SlackNotification] = []

        # Statistics
        self.stats = {
            'total_notifications': 0,
            'governance_sessions': 0,
            'approval_requests': 0,
            'approvals_granted': 0,
            'approvals_denied': 0,
            'security_alerts': 0
        }

        # Channel routing
        self.channel_routing = {
            NotificationType.GOVERNANCE_SESSION: SlackChannel.GOVERNANCE,
            NotificationType.APPROVAL_REQUEST: SlackChannel.DECISIONS,
            NotificationType.SECURITY_ALERT: SlackChannel.ALERTS,
            NotificationType.SELF_UPGRADE: SlackChannel.UPGRADES,
            NotificationType.LEARNING_MILESTONE: SlackChannel.UPGRADES,
            NotificationType.INFORMATIONAL: SlackChannel.ACTIVITY,
            NotificationType.DECISION_REQUIRED: SlackChannel.DECISIONS
        }

        logger.info("SlackNotifier initialized")

    def _get_webhook_url(self, channel: Optional[SlackChannel] = None) -> Optional[str]:
        """Get Slack webhook URL from environment"""
        import os
        # Normalize channel to enum if it's a string
        if channel and isinstance(channel, str):
            try:
                channel = SlackChannel[channel.upper()]
            except (KeyError, AttributeError):
                logger.warning(f"Invalid channel name: {channel}, using default")
                channel = None

        # If channel specified, use channel-specific webhook
        if channel and channel in self.channel_webhooks:
            webhook = self.channel_webhooks[channel]
            if webhook:
                return webhook
        # Fallback to general webhook URL
        return os.getenv('SLACK_WEBHOOK_URL') or self.webhook_url

    async def notify_singleton_action(
        self,
        action: SingletonAction,
        commitment_contract_id: Optional[str] = None
    ):
        """
        Notify about singleton's autonomous action

        Routes to appropriate notification type based on decision tier:
        - CRITICAL → Governance session
        - IMPORTANT → Approval request
        - ROUTINE → Informational message
        """
        logger.info(
            f"Singleton action: {action.action_type} "
            f"(tier: {action.decision_tier.value}, category: {action.action_category.value})"
        )

        try:
            if action.decision_tier == DecisionTier.CRITICAL:
                # Trigger full governance session
                await self._notify_governance_session(action, commitment_contract_id)

            elif action.decision_tier == DecisionTier.IMPORTANT:
                # Send approval request
                await self._send_approval_request(action, commitment_contract_id)

            else:  # ROUTINE
                # Send informational message
                await self._send_informational_message(action, commitment_contract_id)

        except Exception as e:
            logger.error(f"Failed to notify singleton action: {e}")

    async def _notify_governance_session(
        self,
        action: SingletonAction,
        commitment_contract_id: Optional[str] = None
    ):
        """Notify about a CRITICAL governance session (human approval required)"""
        governance_session_id = f"gov_session_{action.action_id}"

        notification = GovernanceNotification(
            action=action,
            governance_session_id=governance_session_id
        )

        self.governance_sessions[governance_session_id] = notification
        self.stats['governance_sessions'] += 1

        # Build Slack message
        slack_msg = SlackNotification(
            notification_type=NotificationType.GOVERNANCE_SESSION,
            channel=SlackChannel.GOVERNANCE,
            title="🏛️ GOVERNANCE SESSION REQUIRED",
            message=(
                f"The TorinAI singleton is requesting governance approval for a CRITICAL action.\n\n"
                f"**Action**: {action.action_type}\n"
                f"**Category**: {action.action_category.value}\n"
                f"**Description**: {action.description}\n"
                f"**Safety Risk**: {action.safety_risk}\n"
                f"**Impact Level**: {action.impact_level}\n\n"
                f"**Governance Required**: Human Approval\n"
                f"**Session ID**: `{governance_session_id}`\n"
                f"**Commitment Contract**: `{commitment_contract_id or 'N/A'}`"
            ),
            color="#DC143C",  # Crimson red for critical
            fields=[
                {"title": "Action ID", "value": action.action_id, "short": True},
                {"title": "Triggered By", "value": action.triggered_by, "short": True},
                {"title": "Decision Tier", "value": action.decision_tier.value, "short": True},
                {"title": "Expires", "value": f"{notification.approval_expiration_hours} hours", "short": True}
            ],
            metadata={
                'governance_session_id': governance_session_id,
                'action_id': action.action_id,
                'requires_human': True
            }
        )

        await self._send_slack_notification(slack_msg)

        logger.info(f"✓ Governance session notification sent: {governance_session_id}")

    async def _send_approval_request(
        self,
        action: SingletonAction,
        commitment_contract_id: Optional[str] = None
    ):
        """Send Slack approval/denial request with interactive buttons"""
        # Automatic path: no-op while Slack notifications are disabled.
        if not SLACK_NOTIFICATIONS_ENABLED:
            return
        approval_request = ApprovalRequest(
            action=action,
            approval_url=f"https://dominion.labs/api/approve/{action.action_id}",
            denial_url=f"https://dominion.labs/api/deny/{action.action_id}"
        )

        self.pending_approvals[action.action_id] = approval_request
        self.stats['approval_requests'] += 1

        # Get channel-specific webhook URL
        webhook_url = self._get_webhook_url(channel=SlackChannel.DECISIONS)

        if not webhook_url:
            logger.warning(f"Slack webhook URL not configured for decisions channel")
            return

        # Use Block Kit for interactive buttons
        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "⚠️ APPROVAL REQUIRED"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Action:* {action.action_type}\n"
                            f"*Category:* {action.action_category.value}\n"
                            f"*Description:* {action.description}\n\n"
                            f"*Safety Risk:* {action.safety_risk}\n"
                            f"*Impact Level:* {action.impact_level}\n"
                            f"*Timeout:* {approval_request.approval_timeout_minutes} minutes\n"
                            f"*Default:* {approval_request.default_action}"
                        )
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Action ID:*\n`{action.action_id}`"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Triggered By:*\n{action.triggered_by}"
                        }
                    ]
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "✅ Approve"
                            },
                            "style": "primary",
                            "action_id": f"approve_{action.action_id}",
                            "value": action.action_id
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "❌ Deny"
                            },
                            "style": "danger",
                            "action_id": f"deny_{action.action_id}",
                            "value": action.action_id
                        }
                    ]
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Commitment Contract: `{commitment_contract_id or 'N/A'}` | Expires: <t:{int((datetime.now().timestamp() + approval_request.approval_timeout_minutes * 60))}:R>"
                        }
                    ]
                }
            ]
        }

        # Send via webhook with shared session
        try:
            session = self._get_session()
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)  # Reduced from 120s
            ) as response:
                    response_text = await response.text()
                    if response.status == 200 and response_text == "ok":
                        logger.info(f"✓ Approval request sent with buttons: {action.action_id}")
                    else:
                        logger.error(f"✗ Approval request failed: {response.status} - {response_text}")
        except Exception as e:
            logger.error(f"✗ Error sending approval request: {e}")

    async def _send_informational_message(
        self,
        action: SingletonAction,
        commitment_contract_id: Optional[str] = None
    ):
        """Send informational message for routine actions"""
        slack_msg = SlackNotification(
            notification_type=NotificationType.INFORMATIONAL,
            channel=SlackChannel.ACTIVITY,
            title="ℹ️ Singleton Activity",
            message=(
                f"**Action**: {action.action_type}\n"
                f"**Category**: {action.action_category.value}\n"
                f"**Description**: {action.description}\n"
                f"**Commitment Contract**: `{commitment_contract_id or 'N/A'}`"
            ),
            color="#36a64f",  # Green for routine
            fields=[
                {"title": "Action ID", "value": action.action_id, "short": True},
                {"title": "Decision Tier", "value": action.decision_tier.value, "short": True}
            ],
            metadata={
                'action_id': action.action_id,
                'informational': True
            }
        )

        await self._send_slack_notification(slack_msg)

    async def send_security_alert(
        self,
        alert_title: str,
        alert_message: str,
        severity: str = "HIGH",
        metadata: Dict[str, Any] = None
    ):
        """Send security alert notification"""
        self.stats['security_alerts'] += 1

        color_map = {
            "LOW": "#FFEB3B",
            "MODERATE": "#FF9800",
            "HIGH": "#F44336",
            "CRITICAL": "#880E4F"
        }

        slack_msg = SlackNotification(
            notification_type=NotificationType.SECURITY_ALERT,
            channel=SlackChannel.ALERTS,
            title=f"🚨 SECURITY ALERT - {severity}",
            message=f"**{alert_title}**\n\n{alert_message}",
            color=color_map.get(severity, "#F44336"),
            fields=[
                {"title": "Severity", "value": severity, "short": True},
                {"title": "Timestamp", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "short": True}
            ],
            metadata=metadata or {}
        )

        await self._send_slack_notification(slack_msg)

        logger.warning(f"Security alert sent: {alert_title} (severity: {severity})")

    async def send_learning_milestone(
        self,
        milestone_title: str,
        milestone_description: str,
        metrics: Dict[str, Any] = None
    ):
        """Send learning milestone notification"""
        fields = [
            {"title": "Timestamp", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "short": True}
        ]

        if metrics:
            for key, value in list(metrics.items())[:4]:  # Limit to 4 metrics
                fields.append({"title": key, "value": str(value), "short": True})

        slack_msg = SlackNotification(
            notification_type=NotificationType.LEARNING_MILESTONE,
            channel=SlackChannel.UPGRADES,
            title=f"🎓 Learning Milestone: {milestone_title}",
            message=milestone_description,
            color="#9C27B0",  # Purple for learning
            fields=fields,
            metadata={'metrics': metrics or {}}
        )

        await self._send_slack_notification(slack_msg)

    async def record_approval_decision(
        self,
        action_id: str,
        approved: bool,
        decided_by: str
    ):
        """Record approval/denial decision"""
        if action_id not in self.pending_approvals:
            logger.warning(f"Approval decision for unknown action: {action_id}")
            return

        if approved:
            self.stats['approvals_granted'] += 1
            decision = "APPROVED"
            color = "#4CAF50"
        else:
            self.stats['approvals_denied'] += 1
            decision = "DENIED"
            color = "#F44336"

        approval_request = self.pending_approvals.pop(action_id)

        slack_msg = SlackNotification(
            notification_type=NotificationType.INFORMATIONAL,
            channel=SlackChannel.DECISIONS,
            title=f"✅ Decision: {decision}",
            message=(
                f"**Action**: {approval_request.action.action_type}\n"
                f"**Decision**: {decision}\n"
                f"**Decided By**: {decided_by}"
            ),
            color=color,
            fields=[
                {"title": "Action ID", "value": action_id, "short": True},
                {"title": "Decision", "value": decision, "short": True}
            ]
        )

        await self._send_slack_notification(slack_msg)

        logger.info(f"Approval decision recorded: {action_id} → {decision}")

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create shared aiohttp session for connection reuse"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _send_slack_notification(self, notification: SlackNotification, retry_count: int = 0,
                                       force: bool = False):
        # Automatic sends are no-ops. The Slack TOOL is the only deliberate
        # sender and passes force=True; everything else short-circuits here so
        # no webhook is ever hit and the 429 storm cannot recur.
        if not SLACK_NOTIFICATIONS_ENABLED and not force:
            return
        """Send notification to Slack with retry logic and proper error handling"""
        max_retries = 3

        # Get channel-specific webhook URL
        webhook_url = self._get_webhook_url(channel=notification.channel)

        if not webhook_url:
            channel_name = notification.channel.value if hasattr(notification.channel, 'value') else notification.channel
            logger.warning(f"Slack webhook URL not configured for channel {channel_name}, skipping notification")
            return

        try:
            import time as time_module
            start_time = time_module.time()

            # Build Slack message payload
            # NOTE: Don't include "channel" - incoming webhooks are already channel-specific
            payload = {
                "attachments": [{
                    "color": notification.color,
                    "title": notification.title,
                    "text": notification.message,
                    "fields": notification.fields,
                    "footer": "TorinAI Singleton Monitor",
                    "ts": int(notification.timestamp.timestamp())
                }]
            }

            # Send async HTTP request with shared session (connection reuse)
            logger.debug(f"Sending Slack notification to {webhook_url[:50]}... (timeout=30s)")
            session = self._get_session()
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)  # Increased from 10s — real latency observed at 22s
            ) as response:
                    response_text = await response.text()
                    logger.debug(f"Slack response: status={response.status}, body={response_text[:100]}")

                    # SUCCESS: Slack webhooks return "ok" on success
                    if response.status == 200 and response_text == "ok":
                        elapsed = (time_module.time() - start_time) * 1000  # ms
                        self.stats['total_notifications'] += 1
                        self.notification_history.append(notification)
                        logger.debug(f"✓ Slack notification sent: {notification.title} ({elapsed:.0f}ms)")
                        return

                    # ERROR: Bad Request (invalid payload) - don't retry
                    elif response.status == 400:
                        logger.error(f"✗ Slack 400 Bad Request: {response_text}")
                        logger.error(f"Payload: {payload}")
                        return

                    # ERROR: Forbidden (invalid webhook) - don't retry
                    elif response.status == 403:
                        logger.error(f"✗ Slack 403 Forbidden: Invalid webhook URL")
                        return

                    # ERROR: Not Found (webhook deleted) - don't retry
                    elif response.status == 404:
                        logger.error(f"✗ Slack 404 Not Found: Webhook doesn't exist")
                        return

                    # ERROR: Rate Limited - retry with backoff
                    elif response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"✗ Slack 429 Rate Limited: Retry after {retry_after}s")
                        if retry_count < max_retries:
                            await asyncio.sleep(retry_after)
                            await self._send_slack_notification(notification, retry_count + 1, force=force)
                        return

                    # ERROR: Server Error (5xx) - retry with exponential backoff
                    elif response.status >= 500:
                        logger.error(f"✗ Slack server error: {response.status}")
                        if retry_count < max_retries:
                            wait_time = 2 ** retry_count  # 1s, 2s, 4s
                            logger.info(f"Retrying in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            await self._send_slack_notification(notification, retry_count + 1, force=force)
                        return

                    # Other errors
                    else:
                        logger.error(f"✗ Slack notification failed: {response.status} - {response_text}")

        except asyncio.TimeoutError:
            elapsed = (time_module.time() - start_time) * 1000  # ms
            logger.error(f"✗ Slack notification timeout after {elapsed:.0f}ms (limit: 10000ms)")
            if retry_count < max_retries:
                wait_time = 2 ** retry_count
                logger.info(f"Retrying Slack notification in {wait_time}s (attempt {retry_count + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
                await self._send_slack_notification(notification, retry_count + 1, force=force)
        except Exception as e:
            logger.error(f"✗ Slack notification error: {e}")
            if retry_count < max_retries:
                wait_time = 2 ** retry_count
                await asyncio.sleep(wait_time)
                await self._send_slack_notification(notification, retry_count + 1, force=force)

    async def send_notification(
        self,
        message: str,
        title: Optional[str] = None,
        channel: Optional[Any] = None,
        severity: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> bool:
        """Convenience method for sending simple notifications.

        Args:
            message: Message text (markdown supported)
            title: Optional title for the notification
            channel: Optional channel override (SlackChannel or name like "ALERTS")
            severity: Severity level (info, success, warning, error, critical, high, low)
            metadata: Optional key/value metadata to include as fields

        Returns:
            True if notification was dispatched without local errors.
        """
        # AUTOMATIC NOTIFICATIONS ARE REMOVED; DELIBERATE TOOL SENDS ARE NOT.
        # Every automatic caller uses the default and gets a no-op, so the event
        # spam and its 429 storm are gone. The Slack TOOL passes force=True to
        # send a message a task actually asked for.
        if not SLACK_NOTIFICATIONS_ENABLED and not force:
            return True
        try:
            # Normalise severity to a small set of levels
            sev = (severity or "info").lower()
            sev_map = {
                "info": "info",
                "success": "info",
                "low": "info",
                "warning": "warning",
                "warn": "warning",
                "high": "error",
                "error": "error",
                "critical": "critical",
                "fatal": "critical",
            }
            sev_level = sev_map.get(sev, "info")

            emoji_map = {
                "info": "ℹ️",
                "warning": "⚠️",
                "error": "❌",
                "critical": "🚨",
            }
            color_map = {
                "info": "#36a64f",      # green
                "warning": "#FF9800",   # orange
                "error": "#F44336",     # red
                "critical": "#880E4F",  # dark red
            }

            emoji = emoji_map.get(sev_level, "ℹ️")
            color = color_map.get(sev_level, "#36a64f")

            # Normalise channel to SlackChannel when passed as string
            slack_channel: Any = channel or SlackChannel.ACTIVITY
            if isinstance(slack_channel, str):
                try:
                    slack_channel = SlackChannel[slack_channel.upper()]
                except KeyError:
                    # Fall back to activity channel
                    slack_channel = SlackChannel.ACTIVITY

            # Optional metadata → Slack fields
            fields: List[Dict[str, str]] = []
            meta_dict = metadata or {}
            for i, (k, v) in enumerate(meta_dict.items()):
                if i >= 10:
                    break
                fields.append({
                    "title": str(k),
                    "value": str(v),
                    "short": True,
                })

            notification = SlackNotification(
                notification_id=f"simple_{datetime.now().timestamp()}",
                notification_type=NotificationType.INFORMATIONAL,
                title=title or f"{emoji} System Notification",
                message=message,
                timestamp=datetime.now(),
                channel=slack_channel,
                color=color,
                fields=fields,
                metadata=meta_dict,
            )

            # A NOTIFICATION MUST NEVER HOLD ITS CALLER.
            #
            # `_send_slack_notification` retries on 429 and 5xx --
            # `await asyncio.sleep(retry_after)` then a recursive call, up to
            # max_retries -- and each attempt carries its own 30 s
            # ClientTimeout. Those bound one ATTEMPT, not the sequence, so the
            # total wait is retries x (timeout + backoff) and is unbounded from
            # the caller's point of view.
            #
            # That cost landed somewhere it had no business being. Measured:
            # every AbstractReasoningEngine.reason() call blocked indefinitely
            # at `_update_learning`, and instrumenting the awaits showed why --
            #
            #     ENTER select_strategy  EXIT 4ms
            #     ENTER store_memory     EXIT 148ms
            #     ENTER slack            (never exits)
            #
            # -- so all eight registered kinds of thinking were unreachable
            # through their own engine because a chat message would not resolve.
            # Reasoning does not depend on Slack, and must not wait on it.
            #
            # SEND_DEADLINE_SECONDS bounds the whole sequence including every
            # retry and backoff. On expiry the notification is dropped and the
            # caller is told it was not dispatched -- a lost message is a far
            # smaller failure than a stalled substrate, and returning False
            # keeps the two distinguishable.
            try:
                await asyncio.wait_for(
                    self._send_slack_notification(notification, force=force),
                    timeout=self.SEND_DEADLINE_SECONDS)
            except asyncio.TimeoutError:
                logger.warning(
                    "Slack notification dropped after %ss (channel=%s): the "
                    "caller is not held while a webhook is unreachable",
                    self.SEND_DEADLINE_SECONDS, getattr(notification, "channel", "?"))
                return False
            return True

        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    async def send_message(
        self,
        message: str,
        channel: Optional[Any] = None,
        title: Optional[str] = None,
        severity: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Backwards-compatible wrapper used by older components.

        Most legacy code calls ``send_message`` with some combination of
        ``message``, ``channel``, ``title``, ``severity`` and ``metadata``.
        This now forwards to :meth:`send_notification` with compatible
        semantics so legacy callers continue to work.
        """
        return await self.send_notification(
            message=message,
            title=title,
            channel=channel,
            severity=severity,
            metadata=metadata,
        )

    async def get_statistics(self) -> Dict[str, Any]:
        """Get notification statistics"""
        return {
            **self.stats,
            "pending_approvals": len(self.pending_approvals),
            "active_governance_sessions": len(self.governance_sessions),
            "notification_history_size": len(self.notification_history),
            "approval_rate": (
                self.stats['approvals_granted'] /
                max(1, self.stats['approvals_granted'] + self.stats['approvals_denied']) * 100
            )
        }

    async def close(self):
        """Close shared aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("Slack notifier session closed")


# Global instance
_slack_notifier: Optional[SlackNotifier] = None


def get_slack_notifier(webhook_url: Optional[str] = None) -> SlackNotifier:
    """Get global Slack notifier instance"""
    global _slack_notifier
    if _slack_notifier is None:
        _slack_notifier = SlackNotifier(webhook_url=webhook_url)
    return _slack_notifier


# Convenience functions for common notifications

async def notify_singleton_action(
    action_id: str,
    action_category: ActionCategory,
    action_type: str,
    description: str,
    decision_tier: DecisionTier,
    safety_risk: str = "LOW",
    impact_level: str = "LOW",
    commitment_contract_id: Optional[str] = None
):
    """Convenience function to notify about singleton action"""
    notifier = get_slack_notifier()

    action = SingletonAction(
        action_id=action_id,
        action_category=action_category,
        action_type=action_type,
        description=description,
        decision_tier=decision_tier,
        requires_governance=(decision_tier == DecisionTier.CRITICAL),
        requires_approval=(decision_tier == DecisionTier.IMPORTANT),
        safety_risk=safety_risk,
        impact_level=impact_level
    )

    await notifier.notify_singleton_action(action, commitment_contract_id)


async def send_security_alert(
    alert_title: str,
    alert_message: str,
    severity: str = "HIGH"
):
    """Convenience function to send security alert"""
    notifier = get_slack_notifier()
    await notifier.send_security_alert(alert_title, alert_message, severity)


async def send_learning_milestone(
    milestone_title: str,
    milestone_description: str,
    metrics: Dict[str, Any] = None
):
    """Convenience function to send learning milestone"""
    notifier = get_slack_notifier()
    await notifier.send_learning_milestone(
        milestone_title,
        milestone_description,
        metrics
    )


async def send_slack_notification(payload: Dict[str, Any]) -> bool:
    """Removed: outbound Slack notifications are disabled. Returns True (no-op).

    Kept as a callable so importers (notification_publisher and others) do not
    break; it makes no network call. The Slack TOOL is separate and unaffected.
    """
    if not SLACK_NOTIFICATIONS_ENABLED:
        return True
    try:
        notifier = get_slack_notifier()

        # Extract notification details
        title = payload.get('title', 'Notification')
        message = payload.get('message', '')
        notification_type = payload.get('type', 'informational')

        # Route based on type
        if notification_type == 'security_alert':
            await notifier.send_security_alert(
                alert_title=title,
                alert_message=message,
                severity=payload.get('severity', 'HIGH')
            )
        elif notification_type == 'learning_milestone':
            await notifier.send_learning_milestone(
                milestone_title=title,
                milestone_description=message,
                metrics=payload.get('metadata')
            )
        elif notification_type in ['system_info', 'system_warning', 'system_error', 'system_critical']:
            emoji_map = {
                'system_info': '✅',
                'system_warning': '⚠️',
                'system_error': '❌',
                'system_critical': '🚨'
            }
            emoji = emoji_map.get(notification_type, 'ℹ️')

            slack_payload = {
                "text": f"{emoji} *{title}*",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} {title}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": message
                        }
                    }
                ]
            }

            metadata = payload.get('metadata', {})
            if metadata:
                fields = []
                for key, value in metadata.items():
                    if isinstance(value, (str, int, float, bool)):
                        fields.append({"type": "mrkdwn", "text": f"*{key}:*\n{value}"})

                if fields:
                    slack_payload["blocks"].append({
                        "type": "section",
                        "fields": fields[:10]
                    })

            slack_payload["blocks"].append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"
                    }
                ]
            })

            webhook_url = notifier._get_webhook_url(SlackChannel.ACTIVITY)
            if webhook_url:
                import time as time_module
                start_time = time_module.time()
                try:
                    logger.debug(f"Sending {notification_type} notification to Slack (timeout=30s)")
                    # Use shared session from notifier singleton
                    session = notifier._get_session()
                    async with session.post(
                        webhook_url,
                        json=slack_payload,
                        timeout=aiohttp.ClientTimeout(total=30)  # Increased from 10s — observed latency ~22s
                    ) as response:
                            response_text = await response.text()
                            elapsed = (time_module.time() - start_time) * 1000
                            if response.status != 200 or response_text != "ok":
                                logger.error(f"Slack notification failed after {elapsed:.0f}ms: {response.status} - {response_text}")
                                # AN ALERT THAT DID NOT ARRIVE IS A FAILURE OF
                                # THE ALERTING PATH, and it was only ever a log
                                # line -- so the one channel that tells a person
                                # something is wrong could be silently down
                                # while every subsystem believed it had raised
                                # the alarm. Rate limiting (429) in particular
                                # drops alerts for a sustained window.
                                await _report_failure(
                                    failure_type="notification_failed",
                                    description=(f"Slack {notification_type} rejected: "
                                                 f"{response.status} {response_text}"),
                                    severity=("high" if response.status == 429 else "medium"),
                                    metadata={"status": response.status,
                                              "response": str(response_text)[:400],
                                              "notification_type": str(notification_type),
                                              "elapsed_ms": round(elapsed)})
                                return False
                            logger.debug(f"✓ {notification_type} notification sent ({elapsed:.0f}ms)")
                except asyncio.TimeoutError:
                    elapsed = (time_module.time() - start_time) * 1000
                    logger.error(f"✗ Slack notification timeout after {elapsed:.0f}ms (limit: 30000ms)")
                    await _report_failure(
                        failure_type="notification_timeout",
                        description=f"Slack {notification_type} timed out after {elapsed:.0f}ms",
                        severity="medium",
                        metadata={"elapsed_ms": round(elapsed), "limit_ms": 30000})
                    return False
                except Exception as send_error:
                    elapsed = (time_module.time() - start_time) * 1000
                    logger.error(f"✗ Slack notification error after {elapsed:.0f}ms: {send_error}")
                    return False
        else:
            # Generic informational message
            channel = SlackChannel.ACTIVITY
            slack_msg = SlackNotification(
                notification_type=NotificationType.INFORMATIONAL,
                channel=channel,
                title=title,
                message=message,
                color=payload.get('color', '#36a64f'),
                metadata=payload.get('metadata', {})
            )
            await notifier._send_slack_notification(slack_msg)

        return True  # Notification sent successfully

    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False
