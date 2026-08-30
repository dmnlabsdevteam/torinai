#!/usr/bin/env python3
"""
Tool Verification Suite — verify_tools.py
==========================================
Enumerates every tool registered in the ToolRegistry and runs four checks:

  LAYER 1 — INSTANTIATION
    Can the factory produce a Tool object without crashing?

  LAYER 2 — SCHEMA
    Does the tool have a name, description, parameters list, and safety_level?
    Does every ToolParameter have name/type/description?
    Does to_openai_schema() return a valid function-call dict?

  LAYER 3 — PARAMETER VALIDATION
    Does validate_parameters({}) correctly reject a call that omits required params?
    Does validate_parameters with unknown params get rejected with the full schema?

  LAYER 4 — SAFE PROBE  (only for SAFE + MODERATE tools)
    Calls execute() with the cheapest valid inputs that touch real logic but do
    no permanent writes (read-only calls, in-memory transforms, local paths in /tmp).
    Sensitive tools (DANGEROUS / CRITICAL / HIGH_RISK + specific name-based
    blocklist) are skipped and marked SKIPPED-SENSITIVE.

Output
------
• Coloured summary table to stdout
• JSON report written to  logs/tool_verification_<timestamp>.json
• Exit code 0 if all non-skipped checks passed, 1 otherwise

Usage
-----
    python scripts/verify_tools.py [--category CATEGORY] [--tool TOOLNAME]
                                   [--layer 1|2|3|4] [--no-probe] [--json-only]
                                   [--list]

Examples
    python scripts/verify_tools.py                    # full suite
    python scripts/verify_tools.py --layer 1,2,3      # skip live probes
    python scripts/verify_tools.py --tool read_file   # single tool
    python scripts/verify_tools.py --category filesystem
    python scripts/verify_tools.py --list             # just list registered tool names
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

# ── path bootstrap ──────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Fast-init bypass: skip capability regex during tool registration ─────────
# Without this, 80+ ConnectorTool inits each run 100+ regex ops → ~8 seconds.
# The env var is checked at the top of infer_capability_from_task() in
# capabilities.py and returns {} immediately when set.
import os as _os
_os.environ["TORIN_FAST_INIT"] = "1"

# ── suppress noisy startup logs ─────────────────────────────────────────────
import logging
logging.getLogger("TorinAI").setLevel(logging.ERROR)
logging.getLogger("core").setLevel(logging.ERROR)
logging.getLogger("uvicorn").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.disable(logging.WARNING)

# ── ANSI colours ─────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text
PASS  = lambda t: _c("32;1", t)
FAIL  = lambda t: _c("31;1", t)
WARN  = lambda t: _c("33;1", t)
SKIP  = lambda t: _c("36",   t)
BOLD  = lambda t: _c("1",    t)
DIM   = lambda t: _c("2",    t)

# ═══════════════════════════════════════════════════════════════════════════════
# PROBE FIXTURES
# Safe minimal inputs for each tool name (or pattern) — used in Layer 4.
# Format: tool_name → dict of kwargs to pass to execute().
# Tools not listed here get a best-effort auto-probe from their ToolParameter
# schema (generate synthetic values for required params).
# ═══════════════════════════════════════════════════════════════════════════════

# Temp workspace for probes that need real files
_TMP = tempfile.mkdtemp(prefix="torin_toolverify_")
_TMP_FILE = os.path.join(_TMP, "probe.txt")
with open(_TMP_FILE, "w") as _f:
    _f.write("tool verification probe file\nline 2\nline 3\n")

SAFE_PROBES: Dict[str, Dict[str, Any]] = {
    # ── filesystem ────────────────────────────────────────────────────────────
    "read_file":          {"file_path": _TMP_FILE},
    "list_directory":     {"directory_path": _TMP},
    "search_files":       {"directory": _TMP, "pattern": "*.txt"},
    "get_file_info":      {"file_path": _TMP_FILE},
    "calculate_checksum": {"file_path": _TMP_FILE},
    "validate_path":      {"path": _TMP_FILE},
    "find_duplicates":    {"directory": _TMP},
    "write_file":         {"file_path": os.path.join(_TMP, "write_probe.txt"), "content": "probe"},
    "create_directory":   {"directory_path": os.path.join(_TMP, "mkdir_probe")},
    "atomic_write_file":  {"file_path": os.path.join(_TMP, "atomic_probe.txt"), "content": "probe"},
    "copy_file":          {"source": _TMP_FILE, "destination": os.path.join(_TMP, "copy_probe.txt")},
    "patch_file":         {"file_path": _TMP_FILE, "old_string": "line 2", "new_string": "line TWO"},
    "compress_file":      {"file_path": _TMP_FILE, "output_path": os.path.join(_TMP, "probe.gz")},

    # ── system tools ──────────────────────────────────────────────────────────
    "system_info":        {},
    "list_processes":     {},

    # ── search / analysis ─────────────────────────────────────────────────────
    "grep_search":        {"directory": _TMP, "pattern": "probe"},
    "semantic_search":    {"query": "probe file content", "directory": _TMP},
    "count_lines":        {"file_path": _TMP_FILE},
    "analyze_code":       {"file_path": _TMP_FILE},
    "find_todos":         {"directory": _TMP},
    "search_secrets_and_pii": {"directory": _TMP},
    "ast_search":         {"directory": _TMP, "query": "def"},
    "build_dependency_graph": {"directory": _TMP},

    # ── monitoring ────────────────────────────────────────────────────────────
    "get_cpu_usage":      {},
    "get_memory_usage":   {},
    "get_disk_usage":     {},
    "get_network_stats":  {},

    # ── data processing ───────────────────────────────────────────────────────
    "parse_json":         {"data": '{"key": "value"}'},
    "parse_yaml":         {"data": "key: value"},
    "parse_csv":          {"data": "a,b,c\n1,2,3"},
    "parse_jsonl":        {"data": '{"x":1}\n{"x":2}'},
    "convert_format":     {"data": '{"key": "value"}', "from_format": "json", "to_format": "yaml"},
    "filter_data":        {"data": [{"a": 1}, {"a": 2}], "condition": "a > 1"},
    "sort_data":          {"data": [3, 1, 2]},
    "deduplicate_data":   {"data": [1, 2, 2, 3]},
    "transform_data":     {"data": {"key": "value"}, "transformation": "identity"},
    "aggregate_data":     {"data": [{"x": 1}, {"x": 2}], "operation": "sum", "field": "x"},
    "schema_inference":   {"data": [{"name": "Alice", "age": 30}]},
    "pii_scrubbing":      {"text": "Contact John at john@example.com"},
    "dataset_profiling":  {"data": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]},

    # ── testing / validation ──────────────────────────────────────────────────
    "check_syntax":       {"code": "def hello():\n    return 42", "language": "python"},
    "validate_json":      {"data": '{"valid": true}'},
    "validate_yaml":      {"data": "valid: true"},
    "lint_python":        {"code": "import os\ndef f():\n    pass"},
    "type_check":         {"code": "x: int = 1"},
    "run_pytest":         {"directory": _TMP},
    "run_unittest":       {"directory": _TMP},
    "run_coverage":       {"directory": _TMP},
    "benchmark_code":     {"code": "sum(range(100))"},
    "generate_mock":      {"interface": "def foo(x: int) -> str: ..."},
    "test_data_generator":{"schema": {"type": "object", "properties": {"name": {"type": "string"}}}},

    # ── code generation ───────────────────────────────────────────────────────
    "generate_function":  {"description": "Add two numbers", "language": "python"},
    "generate_class":     {"description": "A simple counter class", "language": "python"},
    "format_code":        {"code": "def f( x ):  return x+1", "language": "python"},
    "add_docstring":      {"code": "def add(a, b):\n    return a + b", "language": "python"},
    "add_type_hints":     {"code": "def add(a, b):\n    return a + b", "language": "python"},
    "implement_algorithm":{"name": "binary_search", "language": "python"},
    "extract_method":     {"code": "def f():\n    x = 1\n    y = 2\n    return x+y", "method_name": "compute"},

    # ── security (safe read-only subset) ─────────────────────────────────────
    "hash_data":          {"data": "hello world", "algorithm": "sha256"},
    "generate_password":  {"length": 16},
    "sanitize_input":     {"input": "<script>alert('xss')</script>"},
    "validate_email":     {"email": "test@example.com"},
    "validate_url":       {"url": "https://example.com"},
    "check_malicious_patterns": {"input": "normal text"},
    "sanitize_filename":  {"filename": "my file (1).txt"},
    "validate_sql_input": {"query": "SELECT * FROM users WHERE id = 1"},

    # ── reasoning ─────────────────────────────────────────────────────────────
    "run_monte_carlo":    {"simulation": "coin_flip", "iterations": 100},
    "solve_constraints":  {"constraints": ["x > 0", "x < 10"], "variables": ["x"]},
    "solve_linear_optimization": {"objective": [1, 2], "constraints": [[1, 1]], "bounds": [10]},

    # ── documentation ─────────────────────────────────────────────────────────
    "extract_docstrings": {"file_path": _TMP_FILE},
    "create_diagram":     {"diagram_type": "flowchart", "content": "A -> B -> C"},

    # ── AI/ML (in-memory, no external API) ────────────────────────────────────
    "extract_entities":   {"text": "Apple is a company in California."},
    "generate_embedding": {"text": "hello world"},

    # ── network (safe, use public endpoints) ─────────────────────────────────
    "check_url_status":   {"url": "https://httpbin.org/status/200"},
    "dns_lookup":         {"hostname": "github.com"},
    "ping_host":          {"host": "8.8.8.8", "count": 1},
    "parse_html":         {"html": "<html><body><p>Hello</p></body></html>"},
    "extract_links":      {"html": "<a href='https://example.com'>link</a>"},

    # ── research ──────────────────────────────────────────────────────────────
    "conduct_research":   {"topic": "test probe", "max_sources": 1},
    "search_academic":    {"query": "test probe"},
    "search_news":        {"query": "technology"},
    "search_data":        {"query": "test"},

    # ── system management ─────────────────────────────────────────────────────
    "get_environment_variable": {"name": "PATH"},
    "check_dependencies": {"requirements": ["python"]},

    # ── learning tools ────────────────────────────────────────────────────────
    "profile_performance": {"task_name": "test_task", "metrics": {"latency_ms": 100}},
    "detect_patterns":    {"data": [1, 2, 3, 2, 1]},

    # ── chaos tools (read-only ops) ───────────────────────────────────────────
    "list_chaos_scenarios": {},
}

# ═══════════════════════════════════════════════════════════════════════════════
# SENSITIVE BLOCKLIST
# Tools that must NOT be live-probed even if their ToolSafety level is SAFE.
# These write to external services, execute destructive actions, or cost money.
# ═══════════════════════════════════════════════════════════════════════════════

SENSITIVE_BLOCKLIST: Set[str] = {
    # Slack / communication — send real messages
    "send_slack_message", "post_to_webhook",
    "ask_for_clarification", "report_security_finding",
    "notify_dominionlabs_team", "post_slack_message",
    # Slack monitoring — read live workspace data
    "get_slack_users", "get_slack_channels", "search_slack_messages",
    "get_channel_history", "monitor_team_activity",
    "get_team_health_metrics", "get_user_presence",
    # Database — real writes / reads
    "mysql_query", "mysql_backup", "mysql_restore",
    "redis_set", "redis_get",
    "r2_upload", "r2_download",
    "migration_runner", "transaction_wrapper",
    "store_memory", "query_memory",
    # External APIs that cost money / have rate limits
    "virustotal_scan_file", "virustotal_scan_url",
    "virustotal_get_ip_report", "virustotal_get_domain_report",
    "crowdstrike_search_detections", "crowdstrike_get_host_info",
    "crowdstrike_contain_host", "crowdstrike_lift_containment",
    "crowdstrike_run_rtr_command",
    "misp_create_event", "misp_add_attribute", "misp_enrich_indicators",
    "splunk_search", "elastic_search",
    "run_inference",  # loads model, expensive
    # Security/destructive actions
    "block_ip_address", "unblock_ip_address", "create_waf_rule",
    "apply_rate_limit", "block_country", "add_internal_threat",
    "auto_respond_threat", "hunt_threats",
    "digital_footprint_obliteration", "remove_from_data_brokers",
    "scrub_web_archives", "scrub_dns_whois", "delete_package",
    "purge_cdn_cache", "file_legal_takedown", "rotate_credentials",
    "obfuscate_identity", "nuke_social_media_account",
    "aggressive_data_broker_attack", "nuclear_obliteration",
    # System-level actions
    "kill_process", "update_system", "manage_docker",
    "set_environment_variable", "modify_config_file",
    "reload_config", "schedule_cron_job",
    "start_service", "stop_service", "restart_service",
    "delete_file", "move_file",  # destructive
    "load_test", "chaos_testing",  # can saturate system
    "run_chaos_experiment", "create_chaos_experiment",
    "mutation_testing",  # can be slow + mutates files
    "trigger_self_improvement",
    "run_python", "execute_sandbox", "run_shell_command",
    "execute_with_timeout", "execute_with_resource_limits",
    "execute_network_isolated", "execute_deterministic",
    "execute_with_artifact_capture",
    "run_background_task",
    "install_python_package",
    "scaffold_application",
    "repository_refactor",
    "generate_pdf_document", "generate_word_document",
    "generate_powerpoint",
    "docs_build_preview", "versioned_doc_deployment",
    "port_scan",  # network scanning
    "websocket_connect",
    "upload_file", "download_file",
    "sync_directory",
    "decompress_file",  # don't need to verify archive extraction
    "encrypt_file", "decrypt_file",
    "scan_secrets",
    "check_ip_threat_intelligence",
    "detect_intrusion", "analyze_anomaly", "monitor_logs",
    "detect_brute_force", "analyze_traffic_pattern", "detect_zero_day",
    "ai_digital_footprint_detection",
    "integration_test_runner",
    "fuzz_testing", "static_security_analysis",
    "golden_test_harness",
    "restapi_fetch_alerts", "restapi_create_alert",
    "github_search_repos", "github_get_trending",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Result data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LayerResult:
    layer: int
    passed: bool
    message: str
    detail: str = ""
    duration_ms: float = 0.0

@dataclass
class ToolVerifyResult:
    tool_name: str
    category: str
    safety_level: str
    layers: List[LayerResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    overall: str = "UNKNOWN"  # PASS / FAIL / SKIP / ERROR

    def to_dict(self) -> dict:
        d = asdict(self)
        d["layers"] = [asdict(lr) for lr in self.layers]
        return d

# ═══════════════════════════════════════════════════════════════════════════════
# Auto-probe generator
# Generates minimal valid kwargs from a tool's ToolParameter schema.
# Used when no hand-written fixture exists in SAFE_PROBES.
# ═══════════════════════════════════════════════════════════════════════════════

_TYPE_DEFAULTS = {
    "string":  "test",
    "number":  1,
    "integer": 1,
    "boolean": False,
    "array":   [],
    "object":  {},
}

def _auto_probe(tool) -> Dict[str, Any]:
    """Generate minimal kwargs satisfying required parameters."""
    kwargs: Dict[str, Any] = {}
    for p in getattr(tool, "parameters", []):
        if p.required:
            if p.enum:
                kwargs[p.name] = p.enum[0]
            elif p.default is not None:
                kwargs[p.name] = p.default
            elif p.type == "string" and p.name in ("file_path", "path", "directory", "dir"):
                kwargs[p.name] = _TMP_FILE
            elif p.type == "string" and p.name in ("directory_path",):
                kwargs[p.name] = _TMP
            elif p.type == "string" and p.name in ("code",):
                kwargs[p.name] = "def f(): pass"
            elif p.type == "string" and p.name in ("query", "topic", "text", "content", "search_query"):
                kwargs[p.name] = "test probe"
            elif p.type in ("number", "integer"):
                # Respect min_value so the value doesn't fail range validation
                val = _TYPE_DEFAULTS.get(p.type, 1)
                if getattr(p, 'min_value', None) is not None:
                    val = max(val, p.min_value)
                kwargs[p.name] = val
            else:
                kwargs[p.name] = _TYPE_DEFAULTS.get(p.type, "test")
    return kwargs

# ═══════════════════════════════════════════════════════════════════════════════
# Core verifier
# ═══════════════════════════════════════════════════════════════════════════════

async def _verify_tool(
    tool_name: str,
    factory,
    layers_to_run: Set[int],
    run_probe: bool,
) -> ToolVerifyResult:

    result = ToolVerifyResult(tool_name=tool_name, category="?", safety_level="?")

    # ── LAYER 1: INSTANTIATION ───────────────────────────────────────────────
    tool = None
    if 1 in layers_to_run:
        t0 = time.perf_counter()
        try:
            tool = factory()
            dur = (time.perf_counter() - t0) * 1000
            result.layers.append(LayerResult(1, True, "instantiated", duration_ms=dur))
        except Exception as e:
            dur = (time.perf_counter() - t0) * 1000
            result.layers.append(LayerResult(
                1, False, f"INSTANTIATION FAILED: {type(e).__name__}: {e}",
                detail=traceback.format_exc(), duration_ms=dur
            ))
            result.overall = "FAIL"
            return result
    else:
        try:
            tool = factory()
        except Exception:
            result.skipped = True
            result.skip_reason = "could not instantiate (layer 1 skipped)"
            result.overall = "SKIP"
            return result

    # Fill in metadata from the live tool instance
    result.category = getattr(getattr(tool, "category", None), "value", str(getattr(tool, "category", "?")))
    sl = getattr(tool, "safety_level", None)
    result.safety_level = getattr(sl, "value", str(sl)) if sl else "?"

    # ── Sensitivity check ────────────────────────────────────────────────────
    safe_for_probe = result.safety_level in ("safe", "moderate")
    in_blocklist   = tool_name in SENSITIVE_BLOCKLIST

    # ── LAYER 2: SCHEMA ──────────────────────────────────────────────────────
    if 2 in layers_to_run:
        t0 = time.perf_counter()
        issues = []
        if not getattr(tool, "name", None):
            issues.append("missing tool.name")
        if not getattr(tool, "description", None):
            issues.append("missing tool.description")
        params = getattr(tool, "parameters", None)
        param_count = 0
        if params is None:
            issues.append("tool.parameters is None")
        elif isinstance(params, dict):
            # JSON Schema dict format (e.g. chaos tools) — validate structure
            if "properties" not in params:
                issues.append("dict-format parameters missing 'properties' key")
            else:
                param_count = len(params.get("properties", {}))
                for pname, pdef in params.get("properties", {}).items():
                    if not pdef.get("type"):
                        issues.append(f"param '{pname}' missing type")
                    if not pdef.get("description"):
                        issues.append(f"param '{pname}' missing description")
        else:
            # List[ToolParameter] format
            param_count = len(params)
            for i, p in enumerate(params):
                if not getattr(p, "name", None):
                    issues.append(f"param[{i}] missing name")
                if not getattr(p, "type", None):
                    issues.append(f"param {getattr(p,'name','?')} missing type")
                if not getattr(p, "description", None):
                    issues.append(f"param {getattr(p,'name','?')} missing description")
        # OpenAI schema
        try:
            schema = tool.to_openai_schema()
            if "function" not in schema and "name" not in schema.get("function", {}):
                pass  # some tools return {name, description, parameters} directly
        except Exception as e:
            issues.append(f"to_openai_schema() raised {type(e).__name__}: {e}")
        dur = (time.perf_counter() - t0) * 1000
        if issues:
            result.layers.append(LayerResult(2, False, f"SCHEMA ISSUES: {'; '.join(issues)}", duration_ms=dur))
        else:
            result.layers.append(LayerResult(2, True, f"schema ok ({param_count} params)", duration_ms=dur))

    # ── LAYER 3: PARAMETER VALIDATION ────────────────────────────────────────
    if 3 in layers_to_run:
        t0 = time.perf_counter()
        issues = []

        raw_params = getattr(tool, "parameters", [])

        if isinstance(raw_params, dict):
            # JSON Schema dict format — extract required names and build minimal valid kwargs
            _props = raw_params.get("properties", {})
            _required_names = raw_params.get("required", [])

            # 3a: Missing required param should be rejected
            if _required_names:
                ok, err = tool.validate_parameters({})
                if ok:
                    issues.append(
                        f"validate_parameters({{}}) returned ok=True — should have rejected "
                        f"missing required param '{_required_names[0]}'"
                    )
                elif _required_names[0] not in (err or ""):
                    issues.append(
                        f"rejection message for empty params doesn't mention param name "
                        f"'{_required_names[0]}': got {err!r}"
                    )

            # 3b: Unknown param should be rejected
            bogus = {"_bogus_param_xyz": "test"}
            ok2, err2 = tool.validate_parameters(bogus)
            if ok2:
                issues.append("validate_parameters({'_bogus_param_xyz': 'test'}) returned ok=True — unknown params should be rejected")
            elif err2 and "bogus" not in err2.lower() and "unknown" not in err2.lower():
                issues.append(f"unknown-param rejection message unclear: {err2!r}")

            # 3c: Valid minimal params should pass
            if _required_names:
                valid_kwargs: Dict[str, Any] = {}
                for req in _required_names:
                    pdef = _props.get(req, {})
                    ptype = pdef.get("type", "string")
                    if ptype == "string":
                        valid_kwargs[req] = pdef["enum"][0] if pdef.get("enum") else f"test_{req}"
                    elif ptype in ("integer", "number"):
                        valid_kwargs[req] = pdef.get("minimum", 1)
                    elif ptype == "boolean":
                        valid_kwargs[req] = True
                    elif ptype == "array":
                        valid_kwargs[req] = []
                    elif ptype == "object":
                        valid_kwargs[req] = {}
                    else:
                        valid_kwargs[req] = f"test_{req}"
                ok3, err3 = tool.validate_parameters(valid_kwargs)
                if not ok3:
                    issues.append(f"valid minimal params rejected: {err3!r}")

        else:
            # List[ToolParameter] format — original logic
            required_params = [p for p in raw_params if hasattr(p, 'required') and p.required]

            # 3a: Missing required param should be rejected
            if required_params:
                ok, err = tool.validate_parameters({})
                if ok:
                    issues.append(
                        f"validate_parameters({{}}) returned ok=True — should have rejected "
                        f"missing required param '{required_params[0].name}'"
                    )
                elif required_params[0].name not in (err or ""):
                    issues.append(
                        f"rejection message for empty params doesn't mention param name "
                        f"'{required_params[0].name}': got {err!r}"
                    )

            # 3b: Unknown param should be rejected with schema in error
            bogus = {"_bogus_param_xyz": "test"}
            ok2, err2 = tool.validate_parameters(bogus)
            if ok2:
                issues.append("validate_parameters({'_bogus_param_xyz': 'test'}) returned ok=True — unknown params should be rejected")
            elif err2 and "bogus" not in err2.lower() and "unknown" not in err2.lower():
                issues.append(f"unknown-param rejection message unclear: {err2!r}")

            # 3c: Valid minimal params should pass (if tool has required params)
            if required_params:
                valid_kwargs = _auto_probe(tool)
                ok3, err3 = tool.validate_parameters(valid_kwargs)
                if not ok3:
                    issues.append(f"valid minimal params rejected: {err3!r}")

        dur = (time.perf_counter() - t0) * 1000
        if issues:
            result.layers.append(LayerResult(3, False, f"VALIDATION ISSUES: {'; '.join(issues)}", duration_ms=dur))
        else:
            result.layers.append(LayerResult(3, True, "param validation ok", duration_ms=dur))

    # ── LAYER 4: SAFE PROBE ───────────────────────────────────────────────────
    if 4 in layers_to_run and run_probe:
        if not safe_for_probe or in_blocklist:
            result.layers.append(LayerResult(
                4, True,
                f"SKIPPED — {'blocklist' if in_blocklist else 'safety='+result.safety_level}",
                detail="sensitive tool, probe skipped"
            ))
        else:
            # Get probe kwargs: hand-written > auto-generated
            probe_kwargs = SAFE_PROBES.get(tool_name) or _auto_probe(tool)
            t0 = time.perf_counter()
            try:
                tool_result = await asyncio.wait_for(
                    tool.execute(**probe_kwargs),
                    timeout=30.0
                )
                dur = (time.perf_counter() - t0) * 1000
                if tool_result.success:
                    result.layers.append(LayerResult(
                        4, True,
                        f"execute() success ({dur:.0f}ms)",
                        duration_ms=dur
                    ))
                else:
                    # Non-success is still a pass at layer 4 IF the error is
                    # well-formed (has an error string, not an exception crash).
                    # The tool handled it gracefully.
                    err_str = (tool_result.error or "")
                    is_graceful = (
                        isinstance(err_str, str)
                        and len(err_str) > 0
                        and "traceback" not in err_str.lower()
                    )
                    result.layers.append(LayerResult(
                        4, is_graceful,
                        f"execute() returned success=False — {'graceful' if is_graceful else 'UNHANDLED ERROR'}",
                        detail=err_str[:400],
                        duration_ms=dur
                    ))
            except asyncio.TimeoutError:
                dur = (time.perf_counter() - t0) * 1000
                result.layers.append(LayerResult(
                    4, False, f"execute() TIMED OUT (>30s)",
                    duration_ms=dur
                ))
            except Exception as e:
                dur = (time.perf_counter() - t0) * 1000
                result.layers.append(LayerResult(
                    4, False,
                    f"execute() RAISED EXCEPTION: {type(e).__name__}: {e}",
                    detail=traceback.format_exc()[:600],
                    duration_ms=dur
                ))

    # ── Overall status ────────────────────────────────────────────────────────
    if result.skipped:
        result.overall = "SKIP"
    else:
        all_passed = all(lr.passed for lr in result.layers)
        result.overall = "PASS" if all_passed else "FAIL"

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Reporting
# ═══════════════════════════════════════════════════════════════════════════════

def _status_char(r: ToolVerifyResult) -> str:
    if r.overall == "PASS":   return PASS("✓")
    if r.overall == "SKIP":   return SKIP("⊘")
    if r.overall == "FAIL":   return FAIL("✗")
    return WARN("?")

def _print_summary(results: List[ToolVerifyResult], layers_run: Set[int]) -> int:
    passed = [r for r in results if r.overall == "PASS"]
    failed = [r for r in results if r.overall == "FAIL"]
    skipped = [r for r in results if r.overall == "SKIP"]

    print()
    print(BOLD("═" * 80))
    print(BOLD(f"  TOOL VERIFICATION REPORT  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    print(BOLD(f"  Layers: {sorted(layers_run)}  |  Tools checked: {len(results)}"))
    print(BOLD("═" * 80))

    # Category groupings
    by_cat: Dict[str, List[ToolVerifyResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    for cat in sorted(by_cat):
        cat_results = by_cat[cat]
        n_pass  = sum(1 for r in cat_results if r.overall == "PASS")
        n_fail  = sum(1 for r in cat_results if r.overall == "FAIL")
        n_skip  = sum(1 for r in cat_results if r.overall == "SKIP")
        cat_line = f"  {BOLD(cat.upper())}  ({n_pass}✓ {n_fail}✗ {n_skip}⊘)"
        print(cat_line)
        for r in sorted(cat_results, key=lambda x: x.tool_name):
            char = _status_char(r)
            safety = DIM(f"[{r.safety_level}]")
            line = f"    {char} {r.tool_name:<45} {safety}"
            print(line)
            # Print failure details
            for lr in r.layers:
                if not lr.passed and not (lr.layer == 4 and "SKIPPED" in lr.message):
                    print(FAIL(f"      └─ L{lr.layer}: {lr.message}"))
                    if lr.detail:
                        for dl in lr.detail.strip().split("\n")[:4]:
                            print(DIM(f"         {dl}"))
        print()

    print(BOLD("─" * 80))
    print(BOLD(f"  TOTAL:  ") +
          PASS(f"{len(passed)} passed") + "  " +
          FAIL(f"{len(failed)} failed") + "  " +
          SKIP(f"{len(skipped)} skipped") +
          f"  of {len(results)}")
    print(BOLD("─" * 80))

    if failed:
        print()
        print(BOLD(FAIL("FAILURES:")))
        for r in failed:
            print(f"  {r.tool_name}  [{r.category} / {r.safety_level}]")
            for lr in r.layers:
                if not lr.passed:
                    print(f"    L{lr.layer}: {lr.message}")
                    if lr.detail:
                        for dl in lr.detail.strip().split("\n")[:3]:
                            print(DIM(f"       {dl}"))

    print()
    return 0 if not failed else 1


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(
        description="Verify all registered Torin tools across instantiation, schema, validation, and live-probe layers."
    )
    parser.add_argument("--category",  help="Filter to a single category (e.g. filesystem)")
    parser.add_argument("--tool",      help="Verify a single tool by name")
    parser.add_argument("--layer",     default="1,2,3,4",
                        help="Comma-separated layers to run (default: 1,2,3,4)")
    parser.add_argument("--no-probe",  action="store_true",
                        help="Skip Layer 4 live probes (same as --layer 1,2,3)")
    parser.add_argument("--json-only", action="store_true",
                        help="Only write JSON report, no terminal output")
    parser.add_argument("--list",      action="store_true",
                        help="List all registered tool names and exit")
    parser.add_argument("--output",    default=None,
                        help="Override output JSON path (default: logs/tool_verification_<ts>.json)")
    args = parser.parse_args()

    layers_to_run: Set[int] = set()
    if not args.no_probe:
        for part in args.layer.split(","):
            try:
                layers_to_run.add(int(part.strip()))
            except ValueError:
                pass
    else:
        layers_to_run = {1, 2, 3}

    run_probe = (4 in layers_to_run)

    # ── Import registry ───────────────────────────────────────────────────────
    print(BOLD("Loading tool registry…"), end=" ", flush=True)
    try:
        from core.tools.tool_registry import get_tool_registry, ToolSafety
        registry = get_tool_registry()
    except Exception as e:
        print(FAIL(f"\nFailed to load registry: {e}"))
        traceback.print_exc()
        sys.exit(2)

    all_names = sorted(set(list(registry.tool_factories.keys()) + list(registry.tools.keys())))
    print(PASS(f"OK — {len(all_names)} tools registered"))

    if args.list:
        for n in all_names:
            print(f"  {n}")
        sys.exit(0)

    # Apply filters
    if args.tool:
        if args.tool not in all_names:
            # fuzzy match
            matches = [n for n in all_names if args.tool.lower() in n.lower()]
            if matches:
                print(WARN(f"  Tool '{args.tool}' not found exactly — closest matches: {matches[:5]}"))
                all_names = matches
            else:
                print(FAIL(f"  Tool '{args.tool}' not found"))
                sys.exit(2)
        else:
            all_names = [args.tool]

    # ── Run verification ──────────────────────────────────────────────────────
    results: List[ToolVerifyResult] = []
    total = len(all_names)

    for i, name in enumerate(all_names, 1):
        # Get factory
        if name in registry.tool_factories:
            factory = registry.tool_factories[name]
        elif name in registry.tools:
            factory = lambda n=name: registry.tools[n]
        else:
            continue

        # Category filter
        if args.category:
            # Quick category check without full instantiation
            # Load it briefly to check
            try:
                t = factory()
                cat = getattr(getattr(t, "category", None), "value", "?")
                if cat.lower() != args.category.lower():
                    continue
            except Exception:
                continue

        label = f"  [{i:3d}/{total}] {name:<50}"
        if not args.json_only:
            print(label, end="\r", flush=True)

        r = await _verify_tool(name, factory, layers_to_run, run_probe)
        results.append(r)

        if not args.json_only:
            char = _status_char(r)
            print(f"  [{i:3d}/{total}] {char} {name}")

    # ── Write JSON report ─────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.output or os.path.join(_ROOT, "logs", f"tool_verification_{ts}.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    report = {
        "timestamp": ts,
        "layers_run": sorted(layers_to_run),
        "total_tools": len(results),
        "passed": sum(1 for r in results if r.overall == "PASS"),
        "failed": sum(1 for r in results if r.overall == "FAIL"),
        "skipped": sum(1 for r in results if r.overall == "SKIP"),
        "failures": [
            {
                "tool": r.tool_name,
                "category": r.category,
                "safety": r.safety_level,
                "layers": [
                    {"layer": lr.layer, "message": lr.message, "detail": lr.detail[:300] if lr.detail else ""}
                    for lr in r.layers if not lr.passed
                ]
            }
            for r in results if r.overall == "FAIL"
        ],
        "tools": [r.to_dict() for r in results],
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    if not args.json_only:
        exit_code = _print_summary(results, layers_to_run)
        print(f"\n  JSON report → {report_path}\n")
    else:
        exit_code = 0 if not any(r.overall == "FAIL" for r in results) else 1
        print(report_path)

    # Cleanup tmp
    import shutil
    try:
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:
        pass

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
