# Phase 2: Tool Execution Integration - Testing Plan

**Phase**: 2
**Status**: NOT STARTED
**Dependencies**: Phase 1 (COMPLETE)
**Target Files**: [core/tools/tool_registry.py](../../core/tools/tool_registry.py:275-345)

---

## Overview

Phase 2 integrates the governance trigger system (validated in Phase 1) into the actual tool execution flow. This is where governance moves from **configuration** to **runtime enforcement**.

### Critical Architecture Principle

**Governance triggers on dangerous Singleton decisions, NOT all tool usage:**

- **ALL tools** call `governance.evaluate_action(tool_name, parameters)` - this is just a fast pattern match
- **SAFE tools** (read-only, low-risk) → Returns `ROUTINE` tier → Execute immediately (no queue, no delay)
- **DANGEROUS tools** with dangerous parameters → Returns `CRITICAL/IMPORTANT` tier → Queue for governance

**Examples**:
- `ReadFileTool("readme.txt")` → No trigger match → ROUTINE → Executes immediately
- `ChaosTestingTool(target="production")` → Matches `tool_exec_001` → CRITICAL → Queues for governance
- `MutationTestingTool(target_files=["core/governance"])` → Matches `tool_exec_003` → CRITICAL → Queues

**Performance**: Safe tools have minimal overhead (single pattern match check ~0.1ms). Only dangerous actions queue.

### Current State Analysis

**File**: `core/tools/tool_registry.py`
- **Governance imports**: ✓ Present (lines 29-34)
- **Integration code**: ✗ MISSING
- **Current behavior**: "NO APPROVAL CHECK: Singleton has full autonomy" (line 318)
- **Required changes**: Lines 275-345 in `execute_tool()` method

### What Phase 2 Must Implement

```python
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None  # NEW: For governance context
) -> ToolResult:
    """Execute tool with governance integration"""

    # 1. Get tool and validate parameters (EXISTING)

    # 2. NEW: Evaluate governance triggers
    # NOTE: This happens for ALL tools, but only dangerous ones will trigger
    from core.governance import UnifiedGovernanceTriggerSystem, ActionCategory
    governance = UnifiedGovernanceTriggerSystem()

    evaluation = await governance.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="execute_tool",
        parameters={
            "tool_name": tool_name,
            **parameters  # Tool-specific params for trigger matching
        },
        context=context or {}
    )

    # 3. NEW: Route based on decision tier
    # MOST tools will be ROUTINE (safe) and skip to step 4
    if evaluation.decision_tier == DecisionTier.CRITICAL:
        # DANGEROUS ACTION: Queue for full governance session
        return await self._queue_for_governance(tool, parameters, evaluation)

    elif evaluation.decision_tier == DecisionTier.IMPORTANT:
        # MODERATE RISK: Send notification, wait for simple approval
        return await self._request_notification_approval(tool, parameters, evaluation)

    # DecisionTier.ROUTINE: Safe tool, auto-approved
    # No queue, no delay - just log and execute

    # 4. Execute tool (EXISTING)
    # 5. Log for audit (EXISTING)
```

---

## Phase 2 Testing Requirements

### Test Categories

1. **Governance Trigger Integration** (5 tests)
2. **Decision Tier Routing** (3 tests)
3. **Queue Management** (4 tests)
4. **Singleton Continuation** (2 tests)
5. **End-to-End Flows** (3 tests)

**Total**: 17 tests

---

## Test Suite Specification

### 1. Governance Trigger Integration Tests

#### Test 1.1: Production Chaos Testing Triggers CRITICAL
**Validates**: Tool execution calls governance system correctly

```python
async def test_production_chaos_triggers_critical(self):
    """Verify ChaosTestingTool with production target triggers CRITICAL governance"""

    # Setup
    registry = ToolRegistry()
    chaos_tool = ChaosTestingTool()  # Assuming this exists
    registry.register(chaos_tool)

    # Execute with production target
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production", "duration": 60}
    )

    # Verify governance was triggered
    assert result.governance_triggered == True
    assert result.governance_tier == "CRITICAL"
    assert result.trigger_id == "tool_exec_001"
    assert result.status == "QUEUED_FOR_GOVERNANCE"
    assert result.success == False  # Not executed yet
```

**Expected Behavior**:
- Governance system called with ActionCategory.TOOL_EXECUTION
- Production target matches trigger condition
- Returns queued status, NOT executed
- Includes governance metadata in result

---

#### Test 1.2: Regex Pattern Matching (prod-*)
**Validates**: Regex conditions work in production code

```python
async def test_prod_server_regex_triggers(self):
    """Verify prod-server-* pattern triggers governance"""

    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "prod-server-42"}
    )

    assert result.governance_triggered == True
    assert result.trigger_id == "tool_exec_001"
```

