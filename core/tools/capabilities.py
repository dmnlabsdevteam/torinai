#!/usr/bin/env python3
"""
Tool Capability System
======================
Defines capabilities that tools provide and enables semantic tool discovery.

Instead of AI calling tools by name, it requests capabilities:
- AI: "I need READ_DATA capability for /var/log/system.log"
- Registry: Finds all tools providing READ_DATA → [ReadFileTool, FetchURLTool, ...]
- Registry: Selects best provider based on context (file path → ReadFileTool)

Benefits:
- Lazy loading: Only load tools providing needed capabilities
- Semantic discovery: AI doesn't need to know exact tool names
- Flexibility: Multiple tools can provide same capability
- Composability: Chain capabilities together intelligently

Author: Torin AI Team
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Set


class Capability(Enum):
    """
    Standard capabilities that tools can provide.

    Organized by domain for clarity. Each capability represents a
    high-level operation that one or more tools can perform.
    """

    # ========== DATA ACCESS CAPABILITIES ==========
    READ_DATA = "read_data"                    # Read data from any source (files, APIs, DBs)
    WRITE_DATA = "write_data"                  # Write data to any destination
    DELETE_DATA = "delete_data"                # Delete data (files, records, etc.)
    MOVE_DATA = "move_data"                    # Move/rename data
    COPY_DATA = "copy_data"                    # Copy/duplicate data
    LIST_DATA = "list_data"                    # List available data (files, records, etc.)
    SEARCH_DATA = "search_data"                # Search through data
    VALIDATE_DATA = "validate_data"            # Validate data format/integrity

    # ========== DATA TRANSFORMATION CAPABILITIES ==========
    PARSE_DATA = "parse_data"                  # Parse structured data (JSON, YAML, CSV, etc.)
    TRANSFORM_DATA = "transform_data"          # Transform data format/structure
    AGGREGATE_DATA = "aggregate_data"          # Aggregate/summarize data
    FILTER_DATA = "filter_data"                # Filter data by criteria
    SORT_DATA = "sort_data"                    # Sort data
    MERGE_DATA = "merge_data"                  # Merge datasets
    COMPRESS_DATA = "compress_data"            # Compress data
    DECOMPRESS_DATA = "decompress_data"        # Decompress data
    ENCRYPT_DATA = "encrypt_data"              # Encrypt data
    DECRYPT_DATA = "decrypt_data"              # Decrypt data

    # ========== CODE CAPABILITIES ==========
    GENERATE_CODE = "generate_code"            # Generate code from specifications
    ANALYZE_CODE = "analyze_code"              # Analyze code quality, complexity, etc.
    REFACTOR_CODE = "refactor_code"            # Refactor existing code
    FORMAT_CODE = "format_code"                # Format code style
    EXECUTE_CODE = "execute_code"              # Execute code (Python, shell, etc.)
    DEBUG_CODE = "debug_code"                  # Debug code issues
    TEST_CODE = "test_code"                    # Run tests on code
    LINT_CODE = "lint_code"                    # Lint code for issues
    DOCUMENT_CODE = "document_code"            # Generate code documentation
    ASSESS_QUALITY = "assess_quality"          # Assess code quality metrics
    ASSESS_COMPLEXITY = "assess_complexity"    # Assess code complexity
    DETECT_ISSUE = "detect_issue"              # Detect code issues and problems
    ANALYZE_DEPENDENCIES = "analyze_dependencies" # Analyze code dependencies

    # ========== EXECUTION CAPABILITIES ==========
    RUN_COMMAND = "run_command"                # Execute shell commands
    MANAGE_PROCESS = "manage_process"          # Manage system processes
    SCHEDULE_TASK = "schedule_task"            # Schedule tasks/cron jobs
    RUN_BACKGROUND_TASK = "run_background_task" # Run tasks in background

    # ========== SEARCH CAPABILITIES ==========
    SEMANTIC_SEARCH = "semantic_search"        # Semantic search with embeddings
    TEXT_SEARCH = "text_search"                # Full-text search (grep, ripgrep)
    PATTERN_SEARCH = "pattern_search"          # Pattern-based search (regex, glob)
    AST_SEARCH = "ast_search"                  # Search code by AST structure

    # ========== COMMUNICATION CAPABILITIES ==========
    SEND_MESSAGE = "send_message"              # Send messages (Slack, email, webhooks)
    RECEIVE_MESSAGE = "receive_message"        # Receive/read messages
    NOTIFY = "notify"                          # Send notifications
    ASK_HUMAN = "ask_human"                    # Request human input/approval

    # ========== DATABASE CAPABILITIES ==========
    QUERY_DATABASE = "query_database"          # Query databases (SQL, NoSQL)
    MODIFY_DATABASE = "modify_database"        # Insert/update/delete records
    BACKUP_DATABASE = "backup_database"        # Backup database
    RESTORE_DATABASE = "restore_database"      # Restore database from backup
    MIGRATE_DATABASE = "migrate_database"      # Run database migrations

    # ========== NETWORK CAPABILITIES ==========
    HTTP_REQUEST = "http_request"              # Make HTTP requests
    DOWNLOAD = "download"                      # Download files/data
    UPLOAD = "upload"                          # Upload files/data
    PARSE_HTML = "parse_html"                  # Parse HTML content
    CHECK_CONNECTIVITY = "check_connectivity"  # Check network connectivity
    DNS_LOOKUP = "dns_lookup"                  # Perform DNS lookups
    WEB_SEARCH = "web_search"                  # Search the live web (Google/Bing/DuckDuckGo)
    FETCH_PAGE = "fetch_page"                    # Fetch and extract readable text from a URL
    BROWSE_WEB = "browse_web"                    # Full browser control via Playwright (JS, clicks, forms)

    # ========== MONITORING CAPABILITIES ==========
    MONITOR_SYSTEM = "monitor_system"          # Monitor system resources (CPU, memory, disk)
    MONITOR_LOGS = "monitor_logs"              # Monitor/parse logs
    MONITOR_METRICS = "monitor_metrics"        # Track metrics
    MONITOR_HEALTH = "monitor_health"          # Check system health
    CREATE_ALERT = "create_alert"              # Create alerts/notifications
    DETECT_ANOMALY = "detect_anomaly"          # Detect anomalies
    TRACE_EXECUTION = "trace_execution"        # Distributed tracing

    # ========== SECURITY CAPABILITIES ==========
    SCAN_SECURITY = "scan_security"            # Security scanning
    DETECT_THREAT = "detect_threat"            # Threat detection
    ANALYZE_THREAT = "analyze_threat"          # Threat intelligence analysis
    BLOCK_THREAT = "block_threat"              # Block IPs, apply WAF rules
    VALIDATE_INPUT = "validate_input"          # Input validation/sanitization
    MANAGE_SECRETS = "manage_secrets"          # Manage secrets/credentials
    HASH_DATA = "hash_data"                    # Hash data
    DETECT_INTRUSION = "detect_intrusion"      # Intrusion detection

    # ========== AI/ML CAPABILITIES ==========
    GENERATE_EMBEDDING = "generate_embedding"  # Generate embeddings
    RUN_INFERENCE = "run_inference"            # Run ML inference
    ANALYZE_SIMILARITY = "analyze_similarity"  # Semantic similarity analysis
    EXTRACT_ENTITIES = "extract_entities"      # Named entity recognition
    SUMMARIZE_TEXT = "summarize_text"          # Text summarization

    # ========== RESEARCH CAPABILITIES ==========
    CONDUCT_RESEARCH = "conduct_research"      # Multi-source research
    SEARCH_ACADEMIC = "search_academic"        # Academic paper search
    ANALYZE_PAPER = "analyze_paper"            # Analyze research papers
    GENERATE_CITATION = "generate_citation"    # Generate citations

    # ========== DOCUMENTATION CAPABILITIES ==========
    GENERATE_DOCS = "generate_docs"            # Generate documentation
    CREATE_DIAGRAM = "create_diagram"          # Create diagrams/visualizations
    VISUALIZE_DATA = "visualize_data"          # Visualize data and metrics
    VISUALIZE = "visualize"                    # General visualization capability
    GENERATE_REPORT = "generate_report"        # Generate reports (PDF, Word, etc.)

    # ========== SYSTEM CAPABILITIES ==========
    GET_SYSTEM_INFO = "get_system_info"        # Get system information
    MANAGE_CONFIG = "manage_config"            # Manage configuration
    MANAGE_DEPENDENCIES = "manage_dependencies" # Manage dependencies/packages
    MANAGE_DOCKER = "manage_docker"            # Manage Docker containers

    # ========== TESTING CAPABILITIES ==========
    RUN_TESTS = "run_tests"                    # Run test suites
    GENERATE_TESTS = "generate_tests"          # Generate test cases
    BENCHMARK = "benchmark"                    # Benchmark performance
    COVERAGE_ANALYSIS = "coverage_analysis"    # Analyze test coverage
    ASSESS_COVERAGE = "assess_coverage"        # Assess test coverage metrics
    FUZZ_TEST = "fuzz_test"                    # Fuzz testing
    MUTATION_TEST = "mutation_test"            # Mutation testing

    # ========== CHAOS ENGINEERING CAPABILITIES ==========
    INJECT_FAILURE = "inject_failure"          # Inject failures for testing
    SIMULATE_LOAD = "simulate_load"            # Simulate load/stress
    TEST_RESILIENCE = "test_resilience"        # Test system resilience

    # ========== HYPOTHESIS TESTING & SCIENTIFIC METHOD ==========
    GENERATE_HYPOTHESIS = "generate_hypothesis"      # Generate testable hypotheses
    DESIGN_EXPERIMENT = "design_experiment"          # Design experiments to test hypotheses
    RUN_EXPERIMENT = "run_experiment"                # Execute experiments
    COLLECT_EVIDENCE = "collect_evidence"            # Gather experimental evidence
    EVALUATE_HYPOTHESIS = "evaluate_hypothesis"      # Evaluate hypothesis against evidence
    REVISE_HYPOTHESIS = "revise_hypothesis"          # Revise hypothesis based on results
    VALIDATE_CLAIM = "validate_claim"                # Validate scientific claims

    # ========== LEARNING & PATTERN EXTRACTION ==========
    EXTRACT_PATTERNS = "extract_patterns"            # Extract patterns from data
    EXTRACT_KNOWLEDGE = "extract_knowledge"          # Extract actionable knowledge from data
    META_LEARN = "meta_learn"                        # Learn about learning itself
    CONSOLIDATE_KNOWLEDGE = "consolidate_knowledge"  # Consolidate learned knowledge
    TRANSFER_LEARNING = "transfer_learning"          # Transfer knowledge across domains
    FEW_SHOT_ADAPT = "few_shot_adapt"                # Few-shot learning adaptation
    CONTINUAL_LEARN = "continual_learn"              # Continuous learning without forgetting
    ANALYZE_FEEDBACK = "analyze_feedback"            # Analyze feedback for improvements
    UPDATE_MENTAL_MODEL = "update_mental_model"      # Update internal mental models

    # ========== REASONING CAPABILITIES ==========
    CAUSAL_REASONING = "causal_reasoning"            # Reason about cause and effect
    DEDUCTIVE_REASONING = "deductive_reasoning"      # Deduce conclusions from premises
    INDUCTIVE_REASONING = "inductive_reasoning"      # Generalize from specific cases
    ABDUCTIVE_REASONING = "abductive_reasoning"      # Inference to best explanation
    ANALOGICAL_REASONING = "analogical_reasoning"    # Reason by analogy
    COUNTERFACTUAL_REASONING = "counterfactual_reasoning"  # Reason about hypotheticals
    TEMPORAL_REASONING = "temporal_reasoning"        # Reason about time and sequences
    SPATIAL_REASONING = "spatial_reasoning"          # Reason about space and geometry
    CONSTRAINT_REASONING = "constraint_reasoning"    # Reason with constraints

    # ========== INNOVATION & EXPLORATION ==========
    EXPLORE_DOMAIN = "explore_domain"                # Explore new knowledge domains
    TRACK_FRONTIER = "track_frontier"                # Track technology frontiers
    VALIDATE_APPROACH = "validate_approach"          # Validate new approaches
    BUILD_PROTOTYPE = "build_prototype"              # Build prototypes

    # ========== AGENTSO SECURITY OPERATIONS ==========
    # Threat Detection & Hunting
    THREAT_HUNT = "threat_hunt"                      # AI-powered threat hunting across SIEM/EDR
    INVESTIGATE_INCIDENT = "investigate_incident"    # Automated incident investigation & timeline building
    CORRELATE_EVENTS = "correlate_events"            # Cross-platform event correlation
    DETECT_APT = "detect_apt"                        # Advanced Persistent Threat detection
    BEHAVIORAL_ANALYSIS = "behavioral_analysis"      # User/entity behavioral analysis (UEBA)
    ANOMALY_DETECTION = "anomaly_detection"          # ML-based anomaly detection

    # Incident Response & Remediation
    AUTO_REMEDIATE = "auto_remediate"                # Automated security remediation
    ISOLATE_HOST = "isolate_host"                    # Quarantine/isolate compromised hosts
    BLOCK_IOC = "block_ioc"                          # Block malicious IOCs (IPs, domains, hashes)
    KILL_PROCESS = "kill_process"                    # Terminate malicious processes
    REVOKE_ACCESS = "revoke_access"                  # Revoke compromised credentials/sessions
    EXECUTE_PLAYBOOK = "execute_playbook"            # Execute incident response playbooks
    WAR_ROOM_MANAGEMENT = "war_room_management"      # Manage incident war rooms & coordination
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"      # AI-powered root cause analysis
    GENERATE_POSTMORTEM = "generate_postmortem"      # Auto-generate incident postmortems

    # Code & Application Security
    SECURITY_CODE_REVIEW = "security_code_review"    # AI-powered code security review
    DEPENDENCY_SCAN = "dependency_scan"              # Supply chain vulnerability scanning
    SECRET_DETECTION = "secret_detection"            # Detect exposed credentials in code
    GENERATE_SECURITY_FIX = "generate_security_fix"  # Auto-generate security patches
    SAST_ANALYSIS = "sast_analysis"                  # Static application security testing
    DAST_ANALYSIS = "dast_analysis"                  # Dynamic application security testing
    CONTAINER_SCAN = "container_scan"                # Container image vulnerability scanning

    # Threat Intelligence
    IOC_ENRICHMENT = "ioc_enrichment"                # Enrich threat indicators with context
    THREAT_ATTRIBUTION = "threat_attribution"        # Threat actor attribution & profiling
    TTP_MAPPING = "ttp_mapping"                      # Map attacks to MITRE ATT&CK TTPs
    INTEL_FUSION = "intel_fusion"                    # Fuse intelligence from multiple sources
    PREDICT_ATTACK = "predict_attack"                # Predictive threat modeling

    # Cloud Security
    CLOUD_REMEDIATION = "cloud_remediation"          # Cloud misconfiguration remediation
    ATTACK_PATH_ANALYSIS = "attack_path_analysis"    # Cloud attack path analysis
    CSPM_SCAN = "cspm_scan"                          # Cloud Security Posture Management
    IAM_ANALYSIS = "iam_analysis"                    # Analyze IAM permissions & policies
    ENFORCE_LEAST_PRIVILEGE = "enforce_least_privilege" # Implement least privilege access

    # Compliance & Governance
    COMPLIANCE_CHECK = "compliance_check"            # Compliance monitoring (SOC2, PCI-DSS, etc.)
    COMPLIANCE_REPORT = "compliance_report"          # Generate compliance reports
    AUDIT_TRAIL = "audit_trail"                      # Track security audit trails
    POLICY_ENFORCEMENT = "policy_enforcement"        # Enforce security policies

    # Security Orchestration
    SECURITY_ORCHESTRATION = "security_orchestration" # Orchestrate multi-tool security workflows
    AUTOMATE_ENRICHMENT = "automate_enrichment"      # Automated threat data enrichment
    COORDINATE_RESPONSE = "coordinate_response"      # Coordinate cross-team incident response

    # Vulnerability Management
    VULN_PRIORITIZATION = "vuln_prioritization"      # AI-powered vulnerability prioritization
    PATCH_MANAGEMENT = "patch_management"            # Automated patch management
    EXPLOIT_PREDICTION = "exploit_prediction"        # Predict exploitability of vulnerabilities

    # Innovation & Technology Synthesis
    SYNTHESIZE_TECHNOLOGY = "synthesize_technology"  # Synthesize new technologies
    IDENTIFY_OPPORTUNITY = "identify_opportunity"    # Identify innovation opportunities
    ASSESS_FEASIBILITY = "assess_feasibility"        # Assess technical feasibility

    # ========== SELF-IMPROVEMENT ==========
    ANALYZE_PERFORMANCE = "analyze_performance"      # Analyze own performance
    IDENTIFY_BOTTLENECK = "identify_bottleneck"      # Identify performance bottlenecks
    OPTIMIZE_COMPONENT = "optimize_component"        # Optimize system components
    OPTIMIZE_STRATEGY = "optimize_strategy"          # Optimize strategies and approaches
    REFACTOR_ARCHITECTURE = "refactor_architecture"  # Refactor system architecture
    EXPAND_CAPABILITY = "expand_capability"          # Expand own capabilities
    UPDATE_STRATEGY = "update_strategy"              # Update strategies
    SELF_DIAGNOSE = "self_diagnose"                  # Self-diagnose issues
    SELF_REPAIR = "self_repair"                      # Self-repair capabilities
    BENCHMARK_CAPABILITY = "benchmark_capability"    # Benchmark capabilities
    ASSESS_CAPABILITY = "assess_capability"          # Assess current capability levels

    # ========== STRATEGIC PLANNING ==========
    LONG_TERM_PLAN = "long_term_plan"                # Long-term strategic planning
    DECOMPOSE_GOAL = "decompose_goal"                # Decompose goals into subtasks
    PRIORITIZE_OBJECTIVES = "prioritize_objectives"  # Prioritize objectives
    ALLOCATE_RESOURCES = "allocate_resources"        # Allocate resources optimally
    ASSESS_RISK = "assess_risk"                      # Assess risks
    CONTINGENCY_PLAN = "contingency_plan"            # Create contingency plans
    TRACK_PROGRESS = "track_progress"                # Track progress toward goals
    REVISE_PLAN = "revise_plan"                      # Revise plans based on feedback
    RECOMMEND_ACTION = "recommend_action"            # Recommend optimal actions

    # ========== META-COGNITION ==========
    SELF_REFLECT = "self_reflect"                    # Self-reflection on reasoning
    ASSESS_CONFIDENCE = "assess_confidence"          # Assess confidence in conclusions
    IDENTIFY_BIAS = "identify_bias"                  # Identify cognitive biases
    CALIBRATE_UNCERTAINTY = "calibrate_uncertainty"  # Calibrate uncertainty estimates
    EXPLAIN_REASONING = "explain_reasoning"          # Explain reasoning process
    CRITIQUE_REASONING = "critique_reasoning"        # Critique own reasoning
    DETECT_CONFUSION = "detect_confusion"            # Detect confusion/uncertainty
    REQUEST_CLARIFICATION = "request_clarification"  # Request clarification

    # ========== KNOWLEDGE MANAGEMENT ==========
    BUILD_KNOWLEDGE_GRAPH = "build_knowledge_graph"  # Build knowledge graphs
    QUERY_KNOWLEDGE = "query_knowledge"              # Query knowledge bases
    UPDATE_BELIEFS = "update_beliefs"                # Update beliefs based on evidence
    RESOLVE_CONTRADICTION = "resolve_contradiction"  # Resolve contradictions
    VALIDATE_KNOWLEDGE = "validate_knowledge"        # Validate knowledge
    FORGET_KNOWLEDGE = "forget_knowledge"            # Prune outdated knowledge
    RETRIEVE_MEMORY = "retrieve_memory"              # Retrieve memories
    CONSOLIDATE_MEMORY = "consolidate_memory"        # Consolidate memories

    # ========== COLLABORATION & TEACHING ==========
    TEACH_CONCEPT = "teach_concept"                  # Teach concepts to others
    LEARN_FROM_HUMAN = "learn_from_human"            # Learn from human feedback
    COORDINATE_AGENTS = "coordinate_agents"          # Coordinate multiple agents
    DELEGATE_TASK = "delegate_task"                  # Delegate tasks
    REQUEST_EXPERTISE = "request_expertise"          # Request expert input
    EXPLAIN_TO_HUMAN = "explain_to_human"            # Explain to humans
    RECEIVE_FEEDBACK = "receive_feedback"            # Receive and process feedback

    # ========== SAFETY & ALIGNMENT ==========
    DETECT_MISALIGNMENT = "detect_misalignment"      # Detect goal misalignment
    VERIFY_SAFETY = "verify_safety"                  # Verify safety properties
    PREDICT_CONSEQUENCES = "predict_consequences"    # Predict action consequences
    ASSESS_ETHICS = "assess_ethics"                  # Assess ethical implications
    LIMIT_CAPABILITY = "limit_capability"            # Self-limit capabilities
    REQUEST_OVERSIGHT = "request_oversight"          # Request human oversight
    VALIDATE_ALIGNMENT = "validate_alignment"        # Validate goal alignment
    MONITOR_DRIFT = "monitor_drift"                  # Monitor objective drift


class RiskLevel(Enum):
    """Risk level for capability operations, integrates with governance system"""
    LOW = "low"                # Safe operations (read files, list data)
    MEDIUM = "medium"          # Moderate risk (write files, run queries)
    HIGH = "high"              # High risk (delete data, modify system)
    CRITICAL = "critical"      # Critical operations (security changes, production deploys)


@dataclass
class CapabilityMetadata:
    """
    Metadata about a specific capability that a tool provides.

    Allows tools to declare not just what they CAN do, but HOW they do it,
    what inputs they need, and what constraints apply.
    """
    capability: Capability
    description: str = ""                      # Human-readable description

    # Input/output constraints
    input_types: List[str] = field(default_factory=list)   # e.g., ["file_path", "url", "database_query"]
    output_types: List[str] = field(default_factory=list)  # e.g., ["text", "json", "binary"]

    # Context constraints (when this capability applies)
    context_matchers: Dict[str, Any] = field(default_factory=dict)  # e.g., {"data_source": "file", "format": "json"}

    # Performance characteristics
    latency: str = "low"                       # low, medium, high
    cost: str = "low"                          # low, medium, high (compute/API costs)
    reliability: str = "high"                  # low, medium, high

    # Governance-integrated safety model (replaces binary requires_approval)
    #: WHAT THE TOOL DECLARES ABOUT ITSELF, per capability.
    #:
    #: This is a CAPABILITY prior, not a reading of an invocation, and the two
    #: must never be confused -- treating a per-tool label as a per-invocation
    #: verdict is what once scored `echo hello` as critical. `run_shell_command`
    #: declares CRITICAL capability; whether THIS call is critical is decided
    #: by `blocking_mode` from the arguments.
    #:
    #: Written 297 times and read zero for a long stretch: its only reader was
    #: `requires_approval()`, which itself had no callers. It is now captured on
    #: every evaluation -- reported in the determination as `capability`, and
    #: used as the prior when no rule matches, where a declaration is the only
    #: thing available.
    risk_level: RiskLevel = RiskLevel.LOW
    approval_level: Optional[str] = None       # Required approval level (e.g., "team_lead", "security_officer")

    # Capability dependencies - what other capabilities are needed
    depends_on: List[Capability] = field(default_factory=list)  # Prerequisites for this capability

    # Priority when multiple providers exist
    priority: int = 0                          # Higher = preferred (0 = default)


@dataclass
class ToolCapabilityProfile:
    """
    Complete capability profile for a tool.

    Describes all capabilities a tool provides with metadata.
    """
    tool_name: str
    capabilities: List[CapabilityMetadata] = field(default_factory=list)

    # Tags for additional categorization
    tags: Set[str] = field(default_factory=set)  # e.g., {"filesystem", "async", "batch"}

    # Resource requirements
    requires_network: bool = False
    requires_filesystem: bool = False
    requires_database: bool = False
    requires_credentials: bool = False

    # Execution characteristics
    supports_batch: bool = False               # Can handle batch operations
    supports_streaming: bool = False           # Can stream results
    is_idempotent: bool = True                # Safe to retry

    def get_capability_names(self) -> Set[Capability]:
        """Get set of capability enum values this tool provides"""
        return {cap.capability for cap in self.capabilities}

    def provides_capability(self, capability: Capability) -> bool:
        """Check if tool provides a specific capability"""
        return capability in self.get_capability_names()

    #: Ordered so "the riskiest thing this tool declares" is well defined.
    _RISK_ORDER = ("low", "medium", "high", "critical")

    def declared_risk(self) -> RiskLevel:
        """The highest risk any of this tool's capabilities declares.

        A tool is as risky as the most dangerous thing it offers; taking a
        minimum or a mean would let one benign capability mask the rest.
        """
        worst = RiskLevel.LOW
        for cap in self.capabilities:
            level = getattr(cap, "risk_level", None) or RiskLevel.LOW
            if (self._RISK_ORDER.index(level.value)
                    > self._RISK_ORDER.index(worst.value)):
                worst = level
        return worst

    def declared_summary(self) -> Dict[str, Any]:
        """What the tool says about itself, in the shape the caller reports.

        Kept apart from the per-invocation reading in `determination()` -- a
        declaration and an observation are different kinds of claim, and the
        agent should be able to tell which it is looking at.
        """
        return {
            "declared_risk": self.declared_risk().value,
            "capabilities": sorted(c.capability.value for c in self.capabilities),
            "approval_levels": sorted({c.approval_level for c in self.capabilities
                                       if c.approval_level}),
            "requires_credentials": bool(self.requires_credentials),
            "requires_network": bool(self.requires_network),
            "requires_filesystem": bool(self.requires_filesystem),
            "requires_database": bool(self.requires_database),
            "is_idempotent": bool(self.is_idempotent),
        }

    def get_capability_metadata(self, capability: Capability) -> Optional[CapabilityMetadata]:
        """Get metadata for a specific capability"""
        for cap in self.capabilities:
            if cap.capability == capability:
                return cap
        return None

    def matches_context(self, capability: Capability, context: Dict[str, Any]) -> bool:
        """
        Check if this tool's capability matches the given context.

        Example:
            context = {"data_source": "file", "file_path": "/var/log/system.log"}
            ReadFileTool.matches_context(Capability.READ_DATA, context) → True
            FetchURLTool.matches_context(Capability.READ_DATA, context) → False
        """
        cap_meta = self.get_capability_metadata(capability)
        if not cap_meta:
            return False

        # If no context matchers defined, matches any context
        if not cap_meta.context_matchers:
            return True

        # Check if all matchers are satisfied
        for key, expected_value in cap_meta.context_matchers.items():
            if key not in context:
                return False

            actual_value = context[key]

            # Handle list of acceptable values
            if isinstance(expected_value, list):
                if actual_value not in expected_value:
                    return False
            # Handle exact match
            elif actual_value != expected_value:
                return False

        return True

    def score_for_context(
        self,
        capability: Capability,
        context: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Score this tool's suitability for a capability in given context.

        Uses weighted scoring instead of binary matching to enable optimization.
        Higher scores indicate better matches.

        Args:
            capability: The capability to score
            context: Context dict with task parameters
            weights: Optional weight overrides. Defaults:
                     {"priority": 1.0, "reliability": 0.5, "latency": -0.3, "cost": -0.2}

        Returns:
            Float score (higher = better). Returns -inf if context doesn't match.

        Example:
            weights = {"priority": 2.0, "reliability": 1.0, "latency": -0.5, "cost": -0.1}
            score = profile.score_for_context(Capability.READ_DATA, context, weights)
        """
        # First check if context matches at all
        if not self.matches_context(capability, context):
            return float('-inf')

        cap_meta = self.get_capability_metadata(capability)
        if not cap_meta:
            return float('-inf')

        # Default weights
        default_weights = {
            "priority": 1.0,      # Tool's declared preference
            "reliability": 0.5,   # How reliable the tool is
            "latency": -0.3,      # Penalty for high latency (negative = lower is better)
            "cost": -0.2          # Penalty for high cost
        }

        # Merge with provided weights
        if weights:
            default_weights.update(weights)
        w = default_weights

        # Calculate component scores
        priority_score = cap_meta.priority * w["priority"]

        # Map reliability to numeric (high=3, medium=2, low=1)
        reliability_map = {"high": 3.0, "medium": 2.0, "low": 1.0}
        reliability_score = reliability_map.get(cap_meta.reliability, 2.0) * w["reliability"]

        # Map latency to numeric penalty (low=1, medium=2, high=3)
        latency_map = {"low": 1.0, "medium": 2.0, "high": 3.0}
        latency_score = latency_map.get(cap_meta.latency, 2.0) * w["latency"]

        # Map cost to numeric penalty (low=1, medium=2, high=3)
        cost_map = {"low": 1.0, "medium": 2.0, "high": 3.0}
        cost_score = cost_map.get(cap_meta.cost, 1.0) * w["cost"]

        # Context-aware adjustments
        context_bonus = 0.0

        # Prefer tools that support batch if context requests batch
        if context.get("batch", False) and self.supports_batch:
            context_bonus += 2.0

        # Prefer tools that support streaming if context requests streaming
        if context.get("streaming", False) and self.supports_streaming:
            context_bonus += 2.0

        # Prefer idempotent tools if context emphasizes safety
        if context.get("require_idempotent", False) and self.is_idempotent:
            context_bonus += 1.0

        # Penalty for missing required resources
        resource_penalty = 0.0
        if context.get("no_network", False) and self.requires_network:
            resource_penalty -= 10.0  # Heavy penalty
        if context.get("no_filesystem", False) and self.requires_filesystem:
            resource_penalty -= 10.0
        if context.get("no_database", False) and self.requires_database:
            resource_penalty -= 10.0

        # Total score
        total_score = (
            priority_score +
            reliability_score +
            latency_score +
            cost_score +
            context_bonus +
            resource_penalty
        )

        return total_score

    def get_capability_dependencies(self, capability: Capability) -> List[Capability]:
        """
        Get all capabilities that this capability depends on.

        Enables automatic capability chaining and dependency resolution.

        Args:
            capability: The capability to get dependencies for

        Returns:
            List of prerequisite capabilities

        Example:
            # CONDUCT_RESEARCH depends on HTTP_REQUEST, PARSE_HTML, SUMMARIZE_TEXT
            deps = profile.get_capability_dependencies(Capability.CONDUCT_RESEARCH)
            # Returns: [Capability.HTTP_REQUEST, Capability.PARSE_HTML, Capability.SUMMARIZE_TEXT]
        """
        cap_meta = self.get_capability_metadata(capability)
        if not cap_meta:
            return []
        return cap_meta.depends_on.copy()

    # requires_approval() REMOVED. It read `CapabilityMetadata.risk_level` to
    # decide whether a capability needed sign-off, and had ZERO callers -- so
    # it described an approval tier that nothing consulted, for a
    # governance-session model that no longer exists. Risk is decided per
    # invocation now, by `unified_governance_trigger_system.blocking_mode`,
    # from evidence about the invocation rather than a static per-capability
    # annotation.


