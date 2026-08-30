#!/usr/bin/env python3
"""
Tool Migration Helper - Add Capability Metadata
================================================
Helper script to migrate existing tools to use capability-based discovery.

This script provides:
1. Templates for adding capabilities to tools
2. Automatic capability inference based on tool category
3. Examples for each tool category

Usage:
    # See suggested capabilities for a tool category
    python migrate_to_capabilities.py --suggest filesystem

    # Generate migration code for a specific tool
    python migrate_to_capabilities.py --tool ReadFileTool

Author: Torin AI Team
"""

from typing import List, Dict, Set
from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile
from core.tools.tool_registry import ToolCategory


# ========== CAPABILITY MAPPINGS ==========

# Map tool categories to their primary capabilities
# Based on actual tool inventory: 258 tools across 22 files
CATEGORY_TO_CAPABILITIES: Dict[ToolCategory, List[Capability]] = {
    # FILESYSTEM (16 tools) - file operations
    ToolCategory.FILESYSTEM: [
        Capability.READ_DATA,
        Capability.WRITE_DATA,
        Capability.DELETE_DATA,
        Capability.MOVE_DATA,
        Capability.COPY_DATA,
        Capability.LIST_DATA,
        Capability.SEARCH_DATA,
        Capability.VALIDATE_DATA,
        Capability.COMPRESS_DATA,
        Capability.DECOMPRESS_DATA,
    ],

    # EXECUTION (17 tools) - command/code execution
    ToolCategory.EXECUTION: [
        Capability.RUN_COMMAND,
        Capability.EXECUTE_CODE,
        Capability.MANAGE_PROCESS,
        Capability.SCHEDULE_TASK,
        Capability.RUN_BACKGROUND_TASK,
    ],

    # SEARCH (20 tools) - code/content search
    ToolCategory.SEARCH: [
        Capability.SEARCH_DATA,
        Capability.SEMANTIC_SEARCH,
        Capability.TEXT_SEARCH,
        Capability.PATTERN_SEARCH,
        Capability.AST_SEARCH,
        Capability.ANALYZE_CODE,
    ],

    # NETWORK (12 tools) - HTTP/web operations
    ToolCategory.NETWORK: [
        Capability.HTTP_REQUEST,
        Capability.DOWNLOAD,
        Capability.UPLOAD,
        Capability.PARSE_HTML,
        Capability.CHECK_CONNECTIVITY,
        Capability.DNS_LOOKUP,
    ],

    # DATABASE (13 tools) - database operations
    ToolCategory.DATABASE: [
        Capability.QUERY_DATABASE,
        Capability.MODIFY_DATABASE,
        Capability.BACKUP_DATABASE,
        Capability.RESTORE_DATABASE,
        Capability.MIGRATE_DATABASE,
    ],

    # COMMUNICATION (2 + 3 + 8 = 13 tools) - messaging/notifications
    ToolCategory.COMMUNICATION: [
        Capability.SEND_MESSAGE,
        Capability.RECEIVE_MESSAGE,
        Capability.NOTIFY,
        Capability.ASK_HUMAN,
        Capability.LIST_DATA,  # For Slack user/channel lists
    ],

    # MONITORING (14 tools) - system/health monitoring
    ToolCategory.MONITORING: [
        Capability.MONITOR_SYSTEM,
        Capability.MONITOR_LOGS,
        Capability.MONITOR_METRICS,
        Capability.MONITOR_HEALTH,
        Capability.CREATE_ALERT,
        Capability.DETECT_ANOMALY,
        Capability.TRACE_EXECUTION,
    ],

    # SECURITY (45 tools!) - security/cryptography
    ToolCategory.SECURITY: [
        Capability.SCAN_SECURITY,
        Capability.DETECT_THREAT,
        Capability.ANALYZE_THREAT,
        Capability.BLOCK_THREAT,
        Capability.VALIDATE_INPUT,
        Capability.ENCRYPT_DATA,
        Capability.DECRYPT_DATA,
        Capability.HASH_DATA,
        Capability.MANAGE_SECRETS,
        Capability.DETECT_INTRUSION,
    ],

    # CODE_GENERATION (29 tools) - code generation/modification
    ToolCategory.CODE_GENERATION: [
        Capability.GENERATE_CODE,
        Capability.REFACTOR_CODE,
        Capability.FORMAT_CODE,
        Capability.DOCUMENT_CODE,
        Capability.ANALYZE_CODE,
        Capability.DEBUG_CODE,
    ],

    # TESTING (20 tools) - testing/validation
    ToolCategory.TESTING: [
        Capability.RUN_TESTS,
        Capability.GENERATE_TESTS,
        Capability.BENCHMARK,
        Capability.COVERAGE_ANALYSIS,
        Capability.FUZZ_TEST,
        Capability.MUTATION_TEST,
        Capability.LINT_CODE,
        Capability.TEST_CODE,
    ],

    # DATA_PROCESSING (14 tools) - data transformation
    ToolCategory.DATA_PROCESSING: [
        Capability.PARSE_DATA,
        Capability.TRANSFORM_DATA,
        Capability.AGGREGATE_DATA,
        Capability.FILTER_DATA,
        Capability.SORT_DATA,
        Capability.MERGE_DATA,
    ],

    # AI_ML (8 tools) - ML/embeddings
    ToolCategory.AI_ML: [
        Capability.GENERATE_EMBEDDING,
        Capability.RUN_INFERENCE,
        Capability.ANALYZE_SIMILARITY,
        Capability.EXTRACT_ENTITIES,
        Capability.SUMMARIZE_TEXT,
    ],

    # DOCUMENTATION (15 tools) - docs/diagrams
    ToolCategory.DOCUMENTATION: [
        Capability.GENERATE_DOCS,
        Capability.CREATE_DIAGRAM,
        Capability.GENERATE_REPORT,
        Capability.GENERATE_CITATION,
    ],

    # SYSTEM (4 + 7 = 11 tools) - system info/management
    ToolCategory.SYSTEM: [
        Capability.GET_SYSTEM_INFO,
        Capability.MANAGE_CONFIG,
        Capability.MANAGE_DEPENDENCIES,
        Capability.MANAGE_DOCKER,
    ],
}


