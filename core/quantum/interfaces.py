#!/usr/bin/env python3
"""
Quantum Computing Core Interfaces
Abstract base classes for quantum computing components
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Tuple
import uuid

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit import Parameter
from qiskit.providers import Backend, Job
from qiskit.result import Result
from typing import Dict, List, Optional, Any, Union, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from qiskit.circuit import Parameter as QiskitParameter


class QuantumBackendType(Enum):
    """Types of quantum backends"""
    SIMULATOR = "simulator"
    REAL_HARDWARE = "real_hardware"
    CLOUD = "cloud"
    LOCAL = "local"


class QuantumAlgorithmType(Enum):
    """Types of quantum algorithms"""
    OPTIMIZATION = "optimization"
    MACHINE_LEARNING = "machine_learning"
    SEARCH = "search"
    CRYPTOGRAPHY = "cryptography"
    SIMULATION = "simulation"
    NEURAL_NETWORK = "neural_network"


class JobStatus(Enum):
    """Quantum job execution status"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QuantumConfig:
    """Configuration for quantum computing operations"""
    backend_name: Optional[str] = None
    max_qubits: int = 32
    max_shots: int = 8192
    optimization_level: int = 1
    timeout: int = 300
    use_error_mitigation: bool = True
    use_noise_model: bool = False
    provider_token: Optional[str] = None
    provider_hub: str = "ibm-q"
    provider_group: str = "open"
    provider_project: str = "main"


@dataclass
class QuantumJobMetadata:
    """Metadata for quantum job tracking"""
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    algorithm_type: QuantumAlgorithmType = QuantumAlgorithmType.OPTIMIZATION
    backend_name: str = ""
    circuit_depth: int = 0
    num_qubits: int = 0
    num_shots: int = 1024
    submitted_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: JobStatus = JobStatus.PENDING
    error_message: Optional[str] = None
    user_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuantumExecutionResult:
    """Result from quantum algorithm execution"""
    job_metadata: QuantumJobMetadata
    counts: Dict[str, int] = field(default_factory=dict)
    raw_result: Optional[Result] = None
    processed_result: Optional[Any] = None
    execution_time: float = 0.0
    success: bool = False
    error_message: Optional[str] = None
    quantum_advantage_score: float = 0.0
    fidelity: float = 0.0
    backend_properties: Dict[str, Any] = field(default_factory=dict)


class QuantumProvider(ABC):
    """Abstract base class for quantum computing providers"""
    
    def __init__(self):
        self.initialized: bool = False
    
    @abstractmethod
    async def initialize(self, config: QuantumConfig) -> bool:
        """Initialize the quantum provider"""
        pass
    
    @abstractmethod
    async def get_available_backends(self) -> List[str]:
        """Get list of available quantum backends"""
        pass
    
    @abstractmethod
    async def select_optimal_backend(self, 
                                   circuit: QuantumCircuit,
                                   requirements: Dict[str, Any]) -> str:
        """Select optimal backend for circuit execution"""
        pass
    
    @abstractmethod
    async def execute_circuit(self, 
                            circuit: QuantumCircuit,
                            backend_name: str,
                            shots: int = 1024) -> QuantumExecutionResult:
        """Execute quantum circuit on specified backend"""
        pass
    
    @abstractmethod
    async def get_backend_status(self, backend_name: str) -> Dict[str, Any]:
        """Get current status of quantum backend"""
        pass
    
    @abstractmethod
    async def estimate_cost(self, 
                          circuit: QuantumCircuit,
                          backend_name: str,
                          shots: int) -> Dict[str, float]:
        """Estimate cost of circuit execution"""
        pass


class QuantumCircuitManager(ABC):
    """Abstract base class for quantum circuit management"""
    
    @abstractmethod
    def create_circuit(self, num_qubits: int, num_classical: int = 0) -> QuantumCircuit:
        """Create new quantum circuit"""
        pass
    
    @abstractmethod
    def optimize_circuit(self, circuit: QuantumCircuit) -> QuantumCircuit:
        """Optimize quantum circuit for execution"""
        pass
    
    @abstractmethod
    def validate_circuit(self, circuit: QuantumCircuit) -> Tuple[bool, List[str]]:
        """Validate quantum circuit for errors"""
        pass
    
    @abstractmethod
    def transpile_circuit(self, 
                         circuit: QuantumCircuit,
                         backend: Backend) -> QuantumCircuit:
        """Transpile circuit for specific backend"""
        pass
    
    @abstractmethod
    def estimate_circuit_depth(self, circuit: QuantumCircuit) -> int:
        """Estimate circuit depth after transpilation"""
        pass
    
    @abstractmethod
    def add_error_mitigation(self, circuit: QuantumCircuit) -> QuantumCircuit:
        """Add error mitigation to circuit"""
        pass


