#!/usr/bin/env python3
"""
Formal Argumentation Framework
===============================
Implements Toulmin's argumentation model and formal argumentation theory
for structured reasoning, debate, and fallacy detection.

Core capabilities:
- Toulmin argument structure (claim, data, warrant, backing, qualifier, rebuttal)
- Argument graph construction and analysis
- Fallacy detection (25+ logical fallacies)
- Counter-argument generation
- Argument strength evaluation
- Dialectical reasoning support

Integrates with:
- Multi-agent debate system (structured argumentation)
- Hypothesis testing (evidence evaluation)
- Bayesian uncertainty (confidence in claims)

Based on:
- Toulmin's Model of Argumentation (1958)
- Walton's Argumentation Schemes (1996)
- van Eemeren's Pragma-Dialectics
"""

import asyncio
import logging
import json
import uuid
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from collections import defaultdict
import re

from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


class ArgumentType(Enum):
    """Types of arguments"""
    DEDUCTIVE = "deductive"  # Logically valid
    INDUCTIVE = "inductive"  # Probabilistic
    ABDUCTIVE = "abductive"  # Inference to best explanation
    ANALOGICAL = "analogical"  # Based on similarity
    AUTHORITY = "authority"  # Appeal to expert
    CAUSAL = "causal"  # Cause and effect
    STATISTICAL = "statistical"  # Based on data


class FallacyType(Enum):
    """Types of logical fallacies"""
    # Formal fallacies
    AFFIRMING_CONSEQUENT = "affirming_consequent"
    DENYING_ANTECEDENT = "denying_antecedent"
    UNDISTRIBUTED_MIDDLE = "undistributed_middle"
    
    # Informal fallacies - relevance
    AD_HOMINEM = "ad_hominem"
    AD_POPULUM = "ad_populum"  # Appeal to popularity
    AD_VERECUNDIAM = "ad_verecundiam"  # Appeal to authority
    APPEAL_TO_EMOTION = "appeal_to_emotion"
    RED_HERRING = "red_herring"
    STRAW_MAN = "straw_man"
    
    # Informal fallacies - presumption
    BEGGING_QUESTION = "begging_question"  # Circular reasoning
    FALSE_DILEMMA = "false_dilemma"
    SLIPPERY_SLOPE = "slippery_slope"
    HASTY_GENERALIZATION = "hasty_generalization"
    POST_HOC = "post_hoc"  # False causation
    
    # Informal fallacies - ambiguity
    EQUIVOCATION = "equivocation"
    COMPOSITION = "composition"
    DIVISION = "division"
    
    # Other common fallacies
    APPEAL_TO_IGNORANCE = "appeal_to_ignorance"
    BURDEN_OF_PROOF = "burden_of_proof"
    FALSE_EQUIVALENCE = "false_equivalence"
    CHERRY_PICKING = "cherry_picking"
    MOVING_GOALPOSTS = "moving_goalposts"
    NO_TRUE_SCOTSMAN = "no_true_scotsman"
    GENETIC_FALLACY = "genetic_fallacy"
    TU_QUOQUE = "tu_quoque"  # You too/hypocrisy


class ArgumentStrength(Enum):
    """Strength of an argument"""
    CONCLUSIVE = "conclusive"  # Logically valid deduction
    STRONG = "strong"  # High probability
    MODERATE = "moderate"  # Some support
    WEAK = "weak"  # Little support
    FALLACIOUS = "fallacious"  # Contains fallacy


# Ordinal rank for preference-based defeat. The enum values are strings, so they
# must never be compared directly — "weak" > "strong" is True alphabetically.
STRENGTH_RANK: Dict[ArgumentStrength, int] = {
    ArgumentStrength.FALLACIOUS: 0,
    ArgumentStrength.WEAK: 1,
    ArgumentStrength.MODERATE: 2,
    ArgumentStrength.STRONG: 3,
    ArgumentStrength.CONCLUSIVE: 4,
}


