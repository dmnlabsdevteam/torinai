#!/usr/bin/env python3
"""
TorinAI Autonomous Agents Module
Modular autonomous system with separated concerns for perception, planning, execution, and learning.
Simplified maintenance system with direct implementations.
"""

# Import modular autonomous system components
from .shared_types import (
    SystemMode, TaskType, TaskStatus, Priority,
    Task, Goal, Plan, PerceptionData, SystemState, LearningData
)

from .perception_manager import PerceptionManager
from .planning_engine import PlanningEngine
from .autonomous_coordinator import AutonomousCoordinator, create_autonomous_system

# Import cloud storage and cache sync integration (optional)
try:
    from .cloud_storage_integration import (
        register_cloud_storage_agent,
        initialize_cloud_storage_system,
        register_memory_sync_worker
    )
    CLOUD_STORAGE_AVAILABLE = True
except ImportError:
    CLOUD_STORAGE_AVAILABLE = False
    register_cloud_storage_agent = None
    initialize_cloud_storage_system = None
    register_memory_sync_worker = None

# Import simplified maintenance system (replaces 8+ interface files with 2 concrete classes)
try:
    from .maintenance_core import (
        CoreMaintenanceAgent,
        SystemGuardianAgent,
        MaintenanceIssue,
        MaintenancePriority,
        MaintenanceStatus
    )
    from .maintenance_manager import (
        MaintenanceManager,
        run_quick_maintenance,
        fix_file_issues,
        create_maintenance_manager
    )
    MAINTENANCE_AVAILABLE = True
except ImportError:
    MAINTENANCE_AVAILABLE = False
    CoreMaintenanceAgent = None
    SystemGuardianAgent = None
    MaintenanceIssue = None
    MaintenancePriority = None
    MaintenanceStatus = None
    MaintenanceManager = None
    run_quick_maintenance = None
    fix_file_issues = None
    create_maintenance_manager = None



from core.capability import CapabilityStatus

CLOUD_STORAGE_STATUS = (
    CapabilityStatus.ok("cloud_storage")
    if CLOUD_STORAGE_AVAILABLE
    else CapabilityStatus.missing("cloud_storage", "module cloud_storage_integration not present")
)
MAINTENANCE_STATUS = (
    CapabilityStatus.ok("maintenance")
    if MAINTENANCE_AVAILABLE
    else CapabilityStatus.missing("maintenance", "modules maintenance_core / maintenance_manager not present")
)

__all__ = [
    # Always present
    "AutonomousCoordinator",
    "create_autonomous_system",
    "get_autonomous_coordinator",
    # Explicit availability for the optional subsystems. The modules
    # maintenance_core / maintenance_manager / cloud_storage_integration do not
    # exist in this tree, so their 12 public names were bound to None and then
    # advertised in __all__ unconditionally -- the package promised what its own
    # AVAILABLE flags denied.
    "CLOUD_STORAGE_STATUS",
    "MAINTENANCE_STATUS",
    "CLOUD_STORAGE_AVAILABLE",
    "MAINTENANCE_AVAILABLE",
]

# Conditionally advertise the optional names ONLY when they really imported.
if CLOUD_STORAGE_AVAILABLE:
    __all__ += ["register_cloud_storage_agent", "initialize_cloud_storage_system",
                "register_memory_sync_worker"]
if MAINTENANCE_AVAILABLE:
    __all__ += ["CoreMaintenanceAgent", "SystemGuardianAgent", "MaintenanceIssue",
                "MaintenancePriority", "MaintenanceStatus", "MaintenanceManager",
                "run_quick_maintenance", "fix_file_issues", "create_maintenance_manager"]
