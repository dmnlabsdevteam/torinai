"""
Upgrade Test Suite - Comprehensive Testing with Real Data
=========================================================
Comprehensive test harness for validating self-upgrades before deployment.

Features:
- Real data integration (no mocks/stubs)
- Performance benchmarking
- Regression testing
- Integration testing
- Database validation
- API contract testing

Author: Torin AI
"""

import asyncio
import json
# `os` is used at _test_core_ai_health (RUNNING_IN_DOCKER) and was never
# imported. The suite had zero callers, so the NameError had never been
# reached -- the test reported "Core AI service health check failed: name 'os'
# is not defined", which reads as the SERVICE being unhealthy when it is the
# test that is broken. Unrun code is not working code.
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import logging
import pytest
import sys

# Add workspace to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result from a single test.

    `passed` alone could not express "did not run". Seven of the fifteen tests
    return `{"status": "skipped"}` when their dependency is unavailable, and
    every one of them was counted as PASSED -- so a deployment gate asking
    "does the system still work" was answered by tests that never executed.
    """
    name: str
    passed: bool
    duration_seconds: float
    error: Optional[str] = None
    warnings: Optional[List[str]] = None
    metrics: Optional[Dict[str, Any]] = None
    #: The test could not run: a dependency it needs was unavailable. NOT a
    #: pass, and not a failure of the thing under test either.
    skipped: bool = False
    #: The thing this test covers is not part of this deployment at all.
    not_applicable: bool = False
    reason: Optional[str] = None


@dataclass
class TestSuiteResult:
    """Result from complete test suite"""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    test_results: List[TestResult]
    summary: str
    

class UpgradeTestSuite:
    """
    Comprehensive test suite for upgrade validation.
    
    Tests with real data:
    - Database integrity
    - API contracts
    - Service health
    - Performance benchmarks
    - Integration flows
    """
    
    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path
        self.test_results: List[TestResult] = []

    async def _get_postgres_db(self):
        """Best-effort access to the unified PostgreSQL manager.

        Upgrade tests must not assume a DB is running in every environment.
        """
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            init = getattr(db, "initialize", None)
            if init is not None:
                if asyncio.iscoroutinefunction(init):
                    await init()
                else:
                    init()
            return db
        except Exception as e:
            logger.warning(f"PostgreSQL not available for upgrade tests: {e}")
            return None
        
    async def run_all_tests(self) -> TestSuiteResult:
        """
        Run complete test suite.
        
        Returns:
            TestSuiteResult with all test outcomes
        """
        start_time = time.time()
        
        logger.info("Starting comprehensive test suite")
        
        # Database tests
        await self._run_test("Database Integrity", self._test_database_integrity)
        await self._run_test("Database Schema", self._test_database_schema)
        await self._run_test("Database Queries", self._test_database_queries)
        
        # Service health tests
        await self._run_test("Core AI Service", self._test_core_ai_health)
        await self._run_test("iOS API Service", self._test_ios_api_health)
        await self._run_test("Backend API Service", self._test_backend_api_health)
        
        # API contract tests
        await self._run_test("LLM API Contract", self._test_llm_api_contract)
        await self._run_test("Memory API Contract", self._test_memory_api_contract)
        await self._run_test("Learning API Contract", self._test_learning_api_contract)
        
        # Integration tests
        await self._run_test("End-to-End Flow", self._test_end_to_end_flow)
        await self._run_test("Service Communication", self._test_service_communication)
        
        # Performance tests
        await self._run_test("Response Time", self._test_response_time)
        await self._run_test("Memory Usage", self._test_memory_usage)
        await self._run_test("Throughput", self._test_throughput)
        
        # Regression tests
        await self._run_test("Known Issues", self._test_known_issues)
        
        duration = time.time() - start_time
        
        # Calculate results
        passed = sum(1 for r in self.test_results if r.passed)
        skipped = sum(1 for r in self.test_results if r.skipped)
        not_applicable = sum(1 for r in self.test_results if r.not_applicable)
        failed = sum(1 for r in self.test_results
                     if not r.passed and not r.skipped and not r.not_applicable)
        total = len(self.test_results)

        # `skipped=0` was HARDCODED, so the caller logged "0 skipped" over a run
        # where seven tests had not executed.
        summary = f"{passed}/{total} tests passed"
        if failed:
            summary += f", {failed} failed"
        if skipped:
            summary += f", {skipped} SKIPPED (not verified)"
        if not_applicable:
            summary += f", {not_applicable} n/a"

        result = TestSuiteResult(
            total_tests=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_seconds=duration,
            test_results=self.test_results,
            summary=summary
        )
        
        logger.info(f"Test suite complete: {summary} (took {duration:.2f}s)")
        
        return result
        
    async def _run_test(self, name: str, test_func: Callable) -> TestResult:
        """Run a single test and capture result"""
        logger.info(f"Running test: {name}")
        start_time = time.time()
        
        try:
            metrics = await test_func()
            duration = time.time() - start_time

            # THE TESTS ALREADY SAID SO AND NOBODY READ IT. Every skipping test
            # returns {"status": "skipped", "reason": ...}; this now honours it
            # instead of recording a pass for a test that did nothing.
            status = (metrics or {}).get("status") if isinstance(metrics, dict) else None
            reason = (metrics or {}).get("reason") if isinstance(metrics, dict) else None

            if status == "not_applicable":
                result = TestResult(name=name, passed=False, not_applicable=True,
                                    duration_seconds=duration, metrics=metrics,
                                    reason=reason)
                logger.info(f"— {name} not applicable ({reason})")
            elif status == "skipped":
                result = TestResult(name=name, passed=False, skipped=True,
                                    duration_seconds=duration, metrics=metrics,
                                    reason=reason)
                logger.warning(f"⊘ {name} SKIPPED ({reason}) — not verified")
            else:
                result = TestResult(name=name, passed=True,
                                    duration_seconds=duration, metrics=metrics)
                logger.info(f"✓ {name} passed ({duration:.2f}s)")
            
        except AssertionError as e:
            duration = time.time() - start_time
            result = TestResult(
                name=name,
                passed=False,
                duration_seconds=duration,
                error=str(e)
            )
            logger.error(f"✗ {name} failed: {e}")
            
        except Exception as e:
            duration = time.time() - start_time
            result = TestResult(
                name=name,
                passed=False,
                duration_seconds=duration,
                error=f"Unexpected error: {e}"
            )
            logger.error(f"✗ {name} error: {e}")
        
        self.test_results.append(result)
        return result
        
    # Database Tests
    
    async def _test_database_integrity(self) -> Dict[str, Any]:
        """Test database connectivity + basic health (PostgreSQL)."""
        db = await self._get_postgres_db()
        if not db:
            return {"status": "skipped", "reason": "postgres_unavailable"}

        row = await db.execute_query("SELECT 1 AS ok", fetch_one=True)
        assert row and row.get("ok") == 1, "Database connectivity check failed"

        # Basic catalog sanity
        count = await db.execute_query(
            "SELECT COUNT(*) AS tables FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')",
            fetch_one=True,
        )
        return {"status": "ok", "tables": int(count.get("tables", 0))}
        
    async def _test_database_schema(self) -> Dict[str, Any]:
        """Validate expected TorinAI schemas exist (PostgreSQL)."""
        db = await self._get_postgres_db()
        if not db:
            return {"status": "skipped", "reason": "postgres_unavailable"}

        rows = await db.execute_query(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('unified','memory_hot','memory_cold')",
            fetch_all=True,
        )
        found = sorted({r.get("schema_name") for r in (rows or []) if r.get("schema_name")})
        assert "unified" in found, "Expected schema 'unified' not found"

        return {
            "status": "ok",
            "schemas_found": found,
            "expected": ["unified", "memory_hot", "memory_cold"],
        }
        
    async def _test_database_queries(self) -> Dict[str, Any]:
        """Test simple PostgreSQL query execution."""
        db = await self._get_postgres_db()
        if not db:
            return {"status": "skipped", "reason": "postgres_unavailable"}

        start = time.time()
        row = await db.execute_query("SELECT now() AS ts", fetch_one=True)
        query_time = time.time() - start

        assert row and row.get("ts") is not None, "Failed to query current timestamp"
        return {"query_time_ms": query_time * 1000}
        
    # Service Health Tests
    
    async def _test_core_ai_health(self) -> Dict[str, Any]:
        """Test core-ai service health"""
        try:
            # Skip LLM initialization in Docker (backend delegates to core-ai service)
            is_docker = os.getenv("RUNNING_IN_DOCKER") == "true"
            if is_docker:
                return {
                    "status": "skipped",
                    "reason": "Docker environment - LLM handled by core-ai service",
                    "timestamp": time.time()
                }
            
            # Import and test UnifiedLLMService (local only)
            from core.services.unified_llm import get_llm_service

            service = get_llm_service()
            if hasattr(service, "__await__"):
                service = await service

            # ASK THE SERVICE WHAT IT RESOLVED. This asserted a hardcoded path
            # to `core/models/llama-3.1-70b-gguf` -- a Llama 3.1 70B, from an
            # architecture two models ago, in a directory models have never
            # lived in. The assertion could only fail, and it failed as "Model
            # path not found", which reads as the SERVICE being broken rather
            # than the test naming a model that does not exist.
            #
            # The service resolves its own weights and knows where it looked.
            # A remote backend is healthy with no local file at all, which the
            # old check had no way to express.
            remote_url = getattr(service, "remote_url", "") or ""
            local_path = getattr(service, "local_model_path", "") or ""
            models_dir = getattr(service, "models_dir", None)
            available = sorted(p.name for p in Path(models_dir).rglob("*.gguf")) \
                if models_dir else []

            if not remote_url and not local_path:
                raise AssertionError(
                    "no LLM backend configured: neither LLM_SERVER_URL nor a "
                    "local model path is set")
            if local_path and not Path(local_path).exists():
                raise AssertionError(
                    f"configured local model does not exist: {local_path}. "
                    f"GGUFs under {models_dir}: {available}")

            return {
                "status": "healthy",
                "backend": "remote" if remote_url else "local",
                "remote_url": remote_url,
                "local_model": Path(local_path).name if local_path else None,
                "models_available": available,
            }
            
        except Exception as e:
            raise AssertionError(f"Core AI service health check failed: {e}")
            
    #: Services this suite knows how to check, and the file that implements
    #: each. A path that is absent means the service is not part of this
    #: deployment -- which is not the same as the service being unwell.
    _SERVICE_ENTRYPOINTS = {
        "ios_api": ("servers", "ios_backend", "main.py"),
        "backend_api": ("servers", "chat", "backend_server.py"),
    }

    async def _check_service_entrypoint(self, service: str) -> Dict[str, Any]:
        """Whether a service's entry point exists AND imports.

        THIS REPORTED "healthy" FOR A FILE BEING ON DISK. Existence is not
        health -- a module that raises on import, or that was gutted, passed
        this identically to a working service. And when the file was ABSENT it
        returned "skipped", which `_run_test` counted as a pass, so both
        branches passed and the check could not fail either way.

        Measured: neither `servers/ios_backend/main.py` nor
        `servers/chat/backend_server.py` exists in this tree, so both of these
        "health" tests have only ever taken the absent branch.
        """
        import importlib.util

        path = self.workspace_path.joinpath(*self._SERVICE_ENTRYPOINTS[service])
        if not path.exists():
            return {"status": "not_applicable",
                    "reason": f"{service} is not part of this deployment "
                              f"({path} does not exist)"}

        spec = importlib.util.spec_from_file_location(f"_probe_{service}", path)
        if spec is None or spec.loader is None:
            raise AssertionError(f"{service} entry point at {path} is not importable")
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as error:
            raise AssertionError(
                f"{service} entry point failed to import: "
                f"{type(error).__name__}: {error}") from error

        return {"status": "healthy", "server_path": str(path), "imported": True}

    async def _test_ios_api_health(self) -> Dict[str, Any]:
        """Test ios-api service health"""
        return await self._check_service_entrypoint("ios_api")

    async def _test_backend_api_health(self) -> Dict[str, Any]:
        """Test backend-api service health"""
        return await self._check_service_entrypoint("backend_api")
        
    # API Contract Tests
    
    async def _test_llm_api_contract(self) -> Dict[str, Any]:
        """Test LLM API contract"""
        try:
            from core.services.unified_llm import UnifiedLLMService, LLMRequest, LLMResponse
            
            # Test contract: LLMRequest has required fields
            request = LLMRequest(
                prompt="test",
                system_prompt="test",
                agent_type="frontend",
                max_tokens=10
            )
            
            assert hasattr(request, 'prompt')
            assert hasattr(request, 'system_prompt')
            assert hasattr(request, 'agent_type')
            assert hasattr(request, 'max_tokens')
            
            return {"status": "passed", "contract": "LLMRequest/LLMResponse"}
            
        except Exception as e:
            raise AssertionError(f"LLM API contract test failed: {e}")
            
    async def _test_memory_api_contract(self) -> Dict[str, Any]:
        """Test Memory API contract"""
        try:
            from core.memory import MemoryAgent

            # THE CONTRACT IS THE API THAT EXISTS.
            #
            # This asserted `get_memory`, which MemoryAgent has never had --
            # retrieval by id is `retrieve_memory`, and by query it is
            # `retrieve` / `search_memories`. A contract test that names a
            # method the class does not define can only fail, and since the
            # suite had zero callers it had never failed once, so it guarded
            # nothing. Naming the real surface is what makes it a guard again.
            required = ("store_memory", "retrieve_memory", "retrieve", "search_memories")
            missing = [m for m in required if not hasattr(MemoryAgent, m)]
            assert not missing, f"MemoryAgent is missing {missing}"

            return {"status": "passed", "contract": "MemoryAgent",
                    "methods": list(required)}

        except Exception as e:
            raise AssertionError(f"Memory API contract test failed: {e}")
            
    async def _test_learning_api_contract(self) -> Dict[str, Any]:
        """Test Learning API contract"""
        try:
            from core.learning.unified_learning_system import UnifiedLearningSystem
            
            # Test UnifiedLearningSystem exists
            # Same as the memory contract above: `process_learning_event` does
            # not exist and never did. The learning surface is the
            # `learn_from_*` family plus the state accessors.
            required = ("learn_from_event", "learn_from_experience",
                        "learn_from_example", "get_learning_state")
            missing = [m for m in required if not hasattr(UnifiedLearningSystem, m)]
            assert not missing, f"UnifiedLearningSystem is missing {missing}"
            
            return {"status": "passed", "contract": "UnifiedLearningSystem"}
            
        except Exception as e:
            raise AssertionError(f"Learning API contract test failed: {e}")
            
    # Integration Tests
    
    async def _test_end_to_end_flow(self) -> Dict[str, Any]:
        """Test end-to-end request flow"""
        # This would test a complete request through the system
        # For now, just verify components exist
        
        components = [
            self.workspace_path / "core" / "services" / "unified_llm.py",
            self.workspace_path / "core" / "agents" / "memory_agent.py",
            self.workspace_path / "core" / "learning" / "unified_learning_system.py",
        ]
        
        for component in components:
            assert component.exists(), f"Component not found: {component}"
        
        return {
            "status": "passed",
            "components_verified": len(components)
        }
        
    async def _test_service_communication(self) -> Dict[str, Any]:
        """Test services can communicate"""
        # Test that services can import each other
        try:
            from core.services.unified_llm import UnifiedLLMService
            from core.memory import MemoryAgent
            from core.learning.unified_learning_system import UnifiedLearningSystem

            return {
                "status": "passed",
                "services": ["UnifiedLLMService", "MemoryAgent", "UnifiedLearningSystem"]
            }

        except Exception as e:
            raise AssertionError(f"Service communication test failed: {e}")
            
    # Performance Tests
    
    async def _test_response_time(self) -> Dict[str, Any]:
        """Test response time is acceptable"""
        # Test import time as proxy for responsiveness
        start = time.time()
        
        from core.services.unified_llm import UnifiedLLMService
        
        import_time = time.time() - start
        
        # Import should be fast (< 1 second)
        assert import_time < 1.0, f"Import too slow: {import_time:.2f}s"
        
        return {
            "import_time_ms": import_time * 1000,
            "threshold_ms": 1000
        }
        
    async def _test_memory_usage(self) -> Dict[str, Any]:
        """Test memory usage is reasonable"""
        import psutil
        
        process = psutil.Process()
        memory_mb = process.memory_info().rss / (1024 * 1024)
        
        # Memory should be under 8GB for development
        assert memory_mb < 8192, f"Memory usage too high: {memory_mb:.1f}MB"
        
        return {
            "memory_mb": memory_mb,
            "threshold_mb": 8192
        }
        
    async def _test_throughput(self) -> Dict[str, Any]:
        """Test system throughput"""
        # Test file system throughput
        test_file = self.workspace_path / "test_throughput.tmp"
        
        start = time.time()
        
        # Write 1MB
        data = b"x" * (1024 * 1024)
        test_file.write_bytes(data)
        
        # Read it back
        read_data = test_file.read_bytes()
        
        duration = time.time() - start
        
        # Clean up
        test_file.unlink()
        
        assert read_data == data, "Data corruption detected"
        
        throughput_mbps = 1.0 / duration
        
        return {
            "throughput_mbps": throughput_mbps,
            "duration_ms": duration * 1000
        }
        
    # Regression Tests
    
    async def _test_known_issues(self) -> Dict[str, Any]:
        """Regression checks for issues that were fixed and must stay fixed.

        THREE THINGS WERE WRONG WITH THIS.

        It counted findings and asserted nothing, so it could not fail --
        `_run_test` passes anything that does not raise, and this returns a
        dict either way.

        Its import check used a BARE `except: pass`, which also swallows
        KeyboardInterrupt and SystemExit, and discarded the reason.

        And it looked for `core/models/llama-3.1-70b-gguf`. This system serves
        Qwen; that path has not existed for a long time, so `model_path_exists`
        could never appear in the results and the test silently measured a
        model that was replaced.
        """
        regressions = []

        # The service must import. It is the substrate's teacher and every
        # reasoning path reaches it; an import error here is a real regression.
        try:
            from core.services.unified_llm import UnifiedLLMService  # noqa: F401
        except Exception as error:
            regressions.append(f"unified_llm no longer imports: "
                               f"{type(error).__name__}: {error}")

        # The served model is whatever the service resolves, not a hardcoded
        # filename. Asking the owner means this cannot rot the way the
        # llama-3.1 path did.
        try:
            from core.services.unified_llm import get_llm_service

            service = get_llm_service()
            model_name = getattr(service, "model_name", None)
            if not model_name:
                regressions.append("LLM service reports no model_name")
        except Exception as error:
            regressions.append(f"LLM service unavailable: "
                               f"{type(error).__name__}: {error}")
            model_name = None

        # ASSERTS. Without this the test reports its findings and passes.
        assert not regressions, "; ".join(regressions)

        return {"checks_run": 2, "regressions": 0, "model_name": model_name}
        
    def export_report(self, result: TestSuiteResult, output_path: Path):
        """Export test report as JSON"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": result.summary,
            "total_tests": result.total_tests,
            "passed": result.passed,
            "failed": result.failed,
            "duration_seconds": result.duration_seconds,
            "tests": [
                {
                    "name": test.name,
                    "passed": test.passed,
                    "duration_seconds": test.duration_seconds,
                    "error": test.error,
                    "metrics": test.metrics
                }
                for test in result.test_results
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Test report exported to {output_path}")


async def run_upgrade_tests(workspace_path: Path) -> TestSuiteResult:
    """
    Convenience function to run upgrade test suite.
    
    Args:
        workspace_path: Path to TorinAI workspace
        
    Returns:
        TestSuiteResult
    """
    suite = UpgradeTestSuite(workspace_path)
    return await suite.run_all_tests()


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        workspace = Path("/Users/stefan/TorinAI")
        
        result = await run_upgrade_tests(workspace)
        
        print(f"\n{'='*60}")
        print(f"Test Suite Results: {result.summary}")
        print(f"{'='*60}")
        print(f"Total: {result.total_tests}")
        print(f"Passed: {result.passed}")
        print(f"Failed: {result.failed}")
        print(f"Duration: {result.duration_seconds:.2f}s")
        print(f"{'='*60}\n")
        
        # Show failed tests
        if result.failed > 0:
            print("Failed Tests:")
            for test in result.test_results:
                if not test.passed:
                    print(f"  ✗ {test.name}: {test.error}")
    
    asyncio.run(main())
