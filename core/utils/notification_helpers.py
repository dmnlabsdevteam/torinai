#!/usr/bin/env python3
"""
Notification Helpers for TorinAI
Comprehensive notification functions for all error types, successes, and informational events
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Import notification publisher
try:
    from core.utils.notification_publisher import publish_notification
    NOTIFICATIONS_AVAILABLE = True
except Exception as e:
    NOTIFICATIONS_AVAILABLE = False
    logger.warning(f"Notification publisher not available: {e}")


# ============================================================================
# TOOL EXECUTION NOTIFICATIONS
# ============================================================================

async def notify_tool_failure(
    tool_name: str,
    error: Exception,
    parameters: Dict[str, Any] = None,
    context: str = None
):
    """Send notification for tool execution failure"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    param_str = ""
    if parameters:
        param_preview = {k: (str(v)[:100] + "..." if len(str(v)) > 100 else v)
                        for k, v in parameters.items()}
        param_str = f"\n\n**Parameters:** ```{param_preview}```"

    context_str = f"\n\n**Context:** {context}" if context else ""

    await publish_notification({
        'id': f'tool_failure_{datetime.now().timestamp()}',
        'type': 'tool_failure',
        'title': f"🔧 Tool Execution Failed: {tool_name}",
        'message': f"**Error:** {str(error)}{param_str}{context_str}",
        'status': 'error',
        'color': '#F44336',
        'metadata': {
            "tool_name": tool_name,
            "error_type": type(error).__name__,
            "parameters": parameters or {}
        }
    }, send_to_slack=True)


async def notify_tool_success(
    tool_name: str,
    result: Any,
    execution_time: float = None,
    context: str = None
):
    """Send notification for successful tool execution (for important operations)"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    time_str = f"\n**Execution Time:** {execution_time:.2f}s" if execution_time else ""
    context_str = f"\n**Context:** {context}" if context else ""

    await publish_notification({
        'id': f'tool_success_{datetime.now().timestamp()}',
        'type': 'tool_success',
        'title': f"✅ Tool Executed Successfully: {tool_name}",
        'message': f"Operation completed successfully{time_str}{context_str}",
        'status': 'info',
        'color': '#36a64f',
        'metadata': {
            "tool_name": tool_name,
            "execution_time": execution_time
        }
    }, send_to_slack=True)


# ============================================================================
# DATABASE NOTIFICATIONS
# ============================================================================

async def notify_database_error(
    operation: str,
    error: Exception,
    database: str = "MySQL",
    context: Dict[str, Any] = None
):
    """Send notification for database operation failure"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    context_str = ""
    if context:
        context_preview = {k: (str(v)[:100] + "..." if len(str(v)) > 100 else v)
                          for k, v in context.items()}
        context_str = f"\n\n**Context:** ```{context_preview}```"

    await publish_notification({
        'id': f'db_error_{datetime.now().timestamp()}',
        'type': 'database_error',
        'title': f"🗄️ Database {operation.title()} Failed: {database}",
        'message': f"**Error:** {str(error)}{context_str}\n\n**Action Required:** Check database connectivity and logs",
        'status': 'critical',
        'color': '#880E4F',
        'metadata': {
            "database": database,
            "operation": operation,
            "error_type": type(error).__name__,
            "context": context or {}
        }
    }, send_to_slack=True)


async def notify_database_success(
    operation: str,
    database: str = "MySQL",
    details: str = None
):
    """Send notification for successful database operations"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    details_str = f"\n{details}" if details else ""

    await publish_notification({
        'id': f'db_success_{datetime.now().timestamp()}',
        'type': 'database_success',
        'title': f"✅ Database {operation.title()} Successful: {database}",
        'message': f"Operation completed successfully{details_str}",
        'status': 'info',
        'color': '#36a64f',
        'metadata': {
            "database": database,
            "operation": operation
        }
    }, send_to_slack=True)


# ============================================================================
# LEARNING SYSTEM NOTIFICATIONS
# ============================================================================

async def notify_learning_event(
    event_type: str,
    details: str,
    severity: str = "info",
    metadata: Dict[str, Any] = None
):
    """Send notification for learning system events"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    emoji_map = {
        "upgrade": "🚀",
        "improvement": "📈",
        "failure": "❌",
        "success": "✅",
        "validation": "🔍",
        "rollback": "⏪",
        "training": "🧠",
        "benchmark": "📊"
    }

    color_map = {
        "info": "#36a64f",
        "warning": "#FFA500",
        "error": "#F44336",
        "critical": "#880E4F"
    }

    emoji = emoji_map.get(event_type.lower(), "🧠")

    await publish_notification({
        'id': f'learning_{event_type}_{datetime.now().timestamp()}',
        'type': f'learning_{event_type}',
        'title': f"{emoji} Learning System: {event_type.title()}",
        'message': details,
        'status': severity,
        'color': color_map.get(severity, '#36a64f'),
        'metadata': metadata or {}
    }, send_to_slack=True)


