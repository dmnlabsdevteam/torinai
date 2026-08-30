#!/usr/bin/env python3
"""The generality invariant: the subject changes, the architecture does not.

EDU-12's entire claim rests on ONE learner being taught four different things.
That claim is worth nothing if it is a promise. A reader has no way to tell a
genuinely general architecture from four special cases unless the sameness is
MEASURED, so it is measured here twice, in two different ways, because the two
ways fail differently.

    ARCHITECTURE FINGERPRINT   every .py under core/ hashed, recorded before
                               the first class and re-checked after every
                               block. Catches "I quietly added a branch for
                               chemistry".

    SUBJECT PURITY             a subject module may declare DATA and the NAMES
                               of tools it needs, and nothing else. No imports
                               from core, no function definitions, no classes.
                               Catches "the subject file contains a solver".

The second is the one that actually bites. A fingerprint over core/ is easy to
satisfy by putting the domain-specific cleverness in the subject file instead,
which is the same defect wearing a different hat. So a subject is a declarative
record or it is rejected -- it cannot contain reasoning, because it cannot
contain code.

Exposing different TOOLS is allowed and expected; an intelligent system needs
interfaces to different worlds. The distinction enforced here is between giving
the learner a new instrument and giving it a new mind.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

SUBSTRATE_ROOT = Path(__file__).resolve().parents[3] / "core"
EXCLUDED_PARTS = {"__pycache__", ".cache", "data"}

#: The complete vocabulary a subject file may define. Anything else is a defect.
ALLOWED_SUBJECT_NAMES = {
    "SUBJECT", "DESCRIPTION", "COGNITIVE_DEMAND", "TOOLS", "ENVIRONMENT",
    "LESSONS", "PRETEST", "POSTTEST", "TRANSFER",
}


@dataclass
class PurityViolation:
    subject: str
    kind: str
    detail: str


def _substrate_files() -> List[Path]:
    files = []
    for path in sorted(SUBSTRATE_ROOT.rglob("*.py")):
        if EXCLUDED_PARTS & set(path.relative_to(SUBSTRATE_ROOT).parts):
            continue
        files.append(path)
    return files


def architecture_fingerprint() -> str:
    """SHA-256 over the whole cognitive substrate, path-ordered.

    Includes paths as well as contents, so adding a file changes the
    fingerprint even if every existing file is untouched.
    """
    digest = hashlib.sha256()
    for path in _substrate_files():
        digest.update(str(path.relative_to(SUBSTRATE_ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def substrate_file_count() -> int:
    return len(_substrate_files())


def check_subject_purity(path: Path) -> List[PurityViolation]:
    """A subject must be a declarative record. Parsed, never imported.

    Importing it to inspect it would run whatever it contains, which is
    precisely the thing being checked for.
    """
    name = path.stem
    violations: List[PurityViolation] = []
    tree = ast.parse(path.read_text(), filename=str(path))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.append(PurityViolation(
                name, "defines a function", f"{node.name}() at line {node.lineno}"))
        elif isinstance(node, ast.ClassDef):
            violations.append(PurityViolation(
                name, "defines a class", f"{node.name} at line {node.lineno}"))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            names = [a.name for a in node.names]
            if module.startswith("core") or any(n.startswith("core") for n in names):
                violations.append(PurityViolation(
                    name, "imports the substrate", f"{module or names} at line {node.lineno}"))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in ALLOWED_SUBJECT_NAMES:
                    violations.append(PurityViolation(
                        name, "declares an unexpected name",
                        f"{target.id} at line {node.lineno}"))
        elif isinstance(node, (ast.Expr, ast.Pass)):
            continue                      # docstrings
        else:
            violations.append(PurityViolation(
                name, "contains a statement", f"{type(node).__name__} at line {node.lineno}"))

    # A lambda is a function definition that fits inside an assignment.
    for node in ast.walk(tree):
        if isinstance(node, ast.Lambda):
            violations.append(PurityViolation(
                name, "hides a lambda", f"line {node.lineno}"))
    return violations


def declared_names(path: Path) -> Set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            found |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return found


@dataclass
class FreezeViolation:
    """The substrate changed after the baseline was frozen."""
    frozen_fingerprint: str
    current_fingerprint: str
    frozen_files: int
    current_files: int

    @property
    def message(self) -> str:
        return (
            f"the cognitive substrate has changed since the baseline was frozen "
            f"({self.frozen_fingerprint[:16]}… -> {self.current_fingerprint[:16]}…, "
            f"{self.frozen_files} -> {self.current_files} files). Stage 2 measures "
            f"whether a FROZEN system can be educated; a substrate edited during "
            f"the experiment cannot distinguish 'Torin learned' from 'we upgraded "
            f"Torin while teaching it'. Repair the experiment, not the learner."
        )


def check_freeze(freeze_path: Path) -> Optional[FreezeViolation]:
    """Compare the substrate against the frozen baseline.

    MECHANICAL, NOT A PROMISE. The rule that the implementation may not expand
    during education is the whole basis for reading a Stage 2 gain as learning,
    so it is checked rather than asserted.
    """
    if not freeze_path.exists():
        return None
    frozen = json.loads(freeze_path.read_text())
    current = architecture_fingerprint()
    if current == frozen["architecture_fingerprint"]:
        return None
    return FreezeViolation(
        frozen_fingerprint=frozen["architecture_fingerprint"],
        current_fingerprint=current,
        frozen_files=frozen["substrate_files"],
        current_files=substrate_file_count(),
    )


@dataclass
class GeneralityLedger:
    """Records the fingerprint at every checkpoint of the school day."""
    baseline: str
    checkpoints: Dict[str, str]

    @classmethod
    def open(cls) -> "GeneralityLedger":
        return cls(baseline=architecture_fingerprint(), checkpoints={})

    def check(self, label: str) -> bool:
        current = architecture_fingerprint()
        self.checkpoints[label] = current
        return current == self.baseline

    @property
    def held(self) -> bool:
        return all(v == self.baseline for v in self.checkpoints.values())

    def to_json(self) -> dict:
        return {"baseline_fingerprint": self.baseline,
                "substrate_files": substrate_file_count(),
                "checkpoints": self.checkpoints,
                "architecture_unchanged": self.held}


__all__ = ["check_freeze", "FreezeViolation", "architecture_fingerprint", "substrate_file_count", "check_subject_purity",
           "declared_names", "GeneralityLedger", "PurityViolation",
           "ALLOWED_SUBJECT_NAMES"]
