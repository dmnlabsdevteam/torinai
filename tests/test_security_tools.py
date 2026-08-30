#!/usr/bin/env python3
"""
Test suite for ALL security tools - REAL LLM USAGE with TestBase
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Add tests directory for test_base
tests_dir = Path(__file__).parent
sys.path.insert(0, str(tests_dir))

from test_base import TestBase
from core.services.unified_llm import get_llm_service
from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
from core.agents.autonomous.shared_types import Task, TaskType, Priority


class SecurityToolsTests(TestBase):
    """Security tools test suite with TestBase integration"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="security_tools"
        )

        # Initialize LLM and executor
        self.llm = None
        self.executor = None

        # Test directory setup
        self.test_dir = Path("/Users/stefan/Dominion Labs/TorinAI/data/tool_tests/security")
        self.test_dir.mkdir(parents=True, exist_ok=True)

        # Security tools to test
        self.security_tools = [
            "encrypt_file",
            "decrypt_file",
            "generate_password",
            "hash_data",
            "validate_certificate",
            "scan_secrets",
            "check_ip_threat_intelligence",
            "block_ip_address",
            "unblock_ip_address",
            "get_active_blocks",
            "create_waf_rule",
            "apply_rate_limit",
            "block_country",
            "get_security_metrics",
            "get_block_history",
            "add_internal_threat",
            "sanitize_input",
            "detect_intrusion",
            "analyze_anomaly",
            "monitor_logs",
            "detect_brute_force",
            "analyze_traffic_pattern",
            "auto_respond_threat",
            "hunt_threats",
            "detect_zero_day"
        ]

    async def setup_llm(self):
        """Initialize LLM and executor"""
        print("\n[SETUP] Loading LLM...")
        self.llm = get_llm_service()
        await self.llm.initialize()
        self.executor = GeneralPurposeExecutor(torin_brain=self.llm)
        await self.executor.initialize()
        print("✓ LLM loaded and executor initialized")

        # Create test files
        test_file = self.test_dir / "test_data.txt"
        test_file.write_text("Secret data to test")

        log_file = self.test_dir / "test.log"
        log_file.write_text("2025-01-23 10:00:00 INFO Normal activity\n2025-01-23 10:01:00 ERROR Failed login attempt\n")

    async def teardown_llm(self):
        """Cleanup LLM"""
        if self.llm and hasattr(self.llm, 'shutdown'):
            await self.llm.shutdown()

    def _get_tool_prompt(self, tool_name: str) -> str:
        """Generate appropriate prompt for each tool"""
        if "encrypt_file" in tool_name:
            return f"Use {tool_name} to encrypt the file at {self.test_dir}/test_data.txt with password 'test123' using AES-256"
        elif "decrypt_file" in tool_name:
            return f"Use {tool_name} to decrypt the file at {self.test_dir}/encrypted_test_data.txt with password 'test123' and save to {self.test_dir}/decrypted.txt"
        elif "generate_password" in tool_name:
            return f"Use {tool_name} to generate a random password with 16 characters"
        elif "hash_data" in tool_name:
            return f"Use {tool_name} to hash the text 'hello world' using SHA-256"
        elif "validate_certificate" in tool_name:
            return f"Use {tool_name} to validate the SSL certificate for hostname example.com"
        elif "scan_secrets" in tool_name:
            return f"Use {tool_name} to scan directory {self.test_dir} for secrets like passwords or API keys"
        elif "check_ip_threat_intelligence" in tool_name:
            return f"Use {tool_name} to check if IP address 8.8.8.8 is on any threat lists"
        elif "unblock_ip_address" in tool_name:
            return f"Use {tool_name} to REMOVE the block on IP address 192.168.1.100 and allow it again (unblock operation)"
        elif "block_ip_address" in tool_name:
            return f"Use {tool_name} to block IP address 192.168.1.100 for security reasons"
        elif "get_active_blocks" in tool_name:
            return f"Use {tool_name} to get list of currently blocked IP addresses"
        elif "create_waf_rule" in tool_name:
            return f"Use {tool_name} to create a WAF rule with expression='(http.request.uri.path contains \"malicious\")' description='Block malicious URLs' action='block' priority=50"
        elif "apply_rate_limit" in tool_name:
            return f"Use {tool_name} to apply rate limiting to IP address 192.168.1.50 with 100 requests per minute"
        elif "block_country" in tool_name:
            return f"Use {tool_name} to block traffic from country code XX"
        elif "get_security_metrics" in tool_name:
            return f"Use {tool_name} to get security metrics for the past hour"
        elif "get_block_history" in tool_name:
            return f"Use {tool_name} to retrieve the history of blocked IPs"
        elif "add_internal_threat" in tool_name:
            return f"Use {tool_name} to add IP 10.0.0.5 to internal threat database with threat_types=['port_scan', 'suspicious_behavior'] and reputation_score=0.7"
        elif "sanitize_input" in tool_name:
            return f"Use {tool_name} to sanitize HTML input and remove any XSS attempts like <script>alert('xss')</script>"
        elif "detect_intrusion" in tool_name:
            return f"Use {tool_name} to detect intrusion attempts by analyzing log file {self.test_dir}/test.log"
        elif "analyze_anomaly" in tool_name:
            return f"Use {tool_name} to detect anomalies in the data sequence: 1, 2, 3, 100, 4, 5"
        elif "monitor_logs" in tool_name:
            return f"Use {tool_name} to monitor log file {self.test_dir}/test.log for error patterns"
        elif "detect_brute_force" in tool_name:
            return f"Use {tool_name} to detect brute force login attempts in log file {self.test_dir}/test.log"
        elif "analyze_traffic_pattern" in tool_name:
            return f"Use {tool_name} to analyze network traffic patterns for unusual activity"
        elif "auto_respond_threat" in tool_name:
            return f"Use {tool_name} to automatically respond to threat ID 'threat_001' by blocking it"
        elif "hunt_threats" in tool_name:
            return f"Use {tool_name} to hunt for threats by searching for indicators like 'malicious.com' or suspicious IPs"
        elif "detect_zero_day" in tool_name:
            return f"Use {tool_name} to detect potential zero-day threats based on unusual behavior patterns"
        else:
            return f"Use {tool_name} for security operation"

    async def run_tests(self):
        """Run all security tool tests"""
        print("=" * 80)
        print("SECURITY TOOLS TEST WITH LLM")
        print("=" * 80)

        await self.setup_llm()

        results = {
            "total": len(self.security_tools),
            "passed": 0,
            "failed": 0,
            "details": []
        }

        print(f"\n[INFO] Testing {len(self.security_tools)} security tools")
        print("=" * 80)

        for idx, tool_name in enumerate(self.security_tools, 1):
            prompt = self._get_tool_prompt(tool_name)

            task = Task(
                id=f"test_{tool_name}",
                type=TaskType.EXECUTION,
                description=prompt,
                priority=Priority.HIGH
            )

            try:
                print(f"\n{'='*80}")
                print(f"[{idx:3d}/{len(self.security_tools)}] Testing: {tool_name}")
                print(f"PROMPT: {prompt}")
                print(f"{'-'*80}")

                result = await self.executor.execute_task(task)

                print(f"LLM SUMMARY: {result.get('summary', 'No summary')}")
                print(f"TOOLS CALLED: {[tc['tool'] for tc in result.get('tool_results', [])]}")
                print(f"SUCCESS: {result.get('success', False)}")
                success = result.get('success', False)
                tool_calls = result.get('tool_results', [])
                tools_used = [tc['tool'] for tc in tool_calls]
                used_correct = tool_name in tools_used

                if used_correct and success:
                    results["passed"] += 1
                    status = "✓ PASS"
                else:
                    results["failed"] += 1
                    status = "✗ FAIL"

                results["details"].append({
                    "tool": tool_name,
                    "prompt": prompt,
                    "used_correct": used_correct,
                    "success": success,
                    "tools_used": tools_used
                })

                # Log result to MySQL via TestBase
                await self.log_test_result(
                    test_name=tool_name,
                    passed=used_correct and success,
                    error_message=None if (used_correct and success) else f"Used: {tools_used}",
                    duration=0.0,
                    test_data={"prompt": prompt, "tools_used": tools_used}
                )

                print(f"  [{idx:3d}] {status}: {tool_name}")

            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "tool": tool_name,
                    "error": str(e)
                })

                # Log error to MySQL
                await self.log_test_result(
                    test_name=tool_name,
                    passed=False,
                    error_message=str(e),
                    duration=0.0
                )

                print(f"  [{idx:3d}] ✗ ERR: {tool_name} - {str(e)[:40]}")

        await self.teardown_llm()

        print("\n" + "=" * 80)
        print(f"RESULTS: {results['passed']} passed, {results['failed']} failed")
        pass_rate = (results['passed'] / results['total'] * 100) if results['total'] > 0 else 0
        print(f"PASS RATE: {pass_rate:.1f}%")
        print("=" * 80)

        return results["failed"] == 0


async def main():
    """Main test runner"""
    test_suite = SecurityToolsTests()
    await test_suite.start_session()

    try:
        success = await test_suite.run_tests()
        await test_suite.end_session()
        return success
    except Exception as e:
        print(f"Test suite failed: {e}")
        await test_suite.end_session()
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
