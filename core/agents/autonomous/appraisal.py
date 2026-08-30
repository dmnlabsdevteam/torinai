#!/usr/bin/env python3
"""
AppraisalState — the single authority converting signals into disposition.

WHY THIS EXISTS
---------------
Before this module, each consumer interpreted raw signals for itself. The first
such coupling was `_experience_pressure()` inside `_calculate_curiosity`, which
read the sign of accumulated reward and raised curiosity when it was negative.
That coupling PROVED experience can change behaviour, and it is kept as a
regression invariant — but it is not a defensible policy, because negative
experience is ambiguous:

    failure + uncertainty + alternatives available   -> explore
    failure + confident the approach is wrong        -> replan
    failure + low competence + high consequence      -> caution
    repeated failure + no control + no information   -> disengage / escalate
    failure + high information gain                  -> continue anyway

The sign of one scalar cannot distinguish those. AppraisalState exists so that
interpretation happens ONCE, with context, rather than N times in N consumers.

WHAT IT IS NOT
--------------
Not a store of named emotions. eagerness / doubt / frustration / satisfaction
are DERIVED properties of the low-dimensional variables below, never primitives.
Storing them would create the duplicate-authority defect this module prevents.

Every field is sourced from something already measured elsewhere. Where a signal
is genuinely unavailable it is None — never imputed to a middling default, so
"unmeasured" stays distinguishable from "measured and neutral".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> Optional[float]:
    """Clamp, preserving None. None means UNMEASURED, not zero."""
    if value is None:
        return None
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return None


def _known(*values: Optional[float]) -> List[float]:
    return [v for v in values if v is not None]


def _mean(values: List[float], default: Optional[float] = None) -> Optional[float]:
    return (sum(values) / len(values)) if values else default


@dataclass
class AppraisalState:
    """How the system currently stands toward its situation.

    Core variables are deliberately few and low-dimensional. Behavioural
    pressures are derived from them CONTEXTUALLY — never from the sign of any
    single input.
    """

    # ── Core appraisal variables ────────────────────────────────────────────
    valence: Optional[float] = None            # [-1,1] experience broadly good/bad
    activation: Optional[float] = None         # [0,1] how strongly state should act
    confidence: Optional[float] = None         # [0,1] confidence in current model
    epistemic_opportunity: Optional[float] = None  # [0,1] value of learning more
    progress: Optional[float] = None           # [0,1] movement toward objective
    controllability: Optional[float] = None    # [0,1] can our actions affect the outcome?
    competence: Optional[float] = None         # [0,1] estimated capability here

    # Is where we are moving actually where we need to go? DISTINCT from
    # progress: efficiently optimising the wrong subproblem is high progress
    # with low congruence; necessary investigation is the reverse.
    goal_congruence: Optional[float] = None    # [0,1]

    # "Did I have meaningful choice?" — NOT controllability. Many useless
    # options is high agency + low controllability; one authorised action that
    # reliably works is the reverse.
    agency: Optional[float] = None             # [0,1]

    # How costly would being wrong be? This is what stops curiosity becoming
    # recklessness in security / infrastructure / device-control domains.
    risk: Optional[float] = None               # [0,1]

    # WHY it ended this way. Structured, not a float — reuses OutcomeClass,
    # which already encodes the credit invariant (only some classes may move a
    # posterior). Identical failures with different causes must appraise
    # differently.
    attribution: Optional[str] = None
    attribution_confidence: Optional[float] = None

    # ── Derived behavioural pressures ───────────────────────────────────────
    approach_pressure: float = 0.0
    avoidance_pressure: float = 0.0
    exploration_pressure: float = 0.0
    persistence_pressure: float = 0.0
    replan_pressure: float = 0.0      # the approach is wrong, not the situation
    escalation_pressure: float = 0.0  # we cannot fix this from here
    caution_pressure: float = 0.0     # proceed, but verify more

    # ── Provenance ──────────────────────────────────────────────────────────
    sources: Dict[str, Any] = field(default_factory=dict)
    unmeasured: List[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)

    # ------------------------------------------------------------------
    # Derived interpretations — NOT stored state
    # ------------------------------------------------------------------
    @property
    def eagerness(self) -> Optional[float]:
        """Positive valence + activation + controllability + competence."""
        parts = _known(self._pos(self.valence), self.activation,
                       self.goal_congruence, self.controllability)
        return _mean(parts)

    @property
    def doubt(self) -> Optional[float]:
        """Uncertainty about the current model: low confidence, high open questions."""
        parts = _known(
            None if self.confidence is None else 1.0 - self.confidence,
            self.epistemic_opportunity,
            self.risk,          # being wrong matters more when it costs more
        )
        return _mean(parts)

    @property
    def frustration(self) -> Optional[float]:
        """Negative valence + effort + low progress + control that SHOULD work.

        Requires controllability: being unable to affect an outcome you never
        controlled is not frustration, it is irrelevance.
        """
        # Controllability MULTIPLIES rather than averages. Averaging let a
        # stalled, uncontrollable task read as highly frustrated — but being
        # unable to move something you never controlled is not frustration.
        core = _mean(_known(
            self._neg(self.valence),
            None if self.progress is None else 1.0 - self.progress,
        ))
        if core is None:
            return None
        if self.controllability is None:
            return core
        return core * self.controllability

    @property
    def satisfaction(self) -> Optional[float]:
        """Positive valence + progress + competence."""
        return _mean(_known(self._pos(self.valence), self.progress, self.competence))

    @staticmethod
    def _pos(v: Optional[float]) -> Optional[float]:
        return None if v is None else max(0.0, v)

    @staticmethod
    def _neg(v: Optional[float]) -> Optional[float]:
        return None if v is None else max(0.0, -v)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valence": self.valence,
            "activation": self.activation,
            "confidence": self.confidence,
            "epistemic_opportunity": self.epistemic_opportunity,
            "progress": self.progress,
            "controllability": self.controllability,
            "competence": self.competence,
            "goal_congruence": self.goal_congruence,
            "agency": self.agency,
            "risk": self.risk,
            "attribution": self.attribution,
            "approach_pressure": round(self.approach_pressure, 4),
            "avoidance_pressure": round(self.avoidance_pressure, 4),
            "exploration_pressure": round(self.exploration_pressure, 4),
            "persistence_pressure": round(self.persistence_pressure, 4),
            "replan_pressure": round(self.replan_pressure, 4),
            "escalation_pressure": round(self.escalation_pressure, 4),
            "caution_pressure": round(self.caution_pressure, 4),
            "derived": {
                "eagerness": self.eagerness,
                "doubt": self.doubt,
                "frustration": self.frustration,
                "satisfaction": self.satisfaction,
            },
            "unmeasured": list(self.unmeasured),
            "updated_at": self.updated_at.isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════
# Construction from real signals
# ══════════════════════════════════════════════════════════════════════════

# How fast the fast-moving appraisal forgets. Experience leaves a permanent
# trace in the slow baseline (accumulated_event_reward, persisted); affect
# itself has inertia but RECOVERS, so one bad week cannot permanently bias
# disposition.
APPRAISAL_DECAY = 0.6   # weight on the incoming appraisal vs the previous one


def build_appraisal(
    *,
    outcome_quality: Optional[float] = None,
    intrinsic_reward: Optional[float] = None,
    motivation_state: Optional[Dict[str, Any]] = None,
    epistemic: Optional[Dict[str, Any]] = None,
    performance_stats: Optional[Dict[str, Any]] = None,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    action_success_rate: Optional[float] = None,
    is_stagnant: Optional[bool] = None,
    goal_alignment_score: Optional[float] = None,
    risk_level: Optional[str] = None,
    outcome_class: Optional[Any] = None,
    options_considered: Optional[int] = None,
    self_initiated: Optional[bool] = None,
    previous: Optional[AppraisalState] = None,
) -> AppraisalState:
    """Compose an AppraisalState from signals other subsystems already measured.

    Nothing here recomputes a quantity that has an owner elsewhere:
      outcome_quality / intrinsic_reward  <- ExperienceEvaluator
      activation                          <- IntrinsicMotivationSystem total_reward
      epistemic_*                         <- summarize_epistemic_mutations
      competence                          <- get_domain_performance_stats
      progress                            <- IterationBudget.is_stagnant
    """
    unmeasured: List[str] = []
    sources: Dict[str, Any] = {}

    # ── VALENCE: how good/bad was this, extrinsically AND intrinsically ─────
    # Both are real and can disagree — an operationally poor outcome that
    # taught the system a lot is genuinely mixed, and averaging preserves that
    # rather than letting either erase the other.
    _extrinsic = None
    if outcome_quality is not None:
        _extrinsic = (_clamp(outcome_quality) * 2.0) - 1.0   # [0,1] -> [-1,1]
    _intrinsic = _clamp(intrinsic_reward, -1.0, 1.0)          # already signed
    valence = _mean(_known(_extrinsic, _intrinsic))
    if valence is None:
        unmeasured.append("valence")
    sources["valence"] = {"extrinsic": _extrinsic, "intrinsic": _intrinsic}

    # ── ACTIVATION: drive level already computed by the motivation system ───
    activation = None
    if motivation_state:
        activation = _clamp(motivation_state.get("total_reward"))
    if activation is None:
        unmeasured.append("activation")

    # ── EPISTEMIC OPPORTUNITY + CONFIDENCE ─────────────────────────────────
    epistemic = epistemic or {}
    _gain = _clamp(epistemic.get("information_gain"))
    _reduction = _clamp(epistemic.get("uncertainty_reduction"))
    _increase = _clamp(epistemic.get("uncertainty_increase"))

    # Opportunity = there is something here worth learning. Recent gain shows
    # the vein is productive; rising uncertainty means open questions remain.
    epistemic_opportunity = _mean(_known(_gain, _increase))
    if epistemic_opportunity is None:
        unmeasured.append("epistemic_opportunity")

    # Confidence in the current model. Uncertainty REDUCED raises it;
    # uncertainty INTRODUCED lowers it. Absent evidence leaves it unmeasured
    # rather than asserting a confident 0.5.
    if _reduction is None and _increase is None:
        confidence = None
        unmeasured.append("confidence")
    else:
        confidence = _clamp(0.5 + 0.5 * ((_reduction or 0.0) - (_increase or 0.0)))

    # ── COMPETENCE: measured per-domain success, not a guess ───────────────
    # Raw success_rate is an OBSERVATION, not a competence estimate — 1/1 and
    # 8/9 both read "high" on wildly different support. Until a real estimator
    # exists this uses the ratio, but only when there is enough sample for the
    # number to mean anything; below that it stays UNMEASURED rather than
    # asserting mastery (or incompetence) from one or two tasks.
    MIN_ATTEMPTS_FOR_COMPETENCE = 5
    competence = None
    if performance_stats and performance_stats.get("measured"):
        _attempts = int(performance_stats.get("total_attempts", 0) or 0)
        if _attempts >= MIN_ATTEMPTS_FOR_COMPETENCE:
            competence = _clamp(performance_stats.get("success_rate"))
        else:
            sources["competence"] = {
                "withheld": "insufficient_sample",
                "attempts": _attempts,
                "empirical_success_rate": performance_stats.get("success_rate"),
            }
    if competence is None:
        unmeasured.append("competence")

    # ── PROGRESS: owned by IterationBudget.is_stagnant() ───────────────────
    if is_stagnant is None:
        progress = None
        unmeasured.append("progress")
    else:
        progress = 0.0 if is_stagnant else 1.0

    # ── CONTROLLABILITY: do our actions actually change anything? ──────────
    # No existing owner, so it is derived here from two real observations:
    # whether tools succeed at all, and whether acting moves the epistemic
    # state. An agent whose actions neither succeed nor change what it knows
    # is not in control of the situation.
    # Prefer a pre-computed efficacy rate: production callers pass the canonical
    # value rather than handing this module raw execution records to interpret.
    controllability = None
    _tool_success = _clamp(action_success_rate)
    _acted = [r for r in (tool_results or []) if r.get("tool")]
    if _tool_success is None and _acted:
        _tool_success = sum(1 for r in _acted if r.get("success")) / len(_acted)
    if _tool_success is not None:
        _moved = None if (_gain is None) else _gain
        controllability = _mean(_known(_tool_success, _moved))
        sources["controllability"] = {
            "action_success_rate": round(_tool_success, 4),
            "epistemic_movement": _moved,
        }
    if controllability is None:
        unmeasured.append("controllability")

    # ── GOAL CONGRUENCE: owned by the verification system ──────────────────
    # CompletionScore.goal_alignment_score already measures "does the output
    # match the task objective". Distinct from progress.
    goal_congruence = _clamp(goal_alignment_score)
    if goal_congruence is None:
        unmeasured.append("goal_congruence")

    # ── RISK: cost of being wrong. Governance/task criticality owns the level.
    _RISK = {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 0.95}
    risk = _RISK.get(str(risk_level).lower()) if risk_level is not None else None
    if risk is None:
        unmeasured.append("risk")

    # ── AGENCY: meaningful choice, NOT effectiveness of choice ─────────────
    _agency_terms = []
    if options_considered is not None:
        # One option is no choice; choice saturates quickly after that.
        _agency_terms.append(_clamp(min(1.0, max(0, options_considered - 1) / 3.0)))
    if self_initiated is not None:
        _agency_terms.append(1.0 if self_initiated else 0.0)
    agency = _mean(_known(*_agency_terms))
    if agency is None:
        unmeasured.append("agency")

    # ── CAUSAL ATTRIBUTION: reuse OutcomeClass, do not redefine it ──────────
    attribution = None
    if outcome_class is not None:
        attribution = getattr(outcome_class, "value", str(outcome_class))
    if attribution is None:
        unmeasured.append("attribution")

    state = AppraisalState(
        goal_congruence=goal_congruence,
        agency=agency,
        risk=risk,
        attribution=attribution,
        valence=valence,
        activation=activation,
        confidence=confidence,
        epistemic_opportunity=epistemic_opportunity,
        progress=progress,
        controllability=controllability,
        competence=competence,
        sources=sources,
        unmeasured=unmeasured,
    )

    _derive_pressures(state)

    if previous is not None:
        state = _blend(previous, state)
        _derive_pressures(state)

    return state


def _derive_pressures(s: AppraisalState) -> None:
    """Contextual behavioural tendencies.

    The SAME negative valence produces different pressure depending on context,
    and — critically — on WHY it happened. Attribution is not decoration: an
    identical failure caused by a bad strategy, an API outage, or a safety block
    demands three different responses.

    An unmeasured variable contributes nothing and is excluded from the
    normaliser, so a missing signal never silently reads as zero.
    """
    neg = AppraisalState._neg(s.valence)
    pos = AppraisalState._pos(s.valence)
    attr = s.attribution

    # Attribution classes that mean "the situation, not our approach".
    _external = attr in ("infrastructure_failure", "external_failure")
    _strategy = attr == "strategy_failure"
    _blocked = attr == "safety_blocked"

    # EXPLORATION: something to learn AND the ability to act on it.
    # Dissatisfaction amplifies; it never creates. RISK damps it — this is what
    # keeps curiosity from becoming recklessness.
    _explore_terms = _known(s.epistemic_opportunity, s.controllability)
    if _explore_terms:
        base = _mean(_explore_terms) or 0.0
        base *= (1.0 + 0.5 * (neg or 0.0))
        if s.risk is not None:
            base *= (1.0 - 0.6 * s.risk)
        if _external or _blocked:
            base *= 0.4      # nothing here is ours to explore
        s.exploration_pressure = _clamp(base) or 0.0
    else:
        s.exploration_pressure = 0.0

    # PERSISTENCE: the current line is working. Deliberately NOT a function of
    # valence sign — a painful but progressing, goal-congruent task deserves
    # persistence.
    _persist = _known(s.progress, s.competence, s.controllability, s.goal_congruence)
    persist = _mean(_persist) or 0.0
    if _strategy:
        persist *= 0.4       # persisting with a strategy known to be the fault
    s.persistence_pressure = _clamp(persist) or 0.0

    # REPLAN: our approach is the problem — we still have control, the goal is
    # still worth having, but this route is wrong.
    if neg is not None and _strategy:
        _r = _known(s.controllability, s.goal_congruence, s.agency)
        s.replan_pressure = _clamp(neg * (_mean(_r) if _r else 1.0)) or 0.0
    elif neg is not None and s.goal_congruence is not None and s.progress is not None:
        # Moving, but not toward the objective.
        s.replan_pressure = _clamp(neg * s.progress * (1.0 - s.goal_congruence)) or 0.0
    else:
        s.replan_pressure = 0.0

    # ESCALATION: cannot be fixed from here. Low control, cause outside us.
    if neg is not None:
        _e = []
        if s.controllability is not None:
            _e.append(1.0 - s.controllability)
        if _external or _blocked:
            _e.append(1.0)
        elif attr is not None:
            _e.append(0.0)
        s.escalation_pressure = _clamp(neg * (_mean(_e) if _e else 0.0)) or 0.0
    else:
        s.escalation_pressure = 0.0

    # CAUTION: proceed, but verify more. Driven by consequence and doubt, NOT
    # by valence — a high-risk task deserves caution even when going well.
    _c = _known(
        s.risk,
        None if s.confidence is None else 1.0 - s.confidence,
        None if s.competence is None else 1.0 - s.competence,
    )
    s.caution_pressure = (_mean(_c) or 0.0)

    # AVOIDANCE: back off. Rises with negative valence in proportion to the
    # reasons to retreat. Infrastructure/external causes must NOT read as a
    # reason to avoid the task itself — that is what escalation is for.
    _risk_terms = _known(
        None if s.controllability is None else 1.0 - s.controllability,
        None if s.competence is None else 1.0 - s.competence,
        None if s.progress is None else 1.0 - s.progress,
    )
    if _risk_terms and neg is not None:
        avoid = neg * (_mean(_risk_terms) or 0.0)
        if _external:
            avoid *= 0.3     # not the task's fault; don't learn to fear it
        s.avoidance_pressure = _clamp(avoid) or 0.0
    else:
        s.avoidance_pressure = 0.0

    # APPROACH: positive valence backed by capability, control and alignment.
    _approach = _known(pos, s.competence, s.controllability, s.goal_congruence,
                       s.activation)
    s.approach_pressure = (_mean(_approach) or 0.0)


def _blend(previous: AppraisalState, incoming: AppraisalState) -> AppraisalState:
    """Two timescales: affect has inertia but recovers.

    The slow, persistent trace lives in the motivation profile
    (accumulated_event_reward, restored from the database). THIS state is the
    fast-moving layer: it carries recent history forward but decays toward the
    present, so a bad stretch biases disposition temporarily rather than
    permanently.
    """
    def mix(old: Optional[float], new: Optional[float]) -> Optional[float]:
        if new is None:
            return old          # unmeasured now -> keep what we had
        if old is None:
            return new
        return APPRAISAL_DECAY * new + (1.0 - APPRAISAL_DECAY) * old

    return AppraisalState(
        valence=mix(previous.valence, incoming.valence),
        activation=mix(previous.activation, incoming.activation),
        confidence=mix(previous.confidence, incoming.confidence),
        epistemic_opportunity=mix(previous.epistemic_opportunity,
                                  incoming.epistemic_opportunity),
        progress=mix(previous.progress, incoming.progress),
        controllability=mix(previous.controllability, incoming.controllability),
        competence=mix(previous.competence, incoming.competence),
        goal_congruence=mix(previous.goal_congruence, incoming.goal_congruence),
        agency=mix(previous.agency, incoming.agency),
        risk=mix(previous.risk, incoming.risk),
        # Attribution is a fact about the LAST outcome, never smoothed.
        attribution=incoming.attribution,
        sources=incoming.sources,
        unmeasured=incoming.unmeasured,
    )


# ══════════════════════════════════════════════════════════════════════════
# Canonical home — ONE producer, many consumers
# ══════════════════════════════════════════════════════════════════════════

class AppraisalSystem:
    """The single owner of current appraisal.

    Consumers read `current_state`; they do NOT call build_appraisal() again
    from slightly different inputs. Recomputing per-consumer is exactly the
    duplicate-authority defect removed everywhere else in this substrate.

    Two timescales are preserved: `current_state` is fast-moving and decaying
    (reconstructable), while `history` is the durable record of appraisal
    events. The slow experiential baseline lives in the motivation profile's
    persisted accumulated_event_reward, not here.
    """

    HISTORY_MAX = 200

    def __init__(self) -> None:
        self.current_state: Optional[AppraisalState] = None
        self.history: List[Dict[str, Any]] = []

    def update(self, **signals) -> AppraisalState:
        """Produce the next appraisal, blended onto the current one."""
        state = build_appraisal(previous=self.current_state, **signals)
        self.current_state = state
        self.history.append(state.to_dict())
        if len(self.history) > self.HISTORY_MAX:
            del self.history[: -self.HISTORY_MAX]
        return state


_appraisal_system: Optional[AppraisalSystem] = None


def get_appraisal_system() -> AppraisalSystem:
    global _appraisal_system
    if _appraisal_system is None:
        _appraisal_system = AppraisalSystem()
    return _appraisal_system
