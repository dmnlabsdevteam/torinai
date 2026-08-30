#!/usr/bin/env python3
"""
Task Completion Protocol

Multi-layer completion verification system that replaces self-attestation
with externally verifiable completion criteria.

Core Principle: Completion is a SYSTEM PROPERTY, not a model output.

Architecture:
1. Task Spec defines acceptance criteria upfront
2. LLM proposes completion (AWAITING_VERIFICATION)
3. System verifies completion through multiple layers
4. Only system can mark task as VERIFIED

Verification Layers:
- Artifact verification (files, outputs exist)
- Code verification (lint, type check, tests)
- Research verification (sources, coverage, consistency)
- Graph verification (dependencies resolved)
- Completion scoring (multi-factor score >= threshold)
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Callable, Set
import json

# Reality verification — environment-state truth checks (Layer 3.5)
try:
    from .reality_verifier import RealityVerifier
except ImportError:
    RealityVerifier = None  # type: ignore

# Content quality verification — substance and grounding checks (Layer 5.5)
try:
    from .content_quality_verifier import ContentQualityVerifier
except ImportError:
    ContentQualityVerifier = None  # type: ignore

logger = logging.getLogger(__name__)


# ============================================================================
# COMPLETION STATE MACHINE
# ============================================================================

class CompletionState(Enum):
    """
    Task completion states - replaces simple boolean complete.
    
    State Transitions:
    PLANNED -> IN_PROGRESS (execution starts)
    IN_PROGRESS -> AWAITING_VERIFICATION (LLM proposes completion)
    AWAITING_VERIFICATION -> REVISION_REQUESTED (system provides feedback for correction)
    REVISION_REQUESTED -> IN_PROGRESS (agent addresses feedback)
    AWAITING_VERIFICATION -> VERIFIED (system validates all criteria)
    AWAITING_VERIFICATION -> FAILED (validation failed, no retries)
    IN_PROGRESS -> BLOCKED (dependency not met)
    IN_PROGRESS -> FAILED (unrecoverable error)
    BLOCKED -> IN_PROGRESS (dependency resolved)
    
    CRITICAL: Only the validator can transition to VERIFIED.
    """
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"  # LLM proposed completion
    REVISION_REQUESTED = "revision_requested"  # System feedback for iterative correction
    VERIFIED = "verified"  # System confirmed completion
    FAILED = "failed"
    BLOCKED = "blocked"
    PARTIALLY_COMPLETE = "partially_complete"  # Budget exhausted, ≥70% criteria met


class ValidationStrategy(Enum):
    """Validation strategy based on task type"""
    UNIT_TESTS = "unit_tests"  # Run pytest/unit tests
    INTEGRATION_TESTS = "integration_tests"  # Run integration tests
    STATIC_ANALYSIS = "static_analysis"  # Lint + type check
    ARTIFACT_CHECK = "artifact_check"  # Verify files exist
    RESEARCH_VALIDATION = "research_validation"  # Source/coverage check
    GRAPH_RESOLUTION = "graph_resolution"  # Dependency graph check
    MANUAL_REVIEW = "manual_review"  # Requires human approval
    AUTO = "auto"  # System determines based on task type


@dataclass
class AcceptanceCriterion:
    """
    Single acceptance criterion for task completion.
    
    Examples:
    - "Speed tracker implemented" -> artifact_check
    - "Unit tests pass" -> test_result
    - "No lint errors" -> lint_check
    
    hard_gate: If True, this criterion MUST pass regardless of weighted score.
               Failing a hard gate blocks VERIFIED state.
    """
    description: str
    criterion_type: str  # artifact_check, test_result, lint_check, metric_threshold, custom
    target: Optional[str] = None  # File path, test name, metric name
    threshold: Optional[float] = None  # For numeric criteria
    operator: str = ">="  # >, <, ==, >=, <=, contains
    hard_gate: bool = False  # If True, must pass regardless of score blending
    verified: bool = False
    verification_result: Optional[str] = None
    verified_at: Optional[datetime] = None


@dataclass
class TaskCompletionSpec:
    """
    Complete specification for task completion verification.
    
    This must be defined BEFORE task execution, not retroactively.
    """
    # Success criteria - all must pass
    acceptance_criteria: List[AcceptanceCriterion] = field(default_factory=list)
    
    # Required outputs - must exist
    required_artifacts: List[str] = field(default_factory=list)  # File paths or output keys
    
    # Validation strategy
    validation_strategy: ValidationStrategy = ValidationStrategy.AUTO
    
    # Completion score thresholds
    min_completion_score: float = 0.85  # Minimum score to mark verified
    min_confidence: float = 0.7  # Minimum confidence from validation
    
    # Budget constraints
    max_time_seconds: Optional[int] = None
    max_tokens: Optional[int] = None
    max_iterations: Optional[int] = None
    
    # Premature completion gates
    allow_empty_remaining_risks: bool = False  # If False, must explicitly state "none"
    allow_empty_open_questions: bool = False
    allow_empty_assumptions: bool = True   # assumptions is optional in the tool schema
    
    # Graph constraints
    parent_task_id: Optional[str] = None
    child_task_ids: List[str] = field(default_factory=list)
    dependency_task_ids: List[str] = field(default_factory=list)

    # Phase 1: Question-based validation
    # Generated at task-start via LLM from task_description.
    # If empty, LAYER 5.8 generates them on-demand at verify time.
    verification_questions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "acceptance_criteria": [
                {
                    "description": c.description,
                    "type": c.criterion_type,
                    "target": c.target,
                    "threshold": c.threshold,
                    "operator": c.operator,
                    "verified": c.verified
                }
                for c in self.acceptance_criteria
            ],
            "required_artifacts": self.required_artifacts,
            "validation_strategy": self.validation_strategy.value,
            "min_completion_score": self.min_completion_score,
            "min_confidence": self.min_confidence,
            "max_time_seconds": self.max_time_seconds,
            "max_tokens": self.max_tokens,
            "max_iterations": self.max_iterations
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskCompletionSpec":
        """Reconstruct from dictionary"""
        criteria = [
            AcceptanceCriterion(
                description=c.get("description", ""),
                criterion_type=c.get("type", "custom"),
                target=c.get("target"),
                threshold=c.get("threshold"),
                operator=c.get("operator", ">=")
            )
            for c in data.get("acceptance_criteria", [])
        ]
        
        return cls(
            acceptance_criteria=criteria,
            required_artifacts=data.get("required_artifacts", []),
            validation_strategy=ValidationStrategy(data.get("validation_strategy", "auto")),
            min_completion_score=data.get("min_completion_score", 0.85),
            min_confidence=data.get("min_confidence", 0.7),
            max_time_seconds=data.get("max_time_seconds"),
            max_tokens=data.get("max_tokens"),
            max_iterations=data.get("max_iterations")
        )


@dataclass
class CompletionProposal:
    """
    LLM's proposal for completion - subject to verification.
    
    The LLM outputs this instead of just {"status": "complete"}.
    System then verifies each claim.
    
    Field Presence Tracking:
    - _fields_explicitly_set tracks which fields were in the LLM output
    - Required for premature completion detection (empty list vs omitted)
    """
    # What the LLM claims it accomplished
    claimed_outputs: Dict[str, Any] = field(default_factory=dict)
    
    # Summary of work done
    summary: str = ""
    
    # Self-assessed confidence (will be adjusted by verification)
    confidence: float = 0.5
    
    # Explicit acknowledgment of remaining work
    # None = field omitted (invalid), [] = explicitly empty (valid)
    remaining_risks: Optional[List[str]] = None
    open_questions: Optional[List[str]] = None
    assumptions: Optional[List[str]] = None
    
    # Artifacts claimed to be created/modified
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    
    # Artifact integrity verification (sha256 hashes)
    artifact_hashes: Dict[str, str] = field(default_factory=dict)  # {path: sha256}
    
    # Epistemic outputs (hypotheses, beliefs)
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    belief_updates: List[Dict[str, Any]] = field(default_factory=list)
    
    # For research tasks
    sources_consulted: List[str] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)
    
    # Track which fields were explicitly present in LLM output
    _fields_explicitly_set: Set[str] = field(default_factory=set)


@dataclass
class CompletionScore:
    """
    Multi-factor completion score.
    
    completion_score = weighted sum of:
    - artifact_score: Required outputs exist
    - validation_score: Tests pass, lint clean
    - consistency_score: No contradictions in output
    - goal_alignment_score: Output matches task objective
    - resource_adherence_score: Within budget
    """
    artifact_score: float = 0.0
    validation_score: float = 0.0
    consistency_score: float = 0.0
    goal_alignment_score: float = 0.0
    resource_adherence_score: float = 1.0
    
    # Weights (must sum to 1.0)
    ARTIFACT_WEIGHT: float = 0.30
    VALIDATION_WEIGHT: float = 0.30
    CONSISTENCY_WEIGHT: float = 0.15
    GOAL_ALIGNMENT_WEIGHT: float = 0.15
    RESOURCE_WEIGHT: float = 0.10
    
    @property
    def total_score(self) -> float:
        return (
            self.artifact_score * self.ARTIFACT_WEIGHT +
            self.validation_score * self.VALIDATION_WEIGHT +
            self.consistency_score * self.CONSISTENCY_WEIGHT +
            self.goal_alignment_score * self.GOAL_ALIGNMENT_WEIGHT +
            self.resource_adherence_score * self.RESOURCE_WEIGHT
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_score": self.artifact_score,
            "validation_score": self.validation_score,
            "consistency_score": self.consistency_score,
            "goal_alignment_score": self.goal_alignment_score,
            "resource_adherence_score": self.resource_adherence_score,
            "total_score": self.total_score
        }


@dataclass
class VerificationResult:
    """Result of completion verification"""
    state: CompletionState
    score: CompletionScore
    confidence: float
    issues: List[str] = field(default_factory=list)
    criteria_results: Dict[str, bool] = field(default_factory=dict)
    artifacts_verified: Dict[str, bool] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    verification_time_ms: int = 0
    verified_at: datetime = field(default_factory=datetime.now)
    
    # Hard gate failures (must be fixed, cannot be blended away)
    hard_gate_failures: List[str] = field(default_factory=list)
    
    # Criteria completion ratio for PARTIALLY_COMPLETE determination
    criteria_pass_ratio: float = 0.0
    
    # Revision feedback for REVISION_REQUESTED state
    revision_feedback: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/logging"""
        return {
            "state": self.state.value,
            "score": self.score.to_dict(),
            "confidence": self.confidence,
            "issues": self.issues,
            "criteria_results": self.criteria_results,
            "artifacts_verified": self.artifacts_verified,
            "recommendations": self.recommendations,
            "verification_time_ms": self.verification_time_ms,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "hard_gate_failures": self.hard_gate_failures,
            "criteria_pass_ratio": self.criteria_pass_ratio,
            "revision_feedback": self.revision_feedback
        }
    
    def get_revision_prompt(self) -> str:
        """Generate a structured revision prompt for the LLM"""
        if not self.revision_feedback:
            return ""

        prompt_parts = ["REVISION REQUIRED — Your completion proposal was rejected.\n"]

        if self.hard_gate_failures:
            prompt_parts.append("HARD GATE FAILURES (must fix before re-proposing):")
            for failure in self.hard_gate_failures:
                # Strip the raw "Unmatched example findings: [...]" list from grounding
                # failures — the model reads those quoted strings as instructions to paste
                # them literally into the document, which defeats the purpose.
                import re as _re
                _clean = _re.sub(r'\.\s*Unmatched example findings:.*$', '.', failure, flags=_re.DOTALL)
                prompt_parts.append(f"  ❌ {_clean}")
            prompt_parts.append("")

        if self.issues:
            prompt_parts.append("ISSUES TO ADDRESS:")
            for issue in self.issues[:5]:
                prompt_parts.append(f"  • {issue}")
            prompt_parts.append("")

        prompt_parts.append(f"CURRENT SCORE: {self.score.total_score:.2f} (need ≥0.85)")
        prompt_parts.append("SCORE BREAKDOWN:")
        prompt_parts.append(f"  - Artifact: {self.score.artifact_score:.2f}")
        prompt_parts.append(f"  - Validation: {self.score.validation_score:.2f}")
        prompt_parts.append(f"  - Consistency: {self.score.consistency_score:.2f}")
        prompt_parts.append(f"  - Goal Alignment: {self.score.goal_alignment_score:.2f}")
        prompt_parts.append(f"  - Resources: {self.score.resource_adherence_score:.2f}")
        prompt_parts.append("")

        if self.recommendations:
            prompt_parts.append("RECOMMENDATIONS:")
            for rec in self.recommendations:
                prompt_parts.append(f"  → {rec}")
            prompt_parts.append("")

        # ── Actionable WHAT TO DO section based on failure category ──────────
        _all_text = " ".join(self.hard_gate_failures + self.issues).lower()
        what_to_do = []

        if "grounding" in _all_text or "findings appear in" in _all_text:
            what_to_do.append(
                "GROUNDING FIX — Your document does not reflect the actual data from "
                "your web_search results. Fix:\n"
                "  1. Look back at the web_search tool results in your conversation "
                "history — find the actual snippets, facts, statistics, and source "
                "descriptions that were returned.\n"
                "  2. Call write_file with an EXPANDED document (≥1000 words) that "
                "summarizes, paraphrases, or quotes those actual findings in your own "
                "words. Do NOT just list source titles or article names — synthesize "
                "the actual content: what the sources say about the topic.\n"
                "  3. After rewriting, call propose_completion."
            )
        if "placeholder" in _all_text or "todo" in _all_text or "tbd" in _all_text:
            what_to_do.append(
                "PLACEHOLDER FIX — Replace all placeholder text (TODO, TBD, [URL to ...], "
                "'X kilometers') with real, specific content before re-proposing."
            )
        if "stub section" in _all_text or "stub" in _all_text:
            what_to_do.append(
                "STUB SECTION FIX — Expand the thin sections with actual prose paragraphs, "
                "not just bullet points. Each section needs ≥3 sentences of real content."
            )
        if "duplicate" in _all_text:
            what_to_do.append(
                "DUPLICATE SECTION FIX — Remove the duplicate section(s). "
                "The file may have been appended to — rewrite it from scratch with write_file."
            )
        if "remaining_risks" in _all_text or "open_questions" in _all_text:
            what_to_do.append(
                "REQUIRED FIELDS MISSING — Your propose_completion call was incomplete. "
                "Include ALL required fields:\n"
                "  propose_completion({\n"
                "    \"summary\": \"<detailed summary of what was accomplished>\",\n"
                "    \"outputs\": {\"document_path\": \"<icloud path>\"},\n"
                "    \"confidence\": 0.9,\n"
                "    \"remaining_risks\": [],\n"
                "    \"open_questions\": [],\n"
                "    \"key_findings\": \"<main findings>\",\n"
                "    \"sources_consulted\": [\"<url1>\", \"<url2>\"]\n"
                "  })"
            )
        if "capability gap" in _all_text:
            what_to_do.append(
                "CAPABILITY GAP MISSING — Your document must explicitly discuss the "
                "capability gap that the new weapon system addresses. Add a section "
                "titled '## Capability Gap' that names the specific gap."
            )
        if "citation" in _all_text or "reference" in _all_text:
            what_to_do.append(
                "CITATIONS MISSING — Include real, specific references (URLs, paper titles, "
                "organisation names) from your web_search results. Do not fabricate citations."
            )

        # Phase 1: question-based validation feedback
        _unanswered = (self.revision_feedback or {}).get("unanswered_questions", [])
        if _unanswered:
            what_to_do.append(
                "MISSING CONTENT — Verification checked whether your output directly answers "
                "the following task-specific questions.  These were NOT answered:\n"
                + "\n".join(f"  ❓ {q}" for q in _unanswered)
                + "\n\nAdd content that explicitly and concretely addresses each question above, "
                "then call write_file to update the output, and re-propose completion."
            )

        # Phase 2: claim-level grounding feedback
        _ungrounded = (self.revision_feedback or {}).get("ungrounded_claims", [])
        if _ungrounded:
            what_to_do.append(
                "UNGROUNDED CLAIMS — The following factual claims in your output are not "
                "supported by any evidence you actually gathered (web_search results, fetched "
                "pages, tool data) and are not explicitly marked as inference or estimate:\n"
                + "\n".join(f"  ⚠️ {c}" for c in _ungrounded)
                + "\n\nFor each claim above, either:\n"
                "  • Replace it with a claim you can support from your actual research data, OR\n"
                "  • Explicitly label it as an estimate/inference (e.g. 'it is likely that…', "
                "'estimated…', 'based on available data…').\n"
                "Then rewrite the output with write_file and re-propose completion."
            )

        # Phase 3: coverage graph feedback
        _uncovered = (self.revision_feedback or {}).get("uncovered_requirements", [])
        if _uncovered:
            what_to_do.append(
                "INCOMPLETE COVERAGE — The following task requirements are not substantively "
                "addressed in your output (a passing mention does not count — need at least "
                "2–3 sentences of concrete content per requirement):\n"
                + "\n".join(f"  📋 {r}" for r in _uncovered)
                + "\n\nAdd a dedicated section (or expand existing content) that concretely "
                "addresses each requirement above.  Then rewrite with write_file and re-propose."
            )

        # If no specific issues were identified but score is still below threshold,
        # give the model concrete depth/quality actions instead of silence.
        if not what_to_do and self.revision_feedback:
            _req_delta = self.revision_feedback.get("required_delta", 0)
            if _req_delta and _req_delta > 0:
                what_to_do.append(
                    f"QUALITY DEPTH — Score is {self.score.total_score:.2f}, need "
                    f"{self.score.total_score + _req_delta:.2f}. No hard failures, but the "
                    f"document lacks depth. Actions:\n"
                    f"  1. Expand every section with at least 2 additional paragraphs of "
                    f"     specific technical detail — no bullet-only sections.\n"
                    f"  2. Name at least 3 specific real-world systems by full name "
                    f"     (e.g. 'Raytheon Phalanx CIWS', 'Lockheed Martin HIMARS', "
                    f"     'Boeing YAL-1 Airborne Laser') and explain precisely why each "
                    f"     one fails to address the capability gap.\n"
                    f"  3. Replace vague source lines ('Wikipedia: Military technology') with "
                    f"     real URLs from your web_search results.\n"
                    f"  4. Remove any duplicate paragraphs — each section must say something "
                    f"     different from every other section.\n"
                    f"  5. Rewrite with write_file then call propose_completion."
                )

        if what_to_do:
            prompt_parts.append("WHAT TO DO:")
            for action in what_to_do:
                prompt_parts.append(f"  ▶ {action}\n")

        return "\n".join(prompt_parts)


