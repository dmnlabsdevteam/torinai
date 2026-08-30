# EDU-12 — Open-Domain Autonomous Competence Acquisition

> **During the frozen educational phase, failures may repair the EXPERIMENT but
> may not expand Torin's cognitive implementation.**
>
> Repair: an exam that leaks an answer, a harness that bypasses the production
> ingress, a metric that cannot report failure, state that does not reset.
>
> Do not repair: Torin cannot learn percentages, cannot synthesise programs,
> cannot parse a legitimate held-out construction, cannot transfer a concept.
> Those stay as the result until EDU-12 is over — otherwise the distinction
> between *Torin learned* and *we upgraded Torin while teaching it* is lost.
>
> This is enforced, not promised: the substrate is frozen at
> `EDU-12_S0_ADMISSIBLE` (`FROZEN.json`) and every run checks the fingerprint
> before doing anything else.

**STATUS: STAGE 1 of 5 — baseline and invariants. Teaching is not wired.**
No pre/post number appears here, because instruction has not happened. A
competence table produced before education exists would be the exact fabricated
signal the rest of this ladder was built to catch.

## Central hypothesis

A single persistent Torin instance, with no architecture or code changes
between subjects, can acquire usable competence in multiple previously
untrained domains through instruction and experience, determine what it does
not know, seek the information it needs, learn persistent representations and
procedures, and solve novel held-out tasks after the teacher is removed.

The headline is not a mechanism. It is: **can Torin go to school and come out
broadly more capable?**

## The generality invariant, enforced three ways

*The subject changes. The architecture does not.* That is worth nothing as a
promise, so it is machine-checked — and checked in three places, because a
single check has an obvious hole and the hole is where the defect would live.

| invariant | catches | status |
|---|---|---|
| **architecture fingerprint** — SHA-256 over all 279 `.py` files in `core/`, re-checked after every block | "I quietly added a branch for chemistry" | HELD |
| **subject purity** — a subject may declare data and tool *names*; no functions, classes, lambdas, or `core` imports | "the subject file contains a solver" | HELD |
| **subject agnosticism** — the attempt path is parsed and may not name or branch on a subject | "the harness contains a solver" | HELD |

The second and third exist because the first is trivially satisfiable by moving
the domain-specific cleverness somewhere else. Exposing different **tools** is
allowed and expected — an intelligent system needs interfaces to different
worlds. The line enforced is between giving the learner a new instrument and
giving it a new mind.

Exams are **sealed** (hashed before the first lesson), checked **disjoint** from
lesson content by token overlap, and — added after stage 1 failed — **validated
as answerable** before sealing.

## S0 baseline — the first admissible one

Taken through the production ingress with the teacher model **detached**, not
merely unselected. Two earlier baselines are preserved and permanently marked
invalid; neither is evidence about the substrate.

| subject | pretest | score | UNKNOWN | false confidence | model calls |
|---|---|---|---|---|---|
| mathematics | 6 | 17% | 83% | **0%** | 0 |
| programming | 6 | 0% | 100% | **0%** | 0 |
| causal science | 6 | 67% | 33% | **0%** | 0 |
| language | 6 | 33% | 67% | **0%** | 0 |

**Zero model calls across the entire baseline**, and zero false confidence in
every subject. The substrate never asserted anything untrue: it derived
correctly or declined. That is what makes the coming pre/post comparison
readable — no guessing baseline can inflate it.

Routes actually taken, recorded per item:

```
reason_about -> neural_bridge -> SYMBOLIC -> substrate_verified   (algebra, taxonomy)
reason_about -> neural_bridge -> SYMBOLIC -> substrate_refuted    (correctly undetermined)
learning_authority -> probabilistic_version_space                 (causal structure, intervention)
```

**What the substrate can do today, and what it cannot.** The UNKNOWN column is
the interesting one, and every entry in it has a named cause:

- **can**: linear equations (Z3), taxonomic and part-whole entailment including
  generic claims, causal structure and intervention from trials
- **cannot**: sequence-rule induction, ratio and percentage, program synthesis,
  antonyms, definition parsing, multi-choice options that are not expressible
  as a proposition (left/right, first/second)

Those are measured limits, not guesses, and none of them were engineered around.

**Causal science starts at 67%, and that is a property of the profile.** EDU-09
through EDU-11 built exactly those mechanisms, so it is a trained student
sitting the one subject it already studied. The block is kept for that reason: a
profile with no expected-strong subject cannot tell you which mechanism carried
which result.

### Preserved invalid baselines

| record | why it is inadmissible |
|---|---|
| `S0_INVALID_01.json` | the harness drove `ProbabilisticVersionSpace` directly and returned UNKNOWN for everything else — it measured its own wiring, not Torin |
| `S0_ENCODING_LIMITED.json` | exam items stated their own content in forms nothing could read: `facts` in an invented `"robin is_a bird"` notation, and prompts fusing a preamble with the question so no goal could be parsed |

