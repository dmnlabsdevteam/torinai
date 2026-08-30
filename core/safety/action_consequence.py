#!/usr/bin/env python3
"""What class of consequence does this tool invocation actually have?

The safety layer could previously answer "how dangerous is this TOOL" (ToolSafety)
but never "what will THIS invocation do to the world". Those differ: `move_file`
is reversible, `delete_file` is not, and `run_shell_command` is whichever the
command makes it.

Names are the real registered tools (filesystem_tools / execution_tools /
system_tools), not invented ones.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from .action_contract import ActionClass, _IRREVERSIBILITY_ORDER

logger = logging.getLogger(__name__)

# tool_name -> (ActionClass, IrreversibilityClass name)
_TOOL_CONSEQUENCE: Dict[str, Tuple[ActionClass, str]] = {
    # Pure observation
    "read_file": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "list_directory": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "search_files": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_file_info": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "calculate_checksum": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_path": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "find_duplicate_files": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "system_info": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_process_info": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "list_processes": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),

    # Relocation — recoverable removal. This is what Torin correctly chose.
    "move_file": (ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),
    "copy_file": (ActionClass.MODIFY, "FULLY_REVERSIBLE"),
    "compress_file": (ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),
    "sync_directory": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),

    # In-place change — the previous content is gone unless something kept it.
    "write_file": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "atomic_write_file": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "patch_file": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_directory": (ActionClass.MODIFY, "FULLY_REVERSIBLE"),

    # Irreversible
    "delete_file": (ActionClass.DELETE, "IRREVERSIBLE"),

    # Process/service control — side effects on a running system
    "kill_process": (ActionClass.EXECUTE, "MOSTLY_IRREVERSIBLE"),
    "stop_service": (ActionClass.EXECUTE, "MOSTLY_REVERSIBLE"),
    "start_service": (ActionClass.EXECUTE, "MOSTLY_REVERSIBLE"),
    "restart_service": (ActionClass.EXECUTE, "MOSTLY_REVERSIBLE"),
    "install_python_package": (ActionClass.EXECUTE, "MOSTLY_REVERSIBLE"),
    "schedule_cron_job": (ActionClass.EXECUTE, "MOSTLY_REVERSIBLE"),
    "run_background_task": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),

    # Registered mutating tools that were falling through to the unknown-tool
    # default (EXECUTE/PARTIALLY_REVERSIBLE). That default is calibrated for
    # tools we know nothing about; these are known, and three of them delete.
    # Classified from each tool's OWN description, not from its name.
    #
    #   "Delete packages from registries"            -> DELETE
    #   "Purge and delete cached content from CDN"   -> DELETE, but the cache
    #                                                   refills from origin
    #   "Remove info from data brokers"              -> DELETE, and a removal
    #                                                   request to a third party
    #                                                   cannot be recalled
    "delete_package": (ActionClass.DELETE, "MOSTLY_IRREVERSIBLE"),
    "purge_cdn_cache": (ActionClass.DELETE, "MOSTLY_REVERSIBLE"),
    "remove_from_data_brokers": (ActionClass.DELETE, "IRREVERSIBLE"),

    #   "Migrate code from one pattern/version to another" -> in-place rewrite
    #   "Deploy versioned documentation"                   -> versioned, so the
    #                                                         prior version stays
    "migrate_code": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "versioned_doc_deployment": (ActionClass.MODIFY, "MOSTLY_REVERSIBLE"),

    #   "What software ... is installed on this Mac" -> a question
    #   "Identify skill and capability gaps ... Returns gap analysis" -> a report
    # Both read like mutations by name only; neither changes anything.
    "installed_software": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "identifyskillgaps": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),

    # Surfaced by the coverage test the moment it was added.
    #   "Rename a symbol ... with scope awareness using AST" -> an in-place
    #     source rewrite across every reference; recoverable only from VCS.
    #   "Remove and scrub URLs from web archives ... permanently deleting"
    #     -> says permanent, and third-party archives cannot be restored.
    "rename_symbol": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "scrub_web_archives": (ActionClass.DELETE, "IRREVERSIBLE"),

    # ══════════════════════════════════════════════════════════════════════
    # Bulk classification of the remaining registered tools.
    #
    # DERIVED, not hand-audited: each entry comes from that tool's own name and
    # description, resolved strongest-class-first -- a description that mentions
    # deleting is DELETE even if it also mentions listing. The asymmetry is
    # deliberate. Calling a mutating tool INVESTIGATE would let it past an
    # investigate-only contract; calling a read-only tool MODIFY only costs a
    # contract that has to permit state change. When the evidence is mixed, the
    # stronger class wins.
    #
    # An entry here is a claim about a tool made from its description. If a tool
    # changes what it does, this does not notice -- declare `consequence` on the
    # tool class instead, which classify_action consults before falling back.
    # ══════════════════════════════════════════════════════════════════════

    # ── DELETE ─────────────────────────────────────────────────────
    "crowdstrike_lift_containment": (ActionClass.DELETE, "IRREVERSIBLE"),
    "deduplicate_data": (ActionClass.DELETE, "IRREVERSIBLE"),
    "file_legal_takedown": (ActionClass.DELETE, "IRREVERSIBLE"),
    "nuclear_obliteration": (ActionClass.DELETE, "IRREVERSIBLE"),
    "obliterate_digital_footprint": (ActionClass.DELETE, "IRREVERSIBLE"),
    "sanitize_filename": (ActionClass.DELETE, "IRREVERSIBLE"),
    "scrub_dns_whois": (ActionClass.DELETE, "IRREVERSIBLE"),

    # ── ARCHIVE ─────────────────────────────────────────────────────
    "ast_search": (ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),
    "decompress_file": (ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),
    "mysql_backup": (ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),
    "mysql_restore": (ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),
    "transform_data": (ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),

    # ── MODIFY ─────────────────────────────────────────────────────
    "adr_generator": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "apply_patch": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "awssecurityhub_create_alert": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "clipboard": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_alert": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_chaos_experiment": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_chaos_experiment_from_scenario": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_diagram": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_flowchart": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_research_graph": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "create_waf_rule": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "dashboard_generator": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "distributed_tracing": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_api_client": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_api_docs": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_architecture_diagram": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_artifact_manifest": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_changelog": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_citation": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_class": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_design_pattern": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_embedding": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_function": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_latex_document": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_math_proof": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_mock": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_module": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_numerical_code": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_password": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_pdf_document": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_powerpoint": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_property_test": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_readme": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_symbolic_math": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_test": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generate_word_document": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "generatehypothesis": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "link_claim_to_evidence": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "misp_create_event": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "modify_config_file": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "obfuscate_identity": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "pagerduty_create_alert": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "pagerduty_update_alert": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "redis_set": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "restapi_create_alert": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "set_environment_variable": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "store_memory": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "synthesize_literature": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "test_data_generator": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "thehive_create_alert": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "thehive_create_case": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "thehive_update_alert": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "update_docs": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    "update_system": (ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),

    # ── EXECUTE ─────────────────────────────────────────────────────
    "chaos_testing": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "crowdstrike_run_rtr_command": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "execute_deterministic": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "execute_network_isolated": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "execute_with_artifact_capture": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "execute_with_resource_limits": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "fuzz_testing": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "golden_test_harness": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "integration_test_runner": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "load_test": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "manage_docker": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "mutation_testing": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "notification": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "notify_dominion_labs_team": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "post_slack_message": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "post_to_webhook": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "qradar_search_aql": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "run_chaos_experiment": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "run_coverage": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "run_inference": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "run_monte_carlo": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "run_pytest": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "run_unittest": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "safe_query_executor": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "send_slack_message": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "shuffle_execute_workflow": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "splunk_search": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "static_security_analysis": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "transaction_wrapper": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "triggerselfimprovement": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "upload_file": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),
    "websocket_connect": (ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE"),

    # ── INVESTIGATE ─────────────────────────────────────────────────────
    "alienvaultotx_get_subscribed_pulses": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "alienvaultotx_search_pulses": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "analyze_anomaly": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "analyze_research_paper": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "analyze_test_coverage_report": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "analyze_traffic_pattern": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "anomaly_detection": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "arcsight_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "arcsight_fetch_investigations": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "arcsight_get_active_channels": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "arcsight_get_cases": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "awssecurityhub_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "awssecurityhub_fetch_metrics": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "awssecurityhub_get_findings": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "azuresecuritycenter_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "azuresecuritycenter_fetch_metrics": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "azuresecuritycenter_get_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "azuresecuritycenter_get_recommendations": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "azuresecuritycenter_get_secure_score": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "benchmark_code": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "benchmarklearningsystems": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "browser_navigate": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_code_style_consistency": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_dependencies": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_ip_threat_intelligence": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_malicious_patterns": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_mysql_health": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_rate_limit": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_syntax": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "check_url_status": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "count_lines": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "crowdstrike_get_host_info": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "crowdstrike_search_detections": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "detect_brute_force": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "detect_code_smells": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "detect_digital_footprint": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "detect_intrusion": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "detect_zero_day": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "detectpatterns": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "extract_call_graph": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "extract_docstrings": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "extract_entities": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "extract_links": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "extract_method": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "extract_paper_metadata": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "extractlessonslearned": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "fetch_paper_by_arxiv": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "fetch_paper_by_doi": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "file_watcher": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "find_circular_imports": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "find_dead_code": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "find_performance_issues": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "find_todos": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "forecastcapabilities": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_active_blocks": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_block_history": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_channel_history": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_chaos_experiment_status": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_cpu_usage": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_disk_usage": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_environment_variable": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_memory_usage": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_model_info": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_network_stats": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_performance_profile": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_security_metrics": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_service_status": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_slack_channels": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_slack_users": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_team_health_metrics": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "get_user_presence": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "github_get_code_scanning_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "github_get_repository_security_summary": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "github_get_secret_scanning_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "github_get_vulnerabilities": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "github_list_repositories": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "grep_search": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "license_attribution_check": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "list_chaos_scenarios": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "list_usb_devices": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "logrhythm_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "logrhythm_get_alarms": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "logrhythm_get_cases": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "logrhythm_search_logs": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "migration_runner": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "misp_get_event": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "misp_get_events": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "misp_search_iocs": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "monitor_logs": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "monitor_team_activity": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "monitordatadrift": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "mysql_table_info": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "pagerduty_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "pagerduty_fetch_users": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "pagerduty_get_incidents": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "pagerduty_get_services": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "parse_csv": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "parse_html": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "parse_logs": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "pii_scrubbing": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "ping_host": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "port_scan": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "profileperformance": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "qradar_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "qradar_fetch_metrics": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "qradar_get_offenses": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "qualys_get_host_list": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "query_memory": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "query_metrics": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "recommendtraining": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "recordedfuture_search_threat_actors": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "redis_get": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "report_security_finding": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "restapi_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "scan_secrets": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "search_academic": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "search_data": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "search_news": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "search_secrets_pii": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "search_slack_messages": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "security_scan": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "semantic_search": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "semantic_similarity": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "shodan_get_host_info": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "shodan_search_exploits": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "shodan_search_hosts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "shuffle_get_workflows": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "slo_sli_tooling": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "snyk_get_all_vulnerabilities": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "snyk_get_organizations": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "snyk_get_project_issues": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "snyk_get_projects": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "sonarqube_get_hotspots": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "sonarqube_get_issues": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "sonarqube_get_measures": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "sonarqube_get_project_security_summary": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "sonarqube_get_projects": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "thehive_fetch_alerts": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "thehive_fetch_investigations": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "thehive_get_cases": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "threatconnect_get_indicators": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "trace_dependencies": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "type_check": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_bibliography": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_certificate": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_email": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_json": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_schema": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_sql_input": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_url": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_xml": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "validate_yaml": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "virustotal_get_domain_report": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "virustotal_get_ip_report": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "virustotal_scan_file": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "virustotal_scan_url": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "web_fetch": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
    "web_search": (ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
}

# Shell/python are whatever the payload makes them, so read the payload.
# Ordered most-severe first: the first match wins.
_PAYLOAD_PATTERNS = [
    (r"\brm\s+(-[a-zA-Z]*\s+)*", ActionClass.DELETE, "IRREVERSIBLE"),
    (r"\bshutil\.rmtree\b", ActionClass.DELETE, "IRREVERSIBLE"),
    (r"\bos\.remove\b|\bos\.unlink\b|\bPath\([^)]*\)\.unlink\b|\.unlink\(", ActionClass.DELETE, "IRREVERSIBLE"),
    (r"\bmkfs\b|\bdd\s+if=|\b>\s*/dev/", ActionClass.DELETE, "IRREVERSIBLE"),
    (r"\bDROP\s+(TABLE|DATABASE)\b|\bTRUNCATE\s+TABLE\b", ActionClass.DELETE, "IRREVERSIBLE"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f)", ActionClass.DELETE, "IRREVERSIBLE"),
    (r"\bkill\s+-9\b|\bpkill\b", ActionClass.EXECUTE, "MOSTLY_IRREVERSIBLE"),
    (r"\bshutil\.move\b|\bos\.rename\b|\bmv\s+", ActionClass.ARCHIVE, "MOSTLY_REVERSIBLE"),
    (r"\bopen\([^)]*['\"][wa]", ActionClass.MODIFY, "PARTIALLY_REVERSIBLE"),
    (r"\bshutil\.copy", ActionClass.MODIFY, "FULLY_REVERSIBLE"),
    (r"\b(cat|head|tail|ls|grep|find|wc|stat)\b", ActionClass.INVESTIGATE, "FULLY_REVERSIBLE"),
]

_PAYLOAD_KEYS = ("command", "code", "script", "cmd", "shell_command")


def classify_action(tool_name: str, parameters: Dict[str, Any]) -> Tuple[ActionClass, str]:
    """(action class, irreversibility) for this specific invocation.

    Unknown tools are NOT assumed safe -- but they are not assumed destructive
    either, or every unmapped tool would be blocked under a strict contract.
    They classify as EXECUTE/PARTIALLY_REVERSIBLE: strong enough that an
    investigate-only contract refuses them, weak enough not to break a
    contract that already permits state change.
    """
    name = (tool_name or "").lower()
    sensitive = target_sensitivity(parameters or {})

    def _result(cls, irr):
        """Consequence is verb x target. The verb alone cannot tell
        `delete_file /tmp/scratch.txt` from `delete_file
        core/security/safety_framework.py` -- both were DELETE/IRREVERSIBLE,
        which made a contract unable to authorise the first without also
        authorising the second. A declared-sensitive target raises the
        consequence one step; it never lowers it, and it never changes the verb,
        because what the action DOES is not altered by what it points at."""
        return (cls, _escalate(irr) if sensitive else irr)

    if name in _TOOL_CONSEQUENCE:
        cls, irr = _TOOL_CONSEQUENCE[name]
        # A shell/python tool mapped above still needs its payload read.
        if name not in ("run_shell_command", "run_python"):
            return _result(cls, irr)

    payload = " ".join(
        str(parameters.get(k, "")) for k in _PAYLOAD_KEYS if parameters.get(k)
    )
    if payload:
        for pattern, cls, irr in _PAYLOAD_PATTERNS:
            if re.search(pattern, payload, re.IGNORECASE):
                return _result(cls, irr)

    if name in ("run_shell_command", "run_python"):
        # Ran something we could not classify — treat as a real side effect.
        return _result(ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE")

    if name in _TOOL_CONSEQUENCE:
        return _result(*_TOOL_CONSEQUENCE[name])

    declared = _declared_consequence(name)
    if declared is not None:
        return _result(*declared)

    return _result(ActionClass.EXECUTE, "PARTIALLY_REVERSIBLE")


#: Parameter keys that name what an action is aimed AT.
_TARGET_KEYS = ("file_path", "path", "target_path", "destination_path",
                "source_path", "directory", "target")


def target_sensitivity(parameters: Dict[str, Any]) -> Optional[str]:
    """Which declared-sensitive target this invocation touches, if any.

    Read from governance's already-loaded trigger config, which is the one
    place target sensitivity is declared (`safety_infrastructure_write` knows
    core/safety|security|governance/, `credential_file_read` knows ~/.ssh and
    friends). Re-encoding those regexes here would be a second owner for the
    same question, free to disagree with the first the next time either moves.

    Returns the trigger_id that claims the target, or None.
    """
    values = [str(parameters.get(k)) for k in _TARGET_KEYS if parameters.get(k)]
    if not values:
        return None
    haystack = " ".join(values)
    try:
        from core.governance import get_unified_governance
        config = getattr(get_unified_governance(), "config", None) or {}
        for _category, body in (config.get("action_categories") or {}).items():
            for trigger in body.get("triggers", []):
                params = ((trigger.get("conditions") or {}).get("parameters") or {})
                for key in _TARGET_KEYS:
                    rule = params.get(key)
                    if isinstance(rule, dict) and rule.get("matches"):
                        if re.search(rule["matches"], haystack, re.IGNORECASE):
                            return trigger["trigger_id"]
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("target sensitivity unavailable: %s", e)
    return None


def _escalate(irreversibility: str) -> str:
    """One step stronger, saturating at IRREVERSIBLE."""
    order = _IRREVERSIBILITY_ORDER
    try:
        return order[min(order.index(irreversibility) + 1, len(order) - 1)]
    except ValueError:
        return irreversibility


def _declared_consequence(name: str) -> Optional[Tuple[ActionClass, str]]:
    """What the tool itself says it does, if it says anything.

    Consulted AFTER the payload patterns and the curated table, so a tool
    cannot declare its way out of a rule about what it is actually being asked
    to do: `run_shell_command` is whatever its command is, whatever the class
    declares. Consulted BEFORE the unknown-tool default, so a tool that has
    told us what it does is not treated as unknown.

    Registry problems are swallowed deliberately -- a tool lookup failing must
    degrade to the calibrated default, never raise inside a safety check.
    """
    try:
        from core.tools import get_tool_registry
        registry = get_tool_registry()
        tool = registry.tools.get(name)
        if tool is None:
            factory = registry.tool_factories.get(name)
            if factory is None:
                return None
            tool = factory() if callable(factory) else None
        declared = getattr(tool, "consequence", None)
        if not declared:
            return None
        action_class, irreversibility = declared
        return ActionClass(str(action_class).lower()), str(irreversibility).upper()
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("could not read declared consequence for %s: %s", name, e)
        return None


__all__ = ["classify_action"]