class QuantumAlgorithmBase(ABC):
    """Abstract base class for quantum algorithms"""
    
    def __init__(self, algorithm_type: QuantumAlgorithmType):
        self.algorithm_type = algorithm_type
        self.parameters: Dict[str, Any] = {}
        self.optimization_history: List[Dict[str, Any]] = []
        
    @abstractmethod
    def construct_circuit(self, **kwargs) -> QuantumCircuit:
        """Construct the quantum circuit for this algorithm"""
        pass
    
    @abstractmethod
    async def execute(self, 
                     provider: QuantumProvider,
                     **kwargs) -> QuantumExecutionResult:
        """Execute the quantum algorithm"""
        pass
    
    @abstractmethod
    def process_result(self, result: QuantumExecutionResult) -> Any:
        """Process quantum execution result into meaningful output"""
        pass
    
    @abstractmethod
    def estimate_resources(self) -> Dict[str, int]:
        """Estimate quantum resources needed"""
        pass
    
    def add_parameter(self, name: str, parameter: Any):
        """Add a parameter to the algorithm"""
        self.parameters[name] = parameter
    
    def get_parameter_bounds(self) -> Dict[str, Tuple[float, float]]:
        """Get bounds for algorithm parameters"""
        return {}
    
    def update_parameters(self, parameter_values: Dict[str, float]):
        """Update algorithm parameters with new values"""
        pass


class QuantumBackendSelector(ABC):
    """Abstract base class for quantum backend selection"""
    
    @abstractmethod
    async def rank_backends(self, 
                          circuit: QuantumCircuit,
                          requirements: Dict[str, Any]) -> List[Tuple[str, float]]:
        """Rank available backends by suitability score"""
        pass
    
    @abstractmethod
    async def check_backend_availability(self, backend_name: str) -> bool:
        """Check if backend is currently available"""
        pass
    
    @abstractmethod
    async def get_queue_length(self, backend_name: str) -> int:
        """Get current queue length for backend"""
        pass
    
    @abstractmethod
    async def estimate_wait_time(self, backend_name: str) -> int:
        """Estimate wait time in minutes"""
        pass


class QuantumJobManager(ABC):
    """Abstract base class for quantum job management"""
    
    @abstractmethod
    async def submit_job(self, 
                        circuit: QuantumCircuit,
                        backend_name: str,
                        metadata: QuantumJobMetadata) -> str:
        """Submit quantum job for execution"""
        pass
    
    @abstractmethod
    async def monitor_job(self, job_id: str) -> JobStatus:
        """Monitor job execution status"""
        pass
    
    @abstractmethod
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel pending or running job"""
        pass
    
    @abstractmethod
    async def get_job_result(self, job_id: str) -> Optional[QuantumExecutionResult]:
        """Retrieve job execution result"""
        pass
    
    @abstractmethod
    async def list_active_jobs(self) -> List[QuantumJobMetadata]:
        """List all active jobs"""
        pass


class QuantumResultProcessor(ABC):
    """Abstract base class for quantum result processing"""
    
    @abstractmethod
    def extract_counts(self, result: Result) -> Dict[str, int]:
        """Extract measurement counts from quantum result"""
        pass
    
    @abstractmethod
    def calculate_expectation_value(self, 
                                  counts: Dict[str, int],
                                  observable: Any) -> float:
        """Calculate expectation value of observable"""
        pass
    
    @abstractmethod
    def apply_error_mitigation(self, 
                             counts: Dict[str, int],
                             circuit: QuantumCircuit) -> Dict[str, int]:
        """Apply error mitigation to measurement counts"""
        pass
    
    @abstractmethod
    def calculate_fidelity(self, 
                         measured_counts: Dict[str, int],
                         expected_counts: Dict[str, int]) -> float:
        """Calculate fidelity between measured and expected results"""
        pass
    
    @abstractmethod
    def detect_quantum_advantage(self, 
                               quantum_result: Any,
                               classical_baseline: Any) -> float:
        """Detect and quantify quantum advantage"""
        pass


# Export all interfaces
__all__ = [
    'QuantumBackendType', 'QuantumAlgorithmType', 'JobStatus',
    'QuantumConfig', 'QuantumJobMetadata', 'QuantumExecutionResult',
    'QuantumProvider', 'QuantumCircuitManager', 'QuantumAlgorithmBase',
    'QuantumBackendSelector', 'QuantumJobManager', 'QuantumResultProcessor'
]