Both are kept. A failed baseline is part of the audit trail.

## Failures and fixes

**Stage 1's first run reported a 50% false-confidence rate in causal science,
and every one of those "errors" was the substrate being right.**

Four exam items asked which conditions were required while holding one of those
conditions present in *every* observation. `spark` appeared in all four
observations of `s_pre1`, so "requires spark" and "does not require spark"
predict identically — the evidence cannot separate them, and the minimal
consistent structure the learner returned was the correct reading of its data.

An item like that does not measure competence. It measures whether the learner
will assert more than it knows, and scores the honest answer as a failure.

The fix is not the four items. It is `exam_validity.py`, which now gates
sealing: every causal item's stated answer must be the unique MAP given its own
observations, with a margin over the runner-up, and may not name a condition
that never varies. Four items were given the discriminating observation they
lacked. False confidence went to 0%, and causal science from 33% to 67% —
the score rose because the *exam* was corrected, not the learner.

**The margin criterion replaced an absolute one.** A first version required the
stated answer to hold 20% of posterior mass, which rejected a perfectly fair
transfer item: the hypothesis space is 3ⁿ, so absolute mass shrinks with the
number of conditions and says nothing about whether an item is determined. The
scale-free question is whether the stated answer leads the runner-up.

## Method

```
./venv_torin/bin/python3 experiments/edu/EDU-12/school.py
```

Invariants also run in the suite: `tests/test_edu12_generality_invariants.py`
(21 tests). 0 model calls in stage 1.

## Stage 2 — education

The permitted chain, and the only one:

```
teacher instruction -> Contribution(PROPOSAL) -> SubstrateLearning
   -> CANDIDATE, evidence_roots = 0
   -> Torin practices / reasons / experiments
   -> independent outcome -> evidence -> authority
```

A teacher may teach anything a human teacher could communicate. It may not
modify Torin, invoke a capability owner on Torin's behalf, attest to truth, or
write validated knowledge. *"25% means 25 out of 100"* is not an evidentiary
root because a teacher said it.

**Each class has five phases, and three of them run with the teacher detached.**

| phase | teacher | purpose |
|---|---|---|
| cold retrieval | **detached** | lesson-level S0; catches spontaneous transfer from earlier classes |
| instruction | attached | explanations, worked examples, contrasts, counterexamples |
| guided practice | attached | Torin commits **before** feedback — the reverse order measures copying |
| examination | **detached** | held-out items absent from instruction and practice |
| transfer | **detached** | one problem structurally beyond what was taught |

Enforced mechanically: a phase requiring detachment checks the model is
unreachable *and* inspects every answer's route. **One model call invalidates
the lesson** rather than scoring it — an improvement whose route ends in
"teacher → answer" is not a capability.

**Learning is classified, never aggregated:**

- **RETRIEVAL** — the item was taught almost verbatim. Not impressive.
- **GENERALIZATION** — same operation, unseen instance.
- **COMPOSITION** — requires combining taught pieces, with no demonstrated
  solution. This is where evidence relevant to generality begins.

### The curriculum targets what S0 actually exposed

Not a re-teaching of what Torin already does. S0 located the frontier:

| subject | S0 competence | Stage-2 curriculum |
|---|---|---|
| mathematics | linear equations (Z3) | sequence rules, ratios, percentages, then compositions |
| programming | none through the production path | structure, variables, conditions, loops, functions, then synthesis and debugging |
| causal science | comparatively strong | richer structures, competing explanations, intervention design, uncertainty |
| language | taxonomy, part-whole, generic entailment | definitions, antonyms, relation extraction, richer sentence forms |

**Programming is the most revealing block**, because it starts at 0% correct,
100% UNKNOWN, 0% false confidence — an unusually clean educational control. If
Torin can synthesise an untaught program from acquired concepts with the teacher
absent, that is a genuine gain from zero. If it cannot because the substrate has
no mechanism for constructing programs, that is recorded as *instruction
understood, substrate unable to operationalise* — and **not fixed during the
experiment**.

### The Stage-3 exams are already sealed

`SEALED_EXAMS.json` — 40 items, each with an item hash, target capability,
required cognitive operations, difficulty, expected result and timestamp, sealed
before instruction advanced. Torin never sees them during instruction, and the
teacher never receives them: a teacher shown the questions can train to them
without anyone intending it. A test re-hashes the subject files and fails if any
sealed exam has since changed.

## Remaining stages

2. **Instruction** — lessons, with Qwen permitted as teacher; teacher assertions never admissible as evidence
3. **Self-directed curriculum** — Torin detects its own competence gaps and chooses ASK / EXAMPLE / COUNTEREXAMPLE / EXPERIMENT / PRACTICE / REVIEW
4. **Ablations A–D** — educated / fresh+Qwen / selectively ablated / model unavailable, plus delayed retention
5. **Fifth unseen domain and the Novel Mission** — learning-to-learn measured against an uneducated baseline

