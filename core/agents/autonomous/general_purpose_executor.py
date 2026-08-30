#!/usr/bin/env python3
"""
General Purpose Executor

Executes tasks by delegating to the teacher model (LLM via get_llm_service)
Formats task prompts, calls LLM, parses responses

COMPLETION PROTOCOL:
The LLM cannot mark tasks as complete. It can only PROPOSE completion.
The TaskCompletionValidator verifies proposals against formal criteria.
This prevents self-attestation and ensures externally verifiable completion.
"""

import asyncio
import logging
import uuid
import json
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from .shared_types import Task, TaskType, TaskStatus, TaskSource
from .completion_protocol import (
    CompletionState,
    TaskCompletionSpec,
    CompletionProposal,
    VerificationResult,
    TaskCompletionValidator,
    parse_completion_proposal,
    generate_task_spec,
    get_completion_validator
)
from core.execution.convergence_gate import get_convergence_gate, ConvergenceState
from core.execution.iteration_controller import get_iteration_controller, IterationDecision
from core.database import TorinUnifiedDatabase

# Performance profiling
from core.learning.performance_profiler import profile_performance

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Agent loop tunables
# ─────────────────────────────────────────────────────────────────────────────

# Maximum entries kept in the execution ledger (oldest pruned first).
# Ledger is re-injected after every compression event so causal history
# (which tools ran, what failed, why revisions were requested) is never
# lost to the 8B summary.
EXECUTION_LEDGER_MAX_ENTRIES: int = 50

# How many tool schemas to expose to the model in the initial tool set.
# Remaining discovered tools are held in reserve and can be requested via the
# request_tools meta-tool.  Keeps schema token overhead predictable while
# allowing the agent to reach any capability it actually needs.
MAX_INITIAL_TOOL_SCHEMAS: int = 20

# Minimum successful real-tool calls required before a propose_completion is
# eligible — keyed by TaskType.name.  The verifier is the true quality arbiter;
# this gate only blocks proposals made before the agent has done ANY observable
# work at all.
#
# Reasoning behind each value:
#   EXECUTION  — must have produced a side-effect AND run/tested the code
#   RESEARCH   — must read/search actual files before concluding anything;
#                2000+ file codebase requires genuine investigation
#   ANALYSIS   — must inspect data, not just reason from prior knowledge
#   SYNTHESIS  — aggregation needs at least a few retrievals as input
#   (default)  — unknown task type: require meaningful work as safe baseline
COMPLETION_GATE_BY_TYPE: Dict[str, int] = {
    "EXECUTION":           8,   # explore + read + grep + design + write + run + verify + confirm
    "RESEARCH":            4,   # must search, read multiple sources, synthesise, confirm
    "ANALYSIS":            4,   # inspect, measure, cross-reference, reason
    "SYNTHESIS":           4,   # retrieve from multiple places before synthesising
    "SECURITY_REMEDIATION": 3,  # read finding + write fix + verify
    "LEARNING":            2,   # lightweight knowledge tasks
}
COMPLETION_GATE_DEFAULT: int = 3

# ─────────────────────────────────────────────────────────────────────────────
# PROPOSE_COMPLETION_TOOL
#
# Replaces the old JSON-in-text completion blob.  The model calls this tool
# when it believes the task is done.  The schema mirrors the fields consumed by
# parse_completion_proposal() and the post-completion epistemic pipeline so the
# agent can express all relevant output in one structured call.
# ─────────────────────────────────────────────────────────────────────────────
PROPOSE_COMPLETION_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "propose_completion",
        "description": (
            "Propose that the current task is complete. "
            "PRECONDITION — this call will be IMMEDIATELY REJECTED if either of these is true:\n"
            "  1. You have not yet called `write_file` to create an output document on disk.\n"
            "  2. `files_created` is empty or the listed paths do not exist on disk.\n"
            "The verifier reads deliverables directly from disk. There is no other way to "
            "pass verification. Do NOT call this as a status update, a placeholder, or "
            "a signal that you 'would have' written something — call `write_file` first, "
            "then call this with the actual path in `files_created`.\n"
            "Additional rejection conditions: remaining_risks or open_questions are non-empty."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Detailed summary of what was accomplished.",
                },
                "outputs": {
                    "type": "object",
                    "description": "Structured key/value outputs or artifacts produced.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence that the task is complete, 0.0–1.0. Do not inflate.",
                },
                "remaining_risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any unresolved risks. Must be empty to pass verification.",
                },
                "open_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any unresolved questions. Must be empty to pass verification.",
                },
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Assumptions made during execution.",
                },
                "files_created": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "REQUIRED — full absolute paths to files you created with `write_file`. "
                        "For research/analysis/planning tasks: must be non-empty. "
                        "For code-change (EXECUTION) tasks: may be empty if `files_modified` "
                        "is non-empty (patch_file counts as a deliverable). "
                        "Do NOT leave both files_created and files_modified empty — "
                        "that is an immediate rejection. Example: "
                        '["~/Library/Mobile Documents/com~apple~CloudDocs/output-file/research/2026-04-19_1200_my-task.md"]'
                    ),
                },
                "files_modified": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Full absolute paths to files you modified with `patch_file`. "
                        "For EXECUTION tasks, list every file patched here."
                    ),
                },
                "key_findings": {
                    "type": "string",
                    "description": "Key findings, discoveries, or conclusions.",
                },
                "hypotheses": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Falsifiable claims discovered. Each: "
                        "{claim, domain, predictions: [], confidence}."
                    ),
                },
                "belief_updates": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Beliefs to create/update. Each: "
                        "{claim, domain, relation, confidence, evidence}. "
                        "relation: SUPPORTS|CONTRADICTS|IMPLIES|WEAKENS|REQUIRES."
                    ),
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Sources, files, modules, or references consulted. "
                        "List every file path, URL, or resource examined during this task."
                    ),
                },
            },
            "required": ["summary", "outputs", "files_created"],
        },
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC CONVERGENCE NUDGES
#
# Injected into conversation_history when the convergence gate fires.
# Content is tailored to task type + observed tool state so the model receives
# actionable guidance on *what it still needs to do*, not just "call propose_completion".
#
# nudge_num: 1 = first prompt (what to do next), 2 = escalation (firmer),
#            3 = final warning (last chance before forced exit)
# ─────────────────────────────────────────────────────────────────────────────

_PROPOSE_FOOTER = (
    "\n\n⚡ TOKEN DISCIPLINE: Do NOT write any analysis, reasoning, or explanation "
    "text before the tool call. Your ENTIRE response must be ONLY the "
    "propose_completion tool call JSON — zero preceding text. "
    "If you write reasoning text first you will run out of tokens before finishing "
    "the JSON and the proposal will be empty and rejected."
)


def _build_convergence_nudge(
    task_type_name: str,
    nudge_num: int,
    tool_results: list,
) -> str:
    """
    Return a task-type-aware convergence nudge string.

    Analyses which tools have fired successfully so the message focuses on
    what is *missing*, not on things already done.

    All return paths append _PROPOSE_FOOTER which explicitly instructs the model
    to emit the tool call with zero preceding text (prevents JSON truncation).
    """
    return _build_convergence_nudge_body(task_type_name, nudge_num, tool_results) + _PROPOSE_FOOTER


def _build_convergence_nudge_body(
    task_type_name: str,
    nudge_num: int,
    tool_results: list,
) -> str:
    """Inner body — returns nudge text without the propose footer."""

    # ── Shared state signals ────────────────────────────────────────────────
    _success = lambda t: any(
        r.get("tool") == t and r.get("success") for r in tool_results
    )
    _any_success = lambda ts: any(
        r.get("tool") in ts and r.get("success") for r in tool_results
    )

    _WEB_TOOLS      = {"web_search", "fetch_page", "http_request", "conduct_research"}
    _READ_TOOLS     = {"read_file", "grep_search", "list_directory", "analyze_code", "search_code"}
    _WRITE_TOOLS    = {"write_file", "atomic_write_file", "patch_file"}
    _EXEC_TOOLS     = {"run_python", "run_shell_command", "execute_command", "run_script"}
    _TEST_TOOLS     = {"run_python", "run_tests", "run_shell_command", "pytest"}
    _SCAN_TOOLS     = {"security_scan", "vulnerability_scan", "run_bandit", "semgrep"}
    _MEASURE_TOOLS  = {"run_python", "run_benchmark", "profile_code", "run_shell_command"}

    _did_web        = _any_success(_WEB_TOOLS)
    _did_read       = _any_success(_READ_TOOLS)
    _did_write      = _any_success(_WRITE_TOOLS)
    _did_exec       = _any_success(_EXEC_TOOLS)
    _did_test       = _any_success(_TEST_TOOLS)
    _did_scan       = _any_success(_SCAN_TOOLS)
    _did_measure    = _any_success(_MEASURE_TOOLS)
    _write_count    = sum(1 for r in tool_results if r.get("tool") in _WRITE_TOOLS and r.get("success"))
    _exec_failed    = any(r.get("tool") in _EXEC_TOOLS and not r.get("success") for r in tool_results)
    _exec_passed    = any(r.get("tool") in _EXEC_TOOLS and r.get("success") for r in tool_results)
    _test_passed    = any(
        r.get("tool") in _TEST_TOOLS and r.get("success")
        and any(sig in str(r.get("output", "")).lower()
                for sig in ["passed", "0 failed", " ok", "test session ends", "success"])
        for r in tool_results
    )
    _icloud_write   = any(
        r.get("tool") in _WRITE_TOOLS and r.get("success")
        and "CloudDocs" in str(r.get("output", "") or
                               (r.get("parameters") or r.get("params") or {}).get("file_path", ""))
        for r in tool_results
    )

    tn = task_type_name.upper()

    # ── EXECUTION / SELF_IMPROVEMENT ────────────────────────────────────────
    if tn in ("EXECUTION", "SELF_IMPROVEMENT"):
        if nudge_num == 1:
            missing = []
            if not _did_write:
                missing.append("❌ No code written/patched yet — apply your change with write_file or patch_file")
            elif _did_write and not _did_exec:
                missing.append("❌ Change applied but NOT verified — run a syntax/import check with run_python")
            elif _did_exec and not _test_passed:
                missing.append("❌ Execution ran but tests have not passed — fix errors and re-run")
            if missing:
                steps = "\n".join(missing)
                return (
                    f"⚙️ EXECUTION CHECKLIST — complete these before propose_completion:\n{steps}\n\n"
                    "Required sequence:\n"
                    "  1. patch_file / write_file — apply the change\n"
                    "  2. run_python(code=\"import ast; ast.parse(open('<path>').read()); print('SYNTAX OK')\") — syntax check\n"
                    "  3. run_python(code=\"import importlib; importlib.import_module('<dotted.path>'); print('IMPORT OK')\") — import check\n"
                    "  4. Run your tests — pytest, run_python, or run_shell_command as appropriate\n"
                    "  5. Only call propose_completion when ALL checks pass.\n"
                    "Complete the missing steps NOW."
                )
            else:
                return (
                    "✅ Code change applied and verified. Call propose_completion now.\n"
                    "Include in outputs: files_created/files_modified paths, test results summary."
                )
        elif nudge_num == 2:
            if _did_write and not _test_passed:
                return (
                    "⚠️ Change is written but verification is incomplete.\n"
                    "You MUST run tests before proposing completion:\n"
                    "  run_python(code=\"import ast; ast.parse(open('<patched_file>').read()); print('SYNTAX OK')\")\n"
                    "  Then run your actual test suite.\n"
                    "Fix any failures, then call propose_completion."
                )
            return (
                "⚠️ ESCALATION: All required steps should be complete.\n"
                "If tests are passing → call propose_completion NOW.\n"
                "If tests are still failing → fix the specific error, re-run, then propose."
            )
        else:  # nudge 3
            return (
                "🛑 FINAL WARNING: Call propose_completion immediately.\n"
                "If code is working → propose now.\n"
                "If code is broken → propose with the partial result and document what failed in remaining_risks."
            )

    # ── RESEARCH ────────────────────────────────────────────────────────────
    elif tn == "RESEARCH":
        if nudge_num == 1:
            missing = []
            if not _did_web:
                missing.append("❌ No web search performed — use web_search or fetch_page to gather current information")
            if not _did_read and not _did_web:
                missing.append("❌ No sources consulted — search the web or read relevant files")
            if not _icloud_write:
                missing.append("❌ No output document written — write your findings to the iCloud research folder")
            if missing:
                steps = "\n".join(missing)
                return (
                    f"🔬 RESEARCH CHECKLIST — complete these before propose_completion:\n{steps}\n\n"
                    "Required sequence:\n"
                    "  1. web_search — search for current, authoritative information (use multiple queries)\n"
                    "  2. fetch_page — retrieve full content from the most relevant sources\n"
                    "  3. Synthesise findings — connect sources, identify gaps, form conclusions\n"
                    "  4. write_file — save a structured report to iCloud (research/ sub-directory)\n"
                    "     Format: /Users/stefan/Library/Mobile Documents/com~apple~CloudDocs/output-file/research/YYYY-MM-DD_HHMM_<slug>.md\n"
                    "  5. propose_completion with sources_consulted populated\n"
                    "Complete the missing steps NOW."
                )
            return (
                "✅ Research complete and document written. Call propose_completion now.\n"
                "Populate sources_consulted with the URLs/queries you used."
            )
        elif nudge_num == 2:
            if not _did_web:
                return (
                    "⚠️ ESCALATION: You have NOT searched the web yet.\n"
                    "Call web_search RIGHT NOW with a specific query relevant to the task.\n"
                    "Then fetch_page on the top results, then write_file, then propose_completion."
                )
            if not _icloud_write:
                return (
                    "⚠️ ESCALATION: Research done but no document written.\n"
                    "Call write_file NOW to save your findings:\n"
                    "  file_path: /Users/stefan/Library/Mobile Documents/com~apple~CloudDocs/output-file/research/YYYY-MM-DD_HHMM_<slug>.md\n"
                    "Then call propose_completion."
                )
            return (
                "⚠️ ESCALATION: Call propose_completion immediately with your research summary and sources_consulted."
            )
        else:  # nudge 3
            return (
                "🛑 FINAL WARNING: Write any remaining findings and call propose_completion NOW.\n"
                "If document not yet written — write it immediately then propose.\n"
                "Do not make any more search calls."
            )

    # ── ANALYSIS ────────────────────────────────────────────────────────────
    elif tn == "ANALYSIS":
        if nudge_num == 1:
            missing = []
            if not _did_read:
                missing.append("❌ No files inspected — use read_file, grep_search, or analyze_code on the target data")
            if not _did_exec and not _did_measure:
                missing.append("❌ No measurements taken — run metrics, counts, or statistical checks via run_python")
            if missing:
                steps = "\n".join(missing)
                return (
                    f"📊 ANALYSIS CHECKLIST — complete these before propose_completion:\n{steps}\n\n"
                    "Required sequence:\n"
                    "  1. read_file / grep_search — inspect actual data and code\n"
                    "  2. run_python — compute metrics, counts, or cross-reference findings\n"
                    "  3. Cross-reference at least 2 data points before drawing conclusions\n"
                    "  4. write_file — document findings with specific numbers (not vague estimates)\n"
                    "  5. propose_completion with key_findings populated\n"
                    "Complete the missing steps NOW."
                )
            return (
                "✅ Data inspected and measurements taken. Call propose_completion now.\n"
                "Include specific numbers and file references in key_findings."
            )
        elif nudge_num == 2:
            if not _did_read:
                return (
                    "⚠️ ESCALATION: You have NOT inspected any actual files.\n"
                    "Call read_file or grep_search on the relevant data source NOW.\n"
                    "Analysis without reading files is not analysis — it is speculation."
                )
            return (
                "⚠️ ESCALATION: Inspection done. Document your findings with specific numbers and call propose_completion."
            )
        else:
            return (
                "🛑 FINAL WARNING: Call propose_completion immediately with your analysis findings.\n"
                "Include concrete measurements — not vague statements."
            )

    # ── OPTIMIZATION ────────────────────────────────────────────────────────
    elif tn == "OPTIMIZATION":
        if nudge_num == 1:
            missing = []
            if not _did_measure:
                missing.append("❌ No baseline measurement — run a benchmark or timing test BEFORE optimizing")
            elif _did_write and not _did_measure:
                missing.append("❌ Change applied but no post-optimization measurement to confirm improvement")
            if missing:
                steps = "\n".join(missing)
                return (
                    f"⚡ OPTIMIZATION CHECKLIST:\n{steps}\n\n"
                    "Required sequence:\n"
                    "  1. Measure baseline — run_python with timing/profiling BEFORE changes\n"
                    "  2. Apply optimization — write_file or patch_file\n"
                    "  3. Measure after — run the same benchmark again\n"
                    "  4. Compute delta — show improvement (%, ms, etc.)\n"
                    "  5. propose_completion with before/after numbers in outputs\n"
                    "Do the missing steps NOW."
                )
            return (
                "✅ Baseline and post-optimization measurements taken. Call propose_completion with the delta."
            )
        elif nudge_num == 2:
            return (
                "⚠️ ESCALATION: You must have before AND after measurements.\n"
                "If missing — run the benchmark now. Then propose_completion with the improvement delta."
            )
        else:
            return (
                "🛑 FINAL WARNING: Call propose_completion now. Include whatever measurements you have."
            )

    # ── VALIDATION ────────────────────────────────────────────────────────
    elif tn == "VALIDATION":
        if nudge_num == 1:
            if not _did_test:
                return (
                    "✅ VALIDATION CHECKLIST:\n"
                    "❌ No tests run yet — you MUST execute tests before proposing completion.\n\n"
                    "Required steps:\n"
                    "  1. run_python / run_shell_command — execute the test suite\n"
                    "  2. Capture exact pass/fail counts\n"
                    "  3. For any failures: read the error, identify root cause\n"
                    "  4. propose_completion with test results in outputs (passed_count, failed_count, details)\n"
                    "Run the tests NOW."
                )
            if _did_test and not _test_passed:
                return (
                    "⚠️ Tests ran but failures detected. Do NOT propose completion with failing tests.\n"
                    "Fix the failures, re-run, and only propose when all pass (or document which are known-failing)."
                )
            return (
                "✅ Tests executed and passing. Call propose_completion with the test results in outputs."
            )
        elif nudge_num == 2:
            return (
                "⚠️ ESCALATION: Run your tests NOW if not done. Then call propose_completion with pass/fail results."
            )
        else:
            return "🛑 FINAL WARNING: Call propose_completion with whatever test results you have."

    # ── SECURITY_REMEDIATION ────────────────────────────────────────────────
    elif tn == "SECURITY_REMEDIATION":
        if nudge_num == 1:
            missing = []
            if not _did_scan and not _did_read:
                missing.append("❌ No vulnerability scan or file inspection performed")
            if not _did_write:
                missing.append("❌ No fix applied — patch the vulnerable code")
            if _did_write and not _did_exec:
                missing.append("❌ Fix applied but not verified — run a test or scan to confirm closure")
            if missing:
                steps = "\n".join(missing)
                return (
                    f"🔒 SECURITY REMEDIATION CHECKLIST:\n{steps}\n\n"
                    "Required sequence:\n"
                    "  1. Identify the specific vulnerability (CVE, file path, line number)\n"
                    "  2. Read the vulnerable code with read_file\n"
                    "  3. Apply the fix with patch_file or write_file\n"
                    "  4. Verify the fix: run_python syntax check, import check, or security_scan\n"
                    "  5. propose_completion documenting the vulnerability and the fix applied\n"
                    "Complete missing steps NOW."
                )
            return (
                "✅ Vulnerability identified, fixed, and verified. Call propose_completion with CVE/finding details."
            )
        elif nudge_num == 2:
            return (
                "⚠️ ESCALATION: Fix must be applied AND verified before completion.\n"
                "Run a verification check NOW. Then propose_completion."
            )
        else:
            return "🛑 FINAL WARNING: Call propose_completion now with the remediation summary."

    # ── PLANNING / SYNTHESIS ────────────────────────────────────────────────
    elif tn in ("PLANNING", "SYNTHESIS"):
        if nudge_num == 1:
            missing = []
            if not _did_read and not _did_web:
                missing.append("❌ No information gathered — read relevant files or search for context")
            if not _icloud_write:
                missing.append("❌ No plan document written — write your structured plan to iCloud")
            if missing:
                steps = "\n".join(missing)
                return (
                    f"📋 PLANNING CHECKLIST:\n{steps}\n\n"
                    "Required sequence:\n"
                    "  1. Gather context — read relevant files or search for constraints/requirements\n"
                    "  2. Structure the plan — concrete milestones, dates, owners, dependencies, risks\n"
                    "  3. write_file — save to iCloud planning/ sub-directory\n"
                    "  4. propose_completion with the plan summary\n"
                    "Complete missing steps NOW."
                )
            return (
                "✅ Context gathered and plan written. Call propose_completion with the plan summary."
            )
        elif nudge_num == 2:
            return (
                "⚠️ ESCALATION: Write your plan to iCloud NOW if not done. Then propose_completion."
            )
        else:
            return "🛑 FINAL WARNING: Call propose_completion with your plan now."

    # ── LEARNING ────────────────────────────────────────────────────────────
    elif tn == "LEARNING":
        if nudge_num == 1:
            return (
                "📚 LEARNING TASK — wrap-up:\n"
                "Summarise what you learned and call propose_completion.\n"
                "Populate key_findings with the core concepts discovered.\n"
                "If you found references worth storing, include them in sources_consulted."
            )
        elif nudge_num == 2:
            return "⚠️ Call propose_completion NOW with your learning summary."
        else:
            return "🛑 FINAL WARNING: Emit propose_completion immediately."

    # ── DEFAULT (unknown task type) ─────────────────────────────────────────
    else:
        if nudge_num == 1:
            missing = []
            if not _did_read and not _did_web:
                missing.append("❌ No information gathered yet")
            if not _did_write:
                missing.append("❌ No output produced yet")
            if missing:
                steps = "\n".join(missing)
                return (
                    f"TASK CHECKLIST:\n{steps}\n\n"
                    "Gather the necessary information, produce your output, then call propose_completion."
                )
            return (
                "✅ Work complete. Call propose_completion with your summary and key_findings."
            )
        elif nudge_num == 2:
            return (
                "⚠️ ESCALATION: Complete remaining work and call propose_completion NOW."
            )
        else:
            return "🛑 FINAL WARNING: Call propose_completion immediately."


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST_TOOLS_TOOL
#
# Meta-tool that lets the agent ask for tools beyond the initial schema set.
# The agent loop handles this call internally (never reaches the tool registry)
# by searching the reserved pool and injecting matching schemas into tool_schemas.
# This lets us expose a small, low-noise initial set while preserving full
# capability access.
# ─────────────────────────────────────────────────────────────────────────────
REQUEST_TOOLS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "request_tools",
        "description": (
            "Request additional tools that are not in your current tool set. "
            "Use this when you need a capability you don't currently have access to. "
            "Returns the names of newly available tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "capability": {
                    "type": "string",
                    "description": (
                        "The capability you need, e.g. 'database query', "
                        "'http request', 'file parsing', 'code execution'."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Why you need this capability (helps the system find the best tools).",
                },
            },
            "required": ["capability"],
        },
    },
}



def make_tool_record(
    tool: str,
    parameters: dict,
    success: bool,
    output_display: Any,
    observation: Optional[list] = None,
) -> dict:
    """The ONE constructor for a tool_results entry.

    There were two: the main path stored `str(result.output)[:4000]` and the
    pre-completion path stored the raw dict, under the same "output" key. Three
    downstream sites branch on isinstance(output, dict), so their behaviour
    depended on which code path produced the record rather than on what
    happened in the world. Adding `observation` to both paths independently
    would have fixed the semantic split while preserving the structural one.

    FIELD SEMANTICS -- authoritative:
        success      : did the INVOCATION execute?
        observation  : what the result ESTABLISHES about the world (canonical)
        output       : presentation / legacy compatibility ONLY.
                       No new cognitive code may infer semantics from it.
    """
    return {
        "tool": tool,
        "parameters": parameters,
        "success": success,
        "output": output_display,
        "observation": observation or [],
        "observation_schema_version": 1,
    }


