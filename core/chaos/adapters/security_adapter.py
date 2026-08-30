#!/usr/bin/env python3
"""
Security System Chaos Adapter
==============================

Chaos injection for the security system.

Targets:
- Cloudflare WAF integration
- Malware sandbox
- Threat intelligence
- Security scanning
- Vulnerability detection
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from .base_adapter import TargetSystemAdapter
from ..types import InjectionHandle, ChaosType
from ..context_managers import ChaosContext

logger = logging.getLogger(__name__)


class SecuritySystemAdapter(TargetSystemAdapter):
    """
    Chaos adapter for the security system.

    Injection Points:
    - cloudflare_waf.check_request: WAF latency spikes
    - malware_sandbox.analyze: Sandbox crashes
    - threat_intelligence.lookup: Threat lookup failures
    - vulnerability_scanner.scan: Scanner errors
    """

    def __init__(self):
        super().__init__("security_system")
        self.injection_points = {
            "waf_check": "cloudflare_waf",
            "sandbox_analysis": "malware_sandbox",
            "threat_lookup": "threat_intelligence",
            "vulnerability_scan": "vulnerability_scanner"
        }

    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into security system operations.

        Examples:
        - component="cloudflare_waf", injection_point="check_request"
        - component="malware_sandbox", injection_point="file_analysis"
        """
        injection_id = f"security_latency_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.LATENCY,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Security latency injection: {component}.{injection_point} "
            f"({delay_ms}ms ± {jitter_ms}ms, experiment: {target_id})"
        )

        return handle

    async def inject_error(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        error_type: str,
        error_rate: float
    ) -> InjectionHandle:
        """
        Inject errors into security system operations.

        Examples:
        - component="malware_sandbox", error_type="SandboxCrash"
        - component="threat_intelligence", error_type="ThreatLookupTimeout"
        """
        injection_id = f"security_error_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.ERROR,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Security error injection: {component}.{injection_point} "
            f"({error_type} at {error_rate*100}% rate, experiment: {target_id})"
        )

        return handle

    async def inject_resource_exhaustion(
        self,
        target_id: str,
        component: str,
        resource_type: str,
        limit_value: Optional[float] = None
    ) -> InjectionHandle:
        """
        Inject resource exhaustion into security system.

        Examples:
        - resource_type="sandbox_capacity" (sandbox instances exhausted)
        - resource_type="waf_rate_limit" (WAF rate limits)
        """
        injection_id = f"security_resource_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        injection_point = f"{resource_type}_exhaustion"
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.RESOURCE_EXHAUSTION,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Security resource exhaustion: {component}.{resource_type} "
            f"(experiment: {target_id})"
        )

        return handle

    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get health metrics for security system.

        Metrics:
        - waf_check_latency_p95: WAF check latency
        - malware_scan_success_rate: Sandbox scan success rate
        - threat_detection_rate: Threat detection effectiveness
        - false_positive_rate: False positive rate
        """
        # In production, these would come from actual monitoring
        metrics = {
            "waf_check_latency_p95": 50.0,  # ms
            "waf_check_latency_p99": 100.0,  # ms
            "malware_scan_success_rate": 0.99,  # 99%
            "threat_detection_rate": 0.95,  # 95%
            "false_positive_rate": 0.01,  # 1%
            "active_sandbox_instances": len(self.active_injections),
            "waf_requests_per_second": 1000,
            "healthy": True
        }

        # Mark as unhealthy if latency is high or detection rate is low
        if metrics["waf_check_latency_p95"] > 200 or metrics["threat_detection_rate"] < 0.8:
            metrics["healthy"] = False

        return metrics

    async def cleanup(self):
        """
        Clean up all active chaos injections for security system.
        """
        logger.info(f"Cleaning up {len(self.active_injections)} security system injections")

        # Disable all chaos contexts
        for injection_id, handle in list(self.active_injections.items()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Disable all chaos for security system components
        await ChaosContext.disable_all()

        logger.info("Security system chaos cleanup complete")


# Singleton instance
_security_adapter = None


def get_security_adapter() -> SecuritySystemAdapter:
    """Get global security system adapter instance"""
    global _security_adapter
    if _security_adapter is None:
        _security_adapter = SecuritySystemAdapter()
    return _security_adapter