# ========== MIGRATION EXAMPLES ==========

def get_filesystem_example():
    """Example: Adding capabilities to ReadFileTool"""
    return '''
# Example: ReadFileTool with capability metadata

from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

class ReadFileTool(Tool):
    """Read file from filesystem"""

    def __init__(self):
        super().__init__()
        self.name = "read_file"
        self.description = "Read contents of a file from the filesystem"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE

        # ADD THIS: Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="read_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read data from local files",
                    input_types=["file_path"],
                    output_types=["text", "binary"],
                    context_matchers={"data_source": "file"},  # Matches file paths
                    latency="low",
                    cost="low",
                    reliability="high",
                    priority=10  # Prefer this for file paths
                )
            ],
            requires_filesystem=True,
            is_idempotent=True
        )

        # ... rest of tool implementation ...
'''


def get_network_example():
    """Example: Adding capabilities to HttpRequestTool"""
    return '''
# Example: HttpRequestTool with capability metadata

from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

class HttpRequestTool(Tool):
    """Make HTTP requests"""

    def __init__(self):
        super().__init__()
        self.name = "http_request"
        self.description = "Make HTTP requests to external APIs"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE

        # ADD THIS: Capability profile with multiple capabilities
        self.capability_profile = ToolCapabilityProfile(
            tool_name="http_request",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.HTTP_REQUEST,
                    description="Make HTTP/HTTPS requests",
                    input_types=["url", "headers", "body"],
                    output_types=["json", "text", "binary"],
                    latency="medium",  # Network calls are slower
                    cost="low",
                    reliability="medium"
                ),
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read data from URLs",
                    input_types=["url"],
                    output_types=["json", "text"],
                    context_matchers={"data_source": ["url", "api"]},
                    latency="medium",
                    cost="low",
                    reliability="medium",
                    priority=5  # Lower priority than file reading
                )
            ],
            requires_network=True,
            is_idempotent=False  # Can have side effects
        )

        # ... rest of tool implementation ...
'''


