#!/usr/bin/env python3
"""
Logical formula parsing — the live kernel of the former "logical integration".

This file is now ONE thing: `LogicalFormulaParser`, a strict precedence-climbing
recursive-descent parser that turns a propositional formula into a real syntax
tree (and lowers it to Z3). It is depended on by the authoritative Z3 prover
(advanced_proof_engine), the neural bridge's formalizer (is_formal), and the
abduction reasoning strategy. Parsing is strict: anything outside the grammar
raises FormulaSyntaxError rather than being silently atomised.

The former inference/validator/proof System that wrapped this parser was removed
(2026-09-01) — it was dead + redundant with the Z3 proof engine and the
unifier. See the removal note at the bottom of this file.
"""

import logging
import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class LogicType(Enum):
    """Types of logic systems"""
    PROPOSITIONAL = "propositional"
    FIRST_ORDER = "first_order"
    MODAL = "modal"
    TEMPORAL = "temporal"
    FUZZY = "fuzzy"


class Operator(Enum):
    """Logical operators"""
    AND = "∧"
    OR = "∨"
    NOT = "¬"
    IMPLIES = "→"
    IFF = "↔"
    FORALL = "∀"
    EXISTS = "∃"
    NECESSITY = "□"
    POSSIBILITY = "◊"


@dataclass
class LogicalFormula:
    """Logical formula representation"""
    formula_id: str
    formula_text: str
    logic_type: LogicType

    # Formula metadata
    variables: List[str] = field(default_factory=list)
    predicates: List[str] = field(default_factory=list)
    operators: List[str] = field(default_factory=list)

    # Validation
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)

    # Parsed syntax tree, or None when the formula failed to parse. Consumers
    # that need structure (SMT translation) read this instead of re-parsing
    # formula_text.
    ast: Optional[Any] = None

    # Semantics
    truth_value: Optional[bool] = None
    satisfiable: bool = True

    timestamp: datetime = field(default_factory=datetime.now)


class FormulaSyntaxError(ValueError):
    """Raised when a formula cannot be parsed in the supported grammar."""


