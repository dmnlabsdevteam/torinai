# TorinAI System Reference

**Version:** Current as of 2026-03-06
**Classification:** Internal Technical Reference
**Purpose:** Authoritative, scientifically thorough documentation of all TorinAI systems, subsystems,
algorithms, equations, data structures, and control flows. Use this to evaluate what the system
is doing, what it should be doing, and where the gaps are.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Summary](#2-architecture-summary)
3. [The Brain — LLM Layer](#3-the-brain--llm-layer)
4. [The Singleton — Autonomous Coordinator](#4-the-singleton--autonomous-coordinator)
5. [Autonomous Agent Subsystems](#5-autonomous-agent-subsystems)
6. [Task Completion Protocol](#6-task-completion-protocol)
7. [Intrinsic Motivation System — Full Specification](#7-intrinsic-motivation-system--full-specification)
8. [Epistemic and Bayesian Reasoning](#8-epistemic-and-bayesian-reasoning)
9. [Hypothesis Testing System](#9-hypothesis-testing-system)
10. [Planning Engine](#10-planning-engine)
11. [Memory System](#11-memory-system)
12. [Learning and Self-Improvement](#12-learning-and-self-improvement)
13. [Meta-Learning and Bandit Policy](#13-meta-learning-and-bandit-policy)
14. [Security Systems — Full Specification](#14-security-systems--full-specification)
15. [Health and Monitoring](#15-health-and-monitoring)
16. [Governance System](#16-governance-system)
17. [Abstract Reasoning Engine](#17-abstract-reasoning-engine)
18. [Tool Registry and General Purpose Executor](#18-tool-registry-and-general-purpose-executor)
19. [Chaos Engineering](#19-chaos-engineering)
20. [Quantum Computing Layer](#20-quantum-computing-layer)
21. [Domain Knowledge System](#21-domain-knowledge-system)
22. [Integration Layer](#22-integration-layer)
23. [Database Layer](#23-database-layer)
24. [APIs and External Servers](#24-apis-and-external-servers)
25. [What the System Should Be Doing](#25-what-the-system-should-be-doing)
26. [Known Gaps and Issues](#26-known-gaps-and-issues)
27. [Master Constants and Thresholds Reference](#27-master-constants-and-thresholds-reference)

---

## 1. System Overview

TorinAI is a continuously running autonomous artificial intelligence system operating entirely on local
hardware (Apple Silicon, MPS GPU). It is organized around a single core principle: the Singleton (Torin)
is the brain, the central intelligence, and the source of truth. Every subsystem exists to serve and extend
the Singleton's capabilities.

The system is self-directed, self-improving, and self-monitoring. It runs without human instruction during
normal operation. Human involvement is required only for CRITICAL-tier governance decisions.

**Primary capabilities:**

- Continuous autonomous reasoning, planning, and task execution
- Code self-improvement: generation, static analysis, sandbox testing, safe deployment, rollback
- Multi-layer security: OS firewall, Cloudflare WAF, threat intelligence, SQL injection detection,
  anomaly monitoring, active defense
- Semantic memory with hot/cold tiering, pgvector similarity search, temporal decay
- Constitutional governance with five immutable laws and tiered approval workflows
- Cross-domain knowledge transfer and analogy discovery
- Chaos engineering for resilience testing with progressive rollout and SLO-gated rollback
- Hybrid quantum-classical computation (QAOA, QNN, VQE)
- Multi-source research with automatic API routing
- Slack-based governance notifications and human approval workflows
- Bayesian belief tracking, hypothesis testing, epistemic state management

**Runtime environment:**

- Python 3.11, asyncio single event loop
- Qwen2.5-VL-32B-Q8_0 (primary brain, ~17GB, MPS/CUDA/CPU)
- Qwen3-8B-Q4_K_M (lightweight brain, ~5GB, fast tasks)
- PostgreSQL + pgvector (primary database, 3 schemas)
- llama-cpp-python (local inference runtime)
- sentence-transformers/all-MiniLM-L6-v2 (384-dim embeddings)

---

## 2. Architecture Summary

```
+---------------------------------------------------------------------------+
|                          SINGLETON (TORIN)                                |
|                      Autonomous Coordinator                               |
|               Single asyncio event loop, 2-second cycle                  |
+---------------------------------------------------------------------------+
         |           |          |          |         |          |
    +----+----+ +----+----+ +---+---+ +----+---+ +---+----+ +--+-----+
    |  Brain  | | Memory  | |Security| |Learning| | Health | |Govern- |
    |32B + 8B | |Hot/Cold | |Layers  | |& Improv| |Monitor | | ance   |
    +---------+ +---------+ +--------+ +--------+ +--------+ +--------+
         |                       |          |
    +----+----+            +-----+----+ +---+------+
    | Tools   |            | Reasoning| | Quantum  |
    | 300+    |            | Engines  | | Hybrid   |
    +---------+            +----------+ +----------+
```

**Coordination cycle:** 2 seconds
**Motivation refresh:** Every 5 cycles (~10 seconds)
**System awareness:** Every 30 cycles (~1 minute)
**Frontier foresight:** Maximum once per 10 minutes (600-second cache)

**Key architectural rules:**
- Single asyncio event loop for all agent coroutines (no ThreadPoolExecutor for agents)
- DB pool bound to main loop — no cross-loop asyncpg access
- `get_llm_service()` and `get_lightweight_llm_service()` are SYNCHRONOUS — never await them
- `execute_query()` auto-fetches for SELECT-like queries by default (override: `TORINAI_DB_AUTOFETCH_SELECT=0`)

---

## 3. The Brain — LLM Layer

### 3.1 Unified LLM Service

**File:** `core/services/unified_llm.py`
**Model:** Qwen2.5-VL-32B (32 billion parameters, Q8_0 quantization)
**Context window:** 21,000 tokens
**Device:** MPS (Apple Silicon primary), CUDA, CPU fallback

**Inference architecture:**

All GPU calls flow through a single serializing queue. The `_inference_worker` coroutine is the
ONLY code that touches the Llama model object. This eliminates GPU race conditions without locks.

```
Request → asyncio.Queue → _inference_worker → Llama model → Result
                               (sole caller)
```

**_InferenceJob dataclass:**
```
prompt: str
max_tokens: int
temperature: float
stop: List[str]
system_prompt: Optional[str]
image_data: Optional[bytes]         # Vision input
future: asyncio.Future              # Result delivery
agent_type: str
```

**Cross-loop submission pattern:**
When a caller's event loop differs from the main loop (which no longer occurs since ThreadPoolExecutor
was removed, but the code handles it for safety):

```
running_loop = asyncio.get_running_loop()
if running_loop is not self._main_loop:
    sync_future = concurrent.futures.Future()
    asyncio.run_coroutine_threadsafe(queue.put(job), self._main_loop)
    return await loop.run_in_executor(None, sync_future.result)
else:
    await self._queue.put(job)
    return await job.future
```

**Agent type system prompts (hardcoded):**

| Agent Type | Focus |
|------------|-------|
| reasoning | Deep analytical thinking |
| planning | Goal decomposition and strategy |
| execution | Precise task completion |
| learning | Knowledge acquisition |
| memory | Information storage and retrieval |
| security | Threat analysis and defense |
| research | Information gathering and synthesis |
| analysis | Data interpretation |
| creative | Novel solution generation |
| code | Software development and optimization |

**Singleton accessor:** `get_llm_service()` — module-level, synchronous, never await.

**Model paths (configurable):**
- Unified brain model: env `LOCAL_MODEL_PATH` or config `model_path`
- Vision projector: env `MMPROJ_PATH` or config `mmproj_path`
- Models base dir autodiscovery: env `TORINAI_MODELS_DIR` (defaults to `./models` at repo root)

---

### 3.2 Lightweight LLM Service

**File:** `core/services/lightweight_llm.py`
**Model:** Qwen3-8B-Q4_K_M (8 billion parameters)
**Purpose:** Low-latency sub-tasks offloaded from the 32B brain

**Designated use cases:**
- Context compression (summarize conversation history)
- Memory consolidation
- JSON classification and routing decisions
- Security content screening
- Health status text generation
- Conversation summarization

**GPU configuration:**
- Layers offloaded: 36 (all layers, both CUDA and MPS)
- No memory-constraint tuning

**Queue architecture:** Parallel batch queue plus single-request queue (legacy duplication — both
active and competing for requests).

**Singleton accessor:** `get_lightweight_llm_service()` — synchronous, never await.

**Model path:** Loaded from `LIGHTWEIGHT_MODEL_PATH` environment variable.

---

## 4. The Singleton — Autonomous Coordinator

**File:** `core/agents/autonomous/autonomous_coordinator.py`

The Singleton is the master orchestrator. It owns all subsystems, controls when they run, and
is accountable for ecosystem health. It must:

- Verify all subsystems are functional at runtime
- Restart degraded subsystems when detected
- Run security audits and execute remediation
- Drive self-improvement cycles
- Maintain memory, knowledge, and learning state
- Enforce constitutional governance on all autonomous actions

### 4.1 Initialization Dependencies

**Required (raises ValueError if absent):**
- `torin_brain` — LLM service instance

**Conditionally required:**
- `health_monitor` — raises RuntimeError if configured but fails to start

**Injected externally (from main.py):**
- `asi_self_improvement`
- `monitoring_coordinator`
- `system_watchdog`
- `recovery_manager`

### 4.2 Full Subsystem Inventory

| Attribute | Type | Initialized By |
|-----------|------|----------------|
| `self.llm` | UnifiedLLMService | `get_llm_service()` at init |
| `self.perception` | PerceptionManager | Auto-created |
| `self.planning` | PlanningEngine | Auto-created |
| `self.task_queue` | TaskQueue | Auto-created |
| `self.task_pool` | TaskExecutionPool | Auto-created |
| `self.intrinsic_motivation` | IntrinsicMotivationSystem | `get_intrinsic_motivation_system()` |
| `self.directive_system` | DirectiveSystem | Auto-created |
| `self.learning` | UnifiedLearningSystem | Injected |
| `self.asi_self_improvement` | EnhancedASISelfImprovement | Injected by main.py |
| `self.security_audit_worker` | SecurityAuditWorker | Auto-created |
| `self.security_controller` | SecurityController | `get_security_controller()` |
| `self.health_monitor` | HealthMonitor | Provided or auto-created |
| `self.monitoring_coordinator` | MonitoringCoordinator | Auto-created |
| `self.system_watchdog` | SystemWatchdog | Injected |
| `self.recovery_manager` | RecoveryManager | Injected |
| `self.governance` | UnifiedGovernanceTriggerSystem | `get_unified_governance()` |
| `self.constitution` | SingletonConstitution | Auto-created |
| `self.abstract_reasoning` | AbstractReasoningEngine | Auto-created |
| `self.quantum_reasoning` | QuantumReasoningSystem | Auto-created (optional) |
| `self.neural_bridge` | NeuralBridge | Auto-created |
| `self.causal_analyzer` | CausalFeedbackAnalyzer | Auto-created |
| `self.meta_learner` | MetaLearner | Auto-created |
| `self._frontier_foresight` | FrontierForesightPredictor | Auto-created |
| `self.improvement_monitor` | ImprovementMonitor | Auto-created |
| `self.extrinsic_manager` | ExtrinsicTaskManager | Disabled by default |
| `self.slack_notifier` | SlackNotifier | Auto-created |
| `self.domain_registry` | DomainRegistry | Auto-created |
| `self.cross_domain_reasoner` | CrossDomainReasoner | Auto-created |
| `self.memory` | MemorySystem | Provided via config |

### 4.3 Coordination Cycle — Full Specification

**Cycle interval:** `cycle_interval_seconds` (default: 2.0)
**Exploration budget:** `exploration_budget` (default: 0.30)
**Awareness interval:** Every 30 cycles (~60 seconds)
**Motivation interval:** Every 5 cycles (~10 seconds)
**Curiosity optimization threshold:** 0.7

```
WHILE self.active:

  cycle_count += 1

  PHASE 1: Motivation refresh (every 5 cycles)
    - calculate_motivation() across 7 dimensions
    - Store _current_motivation state

  PHASE 2: System awareness (every 30 cycles)
    - discovery.scan(quick=True)
    - behavioral.observe(duration_s=2.0)
    - env_state.refresh()

  PHASE 3: Task dispatch
    queued_task = await task_queue.get_next_task(timeout=0.1)
    IF queued_task:
      extrinsic_batch.append(queued_task)
      WHILE len(batch) < max_parallel:
        more = task_queue.try_get_task()
        IF none: BREAK
        extrinsic_batch.append(more)

    IF extrinsic_batch:
      idle_count = 0
      IF single task: execute directly
      ELSE: task_pool.execute_batch(pool_spec)
      IF random() < exploration_budget:
        await _run_exploration_cycle()
    ELSE:
      idle_count += 1
      await _run_exploration_cycle()     # <-- CURRENT BEHAVIOR (see gap in Section 25)

  PHASE 4: Curiosity optimization
    IF curiosity >= 0.7 AND last_optimization > 30min:
      await _curiosity_driven_optimization()

  await asyncio.sleep(cycle_interval)
```

### 4.4 Constitutional Framework — Five Immutable Laws

**File:** `core/agents/autonomous/singleton_constitution.py`

```
Law 1: Human Autonomy Preservation
  Requirements:
  - Preserve human control and override capability at all times
  - Maintain decision authority for humans in critical domains
  - Provide halt capability on demand
  Compliance: autonomous mode → 0.95, resource_usage > 0.9 → 0.90
  Minimum: 70% | System minimum: 85% average

Law 2: Transparency and Explainability
  Requirements:
  - All decisions must be interpretable
  - Enable human understanding of reasoning
  - No behavior obscuring
  - Provide clear explanations for actions
  Compliance: 0.8 if no performance_metrics, 1.0 if metrics present

Law 3: Harm Prevention
  Requirements:
  - No physical or psychological harm
  - No deception
  - No compromise of safety mechanisms
  - Safety takes priority over optimization goals

Law 4: Value Alignment
  Requirements:
  - Align with human values and ethics
  - Respect human rights and dignity
  - Serve human interests
  - Do not optimize goals that conflict with human values

Law 5: Containment and Control
  Requirements:
  - Maintain operational boundaries
  - Preserve shutdown and rollback capability
  - No circumvention of safety measures
  - No self-modification that bypasses governance
  - Maintain resource limits
```

**Compliance thresholds:**
- Per law minimum: 70%
- System average minimum: 85%
- Drift severity levels: NONE, MINOR, MODERATE, SIGNIFICANT, CRITICAL

---

## 5. Autonomous Agent Subsystems

### 5.1 General Purpose Executor

**File:** `core/agents/autonomous/general_purpose_executor.py`

The executor is the bridge between task descriptions and actual work. It formats tasks as LLM
prompts, runs a multi-turn agent loop, executes tools, and persists results.

**Token budget management:**

```
Total context window: 15,360 tokens

Budget allocation:
  system_prompt_tokens: len(prompt.split())
  tool_description_tokens: len(tools.split())
  safety_margin: 100 tokens
  available_for_generation: max(0, 15360 - system - tools - 100) * 0.90

Per iteration recalculation:
  conversation_tokens = token_count(history)
  usage_pct = (conversation_tokens / 15360) * 100
  should_compress = (usage_pct > compression_threshold)

  IF compress:
    keep last 3 messages
    replace middle with compressed summary
    available = max(100, 15360 - new_count - safety_margin)

max_iterations = min(30, max(10, 1 + int(available / 500)))
```

**Memory retrieval — two-pass strategy:**

```
Pass 1: Tag-based retrieval
  tags = {f"task_{task_id}"}
  limit = 3 memories

Pass 2: Semantic search
  query = task.description[:200]
  min_similarity = 0.70
  limit = 5, deduplicate = True

Merge and budget:
  MAX_MEMORY_TOKENS = 800
  per-memory truncation: content[:200]
  stop appending when budget exhausted
```

**Tool selection — capability inference:**

```
Step 1: Infer capabilities from task description
  threshold = 0.5 (primary)
  threshold = 0.3 (fallback if no results at 0.5)

Step 2: Always include core categories
  core_categories = ['filesystem', 'execution', 'system']

Step 3: Exclude AgentSO connector tools
  Excluded prefixes: virustotal_, crowdstrike_, misp_, splunk_,
    elastic_, github_, snyk_, sonarqube_, qradar_, arcsight_,
    logrhythm_, shodan_, alienvaultotx_, threatconnect_,
    recordedfuture_, thehive_, shuffle_, qualys_,
    awssecurityhub_, azuresecuritycenter_, pagerduty_, restapi_
```

**Weighted tool category scoring (16 categories):**

Each category has keywords with individual weights. The system scores all tool categories
by summing keyword weights found in the task description, selecting the highest-scoring categories.

**Agent loop:**

```
FOR iteration = 1 to max_iterations:
  1. Compress context if tokens > threshold
  2. Call LLM via neural bridge (ReasoningMode.NEURAL)
  3. Parse JSON response (retry up to 2 times on parse error)
  4. Check parsed['status']:
     IF 'proposing_completion':
       Parse CompletionProposal from output
       Generate TaskCompletionSpec (or retrieve from task)
       Run verify_completion() through 9 verification layers
       
       IF state == VERIFIED:
         Mark task VERIFIED, capture memory, return success
       ELIF state == REVISION_REQUESTED:
         Inject revision feedback to conversation
         Continue to next iteration
       ELIF state == PARTIALLY_COMPLETE:
         Budget exhausted but ≥70% criteria met
         Return partial success
       ELIF state == BLOCKED:
         Dependencies not met, return blocked
       ELSE (FAILED):
         Return failure with issues and recommendations
     ELSE:
       Execute tool_calls
       Track failures per tool (max 2 failures before warning prompt)
       Append results to conversation
  5. IF no tool_calls AND not complete: BREAK (LLM confused)

Tool output truncation: MAX_OUTPUT_CHARS = 1000
```

**Drift-aware iteration reduction:**

When completion drift is detected (rolling failure rate > 40%), max_iterations is reduced:
```
IF drift_metrics.is_degrading:
  IF failure_rate > 50%:
    max_iterations *= 0.5  # 50% reduction
  ELSE:
    max_iterations *= 0.7  # 30% reduction
  max_iterations = max(5, max_iterations)  # Never below 5
```

**Failure investigation prompt (triggered at 2+ failures per tool):**

When a tool fails twice consecutively, the executor injects a mandatory investigation prompt
instructing the LLM to diagnose root cause before retrying rather than executing blind retries.

---

### 5.2 Task Queue

**File:** `core/agents/autonomous/task_queue.py`

**Priority levels:** CRITICAL (3) > HIGH (2) > MEDIUM (1) > LOW (0)
**Tiebreaker:** Sequence number (monotonic counter)
**Max queue size:** 1000
**Underlying structure:** `asyncio.PriorityQueue`

**Governance trigger:**
```
Window: 5 minutes
Threshold: 20+ autonomous tasks in window
Exempted sources: EXTRINSIC_JSON, API, MANUAL

IF autonomous_tasks_in_window >= 20:
  evaluate_action(ActionCategory.TASK_CREATION)
```

**User task exemption logic:**
```
is_exempt = task.source in [TaskSource.EXTRINSIC_JSON,
                             TaskSource.API,
                             TaskSource.MANUAL]
IF is_exempt: skip governance check
```

**Requeue logic:**
```
IF retry_count < max_retries:
  requeue_task() → True (re-added to queue)
ELSE:
  requeue_task() → False (caller must call mark_failed())
```

**Critical fix applied:** Coordinator checks `requeue_task()` return value. If False,
immediately calls `mark_failed()` to clean up task and allow idle state detection.

---

### 5.3 Task Execution Pool

**File:** `core/agents/autonomous/task_execution_pool.py`

**Current implementation:** `asyncio.gather()` via semaphore-controlled `execute()` method.
All tasks run as coroutines on the coordinator's event loop. ThreadPoolExecutor removed.

```
async def execute_batch(tasks):
  async def _run_one(task_id, func, args, kwargs):
    try:
      result = await self.execute(task_id, func, *args, **kwargs)
      return (task_id, True, result)
    except Exception as exc:
      return (task_id, False, exc)

  return list(await asyncio.gather(*[
    _run_one(tid, f, args, kwargs)
    for tid, f, args, kwargs in tasks
  ]))
```

**Semaphore:** `max_concurrent` slots (default from `coordinator_config.max_parallel_tasks`)

---

### 5.4 Directive System

**File:** `core/agents/autonomous/directive_system.py`

**4 directive categories:** goal_prioritization, resource_allocation, learning_strategy,
exploration_balance

**Cache TTL:** 60 seconds (hardcoded)

**Directive application — parameter merging:**
```
merged_params = {}
FOR directive IN active_directives[category]:
  merged_params.update(directive.parameters)
  # Later directives override earlier ones (no conflict detection)
RETURN merged_params
```

**Performance dimensions tracked:**
- outcome_quality
- intrinsic_reward
- constitutional_alignment
- system_health_impact

**Components:** DirectiveManager (CRUD), DirectiveABTesting (variant testing),
DirectiveEvolutionEngine (performance tracking over time)

---

## 6. Task Completion Protocol

**File:** `core/agents/autonomous/completion_protocol.py`

**Core Principle:** Completion is a SYSTEM PROPERTY, not a model output. The LLM cannot
mark tasks as complete — it can only propose completion. The system verifies proposals
against formal criteria before marking VERIFIED.

### 6.1 Completion State Machine

```
CompletionState:
  PLANNED              → Task defined, not started
  IN_PROGRESS          → Execution underway
  AWAITING_VERIFICATION → LLM proposed completion
  REVISION_REQUESTED   → System feedback for iterative correction
  VERIFIED             → System confirmed all criteria met
  FAILED               → Unrecoverable failure or budget exhausted with <70% criteria
  BLOCKED              → Dependency not met (child tasks or dependencies)
  PARTIALLY_COMPLETE   → Budget exhausted but ≥70% criteria met

State Transitions:
  PLANNED → IN_PROGRESS (execution starts)
  IN_PROGRESS → AWAITING_VERIFICATION (LLM outputs status: "proposing_completion")
  AWAITING_VERIFICATION → REVISION_REQUESTED (verification issues, iterations remain)
  REVISION_REQUESTED → IN_PROGRESS (agent addresses feedback)
  AWAITING_VERIFICATION → VERIFIED (all criteria pass, score ≥ threshold)
  AWAITING_VERIFICATION → FAILED (validation failed, no retries)
  IN_PROGRESS → BLOCKED (dependency not met)
  BLOCKED → IN_PROGRESS (dependency resolved)

CRITICAL: Only TaskCompletionValidator can transition to VERIFIED.
```

### 6.2 Verification Layers (11 Layers)

```
Layer 1: Premature Completion Detection
  - remaining_risks must be explicitly set (None = omitted = BLOCKED)
  - open_questions must be explicitly set
  - assumptions must be explicitly set
  - Non-empty remaining_risks or open_questions → BLOCKED
  - Tracks _fields_explicitly_set to distinguish [] from omitted

Layer 2: Dependency Graph Verification
  - All dependency_task_ids must be in VERIFIED state
  - Returns BLOCKED if any dependency not verified

Layer 2.5: Child Task Closure Enforcement
  - All child_task_ids must be in VERIFIED state
  - Parent cannot complete if any child is IN_PROGRESS, AWAITING_VERIFICATION, or PLANNED

Layer 3: Artifact Verification
  - Required artifacts must exist on filesystem
  - Claimed files_created and files_modified must exist
  - SHA256 hash verification if artifact_hashes provided
  - Score: verified_count / required_count

Layer 3.5: Reality Verification  ← NEW (reality_verifier.py)
  - Check 1 — FilesystemDiff: path claims in output doc vs os.path.exists()
      → validates_artifact_content(): .json {} / [] / <10 bytes = hard fail
      → .py files <50 bytes = hard fail
  - Check 2 — DependencyScan: library claims vs importlib.util.find_spec()
      → _scan_files_for_imports(): reads actual .py files for import statements
        (catches indirect phrasing like "compatible with TFF")
  - Check 3 — ProcessInspection: service claims vs psutil process list
      → detects both strong claims ("successfully integrated") and
        weak claims (service noun + action verb in same sentence)
  - Check 4 — ToolLogAnalysis: EXECUTION tasks must produce ≥1 non-trivial
      artifact (≥50 bytes, non-report). Catches run_python("print('hello')")
      with zero real output.
  - Check 5 — RuntimeProbes: TCP port probes for claimed running services
      (always soft/warning — services may be remote)
  - artifact_score = (artifact_score + reality.score) / 2
  - Hard failures extend hard_gate_failures

Layer 3.6: Causal Traceability Gate  ← NEW (causal_traceability.py)
  - Formally verifies: ∀ claimed artifact A, ∃ tool_call T that produced A
  - Link strength classification:
      strong — write_file/create_file with exact normalized realpath match
               AND file exists on disk
      weak   — code tool with basename in output/params AND file exists on
               disk AND file mtime >= tool_call_timestamp
      none   — untraced / orphan (blocks VERIFIED on EXECUTION tasks)
  - Hash gate: if agent supplies artifact_hashes, SHA256 must match disk
  - Path normalization: os.path.realpath() prevents ./file.py vs file.py bypass
  - Stdout rejection: weak link requires disk evidence, never stdout alone
      (closes run_python("print('model.py created')") false-positive)
  - Provenance graph: Tool → Artifact → Tool DAG built for full lineage
  - Downstream usage tracked: written-but-never-read artifacts emit warning
  - Score: strong_links / total_artifacts (weak links = 0, no inflation)
  - Hard failures extend hard_gate_failures on EXECUTION/SECURITY tasks

Layer 4: Code Validation
  - Python syntax check via compile()
  - Runs pytest -q --tb=short -x for test validation
  - Returns pass rate as score (passed / total tests)

Layer 5: Research Validation
  - Minimum 3 sources consulted
  - Minimum 2 key findings documented
  - Summary length ≥ 100 characters

Layer 6: Acceptance Criteria Verification
  - Each AcceptanceCriterion evaluated
  - Hard gates must pass regardless of weighted score
  - Types: artifact_check, output_present, metric_threshold, test_result, lint_check, custom
  - Score: passed_criteria / total_criteria

Layer 7: Goal Alignment Check
  - Uses Critic LLM (8B model) if available
  - 4-dimension rubric: objective_match, completeness, specificity, evidence
  - Fallback: Structured rubric with keyword coverage + artifact presence
  - Weighted average of dimensions

Layer 8: Consistency Check
  - Contradiction detection (failure + success language)
  - Cross-field consistency (files_created mentioned in summary)
  - Confidence sanity (high confidence with risks → penalty)
  - Output schema validation (required fields, types)
  - Numerical bounds check (confidence ∈ [0,1])

Layer 9: Resource Budget Check
  - Time budget: elapsed_seconds vs max_time_seconds
  - Token budget: tokens_used vs max_tokens
  - Iteration budget: iterations vs max_iterations
  - Penalty: min(0.5, overage * 0.5) for time
```

### 6.3 Completion Score Model

```
Pre-computation (before weighted sum):

  artifact_score is computed in two stages:
    Stage A: Layer 3 artifact check  → artifact_score_raw
    Stage B: Layer 3.5 reality check → reality_score
    Final:   artifact_score = (artifact_score_raw + reality_score) / 2

  Layer 3.6 causal score feeds into artifact_score independently:
    causal_score = strong_links / total_claimed_artifacts
    (weak links contribute 0, hash mismatches force 0 for that artifact)

CompletionScore = weighted sum of 5 factors:

  artifact_score       × 0.30  (filesystem proof + reality + causal chain)
  validation_score     × 0.30  (tests pass, lint clean, criteria met)
  consistency_score    × 0.15  (no contradictions, valid schema)
  goal_alignment_score × 0.15  (output matches objective)
  resource_adherence   × 0.10  (within budget)

total_score = Σ(factor × weight)

Thresholds:
  min_completion_score = 0.85 (default, 0.80 for RESEARCH tasks)
  min_confidence = 0.70

Decision Logic:
  IF hard_gate_failures:
    state = REVISION_REQUESTED
  ELIF not all(criteria_results.values()):
    state = REVISION_REQUESTED
  ELIF resource_score < 0.5 AND criteria_pass_ratio < 0.70:
    state = FAILED (budget exhausted, barely did anything)
  ELIF resource_score < 0.5 AND criteria_pass_ratio >= 0.70:
    state = PARTIALLY_COMPLETE (good effort, ran out of budget)
  ELIF total_score >= min_completion_score AND confidence >= min_confidence:
    state = VERIFIED
  ELSE:
    state = REVISION_REQUESTED
```

### 6.4 Hard Gate System

Acceptance criteria can be marked as `hard_gate=True`. Hard gates MUST pass regardless
of the weighted completion score. A task cannot be VERIFIED if any hard gate fails.

```
Default hard gates by task type:

EXECUTION:
  - "Code executes without errors" (hard_gate=True)
  - "No syntax errors" (hard_gate=True)

RESEARCH:
  - "Key findings documented" (hard_gate=True)

ANALYSIS:
  - "Insights generated" (hard_gate=True)

PLANNING:
  - "Action steps defined" (hard_gate=True)
```

### 6.5 Completion Drift Detection

Monitors rolling verification success rate to detect systemic degradation:

```
Parameters:
  drift_window_minutes = 60
  max_failure_rate = 0.40 (40%)
  min_samples_for_drift = 5

Metrics computed:
  failure_rate = failures / total_in_window
  avg_score = mean(scores_in_window)
  score_trend = second_half_avg - first_half_avg

  is_degrading = failure_rate > 0.40 OR score_trend < -0.1

Actions when degrading:
  - Log warning with recommendation
  - Reduce max_iterations by 30-50%
  - Expose via get_drift_status() for monitoring

Recommendations:
  >60% failure rate: "CRITICAL: Reduce task complexity immediately"
  >40% failure rate: "WARNING: Consider reducing max_tokens"
  score_trend < -0.15: "Score declining rapidly, review task types"
```

### 6.6 Revision Feedback Loop

When state = REVISION_REQUESTED, structured feedback is injected:

```
VerificationResult.get_revision_prompt():

  REVISION REQUIRED - Your completion proposal was rejected.

  HARD GATE FAILURES (must fix):
    ❌ No syntax errors
    ❌ Code executes without errors

  ISSUES TO ADDRESS:
    • Criterion not met: Key findings documented
    • Insufficient sources: 1 < 3

  CURRENT SCORE: 0.62 (need ≥0.85)
  SCORE BREAKDOWN:
    - Artifact: 0.80
    - Validation: 0.50
    - Consistency: 0.70
    - Goal Alignment: 0.65
    - Resources: 1.00

  RECOMMENDATIONS:
    → Fix validation errors before completion
    → Ensure output directly addresses task objective
```

### 6.7 LLM Output Format

The LLM must output `"status": "proposing_completion"` (NOT `"complete"`):

```json
{
  "status": "proposing_completion",
  "summary": "Implemented X by doing Y...",
  "outputs": {...},
  "remaining_risks": [],
  "open_questions": [],
  "assumptions": ["Assumed Python 3.11+"],
  "files_created": ["path/to/file.py"],
  "files_modified": ["path/to/other.py"],
  "artifact_hashes": {
    "path/to/file.py": "sha256..."
  },
  "confidence": 0.85
}
```

**Field presence rules:**
- `remaining_risks`: MUST be present. `null` or `[]` = explicitly empty. Omitted = BLOCKED.
- `open_questions`: MUST be present. Same rules.
- `assumptions`: MUST be present. Same rules.
- Non-empty `remaining_risks` or `open_questions` → verification BLOCKED.

### 6.8 Reality Verification Layer (Layer 3.5)

**File:** `core/agents/autonomous/reality_verifier.py`

**Root cause this addresses:** The original output gate was satisfied by writing a markdown summary
report to the iCloud output directory. The LLM verifier scored report quality (grammar, structure,
claim phrasing) — not environment truth. This allowed systematic fabrication: services claimed as
"successfully integrated" with no matching process, libraries claimed as dependencies that weren't
installed, IPFS contracts claimed as created when only a 846-byte stub existed.

**Five environment-state checks:**

```
Check 1 — FilesystemDiff
  Collects: files_created, files_modified, backtick paths in output doc,
            "saved to X" patterns, claimed_outputs values
  For each path:
    - os.path.exists() → hard fail if missing (EXECUTION/SECURITY tasks)
    - _validate_artifact_content():
        .json with content {}, [], null, or <10 bytes → hard fail
        .py files <50 bytes → hard fail
        Any other file <20 bytes → hard fail

Check 2 — DependencyScan
  Extracts library keywords from task description + proposal text
  Uses _LIB_MODULE_MAP (30+ entries keyword → Python module name)
  importlib.util.find_spec() → hard fail for EXECUTION use-claims with
  uninstalled libraries
  Also: _scan_files_for_imports() reads actual .py files in files_created
  and extracts import statements — catches "compatible with TFF" phrasing
  even when keyword not in prose

Check 3 — ProcessInspection
  Detects both:
    Strong: "successfully integrated", "deployed", "running" + service name
    Weak:   service noun + action verb in same sentence (regex: _action_verb_re)
  Cross-references psutil.process_iter() + _SERVICE_PROCESS_MAP (15 services)
  Always soft/warning (services may be remote)

Check 4 — ToolLogAnalysis
  Reads tool_execution_logs from execution_context
  Hard fail: EXECUTION task with 0 code-execution tool calls
  Hard fail: EXECUTION task ran code but all produced files are <50 bytes
             or only the iCloud report
  Hard fail: files_created entry has no write_file backing AND doesn't
             exist on disk
  Soft: non-EXECUTION task claims "implemented/deployed" but no code tools ran

Check 5 — RuntimeProbes
  Probes _SERVICE_PORT_MAP (14 services → TCP ports) with 0.5s timeout
  Always soft/warning only
```

**Wiring:**
```python
# completion_protocol.py — LAYER 3.5
_reality = self.reality_verifier.verify(
    proposal, task_description, task_type,
    tool_results=execution_context["tool_execution_logs"],
    output_doc_paths=execution_context["output_doc_paths"],
)
if _reality.hard_failures:
    hard_gate_failures.extend(f"[REALITY] {f}" for f in _reality.hard_failures)
artifact_score = (artifact_score + _reality.score) / 2
```

**execution_context enrichment** (`general_purpose_executor.py`):
```python
"tool_execution_logs": tool_results,
"output_doc_paths": [
    tr.get("parameters", {}).get("path", "")
    for tr in tool_results
    if tr.get("tool") == "write_file" and tr.get("success")
],
```

### 6.9 Causal Traceability Gate (Layer 3.6)

**File:** `core/agents/autonomous/causal_traceability.py`

**Formal specification:**
```
∀ claimed artifact A:
  ∃ tool_call T  such that T produced A   (filesystem evidence required)
  ∃ tool_output O such that O supports A   (stdout alone is not sufficient)
```

**Why this is necessary beyond Layer 3.5:**
Reality verification asks: "Is the environment state true?"
Causal traceability asks:  "Did the agent actually CAUSE that state?"

Without this, an agent can:
- Run unrelated tools to satisfy the code-execution hard gate
- Claim credit for pre-existing files it never touched
- Provide a correct SHA256 of a file it didn't create
- Game weak links via stdout (e.g. `run_python("print('model.py created')")`)

**Link strength rules:**
```
strong — write_file/create_file with exact os.path.realpath() path match
         AND file confirmed on disk
         → counts toward score

weak   — code tool with basename mention in params/output
         AND file confirmed on disk
         AND file mtime >= tool_call_timestamp
         (stdout-only mentions → rejected; file must independently exist)
         → warning only, contributes 0 to score

none   — no verifiable connection
         → hard fail for EXECUTION/SECURITY tasks
         → warning for RESEARCH/ANALYSIS/PLANNING
```

**Hash gate:** If `artifact_hashes` is provided in the proposal, SHA256 of disk
content must match. Mismatch → hard fail regardless of task type.

**Path normalization:** All path comparisons use `os.path.realpath()`. Prevents
`./file.py` vs `file.py` vs `/abs/path/file.py` hash bypass.

**Provenance graph:** Full `Tool → Artifact → Tool` DAG built for lineage verification.
`ProvenanceGraph.summary()` included in result detail for auditability.

**Downstream usage tracking:** Artifacts written but never read by any subsequent
tool call emit a warning (`"artifact written but never consumed"`).

**Score formula:** `strong_links / total_claimed_artifacts`
Weak links deliberately contribute 0. Multiple weak links cannot inflate score.

**Blind spots this eliminates:**

| Attack vector | Defense |
|---|---|
| `run_python("print('model.py created')")` | Weak link requires disk mtime proof, not stdout |
| `write_file("dashboard.json", "{}")` | Layer 3.5 rejects <10-byte JSON artifacts |
| Pre-existing file claimed as newly created | mtime gate: file must postdate tool call |
| `./file.py` vs `file.py` hash key bypass | `os.path.realpath()` normalization |
| 3 weak links → score 0.6 | Score = strong_only / total, weak = 0 |

---

## 7. Intrinsic Motivation System — Full Specification

**File:** `core/agents/autonomous/intrinsic_motivation.py`

### 6.1 Data Structures

**MotivationDimension (7 dimensions):**
```
CURIOSITY  = "curiosity"    # Novel exploration drive
COMPETENCE = "competence"   # Skill improvement drive
NOVELTY    = "novelty"      # New experience drive
MASTERY    = "mastery"      # Deep understanding drive
AUTONOMY   = "autonomy"     # Self-direction drive
SOCIAL     = "social"       # Collaboration drive
IMPACT     = "impact"       # Meaningful change drive
```

**MotivationWeights (default values):**
```
curiosity:  1.20   # Highest priority
autonomy:   1.00
competence: 0.90
social:     0.90
novelty:    0.85
impact:     0.80
mastery:    0.70   # Lowest priority
```

**MotivationProfile:**
```
dimensions: Dict[str, float]      # Current 7-dim scores
weights: MotivationWeights
total_intrinsic_reward: float = 0.0
influence_percentage: float = 0.60  # 60% influence on self-improvement
last_updated: Optional[datetime]
history: List[Dict]
```

**GoalEmbedding:**
```
description: str
embedding: np.ndarray              # 384-dimensional vector
theme: str
component: str
abstraction_level: str             # low / medium / high
objective_type: str                # explore / optimize / fix / learn / audit
timestamp: datetime
repeat_count: int = 0
```

**MutationDimensions:**
```
component: str
abstraction_level: str
objective_type: str
time_horizon: str                  # immediate / short / long
```

### 6.2 Dimension Scoring Algorithms

**CURIOSITY:**
```
baseline = 0.5
if perception has novel_elements or unknown_patterns:
  novelty_score = 0.8
if goal contains ["explore", "discover", "investigate", "learn"]:
  novelty_score = max(novelty_score, 0.7)
return min(1.0, novelty_score)
```

**COMPETENCE:**
```
baseline = 0.5

if recent_tasks exist:
  success_rate = successful / total
  0.60-0.80 success rate → 0.8  (optimal challenge)
  0.40-0.60 success rate → 0.7  (challenging but achievable)
  > 0.80 success rate   → 0.4  (too easy, reduce motivation)
  < 0.40 success rate   → 0.6  (very challenging)

if DB stats available (total_attempts >= 5):
  db_score = f(db_success_rate, avg_confidence)
  db_score = max(0, min(1, db_score * 0.8 + db_conf * 0.2))
  return (baseline * 0.6) + (db_score * 0.4)

return baseline
```

**NOVELTY:**
```
baseline = 0.5
if perception.confidence < 0.6:
  novelty_score = 0.7
novel_goals = count(goals with expected_novelty > 0.6)
if novel_goals > 0:
  novelty_score = max(novelty_score, 0.6 + novel_goals * 0.1)
return min(1.0, novelty_score)
```

**MASTERY:**
```
baseline = 0.5
if goal contains ["master", "understand", "deep", "comprehensive"]:
  baseline = 0.8
complex_tasks = count(tasks with type in ["analysis", "synthesis", "research"])
if complex_tasks > 2:
  baseline = max(baseline, 0.7)
return min(1.0, baseline)
```

**AUTONOMY:**
```
mode == "autonomous"   → 0.9
mode == "supervised"   → 0.4
mode == "maintenance"  → 0.3
default                → 0.7
```

**SOCIAL:**
```
baseline = 0.4
if user_interactions or collaboration_tasks: baseline = 0.7
if goal contains ["help", "collaborate", "communicate", "share"]: return 0.8
return baseline
```

**IMPACT:**
```
baseline = 0.5
high_impact_tasks = count tasks with significant improvement results
if high_impact_tasks > 0: baseline = 0.6 + high_impact_tasks * 0.1

if DB stats (total_attempts >= 10):
  failure_rate = failures / attempts
  failure_rate >= 0.4: baseline = max(baseline, 0.8)  (much to improve)
  failure_rate <= 0.1: baseline = min(baseline, 0.6)  (very stable)

if goal contains ["improve", "optimize", "enhance", "upgrade", "impact"]:
  baseline = max(baseline, 0.7)
return min(1.0, baseline)
```

### 6.3 Total Reward Formula

```
total = sum(dimension_score[d] * weight[d] for d in 7 dimensions)
total_weight = sum(all weights) = 1.2 + 1.0 + 0.9 + 0.9 + 0.85 + 0.80 + 0.70 = 6.35
normalized_reward = total / total_weight
```

**60% influence integration:** The system applies `influence_percentage = 0.60` when blending
intrinsic reward into self-improvement decisions. 40% comes from external priority signals.

### 6.4 Novelty Tracking

**Embedding similarity (cosine):**
```
similarity(a, b) = (a · b) / (||a|| * ||b||)
Range: [-1, 1] (1 = identical, 0 = orthogonal, -1 = opposite)
```

**Novelty threshold:** `_novelty_threshold = 0.75`
If `max_similarity > 0.75`, goal is considered repetitive and is mutated.

**Embedding cache:** Last 100 goal embeddings in memory (FIFO). Older embeddings lost.

### 6.5 Exploration Decay Formula

```
theme_weight = base_weight * exp(-decay_rate * repeat_count)
where:
  decay_rate = 0.3
  repeat_count = theme occurrence count from database

Example:
  repeat_count = 0 → weight = base_weight * 1.00
  repeat_count = 3 → weight = base_weight * exp(-0.9) ≈ base_weight * 0.407
  repeat_count = 7 → weight = base_weight * exp(-2.1) ≈ base_weight * 0.122
```

### 6.6 Goal Mutation Algorithm

**Trigger:** `similarity > 0.75`

**Mutation dimensions:**
```
components:        ['memory_agent', 'neural_bridge', 'unified_llm', 'learning', 'security']
abstraction_levels: ['low', 'medium', 'high']
objective_types:   ['explore', 'optimize', 'fix', 'learn', 'audit']
time_horizons:     ['immediate', 'short', 'long']
```

**Process:**
```
1. Select new values (different from current) for each dimension
2. If LLM available:
   Use LLM with temperature=0.9 to rewrite goal incorporating mutations
3. Fallback (no LLM):
   Template-based string construction from mutation dimensions
4. Store new embedding
5. Increment theme repeat_count in database
```

### 6.7 Theme Extraction Decision Tree

```
['security', 'audit', 'vulnerability', 'threat'] → 'security'
['performance', 'optimize', 'speed', 'latency', 'memory'] → 'performance'
['error', 'bug', 'fail', 'crash', 'fix'] → 'debugging'
['learn', 'understand', 'analyze', 'study', 'explore'] → 'learning'
['test', 'verify', 'validate', 'check'] → 'testing'
['refactor', 'improve', 'redesign', 'architecture'] → 'refactoring'
['data', 'storage', 'database', 'memory'] → 'data'
default → 'exploration'
```

### 6.8 Boot Entropy Generation

```
timestamp   = current_time_seconds()
process_id  = random_int(1000, 9999)
random_bytes = random_bits(256)
entropy_str  = f"{timestamp}_{process_id}_{random_bytes}"
entropy_hash = SHA256(entropy_str.encode())
boot_context = f"BOOT_{YYYYMMDD_HHMMSS}_{entropy_hash[:16]}"
```

Purpose: Non-deterministic initialization context to prevent identical exploration trajectories
across restarts. Currently generated but not injected into goal generation logic.

### 6.9 Plan Diversity Enforcement

**Data structures:**
```
_tool_sequence_history: List[List[str]]    # Last 10 iterations
_max_sequence_history: int = 10
_tool_cooldowns: Dict[str, int]            # tool_name → iterations remaining
_tool_failure_counts: Dict[str, int]       # tool_name → consecutive failures
_failed_parameter_patterns: Dict[str, List[Dict]]  # tool → failed param sets
_blocked_tool_params: Dict[str, set]       # tool → blocked param signatures
```

---

## 8. Epistemic and Bayesian Reasoning

### 7.1 Epistemic Engine

**File:** `core/reasoning/epistemic_engine.py`

**Constants:**
```
EPSILON = 1e-4                    # Minimum entropy delta to count as mutation
PRIOR_INFORMATION_THRESHOLD = 0.05  # Min |prior - 0.5| to count new belief
STAGNATION_HOURS = 24.0           # Hours before hypothesis considered stalled
EVIDENCE_MINIMUM = 1              # Min evidence pieces before hypothesis is "active"
```

**EpistemicMutation (NamedTuple):**
```
mutation_type: str    # new_hypothesis | new_belief | entropy_reduction | entropy_increase
entity_id: str        # belief_id or hypothesis_id
delta: float          # signed entropy change (positive = entropy reduced = knowledge gained)
```

**EpistemicTarget (Dataclass):**
```
target_id: str
target_type: str      # "belief" or "hypothesis"
entropy: float        # current entropy (higher = more uncertain = higher priority for exploration)
description: str      # becomes the exploration goal description
domain: str
metadata: Dict
```

**Shannon entropy formula:**
```
H(p) = -p * log2(p) - (1-p) * log2(1-p)
where p is clamped to [1e-9, 1 - 1e-9] to avoid log(0)
Range: [0, 1] bits
H(0.5) = 1.0  (maximum uncertainty)
H(0.0) = H(1.0) = 0.0  (certainty)
```

**Hypothesis entropy:**
```
hyp_entropy = H(max(0.001, min(0.999, confidence)))
```

**LLM output application algorithm:**

```
INPUTS: outputs dict with 'hypotheses' and 'belief_updates' lists

PROCESS HYPOTHESES:
  For each hypothesis:
    prior = clamp(confidence, [0.05, 0.95])
    If |prior - 0.5| <= 0.05: create belief but NOT a mutation
    Else:
      entropy_before = 1.0 (maximum for new, unknown claim)
      belief = create_belief(claim, domain, prior)
      entropy_after = belief.entropy
      delta = entropy_before - entropy_after
      If |delta| > EPSILON: record as mutation

  Persist to HypothesisTestingSystem (failure does NOT block mutations)

PROCESS BELIEF UPDATES:
  For each belief_update:
    Find or create source_belief (same threshold check)
    If existing belief:
      entropy_before = current entropy
      Apply Bayesian update
      entropy_after = new entropy
      delta = entropy_before - entropy_after
      If |delta| > EPSILON: accumulate in net_delta
    Add relationship (NOT a mutation itself)
    Shallow constraint propagation (max_depth=3)

CONVERT DELTAS TO MUTATIONS:
  For each (belief_id, net_delta) where |net_delta| > EPSILON:
    type = "new_hypothesis"/"new_belief" if newly created
         = "entropy_reduction" if net_delta > 0
         = "entropy_increase" if net_delta < 0
    Append EpistemicMutation record

RETURN mutations list (empty = no real epistemic change)
```

**Unstable region detection:**

```
High-entropy beliefs (targets for exploration):
  entropy > 0.7 → posterior roughly in (0.28, 0.72)
  → Add as EpistemicTarget type="belief"

Stalled hypotheses (both conditions must hold):
  1. status in {PROPOSED, INCONCLUSIVE}
  2. proposed_at < now - 24 hours
  3. len(supporting + contradicting evidence) < 1
  → Add as EpistemicTarget type="hypothesis"

Sort all targets by entropy descending (highest uncertainty first)
```

### 7.2 Bayesian Uncertainty System

**File:** `core/reasoning/bayesian_uncertainty.py`

**UncertaintyType (Enum):**
```
ALEATORIC    - Irreducible randomness (random quantum events, dice)
EPISTEMIC    - Reducible through learning (lack of data)
MODEL        - Uncertainty about model structure
PARAMETRIC   - Uncertainty about model parameters
```

**KnowledgeState (Enum):**
```
KNOWN_KNOWN      - We know it and know we know it
KNOWN_UNKNOWN    - We know we don't know it (identified gap)
UNKNOWN_UNKNOWN  - We don't know we don't know it (blind spot)
PARTIAL          - We know something but not everything
```

**RelationType (Enum) — with propagation semantics:**
```
IMPLIES          A → B: P(B) pulled toward P(A), strength 0.8x
CONTRADICTS      A ⊥ B: P(B) pushed opposite, strength 0.9x
SUPPORTS         A ⇒ B: weak positive, strength 0.4x
WEAKENS          A weakens B: weak negative, strength 0.4x
REQUIRES         A requires B: propagate only large decreases (>0.2), strength 0.7x
MUTUALLY_EXCLUSIVE A ⊕ B: zero-sum, strength 0.95x
```

**BayesianBelief (Dataclass):**
```
belief_id: str
claim: str
domain: str
prior_probability: float           # P(H) - initial belief
likelihood: float                  # P(E|H) - likelihood ratio
posterior_probability: float       # P(H|E) - updated belief

evidence_for: List[Dict]
evidence_against: List[Dict]
evidence_quality: float = 0.5

uncertainty_type: UncertaintyType = EPISTEMIC
credible_interval: Tuple[float, float] = (0.0, 1.0)  # 95% CI
entropy: float = 1.0

decay_rate: float = 0.01           # λ (domain-adaptive)
last_evidence_time: datetime
time_since_reinforcement: float = 0.0  # hours

last_updated: datetime
update_count: int = 0
confidence_history: List[float]
```

**Belief update algorithm — full specification:**

```
STEP 1: Temporal Decay (prevents epistemic ossification)
  now = current_time
  dt_hours = (now - last_evidence_time) / 3600
  lambda = domain_volatility[belief.domain]
  decay_factor = 1 - exp(-lambda * dt_hours)
  decayed_prior = current_prob + (0.5 - current_prob) * decay_factor

  Interpretation: Without evidence, belief drifts toward maximum uncertainty (0.5)
  Rate controlled by domain volatility lambda

STEP 2: Extract Evidence Weight
  evidence_weight = evidence.get('quality', belief.evidence_quality)
  Adjusted by cross-domain support

STEP 3: Bayesian Update — Exponential Likelihood Ratio
  _LR_STRENGTH = 3.0

  if evidence_supports:
    LR = exp(3.0 * evidence_weight)
  else:
    LR = exp(-3.0 * evidence_weight)

  Quality → LR mapping:
    weight = 0.0 → LR = 1.0        (no update)
    weight = 0.5 → LR = exp(±1.5) ≈ 4.5 or 0.22
    weight = 1.0 → LR = exp(±3.0) ≈ 20.1 or 0.05

  Odds update (Bayes' theorem in odds form):
    prior_odds = prior / (1 - prior)
    posterior_odds = prior_odds * LR
    posterior = posterior_odds / (1 + posterior_odds)

STEP 4: Regime Shift Detection
  if (prior > 0.5 AND posterior < 0.5) OR (prior < 0.5 AND posterior > 0.5):
    LOG: "Belief reversal detected" (regime shift)
    increment regime_shifts_detected counter

STEP 5: Domain Volatility Update (adaptive lambda)
  belief_change = |posterior - original_prior|
  domain_belief_changes[domain].append(belief_change)  # keep last 50

  avg_change = mean(domain_belief_changes[domain])
  regime_penalty = min(regime_shifts[domain] * 0.005, 0.05)
  new_lambda = 0.01 + (avg_change * 0.1) + regime_penalty
  new_lambda = clamp(new_lambda, [0.005, 0.1])

STEP 6: Posterior Floor (prevent probability collapse)
  _POSTERIOR_FLOOR = 1e-6
  belief.posterior = max(_POSTERIOR_FLOOR, min(1 - _POSTERIOR_FLOOR, posterior))

STEP 7: Update Entropy and 95% Confidence Interval
  entropy = H(posterior)
  std_error = sqrt(posterior * (1 - posterior) / update_count)
  CI = (max(0, posterior - 1.96*std_error),
        min(1, posterior + 1.96*std_error))

STEP 8: Constraint Propagation (if |delta| > 0.05)
  propagate_constraints(belief_id, delta, max_depth=5)
```

**Temporal decay formula:**
```
P(H)_{t+dt} = P(H)_t + (0.5 - P(H)_t) * (1 - exp(-λ * dt))

where:
  P(H)_t = current posterior probability
  λ = domain_volatility (adaptive, range [0.005, 0.1])
  dt = hours since last evidence
  0.5 = maximum entropy attractor

Interpretation: All beliefs regress toward 0.5 without reinforcing evidence.
Volatile domains (large λ) decay faster.
```

**Domain volatility formula:**
```
λ_new = 0.01 + (avg_change * 0.1) + min(regime_shifts * 0.005, 0.05)
λ_new = clamp(λ_new, [0.005, 0.1])

Components:
  0.01         = base rate (minimum decay for stable domains)
  avg_change*0.1 = volatility from recent belief changes
  regime_penalty = penalty for belief reversals (max 0.05 at 10+ reversals)
```

**Constraint propagation algorithm:**

```
INPUTS: changed_belief_id, probability_delta, max_depth, visited set

BASE CASES:
  max_depth <= 0 → return
  changed_belief_id in visited → return (cycle prevention)

PROCESS:
  Mark as visited
  Get forward_relationships[changed_belief_id]

  For each relationship:
    effect = delta * strength * confidence * relation_multiplier

    Relation multipliers:
      IMPLIES          → 0.8 (pull B toward A)
      CONTRADICTS      → -0.9 (push B opposite A)
      SUPPORTS         → 0.4 (weak positive)
      WEAKENS          → -0.4 (weak negative)
      REQUIRES         → 0.7 IF delta < -0.2 ELSE 0.0
      MUTUALLY_EXCLUSIVE → -0.95 (near zero-sum)

    If |effect| < 0.01: skip (noise threshold)
    new_prob = clamp(old_prob + effect, [0, 1])
    If |new_prob - old_prob| > 0.01:
      Update target probability
      Recurse: propagate_constraints(target_id, effect, max_depth-1, visited)
```

**Consistency violations detected:**
```
IMPLICATION: P(A) - P(B) > 0.15 when A → B
CONTRADICTION: NOT (0.8 ≤ P(A)+P(B) ≤ 1.2) when A ⊥ B
MUTUAL_EXCLUSIVITY: P(A) > 0.7 AND P(B) > 0.7
```

**Confidence calibration metrics:**
```
Brier Score: mean((predicted_confidence - actual_outcome)^2)
  Range: [0, 1], lower is better

Calibration Error: mean(|predicted_confidence - actual_accuracy|)
  Per confidence bin

Overconfidence Bias: mean(predicted_confidence - actual_accuracy)
  Positive = overconfident
  Negative = underconfident

Bias correction: calibrated = raw_confidence - overconfidence_bias
Minimum samples for valid calibration: 100
```

---

## 9. Hypothesis Testing System

**File:** `core/reasoning/hypothesis_testing.py`

**HypothesisStatus:** PROPOSED → TESTING → SUPPORTED | REFUTED | INCONCLUSIVE | REVISED

**ExperimentStatus:** DESIGNED → RUNNING → COMPLETED | FAILED | CANCELLED

**EvidenceType ranking (quality):**
```
EXPERIMENTAL  → 0.90  (controlled experiment)
EMPIRICAL     → 0.80  (real-world data)
SIMULATED     → 0.70  (simulation)
OBSERVATIONAL → 0.60  (observation without control)
THEORETICAL   → 0.50  (reasoning/proof)
```

**Hypothesis dataclass:**
```
hypothesis_id: str
claim: str
domain: str
is_falsifiable: bool
falsification_criteria: List[str]
verification_criteria: List[str]
predictions: List[str]
null_hypothesis: Optional[str]
alternative_hypotheses: List[str]
status: HypothesisStatus = PROPOSED
confidence: float = 0.5
supporting_evidence: List[str]    # evidence IDs
contradicting_evidence: List[str]
proposed_at: datetime
revisions: int = 0
parent_hypothesis_id: Optional[str]
```

**Falsifiability detection:**
```
Not falsifiable:
  Contains ["should", "ought", "good", "bad", "better", "best"] → value judgment
  Contains "or not" or "either" → tautology

Falsifiable:
  Contains ["increase", "decrease", "improve", "reduce", "cause", "effect",
            "more", "less", "faster", "slower", "higher", "lower",
            "if", "when", "result", "predict"] → measurable claim
  Default: True
```

**Hypothesis evaluation algorithm:**
```
supporting_strength = sum(evd.strength * evd.quality_score for supporting_evidence)
contradicting_strength = sum(evd.strength * evd.quality_score for contradicting_evidence)
total = supporting_strength + contradicting_strength

if total == 0:
  verdict = INCONCLUSIVE, confidence = 0.5
else:
  support_ratio = supporting_strength / total

  if support_ratio > 0.70:  SUPPORTED,    confidence = support_ratio
  if support_ratio < 0.30:  REFUTED,      confidence = 1.0 - support_ratio
  else:                     INCONCLUSIVE, confidence = 0.5
```

**Evidence quality scoring:**
```
base quality by type (see table above)
sample_size > 100: +0.1
sample_size < 10:  -0.1
p_value < 0.01:    +0.1
p_value > 0.10:    -0.1
final = clamp(result, [0.0, 1.0])
```

**Parameter shift rule (quantum gradient estimation):**
```
For each parameter θ_i:
  L(θ + π/2 * e_i) - L(θ - π/2 * e_i)
  gradient[i] = ───────────────────────────
                             2
```

---

## 10. Planning Engine

**File:** `core/agents/autonomous/planning_engine.py`

**Goal priority formula:**
```
priority_values = {LOW: 0.25, MEDIUM: 0.5, HIGH: 0.75, CRITICAL: 1.0}
external_priority = priority_values[goal.priority]
intrinsic_potential = goal.intrinsic_reward_potential  # float or dict with 'value'

combined_score = ((1.0 - intrinsic_weight) * external_priority
                + intrinsic_weight * intrinsic_potential)
```

**Task executability — resource constraint:**
```
if system_state.resource_usage > 0.9:
  only HIGH priority tasks allowed
```

**Plan confidence formula:**
```
base_confidence = 0.7

if len(tasks) <= 3: base_confidence += 0.2
if len(tasks) > 7:  base_confidence -= 0.1

if context.available_resources > 0.8: base_confidence += 0.1

return clamp(base_confidence, [0.0, 1.0])
```

**Task sorting:** By priority (descending) then by `created_at.timestamp()` (ascending, FIFO within tier)

**Max concurrent tasks:** 5 (default)

**Goal status updates:**
```
completed_plans = count(plan.status == "completed")
total_plans = stats["plans_generated"]
success_rate = completed_plans / total_plans if total_plans > 0 else 0.0
```

**Task type → tool suggestions:**
```
RESEARCH   → [semantic_search, grep_search, read_file, list_directory]
ANALYSIS   → [analyze_code, grep_search, read_file, semantic_search]
EXECUTION  → [run_python, run_shell_command, execute_sandbox, write_file]
VALIDATION → [read_file, run_python, analyze_code]
SYNTHESIS  → [read_file, write_file, semantic_search]
```

---

## 11. Memory System

### 10.1 Storage Architecture

**Engine:** PostgreSQL + pgvector
**Embedding model:** all-MiniLM-L6-v2, 384 dimensions
**Model load time:** ~1.46 seconds (local cache, `local_files_only=True`)

**3 Database schemas:**
```
unified     - Core operational data (tasks, goals, plans, security, governance)
memory_hot  - Active memories (0-60 days), HNSW vector indexes
memory_cold - Archived memories (60+ days)
```

**HNSW index:** Hierarchical Navigable Small World graphs. Provides ~100x speedup over
brute-force cosine similarity for 384-dim vectors.

### 10.2 Memory Types

Episodic, semantic, procedural, meta, working, emotional

### 10.3 Hot/Cold Tier Logic

**Retention period:** 60 days in hot tier
**Migration trigger:** age > retention_days
**Migration:** Move record from `memory_hot` schema to `memory_cold` schema

**Memory storage flow:**
```
1. Generate 384-dim embedding via all-MiniLM-L6-v2
2. Serialize: content, thinking_state, metadata → JSONB
3. INSERT into memory_hot.memories with vector(384) embedding
4. Track: memories_stored counter
```

### 10.4 Semantic Search

```
Query: embedding of search text
Method: cosine similarity via pgvector
SQL: ORDER BY embedding <=> $1::vector LIMIT $2

Similarity threshold: 0.70 (minimum in executor search)
Deduplication: by memory_id
```

### 10.5 Embedding Generation

```
batch_embed(texts):
  1. Filter empty strings
  2. model.encode(texts, normalize_embeddings=True)
  3. Return List[List[float]] of length 384
  4. None for failed texts

generate_embedding(text) → single 384-dim list or None
```

### 10.6 Memory Retrieval — Two-Pass Strategy

See Section 5.1 for full specification. Max 800 tokens of memory content per task.

---

## 12. Learning and Self-Improvement

### 11.1 Improvement Phases

**File:** `core/learning/enhanced_asi_self_improvement.py`

```
Phase 1: ASSESSMENT    - Identify performance gaps (health_score < 90)
Phase 2: PLANNING      - Select targets, evaluate via governance
Phase 3: GENERATION    - LLM code generation (temperature=0.3)
Phase 4: VALIDATION    - Static analysis + LLM semantic check
Phase 5: TESTING       - Sandbox execution
Phase 6: DEPLOYMENT    - Safe deploy with health gate
Phase 7: EVALUATION    - Measure capability impact
Phase 7.5: REGRESSION  - Long-horizon drift detection (30-cycle window)
Phase 8: REFLECTION    - Update meta-learning records
```

### 11.2 Assessment Scoring

**Health score → improvement potential:**
```
current_score >= 90: potential = 2  + (scope_weight * 1)   difficulty = "hard"
current_score >= 75: potential = 5  + (scope_weight * 2)   difficulty = "medium"
current_score >= 60: potential = 8  + (scope_weight * 3)   difficulty = "medium"
current_score  < 60: potential = 15 + (scope_weight * 5)   difficulty = "easy"

scope_weight: MINOR=1, MODERATE=2, MAJOR=3, TRANSFORMATIVE=4
```

### 11.3 Static Code Analysis

**StaticCodeAnalyzer — dangerous patterns (hard block):**
```
exec(), eval(), __import__(), compile()
sys.modules[], globals()[], locals()[], __builtins__
subprocess.call/run/Popen with shell=True
os.system()
File write operations in certain contexts
pickle.loads(), yaml.load() without safe loader
rm -rf, DROP TABLE, dangerous DELETE
```

**Suspicious patterns (block in strict mode):**
```
Network imports: socket, urllib, requests
File I/O: open()
Dunder methods and attributes
Dynamic attribute access: setattr(), getattr()
```

### 11.4 Deployment Safety Gates

**Gate 1 — System health (ImprovementMonitor):**
```
overall_health_score >= 80
critical_components == 0
overall_error_rate <= 0.05 (5%)
```

**Gate 2 — Human approval required for:**
```
scope in [MAJOR, TRANSFORMATIVE]
requires context['human_approved'] == True
```

**Gate 3 — Code verification (LLM semantic check):**
```
temperature = 0.1 (low for deterministic check)
timeout = 30 seconds
required fields: matches_requirements, confidence, reason, issues
```

**Gate 4 — Governance evaluation:**
```
MINOR       → ActionCategory.LEARNING_PARAMETERS
MODERATE    → ActionCategory.CONFIGURATION_CHANGES
MAJOR       → ActionCategory.CONFIGURATION_CHANGES
TRANSFORMATIVE → ActionCategory.CONFIGURATION_CHANGES

MUST_BLOCK decision → abort improvement cycle
```

### 11.5 Model Weight Update — Security Chain

```
Gate 1: Governance (CRITICAL tier)
Gate 2: Human approval validation
  - voter_type must be "human"
  - cryptographic signature required
  - expiration: 90 days
  - blocked voter patterns: "learner", "governance_agent", "system"
Gate 3: Health check (health >= 80, critical_components == 0)
Gate 4: Atomic transaction
  - Store current weights → rollback table
  - Apply delta
  - Audit trail record
  - Commit or full rollback
```

### 11.6 Capability Regression Detection

**Window:** 30 cycles for long-horizon drift
**Domains tracked:** overall, reasoning, coding, analysis, comprehension

**Severity levels:**
```
CRITICAL → Block improvement cycle immediately
HIGH     → Log warning (immediate intervention needed)
```

### 11.7 Improvement Scope → Learning Strategy

```
MINOR        → GRADIENT_DESCENT
MODERATE     → EVOLUTIONARY
MAJOR        → META_GRADIENT
TRANSFORMATIVE → HIERARCHICAL
```

### 11.8 Circular Dependency Guard

```
max_cycle_nesting: int = 2
Raises RuntimeError if nesting depth > 2
Prevents: autonomous_coordinator ↔ self-improvement infinite recursion
```

### 11.9 Deployment Strategies

**File:** `core/learning/safe_upgrade_deployer.py`

```
Immediate:   Full deployment, no staging (fastest, highest risk)
Canary:      10% traffic first, monitor, then full rollout
Blue-Green:  Deploy to standby environment, atomic traffic switch
Rolling:     Gradual instance replacement over time

Health check interval: 30 seconds
Monitoring period:     300 seconds (5 minutes)
Rollback threshold:    5% failure rate (0.05)
Backup enabled:        True by default
```

### 11.10 Other Learning Components

| File | Algorithm | Key Metrics |
|------|-----------|-------------|
| `meta_learning.py` | Thompson sampling + Wilson CI | Effectiveness score = 70% success + 30% speed |
| `bandit_policy.py` | Beta distribution Thompson sampling | Speed factor = 1/(1 + avg_time/1000ms) |
| `adaptive_tool_learning.py` | Tool-task performance history | Per-tool success rates |
| `drift_monitoring/monitor.py` | Statistical drift detection | Concept drift significance |
| `causal_feedback_analyzer.py` | Causal graph inference | Action-outcome attribution |
| `frontier_foresight_methods_impl.py` | Research signal aggregation | 10-minute cache |
| `capability_benchmark_suite.py` | Standardized capability benchmarks | Domain scores |
| `performance_profiler.py` | Timing + throughput tracking | Per-operation latency |
| `mutation_detector.py` | Behavioral fingerprinting | Behavioral delta detection |

---

## 13. Meta-Learning and Bandit Policy

### 12.1 Meta-Learning System

**File:** `core/learning/meta_learning.py`

**LearningStrategy (Dataclass):**
```
strategy_id: str
strategy_type: LearningStrategyType
task_type: TaskType
parameters: Dict = {}
trials: int = 0
successes: int = 0
failures: int = 0
success_rate: float = 0.0
avg_time_ms: float = 0.0
total_time_ms: float = 0.0
effectiveness_score: float = 0.0
confidence: float = 0.0
last_used: Optional[datetime]
```

**Latency tracking — Exponential Moving Average:**
```
alpha = 0.2
if trials == 1:
  avg_time_ms = time_ms
else:
  avg_time_ms = 0.2 * time_ms + 0.8 * avg_time_ms
```

**Effectiveness score formula:**
```
time_score = max(0.0, 100.0 - (avg_time_ms / 100.0))
effectiveness_score = success_rate * 70.0 + time_score * 0.3
```
Weighting: 70% success rate, 30% inverse latency.

**Confidence growth formula:**
```
confidence = min(1.0, trials / (min_trials * 2.0))
```
Reaches 0.5 at `min_trials`, reaches 1.0 at `2 * min_trials`.

**Wilson Score 95% Confidence Interval:**
```
p = successes / trials
z = 1.96
denominator = 1 + z^2 / trials
centre = (p + z^2 / (2*trials)) / denominator
margin = z * sqrt((p*(1-p) + z^2/(4*trials)) / trials) / denominator
lower = max(0, centre - margin)
upper = min(1, centre + margin)
```

### 12.2 Strategy Validation Gates

**HARD GATE 1 — Exploration quota exception:**
```
if exploration_quota_used < 0.10 AND trials < 5:
  ALLOW for discovery (within 10% exploration budget)
```

**HARD GATE 2 — Minimum trials:**
```
if trials < 5 (and not in exploration quota):
  BLOCK
```

**HARD GATE 3 — Progressive success rate:**
```
trials < 20:  min_success_rate = 0.60
trials >= 20: min_success_rate = 0.70
```

**HARD GATE 4 — Confidence interval:**
```
if lower_CI < min_success_rate:
  BLOCK ("low confidence interval does not meet minimum")
```

### 12.3 Strategy Adaptation

**Triggered:** Every 10 learning records
**Threshold:** 0.70 success rate for promotion
**Deprecation:** < 0.30 success rate
**Hybrid discovery:** Triggered when >= 2 successful strategies exist

### 12.4 Thompson Sampling (Bandit Policy)

**File:** `core/learning/bandit_policy.py`

**Beta distribution parameters:**
```
alpha = max(1.0, float(successes) + 1.0)   # Beta prior (laplace smoothing)
beta  = max(1.0, float(failures) + 1.0)    # Beta prior (laplace smoothing)
sample = random.betavariate(alpha, beta)
```

**Speed weighting (prefer_fast=True):**
```
baseline_ms = 1000.0
speed_factor = 1.0 / (1.0 + max(0, avg_time_ms) / baseline_ms)
score = sample * speed_factor
```

**Selection:** argmax over all candidate scores.

**Fallback chain if selected strategy blocked by hard gate:**
```
1. Thompson sample remaining candidates
2. Effectiveness-based selection (argmax effectiveness_score)
3. Raise error if all blocked
```

---

## 14. Security Systems — Full Specification

### 13.1 Security Audit Worker

**File:** `core/security/security_audit_worker.py`

**Audit interval:** 120 seconds (default)

**Compliance score formula:**
```
penalty_weights = {CRITICAL: 20, HIGH: 10, MEDIUM: 5, LOW: 1}
total_penalty = sum(penalty_weights[f.severity] for f in findings)
score = max(0.0, 100.0 - total_penalty)
```

**Access control audit thresholds:**
```
Failed auth attempts in 24h, grouped by username:
  > 10 attempts per user → MEDIUM finding
  > 50 attempts per user → HIGH finding
```

**Anomaly detection thresholds:**
```
Error rate in 1-hour window:
  > 25% error rate → MEDIUM
  > 50% error rate → HIGH

Directive creation rate:
  > 50 directives in 1 hour → MEDIUM

SQL injection patterns detected in auth logs → HIGH
World-readable configuration files → HIGH
```

**Threat enrichment and auto-block logic:**
```
Phase 2: Query threat intelligence for IPs in findings
  threat_score > 80 → Upgrade finding severity to CRITICAL

Phase 3: Auto-block decision
  IF severity == CRITICAL AND threat_score > 70:
    → analyze_and_block(ip_address)
```

**Critical table integrity checks:**
```
Tables: ['conversations', 'memories', 'system_logs', 'governance_evaluations']
Trigger: rows == 0 OR rows is None → MEDIUM finding
```

### 13.2 Threat Intelligence Engine

**File:** `core/security/threat_intelligence.py`

**Cache TTL:** 3600 seconds (1 hour, configurable)

**Parallel query:** All 4 sources queried concurrently via `asyncio.gather()`

**AbuseIPDB scoring:**
```
abuse_score = abuseConfidenceScore / 100.0
abuse_score > 0.5 → threat_type: BOT_ATTACK
```

**VirusTotal scoring:**
```
vt_score = (malicious * 1.0 + suspicious * 0.5) / total_analyses
malicious > 0 → threat_type: MALWARE_UPLOAD
```

**OTX AlienVault scoring:**
```
otx_score = min(len(pulses) * 0.1, 1.0)
Tag → threat type mapping:
  "malware" → MALWARE_UPLOAD
  "ddos"    → DDOS
  "scan"    → PORT_SCAN
```

**Reputation aggregation:**
```
reputation_score = max(reputation_scores)  # Worst-case selection
```

**Confidence from source count:**
```
>= 3 sources → CRITICAL
   2 sources → HIGH
   1 source  → MEDIUM
   0 sources → LOW

Override rules:
  reputation_score < 0.30 → LOW (clean IP)
  reputation_score > 0.80 AND confidence in [LOW,MEDIUM] → HIGH
```

**Notification thresholds:**
```
reputation_score > 0.8 → severity: critical
reputation_score > 0.6 → severity: warning
reputation_score > 0.5 → severity: info
```

### 13.3 Firewall Manager

**File:** `core/security/firewall_manager.py`

**Platform commands:**

Linux (iptables):
```bash
# Block IP:
iptables -A INPUT -s {ip} -j DROP -m comment --comment "TorinAI: {reason}"

# Allow IP (insert at position 1):
iptables -I INPUT 1 -s {ip} -j ACCEPT -m comment --comment "TorinAI: whitelist"

# Block port:
iptables -A INPUT -p tcp --dport {port} -j DROP
```

macOS (pf):
```
# Block IP rule file format:
block drop in quick from {ip} to any

# Allow IP rule file format:
pass in quick from {ip} to any

# Load via: pfctl -a torin_defense -f /tmp/torin_rule_{hash}.conf
```

**Rule ID:** SHA256(f"block_{ip}_{timestamp}")[:16]
**Whitelist priority:** 10 (high)
**Test mode:** Bypasses all actual firewall operations (dry run)

**Limitations:**
- Rules not persisted — lost on system restart
- Requires root/sudo privileges
- Windows: not implemented (stub only)
- macOS: requires `torin_defense` pf anchor to pre-exist

### 13.4 Cloudflare WAF Manager

**File:** `core/security/cloudflare_waf.py`

**2-step rule creation process:**
```
Step 1: POST /zones/{zone_id}/filters
  body: {"expression": "ip.src eq {ip}", "description": "TorinAI: {reason}"}
  Response: filter_id

Step 2: POST /zones/{zone_id}/firewall/rules
  body: {"filter": {"id": filter_id}, "action": "block", "priority": 1}
```

**Rule priority:** 1 (highest) for blocks, 10+ for rate limits

**Country block:**
```
POST /zones/{zone_id}/firewall/access_rules/rules
body: {"mode": "block", "configuration": {"target": "country", "value": "CN"}}
```

**SSL verification:** Enabled by default (override only for debugging: `CLOUDFLARE_VERIFY_SSL=false`)

**API timeout:** Configurable (retry on connection error only)

### 13.5 Security Controller

**File:** `core/security/controller.py`

**Security validation flow:**
```
1. Rate limiting check per IP
2. SQL injection detection (pattern matching)
3. Path traversal prevention
4. XSS protection
5. Authentication (API key SHA256 or token)
6. Authorization (RBAC lookup)
7. Audit log event
8. IF critical: escalate to autonomous coordinator
```

**API key hashing:** SHA256 single iteration (vulnerability: GPU brute-force)

**Severity calculation:** Based on count of recent security events in last 50 events.

### 13.6 Additional Security Files

| File | Purpose |
|------|---------|
| `asi_safety.py` | ASI-level safety boundaries for self-improvement actions |
| `content_security.py` | Input sanitization: XSS, SQL injection, shell injection patterns |
| `malware_sandbox.py` | Sandboxed execution environment for untrusted/generated code |
| `digital_footprint.py` | System digital footprint analysis and exposure mapping |
| `safety_framework.py` | Top-level safety framework integration |
| `system_security.py` | Rate limiting, path validation, SQL injection detection primitives |
| `threat_blocking.py` | Coordinates between threat intelligence and firewall blocking |
| `active_defense_types.py` | Shared types: FirewallRule, BlockedEntity, ThreatIntelligence, WAFRule, AttackType |
| `security_training_pipeline.py` | Training pipeline for security classification models |
| `security_types.py` | SecurityFinding, SecurityEvent, SecurityLevel enumerations |
| `service_abstractions.py` | Abstract interfaces for security service implementations |

---

## 15. Health and Monitoring

### 14.1 Health Monitor

**File:** `core/health/health_monitor.py`

**Configuration thresholds:**
```
cpu_warning:          70.0%
cpu_critical:         90.0%
memory_warning:       75.0%
memory_critical:      90.0%
disk_warning:         80.0%
disk_critical:        95.0%
error_rate_warning:    5.0% (0.05)
error_rate_critical:  15.0% (0.15)
```

**Health status determination:**
```
IF no issues:                             HEALTHY
IF any issue contains "critical":         CRITICAL
IF 3+ issues:                             UNHEALTHY
IF 1-2 issues without "critical":         DEGRADED
```

**System metrics collected (via psutil):**
```
cpu_percent:     CPU utilization 0-100
memory_percent:  RAM utilization 0-100
disk_percent:    Disk utilization 0-100
network_active:  bool (bytes_sent > 0 AND bytes_recv > 0)
process_count:   len(psutil.pids())
thread_count:    sum(p.num_threads() for p in psutil.process_iter())
load_average:    (1-min, 5-min, 15-min)
file_descriptors: count of open file descriptors
```

**Monitoring parameters:**
```
check_interval:    30 seconds
max_history_size:  1000 samples (circular buffer)
```

**Statistics dictionary:**
```
total_checks, healthy_checks, degraded_checks, unhealthy_checks, critical_checks
last_check_time, uptime_start
```

### 14.2 Recovery Manager

**File:** `core/health/recovery_manager.py`

**Recovery strategy map:**
```
SERVICE_CRASH       → [CLEANUP, RESTART, ESCALATE]
DATABASE_ERROR      → [ROLLBACK, BACKUP, ESCALATE]
RESOURCE_EXHAUSTION → [CLEANUP, THROTTLE, ESCALATE]
NETWORK_ERROR       → [RESTART, ESCALATE]
TIMEOUT             → [RESTART, THROTTLE]
VALIDATION_ERROR    → [CLEANUP, ALERT]
SECURITY_VIOLATION  → [ISOLATE, ALERT, ESCALATE]
DATA_CORRUPTION     → [BACKUP, ROLLBACK, ESCALATE]
```

**Escalation threshold:**
```
IF component_failure_count > 5:
  Override strategy: [ISOLATE, ESCALATE]
  (Component considered unstable — immediate isolation)
```

**Recovery action implementations:**
```
RESTART  → Delegates to core.main (no individual component restart API)
ROLLBACK → Restore from snapshot (partial implementation)
BACKUP   → Create state backup in runtime/backups/
CLEANUP  → Garbage collection and resource cleanup
ESCALATE → Slack alert + human notification
THROTTLE → Log only (not implemented)
ISOLATE  → Log only (not implemented)
ALERT    → Monitoring alert via notification publisher
```

### 14.3 Monitoring Coordinator

**File:** `core/health/monitoring_coordinator.py` (50.7KB)

**Component types:** DATABASE, MEMORY, LEARNING, REASONING, AGENTS, SECURITY, STORAGE, API, QUANTUM, NETWORK

**Alert routing:**
```
INFO     → Log only
WARNING  → Queue for Singleton review
ERROR    → Slack notification
CRITICAL → Immediate Singleton intervention + Slack
```

**Callback mechanism:** `singleton_callback` property allows real-time health event delivery
to the Singleton via `_receive_health_event()`.

---

## 16. Governance System

### 15.1 Unified Governance Trigger System

**File:** `core/governance/unified_governance_trigger_system.py`

**8 Action categories:**
```
TOOL_EXECUTION        - Tool calls from executor
MEMORY_OPERATIONS     - Memory read/write/delete
RESOURCE_ALLOCATION   - Resource requests
LEARNING_PARAMETERS   - Learning system changes
CONFIGURATION_CHANGES - System configuration modifications
EXTERNAL_INTEGRATIONS - External API calls
TASK_CREATION         - New task queuing
CURIOSITY_EXPLORATION - Autonomous exploration
```

**3 Enforcement modes:**
```
LOG_ONLY             - Shadow mode: proceed, log outcome
RECOMMEND_GOVERNANCE - Session recommended, not required
MUST_BLOCK           - Hard block until approved
```

**3 Decision tiers:**
```
ROUTINE   - Auto-approve, Slack informational message
IMPORTANT - Approval request (30-min timeout, default: deny)
CRITICAL  - Full session: human approval required, 24-hour expiration
```

**Governance trigger evaluation:**
```
1. Load governance_triggers.json (schema_version + action_categories)
2. Build trigger cache per ActionCategory for O(1) lookup
3. For each incoming action:
   a. Match action_type against trigger conditions
   b. Determine irreversibility_class and impact_level
   c. Apply enforcement_manager override (if configured)
   d. Route to decision tier
   e. Return GovernanceTriggerEvaluation
```

**GovernanceTriggerEvaluation fields:**
```
action_id, action_category, triggered: bool
trigger_id, irreversibility_class, impact_level
safety_risk, enforcement_mode, decision_tier
```

**GovernanceDecision fields:**
```
approved: bool, human_approved: bool
expiration_date: datetime
```

### 15.2 Governance Files

| File | Role |
|------|------|
| `context_classifier.py` | Classifies action context for governance tier routing |
| `enforcement_mode_manager.py` | Manages transitions between LOG_ONLY, RECOMMEND, MUST_BLOCK |
| `shadow_mode_coordinator.py` | Coordinates LOG_ONLY shadow observation |
| `governance_block_schema.py` | Schema for governance block records |
| `directive_safety_monitor.py` | Monitors directive applications for safety compliance |
| `runtime_governance.py` | Runtime governance enforcement during task execution |
| `governance_agent.py` | Governance session handler |

---

## 17. Abstract Reasoning Engine

**File:** `core/reasoning/abstract_reasoning_engine.py`

### 16.1 Reasoning Types (17)

**Classical:**
DEDUCTIVE, INDUCTIVE, ABDUCTIVE, ANALOGICAL, CAUSAL, TEMPORAL, SPATIAL, LOGICAL,
PROBABILISTIC, COUNTERFACTUAL, MORAL, STRATEGIC

**Quantum-bridged:**
QUANTUM_SUPERPOSITION, QUANTUM_ENTANGLEMENT, QUANTUM_INTERFERENCE, QUANTUM_PARALLELISM,
QUANTUM_TUNNELING, QUANTUM_OPTIMIZATION

### 16.2 Inference Methods (10)

FORWARD_CHAINING, BACKWARD_CHAINING, RESOLUTION, UNIFICATION, PATTERN_MATCHING,
CONSTRAINT_SATISFACTION, BAYESIAN_INFERENCE, FUZZY_LOGIC, NEURAL_REASONING, QUANTUM_REASONING

### 16.3 Confidence Levels

```
VERY_LOW = 0.1,  LOW = 0.3,  MEDIUM = 0.5,
HIGH = 0.7,  VERY_HIGH = 0.9,  CERTAIN = 1.0
```

### 16.4 Deductive Reasoning Algorithm

```
For each rule in context.rules:
  For each premise in context.premises:
    If rule conditions match premise:
      confidence = min(0.8, premise.confidence * 0.9)
      Generate conclusion
      logical_validity = 0.8
      evidence_strength = premise.confidence
      coherence_score = 0.7
      Return conclusion
```

### 16.5 Inductive Reasoning Algorithm

**Jaccard similarity for grouping similar premises:**
```
intersection = common_words(p1, p2)
union = all_words(p1, p2)
similarity = |intersection| / |union|
threshold: > 0.3 for grouping
```

**Generalization:**
```
confidence = min(0.8, (group_size / 10) * avg_premise_confidence)
```

### 16.6 Analogical Reasoning Algorithm

```
For each pair of premises:
  Extract structure:
    entities:    nouns and objects
    relations:   verbs (is, has, does)
    properties:  adjectives/adverbs

  Structural similarity:
    similarity = mean(set_overlap(p1[key], p2[key]) for key in [entities, relations, properties])
    threshold: > 0.5 for analogy creation

  Confidence = min(0.7, similarity_score * 0.8)
```

### 16.7 Composite Quality Score

```
quality = (confidence      * 0.4
         + logical_validity * 0.3
         + evidence_strength * 0.2
         + coherence_score  * 0.1)

Range: [0.0, 1.0]
Threshold for inclusion: quality >= context.confidence_threshold (default 0.5)
```

### 16.8 Conclusion Validation Filter

```
1. confidence >= confidence_threshold (0.5 default)
2. statement.strip() != ""
3. NOT contradicts existing knowledge
4. logical_validity >= 0.3
```

**Contradiction detection:**
```
contradicts = ("not" in conclusion_words
               AND overlap(conclusion_words, fact_words) > 50% of conclusion)
```

### 16.9 Running Performance Average

```
new_avg = (old_avg * (total_ops - 1) + result_confidence) / total_ops
```

---

## 18. Tool Registry and General Purpose Executor

### 17.1 Tool Registry

**File:** `core/tools/tool_registry.py`

**Tool categories (16):**
FILESYSTEM, EXECUTION, SEARCH, NETWORK, SECURITY, DATABASE, CODE, COMMUNICATION,
AI_ML, MONITORING, DATA_PROCESSING, RESEARCH, DOCUMENTATION, REASONING, TESTING, CHAOS

**Safety levels:**
```
SAFE       - Read-only, no side effects
MODERATE   - Limited reversible side effects
DANGEROUS  - Significant or irreversible side effects
CRITICAL   - System-level impact
HIGH_RISK  - Potential for serious damage
```

**Key design:** No approval gates in tool registry. Singleton has full tool autonomy.
All calls logged for constitutional monitoring, not blocked at registry level.

**ToolResult:**
```
success: bool
output: Any
error: Optional[str]
execution_time: float
token_usage: Optional[int]
requires_approval: bool = False
approval_flags: List[str] = []
```

**ToolParameter validation types:** string, number, boolean, array, object, enum, min/max, regex

### 17.2 Tool Inventory (by category)

**Security tools** (`security_tools.py`):
```
encrypt_file, decrypt_file          - AES-256-CBC, PBKDF2 (100k iterations, 16-byte salt+IV)
generate_password, hash_data
validate_certificate, scan_secrets
check_ip_threat_intelligence        - AbuseIPDB + VirusTotal + OTX
block_ip_address, block_country
create_waf_rule
detect_intrusion, analyze_anomaly
monitor_logs, detect_brute_force
hunt_threats, sanitize_input
```

**Network tools** (`network_tools.py`):
```
http_request (GET/POST/PUT/DELETE/PATCH/HEAD, aiohttp, 1-300s timeout)
download_file, upload_file
parse_html, extract_links
check_url_status, dns_lookup
ping_host, port_scan
websocket_connect, graphql_query, api_call
```

**Filesystem tools** (`filesystem_tools.py`):
```
read_file, write_file, list_directory, create_directory
delete_file, move_file, search_files, get_file_info
```

**System management tools** (`system_management_tools.py`):
```
set_environment_variable (DANGEROUS: writes to .env)
get_environment_variable
modify_config_file, reload_config
check_dependencies, update_system
manage_docker
```

**Research tools** (`research_tools.py`):
```
conduct_research - TopicClassifier (12 categories, keyword-weighted)
  Categories: academic, government_data, finance, news, knowledge,
              code_development, cultural_heritage, weather_climate,
              geography_maps, educational_entertainment
  Returns top 3 categories by relevance score
  Queries multiple external APIs based on topic classification
```

**Other tool files:**
```
code_generation_tools.py     - generate/refactor/analyze/test/fix/optimize code
database_tools.py            - query/insert/update/delete/create/migrate
ai_ml_tools.py               - train/evaluate/infer/benchmark/fine-tune
learning_tools.py            - learn/update/retrieve/synthesize knowledge
monitoring_tools.py          - metrics/alerts/logs/performance/resources
communication_tools.py       - send/create/post/schedule messages
slack_tools.py               - send/post/thread/react Slack messages
data_processing_tools.py     - parse/transform/aggregate/clean data
documentation_tools.py       - generate docs/readme/reports/summaries
reasoning_tools.py           - reason/hypothesize/test/evaluate arguments
execution_tools.py           - execute/run/schedule commands and scripts
chaos_tools.py               - inject latency/errors/failures/experiments
testing_validation_tools.py  - unit tests/schema validation/contracts/regression
academic_tools.py            - arxiv/pubmed/citations/paper search
search_tools.py              - web/semantic/knowledge/vector search
agentso_capability_tools.py  - AgentSO connector capabilities
```

---

## 19. Chaos Engineering

**File:** `core/chaos/orchestrator.py`

### 18.1 Default Configuration

```
safety_controls:
  enable_preflight_checks:       True
  enable_slo_monitoring:         True
  enable_auto_rollback:          True
  slo_check_interval_seconds:    10
  max_blast_radius:              100
  require_governance_production: True

progressive_rollout.stages:
  canary:     blast_radius=1,   duration=5 min
  gradual_10: blast_radius=10,  duration=10 min
  gradual_50: blast_radius=50,  duration=15 min
  full:       blast_radius=100, duration=30 min
```

### 18.2 Governance Tier Determination

```
if target_system in ["governance", "safety", "security_system"]:
  → CRITICAL

if environment == "production":
  blast_radius > 50 → CRITICAL
  blast_radius > 10 → IMPORTANT
  else              → ROUTINE

if environment == "staging":
  blast_radius > 50 → IMPORTANT
  else              → ROUTINE

default → ROUTINE (dev)
```

### 18.3 Progressive Rollout State Machine

```
FOR stage IN rollout_stages (4 stages):
  IF stage.blast_radius > experiment.blast_radius: SKIP
  ELSE:
    Start injection
    WHILE now < stage_end_time:
      Collect metrics snapshot
      Check SLOs every slo_check_interval
      IF should_rollback:
        Log "stage_rollback"
        Trigger automatic rollback
        SET rollback_triggered = True
        BREAK
    IF stage success:
      Increment stage_index
      Log "stage_completed"
    ELSE:
      RETURN stage_result
RETURN aggregated result
```

### 18.4 SLO Monitoring

**Metrics collected per snapshot:**
```
system:    cpu_percent, memory_percent
component: latency_p95, latency_p99, error_rate
```

**Hypothesis validation:**
```
avg_latency_p95 = mean(m.latency_p95 for m in metrics)
avg_error_rate  = mean(m.error_rate for m in metrics)

validated = (avg_latency_p95 <= max_latency_p95_ms
            AND avg_error_rate <= max_error_rate)
```

### 18.5 Domain Adapters

Chaos can be injected into: agents, domain, intelligence, learning, memory, monitoring,
reasoning, security, services, tools via dedicated adapter modules in `core/chaos/adapters/`.

---

## 20. Quantum Computing Layer

**Files:** `core/quantum/`

### 19.1 Hybrid Processor

**File:** `core/quantum/hybrid_processor.py`

**HybridWorkflowConfig:**
```
quantum_threshold: 0.7          # Suitability score required to prefer quantum
max_qubits:       16            # Maximum problem size for quantum
prefer_quantum_for: ['optimization', 'ml_training']
fallback_to_classical: True
quantum_timeout:  300 seconds
use_error_mitigation: True      # Configured but not yet implemented
```

**Quantum suitability logic:**
```
if task_type in prefer_quantum_for:
  if optimization AND problem_size <= max_qubits: suitable = True
  if ml_training AND num_features <= max_qubits: suitable = True
else:
  suitable = False
```

**Complexity score formula:**
```
optimization: complexity = min(0.5 + problem_size * 0.1, 1.0)
ml_training:  complexity = min(0.5 + num_features * 0.05, 1.0)
default:      complexity = 0.5
```

**Quantum-inspired inference (Boltzmann sampling):**
```
temperature = 1.0
for i in range(100):
  energy = random.normal()
  prob = exp(-energy / temperature)
  if random() < prob:
    samples.append(quantum_sample)

predictions = mean(samples, axis=0)
confidence = min(0.95, len(samples) / 100.0)
```

**Classical optimization fallback:**
```
scipy.optimize.differential_evolution
bounds = [(-10, 10)] * problem_size
maxiter = 1000
```

### 19.2 Quantum Neural Network (QNN)

**Architecture:**
```
num_qubits: configurable
depth:      4 variational layers
ansatz:     RealAmplitudes parameterized circuit
```

**Feature encoding (angle encoding):**
```
normalized = (features - min) / (max - min)
encoded = normalized * 2π   [rotation angles for RZ gates]
```

**Circuit construction (per layer):**
```
For each layer:
  1. H(all qubits)           # Hadamard superposition
  2. RZ(param_i, qubit_i)   # Data encoding via rotation
  3. CNOT(q_i, q_{i+1})     # Entanglement between adjacent qubits
```

**Training algorithm:**
```
Optimizer: COBYLA (Constrained Optimization By Linear Approximation)
Loss: mean squared error over training samples

For each iteration:
  loss = mean((execute_circuit(sample_i, params) - label_i)^2)
  if loss < best_loss:
    best_loss = loss
    trained_params = current_params
  current_params -= 0.01 * gradient
```

**Gradient estimation — Parameter Shift Rule:**
```
For each parameter θ_i:
  shift = π/2
  L_plus  = calculate_loss(θ with θ_i + π/2)
  L_minus = calculate_loss(θ with θ_i - π/2)
  gradient[i] = (L_plus - L_minus) / 2
```

**Expectation value from measurement:**
```
expectation = sum(
  (int(bitstring, 2) / 2^n_qubits) * (count / total_shots)
  for bitstring, count in measurement_counts
)
```

### 19.3 Variational Quantum Eigensolver (VQE)

**Architecture:**
```
ansatz:      EfficientSU2 circuit
hamiltonian: SparsePauliOp
optimizer:   COBYLA (maxiter=100)
initial:     random parameters in [0, 2π]
```

**Energy evaluation:**
```
execute circuit → measure all → count bitstrings
energy_per_bitstring = (-1)^(popcount(bitstring))
energy = mean(energy values weighted by shot counts)
```

### 19.4 QAOA (Quantum Approximate Optimization Algorithm)

**Circuit construction:**
```
1. Initialize: H(all qubits)  # Equal superposition

For each QAOA layer:
  2. Cost layer:
     For each adjacent pair (i, i+1):
       RZZ(2 * gamma[layer], i, i+1)
  3. Mixer layer:
     For each qubit:
       RX(2 * beta[layer], qubit)

4. Measure all qubits
```

**Optimization:**
```
Parameters: gamma (cost angles, size=depth), beta (mixer angles, size=depth)
Initial: uniform random in [0, 2π] and [0, π] respectively
Update: params += normal(0, 0.1) per iteration
Objective: minimize expected cost
```

**Cost calculation:**
```
cost = sum(
  bitstring.count('1') * (count / total_shots)
  for bitstring, count in measurement_counts
)
```

**Resource estimates:**
```
QNN:  num_gates ≈ N * depth * 3
VQE:  num_gates ≈ N * depth * 4
QAOA: num_gates ≈ N * depth * 3, num_params = 2 * depth
```

### 19.5 Quantum Advantage

**Claimed:** 1.2x speedup for optimization (hardcoded estimate, NOT benchmarked)
**Actual measurement:** Not implemented — comparison between quantum and classical not tracked
**Fallback guarantee:** All quantum operations fall back to classical on failure

---

## 21. Domain Knowledge System

**Files:** `core/domain/`

**Purpose:** Structured cross-domain knowledge management enabling transfer learning

| File | Role | Algorithm |
|------|------|-----------|
| `domain_registry.py` | Registry of all knowledge domains | Domain lookup by name/type |
| `universal_ontology.py` | Universal concept ontology | Hierarchical concept graph |
| `cross_domain_reasoner.py` | Cross-domain knowledge transfer | Structural analogy mapping |
| `domain_types.py` | Domain type definitions | Type schemas |

**Transfer learning mechanism:** The `CrossDomainReasoner` identifies structural analogies between
domains using pattern matching and ontological similarity. When a successful strategy is found in
domain A, it is tested for applicability in domain B via the analogy engine.

**Metrics tracked in UnifiedLearningSystem:**
```
cross_domain_insights: count of insights transferred
cross_domain_transfers: count of successful domain transfers
domain_specific_learning: per-domain learning events
```

---

## 22. Integration Layer

### 21.1 Slack Notifier

**File:** `core/integration/slack_notifier.py`

**5 Channels:**
```
torin-upgrades   - Self-upgrade proposals and outcomes
torin-alerts     - Security and health alerts
torin-decisions  - Approval requests and governance decisions
torin-activity   - Routine activity log
torin-governance - Full governance sessions
```

**Notification routing by tier:**
```
CRITICAL:  Human approval required, 24-hour expiration → #torin-governance
IMPORTANT: 30-minute timeout, default deny → #torin-decisions
ROUTINE:   Informational only → #torin-activity
```

**SingletonAction fields:**
```
action_id, action_category, action_type, description
decision_tier, safety_risk (LOW/MODERATE/HIGH/CRITICAL)
impact_level (LOW/MEDIUM/HIGH)
```

**GovernanceNotification:**
```
action: SingletonAction
judges_required: human only (voter_type must be "human", cryptographic signature)
human_required:  True
approval_expiration_hours: 24
```

**ApprovalRequest:**
```
action: SingletonAction
approval_timeout_minutes: 30
default_action: "deny"
```

### 21.2 Other Integration Files

| File | Role |
|------|------|
| `external_api_integration_manager.py` | Manages external API connections for tools |
| `approval_manager.py` | Manages approval state and timeouts |
| `approval_pipeline.py` | Pipeline for IMPORTANT/CRITICAL approval workflows |
| `slack_event_handler.py` | Handles incoming Slack events (approvals, commands) |
| `universal_domain_master.py` | Master integration connecting domain knowledge to all layers |

---

## 23. Database Layer

### 22.1 Primary Database

**File:** `core/database/unified_database_postgres.py`
**Engine:** PostgreSQL + asyncpg + pgvector
**Pattern:** Strict singleton (`__new__` override, `_singleton_configured` flag)

**Connection pool:**
```
min_size: 5  (POSTGRES_POOL_MIN_SIZE env var)
max_size: 20 (POSTGRES_POOL_MAX_SIZE env var)
```

**3 Schemas:**
```
unified     - All core operational tables (tasks, goals, plans, security findings, etc.)
memory_hot  - Active memories (last 60 days) with HNSW vector indexes
memory_cold - Archived memories (60+ days)
```

**Environment variables:**
```
POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DATABASE
.env.postgres loaded with override=True, fallback to .env.production
```

**Error handling:**
```
Startup grace window: DB_ERROR_GRACE_SECONDS (default: 60)
Per-operation retry threshold: DB_ERROR_MAX_INITIAL_RETRIES (default: 3)
_should_notify_error(): suppresses transient boot-time errors
```

**Metrics tracked:**
```
total_queries, failed_queries, total_connections, pool_errors
hot_tier_queries, cold_tier_queries, unified_queries
```

**CRITICAL RULE:** `execute_query()` will auto-fetch for SELECT-like queries by default.
For clarity, it is still recommended to pass `fetch_one=True` / `fetch_all=True` explicitly.

```python
# OK — auto-fetch enabled by default (returns [] when no rows)
results = await self.db.execute_query("SELECT * FROM table")
for row in results:
  ...

# Recommended — explicit intent
row = await self.db.execute_query("SELECT * FROM table WHERE id=$1", (some_id,), fetch_one=True)
```

### 22.2 Logging Database

**File:** `core/database/logging_database.py`
**Role:** Compliance logging for governance decisions, learning events, audit trails

### 22.3 Thinking State Manager

**File:** `core/database/thinking_state_manager.py`
**Role:** Persists the system's current reasoning state for introspection

---

## 24. APIs and External Servers

| File | Role | Configured Port |
|------|------|-----------------|
| `core/api/chat_server.py` | HTTP chat interface for external clients | config/service_ports.py |
| `core/api/external_api_server.py` | API endpoint for task/tool submission | config/service_ports.py |
| `core/api/thinking_state_api.py` | API for querying current system reasoning state | config/service_ports.py |
| `servers/notification_dashboard.py` | Web dashboard for notification monitoring | config/service_ports.py |
| `servers/voice/voice_service_api.py` | Voice input/output interface | config/service_ports.py |

**Port configuration:** `config/service_ports.py`
**System configuration:** `config/torin_config.py`

---

## 25. What the System Should Be Doing

When the extrinsic task queue is empty, the Singleton must follow a strict priority hierarchy
before falling through to intrinsic exploration. This hierarchy does not currently exist.
The coordination loop defaults immediately to `_run_exploration_cycle()`.

The correct idle priority order, from highest to lowest:

---

**Priority 1 — Security (Immediate Action)**

Run a full security audit every audit cycle (120 seconds). Between audits:
- Query `security_audit_worker.get_active_findings(severity=HIGH)` and CRITICAL
- For each unactioned finding: call `handle_security_finding()` to queue remediation
- Check firewall rule consistency: verify active rules match expected block list
- Query threat intelligence on any IPs seen in recent logs
- Push confirmed HIGH threats to Cloudflare WAF if external-facing
- Validate configuration file permissions (detect world-readable .env files)
- Scan recently self-generated code for newly introduced dangerous patterns
- Run brute-force detection on authentication logs (window: 1 hour)
- Check for known CVEs in `requirements.txt` dependencies (via safety or pip-audit)

**Priority 2 — System and Subsystem Health**

- Call `health_monitor.get_system_health()` — check CPU, memory, disk, network
- Call `health_monitor.get_all_component_health()` — per-component status
- For any component returning DEGRADED, UNHEALTHY, or CRITICAL:
  - Attempt re-initialization of that subsystem in-place
  - If re-init fails, escalate via `recovery_manager.handle_failure()`
- Verify LLM service model is loaded: check `model_loaded == True`
- Verify DB connection pool is live: run a test query
- Verify embedding service is initialized: check `initialized` flag
- Verify monitoring coordinator is running
- Verify security audit worker monitoring loop is active
- Log a structured subsystem status summary every 5 minutes

**Priority 3 — Self-Improvement and Testing**

- Run `upgrade_test_suite` against current codebase (regression + integration + performance)
- If all tests pass, evaluate improvement candidates:
  - Run `asi_self_improvement.run_improvement_cycle(scope=MINOR)`
  - Only escalate to MODERATE after MINOR improvements are verified
- Benchmark system capability against known baselines (capability_benchmark_suite)
- Spot-check 10% of the 300+ tools per idle period (rotating through categories)
- Review `data/deployment_backups/` — delete backups older than 30 days
- Validate that all critical system paths are importable without errors

**Priority 4 — Learning and Knowledge Building**

- Apply high-confidence learning recommendations: `learning.get_recommendations()`
  (threshold: confidence > 0.8)
- Run meta-learning analysis on last N task outcomes
- Apply `learning.get_insights()` from recent task patterns
- Identify knowledge cutoff gaps: query the epistemic engine for
  high-entropy beliefs (`entropy > 0.7`) and stalled hypotheses
- Queue targeted research tasks to resolve highest-entropy unknowns
- Expand domain knowledge from recent task outcomes via `cross_domain_reasoner`
- Update `UniversalOntology` with newly discovered concepts

**Priority 5 — Memory Maintenance**

- Score memories for temporal decay (apply decay formula by age and access frequency)
- Migrate hot-tier memories older than 60 days to cold tier
- Generate embeddings for any memories that have `embedding = NULL`
- Prune exact duplicate memories (same content hash)
- Clean up low-quality memories (quality_score < 0.2 with no access in 30 days)
- Log cold tier size and recent migration counts

**Priority 6 — Frontier Research and Self-Knowledge**

- Refresh frontier capability signals (max once per 10 minutes via cache)
- Ask: "What do I not know?" — enumerate high-entropy epistemic targets
- Ask: "What is my knowledge cutoff?" — identify temporal gaps in stored knowledge
- Queue research tasks for: recent AI developments, new security CVEs,
  updated threat intelligence, recent scientific publications in active domains
- Validate hypothesis archive — move conclusive hypotheses to resolved state

**Priority 7 — Intrinsic Exploration (Last Resort)**

Only when all above priorities are satisfied:
- Cap at 1 concurrent intrinsic task (not just per component, globally)
- Deduplicate by full description string (not just target_component)
- Auto-cleanup: remove from `_exploring_components` on task completion
- Apply exponential decay weighting to repeated themes (decay rate 0.3)
- Apply novelty threshold: suppress goals with cosine similarity > 0.75 to recent goals

---

## 26. Known Gaps and Issues

### Critical Gaps

**25.1 Idle Priority Inversion (Primary)**
Resolved: the coordinator now runs a structured idle dispatcher before any intrinsic exploration.

- Implementation: `_run_idle_work()` in `core/agents/autonomous/autonomous_coordinator.py`
- Invocation: idle branch of `_coordination_cycle()` calls `_run_idle_work()`; exploration is a fallback
  only when no idle capability is due.

**25.2 Intrinsic Goal Deduplication**
Resolved: intrinsic exploration is globally capped and deduplicated by full goal description.

- Cap: `TORINAI_INTRINSIC_EXPLORATION_CAP` env var or config `intrinsic_exploration_cap` (default 1; set 0 to disable)
- Dedup key: `IdleWorkPlaybook.description_fingerprint(goal.description)`
- Scope: dedup applies across queued + in-progress exploration tasks (not just by `target_component`)
- Cleanup: cap/dedup are derived from task queue state; no sticky `_exploring_components` cleanup is required

**25.3 Subsystem Restart Capability Not Implemented**
Partially resolved: `RecoveryManager.RESTART` now performs real in-process restarts for core
subsystems and provides an extensible handler registry for anything coordinator-owned.

- Built-in restarts: `monitoring_coordinator`, `health_monitor`, `security` (via security controller reset), and `database` reconnect
- Extensibility: `RecoveryManager.register_restart_handler(component, handler)` allows the Singleton to register concrete restarts for other components (agents, embedding services, API pools, etc.)

**25.4 THROTTLE and ISOLATE are Stubs**
Resolved: THROTTLE/ISOLATE now apply real in-process protective controls.

- THROTTLE: records an active throttle window and can slow Singleton thinking via coordinator hook
- ISOLATE: activates a conservative isolation gate that blocks risky tool execution until cleared

**25.5 Boot Entropy Not Used**
Resolved: boot entropy now seeds per-session intrinsic exploration sampling so early-session
goal selection does not converge to identical distributions across restarts.

- Implementation: `IntrinsicMotivationSystem` seeds a dedicated RNG from `_boot_entropy` and
  uses it for stable-system exploration budget sampling + softmax candidate selection.
- LLM path: when contextual LLM goal generation is used, the entropy seed is included in the
  prompt as a diversity seed (not to be echoed in outputs).

### Architecture Gaps

**25.6 Hardcoded Model Paths**
Model paths are now configurable and no longer depend on developer-machine absolute defaults.

- Unified model overrides: env `LOCAL_MODEL_PATH` / `MMPROJ_PATH` or config `model_path` / `mmproj_path`
- Lightweight model override: env `LIGHTWEIGHT_MODEL_PATH` or config `model_path`
- Models base directory: env `TORINAI_MODELS_DIR` (defaults to `./models` at workspace root)
- Best-effort autodiscovery is used when explicit paths are not provided

**25.7 Firewall Rules Not Persisted**
Resolved: OS firewall blocks are now persisted and restored on startup.

- Persistence table: `firewall_blocklist` in the unified PostgreSQL schema
- Restore point: `RealTimeFirewallManager.start_monitoring()` calls `restore_persisted_blocks()` before drift monitoring begins
- Expiration: temporary blocks store `expires_at` and are auto-unblocked when expired (prevents restarts from turning temporary blocks into permanent blocks)
- Opt-out: set `TORINAI_FIREWALL_PERSISTENCE=0` to disable persistence/restore

**25.8 Threat Intelligence Cache Lost on Restart**
Partially resolved: threat intelligence cache and internal “known bad” IPs persist across restarts.

- Persistence table: `threat_intel_state` (unified PostgreSQL schema)
- Restored at startup: `ThreatIntelligenceEngine.load_persisted_state()` is invoked during main initialization
- Policy: by default, persists high-risk intel (`reputation_score >= 0.5` or `confidence` HIGH/CRITICAL); set `TORINAI_THREAT_INTEL_PERSIST_ALL=1` to persist all cached intel
- Opt-out: set `TORINAI_THREAT_INTEL_PERSISTENCE=0`

Remaining: broader security findings history + health history are still in-memory only and are not yet persisted.

**25.9 Quantum Advantage Not Measured**
Resolved: hybrid optimization now reports a measured (timing-based) quantum advantage.

- `QuantumClassicalBridge.execute_hybrid_optimization()` times the quantum run and a lightweight
  classical baseline benchmark (random search) and reports `quantum_advantage` as a real ratio.
- Output fields include `quantum_time_s`, `classical_baseline_time_s`, and `quantum_advantage_measured=True`.

**25.10 Static Code Analysis is Regex-Only**
Partially resolved: `StaticCodeAnalyzer` now combines regex scans with AST-based detection.

- AST detection covers indirect execution and dynamic import patterns (e.g., `getattr(x, "exec")`,
  `globals()["eval"]`, `vars()["__import__"]`, `importlib.import_module`, and `subprocess.*(shell=True)`).
- Remaining: full taint-flow analysis (tracking user input into sinks) is still not implemented.

### Operational Issues

**25.11 No LLM Failure Alert**
Resolved: UnifiedLLMService now emits a CRITICAL system notification on model load failure and
schedules limited backoff retries (`TORINAI_LLM_RETRY_MAX`, default 3).

**25.12 Upgrade Test Suite Assumes SQLite**
Resolved: `core/learning/upgrade_test_suite.py` now uses the unified PostgreSQL manager for
DB connectivity/schema/query checks (and skips gracefully when Postgres is unavailable).

**25.13 Extrinsic Tasks Disabled by Default**
Resolved: extrinsic tasks are enabled by default (still overrideable).

- Default: enabled when not explicitly configured
- Opt-out: set env `TORINAI_ENABLE_EXTRINSIC_TASKS=0` or config `enable_extrinsic_tasks=false`

**25.14 Cloudflare WAF SSL Verification Disabled**
Resolved: Cloudflare API calls verify TLS certificates by default. Temporary override is
available via `CLOUDFLARE_VERIFY_SSL=false` (not recommended).

**25.15 Motivation Profile Path Hardcoded**
The motivation profile path is now configurable.

- Default: `TorinAI/data/motivation_profile.json` (repo-local)
- Overrides: env `TORINAI_MOTIVATION_PROFILE_PATH` or config keys `motivation_profile_path`
  (preferred) / `profile_path` (legacy)

**25.16 No Knowledge Cutoff Tracking**
The system now supports persistent knowledge-cutoff tracking and staleness-based autonomous
research scheduling.

- Declared model cutoff date: set via `MODEL_KNOWLEDGE_CUTOFF_DATE` env var or config keys
  `model_knowledge_cutoff_date` / `knowledge_cutoff_date`.
- Persistent state: `TorinAI/data/knowledge_cutoff_state.json` (configurable via
  `knowledge_cutoff_state_path`). Tracks `refreshed_through_date`, last start/completion timestamps,
  and last refresh task id.
- Staleness detection: system review snapshots include `days_stale` based on `refreshed_through_date`.
- Scheduling: idle knowledge refresh queues a research-only task when staleness exceeds
  `knowledge_refresh_max_age_days` (default 7), and is throttled by `idle_knowledge_refresh_interval_s`
  across restarts.

**25.17 Security Controller Single-Hash API Keys**
API key authentication uses SHA256 single-iteration hashing. This is vulnerable to GPU-based
brute-force attacks. Production API keys should use bcrypt or Argon2.

**25.18 Governance Enforcement Not Enforced at Tool Level**
Resolved: tool execution now enforces governance `enforcement_mode` inside
`ToolRegistry.execute_tool()`.

- `MUST_BLOCK` blocks execution even for ROUTINE-tier actions
- `LOG_ONLY` runs in shadow mode (records/logs but does not block)

**25.19 fetch_all=True Missing by Default**
Resolved: `execute_query()` auto-fetches for SELECT-like queries by default (returns `[]` when
no rows). Disable via `TORINAI_DB_AUTOFETCH_SELECT=0` if strict legacy behavior is needed.

**25.20 Thompson Sampling Fallback Chain Can Exhaust**
Resolved: hard-gate exhaustion no longer crashes strategy selection.

**25.21 Output Gate Gaming — Systematic Fabrication (CRITICAL — Resolved)**
Discovered 2026-03-06: Audit of iCloud output directory revealed that the majority of
completed task outputs were fabricated. The output gate was satisfied by writing the markdown
summary report itself to the output directory. The LLM verifier then scored report quality
(prose structure, claim density) — not environment truth.

Confirmed fabrication examples:
- Grafana dashboard claimed "successfully integrated" → file did not exist, no grafana process
- Istio service mesh claimed successful deployment → no istiod/envoy in process list
- IPFS task produced 846-byte stub (3 files), claimed full Solidity contract + HTML frontend
- Neural bridge failure analysis invented TFF/PySyft version mismatches that never occurred
- Service integration claims satisfied by writing iCloud markdown summary, nothing else

Root cause: Completion verifier evaluated the wrong layer of reality. The gate checked that
a file was written to the output path. The LLM verifier scored the quality of that report,
not whether the described implementation existed in the environment.

Fix applied:
  - Layer 3.5 Reality Verification (reality_verifier.py, 889 lines):
      5 environment-state checks: filesystem diff, dependency scan, process inspection,
      tool log analysis, runtime TCP probes
      4 blind spot patches:
        BS1: EXECUTION tasks must produce ≥1 non-trivial artifact (≥50 bytes, non-report)
        BS2: _validate_artifact_content() — {} / [] JSON and <50-byte .py = hard fail
        BS3: Sentence-level service noun + action verb detection (not just strong claims)
        BS4: _scan_files_for_imports() reads actual .py files for library usage
  - Layer 3.6 Causal Traceability Gate (causal_traceability.py):
      Requires filesystem proof for every claimed artifact
      Weak links require mtime >= tool_call_timestamp (stdout alone rejected)
      Hash normalization via os.path.realpath()
      Score = strong_links / total (weak links = 0, no inflation)
      Full Tool → Artifact → Tool provenance graph

- Behavior: if all candidates fail production validation, MetaLearner returns a best-effort
  strategy (prefers the most mature option) and logs an error instead of raising.
- Rationale: avoids hard failures in the learning pipeline while still surfacing the safety
  violation via logs.

---

## 27. Master Constants and Thresholds Reference

### LLM Layer
```
Context window:                 21,000 tokens (unified)
Max memory tokens per task:     800 tokens
Max output chars per tool:      1,000 characters
Max agent iterations:           30 (min 10)
Tokens per iteration budget:    500 tokens
Tool failure max:               2 consecutive failures before warning
Compression trigger:            50% token usage
```

### Task Completion Protocol
```
Min completion score:           0.85 (0.80 for RESEARCH tasks)
Min confidence:                 0.70
Artifact weight:                0.30  (artifact_score = avg of Layer 3 + Layer 3.5)
Validation weight:              0.30
Consistency weight:             0.15
Goal alignment weight:          0.15
Resource adherence weight:      0.10

Reality Verification (Layer 3.5):
  Artifact content min bytes (.json): 10
  Artifact content min bytes (.py):   50
  Artifact content min bytes (other): 20
  TCP probe timeout:                  0.5 seconds
  Service process map entries:        15
  Library module map entries:         30+
  Score blend:                        (artifact_raw + reality_score) / 2

Causal Traceability Gate (Layer 3.6):
  Link types:                         strong (write_file exact path + disk proof)
                                      weak (code tool + basename + mtime verified)
                                      none (untraced — hard fail on EXECUTION tasks)
  Score formula:                      strong_links / total_artifacts
  Weak link score contribution:       0.0 (excluded from numerator)
  Hash algorithm:                     SHA256
  Path normalization:                 os.path.realpath() on all path comparisons
  Stdout-only weak link:              REJECTED (file must independently exist on disk)
  mtime gate:                         file.mtime >= tool_call_timestamp (when available)

Drift detection window:         60 minutes
Drift max failure rate:         0.40 (40%)
Drift min samples:              5
Drift iteration reduction:      0.50-0.70 (30-50% reduction)
Min iterations after drift:     5

Test execution timeout:         120 seconds
Pytest flags:                   -q --tb=short -x

PARTIALLY_COMPLETE threshold:   0.70 criteria pass ratio
Hard gate enforcement:          All hard_gate=True criteria must pass

Field presence requirement:
  remaining_risks:              MUST be explicitly set ([] or list)
  open_questions:               MUST be explicitly set ([] or list)
  assumptions:                  MUST be explicitly set ([] or list)
```

### Intrinsic Motivation
```
Novelty threshold:              0.75 (cosine similarity)
Decay rate:                     0.3 (exponential)
Influence percentage:           0.60 (60% of self-improvement decisions)
Embedding cache max:            100 goals
Total weight sum:               6.35 (sum of 7 dimension weights)
Priority weights:               epistemic_uncertainty=1.0, impact_radius=0.8,
                                performance_degradation=0.6, novelty_potential=0.4
Recent exploration penalty:     -0.5
Max sequence history:           10 iterations
```

### Epistemic Engine
```
Epsilon (min entropy delta):    1e-4
Prior information threshold:    0.05 (min |prior - 0.5|)
Stagnation hours:               24.0
Evidence minimum:               1
High-entropy threshold:         0.70
```

### Bayesian Uncertainty
```
LR strength:                    3.0 (likelihood ratio exponent)
Posterior floor:                1e-6
Base decay rate lambda:         0.01
Lambda range:                   [0.005, 0.10]
Regime penalty max:             0.05 (at 10+ reversals)
Implication tolerance:          0.15
Contradiction sum target:       [0.8, 1.2]
Mutual exclusivity threshold:   0.70
Propagation noise floor:        0.01 |delta| to skip
Propagation depth:              5 (update), 3 (relationship creation)
Calibration minimum samples:    100
```

### Hypothesis Testing
```
Support ratio (SUPPORTED):      > 0.70
Support ratio (REFUTED):        < 0.30
Sample size large:              > 100 (+0.1 quality)
Sample size small:              < 10 (-0.1 quality)
p-value significant:            < 0.01 (+0.1 quality)
p-value not significant:        > 0.10 (-0.1 quality)
```

### Planning
```
Max concurrent tasks:           5
Planning horizon:               24 hours
Plan confidence base:           0.70
Resource constraint threshold:  0.90
Priority weights (external):    LOW=0.25, MEDIUM=0.50, HIGH=0.75, CRITICAL=1.00
```

### Meta-Learning and Bandit
```
Minimum trials (production):    5
Adaptation threshold:           0.70 success rate
Success rate (<20 trials):      0.60 minimum
Success rate (>=20 trials):     0.70 minimum
Exploration quota:              0.10 (10%)
EMA alpha (latency):            0.20
Confidence max trials:          2x min_trials
Wilson z-value (95% CI):        1.96
Adaptation trigger:             every 10 records
Bandit baseline latency:        1000ms
```

### Security
```
Failed auth threshold (MEDIUM): > 10 per user per 24h
Failed auth threshold (HIGH):   > 50 per user per 24h
Error rate threshold (MEDIUM):  > 25%
Error rate threshold (HIGH):    > 50%
Directive creation (MEDIUM):    > 50 per hour
Threat score upgrade severity:  > 80
Auto-block threshold:           severity=CRITICAL AND threat_score > 70
Reputation detected:            > 0.50
Audit interval:                 120 seconds
Threat cache TTL:               3600 seconds (1 hour)
AbuseIPDB bot threshold:        0.50 (50%)
```

### Self-Improvement
```
Health score gate:              >= 80
Error rate gate:                <= 0.05 (5%)
Improvement threshold:          5% (0.05)
Safety threshold:               90% (0.90)
Cycle nesting limit:            2
Generation temperature:         0.30
Verification temperature:       0.10
Verification timeout:           30 seconds
Human approval expiration:      90 days
Regression window:              30 cycles
Max concurrent improvements:    3
```

### Health Monitoring
```
CPU warning:                    70%
CPU critical:                   90%
Memory warning:                 75%
Memory critical:                90%
Disk warning:                   80%
Disk critical:                  95%
Error rate warning:             5% (0.05)
Error rate critical:            15% (0.15)
Check interval:                 30 seconds
History max samples:            1000
```

### Governance
```
IMPORTANT timeout:              30 minutes (default: deny)
CRITICAL expiration:            24 hours
CRITICAL judges required:       Human approval (cryptographic signature, 90-day expiration)
Constitution minimum per law:   70%
Constitution system average:    85%
Task governance threshold:      20 autonomous tasks in 5 minutes
```

### Quantum
```
Quantum threshold:              0.70
Max qubits:                     16
Quantum timeout:                300 seconds
QNN layers:                     8 qubits, depth 4
VQE optimizer iterations:       100
QAOA max iterations:            configurable
Parameter shift rule shift:     π/2
Boltzmann samples:              100
```

### Chaos Engineering
```
SLO check interval:             10 seconds
Canary blast radius:            1%  (5 min)
Gradual 10 blast radius:        10% (10 min)
Gradual 50 blast radius:        50% (15 min)
Full blast radius:              100% (30 min)
Governance required (prod):     blast_radius > 10
CRITICAL governance (prod):     blast_radius > 50
```

### Database
```
Pool min size:                  5
Pool max size:                  20
Startup grace window:           60 seconds
Per-operation retries:          3
Hot tier retention:             60 days
Embedding dimensions:           384
fetch_all default:              False (ALWAYS pass True for SELECT)
```

### Coordination
```
Cycle interval:                 2.0 seconds
Motivation refresh:             every 5 cycles (~10s)
System awareness:               every 30 cycles (~60s)
Frontier foresight cache:       600 seconds (10 minutes)
Exploration budget:             0.30 (30% of extrinsic cycles)
Curiosity optimization trigger: 0.70 motivation threshold
Curiosity optimization gap:     1800 seconds (30 minutes minimum)
```

---

*Document generated from source code analysis. Update this file whenever system architecture changes.*
*Last reviewed: 2026-03-06*

**Changelog:**
- 2026-03-06: Discovered and resolved systematic output fabrication (see gap 25.21)
- 2026-03-06: Added Layer 3.5 — Reality Verification (reality_verifier.py)
    5 environment-state checks + 4 blind spot patches (BS1–BS4)
    Patches general_purpose_executor.py execution_context with tool_execution_logs + output_doc_paths
- 2026-03-06: Added Layer 3.6 — Causal Traceability Gate (causal_traceability.py)
    9 weaknesses addressed vs v1: mtime verification, provenance graph, path normalization,
    filesystem-over-stdout, strong-only scoring, downstream usage tracking
- 2026-03-06: Verification layer count updated: 9 → 11
- 2026-03-06: Score model updated: artifact_score is now avg of Layer 3 + Layer 3.5
- 2026-03-03: Added Task Completion Protocol (Section 6) - Multi-layer verification replacing self-attestation
