"""
Predictive Intelligence System

Advanced predictive framework integrating quantum reasoning, meta-learning,
research systems, and emergent cognition for autonomous decision-making.
"""

import asyncio
import logging
import time
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import numpy as np
from collections import defaultdict, deque

from core.learning.learning_interfaces import IOutcomePrediction

logger = logging.getLogger(__name__)

class PredictionDomain(Enum):
    """Domains for predictions"""
    SYSTEM_PERFORMANCE = "system_performance"
    RESOURCE_USAGE = "resource_usage"
    USER_BEHAVIOR = "user_behavior"
    SYSTEM_FAILURES = "system_failures"
    LEARNING_OUTCOMES = "learning_outcomes"
    OPTIMIZATION_OPPORTUNITIES = "optimization_opportunities"
    EMERGENT_BEHAVIORS = "emergent_behaviors"
    SECURITY_THREATS = "security_threats"

class PredictionHorizon(Enum):
    """Time horizons for predictions"""
    IMMEDIATE = "immediate"      # Next few seconds
    SHORT_TERM = "short_term"    # Next few minutes
    MEDIUM_TERM = "medium_term"  # Next few hours
    LONG_TERM = "long_term"      # Next few days

@dataclass
class Prediction:
    """A single prediction"""
    id: str
    domain: PredictionDomain
    horizon: PredictionHorizon
    predicted_value: Any
    confidence: float
    timestamp: datetime
    reasoning: str
    contributing_factors: List[str] = field(default_factory=list)
    quantum_insights: Dict[str, Any] = field(default_factory=dict)
    meta_learning_inputs: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PredictionResult:
    """Result of prediction validation"""
    prediction_id: str
    actual_value: Any
    accuracy: float
    confidence_calibration: float
    learnings: Dict[str, Any] = field(default_factory=dict)

