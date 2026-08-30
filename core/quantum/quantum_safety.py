#!/usr/bin/env python3
"""
Quantum Safety and Validation Framework
Extends ASI Safety framework to handle quantum computing risks and validation
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from qiskit import QuantumCircuit
from qiskit.quantum_info import Pauli, PauliList

from .interfaces import QuantumExecutionResult, QuantumJobMetadata

logger = logging.getLogger(__name__)


class QuantumRiskLevel(Enum):
    """Risk levels for quantum operations"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class QuantumSafetyViolation(Enum):
    """Types of quantum safety violations"""
    CIRCUIT_TOO_DEEP = "circuit_too_deep"
    TOO_MANY_QUBITS = "too_many_qubits"
    EXCESSIVE_SHOTS = "excessive_shots"
    UNVALIDATED_PARAMETERS = "unvalidated_parameters"
    ERROR_RATE_TOO_HIGH = "error_rate_too_high"
    DECOHERENCE_RISK = "decoherence_risk"
    HARDWARE_LIMITATIONS = "hardware_limitations"


@dataclass
class QuantumSafetyReport:
    """Report from quantum safety validation"""
    circuit_id: str
    risk_level: QuantumRiskLevel
    violations: List[QuantumSafetyViolation] = field(default_factory=list)
    safety_score: float = 1.0  # 0.0 = unsafe, 1.0 = safe
    recommendations: List[str] = field(default_factory=list)
    error_mitigation_required: bool = False
    approved_for_execution: bool = True
    validation_timestamp: str = ""


class QuantumSafetyValidator:
    """Validates quantum circuits and operations for safety"""
    
    def __init__(self):
        self.max_circuit_depth = 100
        self.max_qubits = 32
        self.max_shots = 100000
        self.max_error_rate = 0.1
        self.safety_thresholds = {
            'coherence_time': 100.0,  # microseconds
            'gate_fidelity': 0.99,
            'readout_fidelity': 0.95
        }
    
    def validate_circuit(self, circuit: QuantumCircuit) -> QuantumSafetyReport:
        """Validate quantum circuit for safety"""
        violations = []
        recommendations = []
        
        # Check circuit depth
        if circuit.depth() > self.max_circuit_depth:
            violations.append(QuantumSafetyViolation.CIRCUIT_TOO_DEEP)
            recommendations.append(f"Reduce circuit depth from {circuit.depth()} to below {self.max_circuit_depth}")
        
        # Check number of qubits
        if circuit.num_qubits > self.max_qubits:
            violations.append(QuantumSafetyViolation.TOO_MANY_QUBITS)
            recommendations.append(f"Reduce qubit count from {circuit.num_qubits} to below {self.max_qubits}")
        
        # Calculate risk level
        risk_level = self._calculate_risk_level(circuit, violations)
        
        # Calculate safety score
        safety_score = self._calculate_safety_score(circuit, violations)
        
        return QuantumSafetyReport(
            circuit_id=f"circuit_{id(circuit)}",
            risk_level=risk_level,
            violations=violations,
            safety_score=safety_score,
            recommendations=recommendations,
            error_mitigation_required=len(violations) > 0,
            approved_for_execution=safety_score > 0.5
        )
    
    def validate_execution_parameters(self, 
                                    circuit: QuantumCircuit,
                                    backend_name: str,
                                    shots: int) -> QuantumSafetyReport:
        """Validate execution parameters"""
        violations = []
        recommendations = []
        
        # Validate shots count
        if shots > self.max_shots:
            violations.append(QuantumSafetyViolation.EXCESSIVE_SHOTS)
            recommendations.append(f"Reduce shots from {shots} to below {self.max_shots}")
        
        # Check if using real hardware without error mitigation
        if 'simulator' not in backend_name.lower():
            if not self._has_error_mitigation(circuit):
                recommendations.append("Consider adding error mitigation for real hardware execution")
        
        # Combine with circuit validation
        circuit_report = self.validate_circuit(circuit)
        violations.extend(circuit_report.violations)
        recommendations.extend(circuit_report.recommendations)
        
        risk_level = self._calculate_risk_level(circuit, violations)
        safety_score = self._calculate_safety_score(circuit, violations)
        
        return QuantumSafetyReport(
            circuit_id=f"execution_{id(circuit)}",
            risk_level=risk_level,
            violations=violations,
            safety_score=safety_score,
            recommendations=recommendations,
            error_mitigation_required=len(violations) > 0,
            approved_for_execution=safety_score > 0.3  # More lenient for execution
        )
    
    def _calculate_risk_level(self, 
                            circuit: QuantumCircuit,
                            violations: List[QuantumSafetyViolation]) -> QuantumRiskLevel:
        """Calculate overall risk level"""
        if not violations:
            return QuantumRiskLevel.LOW
        
        # Critical violations
        critical_violations = {
            QuantumSafetyViolation.TOO_MANY_QUBITS,
            QuantumSafetyViolation.EXCESSIVE_SHOTS
        }
        
        if any(v in critical_violations for v in violations):
            return QuantumRiskLevel.CRITICAL
        
        if len(violations) > 2:
            return QuantumRiskLevel.HIGH
        elif len(violations) > 0:
            return QuantumRiskLevel.MEDIUM
        else:
            return QuantumRiskLevel.LOW
    
    def _calculate_safety_score(self, 
                              circuit: QuantumCircuit,
                              violations: List[QuantumSafetyViolation]) -> float:
        """Calculate numerical safety score"""
        base_score = 1.0
        
        # Penalize each violation
        for violation in violations:
            if violation == QuantumSafetyViolation.CIRCUIT_TOO_DEEP:
                base_score -= 0.2
            elif violation == QuantumSafetyViolation.TOO_MANY_QUBITS:
                base_score -= 0.3
            elif violation == QuantumSafetyViolation.EXCESSIVE_SHOTS:
                base_score -= 0.2
            else:
                base_score -= 0.1
        
        return max(0.0, base_score)
    
    def _has_error_mitigation(self, circuit: QuantumCircuit) -> bool:
        """Check if circuit has error mitigation techniques"""
        # Simplified check - in practice, this would be more sophisticated
        return circuit.depth() < 20  # Shallow circuits inherently have less error


