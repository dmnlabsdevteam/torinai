# Map of prompts & "identity" — `unified_llm` and `autonomous_coordinator`

Purpose: before renaming/rewriting `unified_llm` and stripping the "brain" out of
the coordinator, inventory **every place Torin's identity and cognition are
pinned to the language model** — as prompt strings, as `self.llm`, and as
behaviour the coordinator routes through the model. This is the surface the new
substrate-native center has to absorb or cut.

## The headline

Torin's "self" lives in the LLM in **two** forms, and a third, substrate-native
path runs in parallel:

1. **Identity-as-prompt** — the persona/identity is a *string* in
   `unified_llm.system_prompts`, consumed only by the model when it generates.
2. **Cognition-as-LLM** — the coordinator's core "what should I do now?" decision
   is `self.llm.generate(agent_type="singleton")` over a natural-language prompt,
   and `self.llm` is *also* expected to own memory / research / learning /
   reflection (a "brain" object, not just an inference service).
3. **Substrate-native (model-free)** — the idle tiers (exploration, induction,
   domain discovery, deficit/curiosity) decide and learn without the model.

The contradiction is explicit in the code: the coordinator docstring says
*"THE COGNITIVE SUBSTRATE IS THE BRAIN. A language model is a TEACHER"*
(`coordinator:128`), while the actual idle decision routes through the model
wearing the "Singleton" identity.

---

## A. `core/services/unified_llm.py` — identity as prompt strings

`UnifiedLLMService` is an **inference service** (queue, GPU, model load, logging).
Its own docstring already disowns the crown: *"It is also not the substrate.
Torin is the cognitive substrate this service is [for]"* (`:21`).

### A1. `self.system_prompts` — the persona table (`:554`–~`:780`)
~30 agent-type entries. Every one begins "You are Torin…". Three tiers:

| Tier | Entries | Content |
|---|---|---|
| **Generic** (identical line) | `chat`, `code`, `research`, `reasoning`, `safety`, `memory`, `vision`, `system_maintenance`, `autonomous`, `health_analyst`, `causal_reasoning`, `code_generator`, `documentation_specialist`, `refactoring_specialist`, `performance_optimizer`, `debugging_specialist`, `logical_reasoning`, `conversation_summarizer`, `constitutional_safety`, `documentation_expert`, `deductive_reasoning`, `memory_consolidator`, `pattern_recognition` | "You are Torin, an advanced AGI assistant created by Dominion Labs Inc. You are the central intelligence powering TorinAI." (~20+ copies) |
| **Rich identity** | `singleton` (`:616`–`:655`), `task_executor` (`:659`–`:746`) | The full self-model: *"You are not a model. You are a cognitive substrate: your reasoning is symbolic and evidence-based… it is the thing that decides. A Qwen… model is available to you as a teacher and helper — it proposes, formalises and reads language for you."* Plus behaviour rules (tool-call etiquette, the 5 laws, idle behaviour). |
| **Domain** | `agentso` (`:580`) | Cybersecurity SOC persona. |

**This is where Torin's identity actually lives.** It is inert to the substrate —
only the model reads it. The `singleton`/`task_executor` blocks are the canonical
self-description to lift OUT into a real substrate self-model.

### A2. Prompt resolution / injection (plumbing — keep, it's fine)
- `process_request` defaults empty prompt → `system_prompts[agent_type]` else `chat` (`:1816`–`:1819`).
- `generate` resolves `system_prompt or system_prompts.get(agent_type, "You are a helpful AI assistant.")` (`:1887`–`:1888`).
- `_remote_chat` prepends a system message (`:1015`–`:1016`).
- Bare fallback string "You are a helpful AI assistant." (`:437`, `:1888`).

---

## B. `core/agents/autonomous/autonomous_coordinator.py` — identity as `self.llm` + LLM-driven cognition

### B1. The `self.llm` slot — identity/authority conflation
- `:128` docstring — **stated principle**: "THE COGNITIVE SUBSTRATE IS THE BRAIN. A language model is a TEACHER."
- `:161` `self.llm = teacher_model  # the consultable model, absent by default`.
- `:485` `self.llm = self.config.get("llm_brain")  # Torin will pass itself` ← **identity pinned to the llm slot**: the model is called `llm_brain`, and "Torin passes itself" *as* the llm.
- `:639`–`:641` fallback `self.llm = get_llm_service()` → becomes the plain `UnifiedLLMService`.
- `:685` `self.intrinsic_motivation.set_llm(self.llm)`; `:2659` availability = `self.llm is not None`.

