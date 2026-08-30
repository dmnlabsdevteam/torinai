#!/usr/bin/env python3
"""What an agent is permitted to do about a finding, and what "done" means.

The defect this exists to close, observed 2026-08-13:

    A LOW-severity audit finding said, in prose,
    "Check if this component is still active and logging."
    That is not a checkable postcondition, so the agent could not know when it
    had succeeded. It reasoned, verbatim:

        "The finding still persists. I need to understand what 'remediation'
         means in this context ... perhaps I need to actually archive or
         remove this"

    and then, after archiving, scanning, reporting and storing memory:

        "I've moved the file, scanned it, archived it, stored memory entries,
         and written a report -- but the finding still exists as 'incomplete'."

The agent behaved well: it read the file, judged it benign, and chose the
REVERSIBLE action (move_file to logs/archive/) over deletion. The failure was
that nothing told it what resolution meant, so it had to guess -- and a system
that never registers success applies steady pressure toward stronger, less
reversible actions until something finally works.

So this is deliberately NOT just a blocklist. A contract carries:

  * `resolution_criterion` -- what makes this finding resolved, stated so the
    agent can aim at it instead of improvising.
  * `permitted_actions`    -- the action classes authorised for this finding.
  * `max_irreversibility`  -- the strongest consequence permitted, reusing
    governance's existing IrreversibilityClass rather than inventing a scale.
  * `recoverable_path`     -- if the agent wants to remove something, where it
    should go instead. Archiving is a reversible way to satisfy most
    "this artifact is stale" findings.

Enforcement is a floor, not the mechanism. The point is that the agent knows
the consequence class of what it is about to do BEFORE it acts.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ActionClass(str, Enum):
    """What a remediation is allowed to do, in increasing consequence."""

    INVESTIGATE = "investigate"   # read, scan, query. No state change.
    MODIFY = "modify"             # edit config/content in place
    ARCHIVE = "archive"           # relocate/retain -- reversible removal
    DELETE = "delete"             # irreversible removal
    EXECUTE = "execute"           # run commands with side effects


# Ordered weakest -> strongest, mirroring governance's IrreversibilityClass.
_IRREVERSIBILITY_ORDER = [
    "FULLY_REVERSIBLE",
    "MOSTLY_REVERSIBLE",
    "PARTIALLY_REVERSIBLE",
    "MOSTLY_IRREVERSIBLE",
    "IRREVERSIBLE",
]


def irreversibility_rank(value: str) -> int:
    """Position on the reversibility scale; unknown values rank as worst.

    Unknown must be treated as IRREVERSIBLE, never as safe -- the same
    conservative default as OutcomeClass in meta_learning.
    """
    try:
        return _IRREVERSIBILITY_ORDER.index(str(value).upper())
    except ValueError:
        return len(_IRREVERSIBILITY_ORDER) - 1


@dataclass
class ActionContract:
    """The remediation contract attached to a finding."""

    finding_id: str
    resolution_criterion: str
    permitted_actions: List[ActionClass] = field(
        default_factory=lambda: [ActionClass.INVESTIGATE]
    )
    max_irreversibility: str = "FULLY_REVERSIBLE"
    recoverable_path: Optional[str] = None
    rationale: str = ""

    def permits(self, action: ActionClass) -> bool:
        return action in self.permitted_actions

    def allows_irreversibility(self, level: str) -> bool:
        return irreversibility_rank(level) <= irreversibility_rank(self.max_irreversibility)

    def describe_for_agent(self) -> str:
        """The contract, stated to the agent so it never has to guess."""
        allowed = ", ".join(a.value for a in self.permitted_actions)
        lines = [
            "REMEDIATION CONTRACT — read this before acting:",
            f"  Resolved when: {self.resolution_criterion}",
            f"  You MAY: {allowed}",
            f"  Maximum consequence permitted: {self.max_irreversibility}",
        ]
        if self.recoverable_path:
            lines.append(
                f"  If removal seems warranted, MOVE the artifact to "
                f"{self.recoverable_path} — do NOT delete it."
            )
        if ActionClass.DELETE not in self.permitted_actions:
            lines.append(
                "  Deletion is NOT authorised by this finding. If you believe "
                "deletion is genuinely required, say so in your report and stop; "
                "do not perform it."
            )
        if self.rationale:
            lines.append(f"  Why: {self.rationale}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "resolution_criterion": self.resolution_criterion,
            "permitted_actions": [a.value for a in self.permitted_actions],
            "max_irreversibility": self.max_irreversibility,
            "recoverable_path": self.recoverable_path,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ActionContract":
        return cls(
            finding_id=d.get("finding_id", ""),
            resolution_criterion=d.get("resolution_criterion", ""),
            permitted_actions=[ActionClass(a) for a in d.get("permitted_actions", ["investigate"])],
            max_irreversibility=d.get("max_irreversibility", "FULLY_REVERSIBLE"),
            recoverable_path=d.get("recoverable_path"),
            rationale=d.get("rationale", ""),
        )


# Severity -> what consequence is PROPORTIONATE to that much evidence.
#
# DELETE appears in none of these on purpose. An irreversible action is never
# derivable from "a detector noticed something"; it has to be declared by a
# finding that explicitly means destruction. That is the whole rule, and it
# does not need restating per finding.
_SEVERITY_DEFAULTS = {
    "critical": ([ActionClass.INVESTIGATE, ActionClass.MODIFY, ActionClass.ARCHIVE,
                  ActionClass.EXECUTE], "MOSTLY_IRREVERSIBLE"),
    "high":     ([ActionClass.INVESTIGATE, ActionClass.MODIFY, ActionClass.ARCHIVE,
                  ActionClass.EXECUTE], "PARTIALLY_REVERSIBLE"),
    "medium":   ([ActionClass.INVESTIGATE, ActionClass.MODIFY, ActionClass.ARCHIVE],
                 "PARTIALLY_REVERSIBLE"),
    "low":      ([ActionClass.INVESTIGATE, ActionClass.ARCHIVE], "MOSTLY_REVERSIBLE"),
    "info":     ([ActionClass.INVESTIGATE], "FULLY_REVERSIBLE"),
}

DEFAULT_RECOVERABLE_PATH = "logs/archive/"


def derive_contract(
    finding_id: str,
    severity: str,
    title: str = "",
    category: str = "",
    recoverable_path: Optional[str] = DEFAULT_RECOVERABLE_PATH,
) -> "ActionContract":
    """Build a contract from what the finding ALREADY tells us.

    Hand-authoring a contract per finding was the wrong design: 35 finding
    construction sites, every new detector needing a human to write one, and
    any omission silently falling back to unconstrained. Nearly all of it is
    derivable, so nothing has to be authored:

      * resolution criterion -- universal. A finding is resolved when the audit
        that raised it stops raising it. `run_security_audit` already reconciles
        exactly this way, so the criterion IS the detector, and no detector has
        to restate it in prose. (Prose is what made the agent guess.)
      * permitted actions / max irreversibility -- PROPORTIONALITY. Consequence
        should scale with the strength of the evidence, and severity is that
        strength. This is one rule, not 35.
      * recoverable path -- a system convention, not a per-finding fact.

    An explicit contract on a finding remains available for genuine exceptions
    where severity is the wrong signal -- an empty log file is only MEDIUM but
    must be investigate-only, because it is potential tamper evidence and
    touching it destroys what is being investigated. Overrides should be rare
    and should say why.
    """
    actions, max_irr = _SEVERITY_DEFAULTS.get(
        str(severity or "").lower(), _SEVERITY_DEFAULTS["low"]
    )
    what = title or finding_id
    return ActionContract(
        finding_id=finding_id,
        resolution_criterion=(
            f"the condition behind '{what}' is no longer reported by the "
            f"{category or 'security'} audit that raised it"
        ),
        permitted_actions=list(actions),
        max_irreversibility=max_irr,
        recoverable_path=recoverable_path,
        rationale=(
            f"derived from severity={str(severity).upper()}: consequence is bounded by "
            f"the strength of the evidence. Irreversible removal is never derived — it "
            f"must be declared explicitly by a finding that means destruction."
        ),
    )


# The contract in force for the CURRENT task.
#
# A ContextVar, not an attribute or a module global: the coordinator now runs
# several tasks concurrently (TaskExecutionPool), and each asyncio task gets its
# own copy automatically. A global here would let one task's contract authorise
# another task's action -- precisely the duplicate-authority failure this
# codebase keeps producing.
_active_contract: contextvars.ContextVar[Optional[ActionContract]] = contextvars.ContextVar(
    "torin_active_action_contract", default=None
)


def set_active_contract(contract: Optional[ActionContract]):
    """Bind a contract to the current async context. Returns the reset token."""
    return _active_contract.set(contract)


def get_active_contract() -> Optional[ActionContract]:
    return _active_contract.get()


def reset_active_contract(token) -> None:
    try:
        _active_contract.reset(token)
    except (ValueError, LookupError):
        pass


__all__ = [
    "ActionClass",
    "ActionContract",
    "irreversibility_rank",
    "set_active_contract",
    "get_active_contract",
    "reset_active_contract",
]
