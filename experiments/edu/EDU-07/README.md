# EDU-07 — Functional Cross-Domain Transfer

## Claim

Prior knowledge from a structurally analogous source domain reduces the target-domain evidence required for validated competence, without reducing held-out performance.

## In plain terms

This is the one that matters. Torin took a rule it had learned in one world and used
it to learn a THIRD world faster.

After watching a single event in the new warehouse world, Torin proposed a complete
rule for it -- borrowed from the movement rule it already knew. Learning the same
rule from scratch took six observations. The proposal was only ever a proposal: it
was filed as a guess with no supporting evidence, and only became usable knowledge
after the warehouse itself confirmed it on five separate tests it had not been built
from.

We also checked it was really the analogy doing the work. We left everything in place
-- both worlds, all the machinery -- and cut only the link between them. The proposal
disappeared.

## Result

N_A=1 vs N_B=6 target observations to validated competence; held-out 5/5 in both; ablation removes the proposal; candidate enters with 0 evidence roots and is authorized only by target evidence; model_calls 0.

## Method

Run from the repository root:

```
TORIN_MODEL_POLICY=strict_model_free ./venv_torin/bin/python3 experiments/edu/EDU-07/experiment.py
```

`manifest.json` in this folder is the frozen result. Every run records
`model_calls`; the substrate claims are only meaningful at zero.

## Failures encountered, and what was changed

- The first held-out exam tested only one precondition, so a scratch rule missing two
  of them still scored 3/3 and 'equal performance' was true of an exam that could not
  fail it. Every precondition now has a case isolating it; scratch moved 4 -> 6.
- The evidence-free invariant is TEMPORAL. Checking it after validation asserts the
  opposite of what validation does.
- Fingerprint idempotency correctly returned a rule a previous run had validated, so
  the invariant was measured on a rule this run never projected. The experiment now
  resets its own target artifacts.

## Files

- `experiment.py` — the runnable experiment
- `manifest.json` — frozen result (absent where the experiment was superseded)
- `README.md` — this file
