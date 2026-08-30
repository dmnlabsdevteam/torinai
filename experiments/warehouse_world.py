#!/usr/bin/env python3
"""A third real world for EDU-07. Different names again.

TRANSFER / LOCATED / ROUTE / AVAILABLE, structurally analogous to KITE's
MOVE / AT / PATH / OPEN and to ARCHIVE's RELOCATE / IN / LINK / READY, sharing
no useful lexical identity with either.

Bays are directories, pallets are files, and the world ENFORCES its own
preconditions -- a refusal is a real refusal, so a negative demonstration is an
observation rather than a label.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from core.learning.rule_induction import Fact

WORLD_ROOT = Path(__file__).resolve().parents[1] / "warehouse_world"
BAYS = ("DOCK", "AISLE", "VAULT")
ROUTES = (("DOCK", "AISLE"), ("AISLE", "VAULT"))


class WarehouseWorld:
    MARKER = ".available"

    def __init__(self, root: Path = WORLD_ROOT):
        self.root = Path(root)
        self.reset()

    def reset(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        for bay in BAYS:
            (self.root / bay).mkdir(parents=True)

    def place(self, pallet: str, bay: str) -> None:
        (self.root / bay / pallet).write_text("")

    def make_available(self, bay: str) -> None:
        (self.root / bay / self.MARKER).write_text("")

    def observe(self):
        if not self.root.exists():
            return None
        facts = set()
        for bay in BAYS:
            directory = self.root / bay
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if entry.name == self.MARKER:
                    facts.add(Fact("AVAILABLE", (bay,)))
                elif entry.is_file():
                    facts.add(Fact("LOCATED", (entry.name, bay)))
        for a, b in ROUTES:
            facts.add(Fact("ROUTE", (a, b)))
        return frozenset(facts)

    def transfer(self, pallet: str, source: str, destination: str) -> bool:
        """The real effect. Preconditions enforced by the world, not the teacher."""
        origin = self.root / source / pallet
        if not origin.exists():                                     # LOCATED
            return False
        if (source, destination) not in ROUTES:                     # ROUTE
            return False
        if not (self.root / destination / self.MARKER).exists():    # AVAILABLE
            return False
        origin.rename(self.root / destination / pallet)
        return True


__all__ = ["WarehouseWorld", "WORLD_ROOT", "BAYS", "ROUTES"]