# ============================================================================
# SECURITY NOTIFICATIONS
# ============================================================================

async def notify_security_event(
    event_type: str,
    severity: str,
    details: str,
    threat_info: Dict[str, Any] = None
):
    """Send notification for security events"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    emoji_map = {
        "threat_detected": "🚨",
        "attack_blocked": "🛡️",
        "vulnerability": "⚠️",
        "breach_attempt": "🔥",
        "audit": "🔍",
        "scan_complete": "✅",
        "threat_blocked": "🚫"
    }

    color_map = {
        "info": "#36a64f",
        "warning": "#FFA500",
        "error": "#F44336",
        "critical": "#880E4F"
    }

    emoji = emoji_map.get(event_type.lower(), "🔒")

    await publish_notification({
        'id': f'security_{event_type}_{datetime.now().timestamp()}',
        'type': f'security_{event_type}',
        'title': f"{emoji} Security Alert: {event_type.replace('_', ' ').title()}",
        'message': details,
        'status': severity,
        'color': color_map.get(severity, '#36a64f'),
        'metadata': threat_info or {}
    }, send_to_slack=True)


# ============================================================================
# GOVERNANCE NOTIFICATIONS
# ============================================================================

async def notify_governance_decision(
    decision_type: str,
    action: str,
    decision: str,
    details: str = None,
    metadata: Dict[str, Any] = None
):
    """Send notification for governance decisions"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    emoji_map = {
        "approved": "✅",
        "blocked": "🚫",
        "escalated": "⬆️",
        "queued": "⏳",
        "reviewed": "👀"
    }

    emoji = emoji_map.get(decision_type.lower(), "⚖️")
    details_str = f"\n\n{details}" if details else ""

    await publish_notification({
        'id': f'governance_{decision_type}_{datetime.now().timestamp()}',
        'type': f'governance_{decision_type}',
        'title': f"{emoji} Governance: {action}",
        'message': f"**Decision:** {decision}{details_str}",
        'status': 'warning' if decision_type == "blocked" else "info",
        'color': '#FFA500' if decision_type == "blocked" else '#36a64f',
        'metadata': metadata or {}
    }, send_to_slack=True)


# ============================================================================
# AUTONOMOUS COORDINATOR NOTIFICATIONS
# ============================================================================

async def notify_autonomous_event(
    event_type: str,
    details: str,
    severity: str = "info",
    metadata: Dict[str, Any] = None
):
    """Send notification for autonomous coordinator events"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    emoji_map = {
        "cycle_complete": "🔄",
        "task_executed": "✅",
        "error": "❌",
        "paused": "⏸️",
        "resumed": "▶️",
        "shutdown": "🛑",
        "started": "🚀",
        "decision": "🤔"
    }

    color_map = {
        "info": "#36a64f",
        "warning": "#FFA500",
        "error": "#F44336",
        "critical": "#880E4F"
    }

    emoji = emoji_map.get(event_type.lower(), "🤖")

    await publish_notification({
        'id': f'autonomous_{event_type}_{datetime.now().timestamp()}',
        'type': f'autonomous_{event_type}',
        'title': f"{emoji} Autonomous Coordinator: {event_type.replace('_', ' ').title()}",
        'message': details,
        'status': severity,
        'color': color_map.get(severity, '#36a64f'),
        'metadata': metadata or {}
    }, send_to_slack=True)


# ============================================================================
# MEMORY SYSTEM NOTIFICATIONS
# ============================================================================

async def notify_memory_event(
    event_type: str,
    details: str,
    severity: str = "info",
    metadata: Dict[str, Any] = None
):
    """Send notification for memory system events"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    emoji_map = {
        "storage_error": "❌",
        "retrieval_error": "⚠️",
        "storage_success": "✅",
        "compaction": "🗜️",
        "migration": "🔄"
    }

    color_map = {
        "info": "#36a64f",
        "warning": "#FFA500",
        "error": "#F44336",
        "critical": "#880E4F"
    }

    emoji = emoji_map.get(event_type.lower(), "🧠")

    await publish_notification({
        'id': f'memory_{event_type}_{datetime.now().timestamp()}',
        'type': f'memory_{event_type}',
        'title': f"{emoji} Memory System: {event_type.replace('_', ' ').title()}",
        'message': details,
        'status': severity,
        'color': color_map.get(severity, '#36a64f'),
        'metadata': metadata or {}
    }, send_to_slack=True)


