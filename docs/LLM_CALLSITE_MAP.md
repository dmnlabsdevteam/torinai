# LLM call-site map — repo-wide

**The rule:** the ONLY place a model belongs is **TeacherPolicy** — it proposes,
the substrate verifies and attests. Every other call site below is a capability to
**rewrite for the substrate and move to its authority** — not deleted, rewritten.
Two model services exist and both empty out except the teacher path: `unified_llm`
(35B teacher) and `lightweight_llm` (8B classify/compress). Swept 2026-08-28.

## KEEP — the one model consumer
- `core/learning/teacher_policy.py` — TeacherPolicy: scores lessons by what they
  SEPARATE (model-free scoring); the model only proposes situations.
- `core/learning/llm_teacher.py` — the proposal call (`extract_structured`) the
  policy governs. The model's legitimate home.
- `core/learning/learning_authority.py` — wires the teacher in; contributions are
  CANDIDATE, propose-never-attest.

## REWRITE → substrate, by authority

### Execution — substrate execution (`planning_engine` + `procedure` + induce→plan→execute). THE center.
- `agents/autonomous/general_purpose_executor.py` — `generate_with_messages` agent
  loop + lightweight critic. Its own words: "Delegates ALL intelligence to LLM."
- ~~`agents/autonomous/completion_protocol.py` — `critic_llm.generate` ×4~~ **✅ DONE
  (2026-08-28, verified).** Tested BOTH completion validators against the real system
  first (user's gate): `TaskCompletionValidator` rejects a claimed-but-missing artifact
  (`revision_requested`) via deterministic reality checks with the critic OFF;
  `SuccessValidator` (legacy) rubber-stamped it (`complete=True`) — it checks the result
  DICT (self-attestation), not the world. So: removed the LLM critic entirely (the 3
  `_run_*_validation` methods + `_generate_verification_questions` + helpers + the
  `_check_goal_alignment` LLM branch, keeping its deterministic rubric; executor stops
  supplying `critic_llm`; `initialize()` drops the param) — 2532→1868 lines. Resolved the
  two-validator duplicate: **deleted `SuccessValidator`** (archived), coordinator's
  `'legacy'` fallback now honest (declared-success only, capped confidence, flagged
  UNVERIFIED — no re-introduced self-attestation). One completion authority. NOT needed
  for substrate state-goal execution (completion there = re-observe world holds goal).
  Archived: `archive/completion_llm_critic_pre_retirement_2026-08-28/`.
- `agents/autonomous/autonomous_coordinator.py` — residual `get_llm_service` handle;
  the body should reach cognition through authorities (see the Self migration).
- ~~`agents/autonomous/intrinsic_motivation.py` — `self.llm.generate` / `process_request`~~
  **✅ DONE (2026-08-28, verified end-to-end).** Removed the LLM goal-generation
  (`_generate_contextual_goals_with_llm`), LLM goal-mutation (`_mutate_goal_dimensions`),
  the two LLM fallback branches, `set_llm`/`self.llm`, `_build_system_context`, and the
  static `_generate_exploration_goal` fallback. Design (user's call): **NO FALLBACK, honest
  empty** — goals come only from real substrate signals (metric-driven component
  uncertainties + epistemic unstable-belief goals); when both are empty, no goal that
  cycle. Verified live: real metric-composed goals from injected signals (e.g. "tool_executor
  shows 70% prediction error, 100% failure rate → analyze prediction failures"), honest 0
  goals on empty context, **0 LLM calls**. Coordinator's `set_llm` call removed;
  `test_intrinsic_motivation.py` rewritten to verify the substrate (passes). Caveat: the
  novelty/dedup step still uses an embedding ENCODER (not the LLM) — separate question if
  the bar becomes "no models at all".

### Reasoning — `neural_bridge` / `abstract_reasoning_engine` (substrate, verified 0-LLM for proofs)
- `reasoning/neural_bridge.py` — residual `llm_service` handle; any model use routes
  through the teacher.
- `reasoning/abstract_reasoning_engine.py` — `get_llm_service`.

### NOT a rewrite target — retires WITH the executor
- `reasoning/context_compression.py` + `reasoning/context_manager.py` +
  `reasoning/context_config.py` — LLM-window artifacts. "Compress conversation
  history to reduce token usage"; only functional caller is the executor's
  conversation manager. **The substrate has no context window** — `n_ctx` lives only
  on the model services and the executor loop; the substrate reasoner RETRIEVES
  (`inject_memories`, top-k by relevance), it has no buffer to compress. Nothing to
  move to a substrate authority; these retire when the LLM executor is replaced.
  (Verified 2026-08-28.)

### Learning
- `learning/causal_feedback_analyzer.py` — `llm.generate` → substrate causal reasoning.
- `learning/enhanced_asi_self_improvement.py` — `get_llm_service` (code-gen) →
  substrate program construction (its comment already says "EXISTS TO REPLACE").
- `learning/frontier_foresight_methods_impl.py` — `llm.generate`.
- `learning/unified_learning_system.py` — `get_llm_service` (contributor).
- `learning/capability_benchmark_suite.py` — `llm_service.generate`.

### Domain / Semantics — ✅ DONE (2026-08-28, verified end-to-end)
- `domain/concept_ingestion.py` — ~~`generate` via `LLMConceptExtractor`~~ **removed.**
- `domain/semantic_extraction.py` — ~~`extract_structured` via `SemanticExtractor`~~ **removed** (typed contract `ExtractionResult`/`record_attempt` kept — model-neutral).
- Live substrate path (verified 0-LLM): `conversation.teach/understand` → `cognitive_ingress` → `ConceptIngestionService` (deterministic `ConceptExtractor`, name `structured`) → store. Store already dominated by it: 3,316 `structured` relations vs 195 `llm_structured`. Readable prose stored via deterministic extractor; unreadable prose honestly refused ("could not read"), never faked. `domain/` is now LLM-free. Archived: `archive/llm_concept_extraction_pre_retirement_2026-08-28/`. Tests green (8). Follow-up: `ExtractionResult`/`record_attempt`/`extraction_attempts` now have no producer — candidate for a later clean-up.

### Language OUT / serving → `conversation.understand→say` + `Self.render`
- `api/chat_server.py` — `stream_chat`.
- `api/companion_server.py` — `stream_chat`.
- `api/external_api_server.py` — `LLMRequest`.

### Health → NOT rewrite targets (false positives — they MONITOR the model, don't use it)
- `health/health_monitor.py:2668` — `_check_llm_health`: a health PROBE of the teacher
  model (model loaded, throughput, failure rate). Monitors the resource; stays as long
  as the teacher exists. NOT cognition.
- `health/recovery_manager.py:295` — service-registry entry `('...', 'get_llm_service',
  'initialize')`: lifecycle re-init on recovery. NOT cognition.
- (The actual health-DIAGNOSIS cognition — the LLM analyzing health events — was already
  replaced in the coordinator by the deterministic `_diagnose_health`, 2026-08-27.)

### Security → substrate
- `security/digital_footprint.py` — lightweight_llm.
- `security/security_training_pipeline.py` — lightweight_llm.

### Artifact tools → substrate program / language generation — largest surface
- `tools/code_generation_tools.py` — 35 sites.
- `tools/ai_ml_tools.py` — 21 sites.
- `tools/documentation_tools.py` — 14 sites.
- `tools/academic_tools.py` — 6 sites.

### Lifecycle / the pipe
- `main.py` — initializes both model services.
- `core/services/unified_llm.py`, `core/services/lightweight_llm.py` — the inference
  pipes; shrink to the teacher path, then delete.
