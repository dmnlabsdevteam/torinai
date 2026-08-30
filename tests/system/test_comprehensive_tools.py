#!/usr/bin/env python3
"""
Comprehensive Tool Test Suite
==============================
Tests all extended and new tools to verify they register and function properly.

Run with: python3 -m pytest tests/test_comprehensive_tools.py -v

Author: Torin AI Team
"""

import asyncio
import pytest
import tempfile
import json
from pathlib import Path
from core.tools.tool_registry import get_tool_registry, ToolCategory


@pytest.fixture
def registry():
    """Get tool registry instance"""
    return get_tool_registry()


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestToolRegistry:
    """Test tool registry and registration"""

    def test_registry_created(self, registry):
        """Test that registry is properly created"""
        assert registry is not None
        assert len(registry.tools) > 0

    def test_all_categories_present(self, registry):
        """Test that all tool categories are present.

        Counted over the WHOLE registry, not `registry.tools`. That dict holds
        only eagerly-loaded tools -- 92 of 372 here -- so every assertion made
        against it silently measures a quarter of the system and reports the
        rest as absent. `category_index` is the view that includes lazily
        registered tools, which is what list_tools' own docstring warns about.
        """
        categories = {ToolCategory(name) for name in registry.category_index}

        expected_categories = {
            ToolCategory.FILESYSTEM,
            ToolCategory.EXECUTION,
            ToolCategory.SEARCH,
            ToolCategory.NETWORK,
            ToolCategory.DATABASE,
            ToolCategory.COMMUNICATION,
            ToolCategory.MONITORING,
            ToolCategory.AI_ML,
            ToolCategory.DATA_PROCESSING,
            ToolCategory.CODE_GENERATION,
            ToolCategory.TESTING,
            ToolCategory.DOCUMENTATION,
            ToolCategory.SYSTEM,
            ToolCategory.SECURITY
        }

        assert categories.issuperset(expected_categories), f"Missing categories: {expected_categories - categories}"

    def test_minimum_tool_count(self, registry):
        """Test that we have at least 100 tools registered (eager + lazy)."""
        registered = set(registry.tools) | set(registry.tool_factories)
        assert len(registered) >= 100, f"Expected at least 100 tools, got {len(registered)}"

    def test_tools_have_schemas(self, registry):
        """Test that all tools can generate JSON schemas"""
        schemas = registry.get_tools_schema()
        # get_tools_schema covers eager AND lazy tools; 12 names are registered
        # both ways, so the comparison is against the deduplicated union.
        registered = set(registry.tools) | set(registry.tool_factories)
        assert len(schemas) == len(registered)

        # get_tools_schema returns OpenAI function-calling format --
        # {"type": "function", "function": {...}} -- so the fields live one
        # level in. Asserting them at the top level passed vacuously for
        # nothing and failed once the format was correct.
        for schema in schemas:
            assert schema['type'] == 'function'
            fn = schema['function']
            assert 'name' in fn
            assert 'description' in fn
            assert 'parameters' in fn


class TestFilesystemToolsExtended:
    """Test extended filesystem tools"""

    @pytest.mark.asyncio
    async def test_copy_file_tool(self, registry, temp_dir):
        """Test file copy functionality"""
        tool = registry.get_tool('copy_file')
        assert tool is not None

        # Create source file
        source = temp_dir / "source.txt"
        source.write_text("test content")
        dest = temp_dir / "dest.txt"

        result = await tool.execute(
            source_path=str(source),
            destination_path=str(dest)
        )

        assert result.success is True
        assert dest.exists()
        assert dest.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_get_file_info_tool(self, registry, temp_dir):
        """Test file info retrieval"""
        tool = registry.get_tool('get_file_info')
        assert tool is not None

        test_file = temp_dir / "test.txt"
        test_file.write_text("hello")

        result = await tool.execute(file_path=str(test_file))

        assert result.success is True
        assert 'size_bytes' in result.output
        assert result.output['size_bytes'] == 5

    @pytest.mark.asyncio
    async def test_calculate_checksum_tool(self, registry, temp_dir):
        """Test checksum calculation"""
        tool = registry.get_tool('calculate_checksum')
        assert tool is not None

        test_file = temp_dir / "test.txt"
        test_file.write_text("hello world")

        result = await tool.execute(
            file_path=str(test_file),
            algorithm='sha256'
        )

        assert result.success is True
        assert 'checksum' in result.output
        assert len(result.output['checksum']) == 64  # SHA-256 is 64 hex chars


