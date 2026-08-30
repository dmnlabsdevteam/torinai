# Phase 3: Memory & Resource Integration - Testing Plan

**Phase**: 3 of 9
**Focus**: MEMORY_OPERATIONS and RESOURCE_ALLOCATION governance integration
**Target Files**:
- [core/agents/autonomous/autonomous_coordinator.py](../../core/agents/autonomous/autonomous_coordinator.py:808+) - Memory operations
- [core/memory/__init__.py](../../core/memory/__init__.py) - Memory system hooks
- [core/agents/autonomous/autonomous_coordinator.py](../../core/agents/autonomous/autonomous_coordinator.py:3406) - Resource allocation

---

## Overview

Phase 3 integrates governance triggers for **memory system architecture changes** and **resource allocation decisions**. This extends the governance system from tool execution (Phase 2) to system-level operational decisions.

### Critical Architecture Principles

#### Memory Operations Governance

**IMPORTANT**: Governance applies to **memory SYSTEM architecture**, NOT individual memory deletion/editing.

**Key Concept**:
- ✅ **Singleton CAN**: Improve memory system architecture (indexing, search, storage optimization)
- ❌ **Singleton CANNOT**: Delete or edit individual memories (requires MemoryAgent capability tokens)

**Examples of Governed Operations**:
- Changing indexing algorithms → Triggers `mem_ops_001` (CRITICAL)
- Switching storage backends → Triggers `mem_ops_006` (CRITICAL)
- Modifying ranking weights → Triggers `mem_ops_004` (CRITICAL - prevents shadow suppression)
- Changing TTL/privacy flags → Triggers `mem_ops_005` (CRITICAL - prevents indirect deletion)

**Non-Governed Operations** (handled by capability tokens):
- Storing new memories
- Querying/retrieving memories
- Individual memory deletion (requires MemoryAgent approval)

**Shadow Suppression Prevention**: Triggers prevent hiding memories via indirect manipulation (e.g., changing ranking weights to bury unwanted memories, modifying query filters to exclude content).

#### Resource Allocation Governance

**Philosophy**: Prevent resource exhaustion and instability via large changes or cumulative drift.

**Examples of Governed Operations**:
- Allocating >=25% resource change → Triggers `resource_001` (IMPORTANT)
- Exceeding usable capacity → Triggers `resource_002` (CRITICAL)
- Cumulative >25% change in 1 hour → Triggers `resource_003` (CRITICAL - prevents death-by-a-thousand-cuts)
- >3 changes in 5 minutes → Triggers `resource_004` (IMPORTANT - prevents oscillation)

---

## Current State Analysis

### Memory System Integration Points

**File**: `core/agents/autonomous/autonomous_coordinator.py` (line ~808+)

**Current Status**: ❓ UNKNOWN - Need to inspect

**Expected Methods**:
- `upgrade_memory_system(change_type, parameters)` - Architecture changes
- `change_memory_tier_threshold(threshold_change_days)` - Hot/cold tier management
- `change_storage_backend(new_backend)` - Backend migration
- `change_ranking_weights(weights)` - Ranking algorithm changes
- `change_ttl(new_ttl)` - Memory TTL changes
- `change_query_filter_logic(filter_logic)` - Query filter modifications

**Required Changes**:
- Add governance evaluation before ALL memory system operations
- Route to governance queue for CRITICAL operations
- Preserve capability token enforcement (orthogonal to governance)

### Memory Module Hooks

**File**: `core/memory/__init__.py`

**Current Status**: ❓ UNKNOWN - Need to inspect

**Expected Hooks**:
- Module-level functions that delegate to MemoryAgent with capability tokens
- No direct governance (governance happens at coordinator level)

### Resource Allocation Integration Point

**File**: `core/agents/autonomous/autonomous_coordinator.py` (line ~3406)

**Current Status**: ❓ UNKNOWN - Need to inspect

**Expected Method**:
- `allocate_resources(resource_type, amount, metadata)` - Resource allocation

**Required Changes**:
- Calculate percent change from current allocation
- Track cumulative changes in time windows (death-by-a-thousand-cuts detection)
- Detect oscillation patterns (change count in time window)
- Evaluate governance triggers before applying changes
- Queue for governance if triggers match

---

## Phase 3 Testing Requirements

### Test Suite Structure

**File to Create**: `tests/governance/test_phase3_memory_resource.py`

**Test Categories**:
1. Memory system architecture governance (7 triggers)
2. Resource allocation governance (4 triggers)
3. Safe memory operations (no triggers)
4. Safe resource operations (no triggers)
5. Blocking behavior validation
6. Queuing behavior validation

**Total Tests**: ~18 tests

---

