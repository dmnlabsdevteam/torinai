#!/usr/bin/env python3
"""
Health Monitor
==============
Monitors system health and performance metrics

Purpose:
- Track component health status
- Monitor resource utilization
- Detect performance degradation
- Generate health reports
"""

import ast
import asyncio
import json
import logging
import os
import psutil
import socket
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

class _SkipBaseline(Exception):
    """Not an error: this reading must not become a component's first baseline."""



class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
    #: The component's host process is intentionally stopped. Distinct from
    #: UNHEALTHY/CRITICAL: a cognitive subsystem reading zero because the
    #: substrate was stopped by the operator has not failed and must not raise
    #: a regression or trip the watchdog into restarting it.
    OFFLINE = "offline"


# Ownership is declared once, in core.health.ownership, and imported by both
# this monitor and the dashboard CLI so the classification cannot drift. The
# guardian grades only 'system' components, the substrate only 'substrate' ones;
# a stopped substrate's internals are shown offline from its heartbeat rather
# than graded to zero by a process that cannot see them.
from core.health.ownership import (  # noqa: E402
    SUBSTRATE_OWNED_COMPONENTS, component_owner)

#: Backwards-compatible alias for the earlier, narrower name.
SUBSTRATE_HOSTED_COMPONENTS = SUBSTRATE_OWNED_COMPONENTS


@dataclass
class ComponentHealth:
    """Component health data"""
    component: str
    status: HealthStatus
    timestamp: datetime
    metrics: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    uptime_seconds: float = 0.0
    last_check: Optional[datetime] = None
    check_count: int = 0
    error_count: int = 0


@dataclass
class HealthMetric:
    """One normalized health signal, declared by the subsystem that measured it.

    The subsystem owns measurement AND normalization; the central evaluator owns
    aggregation, criticality and the final status. Previously the evaluator
    inferred meaning from metric NAMES -- treating any `*_rate` as
    higher-is-better and matching cost substrings -- which made it responsible
    for understanding milliseconds, pool depths and classifier scores it has no
    business knowing. A metric now arrives already normalized, with its own
    weight and its own declaration of whether it is required or a hard gate.
    """
    name: str
    raw_value: Any
    normalized: Optional[float]       # 0.0-1.0, or None when UNMEASURED
    weight: float = 1.0
    required: bool = False            # absence blocks a confident HEALTHY
    critical: bool = False            # False/0.0 hard-fails the component
    reason: Optional[str] = None


def higher_is_better(value: float, fail: float, healthy: float) -> float:
    """Success rates, availability, coverage."""
    if healthy == fail:
        return 1.0 if value >= healthy else 0.0
    return max(0.0, min(1.0, (value - fail) / (healthy - fail)))


def lower_is_better(value: float, fail: float, healthy: float) -> float:
    """Latency, error rate, saturation."""
    if fail == healthy:
        return 1.0 if value <= healthy else 0.0
    return max(0.0, min(1.0, (fail - value) / (fail - healthy)))


def invariant(passed: bool) -> float:
    """A capability either holds or it does not."""
    return 1.0 if passed else 0.0


