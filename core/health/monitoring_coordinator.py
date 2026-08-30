#!/usr/bin/env python3
"""
Monitoring Coordinator
======================
Coordinates health monitoring across all TorinAI components

Purpose:
- Orchestrate multiple health monitors
- Aggregate component health status
- Route alerts to notification system
- Manage periodic health check cycles
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from core.health.health_monitor import HealthMonitor, get_health_monitor
from core.health.system_watchdog import SystemWatchdog, get_system_watchdog
from core.health.recovery_manager import RecoveryManager, get_recovery_manager

logger = logging.getLogger(__name__)


class ComponentType(Enum):
    """Component types for monitoring"""
    DATABASE = "database"
    MEMORY = "memory"
    LEARNING = "learning"
    REASONING = "reasoning"
    AGENTS = "agents"
    SECURITY = "security"
    STORAGE = "storage"
    API = "api"
    QUANTUM = "quantum"
    NETWORK = "network"


class HealthStatus(Enum):
    """System health status"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ComponentHealth:
    """Component health status"""
    component: ComponentType
    status: HealthStatus
    metrics: Dict[str, Any] = field(default_factory=dict)
    last_check: datetime = field(default_factory=datetime.now)
    issues: List[str] = field(default_factory=list)
    uptime_seconds: float = 0.0


@dataclass
class SystemHealth:
    """Overall system health"""
    overall_status: HealthStatus
    components: Dict[ComponentType, ComponentHealth]
    timestamp: datetime
    active_alerts: int = 0
    critical_issues: int = 0
    total_components: int = 0
    healthy_components: int = 0


@dataclass
class Alert:
    """System alert"""
    alert_id: str
    severity: AlertSeverity
    component: ComponentType
    message: str
    timestamp: datetime
    acknowledged: bool = False
    resolved: bool = False


