# EDU-03 — First transfer attempt (superseded)

## Claim

Superseded by EDU-04. Retained because the negative result is part of the record.

## In plain terms

An early attempt to show knowledge moving between domains. It failed for a real
reason: an induced rule could not become a concept at all, so there was nothing in
the graph for a match to find. Kept so the sequence of what we tried is visible.

## Result

NO_MATCH -- the operator had no representation in the graph being searched.

## Method

Run from the repository root:

```
TORIN_MODEL_POLICY=strict_model_free ./venv_torin/bin/python3 experiments/edu/EDU-03/experiment.py
```

`manifest.json` in this folder is the frozen result. Every run records
`model_calls`; the substrate claims are only meaningful at zero.

## Failures encountered, and what was changed

- `submit_learned_rule` ingested cleanly but produced zero concepts: the structured
  form it emitted was one no extractor read.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result (absent where the experiment was superseded)
- `README.md` — this file
