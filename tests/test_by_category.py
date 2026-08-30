#!/usr/bin/env python3
"""
Test Tools by Category
======================
Run tool tests organized by category for better performance and debugging.

Usage:
    python3 tests/test_by_category.py filesystem
    python3 tests/test_by_category.py all
"""

import pytest
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / '.env.production')

from core.tools.tool_registry import get_tool_registry

# Simple test parameters for each tool
SIMPLE_TEST_PARAMS = {
    # ===== FILESYSTEM (17 tools) =====
    'write_file': {'file_path': '/tmp/torin_test.txt', 'content': 'test'},
    'read_file': {'file_path': '/tmp/torin_atomic.txt'},  # Use atomic file that persists
    'list_directory': {'directory_path': '/tmp'},
    'delete_file': {'path': '/private/tmp/torin_delete_test.txt', 'confirm': True},  # Created by setup_test_env
    'create_directory': {'directory_path': '/tmp/torin_test_dir_' + str(datetime.now().timestamp())},
    'copy_file': {'source_path': '/tmp/torin_atomic.txt', 'destination_path': '/tmp/torin_test_copy_' + str(datetime.now().timestamp()) + '.txt'},
    'move_file': {'source_path': '/tmp/torin_test.txt', 'destination_path': '/tmp/torin_test_moved_' + str(datetime.now().timestamp()) + '.txt'},
    'search_files': {'pattern': '*.txt', 'base_path': '/tmp'},
    'atomic_write_file': {'file_path': '/tmp/torin_atomic.txt', 'content': 'atomic'},
    'validate_path': {'path': '/tmp', 'allowed_roots': ['/tmp'], 'must_exist': True},
    'get_file_info': {'file_path': '/tmp/torin_atomic.txt'},
    'calculate_checksum': {'file_path': '/tmp/torin_atomic.txt'},
    'compress_file': {'source_path': '/tmp/torin_atomic.txt', 'archive_path': '/tmp/test_' + str(datetime.now().timestamp()) + '.zip'},
    'decompress_file': {'archive_path': '/tmp/test.zip', 'destination_path': '/tmp/extracted_' + str(datetime.now().timestamp())},
    'find_duplicate_files': {'directory_path': '/tmp/torin_tool_tests'},  # Use safer test directory
    'sync_directory': {'source_path': '/tmp/torin_tool_tests', 'destination_path': '/tmp/sync_dest_' + str(datetime.now().timestamp())},
    'file_watcher': {'file_paths': ['/tmp/torin_atomic.txt']},

    # ===== EXECUTION (17 tools) =====
    'run_python': {'code': 'print("test")'},
    'run_shell_command': {'command': 'echo test'},
    'execute_sandbox': {'code': 'print("test")'},
    'list_processes': {},
    'kill_process': {'pid': 'SPAWN_TEST_PROCESS'},  # Will spawn process dynamically
    'start_service': {'service_name': 'test_service'},
    'stop_service': {'service_name': 'test_service'},
    'restart_service': {'service_name': 'test_service'},
    'get_process_info': {'pid': os.getpid()},  # Use current process
    'run_background_task': {'command': 'sleep 1'},
    'schedule_cron_job': {'command': f'echo torin_test_{int(datetime.now().timestamp())}', 'schedule': '0 0 * * *'},
    'install_python_package': {'package_name': 'requests'},
    'execute_with_timeout': {'command': 'echo test', 'hard_timeout': 5},
    'execute_with_resource_limits': {'command': 'print("test")', 'language': 'python'},
    'execute_network_isolated': {'code': 'print("test")'},
    'execute_deterministic': {'code': 'print("test")'},
    'execute_with_artifact_capture': {'command': 'print("test")', 'language': 'python'},

    # ===== DATABASE (16 tools) =====
    'mysql_query': {'query': 'SELECT 1'},
    'mysql_table_info': {'table_name': 'test_sessions'},
    'mysql_backup': {'table_name': 'test_results', 'output_path': '/tmp/backup.json'},
    'mysql_restore': {'table_name': 'test_results', 'backup_path': '/tmp/backup.json'},
    'redis_get': {'key': 'test_key'},
    'redis_set': {'key': 'test_key', 'value': 'test_value'},
    'r2_upload': {'file_path': '/tmp/torin_test.txt', 'object_key': 'test_object'},
    'r2_download': {'object_key': 'test_object', 'file_path': '/tmp/downloaded.txt'},
    'connection_pool_manager': {'operation': 'check_health'},
    'transaction_wrapper': {'queries': ['SELECT 1']},
    'migration_runner': {'operation': 'get_history'},
    'row_level_access_control': {'operation': 'create_policy', 'table_name': 'test_sessions', 'service_user': 'test', 'allowed_owners': ['test_user']},
    'safe_query_executor': {'query': 'SELECT 1'},
    'check_mysql_health': {},
    'query_metrics': {'metric_type': 'health'},
    'create_alert': {'alert_type': 'health', 'message': 'test alert'},

    # ===== NETWORK (18 tools) =====
    'http_request': {'url': 'https://httpbin.org/get', 'method': 'GET'},
    'download_file': {'url': 'https://httpbin.org/robots.txt', 'destination_path': '/tmp/robots.txt'},
    'upload_file': {'url': 'https://httpbin.org/post', 'file_path': '/tmp/torin_atomic.txt'},
    'parse_html': {'html': '<html><body><h1>Test</h1></body></html>', 'selector': 'h1'},
    'extract_links': {'html': '<html><body><a href="http://test.com">Link</a></body></html>'},
    'check_url_status': {'url': 'https://httpbin.org'},
    'dns_lookup': {'domain': 'google.com'},
    'ping_host': {'host': '8.8.8.8'},
    'port_scan': {'host': '127.0.0.1', 'ports': [80, 443]},
    'websocket_connect': {'url': 'wss://echo.websocket.org'},
    'graphql_query': {'url': 'https://httpbin.org/graphql', 'query': '{ test }'},
    'api_call': {'url': 'https://httpbin.org/get'},
    'conduct_research': {'topic': 'AI testing'},
    'search_academic': {'query': 'machine learning'},
    'search_data': {'query': 'test data'},
    'search_news': {'query': 'technology'},
    'fetch_paper_by_doi': {'doi': '10.1234/test.doi'},
    'fetch_paper_by_arxiv': {'arxiv_id': '2301.00000'},

    # ===== SECURITY (25 tools) =====
    'encrypt_file': {'input_file': '/tmp/torin_atomic.txt', 'output_file': '/tmp/encrypted.txt', 'password': 'test123'},
    'decrypt_file': {'input_file': '/tmp/encrypted.txt', 'output_file': '/tmp/decrypted.txt', 'password': 'test123'},
    'generate_password': {},
    'hash_data': {'data': 'test data'},
    'validate_certificate': {'hostname': 'google.com'},
    'scan_secrets': {'directory_path': '/tmp'},
    'check_ip_threat_intelligence': {'ip_address': '8.8.8.8'},
    'block_ip_address': {'ip_address': '192.168.1.1', 'reason': 'test block'},
    'unblock_ip_address': {'ip_address': '192.168.1.1'},
    'get_active_blocks': {},
    'create_waf_rule': {'expression': 'test_rule', 'action': 'block', 'description': 'test WAF rule'},
    'apply_rate_limit': {'ip_address': '192.168.1.1', 'requests_per_minute': 100},
    'block_country': {'country_code': 'XX', 'reason': 'test geo-block'},
    'get_security_metrics': {},
    'get_block_history': {},
    'add_internal_threat': {'ip_address': '127.0.0.1', 'threat_types': [], 'reputation_score': 1},
    'sanitize_input': {'input_data': 'test<script>alert()</script>'},
    'detect_intrusion': {},
    'analyze_anomaly': {'entity_id': 'test'},
    'monitor_logs': {'log_source': 'auth'},
    'detect_brute_force': {},
    'analyze_traffic_pattern': {},
    'auto_respond_threat': {'threat_id': 'test', 'threat_type': 'brute_force', 'response_action': 'block_ip', 'severity': 'high'},
    'hunt_threats': {'iocs': [], 'hunt_type': 'ioc_based'},
    'detect_zero_day': {},

    # ===== CODE GENERATION (28 tools) =====
    'generate_function': {'description': 'test function', 'function_name': 'test_func'},
    'refactor_code': {'code': 'def test(): pass'},
    'add_docstring': {'code': 'def test(): pass'},
    'add_type_hints': {'code': 'def test(x, y): return x + y'},
    'format_code': {'code': 'def test():pass'},
    'fix_linting_errors': {'code': 'def test( ): pass'},
    'generate_test': {'code': 'def add(x, y): return x + y'},
    'migrate_code': {'code': 'print "test"', 'source_version': 'python2', 'target_version': 'python3'},
    'generate_class': {'class_name': 'TestClass', 'description': 'test class'},
    'generate_module': {'module_name': 'test_module', 'description': 'test'},
    'add_logging': {'code': 'def test(): pass'},
    'optimize_code': {'code': 'def test(): x = 1; y = 2; return x + y'},
    'convert_to_async': {'code': 'def test(): return 1'},
    'extract_method': {'code': 'def test(): x = 1; y = 2; return x + y', 'start_line': 1, 'end_line': 2},
    'inline_variable': {'code': 'def test(): x = 1; return x', 'variable_name': 'x'},
    'rename_symbol': {'code': 'def old_name(): pass', 'old_name': 'old_name', 'new_name': 'new_name'},
    'implement_algorithm': {'algorithm_name': 'binary_search'},
    'generate_symbolic_math': {'expression': 'x^2 + 2*x + 1'},
    'generate_numerical_code': {'formula': 'f(x) = x^2'},
    'generate_math_proof': {'theorem': 'pythagorean'},
    'generate_design_pattern': {'pattern_name': 'singleton'},
    'generate_api_client': {'api_spec': 'test api'},
    'scaffold_application': {'app_type': 'web', 'framework': 'flask'},
    'synthesize_from_examples': {'examples': [{'input': 1, 'output': 2}]},
    'generate_property_test': {'code': 'def add(x, y): return x + y'},
    'apply_patch': {'code': 'def test(): pass', 'patch': 'diff'},
    'compile_typecheck_gate': {'code': 'def test(): pass'},
    'repository_refactor': {'operation': 'analyze'},
    'license_attribution_check': {'code': 'def test(): pass'},

    # ===== SYSTEM/TESTING (35 tools) =====
    'system_info': {},
    'clipboard': {'action': 'read'},
    'notification': {'title': 'Test', 'message': 'test'},
    'lint_python': {'code': 'def test(): pass'},
    'type_check': {'code': 'def test(): pass'},
    'run_pytest': {},
    'run_unittest': {'test_path': '/tmp'},
    'check_syntax': {'code': 'def test(): pass'},
    'validate_json': {'json_data': '{"test": true}'},
    'validate_yaml': {'yaml_data': 'test: true'},
    'benchmark_code': {'code': 'def test(): pass'},
    'generate_mock': {'interface': 'test'},
    'run_coverage': {},
    'validate_xml': {'xml_data': '<test>data</test>'},
    'validate_schema': {'data': {}, 'schema': {}},
    'load_test': {'url': 'https://httpbin.org/get', 'requests': 10},
    'integration_test_runner': {'test_suite': 'test'},
    'test_data_generator': {'schema': {'type': 'object'}},
    'fuzz_testing': {'target_file': '/tmp/torin_atomic.txt', 'target_function': 'test'},
    'mutation_testing': {'source_file': '/tmp/torin_atomic.txt', 'test_file': '/tmp/torin_atomic.txt'},
    'static_security_analysis': {'code': 'def test(): pass'},
    'golden_test_harness': {'test_file': '/tmp/test.txt', 'golden_dir': '/tmp'},
    'chaos_testing': {'chaos_type': 'latency', 'target': 'test'},

    # Chaos Engineering Tools
    'createchaosexperiment': {
        'name': 'Test Chaos Experiment',
        'description': 'Test experiment for tool testing',
        'target_system': 'tool_system',
        'chaos_type': 'LATENCY',
        'component': 'tool_registry',
        'injection_point': 'execute_tool',
        'environment': 'dev',
        'blast_radius': 10,
        'duration_seconds': 60
    },
    'runchaosexperiment': {'experiment_id': 'test-experiment-id'},
    'createchaosexperimentfromscenario': {'scenario_name': 'tool_registry_latency'},
    'listchaosscenarios': {},
    'getchaosexperimentstatus': {'experiment_id': 'test-experiment-id'},
    'rollbackchaosexperiment': {'experiment_id': 'test-experiment-id', 'reason': 'Test rollback'},

    'generate_embedding': {'text': 'test text'},
    'query_memory': {'query': 'test query'},
    'store_memory': {'content': 'test content'},
    'run_inference': {'model_name': 'test', 'input_data': {}},
    'analyze_training_data': {'data': []},
    'get_model_info': {},
    'semantic_similarity': {'text1': 'test', 'text2': 'test'},
    'extract_entities': {'text': 'test text'},
    'set_environment_variable': {'key': 'TEST_VAR', 'value': 'test'},
    'get_environment_variable': {'key': 'PATH'},
    'modify_config_file': {'config_file': '/tmp/config.ini', 'key_path': 'test.key', 'value': 'value'},
    'reload_config': {},
    'check_dependencies': {},
    'update_system': {},
    'manage_docker': {'action': 'list'},

    # ===== DOCUMENTATION (14 tools) =====
    'generate_readme': {'project_path': '/tmp'},
    'generate_api_docs': {'code': 'def test(): pass'},
    'extract_docstrings': {'code': 'def test():\n    """Test function"""\n    pass'},
    'generate_changelog': {},
    'create_diagram': {'diagram_type': 'flowchart', 'content': 'A -> B'},
    'update_docs': {'docs_path': '/tmp/docs', 'changes': []},
    'docs_build_preview': {'docs_dir': '/tmp/docs'},
    'versioned_doc_deployment': {'version': '1.0.0', 'docs_path': '/tmp/docs'},
    'adr_generator': {'decision_title': 'test decision', 'context': 'test', 'decision': 'test'},
    'analyze_research_paper': {'paper_text': 'test paper'},
    'generate_citation': {'paper_info': {'title': 'Test', 'authors': ['Author']}},
    'synthesize_literature': {'research_question': 'What is AI?', 'papers': []},
    'extract_paper_metadata': {'paper_text': 'test'},
    'generate_architecture_diagram': {'components': []},

    # ===== MONITORING (11 tools) =====
    'get_cpu_usage': {},
    'get_memory_usage': {},
    'get_disk_usage': {},
    'get_network_stats': {},
    'get_service_status': {'service_name': 'test'},
    'parse_logs': {'log_file': '/private/tmp/torin_atomic.txt'},
    'get_performance_profile': {},
    'distributed_tracing': {'operation': 'create_trace'},
    'slo_sli_tooling': {'operation': 'list_slos'},
    'anomaly_detection': {'metric_name': 'cpu_usage', 'values': [10, 20, 30]},
    'dashboard_generator': {'dashboard_name': 'Test Dashboard', 'panels': [{'title': 'CPU Usage', 'type': 'graph', 'metric': 'cpu_percent'}]},

    # ===== SEARCH (20 tools) =====
    'semantic_search': {'query': 'test query', 'workspace_path': '/tmp'},
    'grep_search': {'pattern': 'test', 'path': '/tmp'},
    'analyze_code': {'file_path': '/tmp/torin_test.txt'},
    'analyze_code_quality': {'file_path': '/tmp/torin_test.txt'},
    'analyze_dependencies': {'project_path': '/tmp'},
    'find_dead_code': {'directory_path': '/tmp'},
    'security_scan': {'file_path': '/tmp/torin_test.txt'},
    'find_todos': {'directory_path': '/tmp'},
    'count_lines': {'directory_path': '/tmp'},
    'analyze_complexity': {'file_path': '/private/tmp/torin_test.txt'},
    'detect_code_smells': {'file_path': '/private/tmp/torin_test.txt'},
    'trace_dependencies': {'project_path': '/tmp'},
    'find_circular_imports': {'project_path': '/tmp'},
    'analyze_test_coverage_report': {'coverage_file': '/private/tmp/coverage.xml'},
    'find_performance_issues': {'file_path': '/private/tmp/torin_test.txt'},
    'check_code_style_consistency': {'directory_path': '/tmp'},
    'ast_search': {'directory_path': '/tmp', 'search_type': 'function_def', 'symbol_name': 'test'},
    'build_dependency_graph': {'project_path': '/tmp'},
    'extract_call_graph': {'directory_path': '/tmp'},
    'search_secrets_pii': {'directory_path': '/tmp'},

    # ===== DATA PROCESSING (17 tools) =====
    'parse_json': {'input': '{"test": true}'},
    'parse_yaml': {'input': 'test: true'},
    'parse_csv': {'file_path': '/private/tmp/torin_test.csv'},
    'convert_format': {'input_file': '/private/tmp/torin_test.json', 'output_file': '/private/tmp/torin_output.yaml', 'output_format': 'yaml'},
    'transform_data': {'data': [{'name': 'test', 'value': 1}], 'select_fields': ['name']},
    'aggregate_data': {'data': [{'category': 'A', 'value': 10}], 'group_by': 'category'},
    'merge_datasets': {'dataset1': [{'id': 1, 'name': 'A'}], 'dataset2': [{'id': 1, 'score': 100}], 'key_field': 'id'},
    'filter_data': {'data': [{'status': 'active', 'value': 10}], 'field': 'status', 'value': 'active'},
    'sort_data': {'data': [{'name': 'B', 'score': 10}, {'name': 'A', 'score': 20}], 'sort_by': 'score'},
    'deduplicate_data': {'data': [{'id': 1}, {'id': 2}, {'id': 1}]},
    'parse_jsonl': {'file_path': '/private/tmp/torin_test.jsonl'},
    'schema_inference': {'data': [{'a': 1}]},
    'pii_scrubbing': {'data': {'text': 'John Doe 555-1234', 'email': 'test@example.com'}},
    'dataset_profiling': {'data': [{'value': 10}, {'value': 20}]},
    'analyze_research_data': {'data': {'values': [1, 2, 3, 4, 5]}},
    'create_research_graph': {'data': {'x': [1, 2, 3, 4], 'y': [10, 20, 15, 25]}, 'graph_type': 'line', 'title': 'Test Graph'},

    # ===== COMMUNICATION (2 tools) =====
    'send_slack_message': {'channel': 'torin-activity', 'message': 'test'},
    'post_to_webhook': {'webhook_url': 'https://httpbin.org/post', 'data': {'test': True}},

    # ===== AI/ML (2 tools) - already covered above =====

    # ===== UNCATEGORIZED (6 tools) - need to discover =====
}