---

#### Test 1.3: High Intensity Numeric Comparison
**Validates**: Numeric threshold conditions work

```python
async def test_high_intensity_triggers(self):
    """Verify intensity >= 7 triggers governance"""

    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "staging", "intensity": 9}
    )

    assert result.governance_triggered == True
    assert result.trigger_id == "tool_exec_002"
```

---

#### Test 1.4: Safe Tool Auto-Approval
**Validates**: Safe tools execute without governance

```python
async def test_safe_tool_auto_approved(self):
    """Verify safe tools execute immediately (ROUTINE tier)"""

    result = await registry.execute_tool(
        tool_name="SafeReadTool",
        parameters={"file_path": "readme.txt"}
    )

    assert result.governance_triggered == True  # Checked but auto-approved
    assert result.governance_tier == "ROUTINE"
    assert result.status == "COMPLETED"
    assert result.success == True  # Executed immediately
```

---

#### Test 1.5: Context Classification Integration
**Validates**: ContextClassifier labels are included

```python
async def test_context_classification_in_governance(self):
    """Verify context items are classified before governance"""

    context_items = [
        {"type": "action_parameters", "content": {"tool_name": "ChaosTestingTool"}},
        {"type": "tool_output", "content": "Previous result"}
    ]

    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"},
        context={"items": context_items}
    )

    # Verify context was classified
    assert result.classified_context is not None
    assert len(result.classified_context) == 2
    assert result.classified_context[0].label == ContextLabel.DECISIONAL
    assert result.classified_context[1].label == ContextLabel.TRANSIENT
```

---

### 2. Decision Tier Routing Tests

#### Test 2.1: CRITICAL Tier Queues for Full Governance
**Validates**: CRITICAL actions queue for 5 AI judges + human

```python
async def test_critical_tier_queues_for_governance(self):
    """Verify CRITICAL tier actions queue for full governance session"""

    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"}
    )

    # Check queue status
    assert result.status == "QUEUED_FOR_GOVERNANCE"
    assert result.queue_id is not None
    assert result.estimated_wait_time > 0  # Minutes

    # Verify NOT executed
    assert result.output is None
    assert result.success == False
```

---

#### Test 2.2: IMPORTANT Tier Sends Notification
**Validates**: IMPORTANT actions send simple notification

```python
async def test_important_tier_sends_notification(self):
    """Verify IMPORTANT tier sends user notification"""

    result = await registry.execute_tool(
        tool_name="ModerateRiskTool",
        parameters={"risk_level": "moderate"}
    )

    assert result.status == "AWAITING_NOTIFICATION_APPROVAL"
    assert result.notification_sent == True
    assert result.notification_timeout == 300  # 5 minutes
    assert result.success == False  # Not executed yet
```

---

#### Test 2.3: ROUTINE Tier Auto-Approves with Logging
**Validates**: ROUTINE actions execute immediately

```python
async def test_routine_tier_auto_approves(self):
    """Verify ROUTINE tier executes immediately with audit logging"""

    result = await registry.execute_tool(
        tool_name="SafeAnalysisTool",
        parameters={"analysis_type": "metrics"}
    )

    assert result.status == "COMPLETED"
    assert result.governance_tier == "ROUTINE"
    assert result.success == True
    assert result.audit_logged == True  # Still logged for audit trail
```

---

### 3. Queue Management Tests

#### Test 3.1: Queued Action Waits for Approval
**Validates**: Actions don't execute until approved

```python
async def test_queued_action_waits_for_approval(self):
    """Verify queued actions wait indefinitely for human decision"""

    # Queue action
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"}
    )

    queue_id = result.queue_id

    # Verify still queued after 10 seconds
    await asyncio.sleep(10)
    status = await registry.check_queue_status(queue_id)
    assert status == "PENDING_GOVERNANCE"

    # Verify NOT executed
    execution_result = await registry.get_execution_result(queue_id)
    assert execution_result is None
```

---

#### Test 3.2: Approved Action Executes
**Validates**: Approval triggers execution

```python
async def test_approved_action_executes(self):
    """Verify approved actions execute after governance approval"""

    # Queue action
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"}
    )

    queue_id = result.queue_id

    # Simulate governance approval
    from core.agents.autonomous.governance_queue import GovernanceQueue
    queue = GovernanceQueue()
    await queue.approve_action(
        queue_id=queue_id,
        decision="APPROVE",
        approver="human_user_123"
    )

    # Wait for execution
    await asyncio.sleep(2)

    # Verify executed
    execution_result = await registry.get_execution_result(queue_id)
    assert execution_result is not None
    assert execution_result.success == True
    assert execution_result.status == "COMPLETED"
```

---

