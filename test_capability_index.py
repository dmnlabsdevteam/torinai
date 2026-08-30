#!/usr/bin/env python3
"""Quick test to check if capability index is being built"""

from core.tools import get_tool_registry
from core.tools.capabilities import Capability

registry = get_tool_registry()

print("\n" + "="*80)
print("CAPABILITY INDEX CHECK")
print("="*80)

# Check specific capabilities
test_capabilities = [
    Capability.CAUSAL_REASONING,
    Capability.ANALYZE_PERFORMANCE,
    Capability.PREDICT_BREAKTHROUGH,
    Capability.TEST_RESILIENCE
]

for cap in test_capabilities:
    providers = registry.find_providers(cap)
    print(f"\n{cap.value}:")
    print(f"  Providers: {[p.name for p in providers]}")
    print(f"  Count: {len(providers)}")

# Check capability coverage stats
print("\n" + "="*80)
coverage = registry.get_capability_coverage()
print(f"Total capabilities covered: {len(coverage)}")
print(f"\nCoverage breakdown:")
for cap, count in sorted(coverage.items(), key=lambda x: -x[1])[:10]:
    print(f"  {cap.value}: {count} tools")