class TestDatabaseTools:
    """Test database and storage tools"""

    @pytest.mark.asyncio
    async def test_redis_tools_registered(self, registry):
        """Test that Redis tools are registered"""
        assert registry.get_tool('redis_get') is not None
        assert registry.get_tool('redis_set') is not None

    @pytest.mark.asyncio
    async def test_mysql_tools_registered(self, registry):
        """Test that MySQL tools are registered"""
        assert registry.get_tool('mysql_query') is not None
        assert registry.get_tool('mysql_table_info') is not None
        assert registry.get_tool('mysql_backup') is not None
        assert registry.get_tool('mysql_restore') is not None

    @pytest.mark.asyncio
    async def test_r2_tools_registered(self, registry):
        """Test that R2 storage tools are registered"""
        assert registry.get_tool('r2_upload') is not None
        assert registry.get_tool('r2_download') is not None


class TestNetworkTools:
    """Test network and web tools"""

    @pytest.mark.asyncio
    async def test_http_request_tool_registered(self, registry):
        """Test that HTTP request tool is registered"""
        tool = registry.get_tool('http_request')
        assert tool is not None
        assert tool.category == ToolCategory.NETWORK

    @pytest.mark.asyncio
    async def test_check_url_status_tool(self, registry):
        """Test URL status checking"""
        tool = registry.get_tool('check_url_status')
        assert tool is not None

        # Test with a reliable URL
        result = await tool.execute(url='https://www.google.com')
        assert result.success is True
        assert 'status' in result.output
        assert result.output['accessible'] is True


class TestCommunicationTools:
    """Test communication tools"""

    @pytest.mark.asyncio
    async def test_slack_tool_registered(self, registry):
        """Test that Slack message tool is registered"""
        tool = registry.get_tool('send_slack_message')
        assert tool is not None
        assert tool.category == ToolCategory.COMMUNICATION

    @pytest.mark.asyncio
    async def test_webhook_tool_registered(self, registry):
        """Test that webhook tool is registered"""
        tool = registry.get_tool('post_to_webhook')
        assert tool is not None


class TestMonitoringTools:
    """Test monitoring and metrics tools"""

    @pytest.mark.asyncio
    async def test_cpu_usage_tool(self, registry):
        """Test CPU usage monitoring"""
        tool = registry.get_tool('get_cpu_usage')
        assert tool is not None

        result = await tool.execute()
        assert result.success is True
        assert 'cpu_percent' in result.output

    @pytest.mark.asyncio
    async def test_memory_usage_tool(self, registry):
        """Test memory usage monitoring"""
        tool = registry.get_tool('get_memory_usage')
        assert tool is not None

        result = await tool.execute()
        assert result.success is True
        assert 'total_gb' in result.output
        assert 'available_gb' in result.output


class TestAIMLTools:
    """Test AI/ML operations tools"""

    @pytest.mark.asyncio
    async def test_ai_ml_tools_registered(self, registry):
        """Test that AI/ML tools are registered"""
        assert registry.get_tool('generate_embedding') is not None
        assert registry.get_tool('query_memory') is not None
        assert registry.get_tool('store_memory') is not None
        assert registry.get_tool('run_inference') is not None
        assert registry.get_tool('semantic_similarity') is not None


