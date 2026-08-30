#!/usr/bin/env python3
"""
TorinAI Intelligence Module
Predictive intelligence and advanced cognitive systems.
"""

from .predictive_intelligence_system import (
    PredictiveIntelligenceSystem,
    PredictionDomain,
    PredictionHorizon,
    Prediction
)

# Singleton instance
_predictive_intelligence = None

async def get_predictive_intelligence() -> PredictiveIntelligenceSystem:
    """Get global predictive intelligence system instance (singleton)"""
    global _predictive_intelligence
    if _predictive_intelligence is None:
        _predictive_intelligence = PredictiveIntelligenceSystem()
        await _predictive_intelligence.initialize()
    return _predictive_intelligence

async def initialize_predictive_intelligence(**kwargs) -> PredictiveIntelligenceSystem:
    """Initialize predictive intelligence system (main entry point for main.py)"""
    global _predictive_intelligence
    if _predictive_intelligence is None:
        _predictive_intelligence = PredictiveIntelligenceSystem(kwargs.get('config'))
        await _predictive_intelligence.initialize(
            cognitive_scheduler=kwargs.get('cognitive_scheduler'),
            automation_framework=kwargs.get('automation_framework'),
            quantum_reasoning=kwargs.get('quantum_reasoning'),
            unified_learning=kwargs.get('unified_learning'),
            research_systems=kwargs.get('research_systems')
        )
    return _predictive_intelligence

__all__ = [
    'PredictiveIntelligenceSystem',
    'PredictionDomain',
    'PredictionHorizon',
    'Prediction',
    'get_predictive_intelligence',
    'initialize_predictive_intelligence'
]