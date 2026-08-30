#!/usr/bin/env python3
"""
Recovery Manager
================
System recovery and failure handling for TorinAI

Purpose:
- Detect and handle system failures
- Execute recovery strategies
- Track failure patterns
- Escalate unrecoverable failures
"""

import asyncio
import logging
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable, Awaitable, Tuple
from datetime import datetime
from enum import Enum
import time

logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Types of system failures"""
    SERVICE_CRASH = "service_crash"
    COMPONENT_FAILURE = "component_failure"  # Generic catch-all used by execute_recovery_action()
    DATABASE_ERROR = "database_error"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    VALIDATION_ERROR = "validation_error"
    SECURITY_VIOLATION = "security_violation"
    DATA_CORRUPTION = "data_corruption"


class RecoveryAction(Enum):
    """Recovery actions"""
    RESTART = "restart"
    ROLLBACK = "rollback"
    BACKUP = "backup"
    CLEANUP = "cleanup"
    ESCALATE = "escalate"
    THROTTLE = "throttle"
    ISOLATE = "isolate"
    ALERT = "alert"
    # Read-only re-check. Verification is NOT a repair: mapping verify_* onto
    # CLEANUP made "confirm the database is intact" perform a mutation, the same
    # action-semantics confusion as treating a file read as a write.
    VERIFY = "verify"


@dataclass
class FailureEvent:
    """System failure event"""
    failure_id: str
    failure_type: FailureType
    component: str
    description: str
    timestamp: datetime = field(default_factory=datetime.now)
    severity: str = "medium"
    recovered: bool = False
    recovery_actions: List[RecoveryAction] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryResult:
    """Result of recovery attempt"""
    success: bool
    actions_taken: List[RecoveryAction]
    message: str
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class RecoveryManager:
    """
    System Recovery Manager

    Purpose:
    - Handle system failures with appropriate recovery strategies
    - Track failure patterns and history
    - Escalate unrecoverable failures
    - Coordinate with health monitoring systems

    Usage:
        manager = RecoveryManager()
        await manager.initialize()

        result = await manager.handle_failure(
            failure_type=FailureType.SERVICE_CRASH,
            component="chat_agent",
            description="Agent process crashed"
        )
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.initialized = False

        # Optional component-level restart handlers.
        # Allows the coordinator (or other owner) to register concrete restart behavior
        # for in-process subsystems that can't be restarted purely from here.
        # Signature: async (metadata: Dict[str, Any]) -> bool
        self._restart_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[bool]]] = {}

        # Runtime controls (in-process) used by THROTTLE / ISOLATE.
        # These are intentionally lightweight and do not depend on DB.
        #
        # Keying scheme:
        # - component keys are normalized (lowercase, stripped)
        # - special keys may be used for cross-cutting control:
        #   - "tool_registry" / "tools" : gate tool execution
        #   - "autonomous_coordinator"  : slow singleton thinking cycle
        self._throttle_state: Dict[str, Dict[str, Any]] = {}
        self._isolation_state: Dict[str, Dict[str, Any]] = {}

        # Tool gating allowlist during isolation. Everything else is blocked.
        self._tool_isolation_allowlist = {
            # Read-only introspection
            "read_file",
            "list_directory",
            "search_files",
            "grep_search",
            "semantic_search",
            "system_info",
            # Notifications
            "notification",
            "notify",
        }

        # Failure tracking
        self.failures: List[FailureEvent] = []
        self.failure_counts: Dict[str, int] = {}

        #: component -> async callable returning JSON-serialisable state, and
        #: component -> async callable applying it back. BACKUP and ROLLBACK
        #: are only real for components that register these; without them the
        #: actions report failure instead of claiming work they cannot do.
        self._snapshot_handlers: Dict[str, Any] = {}
        self._restore_handlers: Dict[str, Any] = {}
        self.last_snapshot_id: Dict[str, str] = {}
        self.recovery_attempts: Dict[str, int] = {}
        self.max_failures = 1000

        # Recovery strategies by failure type
        self.strategies = {
            FailureType.SERVICE_CRASH: [
                RecoveryAction.CLEANUP,
                RecoveryAction.RESTART,
                RecoveryAction.ESCALATE
            ],
            FailureType.DATABASE_ERROR: [
                RecoveryAction.ROLLBACK,
                RecoveryAction.BACKUP,
                RecoveryAction.ESCALATE
            ],
            FailureType.RESOURCE_EXHAUSTION: [
                RecoveryAction.CLEANUP,
                RecoveryAction.THROTTLE,
                RecoveryAction.ESCALATE
            ],
            FailureType.NETWORK_ERROR: [
                RecoveryAction.RESTART,
                RecoveryAction.ESCALATE
            ],
            FailureType.TIMEOUT: [
                RecoveryAction.RESTART,
                RecoveryAction.THROTTLE
            ],
            FailureType.VALIDATION_ERROR: [
                RecoveryAction.CLEANUP,
                RecoveryAction.ALERT
            ],
            FailureType.SECURITY_VIOLATION: [
                RecoveryAction.ISOLATE,
                RecoveryAction.ALERT,
                RecoveryAction.ESCALATE
            ],
            FailureType.DATA_CORRUPTION: [
                RecoveryAction.BACKUP,
                RecoveryAction.ROLLBACK,
                RecoveryAction.ESCALATE
            ]
        }

        # Statistics
        self.statistics = {
            'total_failures': 0,
            'successful_recoveries': 0,
            'failed_recoveries': 0,
            'escalations': 0
        }

        logger.info("RecoveryManager initialized")

    def register_snapshot_handler(self, component: str, capture, restore=None) -> None:
        """Declare how a component's state is captured and put back.

        Without this pair, BACKUP and ROLLBACK have nothing to act on, which
        is why they now refuse rather than report success.
        """
        key = self._norm_key(component)
        self._snapshot_handlers[key] = capture
        if restore is not None:
            self._restore_handlers[key] = restore
        logger.info("Snapshot handler registered for %s (restore=%s)",
                    key, restore is not None)

    def register_restart_handler(
        self,
        component: str,
        handler: Callable[[Dict[str, Any]], Awaitable[bool]]
    ) -> None:
        """Register an async restart handler for a specific component key."""
        if not component:
            return
        self._restart_handlers[component.strip().lower()] = handler

    # ---------------------------------------------------------------------
    # Throttle/Isolation public helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _norm_key(component: str) -> str:
        return (component or "").strip().lower()

    def is_component_isolated(self, component: str) -> bool:
        key = self._norm_key(component)
        state = self._isolation_state.get(key)
        return bool(state and state.get("active"))

    def get_throttle_delay_seconds(self, component: str) -> float:
        """Return fixed delay (seconds) to apply while a throttle is active."""
        key = self._norm_key(component)
        state = self._throttle_state.get(key)
        if not state or not state.get("active"):
            return 0.0
        until = float(state.get("until_ts", 0.0))
        if until and time.time() > until:
            # Expired
            state["active"] = False
            return 0.0
        return float(state.get("delay_s", 0.0))

    def tool_execution_policy(
        self,
        tool_name: str,
        tool_category: Optional[str] = None,
        tool_safety_level: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], float]:
        """Policy check for tool execution.

        Returns:
            (allowed, reason_if_blocked, throttle_delay_seconds)
        """
        name = (tool_name or "").strip().lower()
        category = (tool_category or "").strip().lower()
        safety = (tool_safety_level or "").strip().lower()

        # Global/tool-level isolation gates
        for key in ("tool_registry", "tools", "system"):
            state = self._isolation_state.get(key)
            if state and state.get("active"):
                if name in self._tool_isolation_allowlist:
                    break

                # During isolation, block anything that can mutate state or touch the network.
                if category in {"network", "execution", "filesystem", "database"} or safety in {"dangerous", "moderate"}:
                    reason = state.get("reason") or "Tool execution is isolated by RecoveryManager"
                    return False, reason, 0.0

        # Throttle policy: apply a small fixed delay if configured
        delay = 0.0
        for key in ("tool_registry", "tools", "system"):
            delay = max(delay, self.get_throttle_delay_seconds(key))
        return True, None, delay

    #: Subsystems this manager can actually restart, and the call that does it.
    #:
    #: register_restart_handler() had ZERO callers, so _restart_component fell
    #: through to "No restart implementation for component X" for everything
    #: outside its four built-ins -- recovery could diagnose a dead subsystem
    #: and had no way to act on one. Every entry below was verified to exist on
    #: the live object before being listed; a handler that cannot be called is
    #: worse than none, because it reports a recovery that never happened.
    BUILTIN_RESTART_TARGETS = {
        'watchdog':        ('core.health.system_watchdog', 'get_system_watchdog', 'start'),
        'health_system':   ('core.health.system_watchdog', 'get_system_watchdog', 'start'),
        'backup':          ('core.services.backup_scheduler', 'get_backup_scheduler', 'start_scheduler'),
        'neural_bridge':   ('core.reasoning.neural_bridge', 'get_neural_bridge', 'initialize'),
        'reasoning':       ('core.reasoning.neural_bridge', 'get_neural_bridge', 'initialize'),
        'llm':             ('core.services.unified_llm', 'get_llm_service', 'initialize'),
        'intelligence':    ('core.intelligence.predictive_intelligence_system',
                            'get_predictive_intelligence', 'initialize'),
        # The improvement cycle attempted `agents` on every run for two days and
        # failed here, because nothing in this table could act on it.
        # get_autonomous_coordinator() returns the live instance and only builds
        # one when handed a teacher model, so calling it bare observes rather than
        # creates; start_coordination() is a no-op when the cycle is already
        # running, which makes the handler safe to call speculatively.
        'agents':          ('core.agents.autonomous.autonomous_coordinator',
                            'get_autonomous_coordinator', 'start_coordination'),
    }

    #: DELIBERATELY ABSENT, so nobody adds a handler that reports a recovery it
    #: cannot perform:
    #:
    #:   security  -- SecurityController exposes no initialize()/start(); its
    #:                low score is measurement coverage, not a stopped process.
    #:   learning  -- degraded by a low ASI success rate over real cycles. That
    #:                is a result, not a liveness fault, and restarting nothing
    #:                would change it. _remediate_targets already classifies it
    #:                `not_applicable` because its issues carry no liveness
    #:                marker, which is the correct verdict.
    #:
    #: A restart path is only listed once the accessor and the method have been
    #: confirmed to exist on the live object.

    def _register_builtin_restart_handlers(self) -> int:
        """Register the verified restart paths so recovery can act, not just report."""
        import importlib

        registered = 0
        for component, (module, accessor, method) in self.BUILTIN_RESTART_TARGETS.items():
            def _make(mod=module, acc=accessor, meth=method, comp=component):
                async def _restart(_params: Dict[str, Any]) -> bool:
                    obj = getattr(importlib.import_module(mod), acc)()
                    if asyncio.iscoroutine(obj):
                        obj = await obj
                    fn = getattr(obj, meth, None)
                    if fn is None:
                        raise AttributeError(
                            f"{mod}.{acc}() exposes no {meth}(); the declared "
                            f"restart path for {comp!r} no longer exists")
                    result = fn()
                    if asyncio.iscoroutine(result):
                        result = await result
                    # A start method returning None means "did not raise", which
                    # for these APIs is success; only an explicit False is failure.
                    return result is not False
                return _restart
            self.register_restart_handler(component, _make())
            registered += 1
        logger.info("Registered %d built-in restart handler(s)", registered)
        return registered

    async def initialize(self) -> bool:
        """Initialize recovery manager"""
        try:
            logger.info("Initializing Recovery Manager")
            self._register_builtin_restart_handlers()

            from core.database import get_database_manager
            self.db_manager = get_database_manager()

            # Create system_failures table and indexes if they don't exist (PostgreSQL)
            await self.db_manager.execute_query("""
                CREATE TABLE IF NOT EXISTS system_failures (
                    failure_id TEXT PRIMARY KEY,
                    component TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    recovered BOOLEAN DEFAULT FALSE,
                    recovery_action TEXT,
                    recovery_timestamp TIMESTAMPTZ,
                    error_message TEXT
                )
            """, commit=True)

            # Create supporting indexes
            await self.db_manager.execute_query(
                "CREATE INDEX IF NOT EXISTS idx_system_failures_component ON system_failures(component)",
                commit=True,
            )
            await self.db_manager.execute_query(
                "CREATE INDEX IF NOT EXISTS idx_system_failures_timestamp ON system_failures(timestamp)",
                commit=True,
            )
            await self.db_manager.execute_query(
                "CREATE INDEX IF NOT EXISTS idx_system_failures_recovered ON system_failures(recovered)",
                commit=True,
            )

            # Load recent failures
            await self.db_manager.query("""
                SELECT failure_id, component, failure_type, severity, timestamp, recovered
                FROM system_failures
                ORDER BY timestamp DESC
                LIMIT 1000
            """)

            self.initialized = True
            logger.info("✓ Recovery Manager ready")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize recovery manager: {e}")
            return False

    async def _verify_component(self, component: str) -> bool:
        """Re-check a component's health. Read-only, never repairs.

        True  = component is healthy now
        False = still unhealthy, OR health could not be determined
        The caller must not read False as "the repair failed" — it means the
        post-condition is not established, which is the honest answer either way.
        """
        try:
            from core.health.health_monitor import get_health_monitor
            monitor = get_health_monitor()
            if monitor is None:
                logger.warning("VERIFY %s: no health monitor available", component)
                return False
            status = await monitor.check_component_health(component)
            state = getattr(status, "status", status)
            state = str(getattr(state, "value", state)).lower()
            healthy = state == "healthy"
            logger.info("🔎 VERIFY %s -> %s", component, state)
            return healthy
        except Exception as e:
            logger.warning("VERIFY %s failed to determine health: %s", component, e)
            return False

    async def execute_recovery_action(
        self,
        component: str,
        action: str,
        parameters: Dict[str, Any] = None
    ) -> bool:
        """
        Execute a specific recovery action (IRecoveryManager interface implementation)

        This method provides a direct interface for executing recovery actions,
        used by autonomous_coordinator's AI self-healing system.

        Args:
            component: Component to recover
            action: Action name (reconnect_database, restart_component, clear_cache, etc.)
            parameters: Additional parameters for the action

        Returns:
            True if action succeeded, False otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            params = parameters or {}
            logger.info(f"🔧 Executing recovery action '{action}' on {component}")

            # Map action names to recovery action enums
            action_map = {
                'reconnect_database': RecoveryAction.RESTART,
                'restart_component': RecoveryAction.RESTART,
                'clear_cache': RecoveryAction.CLEANUP,
                'clear_component_cache': RecoveryAction.CLEANUP,
                'reset_state': RecoveryAction.ROLLBACK,
                'reset_component_state': RecoveryAction.ROLLBACK,
                'rollback': RecoveryAction.ROLLBACK,
                'restart': RecoveryAction.RESTART,
                'cleanup': RecoveryAction.CLEANUP,
                'throttle': RecoveryAction.THROTTLE,
                'isolate': RecoveryAction.ISOLATE,
                'backup': RecoveryAction.BACKUP,
                # Playbook-defined aliases
                'backup_before_repair': RecoveryAction.BACKUP,
                # Verification is read-only — never CLEANUP, which mutates.
                'verify_db_integrity': RecoveryAction.VERIFY,
                'verify_after_restart': RecoveryAction.VERIFY,
                'verify_api_connectivity': RecoveryAction.VERIFY,
                'verify_network': RecoveryAction.VERIFY,
                'verify_dns_resolution': RecoveryAction.VERIFY,
                'verify_reasoning_output': RecoveryAction.VERIFY,
                'track_storage_health': RecoveryAction.VERIFY,
                # Alerts notify; they do not clean up.
                'alert_db_recovery': RecoveryAction.ALERT,
                'alert_quantum_degraded': RecoveryAction.ALERT,
                'alert_network_issue': RecoveryAction.ALERT,
                # Restarts
                'restart_api_connections': RecoveryAction.RESTART,
                'gc_collect': RecoveryAction.CLEANUP,
                'reduce_cache_size': RecoveryAction.CLEANUP,
                'track_memory_trend': RecoveryAction.CLEANUP,
            }

            recovery_action = action_map.get(action.lower())
            if not recovery_action:
                logger.warning(f"Unknown recovery action: {action}")
                return False

            # Execute the recovery action directly
            success = await self._execute_recovery_action(
                recovery_action,
                component,
                FailureType.COMPONENT_FAILURE,  # Generic failure type
                params
            )

            if success:
                logger.info(f"✅ Recovery action '{action}' succeeded for {component}")
                self.statistics['successful_recoveries'] += 1
            else:
                logger.error(f"❌ Recovery action '{action}' failed for {component}")
                self.statistics['failed_recoveries'] += 1

            return success

        except Exception as e:
            logger.error(f"Error executing recovery action: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def handle_failure(
        self,
        failure_type: FailureType,
        component: str,
        description: str,
        severity: str = "medium",
        metadata: Dict[str, Any] = None
    ) -> RecoveryResult:
        """
        Handle system failure and execute recovery

        Args:
            failure_type: Type of failure
            component: Component that failed
            description: Failure description
            severity: Severity level (low, medium, high, critical)
            metadata: Additional failure metadata

        Returns:
            RecoveryResult with success status and actions taken
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            logger.warning(f"Handling failure: {failure_type.value} in {component}")

            # Create failure event
            failure_id = f"{component}_{failure_type.value}_{datetime.now().timestamp()}"
            failure_event = FailureEvent(
                failure_id=failure_id,
                failure_type=failure_type,
                component=component,
                description=description,
                severity=severity,
                metadata=metadata or {}
            )

            # Track failure
            self.failures.append(failure_event)
            if len(self.failures) > self.max_failures:
                self.failures = self.failures[-self.max_failures:]

            self.failure_counts[component] = self.failure_counts.get(component, 0) + 1
            self.statistics['total_failures'] += 1

            # Get recovery strategy
            strategy = self.strategies.get(failure_type, [RecoveryAction.ESCALATE])

            # Check if component has failed too many times
            if self.failure_counts.get(component, 0) > 5:
                logger.error(f"Component {component} has failed {self.failure_counts[component]} times")
                strategy = [RecoveryAction.ISOLATE, RecoveryAction.ESCALATE]

            # Execute recovery actions
            actions_taken = []
            recovery_success = False

            for action in strategy:
                try:
                    success = await self._execute_recovery_action(
                        action, component, failure_type, metadata or {}
                    )
                    actions_taken.append(action)

                    if action == RecoveryAction.RESTART and success:
                        recovery_success = True
                        break
                    elif action == RecoveryAction.ROLLBACK and success:
                        recovery_success = True
                        break
                    elif action == RecoveryAction.CLEANUP and success:
                        recovery_success = True
                        break

                except Exception as e:
                    logger.error(f"Recovery action {action.value} failed: {e}")

            # Update statistics
            if recovery_success:
                self.statistics['successful_recoveries'] += 1
                failure_event.recovered = True

                try:
                    from core.utils.notification_publisher import send_system_notification
                    actions_text = "\n".join([f"• {action}" for action in actions_taken])
                    await send_system_notification(
                        title=f"✅ Component Recovered: {component}",
                        message=f"**Component:** {component}\n**Status:** RECOVERED\n**Actions Taken:**\n{actions_text}\n**Total Successful Recoveries:** {self.statistics['successful_recoveries']}",
                        severity="info",
                        metadata={"component": component, "actions": actions_taken, "successful_count": self.statistics['successful_recoveries']}
                    )
                except:
                    pass
            else:
                self.statistics['failed_recoveries'] += 1

                try:
                    from core.utils.notification_publisher import send_system_notification
                    await send_system_notification(
                        title=f"❌ Component Recovery Failed: {component}",
                        message=f"**Component:** {component}\n**Status:** RECOVERY FAILED\n**Attempted Actions:** {len(actions_taken)}\n**Total Failed Recoveries:** {self.statistics['failed_recoveries']}",
                        severity="error",
                        metadata={"component": component, "failed_count": self.statistics['failed_recoveries']}
                    )
                except:
                    pass

            failure_event.recovery_actions = actions_taken

            # Persist failure event
            await self._persist_failure(failure_event)

            result = RecoveryResult(
                success=recovery_success,
                actions_taken=actions_taken,
                message=f"Recovery {'succeeded' if recovery_success else 'failed'} for {component}",
                retry_count=self.recovery_attempts.get(component, 0)
            )

            logger.info(f"Recovery result: {result.message}")
            return result

        except Exception as e:
            logger.error(f"Failed to handle failure: {e}")
            return RecoveryResult(
                success=False,
                actions_taken=[],
                message=f"Recovery handler error: {str(e)}"
            )

    async def _execute_recovery_action(
        self,
        action: RecoveryAction,
        component: str,
        failure_type: FailureType,
        metadata: Dict[str, Any]
    ) -> bool:
        """Execute a specific recovery action"""
        logger.info(f"Executing recovery action: {action.value} for {component}")

        try:
            if action == RecoveryAction.RESTART:
                # Restart the component
                return await self._restart_component(component, metadata)

            elif action == RecoveryAction.ROLLBACK:
                # Rollback to previous state
                return await self._rollback_component(component, metadata)

            elif action == RecoveryAction.BACKUP:
                # Create backup before recovery
                return await self._backup_component(component)

            elif action == RecoveryAction.CLEANUP:
                # Clean up resources
                return await self._cleanup_component(component)

            elif action == RecoveryAction.ESCALATE:
                # Escalate to higher level (human intervention)
                await self._escalate_failure(component, failure_type, metadata)
                self.statistics['escalations'] += 1
                return True

            elif action == RecoveryAction.THROTTLE:
                # Throttle component activity
                return await self._throttle_component(component, metadata)

            elif action == RecoveryAction.ISOLATE:
                # Isolate component from system
                return await self._isolate_component(component)

            elif action == RecoveryAction.ALERT:
                # Send alert to monitoring systems
                await self._send_alert(component, failure_type, metadata)
                return True

            elif action == RecoveryAction.VERIFY:
                # Read-only: re-check the component against the health monitor.
                # Returns the ACTUAL health, so a verification that finds the
                # component still unhealthy correctly reports failure rather
                # than reporting success for having looked.
                return await self._verify_component(component)

            else:
                logger.warning(f"Unknown recovery action: {action}")
                return False

        except Exception as e:
            logger.error(f"Recovery action {action.value} failed: {e}")
            return False

    async def _restart_component(self, component: str, metadata: Dict[str, Any]) -> bool:
        """Restart a failed component (in-process).

        This is intentionally conservative: it only restarts known subsystems or
        those with explicit registered handlers.
        """
        component_key = (component or "").strip().lower()
        logger.info(f"Restarting component: {component_key or component}")

        params = metadata or {}

        # 1) Registered handlers (preferred)
        handler = self._restart_handlers.get(component_key)
        if handler:
            try:
                return bool(await handler(params))
            except Exception as e:
                logger.error(f"Restart handler failed for {component_key}: {e}")
                return False

        # 2) Built-in restart targets
        try:
            if component_key in {"monitoring", "monitoring_coordinator", "monitor"}:
                from core.health.monitoring_coordinator import get_monitoring_coordinator

                coordinator = get_monitoring_coordinator()
                try:
                    if hasattr(coordinator, "stop_monitoring"):
                        await coordinator.stop_monitoring()
                except Exception:
                    pass

                ok_init = await coordinator.initialize()
                if not ok_init:
                    return False
                await coordinator.start_monitoring()
                return True

            if component_key in {"health", "health_monitor"}:
                from core.health.health_monitor import get_health_monitor

                monitor = get_health_monitor()
                try:
                    if hasattr(monitor, "stop_monitoring"):
                        await monitor.stop_monitoring()
                except Exception:
                    pass

                await monitor.start_monitoring()
                return True

            if component_key in {"security", "security_controller", "security_system"}:
                from core.security.controller import get_security_controller

                # If reset helper exists, use it. Otherwise attempt a light-touch restart.
                try:
                    from core.security.controller import reset_security_controller
                    await reset_security_controller()
                except Exception:
                    pass

                controller = get_security_controller()
                coordinator = params.get("coordinator") or params.get("autonomous_coordinator")
                if coordinator is not None and hasattr(controller, "set_autonomous_coordinator"):
                    controller.set_autonomous_coordinator(coordinator)
                return True

            if component_key in {"db", "database", "postgres", "postgresql"}:
                from core.database import get_database_manager

                db = get_database_manager()
                try:
                    if hasattr(db, "close"):
                        await db.close()
                except Exception:
                    pass

                if hasattr(db, "initialize"):
                    return bool(await db.initialize())
                return False

            logger.warning(
                f"No restart implementation for component '{component_key}'. "
                f"Register a handler via register_restart_handler()."
            )
            return False

        except Exception as e:
            logger.error(f"Component restart failed for {component_key}: {e}")
            return False

    async def _rollback_component(self, component: str, metadata: Dict[str, Any]) -> bool:
        """Restore a component from a snapshot, or refuse.

        THIS CLAIMED A RESTORE IT NEVER PERFORMED. When a snapshot row was
        found it logged "Restored {component} to snapshot {id}" and returned
        True -- while `state_data`, the row it had just fetched, was never
        read and nothing was applied. A recovery action that reports success
        for doing nothing is the most dangerous shape in this file, because
        `handle_failure` breaks its strategy loop on a ROLLBACK success and
        stops trying anything else.

        It also queried `component_snapshots`, which does not exist in any
        schema and which nothing in the codebase writes.

        Restoring in-process component state is a capability the system does
        not have. Saying so is the honest answer; the strategy loop then
        continues to the next action instead of stopping on a fiction.
        """
        logger.info("Rollback requested for component: %s", component)

        snapshot_id = metadata.get("snapshot_id")
        if not snapshot_id:
            logger.warning("No snapshot id supplied for %s; cannot roll back", component)
            return False

        try:
            from core.database import get_database_manager

            db = get_database_manager()
            rows = await db.execute_query(
                "SELECT state_data FROM unified.component_snapshots "
                "WHERE component = $1 AND snapshot_id = $2",
                (component, snapshot_id), fetch_all=True)
        except Exception as e:
            logger.error("Snapshot lookup failed for %s: %s", component, e)
            return False

        if not rows:
            logger.warning("No snapshot %s for %s; cannot roll back", snapshot_id, component)
            return False

        # A snapshot exists. Applying it needs a registered restorer for this
        # component -- a generic "restore arbitrary state" does not exist and
        # pretending otherwise is what this function used to do.
        restorer = self._restore_handlers.get(self._norm_key(component))
        if restorer is None:
            logger.error(
                "Snapshot %s exists for %s but no restore handler is registered, "
                "so the state cannot be applied. Reporting failure rather than a "
                "restore that did not happen.", snapshot_id, component)
            return False

        try:
            applied = await restorer(rows[0]["state_data"])
        except Exception as e:
            logger.error("Restore handler for %s raised: %s", component, e)
            return False

        if applied:
            logger.info("Restored %s to snapshot %s", component, snapshot_id)
            return True
        logger.error("Restore handler for %s declined to apply snapshot %s",
                     component, snapshot_id)
        return False

    async def _backup_component(self, component: str) -> bool:
        """Capture a component's restorable state as a snapshot.

        THIS BACKED UP NOTHING. It called `os.makedirs("runtime/backups")` and
        returned True -- so every BACKUP action reported success for creating
        an empty directory, and the snapshot `_rollback_component` looks for
        was never written by anything.

        What can honestly be captured is the component's persisted health
        record and whatever a registered snapshotter supplies. Without a
        snapshotter there is no component state to save, and that is reported
        rather than dressed up as a backup.
        """
        component_key = self._norm_key(component)
        snapshotter = self._snapshot_handlers.get(component_key)
        if snapshotter is None:
            logger.warning(
                "No snapshot handler registered for %s; there is no component "
                "state to capture, so no backup was taken", component)
            return False

        try:
            state = await snapshotter()
        except Exception as e:
            logger.error("Snapshot handler for %s raised: %s", component, e)
            return False

        if state is None:
            logger.warning("Snapshot handler for %s produced no state", component)
            return False

        snapshot_id = f"snap_{component_key}_{int(time.time())}"
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            await db.execute_query(
                """CREATE TABLE IF NOT EXISTS unified.component_snapshots (
                       snapshot_id  varchar(128) PRIMARY KEY,
                       component    varchar(128) NOT NULL,
                       state_data   jsonb        NOT NULL,
                       created_at   timestamptz  NOT NULL DEFAULT NOW())""",
                commit=True)
            await db.execute_query(
                "INSERT INTO unified.component_snapshots "
                "(snapshot_id, component, state_data) VALUES ($1, $2, $3::jsonb)",
                (snapshot_id, component_key, json.dumps(state, default=str)),
                commit=True)
        except Exception as e:
            logger.error("Could not persist snapshot for %s: %s", component, e)
            return False

        self.last_snapshot_id[component_key] = snapshot_id
        logger.info("Backed up %s as %s", component, snapshot_id)
        return True

    async def _cleanup_component(self, component: str) -> bool:
        """Release process-wide memory. NOT a recovery of the component.

        THIS SHORT-CIRCUITED THE ACTUAL REMEDY. It ran `gc.collect()` and
        returned True -- and `gc.collect()` cannot fail -- while
        `handle_failure` BREAKS its strategy loop on a CLEANUP success. Three
        of the eight failure types begin with CLEANUP:

            SERVICE_CRASH        [CLEANUP, RESTART, ESCALATE]
            RESOURCE_EXHAUSTION  [CLEANUP, THROTTLE, ESCALATE]
            VALIDATION_ERROR     [CLEANUP, ALERT]

        So a crashed service was "recovered" by a garbage collection, the
        RESTART never ran, the escalation never fired, and the event was
        recorded as a successful recovery with an alert reading "Status:
        RECOVERED".

        Garbage collection is process-wide and knows nothing about a
        component. It is worth doing before a restart, and it is not evidence
        that anything was fixed -- so it reports False and the strategy
        continues to the action that might actually help.
        """
        try:
            import gc

            collected = gc.collect()
            logger.info(
                "Ran garbage collection before recovering %s (%d object(s) freed). "
                "This is not a recovery; continuing to the next action.",
                component, collected)
        except Exception as e:
            logger.error("Garbage collection failed: %s", e)
        return False

    async def _throttle_component(self, component: str, metadata: Dict[str, Any]) -> bool:
        """Throttle component activity.

        This is an in-process protective measure intended for RESOURCE_EXHAUSTION
        and TIMEOUT scenarios. It does two things when possible:

        1) Records a throttle window so other subsystems can consult it.
        2) If an AutonomousCoordinator instance is provided, increases its
           singleton thinking interval during the window.
        """
        component_key = self._norm_key(component)
        params = metadata or {}
        duration_s = int(params.get("duration_s") or params.get("throttle_duration_s") or 300)
        delay_s = float(params.get("delay_s") or params.get("throttle_delay_s") or 0.25)
        thinking_interval_idle_cycles = params.get("thinking_interval_idle_cycles")

        until_ts = time.time() + max(1, duration_s)
        self._throttle_state[component_key] = {
            "active": True,
            "until_ts": until_ts,
            "delay_s": max(0.0, delay_s),
            "set_at": time.time(),
            "reason": params.get("reason") or f"throttle due to {params.get('failure_type') or 'recovery strategy'}",
        }

        coordinator = params.get("coordinator") or params.get("autonomous_coordinator")
        if coordinator is not None and thinking_interval_idle_cycles is not None:
            try:
                apply = getattr(coordinator, "apply_throttle", None)
                if callable(apply):
                    apply(
                        thinking_interval_idle_cycles=int(thinking_interval_idle_cycles),
                        duration_s=duration_s,
                        reason=self._throttle_state[component_key]["reason"],
                    )
            except Exception as e:
                logger.debug(f"Coordinator throttle hook failed: {e}")

        logger.warning(
            f"Throttling '{component_key}' for {duration_s}s "
            f"(delay_s={delay_s}, until={datetime.fromtimestamp(until_ts).isoformat()})"
        )
        return True

    async def _isolate_component(self, component: str) -> bool:
        """Isolate component from system.

        Isolation is used for SECURITY_VIOLATION scenarios. It records an
        isolation flag that enforcement points can consult (e.g., tool registry).

        Note: Isolation here is logical (policy gating), not OS-level sandboxing.
        """
        component_key = self._norm_key(component)
        state = {
            "active": True,
            "set_at": time.time(),
            "reason": f"isolated by RecoveryManager: {component_key}",
        }

        self._isolation_state[component_key] = state

        # SECURITY_VIOLATION isolation should be protective at the system boundary.
        # If a specific component is isolated, also raise a conservative global
        # isolation gate that blocks risky tools until humans intervene.
        if component_key not in {"tool_registry", "tools", "system"}:
            self._isolation_state["system"] = {
                "active": True,
                "set_at": state["set_at"],
                "reason": f"system isolation due to component isolation: {component_key}",
            }

        logger.critical(
            f"Component '{component_key}' isolated from system (logical policy gating). "
            f"Manual intervention may be required."
        )
        return True

    async def _escalate_failure(
        self,
        component: str,
        failure_type: FailureType,
        metadata: Dict[str, Any]
    ):
        """Escalate failure to higher level with Slack notification"""
        logger.error(f"Escalating failure for component: {component}")
        await self._send_alert(component, failure_type, metadata)

    async def _send_alert(
        self,
        component: str,
        failure_type: FailureType,
        metadata: Dict[str, Any]
    ):
        """Send alert to Slack monitoring"""
        logger.warning(f"Alert: {failure_type.value} in {component}")

        try:
            from core.integration.slack_notifier import get_slack_notifier
            slack = get_slack_notifier()
            await slack.send_message(
                f"🚨 System Alert: {failure_type.value} in {component}\nMetadata: {metadata}",
                channel="ALERTS"
            )
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")

    async def _persist_failure(self, failure: FailureEvent):
        """Persist failure event to database"""
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            await db.execute_query(
                """
                INSERT INTO system_failures
                (failure_id, component, failure_type, severity, timestamp, description, recovered, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                params=(
                    failure.failure_id,
                    failure.component,
                    failure.failure_type.value,
                    failure.severity,
                    failure.timestamp,
                    failure.description,
                    failure.recovered,
                    # metadata is a JSON column — str() produces a Python repr
                    # with single quotes, which Postgres rejects
                    json.dumps(failure.metadata or {}, default=str),
                ),
                commit=True,
            )
        except Exception as e:
            logger.error(f"Failed to persist failure event: {e}")

        # ALSO to the canonical record. `system_failures` is this manager's own
        # table and only this manager reads it; the coordinator, the health
        # system, intrinsic motivation and the improvement cycle all need to
        # know a component failed, and none of them look here.
        try:
            from core.observability import failure_record

            await failure_record.report(
                component=failure.component,
                failure_type=failure.failure_type.value,
                description=failure.description,
                source_system="recovery_manager",
                severity=str(failure.severity or "medium").lower(),
                metadata=failure.metadata or {},
                recovered=bool(failure.recovered),
            )
        except Exception as e:
            logger.error("Canonical failure record not written: %s", e)

    async def get_failure_history(
        self,
        component: Optional[str] = None,
        limit: int = 100,
        within_minutes: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Failures for a component, from the CANONICAL record.

        This read `self.failure_history`, an in-process list, and
        `unified.system_failures`, which only this manager writes.
        `autonomous_coordinator` calls it to decide
        `is_recurring = failure_count >= 3` -- against a table holding one row,
        ever. So recurring-failure detection could not fire no matter how often
        a component failed, because the failures were recorded by the subsystem
        that hit them, somewhere else.
        """
        from core.observability import failure_record

        records = await failure_record.recent(
            component=component, within_minutes=within_minutes, limit=limit)
        return [r.as_dict() for r in records]

    async def get_statistics(self) -> Dict[str, Any]:
        """Get recovery statistics"""
        stats = self.statistics.copy()
        stats['active_failures'] = len([f for f in self.failures if not f.recovered])
        stats['failure_rate'] = len(self.failures) / max(1, self.statistics['total_failures'])
        return stats

    async def clear_failure_history(self, component: Optional[str] = None):
        """Clear failure history"""
        if component:
            self.failures = [f for f in self.failures if f.component != component]
            if component in self.failure_counts:
                del self.failure_counts[component]
        else:
            self.failures.clear()
            self.failure_counts.clear()
            self.recovery_attempts.clear()

        logger.info(f"Cleared failure history{' for ' + component if component else ''}")


# Singleton instance
_recovery_manager = None


def get_recovery_manager() -> RecoveryManager:
    """Get global recovery manager instance"""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = RecoveryManager()
    return _recovery_manager


# CLI test
async def main():
    """Test recovery manager"""
    logging.basicConfig(level=logging.INFO)

    manager = get_recovery_manager()
    await manager.initialize()

    # Test failure handling
    result = await manager.handle_failure(
        failure_type=FailureType.SERVICE_CRASH,
        component="test_service",
        description="Test service crashed during operation",
        severity="high"
    )

    print("\n=== Recovery Manager Test ===")
    print(f"Recovery Success: {result.success}")
    print(f"Actions Taken: {[a.value for a in result.actions_taken]}")
    print(f"Message: {result.message}")

    # Get statistics
    stats = await manager.get_statistics()
    print(f"\nStatistics: {stats}")

    # Get failure history
    history = await manager.get_failure_history(limit=10)
    print(f"\nRecent Failures: {len(history)}")


if __name__ == "__main__":
    asyncio.run(main())
