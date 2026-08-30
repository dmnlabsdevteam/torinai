#!/usr/bin/env python3
"""
Security Module
===============
TorinAI security and safety framework
"""

import os
import logging
from typing import Dict, Any, Optional

# Content Security
from core.security.content_security import (
    sanitize_input,
    validate_email,
    validate_url,
    check_malicious_patterns,
    sanitize_filename,
    MALICIOUS_PATTERNS,
    EMAIL_REGEX
)

# System Security
from core.security.system_security import (
    SystemSecurity,
    get_system_security,
    validate_input
)

# Malware Sandbox
from core.security.malware_sandbox import (
    MalwareSandbox,
    get_malware_sandbox,
    ThreatLevel,
    AnalysisType,
    SandboxReport
)

# Security Controller
from core.security.controller import (
    SecurityController,
    get_security_controller
)

# Active Defense Components
from core.security.threat_intelligence import ThreatIntelligenceEngine
from core.security.firewall_manager import RealTimeFirewallManager
from core.security.cloudflare_waf import CloudflareWAFManager
from core.security.threat_blocking import ThreatBlockingEngine
from core.security.active_defense_types import DefensePolicy, BlockDuration

logger = logging.getLogger(__name__)

# Singleton instance
_integrated_security_system: Optional[Dict[str, Any]] = None