def get_communication_example():
    """Example: Adding capabilities to Slack tools"""
    return '''
# Example: Slack tools with capability metadata

from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

class AskForClarificationTool(Tool):
    """Ask human for clarification via Slack"""

    def __init__(self):
        super().__init__()
        self.name = "ask_for_clarification"
        self.description = "Ask Dominion Labs team for clarification when uncertain"
        self.category = ToolCategory.COMMUNICATION
        self.safety_level = ToolSafety.SAFE

        # ADD THIS: Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="ask_for_clarification",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ASK_HUMAN,
                    description="Request human input/clarification",
                    input_types=["question", "context"],
                    output_types=["response"],
                    latency="high",  # Human response takes time
                    cost="low",
                    reliability="high",
                    priority=10  # Prefer this for asking questions
                ),
                CapabilityMetadata(
                    capability=Capability.SEND_MESSAGE,
                    description="Send messages to Slack",
                    input_types=["message", "channel"],
                    output_types=["message_id"],
                    latency="medium",
                    cost="low",
                    reliability="high"
                )
            ],
            requires_network=True,
            requires_credentials=True,
            is_idempotent=False
        )

        # ... rest of tool implementation ...
'''


def get_security_example():
    """Example: Adding capabilities to security tools (45 tools in security_tools.py!)"""
    return '''
# Example: Security tools with capability metadata
# SECURITY has 45 tools - largest category!

from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

class ScanSecretsTool(Tool):
    """Scan code for secrets/credentials"""

    def __init__(self):
        super().__init__()
        self.name = "scan_secrets"
        self.description = "Scan files for hardcoded secrets and credentials"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE

        # ADD THIS: Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="scan_secrets",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SCAN_SECURITY,
                    description="Scan for security vulnerabilities",
                    input_types=["file_path", "directory"],
                    output_types=["findings"],
                    latency="medium",
                    cost="low",
                    reliability="high"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code for issues",
                    input_types=["code", "file_path"],
                    output_types=["analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high"
                )
            ],
            requires_filesystem=True,
            is_idempotent=True
        )

        # ... rest of tool implementation ...


# Example: Threat detection tool
class DetectIntrusionTool(Tool):
    """Detect intrusion attempts"""

    def __init__(self):
        super().__init__()
        self.name = "detect_intrusion"
        self.description = "Detect intrusion attempts from logs/traffic"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.SAFE

        self.capability_profile = ToolCapabilityProfile(
            tool_name="detect_intrusion",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_INTRUSION,
                    description="Detect intrusion attempts",
                    input_types=["logs", "traffic_data"],
                    output_types=["alerts", "incidents"],
                    latency="medium",
                    cost="medium",
                    reliability="high"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_THREAT,
                    description="Analyze threat patterns",
                    input_types=["security_events"],
                    output_types=["threat_analysis"],
                    latency="medium",
                    cost="medium",
                    reliability="high"
                )
            ],
            requires_network=False,
            is_idempotent=True
        )
'''


def get_code_generation_example():
    """Example: Code generation tools (29 tools!)"""
    return '''
# Example: Code generation tools
# CODE_GENERATION has 29 tools - second largest category!

from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

class GenerateFunctionTool(Tool):
    """Generate Python function from specification"""

    def __init__(self):
        super().__init__()
        self.name = "generate_function"
        self.description = "Generate Python function from natural language specification"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_function",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    description="Generate code from specifications",
                    input_types=["specification", "requirements"],
                    output_types=["code"],
                    context_matchers={"code_type": "function"},
                    latency="medium",
                    cost="medium",  # LLM inference cost
                    reliability="high",
                    priority=10
                )
            ],
            is_idempotent=False  # Each generation may be different
        )


class RefactorCodeTool(Tool):
    """Refactor existing code"""

    def __init__(self):
        super().__init__()
        self.name = "refactor_code"
        self.description = "Refactor code for better structure/performance"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE

        self.capability_profile = ToolCapabilityProfile(
            tool_name="refactor_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    description="Refactor existing code",
                    input_types=["code", "refactor_goals"],
                    output_types=["refactored_code"],
                    latency="medium",
                    cost="medium",
                    reliability="high"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code before refactoring",
                    input_types=["code"],
                    output_types=["analysis"],
                    latency="low",
                    cost="low",
                    reliability="high"
                )
            ],
            requires_filesystem=True,
            is_idempotent=False
        )
'''


