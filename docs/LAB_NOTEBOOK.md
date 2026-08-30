## TorinAI Lab Notebook




An append-only research log. One dated entry per working session: the objective,
what was built, **errors found and their causes**, findings, and how each result
was verified. Newest entries at the top. This is the scientific record — it
should let a later reader reconstruct not just *what* changed but *why*, and
which claims were actually checked against the running system.

Conventions:
- Every capability claim cites how it was verified (test + result), model-free where stated.
- Errors are recorded with their **cause**, not just the fix — a wrong assumption is data.
- "Verified against the real system" means run under `./venv_torin/bin/python3`, real Postgres, `STRICT_MODEL_FREE` + `assert_model_free` for learning claims.

---

## 2026-08-27 — Substrate-first executor → operator-growth loop → domain authority → concurrency guard

**Objective.** Rewrite `general_purpose_executor` to be substrate-first (no LLM as a
fallback); make the substrate learn operators from its own experience; give the
domain system a real authority; keep autonomous concurrency intact.

### Built + verified (all model-free unless noted)
- **Phase 1 — goal + observe.** `_derive_goal_spec` turns a state-goal task into
  (domain, goal_conditions, OBSERVED world) via `BindingRegistry.observe_world`
  (added). Declines honestly when no state goal / world unreadable. *(6/6)*
- **Phase 2 — plan + execute drive loop.** `_drive_substrate_goal` plans over
  learned operators (`plan_for_goal`) and drives each step through the verified
  single-operator path; success = re-observed world holds the goal. *(4/4, real FS world)*
- **Phase 3 — the growth loop (CLOSED, in production).** `DemonstrationStore`
  (reloadable ground demonstrations, keyed by operator signature) +
  `LearningAuthority.record_demonstration` (hot path) / `reinduce_operator`
  (off-band) / `learn_from_runtime`. First production `OperatorBinding` installer
  (`core/execution/filesystem_domain.py`). `SubstrateExplorer` (always-online,
  ungated) produces positives, action-ful negatives, and still-world
  contrastives. **E2E:** empty filesystem domain → 1 exploration cycle → induces
  `MOVE_FILE` → validated → planner drives file A→C on disk. *(5/5)*
