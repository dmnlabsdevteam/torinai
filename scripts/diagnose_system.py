#!/usr/bin/env python3
"""
Comprehensive System Diagnostics - Run Without Restart

Tests:
1. LLM inference (text generation, tool calling, reasoning)
2. Task queue behavior
3. Tool execution
4. Memory system
5. Database connectivity
6. Component health

Usage:
    python scripts/diagnose_system.py
    python scripts/diagnose_system.py --quick  # Skip slow tests
    python scripts/diagnose_system.py --llm-only  # Only test LLM
"""

import asyncio
import sys
import time
import json
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

class SystemDiagnostics:
    """Comprehensive system diagnostics without restart"""
    
    def __init__(self):
        self.results = {}
        self.start_time = None
        
    async def run_all_tests(self, quick=False, llm_only=False):
        """Run all diagnostic tests"""
        self.start_time = time.time()
        
        print("=" * 80)
        print("TORIN SYSTEM DIAGNOSTICS")
        print("=" * 80)
        print(f"Started: {datetime.now().isoformat()}")
        print()
        
        if llm_only:
            await self.test_llm_system()
        else:
            # Test each component
            await self.test_database()
            await self.test_llm_system()
            await self.test_tool_calling()
            
            if not quick:
                await self.test_task_execution()
                await self.test_memory_system()
                await self.test_queue_behavior()
        
        # Generate report
        self._print_summary()
        
        return self.results
    
    async def test_database(self):
        """Test database connectivity and queries"""
        print("\n" + "─" * 80)
        print("TEST 1: DATABASE CONNECTIVITY")
        print("─" * 80)
        
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            
            # Test basic query
            start = time.time()
            result = await db.query("SELECT 1 as test")
            duration = time.time() - start
            
            self.results['database'] = {
                'status': 'PASS',
                'connected': True,
                'query_time': f"{duration*1000:.2f}ms",
                'result': result
            }
            
            print(f"✓ Database connected")
            print(f"✓ Query executed in {duration*1000:.2f}ms")
            print(f"✓ Result: {result}")
            
            # Test table access
            tables_result = await db.query("""
                SELECT schemaname, tablename 
                FROM pg_tables 
                WHERE schemaname IN ('unified', 'memory_hot', 'memory_cold')
                LIMIT 5
            """)
            print(f"✓ Found {len(tables_result) if tables_result else 0} tables")
            
        except Exception as e:
            self.results['database'] = {
                'status': 'FAIL',
                'error': str(e)
            }
            print(f"✗ Database test failed: {e}")
    
    async def test_llm_system(self):
        """Test LLM inference end-to-end"""
        print("\n" + "─" * 80)
        print("TEST 2: LLM INFERENCE")
        print("─" * 80)
        
        try:
            from core.services.unified_llm import get_unified_llm
            llm = get_unified_llm()
            
            # Test 1: Simple text generation
            print("\n[TEST 2.1] Simple text generation...")
            start = time.time()
            response = await llm.generate(
                "Reply with exactly: WORKING",
                max_tokens=10,
                temperature=0.0
            )
            duration = time.time() - start
            
            text_result = {
                'response': response,
                'duration': f"{duration:.2f}s",
                'tokens_per_sec': f"{10/duration:.1f}" if duration > 0 else "N/A",
                'contains_working': 'WORKING' in response.upper()
            }
            
            print(f"✓ Response: {response[:100]}")
            print(f"✓ Duration: {duration:.2f}s")
            print(f"✓ Speed: {10/duration:.1f} tok/s")
            
            # Test 2: Tool calling
            print("\n[TEST 2.2] Tool calling...")
            messages = [
                {"role": "system", "content": "You are a helpful assistant. Use tools to answer."},
                {"role": "user", "content": "Use the test_tool to say hello"}
            ]
            
            tools = [{
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "A test tool that returns a greeting",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "Message to return"}
                        },
                        "required": ["message"]
                    }
                }
            }]
            
            start = time.time()
            tool_response = await llm.generate_with_messages(
                messages=messages,
                tools=tools,
                max_tokens=100,
                temperature=0.0
            )
            duration = time.time() - start
            
            # Check if tool was called
            tool_called = False
            tool_name = None
            tool_args = None
            
            if tool_response.get('choices'):
                message = tool_response['choices'][0].get('message', {})
                tool_calls = message.get('tool_calls', [])
                if tool_calls:
                    tool_called = True
                    tool_name = tool_calls[0].get('function', {}).get('name')
                    tool_args = tool_calls[0].get('function', {}).get('arguments')
            
            tool_result = {
                'tool_called': tool_called,
                'tool_name': tool_name,
                'tool_args': tool_args,
                'duration': f"{duration:.2f}s",
                'raw_response': tool_response
            }
            
            if tool_called:
                print(f"✓ Tool called: {tool_name}")
                print(f"✓ Arguments: {tool_args}")
            else:
                print(f"✗ Tool NOT called")
                print(f"  Response: {tool_response}")
            
            # Test 3: Multi-turn conversation
            print("\n[TEST 2.3] Multi-turn conversation...")
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is 2+2?"},
            ]
            
            start = time.time()
            conv_response = await llm.generate_with_messages(
                messages=messages,
                max_tokens=50,
                temperature=0.0
            )
            duration = time.time() - start
            
            answer = ""
            if conv_response.get('choices'):
                answer = conv_response['choices'][0].get('message', {}).get('content', '')
            
            conv_result = {
                'answer': answer,
                'contains_four': '4' in answer,
                'duration': f"{duration:.2f}s"
            }
            
            print(f"✓ Answer: {answer[:100]}")
            print(f"✓ Correct: {'4' in answer}")
            
            self.results['llm'] = {
                'status': 'PASS' if (text_result['contains_working'] and tool_called) else 'PARTIAL',
                'text_generation': text_result,
                'tool_calling': tool_result,
                'conversation': conv_result
            }
            
        except Exception as e:
            self.results['llm'] = {
                'status': 'FAIL',
                'error': str(e),
                'traceback': __import__('traceback').format_exc()
            }
            print(f"✗ LLM test failed: {e}")
    
    async def test_tool_calling(self):
        """Test actual tool execution"""
        print("\n" + "─" * 80)
        print("TEST 3: TOOL EXECUTION")
        print("─" * 80)
        
        try:
            import importlib

            ReadFileTool = None
            for module_path in (
                "core.tools.file_tools",
                "core.tools.read_file_tool",
                "core.tools.file_tool",
            ):
                try:
                    module = importlib.import_module(module_path)
                    ReadFileTool = getattr(module, "ReadFileTool", None)
                    if ReadFileTool is not None:
                        break
                except ModuleNotFoundError:
                    continue

            if ReadFileTool is None:
                raise ImportError(
                    "Could not resolve ReadFileTool from expected modules: "
                    "core.tools.file_tools, core.tools.read_file_tool, core.tools.file_tool"
                )
            
            # Test file read tool
            tool = ReadFileTool()
            
            # Create test file
            test_file = Path("/tmp/torin_test.txt")
            test_file.write_text("DIAGNOSTIC_TEST_CONTENT")
            
            start = time.time()
            result = await tool.execute({
                'file_path': str(test_file),
                'start_line': 1,
                'end_line': 1
            })
            duration = time.time() - start
            
            success = result.get('success', False)
            content = result.get('content', '')
            
            self.results['tools'] = {
                'status': 'PASS' if success else 'FAIL',
                'execution_time': f"{duration*1000:.2f}ms",
                'result': result
            }
            
            print(f"✓ Tool executed in {duration*1000:.2f}ms")
            print(f"✓ Success: {success}")
            print(f"✓ Content match: {'DIAGNOSTIC_TEST_CONTENT' in content}")
            
            # Cleanup
            test_file.unlink()
            
        except Exception as e:
            self.results['tools'] = {
                'status': 'FAIL',
                'error': str(e)
            }
            print(f"✗ Tool execution failed: {e}")
    
    async def test_task_execution(self):
        """Test task queue and execution"""
        print("\n" + "─" * 80)
        print("TEST 4: TASK EXECUTION")
        print("─" * 80)
        
        try:
            from core.agents.autonomous.shared_types import Task, TaskType, TaskSource, Priority
            from core.agents.autonomous.task_queue import TaskQueue
            
            queue = TaskQueue()
            
            # Create test task
            test_task = Task(
                id="diagnostic_test_task",
                type=TaskType.ANALYSIS,
                description="Diagnostic test task: Analyze the number 42",
                priority=Priority.MEDIUM,
                source=TaskSource.AUTONOMOUS,
                created_by="diagnostics"
            )
            
            # Add to queue
            start = time.time()
            added = await queue.add_task(test_task, priority=Priority.MEDIUM)
            add_duration = time.time() - start
            
            # Get next task
            next_task = await queue.get_next_task()
            
            self.results['task_queue'] = {
                'status': 'PASS' if added and next_task else 'FAIL',
                'task_added': added,
                'task_retrieved': next_task is not None,
                'queue_size': len(queue.tasks_by_id),
                'add_time': f"{add_duration*1000:.2f}ms"
            }
            
            print(f"✓ Task added: {added}")
            print(f"✓ Task retrieved: {next_task is not None}")
            print(f"✓ Queue size: {len(queue.tasks_by_id)}")
            
        except Exception as e:
            self.results['task_queue'] = {
                'status': 'FAIL',
                'error': str(e)
            }
            print(f"✗ Task queue test failed: {e}")
    
    async def test_memory_system(self):
        """Test memory storage and retrieval"""
        print("\n" + "─" * 80)
        print("TEST 5: MEMORY SYSTEM")
        print("─" * 80)
        
        try:
            from core.agents.memory_agent import MemoryAgent
            
            memory = MemoryAgent()
            await memory.initialize()
            
            # Store test memory
            test_content = f"Diagnostic test memory - {datetime.now().isoformat()}"
            
            start = time.time()
            stored = await memory.store_memory(
                content=test_content,
                tags=['diagnostic', 'test'],
                importance=0.5
            )
            store_duration = time.time() - start
            
            # Search for it
            start = time.time()
            results = await memory.search_memories(
                query="diagnostic test",
                limit=5
            )
            search_duration = time.time() - start
            
            found = any(test_content in str(r) for r in results)
            
            self.results['memory'] = {
                'status': 'PASS' if stored and found else 'PARTIAL',
                'stored': stored,
                'found': found,
                'store_time': f"{store_duration*1000:.2f}ms",
                'search_time': f"{search_duration*1000:.2f}ms",
                'results_count': len(results)
            }
            
            print(f"✓ Memory stored in {store_duration*1000:.2f}ms")
            print(f"✓ Search completed in {search_duration*1000:.2f}ms")
            print(f"✓ Found: {found}")
            
        except Exception as e:
            self.results['memory'] = {
                'status': 'FAIL',
                'error': str(e)
            }
            print(f"✗ Memory test failed: {e}")
    
    async def test_queue_behavior(self):
        """Test queue priority and ordering"""
        print("\n" + "─" * 80)
        print("TEST 6: QUEUE PRIORITY BEHAVIOR")
        print("─" * 80)
        
        try:
            from core.agents.autonomous.shared_types import Task, TaskType, TaskSource, Priority
            from core.agents.autonomous.task_queue import TaskQueue
            
            queue = TaskQueue()
            
            # Add tasks with different priorities
            tasks = [
                Task(id="low_priority", type=TaskType.ANALYSIS, description="Low priority task", 
                     priority=Priority.LOW, source=TaskSource.AUTONOMOUS, created_by="test"),
                Task(id="high_priority", type=TaskType.ANALYSIS, description="High priority task",
                     priority=Priority.HIGH, source=TaskSource.AUTONOMOUS, created_by="test"),
                Task(id="medium_priority", type=TaskType.ANALYSIS, description="Medium priority task",
                     priority=Priority.MEDIUM, source=TaskSource.AUTONOMOUS, created_by="test"),
            ]
            
            # Add in random order
            for task in tasks:
                await queue.add_task(task, priority=task.priority)
            
            # Get tasks in order
            retrieved_order = []
            for _ in range(3):
                task = await queue.get_next_task()
                if task:
                    retrieved_order.append(task.id)
            
            # Expected order: HIGH -> MEDIUM -> LOW
            correct_order = retrieved_order == ["high_priority", "medium_priority", "low_priority"]
            
            self.results['queue_priority'] = {
                'status': 'PASS' if correct_order else 'FAIL',
                'retrieved_order': retrieved_order,
                'expected_order': ["high_priority", "medium_priority", "low_priority"],
                'correct': correct_order
            }
            
            print(f"✓ Retrieved order: {retrieved_order}")
            print(f"✓ Correct priority ordering: {correct_order}")
            
        except Exception as e:
            self.results['queue_priority'] = {
                'status': 'FAIL',
                'error': str(e)
            }
            print(f"✗ Queue priority test failed: {e}")
    
    def _print_summary(self):
        """Print diagnostic summary"""
        print("\n" + "=" * 80)
        print("DIAGNOSTIC SUMMARY")
        print("=" * 80)
        
        total_duration = time.time() - self.start_time
        
        # Count results
        passed = sum(1 for r in self.results.values() if r.get('status') == 'PASS')
        failed = sum(1 for r in self.results.values() if r.get('status') == 'FAIL')
        partial = sum(1 for r in self.results.values() if r.get('status') == 'PARTIAL')
        
        print(f"\nTotal Duration: {total_duration:.2f}s")
        print(f"Tests Passed: {passed}")
        print(f"Tests Failed: {failed}")
        print(f"Partial Pass: {partial}")
        
        print("\nDetailed Results:")
        for test_name, result in self.results.items():
            status = result.get('status', 'UNKNOWN')
            icon = '✓' if status == 'PASS' else ('⚠' if status == 'PARTIAL' else '✗')
            print(f"  {icon} {test_name.upper()}: {status}")
            
            if result.get('error'):
                print(f"    Error: {result['error']}")
        
        # Save detailed results
        output_file = Path(__file__).parent.parent / "logs" / f"diagnostics_{int(time.time())}.json"
        output_file.parent.mkdir(exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'duration': total_duration,
                'summary': {
                    'passed': passed,
                    'failed': failed,
                    'partial': partial
                },
                'results': self.results
            }, f, indent=2, default=str)
        
        print(f"\n✓ Detailed results saved to: {output_file}")
        print("=" * 80)

async def main():
    """Run diagnostics"""
    import argparse
    
    parser = argparse.ArgumentParser(description='TorinAI System Diagnostics')
    parser.add_argument('--quick', action='store_true', help='Skip slow tests')
    parser.add_argument('--llm-only', action='store_true', help='Only test LLM system')
    args = parser.parse_args()
    
    diagnostics = SystemDiagnostics()
    results = await diagnostics.run_all_tests(quick=args.quick, llm_only=args.llm_only)
    
    # Exit code based on results
    failed = sum(1 for r in results.values() if r.get('status') == 'FAIL')
    sys.exit(1 if failed > 0 else 0)

if __name__ == "__main__":
    asyncio.run(main())