#### Test 3.3: Rejected Action Does NOT Execute
**Validates**: Rejection blocks execution permanently

```python
async def test_rejected_action_blocked(self):
    """Verify rejected actions do NOT execute"""

    # Queue action
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"}
    )

    queue_id = result.queue_id

    # Simulate governance rejection
    queue = GovernanceQueue()
    await queue.reject_action(
        queue_id=queue_id,
        decision="REJECT",
        reason="Too risky for current environment",
        rejector="human_user_123"
    )

    # Wait
    await asyncio.sleep(2)

    # Verify NOT executed
    execution_result = await registry.get_execution_result(queue_id)
    assert execution_result is None or execution_result.success == False

    # Verify rejection logged
    audit_log = await registry.get_audit_log(queue_id)
    assert audit_log.decision == "REJECT"
    assert audit_log.reason == "Too risky for current environment"
```

---

#### Test 3.4: Queue Preserves Action Integrity
**Validates**: Approved action matches original (commitment contract)

```python
async def test_queue_preserves_action_integrity(self):
    """Verify executed action matches approved action (no tampering)"""

    # Queue action with specific parameters
    original_params = {"target": "production", "duration": 60}
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters=original_params
    )

    queue_id = result.queue_id

    # Get action hash before approval
    queue = GovernanceQueue()
    queued_action = await queue.get_action(queue_id)
    original_hash = queued_action.action_hash

    # Approve and execute
    await queue.approve_action(queue_id, "APPROVE", "human_user_123")
    await asyncio.sleep(2)

    # Verify executed parameters match original
    execution_result = await registry.get_execution_result(queue_id)
    assert execution_result.parameters == original_params
    assert execution_result.action_hash == original_hash
```

---

### 4. Singleton Continuation Tests

#### Test 4.1: Singleton Continues with Other Tasks
**Validates**: Blocking one action doesn't block unrelated work

```python
async def test_singleton_continues_with_other_work(self):
    """Verify Singleton continues with independent tasks while waiting"""

    # Queue CRITICAL action (blocks)
    critical_result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"}
    )

    assert critical_result.status == "QUEUED_FOR_GOVERNANCE"

    # Execute ROUTINE action (should work immediately)
    routine_result = await registry.execute_tool(
        tool_name="SafeAnalysisTool",
        parameters={"analysis_type": "metrics"}
    )

    assert routine_result.status == "COMPLETED"
    assert routine_result.success == True

    # Verify critical action still queued
    status = await registry.check_queue_status(critical_result.queue_id)
    assert status == "PENDING_GOVERNANCE"
```

---

#### Test 4.2: Dependent Tasks Wait or Branch
**Validates**: Tasks depending on queued actions are handled correctly

```python
async def test_dependent_tasks_wait_or_branch(self):
    """Verify tasks depending on queued actions block or branch"""

    # Queue action
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"}
    )

    queue_id = result.queue_id

    # Try to execute dependent task
    dependent_result = await registry.execute_tool(
        tool_name="AnalyzeChaosTool",
        parameters={"chaos_result_id": queue_id},
        dependencies=[queue_id]  # Declares dependency
    )

    # Should either:
    # 1. Also queue (waiting for dependency)
    # 2. Branch (use alternative approach)
    assert dependent_result.status in ["QUEUED_FOR_DEPENDENCY", "BRANCHED"]
    assert dependent_result.success == False  # Not executed yet
```

---

### 5. End-to-End Flow Tests

#### Test 5.1: Full CRITICAL Flow
**Validates**: Complete governance session flow

```python
async def test_full_critical_governance_flow(self):
    """Test: Tool trigger → Governance session → Human vote → Execution"""

    # 1. Tool execution triggers governance
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production", "duration": 60}
    )

    assert result.governance_triggered == True
    assert result.governance_tier == "CRITICAL"
    queue_id = result.queue_id

    # 2. Governance session launches
    from core.agents.autonomous.governance_session import GovernanceSession
    session = GovernanceSession()
    session_result = await session.evaluate_queued_action(queue_id)

    assert session_result.judges_count == 5
    assert session_result.human_oversight == True

    # 3. Human approves
    queue = GovernanceQueue()
    await queue.approve_action(queue_id, "APPROVE", "human_user_123")

    # 4. Action executes
    await asyncio.sleep(3)
    execution_result = await registry.get_execution_result(queue_id)

    assert execution_result.success == True
    assert execution_result.status == "COMPLETED"
```

---

#### Test 5.2: Full IMPORTANT Flow (Notification)
**Validates**: Notification approval flow

