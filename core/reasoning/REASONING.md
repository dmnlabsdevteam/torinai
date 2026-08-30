# Reasoning in a Cognitive Substrate

**Dominion Labs — Cognitive Substrate Series, Paper I**

---

## Abstract

This paper describes how reasoning works in a cognitive substrate: a system that
derives conclusions from evidence it holds, rather than generating text that
resembles conclusions. It sets out eleven distinct kinds of inference, the order
in which they are attempted, how each earns the confidence it reports, and the
conditions under which the system declines to answer.

The central claim is narrow and testable. **A reasoning system should be able to
show why it believes something, and should be able to say when it cannot.** Most
contemporary systems can do neither: they produce an answer for every input and
a confidence that is asserted rather than computed. The architecture described
here separates those two failures and removes them independently.

Measurements are given for every claim. Where the system is limited, the limits
are stated in the same detail as the capabilities.

---

## 1. The problem this addresses

Two distinct failures are usually conflated.

**The first is fabrication.** A system that must produce an answer will produce
one whether or not it has grounds. There is no output that means *"nothing
follows from what I was given."* Absence of knowledge and presence of a wrong
answer are rendered identically.

**The second is unearned confidence.** A number attached to an answer is only
meaningful if something computed it. A system that reports its own certainty is
reporting a disposition, not a measurement — and downstream consumers cannot
tell the difference, because the number looks the same either way.

These compound. A fabricated answer carrying a self-assessed confidence is
indistinguishable, in a database, from a derived answer carrying a computed one.
Anything that later learns from that record learns from both equally.

The architecture below addresses each separately: conclusions must be derived,
and confidence must be computed by something other than the thing being
measured.

---

## 2. Reasoning is not one activity

Systems commonly treat reasoning as a single capability with a single quality
score. It is not. Different questions require structurally different inference,
and the difference determines what counts as evidence.

The substrate implements eleven kinds of classical inference. Each is a distinct
procedure with its own applicability conditions and its own basis for
confidence.

| Kind | The question it answers |
|---|---|
| **Deductive** | What must follow from these premises? |
| **Inductive** | What do these cases generalise to? |
| **Abductive** | What would best explain this observation? |
| **Analogical** | What is this structurally like? |
| **Causal** | What brings about what? |
| **Probabilistic** | What does this evidence make more likely? |
| **Fuzzy** | What holds by degree rather than sharply? |
| **Temporal** | What holds before, after, until? |
| **Spatial** | What contains, adjoins, lies within? |
| **Logical** | Is this satisfiable, provable as stated? |
| **Counterfactual** | What would have followed instead? |

The separation is not taxonomic tidiness. It has three consequences.

**Evidence differs by kind.** A deductive conclusion is supported by a
derivation. An inductive one is supported by a count of confirmations and
disconfirmations. A causal one is supported by the weakest link in a chain.
These are not comparable quantities, and a single "confidence" that averaged
them would mean nothing.

**Applicability differs by kind.** A question with no causal claim in it cannot
be answered causally. Each kind decides for itself whether the material it needs
is present, and declines when it is not. *No kind applied* and *a kind ran and
concluded nothing* are different outcomes, reported differently, because only
the first indicates that something else should be tried.

**Failure differs by kind.** Deduction fails by finding no derivation.
Induction fails by finding contradicting cases. Counterfactual reasoning fails
by finding the alternative was never reachable. Collapsing these into a low
score discards the reason.

---

## 3. The order of resort

When a question arrives, three things are tried in a fixed order. The order is
the architecture, not an optimisation.

### First: what can be proved

The system attempts to represent the question in its own formal terms. If it
succeeds, a solver decides the question and the answer carries a proof — a
sequence of steps that can be inspected and checked independently of the system
that produced it.

This is attempted for **every** request, without exception, and regardless of
what kind of processing the caller expected. Whether the system can settle a
question from its own rules is not a preference to be configured; it is the
first question, and its answer does not depend on what the caller guessed the
work would require.

### Second: what can be derived

Formal representation is narrow, and much of what a system is asked cannot be
expressed that way. That does not mean the next step is generation.

The eleven kinds of inference run here. Which are attempted is determined by the
question itself — the presence of causal, temporal, spatial or other markers —
or named explicitly by the caller. Every one is deterministic. None consults a
language model.

A conclusion reached here carries a derivation: the premises it rests on, the
steps taken, and the arithmetic that produced its confidence.

### Third: what can be proposed

Only if neither of the above settles the question is a language model consulted,
and then only for coverage — to translate an input the substrate could not read
into terms it can, or to suggest a candidate the substrate will then check.

**A model may propose. It may never attest.** Anything it produces is re-parsed;
anything malformed is discarded; every term is checked against the input, so an
invented premise degrades into a failure to represent rather than reaching the
solver disguised as legitimate. Proposals carry no confidence of their own,
contribute nothing to any quality metric, are ranked below every derived
conclusion, and are marked as proposals in every record that survives them.

