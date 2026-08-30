#!/usr/bin/env python3
"""
TorinAI Monitoring Module
Distributed monitoring agents for model validation and coordination
"""

# Drift monitoring has been moved to core/learning/drift_monitoring/
# Import from new location for backwards compatibility
try:
    from core.learning.drift_monitoring import (
        Schema, load_csv, run_drift_report, summarize_drift, 
        evaluate_thresholds, write_alert, retrain_model,
        AutonomousMonitoringSystem, create_autonomous_monitoring_system
    )
except ImportError:
    # Provide deprecation warning
    import warnings
    warnings.warn(
        "Drift monitoring has moved to core.learning.drift_monitoring. "
        "Please update your imports.",
        DeprecationWarning,
        stacklevel=2
    )
    Schema = None
    load_csv = None
    run_drift_report = None
    summarize_drift = None
    evaluate_thresholds = None
    write_alert = None
    retrain_model = None
    AutonomousMonitoringSystem = None
    create_autonomous_monitoring_system = None

# core/monitoring/agents/ DOES NOT EXIST -- these four names could never be
# imported. They were bound to None and then listed unconditionally in __all__,
# so the package advertised four monitoring agents it does not have. Stated
# explicitly instead; nothing advertised may resolve to None.
from core.capability import CapabilityStatus

MONITORING_AGENTS_STATUS = CapabilityStatus.missing(
    "monitoring_agents",
    "core/monitoring/agents/ does not exist",
    expected=["ValidatorAgent", "DriftValidator", "CoordinatorAgent", "SanitizerAgent"],
)

__all__ = [
    # DEPRECATED - Use core.learning.drift_monitoring instead
    'Schema',
    'load_csv', 
    'run_drift_report',
    'summarize_drift',
    'evaluate_thresholds',
    'write_alert',
    'retrain_model',
    'AutonomousMonitoringSystem',
    'create_autonomous_monitoring_system',
    
    # Agent-based monitoring: NOT PRESENT. See MONITORING_AGENTS_STATUS.
    'MONITORING_AGENTS_STATUS',
]
