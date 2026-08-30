#!/usr/bin/env python3
"""
TorinAI Chaos Engineering Framework
====================================

Production-grade chaos testing framework for discovering resilience gaps
before they become production incidents.

Core Components:
- ChaosOrchestrator: Main controller for experiment lifecycle
- ChaosInjectionEngine: Fault injection via decorators and proxies
- ChaosSafetyController: Production safety guardrails
- ChaosObservability: Metrics collection and hypothesis validation

Target Systems:
- Learning System
- Security System
- Reasoning System
- Autonomous Agents
- Domain Knowledge
- Memory Systems
- Tool Execution

Author: Torin AI Team
"""

from .types import (
    ChaosExperiment,
    ExperimentStatus,
    ChaosType,
    ExperimentResult,
    MetricsSnapshot,
    ChaosEvent,
    Hypothesis,
    SLOThresholds,
    PreFlightCheck,
    PreFlightResult,
    CircuitState,
    RolloutStage,
)

__all__ = [
    "ChaosExperiment",
    "ExperimentStatus",
    "ChaosType",
    "ExperimentResult",
    "MetricsSnapshot",
    "ChaosEvent",
    "Hypothesis",
    "SLOThresholds",
    "PreFlightCheck",
    "PreFlightResult",
    "CircuitState",
    "RolloutStage",
]

__version__ = "1.0.0"
