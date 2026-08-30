#!/usr/bin/env python3
"""
Communication Tools
===================
Tools for external communication (Slack only - it's already set up)

Tools:
- send_slack_message: Send message to Dominion Labs Slack channels
- post_to_webhook: Generic webhook poster

Author: Torin AI Team
"""

import logging
import os
from typing import Any, Dict

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata


logger = logging.getLogger(__name__)


class SendSlackMessageTool(Tool):
    """Send message to Dominion Labs Slack"""

    def __init__(self):
        super().__init__()
        self.name = "send_slack_message"
        self.description = "Send notification message to Dominion Labs Slack channels (wraps existing Slack integration)"
        self.category = ToolCategory.COMMUNICATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="message",
                type="string",
                description="Message content",
                required=True
            ),
            ToolParameter(
                name="channel",
                type="string",
                description="Slack channel",
                required=False,
                default="torin-activity",
                enum=["torin-upgrades", "torin-alerts", "torin-decisions", "torin-activity"]
            ),
            ToolParameter(
                name="notification_type",
                type="string",
                description="Type of notification",
                required=False,
                default="info",
                enum=["self_upgrade", "security", "decision_required", "activity_summary", "info", "learning_milestone", "research_insight"]
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Notification title",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="send_slack_message",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SEND_MESSAGE,
                    description="SendSlackMessage capability"
                )
            ]
        )

    async def execute(self, message: str, channel: str = "torin-activity",
                     notification_type: str = "info", title: str = None) -> ToolResult:
        try:
            from core.integration.slack_notifier import send_slack_notification
            from datetime import datetime

            # Build notification object matching the existing Slack notifier format
            notification = {
                'id': f'tool_{hash(message) % 10000}',
                'type': notification_type,
                'title': title or "TorinAI Notification",
                'message': message,
                'time': datetime.now().isoformat(),
                'status': 'info',
                'metadata': {
                    'channel': channel,
                    'source': 'tool_call'
                }
            }

            # Send via existing Slack integration
            success = await send_slack_notification(notification)

            return ToolResult(
                success=success,
                output={
                    'sent': success,
                    'channel': channel,
                    'notification_type': notification_type,
                    'message': message[:100] + '...' if len(message) > 100 else message
                }
            )

        except Exception as e:
            logger.error(f"Slack notification error: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class PostToWebhookTool(Tool):
    """Post data to generic webhook"""

    def __init__(self):
        super().__init__()
        self.name = "post_to_webhook"
        self.description = "Send JSON data to any webhook URL"
        self.category = ToolCategory.COMMUNICATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="webhook_url",
                type="string",
                description="Webhook URL to post to",
                required=True
            ),
            ToolParameter(
                name="data",
                type="object",
                description="Data to send as JSON",
                required=True
            ),
            ToolParameter(
                name="headers",
                type="object",
                description="Optional HTTP headers",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="post_to_webhook",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SEND_MESSAGE,
                    description="PostToWebhook capability"
                )
            ]
        )

    async def execute(self, webhook_url: str, data: dict, headers: dict = None) -> ToolResult:
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=data,
                    headers=headers,
                    timeout=10
                ) as response:
                    response_text = await response.text()

                    return ToolResult(
                        success=response.status < 300,
                        output={
                            'url': webhook_url,
                            'status': response.status,
                            'response': response_text[:200]  # Limit response size
                        }
                    )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
