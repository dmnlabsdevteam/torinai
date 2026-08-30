# EDU-05 — Executed Action Becomes Root Evidence

## Claim

Work Torin actually does becomes evidence it can learn from.

## In plain terms

Torin moved a real file on a real disk, looked at the disk before and after, and
filed what changed as a genuine observation -- the same kind of evidence a teacher's
lesson would be.

Before this, every lesson Torin had ever had came from a teacher. Its own actions
taught it nothing, because the function for turning an action into a lesson had
never been connected to anything.

## Result

File moved HALL->LAB on disk; recorded as task_artifact; four concepts reached WELL_SUPPORTED; observation is its own root; model_calls 0.

## Method

Run from the repository root:

```
TORIN_MODEL_POLICY=strict_model_free ./venv_torin/bin/python3 experiments/edu/EDU-05/experiment.py
```

`manifest.json` in this folder is the frozen result. Every run records
`model_calls`; the substrate claims are only meaningful at zero.

## Failures encountered, and what was changed

- `training_example_from_runtime` existed with zero callers.
- The oracle must be the filesystem listing, never the tool's own return value: a
  rule confirmed by its invocation returning cleanly is confirmed by nothing.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result (absent where the experiment was superseded)
- `README.md` — this file
