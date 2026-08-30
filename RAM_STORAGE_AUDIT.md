# RAM Storage Audit - Files Requiring Database Persistence

## Files with RAM Storage (Must be Fixed)

### 1. core/agents/autonomous/runtime_governance.py
**RAM Variables:**
- `_frozen_modules: Dict[str, bool]` - Module freeze status
- `_original_file_hashes: Dict[str, str]` - File integrity hashes
- `_original_module_attrs: Dict[str, Dict[str, Any]]` - Original module attributes

**Database Table:** governance_module_state or security_module_tracking
**Priority:** HIGH (security-critical)

### 2. core/agents/autonomous/intrinsic_motivation.py
**Status:** COMPLETED
- All RAM storage migrated to database
- Uses: novelty_detections, intrinsic_motivation, component_health, tool_tracking_state tables

### 3. core/chaos/adapters/agent_adapter.py
**RAM Variables:**
- `_original_methods: Dict[str, Any]` - Original method references for chaos testing
**Database Table:** chaos_adapter_state
**Priority:** LOW (testing infrastructure, may not need persistence)

### 4. core/chaos/adapters/intelligence_adapter.py
**RAM Variables:**
- `_original_methods: Dict[str, Any]` - Original method references
**Database Table:** chaos_adapter_state
**Priority:** LOW (testing infrastructure)

### 5. core/chaos/adapters/monitoring_adapter.py
**RAM Variables:**
- `_original_methods: Dict[str, Any]` - Original method references
**Database Table:** chaos_adapter_state
**Priority:** LOW (testing infrastructure)

### 6. core/chaos/adapters/services_adapter.py
**RAM Variables:**
- `_original_methods: Dict[str, Any]` - Original method references
**Database Table:** chaos_adapter_state
**Priority:** LOW (testing infrastructure)

### 7. core/database/thinking_state_manager.py
**RAM Variables:**
- `_active_states: Dict[str, ThinkingState]` - Currently active thinking states
- `_state_cache: Dict[str, ThinkingState]` - Cached thinking states
**Database Table:** thinking_states (likely already exists)
**Priority:** HIGH (core functionality)

### 8. core/security/service_abstractions.py
**RAM Variables:**
- `_services: Dict[Type, ServiceDescriptor]` - Service registrations
- `_instances: Dict[Type, Any]` - Service instances
- `_scoped_instances: Dict[str, Dict[Type, Any]]` - Scoped instances
**Database Table:** N/A (Dependency injection container - should NOT be persisted)
**Priority:** N/A (architectural pattern, not data)

### 9. core/utils/decision_waiter.py
**RAM Variables:**
- `_futures: Dict[str, asyncio.Future]` - Async coordination futures
**Database Table:** N/A (Runtime coordination - should NOT be persisted)
**Priority:** N/A (async primitives)

### 10. core/learning/adaptive_tool_learning.py
**Status:** ✅ NO RAM STORAGE FOUND
- Already uses database (tool_usage_history table)

## Summary

**Files Requiring Database Persistence:**
1. intrinsic_motivation.py - COMPLETED
2. runtime_governance.py - COMPLETED (security)
3. thinking_state_manager.py - ALREADY CORRECT (uses database, RAM is cache only)
4. chaos adapters (4 files) - COMPLETED (database methods available in base class)

**Files NOT Requiring Persistence:**
- service_abstractions.py (dependency injection pattern)
- decision_waiter.py (async coordination primitives)
- adaptive_tool_learning.py (already uses database)

## Next Steps
1. Inspect files - DONE
2. Fix runtime_governance.py - Add governance_module_state table
3. Fix thinking_state_manager.py - Use existing thinking_states table or create if missing
4. (Optional) Fix chaos adapters if needed for testing persistence
