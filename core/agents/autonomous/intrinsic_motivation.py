#!/usr/bin/env python3
"""
Intrinsic Motivation System
Implements 7-dimensional intrinsic motivation for autonomous behavior
Influences 60% of self-improvement decisions
"""

from core.capability import raise_if_structural
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import json
from pathlib import Path
import numpy as np
import math
import random
import time
import hashlib

from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


class MotivationDimension:
    """Individual dimension of intrinsic motivation"""
    CURIOSITY = "curiosity"  # Novel exploration
    COMPETENCE = "competence"  # Skill improvement
    NOVELTY = "novelty"  # New experiences
    MASTERY = "mastery"  # Deep understanding
    AUTONOMY = "autonomy"  # Self-direction
    SOCIAL = "social"  # Collaboration
    IMPACT = "impact"  # Meaningful change


@dataclass
class MotivationWeights:
    """Weights for each motivation dimension"""
    curiosity: float = 1.2  # Highest priority
    competence: float = 0.9
    novelty: float = 0.85
    mastery: float = 0.7
    autonomy: float = 1.0
    social: float = 0.9
    impact: float = 0.8


@dataclass
class IntrinsicReward:
    """Reward for a single event — deliberately not a motivation dimension.

    A dimension is a drive level ("how strongly is curiosity active now").
    A reward is event-scoped ("how much did this event advance that drive").
    They are not interchangeable: the competence drive is an inverted-U, so
    delegating competence_reward to _calculate_competence would pay the system
    least exactly when it performs best.
    """
    dimension: str
    reward_value: float
    components: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _numeric_vector(experience: Dict[str, Any]) -> Dict[str, float]:
    """Numeric fields of an experience, for novelty comparison."""
    if not isinstance(experience, dict):
        return {}
    return {
        k: float(v)
        for k, v in experience.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def _normalised_distance(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Mean per-field relative difference over the fields the two share."""
    shared = set(a) & set(b)
    if not shared:
        return 1.0
    total = 0.0
    for key in shared:
        scale = max(abs(a[key]), abs(b[key]), 1.0)
        total += min(1.0, abs(a[key] - b[key]) / scale)
    return total / len(shared)


@dataclass
class MotivationProfile:
    """Complete motivation profile for the system"""
    dimensions: Dict[str, float] = field(default_factory=dict)
    weights: MotivationWeights = field(default_factory=MotivationWeights)

    # Instantaneous drive level: the weighted mean of the 7 dimensions, in
    # [0,1]. Recomputed from scratch on every calculate_motivation() call.
    total_intrinsic_reward: float = 0.0

    # Accumulated event rewards. A DIFFERENT quantity: unbounded running sum of
    # what individual experiences were worth to the drives.
    #
    # These two used to share the field above. log_intrinsic_reward() did
    # `+= reward_value` and calculate_motivation() did `= weighted_mean(...)`,
    # so every persisted reward's contribution was wiped on the next motivation
    # refresh — the reward→drive edge could never survive one cycle.
    accumulated_event_reward: float = 0.0
    event_reward_count: int = 0

    influence_percentage: float = 0.60  # 60% influence on self-improvement
    last_updated: Optional[datetime] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def mean_event_reward(self) -> float:
        """Average worth of recent experience to the drives. [-1, 1]."""
        if not self.event_reward_count:
            return 0.0
        return self.accumulated_event_reward / self.event_reward_count


@dataclass
class GoalEmbedding:
    """Stored goal with embedding for novelty tracking"""
    description: str
    embedding: np.ndarray
    theme: str
    component: str
    abstraction_level: str
    objective_type: str
    timestamp: datetime
    repeat_count: int = 0


@dataclass
class MutationDimensions:
    """Dimensions that can be mutated in goals"""
    component: str  # Target component
    abstraction_level: str  # low/medium/high
    objective_type: str  # explore/optimize/fix/learn
    time_horizon: str  # immediate/short/long



def _unmeasured_stats(domain: str, reason: str) -> Dict[str, Any]:
    """Honest 'no measurement' result.

    success_rate/failure_rate/confidence are None — NOT 0.5. A fabricated
    midpoint made 0 observations indistinguishable from a genuinely coin-flip
    domain, and consumers silently inherited it as if it were data. Callers
    needing a prior must apply one explicitly, with provenance.
    """
    return {
        "success_rate": None,
        "failure_rate": None,
        "avg_outcome_label_confidence": None,
        "successes": 0,
        "failures": 0,
        "total_attempts": 0,
        "measured": False,
        "unmeasured_reason": reason,
        "domain": domain,
    }


@dataclass
class CapabilityEvidence:
    """What we have OBSERVED about a capability — evidence, not a verdict.

    Deliberately stops short of `estimated_competence`. Raw success rate is not
    competence: 4/4 causal successes and 8/9 technical successes both look
    "high" while resting on very different support, and 1/1 is not mastery.
    Producing a single maturity number here would recreate the defect this
    layer exists to prevent — an authoritative-looking scalar with no
    justification for its aggregation.

    task_diversity / difficulty_coverage / recency_coverage are None until
    something can actually measure them. They are named so their absence is
    visible rather than quietly assumed adequate.
    """

    capability: str
    successes: int = 0
    failures: int = 0
    attempts: int = 0
    empirical_success_rate: Optional[float] = None

    # "How sure were we this task succeeded?" — NOT confidence in the rate.
    outcome_label_confidence: Optional[float] = None

    task_diversity: Optional[float] = None
    difficulty_coverage: Optional[float] = None
    recency_coverage: Optional[float] = None

    evidence_ids: List[str] = field(default_factory=list)

    @classmethod
    def from_domain_stats(cls, capability: str, stats: Dict[str, Any]) -> "CapabilityEvidence":
        """Lift statistical observation into structured evidence. No inference."""
        return cls(
            capability=capability,
            successes=int(stats.get("successes", 0) or 0),
            failures=int(stats.get("failures", 0) or 0),
            attempts=int(stats.get("total_attempts", 0) or 0),
            empirical_success_rate=stats.get("success_rate"),
            outcome_label_confidence=stats.get("avg_outcome_label_confidence"),
        )

    @property
    def is_measured(self) -> bool:
        return self.attempts > 0

    @property
    def support(self) -> str:
        """Qualitative sample support. Names the sparsity the ratio hides."""
        if self.attempts == 0:
            return "none"
        if self.attempts < 3:
            return "anecdotal"
        if self.attempts < 10:
            return "sparse"
        return "moderate"


class IntrinsicMotivationSystem:
    """
    Intrinsic Motivation System

    Calculates motivation across 7 dimensions:
    1. Curiosity (1.2x) - Novel exploration
    2. Competence (0.9x) - Skill improvement
    3. Novelty (0.85x) - New experiences
    4. Mastery (0.7x) - Deep understanding
    5. Autonomy (1.0x) - Self-direction
    6. Social (0.9x) - Collaboration
    7. Impact (0.8x) - Meaningful change

    Influences 60% of autonomous self-improvement decisions
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        # Motivation profile
        self.profile = MotivationProfile()
        self.weights = MotivationWeights()

        # Database for persistence (optional - gracefully degrades)
        self.db = None


        # Integration points
        self.security_audit_worker = None  # For receiving security findings

        # Configuration
        self.influence_percentage = self.config.get("influence_percentage", 0.60)
        # Motivation profile persistence
        # Precedence:
        # 1) env TORINAI_MOTIVATION_PROFILE_PATH
                # 2) config motivation_profile_path
        # 3) config profile_path (legacy)
        # Default: TorinAI/data/motivation_profile.json (inside repo)
        import os

        torin_root = Path(__file__).resolve().parents[3]
        default_path = torin_root / "data" / "motivation_profile.json"

        raw_path = (
            os.getenv("TORINAI_MOTIVATION_PROFILE_PATH")
            or self.config.get("motivation_profile_path")
            or self.config.get("profile_path")
            or str(default_path)
        )
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (torin_root / candidate).resolve()
        self.profile_path = candidate

        logger.info(f"Motivation profile path: {self.profile_path}")

        # Motivation history (recent calculations)
        self.history_limit = self.config.get("history_limit", 100)

        # Track previously generated goals to avoid repetition (persisted across restarts)
        self._recent_goal_descriptions: List[str] = []
        self._max_recent_goals = 20
        # Persist recent goal list to disk so restarts don't lose cross-session novelty memory
        self._goal_history_path = self.profile_path.parent / "goal_history.json"

        # ========== NEW: 4 Advanced Features ==========

        # 1. NOVELTY TRACKER: Stores embeddings of intrinsic goals
        self._goal_embeddings: List[GoalEmbedding] = []
        self._embedding_service = None  # Set during initialize()
        # Similarity threshold for DOWNSTREAM novelty/dedup guidance only. It is
        # NOT a formation gate: goal formation is deterministic and never vetoed by
        # the similarity model (severing MiniLM must not change whether a goal forms).
        self._novelty_threshold = 0.75

        # 2. ENTROPY INJECTOR: Non-deterministic boot-time context
        self._boot_entropy = self._generate_boot_entropy()
        logger.info(f"Boot entropy injected: {self._boot_entropy[:50]}...")

        # Use boot entropy to seed per-session sampling so early exploration
        # does not converge to identical goal distributions across restarts.
        try:
            self._boot_entropy_seed = int(hashlib.sha256(self._boot_entropy.encode()).hexdigest()[:8], 16)
        except Exception:
            self._boot_entropy_seed = random.randint(0, 2**32 - 1)
        self._entropy_rng = random.Random(self._boot_entropy_seed)
        try:
            self._entropy_np_rng = np.random.default_rng(self._boot_entropy_seed)
        except Exception:
            self._entropy_np_rng = None

        # 3. EXPLORATION DECAY: Theme-based decay tracking
        self._theme_counts: Dict[str, int] = {}  # theme -> repeat_count
        self._decay_rate = 0.3  # Decay coefficient for exp(-decay_rate * count)

        # 4. GOAL MUTATION ENGINE: Dimensional mutation parameters
        self._mutation_enabled = True
        self._mutation_dimensions = {
            'components': ['memory_agent', 'neural_bridge', 'unified_llm', 'learning', 'security'],
            'abstraction_levels': ['low', 'medium', 'high'],
            'objective_types': ['research', 'explore', 'learn', 'analyze', 'optimize', 'investigate', 'improve'],
            'time_horizons': ['immediate', 'short', 'long']
        }
        # ==============================================

        # UNCERTAINTY QUANTIFICATION: Component metrics tracking
        self._component_baselines: Dict[str, Dict[str, float]] = {}  # component -> metrics baseline
        self._metric_history: Dict[str, List[Dict[str, float]]] = {}  # component -> history of metrics

        # Weighted priority coefficients
        self._priority_weights = {
            'epistemic_uncertainty': 1.0,
            'impact_radius': 0.8,
            'performance_degradation': 0.6,
            'novelty_potential': 0.4,
            'recent_exploration_penalty': -0.5
        }

        # PLAN DIVERSITY ENFORCEMENT: Track tool sequence history
        self._tool_sequence_history: List[List[str]] = []  # List of tool sequences per iteration
        self._max_sequence_history = 10  # Keep last 10 iterations
        self._tool_cooldowns: Dict[str, int] = {}  # tool_name -> iterations remaining
        self._tool_failure_counts: Dict[str, int] = {}  # tool_name -> consecutive failures

        # NON-ADAPTIVE RETRY DETECTION: Track parameter patterns
        self._failed_parameter_patterns: Dict[str, List[Dict]] = {}  # tool_name -> failed param sets
        self._blocked_tool_params: Dict[str, set] = {}  # tool_name -> set of blocked param signatures

        # Initialize dimensions
        self._initialize_dimensions()

        logger.info("Intrinsic motivation system initialized with advanced novelty features")


    def set_security_audit_worker(self, worker):
        """Set security audit worker for receiving security findings"""
        self.security_audit_worker = worker
        logger.info("Intrinsic motivation system connected to security audit worker")

    async def log_intrinsic_reward(
        self,
        task_id: str,
        task_type: str,
        reward_value: float,
        outcome_quality: float,
        success: bool,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Persist an intrinsic reward score to the unified.intrinsic_motivation table.

        This is the long-term memory for the reward system: every task outcome
        is recorded so competence calibration and curiosity calculations have
        real historical data to work from across restarts.

        Schema: id, timestamp, motivation_type, score, context, metadata
        """
        if not self.db:
            return
        try:
            import uuid as _uuid
            import json as _json
            _row_id = str(_uuid.uuid4())
            _meta = _json.dumps({
                'task_id': task_id,
                'task_type': task_type,
                'outcome_quality': outcome_quality,
                'success': success,
                **(extra or {}),
            })
            await self.db.execute_query(
                """
                INSERT INTO intrinsic_motivation
                    (id, timestamp, motivation_type, score, context, metadata)
                VALUES ($1, NOW(), 'task_outcome', $2, $3, $4)
                """,
                params=(_row_id, reward_value, task_id[:64], _meta),
                commit=True,
            )
            # Accumulate on the EVENT reward, not the drive level — writing to
            # total_intrinsic_reward here meant calculate_motivation() erased it.
            self.profile.accumulated_event_reward += reward_value
            self.profile.event_reward_count += 1
            logger.debug(
                f"Persisted intrinsic reward: task={task_id[:8]} "
                f"type={task_type} reward={reward_value:.3f} success={success}"
            )
        except Exception as _e:
            logger.warning(f"log_intrinsic_reward DB write failed (non-fatal): {_e}")

    async def initialize(self) -> bool:
        """Bring the motivation system up. Mirror of shutdown().

        The coordinator's module loop calls initialize() on every subsystem;
        this class never had one, so the loop raised AttributeError and the
        whole coordinator failed to start. It also left three fields at their
        constructor defaults forever:

          - self.db is None, so log_intrinsic_reward() returns early and
            theme counts always read 0 (making novelty decay exp(0) = 1.0,
            i.e. never decaying)
          - self.active is False, so calculate_motivation() returns {}
          - self._embedding_service is None, which line 154 documents as
            "Set during initialize()"

        Both dependencies are required, not optional. PostgreSQL is the live
        store and all-MiniLM-L6-v2 is present locally. If either is missing
        that is a real fault: without the database no motivation reward is
        ever persisted, and without embeddings every goal looks equally novel.
        Both are logged as errors so the failure is visible rather than silent.
        """
        try:
            self._initialize_dimensions()

            from core.database import get_database_manager
            self.db = get_database_manager()

            from core.memory.utils.embedding_service import get_embedding_service
            self._embedding_service = get_embedding_service()

            await self.load_profile()
            await self._restore_event_rewards()

            self.active = True
            logger.info("Intrinsic motivation system initialized")
            return True

        except Exception as e:
            logger.error(
                f"Failed to initialize motivation system: {e} — "
                f"rewards will not persist and goal novelty cannot be computed"
            )
            return False

    async def shutdown(self) -> None:
        """Shutdown the motivation system"""
        try:
            # Save current profile
            await self.save_profile()
            self.active = False
            logger.info("Intrinsic motivation system shutdown")
        except Exception as e:
            logger.error(f"Error during motivation shutdown: {e}")

    # ========== FEATURE 1: NOVELTY TRACKER ==========
    def _generate_boot_entropy(self) -> str:
        """
        FEATURE 2: ENTROPY INJECTOR
        Generate non-deterministic boot-time context for exploration variance
        """
        # Combine multiple entropy sources
        timestamp = str(time.time())
        process_id = str(random.randint(1000, 9999))
        random_bytes = str(random.getrandbits(256))

        # Create unique hash
        entropy_string = f"{timestamp}_{process_id}_{random_bytes}"
        entropy_hash = hashlib.sha256(entropy_string.encode()).hexdigest()

        # Add human-readable component
        boot_context = f"BOOT_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{entropy_hash[:16]}"
        return boot_context



    async def _store_goal_embedding(self, goal_description: str, theme: str,
                                   component: str, abstraction: str, objective: str) -> None:
        """
        FEATURE 1: NOVELTY TRACKER
        Store goal embedding for similarity checking
        """
        try:
            # Get embedding service if not initialized
            if not self._embedding_service:
                try:
                    from core.memory.utils.embedding_service import get_embedding_service
                    self._embedding_service = get_embedding_service()
                except Exception as e:
                    logger.warning(f"Embedding service unavailable: {e}")
                    return

            # Generate embedding for goal description
            embedding = self._embedding_service.generate_embedding(goal_description)
            if embedding is None:
                logger.warning("Failed to generate embedding for goal")
                return

            # Store to database
            await self._store_goal_embedding_to_db(
                goal_description, theme, component, abstraction, objective,
                np.array(embedding)
            )

            # Also maintain in-memory cache for quick similarity checks (last 100)
            goal_emb = GoalEmbedding(
                description=goal_description,
                embedding=np.array(embedding),
                theme=theme,
                component=component,
                abstraction_level=abstraction,
                objective_type=objective,
                timestamp=datetime.now(),
                repeat_count=await self._get_theme_count_from_db(theme)
            )

            self._goal_embeddings.append(goal_emb)

            # Keep only last 100 embeddings in cache
            if len(self._goal_embeddings) > 100:
                self._goal_embeddings = self._goal_embeddings[-100:]

            logger.debug(f"Stored goal embedding: {theme} (cache: {len(self._goal_embeddings)})")

        except Exception as e:
            logger.error(f"Error storing goal embedding: {e}")

    async def _calculate_goal_similarity(self, goal_description: str) -> Tuple[float, Optional[GoalEmbedding]]:
        """
        FEATURE 1: NOVELTY TRACKER
        Calculate cosine similarity with stored goals
        Returns: (max_similarity, most_similar_goal)
        """
        try:
            if not self._embedding_service:
                return 0.0, None

            # Load from database if cache is empty
            if not self._goal_embeddings:
                self._goal_embeddings = await self._load_goal_embeddings_from_db(limit=100)

            if not self._goal_embeddings:
                return 0.0, None

            # Generate embedding for new goal
            new_embedding = self._embedding_service.generate_embedding(goal_description)
            if new_embedding is None:
                return 0.0, None

            new_emb = np.array(new_embedding)

            # Calculate cosine similarity with all stored goals
            max_similarity = 0.0
            most_similar = None

            for stored_goal in self._goal_embeddings:
                similarity = self._cosine_similarity(new_emb, stored_goal.embedding)
                if similarity > max_similarity:
                    max_similarity = similarity
                    most_similar = stored_goal

            return max_similarity, most_similar

        except Exception as e:
            logger.error(f"Error calculating goal similarity: {e}")
            return 0.0, None

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        try:
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return float(dot_product / (norm_a * norm_b))
        except Exception:
            return 0.0

    async def _calculate_exploration_decay(self, theme: str, base_weight: float = 1.0) -> float:
        """
        FEATURE 3: EXPLORATION DECAY
        Calculate decayed weight based on theme repetition
        Formula: theme_weight = base_weight * exp(-decay_rate * repeat_count)
        """
        # Get count from database
        repeat_count = await self._get_theme_count_from_db(theme)

        # Apply exponential decay
        decayed_weight = base_weight * math.exp(-self._decay_rate * repeat_count)

        logger.debug(f"Theme '{theme}' decay: {repeat_count} repeats → weight {decayed_weight:.3f}")
        return decayed_weight


    async def _increment_theme_count(self, theme: str) -> None:
        """Increment repetition count for a theme"""
        await self._increment_theme_count_in_db(theme)
        # Update in-memory cache as well
        self._theme_counts[theme] = self._theme_counts.get(theme, 0) + 1
        logger.debug(f"Theme '{theme}' count: {self._theme_counts[theme]}")

    def _extract_theme(self, goal_description: str) -> str:
        """Extract high-level theme from goal description"""
        goal_lower = goal_description.lower()

        # Map keywords to themes
        if any(word in goal_lower for word in ['chaos', 'resilience', 'fault injection', 'create_chaos', 'failure propagation', 'recovery']):
            return 'resilience'
        elif any(word in goal_lower for word in ['compare', 'comparative', 'benchmark', 'delta', 'vs ', 'versus', 'pattern']):
            return 'comparative'
        elif any(word in goal_lower for word in ['security', 'audit', 'vulnerability', 'threat', 'authentication', 'sanitiz']):
            return 'security'
        elif any(word in goal_lower for word in ['performance', 'optimize', 'speed', 'latency', 'throughput', 'concurrent']):
            return 'performance'
        elif any(word in goal_lower for word in ['error', 'bug', 'fail', 'crash', 'fix', 'flaky', 'regression']):
            return 'debugging'
        elif any(word in goal_lower for word in ['web_search', 'http_request', 'research', 'paper', 'arxiv', 'framework']):
            return 'world_awareness'
        elif any(word in goal_lower for word in ['learn', 'understand', 'analyze', 'study', 'explore', 'investigate']):
            return 'learning'
        elif any(word in goal_lower for word in ['test', 'run_pytest', 'verify', 'validate', 'coverage']):
            return 'testing'
        elif any(word in goal_lower for word in ['refactor', 'improve', 'trigger_self_improvement', 'benchmark_learning']):
            return 'self_improvement'
        elif any(word in goal_lower for word in ['trace', 'architecture', 'execution path', 'neural_bridge', 'source']):
            return 'architecture'
        elif any(word in goal_lower for word in ['data', 'storage', 'database', 'memory']):
            return 'data'
        else:
            return 'exploration'

    def _extract_component(self, goal_description: str) -> str:
        """Extract target component from goal description"""
        goal_lower = goal_description.lower()

        for component in self._mutation_dimensions['components']:
            if component.lower() in goal_lower:
                return component

        # Default
        return 'system'

    def _extract_abstraction(self, goal_description: str) -> str:
        """Extract abstraction level from goal description"""
        goal_lower = goal_description.lower()

        # High-level indicators
        if any(word in goal_lower for word in ['architecture', 'system', 'design', 'strategy']):
            return 'high'
        # Low-level indicators
        elif any(word in goal_lower for word in ['implementation', 'code', 'function', 'specific']):
            return 'low'
        # Default to medium
        else:
            return 'medium'

    def _extract_objective(self, goal_description: str) -> str:
        """Extract objective type from goal description"""
        goal_lower = goal_description.lower()

        for objective in self._mutation_dimensions['objective_types']:
            if objective.lower() in goal_lower:
                return objective

        # Default based on keywords
        if any(word in goal_lower for word in ['explore', 'investigate', 'discover']):
            return 'explore'
        elif any(word in goal_lower for word in ['fix', 'resolve', 'repair']):
            return 'fix'
        elif any(word in goal_lower for word in ['optimize', 'improve', 'enhance']):
            return 'optimize'
        else:
            return 'learn'

    # =================================================

    def _initialize_dimensions(self) -> None:
        """Initialize all motivation dimensions to baseline values"""
        self.profile.dimensions = {
            MotivationDimension.CURIOSITY: 0.5,
            MotivationDimension.COMPETENCE: 0.5,
            MotivationDimension.NOVELTY: 0.5,
            MotivationDimension.MASTERY: 0.5,
            MotivationDimension.AUTONOMY: 0.5,
            MotivationDimension.SOCIAL: 0.5,
            MotivationDimension.IMPACT: 0.5
        }

    async def calculate_motivation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate intrinsic motivation based on current context

        Args:
            context: Current system context (perception, goals, tasks, etc.)

        Returns:
            Dict with motivation state including dimensions and total reward
        """
        if not self.active:
            logger.warning("Motivation system not active")
            return {}

        try:
            # Extract context information
            perception = context.get("perception")
            system_state = context.get("system_state")
            active_goals = context.get("active_goals", [])
            recent_tasks = context.get("recent_tasks", [])

            # Pull real performance feedback once to ground motivation
            performance_stats = await self.get_domain_performance_stats(domain="all")

            # Calculate each dimension
            dimensions = {}

            # 1. CURIOSITY - desire for novel exploration
            dimensions[MotivationDimension.CURIOSITY] = await self._calculate_curiosity(
                perception, active_goals
            )

            # 2. COMPETENCE - desire for skill improvement
            dimensions[MotivationDimension.COMPETENCE] = await self._calculate_competence(
                recent_tasks, system_state, performance_stats
            )

            # 3. NOVELTY - preference for new experiences
            dimensions[MotivationDimension.NOVELTY] = await self._calculate_novelty(
                perception, active_goals
            )

            # 4. MASTERY - drive for deep understanding
            dimensions[MotivationDimension.MASTERY] = await self._calculate_mastery(
                active_goals, recent_tasks
            )

            # 5. AUTONOMY - need for self-direction
            dimensions[MotivationDimension.AUTONOMY] = await self._calculate_autonomy(
                system_state
            )

            # 6. SOCIAL - motivation for collaboration
            dimensions[MotivationDimension.SOCIAL] = await self._calculate_social(
                context
            )

            # 7. IMPACT - desire for meaningful change
            dimensions[MotivationDimension.IMPACT] = await self._calculate_impact(
                recent_tasks, active_goals, performance_stats
            )

            # Update profile
            self.profile.dimensions = dimensions
            self.profile.last_updated = datetime.now()

            # Calculate total intrinsic reward (weighted sum)
            total_reward = self._calculate_total_reward(dimensions)
            self.profile.total_intrinsic_reward = total_reward

            # Add to history
            self._add_to_history({
                "timestamp": datetime.now().isoformat(),
                "dimensions": dimensions.copy(),
                "total_reward": total_reward
            })

            # Return motivation state
            return {
                "dimensions": dimensions,
                "weights": {
                    "curiosity": self.weights.curiosity,
                    "competence": self.weights.competence,
                    "novelty": self.weights.novelty,
                    "mastery": self.weights.mastery,
                    "autonomy": self.weights.autonomy,
                    "social": self.weights.social,
                    "impact": self.weights.impact
                },
                "total_reward": total_reward,
                # Drive LEVEL (total_reward, weighted mean of the 7 dimensions)
                # and the WORTH of recent experience are different quantities.
                # They shared one field until now, so the second was erased on
                # every refresh and could never reach behaviour.
                "mean_event_reward": self.profile.mean_event_reward,
                "event_reward_count": self.profile.event_reward_count,
                "influence_percentage": self.influence_percentage,
                "timestamp": self.profile.last_updated.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to calculate motivation: {e}")
            return {}

    # =========================================================================
    # DIMENSION CALCULATION METHODS
    # =========================================================================

    # How strongly accumulated experience may shift a drive. Bounded so lived
    # experience modulates disposition without overwhelming the situation in
    # front of the system — an agent whose history drowns out its present is as
    # broken as one with no history at all.
    EXPERIENCE_PRESSURE_GAIN = 0.25

    def _experience_pressure(self) -> float:
        """Exploration pressure implied by recent experience, in [-gain, +gain].

        Negative mean_event_reward (recent experience has been intrinsically
        barren or costly) RAISES seeking pressure; richly-rewarded experience
        lowers it. Returns 0.0 with no history, so a fresh system is driven by
        its situation alone rather than by an imputed mood.
        """
        if not self.profile.event_reward_count:
            return 0.0
        return _clamp(
            -self.profile.mean_event_reward * self.EXPERIENCE_PRESSURE_GAIN,
            -self.EXPERIENCE_PRESSURE_GAIN,
            self.EXPERIENCE_PRESSURE_GAIN,
        )

    async def _calculate_curiosity(self, perception: Any, active_goals: List) -> float:
        """
        Calculate curiosity motivation
        High when encountering novel or unexplored domains
        """
        try:
            # Check for novel information in perception
            novelty_score = 0.5  # Baseline

            if perception:
                # High curiosity if perception contains new/unknown elements
                content = perception.content if hasattr(perception, 'content') else {}
                if content.get("novel_elements") or content.get("unknown_patterns"):
                    novelty_score = 0.8

            # Check if goals involve exploration
            for goal in active_goals:
                if hasattr(goal, 'description'):
                    desc_lower = goal.description.lower()
                    if any(word in desc_lower for word in ["explore", "discover", "investigate", "learn"]):
                        novelty_score = max(novelty_score, 0.7)

            # EXPERIENCE MODULATION — the edge that makes accumulated experience
            # change disposition. Direction follows the principle this class
            # already encodes for competence (success_rate > 0.8 -> drive drops
            # to 0.4, "too easy, low motivation"): when a drive is being well
            # fed, pressure to seek more of it falls; when recent experience has
            # been intrinsically barren or costly, pressure rises.
            novelty_score += self._experience_pressure()

            return max(0.0, min(1.0, novelty_score))

        except Exception as e:
            logger.error(f"Error calculating curiosity: {e}")
            return 0.5

    async def _calculate_competence(
        self,
        recent_tasks: List,
        system_state: Any,
        performance_stats: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Calculate competence motivation
        High when opportunities for skill improvement exist
        """
        try:
            # Heuristic baseline from recent tasks
            baseline = 0.5

            if recent_tasks:
                successful = sum(
                    1
                    for task in recent_tasks
                    if hasattr(task, "status") and getattr(task.status, "value", None) == "completed"
                )
                total = len(recent_tasks)
                success_rate = successful / total if total > 0 else 0.5

                # Moderate success (60-80%) drives highest competence motivation
                # Too easy (>90%) or too hard (<40%) reduces motivation
                if 0.6 <= success_rate <= 0.8:
                    baseline = 0.8  # Optimal challenge level
                elif 0.4 <= success_rate < 0.6:
                    baseline = 0.7  # Challenging but achievable
                elif success_rate > 0.8:
                    baseline = 0.4  # Too easy, low motivation for competence
                else:
                    baseline = 0.6  # Very challenging, moderate motivation

            # Feedback-grounded adjustment from persisted task outcomes
            if performance_stats and performance_stats.get("total_attempts", 0) >= 5:
                db_success = performance_stats.get("success_rate")
                db_conf = performance_stats.get("avg_outcome_label_confidence")
                if db_success is None:
                    db_success, db_conf = 0.5, 0.5   # unmeasured -> neutral, explicitly

                # Map database success/confidence to a competence score
                db_score = 0.5
                if 0.6 <= db_success <= 0.8:
                    db_score = 0.8
                elif 0.4 <= db_success < 0.6:
                    db_score = 0.7
                elif db_success > 0.8:
                    db_score = 0.5  # high success, but maybe low challenge
                else:
                    db_score = 0.6

                # Confidence slightly nudges the score
                db_score = max(0.0, min(1.0, db_score * 0.8 + db_conf * 0.2))

                # Blend baseline heuristic with feedback-grounded score
                return (baseline * 0.6) + (db_score * 0.4)

            return baseline  # Baseline when no reliable feedback yet

        except Exception as e:
            logger.error(f"Error calculating competence: {e}")
            return 0.5

    async def _calculate_novelty(self, perception: Any, active_goals: List) -> float:
        """
        Calculate novelty motivation
        High when new experiences are available
        """
        try:
            novelty_score = 0.5  # Baseline

            # Check if perception indicates new experiences
            if perception and hasattr(perception, 'confidence'):
                # Low confidence suggests novelty (encountering something new)
                if perception.confidence < 0.6:
                    novelty_score = 0.7

            # Check goal novelty
            novel_goals = 0
            for goal in active_goals:
                if hasattr(goal, 'expected_novelty') and goal.expected_novelty > 0.6:
                    novel_goals += 1

            if novel_goals > 0:
                novelty_score = max(novelty_score, 0.6 + (novel_goals * 0.1))

            return min(1.0, novelty_score)

        except Exception as e:
            logger.error(f"Error calculating novelty: {e}")
            return 0.5

    async def _calculate_mastery(self, active_goals: List, recent_tasks: List) -> float:
        """
        Calculate mastery motivation
        High when deep understanding opportunities exist
        """
        try:
            # Check for mastery-oriented goals
            mastery_score = 0.5

            for goal in active_goals:
                if hasattr(goal, 'description'):
                    desc_lower = goal.description.lower()
                    if any(word in desc_lower for word in ["master", "understand", "deep", "comprehensive"]):
                        mastery_score = 0.8
                        break

            # Check if recent tasks involved complex problem-solving
            complex_tasks = 0
            for task in recent_tasks:
                if hasattr(task, 'type') and task.type.value in ["analysis", "synthesis", "research"]:
                    complex_tasks += 1

            if complex_tasks > 2:
                mastery_score = max(mastery_score, 0.7)

            return min(1.0, mastery_score)

        except Exception as e:
            logger.error(f"Error calculating mastery: {e}")
            return 0.5

    async def _calculate_autonomy(self, system_state: Any) -> float:
        """
        Calculate autonomy motivation
        High when system has freedom to make decisions
        """
        try:
            # Check system mode
            autonomy_score = 0.7  # Baseline (assume some autonomy)

            if system_state:
                # Check if in autonomous mode
                if hasattr(system_state, 'mode'):
                    if system_state.mode.value == "autonomous":
                        autonomy_score = 0.9
                    elif system_state.mode.value == "supervised":
                        autonomy_score = 0.4
                    elif system_state.mode.value == "maintenance":
                        autonomy_score = 0.3

            return autonomy_score

        except Exception as e:
            logger.error(f"Error calculating autonomy: {e}")
            return 0.5

    async def _calculate_social(self, context: Dict[str, Any]) -> float:
        """
        Calculate social motivation
        High when collaboration opportunities exist
        """
        try:
            # Check for collaboration indicators
            social_score = 0.4  # Lower baseline (autonomous systems have less social interaction)

            # Check if there are user interactions or team collaboration
            if context.get("user_interactions") or context.get("collaboration_tasks"):
                social_score = 0.7

            # Check if goals involve communication or helping
            active_goals = context.get("active_goals", [])
            for goal in active_goals:
                if hasattr(goal, 'description'):
                    desc_lower = goal.description.lower()
                    if any(word in desc_lower for word in ["help", "collaborate", "communicate", "share"]):
                        social_score = 0.8
                        break

            return social_score

        except Exception as e:
            logger.error(f"Error calculating social: {e}")
            return 0.4

    async def _calculate_impact(
        self,
        recent_tasks: List,
        active_goals: List,
        performance_stats: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Calculate impact motivation
        High when opportunities for meaningful change exist
        """
        try:
            impact_score = 0.5  # Baseline

            # Check if recent tasks had significant outcomes
            high_impact_tasks = 0
            for task in recent_tasks:
                if hasattr(task, "result") and task.result:
                    # Check result magnitude or importance
                    if task.result.get("significant") or task.result.get("system_improvement"):
                        high_impact_tasks += 1

            if high_impact_tasks > 0:
                impact_score = 0.6 + (high_impact_tasks * 0.1)

            # Incorporate global performance feedback: high failure with many attempts
            # increases impact motivation (more to fix), while very stable success
            # can slightly reduce it.
            if performance_stats and performance_stats.get("total_attempts", 0) >= 5:
                failure_rate = performance_stats.get("failure_rate", 0.5)
                total_attempts = performance_stats.get("total_attempts", 0)

                # When many attempts and noticeable failures, raise impact motivation
                if total_attempts >= 10:
                    if failure_rate >= 0.4:
                        impact_score = max(impact_score, 0.8)
                    elif failure_rate <= 0.1:
                        impact_score = min(impact_score, 0.6)

            # Check for impact-oriented goals
            for goal in active_goals:
                if hasattr(goal, "description"):
                    desc_lower = goal.description.lower()
                    if any(word in desc_lower for word in ["improve", "optimize", "enhance", "upgrade", "impact"]):
                        impact_score = max(impact_score, 0.7)

            return min(1.0, impact_score)

        except Exception as e:
            logger.error(f"Error calculating impact: {e}")
            return 0.5

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def _calculate_total_reward(self, dimensions: Dict[str, float]) -> float:
        """Calculate weighted total intrinsic reward"""
        try:
            total = 0.0
            total += dimensions.get(MotivationDimension.CURIOSITY, 0.5) * self.weights.curiosity
            total += dimensions.get(MotivationDimension.COMPETENCE, 0.5) * self.weights.competence
            total += dimensions.get(MotivationDimension.NOVELTY, 0.5) * self.weights.novelty
            total += dimensions.get(MotivationDimension.MASTERY, 0.5) * self.weights.mastery
            total += dimensions.get(MotivationDimension.AUTONOMY, 0.5) * self.weights.autonomy
            total += dimensions.get(MotivationDimension.SOCIAL, 0.5) * self.weights.social
            total += dimensions.get(MotivationDimension.IMPACT, 0.5) * self.weights.impact

            # Normalize by total weight
            total_weight = (
                self.weights.curiosity + self.weights.competence + self.weights.novelty +
                self.weights.mastery + self.weights.autonomy + self.weights.social +
                self.weights.impact
            )

            return total / total_weight if total_weight > 0 else 0.5

        except Exception as e:
            logger.error(f"Error calculating total reward: {e}")
            return 0.5

    # ========================================================================
    # EVENT REWARDS
    #
    # These are NOT the _calculate_<dimension>() drive levels, and must not be
    # implemented by delegating to them.
    #
    #   dimension = "how strongly is this drive active right now"
    #   reward    = "how much did this particular event advance that drive"
    #
    # The competence drive is an inverted-U: a success rate above 0.8 drops it
    # to 0.4 because there is no room left to grow. Aliasing the reward to it
    # would pay the system least exactly when it performs best. The coordinator
    # called these five names for a long time and none of them existed, so
    # every call raised AttributeError -- see the notes on each caller.
    # ========================================================================

    SKILL_HISTORY = 20

    def _skill_history(self) -> Dict[str, List[float]]:
        if not hasattr(self, "_skill_perf"):
            self._skill_perf: Dict[str, List[float]] = {}
        return self._skill_perf

    async def calculate_competence_reward(
        self, skill_name: str, performance: float, success: bool
    ) -> IntrinsicReward:
        """Learning progress on one skill: improvement over its own baseline.

        Absolute performance would pay forever for an already-mastered skill.
        Progress decays toward zero as a skill saturates -- the same behaviour
        the competence drive expresses as its inverted-U, without inverting the
        sign of the reward.
        """
        performance = _clamp(performance)
        history = self._skill_history().setdefault(str(skill_name), [])
        baseline = (sum(history) / len(history)) if history else None

        history.append(performance)
        if len(history) > self.SKILL_HISTORY:
            del history[:-self.SKILL_HISTORY]

        if baseline is None:
            value = 0.5 * performance          # no baseline yet: provisional credit
        else:
            value = performance - baseline     # learning progress; may be negative
        if not success:
            value = min(0.0, value) - 0.1 * (1.0 - performance)

        return IntrinsicReward(
            dimension=MotivationDimension.COMPETENCE,
            reward_value=round(max(-1.0, min(1.0, value)), 4),
            components={
                "performance": performance,
                "baseline": baseline if baseline is not None else performance,
                "observations": float(len(history)),
            },
        )

    async def calculate_curiosity_reward(self, signals: Dict[str, Any]) -> IntrinsicReward:
        """Information gain actually realised.

        question_complexity pays only through answer_depth: a hard question
        left unanswered is curiosity aroused, not curiosity satisfied.
        """
        gain = _clamp(signals.get("information_gain", 0.0))
        reduction = _clamp(signals.get("uncertainty_reduction", 0.0))
        complexity = _clamp(signals.get("question_complexity", 0.0))
        depth = _clamp(signals.get("answer_depth", 0.0))

        value = 0.4 * gain + 0.4 * reduction + 0.2 * (complexity * depth)

        return IntrinsicReward(
            dimension=MotivationDimension.CURIOSITY,
            reward_value=round(_clamp(value), 4),
            components={
                "information_gain": gain,
                "uncertainty_reduction": reduction,
                "resolved_complexity": round(complexity * depth, 4),
            },
        )

    async def calculate_novelty_reward(self, experience: Dict[str, Any]) -> IntrinsicReward:
        """Distance of this experience from the recent ones already recorded.

        Reuses the profile history the system already keeps rather than opening
        a second store of the same thing.
        """
        vector = _numeric_vector(experience)
        if not vector:
            return IntrinsicReward(MotivationDimension.NOVELTY, 0.0, {"comparable_fields": 0.0})

        previous = [
            _numeric_vector(entry.get("experience", {}))
            for entry in (self.profile.history or [])[-self.SKILL_HISTORY:]
        ]
        comparable = [p for p in previous if p and set(p) & set(vector)]

        if not comparable:
            value = 1.0        # nothing to compare against: maximally novel
        else:
            value = min(_normalised_distance(vector, p) for p in comparable)

        self._add_to_history({"experience": experience, "novelty": value})

        return IntrinsicReward(
            dimension=MotivationDimension.NOVELTY,
            reward_value=round(_clamp(value), 4),
            components={"compared_against": float(len(comparable))},
        )

    async def calculate_autonomy_reward(self, signals: Dict[str, Any]) -> IntrinsicReward:
        """Self-direction: acting on its own initiative, with a real choice.

        The exploration term peaks at a balanced ratio -- neither pure
        exploitation nor pure exploration is autonomous behaviour.
        """
        self_initiated = bool(signals.get("self_initiated", False))
        choice_made = bool(signals.get("choice_made", False))
        ratio = _clamp(signals.get("exploration_ratio", 0.5))
        balance = 1.0 - abs(ratio - 0.5) * 2.0

        value = (0.5 if self_initiated else 0.0) + (0.3 if choice_made else 0.0) + 0.2 * balance

        return IntrinsicReward(
            dimension=MotivationDimension.AUTONOMY,
            reward_value=round(_clamp(value), 4),
            components={
                "self_initiated": float(self_initiated),
                "choice_made": float(choice_made),
                "exploration_balance": round(balance, 4),
            },
        )

    # ========================================================================
    # EXPLORATION TARGETS
    #
    # Exposure, not new computation. EpistemicEngine.get_unstable_regions()
    # already returns EpistemicTargets -- high-entropy beliefs and stalled
    # hypotheses -- sorted by entropy descending, and its own docstring calls
    # them "a high-uncertainty region that intrinsic motivation should explore".
    # ========================================================================

    async def get_top_exploration_targets(self, limit: int = 5) -> List[Any]:
        """The most uncertain regions worth exploring, most uncertain first.

        Raises rather than returning [] when the epistemic engine is
        unavailable: "nothing to explore" and "the subsystem is broken" must
        not be the same observation.
        """
        from core.reasoning.epistemic_engine import get_epistemic_engine

        targets = get_epistemic_engine().get_unstable_regions()
        return list(targets or [])[:max(0, int(limit))]

    async def mark_target_explored(self, target_id: str) -> None:
        """Record that a target was acted on.

        Feeds the existing recent-exploration penalty in _calculate_goal_priority
        via the theme counter, so repeatedly chasing the same region is damped.
        """
        await self._increment_theme_count(self._extract_theme(str(target_id)))

    def _add_to_history(self, entry: Dict[str, Any]) -> None:
        """Add motivation calculation to history"""
        try:
            self.profile.history.append(entry)

            # Trim history if too long
            if len(self.profile.history) > self.history_limit:
                self.profile.history = self.profile.history[-self.history_limit:]

        except Exception as e:
            logger.error(f"Error adding to history: {e}")

    async def save_profile(self) -> bool:
        """Save motivation profile to disk"""
        try:
            # Ensure directory exists
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert profile to dict
            profile_dict = {
                "dimensions": self.profile.dimensions,
                "total_intrinsic_reward": self.profile.total_intrinsic_reward,
                "influence_percentage": self.profile.influence_percentage,
                "last_updated": self.profile.last_updated.isoformat() if self.profile.last_updated else None,
                "history": self.profile.history[-50:]  # Save last 50 entries
            }

            # Write to file
            with open(self.profile_path, 'w') as f:
                json.dump(profile_dict, f, indent=2)

            logger.debug(f"Motivation profile saved to {self.profile_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save motivation profile: {e}")
            return False

    async def load_profile(self) -> bool:
        """Load motivation profile from disk"""
        try:
            if not self.profile_path.exists():
                logger.info("No existing motivation profile found, using defaults")
                return False

            with open(self.profile_path, 'r') as f:
                profile_dict = json.load(f)

            # Restore profile
            self.profile.dimensions = profile_dict.get("dimensions", {})
            self.profile.total_intrinsic_reward = profile_dict.get("total_intrinsic_reward", 0.0)
            self.profile.influence_percentage = profile_dict.get("influence_percentage", 0.60)

            last_updated_str = profile_dict.get("last_updated")
            if last_updated_str:
                self.profile.last_updated = datetime.fromisoformat(last_updated_str)

            self.profile.history = profile_dict.get("history", [])

            logger.info(f"Motivation profile loaded from {self.profile_path}")
            return True

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'intrinsic_motivation.load_profile')
            logger.error(f"Failed to load motivation profile: {e}")
            return False

    async def get_motivation_state(self) -> Dict[str, Any]:
        """Get current motivation state"""
        return {
            "dimensions": self.profile.dimensions.copy(),
            "total_reward": self.profile.total_intrinsic_reward,
            "influence_percentage": self.influence_percentage,
            "last_updated": self.profile.last_updated.isoformat() if self.profile.last_updated else None,
            "active": self.active
        }

    async def generate_curiosity_driven_goals(
        self,
        max_goals: int = 1,
        system_context: Optional[Dict[str, Any]] = None
    ) -> List:
        """
        Generate goals using uncertainty-weighted sampling (ICM/RND-inspired).

        No LLM templates - pure metric-driven generation:
        1. Quantify epistemic uncertainty per component
        2. Detect uncertainty gradients (Δ from baseline)
        3. Score candidates: w1*uncertainty + w2*impact + w3*perf_deg + w4*novelty - w5*recent
        4. Sample stochastically from top candidates

        Args:
            max_goals: Maximum number of goals to generate
            system_context: Current system state including errors, metrics, recent tasks

        Returns:
            List of Goal objects with metric-driven priorities
        """
        try:
            from .shared_types import Goal, Priority
            import uuid

            # Step 1: Quantify component uncertainties
            component_metrics = await self._quantify_component_uncertainties(system_context)

            # Steps 2-4: metric-driven goals, only when there are uncertainty
            # signals to drive them.
            goals = []
            if component_metrics:
                uncertainty_deltas = await self._calculate_uncertainty_gradients(component_metrics)
                candidates = []
                for component, metrics in component_metrics.items():
                    priority_score = await self._calculate_goal_priority(
                        component=component,
                        metrics=metrics,
                        delta=uncertainty_deltas.get(component, 0.0)
                    )
                    candidates.append({
                        'component': component,
                        'metrics': metrics,
                        'delta': uncertainty_deltas.get(component, 0.0),
                        'priority_score': priority_score
                    })
                goals = await self._sample_goal_candidates(candidates, max_goals)

            # Step 5: Supplement with epistemic goals (high-entropy beliefs +
            # stalled hypotheses), ranked by entropy from get_unstable_regions().
            # Always attempted — unstable beliefs exist independently of whether
            # any component is currently uncertain, so a "stable" system can
            # still have something to resolve.
            epistemic_budget = max(1, max_goals - len(goals))
            epistemic_goals = await self._generate_epistemic_goals(epistemic_budget)
            goals.extend(epistemic_goals)

            # NO FALLBACK. Goals come only from real substrate signals — component
            # uncertainties and unstable beliefs. When both are empty there is
            # genuinely nothing to be curious about from measured state, and the
            # honest answer is no goal this cycle — never an invented one, and
            # never from the model.
            if not goals:
                logger.info("No uncertainty signals and no unstable beliefs — "
                            "no intrinsic goal this cycle")
                return []

            n_metric = len(goals) - len(epistemic_goals)
            logger.info(
                f"Generated {len(goals)} goals: "
                f"{n_metric} metric-driven, {len(epistemic_goals)} epistemic"
            )
            return goals

        except Exception as e:
            logger.error(f"Error generating curiosity-driven goals: {e}", exc_info=True)
            return []


    async def query_governance_blocks(self) -> List[str]:
        """Query META memory for governance blocks.

        Returns a list of human-readable constraint descriptions derived from
        structured governance_block META memories. Falls back gracefully if
        legacy / non-conforming records are encountered.
        """
        try:
            # Import memory system via unified public entrypoint
            from core.governance.governance_block_schema import GovernanceBlock
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            memory_agent = await get_memory_agent()

            if not memory_agent or not memory_agent.initialized:
                logger.debug("Memory agent not available for governance query")
                return []

            # Query META memories with governance_block tag
            memories = await memory_agent.search_memories(
                query_text="governance_block",
                memory_type=MemoryType.META,
                tags=["governance_block"],
                max_results=50,  # Get recent blocks
                min_importance=0.5,
            )

            if not memories:
                return []

            constraints: List[str] = []
            task_descriptions: set[str] = set()

            for memory in memories:
                try:
                    raw = memory.content

                    # New path: content already a dict with schema marker
                    if isinstance(raw, dict) and raw.get("event") == "governance_block":
                        try:
                            block = GovernanceBlock.from_dict(raw)
                        except Exception as schema_error:
                            logger.debug(
                                "Skipping governance_block memory with invalid schema: %s",
                                schema_error,
                            )
                            continue

                        desc = block.task_description.strip()
                        if desc and desc not in task_descriptions:
                            task_descriptions.add(desc)
                            constraint = f"Avoid: {desc} (blocked: {block.block_reason.strip()})"
                            constraints.append(constraint)
                        continue

                    # Fallback path: legacy string/dict representation
                    content_str = (
                        raw
                        if isinstance(raw, str)
                        else str(raw)
                    )

                    if "task_description" not in content_str:
                        continue

                    # Very simple legacy extraction; retained for backward compatibility
                    try:
                        task_desc_match = content_str.split("task_description")[1].split(",")[0]
                        block_reason_match = (
                            content_str.split("block_reason")[1].split(",")[0]
                            if "block_reason" in content_str
                            else None
                        )
                    except Exception:
                        continue

                    if task_desc_match and task_desc_match not in task_descriptions:
                        task_descriptions.add(task_desc_match)
                        constraint = f"Avoid: {task_desc_match.strip()}"
                        if block_reason_match:
                            constraint += f" (blocked: {block_reason_match.strip()})"
                        constraints.append(constraint)

                except Exception as parse_error:
                    logger.debug("Failed to parse governance block memory: %s", parse_error)
                    continue

            logger.info("🛡️ Found %d governance constraints from META memory", len(constraints))

            return constraints

        except Exception as e:
            logger.error(f"Failed to query governance blocks: {e}")
            return []

    async def get_domain_performance_stats(self, domain: str = "all") -> Dict[str, Any]:
        """
        Query META memory for domain performance statistics

        Args:
            domain: Specific domain or "all" for overall stats

        Returns:
            Dictionary with success rate, failure rate, avg confidence
        """
        try:
            from core.governance.governance_block_schema import task_outcome_from_memory
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            memory_agent = await get_memory_agent()

            # UNMEASURED, not 50%. A fabricated midpoint made "no observations"
            # indistinguishable from "a genuinely coin-flip domain", and every
            # consumer downstream inherited that lie.
            if not memory_agent or not memory_agent.initialized:
                return _unmeasured_stats(domain, reason="memory_agent_unavailable")

            # Query META task outcomes.
            # `domain` used to be passed as query_text, which only nudged
            # semantic ranking — it never constrained the result set, so every
            # domain reported the global average. The domain is filtered below
            # on the authoritative record field instead of a search string.
            memories = await memory_agent.search_memories(
                query_text="task_outcome",
                memory_type=MemoryType.META,
                tags=["task_outcome", "performance_tracking"],
                max_results=500,
            )

            if not memories:
                return _unmeasured_stats(domain, reason="no_task_outcome_memories")

            # Calculate statistics
            successes = 0
            failures = 0
            total_confidence = 0.0

            skipped = 0
            for memory in memories:
                record = task_outcome_from_memory(memory)
                if record is None:
                    # Not a task outcome, or a malformed one. Never guess from
                    # the narrative — a parsed sentence is a second, divergent
                    # reading of an observation that already has a record.
                    skipped += 1
                    continue

                if domain != "all" and record.domain != domain:
                    continue

                if record.outcome == "success":
                    successes += 1
                elif record.outcome == "failure":
                    failures += 1

                total_confidence += float(record.confidence)

            if skipped:
                logger.debug(
                    "get_domain_performance_stats: %d/%d memories carried no "
                    "structured task outcome", skipped, len(memories)
                )

            total = successes + failures
            if total == 0:
                return _unmeasured_stats(domain, reason="no_outcomes_for_domain")

            # STATISTICAL OBSERVATION — deliberately NOT a competence estimate.
            # 4/4 causal successes is an empirical success rate of 1.000; it is
            # not "causal reasoning capability = 1.000". Consumers that need a
            # capability estimate must build one from CapabilityEvidence, which
            # carries the sample size, diversity and recency this cannot.
            stats = {
                "success_rate": successes / total,
                "failure_rate": failures / total,
                # RENAMED. Sitting next to success_rate as `avg_confidence` this
                # read as "confidence in the rate". It is not: it is how sure we
                # were about each individual outcome LABEL. Two different
                # confidences that must never share a field again.
                "avg_outcome_label_confidence": total_confidence / total,
                "successes": successes,
                "failures": failures,
                "total_attempts": total,
                "measured": True,
                "domain": domain,
            }

            logger.info(f"📊 Domain '{domain}' stats: {stats['success_rate']:.1%} success rate ({total} attempts)")

            return stats

        except Exception as e:
            logger.error(f"Failed to get domain performance stats: {e}")
            # A failure to measure is UNMEASURED, never a 50% result.
            return _unmeasured_stats(domain, reason=f"error: {type(e).__name__}")

    # =========================================================================
    # UNCERTAINTY-WEIGHTED GOAL SAMPLING (ICM/RND-Inspired)
    # =========================================================================

    async def _quantify_component_uncertainties(self, system_context: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """
        Step 1: Quantify epistemic uncertainty per component from system signals.

        Distinguishes:
        - Epistemic uncertainty (can be reduced by learning)
        - Aleatoric uncertainty (inherent randomness)
        - Structural flaws (deterministic failures)
        """
        component_metrics = {}

        if not system_context:
            return component_metrics

        # Extract component failures from failed_tasks
        failed_tasks = system_context.get('failed_tasks', [])
        task_stats = {}  # component -> {failures, total, confidence_scores}

        for task in failed_tasks:
            component = self._extract_component_from_task(task)
            if component not in task_stats:
                task_stats[component] = {'failures': 0, 'total': 0, 'confidence_scores': []}

            task_stats[component]['total'] += 1
            if task.get('status') == 'failed':
                task_stats[component]['failures'] += 1

            if 'confidence' in task:
                task_stats[component]['confidence_scores'].append(task['confidence'])

        # Extract performance degradation from performance_metrics
        performance_metrics = system_context.get('performance_metrics', {})

        # Extract error patterns from recent_errors
        recent_errors = system_context.get('recent_errors', [])
        error_stats = {}  # component -> {error_types, error_variance}

        for error in recent_errors:
            component = error.get('component', 'unknown')
            if component not in error_stats:
                error_stats[component] = {'error_types': set(), 'error_count': 0}

            error_stats[component]['error_types'].add(error.get('type', 'unknown'))
            error_stats[component]['error_count'] += 1

        # Extract knowledge gaps
        knowledge_gaps = system_context.get('knowledge_gaps', [])
        gap_stats = {}  # component -> uncertainty_score

        for gap in knowledge_gaps:
            component = gap.get('component', 'unknown')
            gap_stats[component] = gap.get('uncertainty', 0.5)

        # Extract security findings
        security_findings = system_context.get('security_findings', [])
        security_stats = {}  # component -> {severity_score, finding_count}

        severity_map = {'critical': 1.0, 'high': 0.8, 'medium': 0.5, 'low': 0.3}
        for finding in security_findings:
            component = finding.get('component', 'security')
            severity = finding.get('severity', 'medium').lower()
            severity_score = severity_map.get(severity, 0.5)

            if component not in security_stats:
                security_stats[component] = {'severity_score': 0.0, 'finding_count': 0}

            security_stats[component]['severity_score'] = max(
                security_stats[component]['severity_score'],
                severity_score
            )
            security_stats[component]['finding_count'] += 1

        # Combine all signals into component_metrics
        all_components = set(task_stats.keys()) | set(error_stats.keys()) | set(gap_stats.keys()) | set(performance_metrics.keys()) | set(security_stats.keys())

        for component in all_components:
            # Calculate failure_rate
            task_info = task_stats.get(component, {'failures': 0, 'total': 0, 'confidence_scores': []})
            failure_rate = task_info['failures'] / task_info['total'] if task_info['total'] > 0 else 0.0

            # Calculate confidence_variance
            conf_scores = task_info['confidence_scores']
            confidence_variance = np.var(conf_scores) if len(conf_scores) > 1 else 0.0

            # Calculate prediction_error (from performance_metrics if available)
            perf_data = performance_metrics.get(component, {})
            # Ensure perf_data is a dict (could be int/float from malformed system_context)
            if not isinstance(perf_data, dict):
                perf_data = {}
            prediction_error = perf_data.get('prediction_error', failure_rate * 0.7)

            # Calculate performance_degradation
            current_perf = perf_data.get('current', 1.0)
            baseline_perf = perf_data.get('baseline', 1.0)
            performance_degradation = max(0, 1.0 - (current_perf / baseline_perf)) if baseline_perf > 0 else 0.0

            # Calculate epistemic_uncertainty (distinguishing from aleatoric/structural)
            error_info = error_stats.get(component, {'error_types': set(), 'error_count': 0})
            error_diversity = len(error_info['error_types'])

            # High variance + high error = epistemic (learnable)
            # Low variance + high error = aleatoric or structural flaw
            if confidence_variance > 0.15 and prediction_error > 0.3:
                epistemic_uncertainty = min(0.9, prediction_error + confidence_variance * 0.5)
            elif confidence_variance < 0.05 and prediction_error > 0.4:
                # Deterministic failure - structural, not epistemic
                epistemic_uncertainty = 0.2
            else:
                # Mix of epistemic and aleatoric
                epistemic_uncertainty = gap_stats.get(component, prediction_error * 0.6)

            # Boost uncertainty for security findings
            sec_info = security_stats.get(component, {})
            if sec_info:
                security_boost = sec_info.get('severity_score', 0.0) * 0.7
                epistemic_uncertainty = min(0.95, epistemic_uncertainty + security_boost)

            # Calculate impact_radius based on component type
            impact_radius = self._calculate_impact_radius(component, error_info['error_count'])

            # Calculate novelty_potential (inverse of exploration frequency)
            theme = self._extract_theme(component)
            exploration_frequency = await self._get_theme_count_from_db(theme)
            novelty_potential = max(0.1, 1.0 - (exploration_frequency * 0.1))

            component_metrics[component] = {
                'epistemic_uncertainty': round(epistemic_uncertainty, 3),
                'confidence_variance': round(confidence_variance, 3),
                'prediction_error': round(prediction_error, 3),
                'failure_rate': round(failure_rate, 3),
                'impact_radius': impact_radius,
                'performance_degradation': round(performance_degradation, 3),
                'novelty_potential': round(novelty_potential, 3)
            }

        return component_metrics

    def _extract_component_from_task(self, task: Dict[str, Any]) -> str:
        """Extract component name from task description or metadata"""
        if 'component' in task:
            return task['component']

        description = task.get('description', '').lower()
        # Map keywords to components
        component_keywords = {
            'memory': 'memory_agent',
            'neural': 'neural_bridge',
            'llm': 'unified_llm',
            'learning': 'learning',
            'security': 'security',
            'tool': 'tool_execution',
            'database': 'database',
            'api': 'api_layer'
        }

        for keyword, component in component_keywords.items():
            if keyword in description:
                return component

        return 'unknown'

    def _calculate_impact_radius(self, component: str, error_count: int) -> float:
        """Calculate impact radius: 0.0=component, 0.5=system, 1.0=user-facing"""
        # User-facing components have highest impact
        user_facing = ['api_layer', 'unified_llm', 'security']
        system_critical = ['memory_agent', 'neural_bridge', 'database']

        if component in user_facing:
            base_impact = 1.0
        elif component in system_critical:
            base_impact = 0.7
        else:
            base_impact = 0.3

        # Scale by error frequency
        error_multiplier = min(1.0, 1.0 + (error_count * 0.05))
        return min(1.0, base_impact * error_multiplier)

    async def _calculate_uncertainty_gradients(self, component_metrics: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """
        Step 2: Calculate uncertainty gradients (Δ from rolling baseline).

        Rising uncertainty is more important than static high uncertainty.
        """
        deltas = {}

        for component, metrics in component_metrics.items():
            epistemic = metrics.get('epistemic_uncertainty', 0.0)

            # Get baseline from database
            baseline_data = await self._get_component_baseline_from_db(component)

            if not baseline_data:
                # First observation, no gradient
                baseline_data = {'epistemic_uncertainty': epistemic}
                await self._update_component_baseline_in_db(component, baseline_data)
                deltas[component] = 0.0
            else:
                baseline = baseline_data.get('epistemic_uncertainty', epistemic)
                deltas[component] = epistemic - baseline

                # Update rolling baseline (exponential moving average, α=0.3)
                new_baseline = 0.3 * epistemic + 0.7 * baseline
                baseline_data['epistemic_uncertainty'] = new_baseline
                await self._update_component_baseline_in_db(component, baseline_data)

                # Also update in-memory cache
                self._component_baselines[component] = baseline_data

            # Store in history (both database and memory cache)
            await self._store_metric_history_to_db(component, metrics)

            # Update in-memory cache
            if component not in self._metric_history:
                self._metric_history[component] = []
            self._metric_history[component].append(metrics.copy())
            # Keep last 50 entries in cache
            if len(self._metric_history[component]) > 50:
                self._metric_history[component] = self._metric_history[component][-50:]

        return deltas

    async def _calculate_goal_priority(self, component: str, metrics: Dict[str, float], delta: float) -> float:
        """
        Step 3: Calculate weighted priority score.

        GoalPriority =
            w1 * EpistemicUncertainty
          + w2 * ImpactRadius
          + w3 * PerformanceDegradation
          + w4 * NoveltyPotential
          - w5 * RecentExplorationPenalty
        """
        w = self._priority_weights

        # Extract metrics
        epistemic_uncertainty = metrics.get('epistemic_uncertainty', 0.0)
        impact_radius = metrics.get('impact_radius', 0.5)  # 0=component, 0.5=system, 1.0=user-facing
        perf_degradation = metrics.get('performance_degradation', 0.0)
        novelty_potential = metrics.get('novelty_potential', 0.5)

        # Recent exploration penalty (have we explored this component recently?)
        recent_penalty = 0.0
        theme = self._extract_theme(component)
        repeat_count = await self._get_theme_count_from_db(theme)
        if repeat_count > 0:
            recent_penalty = min(repeat_count * 0.1, 1.0)  # Cap at 1.0

        # Boost for rising uncertainty (gradient)
        uncertainty_with_gradient = epistemic_uncertainty + max(0, delta) * 0.5

        priority = (
            w['epistemic_uncertainty'] * uncertainty_with_gradient +
            w['impact_radius'] * impact_radius +
            w['performance_degradation'] * perf_degradation +
            w['novelty_potential'] * novelty_potential +
            w['recent_exploration_penalty'] * recent_penalty
        )

        return max(0.0, priority)  # No negative priorities

    async def _sample_goal_candidates(self, candidates: List[Dict], max_goals: int) -> List:
        """
        Step 4: Stochastic sampling from top candidates (softmax).

        Avoids deterministic "always pick highest" which causes tunneling.
        """
        from .shared_types import Goal, Priority
        import uuid

        if not candidates:
            return []

        # Sort by priority
        candidates_sorted = sorted(candidates, key=lambda x: x['priority_score'], reverse=True)

        # Take top 2*max_goals candidates
        top_candidates = candidates_sorted[:max_goals * 2]

        if not top_candidates:
            return []

        # Softmax sampling (temperature = 0.5 for moderate stochasticity)
        scores = np.array([c['priority_score'] for c in top_candidates])
        temperature = 0.5
        exp_scores = np.exp(scores / temperature)
        probabilities = exp_scores / exp_scores.sum()

        # Sample without replacement
        num_to_sample = min(max_goals, len(top_candidates))
        # Use boot-entropy-seeded RNG to avoid identical early-session sampling
        # when metrics are stable.
        rng = getattr(self, "_entropy_np_rng", None)
        if rng is None:
            sampled_indices = np.random.choice(
                len(top_candidates),
                size=num_to_sample,
                replace=False,
                p=probabilities
            )
        else:
            sampled_indices = rng.choice(
                len(top_candidates),
                size=num_to_sample,
                replace=False,
                p=probabilities
            )

        # Generate goals from sampled candidates
        goals = []
        for idx in sampled_indices:
            candidate = top_candidates[idx]
            goal = await self._create_metric_driven_goal(candidate)
            if goal:
                goals.append(goal)

        return goals

    async def _create_metric_driven_goal(self, candidate: Dict):
        """
        Create goal directly from metrics - NO LLM, NO templates.

        Format: "component shows X variance and Y error (Δ +Z from baseline) → action"
        """
        from .shared_types import Goal, Priority
        import uuid

        component = candidate['component']
        metrics = candidate['metrics']
        delta = candidate['delta']
        priority_score = candidate['priority_score']

        # AN ABSENT METRIC IS NOT A GOOD SCORE.
        #
        # These defaulted to 0.0, and every gate below reads them as "better
        # than threshold": 0.0 prediction_error and 0.0 failure_rate mean
        # flawless, 0.0 confidence_variance means perfectly certain. So a
        # component whose metrics were never collected produced the same
        # reading as a component measured as healthy — and since the whole
        # point of this generator is to raise goals about components that are
        # doing BADLY, missing data silently suppressed exactly the goals it
        # exists to create. The worse the instrumentation, the healthier the
        # component looked.
        #
        # Absent stays absent. Present-but-zero is still a real measurement and
        # is kept, so this distinguishes "measured 0.0" from "never measured".
        MEASURES = ('epistemic_uncertainty', 'confidence_variance',
                    'prediction_error', 'failure_rate')
        measured = {k: metrics[k] for k in MEASURES
                    if metrics.get(k) is not None}

        if not measured:
            logger.debug(
                "No metric measured for %s (%s absent); no metric-driven goal — "
                "a goal about performance cannot be built from missing data",
                component, "/".join(MEASURES))
            return None

        epistemic_unc = measured.get('epistemic_uncertainty')
        confidence_var = measured.get('confidence_variance')
        prediction_error = measured.get('prediction_error')
        failure_rate = measured.get('failure_rate')

        def over(value, threshold):
            """True only when a MEASURED value exceeds the threshold."""
            return value is not None and value > threshold

        # Build metric-driven description
        metric_summary = f"{component} shows "
        metric_parts = []

        if over(confidence_var, 0.2):
            metric_parts.append(f"{confidence_var:.2f} confidence variance")
        if over(prediction_error, 0.3):
            metric_parts.append(f"{prediction_error:.0%} prediction error")
        if over(failure_rate, 0.2):
            metric_parts.append(f"{failure_rate:.0%} failure rate")

        if not metric_parts:
            # Name whichever measure actually exists, rather than printing a
            # fabricated 0.00 epistemic uncertainty for a component that was
            # measured on a different axis entirely.
            key, value = next(iter(measured.items()))
            metric_parts.append(f"{value:.2f} {key.replace('_', ' ')}")

        metric_summary += ", ".join(metric_parts)

        # Add gradient if significant
        if abs(delta) > 0.1:
            metric_summary += f" (Δ {delta:+.2f} from baseline)"

        # Determine action based on dominant signal
        if over(prediction_error, 0.4):
            action = "analyze prediction failures and model assumptions"
        elif over(failure_rate, 0.4):
            action = "investigate failure patterns and error handling"
        elif over(confidence_var, 0.3):
            action = "profile uncertainty sources and input distribution"
        else:
            action = "explore capability boundaries and edge cases"

        description = f"{metric_summary} → {action}"

        # NOVELTY IS NOT A GATE AND NOT A PRIORITY INPUT. Whether this component
        # merits a goal, and its priority, are decided by the measured metrics
        # above — deterministic and model-free. MiniLM's similarity is computed
        # and stored ONLY for DOWNSTREAM dedup/retrieval (recorded as metadata,
        # maintaining the embedding index); it never suppresses a metric-valid
        # goal and never feeds the goal's priority/novelty fields. Severing MiniLM
        # must not change whether the goal forms OR how it ranks.
        similarity, _ = await self._calculate_goal_similarity(description)

        # Store embedding (maintain the index for downstream novelty/retrieval)
        theme = self._extract_theme(description)
        await self._store_goal_embedding(description, theme, component, "metric_driven", "investigate")
        await self._increment_theme_count(theme)

        # Create goal
        goal = Goal(
            id=f"intrinsic_goal_{uuid.uuid4().hex[:8]}",
            description=description,
            priority=Priority.LOW,
            # Derived from measurements, never from a substituted default: a
            # curiosity value invented from an absent uncertainty is a number
            # the ranker cannot tell from a real one.
            curiosity_value=(epistemic_unc * 0.9) if epistemic_unc is not None
                            else float(priority_score),
            # DETERMINISTIC — the theme-frequency novelty the substrate measures.
            # MiniLM does not feed this.
            expected_novelty=(metrics['novelty_potential'] * 0.8
                              if metrics.get('novelty_potential') is not None else 1.0),
            expected_competence_gain=0.7,
            intrinsic_reward_potential=priority_score
        )

        # Tag goal with source component and pre-task uncertainty for closed-loop completion gate
        goal.metadata["target_component"] = component
        goal.metadata["uncertainty_before"] = epistemic_unc
        goal.metadata["novelty_similarity"] = similarity  # guidance, not a gate

        logger.info(f"Created metric-driven goal (priority={priority_score:.2f}): {description[:80]}...")
        return goal


    async def _generate_epistemic_goals(self, max_goals: int) -> List:
        """
        Generate goals targeting high-entropy beliefs and stalled hypotheses.

        Queries EpistemicEngine.get_unstable_regions() for the current set of
        beliefs with entropy > 0.85 and stalled hypotheses (old + low evidence).
        Returns Goal objects tagged with requires_epistemic_output=True so the
        executor gate enforces that completing them mutates the belief graph.

        Priority is proportional to entropy: high entropy = high exploration drive.
        Does NOT invert — we want to explore uncertainty, not certainty.

        Args:
            max_goals: Maximum number of epistemic goals to return.

        Returns:
            List of Goal objects (may be empty if no unstable regions found).
        """
        if max_goals <= 0:
            return []

        from .shared_types import Goal, Priority
        import uuid

        try:
            from core.reasoning.epistemic_engine import get_epistemic_engine
            targets = get_epistemic_engine().get_unstable_regions()
        except Exception as e:
            logger.warning(f"_generate_epistemic_goals: EpistemicEngine unavailable: {e}")
            return []

        if not targets:
            return []

        goals = []
        for target in targets[:max_goals]:
            description = target.description

            # Novelty is GUIDANCE, not a veto. An unstable belief that needs
            # resolving does not stop mattering because a similar goal was issued
            # — the entropy decides. Similarity is kept as metadata guidance (and
            # for downstream dedup), never a suppressor of a real epistemic goal.
            try:
                similarity, _ = await self._calculate_goal_similarity(description)
            except Exception:
                similarity = 0.0
                self.logger.warning("Novelty check failed: %s", description)

            # Store embedding for future novelty checks
            try:
                theme = self._extract_theme(description)
                await self._store_goal_embedding(
                    description, theme, target.domain, "epistemic", "investigate"
                )
                await self._increment_theme_count(theme)
            except Exception as e:
                self.logger.error("Error storing goal embedding: %s", str(e))

            # Priority proportional to entropy: [0.85, 1.0] → [0.0, 1.0]
            priority_score = (target.entropy - 0.85) / 0.15
            priority_score = max(0.05, min(1.0, priority_score))

            goal = Goal(
                id=f"epistemic_goal_{uuid.uuid4().hex[:8]}",
                description=description,
                priority=Priority.MEDIUM if priority_score > 0.5 else Priority.LOW,
                curiosity_value=target.entropy,
                # DETERMINISTIC. MiniLM does not feed priority/novelty; the goal
                # forms and ranks from entropy either way.
                expected_novelty=0.8,
                expected_competence_gain=0.6,
                intrinsic_reward_potential=priority_score,
            )
            # Tag with all epistemic metadata — executor and coordinator read this
            goal.metadata.update(target.metadata)
            goal.metadata["novelty_similarity"] = similarity  # guidance, not a gate

            logger.info(
                f"Epistemic goal (entropy={target.entropy:.3f}, "
                f"type={target.target_type}): {description[:80]}..."
            )
            goals.append(goal)

        return goals

    # =========================================================================
    # PLAN DIVERSITY ENFORCEMENT & TOOL REPETITION PENALTY
    # =========================================================================

    async def track_tool_sequence(self, tools_used: List[str]):
        """Track tool sequence for this iteration to detect repetition"""
        # Store to database
        await self._store_tool_sequence(tools_used)

        # Also maintain in-memory cache
        self._tool_sequence_history.append(tools_used.copy())

        # Keep only last N iterations in cache
        if len(self._tool_sequence_history) > self._max_sequence_history:
            self._tool_sequence_history = self._tool_sequence_history[-self._max_sequence_history:]

    async def detect_sequence_repetition(self, proposed_tools: List[str]) -> bool:
        """
        Detect if proposed tool sequence repeats recent patterns.

        Returns True if sequence should be blocked.
        """
        # Load from database if cache is empty
        if not self._tool_sequence_history:
            self._tool_sequence_history = await self._get_recent_tool_sequences(limit=self._max_sequence_history)

        if len(self._tool_sequence_history) < 2:
            return False

        # Check if last 2 iterations used same sequence
        if len(self._tool_sequence_history) >= 2:
            last_two = self._tool_sequence_history[-2:]
            if last_two[0] == last_two[1] == proposed_tools:
                logger.warning(f"🚫 Blocking repeated tool sequence: {proposed_tools}")
                return True

        # Check if proposed sequence matches any of last 3 iterations
        recent = self._tool_sequence_history[-3:]
        if proposed_tools in recent:
            logger.warning(f"🚫 Tool sequence appeared {recent.count(proposed_tools)} times recently: {proposed_tools}")
            return True

        return False

    async def apply_tool_cooldowns(self, available_tools: List[str]) -> List[str]:
        """
        Apply cooldown penalties to tools that failed repeatedly.

        Returns filtered list of tools with cooldowns removed.
        """
        # Load cooldowns from database
        self._tool_cooldowns = await self._get_all_tool_cooldowns()

        # Decrement all cooldowns
        for tool in list(self._tool_cooldowns.keys()):
            self._tool_cooldowns[tool] -= 1
            if self._tool_cooldowns[tool] <= 0:
                del self._tool_cooldowns[tool]
                await self._delete_tool_cooldown(tool)
                logger.info(f"✓ Tool '{tool}' cooldown expired")
            else:
                await self._store_tool_cooldown(tool, self._tool_cooldowns[tool])

        # Filter out tools on cooldown
        filtered = [t for t in available_tools if t not in self._tool_cooldowns]

        if len(filtered) < len(available_tools):
            blocked = set(available_tools) - set(filtered)
            logger.info(f"🔒 Tools on cooldown: {blocked}")

        return filtered

    async def record_tool_failure(self, tool_name: str, params: Dict[str, Any], error_message: str):
        """
        Record tool failure and apply cooldown if threshold reached.

        After 2 consecutive failures → 3 iteration cooldown.
        """
        # Load failure count from database
        failure_count = await self._get_tool_failure_count(tool_name)
        failure_count += 1

        # Store updated failure count
        await self._store_tool_failure_count(tool_name, failure_count)

        # Update in-memory cache
        self._tool_failure_counts[tool_name] = failure_count

        # Store failed parameter pattern (in-memory for now, could be DB too)
        if tool_name not in self._failed_parameter_patterns:
            self._failed_parameter_patterns[tool_name] = []

        self._failed_parameter_patterns[tool_name].append({
            'params': params.copy(),
            'error': error_message,
            'timestamp': time.time()
        })

        # Apply cooldown after 2 failures
        if failure_count >= 2:
            await self._store_tool_cooldown(tool_name, 3)  # 3 iteration cooldown
            self._tool_cooldowns[tool_name] = 3
            logger.warning(f"⚠️  Tool '{tool_name}' failed {failure_count} times → 3 iteration cooldown")

            # Reset failure counter
            await self._store_tool_failure_count(tool_name, 0)
            self._tool_failure_counts[tool_name] = 0

    async def record_tool_success(self, tool_name: str):
        """Reset failure counter on success"""
        # Remove from database
        await self.db.execute_query(
            """
            DELETE FROM tool_tracking_state
            WHERE tool_name = $1 AND tracking_type = 'failure_count'
            """,
            params=(tool_name,),
            commit=True
        ) if self.db else None

        # Remove from cache
        if tool_name in self._tool_failure_counts:
            del self._tool_failure_counts[tool_name]

    def detect_non_adaptive_retry(self, tool_name: str, params: Dict[str, Any]) -> bool:
        """
        Detect if tool call is retrying with similar parameters after schema error.

        Blocks calls that:
        1. Failed due to missing required parameters
        2. Are being retried with empty or incomplete parameters

        Returns True if retry should be blocked.
        """
        if tool_name not in self._failed_parameter_patterns:
            return False

        recent_failures = self._failed_parameter_patterns[tool_name]
        if not recent_failures:
            return False

        # Check last failure
        last_failure = recent_failures[-1]
        last_params = last_failure['params']
        last_error_msg = last_failure['error']

        # Detect schema errors
        schema_error_keywords = ['missing', 'required', 'parameter', 'schema', 'validation', 'field']
        is_schema_error = any(keyword in last_error_msg.lower() for keyword in schema_error_keywords)

        if not is_schema_error:
            return False

        # Extract missing field from error message
        missing_field = self._extract_missing_field(last_error_msg)

        if missing_field:
            # Check if retry still missing the same field
            if missing_field not in params or params.get(missing_field) in [None, {}, [], '']:
                logger.error(f"🚫 Blocking non-adaptive retry of '{tool_name}': still missing '{missing_field}' after schema error")
                logger.error(f"   Last error: {last_error_msg}")
                logger.error(f"   Current params: {params}")
                return True

        # Check if parameters are identical or still incomplete
        param_signature = self._get_param_signature(params)
        last_param_signature = self._get_param_signature(last_params)

        if param_signature == last_param_signature:
            logger.error(f"🚫 Blocking identical retry of '{tool_name}' after schema error")
            return True

        # Check if parameters are still mostly empty
        if self._params_mostly_empty(params):
            logger.error(f"🚫 Blocking retry of '{tool_name}' with empty parameters after schema error")
            return True

        return False

    def _extract_missing_field(self, error_message: str) -> Optional[str]:
        """Extract missing field name from error message"""
        import re

        patterns = [
            r"missing required parameter[:\s]+(\w+)",
            r"parameter '(\w+)' is required",
            r"'(\w+)' is required",
            r"missing.*field[:\s]+(\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, error_message.lower())
            if match:
                return match.group(1)

        return None

    def _get_param_signature(self, params: Dict[str, Any]) -> str:
        """Generate signature for parameter set (for comparison)"""
        import json
        import hashlib

        # Normalize params for comparison
        normalized = {
            k: str(type(v).__name__) if v is not None else 'None'
            for k, v in sorted(params.items())
        }

        return hashlib.md5(json.dumps(normalized, sort_keys=True).encode()).hexdigest()

    def _params_mostly_empty(self, params: Dict[str, Any]) -> bool:
        """Check if parameters are mostly empty/default values"""
        if not params:
            return True

        empty_values = [None, {}, [], '', 0]
        empty_count = sum(1 for v in params.values() if v in empty_values)

        # If more than 70% of params are empty
        return (empty_count / len(params)) > 0.7

    # =========================================================================
    # DATABASE PERSISTENCE METHODS
    # =========================================================================

    async def _store_goal_embedding_to_db(self, goal_description: str, theme: str,
                                          component: str, abstraction: str, objective: str,
                                          embedding: np.ndarray) -> None:
        """Store goal embedding to novelty_detections table"""
        if not self.db:
            return

        try:
            experience_hash = hashlib.md5(goal_description.encode()).hexdigest()

            # Calculate novelty score (0 if first time, otherwise based on similarity)
            novelty_score = 1.0  # Default high novelty for new goals

            await self.db.execute_query(
                """
                INSERT INTO novelty_detections (
                    id,
                    timestamp,
                    experience_hash,
                    novelty_score,
                    context,
                    metadata
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                params=(
                    f"novelty_{int(time.time() * 1000)}_{experience_hash[:8]}",
                    datetime.now(),
                    experience_hash,
                    float(novelty_score),
                    json.dumps({'description': goal_description, 'theme': theme}),
                    json.dumps({
                        'theme': theme,
                        'component': component,
                        'abstraction_level': abstraction,
                        'objective_type': objective,
                        'embedding': embedding.tolist() if isinstance(embedding, np.ndarray) else embedding,
                        'repeat_count': await self._get_theme_count_from_db(theme),
                    }),
                ),
                commit=True,
            )

            logger.debug(f"Stored goal embedding to DB: {theme}")

        except Exception as e:
            logger.error(f"Failed to store goal embedding to DB: {e}")

    async def _load_goal_embeddings_from_db(self, limit: int = 100) -> List[GoalEmbedding]:
        """Load recent goal embeddings from novelty_detections table"""
        if not self.db:
            return []

        try:
            results = await self.db.execute_query(
                """
                SELECT context, metadata, timestamp
                FROM novelty_detections
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                params=(limit,),
                fetch_all=True,
            )

            if not results:
                return []

            goal_embeddings = []
            for row in results:
                try:
                    context = json.loads(row['context']) if isinstance(row['context'], str) else row['context']
                    metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

                    embedding_data = metadata.get('embedding', [])
                    embedding = np.array(embedding_data) if embedding_data else np.zeros(384)

                    goal_emb = GoalEmbedding(
                        description=context.get('description', ''),
                        embedding=embedding,
                        theme=metadata.get('theme', 'unknown'),
                        component=metadata.get('component', 'unknown'),
                        abstraction_level=metadata.get('abstraction_level', 'medium'),
                        objective_type=metadata.get('objective_type', 'explore'),
                        timestamp=row['timestamp'],
                        repeat_count=metadata.get('repeat_count', 0)
                    )
                    goal_embeddings.append(goal_emb)

                except Exception as parse_error:
                    logger.debug(f"Failed to parse goal embedding row: {parse_error}")
                    continue

            logger.debug(f"Loaded {len(goal_embeddings)} goal embeddings from DB")
            return goal_embeddings

        except Exception as e:
            logger.error(f"Failed to load goal embeddings from DB: {e}")
            return []

    async def _restore_event_rewards(self, window: int = 100) -> None:
        """Reload recent event rewards so drive state survives a restart.

        unified.intrinsic_motivation already held every reward ever computed and
        NOTHING read them back: the only query against this table filters
        motivation_type='theme_count'. Rewards were write-only, so on every
        restart the system's sense of how worthwhile its recent experience had
        been reset to zero.
        """
        if not self.db:
            logger.warning("Cannot restore event rewards: no database handle")
            return
        try:
            # get_database_manager() hands back an UNINITIALISED manager; whether
            # someone else has initialised it by now is an ordering accident.
            # initialize() is idempotent, so make this self-sufficient rather
            # than silently restoring zero rewards.
            if not getattr(self.db, 'initialized', False):
                await self.db.initialize()

            rows = await self.db.execute_query(
                """
                SELECT score FROM intrinsic_motivation
                WHERE motivation_type = 'task_outcome'
                ORDER BY timestamp DESC LIMIT $1
                """,
                params=(window,),
                fetch_all=True,
            )
            if not rows:
                return
            values = [float(r['score']) for r in rows if r['score'] is not None]
            if not values:
                return
            self.profile.accumulated_event_reward = sum(values)
            self.profile.event_reward_count = len(values)
            logger.info(
                "Restored %d event rewards (mean %.4f) from unified.intrinsic_motivation",
                len(values), self.profile.mean_event_reward,
            )
        except Exception as e:
            logger.warning(f"Could not restore event rewards: {e}")

    async def _get_theme_count_from_db(self, theme: str) -> int:
        """Get theme repetition count from database"""
        if not self.db:
            return 0

        try:
            results = await self.db.execute_query(
                """
                SELECT COUNT(*) AS count
                FROM intrinsic_motivation
                WHERE motivation_type = 'theme_count' AND context = $1
                """,
                params=(theme,),
                fetch_all=True,
            )

            if results and len(results) > 0:
                return results[0]['count']
            return 0

        except Exception as e:
            logger.error(f"Failed to get theme count from DB: {e}")
            return 0

    async def _increment_theme_count_in_db(self, theme: str) -> None:
        """Increment theme repetition count in database"""
        if not self.db:
            return

        try:
            # Insert or update theme count
            await self.db.execute_query(
                """
                INSERT INTO intrinsic_motivation (
                    id,
                    timestamp,
                    motivation_type,
                    score,
                    context,
                    metadata
                ) VALUES ($1, $2, 'theme_count', 1, $3, $4)
                ON CONFLICT (id) DO UPDATE SET
                    score = intrinsic_motivation.score + 1,
                    timestamp = EXCLUDED.timestamp,
                    metadata = EXCLUDED.metadata
                """,
                params=(
                    f"theme_{theme}_{int(time.time())}",
                    datetime.now(),
                    theme,
                    json.dumps({'theme': theme, 'updated': datetime.now().isoformat()}),
                ),
                commit=True,
            )

            logger.debug(f"Incremented theme count in DB: {theme}")

        except Exception as e:
            logger.error(f"Failed to increment theme count in DB: {e}")

    async def _get_component_baseline_from_db(self, component: str) -> Optional[Dict[str, float]]:
        """Get component baseline metrics from component_health table"""
        if not self.db:
            return None

        try:
            results = await self.db.execute_query(
                """
                SELECT metadata, health_score, last_updated
                FROM component_health
                WHERE component_name = $1
                ORDER BY last_updated DESC
                LIMIT 1
                """,
                params=(component,),
                fetch_all=True,
            )

            if results and len(results) > 0:
                row = results[0]
                metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

                return {
                    'epistemic_uncertainty': metadata.get('epistemic_uncertainty', 0.5),
                    'impact_radius': metadata.get('impact_radius', 0.5),
                    'performance_degradation': metadata.get('performance_degradation', 0.0),
                    'novelty_potential': metadata.get('novelty_potential', 0.5),
                    'health_score': float(row['health_score']) if row['health_score'] else 0.5
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get component baseline from DB: {e}")
            return None

    async def _update_component_baseline_in_db(self, component: str, metrics: Dict[str, float]) -> None:
        """Update component baseline metrics in component_health table"""
        if not self.db:
            return

        try:
            # Calculate health score from metrics
            # 0-100, the scale unified.component_health is declared on
            # (ComponentHealth.health_score: float = 100.0  # 0-100) and the
            # scale every consumer gates against: assessment treats < 90 as
            # needing improvement, and the deployment hard gate blocks below 80.
            # Writing the raw 0-1 value put rows of 0.8-1.0 in that column, so
            # every component read as catastrophically unhealthy -- assessment
            # fired on all of them and the deployment gate could never open.
            health_score = (1.0 - metrics.get('epistemic_uncertainty', 0.5)) * 100.0

            await self.db.execute_query(
                """
                INSERT INTO component_health (
                    component_name,
                    status,
                    error_count,
                    success_count,
                    health_score,
                    last_updated,
                    metadata
                ) VALUES ($1, $2, 0, 0, $3, $4, $5)
                ON CONFLICT (component_name) DO UPDATE SET
                    health_score = EXCLUDED.health_score,
                    last_updated = EXCLUDED.last_updated,
                    metadata = EXCLUDED.metadata
                """,
                params=(
                    component,
                    'monitoring',
                    float(health_score),
                    datetime.now(),
                    json.dumps(metrics),
                ),
                commit=True,
            )

            logger.debug(f"Updated component baseline in DB: {component}")

        except Exception as e:
            logger.error(f"Failed to update component baseline in DB: {e}")

    async def _store_metric_history_to_db(self, component: str, metrics: Dict[str, float]) -> None:
        """Store metric history entry to component_health table"""
        if not self.db:
            return

        try:
            # 0-100, the scale unified.component_health is declared on
            # (ComponentHealth.health_score: float = 100.0  # 0-100) and the
            # scale every consumer gates against: assessment treats < 90 as
            # needing improvement, and the deployment hard gate blocks below 80.
            # Writing the raw 0-1 value put rows of 0.8-1.0 in that column, so
            # every component read as catastrophically unhealthy -- assessment
            # fired on all of them and the deployment gate could never open.
            health_score = (1.0 - metrics.get('epistemic_uncertainty', 0.5)) * 100.0

            await self.db.execute_query(
                """
                INSERT INTO component_health (
                    component_name, status, error_count, success_count,
                    health_score, last_updated, metadata
                ) VALUES ($1, 'history', 0, 0, $2, $3, $4)
                ON CONFLICT (component_name) 
                DO UPDATE SET
                    health_score = EXCLUDED.health_score,
                    last_updated = EXCLUDED.last_updated,
                    metadata = EXCLUDED.metadata
                """,
                params=(
                    component,
                    health_score,
                    datetime.now(),
                    json.dumps(metrics)
                ),
                commit=True
            )

            logger.debug(f"Stored metric history to DB: {component}")

        except Exception as e:
            logger.error(f"Failed to store metric history to DB: {e}")

    async def _load_metric_history_from_db(self, component: str, limit: int = 50) -> List[Dict[str, float]]:
        """Load metric history from component_health table"""
        if not self.db:
            return []

        try:
            results = await self.db.execute_query(
                """
                SELECT metadata, last_updated
                FROM component_health
                WHERE component_name = $1 AND status = 'history'
                ORDER BY last_updated DESC
                LIMIT $2
                """,
                params=(component, limit),
                fetch_all=True,
            )

            history = []
            for row in results:
                try:
                    metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
                    history.append(metadata)
                except Exception as parse_error:
                    logger.debug(f"Failed to parse metric history row: {parse_error}")
                    continue

            # Reverse to get chronological order
            history.reverse()

            logger.debug(f"Loaded {len(history)} metric history entries from DB for {component}")
            return history

        except Exception as e:
            logger.error(f"Failed to load metric history from DB: {e}")
            return []

    async def _ensure_tool_tracking_table(self) -> None:
        """Ensure tool_tracking_state table exists"""
        if not self.db:
            return

        try:
            # Table is created centrally in postgres_schemas.sql (unified.tool_tracking_state);
            # perform a lightweight access check instead of MySQL-specific DDL.
            await self.db.execute_query(
                "SELECT 1 FROM tool_tracking_state LIMIT 1",
                fetch_one=True,
            )
        except Exception as e:
            logger.debug(f"Tool tracking table may already exist: {e}")

    async def _store_tool_cooldown(self, tool_name: str, iterations_remaining: int) -> None:
        """Store or update tool cooldown in database"""
        if not self.db:
            return

        try:
            await self._ensure_tool_tracking_table()

            await self.db.execute_query(
                """
                INSERT INTO tool_tracking_state (
                    tool_name,
                    tracking_type,
                    state_data,
                    iteration_count
                ) VALUES ($1, 'cooldown', $2, $3)
                ON CONFLICT (tool_name, tracking_type) DO UPDATE SET
                    state_data = EXCLUDED.state_data,
                    iteration_count = EXCLUDED.iteration_count,
                    last_updated = CURRENT_TIMESTAMP
                """,
                params=(
                    tool_name,
                    json.dumps({'iterations_remaining': iterations_remaining}),
                    iterations_remaining,
                ),
                commit=True,
            )

            logger.debug(f"Stored tool cooldown in DB: {tool_name} → {iterations_remaining} iterations")

        except Exception as e:
            logger.error(f"Failed to store tool cooldown: {e}")

    async def _get_tool_cooldown(self, tool_name: str) -> int:
        """Get tool cooldown from database"""
        if not self.db:
            return 0

        try:
            results = await self.db.execute_query(
                """
                SELECT state_data
                FROM tool_tracking_state
                WHERE tool_name = $1 AND tracking_type = 'cooldown'
                """,
                params=(tool_name,),
                fetch_all=True
            )

            if results and len(results) > 0:
                state_data = json.loads(results[0]['state_data']) if isinstance(results[0]['state_data'], str) else results[0]['state_data']
                return state_data.get('iterations_remaining', 0)

            return 0

        except Exception as e:
            logger.error(f"Failed to get tool cooldown: {e}")
            return 0

    async def _delete_tool_cooldown(self, tool_name: str) -> None:
        """Delete tool cooldown from database"""
        if not self.db:
            return

        try:
            await self.db.execute_query(
                """
                DELETE FROM tool_tracking_state
                WHERE tool_name = $1 AND tracking_type = 'cooldown'
                """,
                params=(tool_name,),
                commit=True
            )

            logger.debug(f"Deleted tool cooldown from DB: {tool_name}")

        except Exception as e:
            logger.error(f"Failed to delete tool cooldown: {e}")

    async def _get_all_tool_cooldowns(self) -> Dict[str, int]:
        """Get all tool cooldowns from database"""
        if not self.db:
            return {}

        try:
            results = await self.db.execute_query(
                """
                SELECT tool_name, state_data
                FROM tool_tracking_state
                WHERE tracking_type = 'cooldown' AND iteration_count > 0
                """,
                fetch_all=True
            )

            cooldowns = {}
            for row in results:
                try:
                    state_data = json.loads(row['state_data']) if isinstance(row['state_data'], str) else row['state_data']
                    iterations = state_data.get('iterations_remaining', 0)
                    if iterations > 0:
                        cooldowns[row['tool_name']] = iterations
                except Exception as parse_error:
                    logger.debug(f"Failed to parse cooldown row: {parse_error}")
                    continue

            return cooldowns

        except Exception as e:
            logger.error(f"Failed to get all tool cooldowns: {e}")
            return {}

    async def _store_tool_failure_count(self, tool_name: str, count: int) -> None:
        """Store tool failure count in database"""
        if not self.db:
            return

        try:
            await self._ensure_tool_tracking_table()

            await self.db.execute_query(
                """
                INSERT INTO tool_tracking_state (
                    tool_name, tracking_type, state_data, iteration_count
                ) VALUES ($1, 'failure_count', $2, $3)
                ON CONFLICT (tool_name, tracking_type) DO UPDATE SET
                    state_data = EXCLUDED.state_data,
                    iteration_count = EXCLUDED.iteration_count,
                    last_updated = CURRENT_TIMESTAMP
                """,
                params=(
                    tool_name,
                    json.dumps({'failure_count': count}),
                    count
                ),
                commit=True
            )

            logger.debug(f"Stored tool failure count in DB: {tool_name} → {count}")

        except Exception as e:
            logger.error(f"Failed to store tool failure count: {e}")

    async def _get_tool_failure_count(self, tool_name: str) -> int:
        """Get tool failure count from database"""
        if not self.db:
            return 0

        try:
            results = await self.db.execute_query(
                """
                SELECT state_data
                FROM tool_tracking_state
                WHERE tool_name = $1 AND tracking_type = 'failure_count'
                """,
                params=(tool_name,),
                fetch_all=True
            )

            if results and len(results) > 0:
                state_data = json.loads(results[0]['state_data']) if isinstance(results[0]['state_data'], str) else results[0]['state_data']
                return state_data.get('failure_count', 0)

            return 0

        except Exception as e:
            logger.error(f"Failed to get tool failure count: {e}")
            return 0

    async def _store_tool_sequence(self, tools_used: List[str]) -> None:
        """Store tool sequence in database"""
        if not self.db:
            return

        try:
            await self._ensure_tool_tracking_table()

            # Store with timestamp as tool_name since we want multiple sequences
            tool_name = f"sequence_{int(time.time() * 1000)}"

            await self.db.execute_query(
                """
                INSERT INTO tool_tracking_state (
                    tool_name, tracking_type, state_data
                ) VALUES ($1, 'sequence', $2)
                """,
                params=(
                    tool_name,
                    json.dumps({'tools': tools_used, 'timestamp': datetime.now().isoformat()})
                ),
                commit=True
            )

            # Clean up old sequences (keep last 10)
            await self.db.execute_query(
                """
                DELETE FROM tool_tracking_state
                WHERE tracking_type = 'sequence'
                AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM tool_tracking_state
                        WHERE tracking_type = 'sequence'
                        ORDER BY last_updated DESC
                        LIMIT 10
                    ) AS recent
                )
                """,
                commit=True
            )

            logger.debug(f"Stored tool sequence in DB: {tools_used}")

        except Exception as e:
            logger.error(f"Failed to store tool sequence: {e}")

    async def _get_recent_tool_sequences(self, limit: int = 10) -> List[List[str]]:
        """Get recent tool sequences from database"""
        if not self.db:
            return []

        try:
            results = await self.db.execute_query(
                """
                SELECT state_data
                FROM tool_tracking_state
                WHERE tracking_type = 'sequence'
                ORDER BY last_updated DESC
                LIMIT $1
                """,
                params=(limit,),
                fetch_all=True
            )

            sequences = []
            for row in results:
                try:
                    state_data = json.loads(row['state_data']) if isinstance(row['state_data'], str) else row['state_data']
                    tools = state_data.get('tools', [])
                    if tools:
                        sequences.append(tools)
                except Exception as parse_error:
                    logger.debug(f"Failed to parse sequence row: {parse_error}")
                    continue

            return sequences

        except Exception as e:
            logger.error(f"Failed to get recent tool sequences: {e}")
            return []

    async def get_skill_recommendations(self, max_skills: int = 10) -> List[Tuple[str, float]]:
        """
        Get skill/domain recommendations ranked by learning potential

        Ranks domains based on:
        - Prior success rate (META memory)
        - Bayesian belief confidence
        - Abstraction coverage (schemas formed)
        - Cross-domain transfer potential

        Args:
            max_skills: Maximum number of skills to return

        Returns:
            List of (domain_name, score) tuples sorted by score descending
        """
        try:
            from core.integration.universal_domain_master import get_universal_domain_master, DomainType
            from core.memory import get_memory_agent
            from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
            from core.reasoning.hierarchical_abstraction import get_hierarchical_abstraction

            domain_master = get_universal_domain_master()
            memory_agent = await get_memory_agent()
            bayesian = get_bayesian_uncertainty()
            abstraction = get_hierarchical_abstraction()

            # Score each domain
            domain_scores: Dict[str, float] = {}

            for domain_type in DomainType:
                domain_name = domain_type.value
                score = 0.0

                # Factor 1: META memory success rate (40% weight)
                perf_stats = await self.get_domain_performance_stats(domain_name)
                success_rate = perf_stats.get("success_rate", 0.5)
                total_attempts = perf_stats.get("total_attempts", 0)

                # Reward domains with moderate success (learning zone: 50-80%)
                if 0.5 <= success_rate <= 0.8:
                    meta_score = 0.8
                elif 0.3 <= success_rate < 0.5:
                    meta_score = 0.6  # Challenging but improvable
                elif success_rate > 0.8:
                    meta_score = 0.3  # Too easy, low learning potential
                else:
                    meta_score = 0.4  # Very challenging

                # Boost if we have data
                if total_attempts > 0:
                    meta_score *= 1.2

                score += meta_score * 0.4

                # Factor 2: Bayesian belief confidence (25% weight)
                if bayesian and hasattr(bayesian, 'beliefs'):
                    domain_beliefs = [
                        belief for belief in bayesian.beliefs.values()
                        if belief.domain == domain_name
                    ]

                    if domain_beliefs:
                        avg_confidence = sum(b.posterior_probability for b in domain_beliefs) / len(domain_beliefs)
                        # Reward moderate confidence (learning zone)
                        if 0.4 <= avg_confidence <= 0.7:
                            belief_score = 0.8
                        elif avg_confidence < 0.4:
                            belief_score = 0.5  # Low confidence, needs work
                        else:
                            belief_score = 0.3  # High confidence, less to learn

                        score += belief_score * 0.25
                    else:
                        # No beliefs = unexplored domain
                        score += 0.6 * 0.25

                # Factor 3: Abstraction coverage (20% weight)
                if abstraction and hasattr(abstraction, 'active_schemas'):
                    domain_schemas = [
                        schema for schema in abstraction.active_schemas.values()
                        if schema.metadata.get('domain') == domain_name
                    ]

                    schema_count = len(domain_schemas)

                    # Reward domains with some but not too many schemas
                    if 2 <= schema_count <= 8:
                        abstraction_score = 0.8  # Good coverage, room to grow
                    elif schema_count < 2:
                        abstraction_score = 0.6  # Underdeveloped
                    else:
                        abstraction_score = 0.4  # Well-covered

                    score += abstraction_score * 0.20
                else:
                    score += 0.5 * 0.20

                # Factor 4: Cross-domain transfer potential (15% weight)
                # Query domain master for mappings
                if domain_master and hasattr(domain_master, 'mapping_cache'):
                    # Count mappings involving this domain
                    mapping_count = 0
                    for (source, target), mappings in domain_master.mapping_cache.items():
                        if source == domain_type or target == domain_type:
                            mapping_count += len(mappings)

                    # Reward domains with transfer potential
                    if mapping_count > 5:
                        transfer_score = 0.8  # High transfer potential
                    elif mapping_count > 0:
                        transfer_score = 0.6
                    else:
                        transfer_score = 0.4  # No known transfers

                    score += transfer_score * 0.15
                else:
                    score += 0.5 * 0.15

                domain_scores[domain_name] = score

            # Sort by score descending
            sorted_skills = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)

            # Return top N
            top_skills = sorted_skills[:max_skills]

            if top_skills:
                logger.info(f"🎯 Top skill recommendations: {', '.join(f'{s[0]}({s[1]:.2f})' for s in top_skills[:3])}")

            return top_skills

        except Exception as e:
            logger.error(f"Failed to get skill recommendations: {e}", exc_info=True)
            # Return default recommendations
            return [
                ("technical", 0.7),
                ("scientific", 0.65),
                ("practical", 0.6)
            ]

    # =========================================================================
    # HYPOTHESIS TESTING INTEGRATION
    # =========================================================================

    async def convert_goal_to_hypothesis(
        self,
        goal: Dict[str, Any]
    ) -> Optional[str]:
        """
        Convert an intrinsic exploration goal into a testable hypothesis.

        Args:
            goal: Goal dictionary with description, component, etc.

        Returns:
            hypothesis_id if hypothesis was created, None otherwise
        """
        try:
            from core.reasoning.hypothesis_testing import get_hypothesis_system

            hypothesis_system = get_hypothesis_system()

            # Initialize if not already done
            if not hasattr(hypothesis_system, 'db') or not hypothesis_system.db:
                await hypothesis_system.initialize()

            # Extract goal details
            description = goal.get('description', '')
            component = goal.get('component', 'system')
            objective_type = goal.get('objective_type', 'explore')

            # Convert goal into falsifiable hypothesis claim
            claim = self._goal_to_hypothesis_claim(description, objective_type)

            # Generate predictions based on goal type
            predictions = self._generate_hypothesis_predictions(goal, objective_type)

            # Create hypothesis
            hypothesis = await hypothesis_system.generate_hypothesis(
                claim=claim,
                domain=component,
                predictions=predictions,
                alternatives=self._generate_alternative_hypotheses(goal)
            )

            logger.info(f"✓ Created hypothesis {hypothesis.hypothesis_id} from goal: {description[:60]}...")
            logger.debug(f"  Claim: {claim}")
            logger.debug(f"  Predictions: {len(predictions)}")

            # Store mapping between goal and hypothesis
            if hasattr(goal, 'get') and 'id' in goal:
                await self._store_goal_hypothesis_mapping(goal['id'], hypothesis.hypothesis_id)

            return hypothesis.hypothesis_id

        except Exception as e:
            logger.error(f"Failed to convert goal to hypothesis: {e}")
            return None

    def _goal_to_hypothesis_claim(self, description: str, objective_type: str) -> str:
        """Convert goal description into falsifiable hypothesis claim"""
        description_lower = description.lower()

        # Map objective types to hypothesis formats
        if objective_type == 'explore':
            if 'uncertainty' in description_lower:
                return f"Exploring {description} will reduce epistemic uncertainty by >10%"
            else:
                return f"{description} will reveal novel patterns or insights"

        elif objective_type == 'optimize':
            return f"{description} will improve performance metrics by >5%"

        elif objective_type == 'fix':
            return f"{description} will reduce error rate by >20%"

        elif objective_type == 'learn':
            return f"{description} will increase domain competence score by >0.1"

        else:
            # Generic explorative claim
            return f"Investigating {description} will produce measurable system improvements"

    def _generate_hypothesis_predictions(
        self,
        goal: Dict[str, Any],
        objective_type: str
    ) -> List[str]:
        """Generate testable predictions from goal"""
        predictions = []
        component = goal.get('component', 'system')

        if objective_type == 'explore':
            predictions.append(f"Component {component} uncertainty will decrease after exploration")
            predictions.append(f"Novelty detection will identify new patterns in {component}")
            predictions.append(f"Confidence scores for {component} will increase")

        elif objective_type == 'optimize':
            predictions.append(f"{component} performance metrics will improve")
            predictions.append(f"Resource utilization in {component} will be more efficient")
            predictions.append(f"Latency or error rates in {component} will decrease")

        elif objective_type == 'fix':
            predictions.append(f"Error count in {component} will decrease by >20%")
            predictions.append(f"Health score for {component} will improve")
            predictions.append(f"Failure rate in {component} will be reduced")

        elif objective_type == 'learn':
            predictions.append(f"Domain knowledge score for {component} will increase")
            predictions.append(f"Reasoning depth for {component} tasks will improve")
            predictions.append(f"Confidence in {component} decisions will be higher")

        return predictions

    def _generate_alternative_hypotheses(self, goal: Dict[str, Any]) -> List[str]:
        """Generate alternative explanations to test against"""
        description = goal.get('description', '')
        component = goal.get('component', 'system')

        return [
            f"{description} will have no measurable effect (null hypothesis)",
            f"{description} will reveal existing knowledge, not new insights",
            f"Random exploration would yield equivalent results",
            f"The observed effects are due to other system changes, not {component}",
        ]

    async def _store_goal_hypothesis_mapping(
        self,
        goal_id: str,
        hypothesis_id: str
    ) -> None:
        """Store mapping between goal and hypothesis for tracking"""
        if not self.db:
            return

        try:
            await self.db.execute_query(
                """
                INSERT INTO unified.novelty_detections
                (novelty_id, goal_description, theme, component, metadata)
                VALUES ($1, $2, 'hypothesis_mapping', 'intrinsic_motivation', $3)
                ON CONFLICT (novelty_id) DO UPDATE SET
                    metadata = EXCLUDED.metadata
                """,
                (
                    f"goal_hyp_map_{goal_id}",
                    f"Goal-Hypothesis mapping: {goal_id} -> {hypothesis_id}",
                    json.dumps({
                        'goal_id': goal_id,
                        'hypothesis_id': hypothesis_id,
                        'created_at': datetime.now().isoformat()
                    })
                ),
                commit=True
            )

            logger.debug(f"Stored goal-hypothesis mapping: {goal_id} -> {hypothesis_id}")

        except Exception as e:
            logger.error(f"Failed to store goal-hypothesis mapping: {e}")



# ============================================================================
# Singleton accessor
# ============================================================================

_intrinsic_motivation_system: Optional[IntrinsicMotivationSystem] = None


def get_intrinsic_motivation_system(
    config: Optional[Dict[str, Any]] = None,
) -> IntrinsicMotivationSystem:
    """Get global IntrinsicMotivationSystem instance (singleton).

    The first caller may provide configuration; later calls ignore
    config overrides and return the existing instance.
    """
    global _intrinsic_motivation_system

    if _intrinsic_motivation_system is None:
        _intrinsic_motivation_system = IntrinsicMotivationSystem(config=config)
    else:
        if config:
            logger.debug(
                "get_intrinsic_motivation_system called with config after "
                "initialization; ignoring override and returning existing "
                "singleton"
            )

    return _intrinsic_motivation_system
