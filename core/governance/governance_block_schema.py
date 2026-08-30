"""Governance block META memory schema and validation.

This module defines the canonical structure for governance_block
META memories written by the autonomous coordinator and queried by
intrinsic motivation / reasoning components.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict


@dataclass
class GovernanceBlock:
    """Structured representation of a governance block META memory."""

    task_id: str
    task_type: str
    task_description: str
    block_type: str
    block_reason: str
    task_source: str
    domain: str
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceBlock":
        """Validate and construct from a raw dict.

        Raises ValueError if required fields are missing or malformed.
        """

        required_fields = [
            "task_id",
            "task_type",
            "task_description",
            "block_type",
            "block_reason",
            "task_source",
            "domain",
            "timestamp",
        ]

        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(f"Missing fields in GovernanceBlock: {', '.join(missing)}")

        # Basic type checks
        for field in [
            "task_id",
            "task_type",
            "task_description",
            "block_type",
            "block_reason",
            "task_source",
            "domain",
        ]:
            if not isinstance(data[field], str):
                raise ValueError(f"Field '{field}' must be a string")

        # Parse timestamp
        ts = data["timestamp"]
        if isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid timestamp format: {ts}") from exc
        elif isinstance(ts, datetime):
            timestamp = ts
        else:
            raise ValueError("Field 'timestamp' must be ISO string or datetime")

        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            task_description=data["task_description"],
            block_type=data["block_type"],
            block_reason=data["block_reason"],
            task_source=data["task_source"],
            domain=data["domain"],
            timestamp=timestamp,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict."""

        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_description": self.task_description,
            "block_type": self.block_type,
            "block_reason": self.block_reason,
            "task_source": self.task_source,
            "domain": self.domain,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TaskOutcomeRecord:
    """Structured representation of a task outcome / performance META memory."""

    task_id: str
    task_type: str
    task_description: str
    outcome: str  # "success" or "failure"
    confidence: float
    domain: str
    task_source: str
    timestamp: datetime
    result_summary: str | None = None
    failure_reason: str | None = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskOutcomeRecord":
        """Validate and construct from a raw dict.

        Raises ValueError if required fields are missing or malformed.
        """

        required_fields = [
            "task_id",
            "task_type",
            "task_description",
            "outcome",
            "confidence",
            "domain",
            "task_source",
            "timestamp",
        ]

        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(f"Missing fields in TaskOutcomeRecord: {', '.join(missing)}")

        # Basic type checks
        for field in [
            "task_id",
            "task_type",
            "task_description",
            "outcome",
            "domain",
            "task_source",
        ]:
            if not isinstance(data[field], str):
                raise ValueError(f"Field '{field}' must be a string")

        if not isinstance(data["confidence"], (int, float)):
            raise ValueError("Field 'confidence' must be a number")

        ts = data["timestamp"]
        if isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid timestamp format: {ts}") from exc
        elif isinstance(ts, datetime):
            timestamp = ts
        else:
            raise ValueError("Field 'timestamp' must be ISO string or datetime")

        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            task_description=data["task_description"],
            outcome=data["outcome"],
            confidence=float(data["confidence"]),
            domain=data["domain"],
            task_source=data["task_source"],
            timestamp=timestamp,
            result_summary=data.get("result_summary"),
            failure_reason=data.get("failure_reason"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict."""

        payload: Dict[str, Any] = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_description": self.task_description,
            "outcome": self.outcome,
            "confidence": float(self.confidence),
            "domain": self.domain,
            "task_source": self.task_source,
            "timestamp": self.timestamp.isoformat(),
        }

        if self.result_summary is not None:
            payload["result_summary"] = self.result_summary
        if self.failure_reason is not None:
            payload["failure_reason"] = self.failure_reason

        return payload


TASK_OUTCOME_EVENT = "task_outcome"


def task_outcome_from_memory(memory: Any) -> "TaskOutcomeRecord | None":
    """Recover the structured TaskOutcomeRecord from a stored memory.

    The coordinator stores one event in two representations:
      - ``content``                     : a narrative *string* (human / embedding)
      - ``thinking_state["raw_event"]`` : the structured record

    ``thinking_state["raw_event"]`` is authoritative. The narrative is lossy and
    is never parsed back — reconstructing cognitive state from prose would create
    a second, divergent interpretation of a single observation.

    Accepts a MemoryItem (duck-typed on ``.content`` / ``.thinking_state``) or a
    plain dict. Returns None if the memory is not a task outcome, or if the
    record fails validation.
    """

    if isinstance(memory, dict):
        thinking_state = memory.get("thinking_state")
        content = memory.get("content")
    else:
        thinking_state = getattr(memory, "thinking_state", None)
        content = getattr(memory, "content", None)

    candidates = []
    if isinstance(thinking_state, dict):
        candidates.append(thinking_state.get("raw_event"))
    # In-process callers and tests may hand over the record dict directly,
    # before it has been through the narrative-building store path.
    candidates.append(content)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("event") != TASK_OUTCOME_EVENT:
            continue
        try:
            return TaskOutcomeRecord.from_dict(candidate)
        except ValueError:
            continue

    return None


__all__ = [
    "GovernanceBlock",
    "TaskOutcomeRecord",
    "TASK_OUTCOME_EVENT",
    "task_outcome_from_memory",
]
