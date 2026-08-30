#!/usr/bin/env python3
"""
Reality Verification Layer
==========================

Sits between the artifact checker (Layer 3) and code validator (Layer 4)
in the task completion pipeline.

Problem it solves:
  The LLM verifier evaluates *report quality*, not *environment truth*.
  A well-written report about "successfully deploying Istio" scores 0.98
  even when Istio is not running and no files were actually created.

Verification methods:
  1. FilesystemDiff      — path claims in output doc vs os.path.exists()
  2. DependencyScan      — library/package claims vs importlib.find_spec()
  3. ProcessInspection   — service "successfully integrated" claims vs psutil
  4. ToolLogAnalysis     — claimed code work vs actual tool execution calls
  5. RuntimeProbe        — endpoint/socket reachability (soft / warning only)

Failure semantics:
  hard_failures  — provably false claims: block completion (→ hard_gate_failures)
  warnings       — unverifiable or soft discrepancies: recorded, non-blocking

Hard failures are issued for:
  - EXECUTION/SECURITY_REMEDIATION tasks: missing files, missing required libs,
    no code execution tools called
  - All tasks: files listed in files_created that neither exist on disk nor were
    written by a write_file tool call

Warnings are issued for:
  - RESEARCH/ANALYSIS/PLANNING tasks: path references that don't exist
    (they may be designing a future state, not implementing one)
  - Process checks: services "successfully integrated" but not running locally
  - Runtime probes: endpoints not reachable (may be external/remote)
"""

import importlib.util
import logging
import os
import re
import socket
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# psutil is optional — graceful degradation if absent
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Service → process-name map (for ProcessInspection)
# ---------------------------------------------------------------------------
_SERVICE_PROCESS_MAP: Dict[str, List[str]] = {
    "istio":         ["istiod", "envoy", "pilot-agent"],
    "prometheus":    ["prometheus"],
    "grafana":       ["grafana", "grafana-server"],
    "jaeger":        ["jaeger", "all-in-one"],
    "nginx":         ["nginx"],
    "kafka":         ["kafka.Kafka", "kafka"],
    "redis":         ["redis-server", "redis"],
    "postgres":      ["postgres", "postgresql"],
    "elasticsearch": ["elasticsearch"],
    "kibana":        ["kibana"],
    "ipfs":          ["ipfs"],
    "ganache":       ["ganache", "node"],
    "hardhat":       ["hardhat", "node"],
    "zookeeper":     ["zookeeper"],
    "rabbitmq":      ["rabbitmq", "beam.smp"],
}

# ---------------------------------------------------------------------------
# Library keyword → importable Python module (for DependencyScan)
# None = not a Python package (skip import check, still warn on mention)
# ---------------------------------------------------------------------------
_LIB_MODULE_MAP: Dict[str, Optional[str]] = {
    # Federated / privacy ML
    "tensorflow federated": "tensorflow_federated",
    "tff":                  "tensorflow_federated",
    "pysyft":               "syft",
    "syft":                 "syft",
    "opacus":               "opacus",
    "diffprivlib":          "diffprivlib",
    # General ML
    "tensorflow":           "tensorflow",
    "torch":                "torch",
    "pytorch":              "torch",
    "scikit-learn":         "sklearn",
    "sklearn":              "sklearn",
    "xgboost":              "xgboost",
    "lightgbm":             "lightgbm",
    # Web3 / blockchain
    "web3":                 "web3",
    "ipfshttpclient":       "ipfshttpclient",
    "solidity":             None,   # not a Python package
    "hardhat":              None,
    "truffle":              None,
    # Graph / API
    "graphql":              "graphql",
    "ariadne":              "ariadne",
    "strawberry":           "strawberry",
    "neo4j":                "neo4j",
    "py2neo":               "py2neo",
    # Infra / observability
    "grpc":                 "grpc",
    "kubernetes":           "kubernetes",
    "docker":               "docker",
    "boto3":                "boto3",
    "celery":               "celery",
    "redis":                "redis",
    # Standard data
    "pandas":               "pandas",
    "numpy":                "numpy",
    "scipy":                "scipy",
    "matplotlib":           "matplotlib",
    "sqlalchemy":           "sqlalchemy",
}

