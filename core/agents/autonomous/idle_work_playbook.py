"""
Idle Work Playbook
==================
Structured decision graphs for all 6 idle priority tiers.

For each tier the playbook maps a raw observation (data returned by a subsystem
call) to an ordered list of RemediationPlan / PlaybookStep objects.  The
coordinator's dedicated _idle_XXX_work() methods consume these plans and
execute the steps — creating tasks, calling recovery handlers, storing memory,
and sending notifications — without ad-hoc if/else chains scattered through
the coordinator.

Priority tiers (mirrors _run_idle_work ordering):
  1. Security  — (AuditCategory, AuditSeverity) → RemediationPlan
  2. Health    — (component_name, health_status) → RemediationPlan
  3. Self-improvement — selects target components from health + failure data
  4. Meta-learning    — returns ordered TaskType list to evaluate
  5. Memory           — returns ordered ConsolidationStrategy list
  6. Exploration      — filters + caps goal generation config
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


# ============================================================================
# Governance tiers — used to decide auto-execute vs. deferred approval
# ============================================================================

class GovernanceTier(Enum):
    ROUTINE   = "ROUTINE"    # Auto-execute — no human approval required
    IMPORTANT = "IMPORTANT"  # Notify human; create deferred task for approval
    CRITICAL  = "CRITICAL"   # Must have explicit human approval before executing


# ============================================================================
# Core data structures
# ============================================================================

class StepIdempotency(Enum):
    """
    Idempotency class for a playbook step.  Determines the minimum cooldown
    window enforced by _step_is_due() before the same (trigger_id, action)
    pair is allowed to execute again.

    SAFE      — read-only or genuinely idempotent; no cooldown enforced.
    NOTIFY    — sends a human notification; cooldown = 30 min to prevent spam.
    RESTART   — restarts a process/component; cooldown = 10 min to prevent
                double-restart races while the first is still settling.
    MUTATING  — modifies state but is recoverable (block IP, fix config, etc.);
                cooldown = 15 min.
    DESTRUCTIVE — irreversible or high-impact (rotate keys, restore backup,
                  revoke sessions); cooldown = 60 min.
    """
    SAFE        = "safe"        # No cooldown
    NOTIFY      = "notify"      # 30 min cooldown
    RESTART     = "restart"     # 10 min cooldown
    MUTATING    = "mutating"    # 15 min cooldown
    DESTRUCTIVE = "destructive" # 60 min cooldown


# Cooldown in seconds per idempotency class
STEP_COOLDOWNS: Dict[StepIdempotency, float] = {
    StepIdempotency.SAFE:        0.0,
    StepIdempotency.NOTIFY:      1800.0,   # 30 min
    StepIdempotency.RESTART:     600.0,    # 10 min
    StepIdempotency.MUTATING:    900.0,    # 15 min
    StepIdempotency.DESTRUCTIVE: 3600.0,   # 60 min
}

# Per-action idempotency classification
# Any action not listed here defaults to MUTATING (safe conservative choice)
ACTION_IDEMPOTENCY: Dict[str, StepIdempotency] = {
    # ── Read-only / truly idempotent ──────────────────────────────────────
    "audit_auth_logs":            StepIdempotency.SAFE,
    "audit_data_consistency":     StepIdempotency.SAFE,
    "audit_iam_policies":         StepIdempotency.SAFE,
    "audit_encryption_coverage":  StepIdempotency.SAFE,
    "verify_firewall_rules":      StepIdempotency.SAFE,
    "verify_db_integrity":        StepIdempotency.SAFE,
    "verify_after_restart":       StepIdempotency.SAFE,
    "verify_agents_healthy":      StepIdempotency.SAFE,
    "verify_reasoning_output":    StepIdempotency.SAFE,
    "verify_api_connectivity":    StepIdempotency.SAFE,
    "verify_network":             StepIdempotency.SAFE,
    "verify_dns_resolution":      StepIdempotency.SAFE,
    "run_compliance_scan":        StepIdempotency.SAFE,
    "run_full_compliance_scan":   StepIdempotency.SAFE,
    "generate_compliance_report": StepIdempotency.SAFE,
    "scan_codebase":              StepIdempotency.SAFE,
    "scan_dependencies":          StepIdempotency.SAFE,
    "investigate_anomaly":        StepIdempotency.SAFE,
    "threat_intel_lookup":        StepIdempotency.SAFE,
    "track_memory_trend":         StepIdempotency.SAFE,
    "track_storage_health":       StepIdempotency.SAFE,
    "rescan_access_control":      StepIdempotency.SAFE,
    "rescan_authentication":      StepIdempotency.SAFE,
    "rescan_configuration":       StepIdempotency.SAFE,
    "emergency_security_scan":    StepIdempotency.SAFE,
    "gc_collect":                 StepIdempotency.SAFE,

    # ── Notifications — 30 min cooldown ──────────────────────────────────
    "notify_oncall":              StepIdempotency.NOTIFY,
    "notify_security_team":       StepIdempotency.NOTIFY,
    "notify_team":                StepIdempotency.NOTIFY,
    "alert_db_recovery":          StepIdempotency.NOTIFY,
    "alert_learning_degraded":    StepIdempotency.NOTIFY,
    "alert_security_degraded":    StepIdempotency.NOTIFY,
    "alert_quantum_degraded":     StepIdempotency.NOTIFY,
    "alert_network_issue":        StepIdempotency.NOTIFY,

    # ── Restarts — 10 min cooldown ────────────────────────────────────────
    "restart_component":          StepIdempotency.RESTART,
    "restart_security_worker":    StepIdempotency.RESTART,
    "restart_agents":             StepIdempotency.RESTART,
    "restart_api_connections":    StepIdempotency.RESTART,
    "reinitialize_learning":      StepIdempotency.RESTART,
    "reset_reasoning_state":      StepIdempotency.RESTART,
    "rebuild_strategy_cache":     StepIdempotency.RESTART,
    "fallback_to_classical":      StepIdempotency.RESTART,
    "reconnect_database":         StepIdempotency.RESTART,

    # ── Mutating but recoverable — 15 min cooldown ────────────────────────
    "fix_config_issue":           StepIdempotency.MUTATING,
    "fix_critical_config":        StepIdempotency.MUTATING,
    "block_suspicious_ips":       StepIdempotency.MUTATING,
    "block_if_confirmed":         StepIdempotency.MUTATING,
    "enforce_encryption":         StepIdempotency.MUTATING,
    "enforce_least_privilege":    StepIdempotency.MUTATING,
    "reduce_cache_size":          StepIdempotency.MUTATING,
    "repair_storage":             StepIdempotency.MUTATING,

    # ── Destructive / high-impact — 60 min cooldown ───────────────────────
    "rotate_credentials":         StepIdempotency.DESTRUCTIVE,
    "rotate_api_keys":            StepIdempotency.DESTRUCTIVE,
    "rotate_secrets":             StepIdempotency.DESTRUCTIVE,
    "rotate_encryption_keys":     StepIdempotency.DESTRUCTIVE,
    "revoke_suspicious_sessions": StepIdempotency.DESTRUCTIVE,
    "revoke_all_sessions":        StepIdempotency.DESTRUCTIVE,
    "revoke_overprivileged":      StepIdempotency.DESTRUCTIVE,
    "backup_before_repair":       StepIdempotency.DESTRUCTIVE,
    "restore_from_backup":        StepIdempotency.DESTRUCTIVE,
    "generate_patch":             StepIdempotency.DESTRUCTIVE,
    "apply_via_asi":              StepIdempotency.DESTRUCTIVE,
}


@dataclass
class PlaybookStep:
    """
    A single actionable step inside a RemediationPlan.

    The 'capability' field references the Capability enum name from
    core/tools/capabilities.py and is used for semantic logging/discovery.
    The 'action' field is the handler key understood by _execute_playbook_plan()
    in the coordinator.

    Idempotency is enforced by the coordinator via _step_is_due() before
    any step is executed.  See StepIdempotency and STEP_COOLDOWNS.
    """
    capability:   str                            # e.g. "AUTO_REMEDIATE", "BLOCK_THREAT"
    action:       str                            # e.g. "block_suspicious_ips", "reconnect_database"
    description:  str                            # Human-readable one-liner
    params:       Dict[str, Any] = field(default_factory=dict)
    governance:   GovernanceTier = GovernanceTier.ROUTINE
    on_failure:   str            = "skip"        # "skip" | "abort" | "alert"
    order:        int            = 0             # Execution order (lower = first)
    idempotency:  Optional[StepIdempotency] = None  # None = auto-classify from ACTION_IDEMPOTENCY
    # Action name this step's meaning DEPENDS on having succeeded. A plan
    # containing a step is not the same as that step being valid to execute now:
    # "verify health after restart" asserts something about a restart that
    # happened. Running it after a FAILED restart reports on an event that never
    # occurred, which is worse than not checking at all.
    requires:     Optional[str]  = None

    def effective_idempotency(self) -> StepIdempotency:
        """Return the idempotency class for this step, auto-classified if not set."""
        if self.idempotency is not None:
            return self.idempotency
        return ACTION_IDEMPOTENCY.get(self.action, StepIdempotency.MUTATING)

    def cooldown_seconds(self) -> float:
        """Return the minimum seconds between executions of this step."""
        return STEP_COOLDOWNS[self.effective_idempotency()]


@dataclass
class RemediationPlan:
    """
    Structured response plan produced by the playbook for a single observation.
    Returned by all plan_XXX() methods and consumed by the coordinator.
    """
    trigger_id:      str                        # Finding ID, component name, etc.
    trigger_type:    str                        # "security_finding" | "unhealthy_component" | ...
    severity:        str                        # "critical" | "high" | "medium" | "low" | "info"
    summary:         str                        # One-line description for logs/memory
    steps:           List[PlaybookStep] = field(default_factory=list)
    notify:          bool               = False # Whether to send Slack notification
    store_to_memory: bool               = True  # Whether to persist plan execution to memory


# ============================================================================
# TIER 1 — Security playbook matrix
# ============================================================================
# Key: (AuditCategory.value, AuditSeverity.value)
# Value: list of PlaybookStep in execution order

_SECURITY_MATRIX: Dict[tuple, List[PlaybookStep]] = {

    # ── ACCESS CONTROL ───────────────────────────────────────────────────────
    ("access_control", "critical"): [
        PlaybookStep("AUDIT_TRAIL",   "audit_auth_logs",            "Audit recent authentication logs",         order=1),
        PlaybookStep("REVOKE_ACCESS", "revoke_suspicious_sessions", "Revoke suspicious active sessions",         order=2, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("MANAGE_SECRETS","rotate_credentials",          "Rotate affected credentials",               order=3, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("NOTIFY",        "notify_oncall",               "Alert on-call security engineer",           order=4),
        PlaybookStep("SCAN_SECURITY", "rescan_access_control",       "Rescan to verify remediation",              order=5, on_failure="alert"),
    ],
    ("access_control", "high"): [
        PlaybookStep("AUDIT_TRAIL",   "audit_auth_logs",            "Audit recent authentication logs",         order=1),
        PlaybookStep("NOTIFY",        "notify_security_team",        "Notify security team",                      order=2),
    ],
    ("access_control", "medium"): [
        PlaybookStep("AUDIT_TRAIL",   "audit_auth_logs",            "Audit recent authentication logs",         order=1),
    ],

    # ── AUTHENTICATION ────────────────────────────────────────────────────────
    ("authentication", "critical"): [
        PlaybookStep("REVOKE_ACCESS", "revoke_all_sessions",        "Revoke all active sessions",                order=1, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("MANAGE_SECRETS","rotate_api_keys",             "Rotate all API keys",                       order=2, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("NOTIFY",        "notify_oncall",               "Alert on-call security engineer",           order=3),
        PlaybookStep("SCAN_SECURITY", "rescan_authentication",       "Rescan authentication controls",            order=4),
    ],
    ("authentication", "high"): [
        PlaybookStep("AUDIT_TRAIL",   "audit_auth_logs",            "Audit authentication logs",                order=1),
        PlaybookStep("NOTIFY",        "notify_security_team",        "Notify security team",                      order=2),
    ],
    ("authentication", "medium"): [
        PlaybookStep("AUDIT_TRAIL",   "audit_auth_logs",            "Audit authentication logs",                order=1),
    ],

    # ── AUTHORIZATION ─────────────────────────────────────────────────────────
    ("authorization", "critical"): [
        PlaybookStep("IAM_ANALYSIS",           "audit_iam_policies",       "Audit IAM policies and permissions",        order=1),
        PlaybookStep("ENFORCE_LEAST_PRIVILEGE","enforce_least_privilege",   "Enforce least-privilege access model",      order=2, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("REVOKE_ACCESS",          "revoke_overprivileged",     "Revoke over-privileged access grants",      order=3, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("NOTIFY",                 "notify_oncall",             "Alert on-call engineer",                    order=4),
    ],
    ("authorization", "high"): [
        PlaybookStep("IAM_ANALYSIS",           "audit_iam_policies",       "Audit IAM policies",                        order=1),
        PlaybookStep("ENFORCE_LEAST_PRIVILEGE","enforce_least_privilege",   "Enforce least privilege",                   order=2, governance=GovernanceTier.IMPORTANT),
    ],
    ("authorization", "medium"): [
        PlaybookStep("IAM_ANALYSIS",           "audit_iam_policies",       "Audit IAM policies",                        order=1),
    ],

    # ── DATA INTEGRITY ────────────────────────────────────────────────────────
    ("data_integrity", "critical"): [
        PlaybookStep("BACKUP_DATABASE",  "backup_before_repair",      "Backup data before repair",                 order=1, on_failure="abort"),
        PlaybookStep("VALIDATE_DATA",    "audit_data_consistency",    "Audit data consistency",                    order=2),
        PlaybookStep("RESTORE_DATABASE", "restore_from_backup",       "Restore from last known good backup",       order=3, governance=GovernanceTier.CRITICAL),
        PlaybookStep("NOTIFY",           "notify_oncall",             "Alert on-call engineer",                    order=4),
    ],
    ("data_integrity", "high"): [
        PlaybookStep("VALIDATE_DATA",    "audit_data_consistency",    "Audit data consistency",                    order=1),
        PlaybookStep("NOTIFY",           "notify_team",               "Notify team of integrity issue",            order=2),
    ],
    ("data_integrity", "medium"): [
        PlaybookStep("VALIDATE_DATA",    "audit_data_consistency",    "Audit data consistency",                    order=1),
    ],

    # ── CONFIGURATION ─────────────────────────────────────────────────────────
    ("configuration", "critical"): [
        PlaybookStep("MANAGE_CONFIG",  "fix_critical_config",        "Apply critical configuration fix",          order=1, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("MANAGE_SECRETS", "rotate_secrets",             "Rotate any exposed secrets",                order=2, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("NOTIFY",         "notify_oncall",              "Alert on-call engineer",                    order=3),
        PlaybookStep("SCAN_SECURITY",  "rescan_configuration",       "Rescan configuration after fix",            order=4),
    ],
    ("configuration", "high"): [
        PlaybookStep("MANAGE_CONFIG",  "fix_config_issue",           "Apply configuration fix",                   order=1),
        PlaybookStep("MANAGE_SECRETS", "rotate_secrets",             "Rotate exposed secrets",                    order=2, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("SCAN_SECURITY",  "rescan_configuration",       "Rescan configuration after fix",            order=3),
    ],
    ("configuration", "medium"): [
        PlaybookStep("MANAGE_CONFIG",  "fix_config_issue",           "Apply configuration fix",                   order=1),
    ],

    # ── CODE SECURITY ─────────────────────────────────────────────────────────
    ("code_security", "critical"): [
        PlaybookStep("SECURITY_CODE_REVIEW",  "scan_codebase",       "Run full codebase security scan",           order=1),
        PlaybookStep("DEPENDENCY_SCAN",       "scan_dependencies",   "Scan dependencies for known CVEs",          order=2),
        PlaybookStep("GENERATE_SECURITY_FIX", "generate_patch",      "Generate security patch via ASI",           order=3, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("PATCH_MANAGEMENT",      "apply_via_asi",       "Apply patch via ASI self-improvement",      order=4, governance=GovernanceTier.CRITICAL),
        PlaybookStep("NOTIFY",                "notify_oncall",       "Alert on-call engineer",                    order=5),
    ],
    ("code_security", "high"): [
        PlaybookStep("SECURITY_CODE_REVIEW",  "scan_codebase",       "Run code security scan",                    order=1),
        PlaybookStep("DEPENDENCY_SCAN",       "scan_dependencies",   "Scan dependencies for CVEs",                order=2),
        PlaybookStep("GENERATE_SECURITY_FIX", "generate_patch",      "Generate security patch",                   order=3, governance=GovernanceTier.IMPORTANT),
    ],
    ("code_security", "medium"): [
        PlaybookStep("SECURITY_CODE_REVIEW",  "scan_codebase",       "Run code security scan",                    order=1),
        PlaybookStep("DEPENDENCY_SCAN",       "scan_dependencies",   "Scan dependencies for CVEs",                order=2),
    ],

    # ── ANOMALY DETECTION ─────────────────────────────────────────────────────
    ("anomaly_detection", "critical"): [
        PlaybookStep("DETECT_THREAT",   "investigate_anomaly",       "Investigate the detected anomaly",          order=1),
        PlaybookStep("ANALYZE_THREAT",  "threat_intel_lookup",       "Query threat intelligence sources",         order=2),
        PlaybookStep("BLOCK_THREAT",    "block_if_confirmed",        "Block confirmed threat source",             order=3, governance=GovernanceTier.IMPORTANT, on_failure="alert"),
        PlaybookStep("NOTIFY",          "notify_oncall",             "Alert on-call security engineer",           order=4),
    ],
    ("anomaly_detection", "high"): [
        PlaybookStep("DETECT_THREAT",   "investigate_anomaly",       "Investigate the detected anomaly",          order=1),
        PlaybookStep("ANALYZE_THREAT",  "threat_intel_lookup",       "Query threat intelligence sources",         order=2),
        PlaybookStep("NOTIFY",          "notify_security_team",      "Notify security team",                      order=3),
    ],
    ("anomaly_detection", "medium"): [
        PlaybookStep("DETECT_THREAT",   "investigate_anomaly",       "Investigate the detected anomaly",          order=1),
    ],

    # ── NETWORK SECURITY ──────────────────────────────────────────────────────
    ("network_security", "critical"): [
        PlaybookStep("BLOCK_THREAT",       "block_suspicious_ips",   "Block suspicious IP addresses",             order=1, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("CHECK_CONNECTIVITY", "verify_firewall_rules",  "Verify firewall rules are enforced",        order=2),
        PlaybookStep("NOTIFY",             "notify_oncall",          "Alert on-call engineer",                    order=3),
    ],
    ("network_security", "high"): [
        PlaybookStep("BLOCK_THREAT",       "block_suspicious_ips",   "Block suspicious IP addresses",             order=1),
        PlaybookStep("CHECK_CONNECTIVITY", "verify_firewall_rules",  "Verify firewall rules are enforced",        order=2),
    ],
    ("network_security", "medium"): [
        PlaybookStep("CHECK_CONNECTIVITY", "verify_firewall_rules",  "Verify firewall rules",                     order=1),
    ],

    # ── ENCRYPTION ────────────────────────────────────────────────────────────
    ("encryption", "critical"): [
        PlaybookStep("ENCRYPT_DATA", "enforce_encryption",          "Enforce encryption on sensitive data",       order=1, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("MANAGE_SECRETS","rotate_encryption_keys",     "Rotate encryption keys",                    order=2, governance=GovernanceTier.IMPORTANT),
        PlaybookStep("NOTIFY",       "notify_oncall",               "Alert on-call engineer",                    order=3),
    ],
    ("encryption", "high"): [
        PlaybookStep("ENCRYPT_DATA", "enforce_encryption",          "Enforce encryption on sensitive data",       order=1, governance=GovernanceTier.IMPORTANT),
    ],
    ("encryption", "medium"): [
        PlaybookStep("VALIDATE_DATA","audit_encryption_coverage",   "Audit encryption coverage",                  order=1),
    ],

    # ── COMPLIANCE ────────────────────────────────────────────────────────────
    ("compliance", "critical"): [
        PlaybookStep("COMPLIANCE_CHECK",  "run_full_compliance_scan",     "Run full compliance scan",              order=1),
        PlaybookStep("COMPLIANCE_REPORT", "generate_compliance_report",   "Generate compliance report",            order=2),
        PlaybookStep("NOTIFY",            "notify_oncall",                "Alert compliance officer",              order=3),
    ],
    ("compliance", "high"): [
        PlaybookStep("COMPLIANCE_CHECK",  "run_compliance_scan",          "Run targeted compliance scan",          order=1),
        PlaybookStep("COMPLIANCE_REPORT", "generate_compliance_report",   "Generate compliance report",            order=2),
    ],
    ("compliance", "medium"): [
        PlaybookStep("COMPLIANCE_CHECK",  "run_compliance_scan",          "Run compliance scan",                   order=1),
    ],
}

# Severity levels that warrant notify=True in the produced plan
_NOTIFY_SEVERITIES = {"critical", "high"}

# Generic fallback steps used when no specific matrix entry exists
_GENERIC_INVESTIGATE = PlaybookStep(
    "SCAN_SECURITY", "investigate_finding",
    "Investigate security finding",
    order=1
)
_GENERIC_NOTIFY = PlaybookStep(
    "NOTIFY", "notify_security_team",
    "Notify security team",
    order=2
)


# ============================================================================
# TIER 2 — Health playbook matrix
# ============================================================================
# Key: component name prefix (lowercase)
# Value: ordered recovery steps

_HEALTH_MATRIX: Dict[str, List[PlaybookStep]] = {
    "database": [
        PlaybookStep("BACKUP_DATABASE",  "backup_before_repair",      "Backup database state before repair",     order=1),
        PlaybookStep("RESTORE_DATABASE", "reconnect_database",         "Reconnect database connection pool",      order=2, on_failure="alert"),
        PlaybookStep("VALIDATE_DATA",    "verify_db_integrity",        "Verify database integrity post-repair",   order=3),
        PlaybookStep("NOTIFY",           "alert_db_recovery",          "Alert team about database recovery",      order=4),
    ],
    "memory": [
        PlaybookStep("MANAGE_PROCESS",    "gc_collect",                "Trigger Python garbage collection",       order=1),
        PlaybookStep("OPTIMIZE_COMPONENT","reduce_cache_size",          "Reduce in-memory cache allocation",       order=2),
        PlaybookStep("MONITOR_METRICS",   "track_memory_trend",        "Track memory usage trend for 5 minutes",  order=3),
    ],
    "learning": [
        PlaybookStep("SELF_REPAIR",  "reinitialize_learning",          "Reinitialize learning subsystem",         order=1),
        PlaybookStep("META_LEARN",   "rebuild_strategy_cache",         "Rebuild meta-learning strategy cache",    order=2),
        PlaybookStep("NOTIFY",       "alert_learning_degraded",        "Alert: learning subsystem degraded",      order=3),
    ],
    "security": [
        PlaybookStep("SELF_REPAIR",   "restart_security_worker",       "Restart security audit worker",           order=1),
        PlaybookStep("SCAN_SECURITY", "emergency_security_scan",       "Run emergency security scan post-restart",order=2),
        PlaybookStep("NOTIFY",        "alert_security_degraded",       "Alert: security monitoring degraded",     order=3, governance=GovernanceTier.IMPORTANT),
    ],
    "agents": [
        PlaybookStep("SELF_REPAIR",   "restart_agents",                "Restart degraded agent pool",             order=1),
        PlaybookStep("MONITOR_HEALTH","verify_agents_healthy",         "Verify agents are healthy post-restart",  order=2),
    ],
    "reasoning": [
        PlaybookStep("SELF_REPAIR",      "reset_reasoning_state",      "Reset reasoning engine state",            order=1),
        PlaybookStep("VALIDATE_APPROACH","verify_reasoning_output",    "Verify reasoning output validity",        order=2),
    ],
    "quantum": [
        PlaybookStep("SELF_REPAIR", "fallback_to_classical",           "Fall back to classical reasoning path",   order=1),
        PlaybookStep("NOTIFY",      "alert_quantum_degraded",          "Alert: quantum subsystem degraded",       order=2),
    ],
    "api": [
        PlaybookStep("CHECK_CONNECTIVITY","verify_api_connectivity",   "Verify API connectivity",                 order=1),
        PlaybookStep("SELF_REPAIR",       "restart_api_connections",   "Restart API connection pool",             order=2),
    ],
    "storage": [
        PlaybookStep("BACKUP_DATABASE",   "backup_before_repair",      "Backup storage before repair",            order=1),
        PlaybookStep("SELF_REPAIR",       "repair_storage",            "Repair storage layer",                    order=2),
        PlaybookStep("MONITOR_METRICS",   "track_storage_health",      "Monitor storage health trend",            order=3),
    ],
    "network": [
        PlaybookStep("CHECK_CONNECTIVITY","verify_network",            "Verify network connectivity",             order=1),
        PlaybookStep("DNS_LOOKUP",        "verify_dns_resolution",     "Verify DNS resolution is working",        order=2),
        PlaybookStep("NOTIFY",            "alert_network_issue",       "Alert: network connectivity issue",       order=3),
    ],
}

# Statuses that indicate a component needs recovery
_UNHEALTHY_STATUSES: Set[str] = {
    "unhealthy", "degraded", "error", "critical",
    "failing", "failed", "down", "unavailable", "timeout"
}

_GENERIC_HEALTH_STEPS = [
    PlaybookStep("SELF_REPAIR",   "restart_component",     "Restart component",                     order=1),
    PlaybookStep("MONITOR_HEALTH","verify_after_restart",  "Verify health after restart",           order=2,
                 requires="restart_component"),
]


# ============================================================================
# TIER 3 — Self-improvement: component target selection
# ============================================================================

# Components that are unhealthy get targeted for ASI improvement pass
# Same set as health statuses
_IMPROVEMENT_TARGET_STATUSES = _UNHEALTHY_STATUSES


# ============================================================================
# TIER 4 — Meta-learning: task types to evaluate
# ============================================================================

# All task type values (mirrors TaskType enum in shared_types.py)
_META_LEARNING_TASK_TYPES: List[str] = [
    "research",
    "analysis",
    "synthesis",
    "execution",
    "planning",
    "validation",
    "learning",
    "optimization",
    "security_remediation",
]

# Win rate below this threshold triggers adaptive strategy revision
META_LEARNING_LOW_WIN_RATE  = 0.35
# Win rate above this threshold triggers strategy consolidation
META_LEARNING_HIGH_WIN_RATE = 0.85


# ============================================================================
# TIER 4.5 — Strategy Adaptation Gate (robust statistical filtering)
# ============================================================================

class StrategyAdaptationGate:
    """
    Validates whether strategy adaptation should trigger based on:
    1. Minimum sample count (avoid noise)
    2. Binomial confidence interval (statistical rigor)
    3. Decay-weighted win rate (favor recent performance)
    4. Variance stability check (distinguish low-performance from oscillation)

    Prevents chaotic strategy thrashing while remaining sensitive to real degradation.
    """

    # Minimum executions before considering adaptation
    MIN_EXECUTIONS = 10

    # Binomial confidence level (95%)
    CONFIDENCE_LEVEL = 0.95

    # Decay factor for old data (exponential, α=0.2)
    DECAY_ALPHA = 0.2

    # Threshold: adapt if decay_weighted_win_rate < this
    ADAPT_WIN_RATE_THRESHOLD = 0.40

    # Threshold: adapt if variance > this (indicates instability, may need reset)
    ADAPT_VARIANCE_THRESHOLD = 0.25

    @staticmethod
    def should_adapt(
        task_type: str,
        executions: int,
        wins: int,
        recent_outcomes: Optional[List[bool]] = None,
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Determine if strategy adaptation should trigger.

        Args:
            task_type: TaskType.value for logging
            executions: Total execution count
            wins: Total win count
            recent_outcomes: Last N boolean outcomes [True=win, False=loss]

        Returns:
            (should_adapt, reason_dict) where reason_dict explains the decision
        """
        if recent_outcomes is None:
            recent_outcomes = []

        reason = {
            "task_type": task_type,
            "total_executions": executions,
            "total_wins": wins,
            "basic_win_rate": wins / max(executions, 1),
            "checks_passed": [],
            "checks_failed": [],
        }

        # ──── Check 1: Minimum sample size ────
        if executions < StrategyAdaptationGate.MIN_EXECUTIONS:
            reason["checks_failed"].append(
                f"sample_size: {executions} < {StrategyAdaptationGate.MIN_EXECUTIONS}"
            )
            reason["decision"] = "HOLD_INSUFFICIENT_SAMPLE"
            return False, reason

        reason["checks_passed"].append(
            f"sample_size: {executions} ≥ {StrategyAdaptationGate.MIN_EXECUTIONS}"
        )

        # ──── Check 2: Binomial confidence interval ────
        # Wilson score interval (more robust than Agresti-Coull for small n)
        ci_lower, ci_upper = StrategyAdaptationGate._wilson_ci(
            wins, executions, StrategyAdaptationGate.CONFIDENCE_LEVEL
        )

        reason["confidence_interval_95"] = {
            "lower": round(ci_lower, 3),
            "upper": round(ci_upper, 3),
        }

        # Adapt if lower bound is significantly below threshold
        adapt_threshold = StrategyAdaptationGate.ADAPT_WIN_RATE_THRESHOLD
        if ci_lower < adapt_threshold:
            reason["checks_passed"].append(
                f"ci_lower: {ci_lower:.3f} < {adapt_threshold} (statistically low)"
            )
        else:
            reason["checks_failed"].append(
                f"ci_lower: {ci_lower:.3f} ≥ {adapt_threshold} (not statistically low)"
            )
            reason["decision"] = "HOLD_NOT_STATISTICALLY_LOW"
            return False, reason

        # ──── Check 3: Decay-weighted win rate (favor recent) ────
        if recent_outcomes and len(recent_outcomes) > 0:
            decay_weight = StrategyAdaptationGate._calculate_decay_weights(len(recent_outcomes))
            recent_wins = sum(
                outcome * weight
                for outcome, weight in zip(recent_outcomes, decay_weight)
            )
            recent_total = sum(decay_weight)
            decay_win_rate = recent_wins / recent_total if recent_total > 0 else 0

            reason["decay_weighted_win_rate"] = round(decay_win_rate, 3)
            reason["recent_outcomes"] = recent_outcomes

            # Adapt if decay-weighted rate is also low
            if decay_win_rate >= adapt_threshold * 0.9:  # 90% of threshold
                reason["checks_failed"].append(
                    f"decay_win_rate: {decay_win_rate:.3f} ≥ {adapt_threshold * 0.9:.3f} "
                    f"(recent performance improving)"
                )
                reason["decision"] = "HOLD_RECENT_IMPROVING"
                return False, reason

            reason["checks_passed"].append(
                f"decay_win_rate: {decay_win_rate:.3f} < {adapt_threshold * 0.9:.3f} "
                f"(recent performance low)"
            )

        # ──── Check 4: Variance stability ────
        if recent_outcomes and len(recent_outcomes) > 2:
            variance = StrategyAdaptationGate._calculate_outcome_variance(recent_outcomes)
            reason["outcome_variance"] = round(variance, 3)

            # High variance = unstable, may need reset; low variance = consistently bad
            if variance > StrategyAdaptationGate.ADAPT_VARIANCE_THRESHOLD:
                reason["adaptation_reason"] = "high_variance_instability"
                reason["checks_passed"].append(
                    f"variance: {variance:.3f} > {StrategyAdaptationGate.ADAPT_VARIANCE_THRESHOLD} "
                    f"(oscillating, needs reset)"
                )
            else:
                reason["adaptation_reason"] = "consistent_low_performance"
                reason["checks_passed"].append(
                    f"variance: {variance:.3f} ≤ {StrategyAdaptationGate.ADAPT_VARIANCE_THRESHOLD} "
                    f"(consistently bad, needs improvement)"
                )

        # All checks passed → adapt
        reason["decision"] = "ADAPT"
        return True, reason

    @staticmethod
    def _wilson_ci(wins: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
        """
        Calculate Wilson score confidence interval for win rate.

        More robust than Agresti-Coull for small sample sizes.
        Handles edge cases (0 wins, all wins).

        Args:
            wins: Number of successes
            total: Total trials
            confidence: Confidence level (default 0.95 = 95%)

        Returns:
            (lower_bound, upper_bound) as proportions [0, 1]
        """
        import math

        if total == 0:
            return 0.0, 1.0

        p_hat = wins / total
        z = 1.96 if confidence == 0.95 else 2.576  # 95% or 99%

        denominator = 1 + z**2 / total
        center = (p_hat + z**2 / (2 * total)) / denominator
        margin = z * math.sqrt(p_hat * (1 - p_hat) / total + z**2 / (4 * total**2)) / denominator

        return max(0.0, center - margin), min(1.0, center + margin)

    @staticmethod
    def _calculate_decay_weights(n: int) -> List[float]:
        """
        Calculate exponential decay weights for last n outcomes.

        Most recent gets highest weight; older outcomes decay exponentially.
        Formula: weight[i] = exp(-decay_alpha * (n - i))

        Args:
            n: Number of outcomes

        Returns:
            List of n weights summing to ~n (for averaging)
        """
        import math

        alpha = StrategyAdaptationGate.DECAY_ALPHA
        weights = [math.exp(-alpha * (n - 1 - i)) for i in range(n)]

        # Normalize so sum ≈ n (for intuitive averaging)
        total = sum(weights)
        return [w * n / total for w in weights]

    @staticmethod
    def _calculate_outcome_variance(outcomes: List[bool]) -> float:
        """
        Calculate variance of outcome sequence (higher = more oscillation).

        Variance = mean((outcome - mean)^2)

        Args:
            outcomes: List of boolean outcomes

        Returns:
            Variance in range [0, 0.25] (max variance for binary data)
        """
        if len(outcomes) < 2:
            return 0.0

        numeric = [float(o) for o in outcomes]
        mean = sum(numeric) / len(numeric)
        variance = sum((x - mean) ** 2 for x in numeric) / len(numeric)

        return variance


# ============================================================================
# TIER 5 — Memory consolidation strategies
# ============================================================================

class ConsolidationStrategy(Enum):
    LLM_AUTONOMOUS = "llm_autonomous"   # llm._autonomous_memory_consolidation()
    TIER_UPGRADE   = "tier_upgrade"     # Upgrade high-importance short-term → long-term
    SUMMARY_WRITE  = "summary_write"    # Write a meta-memory consolidation summary record


# ============================================================================
# Main Playbook class
# ============================================================================

class IdleWorkPlaybook:
    """
    Deterministic decision graphs for all 6 idle priority tiers.

    Maps raw subsystem observations to structured, ordered action plans.
    The coordinator's _idle_XXX_work() methods call these plan_XXX() methods,
    then execute each RemediationPlan via _execute_playbook_plan().
    """

    # ── TIER 1: Security ──────────────────────────────────────────────────────

    def plan_security_response(
        self,
        findings: List[Any],          # List[SecurityAuditFinding]
        min_severity: str = "low",    # Ignore findings below this severity
    ) -> List[RemediationPlan]:
        """
        Map each security finding to a structured remediation plan.

        Covers ALL severity levels (not just CRITICAL) using the matrix above.
        Findings with no specific matrix entry get a generic investigation plan.
        Returns plans sorted from highest to lowest severity.
        """
        severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
        min_rank = severity_rank.get(min_severity.lower(), 0)

        plans: List[RemediationPlan] = []
        for finding in findings:
            category = getattr(finding, "category", None)
            severity = getattr(finding, "severity", None)
            if category is None or severity is None:
                continue

            cat_val = category.value if hasattr(category, "value") else str(category)
            sev_val = severity.value if hasattr(severity, "value") else str(severity)

            # Skip findings below requested minimum severity
            if severity_rank.get(sev_val, 0) < min_rank:
                continue

            # Exact matrix lookup → severity-fallback
            steps = (
                _SECURITY_MATRIX.get((cat_val, sev_val))
                or _SECURITY_MATRIX.get(("anomaly_detection", sev_val))
            )

            if not steps:
                # Generic fallback: always investigate; notify for high+
                steps = [_GENERIC_INVESTIGATE]
                if sev_val in _NOTIFY_SEVERITIES:
                    steps = [_GENERIC_INVESTIGATE, _GENERIC_NOTIFY]

            plans.append(RemediationPlan(
                trigger_id   = getattr(finding, "finding_id", "unknown"),
                trigger_type = "security_finding",
                severity     = sev_val,
                summary      = (
                    f"[{cat_val.upper()}:{sev_val.upper()}] "
                    f"{getattr(finding, 'title', 'Security Finding')}"
                ),
                steps        = sorted(steps, key=lambda s: s.order),
                notify       = sev_val in _NOTIFY_SEVERITIES,
                store_to_memory = True,
            ))

        # Return highest severity first
        plans.sort(key=lambda p: severity_rank.get(p.severity, 0), reverse=True)
        return plans

    # ── TIER 2: Health ────────────────────────────────────────────────────────

    def plan_health_response(
        self,
        component: str,
        status_data: Dict[str, Any],
    ) -> Optional[RemediationPlan]:
        """
        Map a single unhealthy component to a structured recovery plan.
        Returns None if the component is healthy / status is unknown.
        """
        status = str(status_data.get("status", "")).lower()
        if status not in _UNHEALTHY_STATUSES:
            return None

        # Prefix match — "database_primary" matches "database" key
        steps = None
        comp_lower = component.lower()
        for prefix, plan_steps in _HEALTH_MATRIX.items():
            if comp_lower.startswith(prefix):
                steps = plan_steps
                break

        if steps is None:
            steps = _GENERIC_HEALTH_STEPS

        sev = "critical" if status in {"critical", "down", "failed", "failing"} else "high"

        return RemediationPlan(
            trigger_id   = component,
            trigger_type = "unhealthy_component",
            severity     = sev,
            summary      = f"Component '{component}' is {status} — initiating recovery",
            steps        = sorted(steps, key=lambda s: s.order),
            notify       = sev == "critical",
            store_to_memory = True,
        )

    def plan_all_health_responses(
        self,
        health_data: Dict[str, Any],
    ) -> List[RemediationPlan]:
        """
        Iterate all components in the health snapshot and return a plan for
        each unhealthy one.  Plans are sorted critical-first.
        """
        severity_rank = {"critical": 2, "high": 1}
        plans: List[RemediationPlan] = []
        components = health_data.get("components", {}) or {}
        for comp_name, comp_data in components.items():
            if not isinstance(comp_data, dict):
                continue
            plan = self.plan_health_response(comp_name, comp_data)
            if plan is not None:
                plans.append(plan)
        plans.sort(key=lambda p: severity_rank.get(p.severity, 0), reverse=True)
        return plans

    # ── TIER 3: Self-improvement target selection ──────────────────────────────

    def plan_self_improvement_targets(
        self,
        health_data: Dict[str, Any],
        recent_failure_components: List[str],
    ) -> List[str]:
        """
        Return a prioritized list of improvement targets for an ASI improvement pass.

        Priority order:
          1. Critical/down components from health check   (reactive — fix broken things)
          2. Recently failed components from task history (reactive — address regressions)
          3. Degraded/unhealthy components from health check
        """
        critical_targets: List[str] = []
        degraded_targets: List[str] = []

        components = health_data.get("components", {}) or {}
        for comp_name, comp_data in components.items():
            if not isinstance(comp_data, dict):
                continue
            status = str(comp_data.get("status", "")).lower()
            if status in {"critical", "down", "failed", "failing"}:
                critical_targets.append(comp_name)
            elif status in _IMPROVEMENT_TARGET_STATUSES:
                degraded_targets.append(comp_name)

        # Merge reactive targets: critical first, then recent failures, then degraded
        seen: Set[str] = set()
        targets: List[str] = []
        for comp in critical_targets + recent_failure_components + degraded_targets:
            if comp and comp not in seen:
                targets.append(comp)
                seen.add(comp)

        return targets

    def plan_meta_learning_evaluation(self) -> List[str]:
        """
        Return the full ordered list of task type values to evaluate.
        All types are evaluated every meta-learning cycle so the bandit
        policy has complete performance data across all task families.
        """
        return list(_META_LEARNING_TASK_TYPES)

    # ── TIER 5: Memory consolidation strategy list ─────────────────────────────

    def plan_memory_consolidation(
        self,
        llm_has_consolidation_method: bool,
        uptime_hours: float,
    ) -> List[ConsolidationStrategy]:
        """
        Return an ordered list of consolidation strategies to attempt.
        The coordinator falls through to the next strategy if a previous
        one is unavailable or errors.

        - LLM_AUTONOMOUS: preferred — rich semantic consolidation via LLM
        - TIER_UPGRADE: runs when uptime >= 4h — moves aged short-term → long-term
        - SUMMARY_WRITE: always runs — audit trail of consolidation activity
        """
        strategies: List[ConsolidationStrategy] = []
        if llm_has_consolidation_method:
            strategies.append(ConsolidationStrategy.LLM_AUTONOMOUS)
        if uptime_hours >= 4.0:
            strategies.append(ConsolidationStrategy.TIER_UPGRADE)
        strategies.append(ConsolidationStrategy.SUMMARY_WRITE)
        return strategies

    # ── TIER 6: Exploration configuration ─────────────────────────────────────

    def plan_exploration_config(
        self,
        motivation:               Dict[str, Any],
        active_task_descriptions: Set[str],
        exploring_components:     Set[str],
        max_concurrent:           int,
        current_intrinsic_count:  int,
        directive:                Any = None,
    ) -> Dict[str, Any]:
        """
        Return exploration configuration for _run_exploration_cycle().

        Applies:
          - Capacity cap: don't spawn if already at max_concurrent intrinsic tasks
          - Description deduplication: via description_fingerprint()
          - Motivation-weighted goal count: higher curiosity → more goals
        """
        slots = max(0, max_concurrent - current_intrinsic_count)
        dims  = motivation.get("dimensions", {})
        curiosity = dims.get("curiosity", 0.5)
        novelty   = dims.get("novelty",   0.5)

        # When a BehavioralDirective is supplied this function is a TRANSLATOR,
        # not a second interpreter: the decision was already made by the
        # arbiter from appraisal. Reinterpreting curiosity here would put two
        # authorities on one decision. Raw-motivation mode is the fallback for
        # callers that have no appraisal yet.
        if directive is not None:
            return {
                "slots_available":         slots,
                "should_explore":          bool(directive.should_explore) and slots > 0,
                "max_goals":               max(0, min(slots, directive.max_goals)),
                "novelty_weight":          novelty,
                "verification_intensity":  directive.verification_intensity,
                "mode":                    directive.mode,
                "reason_codes":            list(directive.reason_codes),
                "active_task_descriptions": active_task_descriptions,
                "exploring_components":    exploring_components,
            }

        return {
            "slots_available":         slots,
            "should_explore":          slots > 0 and curiosity > 0.3,
            "max_goals":               min(slots, max(1, int(curiosity * 3))),
            "active_task_descriptions": active_task_descriptions,
            "exploring_components":    exploring_components,
            "novelty_weight":          novelty,
        }

    # ── Idempotency enforcement ────────────────────────────────────────────────

    @staticmethod
    def step_is_due(
        trigger_id:          str,
        step:                PlaybookStep,
        execution_log:       Dict[str, float],   # {log_key: last_executed_unix_ts}
        current_time_unix:   float,
    ) -> bool:
        """
        Return True if this step is allowed to execute right now.

        The execution log key is ``"{trigger_id}:{step.action}"`` so each
        (finding/component, action) pair is tracked independently.

        Steps classified as SAFE always return True (no cooldown).
        All other classes are gated by their cooldown window from
        STEP_COOLDOWNS.
        """
        idempotency = step.effective_idempotency()
        cooldown    = STEP_COOLDOWNS[idempotency]

        if cooldown <= 0.0:
            return True  # SAFE — always allowed

        log_key   = f"{trigger_id}:{step.action}"
        last_exec = execution_log.get(log_key, 0.0)
        elapsed   = current_time_unix - last_exec
        return elapsed >= cooldown

    @staticmethod
    def record_step_executed(
        trigger_id:        str,
        step:              PlaybookStep,
        execution_log:     Dict[str, float],
        current_time_unix: float,
    ) -> None:
        """
        Record that a step was just executed so future calls to step_is_due()
        will respect the cooldown.  Call this immediately after a step fires,
        regardless of whether it succeeded — the cooldown protects against
        duplicate attempts, not just duplicate successes.
        """
        log_key = f"{trigger_id}:{step.action}"
        execution_log[log_key] = current_time_unix

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def description_fingerprint(description: str) -> str:
        """
        Stable 12-char fingerprint for a goal description.
        Used to deduplicate intrinsic goals by semantic content,
        not just by target_component field.
        """
        normalized = " ".join(description.lower().split())[:120]
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