async def setup_test_env():
    """Setup test environment"""
    import os
    import tempfile
    import json

    # Create dedicated test directory
    test_dir = os.path.join(tempfile.gettempdir(), 'torin_tool_tests')
    os.makedirs(test_dir, exist_ok=True)

    # Create test file
    test_file = os.path.join(test_dir, 'test.txt')
    with open(test_file, 'w') as f:
        f.write('test content')

    # Create file for delete test (always recreate in case previous test deleted it)
    delete_test_file = '/private/tmp/torin_delete_test.txt'
    with open(delete_test_file, 'w') as f:
        f.write('delete me')

    # Also ensure atomic test file exists
    atomic_test_file = '/private/tmp/torin_atomic.txt'
    if not os.path.exists(atomic_test_file):
        with open(atomic_test_file, 'w') as f:
            f.write('atomic test content')

    # Create test CSV file for data processing (use /private/tmp for macOS compatibility)
    csv_test_file = '/private/tmp/torin_test.csv'
    with open(csv_test_file, 'w') as f:
        f.write('name,value,category\n')
        f.write('A,10,cat1\n')
        f.write('B,20,cat2\n')

    # Create test JSON file for format conversion
    json_test_file = '/private/tmp/torin_test.json'
    with open(json_test_file, 'w') as f:
        json.dump({'test': 'data', 'value': 123}, f)

    # Create test JSONL file
    jsonl_test_file = '/private/tmp/torin_test.jsonl'
    with open(jsonl_test_file, 'w') as f:
        f.write('{"id": 1, "name": "A"}\n')
        f.write('{"id": 2, "name": "B"}\n')

    # Create test Python file for search/analysis tools
    py_test_file = '/private/tmp/torin_test.txt'
    with open(py_test_file, 'w') as f:
        f.write('#!/usr/bin/env python3\n')
        f.write('"""Test module"""\n\n')
        f.write('def test_function(x, y):\n')
        f.write('    """Test function"""\n')
        f.write('    return x + y\n\n')
        f.write('class TestClass:\n')
        f.write('    """Test class"""\n')
        f.write('    def method(self):\n')
        f.write('        pass\n')

    return test_dir, test_file