# ---------------------------------------------------------------------------
# Service → well-known local TCP port (for RuntimeProbe)
# ---------------------------------------------------------------------------
_SERVICE_PORT_MAP: Dict[str, int] = {
    "grafana":        3000,
    "prometheus":     9090,
    "jaeger":         14268,
    "ipfs":           5001,
    "ethereum":       8545,
    "hardhat":        8545,
    "ganache":        8545,
    "redis":          6379,
    # TorinAI's own instance. 5432 is the shared one holding agentso's
    # tenant databases, and a claim verified against it is a claim about
    # somebody else's database.
    "postgres":       5433,
    "postgresql":     5433,
    "elasticsearch":  9200,
    "kibana":         5601,
    "kafka":          9092,
    "rabbitmq":       5672,
}

# File extensions that indicate a real artifact path
_PATH_EXTENSIONS = (
    ".py", ".json", ".yaml", ".yml", ".md", ".txt", ".sol",
    ".html", ".js", ".ts", ".go", ".rs", ".sh", ".csv",
    ".db", ".sqlite", ".log", ".xml", ".toml", ".cfg", ".ini",
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RealityCheckResult:
    """
    Aggregated result from all 5 reality verification checks.

    passed        — False if any hard_failure is present
    score         — 0.0–1.0, blended into artifact_score in completion_protocol
    hard_failures — provably false claims; each becomes a hard_gate_failure
    warnings      — soft discrepancies; recorded in issues, non-blocking
    detail        — per-check breakdown dict for logging / storage
    """
    passed: bool
    score: float
    hard_failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main verifier
# ---------------------------------------------------------------------------

class RealityVerifier:
    """
    Reality Verification Layer — environment state truth checks.

    Stateless: every verify() call is independent.
    Does NOT evaluate report quality; evaluates environment truth.

    The `proposal` argument is duck-typed (not imported from completion_protocol)
    to avoid circular imports.  Expected attributes:
        proposal.files_created   : List[str]
        proposal.files_modified  : List[str]
        proposal.claimed_outputs : Dict[str, Any]
        proposal.summary         : str
        proposal.key_findings    : List[str]
    """

    def __init__(self, workspace_root: str = "/Users/stefan/Dominion Labs/TorinAI"):
        self.workspace_root = workspace_root

    # =========================================================================
    # Public entry point
    # =========================================================================

    async def verify(
        self,
        proposal: Any,
        task_description: str,
        task_type: str,
        tool_results: List[Dict[str, Any]],
        output_doc_paths: Optional[List[str]] = None,
    ) -> RealityCheckResult:
        """
        Run all 5 reality checks and aggregate results.

        Parameters
        ----------
        proposal         : CompletionProposal (duck-typed)
        task_description : original task description string
        task_type        : TaskType name, e.g. "EXECUTION", "RESEARCH"
        tool_results     : list of tool call records from the executor
        output_doc_paths : paths to output documents written by write_file
        """
        hard_failures: List[str] = []
        warnings: List[str] = []
        detail: Dict[str, Any] = {}
        scores: List[float] = []

        # 1 ── Filesystem diff
        fs_score, fs_hard, fs_warn, fs_detail = self._check_filesystem_claims(
            proposal, output_doc_paths or [], task_type
        )
        scores.append(fs_score)
        hard_failures.extend(fs_hard)
        warnings.extend(fs_warn)
        detail["filesystem"] = fs_detail

        # 2 ── Dependency scan
        dep_score, dep_hard, dep_warn, dep_detail = self._check_dependencies(
            task_description, proposal, task_type
        )
        scores.append(dep_score)
        hard_failures.extend(dep_hard)
        warnings.extend(dep_warn)
        detail["dependencies"] = dep_detail

        # 3 ── Process inspection
        proc_score, proc_hard, proc_warn, proc_detail = self._check_processes(
            task_description, proposal
        )
        scores.append(proc_score)
        hard_failures.extend(proc_hard)
        warnings.extend(proc_warn)
        detail["processes"] = proc_detail

        # 4 ── Tool execution log analysis
        tool_score, tool_hard, tool_warn, tool_detail = self._check_tool_execution_logs(
            tool_results, task_type, proposal
        )
        scores.append(tool_score)
        hard_failures.extend(tool_hard)
        warnings.extend(tool_warn)
        detail["tool_logs"] = tool_detail

        # 5 ── Runtime probes (always soft — may be remote/external)
        probe_score, _, probe_warn, probe_detail = self._check_runtime_probes(
            task_description, proposal
        )
        scores.append(probe_score)
        warnings.extend(probe_warn)
        detail["runtime_probes"] = probe_detail

        overall_score = sum(scores) / len(scores) if scores else 1.0
        passed = len(hard_failures) == 0

        if hard_failures:
            logger.warning(
                f"[REALITY] {len(hard_failures)} hard failure(s): "
                f"{hard_failures[:3]}"
            )
        if warnings:
            logger.info(
                f"[REALITY] {len(warnings)} warning(s): {warnings[:3]}"
            )

        return RealityCheckResult(
            passed=passed,
            score=overall_score,
            hard_failures=hard_failures,
            warnings=warnings,
            detail=detail,
        )

    # =========================================================================
    # CHECK 1: Filesystem diff
    # =========================================================================

    def _check_filesystem_claims(
        self,
        proposal: Any,
        output_doc_paths: List[str],
        task_type: str,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """
        Extract all path claims from:
          • proposal.files_created / files_modified
          • output document text (backtick paths, "saved to X" patterns)
          • proposal.claimed_outputs values

        Then verify each claimed path exists on disk.

        EXECUTION/SECURITY_REMEDIATION → missing paths → hard failure
        RESEARCH/ANALYSIS/PLANNING     → missing paths → warning
        """
        hard_failures: List[str] = []
        warnings: List[str] = []
        claimed_paths: Set[str] = set()

        # -- From proposal fields
        for p in (getattr(proposal, "files_created", None) or []):
            if isinstance(p, str) and p:
                claimed_paths.add(p)
        for p in (getattr(proposal, "files_modified", None) or []):
            if isinstance(p, str) and p:
                claimed_paths.add(p)

        # -- From output document text
        doc_texts: List[str] = []
        for doc_path in output_doc_paths:
            try:
                with open(doc_path, "r", errors="replace") as fh:
                    doc_texts.append(fh.read())
            except Exception:
                pass

        for text in doc_texts:
            # Backtick-quoted paths: `…`
            for m in re.finditer(r'`([^`\n]{5,200})`', text):
                candidate = m.group(1).strip()
                if self._looks_like_path(candidate):
                    claimed_paths.add(candidate)

            # "saved as/to/at /abs/path", "created at /abs/path", etc.
            # NOTE: [^\s] stops at spaces, so paths containing spaces in directory
            # components (e.g. "/Users/stefan/Dominion Labs/...") get truncated.
            # Apply _looks_like_path() filter (requires a file extension) so that
            # truncated directory-only fragments don't get checked as artifacts.
            for m in re.finditer(
                r'(?:saved\s+(?:as|to|at)|created\s+(?:as|at|in)|'
                r'written\s+to|stored\s+(?:at|in|as))\s+[`"\']?(/[^\s`"\'<>\n]{5,250})[`"\']?',
                text,
                re.IGNORECASE,
            ):
                candidate = m.group(1).rstrip(".,;)")
                if self._looks_like_path(candidate):
                    claimed_paths.add(candidate)

        # -- From claimed_outputs dict values
        for val in (getattr(proposal, "claimed_outputs", None) or {}).values():
            if isinstance(val, str) and self._looks_like_path(val):
                claimed_paths.add(val)

        # Exclude the output doc paths themselves from the check
        # (the verifier already confirmed those exist via the output gate)
        output_doc_set = set(output_doc_paths)

        if not claimed_paths:
            return 1.0, [], [], {"checked": 0, "found": 0, "missing": []}

        missing: List[str] = []
        found: List[str] = []
        is_impl_task = task_type.upper() in ("EXECUTION", "SECURITY_REMEDIATION")

        for raw_path in claimed_paths:
            if raw_path in output_doc_set:
                found.append(raw_path)
                continue
            # Skip iCloud/CloudDocs paths — they are the output report location
            # and are already validated by the output gate; checking them here
            # causes false-positive score penalties on every revision attempt.
            if "CloudDocs" in raw_path or "output-file" in raw_path:
                found.append(raw_path)
                continue
            full_path = (
                raw_path if os.path.isabs(raw_path)
                else os.path.join(self.workspace_root, raw_path)
            )
            if os.path.exists(full_path):
                found.append(raw_path)
                # Blind Spot 2: validate content quality (not trivially empty)
                content_msg, is_hard = self._validate_artifact_content(
                    full_path, is_impl_task
                )
                if content_msg:
                    if is_hard:
                        hard_failures.append(content_msg)
                    else:
                        warnings.append(content_msg)
            else:
                missing.append(raw_path)
                msg = f"Claimed path does not exist on disk: {raw_path}"
                if is_impl_task:
                    hard_failures.append(msg)
                else:
                    warnings.append(msg)

        score = len(found) / len(claimed_paths) if claimed_paths else 1.0
        return score, hard_failures, warnings, {
            "checked": len(claimed_paths),
            "found": len(found),
            "missing": missing[:15],
        }

    @staticmethod
    def _looks_like_path(s: str) -> bool:
        """Heuristic: absolute path ending in a known file extension."""
        return (
            s.startswith("/")
            and len(s) > 5
            and any(s.endswith(ext) for ext in _PATH_EXTENSIONS)
            and "\n" not in s
            and " " not in s.split("/")[-1]  # filename has no spaces
        )

    def _validate_artifact_content(
        self, path: str, is_impl_task: bool
    ) -> Tuple[Optional[str], bool]:
        """
        Blind Spot 2: Check artifact has non-trivial content.

        Returns (message, is_hard_failure).
          message=None        → content is OK, no issue.
          is_hard_failure=True  → add to hard_gate_failures (blocks VERIFIED).
          is_hard_failure=False → add to warnings (non-blocking).
        """
        import json as _json
        try:
            size = os.path.getsize(path)
        except OSError:
            return f"Cannot read file size: {path}", False

        ext = os.path.splitext(path)[1].lower()

        if ext == ".json":
            if size < 10:
                return f"Trivially small JSON artifact ({size} bytes): {path}", is_impl_task
            try:
                with open(path, "r", errors="replace") as f:
                    content = f.read().strip()
                if content in ("{}", "[]", "null", ""):
                    return (
                        f"JSON artifact is empty/trivial (content: '{content[:20]}'): {path}",
                        is_impl_task,
                    )
                data = _json.loads(content)
                if isinstance(data, (dict, list)) and len(data) == 0:
                    return f"JSON artifact is an empty container: {path}", is_impl_task
            except Exception:
                pass  # Not valid JSON — let other checks handle it

        elif ext == ".py":
            if size < 50:
                return (
                    f"Suspiciously small Python file ({size} bytes, likely a stub): {path}",
                    is_impl_task,
                )

        elif size < 20:
            return f"Artifact appears empty ({size} bytes): {path}", is_impl_task

        return None, False  # Content is OK

    # =========================================================================
    # CHECK 2: Dependency scan
    # =========================================================================

    def _check_dependencies(
        self,
        task_description: str,
        proposal: Any,
        task_type: str,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """
        Find library/framework names in task description + proposal text,
        then check whether the corresponding Python module is importable.

        Hard failure: EXECUTION task *uses* a library that isn't installed.
        Warning:      Mention without a use-claim, or non-EXECUTION task type.
        """
        hard_failures: List[str] = []
        warnings: List[str] = []

        combined = " ".join(filter(None, [
            task_description,
            getattr(proposal, "summary", "") or "",
            " ".join(getattr(proposal, "key_findings", None) or []),
            " ".join(
                str(v) for v in
                (getattr(proposal, "claimed_outputs", None) or {}).values()
            ),
        ])).lower()

        verified: List[str] = []
        missing: List[str] = []
        is_impl_task = task_type.upper() in ("EXECUTION", "SECURITY_REMEDIATION")

        for keyword, module_name in _LIB_MODULE_MAP.items():
            if keyword not in combined:
                continue
            if module_name is None:
                # Not a Python package — just note the mention
                continue

            spec = importlib.util.find_spec(module_name)
            is_installed = spec is not None

            if is_installed:
                verified.append(keyword)
                continue

            missing.append(keyword)

            # Determine whether this is an active USE claim vs a mere mention
            use_patterns = [
                rf"using {re.escape(keyword)}",
                rf"using {re.escape(module_name)}",
                rf"import {re.escape(module_name)}",
                rf"implemented.*{re.escape(keyword)}",
                rf"integrat\w*.*{re.escape(keyword)}",
                rf"deployed.*{re.escape(keyword)}",
                rf"tested.*{re.escape(keyword)}",
                rf"with {re.escape(keyword)}",
            ]
            is_use_claim = any(re.search(pat, combined) for pat in use_patterns)

            msg = (
                f"Library '{keyword}' {'used' if is_use_claim else 'mentioned'} "
                f"but not installed (python module: {module_name})"
            )
            if is_use_claim and is_impl_task:
                hard_failures.append(msg)
            else:
                warnings.append(msg)

        # Blind Spot 4: scan created Python files for actual import statements.
        # Catches indirect phrasing like "compatible with TFF" where keyword
        # matching above misses it, but the generated file imports tensorflow_federated.
        _file_imports = self._scan_files_for_imports(
            getattr(proposal, "files_created", None) or []
        )
        for imported_mod, import_src_files in _file_imports.items():
            for keyword, known_mod in _LIB_MODULE_MAP.items():
                if known_mod != imported_mod:
                    continue
                if keyword in verified:
                    continue  # Already confirmed installed
                spec = importlib.util.find_spec(imported_mod)
                if spec is None:
                    msg = (
                        f"Module '{imported_mod}' is imported in "
                        f"{import_src_files[0]} but is not installed"
                    )
                    if keyword not in missing:
                        missing.append(keyword)
                    if is_impl_task:
                        if msg not in hard_failures:
                            hard_failures.append(msg)
                    else:
                        if msg not in warnings:
                            warnings.append(msg)
                else:
                    if keyword not in verified:
                        verified.append(keyword)

        total = len(verified) + len(missing)
        score = len(verified) / total if total > 0 else 1.0

        return score, hard_failures, warnings, {
            "verified_installed": verified,
            "missing": missing,
        }

    # =========================================================================
    # CHECK 3: Process inspection
    # =========================================================================

    def _check_processes(
        self,
        task_description: str,
        proposal: Any,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """
        Check if services claimed as "successfully integrated / deployed /
        running" are actually present as OS processes.

        Always soft (warning only) — services may be external or containerised.
        Requires psutil; gracefully skips if unavailable.
        """
        if not _PSUTIL_AVAILABLE:
            return 1.0, [], [], {"available": False, "reason": "psutil not installed"}

        warnings: List[str] = []

        combined = (
            task_description + " " +
            (getattr(proposal, "summary", "") or "")
        ).lower()

        # Strong claim: "successfully integrated/deployed/..."
        _strong_claim_re = re.compile(
            r'(?:successfully\s+(?:integrated|deployed|configured|installed|setup)|'
            r'(?:integrated|deployed|configured|installed)\s+successfully)',
            re.IGNORECASE,
        )
        has_strong_claim = bool(_strong_claim_re.search(combined))

        # Blind Spot 3: also detect service noun + action verb in the same sentence,
        # catching weaker claims like "Grafana was deployed" or "configured the Istio mesh".
        _action_verb_re = re.compile(
            r'\b(?:deploy|integrat|configur|install|setup|enabl|start|run|launch|creat|build)\w*\b',
            re.IGNORECASE,
        )
        sentences = re.split(r'[.!?\n]', combined)
        services_weak_claim: List[str] = []
        for svc in _SERVICE_PROCESS_MAP:
            if svc not in combined:
                continue
            for sentence in sentences:
                if svc in sentence and _action_verb_re.search(sentence):
                    if svc not in services_weak_claim:
                        services_weak_claim.append(svc)
                    break

        if has_strong_claim:
            services_mentioned = [svc for svc in _SERVICE_PROCESS_MAP if svc in combined]
        else:
            services_mentioned = services_weak_claim

        if not services_mentioned:
            return 1.0, [], [], {
                "available": True,
                "claimed_running": [],
                "note": "no integration claim found (strong or weak)",
            }

        # Get running process names from OS
        try:
            running_names: Set[str] = {
                p.info["name"].lower()
                for p in psutil.process_iter(["name"])
                if p.info.get("name")
            }
        except Exception as exc:
            return 1.0, [], [], {"available": True, "error": str(exc)}

        verified_running: List[str] = []
        not_running: List[str] = []

        for svc in services_mentioned:
            proc_names = _SERVICE_PROCESS_MAP[svc]
            if any(pn.lower() in running_names for pn in proc_names):
                verified_running.append(svc)
            else:
                not_running.append(svc)
                warnings.append(
                    f"Service '{svc}' claimed as successfully integrated/deployed "
                    f"but no matching OS process found (expected one of: {proc_names})"
                )

        # Soft scoring: penalise 0.15 per unverified service, floor at 0.5
        penalty = 0.15 * len(not_running)
        score = max(0.5, 1.0 - penalty)

        return score, [], warnings, {
            "available": True,
            "claimed_running": services_mentioned,
            "verified_running": verified_running,
            "not_running": not_running,
        }

    # =========================================================================
    # CHECK 4: Tool execution log analysis
    # =========================================================================

    def _check_tool_execution_logs(
        self,
        tool_results: List[Dict[str, Any]],
        task_type: str,
        proposal: Any,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """
        Verify that claimed work is backed by actual tool execution records.

        Hard failures:
        • EXECUTION/SECURITY task that called zero code-execution tools
        • File in files_created that: (a) was never written by write_file AND
          (b) does not actually exist on disk

        Warnings:
        • Non-EXECUTION tasks that claim code-heavy outcomes but ran no code tools
        """
        _CODE_TOOLS = {"run_python", "run_shell_command", "execute_command", "run_script"}
        _WRITE_TOOLS = {"write_file", "create_file"}
        _PATCH_TOOLS = {"patch_file", "atomic_write_file"}

        hard_failures: List[str] = []
        warnings: List[str] = []

        successful = [r for r in tool_results if r.get("success")]
        code_calls = [r for r in tool_results if r.get("tool") in _CODE_TOOLS]
        write_calls = [r for r in successful if r.get("tool") in _WRITE_TOOLS]
        patch_calls = [r for r in successful if r.get("tool") in _PATCH_TOOLS]

        # Paths actually written during this task via write_file/create_file
        actually_written: Set[str] = set()
        for r in write_calls:
            p = (r.get("parameters") or {}).get("path", "") or (r.get("parameters") or {}).get("file_path", "")
            if p:
                actually_written.add(p)
        # patch_file uses file_path — also counts as a real artifact
        for r in patch_calls:
            p = (r.get("parameters") or {}).get("file_path", "") or (r.get("parameters") or {}).get("path", "")
            if p:
                actually_written.add(p)

        is_impl_task = task_type.upper() in ("EXECUTION", "SECURITY_REMEDIATION")

        # -- Hard check: EXECUTION tasks must run code
        if is_impl_task and not code_calls:
            hard_failures.append(
                f"{task_type.upper()} task completed with zero code-execution "
                "tool calls (run_python / run_shell_command / execute_command). "
                "No real implementation can have occurred."
            )

        # Blind Spot 1: code was called but could be trivial (run_python("print('hello')")).
        # EXECUTION tasks must also produce at least one non-trivial artifact (>=50 bytes,
        # not counting the output report) — otherwise no real implementation occurred.
        if is_impl_task and code_calls:
            non_trivial: List[str] = []
            _all_claimed = list(actually_written) + [
                p for p in (getattr(proposal, "files_created", None) or [])
                if isinstance(p, str)
            ]
            for p in _all_claimed:
                if "output-file" in p or "CloudDocs" in p:
                    continue
                full = p if os.path.isabs(p) else os.path.join(self.workspace_root, p)
                try:
                    if os.path.exists(full) and os.path.getsize(full) >= 50:
                        non_trivial.append(p)
                except OSError:
                    pass
            if not non_trivial:
                hard_failures.append(
                    f"{task_type.upper()} task called code-execution tools but produced "
                    "zero non-trivial artifacts (all claimed files are <50 bytes, missing, "
                    "or only the output report). A trivial `run_python('print(...)')` "
                    "does not constitute real implementation."
                )

        # -- Check files_created are traceable
        files_created = getattr(proposal, "files_created", None) or []
        unverified_files: List[str] = []

        for path in files_created:
            if not isinstance(path, str):
                continue
            # Skip the iCloud output report (the output gate already checked it)
            if "output-file" in path or "CloudDocs" in path:
                continue
            if path in actually_written:
                continue  # Backed by write_file call — verified
            # Fall back: check disk existence (could be written by run_python)
            full = path if os.path.isabs(path) else os.path.join(self.workspace_root, path)
            if os.path.exists(full):
                continue  # File exists regardless of how it was created — ok
            unverified_files.append(path)
            msg = (
                f"File '{path}' listed in files_created but "
                "no matching write_file call and file does not exist on disk"
            )
            if is_impl_task:
                hard_failures.append(msg)
            else:
                warnings.append(msg)

        # Soft check: design/research tasks that mention code outcomes but ran nothing
        if not is_impl_task and not code_calls:
            summary_lower = (getattr(proposal, "summary", "") or "").lower()
            code_outcome_words = [
                "implemented", "deployed", "installed", "tested", "ran",
                "executed", "configured", "setup", "running",
            ]
            if any(w in summary_lower for w in code_outcome_words):
                warnings.append(
                    "Summary claims code/deployment outcomes but no code execution "
                    "tools were called during this task"
                )

        # Score
        score_parts: List[float] = []
        if is_impl_task:
            score_parts.append(1.0 if code_calls else 0.0)
        non_report_claimed = [
            p for p in files_created
            if isinstance(p, str)
            and "output-file" not in p
            and "CloudDocs" not in p
        ]
        if non_report_claimed:
            backed = len(non_report_claimed) - len(unverified_files)
            score_parts.append(backed / len(non_report_claimed))

        score = sum(score_parts) / len(score_parts) if score_parts else 1.0

        return score, hard_failures, warnings, {
            "code_tool_calls": len(code_calls),
            "write_tool_calls": len(write_calls),
            "actually_written": list(actually_written)[:10],
            "files_claimed": len(files_created),
            "unverified_files": unverified_files[:10],
        }

    # =========================================================================
    # CHECK 5: Runtime probes (soft / warning only)
    # =========================================================================

    def _check_runtime_probes(
        self,
        task_description: str,
        proposal: Any,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """
        Probe well-known local TCP ports for services mentioned in the task.

        Always soft — services may be external, containerised, or on other hosts.
        Uses a short 0.5 s timeout to avoid slowing down the pipeline.
        """
        combined = (
            task_description + " " +
            (getattr(proposal, "summary", "") or "")
        ).lower()

        probed: List[Tuple[str, int]] = []
        reachable: List[str] = []
        unreachable: List[str] = []
        warnings: List[str] = []

        for service, port in _SERVICE_PORT_MAP.items():
            if service not in combined:
                continue
            is_up = self._probe_port("127.0.0.1", port, timeout=0.5)
            probed.append((service, port))
            if is_up:
                reachable.append(service)
            else:
                unreachable.append(service)
                warnings.append(
                    f"Service '{service}' (localhost:{port}) is not reachable — "
                    "may be remote, containerised, or not yet started"
                )

        # Never penalise score for probe failures — always soft
        return 1.0, [], warnings, {
            "probed": [(s, p) for s, p in probed],
            "reachable": reachable,
            "unreachable": unreachable,
        }

    @staticmethod
    def _probe_port(host: str, port: int, timeout: float = 0.5) -> bool:
        """Return True if a TCP connection to host:port succeeds within timeout."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def _scan_files_for_imports(
        self, files_created: List[str]
    ) -> Dict[str, List[str]]:
        """
        Blind Spot 4: Scan Python files listed in files_created for actual
        `import` / `from X import` statements.

        Returns {top_level_module_name: [file_paths]} for every module
        imported in any of the created .py files.
        """
        found: Dict[str, List[str]] = {}
        for path in files_created:
            if not isinstance(path, str):
                continue
            full = path if os.path.isabs(path) else os.path.join(self.workspace_root, path)
            if not os.path.exists(full):
                continue
            if not full.endswith(".py"):
                continue
            try:
                with open(full, "r", errors="replace") as f:
                    content = f.read()
                # Match: `import X`, `import X.Y`, `from X import ...`, `from X.Y import ...`
                for m in re.finditer(
                    r'^(?:import|from)\s+([\w\.]+)', content, re.MULTILINE
                ):
                    top_mod = m.group(1).split(".")[0]
                    found.setdefault(top_mod, []).append(path)
            except Exception:
                pass
        return found
