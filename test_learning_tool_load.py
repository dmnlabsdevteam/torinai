#!/usr/bin/env python3
"""Test if learning tools are loading and have capability profiles"""

from core.tools.learning_tools import (
    AnalyzeCausalFeedbackTool,
    ProfilePerformanceTool,
    ForecastCapabilitiesTool
)

print("\n" + "="*80)
print("LEARNING TOOL CAPABILITY PROFILE CHECK")
print("="*80)

tools = [
    ("analyzecausalfeedback", AnalyzeCausalFeedbackTool()),
    ("profileperformance", ProfilePerformanceTool()),
    ("forecastcapabilities", ForecastCapabilitiesTool())
]

for tool_name, tool in tools:
    print(f"\n{tool_name}:")
    print(f"  Name: {tool.name}")
    print(f"  Has capability_profile: {hasattr(tool, 'capability_profile')}")

    if hasattr(tool, 'capability_profile') and tool.capability_profile:
        caps = tool.capability_profile.get_capability_names()
        print(f"  Capabilities: {[c.value for c in caps]}")
    else:
        print(f"  ❌ NO CAPABILITY PROFILE")