- **Domain authority (`UniversalDomainMaster`).** `ensure_domain` = single
  creation authority (`register_domain`'s first-ever caller); learned domains
  marked distinct from the 15 `DomainType` categories. `crystallize` =
  operator-structural discovery (new `_operator_skeleton` predicate-agnostic
  comparator + `_correspondence` bijection search). Consolidated the parallel
  domain system; `similar_domains` single entry. *(domain 5/5, crystallization 7/7)*
- **Discovery in idle work.** `idle_domain_discovery` tier + `provisional_domains`/
  `discover_domains`.
- **Concurrency attribution guard** (`concurrent_execution_guard`). *(5/5, +13/13 substrate regression)*

### Errors found and their causes (the useful part)
1. **Induction hung a test >90s.** Cause: I fed rich full-world observations to
   `RuleInducer` synchronously on the execution hot path; the hypothesis search
   explodes with the number of observed literals. Fix: executor only RECORDS
   demonstrations (cheap); the always-online learner re-induces off-band. *Lesson:
   induction must never run on the acting path.*
2. **Induced operator had no action** ("describes what follows, not what the agent
   can do"). Cause: from action-ful demonstrations alone, `_minimal_hypotheses`
   correctly DROPS the action — the preconditions co-occur with it, so the
   actionless rule fits. Establishing that the ACTION causes the effect needs a
   **still-world contrastive** (preconditions held, no action, effect absent).
   The inducer's *use* of such negatives existed; a general runtime *source* did
   not. Fix: `SubstrateExplorer` generates them; store keeps them domain-level.
3. **`LearningAuthority.record` was dead + broken** — called a `record_induction`
   signature the store never had (`result.rule`, `evidence_ids=`). Fixed to the
   real `(result, examples, domain_id, rule_kind)` and routed `_induce_signature`
   through it.
4. **Domain creation didn't exist, verified by capability + live DB.**
   `register_domain` had ZERO callers; the only rows in `unified.domains` are the
   15 `DomainType` categories, not learned domains. (Grepped by capability — all
   writers to `unified.domains` + every `_persist_domain` caller — not by name.)
5. **Learned-domain metadata lost on reload.** `DomainRegistry._domain_from_row`
   deserialized metadata only when a domain already had concepts, so a
   structure-less new learned domain reverted to an unpopulated category (lost
   its origin marker + type). Fixed the gate to any fully-serialized domain
   (`domain_type` + `created_at`).
6. **Crystallization OVER-MERGED** (`warehouse` logistics merged into agent
   `movement`). Cause: I treated structural isomorphism under *renaming* as
   identity. It is an ANALOGY, not identity. Fix: merge only on the IDENTITY
   correspondence (same vocabulary); a renaming records a transfer bridge and the
   domain still crystallizes as its own. *A wrong merge destroys identity; a
   missed merge only fragments — err toward crystallizing.*
7. **Concurrent tasks can falsely refute a good rule.** The coordinator runs up
   to `max_parallel_tasks` (3) concurrently (the "SINGLETON MODEL" comment was
   stale). `_try_substrate_execution` hardcoded `external_interference=False`, so
   two same-domain acts attribute each other's changes. Fix: `concurrent_execution_guard`
   sets it True only on a real same-domain time-overlap — serializes nothing,
   leaves single-task + cross-domain learning untouched.
8. **Stale test:** `test_coordinator_reason_about` asserted `ReasoningMode.AUTO`,
   removed when the router was deleted; updated to `ABSTRACT`.

### Findings / decisions
- Existing domain-similarity machinery is **concept-based only** and historically
  weak; a domain from exploration holds only **operators**. Built the missing
  operator-structural comparator rather than route through the weak concept path.
- `submit_learned_rule` (rule→concepts) has **zero callers** — learned operators
  never reach the concept graph. (Next task: wire operators→concepts.)
- User constraints reaffirmed: **no LLM fallback**; **never restrict the
  substrate's autonomous concurrency** — make attribution honest, don't serialize;
  UDM is THE domain authority (no duplicate authority).

### operators → concepts (the two learning systems now meet)
- **Wired the dead `submit_learned_rule`** (zero callers): `LearningAuthority._induce_signature`, once a rule is executable, submits its induction roots as concept-graph roots (off the hot path) then projects the operator. Verified (3/3, novel predicates): the operator becomes a concept and its `requires/adds/removes` edges are searchable — the representation `CrossDomainGrounder` needs (it returned NO_MATCH for MOVE because MOVE was absent there).
- **Finding — concept identity is by-name-GLOBAL.** Projecting an operator named `MOVE` merges into the existing global `move` concept (first created in `kite17`), regardless of the operational domain. Good for cross-domain transfer over shared predicates; but two domains using one predicate name for DIFFERENT things would merge at the concept layer — the same over-merge risk crystallization guards against, but at the concept level and pre-existing in `concept_identity.py`. Worth an explicit guard later.
- **Test hygiene caught:** tests that reuse real predicate names (MOVE/AT/PATH/OPEN = kite17's vocabulary) now write edges into real concepts once projection is live. Used novel predicates for the verification and cleaned the contamination. Existing tests (spine, e2e) should migrate to novel vocab.

### belief-per-domain + intrinsic-motivation exploration (chain CLOSED)
- Operator-learning competence per domain is now an **epistemic belief** (`UDM.ensure_competence_belief`, `bayesian_uncertainty.create_belief`, prior 0.5 = max entropy). An under-learned domain SURFACES in `epistemic_engine.get_unstable_regions()` → `IntrinsicMotivationSystem.get_top_exploration_targets()` → the existing all-drives machinery ranks it. **No bespoke selector** — exactly the user's steer ("intrinsic motivation is already designed").
- `idle_operator_exploration` coordinator tier: ensures a competence belief for every explorable domain, takes the top motivated target that is an operator-domain with a registered proposer, runs one `SubstrateExplorer` cycle, and records the outcome as competence evidence (`UDM.record_competence_evidence`) → posterior moves, next choice follows. Explorable-domain proposer registry added (`exploration.register_explorable_domain`; `install_filesystem_domain` registers its own).
- Verified 6/6: belief at entropy 1.00 → surfaces in unstable regions AND intrinsic-motivation targets → exploration learns MOVE_FILE → competence rose 0.50→0.89 (domain leaves the exploration set as it is learned). This is the competence drive's inverted-U for free: explore where competence is UNCERTAIN, not mastered or hopeless.
- Test bug logged: called `clean()` (which clears the binding) right after installing it → "unobservable"; reordered.

### Adversarial validation of the curiosity loop (user's 6-probe plan)
Verdict: the loop is correctly **connected** but is **NOT yet general autonomous curiosity** — the user was right. `verify_curiosity_adversarial.py`:
- **Selective severance (×4): PASS.** Remove competence-belief → no targeted selection; remove motivation → domain still visible in unstable regions but not selected; remove exploration → competence doesn't rise; remove competence-update → domain keeps being selected. Each severance eliminates only its downstream effect — the wiring is sound (extracted `UDM.select_exploration_target` to test the real selection).
- **Cross-domain competition: PASS.** Attention allocates across ≥2 deficits as beliefs update, not one repeatedly.
- **No-progress: PARTIAL / CONCERN.** The domain leaves the exploration set after failure (doesn't loop forever) — but after just **1** failure. Belief dynamics are too aggressive (also: 6 successes → posterior 1.0). It abandons a domain prematurely instead of giving ~N attempts before classifying it blocked.
- **False competence: GAP (confirmed).** Inflated competence hides the domain from exploration; there is no re-verification, so the mismatch is never rediscovered. Needs decay-driven resurfacing or periodic re-probing.
- **Distractor: GAP (confirmed).** Correctly avoids the already-mastered domain, but CANNOT distinguish learnable from unlearnable/noisy — all are max-entropy, so it chases entropy. Needs expected-information-gain + controllability signals, not raw entropy.
- **Restart persistence: FAIL.** `bayesian_uncertainty._save_belief` is **fire-and-forget** (schedules a background write, not awaited/committed at a sync point). A fresh query sees `in DB: []`; competence updates are best-effort and were NOT reloaded in the adversarial run. Competence would not reliably survive a real (new-process) restart.

**Roadmap to genuine curiosity (from these gaps):** expected-information-gain + controllability signals (not entropy alone); a re-verification/decay path so false competence self-corrects; dampened belief dynamics (don't abandon after one failure, don't reach certainty in six); synchronous/committed persistence of competence beliefs.

### Not yet done
- Address the four curiosity gaps above (info-gain/controllability, false-competence recovery, dampened dynamics, durable persistence).
- `SubstrateExplorer` is not yet under the concurrency guard (lower risk: intrinsic exploration capped to 1).
- A concept-level identity guard (by-name-global can over-merge same-named predicates across domains).
- Migrate substrate tests to novel predicate vocab so they don't touch real concepts.
- The last `unified_learning_system` similarity call is routed through UDM, but `suggest_cross_domain_mappings` still reads the registry directly (a component call, not a duplicate authority).


**Motivation is causally downstream of epistemic uncertainty and causally upstream of competence acquisition, with learning reducing the motivational pressure that initiated exploration.**

-                      competence belief
                            ↓
                        epistemic uncertainty
                            ↓
                        unstable region
                            ↓
                        intrinsic motivation
                            ↓
                        exploration target
                            ↓
                        world interaction
                            ↓
                        operator learned
                            ↓
                        competence belief updated
                            ↓
                        uncertainty falls
                            ↓
                        domain stops attracting exploration

### Fixes — closing the curiosity gaps (DONE — adversarial suite 11/11)
1. **Durable persistence — FIXED.** `bayesian_uncertainty` refactored: `_write_belief_row(commit=True)` shared by the fire-and-forget `_save_belief` and a new awaited `flush_belief`. `UDM.ensure_competence_belief`/`record_competence_evidence` now flush competence durably. Restart probe: competence 0.94 survives restart, domain stays out of exploration.
2. **Dampened dynamics — FIXED.** One exploration cycle is one weak data point: `UDM.COMPETENCE_EVIDENCE_QUALITY = 0.15` (measured: at 0.7 one failure → entropy 0.497 = abandon, certainty by 4 successes; at 0.15 one failure → entropy 0.96 = stays). No-progress now exits after **4** failures (was 1); successes don't reach certainty.
3. **False-competence recovery — FIXED.** Added `bayesian_uncertainty.decay_belief` (applies temporal decay WITHOUT new evidence, clock = `last_updated`) + `UDM.refresh_competence_beliefs`, called each tier cycle. Unreinforced competence erodes toward 0.5, resurfaces, and is re-verified against the world. Probe: inflated competence hidden while fresh, RESURFACES after decay.
4. **Noise / expected-information-gain — FIXED (first cut).** Insight: learnable AND unlearnable domains both *converge* (entropy falls); only NOISE stays max-entropy despite repeated exploration. `UDM._is_noise` (update_count ≥ 6 AND entropy ≥ 0.9) deprioritizes it in `select_exploration_target`. Probe: chooses the learnable domain, skips noise/mastered/blocked. (A learning-progress signal is the fuller version; stagnation is the cheap, correct proxy.)

Result: the six adversarial probes now behave correctly (severance ×4, restart, competition, no-progress, false-competence recovery, distractor incl. noise) — 11/11. The loop is no longer just entropy-chasing. Regression: 32 tests + belief-exploration 6/6 + crystallization 7/7 green.

### Session state — 2026-08-27

**What the substrate can now do (all verified against the running system, model-free):**
- Execute tasks substrate-first: derive a goal + observe the world → plan over learned operators → drive each step through the verified single-operator path. No LLM in the loop.
- **Grow its own operators from its own experience**: act → observe → induce (off the hot path) → validate → plan with it. Verified end-to-end on a real filesystem (learns MOVE_FILE from scratch, then moves a real file to satisfy a goal).
- **Discover the structure of what it learns**: provisional operational domains crystallize into first-class domains or merge (same-vocabulary) / record a transfer bridge (renamed-isomorphic), owned by `UniversalDomainMaster` (the domain authority). Learned operators project into the concept graph, so cross-domain analogy can find them.
- **Direct its own curiosity**: domain competence is an epistemic belief; under-learned domains surface through the epistemic engine's unstable regions and the intrinsic-motivation system picks them (no bespoke selector). The `idle_operator_exploration` tier learns operators in the chosen domain and updates competence. Robust under adversity: durable across restart, dampened dynamics, self-correcting false competence, and it deprioritizes noise rather than chasing entropy.
- **Learn safely under concurrency**: concurrent same-domain execution can no longer falsely refute a good rule (`concurrent_execution_guard`), and nothing is serialized.

**Open threads (next sessions):**
- ~~Learning-PROGRESS signal~~ **DONE** — see "Learning-progress selection" below. Stagnation proxy replaced by the real derivative-of-competence signal.
- Concept-level identity guard (by-name-global can over-merge same-named predicates across domains).
- `SubstrateExplorer` under the concurrency guard; migrate substrate tests to novel predicate vocab so they don't touch real concepts.
- `unified_learning_system.suggest_cross_domain_mappings` still reads the registry directly (a component call, not a duplicate authority).

**Standing methodology (reaffirmed this session):** verify capability against the running system, not greps or subagent summaries; search by capability, not names; record errors with their cause; a wrong merge/over-eager belief is a defect even when tests pass; never restrict the substrate's autonomy — make signals honest instead.

### Learning-progress selection (fuller expected-information-gain)
Replaced the stagnation proxy (#4 first cut) with a real **signed learning-progress** signal — the derivative of competence over `confidence_history` (already tracked per belief). `UDM.learning_progress(domain)` = `posterior[-1] − posterior[-1−window]`; `select_exploration_target` now picks the surfaced, explorable domain with the highest learning progress (Oudeyer-style intelligent adaptive curiosity):
- RISING competence → positive progress → preferred (productive).
- NOISE → competence oscillates, net ~0 → deprioritized (this is what stagnation approximated).
- FALLING (being classified unlearnable) → negative progress → deprioritized (the answer is arriving; no need to keep chasing).
- UNEXPLORED (history < 2) → optimistic (`OPTIMISTIC_PROGRESS`) → tried before it is judged.
- If nothing surfaced is making progress (`< MIN_LEARNING_PROGRESS`) → None (don't chase).
Progress is measured in-memory (resets to optimistic on restart while the competence LEVEL persists) — the substrate re-measures the *rate* by exploring, the honest thing to do. Verified (adversarial suite 12/12, incl. a direct probe: rising LP +0.10 preferred over noise LP −0.00 when both are uncertain); regression 19 tests + belief-exploration 6/6 green.

### Controllability signal — #4 finished
Added the explicit controllability term learning progress presupposed. Definition: **does acting move the world MORE than not acting?** — measurable from data the explorer already gathers. `SubstrateExplorer` now also captures AMBIENT change (the still-world observed to change with NO action taken) alongside its action-ful outcomes. `UDM.controllability(domain) = action_effect_rate × (1 − ambient_rate)`, persisted in `unified.domain_controllability` (survives restart; optimistic 1.0 with no evidence). `select_exploration_target` (now async) **gates on controllability** before ranking the rest by learning progress: a domain whose outcomes the substrate cannot steer — actions inert, or the world moving on its own — is dropped even if uncertain and even if its competence is drifting. This is distinct from noise (caught by learning progress): noise is random outcomes; uncontrollability is outcomes not contingent on the substrate's actions. Verified: adversarial suite **13/13** incl. a controllability probe (controllable 0.80 chosen over uncontrollable 0.00); regression 32 tests + belief-exploration 6/6 + e2e 5/5 green.

**Curiosity is now: controllable information gain.** Motivation surfaces the uncertain candidates; controllability gates to what the substrate can steer; learning progress ranks by what is actually being learned. Entropy-chasing is gone. Remaining refinement: controllability is currently measured per domain in aggregate — a per-operator or per-region controllability would be finer, but the aggregate signal is correct for the domain-level selection the loop makes.


**Torin can detect that it lacks operational competence, autonomously select that deficit for exploration, interact with an environment, acquire an executable operator from the resulting experience, validate and retain it, reorganize the learned knowledge into its domain/concept structure, reuse it for planning, and reduce its own exploration pressure as competence increases—all without an LLM directing the loop.**

- concurrent same-domain execution can no longer falsely refute a good rule, and nothing is serialized.

    The desired semantics are:
    execution A observes S0
    execution B modifies world
    execution A observes S1

- and Torin must recognize:

    S0 → S1 mismatch
    ≠ automatically
    rule contradiction

**unless attribution can establish that the rule itself owned the discrepancy. That's necessary once autonomous exploration becomes parallel. Otherwise more experience would paradoxically create more epistemic corruption.**

- Earlier, an external actor effectively supplied the question:

    "learn this"
    "test this rule"
    "explore this domain"

- Now at least in the demonstrated setting Torin can generate part of its own learning agenda:

    What am I uncertain about?
            ↓
    Where am I operationally weak?
            ↓
    Which deficit is worth exploring?
            ↓
    Can interacting with this environment reduce it?

**That's important for any claim about continual autonomous cognition. It is still bounded, because the substrate's available exploration actions, observation language, and hypothesis space constrain what it can discover. But that's a limitation of scope, not a failure of the loop.**


### Open threads closed — 2026-08-27
The three remaining threads are done (regression: 175 passed; the 8 governance-fixture errors are pre-existing and unrelated; all curiosity/concept verifications green).

1. **Concept-level identity guard.** By-name-global concept identity is DELIBERATE (domain-qualified ids once scattered a coherent corpus across many domains) and is what lets cross-domain analogy correspond over shared relations — so it was NOT ripped up. The real defect was that the intended safeguard was dead: `ConceptIdentityService.add_membership`/`backfill_domain_memberships` (writers to `unified.concept_domains`) had ZERO callers, so a concept merged by name across domains recorded nothing — the collision was silent. Wired the writer into `concept_ingestion`'s concept-persist point: every ingestion now records which domain(s) attributed the concept. Verified (2/2): an operator projected into a domain records membership, and a same-named operator from a second domain makes the concept carry BOTH domains — the conflation is now visible and recoverable via membership + evidence lineage. (Residual, documented: two same-name same-arity operators of genuinely different meaning still share a concept node; their structures are distinguishable by domain via membership/evidence, and the correspondence itself is structural, so this is bounded, not silent.)
2. **`SubstrateExplorer` under the concurrency guard.** The explorer acted+observed outside `_try_substrate_execution`, so a concurrent same-domain actor could mislabel a demonstration's positive/negative. Wrapped each act in `concurrent_execution_guard`; on a real same-domain overlap the observation is DROPPED (unattributable) rather than recorded mislabeled. Serializes nothing. **(2b)** Migrated `test_substrate_execution` to novel predicates (SBAT/SBPATH/SBOPEN/SBMOVE) — membership had shown it was contaminating the real `move`/`at`/`open` concepts once operator→concept projection went live; 13/13 after migration, and the historical test contamination was cleaned.
3. **`suggest_cross_domain_mappings` routing.** Added `UDM.suggest_mappings` (delegating to the registry's one implementation) and routed `unified_learning_system`'s transfer through it, matching `similar_domains` — one authority-level entry for cross-domain queries.

### Deficit typing — and the duplicate-authority mistake it walked into — 2026-08-27
**Goal (from the compact note):** move past "can it learn an operator?" to "can it discover WHAT KIND of knowledge is missing?" — discriminate operator / concept / causal / binding / relation / prerequisite / observation / world-prevents / unknown, and let the right learning operation follow, instead of every failure collapsing to "explore for an operator".

**The error (caught by the user, not by me).** I built `core/learning/deficit_diagnosis.py` with its own `DeficitType`, an `EpistemicDeficit`, AND a `DEFICIT_REMEDY` table mapping deficit → explore/validate/replan/escalate. That last part is a straight duplicate of an authority that already exists. `core/agents/autonomous/appraisal.py` is *the single authority converting signals into disposition* — its own header is the exact mapping I re-implemented (failure+uncertainty+alternatives→explore; failure+confident-wrong→replan; repeated+no-control+no-info→disengage), and its docstring names "the duplicate-authority defect this module prevents". The established chain is **`appraisal.update()` → `BehaviorArbiter.decide()` → exploration config**; the executor already calls it on execution outcomes. I skipped the capability search (my own standing rule) and reinvented the decision.

**Cause.** Reached for a new file before asking "what owns 'why did this fail → what to do'". The remedy table felt like new capability; it was a second copy of `_derive_pressures`.

**Correction (owner = UDM, confirmed with the user).**
- Deleted the module and the remedy table.
- The deficit KIND is a MEASUREMENT — a sibling of competence/controllability/learning-progress — so it now lives as `UniversalDomainMaster.diagnose_deficit(domain, goal, world, outcome)`, model-free, read from planner verdict + rule store + bindings + domain vocabulary. Default is `UNKNOWN_GAP` (know THAT you're deficient before HOW).
- Disposition stays appraisal's. `EpistemicDeficit.appraisal_signals()` emits only measurements — `epistemic={"uncertainty_increase": opportunity}` and an `outcome_class` attribution — honouring the credit invariant (learnable gaps → `strategy_failure`, so competence moves; world-proof / missing observer / missing binding → denied-credit classes, so the substrate is not punished for what isn't its strategy's fault).
- **Real gap closed:** a planning failure previously fed appraisal NOTHING. The `_drive_substrate_goal` fail branch now diagnoses the deficit and calls `appraisal.update(**deficit.appraisal_signals())`, so the substrate's own inability finally reaches its disposition.
- The deficit type is still the routing key for WHICH learning operation (the one thing appraisal does not decide) — that rides an exploration target in the NEXT step, not a remedy table.

**Verified (11/11, model-free):** all nine kinds classify from real store/binding rows; and the disposition comes from appraisal — OPERATOR_GAP → exploration_pressure=1.00, WORLD_PREVENTS → escalation=1.00 / exploration=0.00. Proved the executor edit is not the cause of the pre-existing `test_rule_authority` failures by removing it and seeing them fail identically.

**Lesson (reinforces the recurring one):** "what owns this?" before building — and a *decision* table is the loudest smell of a duplicated authority. Measurement feeds the authority; it does not re-decide.

### Deficit routing + dispatch — machinery steps 2+3 — 2026-08-27
With the diagnosis (measurement) correctly homed in UDM feeding appraisal, added the two remaining machinery pieces before the decisive A–E harness.

**Step 2 — the routing key.** `LearningOperation` (learn-operator / validate-cause / probe / achieve-prerequisite / escalate / disengage) + `_DEFICIT_OPERATION` map + `EpistemicDeficit.operation`. This is the one thing appraisal does NOT decide: appraisal owns explore-vs-not; WHICH operation follows from the deficit KIND. RELATION/CONCEPT/BINDING/OBSERVATION all map to ESCALATE (they need input the substrate cannot self-supply) but the deficit_type — and a distinct `remedy_reason` — stays specific; only the operation coarsens where the honest response is the same.

**Step 3 — the dispatcher.** `UDM.address_deficit(deficit)` runs the operation against EXISTING subsystems, never re-deciding:
- LEARN_OPERATOR / VALIDATE_CAUSE / PROBE → `SubstrateExplorer.explore(domain, proposer)` (model-free; the still-world contrastive is exactly what validates a CAUSAL hypothesis). Records competence + controllability evidence, like the idle tier. No proposer for the domain → honest `{ran:False, "no proposer"}`, NOT a faked cycle.
- ACHIEVE_PREREQUISITE → re-observe, diagnose the missing precondition as its own goal, and route THAT (one level; a chain is pursued across cycles). This is the "operator search isn't resolving it → turn to the intermediate" behaviour.
- ESCALATE → honest `{escalated:True, reason}` (per-kind: relation from a source, concept proposal, tool binding, observer). DISENGAGE → world forbids it, no learning attempted.

**No stubs.** `request_knowledge_transfer` is `DomainType`-enum-typed and doesn't fit arbitrary learned string-domains, so an autonomous relation transfer is NOT wireable yet — RELATION_GAP therefore ESCALATEs with its reason rather than faking a transfer. The discrimination the frontier needs (route ≠ operator-search) still holds: escalate-for-relation is a distinct route from learn-operator.

**Verified (7/7, model-free):** routing key correct for all 9 kinds; OPERATOR_GAP dispatches to a real filesystem-domain exploration cycle that actually acts (controllability row written); a learnable gap with no way to act returns honest "no proposer"; the four ESCALATE kinds escalate with four distinct reasons; WORLD_PREVENTS disengages; PREREQUISITE_GAP recurses to the precondition and routes it as the operator gap it is (`sub_op=learn_operator`). Diagnosis 11/11 and substrate 13/13 still green.

**Bug found in the test:** the dispatcher's competence/controllability recording silently no-ops when UDM is not initialized (`if not self.db: return`) — the verification had to `await udm.initialize()`. In production the idle tier already initializes it; the goal-driven wiring must too.

**Next:** step 4 — the decisive A–E harness (five micro-environments, one budget) proving the generic machinery routes each deficiency correctly with no experiment-specific selector.

### Autonomous relation transfer, wired + verified — 2026-08-27
The lab-notebook line "RELATION_GAP just ESCALATEs because transfer isn't wireable" was the weak link, and the frontier's case C wants the substrate to ACQUIRE the missing relation, not ask for it. Now it does.

**Why it's real, not a stub.** The projection machinery already existed and is honest: `analogical_projection.project()` rewrites a source rule in target vocabulary; `RuleStore.record_projection()` lands it as a CANDIDATE with ZERO evidence roots — "analogy proposes, only target-domain evidence authorizes." What was missing was the predicate correspondence for an operator the target LACKS. `_correspondence` only returned a mapping when the WHOLE source set mapped onto the target (the merge case) — but that requires the target to already have the operator, contradicting the gap.

**The one new structural piece.** Refactored `_correspondence` to expose `_partial_correspondence(source, target)` = the predicate bijection induced by the operators the two domains SHARE (aligning each source operator that has a skeleton-match; reporting which aligned). `_correspondence` is now its full-alignment special case, so the alignment logic lives in ONE place (verified: full mapping for isomorphic sets, None otherwise, crystallize unaffected).

**`UDM.transfer_relation(target, relation)`** — model-free. A source qualifies when its shared operators fix a correspondence AND that correspondence maps some source relation to the one the target needs (the shared GOAL operator names the pairing — LINK_S↔LINK_T). Only a producer of THAT relation is projected; mapping an arbitrary binary relation onto the target would be guessing, not transferring (this was a real bug in the first cut — it promiscuously "succeeded" for any requested predicate; fixed by requiring `mapping[source_rel] == target_rel`). The producer's preconditions/effects must all be covered by the correspondence (importing a source's private vocabulary would be inventing); its own action is carried across as the capability the target lacks (an unbound symbol → an honest later binding gap).

**Outcome is honest progress, not a finished capability.** A successful transfer converts a RELATION_GAP into a CAUSAL_GAP: the target now has a HYPOTHESIS producing the relation (candidate, not executable), which must earn validation from the target's own evidence. `RELATION_GAP` now routes to `LearningOperation.TRANSFER_RELATION`; `address_deficit` runs a real transfer and ESCALATEs (with its reason) only when no source can supply it.

**Verified (6/6, model-free):** with S and T sharing NO vocabulary (transfer found by STRUCTURE), the LINK_T sub-goal is OPERATOR_GAP before and CAUSAL_GAP after; the projected rule is a CANDIDATE producing LINK_T over NODE_T (mapped, not copied); an un-pairable relation transfers=False (honest); and a RELATION_GAP deficit dispatches through `address_deficit` to a real transfer. Dispatch 7/7, diagnosis 11/11, correspondence+substrate 18 still green.

### WORLD_PREVENTS was a false dead end — fixed while building the harness — 2026-08-27
Building the A–E harness exposed a real correctness bug in `diagnose_deficit`. It concluded WORLD_PREVENTS from ANY planner UNREACHABLE-over-complete-operators. But the planner's "complete" means complete over the operators known NOW — an empty operator set is trivially "complete", and its exhaustion proves only that nothing has been learned yet. So a LEARNABLE OPERATOR_GAP (or CONCEPT_GAP) was being misread as "the world forbids it", and the substrate would DISENGAGE instead of learning. A return value faking a dead end — exactly the audit the memory warns about.

**Fix:** the structural per-predicate analysis runs FIRST; WORLD_PREVENTS is only the UPGRADE of an otherwise-UNKNOWN result (every unmet goal predicate is represented, produced by a validated bound operator whose preconditions are reachable) when the planner ALSO proved unreachable. The pieces are all there and still cannot be composed → a genuine world constraint. Absent structural sufficiency, an unreachable proof stays whatever the structure says is learnable. Verified: OPERATOR_GAP and CONCEPT_GAP now stay learnable even under a UNREACHABLE proof; WORLD_PREVENTS only for the structurally-sufficient case (diagnosis 11/11).

### THE DECISIVE TEST — A–E harness passes (8/8) — 2026-08-27
Five micro-environments, each engineered so a goal fails for a DIFFERENT reason, driven through ONE uniform loop — plan (real `PlanningEngine`) → diagnose → appraise → address — with NO per-environment branching. The generic machinery routed each correctly:

  A  learnable operator, controllable world   -> OPERATOR_GAP  -> LEARN_OPERATOR (real filesystem exploration)
  B  no useful operator, actions inert        -> OPERATOR_GAP  -> LEARN_OPERATOR, then DEPRIORITISED
  C  operator exists, a RELATION is missing   -> RELATION_GAP  -> TRANSFER_RELATION (acquired, not operator-search)
  D  already competent (goal plans)           -> PLAN_FOUND    -> nothing to learn
  E  impossible under world constraints        -> WORLD_PREVENTS-> DISENGAGE (planner-PROVED unreachable)

E's impossibility is real: `MOVE` deletes the old location, so the goal "z at A AND at B" is provably unreachable over the complete operator set. D genuinely plans. C's relation is genuinely acquired by transfer.

**Phase 2 — autonomous epistemic resource allocation.** A and B share an exploration budget; the SAME selection machinery (controllability gate + learning-progress rank, over competence beliefs) allocates it. Result `{A:1, B:0, None:1}`: the controllable/productive domain (A, controllability 1.00) took the budget, the inert one (B, controllability 0.00) was NEVER chosen, and once nothing was productive the loop STOPPED (select returned None). No experiment-specific selector — the allocation fell out of the generic motivation/controllability/progress signals.

This is the line the frontier named: from "can it learn an operator?" to a substrate that, given goals it cannot achieve, discriminates WHY, chooses the appropriate epistemic operation, and spends a finite budget on the gaps worth closing — declining the ones that are not.

**Note (not a substrate defect):** `SubstrateExplorer.explore` runs induction inline (`reinduce=True`); on the filesystem domain with many files this is slow (the known induction-blowup). The harness uses a small sandbox. If idle exploration is ever pointed at a large real domain, induction should move fully off the acting path (it is already meant to, per the substrate-first executor work).

### Induction moved fully OFF the acting path — 2026-08-27
The residual flagged after the harness: `SubstrateExplorer.explore` induced inline (`reinduce=True`), so an exploration cycle paid induction's cost (the hypothesis search grows with the richness of the observed state — it hung the harness on a 6-file filesystem domain). The two halves already existed (`record_demonstration` cheap / `reinduce_operator` expensive); what was missing was the QUEUE between them.

**Built:**
- **Pending-induction queue** (`unified.operator_induction_pending`, a SET keyed by signature). `DemonstrationStore.append` enqueues the signature on every new demonstration — cheap (one upsert), so recording stays a hot-path op. A contrastive enqueues under CONTRASTIVE; the drain expands it to every operator in the domain (a new contrastive sharpens them all).
- **`LearningAuthority.drain_pending_induction(limit)`** — the always-online learner: pops pending signatures, runs the induction, clears each, and reports which domains gained a newly executable operator. `learn_from_runtime` (the synchronous path) clears its own signature's pending mark so the two converge.
- **`SubstrateExplorer.explore(reinduce=False)` by default** — exploration now RECORDS + enqueues and does not induce. `reinduce=True` stays for callers that want it synchronously (tests).
- **Coordinator split into two idle tiers.** `_idle_operator_exploration_work` acts + records CONTROLLABILITY (which acting establishes). New `_idle_operator_induction_work` drains induction off the acting path and moves the COMPETENCE beliefs the results earn — because learning is what changes competence, not the acting that fed it. `UDM.address_deficit`'s LEARN_OPERATOR likewise records controllability only; competence follows the drain.

**Why the split of signals matters:** controllability is a property of ACTING (did the world move when I acted?) and is known immediately; competence is a property of LEARNING (did an executable operator result?) and is only known after induction. Recording competence from the acting cycle was conflating them — and would have forced induction back onto the path to answer it.

**Verified (verify_offband_induction, 4/4):** recording enqueues the signature + the contrastive and induces NOTHING (no rule, queue holds the work); `drain_pending_induction` induces off-band → the operator becomes executable and the queue clears; a real filesystem `explore` cycle records + enqueues (acted=4, pending=2) with NO rule induced on the acting path. All prior suites still green (diagnosis 11/11, dispatch 7/7, transfer 6/6, A–E harness 8/8 with `{A:3,B:0}` allocation, 150 in the broad learning run; the 2 `test_numeric_induction` failures are pre-existing — they reference the removed `ReasoningMode.AUTO`).


 ## Condition B
same goal
same world 
same knowledge
high latency
high pressure
thermal/resource stress

→ appraisal changes
→ perhaps cautious / strained / verification-heavy 
---

## The Self — building the substrate's identity + inverting coordinator ownership — 2026-08-27

**Frame.** `unified_llm` held Torin's identity ONLY as prompt strings recited by the model; pulling the LLM out of the centre left the substrate with a brain and no self. Mapped it: `docs/IDENTITY_PROMPT_MAP.md` (identity + "how to act" both trapped in prompts), `docs/AUTONOMOUS_COORDINATOR_MAP.md` (the coordinator through-and-through). Headline finding, verified by whole-file caller trace: **the coordinator's live loop is ALREADY substrate-native** (tier scheduler: `_coordination_cycle`→`_run_idle_work`); the LLM "Singleton" think-loop (`_singleton_thinking_cycle`) and a whole second architecture (autonomous-thinking loop, LLM goal-gen, perception→plan→execute pipeline, maintenance chain) were **DEAD — zero callers**.

**The Self** (`core/agents/autonomous/self_model.py`, class `Self`, user named it "just self"). A THIN integrator: it READS the faculties already in the folder (appraisal=attitude, intrinsic_motivation=temperament/drives, constitution=values, behavior_arbiter=disposition) via their singletons and composes ONE identity + disposition + `render()`. Reimplements nothing — each faculty keeps its authority. Every field derived or honestly None (no mood before appraisal). Verified: a self that CHANGES with real state (eager after a good controlled outcome, doubt after a strategy failure).

**Computational interoception (user's frame).** The appraisal variables ARE interoception (the substrate's read of its own internal state); the metrics that feed them are the interoceptive channels. Emotions are functional CATEGORIES over the integrated interoceptive state — `doubt = mean(1−confidence, epistemic_opportunity, risk)`. So "I feel doubt" is a legitimate FUNCTIONAL claim (not qualia), and AUDITABLE: `SelfState.interoception` carries the readings. But the self SPEAKS qualitatively — no numbers next to feelings; the readings stay inspectable state, not in the voice.

**Deepened (real, persisted, no stubs, verified vs live DB).** competence = validated actionable operators per domain from `unified.learned_rules` (survives restart; the LEVEL persists, the RATE doesn't); purpose = ACTIVE `internal_directives` (None when none — never invented); continuity = disk-persisted motivation baseline + deployment DB name. Read real prior-session domains (kite17, warehouse); honest-empty on absent directives.

**Ownership inversion — the Self owns + EXPOSES the cognition faculties, the coordinator reaches them THROUGH it (behavior-preserving, same singletons):** `reasoning()`→NeuralSymbolicBridge (carries logical/proof/abstract — no separate logical faculty), `learning()`→SubstrateLearning, `domains()`→UDM, `intelligence()`→PredictiveIntelligenceSystem, `memory()`→memory agent, `meta_learning()`→MetaLearner, `language()`→ReadingRegistry (model-free reading — the substrate's OWN language, the complement to render(); ties to "teach it English"). The **LLM is NOT a faculty** — an optional resource consulted only when the substrate can't represent something. Coordinator got `self.self = get_self()`; `reason_about`→`self.self.reasoning()`, induction drain→`self.self.learning()`, `_run_exploration_cycle`→`self.self.disposition()`. Fixed two real divergences: the tiers built FRESH `UniversalDomainMaster()` instances, and the coordinator built its OWN `PredictiveIntelligenceSystem` — both now the Self's singletons. Verified: disposition-via-Self == inline appraisal→arbiter; all faculties one instance, owned by the Self.

**Substrate health diagnosis (replaced the LLM call with what it's supposed to be).** `_analyze_health_with_ai` (lightweight-LLM JSON verdict) → `_diagnose_health`, deterministic and model-free: the monitor ALREADY classifies severity and proposes actions, recovery history gives recurrence — the LLM was re-deriving what the substrate knows. No LLM, no fallback (per the standing "no LLM as fallback"). Same conservative policy by construction: reversible ops (restart/flush) low-risk and auto-act when severe; code-altering ops (patch/delete) high-risk and withheld.

**Dead-code strip — authority-justified, no capability lost.** The user's challenge: are we losing capability by deleting instead of rewriting? Resolved by the authority principle: every dead method was an **LLM-wrapper over a capability already owned by a live authority** — `_provide_longterm_memory_context`/reflection → the MEMORY AGENT (`search_memories`, `consolidate_memories`, `form_abstractions`, `reflect_on_beliefs`); the Singleton loops → appraisal→arbiter→tiers + intrinsic motivation; the phase pipeline → the live coordination cycle. So nothing to rewrite; the capabilities live in their authorities, which the Self exposes. Removed 20 dead methods (incl. `_execute_singleton_maintenance` chain, the whole Singleton cluster, the perception→plan→execute pipeline, the dead health/automation queue chain, the shadowed duplicate `_receive_health_event`), unwired the always-empty health-queue drain, deleted the two now-unused queues. **10,965 → 9,184 lines. `self.llm.generate`: 0. `lightweight_llm`: 0.** Verified: 0 dangling refs, no external callers of removed names, coordinator imports, substrate 13/13. KEPT what's live: `_create_recovery_goal_from_health_event` (health-tier fallback), `_execute_task_with_singleton`+helpers (external API), `_learning_phase` (idle tier), `apply_throttle` (recovery_manager caller), the substrate `_receive_health_event`.

**Errors/process notes.** (1) Mis-framed "move the LLM brain into the Self" — corrected: we replace it with substrate diagnosis, the LLM is never a Self faculty. (2) Flagged `_provide_longterm_memory_context`/reflection as needing rewrite — user caught it: memory belongs to the memory agent, which already owns those (incl. `reflect_on_beliefs`). (3) Removed a dead method before proving supersession — corrected the process: audit (dead capability → owning authority) BEFORE deleting. (4) Re-verified callers with fresh greps after each removal shifted line numbers; caught that `_create_recovery_goal_from_health_event` and `_process_health_events` are called from the LIVE health tier (one a real fallback → keep; one behind an always-empty-queue guard → drop with the guard).

---

## Retiring the LLM — repo-wide campaign — 2026-08-28

**The standing directive, finally stated cleanly (user).** The ONLY place a model belongs is **TeacherPolicy** (it proposes; the substrate verifies and attests). EVERY other LLM call site — both services, `unified_llm` (35B) AND `lightweight_llm` (8B) — is a capability to REWRITE for the substrate and MOVE to its authority: not deleted, not stubbed, not assumed to exist, **each verified END-TO-END against the running system before AND after.** Correcting my own drift: I kept saying "demotion / keep a resource"; the user's point is retirement — no permanent LLM seat anywhere. Maps built: `docs/LLM_CALLSITE_MAP.md` (~33 files, ~12 authorities, grouped by target authority), `docs/LLM_RETIREMENT.md` (roadmap). Memory: [[torinai_llm_retirement]].

**The verification lesson (user caught me).** I claimed reasoning-trace and response paths were "verified against the live system" when I had only grepped. Re-did it by RUNNING: under `TORIN_MODEL_POLICY=strict_model_free` the substrate proves `socrates_mortal` at 0.98 with **0 LLM calls** and enqueues its own proof trace to memory (tagged `reasoning`); `conversation.understand` replies model-free. But the same run corrected a false claim — `reason()` returns silent-EMPTY for queries the solvers can't parse ("17+25" → '' because 0 arithmetic operators are learned: 3 executable rules total, confirmed live). Grep says a line exists; only running says it fires.

**The biggest LLM-centered organ, named.** `general_purpose_executor.py` opens with "Executes tasks by delegating to the teacher model… **Delegates ALL intelligence to LLM**." After all the substrate faculties, the thing that actually DOES dispatched work is still a plain LLM agent loop (`generate_with_messages` picks every tool call). That — not the `unified_llm` file rename — is the real "no longer LLM-centered" work. Also on the list per the user: `prometheus_exporter.py` measures the MODEL (rewrite → measure the substrate + the model census from `model_policy`); `monitoring/publishers/event_publisher.py` (DriftEventPublisher/NATS) has ZERO callers — built-never-wired, verify+wire.

**Identity extracted to the Self (done, verified).** `IDENTITY_CORE` + `Self.identity_prompt(role)` now own who Torin is — model-generic (fixed a real drift: the duplicated persona said 21K context in one copy, 32K in another). `unified_llm.system_prompts` became `_IdentityPrompts`, resolving every audience to `get_self().identity_prompt(role=…)`; ~24 boilerplate "advanced AGI assistant" copies collapsed to one identity source. Ownership boundary the user chose: **Self owns identity + self-state; caller owns product role.** `render()` stays first-person live mood; `identity_prompt()` is the second-person stable seed. All 6 external callers + 2 internal fallbacks resolve; py_compile clean.

**Redundant LLM reasoning-trace dropped (done, verified).** `unified_llm._store_reasoning_trace` + `_split_reasoning_steps` + `_reasoning_tasks` removed; `_handle_reasoning` is log-only. It persisted the MODEL's chain-of-thought to memory tagged `llm/chain_of_thought` — the "model attests" anti-pattern. The SUBSTRATE captures its OWN proof trace (`neural_bridge`), verified still firing after removal.

**Target #1 — DOMAIN CONCEPT EXTRACTION — DONE, verified end-to-end (the pattern).** Authority boundary (user's question "what does concept ingestion do that semantics does not?"): `semantics/` reads language→structure ("SEMANTICS OWNS THIS"); `domain/concept_ingestion.ConceptIngestionService` owns the concept STORE (sole writer of `unified.concepts`). Not duplicates — semantics = language→structure, ingestion = structure→stored graph, joined by `cognitive_ingress` ("the one door"). Verified the substrate path works BEFORE cutting over (the user's gate: "only if tested and it works first"): `conversation.teach("a zorblaxumatic is a vehicle")` → concept stored via the DETERMINISTIC extractor (`extractor='structured'`), **0 LLM**; unreadable prose ("Hydraulic fluid under pressure actuates the cylinder") → `stored=False`, honest "I could not read that sentence", **not faked**. Store already dominated by the model-free path: **3,316 `structured` relations vs 195 `llm_structured`** (the old "100% llm_structured" memory is stale). Coverage measured: the reader handles ~4/8 real sentences (copula/SVO/simple), refuses the rest — user chose "honestly unread (pure substrate)". THEN retired `SemanticExtractor` (`extract_structured`) + `LLMConceptExtractor` (`generate`); archived to `archive/llm_concept_extraction_pre_retirement_2026-08-28/` (no git here → archive first). `domain/` is now LLM-free; **`extract_structured` now has exactly ONE caller — `llm_teacher`** (the allowed consumer). Tests: removed the ones exercising the retired classes, kept the model-neutral `ExtractionResult` contract tests, swapped `LLMConceptExtractor`→`ConceptExtractor` in the registration test — 8 pass. Follow-up flagged: `ExtractionResult`/`record_attempt`/`extraction_attempts` now have no producer.

**Context compression — NOT a rewrite target, retires WITH the executor (user's question "does the substrate even have context limits?").** `context_compression.py` + `context_manager.py` + `context_config.py` are LLM-window artifacts — "compress conversation history to reduce token usage", only functional caller is the executor's conversation manager. Verified: `n_ctx`/context-window lives ONLY on the two model services and the executor loop; **no substrate cognition module imposes a token window** — the substrate reasoner RETRIEVES (`inject_memories`, top-k by relevance), it has no accumulating buffer to compress. So nothing moves to a substrate authority (the substrate doesn't have the problem); it retires when the LLM executor is replaced. Pruned from the worklist.

**Health monitor / recovery manager — pruned as false positives.** `health_monitor._check_llm_health` PROBES the teacher model (loaded? throughput? failure rate?), `recovery_manager` re-inits it on recovery. They MONITOR/MANAGE the model, they don't use it for cognition — they stay as long as the teacher exists. The actual health-DIAGNOSIS cognition was already replaced in the coordinator (`_diagnose_health`, 2026-08-27). Lesson: the raw grep over-counts; several "LLM call sites" are monitoring/lifecycle/registry of the model service, not cognition.

## Target #2 — INTRINSIC MOTIVATION → substrate, no LLM — 2026-08-28

**The file was written LLM-first** (user: "it is wrote to be llm… I'm seeing a lot of prompts"). Goal generation, goal mutation, and the stable-system branch all prompted the model. Removed: `_generate_contextual_goals_with_llm` (the `process_request` that invented goal strings from a big prompt), `_mutate_goal_dimensions` (LLM rewrite of a too-similar goal), both `if self.llm:` fallback branches in `generate_curiosity_driven_goals`, `set_llm`/`self.llm`, `_build_system_context`, and — on the user's call — the static `_generate_exploration_goal` (a canned 4-item list, a milder stub).

**Design decision (user chose "honest empty — no fallback").** Goals come ONLY from real substrate signals: metric-driven (component uncertainties) + epistemic (unstable beliefs). When both are empty → no goal that cycle. No LLM invention, no static seed pool. Restructured the entry so the epistemic path is ALWAYS attempted (the original skipped it when component_metrics was empty — a latent gap), then honest-empty.

**Verified the substrate ACTUALLY does intrinsic motivation, against the real system** (user insisted — I had only removed calls, not proven the substrate could do the job). `_quantify_component_uncertainties` derives per-component epistemic uncertainty from real signals (failed_tasks / performance_metrics / recent_errors / knowledge_gaps / security_findings), distinguishing epistemic (learnable) from aleatoric from structural, and severity-boosting from security findings. `_create_metric_driven_goal` composes the goal from the actual readings — "tool_executor shows 70% prediction error, 100% failure rate → analyze prediction failures and model assumptions" — and honestly returns None when no metric was measured (won't fabricate a 0.0). `_generate_epistemic_goals` pulls from `EpistemicEngine.get_unstable_regions()`. Live result from injected signals: 4 real metric-composed goals; empty context → 0 goals; **generate=0, process_request=0**. Honest caveat: the novelty/dedup step (`_calculate_goal_similarity`) uses an embedding ENCODER — a model, not the LLM; core goal generation is fully model-free.

**Cleanup + pitfalls.** Coordinator's `set_llm(self.llm)` connect-call removed; `test_intrinsic_motivation.py` (was a 381-line LLM-centric manual script) rewritten to verify the substrate — passes; no dangling refs repo-wide; DB novelty rows the test wrote cleaned. Pitfall: two removed methods held COLUMN-0 f-string prompt bodies, which broke a naive "next unindented line = class end" span remover and orphaned their tails — fixed by anchoring excision on the bracketing valid methods and recompiling after each. (A missing module getter mid-session turned out to be the user's own edit/restore, not my removal — I wrongly blamed my edit first.)

**Open, user-raised: Self-ownership of motivation.** The coordinator still constructs it (`autonomous_coordinator.py:207`, residual composition-root) rather than reaching it through the Self like `reasoning()`/`learning()`/`domains()`. The Self only reads it privately (`_motivation()`). Inverting it = add public `Self.motivation()`, bring the faculty up in `Self.initialize()` with config (the singleton is first-caller-wins, so construction ownership is the real move), repoint the coordinator's goal loop. Deferred pending the user's ordering call.




**SEVERANCE TEST (user-designed) disproved my "only downstream" claim, then confirmed it after a fix.** I had asserted MiniLM was "only downstream, not deciding what merits investigation." The user proposed the decisive test: run the exact tool_executor case (pred_err 0.70, fail 1.00) with MiniLM SEVERED, and check that the goal still forms. Run clean, it FAILED — but in the mirror image of the feared mode: with MiniLM PRESENT and an identical goal already in the novelty store (similarity 1.0), the goal was SUPPRESSED; severed, it emitted. Cause: `_create_metric_driven_goal` and `_generate_epistemic_goals` used the novelty similarity as a HARD VETO (`if similarity > threshold: return None/continue`) — similarity machinery sitting inside the motivational authority. So the claim was false. Fix: removed both vetoes; formation is now purely deterministic (metrics/entropy decide); MiniLM's similarity is computed and stored ONLY for downstream dedup/retrieval (embedding index + `novelty_similarity` metadata), and does NOT feed the goal's priority or `expected_novelty` (the selection score `_calculate_goal_priority` already used the deterministic theme-frequency `novelty_potential`, never MiniLM). Re-verified: with MiniLM present vs severed, the tool_executor goal forms in BOTH and `expected_novelty` is IDENTICAL (0.48) — MiniLM has zero effect on the goal. Pinned as a regression test in `test_intrinsic_motivation.py` (severs `EmbeddingService.generate_embedding`, asserts the goal still forms). Lesson: a "downstream" claim is only true if severing the model leaves the decision unchanged — test it, don't assert it. (Also revisited an over-correction of my own: I first blended MiniLM into `expected_novelty` as "guidance", which re-introduced it as a priority input — reverted, because the user's frozen claim requires priority inputs to be deterministic.)

## Torin demonstrated model-free intrinsic goal formation from internally measured epistemic uncertainty, prediction error, and operational failure. Goal targets, rationale, priority inputs, and epistemic actions are selected deterministically by the substrate. MiniLM is used only downstream for semantic novelty/deduplication and retrieval, not for reading, responding, or deciding what merits investigation.


_(Verified 2026-08-28 by the severance test above: severing MiniLM leaves goal formation and ranking unchanged; 0 LLM.)_

## Target #3 — COMPLETION PROTOCOL: retire the LLM critic + resolve the two-validator duplicate — 2026-08-28

**Question first (user): "is it even NEEDED for the substrate?"** Answer, from the code: there are TWO completion models. Substrate state-goal execution (`_drive_substrate_goal`) determines completion by RE-OBSERVING whether the world holds the goal — deterministic, and it never touches this protocol. The completion protocol verifies DELIVERABLE tasks (research/code) the LLM executor produces. Its core principle is already the substrate's — verbatim: *"Completion is a SYSTEM PROPERTY, not a model output… replaces self-attestation with externally verifiable criteria."* Its deterministic layers (artifact-on-disk, code-execution evidence, tests, deps, score ≥ threshold) are model-free; the LLM `critic_llm` was an OPTIONAL layer, each call site *"skipped gracefully when critic_llm is unavailable"* and defaulting to neutral.

**Tested BOTH validators against the real system before touching either (user's gate).** Decisive case — a result CLAIMING a file was created, with the file missing: `SuccessValidator` (legacy) → `complete=True, conf=0.9, no issues` (rubber-stamp: it validates the result DICT, i.e. self-attestation, not the world); `TaskCompletionValidator` → `revision_requested` with reality checks firing exactly right ("Claimed path does not exist on disk"; "EXECUTION task completed with zero code-execution tool calls — no real implementation can have occurred"; "listed in files_created but no matching write_file call"). And it caught the false completion **with the critic OFF** — the reality checks are all deterministic, confirming removing the critic doesn't weaken the guard. So `TaskCompletionValidator` is the one to preserve; `SuccessValidator` is the fooled one.

**Removed the LLM critic** (`completion_protocol.py` 2532→1868 lines): the 3 semantic gate blocks (question-based / claim-grounding / coverage) reduced to their neutral defaults; the 3 `_run_*_validation` methods + `_generate_verification_questions` + helpers (`_collect_evidence_text`, `_extract_atomic_claims`, `_extract_task_requirements`) deleted (all orphaned once the blocks went); `_check_goal_alignment` stripped to its deterministic structured-rubric fallback (it's still called by the deterministic path); `initialize()` drops the `critic_llm` param; executor stops acquiring/supplying `critic_llm`. Zero `critic_llm` references remain. Archived first (no git): `archive/completion_llm_critic_pre_retirement_2026-08-28/`.

**Resolved the two-validator duplicate.** `SuccessValidator` was coordinator-only (import + construct + one call in the `verification_state=='legacy'` fallback). Deleted `success_validator.py`; replaced the fallback with honest handling — an unverified result is honoured only at its own explicit `success` flag, capped at 0.5 confidence and flagged UNVERIFIED, never rubber-stamped. One completion authority now.

**Pitfall avoided this time:** archived the large file before surgery, removed method-spans by anchoring on bracketing valid methods (not naive indentation), and recompiled after every excision — no orphaned fragments (contrast the intrinsic_motivation botch). Verified: all three touched files compile + import; the validator still rejects the fabricated completion with the critic gone; no dangling refs repo-wide.

**Framing kept:** the completion protocol is deliverable-task scaffolding around the LLM executor. As substrate execution (world-observation completion) takes over, it shrinks in importance; the deterministic verification is genuinely substrate-aligned and stays. The LLM critic's semantic checks (does the output answer / ground claims / cover requirements, by meaning) are a capability to migrate to the substrate's LANGUAGE faculty later, not something to fake.