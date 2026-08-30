# SESSION-01 — Does Proposal Quality Decay Across Repeated Model Calls?

*A systems diagnostic, not an EDU rung. It measures the behaviour of a plug-in
language model, not a capability of the substrate.*

## Question

EDU-08 left an unexplained observation: five model-teacher trials run inside one
process converged 1/5, while five run as separate processes converged 3/5, and
one in-process trial proposed nothing at all. The candidate causes — model
sampling, llama-server state, conversation state, KV-cache behaviour, request
construction, the wrapper — are not distinguishable from that data, and guessing
between them would attach a cause to a correlation.

This experiment does not explain the spread. It **localises** it.

## Result — no positional decay in any condition

Eight identical proposal calls per condition, everything else held constant
(prompt, temperature, structured-extraction path, world, version space, budget).

| condition | admitted | 1st half | 2nd half | decay |
|---|---|---|---|---|
| A persistent *(one process, one service instance)* | 24 | 3 | 3 | **0** |
| B fresh process *(new Python process per call)* | 24 | 3 | 3 | **0** |
| C fresh state *(one process, new service instance per call)* | 24 | 3 | 3 | **0** |

```
A persistent : [3, 3, 3, 3, 3, 3, 3, 3]
C fresh state: [3, 3, 3, 3, 3, 3, 3, 3]
B fresh proc : [3, 2, 4, 3, 3, 3, 3, 3]
```

Quality does not fall with call position under any isolation. There is no
session effect to chase: nothing that persists in the process, in the wrapper,
or in the server degrades the proposer over eight calls.

**Zero calls proposed nothing**, which is the specific EDU-08 symptom that
prompted this. It did not reproduce.

## What this does NOT establish

The metric is the *count* of admitted proposals per call. A and C returned a
perfectly constant 3 while B — the only condition with a fresh process — varied
(3, 2, 4, 3, …). A constant count is **not** evidence of identical proposals, and
this experiment did not record proposal content, so it cannot distinguish:

- in-process calls returning genuinely independent proposals that happen to
  admit three each time, from
- in-process calls returning the *same* proposal repeatedly

That difference matters for reading EDU-08. If repeated in-process calls are
correlated, then EDU-08's five in-process trials were not five independent
samples, and "1/5 versus 3/5" would be closer to one sample versus three — a
different explanation from sampling noise, and one this data cannot rule out.

Answering it requires recording and comparing proposal *content* across calls.
Stated here rather than left as an implied conclusion, because the experiment's
own summary line ("EDU-08's spread was sampling noise") claims more than the
counts support.

## Method

```
SESSION01_CALLS=8 ./venv_torin/bin/python3 experiments/systems/SESSION-01/experiment.py
```

Requires the Qwen3.6-35B llama-server on port 8099. Unlike everything on the EDU
ladder, this experiment **does** use a language model — measuring one is its
entire purpose.
