#!/usr/bin/env python3
"""
Security Audit Worker
=====================
Continuous security monitoring and auditing for TorinAI system

Features:
- Real-time security event monitoring
- Vulnerability detection
- Compliance checking
- Automated security reports
- Integration with governance and safety systems
"""

import logging
import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum

from core.observability import failure_record

logger = logging.getLogger(__name__)


class AuditSeverity(Enum):
    """Security audit severity levels"""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AuditCategory(Enum):
    """Security audit categories"""
    ACCESS_CONTROL = "access_control"
    DATA_INTEGRITY = "data_integrity"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ENCRYPTION = "encryption"
    NETWORK_SECURITY = "network_security"
    CODE_SECURITY = "code_security"
    CONFIGURATION = "configuration"
    COMPLIANCE = "compliance"
    ANOMALY_DETECTION = "anomaly_detection"


@dataclass
class SecurityAuditFinding:
    """Individual security audit finding"""
    finding_id: str
    category: AuditCategory
    severity: AuditSeverity
    title: str
    description: str
    affected_components: List[str] = field(default_factory=list)
    remediation: Optional[str] = None
    # What "resolved" means and what the agent may do to get there. Prose
    # remediation ("Check if this component is still active and logging") gave
    # the agent nothing to aim at, so it guessed. See core/safety/action_contract.
    contract: Optional[Any] = None
    detected_at: datetime = field(default_factory=datetime.now)
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
    """Security audit report"""
    report_id: str
    audit_period_start: datetime
    audit_period_end: datetime
    findings: List[SecurityAuditFinding] = field(default_factory=list)
    total_findings: int = 0
    critical_findings: int = 0
    high_findings: int = 0
    medium_findings: int = 0
    low_findings: int = 0
    compliance_score: float = 100.0
    generated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


_SESSION_LOG_RE = re.compile(
    r"""(
          _\d{8}[_-]?\d{0,6}      # _20260321_224308  /  _20260321
        | _run\d+                  # _run10
        | _\d{6,}                  # _1786658469
    )""",
    re.VERBOSE,
)


def _is_session_log(name: str) -> bool:
    """Is this the log of a COMPLETED run rather than a live component?

    Session logs carry their run identity in the filename (a timestamp or run
    number); component logs have stable names (`torin_main.log`). Only the
    latter can be meaningfully "stale" -- a finished session is supposed to
    stop being written to.
    """
    return bool(_SESSION_LOG_RE.search(name))