@dataclass
class SystemMetrics:
    """System-level metrics"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_active: bool
    process_count: int
    thread_count: int
    file_descriptors: int = 0
    load_average: tuple = (0.0, 0.0, 0.0)


class HealthMonitor:
    """
    Health Monitor

    Purpose:
    - Monitor system and component health
    - Track performance metrics
    - Detect anomalies and issues
    - Generate health reports

    Usage:
        monitor = HealthMonitor()
        health = await monitor.check_component_health("database")
        system_health = await monitor.get_system_health()
    """

    #: THE component vocabulary for the substrate.
    #:
    #: Four different vocabularies existed for the same subsystems: this class's
    #: bare name list, EnhancedASISelfImprovement's hardcoded five
    #: (chat_agent/memory_system/reasoning_engine/...), the metric keys that
    #: intrinsic_motivation was writing into unified.component_health, and the
    #: unified.components registry -- which was designed for exactly this and
    #: sat empty because its only writers use SQLite syntax in a dead migration
    #: script. Nothing could join a measurement to the thing measured.
    #:
    #: `module` is the import this component's health check actually reaches
    #: for, verified to resolve. `monitoring_enabled=False` records a component
    #: that EXISTS but is deliberately not monitored -- quantum is disabled in
    #: this deployment (qiskit_algorithms is absent), and saying so here is the
    #: honest form. Removing the entry would erase the fact that it exists.
    COMPONENT_MANIFEST: Dict[str, Dict[str, Any]] = {
        'database':         {'type': 'infrastructure', 'category': 'storage',
                             'module': 'core.database.unified_database_postgres',
                             'description': 'PostgreSQL unified store (hot/cold tiers)',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'connection_pool': {
                                     'module': 'core.database.unified_database_postgres',
                                     'description': 'asyncpg connection pool',
                                     'metric_prefixes': ('pool_',)},
                             }},
        'memory':           {'type': 'cognitive', 'category': 'memory',
                             'module': 'core.agents.memory_agent',
                             'description': 'Memory agent and tiered memory store',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'postgres_storage': {
                                     'module': 'core.memory.storage.postgres_storage',
                                     'description': 'Tiered memory store (hot/cold)',
                                     'metric_prefixes': ('storage_',)},
                                 'cache': {
                                     'module': 'core.agents.memory_agent',
                                     'description': 'In-process memory cache',
                                     'metric_prefixes': ('cache_',)},
                                 'embedding_service': {
                                     'module': 'core.memory',
                                     'description': 'Embedding generation for semantic recall',
                                     'metric_prefixes': ('embedding_',)},
                             }},
        'learning':         {'type': 'cognitive', 'category': 'learning',
                             'module': 'core.learning.enhanced_asi_self_improvement',
                             'description': 'Self-improvement and meta-learning',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'asi_self_improvement': {
                                     'module': 'core.learning.enhanced_asi_self_improvement',
                                     'description': 'ASI improvement cycle orchestrator',
                                     'metric_prefixes': ('asi_',)},
                                 'performance_profiler': {
                                     'module': 'core.learning.performance_profiler',
                                     'description': 'Per-operation timing and throughput',
                                     'metric_prefixes': ('profiler_',)},
                             }},
        'reasoning':        {'type': 'cognitive', 'category': 'reasoning',
                             'module': 'core.reasoning.neural_bridge',
                             'description': 'Neural-symbolic reasoning bridge',
                             'monitoring_enabled': True,
                             # Both are probed by _check_reasoning_health today and
                             # their readings are merged into one verdict, so a
                             # dead neural bridge and a dead Bayesian engine are
                             # the same "reasoning: degraded".
                             'subcomponents': {
                                 'neural_bridge': {
                                     'module': 'core.reasoning.neural_bridge',
                                     'description': 'Neural-symbolic bridge',
                                     'metric_prefixes': ('neural_bridge_', 'reasoning_')},
                                 'bayesian_uncertainty': {
                                     'module': 'core.reasoning.bayesian_uncertainty',
                                     'description': 'Bayesian uncertainty estimation',
                                     'metric_prefixes': ('bayesian_',)},
                             }},
        'agents':           {'type': 'cognitive', 'category': 'orchestration',
                             'module': 'core.agents.autonomous.task_queue',
                             'description': 'Autonomous agents and task queue',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'task_queue': {
                                     'module': 'core.agents.autonomous.task_queue',
                                     'description': 'Autonomous task queue',
                                     # 'task_' alone also matched
                                     # task_execution_pool_*, so two sub-components
                                     # claimed the same readings. The queue's own
                                     # metrics are queue_* plus task_failure_rate.
                                     'metric_prefixes': ('queue_', 'task_failure_rate')},
                             }},
        'llm':              {'type': 'cognitive', 'category': 'inference',
                             'module': 'core.services.unified_llm',
                             'description': 'Unified local LLM inference service',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'model': {
                                     'module': 'core.services.unified_llm',
                                     'description': 'Loaded inference model',
                                     'metric_prefixes': ('llm_model_',)},
                                 'inference_queue': {
                                     'module': 'core.services.unified_llm',
                                     'description': 'Inference job queue and worker',
                                     'metric_prefixes': ('llm_queue_',)},
                             }},
        'quantum':          {'type': 'cognitive', 'category': 'reasoning',
                             'module': 'core.quantum.quantum_factory',
                             'description': 'Quantum reasoning (disabled: no IBM access, '
                                            'qiskit_algorithms not installed)',
                             'monitoring_enabled': False},
        'governance':       {'type': 'governance', 'category': 'policy',
                             'module': 'core.governance.unified_governance_trigger_system',
                             'description': 'Governance trigger evaluation',
                             'monitoring_enabled': True},
        'safety':           {'type': 'safety', 'category': 'commitment',
                             'module': 'core.safety.commitment_contract_manager',
                             'description': 'Commitment contracts and safety enforcement',
                             'monitoring_enabled': True},
        'security':         {'type': 'security', 'category': 'control',
                             'module': 'core.security.controller',
                             'description': 'Security controller and request validation',
                             'monitoring_enabled': True},
        'threat_intel':     {'type': 'security', 'category': 'intelligence',
                             'module': 'core.security',
                             'description': 'Threat intelligence lookups and cache',
                             'monitoring_enabled': True},
        'firewall':         {'type': 'security', 'category': 'network',
                             'module': 'core.security',
                             'description': 'Firewall rules and IP blocking',
                             'monitoring_enabled': True},
        'content_security': {'type': 'security', 'category': 'scanning',
                             'module': 'core.security.content_security',
                             'description': 'Content scanning for unsafe payloads',
                             'monitoring_enabled': True},
        'malware_sandbox':  {'type': 'security', 'category': 'scanning',
                             'module': 'core.security.malware_sandbox',
                             'description': 'Malware detonation sandbox',
                             'monitoring_enabled': True},
        # THE GUARDIAN'S ACTIVE SECURITY SCANNER, as its own system component.
        # It was a probed sub of 'security' (the substrate's request-validation
        # controller), which conflated an always-on guardian scanner with a
        # substrate-internal gate: its 55-finding backlog was folded into the
        # controller's score, and it inherited 'substrate' ownership though the
        # guardian runs it. Separated here so each is graded by its true owner.
        'security_audit':   {'type': 'security', 'category': 'audit',
                             'module': 'core.security.security_audit_worker',
                             'description': 'Continuous security audit: findings and resolution',
                             'monitoring_enabled': True},
        'health_system':    {'type': 'infrastructure', 'category': 'observability',
                             'module': 'core.health.health_monitor',
                             'description': 'The health system itself: watchdog and recovery',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'recovery_manager': {
                                     'module': 'core.health.recovery_manager',
                                     'description': 'Automatic failure recovery',
                                     'metric_prefixes': ('recovery_',)},
                                 'watchdog': {
                                     'module': 'core.health.system_watchdog',
                                     'description': 'Watches the monitor itself',
                                     'metric_prefixes': ('watchdog_',)},
                             }},
        'execution':        {'type': 'cognitive', 'category': 'control',
                             'module': 'core.execution.iteration_controller',
                             'description': 'Iteration budgets and convergence gating',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'convergence_gate': {
                                     'module': 'core.execution.convergence_gate',
                                     'description': 'Convergence decisions',
                                     'metric_prefixes': ('convergence_',)},
                                 'iteration_controller': {
                                     'module': 'core.execution.iteration_controller',
                                     'description': 'Iteration budget allocation',
                                     'metric_prefixes': ('iteration_',)},
                             }},
        'system_awareness': {'type': 'infrastructure', 'category': 'awareness',
                             'module': 'core.system.environment_state',
                             'description': 'Environment, service discovery, topology',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'discovery': {
                                     'module': 'core.system.active_discovery',
                                     'description': 'Active service discovery',
                                     'metric_prefixes': ('discovery_',)},
                                 'topology': {
                                     'module': 'core.system.infrastructure_topology',
                                     'description': 'Infrastructure topology and SPOFs',
                                     'metric_prefixes': ('topology_',)},
                             }},
        'intelligence':     {'type': 'cognitive', 'category': 'prediction',
                             'module': 'core.intelligence.predictive_intelligence_system',
                             'description': 'Predictive intelligence',
                             'monitoring_enabled': True},
        'metrics_export':   {'type': 'infrastructure', 'category': 'observability',
                             'module': 'core.monitoring.prometheus_exporter',
                             'description': 'Prometheus metrics export',
                             'monitoring_enabled': True},
        'simulation':       {'type': 'library', 'category': 'modelling',
                             'module': 'core.simulation.system_dynamics',
                             'description': 'System dynamics and numerical simulation',
                             'monitoring_enabled': True},
        'optimization':     {'type': 'library', 'category': 'modelling',
                             'module': 'core.optimization.optimizers',
                             'description': 'Optimizers',
                             'monitoring_enabled': True},
        'utils':            {'type': 'library', 'category': 'support',
                             'module': 'core.utils.env_loader',
                             'description': 'Ports, env loading, notifications, chunking',
                             'monitoring_enabled': True},
        'api_surface':      {'type': 'integration', 'category': 'surface',
                             'module': 'core.api.thinking_state_api',
                             'description': 'API surfaces: thinking-state, device auth, key attestation',
                             'monitoring_enabled': True},
        'tools':            {'type': 'capability', 'category': 'action',
                             'module': 'core.tools.tool_registry',
                             'description': 'Tool registry: everything the agent can act with',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'registry': {
                                     'module': 'core.tools.tool_registry',
                                     'description': 'Tool inventory and indexes',
                                     'metric_prefixes': ('tools_total', 'tools_eager',
                                                         'tools_lazy', 'tools_loaded',
                                                         'tools_categories',
                                                         'tools_capabilities_indexed')},
                                 'usage_record': {
                                     'module': 'core.learning.adaptive_tool_learning',
                                     'description': 'Persisted tool outcome history',
                                     'metric_prefixes': ('tools_recorded_', 'tools_session_')},
                             }},
        'domain':           {'type': 'cognitive', 'category': 'knowledge',
                             'module': 'core.domain.domain_registry',
                             'description': 'Domain knowledge and cross-domain correspondence',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'registry': {
                                     'module': 'core.domain.domain_registry',
                                     'description': 'Domains and learned concepts',
                                     'metric_prefixes': ('domain_total', 'domain_populated',
                                                         'domain_empty', 'domain_learned_',
                                                         'domain_projected_')},
                                 'cross_domain_mappings': {
                                     'module': 'core.domain.universal_ontology',
                                     'description': 'Validated cross-domain correspondences',
                                     'metric_prefixes': ('domain_mappings_',)},
                                 'knowledge_transfer': {
                                     'module': 'core.learning.unified_learning_system',
                                     'description': 'Transfers and their resolved outcomes',
                                     'metric_prefixes': ('domain_transfers_',)},
                             }},
        'chaos':            {'type': 'resilience', 'category': 'testing',
                             'module': 'core.chaos.safety_controller',
                             'description': 'Chaos experiment safety controller',
                             'monitoring_enabled': True},
        'api':              {'type': 'integration', 'category': 'external',
                             'module': 'core.integration.external_api_integration_manager',
                             'description': 'External API providers and cost tracking',
                             'monitoring_enabled': True},
        'backup':           {'type': 'infrastructure', 'category': 'durability',
                             'module': 'core.services.backup_scheduler',
                             'description': 'Scheduled backups',
                             'monitoring_enabled': True,
                             'subcomponents': {
                                 'scheduler': {
                                     'module': 'core.services.backup_scheduler',
                                     'description': 'Backup scheduling loop',
                                     'metric_prefixes': ('backup_scheduler_',)},
                             }},
        'storage':          {'type': 'infrastructure', 'category': 'host',
                             'module': 'psutil',
                             'description': 'Host disk capacity',
                             'monitoring_enabled': True},
        'network':          {'type': 'infrastructure', 'category': 'host',
                             'module': 'psutil',
                             'description': 'Host network throughput',
                             'monitoring_enabled': True},
    }

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Metrics a subsystem normalized itself, keyed by component.
        self._declared_metrics: Dict[str, List[HealthMetric]] = {}

        # Health tracking
        self.component_health: Dict[str, ComponentHealth] = {}
        self.health_history: List[SystemMetrics] = []
        self.max_history_size = 1000

        # Monitoring state
        self.is_monitoring = False
        self.monitor_task = None
        self.check_interval = self.config.get('check_interval', 30)  # seconds

        # Thresholds
        self.thresholds = {
            'cpu_warning': 70.0,
            'cpu_critical': 90.0,
            'memory_warning': 75.0,
            'memory_critical': 90.0,
            'disk_warning': 80.0,
            'disk_critical': 95.0,
            'error_rate_warning': 0.05,  # 5%
            'error_rate_critical': 0.15   # 15%
        }

        # Statistics
        self.stats = {
            'total_checks': 0,
            'healthy_checks': 0,
            'degraded_checks': 0,
            'unhealthy_checks': 0,
            'critical_checks': 0,
            'last_check_time': None,
            'uptime_start': datetime.now()
        }

        # WHICH LAYER THIS MONITOR SPEAKS FOR. 'system' = the always-on guardian,
        # 'substrate' = the substrate process, 'all' = both (single-process
        # deployments / tests). Each process grades ONLY the components it owns,
        # so no process reports on a subsystem it does not host. Read from the
        # environment so a process can declare itself before the singleton is
        # built; changeable later via set_scope().
        self.scope: str = (os.getenv("TORINAI_HEALTH_SCOPE", "all") or "all").strip().lower()

        # Derived from COMPONENT_MANIFEST so the set of monitored components and
        # their description are ONE declaration. Synced to unified.components in
        # initialize(), which is what the improvement system resolves against.
        self._monitored_components: List[str] = self._components_in_scope()

        logger.info(
            "HealthMonitor initialized (scope=%s, %d components monitored, %d declared)",
            self.scope, len(self._monitored_components), len(self.COMPONENT_MANIFEST))

    def _components_in_scope(self) -> List[str]:
        """Monitor-enabled components this monitor's scope is responsible for."""
        return [
            name for name, spec in self.COMPONENT_MANIFEST.items()
            if spec["monitoring_enabled"]
            and (self.scope == "all" or component_owner(name) == self.scope)
        ]

    def set_scope(self, scope: str) -> None:
        """Declare which layer this monitor grades, and re-scope its component set.

        Called by the guardian ('system') and the substrate ('substrate') so
        each grades only what it owns. Idempotent.
        """
        self.scope = (scope or "all").strip().lower()
        self._monitored_components = self._components_in_scope()
        logger.info("HealthMonitor scope set to %s (%d components monitored)",
                    self.scope, len(self._monitored_components))

    async def initialize(self):
        """Initialize health monitor (registers components, starts monitoring)"""
        await self.sync_component_registry()
        await self.start_monitoring()
        logger.info("HealthMonitor started")

    #: Where core/ lives, for structural discovery.
    CORE_ROOT = Path(__file__).resolve().parents[1]

    @classmethod
    def discover_components(cls) -> Dict[str, Dict[str, Any]]:
        """The substrate's real component tree, read from the code.

        A hand-written list cannot describe 23 packages and 224 modules, and it
        rots the moment a module moves -- which is how four different component
        vocabularies came to exist. This reads the tree instead.

        A package or module is declared only if it DEFINES something (a class or
        a function). An empty shell is not a component: core/cache, core/logs,
        core/databases, core/reporting and core/neural_bridge hold no modules at
        all, and declaring them would put components in the registry that no
        code corresponds to.

        Ids are the dotted module path with `core.` stripped, so a component's
        id and its import are the same fact stated once.
        """
        found: Dict[str, Dict[str, Any]] = {}

        def walk(pkg_dir: Path, parent_id: Optional[str]) -> None:
            pkg_id = f"{parent_id}.{pkg_dir.name}" if parent_id else pkg_dir.name
            modules, defines = [], 0
            for m in sorted(pkg_dir.glob("*.py")):
                if m.name == "__init__.py":
                    continue
                try:
                    tree = ast.parse(m.read_text(errors="ignore"))
                except SyntaxError:
                    logger.warning("Component discovery: %s does not parse", m)
                    continue
                classes = sum(1 for n in tree.body if isinstance(n, ast.ClassDef))
                funcs = sum(1 for n in tree.body
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
                if classes or funcs:
                    modules.append((m, classes)); defines += 1

            subpkgs = [d for d in sorted(pkg_dir.iterdir())
                       if d.is_dir() and d.name != "__pycache__"
                       and any(p.suffix == ".py" for p in d.rglob("*.py"))]
            if not modules and not subpkgs:
                return

            found[pkg_id] = {"kind": "package", "parent": parent_id,
                             "module": f"core.{pkg_id}", "classes": 0}
            for m, classes in modules:
                found[f"{pkg_id}.{m.stem}"] = {
                    "kind": "module", "parent": pkg_id,
                    "module": f"core.{pkg_id}.{m.stem}", "classes": classes}
            for d in subpkgs:
                walk(d, pkg_id)

        for d in sorted(cls.CORE_ROOT.iterdir()):
            if d.is_dir() and d.name != "__pycache__":
                walk(d, None)
        return found

    @classmethod
    def _monitored_module_ids(cls) -> Dict[str, str]:
        """component_id -> health-check name, for components a check measures.

        The check names are CAPABILITIES ("llm", "firewall"), not packages --
        `llm` is core/services/unified_llm.py. Mapping them onto the structural
        id keeps ONE id space: monitoring is an attribute of a component, not a
        parallel list of names.
        """
        mapping: Dict[str, str] = {}
        for name, spec in cls.COMPONENT_MANIFEST.items():
            module = spec.get("module") or ""
            if module.startswith("core."):
                mapping.setdefault(module[len("core."):], name)
        return mapping

    async def sync_component_registry(self) -> int:
        """Declare this substrate's components into unified.components.

        The registry table exists with exactly the right shape -- component_id,
        type, category, dependencies, capabilities, monitoring_enabled -- and
        held zero rows, because its only writers live in a dead SQLite migration
        script (`INSERT OR REPLACE`, `strftime`) that nothing imports. So every
        consumer invented its own component list instead.

        This is the declaration, and it is the one both the health monitor and
        the improvement system resolve against. Only the declared fields are
        written: health_score and last_health_check belong to measurement, not
        to declaration, and are left to the assessment path.
        """
        from core.database import get_database_manager

        db = get_database_manager()
        await db.initialize()

        async def declare(component_id, name, ctype, category, description,
                          enabled, module, parent):
            await db.execute_query(
                """
                INSERT INTO unified.components
                    (component_id, component_name, component_type,
                     component_category, description, status,
                     monitoring_enabled, dependencies, parent_component_id,
                     last_update)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, NOW())
                ON CONFLICT (component_id) DO UPDATE SET
                    component_type      = EXCLUDED.component_type,
                    component_category  = EXCLUDED.component_category,
                    description         = EXCLUDED.description,
                    monitoring_enabled  = EXCLUDED.monitoring_enabled,
                    dependencies        = EXCLUDED.dependencies,
                    parent_component_id = EXCLUDED.parent_component_id,
                    last_update         = NOW()
                """,
                (component_id, name, ctype, category, description,
                 'declared' if enabled else 'not_monitored', enabled,
                 json.dumps({'module': module}), parent),
                commit=True,
            )

        # EVERYTHING THAT EXISTS, not only what happens to have a check.
        #
        # The registry previously held the 19 names the health monitor probes --
        # about 5% of the substrate. Everything else was invisible to it, which
        # is the same condition that let four vocabularies drift apart. What a
        # check measures is recorded as an ATTRIBUTE (monitoring_enabled), so
        # the unmonitored 95% is stated rather than omitted, and coverage
        # becomes a number instead of an assumption.
        structural = self.discover_components()
        monitored = self._monitored_module_ids()

        written = 0
        # Parents before children: parent_component_id is a self-referencing FK.
        for cid in sorted(structural, key=lambda k: (k.count('.'), k)):
            spec = structural[cid]
            check = monitored.get(cid)
            curated = self.COMPONENT_MANIFEST.get(check, {}) if check else {}
            await declare(
                cid, cid.rsplit('.', 1)[-1],
                curated.get('type', spec['kind']),
                curated.get('category', cid.split('.')[0]),
                curated.get('description',
                            f"{spec['kind']} {spec['module']}"
                            + (f" ({spec['classes']} classes)" if spec['classes'] else "")),
                bool(check) and curated.get('monitoring_enabled', False),
                spec['module'], spec['parent'])
            written += 1

        # Capabilities that are measured but are not a single module: the
        # inference queue inside unified_llm, the pool inside the database
        # client, the firewall inside the integrated security system. Declared
        # as runtime parts of the component they live in, so a measurement has
        # somewhere to attach without inventing a module that does not exist.
        for name, spec in self.COMPONENT_MANIFEST.items():
            module = spec.get('module') or ''
            host = module[len("core."):] if module.startswith("core.") else None
            if host is None or host not in structural:
                continue          # psutil-backed capabilities (storage, network)
            for sub, sub_spec in (spec.get('subcomponents') or {}).items():
                sub_module = sub_spec.get('module') or ''
                sub_id = (sub_module[len("core."):]
                          if sub_module.startswith("core.")
                          and sub_module[len("core."):] in structural
                          else f"{host}.{sub}")
                if sub_id in structural:
                    continue      # already declared structurally; do not duplicate
                await declare(sub_id, sub, 'runtime_part',
                              spec.get('category', 'runtime'),
                              sub_spec['description'],
                              spec['monitoring_enabled'], sub_module or module, host)
                written += 1

        # CAPABILITIES, declared under the id the health store keys on.
        #
        # Structural ids are module paths (agents.autonomous.task_queue); the
        # health monitor measures CAPABILITIES (agents.task_queue, llm) and
        # writes unified.component_health under those. Declaring only the
        # modules left the two tables in different namespaces -- a join matched
        # 9 of 76 and duplicated wherever a capability and a module share a bare
        # name. The capability is declared as its own row, linked to the module
        # it is implemented by, so one id space addresses both.
        for name, spec in self.COMPONENT_MANIFEST.items():
            module = spec.get('module') or ''
            host = module[len("core."):] if module.startswith("core.") else None
            await declare(name, name, spec['type'], spec['category'],
                          spec['description'], spec['monitoring_enabled'],
                          module, host if host in structural else None)
            written += 1
            for sub, sub_spec in self._subcomponent_specs(name).items():
                await declare(f"{name}.{sub}", sub, 'capability_part',
                              spec['category'], sub_spec['description'],
                              spec['monitoring_enabled'],
                              sub_spec.get('module') or module, name)
                written += 1

        logger.info(
            "Component registry synced: %d component(s) declared, %d monitored",
            written, len(monitored))
        return written

    async def monitored_components(self) -> List[str]:
        """Components to monitor, read from the registry.

        Resolving through unified.components rather than the in-process list is
        what makes the registry authoritative: disabling a component becomes a
        row change both this monitor and the improvement system observe, instead
        of an edit that only one of them sees.
        """
        from core.database import get_database_manager

        db = get_database_manager()
        rows = await db.execute_query(
            "SELECT component_name FROM unified.components "
            "WHERE monitoring_enabled IS TRUE ORDER BY component_name",
            fetch_all=True,
        ) or []
        if not rows:
            raise RuntimeError(
                "unified.components has no monitoring-enabled component; the "
                "registry was never synced and the monitored set is unknown")
        return [r["component_name"] for r in rows]

    async def check_component_health(
        self,
        component: str,
        custom_checks: Dict[str, Any] = None
    ) -> ComponentHealth:
        """
        Check health of a specific component

        Args:
            component: Component name
            custom_checks: Optional custom health checks

        Returns:
            ComponentHealth with status and metrics
        """
        try:
            start_time = time.time()

            # Get or create component health record
            if component not in self.component_health:
                self.component_health[component] = ComponentHealth(
                    component=component,
                    status=HealthStatus.UNKNOWN,
                    timestamp=datetime.now()
                )

            health = self.component_health[component]
            health.check_count += 1
            health.last_check = datetime.now()

            # Collect metrics
            metrics = {}
            issues = []

            # Component-specific health checks
            if component == "database":
                metrics, issues = await self._check_database_health()
            elif component == "memory":
                metrics, issues = await self._check_memory_health()
            elif component == "learning":
                metrics, issues = await self._check_learning_health()
            elif component == "reasoning":
                metrics, issues = await self._check_reasoning_health()
            elif component == "agents":
                metrics, issues = await self._check_agents_health()
            elif component == "security":
                metrics, issues = await self._check_security_health()
            elif component == "security_audit":
                metrics, issues = await self._check_security_audit_health()
            elif component == "storage":
                metrics, issues = await self._check_storage_health()
            elif component == "api":
                metrics, issues = await self._check_api_health()
            elif component == "quantum":
                metrics, issues = await self._check_quantum_health()
            elif component == "network":
                metrics, issues = await self._check_network_health()
            elif component == "llm":
                metrics, issues = await self._check_llm_health()
            elif component == "governance":
                metrics, issues = await self._check_governance_health()
            elif component == "chaos":
                metrics, issues = await self._check_chaos_health()
            elif component == "safety":
                metrics, issues = await self._check_safety_health()
            elif component == "backup":
                metrics, issues = await self._check_backup_health()
            elif component == "threat_intel":
                metrics, issues = await self._check_threat_intel_health()
            elif component == "firewall":
                metrics, issues = await self._check_firewall_health()
            elif component == "content_security":
                metrics, issues = await self._check_content_security_health()
            elif component == "malware_sandbox":
                metrics, issues = await self._check_malware_sandbox_health()
            elif component == "tools":
                metrics, issues = await self._check_tools_health()
            elif component == "domain":
                metrics, issues = await self._check_domain_health()
            elif component == "health_system":
                metrics, issues = await self._check_health_system_health()
            elif component == "execution":
                metrics, issues = await self._check_execution_health()
            elif component == "system_awareness":
                metrics, issues = await self._check_system_awareness_health()
            elif component == "intelligence":
                metrics, issues = await self._check_intelligence_health()
            elif component == "metrics_export":
                metrics, issues = await self._check_metrics_export_health()
            elif component in self._LIBRARY_PACKAGES:
                metrics, issues = await self._check_library_health(component)
            else:
                # Generic health check
                metrics, issues = await self._generic_health_check(component, custom_checks)

            # A SUBSYSTEM THAT REPORTS ITSELF DOWN IS NOT HEALTHY.
            #
            # Status is derived from `issues` alone, but the checks record
            # failure states as METRICS -- neural_bridge_initialized=False,
            # safety_contracts_initialized=False, queue_available=False,
            # quantum_status=error. None of those appended an issue, so a
            # subsystem sitting in an error state graded HEALTHY. The safety
            # subsystem reporting healthy while uninitialized is the clearest
            # case of why this cannot stay a per-check convention.
            #
            # Applied here rather than in each check so a new check inherits it,
            # and so the rule is stated once instead of nineteen times.
            # Probed sub-components contribute their own readings before status
            # is derived, so a failing part degrades its subsystem rather than
            # being invisible to it.
            probed_metrics, probed_issues = await self._probe_subcomponents(component)
            metrics.update(probed_metrics)
            issues.extend(probed_issues)

            issues.extend(self._failures_reported_as_metrics(component, metrics))

            # ATTRIBUTE the readings to the sub-components they came from.
            #
            # A check probes several modules and merges their readings into one
            # verdict, so "reasoning: degraded" cannot say whether the neural
            # bridge or the Bayesian engine is down -- and the improvement system
            # selecting `reasoning` as a target has no idea which part to work
            # on. The readings are already separated by metric prefix; this
            # records them against the sub-component that produced them.
            subs = self._record_subcomponent_health(component, metrics)

            # Update health record
            health.metrics = metrics
            health.issues = issues
            health.timestamp = datetime.now()

            # Weighted + gated assessment replaces issue-counting. The old rule
            # made severity a function of how many findings there were and of
            # whether the word "critical" appeared in one of them.
            declared_metrics = self._declared_metrics.pop(component, None)
            assessment = (self.evaluate_declared(component, declared_metrics, issues)
                          if declared_metrics
                          else self.evaluate(component, metrics, issues))
            health.status = assessment["status"]
            health.metrics["_health_score"] = assessment["score"]
            health.metrics["_criticality"] = assessment["criticality"]
            health.metrics["_evidence_coverage"] = assessment["coverage"]
            # Coverage is measured/declared, so a component declaring one
            # liveness signal reports 1.0 exactly like one declaring ten. The
            # evaluator computes the count; not surfacing it left "alive, and
            # nothing else is known" reading as complete evidence.
            health.metrics["_signals_measured"] = assessment["signals_measured"]
            health.metrics["_activity_state"] = self.activity_state(component, metrics)
            if assessment["gate_failures"]:
                health.metrics["_gate_failures"] = assessment["gate_failures"]

            # Notifications are driven BY the evaluated status. These branches
            # used to re-assign it -- `elif len(issues) >= 3: UNHEALTHY` and a
            # trailing `else: DEGRADED` -- which silently overrode the weighted
            # verdict, so a component scoring 1.0 with one issue still reported
            # DEGRADED and the gates never surfaced.
            if health.status == HealthStatus.HEALTHY:
                self.stats['healthy_checks'] += 1
            elif health.status == HealthStatus.CRITICAL:
                self.stats['critical_checks'] += 1
                await self._notify_status(component, health, "critical",
                                          "🚨 Component Critical")
            elif health.status == HealthStatus.UNHEALTHY:
                self.stats['unhealthy_checks'] += 1
                await self._notify_status(component, health, "warning",
                                          "⚠️ Component Unhealthy")
            elif health.status == HealthStatus.DEGRADED:
                self.stats['degraded_checks'] += 1

            # Update statistics
            check_duration = time.time() - start_time
            health.uptime_seconds = (datetime.now() - self.stats['uptime_start']).total_seconds()
            self.stats['total_checks'] += 1
            self.stats['last_check_time'] = datetime.now().isoformat()

            logger.info(f"Component health check: {component} = {health.status.value} ({check_duration:.2f}s)")

            # Persist the assessment so the improvement system can select
            # targets from measured components instead of invented ones.
            #
            # RECORDING IS NOT MEASURING. These calls sat inside the outer
            # handler, so a failed database write replaced an already-computed
            # verdict with UNKNOWN -- an llm that measured 1.0 with every gate
            # passing reported "unknown" because the store was unreachable, and
            # a component that measured CRITICAL would have had its verdict
            # erased the same way, which hides the failure instead of the
            # outage. The measurement is finished by this point; a storage
            # problem is its own fact and belongs to storage.
            try:
                await self._persist_assessment(health)
                for record in subs.values():
                    await self._persist_assessment(record)
            except Exception as e:
                logger.error(f"Failed to persist health assessment for {component}: {e}")
                health.metrics["_persisted"] = False
                health.issues.append(f"Assessment not recorded: {e}")

            return health

        except Exception as e:
            logger.error(f"Health check failed for {component}: {e}")
            health.error_count += 1
            health.status = HealthStatus.UNKNOWN
            health.issues.append(f"Health check error: {str(e)}")
            return health

    #: What it costs the substrate if this component is not working.
    #:
    #: Criticality is NOT a weight. A critical component that fails a gate is
    #: UNHEALTHY regardless of how well everything else scores -- a database
    #: that is unreachable while CPU, memory and latency are all perfect must
    #: not average out to 0.80 HEALTHY.
    CRITICALITY = {
        'critical': {'database', 'memory', 'safety', 'governance', 'security',
                     'health_system', 'llm', 'domain', 'tools'},
        'optional': {'quantum', 'chaos', 'simulation', 'optimization',
                     'intelligence', 'metrics_export', 'malware_sandbox'},
    }

    #: Components that run an autonomous loop, and how often an iteration is
    #: expected. Declared ONLY where a loop exists -- a request-driven service
    #: has no cadence, and asserting one would make "nobody called it" look like
    #: a stall. Read from the component's own configured interval where it has
    #: one (SystemWatchdog.check_interval is 30s).
    LOOP_CADENCE_SEC = {
        'health_system': 60,
        'agents': 300,
        'backup': 86400,
    }

    async def _notify_status(self, component: str, health: 'ComponentHealth',
                             severity: str, title: str) -> None:
        """Emit a status notification. Never raises into the check."""
        try:
            from core.utils.notification_publisher import send_system_notification
            issues_text = "\n".join(f"• {i}" for i in health.issues[:5])
            asyncio.create_task(send_system_notification(
                title=f"{title}: {component}",
                message=(f"**Component:** {component}\n**Status:** "
                         f"{health.status.value}\n**Issues:** {len(health.issues)}\n\n{issues_text}"),
                severity=severity,
                metadata={"component": component, "issues_count": len(health.issues),
                          "health_score": health.metrics.get("_health_score"),
                          "criticality": health.metrics.get("_criticality")},
            ))
        except Exception as e:
            logger.debug("Status notification not sent for %s: %s", component, e)

    #: Rate metrics where a HIGHER value is WORSE. Listed explicitly rather
    #: than inferred, so a new metric is classified deliberately instead of by
    #: whatever its name happens to contain.
    _COST_RATE_MARKERS = ('failure', 'error', 'threat', 'rejection', 'violation',
                          'malicious', 'overconfidence', 'drop', 'miss')

    @classmethod
    def _is_cost_rate(cls, key: str) -> bool:
        """True when a higher value of this rate means worse health."""
        return any(marker in key for marker in cls._COST_RATE_MARKERS)

    def _classify_criticality(self, component: str) -> str:
        base = component.split('.', 1)[0]
        for level, members in self.CRITICALITY.items():
            if base in members or component in members:
                return level
        return 'standard'

    def evaluate_declared(
        self, component: str, declared: List[HealthMetric], issues: List[str]
    ) -> Dict[str, Any]:
        """Aggregate metrics the subsystem already normalized.

        The evaluator's whole job: gates, weights, coverage, criticality. It
        never interprets a raw value -- a latency in milliseconds and a
        classifier confidence arrive as the same kind of 0-1 signal because the
        subsystem that understands them did the conversion.
        """
        criticality = self._classify_criticality(component)

        gate_failures = [m.name for m in declared
                         if m.critical and (m.normalized is None or m.normalized <= 0.0)]
        measured = [m for m in declared if m.normalized is not None]
        required = [m for m in declared if m.required]
        required_measured = [m for m in required if m.normalized is not None]
        coverage = (len(required_measured) / len(required)) if required else (
            1.0 if measured else 0.0)

        if gate_failures:
            status = (HealthStatus.CRITICAL if criticality == 'critical'
                      else HealthStatus.UNHEALTHY)
            score = 0.0
        elif not measured:
            status, score = HealthStatus.UNKNOWN, None
        else:
            total_weight = sum(m.weight for m in measured) or 1.0
            score = sum(m.normalized * m.weight for m in measured) / total_weight
            score = max(0.0, score - 0.1 * len(issues))
            # A REQUIRED metric that could not be measured blocks a confident
            # HEALTHY: the score may be high, but it was computed without the
            # evidence that was declared necessary.
            if coverage < 1.0 and score >= 0.9:
                status = HealthStatus.DEGRADED
            elif score >= 0.9:
                status = HealthStatus.HEALTHY
            elif score >= 0.6:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY

        return {
            "status": status, "score": score, "criticality": criticality,
            "coverage": round(coverage, 3), "signals_measured": len(measured),
            "signals_unknown": [m.name for m in declared if m.normalized is None],
            "gate_failures": gate_failures, "normalization": "declared",
        }

    def evaluate(
        self, component: str, metrics: Dict[str, Any], issues: List[str]
    ) -> Dict[str, Any]:
        """Weighted, gated health assessment with explicit evidence coverage.

        Status was derived by COUNTING issues: zero meant healthy, three meant
        unhealthy, and CRITICAL was a substring match on issue text. Counting
        treats every finding as equally severe -- "firewall in test mode" and
        "database unreachable" both being one issue -- and a substring match
        makes severity depend on wording.

        Two safeguards, because a weighted average alone is not enough:

        1. CRITICAL GATES. Some signals are gates, not weights. A critical
           component whose liveness signal is False is UNHEALTHY however good
           its other numbers are; averaging cannot rescue an unreachable
           database.
        2. MISSING EVIDENCE STAYS UNKNOWN. An unmeasured signal is never
           imputed as 1.0 or 0.0. Coverage is reported alongside the score so a
           confident number computed from two signals is distinguishable from
           the same number computed from ten.
        """
        criticality = self._classify_criticality(component)

        # Normalised signals from what the checks already emit. Nothing is
        # invented: booleans are liveness, *_rate is already 0-1, and anything
        # unmeasured is absent rather than defaulted.
        signals: Dict[str, float] = {}
        gate_failures: List[str] = []
        unknown: List[str] = []

        # UNDEFINED IS NOT UNMEASURED. A failure rate over zero requests has no
        # value to report; that is a property of the arithmetic, not a failed
        # reading. Counting it as missing evidence held an idle-but-working
        # service below full coverage permanently, so it could never grade
        # HEALTHY no matter how well it ran -- the same mistake as gating on a
        # signal that does not apply to the running mode, pointed the other way.
        #
        # The check declares these, because only the code that computed the
        # value knows whether None means "no observations" or "could not read".
        not_applicable = set((metrics or {}).get('_not_applicable') or ())

        for key, value in (metrics or {}).items():
            if key in not_applicable:
                continue
            if value is None:
                unknown.append(key)
                continue
            if isinstance(value, bool):
                # `accessible` and `initialized` carry no suffix but are the
                # plainest liveness signals there are -- omitting them meant a
                # database reporting accessible=False sailed through the gate.
                if key.endswith(self._LIVENESS_SUFFIXES) or key in self._BARE_LIVENESS:
                    signals[key] = 1.0 if value else 0.0
                    if not value and criticality == 'critical':
                        gate_failures.append(key)
            elif key.endswith('_rate') and isinstance(value, (int, float)):
                # POLARITY IS NOT UNIFORM. success_rate and convergence_rate are
                # better when high; failure_rate, error_rate, threat_rate and
                # violation_rate are better when LOW. Treating every *_rate as
                # "higher is better" scored zero failures as 0.0 UNHEALTHY and a
                # 100% failure rate as 1.0 HEALTHY -- an exact inversion on the
                # metrics that matter most.
                v = max(0.0, min(1.0, float(value)))
                signals[key] = (1.0 - v) if self._is_cost_rate(key) else v

        declared = len(signals) + len(unknown)
        coverage = (len(signals) / declared) if declared else 0.0

        if gate_failures:
            status = HealthStatus.CRITICAL if criticality == 'critical' else HealthStatus.UNHEALTHY
            score = 0.0
        elif not signals:
            # NO SIGNALS MEANS NO SCORE. The previous `sum(...) if signals else
            # 1.0` invented a perfect score out of zero evidence, then decremented
            # it per issue -- so a component with one issue and nothing measurable
            # graded HEALTHY 0.9, and one with eleven graded UNHEALTHY 0.0. That is
            # severity by issue count applied to a fabricated baseline: the exact
            # rule this evaluator replaced, reintroduced through the fallback.
            #
            # Issues are qualitative evidence that something is wrong; they cannot
            # quantify how wrong. So the score stays None and the status says which
            # of the two unmeasured cases this is.
            score = None
            status = HealthStatus.DEGRADED if issues else HealthStatus.UNKNOWN
        else:
            score = sum(signals.values()) / len(signals)
            # Issues are evidence of degradation but do not define severity by
            # count alone; each reduces quality within the valid operating band.
            score = max(0.0, score - 0.1 * len(issues))
            # A metric that was attempted and came back None is missing evidence,
            # not a passing reading. Declaring HEALTHY off one signal while three
            # others failed to measure is the same overconfidence the declared
            # path already blocks -- both paths now apply the identical rule.
            if score >= 0.9 and coverage < 1.0:
                status = HealthStatus.DEGRADED
            elif score >= 0.9:
                status = HealthStatus.HEALTHY
            elif score >= 0.6:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY

        return {
            "status": status,
            "score": score,
            "criticality": criticality,
            "coverage": round(coverage, 3),
            "signals_measured": len(signals),
            "signals_unknown": unknown,
            "gate_failures": gate_failures,
        }

    def activity_state(self, component: str, metrics: Dict[str, Any]) -> str:
        """Operational condition, reported SEPARATELY from health.

        health=HEALTHY / activity=IDLE is a normal, correct state. Making idle
        a peer of healthy forces a component with nothing to do to look faulty.
        """
        cadence = self.LOOP_CADENCE_SEC.get(component)
        last = (metrics or {}).get('last_iteration_completed_at')
        if cadence and last:
            try:
                age = (datetime.now() - datetime.fromisoformat(str(last))).total_seconds()
                if age > cadence * 3:
                    return 'STALLED'
            except (TypeError, ValueError):
                pass
        for key, value in (metrics or {}).items():
            if key.endswith(('_backlog', '_queue_depth', '_pending')) and isinstance(value, int):
                if value > 0:
                    return 'BACKLOGGED'
        return 'ACTIVE'

    # The status -> 0-100 bucket table that used to live here is gone. Its two
    # callers both had a real computed score available and reached for the
    # bucket instead, collapsing every measurement onto four values on the way
    # to the store and on the way back out of it. Keeping it as a convenience
    # only offered a way to reintroduce that. unified.component_health is
    # written from the evaluator's score, scaled, or NULL.

    async def _persist_assessment(self, health: 'ComponentHealth') -> bool:
        """Write an assessment to unified.component_health.

        THE JOIN THAT WAS MISSING. This monitor measured every subsystem each
        cycle and kept the result in memory; unified.component_health -- the
        table EnhancedASISelfImprovement selects improvement targets from -- was
        written only by intrinsic_motivation, with metric names as component
        names on a 0-1 scale. So the improvement system read six rows called
        `overall_status` and `active_alerts` and nothing about any real
        component.

        Only the ASSESSMENT columns are written. error_count / success_count /
        avg_latency_ms belong to per-operation reporting via
        ImprovementMonitor.update_component_health, which is a different
        question about the same component; splitting them keeps one writer per
        column instead of two writers disagreeing about health_score.
        """
        # PERSIST THE COMPUTED SCORE, not a coarse re-derivation of it.
        #
        # This wrote _STATUS_SCORE[status] -- 100/75/40/10 -- discarding the
        # weighted score the evaluator just computed. A component at 0.62 and
        # one at 0.89 both persisted as 75.0 DEGRADED, so every consumer,
        # including ASI target ranking, saw four possible values instead of a
        # measurement. Exactly the defect the `verified` column had: a verdict
        # computed correctly and dropped on the way to the table.
        # An absent score is NULL, not a bucket. Falling back to
        # _STATUS_SCORE[status] here re-created the very 100/75/40/10 the note
        # above describes, and did it for precisely the states that have no
        # measurement behind them -- inventing 75.0 for a component whose score
        # was None because nothing could be measured.
        #
        # The row is written either way. Returning early on an unmeasurable
        # component left its PREVIOUS row in place, so the store went on serving
        # a stale `healthy` (and a stale last_updated) for something that could
        # no longer be measured at all. health_score is nullable: status UNKNOWN
        # with a NULL score records "checked, not measurable", which is a
        # different fact from "never checked" and from "measured as bad".
        computed = (health.metrics or {}).get("_health_score")
        score = round(float(computed) * 100.0, 2) if computed is not None else None

        # OWNERSHIP, NOT OFFLINE-PATCHING, is the boundary now: a monitor only
        # persists components in its own scope (the guardian never grades
        # substrate cognition), so a component reaching this method is one this
        # process legitimately owns and its score is a real reading. A stopped
        # substrate's internals are shown offline from its heartbeat by the
        # dashboard, not written here by a process that cannot see them.

        from core.database import get_database_manager
        db = get_database_manager()
        await db.execute_query(
            """
            INSERT INTO unified.component_health
                (component_name, status, health_score, last_error, last_updated, metadata)
            VALUES ($1, $2, $3, $4, NOW(), $5::jsonb)
            ON CONFLICT (component_name) DO UPDATE SET
                status       = EXCLUDED.status,
                health_score = EXCLUDED.health_score,
                last_error   = EXCLUDED.last_error,
                last_updated = NOW(),
                metadata     = EXCLUDED.metadata
            """,
            (
                health.component,
                health.status.value,
                score,
                health.issues[0][:500] if health.issues else None,
                # WHO MEASURED THIS, AND WHEN.
                #
                # Most of what these checks read is in-process singleton state:
                # watchdog.is_running, llm.model_loaded, scheduler_active. A
                # reading is therefore only true of the process that took it.
                # Without provenance the store said "health_system: healthy" --
                # from a process that had restarted its own watchdog -- while
                # every other process saw it stopped, and the improvement system
                # read that row as current system state and skipped the
                # component. A measurement of one process presented as a
                # measurement of the system is the same defect as a default
                # presented as a reading.
                json.dumps({"issues": health.issues[:10],
                            "measured_by": {"pid": os.getpid(),
                                            "host": socket.gethostname(),
                                            "at": datetime.now().isoformat()},
                            "metrics": {k: v for k, v in (health.metrics or {}).items()
                                        if isinstance(v, (int, float, bool, str))
                                        or v is None}}),
            ),
            commit=True,
        )

        # A LONG-TERM BASELINE FOR EVERY COMPONENT, at the one place a score is
        # already computed and persisted.
        #
        # `unified.component_health` holds only the CURRENT score, so nothing
        # could say whether 0.62 is where this component has always been or
        # where it fell to. `long_term_baselines` answers that, and it was
        # empty because its only writer had no callers.
        #
        # POLARITY. `track_cross_cycle_capability` treats higher as better, and
        # that is true of `_health_score` and of almost nothing else here --
        # `active_findings`, `error_rate` and `write_queue` all mean the
        # opposite. Feeding one of those in would report a rising error rate as
        # an IMPROVING capability, so only the computed score is baselined and
        # any per-metric baseline must declare its own direction first.
        # A BASELINE OF ZERO IS A FLOOR NOTHING CAN FALL THROUGH.
        #
        # Measured while wiring this: a health check run against a process
        # where the subsystem is not initialised scores `memory` at 0.0,
        # although its last real reading was 100. Establishing the baseline
        # from that would fix the floor at zero permanently -- every later
        # reading is >= it, so the component could never regress, and the
        # component that looks most stable would be the one measured while it
        # was down.
        #
        # So a NEW baseline is only established from a live, non-zero reading.
        # An EXISTING baseline is always updated, because a genuine fall to
        # zero is exactly the regression this is here to catch.
        if score is not None:
            try:
                from core.learning.improvement_monitor import get_improvement_monitor

                monitor = get_improvement_monitor()
                usable = float(score) > 0.0 and health.status is not HealthStatus.UNKNOWN
                if not usable:
                    from core.database import get_database_manager as _gdb

                    existing = await _gdb().execute_query(
                        "SELECT 1 FROM unified.long_term_baselines "
                        "WHERE component_name = $1 AND metric_name = 'health_score'",
                        (health.component,), fetch_all=True)
                    if not existing:
                        logger.warning(
                            "Not establishing a long-term baseline for %s from a "
                            "score of %s (status %s): a zero baseline could never "
                            "detect regression", health.component, score,
                            health.status.value)
                        raise _SkipBaseline

                await monitor.track_cross_cycle_capability(
                    component_name=health.component,
                    metric_name="health_score",
                    current_value=float(score),
                    cycle_number=0)
            except _SkipBaseline:
                pass
            except Exception as baseline_error:
                logger.error("Long-term baseline not updated for %s: %s",
                             health.component, baseline_error)
        return True

    #: Metric suffixes whose value is a self-report of being up. Exactly False
    #: means the subsystem said it is not running -- which is a health finding,
    #: not a datum. Kept as an explicit list rather than a heuristic on the
    #: value, so a numeric 0 or an empty string can never be read as "down".
    #: Liveness signals whose names carry no suffix.
    _BARE_LIVENESS = frozenset({'accessible', 'initialized', 'available', 'connected'})

    _LIVENESS_SUFFIXES = ('_initialized', '_available', '_loaded', '_connected',
                          '_active', '_alive', '_running', '_attached')

    def _record_subcomponent_health(
        self, component: str, metrics: Dict[str, Any]
    ) -> Dict[str, ComponentHealth]:
        """Split a subsystem's readings into per-sub-component health.

        Each sub-component is graded on ITS OWN metrics under the same liveness
        rule the parent uses, so a sub-component that reports itself down is
        degraded even when its siblings are fine. Sub-components are stored in
        component_health under their hierarchical id, which is what
        get_all_component_health() and the registry both address them by.

        A sub-component contributing NO metrics is recorded as UNKNOWN rather
        than healthy: the probe produced nothing, which is not a clean bill of
        health.
        """
        # Hand-written AND probe-derived, so a sub-component listed only in
        # _PROBED_SUBCOMPONENTS still gets its own record instead of having its
        # readings silently absorbed into the parent.
        results: Dict[str, ComponentHealth] = {}

        for sub, sub_spec in self._subcomponent_specs(component).items():
            prefixes = tuple(sub_spec['metric_prefixes'])
            owned = {k: v for k, v in (metrics or {}).items() if k.startswith(prefixes)}
            sub_id = f"{component}.{sub}"
            sub_issues = self._failures_reported_as_metrics(sub_id, owned)

            if not owned:
                status = HealthStatus.UNKNOWN
                sub_issues = [f"{sub_id}: probe returned no metrics"]
            elif any('critical' in i.lower() for i in sub_issues):
                status = HealthStatus.CRITICAL
            elif sub_issues:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY

            record = self.component_health.get(sub_id) or ComponentHealth(
                component=sub_id, status=status, timestamp=datetime.now())
            record.status = status
            record.metrics = owned
            record.issues = sub_issues
            record.timestamp = datetime.now()
            record.check_count += 1
            self.component_health[sub_id] = record
            results[sub_id] = record

        return results

    @staticmethod
    def _failures_reported_as_metrics(
        component: str, metrics: Dict[str, Any]
    ) -> List[str]:
        """Turn self-reported failure metrics into issues.

        Only two shapes count, both unambiguous:
          <name>_initialized/_available/_loaded/_connected is exactly False
          <name>_status is exactly the string "error"

        `is False` and `== "error"` are exact on purpose. A count of 0, an empty
        dict or a None must NOT be read as a failure -- that would turn "not
        measured" back into "broken", which is the same conflation in reverse.
        """
        found: List[str] = []
        for key, value in (metrics or {}).items():
            if value is False and key.endswith(HealthMonitor._LIVENESS_SUFFIXES):
                found.append(f"{component}: {key} is False — subsystem reports it is not running")
            elif key.endswith('_status') and isinstance(value, str) and value.lower() == 'error':
                found.append(f"{component}: {key} reports 'error'")
        return found

    async def _check_health_system_health(self) -> tuple[Dict[str, Any], List[str]]:
        """The health system monitoring itself.

        Nothing watched the watcher: a stalled watchdog or a recovery manager
        that fails every recovery produced no signal at all, because the only
        thing that could have reported it was the thing that had stopped.
        """
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        try:
            from core.health.recovery_manager import get_recovery_manager
            rec = await get_recovery_manager().get_statistics()   # get_statistics is async
            metrics['recovery_total_failures'] = rec['total_failures']
            metrics['recovery_successful'] = rec['successful_recoveries']
            metrics['recovery_failed'] = rec['failed_recoveries']
            metrics['recovery_active_failures'] = rec['active_failures']
            metrics['recovery_escalations'] = rec['escalations']
            self._record_rate(metrics, 'recovery_failure_rate',
                              rec['failure_rate'], rec['total_failures'])

            from core.health.system_watchdog import get_system_watchdog
            wd = get_system_watchdog()
            metrics['watchdog_running'] = bool(getattr(wd, 'is_running', False))
            metrics['watchdog_recovery_attempts'] = len(getattr(wd, 'recovery_attempts', {}) or {})
            metrics['watchdog_monitor_attached'] = getattr(wd, 'health_monitor', None) is not None

            metrics['monitored_components'] = len(self._monitored_components)
            metrics['components_with_readings'] = len(self.component_health)
            metrics['checks_total'] = self.stats['total_checks']
            metrics['checks_critical'] = self.stats['critical_checks']

            if metrics['recovery_active_failures'] > 0:
                issues.append(f"{metrics['recovery_active_failures']} unrecovered failure(s) active")
            if metrics['recovery_escalations'] > 0:
                issues.append(f"{metrics['recovery_escalations']} failure(s) escalated beyond automatic recovery")
        except Exception as e:
            metrics['health_system_available'] = False
            issues.append(f"Health system self-check error: {e}")
        return metrics, issues

    async def _check_execution_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Iteration budgets and convergence — whether reasoning terminates."""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        try:
            from core.execution.convergence_gate import get_convergence_gate
            cg = get_convergence_gate().get_stats()
            # LIVENESS WAS NEVER REPORTED. This check emitted only counters and
            # a rate that is undefined until something runs, so an execution
            # subsystem that was loaded and working produced zero signals and
            # graded UNKNOWN at 0.0 coverage -- indistinguishable from one whose
            # modules are absent. Resolving the provider and getting a reading
            # out of it is the evidence; it was being discarded.
            metrics['convergence_gate_available'] = True
            metrics['convergence_total_checks'] = cg['total_checks']
            metrics['convergence_converged'] = cg['converged']
            self._record_rate(metrics, 'convergence_rate',
                              cg['convergence_rate'], cg['total_checks'])
            metrics['convergence_failed_constraints'] = cg['failed_constraints']

            from core.execution.iteration_controller import get_iteration_controller
            ic = get_iteration_controller().get_stats()
            metrics['iteration_controller_available'] = True
            metrics['iteration_budgets_created'] = ic['total_budgets_created']
            metrics['iteration_bayesian'] = ic['bayesian_iterations']
            metrics['iteration_heuristic_fallbacks'] = ic['heuristic_fallbacks']
            metrics['iteration_temporal_limits_hit'] = ic['temporal_limits_hit']

            if cg['total_checks'] >= 10 and cg['convergence_rate'] < 0.5:
                issues.append(
                    f"Convergence rate {cg['convergence_rate']:.0%} over "
                    f"{cg['total_checks']} checks — reasoning frequently fails to converge")
            if ic['temporal_limits_hit'] > 0:
                issues.append(f"{ic['temporal_limits_hit']} iteration budget(s) hit the temporal limit")
        except Exception as e:
            metrics['execution_available'] = False
            issues.append(f"Execution health check error: {e}")
        return metrics, issues

    async def _check_system_awareness_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Environment, service discovery and infrastructure topology."""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        try:
            # NOTHING HAD PROBED EITHER OBJECT. Both EnvironmentState and
            # InfrastructureTopology were constructed and read immediately, so
            # every number came from their constructors. Topology explicitly
            # starts every node at is_running=False ("assume down until proven
            # up"), and the proving never happened -- so this reported
            # "4 critical service(s) down" on every run regardless of what was
            # actually running, and system_awareness was permanently degraded by
            # its own default state. An unprobed default presented as a
            # measurement is the same defect as a fabricated score.
            #
            # refresh() does the real work: it port-scans the services and
            # health-checks their endpoints. update_from_environment then moves
            # those readings into the topology.
            from core.system.environment_state import EnvironmentState
            env_state = EnvironmentState()
            await env_state.refresh()
            env = env_state.get_state_summary()
            metrics['env_health'] = env['health']
            metrics['env_services'] = len(env['services']) if hasattr(env['services'], '__len__') else env['services']

            from core.system.active_discovery import get_active_discovery
            disc = get_active_discovery().get_service_summary()
            metrics['discovery_total_services'] = disc['total_services']
            metrics['discovery_healthy_services'] = disc['healthy_services']
            metrics['discovery_total_scans'] = disc['total_scans']
            metrics['discovery_unidentified_ports'] = disc['unidentified_ports']

            from core.system.infrastructure_topology import InfrastructureTopology
            topology = InfrastructureTopology()
            topology.update_from_environment(env_state)
            topo = topology.get_health_summary()
            metrics['topology_total_services'] = topo['total_services']
            metrics['topology_down'] = topo['down']
            metrics['topology_degraded'] = topo['degraded']
            metrics['topology_critical_down'] = topo['critical_services_down']
            metrics['topology_spof'] = len(topo['single_points_of_failure']) \
                if hasattr(topo['single_points_of_failure'], '__len__') else topo['single_points_of_failure']
            metrics['system_awareness_available'] = True
            if topo['total_services']:
                metrics['topology_healthy_rate'] = round(
                    topo['healthy'] / topo['total_services'], 4)

            if topo['critical_services_down'] > 0:
                issues.append(f"{topo['critical_services_down']} critical service(s) down")
            if metrics['topology_spof'] > 0:
                issues.append(f"{metrics['topology_spof']} single point(s) of failure in the topology")
        except Exception as e:
            metrics['system_awareness_available'] = False
            issues.append(f"System awareness health check error: {e}")
        return metrics, issues

    async def _check_intelligence_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Predictive intelligence: initialised, and whether it predicts anything."""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        try:
            from core.intelligence.predictive_intelligence_system import get_predictive_intelligence
            pi = get_predictive_intelligence()
            metrics['predictive_initialized'] = bool(getattr(pi, 'initialized', False))
            metrics['predictive_active_predictions'] = len(getattr(pi, 'active_predictions', {}) or {})
            metrics['predictive_history'] = len(getattr(pi, 'prediction_history', []) or [])
            metrics['predictive_accuracy_tracked'] = len(getattr(pi, 'accuracy_metrics', {}) or {})
        except Exception as e:
            metrics['intelligence_available'] = False
            issues.append(f"Intelligence health check error: {e}")
        return metrics, issues

    async def _check_metrics_export_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Prometheus exporter — whether the substrate can be observed externally."""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        try:
            from core.monitoring.prometheus_exporter import get_prometheus_metrics
            pm = get_prometheus_metrics()
            # export_metrics() returns BYTES (the Prometheus wire format), not
            # str -- .startswith('#') on bytes raises, so the check reported its
            # own type error as the exporter's health.
            exported = pm.export_metrics() or b""
            text = exported.decode('utf-8', 'replace') if isinstance(exported, bytes) else exported
            metrics['prometheus_available'] = True
            metrics['prometheus_payload_bytes'] = len(exported)
            metrics['prometheus_series'] = sum(
                1 for line in text.splitlines() if line and not line.startswith('#'))
            if metrics['prometheus_series'] == 0:
                issues.append('Prometheus exporter produces no series — '
                              'the substrate is not externally observable')
        except Exception as e:
            metrics['prometheus_available'] = False
            issues.append(f"Metrics export health check error: {e}")
        return metrics, issues

    #: Sub-components measured by calling their own stats provider.
    #:
    #: Each entry is (module, singleton_accessor, stats_method) and every one was
    #: verified to return a non-empty dict before being listed -- two candidates
    #: were dropped because CircuitBreakerRegistry has no get_stats and
    #: safety_audit_trail.get_logger() requires an argument. Declaring a
    #: sub-component that cannot be probed would put a component in the registry
    #: that no measurement can ever reach.
    #:
    #: This table is also the DECLARATION: _subcomponent_specs() derives the
    #: manifest entries from it, so a probe and its declaration cannot drift.
    _PROBED_SUBCOMPONENTS: Dict[str, Dict[str, tuple]] = {
        'agents': {
            'agent_coordinator':   ('core.agents.agents', 'get_agent_coordinator', 'get_statistics'),
            'queue_authority':     ('core.agents.autonomous.queue_authority', 'get_queue_authority', 'get_statistics'),
        },
        'reasoning': {
            'proof_engine':        ('core.reasoning.advanced_proof_engine', 'get_proof_engine', 'get_statistics'),
            'analogy_discovery':   ('core.reasoning.analogy_discovery', 'get_analogy_discovery', 'get_statistics'),
            'formal_argumentation':('core.reasoning.formal_argumentation', 'get_argumentation_system', 'get_statistics'),
            'hypothesis_testing':  ('core.reasoning.hypothesis_testing', 'get_hypothesis_system', 'get_statistics'),
            'temporal_reasoning':  ('core.reasoning.temporal_reasoning', 'get_temporal_system', 'get_statistics'),
            # Previously BLIND to health despite doing real work: the abstract
            # reasoning engine (the coordinator's primary kind-reasoner), the
            # abstraction pipeline, and the constraint solver now each expose
            # get_statistics and are probed here.
            'abstract_reasoning':  ('core.reasoning.abstract_reasoning_engine', 'get_abstract_reasoning_engine', 'get_statistics'),
            'hierarchical_abstraction': ('core.reasoning.hierarchical_abstraction', 'get_hierarchical_abstraction', 'get_statistics'),
            'constraint_solver':   ('core.reasoning.constraint_solver', 'get_constraint_solver', 'get_statistics'),
        },
        'security': {
            # The substrate's request-validation controller and the policy that
            # gates ITS actions. The guardian's audit scanner is NOT here -- it
            # is the top-level system component 'security_audit' -- so this no
            # longer conflates a substrate gate with an always-on scanner.
            'safety_framework':    ('core.security.safety_framework', 'get_safety_framework', 'get_statistics'),
            'training_pipeline':   ('core.security.security_training_pipeline', 'get_training_pipeline', 'get_statistics'),
            'digital_footprint':   ('core.security.digital_footprint', 'get_digital_footprint_obliterator', 'get_statistics'),
        },
        'security_audit': {
            'audit_worker':        ('core.security.security_audit_worker', 'get_audit_worker', 'get_statistics'),
        },
        'learning': {
            'causal_analyzer':     ('core.learning.causal_feedback_analyzer', 'get_causal_analyzer', 'get_statistics'),
            'meta_learner':        ('core.learning.meta_learning', 'get_meta_learner', 'get_statistics'),
            'interaction_learner': ('core.learning.interaction_meta_learning', 'get_interaction_learner', 'get_statistics'),
        },
        'memory': {
            'embedding_service':   ('core.memory.utils.embedding_service', 'get_embedding_service', 'get_metrics'),
            'memory_filter':       ('core.memory.utils.memory_filter', 'get_memory_filter', 'get_metrics'),
            'memory_injector':     ('core.memory.utils.memory_injector', 'get_memory_injector', 'get_statistics'),
        },
        'tools': {
            'testing_tools':       ('core.tools.testing_validation_tools', 'get_testing_tools', 'get_statistics'),
        },
    }

    @classmethod
    def _subcomponent_specs(cls, component: str) -> Dict[str, Dict[str, Any]]:
        """Declared sub-components: hand-written plus probe-derived, merged."""
        specs = dict((cls.COMPONENT_MANIFEST.get(component, {}).get('subcomponents') or {}))
        for sub, (module, _acc, _meth) in cls._PROBED_SUBCOMPONENTS.get(component, {}).items():
            specs.setdefault(sub, {
                'module': module,
                'description': f"Probed via {module}",
                'metric_prefixes': (f"{sub}_",),
            })
        return specs

    @staticmethod
    def _live_singleton(module_path: str, *names: str):
        """The instance the running system is USING, or None. Never builds one.

        Three checks reached for a `_instance` class attribute that nothing
        anywhere assigns -- `TaskQueue._instance`, `MemoryAgent._instance`,
        `ContentSecurityScanner._instance` -- the same defect already corrected
        for `safety`, where the handle turned out to be
        `SafetyFramework.contract_manager`. Because the attribute never exists
        the lookup always missed, and the three checks then diverged:

          - agents recorded `queue_available = False` and stopped, so a running
            queue was reported down on every cycle in every process;
          - memory and content_security CONSTRUCTED a fresh object and measured
            that, so a subsystem that was never started reported zero scans and
            zero errors as though it had been observed doing nothing.

        Both are fabrications, in opposite directions, and the second is worse
        than a wrong number: `get_memory_agent()` caches what it builds, so the
        health check installed the process-wide memory agent as a side effect of
        measuring it.

        Measuring a thing must never create it. Reading an already-bound module
        global has no side effect, which is what makes it a legitimate probe --
        the same line the sub-component probe draws when it hydrates persisted
        state but refuses to start a service.
        """
        import importlib
        try:
            module = importlib.import_module(module_path)
        except Exception:
            return None
        for name in names:
            instance = getattr(module, name, None)
            if instance is not None:
                return instance
        return None

    async def _probe_subcomponents(self, component: str) -> tuple:
        """Call each probed sub-component's own stats provider.

        Every key is prefixed with the sub-component name, which is what lets a
        reading be attributed to the part that produced it instead of being
        merged into one verdict for the whole subsystem.
        """
        import importlib

        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        for sub, (module, accessor, meth) in self._PROBED_SUBCOMPONENTS.get(component, {}).items():
            try:
                obj = getattr(importlib.import_module(module), accessor)()
                if asyncio.iscoroutine(obj):
                    obj = await obj
                # AN UNINITIALIZED PROVIDER HAS NO MEASUREMENTS, ONLY DEFAULTS.
                #
                # get_meta_learner() returns a fresh object whose counters are
                # zero; initialize() is what loads the persisted state. Reading
                # it unhydrated reported success_rate 0.0 for a learner that
                # actually holds 141 trials at 83% success -- a fabricated zero
                # that then drove `learning` to UNHEALTHY. Hydration is a read,
                # not a start: it loads what is already on disk and begins
                # nothing, so it is safe here in a way that starting a service
                # would not be.
                # Classes disagree on the flag: MemoryAgent uses `initialized`,
                # MetaLearner uses `active`. Checking only one name meant the
                # guard never fired for the other and the check read a hollow
                # object's defaults as measurements.
                ready_attr = next(
                    (a for a in ("initialized", "active", "is_initialized")
                     if hasattr(obj, a)), None)
                if ready_attr is not None and not getattr(obj, ready_attr):
                    init = getattr(obj, "initialize", None)
                    if init is not None:
                        try:
                            result = init()
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            metrics[f"{sub}_initialized"] = False
                            issues.append(f"{sub}: could not load state ({type(e).__name__})")
                            continue
                    if not getattr(obj, ready_attr, False):
                        # Report the state, never its empty defaults.
                        metrics[f"{sub}_initialized"] = False
                        continue

                stats = getattr(obj, meth)()
                if asyncio.iscoroutine(stats):
                    stats = await stats
                if not isinstance(stats, dict):
                    issues.append(f"{sub}: stats provider returned {type(stats).__name__}, not a mapping")
                    continue

                # A rate over zero observations is undefined. Providers return
                # 0.0 rather than None, and the evaluator cannot tell that from
                # a measured 0%.
                counters = [v for k, v in stats.items()
                            if isinstance(v, int) and not isinstance(v, bool)
                            and any(t in k for t in ('total', 'count', 'analyzed',
                                                     'records', 'trials', 'processed'))]
                no_activity = bool(counters) and all(c == 0 for c in counters)

                for key, value in stats.items():
                    if no_activity and key.endswith('_rate'):
                        metrics[f"{sub}_{key}"] = None
                        continue
                    if isinstance(value, (int, float, bool, str)) or value is None:
                        metrics[f"{sub}_{key}"] = value
                    else:
                        metrics[f"{sub}_{key}_count"] = len(value) if hasattr(value, '__len__') else None
            except Exception as e:
                # A sub-component that cannot be probed is reported, not skipped:
                # silence here would read as "this part is fine".
                metrics[f"{sub}_available"] = False
                issues.append(f"{sub}: probe failed ({type(e).__name__}: {str(e)[:60]})")
        return metrics, issues

    #: Packages that are computation libraries rather than running services.
    #: They hold no runtime state, so the honest health question is whether the
    #: capability can be loaded at all -- a broken import means the capability
    #: is gone, and nothing else was checking that.
    _LIBRARY_PACKAGES: Dict[str, tuple] = {
        'simulation':   ('core.simulation.system_dynamics',
                         'core.simulation.numerical_simulation'),
        'optimization': ('core.optimization.optimizers',),
        'utils':        ('core.utils.port_manager', 'core.utils.env_loader',
                         'core.utils.notification_publisher', 'core.utils.research_chunker'),
        'api_surface':  ('core.api.thinking_state_api', 'core.api.device_auth',
                         'core.api.key_attestation'),
    }

    async def _check_library_health(self, package: str) -> tuple[Dict[str, Any], List[str]]:
        """Importability of a library package's modules."""
        import importlib

        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        modules = self._LIBRARY_PACKAGES[package]
        loaded, broken = 0, []
        for mod in modules:
            try:
                m = importlib.import_module(mod)
                loaded += 1
                metrics[f"{package}_{mod.rsplit('.', 1)[-1]}_symbols"] = len(
                    [x for x in dir(m) if not x.startswith('_')])
            except Exception as e:
                broken.append(f"{mod} ({type(e).__name__})")
        metrics[f'{package}_modules_declared'] = len(modules)
        metrics[f'{package}_modules_loaded'] = loaded
        # Importability expressed as a rate, which is what "can this capability
        # load at all" means when there are several modules.
        metrics[f'{package}_import_rate'] = round(loaded / len(modules), 4) if modules else 0.0
        metrics[f'{package}_available'] = loaded > 0
        if broken:
            issues.append(f"{package}: {len(broken)} module(s) fail to import: {', '.join(broken[:3])}")
        return metrics, issues

    async def _check_tools_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Tool registry: inventory, indexes, and what usage is actually recorded.

        The registry had no health check at all -- 29 modules and 330 classes,
        and the agent's entire ability to act, unmonitored. Every number below
        is read from the registry or the store; none is defaulted.
        """
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        declared: List[HealthMetric] = []

        try:
            from core.tools import get_tool_registry
            registry = get_tool_registry()

            # EVERY READING WAS A COUNTER. Ints are not signals, so this check
            # produced no evidence at all: `tools` -- a critical component --
            # scored from an empty signal set at 0.0 coverage. `tools_available`
            # was written only on the failure path, so a registry that resolved
            # and answered recorded nothing to say so.
            metrics['tools_available'] = True

            stats = registry.get_usage_stats()
            metrics['tools_total'] = stats['total_tools']
            metrics['tools_eager'] = stats['eager_tools']
            metrics['tools_lazy'] = stats['lazy_tools']
            metrics['tools_loaded'] = stats['loaded_tools']
            metrics['tools_session_uses'] = stats['session_uses']
            metrics['tools_categories'] = len(registry.category_index)
            metrics['tools_capabilities_indexed'] = len(registry.capability_index)

            # Declared rather than name-inferred: an empty registry and a
            # missing capability index are not equally severe, and neither
            # distinction survives being encoded in a key suffix.
            has_tools = metrics['tools_total'] > 0
            has_index = metrics['tools_capabilities_indexed'] > 0
            declared.append(HealthMetric(
                name='tools_available', raw_value=True, normalized=1.0,
                weight=1.0, required=True, critical=True))
            declared.append(HealthMetric(
                name='tools_registry_populated', raw_value=metrics['tools_total'],
                normalized=invariant(has_tools), weight=1.0,
                required=True, critical=True,
                reason=None if has_tools else 'registry empty — the agent cannot act'))
            declared.append(HealthMetric(
                name='tools_capability_index_populated',
                raw_value=metrics['tools_capabilities_indexed'],
                normalized=invariant(has_index), weight=0.6,
                required=True, critical=False,
                reason=None if has_index else 'discovery cannot rank tools'))

            if not has_tools:
                issues.append('Tool registry is empty — the agent has no tools to act with')
            if not has_index:
                issues.append('Capability index empty — tool discovery cannot rank tools')

            # PERSISTED history. The registry's own counters are per-process and
            # reset on restart, so they cannot answer what the system has done.
            from core.database import get_database_manager
            db = get_database_manager()
            recorded = await db.execute_query(
                """SELECT (SELECT count(*) FROM unified.tool_error_events)  AS errors,
                          (SELECT count(*) FROM unified.tool_usage_history) AS uses""",
                fetch_all=True)
            row = recorded[0]
            metrics['tools_recorded_errors'] = int(row['errors'])
            metrics['tools_recorded_uses'] = int(row['uses'])

            # Recording failures but not successes biases every downstream
            # judgement toward failure. Stated as a health finding because the
            # asymmetry is invisible in either number on its own.
            if metrics['tools_recorded_errors'] > 0 and \
                    metrics['tools_recorded_uses'] <= 1:
                issues.append(
                    f"Tool outcomes are recorded asymmetrically: "
                    f"{metrics['tools_recorded_errors']} errors but "
                    f"{metrics['tools_recorded_uses']} usage record(s) — "
                    f"successes are not being written, so tool learning sees "
                    f"only failures")

            # Whether outcomes are recorded at all is a health property of the
            # registry, not just a note: with no usage records the learning and
            # ranking paths downstream have nothing to read.
            errors = metrics['tools_recorded_errors']
            uses = metrics['tools_recorded_uses']
            symmetric = not (errors > 0 and uses <= 1)
            declared.append(HealthMetric(
                name='tools_outcomes_recorded_symmetrically',
                raw_value={'errors': errors, 'uses': uses},
                normalized=invariant(symmetric), weight=0.6,
                required=False, critical=False,
                reason=None if symmetric else 'only failures are being recorded'))

            self._declared_metrics['tools'] = declared

        except Exception as e:
            metrics['tools_available'] = False
            issues.append(f"Tool registry health check error: {e}")

        return metrics, issues

    async def _check_domain_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Domain knowledge: what has been learned, and what survived validation.

        Reports the LEARNED and DERIVED parts separately -- the universal level
        is projected from the ontology on every load and is not something Torin
        learned, so folding them into one count would report designed concepts
        as acquired knowledge.
        """
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.domain.domain_registry import get_domain_registry
            registry = get_domain_registry()
            if not registry.initialized:
                await registry.initialize()

            stats = await registry.get_domain_statistics()
            metrics['domain_total'] = stats['total_domains']
            metrics['domain_populated'] = stats['populated_domains']
            metrics['domain_empty'] = stats['empty_domains']
            metrics['domain_learned_concepts'] = stats['learned_concepts']
            metrics['domain_projected_concepts'] = stats['projected_concepts']
            metrics['domain_mappings_loaded'] = stats['cross_domain_mappings']
            metrics['domain_registry_initialized'] = bool(registry.initialized)
            if metrics['domain_total']:
                metrics['domain_populated_rate'] = round(
                    metrics['domain_populated'] / metrics['domain_total'], 4)

            from core.database import get_database_manager
            db = get_database_manager()
            stored = await db.execute_query(
                """SELECT (SELECT count(*) FROM unified.domain_mappings) AS mappings,
                          (SELECT count(*) FROM unified.domain_mappings
                            WHERE verified IS TRUE)  AS accepted,
                          (SELECT count(*) FROM unified.domain_mappings
                            WHERE verified IS FALSE) AS refuted,
                          (SELECT count(*) FROM unified.knowledge_transfers) AS transfers,
                          (SELECT count(*) FROM unified.knowledge_transfers
                            WHERE success IS NULL) AS unresolved""",
                fetch_all=True)
            row = stored[0]
            metrics['domain_mappings_stored'] = int(row['mappings'])
            metrics['domain_mappings_accepted'] = int(row['accepted'])
            metrics['domain_mappings_refuted'] = int(row['refuted'])
            metrics['domain_transfers_stored'] = int(row['transfers'])
            metrics['domain_transfers_unresolved'] = int(row['unresolved'])

            if metrics['domain_populated'] == 0:
                issues.append('No domain holds any concept — cross-domain '
                              'reasoning has nothing to reason over')
            if metrics['domain_learned_concepts'] == 0:
                issues.append('No learned concepts — the domain layer holds only '
                              'the projected universal level')
            # Transfers are written by the learning path but never loaded back,
            # so the in-memory registry cannot see its own history.
            if metrics['domain_transfers_stored'] > 0 and \
                    stats['knowledge_transfers'] == 0:
                issues.append(
                    f"{metrics['domain_transfers_stored']} knowledge transfer(s) "
                    f"stored but none loaded into the registry — transfer history "
                    f"is invisible to the running system")

        except Exception as e:
            metrics['domain_available'] = False
            issues.append(f"Domain health check error: {e}")

        return metrics, issues

    async def _check_database_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check database health (PostgreSQL)"""
        metrics = {}
        issues = []

        try:
            from core.database.unified_database_postgres import TorinUnifiedDatabasePostgres
            db = TorinUnifiedDatabasePostgres()

            if not db.pool:
                issues.append('Database pool not initialized')
                return metrics, issues

            # Quick connectivity probe
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow('SELECT 1 AS ok, pg_database_size(current_database()) AS db_bytes')
                metrics['accessible'] = True
                metrics['db_size_mb'] = round(row['db_bytes'] / (1024 * 1024), 1)

            # Pool stats
            pool = db.pool
            metrics['pool_size'] = pool.get_size()
            metrics['pool_idle'] = pool.get_idle_size()
            metrics['pool_used'] = metrics['pool_size'] - metrics['pool_idle']

            if metrics['pool_used'] >= metrics['pool_size'] * 0.9:
                issues.append('Connection pool near capacity')

        except Exception as e:
            issues.append(f'Database health check error: {str(e)}')
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_memory_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check memory system health"""
        metrics = {}
        issues = []

        try:
            # OBSERVE THE LIVE AGENT, NEVER BUILD ONE. The `_instance` read
            # below always missed, and the fallback called get_memory_agent(),
            # which constructs a MemoryAgent AND caches it as the process-wide
            # singleton. So this check measured an agent it had just created --
            # reporting a hollow object's defaults as observations -- and left
            # that agent behind for every subsequent caller.
            memory_agent = self._live_singleton(
                'core.agents.memory_agent', '_memory_agent')

            if memory_agent is None:
                metrics['memory_agent_available'] = False
                issues.append('Memory agent is not running in this process — '
                              'no instance to measure')
                return metrics, issues

            # MEASURE, do not default.
            #
            # This called memory_agent.get_stats(), a method MemoryAgent has
            # never had. The `if hasattr(...) else {}` guard turned that into an
            # empty dict, and the .get(key, 0) chain below turned the empty dict
            # into four zeros. The store held 566 memories and this reported 0 --
            # and because 0 clears every threshold below, the subsystem was
            # graded HEALTHY on numbers nobody measured.
            #
            # The real provider is postgres_storage.get_statistics(), which
            # counts the rows. An absent provider is an ISSUE, because "no
            # measurement" and "measured zero" cannot share a value.
            # An UNINITIALIZED agent is a real health finding, not something a
            # health check should quietly repair. get_memory_agent() returns an
            # uninitialized instance by design, so this must be reported rather
            # than initialized here -- a checker that starts the subsystem it is
            # measuring can never report that it was down.
            metrics['initialized'] = bool(getattr(memory_agent, 'initialized', False))
            storage = getattr(memory_agent, 'postgres_storage', None)
            if storage is None:
                issues.append('Memory agent is not initialized — no storage attached')
                return metrics, issues
            if not hasattr(storage, 'get_statistics'):
                issues.append('Memory storage exposes no statistics provider — '
                              'memory health cannot be measured')
                return metrics, issues

            stats = await storage.get_statistics()
            if not stats or 'error' in stats:
                issues.append(
                    f"Memory statistics unavailable: {(stats or {}).get('error', 'no data')}")
                return metrics, issues

            agent_metrics = memory_agent.get_metrics() if hasattr(memory_agent, 'get_metrics') else {}

            # Prefixed by the sub-part that produced them, so a storage failure
            # and a cache failure are separable instead of one "memory: degraded".
            metrics['total_memories'] = stats['total_memories']        # headline
            metrics['storage_available'] = agent_metrics['postgres_available']
            metrics['storage_total_memories'] = stats['total_memories']
            metrics['storage_by_type'] = stats.get('by_type', {})
            metrics['storage_avg_importance'] = round(float(stats.get('avg_importance') or 0.0), 4)
            metrics['storage_failed_operations'] = stats.get('metrics', {}).get('failed_operations', 0)

            metrics['cache_size'] = agent_metrics['cache_size']
            metrics['cache_hits'] = agent_metrics['cache_hits']

            metrics['embedding_available'] = agent_metrics['embedding_available']

            metrics['write_queue'] = agent_metrics.get('write_queue_size', 0)

            if metrics['storage_failed_operations'] > 0:
                issues.append(f"{metrics['storage_failed_operations']} failed memory operations")

            if metrics['write_queue'] > 500:
                issues.append('Memory write queue backlogged')
            if metrics['total_memories'] > 200000:
                issues.append('High memory count - consider cleanup')

        except Exception as e:
            issues.append(f'Memory health check error: {str(e)}')
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_learning_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check learning system health"""
        metrics = {}
        issues = []

        try:
            from core.learning.enhanced_asi_self_improvement import get_asi_self_improvement
            asi = get_asi_self_improvement()
            # THE DURABLE RECORD, not this process's memory. `get_statistics()`
            # counts an in-process list, and the monitor builds a fresh
            # singleton on every check, so it reported 0 cycles while
            # unified.improvement_cycles held 11 -- scoring learning 46/100 and
            # blocking self-improvement because self-improvement had supposedly
            # never run.
            asi_stats = await asi.get_persisted_statistics()

            metrics['asi_total_cycles'] = asi_stats.get('total_cycles', 0)
            rate = asi_stats.get('success_rate')
            self._record_rate(metrics, 'asi_success_rate',
                              None if rate is None else round(rate, 3),
                              metrics.get('asi_total_cycles'))
            metrics['asi_improvements_deployed'] = asi_stats.get('total_improvements_deployed', 0)
            metrics['asi_avg_cycle_duration_sec'] = round(asi_stats.get('avg_cycle_duration', 0.0), 1)
            metrics['asi_components_improved'] = asi_stats.get('components_improved', 0)

            if (metrics['asi_total_cycles'] > 5
                    and metrics.get('asi_success_rate') is not None
                    and metrics['asi_success_rate'] < 0.3):
                issues.append(f"Low ASI improvement success rate: {metrics['asi_success_rate']:.0%} over {metrics['asi_total_cycles']} cycles")

        except Exception as _asi_err:
            metrics['asi_available'] = False
            logger.debug(f"ASI self-improvement stats unavailable: {_asi_err}")

        # CAPABILITY LOST SINCE THE BASELINE, not just work completed.
        #
        # Every ASI metric above counts what self-improvement DID -- cycles,
        # deployments, success rate. None of them can fall when the system gets
        # WORSE, so a run of successful cycles that quietly degraded three
        # components reported as healthy.
        #
        # `get_capability_regression_report` answers the other half -- "did we
        # lose abilities we had 30-60 cycles ago" -- and had zero callers.
        try:
            from core.learning.improvement_monitor import get_improvement_monitor

            regression_report = await get_improvement_monitor(
            ).get_capability_regression_report()
            regressed = regression_report.get("regressions") or []
            metrics['capability_regressions'] = len(regressed)
            metrics['capability_regressions_critical'] = sum(
                1 for r in regressed if r.get("severity") == "CRITICAL")

            for regression in regressed:
                if regression.get("severity") in ("CRITICAL", "HIGH"):
                    issues.append(
                        f"Capability regression ({regression['severity']}): "
                        f"{regression['component_name']}.{regression['metric_name']} "
                        f"lost {regression.get('pct_capability_lost')}% against a "
                        f"baseline held for {regression.get('cycles_tracked')} cycle(s)")
        except Exception as _reg_err:
            # An unavailable regression report is not an absence of regression.
            metrics['capability_regressions'] = None
            issues.append(f"Capability regression could not be assessed: {_reg_err}")
            logger.error("Capability regression report unavailable: %s", _reg_err)

        try:
            from core.learning.performance_profiler import get_performance_profiler
            profiler = get_performance_profiler()
            prof_stats = await profiler.get_statistics()

            metrics['profiler_total_profiles'] = prof_stats.get('total_profiles', 0)
            metrics['profiler_components'] = prof_stats.get('components_profiled', 0)
            metrics['profiler_avg_time_ms'] = prof_stats.get('avg_time_ms', 0.0)

            if prof_stats.get('avg_time_ms', 0) > 5000:
                issues.append(f"High average operation latency: {prof_stats['avg_time_ms']:.0f}ms")

        except Exception as _prof_err:
            logger.debug(f"Performance profiler stats unavailable: {_prof_err}")

        return metrics, issues

    async def _check_reasoning_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check reasoning system health"""
        metrics = {}
        issues = []

        try:
            from core.reasoning.neural_bridge import get_neural_bridge
            bridge = get_neural_bridge()
            bridge_stats = await bridge.get_statistics()

            metrics['neural_bridge_initialized'] = bridge.initialized if hasattr(bridge, 'initialized') else False
            metrics['reasoning_total_requests'] = bridge_stats.get('total_requests', 0)
            metrics['reasoning_avg_confidence'] = round(bridge_stats.get('average_confidence', 0.0), 3)
            metrics['reasoning_symbolic_requests'] = bridge_stats.get('symbolic_requests', 0)
            metrics['reasoning_hybrid_requests'] = bridge_stats.get('hybrid_requests', 0)

            if metrics['reasoning_total_requests'] > 10 and metrics['reasoning_avg_confidence'] < 0.3:
                issues.append(f"Low reasoning confidence: {metrics['reasoning_avg_confidence']:.0%} average over {metrics['reasoning_total_requests']} requests")

        except Exception as _bridge_err:
            metrics['neural_bridge_available'] = False
            issues.append(f"Neural bridge unavailable: {_bridge_err}")

        try:
            from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
            bayes = get_bayesian_uncertainty()
            bayes_stats = bayes.get_statistics()
            # `total_updates` and `avg_uncertainty` are not keys this provider
            # returns -- both defaulted to 0, so the Bayesian engine reported
            # no activity whether or not it had any. These are its real keys.
            metrics['bayesian_beliefs_tracked'] = bayes_stats['beliefs_tracked']
            metrics['bayesian_active_beliefs'] = bayes_stats['active_beliefs']
            metrics['bayesian_calibration_updates'] = bayes_stats['calibration_updates']
            self._record_rate(metrics, 'bayesian_overconfidence_rate',
                              round(bayes_stats['overconfidence_rate'], 3),
                              bayes_stats['calibration_updates'])
            metrics['bayesian_consistency_violations'] = bayes_stats['consistency_violations']
            metrics['bayesian_persistence_healthy'] = bayes_stats['persistence_healthy']
            if not bayes_stats['persistence_healthy']:
                issues.append(
                    f"Bayesian belief persistence unhealthy "
                    f"({bayes_stats['persistence_drops']} drop(s))")

        except Exception as _bayes_err:
            logger.debug(f"Bayesian uncertainty stats unavailable: {_bayes_err}")

        return metrics, issues

    async def _check_agents_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check agents system health"""
        metrics = {}
        issues = []

        try:
            # THE QUEUE HAS NO SINGLETON. TaskQueue is a plain class; the one
            # the system runs on is built in AutonomousCoordinator.__init__ and
            # held as `self.task_queue`. This read `TaskQueue._instance` and
            # then `task_queue._task_queue_instance`, neither of which is
            # defined anywhere, so `tq` was None on every run and
            # `queue_available = False` was written whether or not the queue was
            # up -- which is the issue the improvement cycle then tried, and
            # failed, to remediate for two days.
            #
            # get_autonomous_coordinator() returns the existing instance and
            # only constructs when handed a teacher model, so calling it with no
            # arguments observes without creating.
            from core.agents.autonomous.autonomous_coordinator import (
                get_autonomous_coordinator)
            coordinator = await get_autonomous_coordinator()
            tq = getattr(coordinator, 'task_queue', None) if coordinator else None

            if tq is not None:
                # QueueAuthority API (post queue-authority migration): get_metrics()
                # returns total_tasks_added/current_queue_size + tasks_completed/
                # tasks_failed/tasks_requeued. The old task_queue attributes
                # (total_tasks_completed, .metrics) no longer exist — reading them
                # raised here and aborted the whole agents probe.
                tq_metrics = tq.get_metrics()
                metrics['queue_pending'] = tq.get_queue_length()
                metrics['queue_total_added'] = tq_metrics.get('total_tasks_added', 0)
                metrics['queue_total_completed'] = tq_metrics.get('tasks_completed', 0)
                metrics['queue_tasks_failed'] = tq_metrics.get('tasks_failed', 0)
                metrics['queue_tasks_requeued'] = tq_metrics.get('tasks_requeued', 0)

                total_finished = metrics['queue_total_completed'] + metrics['queue_tasks_failed']
                if total_finished > 0:
                    failure_rate = metrics['queue_tasks_failed'] / total_finished
                    metrics['task_failure_rate'] = round(failure_rate, 3)
                    if failure_rate > 0.5 and total_finished >= 10:
                        issues.append(f"High task failure rate: {failure_rate:.0%} ({metrics['queue_tasks_failed']} failed / {total_finished} finished)")
                else:
                    # UNDEFINED, not 0%. No finished task means no
                    # failure rate exists; 0.0 clears the >0.5 gate above and
                    # reads as a perfect record built from no observations.
                    metrics['task_failure_rate'] = None

                if metrics['queue_pending'] > 50:
                    issues.append(f"Large task backlog: {metrics['queue_pending']} tasks pending")
            else:
                metrics['queue_available'] = False
                logger.debug('Task queue singleton not found for health check')

            # CONSTITUTION metrics (drift-assessment authority) — surfaced so the
            # health monitor can see it is actually running, not just present.
            constitution = getattr(coordinator, 'constitution', None) if coordinator else None
            if constitution is not None:
                try:
                    cstat = await constitution.get_constitution_status()
                    metrics['constitution_active'] = cstat.get('active')
                    metrics['constitution'] = cstat.get('metrics', {})
                    last_avg = (cstat.get('metrics') or {}).get('last_average_compliance')
                    if last_avg is not None and last_avg < 0.75:
                        issues.append(f"Constitutional alignment low: {last_avg:.0%}")
                except Exception as _ce:
                    logger.debug('constitution metrics unavailable: %s', _ce)

            # DIRECTIVE system metrics (governance + learning-authority-owned) —
            # honest counters of governance decisions and application outcomes.
            directive_system = getattr(coordinator, 'directive_system', None) if coordinator else None
            if directive_system is not None:
                try:
                    dsum = await directive_system.get_system_summary()
                    metrics['directives'] = {
                        'total': dsum.get('total_directives'),
                        'by_status': dsum.get('directives_by_status'),
                        'application': dsum.get('application_metrics'),
                        'governance': dsum.get('governance'),
                    }
                except Exception as _de:
                    logger.debug('directive metrics unavailable: %s', _de)

        except Exception as e:
            issues.append(f"Agents health check error: {str(e)}")
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_security_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check security system health"""
        metrics = {}
        issues = []

        try:
            from core.security.controller import get_security_controller

            security = get_security_controller()

            # Get security statistics
            stats = await security.get_statistics()

            metrics['security_level'] = stats.get('security_level', 'unknown')
            metrics['blocked_requests'] = stats.get('blocked_requests', 0)
            metrics['security_violations'] = stats.get('security_violations', 0)

            # Check for security issues
            if metrics['security_violations'] > 100:
                issues.append("High number of security violations")

        except Exception as e:
            issues.append(f"Security health check error: {str(e)}")
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_security_audit_health(self) -> tuple[Dict[str, Any], List[str]]:
        """The guardian's continuous security audit: findings and resolution.

        Its own component now, not folded into the substrate's security
        controller. An unresolved backlog -- especially a CRITICAL finding -- is
        a real, honest degradation of the system's security posture, surfaced
        here where an always-on scanner belongs.
        """
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        try:
            from core.security.security_audit_worker import get_audit_worker

            stats = await get_audit_worker().get_statistics()
            active = int(stats.get('active_findings', 0) or 0)
            critical = int(stats.get('critical_findings', 0) or 0)
            resolution = float(stats.get('resolution_rate', 0.0) or 0.0)  # 0-100
            metrics['audit_monitoring_active'] = bool(stats.get('monitoring_active', False))
            metrics['audit_total_audits'] = int(stats.get('total_audits', 0) or 0)
            metrics['audit_active_findings'] = active
            metrics['audit_critical_findings'] = critical
            self._record_rate(metrics, 'audit_resolution_rate',
                              round(resolution / 100.0, 3), active or 1)

            if not metrics['audit_monitoring_active']:
                issues.append("Security audit scanner is not running")
            if critical > 0:
                issues.append(f"{critical} unresolved CRITICAL security finding(s)")
            if active > 0 and resolution == 0.0:
                issues.append(f"{active} active finding(s), none resolved")
        except Exception as e:
            issues.append(f"Security audit health check error: {type(e).__name__}: {e}")
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_storage_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check storage system health"""
        metrics = {}
        issues = []

        try:
            # Check disk usage
            disk = psutil.disk_usage('/')

            metrics['disk_total_gb'] = disk.total / (1024**3)
            metrics['disk_used_gb'] = disk.used / (1024**3)
            metrics['disk_free_gb'] = disk.free / (1024**3)
            metrics['disk_percent'] = disk.percent
            # A normalised signal so this contributes to the weighted score.
            # The check measured real bytes and emitted nothing the evaluator
            # could weigh, so the component read UNKNOWN on full evidence.
            metrics['storage_capacity_rate'] = round(max(0.0, 1.0 - disk.percent / 100.0), 4)
            metrics['storage_available'] = True

            # Correctness FIRST, performance second. Capacity headroom says
            # nothing about whether state can actually be persisted and read
            # back, so a read-after-write probe is the gate and the disk numbers
            # are weighted context. The probe uses a dedicated health row and
            # rolls it back rather than writing arbitrary production rows.
            declared: List[HealthMetric] = [HealthMetric(
                name="capacity_headroom", raw_value=disk.percent,
                normalized=lower_is_better(disk.percent, fail=95.0, healthy=70.0),
                weight=0.2)]
            rw_ok, rw_reason = await self._storage_roundtrip_probe()
            declared.append(HealthMetric(
                name="read_after_write", raw_value=rw_ok,
                normalized=invariant(rw_ok), weight=0.35,
                required=True, critical=True, reason=rw_reason))
            metrics['read_after_write_ok'] = rw_ok
            if not rw_ok:
                issues.append(f"storage read-after-write failed: {rw_reason}")
            self._declared_metrics['storage'] = declared

            # Check thresholds
            if disk.percent > self.thresholds['disk_critical']:
                issues.append(f"CRITICAL: Disk usage at {disk.percent}%")
            elif disk.percent > self.thresholds['disk_warning']:
                issues.append(f"WARNING: Disk usage at {disk.percent}%")

        except Exception as e:
            issues.append(f"Storage health check error: {str(e)}")
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_api_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check API system health"""
        metrics = {}
        issues = []

        try:
            from core.integration.external_api_integration_manager import get_api_manager

            api_manager = get_api_manager()

            # ExternalAPIIntegrationManager has no get_statistics(). The call
            # raised AttributeError on every cycle, the except below stored the
            # exception text as a metric, and the component graded DEGRADED for
            # the whole life of the system -- reporting the checker's own defect
            # as the API layer's health. Its real surface is health_check() /
            # get_available_providers() / get_usage() / get_total_cost().
            providers = api_manager.get_available_providers()
            health = await api_manager.health_check() or {}  # health_check is async

            metrics['available_providers'] = len(providers)
            metrics['provider_names'] = sorted(str(p) for p in providers)
            metrics['healthy_providers'] = sum(1 for ok in health.values() if ok)
            metrics['registered_apis'] = len(getattr(api_manager, 'api_registry', {}) or {})
            metrics['api_available'] = bool(providers)
            if health:
                metrics['api_provider_health_rate'] = round(
                    metrics['healthy_providers'] / len(health), 4)
            metrics['total_cost'] = float(await api_manager.get_total_cost() or 0.0)  # async

            # health_check() reports per-provider reachability. An empty result
            # means no provider has been probed yet, which is not the same as
            # every provider being down and is not reported as such.
            unhealthy = sorted(str(p) for p, ok in health.items() if not ok)
            if unhealthy:
                issues.append(f"API providers unreachable: {', '.join(unhealthy)}")
            if not providers:
                issues.append('No external API providers are configured')

        except Exception as e:
            issues.append(f"API health check error: {str(e)}")
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_quantum_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check quantum system health"""
        metrics = {}
        issues = []

        try:
            from core.quantum.quantum_factory import quantum_health_check, get_quantum_capabilities
            result = await quantum_health_check()

            metrics['quantum_available'] = result.get('healthy', False)
            metrics['quantum_status'] = result.get('status', 'unknown')
            metrics['quantum_backend'] = result.get('backend', result.get('backend_name', 'none'))
            metrics['quantum_total_jobs'] = result.get('total_jobs', 0)
            metrics['quantum_success_rate'] = round(result.get('success_rate', 0.0), 3)

            # Also report which capabilities are present
            caps = get_quantum_capabilities()
            if caps:
                metrics['quantum_capabilities'] = list(caps.keys()) if isinstance(caps, dict) else str(caps)

            if not metrics['quantum_available']:
                # Not critical — quantum is optional in this deployment
                status_msg = result.get('message', result.get('status', 'unavailable'))
                logger.debug(f"Quantum subsystem not available: {status_msg}")
            elif metrics['quantum_total_jobs'] > 0 and metrics['quantum_success_rate'] < 0.5:
                issues.append(f"Low quantum job success rate: {metrics['quantum_success_rate']:.0%}")

        except Exception as e:
            metrics['quantum_available'] = False
            metrics['quantum_status'] = 'error'
            issues.append(f"Quantum health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Quantum health check error (non-critical): {e}")

        return metrics, issues

    #: The network paths Torin actually requires, and whether each is essential.
    #: Health means "the communication this substrate depends on works", not
    #: "the internet is reachable" -- an optional integration being down must
    #: not declare the network unhealthy.
    REQUIRED_NETWORK_PATHS = (
        ("llm_server", "LLM_SERVER_URL", True),
        ("database", None, True),
    )

    @staticmethod
    def _rate_or_unknown(value: Any, denominator: Any) -> Optional[float]:
        """A rate is UNDEFINED when nothing has been counted.

        Providers return 0.0 for success_rate when zero cycles have run, and the
        evaluator cannot tell that from a measured 0% success, so reporting it
        as None stops "nothing has happened yet" being indistinguishable from
        "everything failed".

        Prefer `_record_rate`, which additionally tells the evaluator WHY the
        value is None. This returns a bare scalar, so both reasons arrive as the
        same None and both count as missing evidence.
        """
        try:
            if denominator is None or float(denominator) <= 0:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _record_rate(metrics: Dict[str, Any], key: str,
                     value: Any, denominator: Any) -> None:
        """Record a rate, distinguishing undefined from unread.

        One None was doing two jobs. A rate over zero observations has no value
        to report -- that is arithmetic, and the subsystem is fine. A value that
        could not be coerced is a reading that failed, which is missing
        evidence. Collapsing them meant an idle component never reached full
        coverage and so could never grade HEALTHY, however well it was running.

        Only the code computing the value knows which case it is, so it is
        recorded here rather than guessed by the evaluator.
        """
        try:
            if denominator is None or float(denominator) <= 0:
                metrics[key] = None
                metrics.setdefault('_not_applicable', []).append(key)
                return
        except (TypeError, ValueError):
            # A denominator that is not a number is a broken reading, not an
            # empty one -- it stays missing evidence.
            metrics[key] = None
            return
        try:
            metrics[key] = float(value)
        except (TypeError, ValueError):
            metrics[key] = None

    async def _storage_roundtrip_probe(self) -> tuple:
        """Write a health row, read it back, roll it back.

        Answers the question capacity cannot: can state be correctly persisted
        and retrieved? A store that responds quickly with wrong state is not
        healthy, so this is a gate rather than a weighted signal.
        """
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            token = f"probe_{os.getpid()}_{int(time.time())}"
            await db.execute_query(
                """CREATE TABLE IF NOT EXISTS unified.storage_health_probe (
                       probe_id VARCHAR(128) PRIMARY KEY,
                       written_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
                commit=True)
            await db.execute_query(
                "INSERT INTO unified.storage_health_probe (probe_id) VALUES ($1) "
                "ON CONFLICT (probe_id) DO NOTHING", (token,), commit=True)
            rows = await db.execute_query(
                "SELECT probe_id FROM unified.storage_health_probe WHERE probe_id = $1",
                (token,), fetch_all=True)
            await db.execute_query(
                "DELETE FROM unified.storage_health_probe WHERE probe_id = $1",
                (token,), commit=True)
            if not rows or rows[0]["probe_id"] != token:
                return False, "value written was not read back"
            return True, None
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:80]}"

    async def _check_network_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Network health = Torin's required communication paths work.

        This counted psutil packet totals, which say nothing about whether the
        substrate can reach what it depends on, and emitted no normalized
        signal at all -- so the component evaluated to UNKNOWN on a full set of
        real numbers. Reachability of a REQUIRED dependency is the signal; the
        interface counters are context.
        """
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        declared: List[HealthMetric] = []

        # Interface counters: context, not health.
        try:
            net_io = psutil.net_io_counters()
            metrics['bytes_sent'] = net_io.bytes_sent
            metrics['bytes_recv'] = net_io.bytes_recv
            metrics['packets_sent'] = net_io.packets_sent
            metrics['packets_recv'] = net_io.packets_recv
            metrics['errors_in'] = net_io.errin
            metrics['errors_out'] = net_io.errout
            total_packets = max(1, net_io.packets_sent + net_io.packets_recv)
            err_rate = (net_io.errin + net_io.errout) / total_packets
            metrics['interface_error_rate'] = round(err_rate, 6)
            declared.append(HealthMetric(
                name="interface_error_rate", raw_value=err_rate,
                normalized=lower_is_better(err_rate, fail=0.01, healthy=0.0),
                weight=0.2))
        except Exception as e:
            issues.append(f"Interface counters unavailable: {e}")

        # Required paths. Each names itself in the reason code so a failure
        # identifies WHICH dependency is unreachable.
        reachable = 0
        probed = 0
        for name, env_var, essential in self.REQUIRED_NETWORK_PATHS:
            ok: Optional[bool] = None
            try:
                if name == "database":
                    from core.database import get_database_manager
                    db = get_database_manager()
                    rows = await db.execute_query("SELECT 1 AS ok", fetch_all=True)
                    ok = bool(rows)
                else:
                    url = os.getenv(env_var or "")
                    if not url:
                        metrics[f'path_{name}'] = 'not_configured'
                        continue
                    import httpx
                    try:
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            resp = await client.get(f"{url.rstrip('/')}/v1/models")
                            ok = resp.status_code < 500
                    except (httpx.ReadTimeout, httpx.PoolTimeout):
                        # BUSY IS NOT UNREACHABLE. llama-server serves one
                        # request at a time, so /v1/models queues behind an
                        # in-flight generation and blows a 5s budget whenever
                        # the teacher model is answering. This is a CRITICAL gate, so a
                        # normal inference load flipped the whole network
                        # component to UNHEALTHY and made system_awareness
                        # report critical services down -- while inference was
                        # completing successfully.
                        #
                        # ReadTimeout means the connection was established and
                        # the response was slow; ConnectTimeout/ConnectError
                        # mean the path itself is down. Only the second is a
                        # reachability failure. How fast the model answers is
                        # the llm component's measurement, not this one's.
                        ok = True
                        metrics[f'path_{name}_slow'] = True
            except Exception as e:
                ok = False
                issues.append(f"required_dependency_unreachable:{name} ({type(e).__name__})")

            probed += 1
            metrics[f'path_{name}_reachable'] = ok
            if ok:
                reachable += 1
            declared.append(HealthMetric(
                name=f"path_{name}_reachable", raw_value=ok,
                normalized=invariant(bool(ok)), weight=0.8 if essential else 0.2,
                required=essential, critical=essential,
                reason=None if ok else f"required_dependency_unreachable:{name}"))

        if probed:
            metrics['required_path_reachability'] = round(reachable / probed, 4)

        self._declared_metrics['network'] = declared
        return metrics, issues

    async def _check_llm_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check the teacher model health — model loaded, throughput, failure rate"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            # `.statistics` is the raw counter dict (9 keys). get_statistics()
            # is the provider, and it adds the three signals that actually say
            # whether inference can be served at all: model_loaded, worker_alive
            # and inference_queue_size. Reading the attribute meant the guessing
            # chain below fell through to bool(None) -> False, so "model not
            # loaded" was reported whether or not it was.
            stats = llm.get_statistics()
            metrics['llm_model_loaded'] = bool(stats['model_loaded'])
            metrics['llm_total_requests'] = stats.get('total_requests', 0)
            metrics['llm_successful_requests'] = stats.get('successful_requests', 0)
            metrics['llm_failed_requests'] = stats.get('failed_requests', 0)
            metrics['llm_total_tokens'] = stats.get('total_tokens', 0)
            metrics['llm_avg_processing_time_sec'] = round(float(stats.get('avg_processing_time', 0.0)), 2)
            # The provider returns these and nothing read them: a dead inference
            # worker is the difference between "no requests yet" and "requests
            # cannot be served at all", and both looked identical.
            metrics['llm_queue_depth'] = stats['inference_queue_size']

            # THE WORKER IS A LOCAL-MODE CONCEPT. `worker_alive` reads
            # `_worker_task`, which exists to serialise access to an in-process
            # Llama object; it is created only on the local model-loading path.
            # Production runs remote (LLM_SERVER_URL), where there is no such
            # object and therefore no worker by design -- so this gate reported
            # "requests cannot be served" as CRITICAL while requests were being
            # served successfully. A signal that is inapplicable to the running
            # mode is not evidence of failure; it is not evidence at all.
            #
            # `_remote_client` is the runtime discriminator: it is set only
            # after the remote handshake succeeds and reset to None when remote
            # becomes unavailable.
            remote = getattr(llm, '_remote_client', None) is not None
            metrics['llm_mode'] = 'remote' if remote else 'local'

            if remote:
                # A handshake that succeeded at startup is not proof the teacher model is
                # reachable now, so this measures it rather than trusting the
                # flag. Short timeout: the client's own is the 600s inference
                # timeout, which would hang the health check.
                try:
                    r = await llm._remote_client.get(
                        f"{llm.remote_url}/v1/models", timeout=5.0)
                    metrics['llm_remote_endpoint_connected'] = (r.status_code == 200)
                    if r.status_code != 200:
                        issues.append(
                            f"LLM server returned HTTP {r.status_code} — inference unavailable")
                except Exception as e:
                    metrics['llm_remote_endpoint_connected'] = False
                    issues.append(f"LLM server unreachable at {llm.remote_url}: {e}")
            else:
                metrics['llm_queue_worker_alive'] = stats['worker_alive']
                if not stats['worker_alive']:
                    issues.append(
                        'LLM inference worker is not alive — requests cannot be served')

            total = metrics['llm_total_requests']
            if total > 0:
                failure_rate = metrics['llm_failed_requests'] / total
                metrics['llm_failure_rate'] = round(failure_rate, 3)
                if failure_rate > 0.3 and total >= 5:
                    issues.append(
                        f"High LLM failure rate: {failure_rate:.0%} "
                        f"({metrics['llm_failed_requests']}/{total})"
                    )
            else:
                # No request has been made; a failure rate over zero
                # observations is undefined, not zero -- and undefined for that
                # reason is not missing evidence, so it does not count against
                # coverage.
                metrics['llm_failure_rate'] = None
                metrics['_not_applicable'] = ['llm_failure_rate']

            if not metrics['llm_model_loaded']:
                issues.append("LLM model not loaded — inference unavailable")

            if metrics['llm_avg_processing_time_sec'] > 120:
                issues.append(
                    f"Slow LLM response: avg {metrics['llm_avg_processing_time_sec']:.1f}s"
                )

        except Exception as e:
            issues.append(f"LLM health check error: {str(e)}")
            metrics['error'] = str(e)

        return metrics, issues

    async def _check_governance_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check governance system health — evaluation counts, rejection rate, enforcement level"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.governance.unified_governance_trigger_system import get_unified_governance
            gov = get_unified_governance()

            # EVERY READ HERE WAS INVENTED.
            #
            # UnifiedGovernanceTriggerSystem has no `stats`, no `initialized` and
            # no `enforcement_level` -- its surface is config / trigger_cache /
            # enforcement_manager / evaluate_action. So:
            #   stats            -> {}    -> all counts reported 0
            #   initialized      -> getattr default True  -> ALWAYS "initialized",
            #                       which made the "not initialized" issue below
            #                       unreachable by construction
            # Governance reported 0 evaluations while unified.safety_assessments
            # held 3,775 of them.
            #
            # The counts are persisted, so they are read from where they live.
            from core.database import get_database_manager
            db = get_database_manager()
            counts = await db.execute_query(
                """SELECT count(*) AS total,
                          count(*) FILTER (WHERE approved IS TRUE)  AS approved,
                          count(*) FILTER (WHERE approved IS FALSE) AS rejected
                   FROM unified.safety_assessments""",
                fetch_all=True,
            )
            row = counts[0] if counts else {'total': 0, 'approved': 0, 'rejected': 0}

            # Real liveness: the rule engine is usable only if its triggers loaded.
            trigger_cache = getattr(gov, 'trigger_cache', None) or {}
            metrics['governance_initialized'] = bool(trigger_cache)
            metrics['governance_trigger_categories'] = len(trigger_cache)
            metrics['governance_total_evaluations'] = int(row['total'])
            metrics['governance_approved'] = int(row['approved'] or 0)
            metrics['governance_rejected'] = int(row['rejected'] or 0)

            # enforcement_manager is a real attribute and is None when no
            # enforcement is attached -- reported instead of an invented level.
            enforcement = getattr(gov, 'enforcement_manager', None)
            metrics['governance_enforcement_attached'] = enforcement is not None
            metrics['governance_enforcement_level'] = str(
                getattr(enforcement, 'mode', 'none') if enforcement else 'none')
            if enforcement is None:
                issues.append('Governance enforcement manager not attached — '
                              'triggers evaluate but nothing enforces them')

            total = metrics['governance_total_evaluations']
            if total > 0:
                rejection_rate = metrics['governance_rejected'] / total
                metrics['governance_rejection_rate'] = round(rejection_rate, 3)
                if rejection_rate > 0.5 and total >= 10:
                    issues.append(
                        f"High governance rejection rate: {rejection_rate:.0%} — "
                        "system may be over-constrained or misconfigured"
                    )
            else:
                # No evaluation recorded -- rejection rate undefined.
                metrics['governance_rejection_rate'] = None

            if not metrics.get('governance_initialized', True):
                issues.append("Governance system not initialized — actions are ungoverned")

        except Exception as e:
            metrics['governance_available'] = False
            # A FAILED CHECK HAS TO SAY WHY. The *_available gate fires, so the
            # component grades correctly -- but the cause went only to a debug
            # log and no issue was recorded, leaving an unexplained CRITICAL for
            # the operator and nothing for the remediation path, which selects
            # what to do from `issues`. Same at the eight sibling checks.
            issues.append(f"Governance health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Governance health check error: {e}")

        return metrics, issues

    async def _check_chaos_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check chaos engineering safety controller — circuit breaker states"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.chaos.safety_controller import get_safety_controller
            controller = get_safety_controller()

            circuit_breakers = getattr(controller, 'circuit_breakers', {})
            metrics['chaos_circuit_breaker_count'] = len(circuit_breakers)
            metrics['chaos_max_concurrent_experiments'] = getattr(
                controller, 'max_concurrent_experiments', 3
            )

            open_breakers: List[str] = []
            for target, breaker in circuit_breakers.items():
                state = getattr(breaker, 'state', None)
                if state is not None:
                    state_val = state.value if hasattr(state, 'value') else str(state)
                    if state_val in ('open', 'half_open'):
                        open_breakers.append(target)

            metrics['chaos_open_circuit_breakers'] = len(open_breakers)
            metrics['chaos_available'] = True
            if circuit_breakers:
                metrics['chaos_breaker_open_rate'] = round(
                    len(open_breakers) / len(circuit_breakers), 4)
            if open_breakers:
                issues.append(
                    f"Circuit breakers OPEN for: {', '.join(open_breakers[:5])}"
                )

        except Exception as e:
            metrics['chaos_available'] = False
            issues.append(f"Chaos safety controller health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Chaos safety controller health check error: {e}")

        return metrics, issues

    async def _check_safety_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check the safety layer — the framework that gates actions, and the
        commitment contracts subsystem alongside it.

        THIS MEASURED THE WRONG SUBSYSTEM. The whole verdict came from
        `CommitmentContractManager._instance`, which nothing constructs, so
        `safety` graded CRITICAL permanently -- while SafetyFramework, the
        single entry point every tool call and task evaluation routes through,
        was not measured at all. The component reporting critical and the
        component's actual enforcement being unobserved were the same bug: the
        check was pointed at a subsystem that is not on the enforcement path.

        Contracts are still reported, because absent is a fact worth recording.
        They no longer decide the verdict: a subsystem nothing has wired cannot
        be the reason the safety layer reads as failing, and letting it be that
        reason is what hid the enforcement signals behind a permanent CRITICAL.

        Metrics are DECLARED here rather than inferred from name suffixes, so
        which signals gate is stated explicitly instead of following from the
        fact that a key happens to end in `_initialized`.
        """
        metrics: Dict[str, Any] = {}
        issues: List[str] = []
        declared: List[HealthMetric] = []

        try:
            # Read the module singleton rather than calling the factory: the
            # factory CREATES the framework when absent, so measuring through it
            # would bring into existence the thing being measured and always
            # report success.
            from core.security import safety_framework as sf_mod
            framework = getattr(sf_mod, '_safety_framework', None)

            metrics['safety_framework_initialized'] = framework is not None
            declared.append(HealthMetric(
                name='safety_framework_initialized', raw_value=framework is not None,
                normalized=invariant(framework is not None), weight=1.0,
                required=True, critical=True,
                reason=None if framework else 'safety framework not constructed'))

            if framework is None:
                issues.append('Safety framework not initialized — '
                              'actions are evaluated by nothing')
            else:
                stats = framework.get_statistics()

                blocking = bool(stats.get('blocking_enabled'))
                metrics['safety_blocking_enabled'] = blocking
                declared.append(HealthMetric(
                    name='safety_blocking_enabled', raw_value=blocking,
                    normalized=invariant(blocking), weight=1.0,
                    required=True, critical=True,
                    reason=None if blocking else 'evaluations run but nothing is blocked'))
                if not blocking:
                    issues.append('Safety blocking disabled — violations are '
                                  'detected but actions still execute')

                # Recorded, deliberately not gated. SafetyFramework.constraints
                # is assigned an empty list in __init__ and nothing anywhere
                # appends to it -- its only reader is this statistic. Gating on
                # `> 0` would be permanently unsatisfiable, which is the same
                # defect as the contract gate below: a critical check that no
                # reachable state can pass. Enforcement lives in the pattern and
                # validation layers, not in this field.
                metrics['safety_constraints_loaded'] = int(stats.get('constraints_count', 0))

                evaluations = int(stats.get('evaluations_performed', 0))
                violations = int(stats.get('violations_detected', 0))
                metrics['safety_evaluations_performed'] = evaluations
                metrics['safety_violations_detected'] = violations
                metrics['safety_events_logged'] = int(stats.get('events_logged', 0))

                # get_statistics() divides by total_evaluations and returns 0.0
                # when there have been none. A 0% violation rate over zero
                # evaluations is not a clean record, and as a cost rate it would
                # normalise to a perfect 1.0.
                self._record_rate(metrics, 'safety_violation_rate',
                                  round(float(stats.get('violation_rate', 0.0)), 3),
                                  evaluations)
                rate = metrics['safety_violation_rate']
                declared.append(HealthMetric(
                    name='safety_violation_rate', raw_value=rate,
                    normalized=None if rate is None else lower_is_better(rate, 0.2, 0.0),
                    weight=0.5, required=False, critical=False))

            # THE CONTRACT GATE COULD NEVER PASS. This read
            # `CommitmentContractManager._instance` -- an attribute the class
            # does not define and nothing anywhere assigns -- so the getattr
            # default made `safety_contracts_initialized` False on every run.
            # As a `_initialized` key on a critical component that is an
            # automatic gate, so `safety` reported CRITICAL permanently, for a
            # condition no reachable state could satisfy.
            #
            # The manager was initialized the whole time: SafetyFramework builds
            # one in __init__ and holds it as `contract_manager`. That is the
            # real handle, so it is the one read here.
            manager_instance = getattr(framework, 'contract_manager', None)
            metrics['safety_contracts_initialized'] = manager_instance is not None

            if manager_instance is None:
                issues.append('Commitment contract manager not initialized — '
                              'contract verification is not running')
            else:
                # TWO CLASSES SHARE THIS NAME. core/safety/commitment_contracts
                # holds the one SafetyFramework constructs; the one this check
                # used to import, core/safety/commitment_contract_manager, is a
                # separate implementation that nothing on the enforcement path
                # builds. They do not share an interface -- the live one's
                # get_contract_stats is sync and returns a dict, the other's is
                # async and returns a ContractStats -- so the `await ... .field`
                # here was wrong for the object actually in use. It never raised
                # only because the impossible gate above returned first.
                #
                # That method is also a stub (`return {}`), so the counts are
                # read from the state the manager really keeps. Reporting the
                # stub's zeros would say "measured: no contracts, no violations"
                # about a subsystem that measured nothing.
                contracts = getattr(manager_instance, 'contracts', None)
                violations_by_cat = getattr(manager_instance, 'violations_by_category', None)
                metrics['safety_contract_stats_implemented'] = bool(
                    manager_instance.get_contract_stats())

                if contracts is None or violations_by_cat is None:
                    issues.append('Commitment contract manager exposes no contract state')
                else:
                    total = len(contracts)
                    violated = sum(len(v) for v in violations_by_cat.values())
                    metrics['safety_total_contracts'] = total
                    metrics['safety_violated_contracts'] = violated
                    self._record_rate(metrics, 'safety_contract_violation_rate',
                                      (violated / total) if total else 0.0, total)
                    c_rate = metrics['safety_contract_violation_rate']
                    declared.append(HealthMetric(
                        name='safety_contract_violation_rate', raw_value=c_rate,
                        normalized=None if c_rate is None else lower_is_better(c_rate, 0.2, 0.0),
                        weight=0.5, required=False, critical=False))

                    if c_rate is not None and c_rate > 0.2 and total >= 5:
                        issues.append(
                            f"High commitment violation rate: {c_rate:.0%}"
                        )

            self._declared_metrics['safety'] = declared

        except Exception as e:
            metrics['safety_available'] = False
            issues.append(f"Safety framework health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Safety framework health check error: {e}")

        return metrics, issues

    async def _check_backup_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check backup system health — scheduler active, last run time, success rate"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.services.backup_scheduler import get_backup_scheduler
            scheduler = get_backup_scheduler()

            stats = await scheduler.get_statistics()
            metrics['backup_total_runs'] = stats.get('total_backups', 0)
            metrics['backup_successful'] = stats.get('successful_backups', 0)
            metrics['backup_failed'] = stats.get('failed_backups', 0)
            metrics['backup_success_rate_pct'] = round(stats.get('success_rate', 100.0), 1)
            metrics['backup_scheduler_active'] = stats.get('scheduler_active', False)
            metrics['backup_configs'] = stats.get('total_configs', 0)

            last_backup = stats.get('last_backup_time')
            if last_backup:
                metrics['backup_last_run'] = str(last_backup)
                try:
                    last_ts = datetime.fromisoformat(str(last_backup))
                    age_hours = (datetime.now() - last_ts).total_seconds() / 3600
                    metrics['backup_age_hours'] = round(age_hours, 1)
                    if age_hours > 48:
                        issues.append(f"Backup stale: last run {age_hours:.0f}h ago")
                    elif age_hours > 24:
                        issues.append(f"Backup overdue: last run {age_hours:.0f}h ago")
                except Exception:
                    pass
            else:
                metrics['backup_last_run'] = None

            if metrics['backup_total_runs'] > 0 and metrics['backup_success_rate_pct'] < 70:
                issues.append(
                    f"Low backup success rate: {metrics['backup_success_rate_pct']:.0f}%"
                )

            if not metrics['backup_scheduler_active']:
                issues.append("Backup scheduler is inactive")

        except Exception as e:
            metrics['backup_available'] = False
            issues.append(f"Backup health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Backup health check error: {e}")

        return metrics, issues

    async def _check_threat_intel_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check threat intelligence engine — sources configured, cache stats"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.security import get_integrated_security_system
            sec_sys = get_integrated_security_system()
            if sec_sys is None:
                # Observing must not create the system; absence is the finding.
                metrics['threat_intel_available'] = False
                metrics['firewall_available'] = False
                metrics['reason'] = 'integrated security system not initialised'
                return metrics, issues
            threat_intel = sec_sys.get('threat_intel')

            if threat_intel is None or isinstance(threat_intel, str):
                metrics['threat_intel_available'] = False
                issues.append("Threat intelligence engine not available in-process")
                return metrics, issues

            # The unavailable path reports threat_intel_available=False and
            # returns; the working path reported no liveness at all, so the
            # engine being present and answering was invisible to the evaluator.
            metrics['threat_intel_available'] = True
            stats = threat_intel.get_statistics()
            metrics['threat_intel_queries'] = stats.get('queries', 0)
            metrics['threat_intel_cache_hits'] = stats.get('cache_hits', 0)
            self._record_rate(metrics, 'threat_intel_cache_hit_rate',
                              round(float(stats.get('cache_hit_rate', 0.0)), 3),
                              metrics.get('threat_intel_queries'))
            metrics['threat_intel_internal_threats'] = stats.get('internal_threats_count', 0)
            metrics['threat_intel_sources_available'] = stats.get('sources_available', 0)
            metrics['threat_intel_cache_size'] = stats.get('cache_size', 0)

            if metrics['threat_intel_sources_available'] == 0:
                issues.append(
                    "No threat intelligence sources configured — "
                    "IP reputation lookups unavailable"
                )

        except Exception as e:
            metrics['threat_intel_available'] = False
            issues.append(f"Threat intelligence health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Threat intel health check error: {e}")

        return metrics, issues

    async def _check_firewall_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check firewall manager — active rules, blocked IPs, mode"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.security import get_integrated_security_system
            sec_sys = get_integrated_security_system()
            if sec_sys is None:
                # Observing must not create the system; absence is the finding.
                metrics['threat_intel_available'] = False
                metrics['firewall_available'] = False
                metrics['reason'] = 'integrated security system not initialised'
                return metrics, issues
            firewall = sec_sys.get('firewall')

            if firewall is None or isinstance(firewall, str):
                metrics['firewall_available'] = False
                return metrics, issues

            stats = firewall.get_statistics()
            metrics['firewall_active_rules'] = stats.get('active_rules', 0)
            metrics['firewall_blocked_ips'] = stats.get('blocked_ips', 0)
            # The provider's keys are rules_created / rules_deleted; `rules_added`
            # and `rules_removed` are not keys it returns and defaulted to 0.
            # Its genuine failure signals were also going unread.
            metrics['firewall_available'] = True
            metrics['firewall_rules_created'] = stats['rules_created']
            metrics['firewall_rules_deleted'] = stats['rules_deleted']
            metrics['firewall_rule_errors'] = stats['rule_errors']
            metrics['firewall_drift_detected'] = stats['drift_detected']
            if stats['rule_errors']:
                issues.append(f"{stats['rule_errors']} firewall rule error(s)")
            if stats['drift_detected']:
                issues.append('Firewall rule drift detected — OS rules differ from intended state')
            metrics['firewall_test_mode'] = stats.get('test_mode', True)
            metrics['firewall_os_type'] = stats.get('os_type', 'unknown')

            # ENFORCEMENT IS AT THE EDGE, NOT LOCAL pf. Every Dominion Labs
            # service ingresses through the API Gateway -> Cloudflare tunnel, so
            # the local firewall is intentionally dry-run and the Cloudflare WAF
            # is the real enforcement surface. Flagging local test_mode as a
            # degradation when the WAF is wired is a false signal -- it docked
            # the score to 90 and reported a standing -10% "regression" for the
            # intended configuration. Only flag test_mode when there is NO edge
            # enforcement to fall back on.
            waf = sec_sys.get('waf') if isinstance(sec_sys, dict) else None
            metrics['firewall_edge_enforcement'] = waf is not None
            if metrics['firewall_test_mode'] and waf is None:
                issues.append(
                    "Firewall in TEST MODE with no edge (Cloudflare) enforcement "
                    "— no IP blocking is active at any layer"
                )

        except Exception as e:
            metrics['firewall_available'] = False
            issues.append(f"Firewall health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Firewall health check error: {e}")

        return metrics, issues

    async def _check_content_security_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check content security scanner — scan counts, threat detection rate"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            # THE SCANNER IS NOT AN IN-PROCESS SINGLETON. It is owned by
            # ContentSecurityService in start_security_systems.py, which
            # constructs a ContentSecurityScanner and serves it over HTTP on a
            # port allocated under the service key `security_content`. Looking
            # for a module global in core.security.content_security therefore
            # reported "nothing constructs one" no matter what was running --
            # the capability exists and the check could not see it.
            #
            # Asking the port registry and then the service itself is the only
            # reading that distinguishes the three real states: not registered,
            # registered but down, and serving.
            from core.utils.port_manager import get_port_manager

            port = get_port_manager().get_port('security_content')
            if not port:
                metrics['content_security_available'] = False
                issues.append(
                    'Content security scanner is not running: no port is '
                    'registered for `security_content`. It is started by '
                    'start_security_systems.py, which owns the scanner.')
                return metrics, issues

            metrics['content_security_port'] = port
            scanner = await self._content_security_service(port)
            if scanner is None:
                metrics['content_security_available'] = False
                issues.append(
                    f'Content security scanner registered on port {port} but '
                    f'not answering; the service is down, not absent')
                return metrics, issues

            stats = scanner
            metrics['content_scans_performed'] = stats.get('scans_performed', 0)
            metrics['content_threats_found'] = stats.get('threats_found', 0)
            metrics['content_security_available'] = True

            scans = metrics['content_scans_performed']
            # Declared through _record_rate like every other rate here: a threat
            # rate over zero scans is undefined arithmetic, not a failed
            # reading, and leaving it as a bare None held a running-but-idle
            # scanner below full coverage so it could never grade HEALTHY.
            self._record_rate(
                metrics, 'content_threat_rate',
                round(metrics['content_threats_found'] / scans, 3) if scans else None,
                scans)
            rate = metrics.get('content_threat_rate')
            if rate is not None and rate > 0.1:
                issues.append(
                    f"High content threat rate: {rate:.0%} of scanned content")

        except Exception as e:
            metrics['content_security_available'] = False
            issues.append(f"Content security health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Content security health check error: {e}")

        return metrics, issues

    #: Long enough for a local service to answer, short enough that a hung one
    #: does not stall the whole health sweep behind it.
    _SERVICE_PROBE_TIMEOUT_SEC = 2.0

    async def _content_security_service(self, port: int) -> Optional[Dict[str, Any]]:
        """Statistics from the running scanner service, or None if it is down.

        None means "did not answer", never "answered zero". The distinction is
        the whole point: a service that is down and one that has scanned
        nothing are different findings, and averaging a zero for the first
        invents a measurement.
        """
        import aiohttp

        try:
            timeout = aiohttp.ClientTimeout(total=self._SERVICE_PROBE_TIMEOUT_SEC)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"http://localhost:{port}/health") as response:
                    if response.status != 200:
                        return None
                    await response.json()
                async with session.get(f"http://localhost:{port}/statistics") as response:
                    if response.status != 200:
                        # Serving but with no statistics endpoint: alive, and
                        # nothing further can be measured about it.
                        return {}
                    return await response.json()
        except Exception as e:
            logger.debug("content security service probe failed on %s: %s", port, e)
            return None

    async def _check_malware_sandbox_health(self) -> tuple[Dict[str, Any], List[str]]:
        """Check malware sandbox — analysis counts, malicious detection rate"""
        metrics: Dict[str, Any] = {}
        issues: List[str] = []

        try:
            from core.security.malware_sandbox import get_malware_sandbox
            sandbox = get_malware_sandbox()

            stats = await sandbox.get_statistics()
            metrics['sandbox_available'] = True
            metrics['sandbox_total_analyses'] = stats.get('total_analyses', 0)
            metrics['sandbox_malicious_detected'] = stats.get('malicious_detected', 0)
            self._record_rate(metrics, 'sandbox_malicious_rate',
                              round(float(stats.get('malicious_rate', 0.0)), 3),
                              metrics.get('sandbox_total_analyses'))
            metrics['sandbox_known_malware_hashes'] = stats.get('known_malware_hashes', 0)
            metrics['sandbox_recent_analyses'] = stats.get('recent_analyses', 0)

            if (metrics['sandbox_malicious_rate'] is not None
                    and metrics['sandbox_malicious_rate'] > 0.3
                    and metrics['sandbox_total_analyses'] >= 5):
                issues.append(
                    f"High malware detection rate: {metrics['sandbox_malicious_rate']:.0%} "
                    "of analyzed files flagged malicious"
                )

        except Exception as e:
            metrics['malware_sandbox_available'] = False
            issues.append(f"Malware sandbox health check failed: "
                          f"{type(e).__name__}: {e}")
            logger.warning(f"Malware sandbox health check error: {e}")

        return metrics, issues

    async def _generic_health_check(
        self,
        component: str,
        custom_checks: Dict[str, Any] = None
    ) -> tuple[Dict[str, Any], List[str]]:
        """Generic health check for unknown components"""
        metrics = {'component': component, 'check_type': 'generic'}
        issues = []

        if custom_checks:
            metrics.update(custom_checks)

        return metrics, issues

    async def get_system_health(self) -> Dict[str, Any]:
        """
        Get overall system health

        Returns:
            System health summary
        """
        try:
            # Collect system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # Network check
            net_io = psutil.net_io_counters()
            network_active = (net_io.bytes_sent > 0 and net_io.bytes_recv > 0)

            # Process metrics
            process_count = len(psutil.pids())

            # Create system metrics
            system_metrics = SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                disk_percent=disk.percent,
                network_active=network_active,
                process_count=process_count,
                thread_count=sum(p.num_threads() for p in psutil.process_iter(['num_threads']) if p.info['num_threads'])
            )

            # Add to history
            self.health_history.append(system_metrics)
            if len(self.health_history) > self.max_history_size:
                self.health_history = self.health_history[-self.max_history_size:]

            # Determine overall status
            issues = []

            if cpu_percent > self.thresholds['cpu_critical']:
                issues.append(f"CRITICAL: CPU at {cpu_percent}%")
            elif cpu_percent > self.thresholds['cpu_warning']:
                issues.append(f"WARNING: CPU at {cpu_percent}%")

            if memory.percent > self.thresholds['memory_critical']:
                issues.append(f"CRITICAL: Memory at {memory.percent}%")
            elif memory.percent > self.thresholds['memory_warning']:
                issues.append(f"WARNING: Memory at {memory.percent}%")

            if disk.percent > self.thresholds['disk_critical']:
                issues.append(f"CRITICAL: Disk at {disk.percent}%")
            elif disk.percent > self.thresholds['disk_warning']:
                issues.append(f"WARNING: Disk at {disk.percent}%")

            # Overall status
            if any('CRITICAL' in issue for issue in issues):
                overall_status = HealthStatus.CRITICAL
            elif len(issues) >= 2:
                overall_status = HealthStatus.UNHEALTHY
            elif len(issues) == 1:
                overall_status = HealthStatus.DEGRADED
            else:
                overall_status = HealthStatus.HEALTHY

            # Build components dict from registered component_health entries
            # plus synthetic OS-level components
            components: dict = {}

            # Synthetic: CPU
            if cpu_percent > self.thresholds.get('cpu_critical', 95):
                components['cpu'] = {'status': 'critical', 'cpu_percent': cpu_percent, 'issues': [f'CPU at {cpu_percent}%']}
            elif cpu_percent > self.thresholds.get('cpu_warning', 80):
                components['cpu'] = {'status': 'degraded', 'cpu_percent': cpu_percent, 'issues': [f'High CPU: {cpu_percent}%']}

            # Synthetic: RAM
            if memory.percent > self.thresholds.get('memory_critical', 95):
                components['memory'] = {'status': 'critical', 'memory_percent': memory.percent, 'issues': [f'Memory at {memory.percent}%']}
            elif memory.percent > self.thresholds.get('memory_warning', 85):
                components['memory'] = {'status': 'degraded', 'memory_percent': memory.percent, 'issues': [f'High memory: {memory.percent}%']}

            # Synthetic: Disk
            if disk.percent > self.thresholds.get('disk_critical', 95):
                components['disk'] = {'status': 'critical', 'disk_percent': disk.percent, 'issues': [f'Disk at {disk.percent}%']}
            elif disk.percent > self.thresholds.get('disk_warning', 85):
                components['disk'] = {'status': 'degraded', 'disk_percent': disk.percent, 'issues': [f'High disk: {disk.percent}%']}

            # Registered TorinAI service components
            for comp_name, comp_health in self.component_health.items():
                status_val = comp_health.status.value if hasattr(comp_health.status, 'value') else str(comp_health.status)
                components[comp_name] = {
                    'status': status_val,
                    'metrics': comp_health.metrics or {},
                    'issues': comp_health.issues or [],
                    'check_count': comp_health.check_count,
                    'last_check': comp_health.last_check.isoformat() if comp_health.last_check else None,
                }

            return {
                'status': overall_status.value,
                'timestamp': datetime.now().isoformat(),
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'disk_percent': disk.percent,
                'network_active': network_active,
                'process_count': process_count,
                'issues': issues,
                'uptime_seconds': (datetime.now() - self.stats['uptime_start']).total_seconds(),
                'component_count': len(self.component_health),
                'healthy_components': sum(1 for h in self.component_health.values() if h.status == HealthStatus.HEALTHY),
                'statistics': self.stats.copy(),
                'components': components,
            }

        except Exception as e:
            logger.error(f"Failed to get system health: {e}")
            return {
                'status': HealthStatus.UNKNOWN.value,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    async def start_monitoring(self):
        """Start continuous health monitoring"""
        if self.is_monitoring:
            logger.warning("Health monitoring already running")
            return

        self.is_monitoring = True
        logger.info(f"Starting health monitoring: {self.check_interval}s interval")

        self.monitor_task = asyncio.create_task(self._monitoring_loop())

    async def stop_monitoring(self):
        """Stop health monitoring"""
        if not self.is_monitoring:
            return

        self.is_monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("Health monitoring stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop — checks every registered subsystem every cycle"""
        while self.is_monitoring:
            try:
                # Check OS-level system health
                await self.get_system_health()

                # Check ALL known TorinAI subsystems (not just already-registered ones)
                for component in self._monitored_components:
                    try:
                        await self.check_component_health(component)
                    except Exception as _comp_err:
                        logger.debug(
                            f"[HealthMonitor] Error checking {component}: {_comp_err}"
                        )

                # Wait for next check
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(self.check_interval)

    async def get_component_health(self, component: str) -> Optional[ComponentHealth]:
        """Get health data for a component"""
        return self.component_health.get(component)

    async def get_all_component_health(self) -> Dict[str, ComponentHealth]:
        """Get health data for all components"""
        return self.component_health.copy()

    async def get_health_history(
        self,
        minutes: int = 60
    ) -> List[SystemMetrics]:
        """Get system health history"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)

        return [
            metrics for metrics in self.health_history
            if metrics.timestamp >= cutoff_time
        ]

    async def clear_component_health(self, component: str):
        """Clear health data for a component"""
        if component in self.component_health:
            del self.component_health[component]
            logger.info(f"Cleared health data for: {component}")

    async def reset_statistics(self):
        """Reset health statistics"""
        self.stats = {
            'total_checks': 0,
            'healthy_checks': 0,
            'degraded_checks': 0,
            'unhealthy_checks': 0,
            'critical_checks': 0,
            'last_check_time': None,
            'uptime_start': datetime.now()
        }
        logger.info("Health statistics reset")


# Singleton instance
_health_monitor = None


def get_health_monitor() -> HealthMonitor:
    """Get global health monitor instance"""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


# CLI test
async def main():
    """Test health monitor"""
    logging.basicConfig(level=logging.INFO)

    monitor = get_health_monitor()

    print("\n=== Health Monitor Test ===")

    # Check system health
    system_health = await monitor.get_system_health()
    print(f"\nSystem Health: {system_health['status']}")
    print(f"CPU: {system_health['cpu_percent']:.1f}%")
    print(f"Memory: {system_health['memory_percent']:.1f}%")
    print(f"Disk: {system_health['disk_percent']:.1f}%")

    if system_health.get('issues'):
        print(f"\nIssues:")
        for issue in system_health['issues']:
            print(f"  - {issue}")

    # Check component health
    components = ['database', 'memory', 'security', 'storage']

    print(f"\nComponent Health:")
    for component in components:
        health = await monitor.check_component_health(component)
        print(f"  {component}: {health.status.value}")
        if health.issues:
            for issue in health.issues:
                print(f"    - {issue}")


if __name__ == "__main__":
    asyncio.run(main())
