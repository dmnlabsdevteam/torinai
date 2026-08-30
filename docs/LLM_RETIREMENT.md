# Retiring the LLM — substrate-first roadmap

The LLM is scaffolding, not an organ: present only where a substrate faculty has
not yet grown the capability, and it exits as that faculty grows. **No role is
permanently the LLM's.** Full retirement is the destination; the order below is
just the sequence capabilities come out in. State verified against the running
system 2026-08-28.

## Center — the LLM as the thing that decides → RETIRE

- [ ] **Task executor delegates ALL intelligence to the LLM.**
  `core/agents/autonomous/general_purpose_executor.py` picks every tool call via
  `self.llm.generate_with_messages` — its own docstring says "Executes tasks by
  delegating to the teacher model… Delegates ALL intelligence to LLM." This is
  the largest LLM-centered organ left: after building reason/learn/self as
  substrate faculties, the organ that actually *does dispatched work* is still a
  plain LLM agent loop. Replace with substrate execution — the pieces exist
  (`core/learning/demonstration_store.py`, `core/agents/autonomous/planning_engine.py`,
  `core/execution/procedure.py`, the induce→plan→execute growth loop) but today
  run only the learning/exploration path, not dispatched tasks. **THE priority.**
- [x] Identity → the Self (`self_model.IDENTITY_CORE` + `Self.identity_prompt`), verified live
- [x] Reasoning → substrate (`neural_bridge.reason`, 0 LLM calls), verified live
- [x] Reasoning-trace persistence → substrate's own (`neural_bridge` captures its proof
  trace to memory; the LLM chain-of-thought→memory path removed), verified live

## Periphery — language & proposal → SUBSTRATE work (LLM withers, NOT kept)

Each is a substrate faculty. The LLM covers it only until the faculty reaches it;
none of these is a permanent LLM role.

- [ ] **Language IN** — the substrate reads arbitrary human input (reader derives
  readings; EDU-13/14 proved model-free reading over taught vocabulary). LLM parses
  only what the reader cannot yet.
- [ ] **Language OUT** — `conversation.say` / `Self.render` produce fluent output;
  today narrow (subject-copula-object). Grow it; the LLM renders only the gap.
- [ ] **Proposal** — inducer / abduction / teacher-policy propose candidates the
  substrate verifies before attesting. LLM proposes only where those don't yet reach.
- [ ] **Artifact generation** (code / docs / research synthesis) — substrate vs the
  current LLM tools (`code_generation_tools`, `documentation_tools`, `academic_tools`).

## unified_llm cleanup — bookkeeping (follows, does not lead)

- [ ] Drop vision / plug-and-play / structured-output; rename to a bounded, counted
  model *resource* (not a service that sits in the center).
- [ ] Flip `TORIN_MODEL_POLICY` default `NORMAL → model-free`, so any model use is
  explicit and counted rather than the silent default (an LLM-centered leftover).

## Instrumentation

- [ ] **Prometheus exporter rewrite** — `core/monitoring/prometheus_exporter.py`
  measures the MODEL: headline `record_llm_request` (stale `qwen-32b` label), and the
  substrate gauges it declares (`learning_cycles`, `memory_operations`, `db_queries`)
  have no recorder method — declared and never fed. Rewrite to measure the SUBSTRATE:
  the **model census** (`attempts/blocked/executed` per `ModelClass`, from
  `core/model_policy.py` — the "how model-free are we" number), reasoning
  verified-vs-unsettled, faculty/tier activity, learned rules / competence, belief
  stability, disposition. Model use = a counted resource, not the headline.
- [ ] **Event publisher — verify + wire.**
  `core/monitoring/publishers/event_publisher.py` (`DriftEventPublisher` over NATS,
  `nats://localhost:4222`) has ZERO live callers outside its own package — built,
  never connected. Verify it actually works (NATS up) and wire it to the drift
  monitor that produces the events it is meant to publish.
