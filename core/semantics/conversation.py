#!/usr/bin/env python3
"""The held conversation — re-exported from where it now lives.

The `Conversation` faculty (and `get_conversation`/`end_conversation`) was moved
into `core.agents.autonomous.autonomous_coordinator` when the Self was collapsed
into the coordinator: the substrate IS the coordinator, so the faculty it holds
a conversation with lives with it. This module is the STABLE import path the
rest of the tree (talk.py, the EDU teaching passes, tool discovery) has always
used, kept pointing at the single authority so there is never a second
`Conversation` to drift from it.

The re-export is LAZY (PEP 562 module __getattr__): importing the coordinator
pulls the whole substrate, and some of its own imports reach this module, so an
eager `from ... import Conversation` here would be a cycle. Nothing is imported
until an attribute is actually read, by which point the coordinator module has
finished loading.
"""
from __future__ import annotations

_EXPORTS = ("Conversation", "get_conversation", "end_conversation",
            "held_conversations", "Turn", "Acquired", "Resolved", "Answer",
            "Understanding")


def __getattr__(name: str):
    if name in _EXPORTS:
        from core.agents.autonomous import autonomous_coordinator as _coord
        return getattr(_coord, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(_EXPORTS)