### What the baseline runs exposed, in order

Each S0 attempt failed for a different reason, and each reason was a real defect
found by running rather than by inspection.

1. **The harness was a sidecar** (`S0_INVALID_01`). It imported
   `ProbabilisticVersionSpace` and drove it directly. Fixed by routing every
   item to the owner of its question — `reason_about` for reasoning,
   `SubstrateLearning` for induction — and by giving the version space a public
   route at all, which it had never had.

2. **The exam could not state itself** (`S0_ENCODING_LIMITED`). Language items
   put premises in an invented triple notation and fused preamble with question.
   Corrected before any instruction existed, so nothing was tuned to a result.

3. **A generic goal could not be proved.** "Is a robin an animal?" asks about a
   KIND, and a kind is not an individual for universals to ground over —
   grounding produced `robin_robin -> robin_bird`, and `robin_robin` is never
   asserted, so a question its premises plainly entail returned "not entailed".
   Proving something of a kind is proving it of an arbitrary member, so one is
   introduced, asserted to be of that kind and nothing more. A generic claim the
   premises do NOT entail is still refused — verified by test, because a skolem
   that carries extra assumptions would make everything provable.

   This one first surfaced as **50% false confidence in language**: the harness
   mapped "not entailed" to a confident "undetermined". The substrate was wrong,
   the mapping made it worse, and both were fixed rather than the score accepted.

### Correction to an earlier claim in this file

An earlier version of this README stated that "there is no arithmetic or numeric
induction anywhere in the substrate". **That was wrong**, and it was wrong
because of a single narrow grep rather than a search. The substrate ships a Z3
constraint solver at `core/reasoning/constraint_solver.py`, and it answers this
experiment's own algebra items directly:

```
m_pre3   4x + 8 = 32   -> x = 6
m_post3  7x + 5 = 54   -> x = 7
m_post6  2x + 19 = 7   -> x = -6      (negative root, no special casing)
```

It also carries 11 non-quantum reasoning types, 10 inference methods including
constraint satisfaction, four reasoning strategies, a proof engine, Bayesian
uncertainty, hypothesis testing with experiment design, and a model-free prose
formalizer. The S0 zeros were **not** an absence of capability.

### What the zeros actually were: wiring

`attempt.py` as first written was a sidecar. It called
`ProbabilisticVersionSpace` directly and returned UNKNOWN for everything else,
so it measured what one harness had been connected to — not what Torin can do.
That is the same defect the companion had, and the same one this repository
keeps finding.

Three wiring faults were found underneath it, each verified by execution:

1. **`AutonomousCoordinator.reason_about` could never succeed.** It put the
   question into `facts` while every strategy's `is_applicable` requires
   `premises`, and never supplied `rules`. All four strategies inapplicable,
   zero conclusions, under every reasoning type — with **zero callers
   repo-wide**, so nothing surfaced it. Its `return None` made a total wiring
   failure identical to "no answer". *Fixed:* it now delegates to
   `NeuralSymbolicBridge`, which already owns mode selection, and reports an
   unwired substrate as a fault rather than as ignorance.

2. **Deduction is implemented twice, and the coordinator routed to the broken
   copy.** `DeductiveReasoningStrategy._apply_rule` matches a rule's condition
   text as a *substring* of the premise — `"x is human" in "socrates is human"`
   is False — so **no rule containing a variable can ever fire**. Its gate uses
   loose word overlap, so it passes the gate and then silently returns None.
   Meanwhile `core/learning/rule_induction.py` does real unification and binds
   `?X` to every match. Duplicate authority, still to be resolved.

3. **The prose reader was defeated by an article.** `DeterministicExtractor`
   bound its subject to a single token, so `"A robin is a bird"` returned None
   while `"robin is a bird"` parsed correctly — the sentence never reached a
   solver, and the symbolic path reported 0.0 confidence that read as "cannot
   reason" instead of "was never given it". *Fixed*, with tests.

With the reader fixed, the model-free symbolic path proves the classic syllogism
at **0.98 confidence with `verified=True`** and no model involved.

### The remaining gap is representational, not arithmetic

`"A robin is a bird"` still yields no transitivity, because an indefinite
generic is parsed as a *particular fact* (`robin_bird`) when it means **"all
robins are birds"**. Chaining `robin → bird → animal` needs the generic reading.
That is a semantic fix in a shared parser and is the next piece of wiring, not a
missing capability.

Mathematics remains the block to watch, but for the honest reason: the solver
exists and works, so the open question is whether the substrate *selects* it
without being told to — which is exactly what EDU-12 is meant to measure.
