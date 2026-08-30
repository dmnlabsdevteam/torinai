# Memory Filtering System

## What It Does

Prevents trivial memories from clogging up the database. Reasoning systems tag their outputs with metadata, and the memory agent decides what's worth keeping based on simple rules.

## The Problem

Before: Memory agent stored everything, including dumb stuff like "What is the capital of France?" This bloated the database.

After: Smart filtering keeps only valuable memories like strategic decisions, deep reasoning, and novel insights.

## Architecture

```
Reasoning System → Generates Metadata → Memory Agent → Filter Evaluation → Store or Reject
```

### 1. Upstream Metadata Tagging

Reasoning systems self-tag their outputs when they create them (where context actually exists):

- **Abstract Reasoning Engine**: Tags deductive/inductive/abductive reasoning
- **Neural Bridge**: Tags neural-symbolic hybrid reasoning
- **Hypothesis Testing**: Tags experiment results

### 2. Metadata Structure

7 namespaced sections (no ambiguity):

**Cognition** - How hard did the system think?
- reasoning_steps: Number of steps taken
- complexity_score: Self-assessed difficulty (0.0-1.0)
- execution_time_ms: Time spent reasoning
- reasoning_depth: Levels of nested inference

**Novelty** - Is this new knowledge?
- is_novel: Boolean flag
- pattern_type: ROUTINE | VARIANT | EMERGENT
- synthesis_of_domains: List of domains combined

**Criticality** - Will this be needed again?
- decision_type: STRATEGIC | TACTICAL | OPERATIONAL | INFORMATIONAL
- consequence_level: NONE | LOW | MEDIUM | HIGH | CRITICAL
- reusability: NONE | LOW | MEDIUM | HIGH

**Query** - What kind of question?
- query_type: FACTUAL_LOOKUP | SIMPLE_CALCULATION | COMPLEX_REASONING | SYNTHESIS | ANALYSIS
- multi_step: Boolean
- requires_synthesis: Boolean

**Outcome** - What was produced?
- action_type: What happened
- action_summary: Human-readable description
- affected_components: What changed

**Temporal** - When did this happen?
- created_at: ISO 8601 timestamp
- session_id: Session identifier
- trigger_event: What caused this
- sequence_number: Order within session

**Justification** - Why store this?
- store_reason: Rules that matched
- decision_summary: Why it's valuable
- alternatives_considered: Other approaches
- rejected_because: Why alternatives didn't work

### 3. Filtering Rules

**Hard Store** (always keep):
- Strategic decisions
- Deep reasoning (5+ steps)
- Multi-level inference (3+ depth)
- Cross-domain synthesis
- High/critical consequence
- Novel knowledge creation
- Emergent patterns

**Hard Reject** (never keep):
- Trivial factual lookups (e.g., "What is X?" with <2 steps)
- Simple calculations with complexity <0.3
- No reusability + low consequence

**Soft Thresholds** (evaluate if no hard match):
- Complexity score >= 0.6
- Reasoning steps >= 3
- Execution time >= 100ms

### 4. O(1) Filtering

No complex scoring or embeddings needed. Just check enum values and counters:

```python
# Example: Check if strategic decision
if metadata.criticality.decision_type == DecisionType.STRATEGIC:
    return STORE

# Example: Check if trivial lookup
if (metadata.query.query_type == QueryType.FACTUAL_LOOKUP
    and metadata.cognition.reasoning_steps < 2):
    return REJECT
```

## Key Files

**Core Files**:
- `core/memory/utils/memory_worthiness.py` - Metadata dataclasses
- `core/memory/utils/memory_filter.py` - Filtering engine
- `config/memory_filtering_policy.json` - Tunable thresholds
- `core/agents/memory_agent.py` - Integration point

**Reasoning Systems** (generate metadata):
- `core/reasoning/abstract_reasoning_engine.py`
- `core/reasoning/neural_bridge.py`
- `core/reasoning/hypothesis_testing.py`

## How It Works

1. **Reasoning system finishes work** → Generates MemoryWorthinessMetadata
2. **Calls memory_agent.store_memory()** → Passes metadata in thinking_state
3. **Memory agent extracts metadata** → Deserializes from dict
4. **MemoryFilter.evaluate()** → Runs O(1) rule checks
5. **Decision made** → Store or reject with logged rationale
6. **Metadata frozen** → Prevents retroactive edits

## Calibration Layer

Randomly samples 5% of stored memories to verify accuracy:

- Checks claimed reasoning_steps vs actual trace length
- Logs warnings if mismatch > 20%
- Helps catch systems gaming the filter

## Immutability

Once metadata is frozen, it can't be changed. This prevents:
- Retroactive reinterpretation
- Rewriting history
- Losing "why" context

Corrections must be new memories, not edits to old ones.

## Configuration

Edit `config/memory_filtering_policy.json` to tune thresholds:

```json
{
  "soft_threshold_conditions": {
    "thresholds": {
      "min_complexity_score": 0.6,
      "min_reasoning_steps": 3,
      "min_execution_time_ms": 100
    }
  },
  "calibration_settings": {
    "enabled": true,
    "sample_rate": 0.05
  }
}
```

## Metrics

Track filter performance via `MemoryFilter.get_metrics()`:

- Total evaluated/stored/rejected
- Storage rate vs rejection rate
- Top rejection reasons
- Top storage reasons
- Calibration mismatches

## Examples

**STORED** - Deep reasoning:
```
Query: "Design a distributed consensus algorithm for autonomous agents"
- reasoning_steps: 7
- complexity_score: 0.85
- decision_type: STRATEGIC
- pattern_type: EMERGENT
→ ACCEPTED (rule: deep_reasoning)
```

**REJECTED** - Trivial lookup:
```
Query: "What is the capital of France?"
- reasoning_steps: 1
- query_type: FACTUAL_LOOKUP
- is_novel: false
→ REJECTED (rule: trivial_factual_lookup)
```

**STORED** - Cross-domain synthesis:
```
Query: "How can security threat detection inform continuous learning?"
- synthesis_of_domains: ["security", "learning"]
- complexity_score: 0.72
→ ACCEPTED (rule: cross_domain_synthesis)
```

## Design Principles

1. **Upstream tagging** - Intelligence where context exists
2. **O(1) filtering** - No latency impact
3. **Explicit namespacing** - No rule ambiguity
4. **Enumerations** - Deterministic decisions
5. **Immutability** - Historical accuracy
6. **Fail-open** - Default to storing on errors
7. **Observability** - Log all decisions

## What's Next

Future systems that should generate metadata:
- Task execution engine
- Cross-domain reasoner
- Tool execution layer
- Autonomous planning system

Just implement `_store_in_memory()` with metadata generation, and the filter handles the rest.