The distinction is recorded permanently. A stored conclusion says whether it was
proved, derived, or proposed, and a system reading that record later can tell.

---

## 4. Confidence is computed, not declared

Each kind computes its confidence from something specific to it. What follows is
the basis in each case, and each is deliberately conservative.

**Deduction** takes it from the derivation. A conclusion that follows, follows;
the number reflects the strength of the premises it rests on, not an opinion
about the inference.

**Induction** uses Laplace's rule of succession. Given *s* supporting cases and
*f* contradicting ones, the posterior mean that the next case conforms is
`(s + 1) / (s + f + 2)` under a uniform prior over the underlying rate.

| evidence | confidence |
|---|---|
| 3 confirmations, no counterexample | 0.80 |
| 3 confirmations, 1 counterexample | 0.67 |
| 2 confirmations, 2 counterexamples | 0.50 |
| 9 confirmations, no counterexample | 0.91 |

This has the shape induction should have: never certain however many cases are
seen, never below one half, because a run of confirmations is evidence even when
short.

**Abduction** is capped. Structural plausibility is not evidence, so an
explanation that merely accounts for the observations cannot reach certainty from
structure alone. Within that ceiling it is scored on coverage — how much of what
was observed it explains — and on simplicity, following Occam: an explanation
resting on more conjuncts assumes more, and is scored lower for it.

**Causal** conclusions take the weakest link in the chain. A conclusion resting
on a 0.4 step is not a 0.9 conclusion because the other steps were strong. The
minimum is taken over the links actually traversed, not over every link touching
a node — a distinction that matters whenever one event participates in several
chains of differing strength.

**Probabilistic** conclusions report a posterior. Each premise enters as
evidence weighted by its own confidence and polarity; the posterior is the
answer, and scaling it further would be inventing a second opinion about a
number that already means exactly this.

**Fuzzy** conclusions carry two numbers, and the separation is the point.
*Degree* is how much the property holds; *confidence* is how sure we are of that
degree. "The disk is mostly full" is not an uncertain claim about a sharp fact —
it is a certain claim about a graded one. A system carrying only confidence must
record it as "probably full", which is a different and false statement: it says
the disk might be entirely full, and might not be full at all. Degrees combine
under the standard operators — conjunction takes the minimum, disjunction the
maximum — and linguistic hedges concentrate or dilate the degree without
touching the confidence.

**Counterfactual** conclusions include reachability. "Things would have gone
better" is worth little if the alternative could never have obtained, so the
conclusion states whether the alternative was reachable from the conditions that
actually held, and an unreachable alternative is reported as unreachable rather
than quietly scored as an improvement.

**Spatial** conclusions compose only the relations that actually compose.
Containment and vertical order are transitive; adjacency is not. That *a* is near
*b* and *b* is near *c* does not make *a* near *c*, and asserting it would be
inventing a fact. Knowing which relations compose is the substantive content of
a spatial reasoner.

**Logical** conclusions come from a solver, and a failed proof produces no
conclusion at all rather than a low-confidence one. **Not proved is not
disproved, and it is not a weak yes.** Emitting one would convert "the prover
could not settle this" into evidence.

---

## 5. Declining is a result

The system can return that it could not represent a question. This is a distinct
outcome with its own marker, separable in the record from a conclusion of low
confidence, and it is one of the more useful things the architecture provides.

Consider the alternative. A system that always answers has no way to signal the
boundary of its competence, so every consumer must treat every answer as
potentially fabricated, and no answer can be trusted more than the least
trustworthy. A system that can decline makes its confident answers mean
something.

Three states are kept apart, and every result carries enough metadata to
distinguish them without inspecting the answer text:

- **Settled** — proved, or derived by a kind of inference
- **Not entailed** — representable, and the conclusion does not follow
- **Not representable** — outside what the system can currently express

The third is a fact about the system's coverage, not about the world. It is
reported as such, and it is never converted into a claim about the question.

### A subtlety worth stating

Formal representation can be lossy. Rendering statements as opaque propositions
discards the relations between them: from *the chip is inside the socket* and
*the socket is inside the board*, a purely propositional reading gives three
unrelated symbols, and correctly reports that *the chip is inside the board* does
not follow. Correct about the propositions it was handed, and wrong about the
world, because containment composes and opaque symbols do not.

The system therefore distinguishes a **proof** from a **failure to derive under a
particular reading**. A proof is final. A failure to derive is a fact about the
reading, and the question is passed to the kinds of inference that can express
what the reading discarded — spatial reasoning, in that example, settles it in
one step. The original finding is retained and returned if nothing else settles
the question; it is deferred, never discarded.

This deferral applies only where the question indicates a kind of reasoning that
propositions cannot express. A sound refutation of a genuinely propositional
question stands.

