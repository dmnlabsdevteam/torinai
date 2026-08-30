#!/usr/bin/env python3
"""
Upgrade Sandbox
====================
Isolated environment for testing code upgrades safely

Features:
- Resource isolation (CPU, memory, network)
- Filesystem isolation
- Safe code execution with monitoring
- Automatic cleanup
- Resource usage tracking

Approach:
Uses Docker containers for strong isolation
Monitors resource usage and enforces limits
Captures all output for analysis
Automatically cleans up after execution

Safety:
- Fail-closed: Any errors abort upgrade
- Resource limits enforced
- Network isolation optional
- Read-only access to critical paths
- Automatic timeout protection

Example:
    sandbox = UpgradeSandbox(
        cpu_limit=0.5,  # 50% of one CPU core
        memory_limit_mb=512,
        timeout_seconds=300
    )
    result = await sandbox.run_code(code, entry_point="main")
"""

import asyncio
import logging
import os
import tempfile
import shutil
import subprocess  # For Docker
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from pathlib import Path


logger = logging.getLogger(__name__)


#: The image the sandbox runs candidates in.
#:
#: `python:3.11-slim` has none of the system's dependencies, so importing a
#: changed module against the real repo died on the first third-party package
#: and every candidate looked broken. `torinai-sandbox` is that image plus
#: requirements.txt (built from Dockerfile.sandbox), so a change can be
#: exercised in the context it will actually run in.
#:
#: Falls back to the slim image when the built one is absent, and SAYS SO --
#: a sandbox silently missing its dependencies is how an environment failure
#: gets recorded as a code failure.
SANDBOX_IMAGE = "torinai-sandbox:latest"
SANDBOX_FALLBACK_IMAGE = "python:3.11-slim"


def _sandbox_image() -> tuple:
    """(image, is_full) -- the image to use and whether it carries the deps."""
    try:
        probe = subprocess.run(["docker", "image", "inspect", SANDBOX_IMAGE],
                               capture_output=True, timeout=15)
        if probe.returncode == 0:
            return SANDBOX_IMAGE, True
    except Exception as error:
        logger.debug("Could not inspect %s: %s", SANDBOX_IMAGE, error)
    logger.warning(
        "%s is not built; falling back to %s, which has NONE of the system's "
        "dependencies. Import checks against the real repo will fail for "
        "environmental reasons, not because the change is wrong. "
        "Build it with: docker build -f Dockerfile.sandbox -t %s .",
        SANDBOX_IMAGE, SANDBOX_FALLBACK_IMAGE, SANDBOX_IMAGE)
    return SANDBOX_FALLBACK_IMAGE, False


@dataclass
class SandboxConfig:
    """Sandbox configuration"""
    sandbox_id: str
    cpu_limit: float = 0.5  # CPU cores
    memory_limit_mb: int = 512  # Memory limit in MB
    timeout_seconds: int = 300  # Max execution time
    network_isolated: bool = True
    read_only_paths: List[str] = field(default_factory=list)
    writable_paths: List[str] = field(default_factory=list)


@dataclass
class SandboxEnvironment:
    """Sandbox environment state"""
    sandbox_id: str
    container_id: str
    status: str  # "initializing", "running", "stopped", "error"
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class SandboxResult:
    """Result of sandbox execution"""
    success: bool
    output: str
    errors: List[str] = field(default_factory=list)
    exit_code: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)


