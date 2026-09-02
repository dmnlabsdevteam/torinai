"""Self-contained theorem-proving faculty owned by the code tools.

Duplicates exactly what ``generate_math_proof`` needs and nothing more: a
propositional prover over the connectives ``~ & | -> <->`` plus a light
natural-language layer for syllogisms ("All P are Q", "X is P", "If A then
B"), decided by Z3 refutation (premises together with the negated goal are
unsatisfiable iff the goal is entailed).

It imports only ``z3``. It does NOT route through the substrate's reasoning
authority — the capability lives here, in the tool layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    import z3
    _HAVE_Z3 = True
except Exception:  # pragma: no cover - environment without z3
    _HAVE_Z3 = False


@dataclass
class ProofResult:
    goal: str
    premises: List[str]
    proved: bool = False
    steps: List[str] = field(default_factory=list)
    method: str = "propositional_refutation"
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "premises": self.premises,
            "proved": self.proved,
            "steps": self.steps,
            "method": self.method,
            "error": self.error,
        }


# ---- natural-language patterns -------------------------------------------------
_IF_THEN = re.compile(r'^\s*if\s+(.+?)\s+then\s+(.+?)\s*$', re.IGNORECASE)
_ALL = re.compile(r'^\s*(?:all|every)\s+(.+?)\s+(?:are|is)\s+(.+?)\s*$', re.IGNORECASE)
_NO = re.compile(r'^\s*no\s+(.+?)\s+(?:are|is)\s+(.+?)\s*$', re.IGNORECASE)
_IS = re.compile(r'^\s*(.+?)\s+is\s+(not\s+)?(?:a\s+|an\s+)?(.+?)\s*$', re.IGNORECASE)

# propositional tokens: <-> -> & | ~ ( ) identifier
_TOKEN = re.compile(r'\s*(<->|->|&|\||~|\(|\)|[A-Za-z_][A-Za-z0-9_]*)')


def _ident(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', text.strip().lower()).strip('_')


def _singular(pred: str) -> str:
    p = _ident(pred)
    if len(p) > 3 and p.endswith('s') and not p.endswith('ss'):
        return p[:-1]
    return p


class _Prover:
    def __init__(self):
        self._atoms: Dict[str, "z3.BoolRef"] = {}
        self.individuals: List[str] = []

    def _bool(self, name: str):
        if name not in self._atoms:
            self._atoms[name] = z3.Bool(name)
        return self._atoms[name]

    def _pred_atom(self, individual: str, predicate: str):
        return self._bool(f"{_ident(individual)}__{_singular(predicate)}")

    # -- individual collection (first pass) --
    def note_individuals(self, text: str) -> None:
        if _IF_THEN.match(text) or _ALL.match(text) or _NO.match(text):
            return
        m = _IS.match(text)
        if m:
            subj = _ident(m.group(1))
            if subj and subj not in self.individuals:
                self.individuals.append(subj)

    # -- formula construction (second pass) --
    def to_formula(self, text: str):
        text = text.strip()

        m = _IF_THEN.match(text)
        if m:
            return z3.Implies(self.to_formula(m.group(1)), self.to_formula(m.group(2)))

        m = _ALL.match(text)
        if m:
            p, q = m.group(1), m.group(2)
            clauses = [z3.Implies(self._pred_atom(i, p), self._pred_atom(i, q))
                       for i in self.individuals]
            return z3.And(*clauses) if clauses else z3.BoolVal(True)

        m = _NO.match(text)
        if m:
            p, q = m.group(1), m.group(2)
            clauses = [z3.Implies(self._pred_atom(i, p), z3.Not(self._pred_atom(i, q)))
                       for i in self.individuals]
            return z3.And(*clauses) if clauses else z3.BoolVal(True)

        m = _IS.match(text)
        if m and '->' not in text and '&' not in text and '|' not in text:
            subj, neg, pred = m.group(1), m.group(2), m.group(3)
            atom = self._pred_atom(subj, pred)
            return z3.Not(atom) if neg else atom

        # Fall back to the propositional grammar.
        return self._parse_propositional(text)

    # -- recursive-descent propositional parser --
    def _parse_propositional(self, text: str):
        tokens = self._tokenize(text)
        pos = [0]

        def peek():
            return tokens[pos[0]] if pos[0] < len(tokens) else None

        def advance():
            tok = tokens[pos[0]]
            pos[0] += 1
            return tok

        def parse_iff():
            left = parse_impl()
            while peek() == '<->':
                advance()
                right = parse_impl()
                left = (left == right)
            return left

        def parse_impl():
            left = parse_or()
            if peek() == '->':
                advance()
                right = parse_impl()  # right-associative
                return z3.Implies(left, right)
            return left

        def parse_or():
            left = parse_and()
            while peek() == '|':
                advance()
                left = z3.Or(left, parse_and())
            return left

        def parse_and():
            left = parse_not()
            while peek() == '&':
                advance()
                left = z3.And(left, parse_not())
            return left

        def parse_not():
            if peek() == '~':
                advance()
                return z3.Not(parse_not())
            return parse_atom()

        def parse_atom():
            tok = peek()
            if tok == '(':
                advance()
                inner = parse_iff()
                if peek() != ')':
                    raise ValueError(f"missing ')' in {text!r}")
                advance()
                return inner
            if tok is None or tok in ('->', '<->', '&', '|', ')'):
                raise ValueError(f"unexpected token {tok!r} in {text!r}")
            advance()
            return self._bool(_ident(tok))

        formula = parse_iff()
        if pos[0] != len(tokens):
            raise ValueError(f"trailing tokens in {text!r}")
        return formula

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        tokens, i = [], 0
        while i < len(text):
            m = _TOKEN.match(text, i)
            if not m:
                if text[i].isspace():
                    i += 1
                    continue
                raise ValueError(f"cannot tokenize {text[i:]!r}")
            tokens.append(m.group(1))
            i = m.end()
        return tokens


def prove(goal: str, premises: Optional[List[str]] = None) -> ProofResult:
    """Prove ``goal`` from ``premises`` by Z3 refutation. Self-contained."""
    premises = list(premises or [])
    result = ProofResult(goal=goal, premises=premises)

    if not _HAVE_Z3:
        result.error = "z3 not available"
        return result
    if not goal.strip():
        result.error = "no goal provided"
        return result

    prover = _Prover()
    try:
        for text in premises + [goal]:
            prover.note_individuals(text)

        prem_formulas = [prover.to_formula(p) for p in premises]
        goal_formula = prover.to_formula(goal)
    except Exception as e:
        result.error = f"could not formalize: {e}"
        return result

    solver = z3.Solver()
    for f in prem_formulas:
        solver.add(f)
    solver.add(z3.Not(goal_formula))  # refutation

    status = solver.check()
    steps = [f"Premise: {p}" for p in premises]
    if status == z3.unsat:
        result.proved = True
        steps.append(f"Assume for contradiction: not ({goal})")
        steps.append("The premises together with the negated goal are unsatisfiable.")
    elif status == z3.sat:
        result.proved = False
        result.error = "not entailed: premises are consistent with the negation of the goal"
    else:
        result.proved = False
        result.error = "undecided: the solver returned unknown"
    result.steps = steps
    return result
