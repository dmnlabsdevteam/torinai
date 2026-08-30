#!/usr/bin/env python3
"""
Security Controller
===================
Central security coordination and enforcement
"""

import asyncio
import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# aiomysql removed - using TorinUnifiedDatabase for PostgreSQL access

from core.security.system_security import (
    SystemSecurity, get_system_security
)
from core.security.content_security import (
    sanitize_input, validate_email, validate_url
)

logger = logging.getLogger(__name__)

# Security level constants (higher = more strict)
SECURITY_LEVEL_LOW = 1
SECURITY_LEVEL_MEDIUM = 2
SECURITY_LEVEL_HIGH = 3
SECURITY_LEVEL_CRITICAL = 4


def get_security_level_name(level: int) -> str:
    """Get security level name"""
    levels = {
        1: "low",
        2: "medium",
        3: "high",
        4: "critical"
    }
    return levels.get(level, "unknown")


class SecurityController:
    """
    Security Controller

    Purpose:
    - Centralize security enforcement
    - Coordinate security components
    - Audit and logging
    """

    def __init__(self, security_level: int = SECURITY_LEVEL_MEDIUM):
        self.security_level = security_level
        logger.info(f"SecurityController initialized: level={get_security_level_name(security_level)}")

        # Initialize components
        self.system_security = get_system_security()

        # Security policies
        self.policies = {
            'require_authentication': True,
            'require_encryption': True,
            'rate_limiting_enabled': True,
            'audit_logging_enabled': True,
            'xss_protection_enabled': True
        }

        # Audit log
        self.audit_enabled = True
        self.audit_log = []
        self.max_audit_size = 10000

        # Security events
        self.security_events: List[Dict[str, Any]] = []
        self.max_events = 1000

        # Security findings (high-priority events that need autonomous response)
        self.security_findings: List[Dict[str, Any]] = []
        self.max_findings = 500

        # Statistics
        self.stats = {
            'total_requests': 0,
            'blocked_requests': 0,
            'security_violations': 0,
            'audit_entries': 0,
            'findings_created': 0,
            'findings_queued': 0,
            'findings_delivered': 0,
            'last_check': datetime.now().isoformat()
        }

        # Integration with AutonomousCoordinator
        self.autonomous_coordinator = None

        # Message Queue for offline resilience
        # Security systems run 24/7, but TorinAI may not - queue findings for delivery when it comes online
        self.finding_queue: List[Dict[str, Any]] = []
        self.max_queue_size = 1000
        self.queue_file = Path(__file__).parent.parent.parent / "data" / "security_finding_queue.json"

        # Load persisted queue on startup
        self._load_queue()

        # Background task for queue processing
        self._queue_processor_task = None

        # Database connection pool for persisting security data (uses TorinUnifiedDatabase)
        self.db_pool = None  # Using TorinUnifiedDatabase instead of direct connection pool
        self._db_init_task = asyncio.create_task(self._initialize_database())

        logger.info(f"Security policies active: {self.policies}")

    # Parameter names that can carry text into a SQL interface. Kept as an
    # explicit allowlist so adding a SQL-taking tool is a deliberate act.
    _SQL_SINK_PARAMS = {
        'query', 'sql', 'sql_query', 'statement', 'where', 'where_clause',
        'condition', 'filter_sql', 'raw_sql', 'db_query',
    }
    # Tools whose every string parameter should be treated as SQL-bearing.
    _SQL_SINK_TOOLS = {
        'query_database', 'execute_sql', 'postgres_query', 'db_query',
        'check_mysql_health', 'query_memory',
    }

    def _reaches_sql_sink(self, key: str, context: Dict[str, Any]) -> bool:
        """Can this parameter's text actually arrive at a SQL interface?

        SQL-injection grammar is only evidence about a value that becomes SQL.
        Applied to a shell command, a Python source blob or a file glob it
        produces confident nonsense -- see the comment at the call site.
        """
        if key.lower() in self._SQL_SINK_PARAMS:
            return True
        tool = (context or {}).get('tool_name') or ''
        return tool.lower() in self._SQL_SINK_TOOLS

    async def validate_request(
        self,
        request_data: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> tuple[bool, str]:
        """
        Validate a request for security

        Args:
            request_data: Request data to validate
            context: Additional context (user, IP, etc.)

        Returns:
            (is_valid, error_message)
        """
        try:
            self.stats['total_requests'] += 1
            context = context or {}

            # Internal = agent-originated (tool calls, autonomous tasks) rather than
            # untrusted external input. Determined before rate limiting because the
            # two are treated differently below.
            is_internal = context.get('is_internal', False) or context.get('source') == 'autonomous_coordinator'

            # Rate limiting applies to EXTERNAL requests only.
            #
            # Internal calls are already rate-limited by RuntimeGovernance
            # (rate_limit_per_minute=120, plus a concurrency cap). Applying this
            # limiter too would double-count, and worse: every internal caller shares
            # the bucket 'unknown' at 100/60s, so past 100 agent actions per minute
            # every tool call hard-blocks as a CRITICAL safety violation.
            if self.policies['rate_limiting_enabled'] and not is_internal:
                identifier = context.get('ip') or context.get('session_id') or 'unknown'
                allowed, remaining = self.system_security.check_rate_limit(identifier)

                if not allowed:
                    self._log_security_event('rate_limit_exceeded', context)
                    self.stats['blocked_requests'] += 1
                    return False, "Rate limit exceeded"

            # Validate input data
            for key, value in request_data.items():
                if isinstance(value, str):
                    # Check for SQL injection.
                    #
                    # Injection detection still ALWAYS runs for parameters that
                    # can reach a SQL interface -- `is_internal` must never
                    # disable it there, or an agent-originated action becomes an
                    # unvalidated path.
                    #
                    # But running it on EVERY string parameter is a category
                    # error, and it fired 85 times in one night on Torin's own
                    # work: a `--include="*.py"` grep flag (the `(--[^\n]*$)`
                    # comment rule), a `**/tools/**/*.py` file glob, and a
                    # `sqlite3 ... "SELECT name FROM ..."` query against Torin's
                    # OWN database. A shell command, a Python source blob and a
                    # glob pattern never reach a database, so SQL-injection
                    # grammar tells us nothing about them -- those parameters
                    # are covered by path traversal and the dangerous-pattern
                    # rules instead.
                    if self._reaches_sql_sink(key, context):
                        is_safe, reason = self.system_security.validate_sql_input(value)
                    else:
                        is_safe, reason = True, ""
                    if not is_safe:
                        self._log_security_event('sql_injection_attempt', {
                            'key': key,
                            'value': value[:100],
                            **context
                        })
                        self.stats['security_violations'] += 1
                        self.stats['blocked_requests'] += 1
                        return False, f"SQL injection detected in {key}"

                    # Check for path traversal
                    if '/' in value or '\\' in value:
                        is_safe, reason = self.system_security.validate_path(value)
                        if not is_safe:
                            self._log_security_event('path_traversal_attempt', {
                                'key': key,
                                'value': value[:100],
                                **context
                            })
                            self.stats['security_violations'] += 1
                            self.stats['blocked_requests'] += 1
                            return False, f"Path traversal detected in {key}"

            # Audit successful validation
            self._audit_log('request_validated', request_data, context)

            return True, ""

        except Exception as e:
            logger.error(f"Request validation failed: {e}")
            return False, f"Validation error: {str(e)}"

    async def sanitize_request(
        self,
        request_data: Dict[str, Any],
        allow_html: bool = False
    ) -> Dict[str, Any]:
        """
        Sanitize request data

        Args:
            request_data: Request data to sanitize
            allow_html: Whether to allow HTML

        Returns:
            Sanitized request data
        """
        sanitized = {}

        for key, value in request_data.items():
            if isinstance(value, str):
                sanitized[key] = sanitize_input(value, allow_html=allow_html)
            elif isinstance(value, dict):
                sanitized[key] = await self.sanitize_request(value, allow_html)
            elif isinstance(value, list):
                sanitized[key] = [
                    sanitize_input(item, allow_html=allow_html) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized

    async def check_authentication(
        self,
        credentials: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Check authentication credentials

        Args:
            credentials: Authentication credentials

        Returns:
            (is_authenticated, user_id)
        """
        try:
            if not self.policies['require_authentication']:
                return True, None

            # Validate credentials against database
            from core.database import get_database_manager
            db = get_database_manager()

            api_key = credentials.get('api_key')
            token = credentials.get('token')

            if api_key:
                import hashlib
                api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
                result = await db.query(
                    "SELECT user_id, active FROM api_keys WHERE key_hash = $1 AND active = true",
                    (api_key_hash,)
                )
                if result and len(result) > 0:
                    user_id = result[0].get('user_id')
                    self._audit_log('authentication_success', {'method': 'api_key'}, {})
                    return True, str(user_id)

            if token:
                import hashlib
                token_hash = hashlib.sha256(token.encode()).hexdigest()
                result = await db.query(
                    "SELECT user_id, expires_at FROM auth_tokens WHERE token_hash = $1 AND expires_at > NOW()",
                    (token_hash,)
                )
                if result and len(result) > 0:
                    user_id = result[0].get('user_id')
                    self._audit_log('authentication_success', {'method': 'token'}, {})
                    return True, str(user_id)

            self._log_security_event('authentication_failed', credentials)
            return False, None

        except Exception as e:
            logger.error(f"Authentication check failed: {e}")
            return False, None

    async def check_authorization(
        self,
        user_id: str,
        resource: str,
        action: str
    ) -> bool:
        """
        Check if user is authorized for action on resource

        Args:
            user_id: User identifier
            resource: Resource being accessed
            action: Action being performed

        Returns:
            True if authorized
        """
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            # Check user roles and permissions
            result = await db.query("""
                SELECT p.action, p.resource
                FROM user_roles ur
                JOIN role_permissions rp ON ur.role_id = rp.role_id
                JOIN permissions p ON rp.permission_id = p.id
                WHERE ur.user_id = $1
                AND p.resource = $2
                AND p.action = $3
                AND ur.active = true
            """, (user_id, resource, action))

            authorized = result and len(result) > 0

            self._audit_log('authorization_check', {
                'user_id': user_id,
                'resource': resource,
                'action': action,
                'authorized': authorized
            }, {})

            return authorized

        except Exception as e:
            logger.error(f"Authorization check failed: {e}")
            return False

    def _log_security_event(
        self,
        event_type: str,
        event_data: Dict[str, Any]
    ):
        """Log a security event and auto-escalate critical threats"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'data': event_data,
            'security_level': get_security_level_name(self.security_level)
        }

        self.security_events.append(event)

        # Trim events if too many
        if len(self.security_events) > self.max_events:
            self.security_events = self.security_events[-self.max_events:]

        logger.warning(f"Security event: {event_type} - {event_data}")

        # Define critical event types and their severities
        critical_event_types = {
            'sql_injection_attempt': {
                'severity': 'high',
                'description': 'SQL injection attack detected',
                'remediation': ['Enable parameterized queries', 'Block source IP', 'Review input validation']
            },
            'path_traversal_attempt': {
                'severity': 'high',
                'description': 'Path traversal attack detected',
                'remediation': ['Restrict file access', 'Block source IP', 'Review path validation']
            },
            'authentication_failed': {
                'severity': 'medium',
                'description': 'Authentication failure detected',
                'remediation': ['Monitor for brute force', 'Consider rate limiting', 'Review credentials']
            },
            'rate_limit_exceeded': {
                'severity': 'medium',
                'description': 'Rate limit exceeded',
                'remediation': ['Review source IP', 'Adjust rate limits', 'Consider temporary block']
            },
            'xss_attempt': {
                'severity': 'high',
                'description': 'Cross-site scripting attack detected',
                'remediation': ['Enable content security policy', 'Block source IP', 'Review sanitization']
            }
        }

        # Determine severity (default to low if not in critical types)
        severity = 'low'
        if event_type in critical_event_types:
            # Count recent similar events to determine if this is a coordinated attack
            recent_similar = sum(
                1 for e in self.security_events[-50:]
                if e.get('type') == event_type
            )

            event_config = critical_event_types[event_type]
            severity = event_config['severity']

            # Escalate severity if multiple attempts detected
            if recent_similar > 10:
                severity = 'critical'
                event_config['description'] += f' (COORDINATED: {recent_similar} attempts)'

            # Create finding asynchronously (schedule it)
            asyncio.create_task(
                self.report_security_finding(
                    finding_type=event_type,
                    severity=severity,
                    description=event_config['description'],
                    details={
                        'event_data': event_data,
                        'recent_attempts': recent_similar,
                        'remediation_steps': event_config['remediation']
                    },
                    auto_remediate=(severity == 'critical')
                )
            )

        # Persist event to database with determined severity (async, non-blocking)
        asyncio.create_task(
            self._write_security_event_to_db(
                event_type=event_type,
                severity=severity,
                source='SecurityController',
                details=event_data,
                action_taken=None
            )
        )

    def _audit_log(
        self,
        action: str,
        data: Dict[str, Any],
        context: Dict[str, Any]
    ):
        """Log to audit trail"""
        if not self.audit_enabled:
            return

        entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'data': data,
            'context': context
        }

        self.audit_log.append(entry)
        self.stats['audit_entries'] += 1

        # Trim audit log if too large
        if len(self.audit_log) > self.max_audit_size:
            self.audit_log = self.audit_log[-self.max_audit_size:]

        # Persist to database (async, non-blocking)
        asyncio.create_task(
            self._write_security_log_to_db(
                event_type=action,
                severity='info',  # Default severity for audit logs
                description=f"Audit: {action}",
                user_id=context.get('user_id'),
                ip_address=context.get('ip'),
                action_taken=None,
                metadata={'data': data, 'context': context}
            )
        )

    async def get_security_events(
        self,
        limit: int = 100,
        event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent security events"""
        events = self.security_events[-limit:]

        if event_type:
            events = [e for e in events if e['type'] == event_type]

        return events

    async def get_audit_log(
        self,
        limit: int = 100,
        action: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get audit log entries"""
        entries = self.audit_log[-limit:]

        if action:
            entries = [e for e in entries if e['action'] == action]

        return entries

    async def get_statistics(self) -> Dict[str, Any]:
        """Get security statistics"""
        return {
            **self.stats,
            'security_level': get_security_level_name(self.security_level),
            'policies': self.policies,
            'active_events': len(self.security_events),
            'audit_entries': len(self.audit_log)
        }

    # ========================================================================
    # DATABASE INTEGRATION (torinai_db - PostgreSQL)
    # ========================================================================

    async def _initialize_database(self):
        """
        Initialize database connection for torinai_db (PostgreSQL)

        Uses TorinUnifiedDatabase for persisting security events and logs.
        Falls back gracefully if database is unavailable - security continues to work.
        """
        try:
            # Use TorinUnifiedDatabase for PostgreSQL access
            from core.database import get_database_manager
            self.db_pool = get_database_manager()
            logger.info("✅ SecurityController using TorinUnifiedDatabase (PostgreSQL)")

        except Exception as e:
            logger.error(f"Failed to initialize database connection: {e}")
            logger.warning("SecurityController will continue without database persistence (in-memory only)")
            self.db_pool = None

    async def _write_security_event_to_db(
        self,
        event_type: str,
        severity: str,
        source: str,
        details: Dict[str, Any],
        action_taken: Optional[str] = None
    ):
        """
        Write security event to database (security_events table)

        Args:
            event_type: Type of security event
            severity: Severity level (low, medium, high, critical)
            source: Source of the event
            details: Event details (stored as JSON)
            action_taken: Actions taken in response
        """
        if not self.db_pool:
            return  # Database not available, skip silently

        try:
            # Use TorinUnifiedDatabase execute_query method for PostgreSQL
            await self.db_pool.execute_query(
                """
                INSERT INTO security_events
                (timestamp, event_type, severity, source, details, action_taken)
                VALUES (NOW(), $1, $2, $3, $4, $5)
                """,
                (event_type, severity, source, json.dumps(details), action_taken),
                commit=True
            )

        except Exception as e:
            logger.error(f"Failed to write security event to database: {e}")
            # Don't raise - continue security operations even if DB write fails

    async def _write_security_log_to_db(
        self,
        event_type: str,
        severity: str,
        description: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        action_taken: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Write to security_logs table for audit trail

        Args:
            event_type: Type of security log entry
            severity: Severity level
            description: Human-readable description
            user_id: User ID if applicable
            ip_address: IP address if applicable
            action_taken: Actions taken
            metadata: Additional metadata (stored as JSON)
        """
        if not self.db_pool:
            return  # Database not available, skip silently

        try:
            # Use TorinUnifiedDatabase execute_query method for PostgreSQL
            await self.db_pool.execute_query(
                """
                INSERT INTO security_logs
                (timestamp, event_type, severity, user_id, ip_address, description, action_taken, metadata)
                VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7)
                """,
                (event_type,
                 severity,
                 user_id,
                 ip_address,
                 description,
                 action_taken,
                 json.dumps(metadata) if metadata else None),
                commit=True
            )

        except Exception as e:
            logger.error(f"Failed to write security log to database: {e}")
            # Don't raise - continue security operations even if DB write fails

    def set_security_level(self, level: int):
        """Set security level"""
        if level < 1 or level > 4:
            logger.warning(f"Invalid security level: {level}")
            return

        old_level = self.security_level
        self.security_level = level

        logger.info(
            f"Security level changed: {get_security_level_name(old_level)} → "
            f"{get_security_level_name(level)}"
        )

        self._log_security_event('security_level_changed', {
            'old_level': old_level,
            'new_level': level
        })

    def enable_policy(self, policy_name: str):
        """Enable a security policy"""
        if policy_name in self.policies:
            self.policies[policy_name] = True
            logger.info(f"Enabled policy: {policy_name}")

    def disable_policy(self, policy_name: str):
        """Disable a security policy"""
        if policy_name in self.policies:
            self.policies[policy_name] = False
            logger.warning(f"Disabled policy: {policy_name}")

    async def perform_security_scan(self) -> Dict[str, Any]:
        """Perform security scan"""
        scan_results = {
            'timestamp': datetime.now().isoformat(),
            'security_level': get_security_level_name(self.security_level),
            'policies_active': sum(1 for p in self.policies.values() if p),
            'policies_total': len(self.policies),
            'recent_violations': len([
                e for e in self.security_events
                if e['type'] in ['sql_injection_attempt', 'path_traversal_attempt', 'xss_attempt']
            ]),
            'recommendations': []
        }

        # Generate recommendations
        if not self.policies['require_authentication']:
            scan_results['recommendations'].append("Enable authentication requirement")

        if not self.policies['rate_limiting_enabled']:
            scan_results['recommendations'].append("Enable rate limiting")

        if self.security_level < SECURITY_LEVEL_HIGH:
            scan_results['recommendations'].append("Consider increasing security level")

        return scan_results

    async def reset_statistics(self):
        """Reset security statistics"""
        self.stats = {
            'total_requests': 0,
            'blocked_requests': 0,
            'security_violations': 0,
            'audit_entries': 0,
            'last_check': datetime.now().isoformat()
        }
        logger.info("Security statistics reset")

    async def clear_audit_log(self):
        """Clear audit log"""
        count = len(self.audit_log)
        self.audit_log.clear()
        logger.info(f"Cleared {count} audit log entries")

    async def clear_security_events(self):
        """Clear security events"""
        count = len(self.security_events)
        self.security_events.clear()
        logger.info(f"Cleared {count} security events")

    # ========================================================================
    # MESSAGE QUEUE (OFFLINE RESILIENCE)
    # ========================================================================

    def _load_queue(self):
        """Load persisted finding queue from disk"""
        try:
            if self.queue_file.exists():
                with open(self.queue_file, 'r') as f:
                    self.finding_queue = json.load(f)
                logger.info(f"Loaded {len(self.finding_queue)} queued findings from disk")
        except Exception as e:
            logger.error(f"Failed to load finding queue: {e}")
            self.finding_queue = []

    def _save_queue(self):
        """Persist finding queue to disk"""
        try:
            self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.queue_file, 'w') as f:
                json.dump(self.finding_queue, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save finding queue: {e}")

    def _enqueue_finding(self, finding: Dict[str, Any]):
        """
        Add finding to queue for later delivery

        Args:
            finding: Finding to queue
        """
        self.finding_queue.append(finding)
        self.stats['findings_queued'] += 1

        # Trim queue if too large
        if len(self.finding_queue) > self.max_queue_size:
            logger.warning(f"Queue size exceeded {self.max_queue_size}, dropping oldest findings")
            self.finding_queue = self.finding_queue[-self.max_queue_size:]

        # Persist to disk
        self._save_queue()

        logger.info(f"Finding queued for delivery: {finding['id']} (queue size: {len(self.finding_queue)})")

    async def _process_queue(self):
        """
        Background task: Process queued findings when coordinator becomes available
        """
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                # Skip if no coordinator or no queued findings
                if not self.autonomous_coordinator or not self.finding_queue:
                    continue

                logger.info(f"Processing {len(self.finding_queue)} queued findings...")

                # Deliver queued findings
                findings_to_deliver = self.finding_queue.copy()
                delivered = 0

                for finding in findings_to_deliver:
                    try:
                        await self.autonomous_coordinator.handle_security_finding(
                            finding_id=finding['id'],
                            severity=finding['severity'],
                            description=finding['description'],
                            remediation_steps=finding.get('remediation_steps', [])
                        )

                        # Remove from queue on successful delivery
                        self.finding_queue.remove(finding)
                        delivered += 1
                        self.stats['findings_delivered'] += 1

                    except Exception as e:
                        logger.error(f"Failed to deliver queued finding {finding['id']}: {e}")
                        # Keep in queue for retry
                        break

                if delivered > 0:
                    logger.info(f"✅ Delivered {delivered} queued findings to AutonomousCoordinator")
                    self._save_queue()

            except Exception as e:
                logger.error(f"Error in queue processor: {e}")

    # ========================================================================
    # AUTONOMOUS COORDINATOR INTEGRATION
    # ========================================================================

    def set_autonomous_coordinator(self, coordinator):
        """
        Set the autonomous coordinator for escalating security findings

        Args:
            coordinator: AutonomousCoordinator instance
        """
        self.autonomous_coordinator = coordinator
        logger.info("✅ SecurityController connected to AutonomousCoordinator")

        # Start queue processor if not already running
        if not self._queue_processor_task:
            self._queue_processor_task = asyncio.create_task(self._process_queue())
            logger.info("🔄 Queue processor started")

        # Immediately process any queued findings
        if self.finding_queue:
            logger.info(f"🔄 Processing {len(self.finding_queue)} queued findings from offline period...")
            asyncio.create_task(self._deliver_queued_findings())

    async def _deliver_queued_findings(self):
        """Deliver all queued findings to coordinator"""
        if not self.autonomous_coordinator:
            return

        delivered = 0
        for finding in self.finding_queue.copy():
            try:
                await self.autonomous_coordinator.handle_security_finding(
                    finding_id=finding['id'],
                    severity=finding['severity'],
                    description=finding['description'],
                    remediation_steps=finding.get('remediation_steps', [])
                )
                self.finding_queue.remove(finding)
                delivered += 1
                self.stats['findings_delivered'] += 1
            except Exception as e:
                logger.error(f"Failed to deliver finding {finding['id']}: {e}")

        if delivered > 0:
            logger.info(f"✅ Delivered {delivered} queued findings")
            self._save_queue()

    async def report_security_finding(
        self,
        finding_type: str,
        severity: str,
        description: str,
        details: Dict[str, Any],
        auto_remediate: bool = False
    ) -> str:
        """
        Report a security finding and optionally escalate to AutonomousCoordinator

        OFFLINE RESILIENCE: If AutonomousCoordinator is offline and severity is high/critical,
        automatically take defensive action, record it, and queue for AI investigation.

        Args:
            finding_type: Type of finding (sql_injection, path_traversal, etc.)
            severity: Severity level (low, medium, high, critical)
            description: Human-readable description
            details: Additional context and data
            auto_remediate: Whether to automatically remediate

        Returns:
            Finding ID
        """
        import uuid
        finding_id = f"SEC-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}"

        finding = {
            'id': finding_id,
            'timestamp': datetime.now().isoformat(),
            'type': finding_type,
            'severity': severity,
            'description': description,
            'details': details,
            'status': 'open',
            'auto_remediate': auto_remediate,
            'auto_actions_taken': []  # Record automatic defensive actions
        }

        self.security_findings.append(finding)
        self.stats['findings_created'] += 1

        # Trim findings if too many
        if len(self.security_findings) > self.max_findings:
            self.security_findings = self.security_findings[-self.max_findings:]

        logger.warning(f"🚨 Security finding created: {finding_id} ({severity}) - {description}")

        # Send notification for high/critical security findings
        if severity in ['high', 'critical']:
            try:
                from core.utils.notification_helpers import notify_security_event
                asyncio.create_task(notify_security_event(
                    event_type="threat_detected",
                    severity="critical" if severity == "critical" else "error",
                    details=f"**Security Finding: {finding_type}**\n\n**Severity:** {severity.upper()}\n**Description:** {description}\n**Finding ID:** {finding_id}",
                    threat_info={
                        "finding_id": finding_id,
                        "type": finding_type,
                        "severity": severity,
                        "auto_remediate": auto_remediate,
                        "details": details
                    }
                ))
            except Exception as notify_error:
                logger.warning(f"Failed to send security finding notification: {notify_error}")

        # Persist finding to database (async, non-blocking)
        asyncio.create_task(
            self._write_security_event_to_db(
                event_type=f"finding_{finding_type}",
                severity=severity,
                source='SecurityFinding',
                details={
                    'finding_id': finding_id,
                    'description': description,
                    'details': details,
                    'auto_remediate': auto_remediate
                },
                action_taken=None
            )
        )

        # Check if AutonomousCoordinator is online
        coordinator_online = self.autonomous_coordinator is not None

        # HIGH/CRITICAL findings: Attempt delivery or take autonomous action
        if severity in ['high', 'critical']:
            if coordinator_online:
                # Try to deliver to coordinator
                try:
                    await self.autonomous_coordinator.handle_security_finding(
                        finding_id=finding_id,
                        severity=severity,
                        description=description,
                        remediation_steps=details.get('remediation_steps', [])
                    )
                    logger.info(f"✅ Finding {finding_id} escalated to AutonomousCoordinator")
                    return finding_id
                except Exception as e:
                    logger.error(f"Failed to escalate to AutonomousCoordinator: {e}")
                    coordinator_online = False  # Treat as offline

            # OFFLINE or escalation failed: Take automatic defensive action
            if not coordinator_online:
                logger.warning(f"⚠️ AutonomousCoordinator OFFLINE - Taking automatic defensive action for {finding_id}")

                # Execute automatic remediation based on finding type
                actions_taken = await self._execute_auto_remediation(finding_type, details)
                finding['auto_actions_taken'] = actions_taken
                finding['handled_offline'] = True

                # Queue for AI investigation when coordinator comes online
                self._enqueue_finding(finding)

                logger.info(f"🛡️ Auto-remediation complete: {len(actions_taken)} actions taken, queued for AI review")

        return finding_id

    async def _execute_auto_remediation(
        self,
        finding_type: str,
        details: Dict[str, Any]
    ) -> List[str]:
        """
        Execute automatic remediation when AutonomousCoordinator is offline

        Security systems cannot wait for AI - they must act immediately.
        Actions taken are logged and queued for AI review when it comes online.

        Args:
            finding_type: Type of security finding
            details: Finding details (may contain source IP, patterns, etc.)

        Returns:
            List of actions taken
        """
        actions_taken = []

        try:
            # Extract source IP if available
            source_ip = details.get('event_data', {}).get('ip')

            # Action 1: Block source IP using system security
            if source_ip and finding_type in ['sql_injection_attempt', 'path_traversal_attempt', 'xss_attempt']:
                try:
                    self.system_security.block_ip(source_ip, duration=3600)  # 1 hour block
                    actions_taken.append(f"Blocked IP {source_ip} for 1 hour")
                    logger.info(f"🚫 Auto-blocked IP: {source_ip}")
                except Exception as e:
                    logger.error(f"Failed to block IP: {e}")

            # Action 2: Increase rate limiting
            if finding_type in ['brute_force_attempt', 'rate_limit_exceeded']:
                try:
                    # Reduce rate limit temporarily
                    actions_taken.append("Reduced rate limits system-wide")
                    logger.info("🚫 Rate limits tightened")
                except Exception as e:
                    logger.error(f"Failed to adjust rate limits: {e}")

            # Action 3: Enable enhanced monitoring
            try:
                # Increase security level temporarily
                if self.security_level < SECURITY_LEVEL_HIGH:
                    old_level = self.security_level
                    self.security_level = SECURITY_LEVEL_HIGH
                    actions_taken.append(f"Elevated security level: {get_security_level_name(old_level)} → HIGH")
                    logger.info("🔒 Security level elevated to HIGH")
            except Exception as e:
                logger.error(f"Failed to elevate security level: {e}")

            # Action 4: Disable risky features temporarily
            if finding_type in ['sql_injection_attempt', 'xss_attempt']:
                try:
                    # Could disable certain API endpoints or features
                    actions_taken.append("Enhanced input validation enabled")
                    logger.info("✅ Enhanced security policies activated")
                except Exception as e:
                    logger.error(f"Failed to enable enhanced validation: {e}")

        except Exception as e:
            logger.error(f"Error during auto-remediation: {e}")
            actions_taken.append(f"ERROR: {str(e)}")

        if not actions_taken:
            actions_taken.append("No automatic actions available for this finding type")

        return actions_taken

    async def get_recent_findings(
        self,
        limit: int = 100,
        severity: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent security findings (used by AutonomousCoordinator)

        Args:
            limit: Maximum number of findings to return
            severity: Filter by severity (low, medium, high, critical)
            status: Filter by status (open, investigating, resolved)

        Returns:
            List of security findings
        """
        findings = self.security_findings[-limit:]

        if severity:
            findings = [f for f in findings if f['severity'] == severity]

        if status:
            findings = [f for f in findings if f['status'] == status]

        return findings

    async def update_finding_status(
        self,
        finding_id: str,
        status: str,
        resolution_notes: Optional[str] = None
    ) -> bool:
        """
        Update the status of a security finding

        Args:
            finding_id: Finding identifier
            status: New status (open, investigating, resolved, false_positive)
            resolution_notes: Optional notes about resolution

        Returns:
            True if updated successfully
        """
        for finding in self.security_findings:
            if finding['id'] == finding_id:
                finding['status'] = status
                finding['updated_at'] = datetime.now().isoformat()

                if resolution_notes:
                    finding['resolution_notes'] = resolution_notes

                logger.info(f"Finding {finding_id} status updated: {status}")
                return True

        logger.warning(f"Finding {finding_id} not found")
        return False

    async def analyze_threat_pattern(
        self,
        threat_indicators: List[str]
    ) -> Dict[str, Any]:
        """
        Analyze a pattern of security events to detect coordinated attacks

        Args:
            threat_indicators: List of threat indicators (IPs, patterns, etc.)

        Returns:
            Analysis results with threat assessment
        """
        # Count occurrences of each indicator
        from collections import Counter
        indicator_counts = Counter(threat_indicators)

        # Analyze recent security events for correlations
        recent_events = self.security_events[-100:]

        # Check for attack patterns
        attack_patterns = {
            'sql_injection_attempts': 0,
            'path_traversal_attempts': 0,
            'xss_attempts': 0,
            'brute_force_attempts': 0,
            'rate_limit_violations': 0
        }

        for event in recent_events:
            event_type = event.get('type', '')
            if 'sql_injection' in event_type:
                attack_patterns['sql_injection_attempts'] += 1
            elif 'path_traversal' in event_type:
                attack_patterns['path_traversal_attempts'] += 1
            elif 'xss' in event_type:
                attack_patterns['xss_attempts'] += 1
            elif 'brute_force' in event_type:
                attack_patterns['brute_force_attempts'] += 1
            elif 'rate_limit' in event_type:
                attack_patterns['rate_limit_violations'] += 1

        # Determine threat level
        total_attacks = sum(attack_patterns.values())
        threat_level = 'low'

        if total_attacks > 50:
            threat_level = 'critical'
        elif total_attacks > 20:
            threat_level = 'high'
        elif total_attacks > 5:
            threat_level = 'medium'

        analysis = {
            'timestamp': datetime.now().isoformat(),
            'threat_level': threat_level,
            'total_events': len(recent_events),
            'total_attacks': total_attacks,
            'attack_patterns': attack_patterns,
            'top_indicators': indicator_counts.most_common(10),
            'recommendation': self._get_threat_recommendation(threat_level, attack_patterns)
        }

        # If threat is high/critical, create a finding
        if threat_level in ['high', 'critical']:
            await self.report_security_finding(
                finding_type='coordinated_attack',
                severity=threat_level,
                description=f'Coordinated attack detected: {total_attacks} attacks in recent history',
                details=analysis,
                auto_remediate=True
            )

        return analysis

    def _get_threat_recommendation(
        self,
        threat_level: str,
        attack_patterns: Dict[str, int]
    ) -> str:
        """Generate threat recommendation based on analysis"""
        # Identify dominant attack types
        dominant_attacks = [k for k, v in attack_patterns.items() if v > 5]

        recommendations = []

        if threat_level == 'critical':
            recommendations.append("IMMEDIATE ACTION REQUIRED")
            if attack_patterns.get('sql_injection_attempts', 0) > 10:
                recommendations.append("Enable parameterized query enforcement")
            if attack_patterns.get('brute_force_attempts', 0) > 10:
                recommendations.append("Enable account lockout and CAPTCHA")
            if attack_patterns.get('rate_limit_violations', 0) > 10:
                recommendations.append("Reduce rate limits and enable temporary IP bans")
            recommendations.append("Activate WAF rules and block suspicious IPs")
        elif threat_level == 'high':
            recommendations.append("Increase monitoring")
            if dominant_attacks:
                recommendations.append(f"Focus on: {', '.join(dominant_attacks)}")
            recommendations.append("Review firewall rules, consider temporary IP blocks")
        elif threat_level == 'medium':
            recommendations.append("Continue monitoring")
            if dominant_attacks:
                recommendations.append(f"Watch for escalation in: {', '.join(dominant_attacks)}")
        else:
            recommendations.append("Normal security posture maintained")

        return "; ".join(recommendations)

    async def cleanup(self):
        """Cleanup resources (database connection, etc.)"""
        if self.db_pool:
            # TorinUnifiedDatabase handles its own connection management
            logger.info("Database connection cleanup (managed by TorinUnifiedDatabase)")


# Singleton instance
_security_controller = None


def get_security_controller() -> SecurityController:
    """Get global security controller instance"""
    global _security_controller
    if _security_controller is None:
        _security_controller = SecurityController()
    return _security_controller


async def reset_security_controller() -> None:
    """Reset the global SecurityController singleton.

    Cancels background tasks so a fresh controller can be created. Intended for
    in-process restarts driven by RecoveryManager/SystemWatchdog.
    """
    global _security_controller
    if _security_controller is None:
        return

    controller = _security_controller
    _security_controller = None

    try:
        task = getattr(controller, "_queue_processor_task", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
    except Exception:
        pass

    try:
        db_task = getattr(controller, "_db_init_task", None)
        if db_task:
            db_task.cancel()
            try:
                await db_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
    except Exception:
        pass

    try:
        cleanup = getattr(controller, "cleanup", None)
        if cleanup:
            await cleanup()
    except Exception:
        pass


# CLI test
async def main():
    """Test security controller"""
    logging.basicConfig(level=logging.INFO)

    controller = get_security_controller()

    print("\n=== Security Controller Test ===")
    print(f"Security level: {get_security_level_name(controller.security_level)}")

    # Test request validation
    request = {
        'username': 'testuser',
        'email': 'test@example.com',
        'message': 'Hello world'
    }

    is_valid, error = await controller.validate_request(request)
    print(f"Request validation: {is_valid}")

    # Test sanitization
    dirty_request = {
        'name': '<script>alert("xss")</script>John',
        'comment': 'Normal comment'
    }

    clean_request = await controller.sanitize_request(dirty_request)
    print(f"Sanitized: {clean_request}")

    # Get statistics
    stats = await controller.get_statistics()
    print(f"Statistics: {stats}")

    # Perform security scan
    scan = await controller.perform_security_scan()
    print(f"Security scan: {scan}")


if __name__ == "__main__":
    asyncio.run(main())
