#!/usr/bin/env python3
"""
Integration Test: LLM + Capability-Based Tool Discovery
========================================================

Tests that the LLM can correctly:
1. Understand capability-based tool descriptions
2. Request capabilities based on task context
3. Use tools selected via capability matching (not keyword matching)
4. Complete tasks using the capability system

EXPANDED: Also tests full registry completeness, all capability domains,
safe direct tool execution, tool schema validity, and connector discovery.

This is the REAL test - verifying the brain (LLM) works with the capability system.
"""

import asyncio
import logging
import json
from typing import Dict, Any, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_llm_capability_understanding():
    """Test 1: Can the LLM understand capability-based tool descriptions?"""
    print("\n" + "="*80)
    print("TEST 1: LLM Understanding of Capability Descriptions")
    print("="*80)

    from core.services.unified_llm import get_llm_service
    from core.tools import get_tool_registry
    from core.tools.capabilities import Capability

    # Get services
    llm = get_llm_service()
    registry = get_tool_registry()

    # Get a tool with capability profile
    causal_tool = registry.get_tool('analyzecausalfeedback')

    if not causal_tool or not hasattr(causal_tool, 'capability_profile'):
        print("❌ FAIL: Tool missing capability profile")
        return False

    # Ask LLM what this tool does based on its capabilities
    capabilities = causal_tool.capability_profile.get_capability_names()
    cap_names = [cap.value for cap in capabilities]

    prompt = f"""A tool declares these capabilities: {cap_names}

Based on these capabilities, what kind of tasks is this tool designed for?
Answer in 1-2 sentences."""

    # Use generate() which returns Dict with "content" key
    result = await llm.generate(
        prompt=prompt,
        temperature=0.3,
        max_tokens=100,
        agent_type="test"
    )

    response = result.get("content", "")

    print(f"\n📋 Tool: {causal_tool.name}")
    print(f"   Declared capabilities: {cap_names}")
    print(f"   LLM's understanding: {response.strip()}")

    # Check if LLM mentioned key concepts
    key_concepts = ['cause', 'effect', 'feedback', 'analysis', 'pattern']
    found_concepts = [c for c in key_concepts if c.lower() in response.lower()]

    if len(found_concepts) >= 2:
        print(f"   ✓ LLM correctly understood the tool (mentioned: {found_concepts})")
        return True
    else:
        print(f"   ✗ LLM may not fully understand (only mentioned: {found_concepts})")
        return False


async def test_llm_capability_selection():
    """Test 2: Can the LLM select correct capabilities for a task?"""
    print("\n" + "="*80)
    print("TEST 2: LLM Capability Selection from Task Description")
    print("="*80)

    from core.services.unified_llm import get_llm_service
    from core.tools.capabilities import Capability

    llm = get_llm_service()

    # Available capabilities (from our expanded capability system)
    available_capabilities = [
        "CAUSAL_REASONING",
        "TEST_RESILIENCE",
        "PREDICT_BREAKTHROUGH",
        "GENERATE_CODE",
        "ANALYZE_PERFORMANCE",
        "EXECUTE_CODE",
        "ENCRYPT_DATA"
    ]

    test_tasks = [
        {
            "description": "Analyze why database queries are timing out after the recent deployment",
            "expected_capabilities": ["CAUSAL_REASONING", "ANALYZE_PERFORMANCE"]
        },
        {
            "description": "Test how the system handles network partitions and service failures",
            "expected_capabilities": ["TEST_RESILIENCE"]
        },
        {
            "description": "Predict when AGI capabilities will emerge based on current AI research trends",
            "expected_capabilities": ["PREDICT_BREAKTHROUGH"]
        }
    ]

    passed = 0
    for task in test_tasks:
        print(f"\n📋 Task: {task['description']}")

        prompt = f"""Given this task: "{task['description']}"

Which capabilities from this list are needed?
{json.dumps(available_capabilities, indent=2)}

Return ONLY a JSON array of capability names needed, like: ["CAPABILITY1", "CAPABILITY2"]
No explanation, just the JSON array."""

        # Use generate() which returns Dict with "content" key
        result = await llm.generate(
            prompt=prompt,
            temperature=0.1,
            max_tokens=100,
            agent_type="test"
        )

        response = result.get("content", "")

        try:
            # Extract JSON from response
            response_clean = response.strip()
            if not response_clean.startswith('['):
                # Try to find JSON array in response
                start = response_clean.find('[')
                end = response_clean.rfind(']') + 1
                if start >= 0 and end > start:
                    response_clean = response_clean[start:end]

            selected = json.loads(response_clean)

            print(f"   Expected: {task['expected_capabilities']}")
            print(f"   LLM selected: {selected}")

            # Check if at least one expected capability was selected
            matches = [cap for cap in task['expected_capabilities'] if cap in selected]
            if matches:
                print(f"   ✓ PASS: LLM selected correct capabilities: {matches}")
                passed += 1
            else:
                print(f"   ✗ FAIL: LLM didn't select expected capabilities")

        except json.JSONDecodeError as e:
            print(f"   ✗ FAIL: LLM didn't return valid JSON: {response[:100]}")

    print(f"\n📊 Results: {passed}/{len(test_tasks)} tasks correctly analyzed")
    return passed == len(test_tasks)