```python
async def test_full_important_notification_flow(self):
    """Test: Tool trigger → Notification → User clicks Approve → Execution"""

    # 1. Tool execution sends notification
    result = await registry.execute_tool(
        tool_name="ModerateRiskTool",
        parameters={"risk_level": "moderate"}
    )

    assert result.status == "AWAITING_NOTIFICATION_APPROVAL"
    notification_id = result.notification_id

    # 2. User approves via notification
    from core.notifications import NotificationSystem
    notif_system = NotificationSystem()
    await notif_system.user_responds(
        notification_id=notification_id,
        response="APPROVE"
    )

    # 3. Action executes
    await asyncio.sleep(2)
    execution_result = await registry.get_execution_result(result.queue_id)

    assert execution_result.success == True
    assert execution_result.response_time < 5  # Fast approval
```

---

#### Test 5.3: Rejection Logging and Learning
**Validates**: Rejected actions logged for pattern learning

```python
async def test_rejection_logged_for_learning(self):
    """Verify rejected actions stored for governance pattern learning"""

    # Queue and reject action
    result = await registry.execute_tool(
        tool_name="ChaosTestingTool",
        parameters={"target": "production"}
    )

    queue = GovernanceQueue()
    await queue.reject_action(
        queue_id=result.queue_id,
        decision="REJECT",
        reason="Too risky without rollback plan",
        rejector="human_user_123"
    )

    # Verify logged for learning
    from core.learning.governance_pattern_learner import GovernancePatternLearner
    learner = GovernancePatternLearner()

    decision_log = await learner.get_decision(result.queue_id)
    assert decision_log.decision == "REJECT"
    assert decision_log.action_category == "TOOL_EXECUTION"
    assert decision_log.trigger_id == "tool_exec_001"
    assert "rollback plan" in decision_log.reason
```

---

## Success Criteria

### Phase 2 Complete When:

1. ✅ All 17 tests passing
2. ✅ Tool execution integrated with governance trigger system
3. ✅ Decision tier routing implemented (CRITICAL/IMPORTANT/ROUTINE)
4. ✅ Queue management functional (queue, approve, reject, execute)
5. ✅ Singleton continues with independent work while queued actions wait
6. ✅ End-to-end flows validated (trigger → session → approval → execution)
7. ✅ All tests logged to MySQL with metadata

---

## Implementation Checklist

### Code Changes Required

- [ ] Modify `core/tools/tool_registry.py` execute_tool() method
  - [ ] Add governance evaluation call
  - [ ] Add decision tier routing logic
  - [ ] Add queue management integration
  - [ ] Add notification system integration
  - [ ] Preserve audit logging

- [ ] Ensure GovernanceQueue exists and works
  - [ ] Queue action storage
  - [ ] Approval/rejection handling
  - [ ] Execution triggering
  - [ ] Action integrity (commitment contracts)

- [ ] Ensure NotificationSystem exists (for IMPORTANT tier)
  - [ ] Notification sending
  - [ ] User response handling
  - [ ] Timeout management

### Test Infrastructure

- [ ] Create `tests/governance/test_phase2_tool_integration.py`
- [ ] Extend TestBase if needed for governance testing
- [ ] Add test helpers for simulating approvals/rejections
- [ ] Add test helpers for checking queue status

---

## Dependencies

### Must Exist Before Phase 2:
- ✅ Phase 1: UnifiedGovernanceTriggerSystem (COMPLETE)
- ✅ Phase 1: ContextClassifier (COMPLETE)
- ❓ GovernanceQueue class
- ❓ GovernanceSession class (for CRITICAL tier)
- ❓ NotificationSystem class (for IMPORTANT tier)

### Created During Phase 2:
- Tool registry governance integration code
- Queue management helpers
- Test suite (17 tests)

---

## Notes

**Principle**: Phase 2 is about **wiring**, not **configuration**. The trigger system already works (Phase 1 validated). Now we connect it to actual tool execution.

**Critical Architecture Decision**: Governance evaluates ALL tool executions, but only dangerous Singleton decisions trigger governance sessions:
- Safe tools (read-only, low-risk) → ROUTINE tier → Execute immediately (99% of tool usage)
- Dangerous tools with dangerous parameters → CRITICAL/IMPORTANT tier → Queue for governance (1% of tool usage)
- The governance system's trigger matching determines what's dangerous (governance_triggers.json)
- This is about Singleton decision-making and high-risk actions, not system capabilities

**Critical**: Phase 2 MUST preserve the "NO DELETION" principle from ContextClassifier - all context is preserved and classified, never filtered.

**Testing Philosophy**: Tests should validate both positive (approval → execution) and negative (rejection → blocked) flows to ensure governance is truly enforced. Tests must include BOTH dangerous tools (that trigger) AND safe tools (that don't trigger).

---

**Document Status**: DRAFT
**Created**: January 1, 2026
**Next Action**: Implement Phase 2 integration code, then run test suite
