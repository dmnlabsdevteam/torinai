#!/usr/bin/env python3
"""What the substrate knows about individual words, and how it came to know it.

Before this there was nowhere to put a word class. The reader held three closed
function-word sets -- {a, an, the}, {is, are}, {not} -- and every other word was
undifferentiated CONTENT, so "the cold is heavy" and "the tank is heavy" were
indistinguishable and no amount of teaching could show up anywhere.

    A CLASS IS A CLAIM, AND A CLAIM NEEDS A SOURCE.

Every entry records where it came from. A class PROPOSED by a teacher is a
candidate and reads as one; it becomes CONFIRMED only when a sentence that
depends on it actually reads. That is the same rule the rest of the substrate
uses: a model may propose, the world attests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

logger = logging.getLogger(__name__)

NOUN, ADJECTIVE, VERB = "NOUN", "ADJECTIVE", "VERB"
CLASSES = (NOUN, ADJECTIVE, VERB)

PROPOSED = "proposed"      # a teacher said so; no evidence yet
CONFIRMED = "confirmed"    # a sentence depending on it read successfully
REFUTED = "refuted"        # a sentence depending on it failed to read


@dataclass
class Entry:
    """One word, its class, and the standing of that claim."""

    word: str
    word_class: str
    status: str = PROPOSED
    source: str = ""
    confirmations: int = 0
    contradictions: int = 0
    evidence: list = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether reading may rely on it.

        A proposal is usable -- otherwise nothing could ever be tested and no
        evidence could ever arrive -- but it is never reported as confirmed.
        A refuted entry is not usable: it was tried and the world disagreed.
        """
        return self.status != REFUTED


class Lexicon:
    """The word store. Small, inspectable, and persisted as plain JSON."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else (
            Path(__file__).resolve().parents[2] / "data" / "lexicon.json")
        self._entries: Dict[str, Entry] = {}
        self.load()

    # ── reading ─────────────────────────────────────────────────────────────
    def class_of(self, word: str) -> Optional[str]:
        entry = self._entries.get(word.lower())
        return entry.word_class if entry and entry.usable else None

    def entry(self, word: str) -> Optional[Entry]:
        return self._entries.get(word.lower())

    def words_of_class(self, word_class: str) -> Set[str]:
        return {w for w, e in self._entries.items()
                if e.word_class == word_class and e.usable}

    def known(self) -> Iterable[Entry]:
        return list(self._entries.values())

    # ── writing ─────────────────────────────────────────────────────────────
    def propose(self, word: str, word_class: str, source: str) -> Entry:
        """Record a claim. Proposing does not make it true."""
        if word_class not in CLASSES:
            raise ValueError(f"unknown word class {word_class!r}; expected {CLASSES}")
        key = word.lower()
        existing = self._entries.get(key)
        if existing and existing.word_class != word_class:
            # A second, different proposal does not overwrite the first: two
            # sources disagreeing is information, and silently taking the later
            # one would erase it.
            existing.contradictions += 1
            existing.evidence.append(f"conflicting proposal {word_class} from {source}")
            return existing
        entry = existing or Entry(word=key, word_class=word_class, source=source)
        self._entries[key] = entry
        return entry

    def confirm(self, word: str, evidence: str) -> None:
        entry = self._entries.get(word.lower())
        if not entry:
            return
        entry.confirmations += 1
        entry.status = CONFIRMED
        entry.evidence.append(f"confirmed: {evidence}")

    def refute(self, word: str, evidence: str) -> None:
        entry = self._entries.get(word.lower())
        if not entry:
            return
        entry.contradictions += 1
        entry.evidence.append(f"contradicted: {evidence}")
        # One contradiction does not refute a claim with standing behind it.
        if entry.contradictions > entry.confirmations:
            entry.status = REFUTED

    # ── persistence ─────────────────────────────────────────────────────────
    def load(self) -> int:
        if not self.path.exists():
            return 0
        try:
            blob = json.loads(self.path.read_text())
        except Exception as error:
            logger.warning("lexicon unreadable (%s); starting empty", error)
            return 0
        self._entries = {w: Entry(**e) for w, e in blob.items()}
        return len(self._entries)

    def save(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {w: e.__dict__ for w, e in self._entries.items()}, indent=2))
        return len(self._entries)

    def clear(self) -> None:
        self._entries = {}


_lexicon: Optional[Lexicon] = None


def get_lexicon() -> Lexicon:
    global _lexicon
    if _lexicon is None:
        _lexicon = Lexicon()
    return _lexicon
