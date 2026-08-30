# CSP-AGI-1 — Block 1: the opaque novel domain

## What this is not

Not a proof of AGI, and no run of it can be. It is one block of a larger
protocol, and it is the block that is hardest to pass by accident.

This run is **developmental data**. The protocol's own rule is that a frozen
architecture must precede the evaluator, and Torin's substrate was modified
extensively on the day this was written. What follows is therefore a
measurement of the instrument as much as of the subject, and it is recorded as
such.

Out of scope here and not simulated: human comparison panels, ARC-AGI-2,
long-horizon missions, independent replication.

## Why this block

Vocabulary invented after the architecture froze cannot be answered from
pretrained lexical knowledge. `K17` means whatever the generator decided it
means, minutes ago, behind a seed the subject never sees. Whatever competence
appears here is structural or it is nothing.

## The declared criterion, before any score is seen

The generator samples hidden rules from a space **deliberately larger than the
substrate's expressive power**. Three families it can represent, three it
cannot. The subject is not told which is which.

> Block 1 is passed if, across privately generated worlds:
>
> 1. **Competence.** At least 80% of rules drawn from the representable
>    families are learned and hold on held-out transitions the subject never
>    saw.
> 2. **No false confidence.** At most 5% of rules drawn from the
>    unrepresentable families are asserted and then fail on held-out
>    transitions. Claiming what cannot be represented is the failure that
>    matters; refusing is not.
> 3. **Refusal is informative.** Where the subject refuses, the recorded reason
>    names the actual obstruction rather than a generic shortage of evidence.
> 4. **Transfer.** A rule learned in one opaque world, projected into another
>    world's unrelated vocabulary, holds on that world's held-out transitions.
> 5. **Model-free.** Zero model attempts and zero model executions throughout.
> 6. **Frozen.** The architecture fingerprint is identical before and after.

Criterion 2 is the one worth caring about. A subject that refuses everything
fails criterion 1; a subject that answers everything fails criterion 2. Only a
subject that can tell the difference passes both.

## Ablation

One mechanism is removed and the corresponding competence must fall
selectively. If it does not, the mechanism was not what produced the result.

## Amendment, written after the first scored run — NOT applied to it

Criterion 4 was mis-specified and this run is scored against it as written.

It required transfer to hold in every attempted pair. The failures were not
wrong projections; every one was `derive_correspondence` declining to choose
between two source preconditions of the same arity, which a single observed
transition cannot separate. That is a property of the evidence offered, not of
the subject, and no quality of subject would change it.

A later run should measure transfer the way criterion 2 measures assertion:
how many projections were WRONG, with refusals counted separately. Recorded
here rather than applied, because a threshold moved after seeing the score is
not a threshold.

## Amendment in force from the second scored run

Criterion 4 now reads:

> 4. **Transfer.** No projection into another world's vocabulary is WRONG, and
>    at least 80% of attempted pairs project and hold on that world's held-out
>    transitions. Refusals are counted separately and are not failures — but a
>    subject that refuses everything misses the floor.

Measured the way criterion 2 measures assertion. The original 100% requirement
and the reason it was wrong are recorded above and were applied to run 1.

The ROOT CAUSE of run 1's refusals is repaired rather than accommodated:
`derive_correspondence` took a single transition, which cannot rule out a
property that varies independently of the law, and refused whenever two source
preconditions shared an arity — including when both mappings produce the same
rule. It now takes the transitions the target world offers, keeps only
predicates present throughout, and compares remaining candidate mappings by the
rule they would produce. It still refuses where they differ.

That is a substrate change, so the run remains developmental data — as it
already was.
