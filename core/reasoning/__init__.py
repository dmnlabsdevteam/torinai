#!/usr/bin/env python3
"""
TorinAI Reasoning Module
Advanced reasoning engines including abstract, quantum, and symbolic reasoning.
"""

# Import all reasoning components
from .abstract_reasoning_engine import (
    AbstractReasoningEngine, 
    ReasoningContext, 
    ReasoningConclusion,
    ReasoningType, 
    InferenceMethod,
    create_abstract_reasoning_engine
)

from .advanced_proof_engine import (
    AdvancedProofEngine, 
    ProofMethod,
    create_advanced_proof_engine
)

# Import unified quantum reasoning system (replaces old quantum_reasoning_engine)
from .unified_quantum_reasoning_system import (
    UnifiedQuantumReasoningSystem,
    get_unified_reasoning_system,
    get_quantum_reasoning_system,
)

# Backward compatibility aliases
QuantumReasoningSystem = UnifiedQuantumReasoningSystem
QuantumReasoningEngine = UnifiedQuantumReasoningSystem

def create_quantum_reasoning_system(config=None):
    return UnifiedQuantumReasoningSystem(config)

def create_quantum_reasoning_engine(config=None):
    return UnifiedQuantumReasoningSystem(config)

quantum_reasoning_system = get_unified_reasoning_system()


def get_quantum_reasoning() -> UnifiedQuantumReasoningSystem:
    """Backward-compatible accessor used by health checks.

    Returns the global quantum reasoning system instance. If quantum
    capabilities are effectively disabled (e.g., no provider or qiskit),
    the instance will simply operate in classical-only mode and health
    checks can treat it as degraded instead of failing import-time.
    """
    return get_quantum_reasoning_system()

# Import checkpoint system for unlimited reasoning chains
from .checkpoint_manager import (
    Checkpoint,
    CheckpointManager
)

# Backward compatibility aliases
ReasoningCheckpoint = Checkpoint
ReasoningCheckpointManager = CheckpointManager

def get_checkpoint_manager():
    """Get global checkpoint manager instance"""
    return CheckpointManager()

from .context_compression import (
    CompressedContext,
    ContextCompression
)

# Backward compatibility aliases
CompressionResult = CompressedContext
ContextCompressor = ContextCompression

def get_context_compressor():
    """Get context compressor instance"""
    return ContextCompression()

# Import Neural Bridge - connects natural language with formal logic
from .neural_bridge import (
    NeuralSymbolicBridge,
    ReasoningMode,
    ReasoningRequest,
    ReasoningResult as NeuralBridgeResult,
    get_neural_bridge
)

# Backward compatibility aliases
ExtractionMode = ReasoningMode
LogicalFormula = ReasoningRequest
ExtractionResult = NeuralBridgeResult

def extract_logic_from_text(text):
    """Extract logic from text (backward compatibility)"""
    bridge = get_neural_bridge()
    return bridge.extract_logic(text)

# Export main classes
__all__ = [
    'AbstractReasoningEngine', 'ReasoningContext', 'ReasoningConclusion',
    'ReasoningType', 'InferenceMethod', 'create_abstract_reasoning_engine',
    'AdvancedProofEngine', 'ProofMethod', 'create_advanced_proof_engine',
    'QuantumReasoningSystem', 'QuantumReasoningEngine', 'create_quantum_reasoning_system',
    'create_quantum_reasoning_engine', 'quantum_reasoning_system', 'get_quantum_reasoning',
    'ReasoningCheckpoint', 'ReasoningCheckpointManager', 'get_checkpoint_manager',
    'CompressionResult', 'ContextCompressor', 'get_context_compressor',
    'NeuralSymbolicBridge', 'ExtractionMode', 'LogicalFormula', 'ExtractionResult',
    'get_neural_bridge', 'extract_logic_from_text'
]