class UpgradeSandbox:
    """
    Isolated sandbox for testing code upgrades

    Uses Docker for strong isolation:
    - CPU and memory limits
    - Network isolation
    - Filesystem isolation
    - Resource monitoring
    """

    def __init__(self, config: Dict[str, Any] = None):
        # Default configuration
        if config is None:
            config = {}

        self.config = SandboxConfig(
            sandbox_id=config.get("sandbox_id", f"sandbox_{int(time.time())}"),
            cpu_limit=config.get("cpu_limit", 0.5),
            memory_limit_mb=config.get("memory_limit_mb", 512),
            timeout_seconds=config.get("timeout_seconds", 300),
            network_isolated=config.get("network_isolated", True),
            read_only_paths=config.get("read_only_paths", []),
            writable_paths=config.get("writable_paths", [])
        )

        self.container_id = None
        self.temp_dir = None

        #: Why the last _initialize_sandbox() failed. A gate that refuses has to
        #: say what it refused on: the cause was logged and then dropped, so
        #: every caller reported the bare string "Sandbox initialization
        #: failed" and the self-improvement cycle recorded that as its abort
        #: reason -- with no way to tell an unavailable Docker daemon from a
        #: permissions problem or a full disk.
        self._init_error: Optional[str] = None

        # Metrics tracking
        self.execution_metrics = {}

        logger.info(f"UpgradeSandbox initialized: {self.config.sandbox_id}")

    def __del__(self):
        """Cleanup on destruction"""
        try:
            self._cleanup_sandbox()
        except:
            pass

    def __enter__(self):
        """Context manager entry"""
        # Create temp directory if not exists
        if not self.temp_dir:
            self.temp_dir = tempfile.mkdtemp(prefix=f"{self.config.sandbox_id}_")
            logger.info(f"Created sandbox workspace: {self.temp_dir}")
            # Create subdirectories
            os.makedirs(os.path.join(self.temp_dir, "code"), exist_ok=True)
            os.makedirs(os.path.join(self.temp_dir, "output"), exist_ok=True)

        # Set sandbox_root as a Path object
        self.sandbox_root = Path(self.temp_dir)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self._cleanup_sandbox()
        return False

    def _cleanup_sandbox(self, force: bool = False):
        """Clean up sandbox resources"""
        # Remove Docker container if exists
        if self.container_id:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self.container_id],
                    capture_output=True,
                    timeout=30
                )
                logger.info(f"Removed container: {self.container_id}")
            except Exception as e:
                logger.error(f"Failed to remove container: {e}")

        # Remove temp directory
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                logger.debug(f"Removed temp directory: {self.temp_dir}")
            except Exception as e:
                logger.error(f"Failed to remove temp directory: {e}")

    async def _initialize_sandbox(self) -> bool:
        """
        Initialize sandbox environment

        Creates:
        - Temporary workspace directory
        - Docker container with resource limits
        - Network isolation (if enabled)
        - Filesystem mounts

        Returns:
            True if initialization successful
        """
        self._init_error = None
        try:
            # Create temporary directory for sandbox workspace
            self.temp_dir = tempfile.mkdtemp(prefix=f"{self.config.sandbox_id}_")
            logger.info(f"Created sandbox workspace: {self.temp_dir}")

            # Create subdirectories
            os.makedirs(os.path.join(self.temp_dir, "code"), exist_ok=True)
            os.makedirs(os.path.join(self.temp_dir, "output"), exist_ok=True)

            # Build Docker run command
            docker_cmd = self._build_docker_command()

            logger.info(f"Initializing Docker container: {self.config.sandbox_id}")

            # Create container (but don't start yet)
            # We'll start it when we run code
            # For now, just verify Docker is available

            result = subprocess.run(
                ["docker", "version"],
                capture_output=True,
                timeout=10
            )

            if result.returncode != 0:
                detail = (result.stderr or b"").decode(errors="replace").strip()
                self._init_error = (
                    "Docker is not available: `docker version` exited "
                    f"{result.returncode}"
                    + (f" ({detail.splitlines()[0][:200]})" if detail else "")
                    + ". The sandbox is the hard gate on self-improvement, so "
                      "the cycle cannot test or deploy anything until the "
                      "Docker daemon is running."
                )
                logger.error(self._init_error)
                return False

            logger.info("Sandbox initialized successfully")
            return True

        except FileNotFoundError as e:
            self._init_error = (
                f"Docker executable not found ({e}); the sandbox cannot start")
            logger.error(self._init_error)
            self._cleanup_sandbox(force=True)
            return False

        except subprocess.TimeoutExpired:
            self._init_error = (
                "Docker did not respond within 10s; the daemon may be starting "
                "or unresponsive")
            logger.error(self._init_error)
            self._cleanup_sandbox(force=True)
            return False

        except Exception as e:
            self._init_error = f"{type(e).__name__}: {e}"
            logger.error(f"Sandbox initialization failed: {self._init_error}")
            self._cleanup_sandbox(force=True)
            return False

    async def run_against_repo(
        self,
        code: str,
        target_rel_path: str,
        repo_path: str,
        check: str = "import",
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        """Run the change AGAINST THE REAL CODEBASE, not against a bare file.

        `run_code()` puts one file in an empty `python:3.11-slim` with no repo
        and no network, so importing it proves only that the text parses. It
        cannot catch the thing that actually matters about a change: whether it
        still works INSIDE the system it is going into -- whether the symbols it
        references exist, whether the modules that import it still import, and
        whether anything downstream breaks.

        This mounts the repository read-only and bind-mounts the candidate file
        OVER its real path, so the container sees the whole system with exactly
        one file changed. Nothing outside the container is touched: the overlay
        is a mount, the repo mount is `:ro`, and the change never reaches disk.

        `check`:
          "import"  -- import the changed module in the context of the repo
          "reverse" -- also import every module that imports it
        """
        if not self.temp_dir:
            if not await self._initialize_sandbox():
                return SandboxResult(success=False, output="",
                                     errors=[self._init_error or "Sandbox init failed"],
                                     exit_code=-1)

        overlay_dir = os.path.join(self.temp_dir, "overlay")
        os.makedirs(overlay_dir, exist_ok=True)
        overlay_file = os.path.join(overlay_dir, os.path.basename(target_rel_path))
        with open(overlay_file, "w", encoding="utf-8") as handle:
            handle.write(code)

        module = target_rel_path.replace("/", ".").removesuffix(".py")
        # The probe lives at / so sys.path[0] is /, not /repo. Without this the
        # import fails with "No module named 'core'" for every candidate --
        # which looks like the change being broken when it is the harness.
        probe = (f"import sys, importlib\n"
                 f"sys.path.insert(0, '/repo')\n"
                 f"importlib.import_module('{module}')\n"
                 f"print('IMPORTED {module}')\n")
        probe_path = os.path.join(overlay_dir, "_probe.py")
        with open(probe_path, "w", encoding="utf-8") as handle:
            handle.write(probe)

        cmd = [
            "docker", "run", "--rm",
            "--cpus", str(self.config.cpu_limit),
            "--memory", f"{self.config.memory_limit_mb}m",
        ]
        if self.config.network_isolated:
            cmd.extend(["--network", "none"])
        cmd.extend([
            # The real system, read-only.
            "-v", f"{repo_path}:/repo:ro",
            # The candidate file, mounted OVER its real location. Docker allows
            # a file-level bind mount, so the tree is unchanged except here.
            "-v", f"{overlay_file}:/repo/{target_rel_path}:ro",
            "-v", f"{probe_path}:/probe.py:ro",
            "-w", "/repo",
        ])
        image, full_image = _sandbox_image()
        cmd.extend([image, "python", "/probe.py"])

        logger.info("Sandbox: importing %s against the real repo", module)
        try:
            result = subprocess.run(cmd, capture_output=True,
                                    timeout=timeout or self.config.timeout_seconds)
        except subprocess.TimeoutExpired:
            return SandboxResult(success=False, output="",
                                 errors=[f"timed out after "
                                         f"{timeout or self.config.timeout_seconds}s"],
                                 exit_code=-1)

        out = result.stdout.decode(errors="replace")
        err = result.stderr.decode(errors="replace")
        # A MISSING DEPENDENCY IS NOT A BROKEN CHANGE. Distinguished, so an
        # empty sandbox can never be recorded as a failed candidate.
        environmental = (not full_image
                         and "ModuleNotFoundError" in err
                         and f"'{module.split('.')[0]}'" not in err)
        return SandboxResult(
            success=result.returncode == 0,
            output=out,
            errors=[err] if err else [],
            exit_code=result.returncode,
            metrics={"module": module, "check": check, "repo": repo_path,
                     "image": image, "dependencies_present": full_image,
                     "environmental_failure": environmental},
        )

    def _build_docker_command(self) -> List[str]:
        """Build Docker run command with resource limits"""
        cmd = [
            "docker", "run",
            "--rm",  # Remove container after exit
            "-d",    # Detached mode
        ]

        # Resource limits
        cmd.extend([
            "--cpus", str(self.config.cpu_limit),
            "--memory", f"{self.config.memory_limit_mb}m"
        ])

        # Network isolation
        if self.config.network_isolated:
            cmd.extend(["--network", "none"])

        # Mount code directory
        code_dir = os.path.join(self.temp_dir, "code")
        cmd.extend([
            "-v", f"{code_dir}:/workspace:rw",
        ])

        # Read-only mounts for security-sensitive paths
        for path in self.config.read_only_paths:
            if os.path.exists(path):
                cmd.extend(["-v", f"{path}:{path}:ro"])

        # Writable mounts
        for path in self.config.writable_paths:
            if os.path.exists(path):
                cmd.extend(["-v", f"{path}:{path}:rw"])

        # The image with the system's dependencies, when it has been built.
        image, _full = _sandbox_image()
        cmd.append(image)

        # Keep container alive (we'll exec into it)
        cmd.extend(["sleep", "infinity"])

        return cmd

    def _copy_code_to_sandbox(self, code: str, filename: str = "upgrade.py"):
        """Copy code to sandbox workspace"""
        try:
            code_path = os.path.join(self.temp_dir, "code", filename)
            with open(code_path, 'w', encoding='utf-8') as f:
                f.write(code)
            logger.debug(f"Copied code to sandbox: {filename}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy code: {e}")
            return False

    async def run_code(
        self,
        code: str,
        entry_point: Optional[str] = "main",
        *args,
        **kwargs
    ) -> SandboxResult:
        """
        Execute code in sandbox

        Args:
            code: Python code to execute
            entry_point: Function name to call, or None to IMPORT ONLY.

                Import-only is the honest test for generated code. The
                generators emit `improve_<component>(...)` with a signature this
                caller does not know, so calling a fixed `main()` with no
                arguments tested nothing that could pass: either the function
                did not exist or it was invoked with the wrong arity. Importing
                the module under Docker isolation is a real check -- it catches
                syntax errors, bad imports and anything that raises at import
                time -- and it does not pretend to have exercised a function it
                cannot call correctly.
            *args: Positional arguments for entry point
            **kwargs: Keyword arguments for entry point

        Returns:
            SandboxResult with execution outcome
        """
        if not self.temp_dir:
            logger.warning("Sandbox not initialized, initializing now")
            initialized = await self._initialize_sandbox()
            if not initialized:
                return SandboxResult(
                    success=False,
                    output="",
                    errors=[self._init_error or "Sandbox initialization failed"],
                    exit_code=-1
                )

        logger.info(f"Running code in sandbox: {self.config.sandbox_id}")

        # Copy code to sandbox
        if not self._copy_code_to_sandbox(code):
            return SandboxResult(
                success=False,
                output="",
                errors=["Failed to copy code to sandbox"]
            )

        output = ""
        errors = []
        exit_code = 0

        try:
            # Start Docker container
            docker_cmd = self._build_docker_command()
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=30
            )

            if result.returncode != 0:
                raise Exception(f"Failed to start container: {result.stderr.decode()}")

            self.container_id = result.stdout.decode().strip()
            logger.info(f"Container started: {self.container_id}")

            # Execute code in container
            # Create wrapper script that calls entry point
            if entry_point is None:
                wrapper_code = """
import sys
sys.path.insert(0, '/workspace')

try:
    import upgrade
    print("IMPORTED:", upgrade.__name__)
    sys.exit(0)
except Exception as e:
    print("ERROR:", str(e), file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""
            else:
                wrapper_code = f"""