---

## 6. Counterexamples

Induction deserves separate treatment, because the natural implementation is
wrong in a way that is difficult to see.

A system that groups similar cases together and generalises from each group will
absorb contradicting cases into the group it contradicts — they are, after all,
similar. The generalisation is then drawn over mixed evidence with every member
counted as support. A disconfirmation does not merely go unchecked; it moves the
confidence in the wrong direction.

Worse, an evenly divided group hides itself. If half the cases show one property
and half show its opposite, neither reaches the threshold to enter the
generalisation, and what remains is the shared subject — a statement that asserts
nothing and therefore cannot be contradicted. Contentless generalisations score
highest precisely because there is nothing in them to disagree with.

The substrate handles this by identifying the **contested term**: a property that
some members carry and others do not. Members on the minority side are counted as
counterexamples, and the confidence falls accordingly. Terms appearing in a single
case are instance labels, not contested properties — a group is not divided by its
members having different names.

The result is the ordering one would expect and which the naive implementation
inverts: evenly split evidence scores below three-to-one, which scores below
unanimous.

**A limit, stated plainly.** This counts the disconfirmations it was given. It
does not search for a disconfirming case that was never supplied. The confidence
is therefore an accurate summary of the evidence presented and an overstatement
of the evidence available, whenever the presentation is incomplete.

---

## 7. What was measured

Every figure below comes from the system as it runs, entered through its normal
interface with no internal state arranged by hand.

**Reasoning is fast.** A complete inference — representing the question, deciding
it, assembling the result with its proof — takes approximately **1.2 milliseconds**.
For scale, a single trivial database round trip in the same process takes 0.66 ms.
*The reasoning costs less than half of one database query.*

Search remains inexpensive at scale: inducing rules from 2,400 demonstrations
takes 55.8 ms; grounding 5,000 operators against 301 facts takes 56.9 ms; planning
over those operators takes 12.3 ms.

**Every kind runs model-free.** All eleven, entered from a plain question, with
zero language-model calls. Reported times range from 3.0 ms to 65 ms.

**Ordering holds under every entry.** The same settleable question produces the
same proof at the same confidence through all seven execution paths, with zero
model calls in each — including the path a caller would choose if they explicitly
wanted model inference. The substrate settles it first, so the model is not
reached.

**Conclusions persist and survive restart.** Verified across two separate process
runs: a conclusion derived in one is present in the next, tagged with the kind of
inference that produced it, alongside the rules it reasoned from. Working state —
the intermediate structures a query builds — is correctly *not* persisted; it is
the derivation, not knowledge, and is rebuilt each time. Repeated identical
reasoning accumulates nothing.

---

## 8. Limits

Stated at the same resolution as the capabilities, because a paper that reports
only what works is not describing a system.

**The reading problem is the binding constraint.** The substrate reasons well
over its own notation and cannot read the same content stated in ordinary
English. It will prove a syllogism whose premises arrive separately and decline
the identical content written as one sentence. This is the difference between a
system that reasons and a system one can talk to, and it is where the work is.

**Notation is exacting and fails quietly.** Distinctions in how a rule is written
determine whether it matches anything at all, and a rule that does not match
produces no conclusions rather than a report that it could not be read. Silence
is the wrong failure mode; a system should say when it did not understand its own
inputs.

**Induction does not seek counterexamples.** As above: it weighs what it is
given.

**Coverage is narrow and grows by teaching.** Every kind of inference above
operates on what the system has been taught to represent. The breadth comes from
accumulation, not from pre-training, which is the trade this architecture makes:
reliability within its coverage, at the cost of coverage that must be built.

Whether that trade is favourable depends on a question this paper does not
settle — whether the cost of teaching a new domain falls as more domains are
taught. If structures learned in one domain transfer to another, breadth compounds.
If they do not, it accumulates linearly. That measurement is the subject of a
later paper in this series.

---

## 9. Summary

The architecture makes four commitments, each of which is testable and each of
which was tested.

1. **Conclusions are derived, and the derivation is retained.** Every answer can
   show its premises, its steps, and the arithmetic behind its confidence.
2. **Confidence is computed by something other than the thing being measured.**
   No component reports its own certainty.
3. **The order of resort is fixed**: what can be proved, then what can be
   derived, then what can be proposed — and this holds for every request, not as
   a configurable preference.
4. **The system can decline**, and declining is distinguishable in the record
   from concluding.

None of these requires a language model, and the measurements confirm that none
of them uses one. What a model is genuinely useful for is coverage — reading an
input the substrate cannot yet read, and proposing candidates the substrate will
then check. It is a source of suggestions, never an authority over what is true.

---

*Dominion Labs — Cognitive Substrate Series*
*Paper I: Reasoning. Subsequent papers address memory and evidence, language and
representation, and the economics of taught coverage.*