def get_testing_example():
    """Example: Testing tools (20 tools!)"""
    return '''
# Example: Testing/validation tools
# TESTING has 20 tools - includes pytest, unittest, benchmarks, etc.

from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

class RunPytestTool(Tool):
    """Run pytest test suite"""

    def __init__(self):
        super().__init__()
        self.name = "run_pytest"
        self.description = "Run pytest test suite"
        self.category = ToolCategory.TESTING
        self.safety_level = ToolSafety.SAFE

        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_pytest",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_TESTS,
                    description="Execute test suite",
                    input_types=["test_path", "options"],
                    output_types=["test_results"],
                    context_matchers={"test_framework": "pytest"},
                    latency="high",  # Tests can take time
                    cost="medium",
                    reliability="high",
                    priority=10  # Prefer for pytest tests
                ),
                CapabilityMetadata(
                    capability=Capability.TEST_CODE,
                    description="Validate code correctness",
                    input_types=["code_path"],
                    output_types=["pass_fail_results"],
                    latency="high",
                    cost="medium",
                    reliability="high"
                )
            ],
            requires_filesystem=True,
            requires_network=False,  # Unless tests need network
            is_idempotent=True  # Same tests = same results
        )


class BenchmarkCodeTool(Tool):
    """Benchmark code performance"""

    def __init__(self):
        super().__init__()
        self.name = "benchmark_code"
        self.description = "Benchmark code performance"
        self.category = ToolCategory.TESTING
        self.safety_level = ToolSafety.SAFE

        self.capability_profile = ToolCapabilityProfile(
            tool_name="benchmark_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BENCHMARK,
                    description="Measure code performance",
                    input_types=["code", "iterations"],
                    output_types=["performance_metrics"],
                    latency="high",
                    cost="medium",
                    reliability="high"
                )
            ],
            requires_filesystem=True,
            is_idempotent=False  # Performance varies
        )
'''


def get_monitoring_example():
    """Example: Monitoring tools (14 tools)"""
    return '''
# Example: Monitoring tools
# MONITORING has 14 tools - system health, metrics, logs

from core.tools.capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

class GetCPUUsageTool(Tool):
    """Get CPU usage metrics"""

    def __init__(self):
        super().__init__()
        self.name = "get_cpu_usage"
        self.description = "Get current CPU usage metrics"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE

        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_cpu_usage",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MONITOR_SYSTEM,
                    description="Monitor system resources",
                    input_types=[],
                    output_types=["cpu_metrics"],
                    context_matchers={"metric_type": "cpu"},
                    latency="low",
                    cost="low",
                    reliability="high",
                    priority=10
                )
            ],
            is_idempotent=False  # Metrics change over time
        )


class ParseLogsTool(Tool):
    """Parse and analyze log files"""

    def __init__(self):
        super().__init__()
        self.name = "parse_logs"
        self.description = "Parse and analyze log files"
        self.category = ToolCategory.MONITORING
        self.safety_level = ToolSafety.SAFE

        self.capability_profile = ToolCapabilityProfile(
            tool_name="parse_logs",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MONITOR_LOGS,
                    description="Parse and analyze logs",
                    input_types=["log_path", "patterns"],
                    output_types=["parsed_logs", "insights"],
                    latency="medium",
                    cost="low",
                    reliability="high"
                ),
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read log data",
                    input_types=["log_path"],
                    output_types=["log_content"],
                    context_matchers={"data_source": "logs"},
                    latency="low",
                    cost="low",
                    reliability="high"
                )
            ],
            requires_filesystem=True,
            is_idempotent=True
        )
'''


# ========== MIGRATION HELPERS ==========

def suggest_capabilities(category: ToolCategory) -> List[Capability]:
    """Suggest capabilities for a tool category"""
    return CATEGORY_TO_CAPABILITIES.get(category, [])


