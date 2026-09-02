# TorinAI

**A persistent, model-optional experimental cognitive architecture.**

TorinAI is a *cognitive substrate*: a system that **derives** conclusions from
evidence it holds, rather than generating text that resembles conclusions. A
language model, when present, is a **teacher** — it may translate an input the
substrate cannot yet read, or propose a candidate the substrate will then check —
but it is never the source of intelligence and is never required to think. The
substrate reasons, learns, remembers, and governs itself model-free by
construction on its core paths.

> *Model-optional ≠ model-free.* The substrate runs without any model; a model is
> an optional source of coverage and suggestions, never an authority over what is
> true.

This repository is a research system. Where a capability is real it is stated
plainly; where it is limited, the limit is stated at the same resolution as the
capability (see [Status & honest limitations](#status--honest-limitations)).

---

## Table of contents

- [The thesis](#the-thesis)
- [Design principles](#design-principles)
- [Architecture at a glance](#architecture-at-a-glance)
- [The substrate self (autonomous coordinator)](#the-substrate-self-autonomous-coordinator)
- [Reasoning](#reasoning)
- [Learning](#learning)
- [Memory](#memory)
- [Governance: constitution, governance agent, directives](#governance-constitution-governance-agent-directives)
- [The model as a teacher](#the-model-as-a-teacher)
- [Persistence](#persistence)
- [Getting started](#getting-started)
- [Testing](#testing)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
- [Status & honest limitations](#status--honest-limitations)

---

## The thesis

Two failures are usually conflated in AI systems: **fabrication** (producing an
answer whether or not there are grounds) and **unearned confidence** (a number
attached to an answer that nothing actually computed). TorinAI separates and
removes them:

1. **Conclusions are derived, and the derivation is retained.** Every answer can
   show its premises, its steps, and the arithmetic behind its confidence.
2. **Confidence is computed by something other than the thing being measured.**
   No component reports its own certainty.
3. **The order of resort is fixed:** what can be *proved*, then what can be
   *derived*, then what can be *proposed* — for every request.
4. **The system can decline.** "I cannot represent this" is a first-class result,
   distinguishable in the record from a low-confidence conclusion.

The substrate accumulates capability by **being taught**, not by pre-training —
the trade it makes is reliability within its coverage, at the cost of coverage
that must be built.

---

## Design principles

These principles are enforced throughout the codebase, and pull requests are held
to them:

- **Single authority.** Each concept has exactly one authoritative owner.
  Reasoning is owned by the `NeuralSymbolicBridge`; learning by the
  `UnifiedLearningSystem` / `MetaLearner`; domains by the `UniversalDomainMaster`;
  belief/uncertainty by the `BayesianUncertaintySystem`; governance decisions by
  the `GovernanceAgent`; the constitution owns the five governance laws. Nothing
  bypasses an authority or stands up a second one for the same concept.
- **Model-free by construction on the core paths.** The reasoning, acting, and
  learning-credit paths take no model call. A model is reached only as a last
  resort for coverage, never as a factor in *whether* the substrate reasons.
- **Honesty over green.** A component that cannot do its work surfaces the honest
  status and leaves the durable mark off — it never stamps success to clear a
  queue. Completion is *verified* against re-observed world evidence, not
  self-declared.
- **No fallbacks, no false positives, no false negatives.** A missing or broken
  dependency is surfaced with a real error and a metric, never silently swallowed
  into a fabricated "no."
- **Event-driven, not clock-driven.** The self reacts to the events that should
  drive it; genuinely periodic work (sampling the outside world) lives on one
  scheduler (the queue authority), not scattered polls.
- **Everything measured is persisted.** Measured reasoning difficulty and quality,
  beliefs, schemas, directives, and telemetry survive a restart.

---

## Architecture at a glance

```
                         ┌───────────────────────────────────────────┐
                         │        AutonomousCoordinator (the self)     │
                         │  live loop · event dispatch · reactions     │
                         │  intrinsic motivation · appraisal · arbiter │
                         └───────────────────────────────────────────┘
              emits/consumes SelfEvents (TASK_COMPLETED, OUTCOME_OBSERVED,
              COMPETENCE_CHANGED, EVIDENCE_ADMITTED, JOB_COMPLETED, …)
      ┌───────────────┬───────────────┬───────────────┬───────────────┬───────────────┐
      ▼               ▼               ▼               ▼               ▼               ▼
┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
│ Reasoning │   │ Learning  │   │  Memory   │   │  Domains  │   │Governance │   │  Queue    │
│ authority │   │ authority │   │  agent    │   │ authority │   │ + consti- │   │ authority │
│ (Neural   │   │ (Unified  │   │(Postgres/ │   │(Universal │   │ tution +  │   │(work/sched│
│  Bridge)  │   │ Learning /│   │ pgvector) │   │  Domain   │   │ directives│   │ /await)   │
│           │   │MetaLearner│   │           │   │  Master)  │   │           │   │           │
└───────────┘   └───────────┘   └───────────┘   └───────────┘   └───────────┘   └───────────┘
              a model (optional) sits OUTSIDE this — reached only for coverage
```

Everything runs against one unified PostgreSQL database (`unified.*` schema). The
coordinator is the substrate's *self*: the earlier standalone `self_model.py` was
collapsed into it, so the live loop, the faculties, conversation, and identity all
belong to one object.

---

## The substrate self (autonomous coordinator)

`core/agents/autonomous/autonomous_coordinator.py` is the self. It runs a
continuous cognition loop and reacts to typed **self-events** instead of polling:

- **Event dispatch.** `on(event_type, handler, mode, priority)` registers a
  reaction; `emit(SelfEvent)` fires it — synchronous reactions inline, expensive
  ones on a reactive drain worker with its own concurrency budget (separate from
  the acting cap, so learning never steals acting slots).
- **Intrinsic motivation & affect.** Curiosity, competence, novelty, and impact
  drives (`intrinsic_motivation.py`) are computed from real system context and
  drive goal generation; affect is updated event-driven from task outcomes.
- **Appraisal → disposition.** The `AppraisalSystem` turns outcomes into
  interoceptive pressures (valence, attribution, controllability, …); the
  `BehaviorArbiter` turns those into a decision (explore / replan / escalate /
  proceed) that real control points consume — e.g. an externally-attributed
  failure suppresses wasted self-directed diagnostics.
- **Idle tiers.** Security audit, health, meta-learning, domain expansion,
  operator induction/exploration, analogy discovery, self-optimization,
  constitutional-alignment, self-state refresh, and more, all scheduled as
  recurring jobs on the **queue authority** — the one owner of cadence.
- **Health & recovery.** Health events drive diagnose → recover → verify on
  events; security findings drive detection → remediation → verification →
  closure.

---

## Reasoning

The reasoning authority is `NeuralSymbolicBridge` (`core/reasoning/neural_bridge.py`),
reached by `get_neural_bridge()`. Every reasoning request enters through
`reason(ReasoningRequest)` and leaves with a `ReasoningResult` carrying a
credit-assignment contract in its metadata (`verified`, `formalized`, `reason`,
`model_required`, `model_available`).

**The order of resort** (all model-free until the last step):

1. **What can be proved** — deterministic formalizers turn the query into the
   substrate's own grammar; a solver decides it. Arithmetic goes to a Z3 constraint
   solver; sequences are settled by *inducing* their rule; relational queries are
   answered over the learned concept graph via a typed relation algebra;
   propositional goals are proved/refuted by the SMT proof engine.
2. **What can be derived** — the **eleven kinds of classical inference**
   (`abstract_reasoning_engine.py`): deductive, inductive, abductive, analogical,
   causal, probabilistic, fuzzy, temporal, spatial, logical, counterfactual. Each
   is a distinct procedure with its own applicability condition, its own basis for
   confidence (e.g. Laplace's rule of succession for induction, weakest-link for
   causal chains, Zadeh operators for fuzzy degree), and its own way of declining.
3. **What can be proposed** — only if neither settles it is a model consulted, and
   only for coverage. A model may propose; it may never attest.

Supporting engines: **beliefs & uncertainty** (`bayesian_uncertainty.py` —
odds-form Bayesian updates, temporal decay, consistency, calibration); the
**epistemic engine** (`epistemic_engine.py` — turns tool observations into beliefs
and surfaces the unstable regions that drive exploration); **hierarchical
abstraction** (`hierarchical_abstraction.py` — induces probabilistic schemas from
clustered experience); **typed relation algebra** (`relation_algebra.py` —
licensed composition so *reachability is never mistaken for entailment*); the
**advanced proof engine** (Z3/SMT refutation + a direct forward-chaining prover);
and the temporal, hypothesis-testing, formal-argumentation, and analogy engines.

The bridge measures its own behaviour: per-kind **difficulty** (latency) and
**quality** (how often a kind, once considered, settles a query), both persisted
and used to prefer the kinds that actually work.

See [`core/reasoning/REASONING.md`](core/reasoning/REASONING.md) (the paper),
[`REASONING_PIPELINE.md`](core/reasoning/REASONING_PIPELINE.md) (method-level
reference), and [`REASONING_PATHS_VERIFIED.md`](core/reasoning/REASONING_PATHS_VERIFIED.md)
(the eleven paths tested against the live system).

---

## Learning

`UnifiedLearningSystem` (`core/learning/unified_learning_system.py`) is the one
learning authority; contributors *propose*, they never self-attest. Within it, the
`MetaLearner` (`core/learning/meta_learning.py`) owns strategy/arm credit via a
Thompson-sampling bandit with a credit-assignment taxonomy (a strategy is never
charged for an infrastructure failure). Rule **induction** derives operators and
sequence rules from demonstrations model-free; domain learning expands the
substrate's map of subjects from real task outcomes.

"Which choice works" — which task type, which executor, which directive — is always
the MetaLearner's; no subsystem keeps a parallel learner.

---

## Memory

`MemoryAgent` (`core/agents/memory_agent.py`) owns storage and the maintenance
loops. Memories live in PostgreSQL with **pgvector** embeddings for semantic
retrieval; a write-queue worker runs the full store pipeline off the hot path.
Abstraction and belief reflection are *reasoning*, so they are delegated to the
reasoning authority (the bridge owns beliefs/abstraction), and abstraction is
event-triggered by episodic accumulation rather than a clock.

---

## Governance: constitution, governance agent, directives

Three distinct, non-overlapping layers — do not conflate them:

- **Constitution** (`singleton_constitution.py`) — five *immutable* governance
  laws (Human Autonomy, Transparency, Harm Prevention, Value Alignment,
  Containment). It is the standard the system is judged against: it assesses
  whole-system **drift** and scores any action/policy context against the laws
  (model-free). Live at boot, scheduled, emitting metrics.
- **Governance agent** (`governance_agent.py`) — the compliance-**decision**
  authority. It scores an action against the constitution's laws, applies a
  threshold and external rules, and returns allow/block. It gates real actions
  (via the safety framework and runtime governance).
- **Directives** (`directive_system.py` and helpers) — *mutable, evolvable*
  operating policies in four categories (goal prioritization, resource
  allocation, learning strategy, exploration balance). The substrate
  **self-proposes** a directive from real measured signals on the
  self-optimization tier, the directive is **governed** (DirectiveSystem →
  GovernanceAgent → constitution) before it can exist, it is **learned** as a
  MetaLearner arm (outcomes credit it, the learning authority promotes it), and it
  is **applied** at the corresponding decision point. Constitution constrains;
  directives steer; the governance check keeps every directive inside the
  constitution's bounds.

---

## The model as a teacher

When a language model is available it is used strictly for **coverage**: reading
an input the substrate cannot yet formalize, and proposing candidates the
substrate re-parses and checks. Model proposals carry no confidence of their own,
are ranked below every derived conclusion, contribute nothing to any quality
metric, and are marked as proposals in every record that survives them. Removing
the model changes what the substrate can *read*, not whether it can *reason*.

---

## Persistence

Everything durable lives in one PostgreSQL database under the `unified.*` schema:
beliefs, schemas, domain volatility, reasoning telemetry & quality, the task
queue, directives and their applications/evolution, governance evaluations,
memories (with pgvector), and more. Working state (the intermediate structures a
query builds) is deliberately *not* persisted — it is the derivation, not
knowledge, and is rebuilt each time.

---

## Getting started

**Requirements**

- Python **3.11** (the repo pins a `venv_torin` virtualenv running 3.11.x).
- PostgreSQL with the **pgvector** extension (default local instance: database
  `torinai_db` on port `5433`).
- Optional: a local LLM server (e.g. llama.cpp / an OpenAI-compatible endpoint)
  for the teacher role — the substrate runs without it.

**Install**

```bash
python3.11 -m venv venv_torin
./venv_torin/bin/pip install -r requirements.txt
```

**Configure**

Environment is loaded from `.env.production` and then `.env` (local overrides).
The Postgres connection and optional model endpoint are configured there, e.g.:

```
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DATABASE=torinai_db
POSTGRES_USER=...
POSTGRES_PASSWORD=...
LLM_SERVER_URL=http://localhost:8099   # optional teacher
```

**Run**

The system is orchestrated by `core/main.py`:

```bash
PYTHONPATH="$PWD" ./venv_torin/bin/python3 -m core.main
```

Programmatic bring-up:

```python
from core.main import get_system
system = get_system()
await system.initialize()
coord = system.autonomous_coordinator   # the self
bridge = (await __import__('core.reasoning', fromlist=['get_neural_bridge']).get_neural_bridge())
```

---

## Testing

Tests live under `tests/` (organized by subsystem: `reasoning/`, `memory/`,
`learning/`, `autonomous/`, `governance/`, `integration/`, `chaos/`, …). They run
against real backends — nothing is stubbed. A `torinai-sandbox` container image is
used to run them against the live host services (real Postgres, real model
server); see `REASONING_PATHS_VERIFIED.md` for a reproducible example.

```bash
PYTHONPATH="$PWD" ./venv_torin/bin/python3 tests/reasoning/test_eleven_paths_real.py
```

---

## Repository layout

```
core/
  main.py                     # TorinAISystem: bring-up + orchestration entrypoint
  agents/
    autonomous/               # the self: coordinator, intrinsic motivation, appraisal,
                              #   behavior arbiter, queue authority, constitution,
                              #   directives + governance agent, executor
    memory_agent.py           # memory authority (Postgres + pgvector)
  reasoning/                  # NeuralSymbolicBridge + the eleven kinds, proof/constraint,
                              #   beliefs, epistemic engine, abstraction, relation algebra
  learning/                   # UnifiedLearningSystem, MetaLearner, rule induction
  integration/                # UniversalDomainMaster (domain authority)
  semantics/                  # reading/formalization, derived reader, relation types
  memory/                     # storage, retrieval, embeddings
  governance/ · security/ · safety/   # runtime governance, safety framework
  health/                     # health monitor + recovery
  database/                   # unified PostgreSQL access
tests/                        # subsystem tests, run against real backends
docs/                         # architecture maps, audits, lab notebook, papers
archive/                      # superseded / LLM-era modules kept for provenance
```

---

## Documentation

- **Reasoning:** [`core/reasoning/REASONING.md`](core/reasoning/REASONING.md),
  [`REASONING_PIPELINE.md`](core/reasoning/REASONING_PIPELINE.md),
  [`REASONING_PATHS_VERIFIED.md`](core/reasoning/REASONING_PATHS_VERIFIED.md)
- **Architecture maps:** [`docs/ARCHITECTURE_GRAPH.md`](docs/ARCHITECTURE_GRAPH.md),
  [`docs/AUTONOMOUS_COORDINATOR_MAP.md`](docs/AUTONOMOUS_COORDINATOR_MAP.md),
  [`docs/AFFECT_ARCHITECTURE.md`](docs/AFFECT_ARCHITECTURE.md),
  [`docs/SAFETY_ARCHITECTURE.md`](docs/SAFETY_ARCHITECTURE.md)
- **Direction & retirement of the model:** [`docs/LLM_RETIREMENT.md`](docs/LLM_RETIREMENT.md),
  [`docs/LLM_CALLSITE_MAP.md`](docs/LLM_CALLSITE_MAP.md)
- **Lab notebook & audits:** [`docs/LAB_NOTEBOOK.md`](docs/LAB_NOTEBOOK.md) and the
  various `*_AUDIT*.md` under `docs/`
- Experiment writeups live under `experiments/` (each `EDU-*` / `SESSION-*` has its
  own README).

---

## Status & honest limitations

TorinAI is an **experimental research architecture**, not a product. Stated at the
same resolution as the capabilities:

- **Reading is the binding constraint.** The substrate reasons well over its own
  notation and cannot yet read arbitrary English at the same fidelity; coverage
  grows by teaching. Shrinking this gap (via derived readings, not hand-written
  patterns) is where much of the work is.
- **Coverage is narrow and accumulates.** Every kind of inference operates on what
  the system has been taught to represent.
- **Some engines implement a reduced surface** of the theory they cite (e.g. the
  temporal engine evaluates a subset of operators; hypothesis testing applies a
  significance gate over caller-supplied statistics rather than computing them).
  These are documented in `REASONING_PIPELINE.md` rather than glossed over.
- **Model-optional does not mean feature-complete without a model** — a model
  still widens what inputs the substrate can *read*.

Where you find a claim in this repository, expect to find the code and, usually, a
test or a measurement behind it. Where you find a limitation, expect it stated
plainly.

---

*Dominion Labs — Cognitive Substrate Series.*
