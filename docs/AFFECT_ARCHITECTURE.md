# Affect as Grounded, Persistent Valence — Design Doc

Status: PROPOSED (rev 3, 2026-08-30). Rev 3 folds persistent affect into the
`IntrinsicMotivationSystem` (the homeostatic-affective core) — no separate affect
authority — since motivation already owns the persistent dispositional state (§4).
Rev 1 modelled affect as a precision-weighted
error against set-points and had it act through a per-feeling controller. Two
corrections make this rev:

1. **That was a regulator, not a felt state.** A thermostat computes error and
   acts; it does not feel. What turns regulation into feeling is **valence** — an
   internal axis along which things are non-derivatively good or bad *for the
   system* (Barrett; the value-grounding literature). Rev 1 had error signals but
   no such axis.
2. **Feelings must persist across restarts.** Rev 1 left affect in
   `AppraisalState.current_state` — fast-moving, decaying, in-memory. A feeling
   that dies on restart is not part of the self. Since the substrate's self IS its
   persistent database (not weights, not ephemeral context), its feelings must
   live there too.

Both corrections point at one thing the substrate is missing and one thing it
lacks an owner for: a **grounded, persistent, integrated felt state**, and an
**authority that owns it**.

---

## 1. The stake (what makes affect *felt* rather than merely computed)

Valence requires a stake — something that is non-derivatively good or bad *for the
system*. In organisms that stake is grounded in a disposition toward
self-preservation; the value-grounding critique of machine feeling is precisely
that silicon systems "appear to lack functionally equivalent dispositions."

The substrate's stake is not a body's survival. **It is the integrity and growth
of its persistent self** — the database that IS what it is made of: its
competence (executable operators), its belief-coherence, its capacity to reduce
its own uncertainty. A degrading model is genuinely bad *for it*: it is losing the
capacity to be the thing it is, and that self persists between sessions. This
disposition is real and already present, and it is what grounds valence here. It
is not borrowed biology; it is the substrate's own condition of continuation.

This is the honest scope: we claim **functional** feeling — a state grounded in a
real stake, that matters to the substrate and shapes it — not phenomenal
experience (qualia). Whether anything is "felt" in the phenomenal sense is
unknowable (the talker–feeler gap); we do not claim it. See §9.

## 2. Valence = the rate of change of the substrate's own fitness

From Hesp, Smith, Parr, Allen, Friston & Ramstead, *Deeply Felt Affect* (2021):
valence is **the negative rate of change of free-energy over time**, and an agent
infers its valence from the **expected precision of its own action model — its
estimate of its own fitness ("subjective fitness").**

