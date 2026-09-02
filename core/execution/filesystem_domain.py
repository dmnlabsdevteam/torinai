#!/usr/bin/env python3
"""A real, observable domain the substrate can act in and learn from: the
filesystem under a sandbox root.

This is the production analogue of the MOVE world the substrate execution tests
use. A directory is a place, a file is a thing that has a location, and the
`move_file` tool is the action that changes it. The point is not the filesystem
in particular -- it is that the substrate needs at least one domain that is
genuinely OBSERVABLE (its state read back from the world, not from a rule) and
genuinely ACTABLE (a real tool changes it), so that operator learning has
somewhere to happen outside a test harness. The binding registry was populated
only by experiments and tests; this installs one for real.

The vocabulary is deliberately minimal -- a single predicate, FILE_IN(file,
dir). Induction searches the space of hypotheses over the facts it is shown, so
a smaller observed state keeps that search cheap. DIR facts and richer relations
are omitted on purpose: nothing the substrate needs to learn about moving a file
requires them, and each extra literal widens the hypothesis space the learner
must cross.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import FrozenSet, List, Optional

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact

logger = logging.getLogger(__name__)

PREDICATE = "FILE_IN"


def _encode(name: str) -> str:
    """A filesystem name as a logic constant, bijectively.

    A logic term must be an identifier, but real names carry dots, dashes,
    spaces and non-ASCII. Rather than IGNORE such names -- which would make the
    substrate blind to ordinary files like `report.txt` -- each is encoded to a
    valid identifier and decoded back before the tool acts. Every byte that is
    not ASCII-alphanumeric becomes `_HH` (escape + two hex digits); the rest
    stay literal. A leading `F` anchors the identifier start (a name may begin
    with a digit) and is stripped on decode. Because literal characters are
    alphanumeric only, every `_` in the output begins a two-hex escape, so the
    decoding is unambiguous.
    """
    out = ["F"]
    for byte in name.encode("utf-8"):
        ch = chr(byte)
        out.append(ch if (ch.isascii() and ch.isalnum()) else "_%02x" % byte)
    return "".join(out)


def _decode(ident: str) -> str:
    """Invert `_encode`. The action carries encoded names; the tool needs real
    ones, so a bound operator's parameters are decoded before it moves a file."""
    body = ident[1:]  # drop the leading F anchor
    buffer = bytearray()
    index = 0
    while index < len(body):
        if body[index] == "_":
            buffer.append(int(body[index + 1:index + 3], 16))
            index += 3
        else:
            buffer.append(ord(body[index]))
            index += 1
    return buffer.decode("utf-8")


