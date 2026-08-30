# Phase 1: Core Infrastructure Testing Plan

## Overview

Verify that the core governance infrastructure is correctly implemented and functional:
- Configuration loading from governance_triggers.json
- UnifiedGovernanceTriggerSystem evaluation logic
- Decision tier assignment (CRITICAL/IMPORTANT/ROUTINE)
- Escalation category mapping
- Irreversibility classification

## Test Categories

### 1. Configuration Loading Tests

**Test 1.1: Load governance_triggers.json**
- ✅ File exists and is valid JSON
- ✅ Contains all 8 action categories
- ✅ Schema version is present
- ✅ Each trigger has required fields

**Test 1.2: Validate trigger structure**
- ✅ Each trigger has trigger_id, name, conditions
- ✅ escalation_category is defined
- ✅ irreversibility_class is one of: IRREVERSIBLE, PARTIALLY_REVERSIBLE, MOSTLY_REVERSIBLE, FULLY_REVERSIBLE
- ✅ enforcement_mode is one of: MUST_BLOCK, RECOMMEND_GOVERNANCE, LOG_ONLY

### 2. Condition Matching Tests

**Test 2.1: TOOL_EXECUTION - Exact match**
- Action: ChaosTestingTool with target="production"
- Expected: Match trigger_id "tool_exec_001"
- Decision Tier: CRITICAL

**Test 2.2: TOOL_EXECUTION - Regex match**
- Action: ChaosTestingTool with target="prod-server-01"
- Expected: Match trigger_id "tool_exec_001" (matches "production|prod")
- Decision Tier: CRITICAL

**Test 2.3: TOOL_EXECUTION - Numeric comparison**
- Action: ChaosTestingTool with intensity=8
- Expected: Match trigger_id "tool_exec_002" (intensity >= 7)
- Decision Tier: IMPORTANT

**Test 2.4: TOOL_EXECUTION - Contains match**
- Action: MutationTestingTool with target_files=["core/governance/test.py"]
- Expected: Match trigger_id "tool_exec_003" (contains_any: core/governance)
- Decision Tier: CRITICAL

**Test 2.5: TOOL_EXECUTION - No match**
- Action: ChaosTestingTool with target="staging", intensity=3
- Expected: No match, returns ROUTINE tier
- Decision Tier: ROUTINE

### 3. Decision Tier Assignment Tests

**Test 3.1: CRITICAL tier assignment**
- Conditions that should trigger CRITICAL:
  - enforcement_mode = MUST_BLOCK
  - irreversibility_class = IRREVERSIBLE
  - safety_risk = CRITICAL
- Verify: evaluate_action() returns decision_tier="CRITICAL"

**Test 3.2: IMPORTANT tier assignment**
- Conditions that should trigger IMPORTANT:
  - enforcement_mode = RECOMMEND_GOVERNANCE
  - irreversibility_class = PARTIALLY_REVERSIBLE
  - impact_level = MEDIUM or HIGH
- Verify: evaluate_action() returns decision_tier="IMPORTANT"

**Test 3.3: ROUTINE tier assignment**
- Conditions that should trigger ROUTINE:
  - enforcement_mode = LOG_ONLY
  - No matching triggers
  - Low risk actions
- Verify: evaluate_action() returns decision_tier="ROUTINE"

### 4. Escalation Category Mapping Tests

**Test 4.1: Tool execution categories**
- CHAOS_TESTING_PRODUCTION
- CHAOS_TESTING_HIGH_INTENSITY
- MUTATION_TESTING_CRITICAL_FILES
- FUZZ_TESTING_CODE_EXEC

**Test 4.2: Memory operation categories**
- MEMORY_SYSTEM_ARCHITECTURE
- MEMORY_STORAGE_FORMAT

**Test 4.3: Resource allocation categories**
- RESOURCE_ALLOCATION_LARGE_CHANGE
- RESOURCE_CAPACITY_EXCEEDED

**Test 4.4: Learning categories**
- MODEL_WEIGHT_MODIFICATION
- LEARNING_PARAMETER_CHANGE

**Test 4.5: Configuration categories**
- SAFETY_THRESHOLD_MODIFICATION
- CRITICAL_CONFIG_CHANGE

**Test 4.6: Task creation categories**
- RECURSIVE_TASK_CREATION
- BULK_TASK_CREATION

**Test 4.7: External integration categories**
- NEW_EXTERNAL_INTEGRATION
- EXTERNAL_API_REGISTRATION

**Test 4.8: Curiosity categories**
- CURIOSITY_HIGH_RISK_EXPLORATION

### 5. Irreversibility Classification Tests

