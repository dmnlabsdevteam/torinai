#!/usr/bin/env python3
"""
Quantum Computing Factory
=========================
Factory functions for initializing Torin's quantum computing subsystem with IBM Quantum

Provides:
- IBM Quantum provider initialization with credentials
- Hybrid quantum-classical processor setup
- Quantum system configuration
"""

import logging
import os
from typing import Dict, Any, Optional

from .ibm_quantum_provider import IBMQuantumProvider, IBMQuantumConfig
from .hybrid_processor import HybridQuantumProcessor, HybridWorkflowConfig
from .interfaces import QuantumConfig, QuantumBackendType

logger = logging.getLogger(__name__)


def create_quantum_config(
    api_token: Optional[str] = None,
    use_simulator: bool = True,
    backend_name: Optional[str] = None,
    max_qubits: int = 16,
    optimization_level: int = 1,
    use_error_mitigation: bool = True,
    **kwargs
) -> IBMQuantumConfig:
    """
    Create quantum configuration for IBM Quantum

    Args:
        api_token: IBM Quantum API token (falls back to env var IBM_QUANTUM_TOKEN)
        use_simulator: Use simulator vs real hardware
        backend_name: Specific backend (e.g., "ibm_brisbane", "ibm_kyoto")
        max_qubits: Maximum qubits for circuit
        optimization_level: Transpilation optimization level (0-3)
        use_error_mitigation: Enable error mitigation
        **kwargs: Additional configuration options

    Returns:
        IBMQuantumConfig instance
    """
    # Get API token from environment if not provided
    if api_token is None:
        api_token = os.getenv('IBM_QUANTUM_TOKEN')

    if not api_token:
        logger.warning("No IBM Quantum API token provided - will use simulator only mode")

    config = IBMQuantumConfig(
        api_token=api_token,
        backend_name=backend_name,
        use_simulator=use_simulator,
        optimization_level=optimization_level,
        resilience_level=1 if use_error_mitigation else 0,
        **kwargs
    )

    logger.info(f"Created quantum config: simulator={use_simulator}, backend={backend_name or 'auto'}")
    return config


async def create_quantum_processor(
    config: IBMQuantumConfig,
    workflow_config: Optional[HybridWorkflowConfig] = None
) -> HybridQuantumProcessor:
    """
    Create hybrid quantum-classical processor

    Args:
        config: IBM Quantum configuration
        workflow_config: Hybrid workflow configuration

    Returns:
        Initialized HybridQuantumProcessor
    """
    try:
        # Initialize IBM Quantum provider
        logger.info("Initializing IBM Quantum provider...")
        ibm_provider = IBMQuantumProvider(config)
        await ibm_provider.initialize()

        # Create hybrid processor
        if workflow_config is None:
            workflow_config = HybridWorkflowConfig(
                use_error_mitigation=config.resilience_level > 0,
                max_qubits=16,
                quantum_threshold=0.7,
                prefer_quantum_for=['optimization', 'ml_training'],
                fallback_to_classical=True
            )

        processor = HybridQuantumProcessor()
        await processor.initialize(config, workflow_config)

        logger.info("Hybrid quantum processor initialized successfully")
        return processor

    except Exception as e:
        logger.error(f"Failed to create quantum processor: {e}")
        raise


async def initialize_quantum_computing(
    api_token: Optional[str] = None,
    use_simulator: bool = True,
    **kwargs
) -> HybridQuantumProcessor:
    """
    Initialize complete quantum computing subsystem

    This is the main entry point called by main.py to initialize
    the quantum computing capabilities with IBM Quantum hardware.

    Args:
        api_token: IBM Quantum API token (falls back to env var)
        use_simulator: Use simulator vs real hardware
        **kwargs: Additional configuration options

    Returns:
        Initialized HybridQuantumProcessor

    Raises:
        RuntimeError: If initialization fails
    """
    try:
        logger.info("🚀 Initializing Torin Quantum Computing Subsystem")
        logger.info(f"   Mode: {'Simulator' if use_simulator else 'Real Hardware'}")

        # Create configuration
        config = create_quantum_config(
            api_token=api_token,
            use_simulator=use_simulator,
            use_error_mitigation=True,
            **kwargs
        )

        # Create and initialize processor
        processor = await create_quantum_processor(config)

        logger.info("✅ Quantum computing subsystem initialized successfully")
        if config.api_token:
            logger.info("   Connected to IBM Quantum cloud services")
        else:
            logger.info("   Running in local simulator mode (no cloud connection)")

        return processor

    except Exception as e:
        logger.error(f"Failed to initialize quantum computing: {e}")
        raise RuntimeError(f"Quantum initialization failed: {e}") from e


