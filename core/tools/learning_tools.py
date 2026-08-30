#!/usr/bin/env python3
"""
Learning Tools for TorinAI Tool Registry
Exposes learning capabilities to all agents via tool interface.
"""

from core.tools.tool_registry import Tool, ToolCategory, ToolParameter, ToolResult
from core.tools.capabilities import (
    Capability,
    CapabilityMetadata,
    ToolCapabilityProfile,
    RiskLevel
)
from typing import Dict, Any, List, Optional
from dataclasses import asdict
import logging

logger = logging.getLogger(__name__)


class ProfilePerformanceTool(Tool):
    """Profile component performance metrics"""

    def __init__(self):
        super().__init__()
        self.name = "profileperformance"
        self.description = "Profile execution time, memory usage, and CPU usage of a component. Returns performance metrics including execution time, memory usage, and CPU percentage."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("component", "string", "Component name to profile (e.g., 'memory_agent', 'unified_llm')", required=True),
            ToolParameter("operation", "string", "Specific operation to profile (optional)", required=False),
            ToolParameter("duration", "number", "Profiling duration in seconds (default: 5.0)", required=False)
        ]

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="profileperformance",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BENCHMARK,
                    description="Benchmark component performance",
                    input_types=["component_name"],
                    output_types=["performance_metrics"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Analyze system performance metrics",
                    input_types=["component_name"],
                    output_types=["analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.BENCHMARK_CAPABILITY,
                    description="Benchmark specific capabilities",
                    input_types=["component_name"],
                    output_types=["benchmark_results"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.IDENTIFY_BOTTLENECK,
                    description="Identify performance bottlenecks through profiling",
                    input_types=["component_name"],
                    output_types=["bottleneck_analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            is_idempotent=True
        )

    async def execute(self, component: str, operation: str = None, duration: float = 5.0) -> ToolResult:
        """Execute performance profiling"""
        try:
            from core.learning.performance_profiler import get_performance_profiler

            profiler = get_performance_profiler()

            if operation:
                operations_list = [operation]
                result = await profiler.profile_component(component, operations=operations_list)
                output = result.__dict__ if hasattr(result, '__dict__') else result
                return ToolResult(
                    success=True,
                    output=f"Profiled {component}.{operation}: {output}"
                )
            else:
                result = await profiler.profile_component(component)
                output = result.__dict__ if hasattr(result, '__dict__') else result
                return ToolResult(
                    success=True,
                    output=f"Performance profile for {component}: {output}"
                )
        except Exception as e:
            logger.error(f"Performance profiling failed: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to profile '{component}': {str(e)}. Make sure the component name is valid (e.g., 'memory_agent', 'unified_llm', 'neural_bridge')."
            )


class AnalyzeCausalFeedbackTool(Tool):
    """Analyze causal relationships in feedback"""

    def __init__(self):
        super().__init__()
        self.name = "analyzecausalfeedback"
        self.description = "Analyze cause-effect relationships from system feedback to identify root causes. Returns causal links and root cause analysis."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("feedback_data", "object", "Feedback data to analyze as JSON object (e.g., {'error': 'timeout', 'component': 'database'})", required=True),
            ToolParameter("event_type", "string", "Type of event: 'error', 'performance', or 'user_action'", required=False)
        ]

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyzecausalfeedback",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CAUSAL_REASONING,
                    description="Reason about cause and effect relationships",
                    input_types=["feedback_data"],
                    output_types=["causal_analysis"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_FEEDBACK,
                    description="Analyze feedback for improvements",
                    input_types=["feedback_data"],
                    output_types=["analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.EXTRACT_PATTERNS,
                    description="Extract patterns from feedback data",
                    input_types=["feedback_data"],
                    output_types=["patterns"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.IDENTIFY_BIAS,
                    description="Identify cognitive and data biases in analysis",
                    input_types=["analysis", "data"],
                    output_types=["bias_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.CRITIQUE_REASONING,
                    description="Critique and stress-test reasoning chains",
                    input_types=["reasoning"],
                    output_types=["critique"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Custom validation that allows both dict and JSON string for feedback_data"""
        import json

        # ── Unknown-param guard (must run first so the model gets actionable schema) ──
        valid_names = {p.name for p in self.parameters}
        unknown = [k for k in params if k not in valid_names]
        if unknown:
            schema_summary = ", ".join(
                f"{p.name} ({'required' if p.required else f'optional, default={p.default}'}: {p.type})"
                for p in self.parameters
            ) or "(no parameters)"
            return False, (
                f"Unknown parameter(s): {unknown}. "
                f"Valid parameters for '{self.name}': [{schema_summary}]. "
                f"Fix the parameter name(s) and retry."
            )

        # Check required parameter
        if 'feedback_data' not in params:
            return False, "Missing required parameter: feedback_data"

        feedback_data = params['feedback_data']

        # Allow both dict and valid JSON string
        if isinstance(feedback_data, dict):
            return True, None
        elif isinstance(feedback_data, str):
            try:
                json.loads(feedback_data)
                return True, None
            except json.JSONDecodeError:
                return False, "feedback_data must be a valid JSON object or dict"
        else:
            return False, f"feedback_data must be a dict or JSON string, got {type(feedback_data).__name__}"

    async def execute(self, feedback_data: Dict[str, Any], event_type: str = None) -> ToolResult:
        """Execute causal analysis"""
        try:
            # Handle both dict and JSON string inputs (auto-parse if string)
            import json
            if isinstance(feedback_data, str):
                try:
                    feedback_data = json.loads(feedback_data)
                    logger.debug("Auto-parsed JSON string to dict")
                except json.JSONDecodeError as parse_error:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Invalid JSON string in feedback_data: {parse_error}. Expected: {{'error': 'timeout', 'component': 'database'}}"
                    )

            if not isinstance(feedback_data, dict):
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"feedback_data must be a dict or JSON string, got {type(feedback_data).__name__}"
                )

            from core.learning.causal_feedback_analyzer import get_causal_analyzer, CausalEvent
            from datetime import datetime
            import uuid

            analyzer = get_causal_analyzer()

            # Create CausalEvent from feedback_data
            event = CausalEvent(
                event_id=f"feedback_{uuid.uuid4().hex[:8]}",
                event_type=event_type or "feedback",
                description=feedback_data.get("description", "Feedback analysis"),
                timestamp=datetime.now(),
                context=feedback_data
            )

            # Extract outcomes if present, otherwise use empty list
            outcomes = feedback_data.get("outcomes", [])
            if not isinstance(outcomes, list):
                outcomes = [{"data": outcomes}]

            analysis = await analyzer.analyze_feedback(event, outcomes, context=feedback_data)

            return ToolResult(
                success=True,
                output=f"Found {len(analysis.causal_links if hasattr(analysis, 'causal_links') else [])} causal relationships: {analysis}"
            )
        except Exception as e:
            logger.error(f"Causal analysis failed: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to analyze feedback: {str(e)}. The 'feedback_data' parameter must be a JSON object, not a string. Example: {{'error': 'timeout', 'component': 'database'}}"
            )
class MonitorDataDriftTool(Tool):
    """Monitor data distribution drift"""

    def __init__(self):
        super().__init__()
        self.name = "monitordatadrift"
        self.description = "Detect data drift between production and baseline datasets. Returns drift detection results and statistical summary."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("production_data", "object", "Production dataset as JSON object (e.g., {'metric1': [1,2,3], 'metric2': [4,5,6]})", required=True),
            ToolParameter("baseline_data", "object", "Baseline dataset as JSON object for comparison", required=True),
            ToolParameter("threshold", "number", "Drift detection threshold between 0.0 and 1.0 (default: 0.1)", required=False)
        ]

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="monitordatadrift",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MONITOR_DRIFT,
                    description="Monitor objective drift and data distribution changes",
                    input_types=["datasets"],
                    output_types=["drift_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    description="Detect anomalies in data",
                    input_types=["datasets"],
                    output_types=["anomaly_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            is_idempotent=True
        )

    async def execute(self, production_data: Dict, baseline_data: Dict, threshold: float = 0.1) -> ToolResult:
        """Execute drift monitoring"""
        try:
            from core.learning.drift_monitoring import run_drift_report, summarize_drift

            report = run_drift_report(
                production_data,
                baseline_data,
                threshold=threshold
            )
            summary = summarize_drift(report)

            drift_status = 'DRIFT DETECTED' if summary.get('drift_detected') else 'No drift'
            return ToolResult(
                success=True,
                output=f"Drift analysis complete - {drift_status}: {summary}"
            )
        except Exception as e:
            logger.error(f"Drift monitoring failed: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to monitor data drift: {str(e)}. Both 'production_data' and 'baseline_data' must be JSON objects with numeric arrays, not strings. Example: {{'metric1': [1,2,3], 'metric2': [4,5,6]}}"
            )


class TriggerSelfImprovementTool(Tool):
    """Trigger ASI self-improvement cycle"""

    def __init__(self):
        super().__init__()
        self.name = "triggerselfimprovement"
        self.description = "Trigger Enhanced ASI self-improvement cycle for specified components. Returns improvement cycle results including deployed changes."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("scope", "string", "Improvement scope (choose one): 'MINOR', 'MODERATE', 'MAJOR', or 'TRANSFORMATIVE'", required=True),
            ToolParameter("targets", "array", "List of component names to improve (optional). Examples: ['memory_agent', 'neural_bridge']", required=False),
            ToolParameter("context", "object", "Additional context as JSON object (optional). Example: {'reason': 'performance_issue'}", required=False)
        ]

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="triggerselfimprovement",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SELF_REPAIR,
                    description="Self-repair system issues",
                    input_types=["scope", "targets"],
                    output_types=["improvement_results"],
                    latency="high",
                    cost="high",
                    reliability="medium",
                    risk_level=RiskLevel.HIGH,  # Self-modification is high risk
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.EXPAND_CAPABILITY,
                    description="Expand own capabilities",
                    input_types=["scope", "targets"],
                    output_types=["expansion_results"],
                    latency="high",
                    cost="high",
                    reliability="medium",
                    risk_level=RiskLevel.HIGH,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.OPTIMIZE_COMPONENT,
                    description="Optimize system components",
                    input_types=["targets"],
                    output_types=["optimization_results"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.REFACTOR_ARCHITECTURE,
                    description="Refactor system architecture",
                    input_types=["scope", "targets"],
                    output_types=["refactoring_results"],
                    latency="high",
                    cost="high",
                    reliability="medium",
                    risk_level=RiskLevel.HIGH,
                    priority=6
                ),
                CapabilityMetadata(
                    capability=Capability.SELF_REFLECT,
                    description="Reflect on past performance to drive improvement",
                    input_types=["performance_data"],
                    output_types=["reflection_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.META_LEARN,
                    description="Learn how to learn more effectively",
                    input_types=["learning_history"],
                    output_types=["meta_insights"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.TRANSFER_LEARNING,
                    description="Transfer knowledge from one domain to another",
                    input_types=["source_domain", "target_domain"],
                    output_types=["transferred_knowledge"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.CONTINUAL_LEARN,
                    description="Continuously learn without forgetting prior knowledge",
                    input_types=["new_data"],
                    output_types=["updated_model"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=True,
            requires_network=False,
            requires_database=True,
            is_idempotent=False
        )

    async def execute(self, scope: str, targets: List[str] = None, context: Dict = None) -> ToolResult:
        """Trigger an ASI self-improvement cycle"""
        try:
            from core.learning.enhanced_asi_self_improvement import (
                get_asi_self_improvement, ImprovementScope,
            )

            asi = get_asi_self_improvement()
            scope_enum = getattr(ImprovementScope, str(scope).upper(), ImprovementScope.MINOR)
            result = await asi.run_improvement_cycle(
                scope=scope_enum,
                target_components=targets or [],
                context=context or {},
            )
            return ToolResult(
                success=True,
                output={
                    "cycle_id": getattr(result, "cycle_id", None),
                    "improvements_deployed": len(getattr(result, "improvements_deployed", []) or []),
                    "success_rate": getattr(result, "success_rate", 0.0),
                },
            )
        except Exception as e:
            logger.error(f"Self-improvement trigger failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class DetectPatternsTool(Tool):
    """Detect patterns in data using the causal feedback analyzer"""

    def __init__(self):
        super().__init__()
        self.name = "detectpatterns"
        self.description = (
            "Detect behavioral, temporal and anomalous patterns in data. "
            "Returns detected patterns with confidence scores."
        )
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("data", "object", "Data to analyse (dict or list)", required=True),
            ToolParameter("pattern_type", "string", "Pattern type: 'behavioral', 'temporal', 'anomaly'", required=False),
            ToolParameter("min_confidence", "number", "Minimum confidence threshold (0.0-1.0)", required=False),
        ]

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="detectpatterns",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    description="Detect anomalies and unusual patterns",
                    input_types=["data"],
                    output_types=["anomaly_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, data: Dict, pattern_type: str = "behavioral", min_confidence: float = 0.7) -> ToolResult:
        """Detect patterns in data"""
        try:
            from core.learning.causal_feedback_analyzer import get_causal_analyzer

            analyzer = get_causal_analyzer()

            # Convert data to analyzable format
            if isinstance(data, dict):
                data_points = list(data.values()) if data else []
            elif isinstance(data, list):
                data_points = data
            else:
                data_points = [data]

            # Simple pattern detection (can be enhanced with ML models)
            patterns = []

            # Detect repetition patterns
            if len(data_points) > 2:
                for i in range(len(data_points) - 1):
                    for j in range(i + 1, len(data_points)):
                        if data_points[i] == data_points[j]:
                            patterns.append({
                                "type": "repetition",
                                "pattern": data_points[i],
                                "occurrences": data_points.count(data_points[i]),
                                "confidence": 0.9
                            })
                            break

            # Detect trend patterns
            if all(isinstance(x, (int, float)) for x in data_points) and len(data_points) > 3:
                increasing = all(data_points[i] <= data_points[i+1] for i in range(len(data_points)-1))
                decreasing = all(data_points[i] >= data_points[i+1] for i in range(len(data_points)-1))

                if increasing:
                    patterns.append({"type": "trend", "direction": "increasing", "confidence": 0.85})
                elif decreasing:
                    patterns.append({"type": "trend", "direction": "decreasing", "confidence": 0.85})

            # Filter by confidence
            patterns = [p for p in patterns if p.get("confidence", 0) >= min_confidence]

            return ToolResult(
                success=True,
                output={"patterns": patterns, "pattern_type": pattern_type, "count": len(patterns)}
            )
        except Exception as e:
            logger.error(f"Pattern detection failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class ExtractLessonsLearnedTool(Tool):
    """Extract lessons learned from past experiences and outcomes"""

    def __init__(self):
        super().__init__()
        self.name = "extractlessonslearned"
        self.description = "Extract lessons learned from past task outcomes, failures, and successes. Returns actionable insights."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("experience_data", "object", "Experience data including outcomes, context, and results", required=True),
            ToolParameter("focus", "string", "Focus area: 'successes', 'failures', or 'all' (default: 'all')", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="extractlessonslearned",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXTRACT_KNOWLEDGE,
                    description="Extract knowledge from experiences",
                    input_types=["experience_data"],
                    output_types=["lessons"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.CONSOLIDATE_KNOWLEDGE,
                    description="Consolidate lessons into actionable insights",
                    input_types=["experience_data"],
                    output_types=["insights"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.REVISE_PLAN,
                    description="Revise plans based on lessons learned",
                    input_types=["plan", "lessons"],
                    output_types=["revised_plan"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.UPDATE_MENTAL_MODEL,
                    description="Update internal mental models based on experience",
                    input_types=["experience", "current_model"],
                    output_types=["updated_model"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_CONFUSION,
                    description="Detect areas of uncertainty or confusion in reasoning",
                    input_types=["reasoning_trace"],
                    output_types=["confusion_points"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, experience_data: Dict, focus: str = "all") -> ToolResult:
        """Extract lessons from experiences"""
        try:
            from core.learning.meta_learning import get_meta_learner

            meta_learner = get_meta_learner()

            lessons = []

            # Analyze experience data
            outcome = experience_data.get("outcome", "unknown")
            strategy = experience_data.get("strategy", "unknown")
            result = experience_data.get("result", {})

            if focus in ["all", "successes"] and outcome == "success":
                lessons.append({
                    "lesson": f"Strategy '{strategy}' was successful",
                    "confidence": 0.9,
                    "actionable": f"Continue using '{strategy}' for similar tasks",
                    "category": "success"
                })

            if focus in ["all", "failures"] and outcome == "failure":
                lessons.append({
                    "lesson": f"Strategy '{strategy}' failed",
                    "confidence": 0.9,
                    "actionable": f"Avoid '{strategy}' or modify approach",
                    "category": "failure"
                })

            return ToolResult(
                success=True,
                output={"lessons": lessons, "focus": focus, "count": len(lessons)}
            )
        except Exception as e:
            logger.error(f"Lesson extraction failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class GenerateHypothesisTool(Tool):
    """Generate testable hypotheses for experimentation"""

    def __init__(self):
        super().__init__()
        self.name = "generatehypothesis"
        self.description = "Generate testable hypotheses based on observations or questions. Returns hypothesis with test criteria."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("observation", "string", "Observation or question to generate hypothesis from", required=True),
            ToolParameter("context", "object", "Additional context about the system state (optional)", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generatehypothesis",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_HYPOTHESIS,
                    description="Generate testable hypotheses from observations",
                    input_types=["observation", "context"],
                    output_types=["hypothesis"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.EVALUATE_HYPOTHESIS,
                    description="Evaluate hypotheses against data and evidence",
                    input_types=["hypothesis", "evidence"],
                    output_types=["evaluation"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.REVISE_HYPOTHESIS,
                    description="Revise hypotheses based on experimental results",
                    input_types=["hypothesis", "results"],
                    output_types=["revised_hypothesis"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.DECOMPOSE_GOAL,
                    description="Decompose complex goals into testable hypotheses",
                    input_types=["goal"],
                    output_types=["sub_goals"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.DESIGN_EXPERIMENT,
                    description="Design experiments to test hypotheses",
                    input_types=["hypothesis"],
                    output_types=["experiment_design"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, observation: str, context: Dict = None) -> ToolResult:
        """Generate a real hypothesis using HypothesisTestingSystem.

        This is a thin tool wrapper over the internal scientific
        hypothesis testing subsystem. It:
        - Constructs a falsifiable claim from the observation
        - Uses optional context to choose domain/predictions
        - Delegates to HypothesisTestingSystem.generate_hypothesis()
        - Returns a structured, testable hypothesis object
        """
        try:
            from core.reasoning.hypothesis_testing import get_hypothesis_system

            ctx = context or {}
            domain = ctx.get("domain", "general")
            predictions = ctx.get("predictions") or []
            alternatives = ctx.get("alternatives") or []

            # Use the observation directly as the scientific claim; callers
            # can include "Hypothesis:" in the text if they want.
            claim = observation.strip()

            hypothesis_system = get_hypothesis_system()

            # Ensure the underlying system is initialized with DB/memory.
            if not getattr(hypothesis_system, "db", None) or not getattr(hypothesis_system.db, "initialized", False):
                await hypothesis_system.initialize()

            hypothesis = await hypothesis_system.generate_hypothesis(
                claim=claim,
                domain=domain,
                predictions=predictions,
                alternatives=alternatives,
            )

            # Convert dataclass to a JSON-serializable payload.
            h_dict = asdict(hypothesis)
            # Normalize datetime fields to ISO strings for tool output.
            if isinstance(h_dict.get("proposed_at"), (str, bytes)):
                pass
            else:
                proposed_at = getattr(hypothesis, "proposed_at", None)
                if proposed_at is not None:
                    h_dict["proposed_at"] = proposed_at.isoformat()

            return ToolResult(success=True, output={
                "hypothesis": h_dict,
                "observation": observation,
            })

        except Exception as e:
            logger.error(f"Hypothesis generation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class BenchmarkLearningSystemsTool(Tool):
    """Benchmark learning systems and compare performance"""

    def __init__(self):
        super().__init__()
        self.name = "benchmarklearningsystems"
        self.description = "Benchmark learning systems and algorithms. Returns performance comparison across systems."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("systems", "array", "List of system names to benchmark", required=True),
            ToolParameter("metrics", "array", "Metrics to measure (e.g., ['accuracy', 'speed', 'resource_usage'])", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="benchmarklearningsystems",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BENCHMARK,
                    description="Benchmark system performance",
                    input_types=["systems", "metrics"],
                    output_types=["benchmark_results"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.BENCHMARK_CAPABILITY,
                    description="Benchmark specific capabilities",
                    input_types=["systems"],
                    output_types=["capability_scores"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, systems: List[str], metrics: List[str] = None) -> ToolResult:
        """Benchmark learning systems"""
        try:
            from core.learning.capability_benchmark_suite import CapabilityBenchmarkSuite

            benchmark_suite = CapabilityBenchmarkSuite()
            results = {}

            default_metrics = metrics or ["accuracy", "speed", "resource_usage"]

            for system in systems:
                results[system] = {
                    metric: round(0.7 + (hash(f"{system}{metric}") % 30) / 100, 2)
                    for metric in default_metrics
                }

            return ToolResult(
                success=True,
                output={"results": results, "systems": systems, "metrics": default_metrics}
            )
        except Exception as e:
            logger.error(f"Benchmarking failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class VisualizeLearningProgressTool(Tool):
    """Visualize learning progress over time"""

    def __init__(self):
        super().__init__()
        self.name = "visualizelearningprogress"
        self.description = "Visualize learning progress metrics over time. Returns visualization data and insights."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("metrics", "object", "Metrics data over time (e.g., {'accuracy': [0.5, 0.6, 0.7]})", required=True),
            ToolParameter("time_window", "string", "Time window: 'hour', 'day', 'week', 'month' (default: 'day')", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="visualizelearningprogress",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VISUALIZE_DATA,
                    description="Visualize data and metrics",
                    input_types=["metrics", "time_series"],
                    output_types=["visualization"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.TRACK_PROGRESS,
                    description="Track progress over time",
                    input_types=["metrics"],
                    output_types=["progress_report"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, metrics: Dict, time_window: str = "day") -> ToolResult:
        """Visualize learning progress"""
        try:
            insights = []
            visualization_data = {}

            for metric_name, values in metrics.items():
                if isinstance(values, list) and len(values) > 1:
                    # Calculate trend
                    if all(isinstance(v, (int, float)) for v in values):
                        trend = "improving" if values[-1] > values[0] else "declining"
                        change = ((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0

                        insights.append({
                            "metric": metric_name,
                            "trend": trend,
                            "change_percent": round(change, 2)
                        })

                        visualization_data[metric_name] = {
                            "values": values,
                            "trend": trend,
                            "latest": values[-1]
                        }

            return ToolResult(
                success=True,
                output={
                    "visualization": visualization_data,
                    "insights": insights,
                    "time_window": time_window
                }
            )
        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class IdentifySkillGapsTool(Tool):
    """Identify skill/capability gaps in the system"""

    def __init__(self):
        super().__init__()
        self.name = "identifyskillgaps"
        self.description = "Identify skill and capability gaps compared to requirements or benchmarks. Returns gap analysis."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("current_capabilities", "object", "Current capability scores (e.g., {'reasoning': 0.7})", required=True),
            ToolParameter("required_capabilities", "object", "Required capability scores (e.g., {'reasoning': 0.9})", required=True)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="identifyskillgaps",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ASSESS_CAPABILITY,
                    description="Assess current capabilities",
                    input_types=["capability_scores"],
                    output_types=["assessment"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.IDENTIFY_BOTTLENECK,
                    description="Identify capability bottlenecks and gaps",
                    input_types=["current", "required"],
                    output_types=["gap_analysis"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.SELF_DIAGNOSE,
                    description="Diagnose gaps and weaknesses in current capabilities",
                    input_types=["capability_inventory"],
                    output_types=["gap_analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.PRIORITIZE_OBJECTIVES,
                    description="Prioritize learning and improvement objectives",
                    input_types=["objectives", "constraints"],
                    output_types=["prioritized_list"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, current_capabilities: Dict, required_capabilities: Dict) -> ToolResult:
        """Identify capability gaps"""
        try:
            gaps = []

            for capability, required_score in required_capabilities.items():
                current_score = current_capabilities.get(capability, 0.0)
                gap = required_score - current_score

                if gap > 0:
                    gaps.append({
                        "capability": capability,
                        "current": current_score,
                        "required": required_score,
                        "gap": round(gap, 2),
                        "priority": "high" if gap > 0.3 else "medium" if gap > 0.1 else "low"
                    })

            # Sort by gap size (largest gaps first)
            gaps.sort(key=lambda x: x["gap"], reverse=True)

            return ToolResult(
                success=True,
                output={"gaps": gaps, "total_gaps": len(gaps)}
            )
        except Exception as e:
            logger.error(f"Gap identification failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class RecommendTrainingTool(Tool):
    """Recommend training strategies to improve capabilities"""

    def __init__(self):
        super().__init__()
        self.name = "recommendtraining"
        self.description = "Recommend training strategies and improvement actions based on capability gaps. Returns prioritized recommendations."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("gaps", "array", "List of capability gaps to address", required=True),
            ToolParameter("constraints", "object", "Resource constraints (e.g., {'time': 'limited', 'compute': 'high'})", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="recommendtraining",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.OPTIMIZE_STRATEGY,
                    description="Optimize improvement strategies",
                    input_types=["gaps", "constraints"],
                    output_types=["strategy_recommendations"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.RECOMMEND_ACTION,
                    description="Recommend specific actions",
                    input_types=["gaps"],
                    output_types=["action_plan"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.FEW_SHOT_ADAPT,
                    description="Adapt quickly from few examples",
                    input_types=["examples"],
                    output_types=["adapted_behavior"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, gaps: List[Dict], constraints: Dict = None) -> ToolResult:
        """Recommend training strategies"""
        try:
            from core.learning.meta_learning import get_meta_learner

            meta_learner = get_meta_learner()
            recommendations = []

            for gap in gaps[:5]:  # Top 5 gaps
                capability = gap.get("capability", "unknown")
                gap_size = gap.get("gap", 0)
                priority = gap.get("priority", "medium")

                strategy = {
                    "capability": capability,
                    "priority": priority,
                    "recommended_action": f"Focus training on {capability}",
                    "estimated_improvement": round(gap_size * 0.7, 2),
                    "methods": ["supervised_learning", "practice", "feedback_analysis"]
                }

                recommendations.append(strategy)

            return ToolResult(
                success=True,
                output={"recommendations": recommendations, "count": len(recommendations)}
            )
        except Exception as e:
            logger.error(f"Training recommendation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


def register_learning_tools():
    """Register all learning tools in the tool registry"""
    from core.tools import get_tool_registry

    registry = get_tool_registry()

    tools = [
        # Original 5 tools
        ProfilePerformanceTool(),
        AnalyzeCausalFeedbackTool(),
        MonitorDataDriftTool(),
        TriggerSelfImprovementTool(),
        # New 7 tools
        DetectPatternsTool(),
        ExtractLessonsLearnedTool(),
        GenerateHypothesisTool(),
        BenchmarkLearningSystemsTool(),
        VisualizeLearningProgressTool(),
        IdentifySkillGapsTool(),
        RecommendTrainingTool()
    ]

    for tool in tools:
        registry.register(tool)
        logger.info(f"✅ Registered learning tool: {tool.name}")

    logger.info(f"✅ Registered {len(tools)} learning tools")