@pytest.mark.asyncio
# Helper, not a pytest test: it takes an argument and is driven by the
# script's own runner below. Named `test_*` it was collected anyway and
# pytest failed resolving the argument as a fixture -- an error that
# reported the file as broken while the script itself worked.
async def check_category(category_name: str):
    """Test all tools in a specific category"""
    registry = get_tool_registry()
    all_tools = registry.list_tools()

    # Pre-load LLM service ONCE to avoid reloading 32GB model for every tool
    print("Initializing LLM service (one-time load)...")
    try:
        from core.services.unified_llm import get_llm_service
        llm = get_llm_service()
        if not llm.model_loaded:
            await llm.initialize()
        print("✓ LLM service initialized and ready\n")
    except Exception as e:
        print(f"⚠ LLM service initialization failed (some tools may fail): {e}\n")

    # Setup test environment
    test_dir, test_file = await setup_test_env()

    # Filter by category
    category_tools = []
    for tool in all_tools:
        try:
            cat = str(tool.category.value if hasattr(tool.category, 'value') else tool.category) if hasattr(tool, 'category') else 'uncategorized'
        except:
            cat = 'uncategorized'

        if cat == category_name or category_name == 'all':
            category_tools.append(tool)

    if not category_tools:
        print(f"No tools found in category: {category_name}")
        return

    print(f"\n{'='*70}")
    print(f"Testing {len(category_tools)} tools in category: {category_name.upper()}")
    print(f"{'='*70}\n")

    passed = 0
    failed = 0
    skipped = 0

    for tool in category_tools:
        # Get test params or skip
        params = SIMPLE_TEST_PARAMS.get(tool.name, {})

        # Special handling for kill_process: spawn a test process
        if tool.name == 'kill_process' and params.get('pid') == 'SPAWN_TEST_PROCESS':
            import subprocess
            test_proc = subprocess.Popen(['sleep', '60'])
            params = {'pid': test_proc.pid, 'force': False}

        try:
            result = await registry.execute_tool(tool.name, params)

            if result.success:
                print(f"✓ {tool.name}")
                passed += 1
            else:
                error_msg = result.error[:80] if result.error else 'Unknown error'
                print(f"✗ {tool.name}: {error_msg}")
                failed += 1

        except Exception as e:
            error_msg = str(e)[:80]
            print(f"✗ {tool.name}: {error_msg}")
            failed += 1

    # Summary
    total = passed + failed + skipped
    pass_rate = (passed / total * 100) if total > 0 else 0

    print(f"\n{'='*70}")
    print(f"Category: {category_name}")
    print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print(f"Pass Rate: {pass_rate:.1f}%")
    print(f"{'='*70}\n")

    return {
        'category': category_name,
        'total': total,
        'passed': passed,
        'failed': failed,
        'pass_rate': pass_rate
    }


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tests/test_by_category.py <category>")
        print("\nAvailable categories:")
        print("  - filesystem")
        print("  - execution")
        print("  - database")
        print("  - network")
        print("  - security")
        print("  - system")
        print("  - code_generation")
        print("  - documentation")
        print("  - monitoring")
        print("  - search")
        print("  - data_processing")
        print("  - ai_ml")
        print("  - communication")
        print("  - all (run all categories)")
        sys.exit(1)

    category = sys.argv[1].lower()

    if category == 'all':
        categories = [
            'filesystem', 'execution', 'database', 'network', 'security',
            'system', 'code_generation', 'documentation', 'monitoring',
            'search', 'data_processing', 'ai_ml', 'communication', 'uncategorized'
        ]

        all_results = []
        for cat in categories:
            result = await check_category(cat)
            all_results.append(result)

        # Overall summary
        print(f"\n{'='*70}")
        print("OVERALL SUMMARY")
        print(f"{'='*70}")
        for result in all_results:
            print(f"{result['category']:20} | {result['passed']:3}/{result['total']:3} passed ({result['pass_rate']:.1f}%)")
        print(f"{'='*70}\n")
    else:
        await check_category(category)


if __name__ == "__main__":
    asyncio.run(main())
