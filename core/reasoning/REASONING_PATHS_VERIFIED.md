# The Eleven Reasoning Paths — Verified Against the Real System

This document describes each of TorinAI's eleven kinds of thinking, states what a
correct test of each one must show, and records the result of testing all eleven
**through the reasoning authority, against the real running system** — real
PostgreSQL, real llama-server, executed inside the sandbox container.

    positives 11/11 · negatives 11/11 · 22/22 total

Every path was verified twice: once that it **derives the right answer** on
material it fits (no false negative), and once that it **abstains** on material
it does not fit (no false positive).

The test is `tests/reasoning/test_eleven_paths_real.py`. It is reproduced at the
end.

---

## Methodology

### 1. Everything goes through the authority

The authority is **`NeuralSymbolicBridge.reason()`**. The abstract reasoning
engine and its eleven strategies run *underneath* it. A test that reached into
`engine.reason()` or a strategy object directly would be going *around* the
authority — it would fake the inputs and skip substrate-first routing,
verification stamping, and the derived-vs-proposed filter. So every case submits
a real question to `reason(ReasoningRequest(query=…, context=[…], kinds=[…]))`
and reads the authority's own verdict.

### 2. The order the authority reasons in

```
reason()  →  substrate-first (proof)  →  the eleven kinds  →  a model (last resort)
```

What the substrate can **prove**, then what it can **derive**, and only then what
a model can **propose**. The eleven kinds are all model-free.

### 3. The verdict fields that make false positives impossible

`reason()` returns metadata the test asserts on:

| field | meaning |
|---|---|
| `metadata['verified']` | the substrate stands behind this — not a model guess |
| `metadata['kind']` | which of the eleven settled it — **set only on the derived path** |
| `metadata['reason']` | `derived_by_kind` (a kind derived it) / `substrate_verified` (proved) |
| `result.answer` | the derived statement |

`metadata['kind']` is set **only** when a strategy's conclusion has
`origin == "derived"`. A model proposal (`origin == "proposed"`) is filtered out
by the authority before `kind` is ever assigned. **A model answer therefore can
never masquerade as a kind of thinking** — which is the property that makes the
positive assertions immune to a false pass.

### 4. The whole test is model-free — because reasoning is always substrate-first

Every case, positive and negative, runs under **`STRICT_MODEL_FREE`**. This is
not a special mode the test switches on to prove a point; it is what always
holds. Reasoning is **always substrate-first**: the substrate tries deterministic
formalization, then all eleven kinds, and the model is only ever a last resort —
never a factor in *whether* the substrate reasons. So forbidding the model
changes nothing about the eleven paths, and a path that only settled because a
model answered would fail here instead of passing quietly. All 22 pass model-free.

(This was not always true. `_substrate_first` used to branch on whether a model
was *available*: with one it fell through to the kinds, without one it declared
the input `unsupported_input` and the kinds never ran — the same question
answered or refused depending only on whether a model was around. That was the
model-in-the-muddle the architecture forbids, and it is fixed: substrate-first
always falls through to the kinds regardless of any model.)

### 5. Against the real system, in the sandbox

The test runs in the `torinai-sandbox` container with the real host services:

```
POSTGRES_HOST=host.docker.internal   → the real torinai_db on :5433
LLM_SERVER_URL=…host.docker.internal:8099 → the real llama-server
```

Nothing is stubbed. Store, retrieval, embedding, proof, and persistence all use
the real backends.

---

## The eleven paths

Each section: **what it is**, **what we test for**, the **positive** case
(material → derived answer) and the **negative** case (material it must abstain
on), and the **result**.

### 1. Deductive — what must follow from the premises

- **What it is.** Rule application over formal atoms. If a rule's body matches a
  premise, its head follows. No rule applies → nothing follows, and saying so is
  the correct output. The model is never consulted; deduction *is* what the
  substrate derives.
- **What we test for.** Given a ground fact and a universally-quantified rule,
  the correct instance is derived — and only that.
- **Positive.** `human(socrates)`, `human(?x) -> mortal(?x)` → **`mortal(socrates)`** ✅ `derived_by_kind`
- **Negative.** `human(socrates)` with no rule → abstains ✅ (deduction needs a rule)

### 2. Inductive — what the cases generalise to

- **What it is.** Generalisation from repeated instances, with confidence set by
  **Laplace's rule of succession** `(s+1)/(s+f+2)` — not an invented constant.