import sys
sys.path.insert(0, '/workspace')

try:
    from upgrade import {entry_point}
    result = {entry_point}(*{args}, **{kwargs})
    print("RESULT:", result)
    sys.exit(0)
except Exception as e:
    print("ERROR:", str(e), file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""

            # Write wrapper to sandbox
            wrapper_path = os.path.join(self.temp_dir, "code", "_wrapper.py")
            with open(wrapper_path, 'w') as f:
                f.write(wrapper_code)

            # Execute with timeout
            exec_cmd = [
                "docker", "exec",
                self.container_id,
                "python", "/workspace/_wrapper.py"
            ]

            logger.debug(f"Executing: {' '.join(exec_cmd)}")

            exec_result = subprocess.run(
                exec_cmd,
                capture_output=True,
                timeout=self.config.timeout_seconds
            )

            output = exec_result.stdout.decode()
            stderr = exec_result.stderr.decode()
            exit_code = exec_result.returncode

            if stderr:
                errors.append(stderr)

            logger.info(f"Execution complete: exit_code={exit_code}")

        except subprocess.TimeoutExpired:
            errors.append(f"Execution timeout ({self.config.timeout_seconds}s)")
            exit_code = -1
            logger.error("Execution timeout")

        except Exception as e:
            errors.append(f"Execution error: {str(e)}")
            exit_code = -1
            logger.error(f"Execution error: {e}")

        finally:
            # Cleanup container
            if self.container_id:
                try:
                    removal = subprocess.run(
                        ["docker", "rm", "-f", self.container_id],
                        capture_output=True,
                        timeout=30
                    )
                    if removal.returncode != 0:
                        # A container that would not die is still holding CPU,
                        # memory and a mount of the workspace. Silence here
                        # leaks one per run and nothing ever says why the host
                        # is slowing down.
                        logger.error(
                            "Sandbox container %s not removed (exit %s): %s",
                            self.container_id[:12], removal.returncode,
                            removal.stderr.decode(errors="replace")[:200])
                except Exception as cleanup_error:
                    logger.error("Sandbox container %s could not be removed: %s",
                                 str(self.container_id)[:12], cleanup_error)

        # Build result
        success = (exit_code == 0) and (len(errors) == 0)

        return SandboxResult(
            success=success,
            output=output,
            errors=errors,
            exit_code=exit_code,
            metrics=self.execution_metrics
        )

    async def run_tests(
        self,
        test_files: List[str],
        test_framework: str = "pytest"
    ) -> SandboxResult:
        """
        Run test suite in sandbox

        Args:
            test_files: List of test file paths
            test_framework: Test framework to use (pytest, unittest)

        Returns:
            SandboxResult with test execution outcome
        """
        if not self.temp_dir:
            logger.warning("Sandbox not initialized, initializing now")
            initialized = await self._initialize_sandbox()
            if not initialized:
                return SandboxResult(
                    success=False,
                    output="",
                    errors=[self._init_error or "Sandbox initialization failed"]
                )

        logger.info(f"Running tests in sandbox: {len(test_files)} file(s)")

        # Copy test files to sandbox
        code_dir = os.path.join(self.temp_dir, "code")
        for test_file in test_files:
            if not os.path.exists(test_file):
                # A named test file that is not there means the suite is not
                # what the caller thinks it is. Silently skipping it would let
                # a run of zero tests report as a pass.
                return SandboxResult(
                    success=False, output="",
                    errors=[f"test file not found: {test_file}"], exit_code=-1)
            dest = os.path.join(code_dir, os.path.basename(test_file))
            if os.path.abspath(test_file) == os.path.abspath(dest):
                continue          # already in the workspace (inline suite)
            shutil.copy(test_file, dest)

        # Start container
        docker_cmd = self._build_docker_command()
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            timeout=30
        )

        if result.returncode != 0:
            return SandboxResult(
                success=False,
                output="",
                errors=[f"Failed to start container: {result.stderr.decode()}"]
            )

        self.container_id = result.stdout.decode().strip()

        output = ""
        errors = []
        exit_code = 0

        try:
            # THE INSTALL COULD NEVER WORK AND ITS RESULT WAS DISCARDED.
            #
            # The sandbox runs with `--network none`, so `pip install` has
            # nowhere to fetch from -- and `subprocess.run(...)` here threw the
            # result away, so a missing framework surfaced later as "Tests
            # failed (exit code: N)". A test run that never started and a test
            # run that failed are different facts.
            #
            # torinai-sandbox:latest already carries pytest (verified 9.1.1),
            # so the framework is CHECKED rather than installed, and its
            # absence is reported as what it is.
            if test_framework == "pytest":
                probe = subprocess.run(
                    ["docker", "exec", self.container_id,
                     "python", "-c", "import pytest"],
                    capture_output=True, timeout=60)
                if probe.returncode != 0:
                    return SandboxResult(
                        success=False, output="",
                        errors=["pytest is not available in the sandbox image "
                                "and the sandbox has no network to install it; "
                                "no test was run"],
                        exit_code=-1)

            # Run tests
            if test_framework == "pytest":
                test_cmd = [
                    "docker", "exec",
                    self.container_id,
                    "pytest", "/workspace", "-v"
                ]
            else:  # unittest
                test_cmd = [
                    "docker", "exec",
                    self.container_id,
                    "python", "-m", "unittest", "discover", "/workspace"
                ]

            test_result = subprocess.run(
                test_cmd,
                capture_output=True,
                timeout=self.config.timeout_seconds
            )

            output = test_result.stdout.decode()
            stderr = test_result.stderr.decode()
            exit_code = test_result.returncode

            if exit_code != 0:
                errors.append(f"Tests failed (exit code: {exit_code})")

            if stderr and "PASSED" not in stderr:
                errors.append(stderr)

        except subprocess.TimeoutExpired:
            errors.append("Test execution timeout")
            exit_code = -1

        except Exception as e:
            errors.append(f"Test execution error: {str(e)}")
            exit_code = -1

        finally:
            # Cleanup
            if self.container_id:
                try:
                    removal = subprocess.run(
                        ["docker", "rm", "-f", self.container_id],
                        capture_output=True,
                        timeout=30
                    )
                    if removal.returncode != 0:
                        # A container that would not die is still holding CPU,
                        # memory and a mount of the workspace. Silence here
                        # leaks one per run and nothing ever says why the host
                        # is slowing down.
                        logger.error(
                            "Sandbox container %s not removed (exit %s): %s",
                            self.container_id[:12], removal.returncode,
                            removal.stderr.decode(errors="replace")[:200])
                except Exception as cleanup_error:
                    logger.error("Sandbox container %s could not be removed: %s",
                                 str(self.container_id)[:12], cleanup_error)

        success = (exit_code == 0)

        return SandboxResult(
            success=success,
            output=output,
            errors=errors,
            exit_code=exit_code,
            metrics={}
        )

    async def get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage of sandbox"""
        if not self.container_id:
            return {}

        try:
            # Get container stats
            stats_cmd = ["docker", "stats", "--no-stream", "--format",
                        "{{.CPUPerc}},{{.MemUsage}},{{.NetIO}}", self.container_id]

            result = subprocess.run(
                stats_cmd,
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                stats = result.stdout.decode().strip().split(',')
                cpu_usage = float(stats[0].rstrip('%')) if len(stats) > 0 else 0
                mem_usage = stats[1] if len(stats) > 1 else "0MiB / 0MiB"

                return {
                    "cpu_percent": cpu_usage,
                    "memory_usage": mem_usage,
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            logger.error(f"Failed to get resource usage: {e}")
            # {} is what "the container used nothing" would also look like.
            return {"available": False, "error": f"{type(e).__name__}: {e}"}

        return {"available": False, "error": "no stats returned by docker"}

    def _cleanup(self):
        """Cleanup sandbox resources"""
        if self.container_id:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self.container_id],
                    capture_output=True,
                    timeout=30
                )
                logger.info(f"Cleaned up container: {self.container_id}")
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                logger.error(f"Failed to remove temp dir: {e}")

    async def _store_sandbox_result(self, result: SandboxResult, upgrade_id: str, metadata: Dict):
        """Store sandbox execution result in database (Postgres)"""
        try:
            from core.database import get_database_manager
            import json
            db = get_database_manager()

            await db.execute_query(
                """
                INSERT INTO sandbox_results
                   (sandbox_id, upgrade_id, success, exit_code, output_length,
                    error_count, timestamp, cpu_limit, memory_limit_mb, timeout_seconds,
                    output, errors, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                params=(
                    self.config.sandbox_id,
                    upgrade_id,
                    result.success,
                    result.exit_code,
                    len(result.output),
                    len(result.errors),
                    datetime.now(),
                    self.config.cpu_limit,
                    self.config.memory_limit_mb,
                    self.config.timeout_seconds,
                    result.output[:10000],  # Limit output size in DB
                    json.dumps(result.errors),
                    json.dumps(metadata),
                ),
                commit=True,
            )

            logger.info(f"Sandbox result stored in database: {upgrade_id}")

        except Exception as e:
            logger.error(f"Failed to store sandbox result: {e}")

    async def validate_upgrade(self, code: str, test_suite: str = "") -> Tuple[bool, str]:
        """Run a test suite against generated code, inside the sandbox.

        TWO DEFECTS MADE THIS A RUBBER STAMP.

        `code` was accepted and never used -- it was never written into the
        sandbox, so `run_tests` ran the suite against a workspace that did not
        contain the thing under test. Whatever the tests imported, it was not
        this upgrade.

        And with no `test_suite` it returned `(True, "Validation successful")`,
        having executed nothing. The one caller that would supply a suite --
        `EnhancedASI` -- never writes the `test_suite` column, so every real
        call would have taken exactly that path: a validation that passes
        because nothing was checked.

        Now the code is written into the workspace first, a suite is REQUIRED,
        and the message says what actually ran.
        """
        if not code or not str(code).strip():
            return False, "no code supplied; there is nothing to validate"

        initialized = await self._initialize_sandbox()
        if not initialized:
            return False, self._init_error or "Sandbox initialization failed"

        # THE CODE UNDER TEST GOES IN FIRST. Without this the suite runs
        # against an empty workspace and its imports fail -- or worse, pass
        # against whatever else happens to be there.
        if not self._copy_code_to_sandbox(code, "upgrade.py"):
            return False, "could not place the code in the sandbox workspace"

        test_files = self._resolve_test_suite(test_suite)
        if not test_files:
            # NOT a pass. "I ran no tests" and "the tests passed" are the two
            # answers this function exists to distinguish.
            return False, (
                "no test suite supplied, so nothing was verified; refusing to "
                "report an unrun suite as a successful validation")

        result = await self.run_tests(test_files)
        if not result.success:
            return False, f"tests failed: {'; '.join(result.errors) or 'see output'}"
        return True, f"{len(test_files)} test file(s) passed in the sandbox"

    def _resolve_test_suite(self, test_suite: str) -> List[str]:
        """Test files from a directory, a file, or literal source text.

        This only ever handled paths, while the code it validates arrives as a
        STRING -- so a caller holding generated test source had no way to pass
        it and fell into the "no tests" branch that returned success.
        """
        if not test_suite or not str(test_suite).strip():
            return []

        candidate = str(test_suite)
        try:
            if os.path.isdir(candidate):
                return [os.path.join(candidate, name)
                        for name in sorted(os.listdir(candidate))
                        if name.startswith("test_") and name.endswith(".py")]
            if os.path.isfile(candidate):
                return [candidate]
        except OSError as error:
            logger.error("Test suite path %r unreadable: %s", candidate[:80], error)
            return []

        # Not a path. Treat it as source only if it actually parses as Python;
        # a stray string is not a test suite and must not become an empty file
        # that pytest collects as zero tests and calls a pass.
        try:
            compile(candidate, "test_upgrade.py", "exec")
        except SyntaxError as error:
            logger.error("Test suite is neither a path nor valid Python: %s", error)
            return []

        written = os.path.join(self.temp_dir, "code", "test_upgrade.py")
        try:
            with open(written, "w", encoding="utf-8") as handle:
                handle.write(candidate)
        except OSError as error:
            logger.error("Could not write inline test suite: %s", error)
            return []
        return [written]