def create_integrated_security_system(
    test_mode: bool = True,
    cloudflare_api_token: Optional[str] = None,
    cloudflare_zone_id: Optional[str] = None,
    abuseipdb_key: Optional[str] = None,
    virustotal_key: Optional[str] = None,
    otx_key: Optional[str] = None,
    use_singleton: bool = True
) -> Dict[str, Any]:
    """
    Create integrated security system with active defense components

    Production-ready security infrastructure combining:
    - Threat Intelligence (AbuseIPDB, VirusTotal, AlienVault OTX)
    - OS Firewall Management (iptables/pf)
    - Cloudflare WAF Integration
    - Coordinated Threat Blocking

    Args:
        test_mode: If True, firewall runs in dry-run mode (default: True for safety)
        cloudflare_api_token: Cloudflare API token (or set CLOUDFLARE_API_TOKEN env var)
        cloudflare_zone_id: Cloudflare zone ID (or set CLOUDFLARE_ZONE_ID env var)
        abuseipdb_key: AbuseIPDB API key (or set ABUSEIPDB_API_KEY env var)
        virustotal_key: VirusTotal API key (or set VIRUSTOTAL_API_KEY env var)
        otx_key: AlienVault OTX API key (or set OTX_API_KEY env var)
        use_singleton: Return singleton instance if already created

    Returns:
        Dictionary containing:
        - threat_intel: ThreatIntelligenceEngine
        - firewall: RealTimeFirewallManager
        - waf: CloudflareWAFManager (or None if no credentials)
        - threat_blocking: ThreatBlockingEngine
        - policy: DefensePolicy
        - test_mode: bool
    """
    global _integrated_security_system

    # Return singleton if requested and exists.
    #
    # A DIFFERING MODE IS A CONFLICT, NOT A PREFERENCE. Silently returning the
    # existing instance means a caller that asked for real enforcement gets
    # dry-run and cannot tell. Refusing the dangerous direction is the whole
    # point: better to fail at startup than to run unprotected while reporting
    # protection.
    if use_singleton and _integrated_security_system is not None:
        existing_mode = _integrated_security_system.get("test_mode")
        if existing_mode is not None and bool(existing_mode) != bool(test_mode):
            if not test_mode:
                raise RuntimeError(
                    "integrated security system already exists in dry-run mode "
                    "(test_mode=True) and cannot be upgraded to enforcement by "
                    "this call; whatever created it first decided the mode. "
                    "Call reset_integrated_security_system() before requesting "
                    "enforcement, or find the earlier creator."
                )
            logger.warning(
                "requested dry-run security but an enforcing system already "
                "exists; returning the enforcing one"
            )
        return _integrated_security_system

    # CHECK FOR EXTERNAL SECURITY SERVICES FIRST
    from pathlib import Path
    import json
    import aiohttp

    ports_file = Path(__file__).parent.parent.parent / "data" / "ports.json"
    external_services_available = False

    if ports_file.exists():
        try:
            with open(ports_file, 'r') as f:
                ports_data = json.load(f)
                security_ports = {k: v for k, v in ports_data.get('ports', {}).items() if k.startswith('security_')}

                if security_ports:
                    logger.info(f"Found external security services on ports: {security_ports}")
                    external_services_available = True

                    # Return external service endpoints instead of creating in-process objects
                    _integrated_security_system = {
                        'threat_intel': f"http://localhost:{security_ports.get('security_threat_intel')}",
                        'firewall': f"http://localhost:{security_ports.get('security_firewall')}",
                        'threat_blocking': f"http://localhost:{security_ports.get('security_threat_blocking')}",
                        'content_security': f"http://localhost:{security_ports.get('security_content')}",
                        'malware_sandbox': f"http://localhost:{security_ports.get('security_malware_sandbox')}",
                        'security_controller': f"http://localhost:{security_ports.get('security_controller')}",
                        'mode': 'external_services',
                        'test_mode': test_mode,
                        'policy': None  # External services manage their own policies
                    }

                    logger.info("✅ Using EXTERNAL security services (running as separate processes)")
                    logger.info(f"   Threat Intel:        {_integrated_security_system['threat_intel']}")
                    logger.info(f"   Firewall:            {_integrated_security_system['firewall']}")
                    logger.info(f"   Threat Blocking:     {_integrated_security_system['threat_blocking']}")
                    logger.info(f"   Security Controller: {_integrated_security_system['security_controller']}")

                    return _integrated_security_system
        except Exception as e:
            logger.warning(f"Failed to load external security services config: {e}")

    # FALLBACK: Create in-process security objects if external services not available
    logger.info(f"Creating IN-PROCESS integrated security system (test_mode={test_mode})")
    logger.info("  (To use external services, start them with: python start_security_systems.py)")

    # Load API keys from environment if not provided
    cloudflare_api_token = cloudflare_api_token or os.getenv("CLOUDFLARE_API_TOKEN")
    cloudflare_zone_id = cloudflare_zone_id or os.getenv("CLOUDFLARE_ZONE_ID")
    abuseipdb_key = abuseipdb_key or os.getenv("ABUSEIPDB_API_KEY")
    virustotal_key = virustotal_key or os.getenv("VIRUSTOTAL_API_KEY")
    otx_key = otx_key or os.getenv("OTX_API_KEY")

    # 1. Initialize Threat Intelligence Engine
    threat_intel = ThreatIntelligenceEngine(
        abuseipdb_key=abuseipdb_key,
        virustotal_key=virustotal_key,
        otx_key=otx_key,
        enable_caching=True,
        cache_ttl_seconds=3600
    )
    logger.info("✓ Threat Intelligence Engine initialized")

    # 2. Initialize Firewall Manager
    # NOTE: test_mode=True means dry-run (no actual OS firewall changes)
    # Set test_mode=False in production with root/sudo privileges to enable real blocking
    firewall_manager = RealTimeFirewallManager(test_mode=test_mode)
    if test_mode:
        logger.info("✓ Firewall Manager initialized (TEST MODE - dry run, no actual rules applied)")
    else:
        logger.info("✓ Firewall Manager initialized (PRODUCTION MODE - actual iptables/pf rules)")
        logger.warning("  ⚠️  Firewall in PRODUCTION mode - requires root privileges for OS firewall changes")

    # 3. Initialize WAF Manager (Cloudflare)
    waf_manager = None
    if cloudflare_api_token and cloudflare_zone_id:
        try:
            waf_manager = CloudflareWAFManager(
                api_token=cloudflare_api_token,
                zone_id=cloudflare_zone_id
            )
            logger.info("✓ Cloudflare WAF Manager initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Cloudflare WAF: {e}")
            waf_manager = None
    else:
        logger.info("⚠ Cloudflare WAF not initialized (missing API credentials)")

    # 4. Create Defense Policy
    defense_policy = DefensePolicy(
        policy_id="default_production",
        name="Production Defense Policy",
        enabled=True,
        block_threshold_score=0.75,  # Block if threat score >= 75%
        auto_block_enabled=True,
        auto_rate_limit_enabled=True,
        default_block_duration=BlockDuration.TEMPORARY_1H,
        use_threat_intel=True
    )
    logger.info("✓ Defense Policy created")

    # 5. Initialize Threat Blocking Engine (coordinates all components)
    threat_blocking = ThreatBlockingEngine(
        policy=defense_policy,
        threat_intel=threat_intel,
        firewall_manager=firewall_manager,
        waf_manager=waf_manager
    )
    logger.info("✓ Threat Blocking Engine initialized")

    # 6. Initialize Security Controller (central security coordination)
    security_controller = get_security_controller()
    logger.info("✓ Security Controller initialized")

    # Build system dict
    system = {
        "threat_intel": threat_intel,
        "firewall": firewall_manager,
        "waf": waf_manager,
        "threat_blocking": threat_blocking,
        "security_controller": security_controller,
        "policy": defense_policy,
        "test_mode": test_mode,
        "has_waf": waf_manager is not None,
        "has_threat_intel_keys": bool(abuseipdb_key or virustotal_key or otx_key)
    }

    # Store singleton
    if use_singleton:
        _integrated_security_system = system

    logger.info("Integrated security system ready")
    logger.info(f"  - Threat Intelligence: {'✓' if system['has_threat_intel_keys'] else '⚠ (no API keys)'}")
    logger.info(f"  - Firewall: ✓ (test mode)")
    logger.info(f"  - WAF: {'✓' if system['has_waf'] else '⚠ (no credentials)'}")
    logger.info(f"  - Threat Blocking: ✓")

    return system