@dataclass
class Claim:
    """A claim or proposition"""
    claim_id: str
    statement: str
    
    # Toulmin elements
    data: List[str] = field(default_factory=list)  # Evidence/grounds
    warrant: str = ""  # Rule/principle connecting data to claim
    backing: List[str] = field(default_factory=list)  # Support for warrant
    qualifier: str = ""  # Degree of certainty (probably, certainly, possibly)
    rebuttal: List[str] = field(default_factory=list)  # Conditions where claim fails
    
    # Metadata
    claim_type: str = "assertion"
    confidence: float = 0.5
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Argument:
    """A formal argument with Toulmin structure"""
    argument_id: str
    claim: Claim
    argument_type: ArgumentType
    
    # Structure
    premises: List[str] = field(default_factory=list)
    conclusion: str = ""
    
    # Evaluation
    strength: ArgumentStrength = ArgumentStrength.MODERATE
    validity: bool = False  # Logically valid?
    soundness: bool = False  # Valid + true premises?
    
    # Fallacies
    fallacies_detected: List[FallacyType] = field(default_factory=list)
    fallacy_explanations: Dict[str, str] = field(default_factory=dict)
    
    # Counter-arguments
    counter_arguments: List[str] = field(default_factory=list)  # IDs of counter-arguments
    refuted_by: Optional[str] = None  # ID of successful rebuttal
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ArgumentGraph:
    """Graph of arguments and their relationships"""
    graph_id: str
    topic: str
    
    # Nodes (arguments)
    arguments: Dict[str, Argument] = field(default_factory=dict)
    
    # Edges (relationships)
    supports: List[Tuple[str, str]] = field(default_factory=list)  # (arg1_id, arg2_id)
    attacks: List[Tuple[str, str]] = field(default_factory=list)  # (arg1_id, arg2_id)
    rebuts: List[Tuple[str, str]] = field(default_factory=list)  # (arg1_id, arg2_id)
    
    # Analysis
    root_claim: Optional[str] = None  # Main claim being debated
    winning_arguments: List[str] = field(default_factory=list)  # grounded extension

    # Dung semantics
    grounded_extension: List[str] = field(default_factory=list)
    preferred_extensions: List[List[str]] = field(default_factory=list)
    stable_extensions: List[List[str]] = field(default_factory=list)
    semantics_complete: bool = True  # False if extension search was capped

    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Fallacy:
    """A detected logical fallacy"""
    fallacy_id: str
    fallacy_type: FallacyType
    argument_id: str
    
    # Details
    description: str
    location: str  # Where in argument
    severity: float  # 0.0 to 1.0
    
    # Correction
    how_to_fix: str = ""
    corrected_version: Optional[str] = None