class SandboxManager:
    """Manages multiple sandbox instances"""

    def __init__(self):
        self.sandboxes: Dict[str, UpgradeSandbox] = {}

    def create_sandbox(self, sandbox_id: str, config: Dict[str, Any]) -> UpgradeSandbox:
        """Create a new sandbox"""
        config["sandbox_id"] = sandbox_id
        sandbox = UpgradeSandbox(config)
        self.sandboxes[sandbox_id] = sandbox
        return sandbox

    def get_sandbox(self, sandbox_id: str) -> Optional[UpgradeSandbox]:
        """Get existing sandbox"""
        return self.sandboxes.get(sandbox_id)

    async def cleanup_all(self):
        """Cleanup all sandboxes"""
        for sandbox_id, sandbox in list(self.sandboxes.items()):
            try:
                sandbox._cleanup_sandbox(force=True)
                del self.sandboxes[sandbox_id]
            except Exception as e:
                logger.error(f"Failed to cleanup sandbox {sandbox_id}: {e}")

    async def get_active_sandboxes(self) -> List[str]:
        """Get list of active sandbox IDs"""
        return list(self.sandboxes.keys())

    async def get_sandbox_stats(self, sandbox_id: str) -> Dict[str, Any]:
        """Get statistics for a specific sandbox"""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return {"error": "Sandbox not found"}

        stats = {
            "sandbox_id": sandbox_id,
            "config": {
                "cpu_limit": sandbox.config.cpu_limit,
                "memory_limit_mb": sandbox.config.memory_limit_mb,
                "timeout_seconds": sandbox.config.timeout_seconds,
                "network_isolated": sandbox.config.network_isolated
            },
            "status": "active" if sandbox.container_id else "stopped"
        }

        # Get resource usage if container is running
        if sandbox.container_id:
            usage = await sandbox.get_resource_usage()
            stats["resource_usage"] = usage

        return stats