## Detailed Test Specifications

### Category 1: Memory System Architecture Governance (7 tests)

#### Test 1.1: Memory System Architecture Change (mem_ops_001)
```python
async def test_memory_architecture_change_triggers():
    """Test that indexing algorithm changes trigger CRITICAL governance"""

    result = await coordinator.upgrade_memory_system(
        change_type="indexing_algorithm",
        parameters={"algorithm": "new_vector_index_v2"}
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert result.success == False
    assert "QUEUED_FOR_GOVERNANCE" in result.approval_message
    assert "mem_ops_001" in result.approval_message

    # Validate change did NOT apply (queued, not executed)
    current_algorithm = await coordinator.get_memory_config("indexing_algorithm")
    assert current_algorithm != "new_vector_index_v2"  # Should still be old algorithm
```

**Trigger**: `mem_ops_001`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK

---

#### Test 1.2: Storage Format Change (mem_ops_002)
```python
async def test_storage_format_change_triggers():
    """Test that storage format changes trigger CRITICAL governance"""

    result = await coordinator.upgrade_memory_system(
        change_type="storage_format",
        parameters={"new_format": "parquet_v2"}
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "QUEUED_FOR_GOVERNANCE" in result.approval_message
    assert "mem_ops_002" in result.approval_message

    # Validate requires rollback plan
    assert result.metadata.get("requires_rollback_plan") == True
```

**Trigger**: `mem_ops_002`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK

---

#### Test 1.3: Hot/Cold Tier Threshold Change (mem_ops_003)
```python
async def test_tier_threshold_change_triggers():
    """Test that hot/cold tier threshold changes trigger governance"""

    result = await coordinator.change_memory_tier_threshold(
        threshold_change_days=14  # Moving hot/cold boundary from 30 days to 14 days
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "mem_ops_003" in result.approval_message
```

**Trigger**: `mem_ops_003`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK

---

#### Test 1.4: Ranking Weight Changes (mem_ops_004)
```python
async def test_ranking_weight_change_triggers():
    """Test that ranking weight changes trigger governance (shadow suppression prevention)"""

    result = await coordinator.change_ranking_weights(
        weights={"recency": 0.8, "relevance": 0.2}  # Heavily weighting recency
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "mem_ops_004" in result.approval_message

    # Rationale check
    assert "shadow suppression" in result.approval_message.lower()
```

**Trigger**: `mem_ops_004`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK
**Rationale**: Prevents hiding memories via ranking manipulation

---

#### Test 1.5: Memory Visibility Changes (mem_ops_005)
```python
async def test_ttl_change_triggers():
    """Test that TTL changes trigger governance (indirect deletion prevention)"""

    result = await coordinator.change_ttl(
        new_ttl_days=7  # Reducing from default 90 days
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "mem_ops_005" in result.approval_message
```

**Trigger**: `mem_ops_005`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK

---

#### Test 1.6: Backend Storage Switch (mem_ops_006)
```python
async def test_backend_switch_triggers():
    """Test that storage backend changes trigger governance"""

    result = await coordinator.change_storage_backend(
        new_backend="postgres_v2"
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "mem_ops_006" in result.approval_message

    # Validate migration requirements
    assert result.metadata.get("requires_migration_dry_run") == True
```

**Trigger**: `mem_ops_006`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK

---

#### Test 1.7: Query Filter Logic Change (mem_ops_007)
```python
async def test_query_filter_change_triggers():
    """Test that query filter logic changes trigger governance (shadow suppression)"""

    result = await coordinator.change_query_filter_logic(
        filter_logic="exclude_patterns(['error', 'failure'])"
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "mem_ops_007" in result.approval_message
```

**Trigger**: `mem_ops_007`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK

---

### Category 2: Resource Allocation Governance (4 tests)

#### Test 2.1: Large Resource Change (resource_001)
```python
async def test_large_resource_change_triggers():
    """Test that >=25% resource changes trigger governance"""

    # Current allocation: 100 units
    # Requesting: 130 units (30% increase)
    result = await coordinator.allocate_resources(
        resource_type="cpu",
        amount=130,
        current_allocation=100
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "resource_001" in result.approval_message

    # Validate percent change calculation
    assert result.metadata["percent_change"] == 30.0
```

**Trigger**: `resource_001`
**Decision Tier**: IMPORTANT
**Enforcement**: MUST_BLOCK

---