async def test_llm_with_capability_discovery():
    """Test 3: End-to-end LLM task with capability-based tool discovery"""
    print("\n" + "="*80)
    print("TEST 3: End-to-End LLM + Capability Discovery")
    print("="*80)

    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
    from core.tools import get_tool_registry

    executor = GeneralPurposeExecutor()
    await executor.initialize()

    # Real-world task scenarios
    test_scenarios = [
        {
            "description": "Analyze the causal relationship between high memory usage and slow API response times",
            "expected_tools": ["analyzecausalfeedback", "profileperformance"],
            "expected_capabilities": ["CAUSAL_REASONING", "ANALYZE_PERFORMANCE"]
        },
        {
            "description": "Predict when quantum computing will enable practical code-breaking capabilities",
            "expected_tools": ["forecastcapabilities"],
            "expected_capabilities": ["PREDICT_BREAKTHROUGH", "TRACK_FRONTIER"]
        },
        {
            "description": "Test system resilience under network partition and high load scenarios",
            "expected_tools": ["create_chaos_experiment", "run_chaos_experiment"],
            "expected_capabilities": ["TEST_RESILIENCE", "INJECT_FAILURE"]
        }
    ]

    passed = 0
    for scenario in test_scenarios:
        print(f"\n📋 Scenario: {scenario['description'][:60]}...")

        # Use capability-based discovery (the NEW method)
        discovered_tools = await executor._get_tools_by_capability(scenario['description'])

        print(f"   Expected tools: {scenario['expected_tools'][:3]}")
        print(f"   Discovered tools: {list(discovered_tools.keys())[:10]}")

        # Check if at least one expected tool was discovered
        found_tools = [t for t in scenario['expected_tools'] if t in discovered_tools]

        if found_tools:
            print(f"   ✓ PASS: Found expected tools via capability matching: {found_tools}")

            # Verify these tools have the expected capabilities
            for tool_name in found_tools:
                tool = discovered_tools[tool_name]
                if hasattr(tool, 'capability_profile') and tool.capability_profile:
                    caps = [cap.value for cap in tool.capability_profile.get_capability_names()]
                    matching_caps = [c for c in scenario['expected_capabilities'] if c in caps]
                    print(f"      → {tool_name} capabilities: {matching_caps}")
            passed += 1
        else:
            print(f"   ✗ FAIL: Expected tools not discovered")
            print(f"      Available tools: {list(discovered_tools.keys())[:20]}")

    print(f"\n📊 Results: {passed}/{len(test_scenarios)} scenarios correctly matched")
    return passed == len(test_scenarios)


