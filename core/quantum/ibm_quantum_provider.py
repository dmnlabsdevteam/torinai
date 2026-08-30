#!/usr/bin/env python3
"""
IBM Quantum Provider
====================
Integration with IBM Quantum computing platform

Provides access to:
- IBM Quantum cloud services
- Real quantum hardware
- Quantum simulators
- Job management and result retrieval
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from enum import Enum

# Qiskit imports
try:
    from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
    from qiskit_ibm_runtime import (
        QiskitRuntimeService,
        Session,
        SamplerV2 as Sampler,
        EstimatorV2 as Estimator,
        Options
    )
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit.providers import Backend, JobStatus
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False
    # Fallback definitions
    class QiskitRuntimeService:
        pass
    class Backend:
        pass
    class JobStatus:
        DONE = "DONE"
        ERROR = "ERROR"
        RUNNING = "RUNNING"
        CANCELLED = "CANCELLED"

from core.quantum.interfaces import (
    QuantumProvider,
    QuantumBackendType,
    QuantumJobMetadata,
    QuantumExecutionResult
)

from core.capability import raise_if_structural

logger = logging.getLogger(__name__)


# IBM Quantum configuration constants
IBM_CHANNEL_DEFAULT = "ibm_quantum_platform"
IBM_INSTANCE_DEFAULT = "ibm-q/open/main"  # Default public hub


class IBMBackendType(Enum):
    """IBM-specific backend types"""
    SIMULATOR_STATEVECTOR = "simulator_statevector"
    SIMULATOR_MPS = "simulator_mps"
    SIMULATOR_EXTENDED_STABILIZER = "simulator_extended_stabilizer"
    SIMULATOR_STABILIZER = "simulator_stabilizer"
    REAL_HARDWARE = "ibmq_hardware"
    FAKE_PROVIDER = "fake_provider"


@dataclass
class IBMQuantumConfig:
    """IBM Quantum configuration"""
    # Authentication
    api_token: Optional[str] = None
    channel: str = IBM_CHANNEL_DEFAULT

    # Instance (hub/group/project)
    instance: str = IBM_INSTANCE_DEFAULT

    # Backend selection
    backend_name: Optional[str] = None  # e.g., "ibm_brisbane", "ibm_kyoto"
    use_simulator: bool = True

    # Execution settings
    max_shots: int = 8192
    optimization_level: int = 1  # 0-3
    resilience_level: int = 1    # 0-2 (error mitigation)
    timeout: int = 300

    # Session settings
    max_time: int = 28800  # 8 hours max session

    metadata: Dict[str, Any] = field(default_factory=dict)


class IBMQuantumProvider(QuantumProvider):
    """
    IBM Quantum Platform Provider

    Provides integration with IBM's quantum computing services,
    including real quantum hardware and cloud simulators.

    Features:
    - Automatic authentication with IBM Quantum
    - Backend selection (simulator or real hardware)
    - Circuit optimization and transpilation
    - Job submission and tracking
    - Result retrieval and processing
    - Error mitigation support
    """

    def __init__(self, config: IBMQuantumConfig = None):
        self.config = config or IBMQuantumConfig()
        self.service: Optional[QiskitRuntimeService] = None
        self.backend: Optional[Backend] = None
        self.session: Optional[Session] = None
        self.initialized = False

        # Job tracking
        self.active_jobs: Dict[str, Any] = {}
        self.job_history: List[QuantumJobMetadata] = []

        # Statistics
        self.stats = {
            'total_jobs': 0,
            'successful_jobs': 0,
            'failed_jobs': 0,
            'total_shots': 0,
            'total_circuits': 0
        }

        logger.info("IBMQuantumProvider initialized")

    async def initialize(self) -> bool:
        """
        Initialize IBM Quantum connection

        Returns:
            Success status
        """
        if not QISKIT_AVAILABLE:
            logger.error("Qiskit not available - cannot initialize IBM Quantum")
            return False

        try:
            logger.info("Initializing IBM Quantum connection")

            # Initialize QiskitRuntimeService
            if self.config.api_token:
                # Use provided token
                self.service = QiskitRuntimeService(
                    channel=self.config.channel,
                    token=self.config.api_token,
                    instance=self.config.instance
                )
            else:
                # Use saved credentials
                try:
                    self.service = QiskitRuntimeService(
                        channel=self.config.channel,
                        instance=self.config.instance
                    )
                except Exception as e:
                    logger.warning(f"Could not load saved credentials: {e}")
                    logger.info("Attempting to use local simulator")
                    self.config.use_simulator = True

            # Select backend
            await self._select_backend()

            # INITIALIZED MEANS A BACKEND WAS SELECTED. This set
            # initialized = True and returned True unconditionally, then logged
            # "(backend: None)" on the same line -- so every caller believed
            # quantum execution was available while there was nothing to run on,
            # and the log recorded the contradiction without acting on it.
            if self.backend is None:
                self.initialized = False
                logger.error(
                    "IBM Quantum NOT initialized: no backend was selected "
                    "(no valid API token, or no operational backend matched). "
                    "Quantum execution is unavailable.")
                return False

            self.initialized = True
            logger.info(f"✓ IBM Quantum initialized (backend: {self.backend.name})")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize IBM Quantum: {e}")
            return False

    async def _select_backend(self):
        """Select appropriate quantum backend"""
        try:
            if self.config.use_simulator:
                # Use local Aer simulator
                from qiskit_aer import AerSimulator
                self.backend = AerSimulator()
                logger.info("Using local Aer simulator")

            elif self.config.backend_name:
                # Use specific backend
                self.backend = self.service.backend(self.config.backend_name)
                logger.info(f"Using backend: {self.config.backend_name}")

            else:
                # Auto-select least busy backend
                backend_list = self.service.backends(
                    operational=True,
                    simulator=False
                )

                if backend_list:
                    # Get least busy backend
                    self.backend = self.service.least_busy(min_num_qubits=5)
                    logger.info(f"Auto-selected least busy backend: {self.backend.name}")
                else:
                    # Fallback to simulator
                    logger.warning("No real backends available, using simulator")
                    from qiskit_aer import AerSimulator
                    self.backend = AerSimulator()

        except Exception as e:
            logger.error(f"Backend selection failed: {e}")
            # Fallback to simulator
            try:
                from qiskit_aer import AerSimulator
                self.backend = AerSimulator()
                logger.info("Fallback: Using Aer simulator")
            except:
                logger.error("Could not initialize any backend")
                raise

    async def execute_circuit(
        self,
        circuit: QuantumCircuit,
        shots: int = 1024,
        metadata: Dict[str, Any] = None
    ) -> QuantumExecutionResult:
        """
        Execute quantum circuit

        Args:
            circuit: Quantum circuit to execute
            shots: Number of measurement shots
            metadata: Additional metadata

        Returns:
            QuantumResult with measurement outcomes
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if not self.backend:
            raise RuntimeError("No backend available")

        try:
            job_id = f"ibm_job_{datetime.now().timestamp()}"
            start_time = datetime.now()

            logger.info(f"Executing circuit on {self.backend.name}: {shots} shots")

            # Transpile circuit for backend
            pm = generate_preset_pass_manager(
                optimization_level=self.config.optimization_level,
                backend=self.backend
            )
            transpiled = pm.run(circuit)

            logger.debug(f"Circuit transpiled: {transpiled.depth()} depth, {transpiled.num_qubits} qubits")

            # Execute based on backend type
            if self.config.use_simulator or 'aer' in self.backend.name.lower():
                # Local simulator - direct execution
                from qiskit import transpile
                from qiskit_aer import AerSimulator

                simulator = AerSimulator()
                transpiled_circuit = transpile(circuit, simulator)
                job = simulator.run(transpiled_circuit, shots=shots)
                qiskit_result = job.result()

                # Extract counts
                counts = qiskit_result.get_counts()

                # Convert to probabilities
                total_shots = sum(counts.values())
                probabilities = {
                    bitstring: count / total_shots
                    for bitstring, count in counts.items()
                }

            else:
                # Real hardware - use Sampler primitive
                if not self.session:
                    self.session = Session(backend=self.backend)

                sampler = Sampler(session=self.session)

                # Configure options
                options = Options()
                options.execution.shots = shots
                options.resilience_level = self.config.resilience_level
                options.optimization_level = self.config.optimization_level

                # Run with primitive
                job = sampler.run([transpiled], shots=shots)
                result = job.result()

                # Extract data from SamplerV2 result
                pub_result = result[0]
                counts = pub_result.data.meas.get_counts()

                # Convert to probabilities
                total_shots = sum(counts.values())
                probabilities = {
                    bitstring: count / total_shots
                    for bitstring, count in counts.items()
                }

            # Calculate execution time
            execution_time = (datetime.now() - start_time).total_seconds()

            # Update statistics
            self.stats['total_jobs'] += 1
            self.stats['successful_jobs'] += 1
            self.stats['total_shots'] += shots
            self.stats['total_circuits'] += 1

            # Build result
            quantum_result = QuantumExecutionResult(
                job_id=job_id,
                success=True,
                counts=counts,
                probabilities=probabilities,
                execution_time=execution_time,
                shots=shots,
                backend_name=self.backend.name,
                metadata={
                    'circuit_depth': transpiled.depth(),
                    'num_qubits': transpiled.num_qubits,
                    'optimization_level': self.config.optimization_level,
                    'resilience_level': self.config.resilience_level,
                    **(metadata or {})
                }
            )

            logger.info(
                f"✓ Circuit executed successfully: {execution_time:.2f}s, "
                f"{len(probabilities)} unique outcomes"
            )

            return quantum_result

        except Exception as e:
            logger.error(f"Circuit execution failed: {e}")
            self.stats['failed_jobs'] += 1

            return QuantumExecutionResult(
                job_id=job_id,
                success=False,
                counts={},
                probabilities={},
                execution_time=execution_time,
                shots=shots,
                backend_name=self.backend.name if self.backend else "unknown",
                error=str(e),
                metadata=metadata or {}
            )

    async def get_backend_info(self) -> Dict[str, Any]:
        """Get information about current backend"""
        if not self.backend:
            return {"error": "No backend configured"}

        try:
            config = self.backend.configuration()

            info = {
                "name": self.backend.name,
                "backend_version": getattr(config, 'backend_version', 'unknown'),
                "num_qubits": getattr(config, 'n_qubits', 0),
                "simulator": getattr(config, 'simulator', True),
                "local": getattr(config, 'local', True),
                "coupling_map": getattr(config, 'coupling_map', None),
                "basis_gates": getattr(config, 'basis_gates', []),
                "max_shots": getattr(config, 'max_shots', self.config.max_shots)
            }

            # Add status for real hardware
            if not info['simulator'] and self.service:
                try:
                    status = self.backend.status()
                    info['operational'] = status.operational
                    info['pending_jobs'] = status.pending_jobs
                    info['status_msg'] = status.status_msg
                except:
                    pass

            return info

        except Exception as e:
            logger.error(f"Failed to get backend info: {e}")
            return {"error": str(e)}

    async def list_available_backends(self) -> List[Dict[str, Any]]:
        """List all available backends"""
        if not self.service:
            return []

        try:
            backends = self.service.backends()

            backend_list = []
            for backend in backends:
                try:
                    config = backend.configuration()
                    status = backend.status()

                    backend_list.append({
                        "name": backend.name,
                        "num_qubits": config.n_qubits,
                        "simulator": config.simulator,
                        "operational": status.operational,
                        "pending_jobs": status.pending_jobs,
                        "basis_gates": config.basis_gates[:5]  # First 5 gates
                    })
                except Exception as backend_error:
                    # A backend whose configuration could not be read is
                    # REPORTED, not dropped. `except: pass` silently shortened
                    # the list, so a backend that exists and is momentarily
                    # unreadable was indistinguishable from one that does not
                    # exist at all.
                    logger.warning("Could not read backend %s: %s",
                                   getattr(backend, "name", "?"), backend_error)
                    backend_list.append({
                        "name": getattr(backend, "name", "unknown"),
                        "readable": False,
                        "error": str(backend_error),
                    })

            return backend_list

        except Exception as e:
            # An empty list means "this account has no backends". A listing
            # that failed is a different fact and must not borrow that meaning
            # -- a caller that sees [] concludes quantum hardware is
            # unavailable to it, and stops asking.
            raise_if_structural(e, "ibm_quantum_provider.list_backends")
            logger.error("Could not list backends (not the same as none "
                         "existing): %s", e)
            raise

    async def get_statistics(self) -> Dict[str, Any]:
        """Get provider statistics"""
        return {
            **self.stats,
            "backend_name": self.backend.name if self.backend else "None",
            "initialized": self.initialized,
            "active_jobs": len(self.active_jobs),
            "success_rate": (
                self.stats['successful_jobs'] / self.stats['total_jobs'] * 100
                if self.stats['total_jobs'] > 0 else 0
            )
        }

    async def estimate_cost(self, circuit: 'QuantumCircuit', shots: int = 1024) -> Dict[str, Any]:
        """Estimate cost of running a quantum circuit"""
        try:
            if self.config.use_simulator:
                return {'cost_usd': 0.0, 'backend': 'simulator', 'shots': shots, 'estimated': True}

            if not self.backend:
                # No backend means no estimate, not a free run. 0.0 here
                # reads as 'costs nothing' to any caller that branches on it.
                return {'cost_usd': None, 'estimated': False,
                        'error': 'No backend available'}

            estimated_time_seconds = shots / 100
            cost_per_second = 1.60 / 100
            estimated_cost = estimated_time_seconds * cost_per_second

            return {
                'cost_usd': round(estimated_cost, 4),
                'backend': self.backend.name,
                'shots': shots,
                'estimated_time_seconds': estimated_time_seconds,
                'estimated': True
            }
        except Exception as e:
            # NOT ZERO. `cost_usd: 0.0` on a failed estimate tells the caller
            # the run is free, which is the one answer that invites them to
            # proceed. None says the estimate does not exist.
            logger.error(f"Error estimating cost: {e}")
            return {'cost_usd': None, 'estimated': False, 'error': str(e)}

    async def get_available_backends(self) -> List[str]:
        """Get list of available backend names"""
        try:
            backends = await self.list_backends()
            return [b['name'] for b in backends]
        except Exception as e:
            raise_if_structural(e, "ibm_quantum_provider.get_available_backends")
            logger.error("Could not read available backends: %s", e)
            raise

    async def get_backend_status(self, backend_name: str) -> Dict[str, Any]:
        """Get status of a specific backend"""
        try:
            if not self.service:
                return {'status': 'unavailable', 'reason': 'Service not initialized'}

            if QISKIT_AVAILABLE:
                try:
                    backend = self.service.backend(backend_name)
                    status = backend.status()
                    return {
                        'name': backend_name,
                        'operational': status.operational if hasattr(status, 'operational') else True,
                        'status_msg': status.status_msg if hasattr(status, 'status_msg') else 'operational',
                        'pending_jobs': status.pending_jobs if hasattr(status, 'pending_jobs') else 0,
                        'available': True
                    }
                except Exception as e:
                    return {'name': backend_name, 'available': False, 'error': str(e)}
            else:
                return {'name': backend_name, 'available': False, 'reason': 'Qiskit not available'}
        except Exception as e:
            logger.error(f"Error getting backend status: {e}")
            return {'status': 'error', 'error': str(e)}

    async def select_optimal_backend(self, num_qubits: int, requirements: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Select optimal backend based on requirements"""
        try:
            if self.config.use_simulator:
                return 'aer_simulator' if QISKIT_AVAILABLE else 'simulator'

            backends = await self.list_backends()
            suitable = [b for b in backends if b.get('num_qubits', 0) >= num_qubits]

            if not suitable:
                logger.warning(f"No backends found with {num_qubits}+ qubits")
                return None

            suitable.sort(
                key=lambda b: (
                    not b.get('operational', True),
                    b.get('pending_jobs', 999),
                    -b.get('num_qubits', 0)
                )
            )

            selected = suitable[0]
            logger.info(f"Selected optimal backend: {selected['name']} ({selected.get('num_qubits')} qubits)")
            return selected['name']
        except Exception as e:
            logger.error(f"Error selecting optimal backend: {e}")
            return None

    async def shutdown(self):
        """Shutdown provider and cleanup resources"""
        try:
            # Close session if active
            if self.session:
                self.session.close()
                self.session = None

            logger.info("IBM Quantum provider shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Convenience function
def get_ibm_provider(
    api_token: str = None,
    backend_name: str = None,
    use_simulator: bool = True
) -> IBMQuantumProvider:
    """
    Get IBM Quantum provider instance

    Args:
        api_token: IBM Quantum API token
        backend_name: Specific backend to use
        use_simulator: Whether to use simulator

    Returns:
        Configured IBMQuantumProvider
    """
    config = IBMQuantumConfig(
        api_token=api_token,
        backend_name=backend_name,
        use_simulator=use_simulator
    )

    return IBMQuantumProvider(config=config)


# Test/example usage
async def main():
    """Test IBM Quantum provider"""
    logging.basicConfig(level=logging.INFO)

    provider = get_ibm_provider(use_simulator=True)
    await provider.initialize()

    # Test circuit
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])

    result = await provider.execute_circuit(qc, shots=1024)

    print(f"\n{'='*50}")
    print("IBM Quantum Provider Test")
    print(f"{'='*50}")
    print(f"Success: {result.success}")
    print(f"Backend: {result.backend_name}")
    print(f"Execution time: {result.execution_time:.2f}s")
    print(f"\nMeasurement counts:")
    for bitstring, count in result.counts.items():
        print(f"  {bitstring}: {count}")

    # Get statistics
    stats = await provider.get_statistics()
    print(f"\nProvider statistics: {stats}")

    await provider.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
