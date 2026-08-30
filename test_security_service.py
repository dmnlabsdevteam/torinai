#!/usr/bin/env python3
"""
Simple test for security systems
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.utils.port_manager import get_port_manager
from core.security.threat_intelligence import ThreatIntelligenceEngine
from core.security.firewall_manager import RealTimeFirewallManager
from core.security.threat_blocking import ThreatBlockingEngine
from core.security.active_defense_types import DefensePolicy
from core.security.content_security import ContentSecurityScanner

async def test():
    print("Testing security systems initialization...\n")

    # Test 1: ThreatIntelligenceEngine
    print("1. ThreatIntelligenceEngine...")
    try:
        threat_intel = ThreatIntelligenceEngine()
        print("   ✅ Created successfully")
        stats = threat_intel.get_statistics()
        print(f"   Stats: {stats}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 2: RealTimeFirewallManager
    print("\n2. RealTimeFirewallManager...")
    try:
        firewall = RealTimeFirewallManager(test_mode=True)
        print("   ✅ Created successfully")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 3: ThreatBlockingEngine
    print("\n3. ThreatBlockingEngine...")
    try:
        policy = DefensePolicy()
        threat_blocking = ThreatBlockingEngine(
            firewall_manager=firewall,
            waf_manager=None,
            policy=policy
        )
        print("   ✅ Created successfully")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 4: ContentSecurityScanner
    print("\n4. ContentSecurityScanner...")
    try:
        content_security = ContentSecurityScanner()
        print("   ✅ Created successfully")
        result = content_security.scan_content("Hello world")
        print(f"   Test scan: {result}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 5: PortManager
    print("\n5. PortManager...")
    try:
        port_manager = get_port_manager()
        port = port_manager.allocate_port("test_service", port_range=(8400, 8500))
        print(f"   ✅ Allocated port: {port}")
        port_manager.release_port("test_service")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(test())