class QuantumErrorCorrection:
    """Quantum error correction and mitigation techniques"""
    
    def __init__(self):
        self.error_correction_enabled = True
        self.mitigation_techniques = [
            'zero_noise_extrapolation',
            'readout_error_mitigation', 
            'symmetry_verification'
        ]
    
    def apply_error_mitigation(self, circuit: QuantumCircuit) -> QuantumCircuit:
        """Apply error mitigation to quantum circuit"""
        if not self.error_correction_enabled:
            return circuit
        
        # Create a copy to avoid modifying original
        mitigated_circuit = circuit.copy()
        
        # Add error mitigation (simplified implementation)
        # In practice, this would use sophisticated error correction codes
        
        # Example: Add symmetry verification
        if mitigated_circuit.num_qubits > 1:
            # Add parity checks (simplified)
            for i in range(min(2, mitigated_circuit.num_qubits - 1)):
                mitigated_circuit.cx(i, i + 1)
        
        return mitigated_circuit
    
    def estimate_error_rate(self, 
                          circuit: QuantumCircuit,
                          backend_properties: Dict[str, Any]) -> float:
        """Estimate error rate for circuit execution"""
        # Simplified error estimation
        base_error_rate = 0.001  # 0.1% base error
        
        # Error increases with circuit depth
        depth_penalty = circuit.depth() * 0.0001
        
        # Error increases with number of qubits
        qubit_penalty = circuit.num_qubits * 0.0005
        
        # Backend-specific errors
        backend_error = backend_properties.get('avg_error_rate', 0.01)
        
        total_error_rate = base_error_rate + depth_penalty + qubit_penalty + backend_error
        
        return min(total_error_rate, 0.5)  # Cap at 50%
    
    def recommend_error_mitigation(self, 
                                 error_rate: float,
                                 circuit: QuantumCircuit) -> List[str]:
        """Recommend error mitigation strategies"""
        recommendations = []
        
        if error_rate > 0.1:
            recommendations.append("Use zero-noise extrapolation")
            recommendations.append("Implement readout error mitigation")
        
        if error_rate > 0.05:
            recommendations.append("Consider circuit optimization")
            recommendations.append("Use symmetry verification")
        
        if circuit.depth() > 50:
            recommendations.append("Break circuit into smaller sub-circuits")
        
        if circuit.num_qubits > 16:
            recommendations.append("Consider problem decomposition")
        
        return recommendations


