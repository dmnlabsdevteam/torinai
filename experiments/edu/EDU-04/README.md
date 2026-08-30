# EDU-04 — Structural Correspondence to an Unfamiliar Observation

## Claim

A learned rule can carry an observation whose elements are opaque, and the match depends on the generalization rather than on the demonstrations.

## In plain terms

We described a situation to Torin using placeholder names -- e1, e2, e3 -- so it
could not recognise anything by name. Only the shape was given. Torin matched it to
the movement rule it had learned.

To check this was not luck we did two things: we offered a differently-shaped
situation, which it correctly refused; and we deleted the part of its knowledge
that came from generalizing, leaving only what it had directly observed. The match
disappeared. So the match depended on what Torin had worked out, not on what it had
merely seen.

## Result

GROUNDED 1.00/0.60. Distractor NO_MATCH 0.50. Ablation of rule-derived edges NO_MATCH 0.50. model_calls 0.

## Method

Run from the repository root:

```
TORIN_MODEL_POLICY=strict_model_free ./venv_torin/bin/python3 experiments/edu/EDU-04/experiment.py
```

`manifest.json` in this folder is the frozen result. Every run records
`model_calls`; the substrate claims are only meaningful at zero.

## Failures encountered, and what was changed

- The observation was hand-authored. That is why this is NOT domain transfer and why
  EDU-06 exists.
- Support is computed on raw relation labels, so the observation and the structure
  share a role vocabulary. Stated in the manifest as a limit.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result (absent where the experiment was superseded)
- `README.md` — this file
