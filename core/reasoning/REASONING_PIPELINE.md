# The TorinAI Reasoning Pipeline

**Dominion Labs — Cognitive Substrate Series · Engineering & Architecture Reference**

*A method-by-method account of how the reasoning substrate turns a question into a
derived, checkable conclusion — or an honest refusal. Written for two audiences at
once: engineers who will change this code, and researchers evaluating what the
architecture does and does not claim. Every algorithm below is described as it is
implemented, with file and line references, and every limitation is stated at the
same resolution as the capability.*

Companion documents in this folder:
- `REASONING.md` — the conceptual paper (Paper I: Reasoning).
- `REASONING_PATHS_VERIFIED.md` — the eleven-paths test verified against the live system.

This document is the implementation-level complement to both: it walks the actual
call graph and the actual formulas.

---

## 0. Orientation

### 0.1 One authority

All reasoning enters through a single object: the **`NeuralSymbolicBridge`**
(`neural_bridge.py:788`), reached by the process-wide accessor `get_neural_bridge()`
(`neural_bridge.py:3373`). Nothing else is a reasoning entry point. The bridge owns
the belief graph, the abstraction pipeline, and the abstract-reasoning engine
(constructed in `initialize()`, `neural_bridge.py:1231`), and it is the only surface
that other subsystems call to reason, to reflect, to assess uncertainty, or to
generate a hypothesis. This is the "self is the sheriff; authorities are deputies"
design: the bridge is the reasoning deputy, and it exposes one door.

### 0.2 Model-free by construction

The substrate derives conclusions from evidence it holds; it does not generate text
that resembles conclusions. A language model is a **teacher**, never an authority:
it may *propose* a candidate or *translate* an input the substrate cannot yet read,
but it may never *attest*. Every model proposal is re-parsed, checked against the
input, ranked below every derived conclusion, and marked as a proposal in every
record that survives it. The eleven kinds of inference and every solver below run
with zero model calls. This is not a runtime flag — there is no model in the
dispatch or acting path to gate.

### 0.3 The credit-assignment contract

Every `ReasoningResult` carries metadata that lets a downstream consumer — or a
later training pass — tell *how* a conclusion was reached without inspecting the
answer text. Five fields are load-bearing (`neural_bridge.py:2991`):

| field | meaning |
|---|---|
| `verified` | the substrate stands behind this (proved or derived), not a guess |
| `formalized` | a solver checked a formalized statement (proof), vs. a kind composed it |
| `reason` | a reason code (below) distinguishing proof / derivation / refusal / coverage |
| `model_required` | always `False` — the substrate never *requires* a model (see 0.4) |
| `model_available` | whether a teacher happened to be reachable (a fact about coverage) |

The **reason codes** (`neural_bridge.py:155`) exist so that three things that used
to look identically like "low confidence" stay separable:

- `substrate_verified` — a solver proved the goal.
- `substrate_refuted` — a solver decided against it (an authoritative negative).
- `derived_by_kind` — a kind of inference composed it from premises (no solver).
- `substrate_undecided` — a solver ran and gave up (timeout).
- `unsupported_input` — the substrate could not represent the input at all.
- `capability_unavailable` — the owner of this question is missing (a wiring fault, reported not routed-around).

### 0.4 "The substrate is not a model, and it never requires one"

The metadata key `model_required` is retained only as a deprecated alias and is
**always `False`** (`neural_bridge.py:182`). The claim that matters is
`substrate_formalized` — a statement about the substrate alone. Whether a teacher is
reachable (`teacher_available`) is a separate, optional fact about coverage, never a
statement about whether reasoning was possible.

---

## Part 1 — The Authority and the Router (`neural_bridge.py`)

### 1.1 The request and the result

**`ReasoningRequest`** (`neural_bridge.py:78`): `query: str`, `context: List[str]`
(the premises), `mode: ReasoningMode` (default `ABSTRACT`), `kinds:
List[ReasoningType]` (which of the eleven to try; empty ⇒ read them from the query),
plus optional vision inputs, a caller token budget, `cached_memories`, and
`task_metadata`.

**`ReasoningResult`** (`neural_bridge.py:120`): `answer: str`, `confidence: float`,
`reasoning_steps: List[str]`, `mode_used`, and the `metadata` dict carrying the
credit-assignment contract.

**`ReasoningMode`** (`neural_bridge.py:49`) is *not* a kind of thinking — it names
which machinery a caller may explicitly select: `SYMBOLIC` (solver over a formalized
statement), `NEURAL` (model inference, last resort), `HYBRID` (propose/constrain/
revise), `NEURO_SYMBOLIC` (plan then execute), `ABSTRACT` (the default: the whole
substrate, all eleven kinds), `CROSS_DOMAIN`. Under substrate-first these are
peers; a mode is consulted only when the default pipeline could not settle the
question. The *kinds* of thinking are the eleven in **`ReasoningType`**
(`reasoning_interfaces.py:12`).

### 1.2 `reason()` — the timing-and-annotation wrapper (`neural_bridge.py:1360`)

`reason()` is a thin wrapper over `_reason_impl`. It does four things around the
core:

1. **Times the call** per kind exercised (`record_reasoning`), which is what makes
   reasoning *difficulty* a measured quantity rather than a declared table (see 1.9).
2. **Fallacy annotation**: runs `_check_argument_fallacies` on the settled answer
   (the live home of the formal-argumentation engine). This is an *honest
   annotation* — it flags a detected fallacy in `metadata["fallacy_warning"]` and
   never changes the answer or its confidence.
3. **Epistemic-uncertainty annotation**: calls `assess_uncertainty` and writes
   `metadata["epistemic_uncertainty"]` — how unsettled the substrate's *own*
   knowledge is about this query (belief-graph entropy). A reading, not a change.
4. Returns the result unchanged otherwise.

### 1.3 `_reason_impl()` — the order of resort (`neural_bridge.py:1409`)

This is the spine. After a one-time memory injection (memories reach the eleven
kinds as *one clean claim per premise*, never a stamped prompt blob — a subtle but
measured correctness point, `neural_bridge.py:1444`), control reaches the router:

```
if request.mode != ABSTRACT:  run the named machinery (_run_mode), else honest inability
# DEFAULT (ABSTRACT):
substrate  = await _substrate_solvers(request)      # what can be PROVED
   ↳ a lossy propositional refutation/verification is DEFERRED to the kinds
by_kind    = await _reason_by_kind(request)         # what can be DERIVED
deferred_substrate                                  # the deferred proof, if kinds found nothing
cross      = await _cross_domain_reasoning(request) # grounding BETWEEN named domains
_unsettled(...)                                     # honest inability
```

The order — **prove, then derive, then propose** — *is* the architecture, not an
optimization. Two subtleties:

- **Deferral of lossy readings** (`neural_bridge.py:1560`). A propositional reading
  is lossy: from *the chip is inside the socket* and *the socket is inside the
  board*, opaque propositional symbols correctly report that *the chip is inside the
  board* does not follow — correct about the propositions, wrong about the world,
  because containment composes and opaque symbols do not. So when a substrate result
  is a *refutation* or *verification* from a propositional reading **and** the query
  carries markers of a kind that can express what the reading discarded (or the
  context carries a *predicate* rule like `human(?x) -> mortal(?x)` that a
  propositional reading cannot use), the substrate result is **deferred** — held
  back, offered to the kinds, and returned only if no kind settles it. A sound
  propositional refutation of a genuinely propositional question still stands.

- **Every exit goes through `_finish()`** (`neural_bridge.py:1326`): the single exit
  updates statistics and (for standalone calls with a real answer) captures the
  conclusion to memory. Making capture depend on *what a result is* rather than
  *which branch produced it* is itself a correctness fix.

### 1.4 `_substrate_solvers()` — what can be proved (`neural_bridge.py:2018`)

Runs only deterministic formalizers, so an input the substrate can represent never
enters a model call graph. In order:

1. **Arithmetic first.** `read_equation(query)` (`arithmetic_reading.py`) reads a
   linear equation; if present, `_solve_equation` (`neural_bridge.py:1826`) hands it
   to the **constraint solver** (Z3). "Torin can do algebra" is therefore a
   substrate claim — the solver *produces* the answer at confidence 1.0, and there
   is deliberately **no fallback**: if the solver is absent this reports
   `capability_unavailable`, never a model guess.
2. **Sequences.** `read_sequence(query)` → `_extend_sequence` (`neural_bridge.py:1875`)
   asks the **learning authority** to *induce* the rule
   (`induce_sequence_rule`). A sequence with no constant difference/ratio has no
   rule in this language; inventing one would be the most tempting fabrication here,
   so `MULTIPLE_HYPOTHESES` / `NO_RULE` returns "not settled", not a guess.
3. **Relational lookup over the learned concept graph.**
   `_answer_over_concept_graph` (`neural_bridge.py:1958`) reads the query into a
   typed (subject, relation, object) triple and answers it via the typed relation
   algebra (Part 4). `UNKNOWN` falls through honestly.
4. **Deterministic formalization → symbolic reasoning.** The formalizer chain
   (1.5) turns the query into a statement + premises; on success `_symbolic_reasoning`
   (`neural_bridge.py:2103`) hands it to Z3 and both the verdict and its confidence
   come from the solver.

If deterministic formalization fails, `_substrate_solvers` returns `None` — **which
is not the end and never depends on a model**. The eleven kinds are substrate
reasoning too and are tried next. (Historically this branched on
`_model_available()`: with a model it fell through to the kinds, without one it
declared `unsupported_input` and the kinds never ran — the "model-in-the-muddle"
the architecture forbids. It now always falls through.)

### 1.5 The formalizer chain — the reading→formalization boundary

Reading belongs to `core.semantics`; the *formalizer* — turning a reading into the
statement and premises a solver can take — is the reasoning side of the boundary.
`_get_deterministic_formalizer()` (`neural_bridge.py:2089`) is a `FormalizerChain`
of three, each needing no model:

- **`PassthroughFormalizer`** (`neural_bridge.py:323`): accepts input already in the
  formal grammar (via `LogicalFormulaParser.is_formal`). Context items that do not
  parse are *dropped*, which is sound — withholding a premise can only make a goal
  harder to prove, never prove something false.
- **`DeterministicExtractor`** (`neural_bridge.py:371`): translates a bounded slice
  of English into the propositional grammar. Because the substrate is
  propositional, universals are **grounded**: "All humans are mortal" becomes one
  implication per subject actually mentioned (`s_human -> s_mortal`). A generic goal
  ("Is a robin an animal?") introduces a **Skolem individual** — an arbitrary member
  asserted to be of the kind — so proving something of a kind is proving it of an
  arbitrary member (`neural_bridge.py:519`). Anything outside the supported patterns
  is *declined* so the chain falls through; a wrong guess here would put a false
  premise in front of the solver, the one failure mode the substrate cannot detect.
  It also reports **connectivity** (`neural_bridge.py:613`): whether the goal's atom
  occurs in the premises at all, so a translation gap is told apart from a genuine
  non-entailment.
- **`DerivedReadingFormalizer`** (`neural_bridge.py:635`): formalizes with readings
  the substrate *derived* (via `procedure_synthesis`, registered once per process),
  not ones a human wrote. This is what shrinks the model-backed share for a reason
  other than someone adding a regex. It declines where no registered reading applies.

### 1.6 `_reason_by_kind()` — what can be derived (`neural_bridge.py:2902`)

The dispatcher for the eleven kinds. Its logic:

1. **Which kinds to try**: whatever `request.kinds` names, else
   `kinds_of_thinking_for(query)` (marker-scored, `reasoning_interfaces.py:161`),
   else *every* classical kind. That last fallback is not a guess — each strategy's
   `is_applicable` then refuses unless the material it needs is present.
2. **Quality ordering**: kinds are sorted by *measured* success rate
   (`reasoning_quality`, 1.9) so historically-successful kinds are considered first.
   Cold kinds keep the neutral prior, so this only reorders once there is evidence;
   it never drops a kind.
3. Runs the **persistent** `AbstractReasoningEngine` (so per-kind stats accumulate)
   and keeps only conclusions with `origin == "derived"` (model proposals are
   filtered *before* a kind is ever credited).
4. **Relevance filter**: a kind can derive a *sound* conclusion about an *off-topic*
   premise (the temporal kind reading "during" in an unrelated sentence). Only
   conclusions connected to the query's own topic survive (`_query_topic` /
   `_relevant_to_topic`).
5. **Quality-weighted selection**: among on-topic conclusions, the one from the kind
   with the higher measured success rate wins, ties broken by confidence.
6. **Returns `None`, never an empty result**, when nothing applies — the caller must
   tell "no kind fits this" from "a kind ran and found nothing", because only the
   first should fall through further. Learned **schemas** bearing on the query
   (`_schemas_bearing_on`, `neural_bridge.py:2879`) are surfaced into the live result
   as induced priors.

### 1.7 `_cross_domain_reasoning()` (`neural_bridge.py:3045`)

Not one of the eleven kinds — it maps structure *between* named domains via the
`UniversalDomainMaster`, and runs only when a caller puts `source_domains` /
`target_domains` in `task_metadata`. Returns `None` (honest inability) when nothing
grounds across the domains, never a fabricated "no insights".

### 1.8 `_unsettled()` — declining as a result (`neural_bridge.py:1937`)

The substrate can return that it could not represent a question. This is a distinct
outcome with its own reason code (`unsupported_input`), told apart from a wrong
answer by *metadata*, not confidence (both can be low). No model fills the gap. A
system that can decline is what makes its confident answers mean something.

