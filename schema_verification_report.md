# PostgreSQL Schema Verification Report
**Date:** 2026-02-12
**Purpose:** Verify completeness of postgres_schemas.sql

## Tables Currently in postgres_schemas.sql (48 tables)

### unified schema (45 tables)
✓ auth_logs
✓ benchmark_history
✓ chaos_adapter_state
✓ chaos_events
✓ chaos_experiments
✓ chaos_metrics
✓ component_health
✓ directive_ab_tests
✓ directive_applications
✓ directive_evolution_log
✓ directive_governance_evaluations
✓ emergency_halts
✓ generated_improvements
✓ goals
✓ governance_audit_log
✓ governance_laws
✓ governance_module_state
✓ governance_violations
✓ improvement_events
✓ improvement_metrics
✓ internal_directives
✓ intrinsic_motivation
✓ malware_analyses
✓ meta_parameter_snapshots
✓ metric_measurements
✓ model_weight_backups
✓ novelty_detections
✓ operation_logs
✓ pending_approvals
✓ performance_logs
✓ performance_metrics
✓ plans
✓ profiler_results
✓ research_predictions
✓ research_publications
✓ security_events
✓ security_logs
✓ security_training_examples
✓ system_alerts
✓ system_failures
✓ system_logs
✓ test_results
✓ test_sessions
✓ tool_tracking_state
✓ tool_usage_history

### memory_hot schema (2 tables)
✓ memory_hot
✓ archive_log

### memory_cold schema (1 table)
✓ memory_cold

---

## MISSING TABLES Found in Codebase

### 1. Unified System Tables (unified_database_schemas.py)
❌ **components** - Unified component registry
   - Location: data/system/unified_database_schemas.py:150-180
   - Purpose: Central registry of all Dominion Labs components
   - Replaces: component_health (older table)
   - Status: CRITICAL - Used by UnifiedDatabaseSchemas system

❌ **unified_metrics** - Unified metrics consolidation
   - Location: data/system/unified_database_schemas.py:22-52
   - Purpose: Consolidates ResourceManager.resource_metrics and HealthManager.health_metrics
   - Status: CRITICAL - Used by monitoring systems

❌ **unified_alerts** - Unified alerts consolidation
   - Location: data/system/unified_database_schemas.py:54-90
   - Purpose: Consolidates resource_alerts and health_alerts
   - Status: CRITICAL - Used by alert management

❌ **unified_processes** - Unified process monitoring
   - Location: data/system/unified_database_schemas.py:92-128
   - Purpose: Process metrics tracking
   - Status: CRITICAL - Used by resource manager

❌ **unified_actions** - Unified action tracking
   - Location: data/system/unified_database_schemas.py:182-216
   - Purpose: Optimization and healing actions
   - Status: CRITICAL - Used by action management

### 2. Thinking State Tables (thinking_state_manager.py)
❌ **thinking_states** - AI thinking state persistence
   - Location: core/database/thinking_state_manager.py:145-161
   - Purpose: Persistent storage of thinking states, reasoning chains, cognitive traces
   - Status: HIGH PRIORITY - Used by ThinkingStateManager

❌ **reasoning_chains** - Detailed reasoning tracking
   - Location: core/database/thinking_state_manager.py:166-179
   - Purpose: Detailed tracking of reasoning steps
   - Status: HIGH PRIORITY - Foreign key to thinking_states

### 3. Scientific Research Tables (hypothesis_testing.py)
❌ **hypotheses** - Scientific hypotheses
   - Location: core/reasoning/hypothesis_testing.py:208-221
   - Purpose: Store falsifiable hypotheses with predictions
   - Status: MEDIUM PRIORITY - Used by HypothesisTestingSystem
   - Note: Code shows SQLite but comments indicate unified DB migration

❌ **experiments** - Hypothesis testing experiments
   - Location: core/reasoning/hypothesis_testing.py:224-238
   - Purpose: Experimental design and results
   - Status: MEDIUM PRIORITY - Foreign key to hypotheses

❌ **evidence** - Scientific evidence tracking
   - Location: core/reasoning/hypothesis_testing.py:241-256
   - Purpose: Evidence for/against hypotheses
   - Status: MEDIUM PRIORITY - Foreign keys to hypotheses and experiments

### 4. Analogy Discovery Tables (analogy_discovery.py)
❌ **concepts** - Concept knowledge base
   - Location: core/reasoning/analogy_discovery.py:181-189
   - Purpose: Store concepts for analogy discovery
   - Status: LOW-MEDIUM PRIORITY - Used by AnalogyDiscovery system

❌ **analogies** - Discovered analogies
   - Location: core/reasoning/analogy_discovery.py:192-199 (truncated)
   - Purpose: Store cross-domain analogies
   - Status: LOW-MEDIUM PRIORITY - Used by AnalogyDiscovery system

### 5. Formal Argumentation Tables (formal_argumentation.py)
❌ **arguments** - Formal arguments
   - Location: core/reasoning/formal_argumentation.py (imports TorinUnifiedDatabase line 39)
   - Purpose: Store Toulmin-model arguments
   - Status: LOW-MEDIUM PRIORITY - Used by FormalArgumentationSystem

❌ **claims** - Argument claims
   - Location: core/reasoning/formal_argumentation.py
   - Purpose: Store claims with Toulmin structure
   - Status: LOW-MEDIUM PRIORITY

❌ **fallacies** - Logical fallacy detection
   - Location: core/reasoning/formal_argumentation.py
   - Purpose: Track detected fallacies
   - Status: LOW-MEDIUM PRIORITY

---

## Priority Assessment

### CRITICAL (Must Add - System Will Fail)
1. components
2. unified_metrics
3. unified_alerts
4. unified_processes
5. unified_actions

These are part of the UnifiedDatabaseSchemas system that consolidates monitoring and management. Without these, the unified schema migration will fail.

### HIGH PRIORITY (Core Functionality)
6. thinking_states
7. reasoning_chains

These support the ThinkingStateManager which is actively used for AI state persistence.

### MEDIUM PRIORITY (Advanced Features)
8. hypotheses
9. experiments
10. evidence

Scientific hypothesis testing - may be optional but code expects them.

### LOW-MEDIUM PRIORITY (Specialized Features)
11. concepts
12. analogies
13. arguments
14. claims
15. fallacies

Analogy discovery and formal argumentation - may be optional features.

---

## Recommendation

**Action Required:** Add all 15 missing tables to postgres_schemas.sql

**Grouping:**
- Add CRITICAL tables to unified schema (5 tables)
- Add HIGH PRIORITY tables to unified schema (2 tables)
- Add MEDIUM PRIORITY tables to unified schema (3 tables)
- Add LOW-MEDIUM PRIORITY tables to unified schema (5 tables)

**Total New Tables:** 15
**New Total:** 63 tables (was 48, now 63)

---

## Schema Organization Decision

All tables should go in **unified schema** because:
1. They all use TorinUnifiedDatabase
2. They're part of the main operational system
3. memory_hot and memory_cold are specifically for memory tiering only
4. Keeps reasoning/management tables together for easier querying