class LogicalFormulaParser:
    """Parser for logical formulas.

    Produces a real syntax tree via precedence climbing over self.precedence,
    so downstream consumers (the SMT proof engine) get structure rather than a
    bag of extracted tokens.

    Parsing is strict: anything outside the grammar raises FormulaSyntaxError
    instead of being coerced into an atom. Natural language must fail loudly
    here, because a silently-atomised premise makes a valid theorem
    unprovable with no error to explain why.
    """

    def __init__(self):
        # Symbol mappings
        self.symbol_map = {
            "AND": "∧",
            "&": "∧",
            "and": "∧",
            "OR": "∨",
            "|": "∨",
            "or": "∨",
            "NOT": "¬",
            "~": "¬",
            "not": "¬",
            "IMPLIES": "→",
            "->": "→",
            "implies": "→",
            "IFF": "↔",
            "<->": "↔",
            "iff": "↔",
            "FORALL": "∀",
            "forall": "∀",
            "EXISTS": "∃",
            "exists": "∃",
            "NECESSITY": "□",
            "necessity": "□",
            "POSSIBILITY": "◊",
            "possibility": "◊"
        }

        # Operator precedence (tightest binding first). This drives the
        # precedence-climbing parser below.
        self.precedence = {
            "¬": 4,
            "∧": 3,
            "∨": 2,
            "→": 1,
            "↔": 1
        }

        # Implication and equivalence group to the right: a → b → c is
        # a → (b → c). Conjunction and disjunction group to the left.
        self.right_associative = {"→", "↔"}

        # Canonical binary operator -> AST node kind
        self.binary_nodes = {
            "∧": "and",
            "∨": "or",
            "→": "implies",
            "↔": "iff",
        }

        # Multi-character symbols are matched longest-first so that '<->'
        # wins over '<' plus '->', and '&&' over '&'.
        self._symbol_tokens = sorted(
            [
                ("<->", "↔"), ("<=>", "↔"), ("↔", "↔"),
                ("->", "→"), ("=>", "→"), ("→", "→"),
                ("&&", "∧"), ("&", "∧"), ("∧", "∧"),
                ("||", "∨"), ("|", "∨"), ("∨", "∨"),
                ("~", "¬"), ("!", "¬"), ("¬", "¬"),
            ],
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

        # Word operators are recognised only as complete identifiers, so
        # 'android' stays an atom instead of becoming '∧roid'.
        self._word_tokens = {
            "AND": "∧",
            "OR": "∨",
            "NOT": "¬",
            "IMPLIES": "→",
            "IFF": "↔",
        }

        # Quantifiers are tokenised so they can be rejected with a clear
        # message rather than silently parsed as propositional atoms.
        self._quantifier_tokens = {
            "FORALL": "∀", "∀": "∀",
            "EXISTS": "∃", "∃": "∃",
        }

    def parse(self, formula_text: str, logic_type: LogicType = LogicType.PROPOSITIONAL) -> LogicalFormula:
        """Parse a logical formula, reporting failure rather than guessing.

        A formula that does not parse comes back with is_valid=False and the
        reason in validation_errors; it never comes back as a bare atom.
        """
        # Identifiers were previously derived from whole-second timestamps, so
        # formulas parsed in the same second collided and overwrote each other
        # in the caller's formula store.
        formula_id = f"formula_{uuid.uuid4().hex[:12]}"

        try:
            ast_node = self.parse_ast(formula_text, logic_type)
        except FormulaSyntaxError as e:
            logger.debug(f"Formula parsing failed for {formula_text!r}: {e}")
            return LogicalFormula(
                formula_id=formula_id,
                formula_text=str(formula_text).strip(),
                logic_type=logic_type,
                is_valid=False,
                validation_errors=[str(e)]
            )

        atoms = sorted(self.formula_atoms(ast_node))
        return LogicalFormula(
            formula_id=formula_id,
            formula_text=self.render(ast_node),
            logic_type=logic_type,
            variables=[name for name in atoms if "(" not in name],
            predicates=[name for name in atoms if "(" in name],
            operators=sorted(self._operators_in(ast_node)),
            is_valid=True,
            validation_errors=[],
            ast=ast_node
        )

    def parse_ast(self, formula_text: str, logic_type: LogicType = LogicType.PROPOSITIONAL) -> Any:
        """Parse a formula into a syntax tree, raising on malformed input."""
        if formula_text is None or not str(formula_text).strip():
            raise FormulaSyntaxError("empty formula")

        source = str(formula_text).strip()
        state = {"tokens": self._tokenize(source), "pos": 0, "source": source}

        node = self._parse_expression(state, min_precedence=1)

        kind, value, position = state["tokens"][state["pos"]]
        if kind != "EOF":
            raise FormulaSyntaxError(
                f"unexpected {value!r} at position {position} in {source!r}"
            )
        return node

    def is_formal(self, formula_text: str) -> bool:
        """True when the text is already expressible in the formal grammar."""
        try:
            self.parse_ast(formula_text)
            return True
        except FormulaSyntaxError:
            return False

    def _tokenize(self, text: str) -> List[Tuple[str, str, int]]:
        """Split a formula into (kind, canonical_value, position) triples.

        Word operators are matched only as whole identifiers. The previous
        implementation normalised by running str.replace() for every entry in
        the symbol table, which rewrote operator names occurring *inside*
        identifiers -- 'android' became '∧roid' and 'notion' became '¬ion',
        both still reported valid.
        """
        tokens: List[Tuple[str, str, int]] = []
        index, length = 0, len(text)

        while index < length:
            char = text[index]

            if char.isspace():
                index += 1
                continue

            if char.isalpha() or char == "_":
                start = index
                while index < length and (text[index].isalnum() or text[index] in "_."):
                    index += 1
                word = text[start:index]
                upper = word.upper()

                if upper in self._word_tokens:
                    tokens.append(("OP", self._word_tokens[upper], start))
                    continue
                if upper in self._quantifier_tokens:
                    tokens.append(("QUANT", self._quantifier_tokens[upper], start))
                    continue

                # Ground predicates such as P(x) or Q(x, y) are treated as
                # single propositional atoms. Only simple argument lists
                # qualify, so '(' opening a real subformula is untouched.
                if index < length and text[index] == "(":
                    close = text.find(")", index)
                    if close != -1:
                        arguments = text[index + 1:close]
                        if arguments and all(c.isalnum() or c in "_,. " for c in arguments):
                            joined = ",".join(a.strip() for a in arguments.split(","))
                            word = f"{word}({joined})"
                            index = close + 1

                tokens.append(("IDENT", word, start))
                continue

            if char == "(":
                tokens.append(("LPAREN", char, index))
                index += 1
                continue

            if char == ")":
                tokens.append(("RPAREN", char, index))
                index += 1
                continue

            if char in self._quantifier_tokens:
                tokens.append(("QUANT", self._quantifier_tokens[char], index))
                index += 1
                continue

            for symbol, canonical in self._symbol_tokens:
                if text.startswith(symbol, index):
                    tokens.append(("OP", canonical, index))
                    index += len(symbol)
                    break
            else:
                raise FormulaSyntaxError(
                    f"unexpected character {char!r} at position {index} in {text!r}"
                )

        tokens.append(("EOF", "", length))
        return tokens

    def _parse_expression(self, state: Dict[str, Any], min_precedence: int) -> Any:
        """Precedence-climbing parse of binary operators."""
        left = self._parse_unary(state)

        while True:
            kind, value, _ = state["tokens"][state["pos"]]
            if kind != "OP" or value not in self.binary_nodes:
                break

            precedence = self.precedence[value]
            if precedence < min_precedence:
                break

            state["pos"] += 1
            # Right-associative operators recurse at the same precedence so
            # they group rightward; left-associative ones step up by one.
            next_minimum = precedence if value in self.right_associative else precedence + 1
            right = self._parse_expression(state, next_minimum)
            left = (self.binary_nodes[value], left, right)

        return left

    def _parse_unary(self, state: Dict[str, Any]) -> Any:
        """Parse negation, parentheses and atoms.

        Negation is handled here rather than as a binary case, which is what
        makes it bind tighter than conjunction: '~a & b' is (~a) & b.
        """
        kind, value, position = state["tokens"][state["pos"]]

        if kind == "OP" and value == "¬":
            state["pos"] += 1
            return ("not", self._parse_unary(state))

        if kind == "QUANT":
            raise FormulaSyntaxError(
                f"quantifier {value!r} at position {position} is not supported: "
                f"the SMT backend is propositional, so quantified formulas "
                f"cannot be proved rather than being silently treated as atoms"
            )

        if kind == "IDENT":
            state["pos"] += 1
            return ("atom", value)

        if kind == "LPAREN":
            state["pos"] += 1
            node = self._parse_expression(state, min_precedence=1)
            closing_kind, closing_value, closing_position = state["tokens"][state["pos"]]
            if closing_kind != "RPAREN":
                raise FormulaSyntaxError(
                    f"expected ')' but found {closing_value!r} at position "
                    f"{closing_position} in {state['source']!r}"
                )
            state["pos"] += 1
            return node

        raise FormulaSyntaxError(
            f"expected an atom or '(' but found {value!r} at position "
            f"{position} in {state['source']!r}"
        )

    def formula_atoms(self, node: Any, into: Optional[Set[str]] = None) -> Set[str]:
        """Collect every atom name appearing in a syntax tree."""
        atoms: Set[str] = set() if into is None else into
        if node[0] == "atom":
            atoms.add(node[1])
        elif node[0] == "not":
            self.formula_atoms(node[1], atoms)
        else:
            self.formula_atoms(node[1], atoms)
            self.formula_atoms(node[2], atoms)
        return atoms

    def _operators_in(self, node: Any, into: Optional[Set[str]] = None) -> Set[str]:
        """Collect the canonical operator symbols used in a syntax tree."""
        operators: Set[str] = set() if into is None else into
        kind = node[0]
        if kind == "atom":
            return operators
        if kind == "not":
            operators.add("¬")
            self._operators_in(node[1], operators)
            return operators
        for symbol, node_kind in self.binary_nodes.items():
            if node_kind == kind:
                operators.add(symbol)
                break
        self._operators_in(node[1], operators)
        self._operators_in(node[2], operators)
        return operators

    def render(self, node: Any) -> str:
        """Render a syntax tree back to canonical, fully-parenthesised text."""
        kind = node[0]
        if kind == "atom":
            return node[1]
        if kind == "not":
            return f"¬{self.render(node[1])}"
        for symbol, node_kind in self.binary_nodes.items():
            if node_kind == kind:
                return f"({self.render(node[1])} {symbol} {self.render(node[2])})"
        raise FormulaSyntaxError(f"unknown node kind {kind!r}")

    def to_z3(self, node: Any, z3_vars: Dict[str, Any]) -> Any:
        """Convert a syntax tree into a Z3 expression.

        z3_vars must already declare every atom from formula_atoms(); a missing
        entry is a caller bug, not licence to invent a symbol.
        """
        from z3 import And, Implies, Not, Or

        kind = node[0]
        if kind == "atom":
            name = node[1]
            if name not in z3_vars:
                raise KeyError(f"no Z3 variable declared for atom {name!r}")
            return z3_vars[name]
        if kind == "not":
            return Not(self.to_z3(node[1], z3_vars))
        if kind == "and":
            return And(self.to_z3(node[1], z3_vars), self.to_z3(node[2], z3_vars))
        if kind == "or":
            return Or(self.to_z3(node[1], z3_vars), self.to_z3(node[2], z3_vars))
        if kind == "implies":
            return Implies(self.to_z3(node[1], z3_vars), self.to_z3(node[2], z3_vars))
        if kind == "iff":
            return self.to_z3(node[1], z3_vars) == self.to_z3(node[2], z3_vars)
        raise FormulaSyntaxError(f"unknown node kind {kind!r}")


# ── REMOVED (2026-09-01) ─────────────────────────────────────────────────
# LogicalInferenceEngine, LogicalReasoningValidator, LogicalIntegrationSystem
# and get_logical_integration() were removed. They were DEAD + REDUNDANT: no
# live caller invoked their inference/proof methods; prove_theorem merely
# re-wrapped the real Z3 prover (advanced_proof_engine.get_proof_engine) with
# lossy hardcoded steps, and the string-matching InferenceEngine was a
# unification-free re-implementation of unification.py. The LIVE kernel of
# this file is LogicalFormulaParser (formula -> AST -> Z3), depended on by
# advanced_proof_engine, neural_bridge's formalizer, and the abduction
# strategy. Full pre-prune copy: archive/llm_era_reasoning_2026-09-01/
# logical_integration_full_pre_prune.py