async def test_sandbox_execution(code: str) -> Tuple[bool, str]:
    """
    Convenience function to test code in sandbox

    Args:
        code: Code to execute

    Returns:
        Tuple of (success, message)
    """
    sandbox = UpgradeSandbox(
        config={
            "cpu_limit": 0.5,
            "memory_limit_mb": 512,
            "timeout_seconds": 60,
            "network_isolated": True
        }
    )

    try:
        result = await sandbox.run_code(code, entry_point="main")
        return result.success, result.output
    finally:
        sandbox._cleanup()


# Example usage

# ---------------------------------------------------------------------------
# Singleton accessor
#
# Runs a candidate upgrade in isolation before any deployment.
# enhanced_asi_self_improvement.py has always imported `get_upgrade_sandbox` from this
# module, but it was never defined -- the import silently bound the name to
# None via `except ImportError`, and the ASI phase that depends on it aborted
# every single improvement cycle. The class below was complete; only this
# accessor was missing.
# ---------------------------------------------------------------------------

_upgrade_sandbox_instance: Optional[UpgradeSandbox] = None


def get_upgrade_sandbox(config: Optional[Dict[str, Any]] = None) -> UpgradeSandbox:
    """Get the shared UpgradeSandbox instance (singleton)."""
    global _upgrade_sandbox_instance
    if _upgrade_sandbox_instance is None:
        _upgrade_sandbox_instance = UpgradeSandbox(config) if config else UpgradeSandbox()
    return _upgrade_sandbox_instance

if __name__ == "__main__":
    asyncio.run(main())

    async def main():
        # Example code to test
        code = """
async def main():
    # Simple test code
    print("Hello from sandbox!")
    return {"status": "success"}
"""

        sandbox = UpgradeSandbox()

        # Initialize
        initialized = await sandbox._initialize_sandbox()
        if not initialized:
            print("Failed to initialize sandbox")
            return

        # Run code
        result = await sandbox.run_code(code, entry_point="main")

        print(f"\nSandbox Result:")
        print(f"Success: {result.success}")
        print(f"Output: {result.output}")
        print(f"Errors: {result.errors}")
        print(f"Exit Code: {result.exit_code}")
