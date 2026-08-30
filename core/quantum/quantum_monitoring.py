#!/usr/bin/env python3
"""
Quantum Computing Monitoring and Statistics
Provides comprehensive monitoring and health tracking for quantum operations
"""

import asyncio
import logging
import json
import time
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from collections import defaultdict, deque

# Import health monitoring system
try:
    from core.health.health_monitor import HealthMonitor
    from data.databases.health_monitoring import HealthDatabase
except ImportError:
    # Fallback in case of import issues
    HealthMonitor = None
    HealthDatabase = None

# Import quantum components
from .quantum_factory import get_quantum_capabilities, quantum_health_check
from .quantum_learning_bridge import get_quantum_learning_bridge
from .quantum_reasoning_bridge import get_quantum_reasoning_bridge
from .asi_quantum_safety import get_asi_quantum_safety

logger = logging.getLogger(__name__)


@dataclass
class QuantumPerformanceMetrics:
    """Quantum computing performance metrics"""
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    average_execution_time: float = 0.0
    quantum_vs_classical_ratio: float = 0.0
    quantum_advantage_score: float = 1.0
    hardware_utilization: float = 0.0
    error_rate: float = 0.0
    timestamp: str = ""


@dataclass
class QuantumHealthStatus:
    """Overall quantum system health status"""
    system_operational: bool = True
    quantum_hardware_available: bool = False
    safety_systems_active: bool = True
    performance_score: float = 1.0
    last_health_check: str = ""
    active_quantum_jobs: int = 0
    quantum_error_rate: float = 0.0
    recommendations: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []


@dataclass
class QuantumUsageStatistics:
    """Quantum computing usage statistics"""
    learning_enhancement_usage: int = 0
    reasoning_acceleration_usage: int = 0
    optimization_tasks: int = 0
    safety_assessments: int = 0
    total_quantum_circuits_executed: int = 0
    total_classical_fallbacks: int = 0
    average_quantum_speedup: float = 1.0
    most_used_algorithms: Optional[Dict[str, int]] = None
    
    def __post_init__(self):
        if self.most_used_algorithms is None:
            self.most_used_algorithms = {}


