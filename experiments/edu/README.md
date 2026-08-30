# EDU — the education benchmark ladder

> **What this ladder is evidence for.** TorinAI is a persistent, model-optional
> experimental cognitive architecture with substrate-native learning, causal
> reasoning, active experimentation, cross-domain transfer, planning, action,
> self-correction, and probabilistic epistemic control.
>
> *Model-optional* is the load-bearing word, and it is a claim these
> experiments have to earn rather than assert: a language model may propose,
> formalise, or teach, but nothing it emits is admissible as evidence. Every
> result on this ladder was produced with no model in the loop.

One folder per experiment, append-only. **Numbers are never reused or
reassigned**: manifests are frozen, and citations, hashes and reports must keep
resolving.

Each folder holds `README.md` (claim, plain-language explanation, method,
failures and fixes), `experiment.py`, and `manifest.json` where a result was
frozen.

## Two axes, deliberately separate

**Competence** is what Torin has learned. **Teachability** is how efficiently it
can be taught. They are different questions and a teaching experiment is not a
higher level of competence, so the teacher track is not EDU numbered as Levels
7 and 8.

### Competence ladder — FROZEN

```
Level 1  Recall
Level 2  Generalization
Level 3  Composition                                          EDU-01
Level 4  Cross-domain structural analogy                      EDU-06  CLOSED
Level 5  Error-driven self-correction                         EDU-02  CLOSED
Level 6  Functional cross-domain transfer                     EDU-07  CLOSED
         source knowledge reduces target evidence burden
```

### Teacher capability track

```
EDU-08  Safe active teaching with a stochastic proposer       measured
EDU-09  Active teaching under combinatorial search constraints  CLOSED
EDU-10  Active learning under stochastic + partial observation  CLOSED
EDU-11  Causal discovery with an unobservable cause             CLOSED
EDU-12  Open-domain autonomous competence acquisition           STAGE 1/5
```

| | experiment | result |
|---|---|---|
| EDU-01 | Discriminating evidence → compositional capability | 2/9 → 9/9 |
| EDU-02 | Autonomous runtime refutation | VALIDATED → REFUTED |
| EDU-03 | First transfer attempt | superseded by EDU-04 |
| EDU-04 | Structural correspondence to an unfamiliar observation | GROUNDED 1.00 |
| EDU-05 | Executed action becomes root evidence | own root, 0 model calls |
| EDU-06 | Action-schema analogy between two real learned domains | 1.00 across domains |
| EDU-07 | Functional cross-domain transfer | N_A=1 vs N_B=6 |
| EDU-08 | Safe active teaching (stochastic proposer) | safety PASS · efficacy 40% |
| EDU-09 | Bounded active teaching, 4096 situations, budget 8 | 13 lessons = the information-theoretic minimum · 0% false knowledge |
| EDU-10 | Active learning under stochastic + partial observation | true structure in every seed · 30 misleading failures + 18 leak successes failed to corrupt it |
| EDU-11 | Causal discovery with an unobservable cause | latent recovered at 0.976 alignment where identifiable · 0% false positives where it is not |
| EDU-12 | Open-domain competence across 4 heterogeneous subjects | *stage 1:* generality invariants held · S0 baseline with 0% false confidence |

## Standing invariants

**Analogy proposes; only target-domain evidence authorizes.** A projected rule
enters as CANDIDATE with zero evidence roots and reaches VALIDATED only by
surviving target observations it was not built from.

**The proposer proposes a SITUATION; the world supplies the OUTCOME.** There is
deliberately no edge from `model says outcome` to `evidence`. A model may waste
a setup; it cannot create a fact.

**Safety and efficacy are never one number.** A teacher that succeeds once in a
hundred trials and never corrupts knowledge is safe and not useful. Reporting a
single PASS hides which one you have.

**`model_calls: 0`** for every competence claim. A capability demonstrated with a
model in the loop is a claim about the model.

**A negative only constrains a hypothesis when the predicted OBSERVATION would
otherwise differ.** Not whether the rule fires internally — what an observer
could see. Enforced by `core.learning.teacher_policy`.

**Unmeasured is not negative.** An ablation returning UNREACHABLE is honest; one
returning a confident wrong answer is not.

## Open systems findings

`SESSION-01` — proposal quality appears to degrade across repeated calls within
one process (1/5 convergence in-process vs 3/5 across separate processes, and
one trial that proposed nothing). Cause unknown; kept as its own probe rather
than buried inside a capability experiment.
