#!/usr/bin/env python3
"""Capability-integrity guard.

The invariant is NOT "no public name may be None" -- optional dependencies are
legitimate. The invariant is:

    Nothing advertised as available may resolve to None, and an unavailable
    capability must be explicitly represented as unavailable.

A bare `except ImportError: X = None` violates this by converting an
initialization defect into a distant runtime defect: the symbol exists, so
`if X is not None` guards pass, `from pkg import X` succeeds, and the failure
surfaces somewhere far away with no link to its cause. That mechanism is how
`create_agents_system` -- a name defined NOWHERE in the codebase -- survived in
the public surface long enough for the entire multi-agent layer to go unnoticed
as dead code.

Four contradictions are failures. Each is a statement the package makes about
itself that its own contents deny:

  C1  EXPORTED_BUT_NONE        name is in __all__ and resolves to None
  C2  ADVERTISED_BUT_ABSENT    a guarded import names a symbol its source module
                               does not define (the import can never succeed)
  C3  FLAG_TRUE_BUT_NONE       a *_AVAILABLE flag is True while the symbols it
                               guards are None
  C4  ASYMMETRIC_BINDING       a class is None while its paired factory is a live
                               callable, so `is not None` guards pass and the
                               ImportError is deferred to call time

Run:  venv_torin/bin/python tests/test_capability_integrity.py
"""

from __future__ import annotations

import ast
import importlib
import os
import pkgutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Modules that must not be imported for side-effect reasons (start servers,
# open sockets, spawn loops). Keep this list SHORT and justified.
SKIP_PREFIXES = (
    "core.api.chat_server",
    "core.main",
)


def _iter_modules() -> List[str]:
    names = []
    for mod in pkgutil.walk_packages([str(ROOT / "core")], prefix="core."):
        if mod.name.startswith(SKIP_PREFIXES):
            continue
        names.append(mod.name)
    return sorted(names)


def _guarded_imports(path: Path) -> List[Tuple[str, str, int]]:
    """Return (source_module, symbol, lineno) for imports inside try/except."""
    out: List[Tuple[str, str, int]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.ImportFrom) and stmt.module:
                mod = ("." * (stmt.level or 0)) + stmt.module
                for alias in stmt.names:
                    if alias.name == "*":
                        continue  # star import names no specific symbol
                    out.append((mod, alias.name, stmt.lineno))
    return out


def _resolve_relative(base_pkg: str, mod: str) -> str:
    if not mod.startswith("."):
        return mod
    level = len(mod) - len(mod.lstrip("."))
    tail = mod.lstrip(".")
    parts = base_pkg.split(".")
    anchor = parts[: len(parts) - level + 1] if level > 1 else parts
    return ".".join([p for p in (".".join(anchor), tail) if p])


def check() -> Dict[str, List[str]]:
    violations: Dict[str, List[str]] = {
        "C1_EXPORTED_BUT_NONE": [],
        "C2_ADVERTISED_BUT_ABSENT": [],
        "C3_FLAG_TRUE_BUT_NONE": [],
        "C4_ASYMMETRIC_BINDING": [],
    }

    for name in _iter_modules():
        try:
            mod = importlib.import_module(name)
        except Exception:
            # A module that cannot import at all is a different (louder) problem;
            # this guard is about modules that import "successfully" while lying.
            continue

        exported = getattr(mod, "__all__", None) or []

        # ---- C1: exported but None -------------------------------------
        for sym in exported:
            if getattr(mod, sym, "<missing>") is None:
                violations["C1_EXPORTED_BUT_NONE"].append(f"{name}.{sym}")

        # ---- C2: guarded import names a symbol its source does not define
        modfile = getattr(mod, "__file__", None)
        if modfile:
            base_pkg = name if hasattr(mod, "__path__") else name.rsplit(".", 1)[0]
            for src, sym, lineno in _guarded_imports(Path(modfile)):
                target = _resolve_relative(base_pkg, src)
                try:
                    srcmod = importlib.import_module(target)
                except Exception:
                    continue  # source itself unimportable -- not this check's job
                if not hasattr(srcmod, sym):
                    violations["C2_ADVERTISED_BUT_ABSENT"].append(
                        f"{name}:{lineno} imports '{sym}' from '{target}' "
                        f"-- '{sym}' is not defined there"
                    )

        # ---- C3: availability flag True while its symbols are None ------
        for attr in dir(mod):
            if not attr.endswith("_AVAILABLE"):
                continue
            if getattr(mod, attr, None) is not True:
                continue
            stem = attr[: -len("_AVAILABLE")].lower()
            for sym in list(exported) + [a for a in dir(mod) if not a.startswith("_")]:
                if stem and stem.split("_")[0] in sym.lower():
                    if getattr(mod, sym, "<missing>") is None:
                        violations["C3_FLAG_TRUE_BUT_NONE"].append(
                            f"{name}.{attr} is True but {name}.{sym} is None"
                        )

        # ---- C4: class None while paired factory is callable ------------
        publics = [a for a in dir(mod) if not a.startswith("_")]
        for sym in publics:
            if getattr(mod, sym, "<missing>") is not None:
                continue
            for factory in publics:
                if not (factory.startswith("get_") or factory.startswith("create_")):
                    continue
                fval = getattr(mod, factory, None)
                if not callable(fval):
                    continue
                stem = factory.split("_", 1)[1].replace("_", "").lower()
                if stem and stem in sym.replace("_", "").lower():
                    violations["C4_ASYMMETRIC_BINDING"].append(
                        f"{name}: class '{sym}' is None but factory "
                        f"'{factory}' is callable -- guards pass, call explodes"
                    )

    return violations


def main() -> int:
    v = check()
    total = sum(len(x) for x in v.values())

    print("=" * 78)
    print("CAPABILITY INTEGRITY")
    print("  Nothing advertised as available may resolve to None.")
    print("=" * 78)
    for cls, items in v.items():
        print(f"\n{cls}: {len(items)}")
        for i in sorted(set(items)):
            print(f"    {i}")

    print("\n" + "=" * 78)
    print(f"TOTAL CONTRADICTIONS: {total}")
    print("=" * 78)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