class QuantumMonitoringSystem:
    """Comprehensive quantum computing monitoring system"""
    
    def __init__(self):
        self.health_monitor: Optional[Any] = None
        self.system_monitor: Optional[Any] = None
        
        # Performance tracking
        self.performance_history: deque = deque(maxlen=1000)
        self.operation_logs: deque = deque(maxlen=5000)
        
        # Real-time metrics
        self.current_metrics = QuantumPerformanceMetrics()
        self.health_status = QuantumHealthStatus()
        self.usage_stats = QuantumUsageStatistics()
        
        # Monitoring configuration
        self.monitoring_interval = 30.0  # seconds
        self.health_check_interval = 300.0  # 5 minutes
        self.performance_window = 3600.0  # 1 hour for performance calculations
        
        # Tracking containers
        self.operation_timings: deque = deque(maxlen=100)
        self.quantum_advantages: deque = deque(maxlen=100)
        self.error_rates: deque = deque(maxlen=100)
        
        # Monitoring task
        #: Whether the monitoring loops are actually running. Set True only
        #: once they are started and flipped back the moment one exits, so
        #: nothing can report monitoring it is not doing.
        self.monitoring_active: bool = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        
    def _on_loop_exit(self, task, name: str) -> None:
        """A monitoring loop that stopped must stop the claim that it is running."""
        if task.cancelled():
            logger.info("Quantum monitoring loop %s cancelled", name)
            return
        error = task.exception()
        if error is not None:
            self.monitoring_active = False
            logger.error("Quantum monitoring loop %s DIED: %s: %s",
                         name, type(error).__name__, error, exc_info=error)
        else:
            self.monitoring_active = False
            logger.warning("Quantum monitoring loop %s exited; monitoring is "
                           "no longer running", name)

    async def initialize(self) -> bool:
        """Initialize quantum monitoring system"""
        try:
            # Connect to health monitoring system (use singleton)
            if HealthMonitor:
                from core.health.health_monitor import get_health_monitor
                self.health_monitor = get_health_monitor()
                if hasattr(self.health_monitor, 'initialize'):
                    await self.health_monitor.initialize()
            
            # Note: SystemMonitor has been consolidated into health monitoring
            # Use health_monitor for system-level monitoring
            
            # Start monitoring tasks. create_task RETURNS IMMEDIATELY, so a
            # loop that raises on its first line dies silently while this
            # reports monitoring as initialized -- and an unretrieved task
            # exception is only surfaced when the task is garbage collected.
            # The done-callback makes the failure loud and flips the flag, so
            # "monitoring is running" cannot outlive the loop that runs it.
            self._monitoring_task = asyncio.create_task(self._monitoring_loop())
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            for task, name in ((self._monitoring_task, "_monitoring_loop"),
                               (self._health_check_task, "_health_check_loop")):
                task.add_done_callback(
                    lambda t, n=name: self._on_loop_exit(t, n))

            self.monitoring_active = True
            logger.info("Quantum monitoring system initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize quantum monitoring: {e}")
            return False
    
    async def record_quantum_operation(self, 
                                     operation_type: str,
                                     execution_time: float,
                                     success: bool,
                                     quantum_used: bool,
                                     quantum_advantage: float = 1.0,
                                     error_details: Optional[str] = None) -> None:
        """Record quantum operation for monitoring"""
        
        operation_record = {
            'timestamp': datetime.now().isoformat(),
            'operation_type': operation_type,
            'execution_time': execution_time,
            'success': success,
            'quantum_used': quantum_used,
            'quantum_advantage': quantum_advantage,
            'error_details': error_details
        }
        
        # Add to operation logs
        self.operation_logs.append(operation_record)
        
        # Update performance metrics
        await self._update_performance_metrics(operation_record)
        
        # Update usage statistics
        await self._update_usage_statistics(operation_type, quantum_used)
        
        # Log performance data
        if self.health_monitor:
            try:
                await self._log_to_health_monitor(operation_record)
            except Exception as e:
                logger.warning(f"Failed to log to health monitor: {e}")
    
    async def _update_performance_metrics(self, operation_record: Dict[str, Any]) -> None:
        """Update real-time performance metrics"""
        
        # Update operation counts
        self.current_metrics.total_operations += 1
        
        if operation_record['success']:
            self.current_metrics.successful_operations += 1
        else:
            self.current_metrics.failed_operations += 1
        
        # Update timing metrics
        self.operation_timings.append(operation_record['execution_time'])
        if self.operation_timings:
            self.current_metrics.average_execution_time = float(np.mean(self.operation_timings))
        
        # Update quantum advantage tracking
        if operation_record['quantum_used']:
            self.quantum_advantages.append(operation_record['quantum_advantage'])
            if self.quantum_advantages:
                self.current_metrics.quantum_advantage_score = float(np.mean(self.quantum_advantages))
        
        # Update quantum vs classical ratio
        total_ops = self.current_metrics.total_operations
        quantum_ops = sum(1 for log in list(self.operation_logs)[-100:] if log.get('quantum_used', False))
        self.current_metrics.quantum_vs_classical_ratio = quantum_ops / max(1, min(100, total_ops))
        
        # Update error rate
        recent_ops = list(self.operation_logs)[-50:]  # Last 50 operations
        if recent_ops:
            failed_ops = sum(1 for op in recent_ops if not op['success'])
            self.current_metrics.error_rate = failed_ops / len(recent_ops)
        
        # Update timestamp
        self.current_metrics.timestamp = datetime.now().isoformat()
    
    async def _update_usage_statistics(self, operation_type: str, quantum_used: bool) -> None:
        """Update usage statistics"""
        
        # Track by operation type
        if 'learning' in operation_type.lower():
            self.usage_stats.learning_enhancement_usage += 1
        elif 'reasoning' in operation_type.lower():
            self.usage_stats.reasoning_acceleration_usage += 1
        elif 'optimization' in operation_type.lower():
            self.usage_stats.optimization_tasks += 1
        elif 'safety' in operation_type.lower():
            self.usage_stats.safety_assessments += 1
        
        # Track quantum vs classical
        if quantum_used:
            self.usage_stats.total_quantum_circuits_executed += 1
        else:
            self.usage_stats.total_classical_fallbacks += 1
        
        # Update algorithm usage
        if self.usage_stats.most_used_algorithms is None:
            self.usage_stats.most_used_algorithms = {}
        
        if operation_type in self.usage_stats.most_used_algorithms:
            self.usage_stats.most_used_algorithms[operation_type] += 1
        else:
            self.usage_stats.most_used_algorithms[operation_type] = 1
        
        # Update average speedup
        if self.quantum_advantages:
            self.usage_stats.average_quantum_speedup = float(np.mean(self.quantum_advantages))
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop"""
        while True:
            try:
                await asyncio.sleep(self.monitoring_interval)
                
                # Collect performance data
                await self._collect_performance_data()
                
                # Check for anomalies
                await self._detect_performance_anomalies()
                
                # Update health status
                await self._update_health_status()
                
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
    
    async def _health_check_loop(self) -> None:
        """Health check loop"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                
                # Perform comprehensive health check
                await self._perform_health_check()
                
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
    
    async def _collect_performance_data(self) -> None:
        """Collect and store performance data"""
        
        # Create performance snapshot
        performance_snapshot = QuantumPerformanceMetrics(
            total_operations=self.current_metrics.total_operations,
            successful_operations=self.current_metrics.successful_operations,
            failed_operations=self.current_metrics.failed_operations,
            average_execution_time=self.current_metrics.average_execution_time,
            quantum_vs_classical_ratio=self.current_metrics.quantum_vs_classical_ratio,
            quantum_advantage_score=self.current_metrics.quantum_advantage_score,
            hardware_utilization=self.current_metrics.hardware_utilization,
            error_rate=self.current_metrics.error_rate,
            timestamp=datetime.now().isoformat()
        )
        
        # Add to history
        self.performance_history.append(performance_snapshot)
    
    async def _detect_performance_anomalies(self) -> None:
        """Detect performance anomalies and alerts"""
        
        alerts = []
        
        # High error rate
        if self.current_metrics.error_rate > 0.1:
            alerts.append(f"High quantum error rate: {self.current_metrics.error_rate:.2%}")
        
        # Low quantum advantage
        if self.current_metrics.quantum_advantage_score < 1.1:
            alerts.append(f"Low quantum advantage: {self.current_metrics.quantum_advantage_score:.2f}")
        
        # Slow execution times
        if self.current_metrics.average_execution_time > 30.0:
            alerts.append(f"Slow quantum execution: {self.current_metrics.average_execution_time:.1f}s avg")
        
        # Few quantum operations
        if self.current_metrics.quantum_vs_classical_ratio < 0.1:
            alerts.append(f"Low quantum usage: {self.current_metrics.quantum_vs_classical_ratio:.2%}")
        
        # Log alerts
        for alert in alerts:
            logger.warning(f"Quantum performance alert: {alert}")
    
    async def _update_health_status(self) -> None:
        """Update overall health status"""
        
        # Check system operational status
        success_rate = (self.current_metrics.successful_operations / 
                       max(1, self.current_metrics.total_operations))
        self.health_status.system_operational = success_rate > 0.8
        
        # Check error rate
        self.health_status.quantum_error_rate = self.current_metrics.error_rate
        
        # Calculate performance score
        performance_factors = [
            success_rate,
            1.0 - min(1.0, self.current_metrics.error_rate),
            min(1.0, self.current_metrics.quantum_advantage_score / 2.0),
            min(1.0, self.current_metrics.quantum_vs_classical_ratio * 2.0)
        ]
        self.health_status.performance_score = float(np.mean(performance_factors))
        
        # Update timestamp
        self.health_status.last_health_check = datetime.now().isoformat()
        
        # Generate recommendations
        self.health_status.recommendations = self._generate_health_recommendations()
    
    async def _perform_health_check(self) -> None:
        """Perform comprehensive quantum health check"""
        
        try:
            # Check quantum capabilities
            capabilities = get_quantum_capabilities()
            self.health_status.quantum_hardware_available = capabilities.get('hardware_available', False)
            
            # Perform quantum system health check
            health_check_result = await quantum_health_check()
            
            # Update health status based on check
            if health_check_result:
                self.health_status.system_operational = health_check_result.get('system_healthy', True)
                self.health_status.active_quantum_jobs = health_check_result.get('active_jobs', 0)
            
            # Check subsystem health
            await self._check_subsystem_health()
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.health_status.system_operational = False
    
    async def _check_subsystem_health(self) -> None:
        """Check health of quantum subsystems"""
        
        try:
            # Check learning bridge
            learning_bridge = await get_quantum_learning_bridge()
            learning_summary = learning_bridge.get_performance_summary()
            
            # Check reasoning bridge
            reasoning_bridge = await get_quantum_reasoning_bridge()
            reasoning_summary = reasoning_bridge.get_reasoning_performance_summary()
            
            # Check ASI safety
            asi_safety = await get_asi_quantum_safety()
            safety_summary = asi_safety.get_safety_summary()
            
            # Update subsystem health information
            self.health_status.safety_systems_active = (
                safety_summary.get('total_assessments', 0) > 0 and
                safety_summary.get('safety_rate', 0) > 80.0
            )
            
        except Exception as e:
            logger.warning(f"Subsystem health check failed: {e}")
    
    def _generate_health_recommendations(self) -> List[str]:
        """Generate health recommendations"""
        
        recommendations = []
        
        if self.health_status.quantum_error_rate > 0.1:
            recommendations.append("High error rate detected - check quantum hardware calibration")
        
        if self.current_metrics.quantum_advantage_score < 1.2:
            recommendations.append("Low quantum advantage - consider algorithm optimization")
        
        if self.current_metrics.quantum_vs_classical_ratio < 0.2:
            recommendations.append("Low quantum usage - review task routing policies")
        
        if not self.health_status.quantum_hardware_available:
            recommendations.append("Quantum hardware unavailable - using simulation mode")
        
        if self.health_status.performance_score < 0.7:
            recommendations.append("System performance below optimal - review quantum configurations")
        
        if not recommendations:
            recommendations.append("Quantum system operating within normal parameters")
        
        return recommendations
    
    async def _log_to_health_monitor(self, operation_record: Dict[str, Any]) -> None:
        """Log quantum operation to health monitoring system"""
        
        if not self.health_monitor:
            return
        
        health_data = {
            'component': 'quantum_computing',
            'metrics': {
                'operation_type': operation_record['operation_type'],
                'execution_time': operation_record['execution_time'],
                'success': operation_record['success'],
                'quantum_used': operation_record['quantum_used'],
                'quantum_advantage': operation_record['quantum_advantage']
            },
            'timestamp': operation_record['timestamp']
        }
        
        # Log to health monitor if method exists
        if hasattr(self.health_monitor, 'log_component_health'):
            await self.health_monitor.log_component_health(health_data)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary"""
        
        # Calculate trends
        recent_performance = list(self.performance_history)[-10:] if self.performance_history else []
        
        trends = {}
        if len(recent_performance) > 1:
            trends = {
                'error_rate_trend': self._calculate_trend([p.error_rate for p in recent_performance]),
                'quantum_advantage_trend': self._calculate_trend([p.quantum_advantage_score for p in recent_performance]),
                'execution_time_trend': self._calculate_trend([p.average_execution_time for p in recent_performance])
            }
        
        return {
            'current_metrics': asdict(self.current_metrics),
            'health_status': asdict(self.health_status),
            'usage_statistics': asdict(self.usage_stats),
            'performance_trends': trends,
            'total_operations_logged': len(self.operation_logs),
            'monitoring_uptime': self._get_monitoring_uptime(),
            'last_update': datetime.now().isoformat()
        }
    
    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction"""
        if len(values) < 2:
            return "stable"
        
        recent_avg = np.mean(values[-3:]) if len(values) >= 3 else values[-1]
        earlier_avg = np.mean(values[:-3]) if len(values) >= 6 else values[0]
        
        change_percent = (recent_avg - earlier_avg) / max(abs(earlier_avg), 0.001) * 100
        
        if change_percent > 5:
            return "increasing"
        elif change_percent < -5:
            return "decreasing"
        else:
            return "stable"
    
    def _get_monitoring_uptime(self) -> str:
        """Get monitoring system uptime"""
        if self._monitoring_task and not self._monitoring_task.done():
            # In a real implementation, would track actual start time
            return "active"
        else:
            return "inactive"
    
    async def shutdown(self) -> None:
        """Shutdown monitoring system"""
        try:
            if self._monitoring_task:
                self._monitoring_task.cancel()
            
            if self._health_check_task:
                self._health_check_task.cancel()
            
            logger.info("Quantum monitoring system shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during monitoring shutdown: {e}")


