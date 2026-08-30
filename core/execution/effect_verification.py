#!/usr/bin/env python3
"""Did the world do what the learned rule predicted?

One canonical interpretation of what a tool did, and one comparison of that
against what the operator claimed would happen. Every consumer -- the rule
store's runtime evidence, the world-state updater, memory -- reads the same
`ToolObservation`. Nothing re-parses raw tool output downstream; a second
interpreter is how two parts of the substrate come to believe different things
happened.

Three runtime outcomes, because absence of evidence is not contradiction:

    CONFIRMATION    observation positively matches the predicted effect
    CONTRADICTION   observation positively establishes the opposite
    INDETERMINATE   execution occurred; observation cannot settle it

A successful tool call is NOT confirmation of the learned action model. The
tool reporting "completed" says the command ran, not that the world changed the
way the rule said it would. Collapsing those two would let a rule accumulate
support from its own invocation, which is the purest form of a system
confirming itself.

Add and delete effects are verified independently and kept independent. An
operator that adds AT(z,LAB) and retracts AT(z,HALL) can come back
ADD confirmed / DELETE unknown, or ADD confirmed / DELETE contradicted, and
those are different facts about the rule. Reducing them to one boolean discards
exactly the signal that would say which half of the model is wrong.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from core.learning.rule_induction import Fact, RuleEffects
from core.reasoning.unification import match_literal

logger = logging.getLogger(__name__)


# ── CONCURRENT-EXECUTION INTERFERENCE ─────────────────────────────────────
#
# The coordinator runs several tasks at once. A rule is judged by observing
# what changed in the world during an act, and that judgement is only sound if
# nothing ELSE moved the world meanwhile. Two tasks acting in the same domain
# CAN move it for each other, so a contradiction observed then is not
# attributable to either rule -- and recording it as rule evidence would revise
# a correct rule because another task happened to run at the same time.
#
# The guard does NOT serialize anything. Executions run fully in parallel; this
# only remembers whether another execution in the SAME domain overlapped this
# one in time. When one did, attribution treats the mismatch as external, not
# as evidence against the rule. Single-task execution and execution in DIFFERENT
# domains never overlap here, so learning proceeds exactly as before -- the only
# thing suppressed is a false refutation that concurrency would have invented.
#
# Domain is a sound over-approximation of "same world": two tasks in different
# domains observe disjoint facts and cannot interfere. Within one domain it may
# flag interference between tasks that touched disjoint objects, which only
# declines to learn from a contradiction rather than inventing one -- the safe
# direction, matching the module's fail-toward-INDETERMINATE stance.

_interference_lock = threading.Lock()
_active_by_domain: Dict[str, set] = defaultdict(set)
_overlapped_tokens: set = set()


@contextlib.contextmanager
def concurrent_execution_guard(domain_id: Optional[str]):
    """Mark a substrate execution active in `domain_id` for its duration.

    Yields a callable returning whether another execution in the same domain
    overlapped this one in time -- the value to pass as
    `AttributionContext.external_interference`.
    """
    token = uuid.uuid4().hex
    key = domain_id or "__no_domain__"
    with _interference_lock:
        peers = _active_by_domain[key]
        if peers:
            # We overlap everyone already here, and they overlap us.
            _overlapped_tokens.add(token)
            _overlapped_tokens.update(peers)
        peers.add(token)

    def overlapped() -> bool:
        with _interference_lock:
            return token in _overlapped_tokens

    try:
        yield overlapped
    finally:
        with _interference_lock:
            _active_by_domain[key].discard(token)
            if not _active_by_domain[key]:
                del _active_by_domain[key]
            _overlapped_tokens.discard(token)


class Polarity(Enum):
    ADD = "add"
    DELETE = "delete"


class EffectVerdict(Enum):
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class RuntimeOutcome(Enum):
    CONFIRMATION = "runtime_confirmation"
    CONTRADICTION = "runtime_contradiction"
    INDETERMINATE = "runtime_indeterminate"


@dataclass(frozen=True)
class ToolObservation:
    """The canonical reading of one tool invocation and the world after it.

    `facts` is what the world was observed to contain, not what the tool said
    about itself. `observed` records whether the world could be inspected at
    all -- without it, an empty fact set is indistinguishable from an empty
    world, and every delete effect would read as confirmed.
    """

    observation_id: str
    tool_name: str
    invoked: bool
    tool_reported_success: bool
    observed: bool
    facts: FrozenSet[Fact] = frozenset()
    #: The world before the action. Required to judge a prediction that names
    #: no particular value: "reading produces some text" is confirmed by text
    #: that appeared, and by text that was already lying there it is not
    #: confirmed at all.
    before: Optional[FrozenSet[Fact]] = None
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def contains(self, fact: Fact) -> Optional[bool]:
        """Whether the world holds this, or holds something matching it.

        A GROUND prediction is exact membership. A prediction carrying a
        variable is one the rule made without claiming which value would
        appear -- what a file holds, what a request returns -- and it is
        satisfied by anything matching it. Exact membership judged those false
        against every world, so a rule that said only "acting produces a value"
        was contradicted by the value appearing.

        Such a prediction is judged against what CHANGED, and where the world
        before the action was not supplied it is left UNKNOWN: text that was
        already there confirms nothing about the read.
        """
        if not self.observed:
            return None
        if fact.is_ground:
            return fact in self.facts
        if self.before is None:
            return None
        return bool(match_literal(fact, self.facts - self.before))


@dataclass(frozen=True)
class EffectVerification:
    predicted_effect: Fact
    polarity: Polarity
    verdict: EffectVerdict
    observation_id: str
    evidence_root_id: Optional[str] = None
    detail: str = ""


@dataclass
class RuntimeEvidence:
    """What executing this operator established about the rule behind it."""

    outcome: RuntimeOutcome
    rule_id: Optional[str]
    operator: str
    observation_id: str
    verifications: List[EffectVerification] = field(default_factory=list)
    detail: str = ""

    @property
    def confirmed(self) -> List[EffectVerification]:
        return [v for v in self.verifications if v.verdict is EffectVerdict.CONFIRMED]

    @property
    def contradicted(self) -> List[EffectVerification]:
        return [v for v in self.verifications if v.verdict is EffectVerdict.CONTRADICTED]

    @property
    def unknown(self) -> List[EffectVerification]:
        return [v for v in self.verifications if v.verdict is EffectVerdict.UNKNOWN]


def verify_effects(
    effects: RuleEffects,
    observation: ToolObservation,
    rule_id: Optional[str] = None,
    operator: str = "",
    evidence_root_id: Optional[str] = None,
) -> RuntimeEvidence:
    """Compare each predicted effect against the observed world, independently."""
    verifications: List[EffectVerification] = []

    for fact in sorted(effects.add):
        present = observation.contains(fact)
        verifications.append(EffectVerification(
            predicted_effect=fact, polarity=Polarity.ADD,
            verdict=(EffectVerdict.UNKNOWN if present is None
                     else EffectVerdict.CONFIRMED if present
                     else EffectVerdict.CONTRADICTED),
            observation_id=observation.observation_id,
            evidence_root_id=evidence_root_id,
            detail=("world not observable" if present is None
                    else "" if present else "predicted addition is absent"),
        ))

    for fact in sorted(effects.delete):
        present = observation.contains(fact)
        verifications.append(EffectVerification(
            predicted_effect=fact, polarity=Polarity.DELETE,
            verdict=(EffectVerdict.UNKNOWN if present is None
                     else EffectVerdict.CONTRADICTED if present
                     else EffectVerdict.CONFIRMED),
            observation_id=observation.observation_id,
            evidence_root_id=evidence_root_id,
            detail=("world not observable" if present is None
                    else "predicted retraction did not happen" if present else ""),
        ))

    outcome = _outcome(verifications, observation)
    evidence = RuntimeEvidence(
        outcome=outcome, rule_id=rule_id, operator=operator,
        observation_id=observation.observation_id, verifications=verifications,
    )
    evidence.detail = _describe(evidence, observation)
    return evidence


def _outcome(
    verifications: Sequence[EffectVerification], observation: ToolObservation
) -> RuntimeOutcome:
    if not observation.invoked:
        return RuntimeOutcome.INDETERMINATE
    if any(v.verdict is EffectVerdict.CONTRADICTED for v in verifications):
        return RuntimeOutcome.CONTRADICTION
    if not verifications:
        # Nothing was predicted, so nothing was established. A tool that ran
        # successfully still says nothing about an action model with no claims.
        return RuntimeOutcome.INDETERMINATE
    if all(v.verdict is EffectVerdict.CONFIRMED for v in verifications):
        return RuntimeOutcome.CONFIRMATION
    return RuntimeOutcome.INDETERMINATE


def _describe(evidence: RuntimeEvidence, observation: ToolObservation) -> str:
    if not observation.invoked:
        return f"operator was not invoked: {observation.error or 'no reason recorded'}"
    if not observation.observed:
        return (
            f"{observation.tool_name} reported "
            f"{'success' if observation.tool_reported_success else 'failure'}, but the "
            f"world could not be observed, so the predicted effects are unverified"
        )
    parts = []
    if evidence.contradicted:
        parts.append("contradicted: " + ", ".join(
            f"{v.polarity.value} {v.predicted_effect}" for v in evidence.contradicted))
    if evidence.confirmed:
        parts.append(f"{len(evidence.confirmed)} effect(s) confirmed")
    if evidence.unknown:
        parts.append(f"{len(evidence.unknown)} unobservable")
    return "; ".join(parts)


class Attribution(Enum):
    """What a prediction mismatch is evidence ABOUT.

    A contradiction establishes that the world disagreed with the prediction.
    It does not, by itself, establish that the learned rule is wrong. The
    mismatch is equally consistent with a wrong tool binding, a failed
    actuator, an untrustworthy observer, concurrent change by something else,
    or the wrong entity being watched.

    Charging the rule for any of those is the infrastructure-poisoning failure
    the credit invariant already forbids elsewhere: a strategy must never be
    debited for an infrastructure failure. Only RULE_EVIDENCE may reach the
    rule store.
    """

    RULE_EVIDENCE = "rule_evidence"
    EXECUTION_FAILURE = "execution_failure"
    EXTERNAL_FAILURE = "external_failure"
    INDETERMINATE = "indeterminate"


@dataclass
class AttributionContext:
    """The conditions that must independently hold for a mismatch to count
    against the learned action model."""

    preconditions_observed: bool = False
    rule_validated_at_execution: bool = False
    action_matches_rule: bool = False
    arguments_verified: bool = False
    invocation_occurred: bool = False
    observer_available: bool = False
    post_state_observed: bool = False
    external_interference: bool = False

    def unmet(self) -> List[str]:
        required = {
            "preconditions_observed": self.preconditions_observed,
            "rule_validated_at_execution": self.rule_validated_at_execution,
            "action_matches_rule": self.action_matches_rule,
            "arguments_verified": self.arguments_verified,
            "invocation_occurred": self.invocation_occurred,
            "observer_available": self.observer_available,
            "post_state_observed": self.post_state_observed,
        }
        missing = [name for name, held in required.items() if not held]
        if self.external_interference:
            missing.append("external_interference_present")
        return missing


def attribute(
    evidence: RuntimeEvidence, context: AttributionContext
) -> Tuple[Attribution, str]:
    """Decide what this runtime outcome is evidence about.

    Fails toward INDETERMINATE. An unattributable mismatch is a real epistemic
    state, and recording it as rule evidence would let the substrate revise a
    correct rule because a tool was misbound.
    """
    if evidence.outcome is RuntimeOutcome.INDETERMINATE:
        return Attribution.INDETERMINATE, evidence.detail or "nothing was established"

    unmet = context.unmet()
    if not unmet:
        return (
            Attribution.RULE_EVIDENCE,
            "every authority condition held independently, so the world's "
            "disagreement is about the action model",
        )

    if not context.invocation_occurred or not context.arguments_verified \
            or not context.action_matches_rule:
        return (
            Attribution.EXECUTION_FAILURE,
            f"the action was not carried out as the rule specifies: {unmet}",
        )
    if not context.observer_available or not context.post_state_observed:
        return (
            Attribution.INDETERMINATE,
            f"the world could not be read well enough to judge: {unmet}",
        )
    if context.external_interference:
        return (
            Attribution.EXTERNAL_FAILURE,
            "the world was changed by something other than this action",
        )
    return Attribution.INDETERMINATE, f"unresolved conditions: {unmet}"


def outcome_class_for(evidence: RuntimeEvidence, attribution: Attribution):
    """State this runtime outcome in the vocabulary the credit system uses.

    `OutcomeClass` already answers "why did this end the way it did", and the
    credit invariant is already defined over it. Restating that judgement in a
    second taxonomy would give the substrate two answers to the same question,
    so this translates rather than re-decides.

    The mapping that matters: an attributable contradiction is a
    STRATEGY_FAILURE -- the approach was wrong and we are still in control --
    which is precisely the condition appraisal turns into replan pressure. A
    contradiction that could not be charged to the rule maps to whatever
    actually failed, so nothing punishes the strategy for a broken tool.
    """
    from core.learning.meta_learning import OutcomeClass

    if attribution is Attribution.EXECUTION_FAILURE:
        return OutcomeClass.EXECUTION_FAILURE
    if attribution is Attribution.EXTERNAL_FAILURE:
        return OutcomeClass.EXTERNAL_FAILURE
    if attribution is Attribution.INDETERMINATE:
        return OutcomeClass.INDETERMINATE
    if evidence.outcome is RuntimeOutcome.CONFIRMATION:
        return OutcomeClass.SUCCESS
    if evidence.outcome is RuntimeOutcome.CONTRADICTION:
        return OutcomeClass.STRATEGY_FAILURE
    return OutcomeClass.INDETERMINATE