### B2. "The Singleton" as brain / source of truth (identity language)
Scattered assertions that the Singleton IS the decider/brain:
- `:764`, `:3233`, `:3334`–`:3344`, `:5709`, and most bluntly
  `:7774`–`:7780`: *"All systems are built around the Singleton — nothing operates without it… The Singleton IS the source of truth, the brain that makes the architecture alive."*

### B3. LLM-driven cognition — the core decision IS the model
The autonomous "think" cycle builds a natural-language prompt and asks the model,
as `singleton`, what to do:
- **`_autonomous_cognition_cycle`** (`:3334`+): gated `if not self.llm: return` (`:3347`).
  STEP 2 THINK builds `thinking_prompt` (`:3431`–`:3461`, "DECIDE WHAT TO DO… DECISION: [ACT/REFLECT/WAIT]") → `self.llm.generate(agent_type="singleton")` (`:3464`) → `_parse_thinking_decision` keyword-parses free text (`:3479`, `:3582`). **This is the substrate's idle agency, and it is the model.**
- `maintenance_prompt` (`:7791`) → `generate(agent_type="singleton")` (`:7836`).
- `goal_generation_prompt` (`:7883`, "YOUR HIGH-LEVEL DIRECTIVES…") → `generate(singleton)` (`:7902`).
- Routing decision via lightweight model (`:8339`–`:8355`).
- Context f-strings fed into the above: `intrinsic_signals` (`:8241`), `domain_insights` (`:8279`), `context` (`:8300`).

### B4. "Brain" behaviour expected ON the `self.llm` object (not just generation)
The coordinator treats `self.llm` as a full cognitive object, calling brain
methods on it — all `hasattr`-guarded, so **inert when `self.llm` is the plain
`UnifiedLLMService`** (which has none of these), i.e. these only fire if a richer
"brain" object is injected as `llm_brain`:
- Memory: `self.llm.memory.store_memory / search_memories` (`:3616`, `:3636`, `:8007`, `:8024`, `:8200`, `:8213`).
- Autonomy methods: `self.llm._autonomous_research` (`:8378`), `_autonomous_learning` (`:8384`), `_autonomous_memory_consolidation` (`:5650`, `:8411`), `_autonomous_reflection` (`:8417`).
- Feedback: `self.llm._check_feedback_database` (`:8045`).

**Finding:** "memory / research / learning / reflection" are modelled as
properties of the *llm object*, not the substrate. Either a god-object is passed
as `llm_brain`, or these paths are dead. Both are the same disease: the brain is
conceptually the model.

---

## C. The substrate-native path already exists (the counter-model)
For contrast, these decide/learn with **no model**, and are where the new center
should route:
- Idle tiers: `_idle_domain_discovery_work`, `_idle_operator_exploration_work`,
  `_idle_operator_induction_work` (exploration records; induction drains off-band).
- Reasoning delegated to the substrate: `reason_about` → `NeuralSymbolicBridge.reason()`
  (`:2661`+, docstring "DELEGATES rather than reasoning").
- Learning delegated: `get_learning_authority().drain_pending_induction()` (`:5242`).
- Curiosity/allocation: `UDM.select_exploration_target` + appraisal → behaviour arbiter.

---

## D. What the rewrite has to do (implications, not yet a plan)
1. **Lift the self out of the prompt.** The `singleton`/`task_executor` identity
   blocks (`unified_llm:616`, `:659`) become a real substrate **self-model** the
   substrate *operates from*, not a string the model recites. (Ties to the
   existing "no substrate self-model / DeploymentIdentity" gap.)
2. **Move the idle decision off the model.** `_autonomous_cognition_cycle`'s
   THINK step should be the substrate's own decision (appraisal → arbiter →
   tiers already exist and run in parallel); the LLM `singleton` generate becomes
   a fallback for *input coverage*, not the decider.
3. **Stop treating `self.llm` as the brain.** Split it: an **inference resource**
   (rename `unified_llm` to what it is) vs. the substrate **self/center** that
   owns memory/research/learning/reflection through the real subsystems.
4. **Demote `llm_brain` / "Torin passes itself."** Torin is the substrate; the
   model is a part it consults.

_Generated 2026-08-27 from a direct read of both files. Line numbers are current
as of this commit; treat as anchors, re-grep before editing._
