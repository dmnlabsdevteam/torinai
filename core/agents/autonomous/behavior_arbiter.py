#!/usr/bin/env python3
"""
BehaviorArbiter — turns disposition into a decision for THIS situation.

    AppraisalState        "how I stand toward things"      (recommends)
          ↓
    BehaviorArbiter       "what that means right now"      (decides)
          ↓
    BehavioralDirective   consumed by existing control points

The arbiter consumes appraisal PRESSURES. It never re-reads the underlying
evidence — that interpretation already happened once, in AppraisalState.

Governance and safety sit ABOVE this. Caution is not permission: the arbiter
only decides how conservatively to operate inside space already permitted, and
never widens what is allowed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# A pressure must clear this to change behaviour, so noise near zero does not
# produce twitchy mode-switching.
ACT_THRESHOLD = 0.35


@dataclass
class BehavioralDirective:
    """What to do next, and why."""

    mode: str = "proceed"

    exploration: float = 0.0
    persistence: float = 0.0
    replan: float = 0.0
    escalation: float = 0.0
    caution: float = 0.0
    avoidance: float = 0.0

    should_explore: bool = False
    should_replan: bool = False
    should_escalate: bool = False

    max_goals: int = 1
    verification_intensity: float = 0.5

    reason_codes: List[str] = field(default_factory=list)
    appraisal: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "should_explore": self.should_explore,
            "should_replan": self.should_replan,
            "should_escalate": self.should_escalate,
            "max_goals": self.max_goals,
            "verification_intensity": round(self.verification_intensity, 4),
            "reason_codes": list(self.reason_codes),
        }


class BehaviorArbiter:
    """Decides how disposition applies to the current situation."""

    def decide(
        self,
        appraisal: Optional[Any],
        *,
        slots_available: int = 1,
        queue_pressure: str = "nominal",
    ) -> BehavioralDirective:
        d = BehavioralDirective()

        if appraisal is None:
            # No appraisal yet is NOT a reason to act boldly or to freeze.
            # Proceed with the system's neutral default and say so.
            d.reason_codes.append("no_appraisal")
            d.max_goals = max(1, min(slots_available, 1))
            return d

        d.exploration = appraisal.exploration_pressure
        d.persistence = appraisal.persistence_pressure
        d.replan = appraisal.replan_pressure
        d.escalation = appraisal.escalation_pressure
        d.caution = appraisal.caution_pressure
        d.avoidance = appraisal.avoidance_pressure
        d.appraisal = {
            "valence": appraisal.valence,
            "attribution": appraisal.attribution,
            "risk": appraisal.risk,
        }

        # ── mode: the single dominant response ──────────────────────────────
        ranked = sorted(
            (
                ("escalate", d.escalation),
                ("replan", d.replan),
                ("explore", d.exploration),
                ("persist", d.persistence),
                ("avoid", d.avoidance),
            ),
            key=lambda kv: kv[1],
            reverse=True,
        )
        top_name, top_value = ranked[0]
        d.mode = top_name if top_value >= ACT_THRESHOLD else "proceed"
        d.reason_codes.append(f"dominant:{top_name}:{top_value:.2f}")

        d.should_escalate = d.escalation >= ACT_THRESHOLD
        d.should_replan = d.replan >= ACT_THRESHOLD

        # ── exploration admission ───────────────────────────────────────────
        # Escalation means the blocker is outside us; thrashing through more
        # self-directed exploration is the wrong response and wastes the queue.
        d.should_explore = (
            d.exploration >= ACT_THRESHOLD
            and not d.should_escalate
            and slots_available > 0
            and queue_pressure == "nominal"
        )
        if d.should_escalate and d.exploration >= ACT_THRESHOLD:
            d.reason_codes.append("exploration_suppressed_by_escalation")
        if queue_pressure != "nominal":
            d.reason_codes.append(f"queue_pressure:{queue_pressure}")

        # Breadth scales with exploration pressure and is capped by real slots.
        d.max_goals = max(1, min(slots_available, int(round(d.exploration * 3)))) \
            if d.should_explore else 0

        # ── verification intensity ──────────────────────────────────────────
        # Caution buys evidence, not permission.
        d.verification_intensity = min(1.0, 0.5 + 0.5 * d.caution)
        if d.caution >= ACT_THRESHOLD:
            d.reason_codes.append(f"elevated_verification:{d.verification_intensity:.2f}")

        return d


_arbiter: Optional[BehaviorArbiter] = None


def get_behavior_arbiter() -> BehaviorArbiter:
    global _arbiter
    if _arbiter is None:
        _arbiter = BehaviorArbiter()
    return _arbiter