# ========== CAPABILITY HELPERS ==========

def get_capabilities_by_domain(domain: str) -> List[Capability]:
    """
    Get all capabilities for a specific domain.

    Args:
        domain: Domain name (e.g., "DATA ACCESS", "CODE", "SECURITY")

    Returns:
        List of capabilities in that domain
    """
    domain_map = {
        "data_access": [
            Capability.READ_DATA, Capability.WRITE_DATA, Capability.DELETE_DATA,
            Capability.MOVE_DATA, Capability.COPY_DATA, Capability.LIST_DATA,
            Capability.SEARCH_DATA, Capability.VALIDATE_DATA
        ],
        "data_transformation": [
            Capability.PARSE_DATA, Capability.TRANSFORM_DATA, Capability.AGGREGATE_DATA,
            Capability.FILTER_DATA, Capability.SORT_DATA, Capability.MERGE_DATA,
            Capability.COMPRESS_DATA, Capability.DECOMPRESS_DATA,
            Capability.ENCRYPT_DATA, Capability.DECRYPT_DATA
        ],
        "code": [
            Capability.GENERATE_CODE, Capability.ANALYZE_CODE, Capability.REFACTOR_CODE,
            Capability.FORMAT_CODE, Capability.EXECUTE_CODE, Capability.DEBUG_CODE,
            Capability.TEST_CODE, Capability.LINT_CODE, Capability.DOCUMENT_CODE
        ],
        "communication": [
            Capability.SEND_MESSAGE, Capability.RECEIVE_MESSAGE,
            Capability.NOTIFY, Capability.ASK_HUMAN
        ],
        "security": [
            Capability.SCAN_SECURITY, Capability.DETECT_THREAT, Capability.ANALYZE_THREAT,
            Capability.BLOCK_THREAT, Capability.VALIDATE_INPUT, Capability.MANAGE_SECRETS,
            Capability.HASH_DATA, Capability.DETECT_INTRUSION
        ],
        "monitoring": [
            Capability.MONITOR_SYSTEM, Capability.MONITOR_LOGS, Capability.MONITOR_METRICS,
            Capability.MONITOR_HEALTH, Capability.CREATE_ALERT, Capability.DETECT_ANOMALY,
            Capability.TRACE_EXECUTION
        ]
    }

    return domain_map.get(domain.lower(), [])