- **What we test for.** Several instances sharing a pattern generalise to it;
  fewer than two instances is not a pattern.
- **Positive.** `raven one is black`, `raven two is black`, `raven three is black`
  → **generalises "raven … black"** ✅ `derived_by_kind`
- **Negative.** a single instance → abstains ✅ (needs ≥ 2 premises)

### 3. Abductive — what would best explain the observation

- **What it is.** Backward rule search: given an observation and rules, find the
  antecedent that would produce it. Capped below certainty — an explanation is a
  hypothesis, not a proof.
- **What we test for.** The observation is explained by the cause the rule names.
- **Positive.** `wet(lawn)`, `rained(sky) -> wet(lawn)` → **`rained(sky)`** ✅ `derived_by_kind`
- **Negative.** `wet(lawn)` with no rule → abstains ✅ (nothing to explain from)

### 4. Analogical — mapping structure between two things

- **What it is.** Structural alignment between two premises: same relational
  shape, different content.
- **What we test for.** Two structurally-parallel statements yield an analogy.
- **Positive.** `the heart pumps blood through the vessels`,
  `a pump pushes water through the pipes` → **maps heart↔pump** ✅ `derived_by_kind`
- **Negative.** one statement → abstains ✅ (needs ≥ 2 premises to align)

### 5. Causal — tracing cause to effect

- **What it is.** Reads a stated causal relation (`X causes Y`, `Y because of X`)
  and can chain links. Cause/effect are modelled as timed propositions — this is
  the path that shares the temporal engine.
- **What we test for.** A stated causal claim becomes a causal conclusion.
- **Positive.** `smoking causes lung damage` → **`smoking causes lung damage`** ✅ `derived_by_kind`
- **Negative.** `the sky is blue` → abstains ✅ (no causal form present)

### 6. Counterfactual — what would have happened otherwise

- **What it is.** Compares an alternative against the conditions that actually
  hold. An alternative with no real state to compare against is a wish, not a
  counterfactual — so both are required. Capped by a structural ceiling.
- **What we test for.** An alternative plus the actual state yields a projected
  outcome.
- **Positive.** `the deployment failed`,
  `the deployment would have succeeded without the config error`
  → **projects the without-config-error outcome** ✅ `derived_by_kind`
- **Negative.** `the deployment failed` alone → abstains ✅ (no alternative to consider)

### 7. Spatial — reasoning over spatial relations

- **What it is.** Builds a relation graph (inside / contains / above / below /
  near) with converses folded in, and composes it transitively.
- **What we test for.** Containment composes.
- **Positive.** `the book is inside the box`, `the box is inside the room`
  → **`book inside room`** ✅ `derived_by_kind`
- **Negative.** `the cat is happy` → abstains ✅ (no spatial relation stated)

### 8. Fuzzy — claims that hold by degree

- **What it is.** A hedged claim holds to a **degree**, not a probability.
  Zadeh's concentration/dilation — `very` sharpens (`d²`), `somewhat` softens
  (`d^0.5`). A sharp claim is deduction's job, not this one.
- **What we test for.** A hedged claim is read at its degree.
- **Positive.** `the disk is mostly full` → **`holds to degree 0.80: the disk is mostly full`** ✅ `derived_by_kind`
- **Negative.** `the disk is full` (sharp) → abstains ✅ (no hedge to grade)

### 9. Logical — proving a proposition

- **What it is.** Propositional / first-order proof, served by
  `LogicalReasoningStrategy` — the reasoning strategy, first and always, like
  every other kind. Substrate-first and the strategy call the *same* prover
  (`advanced_proof_engine`), so `reason()` **defers** a substrate proof to the
  kinds (exactly as it defers a refutation): the logical strategy proves it and
  is named as the one that did, with the substrate's own proof kept only as a
  fallback if no kind settles it.
- **What we test for.** A proposition provable from the premises is proved, *by
  the logical strategy*.
- **Positive.** `p`, `p -> q`, goal `q` → **`Proved: q`** ✅ `derived_by_kind` (fired=logical)
- **Negative.** `p`, goal `z` → abstains ✅ (`z` does not follow from `p`)

### 10. Probabilistic — holding a belief and moving it with evidence

- **What it is.** Creates a belief about a claim and updates it from evidence
  premises, reporting a probability.
