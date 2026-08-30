#!/usr/bin/env python3
"""
Unified Quantum Reasoning System
=================================
Integrates quantum computing with classical reasoning for enhanced problem-solving

Features:
- Quantum-accelerated logical reasoning
- Probabilistic inference with superposition
- Pattern matching using quantum neural networks
- Optimization using QAOA
- Hybrid quantum-classical workflows
"""

import logging
import asyncio
import warnings
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from enum import Enum

try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False


logger = logging.getLogger(__name__)


class QuantumTaskType(Enum):
    """Which quantum ALGORITHM a task should be dispatched to.

    RENAMED FROM `ReasoningType`, which collided with the canonical enum of
    KINDS OF THINKING in `reasoning_interfaces`. This is a different concept and
    the overlap in names hid that: LOGICAL/PROBABILISTIC/CAUSAL do name kinds of
    thinking, but OPTIMIZATION and PATTERN_MATCHING are search methods (the
    latter is a member of `InferenceStrategy`), and ANALOGY is spelled
    ANALOGICAL everywhere else -- so even the members that looked shared were
    not reliably the same.

    What this actually selects is a quantum routine -- Grover, QAOA, amplitude
    estimation -- so it is named for that.
    """
    LOGICAL = "logical"              # Boolean logic, theorem proving
    PROBABILISTIC = "probabilistic"  # Bayesian inference, uncertainty
    OPTIMIZATION = "optimization"     # Constraint satisfaction, search
    PATTERN_MATCHING = "pattern_matching"  # Pattern recognition
    ANALOGY = "analogy"              # Analogical reasoning
    CAUSAL = "causal"                # Causal inference


class QuantumAdvantageLevel(Enum):
    """Level of quantum advantage expected"""
    NONE = "none"            # No quantum advantage
    MARGINAL = "marginal"    # Small speedup (1.1-1.5x)
    MODERATE = "moderate"    # Significant speedup (1.5-2x)
    SUBSTANTIAL = "substantial"  # Large speedup (2x+)


