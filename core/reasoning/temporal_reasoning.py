#!/usr/bin/env python3
"""
Temporal Reasoning & Prediction System
=======================================
Enables reasoning about time, causality, and future states.

Core capabilities:
- Temporal logic (past, present, future, always, eventually, until)
- Future-state projection
- Causal reasoning across time
- Multi-step planning with dependencies
- Timeline analysis
- Counterfactual temporal reasoning

Based on:
- Linear Temporal Logic (LTL)
- Branching Time Logic (CTL)
- Temporal Causal Networks
- STRIPS planning with temporal constraints
"""

import asyncio
import hashlib
import logging
import json
import uuid
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from collections import defaultdict, deque

from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


class TemporalOperator(Enum):
    """Temporal logic operators"""
    ALWAYS = "always"  # □ - true at all times
    EVENTUALLY = "eventually"  # ◇ - true at some future time
    NEXT = "next"  # ○ - true at next time
    UNTIL = "until"  # U - p until q
    SINCE = "since"  # S - p since q
    BEFORE = "before"  # < temporal ordering
    AFTER = "after"  # > temporal ordering
    DURING = "during"  # overlapping intervals


class TimePoint(Enum):
    """Time reference points"""
    PAST = "past"
    PRESENT = "present"
    FUTURE = "future"
    NEAR_FUTURE = "near_future"  # Soon
    FAR_FUTURE = "far_future"  # Later


@dataclass
class TemporalProposition:
    """A proposition with temporal properties"""
    prop_id: str
    statement: str
    
    # Temporal properties
    time_point: TimePoint
    timestamp: Optional[datetime] = None
    duration: Optional[timedelta] = None
    
    # Temporal logic
    temporal_operator: Optional[TemporalOperator] = None
    operands: List[str] = field(default_factory=list)  # IDs of related propositions
    
    # Truth value
    is_true: bool = True
    confidence: float = 1.0
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CausalLink:
    """A causal relationship between events"""
    link_id: str
    cause_id: str
    effect_id: str
    
    # Causal properties
    causal_strength: float = 0.5  # 0.0 to 1.0
    time_delay: Optional[timedelta] = None  # How long until effect?
    necessary: bool = False  # Is cause necessary for effect?
    sufficient: bool = False  # Is cause sufficient for effect?
    
    # Evidence
    evidence: List[str] = field(default_factory=list)
    observations: int = 0
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FutureState:
    """A projected future state"""
    state_id: str
    description: str
    
    # Temporal properties
    projected_time: datetime
    time_horizon: timedelta
    
    # State properties
    conditions: List[str] = field(default_factory=list)  # What must be true
    probability: float = 0.5
    
    # Path to state
    required_actions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # Other state IDs
    
    # Evaluation
    desirability: float = 0.5  # How good is this state?
    achievable: bool = True
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)


class PlanningStatus(Enum):
    """What planning established. Not every non-plan is the same non-plan.

    UNREACHABLE is a proof: the space was exhausted and no action sequence
    achieves the goal. INDETERMINATE is an admission: the search hit its bound
    and does not know. Collapsing them lets a caller treat "impossible" and
    "I gave up" as one thing, which is how a system ends up manufacturing a
    plan whenever real planning fails.
    """

    PLAN_FOUND = "plan_found"
    UNREACHABLE = "unreachable"
    INDETERMINATE = "indeterminate"
    INVALID_GOAL = "invalid_goal"
    UNSUPPORTED_GOAL = "unsupported_goal"


class PlanOutcome(Enum):
    """What planning established, status and guarantee read together.

    The vocabulary outgrew one notion of PLAN_FOUND. A plan whose every value
    was computed while planning and a plan that will not know its own result
    until it runs are both PLAN_FOUND, and treating them alike is how a system
    reports an answer it never had.

    PROVED_PLAN                   every value the goal depends on was computed
                                  while planning; reaching it follows from the
                                  operators alone.
    CONDITIONAL_PLAN              the chain of steps is proved and the exact
                                  result is not: a value arrives only at
                                  runtime.
    NO_PROVED_PLAN_WITHIN_BOUND   a conditional plan, PLUS what the search
                                  established on the way to it -- no proved plan
                                  of that length or shorter exists. Where an
                                  action invents a value the space has no end to
                                  exhaust, so this is the strongest negative
                                  available and it is not UNREACHABLE.
    UNREACHABLE                   the space was exhausted. Only ever from a
                                  complete operator set.
    """

    PROVED_PLAN = "proved_plan"
    CONDITIONAL_PLAN = "conditional_plan"
    NO_PROVED_PLAN_WITHIN_BOUND = "no_proved_plan_within_bound"
    UNREACHABLE = "unreachable"
    INDETERMINATE = "indeterminate"
    INVALID_GOAL = "invalid_goal"
    UNSUPPORTED_GOAL = "unsupported_goal"


class PlanGuarantee(Enum):
    """Whether the plan's result is proved or merely structured.

    Carried BESIDE the status rather than as two more members of it, so that
    every existing `is PlanningStatus.PLAN_FOUND` keeps meaning "there is a
    plan" and cannot silently start meaning "there is a proved plan".

    GUARANTEED   every value the plan depends on was computed while planning,
                 so reaching the goal follows from the operators alone.
    CONDITIONAL  the plan passes through a value only running it can produce --
                 what a file contains, what a request returns. The SHAPE is
                 proved and the exact result is not, and a caller that treats
                 the two alike will report an answer it never had.
    """

    GUARANTEED = "guaranteed"
    CONDITIONAL = "conditional"


