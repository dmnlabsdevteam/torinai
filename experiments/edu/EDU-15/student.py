#!/usr/bin/env python3
"""Asking the substrate to construct a program, through the real ingress.

No shortcut path. The task goes to the same entry point a person would use, so
what is measured is what the system can actually do when asked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Attempt:
    """What the substrate produced, and whether it produced anything."""

    task_id: str
    source: str = ""
    responded: bool = False
    said_unknown: bool = False
    raw: str = ""
    error: Optional[str] = None


_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.S | re.I)
_UNKNOWN = ("i do not know", "i don't know", "unknown", "cannot", "i hold nothing")


def extract_code(text: str) -> str:
    """The program inside a reply, if there is one.

    A reply with no code is not a wrong program -- it is an absence of one, and
    the two are scored differently: a wrong program is a false belief, an
    absence is an honest UNKNOWN.
    """
    if not text:
        return ""
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    if re.search(r"^\s*def\s+\w+\s*\(", text, re.M):
        return text.strip()
    return ""


async def ask_substrate(task) -> Attempt:
    """Put the task to Torin through the conversation ingress."""
    from core.semantics.conversation import Conversation

    talk = Conversation()
    try:
        understanding = await talk.understand(task.prompt)
        reply = understanding.reply or ""
    except Exception as error:
        return Attempt(task.task_id, error=f"{type(error).__name__}: {error}")

    code = extract_code(reply)
    return Attempt(
        task_id=task.task_id,
        source=code,
        responded=bool(reply.strip()),
        said_unknown=any(m in reply.lower() for m in _UNKNOWN),
        raw=reply[:400],
    )
