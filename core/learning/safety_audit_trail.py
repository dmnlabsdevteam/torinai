#!/usr/bin/env python3
"""
Safety Audit Trail
========================
Maintains comprehensive audit trail of safety-related events

Tracks ~6 months of safety events

Features:
- Safety event logging
- Violation tracking
- Decision recording
- Escalation tracking
- Audit reports
- Compliance tracking

Purpose:
- Safety compliance
- Incident analysis
- Pattern recognition
- Accountability
"""

import asyncio
import logging
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum
from pathlib import Path


# Get logger without color codes for production
def get_logger(name: str) -> logging.Logger:
    """Get logger, handling color codes if needed"""
    if hasattr(logging, 'getLogger'):
        # Production: use standard logger
        return logging.getLogger(name)
    else:
        # Development: use custom logger with color support
        return logging.getLogger(name) or logging.getLogger("safety_audit")

logger = get_logger(__name__)


# Singleton instance
_audit_trail = None


class SafetyEventType(Enum):
    """Types of safety events"""
    VIOLATION = "violation"
    ESCALATION = "escalation"
    DECISION = "decision"
    WARNING = "warning"
    # BLOCKED_ACTION and REQUIRES_APPROVAL were referenced by 11 call sites but
    # never defined, so every attempt to record a BLOCK raised AttributeError
    # before record_event() was entered — while approvals recorded normally.
    # The audit trail was structurally incapable of logging the one event class
    # that matters most.
    BLOCKED_ACTION = "blocked_action"
    REQUIRES_APPROVAL = "requires_approval"
    BOUNDARY_CHECK = "boundary_check"
    DEPLOYMENT = "deployment"
    CODE_CHANGE = "code_change"
    LEARNING_CYCLE = "learning_cycle"
    GOVERNANCE = "governance"
    REDTEAM = "redteam"
    ROLLBACK = "rollback"
    INCIDENT = "incident"


@dataclass
class SafetyEvent:
    """Safety event record"""
    event_id: str
    event_type: SafetyEventType
    severity: str  # "low", "medium", "high", "critical"

    # Event details
    description: str
    action: str
    outcome: str

    # Context
    component: str = "unknown"
    subsystem: str = "unknown"

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)