class TestDataProcessingTools:
    """Test data processing tools"""

    @pytest.mark.asyncio
    async def test_parse_json_tool(self, registry):
        """Test JSON parsing"""
        tool = registry.get_tool('parse_json')
        assert tool is not None

        test_json = '{"name": "test", "value": 123}'
        result = await tool.execute(input=test_json)

        assert result.success is True
        assert result.output['data']['name'] == 'test'

    @pytest.mark.asyncio
    async def test_filter_data_tool(self, registry):
        """Test data filtering"""
        tool = registry.get_tool('filter_data')
        assert tool is not None

        test_data = [
            {'name': 'Alice', 'age': 30},
            {'name': 'Bob', 'age': 25},
            {'name': 'Charlie', 'age': 35}
        ]

        result = await tool.execute(
            data=test_data,
            field='age',
            operator='gt',
            value='28'
        )

        assert result.success is True
        assert len(result.output['filtered_data']) == 2

    @pytest.mark.asyncio
    async def test_sort_data_tool(self, registry):
        """Test data sorting"""
        tool = registry.get_tool('sort_data')
        assert tool is not None

        test_data = [
            {'name': 'Charlie', 'score': 85},
            {'name': 'Alice', 'score': 95},
            {'name': 'Bob', 'score': 90}
        ]

        result = await tool.execute(
            data=test_data,
            sort_by='score',
            descending=True
        )

        assert result.success is True
        assert result.output['sorted_data'][0]['name'] == 'Alice'


class TestSearchAnalysisTools:
    """Test search and analysis tools extensions"""

    @pytest.mark.asyncio
    async def test_find_todos_tool(self, registry, temp_dir):
        """Test TODO finding"""
        tool = registry.get_tool('find_todos')
        assert tool is not None

        # Create test file with TODOs
        test_file = temp_dir / "test.py"
        test_file.write_text("# TODO: Implement this\ndef foo():\n    pass  # FIXME: Fix later")

        result = await tool.execute(
            directory_path=str(temp_dir),
            extensions=['.py']
        )

        assert result.success is True
        assert result.output['total_found'] >= 2

    @pytest.mark.asyncio
    async def test_count_lines_tool(self, registry, temp_dir):
        """Test line counting"""
        tool = registry.get_tool('count_lines')
        assert tool is not None

        # Create test files
        (temp_dir / "test.py").write_text("# Comment\nprint('hello')\n\n")
        (temp_dir / "test.js").write_text("// Comment\nconsole.log('hello');\n")

        result = await tool.execute(directory_path=str(temp_dir))

        assert result.success is True
        assert '.py' in result.output['by_extension']


class TestCodeGenerationTools:
    """Test code generation and modification tools"""

    @pytest.mark.asyncio
    async def test_code_gen_tools_registered(self, registry):
        """Test that code generation tools are registered"""
        assert registry.get_tool('generate_function') is not None
        assert registry.get_tool('refactor_code') is not None
        assert registry.get_tool('add_docstring') is not None
        assert registry.get_tool('add_type_hints') is not None
        assert registry.get_tool('format_code') is not None


class TestTestingValidationTools:
    """Test testing and validation tools"""

    @pytest.mark.asyncio
    async def test_check_syntax_tool(self, registry, temp_dir):
        """Test Python syntax checking"""
        tool = registry.get_tool('check_syntax')
        assert tool is not None

        # Valid Python
        valid_file = temp_dir / "valid.py"
        valid_file.write_text("def foo():\n    return 42")

        result = await tool.execute(file_path=str(valid_file))
        assert result.success is True
        assert result.output['valid'] is True

    @pytest.mark.asyncio
    async def test_validate_json_tool(self, registry):
        """Test JSON validation"""
        tool = registry.get_tool('validate_json')
        assert tool is not None

        valid_json = '{"key": "value", "number": 123}'
        result = await tool.execute(json_data=valid_json)

        assert result.success is True
        assert result.output['valid'] is True


class TestDocumentationTools:
    """Test documentation tools"""

    @pytest.mark.asyncio
    async def test_documentation_tools_registered(self, registry):
        """Test that documentation tools are registered"""
        assert registry.get_tool('generate_readme') is not None
        assert registry.get_tool('generate_api_docs') is not None
        assert registry.get_tool('extract_docstrings') is not None
        assert registry.get_tool('generate_changelog') is not None


