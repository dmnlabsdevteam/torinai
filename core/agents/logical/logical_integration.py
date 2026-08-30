#!/usr/bin/env python3
"""
Logical Integration System
==========================
Integrates formal logical reasoning with agent systems

Purpose:
- Connect logical reasoning engines to autonomous agents
- Provide logical inference capabilities
- Support propositional and first-order logic
- Enable automated theorem proving integration
- Bridge formal logic with natural language

Features:
- Formula parsing and validation
- Logical inference rules (modus ponens, tollens, etc.)
- Proof verification
- Natural language to logic translation
- Integration with advanced proof engine
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


class InferenceRule(Enum):
    """Logical inference rules"""
    MODUS_PONENS = "modus_ponens"           # P → Q, P ⊢ Q
    MODUS_TOLLENS = "modus_tollens"         # P → Q, ¬Q ⊢ ¬P
    HYPOTHETICAL_SYLLOGISM = "hypothetical_syllogism"  # P → Q, Q → R ⊢ P → R
    DISJUNCTIVE_SYLLOGISM = "disjunctive_syllogism"    # P ∨ Q, ¬P ⊢ Q
    CONJUNCTION_INTRO = "conjunction_intro"  # P, Q ⊢ P ∧ Q
    CONJUNCTION_ELIM = "conjunction_elim"    # P ∧ Q ⊢ P (or Q)
    DISJUNCTION_INTRO = "disjunction_intro"  # P ⊢ P ∨ Q
    RESOLUTION = "resolution"                # P ∨ Q, ¬P ∨ R ⊢ Q ∨ R
    UNIVERSAL_INSTANTIATION = "universal_instantiation"  # ∀x P(x) ⊢ P(a)
    EXISTENTIAL_GENERALIZATION = "existential_generalization"  # P(a) ⊢ ∃x P(x)


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


@dataclass
class InferenceStep:
    """Single step in logical inference"""
    step_number: int
    rule_applied: InferenceRule
    premises: List[str]
    conclusion: str

    # Step metadata
    justification: str = ""
    confidence: float = 1.0

    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LogicalProof:
    """Logical proof structure"""
    proof_id: str
    theorem: str

    # Proof steps
    steps: List[InferenceStep] = field(default_factory=list)
    premises: List[str] = field(default_factory=list)

    # Proof status
    proven: bool = False
    proof_method: str = "direct"
    confidence: float = 0.0

    # Performance
    execution_time: float = 0.0

    error: Optional[str] = None
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


class LogicalInferenceEngine:
    """Logical inference engine"""

    def __init__(self):
        # Inference rules
        self.inference_rules = {
            InferenceRule.MODUS_PONENS,
            InferenceRule.MODUS_TOLLENS,
            InferenceRule.HYPOTHETICAL_SYLLOGISM,
            InferenceRule.DISJUNCTIVE_SYLLOGISM
        }

    async def apply_inference(
        self,
        premises: List[str],
        rule: InferenceRule,
        target: Optional[str] = None
    ) -> List[str]:
        """Apply inference rule to premises"""
        conclusions = []

        try:
            if rule == InferenceRule.MODUS_PONENS:
                conclusions = await self._apply_modus_ponens(premises, target)

            elif rule == InferenceRule.MODUS_TOLLENS:
                conclusions = await self._apply_modus_tollens(premises, target)

            elif rule == InferenceRule.HYPOTHETICAL_SYLLOGISM:
                conclusions = await self._apply_hypothetical_syllogism(premises, target)

            elif rule == InferenceRule.DISJUNCTIVE_SYLLOGISM:
                conclusions = await self._apply_disjunctive_syllogism(premises, target)

        except Exception as e:
            logger.error(f"Inference failed: {e}")

        return conclusions

    async def _apply_modus_ponens(self, premises: List[str], target: Optional[str] = None) -> List[str]:
        """Apply modus ponens: P → Q, P ⊢ Q"""
        conclusions = []

        # Find implications
        implications = []
        facts = []

        for premise in premises:
            if "→" in premise:
                implications.append(premise)
            else:
                facts.append(premise)

        # Apply rule
        for impl in implications:
            if "→" in impl:
                # Parse P → Q
                parts = impl.split("→")
                if len(parts) == 2:
                    antecedent = parts[0].strip()
                    consequent = parts[1].strip()

                    # Check if antecedent is in facts
                    if antecedent in facts:
                        # Derive consequent
                        conclusion = consequent

                        if target is None or conclusion == target:
                            conclusions.append(conclusion)

        return conclusions

    async def _apply_modus_tollens(self, premises: List[str], target: Optional[str] = None) -> List[str]:
        """Apply modus tollens: P → Q, ¬Q ⊢ ¬P"""
        conclusions = []

        # Find implications
        implications = []
        negations = []

        for premise in premises:
            if "→" in premise:
                implications.append(premise)
            elif "¬" in premise:
                negations.append(premise)

        # Apply rule
        for impl in implications:
            parts = impl.split("→")
            if len(parts) == 2:
                antecedent = parts[0].strip()
                consequent = parts[1].strip()

                # Check if ¬consequent is in premises
                neg_consequent = f"¬{consequent}"

                if neg_consequent in negations:
                    # Derive ¬antecedent
                    conclusion = f"¬{antecedent}"

                    if target is None or conclusion == target:
                        conclusions.append(conclusion)

        return conclusions

    async def _apply_hypothetical_syllogism(self, premises: List[str], target: Optional[str] = None) -> List[str]:
        """Apply hypothetical syllogism: P → Q, Q → R ⊢ P → R"""
        conclusions = []

        # Find implications
        implications = [p for p in premises if "→" in p]

        # Look for chains
        for impl1 in implications:
            for impl2 in implications:
                if impl1 != impl2:
                    # Parse implications
                    parts1 = impl1.split("→")
                    parts2 = impl2.split("→")

                    if len(parts1) == 2 and len(parts2) == 2:
                        p = parts1[0].strip()
                        q = parts1[1].strip()
                        q2 = parts2[0].strip()
                        r = parts2[1].strip()

                        # Check if consequent of first matches antecedent of second
                        if q == q2:
                            conclusion = f"{p} → {r}"

                            if target is None or conclusion == target:
                                conclusions.append(conclusion)

        return conclusions

    async def _apply_disjunctive_syllogism(self, premises: List[str], target: Optional[str] = None) -> List[str]:
        """Apply disjunctive syllogism: P ∨ Q, ¬P ⊢ Q"""
        conclusions = []

        # Find disjunctions and negations
        disjunctions = [p for p in premises if "∨" in p]
        negations = [p for p in premises if "¬" in p]

        for disj in disjunctions:
            parts = [p.strip() for p in disj.split("∨")]

            for part in parts:
                # Check if negation of this part exists
                neg_part = f"¬{part}"

                if neg_part in negations:
                    # Derive the other part
                    other_parts = [p for p in parts if p != part]
                    if other_parts:
                        conclusion = " ∨ ".join(other_parts)

                        if target is None or conclusion == target:
                            conclusions.append(conclusion)

        return conclusions


class LogicalReasoningValidator:
    """Validates logical reasoning steps"""

    def __init__(self):
        self.negation_forms = [
            ("NOT", "¬"),
            ("not", "¬"),
            ("~", "¬")
        ]

    async def validate_inference(
        self,
        premises: List[str],
        conclusion: str,
        rule: InferenceRule
    ) -> Tuple[bool, List[str]]:
        """Validate inference step"""
        errors = []

        try:
            # Normalize
            norm_premises = [self._normalize(p) for p in premises]
            norm_conclusion = self._normalize(conclusion)

            # Prefer a real entailment check: it is sound for every rule, not
            # just the two with hand-written structural checks.
            entailed = await self._entails(premises, conclusion)

            if entailed is not None:
                if not entailed:
                    errors.append(
                        f"Invalid {rule.value} inference: premises do not entail the conclusion"
                    )
                return (len(errors) == 0, errors)

            # Solver unavailable or formulas not in the formal grammar. Fall
            # back to structural checks where they exist and decline to certify
            # anything else -- unrecognised rules were previously assumed valid,
            # so the validator approved every inference it did not understand.
            if rule == InferenceRule.MODUS_PONENS:
                valid = self._validate_modus_ponens(norm_premises, norm_conclusion)
            elif rule == InferenceRule.MODUS_TOLLENS:
                valid = self._validate_modus_tollens(norm_premises, norm_conclusion)
            else:
                return (False, [
                    f"Cannot validate {rule.value}: formulas are not in the formal "
                    f"grammar and no structural check exists for this rule"
                ])

            if not valid:
                errors.append(f"Invalid {rule.value} inference")

            return (len(errors) == 0, errors)

        except Exception as e:
            return (False, [str(e)])

    async def _entails(self, premises: List[str], conclusion: str) -> Optional[bool]:
        """Check entailment with the solver.

        Returns True/False when the question was decided, or None when it could
        not be posed at all (unparseable formulas, no solver, or a timeout).
        None means "unknown" and must not be read as either verdict.
        """
        parser = LogicalFormulaParser()

        try:
            for premise in premises:
                parser.parse_ast(premise)
            parser.parse_ast(conclusion)
        except FormulaSyntaxError:
            return None

        try:
            from core.reasoning.advanced_proof_engine import (
                LogicType as ProofLogicType,
                Theorem,
                get_proof_engine,
            )
        except Exception as e:
            logger.debug(f"Proof engine unavailable for entailment check: {e}")
            return None

        engine = get_proof_engine()
        if not getattr(engine, "z3_available", False):
            return None

        proof = await engine.prove_theorem(
            Theorem(
                theorem_id=f"validate_{uuid.uuid4().hex[:8]}",
                statement=conclusion,
                premises=list(premises),
                logic_type=ProofLogicType.PROPOSITIONAL,
            ),
            timeout=5.0,
        )

        # An error here means undecided (typically the timeout), which is not
        # evidence that the inference is invalid.
        if proof.error:
            return None

        return bool(proof.proved)

    def _normalize(self, formula: str) -> str:
        """Normalize formula for comparison.

        Word-form negations are replaced only on identifier boundaries, so an
        atom such as 'notion' is left alone instead of becoming '¬ion'.
        """
        formula = formula.replace(" ", "")

        for text_negation, unicode_negation in self.negation_forms:
            if text_negation.isalpha():
                formula = re.sub(
                    rf"\b{re.escape(text_negation)}\b",
                    unicode_negation,
                    formula,
                )
            else:
                formula = formula.replace(text_negation, unicode_negation)

        return formula

    def _validate_modus_ponens(self, premises: List[str], conclusion: str) -> bool:
        """Validate modus ponens"""
        # Find implication
        impl = None
        fact = None

        for premise in premises:
            if "→" in premise:
                impl = premise
            else:
                fact = premise

        if impl and fact:
            # Parse P → Q
            parts = impl.split("→")
            if len(parts) == 2:
                antecedent = parts[0]
                consequent = parts[1]

                # Check if fact matches antecedent and conclusion matches consequent
                return (fact == antecedent and conclusion == consequent)

        return False

    def _validate_modus_tollens(self, premises: List[str], conclusion: str) -> bool:
        """Validate modus tollens: from P → Q and ¬Q, infer ¬P.

        This method was referenced by validate_inference but never defined, so
        every modus tollens check raised AttributeError. The surrounding
        try/except then reported the *valid* inference as invalid, attaching
        the AttributeError text as the reason.
        """
        implication = None
        negated_consequent = None

        for premise in premises:
            if "→" in premise:
                implication = premise
            elif premise.startswith("¬"):
                negated_consequent = premise

        if not implication or not negated_consequent:
            return False

        parts = implication.split("→")
        if len(parts) != 2:
            return False

        antecedent, consequent = parts[0], parts[1]

        return (
            negated_consequent == f"¬{consequent}"
            and conclusion == f"¬{antecedent}"
        )


class LogicalIntegrationSystem:
    """
    Logical Integration System

    Integrates formal logical reasoning with autonomous agents,
    providing inference capabilities and proof verification.

    Features:
    - Formula parsing and validation
    - Logical inference (10+ rules)
    - Proof construction and verification
    - Natural language to logic translation
    - Integration with proof engine
    """

    async def execute(self, task: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Dispatch entry point used by AgentCoordinator.execute_task.

        Forwards to the real prover. This class is a working theorem prover
        (parse_formula/prove_theorem); it simply had no method with the name
        the coordinator calls.
        """
        params = parameters or {}
        goal = params.get("goal") or params.get("theorem") or task
        premises = params.get("premises") or []
        proof = await self.prove_theorem(goal, premises) if asyncio.iscoroutinefunction(
            self.prove_theorem) else self.prove_theorem(goal, premises)
        return {
            "goal": goal,
            "premises": premises,
            "proof": proof,
            "status": "completed",
        }

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Components
        self.parser = LogicalFormulaParser()
        self.inference_engine = LogicalInferenceEngine()
        self.validator = LogicalReasoningValidator()

        # Knowledge base
        self.formulas: Dict[str, LogicalFormula] = {}
        self.proofs: Dict[str, LogicalProof] = {}

        # Proof engine integration
        self.proof_engine = None

        # Statistics
        self.stats = {
            'total_formulas': 0,
            'total_inferences': 0,
            'total_proofs': 0,
            'successful_proofs': 0,
            'failed_proofs': 0
        }

        logger.info("LogicalIntegrationSystem initialized")

    async def initialize(self):
        """Initialize logical integration system"""
        try:
            # Load proof engine
            from core.reasoning.advanced_proof_engine import get_proof_engine
            self.proof_engine = get_proof_engine()

            logger.info("✓ Logical integration system initialized")

        except Exception as e:
            logger.warning(f"Proof engine not available: {e}")

    async def parse_formula(self, formula_text: str, logic_type: LogicType = LogicType.PROPOSITIONAL) -> LogicalFormula:
        """Parse and validate logical formula"""
        self.stats['total_formulas'] += 1

        formula = self.parser.parse(formula_text, logic_type)

        # Store formula
        self.formulas[formula.formula_id] = formula

        if formula.is_valid:
            logger.debug(f"Formula parsed: {formula_text}")
        else:
            logger.warning(f"Invalid formula: {formula.validation_errors}")

        return formula

    async def apply_rule(
        self,
        premises: List[str],
        rule: InferenceRule,
        target: Optional[str] = None
    ) -> Tuple[bool, List[str]]:
        """Apply logical inference rule"""
        self.stats['total_inferences'] += 1

        try:
            # Apply inference
            conclusions = await self.inference_engine.apply_inference(premises, rule, target)

            # Validate each conclusion
            valid_conclusions = []
            for conclusion in conclusions:
                is_valid, errors = await self.validator.validate_inference(
                    premises,
                    conclusion,
                    rule
                )

                if is_valid:
                    valid_conclusions.append(conclusion)

            return (True, valid_conclusions)

        except Exception as e:
            logger.error(f"Rule application failed: {e}")
            return (False, [])

    async def prove_theorem(
        self,
        theorem: str,
        premises: List[str],
        max_steps: int = 100
    ) -> LogicalProof:
        """Prove theorem using logical inference"""
        proof_id = f"proof_{int(datetime.now().timestamp())}"
        start_time = datetime.now()
        self.stats['total_proofs'] += 1

        logger.info(f"Proving theorem: {theorem}")

        try:
            # Use proof engine if available
            if self.proof_engine:
                from core.reasoning.advanced_proof_engine import Theorem, LogicType as ProofLogicType

                theorem_obj = Theorem(
                    theorem_id=proof_id,
                    statement=theorem,
                    premises=premises,
                    logic_type=ProofLogicType.PROPOSITIONAL
                )

                # Attempt proof
                proof_result = await self.proof_engine.prove_theorem(theorem_obj, max_steps)

                # Convert to our format
                steps = [
                    InferenceStep(
                        step_number=step.step_number,
                        rule_applied=InferenceRule.MODUS_PONENS,  # Simplified
                        premises=[],
                        conclusion=step.statement,
                        justification=step.justification
                    )
                    for step in proof_result.steps
                ]

                execution_time = (datetime.now() - start_time).total_seconds()

                proof = LogicalProof(
                    proof_id=proof_id,
                    theorem=theorem,
                    steps=steps,
                    premises=premises,
                    proven=proof_result.proved,
                    confidence=proof_result.confidence,
                    execution_time=execution_time
                )

                if proof.proven:
                    self.stats['successful_proofs'] += 1
                else:
                    self.stats['failed_proofs'] += 1

                # Store proof
                self.proofs[proof_id] = proof

                return proof

            else:
                # Fallback: simple direct proof
                proof = await self._simple_direct_proof(proof_id, theorem, premises, max_steps)
                return proof

        except Exception as e:
            logger.error(f"Theorem proving failed: {e}")
            self.stats['failed_proofs'] += 1

            execution_time = (datetime.now() - start_time).total_seconds()

            return LogicalProof(
                proof_id=proof_id,
                theorem=theorem,
                premises=premises,
                proven=False,
                error=str(e),
                execution_time=execution_time
            )

    async def _simple_direct_proof(
        self,
        proof_id: str,
        theorem: str,
        premises: List[str],
        max_steps: int
    ) -> LogicalProof:
        """Simple direct proof (fallback)"""
        steps = []

        # Add premises as initial steps
        for i, premise in enumerate(premises):
            steps.append(InferenceStep(
                step_number=i + 1,
                rule_applied=InferenceRule.MODUS_PONENS,
                premises=[],
                conclusion=premise,
                justification="Premise"
            ))

        # Try applying rules
        current_facts = set(premises)

        for step_num in range(len(premises) + 1, max_steps):
            # Try modus ponens
            success, conclusions = await self.apply_rule(
                list(current_facts),
                InferenceRule.MODUS_PONENS,
                theorem
            )

            if success and conclusions:
                for conclusion in conclusions:
                    steps.append(InferenceStep(
                        step_number=step_num,
                        rule_applied=InferenceRule.MODUS_PONENS,
                        premises=list(current_facts),
                        conclusion=conclusion,
                        justification="Modus ponens"
                    ))

                    current_facts.add(conclusion)

                    # Check if we proved the theorem
                    if conclusion == theorem:
                        return LogicalProof(
                            proof_id=proof_id,
                            theorem=theorem,
                            steps=steps,
                            premises=premises,
                            proven=True,
                            confidence=0.9
                        )
            else:
                # No more inferences
                break

        # Could not prove
        return LogicalProof(
            proof_id=proof_id,
            theorem=theorem,
            steps=steps,
            premises=premises,
            proven=False,
            confidence=0.0
        )

    async def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        return {
            **self.stats,
            "formulas_stored": len(self.formulas),
            "proofs_stored": len(self.proofs),
            "proof_engine_available": self.proof_engine is not None
        }


# Global instance
_logical_integration: Optional[LogicalIntegrationSystem] = None


def get_logical_integration(config: Dict[str, Any] = None) -> LogicalIntegrationSystem:
    """Get global logical integration system"""
    global _logical_integration
    if _logical_integration is None:
        _logical_integration = LogicalIntegrationSystem(config)
    return _logical_integration


# Convenience exports
__all__ = [
    "LogicType",
    "InferenceRule",
    "Operator",
    "LogicalFormula",
    "InferenceStep",
    "LogicalProof",
    "LogicalFormulaParser",
    "LogicalInferenceEngine",
    "LogicalReasoningValidator",
    "LogicalIntegrationSystem",
    "get_logical_integration"
]
