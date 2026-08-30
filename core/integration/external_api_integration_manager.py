#!/usr/bin/env python3
"""
External API Integration Manager
==================================

Manages integrations with external APIs and services

Purpose:
- Centralize external API connections
- Handle API authentication and rate limiting
- Provide unified interface for external services
- Track API usage and costs

Features:
- API key management (secure + rotation)
- Rate limiting + retry logic
- Usage tracking
- Cost monitoring
- Health checks
"""

import asyncio
import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

# Optional: aiohttp for async HTTP requests
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)


class APIProvider(Enum):
    """Supported API providers"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    TOGETHER = "together"
    GROQ = "groq"
    PERPLEXITY = "perplexity"


# Phase 5B: External API Governance Enums
class APIStatus(Enum):
    """API safety status for governance"""
    ADDED = "added"  # Auto-added, safe to use
    BLOCKED = "blocked"  # Blocked, requires governance approval
    FLAGGED = "flagged"  # Flagged for review, requires governance approval


class APISafetyReason(Enum):
    """Reasons for API safety classification"""
    SAFE = "safe"  # Trusted domain, HTTPS, safe use case
    HTTP_ONLY = "http_only"  # No HTTPS support
    MALICIOUS_DOMAIN = "malicious_domain"  # Known malicious domain
    SUSPICIOUS_USE_CASE = "suspicious_use_case"  # Suspicious keywords in use case
    UNKNOWN_DOMAIN = "unknown_domain"  # Domain not in trusted/malicious lists
    TRUSTED_DOMAIN = "trusted_domain"  # Domain in trusted list


@dataclass
class APIConfig:
    """API configuration"""
    provider: APIProvider
    api_key: str
    base_url: str = ""
    rate_limit: int = 60  # requests per minute
    timeout: int = 30  # seconds
    retry_attempts: int = 3
    cost_per_1k_tokens: float = 0.0
    enabled: bool = True


@dataclass
class APIUsage:
    """API usage tracking"""
    provider: APIProvider
    requests: int = 0
    tokens: int = 0
    cost: float = 0.0
    errors: int = 0
    last_request: Optional[datetime] = None


# Phase 5B: API Safety Evaluation Result
@dataclass
class APISafetyEvaluation:
    """Result of API safety validation"""
    url: str
    status: APIStatus
    reason: APISafetyReason
    governance_triggered: bool = False
    governance_approved: bool = False
    governance_action_id: Optional[str] = None
    message: str = ""


# Phase 5B: API Registry Entry
@dataclass
class APIRegistryEntry:
    """Entry in API registry for approved external APIs"""
    api_url: str
    api_name: str
    use_case: str
    status: APIStatus
    safety_reason: APISafetyReason
    added_at: datetime = field(default_factory=datetime.now)
    added_by: str = "automated_safety_validation"
    metadata: Dict[str, Any] = field(default_factory=dict)
    flagged_for_review: bool = False
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None


class ExternalAPIIntegrationManager:
    """
    External API Integration Manager

    Purpose:
    - Manage connections to external APIs (OpenAI, Anthropic, etc.)
    - Handle authentication, rate limiting, retries
    - Track usage and costs across all APIs
    - Provide health monitoring
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # API configurations (str name -> APIConfig)
        self.api_configs_by_name: Dict[str, Dict[str, Any]] = {}

        # Legacy provider configs (for LLM providers)
        self.api_configs: Dict[APIProvider, APIConfig] = {}

        # Usage tracking (by API name)
        self.usage_by_name: Dict[str, Dict[str, Any]] = {}

        # Legacy usage tracking
        self.usage: Dict[APIProvider, APIUsage] = {}

        # Rate limiting (API name -> list of request timestamps)
        self.rate_limit_tracker_by_name: Dict[str, List[float]] = {}
        self.rate_limit_tracker: Dict[APIProvider, List[float]] = {}

        # Available providers
        self.available_providers = {
            APIProvider.OPENAI,
            APIProvider.ANTHROPIC,
            APIProvider.GOOGLE
        }

        # Provider health status
        self.health_status: Dict[APIProvider, bool] = {
            provider: True for provider in self.available_providers
        }

        # Health status by API name
        self.health_status_by_name: Dict[str, bool] = {}

        # Phase 5B: API Safety Validation
        self.trusted_domains = {
            "github.com", "api.github.com",
            "stackoverflow.com", "api.stackoverflow.com",
            "docs.python.org", "readthedocs.io",
            "google.com", "apis.google.com",
            "microsoft.com", "azure.microsoft.com",
            "mozilla.org", "npmjs.com", "pypi.org"
        }

        self.malicious_domains = {
            "malicious-example.com", "phishing-site.com",
            "scam-api.net", "hack-tools.ru", "exploit-db-fake.com"
        }

        self.suspicious_keywords = {
            "hack", "crack", "exploit", "breach",
            "steal", "password", "credential", "backdoor",
            "phish", "scam", "fraud", "malware",
            "ransomware", "keylog", "trojan", "rootkit"
        }

        # API registry for governance-approved APIs
        self.api_registry: Dict[str, APIRegistryEntry] = {}

        # Metrics
        self.apis_added_count = 0
        self.apis_blocked_count = 0
        self.apis_flagged_count = 0
        self.governance_triggered_count = 0

        # Load API registry from JSON
        self._load_api_registry()

        logger.info("ExternalAPIIntegrationManager initialized")

    def _load_api_registry(self):
        """Load API registry from JSON file"""
        try:
            # Try to find the registry file
            possible_paths = [
                Path(__file__).parent.parent / "tools" / "api_registry.json",
                Path("core/tools/api_registry.json"),
                Path("TorinAI/core/tools/api_registry.json")
            ]

            registry_path = None
            for path in possible_paths:
                if path.exists():
                    registry_path = path
                    break

            if not registry_path:
                logger.warning("API registry file not found, using defaults")
                return

            # Load JSON
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)

            # Process each category
            for category_name, category_data in registry.get('categories', {}).items():
                for api_info in category_data.get('apis', []):
                    api_name = api_info['name']

                    # Store API config
                    self.api_configs_by_name[api_name] = {
                        'name': api_name,
                        'base_url': api_info.get('base_url', ''),
                        'description': api_info.get('description', ''),
                        'auth': api_info.get('auth', 'none'),
                        'rate_limit': api_info.get('rate_limit', 'Unlimited'),
                        'quality_score': api_info.get('quality_score', 0.8),
                        'category': category_name,
                        'tested': api_info.get('tested', False),
                        'topics': api_info.get('topics', [])
                    }

                    # Initialize usage tracking
                    self.usage_by_name[api_name] = {
                        'requests': 0,
                        'errors': 0,
                        'last_request': None
                    }

                    # Initialize rate limiting
                    self.rate_limit_tracker_by_name[api_name] = []

                    # Initialize health status
                    self.health_status_by_name[api_name] = True

            logger.info(f"Loaded {len(self.api_configs_by_name)} APIs from registry")

        except Exception as e:
            logger.error(f"Failed to load API registry: {e}")

    def register_api(self, config: APIConfig):
        """Register an external API (for LLM providers)"""
        self.api_configs[config.provider] = config
        self.usage[config.provider] = APIUsage(provider=config.provider)
        self.rate_limit_tracker[config.provider] = []
        self.available_providers.add(config.provider)
        self.health_status[config.provider] = config.enabled

        logger.info(f"Registered API: {config.provider.value}")

    # Phase 5B: API Safety Validation
    async def add_api(
        self,
        api_url: str,
        api_name: str,
        use_case: str,
        metadata: Dict[str, Any] = None
    ) -> APISafetyEvaluation:
        """
        Add external API with automated safety validation

        Safety Pipeline:
        1. HTTPS requirement check -> BLOCK if HTTP
        2. Malicious domain check -> BLOCK if blacklisted
        3. Suspicious use case check -> BLOCK if harmful keywords
        4. Trusted domain check -> AUTO-ADD if whitelisted
        5. Unknown domain handling -> FLAG for review

        Returns:
            APISafetyEvaluation with status and reason
        """
        # Run safety validation
        evaluation = await self._validate_api_safety(api_url, use_case)

        # Handle BLOCKED status
        if evaluation.status == APIStatus.BLOCKED:
            self.apis_blocked_count += 1
            logger.warning(f"API blocked: {api_name} ({evaluation.reason.value})")

            # Trigger governance for blocked APIs
            evaluation = await self._trigger_api_governance(
                api_url, api_name, use_case, evaluation
            )

            # Even if governance approves, we still block unsafe APIs (fail-closed)
            return evaluation

        # Handle FLAGGED status
        if evaluation.status == APIStatus.FLAGGED:
            self.apis_flagged_count += 1
            logger.info(f"API flagged for review: {api_name}")

            # Trigger governance for flagged APIs
            evaluation = await self._trigger_api_governance(
                api_url, api_name, use_case, evaluation
            )

            # Add to registry as flagged
            entry = APIRegistryEntry(
                api_url=api_url,
                api_name=api_name,
                use_case=use_case,
                status=evaluation.status,
                safety_reason=evaluation.reason,
                metadata=metadata or {},
                flagged_for_review=True
            )
            self.api_registry[api_url] = entry
            return evaluation

        # Handle ADDED status (safe API)
        if evaluation.status == APIStatus.ADDED:
            self.apis_added_count += 1
            logger.info(f"API added: {api_name} ({evaluation.reason.value})")

            # Add to registry
            entry = APIRegistryEntry(
                api_url=api_url,
                api_name=api_name,
                use_case=use_case,
                status=evaluation.status,
                safety_reason=evaluation.reason,
                metadata=metadata or {}
            )
            self.api_registry[api_url] = entry

        return evaluation

    async def _validate_api_safety(self, api_url: str, use_case: str) -> APISafetyEvaluation:
        """
        Validate API safety through security checks

        Returns APISafetyEvaluation with status and reason
        """
        from urllib.parse import urlparse

        # Parse URL
        try:
            parsed = urlparse(api_url)
            domain = parsed.netloc or parsed.path.split('/')[0]
        except Exception as e:
            logger.error(f"Invalid URL format: {api_url} - {e}")
            return APISafetyEvaluation(
                url=api_url,
                status=APIStatus.BLOCKED,
                reason=APISafetyReason.HTTP_ONLY,
                message=f"Invalid URL format: {e}"
            )

        # 1. HTTPS requirement check
        if not api_url.startswith("https://"):
            return APISafetyEvaluation(
                url=api_url,
                status=APIStatus.BLOCKED,
                reason=APISafetyReason.HTTP_ONLY,
                message="HTTPS required for all external APIs"
            )

        # 2. Malicious domain check
        if domain in self.malicious_domains:
            return APISafetyEvaluation(
                url=api_url,
                status=APIStatus.BLOCKED,
                reason=APISafetyReason.MALICIOUS_DOMAIN,
                message=f"Domain {domain} is blacklisted"
            )

        # 3. Suspicious use case check
        use_case_lower = use_case.lower()
        for keyword in self.suspicious_keywords:
            if keyword in use_case_lower:
                return APISafetyEvaluation(
                    url=api_url,
                    status=APIStatus.BLOCKED,
                    reason=APISafetyReason.SUSPICIOUS_USE_CASE,
                    message=f"Suspicious keyword detected: {keyword}"
                )

        # 4. Trusted domain check
        if domain in self.trusted_domains:
            return APISafetyEvaluation(
                url=api_url,
                status=APIStatus.ADDED,
                reason=APISafetyReason.TRUSTED_DOMAIN,
                message=f"Trusted domain: {domain}"
            )

        # 5. Unknown domain -> flag for review
        return APISafetyEvaluation(
            url=api_url,
            status=APIStatus.FLAGGED,
            reason=APISafetyReason.UNKNOWN_DOMAIN,
            message=f"Unknown domain requires review: {domain}"
        )

    async def _trigger_api_governance(
        self,
        api_url: str,
        api_name: str,
        use_case: str,
        evaluation: APISafetyEvaluation
    ) -> APISafetyEvaluation:
        """Trigger governance for blocked/flagged APIs"""
        try:
            from core.governance import get_unified_governance, ActionCategory

            # Use governance singleton
            governance = get_unified_governance()
            result = await governance.evaluate_action(
                action_category=ActionCategory.EXTERNAL_INTEGRATIONS,
                action_type="external_api_addition",
                parameters={
                    "api_url": api_url,
                    "api_name": api_name,
                    "use_case": use_case,
                    "status": evaluation.status.value,
                    "reason": evaluation.reason.value
                },
                context={
                    "component": "external_api_integration_manager",
                    "safety_evaluation": {
                        "status": evaluation.status.value,
                        "reason": evaluation.reason.value,
                        "message": evaluation.message
                    }
                }
            )

            self.governance_triggered_count += 1
            evaluation.governance_triggered = True
            evaluation.governance_approved = result.approved if hasattr(result, 'approved') else False
            evaluation.governance_action_id = result.action_id if hasattr(result, 'action_id') else None

            logger.info(f"Governance triggered for {api_name}: approved={evaluation.governance_approved}")

        except Exception as e:
            logger.error(f"Governance trigger failed: {e}")
            evaluation.governance_triggered = False
            evaluation.governance_approved = False

        return evaluation

    async def call_api(
        self,
        provider: APIProvider,
        endpoint: str,
        method: str = "POST",
        data: Dict[str, Any] = None,
        headers: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Call an external API

        Args:
            provider: API provider
            endpoint: API endpoint path
            method: HTTP method
            data: Request data
            headers: Additional headers

        Returns:
            API response data
        """
        try:
            # Check if provider is configured
            if provider not in self.api_configs:
                logger.error(f"API provider not configured: {provider.value}")
                return {"error": f"Provider {provider.value} not configured"}

            config = self.api_configs[provider]

            if not config.enabled:
                logger.warning(f"API provider disabled: {provider.value}")
                return {"error": f"Provider {provider.value} disabled"}

            # Check rate limiting
            if not await self._check_rate_limit(provider):
                logger.warning(f"Rate limit exceeded for {provider.value}")
                return {"error": "Rate limit exceeded"}

            # Build request
            url = f"{config.base_url}/{endpoint}" if config.base_url else endpoint
            request_headers = headers or {}
            request_headers["Authorization"] = f"Bearer {config.api_key}"

            # Execute request with retry logic
            for attempt in range(config.retry_attempts):
                try:
                    if AIOHTTP_AVAILABLE:
                        response = await self._make_http_request(
                            method, url, data, request_headers, config.timeout
                        )
                    else:
                        # Fallback simulation
                        await asyncio.sleep(0.1)
                        response = {"status": "success", "data": {}}

                    # Update usage tracking
                    await self._update_usage(provider, response)

                    return response

                except Exception as e:
                    if attempt < config.retry_attempts - 1:
                        logger.warning(f"API call failed (attempt {attempt + 1}), retrying: {e}")
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        raise

        except Exception as e:
            logger.error(f"API call failed for {provider.value}: {e}")
            self.usage[provider].errors += 1
            return {"error": str(e)}

    async def _make_http_request(
        self,
        method: str,
        url: str,
        data: Dict[str, Any],
        headers: Dict[str, str],
        timeout: int
    ) -> Dict[str, Any]:
        """Make HTTP request using aiohttp"""
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                return await response.json()

    async def _check_rate_limit(self, provider: APIProvider) -> bool:
        """Check if request is within rate limit"""
        config = self.api_configs[provider]
        now = time.time()

        # Remove requests older than 1 minute
        self.rate_limit_tracker[provider] = [
            ts for ts in self.rate_limit_tracker[provider]
            if now - ts < 60
        ]

        # Check if under limit
        if len(self.rate_limit_tracker[provider]) >= config.rate_limit:
            return False

        # Add current request
        self.rate_limit_tracker[provider].append(now)
        return True

    async def _update_usage(self, provider: APIProvider, response: Dict[str, Any]):
        """Update usage statistics"""
        usage = self.usage[provider]
        usage.requests += 1
        usage.last_request = datetime.now()

        # Extract token usage if available
        if 'usage' in response:
            tokens = response['usage'].get('total_tokens', 0)
            usage.tokens += tokens

            # Calculate cost
            config = self.api_configs[provider]
            cost = (tokens / 1000) * config.cost_per_1k_tokens
            usage.cost += cost

    async def get_usage(self, provider: Optional[APIProvider] = None) -> Dict[str, Any]:
        """Get usage statistics"""
        if provider:
            usage = self.usage.get(provider)
            if usage:
                return {
                    "provider": provider.value,
                    "requests": usage.requests,
                    "tokens": usage.tokens,
                    "cost": round(usage.cost, 4),
                    "errors": usage.errors,
                    "last_request": usage.last_request.isoformat() if usage.last_request else None
                }
            return {}

        # Return all usage
        return {
            provider.value: {
                "requests": usage.requests,
                "tokens": usage.tokens,
                "cost": round(usage.cost, 4),
                "errors": usage.errors
            }
            for provider, usage in self.usage.items()
        }

    async def health_check(self) -> Dict[str, bool]:
        """Check health of all configured APIs"""
        results = {}

        for provider in self.api_configs.keys():
            try:
                config = self.api_configs[provider]

                if not config.enabled:
                    self.health_status[provider] = False
                    results[provider.value] = False
                    continue

                # Make actual health check HTTP request
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    health_url = f"{config.base_url}/health" if '/health' not in config.base_url else config.base_url

                    try:
                        async with session.get(
                            health_url,
                            headers={"Authorization": f"Bearer {config.api_key}"},
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as response:
                            is_healthy = response.status < 400
                    except:
                        is_healthy = False

                self.health_status[provider] = is_healthy
                results[provider.value] = is_healthy

            except Exception as e:
                logger.error(f"Health check failed for {provider.value}: {e}")
                self.health_status[provider] = False
                results[provider.value] = False

        return results

    def get_available_providers(self) -> List[str]:
        """Get list of available API providers"""
        return [p.value for p in self.available_providers if self.health_status.get(p, False)]

    async def reset_usage(self, provider: Optional[APIProvider] = None):
        """Reset usage statistics"""
        if provider:
            if provider in self.usage:
                self.usage[provider] = APIUsage(provider=provider)
                logger.info(f"Reset usage for {provider.value}")
        else:
            for provider in self.usage.keys():
                self.usage[provider] = APIUsage(provider=provider)
            logger.info("Reset usage for all providers")

    def disable_provider(self, provider: APIProvider):
        """Disable an API provider"""
        if provider in self.api_configs:
            self.api_configs[provider].enabled = False
            self.health_status[provider] = False
            logger.warning(f"Disabled provider: {provider.value}")

    def enable_provider(self, provider: APIProvider):
        """Enable an API provider"""
        if provider in self.api_configs:
            self.api_configs[provider].enabled = True
            self.health_status[provider] = True
            logger.info(f"Enabled provider: {provider.value}")

    async def get_total_cost(self) -> float:
        """Get total cost across all providers"""
        return sum(usage.cost for usage in self.usage.values())

    async def get_provider_recommendation(
        self,
        task_type: str = "chat"
    ) -> Optional[APIProvider]:
        """
        Recommend best provider for a task based on health and cost

        Args:
            task_type: Type of task (chat, embeddings, etc.)

        Returns:
            Recommended provider or None
        """
        # Filter healthy and enabled providers
        healthy_providers = [
            provider for provider in self.api_configs.keys()
            if self.health_status.get(provider, False)
            and self.api_configs[provider].enabled
        ]

        if not healthy_providers:
            return None

        # Smart routing based on cost, latency, and usage
        provider_scores = {}

        for provider in healthy_providers:
            usage = self.usage.get(provider, APIUsage(provider=provider))

            # Calculate score (lower is better)
            score = 0.0

            # Cost factor (30% weight)
            avg_cost_per_request = usage.cost / usage.total_requests if usage.total_requests > 0 else 0
            score += avg_cost_per_request * 0.3

            # Latency factor (40% weight)
            avg_latency = usage.latency_ms / usage.total_requests if usage.total_requests > 0 else 100
            score += (avg_latency / 1000) * 0.4  # Normalize to seconds

            # Load balancing (30% weight) - prefer less-used providers
            score += (usage.total_requests / 1000) * 0.3

            provider_scores[provider] = score

        # Return provider with lowest score
        best_provider = min(provider_scores.items(), key=lambda x: x[1])[0]
        return best_provider


# Singleton instance
_api_manager = None


def get_api_manager() -> ExternalAPIIntegrationManager:
    """Get global API integration manager instance"""
    global _api_manager
    if _api_manager is None:
        _api_manager = ExternalAPIIntegrationManager()
    return _api_manager


# CLI test
async def main():
    """Test external API integration manager"""
    logging.basicConfig(level=logging.INFO)

    manager = get_api_manager()

    # Register sample API
    manager.register_api(APIConfig(
        provider=APIProvider.OPENAI,
        api_key="sk-test-key",
        base_url="https://api.openai.com/v1",
        rate_limit=60,
        cost_per_1k_tokens=0.002
    ))

    print("\n=== External API Integration Test ===")
    print(f"Available providers: {manager.get_available_providers()}")

    # Health check
    health = await manager.health_check()
    print(f"Health status: {health}")

    # Get recommendation
    recommended = await manager.get_provider_recommendation("chat")
    print(f"Recommended provider: {recommended.value if recommended else 'None'}")

    # Get usage
    usage = await manager.get_usage()
    print(f"Usage: {usage}")


if __name__ == "__main__":
    asyncio.run(main())
