# EDU-08 — Teaching With and Without a Language Model

## Claim

A plug-in language model may propose *situations* and cannot inject *evidence*.
The world supplies every outcome, and the same `TeacherPolicy` governs both
cycles.

## In plain terms

Torin is meant to be able to use a language model as a helper or a teacher, and
we swap models in and out. So the question is not "is the model any good" — it
is "what damage can a model do if it is wrong, confident, or lying".

We ran the same lesson exactly twice. Once with a fixed list of situations to
try, and once with Qwen 3.6 (a 35-billion-parameter model running on this
machine) suggesting which situations to try. Both runs were policed by the same
rule: a lesson is only worth teaching if the possibilities Torin is still
weighing would *look different* afterwards. A lesson everything agrees on
teaches nothing, no matter how sensible it sounds.

The important part is what the model is *allowed* to say. It can suggest a
situation to set up. It cannot say what happens. Every suggestion it makes is
built for real in the warehouse and actually run, and whatever the disk does is
the lesson. So a model that invents a fact, or insists on an outcome that is
false, cannot put a single wrong thing into what Torin believes. The worst it
can do is waste a setup.

## Method

```
TORIN_MODEL_POLICY is NOT set to strict here -- the model cycle is
deliberately allowed to call the model. The substrate cycle is measured
alongside it and must reach the same answer.

./venv_torin/bin/python3 experiments/edu/EDU-08/experiment.py
```

Model: `Qwen3.6-35B-A3B-UD-Q5_K_XL` served locally at `127.0.0.1:8099`.

The version space is explicit — every rule with the TRANSFER action and some
subset of the three candidate preconditions, so "how much did this lesson
settle" is a count rather than a judgement.

## Measured result

| | substrate | model (Qwen3.6-35B-A3B) |
|---|---|---|
| lessons to converge | 3 | 3 when it converges |
| convergence | **5/5 deterministic** | **4/10 trials** |
| taught a wrong rule | never | **never** |
| exam when converged | 5/5 | 5/5 |

The two cycles are identical where the model succeeds — same separation scores
(16, 4, 1), same version-space collapse (8→4→2→1), same rule, same exam.

**The asymmetry is the finding.** Every model failure was the same shape: it ran
out of discriminating proposals and the cycle stopped with the version space
uncollapsed. Not once, across ten trials and every earlier failure mode
(truncated deliberation, `!`-negated facts, unbuildable routes), did it cause a
wrong rule to be learned. **Its failure mode is incompleteness, never
corruption** — which is structural, not luck: it proposes situations, the world
produces outcomes, and a proposal that separates nothing is refused before it
costs an observation.

### On this task the enumerator is strictly better

54 candidates a round is nothing, and exhaustive search converges every time.
Where the model earned its place is proposal efficiency: by step 3 only **2 of
54** enumerated situations still separated anything, and the model offered
**1** — one of those 2. That matters only in situation spaces where enumeration
is not available, which this task cannot demonstrate. Reported as a limit of
the benchmark, not of the model.

### Unexplained

Run in-process, five consecutive trials converged 1/5; run as five separate
processes, 3/5. One trial proposed nothing at all (`0/0`). Something about
repeated calls within a session degrades proposal quality. Recorded rather than
smoothed over; not yet diagnosed.

## What is measured

- lessons required to collapse the version space to one hypothesis
- whether that survivor passes an exam whose cases isolate each precondition
- model proposals: offered, unparseable, admitted, refused as non-separating
- **whether the model cycle reaches the same rule** — the invariant that matters
  more than either count

## Design points

- **The model proposes a situation; the world supplies the outcome.** The
  model's own `after` field is discarded.
- Malformed proposals are **declined, never repaired**. Guessing at half-parsed
  output is how a model's mistake acquires a teacher's authority.
- An unavailable model proposes **nothing**, rather than a fabricated
  curriculum under the same name.
- The policy has no input for confidence, authorship or argument. The same
  lesson from any proposer gets the same verdict.
