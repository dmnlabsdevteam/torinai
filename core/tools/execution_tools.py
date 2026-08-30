#!/usr/bin/env python3
"""
Code Execution Tools
===================
Tools for executing Python code and shell commands safely.

Available Tools:
- run_python: Execute Python code in isolated environment
- run_shell_command: Execute shell commands with safety constraints
- execute_sandbox: Run code in full sandbox environment

Author: Torin AI Team
"""

import asyncio
import logging
import subprocess
import sys
import tempfile
import psutil
import resource
import signal
import os
import json
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, List

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from core.execution import command_console
from .capabilities import (
    ToolCapabilityProfile, CapabilityMetadata, Capability, RiskLevel
)


logger = logging.getLogger(__name__)


def resolve_working_directory(working_directory: Optional[str]) -> Optional[Path]:
    """
    Resolve working directory path, handling special cases.
    Maps /data to TorinAI's actual data directory.
    """
    if not working_directory:
        return None

    path = Path(working_directory)

    # Handle absolute /data path - map to TorinAI data directory
    if str(path).startswith('/data'):
        torin_root = Path(__file__).parent.parent.parent  # Get TorinAI root
        relative_path = str(path)[1:]  # Remove leading /
        path = torin_root / relative_path

    # Create directory if it doesn't exist
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created working directory: {path}")
        except Exception as e:
            logger.error(f"Failed to create directory {path}: {e}")
            return None

    return path.resolve()