class SecurityAuditWorker:
    """
    Security Audit Worker

    Performs continuous security monitoring and auditing:
    - Monitors system security events
    - Detects vulnerabilities and anomalies
    - Validates compliance with security policies
    - Generates security reports
    - Integrates with governance and notification systems
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Audit state
        self.findings: Dict[str, SecurityAuditFinding] = {}
        self.audit_history: List[AuditReport] = []

        # Monitoring
        self.monitoring_active = False
        self.audit_interval = self.config.get('audit_interval', 120) 

        # Statistics
        self.stats = {
            'total_audits': 0,
            'total_findings': 0,
            'critical_findings': 0,
            'resolved_findings': 0,
            'last_audit_time': None
        }

        # Set when any sub-audit fails, so a partial scan is never mistaken for
        # "these conditions are gone" during reconciliation.
        self._scan_degraded: List[str] = []

        # Integration points
        self.safety_framework = None
        self.governance_system = None
        self.slack_notifier = None
        self.autonomous_coordinator = None  # For creating remediation tasks

        # Integrated security system (active defense)
        self.integrated_security = None
        self.threat_intel = None
        self.threat_blocking = None
        self.security_controller = None

        logger.info("SecurityAuditWorker initialized")

    def set_integrated_security(self, integrated_security: Dict[str, Any]):
        """
        Set integrated security system for active defense

        Connects SecurityAuditWorker to:
        - ThreatIntelligenceEngine (IP reputation lookups)
        - ThreatBlockingEngine (automated blocking)
        - SecurityController (request validation)

        Args:
            integrated_security: Dictionary with security components
        """
        self.integrated_security = integrated_security
        self.threat_intel = integrated_security.get('threat_intel')
        self.threat_blocking = integrated_security.get('threat_blocking')
        self.security_controller = integrated_security.get('security_controller')

        logger.info("✅ SecurityAuditWorker connected to integrated security system")
        logger.info(f"   Threat Intel: {'✓' if self.threat_intel else '✗'}")
        logger.info(f"   Threat Blocking: {'✓' if self.threat_blocking else '✗'}")
        logger.info(f"   Security Controller: {'✓' if self.security_controller else '✗'}")

    async def start_monitoring(self):
        """Start continuous security monitoring"""
        if self.monitoring_active:
            logger.warning("Security monitoring already active")
            return

        self.monitoring_active = True
        logger.info("Starting security audit monitoring")

        # Start monitoring loop
        asyncio.create_task(self._monitoring_loop())

    async def stop_monitoring(self):
        """Stop security monitoring"""
        self.monitoring_active = False
        logger.info("Stopped security audit monitoring")

    async def _monitoring_loop(self):
        """Continuous monitoring loop"""
        while self.monitoring_active:
            try:
                # Run security audit
                report = await self.run_security_audit()

                # Check for critical findings
                if report.critical_findings > 0:
                    await self._handle_critical_findings(report)

                # Wait for next audit interval
                await asyncio.sleep(self.audit_interval)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def run_security_audit(self) -> AuditReport:
        """
        Run comprehensive security audit

        COALESCED. Two independent schedulers drive this — the worker's own
        _monitoring_loop() and the coordinator's [IDLE:SECURITY] tier — so audits
        overlapped, each taking ~46s and each re-emitting the full finding set.
        That doubled the remediation-task pressure on the queue for no extra
        information.

        A concurrent caller now awaits the in-flight audit and receives ITS
        report rather than starting a second scan. Neither scheduler needs to
        know about the other, and removing one would be a guess about which is
        authoritative.

        Returns:
            Audit report with findings
        """
        # Fast path: an audit is already running — join it.
        _inflight = getattr(self, '_audit_inflight', None)
        if _inflight is not None and not _inflight.done():
            logger.info("Security audit already in progress — joining it (coalesced)")
            return await asyncio.shield(_inflight)

        _task = asyncio.ensure_future(self._run_security_audit_inner())
        self._audit_inflight = _task
        try:
            return await _task
        finally:
            if getattr(self, '_audit_inflight', None) is _task:
                self._audit_inflight = None

    async def _run_security_audit_inner(self) -> AuditReport:
        """The actual audit. Entered by exactly one caller at a time."""
        start_time = datetime.now()
        logger.info("Running security audit")

        self._scan_degraded = []
        findings = []

        # Each sub-audit owns a slice of the finding space. Retirement is scoped
        # per sub-audit, not globally: attack-surface needs privileges it does
        # not have here (psutil.AccessDenied) and fails on EVERY scan, so an
        # all-or-nothing guard would mean nothing is ever retired and the
        # detect->remediate->close loop stays dead.
        self._scanner_ok = {}
        _sub_audits = [
            ("access_control", self._audit_access_control),
            ("data_integrity", self._audit_data_integrity),
            ("authentication", self._audit_authentication),
            ("configuration", self._audit_configuration),
            ("anomalies", self._audit_anomalies),
            ("file_integrity", self._audit_file_integrity),
            ("attack_surface", self._audit_attack_surface),
            ("tool_permissions", self._audit_tool_permissions),
            ("log_integrity", self._audit_log_integrity),
            ("dependency_security", self._audit_dependency_security),
            ("active_defense_coverage", self._audit_active_defense_coverage),
        ]
        for _name, _fn in _sub_audits:
            _before = len(self._scan_degraded)
            try:
                _sub = await _fn()
            except Exception as _e:
                self._note_scan_degraded(_name, _e)
                _sub = []
            self._scanner_ok[_name] = (len(self._scan_degraded) == _before)
            for _f in _sub:
                _f.metadata.setdefault('_scanner', _name)
            findings.extend(_sub)

        # Count findings by severity
        critical = sum(1 for f in findings if f.severity == AuditSeverity.CRITICAL)
        high = sum(1 for f in findings if f.severity == AuditSeverity.HIGH)
        medium = sum(1 for f in findings if f.severity == AuditSeverity.MEDIUM)
        low = sum(1 for f in findings if f.severity == AuditSeverity.LOW)

        # Calculate compliance score
        compliance_score = self._calculate_compliance_score(findings)

        # Create report
        report = AuditReport(
            report_id=f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            audit_period_start=start_time,
            audit_period_end=datetime.now(),
            findings=findings,
            total_findings=len(findings),
            critical_findings=critical,
            high_findings=high,
            medium_findings=medium,
            low_findings=low,
            compliance_score=compliance_score
        )

        # Reconcile the finding store against what this scan actually observed.
        #
        # This used to be `self.findings[id] = finding` and nothing else, which
        # made the store append-only: a finding whose condition had been fixed
        # stayed "active" forever. Combined with finding_ids that embedded
        # datetime.now().timestamp(), every scan minted new ids for the same
        # conditions -- 239 real problems became ~81,500 permanently
        # unresolvable records over one 13.5h run, and the convergence gate
        # (which asks get_active_findings whether a finding is still open)
        # could never see a remediation succeed.
        #
        # A scan is now an OBSERVATION of current reality:
        #   detected  -> active (re-opened if the condition came back)
        #   absent    -> retired, the condition is no longer observed
        #
        # Retirement is skipped entirely when any sub-audit failed, because a
        # partial scan is not evidence that anything was fixed.
        detected_ids = set()
        for finding in findings:
            detected_ids.add(finding.finding_id)
            existing = self.findings.get(finding.finding_id)
            if existing is not None and existing.resolved:
                # Condition is back (or was never really fixed).
                existing.resolved = False
                existing.resolved_at = None
                existing.metadata['reopened_at'] = datetime.now().isoformat()
                logger.info(f"Re-opened finding (condition still present): {finding.finding_id}")
            else:
                self.findings[finding.finding_id] = finding

        if self._scan_degraded:
            logger.warning(
                f"Audit sub-scans FAILED ({', '.join(sorted(set(self._scan_degraded)))}) -- "
                f"their findings are held open; other scanners still reconcile"
            )
        retired = 0
        for fid, finding in self.findings.items():
            if fid in detected_ids or finding.resolved:
                continue
            # Only a scanner that ran successfully may conclude its conditions
            # are gone. Unknown owner (pre-existing finding) is not evidence.
            owner = finding.metadata.get('_scanner')
            if not owner or not self._scanner_ok.get(owner, False):
                continue
            finding.resolved = True
            finding.resolved_at = datetime.now()
            finding.metadata['resolution_notes'] = (
                f"auto-retired: condition no longer observed by {owner} scan"
            )
            self.stats['resolved_findings'] += 1
            retired += 1
        if retired:
            logger.info(f"Retired {retired} finding(s) whose condition is no longer present")

        # Update statistics
        self.stats['total_audits'] += 1
        self.stats['total_findings'] += len(findings)
        self.stats['critical_findings'] += critical
        self.stats['last_audit_time'] = datetime.now()

        # Store report
        self.audit_history.append(report)

        logger.info(f"Security audit complete: {len(findings)} findings "
                   f"(Critical: {critical}, High: {high}, Medium: {medium}, Low: {low})")

        # HIGH findings too. Only CRITICAL was ever surfaced anywhere, so 27
        # high-severity findings in a single audit left no durable trace at all.
        for finding in findings:
            if finding.severity is not AuditSeverity.HIGH:
                continue
            await failure_record.report(
                component=(finding.affected_components[0]
                           if finding.affected_components else "security"),
                failure_type="security_finding",
                description=f"{finding.title}: {finding.description}",
                source_system="security_audit_worker",
                severity="high",
                metadata={"category": finding.category.value,
                          "remediation": finding.remediation},
            )

        return report

    async def _audit_access_control(self) -> List[SecurityAuditFinding]:
        """Audit access control mechanisms"""
        findings = []

        try:
            from core.database import get_database_manager
            db = get_database_manager()

            # Check for failed access attempts in auth_logs (correct table with 'result' column)
            # PostgreSQL equivalent of MySQL's DATE_SUB(NOW(), INTERVAL 24 HOUR)
            # NOTE: PostgreSQL does not allow using SELECT aliases in HAVING, so we repeat COUNT(*)
            failed_access = await db.query("""
                SELECT username, COUNT(*) as attempts, MAX(timestamp) as last_attempt
                FROM auth_logs
                WHERE timestamp > NOW() - INTERVAL '24 hours'
                AND result IN ('failed', 'denied', 'access_denied', 'unauthorized')
                GROUP BY username
                HAVING COUNT(*) > 10
            """)

            for row in (failed_access or []):
                severity = AuditSeverity.HIGH if row.get('attempts', 0) > 50 else AuditSeverity.MEDIUM
                username = row.get('username', 'unknown')
                findings.append(SecurityAuditFinding(
                    finding_id=f"access_{username}",
                    category=AuditCategory.ACCESS_CONTROL,
                    severity=severity,
                    title=f"High access denial rate: {username}",
                    description=f"User '{username}' had {row.get('attempts')} failed access attempts in 24h",
                    affected_components=["authentication"],
                    remediation="Investigate potential brute force attack or unauthorized access attempts"
                ))

        except Exception as e:
            self._note_scan_degraded("Access control", e)

        return findings

    async def _audit_data_integrity(self) -> List[SecurityAuditFinding]:
        """Audit data integrity"""
        findings = []

        try:
            from core.database import get_database_manager
            db = get_database_manager()

            # Check for database corruption indicators
            # PostgreSQL equivalent of MySQL's SHOW TABLE STATUS
            table_status = await db.query("""
                SELECT
                    relname AS "Name",
                    n_live_tup AS "Rows"
                FROM pg_stat_user_tables
            """)

            for table in (table_status or []):
                table_name = table.get('Name')

                # Check for NULL or 0 rows in critical tables
                # NOTE: system_logs is unused (file-based logging used instead), excluded from check
                if table_name in ['conversations', 'memories', 'governance_evaluations']:
                    rows = table.get('Rows', 0)
                    if rows == 0 or rows is None:
                        findings.append(SecurityAuditFinding(
                            finding_id=f"integrity_{table_name}",
                            category=AuditCategory.DATA_INTEGRITY,
                            severity=AuditSeverity.MEDIUM,
                            title=f"Critical table appears empty: {table_name}",
                            description=f"Table '{table_name}' has {rows} rows",
                            affected_components=['database', table_name],
                            remediation="Verify table integrity and restore from backup if needed"
                        ))

            # Check for orphaned records
            orphaned_check = await db.query("""
                SELECT COUNT(*) as orphaned
                FROM directive_applications da
                LEFT JOIN internal_directives id ON da.directive_id = id.directive_id
                WHERE id.directive_id IS NULL
            """)

            if orphaned_check and orphaned_check[0].get('orphaned', 0) > 0:
                findings.append(SecurityAuditFinding(
                    finding_id=f"orphaned",
                    category=AuditCategory.DATA_INTEGRITY,
                    severity=AuditSeverity.LOW,
                    title="Orphaned directive applications detected",
                    description=f"{orphaned_check[0].get('orphaned')} applications reference non-existent directives",
                    affected_components=['database'],
                    remediation="Clean up orphaned records"
                ))

        except Exception as e:
            self._note_scan_degraded("Data integrity", e)

        return findings

    async def _audit_authentication(self) -> List[SecurityAuditFinding]:
        """Audit authentication mechanisms — API key exposure, blocked IPs, injection attempts"""
        findings = []

        try:
            import os
            import stat

            # ── 1. System security audit log: injection / path traversal attempts ──
            try:
                from core.security.system_security import get_system_security
                sys_sec = get_system_security()
                audit_entries = sys_sec.get_audit_log(limit=1000)

                sql_attempts = [e for e in audit_entries if e.get('event') == 'sql_injection_attempt']
                if len(sql_attempts) > 5:
                    findings.append(SecurityAuditFinding(
                        finding_id=f"auth_sqli",
                        category=AuditCategory.AUTHENTICATION,
                        severity=AuditSeverity.HIGH if len(sql_attempts) > 20 else AuditSeverity.MEDIUM,
                        title=f"SQL injection attempts detected in session",
                        description=f"{len(sql_attempts)} SQL injection attempts logged in current session audit log",
                        affected_components=['input_validation', 'database'],
                        remediation="Review input validation middleware; consider rate-limiting suspicious sources"
                    ))

                blocked_ips = sys_sec.blocked_ips
                if blocked_ips:
                    findings.append(SecurityAuditFinding(
                        finding_id=f"auth_blocked_ips",
                        category=AuditCategory.AUTHENTICATION,
                        severity=AuditSeverity.LOW,
                        title=f"{len(blocked_ips)} IP(s) currently blocked",
                        description=f"Blocked IPs: {', '.join(list(blocked_ips)[:10])}",
                        affected_components=['network', 'access_control'],
                        remediation="Verify blocked IPs are intentional; review rate limit configuration"
                    ))
            except Exception as _ss_err:
                logger.debug(f"system_security audit log check failed: {_ss_err}")

            # ── 2. Sensitive key/credential file permissions ──
            # NOTE: config/ must remain world-readable (0o755) for system operation
            # Only flag .env and keys/ which truly require restrictive permissions
            sensitive_files = ['.env', 'keys/']  # config/ intentionally excluded — required for operation
            torin_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            for rel_path in sensitive_files:
                abs_path = os.path.join(torin_root, rel_path)
                if os.path.exists(abs_path):
                    try:
                        mode = os.stat(abs_path).st_mode
                        # Flag if world-readable or world-writable
                        if mode & (stat.S_IROTH | stat.S_IWOTH):
                            octal = oct(stat.S_IMODE(mode))
                            findings.append(SecurityAuditFinding(
                                finding_id=f"auth_perms_{rel_path.replace('/', '_')}",
                                category=AuditCategory.AUTHENTICATION,
                                severity=AuditSeverity.CRITICAL,
                                title=f"Insecure permissions on '{rel_path}'",
                                description=f"Path '{abs_path}' is world-readable/writable (mode {octal})",
                                affected_components=['credentials', 'configuration'],
                                remediation=f"Run: chmod 600 '{abs_path}' (or 700 for directories)"
                            ))
                    except Exception:
                        pass

            # ── 3. Missing API credential environment variables ──
            api_credential_vars = [
                'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'SLACK_BOT_TOKEN',
                'SLACK_WEBHOOK_URL', 'POSTGRES_PASSWORD',
            ]
            # Database authentication — check what the server ACTUALLY accepts.
            #
            # This used to be `if not os.getenv('POSTGRES_PASSWORD')` → HIGH,
            # "set it in .env with a strong random value". Two things wrong with
            # that, and both cost real time:
            #
            #  * It tested for the presence of a STRING, not for a security
            #    property. Here every pg_hba rule is `trust`, which ignores
            #    passwords entirely — so writing a strong random value would
            #    have closed the finding and changed nothing at all.
            #  * The remediation was therefore unachievable-by-construction: the
            #    condition it checks (`os.getenv`) is not the condition that
            #    makes the system safe, so the finding would reopen or the fix
            #    would be theatre. It ran 200 iterations against this.
            #
            # `pg_hba_file_rules` reports the live rules without needing file
            # access, so this asks the server rather than guessing.
            findings.extend(await self._audit_database_auth())

            # ── 4. Check for signing_key.pem world-readable ──
            signing_key = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'signing_key.pem')
            if os.path.exists(signing_key):
                mode = os.stat(signing_key).st_mode
                if mode & (stat.S_IRGRP | stat.S_IROTH):
                    findings.append(SecurityAuditFinding(
                        finding_id=f"auth_signing_key",
                        category=AuditCategory.AUTHENTICATION,
                        severity=AuditSeverity.CRITICAL,
                        title="Signing key is group/world readable",
                        description=f"signing_key.pem has mode {oct(stat.S_IMODE(mode))} — private key should be 600",
                        affected_components=['authentication', 'integrity'],
                        remediation="Run: chmod 600 core/security/signing_key.pem"
                    ))

        except Exception as e:
            self._note_scan_degraded("Authentication", e)

        return findings

    async def _audit_configuration(self) -> List[SecurityAuditFinding]:
        """Audit system configuration"""
        findings = []

        try:
            import os

            # Check for required environment variables (TorinAI uses PostgreSQL)
            required_vars = ['POSTGRES_HOST', 'POSTGRES_DATABASE', 'POSTGRES_USER']
            missing_vars = [var for var in required_vars if not os.getenv(var)]

            if missing_vars:
                findings.append(SecurityAuditFinding(
                    finding_id=f"config_env",
                    category=AuditCategory.CONFIGURATION,
                    severity=AuditSeverity.HIGH,
                    title="Missing required environment variables",
                    description=f"Missing: {', '.join(missing_vars)}",
                    affected_components=['configuration'],
                    remediation="Set required environment variables in .env files"
                ))

            # Check file permissions on critical files
            critical_files = ['.env']
            for file in critical_files:
                if os.path.exists(file):
                    stat_info = os.stat(file)
                    mode = stat_info.st_mode & 0o777

                    # Check if file is world-readable (security risk)
                    if mode & 0o004:
                        findings.append(SecurityAuditFinding(
                            finding_id=f"config_perms_{file}",
                            category=AuditCategory.CONFIGURATION,
                            severity=AuditSeverity.CRITICAL,
                            title=f"Insecure file permissions: {file}",
                            description=f"File {file} is world-readable (mode: {oct(mode)})",
                            affected_components=['configuration'],
                            remediation=f"Run: chmod 600 {file}"
                        ))

        except Exception as e:
            self._note_scan_degraded("Configuration", e)

        return findings

    async def _audit_anomalies_OLD_DEAD_STUB(self) -> List[SecurityAuditFinding]:
        """Detect security anomalies"""
        findings = []

        try:
            from core.database import get_database_manager
            db = get_database_manager()

            # Check for unusual error rates (last hour)
            error_rate = await db.query("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN level = 'ERROR' OR level = 'CRITICAL' THEN 1 ELSE 0 END) as errors
                FROM system_logs
                WHERE timestamp > NOW() - INTERVAL '1 hour'
            """)

            if error_rate and len(error_rate) > 0:
                total = error_rate[0].get('total', 0)
                errors = error_rate[0].get('errors', 0)

                if total > 0:
                    error_percentage = (errors / total) * 100

                    if error_percentage > 25:
                        findings.append(SecurityAuditFinding(
                            finding_id=f"anomaly_errors",
                            category=AuditCategory.ANOMALY_DETECTION,
                            severity=AuditSeverity.HIGH if error_percentage > 50 else AuditSeverity.MEDIUM,
                            title="Abnormally high error rate detected",
                            description=f"Error rate: {error_percentage:.1f}% ({errors}/{total} logs)",
                            affected_components=['system'],
                            remediation="Investigate recent errors and system health"
                        ))

            # Check for rapid directive creation (potential abuse) in last hour
            rapid_directives = await db.query("""
                SELECT COUNT(*) as count
                FROM internal_directives
                WHERE created_at > NOW() - INTERVAL '1 hour'
            """)

            if rapid_directives and rapid_directives[0].get('count', 0) > 50:
                findings.append(SecurityAuditFinding(
                    finding_id=f"anomaly_directives",
                    category=AuditCategory.ANOMALY_DETECTION,
                    severity=AuditSeverity.MEDIUM,
                    title="Unusually high directive creation rate",
                    description=f"{rapid_directives[0].get('count')} directives created in last hour",
                    affected_components=['directives'],
                    remediation="Review recent directive creation patterns"
                ))

            # Check for database connection issues
            try:
                await db.query("SELECT 1")
            except Exception as db_error:
                findings.append(SecurityAuditFinding(
                    finding_id=f"anomaly_db",
                    category=AuditCategory.ANOMALY_DETECTION,
                    severity=AuditSeverity.CRITICAL,
                    title="Database connectivity issue",
                    description=f"Database query failed: {str(db_error)}",
                    affected_components=['database'],
                    remediation="Check database connection and credentials"
                ))

        except Exception as e:
            self._note_scan_degraded("Anomaly detection", e)

        return findings

    async def _audit_anomalies(self) -> List[SecurityAuditFinding]:
        """Detect security anomalies via file-based log scanning + database"""
        findings = []

        try:
            import os
            from pathlib import Path

            torin_root = Path(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )

            # ── 1. Scan recent log files for error spikes ──
            logs_dir = torin_root / 'logs'
            if logs_dir.exists():
                error_count = 0
                critical_count = 0
                total_lines = 0

                # Check the 3 most recently modified log files, last 1000 lines each
                recent_logs = sorted(
                    logs_dir.glob('*.log'),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True
                )[:3]

                for log_file in recent_logs:
                    try:
                        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                            lines = f.readlines()
                        recent = lines[-1000:] if len(lines) > 1000 else lines
                        for line in recent:
                            total_lines += 1
                            if ' ERROR ' in line or ' - ERROR' in line:
                                error_count += 1
                            if ' CRITICAL ' in line or ' - CRITICAL' in line:
                                critical_count += 1
                    except Exception:
                        pass

                if total_lines > 0:
                    error_rate = (error_count + critical_count) / total_lines
                    if error_rate > 0.25:
                        findings.append(SecurityAuditFinding(
                            finding_id=f"anomaly_log_errors",
                            category=AuditCategory.ANOMALY_DETECTION,
                            severity=(
                                AuditSeverity.HIGH if error_rate > 0.5
                                else AuditSeverity.MEDIUM
                            ),
                            title=f"Abnormally high error rate in logs: {error_rate:.0%}",
                            description=(
                                f"{error_count} ERRORs + {critical_count} CRITICALs "
                                f"in {total_lines} recent log lines"
                            ),
                            affected_components=['system', 'logging'],
                            remediation="Investigate recent errors and system health"
                        ))

                    if critical_count > 10:
                        findings.append(SecurityAuditFinding(
                            finding_id=f"anomaly_critical_log",
                            category=AuditCategory.ANOMALY_DETECTION,
                            severity=AuditSeverity.CRITICAL,
                            title=f"{critical_count} CRITICAL log entries in recent logs",
                            description=(
                                f"Elevated CRITICAL severity count ({critical_count}) "
                                f"in last {total_lines} scanned lines"
                            ),
                            affected_components=['system'],
                            remediation="Immediately investigate CRITICAL log entries"
                        ))

            # ── 2. Rapid directive creation (potential directive-injection abuse) ──
            try:
                from core.database import get_database_manager
                db = get_database_manager()

                rapid_directives = await db.query("""
                    SELECT COUNT(*) as count
                    FROM internal_directives
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """)

                if rapid_directives and rapid_directives[0].get('count', 0) > 50:
                    findings.append(SecurityAuditFinding(
                        finding_id=f"anomaly_directives",
                        category=AuditCategory.ANOMALY_DETECTION,
                        severity=AuditSeverity.MEDIUM,
                        title="Unusually high directive creation rate",
                        description=(
                            f"{rapid_directives[0].get('count')} directives created "
                            "in the last hour"
                        ),
                        affected_components=['directives'],
                        remediation="Review recent directive creation patterns for abuse"
                    ))

                # Connectivity probe
                await db.query("SELECT 1")

            except Exception as db_error:
                findings.append(SecurityAuditFinding(
                    finding_id=f"anomaly_db",
                    category=AuditCategory.ANOMALY_DETECTION,
                    severity=AuditSeverity.CRITICAL,
                    title="Database connectivity issue",
                    description=f"Database query failed: {str(db_error)}",
                    affected_components=['database'],
                    remediation="Check database connection and credentials"
                ))

            # ── 3. SecurityController violation spike ──
            try:
                from core.security.controller import get_security_controller
                sc = get_security_controller()
                sc_stats = await sc.get_statistics()
                violations = sc_stats.get('security_violations', 0)
                total_reqs = sc_stats.get('total_requests', 0)
                if total_reqs > 100:
                    violation_rate = violations / total_reqs
                    if violation_rate > 0.1:
                        findings.append(SecurityAuditFinding(
                            finding_id=f"anomaly_violation_spike",
                            category=AuditCategory.ANOMALY_DETECTION,
                            severity=AuditSeverity.HIGH,
                            title=f"Security violation spike: {violation_rate:.0%} of requests",
                            description=(
                                f"{violations} violations detected in {total_reqs} total requests"
                            ),
                            affected_components=['security_controller'],
                            remediation=(
                                "Review violation sources; consider increasing security level"
                            )
                        ))
            except Exception:
                pass

        except Exception as e:
            self._note_scan_degraded("Anomaly detection", e)

        return findings

    # ── Integrity provenance ────────────────────────────────────────────────
    # The baseline records WHAT the trusted state is. The manifest records WHY it
    # is trusted. Without the second, "changed" and "tampered" are the same
    # observation, so authorised development permanently manufactures HIGH
    # security findings — which is exactly how the remediation queue flooded.
    MANIFEST_REL = 'data/integrity_manifest.json'

    def _manifest_path(self):
        from pathlib import Path
        return Path(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ) / self.MANIFEST_REL

    def _load_manifest(self) -> Dict[str, Any]:
        import json
        mp = self._manifest_path()
        if not mp.exists():
            return {}
        try:
            with open(mp) as f:
                return json.load(f) or {}
        except Exception as e:
            logger.warning("[Integrity] manifest unreadable (%s) — treating as absent", e)
            return {}

    def _provenance_mode(self) -> str:
        """'production' or 'development'.

        Default is DEVELOPMENT, deliberately. Claiming production provenance
        without a manifest to back it would assert a guarantee nothing supports —
        and would turn every local edit into a HIGH security incident, which is
        the failure this replaces. Production must be asserted, never assumed.
        """
        env = (os.environ.get('TORIN_PROVENANCE_MODE') or '').strip().lower()
        if env in ('production', 'development'):
            return env
        return (self._load_manifest().get('mode') or 'development').lower()

    def _transition_authorized(self, rel: str, current_hash: str):
        """Does an authorised deployment explain this file's current hash?

        Returns (authorized, reason). Authorisation comes from the manifest —
        a record of a deployment that produced this artifact — never from the
        mere fact that the file changed.
        """
        m = self._load_manifest()
        if not m:
            return False, 'no deployment manifest present'
        artifacts = m.get('artifacts') or {}
        expected = artifacts.get(rel)
        if expected is None:
            return False, f"artifact not listed in manifest {m.get('deployment_id', '?')}"
        if expected == current_hash:
            return True, (
                f"authorised by deployment {m.get('deployment_id', '?')} "
                f"({m.get('provenance', 'unspecified provenance')})"
            )
        return False, (
            f"manifest {m.get('deployment_id', '?')} expects "
            f"{str(expected)[:16]}…, found {current_hash[:16]}…"
        )

    def _advance_trusted_state(self, rel: str, current_hash: str, why: str) -> None:
        """Move the runtime baseline forward for an AUTHORISED transition."""
        import json
        try:
            bp = self._manifest_path().parent / 'file_integrity_baseline.json'
            baseline = json.load(open(bp)) if bp.exists() else {}
            baseline[rel] = current_hash
            with open(bp, 'w') as f:
                json.dump(baseline, f, indent=2)
            logger.info("[Integrity] trusted state advanced for %s — %s", rel, why)
        except Exception as e:
            logger.warning("[Integrity] could not advance trusted state for %s: %s", rel, e)

    def authorize_current_state(self, deployment_id: str, provenance: str,
                                mode: str = 'development') -> Dict[str, Any]:
        """Record the current artifacts as authorised, WITH provenance.

        This replaces "re-take the baseline". The difference is not mechanical —
        a baseline says "trust this now", a manifest says "trust this because it
        came from HERE". Only the second can distinguish a deployment from an
        intruder on the next scan.
        """
        import json, hashlib
        from pathlib import Path
        from datetime import datetime as _dt
        root = self._manifest_path().parent.parent
        def _sha(p):
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for c in iter(lambda: f.read(65536), b''):
                    h.update(c)
            return h.hexdigest()
        bp = root / 'data' / 'file_integrity_baseline.json'
        tracked = list(json.load(open(bp)).keys()) if bp.exists() else []
        artifacts = {rel: _sha(str(root / rel)) for rel in tracked if (root / rel).exists()}
        manifest = {
            'deployment_id': deployment_id,
            'provenance': provenance,
            'mode': mode,
            'created_at': _dt.now().isoformat(),
            'artifacts': artifacts,
        }
        with open(self._manifest_path(), 'w') as f:
            json.dump(manifest, f, indent=2)
        with open(bp, 'w') as f:
            json.dump(artifacts, f, indent=2)
        logger.info("[Integrity] authorised %d artifacts under deployment %s (%s)",
                    len(artifacts), deployment_id, mode)
        return manifest

    async def _audit_file_integrity(self) -> List[SecurityAuditFinding]:
        """
        Hash critical core source files against a stored baseline.
        On first run, creates the baseline. Subsequent runs detect modifications or deletions.
        """
        findings = []
        try:
            import hashlib
            import json
            from pathlib import Path

            torin_root = Path(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
            baseline_path = torin_root / 'data' / 'file_integrity_baseline.json'

            # Core files that must not be tampered with
            critical_files = [
                'core/security/controller.py',
                'core/security/security_audit_worker.py',
                'core/governance/unified_governance_trigger_system.py',
                'core/agents/autonomous/autonomous_coordinator.py',
                'core/agents/autonomous/general_purpose_executor.py',
                'core/agents/autonomous/task_queue.py',
                'core/health/health_monitor.py',
                'core/safety/commitment_contract_manager.py',
            ]

            def sha256_file(path: str) -> str:
                h = hashlib.sha256()
                with open(path, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                return h.hexdigest()

            if not baseline_path.exists():
                # First run: build and persist baseline
                baseline = {}
                for rel in critical_files:
                    abs_path = torin_root / rel
                    if abs_path.exists():
                        baseline[rel] = sha256_file(str(abs_path))
                baseline_path.parent.mkdir(parents=True, exist_ok=True)
                with open(baseline_path, 'w') as f:
                    json.dump(baseline, f, indent=2)
                logger.info(f"[FileIntegrity] Baseline created for {len(baseline)} files")
            else:
                with open(baseline_path, 'r') as f:
                    baseline = json.load(f)

                for rel, expected_hash in baseline.items():
                    abs_path = torin_root / rel
                    if not abs_path.exists():
                        findings.append(SecurityAuditFinding(
                            finding_id=(
                                f"integrity_missing_{rel.replace('/', '_')}"
                            ),
                            category=AuditCategory.CODE_SECURITY,
                            severity=AuditSeverity.CRITICAL,
                            title=f"Core file MISSING: {rel}",
                            description=(
                                f"Critical source file has been deleted: {rel}"
                            ),
                            affected_components=['core', rel],
                            remediation=f"Restore {rel} from git or backup immediately"
                        ))
                    else:
                        current_hash = sha256_file(str(abs_path))
                        if current_hash != expected_hash:
                            # A hash mismatch is a STATE TRANSITION, not a verdict.
                            # The question is whether the transition was authorised —
                            # the baseline alone cannot answer it, which is why
                            # ordinary development regenerated HIGH findings forever
                            # and flooded the autonomous task queue.
                            authorized, why = self._transition_authorized(rel, current_hash)
                            if authorized:
                                self._advance_trusted_state(rel, current_hash, why)
                                continue

                            mode = self._provenance_mode()
                            if mode == 'development':
                                # Dev policy differs; dev does NOT redefine truth.
                                # The drift is still reported — at its real severity,
                                # under its real name, and never as "matches baseline".
                                findings.append(SecurityAuditFinding(
                                    finding_id=(
                                        f"integrity_dev_drift_{rel.replace('/', '_')}"
                                    ),
                                    category=AuditCategory.CODE_SECURITY,
                                    severity=AuditSeverity.LOW,
                                    title=f"AUTHORIZED_DEV_DRIFT: {rel}",
                                    description=(
                                        f"{rel} differs from the trusted manifest "
                                        f"({expected_hash[:16]}… → {current_hash[:16]}…). "
                                        "Running in development provenance mode, so this "
                                        "is expected local editing rather than tampering. "
                                        "It is NOT evidence the file matches a deployed "
                                        "artifact."
                                    ),
                                    affected_components=['core', rel],
                                    remediation=(
                                        "No action while in development mode. Authorise the "
                                        "new state on deploy (record a manifest with "
                                        "provenance) rather than re-taking a baseline."
                                    )
                                ))
                            else:
                                findings.append(SecurityAuditFinding(
                                    finding_id=(
                                        f"integrity_modified_{rel.replace('/', '_')}"
                                    ),
                                    category=AuditCategory.CODE_SECURITY,
                                    severity=AuditSeverity.HIGH,
                                    title=f"UNAUTHORIZED modification: {rel}",
                                    description=(
                                        f"Hash mismatch for {rel} — "
                                        f"trusted: {expected_hash[:16]}…, "
                                        f"current: {current_hash[:16]}…. "
                                        f"No authorised deployment explains this "
                                        f"transition ({why})."
                                    ),
                                    affected_components=['core', rel],
                                    remediation=(
                                        f"Investigate the origin of the change to {rel}. "
                                        "If legitimate, it must arrive through an "
                                        "authorised deployment that records provenance."
                                    )
                                ))

        except Exception as e:
            self._note_scan_degraded("File integrity", e)

        return findings

    async def _enumerate_listeners(self) -> Tuple[Dict[int, Dict], str]:
        """Enumerate listening sockets, degrading rather than aborting.

        psutil.net_connections(kind='inet') walks EVERY process's file
        descriptors. On macOS that needs root, so one unreadable process raised
        AccessDenied and killed the whole scan — Torin learned nothing about its
        own listening ports because it could not read someone else's.

        Strategy, best coverage first:
          1. psutil system-wide      — complete, incl. PIDs (root)
          2. per-process iteration   — skips only what we cannot read
          3. netstat -an             — complete listener list, no PIDs

        Returns (ports, coverage) where coverage is
        'complete' | 'partial_no_pids' | 'partial_processes' | 'none'.
        A caller must treat anything but 'complete' as "do not assert absence".
        """
        import psutil

        ports: Dict[int, Dict] = {}

        # 1. system-wide
        try:
            for c in psutil.net_connections(kind='inet'):
                if c.status == 'LISTEN' and c.laddr:
                    ports[c.laddr.port] = {'host': c.laddr.ip, 'pid': c.pid}
            return ports, 'complete'
        except (psutil.AccessDenied, PermissionError):
            pass
        except Exception as e:
            logger.debug("[AttackSurface] system-wide enumeration failed: %s", e)

        # 2. per-process — skip only the processes we cannot read
        denied = 0
        seen_any = False
        for proc in psutil.process_iter(['pid']):
            try:
                for c in proc.net_connections(kind='inet'):
                    if c.status == 'LISTEN' and c.laddr:
                        ports[c.laddr.port] = {'host': c.laddr.ip, 'pid': proc.pid}
                seen_any = True
            except (psutil.AccessDenied, psutil.NoSuchProcess, PermissionError):
                denied += 1
            except Exception:
                denied += 1

        # 3. netstat — no PIDs, but the listener set is complete and needs no
        #    privilege. Fills in ports owned by processes we could not read.
        netstat_ports = await self._listeners_via_netstat()
        for port, host in netstat_ports.items():
            ports.setdefault(port, {'host': host, 'pid': None})

        if netstat_ports:
            return ports, ('complete' if not denied else 'partial_no_pids')
        if seen_any:
            return ports, 'partial_processes'
        return ports, ('partial_processes' if ports else 'none')

    async def _listeners_via_netstat(self) -> Dict[int, str]:
        """Listening ports via netstat. No per-process access required."""
        import asyncio as _asyncio
        out: Dict[int, str] = {}
        try:
            proc = await _asyncio.create_subprocess_exec(
                'netstat', '-an',
                stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=15)
        except Exception as e:
            logger.debug("[AttackSurface] netstat unavailable: %s", e)
            return out

        for line in stdout.decode(errors='replace').splitlines():
            if 'LISTEN' not in line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            local = parts[3]
            # macOS: 127.0.0.1.5432 / *.8000 / ::1.5432
            host, sep, port_s = local.rpartition('.')
            if not sep or not port_s.isdigit():
                continue
            host = host.replace('*', '0.0.0.0') or '0.0.0.0'
            out[int(port_s)] = host
        return out

    async def _audit_attack_surface(self) -> List[SecurityAuditFinding]:
        """
        Audit exposed network attack surface — enumerate listening ports,
        flag unexpected public listeners, and detect critical services bound to 0.0.0.0.
        """
        findings = []
        try:
            listening_ports, coverage = await self._enumerate_listeners()

            if not listening_ports and coverage != 'complete':
                # Seeing nothing because we were BLIND is not the same as seeing
                # nothing because there is nothing. Reporting "no unexpected
                # listeners" from a failed enumeration is a false all-clear —
                # the most dangerous output a security scan can produce.
                raise RuntimeError(
                    "attack surface could not be enumerated "
                    f"(coverage={coverage}); refusing to report an all-clear"
                )
            if coverage != 'complete':
                logger.info(
                    "[AttackSurface] partial coverage (%s): %d listener(s) found; "
                    "PID attribution may be incomplete",
                    coverage, len(listening_ports)
                )

            # EXPOSURE IS DETERMINED BY BIND ADDRESS, NOT PORT NUMBER.
            #
            # The previous rule flagged any port outside a 11-entry whitelist,
            # which — once the scan actually worked — produced 24 findings on a
            # normal developer machine: macOS Continuity (rapportd), AirPlay
            # Receiver (ControlCenter on 5000/7000), VS Code helpers, cloudflared,
            # and our own observability stack. Whitelisting every legitimate port
            # is unwinnable; asking "is this reachable from the network?" is not.
            EPHEMERAL_MIN = 49152          # macOS/IANA dynamic range
            _LOOPBACK = ('127.0.0.1', '::1', 'localhost')

            # SELF-KNOWLEDGE. Torin discovers its own services continuously; the
            # audit simply never asked, so it reported its OWN 11 Python services
            # as unidentified public listeners. "My service is exposed" and "an
            # unidentified process is listening" are different findings with
            # different severities and different remediations — collapsing them
            # wasted the distinction the discovery subsystem already computes.
            own_ports = set()
            try:
                from core.system.active_discovery import get_active_discovery
                _sum = get_active_discovery().get_service_summary()
                # 'identified_ports', NOT 'ports'. A port that is open but whose
                # fingerprint FAILED is the least safe thing to assume is ours —
                # treating mere observation as ownership is how a self-model
                # becomes an implicit whitelist that fails open.
                own_ports = set(_sum.get('identified_ports') or [])
            except Exception as e:
                logger.debug("[AttackSurface] own-service inventory unavailable: %s", e)

            for port, info in sorted(listening_ports.items()):
                host = info.get('host') or ''

                # Ephemeral ports are transient client/peer sockets, not services.
                # They change every run, so findings about them can never be
                # closed — they generated permanent, unresolvable remediation work.
                if port >= EPHEMERAL_MIN:
                    continue

                # Loopback-only is not attack surface. This is the single most
                # important distinction and the old rule ignored it entirely.
                if host in _LOOPBACK:
                    continue

                if host not in ('0.0.0.0', '::', ''):
                    continue   # bound to one specific interface — reported below only if public

                is_own = port in own_ports
                findings.append(SecurityAuditFinding(
                    finding_id=(
                        f"attack_surface_own_service_{port}" if is_own
                        else f"attack_surface_unidentified_{port}"
                    ),
                    category=AuditCategory.NETWORK_SECURITY,
                    # An unidentified public listener is strictly more alarming
                    # than a known one of ours bound too broadly.
                    severity=AuditSeverity.MEDIUM if is_own else AuditSeverity.HIGH,
                    title=(
                        f"Own service on port {port} bound to all interfaces"
                        if is_own else
                        f"UNIDENTIFIED process listening publicly on port {port}"
                    ),
                    description=(
                        f"Port {port} is bound to {host} (all interfaces, "
                        f"PID: {info.get('pid')}). "
                        + ("This is one of Torin's own discovered services — a "
                           "binding decision, not an intruder."
                           if is_own else
                           "This port is NOT in Torin's own service inventory, so "
                           "it belongs to a process Torin did not start.")
                    ),
                    affected_components=['network', 'infrastructure'],
                    remediation=(
                        (f"Bind port {port} to 127.0.0.1 unless off-host access is "
                         "required; if it is, confirm it authenticates every request.")
                        if is_own else
                        (f"Identify the process owning port {port} and confirm it is "
                         "expected on this host.")
                    )
                ))

            # PostgreSQL should NEVER be bound to 0.0.0.0.
            #
            # THIS WATCHED ONLY 5432 -- the shared instance holding agentso's
            # tenant databases. TorinAI's own database moved to 5433, so the
            # one instance this system is actually responsible for was outside
            # the check entirely: it could have been bound to every interface
            # and this audit would have reported nothing. Both are checked now,
            # because an exposed database on this host is a finding either way.
            from core.database.postgres_config import DEFAULT_PORT

            for pg_port in (DEFAULT_PORT, 5432):
                pg_info = listening_ports.get(pg_port)
                if not (pg_info and pg_info.get('host') in ('0.0.0.0', '::')):
                    continue
                which = ("TorinAI" if pg_port == DEFAULT_PORT
                         else "shared/agentso")
                findings.append(SecurityAuditFinding(
                    finding_id=f"attack_surface_pg_exposed_{pg_port}",
                    category=AuditCategory.NETWORK_SECURITY,
                    severity=AuditSeverity.CRITICAL,
                    title="PostgreSQL exposed on all network interfaces",
                    description=(
                        f"PostgreSQL ({which}, port {pg_port}) bound to "
                        f"{pg_info['host']} — accessible from the network, "
                        "not just localhost"
                    ),
                    affected_components=['database', 'network'],
                    remediation=(
                        "Edit postgresql.conf: listen_addresses = 'localhost' "
                        "and restart PostgreSQL"
                    )
                ))

        except Exception as e:
            self._note_scan_degraded("Attack surface", e)

        return findings

    async def _audit_tool_permissions(self) -> List[SecurityAuditFinding]:
        """
        Audit the tool registry for high-risk tools (shell exec, file write, DB write).
        Flags how many dangerous tools are registered and ensures they are governance-gated.
        """
        findings = []
        try:
            from core.tools.tool_registry import get_tool_registry
            registry = get_tool_registry()

            all_tools = list(
                list(getattr(registry, 'tool_factories', {}).keys())
                + list(getattr(registry, 'tools', {}).keys())
            )

            HIGH_RISK_PATTERNS = [
                'shell', 'exec', 'subprocess', 'terminal', 'command',
                'file_write', 'write_file', 'create_file', 'delete_file',
                'database_write', 'sql_exec', 'run_code', 'execute_code',
            ]

            risky_tools = [
                t for t in all_tools
                if any(p in t.lower() for p in HIGH_RISK_PATTERNS)
            ]

            if risky_tools:
                findings.append(SecurityAuditFinding(
                    finding_id=f"tool_perms_high_risk",
                    category=AuditCategory.CODE_SECURITY,
                    severity=AuditSeverity.MEDIUM,
                    title=f"{len(risky_tools)} high-risk execution tools registered",
                    description=(
                        "Tools with code/shell/file execution capability: "
                        + ', '.join(risky_tools[:15])
                        + (f" … (+{len(risky_tools)-15} more)" if len(risky_tools) > 15 else "")
                    ),
                    affected_components=['tools', 'agents'],
                    remediation=(
                        "Verify all high-risk tools are evaluated by governance "
                        "before execution; add governance gate if missing"
                    )
                ))

        except Exception as e:
            self._note_scan_degraded("Tool permissions", e)

        return findings

    async def _audit_log_integrity(self) -> List[SecurityAuditFinding]:
        """
        Verify log files exist, are non-empty, and have been written to recently.
        Empty or stale log files may indicate tampering or a crashed logging subsystem.
        """
        findings = []
        try:
            from pathlib import Path

            torin_root = Path(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
            logs_dir = torin_root / 'logs'

            if not logs_dir.exists():
                findings.append(SecurityAuditFinding(
                    finding_id=f"log_integrity_no_dir",
                    category=AuditCategory.ANOMALY_DETECTION,
                    severity=AuditSeverity.HIGH,
                    title="Logs directory missing",
                    description=f"Expected logs directory not found: {logs_dir}",
                    affected_components=['logging'],
                    remediation="Ensure logging is configured and logs/ directory exists"
                ))
                return findings

            log_files = list(logs_dir.glob('*.log'))
            if not log_files:
                findings.append(SecurityAuditFinding(
                    finding_id=f"log_integrity_no_files",
                    category=AuditCategory.ANOMALY_DETECTION,
                    severity=AuditSeverity.MEDIUM,
                    title="No log files found in logs/",
                    description="No .log files present — logging may not be active",
                    affected_components=['logging'],
                    remediation="Verify logging configuration and file handler setup"
                ))
                return findings

            now = datetime.now()
            stale_threshold_hours = 6.0

            for log_file in log_files:
                try:
                    # A staleness check asks "is this component still alive?".
                    # That question only makes sense for a log a live component
                    # is EXPECTED to keep writing. logs/ is mostly an archive:
                    # 205 of 242 files are `shadow_<timestamp>.log` session
                    # records from completed diagnostic runs in March/April. A
                    # finished session's log is supposed to never be written
                    # again -- it is a historical artifact, not a dead service.
                    #
                    # Flagging them produced 238 of 239 findings as false
                    # positives, which then became 238 remediation tasks. Torin
                    # DELETED two of those archives (shadow_20260307_193524.log,
                    # shadow_20260322_111516.log) acting on a finding whose own
                    # remediation text is "Check if this component is still
                    # active and logging" -- an investigation, not a deletion.
                    if _is_session_log(log_file.name):
                        continue
                    st = log_file.stat()
                    age_hours = (now - datetime.fromtimestamp(st.st_mtime)).total_seconds() / 3600

                    if st.st_size == 0:
                        # OVERRIDE — one of the rare cases where severity is the
                        # wrong signal. This is MEDIUM, which would derive
                        # modify+archive, but a zero-byte log is potential
                        # TAMPER EVIDENCE: touching it destroys the thing being
                        # investigated. Overrides exist for exactly this, and
                        # should say why.
                        from core.safety.action_contract import ActionContract, ActionClass
                        findings.append(SecurityAuditFinding(
                            contract=ActionContract(
                                finding_id=f"log_integrity_empty_{log_file.name}",
                                resolution_criterion=(
                                    "the cause of the truncation is identified and reported "
                                    "(rotation, crash, or tampering)"
                                ),
                                permitted_actions=[ActionClass.INVESTIGATE],
                                max_irreversibility="FULLY_REVERSIBLE",
                                rationale=(
                                    "a zero-byte log may be evidence of log tampering; "
                                    "preserve it and report rather than modifying it"
                                ),
                            ),
                            finding_id=(
                                f"log_integrity_empty_{log_file.name}"
                            ),
                            category=AuditCategory.ANOMALY_DETECTION,
                            severity=AuditSeverity.MEDIUM,
                            title=f"Empty log file: {log_file.name}",
                            description=(
                                f"{log_file.name} is 0 bytes — "
                                "may have been cleared or truncated"
                            ),
                            affected_components=['logging'],
                            remediation="Investigate potential log tampering or logging failure"
                        ))
                    elif age_hours > stale_threshold_hours:
                        # No contract authored here on purpose: LOW severity
                        # already derives investigate+archive, max
                        # MOSTLY_REVERSIBLE. Restating it per detector is the
                        # burden that made this design wrong.
                        findings.append(SecurityAuditFinding(
                            finding_id=(
                                f"log_integrity_stale_{log_file.name}"
                            ),
                            category=AuditCategory.ANOMALY_DETECTION,
                            severity=AuditSeverity.LOW,
                            title=f"Stale log file: {log_file.name}",
                            description=(
                                f"{log_file.name} last written "
                                f"{age_hours:.1f}h ago — component may not be running"
                            ),
                            affected_components=['logging'],
                            remediation="Check if this component is still active and logging"
                        ))
                except Exception:
                    pass

        except Exception as e:
            self._note_scan_degraded("Log integrity", e)

        return findings

    async def _audit_dependency_security(self) -> List[SecurityAuditFinding]:
        """
        Check for outdated security-sensitive Python packages and known CVEs.
        Uses pip list --outdated and pip-audit (if installed) for CVE detection.
        """
        findings = []
        try:
            import subprocess
            import sys
            import json as _json

            # ── 1. Outdated security-sensitive packages ──
            try:
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'list',
                     '--format=json', '--outdated'],
                    capture_output=True, text=True, timeout=45
                )
                if result.returncode == 0 and result.stdout.strip():
                    outdated = _json.loads(result.stdout)

                    SECURITY_PACKAGES = {
                        'cryptography', 'pyopenssl', 'paramiko', 'requests',
                        'urllib3', 'certifi', 'aiohttp', 'httpx', 'flask',
                        'django', 'fastapi', 'uvicorn', 'pydantic', 'sqlalchemy',
                        'asyncpg', 'psycopg2', 'pillow', 'pyjwt', 'jwt',
                        'werkzeug', 'jinja2', 'twisted', 'tornado',
                    }

                    outdated_security = [
                        pkg for pkg in outdated
                        if pkg.get('name', '').lower() in SECURITY_PACKAGES
                    ]

                    if outdated_security:
                        pkg_list = ', '.join(
                            f"{p['name']} "
                            f"({p.get('version','?')}→{p.get('latest_version','?')})"
                            for p in outdated_security[:10]
                        )
                        findings.append(SecurityAuditFinding(
                            finding_id=f"deps_outdated_security",
                            category=AuditCategory.CODE_SECURITY,
                            severity=AuditSeverity.HIGH,
                            title=(
                                f"{len(outdated_security)} security-sensitive "
                                "packages are outdated"
                            ),
                            description=f"Outdated packages: {pkg_list}",
                            affected_components=['dependencies'],
                            remediation=(
                                "pip install --upgrade "
                                + ' '.join(p['name'] for p in outdated_security[:5])
                            )
                        ))

                    if len(outdated) > 20:
                        findings.append(SecurityAuditFinding(
                            finding_id=f"deps_many_outdated",
                            category=AuditCategory.CODE_SECURITY,
                            severity=AuditSeverity.LOW,
                            title=f"{len(outdated)} packages are outdated",
                            description="Consider updating all packages to reduce risk surface",
                            affected_components=['dependencies'],
                            remediation="pip install --upgrade -r requirements.txt"
                        ))
            except Exception:
                pass

            # ── 2. CVE scan via pip-audit (if available) ──
            try:
                audit_result = subprocess.run(
                    [sys.executable, '-m', 'pip_audit', '--format=json'],
                    capture_output=True, text=True, timeout=90
                )
                if audit_result.returncode == 0 and audit_result.stdout.strip():
                    audit_data = _json.loads(audit_result.stdout)
                    vulns = audit_data.get('vulnerabilities', [])
                    if vulns:
                        vuln_list = ', '.join(
                            f"{v.get('name','?')} ({v.get('id','CVE-?')})"
                            for v in vulns[:5]
                        )
                        findings.append(SecurityAuditFinding(
                            finding_id=f"deps_cve",
                            category=AuditCategory.CODE_SECURITY,
                            severity=AuditSeverity.CRITICAL,
                            title=(
                                f"{len(vulns)} known CVE vulnerabilities "
                                "in installed packages"
                            ),
                            description=f"Vulnerable packages: {vuln_list}",
                            affected_components=['dependencies'],
                            remediation=(
                                "Run: pip-audit --fix  "
                                "OR  pip install --upgrade <package>"
                            )
                        ))
            except Exception:
                pass  # pip-audit not installed — skip CVE check

        except Exception as e:
            self._note_scan_degraded("Dependency security", e)

        return findings

    async def _audit_active_defense_coverage(self) -> List[SecurityAuditFinding]:
        """
        Audit the active defense systems:
        - Threat intelligence source coverage
        - Firewall mode (test vs production)
        - Malware sandbox integrity
        """
        findings = []
        try:
            from core.security import get_integrated_security_system
            sec_sys = get_integrated_security_system()
            if sec_sys is None:
                # Nothing has created the security system. Observing must not
                # create it -- doing so used to fix the process into dry-run.
                #
                # This is a List[SecurityAuditFinding] contract: the caller does
                # `for _f in _sub: _f.metadata...`. Returning a bare dict here
                # made that loop iterate the dict's KEYS ('available', 'reason'),
                # so every scan crashed with "'str' object has no attribute
                # 'metadata'". Absent active defense is itself the finding, with
                # a stable id so it reconciles rather than multiplying.
                findings.append(SecurityAuditFinding(
                    finding_id="defense_system_not_initialised",
                    category=AuditCategory.NETWORK_SECURITY,
                    severity=AuditSeverity.HIGH,
                    title="Active defense system not initialised",
                    description=(
                        "The integrated security system (threat intelligence, "
                        "firewall, malware sandbox) is not running in-process, "
                        "so no active defense coverage can be assessed or applied."
                    ),
                    affected_components=['integrated_security_system'],
                    remediation=(
                        "Start the integrated security system "
                        "(create_integrated_security_system) so active defense "
                        "is live independent of the substrate."
                    )
                ))
                return findings

            # ── 1. Threat intelligence sources ──
            threat_intel = sec_sys.get('threat_intel')
            if threat_intel is None or isinstance(threat_intel, str):
                findings.append(SecurityAuditFinding(
                    finding_id=f"defense_no_threat_intel",
                    category=AuditCategory.NETWORK_SECURITY,
                    severity=AuditSeverity.MEDIUM,
                    title="Threat intelligence engine not available in-process",
                    description=(
                        "ThreatIntelligenceEngine object not found — using external "
                        "service or not configured"
                    ),
                    affected_components=['threat_intelligence'],
                    remediation=(
                        "Set API keys: ABUSEIPDB_API_KEY, VIRUSTOTAL_API_KEY, OTX_API_KEY"
                    )
                ))
            else:
                stats = threat_intel.get_statistics()
                if stats.get('sources_available', 0) == 0:
                    findings.append(SecurityAuditFinding(
                        finding_id=f"defense_no_intel_sources",
                        category=AuditCategory.NETWORK_SECURITY,
                        severity=AuditSeverity.MEDIUM,
                        title="No threat intelligence sources configured",
                        description=(
                            "sources_available=0 — no IP reputation lookups will succeed"
                        ),
                        affected_components=['threat_intelligence'],
                        remediation=(
                            "Set ABUSEIPDB_API_KEY, VIRUSTOTAL_API_KEY, OTX_API_KEY env vars"
                        )
                    ))

            # ── 2. Firewall mode ──
            firewall = sec_sys.get('firewall')
            if firewall is not None and not isinstance(firewall, str):
                fw_stats = firewall.get_statistics()
                if fw_stats.get('test_mode', True):
                    findings.append(SecurityAuditFinding(
                        finding_id=f"defense_firewall_test_mode",
                        category=AuditCategory.NETWORK_SECURITY,
                        severity=AuditSeverity.MEDIUM,
                        title="Firewall running in TEST MODE (dry run)",
                        description=(
                            "Firewall is in dry-run mode — no actual OS-level "
                            "IP blocking is being applied"
                        ),
                        affected_components=['firewall'],
                        remediation=(
                            "Set test_mode=False in create_integrated_security_system() "
                            "and ensure the process has root/sudo for iptables/pf"
                        )
                    ))
                if fw_stats.get('active_rules', 0) == 0:
                    findings.append(SecurityAuditFinding(
                        finding_id=f"defense_no_fw_rules",
                        category=AuditCategory.NETWORK_SECURITY,
                        severity=AuditSeverity.LOW,
                        title="Firewall has no active rules",
                        description="RealTimeFirewallManager has 0 active_rules",
                        affected_components=['firewall'],
                        remediation="Review firewall configuration and rule initialization"
                    ))

            # ── 3. Malware sandbox known-hash database ──
            try:
                from core.security.malware_sandbox import get_malware_sandbox
                sandbox = get_malware_sandbox()
                sb_stats = await sandbox.get_statistics()
                if sb_stats.get('known_malware_hashes', 0) == 0:
                    findings.append(SecurityAuditFinding(
                        finding_id=f"defense_no_malware_db",
                        category=AuditCategory.CODE_SECURITY,
                        severity=AuditSeverity.LOW,
                        title="Malware sandbox: no known hash database loaded",
                        description="known_malware_hashes=0 — signature-based detection disabled",
                        affected_components=['malware_sandbox'],
                        remediation="Load a malware hash database into MalwareSandbox.known_malware_hashes"
                    ))
            except Exception:
                pass

        except Exception as e:
            self._note_scan_degraded("Active defense coverage", e)

        return findings

    def _calculate_compliance_score(self, findings: List[SecurityAuditFinding]) -> float:
        """Calculate compliance score based on findings"""
        if not findings:
            return 100.0

        # Weighted scoring
        weights = {
            AuditSeverity.CRITICAL: 20,
            AuditSeverity.HIGH: 10,
            AuditSeverity.MEDIUM: 5,
            AuditSeverity.LOW: 1
        }

        total_penalty = sum(weights.get(f.severity, 0) for f in findings)

        # Calculate score (100 - penalties, minimum 0)
        score = max(0.0, 100.0 - total_penalty)

        return round(score, 2)

    async def _handle_critical_findings(self, report: AuditReport):
        """Handle critical security findings"""
        critical_findings = [
            f for f in report.findings
            if f.severity == AuditSeverity.CRITICAL
        ]

        logger.critical(f"CRITICAL SECURITY FINDINGS: {len(critical_findings)} issues detected")

        # THE FINDING NOW OUTLIVES THE PROCESS AND REACHES THE SYSTEMS THAT ACT
        # ON IT. Critical findings went to a log line, a Slack message, and
        # `SecurityController.security_findings` -- a Python list trimmed to
        # `max_findings` and lost at shutdown. Nothing queryable, so the
        # coordinator could not see a recurring security fault, the improvement
        # cycle could not target it, and the recovery manager never heard of it.
        for finding in critical_findings:
            await failure_record.report(
                component=(finding.affected_components[0]
                           if finding.affected_components else "security"),
                failure_type="security_violation",
                description=f"{finding.title}: {finding.description}",
                source_system="security_audit_worker",
                severity="critical",
                metadata={
                    "category": finding.category.value,
                    "remediation": finding.remediation,
                    "affected_components": list(finding.affected_components or []),
                    "finding_id": getattr(finding, "finding_id", None),
                },
            )

        # Notify via Slack with detailed findings
        if self.slack_notifier:
            try:
                # Build detailed message with findings
                findings_detail = []
                for i, finding in enumerate(critical_findings[:5], 1):  # Limit to first 5
                    findings_detail.append(
                        f"**{i}. {finding.title}**\n"
                        f"   Category: {finding.category.value}\n"
                        f"   Description: {finding.description}\n"
                        f"   Affected: {', '.join(finding.affected_components) if finding.affected_components else 'N/A'}\n"
                        f"   Remediation: {finding.remediation or 'Manual review required'}"
                    )

                findings_text = "\n\n".join(findings_detail)
                if len(critical_findings) > 5:
                    findings_text += f"\n\n... and {len(critical_findings) - 5} more findings"

                await self.slack_notifier.send_security_alert(
                    alert_title="Critical Security Findings Detected",
                    alert_message=f"**{len(critical_findings)} critical security issues found:**\n\n{findings_text}",
                    severity="CRITICAL",
                    metadata={
                        'total_findings': len(critical_findings),
                        'findings': [
                            {
                                'id': f.finding_id,
                                'title': f.title,
                                'category': f.category.value,
                                'components': f.affected_components
                            } for f in critical_findings
                        ]
                    }
                )
            except Exception as e:
                logger.error(f"Failed to send Slack notification: {e}")

        # Escalate to governance if available
        if self.governance_system:
            try:
                await self.governance_system.escalate_security_event(
                    event_type="critical_findings",
                    findings=critical_findings
                )
            except Exception as e:
                logger.error(f"Failed to escalate to governance: {e}")

        # Enrich findings with threat intelligence and auto-block critical threats
        if self.threat_intel or self.threat_blocking:
            try:
                await self._enrich_and_auto_block_findings(critical_findings)
            except Exception as e:
                logger.error(f"Failed to enrich/block findings: {e}")

        # Create remediation tasks through autonomous coordinator
        if self.autonomous_coordinator:
            try:
                await self._create_remediation_tasks(critical_findings)
            except Exception as e:
                logger.error(f"Failed to create remediation tasks: {e}")

    async def _enrich_and_auto_block_findings(self, findings: List[SecurityAuditFinding]):
        """
        Enrich findings with threat intelligence and auto-block critical threats

        Phase 2: Query threat intelligence for IP reputation
        Phase 3: Auto-block IPs with high threat scores

        Args:
            findings: List of security findings to process
        """
        for finding in findings:
            # Extract IP address from finding metadata
            ip_address = finding.metadata.get('ip_address') or finding.metadata.get('source_ip')

            if not ip_address:
                continue

            # Phase 2: Query threat intelligence
            if self.threat_intel:
                try:
                    intel = await self.threat_intel.get_ip_intelligence(ip_address)

                    # Enrich finding with threat intelligence
                    finding.metadata['threat_score'] = intel.threat_score
                    finding.metadata['confidence'] = intel.confidence
                    finding.metadata['attack_types'] = [a.value for a in intel.attack_types]
                    finding.metadata['threat_sources'] = [s.value for s in intel.sources]

                    # Upgrade severity based on threat score
                    if intel.threat_score > 80 and finding.severity != AuditSeverity.CRITICAL:
                        logger.warning(
                            f"Upgrading finding {finding.finding_id} to CRITICAL "
                            f"(threat score: {intel.threat_score})"
                        )
                        finding.severity = AuditSeverity.CRITICAL

                    logger.info(
                        f"Threat intel for {ip_address}: "
                        f"score={intel.threat_score}, confidence={intel.confidence}"
                    )

                except Exception as e:
                    logger.error(f"Failed to query threat intel for {ip_address}: {e}")

            # Phase 3: Auto-block critical threats with high threat scores
            threat_score = finding.metadata.get('threat_score', 0)
            if (self.threat_blocking and
                finding.severity == AuditSeverity.CRITICAL and
                threat_score > 70):  # High confidence threshold

                try:
                    # Map finding category to attack type
                    from core.security.threat_blocking import AttackType
                    attack_type_map = {
                        'network_security': AttackType.NETWORK_SCAN,
                        'authentication': AttackType.BRUTE_FORCE,
                        'access_control': AttackType.UNAUTHORIZED_ACCESS,
                        'anomaly_detection': AttackType.ANOMALY
                    }

                    attack_type = attack_type_map.get(
                        finding.category.value,
                        AttackType.ANOMALY
                    )

                    # Execute auto-block
                    result = await self.threat_blocking.analyze_and_block(
                        ip_address=ip_address,
                        attack_type=attack_type,
                        evidence={
                            'finding_id': finding.finding_id,
                            'description': finding.description,
                            'threat_score': threat_score,
                            'detected_at': finding.detected_at.isoformat()
                        }
                    )

                    if result.get('blocked'):
                        finding.metadata['auto_blocked'] = True
                        finding.metadata['block_duration'] = result.get('duration')
                        finding.metadata['blocked_by'] = result.get('methods', [])
                        finding.remediation = (
                            f"✅ Automatically blocked {ip_address} for {result.get('duration')} "
                            f"(threat score: {threat_score})"
                        )
                        logger.info(f"🛡️ Auto-blocked critical threat: {ip_address}")

                except Exception as e:
                    logger.error(f"Failed to auto-block {ip_address}: {e}")

    async def _create_remediation_tasks(self, findings: List[SecurityAuditFinding]):
        """Create remediation tasks for security findings through autonomous coordinator"""
        try:
            for finding in findings:
                # Create task description
                task_description = (
                    f"Security Remediation: {finding.title}\n"
                    f"Severity: {finding.severity.value}\n"
                    f"Description: {finding.description}\n"
                    f"Remediation: {finding.remediation or 'Investigate and fix'}"
                )

                # Send to autonomous coordinator to create task (which will evaluate through governance)
                await self.autonomous_coordinator.handle_security_finding(
                    finding_id=finding.finding_id,
                    severity=finding.severity.value,
                    description=task_description,
                    remediation=finding.remediation,
                    affected_components=finding.affected_components,
                    contract=finding.contract,
                )

                logger.info(f"Created remediation task for finding: {finding.finding_id}")

        except Exception as e:
            logger.error(f"Error creating remediation tasks: {e}", exc_info=True)

    async def _audit_database_auth(self) -> List[SecurityAuditFinding]:
        """What does Postgres actually accept, and does that match our config?

        Severity follows REACH, because that is what decides how much the
        weakness is worth. `trust` reachable from a network address is a
        different problem from `trust` on loopback, and calling both HIGH is how
        a queue fills with work nobody can rank.
        """
        findings: List[SecurityAuditFinding] = []

        try:
            from core.database import get_database_manager
            db = get_database_manager()
            rules = await db.execute_query(
                "SELECT type, address, auth_method FROM pg_hba_file_rules "
                "WHERE auth_method IS NOT NULL",
                fetch_all=True,
            ) or []
        except Exception as e:
            # Not knowing is its own finding — and must not be reported as
            # "secure". Absence of evidence is not evidence of safety.
            logger.debug(f"database auth audit could not read pg_hba_file_rules: {e}")
            return findings

        def _loopback(addr) -> bool:
            a = str(addr or "").strip()
            return a in ("", "-", "127.0.0.1", "::1", "localhost", "samehost")

        weak = {"trust", "password"}
        remote_weak, local_weak = [], []
        requires_password = False

        for r in rules:
            method = str(r.get("auth_method") or "").lower()
            addr = r.get("address")
            rtype = str(r.get("type") or "")
            if method in ("scram-sha-256", "md5", "cert", "gss", "sspi", "ldap", "radius"):
                requires_password = True
            if method in weak:
                (local_weak if (rtype == "local" or _loopback(addr)) else remote_weak).append(
                    f"{rtype} {addr or '-'} → {method}"
                )

        if remote_weak:
            findings.append(SecurityAuditFinding(
                finding_id="db_auth_trust_remote",
                category=AuditCategory.AUTHENTICATION,
                severity=AuditSeverity.CRITICAL,
                title="Database accepts unauthenticated connections from the network",
                description=(
                    "pg_hba grants access with no credential check from a non-loopback "
                    f"address: {'; '.join(remote_weak)}. Anyone who can route to this "
                    "host has full database access as any role."
                ),
                affected_components=["database", "authentication"],
                remediation=(
                    "In pg_hba.conf change these rules to scram-sha-256, set a role "
                    "password, then reload (SELECT pg_reload_conf())."
                ),
            ))
        elif local_weak:
            findings.append(SecurityAuditFinding(
                finding_id="db_auth_trust_local",
                category=AuditCategory.AUTHENTICATION,
                severity=AuditSeverity.MEDIUM,
                title="Database uses trust authentication on loopback",
                description=(
                    f"pg_hba accepts local connections with no credential: "
                    f"{'; '.join(local_weak)}. Reach is limited to processes already "
                    "on this host, but any of them can act as any database role. "
                    "Note that POSTGRES_PASSWORD is irrelevant while trust is in "
                    "force — trust ignores passwords."
                ),
                affected_components=["database", "authentication"],
                remediation=(
                    "Decide deliberately: acceptable for a single-user workstation, "
                    "not for a shared or exposed host. To harden, set scram-sha-256 "
                    "in pg_hba.conf, ALTER ROLE ... WITH PASSWORD, put the value in "
                    ".env as POSTGRES_PASSWORD, then SELECT pg_reload_conf()."
                ),
            ))

        # The env var only matters if the server actually asks for one. Flagged
        # unconditionally before, which is why it fired on a trust-auth database
        # where the value could not possibly be used.
        if requires_password and not os.getenv("POSTGRES_PASSWORD"):
            findings.append(SecurityAuditFinding(
                finding_id="db_auth_password_required_but_unset",
                category=AuditCategory.AUTHENTICATION,
                severity=AuditSeverity.HIGH,
                title="Postgres requires a password but POSTGRES_PASSWORD is unset",
                description=(
                    "pg_hba has password-based rules, so connections need a credential "
                    "this process does not have."
                ),
                affected_components=["configuration", "database"],
                remediation="Set POSTGRES_PASSWORD in .env to the role's password.",
            ))

        return findings

    def _note_scan_degraded(self, where: str, error: Exception) -> None:
        """Record that a sub-audit failed, at a level someone will actually see.

        These were `logger.debug(...)` -- a failed sub-audit was invisible and
        indistinguishable from one that legitimately found nothing. That matters
        now that an absent finding means "condition fixed": a silently broken
        scan would auto-retire real findings.
        """
        self._scan_degraded.append(where)
        # Log the full traceback ONCE per distinct failure, then a one-line
        # reminder. The audit runs every 120s and some failures are permanent
        # (psutil.net_connections needs privileges macOS will not grant here),
        # so an unconditional exc_info buried the log in the same stack ~700
        # times a day. Still visible, no longer drowning.
        if not hasattr(self, "_degraded_seen"):
            self._degraded_seen = {}
        key = f"{where}:{type(error).__name__}"
        first = key not in self._degraded_seen
        self._degraded_seen[key] = self._degraded_seen.get(key, 0) + 1
        if first:
            logger.warning(f"{where} audit sub-scan FAILED: {error}", exc_info=True)
        elif self._degraded_seen[key] % 50 == 0:
            logger.warning(
                f"{where} audit sub-scan still failing ({type(error).__name__}) "
                f"— {self._degraded_seen[key]} occurrences"
            )
        else:
            logger.debug(f"{where} audit sub-scan failed again: {error}")

    async def resolve_finding(
        self,
        finding_id: str,
        resolution_notes: str = ""
    ) -> bool:
        """
        Mark finding as resolved

        Args:
            finding_id: Finding identifier
            resolution_notes: Notes about resolution

        Returns:
            True if resolved successfully
        """
        if finding_id not in self.findings:
            logger.warning(f"Finding not found: {finding_id}")
            return False

        finding = self.findings[finding_id]
        finding.resolved = True
        finding.resolved_at = datetime.now()
        finding.metadata['resolution_notes'] = resolution_notes

        self.stats['resolved_findings'] += 1

        logger.info(f"Resolved finding: {finding_id}")
        return True

    async def get_active_findings(
        self,
        severity: Optional[AuditSeverity] = None,
        category: Optional[AuditCategory] = None
    ) -> List[SecurityAuditFinding]:
        """
        Get active (unresolved) findings

        Args:
            severity: Filter by severity
            category: Filter by category

        Returns:
            List of active findings
        """
        findings = [f for f in self.findings.values() if not f.resolved]

        if severity:
            findings = [f for f in findings if f.severity == severity]

        if category:
            findings = [f for f in findings if f.category == category]

        return findings

    async def generate_report(
        self,
        period_days: int = 7
    ) -> AuditReport:
        """
        Generate security audit report for period

        Args:
            period_days: Number of days to include

        Returns:
            Audit report
        """
        cutoff = datetime.now() - timedelta(days=period_days)

        # Get findings from period
        period_findings = [
            f for f in self.findings.values()
            if f.detected_at >= cutoff
        ]

        # Count by severity
        critical = sum(1 for f in period_findings if f.severity == AuditSeverity.CRITICAL)
        high = sum(1 for f in period_findings if f.severity == AuditSeverity.HIGH)
        medium = sum(1 for f in period_findings if f.severity == AuditSeverity.MEDIUM)
        low = sum(1 for f in period_findings if f.severity == AuditSeverity.LOW)

        report = AuditReport(
            report_id=f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            audit_period_start=cutoff,
            audit_period_end=datetime.now(),
            findings=period_findings,
            total_findings=len(period_findings),
            critical_findings=critical,
            high_findings=high,
            medium_findings=medium,
            low_findings=low,
            compliance_score=self._calculate_compliance_score(period_findings)
        )

        return report

    async def get_statistics(self) -> Dict[str, Any]:
        """Get audit statistics"""
        active_findings = await self.get_active_findings()

        return {
            **self.stats,
            'active_findings': len(active_findings),
            'resolution_rate': (
                self.stats['resolved_findings'] / self.stats['total_findings'] * 100
                if self.stats['total_findings'] > 0 else 100.0
            ),
            'monitoring_active': self.monitoring_active
        }

    def set_safety_framework(self, framework):
        """Hold a reference to the authority for action safety.

        NOTHING IN THIS CLASS READS `self.safety_framework` YET. Recorded here
        rather than left implicit, because the setter plus a "configured" log
        line reads as a working integration, and for a long time it was fed an
        attribute that was permanently None -- so the call never even happened.
        """
        self.safety_framework = framework
        logger.info("Safety framework reference held (no consumer reads it yet)")

    def set_governance_system(self, governance):
        """Set governance system integration"""
        self.governance_system = governance
        logger.info("Governance system integration configured")

    def set_slack_notifier(self, notifier):
        """Set Slack notifier integration"""
        self.slack_notifier = notifier
        logger.info("Slack notifier integration configured")

    def set_autonomous_coordinator(self, coordinator):
        """Set autonomous coordinator integration for remediation tasks"""
        self.autonomous_coordinator = coordinator
        logger.info("Autonomous coordinator integration configured")

    def set_integrated_security(self, integrated_security):
        """Set integrated security system for active defense"""
        self.integrated_security = integrated_security
        self.threat_intel = integrated_security.get('threat_intel')
        self.threat_blocking = integrated_security.get('threat_blocking')
        self.security_controller = integrated_security.get('controller')
        logger.info("✓ Integrated security system configured (active defense enabled)")


# Global instance
_audit_worker: Optional[SecurityAuditWorker] = None


def get_audit_worker() -> SecurityAuditWorker:
    """Get global audit worker instance"""
    global _audit_worker
    if _audit_worker is None:
        _audit_worker = SecurityAuditWorker()
    return _audit_worker


# Test usage
async def main():
    """Test security audit worker"""
    logging.basicConfig(level=logging.INFO)

    worker = get_audit_worker()

    # Run audit
    report = await worker.run_security_audit()

    print(f"\n{'='*60}")
    print("Security Audit Report")
    print(f"{'='*60}")
    print(f"Report ID: {report.report_id}")
    print(f"Total Findings: {report.total_findings}")
    print(f"  Critical: {report.critical_findings}")
    print(f"  High: {report.high_findings}")
    print(f"  Medium: {report.medium_findings}")
    print(f"  Low: {report.low_findings}")
    print(f"Compliance Score: {report.compliance_score}%")

    stats = await worker.get_statistics()
    print(f"\nStatistics: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
