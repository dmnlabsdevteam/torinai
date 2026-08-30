#!/usr/bin/env python3
"""A corpus large enough to be worth reading.

The sessions were small because the substrate could represent five structures,
so there was nothing to teach into. It now handles seven, and it learns a word
from ONE sighting -- so the limit on how much English it can acquire is how
much English it is given, not how long it is given it.

The teacher writes the sentences. That is a proposal like any other: the
substrate reads them, and only a sentence that READS teaches anything. A
sentence the teacher writes badly teaches nothing and is counted as such.
"""

from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Sequence, Set, Tuple

#: The shapes the substrate can represent. Nothing else is requested, because a
#: sentence it cannot parse is not a lesson -- it is noise with a full stop.
SHAPES: Tuple[Tuple[str, str], ...] = (
    ("fact",        "the NOUN is ADJECTIVE"),
    ("plural",      "the NOUNs are ADJECTIVE"),
    ("negation",    "the NOUN is not ADJECTIVE"),
    ("action",      "the NOUN VERBs"),
    ("transitive",  "the NOUN VERBs the NOUN"),
    ("relation",    "the NOUN is in the NOUN"),
    ("conjunction", "the NOUN is ADJECTIVE and ADJECTIVE"),
)

DOMAINS = (
    "machines in a workshop", "a kitchen", "a garden", "weather",
    "a harbour", "a laboratory", "a library", "a farm",
    "a hospital ward", "a railway station", "a bakery", "a forest",
)


def _clean(line: str) -> str:
    line = line.strip().strip("-*0123456789. ").strip()
    line = re.sub(r"\s+", " ", line)
    return line.rstrip(".").lower()


def usable(line: str) -> bool:
    """Cheap shape filter before anything is asked to read it."""
    if not line or len(line.split()) < 3 or len(line.split()) > 9:
        return False
    if not line.startswith("the "):
        return False
    return bool(re.fullmatch(r"[a-z' ]+", line))


async def generate(teacher, domain: str, shape_name: str, shape: str,
                   count: int = 12) -> List[str]:
    """Ask the teacher for `count` sentences of one shape about one domain."""
    reply = await teacher.say(
        f"Write {count} simple English sentences about {domain}.\n"
        f"Every sentence must follow exactly this shape: {shape}\n"
        f"Use ordinary concrete words. Use a different noun in each sentence.\n"
        f"Output only the sentences, one per line, no numbering, no commentary.",
        max_tokens=420)
    seen: List[str] = []
    for raw in (reply or "").splitlines():
        line = _clean(raw)
        if usable(line) and line not in seen:
            seen.append(line)
    return seen
