#!/usr/bin/env python3
"""
Integration Test: LLM + Security Capability Discovery
======================================================

Tests that the LLM correctly:
1. Understands security tool capabilities
2. Selects appropriate security capabilities for security tasks
3. Discovers the right security tools via capability matching
4. Can reason about security threats using security tools
"""

import asyncio
import logging
import json

logging.basicConfig(
    level=logging.WARNING,  # Suppress noise, only show test output
    format='%(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_security_capability_inference():
    """Test 1: Security capability inference from task descriptions (no LLM needed)"""
    print("\n" + "="*80)
    print("TEST 1: Security Capability Inference (Regex Patterns)")
    print("="*80)

    from core.tools.capabilities import infer_capability_from_task, Capability

    test_cases = [
        {
            "task": "Scan the codebase for SQL injection vulnerabilities",
            "expected": [Capability.SCAN_SECURITY],
        },
        {
            "task": "Detect intrusion attempts in the access logs",
            "expected": [Capability.DETECT_INTRUSION],
        },
        {
            "task": "Encrypt sensitive user data before storing to database",
            "expected": [Capability.ENCRYPT_DATA],
        },
        {
            "task": "Search for hardcoded secrets and API keys in the source code",
            "expected": [Capability.MANAGE_SECRETS],
        },
        {
            "task": "Analyze a suspicious file for malware",
            "expected": [Capability.DETECT_THREAT],
        },
        {
            "task": "Run a security audit on the authentication module",
            "expected": [Capability.SCAN_SECURITY],
        },
        {
            "task": "Check for exposed credentials or passwords in git history",
            "expected": [Capability.MANAGE_SECRETS],
        },
        {
            "task": "Detect threats and block malicious IP addresses",
            "expected": [Capability.DETECT_THREAT],
        },
    ]

    passed = 0
    for case in test_cases:
        caps = infer_capability_from_task(case["task"])
        cap_names = list(caps.keys())

        matched = [e for e in case["expected"] if e in cap_names]
        if matched:
            print(f"  ✓ '{case['task'][:55]}...'")
            print(f"      → {[c.value for c in cap_names[:3]]}")
            passed += 1
        else:
            print(f"  ✗ '{case['task'][:55]}...'")
            print(f"      Expected: {[c.value for c in case['expected']]}")
            print(f"      Got:      {[c.value for c in cap_names[:3]]}")

    print(f"\n  Results: {passed}/{len(test_cases)} tasks correctly inferred")
    return passed == len(test_cases)


async def test_security_tool_discovery():
    """Test 2: Security tools discoverable via capability matching"""
    print("\n" + "="*80)
    print("TEST 2: Security Tool Discovery via Capabilities")
    print("="*80)

    from core.tools import get_tool_registry
    from core.tools.capabilities import Capability

    registry = get_tool_registry()

    # Security capabilities and expected tools that should provide them
    expected_providers = {
        Capability.DETECT_THREAT: ["scan_secrets", "check_ip_threat_intelligence", "hunt_threats"],
        Capability.DETECT_INTRUSION: ["detect_intrusion"],
        Capability.ENCRYPT_DATA: ["encrypt_file"],
        Capability.MANAGE_SECRETS: ["scan_secrets"],
        Capability.SCAN_SECURITY: ["scan_secrets", "detect_intrusion"],
    }

    passed = 0
    for cap, expected_tools in expected_providers.items():
        providers = registry.find_providers(cap)
        provider_names = [t.name for t in providers]

        found = [t for t in expected_tools if t in provider_names]
        if found:
            print(f"  ✓ {cap.value}: {provider_names[:4]}")
            passed += 1
        else:
            print(f"  ✗ {cap.value}: no expected tools found")
            print(f"      Expected one of: {expected_tools}")
            print(f"      Available:       {provider_names[:5]}")

    print(f"\n  Results: {passed}/{len(expected_providers)} capabilities have correct tool providers")
    return passed == len(expected_providers)


async def test_llm_security_capability_selection():
    """Test 3: LLM selects correct security capabilities for security tasks"""
    print("\n" + "="*80)
    print("TEST 3: LLM Security Capability Selection")
    print("="*80)

    from core.services.unified_llm import get_llm_service

    llm = get_llm_service()

    available_capabilities = [
        "SCAN_SECURITY",
        "DETECT_THREAT",
        "DETECT_INTRUSION",
        "MANAGE_SECRETS",
        "ENCRYPT_DATA",
        "GENERATE_CODE",
        "ANALYZE_PERFORMANCE",
        "READ_DATA",
    ]

    security_tasks = [
        {
            "task": "Find SQL injection and XSS vulnerabilities in the web application",
            "expected": ["SCAN_SECURITY"],
        },
        {
            "task": "Search the codebase for exposed API keys and hardcoded passwords",
            "expected": ["MANAGE_SECRETS"],
        },
        {
            "task": "Detect and block suspicious intrusion attempts from the server logs",
            "expected": ["DETECT_INTRUSION", "DETECT_THREAT"],
        },
        {
            "task": "Encrypt user PII data before writing to the database",
            "expected": ["ENCRYPT_DATA"],
        },
    ]

    passed = 0
    for case in security_tasks:
        print(f"\n  Task: {case['task'][:65]}...")

        prompt = f"""Given this security task: "{case['task']}"

Which capabilities are needed from this list?
{json.dumps(available_capabilities, indent=2)}

Return ONLY a JSON array of capability names. Example: ["SCAN_SECURITY"]
No explanation, just the JSON array."""

        result = await llm.generate(
            prompt=prompt,
            temperature=0.1,
            max_tokens=80,
            agent_type="test"
        )

        response = result.get("content", "").strip()

        try:
            start = response.find('[')
            end = response.rfind(']') + 1
            if start >= 0 and end > start:
                selected = json.loads(response[start:end])
            else:
                selected = []

            matches = [c for c in case["expected"] if c in selected]
            if matches:
                print(f"  ✓ LLM selected: {selected} (matched: {matches})")
                passed += 1
            else:
                print(f"  ✗ LLM selected: {selected}")
                print(f"    Expected one of: {case['expected']}")

        except json.JSONDecodeError:
            print(f"  ✗ Invalid JSON response: {response[:80]}")

    print(f"\n  Results: {passed}/{len(security_tasks)} tasks correctly classified")
    return passed >= len(security_tasks) * 0.75  # Pass if 75%+ correct


async def test_llm_security_task_execution():
    """Test 4: LLM executes a security task using capability-discovered tools"""
    print("\n" + "="*80)
    print("TEST 4: LLM Security Task Execution")
    print("="*80)

    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
    from core.agents.autonomous.shared_types import Task, TaskType, Priority, TaskSource

    executor = GeneralPurposeExecutor()
    await executor.initialize()

    task = Task(
        id="test_security_001",
        type=TaskType.ANALYSIS,
        description="Scan the TorinAI codebase for hardcoded secrets, exposed API keys, or credentials in source files. Report any findings.",
        priority=Priority.HIGH,
        source=TaskSource.SYSTEM,
        created_by="security_test"
    )

    print(f"\n  Task: {task.description[:70]}...")

    # Check which tools get discovered for this task
    discovered = await executor._get_tools_by_capability(task.description)
    security_tools = [t for t in discovered.keys()
                      if any(kw in t for kw in ['secret', 'security', 'scan', 'pii', 'threat', 'intrusion', 'encrypt'])]

    print(f"\n  Discovered tools: {list(discovered.keys())[:8]}")
    print(f"  Security-specific tools: {security_tools}")

    if security_tools:
        print(f"  ✓ Security tools correctly discovered via capability matching")
        result = await executor.execute_task(task)
        print(f"\n  Execution result:")
        print(f"    Success: {result.get('success', False)}")
        confidence = result.get('confidence', result.get('outputs', {}).get('confidence', 0.0))
        print(f"    Confidence: {confidence}")
        return True
    else:
        print(f"  ✗ No security tools discovered - capability mapping not working")
        return False


async def main():
    print("\n" + "="*80)
    print("LLM + SECURITY CAPABILITY INTEGRATION TEST")
    print("="*80)
    print("Verifying: LLM correctly understands and discovers security tools")
    print("="*80)

    tests = [
        ("Security Capability Inference",    test_security_capability_inference),
        ("Security Tool Discovery",          test_security_tool_discovery),
        ("LLM Security Capability Selection", test_llm_security_capability_selection),
        ("LLM Security Task Execution",      test_llm_security_task_execution),
    ]

    results = []
    for name, fn in tests:
        try:
            result = await fn()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} FAILED with exception: {e}")
            logger.exception(f"{name} failed")
            results.append((name, False))

    print("\n" + "="*80)
    print("SECURITY TEST SUMMARY")
    print("="*80)

    passed = sum(1 for _, r in results if r)
    for name, result in results:
        print(f"{'✓ PASS' if result else '✗ FAIL'}: {name}")

    print(f"\nOverall: {passed}/{len(results)} tests passed")
    print("="*80)

    if passed == len(results):
        print("\n🎉 SUCCESS: LLM + security capability system fully working!")
    else:
        print(f"\n⚠ {len(results) - passed} test(s) failed")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
