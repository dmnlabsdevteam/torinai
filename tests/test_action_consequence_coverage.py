"""Every registered tool's consequence is known, or knowingly unknown.

The intent layer decides whether an invocation is INVESTIGATE or DELETE, and
`ActionContract` gates on that answer. It had no test file at all, which is how
seven registered mutating tools -- `delete_package`, `purge_cdn_cache`,
`remove_from_data_brokers` among them -- sat unmapped and fell through to the
unknown-tool default. The default is calibrated for tools nothing is known
about; it is the wrong answer for a tool that deletes.

The point of these tests is not to force all 372 tools to be classified. It is
that an unclassified tool must be VISIBLE. `UNMAPPED_TOOLS` below is the ledger:
adding a tool without a consequence fails the suite until it is either declared
or written down here as knowingly deferred.
"""
import pytest

from core.safety.action_consequence import _TOOL_CONSEQUENCE, classify_action
from core.safety.action_contract import ActionClass
from core.tools import get_tool_registry

#: Tools whose consequence depends on their ARGUMENTS, not their identity.
#: `run_shell_command` is INVESTIGATE for `grep` and DELETE for `rm`. A static
#: class would be wrong for half their invocations, so they are read from the
#: payload and must NOT be declared.
PAYLOAD_SENSITIVE = {
    "run_shell_command", "run_python", "execute_command", "mysql_query",
    "graphql_query", "elastic_search", "execute_sandbox", "execute_with_timeout",
}

#: Knowingly deferred. Empty is the goal; entries are a debt, not a permission.
#:
#: These 74 tools have descriptions that name no action verb at all --
#: "Manage X", "X integration" -- so nothing in the description says whether
#: they read or write. Guessing from the name is what misclassified
#: `installed_software` and `identifyskillgaps` as mutations when they only
#: answer questions, so they are listed rather than assumed. Each one falls
#: through to the calibrated unknown-tool default: refused by an
#: investigate-only contract, permitted by one allowing state change.
UNMAPPED_TOOLS: set = {
    "add_docstring",
    "add_internal_threat",
    "add_logging",
    "add_type_hints",
    "aggregate_data",
    "aggressive_broker_attack",
    "alienvaultotx_lookup_indicator",
    "analyze_code",
    "analyze_code_quality",
    "analyze_complexity",
    "analyze_dependencies",
    "analyze_research_data",
    "analyze_training_data",
    "analyzecausalfeedback",
    "api_call",
    "apply_rate_limit",
    "ask_for_clarification",
    "auto_respond_threat",
    "block_country",
    "block_ip_address",
    "build_dependency_graph",
    "compile_typecheck_gate",
    "conduct_research",
    "connection_pool_manager",
    "convert_format",
    "convert_to_async",
    "crowdstrike_contain_host",
    "dataset_profiling",
    "decrypt_file",
    "delegate_task",
    "dns_lookup",
    "docs_build_preview",
    "download_file",
    "encrypt_file",
    "export_bibliography_csl",
    "filter_data",
    "fix_linting_errors",
    "format_code",
    "hash_data",
    "http_request",
    "hunt_threats",
    "implement_algorithm",
    "inline_variable",
    "lint_python",
    "merge_datasets",
    "misp_add_attribute",
    "misp_enrich_indicators",
    "nuke_social_media_account",
    "optimize_code",
    "parse_json",
    "parse_jsonl",
    "parse_yaml",
    "prove_theorem",
    "r2_download",
    "r2_upload",
    "refactor_code",
    "reload_config",
    "repository_refactor",
    "rollback_chaos_experiment",
    "rotate_credentials",
    "row_level_access_control",
    "sanitize_input",
    "scaffold_application",
    "schema_inference",
    "shodan_dns_lookup",
    "simulate_pde_1d",
    "simulate_state_space",
    "snyk_test_package",
    "solve_constraints",
    "solve_linear_optimization",
    "sort_data",
    "synthesize_from_examples",
    "unblock_ip_address",
    "visualizelearningprogress",
}

MUTATING_HINTS = ("write", "edit", "delete", "remove", "move", "drop", "truncate",
                  "kill", "stop", "restart", "install", "deploy", "migrate",
                  "purge", "clean", "archive", "rename")


def _registered():
    r = get_tool_registry()
    return set(r.tools) | set(r.tool_factories)


def _classified(name):
    """True when this tool's class comes from evidence rather than the default."""
    if name in _TOOL_CONSEQUENCE or name in PAYLOAD_SENSITIVE:
        return True
    r = get_tool_registry()
    tool = r.tools.get(name)
    if tool is None:
        factory = r.tool_factories.get(name)
        try:
            tool = factory() if callable(factory) else None
        except Exception:
            return False
    return bool(getattr(tool, "consequence", None))


def test_every_mutating_tool_has_a_known_consequence():
    """A tool that can destroy something must not be classified by default.

    The default (EXECUTE/PARTIALLY_REVERSIBLE) is permitted by any contract
    allowing state change -- so an unmapped `delete_package` would pass a
    contract that only authorised MODIFY.
    """
    mutating = {n for n in _registered()
                if any(h in n for h in MUTATING_HINTS)}
    unknown = sorted(n for n in mutating
                     if not _classified(n) and n not in UNMAPPED_TOOLS)
    assert not unknown, (
        f"{len(unknown)} mutating tool(s) fall through to the unknown-tool "
        f"default; declare `consequence` on the tool or add to UNMAPPED_TOOLS:\n  "
        + "\n  ".join(unknown)
    )


def test_the_deferred_ledger_only_lists_real_tools():
    """A stale entry silences a tool that no longer exists, and would silence a
    new one that later took the same name."""
    stale = sorted(UNMAPPED_TOOLS - _registered())
    assert not stale, f"UNMAPPED_TOOLS lists tools that are not registered: {stale}"


def test_payload_sensitive_tools_are_not_statically_declared():
    """Declaring one of these would freeze it at one class and make the payload
    rules unreachable -- `rm -rf /` would classify as whatever the tool said."""
    frozen = sorted(n for n in PAYLOAD_SENSITIVE if n in _TOOL_CONSEQUENCE
                    and n not in ("run_shell_command", "run_python"))
    assert not frozen, f"payload-sensitive tools given a static class: {frozen}"


def test_the_payload_still_outranks_a_declaration():
    """The ordering that makes the above safe."""
    assert classify_action("run_shell_command", {"command": "grep -rn x ."})[0] is ActionClass.INVESTIGATE
    assert classify_action("run_shell_command", {"command": "rm -rf /"})[0] is ActionClass.DELETE


def test_an_unknown_tool_is_not_assumed_harmless():
    """Unknown must be strong enough that an investigate-only contract refuses
    it, or the default becomes a way to smuggle state changes past a contract."""
    action_class, irreversibility = classify_action("no_such_tool_xyz", {})
    assert action_class is not ActionClass.INVESTIGATE
    assert irreversibility != "FULLY_REVERSIBLE"


@pytest.mark.parametrize("name,expected", [
    ("remove_from_data_brokers", ActionClass.DELETE),
    ("delete_package", ActionClass.DELETE),
    ("purge_cdn_cache", ActionClass.DELETE),
    ("installed_software", ActionClass.INVESTIGATE),
    ("identifyskillgaps", ActionClass.INVESTIGATE),
])
def test_the_previously_unmapped_tools_stay_mapped(name, expected):
    """Regression for the seven. Two of them only LOOK mutating: their own
    descriptions say they answer a question."""
    assert classify_action(name, {})[0] is expected
