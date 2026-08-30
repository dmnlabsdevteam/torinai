#!/usr/bin/env python3
"""A real world where the values a plan needs do not exist until it runs.

`list_machine` proved the substrate can build a fold out of instructions.
`data_world` proved it can compose operations. Neither has the property that
makes program composition hard: an intermediate value that NOTHING can know
before an earlier step actually executes.

Here it does. Registers are files on disk; the input is a file whose contents
the substrate has never seen. What the read returns, what the parse yields, and
therefore what the multiply produces are all unknown at planning time, and the
plan has to be built anyway.

    READ(f)        copy_file    source -> text register
    PARSE_NUMBER   copy_file    text -> number register
    MULTIPLY       run_python   number x factor -> product register
    WRITE          copy_file    product -> output register

EVERY ACTION IS A REAL REGISTERED TOOL, invoked through the tool registry, and
`observe()` reads the filesystem afterwards. Nothing here reports what a tool
claimed; the world is read back independently, which is what lets the multiply's
computed prediction be CHECKED rather than believed.

WHETHER SOMETHING IS A NUMBER IS THE WORLD'S VERDICT, NOT THE PARSER'S.
PARSE_NUMBER moves text into the number register whatever the text is. The
observer emits NUMBER only when the register actually holds one. So a file
containing "hello" produces a register the substrate predicted would hold a
number and does not -- a contradiction the substrate finds out about, rather
than a value it invents to keep going.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact, canonical_term, is_number

ACTIONS = ("READ", "PARSE_NUMBER", "MULTIPLY", "WRITE")

_TERM = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$|^-?\d+(?:\.\d+)?$")


def _term(text: str) -> Optional[str]:
    """One term per readable value, or None where the world holds something it
    cannot represent -- which is reported as an absence, never as a guess."""
    stripped = (text or "").strip()
    return canonical_term(stripped) if _TERM.match(stripped) else None


class ComputationWorld:
    """Registers are files. What they will hold is not knowable in advance."""

    TEXT, NUMBER, PRODUCT, OUTPUT = "text.dat", "number.dat", "product.dat", "output.dat"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- setting the problem up -----------------------------------------

    def put_source(self, name: str, contents: str) -> "ComputationWorld":
        (self.root / f"{name}.txt").write_text(contents)
        return self

    def put_factor(self, value) -> "ComputationWorld":
        (self.root / "factor.txt").write_text(str(value))
        return self

    def clear_registers(self) -> "ComputationWorld":
        for register in (self.TEXT, self.NUMBER, self.PRODUCT, self.OUTPUT):
            (self.root / register).unlink(missing_ok=True)
        return self

    # ---- the world -------------------------------------------------------

    def _read(self, register: str) -> Optional[str]:
        path = self.root / register
        return _term(path.read_text()) if path.exists() else None

    def observe(self) -> Optional[FrozenSet[Fact]]:
        if not self.root.exists():
            return None
        facts = set()
        for source in sorted(self.root.glob("*.txt")):
            if source.name != "factor.txt":
                facts.add(Fact("FILE", (source.stem,)))
        factor = self._read("factor.txt") if (self.root / "factor.txt").exists() else None
        if factor is not None and is_number(factor):
            facts.add(Fact("FACTOR", (factor,)))

        text = self._read(self.TEXT)
        if text is not None:
            facts.add(Fact("TEXT", (text,)))
        for register, predicate in ((self.NUMBER, "NUMBER"), (self.PRODUCT, "PRODUCT"),
                                    (self.OUTPUT, "WRITTEN")):
            value = self._read(register)
            # Only a number counts. A register holding `hello` is a register
            # that does not hold a number, and saying otherwise would let the
            # next step compute with it.
            if value is not None and is_number(value):
                facts.add(Fact(predicate, (value,)))
        return frozenset(facts)

    # ---- binding ---------------------------------------------------------

    def _copy(self, source: str, destination: str) -> Dict[str, Any]:
        return {"source_path": str(self.root / source),
                "destination_path": str(self.root / destination),
                "create_dirs": False}

    def _multiply_script(self) -> str:
        return (
            f"number = open({str(self.root / self.NUMBER)!r}).read().strip()\n"
            f"factor = open({str(self.root / 'factor.txt')!r}).read().strip()\n"
            f"product = float(number) * float(factor)\n"
            f"product = int(product) if product.is_integer() else product\n"
            f"open({str(self.root / self.PRODUCT)!r}, 'w').write(str(product))\n"
        )

    def parameters(self, predicate: str):
        if predicate == "READ":
            return lambda args: self._copy(f"{args[0]}.txt", self.TEXT)
        if predicate == "PARSE_NUMBER":
            return lambda args: self._copy(self.TEXT, self.NUMBER)
        if predicate == "WRITE":
            return lambda args: self._copy(self.PRODUCT, self.OUTPUT)
        return lambda args: {"code": self._multiply_script()}

    def binding(self, predicate: str) -> OperatorBinding:
        return OperatorBinding(
            predicate=predicate,
            tool_name="run_python" if predicate == "MULTIPLY" else "copy_file",
            parameters=self.parameters(predicate),
            observe=self.observe,
            description="registers are files; what they will hold is not known in advance",
        )

    def register(self, domain_id: str) -> "ComputationWorld":
        for predicate in ACTIONS:
            get_binding_registry().register(domain_id, self.binding(predicate))
        return self


__all__ = ["ComputationWorld", "ACTIONS"]