class FormalArgumentationSystem:
    """
    Formal Argumentation Framework for the Singleton
    
    Implements rigorous argumentation theory:
    - Toulmin's model for argument structure
    - Fallacy detection across 25+ types
    - Argument graph analysis
    - Counter-argument generation
    - Dialectical reasoning
    
    Elevates debate beyond rhetoric to formal logic.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        # Use unified database instead of separate argumentation.db
        # Argumentation knowledge persists to the unified PostgreSQL
        # database like the rest of the system -- no SQLite file.
        self.unified_db = TorinUnifiedDatabase()

        # Store db_path (defaults to argumentation.db in workspace)

        # Argument database
        self.claims: Dict[str, Claim] = {}
        self.arguments: Dict[str, Argument] = {}
        self.graphs: Dict[str, ArgumentGraph] = {}
        self.fallacies: Dict[str, Fallacy] = {}
        
        # Fallacy patterns (regex-based detection)
        self.fallacy_patterns = self._initialize_fallacy_patterns()
        
        # Statistics
        self.stats = {
            'arguments_analyzed': 0,
            'fallacies_detected': 0,
            'counter_arguments_generated': 0,
            'graphs_built': 0,
            'claims_validated': 0,
            'debates_resolved': 0
        }
        
        # Initialize database
        # Schema is created lazily by the async persistence path.
    
    def _db(self):
        from core.database import get_database_manager
        return get_database_manager()

    async def _ensure_schema(self):
        """Create the argumentation tables in the unified DB if absent. Idempotent."""
        db = self._db()
        if not getattr(db, "initialized", False):
            await db.initialize()
        await db.execute_query(
            "CREATE TABLE IF NOT EXISTS unified.reasoning_arg_claims ("
            "claim_id TEXT PRIMARY KEY, statement TEXT NOT NULL, warrant TEXT, "
            "qualifier TEXT, confidence REAL, source TEXT, "
            "created_at TIMESTAMPTZ DEFAULT NOW())", commit=True)
        await db.execute_query(
            "CREATE TABLE IF NOT EXISTS unified.reasoning_arguments ("
            "argument_id TEXT PRIMARY KEY, claim_id TEXT, argument_type TEXT, "
            "conclusion TEXT, strength TEXT, validity BOOLEAN, soundness BOOLEAN, "
            "refuted_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW())", commit=True)
        await db.execute_query(
            "CREATE TABLE IF NOT EXISTS unified.reasoning_arg_fallacies ("
            "fallacy_id TEXT PRIMARY KEY, fallacy_type TEXT, argument_id TEXT, "
            "description TEXT, severity REAL, "
            "created_at TIMESTAMPTZ DEFAULT NOW())", commit=True)

    async def persist(self):
        """Persist argumentation knowledge to the unified PostgreSQL DB.
        Off the critical path and non-fatal: reasoning is in-memory and a
        persistence failure must never break it (the old SQLite write was a
        synchronous filesystem write inside the reasoning path)."""
        try:
            await self._ensure_schema()
            db = self._db()
            for c in self.claims.values():
                await db.execute_query(
                    "INSERT INTO unified.reasoning_arg_claims "
                    "(claim_id, statement, warrant, qualifier, confidence, source) "
                    "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (claim_id) DO UPDATE SET "
                    "statement=EXCLUDED.statement, confidence=EXCLUDED.confidence",
                    (c.claim_id, c.statement, c.warrant, c.qualifier,
                     float(c.confidence), c.source), commit=True)
            for a in self.arguments.values():
                await db.execute_query(
                    "INSERT INTO unified.reasoning_arguments "
                    "(argument_id, claim_id, argument_type, conclusion, strength, "
                    "validity, soundness, refuted_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
                    "ON CONFLICT (argument_id) DO UPDATE SET validity=EXCLUDED.validity, "
                    "soundness=EXCLUDED.soundness, refuted_by=EXCLUDED.refuted_by",
                    (a.argument_id, a.claim.claim_id, a.argument_type.value,
                     a.conclusion, a.strength.value, bool(a.validity),
                     bool(a.soundness), a.refuted_by), commit=True)
            for f in self.fallacies.values():
                await db.execute_query(
                    "INSERT INTO unified.reasoning_arg_fallacies "
                    "(fallacy_id, fallacy_type, argument_id, description, severity) "
                    "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (fallacy_id) DO UPDATE SET "
                    "description=EXCLUDED.description, severity=EXCLUDED.severity",
                    (f.fallacy_id, f.fallacy_type.value, f.argument_id,
                     f.description, float(f.severity)), commit=True)
        except Exception as error:
            logger.debug("argumentation persist skipped (non-fatal): %s", error)

    async def load(self, limit: int = 1000):
        """Bring prior claims and arguments into memory so argument evaluation
        consults what earlier sessions established. Non-fatal."""
        try:
            await self._ensure_schema()
            db = self._db()
            rows = await db.execute_query(
                "SELECT claim_id, statement, warrant, qualifier, confidence, source "
                "FROM unified.reasoning_arg_claims ORDER BY created_at DESC LIMIT $1",
                (int(limit),), fetch_all=True) or []
            for r in rows:
                if r["claim_id"] not in self.claims:
                    self.claims[r["claim_id"]] = Claim(
                        claim_id=r["claim_id"], statement=r["statement"],
                        warrant=r["warrant"] or "", qualifier=r["qualifier"] or "",
                        confidence=float(r["confidence"] or 0.5), source=r["source"] or "")
            rows = await db.execute_query(
                "SELECT argument_id, claim_id, argument_type, conclusion, strength, "
                "validity, soundness, refuted_by FROM unified.reasoning_arguments "
                "ORDER BY created_at DESC LIMIT $1", (int(limit),), fetch_all=True) or []
            for r in rows:
                claim = self.claims.get(r["claim_id"])
                if claim is None or r["argument_id"] in self.arguments:
                    continue
                try:
                    self.arguments[r["argument_id"]] = Argument(
                        argument_id=r["argument_id"], claim=claim,
                        argument_type=ArgumentType(r["argument_type"]),
                        conclusion=r["conclusion"] or "",
                        strength=ArgumentStrength(r["strength"]),
                        validity=bool(r["validity"]), soundness=bool(r["soundness"]),
                        refuted_by=r["refuted_by"])
                except Exception:
                    continue
        except Exception as error:
            logger.debug("argumentation load skipped (non-fatal): %s", error)

    def _initialize_fallacy_patterns(self) -> Dict[FallacyType, List[str]]:
        """Initialize regex patterns for fallacy detection"""
        return {
            FallacyType.AD_HOMINEM: [
                r"you(?:'re| are) (?:stupid|dumb|ignorant|biased)",
                r"coming from (?:you|someone like you)",
                r"what would you know about"
            ],
            FallacyType.STRAW_MAN: [
                r"so (?:you|they) (?:think|believe|claim) that",
                r"(?:you|they)(?:'re| are) saying (?:all|every|always)"
            ],
            FallacyType.FALSE_DILEMMA: [
                r"either.*or(?! not)",
                r"(?:only|just) two (?:options|choices|possibilities)",
                r"you(?:'re| are) either (?:with|for) .* or (?:against|opposed)"
            ],
            FallacyType.APPEAL_TO_EMOTION: [
                r"think (?:of|about) the (?:children|victims|suffering)",
                r"how would you feel if",
                r"imagine if (?:your|you were)"
            ],
            FallacyType.AD_POPULUM: [
                r"(?:everyone|everybody|most people) (?:knows|agrees|believes)",
                r"if (?:so many|most|everyone) .* then",
                r"popular (?:opinion|belief|consensus)"
            ],
            FallacyType.SLIPPERY_SLOPE: [
                r"if we (?:allow|permit) .* (?:then|,) (?:next|soon|eventually)",
                r"where (?:does|will) it (?:end|stop)",
                r"leads? (?:inevitably|directly) to"
            ],
            FallacyType.BEGGING_QUESTION: [
                r"(?:because|since) (?:it|that) (?:is|was|has|does)",
                r"(?:obviously|clearly|evidently) true (?:because|since)"
            ],
            FallacyType.POST_HOC: [
                r"after .* (?:therefore|so|thus) .* (?:caused|must have)",
                r"(?:since|because) .* happened .* must be (?:due to|because of)"
            ],
            FallacyType.HASTY_GENERALIZATION: [
                r"(?:I|we) (?:once|one time) .* (?:therefore|so) (?:all|every|always)",
                r"(?:one|a single) .* (?:proves|shows) that (?:all|every)"
            ],
            FallacyType.APPEAL_TO_IGNORANCE: [
                r"(?:nobody|no one) (?:has|can) (?:proven|disproven|shown)",
                r"(?:since|because) (?:you|we) (?:can't|cannot) (?:prove|show|demonstrate)",
                r"absence of evidence"
            ],
            FallacyType.RED_HERRING: [
                r"but what about",
                r"(?:more important|bigger (?:issue|problem))"
            ],
            FallacyType.TU_QUOQUE: [
                r"you (?:do|did) (?:it|that|the same) too",
                r"(?:what|look) about (?:when you|your)"
            ],
            FallacyType.CHERRY_PICKING: [
                r"(?:only|just) (?:look at|consider|focus on) (?:this|these)",
                r"(?:ignore|disregard) (?:all|the) (?:other|rest)"
            ]
        }
    
    # ==================================================================================
    # ARGUMENT CONSTRUCTION
    # ==================================================================================
    
    def create_claim(
        self,
        statement: str,
        data: Optional[List[str]] = None,
        warrant: str = "",
        backing: Optional[List[str]] = None,
        qualifier: str = "probably",
        rebuttal: Optional[List[str]] = None,
        confidence: float = 0.5,
        source: str = ""
    ) -> Claim:
        """Create a claim with Toulmin structure"""
        claim_id = f"claim_{uuid.uuid4().hex[:12]}"
        
        claim = Claim(
            claim_id=claim_id,
            statement=statement,
            data=data or [],
            warrant=warrant,
            backing=backing or [],
            qualifier=qualifier,
            rebuttal=rebuttal or [],
            confidence=confidence,
            source=source
        )
        
        self.claims[claim_id] = claim
        
        return claim
    
    def create_argument(
        self,
        claim: Claim,
        premises: List[str],
        argument_type: ArgumentType = ArgumentType.DEDUCTIVE,
        context: Optional[Dict[str, Any]] = None
    ) -> Argument:
        """Create a formal argument"""
        argument_id = f"arg_{uuid.uuid4().hex[:12]}"
        
        argument = Argument(
            argument_id=argument_id,
            claim=claim,
            argument_type=argument_type,
            premises=premises,
            conclusion=claim.statement,
            context=context or {}
        )
        
        # Evaluate argument
        self._evaluate_argument(argument)
        
        self.arguments[argument_id] = argument
        
        self.stats['arguments_analyzed'] += 1
        
        return argument
    
    def _evaluate_argument(self, argument: Argument):
        """Evaluate argument validity, soundness, and strength"""
        
        # Check for fallacies
        fallacies = self.detect_fallacies(argument)
        argument.fallacies_detected = [f.fallacy_type for f in fallacies]
        argument.fallacy_explanations = {
            f.fallacy_type.value: f.description for f in fallacies
        }
        
        # If fallacies found, mark as fallacious
        if fallacies:
            argument.strength = ArgumentStrength.FALLACIOUS
            argument.validity = False
            argument.soundness = False
            return
        
        # Evaluate based on type
        if argument.argument_type == ArgumentType.DEDUCTIVE:
            # Check logical validity (simple heuristics)
            argument.validity = self._check_deductive_validity(argument)
            # Soundness = validity + true premises (assume true for now)
            argument.soundness = argument.validity
            argument.strength = ArgumentStrength.CONCLUSIVE if argument.soundness else ArgumentStrength.WEAK
        
        elif argument.argument_type == ArgumentType.INDUCTIVE:
            # Inductive strength based on evidence
            if len(argument.premises) >= 5:
                argument.strength = ArgumentStrength.STRONG
            elif len(argument.premises) >= 3:
                argument.strength = ArgumentStrength.MODERATE
            else:
                argument.strength = ArgumentStrength.WEAK
        
        elif argument.argument_type == ArgumentType.ABDUCTIVE:
            # Abductive strength based on explanatory power
            argument.strength = ArgumentStrength.MODERATE
        
        else:
            argument.strength = ArgumentStrength.MODERATE
    
    def _check_deductive_validity(self, argument: Argument) -> bool:
        """Check if deductive argument is logically valid (simple check)"""
        # This is simplified - full validity checking requires formal logic
        
        # Modus ponens pattern: If P then Q. P. Therefore Q.
        if len(argument.premises) == 2:
            p1 = argument.premises[0].lower()
            p2 = argument.premises[1].lower()
            conclusion = argument.conclusion.lower()
            
            # Check for "if...then" structure
            if "if" in p1 and "then" in p1:
                # Extract antecedent and consequent
                parts = p1.split("then")
                if len(parts) == 2:
                    antecedent = parts[0].replace("if", "").strip()
                    consequent = parts[1].strip()
                    
                    # Check if second premise affirms antecedent
                    if antecedent in p2 and consequent in conclusion:
                        return True  # Modus ponens - valid
        
        # Default: cannot verify validity with simple heuristic
        return False
    
    # ==================================================================================
    # FALLACY DETECTION
    # ==================================================================================
    
    def detect_fallacies(self, argument: Argument) -> List[Fallacy]:
        """Detect logical fallacies in an argument"""
        fallacies = []
        
        # Combine all text to analyze
        text_parts = argument.premises + [argument.conclusion, argument.claim.statement]
        full_text = " ".join(text_parts).lower()
        
        # Pattern-based detection
        for fallacy_type, patterns in self.fallacy_patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, full_text, re.IGNORECASE)
                if matches:
                    fallacy = Fallacy(
                        fallacy_id=f"fallacy_{uuid.uuid4().hex[:8]}",
                        fallacy_type=fallacy_type,
                        argument_id=argument.argument_id,
                        description=self._get_fallacy_description(fallacy_type),
                        location=f"Matched pattern: {pattern}",
                        severity=self._get_fallacy_severity(fallacy_type),
                        how_to_fix=self._get_fallacy_fix(fallacy_type)
                    )
                    fallacies.append(fallacy)
                    self.fallacies[fallacy.fallacy_id] = fallacy
                    self.stats['fallacies_detected'] += 1
                    break  # One detection per type
        
        # Structural fallacy detection
        structural_fallacies = self._detect_structural_fallacies(argument)
        fallacies.extend(structural_fallacies)
        
        return fallacies
    
    def _detect_structural_fallacies(self, argument: Argument) -> List[Fallacy]:
        """Detect fallacies based on argument structure"""
        fallacies = []
        
        # Circular reasoning (begging the question)
        if argument.conclusion.lower() in [p.lower() for p in argument.premises]:
            fallacy = Fallacy(
                fallacy_id=f"fallacy_{uuid.uuid4().hex[:8]}",
                fallacy_type=FallacyType.BEGGING_QUESTION,
                argument_id=argument.argument_id,
                description="Circular reasoning: conclusion appears in premises",
                location="Premise-Conclusion structure",
                severity=0.9,
                how_to_fix="Provide independent evidence that doesn't assume the conclusion"
            )
            fallacies.append(fallacy)
            self.fallacies[fallacy.fallacy_id] = fallacy
            self.stats['fallacies_detected'] += 1
        
        # Hasty generalization (too few premises)
        if argument.argument_type == ArgumentType.INDUCTIVE and len(argument.premises) < 2:
            fallacy = Fallacy(
                fallacy_id=f"fallacy_{uuid.uuid4().hex[:8]}",
                fallacy_type=FallacyType.HASTY_GENERALIZATION,
                argument_id=argument.argument_id,
                description="Insufficient evidence for inductive conclusion",
                location="Number of premises",
                severity=0.7,
                how_to_fix="Provide more evidence/examples before generalizing"
            )
            fallacies.append(fallacy)
            self.fallacies[fallacy.fallacy_id] = fallacy
            self.stats['fallacies_detected'] += 1
        
        return fallacies
    
    def _get_fallacy_description(self, fallacy_type: FallacyType) -> str:
        """Get human-readable description of fallacy"""
        descriptions = {
            FallacyType.AD_HOMINEM: "Attacking the person instead of the argument",
            FallacyType.STRAW_MAN: "Misrepresenting opponent's position to make it easier to attack",
            FallacyType.FALSE_DILEMMA: "Presenting only two options when more exist",
            FallacyType.APPEAL_TO_EMOTION: "Manipulating emotions instead of using logic",
            FallacyType.AD_POPULUM: "Arguing something is true because many believe it",
            FallacyType.SLIPPERY_SLOPE: "Claiming one event will inevitably lead to another without justification",
            FallacyType.BEGGING_QUESTION: "Circular reasoning - assuming what you're trying to prove",
            FallacyType.POST_HOC: "Assuming causation from correlation or sequence",
            FallacyType.HASTY_GENERALIZATION: "Drawing broad conclusion from insufficient evidence",
            FallacyType.APPEAL_TO_IGNORANCE: "Claiming something is true because it hasn't been proven false",
            FallacyType.RED_HERRING: "Introducing irrelevant information to distract",
            FallacyType.TU_QUOQUE: "Avoiding criticism by pointing out hypocrisy",
            FallacyType.CHERRY_PICKING: "Selecting only favorable evidence while ignoring contrary evidence",
            FallacyType.AFFIRMING_CONSEQUENT: "If P then Q. Q. Therefore P. (Invalid)",
            FallacyType.DENYING_ANTECEDENT: "If P then Q. Not P. Therefore not Q. (Invalid)"
        }
        return descriptions.get(fallacy_type, f"Logical fallacy: {fallacy_type.value}")
    
    def _get_fallacy_severity(self, fallacy_type: FallacyType) -> float:
        """Get severity rating for fallacy type"""
        # Formal fallacies are more severe (break logical validity)
        formal = [FallacyType.AFFIRMING_CONSEQUENT, FallacyType.DENYING_ANTECEDENT, 
                  FallacyType.UNDISTRIBUTED_MIDDLE]
        if fallacy_type in formal:
            return 1.0
        
        # Circular reasoning is very severe
        if fallacy_type == FallacyType.BEGGING_QUESTION:
            return 0.9
        
        # Most informal fallacies
        return 0.7
    
    def _get_fallacy_fix(self, fallacy_type: FallacyType) -> str:
        """Get advice on how to fix the fallacy"""
        fixes = {
            FallacyType.AD_HOMINEM: "Address the argument, not the person making it",
            FallacyType.STRAW_MAN: "Represent opponent's actual position accurately",
            FallacyType.FALSE_DILEMMA: "Acknowledge and consider additional options",
            FallacyType.APPEAL_TO_EMOTION: "Provide logical evidence instead of emotional appeals",
            FallacyType.AD_POPULUM: "Provide evidence independent of popularity",
            FallacyType.SLIPPERY_SLOPE: "Provide causal links for each step in the chain",
            FallacyType.BEGGING_QUESTION: "Provide independent premises that don't assume the conclusion",
            FallacyType.POST_HOC: "Demonstrate causal mechanism, not just correlation",
            FallacyType.HASTY_GENERALIZATION: "Gather more evidence before generalizing",
            FallacyType.APPEAL_TO_IGNORANCE: "Burden of proof is on the claimant",
            FallacyType.CHERRY_PICKING: "Consider all available evidence, not just favorable examples"
        }
        return fixes.get(fallacy_type, "Review argument for logical soundness")
    
    # ==================================================================================
    # COUNTER-ARGUMENT GENERATION
    # ==================================================================================
    
    def generate_counter_argument(
        self,
        argument: Argument,
        strategy: str = "undercut"
    ) -> Argument:
        """
        Generate counter-argument using specified strategy.
        
        Strategies:
        - undercut: Attack the warrant/reasoning
        - rebut: Attack the conclusion directly
        - undermine: Challenge the evidence/premises
        """
        counter_premises = []
        
        if strategy == "rebut":
            # Direct rebuttal - negate the conclusion
            counter_statement = f"It is not the case that {argument.conclusion.lower()}"
            counter_claim = self.create_claim(
                statement=counter_statement,
                warrant="Direct negation of opponent's conclusion",
                qualifier="arguably"
            )
            counter_premises = [
                f"The claim '{argument.conclusion}' lacks sufficient support",
                f"Alternative explanations exist for the evidence presented"
            ]
        
        elif strategy == "undercut":
            # Attack the warrant
            counter_statement = f"The reasoning from premises to conclusion is flawed"
            counter_claim = self.create_claim(
                statement=counter_statement,
                warrant="Logical connection between premises and conclusion is weak",
                qualifier="likely"
            )
            counter_premises = [
                f"The warrant '{argument.claim.warrant}' does not hold in this case",
                "The logical inference is invalid or unsound"
            ]
        
        elif strategy == "undermine":
            # Challenge the evidence
            counter_statement = f"The evidence provided does not support the conclusion"
            counter_claim = self.create_claim(
                statement=counter_statement,
                warrant="Evidence is insufficient, unreliable, or irrelevant",
                qualifier="possibly"
            )
            counter_premises = [
                "The premises lack adequate evidential support",
                "Alternative interpretations of the evidence are more plausible"
            ]
        else:
            # Default fallback strategy (undercut)
            counter_statement = f"The reasoning from premises to conclusion is flawed"
            counter_claim = self.create_claim(
                statement=counter_statement,
                warrant="Logical connection between premises and conclusion is weak",
                qualifier="likely"
            )
            counter_premises = [
                f"The warrant '{argument.claim.warrant}' does not hold in this case",
                "The logical inference is invalid or unsound"
            ]
        
        # Create counter-argument
        counter_arg = self.create_argument(
            claim=counter_claim,
            premises=counter_premises,
            argument_type=ArgumentType.DEDUCTIVE,
            context={'counter_to': argument.argument_id, 'strategy': strategy}
        )
        
        # Link arguments
        argument.counter_arguments.append(counter_arg.argument_id)
        
        self.stats['counter_arguments_generated'] += 1
        
        logger.info(f"Generated {strategy} counter-argument to {argument.argument_id}")
        
        return counter_arg
    
    # ==================================================================================
    # ARGUMENT GRAPH
    # ==================================================================================
    
    def build_argument_graph(
        self,
        topic: str,
        root_claim: Claim,
        arguments: List[Argument]
    ) -> ArgumentGraph:
        """Build argument graph from a set of arguments"""
        graph_id = f"graph_{uuid.uuid4().hex[:12]}"
        
        graph = ArgumentGraph(
            graph_id=graph_id,
            topic=topic,
            root_claim=root_claim.claim_id
        )
        
        # Add arguments to graph
        for arg in arguments:
            graph.arguments[arg.argument_id] = arg
        
        # Build relationships
        for arg in arguments:
            # Check if this argument supports or attacks others
            for other_arg in arguments:
                if arg.argument_id != other_arg.argument_id:
                    # Supports relationship
                    if self._argument_supports(arg, other_arg):
                        graph.supports.append((arg.argument_id, other_arg.argument_id))
                    
                    # Attacks relationship
                    if self._argument_attacks(arg, other_arg):
                        graph.attacks.append((arg.argument_id, other_arg.argument_id))
                    
                    # Rebuts relationship
                    if arg.argument_id in other_arg.counter_arguments:
                        graph.rebuts.append((arg.argument_id, other_arg.argument_id))
        
        # Analyze graph to find winning arguments
        graph.winning_arguments = self._analyze_argument_graph(graph)
        
        self.graphs[graph_id] = graph
        
        self.stats['graphs_built'] += 1
        
        logger.info(f"Built argument graph: {topic} with {len(arguments)} arguments")
        
        return graph
    
    def _argument_supports(self, arg1: Argument, arg2: Argument) -> bool:
        """Check if arg1 supports arg2"""
        # Simple heuristic: conclusion of arg1 appears in premises of arg2
        return arg1.conclusion.lower() in [p.lower() for p in arg2.premises]
    
    def _argument_attacks(self, arg1: Argument, arg2: Argument) -> bool:
        """Check if arg1 attacks arg2"""
        # Simple heuristic: conclusion of arg1 contradicts conclusion of arg2
        c1 = arg1.conclusion.lower()
        c2 = arg2.conclusion.lower()
        
        # Check for negation words
        negations = ["not", "no", "never", "neither", "cannot", "isn't", "doesn't"]
        
        # If one has negation and other doesn't, they likely attack each other
        c1_has_neg = any(neg in c1 for neg in negations)
        c2_has_neg = any(neg in c2 for neg in negations)
        
        if c1_has_neg != c2_has_neg:
            # Check if they're about the same topic (share significant words)
            c1_words = set(c1.split())
            c2_words = set(c2.split())
            overlap = c1_words & c2_words
            if len(overlap) >= 2:  # At least 2 words in common
                return True
        
        return False
    
    # Above this many arguments, enumerating maximal admissible sets is not
    # tractable; grounded is still exact, preferred/stable are reported empty.
    MAX_ENUMERABLE_ARGUMENTS = 18

    def _build_defeat_relation(
        self,
        graph: ArgumentGraph
    ) -> Tuple[Set[str], Dict[str, Set[str]]]:
        """Return (arguments, defeats) where defeats[a] is the set a defeats.

        An attack only succeeds as a defeat if the attacker is at least as
        strong as its target (preference-based argumentation framework).
        Fallacious arguments are excluded from the framework entirely.
        """
        args = {
            arg_id for arg_id, arg in graph.arguments.items()
            if not arg.fallacies_detected
            and arg.strength is not ArgumentStrength.FALLACIOUS
        }

        defeats: Dict[str, Set[str]] = {a: set() for a in args}
        for attacker_id, target_id in graph.attacks:
            if attacker_id not in args or target_id not in args:
                continue
            attacker = graph.arguments[attacker_id]
            target = graph.arguments[target_id]
            if STRENGTH_RANK[attacker.strength] >= STRENGTH_RANK[target.strength]:
                defeats[attacker_id].add(target_id)

        return args, defeats

    @staticmethod
    def _defeaters(arg_id: str, defeats: Dict[str, Set[str]]) -> Set[str]:
        return {a for a, targets in defeats.items() if arg_id in targets}

    def _is_conflict_free(self, subset: Set[str], defeats: Dict[str, Set[str]]) -> bool:
        return not any(defeats[a] & subset for a in subset)

    def _defends(self, subset: Set[str], arg_id: str, defeats: Dict[str, Set[str]]) -> bool:
        """subset defends arg_id if it defeats every defeater of arg_id."""
        return all(
            any(attacker in defeats[member] for member in subset)
            for attacker in self._defeaters(arg_id, defeats)
        )

    def _characteristic_function(
        self,
        subset: Set[str],
        args: Set[str],
        defeats: Dict[str, Set[str]]
    ) -> Set[str]:
        return {a for a in args if self._defends(subset, a, defeats)}

    def _grounded_extension(self, args: Set[str], defeats: Dict[str, Set[str]]) -> Set[str]:
        """Least fixpoint of the characteristic function, starting from the empty set."""
        current: Set[str] = set()
        while True:
            nxt = self._characteristic_function(current, args, defeats)
            if nxt == current:
                return current
            current = nxt

    def _is_admissible(self, subset: Set[str], defeats: Dict[str, Set[str]]) -> bool:
        return self._is_conflict_free(subset, defeats) and all(
            self._defends(subset, a, defeats) for a in subset
        )

    def _preferred_extensions(
        self,
        args: Set[str],
        defeats: Dict[str, Set[str]]
    ) -> List[Set[str]]:
        """Maximal (w.r.t. set inclusion) admissible sets."""
        ordered = sorted(args)
        admissible: List[Set[str]] = []
        for mask in range(1 << len(ordered)):
            subset = {ordered[i] for i in range(len(ordered)) if mask & (1 << i)}
            if self._is_admissible(subset, defeats):
                admissible.append(subset)

        return [
            s for s in admissible
            if not any(other > s for other in admissible)
        ]

    def _stable_extensions(
        self,
        args: Set[str],
        defeats: Dict[str, Set[str]]
    ) -> List[Set[str]]:
        """Conflict-free sets that defeat every argument outside themselves."""
        ordered = sorted(args)
        stable: List[Set[str]] = []
        for mask in range(1 << len(ordered)):
            subset = {ordered[i] for i in range(len(ordered)) if mask & (1 << i)}
            if not self._is_conflict_free(subset, defeats):
                continue
            outside = args - subset
            if all(any(target in defeats[member] for member in subset) for target in outside):
                stable.append(subset)
        return stable

    def _analyze_argument_graph(self, graph: ArgumentGraph) -> List[str]:
        """Determine accepted arguments using Dung's abstract argumentation semantics.

        Returns the grounded extension — the unique, skeptical set of arguments
        that survive every line of attack. Preferred and stable extensions are
        also recorded on the graph when the framework is small enough to enumerate.
        """
        args, defeats = self._build_defeat_relation(graph)

        grounded = self._grounded_extension(args, defeats)
        graph.grounded_extension = sorted(grounded)

        if len(args) <= self.MAX_ENUMERABLE_ARGUMENTS:
            graph.preferred_extensions = [sorted(s) for s in self._preferred_extensions(args, defeats)]
            graph.stable_extensions = [sorted(s) for s in self._stable_extensions(args, defeats)]
            graph.semantics_complete = True
        else:
            graph.preferred_extensions = []
            graph.stable_extensions = []
            graph.semantics_complete = False
            logger.info(
                f"Argument graph {graph.graph_id}: {len(args)} arguments exceeds "
                f"enumeration cap ({self.MAX_ENUMERABLE_ARGUMENTS}); "
                f"reported grounded extension only"
            )

        return sorted(grounded)
    
    # ==================================================================================
    # PERSISTENCE
    # ==================================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        return {
            **self.stats,
            'total_claims': len(self.claims),
            'total_arguments': len(self.arguments),
            'total_fallacies': len(self.fallacies),
            'total_graphs': len(self.graphs),
            'fallacy_rate': (self.stats['fallacies_detected'] / max(self.stats['arguments_analyzed'], 1))
        }


# Global instance
_argumentation_system: Optional[FormalArgumentationSystem] = None


def get_argumentation_system() -> FormalArgumentationSystem:
    """Get or create global argumentation system"""
    global _argumentation_system
    
    if _argumentation_system is None:
        _argumentation_system = FormalArgumentationSystem()
    
    return _argumentation_system
