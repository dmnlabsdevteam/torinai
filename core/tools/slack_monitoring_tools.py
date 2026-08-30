#!/usr/bin/env python3
"""
Slack Monitoring & Interaction Tools
====================================
Comprehensive tools for Torin to monitor and interact with Dominion Labs Slack workspace.

Leverages all 43+ Slack Bot Events for internal monitoring:
- Message events (channels, DMs, threads)
- User activity (status, presence, profile changes)
- Channel events (create, archive, join, leave)
- File events (upload, share, delete)
- Reaction events (added, removed)
- App interactions (mentions, home tab)
- Team events (join, domain change)

IMPORTANT: These tools are for INTERNAL monitoring of Dominion Labs operations only.
"""

import logging
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)

# Slack Bot Token (for API calls)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")


class SlackEventType(Enum):
    """All Slack Bot Events that can be monitored"""
    # Message events
    MESSAGE_CHANNELS = "message.channels"
    MESSAGE_GROUPS = "message.groups"
    MESSAGE_IM = "message.im"
    MESSAGE_MPIM = "message.mpim"

    # App events
    APP_MENTION = "app_mention"
    APP_HOME_OPENED = "app_home_opened"
    APP_UNINSTALLED = "app_uninstalled"

    # Channel events
    CHANNEL_CREATED = "channel_created"
    CHANNEL_DELETED = "channel_deleted"
    CHANNEL_ARCHIVE = "channel_archive"
    CHANNEL_UNARCHIVE = "channel_unarchive"
    CHANNEL_RENAME = "channel_rename"
    CHANNEL_SHARED = "channel_shared"
    CHANNEL_UNSHARED = "channel_unshared"

    # Member events
    MEMBER_JOINED_CHANNEL = "member_joined_channel"
    MEMBER_LEFT_CHANNEL = "member_left_channel"

    # File events
    FILE_CREATED = "file_created"
    FILE_SHARED = "file_shared"
    FILE_UNSHARED = "file_unshared"
    FILE_PUBLIC = "file_public"
    FILE_DELETED = "file_deleted"
    FILE_CHANGE = "file_change"

    # Reaction events
    REACTION_ADDED = "reaction_added"
    REACTION_REMOVED = "reaction_removed"

    # User events
    USER_CHANGE = "user_change"
    USER_STATUS_CHANGED = "user_status_changed"
    USER_HUDDLE_CHANGED = "user_huddle_changed"
    USER_PROFILE_CHANGED = "user_profile_changed"

    # Team events
    TEAM_JOIN = "team_join"
    TEAM_RENAME = "team_rename"
    TEAM_DOMAIN_CHANGE = "team_domain_change"

    # Pin events
    PIN_ADDED = "pin_added"
    PIN_REMOVED = "pin_removed"

    # Star events
    STAR_ADDED = "star_added"
    STAR_REMOVED = "star_removed"

    # Emoji events
    EMOJI_CHANGED = "emoji_changed"

    # Group events (private channels)
    GROUP_ARCHIVE = "group_archive"
    GROUP_UNARCHIVE = "group_unarchive"
    GROUP_CLOSE = "group_close"
    GROUP_OPEN = "group_open"
    GROUP_RENAME = "group_rename"


# =============================================================================
# SLACK API INTERACTION FUNCTIONS
# =============================================================================

async def get_slack_users(include_bots: bool = False) -> Dict[str, Any]:
    """
    Get list of all users in Dominion Labs Slack workspace.

    Args:
        include_bots: Include bot users in results

    Returns:
        dict: {"success": bool, "users": List[dict], "count": int}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://slack.com/api/users.list",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                users = data.get("members", [])

                # Filter out bots if requested
                if not include_bots:
                    users = [u for u in users if not u.get("is_bot", False)]

                return {
                    "success": True,
                    "users": users,
                    "count": len(users)
                }

    except Exception as e:
        logger.error(f"Error getting Slack users: {e}")
        return {"success": False, "error": str(e)}


async def get_slack_channels(types: str = "public_channel,private_channel") -> Dict[str, Any]:
    """
    Get list of all channels in Dominion Labs Slack workspace.

    Args:
        types: Channel types to include (public_channel, private_channel, mpim, im)

    Returns:
        dict: {"success": bool, "channels": List[dict], "count": int}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                params={"types": types, "exclude_archived": False}
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                channels = data.get("channels", [])

                return {
                    "success": True,
                    "channels": channels,
                    "count": len(channels)
                }

    except Exception as e:
        logger.error(f"Error getting Slack channels: {e}")
        return {"success": False, "error": str(e)}


