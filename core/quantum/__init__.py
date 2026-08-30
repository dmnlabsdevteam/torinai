#!/usr/bin/env python3
"""
Quantum Computing Module for Torin ASI
Provides quantum computing capabilities including IBM Quantum integration
"""

from .interfaces import (
    QuantumProvider, QuantumAlgorithmBase, QuantumCircuitManager,
    QuantumConfig, QuantumExecutionResult, JobStatus
)

from .ibm_quantum_provider import IBMQuantumProvider

from .quantum_algorithms import (
    QuantumNeuralNetwork, QuantumOptimization, VariationalQuantumEigensolver,
    QuantumMLData, QuantumFeatureMap
)

from .hybrid_processor import (
    HybridQuantumProcessor, QuantumClassicalBridge, HybridTask
)

from .quantum_safety import (
    QuantumSafetyValidator, QuantumASISafetyBridge
)

from .quantum_factory import (
    create_quantum_processor, create_quantum_config,
    initialize_quantum_computing, get_quantum_processor
)

from .quantum_learning_bridge import (
    QuantumLearningBridge, QuantumLearningResult,
    get_quantum_learning_bridge, enhance_learning_with_quantum_bridge,
    inject_quantum_into_learning_system
)

from .quantum_reasoning_bridge import (
    QuantumReasoningBridge, QuantumReasoningResult, ReasoningAccelerationRequest,
    get_quantum_reasoning_bridge, accelerate_reasoning_with_quantum,
    inject_quantum_into_reasoning_system
)

from .asi_quantum_safety import (
    QuantumSafetyLevel, QuantumASISafetyResult, QuantumSafetyPolicy,
    ASIQuantumSafetyIntegration, get_asi_quantum_safety,
    assess_quantum_operation_safety, inject_quantum_safety_into_asi
)

from .quantum_monitoring import (
    QuantumPerformanceMetrics, QuantumHealthStatus, QuantumUsageStatistics,
    QuantumMonitoringSystem, get_quantum_monitoring, record_quantum_operation,
    get_quantum_health_status, get_quantum_performance_summary,
    inject_quantum_monitoring_into_system
)

__all__ = [
    # Core interfaces
    'QuantumProvider', 'QuantumAlgorithmBase', 'QuantumCircuitManager',
    'QuantumConfig', 'QuantumExecutionResult', 'JobStatus',

    # IBM Quantum integration
    'IBMQuantumProvider',

    # Quantum algorithms
    'QuantumNeuralNetwork', 'QuantumOptimization', 'VariationalQuantumEigensolver',
    'QuantumMLData', 'QuantumFeatureMap',

    # Hybrid processing
    'HybridQuantumProcessor', 'QuantumClassicalBridge', 'HybridTask',

    # Safety framework
    'QuantumSafetyValidator', 'QuantumASISafetyBridge',

    # Factory functions
    'create_quantum_processor', 'create_quantum_config',
    'initialize_quantum_computing', 'get_quantum_processor',

    # Learning bridge
    'QuantumLearningBridge', 'QuantumLearningResult',
    'get_quantum_learning_bridge', 'enhance_learning_with_quantum_bridge',
    'inject_quantum_into_learning_system',

    # Reasoning bridge
    'QuantumReasoningBridge', 'QuantumReasoningResult', 'ReasoningAccelerationRequest',
    'get_quantum_reasoning_bridge', 'accelerate_reasoning_with_quantum',
    'inject_quantum_into_reasoning_system',

    # ASI Safety integration
    'QuantumSafetyLevel', 'QuantumASISafetyResult', 'QuantumSafetyPolicy',
    'ASIQuantumSafetyIntegration', 'get_asi_quantum_safety',
    'assess_quantum_operation_safety', 'inject_quantum_safety_into_asi',

    # Monitoring and statistics
    'QuantumPerformanceMetrics', 'QuantumHealthStatus', 'QuantumUsageStatistics',
    'QuantumMonitoringSystem', 'get_quantum_monitoring', 'record_quantum_operation',
    'get_quantum_health_status', 'get_quantum_performance_summary',
    'inject_quantum_monitoring_into_system'
]

# Core quantum computing interfaces
from .interfaces import (
    QuantumProvider,
    QuantumCircuitManager,
    QuantumAlgorithmBase,
    QuantumBackendSelector,
    QuantumJobManager,
    QuantumResultProcessor
)

# IBM Quantum integration
from .ibm_quantum_provider import (
    IBMQuantumProvider,
    IBMQuantumConfig
)

# Quantum algorithms
from .quantum_algorithms import (
    QuantumMachineLearning,
    VariationalQuantumEigensolver,
    QuantumOptimization,
    QuantumNeuralNetwork,
    QAOA
)

# Quantum-classical hybrid systems
from .hybrid_processor import (
    HybridQuantumProcessor,
    QuantumClassicalBridge,
    HybridWorkflowManager
)

# Quantum safety and validation
from .quantum_safety import (
    QuantumSafetyValidator,
    QuantumErrorCorrection,
    QuantumCircuitValidator
)

# Duplicate section removed - all imports are at the top of the file