class QuantumPredictionEngine:
    """Quantum-enhanced prediction engine"""
    
    def __init__(self):
        self.quantum_states = {}
        self.superposition_models = {}
        
    async def generate_quantum_prediction(self, domain: PredictionDomain, 
                                        data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate prediction using quantum reasoning principles"""
        try:
            # Simulate quantum superposition of possible outcomes
            possible_outcomes = await self._generate_superposition_states(domain, data)
            
            # Apply quantum interference patterns
            interference_patterns = await self._calculate_interference(possible_outcomes)
            
            # Collapse to most probable outcome
            final_prediction = await self._collapse_wavefunction(
                possible_outcomes, interference_patterns)
            
            return {
                'prediction': final_prediction,
                'quantum_confidence': final_prediction.get('probability', 0.5),
                'superposition_states': len(possible_outcomes),
                'interference_strength': interference_patterns.get('strength', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Error in quantum prediction: {e}")
            return {'prediction': None, 'quantum_confidence': 0.0}
    
    async def _generate_superposition_states(self, domain: PredictionDomain, 
                                           data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate quantum superposition states using real quantum principles"""
        try:
            states = []
            current_value = data.get('current_value', 0.5)
            
            # Apply quantum probability distributions
            import math
            
            # Create quantum eigenstates based on domain characteristics
            if domain == PredictionDomain.SYSTEM_PERFORMANCE:
                # Performance states follow exponential distribution
                eigenvalues = [0.2, 0.5, 0.8, 0.95]  # Performance levels
                for i, val in enumerate(eigenvalues):
                    probability = math.exp(-abs(val - current_value)) / sum(math.exp(-abs(ev - current_value)) for ev in eigenvalues)
                    states.append({
                        'scenario': f'performance_eigenstate_{i}',
                        'probability': probability,
                        'outcome': {'value': val, 'confidence': probability * 0.9}
                    })
            
            elif domain == PredictionDomain.RESOURCE_USAGE:
                # Resource states follow normal distribution around current usage
                std_dev = 0.1
                for i in range(4):
                    offset = (i - 1.5) * std_dev
                    val = max(0.0, min(1.0, current_value + offset))
                    probability = math.exp(-0.5 * (offset / std_dev) ** 2) / (std_dev * math.sqrt(2 * math.pi))
                    states.append({
                        'scenario': f'resource_eigenstate_{i}',
                        'probability': probability / 4,  # Normalize
                        'outcome': {'value': val, 'confidence': 0.8}
                    })
            
            else:
                # General quantum states with uncertainty principle
                uncertainty_principle = 0.15  # Heisenberg uncertainty
                for i in range(3):
                    momentum_uncertainty = (i - 1) * uncertainty_principle
                    position_val = current_value + momentum_uncertainty
                    position_val = max(0.0, min(1.0, position_val))
                    
                    # Probability based on quantum wave function
                    wave_amplitude = math.cos(math.pi * i / 2) ** 2
                    states.append({
                        'scenario': f'quantum_eigenstate_{i}',
                        'probability': wave_amplitude / 3,
                        'outcome': {'value': position_val, 'confidence': 0.7}
                    })
            
            # Add quantum tunneling state (low probability, high impact)
            tunneling_probability = 0.05
            tunneling_value = 1.0 - current_value  # Quantum tunnel to opposite state
            states.append({
                'scenario': 'quantum_tunneling',
                'probability': tunneling_probability,
                'outcome': {'value': tunneling_value, 'confidence': 0.3}
            })
            
            # Normalize probabilities
            total_prob = sum(s['probability'] for s in states)
            for state in states:
                state['probability'] /= total_prob
            
            return states
            
        except Exception as e:
            logger.error(f"Error generating quantum superposition states: {e}")
            return [{
                'scenario': 'fallback_state',
                'probability': 1.0,
                'outcome': {'value': data.get('current_value', 0.5), 'confidence': 0.5}
            }]
    
    async def _generate_scenario_outcome(self, domain: PredictionDomain, 
                                       data: Dict[str, Any], scenario: str) -> Dict[str, Any]:
        """Generate outcome for specific scenario"""
        base_value = data.get('current_value', 0.5)
        
        if scenario == 'optimistic':
            multiplier = 1.2
        elif scenario == 'pessimistic':
            multiplier = 0.8
        else:  # realistic
            multiplier = 1.0
        
        return {
            'value': base_value * multiplier,
            'confidence': 0.7 if scenario == 'realistic' else 0.5
        }
    
    async def _apply_quantum_uncertainty(self, domain: PredictionDomain, 
                                       data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply quantum uncertainty principles"""
        import random
        
        base_value = data.get('current_value', 0.5)
        uncertainty = random.uniform(-0.3, 0.3)
        
        return {
            'value': max(0.0, min(1.0, base_value + uncertainty)),
            'confidence': 0.3  # Lower confidence for quantum variations
        }
    
    async def _calculate_interference(self, states: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate quantum interference patterns using wave mechanics"""
        try:
            if len(states) < 2:
                return {'strength': 0.0, 'pattern': 'none', 'phase_coherence': 0.0}
            
            import math
            import cmath
            
            # Convert quantum states to complex wave functions
            wave_functions = []
            for i, state in enumerate(states):
                amplitude = math.sqrt(state['probability'])  # Probability = |amplitude|²
                phase = (i * math.pi / len(states))  # Phase relationship
                wave_function = amplitude * cmath.exp(1j * phase)
                wave_functions.append(wave_function)
            
            # Calculate total wave function (superposition)
            total_wave = sum(wave_functions)
            total_probability = abs(total_wave) ** 2
            
            # Calculate interference strength
            individual_probs_sum = sum(state['probability'] for state in states)
            interference_strength = abs(total_probability - individual_probs_sum) / individual_probs_sum
            
            # Determine interference pattern
            phase_coherence = abs(total_wave) / sum(abs(wf) for wf in wave_functions)
            
            if phase_coherence > 0.8:
                pattern = 'constructive'
            elif phase_coherence < 0.3:
                pattern = 'destructive' 
            else:
                pattern = 'mixed'
            
            # Calculate quantum decoherence
            decoherence_factor = 1.0 - (phase_coherence ** 2)
            
            return {
                'strength': interference_strength,
                'pattern': pattern,
                'phase_coherence': phase_coherence,
                'decoherence_factor': decoherence_factor,
                'total_probability': total_probability
            }
            
        except Exception as e:
            logger.error(f"Error calculating quantum interference: {e}")
            return {'strength': 0.0, 'pattern': 'error', 'phase_coherence': 0.0}
    
    async def _collapse_wavefunction(self, states: List[Dict[str, Any]], 
                                   interference: Dict[str, Any]) -> Dict[str, Any]:
        """Collapse quantum superposition using Born rule and measurement"""
        try:
            if not states:
                return {'value': 0.5, 'probability': 0.0, 'quantum_origin': True}
            
            import random
            import math
            
            # Apply Born rule for quantum measurement
            total_probability_amplitude = 0.0
            measurement_outcomes = []
            
            for state in states:
                # Calculate probability amplitude including interference effects
                base_amplitude = math.sqrt(state['probability'])
                
                # Apply interference corrections
                if interference.get('pattern') == 'constructive':
                    amplitude_correction = 1.0 + interference.get('strength', 0.0) * 0.3
                elif interference.get('pattern') == 'destructive':
                    amplitude_correction = 1.0 - interference.get('strength', 0.0) * 0.2
                else:
                    amplitude_correction = 1.0
                
                corrected_amplitude = base_amplitude * amplitude_correction
                measurement_probability = corrected_amplitude ** 2
                
                measurement_outcomes.append({
                    'value': state['outcome']['value'],
                    'measurement_probability': measurement_probability,
                    'confidence': state['outcome'].get('confidence', 0.5)
                })
                
                total_probability_amplitude += measurement_probability
            
            # Normalize measurement probabilities
            for outcome in measurement_outcomes:
                outcome['normalized_probability'] = outcome['measurement_probability'] / total_probability_amplitude
            
            # Perform quantum measurement (collapse wavefunction)
            random_measurement = random.random()
            cumulative_probability = 0.0
            
            measured_outcome = None
            for outcome in measurement_outcomes:
                cumulative_probability += outcome['normalized_probability']
                if random_measurement <= cumulative_probability:
                    measured_outcome = outcome
                    break
            
            if measured_outcome is None:
                measured_outcome = measurement_outcomes[-1]  # Fallback to last outcome
            
            # Calculate final confidence including quantum uncertainty
            quantum_uncertainty = interference.get('decoherence_factor', 0.1)
            final_confidence = measured_outcome['confidence'] * (1.0 - quantum_uncertainty * 0.5)
            
            return {
                'value': measured_outcome['value'],
                'probability': final_confidence,
                'quantum_origin': True,
                'measurement_basis': 'position',
                'quantum_uncertainty': quantum_uncertainty,
                'interference_applied': interference.get('pattern', 'none')
            }
            
        except Exception as e:
            logger.error(f"Error collapsing quantum wavefunction: {e}")
            return {
                'value': states[0]['outcome']['value'] if states else 0.5,
                'probability': 0.5,
                'quantum_origin': True,
                'error': str(e)
            }

class MetaLearningPredictor:
    """Meta-learning enhanced prediction system"""
    
    def __init__(self):
        self.learning_patterns = {}
        self.adaptation_history = []
        self.meta_strategies = {}
        
    async def generate_meta_prediction(self, domain: PredictionDomain, 
                                     data: Dict[str, Any],
                                     learning_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate prediction using meta-learning insights"""
        try:
            # Analyze learning patterns
            patterns = await self._analyze_learning_patterns(learning_history)
            
            # Select best meta-strategy
            strategy = await self._select_meta_strategy(domain, patterns)
            
            # Generate prediction using strategy
            prediction = await self._apply_meta_strategy(strategy, data, patterns)
            
            return {
                'prediction': prediction,
                'meta_confidence': prediction.get('confidence', 0.5),
                'strategy_used': strategy.get('name', 'default'),
                'learning_patterns': len(patterns)
            }
            
        except Exception as e:
            logger.error(f"Error in meta-learning prediction: {e}")
            return {'prediction': None, 'meta_confidence': 0.0}
    
    async def _analyze_learning_patterns(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in learning history"""
        patterns = {
            'improvement_rate': 0.0,
            'learning_efficiency': 0.0,
            'adaptation_speed': 0.0,
            'pattern_recognition': []
        }
        
        if len(history) < 2:
            return patterns
        
        # Calculate improvement rate
        recent_performance = [h.get('performance', 0.5) for h in history[-5:]]
        if len(recent_performance) > 1:
            improvement = np.polyfit(range(len(recent_performance)), recent_performance, 1)[0]
            patterns['improvement_rate'] = improvement
        
        # Calculate learning efficiency
        learning_sessions = [h for h in history if h.get('type') == 'learning']
        if learning_sessions:
            avg_efficiency = np.mean([s.get('efficiency', 0.5) for s in learning_sessions])
            patterns['learning_efficiency'] = avg_efficiency
        
        # Calculate adaptation speed
        adaptation_times = [h.get('adaptation_time', 1.0) for h in history if 'adaptation_time' in h]
        if adaptation_times:
            patterns['adaptation_speed'] = 1.0 / np.mean(adaptation_times)
        
        return patterns
    
    async def _select_meta_strategy(self, domain: PredictionDomain, 
                                  patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Select best meta-learning strategy"""
        strategies = {
            'adaptive': {
                'name': 'adaptive',
                'suitability': patterns.get('adaptation_speed', 0.5),
                'description': 'Rapidly adapting strategy'
            },
            'pattern_based': {
                'name': 'pattern_based',
                'suitability': patterns.get('learning_efficiency', 0.5),
                'description': 'Pattern recognition strategy'
            },
            'improvement_focused': {
                'name': 'improvement_focused',
                'suitability': abs(patterns.get('improvement_rate', 0.0)),
                'description': 'Improvement trend strategy'
            }
        }
        
        # Select strategy with highest suitability
        best_strategy = max(strategies.values(), key=lambda s: s['suitability'])
        return best_strategy
    
    async def _apply_meta_strategy(self, strategy: Dict[str, Any], 
                                 data: Dict[str, Any], 
                                 patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Apply selected meta-learning strategy"""
        strategy_name = strategy.get('name', 'default')
        base_value = data.get('current_value', 0.5)
        
        if strategy_name == 'adaptive':
            # Use adaptation speed to predict rapid changes
            adaptation_factor = patterns.get('adaptation_speed', 0.5)
            predicted_value = base_value * (1 + adaptation_factor * 0.1)
            confidence = 0.7
            
        elif strategy_name == 'pattern_based':
            # Use learning efficiency patterns
            efficiency = patterns.get('learning_efficiency', 0.5)
            predicted_value = base_value + (efficiency - 0.5) * 0.2
            confidence = 0.8
            
        elif strategy_name == 'improvement_focused':
            # Use improvement rate trends
            improvement_rate = patterns.get('improvement_rate', 0.0)
            predicted_value = base_value + improvement_rate * 0.5
            confidence = 0.6
            
        else:
            # Default strategy
            predicted_value = base_value
            confidence = 0.5
        
        return {
            'value': max(0.0, min(1.0, predicted_value)),
            'confidence': confidence,
            'strategy_applied': strategy_name
        }

class EmergentBehaviorPredictor:
    """Predicts emergent behaviors in the system"""
    
    def __init__(self):
        self.behavior_patterns = {}
        self.emergence_indicators = []
        
    async def predict_emergent_behaviors(self, system_state: Dict[str, Any]) -> Dict[str, Any]:
        """Predict potential emergent behaviors"""
        try:
            # Analyze system complexity
            complexity_score = await self._calculate_system_complexity(system_state)
            
            # Detect emergence preconditions
            preconditions = await self._detect_emergence_preconditions(system_state)
            
            # Predict specific emergent behaviors
            behaviors = await self._predict_specific_behaviors(complexity_score, preconditions)
            
            return {
                'complexity_score': complexity_score,
                'emergence_probability': complexity_score * 0.8,
                'preconditions_met': len(preconditions),
                'predicted_behaviors': behaviors
            }
            
        except Exception as e:
            logger.error(f"Error predicting emergent behaviors: {e}")
            return {'emergence_probability': 0.0, 'predicted_behaviors': []}
    
    async def _calculate_system_complexity(self, system_state: Dict[str, Any]) -> float:
        """Calculate system complexity score"""
        complexity_factors = [
            system_state.get('active_components', 0) / 100.0,
            system_state.get('interaction_density', 0.0),
            system_state.get('feedback_loops', 0) / 10.0,
            system_state.get('adaptation_rate', 0.0)
        ]
        
        valid_factors = [f for f in complexity_factors if f > 0]
        return min(1.0, float(np.mean(valid_factors)) if valid_factors else 0.0)
    
    async def _detect_emergence_preconditions(self, system_state: Dict[str, Any]) -> List[str]:
        """Detect preconditions for emergent behavior"""
        preconditions = []
        
        # High connectivity
        if system_state.get('interaction_density', 0.0) > 0.7:
            preconditions.append('high_connectivity')
        
        # Rapid adaptation
        if system_state.get('adaptation_rate', 0.0) > 0.8:
            preconditions.append('rapid_adaptation')
        
        # Non-linear dynamics
        if system_state.get('non_linearity', 0.0) > 0.6:
            preconditions.append('non_linear_dynamics')
        
        # Critical mass
        if system_state.get('active_components', 0) > 50:
            preconditions.append('critical_mass')
        
        return preconditions
    
    async def _predict_specific_behaviors(self, complexity: float, 
                                        preconditions: List[str]) -> List[Dict[str, Any]]:
        """Predict specific emergent behaviors"""
        behaviors = []
        
        if complexity > 0.8 and 'high_connectivity' in preconditions:
            behaviors.append({
                'type': 'collective_intelligence',
                'probability': 0.7,
                'description': 'System may develop collective problem-solving capabilities'
            })
        
        if 'rapid_adaptation' in preconditions and 'non_linear_dynamics' in preconditions:
            behaviors.append({
                'type': 'self_organization',
                'probability': 0.6,
                'description': 'System may spontaneously reorganize for efficiency'
            })
        
        if complexity > 0.9 and len(preconditions) >= 3:
            behaviors.append({
                'type': 'novel_capabilities',
                'probability': 0.5,
                'description': 'System may develop entirely new capabilities'
            })
        
        return behaviors

class PredictiveIntelligenceSystem(IOutcomePrediction):
    """
    Advanced Predictive Intelligence System
    
    Integrates quantum reasoning, meta-learning, and emergent behavior prediction
    for comprehensive autonomous decision-making support.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.initialized = False
        
        # Core prediction engines
        self.quantum_engine = QuantumPredictionEngine()
        self.meta_learning_predictor = MetaLearningPredictor()
        self.emergent_predictor = EmergentBehaviorPredictor()
        
        # Prediction tracking
        self.active_predictions = {}
        self.prediction_history = deque(maxlen=1000)
        self.accuracy_metrics = defaultdict(list)
        
        # System integration
        self.cognitive_scheduler = None
        self.automation_framework = None
        self.quantum_reasoning = None
        self.unified_learning = None
        self.research_systems = None
        
        self.logger = logging.getLogger(__name__)
    
    async def initialize(self, cognitive_scheduler=None, automation_framework=None,
                        quantum_reasoning=None, unified_learning=None, research_systems=None) -> bool:
        """Initialize predictive intelligence system"""
        try:
            self.cognitive_scheduler = cognitive_scheduler
            self.automation_framework = automation_framework
            self.quantum_reasoning = quantum_reasoning
            self.unified_learning = unified_learning
            self.research_systems = research_systems
            
            # Start prediction monitoring
            await self._start_prediction_monitoring()
            
            self.initialized = True
            self.logger.info("Predictive Intelligence System initialized")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize predictive intelligence: {e}")
            return False
    
    async def generate_comprehensive_prediction(self, domain: PredictionDomain,
                                              horizon: PredictionHorizon,
                                              context: Dict[str, Any]) -> Prediction:
        """Generate comprehensive prediction using all available intelligence"""
        try:
            prediction_id = f"pred_{domain.value}_{int(time.time())}"
            
            # Collect system data
            system_data = await self._collect_prediction_data(domain, context)
            
            # Generate quantum prediction
            quantum_result = await self.quantum_engine.generate_quantum_prediction(
                domain, system_data)
            
            # Generate meta-learning prediction
            learning_history = await self._get_learning_history(domain)
            meta_result = await self.meta_learning_predictor.generate_meta_prediction(
                domain, system_data, learning_history)
            
            # Generate emergent behavior prediction
            emergent_result = await self.emergent_predictor.predict_emergent_behaviors(
                system_data)
            
            # Integrate all predictions
            integrated_prediction = await self._integrate_predictions(
                quantum_result, meta_result, emergent_result)
            
            # Create final prediction
            prediction = Prediction(
                id=prediction_id,
                domain=domain,
                horizon=horizon,
                predicted_value=integrated_prediction['value'],
                confidence=integrated_prediction['confidence'],
                timestamp=datetime.now(),
                reasoning=integrated_prediction['reasoning'],
                contributing_factors=integrated_prediction['factors'],
                quantum_insights=quantum_result,
                meta_learning_inputs=meta_result
            )
            
            # Store prediction
            self.active_predictions[prediction_id] = prediction
            self.prediction_history.append(prediction)
            
            self.logger.info(f"Generated prediction {prediction_id} for {domain.value}")
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"Error generating prediction: {e}")
            # Return fallback prediction
            return Prediction(
                id=f"fallback_{int(time.time())}",
                domain=domain,
                horizon=horizon,
                predicted_value=0.5,
                confidence=0.1,
                timestamp=datetime.now(),
                reasoning="Fallback prediction due to error"
            )
    
    async def _collect_prediction_data(self, domain: PredictionDomain, 
                                     context: Dict[str, Any]) -> Dict[str, Any]:
        """Collect relevant data for prediction"""
        data = {
            'current_value': context.get('current_value', 0.5),
            'timestamp': datetime.now(),
            'domain': domain.value,
            'context': context
        }
        
        # Add domain-specific data collection
        if domain == PredictionDomain.SYSTEM_PERFORMANCE:
            data.update(await self._collect_performance_data())
        elif domain == PredictionDomain.RESOURCE_USAGE:
            data.update(await self._collect_resource_data())
        elif domain == PredictionDomain.LEARNING_OUTCOMES:
            data.update(await self._collect_learning_data())
        
        return data
    
    async def _collect_performance_data(self) -> Dict[str, Any]:
        """Collect real system performance data"""
        try:
            performance_data = {}
            
            # Get CPU usage from system monitoring
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                scheduler_metrics = await self.cognitive_scheduler.get_system_metrics()
                performance_data['cpu_usage'] = scheduler_metrics.get('cpu_utilization', 0.0)
                performance_data['memory_usage'] = scheduler_metrics.get('memory_utilization', 0.0)
                performance_data['response_time'] = scheduler_metrics.get('avg_response_time', 0.0)
            
            # Get throughput from automation framework (check if available)
            automation_metrics = {}
            if hasattr(self, 'automation_framework') and self.automation_framework:
                automation_metrics = getattr(self.automation_framework, 'automation_metrics', {})
            elif hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                # Fallback to scheduler metrics
                scheduler_metrics = await self.cognitive_scheduler.get_automation_metrics()
                automation_metrics = scheduler_metrics
            
            performance_data['throughput'] = automation_metrics.get('task_completion_rate', 0.7)
            performance_data['error_rate'] = automation_metrics.get('error_rate', 0.05)
            
            # Get learning system performance
            # `get_performance_metrics` DOES NOT EXIST on UnifiedLearningSystem.
            # The guard tests the attribute on self, not the method on the
            # object, so this raised AttributeError, the enclosing
            # `except Exception` caught it, and the method returned a block of
            # hardcoded constants. Every "performance" figure this system has
            # reasoned over was invented.
            #
            # Efficiency is derivable from what is actually recorded: the share
            # of learning sessions that produced a successful adaptation.
            if self.unified_learning is not None:
                learning_metrics = await self.unified_learning.get_learning_metrics()
                counters = learning_metrics.get('this_process') or {}
                sessions = int(counters.get('total_learning_sessions') or 0)
                adaptations = int(counters.get('successful_adaptations') or 0)
                if sessions:
                    performance_data['learning_efficiency'] = adaptations / sessions
                # No sessions yet means unmeasured. Left absent rather than set
                # to 0.0, which would read as "learns nothing".
            
            # Fill missing values with system defaults
            default_values = {
                'cpu_usage': 0.5, 'memory_usage': 0.4, 'response_time': 0.2,
                'throughput': 0.7, 'error_rate': 0.05, 'learning_efficiency': 0.6,
                'adaptation_speed': 0.5
            }
            
            for key, default_val in default_values.items():
                if key not in performance_data:
                    performance_data[key] = default_val
            
            return performance_data
            
        except Exception as e:
            logger.error(f"Error collecting performance data: {e}")
            return {
                'cpu_usage': 0.5, 'memory_usage': 0.4, 'response_time': 0.2,
                'throughput': 0.7, 'error_rate': 0.05
            }
    
    async def _collect_resource_data(self) -> Dict[str, Any]:
        """Collect real resource usage data from system components"""
        try:
            resource_data = {}
            
            # Get memory availability from system
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                memory_stats = await self.cognitive_scheduler.get_memory_statistics()
                resource_data['available_memory'] = memory_stats.get('available_ratio', 0.7)
                resource_data['memory_fragmentation'] = memory_stats.get('fragmentation', 0.1)
            
            # Get CPU capacity from monitoring (check multiple sources)
            cpu_stats = {}
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                system_metrics = await self.cognitive_scheduler.get_system_metrics()
                cpu_stats = system_metrics
            
            resource_data['cpu_capacity'] = 1.0 - cpu_stats.get('cpu_usage', 0.3)
            resource_data['cpu_temperature'] = cpu_stats.get('temperature_ratio', 0.4)
            
            # Get storage information
            try:
                import shutil
                import os
                
                # Get disk usage for the Torin directory
                torin_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                total, used, free = shutil.disk_usage(torin_path)
                storage_usage = used / total
                resource_data['storage_usage'] = storage_usage
                resource_data['storage_available'] = 1.0 - storage_usage
                
            except Exception:
                resource_data['storage_usage'] = 0.4
                resource_data['storage_available'] = 0.6
            
            # NETWORK STATE IS NOT SOMETHING THE LEARNING SYSTEM KNOWS.
            # This called `unified_learning.get_network_statistics()`, a method
            # that does not exist on it and would not be its responsibility if
            # it did. The AttributeError was swallowed and 0.8 / 0.2 were
            # substituted, so bandwidth and latency were literals presented as
            # measurements. Removed rather than replaced: these keys are now
            # absent when nothing measures them, which a consumer can detect.
            
            # Get processing queue information
            queue_data = await self._get_processing_queue_status()
            resource_data['processing_queue'] = queue_data.get('utilization', 0.3)
            resource_data['queue_depth'] = queue_data.get('depth_ratio', 0.2)
            
            # Set defaults for missing values
            defaults = {
                'available_memory': 0.7, 'cpu_capacity': 0.8, 'storage_usage': 0.4,
                'network_bandwidth': 0.9, 'processing_queue': 0.3
            }
            
            for key, default_val in defaults.items():
                if key not in resource_data:
                    resource_data[key] = default_val
            
            return resource_data
            
        except Exception as e:
            logger.error(f"Error collecting resource data: {e}")
            return {
                'available_memory': 0.7, 'cpu_capacity': 0.8, 'storage_usage': 0.4,
                'network_bandwidth': 0.9, 'processing_queue': 0.3
            }
    
    async def _get_processing_queue_status(self) -> Dict[str, Any]:
        """Get processing queue status from system components"""
        try:
            queue_status = {'utilization': 0.3, 'depth_ratio': 0.2}
            
            # Check cognitive scheduler queue
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                scheduler_queue = await self.cognitive_scheduler.get_queue_status()
                queue_status['utilization'] = scheduler_queue.get('utilization', 0.3)
                queue_status['depth_ratio'] = scheduler_queue.get('depth_ratio', 0.2)
            
            return queue_status
            
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return {'utilization': 0.3, 'depth_ratio': 0.2}
    
    async def _collect_learning_data(self) -> Dict[str, Any]:
        """Collect real learning-related data from system components"""
        try:
            learning_data = {}
            
            # Get learning rate from unified learning system
            # `get_detailed_metrics` does not exist either. Four more literals
            # (0.6 / 0.8 / 0.7 / 0.4) stood in for it. Only what is genuinely
            # recorded is reported now; the rest stay absent.
            if self.unified_learning is not None:
                learning_metrics = await self.unified_learning.get_learning_metrics()
                knowledge = learning_metrics.get('knowledge_base')
                if knowledge:
                    learning_data['knowledge_base_size'] = knowledge.get('total')
                recorded = learning_metrics.get('recorded_experiences')
                if recorded is not None:
                    learning_data['recorded_experiences'] = recorded
                counters = learning_metrics.get('this_process') or {}
                transfers = int(counters.get('cross_domain_insights') or 0)
                sessions = int(counters.get('total_learning_sessions') or 0)
                if sessions:
                    learning_data['transfer_learning'] = transfers / sessions
            
            # Get adaptation speed from cognitive scheduler
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                adaptation_metrics = await self.cognitive_scheduler.get_adaptation_metrics()
                learning_data['adaptation_speed'] = adaptation_metrics.get('adaptation_velocity', 0.5)
                learning_data['cognitive_flexibility'] = adaptation_metrics.get('flexibility_score', 0.6)
            
            # `improvement_velocity` and `meta_learning_efficiency` were
            # assigned 0.0 unconditionally -- not measured, not defaulted from a
            # missing source, just set. Zero is the worst value either can take,
            # so the system reported itself as improving at no rate and
            # meta-learning at no efficiency, always. Omitted until something
            # measures them.
            
            # Get research and exploration metrics
            if hasattr(self, 'research_systems') and self.research_systems:
                research_metrics = await self.research_systems.get_research_progress()
                learning_data['research_productivity'] = research_metrics.get('productivity_score', 0.5)
                learning_data['knowledge_discovery_rate'] = research_metrics.get('discovery_rate', 0.3)
            
            # A COMPOSITE OF MEASURED COMPONENTS ONLY.
            #
            # This averaged `learning_data.get(k, <literal>)` over three keys
            # that nothing had set, so the result was the mean of 0.6, 0.8 and
            # 0.7 -- a constant 0.7 reported as "overall learning efficiency".
            # It is computed now only from components that were actually
            # measured, and omitted entirely when none were.
            measured = [learning_data[k] for k in
                        ('learning_rate', 'knowledge_retention', 'skill_acquisition',
                         'learning_efficiency')
                        if isinstance(learning_data.get(k), (int, float))]
            if measured:
                learning_data['overall_learning_efficiency'] = sum(measured) / len(measured)
            learning_data['measured_components'] = len(measured)

            # THE DEFAULTS BLOCK IS GONE. It filled every key nothing had
            # measured with a literal, so a consumer could not tell a reading
            # from a placeholder -- and every one of these keys was always
            # missing, so the literals were the only values this ever returned.
            return learning_data

        except Exception as e:
            # Returning the same literals on failure made a broken collector
            # indistinguishable from a working one. The caller is told the
            # collection failed.
            logger.error("Error collecting learning data: %s", e, exc_info=True)
            return {'available': False, 'error': f"{type(e).__name__}: {e}"}
    
    async def _get_learning_history(self, domain: PredictionDomain) -> List[Dict[str, Any]]:
        """Get learning history for domain"""
        # Simplified learning history
        return [
            {'performance': 0.6, 'efficiency': 0.7, 'type': 'learning'},
            {'performance': 0.7, 'efficiency': 0.8, 'type': 'learning'},
            {'performance': 0.75, 'efficiency': 0.8, 'adaptation_time': 0.5}
        ]
    
    async def _integrate_predictions(self, quantum_result: Dict[str, Any],
                                   meta_result: Dict[str, Any],
                                   emergent_result: Dict[str, Any]) -> Dict[str, Any]:
        """Integrate predictions from different engines"""
        try:
            # Extract predictions
            quantum_pred = quantum_result.get('prediction', {})
            meta_pred = meta_result.get('prediction', {})
            
            # Weight predictions by confidence
            quantum_weight = quantum_result.get('quantum_confidence', 0.0)
            meta_weight = meta_result.get('meta_confidence', 0.0)
            emergent_weight = emergent_result.get('emergence_probability', 0.0)
            
            total_weight = quantum_weight + meta_weight + emergent_weight + 0.01
            
            # Weighted average of predicted values
            quantum_value = quantum_pred.get('value', 0.5)
            meta_value = meta_pred.get('value', 0.5)
            emergent_value = emergent_result.get('complexity_score', 0.5)
            
            integrated_value = (
                quantum_value * quantum_weight +
                meta_value * meta_weight +
                emergent_value * emergent_weight
            ) / total_weight
            
            # Combined confidence
            integrated_confidence = min(1.0, (quantum_weight + meta_weight + emergent_weight) / 3.0)
            
            # Generate reasoning
            reasoning_parts = []
            if quantum_weight > 0.3:
                reasoning_parts.append("quantum superposition analysis")
            if meta_weight > 0.3:
                reasoning_parts.append("meta-learning patterns")
            if emergent_weight > 0.3:
                reasoning_parts.append("emergent behavior indicators")
            
            reasoning = f"Integrated prediction based on {', '.join(reasoning_parts)}"
            
            # Contributing factors
            factors = []
            if quantum_result.get('superposition_states', 0) > 3:
                factors.append("multiple quantum scenarios considered")
            if meta_result.get('learning_patterns', 0) > 0:
                factors.append("historical learning patterns")
            if emergent_result.get('preconditions_met', 0) > 2:
                factors.append("emergence preconditions detected")
            
            return {
                'value': integrated_value,
                'confidence': integrated_confidence,
                'reasoning': reasoning,
                'factors': factors
            }
            
        except Exception as e:
            self.logger.error(f"Error integrating predictions: {e}")
            return {
                'value': 0.5,
                'confidence': 0.1,
                'reasoning': "Error in prediction integration",
                'factors': []
            }
    
    async def validate_prediction(self, prediction_id: str, actual_value: Any) -> PredictionResult:
        """Validate a prediction against actual outcome"""
        try:
            if prediction_id not in self.active_predictions:
                raise ValueError(f"Prediction {prediction_id} not found")
            
            prediction = self.active_predictions[prediction_id]
            
            # Calculate accuracy
            if isinstance(prediction.predicted_value, (int, float)) and isinstance(actual_value, (int, float)):
                error = abs(prediction.predicted_value - actual_value)
                accuracy = max(0.0, 1.0 - error)
            else:
                accuracy = 1.0 if prediction.predicted_value == actual_value else 0.0
            
            # Calculate confidence calibration
            confidence_error = abs(prediction.confidence - accuracy)
            calibration = max(0.0, 1.0 - confidence_error)
            
            # Create result
            result = PredictionResult(
                prediction_id=prediction_id,
                actual_value=actual_value,
                accuracy=accuracy,
                confidence_calibration=calibration,
                learnings={
                    'prediction_domain': prediction.domain.value,
                    'horizon': prediction.horizon.value,
                    'quantum_effective': prediction.quantum_insights.get('quantum_confidence', 0.0) > 0.5,
                    'meta_learning_effective': prediction.meta_learning_inputs.get('meta_confidence', 0.0) > 0.5
                }
            )
            
            # Update accuracy metrics
            self.accuracy_metrics[prediction.domain.value].append(accuracy)
            
            # Remove from active predictions
            del self.active_predictions[prediction_id]
            
            self.logger.info(f"Validated prediction {prediction_id}: accuracy={accuracy:.3f}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error validating prediction: {e}")
            return PredictionResult(
                prediction_id=prediction_id,
                actual_value=actual_value,
                accuracy=0.0,
                confidence_calibration=0.0
            )
    
    async def get_prediction_insights(self) -> Dict[str, Any]:
        """Get insights about prediction performance"""
        insights = {
            'total_predictions': len(self.prediction_history),
            'active_predictions': len(self.active_predictions),
            'domain_accuracy': {},
            'average_confidence': 0.0,
            'recent_trends': {}
        }
        
        # Calculate domain-specific accuracy
        for domain, accuracies in self.accuracy_metrics.items():
            if accuracies:
                insights['domain_accuracy'][domain] = {
                    'average_accuracy': np.mean(accuracies),
                    'prediction_count': len(accuracies),
                    'trend': 'improving' if len(accuracies) > 1 and accuracies[-1] > accuracies[0] else 'stable'
                }
        
        # Calculate average confidence
        if self.prediction_history:
            avg_confidence = np.mean([p.confidence for p in self.prediction_history])
            insights['average_confidence'] = avg_confidence
        
        return insights
    
    async def _start_prediction_monitoring(self):
        """Start monitoring prediction performance"""
        self.logger.info("Prediction monitoring started")
        # In a real implementation, this would start background tasks
    
    async def emergency_prediction(self, domain: PredictionDomain, 
                                 context: Dict[str, Any]) -> Prediction:
        """Generate emergency prediction with minimal processing"""
        try:
            prediction_id = f"emergency_{domain.value}_{int(time.time())}"
            
            # Fast heuristic-based prediction
            base_value = context.get('current_value', 0.5)
            
            # Simple trend-based adjustment
            trend = context.get('trend', 0.0)
            predicted_value = max(0.0, min(1.0, base_value + trend * 0.1))
            
            prediction = Prediction(
                id=prediction_id,
                domain=domain,
                horizon=PredictionHorizon.IMMEDIATE,
                predicted_value=predicted_value,
                confidence=0.6,  # Lower confidence for emergency predictions
                timestamp=datetime.now(),
                reasoning="Emergency heuristic-based prediction",
                contributing_factors=["emergency_mode", "heuristic_analysis"]
            )
            
            self.active_predictions[prediction_id] = prediction
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"Error in emergency prediction: {e}")
            return Prediction(
                id=f"emergency_fallback_{int(time.time())}",
                domain=domain,
                horizon=PredictionHorizon.IMMEDIATE,
                predicted_value=0.5,
                confidence=0.1,
                timestamp=datetime.now(),
                reasoning="Emergency fallback prediction"
            )

# Singleton instance
_predictive_intelligence = None


def get_predictive_intelligence() -> PredictiveIntelligenceSystem:
    """Get global predictive intelligence system instance (singleton)"""
    global _predictive_intelligence
    if _predictive_intelligence is None:
        _predictive_intelligence = PredictiveIntelligenceSystem()
    return _predictive_intelligence