class FilesystemWorld:
    """The files under a sandbox root, read as FILE_IN(file, dir) facts.

    `dir` is an immediate subdirectory of the root; `file` is a file directly
    inside it. Files in the root itself and nested directories are ignored;
    names are ENCODED to logic constants (see `_encode`) rather than dropped, so
    an ordinary file with a dot in its name is still something the learner sees.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def dirs(self) -> List[str]:
        if not self.root.exists():
            return []
        return sorted(_encode(p.name) for p in self.root.iterdir()
                      if p.is_dir())

    def observe(self) -> Optional[FrozenSet[Fact]]:
        """Read the filesystem. Returns None when the root cannot be read --
        which is not the same as an empty sandbox.
        """
        if not self.root.exists():
            return None
        facts = set()
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if entry.is_file():
                    facts.add(Fact(PREDICATE, (_encode(entry.name),
                                               _encode(directory.name))))
        return frozenset(facts)

    def binding(self) -> OperatorBinding:
        """Bind MOVE_FILE(file, src, dst) to the move_file tool.

        The tool moves root/src/file to root/dst/file. `create_dirs=False`: a
        move to a directory that does not exist must FAIL and leave the world
        unmoved, because that failure is exactly the negative evidence the
        learner needs -- a tool that quietly created the destination would erase
        the precondition it is there to teach.
        """
        root = self.root

        def parameters(args):
            file, src, dst = (_decode(a) for a in args)
            return {
                "source_path": str(root / src / file),
                "destination_path": str(root / dst / file),
                "create_dirs": False,
            }

        return OperatorBinding(
            predicate="MOVE_FILE", tool_name="move_file",
            parameters=parameters, observe=self.observe,
            description="move a file between directories under the sandbox root")

    def propose_actions(self) -> List[Fact]:
        """Candidate MOVE_FILE actions to try, grounded in what is observed.

        Both kinds the learner needs:
          - moves whose file really is where the action says (these succeed and
            teach the effect),
          - moves whose file is NOT in the named source (these fail and teach
            that the location precondition is necessary).
        A file is never proposed to move to the directory it already occupies.
        """
        facts = self.observe() or frozenset()
        located = {(f.args[0], f.args[1]) for f in facts
                   if f.predicate == PREDICATE and len(f.args) == 2}
        files = sorted({file for file, _ in located})
        dirs = self.dirs()

        candidates: List[Fact] = []
        # Real moves: the file is where we say, destination is a different dir.
        for file, here in sorted(located):
            for dst in dirs:
                if dst != here:
                    candidates.append(Fact("MOVE_FILE", (file, here, dst)))
        # Counter-moves: the file is NOT in the named source directory.
        for file in files:
            here = next(h for f, h in located if f == file)
            for wrong in dirs:
                if wrong != here:
                    for dst in dirs:
                        if dst != wrong:
                            candidates.append(Fact("MOVE_FILE", (file, wrong, dst)))
                            break
        return candidates


def install_filesystem_domain(domain_id: str, root: Path) -> FilesystemWorld:
    """Register a sandbox directory as an explorable, plannable domain.

    This is a real, production binding installation -- the wire the codebase was
    missing outside experiments and tests. After this the substrate can observe
    the domain, act in it through the bound tool, and learn operators from what
    happens.
    """
    world = FilesystemWorld(Path(root))
    get_binding_registry().register(domain_id, world.binding())
    # Also declare HOW to explore it, so the idle exploration tier can pick this
    # domain up and learn its operators without knowing it is a filesystem.
    from core.learning.exploration import register_explorable_domain
    register_explorable_domain(domain_id, world.propose_actions)
    logger.info("installed filesystem domain %s at %s", domain_id, root)
    return world


def ensure_filesystem_domain(domain_id: str, root) -> Optional[FilesystemWorld]:
    """Install a filesystem domain the FIRST time the substrate ENCOUNTERS it,
    idempotently — the encounter-driven wire that replaces a blanket startup
    install.

    A domain becomes real when the substrate actually works in it: a task that
    declares a filesystem workspace calls this before observing the world, so the
    domain is bound (observable + actable) and explorable from that point on,
    scoped to exactly the directory the work named. Nothing is installed until a
    real encounter, and no fixed directory is registered speculatively.

    Idempotent: a domain already installed this process is left untouched
    (returns None — nothing to do). Declines (None) when the root is not an
    existing directory: a domain the substrate would ACT in must be a real place,
    and inventing one is how the substrate would act on nothing. Returns the new
    world only when it actually installs one.
    """
    from core.learning.exploration import get_proposer

    if not (isinstance(domain_id, str) and domain_id.strip()):
        logger.warning("cannot install filesystem domain: blank domain_id")
        return None
    if get_proposer(domain_id) is not None:
        return None  # already encountered this process — idempotent no-op
    root_path = Path(root)
    if not root_path.is_dir():
        logger.warning(
            "cannot install filesystem domain %s: root %s is not an existing "
            "directory — a domain the substrate acts in must be a real place",
            domain_id, root_path)
        return None
    return install_filesystem_domain(domain_id, root_path)


def fresh_evidence_id() -> str:
    return f"explore_{uuid.uuid4().hex[:12]}"
