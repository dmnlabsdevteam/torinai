
#!/usr/bin/env python3
"""
Notification Publisher for TorinAI
Sends notifications to Slack channels for immediate visibility.

Also publishes to API Gateway (for notification dashboard/governance sessions).
"""
import os
import json
import asyncio
import logging
import hashlib
from datetime import datetime, date
from typing import Dict, Any, Optional
from collections import OrderedDict

try:
    import httpx
except Exception:
    httpx = None

# SLACK REMOVED 2026-08-25. Outbound Slack notifications are retired; the Slack
# TOOL (core/tools/slack_tools) is separate and unaffected. Forced off here so
# the publisher never attempts a Slack send and never logs a "Slack fallback".
SLACK_AVAILABLE = False

logger = logging.getLogger(__name__)

# ============================================================================
# NOTIFICATION DEDUPLICATION
# ============================================================================
# Track recent notifications to prevent duplicates within a time window

class NotificationDeduplicator:
    """Prevents duplicate notifications within a configurable time window."""

    def __init__(self, window_seconds: int = 60, max_cache_size: int = 100):
        self.window_seconds = window_seconds
        self.max_cache_size = max_cache_size
        self._recent: OrderedDict[str, float] = OrderedDict()  # hash -> timestamp

    def _compute_hash(self, payload: Dict[str, Any]) -> str:
        """Compute a content hash for deduplication (ignores timestamps)."""
        # Create a copy excluding time-related fields
        dedupe_payload = {
            k: v for k, v in payload.items()
            if k not in ('id', 'time', 'timestamp')
        }
        content = json.dumps(dedupe_payload, sort_keys=True, default=str)
        return hashlib.md5(content.encode()).hexdigest()

    def is_duplicate(self, payload: Dict[str, Any]) -> bool:
        """Check if this notification was recently sent."""
        content_hash = self._compute_hash(payload)
        now = datetime.now().timestamp()

        # Clean old entries
        cutoff = now - self.window_seconds
        expired = [h for h, ts in self._recent.items() if ts < cutoff]
        for h in expired:
            del self._recent[h]

        # Trim to max size if needed
        while len(self._recent) > self.max_cache_size:
            self._recent.popitem(last=False)

        # Check if duplicate
        if content_hash in self._recent:
            logger.debug(f"Duplicate notification suppressed: {payload.get('title', 'N/A')[:50]}")
            return True

        # Record this notification
        self._recent[content_hash] = now
        return False


# Global deduplicator instance
_deduplicator = NotificationDeduplicator(window_seconds=60, max_cache_size=100)

logger = logging.getLogger(__name__)

def _make_serializable(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable types in a payload."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    return obj


def _gateway_base() -> str:
    base = os.getenv('GATEWAY_BASE')
    if base:
        return base.rstrip('/')
    return 'http://localhost:8080'

async def publish_notification(
    payload: Dict[str, Any],
    notify_token: Optional[str] = None,
    send_to_slack: bool = True,
    max_retries: int = 3,
    skip_deduplication: bool = False
) -> bool:
    """
    Publish notification to API Gateway and optionally to Slack

    Includes retry logic with exponential backoff to handle API gateway startup delays.
    Implements deduplication to prevent duplicate notifications within a 60-second window.

    Args:
        payload: Notification payload dict with keys:
            - id: Notification ID
            - type: Notification type (self_upgrade, security, etc.)
            - title: Notification title
            - message: Notification message
            - status: Notification status
            - metadata: Additional metadata dict (optional)
        notify_token: Optional authentication token
        send_to_slack: Whether to also send to Slack (default True)
        max_retries: Maximum retry attempts for API gateway (default 3)
        skip_deduplication: If True, bypass deduplication check (default False)

    Returns:
        bool: True if API Gateway publish succeeded OR Slack succeeded (fallback)
    """
    # Check for duplicate notifications (unless explicitly skipped)
    if not skip_deduplication and _deduplicator.is_duplicate(payload):
        return True  # Return True to indicate "handled" (just suppressed)

    if httpx is None:
        # If httpx unavailable, try Slack only
        if send_to_slack and SLACK_AVAILABLE:
            try:
                asyncio.create_task(send_slack_notification(payload))
                return True
            except Exception:
                pass
        return False

    p = _make_serializable(dict(payload))
    p.setdefault('time', datetime.now().isoformat())

    # Send to API Gateway with retry logic
    gateway_success = False
    headers = {'Content-Type': 'application/json'}
    token = notify_token or os.getenv('NOTIFY_TOKEN')
    if token:
        headers['X-Notify-Token'] = token

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{_gateway_base()}/api/notifications/publish", json=p, headers=headers)
                gateway_success = resp.status_code == 200

            if gateway_success:
                break
            else:
                logger.warning(f"API Gateway returned status {resp.status_code}, attempt {attempt + 1}/{max_retries}")

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            # API Gateway not ready yet - wait and retry. A gateway that is
            # simply not running (the substrate is stopped) is an expected,
            # recurring condition, not an incident: the notification is still
            # captured in the log channels the dashboard reads, so this degrades
            # at DEBUG rather than a WARNING per attempt on every cycle.
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.debug(f"API Gateway unavailable (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.debug(f"API Gateway unavailable after {max_retries} attempts")

        except Exception as e:
            logger.error(f"Unexpected error publishing to API Gateway: {e}")
            break

    # Send to Slack (always attempt if enabled, even if gateway succeeded)
    slack_success = False
    if send_to_slack and SLACK_AVAILABLE:
        try:
            # AWAIT instead of fire-and-forget so we know if it succeeds
            slack_success = await send_slack_notification(p)
        except Exception as e:
            logger.warning(f"Failed to send Slack notification: {e}")
            slack_success = False

    # Success if either gateway OR Slack worked
    return gateway_success or slack_success


async def send_system_notification(
    title: str,
    message: str,
    severity: str = "info",
    metadata: Dict[str, Any] = None
):
    """
    Send system notification via notification publisher

    Args:
        title: Notification title
        message: Notification message
        severity: Severity level (info, warning, error, critical)
        metadata: Additional metadata
    """
    # Map severity to color
    color_map = {
        "info": "#36a64f",
        "warning": "#FFA500",
        "error": "#F44336",
        "critical": "#880E4F"
    }

    notification_type_map = {
        "info": "system_info",
        "warning": "system_warning",
        "error": "system_error",
        "critical": "system_critical"
    }

    await publish_notification({
        'id': f'system_{datetime.now().timestamp()}',
        'type': notification_type_map.get(severity, 'system_info'),
        'title': title,
        'message': message,
        'status': severity,
        'color': color_map.get(severity, '#36a64f'),
        'metadata': metadata or {}
    }, send_to_slack=True)
