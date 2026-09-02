# TR-2026-09 — Knowledge Gaps vs. Procedural Competence in the TorinAI Domain System

**Status:** verified · **Experiment:** `experiments/DOM-KG-01/experiment.py` · **Result:** 15/15 checks pass

---

## Abstract

A cognitive substrate that learns from being *taught* accumulates two distinct
kinds of mastery over a subject: **declarative knowledge** (facts it holds) and
**procedural competence** (operations it can execute). A system that conflates
them mis-reads its own state — treating "I have not been told that fact yet" as
"I am not competent here," or vice versa. We formalize the two as independent,
separately-measured axes of the TorinAI domain system, state four falsifiable
hypotheses about their discrimination and orthogonality, and test them against
the running substrate. Three held at baseline; the fourth — **localized
detection of a declarative knowledge gap inside an already-mature domain** —
failed, because the epistemic system's *known-unknown* register, though present,
had no producer. We implemented the missing detector (`detect_knowledge_gap`, the
declarative twin of the procedural `CONCEPT_GAP`), and all four hypotheses now
hold, with negative controls confirming the detector does not fabricate gaps and
leaves operator competence untouched. We contrast this with the behavior of an
autoregressive language model, which has no representation of the boundary and
therefore cannot abstain on the basis of it.

---

## 1. Introduction

Ask a large language model a question whose answer was underrepresented in its
training data and it will, absent special conditioning, produce a fluent,
confident answer anyway. It has one channel — next-token likelihood — and no
internal variable that separates *"I hold little information about this"* from
*"I cannot perform this operation."* Both surface as the same thing: a
distribution over tokens. The failure mode we call "hallucination" is, in part,
the absence of that boundary.

TorinAI is a persistent, model-optional symbolic substrate: subjects it learns
become **domains**, each carrying explicit, inspectable state. This report
concerns one boundary within that state — the one an LLM lacks:

> Within a **mature** domain (one the substrate knows a great deal about), can it
> detect a *specific* missing fact and respond by **acquiring** it, without
> mistaking that gap for a loss of **procedural competence**?

The distinction matters because the two call for opposite responses. A
*knowledge* gap is closed by acquisition — research, or being taught. A
*competence* gap is closed by practice — exploring for an operator that produces
the goal. Routing one to the other wastes effort and, worse, corrupts the
substrate's estimate of what it can do.

---

## 2. Architecture background

### 2.1 Two axes, measured separately

| Axis | What it measures | Where it lives | How it moves |
|---|---|---|---|
| **Declarative knowledge coverage** | how much the substrate *knows* about a subject | `Domain.maturity_score`, computed by `structural_complexity(domain)` over the concept graph (size + connectedness + relational variety, ∈ [0,1]) | rises as connected facts are taught |
| **Operator competence** | what the substrate can *do* in a subject | a Bayesian belief, *"the substrate has learned the operators of domain X"* (`bayesian_uncertainty`) | rises/falls only on operator-learning outcomes (`record_competence_evidence`), under the credit invariant |

These are wired to different producers. Teaching facts drives crystallization and
`maturity_score` (TR references: the declarative domain bridge). Acting drives the
competence belief. Neither writes the other's variable.

### 2.2 The procedural gap taxonomy

When a goal will not plan, the domain authority runs a **structural diagnosis**
(`UniversalDomainMaster._classify_deficit`) that walks the causal chain from
symbol to action and returns exactly one typed deficit. The two that matter here:

- **`CONCEPT_GAP`** — the goal predicate is *unrepresented* (appears nowhere in
  the domain's vocabulary). There is nothing to attach an operator to. Routing:
  **`ESCALATE`** — *"needs a concept proposal for an unrepresented predicate."*
- **`OPERATOR_GAP`** — the predicate is represented, but *nothing the substrate
  knows produces it.* Routing: **`LEARN_OPERATOR`** — explore for an action.

Each deficit carries an epistemic-opportunity value and a causal attribution
(`OutcomeClass`) consumed by the `AppraisalSystem`; the deficit makes no decision
itself. Crucially, `diagnose_deficit` **does not call** `record_competence_evidence`
— a diagnosed gap does not, by itself, mutate the competence belief.

### 2.3 The declarative gap register

The epistemic system has a first-class representation of *acknowledged
ignorance*: the **`KnownUnknown`** (`KnowledgeState.KNOWN_UNKNOWN`) — a
domain-scoped question the substrate knows it cannot answer, with an
`information_value` and a resolution strategy. This is the declarative analog of
`CONCEPT_GAP`: not "I cannot act," but "I do not hold this fact."

---

## 3. Hypotheses

- **H1 — Gap-type discrimination.** For an unmet goal predicate, the substrate
  diagnoses `CONCEPT_GAP` iff the predicate is unrepresented, and `OPERATOR_GAP`
  iff it is represented but has no producer; the two are distinct.
- **H2 — Routing/attribution separation.** `CONCEPT_GAP` routes to `ESCALATE`
  (acquire) and `OPERATOR_GAP` to `LEARN_OPERATOR` (explore); the operations
  differ.
- **H3 — Axis orthogonality.** In a mature domain, teaching additional facts
  raises declarative coverage (`maturity_score`) without moving operator
  competence.
- **H4 — Declarative gap detection.** An in-domain question a mature domain
  cannot answer (a missing relation on a known subject) is registered as a
  domain-scoped `KNOWN_UNKNOWN`, the operator-competence belief is left
  unchanged, and no gap is fabricated when the subject is out-of-domain or the
  relation is already present.

**Null / falsification.** H4 is falsified if the unanswerable in-domain query
registers *nothing* (no gap tracked), or if it lowers operator competence
(conflation), or if the detector reports a gap where none exists.

---

## 4. Methods

### 4.1 Apparatus

All checks run against the live substrate (`experiments/DOM-KG-01/experiment.py`).
H1/H2 exercise the pure structural classifier and deficit properties directly.
H3/H4 build a **mature declarative domain** by teaching a connected fictional
taxonomy through the ordinary conversation path:

```
a zephinx is a morphel ; a morphel is a glindar ; a brythe is a glindar ;
a quennel is a glindar ; a vornak is a glindar ; a drayle is a glindar
```

Fictional lexemes are used deliberately: real English words are re-homed by a
residual WordNet-derived alias path into a `wordnet` blob (a known, separate
pollution issue), which would confound domain identity. The taxonomy crystallizes
into `domain_glindar`.

### 4.2 Key algorithms (as implemented)

**Declarative coverage** — `structural_complexity(domain)`:
```
size    = min(1, |concepts| / 20)
density = min(1, (Σ |related_concepts| / |concepts|) / 4)
variety = min(1, |distinct relation verbs| / 12)
coverage = 0.4·size + 0.3·density + 0.3·variety           # -> Domain.maturity_score
```

**Procedural diagnosis** — `_classify_deficit(predicate, …)` (branch order):
```
if predicate ∉ vocabulary:          return CONCEPT_GAP        # unrepresented
if no actionable producer:           return OPERATOR_GAP       # represented, no op
if no validated producer:            return CAUSAL_GAP
if no bound producer:                return BINDING_GAP
… else PREREQUISITE_GAP / UNKNOWN_GAP
```

**Declarative gap detection** — `detect_knowledge_gap(domain_id, subject, relation)`
(new; the declarative twin of `CONCEPT_GAP`):
```
domain  = registry[domain_id]                       # None -> no gap
concept = domain.concepts where name == subject     # None -> not in-domain, no gap
if relation ∈ concept.relationships:                return None      # present, no gap
register KNOWN_UNKNOWN(question = "what does <subject> <relation>?",
                       domain   = domain_id,
                       blocking = "relation unrepresented (knowledge gap, not operator gap)")
# operator-competence belief is deliberately NOT touched
return the KnownUnknown
```

### 4.3 Measurements

`maturity_score` is read from the registry; operator competence is the
`posterior_probability` of the domain's competence belief; declarative gaps are
counted in `bayesian_uncertainty.known_unknowns` filtered by domain.

---

## 5. Results

### 5.1 Baseline

| Hypothesis | Result | Evidence |
|---|---|---|
| H1 gap-type discrimination | **PASS** | `photosynthesizes` → `CONCEPT_GAP {predicate_in_vocabulary: False}`; `flies` (represented, no op) → `OPERATOR_GAP {actionable_producers: 0}`; distinct |
| H2 routing/attribution | **PASS** | `CONCEPT_GAP → escalate` ("needs a concept proposal…"); `OPERATOR_GAP → learn_operator`; distinct |
| H3 axis orthogonality | **PASS** | teaching raised maturity **0.2293 → 0.2925**; operator competence held at **0.5** |
| **H4 declarative gap detection** | **FAIL** | no `detect_knowledge_gap`; the `KnownUnknown` register had **no producer** — the mechanism existed but nothing wrote to it |

The baseline result is itself the finding: the *procedural* boundary is fully
wired and correct, and the two axes are already orthogonal, but a mature **taught**
domain had **no way to localize a knowledge gap**. (The procedural diagnosis does
not apply — it front-loads an `OBSERVATION_GAP` check requiring an observer/tool
bindings, which a purely declarative domain has none of; running it on a taught
domain is a category error, not a gap detector.)

### 5.2 Fix

Implemented `UniversalDomainMaster.detect_knowledge_gap` (§4.2): a missing
relation on a known in-domain subject is registered as a domain-scoped
`KNOWN_UNKNOWN` with a positive `information_value` and a resolution strategy;
the operator-competence belief is not touched.

### 5.3 After fix

| Check | Result | Evidence |
|---|---|---|
| H4.gap_detected | **PASS** | `known_unknowns[domain_glindar]` 0 → 1 |
| H4.competence_untouched | **PASS** | operator competence 0.5 → 0.5 (a knowledge gap is **not** a competence loss) |
| H4.gap_resolvable | **PASS** | `information_value = 0.6`, resolvable = True (the *respond* substrate: acquire, don't explore-for-operator) |
| H4.no_false_gap (out-of-domain) | **PASS** | out-of-domain subject → no gap registered |
| H4.no_false_gap (present) | **PASS** | once `eats` is taught, the same query registers no gap |

### 5.4 Closing the loop — a detected gap is pursued (H5)

A gap that is only *registered* is inert. The final requirement is that a
detected gap becomes something the substrate *wants to close*. Known-unknowns are
therefore surfaced by `EpistemicEngine.get_unstable_regions()` as a third kind of
unstable region (`target_type="knowledge_gap"`), and intrinsic motivation turns
them into **acquisition goals** — routed for *acquisition* (research / being
taught), explicitly **not** the belief-experiment gate. Because every
crystallized domain contributes a competence belief at posterior 0.5 (maximal
entropy), gaps are few and beliefs are many; `_generate_epistemic_goals`
therefore reserves up to half the goal budget for gaps so a concrete, resolvable
gap is never starved by the diffuse belief sea.

| Check | Result | Evidence |
|---|---|---|
| H5.gap_is_exploration_target | **PASS** | a registered gap appears as a `knowledge_gap` target (entropy 0.94) |
| H5.routed_to_acquisition | **PASS** | marked `requires_acquisition`, **not** `requires_epistemic_output` |
| H5.becomes_acquisition_goal | **PASS** | intrinsic motivation emits an acquisition goal for the gap, with reserved budget |

These acquisition goals enter the live goal stream via
`generate_curiosity_driven_goals`, so a detected gap is *explored*, not merely
recorded. **15/15 checks pass.** Full transcript: `experiments/DOM-KG-01/result.json`.

---

## 6. Discussion

**The orthogonality invariant is the load-bearing result.** H3 and
H4.competence_untouched together establish that the two axes move independently:
declarative growth does not inflate procedural competence, and a declarative gap
does not deflate it. This is what licenses the substrate to say *"I do not hold
that fact yet"* rather than *"I am not competent in this domain"* — a distinction
it can now make because the two are separately represented and separately moved.

**Contrast with autoregressive LLMs.** An LLM has no `maturity_score` and no
competence belief; it has a single likelihood surface. Confronted with the H4
scenario — a well-covered subject with one missing fact — it cannot register a
`KNOWN_UNKNOWN`, because it has no register and no notion of *this domain's*
coverage as distinct from *this operation's* feasibility. Its honest-abstention
behavior, where it exists, is a trained surface behavior over token likelihood,
not a read of an internal gap variable. TorinAI's abstention here is mechanical:
the fact is absent from the concept graph, so a typed, resolvable unknown is
created, scoped to the subject, without perturbing the competence estimate.

**Limitations — status after follow-up.**
1. ~~`detect_knowledge_gap` is the detector, not the trigger.~~ **Resolved.**
   `Conversation.understand` now registers a domain-scoped known-unknown when an
   *asked* question resolves to a concept in a crystallized subject domain yet
   yields **no answer** (`Conversation._register_domain_gap`), with operator
   competence untouched. Verified live (§ appendix: brass domain, "what is a
   trombone made of" → gap registered, competence 0.5→0.5).
2. ~~No domain-level sparse-region map.~~ **Resolved.**
   `UniversalDomainMaster.knowledge_sparsity_map` ranks a domain's concepts by
   connectivity (degree, both directions), surfacing the thin regions where a gap
   most likely sits — the localized complement of the global `maturity_score`.
3. ~~WordNet residual-alias capture of real-word subjects.~~ **Resolved.**
   The dangling `wordnet:*` aliases (and the bulk concept dump) were purged;
   real-word teaching now files under `conversation` and crystallizes normally
   (verified: a brass-instrument taxonomy → `domain_brass`, all real words). No
   live path re-populates the dump. Fictional lexemes are used in the automated
   experiment only for determinism, no longer out of necessity.
4. **Consumption resolved; execution is the downstream boundary.** Detected gaps
   are now consumed by intrinsic motivation as acquisition goals (§5.4). The one
   remaining link — an acquisition goal *executing* (research or prompting to be
   taught) and, on success, calling `resolve_known_unknown` — belongs to the
   executor/research subsystem, not the domain system. Until it is wired, a gap
   is detected, measured, discriminated from competence, and pursued as a goal,
   but is closed only when the fact is actually acquired and taught back in.
5. Relational-question reading is surface-form / morphology bound: `does a
   kestrel eat mice` reads only when `eat` (the base form) has been taught, not
   just `eats`. The question-level gap trigger (limitation 1) is unaffected — it
   keys on an unanswered question, not on parsing the verb.

---

## 7. Conclusion

Within a mature domain, the TorinAI substrate discriminates procedural gap types
correctly (`CONCEPT_GAP` vs `OPERATOR_GAP`, H1/H2), keeps declarative coverage and
operator competence orthogonal (H3), and — after the fix reported here — detects a
localized declarative knowledge gap and registers it as a resolvable
`KNOWN_UNKNOWN` without mistaking it for a competence loss (H4), refusing to
fabricate gaps that do not exist. The boundary an autoregressive model lacks is,
in this substrate, an explicit and separately-measured invariant. **The domain
system meets its knowledge-gap/competence discrimination requirement.**

---

## Appendix A — Reproduction

```
./venv_torin/bin/python3 experiments/DOM-KG-01/experiment.py
```

Prints per-hypothesis PASS/FAIL and writes `experiments/DOM-KG-01/result.json`.
Deterministic; teaches and then scrubs its fictional taxonomy each run.

## Appendix B — Provenance of the mechanisms

| Mechanism | Location |
|---|---|
| `structural_complexity` → `maturity_score` | `core/domain/domain_types.py`; `universal_domain_master.update_knowledge_coverage` |
| `_classify_deficit`, `diagnose_deficit`, deficit taxonomy & routing | `core/integration/universal_domain_master.py` |
| operator competence belief | `universal_domain_master.ensure_competence_belief` over `core/reasoning/bayesian_uncertainty.py` |
| `KnownUnknown` register | `core/reasoning/bayesian_uncertainty.register_known_unknown` |
| `detect_knowledge_gap` (new) | `core/integration/universal_domain_master.py` |