- **What we test for.** A claim plus supporting evidence yields a moved belief.
- **Positive.** `the smoke alarm reliably indicates fire`, `the smoke alarm is sounding`,
  goal "is there a fire?" → **`P(is there a fire?) = 0.998`** ✅ `derived_by_kind`
- **Negative.** no evidence premises → abstains ✅ (nothing to move a belief)

### 11. Temporal — reasoning about time order

- **What it is.** Reads temporal operators (before / after / always / never /
  until / since) and evaluates a claim against a timeline. Its knowledge now
  persists to PostgreSQL (see Findings).
- **What we test for.** A temporal ordering claim is evaluated on the timeline.
- **Positive.** `the alarm rings before the coffee brews`,
  `the coffee brews before breakfast`
  → **`before holds: the alarm rings before the coffee brews`** ✅ `derived_by_kind`
- **Negative.** `the alarm is red` → abstains ✅ (no temporal operator)

---

## Findings surfaced by testing against the real system — all fixed

Testing through the real authority — rather than the strategies in isolation —
exposed things a component test would have hidden. All three are now corrected.

### A. Two reasoning engines wrote SQLite in a PostgreSQL system (FIXED — both)

`temporal_reasoning.py` and `formal_argumentation.py` persisted to a local
SQLite file while the rest of the system uses PostgreSQL — a migration that was
started (a dead `unified_db` reference and a "use unified instead" comment) and
never finished. Worse, the SQLite write was **synchronous inside the derivation
loop**: when the filesystem was read-only the write failed and *killed the
reasoning*, returning zero conclusions. The temporal and causal paths both went
dark for this reason.

Both are now migrated to the unified PostgreSQL DB:
- `temporal_reasoning.py` → `unified.reasoning_temporal_propositions` /
  `unified.reasoning_temporal_causal_links`;
- `formal_argumentation.py` → `unified.reasoning_arg_claims` /
  `unified.reasoning_arguments` / `unified.reasoning_arg_fallacies`;
- writes are **off the critical path and non-fatal** — a persistence failure can
  no longer break a derivation, which is in-memory;
- a **`load()` reader is wired** in each so prior knowledge is brought into
  memory and consulted across sessions — the reader the SQLite versions never
  had. Both verified writing (rows land in Postgres after a run).

### B. Logical is now served by the logical strategy (FIXED)

Propositional proofs used to be settled by the substrate-first prover before the
eleven-kind tier, so `LogicalReasoningStrategy` was a shadowed fallback. But
substrate-first and the strategy call the *same* prover, so `reason()` now
**defers** a substrate proof to the kinds — exactly as it defers a refutation.
The logical strategy proves it, is named as the one that did (`fired=logical`,
`derived_by_kind`), and the substrate's own proof is kept only as the fallback.
Logical is served by its reasoning strategy, first and always, like the other ten.

### C. Substrate-first no longer depends on a model (FIXED)

`_substrate_first` used to branch on `_model_available()`: with a model it fell
through to the kinds, without one it declared `unsupported_input` and the kinds
never ran. So the eleven model-free kinds were reachable only when a model
happened to exist — the model-in-the-muddle the architecture forbids. It now
**always** falls through to the kinds regardless of any model. The model is a
last resort, added as a router candidate only when available, with the substrate
as the floor; `STRICT_MODEL_FREE` gates only that last resort and no longer
changes whether the substrate reasons. The entire test now passes model-free.

---

## Reproducing the test

```
docker run --rm --add-host=host.docker.internal:host-gateway \
  -e DOMINION_ENV_LOADED=true \
  -e POSTGRES_HOST=host.docker.internal -e POSTGRES_PORT=5433 \
  -e POSTGRES_DATABASE=torinai_db -e POSTGRES_USER=stefan -e POSTGRES_PASSWORD= \
  -e LLM_SERVER_URL=http://host.docker.internal:8099 \
  -e HF_HOME=/root/.cache/huggingface -e TRANSFORMERS_OFFLINE=1 -e HF_HUB_OFFLINE=1 \
  -e PYTHONPATH=/repo -w /repo \
  -v "$PWD":/repo:ro -v "$HOME/.cache/huggingface":/root/.cache/huggingface:ro \
  torinai-sandbox:latest sh -c "pip install -q pgvector 2>/dev/null; \
    python tests/reasoning/test_eleven_paths_real.py"
```

Expected: `positives 11/11 · negatives 11/11 · 22/22 total`.
