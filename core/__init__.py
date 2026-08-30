"""
Core interfaces for TorinAI architecture
Defines abstract base classes for major system components
Uses AutonomousCoordinator instead of legacy orchestration
"""
try:
    from .agents.autonomous.autonomous_interfaces import IAutonomousController, IDecisionEngine, IPlanningEngine
    AUTONOMOUS_AVAILABLE = True
except ImportError:
    AUTONOMOUS_AVAILABLE = False
    IAutonomousController = None
    IDecisionEngine = None
    IPlanningEngine = None

try:
    # IKnowledgeManager is gone: its capabilities are owned by three separate
    # stores with different epistemics (ConceptIngestionService, RuleStore,
    # MemoryAgent), and one interface implied a single one existed. See
    # learning_interfaces for the map. The contracts below all have declared
    # owners that satisfy them with no stub methods.
    from .learning.learning_interfaces import (IAdaptationEngine,
                                               ILearningAuthority,
                                               ILearningSystem,
                                               IMemoryConsolidation,
                                               IOutcomePrediction,
                                               IStrategySelection)
    LEARNING_AVAILABLE = True
except ImportError:
    LEARNING_AVAILABLE = False
    ILearningSystem = None
    IAdaptationEngine = None
    ILearningAuthority = None
    IStrategySelection = None
    IOutcomePrediction = None
    IMemoryConsolidation = None

try:
    from .memory.memory_interfaces import IMemorySystem, IMemoryStore, IContextManager
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    IMemorySystem = None
    IMemoryStore = None
    IContextManager = None

try:
    from .reasoning.reasoning_interfaces import IReasoningEngine, IInferenceEngine, IAnalysisEngine
    REASONING_AVAILABLE = True
except ImportError:
    REASONING_AVAILABLE = False
    IReasoningEngine = None
    IInferenceEngine = None
    IAnalysisEngine = None

try:
    from .security import create_integrated_security_system, SecurityLevel, ASISafetyFramework
    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False
    create_integrated_security_system = None
    SecurityLevel = None
    ASISafetyFramework = None

__all__ = [
    # Autonomous Control
    'IAutonomousController',
    'IDecisionEngine',
    'IPlanningEngine',
    
    # Learning
    'ILearningSystem',
    'IAdaptationEngine',
    'ILearningAuthority',
    'IStrategySelection',
    'IOutcomePrediction',
    'IMemoryConsolidation',
    
    # Memory
    'IMemorySystem',
    'IMemoryStore',
    'IContextManager',
    
    # Reasoning
    'IReasoningEngine',
    'IInferenceEngine',
    'IAnalysisEngine',
    
    # Security
    'create_integrated_security_system',
    'SecurityLevel',
    'ASISafetyFramework',
]