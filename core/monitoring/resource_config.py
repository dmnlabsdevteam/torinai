"""
Custom resource limits for TorinAI system
"""
from core.health.system_watchdog import ResourceLimits

# Custom limits for this system
TORIN_RESOURCE_LIMITS = ResourceLimits(
    max_cpu_percent=90.0,      # Allow higher CPU usage
    max_memory_gb=100.0,       # Raise memory limit per request
    max_operation_time=60,     # Keep strict timeout to prevent kernel panics
    check_interval=3.0         # More frequent monitoring
)