class GeneralPurposeExecutor:
    """
    General Purpose Task Executor

    Executes tasks by delegating intelligence to the teacher model
    Supports multiple task types: RESEARCH, ANALYSIS, SYNTHESIS, EXECUTION, etc.

    Architecture:
    - Lightweight coordinator (formats, delegates, parses)
    - Delegates ALL intelligence to LLM via get_llm_service()
    - Returns structured results
    """

    def __init__(self, torin_brain=None, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        # Runtime config helpers
        self._env_loaded: bool = False
        #: Values read from .env, kept HERE rather than pushed into os.environ.
        self._dotenv_values: Optional[Dict[str, str]] = None

        # Database for persistence
        self.db = TorinUnifiedDatabase()

        # LLM service (the teacher model) - can be provided or fetched
        self.llm = torin_brain

        # Neural bridge for reasoning capture

        # Context manager for conversation compression and token management
        self.context_manager = None

        # Memory agent - single entry/exit point for all memory operations
        self.memory_agent = None

        # Tool registry - access to all 300+ tools
        self.tool_registry = None

        # Convergence gate - Phase 1: Hard Convergence Core
        self.convergence_gate = None

        # Iteration controller - Phase 2: Uncertainty & Temporal Layer
        self.iteration_controller = None

        # Reward system components — lazy-initialized on first task completion.
        # ExperienceEvaluator computes all 4 normalized metrics (outcome_quality,
        # intrinsic_reward, constitutional_alignment, system_health_impact).
        # IntrinsicMotivationSystem applies per-tool cooldowns + diversity penalties.
        self.experience_evaluator = None
        self._intrinsic_motivation = None

        # Execution stats
        self.stats = {
            'tasks_executed': 0,
            'tasks_successful': 0,
            'tasks_failed': 0,
            'by_type': {}
        }

    def _ensure_dotenv_loaded(self) -> None:
        """Read TorinAI's .env files for runtime integration checks, WITHOUT
        mutating the process environment.

        This previously called load_dotenv(), which writes every key in
        .env.production into os.environ for the life of the process. Two things
        followed. An operator who unset SLACK_BOT_TOKEN to disable Slack had it
        put back by the first integration check, so the executor's answer to
        "is Slack configured" could not be influenced by the environment it was
        actually running in. And the write was global: every other component
        thereafter saw variables that were never in the environment, attributed
        to nobody.

        Same failure as the POSTGRES_* one, same remedy: read the file into a
        dict and resolve with explicit precedence, so the file informs the
        answer instead of silently becoming the environment.
        """
        if self._env_loaded:
            return
        self._env_loaded = True

        try:
            from pathlib import Path
            from dotenv import dotenv_values

            base = Path(__file__).resolve()
            # Walk up until we find TorinAI root (has core/)
            for _ in range(6):
                if (base / "core").is_dir():
                    break
                base = base.parent

            env_prod = base / ".env.production"
            env_fallback = base / ".env"
            if env_prod.exists():
                self._dotenv_values = dict(dotenv_values(env_prod))
            elif env_fallback.exists():
                self._dotenv_values = dict(dotenv_values(env_fallback))
        except Exception:
            # Dotenv is optional; if missing, runtime checks fall back to os.environ
            return

    def _config_value(self, key: str) -> Optional[str]:
        """Resolve one setting: process environment first, then the .env file.

        A variable present in the environment wins, including when a launcher
        set it deliberately. One that is absent falls back to the file. Nothing
        here writes to os.environ, so asking a question never changes the
        answer for whoever asks next.
        """
        import os
        value = os.environ.get(key)
        if value is not None:
            return value
        self._ensure_dotenv_loaded()
        return (self._dotenv_values or {}).get(key)

    def _get_runtime_integration_status(self) -> Dict[str, Any]:
        """Return a small, secret-free snapshot of integration availability."""
        slack_bot_token_configured = bool(self._config_value("SLACK_BOT_TOKEN"))
        slack_webhook_vars = (
            "SLACK_WEBHOOK_URL",
            "SLACK_WEBHOOK_TORIN_UPGRADES",
            "SLACK_WEBHOOK_TORIN_ALERTS",
            "SLACK_WEBHOOK_TORIN_DECISIONS",
            "SLACK_WEBHOOK_TORIN_ACTIVITY",
            "SLACK_WEBHOOK_CRITICAL",
        )
        slack_webhook_configured = any(bool(self._config_value(k)) for k in slack_webhook_vars)

        return {
            "slack_bot_token_configured": slack_bot_token_configured,
            "slack_webhook_configured": slack_webhook_configured,
            "slack_any_configured": slack_bot_token_configured or slack_webhook_configured,
        }

    def _filter_tools_by_runtime_config(
        self,
        tools: Dict[str, Any],
        *,
        integration_status: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Filter tools that will deterministically fail due to missing config."""

        status = integration_status or self._get_runtime_integration_status()

        slack_any = bool(status.get("slack_any_configured"))
        slack_bot = bool(status.get("slack_bot_token_configured"))
        slack_webhook = bool(status.get("slack_webhook_configured"))

        if slack_any and slack_bot:
            return tools

        filtered: Dict[str, Any] = {}
        removed: List[str] = []

        # Slack tools can be exposed even when Slack is not configured.
        # Avoid wasting iterations on known failures.
        slack_webhook_only_allow = {
            "send_slack_message",
            "ask_for_clarification",
            "report_security_finding",
            "notify_dominion_labs_team",
        }
        slack_bot_required_names = {
            "get_slack_users",
            "get_slack_channels",
            "search_slack_messages",
            "post_slack_message",
            "get_user_presence",
        }

        for tool_name, tool in tools.items():
            lower = tool_name.lower()
            is_slackish = ("slack" in lower) or (tool_name in slack_webhook_only_allow)

            if not slack_any and is_slackish:
                removed.append(tool_name)
                continue

            if slack_any and not slack_bot:
                # Webhook-only setup: allow webhook-based notification tools,
                # but drop API tools that require a bot token.
                if tool_name in slack_bot_required_names or tool_name.startswith("get_slack_"):
                    removed.append(tool_name)
                    continue
                if tool_name in slack_webhook_only_allow and not slack_webhook:
                    removed.append(tool_name)
                    continue

            filtered[tool_name] = tool

        if removed:
            logger.info(
                "[TOOL FILTER] Removed %s Slack tool(s) due to missing config (%s)",
                len(removed),
                ",".join(sorted(removed))[:500],
            )

        return filtered

    def _build_preflight_context(self, task: Task, *, integration_status: Dict[str, Any]) -> str:
        """Build a concise preflight block to ground the model."""
        slack_any = bool(integration_status.get("slack_any_configured"))
        slack_bot = bool(integration_status.get("slack_bot_token_configured"))
        slack_webhook = bool(integration_status.get("slack_webhook_configured"))

        lines: List[str] = [
            "RUNTIME_PREFLIGHT:",
            f"  task_source: {getattr(task.source, 'value', task.source)}",
            f"  task_type: {task.type.name}",
            f"  slack_configured: {slack_any}",
            f"  slack_bot_token_configured: {slack_bot}",
            f"  slack_webhook_configured: {slack_webhook}",
        ]

        if not slack_any:
            lines.append("  note: Slack tools are unavailable; do not call Slack tools.")
        elif slack_any and not slack_bot:
            lines.append("  note: Slack bot token missing; do not call Slack API tools (search/get/post).")

        if task.max_time_seconds:
            lines.append(f"  budget_max_time_seconds: {task.max_time_seconds}")

        return "\n".join(lines)

    def _min_successful_tool_calls_for_task(self, task: Task) -> int:
        return COMPLETION_GATE_BY_TYPE.get(task.type.name, COMPLETION_GATE_DEFAULT)

    async def initialize(self) -> bool:
        """Initialize the executor and connect to the teacher model"""
        try:
            logger.info("Initializing general purpose executor...")

            # Connect to the teacher model (LLM service) if not provided
            if not self.llm:
                from core.services.unified_llm import get_llm_service
                logger.info("Connecting to the teacher model (LLM service)...")
                self.llm = get_llm_service()

            if not self.llm:
                logger.error("Failed to connect to LLM service")
                return False

            # Ensure the model is actually loaded (singleton may have been shut down
            # by a previous suite — e.g. llm/roundtrip suites call shutdown() before
            # the task suite runs; get_llm_service returns the same instance but
            # model_loaded=False, so every generate_with_messages call errors out).
            if not getattr(self.llm, "model_loaded", False):
                logger.info("LLM singleton not yet loaded — calling initialize()...")
                if not await self.llm.initialize():
                    logger.error("LLM initialize() failed — cannot execute tasks")
                    return False

            logger.info("Successfully connected to the teacher model")

            # NEURAL BRIDGE INITIALISATION REMOVED 2026-08-24.
            #
            # This constructed the bridge, initialised it, and logged
            # "reasoning traces will be automatically captured". Nothing here
            # ever called it: `self.neural_bridge` appeared only in its own
            # assignments. No trace was captured by this path, and the log said
            # otherwise on every start.
            #
            # The executor EXECUTES. Reasoning is entered through the bridge by
            # callers that reason; a component that holds a reference it never
            # uses is claiming a connection it does not have.
            #
            # Traces from real reasoning are captured where reasoning happens --
            # the bridge records its own results, verified landing in the memory
            # store with the kind of thinking tagged.

            # Initialize context manager for conversation compression
            try:
                from core.reasoning.context_manager import get_context_manager
                from core.reasoning.context_compression import get_context_compression
                from core.memory import get_memory_agent

                logger.info("Initializing context manager...")
                compression = get_context_compression()
                self.memory_agent = await get_memory_agent()  # FIXED: await the coroutine
                await self.memory_agent.initialize()

                # Pull the ACTUAL context window from the VLM rather than hardcoding.
                # The VLM is loaded with n_ctx=21000 (hybrid CPU+GPU mode) but this
                # was previously hardcoded to 15360, wasting ~6K tokens of capacity.
                actual_n_ctx = getattr(self.llm, 'n_ctx', 21000)

                self.context_manager = get_context_manager(
                    compression_service=compression,
                    memory_agent=self.memory_agent,
                    n_ctx=actual_n_ctx,  # Use VLM's actual context window
                    compression_interval=5,  # Not used anymore - compression is token-based
                    preserve_recent=3,  # Keep last 3 messages for continuity
                    safety_margin=100
                )
                logger.info("✓ Context manager initialized - automatic compression enabled")
                logger.info("✓ Memory agent initialized - automatic deduplication enabled")
            except Exception as e:
                logger.error(f"Context manager initialization FAILED: {e}")
                import traceback
                traceback.print_exc()
                self.context_manager = None

            # Initialize completion validator for verifiable completion.
            # NO LLM critic: completion is verified by deterministic reality checks
            # (artifacts on disk, code-execution evidence, tests, dependency graph,
            # score threshold). The LLM critic was retired 2026-08-28 — it added only
            # optional semantic gates that defaulted to neutral when absent, and the
            # deterministic reality checks caught fabricated completions on their own
            # (verified: a claimed-but-missing artifact is rejected with the critic off).
            try:
                self.completion_validator = get_completion_validator()
                await self.completion_validator.initialize()
                logger.info("✓ Completion validator initialized - self-attestation disabled")
            except Exception as e:
                logger.error(f"Completion validator initialization failed: {e}")
                self.completion_validator = None

            # Initialize convergence gate (Phase 1: Hard Convergence Core)
            try:
                self.convergence_gate = get_convergence_gate()
                logger.info("✓ Convergence gate initialized - formal convergence verification enabled")
            except Exception as e:
                logger.error(f"Convergence gate initialization failed: {e}")
                self.convergence_gate = None

            # Initialize iteration controller (Phase 2: Uncertainty & Temporal Layer)
            try:
                self.iteration_controller = get_iteration_controller()
                logger.info("✓ Iteration controller initialized - Bayesian iteration budgets enabled")
            except Exception as e:
                logger.error(f"Iteration controller initialization failed: {e}")
                self.iteration_controller = None

            # Get tool registry FIRST (before database - it doesn't depend on DB)
            from core.tools.tool_registry import get_tool_registry
            self.tool_registry = get_tool_registry()
            # Count both lazy-loaded (factories) and eager-loaded (tools) tools
            tool_count = len(self.tool_registry.tool_factories) + len(self.tool_registry.tools)
            logger.info(f"Connected to tool registry: {tool_count} tools available ({len(self.tool_registry.tool_factories)} lazy + {len(self.tool_registry.tools)} eager)")

            # Initialize database (don't let this block tool registry)
            # Shadow mode: skip DB — task execution doesn't need persistent storage.
            import os as _gpe_os
            if _gpe_os.environ.get("TORIN_SHADOW_MODE"):
                logger.info("⚡ Shadow mode: database init suppressed (TORIN_SHADOW_MODE=1)")
            else:
                try:
                    await self.db.initialize()
                    # Restore epistemic beliefs from PostgreSQL so the convergence gate
                    # has historical context from previous runs.
                    try:
                        from core.reasoning.epistemic_engine import get_epistemic_engine
                        await get_epistemic_engine()._uncertainty().load_from_db()
                        logger.info("✓ Epistemic engine: beliefs loaded from PostgreSQL")
                    except Exception as _ep_e:
                        logger.warning(f"Epistemic belief load non-fatal: {_ep_e}")
                except Exception as e:
                    logger.warning(f"Database initialization failed (non-critical): {e}")

            self.active = True
            logger.info("General purpose executor ready")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize executor: {e}")
            return False

    # ==================================================================
    # SUBSTRATE-FIRST DRIVE — Phase 1: goal derivation + world observation
    #
    # Before the substrate can plan a task it needs two things the model used
    # to supply implicitly: the state that would make the task done, and the
    # state the world is in now. Neither is invented here. The goal is read
    # from what the task carries; the world is OBSERVED through the domain's
    # bindings, never assumed. When the task carries no state semantics the
    # substrate does not guess one -- it declines, and the decision to fall
    # back to anything else is made above this method, not inside it.
    # ==================================================================

    def _observe_world(self, domain_id: str) -> Optional[List[str]]:
        """The world the substrate will plan against, read now from the domain.

        Returns the observed facts as strings, or None when the world cannot be
        read -- which is not the same as an empty world. Planning against a
        world that was never observed would authorise a plan on a state that
        does not exist, so an unreadable world stops the substrate path here
        rather than letting it proceed on an assumption.
        """
        from core.execution.operator_binding import get_binding_registry

        observed = get_binding_registry().observe_world(domain_id)
        if observed is None:
            return None
        return sorted(str(fact) for fact in observed)

    def _derive_goal_spec(self, task: Task) -> Optional[Dict[str, Any]]:
        """Turn a task into a state goal the planner can search, or decline.

        A state goal is (domain, goal_conditions, observed world). The goal
        conditions come from what the task declares -- its provenance for a task
        authored as a state goal, nothing read out of prose. The world is
        observed, not carried: a `world_state` recorded when the task was
        created is planning-time state, and the state that governs execution is
        the one observed now.

        Returns None, honestly, when the task carries no state goal or its world
        cannot be read. A None here is the substrate saying "not mine yet"; it
        never becomes a guessed goal.
        """
        provenance = getattr(task, "provenance", None) or {}

        # A task already carrying a grounded operator is a plan STEP, not a
        # goal to plan -- that is _try_substrate_execution's work, not this.
        if provenance.get("grounded_operator"):
            return None

        raw_conditions = provenance.get("goal_conditions")
        domain_id = provenance.get("domain_id")
        if not raw_conditions or not domain_id:
            return None

        # The conditions must parse as facts, or they are not a state goal the
        # search can reason over. A malformed condition declines the whole task
        # rather than silently dropping the part that failed.
        from core.learning.rule_induction import Fact

        goal_conditions: List[str] = []
        for condition in raw_conditions:
            try:
                goal_conditions.append(str(Fact.parse(str(condition))))
            except ValueError as exc:
                logger.info("goal derivation declined task %s: condition %r does "
                            "not parse: %s", task.id, condition, exc)
                return None

        world_state = self._observe_world(domain_id)
        if world_state is None:
            logger.info("goal derivation declined task %s: the world of domain "
                        "%r could not be observed", task.id, domain_id)
            return None

        return {
            "domain_id": domain_id,
            "goal_conditions": goal_conditions,
            "world_state": world_state,
        }

    # ==================================================================
    # SUBSTRATE-FIRST DRIVE — Phase 2: plan a state goal and execute it
    #
    # Where _try_substrate_execution runs one already-grounded operator, this
    # takes a task that names a STATE to reach, plans a sequence of learned
    # operators to reach it, and drives that sequence through the same verified
    # single-operator path. The substrate decides the steps; no model is asked
    # what to do. When the goal cannot be planned it says so -- UNREACHABLE or
    # INDETERMINATE -- and does not fall to generation.
    # ==================================================================

    async def _get_planning_engine(self):
        """The substrate's planner, created once and kept.

        Planning a state goal is the substrate choosing a sequence of its own
        learned operators. One engine is held so the goals and plans it creates
        persist across the tasks the executor drives, rather than a fresh engine
        forgetting them each call.
        """
        engine = getattr(self, "_planning_engine", None)
        if engine is None:
            from core.agents.autonomous.planning_engine import PlanningEngine
            engine = PlanningEngine(self.config)
            if not await engine.initialize():
                logger.error("planning engine failed to initialize; the "
                             "substrate cannot plan state goals")
                return None
            self._planning_engine = engine
        return engine

    async def _drive_substrate_goal(self, task: Task) -> Optional[Dict[str, Any]]:
        """Plan a state goal over learned operators and execute it, model-free.

        Returns None to decline -- the task names no state goal, or the planner
        is unavailable -- leaving what comes next to the caller. Otherwise the
        substrate owns the goal and the result says what happened: it reached
        the goal, proved it unreachable, or stopped at the step that diverged.

        The world is re-observed for authorization by each step (inside
        _try_substrate_execution) and once more at the end to decide success.
        A plan that ran cleanly while the world did not reach the goal is not a
        success -- the world decides, not the plan's account of itself.
        """
        spec = self._derive_goal_spec(task)
        if spec is None:
            return None

        engine = await self._get_planning_engine()
        if engine is None:
            return None

        from core.reasoning.temporal_reasoning import PlanningStatus

        domain_id = spec["domain_id"]
        goal = await engine.create_goal(
            f"[substrate goal] {task.description}"[:200], task.priority,
            state_conditions=spec["goal_conditions"])
        if goal is None:
            return None

        outcome = await engine.plan_for_goal(
            goal.id, {"world_state": spec["world_state"], "domain_id": domain_id})

        if outcome.status is not PlanningStatus.PLAN_FOUND:
            # Honest inability. UNREACHABLE is a proof about the world;
            # INDETERMINATE is Torin not (yet) knowing enough of its own
            # repertoire. Neither is a reason to ask a model to guess -- but the
            # substrate can go further than "I cannot": the domain authority
            # diagnoses WHAT kind of knowledge is missing (operator, concept,
            # causal link, binding, prerequisite, observation, or none learnable).
            # The diagnosis is a MEASUREMENT, not a decision: it feeds the
            # AppraisalSystem, which owns the disposition (explore / replan /
            # disengage). Until now a planning failure fed appraisal nothing, so
            # the substrate's own inability never reached its disposition.
            from core.integration.universal_domain_master import get_universal_domain_master

            deficit = await get_universal_domain_master().diagnose_deficit(
                domain_id, spec["goal_conditions"], spec["world_state"], outcome)
            try:
                from core.agents.autonomous.appraisal import get_appraisal_system
                get_appraisal_system().update(
                    outcome_quality=0.0,
                    self_initiated=(
                        getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
                    **deficit.appraisal_signals(),
                )
            except Exception as e:
                # Disposition is not allowed to decide whether the planning
                # result is returned; the deficit is already diagnosed.
                logger.warning("substrate planning-failure appraisal update failed: %s", e)
            return {
                'success': False,
                'task_id': task.id,
                'execution_path': 'substrate_plan',
                'model_free': True,
                'domain_id': domain_id,
                'goal_conditions': spec["goal_conditions"],
                'planning_status': outcome.status.value,
                'operators_considered': outcome.operators_considered,
                'grounding_complete': outcome.grounding_complete,
                'error': f"substrate could not plan the goal: {outcome.reason}",
                'reason': outcome.reason,
                'deficit': deficit.to_dict(),
            }

        # The proved chain, run in dependency order. Each step goes through the
        # same verified path a single operator takes; the plan's provenance
        # already carries what that path needs.
        step_results: List[Optional[Dict[str, Any]]] = []
        for step in outcome.plan.tasks:
            result = await self._try_substrate_execution(step)
            step_results.append(result)
            if result is None:
                return {
                    'success': False, 'task_id': task.id,
                    'execution_path': 'substrate_plan', 'model_free': True,
                    'domain_id': domain_id,
                    'error': "a plan step did not present as a grounded operator",
                    'steps': step_results,
                }
            if not result.get('success'):
                # A step refused (authority not established now) or the world
                # did not move as the rule predicted. The drive stops at the
                # step that diverged, not somewhere downstream of it.
                return {
                    'success': False, 'task_id': task.id,
                    'execution_path': 'substrate_plan', 'model_free': True,
                    'domain_id': domain_id,
                    'goal_conditions': spec["goal_conditions"],
                    'stopped_at': step.description,
                    'error': f"step {step.description} did not confirm: "
                             f"{result.get('refused') or result.get('runtime_outcome')}",
                    'steps': step_results,
                }

        # Every step confirmed. Success is the RE-OBSERVED world holding the
        # goal, not the fact that the steps ran.
        final_world = set(self._observe_world(domain_id) or [])
        reached = all(cond in final_world for cond in spec["goal_conditions"])
        return {
            'success': reached,
            'task_id': task.id,
            'execution_path': 'substrate_plan',
            'model_free': True,
            'domain_id': domain_id,
            'goal_conditions': spec["goal_conditions"],
            'steps_executed': len(step_results),
            'goal_reached': reached,
            'steps': step_results,
        }

    @profile_performance("general_purpose_executor", "execute_task")
    async def _try_substrate_execution(self, task: Task) -> Optional[Dict[str, Any]]:
        """Execute deterministically when the substrate holds the authority to.

        Returns None to fall through to model-backed execution. Every authority
        condition is re-established HERE against current state, not inherited
        from the plan, because planning-time authorization goes stale:

            t0  rule VALIDATED, plan generated
            t1  rule REFUTED by new evidence
            t2  task executes

        "The plan already authorized it" is not an argument at t2. The same
        applies to the world: the planner proved applicability in a simulated
        state, and the state governing execution is the observed one.
        """
        provenance = getattr(task, "provenance", None) or {}
        rule_id = provenance.get("learned_rule_id")
        operator_name = provenance.get("grounded_operator")
        if not rule_id or not operator_name:
            return None

        from core.execution.effect_verification import (
            AttributionContext, RuntimeOutcome, ToolObservation, attribute, verify_effects)
        from core.execution.operator_binding import get_binding_registry
        from core.learning.rule_induction import (Fact, RuleEffects, is_variable,
                                                  resolve_outputs)
        from core.reasoning.unification import match_literal
        from core.learning.rule_store import (
            get_rule_store, record_runtime_evidence)

        def refuse(reason: str) -> Dict[str, Any]:
            """A task built on a learned rule fails closed; it never falls
            through to the model.

            Past this point the task IS a grounded operator -- its description
            is `MOVE(z,HALL,LAB)`, authorised by rule R. If the substrate
            cannot establish that authority now, handing the step to a model to
            interpret would substitute generation for the proof the plan was
            built on, and the plan would appear to proceed on authority that
            had already been withdrawn.
            """
            logger.info("substrate path refused task %s: %s", task.id, reason)
            return {
                'success': False,
                'task_id': task.id,
                'execution_path': 'substrate',
                'model_free': True,
                'learned_rule_id': rule_id,
                'operator': operator_name,
                'refused': reason,
                'error': f"substrate authority not established: {reason}",
            }

        domain = provenance.get("domain_id")
        stored = next((r for r in await get_rule_store().load(domain_id=domain)
                       if r.rule_id == rule_id), None)
        if stored is None:
            return refuse(f"rule {rule_id} is no longer in the store")
        if not stored.is_executable:
            return refuse(f"rule {rule_id} is {stored.status.value}, not validated")

        rule = stored.rule
        if rule.action is None:
            return refuse("rule records no action")

        try:
            action = Fact.parse(operator_name)
        except ValueError as e:
            return refuse(f"operator {operator_name!r} does not parse: {e}")
        if action.signature != rule.action.signature:
            return refuse(f"{action.predicate}/{action.arity} does not match the rule's action")

        bindings: Dict[str, str] = {}
        for slot, value in zip(rule.action.args, action.args):
            if is_variable(slot):
                if bindings.setdefault(slot, value) != value:
                    return refuse(f"{operator_name} is not an instance of {rule.action}")
            elif slot != value:
                return refuse(f"{operator_name} is not an instance of {rule.action}")

        binding = get_binding_registry().get(domain or "", action.predicate)
        if binding is None:
            return refuse(f"no tool bound to {action.predicate} in domain {domain!r}")

        before = binding.observe()
        if before is None:
            return refuse("the world could not be read before acting")

        # THE OBSERVED WORLD DECIDES THE BINDING, NOT THE PLAN.
        #
        # Substituting only what the operator's NAME carries leaves every other
        # precondition variable free, and a fact with a variable in it is in no
        # world -- so a rule whose preconditions bind anything the action does
        # not name refused every time, reported as "preconditions absent". The
        # plan does record its own bindings, and trusting them would be
        # inheriting planning-time state, which this method exists not to do.
        #
        # So the preconditions are matched against the world as it is now.
        # Nothing is loosened: a precondition that does not hold still refuses,
        # and it now refuses with the literal that failed.
        candidates = [bindings]
        for literal in sorted(rule.preconditions, key=str):
            candidates = [extended for candidate in candidates
                          for extended in match_literal(literal, before, candidate)]
            if not candidates:
                return refuse(
                    f"precondition {literal.substitute(bindings)} does not hold in "
                    f"the observed world")
        if len(candidates) > 1:
            return refuse(
                f"{operator_name} matches the observed world in {len(candidates)} "
                f"ways; which instance to act on is not determined")
        bindings = candidates[0]

        # A value the action computes is computed now, from what the world was
        # just observed to hold.
        resolved = resolve_outputs(rule, bindings)
        if resolved is None:
            return refuse(
                "a value this action produces has no result on the observed terms")
        bindings = resolved

        # Authorized. Safety and governance are enforced inside execute_tool,
        # which is the single evaluation point for every tool call.
        from core.tools import get_tool_registry

        observation_id = f"obs_{uuid.uuid4().hex[:12]}"
        # The world is read before and after under a concurrency guard: if
        # another substrate execution in this domain overlapped the act, a
        # mismatch is not this rule's to answer for. The guard serializes
        # nothing -- the act still runs concurrently; it only remembers the
        # overlap so attribution can be honest about it.
        from core.execution.effect_verification import concurrent_execution_guard
        with concurrent_execution_guard(domain) as _overlapped:
            result = await get_tool_registry().execute_tool(
                binding.tool_name, binding.parameters(action.args))
            after = binding.observe()
            interfered = _overlapped()
        observation = ToolObservation(
            observation_id=observation_id,
            tool_name=binding.tool_name,
            invoked=True,
            tool_reported_success=bool(getattr(result, "success", False)),
            observed=after is not None,
            facts=after if after is not None else frozenset(),
            before=before,
            error=getattr(result, "error", None),
            raw={"output": getattr(result, "output", None)},
        )
        # An effect still carrying a variable is one the rule declared it could
        # not predict. It is still checked -- against what the action CHANGED,
        # which is what `ToolObservation.before` is for.
        evidence = verify_effects(rule.effects.substitute(bindings), observation,
                                  rule_id=rule_id, operator=operator_name)

        # Attribution is built from what THIS method independently established
        # on the way to authorizing the call. Each flag was a gate above; none
        # is asserted on trust.
        #
        # `external_interference` means KNOWN interference. The executor still
        # cannot prove a quiet world in general, but it CAN know when another
        # substrate execution in the same domain overlapped this act -- and then
        # a mismatch is not attributable to this rule. Defaulting to False when
        # no overlap was seen keeps single-task and cross-domain learning intact;
        # the guard raises it only for a real, observed concurrent overlap, so a
        # correct rule is never revised because another task happened to run.
        attribution, why = attribute(evidence, AttributionContext(
            preconditions_observed=True,      # checked against `before`
            rule_validated_at_execution=True,  # status re-read above
            action_matches_rule=True,          # signature + instance check
            arguments_verified=True,           # built from the parsed operator
            invocation_occurred=True,
            observer_available=after is not None,
            post_state_observed=after is not None,
            external_interference=interfered,
        ))
        revised_status = await record_runtime_evidence(
            get_rule_store(), evidence, attribution, why,
            task_id=task.id,
            plan_id=provenance.get("plan_id"),
            goal_id=provenance.get("goal_id"),
        )

        logger.info("substrate execution %s: %s (%s) — %s",
                    operator_name, evidence.outcome.value, attribution.value,
                    evidence.detail)

        await self._appraise_substrate_execution(task, evidence, attribution, observation)
        await self._record_execution_demonstration(
            domain=domain, action=action, before=before, after=after,
            observation_id=observation_id, evidence=evidence)

        return {
            # Success means the world changed as the rule predicted. A tool that
            # returned cleanly while the world did not move is the case where
            # the action model is wrong and the substrate must find out.
            'success': evidence.outcome is RuntimeOutcome.CONFIRMATION,
            'task_id': task.id,
            'execution_path': 'substrate',
            'model_free': True,
            'learned_rule_id': rule_id,
            'operator': operator_name,
            'runtime_outcome': evidence.outcome.value,
            'attribution': attribution.value,
            'rule_status_after': revised_status.value if revised_status else None,
            'observation_id': observation_id,
            'effects': [
                {'effect': str(v.predicted_effect), 'polarity': v.polarity.value,
                 'verdict': v.verdict.value, 'detail': v.detail}
                for v in evidence.verifications
            ],
            'detail': evidence.detail,
        }

    async def _record_execution_demonstration(
        self, *, domain, action, before, after, observation_id, evidence,
    ) -> None:
        """File one executed action as a demonstration the learner can use.

        THIS IS THE ONLY PLACE THE SUBSTRATE OBSERVES ITS OWN STATE TRANSITIONS.
        `before`, the action invoked and `after` are all read from the world a
        few lines above, so this is the one point in real work that produces the
        before/action/after triple induction needs. Until it was wired, the
        learner could only generalize from demonstrations a TEACHER supplied,
        and every concept a projected rule contributed was confined to a taught
        domain -- which is why cross-domain transfer had exactly one source
        domain to draw on.

        `training_example_from_runtime` was built for this and had no callers.

        NOT recorded when the world could not be read afterwards, and NOT
        recorded for an INDETERMINATE outcome. A demonstration carries a
        verdict, and an unlabelled one defaults to positive -- which would file
        "we could not tell" as "the action worked".
        """
        from core.execution.effect_verification import RuntimeOutcome

        if after is None:
            logger.info(
                "%s: world unreadable after acting; no demonstration recorded "
                "(an unobserved after-state is not an empty one)", observation_id)
            return
        if evidence.outcome is RuntimeOutcome.INDETERMINATE:
            logger.info(
                "%s: outcome indeterminate; no demonstration recorded — an "
                "unlabelled example would be induced from as a positive",
                observation_id)
            return
        if not domain:
            logger.warning(
                "%s: no domain on the executed rule; a concept must belong "
                "somewhere and inventing a domain here is how one topic "
                "acquired 21", observation_id)
            return

        from core.domain.concept_ingestion import EvidenceSourceType
        from core.domain.evidence_producers import submit_demonstration
        from core.learning.rule_store import training_example_from_runtime

        example = training_example_from_runtime(
            before=before, action=action, after=after,
            evidence_id=observation_id,
            positive=evidence.outcome is RuntimeOutcome.CONFIRMATION)

        # THE OPERATOR-LEARNING PATHWAY. Independent of concept ingestion below:
        # this keeps the executed transition so the substrate's plannable
        # repertoire can grow from its own experience. It only RECORDS here --
        # induction is a hypothesis search whose cost grows with the richness of
        # the observed state, far too expensive to run inline, so the
        # always-online learner re-induces off the hot path. The concept path
        # records the transition's structure for cross-domain matching; this
        # records the operator's own evidence. One failing must not lose the
        # other, so they are separate blocks.
        try:
            from core.learning.learning_authority import get_learning_authority
            recorded = await get_learning_authority().record_demonstration(
                example, domain_id=domain)
            logger.info(
                "%s: demonstration %s for operator learning (%s)",
                observation_id, "kept" if recorded else "already held",
                "positive" if example.positive else "negative")
        except Exception as e:
            from core.capability import raise_if_structural
            raise_if_structural(e, "general_purpose_executor.record_demonstration")
            logger.error(
                "%s executed but its demonstration could not be kept: %s: %s",
                observation_id, type(e).__name__, e)

        try:
            result = await submit_demonstration(
                example, domain_id=domain,
                source_type=EvidenceSourceType.TASK_ARTIFACT,
                producer="substrate_execution",
                source_id=f"{domain}:{action.predicate}")
        except Exception as e:
            # Loud, never swallowed: the tool ran and the world moved, so
            # failing the execution over a projection defect would lose the
            # real result. A silent pass would make a broken projection
            # indistinguishable from an action with nothing to project.
            logger.error(
                "%s executed but its demonstration could not be recorded: %s: %s",
                observation_id, type(e).__name__, e)
            return

        if not result.read_successfully:
            logger.error(
                "%s: demonstration recorded but unreadable as structure: %s",
                observation_id, result.extraction_failures)
            return
        logger.info(
            "%s: demonstration recorded (%s) -> %d concept(s) accepted",
            observation_id,
            "positive" if example.positive else "negative", result.accepted)

    async def _appraise_substrate_execution(
        self, task: "Task", evidence, attribution, observation
    ) -> None:
        """Report a substrate execution to appraisal, in measured signals only.

        The model-backed path feeds appraisal through _fire_reward_signals, but
        the substrate path returns before ever reaching it, so acting on proved
        knowledge left disposition untouched -- including when the proof turned
        out to be wrong. That is the one outcome disposition most needs.

        Two signals that look like one are kept apart deliberately:

            action_success_rate   did the action execute?     (the tool ran)
            outcome_quality       was the prediction right?   (the world moved)

        A refuted rule is the case where the first is 1.0 and the second is 0.0
        -- the tool worked perfectly and the model was wrong. Collapsing them
        would read as "we cannot affect the world", which is escalation, when
        the truth is "we still have control and this route is wrong", which is
        replanning.

        Signals with no measurement here are omitted rather than defaulted, so
        nothing invented reaches the appraisal.
        """
        from core.agents.autonomous.appraisal import get_appraisal_system
        from core.execution.effect_verification import RuntimeOutcome, outcome_class_for

        if evidence.outcome is RuntimeOutcome.CONFIRMATION:
            quality = 1.0
        elif evidence.outcome is RuntimeOutcome.CONTRADICTION:
            quality = 0.0
        else:
            quality = None   # nothing was established; do not score it

        try:
            get_appraisal_system().update(
                outcome_quality=quality,
                outcome_class=outcome_class_for(evidence, attribution),
                action_success_rate=(
                    1.0 if observation.tool_reported_success else 0.0),
                # The substrate authorises exactly one operator per step, so
                # there was no choice among options. Reporting otherwise would
                # inflate agency, which feeds replan pressure directly.
                options_considered=1,
                self_initiated=(
                    getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
            )
        except Exception as e:
            # Disposition is not allowed to decide whether the execution result
            # is returned. The evidence is already durable at this point.
            logger.warning("substrate appraisal update failed: %s", e)

    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """
        Execute a task, substrate-first.

        A task carrying a grounded operator from a VALIDATED learned rule is
        already proved: the substrate knows what to do and why. That runs
        deterministically here, with no model consulted. Everything else falls
        through to model-backed execution, where the model acts as a proposer
        for work the substrate cannot yet do itself.

        This mirrors neural_bridge._substrate_solvers, which has routed reasoning
        this way all along. Execution previously went straight to the model
        unconditionally, so a step the substrate could prove was still decided
        by generation.

        Args:
            task: Task to execute

        Returns:
            Dict with execution results
        """
        substrate = await self._try_substrate_execution(task)
        if substrate is not None:
            return substrate

        # A task that names a STATE to reach is planned over learned operators
        # and driven to completion here, still with no model consulted. Where
        # the single-operator path runs one proved step, this proves and runs a
        # whole sequence. It declines (None) only when the task carries no state
        # goal, and then execution falls through as before.
        driven = await self._drive_substrate_goal(task)
        if driven is not None:
            return driven

        if not self.active or not self.llm:
            logger.error("Executor not initialized")
            return {
                'success': False,
                'error': 'Executor not initialized',
                'task_id': task.id
            }

        try:
            logger.info(f"Executing task {task.id}: {task.description}")

            # ====================================================================
            # DRIFT CHECK: Reduce task complexity if completion rate is degrading
            # ====================================================================
            drift_adjustment = None
            if self.completion_validator:
                drift_metrics = self.completion_validator.get_drift_metrics()
                if drift_metrics.get("sufficient_data") and drift_metrics.get("is_degrading"):
                    failure_rate = drift_metrics.get("failure_rate", 0)
                    logger.warning(
                        f"⚠️ COMPLETION DRIFT DETECTED: {failure_rate:.1%} failure rate. "
                        f"Recommendation: {drift_metrics.get('recommendation')}"
                    )
                    drift_adjustment = {
                        "max_iterations_reduced": True,
                        "original_failure_rate": failure_rate
                    }

            # Track stats
            task_type_name = task.type.name
            if task_type_name not in self.stats['by_type']:
                self.stats['by_type'][task_type_name] = {
                    'executed': 0,
                    'successful': 0,
                    'failed': 0
                }

            # ====================================================================
            # GOVERNANCE PRE-EXECUTION CHECK
            # Runs before any tool calls. Checks constitutional laws and blocks
            # tasks that touch protected systems (memory architecture, etc.).
            # ====================================================================
            _gov_action_id = f"task_{task.id}"
            _gov_rg = None
            _gov_checkpoint_active = False
            try:
                from core.agents.autonomous.runtime_governance import get_runtime_governance
                _gov_rg = get_runtime_governance()
                _gov_chk = await _gov_rg.pre_execution_check(
                    action_id=_gov_action_id,
                    action_description=task.description,
                    action_params={
                        "task_type": task.type.value if hasattr(task.type, 'value') else str(task.type),
                        "task_id": task.id,
                        "priority": getattr(task, 'priority', 'medium'),
                    },
                    singleton_context={"source": "task_executor"}
                )
                if _gov_chk.passed:
                    _gov_checkpoint_active = True
                else:
                    # Classify violations by enforcement level.
                    # HALT  → system is literally halted, hard-stop immediately.
                    # BLOCK → constitutional advisory; inject constraints and let the
                    #         AI reformulate. Killing the task here defeats autonomy.
                    # SLOW/WARN → already non-blocking, just log.
                    _halt_violations = [
                        v.details for v in _gov_chk.violations_detected
                        if getattr(v, 'enforcement_action', None) and
                           str(v.enforcement_action).upper().endswith('HALT')
                    ]
                    if _halt_violations:
                        logger.warning(f"GOVERNANCE HALT task {task.id}: {_halt_violations}")
                        return {
                            'success': False,
                            'error': f"GOVERNANCE_HALTED: {'; '.join(_halt_violations)}",
                            'task_id': task.id,
                            'governance_blocked': True,
                        }

                    # BLOCK-level violations become advisory constraints prepended to
                    # the task prompt so the AI can plan around them.
                    _advisory_violations = [
                        v.details for v in _gov_chk.violations_detected
                        if not (getattr(v, 'enforcement_action', None) and
                                str(v.enforcement_action).upper().endswith('HALT'))
                    ]
                    if _advisory_violations:
                        _advisory_text = (
                            "[GOVERNANCE ADVISORY — READ BEFORE PLANNING]\n"
                            "The following governance constraints apply to this task.\n"
                            "You MUST plan your approach to avoid violating them:\n"
                            + "\n".join(f"  • {d}" for d in _advisory_violations)
                            + "\n[END GOVERNANCE ADVISORY]\n\n"
                        )
                        task.description = _advisory_text + task.description
                        logger.info(
                            f"Governance advisory injected for task {task.id}: "
                            f"{len(_advisory_violations)} constraint(s)"
                        )
                    _gov_checkpoint_active = True  # Continue — AI will self-constrain
            except Exception as _gov_e:
                logger.error(f"Governance pre-check FAILED — task running WITHOUT governance guard: {_gov_e}", exc_info=True)

            # Execute task using agent loop with tools
            # Pass drift_adjustment to potentially reduce complexity
            try:
                result = await self._execute_task_with_tools(task, drift_adjustment=drift_adjustment)
            finally:
                if _gov_checkpoint_active and _gov_rg:
                    try:
                        _gov_rg.clear_action(_gov_action_id)
                    except Exception as _gov_clear_err:
                        logger.error("Failed to clear governance checkpoint %s: %s — checkpoint leak",
                                     _gov_action_id, _gov_clear_err)

            # Update task
            task.result = result
            task.status = TaskStatus.COMPLETED if result.get('success', False) else TaskStatus.FAILED
            task.completed_at = datetime.now()

            # Update stats
            self.stats['tasks_executed'] += 1
            self.stats['by_type'][task_type_name]['executed'] += 1

            if result.get('success', False):
                self.stats['tasks_successful'] += 1
                self.stats['by_type'][task_type_name]['successful'] += 1
                logger.info(f"Task {task.id} completed successfully")
                # Memory capture handled automatically by neural bridge
            else:
                self.stats['tasks_failed'] += 1
                self.stats['by_type'][task_type_name]['failed'] += 1
                logger.warning(f"Task {task.id} failed: {result.get('error', 'Unknown error')}")

            return result

        except Exception as e:
            logger.error(f"Task execution error {task.id}: {e}")

            # Update stats for failure
            self.stats['tasks_executed'] += 1
            self.stats['tasks_failed'] += 1
            if task.type.name in self.stats['by_type']:
                self.stats['by_type'][task.type.name]['executed'] += 1
                self.stats['by_type'][task.type.name]['failed'] += 1

            return {
                'success': False,
                'error': str(e),
                'task_id': task.id,
                'task_type': task.type.name
            }

    async def _execute_task_with_tools(self, task: Task, drift_adjustment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute task using agent loop with actual tool invocations

        Multi-turn conversation where LLM:
        1. Decides what tools to use
        2. Executor runs those tools
        3. Results feed back to LLM
        4. Repeats until task complete
        
        If drift_adjustment is provided, reduces max_iterations to prevent
        wasting resources when completion rate is degrading.
        """
        import time
        start_time = time.time()

        conversation_history = []
        tool_results = []

        # Track tool failures to prevent infinite loops
        failed_tools = {}  # {tool_name: failure_count}
        MAX_TOOL_FAILURES = 3  # 1st=warn, 2nd=suggest alternate, 3rd=abort tool path

        # Argument fingerprinting — reject identical failing calls (point 4)
        failed_call_signatures: dict = {}  # {hash(tool_name+sorted_args): fail_count}

        # Successful-call deduplication — blocks the same successful call being
        # repeated more than _MAX_SUCCESS_REPEATS times.  Prevents the model from
        # looping on identical web_search/grep_search queries after already getting
        # results.  Only applies to "retrieval" tools where repeating the same args
        # truly yields nothing new.
        success_call_signatures: dict = {}  # {hash(tool_name+sorted_args): count}
        _SUCCESS_DEDUP_TOOLS = {
            "web_search", "grep_search", "search_code", "search_academic",
            "fetch_page", "web_fetch", "http_request",
        }
        _MAX_SUCCESS_REPEATS = 2  # block on the 3rd identical successful call

        # Tool sequence history — for oscillation detection (point 5)
        _tool_call_history: list = []  # tool_name strings, most-recent last
        _osc_count: int = 0  # consecutive oscillation detections

        # Per-tool failure details for failure memory injection (point 6)
        tool_failure_details: dict = {}  # {tool_name: {count, category, short_hint}}

        # Calls-without-real-progress counter (point 10)
        _no_real_progress_calls: int = 0
        _MAX_NO_PROGRESS_CALLS: int = 10

        # Track repeated file reads to detect loops
        file_reads = {}  # {file_path: read_count}

        # Track successful-but-no-progress calls to detect stuck loops.
        # Key: (tool_name, fingerprint_of_key_arg), Value: success count.
        # When the same tool+arg combo succeeds 2+ times with no intervening
        # side-effects from OTHER tools, the agent is looping without progress.
        _noprogress_calls: dict = {}  # {(tool_name, arg_fp): count}
        MAX_NOPROGRESS_REPEATS = 3  # Nudge after 3 reads of same file+range with no patch

        # ── Execution Ledger (Risk 3 mitigation) ──────────────────────────────
        # A compact, human-readable log of every significant event: tool calls
        # (success/fail), hard gate failures, revision requests, and verification
        # rejections.  Unlike conversation_history, the ledger is NEVER compressed
        # by the 8B model — it is re-injected as a fresh system message after every
        # compression event so the agent always sees the full causal chain even after
        # the conversation has been compressed several times.
        execution_ledger: List[str] = []

        # Reset context manager turn count for new task
        if self.context_manager:
            self.context_manager.reset_turn_count()

        # ========== MEMORY RETRIEVAL: Inject previous context ==========
        previous_context = ""
        #: Memories retrieved once at task start, handed to the neural bridge so
        #: it does not search again. The bridge's contract: None = search fresh,
        #: [] = already in the conversation, non-empty = inject these.
        #:
        #: This was assigned and NEVER READ (AST-verified: stored at two lines,
        #: loaded at none), so `request.cached_memories` was always None and the
        #: bridge ran its own search on top of this one -- the same memories
        #: fetched twice per task, which is exactly what this variable was
        #: introduced to prevent.
        try:
            # Retrieve previous memories related to this task
            if self.memory_agent:
                logger.info(f"Retrieving previous context for task: {task.id}")

                # Ask the ONE policy whether memory belongs here, and on what
                # terms — do not decide it locally.
                #
                # Torin has three separate places that decided this
                # independently: MemoryInjectionPolicy.decide() (consulted only
                # by the coordinator's get_intelligent_memory_context),
                # MemoryInjector._should_search_memories() (its own keyword
                # gate), and this block — which had NO gate at all and a
                # hardcoded min_similarity=0.7 / limit=3. Three answers to
                # "should prior context enter cognition, and how much", drifting
                # apart by construction.
                #
                # Placement legitimately differs — task-start injection and
                # reasoning-call injection happen at different lifecycle points
                # — but relevance must not. One policy decides whether and what;
                # consumers decide only where it goes.
                task_summary = task.description[:200]
                try:
                    from core.memory.utils.memory_injection_policy import (
                        get_memory_injection_policy,
                    )
                    plan = get_memory_injection_policy().decide(
                        query=task_summary,
                        context_type="task_execution",
                    )
                except Exception as e:
                    # A missing policy must not silently restore the old
                    # hardcoded behaviour under a different name.
                    logger.warning(f"[MEMORY] injection policy unavailable: {e}")
                    plan = None

                if plan is not None and not plan.enabled:
                    logger.info(
                        f"[MEMORY] policy declined injection for this task "
                        f"({', '.join(plan.reason_codes) or 'no reason given'})"
                    )
                    success2, semantic_memories = True, []
                else:
                    _limit = plan.max_memories if plan else 3
                    _min = plan.min_relevance if (plan and plan.min_relevance) else 0.7
                    logger.info(
                        f"[MEMORY] policy: limit={_limit} min_relevance={_min} "
                        f"({', '.join(plan.reason_codes) if plan else 'fallback'})"
                    )
                    success2, semantic_memories = await self.memory_agent.search_memories(
                        query=task_summary,
                        min_similarity=_min,
                        limit=_limit,
                        deduplicate=True  # Use deduplication to avoid redundant memories
                    )
                logger.debug(
                    f"[MEMORY] Semantic search complete: {len(semantic_memories or [])} results"
                )

                unique_memories = semantic_memories or []

                if unique_memories:
                    logger.info(
                        f"Retrieved {len(unique_memories)} relevant memories for task"
                    )

                    # `cached_memories` REMOVED 2026-08-24. It was assigned
                    # here, commented "Store for passing to neural bridge", and
                    # never passed anywhere -- the executor does not call the
                    # bridge. The retrieval itself is NOT wasted: the same
                    # memories are formatted just below into `previous_context`,
                    # which does reach the prompt.

                    # Format memories with token budget
                    # NOTE: datetime is already imported at module level (line 19)
                    memory_summaries = []

                    MAX_MEMORY_TOKENS = 800  # Hard cap on memory injection
                    current_tokens = 0

                    for mem in unique_memories:
                        timestamp_str = datetime.fromtimestamp(mem.created_at).strftime('%Y-%m-%d')

                        # Truncate to 200 chars per memory
                        mem_excerpt = mem.content[:200]
                        mem_tokens = len(mem_excerpt.split())

                        if current_tokens + mem_tokens > MAX_MEMORY_TOKENS:
                            break

                        memory_summaries.append(f"- [{timestamp_str}] {mem_excerpt}")
                        current_tokens += mem_tokens

                    if memory_summaries:
                        previous_context = "\n\nPREVIOUS RELEVANT WORK:\n" + "\n".join(memory_summaries)
                    else:
                        previous_context = ""

                    logger.info(f"Injected {len(memory_summaries)} memories into context")
                else:
                    logger.info("No previous memories found for this task")

        except Exception as e:
            logger.error(f"Failed to retrieve previous context — task running WITHOUT memory injection: {e}", exc_info=True)
            previous_context = ""

        try:
            integration_status = self._get_runtime_integration_status()

            # Get available tools using capability-based discovery
            available_tools = await self._get_tools_by_capability(task.description, task_type=task.type)
            available_tools = self._filter_tools_by_runtime_config(
                available_tools,
                integration_status=integration_status,
            )

            # Build OpenAI-compatible tool schemas for native function calling.
            # This replaces the old text-description approach: instead of embedding
            # a giant tool list in the user message, we pass structured schemas to
            # create_chat_completion() so the model returns structured tool_calls.
            # Order by RELEVANCE to this task before the cap below truncates.
            #
            # This iterated the dict and kept the first 20, so which tools the
            # model could call was decided by registration order. Measured cost:
            # the finding `auth_missing_env_POSTGRES_PASSWORD` — whose own
            # remediation is "Set POSTGRES_PASSWORD in the .env file" — ran for
            # 200 iterations calling read_file 923 times, list_directory 446 and
            # search_files 412, and called `set_environment_variable`,
            # `generate_password`, `modify_config_file` and `postgres_query`
            # ZERO times. Not a capability gap: those tools exist, are correctly
            # implemented, and safety allows them. discover_tools() ranks all
            # four into the top 8 for that exact text. The model simply never
            # saw them, and `request_tools` cannot rescue it because nothing can
            # request a tool it does not know exists.
            #
            # The ranker is already the one discovery implementation (BM25 +
            # encoder + capability graph, 0.81 recall@8). Using it here costs
            # one call and decides the whole task.
            ranked_names: List[str] = []
            ranked_scored: List[Tuple[str, float]] = []
            try:
                from core.tools.tool_registry import get_tool_registry as _gtr
                registry = self.tool_registry or _gtr()
                # WITH SCORES. The ranking is the only model-free opinion the
                # system has about which tool fits this task, and discarding
                # the numbers left `selection_score` permanently None: the
                # snapshot it is measured against was read from
                # `_last_ranked_tools`, which NOTHING assigned. A reader with no
                # writer, so every selection recorded as UNRANKED and the
                # "picked a tool the ranker scored far below its top candidate"
                # signal could not fire once.
                for t, score in registry.discover_tools(
                        task.description, MAX_INITIAL_TOOL_SCHEMAS,
                        with_scores=True):
                    n = getattr(t, "name", None)
                    if n and n in available_tools:
                        ranked_names.append(n)
                        ranked_scored.append((n, float(score)))
            except Exception as e:
                logger.warning(f"tool ranking unavailable, falling back to registration order: {e}")

            # Held for the credit step, which must score the decision against
            # the ranking AS IT WAS, not a re-ranking done after the outcome is
            # known — by then the registry, the capability graph and accumulated
            # affinity have all moved.
            self._last_ranked_tools = ranked_scored

            ordered = [(n, available_tools[n]) for n in ranked_names]
            ordered += [(n, t) for n, t in available_tools.items() if n not in set(ranked_names)]
            if ranked_names:
                logger.info(f"[TOOL RANK] top for this task: {', '.join(ranked_names[:8])}")

            tool_schemas = []
            for tool_name, tool in ordered:
                if hasattr(tool, 'to_openai_schema'):
                    try:
                        tool_schemas.append(tool.to_openai_schema())
                    except Exception as e:
                        logger.warning(f"Could not build schema for tool {tool_name}: {e}")

            # ── Risk 2: Tool cap + reserved pool ──────────────────────────────
            # Expose only MAX_INITIAL_TOOL_SCHEMAS to the model initially; hold
            # the rest in reserve so the agent can pull them via request_tools.
            # This keeps schema token overhead predictable and reduces mis-selection
            # probability caused by a 200+ item choice set.
            reserved_tool_pool: Dict[str, Any] = {}  # tool_name → openai schema
            if len(tool_schemas) > MAX_INITIAL_TOOL_SCHEMAS:
                excess = tool_schemas[MAX_INITIAL_TOOL_SCHEMAS:]
                for schema in excess:
                    name = schema.get("function", {}).get("name", "")
                    if name:
                        reserved_tool_pool[name] = schema
                tool_schemas = tool_schemas[:MAX_INITIAL_TOOL_SCHEMAS]
                logger.info(
                    f"[TOOL CAP] Capped initial schemas to {MAX_INITIAL_TOOL_SCHEMAS}, "
                    f"{len(reserved_tool_pool)} tools in reserve (request via request_tools)"
                )

            # Add meta-tools last (always present, not subject to cap)
            tool_schemas.append(PROPOSE_COMPLETION_TOOL)
            tool_schemas.append(REQUEST_TOOLS_TOOL)

            filtered_tool_count = len(available_tools)

            # ── Fail fast if zero tools ──────────────────────────────────
            if filtered_tool_count == 0:
                logger.warning(
                    f"Task {task.id} has 0 tools available — aborting "
                    f"(tool registry may not be fully loaded yet)"
                )
                return {
                    'success': False,
                    'error': 'No tools available for this task — tool registry may not be initialized',
                    'task_id': task.id,
                }

            # Estimate tool schema token cost for context budget.
            #
            # IMPORTANT: use character-length / 3 (not word count) because JSON is
            # tokenized very differently from prose — every brace, quote, colon, and
            # camelCase identifier can be its own token.  Word-count was ~15× too low
            # (587 words ≈ 587 tokens, but actual inference showed ~10 k tokens of
            # schema + system-prompt overhead), which caused compression to never fire
            # before context overflow.
            import json as _json_mod
            tool_schemas_text = _json_mod.dumps(tool_schemas, separators=(',', ':'))
            # chars / 3 ≈ tokens for JSON; add system_prompt overhead (estimated
            # at chars / 4 since it is natural prose, slightly denser than JSON).
            # This intentionally over-estimates slightly to trigger compression early.
            _schema_chars   = len(tool_schemas_text)
            _sysprompt_chars = 0  # filled in below after system_prompt is built
            # Placeholder — updated after system_prompt is constructed (line ~1390)
            tool_desc_tokens_est = _schema_chars // 3
            logger.info(
                f"[TOOL SCHEMAS] {filtered_tool_count} tools + propose_completion → "
                f"{len(tool_schemas)} total schemas, ~{tool_desc_tokens_est} tokens (est, "
                f"schema_chars={_schema_chars})"
            )

            # Keep only static prompt in system role for compression
            task_executor_prompt = self.llm.system_prompts.get("task_executor",
                "You are an autonomous AI agent executing tasks.")

            # ── Append singleton's own environment to the system prompt ─────────
            # This describes where THE SINGLETON ITSELF lives — its own logs,
            # source code, and data directories.  It is NOT about the user's
            # workspace or the task being executed.  Keeping it in the system
            # prompt (not the user message) ensures the model can distinguish
            # "my own files" from "files the user is asking me to work on".
            import os as _os
            _base = _os.path.dirname(_os.path.abspath(__file__))
            # Walk up until we find the TorinAI root (has core/ and logs/)
            for _ in range(6):
                if _os.path.isdir(_os.path.join(_base, "core")) and _os.path.isdir(_os.path.join(_base, "logs")):
                    break
                _base = _os.path.dirname(_base)

            _env_lines = [
                "",
                "MY OWN ENVIRONMENT (the singleton's installation — not the user's workspace):",
                f"  my_base_directory: {_base}",
                f"  NOTE: When a task asks you to inspect your own logs, configs, or source",
                f"  code, use the paths below. When a task involves the USER's files, use",
                f"  whatever paths they provide — do NOT assume their files are in my base dir.",
            ]
            _known_dirs = [
                ("logs/",   "my application logs"),
                ("core/",   "my source code"),
                ("data/",   "my data files"),
                ("config/", "my config files"),
                ("models/", "my model weights"),
            ]
            _env_lines.append("  my_key_directories:")
            for _d, _desc in _known_dirs:
                if _os.path.isdir(_os.path.join(_base, _d.rstrip("/"))):
                    _env_lines.append(f"    {_os.path.join(_base, _d)}  ({_desc})")

            # ── Output document directory (iCloud Drive) ─────────────────────
            # Torin MUST write a professional human-readable document here after
            # every substantive completed task.  Use write_file with create_dirs=True.
            # Sub-directories by task type are pre-created:
            #   research/           — RESEARCH tasks
            #   analysis/           — ANALYSIS tasks
            #   self-improvement/   — SELF_IMPROVEMENT tasks
            #   security/           — SECURITY_REMEDIATION tasks
            #   learning/           — LEARNING tasks
            #   optimization/       — OPTIMIZATION tasks
            #   planning/           — PLANNING, SYNTHESIS tasks
            #   validation/         — VALIDATION tasks
            #   general/            — everything else
            _icloud_output = _os.path.expanduser(
                "~/Library/Mobile Documents/com~apple~CloudDocs/output-file"
            )
            _env_lines += [
                "",
                "OUTPUT DOCUMENT DIRECTORY (iCloud Drive — syncs to all devices):",
                f"  output_root: {_icloud_output}",
                "  REQUIRED: After completing any substantive task, write a professional",
                "  human-readable Markdown (.md) report to the appropriate sub-directory.",
                "  Use the write_file tool with create_dirs=True.",
                "  Filename format: YYYY-MM-DD_HHMM_<short-slug>.md",
                "  Example: research/2026-03-05_1142_iot_sensor_fusion_analysis.md",
                "  Document must include: executive summary, key findings/conclusions,",
                "  methodology, outputs, and sources. Write for a non-technical reader.",
            ]

            _log_dir = _os.path.join(_base, "logs")
            if _os.path.isdir(_log_dir):
                _log_files = sorted(
                    f for f in _os.listdir(_log_dir)
                    if f.endswith(".log") and _os.path.isfile(_os.path.join(_log_dir, f))
                )
                if _log_files:
                    _env_lines.append("  my_log_files:")
                    for _lf in _log_files[:12]:
                        _env_lines.append(f"    {_os.path.join(_log_dir, _lf)}")

            system_prompt = task_executor_prompt + "\n".join(_env_lines)
            # ─────────────────────────────────────────────────────────────────

            # Now that system_prompt is built, compute the actual token overhead.
            #
            # Calibration (observed from run data):
            #   schema_chars=12,579 → actual llama overhead ≈ 19,000–20,000 tokens
            #   (llama.cpp wraps tool schemas in its chat template with extra
            #   formatting, adding ~1.6 tokens per char of raw schema JSON)
            #   sysprompt_chars ≈ 4,000 chars → actual ≈ 1,600 tokens (0.4 tokens/char)
            #   max_output contribution: accounted for in the conversation budget
            #
            # net available for conversation:
            #   = n_ctx − schema_tokens − sysprompt_tokens − max_output_hard_cap
            #
            _sysprompt_chars = len(system_prompt)
            _schema_tokens_est   = int(_schema_chars   * 1.6)
            _sysprompt_tokens_est = int(_sysprompt_chars * 0.4)
            # Hard cap so we always reserve at least 2048 tokens for generation
            _max_output_cap = 2048
            tool_desc_tokens_est = _schema_tokens_est + _sysprompt_tokens_est + _max_output_cap
            logger.info(
                f"[TOKEN OVERHEAD] schema={_schema_tokens_est} + "
                f"sysprompt={_sysprompt_tokens_est} + output_cap={_max_output_cap} "
                f"= {tool_desc_tokens_est} tokens reserved "
                f"(compression threshold = {int(0.70 * max(self.context_manager.n_ctx - tool_desc_tokens_est, 1))} "
                f"conversation tokens)"
            )

            conversation_history.append({"role": "system", "content": system_prompt})

            # Initial user message: framed as an execution directive, not a chat
            # prompt. "Begin working" triggers the chat-assistant greeting pattern;
            # an imperative with an implied first action suppresses it.
            initial_user_message = (
                f"[TASK:{task.id}]\n"
                f"{task.description}"
                + (f"\n\n{previous_context}" if previous_context else "")
                + "\n\n" + self._build_preflight_context(task, integration_status=integration_status)
                + "\n\nExecute now — emit your first tool call."
            )

            # FAILURE CONTEXT INJECTION: If this is a retry, prepend a structured
            # block of exactly what went wrong in previous attempts. Without this,
            # the LLM retries blindly with the same prompt and makes the same mistakes.
            _failure_history = (task.metadata or {}).get('failure_history', [])
            if _failure_history:
                _fh_lines = [
                    "\n\n" + "="*60,
                    "⚠️  RETRY — PREVIOUS ATTEMPTS FAILED. READ THIS BEFORE ACTING.",
                    "="*60,
                    "You have already attempted this task and it FAILED. Do NOT repeat the same actions.",
                    "Diagnose the root cause from the errors below, then take a DIFFERENT approach.\n",
                ]
                for _fh in _failure_history:
                    _fh_lines.append(f"--- Attempt {_fh.get('attempt', '?')} failure ---")
                    _fh_issues = _fh.get('issues', [])
                    if _fh_issues:
                        _fh_lines.append(f"  Validation issues: {'; '.join(str(i) for i in _fh_issues)}")
                    _fh_tools = _fh.get('failed_tools', [])
                    if _fh_tools:
                        for _ft in _fh_tools:
                            _fh_lines.append(f"  Tool '{_ft['tool']}' failed with: {_ft['error']}")
                    _fh_err = _fh.get('error', '')
                    if _fh_err:
                        _fh_lines.append(f"  Error: {_fh_err}")
                _fh_lines.append("\n" + "="*60)
                _fh_lines.append("REQUIRED: Use read_file / run_shell_command / validate_path to diagnose")
                _fh_lines.append("the environment FIRST before attempting to execute the original task.")
                _fh_lines.append("="*60)
                initial_user_message = "\n".join(_fh_lines) + "\n\n" + initial_user_message
                logger.info(f"[RetryContext] Injected {len(_failure_history)} failure(s) into prompt for task {task.id}")

            conversation_history.append({"role": "user", "content": initial_user_message})

            # Calculate token budget if context manager available
            token_budget = None
            if self.context_manager:
                token_budget = self.context_manager.calculate_token_budget(
                    system_prompt=system_prompt,
                    tool_descriptions=tool_schemas_text  # use serialised schemas for budget estimate
                )

                if logger.isEnabledFor(logging.DEBUG):
                    available_calc = (
                        token_budget.total_context_window
                        - token_budget.system_prompt_tokens
                        - token_budget.tool_description_tokens
                        - token_budget.safety_margin
                    )
                    logger.debug(
                        "[INITIAL TOKEN BUDGET DEBUG] window=%s system=%s tools=%s margin=%s available=%s calc=%s",
                        f"{token_budget.total_context_window:,}",
                        f"{token_budget.system_prompt_tokens:,}",
                        f"{token_budget.tool_description_tokens:,}",
                        f"{token_budget.safety_margin:,}",
                        f"{token_budget.available_for_generation:,}",
                        f"{int(available_calc * 0.90):,}",
                    )

                logger.info(
                    f"Token budget: {token_budget.available_for_generation} available for generation "
                    f"(window={token_budget.total_context_window}, "
                    f"system={token_budget.system_prompt_tokens}, "
                    f"tools={token_budget.tool_description_tokens}, "
                    f"margin={token_budget.safety_margin})"
                )

            # Phase 2: Compute Bayesian iteration budget using iteration_controller
            max_iterations = 20  # Fallback
            iteration_budget = None
            start_time = time.time()
            
            if self.iteration_controller:
                # Get initial epistemic uncertainty if available
                initial_uncertainty = None
                if self.convergence_gate and self.convergence_gate.epistemic_engine:
                    try:
                        from core.reasoning.reasoning_interfaces import ReasoningRequest, ReasoningMode
                        uncertainty_request = ReasoningRequest(
                            query=task.description,
                            mode=ReasoningMode.EPISTEMIC,
                            context={"task_id": task.id}
                        )
                        uncertainty_result = await self.convergence_gate.epistemic_engine.reason(uncertainty_request)
                        initial_uncertainty = uncertainty_result.uncertainty
                        logger.info(f"📊 Initial epistemic uncertainty: {initial_uncertainty:.3f}")
                    except Exception as e:
                        logger.error(f"Failed to compute initial uncertainty — convergence gate has NO baseline signal: {e}", exc_info=True)
                
                # Compute deadline if task has one
                deadline = None
                if hasattr(task, 'deadline') and task.deadline:
                    deadline = task.deadline
                
                # Estimate task complexity (simple heuristic for now)
                complexity = 0.5  # Default medium complexity
                if task.type == TaskType.SECURITY_REMEDIATION:
                    complexity = 0.8
                elif task.type == TaskType.SELF_IMPROVEMENT:
                    complexity = 0.7
                elif task.type == TaskType.RESEARCH:
                    # Research/synthesis tasks require substantial work: multiple web searches,
                    # reading content, synthesising a long-form document, revision cycles.
                    # Treat as high complexity so the iteration budget isn't prematurely capped.
                    complexity = 0.7
                elif task.type == TaskType.SYNTHESIS:
                    complexity = 0.7
                elif task.type == TaskType.ANALYSIS:
                    complexity = 0.3
                
                # Compute Bayesian iteration budget
                iteration_budget = self.iteration_controller.compute_iteration_budget(
                    task=task,
                    initial_uncertainty=initial_uncertainty,
                    deadline=deadline,
                    complexity=complexity
                )
                max_iterations = iteration_budget.max_iterations
                logger.info(f"📊 Bayesian iteration budget: {max_iterations} iterations, {iteration_budget.time_budget_seconds:.1f}s")
            else:
                # Fallback: Calculate dynamic max_iterations based on token budget
                if token_budget:
                    max_iterations = min(30, max(10, 1 + int(token_budget.available_for_generation / 500)))
                else:
                    max_iterations = 20

                # DRIFT ADJUSTMENT: Reduce iterations if completion rate is degrading
                if drift_adjustment and drift_adjustment.get("max_iterations_reduced"):
                    original_max = max_iterations
                    # Reduce by 30-50% depending on failure rate
                    failure_rate = drift_adjustment.get("original_failure_rate", 0.4)
                    reduction_factor = 0.5 if failure_rate > 0.5 else 0.7
                    max_iterations = max(5, int(max_iterations * reduction_factor))
                    logger.warning(
                        f"⚠️ Drift adjustment: max_iterations reduced from {original_max} to {max_iterations} "
                        f"(failure_rate={failure_rate:.1%})"
                    )

            logger.info(f"[ITERATIONS] Max iterations: {max_iterations} (Bayesian budget-based)")

            # Initialize conversation_tokens for first iteration
            # This is needed because iteration 0 skips the recalculation block
            conversation_tokens = 0
            if self.context_manager:
                try:
                    conversation_tokens = await self.context_manager.get_conversation_tokens(
                        [(msg["role"], msg["content"]) for msg in conversation_history]
                    )
                    logger.debug(f"[INIT] Initial conversation tokens: {conversation_tokens}")
                except Exception as e:
                    logger.warning(f"Failed to get initial conversation tokens: {e}")
                    conversation_tokens = len(str(conversation_history).split())  # Rough estimate

            # Initialize epistemic_mutations before loop (will be populated during execution)
            epistemic_mutations = []
            # Canonical belief updates from interpret_tool_output(). These are
            # the authority for outcome quality — see summarize_tool_observations.
            tool_observations = []

            # Track which wrap-up nudges have already been injected this execution.
            # Prevents the same nudge from being re-injected on every iteration once
            # the convergence/temporal gate fires repeatedly.
            # Use a dict to count attempts (allows 2 passes before forcing exit).
            _wrap_up_counts: dict = {}

            # Clear stale convergence checkpoints from any previous execution attempt
            # (including retries).  Stale delta history makes the convergence gate
            # declare convergence on the very first check of a new attempt, which
            # prevents the LLM from doing any useful work.
            if self.convergence_gate:
                self.convergence_gate.reset_task_state(task.id)

            # Agent loop
            _termination_reason = None
            iteration = -1
            for iteration in range(max_iterations):
                logger.info(f"Agent iteration {iteration + 1}/{max_iterations} for task {task.id}")

                # ── Tool failure memory injection (point 6) ───────────────────────────
                # Before each reasoning step inject a compact summary of all
                # tool failures so the LLM sees failure state without re-parsing
                # the full conversation history.
                if iteration > 0 and tool_failure_details:
                    _inj_lines = ["Previous tool failures this task (do not repeat with identical arguments):"]
                    for _inj_name, _inj_d in tool_failure_details.items():
                        _inj_cat = _inj_d.get("category", "?")
                        _inj_cnt = _inj_d.get("count", 0)
                        _inj_sh  = _inj_d.get("short_hint", "")
                        _inj_line = f"  {_inj_cnt}. {_inj_name} → {_inj_cat}"
                        if _inj_sh:
                            _inj_line += f"  |  hint: {_inj_sh}"
                        _inj_lines.append(_inj_line)
                    conversation_history.append({
                        "role": "user",
                        "content": "\n".join(_inj_lines),
                    })

                # Phase 2: IterationController checks resource budgets
                # Phase 1: ConvergenceGate has final authority on convergence
                if self.iteration_controller and iteration_budget and iteration > 0:
                    # Get convergence check for shared epistemic state
                    convergence_check = None
                    if self.convergence_gate:
                        try:
                            convergence_state = {
                                'tool_results': tool_results,
                                'epistemic_mutations': epistemic_mutations,
                                'conversation_history': conversation_history,
                                'execution_ledger': execution_ledger,
                                'iteration': iteration,
                            }
                            elapsed = time.time() - start_time
                            convergence_check = await self.convergence_gate.check_convergence(
                                task=task,
                                iteration=iteration,
                                state=convergence_state,
                                deadline_seconds=iteration_budget.time_budget_seconds,
                                elapsed_seconds=elapsed
                            )
                        except Exception as e:
                            logger.error(f"Failed to get convergence check — iteration stopping logic BROKEN this cycle: {e}", exc_info=True)
                    
                    # When ConvergenceGate reports uncertainty=0.0 but converged=False it means
                    # there are NO unstable regions registered — the Bayesian has no signal at all,
                    # NOT that the task is complete.  Feeding 0.0 into should_continue_iteration
                    # fires a false CONVERGED every iteration (0.0 < 0.2 threshold).
                    # Clamp to a neutral 0.5 in that case so the IterationController sees
                    # "no data yet" rather than "fully resolved".
                    _raw_uncertainty = (
                        convergence_check.epistemic_uncertainty
                        if convergence_check else 0.5
                    )
                    current_uncertainty = (
                        0.5
                        if convergence_check and _raw_uncertainty == 0.0 and not convergence_check.converged
                        else _raw_uncertainty
                    )
                    
                    elapsed = time.time() - start_time

                    # ConvergenceGate has final authority: if it says the
                    # state is a fixpoint (converged=True), respect that even
                    # when the IterationController would otherwise say CONTINUE
                    # (e.g. uncertainty=1.0 stuck at max but delta=0.0 forever).
                    if convergence_check and convergence_check.converged:
                        decision = IterationDecision.CONVERGED
                        reason   = f"ConvergenceGate fixpoint: {convergence_check.reason}"
                        logger.info(
                            f"[CONVERGENCE] ConvergenceGate override: "
                            f"uncertainty={current_uncertainty:.3f} but delta≈0 → treating as CONVERGED"
                        )
                    else:
                        decision, reason = await self.iteration_controller.should_continue_iteration(
                            iteration_budget,
                            current_uncertainty,
                            elapsed
                        )

                    if decision != IterationDecision.CONTINUE:
                        logger.warning(f"🛑 Bayesian iteration stopping: {decision.value} — {reason}")
                        # Remember WHY. The post-loop block is reached by every
                        # `break` as well as by exhausting the range, and it used
                        # to report "Max iterations reached" unconditionally.
                        _termination_reason = f"{decision.value}: {reason}"

                        if decision == IterationDecision.CONVERGED:
                            # IterationController says converged, but ConvergenceGate has final authority
                            if convergence_check and convergence_check.converged:
                                # Guard: require at least 2 successful tool calls before wrapping up.
                                # Epistemic uncertainty can drop to 0.0 after a single tool call
                                # (no unstable regions registered) which triggers premature exit.
                                _wrap_successful = sum(
                                    1 for r in tool_results
                                    if r.get("success") and r.get("tool") not in ("request_tools",)
                                )
                                # For EXECUTION tasks: also require at least one write/patch call.
                                # Reading files alone is NOT sufficient — the upgrade cycle must
                                # have produced at least one code change before we allow wrap-up.
                                _wrap_has_impl = any(
                                    r.get("tool") in ("patch_file", "write_file", "atomic_write_file")
                                    and r.get("success")
                                    for r in tool_results
                                )
                                # Minimum substantive tool calls before early convergence wrap-up.
                                # Keyed to task type — research/design tasks need real investigation.
                                _min_wrap_calls = {
                                    "EXECUTION": 4,
                                    "RESEARCH": 3,
                                    "ANALYSIS": 4,
                                    "SYNTHESIS": 3,
                                }.get(task.type.name if hasattr(task, 'type') else '', 3)
                                # EXECUTION tasks must also have at least one successful patch/write.
                                _needs_impl = (
                                    task.type.name == "EXECUTION" and not _wrap_has_impl
                                )
                                if _wrap_successful < _min_wrap_calls or _needs_impl:
                                    _wrap_remaining = max(0, _min_wrap_calls - _wrap_successful)
                                    # Track consecutive impl=False deferrals for escalation
                                    _impl_defers = _wrap_up_counts.get('_impl_defers', 0)
                                    if _needs_impl:
                                        _impl_defers += 1
                                        _wrap_up_counts['_impl_defers'] = _impl_defers
                                    if _needs_impl and _impl_defers >= 2:
                                        # Escalate: model has read the file, now patch it
                                        _defer_msg = (
                                            f"⛔ PATCH NOW (deferral #{_impl_defers}) — "
                                            "You have the file content in your context from read_file. "
                                            "Call patch_file RIGHT NOW using:\n"
                                            "  old_string: the EXACT text from the most recent read_file "
                                            "output (copy CHARACTER-FOR-CHARACTER from that tool response)\n"
                                            "  new_string: your improved version\n"
                                            "If your patches keep failing, use grep_search to find "
                                            "the right line numbers first, then read_file those lines:\n"
                                            "  grep_search(pattern='function_name', path='<abs_file_path>')\n"
                                            "Any successful patch_file call (even a small improvement) "
                                            "unlocks the task."
                                        )
                                    elif _needs_impl:
                                        _defer_msg = (
                                            "⛔ CONVERGENCE DEFERRED — research complete, now implement.\n"
                                            "TWO-STEP SEQUENCE REQUIRED:\n"
                                            "  STEP 1 (this response): call read_file on the EXACT\n"
                                            "     line range you want to modify. Use line numbers\n"
                                            "     from your grep_search results. Call ONLY read_file.\n"
                                            "  STEP 2 (next response): call patch_file using\n"
                                            "     old_string copied CHARACTER-FOR-CHARACTER from\n"
                                            "     the read_file output you receive in step 1.\n"
                                            "Do NOT guess old_string. Do NOT call grep_search again.\n"
                                            "Call read_file NOW with the exact line numbers."
                                        )
                                    else:
                                        _defer_msg = (
                                            f"Not enough evidence yet — you've only made "
                                            f"{_wrap_successful} successful tool call(s), but "
                                            f"{_min_wrap_calls} are required for a {task.type.name} task. "
                                            f"Make {_wrap_remaining} more tool call(s). "
                                            "Consider: reading a related file, verifying your result, "
                                            "or writing a summary. Do NOT propose completion yet."
                                        )
                                    logger.info(
                                        f"[CONVERGENCE] Formal convergence deferred — "
                                        f"impl={_wrap_has_impl}, calls={_wrap_successful}/{_min_wrap_calls}, "
                                        f"defers={_impl_defers}"
                                    )
                                    execution_ledger.append(
                                        f"[iter{iteration+1}] CONVERGED but deferred "
                                        f"(impl={_wrap_has_impl}, {_wrap_successful}/{_min_wrap_calls} calls, "
                                        f"defers={_impl_defers})"
                                    )
                                    conversation_history.append({
                                        "role": "user",
                                        "content": _defer_msg,
                                    })
                                    # Fall through — don't break, keep iterating
                                else:
                                    logger.info(f"✓ Dual convergence: Bayesian + Formal")
                                    execution_ledger.append(f"[iter{iteration+1}] CONVERGED: budget + constraints")
                                    # ── WRAP-UP: give LLM up to 3 chances to call propose_completion ──
                                    # The convergence wrap-up counter is a ONE-WAY RATCHET once
                                    # ConvergenceGate says converged=True.  Tool calls after a nudge
                                    # are fine (the LLM is still working) but they do NOT reset the
                                    # clock — that was causing infinite reprieves where each tool call
                                    # restarted the 3-nudge window indefinitely.
                                    _cw_count = _wrap_up_counts.get('convergence_wrap_up', 0)
                                    # Check if task has a patch but no code-execution call yet
                                    _has_patch = any(
                                        r.get("tool") in ("patch_file", "write_file", "atomic_write_file")
                                        and r.get("success")
                                        for r in tool_results
                                    )
                                    _has_code_exec = any(
                                        r.get("tool") in ("run_python", "run_shell_command", "execute_command", "run_script")
                                        and r.get("success")
                                        for r in tool_results
                                    )
                                    _needs_verification = (
                                        task.type.name == "EXECUTION"
                                        and _has_patch
                                        and not _has_code_exec
                                    )
                                    # ── Completion-gate guard ──────────────────────────────────────
                                    # Do NOT fire "call propose_completion" nudges while the completion
                                    # gate minimum hasn't been reached yet.  The gate already injects
                                    # its own "do more work" message; adding a contradictory propose
                                    # nudge on top of it causes an infinite propose→block loop.
                                    _cgn_min  = self._min_successful_tool_calls_for_task(task)
                                    _cgn_done = sum(
                                        1 for r in tool_results
                                        if r.get("success") and r.get("tool") not in ("request_tools",)
                                    )
                                    if _cgn_min > 0 and _cgn_done < _cgn_min:
                                        # Gate not cleared — skip ALL propose nudges this iteration.
                                        # The model still has the gate's guidance in conversation_history.
                                        pass
                                    elif _wrap_up_counts.pop('_revision_pending', False):
                                        # Revision cooldown: the previous iteration injected a
                                        # revision message.  Skip the convergence nudge this
                                        # iteration so the model can act on the revision feedback
                                        # before being told to call propose_completion again.
                                        logger.info(
                                            "[CONVERGENCE] Skipping nudge — revision cooldown active"
                                        )
                                    elif _cw_count == 0:
                                        # First nudge: task-type-aware checklist of what's still missing.
                                        _wrap_up_counts['convergence_wrap_up'] = 1
                                        _task_type_nm = task.type.name if hasattr(task, 'type') else ''
                                        _nudge_content = _build_convergence_nudge(
                                            _task_type_nm, 1, tool_results
                                        )
                                        conversation_history.append({
                                            "role": "user",
                                            "content": _nudge_content,
                                        })
                                        execution_ledger.append(
                                            f"[iter{iteration+1}] CONVERGENCE WRAP-UP nudge #1 ({_task_type_nm})"
                                        )
                                        logger.info(
                                            f"[CONVERGENCE] Nudge #1 injected (task_type={_task_type_nm})"
                                        )
                                        # Don't break — let the LLM respond
                                    elif _cw_count == 1:
                                        # Second nudge: escalated, still task-type-aware.
                                        _wrap_up_counts['convergence_wrap_up'] = 2
                                        _task_type_nm = task.type.name if hasattr(task, 'type') else ''
                                        _nudge2_content = _build_convergence_nudge(
                                            _task_type_nm, 2, tool_results
                                        )
                                        conversation_history.append({
                                            "role": "user",
                                            "content": _nudge2_content,
                                        })
                                        execution_ledger.append(
                                            f"[iter{iteration+1}] CONVERGENCE WRAP-UP nudge #2 ({_task_type_nm})"
                                        )
                                        logger.info(
                                            f"[CONVERGENCE] Nudge #2 injected (escalated, task_type={_task_type_nm})"
                                        )
                                        # Don't break — one more chance
                                    elif _cw_count == 2:
                                        # Third nudge: final warning.
                                        _wrap_up_counts['convergence_wrap_up'] = 3
                                        _task_type_nm = task.type.name if hasattr(task, 'type') else ''
                                        _nudge3_content = _build_convergence_nudge(
                                            _task_type_nm, 3, tool_results
                                        )
                                        conversation_history.append({
                                            "role": "user",
                                            "content": _nudge3_content,
                                        })
                                        execution_ledger.append(
                                            f"[iter{iteration+1}] CONVERGENCE WRAP-UP nudge #3 ({_task_type_nm}, final)"
                                        )
                                        logger.info(
                                            f"[CONVERGENCE] Nudge #3 injected (final, task_type={_task_type_nm})"
                                        )
                                        # Don't break — absolute last chance
                                    else:
                                        # Fourth time — but if run_python just passed after
                                        # a previous failure, give one final propose nudge
                                        # instead of breaking (the model fixed the code!).
                                        _run_py_just_passed = any(
                                            r.get("tool") in ("run_python", "run_shell_command")
                                            and r.get("success")
                                            for r in tool_results
                                        )
                                        if _has_patch and _run_py_just_passed:
                                            _wrap_up_counts['convergence_wrap_up'] = 4
                                            conversation_history.append({
                                                "role": "user",
                                                "content": (
                                                    "✅ run_python passed — your fix is verified.\n"
                                                    "NOW call `propose_completion` immediately. No more tool calls."
                                                ),
                                            })
                                            execution_ledger.append(
                                                f"[iter{iteration+1}] CONVERGENCE WRAP-UP nudge #4 — run_python passed, propose now"
                                            )
                                            logger.info(
                                                "[CONVERGENCE] Wrap-up nudge #4 injected — run_python passed, final propose"
                                            )
                                            # One absolute final chance
                                        else:
                                            logger.warning(
                                                "[CONVERGENCE] Wrap-up nudge sent 3 times but LLM did not "
                                                "call propose_completion — forcing exit"
                                            )
                                            execution_ledger.append(
                                                f"[iter{iteration+1}] CONVERGED (no proposal after 3 nudges) — exit"
                                            )
                                            break
                            elif convergence_check:
                                logger.warning(f"⚠️ Budget converged but {convergence_check.state.value} — continuing")
                                execution_ledger.append(f"[iter{iteration+1}] Budget converged, {convergence_check.state.value}")
                            else:
                                execution_ledger.append(f"[iter{iteration+1}] Bayesian convergence: {reason}")
                                break
                        elif decision == IterationDecision.TEMPORAL_LIMIT:
                            # Time budget exhausted — give the LLM ONE final iteration to propose.
                            execution_ledger.append(f"[iter{iteration+1}] Temporal limit: {reason}")
                            _tw_count = _wrap_up_counts.get('temporal_wrap_up', 0)
                            if _tw_count == 0:
                                _wrap_up_counts['temporal_wrap_up'] = 1
                                conversation_history.append({
                                    "role": "user",
                                    "content": (
                                        "⏱️ Time budget exhausted. "
                                        "Call the `propose_completion` tool IMMEDIATELY with your findings. "
                                        "Required: summary, confidence, remaining_risks=[], open_questions=[]. "
                                        "Do NOT produce text — emit the tool call now."
                                    ),
                                })
                                logger.info(
                                    "[TEMPORAL] Wrap-up nudge injected — "
                                    "giving LLM one final iteration to propose completion"
                                )
                                # Don't break — let the LLM respond
                            else:
                                # Already sent; no response — hard exit
                                logger.warning(
                                    "[TEMPORAL] Wrap-up nudge already sent but no proposal — hard exit"
                                )
                                break
                        elif decision == IterationDecision.STAGNANT:
                            # No progress — give the LLM ONE final iteration to propose.
                            execution_ledger.append(f"[iter{iteration+1}] Stagnation detected: {reason}")
                            _sw_count = _wrap_up_counts.get('stagnant_wrap_up', 0)
                            if _sw_count == 0:
                                _wrap_up_counts['stagnant_wrap_up'] = 1
                                conversation_history.append({
                                    "role": "user",
                                    "content": (
                                        "⚠️ No new progress detected. "
                                        "Call the `propose_completion` tool with your current findings. "
                                        "Required: summary, confidence, remaining_risks=[], open_questions=[]. "
                                        "Do NOT produce text — emit the tool call now."
                                    ),
                                })
                                logger.info(
                                    "[STAGNANT] Wrap-up nudge injected — "
                                    "giving LLM one final iteration to propose completion"
                                )
                                # Don't break — let the LLM respond
                            else:
                                logger.warning(
                                    "[STAGNANT] Wrap-up nudge already sent but no proposal — hard exit"
                                )
                                break
                        elif decision == IterationDecision.MAX_BUDGET:
                            # Iteration budget exhausted
                            execution_ledger.append(f"[iter{iteration+1}] Iteration budget exhausted: {reason}")
                            break
                    else:
                        logger.info(f"✓ Bayesian iteration continuing: {reason}")
                    
                    # Risk 2: Track iteration cost
                    iteration_duration = time.time() - (start_time + elapsed)
                    if self.iteration_controller:
                        self.iteration_controller.record_iteration_cost(iteration_duration)

                # RECALCULATE token budget on each iteration to account for growing conversation
                if self.context_manager and iteration > 0:
                    # Get conversation token count — handle tool-role messages
                    def _msg_for_token_count(msg: dict):
                        role = msg.get('role', 'user')
                        # For token counting, 'tool' role maps to 'user' (close enough)
                        if role == 'tool':
                            role = 'user'
                        content = msg.get('content') or ''
                        if role == 'assistant' and msg.get('tool_calls'):
                            # Represent tool calls as compact text for token estimation
                            tc_text = ', '.join(
                                tc.get('function', {}).get('name', '?')
                                for tc in (msg.get('tool_calls') or [])
                                if isinstance(tc, dict)
                            )
                            content = (content + f' [calls: {tc_text}]').strip()
                        return (role, content)

                    conversation_tokens = await self.context_manager.get_conversation_tokens(
                        [_msg_for_token_count(m) for m in conversation_history]
                    )

                    # CHECK IF COMPRESSION NEEDED BEFORE GENERATION (CRITICAL FIX)
                    # Pass tool schema token estimate so the effective budget is accurate.
                    # tool_desc_tokens_est is ~22k for 22 schemas; without accounting for
                    # it the compress threshold is 70% of 32k = 22.9k — already above the
                    # schema overhead alone, so compression never fires before overflow.
                    should_compress = await self.context_manager.should_compress(
                        conversation_tokens,
                        reserved_tokens=tool_desc_tokens_est,
                    )
                    usage_pct = (conversation_tokens / max(self.context_manager.n_ctx - tool_desc_tokens_est, 1)) * 100
                    logger.debug(
                        f"[COMPRESSION CHECK] Tokens: {conversation_tokens}/{self.context_manager.n_ctx - tool_desc_tokens_est} "
                        f"effective ({self.context_manager.n_ctx} - {tool_desc_tokens_est} schemas) "
                        f"({usage_pct:.1f}%), should_compress={should_compress}"
                    )
                    if should_compress:
                        logger.info("[COMPRESSION] Compressing BEFORE generation to prevent budget collapse")
                        await self.context_manager.track_turn()

                        # Flatten to (role, content) for the 8B compression model.
                        # Tool-role messages become readable user-side context.
                        messages_to_compress = []
                        for msg in conversation_history:
                            role = msg.get('role', 'user')
                            content = msg.get('content') or ''
                            if role == 'tool':
                                tool_name = msg.get('name', 'tool')
                                content = f"[{tool_name} result]: {content}"
                                role = 'user'
                            elif role == 'assistant' and msg.get('tool_calls'):
                                tc_names = ', '.join(
                                    tc.get('function', {}).get('name', '?')
                                    for tc in (msg.get('tool_calls') or [])
                                    if isinstance(tc, dict)
                                )
                                if content:
                                    content = f"{content}\n[Called tools: {tc_names}]"
                                else:
                                    content = f"[Called tools: {tc_names}]"
                            messages_to_compress.append((role, content))

                        compressed_summary = await self.context_manager.compress_and_store(
                            messages=messages_to_compress,
                            task_id=task.id
                        )

                        if compressed_summary:
                            preserved_count = self.context_manager.preserve_recent
                            recent_messages = conversation_history[-preserved_count:]

                            summary_msg = {
                                "role": "system",
                                "content": (
                                    f"[CONVERSATION HISTORY COMPRESSED]\n"
                                    f"Compressed {len(messages_to_compress)} earlier messages into summary below.\n"
                                    f"This summary preserves all key decisions, findings, and context.\n\n"
                                    f"{compressed_summary}\n\n"
                                    f"[END SUMMARY - Recent messages follow]"
                                )
                            }

                            # CRITICAL: Do NOT preserve conversation_history[1] (initial
                            # user message) — it contains the raw memories + full tool list
                            # which bloats the context.  The 8B compression summary already
                            # captured all relevant context from those messages.  This mirrors
                            # how Claude/GPT work: old context (including initial setup) gets
                            # absorbed into the summary, only recent messages are kept raw.
                            conversation_history = [
                                conversation_history[0],  # Keep system prompt
                                summary_msg              # Compressed summary replaces everything
                            ] + recent_messages

                            # ── Ledger re-injection (Risk 3 mitigation) ──────────
                            # The 8B compressor abstracts away fine-grained tool
                            # history: which calls failed, what errors occurred, which
                            # hard gates fired.  Without this, the agent loses the
                            # causal chain after every compression, which is the primary
                            # driver of completion drift.  The ledger is NOT compressed —
                            # it is re-injected as a fresh system message so it is always
                            # present verbatim at the front of the context.
                            if execution_ledger:
                                ledger_lines = execution_ledger[-EXECUTION_LEDGER_MAX_ENTRIES:]
                                ledger_msg = {
                                    "role": "system",
                                    "content": (
                                        "[EXECUTION HISTORY — PRESERVED ACROSS COMPRESSION]\n"
                                        "This is an exact log of what has been tried, succeeded, "
                                        "and failed. Do NOT repeat failed approaches.\n\n"
                                        + "\n".join(ledger_lines)
                                    ),
                                }
                                # Insert between system prompt and compressed summary
                                conversation_history = [
                                    conversation_history[0],  # system prompt
                                    ledger_msg,               # immutable ledger
                                ] + conversation_history[1:] # summary + recent

                            logger.info(
                                f"[COMPRESSION] ✓ Compressed: {len(messages_to_compress)} → {len(conversation_history)} messages"
                            )

                            # Recalculate tokens after compression
                            conversation_tokens = await self.context_manager.get_conversation_tokens(
                                [_msg_for_token_count(m) for m in conversation_history]
                            )

                    # Recalculate available budget
                    # NOTE: conversation_tokens includes everything (system + initial user message with tools + conversation)
                    # So we DON'T subtract them again - that would be double-counting!
                    available_for_generation = max(100, (
                        self.context_manager.n_ctx
                        - conversation_tokens  # This already includes everything
                        - self.context_manager.safety_margin
                    ))

                    logger.debug(
                        f"[TOKEN BUDGET] Iteration {iteration + 1}: conversation={conversation_tokens}, "
                        f"available={available_for_generation}"
                    )

                    # Update budget with new calculation
                    # Note: system/tool tokens are 0 now since they're already in conversation_tokens
                    from core.reasoning.context_manager import TokenBudget
                    token_budget = TokenBudget(
                        total_context_window=self.context_manager.n_ctx,
                        system_prompt_tokens=0,  # Already counted in conversation_tokens
                        tool_description_tokens=0,  # Already counted in conversation_tokens
                        safety_margin=self.context_manager.safety_margin,
                        available_for_generation=available_for_generation,
                        available_for_conversation=available_for_generation
                    )

                # Use dynamic max_tokens based on task type and throughput
                # This prevents requesting 4096 tokens when 300 would suffice,
                # reducing timeout risk and improving overall throughput.
                max_tokens = 1500  # Default fallback
                try:
                    if self.context_manager and token_budget:
                        from core.services.unified_llm import compute_dynamic_max_tokens, get_llm_service
                        
                        # Get speed tracker from LLM service for throughput-based adjustment
                        llm_service = get_llm_service()
                        speed_tracker = llm_service.speed_tracker if llm_service else None
                        
                        # Estimate prompt tokens for dynamic calculation
                        est_prompt_tokens = conversation_tokens if conversation_tokens > 0 else 500
                        
                        # Compute dynamic max_tokens based on task type
                        task_type_str = task.type.value if hasattr(task.type, 'value') else str(task.type)
                        dynamic_max = compute_dynamic_max_tokens(
                            prompt_tokens=est_prompt_tokens,
                            task_type=task_type_str,
                            tracker=speed_tracker,
                            hard_cap=token_budget.available_for_generation,
                        )
                        
                        max_tokens = dynamic_max
                        logger.debug(f"Dynamic max_tokens: {max_tokens} (task_type={task_type_str}, prompt_tokens={est_prompt_tokens})")
                    else:
                        logger.debug(f"Context manager unavailable, using fallback max_tokens={max_tokens}")
                except Exception as e:
                    logger.error(f"Failed to compute dynamic max_tokens — LLM using fallback={max_tokens}: {e}", exc_info=True)

                # Call LLM directly with native tool calling — no JSON parsing needed.
                # The model sees the full conversation history as proper turns and
                # returns structured tool_calls instead of JSON embedded in text.
                logger.debug(
                    f"[Iteration {iteration + 1}/{max_iterations}] Thinking (max_tokens={max_tokens})"
                )

                # ── Proactive wrap-up nudge at end of iteration budget ─────────────
                # Injected BEFORE the LLM call so the model sees it as the latest
                # user turn and is incentivised to call propose_completion.
                # This is a belt-and-suspenders complement to the convergence/temporal
                # gate nudges above.  Uses _wrap_up_flags to inject at most once.
                _iters_remaining = max_iterations - 1 - iteration

                # ── Document-expansion nudge (RESEARCH / SYNTHESIS / ANALYSIS) ─────
                # After iter 8, if the latest written document is still small
                # (< 12 000 bytes), section-by-section patches will never reach the
                # minimum word count before the budget runs out.  Tell the model to
                # do a single full rewrite using all the data already gathered.
                _task_nm_for_doc = task.type.name if hasattr(task, 'type') else ''
                if (
                    _task_nm_for_doc in ("RESEARCH", "SYNTHESIS", "ANALYSIS")
                    and iteration >= 5  # earlier: synthesis gate fires at 5 retrievals
                    and 'doc_expansion_nudge' not in _wrap_up_counts
                ):
                    import re as _re_doc
                    _latest_doc_bytes = 0
                    for _tr in reversed(tool_results):
                        if _tr.get("tool") in ("write_file", "atomic_write_file", "patch_file"):
                            _out_str = str(_tr.get("output", ""))
                            # bytes_written for write_file, bytes_after for patch_file
                            _m = _re_doc.search(r'bytes_(?:written|after)[\'"\s:]+(\d+)', _out_str)
                            if _m:
                                _latest_doc_bytes = int(_m.group(1))
                            break
                    _has_any_write = any(
                        _tr.get("tool") in ("write_file", "atomic_write_file", "patch_file")
                        and _tr.get("success")
                        for _tr in tool_results
                    )
                    if _latest_doc_bytes == 0 and not _has_any_write:
                        # No document has been written at all — fire a hard "write now" nudge.
                        _wrap_up_counts['doc_expansion_nudge'] = 1
                        conversation_history.append({
                            "role": "user",
                            "content": (
                                f"⚠️ NO OUTPUT DOCUMENT — you have completed {iteration + 1} iterations "
                                "but have not written any output file yet.\n\n"
                                "Verification CANNOT pass without a written document. "
                                "You have gathered sufficient research data. "
                                "Call `write_file` RIGHT NOW with the full absolute iCloud path to write "
                                "a complete document using ALL the data you have already gathered. "
                                "Do NOT call `propose_completion` before calling `write_file`."
                            ),
                        })
                        execution_ledger.append(
                            f"[iter{iteration+1}] NO_DOC nudge — no write_file after {iteration+1} iters"
                        )
                        logger.info(
                            "[WRAP-UP] No-document nudge at iter %d/%d (task=%s)",
                            iteration + 1, max_iterations, _task_nm_for_doc
                        )
                    elif _latest_doc_bytes > 0 and _latest_doc_bytes < 12000:
                        _wrap_up_counts['doc_expansion_nudge'] = 1
                        conversation_history.append({
                            "role": "user",
                            "content": (
                                f"⚠️ DOCUMENT TOO SHORT — your output file is only ~{_latest_doc_bytes} bytes "
                                f"(≈{_latest_doc_bytes // 5} words). "
                                "Verification will FAIL — a substantive document requires at least 2 000 words "
                                "of prose.\n\n"
                                "Stop patching. Call `write_file` to replace the entire document with a "
                                "complete, fully-written report using ALL the data you have already gathered. "
                                "Every section must contain real paragraphs — not bullet lists or placeholders."
                            ),
                        })
                        execution_ledger.append(
                            f"[iter{iteration+1}] DOC_EXPANSION nudge ({_latest_doc_bytes} bytes)"
                        )
                        logger.info(
                            "[WRAP-UP] Doc-expansion nudge at iter %d/%d "
                            "(doc=%d bytes, task=%s)",
                            iteration + 1, max_iterations, _latest_doc_bytes, _task_nm_for_doc
                        )
                if _iters_remaining == 0 and 'final_iter_nudge' not in _wrap_up_counts:
                    _wrap_up_counts['final_iter_nudge'] = 1
                    conversation_history.append({
                        "role": "user",
                        "content": (
                            f"⚠️ FINAL ITERATION ({iteration + 1}/{max_iterations}). "
                            "There are NO more iterations after this. "
                            "Call the `propose_completion` tool NOW with your complete findings. "
                            "Required: summary (string), confidence (0.0-1.0), "
                            "remaining_risks (empty []), open_questions (empty []), key_findings (string). "
                            "Do NOT produce text — emit the tool call."
                        ),
                    })
                    execution_ledger.append(
                        f"[iter{iteration+1}] FINAL ITER nudge injected"
                    )
                    logger.info(f"[WRAP-UP] Final-iteration nudge injected at iter {iteration + 1}/{max_iterations}")
                elif _iters_remaining == 2 and 'output_doc_nudge' not in _wrap_up_counts:
                    _wrap_up_counts['output_doc_nudge'] = 1
                    import os as _os_nudge
                    _icloud_nudge = _os_nudge.path.expanduser(
                        "~/Library/Mobile Documents/com~apple~CloudDocs/output-file"
                    )
                    import datetime as _dt_nudge
                    _nudge_stamp = _dt_nudge.datetime.now().strftime("%Y-%m-%d_%H%M")
                    conversation_history.append({
                        "role": "user",
                        "content": (
                            f"📝 OUTPUT DOCUMENT REQUIRED — {_iters_remaining} iterations remaining.\n\n"
                            "Before you can call `propose_completion`, you MUST write a professional "
                            "Markdown report to the iCloud output directory. This is a hard requirement — "
                            "propose_completion will be REJECTED if no file is written there.\n\n"
                            f"**Write your report NOW to:**\n"
                            f"  `{_icloud_nudge}/<type>/{_nudge_stamp}_<short-slug>.md`\n\n"
                            "Choose the matching sub-directory:\n"
                            "  analysis/  research/  planning/  optimization/  "
                            "self-improvement/  security/  learning/  general/\n\n"
                            "Use `write_file` with `create_dirs=True`. "
                            "Include: executive summary, key findings, methodology, and outputs. "
                            "Then call `propose_completion` on the final iteration."
                        ),
                    })
                    execution_ledger.append(
                        f"[iter{iteration+1}] OUTPUT DOC nudge injected"
                    )
                    logger.info(f"[WRAP-UP] Output-doc nudge injected at iter {iteration + 1}/{max_iterations}")
                elif _iters_remaining == 1 and 'penultimate_nudge' not in _wrap_up_counts:
                    _wrap_up_counts['penultimate_nudge'] = 1
                    conversation_history.append({
                        "role": "user",
                        "content": (
                            f"📋 You have {_iters_remaining} iteration(s) remaining "
                            f"(this is iteration {iteration + 1}/{max_iterations}). "
                            "On the NEXT (final) iteration you MUST call `propose_completion`. "
                            "If you have not yet written your output document to iCloud, do it NOW "
                            "before the final iteration. Then call `propose_completion`."
                        ),
                    })
                    execution_ledger.append(
                        f"[iter{iteration+1}] PENULTIMATE nudge injected"
                    )
                    logger.info(f"[WRAP-UP] Penultimate nudge injected at iter {iteration + 1}/{max_iterations}")

                llm_response = await self.llm.generate_with_messages(
                    messages=conversation_history,
                    tools=tool_schemas,
                    max_tokens=max_tokens,
                )

                content = llm_response.get("content", "")
                native_tool_calls = llm_response.get("tool_calls")  # list or None
                finish_reason = llm_response.get("finish_reason", "stop")

                # ── Shadow mode: log model reasoning text ──────────────────────────
                import os as _shadow_os
                if _shadow_os.environ.get("TORIN_SHADOW_MODE"):
                    _tc_count = len(native_tool_calls) if native_tool_calls else 0
                    if content and content.strip():
                        logger.info(
                            "[SHADOW][iter%s] MODEL REASONING (%d chars):\n%s",
                            iteration + 1, len(content), content[:2000]
                        )
                    else:
                        logger.info(
                            "[SHADOW][iter%s] MODEL: no text — %d tool call(s) only",
                            iteration + 1, _tc_count
                        )
                    if native_tool_calls:
                        for _stc in native_tool_calls:
                            _sfn = _stc.get("function", {}) if isinstance(_stc, dict) else {}
                            _sname = _sfn.get("name", "?") if isinstance(_sfn, dict) else "?"
                            _sargs = str(_sfn.get("arguments", ""))[:200] if isinstance(_sfn, dict) else ""
                            logger.info(
                                "[SHADOW][iter%s]   → tool_call: %s(%s)",
                                iteration + 1, _sname, _sargs
                            )

                logger.debug(
                    "[Iteration %s] Response: finish_reason=%s, %s chars, %s tool calls",
                    iteration + 1,
                    finish_reason,
                    len(content),
                    (len(native_tool_calls) if native_tool_calls else 0),
                )
                if content and logger.isEnabledFor(logging.DEBUG):
                    logger.debug("[Iteration %s] LLM content (truncated): %s", iteration + 1, content[:2000])

                # Detect inference timeout
                if content.strip() in ("[INFERENCE TIMEOUT]", "[VISION INFERENCE TIMEOUT]"):
                    logger.error(f"[Iteration {iteration + 1}] Inference timed out — aborting")
                    return {
                        'success': False,
                        'error': 'Inference timeout',
                        'task_id': task.id,
                        'tool_results': tool_results,
                        'iterations': iteration + 1,
                    }

                # Add assistant turn (include tool_calls metadata if present)
                assistant_msg: dict = {"role": "assistant", "content": content}
                if native_tool_calls:
                    assistant_msg["tool_calls"] = native_tool_calls
                conversation_history.append(assistant_msg)

                # ── Detect propose_completion written as text/code-block (not as tool call) ──
                # The model sometimes writes propose_completion inside a markdown code block
                # instead of emitting it as a native tool call.  Detect this and synthesise
                # a minimal tool call so the completion path fires correctly.
                if not native_tool_calls and content and "propose_completion" in content:
                    import re as _pc_re
                    # Match both ```propose_completion and plain propose_completion( invocations
                    _pc_match = _pc_re.search(
                        r'propose_completion\s*\(\s*\{?[^)]*\}?\s*\)',
                        content, _pc_re.DOTALL
                    )
                    if _pc_match or "propose_completion" in content:
                        logger.warning(
                            f"[iter{iteration+1}] Model wrote propose_completion as TEXT — "
                            "synthesising tool call to trigger completion path"
                        )
                        execution_ledger.append(
                            f"[iter{iteration+1}] ⚠️ propose_completion written as text — auto-converted to tool call"
                        )
                        # Build a minimal synthetic tool call from the text content
                        _synth_tc = {
                            "id": f"synth_propose_{iteration}",
                            "type": "function",
                            "function": {
                                "name": "propose_completion",
                                "arguments": json.dumps({
                                    "summary": content[:800],
                                    "confidence": 0.7,
                                    "remaining_risks": [],
                                    "open_questions": [],
                                    "key_findings": content[:400],
                                    "files_created": [],
                                    "files_modified": [],
                                }),
                            },
                        }
                        native_tool_calls = [_synth_tc]

                # Separate propose_completion from regular tool calls
                completion_tc = None
                regular_tool_calls = []
                if native_tool_calls:
                    for tc in native_tool_calls:
                        func = tc.get("function", {}) if isinstance(tc, dict) else {}
                        name = func.get("name", "") if isinstance(func, dict) else ""
                        if name == "propose_completion":
                            completion_tc = tc
                        else:
                            regular_tool_calls.append(tc)

                # ====================================================================
                # COMPLETION PROTOCOL: LLM proposes via tool call, System verifies
                # ====================================================================
                if completion_tc is not None:
                    logger.info(f"📋 Task {task.id} proposing completion via tool call - initiating verification")

                    # ── Execute regular tool calls first (e.g. write_file) ───────────
                    # If the model calls write_file + propose_completion in the same
                    # batch, execute write_file BEFORE running the completion gate so
                    # that the written artifact exists when verification checks it.
                    if regular_tool_calls:
                        logger.info(
                            f"[COMPLETION] Executing {len(regular_tool_calls)} regular tool call(s) "
                            f"before completion verification"
                        )
                        for _pre_tc in regular_tool_calls:
                            _pre_func = _pre_tc.get("function", {}) if isinstance(_pre_tc, dict) else {}
                            _pre_name = _pre_func.get("name", "") if isinstance(_pre_func, dict) else ""
                            _pre_args = _pre_func.get("arguments", {}) if isinstance(_pre_func, dict) else {}
                            if isinstance(_pre_args, str):
                                try:
                                    import json as _j; _pre_args = _j.loads(_pre_args)
                                except Exception:
                                    _pre_args = {}
                            try:
                                _pre_result = await self.tool_registry.execute_tool(_pre_name, _pre_args)
                                _pre_success = _pre_result.get("success", True) if isinstance(_pre_result, dict) else True
                                _pre_output = _pre_result.get("output", _pre_result) if isinstance(_pre_result, dict) else _pre_result
                                try:
                                    from core.reasoning.epistemic_engine import get_epistemic_engine
                                    _pre_obs = get_epistemic_engine().interpret_tool_output(
                                        _pre_name, _pre_args, _pre_output
                                    )
                                except Exception:
                                    _pre_obs = []
                                tool_results.append(make_tool_record(
                                    tool=_pre_name,
                                    parameters=_pre_args,
                                    success=_pre_success,
                                    output_display=_pre_output,
                                    observation=_pre_obs,
                                ))
                                logger.info(
                                    f"[COMPLETION-PRE] {_pre_name} executed (success={_pre_success})"
                                )
                            except Exception as _pre_exc:
                                logger.warning(
                                    f"[COMPLETION-PRE] {_pre_name} failed: {_pre_exc}"
                                )
                        # Clear so the regular tool path below doesn't re-execute them
                        regular_tool_calls = []

                    # ── Convergence Gate: Formal verification (final authority) ──
                    if self.convergence_gate:
                        logger.info(f"🔬 Running formal convergence check (iteration {iteration + 1})...")
                        
                        convergence_state = {
                            'tool_results': tool_results,
                            'epistemic_mutations': epistemic_mutations,
                            'conversation_history': conversation_history,
                            'execution_ledger': execution_ledger,
                            'iteration': iteration,
                        }
                        
                        convergence_result = await self.convergence_gate.check_convergence(
                            task=task,
                            iteration=iteration,
                            state=convergence_state
                        )
                        
                        if not convergence_result.converged:
                            # CEGAR: Feed structured proof failure back into LLM
                            structured_feedback = {
                                "verification_failed": True,
                                "convergence_state": convergence_result.state.value,
                                "reason": convergence_result.reason,
                                "failed_invariants": convergence_result.failed_invariants_structured,
                                "counterexample_state": convergence_result.counterexample_state,
                                "delta_diagnostic": convergence_result.delta_diagnostic,
                                "epistemic_decomposition": convergence_result.epistemic_decomposition,
                            }
                            
                            # Human-readable + machine-parseable feedback
                            convergence_feedback = (
                                f"⚠️ Formal convergence verification FAILED\n\n"
                                f"**Convergence State:** {convergence_result.state.value}\n"
                                f"**Reason:** {convergence_result.reason}\n\n"
                            )
                            
                            if convergence_result.failed_invariants_structured:
                                convergence_feedback += "**Failed Invariants (Structured):**\n```json\n"
                                convergence_feedback += json.dumps(convergence_result.failed_invariants_structured, indent=2)
                                convergence_feedback += "\n```\n\n"
                            
                            if convergence_result.counterexample_state:
                                convergence_feedback += "**Counterexample State (Z3 Model):**\n```json\n"
                                convergence_feedback += json.dumps(convergence_result.counterexample_state, indent=2)
                                convergence_feedback += "\n```\n\n"
                                convergence_feedback += "This is a concrete state that violates your goal. Analyze it and revise your plan.\n\n"
                            
                            if convergence_result.delta_diagnostic:
                                convergence_feedback += "**State Delta Diagnostic:**\n```json\n"
                                convergence_feedback += json.dumps(convergence_result.delta_diagnostic, indent=2)
                                convergence_feedback += "\n```\n\n"
                            
                            if convergence_result.epistemic_decomposition:
                                convergence_feedback += "**Uncertainty Decomposition:**\n```json\n"
                                convergence_feedback += json.dumps(convergence_result.epistemic_decomposition, indent=2)
                                convergence_feedback += "\n```\n\n"
                                convergence_feedback += "Focus on reducing the highest uncertainty components.\n\n"
                            
                            # Fallback to string invariants if structured not available
                            if not convergence_result.failed_invariants_structured and convergence_result.violated_invariants:
                                convergence_feedback += (
                                    f"Violated Invariants:\n"
                                    + "\n".join(f"  - {inv}" for inv in convergence_result.violated_invariants)
                                    + "\n\n"
                                )
                                # Per-invariant actionable guidance so the model knows what to DO
                                _violated_set = set(convergence_result.violated_invariants or [])
                                if "security_finding_resolved" in _violated_set:
                                    convergence_feedback += (
                                        "**Action required for `security_finding_resolved`:**\n"
                                        "The security audit system still considers this finding open. "
                                        "You must take a concrete action to resolve it:\n"
                                        "  (a) Use `write_file` to write a remediation note or patch to the output directory, OR\n"
                                        "  (b) Use `run_command` to apply the fix directly (e.g. update a config, rotate a key), OR\n"
                                        "  (c) If the finding is a false positive or already fixed, use `write_file` to document this "
                                        "with evidence, then propose completion pointing to that document.\n"
                                        "Do NOT just call `read_file` again — that cannot resolve a security finding.\n\n"
                                    )
                                if "output_document" in _violated_set:
                                    convergence_feedback += (
                                        "**Action required for `output_document`:**\n"
                                        "You must write a Markdown report with your findings to the output directory. "
                                        "Use `write_file` with path under `store/outputs/` before proposing completion.\n\n"
                                    )
                            
                            convergence_feedback += (
                                "Refine your approach based on the structured feedback above. "
                                "Propose completion only after formal verification passes."
                            )
                            
                            execution_ledger.append(
                                f"[iter{iteration+1}] propose_completion BLOCKED by convergence gate "
                                f"({convergence_result.state.value})"
                            )
                            conversation_history.append({"role": "user", "content": convergence_feedback})
                            
                            logger.warning(
                                f"[CONVERGENCE GATE] Completion blocked at iter {iteration+1}: "
                                f"{convergence_result.state.value} — {convergence_result.reason}"
                            )
                            continue  # CEGAR loop: refine and retry
                        
                        # Convergence verified — allow completion proposal to proceed
                        logger.info(
                            f"✓ Convergence gate PASSED: constraints satisfied, "
                            f"uncertainty={convergence_result.epistemic_uncertainty:.3f}, "
                            f"delta={convergence_result.state_delta:.4f}"
                        )
                    
                    # ── Risk 1: Premature completion gate ────────────────────────────
                    # Look up the per-type minimum; 0 means the gate is bypassed and
                    # the verifier alone decides quality.  Only block when the agent
                    # proposes completion before reaching that floor.
                    _min_calls = self._min_successful_tool_calls_for_task(task)
                    _successful_calls = sum(
                        1 for r in tool_results
                        if r.get("success") and r.get("tool") not in ("request_tools",)
                    )
                    if _min_calls > 0 and _successful_calls < _min_calls:
                        _remaining = _min_calls - _successful_calls
                        _tools_used = list({r.get('tool') for r in tool_results if r.get('success')})

                        # Detect propose→block→propose loop: model proposed again with no new tool calls
                        _last_blocked_at = _wrap_up_counts.get('_last_premature_calls', -1)
                        _premature_streak = _wrap_up_counts.get('_premature_streak', 0)
                        if _last_blocked_at == _successful_calls:
                            _premature_streak += 1
                        else:
                            _premature_streak = 1  # reset streak on any new tool call
                        _wrap_up_counts['_last_premature_calls'] = _successful_calls
                        _wrap_up_counts['_premature_streak'] = _premature_streak

                        # Check whether any write/patch was made — useful for EXECUTION phase guidance
                        _has_implementation = any(
                            r.get("tool") in ("patch_file", "write_file", "atomic_write_file")
                            and r.get("success")
                            for r in tool_results
                        )

                        if _premature_streak >= 2:
                            # Model is in a propose→block→propose loop — be much more forceful
                            if task.type.name == "EXECUTION" and not _has_implementation:
                                _gate_reason = (
                                    f"⛔ PHASE GATE VIOLATION — you have called `propose_completion` {_premature_streak} times "
                                    "but you have NOT written or patched any file yet. "
                                    "You are still in Phase 1-2 (research). "
                                    "DO THIS NOW in a single response — emit BOTH tool calls together:\n"
                                    "  STEP 1: read_file with the exact absolute path and line range "
                                    "(start_line, end_line) of the section you want to modify.\n"
                                    "  STEP 2: patch_file with old_string copied VERBATIM from STEP 1 "
                                    "and new_string with your improvement.\n"
                                    "You CAN emit multiple tool calls in one response. "
                                    "Do NOT call propose_completion. Do NOT produce text only. "
                                    "Emit read_file + patch_file TOGETHER right now."
                                )
                            else:
                                _loop_task_hint = {
                                    "EXECUTION": "patch_file to apply your code change",
                                    "RESEARCH": "search_files or read_file on an unexplored path",
                                    "ANALYSIS": "read_file or run_python to inspect the data",
                                    "SYNTHESIS": "write_file to produce your output document",
                                    "SECURITY_REMEDIATION": "write_file to document the fix or run_command to apply it",
                                }.get(task.type.name, "read_file or search_files")
                                _gate_reason = (
                                    f"⛔ LOOP DETECTED — you have called `propose_completion` {_premature_streak} times "
                                    f"in a row without doing any new work (still at {_successful_calls}/{_min_calls} tool calls). "
                                    f"You are NOT allowed to call `propose_completion` again until you have made at least "
                                    f"{_remaining} more successful tool call(s). "
                                    f"Right now you must call: {_loop_task_hint}. "
                                    "Do NOT produce text, do NOT call propose_completion — emit a different tool call."
                                )
                        else:
                            if task.type.name == "EXECUTION" and not _has_implementation:
                                _gate_reason = (
                                    "⛔ IMPLEMENTATION MISSING — you are proposing completion but you have only done "
                                    "research (read_file / search_files). You have NOT called patch_file or write_file. "
                                    "This is an 8-phase self-upgrade task. You are currently in Phase 1-2. "
                                    "Move to Phase 3 (DESIGN): decide exactly what to change and in which file. "
                                    "Then Phase 4 (IMPLEMENT): call read_file on the exact lines, then call "
                                    "patch_file with old_string copied verbatim from that read output. "
                                    "Do NOT call propose_completion until patch_file succeeds at least once."
                                )
                            else:
                                _gate_reason = (
                                    f"Completion proposal rejected — {task.type.name} tasks require "
                                    f"at least {_min_calls} successful tool call(s) before proposing "
                                    f"completion (completed: {_successful_calls}/{_min_calls}, "
                                    f"tools used so far: {_tools_used}). "
                                    f"You still need {_remaining} more tool call(s). "
                                    "Look at what you have not checked yet: did you read all relevant files? "
                                    "Did you verify your output? Did you write a result? "
                                    "Call the next logical tool — do NOT repeat what you already did."
                                )
                        execution_ledger.append(
                            f"[iter{iteration+1}] propose_completion BLOCKED "
                            f"({_successful_calls}/{_min_calls} required for {task.type.name})"
                        )
                        conversation_history.append({"role": "user", "content": _gate_reason})
                        logger.warning(
                            f"[COMPLETION GATE] Premature proposal at iter {iteration+1} suppressed "
                            f"({_successful_calls} < {_min_calls} for {task.type.name})"
                        )
                        # Reset stagnation counter — the model IS working, it just can't
                        # complete yet. Without this, the stagnant hard-exit fires on the
                        # very next iteration because _wrap_up_counts['stagnant_wrap_up']==1.
                        _wrap_up_counts['stagnant_wrap_up'] = 0
                        # Also reset convergence wrap-up: the gate just sent a "do more work"
                        # message; the convergence nudge must NOT immediately fire "call
                        # propose_completion" on the very next iteration — that creates a
                        # contradictory double-message loop.  The counter is reset here so the
                        # model gets a clean "converge → nudge #1" cycle AFTER it does the work.
                        _wrap_up_counts['convergence_wrap_up'] = 0
                        continue  # Back to agent loop — force more work

                    # ── Risk 1.5: Deliverable contract pre-check ─────────────────────
                    # Reject immediately if the proposal declares no deliverables at all.
                    # This is a contract violation — propose_completion requires either
                    # files_created (write_file tasks) or files_modified (patch_file tasks).
                    # Check the proposal arguments directly before any disk I/O.
                    _contract_fc: list = []
                    _contract_fm: list = []
                    try:
                        _cpf = completion_tc.get("function", {}) if isinstance(completion_tc, dict) else {}
                        _cpa = _cpf.get("arguments", {}) if isinstance(_cpf, dict) else {}
                        if isinstance(_cpa, str):
                            _cpa = json.loads(_cpa)
                        _contract_fc = _cpa.get("files_created", []) or []
                        _contract_fm = _cpa.get("files_modified", []) or []
                    except Exception:
                        pass
                    _has_any_declared_deliverable = bool(_contract_fc or _contract_fm)
                    # Also check whether any write_file/patch_file succeeded this run
                    _write_succeeded = any(
                        r.get("tool") in ("write_file", "patch_file") and r.get("success")
                        for r in tool_results
                    )
                    if not _has_any_declared_deliverable and not _write_succeeded:
                        _contract_msg = (
                            "⛔ CONTRACT VIOLATION — propose_completion rejected.\n\n"
                            "You called propose_completion without any deliverables:\n"
                            "  • `files_created` is empty\n"
                            "  • `files_modified` is empty\n"
                            "  • No successful `write_file` or `patch_file` call this task\n\n"
                            "propose_completion is NOT a status update. It is a FINAL SUBMISSION. "
                            "You cannot submit until you have actually produced output.\n\n"
                            "What you must do RIGHT NOW:\n"
                            "  1. Call `write_file` to write your findings as a Markdown document\n"
                            f"     Path: ~/Library/Mobile Documents/com~apple~CloudDocs/output-file/<type>/\n"
                            "  2. Then call `propose_completion` with that path in `files_created`\n\n"
                            "Do not call propose_completion again until step 1 is done."
                        )
                        execution_ledger.append(
                            f"[iter{iteration+1}] propose_completion BLOCKED — contract violation (no deliverables declared)"
                        )
                        conversation_history.append({"role": "user", "content": _contract_msg})
                        logger.warning(
                            f"[CONTRACT GATE] Completion blocked at iter {iteration+1} — "
                            f"no deliverables in proposal and no write_file/patch_file succeeded"
                        )
                        if iteration + 1 >= max_iterations:
                            max_iterations += 1
                        _wrap_up_counts['convergence_wrap_up'] = 0
                        continue

                    # ── Risk 2: Output document gate ─────────────────────────────────
                    # Every substantive task MUST write a Markdown report to the iCloud
                    # output directory before completion is accepted.  Check that at
                    # least one write_file tool call succeeded against that path, OR
                    # that files_created in the proposal contains an output-file path.
                    import os as _os2
                    _icloud_root = _os2.path.expanduser(
                        "~/Library/Mobile Documents/com~apple~CloudDocs/output-file"
                    )
                    # Collect all file paths written by write_file tool calls this task
                    # NOTE: tool_results stores input args under "parameters" key
                    _files_written = set()
                    for _tr in tool_results:
                        if _tr.get("tool") == "write_file" and _tr.get("success"):
                            # write_file uses 'file_path' parameter (not 'path') — check both for safety
                            _path_arg = (
                                _tr.get("parameters", {}).get("file_path", "")
                                or _tr.get("parameters", {}).get("path", "")
                            )
                            if _path_arg:
                                _files_written.add(_path_arg)

                    # Also accept paths declared in the propose_completion files_created field
                    _proposed_files = []
                    try:
                        _prop_func = completion_tc.get("function", {}) if isinstance(completion_tc, dict) else {}
                        _prop_args = _prop_func.get("arguments", {}) if isinstance(_prop_func, dict) else {}
                        if isinstance(_prop_args, str):
                            _prop_args = json.loads(_prop_args)
                        _proposed_files = _prop_args.get("files_created", []) or []
                    except Exception:
                        _proposed_files = []
                    _files_written.update(_proposed_files)

                    # Check if any written path is under the iCloud output root.
                    # Normalise both sides: expanduser + realpath so that paths
                    # stored with ~ or with symlinks still match.
                    import os as _os3
                    _icloud_root_real = _os3.path.realpath(_icloud_root)
                    _has_output_doc = any(
                        _os3.path.realpath(_os3.path.expanduser(p)).startswith(_icloud_root_real)
                        or _os3.path.expanduser(p).startswith(_icloud_root)
                        for p in _files_written
                    )

                    # EXECUTION tasks: a successful patch_file IS the deliverable.
                    # Bypass the iCloud write gate so code-modification tasks don't
                    # get stuck demanding a separate markdown report.
                    if not _has_output_doc and task.type.name == "EXECUTION":
                        _has_patch_for_gate = any(
                            r.get("tool") == "patch_file" and r.get("success")
                            for r in tool_results
                        )
                        if _has_patch_for_gate:
                            _has_output_doc = True
                            logger.info(
                                "[OUTPUT GATE] EXECUTION task with patch_file — "
                                "iCloud output requirement bypassed"
                            )

                    if not _has_output_doc:
                        # Build a helpful list of available sub-dirs
                        import datetime as _dt2
                        _now_stamp = _dt2.datetime.now().strftime("%Y-%m-%d_%H%M")
                        _output_gate_msg = (
                            "⛔ OUTPUT DOCUMENT REQUIRED — completion rejected.\n\n"
                            "You have NOT written a report to the output directory yet. "
                            "This is REQUIRED before calling propose_completion.\n\n"
                            f"**Write a Markdown (.md) report to:**\n"
                            f"  `{_icloud_root}/<type>/{_now_stamp}_<short-slug>.md`\n\n"
                            "Sub-directories (choose the best match for this task):\n"
                            "  research/           — research & investigation tasks\n"
                            "  analysis/           — analysis & evaluation tasks\n"
                            "  planning/           — plans, specs, design docs\n"
                            "  optimization/       — performance & efficiency work\n"
                            "  self-improvement/   — self-improvement tasks\n"
                            "  security/           — security tasks\n"
                            "  learning/           — learning tasks\n"
                            "  general/            — anything else\n\n"
                            "**Document must include:**\n"
                            "  - Executive summary\n"
                            "  - Key findings / conclusions\n"
                            "  - Methodology\n"
                            "  - Outputs or artifacts\n\n"
                            "Use `write_file` with `create_dirs=True`, then call "
                            "`propose_completion` with the path in `files_created`."
                        )
                        execution_ledger.append(
                            f"[iter{iteration+1}] propose_completion BLOCKED — no output doc written"
                        )
                        conversation_history.append({"role": "user", "content": _output_gate_msg})
                        logger.warning(
                            f"[OUTPUT GATE] Completion blocked at iter {iteration+1} — "
                            f"no file written to {_icloud_root}"
                        )
                        # If this is the last iteration, grant a single bonus iteration
                        # so the model has a chance to write the doc and re-propose.
                        if iteration + 1 >= max_iterations:
                            max_iterations += 1
                            logger.info(
                                f"[OUTPUT GATE] Granted bonus iteration — "
                                f"max_iterations extended to {max_iterations}"
                            )
                        continue  # Force the agent to write a document first

                    func = completion_tc.get("function", {}) if isinstance(completion_tc, dict) else {}
                    arguments = func.get("arguments", {}) if isinstance(func, dict) else {}
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except Exception:
                            arguments = {}

                    # Bridge to existing parse_completion_proposal
                    arguments["status"] = "proposing_completion"
                    proposal = parse_completion_proposal(arguments)

                    # If the model omitted sources, auto-populate from web tool call history.
                    # The model often uses web_search / fetch_page but forgets to list them
                    # in propose_completion, causing the "Multiple sources consulted" soft
                    # criterion to fail even when real research was performed.
                    if not proposal.sources_consulted:
                        _web_tools = {"web_search", "fetch_page", "http_request", "conduct_research"}
                        _auto_sources: list = []
                        for _tr in tool_results:
                            if _tr.get("tool") not in _web_tools or not _tr.get("success"):
                                continue
                            _out = _tr.get("output") or {}
                            if isinstance(_out, dict):
                                _src = (_out.get("url") or _out.get("query")
                                        or _out.get("topic") or _out.get("source"))
                            else:
                                _src = str(_out)[:120]
                            if _src:
                                _auto_sources.append(str(_src))
                        if _auto_sources:
                            proposal.sources_consulted = _auto_sources
                            logger.debug(
                                "[propose_completion] Auto-populated %d source(s) from tool history",
                                len(_auto_sources),
                            )

                    # parsed is used by legacy paths below — build a minimal compat dict
                    parsed = arguments

                    # Generate or retrieve task completion spec
                    task_spec = self._get_task_completion_spec(task)
                    
                    # Build execution context for verification
                    # tests_passed: True if at least one run_python/run_shell succeeded
                    # as the FINAL code-execution call. Early failures are expected when
                    # the agent runs syntax checks on a broken patch and then fixes it —
                    # only the last code-execution result matters for the hard gate.
                    _code_run_tools = {"run_python", "run_shell_command", "execute_command", "run_script"}
                    _code_runs = [r for r in tool_results if r.get("tool") in _code_run_tools]
                    _successful_code_runs = [r for r in _code_runs if r.get("success")]
                    _tests_passed = len(_successful_code_runs) > 0
                    # New: add a timeout to avoid infinite loops during testing
                    _code_run_timeout = 30  # 30 seconds timeout
                    execution_context = {
                        "elapsed_seconds": int(time.time() - start_time),
                        "iterations": iteration + 1,
                        "tokens_used": sum(len(str(r.get('output', '')).split()) for r in tool_results),
                        "tool_count": len(tool_results),
                        "task_states": {},  # Will be populated by coordinator for graph validation
                        # Populated from tool_results so the EXECUTION hard gate
                        # ('Code executes without errors') has real signal to check.
                        "tests_passed": _tests_passed,
                        "additional_metric": len(_successful_code_runs) / (iteration + 1),  # New metric: success rate per iteration
                        "code_runs_attempted": len(_code_runs),
                        "code_run_timeout": _code_run_timeout,  # New metric: timeout for code runs
                        # Reality verifier inputs — passed through to LAYER 3.5
                        "tool_execution_logs": tool_results,
                        # write_file stores the path in "file_path"; fall back
                        # to "path" for any tool that uses the old key name.
                        "output_doc_paths": [
                            _tr.get("parameters", {}).get("file_path", "")
                            or _tr.get("parameters", {}).get("path", "")
                            for _tr in tool_results
                            if _tr.get("tool") == "write_file"
                            and _tr.get("success")
                            and (
                                _tr.get("parameters", {}).get("file_path", "")
                                or _tr.get("parameters", {}).get("path", "")
                            )
                        ],
                    }
                    
                    # Run verification through completion validator
                    verification_result = None
                    if self.completion_validator:
                        verification_result = await self.completion_validator.verify_completion(
                            task_id=task.id,
                            task_description=task.description,
                            task_type=task.type.value,
                            proposal=proposal,
                            spec=task_spec,
                            execution_context=execution_context
                        )
                        
                        logger.info(
                            f"🔍 Verification result: {verification_result.state.value}, "
                            f"score={verification_result.score.total_score:.3f}, "
                            f"issues={len(verification_result.issues)}"
                        )
                    
                    # Determine success based on verification (not LLM claim!)
                    if verification_result and verification_result.state == CompletionState.VERIFIED:
                        success = True
                        task.status = TaskStatus.VERIFIED
                        task.completion_score = verification_result.score.total_score
                        task.verified_at = datetime.now()
                        logger.info(f"✅ Task {task.id} VERIFIED (score={verification_result.score.total_score:.3f})")
                    elif verification_result and verification_result.state == CompletionState.PARTIALLY_COMPLETE:
                        success = False
                        task.status = TaskStatus.PARTIALLY_COMPLETE
                        task.completion_score = verification_result.score.total_score
                        logger.warning(f"⚠️  Task {task.id} PARTIALLY_COMPLETE - budget exhausted")
                    elif verification_result and verification_result.state == CompletionState.BLOCKED:
                        success = False
                        task.status = TaskStatus.BLOCKED
                        logger.warning(f"🚫 Task {task.id} BLOCKED - dependencies not met")
                    elif verification_result and verification_result.state == CompletionState.REVISION_REQUESTED:
                        # Revision requested - NOT a failure, but needs more work
                        success = False
                        task.verification_attempts += 1
                        task.last_verification_result = verification_result.to_dict() if verification_result else None

                        # Ledger entry so history survives compression
                        execution_ledger.append(
                            f"[iter{iteration+1}] REVISION_REQUESTED: "
                            f"score={verification_result.score.total_score:.2f}, "
                            f"gates_failed={len(verification_result.hard_gate_failures)}, "
                            f"issues={'; '.join(verification_result.issues[:3])}"
                        )
                        if len(execution_ledger) > EXECUTION_LEDGER_MAX_ENTRIES:
                            execution_ledger.pop(0)
                        
                        logger.info(
                            f"🔄 Revision requested for {task.id}: "
                            f"score={verification_result.score.total_score:.3f}, "
                            f"hard_gate_failures={len(verification_result.hard_gate_failures)}"
                        )
                        
                        # ── Revision-loop cap ──────────────────────────────────────────────
                        # If the score is stable (same value ≥ 3 consecutive attempts) and
                        # there are NO hard gate failures, the model is stuck — further
                        # revisions won't change the score (e.g., consistency check
                        # penalising mixed success/failure language that is factually accurate).
                        # In that case accept the result as PARTIALLY_COMPLETE rather than
                        # burning all remaining iterations.
                        _rev_scores = _wrap_up_counts.setdefault('rev_scores', [])
                        _rev_scores.append(round(verification_result.score.total_score, 3))
                        _rev_stable = (
                            len(_rev_scores) >= 3
                            and len(set(_rev_scores[-3:])) == 1          # same score 3× in a row
                            and not verification_result.hard_gate_failures  # no hard blocks
                        )
                        if _rev_stable:
                            logger.warning(
                                f"⚠️  Revision score stuck at {_rev_scores[-1]:.3f} for "
                                f"{len(set(_rev_scores[-3:]))} unique value(s) over "
                                f"{len(_rev_scores)} attempts — accepting as PARTIALLY_COMPLETE "
                                f"(no hard gate failures)"
                            )
                            success = False
                            task.status = TaskStatus.PARTIALLY_COMPLETE
                            task.completion_score = verification_result.score.total_score
                            break  # Exit agent loop — done

                        # If we have iterations left, inject revision feedback and continue
                        if iteration < max_iterations - 1:
                            # Reset the convergence wrap-up counter so the model gets
                            # nudges to call propose_completion again after doing revision
                            # work.  The _rev_stable guard (3 same scores in a row →
                            # PARTIALLY_COMPLETE) protects against infinite revision loops,
                            # so resetting here is safe.  Without the reset, the counter
                            # stays at 3 and the next convergence check immediately forces
                            # exit saying "LLM did not call propose_completion" — wrong,
                            # it DID call it but was asked to revise.
                            #
                            # Counter reset policy:
                            #   score < 0.3  → empty/truncated proposal (propose_completion({}))
                            #                  Keep the counter so nudge escalates (#2, #3).
                            #                  Do NOT give a fresh #1 start — the model didn't
                            #                  do more work, it just failed to write the JSON.
                            #   score >= 0.3 → real content failure (grounding, quality, etc.)
                            #                  Reset to 0 so the model gets fresh nudge cycle
                            #                  after doing the required revision work.
                            _vr_score = (
                                verification_result.score.total_score
                                if verification_result and verification_result.score
                                else 1.0
                            )
                            if _vr_score < 0.3:
                                # Empty/truncated proposal — keep at current to escalate
                                _prev_cw = _wrap_up_counts.get('convergence_wrap_up', 0)
                                _wrap_up_counts['convergence_wrap_up'] = max(1, _prev_cw)
                            else:
                                # Substantive content failure — reset for revision cycle
                                _wrap_up_counts['convergence_wrap_up'] = 0
                            # Use the structured revision prompt with required deltas
                            feedback_msg = verification_result.get_revision_prompt()
                            conversation_history.append({
                                "role": "user",
                                "content": feedback_msg
                            })
                            # Cooldown: skip convergence nudge on the NEXT iteration so
                            # the model acts on the revision before being told to propose
                            # again.  Without this, the nudge fires in the same iteration
                            # immediately after the revision message, and the model follows
                            # the nudge (most recent message) instead of doing revision work.
                            _wrap_up_counts['_revision_pending'] = True
                            continue  # Go back to agent loop with revision guidance
                    else:
                        # Verification FAILED - rejected by validator or no validator
                        success = False
                        task.verification_attempts += 1
                        task.last_verification_result = verification_result.to_dict() if verification_result else None
                        
                        if verification_result:
                            logger.warning(
                                f"❌ Verification FAILED for {task.id}: "
                                f"{', '.join(verification_result.issues[:3])}"
                            )

                            # Ledger entry so history survives compression
                            execution_ledger.append(
                                f"[iter{iteration+1}] VERIFY_FAILED: "
                                f"score={verification_result.score.total_score:.2f}, "
                                f"issues={'; '.join(verification_result.issues[:3])}"
                            )
                            if len(execution_ledger) > EXECUTION_LEDGER_MAX_ENTRIES:
                                execution_ledger.pop(0)

                            # If we still have iterations left, continue working
                            if iteration < max_iterations - 1:
                                # Provide feedback to LLM about why verification failed
                                feedback_msg = self._format_verification_feedback(verification_result)
                                conversation_history.append({
                                    "role": "user",
                                    "content": feedback_msg
                                })
                                continue  # Go back to agent loop
                        else:
                            # No validator available - fallback to legacy verification
                            logger.warning("Completion validator not available - using legacy output check")
                            outputs = parsed.get('outputs', {})
                            success = await self._verify_task_outputs(task, outputs)
                    
                    # Only proceed with post-completion tasks if actually verified
                    if success:
                        outputs = parsed.get('outputs', {})
                        
                        # Persist epistemic output (hypotheses + belief_updates).
                        # EXTEND, never reassign: `epistemic_mutations = []` here
                        # discarded every mutation observe_tool_result() had
                        # accumulated across the run, so the reward layer saw
                        # only the final-output parse and none of the learning
                        # that happened along the way.
                        _final_mutations = await self._persist_epistemic_output(task, outputs)
                        if _final_mutations:
                            epistemic_mutations.extend(_final_mutations)

                        # Record tool usage outcome for adaptive learning
                        execution_time = int(time.time() - start_time)
                        import os as _shadow_os
                        _shadow_mode = bool(_shadow_os.environ.get("TORIN_SHADOW_MODE"))

                        # Extract code quality signals from tool_results for reward shaping.
                        # These boost outcome_quality so the adaptive learning system
                        # Enhance quality metrics to include test coverage and failure rates.
                        # reinforces clean, tested, lint-passing implementations.
                        # SECOND copy of the substring interpretation used to
                        # live here, feeding _boosted_quality. Same canonical
                        # source as the reward path — one interpretation of tool
                        # evidence, not two that can disagree.
                        from core.reasoning.epistemic_engine import summarize_tool_observations
                        _canon = dict(summarize_tool_observations(tool_observations))
                        _canon.pop("unknown", None)
                        # `is True` — an unmeasured signal earns no bonus and
                        # incurs no penalty; absent is not False.
                        _lint_passed = _canon.get('lint_passed') is True
                        _tests_ran_and_passed = _canon.get('tests_passed') is True
                        _clean_patch = _canon.get('clean_patch') is True
                        _base_quality = verification_result.score.total_score if verification_result else 0.7
                        _failure_rate = (
                            sum(1 for r in _code_runs if not r.get("success")) / len(_code_runs)
                            if _code_runs else 0.0
                        )
                        _quality_bonus = (
                            (0.08 if _lint_passed else 0.0) +
                            (0.10 if _tests_ran_and_passed else 0.0) +
                            (0.05 if _clean_patch else 0.0) +
                            (0.15 * (1 - _failure_rate))  # Penalize failure rate
                        )
                        _boosted_quality = min(1.0, _base_quality + _quality_bonus)
                        if _quality_bonus > 0:
                            logger.info(
                                f"Code quality reward: lint={_lint_passed}, "
                                f"tests={_tests_ran_and_passed}, patch={_clean_patch} "
                                f"→ quality {_base_quality:.2f} → {_boosted_quality:.2f}"
                            )

                        if not _shadow_mode:
                            await self._record_tool_usage_outcome(
                                task=task,
                                tool_results=tool_results,
                                success=success,
                                outcome_quality=_boosted_quality,
                                confidence=verification_result.confidence if verification_result else 0.7,
                                execution_time_seconds=execution_time,
                                iterations_count=iteration + 1,
                                # SAY WHY, or the observation is discarded.
                                #
                                # Omitting this defaulted to `indeterminate`,
                                # which earns no credit — so every task that
                                # COMPLETED, the single most informative thing
                                # that can happen to a tool selection, was
                                # recorded as "outcome undetermined" and thrown
                                # away. `tool_usage_history` held one row after
                                # months, and it was a bootstrap probe.
                                #
                                # This caller does know: the task reached a
                                # completion proposal and verification ruled on
                                # it. Succeeded means the selection worked;
                                # failed here means the approach ran to the end
                                # and did not produce a verified result, which
                                # is the strategy's to answer for — no tool
                                # broke and nothing external failed.
                                outcome_class=("success" if success
                                               else "strategy_failure"),
                            )

                        # Fire reward + penalty signals (runs in shadow mode too)
                        asyncio.create_task(self._fire_reward_signals(
                            task=task,
                            tool_results=tool_results,
                            success=success,
                            verification_score=_boosted_quality,
                            execution_time_seconds=execution_time,
                            iterations_count=iteration + 1,
                            # Accumulated by observe_tool_result() across this
                            # task's tool calls — already in scope, previously
                            # returned to the coordinator and never fed back
                            # into the reward that needed it most.
                            epistemic_mutations=list(epistemic_mutations),
                            tool_observations=list(tool_observations),
                        ))

                        # Store memories (fire-and-forget)
                        if self.memory_agent:
                            asyncio.create_task(self._capture_task_memory(
                                task=task,
                                tool_results=tool_results,
                                success=success,
                                summary=parsed.get('summary', ''),
                                confidence=verification_result.confidence if verification_result else 0.7,
                                execution_time=int(time.time() - start_time),
                                iterations=iteration + 1
                            ))

                        if self.memory_agent and self.context_manager:
                            asyncio.create_task(self._capture_semantic_task_memory(
                                task=task,
                                conversation_history=list(conversation_history),
                                success=success,
                                summary=parsed.get('summary', ''),
                                confidence=verification_result.confidence if verification_result else 0.7,
                                execution_time=int(time.time() - start_time),
                                iterations=iteration + 1
                            ))

                        # Phase 3: Record task outcome for self-optimization
                        # Feed back final uncertainty and success for adaptive calibration
                        if self.iteration_controller:
                            try:
                                # Get final uncertainty from convergence result
                                final_uncertainty = convergence_result.overall_uncertainty if hasattr(convergence_result, 'overall_uncertainty') else 0.1
                                self.iteration_controller.record_task_outcome(
                                    final_uncertainty=final_uncertainty,
                                    success=True
                                )
                            except Exception as e:
                                logger.warning(f"Failed to record Phase 3 task outcome: {e}")

                        # Build the full result dict — include all propose_completion fields
                        # so the coordinator's Slack notification can show conclusions properly
                        _exec_duration = int(time.time() - start_time)
                        _full_result = {
                            'success': True,
                            'task_id': task.id,
                            'summary': parsed.get('summary', ''),
                            'key_findings': parsed.get('key_findings', ''),
                            'outputs': outputs,
                            'tool_results': tool_results,
                            'iterations': iteration + 1,
                            'epistemic_mutations': epistemic_mutations,
                            'completion_score': verification_result.score.total_score if verification_result else None,
                            'verification_state': verification_result.state.value if verification_result else 'legacy',
                            'files_created': parsed.get('files_created') or [],
                            'files_modified': parsed.get('files_modified') or [],
                            'sources': parsed.get('sources') or [],
                            'assumptions': parsed.get('assumptions') or [],
                            'duration_seconds': _exec_duration,
                        }

                        return _full_result
                    else:
                        # Verification failed but no more iterations - return failure
                        if iteration >= max_iterations - 1:
                            # Log drift metrics on final failure for observability
                            if self.completion_validator:
                                drift_metrics = self.completion_validator.get_drift_metrics()
                                if drift_metrics.get("sufficient_data"):
                                    logger.info(
                                        f"📊 Drift metrics at failure: "
                                        f"failure_rate={drift_metrics.get('failure_rate', 0):.1%}, "
                                        f"avg_score={drift_metrics.get('avg_score', 0):.2f}, "
                                        f"is_degrading={drift_metrics.get('is_degrading', False)}"
                                    )
                            
                            # Phase 3: Record task failure for self-optimization
                            if self.iteration_controller:
                                try:
                                    # Get final uncertainty from convergence result
                                    final_uncertainty = convergence_result.overall_uncertainty if hasattr(convergence_result, 'overall_uncertainty') else 0.8
                                    self.iteration_controller.record_task_outcome(
                                        final_uncertainty=final_uncertainty,
                                        success=False
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to record Phase 3 task failure: {e}")
                            
                            _vr_issues = verification_result.issues if verification_result else []
                            _vr_recs   = verification_result.recommendations if verification_result else []
                            _vr_score  = verification_result.score.total_score if verification_result else 0.0
                            _vr_state  = verification_result.state.value if verification_result else 'failed'
                            # Build a human-readable summary for logs and retry context
                            _vr_summary = (
                                f"score={_vr_score:.2f}, state={_vr_state}"
                                + (f", issues=[{'; '.join(str(i) for i in _vr_issues[:3])}]" if _vr_issues else "")
                                + (f", recs=[{'; '.join(str(r) for r in _vr_recs[:2])}]" if _vr_recs else "")
                            )
                            logger.warning(
                                f"Completion verification failed for task {task.id}: {_vr_summary}"
                            )
                            return {
                                'success': False,
                                'task_id': task.id,
                                'error': f'Completion verification failed: {_vr_summary}',
                                'issues': _vr_issues,
                                'recommendations': _vr_recs,
                                'completion_score': _vr_score,
                                'verification_state': _vr_state,
                                'tool_results': tool_results,
                                'iterations': iteration + 1,
                            }
                        # Otherwise continue to next iteration (already added feedback above)

                # Execute regular tool calls (native format from create_chat_completion)
                if regular_tool_calls:
                    logger.info(f"[Iteration {iteration + 1}] Executing {len(regular_tool_calls)} native tool calls")
                    self._consecutive_text_only = 0  # reset apology-loop counter on any real tool call
                    MAX_OUTPUT_CHARS = 4000  # raised from 1000 — short truncation caused hallucinated paths
                    tool_calls_this_turn = regular_tool_calls  # snapshot for no-progress tracking below

                    for tc in regular_tool_calls:
                        # Normalise the tool call object — llama-cpp-python may return
                        # either a dict or a simple namespace object.
                        if isinstance(tc, dict):
                            func = tc.get("function", {})
                            tc_id = tc.get("id", f"call_{iteration}_{len(tool_results)}")
                        else:
                            func = getattr(tc, "function", {})
                            tc_id = getattr(tc, "id", f"call_{iteration}_{len(tool_results)}")

                        tool_name = (func.get("name", "") if isinstance(func, dict)
                                     else getattr(func, "name", ""))
                        arguments = (func.get("arguments", {}) if isinstance(func, dict)
                                     else getattr(func, "arguments", {}))
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except Exception as _arg_parse_err:
                                logger.error("Tool call arg JSON parse failed for %s: %s — raw: %.200s",
                                             tool_name, _arg_parse_err, arguments)
                                tool_results.append({
                                    "tool": tool_name, "parameters": {},
                                    "success": False,
                                    "output": f"MALFORMED_ARGS: tool call arguments could not be parsed as JSON: {_arg_parse_err}"
                                })
                                conversation_history.append({
                                    "role": "tool", "tool_call_id": tc_id,
                                    "name": tool_name,
                                    "content": f"Error: MALFORMED_ARGS — your tool call arguments were not valid JSON. Retry with correctly formatted arguments."
                                })
                                continue

                        logger.info(f"🔧 Tool call [{len(tool_results) + 1}]: {tool_name}")
                        if arguments:
                            preview = {
                                k: (
                                    str(v)[:50] + '...'
                                    if isinstance(v, str) and len(str(v)) > 50
                                    else v
                                )
                                for k, v in list(arguments.items())[:3]
                            }
                            logger.debug(f"Tool parameters preview: {preview}")

                        # ── request_tools meta-tool: handled here, never reaches registry ──
                        if tool_name == "request_tools":
                            capability = arguments.get("capability", "")
                            # Split on spaces AND underscores so 'code_analysis' → ['code', 'analysis']
                            import re as _re_rt
                            raw_kws = _re_rt.split(r'[\s_]+', capability.lower())
                            capability_kws = [w.strip() for w in raw_kws if len(w.strip()) > 2]
                            matched: list[str] = []
                            for reserved_name in list(reserved_tool_pool.keys()):
                                func_info = reserved_tool_pool[reserved_name].get("function", {})
                                searchable = (
                                    reserved_name.lower()
                                    + " "
                                    + func_info.get("description", "").lower()
                                )
                                if any(kw in searchable for kw in capability_kws):
                                    tool_schemas.append(reserved_tool_pool.pop(reserved_name))
                                    matched.append(reserved_name)

                            if matched:
                                tool_content = (
                                    f"Added {len(matched)} tool(s) for '{capability}': "
                                    + ", ".join(matched)
                                    + ". They are now available in your tool set."
                                )
                            else:
                                # Show a sample of what IS available so the model can pick a real name
                                sample = list(reserved_tool_pool.keys())[:20]
                                tool_content = (
                                    f"No tools matched '{capability}' (keywords tried: {capability_kws}). "
                                    f"{len(reserved_tool_pool)} tools remain in reserve. "
                                    f"Available tool names (sample): {', '.join(sample)}. "
                                    "Use an exact tool name or a keyword from its name."
                                )

                            ledger_kw = f"→ +{matched}" if matched else "→ NO MATCH"
                            execution_ledger.append(
                                f"[iter{iteration+1}] request_tools('{capability}') {ledger_kw}"
                            )

                            conversation_history.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": tool_name,
                                "content": tool_content,
                            })
                            tool_results.append({
                                "tool": tool_name,
                                "parameters": arguments,
                                "success": True,
                                "output": tool_content,
                            })
                            continue  # skip tool_registry.execute_tool

                        # ── Argument fingerprinting: block duplicate failing calls (point 4) ─
                        _call_sig = f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"
                        _call_sig_h = hash(_call_sig)
                        if failed_call_signatures.get(_call_sig_h, 0) > 0:
                            _dup_fail_count = failed_call_signatures[_call_sig_h]
                            if tool_name == "patch_file":
                                _old_str_prev = str(arguments.get("old_string", ""))[:100].replace("\n", "\\n")
                                _dup_msg = (
                                    f"⛔ DUPLICATE PATCH BLOCKED (already failed {_dup_fail_count}x): "
                                    f"Your old_string '{_old_str_prev}...' was NOT FOUND in the file. "
                                    "You are reading the WRONG section of the file. "
                                    "Do NOT submit the same patch again. You MUST locate the right lines first:\n"
                                    "  STEP 1: call grep_search to find the function/class you want to modify:\n"
                                    "    grep_search(pattern='function_name', path='<absolute_file_path>')\n"
                                    "  STEP 2: read_file on the EXACT line numbers that grep_search returns\n"
                                    "  STEP 3: copy old_string CHARACTER-FOR-CHARACTER from that read_file output\n"
                                    "  STEP 4: call patch_file with that verbatim content\n"
                                    "Call grep_search RIGHT NOW — do NOT read lines 300-400 or any guessed range."
                                )
                            else:
                                _dup_msg = (
                                    f"⛔ DUPLICATE FAILING CALL BLOCKED: '{tool_name}' with these "
                                    f"exact arguments has already failed {_dup_fail_count}x. "
                                    "Repeating an identical failing call is a loop. "
                                    "Use DIFFERENT arguments or a DIFFERENT tool."
                                )
                            execution_ledger.append(
                                f"[iter{iteration+1}] ⛔ BLOCKED duplicate: {tool_name}"
                            )
                            conversation_history.append({"role": "user", "content": _dup_msg})
                            tool_results.append({
                                "tool": tool_name, "parameters": arguments,
                                "success": False, "output": _dup_msg,
                            })
                            continue

                        # ── Successful-call deduplication ───────────────────────────────
                        # Block retrieval tools called with identical args > N times when
                        # those calls already succeeded.  Repeating the same search query
                        # yields zero new information — it's a research loop.
                        if tool_name in _SUCCESS_DEDUP_TOOLS:
                            _succ_cnt = success_call_signatures.get(_call_sig_h, 0)
                            if _succ_cnt >= _MAX_SUCCESS_REPEATS:
                                _dedup_msg = (
                                    f"⛔ REPEATED QUERY BLOCKED: '{tool_name}' with these exact "
                                    f"arguments has already succeeded {_succ_cnt}x and returned "
                                    "the same results. Repeating it yields nothing new.\n"
                                    "You already have the data. NOW act on it:\n"
                                    "  • If you have web_search results → call write_file to "
                                    "synthesise your findings into a document.\n"
                                    "  • If you need more detail → use web_fetch or fetch_page "
                                    "with a SPECIFIC URL from the search results (not another search).\n"
                                    "  • If you need different information → change your query "
                                    "(use a different topic, not the same words).\n"
                                    "Do NOT call this tool again with the same arguments."
                                )
                                execution_ledger.append(
                                    f"[iter{iteration+1}] ⛔ BLOCKED repeated success: {tool_name}"
                                )
                                conversation_history.append({"role": "user", "content": _dedup_msg})
                                tool_results.append({
                                    "tool": tool_name, "parameters": arguments,
                                    "success": False, "output": _dedup_msg,
                                })
                                logger.info(
                                    f"[DEDUP] Blocked repeated successful call: {tool_name} "
                                    f"(seen {_succ_cnt}x)"
                                )
                                continue

                        # ── 10 calls without real progress → abort (point 10) ──────────
                        if _no_real_progress_calls >= _MAX_NO_PROGRESS_CALLS:
                            _abort_msg = (
                                f"🛑 PROGRESS ABORT: {_no_real_progress_calls} consecutive tool calls "
                                "produced no real progress (all failed or were no-ops). "
                                "The current approach is not working. "
                                "Call propose_completion with a partial result, "
                                "or explain what is blocking progress."
                            )
                            execution_ledger.append(
                                f"[iter{iteration+1}] 🛑 PROGRESS ABORT after {_no_real_progress_calls} stuck calls"
                            )
                            conversation_history.append({"role": "user", "content": _abort_msg})
                            logger.warning(f"[PROGRESS ABORT] {_no_real_progress_calls} stuck calls")
                            break

                        # Phase 3: Track operation timing for cost learning
                        tool_start_time = time.time()

                        # ── Per-tool timeout via IterationController ──────────────────
                        # The IterationController owns the task budget and checks time
                        # at iteration boundaries.  Ask it for the max this single
                        # operation may consume so a runaway tool call cannot silently
                        # exhaust the budget between those checks.
                        _tool_exec_timeout: float | None = None
                        if self.iteration_controller and iteration_budget and start_time:
                            _elapsed_now = time.time() - start_time
                            _tool_exec_timeout = self.iteration_controller.get_operation_timeout(
                                budget=iteration_budget,
                                elapsed_seconds=_elapsed_now,
                                operation="tool_call",
                            )
                            logger.debug(
                                f"[ITER_CTRL] {tool_name} timeout={_tool_exec_timeout:.0f}s "
                                f"({iteration_budget.time_budget_seconds - _elapsed_now:.0f}s remaining)"
                            )

                        try:
                            if _tool_exec_timeout is not None:
                                result = await asyncio.wait_for(
                                    self.tool_registry.execute_tool(tool_name, arguments),
                                    timeout=_tool_exec_timeout,
                                )
                            else:
                                result = await self.tool_registry.execute_tool(tool_name, arguments)
                        except asyncio.TimeoutError:
                            from core.tools.tool_registry import ToolResult
                            _elapsed_now = time.time() - start_time if start_time else 0.0
                            _remaining = (
                                iteration_budget.time_budget_seconds - _elapsed_now
                                if iteration_budget else 0.0
                            )
                            result = ToolResult(
                                success=False,
                                output=None,
                                error=(
                                    f"TOOL_TIMEOUT: {tool_name} exceeded time cap "
                                    f"({_tool_exec_timeout:.0f}s). "
                                    f"{_remaining:.0f}s task budget remaining. "
                                    "Try a different approach."
                                ),
                                tool_name=tool_name,
                            )
                            logger.warning(
                                f"[ITER_CTRL] {tool_name} timed out ({_tool_exec_timeout:.0f}s), "
                                f"{_remaining:.0f}s remaining"
                            )
                        except Exception as exc:
                            from core.tools.tool_registry import ToolResult, _enrich_tool_error
                            _exc_raw = f"EXECUTION_ERROR: {exc.__class__.__name__}: {exc}"
                            _exc_tei = _enrich_tool_error(_exc_raw, tool_name)
                            result = ToolResult(
                                success=False,
                                output=None,
                                error=_exc_tei.to_prompt_str(verbose=True),
                                tool_name=tool_name,
                            )
                        tool_duration = time.time() - tool_start_time

                        # Phase 3: Record operation cost for adaptive learning
                        if self.iteration_controller:
                            try:
                                self.iteration_controller.record_operation_cost(
                                    operation="tool_call",
                                    duration=tool_duration
                                )
                            except Exception as e:
                                logger.warning(f"Failed to record Phase 3 operation cost: {e}")

                        status_icon = "✓" if result.success else "✗"
                        logger.info(
                            f"{status_icon} {tool_name} success={result.success} ({tool_duration:.2f}s)"
                        )

                        # ── Execution ledger entry (Risk 3 mitigation) ────────────────
                        # Record every tool invocation and its outcome so the agent
                        # retains full causal history even after context compression.
                        _args_preview = ", ".join(
                            f"{k}={str(v)[:40]}" for k, v in list(arguments.items())[:3]
                        )
                        _observation = []
                        if result.success:
                            _out_preview = str(result.output)[:100].replace("\n", " ")
                            _ledger_entry = f"[iter{iteration+1}] ✓ {tool_name}({_args_preview}) → {_out_preview}"
                            # Feed successful tool result into epistemic engine so
                            # the convergence gate can measure real task progress.
                            try:
                                from core.reasoning.epistemic_engine import get_epistemic_engine
                                _eng = get_epistemic_engine()
                                # THE canonical interpretation. result.output is the
                                # last point at which the observation is still
                                # structured -- it is str()'d and truncated ~60 lines
                                # below. Interpreted exactly ONCE here, then shared
                                # with the belief graph and the tool record.
                                _observation = _eng.interpret_tool_output(
                                    tool_name, arguments, result.output
                                )
                                _ep_mutations = await _eng.observe_tool_result(
                                    tool_name=tool_name,
                                    parameters=arguments,
                                    output=result.output,
                                    success=True,
                                    interpreted=_observation,
                                )
                                if _ep_mutations:
                                    epistemic_mutations.extend(_ep_mutations)
                                # Keep the canonical observations too: the
                                # mutations carry only (type, id, delta), which
                                # loses the claim. outcome_quality needs the
                                # claim, and must not re-parse tool text to
                                # recover it.
                                if _observation:
                                    tool_observations.extend(_observation)
                            except Exception as _ep_err:
                                logger.debug(f"[epistemic] observe_tool_result non-fatal: {_ep_err}")
                        else:
                            _err_preview = (str(result.error) or str(result.output))[:120].replace("\n", " ")
                            _ledger_entry = f"[iter{iteration+1}] ✗ {tool_name}({_args_preview}) → FAIL: {_err_preview}"
                        execution_ledger.append(_ledger_entry)
                        if len(execution_ledger) > EXECUTION_LEDGER_MAX_ENTRIES:
                            execution_ledger.pop(0)

                        # ── Tool sequence history + oscillation detection (point 5) ──────
                        _tool_call_history.append(tool_name)
                        _tch_len = len(_tool_call_history)

                        _stagnation_triggered = False

                        if not _stagnation_triggered and _tch_len >= 8 and _tool_call_history[-4:] == _tool_call_history[-8:-4]:
                            _osc_seq = " → ".join(_tool_call_history[-4:])
                            _osc_count += 1
                            execution_ledger.append(
                                f"[iter{iteration+1}] ⚠️ OSCILLATION x{_osc_count}: {_osc_seq}"
                            )
                            logger.warning(f"[OSCILLATION x{_osc_count}] Repeating pattern: {_osc_seq}")

                            if _osc_count == 1:
                                # First detection: firm directive
                                _osc_msg = (
                                    f"🚨 LOOP DETECTED (x1): You have called [{_osc_seq}] "
                                    "in a repeating cycle. STOP immediately.\n"
                                    "You have collected enough information. "
                                    "Your next action MUST be to write your findings to a file using write_file, "
                                    "then call propose_completion. Do NOT call any search or fetch tool again."
                                )
                            elif _osc_count == 2:
                                # Second detection: force phase transition
                                _osc_msg = (
                                    "🚨 LOOP DETECTED (x2): You are STILL repeating the same tool calls. "
                                    "Research phase is NOW CLOSED. You are FORBIDDEN from calling any search, "
                                    "fetch, or academic tool for the remainder of this task.\n"
                                    "MANDATORY NEXT STEPS:\n"
                                    "1. Call write_file with a complete document synthesising everything you found.\n"
                                    "2. Call propose_completion.\n"
                                    "Failure to do this will abort the task."
                                )
                            else:
                                # Third+ detection: hard stop — inject propose_completion directly
                                _osc_msg = (
                                    "🛑 FORCED TASK COMPLETION: You have been looping for too long "
                                    f"({_osc_count} oscillation cycles). "
                                    "The system is terminating the research phase NOW.\n"
                                    "You MUST call propose_completion in your very next response. "
                                    "Write a brief synthesis of what you found and call propose_completion. "
                                    "Any other tool call will be ignored."
                                )
                                # Also reset the history so we don't keep hammering this path
                                _tool_call_history.clear()

                            conversation_history.append({"role": "user", "content": _osc_msg})
                        else:
                            # No oscillation this step — reset counter if pattern broke
                            if _osc_count > 0 and _tch_len >= 4:
                                # Only reset if the last tool was genuinely different
                                if tool_name not in _tool_call_history[-5:-1]:
                                    _osc_count = 0

                        # ── Research synthesis gate ─────────────────────────────────────
                        # For RESEARCH tasks: if the model has made 8+ successful retrieval
                        # calls but still has NOT called write_file, the research phase has
                        # gone on long enough — push it to synthesise.
                        _task_type_nm_g = task.type.name if hasattr(task, 'type') else ''
                        if _task_type_nm_g in ("RESEARCH", "SYNTHESIS", "ANALYSIS"):
                            _SYNTH_RETRIEVAL_TOOLS = _SUCCESS_DEDUP_TOOLS | {
                                "search_news", "search_academic", "search_data",
                                "analyze_research_paper", "fetch_paper_by_doi",
                                "fetch_paper_by_arxiv", "synthesize_literature",
                            }
                            _retrieval_successes = sum(
                                1 for r in tool_results
                                if r.get("tool") in _SYNTH_RETRIEVAL_TOOLS and r.get("success")
                            )
                            _has_write_file = any(
                                r.get("tool") in {"write_file", "atomic_write_file"}
                                and r.get("success")
                                for r in tool_results
                            )
                            _synth_gate_key = '_synth_nudge_fired'
                            _synth_threshold = 5
                            if (
                                _retrieval_successes >= _synth_threshold
                                and not _has_write_file
                                and not _wrap_up_counts.get(_synth_gate_key)
                            ):
                                _wrap_up_counts[_synth_gate_key] = True
                                _synth_msg = (
                                    f"📝 SYNTHESIS REQUIRED: You have made {_retrieval_successes} "
                                    "successful research calls but have NOT written any output document yet.\n"
                                    "The research collection phase is complete. You MUST now synthesise:\n"
                                    "  1. Call write_file to save a comprehensive document to iCloud:\n"
                                    "     file_path: /Users/stefan/Library/Mobile Documents/"
                                    "com~apple~CloudDocs/output-file/research/YYYY-MM-DD_HHMM_<slug>.md\n"
                                    "     The document must include: concept overview, underlying physics/"
                                    "technology, components, operation, use cases, limitations, sources.\n"
                                    "     Minimum 800 words. Incorporate the SPECIFIC names, organizations,\n"
                                    "     and technologies from your search results — do not write generically.\n"
                                    "  2. After write_file succeeds → call propose_completion.\n"
                                    "Do NOT make any more search or fetch calls. Write the document NOW."
                                )
                                conversation_history.append({"role": "user", "content": _synth_msg})
                                execution_ledger.append(
                                    f"[iter{iteration+1}] 📝 SYNTHESIS GATE fired "
                                    f"({_retrieval_successes} retrievals, no write)"
                                )
                                logger.info(
                                    f"[SYNTHESIS GATE] {_retrieval_successes} retrievals, no write_file "
                                    f"— injecting synthesis nudge"
                                )

                        # Track failures
                        if not result.success:
                            failed_tools[tool_name] = failed_tools.get(tool_name, 0) + 1
                            _no_real_progress_calls += 1
                            logger.warning(
                                f"[FAILURE TRACKING] {tool_name} failed {failed_tools[tool_name]} times"
                            )

                            # Track signature for fingerprinting guard
                            failed_call_signatures[_call_sig_h] = (
                                failed_call_signatures.get(_call_sig_h, 0) + 1
                            )

                            # Store per-tool failure details for memory injection
                            _fail_meta = result.metadata if isinstance(result.metadata, dict) else {}
                            _fail_cat  = _fail_meta.get("error_category", "")
                            if not _fail_cat:
                                import re as _rereg
                                _cat_m = _rereg.search(r"\[RECOVERY_HINT:(\w+)", str(result.error or ""))
                                _fail_cat = _cat_m.group(1) if _cat_m else "UNKNOWN"
                            _fail_short = _fail_meta.get("short_hint", "")
                            tool_failure_details[tool_name] = {
                                "count":      failed_tools[tool_name],
                                "category":   _fail_cat,
                                "short_hint": _fail_short,
                            }

                            # Terminal error abort (point 3)
                            try:
                                from core.tools.tool_registry import TERMINAL_ERRORS
                                if _fail_cat in TERMINAL_ERRORS:
                                    if _fail_cat == "PATCH_NOOP" and tool_name == "patch_file":
                                        # PATCH_NOOP = the file ALREADY contains your new_string.
                                        # Most common cause: a previous iteration or run already
                                        # applied this change. Tell the model to verify then advance.
                                        _patch_fp = _call_params.get("file_path", "<unknown>")
                                        _terminal_msg = (
                                            f"✅ PATCH_NOOP on '{_patch_fp}': "
                                            "your new_string is ALREADY present in the file — "
                                            "a previous iteration already applied this change.\n"
                                            "DO NOT call patch_file again with this content.\n"
                                            "YOUR NEXT STEP: call read_file on that file to confirm "
                                            "the change is visible, then proceed immediately to "
                                            "Phase 5 verification (syntax → lint → import test). "
                                            "If after reading the file the intended change is NOT "
                                            "present, you must construct old_string by copying the "
                                            "EXACT verbatim text from the read_file output — do NOT "
                                            "reconstruct it from memory."
                                        )
                                    else:
                                        _terminal_msg = (
                                            f"🚫 TERMINAL ERROR [{_fail_cat}]: '{tool_name}' cannot "
                                            f"succeed with these arguments. Do NOT call '{tool_name}' "
                                            "again with the same or similar parameters. "
                                            "Switch to a completely different strategy."
                                            + (f"\nHint: {_fail_short}" if _fail_short else "")
                                        )
                                    execution_ledger.append(
                                        f"[iter{iteration+1}] 🚫 TERMINAL {_fail_cat}: {tool_name}"
                                    )
                                    conversation_history.append({"role": "user", "content": _terminal_msg})
                                    logger.warning(f"[TERMINAL ERROR] {_fail_cat} from {tool_name}")
                                elif _fail_cat == "PATCH_STRING_NOT_FOUND" and tool_name == "patch_file":
                                    # Not terminal (recoverable) but needs specific guidance.
                                    # The model often uses placeholder strings like 'CURRENT_CODE' —
                                    # detect that and give a very targeted correction message.
                                    _old_str = _call_params.get("old_string", "")
                                    _patch_fp2 = _call_params.get("file_path", "<unknown>")
                                    _new_str = _call_params.get("new_string", "")
                                    # Placeholder detection: catch hallucinated/generic old_strings.
                                    # Check 1: too short to be real code
                                    _ph_short = len(_old_str) < 30
                                    # Check 2: exact match to known placeholder words (case-insensitive)
                                    _ph_keywords = {
                                        "CURRENT_CODE", "EXISTING_CODE", "OLD_CODE",
                                        "ORIGINAL_CODE", "CODE_HERE", "YOUR_CODE_HERE",
                                        "PLACEHOLDER", "...", "TODO", "# ...", "EXISTING_CONTENT",
                                    }
                                    _ph_exact = _old_str.strip().upper() in _ph_keywords
                                    # Check 3: contains placeholder tokens even if surrounded by other text
                                    _ph_tokens = any(
                                        tok in _old_str
                                        for tok in (
                                            "CURRENT_CODE", "EXISTING_CODE", "OLD_CODE",
                                            "CODE_HERE", "YOUR_CODE_HERE",
                                            "# existing code", "# ... existing",
                                            "# current implementation",
                                            "\n...",    # ellipsis on its own line (abbreviation)
                                            "\n   ...", "\n    ...",  # indented ellipsis
                                            "   ...\n", "    ...\n",  # ellipsis before newline
                                        )
                                    )
                                    # Check 4: new_string adds a TODO/stub (model implementing a TODO
                                    # comment by adding another TODO comment or a raise/pass stub)
                                    _ph_stub_new = any(
                                        tok in _new_str
                                        for tok in (
                                            "# TODO", "# FIXME", "raise NotImplementedError",
                                            "pass  # implement", "pass # implement",
                                        )
                                    )
                                    _is_placeholder = _ph_short or _ph_exact or _ph_tokens or _ph_stub_new
                                    if _is_placeholder:
                                        _ph_reason = (
                                            "stub new_string (contains TODO/pass/NotImplementedError)" if _ph_stub_new
                                            else "placeholder token in old_string" if _ph_tokens
                                            else "old_string is a keyword placeholder" if _ph_exact
                                            else "old_string too short to be real code"
                                        )
                                        _snf_msg = (
                                            f"⛔ PATCH REJECTED on '{_patch_fp2}' ({_ph_reason}).\n\n"
                                            "RULES:\n"
                                            "  • old_string must be copied CHARACTER-FOR-CHARACTER from "
                                            "a read_file result — never reconstructed from memory.\n"
                                            "  • new_string must contain COMPLETE, WORKING logic — "
                                            "no pass, no raise NotImplementedError, no '# TODO', no stubs.\n"
                                            "  • Only call functions that already exist in the file or "
                                            "that you define in this same patch.\n\n"
                                            "DO THIS NOW:\n"
                                            f"  1. Call read_file(file_path='{_patch_fp2}', "
                                            "start_line=<target line>, end_line=<+15 lines>).\n"
                                            "  2. In the SAME response, call patch_file with:\n"
                                            "     old_string = verbatim copy of what read_file returned\n"
                                            "     new_string = your full implementation (no stubs)\n"
                                            "Emit both tool calls now."
                                        )
                                    else:
                                        _snf_msg = (
                                            f"⛔ PATCH_STRING_NOT_FOUND on '{_patch_fp2}': your "
                                            "old_string does not appear verbatim in the file. "
                                            "The file may have changed, or your old_string contains "
                                            "paraphrased/reconstructed text.\n"
                                            "Fix: call read_file on the exact lines you want to change "
                                            "(use start_line + end_line), copy the output CHARACTER-FOR-CHARACTER "
                                            "as old_string, then retry patch_file in the SAME response."
                                        )
                                    execution_ledger.append(
                                        f"[iter{iteration+1}] ⛔ PATCH_STRING_NOT_FOUND: {tool_name} "
                                        f"(placeholder={_is_placeholder})"
                                    )
                                    conversation_history.append({"role": "user", "content": _snf_msg})
                                    logger.warning(
                                        f"[PATCH_STRING_NOT_FOUND] {tool_name} — "
                                        f"placeholder={_is_placeholder}, file={_patch_fp2}"
                                    )
                            except Exception as _term_err:
                                logger.warning("Terminal error classification failed for %s: %s",
                                               tool_name, _term_err)

                            # Phase 2: Bayesian retry decision
                            if self.iteration_controller and iteration_budget:
                                # Get current uncertainty
                                current_uncertainty = 0.5  # Default
                                if self.convergence_gate and self.convergence_gate.epistemic_engine:
                                    try:
                                        from core.reasoning.reasoning_interfaces import ReasoningRequest, ReasoningMode
                                        uncertainty_request = ReasoningRequest(
                                            query=f"Tool {tool_name} failed: {result.error}",
                                            mode=ReasoningMode.EPISTEMIC,
                                            context={"task_id": task.id, "tool_name": tool_name}
                                        )
                                        uncertainty_result = await self.convergence_gate.epistemic_engine.reason(uncertainty_request)
                                        current_uncertainty = uncertainty_result.uncertainty
                                    except Exception as e:
                                        logger.error(f"Failed to compute tool failure uncertainty — Bayesian retry using hardcoded 0.5: {e}", exc_info=True)
                                
                                # Compute time remaining
                                elapsed = time.time() - start_time
                                time_remaining = iteration_budget.time_budget_seconds - elapsed
                                
                                # Bayesian retry decision
                                retry_decision = await self.iteration_controller.should_retry_operation(
                                    operation="tool_call",
                                    failure_reason=str(result.error),
                                    current_uncertainty=current_uncertainty,
                                    retry_count=failed_tools[tool_name] - 1,  # Already incremented
                                    time_remaining=time_remaining
                                )
                                
                                if retry_decision.should_retry:
                                    logger.info(f"🔄 Bayesian retry: {retry_decision.reason}")
                                else:
                                    logger.warning(f"🚫 Bayesian retry rejected: {retry_decision.reason}")
                                    # Mark as permanently failed if deterministic
                                    if current_uncertainty < 0.3:
                                        execution_ledger.append(
                                            f"[iter{iteration+1}] {tool_name} deterministic failure (uncertainty={current_uncertainty:.3f})"
                                        )

                        if result.success:
                            _no_real_progress_calls = 0  # real progress — reset stuck counter
                            # Track successful calls for dedup (retrieval tools only)
                            if tool_name in _SUCCESS_DEDUP_TOOLS:
                                success_call_signatures[_call_sig_h] = (
                                    success_call_signatures.get(_call_sig_h, 0) + 1
                                )
                            _raw_out = result.output
                            if _raw_out is None or str(_raw_out).strip() in ("", "None", "null"):
                                # Check if this empty result was a credential search
                                _args_str = str(arguments).lower()
                                _cred_search_signals = (
                                    "github_token", "gh_token", "github_pat",
                                    "personal_access_token", "token", "credential",
                                    "osxkeychain", "gh auth",
                                )
                                _is_cred_search = any(s in _args_str for s in _cred_search_signals)
                                if _is_cred_search:
                                    from core.tools.tool_registry import _CREDENTIAL_RECOVERY_HINT
                                    raw_output = (
                                        f"[EMPTY RESULT: {tool_name} returned nothing for this credential search. "
                                        "The token is NOT in the location you searched. "
                                        "You MUST try the remaining sources in this order before giving up:\n"
                                        + _CREDENTIAL_RECOVERY_HINT
                                        + "\nDo NOT skip to complete_task — try each source above first.]"
                                    )
                                else:
                                    raw_output = (
                                        f"[EMPTY RESULT: {tool_name} succeeded but returned no output. "
                                        "The operation may have found nothing, or the path/query returned "
                                        "an empty set. Try a different path, broader search pattern, or "
                                        "use list_directory to verify what exists.]"
                                    )
                            else:
                                raw_output = str(_raw_out)
                        else:
                            # result.error already contains enriched ToolErrorInfo text
                            # from tool_registry.execute_tool — use it directly.
                            raw_output = f"Error: {str(result.error or '')}"
                            # For code-execution tools, also surface stderr/stdout so the
                            # model can read the actual traceback and diagnose what failed.
                            # Without this, run_python failures only show "Process exited
                            # with code 1" and the model retries blind.
                            if isinstance(result.output, dict):
                                _stderr = (result.output.get('stderr') or '').strip()
                                _stdout = (result.output.get('stdout') or '').strip()
                                if _stderr:
                                    raw_output += f"\nstderr:\n{_stderr[:1200]}"
                                if _stdout:
                                    raw_output += f"\nstdout:\n{_stdout[:400]}"
                        if len(raw_output) > MAX_OUTPUT_CHARS:
                            tool_content = (
                                raw_output[:MAX_OUTPUT_CHARS]
                                + f"\n[TOOL OUTPUT TRUNCATED — {len(raw_output):,} chars total, "
                                f"first {MAX_OUTPUT_CHARS:,} shown. Use a narrower query or "
                                "read a specific line range to get the rest.]"
                            )
                        else:
                            tool_content = raw_output

                        # ── Shadow mode: log what the model actually receives ──────────
                        if _shadow_os.environ.get("TORIN_SHADOW_MODE"):
                            _preview = tool_content[:600].replace("\n", " ↵ ")
                            logger.info(
                                "[SHADOW] TOOL RESULT [%s] success=%s → %s",
                                tool_name, result.success, _preview
                            )

                        # Append as proper 'tool' role message — the model receives
                        # each result individually, exactly as OpenAI/Anthropic do.
                        conversation_history.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": tool_name,
                            "content": tool_content,
                        })
                        tool_results.append(make_tool_record(
                            tool=tool_name,
                            parameters=arguments,
                            success=result.success,
                            output_display=tool_content,
                            observation=_observation,
                        ))

                    # Track successful calls for no-progress loop detection.
                    # A "no-progress" call is one that succeeds but produces no new
                    # observable side-effect (e.g. patch_file delta_bytes=0, or
                    # reading the same file section repeatedly).
                    tool_calls_this_turn = regular_tool_calls
                    for _tr in tool_results[-len(tool_calls_this_turn):]:
                        if not _tr.get("success"):
                            continue
                        _tname = _tr.get("tool", "")
                        _tout = _tr.get("output", "")
                        # Build a fingerprint from key output signals
                        _fp = None
                        if _tname == "patch_file":
                            # Read the canonical observation instead of trying to
                            # json.loads() a Python repr() back into a dict. That
                            # parse ALWAYS raised (single quotes, and the string is
                            # truncated at 4000 chars) and was swallowed at debug
                            # level, so this no-op detector has never once fired.
                            for _o in (_tr.get("observation") or []):
                                if _o.get("claim") == "task changes have been applied to disk":
                                    if _o.get("relation") == "WEAKENS":   # delta_bytes == 0
                                        _params = _tr.get("parameters", {}) or {}
                                        _fp = (_tname, str(_params.get("file_path")
                                                           or _params.get("path", "")))
                                    break
                        elif _tname in ("read_file", "list_directory"):
                            # Use file_path + line range as the fingerprint key so that
                            # reading different sections of the same file resets the counter.
                            _params = _tr.get("parameters", {})
                            _path_key = (
                                _params.get("file_path") or _params.get("path") or
                                _params.get("directory") or _params.get("dir") or ""
                            )
                            if _path_key:
                                _sl = str(_params.get("start_line", ""))
                                _el = str(_params.get("end_line", ""))
                                _fp = (_tname, str(_path_key), _sl, _el)
                        if _fp:
                            _noprogress_calls[_fp] = _noprogress_calls.get(_fp, 0) + 1
                            if _noprogress_calls[_fp] >= MAX_NOPROGRESS_REPEATS:
                                _np_tool = _fp[0]
                                _np_arg  = _fp[1]
                                _np_nudge = (
                                    f"⚠️ LOOP DETECTED: '{_np_tool}' has been called {_noprogress_calls[_fp]}x "
                                    f"on '{_np_arg}' with no observable progress. "
                                )
                                if _np_tool == "patch_file":
                                    _np_nudge += (
                                        "The last patch changed 0 bytes — your old_string and "
                                        "new_string were identical or the file already has the "
                                        "content you tried to write. "
                                        "Read the file to see its CURRENT state, then decide: "
                                        "either the target file already contains your change "
                                        "(move on to testing) or identify a DIFFERENT section "
                                        "that still needs changing."
                                    )
                                else:
                                    _np_nudge += (
                                        f"You have read the same section of '{_np_arg}' "
                                        f"{_noprogress_calls[_fp]}x with no patch applied. "
                                        "You are searching the WRONG section of the file. "
                                        "Use grep_search to locate the exact function/section:\n"
                                        "  grep_search(pattern='function_name', path='<abs_file_path>')\n"
                                        "Then read_file on the lines it returns, and patch_file with verbatim content."
                                    )
                                conversation_history.append({"role": "user", "content": _np_nudge})
                                logger.warning(f"[iter{iteration+1}] No-progress loop detected: {_fp} x{_noprogress_calls[_fp]}")
                                # Reset counter so nudge fires again if loop continues
                                _noprogress_calls[_fp] = 0
                        else:
                            # A different successful tool call — reset the no-progress counter
                            # for all tools (real progress was made)
                            if _tname not in ("read_file", "list_directory", "search_code"):
                                _noprogress_calls.clear()

                    # Inject repeated-failure warning as a system nudge
                    if failed_tools:
                        repeatedly_failed = {name: count for name, count in failed_tools.items()
                                             if count >= MAX_TOOL_FAILURES}
                        if repeatedly_failed:
                            failed_list = ", ".join(
                                f"{n} ({c}x)" for n, c in repeatedly_failed.items()
                            )
                            # Check if any recent failure looked like a credential error.
                            # IMPORTANT: HTTP 403/404 from web_fetch/web_search means the
                            # site is blocked or the URL is wrong — NOT a missing API key.
                            # Only flag credential issues for non-web tools.
                            _recent_failures = [
                                r for r in tool_results[-6:] if not r.get("success")
                            ]
                            _web_tools = {"web_fetch", "web_search", "http_request", "fetch_page"}
                            _non_web_errors = " ".join(
                                str(r.get("output", ""))
                                for r in _recent_failures
                                if r.get("tool") not in _web_tools
                            ).lower()
                            _web_errors = " ".join(
                                str(r.get("output", ""))
                                for r in _recent_failures
                                if r.get("tool") in _web_tools
                            ).lower()
                            _cred_signals = ("token", "credential", "unauthorized", "401",
                                             "api key", "authentication")
                            _is_cred_failure = any(s in _non_web_errors for s in _cred_signals)
                            _is_web_access_failure = bool(_web_errors) and any(
                                s in _web_errors for s in ("403", "404", "forbidden", "not found")
                            )
                            _nudge = (
                                f"⚠️ Tools have repeatedly failed: {failed_list}. "
                            )
                            if _is_web_access_failure:
                                _nudge += (
                                    "Web fetch/search is returning 403/404 errors — these sites "
                                    "block automated access or the URLs are wrong. "
                                    "Do NOT search for authentication tokens — that will not help. "
                                    "Instead: use web_search to find real URLs from search results, "
                                    "then web_fetch only the URLs returned by the search."
                                )
                            elif _is_cred_failure:
                                from core.tools.tool_registry import _CREDENTIAL_RECOVERY_HINT
                                _nudge += (
                                    "This looks like a credential/auth issue. "
                                    "Try these sources in order before retrying:\n"
                                    + _CREDENTIAL_RECOVERY_HINT
                                )
                            else:
                                _nudge += (
                                    "Investigate the errors before retrying. "
                                    "Pivot to alternative approaches if the issue cannot be fixed."
                                )
                            conversation_history.append({
                                "role": "user",
                                "content": _nudge,
                            })

                elif completion_tc is None:
                    # No tool calls AND no completion proposal → model only produced text.
                    # Inject a corrective nudge so the next iteration actually uses tools.
                    logger.warning(f"[Iteration {iteration + 1}] Text-only response — injecting tool-use nudge")

                    _has_code_fence = "```" in content
                    _consecutive_text_only = getattr(self, '_consecutive_text_only', 0) + 1
                    self._consecutive_text_only = _consecutive_text_only

                    # Duplicate-content detection: if the model is generating the exact
                    # same non-tool response repeatedly, the generic nudge is not breaking
                    # the KV-cache loop.  Detect this and inject a stronger, structurally
                    # different message that forces a different generation path.
                    _last_tonly_content = getattr(self, '_last_text_only_content', None)
                    _is_stuck_loop = (
                        _last_tonly_content is not None
                        and content == _last_tonly_content
                        and _consecutive_text_only >= 2
                    )
                    self._last_text_only_content = content

                    # Build task-aware context for richer nudges
                    _used_tools = list({r.get("tool") for r in tool_results if r.get("success")})
                    _task_desc_snippet = (task.description or "")[:120] if hasattr(task, "description") else ""
                    _task_type_name = task.type.name if hasattr(task, "type") else "UNKNOWN"

                    if _is_stuck_loop:
                        # The model is generating IDENTICAL text every iteration.
                        # This commonly happens when a tool-output truncation marker
                        # (e.g. "[TOOL OUTPUT TRUNCATED]") leaked into a tool-call
                        # argument string, making the JSON invalid.  Both parse passes
                        # fail silently and the same nudge reproduces the same output.
                        # Use a radically different, highly specific nudge to break out.
                        _truncation_leaked = (
                            "TRUNCATED" in content
                            or "truncated" in content
                            or "(truncated, total:" in content
                        )
                        if _truncation_leaked:
                            _stuck_detail = (
                                "WARNING: your last response contained a truncation marker "
                                "(e.g. '[TOOL OUTPUT TRUNCATED]') INSIDE a tool argument value. "
                                "This makes the JSON invalid. Do NOT copy text from tool results "
                                "into argument strings. Use a clean, manually typed file path instead."
                            )
                        else:
                            _stuck_detail = (
                                f"Your last {_consecutive_text_only} responses were word-for-word "
                                "identical — the nudge is not breaking the loop. You must emit a "
                                "DIFFERENT tool call than before."
                            )
                        logger.warning(
                            f"[Iteration {iteration + 1}] STUCK-LOOP detected "
                            f"(streak={_consecutive_text_only}, truncation_leaked={_truncation_leaked}) "
                            "— injecting cache-breaking nudge"
                        )
                        _suggestion_map = {
                            "EXECUTION":  "search_files or list_directory to find a target file",
                            "RESEARCH":   "search_files with a keyword from your audit finding",
                            "ANALYSIS":   "list_directory on core/agents/autonomous/",
                            "SYNTHESIS":  "write_file to start the output document",
                        }
                        _next_step = _suggestion_map.get(
                            _task_type_name,
                            "list_directory on core/agents/autonomous/ to orient yourself",
                        )
                        _nudge = (
                            f"[LOOP BREAK REQUIRED — iteration {iteration + 1}] "
                            f"{_stuck_detail} "
                            f"Emit ONE <tool_call> right now: call {_next_step}. "
                            "No preamble. No explanation. Just the JSON."
                        )
                    elif _has_code_fence:
                        # Model wrote a code block instead of calling run_python
                        _nudge = (
                            "TOOL CALL REQUIRED. Do not write code blocks — call `run_python` "
                            "with your code as the `code` parameter. Emit the tool call now."
                        )
                    elif _consecutive_text_only == 1:
                        # First offence — short, direct; include task description so model knows its goal
                        if _task_desc_snippet:
                            _nudge = (
                                f"Make the tool call now. Your task is: {_task_desc_snippet}. "
                                "No preamble — emit the tool call JSON directly."
                            )
                        else:
                            _nudge = "Make the tool call now. No preamble."
                    elif _consecutive_text_only == 2:
                        _nudge = (
                            "Still no tool call. Stop generating explanations and emit the "
                            "<tool_call> JSON block directly. Nothing else."
                        )
                    else:
                        # Escalation — model is stuck; be specific about what to do next
                        _suggestion_map = {
                            "EXECUTION":           "run_command or write_file to apply the fix",
                            "RESEARCH":            "search_files or read_file on a relevant path",
                            "ANALYSIS":            "read_file or run_python to examine the data",
                            "SYNTHESIS":           "write_file to produce your summary document",
                            "SECURITY_REMEDIATION": "write_file to document the remediation or run_command to apply a fix",
                            "LEARNING":            "search_files or read_file to gather information",
                        }
                        _suggested_tool = _suggestion_map.get(_task_type_name, "read_file or search_files to orient yourself")
                        _nudge = (
                            f"[ESCALATION — {_consecutive_text_only} text-only responses in a row] "
                            f"Task type: {_task_type_name}. Tools used so far: {_used_tools or ['none']}. "
                            f"Next step for this task type: {_suggested_tool}. "
                            "Emit exactly one <tool_call> block now — no explanation before it."
                        )

                    execution_ledger.append(
                        f"[iter{iteration+1}] TEXT-ONLY (no tool calls, streak={_consecutive_text_only}) — nudged"
                        + (" [had code fence]" if _has_code_fence else "")
                    )
                    conversation_history.append({"role": "user", "content": _nudge})

            # Loop ended. This is reached both by exhausting max_iterations AND
            # by every early `break` (stagnation, convergence gate, budget). It
            # previously reported "Max iterations (200) reached" and
            # iterations_count=200 in ALL cases -- so a task that stopped after 5
            # iterations on the stagnation trap was recorded as having burned the
            # full budget. That false count fed tool_usage_history and the
            # failure message told the reflection loop the opposite of the truth.
            execution_time = int(time.time() - start_time)
            completed_iterations = iteration + 1

            if completed_iterations >= max_iterations:
                failure_reason = f'Max iterations ({max_iterations}) reached without completion'
            elif _termination_reason:
                failure_reason = (
                    f'Stopped early at iteration {completed_iterations}/{max_iterations} '
                    f'— {_termination_reason}'
                )
            else:
                failure_reason = (
                    f'Stopped early at iteration {completed_iterations}/{max_iterations} '
                    f'— no completion proposed'
                )
            logger.warning(f"Task {task.id} ended: {failure_reason}")

            await self._record_tool_usage_outcome(
                task=task,
                tool_results=tool_results,
                success=False,
                outcome_quality=0.2,
                confidence=0.3,
                execution_time_seconds=execution_time,
                iterations_count=completed_iterations,
                failure_reason=failure_reason,
                # Every way of reaching here is the approach failing to arrive:
                # the iteration budget ran out, or IterationController stopped
                # on TEMPORAL_LIMIT, STAGNANT or MAX_BUDGET. None of those is a
                # safety refusal or broken machinery — the tools ran, we stayed
                # in control, and the plan did not get there. That is the
                # selection's to answer for, and the case a learner most needs.
                outcome_class="strategy_failure",
            )
            asyncio.create_task(self._fire_reward_signals(
                task=task,
                tool_results=tool_results,
                success=False,
                # Unverified failure path: no verification score exists, so the
                # evaluator falls back to its own base rather than being handed
                # a fabricated one.
                verification_score=None,
                execution_time_seconds=execution_time,
                iterations_count=completed_iterations,
            ))

            return {
                'success': False,
                'error': failure_reason,
                'termination_reason': _termination_reason or 'no_completion_proposed',
                'task_id': task.id,
                'tool_results': tool_results,
                'iterations': completed_iterations,
                'max_iterations': max_iterations,
            }

        except Exception as e:
            import traceback
            import sys
            
            # Get full traceback with local variables for debugging
            exc_type, exc_value, exc_tb = sys.exc_info()
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            full_traceback = ''.join(tb_lines)
            
            # Extract the actual line that failed
            tb_frame = traceback.extract_tb(exc_tb)[-1] if exc_tb else None
            failed_location = f"{tb_frame.filename}:{tb_frame.lineno} in {tb_frame.name}" if tb_frame else "unknown"
            failed_line = tb_frame.line if tb_frame else "unknown"
            
            # Structured error output for debugging
            error_context = {
                "error_type": exc_type.__name__ if exc_type else "Unknown",
                "error_message": str(e),
                "failed_location": failed_location,
                "failed_line": failed_line,
                "task_id": task.id,
                "task_description": task.description[:200] if task.description else "N/A",
                "iteration": locals().get('iteration', 'N/A'),
                "max_iterations": locals().get('max_iterations', 'N/A'),
                "conversation_tokens": locals().get('conversation_tokens', 'NOT_SET'),
                "tool_results_count": len(tool_results) if 'tool_results' in locals() else 0,
            }
            
            # Log detailed error
            logger.error(
                f"❌ AGENT LOOP FAILURE\n"
                f"   Error: {error_context['error_type']}: {error_context['error_message']}\n"
                f"   Location: {failed_location}\n"
                f"   Line: {failed_line}\n"
                f"   Task: {task.id}\n"
                f"   Iteration: {error_context['iteration']}/{error_context['max_iterations']}\n"
                f"   Conversation Tokens: {error_context['conversation_tokens']}\n"
                f"   Tool Results: {error_context['tool_results_count']}"
            )
            
            # Print full traceback for console visibility
            logger.debug(
                "Full traceback (truncated): %s",
                full_traceback[-4000:] if len(full_traceback) > 4000 else full_traceback,
            )

            execution_time = int(time.time() - start_time)
            await self._record_tool_usage_outcome(
                task=task,
                tool_results=tool_results if 'tool_results' in locals() else [],
                success=False,
                outcome_quality=0.1,
                confidence=0.2,
                execution_time_seconds=execution_time,
                iterations_count=locals().get('iteration', 0),
                failure_reason=f"{error_context['error_type']}: {str(e)}",
                # An exception escaping the executor loop is broken machinery.
                # The tool selection was never fairly tested, so it must not be
                # charged for this.
                outcome_class="infrastructure_failure"
            )
            asyncio.create_task(self._fire_reward_signals(
                task=task,
                tool_results=tool_results if 'tool_results' in locals() else [],
                success=False,
                verification_score=None,
                execution_time_seconds=execution_time,
                iterations_count=locals().get('iteration', 0),
            ))

            return {
                'success': False,
                'error': str(e),
                'error_type': error_context['error_type'],
                'error_location': failed_location,
                'task_id': task.id,
                'iteration': error_context['iteration'],
                'iterations': locals().get('iteration', 0) + 1 if isinstance(locals().get('iteration'), int) else 0,
                'traceback': full_traceback[-2000:] if len(full_traceback) > 2000 else full_traceback  # Truncate if huge
            }

    async def _fire_reward_signals(
        self,
        task,
        tool_results: list,
        success: bool,
        verification_score: Optional[float],
        execution_time_seconds: int,
        iterations_count: int,
        epistemic_mutations: Optional[list] = None,
        tool_observations: Optional[list] = None,
    ) -> None:
        """
        Fire all reward and penalty signals after a task completes or fails.

        This is the missing link that wires three previously disconnected systems:

        1. ExperienceEvaluator  — computes outcome_quality, intrinsic_reward,
           constitutional_alignment, system_health_impact (all in [0,1]).

        2. IntrinsicMotivationSystem (negative rewards):
           - record_tool_failure: 2 consecutive failures → 3-iteration cooldown
           - record_tool_success: resets failure counter
           - track_tool_sequence: diversity enforcement, blocks repeated sequences

        3. Logs the intrinsic_reward so it's visible in traces / future DB write.

        Fires in both shadow mode and production.  All underlying calls degrade
        gracefully — DB errors are caught internally, no exceptions propagate.
        """
        # Stage results, so a partial fire is visible instead of looking like a
        # clean run. Independent cognitive effects must not share a failure
        # transaction: an evaluate_experience defect previously suppressed
        # tool-failure cooldowns and sequence-diversity learning, which do not
        # depend on it in any way.
        fired: Dict[str, Any] = {}

        async def _stage(name: str, coro_fn):
            """Run one reward stage with its own failure boundary."""
            try:
                result = await coro_fn()
                fired[name] = 'ok'
                return result
            except Exception as exc:
                fired[name] = f'failed: {type(exc).__name__}: {exc}'
                logger.warning("Reward stage '%s' failed (isolated): %s", name, exc)
                return None

        try:
            from core.agents.autonomous.intrinsic_motivation import get_intrinsic_motivation_system
            from core.agents.autonomous.experience_evaluator import ExperienceEvaluator
            from core.agents.autonomous.singleton_constitution import SingletonConstitution

            # ── Lazy-init intrinsic motivation singleton ──────────────────────
            if self._intrinsic_motivation is None:
                self._intrinsic_motivation = get_intrinsic_motivation_system()
            im = self._intrinsic_motivation

            # ── Lazy-init ExperienceEvaluator with constitution + IM ──────────
            if self.experience_evaluator is None:
                self.experience_evaluator = ExperienceEvaluator()
                _const = SingletonConstitution()
                await self.experience_evaluator.initialize(
                    constitution=_const,
                    intrinsic_motivation=im,
                )

            # ── Build outcome dict with code quality signals ──────────────────
            # Quality signals come from the canonical belief updates the
            # epistemic engine already derived, NOT from re-reading tool text.
            #
            # The substring version this replaces could not express "unknown",
            # and was wrong in three concrete ways: empty lint output read as
            # clean; a no-op patch_file read as a real change; and "3 failed,
            # 1 passed" read as passing because it contains "passed". The
            # canonical interpreter parses pytest counts, requires
            # delta_bytes != 0, and returns [] for unadjudicable output.
            from core.reasoning.epistemic_engine import summarize_tool_observations
            _quality_signals = summarize_tool_observations(tool_observations)
            _unknown = _quality_signals.pop("unknown", [])

            _outcome = {
                'success': success,
                # NOT 'outcome_quality' — the evaluator owns that name and
                # computes it. This is the verification system's completion
                # score, which becomes the evaluator's base.
                'verification_score': verification_score,
                # Only measured signals are present; absent != False.
                **_quality_signals,
            }
            if _unknown:
                logger.debug(
                    "Task %s: quality signals unmeasured (no licensing observation): %s",
                    task.id, ", ".join(_unknown),
                )

            # ── 1. Full 4-metric evaluation ───────────────────────────────────
            # Epistemic signals ride along in context so the curiosity reward has
            # REAL inputs. The engine derives them, not this call site: a bare
            # mutation count would force the reward layer to re-interpret what a
            # mutation means, creating a second reading of one observation.
            from core.reasoning.epistemic_engine import summarize_epistemic_mutations
            _epistemic = summarize_epistemic_mutations(epistemic_mutations)

            _task_type = task.type.value if hasattr(task.type, 'value') else str(task.type)
            evaluated = await _stage('evaluate_experience', lambda: self.experience_evaluator.evaluate_experience(
                task_id=task.id,
                task_type=_task_type,
                context={
                    'type': _task_type,
                    'task_description': task.description,
                    **_epistemic,
                },
                action={
                    'tool_results_count': len(tool_results),
                    'iterations': iterations_count,
                },
                outcome=_outcome,
                success=success,
                duration_seconds=float(execution_time_seconds),
                error_message=None if success else 'task failed',
            ))
            if evaluated is not None:
                logger.info(
                    f"Reward signals: task={task.id[:8]} success={success} "
                    f"quality={evaluated.outcome_quality:.2f} "
                    f"intrinsic={evaluated.intrinsic_reward:+.2f} "
                    f"alignment={evaluated.constitutional_alignment:.2f} "
                    f"health={evaluated.system_health_impact:.2f}"
                )

                # Persistence GENUINELY depends on evaluation — there is no
                # reward to persist without it. This is a real dependency, not
                # incidental bundling, so it stays nested.
                await _stage('persist_intrinsic_reward', lambda: im.log_intrinsic_reward(
                    task_id=task.id,
                    task_type=_task_type,
                    reward_value=evaluated.intrinsic_reward,
                    outcome_quality=evaluated.outcome_quality,
                    success=success,
                    extra={
                        'constitutional_alignment': evaluated.constitutional_alignment,
                        'system_health_impact': evaluated.system_health_impact,
                        'novel_patterns': evaluated.novel_patterns_discovered,
                        'competence_improved': evaluated.competence_improved,
                        # Which drives produced this reward, and which were
                        # unmeasurable. A reward without its provenance cannot
                        # be audited later.
                        'intrinsic_components': evaluated.intrinsic_components,
                    },
                ))
                # ── PRODUCTION PRODUCER for appraisal ────────────────────
                # Its own stage: depends on evaluation (no appraisal without an
                # evaluated experience) but must never suppress the independent
                # tool/sequence stages below.
                #
                # Consumes canonical MEANING only — evaluated metrics, the
                # epistemic summary, the quality signals — never raw tool
                # output. Signals with no canonical source here stay unmeasured
                # rather than being invented.
                async def _update_appraisal():
                    from core.agents.autonomous.appraisal import get_appraisal_system
                    _acted = [r for r in tool_results if r.get('tool')]
                    _rate = (sum(1 for r in _acted if r.get('success')) / len(_acted)
                             if _acted else None)
                    return get_appraisal_system().update(
                        outcome_quality=evaluated.outcome_quality,
                        intrinsic_reward=evaluated.intrinsic_reward,
                        epistemic=_epistemic,
                        action_success_rate=_rate,
                        risk_level=_outcome.get('risk_level'),
                        options_considered=len(getattr(self, '_last_capabilities', []) or []) or None,
                        self_initiated=(
                            getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'
                        ),
                    )
                await _stage('update_appraisal', _update_appraisal)
            else:
                fired['persist_intrinsic_reward'] = 'skipped: no evaluation'
                fired['update_appraisal'] = 'skipped: no evaluation'

            # ── 2. Per-tool signals — INDEPENDENT of evaluation ───────────────
            # Cooldowns after repeated tool failure are a safety behaviour. They
            # must fire even when appraisal is broken.
            async def _record_tool_outcomes():
                for r in tool_results:
                    _tool_name = r.get('tool', '')
                    if not _tool_name:
                        continue
                    if r.get('success'):
                        await im.record_tool_success(_tool_name)
                    else:
                        _err = str(r.get('error', r.get('output', 'unknown error')))[:200]
                        await im.record_tool_failure(_tool_name, r.get('params', {}), _err)
            await _stage('record_tool_outcomes', _record_tool_outcomes)

            # ── 3. Sequence diversity — INDEPENDENT of both above ─────────────
            async def _track_sequence():
                _seq = [r.get('tool') for r in tool_results if r.get('tool')]
                if _seq:
                    await im.track_tool_sequence(_seq)
            await _stage('track_tool_sequence', _track_sequence)

            _failed = {k: v for k, v in fired.items() if v != 'ok'}
            if _failed:
                logger.warning(
                    "Task %s: reward stages incomplete — %s", task.id, _failed
                )

        except Exception as _rse:
            logger.warning(f"_fire_reward_signals non-fatal error: {_rse}")

    async def _get_tools_by_capability(self, task_description: str, task_type=None) -> Dict[str, Any]:
        """
        Get tools using capability-based discovery instead of keyword matching.

        This replaces the old keyword-based filtering with semantic capability inference.
        The teacher model now requests capabilities (e.g., CAUSAL_REASONING, TEST_RESILIENCE)
        and the registry provides tools that declare those capabilities.
        """
        from core.tools.capabilities import infer_capability_from_task, Capability

        # Step 1: Infer capabilities needed from task description
        inferred_capabilities = infer_capability_from_task(task_description, threshold=0.5)

        if not inferred_capabilities:
            # Fallback: if no capabilities inferred, use low-threshold to get some tools
            inferred_capabilities = infer_capability_from_task(task_description, threshold=0.3)

        # Step 1b: Force web/research capabilities for RESEARCH task type.
        # The regex patterns require specific phrases ("research paper", "web search")
        # that don't appear in all research task descriptions, so we guarantee these
        # capabilities are included whenever the task type is explicitly RESEARCH.
        try:
            from core.agents.autonomous.shared_types import TaskType
            if task_type is not None and task_type == TaskType.RESEARCH:
                for cap in (Capability.WEB_SEARCH, Capability.FETCH_PAGE, Capability.CONDUCT_RESEARCH, Capability.HTTP_REQUEST):
                    if cap not in inferred_capabilities:
                        inferred_capabilities[cap] = 8.0
        except Exception:
            pass

        # Step 2: Get tools providing these capabilities
        relevant_tools = {}
        seen_tools = set()

        for capability, confidence in inferred_capabilities.items():
            # Get ALL providers for this capability (not just the best one)
            # LLM will choose which tool to use based on context
            providers = self.tool_registry.find_providers(capability)

            for provider in providers:
                if provider and provider.name not in seen_tools:
                    relevant_tools[provider.name] = provider
                    seen_tools.add(provider.name)
                    logger.debug(f"Capability {capability.value} → {provider.name} (confidence: {confidence:.2f})")

        # Step 3: Always include core operational tools (filesystem, execution, etc.)
        # These are needed for basic operations regardless of capability inference.
        # Uses get_tools_by_category() which supports lazy loading — list_tools()
        # only returned eager-loaded tools (always 0 when all tools are lazy).
        # 'testing' is always included so run_pytest / chaos tools are available
        # for any audit, analysis, or verification task.
        core_tool_categories = ['filesystem', 'execution', 'system', 'testing']
        for cat in core_tool_categories:
            for tool in self.tool_registry.get_tools_by_category(cat):
                if tool.name not in seen_tools:
                    relevant_tools[tool.name] = tool
                    seen_tools.add(tool.name)

        # Step 4: Exclude AgentSO connector tools (require active context)
        filtered_tools = {}
        for tool_name, tool in relevant_tools.items():
            # Skip connector tools (they're prefixed with platform names)
            if any(tool_name.startswith(prefix) for prefix in [
                'virustotal_', 'crowdstrike_', 'misp_', 'splunk_', 'elastic_',
                'github_', 'snyk_', 'sonarqube_', 'qradar_', 'arcsight_',
                'logrhythm_', 'shodan_', 'alienvaultotx_', 'threatconnect_',
                'recordedfuture_', 'thehive_', 'shuffle_', 'qualys_',
                'awssecurityhub_', 'azuresecuritycenter_', 'pagerduty_', 'restapi_'
            ]):
                continue
            filtered_tools[tool_name] = tool

        logger.info(f"🎯 Capability-based discovery: {len(filtered_tools)} tools selected for task")
        logger.info(f"   Inferred capabilities: {[cap.value for cap in inferred_capabilities.keys()][:5]}")

        return filtered_tools

    async def _format_tools_for_llm(self, tools: Dict[str, Any], task_description: str = "") -> str:
        """Format tool registry for LLM consumption with smart filtering based on task"""

        import re
        task_lower = task_description.lower()
        relevant_category_names = set()

        # FIRST: ALWAYS exclude AgentSO connector tools from autonomous execution
        # Connectors require active AgentSO context and will fail in autonomous mode
        base_tools = {}
        for tool_name, tool in tools.items():
            # Skip connector tools (they're prefixed with security platform names)
            if any(tool_name.startswith(prefix) for prefix in [
                'virustotal_', 'crowdstrike_', 'misp_', 'splunk_', 'elastic_',
                'github_', 'snyk_', 'sonarqube_', 'qradar_', 'arcsight_',
                'logrhythm_', 'shodan_', 'alienvaultotx_', 'threatconnect_',
                'recordedfuture_', 'thehive_', 'shuffle_', 'qualys_',
                'awssecurityhub_', 'azuresecuritycenter_', 'pagerduty_', 'restapi_'
            ]):
                continue
            base_tools[tool_name] = tool

        logger.debug(
            "[TOOL FILTER] Excluded %s AgentSO connector tools from autonomous execution",
            (len(tools) - len(base_tools)),
        )

        # Check if any tool names are mentioned directly in the task
        mentioned_tool_names = set()
        for tool_name in base_tools.keys():
            if tool_name.lower() in task_lower:
                mentioned_tool_names.add(tool_name)

        # Add categories from mentioned tools
        if mentioned_tool_names:
            for tool_name in mentioned_tool_names:
                tool = base_tools[tool_name]
                if hasattr(tool, 'category'):
                    tool_category = tool.category.value if hasattr(tool.category, 'value') else str(tool.category)
                    relevant_category_names.add(tool_category)

        # WEIGHTED keyword matching with domain-specific signals
        # Format: category -> [(keyword, weight), ...]
        # High weight (3.0) = domain-specific, Low weight (0.5) = generic
        category_keywords_weighted = {
            'filesystem': [
                ('file', 1.5), ('directory', 2.0), ('folder', 2.0), ('path', 1.0),
                ('write', 1.0), ('read', 0.8), ('delete', 1.5), ('move', 1.5), ('copy', 1.5)
            ],
            'execution': [
                ('execute', 1.5), ('command', 1.5), ('bash', 3.0), ('shell', 3.0), ('script', 2.0), ('process', 1.0)
            ],
            'network': [
                ('http', 3.0), ('api', 2.5), ('fetch', 2.0), ('download', 2.0), ('upload', 2.0),
                ('url', 2.5), ('endpoint', 3.0), ('request', 1.5)
            ],
            'communication': [
                ('slack', 3.0), ('webhook', 3.0), ('notification', 2.0), ('email', 3.0), ('notify', 2.0)
            ],
            'code_generation': [
                ('refactor', 3.0), ('implement', 2.0), ('build', 1.5), ('generate', 1.0)
            ],
            'code_analysis': [
                ('complexity', 3.0), ('quality', 2.0), ('lint', 3.0), ('review', 1.5)
            ],
            'security': [
                ('encrypt', 3.0), ('decrypt', 3.0), ('hash', 2.5), ('password', 2.5),
                ('threat', 3.0), ('vulnerability', 3.0), ('security', 2.0)
            ],
            'documentation': [
                ('readme', 3.0), ('docs', 2.0), ('documentation', 2.5), ('diagram', 2.5)
            ],
            'testing': [
                ('pytest', 3.0), ('unittest', 3.0), ('benchmark', 2.5)
            ],
            'data_processing': [
                ('parse', 2.0), ('json', 2.0), ('yaml', 3.0), ('csv', 3.0), ('transform', 2.0), ('convert', 1.5)
            ],
            'monitoring': [
                ('cpu', 3.0), ('disk', 3.0), ('monitor', 2.5), ('metrics', 2.5),
                ('resource', 1.5), ('health', 2.0), ('profiling', 3.0)
            ],
            'system': [
                ('clipboard', 3.0), ('system_info', 3.0), ('status', 1.0)
            ],
            'ai_ml': [
                ('training', 3.0), ('inference', 3.0), ('embedding', 3.0), ('semantic', 2.5), ('neural', 2.5)
            ],
            'database': [
                ('sql', 3.0), ('mysql', 3.0), ('postgresql', 3.0), ('query', 2.5), ('schema', 2.5)
            ],
            'research': [
                # ONLY domain-shaping tokens - removed all generic words
                ('domain', 2.5), ('expansion', 2.5), ('capability', 2.0), ('novelty', 3.0),
                ('gap', 2.0), ('unknown', 1.5), ('frontier', 3.0), ('breakthrough', 3.0),
                ('innovative', 2.5), ('exploration', 2.0)
            ]
        }

        # Score categories by weighted keyword matches (BASE SCORES)
        from collections import defaultdict
        category_scores = defaultdict(float)

        for category, weighted_keywords in category_keywords_weighted.items():
            for keyword, weight in weighted_keywords:
                if re.search(r'\b' + re.escape(keyword) + r'\b', task_lower):
                    category_scores[category] += weight

        # ADAPTIVE LEARNING: Apply historical success multipliers
        # This adjusts base keyword scores based on what's worked before for similar intents
        try:
            from core.learning.adaptive_tool_owner import get_adaptive_tool_learning

            # ONE learning subsystem, not a reader constructed here and a writer
            # constructed elsewhere. The previous code built its own scorer via
            # get_adaptive_category_scores(db_manager=self.db_manager) — an
            # attribute this class never assigns — while the write path built its
            # own recorder behind `if self.db_manager:`. The reader silently
            # recovered through an internal fallback; the writer did not, so the
            # loop looked like a permanent cold start.
            atl = getattr(self, "adaptive_tool_learning", None) or \
                  get_adaptive_tool_learning(getattr(self, "db_manager", None))

            # The decision is CAPTURED, not recomputed at feedback time. Held on
            # the executor so observe() credits this exact selection — including
            # the ranking snapshot — rather than a reconstruction.
            selection = await atl.select(
                task_id=getattr(self, "_current_task_id", "") or "",
                task_description=task_description,
                base_category_scores=dict(category_scores),
                ranked_tools=getattr(self, "_last_ranked_tools", None),
            )
            self._current_selection = selection
            category_scores = selection.final_category_scores
        except Exception as e:
            logger.warning(f"Adaptive learning unavailable, using base scores: {e}")
            # Continue with base keyword scores

        # PRIORITIZATION: Sort by score and take top N categories
        # This prevents tool explosion from adding all categories >= threshold
        sorted_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)

        # DYNAMIC THRESHOLD: Use absolute AND relative thresholds (defined outside if block to avoid UnboundLocalError)
        # Accept if: score >= 2.0 OR (top_score >= 2.0 AND score >= top_score * 0.5)
        ABSOLUTE_THRESHOLD = 2.0
        MAX_CATEGORIES = 3  # Limit tool exposure

        if sorted_categories:
            top_score = sorted_categories[0][1]

            accepted_categories = []
            for category, score in sorted_categories[:MAX_CATEGORIES * 2]:  # Consider top 6
                # Accept if meets absolute threshold
                if score >= ABSOLUTE_THRESHOLD:
                    accepted_categories.append((category, score))
                # Or if it's close to top score (within 50%)
                elif top_score >= ABSOLUTE_THRESHOLD and score >= top_score * 0.5:
                    accepted_categories.append((category, score))

            # Take top MAX_CATEGORIES
            for category, score in accepted_categories[:MAX_CATEGORIES]:
                relevant_category_names.add(category)

            # Log scoring for debugging
            if accepted_categories:
                score_summary = ", ".join([f"{cat}={score:.1f}" for cat, score in accepted_categories[:5]])
                logger.debug(f"[TOOL FILTER] Category scores: {score_summary}")
                logger.debug(f"Category scores: {dict(sorted_categories[:10])}")

        # If still no confident matches, use semantic similarity as fallback
        if not relevant_category_names:
            logger.debug(
                f"[TOOL FILTER] No confident keyword matches (threshold={ABSOLUTE_THRESHOLD}), using semantic fallback"
            )

            # Category descriptions for semantic matching
            category_descriptions = {
                'research': 'explore new domains, discover novel capabilities, investigate unknown areas, expand knowledge frontiers',
                'monitoring': 'profile performance, track metrics, measure resource usage, analyze system health',
                'ai_ml': 'train models, run inference, generate embeddings, semantic analysis',
                'database': 'query data, manage schemas, store information, retrieve records',
                'filesystem': 'manage files and directories, read and write data',
                'code_analysis': 'analyze code quality, review complexity, lint source code'
            }

            # Simple semantic match: check if task contains category description words
            best_match_score = 0
            best_match_category = None
            for cat, desc in category_descriptions.items():
                desc_words = set(desc.lower().split())
                task_words = set(task_lower.split())
                overlap = len(desc_words & task_words)
                if overlap > best_match_score:
                    best_match_score = overlap
                    best_match_category = cat

            if best_match_category and best_match_score >= 2:
                relevant_category_names.add(best_match_category)
                logger.debug(
                    f"[TOOL FILTER] Semantic match: '{best_match_category}' (overlap={best_match_score})"
                )
            else:
                # Minimal fallback - only essential categories
                logger.debug("[TOOL FILTER] Using minimal fallback categories")
                relevant_category_names = {'filesystem', 'system', 'monitoring'}

        # Filter tools by category
        filtered_tools = {}
        for tool_name, tool in base_tools.items():
            if hasattr(tool, 'category'):
                tool_category = tool.category.value if hasattr(tool.category, 'value') else str(tool.category)
                if tool_category in relevant_category_names:
                    filtered_tools[tool_name] = tool

        tools_to_show = filtered_tools if filtered_tools else base_tools
        logger.info(f"Filtered {len(tools)} tools → {len(tools_to_show)} by categories: {relevant_category_names}")

        # Format the selected tools
        lines = []
        for tool_name, tool in tools_to_show.items():
            # Build parameter specification with types, enums, defaults
            param_specs = []
            if hasattr(tool, 'parameters') and tool.parameters:
                for p in tool.parameters:
                    if hasattr(p, 'name'):
                        # Build detailed param spec
                        param_str = p.name

                        # Add type
                        if hasattr(p, 'type'):
                            param_str += f": {p.type}"

                        # Add enum values (CRITICAL for LLM to know valid values)
                        if hasattr(p, 'enum') and p.enum:
                            param_str += f" (one of: {', '.join(map(str, p.enum))})"

                        # Add default value
                        elif hasattr(p, 'default') and p.default is not None:
                            param_str += f" = {p.default}"

                        # Mark as optional if not required
                        if hasattr(p, 'required') and not p.required:
                            param_str += " [optional]"

                        param_specs.append(param_str)
                    elif isinstance(p, str):
                        param_specs.append(p)
                    elif isinstance(p, dict) and 'name' in p:
                        param_specs.append(p['name'])

                params = ", ".join(param_specs)
            else:
                params = ""

            description = tool.description if hasattr(tool, 'description') else 'No description'
            lines.append(f"- {tool_name}({params}): {description}")

        return "\n".join(lines)

    def _format_conversation(self, history: List[Dict]) -> str:
        """Format conversation history for LLM"""
        parts = []
        for msg in history:
            role = msg['role'].upper()
            content = msg['content']
            parts.append(f"{role}: {content}")
        return "\n\n".join(parts)

    def _parse_agent_response(self, content: str) -> Dict[str, Any]:
        """Parse LLM response for tool calls or completion status"""
        try:
            # Try to extract JSON from response
            if '```json' in content:
                json_str = content.split('```json')[1].split('```')[0].strip()
                logger.info("Extracted JSON from ```json block")
            elif '```' in content:
                json_str = content.split('```')[1].split('```')[0].strip()
                logger.info("Extracted JSON from ``` block")
            elif '{' in content and '}' in content:
                # Find JSON object - start from first { and extract just the first complete object
                start = content.find('{')
                json_str = content[start:]
                logger.info(f"Extracting JSON from {{ onwards: length={len(json_str)}")
            else:
                logger.warning(f"No JSON found in LLM response (no braces)")
                return {}

            # Strip inline comments (// and # comments) that LLM sometimes adds
            # JSON doesn't support comments, but LLMs often add them
            # IMPORTANT: Don't remove // inside quoted strings (like URLs https://)
            import re

            # Remove inline comments: match // or # followed by text, but NOT inside quoted strings
            # This handles: "key": "value", // comment  OR  "key": "value"  # comment
            # But preserves: "url": "https://example.com"
            def remove_json_comments(text):
                lines = text.split('\n')
                cleaned_lines = []
                for line in lines:
                    # Check if line has // or # outside of quoted strings
                    in_quotes = False
                    quote_char = None
                    cleaned_line = []
                    i = 0
                    while i < len(line):
                        char = line[i]

                        # Track if we're inside quotes
                        if char in ('"', "'") and (i == 0 or line[i-1] != '\\'):
                            if not in_quotes:
                                in_quotes = True
                                quote_char = char
                            elif char == quote_char:
                                in_quotes = False
                                quote_char = None

                        # If we hit // outside quotes, stop processing this line
                        if not in_quotes and i < len(line) - 1 and char == '/' and line[i+1] == '/':
                            break

                        # If we hit # outside quotes, stop processing this line
                        # But skip if # is part of a string like "#ffffff" (color code)
                        if not in_quotes and char == '#':
                            break

                        cleaned_line.append(char)
                        i += 1

                    cleaned_lines.append(''.join(cleaned_line).rstrip())

                return '\n'.join(cleaned_lines)

            json_str = remove_json_comments(json_str)

            # Remove trailing commas before closing brackets/braces (common LLM error)
            # This handles cases like: {"key": "value",} or ["item1", "item2",]
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)

            # CRITICAL FIX: Use raw_decode to parse ONLY the first complete JSON object
            # This handles cases where LLM outputs: {valid json} \n commentary \n {more json}
            # json.loads() would fail with "Extra data" error, but raw_decode extracts just the first object
            decoder = json.JSONDecoder()
            parsed, end_idx = decoder.raw_decode(json_str)

            # Log if there's extra data after the first JSON object (for debugging)
            if end_idx < len(json_str.strip()):
                extra_data = json_str[end_idx:].strip()
                if extra_data:
                    logger.debug(f"Extracted first JSON object, ignoring {len(extra_data)} chars of extra data")
                    logger.debug(f"Extra data preview: {extra_data[:200]}")

            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            logger.error(f"Extracted json_str length: {len(json_str) if 'json_str' in locals() else 'N/A'}")
            if 'json_str' in locals():
                logger.error(f"First 500 chars: {json_str[:500]}")
                logger.error(f"Last 500 chars: {json_str[-500:]}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error parsing response: {e}")
            return {}

    async def _execute_tools(self, tool_calls: List[Dict]) -> List[Dict]:
        """Execute list of tool calls"""
        results = []
        for i, call in enumerate(tool_calls, 1):
            tool_name = call.get('tool')
            params = call.get('parameters', {})

            # Show progress in real-time
            logger.info(f"🔧 Calling tool [{i}/{len(tool_calls)}]: {tool_name}")

            # Show key parameters (limit to avoid clutter)
            param_preview = {k: (v[:50] + '...' if isinstance(v, str) and len(v) > 50 else v)
                           for k, v in list(params.items())[:3]}
            if param_preview:
                logger.debug(f"Tool parameters preview: {param_preview}")

            try:
                result = await self.tool_registry.execute_tool(tool_name, params)

                # Show result status
                status_icon = "✓" if result.success else "✗"
                logger.info(f"{status_icon} {tool_name} success={result.success}")

                # CRITICAL: Show error details when tool fails and pass to AI
                if not result.success:
                    error_msg = result.error or str(result.output)
                    logger.warning(f"Tool {tool_name} error: {error_msg}")
                    # Send error message to AI so it can learn from failures
                    output_for_ai = error_msg
                else:
                    output_for_ai = str(result.output)

                results.append({
                    'tool': tool_name,
                    'parameters': params,
                    'success': result.success,
                    'output': output_for_ai
                })
            except Exception as e:
                logger.exception(f"Tool {tool_name} raised exception")
                results.append({
                    'tool': tool_name,
                    'parameters': params,
                    'success': False,
                    'output': f"Error: {e}"
                })
        return results

    async def _record_tool_usage_outcome(
        self,
        task: Task,
        tool_results: List[Dict],
        success: bool,
        outcome_quality: Optional[float] = None,
        confidence: Optional[float] = None,
        execution_time_seconds: Optional[int] = None,
        iterations_count: Optional[int] = None,
        failure_reason: Optional[str] = None,
        outcome_class: Optional[str] = None,
    ):
        """
        Record tool usage outcome for adaptive learning.

        This is the feedback loop that enables the system to learn which
        tools work best for which types of tasks.

        `outcome_class` says WHY the task ended as it did. It is deliberately
        not derived from `success`: a bare boolean cannot distinguish "these
        tools were the wrong choice" from "the LLM timed out", and recording the
        second as a selection failure teaches a false causal relation. A caller
        that does not know defaults to `indeterminate`, which earns no credit —
        losing an observation is recoverable, inventing one is not.
        """
        if outcome_class is None:
            outcome_class = "indeterminate"
        try:
            from core.learning.adaptive_tool_learning import ToolUsageRecorder, IntentClassifier

            # Extract tool categories and names from results
            tool_categories_used = set()
            tool_names_used = set()

            for result in tool_results:
                tool_name = result.get('tool', '')
                tool_names_used.add(tool_name)

                # Look up tool category from registry
                if self.tool_registry:
                    try:
                        tool_obj = self.tool_registry.get_tool(tool_name)
                        if tool_obj and hasattr(tool_obj, 'category'):
                            category = tool_obj.category.value if hasattr(tool_obj.category, 'value') else str(tool_obj.category)
                            tool_categories_used.add(category)
                    except:
                        pass  # Tool not found, skip

            # Credit the decision that was actually made.
            #
            # This used to re-run IntentClassifier on task.description at
            # feedback time — learning from a RECONSTRUCTION of the decision
            # rather than the decision. Deterministic today, but any change to
            # keyword weights, the tool registry or accumulated affinity
            # silently rewrites history and credit lands on a choice never taken.
            #
            # It was also gated on `self.db_manager`, an attribute never assigned
            # on this class, so nothing was ever written at all.
            from core.learning.adaptive_tool_owner import get_adaptive_tool_learning

            atl = getattr(self, "adaptive_tool_learning", None) or \
                  get_adaptive_tool_learning(getattr(self, "db_manager", None))
            selection = getattr(self, "_current_selection", None)

            if selection is None:
                logger.warning(
                    "no captured selection for %s — skipping tool-selection "
                    "learning rather than crediting a reconstructed decision",
                    task.id[:8],
                )
            else:
                primary = next(iter(tool_names_used), None)
                learn_outcome = await atl.observe(
                    selection=selection,
                    outcome_class=outcome_class,
                    task_success=success,
                    tool_names_used=list(tool_names_used),
                    tool_categories_used=list(tool_categories_used),
                    primary_tool=primary,
                    execution_time_seconds=execution_time_seconds,
                    iterations_count=iterations_count,
                    failure_reason=failure_reason,
                    outcome_quality=outcome_quality,
                )
                logger.info(
                    f"Tool-selection learning: task={task.id[:8]} "
                    f"intent={selection.intent.value} credit={learn_outcome.credit_eligible} "
                    f"({learn_outcome.credit_reason}) score={learn_outcome.selection_score}"
                )
                self._current_selection = None
        except Exception as e:
            logger.warning(f"Failed to record tool usage outcome: {e}")
            # Don't let recording failures block task completion

    async def _capture_task_memory(
        self,
        task,
        tool_results: list,
        success: bool,
        summary: str,
        confidence: float,
        execution_time: int,
        iterations: int
    ) -> None:
        """
        Persist a PROCEDURAL memory for this task execution (background task, never raises).

        Records the tool sequence and outcome so the system can recognise
        similar tasks in the future and replicate or avoid the same approach.
        """
        try:
            # Build a compact tool-sequence description
            tools_used = [r.get('tool', 'unknown') for r in tool_results]
            successful_tools = [r.get('tool', 'unknown') for r in tool_results if r.get('success')]
            failed_tools = [r.get('tool', 'unknown') for r in tool_results if not r.get('success')]

            outcome_label = "SUCCESS" if success else "FAILURE"
            tool_seq = " → ".join(tools_used) if tools_used else "no tools"

            content = (
                f"Task [{outcome_label}]: {task.description[:400]}\n\n"
                f"Tool sequence ({iterations} iterations, {execution_time}s): {tool_seq}\n"
            )
            if successful_tools:
                content += f"Effective tools: {', '.join(set(successful_tools))}\n"
            if failed_tools:
                content += f"Failed tools: {', '.join(set(failed_tools))}\n"
            if summary:
                content += f"\nOutcome: {summary[:300]}"

            importance = 0.5 + (0.3 if success else 0.1) + min(len(tools_used) * 0.02, 0.2)
            importance = min(importance, 1.0)

            tags = ["procedural", "task_execution", outcome_label.lower()]
            task_type = getattr(task, 'task_type', None)
            if task_type:
                tags.append(str(task_type).lower())

            try:
                from core.memory.utils.interfaces import MemoryType
                mem_type = MemoryType.PROCEDURAL
            except ImportError:
                mem_type = None

            success_stored, memory_id = await self.memory_agent.store_memory(
                content=content,
                memory_type=mem_type,
                importance_score=importance,
                confidence_score=confidence,
                tags=tags,
                source_context={
                    "source": "general_purpose_executor",
                    "task_id": task.id,
                    "task_type": str(task_type) if task_type else None,
                    "success": success,
                    "execution_time_seconds": execution_time,
                    "iterations": iterations,
                    "tools_used": list(set(tools_used)),
                },
            )

            if success_stored:
                logger.debug(f"Procedural memory stored for task {task.id[:8]} → memory_id={memory_id}")
            else:
                logger.debug(f"Procedural memory rejected by filter for task {task.id[:8]}")

        except Exception as e:
            logger.warning(f"_capture_task_memory failed for task {getattr(task, 'id', '?')}: {e}")

    async def _capture_semantic_task_memory(
        self,
        task,
        conversation_history: list,
        success: bool,
        summary: str,
        confidence: float,
        execution_time: int,
        iterations: int
    ) -> None:
        """
        Persist a SEMANTIC memory by compressing the full task conversation
        via the 8B lightweight model.

        This is the richest knowledge artifact: it captures WHAT was learned,
        discovered, decided, and concluded — not just which tools were called.
        Future tasks that retrieve this memory get a pre-synthesized, high-quality
        context block instead of disconnected raw facts.

        Memory lifecycle (mirrors Claude/GPT pattern):
          1. Memories injected at task start → baked into conversation
          2. 8B compresses mid-task when context fills up (window management)
          3. At task end, 8B compresses the FINAL conversation → stored as
             semantic memory.  This is the memory that future tasks retrieve.
        """
        task_id_short = getattr(task, 'id', 'unknown')[:8]
        try:
            # Flatten conversation for the 8B compression model.
            # Tool-role messages are folded into user-side context so the
            # compressor (which understands only system/user/assistant) gets
            # a clean signal without losing any information.
            messages = []
            for msg in conversation_history:
                role = msg.get('role', 'user')
                content = msg.get('content') or ''
                if role == 'tool':
                    tool_name = msg.get('name', 'tool')
                    content = f"[{tool_name} result]: {content}"
                    role = 'user'
                elif role == 'assistant' and msg.get('tool_calls'):
                    tc_names = ', '.join(
                        tc.get('function', {}).get('name', '?')
                        for tc in (msg.get('tool_calls') or [])
                        if isinstance(tc, dict)
                    )
                    if content:
                        content = f"{content}\n[Called tools: {tc_names}]"
                    else:
                        content = f"[Called tools: {tc_names}]"
                if content:
                    messages.append((role, content))

            outcome_label = 'SUCCESS' if success else 'FAILURE'

            if len(messages) <= 2:
                # Conversation too short to compress meaningfully.
                # Build a richer fallback that still captures task context,
                # what was attempted, the outcome, and why it matters.
                if not summary:
                    logger.debug(f"Semantic memory skipped for {task_id_short}: no summary and short conversation")
                    return

                task_type = getattr(task, 'task_type', None) or getattr(task, 'type', None)
                task_type_str = str(task_type.value if hasattr(task_type, 'value') else task_type) if task_type else 'general'

                # Pull the last assistant turn if it exists
                last_response = ''
                for msg in reversed(conversation_history):
                    if msg.get('role') == 'assistant' and msg.get('content'):
                        last_response = msg['content'][:600]
                        break

                content = (
                    f"Task ({task_type_str}) [{outcome_label}]: {task.description[:400]}\n\n"
                    f"Execution: {iterations} iteration(s), {execution_time}s, "
                    f"confidence {confidence:.0%}\n\n"
                    f"Summary: {summary[:600]}"
                )
                if last_response:
                    content += f"\n\nFinal response excerpt:\n{last_response}"

            else:
                # Use 8B model to compress the full conversation into a
                # knowledge-dense summary.  This is the same compression
                # pipeline used mid-task, but the output is STORED instead
                # of discarded.
                logger.debug(f"Compressing {len(messages)}-message conversation for semantic memory [{task_id_short}]")
                try:
                    compressed = await self.context_manager.compression.compress_context(
                        messages=messages,
                        target_ratio=0.3,   # Aggressive — distill to core knowledge
                        preserve_recent=0,  # Compress everything, this is archival
                        use_llm=True        # Use 8B for semantic compression
                    )
                except Exception as compress_err:
                    logger.warning(
                        f"Semantic compression failed for task {task_id_short} "
                        f"({len(messages)} messages): {compress_err} — falling back to summary"
                    )
                    compressed = None

                if compressed and compressed.compressed_text.strip():
                    knowledge_block = compressed.compressed_text[:1500]
                    compression_note = f"(8B-compressed from {len(messages)} messages)"
                else:
                    # Compression failed or empty — build a reasonable fallback
                    # from the summary + first/last assistant turns
                    logger.info(
                        f"Semantic compression empty for task {task_id_short} — "
                        f"using summary fallback"
                    )
                    excerpts = []
                    for msg in conversation_history:
                        if msg.get('role') == 'assistant' and msg.get('content'):
                            excerpts.append(msg['content'][:300])
                            if len(excerpts) >= 3:
                                break
                    knowledge_block = summary[:600]
                    if excerpts:
                        knowledge_block += "\n\nKey response excerpts:\n" + "\n---\n".join(excerpts)
                    compression_note = f"(summary fallback, {len(messages)} messages not compressible)"

                content = (
                    f"Task [{outcome_label}]: {task.description[:400]}\n\n"
                    f"Outcome: {outcome_label} — {iterations} iteration(s), "
                    f"{execution_time}s, confidence {confidence:.0%} {compression_note}\n\n"
                    f"Knowledge Summary:\n{knowledge_block}"
                )

            # Calculate importance: successful insights are more valuable
            importance = 0.6 + (0.2 if success else 0.0) + min(iterations * 0.01, 0.1)
            importance = min(importance, 1.0)

            tags = ["semantic", "task_knowledge"]
            tags.append("8b_compressed" if len(messages) > 2 else "summary_fallback")
            tags.append("success" if success else "failure")
            task_type = getattr(task, 'task_type', None)
            if task_type:
                tags.append(str(task_type).lower())

            try:
                from core.memory.utils.interfaces import MemoryType
                mem_type = MemoryType.SEMANTIC
            except ImportError:
                mem_type = None

            success_stored, memory_id = await self.memory_agent.store_memory(
                content=content,
                memory_type=mem_type,
                importance_score=importance,
                confidence_score=confidence,
                tags=tags,
                source_context={
                    "source": "general_purpose_executor",
                    "memory_class": "semantic_task_knowledge",
                    "task_id": task.id,
                    "task_type": str(task_type) if task_type else None,
                    "success": success,
                    "execution_time_seconds": execution_time,
                    "iterations": iterations,
                    "conversation_turns": len(messages),
                    "compression_model": "qwen3-8b",
                },
            )

            if success_stored:
                logger.info(
                    f"✓ Semantic memory stored: task={task_id_short}, "
                    f"memory_id={memory_id}, {len(content)} chars, "
                    f"{len(messages)} conversation turns"
                )
            else:
                logger.warning(
                    f"✗ Semantic memory REJECTED by filter: task={task_id_short}, "
                    f"outcome={outcome_label}, importance={importance:.2f}, "
                    f"content_len={len(content)}"
                )

        except Exception as e:
            import traceback
            logger.error(
                f"_capture_semantic_task_memory FAILED for task {task_id_short}: "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )

    async def _persist_epistemic_output(
        self, task: Task, outputs: Dict
    ) -> list:
        """
        Apply structured epistemic output from LLM to the belief/hypothesis graph.

        Parses outputs["hypotheses"] and outputs["belief_updates"], passes them
        to EpistemicEngine.apply_llm_output(), and returns the mutation list.

        If the task is tagged requires_epistemic_output and no mutations occur,
        raises EpistemicNoOpError (rejecting completion).

        The coordinator reads result["epistemic_mutations"] (the list).
        It never inspects the belief graph directly.
        """
        from core.reasoning.epistemic_engine import (
            EpistemicNoOpError,
            get_epistemic_engine,
        )

        engine = get_epistemic_engine()
        try:
            mutations = await engine.apply_llm_output(outputs)
        except Exception as e:
            logger.warning(
                f"Task {task.id}: epistemic persistence failed ({e}) — "
                f"task still accepted"
            )
            return []

        requires_epistemic = (
            getattr(task, "metadata", None) or {}
        ).get("requires_epistemic_output", False)

        if requires_epistemic and not mutations:
            raise EpistemicNoOpError(
                f"Task {task.id} requires epistemic output but produced "
                f"no belief/hypothesis mutations."
            )

        if mutations:
            types = ", ".join(sorted({m.mutation_type for m in mutations}))
            logger.info(
                f"Task {task.id}: {len(mutations)} epistemic mutations [{types}]"
            )

        return mutations

    def _get_task_completion_spec(self, task: Task) -> TaskCompletionSpec:
        """
        Get or generate TaskCompletionSpec for a task.
        
        If the task has explicit acceptance_criteria, use those.
        Otherwise, generate defaults based on task type.
        """
        # Check if task has explicit criteria
        if task.acceptance_criteria:
            from .completion_protocol import AcceptanceCriterion, ValidationStrategy
            
            criteria = [
                AcceptanceCriterion(
                    description=c.get("description", ""),
                    criterion_type=c.get("type", "custom"),
                    target=c.get("target"),
                    threshold=c.get("threshold"),
                    operator=c.get("operator", ">=")
                )
                for c in task.acceptance_criteria
            ]
            
            return TaskCompletionSpec(
                acceptance_criteria=criteria,
                required_artifacts=task.required_artifacts or [],
                validation_strategy=ValidationStrategy(task.validation_strategy) if task.validation_strategy != "auto" else ValidationStrategy.AUTO,
                max_time_seconds=task.max_time_seconds,
                max_tokens=task.max_tokens,
                max_iterations=task.max_iterations,
                dependency_task_ids=task.dependencies or [],
                parent_task_id=task.parent_task_id,
                child_task_ids=task.child_task_ids or [],
            )
        
        # Generate defaults based on task type
        return generate_task_spec(
            task_type=task.type.value,
            task_description=task.description,
            custom_criteria=task.success_criteria.get("requirements") if task.success_criteria else None,
            required_artifacts=task.required_artifacts or None,
            max_time_seconds=task.max_time_seconds
        )

    def _format_verification_feedback(self, result: VerificationResult) -> str:
        """
        Format verification failure as feedback for the LLM.
        
        This tells the LLM exactly what needs to be fixed before
        it can propose completion again.
        
        For REVISION_REQUESTED, use result.get_revision_prompt() instead
        as it provides structured guidance with required score deltas.
        """
        # If revision feedback is available, use the structured prompt
        if result.revision_feedback:
            return result.get_revision_prompt()
        
        feedback_parts = [
            "⚠️ COMPLETION VERIFICATION FAILED",
            "",
            f"Your completion proposal was rejected. State: {result.state.value}",
            f"Score: {result.score.total_score:.2f} (need ≥ 0.85)",
            f"Criteria Pass Rate: {result.criteria_pass_ratio:.1%}",
            "",
        ]
        
        # Hard gate failures are BLOCKERS - must be addressed first
        if result.hard_gate_failures:
            feedback_parts.append("🚫 HARD GATE FAILURES (MUST FIX - these are blocking):")
            for i, gate in enumerate(result.hard_gate_failures, 1):
                feedback_parts.append(f"  {i}. {gate}")
            feedback_parts.append("")
            feedback_parts.append("These criteria MUST pass regardless of overall score.")
            feedback_parts.append("")
        
        feedback_parts.append("ISSUES FOUND:")
        for i, issue in enumerate(result.issues[:5], 1):
            feedback_parts.append(f"  {i}. {issue}")
        
        if len(result.issues) > 5:
            feedback_parts.append(f"  ... and {len(result.issues) - 5} more issues")
        
        feedback_parts.append("")
        feedback_parts.append("SCORE BREAKDOWN:")
        feedback_parts.append(f"  - Artifact Score: {result.score.artifact_score:.2f}")
        feedback_parts.append(f"  - Validation Score: {result.score.validation_score:.2f}")
        feedback_parts.append(f"  - Consistency Score: {result.score.consistency_score:.2f}")
        feedback_parts.append(f"  - Goal Alignment: {result.score.goal_alignment_score:.2f}")
        feedback_parts.append(f"  - Resource Adherence: {result.score.resource_adherence_score:.2f}")
        
        if result.recommendations:
            feedback_parts.append("")
            feedback_parts.append("RECOMMENDATIONS:")
            for rec in result.recommendations[:3]:
                feedback_parts.append(f"  → {rec}")
        
        feedback_parts.append("")
        feedback_parts.append("Continue working on the task and address these issues before proposing completion again.")
        feedback_parts.append("Remember: remaining_risks and open_questions must be empty to complete.")
        
        return "\n".join(feedback_parts)

    async def _verify_task_outputs(self, task: Task, outputs: Dict) -> bool:
        """Verify that task actually created expected outputs"""
        import os

        # Check if files were created
        files_created = outputs.get('files_created', [])
        if files_created:
            for file_path in files_created:
                if not os.path.exists(file_path):
                    logger.warning(f"Task claims to have created {file_path} but file doesn't exist")
                    return False
            logger.info(f"Verified {len(files_created)} output files exist")
            return True

        # If no specific outputs claimed, accept as complete
        return True

    def _parse_llm_response(self, response: Dict[str, Any], task: Task) -> Dict[str, Any]:
        """
        Parse LLM response into structured result

        Args:
            response: Raw LLM response
            task: Original task

        Returns:
            Structured result dict
        """
        try:
            # Extract text from response (LLM returns 'content' not 'text')
            text = response.get('content', response.get('text', '')).strip()

            if not text:
                logger.error(f"Empty response from LLM for task {task.id}. Response keys: {response.keys()}")
                return {
                    'success': False,
                    'error': 'Empty response from LLM',
                    'task_id': task.id,
                    'response_keys': list(response.keys())
                }

            # Try to parse as JSON
            try:
                # Extract JSON from markdown if present
                if '```json' in text:
                    text = text.split('```json')[1].split('```')[0].strip()
                elif '```' in text:
                    text = text.split('```')[1].split('```')[0].strip()

                # Parse JSON
                parsed_data = json.loads(text)

                # Add success flag
                parsed_data['success'] = True
                parsed_data['task_id'] = task.id
                parsed_data['task_type'] = task.type.name

                # A CONFIDENCE NOBODY STATED IS NOT A CONFIDENCE. Absent, this
                # filled in 0.7 and the unformatted branch below filled in 0.5,
                # so every consumer read a number the model never produced and
                # could not tell it from one it did. None says "unstated", which
                # is the true answer and is checkable.
                if 'confidence' not in parsed_data:
                    parsed_data['confidence'] = None
                    parsed_data['confidence_source'] = 'unstated'
                else:
                    # Clamp to [0.0, 1.0]
                    parsed_data['confidence'] = max(0.0, min(1.0, float(parsed_data['confidence'])))
                    parsed_data['confidence_source'] = 'model'

                return parsed_data

            except json.JSONDecodeError:
                # LLM didn't return valid JSON, wrap response as text
                logger.warning(f"LLM response not JSON for task {task.id}, wrapping as text")
                return {
                    'success': True,
                    'task_id': task.id,
                    'task_type': task.type.name,
                    'result': text,
                    'confidence': None,
                    'confidence_source': 'unstated',
                    'note': 'Response was not JSON formatted'
                }

        except Exception as e:
            logger.error(f"Error parsing LLM response for task {task.id}: {e}")
            return {
                'success': False,
                'error': f'Failed to parse LLM response: {e}',
                'task_id': task.id,
                'raw_response': str(response)
            }

    async def get_status(self) -> Dict[str, Any]:
        """Get executor status including drift metrics"""
        drift_metrics = None
        if self.completion_validator:
            drift_metrics = self.completion_validator.get_drift_metrics()
        
        return {
            'active': self.active,
            'llm_connected': self.llm is not None and self.llm.is_initialized if self.llm else False,
            'stats': self.stats.copy(),
            'completion_drift': drift_metrics
        }
    
    def get_drift_status(self) -> Dict[str, Any]:
        """
        Get current completion drift status for monitoring.
        
        Returns:
            Dict with:
            - sufficient_data: bool - Whether enough samples for analysis
            - failure_rate: float - Rolling failure rate (0-1)
            - avg_score: float - Average completion score
            - score_trend: float - Score change trend (negative = declining)
            - is_degrading: bool - Whether system is degrading
            - recommendation: str - Action to take if degrading
        """
        if not self.completion_validator:
            return {"error": "Completion validator not initialized"}
        
        return self.completion_validator.get_drift_metrics()

    async def shutdown(self) -> None:
        """Shutdown executor"""
        self.active = False
        logger.info("General purpose executor shutdown")
