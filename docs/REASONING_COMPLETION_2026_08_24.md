# Reasoning — completion record, 2026-08-24

What was wrong, what was done, what was measured, and what is still open.
Defect numbering continues the sequence in `MEMORY_SEMANTICS_CONVERSATION.md`,
where the full narrative for each item lives.

---

## The state before

`ReasoningType` declared eleven classical kinds of thinking. Four had strategies.
Nothing selected any of them by that enum, and the entry point could not name a
kind of thinking at all.

Underneath that, roughly 3,800 lines of working model-free reasoning sat with no
route to it: `evaluate_temporal_formula`, `establish_causal_link`,
`trace_causal_chain`, `predict_effect`, `project_future_state` and
`compare_future_states` had **zero callers in the repository**.

---

## What was done

### One vocabulary (defect 23)

`ReasoningType` had THREE definitions. Enum equality is identity-based, so
`A.DEDUCTIVE == B.DEDUCTIVE` was `False` while both printed `'deductive'` — a
strategy registered against one copy was unreachable from the other.

- `ReasoningType` merged to 18 members: the 11 classical plus 7 quantum, with
  `CLASSICAL_REASONING_TYPES` naming the list a router must reach in full.
- `InferenceStrategy` (5) and `InferenceMethod` (12) merged to 15; the latter is
  now an alias, not a copy.
- `ReasoningMode` meant three unrelated things. The uncertainty one is renamed
  `UncertaintyMode` (it described where uncertainty comes FROM, never a way of
  thinking); one in the logical agent was a fourth `ReasoningType` under the
  wrong name and is now an alias; the quantum one is `QuantumTaskType`, because
  what it selects is a quantum ROUTINE.
- All three removed from `KNOWN_SHADOW_DEBT` and added to the guard's resolved
  list, so a new copy fails the test rather than being tolerated.

### Eleven kinds, all model-free

| kind | how it works | ms | LLM |
|---|---|---|---|
| deductive | rule application by unification | 65 | 0 |
| inductive | grouping, pattern, generalisation | 3.9 | 0 |
| abductive | backward rule search, Occam, ceiling 0.7 | 3.0 | 0 |
| analogical | structure mapping | 3.1 | 0 |
| causal | causal links and chain tracing | 7.1 | 0 |
| counterfactual | state projection and comparison | 6.1 | 0 |
| spatial | **new** — transitive closure over stated relations | 3.3 | 0 |
| fuzzy | **new** — Zadeh operators with hedges | 3.2 | 0 |
| logical | Z3 | 31.1 | 0 |
| probabilistic | Bayesian prior to posterior | 3.2 | 0 |
| temporal | temporal-logic operators | 4.6 | 0 |

Five adapt engines that already existed and could not be reached by name. Two
were implemented because no engine existed. Four were already present.

### Substrate-first became the architecture (defect 28)

`_substrate_first` was called INSIDE `if mode == AUTO`. Every other mode went
straight to execution and never asked whether Torin could represent the input —
so naming a mode was, without the caller knowing, asking for the substrate to be
skipped. **Six of the seven routes were model-first.**

Now it runs for every request. `mode` says only what to do when the substrate
cannot settle it.

### The eleven reached the entry point (defect 29)

A request could name only one of seven execution ROUTES. The eleven were entered
only when the router happened to pick ABSTRACT.

- `ReasoningRequest.kinds` lets a caller name kinds of thinking; empty means
  "read it from the query".
- Kinds are tried **after the substrate and before any execution route**. That
  order is the architecture: what can be proved, then what can be derived, then
  what a model can propose.
- Context is split by what each item IS. An implication must arrive as a RULE —
  passed as a premise it is inert, and abduction sat applicable and unused while
  its query went to a model.

### The model left deduction and induction (defect 26)

Both ran their rule path and then called the model UNCONDITIONALLY — the only
thing that skipped it was the absence of a service object.

A statement the rules cannot derive is not a deduction; a pattern the examples do
not support is not an induction. There is no coverage gap for a model to fill,
because the gap IS the answer.

|  | before | after |
|---|---|---|
| deductive | 33,650 ms, 1 LLM call | **65 ms, 0** |
| inductive | did not finish in 60 s | **3.9 ms, 0** |

The reasoning paths are unchanged; only the model call was removed. The 268 lines
of now-unreachable model methods are in `backups/`.

---

## Defects found by testing, not by reading

