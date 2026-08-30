#!/usr/bin/env python3
"""
Scientific Hypothesis Testing System
=====================================
Upgrades the Singleton's research and reasoning with rigorous scientific method:
- Explicit falsifiable hypothesis generation
- Experimental design and execution
- Bayesian belief updating based on results
- Null hypothesis testing
- Multiple hypothesis tracking
- Evidence accumulation

Integrates with:
- Bayesian uncertainty system (belief updating)
- Autonomous research (hypothesis exploration)
- Reasoning methods experimentation (hypothesis testing)
"""

import asyncio
import logging
import json
import re
import uuid
from typing import Dict, Any, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


class HypothesisStatus(Enum):
    """Status of a hypothesis"""
    PROPOSED = "proposed"  # Just proposed
    TESTING = "testing"  # Experiments running
    SUPPORTED = "supported"  # Evidence supports it
    REFUTED = "refuted"  # Evidence contradicts it
    INCONCLUSIVE = "inconclusive"  # Not enough evidence
    REVISED = "revised"  # Modified based on results


class ExperimentStatus(Enum):
    """Status of an experiment"""
    DESIGNED = "designed"  # Design complete
    RUNNING = "running"  # Currently executing
    COMPLETED = "completed"  # Finished
    FAILED = "failed"  # Execution failed
    CANCELLED = "cancelled"  # Stopped


class EvidenceType(Enum):
    """Type of evidence"""
    EXPERIMENTAL = "experimental"  # From controlled experiment
    OBSERVATIONAL = "observational"  # From observation
    THEORETICAL = "theoretical"  # From reasoning/proof
    EMPIRICAL = "empirical"  # From real-world data
    SIMULATED = "simulated"  # From simulation


@dataclass
class Hypothesis:
    """A falsifiable scientific hypothesis"""
    hypothesis_id: str
    claim: str  # The hypothesis statement
    domain: str  # Domain of inquiry
    
    # Falsifiability
    #: True / False / None, where None is UNDETERMINED -- the claim's
    #: falsifiability could not be established. Kept nullable rather than
    #: defaulted to True, which is what the assessor used to do: an
    #: unclassifiable claim was declared falsifiable on no evidence, on the
    #: exact axis that decides whether a hypothesis is worth testing.
    is_falsifiable: Optional[bool]  # Can this be proven wrong?
    falsification_criteria: List[str]  # What would disprove this?
    verification_criteria: List[str]  # What would support this?
    
    # Predictions
    predictions: List[str]  # What does this predict?
    testable_predictions: List[Dict[str, Any]]  # Specific testable predictions
    
    # Alternative hypotheses
    null_hypothesis: Optional[str] = None  # H0: no effect
    alternative_hypotheses: List[str] = field(default_factory=list)  # Competing explanations
    
    # Status
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    confidence: float = 0.5  # Prior probability
    
    # Evidence tracking
    supporting_evidence: List[str] = field(default_factory=list)  # Evidence IDs
    contradicting_evidence: List[str] = field(default_factory=list)  # Evidence IDs
    
    # Metadata
    proposed_at: datetime = field(default_factory=datetime.now)
    proposed_by: str = "singleton"
    revisions: int = 0
    parent_hypothesis_id: Optional[str] = None  # If revised from another


@dataclass
class Experiment:
    """An experiment to test a hypothesis"""
    experiment_id: str
    hypothesis_id: str
    name: str
    description: str
    
    # Design
    independent_variables: List[str]  # What we manipulate
    dependent_variables: List[str]  # What we measure
    control_variables: List[str]  # What we keep constant
    expected_outcome: str  # What we expect if hypothesis is true
    
    # Execution
    procedure: List[str]  # Step-by-step procedure
    execution_function: Optional[Callable] = None  # Actual code to run
    
    # Results
    status: ExperimentStatus = ExperimentStatus.DESIGNED
    results: Optional[Dict[str, Any]] = None
    outcome_supports_hypothesis: Optional[bool] = None
    
    # Metadata
    designed_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time: float = 0.0


@dataclass
class Evidence:
    """Evidence for or against a hypothesis"""
    evidence_id: str
    hypothesis_id: str
    evidence_type: EvidenceType
    
    # Content
    description: str
    data: Dict[str, Any]
    
    # Quality
    quality_score: float  # 0.0 to 1.0
    reliability: float  # How reliable is the source?
    relevance: float  # How relevant to hypothesis?
    
    # Direction
    supports_hypothesis: bool
    strength: float  # How strongly does it support/contradict?
    
    # Source
    source: str  # Where did this come from?
    experiment_id: Optional[str] = None  # If from experiment
    
    # Metadata
    collected_at: datetime = field(default_factory=datetime.now)