### 1.9 Self-measurement: difficulty and quality

The bridge measures its own behaviour and persists it (survives restart):

- **`record_reasoning(kinds, latency)`** (`neural_bridge.py:845`) accumulates
  per-kind `runs` + `total_latency` (the *cost* signal).
- **`reasoning_difficulty(kind)`** (`neural_bridge.py:894`): once a kind has enough
  runs, its difficulty is its average latency normalised against the *fastest*
  measured kind, clamped. "Harder" means "empirically slower here." Consumers (the
  agent allowance, the queue's timeout) read this, not a hardcoded table.
- **`record_reasoning_outcome(attempted, winner)`** (`neural_bridge.py:866`): every
  considered kind gets an *attempt*; the one that settled it gets a *success*.
- **`reasoning_quality(kind)`** (`neural_bridge.py:885`): `successes/attempts`, with a
  neutral prior (`0.5`) until `_QUALITY_MIN_ATTEMPTS = 5` attempts. This is the
  signal `_reason_by_kind` orders and selects by — the loop that lets the pipeline
  prefer the kinds that actually work here.
- **`agent_allowance(kind)`** (`neural_bridge.py:918`): how many agents-of-self a kind
  warrants in parallel, *derived from* measured difficulty (`round(2·difficulty)`,
  clamped [2,6]).
- **Persistence**: `unified.reasoning_telemetry` (kind, runs, total_latency,
  attempts, successes) via `flush_telemetry` / `load_telemetry`
  (`neural_bridge.py:929`), plus the coarse mode-mix statistics
  (`unified.reasoning_bridge_stats`). One scheduled flush,
  `_flush_reasoning_persistence`, whose *cadence* is owned by the queue authority
  and whose *logic* lives here.

### 1.10 Service methods routed through the authority

The bridge is also the single door to reasoning services other subsystems used to
reach by importing different engines directly:

- **`abstract_over_memories(memory_dicts)`** (`neural_bridge.py:1027`) → the
  abstraction pipeline (Part 7). The memory agent used to do this itself; it now
  *asks the authority*.
- **`reflect()`** (`neural_bridge.py:1040`) → belief-graph hygiene: temporal decay,
  contradiction/implication consistency, domain volatility, schema decay. Each step
  isolated so one failure does not abort the rest; the report says what actually ran.
- **`assess_uncertainty(request)`** (`neural_bridge.py:1079`) → the epistemic engine
  (Part 6).
- **`apply_reasoning_output(outputs)`** (`neural_bridge.py:1090`) → folds structured
  conclusions `{hypotheses, belief_updates}` into the belief graph; returns how many
  *real* epistemic mutations resulted.
- **`generate_hypothesis(claim, ...)`** (`neural_bridge.py:1140`) → the hypothesis
  system. `predictions`/`alternatives` are validated and coerced to lists of strings
  by `_coerce_predictions` (`neural_bridge.py:1106`) — a caller error *raises*
  (surfaced), a structured prediction is *flattened* (not dropped). This replaces a
  silent `None` false-negative.
- **`observe_tool_result(tool, params, output, success)`** (`neural_bridge.py:1169`)
  → the epistemic engine folds what a tool *observed* into the belief graph, which
  surfaces/resolves unstable regions that drive the exploration loop.

---

## Part 2 — The Eleven Kinds of Inference (`abstract_reasoning_engine.py`)

Reasoning is not one activity with one quality score. The engine implements eleven
structurally-different procedures, each with its own applicability condition, its own
basis for confidence, and its own failure mode. Each is a `ReasoningStrategy`
(`abstract_reasoning_engine.py:186`) with `reason()`, `is_applicable()`,
`get_strategy_name()`.

### 2.1 The engine dispatcher

`AbstractReasoningEngine.reason(context)` (`abstract_reasoning_engine.py:2143`) is
**set-based, not a switch**: it runs *every* applicable strategy and reconciles their
conclusions. The stages:

- **`_select_strategies`** (`:2315`): pick every strategy whose type is allowed and
  whose `is_applicable(context)` is true; if no types are named, select *all*
  applicable. (This is the fallback the router relies on.)
- **`_validate_conclusion`** (`:2334`): reject empty statements and contradictions; a
  `proposed` conclusion bypasses the confidence gates but travels *marked*; a
  `derived` one is rejected below the confidence threshold or `logical_validity < 0.3`.
- **`_filter_conclusions`** (`:2392`): derived kept iff `confidence ≥ threshold AND
  logical_validity ≥ 0.3 AND coherence ≥ 0.3`; dedup by statement.
- **`_rank_conclusions`** (`:2421`): `composite = 0.4·confidence + 0.3·logical_validity
  + 0.2·evidence_strength + 0.1·coherence`, sorted by the tuple *(derived-outranks-
  proposed, a **certain** kind outranks a **degree/belief** kind, composite)* — so a
  provable fact beats a `P=…` estimate of the same thing.
- **`_calculate_result_quality`** (`:2463`): overall confidence averaged over *derived*
  conclusions only; a proposals-only result has overall confidence 0.0.
- **`explain_reasoning`** (`:2264`): renders the *recorded* derivation (premises used,
  steps, competitors), never generated prose; "none recorded" where a strategy
  logged nothing.

**Provenance of the conclusion** — the `origin` field on `ReasoningConclusion`
(`:113`) is `"derived"` (a deterministic strategy computed it, with a confidence) or
`"proposed"` (a model suggested it, no confidence, no quality credit). **Every one of
the eleven strategies emits `origin="derived"`**; the model-consultation paths were
deleted from the deductive and inductive strategies, so no strategy in this file can
emit a proposal. Quantum reasoning is registered as `None`/disabled (`:2135`).

### 2.2 The eleven, with exact confidence and abstention

Each strategy computes confidence from something specific to it, deliberately
conservative, and **abstains** (returns no conclusion) when its material is absent —
distinguishing *no kind applied* from *a kind ran and concluded nothing*.

| Kind | Algorithm | Confidence (as coded) | Abstains when |
|---|---|---|---|
| **Deductive** (`:205`) | forward rule application by **unification** (delegates to `unification.py`); `_apply_rule` binds a rule body against premise atoms and instantiates the head | `min(0.8, premise.conf · 0.9)` (`:387`) | no rules/premises; no binding; **head not ground** after substitution (refuses to invent an unbound constant) |
| **Inductive** (`:407`) | group premises by Jaccard word-overlap (`>0.3`), pattern = words in ≥70% of a group, split positives/negatives on the **contested term** | **Laplace succession**: `min((s+1)/(s+f+2) · avg_conf, 0.9)` (`:653`) | fewer than 2 premises; fewer than 2 positives survive the split |
| **Abductive** (`:693`) | **backward search** over the rule base: an antecedent whose rule's consequent matches an observation is a candidate explanation, registered as a falsifiable hypothesis | `0.7 · coverage · simplicity`, or `0.0` if inconsistent; `simplicity = 1/#atoms` (Occam) (`:823`) | no observations; no rules; no candidate |
| **Analogical** (`:896`) | extract crude structure (entities/relations/properties), **structural similarity** = mean per-bucket Jaccard | `min(0.7, similarity · 0.8)` (`:1011`) | fewer than 2 premises; similarity ≤ 0.5 |
| **Causal** (`:1035`) | surface-match causal phrasing; **delegates to the temporal engine** (`establish_causal_link` / `trace_causal_chain`); edges keyed by `(cause,effect)` so chains share nodes | direct link = premise conf; chain = **min over walked links** (weakest link) (`:1200`) | no premise states a causal relation |
| **Counterfactual** (`:1227`) | project the *actual* state and the *counterfactual* state (facts + alternative) via the temporal engine; evaluate **reachability** | `min(conf · (1 if reachable else 1−difficulty), 0.7)` (`:1359`) | no alternative, or no actual facts to compare against |
| **Spatial** (`:1393`) | build a relation graph (`inside`/`contains`/`above`/`below` transitive; `near` symmetric-not-transitive), **transitive closure by composition** | `min(first, second)` per composed step (`:1525`) | no stated spatial relation; only restatements |
| **Fuzzy** (`:1554`) | **Zadeh** operators: hedges set a degree, `very`→`d²` (concentration), joint = `min`; *degree ≠ confidence* | confidence taken from the premise; degree = `d^exp` carried in the statement text (`:1669`) | no *hedged* premise (a sharp claim is deduction's job) |
| **Logical** (`:1686`) | build a `Theorem(target, premises+facts+rules)` and **delegate to Z3** (`advanced_proof_engine`) | `proof.confidence` (nothing added) (`:1764`) | no target or no premises; **proof fails → no conclusion** (not a weak yes) |
| **Probabilistic** (`:1783`) | create a belief at prior 0.5, update from each premise (negators → against), **delegates the Bayesian update** to `bayesian_uncertainty` | `belief.posterior_probability` (the posterior *is* the confidence) (`:1885`) | no target/premises; **no evidential signal** (guards the `P=0.998`-from-nothing fabrication) |
| **Temporal** (`:1905`) | map words to operators, build a timeline, **delegate operator evaluation** to the temporal engine (ALWAYS fails the moment one timeline proposition is false) | premise conf (`:1987`) | no temporal operator word in any premise |

The separation is the point: a deductive conclusion is supported by a derivation, an
inductive one by a count of confirmations and disconfirmations, a causal one by the
weakest link. These are not comparable quantities, and a single averaged "confidence"
would mean nothing.

### 2.3 Why induction is subtle

The naive implementation is wrong in a way that is hard to see: a system that groups
similar cases and generalises from each group *absorbs contradicting cases into the
group they contradict* — they are, after all, similar — so a disconfirmation moves
confidence the wrong way, and an evenly-split group hides itself behind a contentless
generalisation (which scores highest precisely because there is nothing in it to
disagree with). The substrate handles this by identifying the **contested term** — a
property some members carry and others do not — and counting the minority side as
counterexamples (`:623`). The result is the ordering one expects and the naive
version inverts: evenly-split < three-to-one < unanimous. **Stated limit**: it counts
the disconfirmations it was *given*; it does not search for a disconfirming case that
was never supplied.

---

## Part 3 — The Formal Core (proof, constraint, unification, parser, values)

### 3.1 `LogicalFormulaParser` — text to AST to Z3 (`logical_integration.py`)

After a prune from ~1147 to ~455 lines (the dead `LogicalInferenceEngine` /
`LogicalReasoningValidator` / `LogicalIntegrationSystem` were removed as redundant
with `unification.py` and the Z3 prover; the full pre-prune copy is archived), what
remains is the shared front end from text to a Z3 boolean expression:

- **Types**: `LogicType` (PROPOSITIONAL/FIRST_ORDER/MODAL/TEMPORAL/FUZZY), `Operator`
  (∧∨¬→↔∀∃□◊), `LogicalFormula`, `FormulaSyntaxError`.
- **Tokenizer** (`_tokenize`, `:238`): a hand-written scanner emitting
  `(kind, canonical, position)`. Multi-char symbols are matched **longest-first** so
  `<->` beats `<` + `->`; word operators (AND/OR/NOT/IMPLIES/IFF) match only as whole
  identifiers so `android` does not become `∧roid`; a ground predicate `P(x, y)` with
  a simple argument list is folded into one atom; quantifiers are tokenized *so they
  can be rejected with a clear message* rather than silently parsed as atoms.
- **Parser** (`_parse_expression`, `:314`): **precedence climbing** with precedence
  `¬:4, ∧:3, ∨:2, →:1, ↔:1` and right-associativity for `→`/`↔`. AST is nested tuples:
  `("atom", n)`, `("not", c)`, `("and"|"or"|"implies"|"iff", l, r)`.
- **`to_z3`** (`:418`): lowers the tree to Z3; an atom not pre-declared raises
  `KeyError` — parsing is "not licence to invent a symbol."
- **`is_formal`** (`:230`): true iff `parse_ast` succeeds — the bridge's passthrough
  formalizer gate.

### 3.2 `AdvancedProofEngine` — SMT refutation and direct proof (`advanced_proof_engine.py`)

- **Method selection** (`_select_proof_method`, `:233`): if Z3 is available and the
  logic is propositional/first-order → **SMT**; otherwise → **DIRECT**. Only these two
  are ever selected.
- **`_smt_proof`** (`:248`): parse every premise and the goal to ASTs; declare one Z3
  boolean per atom; assert all premises **plus the negated goal**; check with a
  millisecond timeout off the event loop. **Refutation encoding**: premises + ¬goal
  are unsatisfiable exactly when the premises entail the goal.
  - `unsat` → **proved**, confidence `0.98`.
  - `sat` → **not proved** (a model falsifies the goal — an *authoritative* negative),
    confidence `0.0`.
  - `unknown`/timeout → **undecided**, confidence `0.0`, error "entailment undecided"
    (explicitly *not* a decided negative).
  - Z3 absent → `capability_unavailable`, `0.0`, and **no fallback** — a weaker method
    would make the solver decorative.
- **Three separable "not proved" semantics**: `sat` (refutation), `unknown`
  (undecided), and `capability_unavailable` / `NEGATIVE_NOT_AUTHORITATIVE` (could not
  derive) are kept distinct so "could not settle" never becomes evidence.
- **`_direct_proof`** (`:380`): forward chaining — seed facts from premises, apply
  **modus ponens** (`_apply_inference_rules`, `:468`: split an `X -> Y` fact and, if
  `X` is known, derive `Y`) up to `max_steps`, succeed when a derived statement equals
  the goal. Proved → `0.95`, else `0.0`.
- **`verify_proof`** (`:497`) re-derives independently: any rule the checker cannot
  re-derive is counted UNCHECKED and *blocks* verification; SMT proofs are re-verified
  by re-running the solver.
- **Removed stub (2026-09-01)**: `_resolution_proof` was a stub that always returned
  `proved=False` with a fabricated `0.6` — deleted; propositional proofs without Z3
  now route to the real `_direct_proof`.

**Honesty note for a scientific reader**: proof confidences are **fixed constants per
outcome path** (0.98 / 0.95 / 0.5 / 0.0), not calibrated measures. They read as
numbers; they are code paths.

### 3.3 `ConstraintSolver` — CSP and optimization (`constraint_solver.py`)

A thin, honest Z3 wrapper. `solve` (`:120`) builds typed vars (int/real/bool), applies
bounds and constraints, checks, and returns a `ConstraintSolution` with a real model
on `sat`. `optimize` uses Z3 `Optimize`. `solve_linear` is the arithmetic wrapper the
bridge calls. `get_statistics` (`:80`) exposes counters (`solves/sat/unsat/
unavailable`) so the health monitor can see the solver *working*, not merely present.
Z3 absent → an explicit `no_solver` state, never a silent fallback.

### 3.4 `unification.py` — one-way matching (the shared authority)

The single unification authority, shared by rule induction and the deductive strategy.
Precise characterization: it is a **one-directional (pattern/ground) Robinson-style
matcher**, not full two-sided unification. Variables are *marked* syntactically by a
`?` prefix, never inferred. `unify(pattern, ground, bindings)` (`:102`) gates on a
`(predicate, arity)` signature, walks args positionally, binds a variable to a ground
term with **conflict detection** (`setdefault(slot, value) != value → None`, so
`LIKES(?X, ?X)` will not match `LIKES(ann, bob)`), and fails on a constant mismatch.
The substitution is a flat `Dict[str,str]`; there is no occurs-check (unneeded —
variables appear only on the pattern side) and no nested-term recursion.
`match_body` (`:136`) satisfies a conjunctive body by **backtracking**, most-
constrained-literal-first. Working on any `AtomLike` protocol lets learning's `Fact`
and reasoning's `Atom` share one algorithm without a common base class.

### 3.5 `value_authority.py` — the meaning of a computation

A deliberately tiny authority sitting *below* both the learner and the planner so both
agree on what a computation returns. The catalogue is four binary functions (`:54`):
`add` (commutative), `subtract`, `multiply` (commutative), `divide`. **Arity and
commutativity are declared, not inferred** — because a searcher that does not know
`add` is commutative manufactures an unresolvable ambiguity (`add(?a,?b)` vs
`add(?b,?a)` is "one hypothesis written twice"). `evaluate(function, inputs)` (`:82`)
returns a canonical value string, or `None` for unknown function / wrong arity /
non-numeric argument / undefined computation (divide-by-zero) — "`None` is a refusal,
not a zero." The catalogue is kept to four on purpose: induction searches it, so every
extra function is another hypothesis that could explain a demonstration by accident.

---

## Part 4 — Typed Relations & the Concept Graph (`relation_algebra.py`, `concept_graph_reasoning.py`)

This is how the substrate answers a relational question over learned knowledge —
*precisely*, with provenance, and without confusing reachability for entailment.

### 4.1 Representation

`Edge(subject, relation, obj)` (frozen), `Derivation(edge, path, rules, hops)` (a
DERIVED edge with the exact observed path it traversed and the rule tag at each step),
and `Answer(verdict ∈ {true,false,unknown}, basis ∈ {observed,derived,none},
derivation?)`. The typed relation vocabulary itself (`SemanticRelation`, ~38 types,
and each relation's `RelationSpec`) lives in `core/semantics/relation_types.py`.

### 4.2 The composition law (`compose`, `relation_algebra.py:60`)

Composition is **licensed, isolation-by-default** — exactly four rules, everything
else returns `None`:

1. `INSTANCE_OF ∘ ISA ⊢ INSTANCE_OF` (Fido instance-of dog, dog isa animal ⇒ Fido
   instance-of animal).
2. `ISA ∘ r ⊢ r` when `r` is **inheritable** (a subkind inherits a superkind's
   generic property/relation).
3. `r ∘ r ⊢ r` when `r`'s transitivity is **ALWAYS**.
4. `r ∘ r ⊢ r` when transitivity is **ONTOLOGY_DEFINED** *and* `r` is in the
   context's licenses.

The load-bearing conservatism is in the specs: **only ISA chains unconditionally**;
`PART_OF`, `LOCATED_IN`, `CAUSES`, `SYNONYM_OF`, `PRECEDES` chain only when
context-licensed; everything else is NEVER-transitive; only seven relations
(`HAS_PART`, `HAS_PROPERTY`, `REQUIRES`, `USED_FOR`, `HAS_FUNCTION`, `EATS`,
`CAPABLE_OF`) are inheritable. This is the entire basis of "reachability is not
entailment" — that `a` is near `b` and `b` near `c` does *not* make `a` near `c`,
because adjacency does not compose.

### 4.3 Derivation and open-world answers

`derive_from` (`:133`) is a **breadth-first search over licensed compositions only**,
optionally seeding inverse edges so inverses can chain, bounded by `max_hops`, with a
`seen_state` guard. `answer(subject, relation, obj, edges, negatives)` (`:206`) is
**open-world**: `FALSE` is returned *only* on an explicit negative edge; an observed
edge is `TRUE/observed`; a licensed derivation is `TRUE/derived` (carrying the full
`Derivation`); **absence is `UNKNOWN`, never `FALSE`**.

### 4.4 `answer_over_graph` over the live Postgres graph (`concept_graph_reasoning.py:66`)

`load_subgraph` (`:34`) BFS-loads the typed subgraph from `unified.concept_relations`,
mapping stored relation strings back to types (**untyped/legacy edges are skipped** —
they license no inference) and **skipping denied edges** (negatives are not positive
facts). `answer_over_graph` normalizes the query terms the same way ingress did
(so "flippers" matches stored "flipper"), loads the subgraph, and delegates to
`answer`. In practice it returns exactly `TRUE` (observed/derived) or `UNKNOWN` — the
honest fall-through the bridge treats as "not this path."

---

## Part 5 — Belief & Uncertainty (`bayesian_uncertainty.py`)

The substrate holds graded beliefs and moves them with evidence. This is the engine
behind the *probabilistic* kind and behind `reflect()`.

### 5.1 The belief

`BayesianBelief` (`:86`): `prior`, `likelihood`, `posterior`, `evidence_for/against`
lists, `entropy`, a 95% `credible_interval`, and temporal-decay fields (`decay_rate`,
`last_evidence_time`). Created at prior 0.5 (max uncertainty) unless told otherwise.

### 5.2 The update (`update_belief`, `:275`)

An **odds-form Bayesian update with an exponential likelihood ratio**, decay-first:

1. Decay the prior toward 0.5 by the time since last evidence (5.3).
2. `LR = exp(±_LR_STRENGTH · evidence_weight)` with `_LR_STRENGTH = 3.0` — quality 0
   ⇒ LR 1.0 (no update), quality 1.0 ⇒ LR ≈ 20× (support) or 0.05× (against).
3. `posterior_odds = prior_odds · LR`, `posterior = odds/(1+odds)`, clamped off 0/1.
4. **Regime-shift detection**: a crossing of the 0.5 threshold flags a reversal,
   feeding domain volatility (5.5).
5. Recompute **Shannon binary entropy** (`_calculate_entropy`, `:406`) and a normal-
   approximation credible interval; propagate constraints if the change exceeds 0.05.

**Constraint propagation** (`_compute_propagation_effect`, `:635`): a belief change
flows along typed relationships with per-type gains (IMPLIES ×0.8, CONTRADICTS ×−0.9,
SUPPORTS ×0.4, WEAKENS ×−0.4, MUTUALLY_EXCLUSIVE ×−0.95), applied only above 0.01,
recursing with cycle detection.

### 5.3 Temporal decay (three paths)

The functional form everywhere is drift toward maximum uncertainty:
`P ← P + (0.5 − P)·(1 − exp(−λ·Δt))`.
- **`_apply_temporal_decay`** (`:413`) — the per-belief primitive, called inside every
  update, clocked on `last_evidence_time`, λ from domain volatility.
- **`apply_temporal_decay_to_all_beliefs`** (`:1459`) — the batch pass driven by
  `reflect()`: decays every belief idle > 1 h, **removes** a belief that decayed into
  the neutral band [0.45, 0.55] with fewer than 3 evidence items (and deletes its
  row), else persists the decayed posterior.
- **`decay_belief`** (`:1267`) — a single belief without new evidence, clocked on
  `last_updated`.

### 5.4 Consistency

Two methods with different jobs:
- **`check_consistency`** (`:677`, sync, read-only): detects IMPLIES violations
  (`source > target + 0.15`), CONTRADICTS (`sum ∉ [0.8,1.2]`), MUTUALLY_EXCLUSIVE
  (both > 0.7).
- **`check_belief_consistency`** (`:1518`, async, *repairing*, driven by `reflect()`):
  a high-confidence CONTRADICTS pair is a violation and the **weaker** belief (fewer
  evidence items) is reduced ×0.9; an IMPLIES pair with a likely source and unlikely
  target **boosts** the target. Mutations are persisted.

### 5.5 Domain volatility (`update_domain_volatility_metrics`, `:1586`)

Per domain, an **adaptive decay rate**: `λ = 0.01 + avg_belief_change·0.1 +
regime_penalty`, clamped [0.005, 0.1], where `regime_penalty = min(shifts·0.005,
0.05)`. A volatile domain (frequent large swings and reversals) decays its beliefs
faster. Persisted to `unified.domain_volatility` and reloaded on boot.

### 5.6 Calibration

`record_prediction` + `_update_calibration_metrics` (`:974`, needs ≥10 predictions)
compute a **Brier score**, calibration error, and an over/under-confidence bias —
the substrate measuring whether its stated confidences match outcomes.

### 5.7 Persistence

`unified.beliefs` (upsert / delete / load), `unified.domain_volatility`,
`unified.known_unknowns`, `unified.calibration_data`. Decision-critical writes are
awaited and committed (`flush_belief`); routine writes are fire-and-forget and skipped
cleanly if no event loop is running. Dropped writes are counted and surfaced in
`get_statistics`.

---

## Part 6 — The Epistemic Engine (`epistemic_engine.py`)

A facade over the belief system and the hypothesis system that turns *experience* and
*reasoning output* into durable belief, and identifies where the substrate's own
knowledge is unsettled. It records only **real** entropy changes (`EPSILON = 1e-4`).

- **`assess_uncertainty(request)`** (`:614`): uncertainty = mean entropy over the
  **unstable regions** of the belief graph (capped at 1.0); confidence = `1 −
  uncertainty`. This is a *global* property of the belief graph, used to annotate a
  reasoning result — not query-conditioned.
- **`apply_reasoning_output(outputs)`** (`:174`): folds `{hypotheses, belief_updates}`
  into the graph under a lock, snapshotting entropy before/after each belief and
  recording one `EpistemicMutation` per belief on the **net** delta (anti-farming — a
  belief nudged back and forth does not manufacture information gain). A prior within
  `PRIOR_INFORMATION_THRESHOLD = 0.05` of 0.5 creates the belief but records no
  mutation (a near-neutral claim carries no information).
- **`observe_tool_result(...)`** (`:394`): a **failed** call returns `[]` immediately
  (failure never lowers uncertainty); a successful one is canonicalized by
  `interpret_tool_output` (`:498`) — mapping a tool name to a capability id
  (`run_python → execution.python`, etc.) and its output to a belief update ("the
  task's test suite passes", parsed from pytest counts; "changes applied to disk",
  from write byte-deltas; lint/security/research claims) — then routed through
  `apply_reasoning_output`. An empty interpretation yields `[]` — a three-valued
  UNKNOWN, no belief manufactured.
- **`get_unstable_regions()`** (`:655`): the exploration driver. Returns
  `EpistemicTarget`s sorted by entropy from three sources: high-entropy beliefs
  (`entropy > 0.7`), resolvable known-unknowns with information value ≥ 0.5, and
  *stalled* hypotheses (proposed/inconclusive, aged past `STAGNATION_HOURS = 24`, with
  below-minimum evidence). Intrinsic motivation consumes these targets to generate
  exploration goals; goal *generation* is external, this engine supplies the raw
  material.
- **Reward converters** (`:816`): `summarize_epistemic_mutations` maps entropy removed
  / added / structural into saturating signals (`1 − exp(−total/scale)`); it
  deliberately does not claim `contradiction_resolved` it cannot measure.

---

## Part 7 — Hierarchical Abstraction (`hierarchical_abstraction.py`)

Where repeated experience becomes reusable structure. This is what `abstract_over_
memories` and the schema-decay half of `reflect()` drive.

### 7.1 Schemas and the lattice

A **schema** (`ProbabilisticSchema`, `:49`) is an induced probabilistic
condition→outcome rule with supporting memories, counterexamples, a Laplace point
estimate, and decay/reinforcement state. Abstraction is a **four-level lattice**
(`AbstractionLevel`): EPISODIC (raw memories) → PATTERN → SCHEMA → PRINCIPLE, held as
a constraint graph of `ConceptNode`s with abstraction/implication/contradiction edges
and two enforced invariants (an implication requires `P(parent) ≥ P(child) − 0.15`; a
contradiction requires `P(a)+P(b) ∈ [0.8,1.2]`).

### 7.2 Formation (`monitor_abstraction_pressure` / `process_memories`)

The pipeline is **normalize → cluster → score pressure → threshold gate → extract
schema**:

1. **Cluster** recent memories by cosine similarity ≥ 0.75, keeping clusters of ≥ 3
   (falling back to grouping by memory type if embeddings are unusable — malformed
   embeddings are dropped, never fatal).
2. **Score abstraction pressure** (`:205`) as a weighted sum:
   `1.0·frequency + 2.0·cross_context + 1.5·outcome_coherence + 1.2·temporal_
   consistency + 0.8·reusability + 0.5·reasoning_depth − 3.0·contradiction (+
   1.5·domain_coherence)`.
3. **Threshold gate**: the continuous monitor uses a **dynamic threshold**
   (`:949`) that rises with the count of active and recently-formed schemas (a
   self-throttle), clamped [3.0, 10.0]; the batch path uses 5.0.
4. **Extract the schema** (`:1069`): a feature is kept in the condition/outcome only
   if its most-common value appears in ≥ 50% of the cluster; probability is the
   Laplace estimate `(positive+1)/(total+2)` over cluster members vs. scanned
   counterexamples; a belief is created from the schema at prior = its probability.

Forming a schema then **boosts** the memories it explains (capped: ≤ +50% per memory,
≤ 3 schemas per memory), **adjusts** related belief priors (cumulative cap 0.30,
relatedness gated by word overlap / domain / embedding / ontology category), adds an
attention bias, and **flags contradicting memories** for strong schemas. When ≥ 3
schemas share a domain they aggregate into a **Level-3 principle**.

### 7.3 Decay and stress testing

Each schema's **decay rate** (`:129`) is adaptive: reinforced, older, more diverse,
and *effective* schemas decay slower; **fragile** and ineffective ones faster; clamped
[0.005, 0.08]. `apply_decay_to_abstractions` (`:1842`) **removes** any schema whose
probability decays below 0.3 (and deletes its row). A **counterfactual stress test**
(`:1532`) flips a schema's condition and outcome and scans recent memory for
contradicting evidence; a net-negative stability score marks the schema fragile and
raises its decay rate.

### 7.4 Cross-domain enrichment

Detached from formation (so it can never block or invalidate it) and
**deterministic-first**: `_find_analogical_mappings` uses the deterministic analogy
engine; only if that finds nothing *and* the schema is valuable (value ≥ 0.6 and
stress ≥ 0.6) does it escalate to a model, under a 20s timeout, splitting results into
**ACCEPTED** (`verified is True`) vs **CANDIDATE** (`verified is None`) — a candidate
never earns the significance boost.

### 7.5 Persistence

`unified.schemas` (schema_id, belief_id, probability, JSONB payload, formation_time):
upserted on formation and on a decayed-but-surviving schema; deleted when a schema
decays below 0.3; loaded on boot so induced structure survives a restart. Unknown
keys are filtered against the dataclass on load, so schema-shape drift degrades
gracefully.

---

## Part 8 — The Supporting Engines

These four engines are reached *through* the strategies and the bridge, never
directly. Each implements a rigorous core but a deliberately reduced surface; the
honest scope of each is stated here.

### 8.1 Temporal reasoning (`temporal_reasoning.py`)

A timed-proposition representation (`TemporalProposition`: a statement with a coarse
`TimePoint` — PAST/PRESENT/FUTURE/NEAR_FUTURE/FAR_FUTURE — and an optional concrete
timestamp) over a sorted `(datetime, event_id)` timeline. **Scope**:
`evaluate_temporal_formula` (`:437`) implements **three of eight** declared operators
— `ALWAYS` (universal over timeline propositions matched by exact statement),
`EVENTUALLY` (existential requiring a FUTURE time point), `NEXT` (a TimePoint
membership test). `UNTIL`, `SINCE`, `BEFORE`, `AFTER`, `DURING` fall through to the
proposition's own truth value; there is no interval algebra. **Causality** is a
weighted directed edge set (`CausalLink`, caller-supplied strength): `trace_causal_
chain` (`:502`) is a bounded backward DFS with cycle protection; `predict_effect`
takes a prediction's confidence to be the edge weight (strengths are not multiplied
along a chain). The most substantial algorithm in the file is a genuine **STRIPS-style
planner** (`plan_for_state_goal`, `:777`): breadth-first over frozenset world-states
(so the first plan is shortest and an exhausted frontier is a real proof of
unreachability), returning a typed `PlanningResult` that separates *proved-no-plan*
from *search-gave-up*, and separates a `GUARANTEED` plan from a `CONDITIONAL` one
(when a value is only computable at runtime, tracked by `pending_…` placeholders and
`value_authority.evaluate`). Persistence (`unified.reasoning_temporal_*`) is explicitly
**off the critical path and non-fatal**.

### 8.2 Hypothesis testing (`hypothesis_testing.py`)

A `Hypothesis` is a falsifiable claim record; **falsifiability is three-valued**
(`_is_falsifiable`, `:309`): value judgements and unbounded absolutes → *not
falsifiable*; measurable/conditional language → *falsifiable*; otherwise *undetermined*
(`None`) rather than a false positive. `evaluate_hypothesis` (`:842`) is a
**quality-weighted support ratio** — `support/(support+contra)` of
`strength·quality`, verdict SUPPORTED > 0.7 / REFUTED < 0.3 / else INCONCLUSIVE — not
a Bayesian update (the actual belief update is delegated to `bayesian_uncertainty`).
**Scope**: the system computes **no statistical test** — `_analyze_results` (`:656`)
reads a `p_value` the caller's experiment supplied and compares it to `0.05`; it never
computes a test statistic, a null distribution, or a sample. Predictions are
coerced from strings into structured `{prediction, measurable, test_method}` dicts by
keyword heuristics. Persistence: `unified.hypotheses` / `experiments` / `evidence`.

### 8.3 Formal argumentation (`formal_argumentation.py`)

The strongest of the four: a genuine **Dung abstract-argumentation** layer with
**preference-based defeat** on top of a Toulmin structural layer. `_build_defeat_
relation` (`:836`) counts an attack as a defeat only if the attacker's strength rank
≥ the target's (`FALLACIOUS:0 < WEAK < MODERATE < STRONG < CONCLUSIVE`), and excludes
fallacious arguments from the framework entirely. `_analyze_argument_graph` (`:934`)
computes the **grounded extension** always (least fixpoint of the characteristic
function) and **preferred** (⊆-maximal admissible sets) and **stable** extensions when
tractable (`MAX_ENUMERABLE_ARGUMENTS = 18`, above which only grounded is reported and
`semantics_complete = False`). **Scope**: this rigorous core is fed by *heuristic*
front ends — attack/support/validity detection is substring-based, and fallacy
detection (`detect_fallacies`, `:544`) is regex patterns covering ~13 of 25 declared
fallacy types plus two structural detectors (verbatim-circular → begging-the-question;
inductive-with-<2-premises → hasty generalization). This engine's live home is the
`reason()` fallacy annotation (1.2). Persistence: `unified.reasoning_arg_*`,
off-critical-path.

### 8.4 Analogy (`analogy_discovery.py` + `analogy_diagnostics.py`)

A **similarity-based** analogy finder, not a faithful Structure-Mapping-Theory
implementation. `_calculate_mapping` (`:467`) scores a concept pair as
`0.6·structural + 0.4·functional`, where structural similarity is **Jaccard over
relation *types*** (refined by attribute-name Jaccard when both concepts have
attributes) and functional similarity is Jaccard over function sets; an analogy's
overall `score` combines coherence, novelty (from a coarse domain-distance table),
and utility. There is no systematicity principle and no one-to-one mapping
constraint. The companion `analogy_diagnostics.py` is an instrumented observer — not
a second scorer — that decomposes the `mappings=0` failure into eight mechanisms via
two oracles (was the expected pair ever presented to the scorer; how did each
component score it) and a graph-health census, calling the production engine's own
methods so it can never mask a defect it is meant to find.

---

## Part 9 — What the architecture guarantees

Four commitments, each testable and each tested (`REASONING_PATHS_VERIFIED.md`
records 22/22 through the live system):

1. **Conclusions are derived, and the derivation is retained.** Every answer can show
   its premises, its steps, and the arithmetic behind its confidence.
2. **Confidence is computed by something other than the thing being measured.** No
   component reports its own certainty: induction uses Laplace succession, causal
   takes the weakest link, probabilistic reports a posterior, logical takes the
   solver's verdict.
3. **The order of resort is fixed** — prove, then derive, then propose — and holds for
   every request, not as a configurable preference.
4. **The system can decline**, and declining (`unsupported_input`) is distinguishable
   in the record from concluding.

None of these uses a language model; the measurements confirm none of them does. A
model is genuinely useful only for *coverage* — reading an input the substrate cannot
yet read, and proposing candidates the substrate then checks. It is a source of
suggestions, never an authority over what is true.

**Measured performance** (from `REASONING.md`): a complete inference is ≈ 1.2 ms
(less than half a trivial DB round-trip); all eleven kinds run model-free from a plain
question; the same settleable question produces the same proof at the same confidence
through all execution paths with zero model calls; conclusions persist and survive
restart while working state is correctly *not* persisted.

---

## Part 10 — Limits and honest scope

Stated at the same resolution as the capabilities, because a document that reports only
what works is not describing a system.

- **Reading is the binding constraint.** The substrate reasons well over its own
  notation and cannot yet read the same content in arbitrary English. It will prove a
  syllogism whose premises arrive separately and decline the identical content in one
  sentence. This is the difference between a system that reasons and one you can talk
  to, and it is where the work is. The `DerivedReadingFormalizer` shrinks this gap by
  *derivation* rather than by hand-written patterns.
- **Propositional readings are lossy**, which is why the router *defers* a
  propositional refutation to the kinds when the query indicates a relation the
  reading discarded (1.3).
- **Unification is one-way matching**, not full first-order unification (3.4).
- **Proof confidences are fixed constants per code path**, not calibrated measures
  (3.2). They should be read as "proved / refuted / undecided", not as probabilities.
- **Several supporting engines implement a reduced surface** of the theory their
  docstrings cite, and this document names each: temporal evaluates 3 of 8 operators
  and has no interval algebra (8.1); hypothesis testing computes no statistical test,
  only a `p<0.05` gate over caller-supplied values (8.2); analogy is label-Jaccard
  similarity, not SMT systematicity (8.4). Formal argumentation's Dung core is sound;
  its front ends are heuristic (8.3).
- **`interpret_tool_output` recognizes a fixed set of tool→belief mappings** (6):
  outside that set a tool observation yields no belief (an honest UNKNOWN, not a
  fabricated one).
- **Induction weighs the disconfirmations it is given**; it does not seek a
  counterexample that was never supplied (2.3).
- **Coverage is narrow and grows by teaching.** Every kind operates on what the system
  has been taught to represent. The trade is reliability within its coverage, at the
  cost of coverage that must be built. Whether that trade compounds (structures
  learned in one domain transferring to another) or accumulates linearly is a measured
  question addressed elsewhere in this series.

### 10.1 Defects found and fixed in this audit (2026-09-01)

Writing this reference against the live code surfaced four latent defects of one
family — broken wiring (a wrong attribute or method name) swallowed by a broad
`except` that returned a zeroed/empty success, so a crashed method read as "nothing to
do." All four were in the reflection / abstraction path and are now fixed and
verified:

1. `bayesian_uncertainty.apply_temporal_decay_to_all_beliefs` read `belief.evidence_
   count`, which does not exist — it threw the moment any belief reached the neutral
   band, aborting the decay batch and reporting "0 decayed." Now computes the count
   from the evidence lists.
2. `bayesian_uncertainty.check_belief_consistency` read `relationship.belief_id_a /
   belief_id_b / relationship_type` and `belief.hypothesis / evidence_count` — none of
   which exist — so the repair pass was inert whenever any relationship existed
   ("0 violations" meant "crashed"). Now uses `source_belief_id / target_belief_id /
   relation_type / claim` and computes evidence counts. Verified: a high-confidence
   CONTRADICTS pair is now detected and the weaker belief reduced.
3. `hierarchical_abstraction._extract_principles_from_schemas` built a `ConceptNode`
   with `schema_ids / confidence / metadata` kwargs the dataclass does not define (and
   omitted the required `content / probability`) — so Level-3 principle formation threw
   and silently never produced a principle. Now builds the node with `content /
   probability / abstraction_of / applicable_contexts`.
4. `hierarchical_abstraction._flag_contradictions` called `self.memory.get_memory()`,
   which does not exist (the API is `retrieve_memory()`, used correctly elsewhere in
   the same file) — so strong-schema contradictions were never actually flagged. Now
   calls `retrieve_memory`.

These are recorded here rather than buried in a commit because the class of defect —
a return value that fakes success while the wiring is broken — is precisely what a
scientific reader should know the system is audited *against*.

---

*Dominion Labs — Cognitive Substrate Series.*
*This reference tracks the code; when the pipeline changes, this document changes with
it. For the conceptual argument see `REASONING.md`; for the end-to-end verification see
`REASONING_PATHS_VERIFIED.md`.*
