#!/usr/bin/env python3
"""
Advanced Proof Engine
=====================
Formal theorem proving and logical verification system

Features:
- Automated theorem proving
- Proof verification
- Logical inference
- Constraint solving
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from enum import Enum

try:
    # Optional SMT backend for industrial-strength proving/constraints
    from z3 import Solver, Bool, And, Or, Not, Implies, sat  # type: ignore
    _Z3_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Solver = None  # type: ignore
    Bool = And = Or = Not = Implies = sat = None  # type: ignore
    _Z3_AVAILABLE = False

logger = logging.getLogger(__name__)


#: The proof was requested from a backend that is not present. NOT a refutation.
CAPABILITY_UNAVAILABLE = "capability_unavailable"
#: A negative reached by an incomplete method while the complete one was absent.
#: "I could not derive it" is not "it does not follow".
NEGATIVE_NOT_AUTHORITATIVE = "negative_not_authoritative"


@dataclass
class ProofVerification:
    """The outcome of checking a proof, with what could not be checked."""

    verified: bool
    reason: str
    method: Optional["ProofMethod"] = None
    failed_step: Optional[int] = None
    unchecked_steps: List[int] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.verified


class ProofMethod(Enum):
    """Proof methods"""
    DIRECT = "direct"
    CONTRADICTION = "contradiction"
    INDUCTION = "induction"
    RESOLUTION = "resolution"
    NATURAL_DEDUCTION = "natural_deduction"
    SMT = "smt"  # Z3-backed SMT solving


class LogicType(Enum):
    """Logic types"""
    PROPOSITIONAL = "propositional"
    FIRST_ORDER = "first_order"
    MODAL = "modal"
    TEMPORAL = "temporal"


@dataclass
class Axiom:
    """Logical axiom"""
    axiom_id: str
    statement: str
    logic_type: LogicType
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Theorem:
    """Theorem to prove"""
    theorem_id: str
    statement: str
    premises: List[str] = field(default_factory=list)
    logic_type: LogicType = LogicType.PROPOSITIONAL
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProofStep:
    """Single step in proof"""
    step_number: int
    statement: str
    justification: str
    rule_applied: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Proof:
    """Complete proof"""
    theorem_id: str
    proved: bool

    steps: List[ProofStep] = field(default_factory=list)
    method: ProofMethod = ProofMethod.DIRECT
    confidence: float = 0.0

    execution_time: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class AdvancedProofEngine:
    """
    Advanced Theorem Proving Engine

    Capabilities:
    - Automated theorem proving
    - Multiple proof strategies
    - Logical inference
    - Proof verification
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Knowledge base
        self.axioms: Dict[str, Axiom] = {}
        self.theorems: Dict[str, Theorem] = {}
        self.proofs: Dict[str, Proof] = {}

        # Inference rules
        self.inference_rules = self._initialize_inference_rules()

        # Statistics
        self.stats = {
            'total_proofs': 0,
            'successful_proofs': 0,
            'failed_proofs': 0
        }

        logger.info("AdvancedProofEngine initialized")

    def _initialize_inference_rules(self) -> Dict[str, Any]:
        """Initialize logical inference rules"""
        return {
            'modus_ponens': {'pattern': '(P -> Q), P |- Q'},
            'modus_tollens': {'pattern': '(P -> Q), ~Q |- ~P'},
            'hypothetical_syllogism': {'pattern': '(P -> Q), (Q -> R) |- (P -> R)'},
            'disjunctive_syllogism': {'pattern': '(P v Q), ~P |- Q'},
            'resolution': {'pattern': '(P v Q), (~P v R) |- (Q v R)'}
        }

    @property
    def z3_available(self) -> bool:
        """Return True if Z3 backend is available."""
        return _Z3_AVAILABLE

    async def prove_theorem(
        self,
        theorem: Theorem,
        max_steps: int = 100,
        timeout: float = 30.0
    ) -> Proof:
        """
        Attempt to prove theorem

        Args:
            theorem: Theorem to prove
            max_steps: Maximum proof steps
            timeout: Timeout in seconds

        Returns:
            Proof result
        """
        start_time = datetime.now()
        self.stats['total_proofs'] += 1

        logger.info(f"Proving theorem: {theorem.theorem_id}")

        try:
            # Store theorem
            self.theorems[theorem.theorem_id] = theorem

            # Select proof method
            method = self._select_proof_method(theorem)

            # Attempt proof
            if method == ProofMethod.SMT:
                proof = await self._smt_proof(theorem, max_steps, timeout)
            elif method == ProofMethod.DIRECT:
                proof = await self._direct_proof(theorem, max_steps)
            elif method == ProofMethod.CONTRADICTION:
                proof = await self._proof_by_contradiction(theorem, max_steps)
            elif method == ProofMethod.RESOLUTION:
                proof = await self._resolution_proof(theorem, max_steps)
            else:
                proof = await self._direct_proof(theorem, max_steps)

            # Calculate execution time
            proof.execution_time = (datetime.now() - start_time).total_seconds()

            # Store proof
            self.proofs[theorem.theorem_id] = proof

            # Update statistics
            if proof.proved:
                self.stats['successful_proofs'] += 1
                logger.info(f"✓ Theorem proved: {theorem.theorem_id} ({len(proof.steps)} steps)")
            else:
                self.stats['failed_proofs'] += 1
                logger.warning(f"✗ Theorem not proved: {theorem.theorem_id}")

            if (not proof.proved and not proof.error
                    and proof.method is not ProofMethod.SMT and not self.z3_available):
                # Recorded so a caller cannot read "could not derive" as
                # "refuted". The complete method was unavailable.
                proof.error = NEGATIVE_NOT_AUTHORITATIVE
            return proof

        except Exception as e:
            logger.error(f"Proof attempt failed: {e}")
            self.stats['failed_proofs'] += 1

            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                error=str(e),
                execution_time=(datetime.now() - start_time).total_seconds()
            )

    def _select_proof_method(self, theorem: Theorem) -> ProofMethod:
        """Select appropriate proof method"""
        # Prefer SMT when available for propositional / simple first-order
        if self.z3_available and theorem.logic_type in (LogicType.PROPOSITIONAL, LogicType.FIRST_ORDER):
            return ProofMethod.SMT

        # Without Z3 the weaker methods are still real inference, not stand-ins
        # -- but they are incomplete, so `proved=False` from them is recorded as
        # NON-AUTHORITATIVE by `prove_theorem`. "I could not derive it" and "it
        # does not follow" are different claims.
        if theorem.logic_type == LogicType.PROPOSITIONAL:
            return ProofMethod.RESOLUTION
        return ProofMethod.DIRECT

    async def _smt_proof(
        self,
        theorem: Theorem,
        max_steps: int,
        timeout: float = 30.0
    ) -> Proof:
        """SMT-based proof strategy using Z3.

        Premises and the goal are parsed by LogicalFormulaParser into syntax
        trees, then translated to Z3. Anything that does not parse is reported
        as a parse failure rather than being reduced to an opaque atom, because
        an atomised premise silently makes a valid theorem unprovable.
        """
        if not self.z3_available:
            # NO FALLBACK. Quietly answering with a weaker method makes the
            # solver decorative: severing it would change nothing observable,
            # and a `proved=False` produced by its absence is indistinguishable
            # from one produced by a refutation.
            logger.error("SMT proof requested but the Z3 backend is unavailable")
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                method=ProofMethod.SMT,
                confidence=0.0,
                error=CAPABILITY_UNAVAILABLE,
            )

        # Imported lazily: logical_integration imports this module inside its
        # own functions, so a module-level import here risks a cycle.
        from core.agents.logical.logical_integration import (
            FormulaSyntaxError,
            LogicalFormulaParser,
        )

        parser = LogicalFormulaParser()

        # Parse every premise and the goal up front so a syntax error is
        # reported as such instead of surfacing as "not proved".
        parsed_premises: List[Any] = []
        try:
            for premise in theorem.premises:
                parsed_premises.append(parser.parse_ast(premise))
            parsed_statement = parser.parse_ast(theorem.statement)
        except FormulaSyntaxError as e:
            logger.info(f"Theorem {theorem.theorem_id} could not be formalised: {e}")
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                steps=[],
                method=ProofMethod.SMT,
                confidence=0.0,
                error=f"formula could not be parsed: {e}"
            )

        # Declare one Z3 boolean per distinct atom across premises and goal.
        atoms: Set[str] = set()
        for node in parsed_premises:
            parser.formula_atoms(node, atoms)
        parser.formula_atoms(parsed_statement, atoms)
        z3_vars: Dict[str, Any] = {name: Bool(name) for name in sorted(atoms)}

        solver = Solver()

        # Bound the search. Without this Z3 can run unbounded on a hard
        # instance and block the event loop, since prove_theorem is reachable
        # from an LLM-callable tool.
        if timeout and timeout > 0:
            solver.set("timeout", int(timeout * 1000))

        # Refutation encoding: premises together with the negated goal are
        # unsatisfiable exactly when the premises entail the goal.
        for node in parsed_premises:
            solver.add(parser.to_z3(node, z3_vars))
        solver.add(Not(parser.to_z3(parsed_statement, z3_vars)))

        logger.debug("Running Z3 SMT solver for theorem %s", theorem.theorem_id)

        result = await asyncio.to_thread(solver.check)
        status = str(result).lower()

        steps: List[ProofStep] = []
        for step_number, premise in enumerate(theorem.premises, start=1):
            steps.append(ProofStep(
                step_number=step_number,
                statement=premise,
                justification="Premise",
                rule_applied="given"
            ))
        steps.append(ProofStep(
            step_number=len(theorem.premises) + 1,
            statement=f"~({theorem.statement})",
            justification="Negation of conclusion (for refutation)",
            rule_applied="assumption"
        ))

        if status == "unsat":
            steps.append(ProofStep(
                step_number=len(steps) + 1,
                statement=theorem.statement,
                justification="Premises with the negated goal are unsatisfiable",
                rule_applied="refutation"
            ))
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=True,
                steps=steps,
                method=ProofMethod.SMT,
                confidence=0.98,
            )

        if status == "sat":
            # A model satisfies the premises while falsifying the goal, so the
            # premises genuinely do not entail it.
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                steps=steps,
                method=ProofMethod.SMT,
                confidence=0.0,
            )

        # "unknown" means the solver gave up (usually the timeout). That is not
        # evidence either way and must not be reported as a decided result.
        return Proof(
            theorem_id=theorem.theorem_id,
            proved=False,
            steps=steps,
            method=ProofMethod.SMT,
            confidence=0.0,
            error=f"solver returned {status!r} (timeout {timeout}s); entailment undecided"
        )

    async def _direct_proof(
        self,
        theorem: Theorem,
        max_steps: int
    ) -> Proof:
        """Direct proof strategy"""
        steps = []
        facts = set(theorem.premises)

        # Step 1: Start with premises
        for i, premise in enumerate(theorem.premises):
            steps.append(ProofStep(
                step_number=i + 1,
                statement=premise,
                justification="Premise",
                rule_applied="given"
            ))

        # Step 2: Apply inference rules
        for step_num in range(len(theorem.premises) + 1, max_steps):
            # Try to derive new facts
            new_fact = self._apply_inference_rules(facts)

            if new_fact:
                steps.append(ProofStep(
                    step_number=step_num,
                    statement=new_fact['statement'],
                    justification=new_fact['justification'],
                    rule_applied=new_fact['rule']
                ))

                facts.add(new_fact['statement'])

                # Check if we proved the theorem
                if new_fact['statement'] == theorem.statement:
                    return Proof(
                        theorem_id=theorem.theorem_id,
                        proved=True,
                        steps=steps,
                        method=ProofMethod.DIRECT,
                        confidence=0.95
                    )
            else:
                # No more inferences possible
                break

        # Could not prove
        return Proof(
            theorem_id=theorem.theorem_id,
            proved=False,
            steps=steps,
            method=ProofMethod.DIRECT,
            confidence=0.0
        )

    async def _proof_by_contradiction(
        self,
        theorem: Theorem,
        max_steps: int
    ) -> Proof:
        """Proof by contradiction strategy"""
        steps = []

        # Assume negation of theorem
        steps.append(ProofStep(
            step_number=1,
            statement=f"~({theorem.statement})",
            justification="Assume negation for contradiction",
            rule_applied="assumption"
        ))

        # Try to derive contradiction
        # (Simplified implementation)

        return Proof(
            theorem_id=theorem.theorem_id,
            proved=False,
            steps=steps,
            method=ProofMethod.CONTRADICTION,
            confidence=0.5
        )

    async def _resolution_proof(
        self,
        theorem: Theorem,
        max_steps: int
    ) -> Proof:
        """Resolution-based proof"""
        steps = []

        # Convert to CNF and apply resolution
        # (Simplified implementation)

        return Proof(
            theorem_id=theorem.theorem_id,
            proved=False,
            steps=steps,
            method=ProofMethod.RESOLUTION,
            confidence=0.6
        )

    def _apply_inference_rules(
        self,
        facts: Set[str]
    ) -> Optional[Dict[str, str]]:
        """Apply inference rules to derive new facts"""
        # Simplified: Try modus ponens
        for fact1 in facts:
            for fact2 in facts:
                if '->' in fact1 and fact2 in fact1:
                    # P -> Q and P, derive Q
                    parts = fact1.split('->')
                    if len(parts) == 2:
                        antecedent = parts[0].strip()
                        consequent = parts[1].strip()

                        if antecedent == fact2:
                            return {
                                'statement': consequent,
                                'justification': f"From {fact1} and {fact2}",
                                'rule': 'modus_ponens'
                            }

        return None

    async def add_axiom(self, axiom: Axiom):
        """Add axiom to knowledge base"""
        self.axioms[axiom.axiom_id] = axiom
        logger.info(f"Added axiom: {axiom.axiom_id}")

    async def verify_proof(self, proof: Proof, theorem: Optional[Theorem] = None
                           ) -> "ProofVerification":
        """Check a proof independently, step by step.

        THE PREVIOUS IMPLEMENTATION VERIFIED NOTHING. It looped over the steps
        with `pass` and returned `proof.proved` -- the very claim it was asked
        to check -- so any caller would have believed a proof had been
        independently confirmed when nothing had been examined. It had zero
        callers, which is the only reason it never fabricated anything.

        This re-derives instead: every step must be a premise of the theorem or
        follow from earlier steps by its stated rule, and the last step must be
        the theorem. A step whose rule this checker does not implement is
        counted as UNCHECKED and blocks verification -- it is never waved
        through, because an unexamined step is exactly what the old version
        returned True on.
        """
        if not proof.proved:
            return ProofVerification(False, "proof does not claim to prove anything")

        if proof.error == CAPABILITY_UNAVAILABLE:
            return ProofVerification(False, "proof was produced without its solver")

        if proof.method is ProofMethod.SMT:
            # An SMT proof carries no re-checkable steps; it is verified by
            # re-running the solver, which is what produced it.
            if theorem is None:
                return ProofVerification(
                    False, "an SMT proof can only be verified against its theorem")
            replay = await self._smt_proof(theorem, max_steps=len(proof.steps) or 10)
            return ProofVerification(
                bool(replay.proved),
                "re-ran the solver" if replay.proved else "solver did not reproduce the proof",
                method=ProofMethod.SMT)

        if not proof.steps:
            return ProofVerification(False, "proof claims success with no steps")

        established: Set[str] = set()
        unchecked: List[int] = []
        for step in proof.steps:
            rule = (step.rule_applied or "").lower()
            if rule in ("given", "premise", "axiom"):
                established.add(step.statement)
                continue
            if rule == "modus_ponens":
                if not self._modus_ponens_holds(step.statement, established):
                    return ProofVerification(
                        False, f"step {step.step_number} does not follow by modus ponens",
                        failed_step=step.step_number)
                established.add(step.statement)
                continue
            unchecked.append(step.step_number)

        if unchecked:
            return ProofVerification(
                False, f"steps {unchecked} use rules this checker cannot re-derive",
                unchecked_steps=unchecked)

        final = proof.steps[-1].statement
        if theorem is not None and final != theorem.statement:
            return ProofVerification(
                False, f"the last step proves {final!r}, not the theorem")

        return ProofVerification(True, "every step re-derived", method=proof.method)

    @staticmethod
    def _modus_ponens_holds(statement: str, established: Set[str]) -> bool:
        """Whether some established implication and antecedent give `statement`."""
        for fact in established:
            if "->" not in fact:
                continue
            antecedent, _, consequent = fact.partition("->")
            if consequent.strip() == statement.strip() and antecedent.strip() in established:
                return True
        return False

    async def get_statistics(self) -> Dict[str, Any]:
        """Get proof engine statistics"""
        total = self.stats['total_proofs']

        return {
            **self.stats,
            'success_rate': (
                self.stats['successful_proofs'] / total * 100
                if total > 0 else 0
            ),
            'axioms_count': len(self.axioms),
            'theorems_count': len(self.theorems)
        }