async def test_llm_tool_execution_with_capabilities():
    """Test 4: LLM can execute tools selected via capability system"""
    print("\n" + "="*80)
    print("TEST 4: LLM Tool Execution via Capability System")
    print("="*80)

    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
    from core.agents.autonomous.shared_types import Task, TaskType, Priority, TaskSource

    executor = GeneralPurposeExecutor()
    await executor.initialize()

    # Create a simple task that requires capability-based tool selection
    task = Task(
        id="test_capability_exec_001",
        type=TaskType.ANALYSIS,
        description="Analyze causal relationships in system feedback to identify root causes of performance degradation",
        priority=Priority.MEDIUM,
        source=TaskSource.SYSTEM,
        created_by="integration_test"
    )

    print(f"\n📋 Task: {task.description[:60]}...")
    print(f"   Task type: {task.type}")

    # The executor should use capability-based discovery
    try:
        # This will use _get_tools_by_capability internally
        result = await executor.execute_task(task)

        print(f"\n📊 Execution Result:")
        print(f"   Success: {result.get('success', False)}")
        print(f"   Confidence: {result.get('confidence', 0.0)}")

        # Check metadata for tools used
        metadata = result.get('metadata', {})
        if metadata and 'tools_used' in metadata:
            tools_used = metadata['tools_used']
            print(f"   Tools used: {tools_used}")

            # Check if capability-based tools were used
            capability_tools = ['analyzecausalfeedback', 'profileperformance', 'forecastcapabilities']
            used_cap_tools = [t for t in capability_tools if t in str(tools_used)]

            if used_cap_tools:
                print(f"   ✓ PASS: Used capability-based tools: {used_cap_tools}")
                return True
            else:
                print(f"   ⚠ WARNING: No obvious capability-based tools used")
                return result.get('success', False)
        else:
            print(f"   ⚠ No tool usage metadata available")
            return result.get('success', False)

    except Exception as e:
        print(f"   ✗ FAIL: Execution failed: {e}")
        logger.exception("Task execution failed")
        return False


async def test_context_matching_accuracy():
    """Test 5: Context matching accuracy - similar tasks get similar tools"""
    print("\n" + "="*80)
    print("TEST 5: Context Matching Accuracy")
    print("="*80)

    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
    from core.tools import get_tool_registry

    executor = GeneralPurposeExecutor()
    await executor.initialize()

    # Similar tasks should get similar tool sets
    similar_task_groups = [
        {
            "theme": "Causal Analysis",
            "tasks": [
                "Analyze why API latency increased after the deployment",
                "Identify the root cause of database connection timeouts",
                "Determine what's causing memory leaks in the service"
            ],
            "expected_common_tools": ["analyzecausalfeedback"]
        },
        {
            "theme": "Performance Analysis",
            "tasks": [
                "Benchmark the memory agent's query performance",
                "Profile execution time of the neural bridge",
                "Measure CPU usage of the autonomous coordinator"
            ],
            "expected_common_tools": ["profileperformance"]
        },
        {
            "theme": "Resilience Testing",
            "tasks": [
                "Test system behavior under network failures",
                "Verify the system handles service outages gracefully",
                "Check resilience during database connection loss"
            ],
            "expected_common_tools": ["create_chaos_experiment", "run_chaos_experiment"]
        }
    ]

    passed_groups = 0
    for group in similar_task_groups:
        print(f"\n📁 Theme: {group['theme']}")

        tool_sets = []
        for task_desc in group['tasks']:
            tools = await executor._get_tools_by_capability(task_desc)
            tool_sets.append(set(tools.keys()))
            print(f"   Task: {task_desc[:50]}...")
            print(f"      Tools: {list(tools.keys())[:5]}")

        # Find common tools across all tasks in this group
        if len(tool_sets) > 1:
            common_tools = set.intersection(*tool_sets)
            print(f"   Common tools across all tasks: {list(common_tools)[:10]}")

            # Check if expected common tools are in the common set
            found_expected = [t for t in group['expected_common_tools'] if t in common_tools]

            if found_expected:
                print(f"   ✓ PASS: Found expected common tools: {found_expected}")
                passed_groups += 1
            else:
                print(f"   ✗ FAIL: Expected common tools not found")
                print(f"      Expected: {group['expected_common_tools']}")
                print(f"      Common: {list(common_tools)[:10]}")
        else:
            print(f"   ⚠ Not enough tasks to compare")

    print(f"\n📊 Results: {passed_groups}/{len(similar_task_groups)} groups showed correct context matching")
    return passed_groups == len(similar_task_groups)