# Singleton instance
_quantum_processor = None


async def get_quantum_processor() -> Optional[HybridQuantumProcessor]:
    """Get global quantum processor instance (singleton)"""
    global _quantum_processor
    if _quantum_processor is None:
        try:
            _quantum_processor = await initialize_quantum_computing()
        except Exception as e:
            logger.warning(f"Could not initialize quantum processor: {e}")
            return None
    return _quantum_processor


async def get_quantum_capabilities() -> Dict[str, Any]:
    """
    Get quantum computing capabilities and status

    Returns:
        Dict with quantum system capabilities
    """
    try:
        processor = await get_quantum_processor()

        if processor is None:
            return {
                'available': False,
                'reason': 'Quantum processor not initialized'
            }

        # Get backend info from the provider
        backend_info = await processor.quantum_provider.get_backend_info()

        return {
            'available': True,
            'backend': backend_info.get('name', 'unknown'),
            'num_qubits': backend_info.get('num_qubits', 0),
            'simulator': backend_info.get('simulator', True),
            'operational': backend_info.get('operational', True),
            'capabilities': ['optimization', 'ml_training', 'vqe', 'qaoa']
        }

    except Exception as e:
        logger.error(f"Error getting quantum capabilities: {e}")
        return {
            'available': False,
            'reason': str(e)
        }


async def quantum_health_check() -> Dict[str, Any]:
    """
    Perform health check on quantum computing subsystem

    Returns:
        Dict with health status
    """
    try:
        processor = await get_quantum_processor()

        if processor is None:
            return {
                'healthy': False,
                'status': 'not_initialized',
                'message': 'Quantum processor not initialized'
            }

        # Get statistics from provider
        stats = await processor.quantum_provider.get_statistics()

        return {
            'healthy': stats.get('initialized', False),
            'status': 'operational',
            'backend': stats.get('backend_name', 'unknown'),
            'total_jobs': stats.get('total_jobs', 0),
            'success_rate': stats.get('success_rate', 0),
            'message': 'Quantum system operational'
        }

    except Exception as e:
        logger.error(f"Quantum health check failed: {e}")
        return {
            'healthy': False,
            'status': 'error',
            'message': str(e)
        }


async def create_quantum_provider(
    api_token: Optional[str] = None,
    use_simulator: bool = True,
    backend_name: Optional[str] = None,
    **kwargs
) -> IBMQuantumProvider:
    """
    Create and initialize IBM Quantum provider

    Args:
        api_token: IBM Quantum API token
        use_simulator: Use simulator vs real hardware
        backend_name: Specific backend name
        **kwargs: Additional configuration options

    Returns:
        Initialized IBMQuantumProvider
    """
    config = create_quantum_config(
        api_token=api_token,
        use_simulator=use_simulator,
        backend_name=backend_name,
        **kwargs
    )

    provider = IBMQuantumProvider(config)
    await provider.initialize()

    logger.info(f"✓ IBM Quantum provider initialized: {provider.backend.name if provider.backend else 'No backend'}")
    return provider


async def enhance_learning_with_quantum(learning_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhance learning process with quantum computing

    This delegates to the quantum learning bridge for actual implementation

    Args:
        learning_data: Learning data to enhance

    Returns:
        Enhanced learning results
    """
    try:
        # Import here to avoid circular dependency
        from .quantum_learning_bridge import enhance_learning_with_quantum_bridge
        return await enhance_learning_with_quantum_bridge(learning_data)

    except Exception as e:
        logger.error(f"Error in quantum learning enhancement: {e}")
        return learning_data


async def enhance_reasoning_with_quantum(reasoning_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhance reasoning process with quantum computing

    This delegates to the quantum reasoning bridge for actual implementation

    Args:
        reasoning_data: Reasoning data to enhance

    Returns:
        Enhanced reasoning results
    """
    try:
        # Import here to avoid circular dependency
        from .quantum_reasoning_bridge import accelerate_reasoning_with_quantum
        return await accelerate_reasoning_with_quantum(reasoning_data)

    except Exception as e:
        logger.error(f"Error in quantum reasoning enhancement: {e}")
        return reasoning_data


__all__ = [
    'create_quantum_config',
    'create_quantum_processor',
    'create_quantum_provider',
    'initialize_quantum_computing',
    'get_quantum_processor',
    'get_quantum_capabilities',
    'quantum_health_check',
    'enhance_learning_with_quantum',
    'enhance_reasoning_with_quantum',
]
