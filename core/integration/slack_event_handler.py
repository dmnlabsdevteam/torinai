#!/usr/bin/env python3
"""
Slack Event Handler
===================
Receives and processes all Slack Bot Events (43+ events enabled).

This handler receives webhook callbacks from Slack when events occur in the
Dominion Labs workspace and routes them to appropriate monitoring/processing functions.

Event Categories:
- Message events (channels, DMs, threads)
- User activity (presence, status, profile changes)
- Channel operations (create, archive, rename)
- File operations (share, delete, change)
- Reactions (added, removed)
- Team events (join, rename)
- App interactions (mentions, home opened)
"""

import logging
import asyncio
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class EventPriority(Enum):
    """Priority levels for event processing"""
    HIGH = "high"        # Requires immediate attention (mentions, security)
    MEDIUM = "medium"    # Important but not urgent (file shares, joins)
    LOW = "low"          # Informational only (reactions, status changes)


class SlackEventHandler:
    """
    Central handler for all Slack Bot Events.

    Processes 43+ Slack event types and routes them to appropriate handlers.
    """

    def __init__(self):
        self.event_handlers: Dict[str, Callable] = {}
        self.event_statistics: Dict[str, int] = {}
        self.last_event_time: Optional[datetime] = None

        # Register default handlers
        self._register_default_handlers()

        logger.info("SlackEventHandler initialized - ready to process 43+ event types")

    def _register_default_handlers(self):
        """Register default handlers for all event types"""

        # Message events (HIGH priority - might need responses)
        self.register_handler("app_mention", self._handle_app_mention, EventPriority.HIGH)
        self.register_handler("message.channels", self._handle_channel_message, EventPriority.MEDIUM)
        self.register_handler("message.im", self._handle_direct_message, EventPriority.HIGH)
        self.register_handler("message.groups", self._handle_group_message, EventPriority.MEDIUM)

        # User events (LOW-MEDIUM priority - tracking)
        self.register_handler("user_change", self._handle_user_change, EventPriority.LOW)
        self.register_handler("user_status_changed", self._handle_status_change, EventPriority.LOW)
        self.register_handler("team_join", self._handle_team_join, EventPriority.MEDIUM)

        # Channel events (MEDIUM priority - organizational awareness)
        self.register_handler("channel_created", self._handle_channel_created, EventPriority.MEDIUM)
        self.register_handler("channel_deleted", self._handle_channel_deleted, EventPriority.MEDIUM)
        self.register_handler("channel_archive", self._handle_channel_archive, EventPriority.LOW)
        self.register_handler("member_joined_channel", self._handle_member_joined, EventPriority.LOW)
        self.register_handler("member_left_channel", self._handle_member_left, EventPriority.LOW)

        # File events (MEDIUM-HIGH priority - security monitoring)
        self.register_handler("file_shared", self._handle_file_shared, EventPriority.MEDIUM)
        self.register_handler("file_deleted", self._handle_file_deleted, EventPriority.LOW)
        self.register_handler("file_public", self._handle_file_public, EventPriority.HIGH)

        # Reaction events (LOW priority - engagement tracking)
        self.register_handler("reaction_added", self._handle_reaction_added, EventPriority.LOW)
        self.register_handler("reaction_removed", self._handle_reaction_removed, EventPriority.LOW)

    def register_handler(
        self,
        event_type: str,
        handler: Callable,
        priority: EventPriority = EventPriority.MEDIUM
    ):
        """
        Register a handler function for a specific event type.

        Args:
            event_type: Slack event type (e.g., "app_mention", "file_shared")
            handler: Async function to handle the event
            priority: Processing priority
        """
        self.event_handlers[event_type] = {
            "handler": handler,
            "priority": priority
        }
        logger.debug(f"Registered handler for {event_type} (priority: {priority.value})")

    async def process_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process incoming Slack event.

        Args:
            event_data: Raw event data from Slack webhook

        Returns:
            dict: {"success": bool, "processed": bool, "event_type": str}
        """
        try:
            # Slack sends challenge on verification
            if "challenge" in event_data:
                return {"challenge": event_data["challenge"]}

            # Extract event details
            event = event_data.get("event", {})
            event_type = event.get("type")

            if not event_type:
                logger.warning("Received event without type")
                return {"success": False, "error": "No event type"}

            # Update statistics
            self.event_statistics[event_type] = self.event_statistics.get(event_type, 0) + 1
            self.last_event_time = datetime.now()

            # Route to appropriate handler
            handler_info = self.event_handlers.get(event_type)

            if handler_info:
                handler = handler_info["handler"]
                priority = handler_info["priority"]

                logger.info(f"Processing {event_type} event (priority: {priority.value})")

                # Process based on priority
                if priority == EventPriority.HIGH:
                    # Process immediately
                    await handler(event)
                else:
                    # Process async (don't block webhook response)
                    asyncio.create_task(handler(event))

                return {
                    "success": True,
                    "processed": True,
                    "event_type": event_type,
                    "priority": priority.value
                }
            else:
                logger.info(f"No handler registered for {event_type} - logging only")
                await self._log_unhandled_event(event_type, event)

                return {
                    "success": True,
                    "processed": False,
                    "event_type": event_type,
                    "note": "No handler registered"
                }

        except Exception as e:
            logger.error(f"Error processing Slack event: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ==========================================================================
    # DEFAULT EVENT HANDLERS
    # ==========================================================================

    async def _handle_app_mention(self, event: Dict[str, Any]):
        """Handle @Torin mentions in channels"""
        try:
            user = event.get("user")
            text = event.get("text", "")
            channel = event.get("channel")
            ts = event.get("ts")

            logger.info(f"🔔 App mention from {user} in {channel}: {text[:100]}")

            # TODO: Integrate with chat system to respond to mention
            # For now, just log and acknowledge
            from core.tools.slack_monitoring_tools import add_reaction
            await add_reaction(channel, ts, "eyes")  # React with 👀 to show we saw it

        except Exception as e:
            logger.error(f"Error handling app mention: {e}")

    async def _handle_channel_message(self, event: Dict[str, Any]):
        """Handle messages in channels"""
        channel = event.get("channel")
        user = event.get("user")

        # Only log, don't process every message (would be noisy)
        logger.debug(f"Message in channel {channel} from {user}")

    async def _handle_direct_message(self, event: Dict[str, Any]):
        """Handle direct messages to Torin"""
        try:
            user = event.get("user")
            text = event.get("text", "")
            channel = event.get("channel")

            logger.info(f"📩 Direct message from {user}: {text[:100]}")

            # TODO: Integrate with chat system for DM responses
            # For now, acknowledge receipt
            from core.tools.slack_monitoring_tools import post_slack_message
            await post_slack_message(
                channel=channel,
                text="Thanks for reaching out! I'm Torin. How can I help with Dominion Labs operations?"
            )

        except Exception as e:
            logger.error(f"Error handling direct message: {e}")

    async def _handle_group_message(self, event: Dict[str, Any]):
        """Handle messages in private channels"""
        logger.debug(f"Group message in {event.get('channel')}")

    async def _handle_user_change(self, event: Dict[str, Any]):
        """Handle user profile changes"""
        user_id = event.get("user", {}).get("id")
        logger.debug(f"User {user_id} profile changed")

    async def _handle_status_change(self, event: Dict[str, Any]):
        """Handle user status changes"""
        user = event.get("user")
        status = event.get("status_text", "")
        logger.debug(f"User {user} status changed: {status}")

    async def _handle_team_join(self, event: Dict[str, Any]):
        """Handle new team member joining"""
        try:
            user = event.get("user", {})
            user_name = user.get("real_name", user.get("name", "Unknown"))

            logger.info(f"🎉 New team member joined: {user_name}")

            # Send welcome notification to team
            from core.integration.slack_notifier import get_slack_notifier, SlackChannel
            slack = get_slack_notifier()

            await slack.send_notification(
                message=f"Welcome {user_name} to Dominion Labs! 🎉",
                title="New Team Member",
                channel=SlackChannel.ACTIVITY,
                severity="info"
            )

        except Exception as e:
            logger.error(f"Error handling team join: {e}")

    async def _handle_channel_created(self, event: Dict[str, Any]):
        """Handle channel creation"""
        channel = event.get("channel", {})
        channel_name = channel.get("name", "unknown")
        creator = channel.get("creator")

        logger.info(f"📢 New channel created: #{channel_name} by {creator}")

    async def _handle_channel_deleted(self, event: Dict[str, Any]):
        """Handle channel deletion"""
        channel_id = event.get("channel")
        logger.info(f"🗑️  Channel {channel_id} deleted")

    async def _handle_channel_archive(self, event: Dict[str, Any]):
        """Handle channel archival"""
        channel_id = event.get("channel")
        logger.info(f"📦 Channel {channel_id} archived")

    async def _handle_member_joined(self, event: Dict[str, Any]):
        """Handle member joining a channel"""
        user = event.get("user")
        channel = event.get("channel")
        logger.debug(f"User {user} joined channel {channel}")

    async def _handle_member_left(self, event: Dict[str, Any]):
        """Handle member leaving a channel"""
        user = event.get("user")
        channel = event.get("channel")
        logger.debug(f"User {user} left channel {channel}")

    async def _handle_file_shared(self, event: Dict[str, Any]):
        """Handle file sharing (important for security monitoring)"""
        try:
            file = event.get("file", {})
            file_id = file.get("id")
            file_name = file.get("name", "unknown")
            user = event.get("user_id")

            logger.info(f"📎 File shared: {file_name} by {user}")

            # Security check: Monitor for sensitive file patterns
            sensitive_patterns = [".env", "credentials", "password", "secret", "private_key", ".pem"]

            if any(pattern in file_name.lower() for pattern in sensitive_patterns):
                logger.warning(f"⚠️  Potential sensitive file shared: {file_name}")

                # Alert security team
                from core.tools.slack_tools import report_security_finding
                await report_security_finding(
                    finding_type="Sensitive File Shared",
                    description=f"User {user} shared file '{file_name}' which may contain sensitive data",
                    severity="MEDIUM",
                    affected_user=user,
                    evidence={"file_id": file_id, "file_name": file_name},
                    notify_who="stefan"
                )

        except Exception as e:
            logger.error(f"Error handling file shared: {e}")

    async def _handle_file_deleted(self, event: Dict[str, Any]):
        """Handle file deletion"""
        file_id = event.get("file_id")
        logger.debug(f"File {file_id} deleted")

    async def _handle_file_public(self, event: Dict[str, Any]):
        """Handle file made public (SECURITY CRITICAL)"""
        try:
            file = event.get("file", {})
            file_name = file.get("name", "unknown")
            user = event.get("user_id")

            logger.warning(f"🚨 File made PUBLIC: {file_name} by {user}")

            # Always alert on public files (security risk)
            from core.tools.slack_tools import report_security_finding
            await report_security_finding(
                finding_type="File Made Public",
                description=f"User {user} made file '{file_name}' publicly accessible",
                severity="HIGH",
                affected_user=user,
                evidence={"file_name": file_name},
                notify_who="both"
            )

        except Exception as e:
            logger.error(f"Error handling file public: {e}")

    async def _handle_reaction_added(self, event: Dict[str, Any]):
        """Handle emoji reaction added"""
        # Low priority - just track engagement
        logger.debug(f"Reaction added: {event.get('reaction')}")

    async def _handle_reaction_removed(self, event: Dict[str, Any]):
        """Handle emoji reaction removed"""
        logger.debug(f"Reaction removed: {event.get('reaction')}")

    async def _log_unhandled_event(self, event_type: str, event: Dict[str, Any]):
        """Log events without specific handlers"""
        logger.info(f"Unhandled event type: {event_type}")

        # Store for analysis if needed
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            await db.execute_query(
                """
                INSERT INTO slack_events_log
                (event_type, event_data, received_at)
                VALUES ($1, $2, NOW())
                """,
                params=(event_type, str(event)),
                commit=True,
            )

        except Exception as e:
            logger.debug(f"Could not log event to database: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get event processing statistics"""
        return {
            "total_events_processed": sum(self.event_statistics.values()),
            "events_by_type": self.event_statistics,
            "last_event_time": self.last_event_time.isoformat() if self.last_event_time else None,
            "registered_handlers": len(self.event_handlers)
        }


# Global instance
_slack_event_handler: Optional[SlackEventHandler] = None


def get_slack_event_handler() -> SlackEventHandler:
    """Get or create global Slack event handler"""
    global _slack_event_handler

    if _slack_event_handler is None:
        _slack_event_handler = SlackEventHandler()

    return _slack_event_handler
