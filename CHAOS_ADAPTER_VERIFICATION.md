# Chaos Adapter Verification & Update Plan

**Date**: 2026-01-05
**Status**: 🔧 IN PROGRESS

---

## Executive Summary

Analysis of chaos adapters reveals they are **architecturally sound** but have:
1. ✅ **Correct API design** - Consistent across all adapters
2. ❌ **Outdated injection points** - Don't match current system structure
3. ❌ **Test mismatches** - Tests expect different API than implemented

**Action Required**: Update injection points to match current architecture + rewrite tests.

---

## Adapter API Analysis

### Current Implementation (Correct)

All adapters follow the **same pattern**:

```python
class SystemAdapter(TargetSystemAdapter):
    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle

    async def inject_error(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        error_type: str,
        error_rate: float
    ) -> InjectionHandle

    async def inject_resource_exhaustion(
        self,
        target_id: str,
        component: str,
        resource_type: str,
        limit_value: Optional[float] = None
    ) -> InjectionHandle

    async def get_health_metrics(self) -> Dict[str, Any]

    async def cleanup(self)
```

**✅ This API is correct and consistent.**

### Test Expectations (Incorrect)

Tests expect:
```python
# Wrong: Single InjectionConfig parameter
await adapter.inject_latency(latency_config)

# Wrong: _chaos_active boolean flag
assert adapter._chaos_active is True

# Wrong: MetricsSnapshot return type
metrics = await adapter.get_health_metrics()
assert isinstance(metrics, MetricsSnapshot)
```

**❌ Tests need complete rewrite to match actual API.**

---

## Memory Adapter Detailed Analysis

### Current Injection Points (Outdated)

```python
self.injection_points = {
    "mysql_query": "memory_storage_mysql",      # ❌ Too vague
    "r2_retrieval": "r2_storage",               # ❌ Component name wrong
    "memory_search": "memory_agent",            # ✅ Correct
    "token_allocation": "capability_tokens"     # ⚠️ May not exist
}
```

### Actual Memory System Architecture

**Components**:
1. **MemoryAgent** ([core/agents/memory_agent.py](core/agents/memory_agent.py))
   - Coordinates hot/cold tiers
   - Methods: `store_memory()`, `search_memories()`, `query_by_tags()`, `update_memory()`, `delete_memory()`

2. **MySQLStorage** ([core/memory/storage/mysql_storage.py](core/memory/storage/mysql_storage.py))
   - Hot tier (0-60 days)
   - Methods: `store_memory()`, `search_memories()`
   - Database: `torinai_thinking_hot`

3. **R2Storage** ([core/memory/storage/r2_storage.py](core/memory/storage/r2_storage.py))
   - Cold tier (60+ days archival)
   - Methods: `store_memory()`, `search_memories()`

4. **MySQLQueryAgent** ([core/memory/query/mysql_query_agent.py](core/memory/query/mysql_query_agent.py))
   - Read-only query interface
   - Methods: `search()`, `search_by_tags()`, `get_memory()`

5. **EmbeddingService** ([core/memory/utils/embedding_service.py](core/memory/utils/embedding_service.py))
   - Semantic similarity search
   - Model: all-MiniLM-L6-v2

### Corrected Injection Points

```python
self.injection_points = {
    # MySQL hot tier storage
    "mysql_store": "mysql_storage.store_memory",
    "mysql_search": "mysql_storage.search_memories",

    # R2 cold tier storage
    "r2_store": "r2_storage.store_memory",
    "r2_search": "r2_storage.search_memories",

    # Memory agent coordination
    "agent_store": "memory_agent.store_memory",
    "agent_search": "memory_agent.search_memories",
    "agent_query_tags": "memory_agent.query_by_tags",

    # Query agents
    "query_search": "mysql_query_agent.search",
    "query_tags": "mysql_query_agent.search_by_tags",

    # Embedding service
    "embedding_encode": "embedding_service.encode",
    "embedding_search": "embedding_service.search_similar"
}
```

### Memory Adapter Health Metrics

**Current metrics** (need verification):
```python
{
    "mysql_query_latency_p95": 80.0,
    "r2_retrieval_latency_p95": 500.0,
    "memory_search_success_rate": 0.99,
    "capability_token_utilization": 0.6,  # ⚠️ May not exist

    # Reasoning trace metrics (GOOD - unique to memory)
    "reasoning_trace_completeness_rate": 0.85,
    "reasoning_trace_avg_length": 150,
    "thinking_state_capture_rate": 0.90,
    "decision_factors_population_rate": 0.75
}
```

**✅ Reasoning trace metrics are excellent and should be kept.**
**⚠️ `capability_token_utilization` needs verification.**

---

## Verification Checklist

### Memory Adapter ✅⚠️

- [x] API signature matches base adapter
- [x] Returns `InjectionHandle` from inject methods
- [x] Returns `Dict[str, Any]` from `get_health_metrics()`
- [x] Has `cleanup()` implementation
- [x] Unique reasoning trace metrics
- [ ] Injection points match actual memory system components
- [ ] Component names match actual class names
- [ ] Health metrics reflect actual monitoring points