_GENERIC_CAP_TOKENS = frozenset({
    "data", "code", "get", "run", "manage", "check", "analyze", "assess", "search",
    "detect", "generate", "create", "update", "validate", "monitor", "track", "build",
})

# Developer phrasing → tokens that appear in Capability enum names.
_CAP_SYNONYMS = {
    "pytest": "tests test", "unittest": "tests test", "test": "tests test",
    "tests": "tests test", "testing": "tests test", "spec": "tests test",
    "mypy": "lint code", "flake8": "lint code", "ruff": "lint code",
    "pylint": "lint code", "eslint": "lint code", "lint": "lint code",
    "linting": "lint code", "linter": "lint code", "typecheck": "lint code",
    "todo": "search text pattern", "todos": "search text pattern",
    "fixme": "search text pattern", "grep": "search text pattern",
    "locate": "search text", "where": "search semantic", "find": "search text",
    "git": "command run", "commit": "command run", "push": "command run",
    "pull": "command run", "branch": "command run", "diff": "command run",
    "rebase": "command run", "checkout": "command run", "stash": "command run",
    "shell": "command run execute", "bash": "command run execute",
    "zsh": "command run execute", "terminal": "command run execute",
    "cli": "command run execute", "exec": "command run execute",
    "usb": "system info command", "hardware": "system info command",
    "device": "system info command", "peripheral": "system info command",
    "plugged": "system info command", "connected": "system info command",
    "cpu": "system info performance", "memory": "system info performance",
    "ram": "system info performance", "disk": "system info performance",
    "gpu": "system info performance", "sluggish": "system performance bottleneck",
    "slow": "system performance bottleneck", "hogging": "system process performance",
    "process": "process manage", "processes": "process manage",
    "pid": "process manage", "kill": "process kill manage",
    "refactor": "refactor code", "rename": "refactor code",
    "cleanup": "refactor code", "tidy": "refactor code",
    "mess": "refactor code", "messy": "refactor code",
    "docker": "docker manage", "container": "docker manage",
    "sql": "database query", "query": "database query", "table": "database query",
    "database": "database query", "postgres": "database query",
    "mysql": "database query", "sqlite": "database query",
    "log": "logs monitor", "logs": "logs monitor", "tail": "logs monitor",
    "port": "connectivity network", "dns": "dns lookup", "ping": "connectivity",
    "curl": "http request fetch", "http": "http request fetch",
    "venv": "command system info", "python": "command system info",
    "node": "command system info", "version": "command system info",
    "installed": "command system info", "npm": "command dependencies",
    "slack": "message send notify", "notify": "notify message send",
    "arxiv": "academic paper research", "paper": "academic paper research",
    "research": "research academic", "cve": "security scan threat vulnerability",
    "vulnerability": "security scan threat", "exploit": "security threat",
    "docs": "docs document generate", "readme": "docs document generate",
    "documentation": "docs document generate", "format": "format code",
    "prettier": "format code", "black": "format code",
    "coverage": "coverage assess", "benchmark": "benchmark performance",
    "profile": "performance benchmark", "backup": "backup database",
    "restore": "restore database", "auth": "semantic search",
}


def _lexical_capability_inference(task_lower: str, cap_floor: float = 1.0) -> Dict[Capability, float]:
    """Infer capabilities by token overlap with capability names.

    The regex table above is high precision but low recall — ordinary phrasing
    ("run the tests", "fix the lint errors") matches none of its patterns. This
    scores every Capability by how much of its name the query covers, so plainly
    worded tasks still resolve. Confidence is capped below the regex range so an
    explicit pattern match always outranks a lexical one.
    """
    import re as _re

    words = set(_re.findall(r"[a-z][a-z0-9]{1,}", task_lower))
    expanded = set(words)
    for w in words:
        syn = _CAP_SYNONYMS.get(w)
        if syn:
            expanded.update(syn.split())

    scored: Dict[Capability, float] = {}
    for cap in Capability:
        ctokens = set(cap.value.split("_"))
        overlap = expanded & ctokens
        if not overlap:
            continue
        coverage = len(overlap) / len(ctokens)
        score = 3.0 * len(overlap) + 3.0 * coverage
        if overlap <= _GENERIC_CAP_TOKENS:
            score *= 0.35
        if score >= cap_floor:
            scored[cap] = round(min(score, 7.0), 2)
    return scored


