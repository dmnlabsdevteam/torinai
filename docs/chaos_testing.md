# Chaos Testing Framework

## What It Does

Breaks things on purpose to find weaknesses before they cause real problems. Injects faults (latency, errors, resource exhaustion) into different systems and validates they handle it gracefully.

## Why

If your memory system crashes when MySQL is slow, better to find out in testing than when it matters.

## Target Systems

- **Learning**: Continuous learning pipeline, pattern recognition, model training
- **Security**: WAF, malware sandbox, threat intelligence
- **Reasoning**: Hypothesis testing, neural bridge, Bayesian inference
- **Agents**: Governance queue, task executor, planning engine
- **Domain**: Cross-domain reasoner, ontology registry
- **Memory**: MySQL hot tier, R2 cold tier, capability tokens
- **Tools**: Tool registry, database connections, external APIs

## Chaos Types

**Latency** - Slow things down
- Add delay_ms + jitter to operations
- Tests: Timeouts, queueing, backpressure

**Errors** - Make things fail
- Inject exceptions at error_rate %
- Tests: Retry logic, fallbacks, error handling

**Resource Exhaustion** - Starve resources
- Limit CPU, memory, connections, disk
- Tests: Degradation, throttling, overflow

**Partial Failures** - Network issues
- Simulate partitions, packet loss, connection drops
- Tests: Distributed system resilience

## Architecture

```
ChaosOrchestrator (main controller)
├── ChaosExperimentManager (CRUD, scenarios)
├── ChaosInjectionEngine (fault injection)
├── ChaosSafetyController (pre-flight, SLO monitoring, rollback)
└── Target Adapters (7 system-specific adapters)
```

### Safety Controls

**Pre-flight checks**:
- Target system health OK
- Resources available (CPU <80%, Memory <85%)
- No concurrent experiments on same target
- Governance approval obtained

**SLO monitoring** (continuous during experiment):
- Latency p95 < 500ms, p99 < 1000ms
- Error rate < 1%
- Resource usage within limits

**Automatic rollback** if SLO violations detected

**Circuit breaker**: Opens after 5 consecutive failures, timeout 60s

## Progressive Rollout

4-stage deployment:

1. **Canary** (1% blast radius, 5 min)
2. **Gradual 10%** (10% blast radius, 10 min)
3. **Gradual 50%** (50% blast radius, 15 min)
4. **Full** (100% blast radius, 30 min)

Rollback to previous stage on SLO violations.

## Governance Integration

**Decision Tier Mapping**:
- **ROUTINE**: Canary tests (1%) in dev/staging - auto-approved
- **IMPORTANT**: Gradual rollout (10-50%) in staging - notification approval
- **CRITICAL**: Full production (>50%) or critical systems - full governance session

Critical systems requiring CRITICAL tier:
- governance_*
- safety_*
- memory_* (if production)

## Example Scenarios

### Memory: Reasoning Trace Capture Under Latency
```
Inject: 300ms delay on store_memory()
Hypothesis: Capture rate should stay >80% despite storage latency
Validation: Check reasoning_trace_completeness_rate
```

### Security: WAF Latency Spike
```
Inject: 500ms delay on request analysis
Hypothesis: Requests should queue, not drop
Validation: p95 latency <800ms, error rate <1%
```

### Learning: Training Pipeline Failures
```
Inject: 20% error rate on model checkpoint saves
Hypothesis: Should retry with exponential backoff
Validation: Eventually saves, no data loss
```

## Key Files

**Core Framework**:
- `core/chaos/orchestrator.py` - Main controller
- `core/chaos/experiment_manager.py` - Experiment CRUD
- `core/chaos/injection_engine.py` - Fault injection
- `core/chaos/safety_controller.py` - Safety guardrails
- `core/chaos/observability.py` - Metrics collection

**Adapters** (one per system):
- `core/chaos/adapters/memory_adapter.py`
- `core/chaos/adapters/learning_adapter.py`
- `core/chaos/adapters/security_adapter.py`
- (etc.)

**Scenarios**:
- `core/chaos/scenarios/scenario_library.py` - 20+ pre-built scenarios

**Config**:
- `config/chaos_config.json` - Framework settings

## Using Decorators

Non-invasive injection via decorators:

```python
from core.chaos.decorators import ChaosDecorators

@ChaosDecorators.inject_latency(
    component="continuous_learning_pipeline",
    injection_point="data_loading",
    delay_ms=500,
    jitter_ms=100
)
async def load_training_data(self, batch_size: int):
    # Normal logic - chaos injected transparently
    pass
```

## Using Context Managers

Scoped chaos injection:

```python
from core.chaos.context_managers import chaos_experiment

async with chaos_experiment(experiment) as ctx:
    # Chaos enabled during this block
    await run_workload()
# Chaos automatically disabled after block
```

## Observability

Every experiment generates:
- Real-time metrics (collected every 5 seconds)
- Hypothesis validation results
- Experiment report with insights
- All data persisted to MySQL

## Running Experiments

1. **Create experiment** via ChaosExperimentManager
2. **Get governance approval** (auto for ROUTINE tier)
3. **Run pre-flight checks** via ChaosSafetyController
4. **Inject chaos** via ChaosInjectionEngine
5. **Monitor SLOs** continuously
6. **Auto rollback** on violations
7. **Generate report** with findings

## Configuration

Edit `config/chaos_config.json`:

```json
{
  "enabled": true,
  "safety_controls": {
    "slo_monitoring_enabled": true,
    "auto_rollback_enabled": true,
    "max_concurrent_experiments": 3
  },
  "slo_thresholds": {
    "latency_p95_ms": 500,
    "latency_p99_ms": 1000,
    "error_rate": 0.01,
    "cpu_percent": 80,
    "memory_percent": 85
  }
}
```

## Database Schema

**chaos_experiments** - Experiment metadata
**chaos_metrics** - Time-series metrics
**chaos_events** - Experiment events (start, stop, rollback, violations)

## Memory System Scenarios

6 scenarios specifically for memory + reasoning trace capture:

1. **MySQL Query Latency** - Slow queries on hot tier
2. **R2 Retrieval Failures** - Cold tier unavailable
3. **Capability Token Exhaustion** - Token pool depleted
4. **Reasoning Trace Capture Under Latency** - Validate capture quality
5. **Chain of Thought Persistence Under Errors** - Database failures
6. **Thinking State Capture Completeness** - Connection pool pressure

Each validates that chain of thought isn't dropped despite chaos.

## Design Principles

1. **Non-invasive** - Decorators/proxies, not code changes
2. **Safety-first** - Pre-flight checks, SLO monitoring, auto rollback
3. **Governance-integrated** - All experiments routed through approval
4. **Progressive** - Canary → gradual → full with stage rollback
5. **Observable** - Comprehensive metrics and reporting
6. **Fail-safe** - Circuit breakers prevent cascading failures

## What's Next

Add more scenarios as new systems are built. Each adapter makes it easy to inject chaos into that system without touching core code.