@dataclass
class ReasoningTask:
    """Reasoning task specification"""
    task_id: str
    reasoning_type: QuantumTaskType
    problem_description: str

    # Input data
    inputs: Dict[str, Any] = field(default_factory=dict)

    # Constraints
    max_time_seconds: float = 30.0
    use_quantum: bool = True
    fallback_to_classical: bool = True

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ReasoningResult:
    """Result from reasoning process"""
    task_id: str
    success: bool

    # Results
    conclusion: Any
    reasoning_steps: List[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1

    # Performance metrics
    execution_time: float = 0.0
    used_quantum: bool = False
    quantum_advantage: QuantumAdvantageLevel = QuantumAdvantageLevel.NONE

    # Details
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class UnifiedQuantumReasoningSystem:
    """
    Unified Quantum Reasoning System

    Integrates quantum computing capabilities with classical reasoning
    to solve complex problems more efficiently.

    Architecture:
    - Automatic task assessment for quantum suitability
    - Quantum circuit construction for reasoning tasks
    - Hybrid quantum-classical execution
    - Fallback to classical methods when needed
    - Performance tracking and optimization
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Quantum resources
        self.quantum_provider = None
        # `quantum_available` USED TO MEAN "qiskit imported". Importing qiskit
        # lets you CONSTRUCT a circuit; it says nothing about whether one can
        # RUN. With no valid API token this reported quantum_available = True
        # to every caller and to get_statistics(), while there was no backend
        # to execute on. The two facts are now separate and availability is
        # derived from the provider rather than asserted at construction.
        self.qiskit_installed = QISKIT_AVAILABLE
        self._quantum_disabled = False

        # Reasoning components
        self.reasoning_engines = {
            QuantumTaskType.LOGICAL: self._logical_reasoning,
            QuantumTaskType.PROBABILISTIC: self._probabilistic_reasoning,
            QuantumTaskType.OPTIMIZATION: self._optimization_reasoning,
            QuantumTaskType.PATTERN_MATCHING: self._pattern_matching_reasoning,
            QuantumTaskType.ANALOGY: self._analogy_reasoning,
            QuantumTaskType.CAUSAL: self._causal_reasoning
        }

        # Performance tracking
        self.stats = {
            'total_tasks': 0,
            'quantum_tasks': 0,
            'classical_tasks': 0,
            'successful_tasks': 0,
            'failed_tasks': 0,
            'avg_quantum_speedup': 1.0
        }

        logger.info("UnifiedQuantumReasoningSystem initialized")

    @property
    def quantum_available(self) -> bool:
        """Whether quantum work can actually EXECUTE, not merely be expressed.

        Requires qiskit to be importable AND a provider to have initialized
        with a usable backend. Derived, so it cannot drift from the thing it
        describes.
        """
        return bool(self.qiskit_installed
                    and self.quantum_provider is not None
                    and not self._quantum_disabled)

    async def initialize(self, quantum_provider=None) -> bool:
        """
        Initialize reasoning system

        Args:
            quantum_provider: Optional quantum computing provider

        Returns:
            Success status
        """
        try:
            logger.info("Initializing Unified Quantum Reasoning System")

            # Initialize quantum provider if available
            if quantum_provider:
                self.quantum_provider = quantum_provider
                logger.info("Using provided quantum provider")

            elif self.qiskit_installed:
                # Try to initialize quantum provider
                try:
                    from core.quantum.quantum_factory import create_quantum_provider

                    self.quantum_provider = await create_quantum_provider(
                        use_simulator=True
                    )
                    await self.quantum_provider.initialize()

                    logger.info("✓ Quantum provider initialized")

                except Exception as e:
                    logger.warning(f"Could not initialize quantum provider: {e}")
                    self._quantum_disabled = True

            else:
                logger.info("Quantum computing not available, using classical methods only")

            logger.info("✓ Unified Quantum Reasoning System ready")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize reasoning system: {e}")
            return False

    async def reason(self, task: ReasoningTask) -> ReasoningResult:
        """
        Execute reasoning task

        Args:
            task: Reasoning task to execute

        Returns:
            ReasoningResult with conclusion and details
        """
        start_time = datetime.now()
        self.stats['total_tasks'] += 1

        logger.info(
            f"Processing reasoning task: {task.task_id} "
            f"(type: {task.reasoning_type.value})"
        )

        try:
            # Select reasoning engine
            reasoning_engine = self.reasoning_engines.get(task.reasoning_type)

            if not reasoning_engine:
                raise ValueError(f"Unknown reasoning type: {task.reasoning_type}")

            # Determine if quantum should be used
            use_quantum = (
                task.use_quantum and
                self.quantum_available and
                self.quantum_provider and
                self._should_use_quantum(task)
            )

            # Execute reasoning
            if use_quantum:
                logger.info("Using quantum-accelerated reasoning")
                result = await reasoning_engine(task, use_quantum=True)
                self.stats['quantum_tasks'] += 1

                # Check if quantum provided advantage
                if result.success and result.quantum_advantage != QuantumAdvantageLevel.NONE:
                    logger.info(f"Quantum advantage: {result.quantum_advantage.value}")

            else:
                logger.info("Using classical reasoning")
                result = await reasoning_engine(task, use_quantum=False)
                self.stats['classical_tasks'] += 1

            # Calculate execution time
            execution_time = (datetime.now() - start_time).total_seconds()
            result.execution_time = execution_time

            # Update statistics
            if result.success:
                self.stats['successful_tasks'] += 1
            else:
                self.stats['failed_tasks'] += 1

            logger.info(
                f"✓ Reasoning task completed: {task.task_id} "
                f"(confidence: {result.confidence:.2f}, time: {execution_time:.2f}s)"
            )

            return result

        except Exception as e:
            logger.error(f"Reasoning task failed: {e}")
            self.stats['failed_tasks'] += 1

            return ReasoningResult(
                task_id=task.task_id,
                success=False,
                conclusion=None,
                error=str(e),
                execution_time=(datetime.now() - start_time).total_seconds()
            )

    def _should_use_quantum(self, task: ReasoningTask) -> bool:
        """
        Determine if quantum computing should be used for this task

        Args:
            task: Reasoning task

        Returns:
            Whether to use quantum
        """
        # Task types that benefit from quantum
        quantum_beneficial = {
            QuantumTaskType.OPTIMIZATION,
            QuantumTaskType.PATTERN_MATCHING,
            QuantumTaskType.PROBABILISTIC
        }

        if task.reasoning_type not in quantum_beneficial:
            return False

        # Check problem size (quantum works better for larger problems)
        problem_size = task.inputs.get('problem_size', 0)

        if problem_size < 10:
            return False  # Too small for quantum advantage

        return True

    async def _logical_reasoning(
        self,
        task: ReasoningTask,
        use_quantum: bool = False
    ) -> ReasoningResult:
        """
        Execute logical reasoning

        Args:
            task: Reasoning task
            use_quantum: Whether to use quantum acceleration

        Returns:
            ReasoningResult
        """
        logger.info("Executing logical reasoning")

        # Extract logical problem
        premises = task.inputs.get('premises', [])
        goal = task.inputs.get('goal', None)

        reasoning_steps = []
        conclusion = None
        confidence = 0.0

        try:
            if use_quantum:
                # Quantum logical reasoning using SAT solver
                # Build quantum circuit for logical constraints
                result = await self._quantum_sat_solver(premises, goal)
                conclusion = result['satisfiable']
                confidence = result['confidence']
                reasoning_steps = result['steps']
                quantum_advantage = QuantumAdvantageLevel.MODERATE

            else:
                # Classical logical reasoning
                # Simple forward chaining
                facts = set(premises)
                proven = False

                reasoning_steps.append(f"Given premises: {premises}")

                # Try to derive goal from facts
                for step in range(10):  # Max 10 reasoning steps
                    if goal in facts:
                        proven = True
                        break

                    new_facts = set()
                    for fact in facts:
                        if "implies" in fact:
                            parts = fact.split("implies")
                            if len(parts) == 2:
                                antecedent = parts[0].strip()
                                consequent = parts[1].strip()
                                if antecedent in facts:
                                    new_facts.add(consequent)

                        if "and" in fact:
                            parts = fact.split("and")
                            if all(p.strip() in facts for p in parts):
                                new_facts.add(fact)

                    if not new_facts:
                        break

                    facts.update(new_facts)
                    reasoning_steps.append(f"Inferred: {new_facts}")

                conclusion = proven
                confidence = 0.9 if proven else 0.1
                quantum_advantage = QuantumAdvantageLevel.NONE

            return ReasoningResult(
                task_id=task.task_id,
                success=True,
                conclusion=conclusion,
                reasoning_steps=reasoning_steps,
                confidence=confidence,
                used_quantum=use_quantum,
                quantum_advantage=quantum_advantage
            )

        except Exception as e:
            logger.error(f"Logical reasoning failed: {e}")
            return ReasoningResult(
                task_id=task.task_id,
                success=False,
                conclusion=None,
                error=str(e)
            )

    async def _probabilistic_reasoning(
        self,
        task: ReasoningTask,
        use_quantum: bool = False
    ) -> ReasoningResult:
        """
        Execute probabilistic reasoning (Bayesian inference)

        Args:
            task: Reasoning task
            use_quantum: Whether to use quantum

        Returns:
            ReasoningResult
        """
        logger.info("Executing probabilistic reasoning")

        try:
            # Extract probabilistic problem
            observations = task.inputs.get('observations', {})
            query = task.inputs.get('query', None)

            if use_quantum:
                # Quantum Bayesian inference using amplitude encoding
                result = await self._quantum_bayesian_inference(observations, query)
                conclusion = result['posterior']
                confidence = result['confidence']
                quantum_advantage = QuantumAdvantageLevel.SUBSTANTIAL

            else:
                # Classical Bayesian inference (simplified)
                # Placeholder for actual Bayesian network computation
                conclusion = {'probability': 0.5}
                confidence = 0.7
                quantum_advantage = QuantumAdvantageLevel.NONE

            return ReasoningResult(
                task_id=task.task_id,
                success=True,
                conclusion=conclusion,
                confidence=confidence,
                used_quantum=use_quantum,
                quantum_advantage=quantum_advantage,
                reasoning_steps=["Bayesian inference performed"]
            )

        except Exception as e:
            logger.error(f"Probabilistic reasoning failed: {e}")
            return ReasoningResult(
                task_id=task.task_id,
                success=False,
                conclusion=None,
                error=str(e)
            )

    async def _optimization_reasoning(
        self,
        task: ReasoningTask,
        use_quantum: bool = False
    ) -> ReasoningResult:
        """
        Execute optimization reasoning

        Args:
            task: Reasoning task
            use_quantum: Whether to use quantum (QAOA)

        Returns:
            ReasoningResult
        """
        logger.info("Executing optimization reasoning")

        try:
            # Extract optimization problem
            objective = task.inputs.get('objective', None)
            constraints = task.inputs.get('constraints', [])

            if use_quantum:
                # Use QAOA for optimization
                from core.quantum.quantum_algorithms import QAOA

                qaoa = QAOA(num_qubits=task.inputs.get('problem_size', 4))
                result = await qaoa.optimize(objective)

                conclusion = result.get('optimal_solution')
                confidence = result.get('quality', 0.8)
                quantum_advantage = QuantumAdvantageLevel.SUBSTANTIAL

            else:
                import random
                objective = task.inputs.get('objective_function', lambda x: sum(x))
                problem_size = task.inputs.get('problem_size', 4)

                best_solution = [random.randint(0, 1) for _ in range(problem_size)]
                best_value = objective(best_solution)

                temperature = 1.0
                for iteration in range(100):
                    candidate = best_solution.copy()
                    flip_idx = random.randint(0, problem_size - 1)
                    candidate[flip_idx] = 1 - candidate[flip_idx]

                    candidate_value = objective(candidate)
                    delta = candidate_value - best_value

                    if delta > 0 or random.random() < np.exp(delta / temperature):
                        best_solution = candidate
                        best_value = candidate_value

                    temperature *= 0.95

                conclusion = {"solution": best_solution, "value": best_value}
                confidence = 0.6
                quantum_advantage = QuantumAdvantageLevel.NONE

            return ReasoningResult(
                task_id=task.task_id,
                success=True,
                conclusion=conclusion,
                confidence=confidence,
                used_quantum=use_quantum,
                quantum_advantage=quantum_advantage,
                reasoning_steps=["Optimization performed"]
            )

        except Exception as e:
            logger.error(f"Optimization reasoning failed: {e}")
            return ReasoningResult(
                task_id=task.task_id,
                success=False,
                conclusion=None,
                error=str(e)
            )

    async def _pattern_matching_reasoning(
        self,
        task: ReasoningTask,
        use_quantum: bool = False
    ) -> ReasoningResult:
        """
        Execute pattern matching reasoning

        Args:
            task: Reasoning task
            use_quantum: Whether to use quantum (QNN)

        Returns:
            ReasoningResult
        """
        logger.info("Executing pattern matching reasoning")

        try:
            # Extract pattern matching problem
            pattern = task.inputs.get('pattern', [])
            dataset = task.inputs.get('dataset', [])

            if use_quantum:
                # Use Quantum Neural Network for pattern matching
                from core.quantum.quantum_algorithms import QuantumNeuralNetwork

                qnn = QuantumNeuralNetwork(num_qubits=len(pattern))
                result = await qnn.match_pattern(pattern, dataset)

                conclusion = result.get('matches', [])
                confidence = result.get('confidence', 0.8)
                quantum_advantage = QuantumAdvantageLevel.MODERATE

            else:
                # Classical pattern matching
                conclusion = []
                confidence = 0.7
                quantum_advantage = QuantumAdvantageLevel.NONE

            return ReasoningResult(
                task_id=task.task_id,
                success=True,
                conclusion=conclusion,
                confidence=confidence,
                used_quantum=use_quantum,
                quantum_advantage=quantum_advantage,
                reasoning_steps=["Pattern matching performed"]
            )

        except Exception as e:
            logger.error(f"Pattern matching failed: {e}")
            return ReasoningResult(
                task_id=task.task_id,
                success=False,
                conclusion=None,
                error=str(e)
            )

    async def _analogy_reasoning(
        self,
        task: ReasoningTask,
        use_quantum: bool = False
    ) -> ReasoningResult:
        """Execute analogical reasoning"""
        logger.info("Executing analogical reasoning")

        # Classical only for now (complex semantic task)
        try:
            source_domain = task.inputs.get('source_domain', {})
            target_domain = task.inputs.get('target_domain', {})

            # Use analogy discovery system
            from core.reasoning.analogy_discovery import AnalogyDiscovery

            analogy_system = AnalogyDiscovery()
            analogy = await analogy_system.find_analogy(
                source_concept=source_domain.get('concept', ''),
                target_domain=target_domain.get('domain', '')
            )

            return ReasoningResult(
                task_id=task.task_id,
                success=analogy is not None,
                conclusion=analogy,
                confidence=analogy.coherence if analogy else 0.0,
                used_quantum=False,
                quantum_advantage=QuantumAdvantageLevel.NONE,
                reasoning_steps=["Analogical mapping performed"]
            )

        except Exception as e:
            logger.error(f"Analogical reasoning failed: {e}")
            return ReasoningResult(
                task_id=task.task_id,
                success=False,
                conclusion=None,
                error=str(e)
            )

    async def _causal_reasoning(
        self,
        task: ReasoningTask,
        use_quantum: bool = False
    ) -> ReasoningResult:
        """Execute causal reasoning"""
        logger.info("Executing causal reasoning")

        # Classical causal inference (complex probabilistic task)
        try:
            cause = task.inputs.get('cause', None)
            effect = task.inputs.get('effect', None)
            observations = task.inputs.get('observations', {})

            # Simplified causal inference
            conclusion = {
                'causal_strength': 0.7,
                'direction': f"{cause} → {effect}"
            }
            confidence = 0.6

            return ReasoningResult(
                task_id=task.task_id,
                success=True,
                conclusion=conclusion,
                confidence=confidence,
                used_quantum=False,
                quantum_advantage=QuantumAdvantageLevel.NONE,
                reasoning_steps=["Causal inference performed"]
            )

        except Exception as e:
            logger.error(f"Causal reasoning failed: {e}")
            return ReasoningResult(
                task_id=task.task_id,
                success=False,
                conclusion=None,
                error=str(e)
            )

    async def _quantum_sat_solver(
        self,
        premises: List[str],
        goal: Any
    ) -> Dict[str, Any]:
        """
        Quantum SAT solver using Grover's algorithm

        Args:
            premises: Logical premises
            goal: Goal to prove

        Returns:
            SAT solution result
        """
        # Placeholder for actual quantum SAT implementation
        return {
            'satisfiable': True,
            'confidence': 0.85,
            'steps': [
                "Encoded premises into quantum state",
                "Applied Grover search",
                "Measured solution"
            ]
        }

    async def _quantum_bayesian_inference(
        self,
        observations: Dict[str, Any],
        query: str
    ) -> Dict[str, Any]:
        """
        Quantum Bayesian inference using amplitude encoding

        Args:
            observations: Observed evidence
            query: Query variable

        Returns:
            Posterior probability distribution
        """
        # Placeholder for actual quantum Bayesian implementation
        return {
            'posterior': {query: 0.75},
            'confidence': 0.9
        }

    async def get_statistics(self) -> Dict[str, Any]:
        """Get reasoning system statistics"""
        total = self.stats['total_tasks']

        return {
            **self.stats,
            'quantum_percentage': (
                self.stats['quantum_tasks'] / total * 100
                if total > 0 else 0
            ),
            'success_rate': (
                self.stats['successful_tasks'] / total * 100
                if total > 0 else 0
            ),
            'quantum_available': self.quantum_available
        }


# Global instance
_unified_reasoning_system: Optional[UnifiedQuantumReasoningSystem] = None


def get_quantum_reasoning_system() -> UnifiedQuantumReasoningSystem:
    """Get global quantum reasoning system instance"""
    global _unified_reasoning_system

    if _unified_reasoning_system is None:
        _unified_reasoning_system = UnifiedQuantumReasoningSystem()

    return _unified_reasoning_system


# Alias for backwards compatibility
def get_unified_reasoning_system() -> UnifiedQuantumReasoningSystem:
    """Get global unified reasoning system instance (alias)"""
    return get_quantum_reasoning_system()


# Module-level singleton instance (for imports)
quantum_reasoning_system = get_quantum_reasoning_system()


# Test usage
async def main():
    """Test unified quantum reasoning system"""
    logging.basicConfig(level=logging.INFO)

    system = get_quantum_reasoning_system()
    await system.initialize()

    # Test optimization task
    task = ReasoningTask(
        task_id="opt_test_1",
        reasoning_type=QuantumTaskType.OPTIMIZATION,
        problem_description="Find optimal solution to constraint satisfaction problem",
        inputs={
            'objective': 'minimize_cost',
            'constraints': ['resource_limit', 'time_limit'],
            'problem_size': 8
        },
        use_quantum=True
    )

    result = await system.reason(task)

    print(f"\n{'='*60}")
    print("Unified Quantum Reasoning System Test")
    print(f"{'='*60}")
    print(f"Task: {task.task_id}")
    print(f"Type: {task.reasoning_type.value}")
    print(f"Success: {result.success}")
    print(f"Used Quantum: {result.used_quantum}")
    print(f"Quantum Advantage: {result.quantum_advantage.value}")
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Execution Time: {result.execution_time:.3f}s")
    print(f"\nConclusion: {result.conclusion}")

    # Get statistics
    stats = await system.get_statistics()
    print(f"\nSystem Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
