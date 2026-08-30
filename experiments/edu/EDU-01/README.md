# EDU-01 — Discriminating Evidence -> Compositional Capability

## Claim

One counterexample that isolates a missing precondition converts an unusable action model into a compositional one.

## In plain terms

Torin had learned a rule for moving things that forgot to check where the thing
currently was. It could therefore "plan" to move an object from a room the object
was not in. We showed it a single lesson in which everything else was true but the
object was somewhere else, and it did not move. From that one lesson it repaired
the rule, and its score on a nine-problem exam went from 2 to 9 -- including
problems needing six moves chained together, which it had never been shown.

The important part is not the score. It is that when we took the lesson away
again, Torin did not go back to being confidently wrong: it went back to saying
"I cannot reach that", which is the honest answer.

## Result

2/9 -> 9/9 (+77.8pp). Ablation returns to 2/9 as UNREACHABLE, not INVALID.

## Retention — does the taught capability survive?

EDU-01's frozen result measured LEARNING. Retention is a separate claim, and
"persistent" is the first word of this architecture's description, so it has to
be evidence rather than an assumption.

`retention_probe.py` re-runs the frozen exam **without teaching anything**,
reading the repaired rule back out of the durable store in a fresh process. It
checks three things, in increasing strength: the rule still exists, its body is
byte-identical to the frozen manifest, and it still scores 9/9.

The third is the one that matters. A surviving rule row whose capability has
quietly gone is the fabricated-persistence failure this repository keeps
finding — the record is there, so something reports success, and nothing checks
that it still does anything.

| checkpoint | rule present | body unchanged | score | verdict |
|---|---|---|---|---|
| **T+6h** | yes | yes | **9/9** | PASS |
| T+24h | — | — | — | pending elapsed time |
| T+7d | — | — | — | pending elapsed time |

```
./venv_torin/bin/python3 experiments/edu/EDU-01/retention_probe.py
```

The log at `retention.json` is append-only and every entry records *measured*
elapsed hours. A checkpoint is only claimed once its nominal time has genuinely
passed — a probe run at T+5.8h reports itself as a pre-milestone probe and does
not get to call itself T+6h.

## Method

Run from the repository root:

```
TORIN_MODEL_POLICY=strict_model_free ./venv_torin/bin/python3 experiments/edu/EDU-01/experiment.py
```

`manifest.json` in this folder is the frozen result. Every run records
`model_calls`; the substrate claims are only meaningful at zero.

## Failures encountered, and what was changed

- The pre-lesson rule concluded AT(X,B) from a source it never checked, so the
  planner produced a one-step plan valid for the rule and impossible in the world.
- A `getattr(res,'plan',None) or getattr(res,'steps',None) or []` fallback made both
  conditions score 1/4 identically, manufacturing a false negative. The real field
  is `PlanningResult.steps`; the fallback was removed rather than extended.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result (absent where the experiment was superseded)
- `README.md` — this file