def infer_capability_from_task(task_description: str, threshold: float = 1.0) -> Dict[Capability, float]:
    """
    Infer needed capabilities from a task description with confidence scoring.

    Uses regex patterns and weighted scoring instead of simple substring matching
    to reduce over-triggering and provide confidence levels.

    Args:
        task_description: Natural language task description
        threshold: Minimum confidence score to include (default 1.0)

    Returns:
        Dict mapping capabilities to confidence scores (0-10 scale)

    Example:
        infer_capability_from_task("read the file at /var/log/system.log")
        # Returns: {Capability.READ_DATA: 8.0}

        infer_capability_from_task("generate test data for the database")
        # Returns: {Capability.GENERATE_TESTS: 4.0, Capability.MODIFY_DATABASE: 2.0}
        # Note: Lower scores for ambiguous cases
    """
    import os
    # Fast-init bypass: set TORIN_FAST_INIT=1 to skip regex during tool registration
    # (used by the tool verifier and any context where capability metadata isn't needed)
    if os.environ.get("TORIN_FAST_INIT"):
        return {}

    import re

    task_lower = task_description.lower()
    scores: Dict[Capability, float] = {}

    # Pattern → (Capability, confidence_weight) mappings
    # Uses regex patterns with flexible matching to handle natural language
    pattern_map = [
        # Data access (high confidence for specific patterns)
        (r'\b(read|open|load|view)\s+(\w+\s+)?(file|data)', Capability.READ_DATA, 8.0),
        (r'\b(file|path).*\bread\b', Capability.READ_DATA, 6.0),
        (r'\bread\s', Capability.READ_DATA, 5.0),  # Simple "read" with space after
        (r'\bfetch\s+(\w+\s+)?(from|data)', Capability.READ_DATA, 7.0),
        (r'\b(write|save|persist|store)\s+(\w+\s+)?(file|data)', Capability.WRITE_DATA, 8.0),
        (r'\b(delete|remove|rm)\s+(\w+\s+)?(file|data)', Capability.DELETE_DATA, 8.0),
        (r'\bsearch\s+(for|in|through)', Capability.SEARCH_DATA, 7.0),
        (r'\b(grep|find|locate)\b', Capability.SEARCH_DATA, 6.0),
        (r'\blist\s+(\w+\s+)?(files|directory|contents)', Capability.LIST_DATA, 8.0),

        # Code operations (context-aware)
        (r'\banalyze\s+(\w+\s+)?(code|codebase|implementation)', Capability.ANALYZE_CODE, 8.0),
        (r'\bcode\s+review\b', Capability.ANALYZE_CODE, 9.0),
        (r'\bgenerate\s+(\w+\s+)?(code|function|class|module)', Capability.GENERATE_CODE, 9.0),
        (r'\brefactor\s+(\w+\s+)?(code|function|class)', Capability.REFACTOR_CODE, 9.0),
        (r'\b(run|execute)\s+(\w+\s+)?tests?\b', Capability.TEST_CODE, 9.0),
        (r'\btest\s+(\w+\s+)?(code|function|suite)', Capability.TEST_CODE, 8.0),
        (r'\bformat\s+code\b', Capability.FORMAT_CODE, 9.0),
        (r'\bdebug\b', Capability.DEBUG_CODE, 6.0),

        # Communication (specific)
        (r'\bslack\s+(\w+\s+)?(message|notification)', Capability.SEND_MESSAGE, 10.0),
        (r'\bsend\s+(\w+\s+)?(message|notification|email)', Capability.SEND_MESSAGE, 8.0),
        (r'\b(notify|alert)\s+(\w+\s+)?team\b', Capability.SEND_MESSAGE, 7.0),
        (r'\bask\s+(for\s+)?(approval|clarification|confirmation)', Capability.ASK_HUMAN, 9.0),

        # Execution
        (r'\b(run|execute)\s+(\w+\s+)?(command|shell|bash)', Capability.RUN_COMMAND, 9.0),
        (r'\bshell\s+command\b', Capability.RUN_COMMAND, 8.0),

        # Database (specific patterns)
        (r'\b(query|select|insert|update)\s+(\w+\s+)?(database|db|sql)', Capability.QUERY_DATABASE, 9.0),
        (r'\bsql\s+query\b', Capability.QUERY_DATABASE, 10.0),
        (r'\b(modify|update|insert|delete)\s+(\w+\s+)?(database|records)', Capability.MODIFY_DATABASE, 9.0),

        # Security (high confidence for specific terms)
        (r'\bsecurity\s+scan\b', Capability.SCAN_SECURITY, 10.0),
        (r'\bvulnerability\s+(scan|assessment|check)', Capability.SCAN_SECURITY, 9.0),
        (r'\bscan\s+(for\s+)?(vulnerabilit|injection|xss|sqli)', Capability.SCAN_SECURITY, 9.0),
        (r'\b(sql\s+injection|xss|csrf|injection)\s+(vulnerabilit|attack)', Capability.SCAN_SECURITY, 9.0),
        (r'\bsecurity\s+(audit|check|analysis|assessment)', Capability.SCAN_SECURITY, 8.0),
        (r'\bencrypt\s+', Capability.ENCRYPT_DATA, 9.0),
        (r'\bdecrypt\s+', Capability.DECRYPT_DATA, 9.0),
        (r'\bencryption\b', Capability.ENCRYPT_DATA, 8.0),
        (r'\bthreat\s+(detection|analysis|intelligence)', Capability.DETECT_THREAT, 9.0),
        (r'\bdetect\s+(threat|attack|intrusion|malware)', Capability.DETECT_THREAT, 9.0),
        (r'\bmalware\s+(analysis|detection|scan)', Capability.DETECT_THREAT, 9.0),
        (r'\bsuspicious\s+(file|activity|behavior)', Capability.DETECT_THREAT, 8.0),
        (r'\bintrusion\s+(detection|attempt)', Capability.DETECT_INTRUSION, 9.0),
        (r'\bdetect\s+intrusion', Capability.DETECT_INTRUSION, 10.0),
        (r'\baccess\s+(log|logs)\s+(for\s+)?(suspicious|attack|intrusion)', Capability.DETECT_INTRUSION, 8.0),
        (r'\b(hardcoded|exposed)\s+(secret|key|password|credential|token)', Capability.MANAGE_SECRETS, 9.0),
        (r'\b(secret|api\s+key|credential|password)\s+(scan|search|leak|exposure)', Capability.MANAGE_SECRETS, 9.0),
        (r'\bsearch\s+for\s+(secret|api\s+key|hardcoded)', Capability.MANAGE_SECRETS, 9.0),
        (r'\bsensitive\s+(data|information)\s+(leak|exposure|protection)', Capability.MANAGE_SECRETS, 8.0),
        (r'\bpii\s+(detection|scan|search)', Capability.MANAGE_SECRETS, 8.0),

        # Monitoring
        (r'\bmonitor\s+(\w+\s+)?(system|logs|metrics)', Capability.MONITOR_SYSTEM, 8.0),
        (r'\bobserve\s+(system|health|behavio[u]?r\w*)\b', Capability.MONITOR_SYSTEM, 8.0),
        (r'\bpost.?(deploy|change|upgrade)\s+(health|monitoring|observation)\b', Capability.MONITOR_SYSTEM, 8.0),
        (r'\bparse\s+logs?\b', Capability.MONITOR_LOGS, 7.0),
        (r'\btail\s+(log|logs)\b', Capability.MONITOR_LOGS, 8.0),

        # Network
        (r'\b(http|https)\s+(request|call|fetch)', Capability.HTTP_REQUEST, 9.0),
        (r'\b(search|browse|fetch)\s+(the\s+)?(web|internet|online)\b', Capability.HTTP_REQUEST, 8.0),
        (r'\bdownload\s+(\w+\s+)?(file|data)', Capability.DOWNLOAD, 8.0),
        (r'\bupload\s+(\w+\s+)?(file|data)', Capability.UPLOAD, 8.0),
        (r'\bparse\s+html\b', Capability.PARSE_HTML, 9.0),

        # Research
        (r'\bresearch\s+(\w+\s+)?(topic|paper|literature)', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bresearch\s+(existing|current|available|emerging|cutting.edge|state.of.the.art)', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bresearch\b', Capability.CONDUCT_RESEARCH, 5.0),  # bare "research" verb
        (r'\bsearch\s+(for\s+)?(the\s+)?(latest|recent|current|new)\s+(research|papers?|breakthroughs?|advances?|developments?)', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bacademic\s+(literature|sources?|databases?)\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bweb\s+(search|research)\b', Capability.CONDUCT_RESEARCH, 7.0),
        (r'\bdesign\s+(\w+\s+)?(concept|system|weapon|device)', Capability.CONDUCT_RESEARCH, 6.0),
        (r'\bidentify\s+(\w+\s+)?(gap|capability|opportunity)', Capability.CONDUCT_RESEARCH, 6.0),
        (r'\bsynthesise|synthesize\b', Capability.CONDUCT_RESEARCH, 6.0),
        (r'\bsearch\s+(academic|papers|arxiv)', Capability.SEARCH_ACADEMIC, 9.0),

        # Testing
        (r'\bgenerate\s+tests?\b', Capability.GENERATE_TESTS, 9.0),
        (r'\brun\s+test\s+suite\b', Capability.RUN_TESTS, 10.0),
        (r'\bbenchmark.*\b(performance|code)', Capability.BENCHMARK, 9.0),
        (r'\bprofile\s+(execution|performance)\s+(time|metrics?)\b', Capability.BENCHMARK, 9.0),
        (r'\bprofile.*\b(performance|execution|time)', Capability.ANALYZE_PERFORMANCE, 9.0),

        # Chaos Engineering & Resilience Testing
        (r'\btest\s+.*\b(resilience|behavior)\b', Capability.TEST_RESILIENCE, 10.0),
        (r'\bresilience\s+(test|testing)', Capability.TEST_RESILIENCE, 10.0),
        (r'\bchaos\s+(test|testing|experiment)', Capability.TEST_RESILIENCE, 9.0),
        (r'\binject\s+.*\b(failure|fault|error)', Capability.INJECT_FAILURE, 10.0),
        (r'\bfailure\s+injection\b', Capability.INJECT_FAILURE, 10.0),
        (r'\bnetwork\s+(partition|failure)', Capability.TEST_RESILIENCE, 8.0),
        (r'\bservice\s+(outage|failure)', Capability.TEST_RESILIENCE, 8.0),
        (r'\bhandles?\s+.*\b(outage|failure)', Capability.TEST_RESILIENCE, 7.0),
        (r'\bverify\s+.*\bhandles?\b', Capability.TEST_RESILIENCE, 7.0),
        (r'\bcheck\s+.*\bresilience\b', Capability.TEST_RESILIENCE, 8.0),
        (r'\bresilience\s+(under|during|against)\b', Capability.TEST_RESILIENCE, 8.0),
        (r'\bdatabase\s+(connection\s+)?(loss|failure|outage)', Capability.TEST_RESILIENCE, 7.0),
        (r'\bsimulate\s+(load|stress)', Capability.SIMULATE_LOAD, 9.0),

        # Hypothesis Testing & Scientific Method
        (r'\bgenerate\s+(\w+\s+)?hypothesis\b', Capability.GENERATE_HYPOTHESIS, 10.0),
        (r'\bhypothesis\s+(test|testing|validation)', Capability.EVALUATE_HYPOTHESIS, 9.0),
        (r'\btest\s+(\w+\s+)?hypothesis\b', Capability.EVALUATE_HYPOTHESIS, 9.0),
        (r'\bdesign\s+(\w+\s+)?experiment\b', Capability.DESIGN_EXPERIMENT, 9.0),
        (r'\brun\s+(\w+\s+)?experiment\b', Capability.RUN_EXPERIMENT, 9.0),
        (r'\bcollect\s+(\w+\s+)?evidence\b', Capability.COLLECT_EVIDENCE, 8.0),
        (r'\bvalidate\s+(\w+\s+)?(claim|approach)\b', Capability.VALIDATE_CLAIM, 8.0),

        # Learning & Pattern Extraction
        (r'\bextract\s+(\w+\s+)?patterns?\b', Capability.EXTRACT_PATTERNS, 10.0),
        (r'\bpattern\s+(extraction|recognition)', Capability.EXTRACT_PATTERNS, 9.0),
        (r'\bmeta.?learn', Capability.META_LEARN, 9.0),
        (r'\blearn\s+(about\s+)?learning\b', Capability.META_LEARN, 8.0),
        (r'\bconsolidate\s+(\w+\s+)?knowledge\b', Capability.CONSOLIDATE_KNOWLEDGE, 9.0),
        (r'\btransfer\s+(\w+\s+)?learning\b', Capability.TRANSFER_LEARNING, 9.0),
        (r'\bcontinual\s+(learning|learn)', Capability.CONTINUAL_LEARN, 9.0),
        (r'\banalyze\s+(\w+\s+)?feedback\b', Capability.ANALYZE_FEEDBACK, 9.0),
        (r'\bfeedback\s+(analysis|loop)', Capability.ANALYZE_FEEDBACK, 8.0),

        # Reasoning
        (r'\bcausal\s+(reasoning|relationship|analysis)', Capability.CAUSAL_REASONING, 10.0),
        (r'\banalyze\s+.*\b(cause|causality)', Capability.CAUSAL_REASONING, 9.0),
        (r'\bcause.and.effect\b', Capability.CAUSAL_REASONING, 9.0),
        (r'\broot\s+cause\b', Capability.CAUSAL_REASONING, 8.0),
        (r'\bdetermine\s+.*\bcausing\b', Capability.CAUSAL_REASONING, 8.0),
        (r'\bwhat\'?s\s+causing\b', Capability.CAUSAL_REASONING, 8.0),
        (r'\bidentify\s+.*\bcause\b', Capability.CAUSAL_REASONING, 7.0),
        (r'\banalyze\s+why\b', Capability.CAUSAL_REASONING, 9.0),
        (r'\bwhy\s+\w+\s+(increased|decreased|changed|failed|slow|timing)', Capability.CAUSAL_REASONING, 8.0),
        (r'\bdeductive\s+reasoning\b', Capability.DEDUCTIVE_REASONING, 10.0),
        (r'\binductive\s+reasoning\b', Capability.INDUCTIVE_REASONING, 10.0),
        (r'\babductive\s+reasoning\b', Capability.ABDUCTIVE_REASONING, 10.0),
        (r'\bcounterfactual\s+(reasoning|analysis)', Capability.COUNTERFACTUAL_REASONING, 10.0),
        (r'\bwhat.if\s+(analysis|scenario)', Capability.COUNTERFACTUAL_REASONING, 7.0),

        # Innovation & Exploration
        (r'\btrack\s+(\w+\s+)?(frontier|technology)', Capability.TRACK_FRONTIER, 9.0),
        (r'\btechnology\s+frontier', Capability.TRACK_FRONTIER, 9.0),
        (r'\bfrontier\s+(analysis|research)', Capability.TRACK_FRONTIER, 8.0),
        (r'\bexplore\s+(\w+\s+)?domain\b', Capability.EXPLORE_DOMAIN, 9.0),
        (r'\bdomain\s+exploration\b', Capability.EXPLORE_DOMAIN, 9.0),
        (r'\bvalidate\s+(\w+\s+)?approach\b', Capability.VALIDATE_APPROACH, 8.0),
        (r'\bfeasibility\s+(assessment|analysis)', Capability.ASSESS_FEASIBILITY, 9.0),
        (r'\bassess\s+(\w+\s+)?feasibility\b', Capability.ASSESS_FEASIBILITY, 9.0),

        # Self-Improvement
        (r'\banalyze.*\bperformance\b', Capability.ANALYZE_PERFORMANCE, 9.0),
        (r'\bperformance\s+(analysis|profiling)', Capability.ANALYZE_PERFORMANCE, 8.0),
        (r'\bprofile\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bmeasure\s+.*\b(CPU|memory|performance|usage)', Capability.ANALYZE_PERFORMANCE, 8.0),
        (r'\bmonitor\s+.*\b(CPU|memory|performance)', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\b(CPU|memory)\s+usage\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bidentify\s+(\w+\s+)?bottleneck', Capability.IDENTIFY_BOTTLENECK, 9.0),
        (r'\bbottleneck\s+(analysis|identification)', Capability.IDENTIFY_BOTTLENECK, 9.0),
        (r'\boptimize\s+(\w+\s+)?(component|system)', Capability.OPTIMIZE_COMPONENT, 9.0),
        (r'\bself.improvement\b', Capability.SELF_REPAIR, 9.0),
        (r'\bself.repair\b', Capability.SELF_REPAIR, 10.0),
        (r'\bself.upgrade\b', Capability.SELF_REPAIR, 9.0),
        (r'\b(upgrade|improve)\s+((your|my|own|the)\s+){1,2}(code|codebase|system|implementation|architecture)\b', Capability.SELF_REPAIR, 9.0),
        (r'\bexpand\s+(\w+\s+)?capabilit', Capability.EXPAND_CAPABILITY, 9.0),
        (r'\bcapability\s+expansion\b', Capability.EXPAND_CAPABILITY, 9.0),
        (r'\blive\s+self.upgrade\s+cycle\b', Capability.EXPAND_CAPABILITY, 10.0),
        (r'\bupgrade\s+cycle\b', Capability.EXPAND_CAPABILITY, 8.0),
        (r'\brefactor\s+(\w+\s+)?architecture\b', Capability.REFACTOR_ARCHITECTURE, 9.0),

        # Strategic Planning
        (r'\blong.term\s+(plan|planning)', Capability.LONG_TERM_PLAN, 9.0),
        (r'\bdecompose\s+(\w+\s+)?goal', Capability.DECOMPOSE_GOAL, 9.0),
        (r'\bprioritize\s+(\w+\s+)?(objectives|tasks)', Capability.PRIORITIZE_OBJECTIVES, 9.0),
        (r'\ballocate\s+(\w+\s+)?resources\b', Capability.ALLOCATE_RESOURCES, 9.0),
        (r'\brisk\s+(assessment|analysis)', Capability.ASSESS_RISK, 9.0),
        (r'\bcontingency\s+plan', Capability.CONTINGENCY_PLAN, 9.0),
        (r'\btrack\s+(\w+\s+)?progress\b', Capability.TRACK_PROGRESS, 8.0),

        # Meta-Cognition
        (r'\bself.reflect', Capability.SELF_REFLECT, 10.0),
        (r'\bassess\s+(\w+\s+)?confidence\b', Capability.ASSESS_CONFIDENCE, 9.0),
        (r'\bconfidence\s+(assessment|calibration)', Capability.ASSESS_CONFIDENCE, 9.0),
        (r'\bidentify\s+(\w+\s+)?bias\b', Capability.IDENTIFY_BIAS, 9.0),
        (r'\bbias\s+(detection|identification)', Capability.IDENTIFY_BIAS, 9.0),
        (r'\bcalibrate\s+(\w+\s+)?uncertainty\b', Capability.CALIBRATE_UNCERTAINTY, 9.0),
        (r'\bexplain\s+(\w+\s+)?reasoning\b', Capability.EXPLAIN_REASONING, 8.0),
        (r'\bcritique\s+(\w+\s+)?reasoning\b', Capability.CRITIQUE_REASONING, 9.0),

        # Knowledge Management
        (r'\bknowledge\s+graph\b', Capability.BUILD_KNOWLEDGE_GRAPH, 10.0),
        (r'\bbuild\s+(\w+\s+)?graph\b', Capability.BUILD_KNOWLEDGE_GRAPH, 7.0),
        (r'\bquery\s+(\w+\s+)?knowledge\b', Capability.QUERY_KNOWLEDGE, 9.0),
        (r'\bupdate\s+(\w+\s+)?beliefs?\b', Capability.UPDATE_BELIEFS, 9.0),
        (r'\bresolve\s+(\w+\s+)?contradiction', Capability.RESOLVE_CONTRADICTION, 9.0),
        (r'\bvalidate\s+(\w+\s+)?knowledge\b', Capability.VALIDATE_KNOWLEDGE, 8.0),
        (r'\bretrieve\s+(\w+\s+)?memor', Capability.RETRIEVE_MEMORY, 8.0),
        (r'\bconsolidate\s+(\w+\s+)?memor', Capability.CONSOLIDATE_MEMORY, 9.0),

        # Safety & Alignment
        (r'\bdetect\s+(\w+\s+)?misalignment\b', Capability.DETECT_MISALIGNMENT, 10.0),
        (r'\bverify\s+(\w+\s+)?safety\b', Capability.VERIFY_SAFETY, 9.0),
        (r'\bsafety\s+(verification|check)', Capability.VERIFY_SAFETY, 9.0),
        (r'\bpredict\s+(\w+\s+)?consequences\b', Capability.PREDICT_CONSEQUENCES, 9.0),
        (r'\bconsequence\s+(analysis|prediction)', Capability.PREDICT_CONSEQUENCES, 8.0),
        (r'\bethics?\s+(assessment|analysis)', Capability.ASSESS_ETHICS, 9.0),
        (r'\bmonitor\s+(\w+\s+)?drift\b', Capability.MONITOR_DRIFT, 9.0),
        (r'\bdata\s+drift\b', Capability.MONITOR_DRIFT, 9.0),
        (r'\bobjective\s+drift\b', Capability.MONITOR_DRIFT, 9.0),

        # ── HTTP / External API ──────────────────────────────────────────────
        (r'\brest\s+api\b', Capability.HTTP_REQUEST, 9.0),
        (r'\bapi\s+(call|request|endpoint)\b', Capability.HTTP_REQUEST, 8.0),
        (r'\bgraphql\b', Capability.HTTP_REQUEST, 9.0),
        (r'\bwebsocket\b', Capability.HTTP_REQUEST, 8.0),
        (r'\bcloudflare\b', Capability.HTTP_REQUEST, 7.0),
        (r'\bwaf\s+(rule|firewall)\b', Capability.HTTP_REQUEST, 7.0),
        (r'\bcheck\s+(if\s+)?url\s+(is\s+)?accessible\b', Capability.CHECK_CONNECTIVITY, 8.0),
        (r'\bconnection\s+pool\b', Capability.CHECK_CONNECTIVITY, 7.0),
        (r'\bping\s+(a\s+)?(host|network)\b', Capability.CHECK_CONNECTIVITY, 9.0),
        (r'\bport\s+scan\b', Capability.CHECK_CONNECTIVITY, 9.0),
        (r'\bhealth\s+(check|connection|pool)\b', Capability.CHECK_CONNECTIVITY, 8.0),

        # ── Security alerts / findings (SIEM / connector descriptions) ───────
        (r'\bsecurity\s+(\w+\s+)?(alerts?|events?|incidents?|findings?|cases?)\b', Capability.DETECT_THREAT, 8.0),
        (r'\bthreat\s+(intelligence|indicators?|actors?|intel|pulses?)\b', Capability.DETECT_THREAT, 9.0),
        (r'\bindicators?\s+(of\s+compromise|lookup|attribute)\b', Capability.DETECT_THREAT, 9.0),
        (r'\bioc\b', Capability.DETECT_THREAT, 9.0),
        (r'\bmalware\b', Capability.DETECT_THREAT, 8.0),
        (r'\bbrute\s+force\b', Capability.DETECT_THREAT, 9.0),
        (r'\bzero.day\b', Capability.DETECT_THREAT, 9.0),
        (r'\bthreat\s+hunt(ing)?\b', Capability.DETECT_THREAT, 9.0),
        (r'\bxss\b|\bscript\s+injection\b', Capability.DETECT_THREAT, 8.0),
        (r'\bheuristic\s+(analysis|detection)\b', Capability.DETECT_THREAT, 8.0),
        (r'\bdigital\s+footprint\b', Capability.DETECT_THREAT, 7.0),
        (r'\bvulnerabilit(y|ies)\b', Capability.SCAN_SECURITY, 8.0),
        (r'\bsecurity\s+(\w+\s+)?(hotspots?|recommendations?|scores?|summary)\b', Capability.SCAN_SECURITY, 8.0),
        (r'\bcode\s+(scanning|scan)\s+alerts?\b', Capability.SCAN_SECURITY, 9.0),
        (r'\bsecret\s+scanning\b', Capability.MANAGE_SECRETS, 9.0),
        (r'\bdependabot\b', Capability.SCAN_SECURITY, 9.0),
        (r'\bsiems?\b|\boffenses?\b|\baql\b', Capability.MONITOR_LOGS, 8.0),
        (r'\bsplunk\b|\bspl\b', Capability.MONITOR_LOGS, 8.0),
        (r'\b(elastic|elasticsearch)\b', Capability.SEARCH_DATA, 8.0),
        (r'\b(log|logs)\s+(search|query|analysis)\b', Capability.MONITOR_LOGS, 8.0),
        (r'\bincidents?\s+(response|management|create|update)\b', Capability.TRACK_PROGRESS, 8.0),
        (r'\bget\s+(all|current|historical|active|blocked|available|detailed|comprehensive)\b', Capability.READ_DATA, 7.0),
        (r'\bget\s+(\w+\s+)?(history|records?|info|metadata|status|list|details?|metrics?|score|channels?|users?)\b', Capability.READ_DATA, 7.0),
        (r'\bfetch\s+(\w+\s+)?(data|events?|alerts?|metrics?|logs?|cases?|findings?|investigations?)\b', Capability.READ_DATA, 7.0),
        (r'\bretrieve\s+\w+\s+(from|for|about)\b', Capability.READ_DATA, 7.0),

        # ── Validate data ─────────────────────────────────────────────────────
        (r'\b(calculate|compute)\s+(cryptographic\s+)?(hash|checksum|sha|md5)\b', Capability.VALIDATE_DATA, 8.0),
        (r'\bintegrity\s+verif(y|ication)\b', Capability.VALIDATE_DATA, 9.0),
        (r'\bpath\s+traversal\b', Capability.VALIDATE_DATA, 8.0),
        (r'\brate.?limit\s+(check|exceeded|status)\b', Capability.VALIDATE_DATA, 7.0),

        # ── Generate code ─────────────────────────────────────────────────────
        (r'\badd\s+.*?\btype\s+hint', Capability.GENERATE_CODE, 8.0),
        (r'\badd\s+.*?\b(logging\s+statement|log\s+call)\b', Capability.GENERATE_CODE, 8.0),
        (r'\bgenerate\s+.*?\b(api\s+client|sdk|wrapper|scaffold|boilerplate)\b', Capability.GENERATE_CODE, 9.0),
        (r'\bscaffold\s+(application|structure|project)\b', Capability.GENERATE_CODE, 8.0),

        # ── Document code ─────────────────────────────────────────────────────
        (r'\b(add|generate|improve)\s+.*?\bdocstring\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\badr\b|\barchitecture\s+decision\s+record\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\b(docs?|documentation)\s+(build|site|preview|generate)\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\bapi\s+docs?\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\b(create|generate)\s+.*?\b(architecture|system)\s+diagram\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\b(create|generate)\s+.*?\bflowchart\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\bextract\s+docstrings?\b', Capability.DOCUMENT_CODE, 9.0),

        # ── Analyze code ──────────────────────────────────────────────────────
        (r'\bcyclomatic\s+complexity\b', Capability.ANALYZE_CODE, 10.0),
        (r'\bcode\s+smell\b', Capability.ANALYZE_CODE, 9.0),
        (r'\bpep\s*8\b|\bstyle\s+(compliance|consistency)\b', Capability.ANALYZE_CODE, 8.0),
        (r'\bmypy\b', Capability.ANALYZE_CODE, 8.0),
        (r'\bcount\s+(total\s+)?(lines?|loc)\b', Capability.ANALYZE_CODE, 7.0),
        (r'\bdead\s+code\b|\bunused\s+(function|import)\b', Capability.ANALYZE_CODE, 8.0),

        # ── Assess quality / complexity / issues ──────────────────────────────
        (r'\bpep\s*8\b|\bstyle\s+(compliance|consistency)\b', Capability.ASSESS_QUALITY, 8.0),
        (r'\bcyclomatic\s+complexity\b', Capability.ASSESS_COMPLEXITY, 9.0),
        (r'\bcode\s+smell\b|\banti.?pattern\b|\bdead\s+code\b', Capability.DETECT_ISSUE, 9.0),
        (r'\b(circular|cyclic)\s+import\b', Capability.DETECT_ISSUE, 8.0),

        # ── Lint / test code ──────────────────────────────────────────────────
        (r'\blint\s+(python|code)\b|\blinting\s+errors?\b', Capability.LINT_CODE, 9.0),
        (r'\bsyntax\s+(check|error)\b', Capability.LINT_CODE, 8.0),
        (r'\bmypy\b', Capability.LINT_CODE, 8.0),
        (r'\bfuzz\s+(test|testing)\b', Capability.TEST_CODE, 9.0),
        (r'\bpytest\b', Capability.RUN_TESTS, 9.0),
        (r'\bunittest\b', Capability.RUN_TESTS, 9.0),
        (r'\bgolden\s+test\b', Capability.RUN_TESTS, 9.0),
        (r'\bproperty.based\s+test\b|\bhypothesis\s+(framework|library)\b', Capability.GENERATE_TESTS, 9.0),
        (r'\bgenerate\s+(pytest|test\s+case)\b', Capability.GENERATE_TESTS, 9.0),

        # ── Refactor / format code ────────────────────────────────────────────
        (r'\bconvert.*?\basync(\/await)?\b', Capability.REFACTOR_CODE, 8.0),
        (r'\binline\s+variable\b', Capability.REFACTOR_CODE, 9.0),
        (r'\bextract\s+(a\s+)?method\b', Capability.REFACTOR_CODE, 9.0),
        (r'\brename\s+symbol\b|\bscope.?aware\b', Capability.REFACTOR_CODE, 9.0),
        (r'\brepository.?wide\s+refactor\b', Capability.REFACTOR_CODE, 9.0),
        (r'\bblack\b|\bautopep8\b', Capability.FORMAT_CODE, 8.0),

        # ── Detect anomaly / patterns ─────────────────────────────────────────
        (r'\banomal(y|ous|ies)\b', Capability.DETECT_ANOMALY, 8.0),
        (r'\boutlier\s+(detection|analysis)\b', Capability.DETECT_ANOMALY, 9.0),
        (r'\bz.score\b', Capability.DETECT_ANOMALY, 8.0),
        (r'\bdetect\s+patterns?\b|\bpattern\s+(detect|identif)\b', Capability.EXTRACT_PATTERNS, 8.0),

        # ── Performance / execution ────────────────────────────────────────────
        (r'\bget\s+(cpu|memory|disk|network)\s+(usage|stats|info|statistics)\b', Capability.ANALYZE_PERFORMANCE, 8.0),
        (r'\btraffic\s+(pattern|analysis)\b', Capability.ANALYZE_PERFORMANCE, 8.0),
        (r'\bperformance\s+(bottleneck|issue)\b', Capability.IDENTIFY_BOTTLENECK, 8.0),
        (r'\bdistributed\s+trac(e|ing)\b', Capability.TRACE_EXECUTION, 9.0),
        (r'\bexecution\s+trace\b', Capability.TRACE_EXECUTION, 8.0),
        (r'\bsandbox\b', Capability.EXECUTE_CODE, 8.0),
        (r'\bdeterministic\s+(mode|execution|seed)\b', Capability.EXECUTE_CODE, 9.0),
        (r'\bresource\s+(limit|constraint)\b', Capability.EXECUTE_CODE, 7.0),
        (r'\bkill\s+switch\b', Capability.EXECUTE_CODE, 8.0),
        (r'\bnetwork.?isolat\b', Capability.EXECUTE_CODE, 7.0),

        # ── Manage process ────────────────────────────────────────────────────
        (r'\bclipboard\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bfile\s+(watcher|modified)\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\benvironment\s+variable\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\bservice\s+status\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\bgeo.?block(ing)?\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\bpip\s+install\b|\binstall.*?\bpackage\b', Capability.RUN_COMMAND, 8.0),
        (r'\b(start|stop|restart)\s+(a\s+)?system\s+service\b', Capability.RUN_COMMAND, 8.0),
        (r'\blaunchctl\b|\bsystemctl\b', Capability.RUN_COMMAND, 8.0),
        (r'\bcron\s+(job|schedule)\b', Capability.SCHEDULE_TASK, 8.0),

        # ── Data operations ───────────────────────────────────────────────────
        (r'\bparse\s+(csv|json|yaml|jsonl|parquet|arrow)\b', Capability.PARSE_DATA, 9.0),
        (r'\baggregate\s+(data|by|operations)\b', Capability.AGGREGATE_DATA, 9.0),
        (r'\bdeduplicate\b|\bremove\s+duplicate\b', Capability.FILTER_DATA, 8.0),
        (r'\bpii\s+(scrub|redact|detect)\b', Capability.FILTER_DATA, 8.0),
        (r'\bsort\s+(data|by\s+field|records?)\b', Capability.SORT_DATA, 9.0),
        (r'\bmerge\s+(two\s+)?(datasets?|data)\b', Capability.MERGE_DATA, 9.0),
        (r'\bconvert.*?\b(json|yaml|csv|format)\b', Capability.TRANSFORM_DATA, 8.0),
        (r'\bapply.*?\bpatch\b|\bunified\s+diff\s+patch\b', Capability.TRANSFORM_DATA, 8.0),
        (r'\b(create|make)\s+(a\s+)?new\s+(director|folder)\b', Capability.WRITE_DATA, 8.0),
        (r'\bredis\s+set\b', Capability.WRITE_DATA, 8.0),
        (r'\b(move|rename)\s+(a\s+)?(file|director)\b', Capability.MOVE_DATA, 8.0),
        (r'\bcopy\s+(a\s+)?(file|director)\b', Capability.COPY_DATA, 9.0),
        (r'\bsync\s+(director|files?)\b', Capability.COPY_DATA, 8.0),
        (r'\b(compress|archive|create.*zip)\s+.*?(file|director)\b', Capability.COMPRESS_DATA, 9.0),
        (r'\bextract\s+(files?\s+)?from\s+(archive|zip|tar|compressed)\b', Capability.DECOMPRESS_DATA, 9.0),
        (r'\bdecompress\b', Capability.DECOMPRESS_DATA, 9.0),

        # ── Database ──────────────────────────────────────────────────────────
        (r'\bmysql\b|\bpostgres\b', Capability.QUERY_DATABASE, 7.0),
        (r'\btransaction\s+(wrapper|rollback)\b', Capability.QUERY_DATABASE, 8.0),
        (r'\bdatabase\s+migration\b|\bapply.*?\bmigration\b', Capability.MIGRATE_DATABASE, 9.0),
        (r'\bschema\s+drift\b', Capability.MIGRATE_DATABASE, 8.0),
        (r'\bbackup\s+(mysql|database|db|table)\b', Capability.BACKUP_DATABASE, 9.0),
        (r'\brestore\s+(mysql|database|db|table)\b', Capability.RESTORE_DATABASE, 9.0),

        # ── Network / DNS / Search ────────────────────────────────────────────
        (r'\bdns\s+(lookup|query|resolution)\b', Capability.DNS_LOOKUP, 9.0),
        (r'\bextract\s+(all\s+)?links?\s+(from|in)\s+(html|page|web)\b', Capability.PARSE_HTML, 9.0),
        (r'\bsemantic\s+search\b|\bnatural\s+language.*search\b', Capability.SEMANTIC_SEARCH, 9.0),
        (r'\bgrep\s+(search|for|pattern|text)\b', Capability.TEXT_SEARCH, 9.0),
        (r'\bast\s+(search|symbol|abstract\s+syntax)\b', Capability.AST_SEARCH, 9.0),
        (r'\brename.safe\s+symbol\b|\bsymbol\s+graph\b', Capability.AST_SEARCH, 8.0),
        (r'\bfind\s+todos?\b|\btodo.*comment\b', Capability.PATTERN_SEARCH, 8.0),
        (r'\b(elastic|elasticsearch)\b', Capability.SEARCH_DATA, 8.0),

        # ── Communication / notifications ─────────────────────────────────────
        (r'\bpost\s+(a\s+message|to\s+webhook|slack\s+message)\b', Capability.SEND_MESSAGE, 9.0),
        (r'\bwebhook\b', Capability.SEND_MESSAGE, 7.0),
        (r'\bcreate\s+(a\s+)?(system\s+)?alert\b', Capability.NOTIFY, 9.0),

        # ── Research / academic / AI ──────────────────────────────────────────
        (r'\bstatistical\s+(analysis|test|correlation)\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\barxiv\b|\bdoi\b', Capability.CONDUCT_RESEARCH, 7.0),
        (r'\bbibliograph(y|ic)\b', Capability.GENERATE_CITATION, 9.0),
        (r'\bcitation\s+(style|manager|csl)\b', Capability.GENERATE_CITATION, 9.0),
        (r'\bvector\s+embedding\b|\bembedding.*text\b', Capability.GENERATE_EMBEDDING, 9.0),
        (r'\bml\s+model\s+inference\b|\brun\s+(ml\s+)?inference\b', Capability.RUN_INFERENCE, 9.0),
        (r'\bnamed?\s+entit(y|ies)\b', Capability.EXTRACT_ENTITIES, 9.0),
        (r'\bsemantic\s+similar\b|\bsimilarit(y|ies)\s+between\b', Capability.ANALYZE_SIMILARITY, 9.0),

        # ── Reasoning / math ──────────────────────────────────────────────────
        (r'\bprove\s+(a\s+)?theorem\b|\bformal\s+proof\b', Capability.DEDUCTIVE_REASONING, 9.0),
        (r'\bsmt\s+(solver|backed)\b|\bz3\b', Capability.DEDUCTIVE_REASONING, 9.0),
        (r'\bconstraint\s+(solver|solving|satisfaction)\b', Capability.CONSTRAINT_REASONING, 9.0),
        (r'\blinear\s+(optimization|programming)\b|\bmilp\b|\bpulp\b', Capability.CONSTRAINT_REASONING, 8.0),
        (r'\bmonte\s+carlo\b', Capability.CALIBRATE_UNCERTAINTY, 8.0),
        (r'\bpde\b|\bparabolic\b|\bfinite\s+difference\b', Capability.TEMPORAL_REASONING, 8.0),
        (r'\bstate.space\s+(system|simulation)\b', Capability.TEMPORAL_REASONING, 7.0),

        # ── Experiments / chaos ───────────────────────────────────────────────
        (r'\bchaos\s+experiment\b', Capability.INJECT_FAILURE, 8.0),
        (r'\brollback.*?\b(chaos|experiment)\b', Capability.CONTINGENCY_PLAN, 8.0),
        (r'\bload\s+test\b|\bload.?testing\b', Capability.SIMULATE_LOAD, 9.0),
        (r'\bconcurrent.*?\brequest\b', Capability.SIMULATE_LOAD, 8.0),

        # ── Memory / knowledge / self-improvement ─────────────────────────────
        (r'\bquery\s+memory\b', Capability.RETRIEVE_MEMORY, 9.0),
        (r'\blessons?\s+learned\b', Capability.EXTRACT_KNOWLEDGE, 9.0),
        (r'\bstore\s+(discover|finding|memor)\b|\bsemantic\s+indexing\b', Capability.CONSOLIDATE_MEMORY, 8.0),
        (r'\bskill\s+(gap|capability\s+gap)\b', Capability.ASSESS_CAPABILITY, 9.0),
        (r'\brecommend\s+(training|strategy|action)\b', Capability.RECOMMEND_ACTION, 9.0),
        (r'\blist\s+(all\s+)?running\s+processes\b', Capability.GET_SYSTEM_INFO, 7.0),
        (r'\bget\s+.*?\bprocess\s+(info|details?)\b', Capability.GET_SYSTEM_INFO, 7.0),
        (r'\bscaffold.*?\bapplication\b', Capability.BUILD_PROTOTYPE, 8.0),

        # ── Validate / block / visualize ──────────────────────────────────────
        (r'\bvalidate\s+(email|url|path)\s+(format|address)\b', Capability.VALIDATE_INPUT, 9.0),
        (r'\bblock\s+(ip|address|country|region)\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bdependency\s+graph\b|\bgrafana\b|\bdashboard\s+(config|generat)\b', Capability.VISUALIZE, 8.0),
        (r'\bvisualize\s+(learning|data|progress|metric)\b', Capability.VISUALIZE_DATA, 9.0),
        (r'\banalyze\s+(python\s+)?(project\s+)?dependenc\b', Capability.ANALYZE_DEPENDENCIES, 8.0),
        (r'\b(circular|cyclic)\s+import\b', Capability.ANALYZE_DEPENDENCIES, 9.0),
        (r'\bhash\s+(data|string|text|file)\b|\bsha.?256|sha.?512\b', Capability.HASH_DATA, 9.0),
        (r'\bincident\s+response\b', Capability.DETECT_INTRUSION, 8.0),
        (r'\bbrute\s+force\s+(attack|detection)\b', Capability.DETECT_INTRUSION, 8.0),
        (r'\bgenerate\s+(pytest|test\s+case)\b', Capability.GENERATE_TESTS, 9.0),
        (r'\blist\s+(all\s+)?(available\s+)?scenarios?\b', Capability.QUERY_KNOWLEDGE, 7.0),
        (r'\bschema\s+drift\b', Capability.MIGRATE_DATABASE, 8.0),
        (r'\bgenerate\s+(\w+\s+)*(function|class|module|method)\b', Capability.GENERATE_CODE, 9.0),
        (r'\bimplement\s+(\w+\s+)*(algorithm|function|method)\b', Capability.GENERATE_CODE, 9.0),
        (r'\badd\s+(strategic\s+)?logging\s+statements?\b', Capability.GENERATE_CODE, 8.0),
        (r'\bgenerate\s+(\w+\s+)*code\s+using\b', Capability.GENERATE_CODE, 8.0),
        (r'\bfrom\s+(natural\s+language|specification|description)\s+using\b', Capability.GENERATE_CODE, 9.0),
        (r'\b(add|improve|extract)\s+docstrings?\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\bgenerate\s+(\w+\s+)*readme\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\bgenerate\s+(api\s+docs?|api\s+documentation|documentation)\s+from\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\bgenerate\s+(changelog|release\s+notes?|architecture\s+decision\s+records?)\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\bcreate\s+(technical\s+)?diagrams?\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\bupdate\s+(\w+\s+)*documentation\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\bdeploy\s+(\w+\s+)*documentation\b', Capability.DOCUMENT_CODE, 8.0),
        (r'\b(terminate|kill)\s+(\w+\s+)?process\b', Capability.MANAGE_PROCESS, 9.0),
        (r'\bdesktop\s+notification\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\bkill\s+switch\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bschedule\s+(a\s+)?(recurring\s+)?task\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bget\s+system\s+information\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\bcheck\s+if\s+(\w+\s+)*service\s+is\s+running\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bfiles?\s+have\s+been\s+modified\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\bmodify\s+(json|yaml)\s+config\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\breload\s+(\w+\s+)*config\b', Capability.MANAGE_PROCESS, 7.0),
        (r'\bschedule.*?\bcron\b|\bcron\s+job\b', Capability.RUN_COMMAND, 8.0),
        (r'\bfind\s+(potentially\s+)?unused\s+(functions?|imports?|code)\b', Capability.ANALYZE_CODE, 8.0),
        (r'\blines?\s+by\s+file\s+type\b', Capability.ANALYZE_CODE, 8.0),
        (r'\bcount\s+(code|comment|blank|total)\s+lines?\b', Capability.ANALYZE_CODE, 8.0),
        (r'\binfer\s+schema\s+from\b', Capability.ANALYZE_CODE, 7.0),
        (r'\btest\s+coverage\s+reports?\b', Capability.ANALYZE_CODE, 7.0),
        (r'\bdetect\s+(potential\s+)?performance\s+bottlenecks?\b', Capability.ANALYZE_PERFORMANCE, 8.0),
        (r'\bteam\s+activity\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bteam\s+(health\s+)?metrics?\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\b(cpu|disk|memory|network)\s+(usage|stats|traffic)\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bconduct\s+(\w+\s+)*research\b', Capability.CONDUCT_RESEARCH, 9.0),
        (r'\bsearch\s+(academic|news\s+articles?)\b', Capability.CONDUCT_RESEARCH, 9.0),
        (r'\bscholarly\s+publications?\b', Capability.CONDUCT_RESEARCH, 9.0),
        (r'\bgenerate\s+(\w+\s+)*citations?\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\blatex\s+document\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bvalidate\s+bibliography\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bexecute\s+(\w+\s+)*code\s+in\s+(\w+\s+)*(isolated|sandbox)\b', Capability.EXECUTE_CODE, 9.0),
        (r'\brun\s+python\s+code\b|\bexecute\s+python\b', Capability.EXECUTE_CODE, 9.0),
        (r'\binstall\s+(\w+\s+)*package\b', Capability.EXECUTE_CODE, 8.0),
        (r'\binstall.*?\bpip\b|\bpip\s+install\b', Capability.EXECUTE_CODE, 8.0),
        (r'\bexecute\s+(\w+\s+)*code\s+with\s+enforced\b', Capability.EXECUTE_CODE, 9.0),
        (r'\bexecute\s+(\w+\s+)*code\s+with\s+(comprehensive\s+)?capture\b', Capability.EXECUTE_CODE, 9.0),
        (r'\bautomatically\s+respond\s+to\s+(\w+\s+)*threats?\b', Capability.EXECUTE_CODE, 8.0),
        (r'\bexecute\s+(\w+\s+)*(full\s+)?sandbox\b', Capability.RUN_EXPERIMENT, 9.0),
        (r'\bsandbox\s+(environment|execution)\b', Capability.RUN_EXPERIMENT, 8.0),
        (r'\bdeterministic\s+mode\b|\bexecute\s+deterministic\b', Capability.RUN_EXPERIMENT, 9.0),
        (r'\benforced\s+(cpu|memory|hard)\s+(limits?|timeout)\b', Capability.RUN_EXPERIMENT, 8.0),
        (r'\bmonte\s+carlo\s+simulations?\b', Capability.RUN_EXPERIMENT, 8.0),
        (r'\bsimulate\s+(\w+\s+)*(pde|state.?space|system)\b', Capability.RUN_EXPERIMENT, 8.0),
        (r'\brun\s+(\w+\s+)*chaos\s+experiment\b', Capability.RUN_EXPERIMENT, 9.0),
        (r'\bmigrate\s+code\b', Capability.REFACTOR_CODE, 9.0),
        (r'\bextract\s+(\w+\s+)*method\b', Capability.REFACTOR_CODE, 9.0),
        (r'\binline\s+(a\s+)?variable\b', Capability.REFACTOR_CODE, 9.0),
        (r'\brename\s+(a\s+)?symbol\b', Capability.REFACTOR_CODE, 9.0),
        (r'\brepository.wide\s+refactoring\b', Capability.REFACTOR_CODE, 9.0),
        (r'\boptimize\s+(\w+\s+)*code\b', Capability.REFACTOR_CODE, 8.0),
        (r'\banalyze\s+cause.effect\b', Capability.EXTRACT_PATTERNS, 9.0),
        (r'\bextract\s+named\s+entities?\b', Capability.EXTRACT_PATTERNS, 9.0),
        (r'\bdetect\s+malicious\s+patterns?\b', Capability.EXTRACT_PATTERNS, 9.0),
        (r'\bfind\s+duplicate\s+files?\b', Capability.VALIDATE_DATA, 8.0),
        (r'\bsynchronize\s+(\w+\s+)*from\b', Capability.VALIDATE_DATA, 8.0),
        (r'\brow.level\s+access\s+controls?\b', Capability.VALIDATE_DATA, 8.0),
        (r'\banalyze\s+training\s+data\b', Capability.VALIDATE_DATA, 8.0),
        (r'\bcompile\s+and\s+typecheck\b', Capability.VALIDATE_DATA, 8.0),
        (r'\btypecheck\s+(\w+\s+)*code\b', Capability.VALIDATE_DATA, 8.0),
        (r'\blicense\s+(headers?|attribution)\b', Capability.VALIDATE_DATA, 8.0),
        (r'\bvalidate\s+json\b', Capability.VALIDATE_DATA, 9.0),
        (r'\bget\s+(schema|metadata)\b', Capability.READ_DATA, 8.0),
        (r'\bget\s+value\s+from\b', Capability.READ_DATA, 8.0),
        (r'\bpresence\s+status\b|\bonline.*?presence\b', Capability.READ_DATA, 7.0),
        (r'\bparse\s+log\s+files?\b', Capability.READ_DATA, 8.0),
        (r'\bdecrypt\s+(a\s+)?file\b', Capability.READ_DATA, 7.0),
        (r'\bcreate\s+(a\s+)?new\s+director(y|ies)?\b', Capability.WRITE_DATA, 8.0),
        (r'\bset\s+value\s+in\b', Capability.WRITE_DATA, 8.0),
        (r'\bstore\s+discoveries?\b', Capability.WRITE_DATA, 7.0),
        (r'\bdetect\s+(\w+\s+)*drift\b', Capability.DETECT_ANOMALY, 9.0),
        (r'\bdetect\s+patterns?\s+in\s+system\s+behavior\b', Capability.DETECT_ANOMALY, 9.0),
        (r'\bscan\s+(\w+\s+)*code\s+for\s+(\w+\s+)*(security|vulnerabilit)\b', Capability.DETECT_THREAT, 9.0),
        (r'\bsearch\s+for\s+secrets?\s+(and\s+pii|in\s+code)\b', Capability.DETECT_THREAT, 9.0),
        (r'\bai.powered\s+detection\b', Capability.DETECT_THREAT, 8.0),
        (r'\bgenerate\s+vector\s+embeddings?\b', Capability.TRANSFORM_DATA, 9.0),
        (r'\bapply\s+transformations?\s+to\s+data\b', Capability.TRANSFORM_DATA, 9.0),
        (r'\bconvert\s+(\w+\s+)*to\s+async\b', Capability.TRANSFORM_DATA, 8.0),
        (r'\bprofile\s+execution\s+time\b', Capability.IDENTIFY_BOTTLENECK, 9.0),
        (r'\bidentify\s+(skill|capability)\s+gaps?\b', Capability.IDENTIFY_BOTTLENECK, 8.0),
        (r'\bgenerate\s+testable\s+hypotheses?\b', Capability.DESIGN_EXPERIMENT, 9.0),
        (r'\bgenerate\s+hypothes\w+\b', Capability.GENERATE_HYPOTHESIS, 9.0),
        (r'\btrace\s+(and\s+visualize\s+)?import\s+dependencies?\b', Capability.ANALYZE_DEPENDENCIES, 9.0),
        (r'\bdependency\s+graph\b', Capability.ANALYZE_DEPENDENCIES, 9.0),
        (r'\bexecute\s+sql\s+queries?\b', Capability.QUERY_DATABASE, 9.0),
        (r'\bsql\s+queries?\s+(on|with|in)\b', Capability.QUERY_DATABASE, 9.0),
        (r'\btransaction\s+with\s+automatic\s+rollback\b', Capability.QUERY_DATABASE, 9.0),
        (r'\bsimulate\s+(a\s+)?(pde|state.?space|differential\s+equation)\b', Capability.CAUSAL_REASONING, 8.0),
        (r'\bsimulate\s+(a\s+)?\w+\s+system\s+(dx|dy|using)\b', Capability.CAUSAL_REASONING, 8.0),
        (r'\bget\s+(all\s+)?(currently\s+)?blocked\s+ips?\b', Capability.MONITOR_SYSTEM, 8.0),
        (r'\bget\s+(current\s+)?security\s+metrics?\b', Capability.MONITOR_SYSTEM, 8.0),
        (r'\bcheck\s+rate\s+limit\b', Capability.MONITOR_SYSTEM, 8.0),
        (r'\bremove.*?\bdata\s+brokers?\b', Capability.DELETE_DATA, 8.0),
        (r'\baccount\s+deletion\b', Capability.DELETE_DATA, 8.0),
        (r'\bvisualize\s+(learning\s+)?progress\b', Capability.TRACK_PROGRESS, 9.0),
        (r'\bhistorical\s+blocking\s+records?\b', Capability.TRACK_PROGRESS, 8.0),
        (r'\badd\s+(an?\s+)?internal\s+threat\b', Capability.TRACK_PROGRESS, 7.0),
        (r'\bpredict\s+timeline\s+for\s+(ai\s+capability|breakthrough)\b', Capability.TRACK_FRONTIER, 9.0),
        (r'\bforecast\s+(ai\s+)?capabilities?\b', Capability.ASSESS_FEASIBILITY, 8.0),
        (r'\bself.improvement\s+cycle\b', Capability.EXPAND_CAPABILITY, 9.0),
        (r'\btrigger.*?\bself.improv\w*', Capability.EXPAND_CAPABILITY, 9.0),
        (r'\btrigger.*?\bself.improv\w*', Capability.REFACTOR_ARCHITECTURE, 9.0),
        (r'\btrigger.*?\bself.improv\w*', Capability.OPTIMIZE_COMPONENT, 9.0),
        (r'\bidentify\s+skill\s+(and\s+capability\s+)?gaps?\b', Capability.ASSESS_CAPABILITY, 9.0),
        (r'\brecommend\s+training\s+strategies?\b', Capability.OPTIMIZE_STRATEGY, 9.0),
        (r'\bvalidate\s+file\s+path\b', Capability.VALIDATE_INPUT, 9.0),
        (r'\bpath\s+traversal\s+attack\b', Capability.VALIDATE_INPUT, 9.0),
        (r'\bcompressed\s+archive\b|\bzip\s+or\s+tar\b', Capability.COMPRESS_DATA, 9.0),
        (r'\bextract\s+files\s+from\s+(a\s+)?compressed\b', Capability.DECOMPRESS_DATA, 9.0),
        (r'\bsynchronize.*?\blike\s+rsync\b', Capability.COPY_DATA, 8.0),
        (r'\bsearch\s+codebase\s+semantic\b', Capability.SEMANTIC_SEARCH, 9.0),
        (r'\bsearch\s+for\s+text\s+patterns?\s+in\s+files?\b', Capability.TEXT_SEARCH, 9.0),
        (r'\banalyze\s+(python\s+)?code\s+quality\b', Capability.ASSESS_QUALITY, 9.0),
        (r'\bcode\s+quality\s+\(complexity\b', Capability.ASSESS_QUALITY, 8.0),
        (r'\banalyze\s+(existing\s+)?test\s+coverage\s+reports?\b', Capability.ASSESS_COVERAGE, 9.0),
        (r'\bsearch\s+for\s+secrets?\s+\(api\s+keys\b', Capability.PATTERN_SEARCH, 9.0),
        (r'\bextract\s+(all\s+)?links\s+from\s+(an?\s+)?html\b', Capability.PARSE_HTML, 9.0),
        (r'\bask.*?\bteam.*?\bclarification\b|\bclarification.*?\bteam\b', Capability.ASK_HUMAN, 8.0),
        (r'\breport\s+security\s+(finding|incident)\b', Capability.SEND_MESSAGE, 8.0),
        (r'\bml\s+model\s+inference\b|\brun.*?inference\b', Capability.GENERATE_EMBEDDING, 8.0),
        (r'\bget\s+information\s+about.*?\bai\s+models?\b', Capability.LIST_DATA, 7.0),
        (r'\bget\s+(info|information)\s+about\s+(available\s+)?ai\s+models?\b', Capability.LIST_DATA, 8.0),
        (r'\bcalculate\s+semantic\s+similarity\b', Capability.ANALOGICAL_REASONING, 9.0),
        (r'\bsemantic\s+similarity\s+between\b', Capability.ANALOGICAL_REASONING, 9.0),
        (r'\bextract\s+named\s+entities?\s+\(people\b', Capability.PARSE_DATA, 9.0),
        (r'\bnamed\s+entities?\s+\(people\|organizations?\b', Capability.PARSE_DATA, 9.0),
        (r'\bproperty.based\s+tests?\b|\busing\s+hypothesis\b', Capability.GENERATE_TESTS, 9.0),
        (r'\bcheck\s+(python\s+)?code\s+for\s+syntax\s+errors?\b', Capability.LINT_CODE, 9.0),
        (r'\brun\s+load\s+tests?\b', Capability.SIMULATE_LOAD, 9.0),
        (r'\blocal\s+tests?\s+on\s+http\s+endpoints?\b', Capability.SIMULATE_LOAD, 8.0),
        (r'\brun\s+(code\s+)?coverage\s+analysis\b', Capability.TEST_CODE, 9.0),
        (r'\brun\s+golden\s+tests?\b', Capability.RUN_TESTS, 9.0),
        (r'\bgolden\s+test\s+harness\b', Capability.RUN_TESTS, 9.0),
        (r'\bprove\s+(a\s+)?(logical\s+)?theorem\b', Capability.EXPLAIN_REASONING, 8.0),
        (r'\bprove\s+(a\s+)?(logical\s+)?theorem\b', Capability.VALIDATE_CLAIM, 9.0),
        (r'\bprove\s+(a\s+)?(logical\s+)?theorem\b', Capability.DEDUCTIVE_REASONING, 9.0),
        (r'\bsolve\s+(numeric|boolean|named)?\s*constraints?\b', Capability.CONSTRAINT_REASONING, 9.0),
        (r'\bsolve\s+(numeric|boolean|named)?\s*constraints?\b', Capability.VALIDATE_CLAIM, 8.0),
        (r'\bsolve\s+(linear|mixed.integer)\s+optim\b', Capability.DEDUCTIVE_REASONING, 8.0),
        (r'\bsolve\s+(linear|mixed.integer)\s+optim\b', Capability.ALLOCATE_RESOURCES, 9.0),
        (r'\bsimulate\s+(a\s+)?linear\s+state.?space\b', Capability.PREDICT_CONSEQUENCES, 9.0),
        (r'\bdetect\s+zero.day\b', Capability.PREDICT_CONSEQUENCES, 8.0),
        (r'\bsimulate\s+(a\s+)?1d\s+(parabolic\s+)?pde\b', Capability.SPATIAL_REASONING, 9.0),
        (r'\bparabolic\s+pde\b', Capability.SPATIAL_REASONING, 9.0),
        (r'\brun\s+monte\s+carlo\s+simulations?\b', Capability.INDUCTIVE_REASONING, 9.0),
        (r'\brun\s+monte\s+carlo\s+simulations?\b', Capability.ASSESS_CONFIDENCE, 9.0),
        (r'\bblock\s+(an?\s+)?ip\s+address\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bcreate\s+(custom\s+)?.*?\bwaf\s+rule\b', Capability.UPDATE_STRATEGY, 9.0),
        (r'\bcloudflare\s+waf\b', Capability.UPDATE_STRATEGY, 8.0),
        (r'\banalyze.*?\blogs\s+for\s+security\s+events?\b', Capability.MONITOR_LOGS, 9.0),
        (r'\bexecute\s+(an?\s+)?approved\s+chaos\s+experiment\b', Capability.COLLECT_EVIDENCE, 9.0),
        (r'\bget\s+(the\s+)?current\s+status\s+of\s+(a\s+)?chaos\b', Capability.MONITOR_METRICS, 9.0),
        (r'\brollback\s+(a\s+)?.*?\bchaos\s+experiment\b', Capability.SELF_REPAIR, 9.0),
        (r'\bextract\s+lessons\s+learned\b', Capability.CONSOLIDATE_KNOWLEDGE, 9.0),
        (r'\bstore.*?\bin\s+memory\b|\bmemory\s+with\s+semantic\s+indexing\b', Capability.CONSOLIDATE_KNOWLEDGE, 8.0),
        (r'\blist\s+(all\s+)?running\s+processes?\b', Capability.TRACE_EXECUTION, 8.0),
        (r'\bget\s+(detailed\s+)?information\s+about\s+a\s+process\b', Capability.TRACE_EXECUTION, 8.0),
        (r'\bget\s+(detailed\s+)?information\s+about\s+a\s+process\b', Capability.GET_SYSTEM_INFO, 8.0),
        (r'\bdetect\s+code\s+smells?\b', Capability.DETECT_ISSUE, 9.0),
        (r'\bcheck\s+(if\s+a?\s+)?url\s+is\s+accessible\b', Capability.CHECK_CONNECTIVITY, 9.0),
        (r'\bcheck\s+(if\s+specific\s+)?ports?\s+are\s+open\b', Capability.CHECK_CONNECTIVITY, 9.0),
        (r'\bquery\s+memory\s+system\b', Capability.QUERY_KNOWLEDGE, 8.0),
        (r'\bfilter\s+data\s+based\s+on\b', Capability.FILTER_DATA, 9.0),
        (r'\bdetect\s+and\s+redact\s+pii\b|\bpii\s+scrubbing\b', Capability.FILTER_DATA, 9.0),
        (r'\bgenerate\s+(cryptographically\s+secure\s+)?random\s+password\b', Capability.ENCRYPT_DATA, 8.0),
        (r'\bscan\s+(code\s+)?files\s+for.*?\bexposed\s+secrets?\b', Capability.SCAN_SECURITY, 9.0),
        (r'\bmonitor\s+for\s+intrusion\s+attempts?\b', Capability.SCAN_SECURITY, 9.0),
        (r'\banalyze.*?\bfeedback\s+to\s+identify\s+root\s+causes?\b', Capability.ANALYZE_FEEDBACK, 9.0),
        (r'\bassess\s+risk\b|\brisk\s+assessment\b', Capability.ASSESS_RISK, 8.0),
        (r'\bquery\s+multi.source\s+threat\s+intelligence\b', Capability.ASSESS_RISK, 8.0),
        (r'\bbenchmark\s+(learning|algorithms?|systems?)\b', Capability.BENCHMARK_CAPABILITY, 9.0),
        (r'\bprofile.*?\bmemory\s+usage.*?\bcpu\s+usage\b', Capability.BENCHMARK_CAPABILITY, 8.0),
        (r'\bprofile\s+execution\s+time,\s+memory\b', Capability.BENCHMARK_CAPABILITY, 9.0),
        (r'\bconduct\b.*?\bresearch\b', Capability.CONDUCT_RESEARCH, 9.0),
        (r'\bsearch\s+government\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bvalidate\s+\S+\s+against\s+(a\s+)?(json\s+)?schema\b', Capability.VALIDATE_DATA, 9.0),
        (r'\bvalidate\s+(ssl|tls|ssl.tls|certificate)\b', Capability.VALIDATE_DATA, 9.0),
        (r'\bcreate\s+(a\s+)?chaos\s+experiment\b', Capability.DESIGN_EXPERIMENT, 9.0),
        (r'\bdetect\s+\S+\s+zero.day\b|\bzero.day\s+exploits?\b', Capability.PREDICT_CONSEQUENCES, 9.0),
        (r'\bsolve\b.*?\bconstraints?\b', Capability.CONSTRAINT_REASONING, 9.0),
        (r'\bsolve\b.*?\bconstraints?\b', Capability.VALIDATE_CLAIM, 8.0),
        (r'\bsolve\b.*?\boptimization\b', Capability.ALLOCATE_RESOURCES, 9.0),
        (r'\bsolve\b.*?\boptimization\b', Capability.DEDUCTIVE_REASONING, 8.0),
        (r'\bmodify\b.*?\bconfiguration\s+files?\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bchaos\s+experiment\s+scenarios?\b', Capability.QUERY_KNOWLEDGE, 8.0),
        (r'\blist\s+\S+.*?scenarios?\b', Capability.QUERY_KNOWLEDGE, 7.0),
        (r'\bsearch\s+codebase\b', Capability.SEMANTIC_SEARCH, 9.0),
        (r'\breport\s+security\s+findings?\b', Capability.SEND_MESSAGE, 9.0),
        (r'\bfind\s+(potentially\s+)?unused\b', Capability.DETECT_ISSUE, 8.0),
        (r'\bfix\s+linting\s+errors?\b', Capability.WRITE_DATA, 8.0),
        (r'\brepository.wide\s+refactoring\b', Capability.WRITE_DATA, 8.0),
        (r'\brate\s+limit\b', Capability.MONITOR_SYSTEM, 8.0),
        (r'\bscan\b.*?\bsecrets?\s+and\s+credentials?\b', Capability.DETECT_THREAT, 9.0),
        (r'\bsearch\s+for\s+secrets?\b', Capability.DETECT_THREAT, 9.0),
        (r'\bperformance\s+bottlenecks?\b', Capability.IDENTIFY_BOTTLENECK, 8.0),
        (r'\bidentify\b.*?\b(skill|capability)\s+gaps?\b', Capability.IDENTIFY_BOTTLENECK, 8.0),
        (r'\bpredict\s+timeline\b', Capability.ASSESS_FEASIBILITY, 9.0),
        (r'\bself.improv\w*', Capability.REFACTOR_ARCHITECTURE, 9.0),
        (r'\bself.improv\w*', Capability.OPTIMIZE_COMPONENT, 9.0),
        (r'\bgenerate\b.*?\bhypothes\w+\b', Capability.GENERATE_HYPOTHESIS, 9.0),
        (r'\banalyze\b.*?\bdependencies?\b', Capability.ANALYZE_DEPENDENCIES, 8.0),
        (r'\bget\b.*?\bai\s+models?\b', Capability.GET_SYSTEM_INFO, 7.0),
        (r'\bmigrate\s+code\b', Capability.TRANSFORM_DATA, 8.0),
        (r'\bidentity\s+obfuscation\b', Capability.ENCRYPT_DATA, 8.0),
        (r'\bdata\s+broker\b', Capability.DELETE_DATA, 8.0),
        (r'\banalyze\b.*?\btraining\s+data\b', Capability.DETECT_ANOMALY, 8.0),
        (r'\banalyze\b.*?\btraining\s+data\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bchaos\b.*?\bstatus\b', Capability.TRACK_PROGRESS, 8.0),
        (r'\badd\b.*?\bthreat\s+intelligence\b', Capability.TRACK_PROGRESS, 7.0),
        (r'\banalyze.*?\blogs\b', Capability.TRACK_PROGRESS, 7.0),
        (r'\bpagerduty\b', Capability.TRACK_PROGRESS, 7.0),
        (r'\bbrute\s+force\b', Capability.EXTRACT_PATTERNS, 8.0),
        (r'\banalyze\b.*?\banomal\w+\b', Capability.EXTRACT_PATTERNS, 8.0),
        (r'\bwaf\s+rule\b', Capability.GENERATE_CODE, 7.0),
        (r'\bvalidate\s+(yaml|xml|json\s+schema|schema|certificate|email\s+address|url\s+format|email|url)\b', Capability.VALIDATE_DATA, 9.0),
        (r'\bhash\s+data\b', Capability.VALIDATE_DATA, 9.0),
        (r'\bsanitize\s+(user\s+)?input\b', Capability.VALIDATE_DATA, 9.0),
        (r'\bcheck\s+input\s+for\s+sql\b', Capability.VALIDATE_DATA, 9.0),
        (r'\brate\s+limit\w*\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bgenerate\s+(\w+\s+)*proof\b', Capability.GENERATE_CODE, 9.0),
        (r'\bgenerate\s+(\w+\s+)*design\s+pattern\b', Capability.GENERATE_CODE, 9.0),
        (r'\bscaffold\s+(\w+\s+)*application\b', Capability.GENERATE_CODE, 9.0),
        (r'\bsynthesize\s+(code|from\s+examples?)\b', Capability.GENERATE_CODE, 9.0),
        (r'\bgenerate\s+(mock\s+objects?|test\s+data)\b', Capability.GENERATE_CODE, 8.0),
        (r'\bgenerate\s+(\w+\s+)*password\b', Capability.GENERATE_CODE, 7.0),
        (r'\b(add|improve|extract)\s+(\w+\s+)?docstrings?\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\bgenerate\s+(\w+\s+)*(pdf|word|powerpoint|docx|pptx)\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\bgenerate\s+(\w+\s+)*(pdf|word|powerpoint)\s+(document|presentation)\b', Capability.DOCUMENT_CODE, 9.0),
        (r'\bmodify\s+(json|yaml)\s+configuration\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\breload\s+(\w+\s+)*configuration\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bcheck\s+(\w+\s+)*dependencies\s+are\s+installed\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bupdate\s+system\s+packages?\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bmanage\s+docker\s+containers?\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bunblock\s+(\w+\s+)*ip\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bapply\s+rate\s+limit\w*\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bgeo.block\w*\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bblock\b.*?\bcountry\b', Capability.BLOCK_THREAT, 9.0),
        (r'\brespond\b.*?\bdetected\s+threats?\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bauto\w*\s+respond\b.*?\bthreat\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bpurge\b', Capability.DELETE_DATA, 8.0),
        (r'\bscrub\b', Capability.DELETE_DATA, 8.0),
        (r'\bobliterat\w+\b', Capability.DELETE_DATA, 9.0),
        (r'\b(dmca|gdpr|ccpa)\b', Capability.SEND_MESSAGE, 9.0),
        (r'\btakedown\s+notices?\b', Capability.SEND_MESSAGE, 9.0),
        (r'\bsubmit\b.*?\b(takedown|request)\b', Capability.SEND_MESSAGE, 8.0),
        (r'\bconduct\s+(\w+\s+)*research\b', Capability.CONDUCT_RESEARCH, 9.0),
        (r'\bpublication.quality\s+(graphs?|charts?|visualiz)\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bexport\s+bibliography\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bprovenance\s+anchors?\b|\blink\s+claims?\s+to\s+evidence\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bresearch\s+reproducibility\b', Capability.CONDUCT_RESEARCH, 8.0),
        (r'\bhealth\s+metrics?\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bdisk\s+(space\s+)?usage\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bdistributed\s+trac(ing|e)\b', Capability.ANALYZE_PERFORMANCE, 8.0),
        (r'\bservice\s+level\s+(objectives?|indicators?|slo|sli)\b', Capability.ANALYZE_PERFORMANCE, 8.0),
        (r'\bget\s+(\w+\s+)*security\s+metrics?\b', Capability.ANALYZE_PERFORMANCE, 7.0),
        (r'\bsimulate.*?\b(pde|state.?space)\b', Capability.CAUSAL_REASONING, 8.0),
        (r'\bproactively\s+hunt\b', Capability.CAUSAL_REASONING, 8.0),
        (r'\bhunt\s+(\w+\s+)*threats?\b', Capability.CAUSAL_REASONING, 7.0),
        (r'\b(run|execute)\s+(\w+\s+)*chaos\s+experiment\b', Capability.RUN_EXPERIMENT, 9.0),
        (r'\bexecute\s+(\w+\s+)*code\s+with\s+enforced\b', Capability.RUN_EXPERIMENT, 9.0),
        (r'\bisolate.*?host\b|\bcontain\s+(a\s+)?host\b', Capability.BLOCK_THREAT, 9.0),
        (r'\bremove\s+(\w+\s+)*containment\b|\blift\s+containment\b', Capability.MANAGE_PROCESS, 8.0),
        (r'\bthreat\s+events?\s+from\b', Capability.DETECT_THREAT, 8.0),
        (r'\bcreate\s+(\w+\s+)*threat\s+event\b', Capability.DETECT_THREAT, 8.0),
        (r'\blist\s+repositories?\b', Capability.LIST_DATA, 7.0),
        (r'\b(create|update)\s+(\w+\s+)*(alert|incident)\s+in\b', Capability.TRACK_PROGRESS, 8.0),
        (r'\b(get|list)\s+(\w+\s+)*(workflows?|services?)\s+(from|in)\b', Capability.LIST_DATA, 7.0),
        (r'\bexecute\s+(\w+\s+)*workflow\b', Capability.RUN_COMMAND, 8.0),
        (r'\bsecure\s+score\b', Capability.SCAN_SECURITY, 8.0),
        (r'\bquery\s+(\w+\s+)*metrics?\s+from\s+(database|db)\b', Capability.READ_DATA, 8.0),
        (r'\busing\s+ast\s+analysis\b', Capability.ANALYZE_CODE, 8.0),
        (r'\bstatic\s+security\s+analysis\b', Capability.ANALYZE_CODE, 9.0),
        (r'\bcode\s+(smells?|quality|issues?|anti.patterns?)\b', Capability.ANALYZE_CODE, 8.0),
        (r'\bast\s+(analysis|transformation)\b', Capability.ANALYZE_CODE, 8.0),
        # Improvement / audit patterns
        (r'\b(low.quality|low quality|poor.quality)\s+code\b', Capability.ANALYZE_CODE, 8.0),
        (r'\b(incomplete|broken|low.quality)\s+(code|implementation|logic)\b', Capability.ANALYZE_CODE, 8.0),
        (r'\bimprovement\s+opportunit', Capability.ANALYZE_CODE, 8.0),
        (r'\bareas?\s+(of|for)\s+improvement\b', Capability.ANALYZE_CODE, 8.0),
        (r'\b(analyse|analyze)\s+(the\s+)?(codebase|code|source|repository)\b', Capability.ANALYZE_CODE, 9.0),
        (r'\bcode\s+(review|audit|inspection|quality)\b', Capability.ANALYZE_CODE, 8.0),
        (r'\b(find|identify|locate)\s+(bugs?|issues?|defects?|problems?|flaws?)\b', Capability.ANALYZE_CODE, 7.0),
        (r'\brefactor\b', Capability.ANALYZE_CODE, 7.0),
    ]

    # Apply patterns and accumulate scores
    for pattern, capability, weight in pattern_map:
        if re.search(pattern, task_lower):
            scores[capability] = max(scores.get(capability, 0.0), weight)

    # Fallback: simple keyword matching with lower confidence
    # Only triggers if no high-confidence patterns matched
    # Lexical fallback over capability names. Engaged when the regex table produced
    # nothing, and used to top up thin results — regex scores are left untouched so
    # an explicit pattern match always wins.
    if len(scores) < 3:
        for cap, lex_score in _lexical_capability_inference(task_lower).items():
            weight = lex_score if not scores else lex_score * 0.75
            if weight > scores.get(cap, 0.0):
                scores[cap] = round(weight, 2)

    # Filter by threshold
    filtered = {cap: score for cap, score in scores.items() if score >= threshold}

    return filtered