class TestSystemManagementTools:
    """Test system management tools"""

    @pytest.mark.asyncio
    async def test_get_environment_variable_tool(self, registry):
        """Test environment variable retrieval"""
        tool = registry.get_tool('get_environment_variable')
        assert tool is not None

        # Test with PATH (should always exist)
        result = await tool.execute(key='PATH')
        assert result.success is True
        assert result.output['exists'] is True

    @pytest.mark.asyncio
    async def test_check_dependencies_tool_registered(self, registry):
        """Test that dependency checking tool is registered"""
        tool = registry.get_tool('check_dependencies')
        assert tool is not None


class TestSecurityTools:
    """Test security and encryption tools"""

    @pytest.mark.asyncio
    async def test_generate_password_tool(self, registry):
        """Test password generation"""
        tool = registry.get_tool('generate_password')
        assert tool is not None

        result = await tool.execute(
            length=16,
            include_symbols=True,
            include_numbers=True
        )

        assert result.success is True
        assert len(result.output['password']) == 16

    @pytest.mark.asyncio
    async def test_hash_data_tool(self, registry):
        """Test data hashing"""
        tool = registry.get_tool('hash_data')
        assert tool is not None

        result = await tool.execute(
            data='test data',
            algorithm='sha256'
        )

        assert result.success is True
        assert len(result.output['hash']) == 64

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_file(self, registry, temp_dir):
        """Test file encryption and decryption"""
        encrypt_tool = registry.get_tool('encrypt_file')
        decrypt_tool = registry.get_tool('decrypt_file')

        assert encrypt_tool is not None
        assert decrypt_tool is not None

        # Create test file
        original = temp_dir / "original.txt"
        original.write_text("secret data")
        encrypted = temp_dir / "encrypted.bin"
        decrypted = temp_dir / "decrypted.txt"

        # Encrypt
        encrypt_result = await encrypt_tool.execute(
            input_file=str(original),
            output_file=str(encrypted),
            password='test_password_123'
        )

        # Skip if cryptography library not installed
        if not encrypt_result.success and 'cryptography library not installed' in str(encrypt_result.error):
            pytest.skip("cryptography library not installed")

        assert encrypt_result.success is True

        # Decrypt
        decrypt_result = await decrypt_tool.execute(
            input_file=str(encrypted),
            output_file=str(decrypted),
            password='test_password_123'
        )
        assert decrypt_result.success is True
        assert decrypted.read_text() == "secret data"

    # ========================================================================
    # Active Defense & Threat Intelligence Tools Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_active_defense_tools_registered(self, registry):
        """Test that all active defense tools are registered"""
        assert registry.get_tool('check_ip_threat_intelligence') is not None
        assert registry.get_tool('block_ip_address') is not None
        assert registry.get_tool('unblock_ip_address') is not None
        assert registry.get_tool('get_active_blocks') is not None
        assert registry.get_tool('create_waf_rule') is not None
        assert registry.get_tool('apply_rate_limit') is not None
        assert registry.get_tool('block_country') is not None
        assert registry.get_tool('get_security_metrics') is not None
        assert registry.get_tool('get_block_history') is not None
        assert registry.get_tool('add_internal_threat') is not None
        assert registry.get_tool('sanitize_input') is not None

    @pytest.mark.asyncio
    async def test_check_ip_threat_intelligence_tool(self, registry):
        """Test threat intelligence lookup (mock test - requires config)"""
        tool = registry.get_tool('check_ip_threat_intelligence')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY

        # This will likely fail without active_defense_config.json, but we test the tool exists
        # and has proper structure
        assert hasattr(tool, 'execute')
        assert tool.name == 'check_ip_threat_intelligence'
        assert tool.description is not None

    @pytest.mark.asyncio
    async def test_sanitize_input_tool(self, registry):
        """Test input sanitization"""
        tool = registry.get_tool('sanitize_input')
        assert tool is not None

        # Test XSS sanitization
        malicious_input = '<script>alert("xss")</script>Hello'
        result = await tool.execute(
            input_data=malicious_input,
            sanitization_type='html'
        )

        assert result.success is True
        assert result.output['is_sanitized'] is True
        assert '<script>' not in result.output['sanitized']
        assert 'script tags' in result.output['removed_patterns'] or 'HTML special characters' in result.output['removed_patterns']

    @pytest.mark.asyncio
    async def test_sanitize_sql_injection(self, registry):
        """Test SQL injection sanitization"""
        tool = registry.get_tool('sanitize_input')
        assert tool is not None

        malicious_sql = "'; DROP TABLE users; --"
        result = await tool.execute(
            input_data=malicious_sql,
            sanitization_type='sql'
        )

        assert result.success is True
        assert result.output['is_sanitized'] is True
        assert 'DROP' not in result.output['sanitized']

    @pytest.mark.asyncio
    async def test_sanitize_shell_injection(self, registry):
        """Test shell injection sanitization"""
        tool = registry.get_tool('sanitize_input')
        assert tool is not None

        malicious_shell = "test; rm -rf /"
        result = await tool.execute(
            input_data=malicious_shell,
            sanitization_type='shell'
        )

        assert result.success is True
        assert result.output['is_sanitized'] is True
        assert ';' not in result.output['sanitized']
        assert 'shell metacharacters' in result.output['removed_patterns']

    @pytest.mark.asyncio
    async def test_sanitize_all_types(self, registry):
        """Test combined sanitization"""
        tool = registry.get_tool('sanitize_input')
        assert tool is not None

        malicious_input = '<script>alert(1)</script>; DROP TABLE users; `rm -rf /`'
        result = await tool.execute(
            input_data=malicious_input,
            sanitization_type='all'
        )

        assert result.success is True
        assert result.output['is_sanitized'] is True
        assert len(result.output['removed_patterns']) > 0

    @pytest.mark.asyncio
    async def test_scan_secrets_tool(self, registry, temp_dir):
        """Test secret scanning in code"""
        tool = registry.get_tool('scan_secrets')
        assert tool is not None

        # Create test file with fake secrets
        test_file = temp_dir / "config.py"
        test_file.write_text('''
# Configuration file
API_KEY = "sk-1234567890abcdefghijklmnopqrstuvwxyz1234567890"
DATABASE_PASSWORD = "super_secret_password_123"
github_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz12345"
        ''')

        result = await tool.execute(
            directory_path=str(temp_dir),
            extensions=['.py']
        )

        assert result.success is True
        assert result.output['total_findings'] >= 2  # Should find API_KEY and PASSWORD
        assert result.output['high_severity'] >= 2

    @pytest.mark.asyncio
    async def test_block_ip_tool_structure(self, registry):
        """Test block IP tool structure (without actual blocking)"""
        tool = registry.get_tool('block_ip_address')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY
        assert tool.safety_level.value == 'dangerous'

        # Verify parameters
        param_names = {p.name for p in tool.parameters}
        assert 'ip_address' in param_names
        assert 'reason' in param_names
        assert 'attack_type' in param_names
        assert 'force_block' in param_names

    @pytest.mark.asyncio
    async def test_unblock_ip_tool_structure(self, registry):
        """Test unblock IP tool structure"""
        tool = registry.get_tool('unblock_ip_address')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY

        param_names = {p.name for p in tool.parameters}
        assert 'ip_address' in param_names

    @pytest.mark.asyncio
    async def test_get_active_blocks_tool_structure(self, registry):
        """Test get active blocks tool structure"""
        tool = registry.get_tool('get_active_blocks')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY
        assert len(tool.parameters) == 0  # No parameters required

    @pytest.mark.asyncio
    async def test_create_waf_rule_tool_structure(self, registry):
        """Test create WAF rule tool structure"""
        tool = registry.get_tool('create_waf_rule')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY
        assert tool.safety_level.value == 'dangerous'

        param_names = {p.name for p in tool.parameters}
        assert 'expression' in param_names
        assert 'description' in param_names
        assert 'action' in param_names
        assert 'priority' in param_names

    @pytest.mark.asyncio
    async def test_apply_rate_limit_tool_structure(self, registry):
        """Test apply rate limit tool structure"""
        tool = registry.get_tool('apply_rate_limit')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY

        param_names = {p.name for p in tool.parameters}
        assert 'ip_address' in param_names
        assert 'requests_per_minute' in param_names

    @pytest.mark.asyncio
    async def test_block_country_tool_structure(self, registry):
        """Test block country tool structure"""
        tool = registry.get_tool('block_country')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY
        assert tool.safety_level.value == 'dangerous'

        param_names = {p.name for p in tool.parameters}
        assert 'country_code' in param_names
        assert 'reason' in param_names

    @pytest.mark.asyncio
    async def test_get_security_metrics_tool_structure(self, registry):
        """Test get security metrics tool structure"""
        tool = registry.get_tool('get_security_metrics')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY
        assert len(tool.parameters) == 0

    @pytest.mark.asyncio
    async def test_get_block_history_tool_structure(self, registry):
        """Test get block history tool structure"""
        tool = registry.get_tool('get_block_history')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY

        param_names = {p.name for p in tool.parameters}
        assert 'ip_address' in param_names

    @pytest.mark.asyncio
    async def test_add_internal_threat_tool_structure(self, registry):
        """Test add internal threat tool structure"""
        tool = registry.get_tool('add_internal_threat')
        assert tool is not None
        assert tool.category == ToolCategory.SECURITY

        param_names = {p.name for p in tool.parameters}
        assert 'ip_address' in param_names
        assert 'threat_types' in param_names
        assert 'reputation_score' in param_names
        assert 'evidence' in param_names