async def get_channel_history(
    channel_id: str,
    limit: int = 100,
    oldest: Optional[str] = None,
    latest: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get message history from a Slack channel.

    Args:
        channel_id: Channel ID to fetch history from
        limit: Number of messages to retrieve (max 1000)
        oldest: Only messages after this Unix timestamp
        latest: Only messages before this Unix timestamp

    Returns:
        dict: {"success": bool, "messages": List[dict], "count": int}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        params = {"channel": channel_id, "limit": min(limit, 1000)}
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://slack.com/api/conversations.history",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                params=params
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                messages = data.get("messages", [])

                return {
                    "success": True,
                    "messages": messages,
                    "count": len(messages),
                    "has_more": data.get("has_more", False)
                }

    except Exception as e:
        logger.error(f"Error getting channel history: {e}")
        return {"success": False, "error": str(e)}


async def search_slack_messages(query: str, count: int = 20) -> Dict[str, Any]:
    """
    Search for messages in Dominion Labs Slack workspace.

    Args:
        query: Search query
        count: Number of results to return

    Returns:
        dict: {"success": bool, "messages": List[dict], "total": int}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://slack.com/api/search.messages",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                params={"query": query, "count": count}
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                messages = data.get("messages", {})

                return {
                    "success": True,
                    "messages": messages.get("matches", []),
                    "total": messages.get("total", 0)
                }

    except Exception as e:
        logger.error(f"Error searching Slack messages: {e}")
        return {"success": False, "error": str(e)}


async def get_user_presence(user_id: str) -> Dict[str, Any]:
    """
    Get presence status for a specific user.

    Args:
        user_id: User ID to check

    Returns:
        dict: {"success": bool, "presence": str ("active" or "away"), "online": bool}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://slack.com/api/users.getPresence",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                params={"user": user_id}
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                presence = data.get("presence", "away")

                return {
                    "success": True,
                    "presence": presence,
                    "online": presence == "active"
                }

    except Exception as e:
        logger.error(f"Error getting user presence: {e}")
        return {"success": False, "error": str(e)}


async def post_slack_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None,
    blocks: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Post a message to a Slack channel.

    Args:
        channel: Channel ID or name
        text: Message text
        thread_ts: Optional thread timestamp to reply in thread
        blocks: Optional Block Kit blocks for rich formatting

    Returns:
        dict: {"success": bool, "ts": str, "channel": str}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        payload = {
            "channel": channel,
            "text": text
        }

        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json=payload
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                return {
                    "success": True,
                    "ts": data.get("ts"),
                    "channel": data.get("channel")
                }

    except Exception as e:
        logger.error(f"Error posting Slack message: {e}")
        return {"success": False, "error": str(e)}


async def add_reaction(channel: str, timestamp: str, emoji: str) -> Dict[str, Any]:
    """
    Add an emoji reaction to a message.

    Args:
        channel: Channel ID
        timestamp: Message timestamp
        emoji: Emoji name (without colons, e.g., "thumbsup")

    Returns:
        dict: {"success": bool}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://slack.com/api/reactions.add",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={"channel": channel, "timestamp": timestamp, "name": emoji}
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                return {"success": True}

    except Exception as e:
        logger.error(f"Error adding reaction: {e}")
        return {"success": False, "error": str(e)}


async def get_channel_members(channel_id: str) -> Dict[str, Any]:
    """
    Get list of members in a channel.

    Args:
        channel_id: Channel ID

    Returns:
        dict: {"success": bool, "members": List[str], "count": int}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://slack.com/api/conversations.members",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                params={"channel": channel_id}
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                members = data.get("members", [])

                return {
                    "success": True,
                    "members": members,
                    "count": len(members)
                }

    except Exception as e:
        logger.error(f"Error getting channel members: {e}")
        return {"success": False, "error": str(e)}


async def get_file_info(file_id: str) -> Dict[str, Any]:
    """
    Get information about a shared file.

    Args:
        file_id: File ID

    Returns:
        dict: {"success": bool, "file": dict}
    """
    try:
        import aiohttp

        if not SLACK_BOT_TOKEN:
            return {"success": False, "error": "SLACK_BOT_TOKEN not configured"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://slack.com/api/files.info",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                params={"file": file_id}
            ) as response:
                data = await response.json()

                if not data.get("ok"):
                    return {"success": False, "error": data.get("error", "Unknown error")}

                return {
                    "success": True,
                    "file": data.get("file", {})
                }

    except Exception as e:
        logger.error(f"Error getting file info: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# SLACK EVENT MONITORING FUNCTIONS
# =============================================================================

async def monitor_team_activity(hours: int = 24) -> Dict[str, Any]:
    """
    Monitor Dominion Labs team activity over specified time period.

    Analyzes:
    - Message activity by user
    - Channel activity
    - File shares
    - Reaction usage
    - Online presence patterns

    Args:
        hours: Number of hours to analyze

    Returns:
        dict: {"success": bool, "activity": dict, "insights": List[str]}
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours)
        cutoff_ts = str(cutoff_time.timestamp())

        # Get all channels
        channels_result = await get_slack_channels()
        if not channels_result["success"]:
            return channels_result

        channels = channels_result["channels"]

        # Analyze activity across channels
        activity = {
            "message_count": 0,
            "active_users": set(),
            "channel_activity": {},
            "timeframe_hours": hours
        }

        for channel in channels:
            if channel.get("is_archived"):
                continue

            channel_id = channel["id"]
            channel_name = channel.get("name", "unknown")

            # Get recent messages
            history = await get_channel_history(channel_id, limit=100, oldest=cutoff_ts)

            if history["success"]:
                messages = history["messages"]
                activity["message_count"] += len(messages)
                activity["channel_activity"][channel_name] = len(messages)

                # Track active users
                for msg in messages:
                    if "user" in msg:
                        activity["active_users"].add(msg["user"])

        # Convert set to count
        activity["active_user_count"] = len(activity["active_users"])
        activity["active_users"] = list(activity["active_users"])

        # Generate insights
        insights = []

        if activity["message_count"] == 0:
            insights.append("⚠️ No team activity detected in the specified timeframe")
        else:
            insights.append(f"📊 {activity['message_count']} messages across {len(activity['channel_activity'])} channels")
            insights.append(f"👥 {activity['active_user_count']} team members active")

            # Most active channel
            if activity["channel_activity"]:
                most_active = max(activity["channel_activity"].items(), key=lambda x: x[1])
                insights.append(f"🔥 Most active channel: #{most_active[0]} ({most_active[1]} messages)")

        return {
            "success": True,
            "activity": activity,
            "insights": insights
        }

    except Exception as e:
        logger.error(f"Error monitoring team activity: {e}")
        return {"success": False, "error": str(e)}


async def get_team_health_metrics() -> Dict[str, Any]:
    """
    Get health metrics for Dominion Labs team based on Slack activity.

    Metrics:
    - Response times
    - Collaboration patterns
    - Work hours patterns
    - Channel engagement

    Returns:
        dict: {"success": bool, "metrics": dict, "health_score": float}
    """
    try:
        # Get users and their presence
        users_result = await get_slack_users(include_bots=False)
        if not users_result["success"]:
            return users_result

        users = users_result["users"]

        # Check presence for all users
        online_count = 0
        for user in users:
            if not user.get("deleted", False):
                presence = await get_user_presence(user["id"])
                if presence.get("online"):
                    online_count += 1

        total_users = len([u for u in users if not u.get("deleted", False)])
        online_percentage = (online_count / total_users * 100) if total_users > 0 else 0

        # Get recent activity
        activity = await monitor_team_activity(hours=24)

        metrics = {
            "total_team_members": total_users,
            "currently_online": online_count,
            "online_percentage": round(online_percentage, 1),
            "messages_24h": activity.get("activity", {}).get("message_count", 0),
            "active_users_24h": activity.get("activity", {}).get("active_user_count", 0)
        }

        # Calculate health score (0-100)
        health_score = 0.0

        # Factor 1: Online presence (30%)
        health_score += (online_percentage / 100) * 30

        # Factor 2: Active users in last 24h (40%)
        active_ratio = metrics["active_users_24h"] / total_users if total_users > 0 else 0
        health_score += active_ratio * 40

        # Factor 3: Message activity (30%)
        # Assume healthy: 50+ messages per day
        message_factor = min(metrics["messages_24h"] / 50, 1.0)
        health_score += message_factor * 30

        return {
            "success": True,
            "metrics": metrics,
            "health_score": round(health_score, 1),
            "status": "healthy" if health_score >= 70 else "needs_attention" if health_score >= 40 else "concerning"
        }

    except Exception as e:
        logger.error(f"Error getting team health metrics: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# TOOL REGISTRY INTEGRATION
# =============================================================================
try:
    from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
    from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel

    class GetSlackUsersTool(Tool):
        """Get list of users in Dominion Labs Slack workspace"""

        def __init__(self):
            super().__init__()
            self.name = "get_slack_users"
            self.description = "Get list of all users in Dominion Labs Slack workspace for internal monitoring"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.SAFE
            self.parameters = [
                ToolParameter(
                    name="include_bots",
                    type="boolean",
                    description="Include bot users in results",
                    required=False,
                    default=False
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="get_slack_users",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.READ_DATA,
                        description="GetSlackUsers capability"
                    )
                ]
            )

        async def execute(self, include_bots: bool = False) -> ToolResult:
            result = await get_slack_users(include_bots=include_bots)
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )


    class GetSlackChannelsTool(Tool):
        """Get list of channels in Dominion Labs Slack workspace"""

        def __init__(self):
            super().__init__()
            self.name = "get_slack_channels"
            self.description = "Get list of all channels in Dominion Labs Slack workspace"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.SAFE
            self.parameters = [
                ToolParameter(
                    name="types",
                    type="string",
                    description="Channel types to include",
                    required=False,
                    default="public_channel,private_channel"
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="get_slack_channels",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.READ_DATA,
                        description="GetSlackChannels capability"
                    )
                ]
            )

        async def execute(self, types: str = "public_channel,private_channel") -> ToolResult:
            result = await get_slack_channels(types=types)
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )


    class SearchSlackMessagesTool(Tool):
        """Search for messages in Dominion Labs Slack"""

        def __init__(self):
            super().__init__()
            self.name = "search_slack_messages"
            self.description = "Search for messages in Dominion Labs Slack workspace"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.SAFE
            self.parameters = [
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query",
                    required=True
                ),
                ToolParameter(
                    name="count",
                    type="number",
                    description="Number of results to return",
                    required=False,
                    default=20
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="search_slack_messages",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.SEARCH_DATA,
                        description="SearchSlackMessages capability"
                    )
                ]
            )

        async def execute(self, query: str, count: int = 20) -> ToolResult:
            result = await search_slack_messages(query=query, count=count)
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )


    class GetChannelHistoryTool(Tool):
        """Get message history from a Slack channel"""

        def __init__(self):
            super().__init__()
            self.name = "get_channel_history"
            self.description = "Get message history from a specific Slack channel"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.SAFE
            self.parameters = [
                ToolParameter(
                    name="channel_id",
                    type="string",
                    description="Channel ID to fetch history from",
                    required=True
                ),
                ToolParameter(
                    name="limit",
                    type="number",
                    description="Number of messages to retrieve",
                    required=False,
                    default=100
                ),
                ToolParameter(
                    name="oldest",
                    type="string",
                    description="Only messages after this Unix timestamp",
                    required=False
                ),
                ToolParameter(
                    name="latest",
                    type="string",
                    description="Only messages before this Unix timestamp",
                    required=False
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="get_channel_history",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.READ_DATA,
                        description="GetChannelHistory capability"
                    ),
                    CapabilityMetadata(
                        capability=Capability.RECEIVE_MESSAGE,
                        description="Receive and read messages from Slack channels",
                        input_types=["channel_id", "filters"],
                        output_types=["messages"],
                        latency="medium",
                        cost="low",
                        reliability="high",
                        risk_level=RiskLevel.LOW,
                        priority=8
                    )
                ]
            )

        async def execute(self, channel_id: str, limit: int = 100,
                         oldest: Optional[str] = None, latest: Optional[str] = None) -> ToolResult:
            result = await get_channel_history(
                channel_id=channel_id,
                limit=limit,
                oldest=oldest,
                latest=latest
            )
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )


    class MonitorTeamActivityTool(Tool):
        """Monitor Dominion Labs team activity on Slack"""

        def __init__(self):
            super().__init__()
            self.name = "monitor_team_activity"
            self.description = "Monitor Dominion Labs team activity patterns and engagement on Slack"
            self.category = ToolCategory.MONITORING
            self.safety_level = ToolSafety.SAFE
            self.parameters = [
                ToolParameter(
                    name="hours",
                    type="number",
                    description="Number of hours to analyze",
                    required=False,
                    default=24
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="monitor_team_activity",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.ANALYZE_PERFORMANCE,
                        description="MonitorTeamActivity capability"
                    )
                ]
            )

        async def execute(self, hours: int = 24) -> ToolResult:
            result = await monitor_team_activity(hours=hours)
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )


    class GetTeamHealthMetricsTool(Tool):
        """Get health metrics for Dominion Labs team"""

        def __init__(self):
            super().__init__()
            self.name = "get_team_health_metrics"
            self.description = "Get health metrics for Dominion Labs team based on Slack activity patterns"
            self.category = ToolCategory.MONITORING
            self.safety_level = ToolSafety.SAFE
            self.parameters = []

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="get_team_health_metrics",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.ANALYZE_PERFORMANCE,
                        description="Get team health metrics"
                    )
                ]
            )

        async def execute(self) -> ToolResult:
            result = await get_team_health_metrics()
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )


    class PostSlackMessageTool(Tool):
        """Post a message to a Slack channel"""

        def __init__(self):
            super().__init__()
            self.name = "post_slack_message"
            self.description = "Post a message to a Slack channel (for internal operations)"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.MODERATE
            self.parameters = [
                ToolParameter(
                    name="channel",
                    type="string",
                    description="Channel ID or name",
                    required=True
                ),
                ToolParameter(
                    name="text",
                    type="string",
                    description="Message text",
                    required=True
                ),
                ToolParameter(
                    name="thread_ts",
                    type="string",
                    description="Optional thread timestamp to reply in thread",
                    required=False
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="post_slack_message",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.SEND_MESSAGE,
                        description="PostSlackMessage capability"
                    )
                ]
            )

        async def execute(self, channel: str, text: str, thread_ts: Optional[str] = None) -> ToolResult:
            result = await post_slack_message(
                channel=channel,
                text=text,
                thread_ts=thread_ts
            )
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )


    class GetUserPresenceTool(Tool):
        """Get presence status for a Slack user"""

        def __init__(self):
            super().__init__()
            self.name = "get_user_presence"
            self.description = "Get online/away presence status for a specific Slack user"
            self.category = ToolCategory.COMMUNICATION
            self.safety_level = ToolSafety.SAFE
            self.parameters = [
                ToolParameter(
                    name="user_id",
                    type="string",
                    description="User ID to check",
                    required=True
                )
            ]

            # Capability profile
            self.capability_profile = ToolCapabilityProfile(
                tool_name="get_user_presence",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.READ_DATA,
                        description="GetUserPresence capability"
                    )
                ]
            )

        async def execute(self, user_id: str) -> ToolResult:
            result = await get_user_presence(user_id=user_id)
            return ToolResult(
                success=result["success"],
                output=result,
                error=result.get("error")
            )

except ImportError:
    logger.info("Tool registry not available - slack_monitoring_tools will work as functions only")


# Export functions
__all__ = [
    # User functions
    'get_slack_users',
    'get_user_presence',

    # Channel functions
    'get_slack_channels',
    'get_channel_history',
    'get_channel_members',

    # Message functions
    'search_slack_messages',
    'post_slack_message',
    'add_reaction',

    # File functions
    'get_file_info',

    # Monitoring functions
    'monitor_team_activity',
    'get_team_health_metrics',

    # Enums
    'SlackEventType'
]