@dataclass
class PlanningResult:
    status: PlanningStatus
    steps: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    goal_conditions: List[str] = field(default_factory=list)
    nodes_expanded: int = 0
    reason: str = ""
    guarantee: PlanGuarantee = PlanGuarantee.GUARANTEED
    #: Values the plan carries that are not known until it runs.
    deferred: List[str] = field(default_factory=list)
    #: What each step read, from where, and what it produced. Recorded by
    #: replaying the plan that was found -- never reconstructed from prose.
    trace: List[Dict[str, Any]] = field(default_factory=list)
    initial: List[str] = field(default_factory=list)
    #: The length up to which no PROVED plan exists. None where the search did
    #: not establish that -- which is different from establishing there is none.
    proved_ruled_out_to: Optional[int] = None

    @property
    def found(self) -> bool:
        return self.status is PlanningStatus.PLAN_FOUND

    @property
    def proved(self) -> bool:
        return self.found and self.guarantee is PlanGuarantee.GUARANTEED

    @property
    def outcome(self) -> "PlanOutcome":
        """Status and guarantee as the one thing a caller has to read."""
        if self.status is not PlanningStatus.PLAN_FOUND:
            return PlanOutcome(self.status.value)
        if self.guarantee is PlanGuarantee.GUARANTEED:
            return PlanOutcome.PROVED_PLAN
        if self.proved_ruled_out_to is not None:
            return PlanOutcome.NO_PROVED_PLAN_WITHIN_BOUND
        return PlanOutcome.CONDITIONAL_PLAN


@dataclass
class Plan:
    """A multi-step plan with temporal constraints"""
    plan_id: str
    goal: str
    
    # Steps
    steps: List[Dict[str, Any]] = field(default_factory=list)
    
    # Temporal constraints
    step_dependencies: List[Tuple[int, int]] = field(default_factory=list)  # (step_i, step_j)
    time_constraints: Dict[int, timedelta] = field(default_factory=dict)  # step -> max duration
    
    # Execution
    current_step: int = 0
    completed_steps: Set[int] = field(default_factory=set)
    failed_steps: Set[int] = field(default_factory=set)
    
    # Evaluation
    estimated_duration: Optional[timedelta] = None
    success_probability: float = 0.5
    
    # Status
    status: str = "planned"  # planned, executing, completed, failed
    created_at: datetime = field(default_factory=datetime.now)