def generate_capability_profile_code(
    tool_name: str,
    category: ToolCategory,
    capabilities: List[Capability],
    requires_network: bool = False,
    requires_filesystem: bool = False,
    requires_database: bool = False,
    requires_credentials: bool = False
) -> str:
    """
    Generate Python code for adding capability profile to a tool.

    Args:
        tool_name: Name of the tool
        category: Tool category
        capabilities: List of capabilities
        requires_network: Whether tool needs network access
        requires_filesystem: Whether tool needs filesystem access
        requires_database: Whether tool needs database access
        requires_credentials: Whether tool needs credentials

    Returns:
        Python code string to add to __init__
    """

    cap_metadata_lines = []
    for cap in capabilities:
        cap_metadata_lines.append(f'''
                CapabilityMetadata(
                    capability=Capability.{cap.name},
                    description="TODO: Describe what this tool does",
                    input_types=["TODO"],
                    output_types=["TODO"],
                    latency="low",  # low, medium, or high
                    cost="low",     # low, medium, or high
                    reliability="high"  # low, medium, or high
                )''')

    cap_metadata_str = "," .join(cap_metadata_lines)

    code = f'''
        # ADD THIS to your __init__ method:
        self.capability_profile = ToolCapabilityProfile(
            tool_name="{tool_name}",
            capabilities=[{cap_metadata_str}
            ],
            requires_network={requires_network},
            requires_filesystem={requires_filesystem},
            requires_database={requires_database},
            requires_credentials={requires_credentials},
            is_idempotent=True  # Change to False if tool has side effects
        )
'''
    return code


# ========== USAGE EXAMPLES ==========

def print_usage():
    """Print usage instructions"""
    print("""
========================================
Tool Migration Helper
========================================

TOOL INVENTORY: 258 total tools across 22 files
------------------------------------------------
Security:         45 tools (largest!)
Code Generation:  29 tools
Testing:          20 tools
Search:           20 tools
Execution:        17 tools
Filesystem:       16 tools
Documentation:    15 tools
Academic:         15 tools
Monitoring:       14 tools
Data Processing:  14 tools
Database:         13 tools
Network:          12 tools
System Mgmt:       7 tools
Chaos:             6 tools
Learning:          5 tools
System:            4 tools
Research:          4 tools
Slack (context):   3 tools
Communication:     2 tools
... and more!

This helper shows you how to add capability metadata to ALL tools.

STEP 1: Look at examples for your tool category
------------------------------------------------
""")

    print("\n1. FILESYSTEM TOOLS (16 tools):")
    print(get_filesystem_example())

    print("\n2. NETWORK TOOLS (12 tools):")
    print(get_network_example())

    print("\n3. COMMUNICATION TOOLS (13 tools - Slack, webhooks, etc.):")
    print(get_communication_example())

    print("\n4. SECURITY TOOLS (45 tools - LARGEST CATEGORY!):")
    print(get_security_example())

    print("\n5. CODE GENERATION TOOLS (29 tools):")
    print(get_code_generation_example())

    print("\n6. TESTING TOOLS (20 tools):")
    print(get_testing_example())

    print("\n7. MONITORING TOOLS (14 tools):")
    print(get_monitoring_example())

    print("""
STEP 2: For your specific tool category, here are suggested capabilities:
------------------------------------------------------------------------
""")

    for category in ToolCategory:
        caps = suggest_capabilities(category)
        if caps:
            print(f"\n{category.value.upper()}:")
            for cap in caps:
                print(f"  - Capability.{cap.name}")

    print("""
========================================
MIGRATION WORKFLOW
========================================

For each tool file (22 files total):

1. Add import:
   from .capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile

2. In each Tool's __init__, add capability_profile:
   self.capability_profile = ToolCapabilityProfile(
       tool_name="your_tool_name",
       capabilities=[...],
       requires_network=True/False,
       requires_filesystem=True/False,
       is_idempotent=True/False
   )

3. Test that tool still works after adding capabilities

4. Register with capability index (automatic if using register())

PRIORITY ORDER (start with these):
-----------------------------------
1. Security tools (45 tools) - most tools
2. Code generation (29 tools) - high value
3. Testing (20 tools) - frequently used
4. Search (20 tools) - core functionality
5. Everything else

""")


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        print_usage()
    else:
        # Handle command line arguments for specific tool migration
        if "--suggest" in sys.argv:
            idx = sys.argv.index("--suggest")
            if idx + 1 < len(sys.argv):
                category_name = sys.argv[idx + 1].upper()
                try:
                    category = ToolCategory[category_name]
                    caps = suggest_capabilities(category)
                    print(f"\nSuggested capabilities for {category.value}:")
                    for cap in caps:
                        print(f"  - Capability.{cap.name}")
                except KeyError:
                    print(f"Unknown category: {category_name}")
                    print(f"Valid categories: {[c.name for c in ToolCategory]}")
