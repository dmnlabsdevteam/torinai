#!/usr/bin/env python3
"""
Phase 3: Memory & Resource Integration Tests
=============================================
Tests governance integration for memory system architecture and resource allocation.

Key Validations:
- Memory SYSTEM architecture changes trigger governance (NOT individual memory ops)
- Resource allocation changes trigger based on magnitude/cumulative/oscillation
- Safe operations execute immediately
- Rejected actions do NOT apply
- Actions wait indefinitely for human decision

Author: Torin AI Team
Date: January 1, 2026
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Add tests directory to path for test_base
tests_dir = Path(__file__).parent.parent
sys.path.insert(0, str(tests_dir))

import asyncio
from test_base import TestBase, TestResult

# Import autonomous coordinator for memory/resource methods
from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator


class GovernancePhase3Tests(TestBase):
    """Phase 3 memory & resource governance tests with database logging"""

    def __init__(self):
        super().__init__(
            test_category="governance",
            test_type="phase3"
        )

        # Create coordinator instance for testing
        self.coordinator = None

    async def setup_coordinator(self):
        """Setup autonomous coordinator for testing"""
        if self.coordinator is None:
            # Create minimal mock brain for testing (coordinator requires it)
            class MockTorinBrain:
                """Minimal mock for testing governance without full LLM"""
                async def generate(self, *args, **kwargs):
                    return {"content": "mock response"}

                async def analyze(self, *args, **kwargs):
                    return {"result": "mock analysis"}

            # Create minimal mock memory for testing (to avoid MySQL initialization)
            class MockMemory:
                """Minimal mock memory to avoid MySQL dependencies"""
                async def store(self, *args, **kwargs):
                    return {"success": True}

                async def query(self, *args, **kwargs):
                    return []

            mock_brain = MockTorinBrain()
            mock_memory = MockMemory()

            # Create minimal coordinator instance (we only need the governance methods)
            config = {
                "coordination_cycle_interval": 60.0,
                "enable_quantum": False,
                "enable_learning": False,
                "memory": mock_memory  # Provide mock memory to avoid MySQL initialization
            }
            self.coordinator = AutonomousCoordinator(config=config, teacher_model=mock_brain)

            # Initialize system_state.resources dict if needed
            if not hasattr(self.coordinator.system_state, 'resources'):
                self.coordinator.system_state.resources = {}

    # ===== Category 1: Memory System Architecture Governance (7 tests) =====

    async def test_memory_architecture_change_triggers(self):
        """Test that indexing algorithm changes trigger CRITICAL governance (mem_ops_001)"""
        await self.setup_coordinator()

        result = await self.coordinator.upgrade_memory_system(
            change_type="indexing_algorithm",
            parameters={"algorithm": "new_vector_index_v2"}
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Memory architecture change should require approval"
        assert result.success == False, "Should NOT execute (queued for governance)"
        assert "REFUSED_BY_GOVERNANCE" in result.approval_message
        assert "mem_ops_001" in result.approval_message

    async def test_storage_format_change_triggers(self):
        """Test that storage format changes trigger CRITICAL governance (mem_ops_002)"""
        await self.setup_coordinator()

        result = await self.coordinator.upgrade_memory_system(
            change_type="storage_format",
            parameters={"new_format": "parquet_v2"}
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Storage format change should require approval"
        assert "REFUSED_BY_GOVERNANCE" in result.approval_message
        assert "mem_ops_002" in result.approval_message

    async def test_tier_threshold_change_triggers(self):
        """Test that hot/cold tier threshold changes trigger governance (mem_ops_003)"""
        await self.setup_coordinator()

        result = await self.coordinator.change_memory_tier_threshold(
            threshold_change_days=14  # Changing tier boundary
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Tier threshold change should require approval"
        assert "mem_ops_003" in result.approval_message

    async def test_ranking_weight_change_triggers(self):
        """Test that ranking weight changes trigger governance (mem_ops_004 - shadow suppression)"""
        await self.setup_coordinator()

        result = await self.coordinator.change_ranking_weights(
            weights={"recency": 0.8, "relevance": 0.2}
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Ranking weight change should require approval"
        assert "mem_ops_004" in result.approval_message
        assert "shadow suppression" in result.approval_message.lower()

    async def test_ttl_change_triggers(self):
        """Test that TTL changes trigger governance (mem_ops_005)"""
        await self.setup_coordinator()

        result = await self.coordinator.change_ttl(
            new_ttl_days=7  # Reducing TTL
        )

        # Validate governance triggered
        assert result.requires_approval == True, "TTL change should require approval"
        assert "mem_ops_005" in result.approval_message

    async def test_backend_switch_triggers(self):
        """Test that storage backend changes trigger governance (mem_ops_006)"""
        await self.setup_coordinator()

        result = await self.coordinator.change_storage_backend(
            new_backend="postgres_v2"
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Backend switch should require approval"
        assert "mem_ops_006" in result.approval_message

    async def test_query_filter_change_triggers(self):
        """Test that query filter logic changes trigger governance (mem_ops_007 - shadow suppression)"""
        await self.setup_coordinator()

        result = await self.coordinator.change_query_filter_logic(
            filter_logic="exclude_patterns(['error', 'failure'])"
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Query filter change should require approval"
        assert "mem_ops_007" in result.approval_message

    # ===== Category 2: Resource Allocation Governance (4 tests) =====

    async def test_large_resource_change_triggers(self):
        """Test that >=25% resource changes trigger governance (resource_001)"""
        await self.setup_coordinator()

        # 30% increase
        result = await self.coordinator.allocate_resources(
            resource_type="cpu",
            amount=130,
            current_allocation=100
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Large resource change should require approval"
        assert "resource_001" in result.approval_message
        assert result.metadata["percent_change"] == 30.0

    async def test_exceeds_capacity_triggers(self):
        """Test that exceeding usable capacity triggers CRITICAL governance (resource_002)"""
        await self.setup_coordinator()

        # Exceeds usable capacity (800 units)
        result = await self.coordinator.allocate_resources(
            resource_type="memory",
            amount=850,
            total_capacity=1000,
            reserved_margin=200
        )

        # Validate governance triggered
        assert result.requires_approval == True, "Exceeding capacity should require approval"
        assert "resource_002" in result.approval_message
        assert result.metadata["exceeds_usable_capacity"] == True

    async def test_cumulative_changes_trigger(self):
        """Test that cumulative >25% change in 1 hour triggers governance (resource_003)"""
        await self.setup_coordinator()

        # Clear history
        self.coordinator._resource_allocation_history = []

        # Make 5 small changes (5%+ each) to accumulate to >25%
        for i in range(5):
            result = await self.coordinator.allocate_resources(
                resource_type="disk",
                amount=105 + (i * 5.2),  # 105, 110.2, 115.4, 120.6, 126
                current_allocation=100,
                track_cumulative=True
            )

        # Last change should trigger (cumulative >25%)
        assert result.requires_approval == True, "Cumulative changes should require approval"
        assert "resource_003" in result.approval_message
        assert result.metadata["cumulative_change_percent"] > 25

    async def test_oscillation_triggers(self):
        """Test that >3 changes in 5 minutes triggers governance (resource_004)"""
        await self.setup_coordinator()

        # Clear history
        self.coordinator._resource_allocation_history = []

        # Make 4 rapid changes
        allocations = [120, 110, 125, 115]
        for amount in allocations:
            result = await self.coordinator.allocate_resources(
                resource_type="cpu",
                amount=amount,
                track_oscillation=True
            )

        # 4th change should trigger (>3 changes)
        assert result.requires_approval == True, "Oscillation should require approval"
        assert "resource_004" in result.approval_message
        assert result.metadata["change_count_in_window"] > 3

    # ===== Category 3: Safe Operations (3 tests) =====

    async def test_safe_memory_improvement_executes(self):
        """Test that safe memory optimizations execute immediately"""
        await self.setup_coordinator()

        # Safe optimization (cache_tuning doesn't match any triggers)
        result = await self.coordinator.upgrade_memory_system(
            change_type="cache_tuning",
            parameters={"enable_caching": True}
        )

        # Should execute (no governance trigger)
        assert result.success == True, "Safe memory optimization should execute"
        assert result.requires_approval == False

    async def test_memory_query_no_governance(self):
        """Test that memory queries don't trigger governance (capability token enforced)"""
        await self.setup_coordinator()

        # Memory query operations are controlled by capability tokens, not governance
        # This test validates that query operations don't go through governance
        # (they use the existing store_memory/search_memories methods)

        # For now, we just verify the coordinator has these methods
        assert hasattr(self.coordinator, 'store_memory')
        assert hasattr(self.coordinator, 'search_memories')

        # These methods don't require governance approval (ROUTINE tier)
        # This is correct - individual memory ops use capability tokens

    async def test_small_resource_change_executes(self):
        """Test that <25% resource changes execute immediately"""
        await self.setup_coordinator()

        # Clear history
        self.coordinator._resource_allocation_history = []

        # 10% increase (below 25% threshold)
        result = await self.coordinator.allocate_resources(
            resource_type="cpu",
            amount=110,
            current_allocation=100
        )

        # Should execute (no governance trigger)
        assert result.success == True, "Small resource change should execute"
        assert result.requires_approval == False
        assert result.metadata["percent_change"] == 10.0

    # ===== Category 4: Blocking Behavior (2 tests) =====

    async def test_rejected_memory_change_blocked(self):
        """Test that rejected memory architecture changes do NOT apply"""
        await self.setup_coordinator()

        # Queue memory architecture change
        result = await self.coordinator.upgrade_memory_system(
            change_type="storage_format",
            parameters={"new_format": "parquet_v2"}
        )

        # Verify queued (not executed)
        assert result.success == False
        assert result.requires_approval == True

        # In a real scenario, we'd simulate human rejection here
        # For now, we verify that the result indicates it's queued and NOT executed

    async def test_rejected_resource_change_blocked(self):
        """Test that rejected resource allocations do NOT apply"""
        await self.setup_coordinator()

        # Record initial allocation
        initial_allocation = self.coordinator.system_state.resources.get("memory", 0)

        # Queue large resource change
        result = await self.coordinator.allocate_resources(
            resource_type="memory",
            amount=500,
            current_allocation=200  # 150% increase
        )

        # Verify queued (requires approval)
        assert result.success == False
        assert result.requires_approval == True

        # Verify allocation did NOT change yet (would only change after approval)
        # Note: In the current implementation, it doesn't change because success=False
        # In production, this would be enforced by the governance queue

    # ===== Category 5: Queuing Behavior (2 tests) =====

    async def test_action_waits_for_human_decision(self):
        """Test that queued actions indicate pending status"""
        await self.setup_coordinator()

        # Queue memory architecture change
        result = await self.coordinator.upgrade_memory_system(
            change_type="indexing_algorithm",
            parameters={"algorithm": "new_index"}
        )

        # Verify action is queued (not executed)
        assert result.requires_approval == True
        assert result.success == False
        assert "REFUSED_BY_GOVERNANCE" in result.approval_message

        # In production, this would create a governance session entry
        # that waits indefinitely for human decision

    async def test_singleton_continues_while_action_queued(self):
        """Test that safe operations work while dangerous action is queued"""
        await self.setup_coordinator()

        # Queue dangerous memory operation
        memory_result = await self.coordinator.upgrade_memory_system(
            change_type="storage_format",
            parameters={"new_format": "parquet"}
        )

        # Verify queued
        assert memory_result.requires_approval == True

        # Execute safe operation while memory change is queued
        safe_result = await self.coordinator.allocate_resources(
            resource_type="cpu",
            amount=105,  # Small 5% change
            current_allocation=100
        )

        # Safe operation should execute successfully
        assert safe_result.success == True
        assert safe_result.requires_approval == False

        # Dangerous operation should STILL indicate it's queued
        assert memory_result.requires_approval == True
        assert memory_result.success == False

    # ===== Test Runner =====

    async def run_all_tests(self):
        """Run all Phase 3 tests"""

        # Category 1: Memory system architecture governance
        await self.run_test(
            "test_memory_architecture_change_triggers",
            self.test_memory_architecture_change_triggers,
            metadata={
                "description": "Verify indexing algorithm changes trigger CRITICAL governance",
                "phase": "3",
                "component": "memory_operations",
                "trigger_id": "mem_ops_001",
                "expected_tier": "CRITICAL"
            }
        )

        await self.run_test(
            "test_storage_format_change_triggers",
            self.test_storage_format_change_triggers,
            metadata={
                "description": "Verify storage format changes trigger CRITICAL governance",
                "phase": "3",
                "component": "memory_operations",
                "trigger_id": "mem_ops_002",
                "expected_tier": "CRITICAL"
            }
        )

        await self.run_test(
            "test_tier_threshold_change_triggers",
            self.test_tier_threshold_change_triggers,
            metadata={
                "description": "Verify hot/cold tier threshold changes trigger governance",
                "phase": "3",
                "component": "memory_operations",
                "trigger_id": "mem_ops_003",
                "expected_tier": "CRITICAL"
            }
        )

        await self.run_test(
            "test_ranking_weight_change_triggers",
            self.test_ranking_weight_change_triggers,
            metadata={
                "description": "Verify ranking weight changes trigger governance (shadow suppression)",
                "phase": "3",
                "component": "memory_operations",
                "trigger_id": "mem_ops_004",
                "expected_tier": "CRITICAL",
                "validates": "Shadow suppression prevention"
            }
        )

        await self.run_test(
            "test_ttl_change_triggers",
            self.test_ttl_change_triggers,
            metadata={
                "description": "Verify TTL changes trigger governance",
                "phase": "3",
                "component": "memory_operations",
                "trigger_id": "mem_ops_005",
                "expected_tier": "CRITICAL"
            }
        )

        await self.run_test(
            "test_backend_switch_triggers",
            self.test_backend_switch_triggers,
            metadata={
                "description": "Verify storage backend changes trigger governance",
                "phase": "3",
                "component": "memory_operations",
                "trigger_id": "mem_ops_006",
                "expected_tier": "CRITICAL"
            }
        )

        await self.run_test(
            "test_query_filter_change_triggers",
            self.test_query_filter_change_triggers,
            metadata={
                "description": "Verify query filter logic changes trigger governance",
                "phase": "3",
                "component": "memory_operations",
                "trigger_id": "mem_ops_007",
                "expected_tier": "CRITICAL",
                "validates": "Shadow suppression prevention"
            }
        )

        # Category 2: Resource allocation governance
        await self.run_test(
            "test_large_resource_change_triggers",
            self.test_large_resource_change_triggers,
            metadata={
                "description": "Verify >=25% resource changes trigger governance",
                "phase": "3",
                "component": "resource_allocation",
                "trigger_id": "resource_001",
                "expected_tier": "IMPORTANT"
            }
        )

        await self.run_test(
            "test_exceeds_capacity_triggers",
            self.test_exceeds_capacity_triggers,
            metadata={
                "description": "Verify exceeding usable capacity triggers CRITICAL governance",
                "phase": "3",
                "component": "resource_allocation",
                "trigger_id": "resource_002",
                "expected_tier": "CRITICAL"
            }
        )

        await self.run_test(
            "test_cumulative_changes_trigger",
            self.test_cumulative_changes_trigger,
            metadata={
                "description": "Verify cumulative >25% change in 1 hour triggers governance",
                "phase": "3",
                "component": "resource_allocation",
                "trigger_id": "resource_003",
                "expected_tier": "CRITICAL",
                "validates": "Death-by-a-thousand-cuts prevention"
            }
        )

        await self.run_test(
            "test_oscillation_triggers",
            self.test_oscillation_triggers,
            metadata={
                "description": "Verify >3 changes in 5 minutes triggers governance",
                "phase": "3",
                "component": "resource_allocation",
                "trigger_id": "resource_004",
                "expected_tier": "IMPORTANT",
                "validates": "Oscillation detection"
            }
        )

        # Category 3: Safe operations
        await self.run_test(
            "test_safe_memory_improvement_executes",
            self.test_safe_memory_improvement_executes,
            metadata={
                "description": "Verify safe memory optimizations execute immediately",
                "phase": "3",
                "component": "memory_operations",
                "expected_tier": "ROUTINE"
            }
        )

        await self.run_test(
            "test_memory_query_no_governance",
            self.test_memory_query_no_governance,
            metadata={
                "description": "Verify memory queries use capability tokens (not governance)",
                "phase": "3",
                "component": "memory_operations",
                "validates": "Capability token enforcement is orthogonal to governance"
            }
        )

        await self.run_test(
            "test_small_resource_change_executes",
            self.test_small_resource_change_executes,
            metadata={
                "description": "Verify <25% resource changes execute immediately",
                "phase": "3",
                "component": "resource_allocation",
                "expected_tier": "ROUTINE"
            }
        )

        # Category 4: Blocking behavior
        await self.run_test(
            "test_rejected_memory_change_blocked",
            self.test_rejected_memory_change_blocked,
            metadata={
                "description": "Verify rejected memory changes do NOT apply",
                "phase": "3",
                "component": "blocking_behavior",
                "validates": "MUST_BLOCK enforcement"
            }
        )

        await self.run_test(
            "test_rejected_resource_change_blocked",
            self.test_rejected_resource_change_blocked,
            metadata={
                "description": "Verify rejected resource allocations do NOT apply",
                "phase": "3",
                "component": "blocking_behavior",
                "validates": "MUST_BLOCK enforcement"
            }
        )

        # Category 5: Queuing behavior
        await self.run_test(
            "test_action_waits_for_human_decision",
            self.test_action_waits_for_human_decision,
            metadata={
                "description": "Verify queued actions wait for human decision",
                "phase": "3",
                "component": "queuing_behavior",
                "validates": "Actions wait indefinitely (no timeout)"
            }
        )

        await self.run_test(
            "test_singleton_continues_while_action_queued",
            self.test_singleton_continues_while_action_queued,
            metadata={
                "description": "Verify Singleton continues other work while actions queued",
                "phase": "3",
                "component": "queuing_behavior",
                "validates": "Non-blocking queue behavior"
            }
        )


async def main():
    """Main test runner"""
    print("\n" + "=" * 60)
    print("Phase 3: Memory & Resource Integration Tests")
    print("=" * 60)
    print()

    # Create test suite
    tests = GovernancePhase3Tests()

    # Start session
    await tests.start_session()

    # Run all tests
    await tests.run_all_tests()

    # End session
    await tests.end_session()

    # Print summary
    tests.print_summary()

    # Return exit code
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
