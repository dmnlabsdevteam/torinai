#!/usr/bin/env python3
"""Module-level conveniences over `FilesystemWorld`, for the end-to-end runs.

WHY THIS FILE EXISTS. EDU-02 imported `e2e_common` from a path under
`/private/tmp/.../scratchpad` -- a per-session temporary directory. The helper
was written there once and never persisted, so the moment that directory was
cleared the experiment died with `ModuleNotFoundError` and stayed dead. An
experiment that depends on a temp file is an experiment that cannot be re-run,
which is the one thing a frozen benchmark has to be able to do. It lives beside
`e2e_world.py` now, in the repository.

THE STRING FORMAT IS LOAD-BEARING AND IS NOT `Fact.to_formula()`.

`Fact.to_formula()` renders `AT(z, HALL)` -- with a space after the comma. Its
callers here test membership against literals built as `f"AT({ITEM},VAULT)"`,
which has no space. Had `observe()` returned the spaced form, that test would
be False no matter what the world contained, `contradicted` would be True
unconditionally, and EDU-02's assertion would pass without ever observing a
contradiction -- a benchmark that reports success because its own comparison
can never match. `_compact` renders the form the callers actually compare
against.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_world import ITEM, PATHS, ROOMS, WORLD_ROOT, FilesystemWorld  # noqa: E402

#: Where the item is placed by `reset_world`. HALL is not adjacent to VAULT
#: (PATHS connects HALL-LAB and LAB-VAULT), which is what gives the broad rule
#: -- the one missing an AT(item, source) precondition -- room to plan a move
#: the world will refuse.
START_ROOM = "HALL"

_world: Optional[FilesystemWorld] = None


def world() -> FilesystemWorld:
    """The single world instance these helpers operate on."""
    global _world
    if _world is None:
        _world = FilesystemWorld()
    return _world


def _compact(fact) -> str:
    """`AT(z,HALL)` -- the form the callers compare against. See module docstring."""
    return f"{fact.predicate}({','.join(fact.args)})"


def reset_world() -> Tuple[str, ...]:
    """Return the world to its starting state and report what is there.

    Rebuilt rather than assumed: a previous run may have moved, sealed or
    removed rooms, and starting from whatever the last run left behind would
    make the result depend on execution order.
    """
    root = Path(WORLD_ROOT)
    for room in ROOMS:
        (root / room).mkdir(parents=True, exist_ok=True)
    w = world()
    w.clear(ITEM)
    w.place(ITEM, START_ROOM)
    return observe()


def observe() -> Tuple[str, ...]:
    """What the filesystem actually holds, as compact formula strings.

    Empty tuple when the world cannot be read at all. `FilesystemWorld.observe`
    returns None for that case specifically so it stays distinguishable from an
    empty world; the callers here treat both as "nothing observed", and the
    distinction is preserved by `readable()` for anything that needs it.
    """
    facts = world().observe()
    if facts is None:
        return ()
    return tuple(sorted(_compact(f) for f in facts))


def readable() -> bool:
    """Whether the world could be read. False is not an empty world."""
    return world().observe() is not None


def where_is(item: str = ITEM) -> Optional[str]:
    """The room holding `item`, or None if it is nowhere in the world."""
    root = Path(WORLD_ROOT)
    for room in ROOMS:
        if (root / room / item).exists():
            return room
    return None


__all__ = ["reset_world", "observe", "readable", "where_is", "world",
           "WORLD_ROOT", "ITEM", "ROOMS", "PATHS", "START_ROOM"]
