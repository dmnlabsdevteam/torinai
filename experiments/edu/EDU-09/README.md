# EDU-09 — Bounded Active Teaching in a Combinatorial Situation Space

## Claim

Under a proposal budget far too small to enumerate the situation space, the
deterministic `TeacherPolicy` drives the substrate to the exactly correct rule —
including a condition that gates only by its ABSENCE — in exactly the
information-theoretic minimum number of lessons, and a bad proposer degrades
convergence without ever producing false knowledge.

## In plain terms

Torin is shown a warehouse with twelve things that can be true or false. Five of
them actually matter. One matters only by being *false* — the bay must not be
locked. The other six are pure decoration: they change constantly and affect
nothing. Torin is not told which is which.

Twelve on/off conditions make 4096 possible situations. The teacher is allowed
to suggest **eight** per lesson — about one fifth of one percent. So "try
everything" is not available; the teacher has to pick well.

The teacher's rule for picking is the one thing it cares about: *of the
explanations Torin still finds possible, how many would this situation rule
out?* The best question is the one that halves what remains.

It worked. Starting from 6,144 possible explanations, the practical teacher
reached the single correct one — including the not-locked part — in 13 lessons.
A cheating version that is allowed to inspect all 4096 situations before
choosing took 12. So the honest teacher, which only ever looks at what Torin
still believes, costs exactly one extra lesson.

The random teacher never got there. It stalled with 121 explanations still
standing and reported that nothing it could offer would help. That is the
important half: **it left Torin uncertain, not confidently wrong.**

## Result

| condition | converged | correct rule | lessons | proposal precision | false knowledge |
|---|---|---|---|---|---|
| A random | 0% | 0% | — | 0.33 | **0%** |
| B search *(deployable)* | 100% | 100% | **13** | 0.52 | **0%** |
| D oracle *(ceiling)* | 100% | 100% | 12 | 1.00 | **0%** |

- situation space 4096 · version space 6,144 hypotheses · budget 8/lesson
- `log₂(6144) ≈ 12.58`, so the minimum is `⌈log₂ 6144⌉ = 13`. **B_search's 13
  lessons ARE the information-theoretic minimum**, not one lesson short of it —
  a lesson yields at most one bit, and a learner cannot take 0.58 of an
  observation. The earlier record here read the floor as 12 by dropping the
  ceiling, understating the result.
- **D_oracle's 12 is not a tighter bound; it is a lucky realisation.** 13 is the
  minimum only in the *worst case*, which is what an information-theoretic bound
  describes. The oracle's twelfth lesson split its 4096 remaining hypotheses
  2048/2048 and the world happened to return the branch that also resolved the
  final ambiguity, carrying ≈1.585 bits rather than 1. A bound on the worst case
  is not violated by a favourable outcome on one path, and the oracle inspects
  all 4096 situations to pick its eight — which is exactly what the budget
  forbids. Nothing here beats 13; one run got a good roll.
- "correct" requires all five causal preconditions **and** `LOCKED: forbidden`
- name-blindness: semantic and opaque vocabularies give identical trajectories

**D_oracle is a ceiling, not a competitor.** It inspects all 4096 situations to
choose its eight, which is precisely what the budget exists to forbid. It says
what the best possible teaching sequence looks like.

## Method

```
EDU09_TRIALS=2 ./venv_torin/bin/python3 experiments/edu/EDU-09/experiment.py
```

No language model is involved. `TeacherPolicy` is the teacher; the proposers are
deterministic and differ only in how well they search.

## Failures encountered, and what was changed

- **`MAX_LESSONS = 12` was the result.** It cut `B_search` off at two surviving
  hypotheses and reported "converged 0%" — measuring the cap, not the proposer.
  A perfect binary search needs 13. Raised to 20 so the reported number is
  lessons-to-converge.
- **The name-blindness check was a print statement.** It announced the
  relabelling and verified nothing. Made to actually run — and it immediately
  failed with `KeyError: 'LOCKED'`, because four places in the harness
  (`build_version_space`, `consistent`, `gain_of`, `propose_search`) hardcoded
  that string. The code asserting it read only the version space was reaching
  for a word. Now read at call time.
- **Pair counting was the wrong currency.** With 6,144 hypotheses a lesson that
  peels off one outlier scores nearly as many pairs as one that halves the
  space. `choose_lesson` ranks by expected survivors, `sum(|block|²)/n`.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result
- `../../warehouse_complex.py` — the world (enforces its own preconditions)
