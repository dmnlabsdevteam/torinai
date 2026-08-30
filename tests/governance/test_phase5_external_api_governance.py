#!/usr/bin/env python3
"""
Phase 5B: External API Governance Tests
Using TestBase for MySQL logging
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root and tests directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tests"))

from test_base import TestBase
from core.integration.external_api_integration_manager import (
    ExternalAPIIntegrationManager,
    APIStatus,
    APISafetyReason
)


class TestPhase5BExternalAPIGovernance(TestBase):
    """Phase 5B: External API Governance - MySQL Logged Tests"""

    def __init__(self):
        super().__init__(
            test_category="governance_phase5b",
            test_type="integration"
        )
        self.manager = None

    @pytest.mark.asyncio
    async def test_1_safe_api_auto_added(self):
        """Trusted HTTPS API should be auto-added"""
        self.manager = ExternalAPIIntegrationManager()

        result = await self.manager.add_api(
            api_url="https://api.github.com/repos",
            api_name="GitHub Repos API",
            use_case="Fetch repository information"
        )

        assert result.status == APIStatus.ADDED, f"Expected ADDED, got {result.status}"
        assert result.reason == APISafetyReason.TRUSTED_DOMAIN, f"Expected TRUSTED_DOMAIN, got {result.reason}"
        assert self.manager.apis_added_count == 1
        assert "https://api.github.com/repos" in self.manager.api_registry

    @pytest.mark.asyncio
    async def test_2_http_api_blocked(self):
        """HTTP API should be blocked (HTTPS required)"""
        self.manager = ExternalAPIIntegrationManager()

        result = await self.manager.add_api(
            api_url="http://insecure-api.com/data",
            api_name="Insecure API",
            use_case="Data retrieval"
        )

        assert result.status == APIStatus.BLOCKED, f"Expected BLOCKED, got {result.status}"
        assert result.reason == APISafetyReason.HTTP_ONLY, f"Expected HTTP_ONLY, got {result.reason}"
        assert self.manager.apis_blocked_count == 1
        assert result.governance_triggered == True, "Governance should be triggered for blocked APIs"

    @pytest.mark.asyncio
    async def test_3_malicious_domain_blocked(self):
        """Known malicious domain should be blocked"""
        self.manager = ExternalAPIIntegrationManager()

        result = await self.manager.add_api(
            api_url="https://malicious-example.com/api",
            api_name="Malicious API",
            use_case="Data collection"
        )

        assert result.status == APIStatus.BLOCKED, f"Expected BLOCKED, got {result.status}"
        assert result.reason == APISafetyReason.MALICIOUS_DOMAIN, f"Expected MALICIOUS_DOMAIN, got {result.reason}"
        assert self.manager.apis_blocked_count == 1
        assert result.governance_triggered == True

    @pytest.mark.asyncio
    async def test_4_suspicious_use_case_blocked(self):
        """Suspicious use case with harmful keywords should be blocked"""
        self.manager = ExternalAPIIntegrationManager()

        result = await self.manager.add_api(
            api_url="https://safe-domain.com/api",
            api_name="Hacking Tools API",
            use_case="Retrieve exploit database for credential theft"
        )

        assert result.status == APIStatus.BLOCKED, f"Expected BLOCKED, got {result.status}"
        assert result.reason == APISafetyReason.SUSPICIOUS_USE_CASE, f"Expected SUSPICIOUS_USE_CASE, got {result.reason}"
        assert self.manager.apis_blocked_count == 1
        assert "exploit" in result.message.lower() or "credential" in result.message.lower()

    @pytest.mark.asyncio
    async def test_5_unknown_domain_flagged(self):
        """Unknown domain should be flagged for review"""
        self.manager = ExternalAPIIntegrationManager()

        result = await self.manager.add_api(
            api_url="https://unknown-startup-api.io/v1/data",
            api_name="Unknown Startup API",
            use_case="Data analytics service"
        )

        assert result.status == APIStatus.FLAGGED, f"Expected FLAGGED, got {result.status}"
        assert result.reason == APISafetyReason.UNKNOWN_DOMAIN, f"Expected UNKNOWN_DOMAIN, got {result.reason}"
        assert self.manager.apis_flagged_count == 1
        assert result.governance_triggered == True

        # Verify added to registry as flagged
        assert "https://unknown-startup-api.io/v1/data" in self.manager.api_registry
        entry = self.manager.api_registry["https://unknown-startup-api.io/v1/data"]
        assert entry.flagged_for_review == True

    @pytest.mark.asyncio
    async def test_6_multiple_apis_metrics(self):
        """Test metrics tracking across multiple API additions"""
        self.manager = ExternalAPIIntegrationManager()

        # Add 3 safe APIs
        await self.manager.add_api("https://github.com/api", "GitHub", "Code hosting")
        await self.manager.add_api("https://docs.python.org/api", "Python Docs", "Documentation")
        await self.manager.add_api("https://stackoverflow.com/api", "StackOverflow", "Q&A")

        # Add 2 blocked APIs
        await self.manager.add_api("http://unsafe.com/api", "Unsafe", "Data")
        await self.manager.add_api("https://malicious-example.com/api", "Malicious", "Data")

        # Add 1 flagged API
        await self.manager.add_api("https://new-service.xyz/api", "New Service", "Analytics")

        assert self.manager.apis_added_count == 3, f"Expected 3 added, got {self.manager.apis_added_count}"
        assert self.manager.apis_blocked_count == 2, f"Expected 2 blocked, got {self.manager.apis_blocked_count}"
        assert self.manager.apis_flagged_count == 1, f"Expected 1 flagged, got {self.manager.apis_flagged_count}"
        assert self.manager.governance_triggered_count >= 3, "Governance should trigger for blocked/flagged APIs"

    async def run_all_tests(self):
        """Run all Phase 5B tests"""
        await self.start_session()

        await self.run_test(
            "test_1_safe_api_auto_added",
            self.test_1_safe_api_auto_added,
            metadata={
                "description": "Trusted HTTPS API should be auto-added",
                "expected_behavior": "API added to registry without governance approval",
                "api_url": "https://api.github.com/repos",
                "expected_status": "ADDED",
                "expected_reason": "TRUSTED_DOMAIN"
            }
        )

        await self.run_test(
            "test_2_http_api_blocked",
            self.test_2_http_api_blocked,
            metadata={
                "description": "HTTP API should be blocked (HTTPS required)",
                "expected_behavior": "API blocked and governance triggered",
                "api_url": "http://insecure-api.com/data",
                "expected_status": "BLOCKED",
                "expected_reason": "HTTP_ONLY"
            }
        )

        await self.run_test(
            "test_3_malicious_domain_blocked",
            self.test_3_malicious_domain_blocked,
            metadata={
                "description": "Known malicious domain should be blocked",
                "expected_behavior": "API blocked due to domain blacklist",
                "api_url": "https://malicious-example.com/api",
                "expected_status": "BLOCKED",
                "expected_reason": "MALICIOUS_DOMAIN"
            }
        )

        await self.run_test(
            "test_4_suspicious_use_case_blocked",
            self.test_4_suspicious_use_case_blocked,
            metadata={
                "description": "Suspicious use case with harmful keywords should be blocked",
                "expected_behavior": "API blocked due to suspicious keywords in use case",
                "use_case": "Retrieve exploit database for credential theft",
                "expected_status": "BLOCKED",
                "expected_reason": "SUSPICIOUS_USE_CASE",
                "blocked_keywords": ["exploit", "credential", "theft"]
            }
        )

        await self.run_test(
            "test_5_unknown_domain_flagged",
            self.test_5_unknown_domain_flagged,
            metadata={
                "description": "Unknown domain should be flagged for review",
                "expected_behavior": "API flagged and added to registry for human review",
                "api_url": "https://unknown-startup-api.io/v1/data",
                "expected_status": "FLAGGED",
                "expected_reason": "UNKNOWN_DOMAIN"
            }
        )

        await self.run_test(
            "test_6_multiple_apis_metrics",
            self.test_6_multiple_apis_metrics,
            metadata={
                "description": "Test metrics tracking across multiple API additions",
                "expected_behavior": "Accurate counting of added/blocked/flagged APIs",
                "apis_tested": 6,
                "expected_added": 3,
                "expected_blocked": 2,
                "expected_flagged": 1
            }
        )

        await self.end_session()
        self.print_summary()


async def main():
    """Run Phase 5B tests"""
    tests = TestPhase5BExternalAPIGovernance()
    await tests.run_all_tests()
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