class TestToolUsageTracking:
    """Test tool usage tracking"""

    @pytest.mark.asyncio
    async def test_usage_stats(self, registry, temp_dir):
        """Test that tool usage is tracked"""
        # Execute a tool
        tool = registry.get_tool('get_file_info')
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        await tool.execute(file_path=str(test_file))

        # Check stats
        stats = registry.get_usage_stats()
        assert stats['total_tools'] > 0
        assert 'by_category' in stats


class TestToolParameterValidation:
    """Test tool parameter validation"""

    @pytest.mark.asyncio
    async def test_missing_required_parameter(self, registry):
        """Test that missing required parameters are caught"""
        tool = registry.get_tool('copy_file')

        result = await registry.execute_tool(
            'copy_file',
            {'source_path': '/tmp/test'}  # Missing destination_path
        )

        assert result.success is False
        assert 'required parameter' in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_enum_value(self, registry):
        """Test that invalid enum values are caught"""
        tool = registry.get_tool('hash_data')

        result = await registry.execute_tool(
            'hash_data',
            {
                'data': 'test',
                'algorithm': 'invalid_algorithm'
            }
        )

        assert result.success is False
        assert 'must be one of' in result.error.lower()


def test_print_tool_summary():
    """Print summary of all registered tools"""
    registry = get_tool_registry()

    print(f"\n{'='*60}")
    print(f"TORIN AI TOOL REGISTRY SUMMARY")
    print(f"{'='*60}\n")

    print(f"Total Tools Registered: {len(registry.tools)}\n")

    by_category = {}
    for tool in registry.tools.values():
        cat = tool.category.value
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(tool.name)

    for category in sorted(by_category.keys()):
        tools = sorted(by_category[category])
        print(f"{category.upper()}: ({len(tools)} tools)")
        for tool_name in tools:
            print(f"  - {tool_name}")
        print()


if __name__ == "__main__":
    # Run summary
    test_print_tool_summary()

    # Run tests
    print("\nRun tests with: python3 -m pytest tests/test_comprehensive_tools.py -v")
