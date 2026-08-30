#!/usr/bin/env python3
"""Direct test of chaos adapters without pytest."""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root to path (script is in tests/chaos/, so go up 2 levels)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.chaos.adapters.memory_adapter import MemorySystemAdapter
from core.chaos.adapters.agent_adapter import AgentSystemAdapter
from core.chaos.adapters.monitoring_adapter import MonitoringSystemAdapter
from core.chaos.adapters.intelligence_adapter import IntelligenceSystemAdapter
from core.chaos.adapters.services_adapter import ServicesSystemAdapter
from core.chaos.injection_engine import ChaosInjectionEngine


# NOT a pytest test: it takes an adapter and a name, and main() drives it over
# every adapter. Named `test_adapter` it was collected anyway, and pytest tried
# to resolve both arguments as fixtures -- a collection error that reported this
# file as broken while the script itself worked fine. Adapter coverage under
# pytest lives in tests/chaos/test_adapters.py.
async def check_adapter(adapter, adapter_name):
    """Exercise one chaos adapter end to end."""
    print(f"\n{adapter_name} Adapter Test:")
    print("=" * 50)

    try:
        # Test latency injection
        print(f"  Testing latency injection...")
        handle = await adapter.inject_latency(
            target_id="test_exp_001",
            component="test_component",
            injection_point="test_point",
            delay_ms=100,
            jitter_ms=10
        )
        assert handle is not None, "Latency injection returned None"
        assert handle.active, "Injection handle not active"
        print(f"  ✓ Latency injection successful: {handle.injection_id}")

        # Test error injection
        print(f"  Testing error injection...")
        handle2 = await adapter.inject_error(
            target_id="test_exp_002",
            component="test_component",
            injection_point="test_point",
            error_type="TestError",
            error_rate=0.5
        )
        assert handle2 is not None, "Error injection returned None"
        assert handle2.active, "Error injection handle not active"
        print(f"  ✓ Error injection successful: {handle2.injection_id}")

        # Test resource exhaustion
        print(f"  Testing resource exhaustion...")
        handle3 = await adapter.inject_resource_exhaustion(
            target_id="test_exp_003",
            component="test_component",
            resource_type="cpu"
        )
        assert handle3 is not None, "Resource exhaustion returned None"
        assert handle3.active, "Resource exhaustion handle not active"
        print(f"  ✓ Resource exhaustion successful: {handle3.injection_id}")

        # Test health metrics
        print(f"  Testing health metrics...")
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict), "Metrics not a dict"
        assert "healthy" in metrics, "Missing 'healthy' field in metrics"
        assert "active_chaos_injections" in metrics, "Missing injection count"
        print(f"  ✓ Health metrics retrieved: {metrics.get('active_chaos_injections', 0)} active injections")

        # Test cleanup
        print(f"  Testing cleanup...")
        await adapter.cleanup()
        metrics_after = await adapter.get_health_metrics()
        assert metrics_after.get("active_chaos_injections", 0) == 0, "Cleanup didn't clear injections"
        print(f"  ✓ Cleanup successful")

        print(f"\n✅ {adapter_name} adapter: ALL TESTS PASSED")
        return True

    except Exception as e:
        print(f"\n❌ {adapter_name} adapter FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


@pytest.mark.asyncio
async def test_injection_engine():
    """Test the injection engine loads all adapters."""
    print("\n\nInjection Engine Test:")
    print("=" * 50)

    try:
        engine = ChaosInjectionEngine()

        # Check all 10 systems loaded
        expected_systems = [
            "tool_system",
            "learning_system",
            "security_system",
            "reasoning_system",
            "autonomous_agents",
            "domain_system",
            "memory_system",
            "intelligence_system",
            "monitoring_system",
            "services_system"
        ]

        for system in expected_systems:
            assert system in engine.adapters, f"Missing adapter: {system}"
            print(f"  ✓ {system} adapter loaded")

        print(f"\n✅ Injection Engine: ALL 10 ADAPTERS LOADED")
        return True

    except Exception as e:
        print(f"\n❌ Injection Engine FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("=" * 70)
    print("CHAOS FRAMEWORK DIRECT ADAPTER TEST")
    print("=" * 70)

    results = []

    # Test each adapter
    adapters = [
        (MemorySystemAdapter(), "Memory"),
        (AgentSystemAdapter(), "Agent"),
        (MonitoringSystemAdapter(), "Monitoring"),
        (IntelligenceSystemAdapter(), "Intelligence"),
        (ServicesSystemAdapter(), "Services")
    ]

    for adapter, name in adapters:
        result = await check_adapter(adapter, name)
        results.append((name, result))

    # Test injection engine
    engine_result = await test_injection_engine()
    results.append(("Injection Engine", engine_result))

    # Summary
    print("\n\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {name:20} {status}")

    print(f"\nTotal: {passed}/{total} passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
