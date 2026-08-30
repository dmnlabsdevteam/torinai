"""
Health management interfaces for system monitoring and recovery
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from enum import Enum


class HealthStatus(Enum):
    """System health status levels"""
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
class HealthMetric:
    """Health metric data"""
    name: str
    value: Any
    status: HealthStatus
    timestamp: float
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SystemAlert:
    """System alert data"""
    alert_id: str
    severity: AlertSeverity
    message: str
    component: str
    timestamp: float
    resolved: bool = False


class IHealthMonitor(ABC):
    """Interface for health monitoring"""
    
    @abstractmethod
    async def collect_metrics(self) -> List[HealthMetric]:
        """Collect system health metrics"""
        pass
    
    @abstractmethod
    async def check_component_health(self, component: str) -> HealthStatus:
        """Check health of specific component"""
        pass
    
    @abstractmethod
    async def get_system_status(self) -> HealthStatus:
        """Get overall system health status"""
        pass
    
    @abstractmethod
    async def generate_alert(self, severity: AlertSeverity, message: str, component: str) -> str:
        """Generate a system alert"""
        pass


class IRecoveryManager(ABC):
    """Interface for system recovery management"""
    
    @abstractmethod
    async def assess_recovery_options(self, issue: str) -> List[str]:
        """Assess available recovery options for an issue"""
        pass
    
    @abstractmethod
    async def execute_recovery_action(self, action: str, parameters: Dict[str, Any]) -> bool:
        """Execute a recovery action"""
        pass
    
    @abstractmethod
    async def verify_recovery(self, component: str) -> bool:
        """Verify that recovery was successful"""
        pass
    
    @abstractmethod
    async def rollback_recovery(self, action_id: str) -> bool:
        """Rollback a recovery action if it failed"""
        pass


class IHealthManager(ABC):
    """Main health manager interface"""
    
    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the health manager"""
        pass
    
    @abstractmethod
    async def start_monitoring(self) -> bool:
        """Start health monitoring"""
        pass
    
    @abstractmethod
    async def stop_monitoring(self) -> bool:
        """Stop health monitoring"""
        pass
    
    @abstractmethod
    async def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report"""
        pass
    
    @abstractmethod
    async def handle_health_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Handle health-related events"""
        pass
    
    @abstractmethod
    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        pass
    
    @abstractmethod
    async def apply_health_recommendation(self, recommendation: Dict[str, Any]) -> bool:
        """Apply a health improvement recommendation"""
        pass
    
    @abstractmethod
    async def schedule_maintenance(self, maintenance_type: str, schedule: Dict[str, Any]) -> str:
        """Schedule system maintenance"""
        pass