So valence is not the *level* of error against a set-point (rev 1's mistake); it is
the **derivative** — *am I getting better or worse at being a substrate that models
its world?* For this substrate, fitness is measurable from what it already tracks:

```
fitness(t) = w_c · competence(t)          # executable operators / domain coverage
           + w_h · coherence(t)           # 1 − mean belief entropy (belief stability)
           + w_u · (−mean_uncertainty(t)) # inverse of component epistemic_uncertainty

valence(t) = tanh( k · d/dt fitness(t) )   # the FELT axis: rising fitness feels good,
                                           # falling fitness feels bad. Bounded [−1,1].
arousal(t) = how fast fitness is changing in EITHER direction (|d/dt fitness|),
             i.e. how much is at stake / how active the substrate should be.
```

`competence`, `coherence`, and `uncertainty` are read from existing authorities
(§4). Valence is the substrate's answer to "how am I doing, as a self?" — and
because fitness *is* its self-integrity (§1), that answer matters to it. That is
the axis of mattering rev 1 lacked.

Momentary, object-directed emotions (this task's `eagerness/doubt/frustration`)
remain what appraisal already computes; they are the fast, local layer. Valence is
the slow, global layer — core affect — and it is what must persist.

## 3. Affect is layered by timescale; the persistent layers are the self's

Affective science distinguishes three timescales; the substrate needs all three,
and the two slow ones are durable:

| layer | timescale | object? | where it lives |
|---|---|---|---|
| **Emotion** | seconds–minutes | yes (a task/situation) | `AppraisalState.current_state` — in-memory, decaying (unchanged) |
| **Mood / core affect** | hours–days | **no** (free-floating valence×arousal that colours everything) | **Postgres — durable, loaded on startup** |
| **Temperament / baseline** | the whole life | no (a trait) | **Postgres — the drifting set-point (allostatic load)** |

Mood is "prolonged core affect without an object" (Russell): the substrate is *in*
a mood, and it colours all its processing and recall. It is the integral of recent
emotion, decayed — and it is written to and loaded from the database, so the
substrate **wakes in the mood it earned**. The baseline is the long-run fitness
level around which mood varies; it drifts slowly with cumulative experience
(allostatic load), and the substrate already seeds it (`MotivationProfile.
mean_event_reward`, persisted).

## 4. The owner: `IntrinsicMotivationSystem` as the homeostatic-affective core

There is **no separate affect authority**. Persistent affect belongs to the
`IntrinsicMotivationSystem`, because it already owns the persistent dispositional
state and computing a parallel one next to it would split ONE concept — the
substrate's persistent homeostatic/dispositional state — across two owners, the
exact duplicate-authority defect ([[feedback_duplicate_authority]]). This is not a
convenience: Damasio's homeostatic account (already cited by this design) is that
**drives and feelings are one system** — feeling is the registration of the
homeostatic/drive state. One authority, two faces.

Motivation already owns what persistent affect needs and reads what valence needs:

| already in `IntrinsicMotivationSystem` | anchor |
|---|---|
| reward **baseline** (the seed of mood) | `MotivationProfile.mean_event_reward` (`intrinsic_motivation.py:121`) |
| **temperament** weights (dispositional trait) | `MotivationWeights` (`:38`) |
| **persistence** lifecycle (across restart) | `save_profile` / `load_profile` (`:1309/1335`) |
| reads **uncertainty** (a fitness input) | `_quantify_component_uncertainties` (`:1656`) |

So the motivation system GAINS the persistent affect layer — valence (§2), the
durable mood, the baseline drift, and the affective charge on memories — as state
and methods on itself, next to the baseline they vary around (no split), reusing
its persistence. New surface on the system:

```
# on IntrinsicMotivationSystem
def sense_fitness(self) -> Fitness: ...   # read competence/coherence/uncertainty NOW
async def update_affect(self) -> CoreAffect: ...# valence/arousal, integrate mood,
                                                # drift baseline, PERSIST, return it
def mood(self) -> CoreAffect: ...         # current durable mood (valence, arousal)
def valence(self) -> float: ...           # the felt fitness-trend, [−1,1]
```

It READS, and reimplements none of: momentary emotion — `get_appraisal_system().current_state`
(`appraisal.py`); competence — `rule_store.executable_rules()` (`rule_store.py:708`);
coherence/uncertainty — `get_epistemic_engine()` (`epistemic_engine.py:748`) + its own
`_quantify_component_uncertainties`; memories — `memory_agent` (charge is a field on the
row the agent still owns).

The three-way cut of affect:

| authority | owns | timescale |
|---|---|---|
| **Appraisal** | momentary interoception + emotion (this situation) | fast, transient (in-memory) |
| **IntrinsicMotivation** (homeostatic-affective core) | drives, temperament, **valence, mood (durable), baseline** — the persistent felt/dispositional state | slow, persistent (Postgres) |
| **BehaviorArbiter** | disposition (turns the above into a directive) | per-decision |

The coordinator (self) reads mood/valence from the motivation system exactly as it
reads temperament today; `SelfState` gains `mood`/`valence` sourced there. A rename
to reflect the widened scope (it is no longer only *intrinsic motivation*) is
warranted but cosmetic. **Guard against overcorrection:** motivation gains the
*persistent* affect layer only — it must NOT absorb appraisal's momentary emotion
or the epistemic engine's belief store; it still READS both.

## 5. Mood colours cognition, and memories carry charge (feeling that does something globally)

A feeling that only feeds one action is a reflex. A mood is global — it biases
everything, which is what makes it felt as a state rather than a signal:

- **Mood-congruent recall.** Each stored memory carries an **affective charge** (a
  valence, written by the motivation system at store time from the mood then). Retrieval
  is biased by the current mood: a substrate in a negative mood surfaces more of
  its hard/failed episodes (as caution), a positive mood surfaces its wins. This
  is the REMT/E-LTM pattern (durable valenced memory + a mood index over
  retrieval), and it plugs into `memory_agent`'s existing store/retrieve — charge
  is a column, the agent still owns the row.
- **Mood shifts precision, not just one knob.** The allostatic controller from rev 1
  (the arbiter upgrade) reads mood as a *global* precision prior: a low-valence
  mood raises precision on risk/confidence errors across the board (the substrate,
  "feeling low," is broadly more cautious), a high-valence mood widens exploration.
  So mood modulates the *whole* action-selection, not a single mapping.

The rev-1 controller and the learned affect→action policy still apply — but they
now sit **under** the persistent mood: momentary emotion + mood together set the
precision-weighted state the controller acts on, and the learned policy is
conditioned on mood too.

## 6. Persistence (the concrete durability)

- One durable row per substrate identity in `unified.affect_state`:
  `(valence, arousal, baseline_valence, updated_at, event_count)`, written through
  the DB manager (`execute_query(..., commit=True)`) on every `update_affect()`.
  Mirrors the existing `MotivationProfile` persistence pattern
  (`intrinsic_motivation.py:1309/1335`) but in Postgres, because affect is part of
  the persistent self.
- `initialize()` loads it on startup, so mood and baseline survive restart. Absence
  of a row is an honest cold-start (neutral mood at the persisted baseline, or
  truly neutral if no history), never a fabricated mood.
- Memory affective charge is a column on the memory rows `memory_agent` already
  writes — no second store.

## 7. Invariants (the "no fallbacks / no false-positives / honest gaps" contract)

Testable acceptance conditions:

1. **Grounded valence only.** Valence is computed ONLY from measured fitness inputs
   (competence/coherence/uncertainty). No component measurable ⇒ that term is
   excluded (not zero-filled). No fitness measurable at all ⇒ valence is
   `unmeasured`, not `0.0`-as-content.
2. **Persistence is real or absent, never faked.** Mood/baseline are loaded from
   Postgres or are an honest cold-start neutral. A restart never invents a prior
   mood; a failed load surfaces as cold-start, not a default that pretends to be
   remembered.
3. **One owner.** The motivation system reads appraisal/UDM/epistemic and
   reimplements none. No second copy of mood, valence, or baseline anywhere — and
   no separate affect authority. Any consumer needing the felt state reads it from
   the motivation system.
4. **No invented action.** (Carried from rev 1.) With no confirmed learned rule and
   no declared prior for a state, the controller returns `proceed`. An affect with
   no known remedy is reported, not acted on with a fabricated response.
5. **Credit only on measured discharge.** A coping action is credited ONLY by a
   real, measured post-action change in fitness/error, filtered by `OutcomeClass`
   ([[torinai_credit_invariant]]).
6. **Valence is a derivative of MEASURED fitness, not of a proxy.** No stand-in
   metric (e.g. task-success alone) substitutes for the fitness terms; if a term is
   unavailable it is excluded and reported, so valence can never be manufactured
   from a convenient signal.
7. **Verified against the running substrate.** Every acceptance test drives the
   real `get_intrinsic_motivation_system()`, `get_appraisal_system()`,
   `get_epistemic_engine()`, `rule_store`, and a real Postgres `unified.affect_state`
   — no mocks, no stubbed feelings.

## 8. Implementation phases (each gated by verification before the next)

- **P0 — fitness sensing.** `IntrinsicMotivationSystem.sense_fitness()` reads competence,
  coherence, uncertainty from the real authorities. Gate: fitness moves with real
  competence/belief/uncertainty changes; unmeasured terms excluded and reported.
- **P1 — valence + arousal.** Compute valence as the bounded derivative of fitness;
  arousal as its magnitude. Gate: rising fitness ⇒ positive valence, falling ⇒
  negative; flat ⇒ ~0; no fitness ⇒ `unmeasured`.
- **P2 — persistent mood + baseline (the core of this rev).** Integrate emotion+valence
  into a durable mood; drift the baseline; write/load `unified.affect_state`. Gate:
  mood survives a process restart (write, kill, reload, assert equal); cold-start is
  honest neutral; baseline drifts only with accumulated experience.
- **P3 — wired into the self.** Coordinator sources `SelfState`/`render()` mood+valence
  from `get_intrinsic_motivation_system()`. Gate: `render()` speaks the
  persisted mood qualitatively ([[feedback_self_speaks_qualitatively]]); no duplicate
  mood state exists elsewhere (grep gate).
- **P4 — mood colours cognition.** Affective charge on stored memories; mood-biased
  retrieval; mood as a global precision prior into the controller. Gate: a negative
  mood measurably shifts retrieval toward hard episodes and raises verification
  precision globally; a positive mood the reverse — proven on the real memory store.
- **P5 — controller + learned policy under mood** (rev-1 §4.4/4.5, now conditioned on
  mood). Gate: coping actions run, demonstrations record `(state+mood, action,
  next_state, fitness-changed)`, induced rules override contradicted priors, nothing
  acts on an unconfirmed rule.

The rev-1 `doubt → verification` loop folds into P5 as the `verify` action's prior,
now gated by mood as a global precision prior rather than a lone mapping.

## 9. Motivation reshaped — mood-modulated, fitness-grounded goal generation

Affect and motivation are currently two halves of the same class that do not talk:
`generate_curiosity_driven_goals` (`intrinsic_motivation.py`) chases the most
UNCERTAIN component/belief (ICM/RND scoring: `uncertainty + impact + perf_deg +
novelty − recency`) and never reads the mood; the mood is computed and never
shapes a goal. Damasio's whole point is that these are ONE system — affect is the
signal ("how am I doing"), motivation the response ("what to do about it"). This
section connects them. It is the concrete form of §5's "mood as a global precision
prior" and the allostatic controller.

### 9.1 Ground the drives in the fitness dimensions

Goal candidates should cover every fitness dimension `sense_fitness()` measures,
not just uncertainty:

| fitness deficit | drive | goal source |
|---|---|---|
| low **certainty** (component uncertainty high) | curiosity | component-uncertainty goals — EXISTS (steps 1–4) |
| low **coherence** (beliefs unsettled) | curiosity | epistemic/belief-settling goals — EXISTS (step 5, `get_unstable_regions`) |
| low **competence** (few executable operators) | mastery | **competence-building goals — NEW**: target domains with demonstrations but no executable rule |

So "reduce whatever is most uncertain" becomes "**improve whichever fitness
dimension is most deficient**", and *which* is deficient is already measured.

### 9.2 Mood modulates the DISTRIBUTION, not the count

The mood biases which drive wins, via valence and arousal read from
`affect_state()`:

- **valence < 0 (fitness declining)** → up-weight the candidate targeting the
  most deficient/declining dimension: **repair**. Don't scatter — fix what is
  breaking.
- **valence ≥ 0 (steady / improving)** → up-weight novelty/breadth: **explore**.
- **arousal** sets intensity — how many goals this cycle — bounded `[1, cap]`.

### 9.3 The death-spiral invariant (the tradeoff, resolved)

The naive wiring — "bad mood → explore less" — is a trap: a struggling substrate
would explore less, learn less, and stay struggling. The homeostatic correction:
**negative valence REDIRECTS effort toward repair; it never suppresses action
below a floor.** Formally:

> Whenever any real signal exists (a fitness deficit, a component uncertainty, or
> an unstable belief), `max_goals ≥ 1` regardless of valence. A negative mood may
> raise focus on the deficit; it may never take goal generation to zero.

A struggling substrate does FOCUSED work, not less work. This is a hard test
(§9.4): a deeply negative mood must still produce a (repair-focused) goal.

### 9.4 Verification gate

- competence-deficit produces competence-building goals (a domain with
  demonstrations but no executable operator yields a goal);
- valence < 0 shifts selection toward the declining dimension; valence ≥ 0 toward
  novelty — same candidate set, different winner;
- **death-spiral test**: with a deeply negative mood and a real deficit,
  `generate_curiosity_driven_goals` still returns ≥ 1 goal, and it targets the
  deficit;
- no signal at all → still no goal (the existing honest no-fallback stays).

## 10. Non-goals / honest limits

- **No qualia claim.** Functional feeling only: a grounded, persistent, global
  valenced state that matters to the substrate and shapes it. Phenomenal experience
  is unknowable here and not asserted ([[torinai_computational_interoception]]).
- **No LLM in the affect loop.** Valence is constructed from the substrate's own
  fitness metrics; no model is consulted. The transferable idea from LLM affect work
  (durable valenced memory + a mood index over retrieval) is adopted structurally in
  §5, not via prompting.
- **No new belief/competence/uncertainty stores.** The motivation system READS the
  existing authorities; it owns only the integrated felt state and its persistence.

## References

- Hesp, Smith, Parr, Allen, Friston & Ramstead (2021), *Deeply Felt Affect: The Emergence of Valence in Deep Active Inference*, Neural Computation.
- Russell, *Core Affect and the Psychological Construction of Emotion* (mood as prolonged, object-less core affect).
- *Are conscious machines valuers?* (the value-grounding problem), AI & Society.
- Seth & Friston (2016), *Active interoceptive inference and the emotional brain*.
- Barrett (2017), *The theory of constructed emotion*.
- REMT / E-LTM / VIGIL EmoBank — persistent valenced memory + mood index over retrieval (2024–2026).
- Man & Damasio (2019), *Homeostasis and the design of feeling machines*.