class SafetyAuditTrail:
    """
    Safety audit trail for tracking all safety-related events

    Maintains comprehensive log of safety events
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        # retention_days is 180; /tmp is purged by the OS, so the trail could
        # never actually hold six months of events.
        self.audit_dir = self.config.get(
            "audit_dir",
            os.getenv("TORIN_AUDIT_DIR", str(Path(__file__).resolve().parents[2] / "data" / "audit")),
        )
        self.retention_days = self.config.get("retention_days", 180)  # 6 months

        # Event storage
        self.events: List[SafetyEvent] = []

        # Statistics
        self.statistics = {
            "total_events": 0,
            "violations": 0,
            "escalations": 0,
            "decisions": 0,
            "warnings": 0,
        }

        # Ensure audit directory exists
        Path(self.audit_dir).mkdir(parents=True, exist_ok=True)

        logger.info("SafetyAuditTrail initialized")

    async def record_event(
        self,
        event_type: SafetyEventType,
        severity: str,
        description: str,
        action: str,
        outcome: str,
        component: str,
        context: Dict[str, Any] = None,
        details: Dict[str, Any] = None,
    ):
        """
        Record a safety event.

        All descriptive fields are REQUIRED by design. Defaulting them would let
        an incomplete call record an event with invented values — an audit trail
        that fabricates is worse than one that fails loudly.

        Args:
            event_type: Type of event ("violation", "escalation", "decision")
            severity: Severity level
            description: Event description
            action: Action taken
            outcome: Result of action
            component: Component involved
            context: Additional context
            details: Alias for context (for backwards compatibility)
        """
        # Merge details into context (details is an alias)
        merged_context = {}
        if context:
            merged_context.update(context)
        if details:
            merged_context.update(details)
        
        event = SafetyEvent(
            event_id=f"{event_type.value}_{datetime.now().timestamp()}",
            event_type=event_type,
            severity=severity,
            description=description,
            action=action,
            outcome=outcome,
            component=component,
            context=merged_context
        )

        # Add to events list (in-memory)
        self.events.append(event)

        # Update statistics
        self._update_stats(event_type)

        # Persist to file
        await self._persist_event(event)

        # Log event (to console)
        await self._log_event(event)

        logger.info(f"Safety event recorded: {event.event_id}")

    async def record_violation(
        self,
        action: str,
        severity: str,
        description: str,
        component: str,
        context: Dict[str, Any] = None
    ):
        """Record a safety violation"""
        await self.record_event(
            event_type=SafetyEventType.VIOLATION,
            severity=severity or "high",
            description=f"Violation: {description}",
            action=action,
            outcome="blocked",
            component=component,
            context={
                "violation": True,
                "blocked": datetime.now().isoformat(),
                "action_attempted": action,
                "severity": severity,
                "component": component
            }
        )

    async def record_escalation(
        self,
        action: str,
        reason: str,
        escalated_to: str,
        context: Dict[str, Any] = None
    ):
        """Record a safety escalation"""
        await self.record_event(
            event_type=SafetyEventType.ESCALATION,
            severity="medium",
            description=f"Escalated: {reason}",
            action=action,
            outcome=f"escalated_to_{escalated_to}",
            component=escalated_to,
            context={
                "escalated_to": escalated_to,
                "reason": reason,
                "action": action,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def record_decision(
        self,
        action: str,
        decision: str,
        rationale: str,
        context: Dict[str, Any] = None
    ):
        """Record a governance decision"""
        await self.record_event(
            event_type=SafetyEventType.DECISION,
            severity="low",
            description=f"Decision: {rationale}",
            action=action,
            outcome=decision,
            component="governance",
            context={
                "decision": decision,
                "rationale": rationale,
                **context
            }
        )

    async def record_deployment(
        self,
        deployment_id: str,
        component: str,
        success: bool,
        details: Dict[str, Any]
    ):
        """Record a deployment event"""
        await self.record_event(
            event_type=SafetyEventType.DEPLOYMENT,
            severity="medium",
            description=f"Deployment: {deployment_id}",
            action="deploy",
            outcome="success" if success else "failed",
            component=component,
            context={
                "deployment_id": deployment_id,
                "success": success,
                "details": details,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def record_boundary_check(
        self,
        action: str,
        safety_level: str,
        violations: List[str]
    ):
        """Record a safety boundary check"""
        await self.record_event(
            event_type=SafetyEventType.BOUNDARY_CHECK,
            severity="low",
            description=f"Boundary check: {action}",
            action=action,
            outcome=safety_level,
            component="safety_boundaries",
            context={
                "safety_level": safety_level,
                "violations": violations,
                "violations_count": len(violations)
            }
        )

    async def _persist_event(
        self,
        event: SafetyEvent
    ):
        """Persist event to JSON file"""
        event_dict = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "severity": event.severity,
            "description": event.description,
            "action": event.action,
            "outcome": event.outcome,
            "component": event.component,
            "timestamp": event.timestamp.isoformat()
        }

        # Add context if available
        if event.context:
            event_dict["context"] = event.context

        # Write to audit log file (append mode)
        def _json_default(obj):
            """Fallback serializer: enums → .value, everything else → str."""
            if hasattr(obj, 'value'):
                return obj.value
            return str(obj)

        try:
            audit_file = Path(self.audit_dir) / f"audit_{datetime.now().date()}.jsonl"
            with open(audit_file, 'a') as f:
                f.write(json.dumps(event_dict, default=_json_default) + '\n')
        except Exception as e:
            logger.error(f"Failed to persist event: {e}")

    async def _log_event(
        self,
        event: SafetyEvent
    ):
        """Log event to console/logger"""
        # Determine log level based on severity
        # Callers pass "HIGH"/"MEDIUM"/"LOW"; these comparisons were lowercase,
        # so every HIGH-severity safety event was logged at INFO.
        _sev = (event.severity or "").lower()
        if _sev == "critical":
            log_func = logger.critical
        elif _sev == "high":
            log_func = logger.error
        elif _sev == "medium":
            log_func = logger.warning
        else:
            log_func = logger.info

        # Log event
        log_func(f"[{event.event_type.value.upper()}] {event.description}")
        log_func(f"  Action: {event.action}")
        log_func(f"  Outcome: {event.outcome}")
        log_func(f"  Component: {event.component}")

    def generate_report(self) -> str:
        """Generate safety audit report"""
        report = f"""# Safety Audit Report

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary

- Total Events: {self.statistics['total_events']}
- Violations: {self.statistics['violations']}
- Escalations: {self.statistics['escalations']}
- Decisions: {self.statistics['decisions']}
- Warnings: {self.statistics['warnings']}