class TemporalReasoningSystem:
    """
    Temporal Reasoning & Prediction for the Singleton
    
    Enables sophisticated reasoning about:
    - Time and causality
    - Future state projection
    - Multi-step planning
    - Temporal dependencies
    - Counterfactual temporal reasoning
    """
    
    def __init__(self, db_path: Optional[str] = None):
        # Temporal knowledge is persisted to the unified PostgreSQL database
        # like the rest of the system -- no separate SQLite file. The parameter
        # is kept for signature compatibility and ignored.
        self.unified_db = TorinUnifiedDatabase()
        
        # Temporal knowledge
        self.propositions: Dict[str, TemporalProposition] = {}
        self.causal_links: Dict[str, CausalLink] = {}
        self.future_states: Dict[str, FutureState] = {}
        self.plans: Dict[str, Plan] = {}
        
        # Timeline
        self.timeline: List[Tuple[datetime, str]] = []  # (time, event_id)
        
        # Statistics
        self.stats = {
            'states_projected': 0,
            'causal_links_discovered': 0,
            'plans_created': 0,
            'plans_executed': 0,
            'predictions_made': 0,
            'predictions_correct': 0
        }
        
        # Schema is created lazily by the async persistence path (persist/load),
        # so constructing the engine never touches the database or the filesystem.
    
    def _db(self):
        """The unified PostgreSQL database -- the one store the whole system uses."""
        from core.database import get_database_manager
        return get_database_manager()

    async def _ensure_schema(self):
        """Create the temporal tables in the unified DB if absent. Idempotent."""
        db = self._db()
        # The reasoning path can reach persistence before anything else has
        # initialised the pool (a below-floor query skips memory injection, which
        # is what normally warms it). initialize() is idempotent, so this is a
        # no-op once connected and the one line that made every persist silently
        # fail with "Database not initialized".
        if not getattr(db, "initialized", False):
            await db.initialize()
        await db.execute_query(
            "CREATE TABLE IF NOT EXISTS unified.reasoning_temporal_propositions ("
            "prop_id TEXT PRIMARY KEY, statement TEXT NOT NULL, time_point TEXT, "
            "ts TIMESTAMPTZ, is_true BOOLEAN, confidence REAL, "
            "created_at TIMESTAMPTZ DEFAULT NOW())", commit=True)
        await db.execute_query(
            "CREATE TABLE IF NOT EXISTS unified.reasoning_temporal_causal_links ("
            "link_id TEXT PRIMARY KEY, cause_id TEXT, effect_id TEXT, "
            "causal_strength REAL, necessary BOOLEAN, sufficient BOOLEAN, "
            "observations INTEGER, created_at TIMESTAMPTZ DEFAULT NOW())", commit=True)

    async def persist(self):
        """Write temporal knowledge to the unified PostgreSQL DB.

        OFF THE CRITICAL PATH AND NON-FATAL. Reasoning is in-memory; a
        persistence failure must never break a derivation. This replaces the
        old per-add synchronous SQLite write that put a filesystem write inside
        the reasoning loop and killed the derivation when it failed.
        """
        try:
            await self._ensure_schema()
            db = self._db()
            for prop in self.propositions.values():
                await db.execute_query(
                    "INSERT INTO unified.reasoning_temporal_propositions "
                    "(prop_id, statement, time_point, ts, is_true, confidence) "
                    "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (prop_id) DO UPDATE SET "
                    "statement=EXCLUDED.statement, is_true=EXCLUDED.is_true, "
                    "confidence=EXCLUDED.confidence",
                    (prop.prop_id, prop.statement,
                     prop.time_point.value if prop.time_point else None,
                     prop.timestamp, bool(prop.is_true), float(prop.confidence)),
                    commit=True)
            for link in self.causal_links.values():
                await db.execute_query(
                    "INSERT INTO unified.reasoning_temporal_causal_links "
                    "(link_id, cause_id, effect_id, causal_strength, necessary, "
                    "sufficient, observations) VALUES ($1,$2,$3,$4,$5,$6,$7) "
                    "ON CONFLICT (link_id) DO UPDATE SET "
                    "causal_strength=EXCLUDED.causal_strength, "
                    "observations=EXCLUDED.observations",
                    (link.link_id, link.cause_id, link.effect_id,
                     float(link.causal_strength), bool(link.necessary),
                     bool(link.sufficient), int(link.observations)), commit=True)
        except Exception as error:
            logger.debug("temporal persist skipped (non-fatal): %s", error)

    async def load(self, limit: int = 1000):
        """Bring prior temporal knowledge into memory so reasoning consults what
        earlier sessions established -- the reader the SQLite version never had.
        Non-fatal: absence of history is not an error.
        """
        try:
            await self._ensure_schema()
            db = self._db()
            rows = await db.execute_query(
                "SELECT prop_id, statement, time_point, ts, is_true, confidence "
                "FROM unified.reasoning_temporal_propositions ORDER BY created_at DESC LIMIT $1",
                (int(limit),), fetch_all=True) or []
            for r in rows:
                if r["prop_id"] not in self.propositions:
                    self.propositions[r["prop_id"]] = TemporalProposition(
                        prop_id=r["prop_id"], statement=r["statement"],
                        time_point=(TimePoint(r["time_point"]) if r["time_point"]
                                    else TimePoint.PRESENT),
                        timestamp=r["ts"], is_true=bool(r["is_true"]),
                        confidence=float(r["confidence"] or 1.0))
            rows = await db.execute_query(
                "SELECT link_id, cause_id, effect_id, causal_strength, necessary, "
                "sufficient, observations FROM unified.reasoning_temporal_causal_links "
                "ORDER BY created_at DESC LIMIT $1", (int(limit),), fetch_all=True) or []
            for r in rows:
                if r["link_id"] not in self.causal_links:
                    self.causal_links[r["link_id"]] = CausalLink(
                        link_id=r["link_id"], cause_id=r["cause_id"],
                        effect_id=r["effect_id"],
                        causal_strength=float(r["causal_strength"] or 0.5),
                        necessary=bool(r["necessary"]), sufficient=bool(r["sufficient"]),
                        observations=int(r["observations"] or 0))
        except Exception as error:
            logger.debug("temporal load skipped (non-fatal): %s", error)
    
    # ==================================================================================
    # TEMPORAL LOGIC
    # ==================================================================================
    
    def create_proposition(
        self,
        statement: str,
        time_point: TimePoint,
        is_true: bool = True,
        confidence: float = 1.0,
        timestamp: Optional[datetime] = None,
        temporal_operator: Optional[TemporalOperator] = None
    ) -> TemporalProposition:
        """Create a temporal proposition"""
        prop_id = f"prop_{uuid.uuid4().hex[:12]}"
        
        prop = TemporalProposition(
            prop_id=prop_id,
            statement=statement,
            time_point=time_point,
            is_true=is_true,
            confidence=confidence,
            timestamp=timestamp or datetime.now(),
            temporal_operator=temporal_operator
        )
        
        self.propositions[prop_id] = prop
        
        # Add to timeline if it's a past/present event
        if time_point in [TimePoint.PAST, TimePoint.PRESENT] and prop.timestamp is not None:
            self.timeline.append((prop.timestamp, prop_id))
            self.timeline.sort()  # Keep timeline sorted
        
        return prop
    
    def evaluate_temporal_formula(
        self,
        operator: TemporalOperator,
        proposition: TemporalProposition,
        timeline_context: Optional[List[TemporalProposition]] = None
    ) -> bool:
        """Evaluate a temporal logic formula"""
        
        if operator == TemporalOperator.ALWAYS:
            # Check if proposition is true at all times in timeline
            if timeline_context:
                return all(p.is_true for p in timeline_context if p.statement == proposition.statement)
            return proposition.is_true
        
        elif operator == TemporalOperator.EVENTUALLY:
            # Check if proposition will be true at some future time
            if timeline_context:
                return any(p.is_true and p.time_point == TimePoint.FUTURE 
                          for p in timeline_context if p.statement == proposition.statement)
            return proposition.time_point == TimePoint.FUTURE and proposition.is_true
        
        elif operator == TemporalOperator.NEXT:
            # True at immediate next time point
            return proposition.time_point in [TimePoint.NEAR_FUTURE, TimePoint.FUTURE]
        
        else:
            return proposition.is_true
    
    # ==================================================================================
    # CAUSAL REASONING
    # ==================================================================================
    
    def establish_causal_link(
        self,
        cause: TemporalProposition,
        effect: TemporalProposition,
        strength: float = 0.5,
        time_delay: Optional[timedelta] = None,
        necessary: bool = False,
        sufficient: bool = False,
        evidence: Optional[List[str]] = None
    ) -> CausalLink:
        """Establish a causal relationship between events"""
        link_id = f"causal_{uuid.uuid4().hex[:12]}"
        
        link = CausalLink(
            link_id=link_id,
            cause_id=cause.prop_id,
            effect_id=effect.prop_id,
            causal_strength=strength,
            time_delay=time_delay,
            necessary=necessary,
            sufficient=sufficient,
            evidence=evidence or [],
            observations=1
        )
        
        self.causal_links[link_id] = link
        
        self.stats['causal_links_discovered'] += 1
        
        logger.info(f"Established causal link: {cause.statement[:50]} → {effect.statement[:50]}")
        
        return link
    
    def trace_causal_chain(
        self,
        effect_id: str,
        max_depth: int = 10
    ) -> List[List[str]]:
        """Trace causal chain backwards to find root causes"""
        chains = []
        visited = set()
        
        def dfs(current_id: str, chain: List[str], depth: int):
            if depth >= max_depth or current_id in visited:
                if chain:
                    chains.append(chain.copy())
                return
            
            visited.add(current_id)
            chain.append(current_id)
            
            # Find causes of current effect
            causes_found = False
            for link in self.causal_links.values():
                if link.effect_id == current_id:
                    causes_found = True
                    dfs(link.cause_id, chain, depth + 1)
            
            if not causes_found:
                chains.append(chain.copy())
            
            chain.pop()
            visited.remove(current_id)
        
        dfs(effect_id, [], 0)
        return chains
    
    def predict_effect(
        self,
        cause_id: str,
        time_horizon: Optional[timedelta] = None
    ) -> List[TemporalProposition]:
        """Predict effects of a cause"""
        predictions = []
        
        for link in self.causal_links.values():
            if link.cause_id == cause_id:
                effect_prop = self.propositions.get(link.effect_id)
                if effect_prop:
                    # Create predicted future state
                    predicted_time = datetime.now()
                    if link.time_delay:
                        predicted_time += link.time_delay
                    elif time_horizon:
                        predicted_time += time_horizon
                    
                    prediction = TemporalProposition(
                        prop_id=f"pred_{uuid.uuid4().hex[:8]}",
                        statement=effect_prop.statement,
                        time_point=TimePoint.FUTURE,
                        timestamp=predicted_time,
                        is_true=True,
                        confidence=link.causal_strength
                    )
                    predictions.append(prediction)
                    
                    self.stats['predictions_made'] += 1
        
        return predictions
    
    # ==================================================================================
    # FUTURE STATE PROJECTION
    # ==================================================================================
    
    def project_future_state(
        self,
        description: str,
        time_horizon: timedelta,
        conditions: Optional[List[str]] = None,
        required_actions: Optional[List[str]] = None,
        probability: float = 0.5
    ) -> FutureState:
        """Project a possible future state"""
        state_id = f"state_{uuid.uuid4().hex[:12]}"
        
        projected_time = datetime.now() + time_horizon
        
        state = FutureState(
            state_id=state_id,
            description=description,
            projected_time=projected_time,
            time_horizon=time_horizon,
            conditions=conditions or [],
            required_actions=required_actions or [],
            probability=probability
        )
        
        self.future_states[state_id] = state
        
        self.stats['states_projected'] += 1
        
        logger.info(f"Projected future state: {description[:50]} @ {projected_time}")
        
        return state
    
    def evaluate_state_reachability(
        self,
        state: FutureState,
        current_conditions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Evaluate if a future state is reachable"""
        
        current = set(current_conditions or [])
        required = set(state.conditions)
        
        # What conditions are met?
        met_conditions = current & required
        missing_conditions = required - current
        
        # Can we achieve missing conditions?
        achievable_conditions = []
        unachievable_conditions = []
        
        for condition in missing_conditions:
            # Check if any action can achieve this condition
            can_achieve = any(
                condition in action for action in state.required_actions
            )
            if can_achieve:
                achievable_conditions.append(condition)
            else:
                unachievable_conditions.append(condition)
        
        # Overall reachability
        reachable = len(unachievable_conditions) == 0
        
        return {
            'reachable': reachable,
            'met_conditions': list(met_conditions),
            'missing_conditions': list(missing_conditions),
            'achievable_conditions': achievable_conditions,
            'unachievable_conditions': unachievable_conditions,
            'actions_needed': state.required_actions,
            'estimated_difficulty': len(missing_conditions) / max(len(required), 1)
        }
    
    def compare_future_states(
        self,
        state1: FutureState,
        state2: FutureState
    ) -> Dict[str, Any]:
        """Compare two future states"""
        
        comparison = {
            'more_probable': state1.state_id if state1.probability > state2.probability else state2.state_id,
            'more_desirable': state1.state_id if state1.desirability > state2.desirability else state2.state_id,
            'sooner': state1.state_id if state1.projected_time < state2.projected_time else state2.state_id,
            'probability_difference': abs(state1.probability - state2.probability),
            'desirability_difference': abs(state1.desirability - state2.desirability),
            'time_difference': abs((state1.projected_time - state2.projected_time).total_seconds())
        }
        
        # Overall preference (weighted)
        score1 = state1.probability * 0.3 + state1.desirability * 0.7
        score2 = state2.probability * 0.3 + state2.desirability * 0.7
        
        comparison['preferred'] = state1.state_id if score1 > score2 else state2.state_id
        comparison['preference_score_difference'] = abs(score1 - score2)
        
        return comparison
    
    # ==================================================================================
    # MULTI-STEP PLANNING
    # ==================================================================================
    
    def create_plan(
        self,
        goal: str,
        steps: List[Dict[str, Any]],
        dependencies: Optional[List[Tuple[int, int]]] = None
    ) -> Plan:
        """Create a multi-step plan with temporal constraints"""
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        
        plan = Plan(
            plan_id=plan_id,
            goal=goal,
            steps=steps,
            step_dependencies=dependencies or []
        )
        
        # Estimate duration
        total_duration = timedelta()
        for step in steps:
            if 'duration' in step:
                total_duration += step['duration']
        plan.estimated_duration = total_duration
        
        self.plans[plan_id] = plan
        
        self.stats['plans_created'] += 1
        
        logger.info(f"Created plan: {goal} with {len(steps)} steps")
        
        return plan
    
    def get_executable_steps(self, plan: Plan) -> List[int]:
        """Get steps that can be executed now (dependencies met)"""
        executable = []
        
        for i, step in enumerate(plan.steps):
            # Skip if already completed or failed
            if i in plan.completed_steps or i in plan.failed_steps:
                continue
            
            # Check if all dependencies are met
            dependencies_met = True
            for dep_from, dep_to in plan.step_dependencies:
                if dep_to == i and dep_from not in plan.completed_steps:
                    dependencies_met = False
                    break
            
            if dependencies_met:
                executable.append(i)
        
        return executable
    
    def execute_plan_step(
        self,
        plan_id: str,
        step_index: int,
        success: bool = True
    ) -> Dict[str, Any]:
        """Execute a single step of a plan"""
        if plan_id not in self.plans:
            return {'error': 'Plan not found'}
        
        plan = self.plans[plan_id]
        
        if step_index >= len(plan.steps):
            return {'error': 'Invalid step index'}
        
        # Check if step is executable
        executable_steps = self.get_executable_steps(plan)
        if step_index not in executable_steps:
            return {'error': 'Step dependencies not met'}
        
        # Execute step
        if success:
            plan.completed_steps.add(step_index)
            logger.info(f"Completed step {step_index} of plan {plan_id}")
        else:
            plan.failed_steps.add(step_index)
            logger.info(f"Failed step {step_index} of plan {plan_id}")
        
        plan.current_step = step_index + 1
        
        # Check if plan is complete
        if len(plan.completed_steps) == len(plan.steps):
            plan.status = "completed"
            self.stats['plans_executed'] += 1
            logger.info(f"Plan {plan_id} completed successfully")
        elif plan.failed_steps:
            plan.status = "failed"
            logger.info(f"Plan {plan_id} failed at step {step_index}")
        else:
            plan.status = "executing"
        
        
        return {
            'success': success,
            'step_index': step_index,
            'plan_status': plan.status,
            'completed_steps': len(plan.completed_steps),
            'total_steps': len(plan.steps),
            'next_executable': self.get_executable_steps(plan)
        }
    
    def plan_for_state_goal(
        self,
        goal: Any,
        current_state: Dict[str, Any],
        available_actions: List[Dict[str, Any]],
        max_depth: int = 20,
        max_nodes: int = 20000,
    ) -> "PlanningResult":
        """Search for an action sequence achieving a goal stated over world state.

        Breadth-first over the state space, so the first plan found is the
        shortest and an exhausted search is a genuine proof that none exists
        within the bound. The previous implementation was greedy hill-climbing
        with three defects that made it unusable and untested:

        1. `current_state.copy()` and `state.copy()` are SHALLOW, so
           `state['conditions']` was one shared list. "Simulating" an action
           permanently applied it and mutated the caller's own state; the search
           was exploring a world it was destroying as it looked.
        2. It emitted inapplicable plans. Asked for a two-step goal it returned
           only the second step, whose precondition was false at the start.
        3. `_extract_conditions` returned `[goal]` -- the whole goal as one
           atom -- so `_measure_progress` was binary and, with selection
           requiring strictly-increasing progress from zero, only an action that
           achieved the goal outright could ever be chosen. Multi-step planning
           was impossible by construction.

        Returns a typed outcome rather than a Plan, because "I proved no plan
        exists" and "I do not know how to plan this" are different cognitive
        states and a caller that cannot tell them apart will paper over both.
        """
        goal_conditions = self._extract_conditions(goal)
        if not goal_conditions:
            return PlanningResult(
                status=PlanningStatus.INVALID_GOAL,
                reason="goal states no conditions to achieve",
            )

        start = frozenset(current_state.get('conditions', []))
        if self._goal_satisfied(goal_conditions, {'conditions': list(start)}):
            return PlanningResult(
                status=PlanningStatus.PLAN_FOUND, steps=[],
                reason="goal already satisfied in the initial state",
                goal_conditions=list(goal_conditions), nodes_expanded=0,
            )

        for action in available_actions:
            if not action.get('name'):
                return PlanningResult(
                    status=PlanningStatus.INVALID_GOAL,
                    reason=f"an available action has no name: {action!r}",
                )

        frontier = deque([(start, [], frozenset())])
        seen = {start}
        expanded = 0
        # The shortest plan that reaches the goal only through a value it
        # cannot yet know. Held rather than returned, so a proved plan found
        # later always wins over a conditional one found sooner.
        conditional: Optional[Tuple[List[Dict[str, Any]], FrozenSet[str]]] = None
        # Parsing the state costs something and is needed only where an
        # operator has to be bound against it.
        lifted = any(a.get('open') or a.get('outputs') for a in available_actions)
        #: Set only when the search finished every shorter level first.
        ruled_out: Optional[int] = None

        while frontier:
            state_facts, path, pending = frontier.popleft()
            if len(path) >= max_depth:
                continue
            # ENOUGH IS KNOWN ONCE THE LEVEL IS FINISHED. Where an action
            # invents a value, every occurrence of it invents a different one,
            # so no state ever repeats and the space has no end to exhaust.
            # Having a plan of length d and having expanded every node above
            # that level, what is established is exact: no PROVED plan of this
            # length or shorter exists. Searching on for a longer proved plan
            # would not terminate.
            if conditional is not None and len(path) >= len(conditional[0]):
                ruled_out = len(conditional[0])
                break
            parsed = self._parse(state_facts) if lifted else None

            for action in available_actions:
              for instance in self._instances(
                      action, state_facts, parsed, len(path) + 1, pending):
                successor = frozenset(
                    self._apply_action(instance, {'conditions': list(state_facts)})['conditions']
                )
                if successor in seen:
                    continue

                expanded += 1
                extended = path + [instance]
                carried = pending | frozenset(instance.get('deferred') or ())

                if self._goal_satisfied(goal_conditions, {'conditions': list(successor)}):
                    return PlanningResult(
                        status=PlanningStatus.PLAN_FOUND,
                        steps=[self._as_step(a) for a in extended],
                        actions=extended,
                        goal_conditions=list(goal_conditions),
                        nodes_expanded=expanded,
                        reason=f"plan of {len(extended)} step(s) found",
                        guarantee=PlanGuarantee.GUARANTEED,
                        deferred=sorted(carried),
                        trace=self._trace(start, extended),
                        initial=sorted(start),
                    )

                if conditional is None and carried and self._goal_satisfied_pending(
                    goal_conditions, successor, carried
                ):
                    conditional = (extended, carried)

                if expanded >= max_nodes:
                    if conditional is None:
                        return PlanningResult(
                            status=PlanningStatus.INDETERMINATE,
                            goal_conditions=list(goal_conditions),
                            nodes_expanded=expanded,
                            reason=(
                                f"search bound reached ({max_nodes} states) without "
                                f"reaching the goal or exhausting the space"
                            ),
                        )
                    # A plan is held. Reporting INDETERMINATE and discarding it
                    # would throw away a real answer to say nothing was found.
                    frontier.clear()
                    break

                seen.add(successor)
                frontier.append((successor, extended, carried))

        if conditional is not None:
            extended, carried = conditional
            if not frontier and ruled_out is None:
                # The space was exhausted, so nothing shorter exists at all.
                ruled_out = len(extended)
            return PlanningResult(
                status=PlanningStatus.PLAN_FOUND,
                steps=[self._as_step(a) for a in extended],
                actions=extended,
                goal_conditions=list(goal_conditions),
                nodes_expanded=expanded,
                guarantee=PlanGuarantee.CONDITIONAL,
                deferred=sorted(carried),
                trace=self._trace(start, extended),
                initial=sorted(start),
                proved_ruled_out_to=ruled_out,
                reason=(
                    f"plan of {len(extended)} step(s) whose result depends on "
                    f"{', '.join(sorted(carried))}, which only running it can "
                    f"produce; the sequence is proved and the exact result is not"
                    + (f"; no proved plan of {ruled_out} step(s) or fewer exists"
                       if ruled_out else "")
                ),
            )

        return PlanningResult(
            status=PlanningStatus.UNREACHABLE,
            goal_conditions=list(goal_conditions),
            nodes_expanded=expanded,
            reason=(
                f"state space exhausted at {expanded} state(s); no sequence of "
                f"the available actions achieves the goal"
            ),
        )

    @staticmethod
    def _parse(conditions) -> List[Any]:
        from core.learning.rule_induction import Fact
        return [Fact.parse(c) for c in conditions]

    @staticmethod
    def _instances(action: Dict[str, Any], state_facts, parsed,
                   step: int, pending: FrozenSet[str]) -> List[Dict[str, Any]]:
        """Every way this operator applies here, with its values resolved.

        A fully ground operator is a membership test and is returned as it is.
        One with open slots is bound against the state, because the term that
        fills it was invented by an earlier action and had no name when the
        operator was built.

        RESOLVED PER APPLICATION, WHICH IS THE POINT. A value the action
        computes is computed from the terms in hand now, so it is a real number
        wherever the inputs are real numbers -- and a value only running the
        action can produce gets an unknown belonging to THIS occurrence. Two
        reads of a file are two answers; one placeholder for the whole operator
        would make the second indistinguishable from the first and the search
        would discard it as a state it had already seen.
        """
        from core.learning.rule_induction import Fact
        from core.reasoning.unification import match_body
        from core.reasoning.value_authority import evaluate

        outputs = action.get('outputs') or ()
        if not action.get('open') and not outputs:
            return [action] if all(p in state_facts for p in action['preconditions']) else []

        patterns = [Fact.parse(p) for p in action['preconditions']]
        state = parsed if parsed is not None else TemporalReasoningSystem._parse(state_facts)
        situation = hashlib.sha256(
            "|".join(sorted(state_facts)).encode()).hexdigest()[:8]

        instances: List[Dict[str, Any]] = []
        for bindings in (match_body(patterns, state) if patterns else [{}]):
            # What grounding already settled, then what matching here adds. An
            # output's inputs name the rule's own variables, and grounding
            # substituted them into the literals but not into the output spec.
            resolved = {**(action.get('bindings') or {}), **bindings}
            produced, deferred = [], []
            undefined = False

            for index, output in enumerate(outputs):
                arguments = [resolved.get(i, i) for i in output.get('inputs', ())]
                label = (output.get('producer') or output.get('function') or 'action').lower()
                seed = "|".join((str(action.get('name')), situation, str(step), str(index)))
                unknown = f"pending_{label}_{hashlib.sha256(seed.encode()).hexdigest()[:10]}"

                if output.get('origin') == 'derived' and not any(a in pending for a in arguments):
                    value = evaluate(output.get('function') or "", arguments)
                    if value is None:
                        undefined = True
                        break
                    resolved[output['variable']] = value
                    produced.append({**output, "term": value, "inputs": list(arguments)})
                    continue

                resolved[output['variable']] = unknown
                deferred.append(unknown)
                produced.append({**output, "term": unknown, "inputs": list(arguments)})

            if undefined:
                continue

            def render(conditions):
                return tuple(sorted(
                    Fact(f.predicate, tuple(resolved.get(a, a) for a in f.args)).to_formula()
                    for f in TemporalReasoningSystem._parse(conditions)))

            instances.append({
                **action,
                'name': render([action['name']])[0],
                'preconditions': list(render(action['preconditions'])),
                'effects': list(render(action.get('effects', []))),
                'deletes': list(render(action.get('deletes', []))),
                'bindings': {**action.get('bindings', {}), **resolved},
                'deferred': deferred,
                'produced': produced,
                'open': False,
            })
        return instances

    @staticmethod
    def _trace(start: FrozenSet[str], actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Replay the plan that was found, recording what each step read and made.

        Recorded from the plan itself rather than reconstructed afterwards: the
        bindings exist only while the step is being applied, and an account of a
        derivation that cannot be checked against the derivation is prose.
        """
        asserted_by: Dict[str, Optional[int]] = {condition: None for condition in start}
        recorded: List[Dict[str, Any]] = []
        for index, action in enumerate(actions, start=1):
            recorded.append({
                'step': index,
                'action': action.get('name'),
                'rule_id': action.get('rule_id'),
                'reads': {condition: asserted_by.get(condition)
                          for condition in action.get('preconditions', [])},
                'produced': [dict(p) for p in (action.get('produced') or ())],
            })
            for condition in action.get('deletes', []):
                asserted_by.pop(condition, None)
            for condition in action.get('effects', []):
                asserted_by[condition] = index
        return recorded

    @classmethod
    def explain_value(cls, result: "PlanningResult", term: str,
                      _depth: int = 0, _seen: Optional[Set[str]] = None) -> List[str]:
        """Where a value in this plan came from, read out of what was recorded.

        Rendered from `trace`, which the planner wrote while applying the
        steps, and from nothing else. An account of a derivation that cannot be
        checked against the derivation is prose, and prose about a computation
        is exactly the thing this layer was built to stop producing.

            5
              <- ?X0 := divide(20, 4)  at step 3, DIVIDE
                  20 <- NUMERATOR(20)  asserted by step 1, TAKE_TOTAL(c1)
                  4  <- DENOMINATOR(4)  asserted by step 2, TAKE_COUNT(c1)

        A term the plan did not produce is named as supplied by the problem,
        and a value the plan cannot predict says so rather than being given an
        origin it does not have.
        """
        pad = "  " * _depth
        seen = set(_seen or ())
        if term in seen:
            return [f"{pad}{term} — already accounted for above"]
        seen.add(term)

        made = next(((step, produced) for step in result.trace
                     for produced in step["produced"] if produced["term"] == term), None)
        if made is None:
            if any(term in condition for condition in result.initial):
                supplied = sorted(c for c in result.initial if term in c)
                return [f"{pad}{term} — supplied by the problem, in {', '.join(supplied)}"]
            return [f"{pad}{term} — not produced by this plan and not supplied by it"]

        step, produced = made
        if produced.get("origin") == "derived":
            how = f"{produced['variable']} := {produced['function']}(" \
                  f"{', '.join(produced['inputs'])})"
        else:
            how = (f"{produced['variable']} := {produced.get('producer')}() — not "
                   f"predictable; the value arrived when the step ran")

        lines = [f"{pad}{term}", f"{pad}  <- {how}  at step {step['step']}, {step['action']}"]

        # A value with no inputs was not computed from anything; what the step
        # READ is the only account of it there is.
        if not produced.get("inputs"):
            return lines + cls._explain_step(result, step["step"], _depth + 3, seen)

        made_here = {p["term"] for s in result.trace for p in s["produced"]}
        for argument in produced["inputs"]:
            mentions = sorted(c for c in step["reads"] if argument in c)
            for condition in mentions:
                lines.append(f"{pad}      {argument} <- {condition}  "
                             f"{cls._origin_of(step['reads'][condition])}")
                # An argument the plan itself made is explained as a value, so
                # a step that could not predict what it produced says so here
                # rather than only showing which fact carried it.
                lines.extend(
                    cls.explain_value(result, argument, _depth + 4, seen)
                    if argument in made_here
                    else cls._explain_step(result, step["reads"][condition],
                                           _depth + 4, seen))
            if not mentions:
                lines.extend(cls.explain_value(result, argument, _depth + 3, seen))
        return lines

    @staticmethod
    def _origin_of(asserted: Optional[int]) -> str:
        return (f"asserted by step {asserted}" if asserted
                else "supplied by the problem")

    @classmethod
    def _explain_step(cls, result: "PlanningResult", number: Optional[int],
                      depth: int, seen: Set[str]) -> List[str]:
        """What the step that asserted a fact had itself read, back to the problem.

        The chain terminates because a fact is only ever asserted by an EARLIER
        step, so each hop strictly decreases.
        """
        if not number:
            return []
        record = next((s for s in result.trace if s["step"] == number), None)
        if record is None:
            return []
        pad = "  " * depth
        lines = [f"{pad}{record['action']} read:"]
        for condition, asserted in sorted(record["reads"].items()):
            lines.append(f"{pad}  {condition}  {cls._origin_of(asserted)}")
            lines.extend(cls._explain_step(result, asserted, depth + 2, seen))
        return lines

    @staticmethod
    def _goal_satisfied_pending(
        goal_conditions: List[str], conditions: FrozenSet[str], pending: FrozenSet[str]
    ) -> bool:
        """Whether the goal holds once unknown values may stand for anything.

        `RESULT(5)` is satisfied by `RESULT(pending_read_0)` only in the
        sense that running the plan MIGHT produce it. That is why this decides
        CONDITIONAL and never PLAN_FOUND on its own: the difference between a
        plan that reaches five and a plan shaped like reaching five is the
        whole of the distinction.
        """
        from core.learning.rule_induction import Fact

        parsed = [Fact.parse(c) for c in conditions]
        for condition in goal_conditions:
            goal = Fact.parse(condition)
            if not any(
                fact.predicate == goal.predicate and fact.arity == goal.arity
                and all(a == b or b in pending for a, b in zip(goal.args, fact.args))
                for fact in parsed
            ):
                return False
        return True

    @staticmethod
    def _as_step(action: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'action': action['name'],
            'parameters': action.get('parameters', {}),
            'duration': action.get('duration', timedelta(minutes=5)),
            'description': action.get('description', ''),
        }

    def generate_plan_for_goal(
        self,
        goal: Any,
        current_state: Dict[str, Any],
        available_actions: List[Dict[str, Any]]
    ) -> Plan:
        """Plan, returning a Plan for callers that only need the steps.

        Prefer plan_for_state_goal, which distinguishes UNREACHABLE from
        INDETERMINATE. An empty Plan here means one of those and cannot say
        which.
        """
        result = self.plan_for_state_goal(goal, current_state, available_actions)
        return self.create_plan(goal=str(goal), steps=result.steps)

    def _extract_conditions(self, goal: Any) -> List[str]:
        """The conditions a goal requires.

        Accepts a state goal (a collection of condition strings) or a single
        condition. This previously wrapped whatever it was given in a list and
        called it one atomic condition, with a note that NLP would do better --
        so a goal of "AT(z,VAULT)" and a goal of "make everything nice" were
        handled identically, and neither could be decomposed.
        """
        if goal is None:
            return []
        if isinstance(goal, str):
            return [goal] if goal.strip() else []
        if isinstance(goal, (list, tuple, set, frozenset)):
            return [str(c) for c in goal if str(c).strip()]
        return [str(goal)]
    
    def _goal_satisfied(self, conditions: List[str], state: Dict[str, Any]) -> bool:
        """Check if goal conditions are satisfied"""
        return all(cond in state.get('conditions', []) for cond in conditions)
    
    def _action_applicable(self, action: Dict[str, Any], state: Dict[str, Any]) -> bool:
        """Check if action can be applied in current state"""
        preconditions = action.get('preconditions', [])
        return all(pre in state.get('conditions', []) for pre in preconditions)
    
    def _apply_action(self, action: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        """Apply action effects to state"""
        if 'conditions' not in state:
            state['conditions'] = []
        
        # Add effects
        for effect in action.get('effects', []):
            if effect not in state['conditions']:
                state['conditions'].append(effect)
        
        # Remove deleted conditions
        for delete in action.get('deletes', []):
            if delete in state['conditions']:
                state['conditions'].remove(delete)
        
        return state
    
    def _measure_progress(self, goal_conditions: List[str], state: Dict[str, Any]) -> float:
        """Measure progress toward goal"""
        met = sum(1 for cond in goal_conditions if cond in state.get('conditions', []))
        return met / max(len(goal_conditions), 1)
    
    # ==================================================================================
    # COUNTERFACTUAL REASONING
    # ==================================================================================
    
    def counterfactual_analysis(
        self,
        actual_event: TemporalProposition,
        counterfactual_event: TemporalProposition
    ) -> Dict[str, Any]:
        """Analyze 'what if' scenarios"""
        
        analysis = {
            'actual': actual_event.statement,
            'counterfactual': counterfactual_event.statement,
            'actual_effects': [],
            'counterfactual_effects': [],
            'difference': []
        }
        
        # Trace actual effects
        for link in self.causal_links.values():
            if link.cause_id == actual_event.prop_id:
                effect = self.propositions.get(link.effect_id)
                if effect:
                    analysis['actual_effects'].append(effect.statement)
        
        # Predict counterfactual effects
        counterfactual_predictions = self.predict_effect(counterfactual_event.prop_id)
        analysis['counterfactual_effects'] = [p.statement for p in counterfactual_predictions]
        
        # Find differences
        actual_set = set(analysis['actual_effects'])
        counter_set = set(analysis['counterfactual_effects'])
        
        analysis['difference'] = {
            'only_in_actual': list(actual_set - counter_set),
            'only_in_counterfactual': list(counter_set - actual_set),
            'common': list(actual_set & counter_set)
        }
        
        return analysis
    
    # ==================================================================================
    # PERSISTENCE
    # ==================================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        return {
            **self.stats,
            'total_propositions': len(self.propositions),
            'total_causal_links': len(self.causal_links),
            'total_future_states': len(self.future_states),
            'total_plans': len(self.plans),
            'timeline_events': len(self.timeline),
            'prediction_accuracy': (self.stats['predictions_correct'] / max(self.stats['predictions_made'], 1))
        }


# Global instance
_temporal_system: Optional[TemporalReasoningSystem] = None


def get_temporal_system() -> TemporalReasoningSystem:
    """Get or create global temporal reasoning system"""
    global _temporal_system
    
    if _temporal_system is None:
        _temporal_system = TemporalReasoningSystem()
    
    return _temporal_system
