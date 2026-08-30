#!/usr/bin/env python3
"""
System Watchdog
===============
Automated system monitoring and recovery

Purpose:
- Continuous health monitoring
- Automatic issue detection
- Automated recovery actions
- Alert generation
"""

import asyncio
import logging
import psutil
import time
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from core.health.health_monitor import get_health_monitor, HealthStatus

logger = logging.getLogger(__name__)


class RecoveryAction(Enum):
    """Recovery action types"""
    RESTART_COMPONENT = "restart_component"
    CLEAR_CACHE = "clear_cache"
    GARBAGE_COLLECT = "garbage_collect"
    REDUCE_LOAD = "reduce_load"
    ALERT_ADMIN = "alert_admin"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"


@dataclass
class WatchdogConfig:
    """Watchdog configuration"""
    check_interval: int = 30  # seconds
    auto_recovery: bool = True
    max_recovery_attempts: int = 3
    recovery_cooldown: int = 300  # seconds
    alert_on_recovery: bool = True
    # Thresholds
    cpu_critical_threshold: float = 95.0
    memory_critical_threshold: float = 95.0
    disk_critical_threshold: float = 98.0
    component_failure_threshold: int = 3


@dataclass
class ResourceLimits:
    """Resource limits used for monitoring and (optionally) governance tests."""

    max_cpu_percent: float = 90.0
    max_memory_gb: float = 8.0
    max_operation_time: int = 60
    check_interval: float = 30.0

    # Reserved margins used by some validators/tests
    reserved_memory_gb: float = 0.0


@dataclass
class RecoveryAttempt:
    """Recovery attempt record"""
    timestamp: datetime
    component: str
    action: RecoveryAction
    success: bool
    error: Optional[str] = None
    duration: float = 0.0