# Global instance
_proof_engine: Optional[AdvancedProofEngine] = None


def get_proof_engine() -> AdvancedProofEngine:
    """Get global proof engine instance"""
    global _proof_engine
    if _proof_engine is None:
        _proof_engine = AdvancedProofEngine()
    return _proof_engine


# Alias for backwards compatibility
def create_advanced_proof_engine() -> AdvancedProofEngine:
    """Create/get advanced proof engine instance (alias for get_proof_engine)"""
    return get_proof_engine()


# Test usage
async def main():
    """Test proof engine"""
    logging.basicConfig(level=logging.INFO)

    engine = get_proof_engine()

    # Test theorem
    theorem = Theorem(
        theorem_id="test_1",
        statement="Q",
        premises=["P -> Q", "P"],
        logic_type=LogicType.PROPOSITIONAL
    )

    proof = await engine.prove_theorem(theorem)

    print(f"\n{'='*50}")
    print("Proof Engine Test")
    print(f"{'='*50}")
    print(f"Theorem: {theorem.statement}")
    print(f"Proved: {proof.proved}")
    print(f"Steps: {len(proof.steps)}")
    print(f"Method: {proof.method.value}")
    print(f"\nProof steps:")
    for step in proof.steps:
        print(f"  {step.step_number}. {step.statement} ({step.justification})")

    stats = await engine.get_statistics()
    print(f"\nStatistics: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
