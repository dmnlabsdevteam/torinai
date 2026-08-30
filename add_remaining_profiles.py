#!/usr/bin/env python3
"""Add capability profiles to remaining search tools"""

import re

# Remaining tools with their capabilities
REMAINING_TOOLS = [
    ("DetectCodeSmellsTool", "detect_code_smells", ["ANALYZE_CODE", "DETECT_ISSUE"]),
    ("TraceDependenciesTool", "trace_dependencies", ["ANALYZE_DEPENDENCIES"]),
    ("FindCircularImportsTool", "find_circular_imports", ["DETECT_ISSUE", "ANALYZE_DEPENDENCIES"]),
    ("AnalyzeTestCoverageReportTool", "analyze_test_coverage_report", ["ANALYZE_CODE", "ASSESS_COVERAGE"]),
    ("FindPerformanceIssuesTool", "find_performance_issues", ["IDENTIFY_BOTTLENECK", "ANALYZE_PERFORMANCE"]),
    ("CheckCodeStyleConsistencyTool", "check_code_style_consistency", ["ANALYZE_CODE", "ASSESS_QUALITY"]),
    ("ASTSearchTool", "ast_search", ["SEARCH_CODE"]),
    ("BuildDependencyGraphTool", "build_dependency_graph", ["ANALYZE_DEPENDENCIES", "VISUALIZE"]),
    ("ExtractCallGraphTool", "extract_call_graph", ["ANALYZE_CODE"]),
    ("SearchSecretsAndPIITool", "search_secrets_pii", ["DETECT_THREAT", "SEARCH_CODE"])
]

CAPABILITY_DESCRIPTIONS = {
    "ANALYZE_CODE": "Analyze code structure and patterns",
    "DETECT_ISSUE": "Detect code issues and problems",
    "ANALYZE_DEPENDENCIES": "Analyze dependencies and imports",
    "ASSESS_COVERAGE": "Assess test coverage metrics",
    "IDENTIFY_BOTTLENECK": "Identify performance bottlenecks",
    "ANALYZE_PERFORMANCE": "Analyze performance characteristics",
    "ASSESS_QUALITY": "Assess code quality and style",
    "SEARCH_CODE": "Search code using advanced techniques",
    "VISUALIZE": "Generate visualizations",
    "DETECT_THREAT": "Detect security threats"
}

def generate_capability_profile(tool_name, capabilities):
    """Generate capability profile code"""
    cap_lines = []
    for cap in capabilities:
        desc = CAPABILITY_DESCRIPTIONS.get(cap, f"{cap.lower()} capability")
        cap_lines.append(f"""                CapabilityMetadata(
                    capability=Capability.{cap},
                    description="{desc}"
                )""")

    caps_str = ",\n".join(cap_lines)

    profile = f"""
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="{tool_name}",
            capabilities=[
{caps_str}
            ]
        )
"""
    return profile

# Read file
file_path = "/Users/stefan/Dominion Labs/TorinAI/core/tools/search_tools.py"
with open(file_path, 'r') as f:
    content = f.read()

# Process each tool
for class_name, tool_name, capabilities in REMAINING_TOOLS:
    print(f"Adding profile to {class_name}...")

    # Find the class and its parameters closing bracket
    class_pattern = rf'class {class_name}\(Tool\):.*?        \](\n\n    async def execute)'

    match = re.search(class_pattern, content, re.DOTALL)
    if not match:
        print(f"  ⚠ Could not find {class_name}")
        continue

    # Generate the profile
    profile = generate_capability_profile(tool_name, capabilities)

    # Insert the profile before "async def execute"
    replacement = match.group(0).replace(
        '\n\n    async def execute',
        profile + '\n    async def execute'
    )

    content = content.replace(match.group(0), replacement)
    print(f"  ✓ Added profile to {class_name}")

# Write back
with open(file_path, 'w') as f:
    f.write(content)

print(f"\n✅ Added capability profiles to {len(REMAINING_TOOLS)} tools!")