# Global quantum monitoring instance
_quantum_monitoring: Optional[QuantumMonitoringSystem] = None


async def get_quantum_monitoring() -> QuantumMonitoringSystem:
    """Get global quantum monitoring system instance"""
    global _quantum_monitoring
    
    if _quantum_monitoring is None:
        _quantum_monitoring = QuantumMonitoringSystem()
        await _quantum_monitoring.initialize()
    
    return _quantum_monitoring


async def record_quantum_operation(operation_type: str,
                                 execution_time: float,
                                 success: bool,
                                 quantum_used: bool,
                                 quantum_advantage: float = 1.0,
                                 error_details: Optional[str] = None) -> None:
    """Record quantum operation for monitoring"""
    monitoring = await get_quantum_monitoring()
    await monitoring.record_quantum_operation(
        operation_type, execution_time, success, quantum_used, quantum_advantage, error_details
    )


async def get_quantum_health_status() -> QuantumHealthStatus:
    """Get current quantum system health status"""
    monitoring = await get_quantum_monitoring()
    return monitoring.health_status


async def get_quantum_performance_summary() -> Dict[str, Any]:
    """Get comprehensive quantum performance summary"""
    monitoring = await get_quantum_monitoring()
    return monitoring.get_performance_summary()


def inject_quantum_monitoring_into_system():
    """Inject quantum monitoring into Torin's monitoring systems"""
    try:
        logger.info("Injecting quantum monitoring into system monitoring")
        
        # In a full implementation, this would integrate with existing health monitoring
        # to provide quantum-specific metrics and alerts
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to inject quantum monitoring: {e}")
        return False


__all__ = [
    'QuantumPerformanceMetrics', 'QuantumHealthStatus', 'QuantumUsageStatistics',
    'QuantumMonitoringSystem', 'get_quantum_monitoring', 'record_quantum_operation',
    'get_quantum_health_status', 'get_quantum_performance_summary',
    'inject_quantum_monitoring_into_system'
]