#### Test 2.2: Exceeds Capacity (resource_002)
```python
async def test_exceeds_capacity_triggers():
    """Test that exceeding usable capacity triggers CRITICAL governance"""

    # Total capacity: 1000 units
    # Reserved margin: 200 units
    # Usable capacity: 800 units
    # Requesting: 850 units (exceeds usable capacity)
    result = await coordinator.allocate_resources(
        resource_type="memory",
        amount=850,
        total_capacity=1000,
        reserved_margin=200
    )

    # Validate governance triggered
    assert result.requires_approval == True
    assert "resource_002" in result.approval_message

    # Validate pre-governance validation
    assert result.metadata["validation_mode"] == "PRE_GOVERNANCE"
    assert result.metadata["exceeds_usable_capacity"] == True
```

**Trigger**: `resource_002`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK

---

#### Test 2.3: Cumulative Changes (resource_003)
```python
async def test_cumulative_changes_trigger():
    """Test that cumulative >25% change in 1 hour triggers governance"""

    # Simulate 5 small changes (5% each) in 30 minutes
    # Total cumulative change: 25%+

    for i in range(5):
        result = await coordinator.allocate_resources(
            resource_type="disk",
            amount=105 + (i * 5),  # 105, 110, 115, 120, 125
            current_allocation=100,
            track_cumulative=True
        )

    # Last change should trigger governance (cumulative >25%)
    assert result.requires_approval == True
    assert "resource_003" in result.approval_message

    # Validate cumulative tracking
    assert result.metadata["cumulative_change_percent"] > 25
    assert result.metadata["time_window_hours"] <= 1
```

**Trigger**: `resource_003`
**Decision Tier**: CRITICAL
**Enforcement**: MUST_BLOCK
**Rationale**: Prevents death-by-a-thousand-cuts resource exhaustion

---

#### Test 2.4: Oscillation Detection (resource_004)
```python
async def test_oscillation_triggers():
    """Test that >3 changes in 5 minutes triggers governance"""

    # Simulate rapid oscillating changes
    allocations = [100, 120, 110, 125, 115]  # 4 changes in rapid succession

    for amount in allocations:
        result = await coordinator.allocate_resources(
            resource_type="cpu",
            amount=amount,
            track_oscillation=True
        )

    # 4th change should trigger governance (>3 changes in window)
    assert result.requires_approval == True
    assert "resource_004" in result.approval_message

    # Validate oscillation detection
    assert result.metadata["change_count_in_window"] > 3
    assert result.metadata["cooldown_period_minutes"] == 10
```

**Trigger**: `resource_004`
**Decision Tier**: IMPORTANT
**Enforcement**: MUST_BLOCK

---

### Category 3: Safe Memory Operations (2 tests)

#### Test 3.1: Safe Architecture Improvement
```python
async def test_safe_memory_improvement_executes():
    """Test that safe memory optimizations execute immediately"""

    # Safe optimization: improving search performance (not changing ranking)
    result = await coordinator.upgrade_memory_system(
        change_type="search_optimization",
        parameters={"enable_caching": True}
    )

    # Should execute (no governance trigger)
    assert result.success == True
    assert result.requires_approval == False
```

**Expected**: No trigger, ROUTINE tier, executes immediately

---

#### Test 3.2: Memory Query (Capability Token)
```python
async def test_memory_query_no_governance():
    """Test that memory queries don't trigger governance (capability token enforced)"""

    # Querying memories is controlled by capability tokens, not governance
    result = await coordinator.query_memories(
        query="recent conversations",
        capability_token=valid_token
    )

    # Should execute (no governance, capability token validates)
    assert result.success == True
    assert result.requires_approval == False
```

**Expected**: No governance trigger (capability token enforcement is orthogonal)

---

### Category 4: Safe Resource Operations (1 test)

#### Test 4.1: Small Resource Change
```python
async def test_small_resource_change_executes():
    """Test that <25% resource changes execute immediately"""

    # 10% increase (below 25% threshold)
    result = await coordinator.allocate_resources(
        resource_type="cpu",
        amount=110,
        current_allocation=100
    )

    # Should execute (no governance trigger)
    assert result.success == True
    assert result.requires_approval == False
    assert result.metadata["percent_change"] == 10.0
```

**Expected**: No trigger, ROUTINE tier, executes immediately

---

### Category 5: Blocking Behavior Validation (2 tests)

#### Test 5.1: Rejected Memory Change Does NOT Apply
```python
async def test_rejected_memory_change_blocked():
    """Test that rejected memory architecture changes do NOT apply"""

    # Queue memory architecture change
    result = await coordinator.upgrade_memory_system(
        change_type="storage_format",
        parameters={"new_format": "parquet_v2"}
    )

    # Simulate human rejection
    governance_session = await get_governance_session(result.action_id)
    await governance_session.record_vote("human_1", False, "Too risky")
    decision = await governance_session.finalize()

    # Verify change did NOT apply
    current_format = await coordinator.get_memory_config("storage_format")
    assert current_format != "parquet_v2"

    # Verify rejection was logged
    assert decision.approved == False
```