"""
        return report

    def _format_event(
        self,
        event: SafetyEvent
    ) -> str:
        """Format event for display"""
        severity_icons = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡"
        }

        icon = severity_icons.get(event.severity, "•")
        badge = f" **[{event.severity.upper()}]**" if (event.severity or "").lower() != "low" else ""

        result = f"### {icon} {event.event_type.value.upper()}{badge}\n"
        result += f"**Time:** {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
        result += f"**Action:** {event.action}\n"
        result += f"**Outcome:** {event.outcome}\n"
        result += f"**Component:** {event.component}\n"

        if event.context:
            result += "**Context:**\n```json\n"
            result += json.dumps(event.context, indent=2)
            result += "\n```\n"

        result += "\n"

        return result

    async def save_report(
        self,
        filename: str
    ):
        """Save audit report to file"""
        # Generate report
        report = self.generate_report()

        # Add recent events
        if self.events:
            report += "## Recent Events\n\n"
            for event in self.events[-20:]:  # Last 20 events
                report += self._format_event(event)

        # Save to file
        report_path = Path(self.audit_dir) / filename
        with open(report_path, 'w') as f:
            f.write(report)

        logger.info(f"Audit report saved: {report_path}")

    def _update_stats(
        self,
        event_type: SafetyEventType
    ):
        """Update statistics"""
        self.statistics["total_events"] += 1

        if event_type == SafetyEventType.VIOLATION:
            self.statistics["violations"] += 1
        elif event_type == SafetyEventType.ESCALATION:
            self.statistics["escalations"] += 1
        elif event_type == SafetyEventType.DECISION:
            self.statistics["decisions"] += 1
        elif event_type == SafetyEventType.WARNING:
            self.statistics["warnings"] += 1

        logger.debug(f"Stats updated: {self.statistics}")

    def get_events(
        self,
        event_type: SafetyEventType = None,
        since: datetime = None
    ) -> List[SafetyEvent]:
        """Get events from audit trail"""
        if not self.events:
            return []

        # Filter by type
        if event_type:
            events = [e for e in self.events if e.event_type == event_type]
        else:
            events = self.events

        # Filter by time
        if since:
            events = [e for e in events if e.timestamp >= since]

        return events

    async def cleanup_old_events(self):
        """Clean up events older than retention period"""
        cutoff = datetime.now() - timedelta(days=self.retention_days)

        # Filter events
        self.events = [e for e in self.events if e.timestamp >= cutoff]

        logger.info(f"Cleaned up events older than {self.retention_days} days")

    def get_violations(
        self,
        since: datetime = None
    ) -> List[SafetyEvent]:
        """Get all violations"""
        return self.get_events(SafetyEventType.VIOLATION, since)

    async def analyze_patterns(
        self,
        lookback_days: int = 7
    ):
        """Analyze patterns in safety events"""
        if not self.events:
            return

        # Get recent events
        cutoff = datetime.now() - timedelta(days=lookback_days)
        recent = [e for e in self.events if e.timestamp >= cutoff]

        # Group by type
        by_type = {}
        for event in recent:
            event_type = event.event_type.value
            if event_type not in by_type:
                by_type[event_type] = []
            by_type[event_type].append(event)

        # Log patterns
        logger.info(f"Pattern analysis (last {lookback_days} days):")
        for event_type, events in by_type.items():
            logger.info(f"  {event_type}: {len(events)} events")

    def get_statistics(self) -> Dict[str, Any]:
        """Get audit trail statistics"""
        return {
            "total_events": len(self.events),
            "violations": sum(1 for e in self.events if e.event_type == SafetyEventType.VIOLATION),
            "escalations": sum(1 for e in self.events if e.event_type == SafetyEventType.ESCALATION),
            "decisions": sum(1 for e in self.events if e.event_type == SafetyEventType.DECISION),
            "warnings": sum(1 for e in self.events if e.event_type == SafetyEventType.WARNING)
        }


# Singleton accessor
_audit_trail_instance = None


def get_safety_audit_trail() -> SafetyAuditTrail:
    """Get global safety audit trail instance"""
    global _audit_trail_instance
    if _audit_trail_instance is None:
        _audit_trail_instance = SafetyAuditTrail()
    return _audit_trail_instance


# CLI test
if __name__ == "__main__":
    trail = get_safety_audit_trail()

    # Test recording events
    asyncio.run(trail.record_violation(
        action="test_action",
        severity="high",
        description="Test violation for demo",
        component="test"
    ))

    asyncio.run(trail.record_decision(
        action="deploy_model",
        decision="approved",
        rationale="Safety checks passed",
        context={"model": "test_v1"}
    ))

    asyncio.run(trail.record_escalation(
        action="modify_safety",
        reason="Requires human approval",
        escalated_to="safety_team"
    ))

    print("\n=== Safety Audit Trail ===")
    print(f"Total events: {trail.get_statistics()}")
    print(f"Recent violations: {len(trail.get_violations())}")
    print(f"Audit directory: {trail.audit_dir}")
    print(f"\nReport:\n{trail.generate_report()}")
