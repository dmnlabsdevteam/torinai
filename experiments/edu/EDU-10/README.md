# EDU-10 — Active Learning Under Stochastic and Partial Observation

## Claim

Across deterministic, stochastic, and partially observable conditions, Torin
recovered the true polarized causal structure in every evaluated seed while
maintaining zero false structural refutations. Stochasticity increased median
evidence requirements from 25 to 32 observations, and partial observation to
36, while hypothesis-specific reliability posteriors captured action
uncertainty independently of structural truth. Active learning remained
model-free throughout.

**Thirty deliberately misleading stochastic failures and eighteen misleading
leak successes were insufficient to corrupt the true structural hypothesis.**

## In plain terms

Every earlier lesson lived in a world where the same setup always gave the same
result. If Torin expected the forklift to move a pallet and it didn't, that was
proof its rule was wrong.

Real machinery isn't like that. A correct procedure fails sometimes. A wrong
one occasionally works anyway. And sometimes nobody can tell what happened.

A learner that treats one disappointment as proof will throw away a perfectly
good rule the first time reality misbehaves. A learner that ignores
disappointments will never fix a rule that is genuinely wrong. Torin has to
tell those two apart, and the only way is to keep two separate books:

- **the structure** — which conditions the action needs, and which must be absent
- **the reliability** — how often it works when those conditions ARE met

A failure with everything in place is news about *reliability*. It is news
about *structure* only if some other structure explains the whole record
better. Here the action works 90% of the time when its preconditions hold, 2%
of the time when they don't, and in one condition 10% of attempts come back
"couldn't tell". Torin gets the observation. It never gets the truth.

## Result

Thirty seeds per condition. Criterion is posterior mass ≥ 0.95 on the exactly
correct structure, not merely a surviving hypothesis.

| condition | reached | median obs | 95% hi | MAP = truth | trap sprung | false refutations | Brier | ECE |
|---|---|---|---|---|---|---|---|---|
| A deterministic | **100%** | 25 | 25 | **100%** | 0 | **0** | 0.003 | 0.051 |
| B stochastic | **100%** | 32 | 44 | **100%** | 30 | **0** | 0.032 | 0.030 |
| C partial *(+UNKNOWN)* | **100%** | 36 | 50 | **100%** | 27 | **0** | 0.033 | 0.031 |

- 8 conditions · 256 hypotheses · proposal budget 8 · truth = 5 required + `LOCKED` forbidden
- noise costs ~28% more observations (25 → 32); unobservable outcomes another ~12% (32 → 36)
- reliability learned by the winning structure: **0.90 / 0.836 / 0.844** against a true 1.00 / 0.90 / 0.90
- held-out accuracy 1.000 / 0.968 / 0.968 · oracle probability error 0.051 / 0.039 / 0.041
- 110 UNKNOWN observations in C, none of which moved any posterior or any rate
- deliberate replications *(a repeat preferred over an untried option on the same menu)*: 207 / 299 / 337
- same seed reproduces the manifest **byte-for-byte**; restart preserves belief in every trial

- **misleading successes** *(violated structure, world succeeded anyway)*: 0 / 18 / 19

**"Trap sprung" is the number that makes "0 false refutations" mean anything.**
It counts the situations where the true structure held and the action failed
anyway — the exact case that destroys a deterministic learner. It happened 30
times under noise and never once cost the truth its standing. It is correctly 0
in A, where a satisfied structure never fails.

The same applies to misleading evidence in the other direction. A success under
a *violated* structure is logically impossible in a deterministic world, so it
would be a valid refutation there. It occurred 18 times under noise and 19 with
partial observability — measured, not assumed — and the correct structure still
won every seed.

Three invariant probes, run before the conditions:

```
4S then F, valid world : mass 0.0089 -> 0.0063 -> 0.0071   above prior(0.0039)=True  recovers=True
5F with LOCKED present : belief in FORBIDDEN polarity 0.5581   moved=True
10 UNKNOWN             : posterior unchanged=True  reliability unchanged=True  counted=True
```

The first is the decisive one. Four successes then a failure leaves belief in
the true rule *above its own uniform prior*, and the next success moves it back
up. Survival is defined that way on purpose: a rule that one unlucky trial
pushed below its prior has been refuted regardless of how gentle the arithmetic
looked, and a rule that cannot climb back was being punished rather than
weighed.

## Method

```
EDU10_SEEDS=30 ./venv_torin/bin/python3 experiments/edu/EDU-10/experiment.py
```

No language model is involved. The learner is
`core/learning/probabilistic_version_space.py`; the world is
`experiments/warehouse_stochastic.py`, which returns `(observation, truth)`
where the truth is used **only** by the experiment to measure calibration and
is never passed to the learner.

## Failures and fixes

Four defects, each found by the experiment failing rather than by inspection.

**1. The target structure was unreachable — the decisive one.** This file
declared `REQUIRED` as a literal four conditions. The world requires *five*:
it also needs `AUTHORISED`, which was missing from the vocabulary entirely. So
`structure_satisfied()` was **always False**, every attempt ran at the 2% leak
rate, and the learner was being asked to find a structure no situation it could
build would ever satisfy. This is the duplicate-authority defect class: the
world owns the causal structure, and restating it here let the two drift.
`REQUIRED`/`FORBIDDEN` are now *derived* from `warehouse_complex`, and
`assert_truth_reachable()` refuses to run an experiment whose target cannot be
satisfied.

It reported a **calibration error of 0.013 while doing this** — because
predicting "this will fail" is superbly calibrated in a world where nothing
ever succeeds. A healthy number produced by the total absence of the
phenomenon being measured.

**2. Uniform priors made learning impossible.** With `Beta(1,1)` on both rates,
satisfying a structure and violating it both predicted success at 0.500. Every
hypothesis made an identical prediction about every situation, expected
information gain was exactly zero everywhere, and the learner correctly took
**zero observations**. The priors are now weakly asymmetric — `Beta(2,1)` on
reliability, `Beta(1,2)` on leak. That encodes the *definition* of a
precondition (satisfying one helps) and nothing about which conditions those
are; three pseudo-counts each, so two real observations outweigh them.

**3. One global reliability, split fractionally, collapsed.** The first version
kept a single reliability and a single leak shared by all 256 hypotheses, and
divided each observation between them in proportion to posterior belief. That
is a credit-assignment approximation, not a posterior, and it fails in a
specific way: while belief is diffuse, half of every violated-structure failure
is charged to reliability. Most *discriminating* experiments violate the true
structure — that is what makes them discriminating — so reliability collapsed
to **0.05 against a true 0.90**, and once reliability was indistinguishable
from leak nothing discriminated anything and learning stopped dead. Each
hypothesis now carries its own four counts, making it a complete generative
model, and the posterior is the exact Beta-Bernoulli marginal likelihood.

**4. Two metrics that could not report bad news.** `false_refutations` counted
occurrences without counting *opportunities*, so a 0 meant "never happened" and
"never possible" indistinguishably; it now records both. And "calibration" was
mean absolute error, which is **not a proper scoring rule** — it is minimised
by confident 0/1 predictions, so an overconfident learner scores better on it
than a correctly uncertain one. Replaced with Brier (strictly proper), binned
ECE, and the exact error against the world's real rates.

A fifth issue was diagnosed and dismissed: a structured ablation proposer
replaced random sampling, which did not fix the collapse (defect 3 did). It was
kept anyway — random subsets were EDU-09's failing condition and are no better
here.
