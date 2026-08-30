#!/usr/bin/env python3
"""
Chaos Scenario Library
======================

Comprehensive library of chaos scenarios for all 7 target systems.
Each scenario is a template that can be instantiated with experiment_manager.
"""

from typing import Dict, List
from ..types import ChaosType

# Tool System Scenarios (3 scenarios)
TOOL_SCENARIOS = {
    "tool_registry_latency": {
        "name": "Tool Registry Latency Spike",
        "description": "Test system resilience when tool registry lookups are slow",
        "target_system": "tool_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "tool_registry",
        "injection_point": "get_tool",
        "injection_config": {
            "delay_ms": 500,
            "jitter_ms": 100,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Tool registry latency should not impact overall system performance beyond SLO limits",
            "expected_behavior": {
                "max_latency_p95_ms": 700,  # 500ms delay + 200ms baseline
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 10,
        "environment": "staging"
    },

    "database_connection_failure": {
        "name": "Database Tool Connection Failures",
        "description": "Test handling of database connection failures in database tools",
        "target_system": "tool_system",
        "chaos_type": ChaosType.ERROR,
        "component": "database_tools",
        "injection_point": "get_connection",
        "injection_config": {
            "error_type": "ConnectionError",
            "error_rate": 0.2,  # 20% failure rate
            "duration_seconds": 180
        },
        "hypothesis": {
            "hypothesis_statement": "Database connection failures should be handled gracefully with retries",
            "expected_behavior": {
                "max_latency_p95_ms": 500,
                "max_error_rate": 0.02  # Some failures acceptable with retries
            }
        },
        "blast_radius": 5,
        "environment": "staging"
    },

    "api_rate_limiting": {
        "name": "External API Rate Limiting",
        "description": "Test resilience when external APIs (OpenAI, etc.) are rate limited",
        "target_system": "tool_system",
        "chaos_type": ChaosType.RATE_LIMIT,
        "component": "ai_ml_tools",
        "injection_point": "openai_request",
        "injection_config": {
            "error_type": "RateLimitError",
            "error_rate": 0.3,  # 30% rate limited
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "Rate limiting should trigger backoff and not cascade to failures",
            "expected_behavior": {
                "max_latency_p95_ms": 1000,  # Higher latency due to backoff
                "max_error_rate": 0.05
            }
        },
        "blast_radius": 15,
        "environment": "staging"
    }
}

# Learning System Scenarios (3 scenarios)
LEARNING_SCENARIOS = {
    "training_pipeline_latency": {
        "name": "Training Pipeline Data Loading Latency",
        "description": "Test continuous learning pipeline with slow data loading",
        "target_system": "learning_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "continuous_learning_pipeline",
        "injection_point": "data_loading",
        "injection_config": {
            "delay_ms": 1000,
            "jitter_ms": 200,
            "duration_seconds": 600
        },
        "hypothesis": {
            "hypothesis_statement": "Training pipeline should handle slow data loading without OOM",
            "expected_behavior": {
                "max_latency_p95_ms": 1200,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 20,
        "environment": "dev"
    },

    "model_checkpoint_save_failure": {
        "name": "Model Checkpoint Save Failures",
        "description": "Test handling of checkpoint save failures during training",
        "target_system": "learning_system",
        "chaos_type": ChaosType.ERROR,
        "component": "safe_upgrade_deployer",
        "injection_point": "save_checkpoint",
        "injection_config": {
            "error_type": "IOError",
            "error_rate": 0.15,  # 15% failure rate
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Checkpoint failures should not halt training, retry mechanism should work",
            "expected_behavior": {
                "max_latency_p95_ms": 500,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 10,
        "environment": "dev"
    },

    "pattern_learner_memory_exhaustion": {
        "name": "Pattern Learner Memory Exhaustion",
        "description": "Test governance pattern learner under memory pressure",
        "target_system": "learning_system",
        "chaos_type": ChaosType.RESOURCE_EXHAUSTION,
        "component": "governance_pattern_learner",
        "injection_point": "extract_patterns",
        "injection_config": {
            "resource_type": "memory",
            "limit_value": 0.9,  # 90% memory utilization
            "duration_seconds": 180
        },
        "hypothesis": {
            "hypothesis_statement": "Memory pressure should trigger graceful degradation, not crashes",
            "expected_behavior": {
                "max_latency_p95_ms": 800,
                "max_error_rate": 0.05
            }
        },
        "blast_radius": 5,
        "environment": "dev"
    }
}

# Security System Scenarios (3 scenarios)
SECURITY_SCENARIOS = {
    "waf_latency_spike": {
        "name": "Cloudflare WAF Latency Spike",
        "description": "Test system performance when WAF checks are slow",
        "target_system": "security_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "cloudflare_waf",
        "injection_point": "check_request",
        "injection_config": {
            "delay_ms": 300,
            "jitter_ms": 50,
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "WAF latency should not block legitimate requests",
            "expected_behavior": {
                "max_latency_p95_ms": 400,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 30,  # Higher blast radius for critical security
        "environment": "staging"
    },

    "malware_sandbox_crash": {
        "name": "Malware Sandbox Crash",
        "description": "Test handling of sandbox crashes during malware analysis",
        "target_system": "security_system",
        "chaos_type": ChaosType.ERROR,
        "component": "malware_sandbox",
        "injection_point": "analyze",
        "injection_config": {
            "error_type": "SandboxCrashError",
            "error_rate": 0.1,  # 10% crash rate
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Sandbox crashes should not prevent threat detection, fallback should work",
            "expected_behavior": {
                "max_latency_p95_ms": 600,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 10,
        "environment": "dev"
    },

    "threat_intelligence_partial_failure": {
        "name": "Threat Intelligence Partial Failure",
        "description": "Test resilience when threat intelligence lookups partially fail",
        "target_system": "security_system",
        "chaos_type": ChaosType.PARTIAL_FAILURE,
        "component": "threat_intelligence",
        "injection_point": "lookup",
        "injection_config": {
            "error_type": "PartialDataError",
            "error_rate": 0.25,  # 25% partial failures
            "duration_seconds": 180
        },
        "hypothesis": {
            "hypothesis_statement": "Partial threat data should still allow basic threat detection",
            "expected_behavior": {
                "max_latency_p95_ms": 500,
                "max_error_rate": 0.03
            }
        },
        "blast_radius": 15,
        "environment": "staging"
    }
}

# Reasoning System Scenarios (2 scenarios)
REASONING_SCENARIOS = {
    "hypothesis_testing_timeout": {
        "name": "Hypothesis Testing Timeout",
        "description": "Test handling of hypothesis testing timeouts",
        "target_system": "reasoning_system",
        "chaos_type": ChaosType.TIMEOUT,
        "component": "hypothesis_testing",
        "injection_point": "test_execution",
        "injection_config": {
            "timeout_ms": 5000,  # 5 second timeout
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Timeouts should trigger fallback to simpler reasoning methods",
            "expected_behavior": {
                "max_latency_p95_ms": 5500,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 20,
        "environment": "dev"
    },

    "bayesian_numeric_overflow": {
        "name": "Bayesian Inference Numeric Overflow",
        "description": "Test handling of numeric overflow in Bayesian computations",
        "target_system": "reasoning_system",
        "chaos_type": ChaosType.ERROR,
        "component": "bayesian_uncertainty",
        "injection_point": "monte_carlo_sampling",
        "injection_config": {
            "error_type": "NumericOverflowError",
            "error_rate": 0.1,  # 10% overflow
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "Numeric overflow should be caught and handled with approximations",
            "expected_behavior": {
                "max_latency_p95_ms": 600,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 10,
        "environment": "dev"
    }
}

# Autonomous Agent Scenarios (3 scenarios)
AGENT_SCENARIOS = {
    "governance_queue_overload": {
        "name": "Governance Queue Overload",
        "description": "Test system resilience when governance queue is overloaded",
        "target_system": "autonomous_agents",
        "chaos_type": ChaosType.RESOURCE_EXHAUSTION,
        "component": "governance_queue",
        "injection_point": "enqueue",
        "injection_config": {
            "resource_type": "queue_capacity",
            "limit_value": 0.95,  # 95% queue full
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Queue overload should trigger backpressure, not drop decisions",
            "expected_behavior": {
                "max_latency_p95_ms": 1000,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 20,
        "environment": "staging"
    },

    "task_executor_network_partition": {
        "name": "Task Executor Network Partition",
        "description": "Test agent communication during network partitions",
        "target_system": "autonomous_agents",
        "chaos_type": ChaosType.NETWORK_PARTITION,
        "component": "task_executor",
        "injection_point": "execute",
        "injection_config": {
            "partition_rate": 0.2,  # 20% packet loss
            "duration_seconds": 180
        },
        "hypothesis": {
            "hypothesis_statement": "Network partitions should not prevent task completion via retries",
            "expected_behavior": {
                "max_latency_p95_ms": 800,
                "max_error_rate": 0.03
            }
        },
        "blast_radius": 15,
        "environment": "dev"
    },

    "planning_engine_latency": {
        "name": "Planning Engine Latency",
        "description": "Test autonomous agents with slow planning",
        "target_system": "autonomous_agents",
        "chaos_type": ChaosType.LATENCY,
        "component": "planning_engine",
        "injection_point": "plan_generation",
        "injection_config": {
            "delay_ms": 2000,
            "jitter_ms": 500,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Slow planning should not block agent coordination",
            "expected_behavior": {
                "max_latency_p95_ms": 2500,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 10,
        "environment": "dev"
    }
}

# Domain System Scenarios (2 scenarios)
DOMAIN_SCENARIOS = {
    "cross_domain_reasoner_failure": {
        "name": "Cross-Domain Reasoner Failures",
        "description": "Test handling of cross-domain reasoning failures",
        "target_system": "domain_system",
        "chaos_type": ChaosType.ERROR,
        "component": "cross_domain_reasoner",
        "injection_point": "domain_mapping",
        "injection_config": {
            "error_type": "DomainMappingError",
            "error_rate": 0.15,  # 15% failure
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "Domain mapping failures should fallback to single-domain reasoning",
            "expected_behavior": {
                "max_latency_p95_ms": 500,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 20,
        "environment": "dev"
    },

    "ontology_registry_latency": {
        "name": "Ontology Registry Latency",
        "description": "Test system performance with slow ontology lookups",
        "target_system": "domain_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "universal_ontology",
        "injection_point": "concept_lookup",
        "injection_config": {
            "delay_ms": 400,
            "jitter_ms": 100,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Ontology latency should be cached to minimize impact",
            "expected_behavior": {
                "max_latency_p95_ms": 600,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 25,
        "environment": "staging"
    }
}

# Memory System Scenarios (6 scenarios)
MEMORY_SCENARIOS = {
    "postgres_query_latency": {
        "name": "PostgreSQL Memory Query Latency",
        "description": "Test memory retrieval with slow PostgreSQL queries (hot tier)",
        "target_system": "memory_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "memory_storage_postgres",
        "injection_point": "memory_query",
        "injection_config": {
            "delay_ms": 200,
            "jitter_ms": 50,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "PostgreSQL latency should be acceptable for hot tier memory",
            "expected_behavior": {
                "max_latency_p95_ms": 300,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 30,
        "environment": "staging"
    },

    "postgres_cold_tier_retrieval_failure": {
        "name": "PostgreSQL Cold Tier Retrieval Failures",
        "description": "Test handling of PostgreSQL cold tier storage retrieval failures (60+ day memories)",
        "target_system": "memory_system",
        "chaos_type": ChaosType.ERROR,
        "component": "postgres_storage",
        "injection_point": "get_memory_from_cold",
        "injection_config": {
            "error_type": "DatabaseConnectionError",
            "error_rate": 0.1,  # 10% failure
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "PostgreSQL cold tier failures should fallback gracefully, not block memory access",
            "expected_behavior": {
                "max_latency_p95_ms": 1000,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 15,
        "environment": "dev"
    },

    "capability_token_exhaustion": {
        "name": "Capability Token Exhaustion",
        "description": "Test system behavior when capability tokens are exhausted",
        "target_system": "memory_system",
        "chaos_type": ChaosType.RESOURCE_EXHAUSTION,
        "component": "capability_tokens",
        "injection_point": "allocate",
        "injection_config": {
            "resource_type": "tokens",
            "limit_value": 0.98,  # 98% tokens used
            "duration_seconds": 180
        },
        "hypothesis": {
            "hypothesis_statement": "Token exhaustion should trigger queuing, not rejection",
            "expected_behavior": {
                "max_latency_p95_ms": 800,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 20,
        "environment": "staging"
    },

    "reasoning_trace_capture_validation": {
        "name": "Reasoning Trace Capture Quality Under Latency",
        "description": "Validate chain of thought capture quality when PostgreSQL storage is slow",
        "target_system": "memory_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "memory_storage_postgres",
        "injection_point": "store_memory",
        "injection_config": {
            "delay_ms": 300,
            "jitter_ms": 100,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Reasoning trace capture rate should remain >80% despite storage latency",
            "expected_behavior": {
                "max_latency_p95_ms": 500,
                "max_error_rate": 0.01,
                "min_reasoning_trace_completeness_rate": 0.8,  # 80% capture
                "min_thinking_state_capture_rate": 0.75
            }
        },
        "blast_radius": 10,
        "environment": "dev"
    },

    "chain_of_thought_persistence_under_errors": {
        "name": "Chain of Thought Persistence Under Database Errors",
        "description": "Validate reasoning traces aren't dropped during database connection failures",
        "target_system": "memory_system",
        "chaos_type": ChaosType.ERROR,
        "component": "memory_storage_postgres",
        "injection_point": "store_memory",
        "injection_config": {
            "error_type": "ConnectionError",
            "error_rate": 0.15,  # 15% failure rate
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "Connection errors should trigger retries, not drop reasoning traces",
            "expected_behavior": {
                "max_latency_p95_ms": 600,
                "max_error_rate": 0.02,
                "min_reasoning_trace_completeness_rate": 0.85,  # 85% capture with retries
                "min_decision_factors_population_rate": 0.8
            }
        },
        "blast_radius": 8,
        "environment": "dev"
    },

    "thinking_state_capture_completeness": {
        "name": "Thinking State Capture Completeness Test",
        "description": "Validate all chain of thought fields are persisted under memory pressure",
        "target_system": "memory_system",
        "chaos_type": ChaosType.RESOURCE_EXHAUSTION,
        "component": "memory_storage_postgres",
        "injection_point": "connection_pool",
        "injection_config": {
            "resource_type": "connections",
            "limit_value": 0.9,  # 90% connection pool utilization
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Connection pool pressure should not degrade chain of thought capture quality",
            "expected_behavior": {
                "max_latency_p95_ms": 700,
                "max_error_rate": 0.03,
                "min_reasoning_trace_completeness_rate": 0.9,  # 90% capture
                "min_thinking_state_capture_rate": 0.85,
                "min_decision_factors_population_rate": 0.85,
                "min_reasoning_trace_avg_length": 3  # At least 3 steps average
            }
        },
        "blast_radius": 12,
        "environment": "staging"
    }
}

# Intelligence System Scenarios (3 scenarios)
INTELLIGENCE_SCENARIOS = {
    "nlp_processing_latency": {
        "name": "NLP Processing Latency Spike",
        "description": "Test NLP optimizer resilience with slow text processing",
        "target_system": "intelligence_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "nlp_processor",
        "injection_point": "nlp_processing",
        "injection_config": {
            "delay_ms": 800,
            "jitter_ms": 150,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "NLP processing latency should not block downstream intelligence tasks",
            "expected_behavior": {
                "max_latency_p95_ms": 1000,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 10,
        "environment": "staging"
    },

    "prediction_model_failures": {
        "name": "Predictive Intelligence Model Failures",
        "description": "Test handling of prediction generation failures",
        "target_system": "intelligence_system",
        "chaos_type": ChaosType.ERROR,
        "component": "predictive_system",
        "injection_point": "prediction_inference",
        "injection_config": {
            "error_type": "PredictionError",
            "error_rate": 0.15,
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "Prediction failures should gracefully degrade with fallback models",
            "expected_behavior": {
                "max_latency_p95_ms": 600,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 8,
        "environment": "staging"
    },

    "prediction_cache_exhaustion": {
        "name": "Prediction Cache Memory Exhaustion",
        "description": "Test prediction system under cache memory pressure",
        "target_system": "intelligence_system",
        "chaos_type": ChaosType.RESOURCE_EXHAUSTION,
        "component": "prediction_cache",
        "injection_point": "cache_operations",
        "injection_config": {
            "resource_type": "cache",
            "duration_seconds": 360
        },
        "hypothesis": {
            "hypothesis_statement": "Cache exhaustion should trigger LRU eviction without failures",
            "expected_behavior": {
                "max_latency_p95_ms": 800,
                "max_error_rate": 0.03
            }
        },
        "blast_radius": 12,
        "environment": "staging"
    }
}

# Monitoring System Scenarios (3 scenarios)
MONITORING_SCENARIOS = {
    "prometheus_export_latency": {
        "name": "Prometheus Metrics Export Latency",
        "description": "Test monitoring system resilience with slow metrics export",
        "target_system": "monitoring_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "prometheus_exporter",
        "injection_point": "metrics_export",
        "injection_config": {
            "delay_ms": 600,
            "jitter_ms": 100,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "Slow metrics export should not impact system observability",
            "expected_behavior": {
                "max_latency_p95_ms": 750,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 5,
        "environment": "staging"
    },

    "metric_collection_failures": {
        "name": "Resource Metric Collection Failures",
        "description": "Test handling of failed resource metric collection",
        "target_system": "monitoring_system",
        "chaos_type": ChaosType.ERROR,
        "component": "resource_monitor",
        "injection_point": "metric_collection",
        "injection_config": {
            "error_type": "MetricCollectionError",
            "error_rate": 0.2,
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "Failed metric collection should retry without data loss",
            "expected_behavior": {
                "max_latency_p95_ms": 500,
                "max_error_rate": 0.05
            }
        },
        "blast_radius": 8,
        "environment": "staging"
    },

    "metric_buffer_overflow": {
        "name": "Metric Buffer Memory Exhaustion",
        "description": "Test monitoring system under metric buffer overflow",
        "target_system": "monitoring_system",
        "chaos_type": ChaosType.RESOURCE_EXHAUSTION,
        "component": "metric_aggregator",
        "injection_point": "metric_aggregation",
        "injection_config": {
            "resource_type": "metric_buffer",
            "duration_seconds": 360
        },
        "hypothesis": {
            "hypothesis_statement": "Buffer overflow should trigger metric sampling without system failure",
            "expected_behavior": {
                "max_latency_p95_ms": 600,
                "max_error_rate": 0.02
            }
        },
        "blast_radius": 10,
        "environment": "staging"
    }
}

# Services System Scenarios (3 scenarios)
SERVICES_SCENARIOS = {
    "llm_inference_latency": {
        "name": "LLM Inference Latency Spike",
        "description": "Test unified LLM service resilience with slow model inference",
        "target_system": "services_system",
        "chaos_type": ChaosType.LATENCY,
        "component": "unified_llm",
        "injection_point": "llm_inference",
        "injection_config": {
            "delay_ms": 2000,
            "jitter_ms": 500,
            "duration_seconds": 300
        },
        "hypothesis": {
            "hypothesis_statement": "LLM inference latency should queue requests without timeouts",
            "expected_behavior": {
                "max_latency_p95_ms": 2800,
                "max_error_rate": 0.01
            }
        },
        "blast_radius": 15,
        "environment": "staging"
    },

    "backup_operation_failures": {
        "name": "Backup Scheduler Operation Failures",
        "description": "Test handling of backup operation failures",
        "target_system": "services_system",
        "chaos_type": ChaosType.ERROR,
        "component": "backup_scheduler",
        "injection_point": "backup_operation",
        "injection_config": {
            "error_type": "BackupError",
            "error_rate": 0.25,
            "duration_seconds": 240
        },
        "hypothesis": {
            "hypothesis_statement": "Backup failures should retry with exponential backoff",
            "expected_behavior": {
                "max_latency_p95_ms": 1000,
                "max_error_rate": 0.05
            }
        },
        "blast_radius": 5,
        "environment": "staging"
    },

    "llm_request_queue_exhaustion": {
        "name": "LLM Request Queue Exhaustion",
        "description": "Test unified LLM service under request queue overflow",
        "target_system": "services_system",
        "chaos_type": ChaosType.RESOURCE_EXHAUSTION,
        "component": "unified_llm",
        "injection_point": "llm_queue",
        "injection_config": {
            "resource_type": "queue",
            "duration_seconds": 360
        },
        "hypothesis": {
            "hypothesis_statement": "Queue exhaustion should trigger request rejection with backpressure",
            "expected_behavior": {
                "max_latency_p95_ms": 1500,
                "max_error_rate": 0.10  # Higher error rate acceptable with queue rejection
            }
        },
        "blast_radius": 20,
        "environment": "staging"
    }
}

# All scenarios combined
ALL_SCENARIOS = {
    **TOOL_SCENARIOS,
    **LEARNING_SCENARIOS,
    **SECURITY_SCENARIOS,
    **REASONING_SCENARIOS,
    **AGENT_SCENARIOS,
    **DOMAIN_SCENARIOS,
    **MEMORY_SCENARIOS,
    **INTELLIGENCE_SCENARIOS,
    **MONITORING_SCENARIOS,
    **SERVICES_SCENARIOS
}


def get_scenario(scenario_name: str) -> Dict:
    """
    Get a scenario by name.

    Args:
        scenario_name: Scenario identifier

    Returns:
        Scenario dict

    Raises:
        KeyError: If scenario not found
    """
    if scenario_name not in ALL_SCENARIOS:
        raise KeyError(f"Scenario '{scenario_name}' not found in library")

    return ALL_SCENARIOS[scenario_name].copy()


def get_scenarios_by_system(target_system: str) -> List[Dict]:
    """
    Get all scenarios for a target system.

    Args:
        target_system: Target system name

    Returns:
        List of scenario dicts
    """
    system_scenarios = {
        "tool_system": TOOL_SCENARIOS,
        "learning_system": LEARNING_SCENARIOS,
        "security_system": SECURITY_SCENARIOS,
        "reasoning_system": REASONING_SCENARIOS,
        "autonomous_agents": AGENT_SCENARIOS,
        "domain_system": DOMAIN_SCENARIOS,
        "memory_system": MEMORY_SCENARIOS,
        "intelligence_system": INTELLIGENCE_SCENARIOS,
        "monitoring_system": MONITORING_SCENARIOS,
        "services_system": SERVICES_SCENARIOS
    }

    if target_system not in system_scenarios:
        raise ValueError(f"Unknown target system: {target_system}")

    return list(system_scenarios[target_system].values())


def list_all_scenarios() -> Dict[str, List[str]]:
    """
    List all available scenarios grouped by system.

    Returns:
        Dict mapping system names to scenario names
    """
    return {
        "tool_system": list(TOOL_SCENARIOS.keys()),
        "learning_system": list(LEARNING_SCENARIOS.keys()),
        "security_system": list(SECURITY_SCENARIOS.keys()),
        "reasoning_system": list(REASONING_SCENARIOS.keys()),
        "autonomous_agents": list(AGENT_SCENARIOS.keys()),
        "domain_system": list(DOMAIN_SCENARIOS.keys()),
        "memory_system": list(MEMORY_SCENARIOS.keys()),
        "intelligence_system": list(INTELLIGENCE_SCENARIOS.keys()),
        "monitoring_system": list(MONITORING_SCENARIOS.keys()),
        "services_system": list(SERVICES_SCENARIOS.keys())
    }
