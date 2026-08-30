#!/usr/bin/env python3
"""
Test Extrinsic Task System
==========================
Tests that the ExtrinsicTaskManager singleton loads tasks from JSON and executes them.

Usage:
    python3 tests/test_extrinsic_tasks.py
"""

import pytest

pytest.skip(
    "core.agents.autonomous.extrinsic_task_manager does not exist anywhere in the repository -- ExtrinsicTaskManager appears only in this file, so the module it tests was never present or was removed without the test.",
    allow_module_level=True,
)


import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / '.env.production')

from core.agents.autonomous.extrinsic_task_manager import ExtrinsicTaskManager
from core.agents.autonomous.task_queue import TaskQueue
from core.agents.autonomous.shared_types import TaskStatus


@pytest.mark.asyncio
async def test_extrinsic_task_loading():
    """Test that ExtrinsicTaskManager loads tasks from JSON file"""
    print("=" * 80)
    print("Testing Extrinsic Task System")
    print("=" * 80)
    print()

    # Pre-load LLM service ONCE to avoid reloading 32GB model
    print("Initializing LLM service (one-time load)...")
    print("  (This will take 2-5 minutes to load 32GB model into memory)")
    try:
        from core.services.unified_llm import get_llm_service
        llm = get_llm_service()
        if not llm.model_loaded:
            print("  Starting LLM initialization with 600 second timeout...")
            await asyncio.wait_for(llm.initialize(), timeout=600)
        print("✓ LLM service initialized and ready\n")
    except asyncio.TimeoutError:
        print("❌ LLM service initialization TIMED OUT after 600 seconds")
        print("  This suggests initialization is hanging on:")
        print("    - Model loading (check model file exists)")
        print("    - Database cleanup (check R2 credentials)")
        print("    - Request processor (check async task setup)\n")
        return False
    except Exception as e:
        print(f"⚠ LLM service initialization failed (some tools may fail): {e}\n")

    # Disable Slack notifications to prevent hanging
    print("Disabling Slack notifications for testing...")
    import os
    os.environ['SLACK_WEBHOOK_URL'] = ''  # Disable Slack
    print()

    # Test 1: Verify JSON file exists and has tasks
    print("Test 1: Checking extrinsic_tasks.json file...")
    task_file = project_root / "data" / "system" / "extrinsic_tasks.json"

    if not task_file.exists():
        print(f"❌ FAIL: Task file not found at {task_file}")
        return False

    with open(task_file, 'r') as f:
        task_data = json.load(f)

    tasks_in_file = task_data.get('tasks', [])
    enabled_tasks = [t for t in tasks_in_file if t.get('enabled', True)]

    print(f"✓ Found {len(tasks_in_file)} tasks in JSON file")
    print(f"✓ {len(enabled_tasks)} tasks are enabled")
    print()

    # Test 2: Initialize TaskQueue
    print("Test 2: Initializing TaskQueue...")
    task_queue = TaskQueue()
    print("✓ TaskQueue created")
    print()

    # Test 3: Initialize ExtrinsicTaskManager (first instance)
    print("Test 3: Initializing ExtrinsicTaskManager (first instance)...")
    manager1 = ExtrinsicTaskManager(
        task_queue=task_queue,
        executor_name="test_executor",
        task_file=task_file
    )

    print("Calling manager1.initialize() with 120 second timeout...")
    try:
        init_success = await asyncio.wait_for(manager1.initialize(), timeout=120)
    except asyncio.TimeoutError:
        print("❌ FAIL: ExtrinsicTaskManager initialization TIMED OUT after 120 seconds")
        print("This suggests the initialization is hanging on:")
        print("  - Slack notification (check webhook)")
        print("  - Database operation (check MySQL connection)")
        print("  - File watcher (check filesystem access)")
        return False

    if not init_success:
        print("❌ FAIL: ExtrinsicTaskManager initialization returned False")
        return False

    print("✓ ExtrinsicTaskManager initialized successfully")

    # Check tasks were loaded
    status = manager1.get_status()
    print(f"✓ Tasks loaded: {status['loaded_tasks']}")
    print(f"✓ Tasks created: {status['tasks_created']}")
    print(f"✓ Active: {status['active']}")
    print()

    # Test 4: Verify tasks were loaded
    print("Test 4: Verifying task loading...")
    if status['loaded_tasks'] == 0:
        print("❌ FAIL: No tasks were loaded from JSON file")
        return False

    if status['loaded_tasks'] != len(enabled_tasks):
        print(f"⚠ WARNING: Expected {len(enabled_tasks)} tasks but loaded {status['loaded_tasks']}")

    print(f"✓ Successfully loaded {status['loaded_tasks']} tasks")

    # List loaded tasks
    print("\nLoaded task IDs:")
    for task_id in sorted(manager1.loaded_task_ids):
        print(f"  - {task_id}")
    print()

    # Test 5: Verify singleton pattern
    print("Test 5: Testing singleton pattern...")
    # Create another instance with same parameters
    manager2 = ExtrinsicTaskManager(
        task_queue=task_queue,
        executor_name="test_executor",
        task_file=task_file
    )

    # Check if it's working as a singleton by comparing loaded_task_ids
    # (Note: Python doesn't enforce true singleton without __new__, but we verify behavior)
    print("✓ Second ExtrinsicTaskManager instance created")
    print(f"  - First instance loaded tasks: {len(manager1.loaded_task_ids)}")
    print(f"  - Second instance loaded tasks: {len(manager2.loaded_task_ids)}")
    print()

    # Test 6: Check task queue integration
    print("Test 6: Checking task queue integration...")
    queue_size = task_queue.get_queue_size()
    print(f"✓ Task queue size: {queue_size}")

    if queue_size == 0:
        print("⚠ WARNING: Task queue is empty (tasks may have been filtered or dependencies not met)")
    else:
        print(f"✓ {queue_size} tasks are queued for execution")
    print()

    # Test 7: Verify task metadata
    print("Test 7: Verifying task metadata...")
    sample_tasks = list(manager1.loaded_task_ids)[:3]  # Check first 3 tasks

    for task_id in sample_tasks:
        # Find task in JSON
        task_def = next((t for t in tasks_in_file if t.get('task_id') == task_id), None)
        if task_def:
            print(f"✓ Task '{task_id}':")
            print(f"  - Name: {task_def.get('task_name', 'N/A')}")
            print(f"  - Priority: {task_def.get('priority', 'N/A')}")
            print(f"  - Enabled: {task_def.get('enabled', True)}")
    print()

    # Test 8: Test task execution capability (without full execution)
    print("Test 8: Testing task execution setup...")

    # Verify LLM service is available
    if manager1.llm_service:
        print("✓ LLM service is connected to task manager")
    else:
        print("⚠ WARNING: LLM service not available (tasks may not execute)")

    # Verify tool registry is available
    if manager1.tool_registry:
        print("✓ Tool registry is connected to task manager")
    else:
        print("⚠ WARNING: Tool registry not available (tool execution may fail)")
    print()

    # Test 9: File watcher status
    print("Test 9: Checking file watcher...")
    if manager1.file_watcher_task and not manager1.file_watcher_task.done():
        print("✓ File watcher is active and monitoring for changes")
    else:
        print("⚠ WARNING: File watcher may not be running")
    print()

    # Shutdown
    print("Shutting down task manager...")
    await manager1.shutdown()
    if manager2.active:
        await manager2.shutdown()
    print("✓ Task managers shutdown complete")
    print()

    # Final summary
    print("=" * 80)
    print("EXTRINSIC TASK SYSTEM TEST RESULTS")
    print("=" * 80)
    print(f"✓ JSON file exists: {task_file}")
    print(f"✓ Tasks in file: {len(tasks_in_file)}")
    print(f"✓ Enabled tasks: {len(enabled_tasks)}")
    print(f"✓ Tasks loaded: {status['loaded_tasks']}")
    print(f"✓ LLM service: {'Connected' if manager1.llm_service else 'Not available'}")
    print(f"✓ Tool registry: {'Connected' if manager1.tool_registry else 'Not available'}")
    print(f"✓ File watcher: {'Active' if (manager1.file_watcher_task and not manager1.file_watcher_task.done()) else 'Inactive'}")
    print()

    if status['loaded_tasks'] > 0:
        print("✅ ALL TESTS PASSED - Extrinsic task system is working correctly!")
        return True
    else:
        print("❌ TESTS FAILED - No tasks were loaded")
        return False


async def main():
    """Main test runner"""
    try:
        success = await test_extrinsic_task_loading()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