class RunPythonTool(Tool):
    """Execute Python code safely"""

    def __init__(self):
        super().__init__()
        self.name = "run_python"
        self.description = (
            "Execute Python code in an isolated environment. Returns stdout, stderr, and exit code. "
            "Pass code directly via the `code` parameter — there is NO `file_path` parameter. "
            "To run a saved script, either (a) read the file first then pass its contents as `code`, "
            "or (b) use run_command with `python3 /path/to/script.py`."
        )
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS  # Logged for monitoring, not blocked
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Python code to execute",
                required=True
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Timeout in seconds (default: 30)",
                required=False,
                default=30,
                min_value=1,
                max_value=300
            ),
            ToolParameter(
                name="working_directory",
                type="string",
                description="Working directory for code execution",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_python",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Execute Python code in isolated environment",
                    input_types=["python_code"],
                    output_types=["stdout", "stderr", "exit_code"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.CRITICAL,
                    priority=9,
                    approval_level="team_lead"
                ),
                CapabilityMetadata(
                    capability=Capability.DEBUG_CODE,
                    description="Execute and debug Python code",
                    input_types=["python_code"],
                    output_types=["output", "errors"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    def validate_parameters(self, params: dict):
        """Allow file_path as a graceful alias for code."""
        # If file_path is supplied without code, treat it as valid — execute() will
        # read the file and use its contents.  The normal required-field check would
        # reject this because 'code' is marked required.
        if "file_path" in params and "code" not in params:
            return True, None
        return super().validate_parameters(params)

    async def execute(
        self,
        code: str = None,
        timeout: int = 30,
        working_directory: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """Execute Python code.

        Accepts an optional ``file_path`` keyword (legacy / model habit) as a
        graceful alias: if ``code`` is not given but ``file_path`` is, the file
        is read and its contents used as the code to execute.
        """
        # Graceful alias: model sometimes calls run_python(file_path='...')
        if code is None:
            file_path_alias = kwargs.get("file_path")
            if file_path_alias:
                try:
                    with open(file_path_alias, "r", encoding="utf-8") as _f:
                        code = _f.read()
                    logger.debug(
                        f"run_python: resolved file_path alias '{file_path_alias}' → {len(code)} chars"
                    )
                except Exception as e:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"run_python: could not read file_path='{file_path_alias}': {e}",
                    )
            else:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Missing required parameter: code",
                )
        try:
            # Use Pylance MCP server if available for better execution
            try:
                from core.tools.pylance_integration import run_python_code
                result = await run_python_code(code, timeout, working_directory)
                return result
            except ImportError:
                pass  # Fall back to subprocess execution
            
            # Create temporary file for code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            try:
                # Execute code
                cwd = resolve_working_directory(working_directory)

                # Build subprocess environment: inject cwd into PYTHONPATH so that
                # internal project imports (e.g. `from services.x import ...`) resolve.
                import os as _os_run
                env = dict(_os_run.environ)
                if cwd is not None:
                    existing_pypath = env.get("PYTHONPATH", "")
                    env["PYTHONPATH"] = str(cwd) + (_os_run.pathsep + existing_pypath if existing_pypath else "")

                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    temp_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Execution timed out after {timeout} seconds"
                    )
                
                return ToolResult(
                    success=process.returncode == 0,
                    output={
                        "stdout": stdout.decode('utf-8') if stdout else "",
                        "stderr": stderr.decode('utf-8') if stderr else "",
                        "exit_code": process.returncode
                    },
                    error=None if process.returncode == 0 else f"Process exited with code {process.returncode}"
                )
                
            finally:
                # Clean up temp file
                Path(temp_file).unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Error executing Python code: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class RunShellCommandTool(Tool):
    """Execute shell commands"""

    def __init__(self):
        super().__init__()
        self.name = "run_shell_command"
        self.description = (
            "Execute a shell command. Returns stdout, stderr, and exit code. "
            "IMPORTANT: This machine's paths contain spaces (e.g. 'Dominion Labs'). "
            "Always single-quote any path argument inside the command string so the shell "
            "does not split it — e.g. 'python -m pytest \'/path/with spaces/tests/test_foo.py\' -x -v'. "
            "Never pass an unquoted path that contains spaces."
        )
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.CRITICAL  # Logged for monitoring, not blocked
        self.parameters = [
            ToolParameter(
                name="command",
                type="string",
                description="Shell command to execute",
                required=True
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Timeout in seconds (default: 30)",
                required=False,
                default=30,
                min_value=1,
                max_value=300
            ),
            ToolParameter(
                name="working_directory",
                type="string",
                description="Working directory for command execution",
                required=False
            ),
            ToolParameter(
                name="shell",
                type="boolean",
                description="Execute through shell (allows pipes, etc.)",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_shell_command",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_COMMAND,
                    description="Execute arbitrary shell commands with full system access",
                    input_types=["shell_command"],
                    output_types=["stdout", "stderr", "exit_code"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.CRITICAL,
                    priority=10,
                    approval_level="team_lead"
                )
            ],
            requires_filesystem=True,
            requires_network=True,
            requires_database=False,
            is_idempotent=False
        )
    
    async def execute(
        self,
        command: str,
        timeout: int = 30,
        working_directory: Optional[str] = None,
        shell: bool = True
    ) -> ToolResult:
        """Execute shell command"""
        try:
            cwd = resolve_working_directory(working_directory)
            started = time.time()

            process = await asyncio.create_subprocess_shell(
                command if shell else command.split(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                # A timeout is an executed command too. Showing only the ones
                # that finish would make the terminal quietest at exactly the
                # moment something is hanging.
                command_console.show(
                    command, None, duration_sec=time.time() - started,
                    stderr=f"timed out after {timeout}s",
                    cwd=str(cwd) if cwd else None, tool="run_shell_command")
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Command timed out after {timeout} seconds"
                )
            
            out = stdout.decode('utf-8') if stdout else ""
            err = stderr.decode('utf-8') if stderr else ""

            payload = {
                "stdout": out,
                "stderr": err,
                "exit_code": process.returncode,
                "command": command
            }
            # A command that succeeds while printing nothing reads as "the thing is
            # not there", and models report it as such. It usually means the wrong
            # command: on macOS 26 `system_profiler SPUSBDataType` exits 0 with no
            # output while devices are plainly attached.
            if process.returncode == 0 and not out.strip() and not err.strip():
                payload["note"] = (
                    "Command exited 0 but printed NOTHING. An empty result is NOT "
                    "evidence that what you looked for is absent — the command may be "
                    "wrong, obsolete, or need different flags on this system. Do not "
                    "report 'none found' or 'not connected'. Verify with a different "
                    "command before concluding anything."
                )

            command_console.show(
                command, process.returncode, stdout=out, stderr=err,
                duration_sec=time.time() - started,
                cwd=str(cwd) if cwd else None, tool="run_shell_command")

            return ToolResult(
                success=process.returncode == 0,
                output=payload,
                error=None if process.returncode == 0 else f"Command exited with code {process.returncode}"
            )
            
        except Exception as e:
            logger.error(f"Error executing shell command: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class ExecuteSandboxTool(Tool):
    """Execute code in full sandbox environment"""

    def __init__(self):
        super().__init__()
        self.name = "execute_sandbox"
        self.description = "Execute code in a full sandbox environment with resource limits and state isolation"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS  # Logged for monitoring, not blocked
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Code to execute in sandbox",
                required=True
            ),
            ToolParameter(
                name="language",
                type="string",
                description="Programming language (currently only 'python' supported)",
                required=False,
                default="python",
                enum=["python"]
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Timeout in seconds",
                required=False,
                default=600,
                min_value=1,
                max_value=3600
            ),
            ToolParameter(
                name="max_memory_mb",
                type="number",
                description="Maximum memory usage in MB",
                required=False,
                default=4096,
                min_value=512,
                max_value=16384
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="execute_sandbox",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Execute code in isolated sandbox with resource limits",
                    input_types=["code", "language"],
                    output_types=["stdout", "stderr", "exit_code"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="team_lead"
                ),
                CapabilityMetadata(
                    capability=Capability.RUN_EXPERIMENT,
                    description="Run experiments in controlled environment",
                    input_types=["code"],
                    output_types=["result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )
    
    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 600,
        max_memory_mb: int = 4096
    ) -> ToolResult:
        """Execute code in sandbox"""
        try:
            from core.learning.upgrade_sandbox import UpgradeSandbox

            import uuid
            config = {
                "sandbox_id": f"exec_sandbox_{uuid.uuid4().hex[:8]}",
                "memory_limit_mb": max_memory_mb,
                "timeout_seconds": timeout,
                "network_isolated": True  # Disable network for safety
            }

            with UpgradeSandbox(config) as sandbox:
                # Write code to temp file in sandbox
                code_file = sandbox.sandbox_root / "execute_code.py"
                code_file.write_text(code)
                
                # Execute in sandbox
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(code_file),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=sandbox.sandbox_root
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Sandbox execution timed out after {timeout} seconds"
                    )
                
                return ToolResult(
                    success=process.returncode == 0,
                    output={
                        "stdout": stdout.decode('utf-8') if stdout else "",
                        "stderr": stderr.decode('utf-8') if stderr else "",
                        "exit_code": process.returncode,
                        "sandbox_path": str(sandbox.sandbox_root)
                    },
                    error=None if process.returncode == 0 else f"Sandbox execution failed with code {process.returncode}"
                )
            
        except Exception as e:
            logger.error(f"Error executing in sandbox: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class ListProcessesTool(Tool):
    """List running processes"""

    def __init__(self):
        super().__init__()
        self.name = "list_processes"
        self.description = "List all running processes with PID, name, and resource usage"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="filter_name",
                type="string",
                description="Optional filter by process name",
                required=False
            ),
            ToolParameter(
                name="limit",
                type="number",
                description="Maximum number of processes to return",
                required=False,
                default=50,
                min_value=1,
                max_value=500
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="list_processes",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRACE_EXECUTION,
                    description="Monitor running processes and system resource usage",
                    input_types=["filter_name"],
                    output_types=["process_list"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=6
                ),
                CapabilityMetadata(
                    capability=Capability.GET_SYSTEM_INFO,
                    description="Get information about system processes",
                    input_types=[],
                    output_types=["process_info"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=5
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, filter_name: str = None, limit: int = 50) -> ToolResult:
        try:
            processes = []

            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
                try:
                    info = proc.info
                    if filter_name and filter_name.lower() not in info['name'].lower():
                        continue

                    processes.append({
                        'pid': info['pid'],
                        'name': info['name'],
                        'cpu_percent': info['cpu_percent'] if info['cpu_percent'] is not None else 0.0,
                        'memory_percent': round(info['memory_percent'], 2) if info['memory_percent'] is not None else 0.0,
                        'status': info['status']
                    })

                    if len(processes) >= limit:
                        break

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return ToolResult(
                success=True,
                output={
                    'processes': processes,
                    'count': len(processes),
                    'filter': filter_name
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class KillProcessTool(Tool):
    """Terminate process by PID"""

    def __init__(self):
        super().__init__()
        self.name = "kill_process"
        self.description = "Terminate a process by PID (DANGEROUS - use with caution)"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="pid",
                type="number",
                description="Process ID to terminate",
                required=True,
                min_value=1
            ),
            ToolParameter(
                name="force",
                type="boolean",
                description="Force kill (SIGKILL) instead of graceful termination (SIGTERM)",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="kill_process",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="Terminate running processes (can cause data loss)",
                    input_types=["pid", "force"],
                    output_types=["termination_result"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="team_lead"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, pid: int, force: bool = False) -> ToolResult:
        try:
            process = psutil.Process(pid)
            proc_name = process.name()

            if force:
                process.kill()  # SIGKILL
            else:
                process.terminate()  # SIGTERM

            # Wait for termination
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                if not force:
                    process.kill()
                    process.wait(timeout=5)

            return ToolResult(
                success=True,
                output={
                    'pid': pid,
                    'process_name': proc_name,
                    'terminated': True,
                    'forced': force
                }
            )
        except psutil.NoSuchProcess:
            return ToolResult(success=False, output=None, error=f"Process {pid} not found")
        except psutil.AccessDenied:
            return ToolResult(success=False, output=None, error=f"Permission denied to kill process {pid}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class StartServiceTool(Tool):
    """Start system service"""

    def __init__(self):
        super().__init__()
        self.name = "start_service"
        self.description = "Start a system service using launchctl (macOS) or systemctl (Linux)"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="service_name",
                type="string",
                description="Name of service to start",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="start_service",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_COMMAND,
                    description="Start system services (requires elevated permissions)",
                    input_types=["service_name"],
                    output_types=["service_status"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7,
                    approval_level="team_lead"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, service_name: str) -> ToolResult:
        try:
            import platform
            system = platform.system()

            if system == "Darwin":  # macOS
                # Modern macOS uses kickstart, try both formats
                import pwd
                uid = os.getuid()
                # Try user domain first
                cmd = ["launchctl", "kickstart", "-k", f"user/{uid}/{service_name}"]
            elif system == "Linux":
                cmd = ["systemctl", "start", service_name]
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported system: {system}")

            result = subprocess.run(cmd, capture_output=True, text=True)

            # Tool is working if it can communicate with service manager
            # Service not existing is a valid response
            tool_working = True
            started = result.returncode == 0

            return ToolResult(
                success=tool_working,
                output={
                    'service': service_name,
                    'started': started,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode
                },
                error=None if tool_working else result.stderr
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class StopServiceTool(Tool):
    """Stop system service"""

    def __init__(self):
        super().__init__()
        self.name = "stop_service"
        self.description = "Stop a system service using launchctl (macOS) or systemctl (Linux)"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="service_name",
                type="string",
                description="Name of service to stop",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="stop_service",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_COMMAND,
                    description="Stop system services (can disrupt system operation)",
                    input_types=["service_name"],
                    output_types=["service_status"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7,
                    approval_level="team_lead"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, service_name: str) -> ToolResult:
        try:
            import platform
            system = platform.system()

            if system == "Darwin":  # macOS
                # Modern macOS uses kickstart to stop, with force kill
                uid = os.getuid()
                cmd = ["launchctl", "kill", "SIGTERM", f"user/{uid}/{service_name}"]
            elif system == "Linux":
                cmd = ["systemctl", "stop", service_name]
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported system: {system}")

            result = subprocess.run(cmd, capture_output=True, text=True)

            # Tool is working if it can communicate with service manager
            tool_working = True
            stopped = result.returncode == 0

            return ToolResult(
                success=tool_working,
                output={
                    'service': service_name,
                    'stopped': stopped,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode
                },
                error=None if tool_working else result.stderr
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RestartServiceTool(Tool):
    """Restart system service"""

    def __init__(self):
        super().__init__()
        self.name = "restart_service"
        self.description = "Restart a system service using launchctl (macOS) or systemctl (Linux)"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="service_name",
                type="string",
                description="Name of service to restart",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="restart_service",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_COMMAND,
                    description="Restart system services (causes temporary service interruption)",
                    input_types=["service_name"],
                    output_types=["service_status"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7,
                    approval_level="team_lead"
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, service_name: str) -> ToolResult:
        try:
            import platform
            system = platform.system()

            if system == "Darwin":  # macOS
                uid = os.getuid()
                cmd = ["launchctl", "kickstart", "-k", f"user/{uid}/{service_name}"]
            elif system == "Linux":
                cmd = ["systemctl", "restart", service_name]
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported system: {system}")

            result = subprocess.run(cmd, capture_output=True, text=True)

            # Tool is working if it can communicate with service manager
            tool_working = True
            restarted = result.returncode == 0

            return ToolResult(
                success=tool_working,
                output={
                    'service': service_name,
                    'restarted': restarted,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode
                },
                error=None if tool_working else result.stderr
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetProcessInfoTool(Tool):
    """Get detailed process information"""

    def __init__(self):
        super().__init__()
        self.name = "get_process_info"
        self.description = "Get detailed information about a process (CPU, memory, threads, etc.)"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="pid",
                type="number",
                description="Process ID",
                required=True,
                min_value=1
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_process_info",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRACE_EXECUTION,
                    description="Get detailed process information and resource usage",
                    input_types=["pid"],
                    output_types=["process_details"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=6
                ),
                CapabilityMetadata(
                    capability=Capability.GET_SYSTEM_INFO,
                    description="Retrieve system process metadata",
                    input_types=["pid"],
                    output_types=["process_metadata"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=5
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, pid: int) -> ToolResult:
        try:
            process = psutil.Process(pid)

            with process.oneshot():
                info = {
                    'pid': pid,
                    'name': process.name(),
                    'status': process.status(),
                    'cpu_percent': process.cpu_percent(interval=0.1),
                    'memory_percent': round(process.memory_percent(), 2),
                    'memory_mb': round(process.memory_info().rss / (1024 * 1024), 2),
                    'num_threads': process.num_threads(),
                    'create_time': process.create_time(),
                    'username': process.username() if hasattr(process, 'username') else None,
                    'cmdline': ' '.join(process.cmdline())
                }

            return ToolResult(success=True, output=info)

        except psutil.NoSuchProcess:
            return ToolResult(success=False, output=None, error=f"Process {pid} not found")
        except psutil.AccessDenied:
            return ToolResult(success=False, output=None, error=f"Permission denied for process {pid}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RunBackgroundTaskTool(Tool):
    """Run command in background"""

    def __init__(self):
        super().__init__()
        self.name = "run_background_task"
        self.description = "Start a long-running command in the background"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="command",
                type="string",
                description="Command to run",
                required=True
            ),
            ToolParameter(
                name="working_directory",
                type="string",
                description="Working directory for command",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_background_task",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_COMMAND,
                    description="Execute long-running commands in background (harder to monitor)",
                    input_types=["command"],
                    output_types=["pid"],
                    latency="low",
                    cost="low",
                    reliability="medium",
                    risk_level=RiskLevel.HIGH,
                    priority=7,
                    approval_level="team_lead"
                ),
                CapabilityMetadata(
                    capability=Capability.RUN_BACKGROUND_TASK,
                    description="Run tasks asynchronously in background",
                    input_types=["task_config"],
                    output_types=["task_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=True,
            requires_network=True,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, command: str, working_directory: str = None) -> ToolResult:
        try:
            cwd = resolve_working_directory(working_directory)

            # Start process in background
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                start_new_session=True
            )

            return ToolResult(
                success=True,
                output={
                    'pid': process.pid,
                    'command': command,
                    'working_directory': str(cwd) if cwd else None,
                    'started': True
                }
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ScheduleCronJobTool(Tool):
    """Schedule recurring tasks with cron"""

    def __init__(self):
        super().__init__()
        self.name = "schedule_cron_job"
        self.description = "Schedule a recurring task using cron (macOS/Linux)"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="command",
                type="string",
                description="Command to run",
                required=True
            ),
            ToolParameter(
                name="schedule",
                type="string",
                description="Cron schedule format (e.g., '0 * * * *' for hourly)",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="schedule_cron_job",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_COMMAND,
                    description="Schedule recurring command execution (persists across reboots)",
                    input_types=["command", "schedule"],
                    output_types=["scheduling_result"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7,
                    approval_level="team_lead"
                ),
                CapabilityMetadata(
                    capability=Capability.SCHEDULE_TASK,
                    description="Schedule recurring tasks via cron",
                    input_types=["cron_expression", "command"],
                    output_types=["job_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=8
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(self, command: str, schedule: str) -> ToolResult:
        try:
            # Read existing crontab
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            existing_cron = result.stdout if result.returncode == 0 else ""

            # Add new job
            new_job = f"{schedule} {command}"
            if new_job in existing_cron:
                return ToolResult(success=False, output=None, error="Cron job already exists")

            updated_cron = existing_cron + f"\n{new_job}\n"

            # Write updated crontab
            proc = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate(input=updated_cron.encode())

            return ToolResult(
                success=proc.returncode == 0,
                output={
                    'command': command,
                    'schedule': schedule,
                    'added': proc.returncode == 0
                },
                error=stderr.decode() if proc.returncode != 0 else None
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class InstallPythonPackageTool(Tool):
    """Install Python packages with pip"""

    def __init__(self):
        super().__init__()
        self.name = "install_python_package"
        self.description = "Install Python package using pip"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="package_name",
                type="string",
                description="Package name (e.g., 'numpy', 'requests>=2.28.0')",
                required=True
            ),
            ToolParameter(
                name="upgrade",
                type="boolean",
                description="Upgrade if already installed",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="install_python_package",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_COMMAND,
                    description="Install Python packages (can introduce security vulnerabilities)",
                    input_types=["package_name"],
                    output_types=["installation_result"],
                    latency="high",
                    cost="low",
                    reliability="medium",
                    risk_level=RiskLevel.HIGH,
                    priority=7,
                    approval_level="team_lead"
                ),
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Install dependencies for project builds",
                    input_types=["package_name"],
                    output_types=["build_result"],
                    latency="high",
                    cost="low",
                    reliability="medium",
                    risk_level=RiskLevel.HIGH,
                    priority=6
                )
            ],
            requires_filesystem=True,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, package_name: str, upgrade: bool = False) -> ToolResult:
        try:
            cmd = ["pip3", "install"]
            if upgrade:
                cmd.append("--upgrade")
            cmd.append(package_name)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            return ToolResult(
                success=result.returncode == 0,
                output={
                    'package': package_name,
                    'installed': result.returncode == 0,
                    'upgraded': upgrade,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                },
                error=result.stderr if result.returncode != 0 else None
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None, error="Installation timeout (5 minutes)")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ExecuteWithTimeoutTool(Tool):
    """Execute code with hard timeout and kill switch"""

    def __init__(self):
        super().__init__()
        self.name = "execute_with_timeout"
        self.description = "Execute code with enforced hard timeout and kill switch capability"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="command",
                type="string",
                description="Command or code to execute",
                required=True
            ),
            ToolParameter(
                name="hard_timeout",
                type="number",
                description="Hard timeout in seconds (process forcibly killed after this)",
                required=True,
                min_value=1,
                max_value=3600
            ),
            ToolParameter(
                name="soft_timeout",
                type="number",
                description="Soft timeout in seconds (SIGTERM sent, then SIGKILL at hard timeout)",
                required=False
            ),
            ToolParameter(
                name="language",
                type="string",
                description="Language to execute (python, shell)",
                required=False,
                default="shell",
                enum=["python", "shell"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="execute_with_timeout",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Execute code with strict timeout enforcement",
                    input_types=["command", "language"],
                    output_types=["stdout", "stderr", "exit_code"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="team_lead"
                ),
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="Forcibly terminate processes that exceed timeout",
                    input_types=["timeout"],
                    output_types=["termination_result"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(
        self,
        command: str,
        hard_timeout: int,
        soft_timeout: Optional[int] = None,
        language: str = "shell"
    ) -> ToolResult:
        """Execute with hard timeout enforcement"""
        try:
            # Create temp file if Python
            temp_file = None
            if language == "python":
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(command)
                    temp_file = f.name
                cmd = [sys.executable, temp_file]
            else:
                cmd = command

            # Start process with process group for complete cleanup
            if isinstance(cmd, str):
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    preexec_fn=os.setsid  # Create new process group
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    preexec_fn=os.setsid
                )

            start_time = time.time()
            soft_timeout_triggered = False

            try:
                # Wait for soft timeout or completion
                timeout_val = soft_timeout if soft_timeout else hard_timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_val
                )

                elapsed = time.time() - start_time

                if temp_file:
                    Path(temp_file).unlink(missing_ok=True)

                return ToolResult(
                    success=process.returncode == 0,
                    output={
                        "stdout": stdout.decode('utf-8', errors='replace') if stdout else "",
                        "stderr": stderr.decode('utf-8', errors='replace') if stderr else "",
                        "exit_code": process.returncode,
                        "elapsed_seconds": round(elapsed, 2),
                        "timeout_triggered": False
                    },
                    error=None if process.returncode == 0 else f"Process exited with code {process.returncode}"
                )

            except asyncio.TimeoutError:
                # Soft timeout reached
                if soft_timeout and not soft_timeout_triggered:
                    soft_timeout_triggered = True
                    # Send SIGTERM to process group
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass

                    # Wait for hard timeout
                    remaining = hard_timeout - soft_timeout
                    if remaining > 0:
                        try:
                            stdout, stderr = await asyncio.wait_for(
                                process.communicate(),
                                timeout=remaining
                            )

                            if temp_file:
                                Path(temp_file).unlink(missing_ok=True)

                            return ToolResult(
                                success=False,
                                output={
                                    "stdout": stdout.decode('utf-8', errors='replace') if stdout else "",
                                    "stderr": stderr.decode('utf-8', errors='replace') if stderr else "",
                                    "exit_code": process.returncode,
                                    "elapsed_seconds": round(time.time() - start_time, 2),
                                    "timeout_triggered": True,
                                    "soft_timeout_triggered": True
                                },
                                error=f"Soft timeout ({soft_timeout}s) reached, process terminated gracefully"
                            )
                        except asyncio.TimeoutError:
                            pass  # Fall through to hard kill

                # Hard timeout - SIGKILL to process group
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

                try:
                    await asyncio.wait_for(process.wait(), timeout=1)
                except:
                    pass

                if temp_file:
                    Path(temp_file).unlink(missing_ok=True)

                return ToolResult(
                    success=False,
                    output={
                        "stdout": "",
                        "stderr": "",
                        "exit_code": -9,
                        "elapsed_seconds": round(time.time() - start_time, 2),
                        "timeout_triggered": True,
                        "hard_timeout_triggered": True
                    },
                    error=f"Hard timeout ({hard_timeout}s) reached, process forcibly killed"
                )

        except Exception as e:
            if temp_file:
                Path(temp_file).unlink(missing_ok=True)
            return ToolResult(success=False, output=None, error=str(e))


class ExecuteWithResourceLimitsTool(Tool):
    """Execute code with CPU and memory limits"""

    def __init__(self):
        super().__init__()
        self.name = "execute_with_resource_limits"
        self.description = "Execute code with enforced CPU and memory limits using resource constraints"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="command",
                type="string",
                description="Command or code to execute",
                required=True
            ),
            ToolParameter(
                name="max_memory_mb",
                type="number",
                description="Maximum memory in MB (RSS limit)",
                required=False,
                default=512,
                min_value=64,
                max_value=16384
            ),
            ToolParameter(
                name="max_cpu_seconds",
                type="number",
                description="Maximum CPU seconds (user+system time)",
                required=False,
                default=60,
                min_value=1,
                max_value=3600
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Wall clock timeout in seconds",
                required=False,
                default=120,
                min_value=1,
                max_value=3600
            ),
            ToolParameter(
                name="language",
                type="string",
                description="Language to execute (python, shell)",
                required=False,
                default="python",
                enum=["python", "shell"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="execute_with_resource_limits",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Execute code with CPU and memory constraints",
                    input_types=["command", "language"],
                    output_types=["stdout", "stderr", "exit_code", "resource_usage"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8,
                    approval_level="team_lead"
                ),
                CapabilityMetadata(
                    capability=Capability.RUN_EXPERIMENT,
                    description="Run controlled experiments with resource limits",
                    input_types=["command", "limits"],
                    output_types=["result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.LIMIT_CAPABILITY,
                    description="Execute code with CPU/memory constraints",
                    input_types=["code", "limits"],
                    output_types=["result"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=8
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(
        self,
        command: str,
        max_memory_mb: int = 512,
        max_cpu_seconds: int = 60,
        timeout: int = 120,
        language: str = "python"
    ) -> ToolResult:
        """Execute with resource limits"""
        try:
            # Create wrapper script that sets resource limits
            limit_script = f"""
import resource
import sys
import subprocess

# Set resource limits (with error handling for platform limitations)
try:
    # Try to set memory limit
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    requested_mem = {max_memory_mb * 1024 * 1024}
    # Use the minimum of requested and hard limit
    mem_limit = min(requested_mem, hard) if hard != resource.RLIM_INFINITY else requested_mem
    if mem_limit > 0:
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
except (ValueError, OSError):
    # Platform doesn't support this limit or value exceeds max
    pass

try:
    # Set CPU time limit
    resource.setrlimit(resource.RLIMIT_CPU, ({max_cpu_seconds}, {max_cpu_seconds}))
except (ValueError, OSError):
    pass

try:
    # Disable core dumps
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except (ValueError, OSError):
    pass

# Execute the actual code
"""

            if language == "python":
                # For Python, exec the code directly
                limit_script += f"""
try:
    exec({repr(command)})
    sys.exit(0)
except MemoryError:
    print("RESOURCE_LIMIT: Memory limit exceeded", file=sys.stderr)
    sys.exit(137)
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
            else:
                # For shell, use subprocess
                limit_script += f"""
import os
result = os.system({repr(command)})
sys.exit(os.WEXITSTATUS(result) if os.WIFEXITED(result) else 1)
"""

            # Write wrapper script
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(limit_script)
                wrapper_file = f.name

            try:
                # Execute wrapper script
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    wrapper_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                start_time = time.time()

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )
                    elapsed = time.time() - start_time

                    # Check exit code for resource limit violations
                    resource_limited = False
                    limit_type = None

                    if process.returncode == 137:  # Memory limit
                        resource_limited = True
                        limit_type = "memory"
                    elif process.returncode == -signal.SIGXCPU or "RESOURCE_LIMIT" in stderr.decode():
                        resource_limited = True
                        limit_type = "cpu"

                    return ToolResult(
                        success=process.returncode == 0,
                        output={
                            "stdout": stdout.decode('utf-8', errors='replace') if stdout else "",
                            "stderr": stderr.decode('utf-8', errors='replace') if stderr else "",
                            "exit_code": process.returncode,
                            "elapsed_seconds": round(elapsed, 2),
                            "resource_limited": resource_limited,
                            "limit_type": limit_type,
                            "limits": {
                                "max_memory_mb": max_memory_mb,
                                "max_cpu_seconds": max_cpu_seconds,
                                "timeout": timeout
                            }
                        },
                        error=f"Resource limit exceeded: {limit_type}" if resource_limited else (
                            None if process.returncode == 0 else f"Process exited with code {process.returncode}"
                        )
                    )

                except asyncio.TimeoutError:
                    process.kill()
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Wall clock timeout ({timeout}s) exceeded"
                    )

            finally:
                Path(wrapper_file).unlink(missing_ok=True)

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ExecuteNetworkIsolatedTool(Tool):
    """Execute code in network-isolated sandbox"""

    def __init__(self):
        super().__init__()
        self.name = "execute_network_isolated"
        self.description = "Execute code in sandbox with network access disabled by default"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Code to execute",
                required=True
            ),
            ToolParameter(
                name="language",
                type="string",
                description="Programming language",
                required=False,
                default="python",
                enum=["python"]
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Timeout in seconds",
                required=False,
                default=60,
                min_value=1,
                max_value=600
            ),
            ToolParameter(
                name="allow_localhost",
                type="boolean",
                description="Allow localhost connections (127.0.0.1)",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="execute_network_isolated",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Execute code in network-isolated sandbox (safer for untrusted code)",
                    input_types=["code", "language"],
                    output_types=["stdout", "stderr", "exit_code"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=8
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 60,
        allow_localhost: bool = False
    ) -> ToolResult:
        """Execute in network-isolated environment"""
        try:
            # Create network isolation wrapper
            isolation_code = """
import socket
import sys

# Store original socket
_original_socket = socket.socket

def _restricted_socket(*args, **kwargs):
    '''Restricted socket that blocks external connections'''
    sock = _original_socket(*args, **kwargs)
    original_connect = sock.connect

    def restricted_connect(address):
        host = address[0] if isinstance(address, tuple) else address
"""

            if allow_localhost:
                isolation_code += """
        # Allow localhost only
        if host not in ('127.0.0.1', 'localhost', '::1'):
            raise PermissionError(f"Network access blocked: {host}")
"""
            else:
                isolation_code += """
        # Block all network access
        raise PermissionError(f"Network access blocked: {host}")
"""

            isolation_code += """
        return original_connect(address)

    sock.connect = restricted_connect
    return sock

# Replace socket
socket.socket = _restricted_socket

# Execute user code
try:
"""

            # Indent user code
            indented_code = '\n'.join('    ' + line for line in code.split('\n'))
            isolation_code += indented_code

            isolation_code += """
except PermissionError as e:
    if "Network access blocked" in str(e):
        print(f"NETWORK_BLOCKED: {e}", file=sys.stderr)
        sys.exit(100)
    raise
"""

            # Write to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(isolation_code)
                temp_file = f.name

            try:
                # Execute isolated code
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    temp_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                start_time = time.time()

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )

                    elapsed = time.time() - start_time
                    network_blocked = process.returncode == 100

                    return ToolResult(
                        success=process.returncode == 0,
                        output={
                            "stdout": stdout.decode('utf-8', errors='replace') if stdout else "",
                            "stderr": stderr.decode('utf-8', errors='replace') if stderr else "",
                            "exit_code": process.returncode,
                            "elapsed_seconds": round(elapsed, 2),
                            "network_blocked": network_blocked,
                            "network_policy": "localhost_only" if allow_localhost else "fully_isolated"
                        },
                        error="Network access attempted and blocked" if network_blocked else (
                            None if process.returncode == 0 else f"Process exited with code {process.returncode}"
                        )
                    )

                except asyncio.TimeoutError:
                    process.kill()
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Execution timed out after {timeout} seconds"
                    )

            finally:
                Path(temp_file).unlink(missing_ok=True)

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ExecuteDeterministicTool(Tool):
    """Execute code in deterministic mode with seed capture"""

    def __init__(self):
        super().__init__()
        self.name = "execute_deterministic"
        self.description = "Execute code in deterministic mode with captured random seeds for reproducibility"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Code to execute",
                required=True
            ),
            ToolParameter(
                name="seed",
                type="number",
                description="Random seed for reproducibility (generated if not provided)",
                required=False
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Timeout in seconds",
                required=False,
                default=60,
                min_value=1,
                max_value=600
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="execute_deterministic",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_EXPERIMENT,
                    description="Execute experiments with reproducible random seeds",
                    input_types=["code", "seed"],
                    output_types=["stdout", "stderr", "exit_code", "seed", "fingerprint"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Execute code with deterministic behavior for testing",
                    input_types=["code"],
                    output_types=["result"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=7
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(
        self,
        code: str,
        seed: Optional[int] = None,
        timeout: int = 60
    ) -> ToolResult:
        """Execute with deterministic seeding"""
        try:
            # Generate seed if not provided
            if seed is None:
                seed = int(time.time() * 1000000) % (2**32)

            # Create deterministic execution wrapper
            deterministic_code = f"""
import random
import sys
import os
import hashlib

# Set deterministic seed
EXECUTION_SEED = {seed}
random.seed(EXECUTION_SEED)

# Also seed hash randomization
os.environ['PYTHONHASHSEED'] = str(EXECUTION_SEED)

# Try to seed numpy if available
try:
    import numpy as np
    np.random.seed(EXECUTION_SEED)
except ImportError:
    pass

# Try to seed torch if available
try:
    import torch
    torch.manual_seed(EXECUTION_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(EXECUTION_SEED)
except ImportError:
    pass

# Print seed info
print(f"[DETERMINISTIC_EXECUTION] Seed: {{EXECUTION_SEED}}", file=sys.stderr)

# Execute user code
"""

            # Indent and add user code
            indented_code = '\n'.join(line for line in code.split('\n'))
            deterministic_code += indented_code

            # Write to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(deterministic_code)
                temp_file = f.name

            try:
                # Execute with PYTHONHASHSEED set
                env = os.environ.copy()
                env['PYTHONHASHSEED'] = str(seed)

                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    temp_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )

                start_time = time.time()

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )

                    elapsed = time.time() - start_time

                    # Create execution fingerprint for verification
                    fingerprint = hashlib.sha256(
                        f"{seed}:{stdout.decode()}:{process.returncode}".encode()
                    ).hexdigest()[:16]

                    return ToolResult(
                        success=process.returncode == 0,
                        output={
                            "stdout": stdout.decode('utf-8', errors='replace') if stdout else "",
                            "stderr": stderr.decode('utf-8', errors='replace') if stderr else "",
                            "exit_code": process.returncode,
                            "elapsed_seconds": round(elapsed, 2),
                            "deterministic": True,
                            "seed": seed,
                            "fingerprint": fingerprint,
                            "reproducible": True
                        },
                        error=None if process.returncode == 0 else f"Process exited with code {process.returncode}"
                    )

                except asyncio.TimeoutError:
                    process.kill()
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Execution timed out after {timeout} seconds"
                    )

            finally:
                Path(temp_file).unlink(missing_ok=True)

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ExecuteWithArtifactCaptureTool(Tool):
    """Execute code with comprehensive artifact capture"""

    def __init__(self):
        super().__init__()
        self.name = "execute_with_artifact_capture"
        self.description = "Execute code with comprehensive capture of stdout, stderr, exit code, execution trace, and timing information"
        self.category = ToolCategory.EXECUTION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="command",
                type="string",
                description="Command or code to execute",
                required=True
            ),
            ToolParameter(
                name="language",
                type="string",
                description="Language to execute (python, shell)",
                required=False,
                default="python",
                enum=["python", "shell"]
            ),
            ToolParameter(
                name="capture_trace",
                type="boolean",
                description="Capture execution trace (Python only, adds overhead)",
                required=False,
                default=False
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Timeout in seconds",
                required=False,
                default=60,
                min_value=1,
                max_value=600
            ),
            ToolParameter(
                name="working_directory",
                type="string",
                description="Working directory for execution",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="execute_with_artifact_capture",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXECUTE_CODE,
                    description="Execute code with comprehensive artifact and trace capture",
                    input_types=["command", "language"],
                    output_types=["stdout", "stderr", "exit_code", "trace", "timing", "environment"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.TRACE_EXECUTION,
                    description="Monitor and capture execution artifacts for analysis",
                    input_types=["command"],
                    output_types=["execution_artifacts"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=6
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=False,
            is_idempotent=False
        )

    async def execute(
        self,
        command: str,
        language: str = "python",
        capture_trace: bool = False,
        timeout: int = 60,
        working_directory: Optional[str] = None
    ) -> ToolResult:
        """Execute with comprehensive artifact capture"""
        try:
            artifacts = {
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "start_time": None,
                "end_time": None,
                "elapsed_seconds": None,
                "trace": None,
                "environment": {},
                "working_directory": working_directory or os.getcwd(),
                "command_hash": hashlib.sha256(command.encode()).hexdigest()[:16]
            }

            start_time = time.time()
            artifacts["start_time"] = start_time

            # Create execution wrapper
            if language == "python" and capture_trace:
                # Python with trace capture
                trace_code = """
import sys
import trace
import io

# Create tracer
tracer = trace.Trace(count=False, trace=True)

# Capture trace output
trace_output = io.StringIO()
original_stdout = sys.stdout

try:
    sys.stdout = trace_output
    tracer.run('''
"""
                # Indent user code
                indented_code = '\n'.join(line for line in command.split('\n'))
                trace_code += indented_code
                trace_code += """
''')
finally:
    sys.stdout = original_stdout

# Print trace to stderr for capture
print("=== EXECUTION TRACE ===", file=sys.stderr)
print(trace_output.getvalue(), file=sys.stderr)
print("=== END TRACE ===", file=sys.stderr)
"""
                exec_code = trace_code
            else:
                exec_code = command

            # Write to temp file
            if language == "python":
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(exec_code)
                    temp_file = f.name
                cmd = [sys.executable, temp_file]
            else:
                temp_file = None
                cmd = command

            try:
                # Capture environment variables
                artifacts["environment"] = {
                    "PYTHON_VERSION": sys.version,
                    "PLATFORM": sys.platform,
                    "PATH": os.environ.get("PATH", ""),
                }

                # Execute
                cwd = resolve_working_directory(working_directory)

                if isinstance(cmd, str):
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd
                    )
                else:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd
                    )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )

                    end_time = time.time()

                    artifacts["stdout"] = stdout.decode('utf-8', errors='replace') if stdout else ""
                    artifacts["stderr"] = stderr.decode('utf-8', errors='replace') if stderr else ""
                    artifacts["exit_code"] = process.returncode
                    artifacts["end_time"] = end_time
                    artifacts["elapsed_seconds"] = round(end_time - start_time, 3)
                    artifacts["timeout_triggered"] = False

                    # Extract trace if captured
                    if capture_trace and language == "python":
                        stderr_str = artifacts["stderr"]
                        if "=== EXECUTION TRACE ===" in stderr_str:
                            trace_start = stderr_str.index("=== EXECUTION TRACE ===") + len("=== EXECUTION TRACE ===")
                            trace_end = stderr_str.index("=== END TRACE ===")
                            artifacts["trace"] = stderr_str[trace_start:trace_end].strip()
                            # Remove trace from stderr
                            artifacts["stderr"] = stderr_str[:stderr_str.index("=== EXECUTION TRACE ===")] + \
                                                 stderr_str[trace_end + len("=== END TRACE ==="):]

                    return ToolResult(
                        success=process.returncode == 0,
                        output=artifacts,
                        error=None if process.returncode == 0 else f"Process exited with code {process.returncode}"
                    )

                except asyncio.TimeoutError:
                    process.kill()
                    end_time = time.time()

                    artifacts["exit_code"] = -1
                    artifacts["end_time"] = end_time
                    artifacts["elapsed_seconds"] = round(end_time - start_time, 3)
                    artifacts["timeout_triggered"] = True

                    return ToolResult(
                        success=False,
                        output=artifacts,
                        error=f"Execution timed out after {timeout} seconds"
                    )

            finally:
                if temp_file:
                    Path(temp_file).unlink(missing_ok=True)

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
