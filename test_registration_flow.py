#!/usr/bin/env python3
"""Test registration flow for learning tools"""

import logging
logging.basicConfig(level=logging.DEBUG)

from core.tools.tool_registry import ToolRegistry, _register_tool_lazy
from core.tools.learning_tools import AnalyzeCausalFeedbackTool
from core.tools.capabilities import Capability

print("\n" + "="*80)
print("TESTING REGISTRATION FLOW")
print("="*80)

# Create fresh registry
registry = ToolRegistry()

print("\n1. Before registration:")
print(f"   capability_index: {registry.capability_index}")

print("\n2. Registering AnalyzeCausalFeedbackTool...")

# Simulate _register_tool_lazy
metadata_instance = AnalyzeCausalFeedbackTool()
tool_name = metadata_instance.name

print(f"   Tool name: {tool_name}")
print(f"   Has capability_profile: {hasattr(metadata_instance, 'capability_profile')}")

if hasattr(metadata_instance, 'capability_profile') and metadata_instance.capability_profile:
    capabilities = list(metadata_instance.capability_profile.get_capability_names())
    print(f"   Extracted capabilities: {[c.value for c in capabilities]}")
else:
    capabilities = None
    print(f"   ❌ No capabilities extracted")

# Register factory
registry.register_factory(
    tool_name,
    AnalyzeCausalFeedbackTool,
    capabilities=capabilities,
    category=metadata_instance.category,
    safety_level=metadata_instance.safety_level
)

print("\n3. After registration:")
print(f"   tool_factories: {list(registry.tool_factories.keys())}")
print(f"   capability_index: {registry.capability_index}")

print("\n4. Testing find_providers:")
providers = registry.find_providers(Capability.CAUSAL_REASONING)
print(f"   Providers for CAUSAL_REASONING: {[p.name for p in providers]}")
