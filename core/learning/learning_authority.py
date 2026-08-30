#!/usr/bin/env python3
"""The authority for learning: the substrate, and what may contribute to it.

Before this existed there were two learning stacks that did not know each other.

`UnifiedLearningSystem` was the DECLARED authority -- exported from
`core/learning/__init__.py` as the `ILearningSystem`, instantiated in
`core/main.py`, built around the language model. It referenced `rule_induction`,
`RuleInducer`, `rule_store`, `RuleStore`, `TeacherPolicy` and
`ProbabilisticVersionSpace` exactly ZERO times.

The learning that actually works -- induction, epistemic status, active
teaching, learning under noise, analogical transfer, hidden-cause detection;
everything EDU-01 through EDU-11 measured -- had NO owner. `core/main.py` never
mentioned it. It was assembled ad hoc at three consumer call sites
(`enhanced_logical_agent`, `general_purpose_executor`, `planning_engine`), each
reaching past the subsystem to grab the parts it happened to need.

So the module named "unified learning system" did not touch the learning with
experimental evidence behind it, and the learning with evidence behind it
answered to nobody.

This module inverts that. The substrate is the authority. A language
model -- or any other proposer -- is a CONTRIBUTOR to it.

THE CONTRIBUTION BOUNDARY IS THE POINT.

    a contributor may PROPOSE      a hypothesis, a situation, a formalization
    a contributor may NOT ATTEST   nothing it offers is evidence

Everything admitted through `contribute()` enters as CANDIDATE with **zero
evidence roots**, exactly like an analogical projection, and only
world-supplied outcomes can move it. There is deliberately no confidence field
on a contribution: a proposer's own certainty is not information about the
world, and accepting one would let a fluent model promote itself.

This is not a policy applied to language models specifically. It is the same
rule the substrate already applies to analogy -- analogy proposes, only
target-domain evidence authorizes -- generalised to every source of proposals.

NOT AN `ILearningSystem`. That interface was shaped around the model-based
system (`adapt_behavior`, `consolidate_learning`, `learn_from_feedback`), and
implementing it here would mean writing several methods that do nothing in
order to satisfy a shape. The authority exposes what it actually owns.

It declares `ILearningAuthority` instead -- a contract drawn FROM this class's
real surface rather than from an idea of what a learner should look like, so
declaring it costs nothing and adds no method that exists to satisfy a shape.
The refusal above stands; what changed is that there is finally an interface
describing the thing that was refusing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from core.capability import raise_if_structural
from core.learning.learning_interfaces import ILearningAuthority
from core.learning.rule_induction import (CandidateRule, InductionResult,
                                          InductionStatus, TrainingExample,
                                          get_rule_inducer)
from core.learning.rule_store import EpistemicStatus, get_rule_store

logger = logging.getLogger(__name__)


# The induction basis is BOUNDED so the hypothesis search stays tractable as
# demonstrations accumulate. Induction cost is exponential in the number of
# examples (measured on real evidence: ~0.03s at 12, ~0.9s at 16, ~17s at 20,
# and past that it does not return), while the information LGG needs saturates
# early: a handful of positives with VARIED constants is what fixes which
# argument positions generalise, and a few negatives is what fixes the
# preconditions. Beyond that, more examples are cost without evidence. Held-out
# validation (reserved separately, before this bound is applied) remains the
# correctness guard, so bounding the basis can never admit a rule the reserved
# evidence does not independently confirm -- it can only make a learnable
# operator learnable in bounded time.
_BASIS_POSITIVES = 8
_BASIS_NEGATIVES = 8
_BASIS_CONTRASTIVE = 6


def _bounded_basis(
    signature_basis: List[TrainingExample],
    contrastive: Sequence[TrainingExample],
) -> List[TrainingExample]:
    """A bounded, constant-diverse subset of the evidence for one induction.

    Exact-duplicate demonstrations carry no new information and are dropped.
    Among the rest, selection round-robins over distinct ground ACTIONS so a
    capped sample spans different constants -- which is exactly what LGG needs
    to variabilise an argument position, rather than many repeats of one move.
    Positives, negatives and contrastives are bounded independently so the
    sample keeps all three kinds of evidence the inducer relies on.
    """
    def _fingerprint(example: TrainingExample):
        return (example.positive, example.action,
                tuple(sorted((f.predicate, f.args) for f in example.before)),
                tuple(sorted((f.predicate, f.args) for f in example.after)))

    def _spread(examples: List[TrainingExample], cap: int) -> List[TrainingExample]:
        seen: set = set()
        unique: List[TrainingExample] = []
        for example in examples:
            key = _fingerprint(example)
            if key in seen:
                continue
            seen.add(key)
            unique.append(example)
        if len(unique) <= cap:
            return unique
        buckets: Dict[Any, List[TrainingExample]] = {}
        order: List[Any] = []
        for example in unique:
            if example.action not in buckets:
                buckets[example.action] = []
                order.append(example.action)
            buckets[example.action].append(example)
        selected: List[TrainingExample] = []
        depth = 0
        while len(selected) < cap and any(len(buckets[a]) > depth for a in order):
            for action in order:
                if depth < len(buckets[action]):
                    selected.append(buckets[action][depth])
                    if len(selected) >= cap:
                        break
            depth += 1
        return selected

    positives = _spread([e for e in signature_basis if e.positive], _BASIS_POSITIVES)
    negatives = _spread([e for e in signature_basis if not e.positive], _BASIS_NEGATIVES)
    contrastives = _spread(list(contrastive), _BASIS_CONTRASTIVE)
    return positives + negatives + contrastives


def _relevant_frame(basis: List[TrainingExample]) -> List[TrainingExample]:
    """Scope each demonstration to the object the action transforms.

    A full-world observation makes Plotkin LGG explode: it pairs every literal
    of a repeated predicate across examples, so a state with w facts of one
    predicate over n positives yields w**n body literals (measured on the
    filesystem domain: 4 files -> 4**n, past MAX_BODY_LITERALS already at n=2).
    But an operator is not about the whole world -- it is about the object it
    changes. That object is domain-agnostically identifiable as the term shared
    by the action's ADD and DELETE effects (for MOVE_FILE(fa,inbox,dst): add
    FILE_IN(fa,dst), delete FILE_IN(fa,inbox) -> fa). Restricting each
    demonstration's LEARNING state to the facts mentioning that object keeps the
    frame narrow without dropping any real precondition: a fact unconnected to
    the changed object cannot be range-restricted into the rule anyway. The
    domain's observe() still reports the whole world for planning and
    verification; only the basis handed to induction is scoped, and held-out
    validation is left on the FULL world so a scoped rule must still fire in
    reality.
    """
    # The object argument positions: those whose value persists through the
    # action's own change. Learned from the positives, which alone carry effects.
    tallies: Dict[int, int] = {}
    acted_positives = 0
    for example in basis:
        if example.action is None or not example.positive:
            continue
        acted_positives += 1
        added = set(example.after) - set(example.before)
        deleted = set(example.before) - set(example.after)
        persistent = ({t for fact in added for t in fact.args}
                      & {t for fact in deleted for t in fact.args})
        for index, arg in enumerate(example.action.args):
            if arg in persistent:
                tallies[index] = tallies.get(index, 0) + 1
    if not tallies:
        return basis  # no transform object identifiable; scope nothing
    object_positions = {i for i, count in tallies.items()
                        if count * 2 >= acted_positives}
    if not object_positions:
        object_positions = {max(tallies, key=lambda i: tallies[i])}

    def scoped(example: TrainingExample) -> TrainingExample:
        if example.action is None:
            return example
        anchors = {example.action.args[i] for i in object_positions
                   if i < len(example.action.args)}
        if not anchors:
            return example
        before = tuple(f for f in example.before if set(f.args) & anchors)
        after = tuple(f for f in example.after if set(f.args) & anchors)
        if not before and not after:
            return example  # nothing anchored; leave it rather than empty it
        from dataclasses import replace
        return replace(example, before=before, after=after)

    return [scoped(example) for example in basis]


class ContributionKind(Enum):
    """What a contributor is offering. None of these are evidence."""
    HYPOTHESIS = "hypothesis"          # a candidate rule to consider
    SITUATION = "situation"            # an experiment worth running
    FORMALIZATION = "formalization"    # a structure read out of unstructured input
    LESSON = "lesson"                  # teaching material


@dataclass(frozen=True)
class Contribution:
    """An offer from a proposer.

    Carries no confidence, deliberately. A proposer's certainty about its own
    output is not a measurement of the world, and admitting one would let a
    fluent contributor grade its own work.
    """
    contributor: str
    kind: ContributionKind
    payload: Any
    rationale: str = ""
    domain_id: Optional[str] = None


@dataclass
class Admission:
    """What the authority did with a contribution, and why."""
    accepted: bool
    reason: str
    contributor: str
    kind: ContributionKind
    #: Always CANDIDATE when accepted. A contribution cannot arrive validated.
    status: Optional[EpistemicStatus] = None
    rule_id: Optional[str] = None

    @property
    def is_knowledge(self) -> bool:
        """Never true on admission. Present so callers cannot forget to ask."""
        return self.status is EpistemicStatus.VALIDATED


@dataclass
class SubstrateLearning(ILearningAuthority):
    """Owns the substrate's learners and the boundary around what may propose."""

    _store: Any = None
    _inducer: Any = None
    _contributors: Dict[str, str] = field(default_factory=dict)
    _admissions: List[Admission] = field(default_factory=list)

    # ---- ownership -------------------------------------------------------

    @property
    def store(self):
        if self._store is None:
            self._store = get_rule_store()
        return self._store

    @property
    def inducer(self):
        if self._inducer is None:
            self._inducer = get_rule_inducer()
        return self._inducer

    def register_contributor(self, name: str, role: str) -> None:
        """Named so provenance survives. An anonymous proposal is untraceable."""
        self._contributors[name] = role
        logger.info(f"learning contributor registered: {name} ({role})")

    @property
    def contributors(self) -> Dict[str, str]:
        return dict(self._contributors)

    # ---- learning from the world ----------------------------------------

    def induce(self, examples: Sequence[TrainingExample],
               target_predicate: Optional[str] = None) -> InductionResult:
        """Learn a rule from demonstrations. The world is the only teacher here."""
        return self.inducer.induce(examples, target_predicate=target_predicate)

    async def record(self, result: InductionResult,
                     examples: Sequence[TrainingExample], *, domain_id: str,
                     rule_kind: str = "state_transition"):
        """Persist what induction produced, against the demonstrations that
        produced it.

        The store keys a rule's induction basis on the demonstrations, not on a
        bare list of ids, because it must know which were positive and which
        negative to attach each under the right evidence role. So the examples
        are passed through, matching `RuleStore.record_induction` exactly -- an
        earlier signature here passed `result.rule` and an `evidence_ids=`
        keyword the store never accepted, so any call would have raised.
        """
        return await self.store.record_induction(
            result, examples, domain_id=domain_id, rule_kind=rule_kind)

    async def record_demonstration(
        self, example: TrainingExample, *, domain_id: str,
    ) -> bool:
        """Keep one executed demonstration; do NOT induce here.

        This is the hot-path half of learning: the executor calls it right after
        acting, so it must be cheap. Induction is a hypothesis search whose cost
        grows with the richness of the observed state -- a full world-observation
        makes it far too expensive to run inline, and blocking execution on it
        would make every action pay for learning that belongs off the hot path.

        So the transition is recorded and induction is left to the always-online
        learner (`reinduce_operator`), which runs it in the background over the
        accumulated demonstrations. Returns whether a new demonstration was
        written (False if this observation was already recorded).
        """
        from core.learning.demonstration_store import get_demonstration_store
        return await get_demonstration_store().append(example, domain_id=domain_id)

    async def reinduce_operator(
        self, *, domain_id: str, predicate: str, arity: int,
    ) -> Dict[str, Any]:
        """Re-induce one operator from its accumulated demonstrations, off the
        hot path, and promote it to executable when independent experience
        confirms it.

        This is the always-online half of learning: the learner calls it for a
        signature that has gathered new demonstrations. It carries the whole
        cost of the hypothesis search, which is why the executor never does.
        """
        return await self._induce_signature(
            domain_id=domain_id, predicate=predicate, arity=arity)

    async def drain_pending_induction(self, *, limit: int = 50) -> Dict[str, Any]:
        """Induce every signature that has gathered demonstrations since it was
        last induced -- the always-online learner's whole job, run off the
        acting path.

        Acting only RECORDS (and enqueues); this drains the queue. A pending
        CONTRASTIVE means the domain gained an actionless negative that sharpens
        EVERY operator, so it expands to all the domain's signatures. Each
        signature is cleared once processed; a later demonstration re-enqueues
        it. Returns which domains gained a newly executable operator, so the
        caller can move their competence beliefs -- learning is what changes
        competence, not the acting that fed it.
        """
        from core.learning.demonstration_store import get_demonstration_store

        demos = get_demonstration_store()
        pending = await demos.pending_signatures(limit=limit)
        induced: List[Dict[str, Any]] = []
        by_domain: Dict[str, bool] = {}

        async def run(domain_id: str, predicate: str, arity: int):
            outcome = await self._induce_signature(
                domain_id=domain_id, predicate=predicate, arity=arity)
            induced.append(outcome)
            by_domain[domain_id] = by_domain.get(domain_id, False) or bool(
                outcome.get("executable"))

        for domain_id, predicate, arity in pending:
            try:
                if (predicate, arity) == demos.CONTRASTIVE:
                    for p, a in await demos.signatures(domain_id=domain_id):
                        if (p, a) != demos.CONTRASTIVE:
                            await run(domain_id, p, a)
                else:
                    await run(domain_id, predicate, arity)
            finally:
                await demos.clear_pending(
                    domain_id=domain_id, predicate=predicate, arity=arity)

        return {"drained": len(pending), "induced": induced, "by_domain": by_domain}

    async def learn_from_runtime(
        self, example: TrainingExample, *, domain_id: str,
    ) -> Dict[str, Any]:
        """Record one executed demonstration AND re-induce the operator it
        teaches, synchronously.

        Convenience for callers that want both halves in one step (and for
        tests). Production execution splits them: the executor calls
        `record_demonstration` on the hot path and the always-online learner
        calls `reinduce_operator`, so induction never blocks an action.

        This is the substrate learning an operator from its OWN action. The
        demonstration is the before/action/after the executor just observed;
        the WORLD supplied the verdict, not a teacher. Each call adds one
        observation to what the operator has been seen to do and re-induces over
        the whole accumulated set, so the model sharpens as experience grows --
        the concrete form of "the substrate learns from its own experience".

        The rule kind is the action predicate, so every demonstration of the
        same operator re-induces into the same semantic identity rather than
        minting a new rule each time. Induction runs over an earlier basis;
        the most recent demonstrations are held back to validate the result
        against experience it was not induced from, without ever letting the
        basis fall below the two positives induction needs. Until a second
        positive exists there is nothing to align, and the demonstration is
        simply kept.
        """
        # An actionless demonstration is contrastive evidence about the whole
        # domain; it teaches no single operator on its own, so it is kept and
        # does not trigger induction. It enters every operator's basis when that
        # operator is next re-induced.
        written = await self.record_demonstration(example, domain_id=domain_id)
        if example.action is None:
            return {"status": "contrastive_recorded",
                    "demonstration_recorded": written, "domain_id": domain_id,
                    "detail": "actionless negative kept as domain contrastive evidence"}

        predicate, arity = example.action.signature
        summary = await self._induce_signature(
            domain_id=domain_id, predicate=predicate, arity=arity)
        # This path induced the signature synchronously, so it owns clearing the
        # pending mark `record_demonstration` just set -- otherwise the off-band
        # drain would redundantly re-induce it. (A contrastive is left pending on
        # purpose: it sharpens every operator, which only the drain expands.)
        from core.learning.demonstration_store import get_demonstration_store
        await get_demonstration_store().clear_pending(
            domain_id=domain_id, predicate=predicate, arity=arity)
        summary["demonstration_recorded"] = written
        return summary

    async def _induce_signature(
        self, *, domain_id: str, predicate: str, arity: int,
    ) -> Dict[str, Any]:
        """Load a signature's demonstrations and re-induce its operator.

        Off the hot path by construction: this is the expensive half. Contrastive
        negatives from the whole domain enter the basis so induction can prove
        the action is necessary; the most recent action-ful demonstrations are
        held back to validate the result independently.
        """
        from core.learning.demonstration_store import get_demonstration_store

        rule_kind = predicate.lower()
        demos = get_demonstration_store()
        signature_examples = await demos.load(
            domain_id=domain_id, predicate=predicate, arity=arity)
        contrastive = await demos.load_contrastive(domain_id=domain_id)

        positives = [e for e in signature_examples if e.positive]
        summary: Dict[str, Any] = {
            "status": "insufficient_evidence",
            "demonstrations": len(signature_examples),
            "contrastive": len(contrastive),
            "positives": len(positives),
            "domain_id": domain_id,
            "signature": f"{predicate}/{arity}",
            "rule_id": None,
            "executable": False,
        }
        if len(positives) < 2:
            return summary

        # Hold the most recent action-ful demonstrations back for INDEPENDENT
        # validation, never dropping the basis below two positives. Contrastive
        # negatives are never held out: they are ambient evidence the induction
        # needs, not observations of this operator's own transitions. Recency
        # makes the split stable -- the rule is judged against what was seen
        # after it was learned.
        signature_basis = list(signature_examples)
        held_out: List[TrainingExample] = []
        while len(held_out) < 2 and len(signature_basis) > 1:
            if sum(1 for e in signature_basis[:-1] if e.positive) >= 2:
                held_out.insert(0, signature_basis.pop())
            else:
                break

        basis = _relevant_frame(_bounded_basis(signature_basis, contrastive))
        result = self.induce(basis)
        summary["status"] = result.status.value
        if result.status is not InductionStatus.RULE_LEARNED:
            return summary

        stored = await self.record(
            result, basis, domain_id=domain_id, rule_kind=rule_kind)
        if not stored:
            return summary
        record = stored[0]
        summary["rule_id"] = record.rule_id

        if held_out:
            try:
                await self.store.validate(record, held_out)
            except Exception as e:
                raise_if_structural(e, "learning_authority.learn_from_runtime")
                logger.info("validation of %s deferred: %s", record.rule_id, e)

        # Executable only if validation actually promoted it -- read the store,
        # do not infer it from having called validate.
        promoted = [r for r in await self.store.executable_rules(domain_id=domain_id)
                    if r.rule_id == record.rule_id]
        summary["executable"] = bool(promoted)
        # Project the learned operator into the concept graph so the operator
        # and concept learning systems meet. Cross-domain analogy searches
        # concept structures; an operator absent from that graph is
        # untransferable -- CrossDomainGrounder returned NO_MATCH for a routing
        # problem structurally identical to MOVE because MOVE had no
        # representation there. Only executable operators are projected.
        if promoted:
            projected = await self._project_operator_to_concepts(
                promoted[0], basis, domain_id=domain_id)
            summary["projected_to_concepts"] = projected
        summary["status"] = "operator_executable" if promoted else "operator_candidate"
        return summary

    async def _project_operator_to_concepts(
        self, record, basis: Sequence[TrainingExample], *, domain_id: str) -> bool:
        """Record the operator's induction roots in the concept graph, then
        project the operator itself as a derivative of them.

        `submit_learned_rule` is derivative and refuses dangling lineage, so its
        induction roots must exist in the graph first. Runtime demonstrations
        reach the graph through the executor; exploration-learned ones only
        reach the DemonstrationStore, so the roots are submitted here, off the
        hot path. Never fatal to learning: a projection defect must not lose a
        validated operator.
        """
        try:
            from core.domain.concept_ingestion import EvidenceSourceType
            from core.domain.evidence_producers import (
                submit_demonstration, submit_learned_rule)

            roots: List[str] = []
            for example in basis:
                # Contrastive negatives teach that an action is necessary; they
                # carry no action and so no operator structure to root.
                if example.action is None or not example.evidence_id:
                    continue
                await submit_demonstration(
                    example, domain_id=domain_id,
                    source_type=EvidenceSourceType.TASK_ARTIFACT,
                    producer="operator_learning",
                    source_id=f"{domain_id}:{example.action.predicate}")
                roots.append(example.evidence_id)

            if not roots:
                return False
            await submit_learned_rule(record, roots, producer="operator_learning")
            return True
        except Exception as e:
            raise_if_structural(e, "learning_authority._project_operator_to_concepts")
            logger.info("operator->concept projection deferred for %s: %s",
                        getattr(record, "rule_id", "?"), e)
            return False

    def derive_procedure(self, operators, guards, examples, terminal: str = "RESULT",
                         max_rules: Optional[int] = None):
        """Derive a length-general procedure from input/output evidence alone.

        A SECOND ACQUISITION MODE, NOT A SECOND LEARNER. `induce` is shown an
        action and generalizes what it does; this is shown what a procedure
        must PRODUCE and derives which learned operators to use, in what order,
        under what condition. Neither can answer the other's question, and
        both belong here so "what has Torin acquired" keeps one answer.

        It can only compose operators already learned, so nothing derived here
        widens what the substrate can do -- only what it can do in sequence.
        """
        from core.learning.procedure_synthesis import (DEFAULT_MAX_RULES,
                                                       derive_procedure)
        return derive_procedure(
            operators, guards, examples, terminal=terminal,
            max_rules=DEFAULT_MAX_RULES if max_rules is None else max_rules)

    def induce_causal_structure(self, observations: Sequence[Dict[str, Any]]):
        """Learn which conditions gate an outcome, from trials.

        WIRED HERE BECAUSE THIS IS THE OWNER. `ProbabilisticVersionSpace` --
        the learner EDU-10 and EDU-11 measured -- had NO public route at all:
        the only way to reach it was to import it and drive it directly, which
        is what made the first EDU-12 baseline a sidecar measuring its own
        harness rather than Torin.

        Returns the fitted version space, or None if the trials are unusable.
        Induction over observations is learning, so it answers to the learning
        authority rather than to the reasoning path.
        """
        from itertools import product

        from core.learning.probabilistic_version_space import (
            ProbabilisticVersionSpace, StructuralHypothesis)

        trials = [o for o in (observations or [])
                  if isinstance(o, dict) and isinstance(o.get("conditions"), (list, tuple))
                  and "outcome" in o]
        if not trials:
            return None

        conditions: List[str] = []
        for trial in trials:
            for condition in trial["conditions"]:
                if condition not in conditions:
                    conditions.append(condition)
        conditions.sort()
        if not conditions:
            return None

        # Every condition is required, forbidden, or irrelevant.
        space = ProbabilisticVersionSpace(hypotheses=[
            StructuralHypothesis(
                frozenset(c for c, a in zip(conditions, assignment) if a == 1),
                frozenset(c for c, a in zip(conditions, assignment) if a == 2))
            for assignment in product((0, 1, 2), repeat=len(conditions))])

        for trial in trials:
            outcome = trial["outcome"]
            if outcome is None:
                # UNKNOWN is inert by construction; pass it through so the
                # version space counts it rather than guessing a value.
                space.observe(frozenset(trial["conditions"]), "unknown")
            else:
                space.observe(frozenset(trial["conditions"]),
                              "success" if outcome else "failure")
        return space

    def induce_sequence_rule(self, terms: Sequence[Any]):
        """Learn the rule behind a numeric sequence, and what comes next.

        DELEGATES TO `RuleInducer`. There is no second numeric pattern-learner:
        arithmetic was un-deferred inside the induction owner instead, so
        "what has Torin generalized" keeps one answer. Each consecutive pair is
        a demonstration -- CURRENT(a) --ADVANCE--> CURRENT(b) -- carrying the
        arithmetic relations that hold across that transition, and the rule is
        whatever generalises over them.

        Returns (InductionResult, next_value). `next_value` is None whenever
        the induced rule does not determine one, which includes the case where
        the version space has not collapsed: MULTIPLE_HYPOTHESES is a real
        answer, not a failure, and guessing between them is what a version
        space exists to avoid.
        """
        from core.learning.rule_induction import (Fact, InductionStatus,
                                                  TrainingExample,
                                                  arithmetic_background,
                                                  canonical_term, is_number)
        from core.reasoning.unification import match_body

        values = [canonical_term(str(t)) for t in (terms or [])]
        if len(values) < 3 or not all(is_number(v) for v in values):
            return None, None

        examples = []
        for before, after in zip(values, values[1:]):
            background = tuple(arithmetic_background([before, after]))
            examples.append(TrainingExample(
                before=(Fact("CURRENT", (before,)), Fact("ADVANCE", ())) + background,
                action=Fact("ADVANCE", ()),
                after=(Fact("CURRENT", (after,)),) + background,
                positive=True))

            # NEGATIVES, OR THE ANSWER IS VACUOUS. Without them the
            # generalisation is `PLUS(?X1, ?X2, ?X0) -> CURRENT(?X0)` with ?X2
            # unbound -- "the next term differs from this one by SOMETHING",
            # which fires for every possible successor and was being reported
            # as RULE_LEARNED. Measured on 1,4,9,16 and 2,5,11,23, neither of
            # which has a constant difference or ratio.
            #
            # A demonstration that the action did NOT produce some other
            # successor is the only thing that can refute an overgeneral rule,
            # which is what negatives are for.
            # The counter-demonstration makes a WRONG successor reachable in
            # the before-state and then shows the action did not produce it.
            #
            # A first attempt built the background from [before, wrong] AND set
            # after=CURRENT(wrong) -- which asserts the wrong value DID happen.
            # That is a positive example wearing a negative's label, and it
            # refuted nothing.
            wrong = canonical_term(str(float(after) + 1))
            examples.append(TrainingExample(
                before=(Fact("CURRENT", (before,)), Fact("ADVANCE", ()))
                       + tuple(arithmetic_background([before, wrong])),
                action=Fact("ADVANCE", ()),
                after=(Fact("CURRENT", (after,)),),
                positive=False))

        result = self.inducer.induce(examples)
        if result.status is not InductionStatus.RULE_LEARNED or not result.rule:
            return result, None

        # Apply the learned rule to the last term: the next value is whatever
        # the rule's body binds when the state is the final observed term.
        last = values[-1]
        state = set(arithmetic_background([last])) | {
            Fact("CURRENT", (last,)), Fact("ADVANCE", ())}
        # The background above relates `last` to nothing yet, so extend it with
        # every candidate the rule's own arithmetic literal can satisfy.
        for literal in result.rule.body:
            if literal.predicate in ("PLUS", "TIMES") and len(literal.args) == 3:
                step = literal.args[1]
                if not is_number(step):
                    continue
                base, factor = float(last), float(step)
                nxt = base + factor if literal.predicate == "PLUS" else base * factor
                state.add(Fact(literal.predicate,
                               (last, step, canonical_term(str(nxt)))))

        for bindings in match_body(result.rule.body, frozenset(state)):
            for effect in result.rule.effects.substitute(bindings).add:
                if effect.predicate == "CURRENT" and effect.is_ground:
                    return result, effect.args[0]
        return result, None

    # ---- the contribution boundary --------------------------------------

    async def contribute(self, contribution: Contribution) -> Admission:
        """Admit a proposal -- as a CANDIDATE carrying no evidence, or not at all.

        A rejected contribution is not an error; declining is the common case
        and must stay cheap. What must never happen is a contribution arriving
        with any status other than CANDIDATE.
        """
        if contribution.contributor not in self._contributors:
            admission = Admission(
                False, "contributor is not registered; a proposal with no "
                       "traceable origin cannot be admitted",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        if contribution.kind is not ContributionKind.HYPOTHESIS:
            # Situations, formalizations and lessons are consumed by the
            # teaching and formalization paths; they never become stored
            # knowledge on their own, so admission ends here.
            admission = Admission(
                True, "accepted as a proposal; not stored as knowledge",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        rule = contribution.payload
        if not isinstance(rule, CandidateRule):
            admission = Admission(
                False, f"hypothesis payload is {type(rule).__name__}, not a CandidateRule",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        try:
            stored = await self.store.record_induction(
                rule,
                domain_id=contribution.domain_id or "unassigned",
                # THE LOAD-BEARING ARGUMENT. No evidence roots, so nothing the
                # contributor said counts as support. The rule must earn its
                # status from the world exactly as an analogical projection does.
                evidence_ids=[],
            )
        except Exception as e:
            raise_if_structural(e, "learning_authority.contribute")
            admission = Admission(False, f"could not record proposal: {e}",
                                  contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        admission = Admission(
            True, "admitted as CANDIDATE with no evidence roots",
            contribution.contributor, contribution.kind,
            status=EpistemicStatus.CANDIDATE,
            rule_id=getattr(stored, "rule_id", None))
        self._admissions.append(admission)
        return admission

    @property
    def admissions(self) -> List[Admission]:
        """The full record, accepted and rejected alike."""
        return list(self._admissions)

    # ---- what the authority knows ---------------------------------------

    async def rules(self, domain_id: Optional[str] = None):
        return await self.store.load(domain_id=domain_id)

    async def metrics(self) -> Dict[str, Any]:
        accepted = [a for a in self._admissions if a.accepted]
        return {
            "contributors": self.contributors,
            "contributions_seen": len(self._admissions),
            "contributions_accepted": len(accepted),
            # Reported separately because they are different claims: a
            # proposal that was admitted is not a thing that was learned.
            "contributions_promoted_to_knowledge": sum(
                1 for a in accepted if a.is_knowledge),
        }


_authority: Optional[SubstrateLearning] = None


def get_learning_authority() -> SubstrateLearning:
    global _authority
    if _authority is None:
        _authority = SubstrateLearning()
    return _authority


__all__ = ["SubstrateLearning", "Contribution", "ContributionKind", "Admission",
           "get_learning_authority"]