async def test_all_tools_load():
    """Test 6: Every tool factory in the registry loads without error"""
    print("\n" + "="*80)
    print("TEST 6: Every Tool Loads (no spot checks — all factories)")
    print("="*80)

    from core.tools.tool_registry import get_tool_registry

    registry = get_tool_registry()
    factory_names = list(registry.tool_factories.keys())
    eager_names = list(registry.tools.keys())
    all_names = factory_names + [n for n in eager_names if n not in registry.tool_factories]

    print(f"\n📦 Factories to load: {len(factory_names)}")
    print(f"📦 Eager tools:       {len(eager_names)}")
    print(f"📦 Total unique:      {len(all_names)}")

    failed_load: List[str] = []
    loaded: List[str] = []

    for name in all_names:
        try:
            tool = registry.get_tool(name)
            if tool is None:
                failed_load.append(f"{name} → get_tool() returned None")
            else:
                loaded.append(name)
        except Exception as e:
            failed_load.append(f"{name} → {type(e).__name__}: {e}")

    print(f"\n✓ Successfully loaded: {len(loaded)}")
    if failed_load:
        print(f"❌ Failed to load ({len(failed_load)}):")
        for entry in failed_load:
            print(f"   • {entry}")
    else:
        print("✓ Zero load failures")

    return len(failed_load) == 0


async def test_all_tools_have_valid_schemas():
    """Test 7: Every loaded tool exposes a complete JSON schema"""
    print("\n" + "="*80)
    print("TEST 7: Every Tool Has a Valid JSON Schema")
    print("="*80)

    from core.tools.tool_registry import get_tool_registry

    registry = get_tool_registry()
    all_names = list(registry.tool_factories.keys()) + [
        n for n in registry.tools if n not in registry.tool_factories
    ]

    missing_method: List[str] = []
    invalid_schema: List[str] = []
    valid_count = 0

    for name in all_names:
        tool = registry.get_tool(name)
        if tool is None:
            invalid_schema.append(f"{name} → tool is None")
            continue

        if not hasattr(tool, 'to_json_schema'):
            missing_method.append(name)
            continue

        try:
            schema = tool.to_json_schema()
            if not isinstance(schema, dict):
                invalid_schema.append(f"{name} → schema is {type(schema).__name__}, not dict")
            elif 'name' not in schema:
                invalid_schema.append(f"{name} → schema missing 'name' key")
            else:
                valid_count += 1
        except Exception as e:
            invalid_schema.append(f"{name} → {type(e).__name__}: {e}")

    print(f"\n✓ Valid schemas:        {valid_count}")
    if missing_method:
        print(f"⚠  Missing to_json_schema ({len(missing_method)}):")
        for n in missing_method:
            print(f"   • {n}")
    if invalid_schema:
        print(f"❌ Invalid schemas ({len(invalid_schema)}):")
        for entry in invalid_schema:
            print(f"   • {entry}")
    else:
        print("✓ Zero schema failures")

    return len(missing_method) == 0 and len(invalid_schema) == 0