class MonitoringCoordinator:
    """
    Monitoring Coordinator

    Purpose:
    - Coordinate health monitoring across all components
    - Aggregate component status into system health
    - Route alerts and manage escalation
    - Schedule periodic health checks
    - Trigger recovery actions when needed

    Usage:
        coordinator = MonitoringCoordinator()
        await coordinator.initialize()
        await coordinator.start_monitoring()
    """

    def __init__(self, check_interval: int = 60, startup_delay: int = 30):
        self.check_interval = check_interval  # seconds
        self.startup_delay = startup_delay    # seconds to wait before first check

        # Component monitors
        self.health_monitor = None
        self.system_watchdog = None
        self.recovery_manager = None

        # Integration points
        self.slack_notifier = None
        self.autonomous_coordinator = None
        self.singleton_callback = None  # Callback for Singleton

        # Component health tracking
        self.component_health: Dict[ComponentType, ComponentHealth] = {}

        # Alert tracking
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.max_alert_history = 1000

        # Monitoring state
        self.is_monitoring = False
        self.monitoring_task = None
        self._startup_complete = False  # Suppress alerts during initialization
        self._checks_since_start = 0    # Track checks for grace period
        self._init_timestamp = time.time()  # Track when monitoring started
        self._startup_grace_seconds = 45    # Suppress alerts for first 45 seconds

        # Statistics
        self.stats = {
            'total_checks': 0,
            'failed_checks': 0,
            'alerts_generated': 0,
            'alerts_resolved': 0,
            'last_check_time': None,
            'uptime_start': datetime.now().isoformat()
        }

        logger.info(f"MonitoringCoordinator initialized: {check_interval}s interval")

    async def initialize(self):
        """Initialize monitoring components"""
        try:
            # Initialize monitors
            self.health_monitor = get_health_monitor()
            self.system_watchdog = get_system_watchdog()
            self.recovery_manager = get_recovery_manager()

            # Initialize component health tracking
            for component_type in ComponentType:
                self.component_health[component_type] = ComponentHealth(
                    component=component_type,
                    status=HealthStatus.HEALTHY
                )

            logger.info("MonitoringCoordinator initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize MonitoringCoordinator: {e}")
            return False

    async def start_monitoring(self):
        """Start periodic monitoring"""
        if self.is_monitoring:
            logger.warning("Monitoring already running")
            return

        self.is_monitoring = True
        logger.info("Starting health monitoring")

        # Start monitoring loop
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())

    async def stop_monitoring(self):
        """Stop periodic monitoring"""
        if not self.is_monitoring:
            return

        self.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("Health monitoring stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop"""
        # Wait for startup delay to let all systems initialize
        if self.startup_delay > 0:
            logger.info(f"Health monitoring waiting {self.startup_delay}s for system initialization...")
            await asyncio.sleep(self.startup_delay)
            logger.info("Startup delay complete, beginning health monitoring")
        
        while self.is_monitoring:
            try:
                # Perform health check
                await self.check_system_health()

                # Wait for next interval
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                self.stats['failed_checks'] += 1
                await asyncio.sleep(self.check_interval)

    async def check_system_health(self) -> SystemHealth:
        """
        Check health of all system components

        Returns:
            SystemHealth with aggregated status
        """
        try:
            self.stats['total_checks'] += 1
            self.stats['last_check_time'] = datetime.now().isoformat()
            self._checks_since_start += 1
            
            # Mark startup complete after 3 checks (gives systems time to initialize)
            if self._checks_since_start >= 3 and not self._startup_complete:
                self._startup_complete = True
                logger.info("Health monitoring startup grace period complete - alerts now active")

            # Check each component
            await self._check_database_health()
            await self._check_memory_health()
            await self._check_learning_health()
            # NOTE: Quantum reasoning health check disabled - service is intentionally commented out
            # await self._check_reasoning_health()  # Contains quantum check
            await self._check_agents_health()
            await self._check_security_health()
            await self._check_storage_health()
            await self._check_api_health()
            # await self._check_quantum_health()  # Quantum is intentionally disabled
            await self._check_network_health()

            # Aggregate system health
            system_health = self._aggregate_health()

            # Check for issues and generate alerts
            await self._process_health_issues(system_health)

            return system_health

        except Exception as e:
            logger.error(f"System health check failed: {e}")
            self.stats['failed_checks'] += 1

            # Return degraded status on error
            return SystemHealth(
                overall_status=HealthStatus.DEGRADED,
                components=self.component_health,
                timestamp=datetime.now(),
                active_alerts=len(self.active_alerts),
                critical_issues=1
            )

    async def _check_database_health(self):
        """Check MySQL database health"""
        import time

        try:
            from core.database import get_database_manager

            db = get_database_manager()
            if not db or not db.initialized:
                self.component_health[ComponentType.DATABASE] = ComponentHealth(
                    component=ComponentType.DATABASE,
                    status=HealthStatus.OFFLINE,
                    metrics={},
                    last_check=datetime.now(),
                    issues=["Database not initialized"]
                )
                return

            # Test connection with actual query
            start_time = time.time()

            async with db.get_connection() as conn:
                # Get real connection stats (PostgreSQL equivalent)
                threads_result = await conn.fetchrow("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                active_connections = int(threads_result[0]) if threads_result else 0

                # Get query performance. Some deployments may not have
                # pg_stat_statements installed; treat that as a missing
                # metric rather than a hard database failure.
                slow_queries = 0
                try:
                    slow_queries_result = await conn.fetchrow(
                        "SELECT count(*) FROM pg_stat_statements WHERE mean_exec_time > 1000"
                    )
                    slow_queries = int(slow_queries_result[0]) if slow_queries_result else 0
                except Exception as stats_exc:
                    logger.debug(f"pg_stat_statements not available, skipping slow query metric: {stats_exc}")

                # Get database size (PostgreSQL)
                size_result = await conn.fetchrow(
                    "SELECT pg_database_size(current_database()) / 1024.0 / 1024.0 AS size_mb"
                )
                db_size_mb = float(size_result[0]) if size_result and size_result[0] else 0.0

            query_latency_ms = (time.time() - start_time) * 1000

            # Determine status and issues
            status = HealthStatus.HEALTHY
            issues = []

            if active_connections > 100:
                status = HealthStatus.CRITICAL
                issues.append(f"Too many connections: {active_connections}")
            elif active_connections > 50:
                status = HealthStatus.WARNING
                issues.append(f"High connection count: {active_connections}")

            if slow_queries > 100:
                status = HealthStatus.WARNING
                issues.append(f"Slow queries detected: {slow_queries}")

            if query_latency_ms > 1000:
                status = HealthStatus.CRITICAL
                issues.append(f"High query latency: {query_latency_ms:.1f}ms")
            elif query_latency_ms > 500:
                status = HealthStatus.WARNING
                issues.append(f"Elevated query latency: {query_latency_ms:.1f}ms")

            self.component_health[ComponentType.DATABASE] = ComponentHealth(
                component=ComponentType.DATABASE,
                status=status,
                metrics={
                    'active_connections': active_connections,
                    'slow_queries': slow_queries,
                    'query_latency_ms': round(query_latency_ms, 2),
                    'database_size_mb': round(db_size_mb, 2)
                },
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            self.component_health[ComponentType.DATABASE] = ComponentHealth(
                component=ComponentType.DATABASE,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Database connection failed: {str(e)}"]
            )

    async def _check_memory_health(self):
        """Check Memory Agent health"""
        try:
            from core.memory import get_memory_agent

            memory = await get_memory_agent()
            if not memory or not memory.initialized:
                self.component_health[ComponentType.MEMORY] = ComponentHealth(
                    component=ComponentType.MEMORY,
                    status=HealthStatus.OFFLINE,
                    metrics={},
                    last_check=datetime.now(),
                    issues=["Memory Agent not initialized"]
                )
                return

            # Get real metrics from memory agent
            mem_metrics = memory.get_metrics()

            status = HealthStatus.HEALTHY
            issues = []

            # Check PostgreSQL availability (the actual memory storage backend)
            if not mem_metrics.get('postgres_available'):
                status = HealthStatus.CRITICAL
                issues.append("PostgreSQL storage not available")

            # Check embedding service
            if not mem_metrics.get('embedding_available'):
                status = HealthStatus.WARNING
                issues.append("Embedding service not available")

            # Check cache size
            cache_size = mem_metrics.get('cache_size', 0)
            if cache_size > 10000:
                status = HealthStatus.WARNING
                issues.append(f"Large cache size: {cache_size} items")

            # Extract key metrics
            total_memories = mem_metrics.get('total_memories_stored', 0)
            total_queries = mem_metrics.get('total_queries', 0)
            avg_query_time = mem_metrics.get('avg_query_time_ms', 0)

            if avg_query_time > 1000:
                status = HealthStatus.CRITICAL
                issues.append(f"High query latency: {avg_query_time:.1f}ms")
            elif avg_query_time > 500:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.WARNING
                issues.append(f"Elevated query latency: {avg_query_time:.1f}ms")

            self.component_health[ComponentType.MEMORY] = ComponentHealth(
                component=ComponentType.MEMORY,
                status=status,
                metrics={
                    'total_memories': total_memories,
                    'total_queries': total_queries,
                    'avg_query_time_ms': round(avg_query_time, 2),
                    'cache_size': cache_size,
                    'mysql_available': mem_metrics.get('mysql_available', False),
                    'embedding_available': mem_metrics.get('embedding_available', False)
                },
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Memory health check failed: {e}")
            self.component_health[ComponentType.MEMORY] = ComponentHealth(
                component=ComponentType.MEMORY,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Memory check failed: {str(e)}"]
            )

    async def _check_learning_health(self):
        """Check Unified Learning System health"""
        try:
            from core.learning import get_unified_learning_system

            learning = get_unified_learning_system()
            if not learning or not learning.initialized:
                self.component_health[ComponentType.LEARNING] = ComponentHealth(
                    component=ComponentType.LEARNING,
                    status=HealthStatus.OFFLINE,
                    metrics={},
                    last_check=datetime.now(),
                    issues=["Learning System not initialized"]
                )
                return

            # Get real status from learning system
            system_status = learning.get_system_status()
            components = system_status.get('components', {})
            metrics = system_status.get('metrics', {})

            status = HealthStatus.HEALTHY
            issues = []

            # Check component health
            if not components.get('memory_system'):
                status = HealthStatus.CRITICAL
                issues.append("Memory system not connected")

            if not components.get('llm_service'):
                status = HealthStatus.CRITICAL
                issues.append("LLM service not connected")

            # Meta-learning is optional - don't generate critical alerts for it
            if not components.get('meta_learning'):
                # Just log, don't change status - meta-learning is optional
                logger.debug("Meta-learning not initialized (optional component)")

            # Check activity levels
            active_tasks = system_status.get('active_tasks', 0)
            total_sessions = metrics.get('total_learning_sessions', 0)
            successful_adaptations = metrics.get('successful_adaptations', 0)

            # Calculate success rate
            success_rate = (successful_adaptations / total_sessions * 100) if total_sessions > 0 else 0

            if success_rate < 50 and total_sessions > 10:
                status = HealthStatus.WARNING
                issues.append(f"Low success rate: {success_rate:.1f}%")

            self.component_health[ComponentType.LEARNING] = ComponentHealth(
                component=ComponentType.LEARNING,
                status=status,
                metrics={
                    'initialized': system_status.get('initialized', False),
                    'total_sessions': total_sessions,
                    'successful_adaptations': successful_adaptations,
                    'success_rate_percent': round(success_rate, 1),
                    'active_tasks': active_tasks,
                    'knowledge_base_size': metrics.get('knowledge_base_size', 0),
                    'memory_connected': components.get('memory_system', False),
                    'llm_connected': components.get('llm_service', False)
                },
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Learning health check failed: {e}")
            self.component_health[ComponentType.LEARNING] = ComponentHealth(
                component=ComponentType.LEARNING,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Learning check failed: {str(e)}"]
            )

    async def _check_reasoning_health(self):
        """Check Quantum Reasoning and Predictive Intelligence health"""
        try:
            from core.reasoning import get_quantum_reasoning
            from core.intelligence import get_predictive_intelligence

            status = HealthStatus.HEALTHY
            issues = []
            metrics = {}

            # Check Quantum Reasoning
            try:
                quantum = get_quantum_reasoning()
                if quantum and hasattr(quantum, 'initialized'):
                    metrics['quantum_initialized'] = quantum.initialized
                    if not quantum.initialized:
                        status = HealthStatus.WARNING
                        issues.append("Quantum reasoning not initialized")
                else:
                    metrics['quantum_initialized'] = False
                    status = HealthStatus.DEGRADED
                    issues.append("Quantum reasoning not available")
            except Exception as e:
                metrics['quantum_initialized'] = False
                logger.debug(f"Quantum reasoning check: {e}")

            # Check Predictive Intelligence
            try:
                predictive = await get_predictive_intelligence()
                if predictive and hasattr(predictive, 'initialized'):
                    metrics['predictive_initialized'] = predictive.initialized
                    if not predictive.initialized and status == HealthStatus.HEALTHY:
                        status = HealthStatus.WARNING
                        issues.append("Predictive intelligence not initialized")
                else:
                    metrics['predictive_initialized'] = False
                    if status == HealthStatus.HEALTHY:
                        status = HealthStatus.DEGRADED
                    issues.append("Predictive intelligence not available")
            except Exception as e:
                metrics['predictive_initialized'] = False
                logger.debug(f"Predictive intelligence check: {e}")

            # If both are unavailable, mark as degraded
            if not metrics.get('quantum_initialized') and not metrics.get('predictive_initialized'):
                status = HealthStatus.DEGRADED

            self.component_health[ComponentType.REASONING] = ComponentHealth(
                component=ComponentType.REASONING,
                status=status,
                metrics=metrics,
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Reasoning health check failed: {e}")
            self.component_health[ComponentType.REASONING] = ComponentHealth(
                component=ComponentType.REASONING,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Reasoning check failed: {str(e)}"]
            )

    async def _check_agents_health(self):
        """Check Autonomous Coordinator and agent systems health"""
        try:
            # Check if we can access coordinator through our callback
            coordinator = None
            if self.autonomous_coordinator:
                coordinator = self.autonomous_coordinator
            else:
                # Try to get from singleton
                try:
                    from core.agents.autonomous import get_autonomous_coordinator
                    coordinator = get_autonomous_coordinator()
                except:
                    pass

            if not coordinator:
                self.component_health[ComponentType.AGENTS] = ComponentHealth(
                    component=ComponentType.AGENTS,
                    status=HealthStatus.OFFLINE,
                    metrics={},
                    last_check=datetime.now(),
                    issues=["Autonomous Coordinator not available"]
                )
                return

            status = HealthStatus.HEALTHY
            issues = []

            # Check coordinator initialization
            metrics = {
                'coordinator_initialized': hasattr(coordinator, 'initialized') and coordinator.initialized
            }

            # The coordinator IS running if this health check is being called from it
            # So don't report it as not initialized - just check the teacher model
            if not metrics['coordinator_initialized']:
                # Check if coordinator is actually making decisions (it is, since we're here)
                if hasattr(coordinator, 'stats') and coordinator.stats.get('cycles_completed', 0) > 0:
                    metrics['coordinator_initialized'] = True
                    logger.debug("Coordinator working (cycles completed) despite initialized=False")
                else:
                    # During startup, this is just a warning not critical
                    status = HealthStatus.WARNING
                    issues.append("Autonomous Coordinator initializing...")

            # Check the teacher model (unified LLM)
            if getattr(coordinator, 'teacher_model', None):
                metrics['brain_connected'] = True
            else:
                metrics['brain_connected'] = False
                status = HealthStatus.CRITICAL
                issues.append("Teacher model (Unified LLM) not connected")

            # Check executor
            if hasattr(coordinator, 'executor') and coordinator.executor:
                metrics['executor_available'] = True
            else:
                metrics['executor_available'] = False
                status = HealthStatus.WARNING
                issues.append("General Purpose Executor not available")

            # Check subsystems
            subsystems_connected = 0
            total_subsystems = 0

            for subsystem_name in ['perception', 'planning', 'learning', 'memory_system']:
                total_subsystems += 1
                if hasattr(coordinator, subsystem_name) and getattr(coordinator, subsystem_name):
                    subsystems_connected += 1

            metrics['subsystems_connected'] = subsystems_connected
            metrics['total_subsystems'] = total_subsystems

            if subsystems_connected < total_subsystems // 2:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.WARNING
                issues.append(f"Only {subsystems_connected}/{total_subsystems} subsystems connected")

            self.component_health[ComponentType.AGENTS] = ComponentHealth(
                component=ComponentType.AGENTS,
                status=status,
                metrics=metrics,
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Agents health check failed: {e}")
            self.component_health[ComponentType.AGENTS] = ComponentHealth(
                component=ComponentType.AGENTS,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Agents check failed: {str(e)}"]
            )

    async def _check_security_health(self):
        """Check Unified Governance and Security systems health"""
        try:
            from core.governance import get_unified_governance

            governance = get_unified_governance()
            if not governance:
                self.component_health[ComponentType.SECURITY] = ComponentHealth(
                    component=ComponentType.SECURITY,
                    status=HealthStatus.OFFLINE,
                    metrics={},
                    last_check=datetime.now(),
                    issues=["Governance system not available"]
                )
                return

            status = HealthStatus.HEALTHY
            issues = []

            # Check governance initialization
            metrics = {
                'governance_initialized': hasattr(governance, 'initialized') and governance.initialized
            }

            # Check if governance is actually processing (more reliable than .initialized flag)
            # The governance system may be working even if .initialized is False during startup
            if not metrics['governance_initialized']:
                # Check if governance has made any decisions (indicates it's actually working)
                if hasattr(governance, 'get_stats'):
                    try:
                        stats = governance.get_stats()
                        if stats.get('total_decisions', 0) > 0:
                            # Governance is working, just flag wasn't set
                            metrics['governance_initialized'] = True
                            logger.debug("Governance working (decisions made) despite initialized=False")
                        else:
                            # Only warn if no decisions AND not initialized
                            status = HealthStatus.WARNING
                            issues.append("Unified Governance initializing...")
                    except:
                        status = HealthStatus.WARNING
                        issues.append("Unified Governance initializing...")
                else:
                    status = HealthStatus.WARNING
                    issues.append("Unified Governance initializing...")

            # Check if governance has stats/metrics
            if hasattr(governance, 'get_stats'):
                try:
                    stats = governance.get_stats()
                    metrics['total_decisions'] = stats.get('total_decisions', 0)
                    metrics['blocked_actions'] = stats.get('blocked_actions', 0)
                    metrics['violations'] = stats.get('violations', 0)

                    if metrics['violations'] > 0:
                        status = HealthStatus.WARNING
                        issues.append(f"{metrics['violations']} governance violations detected")
                except:
                    pass

            self.component_health[ComponentType.SECURITY] = ComponentHealth(
                component=ComponentType.SECURITY,
                status=status,
                metrics=metrics,
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Security health check failed: {e}")
            self.component_health[ComponentType.SECURITY] = ComponentHealth(
                component=ComponentType.SECURITY,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Security check failed: {str(e)}"]
            )

    async def _check_storage_health(self):
        """Check disk storage health"""
        try:
            import psutil

            status = HealthStatus.HEALTHY
            issues = []

            # Check local disk usage (REAL)
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent

            metrics = {
                'disk_usage_percent': round(disk_percent, 1),
                'disk_used_gb': round(disk.used / (1024**3), 2),
                'disk_free_gb': round(disk.free / (1024**3), 2),
                'disk_total_gb': round(disk.total / (1024**3), 2)
            }

            if disk_percent > 95:
                status = HealthStatus.CRITICAL
                issues.append(f"Critical disk space: {disk_percent:.1f}% used")
            elif disk_percent > 85:
                status = HealthStatus.WARNING
                issues.append(f"High disk usage: {disk_percent:.1f}% used")

            self.component_health[ComponentType.STORAGE] = ComponentHealth(
                component=ComponentType.STORAGE,
                status=status,
                metrics=metrics,
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Storage health check failed: {e}")
            self.component_health[ComponentType.STORAGE] = ComponentHealth(
                component=ComponentType.STORAGE,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Storage check failed: {str(e)}"]
            )

    async def _check_api_health(self):
        """Check Tool Registry and API systems health"""
        try:
            from core.tools import get_tool_registry

            registry = get_tool_registry()
            if not registry:
                self.component_health[ComponentType.API] = ComponentHealth(
                    component=ComponentType.API,
                    status=HealthStatus.OFFLINE,
                    metrics={},
                    last_check=datetime.now(),
                    issues=["Tool Registry not available"]
                )
                return

            status = HealthStatus.HEALTHY
            issues = []

            # Count registered tools
            all_tools = registry.list_tools() if hasattr(registry, 'list_tools') else []
            tool_count = len(all_tools)

            metrics = {
                'tool_registry_available': True,
                'total_tools_registered': tool_count
            }

            if tool_count == 0:
                status = HealthStatus.WARNING
                issues.append("No tools registered in tool registry")
            elif tool_count < 50:
                status = HealthStatus.WARNING
                issues.append(f"Low tool count: {tool_count} tools")

            # Check if registry has categories
            if hasattr(registry, 'get_categories'):
                try:
                    categories = registry.get_categories()
                    metrics['tool_categories'] = len(categories)
                except:
                    pass

            self.component_health[ComponentType.API] = ComponentHealth(
                component=ComponentType.API,
                status=status,
                metrics=metrics,
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"API health check failed: {e}")
            self.component_health[ComponentType.API] = ComponentHealth(
                component=ComponentType.API,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"API check failed: {str(e)}"]
            )

    async def _check_quantum_health(self):
        """Check Quantum Reasoning system health"""
        try:
            from core.reasoning import get_quantum_reasoning

            quantum = get_quantum_reasoning()
            status = HealthStatus.HEALTHY
            issues = []

            if not quantum:
                # Quantum not available is acceptable (degraded, not critical)
                self.component_health[ComponentType.QUANTUM] = ComponentHealth(
                    component=ComponentType.QUANTUM,
                    status=HealthStatus.DEGRADED,
                    metrics={'quantum_available': False},
                    last_check=datetime.now(),
                    issues=["Quantum Reasoning not available (using classical fallback)"]
                )
                return

            metrics = {
                'quantum_available': True,
                'initialized': hasattr(quantum, 'initialized') and quantum.initialized
            }

            if not metrics['initialized']:
                status = HealthStatus.DEGRADED
                issues.append("Quantum Reasoning not initialized (using fallback)")

            # Check if quantum has any stats/metrics
            if hasattr(quantum, 'get_stats'):
                try:
                    stats = quantum.get_stats()
                    metrics.update(stats)
                except:
                    pass

            self.component_health[ComponentType.QUANTUM] = ComponentHealth(
                component=ComponentType.QUANTUM,
                status=status,
                metrics=metrics,
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.debug(f"Quantum health check: {e}")
            # Quantum not working is degraded, not critical
            self.component_health[ComponentType.QUANTUM] = ComponentHealth(
                component=ComponentType.QUANTUM,
                status=HealthStatus.DEGRADED,
                metrics={'quantum_available': False},
                last_check=datetime.now(),
                issues=["Quantum system check failed (using classical fallback)"]
            )

    async def _check_network_health(self):
        """Check network connectivity"""
        import socket
        import time

        try:
            status = HealthStatus.HEALTHY
            issues = []

            # Test DNS resolution and connectivity
            internet_available = False
            latency_ms = 0.0

            try:
                start_time = time.time()
                # Try to resolve and connect to a reliable host
                socket.create_connection(("8.8.8.8", 53), timeout=3)
                latency_ms = (time.time() - start_time) * 1000
                internet_available = True
            except (socket.timeout, socket.error, OSError):
                internet_available = False
                logger.warning("Network connectivity test failed")

            metrics = {
                'internet_available': internet_available,
                'latency_ms': round(latency_ms, 2) if internet_available else 0.0
            }

            if not internet_available:
                status = HealthStatus.CRITICAL
                issues.append("No internet connectivity")
            elif latency_ms > 1000:
                status = HealthStatus.WARNING
                issues.append(f"High network latency: {latency_ms:.1f}ms")

            self.component_health[ComponentType.NETWORK] = ComponentHealth(
                component=ComponentType.NETWORK,
                status=status,
                metrics=metrics,
                last_check=datetime.now(),
                issues=issues
            )

        except Exception as e:
            logger.error(f"Network health check failed: {e}")
            self.component_health[ComponentType.NETWORK] = ComponentHealth(
                component=ComponentType.NETWORK,
                status=HealthStatus.OFFLINE,
                metrics={},
                last_check=datetime.now(),
                issues=[f"Network check failed: {str(e)}"]
            )

    def _aggregate_health(self) -> SystemHealth:
        """Aggregate component health into system health"""
        total_components = len(self.component_health)
        healthy_components = 0
        critical_issues = 0

        # Determine overall status
        critical_count = 0
        warning_count = 0
        offline_count = 0

        for component_health in self.component_health.values():
            if component_health.status == HealthStatus.HEALTHY:
                healthy_components += 1
            elif component_health.status == HealthStatus.WARNING:
                warning_count += 1
            elif component_health.status == HealthStatus.CRITICAL:
                critical_count += 1
                critical_issues += len(component_health.issues)
            elif component_health.status == HealthStatus.OFFLINE:
                offline_count += 1
                critical_issues += 1

        # Determine overall status
        if critical_count > 0 or offline_count > 2:
            overall_status = HealthStatus.CRITICAL
        elif offline_count > 0 or warning_count > 3:
            overall_status = HealthStatus.DEGRADED
        elif warning_count > 0:
            overall_status = HealthStatus.WARNING
        else:
            overall_status = HealthStatus.HEALTHY

        return SystemHealth(
            overall_status=overall_status,
            components=self.component_health,
            timestamp=datetime.now(),
            active_alerts=len(self.active_alerts),
            critical_issues=critical_issues,
            total_components=total_components,
            healthy_components=healthy_components
        )

    async def _process_health_issues(self, system_health: SystemHealth):
        """Process health issues and generate alerts"""
        try:
            # Check each component for issues
            for component_type, component_health in system_health.components.items():
                # Generate alerts for critical issues
                if component_health.status == HealthStatus.CRITICAL:
                    for issue in component_health.issues:
                        await self._generate_alert(
                            AlertSeverity.CRITICAL,
                            component_type,
                            issue
                        )

                # Generate warnings
                elif component_health.status == HealthStatus.WARNING:
                    for issue in component_health.issues:
                        await self._generate_alert(
                            AlertSeverity.WARNING,
                            component_type,
                            issue
                        )

                # Alert on offline components
                elif component_health.status == HealthStatus.OFFLINE:
                    await self._generate_alert(
                        AlertSeverity.ERROR,
                        component_type,
                        f"{component_type.value} is offline"
                    )

        except Exception as e:
            logger.error(f"Failed to process health issues: {e}")

    async def _generate_alert(
        self,
        severity: AlertSeverity,
        component: ComponentType,
        message: str
    ) -> str:
        """
        Generate a system alert

        Returns:
            Alert ID
        """
        try:
            # Suppress alerts during startup grace period using BOTH checks:
            # 1. Time-based: first 45 seconds after initialization
            # 2. Count-based: first 3 health checks
            # This ensures we don't generate false positives while systems initialize
            elapsed = time.time() - self._init_timestamp
            if elapsed < self._startup_grace_seconds or (not self._startup_complete and self._checks_since_start < 3):
                logger.debug(f"Suppressing startup alert ({elapsed:.1f}s elapsed): {severity.value} - {component.value} - {message}")
                return ""

            # Don't alert on "initializing..." messages - these are transient states
            if "initializing" in message.lower():
                logger.debug(f"Suppressing transient state alert: {component.value} - {message}")
                return ""
            
            alert_id = f"{component.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

            # Check if similar alert already exists
            for existing_alert in self.active_alerts.values():
                if (existing_alert.component == component and
                    existing_alert.message == message and
                    not existing_alert.resolved):
                    # Don't create duplicate alert
                    return existing_alert.alert_id

            # Create new alert
            alert = Alert(
                alert_id=alert_id,
                severity=severity,
                component=component,
                message=message,
                timestamp=datetime.now()
            )

            self.active_alerts[alert_id] = alert
            self.alert_history.append(alert)

            # Trim alert history
            if len(self.alert_history) > self.max_alert_history:
                self.alert_history = self.alert_history[-self.max_alert_history:]

            self.stats['alerts_generated'] += 1

            logger.warning(f"Alert generated: {severity.value} - {component.value} - {message}")

            # Forward critical issues to the Singleton immediately (non-blocking)
            # so it can analyze and attempt recovery while the system continues
            # normal operation. Warnings can be handled on the next coordination
            # cycle via regular health checks.
            try:
                if self.singleton_callback and severity in {AlertSeverity.ERROR, AlertSeverity.CRITICAL}:
                    import asyncio

                    health_event = {
                        "event_type": "health_alert",
                        "severity": severity.value,
                        "component": component.value,
                        "message": message,
                        "timestamp": alert.timestamp.isoformat(),
                        "proposed_actions": []  # Recovery playbooks can enrich this later
                    }

                    # Fire-and-forget: do not block monitoring on Singleton processing
                    asyncio.create_task(self.singleton_callback(health_event))
            except Exception as callback_error:
                logger.error(f"Failed to forward health alert to Singleton: {callback_error}")

            # Trigger recovery if critical
            if severity == AlertSeverity.CRITICAL:
                await self._trigger_recovery(component, message)

            return alert_id

        except Exception as e:
            logger.error(f"Failed to generate alert: {e}")
            return ""

    async def _trigger_recovery(self, component: ComponentType, issue: str):
        """Hand a critical alert to the recovery manager.

        This LOGGED "Triggering recovery for X" and did nothing: the one call
        that would have acted was commented out, and it named
        `recover_component()`, a method RecoveryManager does not define -- so
        it could not simply be uncommented either. Every CRITICAL alert since
        has reported a recovery that was never attempted, which is worse than
        no recovery at all: the log is the only evidence anyone has, and it
        said the system had responded.

        `handle_failure` is the entry point. It classifies the failure, selects
        a strategy and records the attempt, which is what this path needs --
        an alert knows something is critical but not what the remedy is. The
        improvement cycle uses `execute_recovery_action` instead because it has
        already decided the remedy is a restart.
        """
        if not self.recovery_manager:
            logger.warning(
                "Critical alert on %s with no recovery manager attached; "
                "no recovery attempted: %s", component.value, issue)
            return

        try:
            from core.health.recovery_manager import FailureType

            result = await self.recovery_manager.handle_failure(
                failure_type=FailureType.COMPONENT_FAILURE,
                component=component.value,
                description=issue,
                severity="critical",
                metadata={"source": "monitoring_coordinator_alert"},
            )

            # REPORT WHAT HAPPENED, NOT THAT IT WAS ASKED FOR.
            if getattr(result, "success", False):
                logger.info("Recovery succeeded for %s: %s",
                            component.value, getattr(result, "actions_taken", None))
            else:
                logger.error("Recovery FAILED for %s: %s",
                             component.value, getattr(result, "message", None))

        except Exception as e:
            logger.error(f"Recovery trigger failed for {component.value}: {e}")

    async def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert"""
        if alert_id in self.active_alerts:
            self.active_alerts[alert_id].acknowledged = True
            logger.info(f"Alert acknowledged: {alert_id}")
            return True
        return False

    async def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert"""
        if alert_id in self.active_alerts:
            self.active_alerts[alert_id].resolved = True
            self.stats['alerts_resolved'] += 1
            logger.info(f"Alert resolved: {alert_id}")

            # Remove from active alerts
            del self.active_alerts[alert_id]
            return True
        return False

    async def get_system_health(self) -> SystemHealth:
        """Get current system health (without triggering new check)"""
        return self._aggregate_health()

    async def get_component_health(self, component: ComponentType) -> Optional[ComponentHealth]:
        """Get health of specific component"""
        return self.component_health.get(component)

    async def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts"""
        return list(self.active_alerts.values())

    def set_slack_notifier(self, notifier):
        """Set Slack notifier for sending health alerts"""
        self.slack_notifier = notifier
        logger.info("Slack notifier integration configured for monitoring coordinator")

    def set_autonomous_coordinator(self, coordinator):
        """Set autonomous coordinator for reporting health events"""
        self.autonomous_coordinator = coordinator
        logger.info("Autonomous coordinator integration configured for monitoring coordinator")

    def mark_startup_complete(self):
        """
        Mark system startup as complete, enabling alert generation.
        Call this after all services have initialized.
        """
        if not self._startup_complete:
            self._startup_complete = True
            logger.info("Health monitoring: startup marked complete by system - alerts now active")

    async def get_statistics(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        return {
            **self.stats,
            'is_monitoring': self.is_monitoring,
            'check_interval': self.check_interval,
            'active_alerts': len(self.active_alerts),
            'total_components': len(self.component_health)
        }


# Singleton instance
_monitoring_coordinator = None


def get_monitoring_coordinator() -> MonitoringCoordinator:
    """Get global monitoring coordinator instance"""
    global _monitoring_coordinator
    if _monitoring_coordinator is None:
        _monitoring_coordinator = MonitoringCoordinator()
    return _monitoring_coordinator


# CLI test
async def main():
    """Test monitoring coordinator"""
    logging.basicConfig(level=logging.INFO)

    coordinator = get_monitoring_coordinator()
    await coordinator.initialize()

    print("\n=== Monitoring Coordinator Test ===")

    # Check system health
    print("\nChecking system health...")
    health = await coordinator.check_system_health()
    print(f"Overall Status: {health.overall_status.value}")
    print(f"Healthy Components: {health.healthy_components}/{health.total_components}")
    print(f"Active Alerts: {health.active_alerts}")
    print(f"Critical Issues: {health.critical_issues}")

    # Show component status
    print("\nComponent Status:")
    for component_type, component_health in health.components.items():
        print(f"  {component_type.value}: {component_health.status.value}")
        if component_health.issues:
            for issue in component_health.issues:
                print(f"    - {issue}")

    # Get statistics
    print("\nStatistics:")
    stats = await coordinator.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