def get_integrated_security_system() -> Optional[Dict[str, Any]]:
    """Return the integrated security system if one has been created, else None.

    THIS USED TO CREATE ONE, HARDCODED TO test_mode=True -- dry-run, no actual
    OS firewall changes. Its only callers are read-only observers (the security
    audit worker and two health checks), so an observer merely LOOKING at
    security could construct the process-wide singleton in dry-run mode. Every
    later call, including the production initialisation in `core/main.py` that
    passes `test_mode=False` and the real API keys, then hit the
    `use_singleton` early-return and got the dry-run instance back with all its
    arguments discarded -- while logging "Firewall PRODUCTION MODE - real
    iptables/pf rules will be applied".

    Enforcement mode was therefore decided by initialisation ORDER, silently.
    An observer now observes: if nothing has created the system, that is what
    it reports.
    """
    return _integrated_security_system


def reset_integrated_security_system():
    """Reset the singleton instance (useful for testing)"""
    global _integrated_security_system
    _integrated_security_system = None
    logger.info("Integrated security system reset")


# Expose key functions and classes
__all__ = [
    # Content Security
    'sanitize_input',
    'validate_email',
    'validate_url',
    'check_malicious_patterns',
    'sanitize_filename',
    'MALICIOUS_PATTERNS',
    'EMAIL_REGEX',

    # System Security
    'SystemSecurity',
    'get_system_security',
    'validate_input',

    # Malware Sandbox
    'MalwareSandbox',
    'get_malware_sandbox',
    'ThreatLevel',
    'AnalysisType',
    'SandboxReport',

    # Security Controller
    'SecurityController',
    'get_security_controller',

    # Integrated Security System
    'create_integrated_security_system',
    'get_integrated_security_system',
    'reset_integrated_security_system',

    # Active Defense Components
    'ThreatIntelligenceEngine',
    'RealTimeFirewallManager',
    'CloudflareWAFManager',
    'ThreatBlockingEngine',
    'DefensePolicy',
]

# Version
__version__ = '1.0.0'