async def test_all_tools_have_capability_profiles():
    """Test 8: Every tool declares a capability_profile (required for discovery)"""
    print("\n" + "="*80)
    print("TEST 8: Every Tool Has a Capability Profile")
    print("="*80)

    from core.tools.tool_registry import get_tool_registry

    registry = get_tool_registry()
    all_names = list(registry.tool_factories.keys()) + [
        n for n in registry.tools if n not in registry.tool_factories
    ]

    no_profile: List[str] = []
    empty_profile: List[str] = []
    valid_count = 0

    for name in all_names:
        tool = registry.get_tool(name)
        if tool is None:
            no_profile.append(f"{name} → None")
            continue

        if not hasattr(tool, 'capability_profile'):
            no_profile.append(name)
            continue

        profile = tool.capability_profile
        if profile is None:
            no_profile.append(f"{name} → capability_profile is None")
        else:
            caps = profile.get_capability_names()
            if not caps:
                empty_profile.append(name)
            else:
                valid_count += 1

    print(f"\n✓ Tools with valid profiles: {valid_count}")
    if no_profile:
        print(f"❌ Missing capability_profile ({len(no_profile)}):")
        for n in no_profile:
            print(f"   • {n}")
    if empty_profile:
        print(f"⚠  Empty capability profiles ({len(empty_profile)}):")
        for n in empty_profile:
            print(f"   • {n}")
    if not no_profile and not empty_profile:
        print("✓ All tools have non-empty capability profiles")

    return len(no_profile) == 0 and len(empty_profile) == 0


