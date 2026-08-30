#!/usr/bin/env python3
"""
Hybrid Quantum-Classical Processor
Bridges quantum computing with classical AI systems for enhanced capabilities
"""

import asyncio
import logging
import numpy as np
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass, field

from .interfaces import QuantumProvider, QuantumConfig, QuantumExecutionResult
from .quantum_algorithms import QuantumNeuralNetwork, QuantumOptimization, QuantumMLData
from .ibm_quantum_provider import IBMQuantumProvider

from core.capability import not_implemented

logger = logging.getLogger(__name__)


@dataclass
class HybridWorkflowConfig:
    """Configuration for hybrid quantum-classical workflows"""
    quantum_threshold: float = 0.7  # When to use quantum vs classical
    max_qubits: int = 16
    prefer_quantum_for: List[str] = field(default_factory=lambda: ['optimization', 'ml_training'])
    fallback_to_classical: bool = True
    quantum_timeout: int = 300  # seconds
    use_error_mitigation: bool = True


@dataclass
class HybridTask:
    """Represents a hybrid quantum-classical task"""
    task_id: str
    task_type: str  # 'optimization', 'ml_training', 'inference', 'reasoning'
    input_data: Any
    quantum_suitable: bool = False
    complexity_score: float = 0.0
    expected_quantum_advantage: float = 1.0
    classical_fallback: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class QuantumClassicalBridge:
    """Bridges quantum computing with classical AI systems"""
    
    def __init__(self, quantum_provider: QuantumProvider):
        self.quantum_provider = quantum_provider
        self.performance_history: List[Dict[str, Any]] = []
        self.quantum_algorithms: Dict[str, Any] = {
            'qnn': None,
            'qaoa': None,
            'vqe': None
        }
    
    async def initialize_algorithms(self):
        """Initialize quantum algorithms"""
        try:
            # Initialize Quantum Neural Network
            self.quantum_algorithms['qnn'] = QuantumNeuralNetwork(num_qubits=8, depth=4)
            
            # Initialize Quantum Optimization
            self.quantum_algorithms['qaoa'] = QuantumOptimization(problem_size=8, depth=2)
            
            logger.info("Quantum algorithms initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize quantum algorithms: {e}")
    
    async def execute_hybrid_ml_training(self, 
                                       training_data: np.ndarray,
                                       labels: np.ndarray,
                                       use_quantum: bool = True) -> Dict[str, Any]:
        """Execute hybrid quantum-classical machine learning training"""
        try:
            if use_quantum and self.quantum_algorithms['qnn']:
                # Quantum ML approach
                qml_data = QuantumMLData(features=training_data, labels=labels)
                
                # Train quantum neural network
                qnn = self.quantum_algorithms['qnn']
                training_result = await qnn.train(qml_data, self.quantum_provider)
                
                return {
                    'method': 'quantum',
                    'success': True,
                    'training_result': training_result,
                    # Missing means the trainer did not report one, not parity.
                    'quantum_advantage': training_result.get('quantum_advantage')
                }
            else:
                # Classical fallback
                return await self._classical_ml_training(training_data, labels)
                
        except Exception as e:
            logger.error(f"Hybrid ML training failed: {e}")
            # Fallback to classical
            return await self._classical_ml_training(training_data, labels)
    
    async def execute_hybrid_optimization(self, 
                                        objective_function: Callable,
                                        problem_size: int,
                                        use_quantum: bool = True) -> Dict[str, Any]:
        """Execute hybrid quantum-classical optimization"""
        try:
            if use_quantum and problem_size <= 16:  # Quantum suitable
                # Use QAOA for optimization
                qaoa = QuantumOptimization(problem_size=problem_size, depth=3)
                
                # Create a simple optimization problem (example)
                quantum_start = time.perf_counter()
                result = await qaoa.execute(self.quantum_provider, max_iterations=50)
                quantum_time_s = max(1e-9, time.perf_counter() - quantum_start)

                classical_time_s, classical_best = await self._benchmark_classical_optimization(
                    objective_function,
                    problem_size,
                    budget_evals=200,
                )

                # None when the classical baseline could not be measured:
                # there is no ratio, and 1.0 would assert a parity nobody timed.
                quantum_advantage = (classical_time_s / quantum_time_s
                                     if classical_time_s is not None else None)
                
                return {
                    'method': 'quantum',
                    'success': result.success,
                    'optimal_value': result.processed_result.get('best_cost', float('inf')),
                    'quantum_time_s': quantum_time_s,
                    'classical_baseline_time_s': classical_time_s,
                    'classical_baseline_best_cost': classical_best,
                    'quantum_advantage': (None if quantum_advantage is None
                                          else float(quantum_advantage)),
                    'quantum_advantage_measured': quantum_advantage is not None,
                }
            else:
                # Classical optimization
                return await self._classical_optimization(objective_function, problem_size)
                
        except Exception as e:
            logger.error(f"Hybrid optimization failed: {e}")
            return await self._classical_optimization(objective_function, problem_size)

    async def _benchmark_classical_optimization(
        self,
        objective_function: Callable,
        problem_size: int,
        budget_evals: int = 200,
    ) -> tuple[float, float]:
        """Fast classical baseline benchmark for speed comparisons.

        This is intentionally lightweight (random search) so quantum runs can
        report a measured speed ratio without requiring SciPy.
        """
        start = time.perf_counter()
        best = float("inf")

        # Random search in [-10, 10]^n (matches bounds used in _classical_optimization)
        for _ in range(max(1, int(budget_evals))):
            x = np.random.uniform(-10, 10, problem_size)
            try:
                v = float(objective_function(x))
            except Exception:
                continue
            if v < best:
                best = v

        elapsed = max(1e-9, time.perf_counter() - start)
        return elapsed, best
    
    async def _classical_ml_training(self, 
                                   training_data: np.ndarray,
                                   labels: np.ndarray) -> Dict[str, Any]:
        """Not implemented. Raises rather than returning invented metrics.

        This returned `success: True` with final_loss 0.1, accuracy 0.85 and
        training_time 1.5 -- three constants typed into a placeholder, with a
        comment saying real training "would use scikit-learn, PyTorch, etc."
        Nothing was trained. An accuracy figure is exactly the kind of number a
        caller records, reports and later reasons about.
        """
        raise not_implemented(
            "classical_ml_training",
            "HybridQuantumProcessor._classical_ml_training is a placeholder; "
            "it returned fixed loss/accuracy figures for training that never ran",
        )
    
    async def _classical_optimization(self, 
                                    objective_function: Callable,
                                    problem_size: int) -> Dict[str, Any]:
        """Classical optimization using scipy"""
        try:
            from scipy.optimize import minimize, differential_evolution
            
            # Define bounds for optimization
            bounds = [(-10, 10) for _ in range(problem_size)]
            
            # Try differential evolution for global optimization
            result = differential_evolution(
                objective_function,
                bounds=bounds,
                maxiter=1000,
                workers=-1  # Use all available cores
            )
            
            return {
                'method': 'classical_differential_evolution',
                'success': result.success,
                'optimal_value': float(result.fun),
                'optimal_solution': result.x.tolist(),
                'iterations': result.nit,
                # Classical run: no quantum execution to compare against.
                'quantum_advantage': None
            }
            
        except ImportError:
            # Fallback: simple gradient descent
            import numpy as np
            x = np.random.uniform(-10, 10, problem_size)
            learning_rate = 0.01
            iterations = 1000
            
            for _ in range(iterations):
                # Compute gradient numerically
                grad = np.zeros_like(x)
                eps = 1e-8
                for i in range(len(x)):
                    x_plus = x.copy()
                    x_plus[i] += eps
                    grad[i] = (objective_function(x_plus) - objective_function(x)) / eps
                
                x = x - learning_rate * grad
            
            # NO QUANTUM PATH RAN, so there is no advantage to report. This
            # said `quantum_advantage: 1.0`, which reads as "measured parity"
            # rather than "not applicable" -- a number where the honest answer
            # is that the comparison was never made. The optimisation itself is
            # real and success stays True.
            return {
                'method': 'classical_gradient_descent',
                'success': True,
                'optimal_value': float(objective_function(x)),
                'optimal_solution': x.tolist(),
                'iterations': iterations,
                'quantum_advantage': None
            }
            
        except Exception as e:
            logger.error(f"Classical optimization failed: {e}")
            return {
                'method': 'classical',
                'success': False,
                'error': str(e),
                'quantum_advantage': None,
            }