**Test 5.1: IRREVERSIBLE classification**
- Model weight modifications
- Production chaos testing
- Fuzz testing with code execution
- Examples should return irreversibility_class="IRREVERSIBLE"

**Test 5.2: PARTIALLY_REVERSIBLE classification**
- Memory system architecture changes
- High intensity chaos testing
- Resource allocation changes
- Examples should return irreversibility_class="PARTIALLY_REVERSIBLE"

**Test 5.3: MOSTLY_REVERSIBLE classification**
- Mutation testing on critical files
- Configuration changes with backups
- Examples should return irreversibility_class="MOSTLY_REVERSIBLE"

**Test 5.4: FULLY_REVERSIBLE classification**
- Read operations
- Safe analysis tools
- Low-impact changes
- Examples should return irreversibility_class="FULLY_REVERSIBLE"

### 6. Cross-Category Integration Tests

**Test 6.1: All 8 action categories**
Verify evaluate_action() works for:
- ✅ TOOL_EXECUTION
- ✅ MEMORY_OPERATIONS
- ✅ RESOURCE_ALLOCATION
- ✅ LEARNING_CHANGES
- ✅ CONFIG_MODIFICATIONS
- ✅ TASK_CREATION
- ✅ EXTERNAL_INTEGRATIONS
- ✅ CURIOSITY_EXPLORATION

**Test 6.2: Edge cases**
- Action with no matching triggers → ROUTINE
- Action matching multiple triggers → Highest severity wins
- Invalid action_category → Error handling
- Missing required parameters → Error handling

## Test Execution

### Unit Test File: `tests/governance/test_phase1_core_infrastructure.py`

Create comprehensive pytest tests covering all scenarios above.

### Success Criteria

- ✅ All configuration loading tests pass
- ✅ All condition matching tests pass
- ✅ All decision tier assignment tests pass
- ✅ All escalation category mapping tests pass
- ✅ All irreversibility classification tests pass
- ✅ All cross-category integration tests pass
- ✅ Code coverage > 90% for unified_governance_trigger_system.py

## Implementation Commands

```bash
# Run Phase 1 tests
pytest tests/governance/test_phase1_core_infrastructure.py -v

# Run with coverage
pytest tests/governance/test_phase1_core_infrastructure.py --cov=core.governance --cov-report=term-missing

# Run specific test category
pytest tests/governance/test_phase1_core_infrastructure.py::TestConditionMatching -v
```

## Expected Output

```
tests/governance/test_phase1_core_infrastructure.py::TestConfigurationLoading::test_load_governance_triggers PASSED
tests/governance/test_phase1_core_infrastructure.py::TestConfigurationLoading::test_validate_trigger_structure PASSED
tests/governance/test_phase1_core_infrastructure.py::TestConditionMatching::test_tool_execution_exact_match PASSED
tests/governance/test_phase1_core_infrastructure.py::TestConditionMatching::test_tool_execution_regex_match PASSED
tests/governance/test_phase1_core_infrastructure.py::TestConditionMatching::test_tool_execution_numeric_comparison PASSED
tests/governance/test_phase1_core_infrastructure.py::TestConditionMatching::test_tool_execution_contains_match PASSED
tests/governance/test_phase1_core_infrastructure.py::TestConditionMatching::test_tool_execution_no_match PASSED
tests/governance/test_phase1_core_infrastructure.py::TestDecisionTier::test_critical_tier_assignment PASSED
tests/governance/test_phase1_core_infrastructure.py::TestDecisionTier::test_important_tier_assignment PASSED
tests/governance/test_phase1_core_infrastructure.py::TestDecisionTier::test_routine_tier_assignment PASSED
tests/governance/test_phase1_core_infrastructure.py::TestEscalationCategory::test_all_categories_mapped PASSED
tests/governance/test_phase1_core_infrastructure.py::TestIrreversibility::test_irreversible_classification PASSED
tests/governance/test_phase1_core_infrastructure.py::TestIrreversibility::test_partially_reversible_classification PASSED
tests/governance/test_phase1_core_infrastructure.py::TestIrreversibility::test_mostly_reversible_classification PASSED
tests/governance/test_phase1_core_infrastructure.py::TestIrreversibility::test_fully_reversible_classification PASSED
tests/governance/test_phase1_core_infrastructure.py::TestCrossCategory::test_all_8_action_categories PASSED
tests/governance/test_phase1_core_infrastructure.py::TestCrossCategory::test_edge_cases PASSED

======================== 17 passed in 2.34s ========================
Coverage: 95%
```

## Next Steps After Phase 1 Completion

Once all tests pass:
1. Document any issues found and resolutions
2. Update governance_triggers.json if needed
3. Commit Phase 1 infrastructure with passing tests
4. Proceed to Phase 2: Tool Execution Integration