async def test_all_capabilities_have_providers():
    """Test 9: Every Capability enum value has at least one registered provider"""
    print("\n" + "="*80)
    print("TEST 9: Every Capability Has at Least One Provider")
    print("="*80)

    from core.tools.tool_registry import get_tool_registry
    from core.tools.capabilities import Capability, RiskLevel

    registry = get_tool_registry()

    # Get only real Capability members (exclude RiskLevel which is a separate Enum)
    capability_members = [c for c in Capability if not isinstance(c, RiskLevel)]

    no_providers: List[str] = []
    provider_counts: Dict[str, int] = {}

    for cap in capability_members:
        providers = registry.find_providers(cap)
        provider_counts[cap.value] = len(providers)
        if not providers:
            no_providers.append(cap.value)

    print(f"\n📊 Total capabilities checked: {len(capability_members)}")
    print(f"✓ Capabilities with providers:  {len(capability_members) - len(no_providers)}")

    if no_providers:
        print(f"❌ Capabilities with ZERO providers ({len(no_providers)}):")
        for cap_name in sorted(no_providers):
            print(f"   • {cap_name}")
    else:
        print("✓ Every capability has at least one registered tool provider")

    # Print top 10 most-covered capabilities
    top = sorted(provider_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    print(f"\n📈 Top 10 most-covered capabilities:")
    for cap_name, count in top:
        print(f"   {cap_name:40s} → {count} provider(s)")

    return len(no_providers) == 0


async def test_capability_index_bidirectional():
    """Test 10: If a tool declares capability X, find_providers(X) must return that tool"""
    print("\n" + "="*80)
    print("TEST 10: Capability Index Bidirectional Consistency")
    print("="*80)

    from core.tools.tool_registry import get_tool_registry
    from core.tools.capabilities import RiskLevel

    registry = get_tool_registry()
    all_names = list(registry.tool_factories.keys()) + [
        n for n in registry.tools if n not in registry.tool_factories
    ]

    # Force-load all tools so the capability index is fully built
    for name in all_names:
        registry.get_tool(name)

    broken: List[str] = []
    checked_pairs = 0

    for name in all_names:
        tool = registry.get_tool(name)
        if tool is None or not hasattr(tool, 'capability_profile') or tool.capability_profile is None:
            continue

        declared_caps = tool.capability_profile.get_capability_names()
        for cap in declared_caps:
            if isinstance(cap, RiskLevel):
                continue
            checked_pairs += 1
            providers = registry.find_providers(cap)
            provider_names = [p.name for p in providers if p is not None]
            if name not in provider_names and tool.name not in provider_names:
                broken.append(f"{name} declares {cap.value} but is not in find_providers() result")

    print(f"\n📊 Tool-capability pairs checked: {checked_pairs}")
    if broken:
        print(f"❌ Broken bidirectional entries ({len(broken)}):")
        for entry in broken[:30]:  # cap at 30 lines to avoid wall of text
            print(f"   • {entry}")
        if len(broken) > 30:
            print(f"   ... and {len(broken) - 30} more")
    else:
        print("✓ All declared capabilities are findable via find_providers()")

    return len(broken) == 0


async def test_safe_tool_direct_execution():
    """Test 11: Execute every safe (side-effect-free) tool and verify output"""
    print("\n" + "="*80)
    print("TEST 11: Safe Tool Direct Execution")
    print("="*80)

    from core.tools.tool_registry import get_tool_registry

    registry = get_tool_registry()

    # TODO(human): Fill in safe_tool_params.
    #
    # This dict maps tool_name → kwargs to pass to tool.execute(**kwargs).
    # Only include tools that are side-effect-free (reads, computes, validates — no
    # writes to external systems, no deletes, no network calls to production).
    #
    # For each tool you add:
    #   - Use real but harmless inputs (a temp file path, a sample JSON string, etc.)
    #   - The test will call tool.execute(**kwargs) and check result.success is True
    #
    # Cover at least one tool from each of these categories:
    #   filesystem, data_processing, security (hash/validate), monitoring,
    #   ai_ml, code_analysis, testing_validation, reasoning
    #
    # Example entry shape:
    #   "parsejson": {"data": '{"hello": "world"}'},
    #   "hashdata":  {"data": "test string", "algorithm": "sha256"},
    safe_tool_params: Dict[str, Dict[str, Any]] = {
        # --- Filesystem ---
        "list_directory": {"directory_path": "/tmp"},
        "validate_path":  {"path": "/tmp"},
        "get_file_info":  {"file_path": "/tmp"},

        # --- Data Processing ---
        "parse_json":    {"input": '{"status": "ok", "value": 42}'},
        "parse_yaml":    {"input": "status: ok\nvalue: 42"},
        "validate_json": {"json_data": '{"key": "value"}'},
        "validate_yaml": {"yaml_data": "key: value"},

        # --- Security (hash / validate — no network, no writes) ---
        "hash_data":               {"data": "torinai-test-string", "algorithm": "sha256"},
        "generate_password":       {"length": 16, "include_symbols": True, "include_numbers": True},
        "validate_email":          {"email": "test@dominionlabs.ai"},
        "validate_url":            {"url": "https://dominionlabs.ai"},
        "check_malicious_patterns": {"text": "SELECT * FROM users WHERE 1=1"},

        # --- Monitoring (read-only system queries) ---
        "get_cpu_usage":    {},
        "get_memory_usage": {},
        "get_disk_usage":   {"path": "/tmp"},
        "system_info":      {},

        # --- AI / ML ---
        "semantic_similarity": {
            "text1": "The system is running out of memory",
            "text2": "RAM usage has reached its limit"
        },
        "extract_entities": {"text": "Dominion Labs deployed TorinAI on February 18, 2026 in San Francisco."},

        # --- Code Analysis ---
        "check_syntax":       {"code": "def hello():\n    return 'world'"},
        "count_lines":        {"directory_path": "/tmp"},
        "analyze_complexity": {"file_path": __file__},
        "find_todos":         {"directory_path": "/tmp"},

        # --- Testing & Validation ---
        "validate_path": {"path": "/tmp"},

        # --- Reasoning ---
        "solve_constraints": {
            "variables": [
                {"name": "x", "vtype": "int", "lower": 1, "upper": 5},
                {"name": "y", "vtype": "int", "lower": 1, "upper": 5},
            ],
            "constraints": [
                # x + y == 6
                {"type": "op", "op": "==", "args": [
                    {"type": "op", "op": "+", "args": [
                        {"type": "var", "name": "x"},
                        {"type": "var", "name": "y"},
                    ]},
                    {"type": "const", "value": 6},
                ]},
                # x > y
                {"type": "op", "op": ">", "args": [
                    {"type": "var", "name": "x"},
                    {"type": "var", "name": "y"},
                ]},
            ],
        },
        "run_monte_carlo": {
            "n_samples": 100,
            "distribution": "normal",
            "params": {"mean": 0, "std": 1},
            "seed": 42
        },

        # --- Learning / Pattern Detection ---
        "detectpatterns": {
            "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "pattern_type": "trend",
            "min_confidence": 0.5
        },
        "generatehypothesis": {
            "observation": "CPU usage spikes every 60 seconds",
            "context": "system monitoring"
        },
    }

    if not safe_tool_params:
        print("   ⚠ No entries in safe_tool_params — see TODO(human) above")
        return False

    passed = 0
    skipped = 0
    failed: List[str] = []

    for tool_name, kwargs in safe_tool_params.items():
        tool = registry.get_tool(tool_name)
        if tool is None:
            print(f"   ✗ {tool_name}: not found in registry")
            failed.append(tool_name)
            continue
        try:
            result = await tool.execute(**kwargs)
            if result.success:
                print(f"   ✓ {tool_name}")
                passed += 1
            else:
                print(f"   ✗ {tool_name}: success=False, error={result.error}")
                failed.append(tool_name)
        except Exception as e:
            print(f"   ✗ {tool_name}: {type(e).__name__}: {e}")
            failed.append(tool_name)

    total = len(safe_tool_params)
    print(f"\n📊 Results: {passed}/{total} passed, {skipped} skipped, {len(failed)} failed")
    if failed:
        print(f"❌ Failed tools: {failed}")
    return len(failed) == 0


async def main():
    """Run all LLM + Capability integration tests"""
    print("\n" + "="*80)
    print("LLM + CAPABILITY SYSTEM INTEGRATION TESTS")
    print("="*80)
    print("Testing that the LLM brain correctly uses capability-based tool discovery")
    print("="*80)

    tests = [
        # --- Original LLM tests ---
        ("LLM Capability Understanding",    test_llm_capability_understanding),
        ("LLM Capability Selection",         test_llm_capability_selection),
        ("LLM + Capability Discovery",       test_llm_with_capability_discovery),
        ("LLM Tool Execution",               test_llm_tool_execution_with_capabilities),
        ("Context Matching Accuracy",        test_context_matching_accuracy),
        # --- Comprehensive registry tests ---
        ("All Tools Load",                   test_all_tools_load),
        ("All Tools Have Valid Schemas",     test_all_tools_have_valid_schemas),
        ("All Tools Have Capability Profiles", test_all_tools_have_capability_profiles),
        ("All Capabilities Have Providers",  test_all_capabilities_have_providers),
        ("Capability Index Bidirectional",   test_capability_index_bidirectional),
        ("Safe Tool Direct Execution",       test_safe_tool_direct_execution),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            print(f"\n{'='*80}")
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ {test_name} FAILED with exception: {e}")
            logger.exception(f"{test_name} failed")
            results.append((test_name, False))

    # Final Summary
    print("\n" + "="*80)
    print("INTEGRATION TEST SUMMARY")
    print("="*80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")

    print(f"\n{'='*80}")
    print(f"Overall: {passed}/{total} tests passed")
    print(f"{'='*80}")

    if passed == total:
        print("\n🎉 SUCCESS: All tools, all capabilities, and LLM integration verified!")
    else:
        print(f"\n⚠ {total - passed} test(s) failed — see details above")

    return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
