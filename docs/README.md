# TorinAI Documentation

## Overview

TorinAI is an AGI system with reasoning, memory, learning, security, and autonomous capabilities. This doc folder contains practical guides for the main systems.

## Core Systems

### Memory & Filtering
[memory_filtering.md](memory_filtering.md) - How the system decides what's worth remembering

**Key idea**: Reasoning systems tag outputs with metadata (complexity, novelty, importance). Memory agent filters out trivial stuff like "What is the capital of France?" but keeps strategic decisions and deep reasoning.

**Main components**:
- MemoryWorthinessMetadata - Structured metadata with 7 namespaces
- MemoryFilter - O(1) deterministic filtering rules
- MemoryAgent - Integration point for storage

### Chaos Testing
[chaos_testing.md](chaos_testing.md) - Breaking things on purpose to find weaknesses

**Key idea**: Inject faults (latency, errors, resource exhaustion) into different systems and validate they handle it gracefully. Better to find issues in testing than in production.

**Main components**:
- ChaosOrchestrator - Main controller
- Target Adapters - 7 system-specific adapters
- Safety Controls - Pre-flight checks, SLO monitoring, auto rollback

### Governance
[governance/](governance/) - Decision-making framework

**Key idea**: Different decisions require different approval levels. Routine stuff auto-approves, critical stuff needs full governance session.

**Decision tiers**:
- ROUTINE - Auto-approved
- IMPORTANT - Notification approval
- CRITICAL - Full governance session

## File Structure

```
TorinAI/
├── core/
│   ├── agents/          # Autonomous agents (memory, planning, task execution)
│   ├── reasoning/       # Reasoning engines (abstract, neural, hypothesis)
│   ├── memory/          # Memory systems (hot/cold tier, filtering)
│   ├── learning/        # Learning systems (continuous, pattern recognition)
│   ├── security/        # Security systems (WAF, malware sandbox, threat intel)
│   ├── tools/           # Tool registry and execution
│   ├── governance/      # Governance and decision-making
│   ├── chaos/           # Chaos testing framework
│   └── database/        # Database management
│
├── config/              # Configuration files
│   ├── memory_filtering_policy.json
│   ├── chaos_config.json
│   └── governance_triggers.json
│
└── docs/                # This folder
    ├── memory_filtering.md
    ├── chaos_testing.md
    └── governance/
```

## Key Design Principles

**Upstream Intelligence** - Put smarts where context exists, not downstream

Example: Reasoning systems tag their outputs with metadata when they create them, not later when context is lost.

**O(1) Operations** - Avoid complex scoring/analysis in hot paths

Example: Memory filter checks enum values and counters, not embeddings or cross-memory comparisons.

**Explicit Structure** - Use namespaces and enums, not flat dicts and strings

Example: `metadata.criticality.decision_type == DecisionType.STRATEGIC` not `metadata["decision_type"] == "strategic"`

**Immutability** - Historical accuracy matters

Example: Once metadata is frozen, it can't be changed. Corrections are new memories, not edits.

**Fail-Safe** - Default to safe behavior on errors

Example: If memory filter errors, default to storing (fail-open). If chaos SLO violated, auto rollback (fail-safe).

**Governance Integration** - Route risky operations through approval

Example: Critical chaos experiments require full governance session, not auto-approval.

**Observability** - Log everything with rationale

Example: Every filter decision logged with rule_matched and rationale for debugging.

## Quick Links

**Memory System**:
- [memory_filtering.md](memory_filtering.md) - Filtering logic
- `core/memory/utils/memory_worthiness.py` - Metadata structure
- `core/memory/utils/memory_filter.py` - Filter engine
- `core/agents/memory_agent.py` - Storage integration

**Chaos Testing**:
- [chaos_testing.md](chaos_testing.md) - Framework overview
- `core/chaos/orchestrator.py` - Main controller
- `core/chaos/scenarios/scenario_library.py` - 20+ scenarios
- `core/chaos/adapters/` - Target system adapters

**Governance**:
- `governance/` - Full governance docs
- `core/governance/unified_governance_trigger_system.py` - Trigger system

## Common Patterns

### Adding Upstream Metadata to a New System

1. Import metadata structure:
```python
from core.memory.utils.memory_worthiness import (
    MemoryWorthinessMetadata,
    CognitionMetadata,
    NoveltyMetadata,
    # etc.
)
```

2. Generate metadata when creating output:
```python
metadata = MemoryWorthinessMetadata(
    cognition=CognitionMetadata(
        reasoning_steps=len(steps),
        complexity_score=calculate_complexity(),
        execution_time_ms=elapsed_time
    ),
    # ... other namespaces
)
```

3. Pass to memory agent:
```python
thinking_state = {
    "worthiness_metadata": metadata.to_dict()
}

await memory_agent.store_memory(
    content=result,
    reasoning_trace=steps,
    thinking_state=thinking_state
)
```

Filter handles the rest automatically.

### Adding a Chaos Scenario

1. Create scenario in `scenario_library.py`:
```python
"my_new_scenario": {
    "name": "My Test Name",
    "description": "What this tests",
    "target_system": "memory_system",
    "chaos_type": ChaosType.LATENCY,
    "injection_config": {
        "delay_ms": 300,
        "duration_seconds": 180
    },
    "hypothesis": {
        "expected_behavior": {
            "max_latency_p95_ms": 500,
            "max_error_rate": 0.01
        }
    }
}
```

2. Run via orchestrator - safety controls automatic.

## Getting Started

Start with the specific system docs:
- Working with memory? → [memory_filtering.md](memory_filtering.md)
- Setting up testing? → [chaos_testing.md](chaos_testing.md)
- Need approval logic? → [governance/](governance/)

Each doc has practical examples and key files.