# ============================================================================
# COMPLETION VALIDATOR
# ============================================================================

class TaskCompletionValidator:
    """
    Multi-layer task completion validator.
    
    This is the ONLY component authorized to mark tasks as VERIFIED.
    The LLM can only propose AWAITING_VERIFICATION.
    
    Features:
    - 9 verification layers
    - Hard gate enforcement (criteria that must pass regardless of score)
    - Completion drift detection (rolling failure rate monitoring)
    - Artifact integrity verification (sha256 hashes)
    - Iterative revision feedback
    """
    
    def __init__(self, workspace_root: str = "/Users/stefan/Dominion Labs/TorinAI"):
        self.workspace_root = workspace_root
        # Reality verifier — environment-state truth checks
        self.reality_verifier = (
            RealityVerifier(workspace_root=workspace_root)
            if RealityVerifier is not None
            else None
        )
        # Content quality verifier — document substance and grounding checks
        self.content_quality_verifier = (
            ContentQualityVerifier(workspace_root=workspace_root)
            if ContentQualityVerifier is not None
            else None
        )

        # Verification statistics
        self.stats = {
            "verifications_attempted": 0,
            "verifications_passed": 0,
            "verifications_failed": 0,
            "premature_completions_blocked": 0,
            "dependency_blocks": 0,
            "hard_gate_failures": 0,
            "child_task_blocks": 0,
            "question_validations_run": 0,
            "question_hard_gate_blocks": 0,
            "claim_grounding_validations_run": 0,
            "claim_grounding_hard_gate_blocks": 0,
            "coverage_validations_run": 0,
            "coverage_hard_gate_blocks": 0,
        }
        
        # Completion drift detection
        self._recent_results: List[Tuple[datetime, bool, float]] = []  # (time, passed, score)
        self._drift_window_minutes: int = 60
        self._max_failure_rate: float = 0.40  # Alert if >40% failures
        self._min_samples_for_drift: int = 5
    
    async def initialize(self):
        """Initialize the validator. Completion is verified by deterministic
        reality checks only — no LLM critic (retired 2026-08-28)."""
        logger.info("✅ TaskCompletionValidator initialized")
    
    def get_drift_metrics(self) -> Dict[str, Any]:
        """Get completion drift metrics for monitoring"""
        now = datetime.now()
        cutoff = now.timestamp() - (self._drift_window_minutes * 60)
        
        recent = [(t, p, s) for t, p, s in self._recent_results if t.timestamp() > cutoff]
        
        if len(recent) < self._min_samples_for_drift:
            return {"sufficient_data": False, "samples": len(recent)}
        
        failures = sum(1 for _, p, _ in recent if not p)
        failure_rate = failures / len(recent)
        avg_score = sum(s for _, _, s in recent) / len(recent)
        
        # Check for score degradation trend
        if len(recent) >= 4:
            first_half_avg = sum(s for _, _, s in recent[:len(recent)//2]) / (len(recent)//2)
            second_half_avg = sum(s for _, _, s in recent[len(recent)//2:]) / (len(recent) - len(recent)//2)
            score_trend = second_half_avg - first_half_avg
        else:
            score_trend = 0.0
        
        is_degrading = failure_rate > self._max_failure_rate or score_trend < -0.1
        
        return {
            "sufficient_data": True,
            "samples": len(recent),
            "failure_rate": failure_rate,
            "avg_score": avg_score,
            "score_trend": score_trend,
            "is_degrading": is_degrading,
            "recommendation": self._get_drift_recommendation(failure_rate, score_trend) if is_degrading else None
        }
    
    def _get_drift_recommendation(self, failure_rate: float, score_trend: float) -> str:
        """Generate recommendation for completion drift"""
        if failure_rate > 0.6:
            return "CRITICAL: >60% failure rate. Reduce task complexity immediately."
        elif failure_rate > 0.4:
            return "WARNING: >40% failure rate. Consider reducing max_tokens and increasing validation strictness."
        elif score_trend < -0.15:
            return "Score declining rapidly. Review recent task types for systematic issues."
        else:
            return "Minor degradation detected. Monitor closely."
    
    async def verify_completion(
        self,
        task_id: str,
        task_description: str,
        task_type: str,
        proposal: CompletionProposal,
        spec: TaskCompletionSpec,
        execution_context: Dict[str, Any]
    ) -> VerificationResult:
        """
        Verify task completion through multiple layers.
        
        This is the main entry point for completion verification.
        Returns VerificationResult with final state and detailed scores.
        """
        start_time = datetime.now()
        self.stats["verifications_attempted"] += 1
        
        issues = []
        criteria_results = {}
        artifacts_verified = {}
        hard_gate_failures = []
        
        logger.info(f"🔍 Verifying completion for task {task_id}")
        
        # ====================================================================
        # LAYER 1: Premature Completion Detection
        # ====================================================================
        premature_issues = self._check_premature_completion(proposal, spec)
        if premature_issues:
            self.stats["premature_completions_blocked"] += 1
            logger.warning(f"⚠️  Premature completion blocked: {premature_issues}")
            result = VerificationResult(
                state=CompletionState.REVISION_REQUESTED,
                score=CompletionScore(),
                confidence=0.0,
                issues=premature_issues,
                recommendations=["Address remaining risks and open questions before claiming completion"],
                verification_time_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            result.revision_feedback = {"type": "premature_completion", "issues": premature_issues}
            self._record_result(False, 0.0)
            return result
        
        # ====================================================================
        # LAYER 2: Dependency Graph Verification
        # ====================================================================
        if spec.dependency_task_ids:
            dep_issues = await self._verify_dependencies(spec.dependency_task_ids, execution_context)
            if dep_issues:
                self.stats["dependency_blocks"] += 1
                return VerificationResult(
                    state=CompletionState.BLOCKED,
                    score=CompletionScore(),
                    confidence=0.0,
                    issues=dep_issues,
                    recommendations=["Complete blocking dependencies first"],
                    verification_time_ms=int((datetime.now() - start_time).total_seconds() * 1000)
                )
        
        # ====================================================================
        # LAYER 2.5: Child Task Closure Enforcement
        # ====================================================================
        if spec.child_task_ids:
            child_issues = await self._verify_child_tasks(spec.child_task_ids, execution_context)
            if child_issues:
                self.stats["child_task_blocks"] += 1
                return VerificationResult(
                    state=CompletionState.BLOCKED,
                    score=CompletionScore(),
                    confidence=0.0,
                    issues=child_issues,
                    recommendations=["All child tasks must be VERIFIED before parent can complete"],
                    verification_time_ms=int((datetime.now() - start_time).total_seconds() * 1000)
                )
        
        # ====================================================================
        # LAYER 3: Artifact Verification
        # ====================================================================
        artifact_score, artifact_issues, artifact_results = await self._verify_artifacts(
            proposal, spec
        )
        issues.extend(artifact_issues)
        artifacts_verified.update(artifact_results)

        # ====================================================================
        # LAYER 3.5: Reality Verification — environment state truth checks
        # ====================================================================
        # Runs AFTER the basic artifact list check but BEFORE code validation.
        # Catches: fabricated file paths, uninstalled dependencies, missing
        # processes, and code-outcome claims with no code execution tool calls.
        #
        # _tool_logs and _doc_paths are hoisted here (outside the if-block)
        # so that Layer 5.5 (ContentQualityVerifier) can access them even
        # when RealityVerifier is not available.
        _tool_logs = execution_context.get("tool_execution_logs", [])
        _doc_paths = execution_context.get("output_doc_paths", [])
        if self.reality_verifier:
            _reality = await self.reality_verifier.verify(
                proposal=proposal,
                task_description=task_description,
                task_type=task_type,
                tool_results=_tool_logs,
                output_doc_paths=_doc_paths,
            )
            if _reality.hard_failures:
                hard_gate_failures.extend(
                    f"[REALITY] {f}" for f in _reality.hard_failures
                )
                issues.extend(_reality.hard_failures)
                logger.warning(
                    f"\u26a0\ufe0f  Reality verification: {len(_reality.hard_failures)} hard failure(s): "
                    f"{_reality.hard_failures[:2]}"
                )
            if _reality.warnings:
                issues.extend(
                    f"[REALITY WARNING] {w}" for w in _reality.warnings
                )
            # Blend reality score 50/50 into the artifact score so fabricated
            # claims directly reduce the weighted artifact component.
            artifact_score = (artifact_score + _reality.score) / 2
            logger.info(
                f"\U0001f52c Reality check: passed={_reality.passed}, "
                f"score={_reality.score:.3f}, "
                f"hard_failures={len(_reality.hard_failures)}, "
                f"warnings={len(_reality.warnings)}"
            )

        # ====================================================================
        # LAYER 4: Code Validation (if applicable)
        # ====================================================================
        validation_score = 1.0
        if spec.validation_strategy in [ValidationStrategy.UNIT_TESTS, ValidationStrategy.INTEGRATION_TESTS, 
                                         ValidationStrategy.STATIC_ANALYSIS, ValidationStrategy.AUTO]:
            validation_score, validation_issues = await self._run_code_validation(
                proposal, spec, task_type
            )
            issues.extend(validation_issues)
        
        # ====================================================================
        # LAYER 5: Research Validation (if applicable)
        # ====================================================================
        if task_type.upper() == "RESEARCH" or spec.validation_strategy == ValidationStrategy.RESEARCH_VALIDATION:
            research_score, research_issues = await self._validate_research_output(
                proposal, spec
            )
            # Blend with validation score
            validation_score = (validation_score + research_score) / 2
            issues.extend(research_issues)

        # ====================================================================
        # LAYER 5.5: Content Quality Verification
        # ====================================================================
        # Checks document substance: placeholder text, duplicate sections,
        # stub-only content, tool-grounding (findings must appear in doc),
        # generic ungrounded prose, and task-type-specific quality signals.
        # Runs for ALL task types — hard gates block VERIFIED regardless of score.
        if self.content_quality_verifier:
            _cq = await self.content_quality_verifier.verify(
                proposal=proposal,
                task_description=task_description,
                task_type=task_type,
                tool_results=_tool_logs,
                output_doc_paths=_doc_paths,
            )
            if _cq.hard_failures:
                hard_gate_failures.extend(
                    f"[CONTENT_QUALITY] {f}" for f in _cq.hard_failures
                )
                issues.extend(_cq.hard_failures)
                logger.warning(
                    "⚠️  Content quality: %d hard failure(s): %s",
                    len(_cq.hard_failures), _cq.hard_failures[:2],
                )
            if _cq.warnings:
                issues.extend(
                    f"[CONTENT_QUALITY WARNING] {w}" for w in _cq.warnings
                )
            # Blend content quality score into validation_score so hollow
            # documents directly reduce the weighted validation component.
            validation_score = (validation_score + _cq.score) / 2
            logger.info(
                "📄 Content quality: passed=%s score=%.3f hard=%d warnings=%d",
                _cq.passed, _cq.score,
                len(_cq.hard_failures), len(_cq.warnings),
            )

        # ====================================================================
        # LAYER 5.8: Question-Based Validation
        # Generates task-specific verification questions from the task
        # description (no task-type conditioning) and checks whether the
        # actual output answers them.  Fires for ALL task types.
        # Hard gate: blocks VERIFIED if < 60% of questions are answered.
        # ====================================================================
        # LLM-critic semantic gate (question-based) RETIRED 2026-08-28. It was
        # optional and defaulted to neutral when the critic was absent; completion
        # is verified by the deterministic reality checks above. Neutral value kept
        # for the score blend below.
        _q_score = 1.0
        _unanswered_questions: List[str] = []

        # ====================================================================
        # LAYER 5.9: Claim-Level Grounding
        # Extracts atomic factual claims from the output and requires each to
        # be supported by evidence gathered during execution (tool results) OR
        # explicitly marked as inference.  Anti-gaming by construction: more
        # words → more claims → more burden of proof.
        # Hard gate: blocks VERIFIED if < 50% of claims are grounded.
        # ====================================================================
        # LLM-critic semantic gate (claim grounding) RETIRED 2026-08-28 — optional,
        # neutral when absent; deterministic reality checks above do the grounding
        # that matters (a claimed artifact must exist on disk, code must have run).
        _cg_score = 1.0
        _ungrounded_claims: List[str] = []

        # ====================================================================
        # LAYER 5.95: Coverage Graph
        # Extracts semantic requirements from the task description and checks
        # whether each is substantively addressed in the output.  Avoids
        # brittle keyword matching — works on meaning, not word presence.
        # Hard gate: blocks VERIFIED if < 60% of requirements are covered.
        # ====================================================================
        # LLM-critic semantic gate (coverage) RETIRED 2026-08-28 — optional, neutral
        # when absent; deterministic reality checks above verify the work exists.
        _cv_score = 1.0
        _uncovered_requirements: List[str] = []

        # ====================================================================
        # LAYER 6: Acceptance Criteria Verification (including hard gates)
        # ====================================================================
        criteria_score = 0.0
        criteria_pass_ratio = 0.0
        if spec.acceptance_criteria:
            criteria_score, criteria_issues, criteria_results, hard_gate_issues = await self._verify_acceptance_criteria(
                proposal, spec, execution_context
            )
            issues.extend(criteria_issues)
            hard_gate_failures.extend(hard_gate_issues)
            
            # Calculate pass ratio for PARTIALLY_COMPLETE determination
            passed = sum(1 for v in criteria_results.values() if v)
            criteria_pass_ratio = passed / len(criteria_results) if criteria_results else 0.0
        else:
            criteria_score = 1.0  # No explicit criteria = pass by default
            criteria_pass_ratio = 1.0
        
        # ====================================================================
        # LAYER 7: Goal Alignment Check (via Critic LLM)
        # ====================================================================
        goal_alignment_score = await self._check_goal_alignment(
            task_description, proposal, execution_context
        )
        
        # ====================================================================
        # LAYER 8: Consistency Check
        # ====================================================================
        consistency_score, consistency_issues = self._check_consistency(proposal)
        issues.extend(consistency_issues)
        
        # ====================================================================
        # LAYER 9: Resource Budget Check
        # ====================================================================
        resource_score, resource_issues = self._check_resource_budget(
            spec, execution_context
        )
        issues.extend(resource_issues)
        
        # ====================================================================
        # COMPUTE FINAL SCORE
        # ====================================================================
        score = CompletionScore(
            artifact_score=artifact_score,
            validation_score=(validation_score + criteria_score) / 2,
            consistency_score=consistency_score,
            goal_alignment_score=goal_alignment_score,
            resource_adherence_score=resource_score
        )
        
        # ====================================================================
        # DETERMINE FINAL STATE
        # ====================================================================
        total_score = score.total_score
        confidence = min(proposal.confidence, total_score)  # Clamp by actual score
        
        # HARD GATE CHECK: Any hard gate failure blocks VERIFIED regardless of score
        if hard_gate_failures:
            self.stats["hard_gate_failures"] += 1
            logger.warning(f"❌ Hard gate failures: {hard_gate_failures}")
            final_state = CompletionState.REVISION_REQUESTED
            self.stats["verifications_failed"] += 1
        # HARD-GATE acceptance criteria must all pass — soft (hard_gate=False)
        # criteria only affect the weighted score, not the completion state.
        elif spec.acceptance_criteria and not all(
            criteria_results.get(c.description, True)
            for c in spec.acceptance_criteria
            if c.hard_gate
        ):
            hard_gate_crit = [
                c.description for c in spec.acceptance_criteria
                if c.hard_gate and not criteria_results.get(c.description, True)
            ]
            soft_crit = [
                c.description for c in spec.acceptance_criteria
                if not c.hard_gate and not criteria_results.get(c.description, True)
            ]
            if soft_crit:
                logger.info(f"⚠️  Soft acceptance criteria not met (non-blocking): {soft_crit}")
            logger.warning(f"❌ Hard-gate acceptance criteria not all passed: {hard_gate_crit}")
            final_state = CompletionState.REVISION_REQUESTED
            self.stats["verifications_failed"] += 1
        # Resource exhausted check with proper PARTIALLY_COMPLETE vs FAILED logic
        elif resource_score < 0.5:
            if criteria_pass_ratio >= 0.70 and total_score >= 0.60:
                # ≥70% criteria satisfied, budget exhausted, no blocking issues
                final_state = CompletionState.PARTIALLY_COMPLETE
                logger.info(f"⚠️  Budget exhausted but {criteria_pass_ratio:.0%} criteria met - PARTIALLY_COMPLETE")
            else:
                # Barely did anything and burned budget -> FAILED
                final_state = CompletionState.FAILED
                self.stats["verifications_failed"] += 1
                logger.warning(f"❌ Budget exhausted with only {criteria_pass_ratio:.0%} criteria met - FAILED")
        # Full verification check
        elif total_score >= spec.min_completion_score - 0.001 and confidence >= spec.min_confidence:
            final_state = CompletionState.VERIFIED
            self.stats["verifications_passed"] += 1
        else:
            final_state = CompletionState.REVISION_REQUESTED  # Back to work with feedback
            self.stats["verifications_failed"] += 1
        
        # Generate recommendations
        recommendations = self._generate_recommendations(score, issues, spec)
        
        verification_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # Record for drift detection
        self._record_result(final_state == CompletionState.VERIFIED, total_score)
        
        logger.info(
            f"{'✅' if final_state == CompletionState.VERIFIED else '❌'} "
            f"Verification complete: {final_state.value}, score={total_score:.3f}, "
            f"confidence={confidence:.3f}, issues={len(issues)}, hard_gates_failed={len(hard_gate_failures)}"
        )
        
        # Build revision feedback for non-verified states
        revision_feedback = None
        if final_state in [CompletionState.REVISION_REQUESTED, CompletionState.IN_PROGRESS]:
            revision_feedback = {
                "failed_criteria": [k for k, v in criteria_results.items() if not v],
                "hard_gate_failures": hard_gate_failures,
                "score_breakdown": score.to_dict(),
                "required_delta": spec.min_completion_score - total_score,
                "issues": issues[:5],  # Top 5 issues
                # Phase 1: unanswered questions
                "unanswered_questions": _unanswered_questions,
                # Phase 2: ungrounded claims
                "ungrounded_claims": _ungrounded_claims,
                # Phase 3: uncovered task requirements
                "uncovered_requirements": _uncovered_requirements,
            }
        
        return VerificationResult(
            state=final_state,
            score=score,
            confidence=confidence,
            issues=issues,
            criteria_results=criteria_results,
            artifacts_verified=artifacts_verified,
            recommendations=recommendations,
            verification_time_ms=verification_time,
            hard_gate_failures=hard_gate_failures,
            criteria_pass_ratio=criteria_pass_ratio,
            revision_feedback=revision_feedback
        )
    
    def _record_result(self, passed: bool, score: float):
        """Record verification result for drift detection"""
        self._recent_results.append((datetime.now(), passed, score))
        # Keep only recent results
        cutoff = datetime.now().timestamp() - (self._drift_window_minutes * 60)
        self._recent_results = [(t, p, s) for t, p, s in self._recent_results if t.timestamp() > cutoff]
    
    async def _verify_child_tasks(
        self, child_ids: List[str], execution_context: Dict[str, Any]
    ) -> List[str]:
        """Verify all child tasks are VERIFIED before parent can complete"""
        issues = []
        task_states = execution_context.get("task_states", {})
        
        for child_id in child_ids:
            child_state = task_states.get(child_id)
            if child_state != CompletionState.VERIFIED.value and child_state != "verified":
                issues.append(f"Child task {child_id} not verified (state: {child_state})")
        
        return issues
    
    # ========================================================================
    # VERIFICATION LAYER IMPLEMENTATIONS
    # ========================================================================
    
    def _check_premature_completion(
        self, proposal: CompletionProposal, spec: TaskCompletionSpec
    ) -> List[str]:
        """
        Check for premature completion indicators.
        
        Rules:
        1. If remaining_risks or open_questions are non-empty, completion is blocked
        2. If fields are required, they must be explicitly present (None = omitted = invalid)
        3. Empty list [] is valid, None/omitted is not (prevents field omission)
        """
        issues = []
        
        # Check remaining risks - non-empty blocks completion
        if proposal.remaining_risks:
            issues.append(
                f"Cannot complete: {len(proposal.remaining_risks)} remaining risks: "
                f"{', '.join(str(r) for r in proposal.remaining_risks[:3])}"
            )
        
        # Check open questions - non-empty blocks completion
        if proposal.open_questions:
            issues.append(
                f"Cannot complete: {len(proposal.open_questions)} open questions: "
                f"{', '.join(str(q) for q in proposal.open_questions[:3])}"
            )
        
        # Check field presence (None = omitted, [] = explicitly empty)
        if not spec.allow_empty_remaining_risks:
            if proposal.remaining_risks is None:
                issues.append(
                    "remaining_risks field must be present (use [] if none)"
                )
            elif "remaining_risks" not in proposal._fields_explicitly_set:
                issues.append(
                    "remaining_risks must be explicitly set in proposal"
                )
        
        if not spec.allow_empty_open_questions:
            if proposal.open_questions is None:
                issues.append(
                    "open_questions field must be present (use [] if none)"
                )
            elif "open_questions" not in proposal._fields_explicitly_set:
                issues.append(
                    "open_questions must be explicitly set in proposal"
                )
        
        if not spec.allow_empty_assumptions:
            if proposal.assumptions is None:
                issues.append(
                    "assumptions field must be present (use [] if none)"
                )
            elif "assumptions" not in proposal._fields_explicitly_set:
                issues.append(
                    "assumptions must be explicitly set in proposal"
                )
        
        return issues
    
    async def _verify_dependencies(
        self, dependency_ids: List[str], execution_context: Dict[str, Any]
    ) -> List[str]:
        """Verify all dependency tasks are VERIFIED"""
        issues = []
        
        # Get task statuses from execution context
        task_states = execution_context.get("task_states", {})
        
        for dep_id in dependency_ids:
            dep_state = task_states.get(dep_id)
            if dep_state != CompletionState.VERIFIED.value:
                issues.append(f"Dependency {dep_id} not verified (state: {dep_state})")
        
        return issues
    
    async def _verify_artifacts(
        self, proposal: CompletionProposal, spec: TaskCompletionSpec
    ) -> Tuple[float, List[str], Dict[str, bool]]:
        """
        Verify required artifacts exist and optionally verify integrity via SHA256.
        
        If proposal includes artifact_hashes, we verify file contents match.
        This prevents tampering and false claims.
        """
        issues = []
        results = {}
        
        all_required = set(spec.required_artifacts)
        all_claimed = set(proposal.files_created + proposal.files_modified)
        
        # Check required artifacts
        verified_count = 0
        for artifact in all_required:
            if artifact.startswith("/"):
                path = artifact
            else:
                path = os.path.join(self.workspace_root, artifact)
            
            exists = os.path.exists(path)
            results[artifact] = exists
            
            if exists:
                verified_count += 1
            else:
                issues.append(f"Required artifact not found: {artifact}")
        
        # Check claimed files actually exist
        for file_path in proposal.files_created:
            if file_path.startswith("/"):
                path = file_path
            else:
                path = os.path.join(self.workspace_root, file_path)
            
            if not os.path.exists(path):
                issues.append(f"Claimed file does not exist: {file_path}")
                results[file_path] = False
            else:
                results[file_path] = True
                
                # Verify hash if provided
                if proposal.artifact_hashes and file_path in proposal.artifact_hashes:
                    expected_hash = proposal.artifact_hashes[file_path]
                    actual_hash = self._compute_file_hash(path)
                    if actual_hash != expected_hash:
                        issues.append(f"Hash mismatch for {file_path}: expected {expected_hash[:16]}..., got {actual_hash[:16]}...")
                        results[file_path] = False
        
        # Also verify modified files
        for file_path in proposal.files_modified:
            if file_path.startswith("/"):
                path = file_path
            else:
                path = os.path.join(self.workspace_root, file_path)
            
            if not os.path.exists(path):
                issues.append(f"Modified file does not exist: {file_path}")
                results[file_path] = False
            else:
                results[file_path] = True
                
                # Verify hash if provided
                if proposal.artifact_hashes and file_path in proposal.artifact_hashes:
                    expected_hash = proposal.artifact_hashes[file_path]
                    actual_hash = self._compute_file_hash(path)
                    if actual_hash != expected_hash:
                        issues.append(f"Hash mismatch for {file_path}: content may have changed")
                        results[file_path] = False
        
        # Calculate score
        if all_required:
            score = verified_count / len(all_required)
        elif all_claimed:
            verified = sum(1 for v in results.values() if v)
            score = verified / len(results) if results else 1.0
        else:
            score = 1.0  # No artifacts to verify
        
        return score, issues, results
    
    def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of file contents"""
        import hashlib
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""
    
    async def _run_code_validation(
        self, proposal: CompletionProposal, spec: TaskCompletionSpec, task_type: str
    ) -> Tuple[float, List[str]]:
        """Run code validation (lint, type check, tests)"""
        issues = []
        scores = []
        
        # Get files to validate
        files_to_check = proposal.files_created + proposal.files_modified
        python_files = [f for f in files_to_check if f.endswith(".py")]
        
        if not python_files:
            return 1.0, []  # No Python files to validate
        
        # Syntax check using Python's compile
        for file_path in python_files:
            if file_path.startswith("/"):
                path = file_path
            else:
                path = os.path.join(self.workspace_root, file_path)
            
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        source = f.read()
                    compile(source, path, "exec")
                    scores.append(1.0)
                except SyntaxError as e:
                    issues.append(f"Syntax error in {file_path}: {e}")
                    scores.append(0.0)
                except Exception as e:
                    issues.append(f"Error reading {file_path}: {e}")
                    scores.append(0.5)
        
        # Run tests if strategy requires it
        if spec.validation_strategy in [ValidationStrategy.UNIT_TESTS, ValidationStrategy.INTEGRATION_TESTS]:
            test_score, test_issues = await self._run_tests(spec)
            scores.append(test_score)
            issues.extend(test_issues)
        
        return sum(scores) / len(scores) if scores else 1.0, issues
    
    async def _run_tests(self, spec: TaskCompletionSpec) -> Tuple[float, List[str]]:
        """
        Run pytest for test validation.
        
        FIXED: Actually runs tests, not just collects them.
        Uses -q --tb=short for concise output.
        """
        issues = []
        
        try:
            # FIXED: Actually run tests (removed --collect-only)
            result = subprocess.run(
                ["python", "-m", "pytest", "-q", "--tb=short", "-x"],  # -x stops on first failure
                capture_output=True,
                text=True,
                timeout=120,  # Increased timeout for actual test execution
                cwd=self.workspace_root
            )
            
            if result.returncode == 0:
                # Parse test count from output
                # Example: "10 passed in 1.23s"
                import re
                match = re.search(r'(\d+) passed', result.stdout)
                passed_count = int(match.group(1)) if match else 0
                logger.info(f"✅ Tests passed: {passed_count}")
                return 1.0, []
            elif result.returncode == 5:
                # No tests collected - not necessarily a failure for non-test tasks
                return 0.8, ["No tests found to run"]
            else:
                # Tests failed
                # Extract failure summary
                stderr_excerpt = result.stderr[:300] if result.stderr else ""
                stdout_excerpt = result.stdout[:500] if result.stdout else ""
                issues.append(f"Tests failed: {stdout_excerpt}")
                if stderr_excerpt:
                    issues.append(f"Stderr: {stderr_excerpt}")
                
                # Count failures if possible
                import re
                match = re.search(r'(\d+) failed', result.stdout)
                failed_count = int(match.group(1)) if match else 1
                match = re.search(r'(\d+) passed', result.stdout)
                passed_count = int(match.group(1)) if match else 0
                
                total = passed_count + failed_count
                if total > 0:
                    return passed_count / total, issues
                return 0.0, issues
                
        except subprocess.TimeoutExpired:
            return 0.3, ["Test execution timed out (>120s)"]
        except Exception as e:
            return 0.5, [f"Could not run tests: {e}"]
    
    async def _validate_research_output(
        self, proposal: CompletionProposal, spec: TaskCompletionSpec
    ) -> Tuple[float, List[str]]:
        """Validate research task outputs"""
        issues = []
        scores = []
        
        # Check minimum sources
        min_sources = 1  # Lowered from 3 — code analysis tasks may only have 1-2 source files
        if len(proposal.sources_consulted) < min_sources:
            issues.append(f"Insufficient sources: {len(proposal.sources_consulted)} < {min_sources}")
            scores.append(len(proposal.sources_consulted) / min_sources)
        else:
            scores.append(1.0)
        
        # Check key findings
        min_findings = 2
        if len(proposal.key_findings) < min_findings:
            issues.append(f"Insufficient findings: {len(proposal.key_findings)} < {min_findings}")
            scores.append(len(proposal.key_findings) / min_findings)
        else:
            scores.append(1.0)
        
        # Check synthesis length
        if proposal.summary and len(proposal.summary) < 100:
            issues.append("Research summary too brief (< 100 chars)")
            scores.append(0.5)
        else:
            scores.append(1.0)
        
        return sum(scores) / len(scores) if scores else 1.0, issues
    
    async def _verify_acceptance_criteria(
        self, proposal: CompletionProposal, spec: TaskCompletionSpec,
        execution_context: Dict[str, Any]
    ) -> Tuple[float, List[str], Dict[str, bool], List[str]]:
        """
        Verify each acceptance criterion.
        
        Returns:
            Tuple of (score, issues, results_dict, hard_gate_failures)
            
        Hard gates are criteria that MUST pass regardless of weighted score.
        """
        issues = []
        results = {}
        hard_gate_failures = []
        passed = 0
        
        for criterion in spec.acceptance_criteria:
            verified = False
            
            if criterion.criterion_type == "artifact_check":
                # Check if artifact exists
                if criterion.target:
                    path = criterion.target
                    if not path.startswith("/"):
                        path = os.path.join(self.workspace_root, path)
                    verified = os.path.exists(path)
            
            elif criterion.criterion_type == "output_present":
                # Check if output key exists — first in the outputs dict,
                # then as a direct proposal attribute (e.g. key_findings, summary).
                if criterion.target:
                    val_in_outputs = proposal.claimed_outputs.get(criterion.target)
                    verified = bool(val_in_outputs)
                    if not verified:
                        # Fall back to direct proposal attribute
                        field_val = getattr(proposal, criterion.target, None)
                        if isinstance(field_val, str):
                            verified = len(field_val.strip()) > 0
                        elif isinstance(field_val, (list, dict)):
                            verified = len(field_val) > 0
            
            elif criterion.criterion_type == "metric_threshold":
                # Check if metric meets threshold
                if criterion.target and criterion.threshold is not None:
                    value = execution_context.get("metrics", {}).get(criterion.target, 0)
                    verified = self._compare(value, criterion.threshold, criterion.operator)
            
            elif criterion.criterion_type == "test_result":
                # Delegate to test runner
                verified = execution_context.get("tests_passed", False)
            
            elif criterion.criterion_type == "lint_check":
                # Check if no lint errors in modified files
                verified = not any("syntax error" in issue.lower() for issue in issues)
            
            else:
                # Custom criteria - default to checking claimed outputs
                verified = criterion.description.lower() in str(proposal.claimed_outputs).lower()
            
            results[criterion.description] = verified
            if verified:
                passed += 1
                criterion.verified = True
                criterion.verified_at = datetime.now()
            else:
                issues.append(f"Criterion not met: {criterion.description}")
                
                # Track hard gate failures separately
                if criterion.hard_gate:
                    hard_gate_failures.append(f"HARD GATE FAILED: {criterion.description}")
        
        score = passed / len(spec.acceptance_criteria) if spec.acceptance_criteria else 1.0
        return score, issues, results, hard_gate_failures

    # ------------------------------------------------------------------
    # Phase 1: Question-Based Validation helpers
    # All methods are task-agnostic — no task_type conditioning anywhere.
    # ------------------------------------------------------------------

    def _collect_output_text(
        self,
        proposal: "CompletionProposal",
        execution_context: Dict[str, Any],
        max_chars: int = 15000,
    ) -> str:
        """
        Collect all available task output into a single text block.

        Sources (in order of preference):
          1. Written files on disk (output_doc_paths)
          2. proposal.summary / result_summary
          3. Claimed outputs / key findings

        Capped at max_chars to stay within LLM context budgets.
        """
        parts: List[str] = []

        # 1. Written files — the most authoritative output
        for path in execution_context.get("output_doc_paths", []):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read(8000)  # first 8 KB per file
                parts.append(f"=== FILE: {path} ===\n{content}")
            except Exception:
                pass  # file may not exist on disk; skip silently

        # 2. Proposal narrative fields
        if proposal.summary:
            parts.append(f"=== SUMMARY ===\n{proposal.summary}")
        if getattr(proposal, "result_summary", None):
            parts.append(f"=== RESULT SUMMARY ===\n{proposal.result_summary}")

        # 3. Structured claimed outputs and findings
        if proposal.key_findings:
            parts.append("=== KEY FINDINGS ===\n" + "\n".join(str(f) for f in proposal.key_findings))
        if proposal.claimed_outputs:
            import json as _json
            try:
                parts.append("=== CLAIMED OUTPUTS ===\n" + _json.dumps(proposal.claimed_outputs, indent=2))
            except Exception:
                pass

        combined = "\n\n".join(parts)
        return combined[:max_chars]
    async def _check_goal_alignment(
        self, task_description: str, proposal: CompletionProposal,
        execution_context: Dict[str, Any]
    ) -> float:
        """
        Check if output aligns with original task objective.
        
        Structured rubric evaluation — deterministic, model-free (the LLM
        critic was retired 2026-08-28).
        """
        
        
        # IMPROVED FALLBACK: Structured rubric evaluation (no critic LLM)
        score = 0.0
        
        # 1. Check summary addresses task keywords (40%)
        task_words = set(word.lower() for word in task_description.split() if len(word) > 3)
        summary_words = set(word.lower() for word in proposal.summary.split() if len(word) > 3)
        
        if task_words:
            keyword_coverage = len(task_words & summary_words) / len(task_words)
            score += 0.4 * min(1.0, keyword_coverage * 1.5)  # Slight boost
        
        # 2. Check artifacts produced (30%)
        if proposal.files_created or proposal.files_modified:
            score += 0.3
        elif proposal.claimed_outputs:
            score += 0.15  # Partial credit for other outputs
        
        # 3. Check summary length/specificity (15%)
        if len(proposal.summary) > 200:
            score += 0.15
        elif len(proposal.summary) > 50:
            score += 0.08
        
        # 4. Check evidence of work (15%)
        if proposal.key_findings or proposal.hypotheses or proposal.belief_updates:
            score += 0.15
        elif proposal.claimed_outputs:
            score += 0.08
        
        return min(1.0, score)
    
    def _check_consistency(self, proposal: CompletionProposal) -> Tuple[float, List[str]]:
        """
        Check internal consistency of the proposal.
        
        IMPROVED: Added output schema validation, cross-field consistency,
        and numerical sanity checks.
        """
        issues = []
        score = 1.0
        
        # 1. Basic contradiction check
        # NOTE: For EXECUTION tasks that produce real file changes, mixed
        # success/failure language is expected (e.g., "fixed 3 files but
        # could not patch test_comprehensive_tools.py due to non-unique match").
        # Only flag this as an issue when NO files were modified — pure
        # contradiction with no evidence of any work is suspect.
        summary_lower = proposal.summary.lower()
        failure_words = ["failed", "error", "could not", "unable to", "broken", "exception"]
        success_words = ["successfully", "completed", "implemented", "achieved", "fixed"]
        
        has_failure = any(word in summary_lower for word in failure_words)
        has_success = any(word in summary_lower for word in success_words)
        _has_file_evidence = bool(proposal.files_modified or proposal.files_created)
        
        if has_failure and has_success and not _has_file_evidence:
            issues.append("Mixed success/failure language in summary - verify accuracy")
            score -= 0.15
        
        # 2. Check claimed files vs summary
        if proposal.files_created and not proposal.summary:
            issues.append("Files claimed but no summary provided")
            score -= 0.2
        
        # 3. Cross-field consistency: files claimed should be mentioned in summary
        if proposal.files_created:
            files_mentioned = sum(
                1 for f in proposal.files_created
                if os.path.basename(f).lower() in summary_lower
            )
            if files_mentioned == 0 and len(proposal.files_created) > 0:
                issues.append("Created files not mentioned in summary")
                score -= 0.1
        
        # 4. Confidence sanity check
        if proposal.confidence > 0.95 and (proposal.remaining_risks or proposal.open_questions):
            issues.append(f"High confidence ({proposal.confidence}) but has remaining risks/questions")
            score -= 0.15
        
        if proposal.confidence < 0.3 and not proposal.remaining_risks:
            issues.append(f"Low confidence ({proposal.confidence}) but no risks listed")
            score -= 0.1
        
        # 5. Output schema validation
        outputs = proposal.claimed_outputs
        if outputs:
            # Check for common invalid patterns
            if isinstance(outputs.get("confidence"), str):
                issues.append("confidence should be numeric, got string")
                score -= 0.1
            
            # Check hypotheses have required fields
            for i, hyp in enumerate(proposal.hypotheses):
                if not hyp.get("claim"):
                    issues.append(f"Hypothesis {i} missing 'claim' field")
                    score -= 0.05
                if not hyp.get("confidence"):
                    issues.append(f"Hypothesis {i} missing 'confidence' field")
                    score -= 0.05
            
            # Check belief_updates have required fields
            for i, bu in enumerate(proposal.belief_updates):
                if not bu.get("claim"):
                    issues.append(f"Belief update {i} missing 'claim' field")
                    score -= 0.05
                if bu.get("relation") not in [None, "SUPPORTS", "CONTRADICTS", "IMPLIES", "WEAKENS", "REQUIRES"]:
                    issues.append(f"Belief update {i} has invalid relation: {bu.get('relation')}")
                    score -= 0.05
        
        # 6. Numerical sanity checks
        for hyp in proposal.hypotheses:
            conf = hyp.get("confidence", 0.5)
            if isinstance(conf, (int, float)) and (conf < 0 or conf > 1):
                issues.append(f"Hypothesis confidence {conf} out of range [0,1]")
                score -= 0.1
        
        return max(0.0, score), issues
    
    def _check_resource_budget(
        self, spec: TaskCompletionSpec, execution_context: Dict[str, Any]
    ) -> Tuple[float, List[str]]:
        """Check if task stayed within resource budget"""
        issues = []
        score = 1.0
        
        # Time budget
        if spec.max_time_seconds:
            elapsed = execution_context.get("elapsed_seconds", 0)
            if elapsed > spec.max_time_seconds:
                overage = (elapsed - spec.max_time_seconds) / spec.max_time_seconds
                score -= min(0.5, overage * 0.5)
                issues.append(f"Time budget exceeded: {elapsed}s > {spec.max_time_seconds}s")
        
        # Token budget
        if spec.max_tokens:
            used = execution_context.get("tokens_used", 0)
            if used > spec.max_tokens:
                overage = (used - spec.max_tokens) / spec.max_tokens
                score -= min(0.3, overage * 0.3)
                issues.append(f"Token budget exceeded: {used} > {spec.max_tokens}")
        
        # Iteration budget
        if spec.max_iterations:
            iterations = execution_context.get("iterations", 0)
            if iterations > spec.max_iterations:
                issues.append(f"Iteration budget exceeded: {iterations} > {spec.max_iterations}")
                score -= 0.2
        
        return max(0.0, score), issues
    
    def _compare(self, value: float, threshold: float, operator: str) -> bool:
        """Compare value against threshold using operator"""
        ops = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: abs(a - b) < 0.001,
        }
        return ops.get(operator, lambda a, b: a >= b)(value, threshold)
    
    def _generate_recommendations(
        self, score: CompletionScore, issues: List[str], spec: TaskCompletionSpec
    ) -> List[str]:
        """Generate actionable recommendations based on verification results"""
        recommendations = []
        
        if score.artifact_score < 0.8:
            recommendations.append("Create or verify all required artifacts before claiming completion")
        
        if score.validation_score < 0.8:
            recommendations.append("Fix validation errors (syntax, tests) before completion")
        
        if score.consistency_score < 0.8:
            recommendations.append("Review output for internal consistency and accuracy")
        
        if score.goal_alignment_score < 0.7:
            recommendations.append("Ensure output directly addresses the task objective")
        
        if score.resource_adherence_score < 0.8:
            recommendations.append("Consider splitting task if budget constraints are too tight")
        
        if score.total_score < spec.min_completion_score:
            gap = spec.min_completion_score - score.total_score
            recommendations.append(
                f"Total score {score.total_score:.2f} below threshold {spec.min_completion_score}. "
                f"Need +{gap:.2f} improvement."
            )
        
        return recommendations


# ============================================================================
# COMPLETION PROPOSAL PARSER
# ============================================================================

def parse_completion_proposal(llm_output: Dict[str, Any]) -> CompletionProposal:
    """
    Parse LLM output into a structured CompletionProposal.
    
    Tracks which fields were explicitly present vs omitted.
    This is critical for premature completion detection.
    
    Expected LLM format:
    {
        "status": "proposing_completion",  // NOT "complete"!
        "summary": "...",
        "outputs": {...},
        "remaining_risks": [],  // MUST be present, even if empty
        "open_questions": [],   // MUST be present, even if empty
        "assumptions": [],      // MUST be present, even if empty
        "files_created": [],
        "files_modified": [],
        "artifact_hashes": {"path": "sha256"},  // Optional for integrity
        "confidence": 0.85
    }
    """
    # Track which fields were explicitly in the output
    fields_explicitly_set = set()
    
    for field in ["remaining_risks", "open_questions", "assumptions", 
                  "files_created", "files_modified", "summary", "confidence",
                  "artifact_hashes", "hypotheses", "belief_updates"]:
        if field in llm_output:
            fields_explicitly_set.add(field)
    
    # Handle remaining_risks: None if omitted, list if present
    remaining_risks = llm_output.get("remaining_risks")
    if "remaining_risks" not in llm_output:
        remaining_risks = None  # Omitted
    elif remaining_risks is None:
        remaining_risks = []  # Explicitly set to null -> treat as empty
    
    # Handle open_questions
    open_questions = llm_output.get("open_questions")
    if "open_questions" not in llm_output:
        open_questions = None
    elif open_questions is None:
        open_questions = []
    
    # Handle assumptions
    assumptions = llm_output.get("assumptions")
    if "assumptions" not in llm_output:
        assumptions = None
    elif assumptions is None:
        assumptions = []
    
    proposal = CompletionProposal(
        claimed_outputs=llm_output.get("outputs", {}),
        summary=llm_output.get("summary", ""),
        confidence=llm_output.get("confidence", 0.5),
        remaining_risks=remaining_risks,
        open_questions=open_questions,
        assumptions=assumptions,
        files_created=llm_output.get("files_created", []),
        files_modified=llm_output.get("files_modified", []),
        artifact_hashes=llm_output.get("artifact_hashes", {}),
        hypotheses=llm_output.get("hypotheses", llm_output.get("outputs", {}).get("hypotheses", [])),
        belief_updates=llm_output.get("belief_updates", llm_output.get("outputs", {}).get("belief_updates", [])),
        sources_consulted=llm_output.get("sources", llm_output.get("sources_consulted", [])),
        key_findings=llm_output.get("findings", llm_output.get("key_findings", []))
    )
    
    proposal._fields_explicitly_set = fields_explicitly_set
    
    return proposal


# ============================================================================
# TASK SPEC GENERATOR
# ============================================================================

def generate_task_spec(
    task_type: str,
    task_description: str,
    custom_criteria: Optional[List[Dict[str, Any]]] = None,
    required_artifacts: Optional[List[str]] = None,
    max_time_seconds: Optional[int] = None
) -> TaskCompletionSpec:
    """
    Generate appropriate TaskCompletionSpec based on task type.
    
    This should be called BEFORE task execution to define completion criteria.
    Hard gates are criteria that MUST pass regardless of weighted score.
    """
    spec = TaskCompletionSpec()
    
    task_type_upper = task_type.upper()
    
    # Set validation strategy based on task type
    if task_type_upper == "EXECUTION":
        spec.validation_strategy = ValidationStrategy.STATIC_ANALYSIS
        spec.acceptance_criteria = [
            AcceptanceCriterion(
                description="Code executes without errors",
                criterion_type="test_result",
                hard_gate=True  # HARD GATE: Must pass
            ),
            AcceptanceCriterion(
                description="No syntax errors",
                criterion_type="lint_check",
                hard_gate=True  # HARD GATE: Must pass
            )
        ]
    
    elif task_type_upper == "RESEARCH":
        spec.validation_strategy = ValidationStrategy.RESEARCH_VALIDATION
        spec.acceptance_criteria = [
            AcceptanceCriterion(
                description="Multiple sources consulted",
                criterion_type="output_present",
                target="sources_consulted",  # checks proposal.sources_consulted is non-empty
                hard_gate=False  # soft criterion — execution_context never has sources_count
            ),
            AcceptanceCriterion(
                description="Key findings documented",
                criterion_type="output_present",
                target="key_findings",
                hard_gate=True  # Research must have findings
            ),
            AcceptanceCriterion(
                description="Synthesis provided",
                criterion_type="output_present",
                target="summary"
            )
        ]
        spec.min_completion_score = 0.92  # Content quality hard gates enforce substance;
        # score ceiling is reserved for EXECUTION tasks where code must demonstrably work.
    
    elif task_type_upper == "ANALYSIS":
        spec.validation_strategy = ValidationStrategy.AUTO
        spec.acceptance_criteria = [
            AcceptanceCriterion(
                description="Insights generated",
                criterion_type="output_present",
                target="key_findings",  # maps to the key_findings field in propose_completion schema
                hard_gate=True  # Analysis must have findings/insights
            ),
            AcceptanceCriterion(
                description="Summary provided",
                criterion_type="output_present",
                target="summary"  # always present in propose_completion
            )
        ]
    
    elif task_type_upper == "PLANNING":
        spec.validation_strategy = ValidationStrategy.AUTO
        spec.acceptance_criteria = [
            AcceptanceCriterion(
                description="Action steps defined",
                criterion_type="output_present",
                target="steps",
                hard_gate=True  # Planning must have steps
            )
        ]
    
    elif task_type_upper == "SECURITY_REMEDIATION":
        spec.validation_strategy = ValidationStrategy.AUTO
        spec.acceptance_criteria = [
            AcceptanceCriterion(
                description="Security issue fixed/remediated",
                criterion_type="output_present",
                target="fix_applied",
                hard_gate=True  # HARD GATE: Must actually fix the issue
            ),
            AcceptanceCriterion(
                description="Fix verification performed",
                criterion_type="output_present",
                target="verification_result",
                hard_gate=True  # HARD GATE: Must verify the fix worked
            ),
            AcceptanceCriterion(
                description="No remaining risks",
                criterion_type="custom",
                hard_gate=True  # HARD GATE: All risks must be resolved
            )
        ]
        # Stricter requirements for security tasks
        spec.min_completion_score = 0.90  # Higher bar for security
        spec.allow_empty_remaining_risks = False  # Must explicitly state no risks
        spec.allow_empty_open_questions = False  # Must explicitly confirm no questions
    
    # Add custom criteria if provided
    if custom_criteria:
        for c in custom_criteria:
            spec.acceptance_criteria.append(
                AcceptanceCriterion(
                    description=c.get("description", "Custom criterion"),
                    criterion_type=c.get("type", "custom"),
                    target=c.get("target"),
                    threshold=c.get("threshold"),
                    operator=c.get("operator", ">="),
                    hard_gate=c.get("hard_gate", False)
                )
            )
    
    # Add required artifacts
    if required_artifacts:
        spec.required_artifacts = required_artifacts
    
    # Set time budget
    if max_time_seconds:
        spec.max_time_seconds = max_time_seconds
    
    return spec


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_completion_validator: Optional[TaskCompletionValidator] = None


def get_completion_validator() -> TaskCompletionValidator:
    """Get singleton completion validator instance"""
    global _completion_validator
    if _completion_validator is None:
        _completion_validator = TaskCompletionValidator()
    return _completion_validator


async def initialize_completion_validator() -> TaskCompletionValidator:
    """Initialize the completion validator (deterministic reality checks; no LLM)."""
    validator = get_completion_validator()
    await validator.initialize()
    return validator