### Other Adapters (Need Review)

- [ ] **Tool Adapter** - Verify against tool registry
- [ ] **Learning Adapter** - Verify against learning pipeline
- [ ] **Security Adapter** - Verify against security system
- [ ] **Reasoning Adapter** - Verify against neural bridge
- [ ] **Agent Adapter** - Verify against agent coordinator
- [ ] **Domain Adapter** - Verify against domain system
- [ ] **Intelligence Adapter** - Verify against intelligence system
- [ ] **Monitoring Adapter** - Verify against observability
- [ ] **Services Adapter** - Verify against LLM services

---

## Test Update Plan

### Phase 1: Rewrite Test Fixtures

**Old (incorrect)**:
```python
@pytest.fixture
def latency_config():
    return InjectionConfig(
        component="test_component",
        injection_point="test_point",
        chaos_type=ChaosType.LATENCY,
        duration_seconds=300,
        delay_ms=500,
        jitter_ms=100
    )
```

**New (correct)**:
```python
@pytest.fixture
def test_target_id():
    return "test_experiment_001"

@pytest.fixture
def test_component():
    return "memory_agent"

@pytest.fixture
def test_injection_point():
    return "search_memories"
```

### Phase 2: Rewrite Test Assertions

**Old (incorrect)**:
```python
async def test_inject_latency(self, adapter, latency_config):
    await adapter.inject_latency(latency_config)
    assert adapter._chaos_active is True
```

**New (correct)**:
```python
async def test_inject_latency(self, adapter, test_target_id):
    handle = await adapter.inject_latency(
        target_id=test_target_id,
        component="memory_agent",
        injection_point="search_memories",
        delay_ms=500,
        jitter_ms=100
    )

    assert handle.injection_id is not None
    assert handle.active is True
    assert handle.target == "memory_system"
    assert handle.chaos_type == ChaosType.LATENCY
    assert len(adapter.active_injections) == 1
```

### Phase 3: Rewrite Health Metrics Tests

**Old (incorrect)**:
```python
async def test_get_health_metrics(self, adapter):
    metrics = await adapter.get_health_metrics()
    assert isinstance(metrics, MetricsSnapshot)
    assert metrics.latency_p95_ms >= 0
```

**New (correct)**:
```python
async def test_get_health_metrics(self, adapter):
    metrics = await adapter.get_health_metrics()

    assert isinstance(metrics, dict)
    assert "healthy" in metrics
    assert "mysql_query_latency_p95" in metrics
    assert metrics["mysql_query_latency_p95"] >= 0

    # Memory-specific metrics
    assert "reasoning_trace_completeness_rate" in metrics
    assert 0 <= metrics["reasoning_trace_completeness_rate"] <= 1
```

---

## Implementation Priority

### P0 - Critical (Do First)

1. **Update Memory Adapter injection points** to match current memory system
2. **Remove capability_token references** (likely removed in memory restructure)
3. **Rewrite test_adapters.py** to match actual API

### P1 - High (Do Next)

4. **Verify Tool Adapter** against current tool registry
5. **Verify Learning Adapter** against learning pipeline
6. **Verify Reasoning Adapter** against neural bridge

### P2 - Medium

7. **Verify Agent Adapter** against agent coordinator
8. **Verify Security/Domain/Intelligence** adapters

### P3 - Low

9. **Verify Monitoring/Services** adapters
10. **Update integration tests**

---

## Expected Changes

### Memory Adapter

**File**: [core/chaos/adapters/memory_adapter.py](core/chaos/adapters/memory_adapter.py)

**Changes needed**:
1. Update `injection_points` dict (lines 40-46)
2. Remove `capability_tokens` references
3. Update component names in inject methods
4. Update health metrics (remove deprecated fields)
5. Keep reasoning trace metrics (they're good!)

### Test File

**File**: [tests/chaos/test_adapters.py](tests/chaos/test_adapters.py)

**Changes needed**:
1. Rewrite all fixtures (lines 38-86)
2. Rewrite all test methods (lines 90-460)
3. Remove `InjectionConfig` usage
4. Remove `_chaos_active` checks
5. Remove `MetricsSnapshot` type checks
6. Add proper API call tests

---

## Success Criteria

✅ All adapters:
- Match base adapter API contract
- Target actual system components (not outdated names)
- Return correct types (InjectionHandle, Dict)
- Have comprehensive health metrics

✅ All tests:
- Pass with pytest
- Test actual adapter API
- Don't reference deprecated attributes
- Validate injection handles properly

✅ Documentation:
- Injection points documented
- Health metrics explained
- Examples updated

---

## Next Steps

1. **Update memory adapter** injection points
2. **Rewrite memory adapter tests**
3. **Run memory adapter tests** to verify
4. **Repeat for other adapters** (tool, learning, reasoning, etc.)
5. **Integration testing** with chaos orchestrator

---

## Notes

- **Memory adapter reasoning trace metrics are excellent** - keep these!
- **All adapters follow same API pattern** - this is good design
- **Tests are completely out of sync** - suggests they were written for planned API that changed
- **Recent memory restructure** likely removed capability tokens and changed component names
