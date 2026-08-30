# EDU-11 — Causal Discovery With an Unobservable Cause

## Claim

When a genuine precondition is absent from the observation vocabulary entirely,
Torin still recovers the correct *observable* causal structure, and it
distinguishes a hidden cause that leaves a detectable signature from one that
provably does not — positing a latent in the identifiable regime with 0.976
correspondence to the real hidden state, and refusing to posit one in both the
control and the unidentifiable regime.

**The two refusals are the result.** Any detector can find structure when told
to look; the claim worth making is that it declines when the evidence cannot
support the finding.

## In plain terms

Until now Torin was always given a list of things to look at that contained the
real answer. Its job was to work out which ones mattered.

Here one of the things that matters is not on the list at all. The forklift also
needs to be *calibrated*, and nobody can see whether it is.

The tempting mistake is not getting the rule wrong. It is getting the rule right
and then explaining away everything it cannot account for as bad luck —
"this works about half the time" — when really it works 95% of the time under a
condition nobody looked at. A missing cause quietly becomes a known number, and
the resulting model is confident, well calibrated, and wrong.

The trick is that a hidden cause changes *when* things fail, not just how often.
If the forklift's calibration drifts and stays drifted for a while, failures
arrive in clumps. If it were re-rolled every single attempt, the failures would
scatter — and then it is genuinely impossible to tell "hidden cause" from "just
unreliable", because there is nothing left to distinguish them. So Torin is
asked all three questions, and is only allowed to answer "there is something
hidden here" to the one where that is actually knowable.

## Result

Thirty seeds per regime. All three have the same success rate by construction;
only the *time structure* of the hidden condition differs.

| regime | structure ok | posits latent | alignment | residual rate | median obs |
|---|---|---|---|---|---|
| A no latent *(control)* | **100%** | 3% | 0.900 | 0.945 | 26 |
| B i.i.d. latent *(unidentifiable)* | **100%** | **0%** | — | 0.478 | 74 |
| C persistent latent *(identifiable)* | 97% | **100%** | **0.976** | 0.382 | 110 |

```
verdicts
   A_no_latent     undetermined=17  no_residual_structure=12  structured_residual=1
   B_iid_latent    undetermined=0   no_residual_structure=30  structured_residual=0
   C_persistent    undetermined=0   no_residual_structure=0   structured_residual=30
```

- 8 observable conditions · 256 hypotheses · hidden condition `CALIBRATED` · 80 residual trials
- **The hidden cause never corrupted the observable structure** — recovered in 100% / 100% / 97% of seeds
- B's residual rate of 0.478 matches the constructed 0.475 exactly; the learner's
  reliability estimate there is *correct*, and correctly says nothing about why
- an unobservable cause roughly quadruples the evidence needed (26 → 110 observations)
- 0 model calls

**B is the important column.** An i.i.d. hidden cause is not merely hard to
detect — it is indistinguishable from unreliability by any statistic computable
from a single sequence of outcomes. Zero detections in thirty seeds is the
correct answer, and a detector that "found" something there would be
manufacturing knowledge. It is scored as a pass condition, not excused in a
footnote.

**C's alignment of 0.976 is what makes the detection more than a smell test.**
The recovered latent is checked against the world's actual hidden state, which
the learner never sees. Reported as `max(agreement, 1 − agreement)`, because the
two states of a latent have no intrinsic names and recovering it perfectly
inverted is still recovering it. Chance is 0.5.

## Method

```
EDU11_SEEDS=30 ./venv_torin/bin/python3 experiments/edu/EDU-11/experiment.py
```

No language model is involved. Detection is
`core/learning/latent_cause_detection.py` — a Wald-Wolfowitz runs test on the
residual sequence, and only if that rejects independence, a two-state HMM fitted
by Baum-Welch. The world is `experiments/warehouse_latent.py`, which returns the
true hidden state **only** so the experiment can measure alignment.

## Failures and fixes

**The runs test claimed hidden causes that were not there.** In the control
regime the action succeeds 95% of the time, so an 80-trial residual sequence
contains only about four failures. The normal approximation behind the runs
statistic is not valid that far into the tail, and the detector reported a
hidden cause in **7% of control seeds against a nominal 2.3%** — three times its
own stated false-positive rate, in the one regime built to have nothing to find.

The fix is a minimum count of the *minority* outcome, not of the sequence: below
five failures the answer is `UNDETERMINED`. False positives fell to 3%, and 17
of 30 control seeds now correctly report that they cannot tell rather than that
there is nothing there. Those are different claims and must not share a return
value — the same reason `UNKNOWN` is first-class in EDU-10.

**Design note, decided before running.** The three regimes were constructed to
have identical marginal success rates so that only time structure varies. Had B
and C differed in rate, a detector could separate them without doing anything
interesting, and the result would have measured the experiment's design rather
than the substrate's inference.
