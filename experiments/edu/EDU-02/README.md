# EDU-02 — Autonomous Runtime Knowledge Refutation

## Claim

Torin detects its own failure against the world and withdraws a validated rule's authority, unprompted.

## In plain terms

Torin believed a rule, made a plan from it, and acted on a real filesystem. The
world did not do what the rule predicted. Nothing told Torin the rule was wrong --
it worked that out from what actually happened, marked the rule refuted, and
stopped being allowed to use it.

This is the difference between a system that is corrected and a system that
notices.

## Result

VALIDATED -> REFUTED via RUNTIME_CONTRADICTION; transition and originating observation persist.

## Method

Run from the repository root:

```
TORIN_MODEL_POLICY=strict_model_free ./venv_torin/bin/python3 experiments/edu/EDU-02/experiment.py
```

`manifest.json` in this folder is the frozen result. Every run records
`model_calls`; the substrate claims are only meaningful at zero.

## Failures encountered, and what was changed

- Rule ids embedded a timestamp, so findings could never be retired and a 13.5h run
  closed zero of them.
- The world state had to be read by something other than the code that acted, or a
  rule would be 'confirmed' by its own invocation returning cleanly.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result (absent where the experiment was superseded)
- `README.md` — this file
