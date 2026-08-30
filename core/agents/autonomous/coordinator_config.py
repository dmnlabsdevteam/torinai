#!/usr/bin/env python3
"""
Autonomous Coordinator Configuration
Centralizes all magic numbers and thresholds for easy tuning
"""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class CoordinatorConfig:
    """Configuration for AutonomousCoordinator with all tunable parameters"""

    # Coordination cycles
    cycle_interval: float = 5.0  # seconds between coordination cycles

    # Monitoring
    monitoring_check_interval: int = 60  # seconds between health checks
    health_event_queue_size: int = 100  # max events to keep in health queue
    automation_proposal_queue_size: int = 50  # max proposals to queue

    # Goals and motivation
    max_concurrent_goals: int = 1  # singleton: one goal at a time (sub-agents handle parallelism within executor)
    intrinsic_motivation_weight: float = 0.5  # weight for intrinsic motivation (0-1)
    min_active_goals: int = 3  # minimum active goals before generating new ones
    idle_cycles_before_new_goals: int = 2  # cycles to wait before generating goals
    min_new_goals_per_generation: int = 2  # minimum new goals to generate

    # Performance assessment
    assessment_interval_hours: float = 6.0  # hours between performance assessments
    performance_threshold: float = 0.7  # minimum acceptable performance (0-1)
    min_feedback_samples: int = 10  # minimum feedback samples for assessment

    # Task execution
    default_task_interval: int = 3600  # seconds between recurring task executions
    max_goals_curiosity: int = 3  # max curiosity-driven goals to generate

    # Memory retrieval
    memory_max_results: int = 10  # default max memories to retrieve
    memory_min_quality: float = 0.7  # minimum quality score for memories (0-1)
    memory_context_window_minutes: int = 5  # minutes for recent memory context

    # LLM generation
    llm_max_tokens_short: int = 200  # tokens for short responses
    llm_max_tokens_medium: int = 512  # tokens for medium responses
    llm_max_tokens_long: int = 1024  # tokens for long responses

    # Memory consolidation guards (Tier 5)
    llm_consolidation_max_tokens: int = 512  # max tokens per consolidation cycle
    llm_consolidation_timeout_s: float = 30.0  # abort if exceeds timeout
    memory_consolidation_max_items: int = 50  # max memory items to scan per cycle

    # Circuit breaker (for external modules)
    circuit_failure_threshold: int = 5  # failures before opening circuit
    circuit_success_threshold: int = 2  # successes in half_open before closing
    circuit_timeout_seconds: float = 60.0  # seconds before trying half_open
    circuit_half_open_timeout: float = 30.0  # seconds to test in half_open

    # Parallel execution
    max_parallel_tasks: int = 1  # singleton: one task at a time (sub-agents handle parallelism within executor)
    task_execution_timeout: float = 300.0  # seconds before task timeout

    # System limits
    min_cycle_interval: float = 1.0  # minimum coordination cycle interval
    max_cycle_interval: float = 3600.0  # maximum coordination cycle interval

    # Resource thresholds
    cpu_threshold_percent: float = 90.0  # CPU usage threshold for throttling
    memory_threshold_percent: float = 85.0  # Memory usage threshold for throttling

    # Competence thresholds
    expected_competence_gain: float = 0.6  # expected improvement from learning
    information_gain_weight: float = 0.3  # weight for information gain
    question_complexity_weight: float = 0.7  # weight for question complexity

    # Weights for intrinsic reward calculation
    novelty_weight: float = 0.5
    uncertainty_weight: float = 0.3
    competence_weight: float = 0.2

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization"""
        return {
            "cycle_interval": self.cycle_interval,
            "monitoring_check_interval": self.monitoring_check_interval,
            "health_event_queue_size": self.health_event_queue_size,
            "automation_proposal_queue_size": self.automation_proposal_queue_size,
            "max_concurrent_goals": self.max_concurrent_goals,
            "intrinsic_motivation_weight": self.intrinsic_motivation_weight,
            "min_active_goals": self.min_active_goals,
            "idle_cycles_before_new_goals": self.idle_cycles_before_new_goals,
            "min_new_goals_per_generation": self.min_new_goals_per_generation,
            "assessment_interval_hours": self.assessment_interval_hours,
            "performance_threshold": self.performance_threshold,
            "min_feedback_samples": self.min_feedback_samples,
            "default_task_interval": self.default_task_interval,
            "max_goals_curiosity": self.max_goals_curiosity,
            "memory_max_results": self.memory_max_results,
            "memory_min_quality": self.memory_min_quality,
            "memory_context_window_minutes": self.memory_context_window_minutes,
            "llm_max_tokens_short": self.llm_max_tokens_short,
            "llm_max_tokens_medium": self.llm_max_tokens_medium,
            "llm_max_tokens_long": self.llm_max_tokens_long,
            "llm_consolidation_max_tokens": self.llm_consolidation_max_tokens,
            "llm_consolidation_timeout_s": self.llm_consolidation_timeout_s,
            "memory_consolidation_max_items": self.memory_consolidation_max_items,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_success_threshold": self.circuit_success_threshold,
            "circuit_timeout_seconds": self.circuit_timeout_seconds,
            "circuit_half_open_timeout": self.circuit_half_open_timeout,
            "max_parallel_tasks": self.max_parallel_tasks,
            "task_execution_timeout": self.task_execution_timeout,
            "min_cycle_interval": self.min_cycle_interval,
            "max_cycle_interval": self.max_cycle_interval,
            "cpu_threshold_percent": self.cpu_threshold_percent,
            "memory_threshold_percent": self.memory_threshold_percent,
            "expected_competence_gain": self.expected_competence_gain,
            "information_gain_weight": self.information_gain_weight,
            "question_complexity_weight": self.question_complexity_weight,
            "novelty_weight": self.novelty_weight,
            "uncertainty_weight": self.uncertainty_weight,
            "competence_weight": self.competence_weight,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CoordinatorConfig':
        """Create config from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def get_default_config() -> CoordinatorConfig:
    """Get default coordinator configuration"""
    return CoordinatorConfig()
