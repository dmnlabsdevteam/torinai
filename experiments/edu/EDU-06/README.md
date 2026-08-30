# EDU-06 — Action-Schema Analogy Between Two Real Learned Domains

## Claim

Two independently acquired action models from unrelated domains instantiate the same relational and state-transition structure, discovered model-free.

## In plain terms

Torin learned how moving works in one made-up world from a teacher, and learned how
relocating works in a second, different world by actually doing it and watching what
happened. The two worlds share no vocabulary -- one says AT, PATH, OPEN; the other
says IN, LINK, READY.

We then described the first rule to Torin with all the names stripped out, and hid
the first world from it. It recognised the shape as the second world's rule --
including not just what has to be true beforehand, but what becomes true and what
stops being true afterwards.

It is worth being precise: at this point Torin RECOGNISED that two things it already
knew are the same shape. It had not yet used one to learn the other faster. That is
EDU-07.

## Result

kite17:move GROUNDED on archive:relocate at 1.00/0.60 with source domain excluded; all five relations including adds and removes; control NO_MATCH 0.00; model_calls 0.

## Method

Run from the repository root:

```
TORIN_MODEL_POLICY=strict_model_free ./venv_torin/bin/python3 experiments/edu/EDU-06/experiment.py
```

`manifest.json` in this folder is the frozen result. Every run records
`model_calls`; the substrate claims are only meaningful at zero.

## Failures encountered, and what was changed

- First run matched code_generation:extract_method at exactly 0.60 on `requires`
  alone, because adds/removes existed in only one domain. The tool projection
  describes what a tool NEEDS and OFFERS, never what it CHANGES.
- `archive:in` had been fused with `security:include_number` by the acronym matcher
  (initials i-n). A spatial relation and a password parameter became one node.
  MIN_ACRONYM_LEN was 2; raised to 3 and corroboration now required.
- The observation must exclude its own source domain, or the match measures identity
  rather than transfer.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result (absent where the experiment was superseded)
- `README.md` — this file