class HypothesisTestingSystem:
    """
    Scientific Hypothesis Testing for the Singleton
    
    Implements rigorous scientific method:
    1. Generate falsifiable hypotheses
    2. Design experiments to test them
    3. Execute experiments
    4. Collect evidence
    5. Update beliefs using Bayesian inference
    6. Revise or reject hypotheses based on results
    """
    
    def __init__(self, uncertainty_system=None):
        # Use unified PostgreSQL database
        self.db = None  # Will be set to TorinUnifiedDatabase in initialize()
        self.uncertainty = uncertainty_system

        # Memory agent for persisting hypothesis testing traces
        self.memory_agent = None

        # Active hypotheses
        self.hypotheses: Dict[str, Hypothesis] = {}

        # Experiments
        self.experiments: Dict[str, Experiment] = {}

        # Evidence
        self.evidence: Dict[str, Evidence] = {}

        # Statistics
        self.stats = {
            'hypotheses_proposed': 0,
            'hypotheses_supported': 0,
            'hypotheses_refuted': 0,
            'hypotheses_revised': 0,
            'experiments_designed': 0,
            'experiments_completed': 0,
            'evidence_collected': 0
        }
    
    async def initialize(self) -> bool:
        """Initialize hypothesis testing system with database and memory agent"""
        try:
            # Connect to unified PostgreSQL database
            from core.database import get_database_manager
            self.db = get_database_manager()

            if not self.db.initialized:
                await self.db.initialize()

            logger.info("✓ Connected to PostgreSQL for hypothesis testing persistence")

            # Get memory agent for persisting hypothesis testing traces
            try:
                from core.memory import get_memory_agent
                self.memory_agent = await get_memory_agent()
                await self.memory_agent.initialize()
                logger.info("✓ Connected to MemoryAgent for hypothesis testing traces")
            except Exception as e:
                logger.warning(f"MemoryAgent not available: {e}")
                self.memory_agent = None

            logger.info("✓ Hypothesis Testing System ready")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize hypothesis testing system: {e}")
            return False

    # ==================================================================================
    # HYPOTHESIS GENERATION
    # ==================================================================================
    
    async def generate_hypothesis(
        self,
        claim: str,
        domain: str,
        predictions: Optional[List[str]] = None,
        alternatives: Optional[List[str]] = None
    ) -> Hypothesis:
        """
        Generate a falsifiable hypothesis with null hypothesis and predictions.

        Args:
            claim: The hypothesis statement
            domain: Domain of inquiry
            predictions: What this hypothesis predicts
            alternatives: Alternative explanations
        """
        hypothesis_id = f"hyp_{uuid.uuid4().hex[:12]}"

        # Determine falsifiability
        # None = UNDETERMINED. Kept distinct from False downstream: a claim
        # that cannot be assessed is not the same as one shown unfalsifiable.
        is_falsifiable = self._is_falsifiable(claim)

        # Generate falsification criteria
        falsification_criteria = self._generate_falsification_criteria(claim)
        verification_criteria = self._generate_verification_criteria(claim)

        # Generate null hypothesis
        null_hypothesis = self._generate_null_hypothesis(claim)

        # Generate testable predictions
        testable_predictions = self._generate_testable_predictions(
            claim,
            predictions or []
        )

        hypothesis = Hypothesis(
            hypothesis_id=hypothesis_id,
            claim=claim,
            domain=domain,
            is_falsifiable=is_falsifiable,
            falsification_criteria=falsification_criteria,
            verification_criteria=verification_criteria,
            predictions=predictions or [],
            testable_predictions=testable_predictions,
            null_hypothesis=null_hypothesis,
            alternative_hypotheses=alternatives or []
        )

        self.hypotheses[hypothesis_id] = hypothesis
        self.stats['hypotheses_proposed'] += 1

        # Persist to database
        await self._save_hypothesis(hypothesis)
        
        # Create belief in uncertainty system
        if self.uncertainty:
            try:
                from core.reasoning.bayesian_uncertainty import get_uncertainty_system
                uncertainty = get_uncertainty_system()
                uncertainty.create_belief(
                    claim=claim,
                    domain=domain,
                    prior=0.5  # Start neutral
                )
            except Exception as e:
                logger.warning(f"Failed to create belief for hypothesis: {e}")
        
        logger.info(f"Generated hypothesis: {claim[:80]}...")
        logger.debug(f"  Falsifiable: {is_falsifiable}")
        logger.debug(f"  Null hypothesis: {null_hypothesis}")
        logger.debug(f"  Predictions: {len(testable_predictions)}")
        
        return hypothesis
    
    def _is_falsifiable(self, claim: str) -> Optional[bool]:
        """Whether the claim could be shown wrong. None means UNDETERMINED.

        THREE ANSWERS, NOT TWO. The previous version returned True for anything
        its keyword lists did not match -- so an unclassifiable claim was
        declared falsifiable on no evidence, which is a fabricated epistemic
        property on the exact axis that decides whether a hypothesis is worth
        testing at all.

        Worse, it built an `unfalsifiable_indicators` list and NEVER CONSULTED
        IT, so "this always works" came back falsifiable while the list naming
        `always` sat two lines above.

        UNDETERMINED is not a hedge. A hypothesis whose falsifiability cannot be
        established should not be admitted as a scientific one, and the caller
        can act on that -- which it cannot do if the guess already said True.
        """
        claim_lower = (claim or "").lower()
        if not claim_lower.strip():
            return None

        # Value judgements state a preference; no observation contradicts them.
        if any(word in claim_lower for word in
               ("should", "ought", "good", "bad", "better", "best", "beautiful")):
            return False

        # Tautologies are true under every observation.
        if "or not" in claim_lower or "either" in claim_lower:
            return False

        # Unbounded universals and absolutes cannot be settled by any finite
        # observation. This is the list that used to be ignored.
        if any(re.search(rf"\b{word}\b", claim_lower) for word in
               ("always", "never", "all", "none", "perfect", "impossible", "must")):
            return False

        # A claim naming a measurable direction or a conditional can be checked.
        # STEMS, not whole words: `\breduce\b` does not match "reduces", so
        # "Increasing X reduces Y" came back UNDETERMINED -- a measurable claim
        # reported as unassessable purely because of inflection.
        if any(re.search(rf"\b{stem}\w*", claim_lower) for stem in
               ("increas", "decreas", "improv", "reduc", "caus", "effect",
                "more", "less", "faster", "slower", "higher", "lower",
                "if", "when", "result", "predict")):
            return True

        # Nothing in the claim settles it. Say so.
        return None

    def _generate_falsification_criteria(self, claim: str) -> List[str]:
        """Generate criteria that would falsify the hypothesis"""
        criteria = []
        
        claim_lower = claim.lower()
        
        # Look for causal claims
        if 'cause' in claim_lower or 'increase' in claim_lower or 'improve' in claim_lower:
            criteria.append("No observed effect when intervention applied")
            criteria.append("Opposite effect observed consistently")
            criteria.append("Effect disappears in controlled experiments")
        
        # Look for correlational claims
        if 'correlate' in claim_lower or 'relate' in claim_lower or 'associate' in claim_lower:
            criteria.append("Zero or negative correlation in large sample")
            criteria.append("Correlation disappears when controlling for confounds")
        
        # Look for performance claims
        if 'better' in claim_lower or 'worse' in claim_lower or 'faster' in claim_lower:
            criteria.append("No statistically significant difference in performance")
            criteria.append("Performance worse than baseline")
        
        # General falsification
        if not criteria:
            criteria.append("Predictions do not match observations")
            criteria.append("Alternative hypothesis better explains data")
        
        return criteria
    
    def _generate_verification_criteria(self, claim: str) -> List[str]:
        """Generate criteria that would support the hypothesis"""
        criteria = []
        
        claim_lower = claim.lower()
        
        if 'cause' in claim_lower or 'increase' in claim_lower:
            criteria.append("Consistent effect observed across multiple trials")
            criteria.append("Effect size is statistically significant")
            criteria.append("Mechanism is plausible and demonstrated")
        
        if 'better' in claim_lower or 'improve' in claim_lower:
            criteria.append("Performance exceeds baseline with statistical significance")
            criteria.append("Improvement replicates across different conditions")
        
        if not criteria:
            criteria.append("Predictions match observations consistently")
            criteria.append("Evidence accumulates in favor of hypothesis")
        
        return criteria
    
    def _generate_null_hypothesis(self, claim: str) -> str:
        """Generate the null hypothesis (H0: no effect)"""
        claim_lower = claim.lower()
        
        if 'increase' in claim_lower:
            return claim.replace('increase', 'has no effect on').replace('increases', 'has no effect on')
        elif 'improve' in claim_lower:
            return claim.replace('improve', 'does not affect').replace('improves', 'does not affect')
        elif 'cause' in claim_lower:
            return claim.replace('cause', 'does not cause').replace('causes', 'does not cause')
        elif 'better' in claim_lower:
            return claim.replace('better', 'no different from')
        else:
            return f"There is no relationship described in: {claim}"
    
    def _generate_testable_predictions(
        self,
        claim: str,
        predictions: List[str]
    ) -> List[Dict[str, Any]]:
        """Convert predictions into testable format"""
        testable = []
        
        for pred in predictions:
            testable.append({
                'prediction': pred,
                'measurable': self._extract_measurable_outcome(pred),
                'test_method': self._suggest_test_method(pred)
            })
        
        return testable
    
    def _extract_measurable_outcome(self, prediction: str) -> str:
        """Extract the measurable outcome from a prediction"""
        # Simple heuristic
        pred_lower = prediction.lower()
        
        if 'time' in pred_lower or 'faster' in pred_lower or 'slower' in pred_lower:
            return "execution_time"
        elif 'accuracy' in pred_lower or 'correct' in pred_lower:
            return "accuracy_score"
        elif 'quality' in pred_lower or 'better' in pred_lower:
            return "quality_metric"
        elif 'count' in pred_lower or 'number' in pred_lower:
            return "count"
        else:
            return "observation"
    
    def _suggest_test_method(self, prediction: str) -> str:
        """Suggest how to test this prediction"""
        pred_lower = prediction.lower()
        
        if 'compare' in pred_lower or 'better' in pred_lower:
            return "A/B_test"
        elif 'measure' in pred_lower or 'count' in pred_lower:
            return "measurement"
        elif 'observe' in pred_lower:
            return "observation"
        else:
            return "controlled_experiment"
    
    # ==================================================================================
    # EXPERIMENT DESIGN
    # ==================================================================================
    
    async def design_experiment(
        self,
        hypothesis_id: str,
        name: str,
        independent_vars: List[str],
        dependent_vars: List[str],
        control_vars: Optional[List[str]] = None,
        procedure: Optional[List[str]] = None
    ) -> Experiment:
        """
        Design an experiment to test a hypothesis.

        Args:
            hypothesis_id: Hypothesis to test
            name: Experiment name
            independent_vars: Variables to manipulate
            dependent_vars: Variables to measure
            control_vars: Variables to keep constant
            procedure: Step-by-step procedure
        """
        if hypothesis_id not in self.hypotheses:
            raise ValueError(f"Hypothesis not found: {hypothesis_id}")

        hypothesis = self.hypotheses[hypothesis_id]
        experiment_id = f"exp_{uuid.uuid4().hex[:12]}"

        # Generate expected outcome
        expected_outcome = self._generate_expected_outcome(
            hypothesis,
            independent_vars,
            dependent_vars
        )

        # Generate procedure if not provided
        if not procedure:
            procedure = self._generate_procedure(
                hypothesis,
                independent_vars,
                dependent_vars,
                control_vars or []
            )

        experiment = Experiment(
            experiment_id=experiment_id,
            hypothesis_id=hypothesis_id,
            name=name,
            description=f"Testing: {hypothesis.claim}",
            independent_variables=independent_vars,
            dependent_variables=dependent_vars,
            control_variables=control_vars or [],
            expected_outcome=expected_outcome,
            procedure=procedure
        )

        self.experiments[experiment_id] = experiment
        self.stats['experiments_designed'] += 1

        # Persist to database
        await self._save_experiment(experiment)
        
        logger.info(f"Designed experiment: {name}")
        logger.debug(f"  Independent vars: {independent_vars}")
        logger.debug(f"  Dependent vars: {dependent_vars}")
        logger.debug(f"  Expected outcome: {expected_outcome}")
        
        return experiment
    
    def _generate_expected_outcome(
        self,
        hypothesis: Hypothesis,
        independent_vars: List[str],
        dependent_vars: List[str]
    ) -> str:
        """Generate expected outcome if hypothesis is true"""
        claim_lower = hypothesis.claim.lower()
        
        if 'increase' in claim_lower and dependent_vars:
            return f"{dependent_vars[0]} should increase when {independent_vars[0] if independent_vars else 'treatment'} is applied"
        elif 'improve' in claim_lower and dependent_vars:
            return f"{dependent_vars[0]} should show improvement compared to baseline"
        elif 'cause' in claim_lower:
            return f"Observable effect on {dependent_vars[0] if dependent_vars else 'outcome'}"
        else:
            return f"Predictions from hypothesis should be observed"
    
    def _generate_procedure(
        self,
        hypothesis: Hypothesis,
        independent_vars: List[str],
        dependent_vars: List[str],
        control_vars: List[str]
    ) -> List[str]:
        """Generate experimental procedure"""
        procedure = [
            "1. Establish baseline measurement",
            "2. Set up control conditions"
        ]
        
        for i, var in enumerate(control_vars, 3):
            procedure.append(f"{i}. Hold {var} constant")
        
        next_step = len(procedure) + 1
        for var in independent_vars:
            procedure.append(f"{next_step}. Manipulate {var}")
            next_step += 1
        
        for var in dependent_vars:
            procedure.append(f"{next_step}. Measure {var}")
            next_step += 1
        
        procedure.append(f"{next_step}. Compare results to baseline")
        procedure.append(f"{next_step + 1}. Analyze statistical significance")
        
        return procedure
    
    # ==================================================================================
    # EXPERIMENT EXECUTION
    # ==================================================================================
    
    async def run_experiment(
        self,
        experiment_id: str,
        execution_function: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Execute an experiment and collect results.
        
        Args:
            experiment_id: Experiment to run
            execution_function: Async function that runs the experiment
        """
        if experiment_id not in self.experiments:
            raise ValueError(f"Experiment not found: {experiment_id}")
        
        experiment = self.experiments[experiment_id]
        experiment.status = ExperimentStatus.RUNNING
        experiment.started_at = datetime.now()
        
        logger.info(f"Running experiment: {experiment.name}")
        
        try:
            # Run the experiment
            if execution_function:
                experiment.execution_function = execution_function
                results = await execution_function()
            elif experiment.execution_function:
                results = await experiment.execution_function()
            else:
                # No execution function - just mark as completed
                results = {'status': 'no_execution_function'}
            
            # Record results
            experiment.results = results
            experiment.completed_at = datetime.now()
            experiment.execution_time = (
                experiment.completed_at - experiment.started_at
            ).total_seconds()
            experiment.status = ExperimentStatus.COMPLETED
            
            # Analyze results
            supports_hypothesis = self._analyze_results(experiment, results)
            experiment.outcome_supports_hypothesis = supports_hypothesis
            
            self.stats['experiments_completed'] += 1

            # Update experiment in database
            await self._save_experiment(experiment)

            # Persist experiment results to memory with reasoning trace
            await self._store_experiment_in_memory(experiment)

            logger.info(f"Experiment completed: {experiment.name}")
            logger.info(f"  Supports hypothesis: {supports_hypothesis}")
            logger.info(f"  Execution time: {experiment.execution_time:.2f}s")

            return results
            
        except Exception as e:
            experiment.status = ExperimentStatus.FAILED
            experiment.completed_at = datetime.now()
            logger.error(f"Experiment failed: {e}")
            raise
    
    def _analyze_results(
        self,
        experiment: Experiment,
        results: Dict[str, Any]
    ) -> Optional[bool]:
        """Analyze experiment results to determine if they support the hypothesis"""
        # Simple heuristic analysis
        if 'supports_hypothesis' in results:
            return results['supports_hypothesis']
        
        if 'success' in results:
            return results['success']
        
        if 'p_value' in results:
            return results['p_value'] < 0.05  # Statistical significance
        
        if 'improvement' in results:
            return results['improvement'] > 0
        
        # Default to inconclusive
        return None
    
    # ==================================================================================
    # EVIDENCE COLLECTION
    # ==================================================================================
    
    async def collect_evidence(
        self,
        hypothesis_id: str,
        description: str,
        data: Dict[str, Any],
        evidence_type: EvidenceType,
        supports: bool,
        strength: float = 0.5,
        source: str = "experiment",
        experiment_id: Optional[str] = None
    ) -> Evidence:
        """
        Collect evidence for or against a hypothesis.
        
        Args:
            hypothesis_id: Hypothesis this evidence relates to
            description: Description of evidence
            data: Evidence data
            evidence_type: Type of evidence
            supports: Does this support the hypothesis?
            strength: How strong is the evidence (0.0 to 1.0)
            source: Source of evidence
            experiment_id: If from experiment
        """
        if hypothesis_id not in self.hypotheses:
            raise ValueError(f"Hypothesis not found: {hypothesis_id}")
        
        evidence_id = f"evd_{uuid.uuid4().hex[:12]}"
        
        # Calculate quality score
        quality_score = self._calculate_evidence_quality(
            evidence_type,
            data,
            experiment_id
        )
        
        # Calculate reliability
        reliability = self._calculate_reliability(source, evidence_type)
        
        # Calculate relevance
        relevance = strength  # For now, use strength as proxy
        
        evidence = Evidence(
            evidence_id=evidence_id,
            hypothesis_id=hypothesis_id,
            evidence_type=evidence_type,
            description=description,
            data=data,
            quality_score=quality_score,
            reliability=reliability,
            relevance=relevance,
            supports_hypothesis=supports,
            strength=strength,
            source=source,
            experiment_id=experiment_id
        )
        
        self.evidence[evidence_id] = evidence
        self.stats['evidence_collected'] += 1
        
        # Add to hypothesis
        hypothesis = self.hypotheses[hypothesis_id]
        if supports:
            hypothesis.supporting_evidence.append(evidence_id)
        else:
            hypothesis.contradicting_evidence.append(evidence_id)
        
        # Persist to database
        await self._save_evidence(evidence)
        await self._save_hypothesis(hypothesis)
        
        # Update belief in uncertainty system
        if self.uncertainty:
            try:
                from core.reasoning.bayesian_uncertainty import get_uncertainty_system
                uncertainty = get_uncertainty_system()
                
                # Find belief for this hypothesis
                for belief_id, belief in uncertainty.beliefs.items():
                    if belief.claim == hypothesis.claim:
                        uncertainty.update_belief(
                            belief_id=belief_id,
                            evidence={
                                'type': evidence_type.value,
                                'description': description,
                                'quality': quality_score,
                                'strength': strength
                            },
                            evidence_supports=supports
                        )
                        break
            except Exception as e:
                logger.warning(f"Failed to update belief: {e}")
        
        logger.info(f"Collected evidence: {description[:80]}...")
        logger.debug(f"  Type: {evidence_type.value}")
        logger.debug(f"  Supports: {supports}, Strength: {strength:.2f}")
        logger.debug(f"  Quality: {quality_score:.2f}")
        
        return evidence
    
    def _calculate_evidence_quality(
        self,
        evidence_type: EvidenceType,
        data: Dict[str, Any],
        experiment_id: Optional[str]
    ) -> float:
        """Calculate quality score for evidence"""
        quality = 0.5  # Base quality
        
        # Experimental evidence is highest quality
        if evidence_type == EvidenceType.EXPERIMENTAL:
            quality = 0.9
        elif evidence_type == EvidenceType.EMPIRICAL:
            quality = 0.8
        elif evidence_type == EvidenceType.OBSERVATIONAL:
            quality = 0.6
        elif evidence_type == EvidenceType.THEORETICAL:
            quality = 0.5
        elif evidence_type == EvidenceType.SIMULATED:
            quality = 0.7
        
        # Adjust for sample size if available
        if 'sample_size' in data:
            if data['sample_size'] > 100:
                quality += 0.1
            elif data['sample_size'] < 10:
                quality -= 0.1
        
        # Adjust for statistical significance
        if 'p_value' in data:
            if data['p_value'] < 0.01:
                quality += 0.1
            elif data['p_value'] > 0.1:
                quality -= 0.1
        
        return min(1.0, max(0.0, quality))
    
    def _calculate_reliability(self, source: str, evidence_type: EvidenceType) -> float:
        """Calculate reliability of evidence source"""
        reliability = 0.7  # Default
        
        # Controlled experiments are most reliable
        if 'experiment' in source.lower():
            reliability = 0.9
        elif 'research' in source.lower():
            reliability = 0.8
        elif 'observation' in source.lower():
            reliability = 0.6
        
        # Adjust by type
        if evidence_type == EvidenceType.EXPERIMENTAL:
            reliability += 0.1
        
        return min(1.0, reliability)
    
    # ==================================================================================
    # HYPOTHESIS EVALUATION
    # ==================================================================================
    
    async def evaluate_hypothesis(self, hypothesis_id: str) -> Dict[str, Any]:
        """
        Evaluate a hypothesis based on accumulated evidence.

        Returns verdict: supported, refuted, or inconclusive
        """
        if hypothesis_id not in self.hypotheses:
            raise ValueError(f"Hypothesis not found: {hypothesis_id}")

        hypothesis = self.hypotheses[hypothesis_id]

        # Calculate evidence balance
        supporting_strength = 0.0
        contradicting_strength = 0.0

        for evd_id in hypothesis.supporting_evidence:
            if evd_id in self.evidence:
                evd = self.evidence[evd_id]
                supporting_strength += evd.strength * evd.quality_score

        for evd_id in hypothesis.contradicting_evidence:
            if evd_id in self.evidence:
                evd = self.evidence[evd_id]
                contradicting_strength += evd.strength * evd.quality_score

        # Calculate total evidence weight
        total_evidence = supporting_strength + contradicting_strength

        if total_evidence == 0:
            verdict = HypothesisStatus.INCONCLUSIVE
            confidence = 0.5
        else:
            # Calculate support ratio
            support_ratio = supporting_strength / total_evidence

            if support_ratio > 0.7:
                verdict = HypothesisStatus.SUPPORTED
                confidence = support_ratio
                self.stats['hypotheses_supported'] += 1
            elif support_ratio < 0.3:
                verdict = HypothesisStatus.REFUTED
                confidence = 1.0 - support_ratio
                self.stats['hypotheses_refuted'] += 1
            else:
                verdict = HypothesisStatus.INCONCLUSIVE
                confidence = 0.5

        # Update hypothesis
        hypothesis.status = verdict
        hypothesis.confidence = confidence
        await self._save_hypothesis(hypothesis)
        
        evaluation = {
            'verdict': verdict.value,
            'confidence': confidence,
            'supporting_evidence_count': len(hypothesis.supporting_evidence),
            'contradicting_evidence_count': len(hypothesis.contradicting_evidence),
            'supporting_strength': supporting_strength,
            'contradicting_strength': contradicting_strength,
            'total_evidence_weight': total_evidence,
            'support_ratio': support_ratio if total_evidence > 0 else 0.0,
            'recommendation': self._generate_recommendation(verdict, confidence, total_evidence)
        }
        
        logger.info(f"Evaluated hypothesis: {hypothesis.claim[:80]}...")
        logger.info(f"  Verdict: {verdict.value}")
        logger.info(f"  Confidence: {confidence:.2f}")
        logger.info(f"  Evidence: {len(hypothesis.supporting_evidence)} supporting, {len(hypothesis.contradicting_evidence)} contradicting")
        
        return evaluation
    
    def _generate_recommendation(
        self,
        verdict: HypothesisStatus,
        confidence: float,
        total_evidence: float
    ) -> str:
        """Generate recommendation based on evaluation"""
        if total_evidence < 1.0:
            return "Collect more evidence before drawing conclusions"
        
        if verdict == HypothesisStatus.SUPPORTED and confidence > 0.8:
            return "Strong evidence supports hypothesis - consider it validated"
        elif verdict == HypothesisStatus.SUPPORTED:
            return "Moderate support - continue testing to increase confidence"
        elif verdict == HypothesisStatus.REFUTED and confidence > 0.8:
            return "Strong evidence refutes hypothesis - reject or revise"
        elif verdict == HypothesisStatus.REFUTED:
            return "Evidence contradicts hypothesis - consider alternatives"
        else:
            return "Inconclusive - design more discriminating experiments"
    
    async def revise_hypothesis(
        self,
        hypothesis_id: str,
        new_claim: str,
        reason: str
    ) -> Hypothesis:
        """Revise a hypothesis based on evidence"""
        if hypothesis_id not in self.hypotheses:
            raise ValueError(f"Hypothesis not found: {hypothesis_id}")

        old_hypothesis = self.hypotheses[hypothesis_id]
        old_hypothesis.status = HypothesisStatus.REVISED
        await self._save_hypothesis(old_hypothesis)

        # Create revised hypothesis
        new_hypothesis = await self.generate_hypothesis(
            claim=new_claim,
            domain=old_hypothesis.domain,
            predictions=old_hypothesis.predictions,
            alternatives=old_hypothesis.alternative_hypotheses
        )

        new_hypothesis.parent_hypothesis_id = hypothesis_id
        new_hypothesis.revisions = old_hypothesis.revisions + 1

        self.stats['hypotheses_revised'] += 1

        logger.info(f"Revised hypothesis: {old_hypothesis.claim[:60]}...")
        logger.info(f"  New claim: {new_claim[:60]}...")
        logger.info(f"  Reason: {reason}")

        return new_hypothesis
    
    # ==================================================================================
    # PERSISTENCE
    # ==================================================================================
    
    async def _save_hypothesis(self, hypothesis: Hypothesis):
        """Save hypothesis to PostgreSQL database"""
        if not self.db:
            logger.warning("Database not initialized, cannot save hypothesis")
            return

        try:
            await self.db.execute_query(
                """
                INSERT INTO unified.hypotheses
                (hypothesis_id, claim, domain, is_falsifiable, null_hypothesis,
                 status, confidence, proposed_at, revisions, parent_hypothesis_id,
                 falsification_criteria, verification_criteria, predictions,
                 testable_predictions, alternative_hypotheses,
                 supporting_evidence, contradicting_evidence)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17)
                ON CONFLICT (hypothesis_id) DO UPDATE SET
                    claim = EXCLUDED.claim,
                    domain = EXCLUDED.domain,
                    is_falsifiable = EXCLUDED.is_falsifiable,
                    null_hypothesis = EXCLUDED.null_hypothesis,
                    status = EXCLUDED.status,
                    confidence = EXCLUDED.confidence,
                    proposed_at = EXCLUDED.proposed_at,
                    revisions = EXCLUDED.revisions,
                    parent_hypothesis_id = EXCLUDED.parent_hypothesis_id,
                    falsification_criteria = EXCLUDED.falsification_criteria,
                    verification_criteria = EXCLUDED.verification_criteria,
                    predictions = EXCLUDED.predictions,
                    testable_predictions = EXCLUDED.testable_predictions,
                    alternative_hypotheses = EXCLUDED.alternative_hypotheses,
                    supporting_evidence = EXCLUDED.supporting_evidence,
                    contradicting_evidence = EXCLUDED.contradicting_evidence
                """,
                (
                    hypothesis.hypothesis_id,
                    hypothesis.claim,
                    hypothesis.domain,
                    hypothesis.is_falsifiable,
                    hypothesis.null_hypothesis,
                    hypothesis.status.value,
                    hypothesis.confidence,
                    # asyncpg wants a datetime for a TIMESTAMP column. Passing
                    # .isoformat() raised on every call, so this table has never
                    # received a row -- the except logged it and the in-memory
                    # object looked saved.
                    hypothesis.proposed_at,
                    hypothesis.revisions,
                    hypothesis.parent_hypothesis_id,
                    # These eight JSONB columns were declared and never written.
                    # Without falsification_criteria a restored hypothesis comes
                    # back unfalsifiable, which is the only property that makes
                    # it a hypothesis rather than an assertion.
                    json.dumps(hypothesis.falsification_criteria or []),
                    json.dumps(hypothesis.verification_criteria or []),
                    json.dumps(hypothesis.predictions or []),
                    json.dumps(hypothesis.testable_predictions or []),
                    json.dumps(hypothesis.alternative_hypotheses or []),
                    json.dumps(hypothesis.supporting_evidence or []),
                    json.dumps(hypothesis.contradicting_evidence or []),
                ),
                commit=True
            )
        except Exception as e:
            logger.error(f"Error saving hypothesis: {e}")
    
    async def _save_experiment(self, experiment: Experiment):
        """Save experiment to PostgreSQL database"""
        if not self.db:
            logger.warning("Database not initialized, cannot save experiment")
            return

        try:
            await self.db.execute_query(
                """
                INSERT INTO unified.experiments
                (experiment_id, hypothesis_id, name, description, expected_outcome,
                 status, outcome_supports_hypothesis, designed_at, completed_at, execution_time)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (experiment_id) DO UPDATE SET
                    hypothesis_id = EXCLUDED.hypothesis_id,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    expected_outcome = EXCLUDED.expected_outcome,
                    status = EXCLUDED.status,
                    outcome_supports_hypothesis = EXCLUDED.outcome_supports_hypothesis,
                    designed_at = EXCLUDED.designed_at,
                    completed_at = EXCLUDED.completed_at,
                    execution_time = EXCLUDED.execution_time
                """,
                (
                    experiment.experiment_id,
                    experiment.hypothesis_id,
                    experiment.name,
                    experiment.description,
                    experiment.expected_outcome,
                    experiment.status.value,
                    experiment.outcome_supports_hypothesis,
                    # Same defect as _save_hypothesis: asyncpg needs a datetime
                    # for a TIMESTAMP column, so every experiment write raised.
                    experiment.designed_at,
                    experiment.completed_at,
                    experiment.execution_time
                ),
                commit=True
            )
        except Exception as e:
            logger.error(f"Error saving experiment: {e}")

    async def _store_experiment_in_memory(self, experiment: Experiment):
        """
        Store experiment result in memory with rich upstream metadata.

        Generates MemoryWorthinessMetadata at creation time for intelligent filtering.
        """
        try:
            if not self.memory_agent:
                return

            from datetime import datetime
            from core.memory.utils.interfaces import MemoryType
            from core.memory.utils.memory_worthiness import (
                MemoryWorthinessMetadata,
                CognitionMetadata,
                NoveltyMetadata,
                CriticalityMetadata,
                QueryMetadata,
                OutcomeMetadata,
                TemporalMetadata,
                JustificationMetadata,
                DecisionType,
                ConsequenceLevel,
                PatternType,
                QueryType,
                ReusabilityLevel,
                DomainImportance
            )

            # Get associated hypothesis for context
            hypothesis = self.hypotheses.get(experiment.hypothesis_id)

            # Build reasoning trace from experiment procedure
            reasoning_trace = []
            if experiment.procedure:
                reasoning_trace = experiment.procedure if isinstance(experiment.procedure, list) else [experiment.procedure]

            # Add outcome information to reasoning trace
            if experiment.outcome_supports_hypothesis is not None:
                reasoning_trace.append(
                    f"Result: Hypothesis {'supported' if experiment.outcome_supports_hypothesis else 'not supported'}"
                )

            # Build content summary
            content_summary = f"Hypothesis experiment: {experiment.name}"
            if hypothesis:
                content_summary += f" testing '{hypothesis.claim}'"

            # ========== UPSTREAM METADATA GENERATION ==========

            # 1. Cognition Metadata - Measure experimental effort
            procedure_steps = len(reasoning_trace)
            cognition = CognitionMetadata(
                reasoning_steps=procedure_steps,
                reasoning_depth=1,  # Experiments are typically single-level
                execution_time_ms=experiment.execution_time * 1000 if experiment.execution_time else 0.0,
                inference_count=procedure_steps,
                complexity_score=self._calculate_experiment_complexity(experiment, hypothesis),
                required_backtracking=experiment.status == ExperimentStatus.FAILED,
                used_multiple_strategies=False,  # Experiments use single methodology
                uncertainty_resolved=experiment.outcome_supports_hypothesis is not None
            )

            # 2. Novelty Metadata - Is this new knowledge?
            novelty = NoveltyMetadata(
                is_novel=experiment.outcome_supports_hypothesis is not None,  # Completed experiments create knowledge
                contradicts_existing=experiment.outcome_supports_hypothesis == False if experiment.outcome_supports_hypothesis is not None else False,
                synthesis_of_domains=[hypothesis.domain] if hypothesis else [],
                pattern_type=PatternType.EMERGENT if experiment.outcome_supports_hypothesis else PatternType.ROUTINE,
                first_occurrence=True,  # Each experiment is unique
                connects_disparate_knowledge=False
            )

            # 3. Criticality Metadata - How important is this experiment?
            is_critical_domain = hypothesis and hypothesis.domain in ["security", "safety", "governance"]
            criticality = CriticalityMetadata(
                decision_type=DecisionType.TACTICAL,  # Experiments are tactical validation
                domain_importance=DomainImportance.HIGH if is_critical_domain else DomainImportance.MEDIUM,
                reusability=ReusabilityLevel.HIGH,  # Experiment results are highly reusable
                consequence_level=ConsequenceLevel.HIGH if experiment.outcome_supports_hypothesis is False else ConsequenceLevel.MEDIUM,
                likely_reference_count=5,  # Experiments are frequently referenced
                time_sensitivity=is_critical_domain
            )

            # 4. Query Metadata - What type of investigation?
            query = QueryMetadata(
                query_type=QueryType.ANALYSIS,  # Experiments are analytical
                requires_synthesis=False,
                multi_step=procedure_steps > 1,
                involves_uncertainty=experiment.outcome_supports_hypothesis is None,
                ambiguous_input=False,
                context_dependent=True
            )

            # 5. Outcome Metadata - What was produced?
            outcome = OutcomeMetadata(
                conclusion_confidence=hypothesis.confidence if hypothesis else 0.5,
                hypothesis_supported=experiment.outcome_supports_hypothesis,
                actionable=experiment.outcome_supports_hypothesis is not None,
                created_new_knowledge=experiment.status == ExperimentStatus.COMPLETED,
                action_type="hypothesis_testing",
                action_summary=f"Tested hypothesis: {hypothesis.claim if hypothesis else 'unknown'}",
                affected_components=["hypothesis_testing"],
                validated_against_sources=experiment.status == ExperimentStatus.COMPLETED,
                requires_human_review=experiment.outcome_supports_hypothesis is None or experiment.status == ExperimentStatus.FAILED
            )

            # 6. Temporal Metadata - When and why?
            temporal = TemporalMetadata(
                created_at=experiment.completed_at.isoformat() if experiment.completed_at else datetime.now().isoformat(),
                session_id=getattr(self, 'session_id', 'default_session'),
                trigger_event="hypothesis_experiment",
                sequence_number=getattr(self, '_experiment_sequence', 0)
            )
            self._experiment_sequence = getattr(self, '_experiment_sequence', 0) + 1

            # 7. Justification Metadata - Why store this?
            store_reasons = []
            if experiment.status == ExperimentStatus.COMPLETED:
                store_reasons.append("experiment_completed")
            if experiment.outcome_supports_hypothesis is False:
                store_reasons.append("hypothesis_disproved")  # Negative results are important!
            if procedure_steps >= 3:
                store_reasons.append("multi_step_procedure")
            if is_critical_domain:
                store_reasons.append("critical_domain")

            justification = JustificationMetadata(
                store_reason=store_reasons if store_reasons else ["experiment_pending"],
                decision_summary=f"Hypothesis experiment with {procedure_steps} steps, status: {experiment.status.value}",
                alternatives_considered=["skip_storage"] if experiment.status == ExperimentStatus.PENDING else [],
                rejected_because=[] if store_reasons else ["experiment_incomplete"]
            )

            # Create comprehensive metadata
            worthiness_metadata = MemoryWorthinessMetadata(
                cognition=cognition,
                novelty=novelty,
                criticality=criticality,
                query=query,
                outcome=outcome,
                temporal=temporal,
                justification=justification,
                source_system="hypothesis_testing",
                domain=hypothesis.domain if hypothesis else "general"
            )

            # ========== STORE WITH METADATA ==========

            # Rich metadata with justification and outcome
            thinking_state = {
                "experiment_id": experiment.experiment_id,
                "hypothesis_id": experiment.hypothesis_id,
                "status": experiment.status.value,
                "execution_time": experiment.execution_time,
                "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
                "completed_at": experiment.completed_at.isoformat() if experiment.completed_at else None,
                "worthiness_metadata": worthiness_metadata.to_dict(),  # Include full metadata
                # RICH METADATA: Justification for storing this memory
                "justification": {
                    "store_reason": [
                        "hypothesis_testing",
                        "scientific_method",
                        "empirical_validation",
                        "supports_hypothesis" if experiment.outcome_supports_hypothesis else "refutes_hypothesis"
                    ],
                    "decision_summary": f"Hypothesis test '{experiment.name}' {('confirmed' if experiment.outcome_supports_hypothesis else 'refuted')} the hypothesis: {hypothesis.claim if hypothesis else 'N/A'}",
                    "alternatives_considered": [
                        "observational_study",
                        "theoretical_proof",
                        "simulation_only"
                    ],
                    "rejected_because": [
                        "requires_empirical_evidence",
                        "hypothesis_needs_experimental_validation",
                        "real_world_testing_necessary"
                    ],
                    "complexity_assessment": "high" if len(reasoning_trace) > 10 else "medium",
                    "novelty_assessment": "novel" if experiment.outcome_supports_hypothesis and (hypothesis.confidence if hypothesis else 0.5) > 0.8 else "incremental"
                },
                # RICH METADATA: Outcome of this experiment
                "outcome": {
                    "action_type": "hypothesis_test",
                    "action_summary": f"Experiment '{experiment.name}' {('validated' if experiment.outcome_supports_hypothesis else 'invalidated')} hypothesis with {len(reasoning_trace)} steps",
                    "affected_components": ["hypothesis_system", "knowledge_base", (hypothesis.domain if hypothesis else "general")],
                    "created_new_knowledge": experiment.outcome_supports_hypothesis or experiment.status.value == "completed",
                    "confidence": hypothesis.confidence if hypothesis else 0.5,
                    "impact_assessment": "significant" if experiment.outcome_supports_hypothesis else "moderate",
                    "verification_status": "verified" if experiment.status.value == "completed" else "partial",
                    "success_criteria": {
                        "experiment_completed": experiment.status.value == "completed",
                        "hypothesis_evaluated": experiment.outcome_supports_hypothesis is not None,
                        "results_available": bool(experiment.results),
                        "expected_outcome_met": experiment.outcome_supports_hypothesis == (experiment.expected_outcome == "support")
                    }
                }
            }

            decision_factors = {
                "hypothesis_claim": hypothesis.claim if hypothesis else None,
                "expected_outcome": experiment.expected_outcome,
                "actual_outcome": experiment.outcome_supports_hypothesis,
                "procedure_steps": len(reasoning_trace),
                # RICH METADATA: Experimental design decisions
                "experimental_design": {
                    "chosen_method": experiment.method if hasattr(experiment, 'method') else "empirical_test",
                    "design_rationale": f"Experimental method chosen to test hypothesis in {hypothesis.domain if hypothesis else 'general'} domain",
                    "control_variables": experiment.control_variables if hasattr(experiment, 'control_variables') else [],
                    "validity_threats": ["confounding_variables", "measurement_error", "sample_bias"]
                }
            }

            emotional_context = {
                "outcome_supports_hypothesis": experiment.outcome_supports_hypothesis,
                "experiment_status": experiment.status.value,
                "hypothesis_confidence": hypothesis.confidence if hypothesis else None
            }

            if experiment.results:
                emotional_context["has_results"] = True
                if isinstance(experiment.results, dict):
                    emotional_context.update({
                        k: v for k, v in experiment.results.items()
                        if k in ['p_value', 'success', 'improvement', 'supports_hypothesis']
                    })

            # Store to memory agent with full chain of thought
            success, memory_id = await self.memory_agent.store_memory(
                memory_type=MemoryType.EPISODIC,  # Experiments are episodic events
                content=content_summary,
                importance_score=0.8,  # Experiments are important
                confidence_score=hypothesis.confidence if hypothesis else 0.5,
                tags=["hypothesis_testing", "experiment", experiment.status.value, hypothesis.domain if hypothesis else "general"],
                source_context={
                    "experiment_name": experiment.name,
                    "hypothesis_claim": hypothesis.claim if hypothesis else None,
                    "expected_outcome": experiment.expected_outcome,
                    "results": experiment.results
                },
                reasoning_trace=reasoning_trace,
                thinking_state=thinking_state,
                decision_factors=decision_factors,
                emotional_context=emotional_context
            )

            if success:
                logger.debug(f"Hypothesis experiment stored to memory: {memory_id} (worthiness: {worthiness_metadata.justification.store_reason})")

        except Exception as e:
            logger.error(f"Error storing experiment in memory: {e}")

    def _calculate_experiment_complexity(self, experiment: Experiment, hypothesis: Optional[Hypothesis]) -> float:
        """Calculate complexity score (0.0-1.0) for hypothesis experiment"""
        score = 0.0

        # Factor 1: Procedure complexity (up to 0.4)
        if experiment.procedure:
            procedure_steps = len(experiment.procedure) if isinstance(experiment.procedure, list) else 1
            score += min(procedure_steps / 5.0, 0.4)

        # Factor 2: Hypothesis confidence (up to 0.2, inverted - lower confidence = more complex)
        if hypothesis:
            score += min((1.0 - hypothesis.confidence) * 0.4, 0.2)

        # Factor 3: Experiment status (0.2 for completed/failed)
        if experiment.status in [ExperimentStatus.COMPLETED, ExperimentStatus.FAILED]:
            score += 0.2

        # Factor 4: Results complexity (up to 0.2)
        if experiment.results and isinstance(experiment.results, dict):
            score += min(len(experiment.results) / 10.0, 0.2)

        return min(score, 1.0)
    
    async def _save_evidence(self, evidence: Evidence):
        """Save evidence to PostgreSQL database"""
        if not self.db:
            logger.warning("Database not initialized, cannot save evidence")
            return

        try:
            await self.db.execute_query(
                """
                INSERT INTO unified.evidence
                (evidence_id, hypothesis_id, evidence_type, description, quality_score,
                 supports_hypothesis, strength, source, experiment_id, collected_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (evidence_id) DO UPDATE SET
                    hypothesis_id = EXCLUDED.hypothesis_id,
                    evidence_type = EXCLUDED.evidence_type,
                    description = EXCLUDED.description,
                    quality_score = EXCLUDED.quality_score,
                    supports_hypothesis = EXCLUDED.supports_hypothesis,
                    strength = EXCLUDED.strength,
                    source = EXCLUDED.source,
                    experiment_id = EXCLUDED.experiment_id,
                    collected_at = EXCLUDED.collected_at
                """,
                (
                    evidence.evidence_id,
                    evidence.hypothesis_id,
                    evidence.evidence_type.value,
                    evidence.description,
                    evidence.quality_score,
                    evidence.supports_hypothesis,
                    evidence.strength,
                    evidence.source,
                    evidence.experiment_id,
                    evidence.collected_at.isoformat()
                ),
                commit=True
            )
        except Exception as e:
            logger.error(f"Error saving evidence: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        return {
            **self.stats,
            'active_hypotheses': len([h for h in self.hypotheses.values() if h.status == HypothesisStatus.PROPOSED or h.status == HypothesisStatus.TESTING]),
            'supported_hypotheses': len([h for h in self.hypotheses.values() if h.status == HypothesisStatus.SUPPORTED]),
            'refuted_hypotheses': len([h for h in self.hypotheses.values() if h.status == HypothesisStatus.REFUTED]),
            'total_evidence': len(self.evidence),
            'running_experiments': len([e for e in self.experiments.values() if e.status == ExperimentStatus.RUNNING])
        }


# Global instance
_hypothesis_system: Optional[HypothesisTestingSystem] = None


def get_hypothesis_system() -> HypothesisTestingSystem:
    """Get or create global hypothesis testing system"""
    global _hypothesis_system
    
    if _hypothesis_system is None:
        try:
            from core.reasoning.bayesian_uncertainty import get_uncertainty_system
            uncertainty = get_uncertainty_system()
            _hypothesis_system = HypothesisTestingSystem(uncertainty_system=uncertainty)
        except:
            _hypothesis_system = HypothesisTestingSystem()
    
    return _hypothesis_system