**Validation**: Rejected actions MUST NOT execute

---

#### Test 5.2: Rejected Resource Change Does NOT Apply
```python
async def test_rejected_resource_change_blocked():
    """Test that rejected resource allocations do NOT apply"""

    # Queue large resource change
    result = await coordinator.allocate_resources(
        resource_type="memory",
        amount=500,
        current_allocation=200  # 150% increase
    )

    # Simulate human rejection
    governance_session = await get_governance_session(result.action_id)
    await governance_session.record_vote("human_1", False, "Resource spike")
    decision = await governance_session.finalize()

    # Verify allocation did NOT change
    current_allocation = await coordinator.get_resource_allocation("memory")
    assert current_allocation == 200  # Still original amount
```

**Validation**: Rejected actions MUST NOT execute

---

### Category 6: Queuing Behavior Validation (2 tests)

#### Test 6.1: Actions Wait Indefinitely for Decision
```python
async def test_action_waits_for_human_decision():
    """Test that queued actions wait indefinitely for human approval"""

    # Queue memory architecture change
    result = await coordinator.upgrade_memory_system(
        change_type="indexing_algorithm",
        parameters={"algorithm": "new_index"}
    )

    # Verify action is queued
    assert result.requires_approval == True
    assert result.status == "QUEUED_FOR_GOVERNANCE"

    # Simulate 24 hours passing (no timeout)
    await asyncio.sleep(0)  # Fast-forward in test

    # Action should STILL be queued (no timeout)
    action_status = await coordinator.get_action_status(result.action_id)
    assert action_status == "PENDING_APPROVAL"
```

**Validation**: Actions MUST wait indefinitely (no timeout)

---

#### Test 6.2: Singleton Continues with Other Tasks
```python
async def test_singleton_continues_while_action_queued():
    """Test that Singleton can execute other tasks while dangerous action queued"""

    # Queue dangerous memory operation
    memory_result = await coordinator.upgrade_memory_system(
        change_type="storage_format",
        parameters={"new_format": "parquet"}
    )

    # Verify queued
    assert memory_result.requires_approval == True

    # Execute safe operation while memory change is queued
    safe_result = await coordinator.query_memories(
        query="test",
        capability_token=valid_token
    )

    # Safe operation should execute successfully
    assert safe_result.success == True

    # Dangerous operation should STILL be queued
    status = await coordinator.get_action_status(memory_result.action_id)
    assert status == "PENDING_APPROVAL"
```

**Validation**: Singleton can execute other tasks while dangerous actions are queued

---

## Implementation Steps

### Step 1: Inspect Current Code
- Read `autonomous_coordinator.py` to find memory and resource methods
- Read `core/memory/__init__.py` to understand memory module structure
- Identify where governance hooks need to be added

### Step 2: Add Governance Integration
- Import `UnifiedGovernanceTriggerSystem` and `ActionCategory`
- Add governance evaluation calls before memory system operations
- Add governance evaluation calls before resource allocations
- Implement cumulative tracking for resource changes
- Implement oscillation detection for resource changes

### Step 3: Create Test Suite
- Create `tests/governance/test_phase3_memory_resource.py`
- Implement all 18 tests
- Use TestBase class for database logging
- Ensure 100% test coverage

### Step 4: Validate Blocking Behavior
- Ensure rejected actions do NOT execute
- Ensure queued actions wait indefinitely
- Ensure Singleton can continue other work while actions queued

---

## Success Criteria

✅ **All 18 tests passing (100%)**
✅ **Memory architecture changes trigger governance**
✅ **Resource allocation changes trigger governance**
✅ **Safe operations execute immediately**
✅ **Rejected actions do NOT execute**
✅ **Queued actions wait indefinitely**
✅ **Capability token enforcement preserved (orthogonal to governance)**

---

## Critical Notes

### Memory Operations
- Governance applies to **SYSTEM architecture**, not individual memories
- Individual memory deletion/editing requires **MemoryAgent capability tokens**
- Shadow suppression prevention is CRITICAL (ranking, filtering, visibility changes)

### Resource Allocation
- Cumulative tracking prevents death-by-a-thousand-cuts attacks
- Oscillation detection prevents instability
- Reserved margin enforcement (usable capacity = total - reserved)

### Blocking Behavior
- MUST_BLOCK enforcement mode means action CANNOT proceed without approval
- No timeouts - actions wait indefinitely
- Singleton continues other work while dangerous actions queued

---

**Document Status**: DRAFT
**Created**: January 1, 2026
**Next Action**: Inspect current code, implement governance integration, create test suite