# ============================================================================
# SERVICE NOTIFICATIONS
# ============================================================================

async def notify_service_error(
    service_name: str,
    error: Exception,
    context: str = None
):
    """Send notification for service errors"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    context_str = f"\n\n**Context:** {context}" if context else ""

    await publish_notification({
        'id': f'service_error_{datetime.now().timestamp()}',
        'type': 'service_error',
        'title': f"⚠️ Service Error: {service_name}",
        'message': f"**Error:** {str(error)}{context_str}",
        'status': 'error',
        'color': '#F44336',
        'metadata': {
            "service": service_name,
            "error_type": type(error).__name__
        }
    }, send_to_slack=True)


async def notify_service_status(
    service_name: str,
    status: str,
    details: str = None
):
    """Send notification for service status changes"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    emoji_map = {
        "started": "▶️",
        "stopped": "⏹️",
        "restarted": "🔄",
        "degraded": "⚠️",
        "healthy": "✅"
    }

    emoji = emoji_map.get(status.lower(), "ℹ️")
    details_str = f"\n{details}" if details else ""

    await publish_notification({
        'id': f'service_status_{datetime.now().timestamp()}',
        'type': f'service_{status}',
        'title': f"{emoji} Service {status.title()}: {service_name}",
        'message': f"Service status changed to: **{status}**{details_str}",
        'status': 'warning' if status in ['stopped', 'degraded'] else 'info',
        'color': '#FFA500' if status in ['stopped', 'degraded'] else '#36a64f',
        'metadata': {
            "service": service_name,
            "status": status
        }
    }, send_to_slack=True)


# ============================================================================
# API/NETWORK NOTIFICATIONS
# ============================================================================

async def notify_api_error(
    endpoint: str,
    error: Exception,
    request_details: Dict[str, Any] = None
):
    """Send notification for API errors"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    request_str = ""
    if request_details:
        request_preview = {k: (str(v)[:100] + "..." if len(str(v)) > 100 else v)
                          for k, v in request_details.items()}
        request_str = f"\n\n**Request:** ```{request_preview}```"

    await publish_notification({
        'id': f'api_error_{datetime.now().timestamp()}',
        'type': 'api_error',
        'title': f"🌐 API Error: {endpoint}",
        'message': f"**Error:** {str(error)}{request_str}",
        'status': 'error',
        'color': '#F44336',
        'metadata': {
            "endpoint": endpoint,
            "error_type": type(error).__name__,
            "request": request_details or {}
        }
    }, send_to_slack=True)


# ============================================================================
# GENERIC ERROR NOTIFICATION
# ============================================================================

async def notify_error(
    title: str,
    error: Exception,
    context: Dict[str, Any] = None,
    severity: str = "error"
):
    """Send generic error notification"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    context_str = ""
    if context:
        context_preview = {k: (str(v)[:100] + "..." if len(str(v)) > 100 else v)
                          for k, v in context.items()}
        context_str = f"\n\n**Context:** ```{context_preview}```"

    color_map = {
        "info": "#36a64f",
        "warning": "#FFA500",
        "error": "#F44336",
        "critical": "#880E4F"
    }

    await publish_notification({
        'id': f'error_{datetime.now().timestamp()}',
        'type': 'error',
        'title': f"❌ {title}",
        'message': f"**Error:** {str(error)}{context_str}",
        'status': severity,
        'color': color_map.get(severity, '#F44336'),
        'metadata': {
            "error_type": type(error).__name__,
            "context": context or {}
        }
    }, send_to_slack=True)


async def notify_success(
    title: str,
    message: str,
    metadata: Dict[str, Any] = None
):
    """Send generic success notification"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    await publish_notification({
        'id': f'success_{datetime.now().timestamp()}',
        'type': 'success',
        'title': f"✅ {title}",
        'message': message,
        'status': 'info',
        'color': '#36a64f',
        'metadata': metadata or {}
    }, send_to_slack=True)


async def notify_info(
    title: str,
    message: str,
    metadata: Dict[str, Any] = None
):
    """Send generic informational notification"""
    if not NOTIFICATIONS_AVAILABLE:
        return

    await publish_notification({
        'id': f'info_{datetime.now().timestamp()}',
        'type': 'info',
        'title': f"ℹ️ {title}",
        'message': message,
        'status': 'info',
        'color': '#36a64f',
        'metadata': metadata or {}
    }, send_to_slack=True)