class HybridWorkflowManager:
    """Manages hybrid quantum-classical workflows"""
    
    def __init__(self, config: HybridWorkflowConfig):
        self.config = config
        self.quantum_provider: Optional[QuantumProvider] = None
        self.bridge: Optional[QuantumClassicalBridge] = None
        self.active_workflows: Dict[str, HybridTask] = {}
        self.workflow_history: List[Dict[str, Any]] = []
    
    async def initialize(self, quantum_config: QuantumConfig):
        """Initialize hybrid workflow manager"""
        try:
            # Initialize quantum provider with config
            self.quantum_provider = IBMQuantumProvider(quantum_config)
            success = await self.quantum_provider.initialize()
            
            if success:
                # Initialize bridge. The result of initialize_algorithms() was
                # discarded, so a bridge whose algorithms failed to load still
                # reported the manager as initialized successfully.
                self.bridge = QuantumClassicalBridge(self.quantum_provider)
                algorithms_ready = await self.bridge.initialize_algorithms()
                if algorithms_ready is False:
                    logger.error(
                        "Hybrid workflow manager NOT initialized: quantum "
                        "algorithms failed to load on the bridge")
                    return False

                logger.info("Hybrid workflow manager initialized successfully")
                return True
            else:
                logger.error("Failed to initialize quantum provider")
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize hybrid workflow manager: {e}")
            return False
    
    async def submit_task(self, task: HybridTask) -> str:
        """Submit a hybrid task for execution"""
        try:
            # Analyze task suitability for quantum processing
            task.quantum_suitable = self._assess_quantum_suitability(task)
            task.complexity_score = self._calculate_complexity(task)
            
            # Store task
            self.active_workflows[task.task_id] = task
            
            # Execute task
            result = await self._execute_task(task)
            
            # Store result
            self.workflow_history.append({
                'task_id': task.task_id,
                'task_type': task.task_type,
                'quantum_used': task.quantum_suitable,
                'result': result,
                'timestamp': datetime.now().isoformat()
            })
            
            return task.task_id
            
        except Exception as e:
            logger.error(f"Failed to submit task {task.task_id}: {e}")
            raise
    
    async def _execute_task(self, task: HybridTask) -> Dict[str, Any]:
        """Execute a hybrid task"""
        if not self.bridge:
            raise RuntimeError("Hybrid bridge not initialized")
        
        try:
            if task.task_type == 'ml_training':
                return await self._handle_ml_training(task)
            elif task.task_type == 'optimization':
                return await self._handle_optimization(task)
            elif task.task_type == 'inference':
                return await self._handle_inference(task)
            elif task.task_type == 'reasoning':
                return await self._handle_reasoning(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
                
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            # Try classical fallback
            if task.classical_fallback:
                return await task.classical_fallback(task.input_data)
            else:
                raise
    
    async def _handle_ml_training(self, task: HybridTask) -> Dict[str, Any]:
        """Handle machine learning training task"""
        if not self.bridge:
            raise RuntimeError("Bridge not initialized")
            
        data = task.input_data
        training_data = data.get('features')
        labels = data.get('labels')
        
        return await self.bridge.execute_hybrid_ml_training(
            training_data=training_data,
            labels=labels,
            use_quantum=task.quantum_suitable
        )
    
    async def _handle_optimization(self, task: HybridTask) -> Dict[str, Any]:
        """Handle optimization task"""
        if not self.bridge:
            raise RuntimeError("Bridge not initialized")
            
        data = task.input_data
        objective_function = data.get('objective_function')
        problem_size = data.get('problem_size', 8)
        
        return await self.bridge.execute_hybrid_optimization(
            objective_function=objective_function,
            problem_size=problem_size,
            use_quantum=task.quantum_suitable
        )
    
    async def _handle_inference(self, task: HybridTask) -> Dict[str, Any]:
        """Handle inference task using quantum-inspired algorithms"""
        try:
            input_data = task.input_data.get('data', np.random.randn(10, 10))
            
            # Use quantum-inspired sampling for inference
            if task.quantum_suitable:
                # Quantum-inspired Boltzmann sampling
                # Simulates quantum superposition for exploration
                temperature = 1.0
                samples = []
                
                for _ in range(100):
                    # Generate sample with Boltzmann distribution
                    energy = np.random.randn()
                    prob = np.exp(-energy / temperature)
                    if np.random.random() < prob:
                        samples.append(np.random.randn(10))
                
                predictions = np.mean(samples, axis=0).tolist()
                confidence = min(0.95, len(samples) / 100.0)
                
                return {
                    'method': 'quantum_inspired_boltzmann',
                    'success': True,
                    'predictions': predictions,
                    'confidence': confidence,
                    'samples_generated': len(samples),
                    # NOT MEASURED. 1.15 was a constant typed in beside real
                    # outputs, so a caller averaging `quantum_advantage` across
                    # runs was averaging a literal. There is no classical
                    # baseline here to compare against.
                    'quantum_advantage': None,
                }
            else:
                # Classical inference with ensemble
                predictions = []
                for _ in range(10):
                    # Simple ensemble prediction
                    pred = np.mean(input_data, axis=0) + np.random.randn(10) * 0.1
                    predictions.append(pred)
                
                final_prediction = np.mean(predictions, axis=0).tolist()
                
                return {
                    'method': 'classical_ensemble',
                    'success': True,
                    'predictions': final_prediction,
                    'confidence': 0.85,
                    'ensemble_size': len(predictions),
                    # Classical path: no quantum run, so nothing to compare.
                    'quantum_advantage': None,
                }
                
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            # `predictions: [0.0] * 10` is not a prediction -- it is ten zeros
            # shaped like one, and a caller that reads `predictions` without
            # checking `success` consumes them as a result.
            return {
                'method': 'fallback',
                'success': False,
                'error': str(e),
                'predictions': None,
                'confidence': None,
            }
    
    async def _handle_reasoning(self, task: HybridTask) -> Dict[str, Any]:
        """Not implemented. Raises rather than returning a sentence.

        This returned `success: True` with the fixed string "Enhanced quantum
        reasoning result" and `quantum_advantage: 1.15` -- no reasoning ran, no
        advantage was measured, and its own comment said "this WOULD integrate
        with...". A placeholder that reports success is worse than a missing
        method: the caller records a completed reasoning task and moves on.
        """
        raise not_implemented(
            "quantum_reasoning",
            "HybridQuantumProcessor._handle_reasoning was never implemented; "
            "core/reasoning/unified_quantum_reasoning_system.py is the system "
            "it was meant to bridge to",
        )
    
    def _assess_quantum_suitability(self, task: HybridTask) -> bool:
        """Assess if task is suitable for quantum processing"""
        # Decision logic for quantum vs classical
        
        if task.task_type in self.config.prefer_quantum_for:
            # Check problem size
            if task.task_type == 'optimization':
                problem_size = task.input_data.get('problem_size', 0)
                if problem_size <= self.config.max_qubits:
                    return True
            
            elif task.task_type == 'ml_training':
                features = task.input_data.get('features', np.array([]))
                if features.size > 0 and features.shape[1] <= self.config.max_qubits:
                    return True
        
        return False
    
    def _calculate_complexity(self, task: HybridTask) -> float:
        """Calculate task complexity score"""
        base_complexity = 0.5
        
        if task.task_type == 'optimization':
            problem_size = task.input_data.get('problem_size', 1)
            return min(base_complexity + problem_size * 0.1, 1.0)
        
        elif task.task_type == 'ml_training':
            features = task.input_data.get('features', np.array([]))
            if features.size > 0:
                return min(base_complexity + features.shape[1] * 0.05, 1.0)
        
        return base_complexity
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        if not self.workflow_history:
            return {'total_tasks': 0}
        
        total_tasks = len(self.workflow_history)
        quantum_tasks = sum(1 for w in self.workflow_history if w['quantum_used'])
        
        # Only runs that actually measured an advantage. Defaulting the
        # missing ones to 1.0 pulled the average toward parity with readings
        # that were never taken.
        measured_advantages = [
            a for a in (w['result'].get('quantum_advantage')
                        for w in self.workflow_history if w['quantum_used'])
            if a is not None
        ]
        # None, not 1.0: an average over zero measurements does not exist, and
        # reporting parity there is a claim about performance nobody observed.
        avg_quantum_advantage = (float(np.mean(measured_advantages))
                                 if measured_advantages else None)
        
        return {
            'total_tasks': total_tasks,
            'quantum_tasks': quantum_tasks,
            'classical_tasks': total_tasks - quantum_tasks,
            'quantum_usage_rate': quantum_tasks / total_tasks if total_tasks > 0 else 0,
            'avg_quantum_advantage': avg_quantum_advantage,
            'advantage_measurements': len(measured_advantages)
        }


class HybridQuantumProcessor:
    """Main interface for hybrid quantum-classical processing"""
    
    def __init__(self):
        self.workflow_manager: Optional[HybridWorkflowManager] = None
        self.initialized = False
    
    async def initialize(self, 
                       quantum_config: QuantumConfig,
                       hybrid_config: Optional[HybridWorkflowConfig] = None):
        """Initialize hybrid quantum processor"""
        try:
            if hybrid_config is None:
                hybrid_config = HybridWorkflowConfig()
            
            self.workflow_manager = HybridWorkflowManager(hybrid_config)
            success = await self.workflow_manager.initialize(quantum_config)
            
            if success:
                self.initialized = True
                logger.info("Hybrid quantum processor initialized successfully")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to initialize hybrid quantum processor: {e}")
            return False
    
    async def process_ml_task(self, 
                            features: np.ndarray,
                            labels: np.ndarray,
                            task_type: str = 'ml_training') -> Dict[str, Any]:
        """Process machine learning task"""
        if not self.initialized:
            raise RuntimeError("Hybrid processor not initialized")
        
        task = HybridTask(
            task_id=f"ml_{datetime.now().timestamp()}",
            task_type=task_type,
            input_data={'features': features, 'labels': labels}
        )
        
        if not self.workflow_manager:
            raise RuntimeError("Workflow manager not initialized")
        
        await self.workflow_manager.submit_task(task)
        return self.workflow_manager.workflow_history[-1]['result']
    
    async def process_optimization_task(self, 
                                      objective_function: Callable,
                                      problem_size: int) -> Dict[str, Any]:
        """Process optimization task"""
        if not self.initialized:
            raise RuntimeError("Hybrid processor not initialized")
        
        task = HybridTask(
            task_id=f"opt_{datetime.now().timestamp()}",
            task_type='optimization',
            input_data={
                'objective_function': objective_function,
                'problem_size': problem_size
            }
        )
        
        if not self.workflow_manager:
            raise RuntimeError("Workflow manager not initialized")
        
        await self.workflow_manager.submit_task(task)
        return self.workflow_manager.workflow_history[-1]['result']
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        if self.workflow_manager:
            return self.workflow_manager.get_performance_stats()
        return {}


# Factory functions
def create_hybrid_processor(quantum_config: Optional[QuantumConfig] = None) -> HybridQuantumProcessor:
    """Create hybrid quantum processor"""
    processor = HybridQuantumProcessor()
    if quantum_config:
        asyncio.create_task(processor.initialize(quantum_config))
    return processor


__all__ = [
    'HybridWorkflowConfig', 'HybridTask', 'QuantumClassicalBridge',
    'HybridWorkflowManager', 'HybridQuantumProcessor', 'create_hybrid_processor'
]