**A propositional refutation buried the answer (30).** The substrate formalizes
propositionally, so "the chip is inside the socket" and "the socket is inside the
board" become two unrelated atoms and `chip_inside_the_board` correctly does not
follow. It returned `substrate_refuted` and the eleven never ran — while spatial
reasoning derives it in one step, because containment composes and atoms do not.
Correct about the propositions it was handed; wrong about the world. Refutations
from a lossy reading are now deferred behind the kinds, never discarded. A first
version deferred ALL refutations and a test caught it: `mortal` from `["human"]`
is a sound refutation and must stand.

**Everything blocked on a chat message (25).** Every call to the reasoning engine
hung indefinitely. Located by asyncio task introspection: the notifier retries on
429 and 5xx by sleeping and recursing, each attempt with its own 30 s timeout —
bounding one ATTEMPT, never the sequence. Reasoning waited on Slack. Fixed at
both ends: a hard deadline covering all retries, and notifications sent without
being awaited.

**The model graded its own conclusions into memory (20).** One self-reported
number was assigned to four fields, so the weighted quality composite resolved to
exactly the model's self-grade. A missing line defaulted to 0.7; an unparseable
reply still became a conclusion. That number drove `is_novel`, `actionable`,
`consequence_level` and the stored memory's importance — a model writing
`CONFIDENCE: 0.95` about its own guess got it stored as high-confidence, novel,
actionable knowledge and explicitly NOT flagged for review.

**Three low confidences, three causes (31).** A question was being counted as an
observation, halving every abductive score. Induction's confidence was
`len(premises) / 10.0` — a denominator with nothing behind it. Replaced with
Laplace's rule of succession.

**Induction counted its counterexamples as support (32).** Grouping is by word
overlap > 0.3, so "swan d is black" scores 0.33 against "swan a is white" and is
grouped WITH the positives. Worse, an even split hides itself: with two white and
two black, neither colour reaches the pattern threshold, the pattern degrades to
the shared subject, and **evenly divided evidence scored 0.83 — higher than
three-to-one.** A contentless generalisation cannot be contradicted, and that is
what made it look strong.

| evidence | before | after |
|---|---|---|
| 3 white, no counterexample | 0.80 | 0.80 |
| 3 white + 1 black | 0.80 | 0.67 |
| 2 white, 2 black | **0.83** | **0.50** |
| 9 white | 0.91 | 0.91 |

**The record could not say what kind of thinking produced it (33).** Stored
memories were tagged with the execution route, so a causal derivation and a
spatial one were indistinguishable and nothing could ask what Torin had concluded
causally.

Also: two health checks that could not fail, a cached-load statistic that never
incremented, 46 production `print()` calls in the memory authority, and a prompt
dump writing injected memories to stdout.

---

## Verified against the real system

Through `bridge.reason(ReasoningRequest(query, context))`, default mode, nothing
constructed by hand:

- **11 kinds reachable from a plain question** — 9/9 on cases carrying material,
  0 LLM calls
- **All 7 execution routes** returning the substrate's proof with 0 model calls
- **Counterexamples** — 0.80 / 0.67 / 0.50 / 0.91, arithmetic visible in the
  returned steps
- **Persistence** — a real row in the memory store, tagged with the kind
- **Restart** — two separate interpreter runs; the conclusion, the rules and the
  ability to reason all survive, and nothing accumulates across repeats

169 reasoning and memory tests pass.

**Stated plainly: two verifications were originally done wrong** — a hand-built
context and a spy that never wrote — and would have passed with their fixes
reverted. Both were re-done through the real entry point. The distinction between
a unit test of a strategy and a test of the wiring decides what a number means.

---

## Still open

**The reading problem, which is the real constraint.** The substrate reasons well
over its own notation and cannot read the same content in English. Measured:
variables need a `?` prefix, so `human(X)` reads `X` as a constant and matches
nothing — silently. Propositional atoms without parentheses are unreadable to
deduction. A conjunctive rule body produced nothing; not investigated.

**Induction has no counterexample search.** It counts what it was given. Nothing
looks for a disconfirming case that was not supplied.

**The seven execution routes are still the old vocabulary.** Naming them for what
they are is cosmetic now that they run only after the substrate and the kinds,
but it would stop them reading as a competing taxonomy.

**`AbstractReasoningEngine` and `RuleInducer` are two inductions.** They take
different inputs and are not simply redundant, but if they must become one
authority, `RuleInducer` is the one with the experimental evidence behind it.
