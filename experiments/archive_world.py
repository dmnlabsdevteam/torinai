#!/usr/bin/env python3
"""A second real world, in a different domain, with different predicates.

Buckets are directories, items are files, and RELOCATE moves one between them.
Structurally analogous to KITE's MOVE and lexically unrelated: IN / LINK /
READY rather than AT / PATH / OPEN. That is deliberate. The grounder matches on
RELATION ROLE (`requires` / `adds` / `removes`), not on predicate names, so if
a KITE-learned structure grounds an ARCHIVE observation it did so on shape --
it cannot have been carried by a shared word.

`observe()` reads the filesystem. Nothing here predicts; every fact is a thing
that is actually on disk.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from core.learning.rule_induction import Fact

WORLD_ROOT = Path(__file__).resolve().parents[1] / "archive_world"
BUCKETS = ("INBOX", "STAGING", "PROCESSED")
LINKS = (("INBOX", "STAGING"), ("STAGING", "PROCESSED"))


class ArchiveWorld:
    """Buckets are directories; an item is a file; READY is a marker file."""

    MARKER = ".ready"

    def __init__(self, root: Path = WORLD_ROOT):
        self.root = Path(root)
        self.reset()

    def reset(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        for bucket in BUCKETS:
            (self.root / bucket).mkdir(parents=True)

    def place(self, item: str, bucket: str) -> None:
        (self.root / bucket / item).write_text("")

    def mark_ready(self, bucket: str) -> None:
        (self.root / bucket / self.MARKER).write_text("")

    def unmark_ready(self, bucket: str) -> None:
        marker = self.root / bucket / self.MARKER
        if marker.exists():
            marker.unlink()

    def observe(self):
        """Facts read off the disk. None when the world cannot be read."""
        if not self.root.exists():
            return None
        facts = set()
        for bucket in BUCKETS:
            directory = self.root / bucket
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if entry.name == self.MARKER:
                    facts.add(Fact("READY", (bucket,)))
                elif entry.is_file():
                    facts.add(Fact("IN", (entry.name, bucket)))
        for a, b in LINKS:
            facts.add(Fact("LINK", (a, b)))
        return frozenset(facts)

    def relocate(self, item: str, source: str, destination: str) -> bool:
        """The real effect: the file actually moves. False when it cannot.

        THE PRECONDITIONS ARE ENFORCED BY THE WORLD, not by the teacher. A
        negative demonstration is only honest if the action genuinely does not
        happen -- if relocate succeeded regardless of LINK and READY, labelling
        such a run "negative" would be fabricating the very evidence induction
        is supposed to generalize from.
        """
        origin = self.root / source / item
        if not origin.exists():                       # IN(item, source)
            return False
        if (source, destination) not in LINKS:        # LINK(source, destination)
            return False
        if not (self.root / destination / self.MARKER).exists():   # READY(dest)
            return False
        origin.rename(self.root / destination / item)
        return True


__all__ = ["ArchiveWorld", "WORLD_ROOT", "BUCKETS", "LINKS"]
