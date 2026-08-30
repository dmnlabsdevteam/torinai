#!/usr/bin/env python3
"""A real world for substrate execution: rooms are directories, the agent is a
file, and MOVE is the `move_file` tool.

Not a simulation and not a test double. `observe()` reads the filesystem and
returns only what is actually there, which is what makes runtime evidence
admissible: if the world were reported by the same code that acted on it, a
rule would be confirmed by its own invocation returning cleanly.

`observe()` returns None when the world cannot be read at all. That is a
different fact from an empty world, and collapsing the two would make every
delete effect read as confirmed.
"""

from __future__ import annotations

from pathlib import Path

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact

WORLD_ROOT = Path(__file__).resolve().parents[1] / "sandbox_e2e"
ROOMS = ("HALL", "LAB", "VAULT")
PATHS = (("HALL", "LAB"), ("LAB", "VAULT"))
ITEM = "z"


class FilesystemWorld:
    """Rooms are directories, occupants are files, connectivity is declared."""

    def __init__(self, root: Path = WORLD_ROOT, rooms=ROOMS, paths=PATHS):
        self.root = Path(root)
        self.rooms = list(rooms)
        self.paths = [tuple(p) for p in paths]
        for room in self.rooms:
            (self.root / room).mkdir(parents=True, exist_ok=True)

    def place(self, agent: str, room: str) -> None:
        (self.root / room / agent).write_text("")

    def clear(self, agent: str) -> None:
        for room in self.rooms:
            target = self.root / room / agent
            if target.exists():
                target.unlink()

    def seal(self, room: str) -> None:
        """Remove a room entirely, so OPEN(room) stops holding."""
        directory = self.root / room
        for entry in directory.iterdir():
            entry.unlink()
        directory.rmdir()

    def observe(self):
        if not self.root.exists():
            return None
        facts = set()
        for room in self.rooms:
            directory = self.root / room
            if not directory.is_dir():
                continue
            facts.add(Fact("OPEN", (room,)))
            for entry in directory.iterdir():
                if entry.is_file():
                    facts.add(Fact("AT", (entry.name, room)))
        for a, b in self.paths:
            facts.add(Fact("PATH", (a, b)))
        return frozenset(facts)

    def binding(self) -> OperatorBinding:
        return OperatorBinding(
            predicate="MOVE",
            tool_name="move_file",
            parameters=lambda args: {
                "source_path": str(self.root / args[1] / args[0]),
                "destination_path": str(self.root / args[2] / args[0]),
                "create_dirs": False,
            },
            observe=self.observe,
            description="rooms are directories; the agent is a file",
        )

    def register(self, domain_id: str) -> "FilesystemWorld":
        get_binding_registry().register(domain_id, self.binding())
        return self


__all__ = ["FilesystemWorld", "WORLD_ROOT", "ROOMS", "PATHS", "ITEM"]