class QuantumCircuitValidator:
    """Validates quantum circuits for correctness and optimization"""
    
    def __init__(self):
        self.validation_rules = [
            self._check_gate_sequence,
            self._check_measurement_placement,
            self._check_circuit_structure,
            self._check_parameter_bounds
        ]
    
    def validate(self, circuit: QuantumCircuit) -> Tuple[bool, List[str]]:
        """Validate circuit and return (is_valid, error_messages)"""
        errors = []
        
        for rule in self.validation_rules:
            try:
                rule_errors = rule(circuit)
                errors.extend(rule_errors)
            except Exception as e:
                errors.append(f"Validation rule failed: {e}")
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    def _check_gate_sequence(self, circuit: QuantumCircuit) -> List[str]:
        """Check for valid gate sequences"""
        errors = []
        
        # Check for redundant gates (simplified)
        if circuit.depth() > circuit.num_qubits * 10:
            errors.append("Circuit may have redundant gates")
        
        return errors
    
    def _check_measurement_placement(self, circuit: QuantumCircuit) -> List[str]:
        """Check measurement placement"""
        errors = []
        
        # In a real implementation, would check if measurements are at the end
        # For now, just ensure we have some measurements if classical registers exist
        if circuit.num_clbits > 0 and not any(
            instr.operation.name == 'measure' 
            for instr in circuit.data
        ):
            errors.append("Circuit has classical bits but no measurements")
        
        return errors
    
    def _check_circuit_structure(self, circuit: QuantumCircuit) -> List[str]:
        """Check overall circuit structure"""
        errors = []
        
        if circuit.num_qubits == 0:
            errors.append("Circuit has no qubits")
        
        if len(circuit.data) == 0:
            errors.append("Circuit is empty")
        
        return errors
    
    def _check_parameter_bounds(self, circuit: QuantumCircuit) -> List[str]:
        """Check parameter bounds for parameterized circuits"""
        errors = []
        
        # For parameterized circuits, check if parameters are within reasonable bounds
        for param in circuit.parameters:
            # This is a simplified check
            if hasattr(param, 'name') and 'theta' in param.name:
                # Rotation parameters should typically be bounded
                pass  # In practice, would check parameter values
        
        return errors


# Integration with ASI Safety Framework
class QuantumASISafetyBridge:
    """Bridges quantum safety with ASI Safety framework"""
    
    def __init__(self):
        self.quantum_validator = QuantumSafetyValidator()
        self.error_correction = QuantumErrorCorrection()
        self.circuit_validator = QuantumCircuitValidator()
    
    async def assess_quantum_action_safety(self, 
                                         circuit: QuantumCircuit,
                                         execution_params: Dict[str, Any]) -> Dict[str, Any]:
        """Assess safety of quantum action for ASI Safety framework"""
        
        # Validate circuit
        circuit_valid, circuit_errors = self.circuit_validator.validate(circuit)
        
        # Safety validation
        safety_report = self.quantum_validator.validate_execution_parameters(
            circuit=circuit,
            backend_name=execution_params.get('backend_name', 'simulator'),
            shots=execution_params.get('shots', 1024)
        )
        
        # Error rate estimation
        error_rate = self.error_correction.estimate_error_rate(
            circuit=circuit,
            backend_properties=execution_params.get('backend_properties', {})
        )
        
        # ASI Safety assessment
        safety_assessment = {
            'quantum_safety_level': safety_report.risk_level.value,
            'circuit_valid': circuit_valid,
            'circuit_errors': circuit_errors,
            'safety_score': safety_report.safety_score,
            'estimated_error_rate': error_rate,
            'approved_for_execution': safety_report.approved_for_execution,
            'safety_violations': [v.value for v in safety_report.violations],
            'recommendations': safety_report.recommendations,
            'requires_error_mitigation': safety_report.error_mitigation_required,
            'quantum_advantage_risk': self._assess_quantum_advantage_risk(circuit),
            'classical_fallback_recommended': error_rate > 0.1
        }
        
        return safety_assessment
    
    def _assess_quantum_advantage_risk(self, circuit: QuantumCircuit) -> str:
        """Assess risk of not achieving quantum advantage"""
        if circuit.depth() < 10 and circuit.num_qubits < 8:
            return "high_risk_no_advantage"
        elif circuit.depth() < 20 and circuit.num_qubits < 16:
            return "medium_risk"
        else:
            return "low_risk"


# Singleton instance
_quantum_safety_bridge = None


async def get_quantum_safety() -> QuantumASISafetyBridge:
    """Get global quantum safety bridge instance (singleton)"""
    global _quantum_safety_bridge
    if _quantum_safety_bridge is None:
        _quantum_safety_bridge = QuantumASISafetyBridge()
    return _quantum_safety_bridge


async def initialize_quantum_safety() -> QuantumASISafetyBridge:
    """Initialize quantum safety bridge (main entry point for main.py)"""
    return await get_quantum_safety()


__all__ = [
    'QuantumRiskLevel', 'QuantumSafetyViolation', 'QuantumSafetyReport',
    'QuantumSafetyValidator', 'QuantumErrorCorrection', 'QuantumCircuitValidator',
    'QuantumASISafetyBridge', 'get_quantum_safety', 'initialize_quantum_safety'
]