class SystemWatchdog:
    """
    System Watchdog

    Purpose:
    - Monitor system health continuously
    - Detect critical issues automatically
    - Execute recovery actions
    - Generate alerts for administrators

    Usage:
        watchdog = SystemWatchdog()
        await watchdog.start()
    """

    def __init__(
        self,
        config: Optional[Union[WatchdogConfig, ResourceLimits]] = None,
        limits: Optional[ResourceLimits] = None,
    ):
        # Callers historically passed a ResourceLimits positionally (see
        # autonomous_coordinator). The two dataclasses share only check_interval,
        # so storing one as the other silently breaks every later config access.
        # Route it to the field it actually belongs to instead.
        if isinstance(config, ResourceLimits):
            limits = limits or config
            config = None

        self.config = config or WatchdogConfig()
        self.health_monitor = get_health_monitor()
        self.is_running = False
        self.watchdog_task = None

        # Resource limits: caller-supplied, else derived from this machine.
        if limits is not None:
            self.limits = limits
            # Honour the caller's cadence when they specified one
            self.config.check_interval = int(limits.check_interval)
        else:
            try:
                total_mem_gb = psutil.virtual_memory().total / (1024**3)
                default_mem_gb = max(1.0, total_mem_gb - 2.0)
            except Exception:
                default_mem_gb = 8.0

            self.limits = ResourceLimits(
                max_cpu_percent=90.0,
                max_memory_gb=default_mem_gb,
                max_operation_time=60,
                check_interval=float(self.config.check_interval),
            )

        # Critical infrastructure tracking (systems that MUST stay alive)
        self.critical_infrastructure = {
            'health_monitor': None,
            'monitoring_coordinator': None,
            'security_system': None
        }

        # Autonomous Coordinator reference (for AI self-healing alerts)
        self.autonomous_coordinator = None

        # Recovery tracking
        self.recovery_history: List[RecoveryAttempt] = []
        self.recovery_attempts: Dict[str, List[datetime]] = {}
        self.last_recovery: Dict[str, datetime] = {}

        # Recovery handlers
        self.recovery_handlers: Dict[RecoveryAction, Callable] = {
            RecoveryAction.RESTART_COMPONENT: self._restart_component,
            RecoveryAction.CLEAR_CACHE: self._clear_cache,
            RecoveryAction.GARBAGE_COLLECT: self._garbage_collect,
            RecoveryAction.REDUCE_LOAD: self._reduce_load,
            RecoveryAction.ALERT_ADMIN: self._alert_admin
        }

        # Statistics
        self.stats = {
            'total_checks': 0,
            'issues_detected': 0,
            'recoveries_attempted': 0,
            'recoveries_successful': 0,
            'recoveries_failed': 0,
            'alerts_sent': 0,
            'infrastructure_restarts': 0,
            'shadow_mode_active': False,
            'uptime_start': datetime.now()
        }

        logger.info(f"🛡️  SystemWatchdog initialized: {self.config.check_interval}s interval")

    async def start(self):
        """Start watchdog monitoring"""
        if self.is_running:
            logger.warning("Watchdog already running")
            return

        self.is_running = True
        logger.info("Starting system watchdog")

        # Start health monitor if not running
        if not self.health_monitor.is_monitoring:
            await self.health_monitor.start_monitoring()

        # Start watchdog loop
        self.watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self):
        """Stop watchdog monitoring"""
        if not self.is_running:
            return

        self.is_running = False

        # FLUSH BEFORE THE COUNTERS GO. This is the last moment they exist;
        # after the process ends there is no way to recover what this run saw.
        await self.persist_statistics()

        if self.watchdog_task:
            self.watchdog_task.cancel()
            try:
                await self.watchdog_task
            except asyncio.CancelledError:
                pass

        logger.info("System watchdog stopped")

    async def _watchdog_loop(self):
        """Main watchdog monitoring loop - THE ULTIMATE GUARDIAN"""
        logger.info("🛡️  Watchdog loop started - Guarding critical infrastructure")

        while self.is_running:
            try:
                # FIRST PRIORITY: Ensure critical infrastructure is alive
                await self._ensure_critical_infrastructure_alive()

                # Check shadow mode status
                await self._check_shadow_mode_status()

                # Perform health check
                await self._perform_health_check()

                # Check for critical system resources
                await self._check_critical_resources()

                # Check component health
                await self._check_component_health()

                # Wait for next check
                await asyncio.sleep(self.config.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🛡️  Watchdog loop error (CRITICAL - watchdog itself failing): {e}")
                # Even if watchdog has issues, keep trying
                await asyncio.sleep(self.config.check_interval)

    async def _perform_health_check(self):
        """Perform system health check"""
        try:
            self.stats['total_checks'] += 1

            # Get system health
            system_health = await self.health_monitor.get_system_health()

            # Check for critical issues
            if system_health.get('status') == HealthStatus.CRITICAL.value:
                logger.warning(f"CRITICAL system health detected: {system_health.get('issues')}")
                await self._handle_critical_health(system_health)

            # Check for unhealthy status
            elif system_health.get('status') == HealthStatus.UNHEALTHY.value:
                logger.warning(f"Unhealthy system status: {system_health.get('issues')}")
                self.stats['issues_detected'] += 1

        except Exception as e:
            logger.error(f"Health check failed: {e}")

    async def _check_critical_resources(self):
        """Check critical system resources"""
        try:
            # CPU check
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.config.cpu_critical_threshold:
                logger.critical(f"Critical CPU usage: {cpu_percent}% (threshold: {self.config.cpu_critical_threshold}%)")
                await self._handle_high_cpu(cpu_percent)

            # Memory check
            memory = psutil.virtual_memory()
            memory_gb = memory.used / (1024**3)
            if memory.percent > self.config.memory_critical_threshold:
                logger.critical(f"Critical memory usage: {memory_gb:.2f}GB ({memory.percent}%)")
                await self._handle_high_memory(memory.percent)

            # Disk check
            disk = psutil.disk_usage('/')
            if disk.percent > self.config.disk_critical_threshold:
                logger.critical(f"Critical disk usage: {disk.percent}%")
                await self._handle_high_disk(disk.percent)

        except Exception as e:
            logger.error(f"Resource check failed: {e}")

    async def _check_component_health(self):
        """Check health of all components"""
        try:
            all_health = await self.health_monitor.get_all_component_health()

            critical_components = []
            for component, health in all_health.items():
                if health.status == HealthStatus.CRITICAL:
                    critical_components.append((component, health))

            # Handle critical components
            for component, health in critical_components:
                logger.critical(f"Critical component: {component} ({health.issues})")
                await self._handle_component_failure(component, health)

        except Exception as e:
            logger.error(f"Component health check failed: {e}")

    async def _handle_critical_health(self, system_health: Dict[str, Any]):
        """Handle critical system health"""
        try:
            issues = system_health.get('issues', [])

            for issue in issues:
                if 'CPU' in issue:
                    cpu_percent = system_health.get('cpu_percent', 0)
                    await self._handle_high_cpu(cpu_percent)
                elif 'Memory' in issue or 'memory' in issue:
                    memory_percent = system_health.get('memory_percent', 0)
                    await self._handle_high_memory(memory_percent)
                elif 'Disk' in issue or 'disk' in issue:
                    disk_percent = system_health.get('disk_percent', 0)
                    await self._handle_high_disk(disk_percent)

            # Send alert
            await self._send_alert('critical_system_health', system_health)

            try:
                from core.utils.notification_publisher import send_system_notification
                issues_text = "\n".join([f"• {issue}" for issue in issues[:5]])
                await send_system_notification(
                    title="🚨 Critical System Health Alert",
                    message=f"**Status:** CRITICAL\n**Issues:** {len(issues)}\n\n{issues_text}",
                    severity="critical",
                    metadata={
                        "cpu_percent": system_health.get('cpu_percent'),
                        "memory_percent": system_health.get('memory_percent'),
                        "disk_percent": system_health.get('disk_percent'),
                        "issues_count": len(issues)
                    }
                )
            except:
                pass

        except Exception as e:
            logger.error(f"Failed to handle critical health: {e}")

    async def _handle_component_failure(
        self,
        component: str,
        health: Any,
        issues: List[str] = None
    ):
        """Handle component failure"""
        try:
            # Check if in recovery cooldown
            if component in self.last_recovery:
                time_since_recovery = (datetime.now() - self.last_recovery[component]).total_seconds()
                if time_since_recovery < self.config.recovery_cooldown:
                    logger.info(f"Component {component} in recovery cooldown ({time_since_recovery:.0f}s)")
                    return

            # Check recovery attempt count
            if component not in self.recovery_attempts:
                self.recovery_attempts[component] = []

            # Clean old attempts (>1 hour)
            cutoff = datetime.now() - timedelta(hours=1)
            self.recovery_attempts[component] = [
                attempt for attempt in self.recovery_attempts[component]
                if attempt > cutoff
            ]

            # Check if exceeded max attempts
            if len(self.recovery_attempts[component]) >= self.config.max_recovery_attempts:
                logger.error(f"Max recovery attempts exceeded for {component}")
                await self._send_alert('max_recovery_attempts', {
                    'component': component,
                    'attempts': len(self.recovery_attempts[component])
                })
                return

            # Attempt recovery
            if self.config.auto_recovery:
                await self._attempt_recovery(component, RecoveryAction.RESTART_COMPONENT)

        except Exception as e:
            logger.error(f"Failed to handle component failure for {component}: {e}")

    async def _attempt_recovery(
        self,
        component: str,
        action: RecoveryAction,
        context: Dict[str, Any] = None
    ) -> bool:
        """
        Attempt recovery action

        Args:
            component: Component to recover
            action: Recovery action to take
            context: Additional context

        Returns:
            True if recovery successful
        """
        try:
            start_time = time.time()
            logger.info(f"Attempting recovery: {component} - {action.value}")

            self.stats['recoveries_attempted'] += 1
            # setdefault, not [component]. The key is seeded by the
            # rate-limit check that normally runs first, so any caller
            # reaching here by another route raised KeyError into the handler
            # below -- and a recovery that died on a missing dict key is
            # indistinguishable afterwards from one that was tried and failed.
            self.recovery_attempts.setdefault(component, []).append(datetime.now())

            # Get recovery handler
            handler = self.recovery_handlers.get(action)
            if not handler:
                logger.error(f"No handler for recovery action: {action}")
                return False

            # Execute recovery
            success = await handler(component, context or {})

            # Record attempt
            duration = time.time() - start_time
            attempt = RecoveryAttempt(
                timestamp=datetime.now(),
                component=component,
                action=action,
                success=success,
                duration=duration
            )

            self.recovery_history.append(attempt)
            self.last_recovery[component] = datetime.now()
            await self._persist_recovery(attempt, context or {})

            if success:
                self.stats['recoveries_successful'] += 1
                logger.info(f"Recovery successful: {component} ({duration:.2f}s)")

                if self.config.alert_on_recovery:
                    await self._send_alert('recovery_successful', {
                        'component': component,
                        'action': action.value,
                        'duration': duration
                    })
            else:
                self.stats['recoveries_failed'] += 1
                logger.error(f"Recovery failed: {component}")

                await self._send_alert('recovery_failed', {
                    'component': component,
                    'action': action.value
                })

                try:
                    from core.utils.notification_publisher import send_system_notification
                    await send_system_notification(
                        title=f"⚠️ Component Recovery Failed: {component}",
                        message=f"**Component:** {component}\n**Action:** {action.value}\n**Status:** FAILED\n**Total Failed Recoveries:** {self.stats['recoveries_failed']}",
                        severity="warning",
                        metadata={"component": component, "action": action.value, "failed_count": self.stats['recoveries_failed']}
                    )
                except:
                    pass

            return success

        except Exception as e:
            logger.error(f"Recovery attempt failed for {component}: {e}")

            attempt = RecoveryAttempt(
                timestamp=datetime.now(),
                component=component,
                action=action,
                success=False,
                error=str(e)
            )
            self.recovery_history.append(attempt)
            self.stats['recoveries_failed'] += 1

            return False

    # ================================================================================================
    # CRITICAL INFRASTRUCTURE GUARDIANSHIP
    # ================================================================================================

    async def _substrate_present(self) -> bool:
        """Whether the substrate process is alive, cached for a few seconds.

        Read from the substrate heartbeat in unified.system_control_status.
        Used to gate guardianship of substrate-internal systems: when the
        substrate is intentionally stopped, they are expectedly down and must
        not be restarted from this process.
        """
        import time as _time
        now = _time.monotonic()
        cached = getattr(self, "_substrate_present_cache", None)
        if cached is not None and now - cached[0] < 3.0:
            return cached[1]
        try:
            from core.health import system_control as sc
            present = await sc.substrate_present()
        except Exception:
            # Unknown → assume present, so a lookup failure never suppresses a
            # genuine restart of a system that should be up.
            present = True
        self._substrate_present_cache = (now, present)
        return present

    async def _ensure_critical_infrastructure_alive(self):
        """
        THE ULTIMATE GUARDIAN - Ensures security, health, and monitoring NEVER go down.

        This is the highest priority check. If these systems fail, the watchdog
        restarts them immediately.
        """
        try:
            # Check Health Monitor
            if not await self._check_health_monitor_alive():
                logger.critical("🛡️ CRITICAL: Health Monitor down - RESTARTING")
                await self._restart_health_monitor()
                self.stats['infrastructure_restarts'] += 1

                try:
                    from core.utils.notification_publisher import send_system_notification
                    await send_system_notification(
                        title="🚨 CRITICAL: Health Monitor Restarted",
                        message="**Component:** Health Monitor\n**Status:** DOWN → RESTARTING\n**Action:** Automatic restart by system watchdog\n**Total Restarts:** " + str(self.stats['infrastructure_restarts']),
                        severity="critical",
                        metadata={"component": "health_monitor", "restarts": self.stats['infrastructure_restarts']}
                    )
                except:
                    pass

            # SUBSTRATE-INTERNAL SYSTEMS ARE ONLY GUARDED WHILE THE SUBSTRATE RUNS.
            #
            # The monitoring coordinator and the governance/security system live
            # WITH the substrate, not in this guardian process. When the operator
            # stops the substrate they are expectedly down, and "restarting" them
            # from here is both futile and wrong -- this process cannot host a
            # substrate subsystem, so the attempt fails every 2s and spams
            # CRITICAL restarts and "Recovery FAILED for database". Their absence
            # while the substrate is off is not a failure to correct.
            substrate_up = await self._substrate_present()

            # Check Monitoring Coordinator (substrate-internal)
            if substrate_up and not await self._check_monitoring_coordinator_alive():
                logger.critical("🛡️ CRITICAL: Monitoring Coordinator down - RESTARTING")
                await self._restart_monitoring_coordinator()
                self.stats['infrastructure_restarts'] += 1

            # Check Security System (governance — substrate-internal)
            if substrate_up and not await self._check_security_system_alive():
                logger.critical("🛡️ CRITICAL: Security System down - RESTARTING")
                await self._restart_security_system()
                self.stats['infrastructure_restarts'] += 1

            # The Slack notification system was removed (only the deliberate tool
            # remains), so there is nothing here to guard or restart.

        except Exception as e:
            logger.error(f"🛡️ CRITICAL: Infrastructure check failed: {e}")

    async def _check_health_monitor_alive(self) -> bool:
        """Check if Health Monitor is alive and responding"""
        try:
            if not self.health_monitor:
                return False
            # Try to get system health - if this works, monitor is alive
            _ = await self.health_monitor.get_system_health()
            return True
        except:
            return False

    async def _check_monitoring_coordinator_alive(self) -> bool:
        """Check if Monitoring Coordinator is alive"""
        try:
            if not self.critical_infrastructure.get('monitoring_coordinator'):
                # Try to get it
                from core.health.monitoring_coordinator import get_monitoring_coordinator
                self.critical_infrastructure['monitoring_coordinator'] = get_monitoring_coordinator()

            coordinator = self.critical_infrastructure['monitoring_coordinator']
            return coordinator is not None and coordinator.is_monitoring
        except:
            return False

    async def _check_security_system_alive(self) -> bool:
        """Check if Security/Governance system is alive"""
        try:
            from core.governance import get_unified_governance
            governance = get_unified_governance()
            return governance is not None and hasattr(governance, 'initialized') and governance.initialized
        except:
            return False

    async def _restart_health_monitor(self):
        """Restart Health Monitor"""
        try:
            logger.info("🛡️ Restarting Health Monitor...")
            from core.health.health_monitor import get_health_monitor
            self.health_monitor = get_health_monitor()
            await self.health_monitor.start_monitoring()
            logger.info("✅ Health Monitor restarted")

            # Alert AI for self-healing
            await self._send_alert_to_ai('health_monitor_restarted', {
                'severity': 'CRITICAL',
                'action_taken': 'automatic_restart',
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"❌ Failed to restart Health Monitor: {e}")

    async def _restart_monitoring_coordinator(self):
        """Restart Monitoring Coordinator"""
        try:
            logger.info("🛡️ Restarting Monitoring Coordinator...")
            from core.health.monitoring_coordinator import get_monitoring_coordinator
            coordinator = get_monitoring_coordinator()
            await coordinator.initialize()
            await coordinator.start_monitoring()
            self.critical_infrastructure['monitoring_coordinator'] = coordinator
            logger.info("✅ Monitoring Coordinator restarted")

            # Alert AI for self-healing
            await self._send_alert_to_ai('monitoring_coordinator_restarted', {
                'severity': 'CRITICAL',
                'action_taken': 'automatic_restart',
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"❌ Failed to restart Monitoring Coordinator: {e}")

    async def _restart_security_system(self):
        """Restart Security/Governance System"""
        try:
            logger.info("🛡️ Restarting Security System...")
            from core.governance import get_unified_governance
            governance = get_unified_governance()
            if hasattr(governance, 'initialize'):
                await governance.initialize()
            logger.info("✅ Security System restarted")

            # Alert AI for self-healing
            await self._send_alert_to_ai('security_system_restarted', {
                'severity': 'CRITICAL',
                'action_taken': 'automatic_restart',
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"❌ Failed to restart Security System: {e}")

    async def _check_notification_system_alive(self) -> bool:
        """Check if Notification System is alive and responding
        
        NOTE: We check connectivity without actually sending a visible notification.
        """
        try:
            from core.integration.slack_notifier import get_slack_notifier
            notifier = get_slack_notifier()
            
            # Check that the notifier exists and has a valid webhook URL
            if notifier is None:
                return False
            
            # Check that we can get a webhook URL (proves config is loaded)
            from core.integration.slack_notifier import SlackChannel
            webhook_url = notifier._get_webhook_url(SlackChannel.ACTIVITY)
            
            return webhook_url is not None and len(webhook_url) > 0
        except Exception as e:
            logger.error(f"Notification system check failed: {e}")
            return False

    async def _restart_notification_system(self):
        """Restart Notification System"""
        failure_reason = "Unknown"
        try:
            logger.info("Attempting to restart Notification System...")

            # Check current state without sending a notification
            try:
                from core.integration.slack_notifier import get_slack_notifier, SlackChannel
                slack = get_slack_notifier()
                if slack and not slack._get_webhook_url(SlackChannel.ACTIVITY):
                    failure_reason = "Webhook URL not configured"
            except Exception as check_error:
                failure_reason = str(check_error)

            from core.integration.slack_notifier import get_slack_notifier
            slack = get_slack_notifier()

            if hasattr(slack, 'initialize'):
                await slack.initialize()

            logger.info("Notification System restarted")

            # Only send notification if this was a real failure recovery
            if failure_reason != "Unknown":
                try:
                    from core.utils.notification_publisher import send_system_notification
                    await send_system_notification(
                        title="Notification System Restored",
                        message=f"**Status:** DOWN -> RESTARTED\n**Reason for Failure:** {failure_reason}\n**Action:** Automatic restart by system watchdog",
                        severity="warning",
                        metadata={
                            "component": "notification_system",
                            "failure_reason": failure_reason,
                            "restarts": self.stats['infrastructure_restarts']
                        }
                    )
                except:
                    logger.warning("Could not send restart notification - system may still be recovering")

        except Exception as e:
            logger.error(f"Failed to restart Notification System: {e}")

    async def _check_shadow_mode_status(self):
        """Check if system is in shadow mode and update stats"""
        try:
            from core.governance import get_unified_governance
            governance = get_unified_governance()

            if governance and hasattr(governance, 'get_enforcement_status'):
                try:
                    status = governance.get_enforcement_status()
                    shadow_mode = status.get('shadow_mode_active', False)

                    # Update stats
                    if shadow_mode != self.stats['shadow_mode_active']:
                        self.stats['shadow_mode_active'] = shadow_mode
                        if shadow_mode:
                            logger.warning("⚠️ System in SHADOW MODE - Governance not enforcing!")
                            await self._send_alert('shadow_mode_enabled', {
                                'message': 'System in shadow mode - governance triggers logging only, not blocking'
                            })
                        else:
                            logger.info("✅ Shadow mode disabled - Governance enforcing")

                except:
                    pass  # Method might not exist yet

        except Exception as e:
            logger.debug(f"Shadow mode check: {e}")

    async def _send_alert_to_ai(self, alert_type: str, data: Dict[str, Any]):
        """
        Send alert to Autonomous Coordinator for AI self-healing.

        Uses EXISTING self-healing system: _receive_health_event() → AI analysis → recovery
        """
        try:
            if self.autonomous_coordinator:
                # Create health event in format coordinator expects
                health_event = {
                    'event_type': alert_type,
                    'severity': data.get('severity', 'CRITICAL'),
                    'component': 'infrastructure',
                    'timestamp': data.get('timestamp', datetime.now().isoformat()),
                    'action_taken': data.get('action_taken', 'watchdog_restart'),
                    'details': data,
                    'source': 'system_watchdog'
                }

                # Use EXISTING health event system
                if hasattr(self.autonomous_coordinator, '_receive_health_event'):
                    await self.autonomous_coordinator._receive_health_event(health_event)
                    logger.info(f"🤖 Health event sent to AI for analysis: {alert_type}")
                else:
                    logger.warning("Autonomous Coordinator doesn't have _receive_health_event method")

            # Also send to Slack
            await self._send_alert(alert_type, data)

        except Exception as e:
            logger.error(f"Failed to send alert to AI: {e}")

    # ================================================================================================
    # Recovery Action Handlers
    # ================================================================================================

    async def _restart_component(
        self,
        component: str,
        context: Dict[str, Any] = None
    ) -> bool:
        """
        Restart a component

        Args:
            component: Component name
            context: Additional context

        Returns:
            True if restart successful
        """
        try:
            logger.info(f"Restarting component: {component}")

            # Component-specific restart logic
            if component == "database":
                from core.database.mysql_manager import get_mysql_manager
                db_manager = get_mysql_manager()
                await db_manager.reconnect()
                return True

            elif component == "memory":
                from core.memory.memory_manager import get_memory_manager
                memory_manager = get_memory_manager()
                # Clear cache to free memory
                await memory_manager.clear_cache()
                return True

            elif component == "learning":
                # Restart learning system
                logger.info("Learning system restart not implemented")
                return False

            else:
                logger.warning(f"No restart handler for component: {component}")
                return False

        except Exception as e:
            logger.error(f"Component restart failed: {e}")
            return False

    async def _clear_cache(
        self,
        component: str,
        context: Dict[str, Any] = None
    ) -> bool:
        """Clear component caches"""
        try:
            logger.info(f"Clearing cache for: {component}")

            if component == "memory":
                from core.memory.memory_manager import get_memory_manager
                memory_manager = get_memory_manager()
                await memory_manager.clear_cache()
                return True

            return False

        except Exception as e:
            logger.error(f"Cache clear failed: {e}")
            return False

    async def _garbage_collect(
        self,
        component: str,
        context: Dict[str, Any] = None
    ) -> bool:
        """Force garbage collection"""
        try:
            import gc

            logger.info("Running garbage collection")

            # Run garbage collection
            collected = gc.collect()
            logger.info(f"Garbage collection: {collected} objects collected")

            return True

        except Exception as e:
            logger.error(f"Garbage collection failed: {e}")
            return False

    async def _reduce_load(
        self,
        component: str,
        context: Dict[str, Any] = None
    ) -> bool:
        """Reduce system load"""
        try:
            logger.info(f"Reducing load for: {component}")

            # Component-specific load reduction
            # This would involve pausing non-critical tasks, etc.

            return True

        except Exception as e:
            logger.error(f"Load reduction failed: {e}")
            return False

    async def _alert_admin(
        self,
        component: str,
        context: Dict[str, Any] = None
    ) -> bool:
        """Send alert to administrators"""
        return await self._send_alert('component_issue', {
            'component': component,
            **context
        })

    async def _send_alert(
        self,
        alert_type: str,
        data: Dict[str, Any]
    ) -> bool:
        """Send alert"""
        try:
            alert = {
                'timestamp': datetime.now().isoformat(),
                'type': alert_type,
                'data': data
            }

            logger.warning(f"ALERT: {alert_type} - {data}")
            self.stats['alerts_sent'] += 1

            # Send to Slack
            try:
                from core.integration.slack_notifier import get_slack_notifier
                slack = get_slack_notifier()
                await slack.send_message(f"⚠️ Watchdog Alert: {alert_type}\n{data}", channel="ALERTS")
            except Exception as e:
                logger.error(f"Failed to send Slack alert: {e}")

            return True

        except Exception as e:
            logger.error(f"Alert send failed: {e}")
            return False

    # ================================================================================================
    # Resource Handler Methods
    # ================================================================================================

    async def _handle_high_cpu(self, cpu_percent: float):
        """Handle high CPU usage"""
        try:
            logger.warning(f"High CPU detected: {cpu_percent}%")

            if self.config.auto_recovery:
                # Try garbage collection first
                await self._attempt_recovery('system', RecoveryAction.GARBAGE_COLLECT)

                # If still high, reduce load
                cpu_after = psutil.cpu_percent(interval=1)
                if cpu_after > self.config.cpu_critical_threshold * 0.9:
                    await self._attempt_recovery('system', RecoveryAction.REDUCE_LOAD)

            # Send alert
            await self._send_alert('high_cpu', {
                'cpu_percent': cpu_percent,
                'threshold': self.config.cpu_critical_threshold
            })

        except Exception as e:
            logger.error(f"Failed to handle high CPU: {e}")

    async def _handle_high_memory(self, memory_percent: float):
        """Handle high memory usage"""
        try:
            logger.warning(f"High memory detected: {memory_percent}%")

            if self.config.auto_recovery:
                # Try garbage collection
                await self._attempt_recovery('system', RecoveryAction.GARBAGE_COLLECT)

                # Clear caches
                await self._attempt_recovery('memory', RecoveryAction.CLEAR_CACHE)

            # Send alert
            await self._send_alert('high_memory', {
                'memory_percent': memory_percent,
                'threshold': self.config.memory_critical_threshold
            })

        except Exception as e:
            logger.error(f"Failed to handle high memory: {e}")

    async def _handle_high_disk(self, disk_percent: float):
        """Handle high disk usage"""
        try:
            logger.warning(f"High disk detected: {disk_percent}%")

            # Send critical alert
            await self._send_alert('high_disk', {
                'disk_percent': disk_percent,
                'threshold': self.config.disk_critical_threshold,
                'message': 'Manual intervention required'
            })

        except Exception as e:
            logger.error(f"Failed to handle high disk: {e}")

    async def _persist_recovery(self, attempt, context: Dict[str, Any]) -> None:
        """Write one recovery attempt to the durable record.

        EVERYTHING THIS OBJECT KNEW DIED WITH THE PROCESS. `self.stats` and
        `self.recovery_history` were in-memory only, so a restart erased the
        record of what the system had had to recover from -- which is exactly
        the history you need after a restart, and exactly the history a
        restart destroyed. A watchdog that cannot say what it has been doing
        is not a watchdog, it is a log line.
        """
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            await db.execute_query(
                """INSERT INTO unified.watchdog_recoveries
                       (attempt_id, component, action, issue, succeeded, detail,
                        attempted_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT (attempt_id) DO NOTHING""",
                (f"{attempt.component}_{attempt.action.value}_{attempt.timestamp.timestamp()}",
                 str(attempt.component)[:128],
                 str(attempt.action.value)[:64],
                 str(context.get("issue") or context.get("reason") or "")[:2000],
                 bool(attempt.success),
                 f"{attempt.duration:.3f}s",
                 attempt.timestamp),
                commit=True)
        except Exception as e:
            # Reported, never swallowed: a recovery that happened and was not
            # recorded is indistinguishable afterwards from one that did not.
            logger.error("Watchdog recovery not persisted (%s): %s",
                         attempt.component, e)

    async def persist_statistics(self) -> bool:
        """Snapshot the running totals so they survive this process."""
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            uptime = (datetime.now() - self.stats["uptime_start"]).total_seconds()
            await db.execute_query(
                """INSERT INTO unified.watchdog_stats
                       (recorded_at, total_checks, issues_detected,
                        recoveries_attempted, recoveries_successful,
                        recoveries_failed, alerts_sent, infrastructure_restarts,
                        uptime_seconds)
                   VALUES (NOW(),$1,$2,$3,$4,$5,$6,$7,$8)""",
                (int(self.stats["total_checks"]), int(self.stats["issues_detected"]),
                 int(self.stats["recoveries_attempted"]),
                 int(self.stats["recoveries_successful"]),
                 int(self.stats["recoveries_failed"]),
                 int(self.stats["alerts_sent"]),
                 int(self.stats["infrastructure_restarts"]), float(uptime)),
                commit=True)
            return True
        except Exception as e:
            logger.error("Watchdog statistics not persisted: %s", e)
            return False

    async def get_persisted_statistics(self) -> Dict[str, Any]:
        """Totals across ALL runs, not just this process.

        `get_statistics()` reports `self.stats`, which starts at zero every
        boot -- so a freshly started watchdog reports that it has never
        recovered anything, no matter how much it has recovered.
        """
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            rows = await db.execute_query(
                """SELECT COUNT(*)                                   AS attempts,
                          COUNT(*) FILTER (WHERE succeeded)          AS successful,
                          COUNT(*) FILTER (WHERE NOT succeeded)      AS failed,
                          COUNT(DISTINCT component)                  AS components,
                          MAX(attempted_at)                          AS last_recovery
                     FROM unified.watchdog_recoveries""", fetch_all=True)
        except Exception as e:
            logger.error("Persisted watchdog statistics unavailable: %s", e)
            return {"available": False, "error": f"{type(e).__name__}: {e}"}

        row = rows[0] if rows else {}
        attempts = int(row.get("attempts") or 0)
        return {
            "available": True,
            "recoveries_attempted": attempts,
            "recoveries_successful": int(row.get("successful") or 0),
            "recoveries_failed": int(row.get("failed") or 0),
            "components_recovered": int(row.get("components") or 0),
            "last_recovery": row.get("last_recovery"),
            # None over zero attempts: a success rate with nothing to average
            # is undefined, and 0.0 reads as "never succeeded".
            "success_rate": (int(row.get("successful") or 0) / attempts) if attempts else None,
        }

    async def get_statistics(self) -> Dict[str, Any]:
        """Get watchdog statistics"""
        return {
            **self.stats,
            'is_running': self.is_running,
            'recovery_history_count': len(self.recovery_history),
            'components_monitored': len(self.recovery_attempts),
            'uptime_seconds': (datetime.now() - self.stats['uptime_start']).total_seconds()
        }

    async def get_recovery_history(
        self,
        component: str = None,
        limit: int = 100
    ) -> List[RecoveryAttempt]:
        """Get recovery history"""
        history = self.recovery_history[-limit:]

        if component:
            history = [h for h in history if h.component == component]

        return history


# Singleton instance
_system_watchdog: Optional[SystemWatchdog] = None


def get_system_watchdog() -> SystemWatchdog:
    """Get global system watchdog instance"""
    global _system_watchdog
    if _system_watchdog is None:
        _system_watchdog = SystemWatchdog()
    return _system_watchdog


def get_watchdog() -> SystemWatchdog:
    """Backward-compatible alias for get_system_watchdog()."""
    return get_system_watchdog()


async def start_watchdog(config: WatchdogConfig = None):
    """Start the system watchdog"""
    watchdog = get_system_watchdog()
    if config:
        watchdog.config = config
    await watchdog.start()


# CLI test
async def main():
    """Test system watchdog"""
    logging.basicConfig(level=logging.INFO)

    watchdog = get_system_watchdog()

    print("\n=== System Watchdog Test ===")

    # Start watchdog
    await watchdog.start()

    print("Watchdog running, monitoring for 60 seconds...")

    # Run for 60 seconds
    await asyncio.sleep(60)

    # Get statistics
    stats = await watchdog.get_statistics()
    print(f"\nStatistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Stop watchdog
    await watchdog.stop()

    print("\nWatchdog stopped")


if __name__ == "__main__":
    asyncio.run(main())
