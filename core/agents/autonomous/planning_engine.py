#!/usr/bin/env python3
"""
Planning Engine - Simplified goal and task planning
Consolidates all planning functionality from the monolithic controller
"""

from core.capability import raise_if_structural
import asyncio
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from uuid import uuid4

from .shared_types import (
    Goal, GoalType, Task, Plan, TaskType, TaskStatus, Priority, SystemState,
    PRIORITY_ORDINAL, priority_from_ordinal,
)
from .execution_plan_adapter import state_plan_to_tasks
from core.reasoning.temporal_reasoning import PlanningStatus


@dataclass
class PlanningOutcome:
    """What planning established, and by which mode.

    Returned instead of `Plan | None` so a caller can tell UNREACHABLE (proved
    impossible) from INDETERMINATE (not established) from UNSUPPORTED_GOAL.
    Collapsing those into None is what let the absence of a plan look like an
    ordinary result for the lifetime of this module.
    """

    status: PlanningStatus
    plan: Optional[Plan] = None
    planning_mode: str = "template"
    reason: str = ""
    goal_conditions: List[str] = field(default_factory=list)
    grounding_complete: bool = True
    operators_considered: int = 0

    @property
    def found(self) -> bool:
        return self.status is PlanningStatus.PLAN_FOUND
from core.database import get_unified_db
from core.tools import get_tool_registry, ToolRegistry

logger = logging.getLogger(__name__)


class PlanningEngine:
    """Manages goal setting, task planning, and execution sequencing"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        # Planning state
        self.current_goals: Dict[str, Goal] = {}
        self.active_plans: Dict[str, Plan] = {}
        self.task_queue: Dict[str, Task] = {}

        # Tool system integration
        self.tool_registry: ToolRegistry = get_tool_registry()

        # Use unified database singleton - initialized in async initialize()
        self.unified_db = None
        self.connection = None  # For backwards compatibility

        # Planning constraints
        self.max_concurrent_tasks = self.config.get("max_concurrent_tasks", 5)
        self.planning_horizon = self.config.get("planning_horizon_hours", 24)

        # Statistics
        self.stats = {
            "goals_created": 0,
            "plans_generated": 0,
            "tasks_completed": 0,
            "success_rate": 0.0,
            "tools_planned": 0
        }
    
    async def initialize(self) -> bool:
        """Initialize the planning engine"""
        try:
            # Get unified database singleton
            self.unified_db = await get_unified_db()
            # get_unified_db explicitly does NOT initialize the pool; main.py
            # does it at startup. Any other entry point reached this line with an
            # uninitialized pool, and every persistence call below then failed
            # into a logger.error while initialize() still returned True.
            if not getattr(self.unified_db, "initialized", False):
                await self.unified_db.initialize()

            # TorinUnifiedDatabase uses connection pools, not direct connection
            self.connection = self.unified_db  # Store database instance for queries

            # Create tables in unified PostgreSQL database
            await self._create_tables()

            # Load existing goals and plans
            await self._load_persistent_state()
            
            self.active = True
            logger.info("Planning engine initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize planning engine: {e}")
            return False
    
    async def create_goal(self, description: str, priority: Priority = Priority.MEDIUM,
                         deadline: Optional[datetime] = None,
                         intrinsic_values: Optional[Dict[str, float]] = None,
                         state_conditions: Optional[List[str]] = None) -> Optional[Goal]:
        """Create a new goal, optionally as a STATE goal.

        `state_conditions` is what makes a goal planned rather than merely
        described. Goal.goal_type derives from it -- STATE when present,
        DESCRIPTIVE otherwise -- and only a STATE goal reaches
        _plan_state_goal, which is the single path that consults learned rules.

        There was no way to supply them. The field existed, the planner read it,
        and the only writer repo-wide was a test, so every goal any production
        generator produced was DESCRIPTIVE and the validated MOVE operator could
        never supply planning authority outside that test.
        """
        if not self.active:
            return None
        
        try:
            # Extract intrinsic motivation values if provided
            intrinsic = intrinsic_values or {}
            
            # Safely extract intrinsic values, ensuring they're floats
            def get_float_value(key: str, default: float = 0.5) -> float:
                value = intrinsic.get(key, default)
                if isinstance(value, dict):
                    # If it's a dict, try to extract a numeric value
                    value = value.get('value', default) if isinstance(value, dict) else default
                return float(value) if not isinstance(value, dict) else default
            
            goal = Goal(
                id=str(uuid4()),
                description=description,
                priority=priority,
                deadline=deadline,
                created_at=datetime.now(),
                status="active",
                expected_novelty=get_float_value("expected_novelty", 0.5),
                expected_competence_gain=get_float_value("expected_competence_gain", 0.5),
                curiosity_value=get_float_value("curiosity_value", 0.5),
                intrinsic_reward_potential=get_float_value("intrinsic_reward_potential", 0.5),
                state_conditions=list(state_conditions) if state_conditions else None
            )
            
            # Durable first. Registering in memory before the write meant a
            # failed store left a goal the caller was told did not exist, which
            # then vanished at restart while plans referenced it.
            await self._store_goal(goal)
            self.current_goals[goal.id] = goal

            self.stats["goals_created"] += 1
            logger.info(f"Created goal: {description} (intrinsic potential: {goal.intrinsic_reward_potential:.2f})")
            return goal
            
        except Exception as e:
            logger.error(f"Error creating goal: {e}")
            return None
    
    async def plan_for_goal(
        self, goal_id: str, context: Optional[Dict[str, Any]] = None
    ) -> "PlanningOutcome":
        """Plan for a goal, in the mode its TYPE requires, reporting honestly.

        Mode is selected by `goal.goal_type`, never by a planner having failed.
        A state goal that cannot be solved returns UNREACHABLE or INDETERMINATE
        and stops there; it does not fall through to template decomposition.
        That fallthrough is the original silent-success defect, and routing it
        through a delegation layer would only make it harder to see.
        """
        if not self.active:
            return PlanningOutcome(PlanningStatus.UNSUPPORTED_GOAL,
                                   reason="planning engine is not active")
        if goal_id not in self.current_goals:
            return PlanningOutcome(PlanningStatus.INVALID_GOAL,
                                   reason=f"unknown goal {goal_id}")

        goal = self.current_goals[goal_id]
        if goal.goal_type is GoalType.STATE:
            return await self._plan_state_goal(goal, context or {})

        plan = await self.generate_plan(goal_id, context)
        return PlanningOutcome(
            PlanningStatus.PLAN_FOUND if plan else PlanningStatus.UNSUPPORTED_GOAL,
            plan=plan, planning_mode="template",
            reason="" if plan else "template decomposition produced no plan",
        )

    async def _plan_state_goal(
        self, goal: Goal, context: Dict[str, Any]
    ) -> "PlanningOutcome":
        """Search over grounded learned operators for a goal stated over state.

        The world state comes from the caller; nothing here invents one. Without
        it there is no problem to solve, and guessing an empty world would make
        every goal unreachable for a reason that is about the caller rather than
        the world.
        """
        from core.learning.rule_grounding import ground_for_problem
        from core.learning.rule_induction import Fact
        from core.learning.rule_store import get_rule_store
        from core.reasoning.temporal_reasoning import TemporalReasoningSystem

        world = context.get("world_state")
        if world is None:
            return PlanningOutcome(
                PlanningStatus.INDETERMINATE, planning_mode="state",
                reason="no world_state supplied; the goal cannot be evaluated",
            )

        state_facts = [Fact.parse(str(c)) for c in world]
        goal_facts = [Fact.parse(str(c)) for c in goal.state_conditions]

        rules = await get_rule_store().executable_rules(
            domain_id=context.get("domain_id"))
        grounding = ground_for_problem(rules, state_facts, goal_facts)

        result = TemporalReasoningSystem().plan_for_state_goal(
            [f.to_formula() for f in goal_facts],
            {"conditions": [f.to_formula() for f in state_facts]},
            grounding.to_actions(),
        )

        # An exhausted search only proves impossibility if the search was given
        # every operator. With a truncated grounding, "no plan" is ignorance
        # about Torin's own learned repertoire, not a fact about the world.
        status = result.status
        reason = result.reason
        if status is PlanningStatus.UNREACHABLE and not grounding.complete:
            status = PlanningStatus.INDETERMINATE
            reason = (
                f"{result.reason}; but grounding was truncated, so unreached is "
                f"not unreachable"
            )

        if status is not PlanningStatus.PLAN_FOUND:
            return PlanningOutcome(
                status, planning_mode="state", reason=reason,
                goal_conditions=list(result.goal_conditions),
                grounding_complete=grounding.complete,
                operators_considered=len(grounding.operators),
            )

        plan_id = str(uuid4())
        tasks = state_plan_to_tasks(result, goal, plan_id, grounding.complete,
                                    domain_id=context.get("domain_id"))
        plan = Plan(
            id=plan_id, goal_id=goal.id, tasks=tasks,
            estimated_duration=self._estimate_plan_duration(tasks),
            confidence=1.0,  # the plan is proved, not estimated
            created_at=datetime.now(), status="active",
        )
        await self._store_plan(plan)
        self.active_plans[plan.id] = plan
        self.stats["plans_generated"] += 1

        logger.info(
            "state plan for %s: %d step(s) from %d grounded operator(s)",
            goal.id, len(tasks), len(grounding.operators),
        )
        return PlanningOutcome(
            PlanningStatus.PLAN_FOUND, plan=plan, planning_mode="state",
            reason=result.reason, goal_conditions=list(result.goal_conditions),
            grounding_complete=grounding.complete,
            operators_considered=len(grounding.operators),
        )

    async def generate_plan(self, goal_id: str, context: Optional[Dict[str, Any]] = None) -> Optional[Plan]:
        """Template decomposition for a descriptive goal.

        Legal only because the goal has no state semantics. A state goal must
        never arrive here -- see plan_for_goal, which routes by type.
        """
        if not self.active or goal_id not in self.current_goals:
            return None

        try:
            goal = self.current_goals[goal_id]
            if goal.goal_type is GoalType.STATE:
                raise ValueError(
                    f"goal {goal_id} states world conditions and must be planned "
                    f"by search, not decomposed into a task template"
                )

            # Generate tasks for the goal
            tasks = await self._generate_tasks_for_goal(goal, context or {})

            plan = Plan(
                id=str(uuid4()),
                goal_id=goal_id,
                tasks=tasks,
                estimated_duration=self._estimate_plan_duration(tasks),
                confidence=self._calculate_plan_confidence(tasks, context or {}),
                created_at=datetime.now(),
                status="active"
            )
            
            await self._store_plan(plan)
            self.active_plans[plan.id] = plan

            self.stats["plans_generated"] += 1
            logger.info(f"Generated plan for goal: {goal.description}")
            return plan
            
        except Exception as e:
            logger.error(f"Error generating plan: {e}")
            return None
    
    async def get_next_tasks(self, system_state: SystemState) -> List[Task]:
        """Get next tasks to execute based on current system state.

        Authority changes are drained FIRST, because this is the single point
        where work leaves the planner. Draining anywhere else would leave a
        window in which a task authorised by a refuted rule could still be
        handed out.

        If the drain cannot run, nothing is dispatched. Dispatching on unknown
        authority is the failure this ordering exists to prevent, and an empty
        cycle is recoverable where an unauthorised action is not.
        """
        available_tasks = []

        try:
            await self.consume_rule_authority_changes()
        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'planning_engine.get_next_tasks')
            logger.error(
                "cannot confirm rule authority is current (%s) — dispatching "
                "nothing this cycle", e)
            return []

        try:
            # Get all ready tasks from active plans
            for plan in self.active_plans.values():
                if plan.status != "active":
                    continue
                
                for task in plan.tasks:
                    if (task.status == TaskStatus.PENDING and 
                        self._can_execute_task(task, system_state)):
                        available_tasks.append(task)
            
            # Sort by priority and dependencies
            def get_priority_value(task):
                """Safely extract priority value for sorting"""
                try:
                    if isinstance(task.priority, Priority):
                        # It's a Priority enum - use the enum ordering
                        priority_order = {
                            Priority.LOW: 0,
                            Priority.MEDIUM: 1,
                            Priority.HIGH: 2,
                            Priority.CRITICAL: 3
                        }
                        return priority_order.get(task.priority, 1)
                    elif hasattr(task.priority, 'value'):
                        # It's an enum with a value attribute
                        priority_map = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
                        return priority_map.get(str(task.priority.value).lower(), 1)
                    elif isinstance(task.priority, str):
                        # Convert string to numeric value for sorting
                        priority_map = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
                        return priority_map.get(task.priority.lower(), 1)
                    elif isinstance(task.priority, (int, float)):
                        # Already numeric
                        return float(task.priority)
                    else:
                        # Unknown type, use default
                        logger.warning(f"Unknown priority type for task {task.id}: {type(task.priority)}")
                        return 1
                except Exception as e:
                    # `except` must not turn a wiring defect into an empty result.
                    raise_if_structural(e, 'planning_engine.get_next_tasks')
                    logger.error(f"Error extracting priority value: {e}")
                    return 1
            
            available_tasks.sort(key=lambda t: (-get_priority_value(t), t.created_at.timestamp()))
            
            # Limit to max concurrent tasks
            return available_tasks[:self.max_concurrent_tasks]
            
        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'planning_engine.get_next_tasks')
            logger.error(f"Error getting next tasks: {e}")
            return []
    
    async def update_task_status(self, task_id: str, status: TaskStatus, 
                                result: Optional[Dict[str, Any]] = None) -> bool:
        """Update task status and handle completion"""
        try:
            # Find and update task
            for plan in self.active_plans.values():
                for task in plan.tasks:
                    if task.id == task_id:
                        task.status = status
                        if result:
                            task.result = result
                        
                        if status == TaskStatus.COMPLETED:
                            task.completed_at = datetime.now()
                            self.stats["tasks_completed"] += 1
                            
                            # Check if plan is complete
                            await self._check_plan_completion(plan.id)
                        
                        await self._store_plan(plan)
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return False
    
    async def get_prioritized_goals(self, intrinsic_weight: float = 0.3) -> List[Goal]:
        """
        Get goals prioritized by both external priority and intrinsic motivation
        
        Args:
            intrinsic_weight: Weight given to intrinsic motivation (0.0-1.0)
                             0.0 = pure external priority, 1.0 = pure intrinsic motivation
        """
        prioritized = []
        
        for goal in self.current_goals.values():
            if goal.status != "active":
                continue
            
            # Convert priority to numeric value
            priority_values = {
                Priority.LOW: 0.25,
                Priority.MEDIUM: 0.5,
                Priority.HIGH: 0.75,
                Priority.CRITICAL: 1.0
            }
            external_priority = priority_values.get(goal.priority, 0.5)
            
            # Safely extract intrinsic reward potential (handle dict case)
            intrinsic_potential = goal.intrinsic_reward_potential
            if isinstance(intrinsic_potential, dict):
                intrinsic_potential = intrinsic_potential.get('value', 0.5)
            intrinsic_potential = float(intrinsic_potential) if not isinstance(intrinsic_potential, dict) else 0.5
            
            # Calculate combined priority score
            combined_score = (
                (1.0 - intrinsic_weight) * external_priority +
                intrinsic_weight * intrinsic_potential
            )
            
            prioritized.append((combined_score, goal))
        
        # Sort by combined score (highest first)
        prioritized.sort(reverse=True, key=lambda x: x[0])
        
        return [goal for score, goal in prioritized]
    
    async def get_planning_status(self) -> Dict[str, Any]:
        """Get current planning status"""
        return {
            "active_goals": len(self.current_goals),
            "active_plans": len(self.active_plans),
            "pending_tasks": sum(
                1 for plan in self.active_plans.values() 
                for task in plan.tasks 
                if task.status == TaskStatus.PENDING
            ),
            "statistics": self.stats.copy()
        }
    
    async def _generate_tasks_for_goal(self, goal: Goal, context: Dict[str, Any]) -> List[Task]:
        """Generate tasks to achieve a goal - with tool integration"""
        tasks = []

        # Simple task generation based on goal type
        if "research" in goal.description.lower():
            tasks.extend(self._generate_research_tasks(goal))
        elif "analyze" in goal.description.lower():
            tasks.extend(self._generate_analysis_tasks(goal))
        elif "create" in goal.description.lower():
            tasks.extend(self._generate_creation_tasks(goal))
        else:
            # Default task breakdown
            tasks.append(Task(
                id=str(uuid4()),
                type=TaskType.RESEARCH,
                description=f"Research requirements for: {goal.description}",
                priority=goal.priority,
                estimated_duration=30.0,
                created_at=datetime.now()
            ))

            tasks.append(Task(
                id=str(uuid4()),
                type=TaskType.ANALYSIS,
                description=f"Analyze approach for: {goal.description}",
                priority=goal.priority,
                estimated_duration=20.0,
                created_at=datetime.now(),
                dependencies=[tasks[0].id]
            ))

            tasks.append(Task(
                id=str(uuid4()),
                type=TaskType.EXECUTION,
                description=f"Execute: {goal.description}",
                priority=goal.priority,
                estimated_duration=60.0,
                created_at=datetime.now(),
                dependencies=[tasks[1].id]
            ))

        # Enhance all tasks with tool suggestions
        enhanced_tasks = [self._enhance_task_with_tools(task) for task in tasks]

        return enhanced_tasks
    
    def _generate_research_tasks(self, goal: Goal) -> List[Task]:
        """Generate research-specific tasks"""
        return [
            Task(
                id=str(uuid4()),
                type=TaskType.RESEARCH,
                description=f"Information gathering for: {goal.description}",
                priority=goal.priority,
                estimated_duration=45.0,
                created_at=datetime.now()
            ),
            Task(
                id=str(uuid4()),
                type=TaskType.ANALYSIS,
                description=f"Analyze research findings for: {goal.description}",
                priority=goal.priority,
                estimated_duration=30.0,
                created_at=datetime.now()
            )
        ]
    
    def _generate_analysis_tasks(self, goal: Goal) -> List[Task]:
        """Generate analysis-specific tasks"""
        return [
            Task(
                id=str(uuid4()),
                type=TaskType.ANALYSIS,
                description=f"Data analysis for: {goal.description}",
                priority=goal.priority,
                estimated_duration=40.0,
                created_at=datetime.now()
            ),
            Task(
                id=str(uuid4()),
                type=TaskType.SYNTHESIS,
                description=f"Synthesize analysis results for: {goal.description}",
                priority=goal.priority,
                estimated_duration=25.0,
                created_at=datetime.now()
            )
        ]
    
    def _generate_creation_tasks(self, goal: Goal) -> List[Task]:
        """Generate creation-specific tasks"""
        return [
            Task(
                id=str(uuid4()),
                type=TaskType.PLANNING,
                description=f"Plan creation process for: {goal.description}",
                priority=goal.priority,
                estimated_duration=20.0,
                created_at=datetime.now()
            ),
            Task(
                id=str(uuid4()),
                type=TaskType.EXECUTION,
                description=f"Create: {goal.description}",
                priority=goal.priority,
                estimated_duration=90.0,
                created_at=datetime.now()
            ),
            Task(
                id=str(uuid4()),
                type=TaskType.VALIDATION,
                description=f"Validate creation: {goal.description}",
                priority=goal.priority,
                estimated_duration=15.0,
                created_at=datetime.now()
            )
        ]
    
    def _estimate_plan_duration(self, tasks: List[Task]) -> float:
        """Estimate total duration for plan execution"""
        return sum(task.estimated_duration for task in tasks)
    
    def _calculate_plan_confidence(self, tasks: List[Task], context: Dict[str, Any]) -> float:
        """Calculate confidence in plan success"""
        base_confidence = 0.7
        
        # Adjust based on task complexity
        if len(tasks) <= 3:
            base_confidence += 0.2
        elif len(tasks) > 7:
            base_confidence -= 0.1
        
        # Adjust based on context
        if context.get("available_resources", 0) > 0.8:
            base_confidence += 0.1
        
        return min(1.0, max(0.0, base_confidence))
    
    def _can_execute_task(self, task: Task, system_state: SystemState) -> bool:
        """Check if task can be executed given current system state.

        Dependencies fail CLOSED. The previous form was
        `if dep_id in dep_tasks and ... != COMPLETED`, so a dependency id that
        matched no known task read as "no blocker" rather than "cannot be
        satisfied". Ordering in a state plan is carried entirely by these
        chains, so an unresolvable id there would let steps run out of
        sequence -- with each step's preconditions established by the one
        before it, that is silent corruption rather than a visible failure.
        """
        if task.dependencies:
            known: Dict[str, Task] = {}
            for plan in self.active_plans.values():
                known.update({t.id: t for t in plan.tasks})

            for dep_id in task.dependencies:
                dependency = known.get(dep_id)
                if dependency is None:
                    logger.error(
                        "task %s depends on unknown task %s — refusing to run it",
                        task.id, dep_id,
                    )
                    return False
                if dependency.status != TaskStatus.COMPLETED:
                    return False


        # Check resource requirements
        if system_state.resource_usage > 0.9:
            return task.priority == Priority.HIGH
        
        return True
    
    async def consume_rule_authority_changes(self) -> Dict[str, Any]:
        """Withdraw plans that stand on a rule which has lost its authority.

        Plans are authorised at planning time by the rules they ground. When a
        rule is refuted, every unrun step that depends on it is unauthorised —
        including steps queued behind a predecessor that completed perfectly.
        A dependency chain guarantees ORDER, not continued validity, so
        "my predecessor finished" is not a reason for the next step to run.

        The executor does not call this and does not know it exists. It writes
        down that authority changed; what that means for plans is decided here,
        which is where plans live.

        Completed work is left alone. It happened, and the rule was validated
        when it did — that is history, not something to retract.
        """
        from core.learning.rule_authority import (
            mark_consumed, pending_authority_changes)

        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        events = await pending_authority_changes(self.connection, lost_only=True)
        report = {
            "events": len(events),
            "plans_invalidated": [],
            "tasks_blocked": 0,
            "rules": sorted({e.rule_id for e in events}),
        }
        if not events:
            return report

        revoked = {e.rule_id for e in events}
        unrunnable = {TaskStatus.PENDING, TaskStatus.PLANNED,
                      TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}

        for plan in list(self.active_plans.values()):
            if plan.status != "active":
                continue

            affected = [
                task for task in plan.tasks
                if task.status in unrunnable
                and (task.provenance or {}).get("learned_rule_id") in revoked
            ]
            if not affected:
                continue

            for task in affected:
                task.status = TaskStatus.BLOCKED
                task.result = {
                    **(task.result or {}),
                    "blocked_reason": "learned_rule_lost_execution_authority",
                    "learned_rule_id": (task.provenance or {})["learned_rule_id"],
                }
            plan.status = "invalidated"
            plan.metadata = {
                **(plan.metadata or {}),
                "invalidated_by": "rule_authority_change",
                "revoked_rules": sorted(
                    {(t.provenance or {})["learned_rule_id"] for t in affected}),
                "invalidated_at": datetime.now().isoformat(),
            }
            await self._store_plan(plan)

            report["plans_invalidated"].append(plan.id)
            report["tasks_blocked"] += len(affected)
            logger.warning(
                "plan %s invalidated: %d step(s) depended on a rule that lost "
                "execution authority (%s)",
                plan.id, len(affected), ", ".join(plan.metadata["revoked_rules"]),
            )

        # Drained only after the plans are durably written. Marking first would
        # let a crash in between lose the event and leave an invalidated plan
        # still queued, with nothing left to say why it should not be.
        report["drained"] = await mark_consumed(
            self.connection, [e.event_id for e in events], "planning_engine")
        return report

    async def _check_plan_completion(self, plan_id: str):
        """Check if plan is complete and update goal status"""
        if plan_id not in self.active_plans:
            return
        
        plan = self.active_plans[plan_id]
        completed_tasks = sum(1 for task in plan.tasks if task.status == TaskStatus.COMPLETED)
        
        if completed_tasks == len(plan.tasks):
            plan.status = "completed"
            plan.completed_at = datetime.now()
            
            # Update goal status
            if plan.goal_id in self.current_goals:
                self.current_goals[plan.goal_id].status = "completed"
                self.current_goals[plan.goal_id].completed_at = datetime.now()
            
            # Update success rate
            total_plans = self.stats["plans_generated"]
            completed_plans = sum(1 for p in self.active_plans.values() if p.status == "completed")
            self.stats["success_rate"] = completed_plans / total_plans if total_plans > 0 else 0.0
    
    async def _create_tables(self):
        """Ensure the goals and plans tables exist, with the real column types.

        These declarations previously disagreed with the tables a migration had
        already created -- priority VARCHAR against an INTEGER column, epoch
        DOUBLE PRECISION against TIMESTAMP, TEXT tasks against JSONB. Because
        the tables existed, CREATE TABLE IF NOT EXISTS was a permanent no-op and
        the disagreement was invisible until every INSERT failed on type.

        The deployed schema is authoritative; these match it. Raises on failure
        so initialize() cannot report success over a broken store.
        """
        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        await self.connection.execute_query("""
            CREATE TABLE IF NOT EXISTS goals (
                id VARCHAR(255) PRIMARY KEY,
                description TEXT NOT NULL,
                priority INTEGER,
                deadline TIMESTAMP,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                status VARCHAR(50) DEFAULT 'active'
            )
        """, commit=True)

        await self.connection.execute_query("""
            CREATE TABLE IF NOT EXISTS plans (
                id VARCHAR(255) PRIMARY KEY,
                goal_id VARCHAR(255),
                tasks JSONB NOT NULL,
                estimated_duration INTEGER,
                confidence NUMERIC,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                status VARCHAR(50) DEFAULT 'active'
            )
        """, commit=True)

        logger.debug("Goals and plans tables ready")

    async def _store_goal(self, goal: Goal):
        """Store goal in database.

        Raises on failure. This previously wrote `goal.priority.name` into an
        INTEGER column and `.timestamp()` floats into TIMESTAMP columns, caught
        the resulting error and logged it, so create_goal reported success and
        incremented its counter while no goal was ever written -- in production
        or anywhere. The types below are the ones unified.goals actually has.
        """
        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        await self.connection.execute_query(
            """
            INSERT INTO goals
            (id, description, priority, deadline, created_at, completed_at, status,
             state_conditions)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                description = EXCLUDED.description,
                priority = EXCLUDED.priority,
                deadline = EXCLUDED.deadline,
                completed_at = EXCLUDED.completed_at,
                status = EXCLUDED.status,
                state_conditions = EXCLUDED.state_conditions
            """,
            params=(
                goal.id, goal.description, PRIORITY_ORDINAL[goal.priority],
                goal.deadline, goal.created_at, goal.completed_at, goal.status,
                # Persisted, or a goal comes back from restart having silently
                # become DESCRIPTIVE -- losing its planning authority exactly
                # when the plan it belongs to needs resuming.
                json.dumps(list(goal.state_conditions)) if goal.state_conditions else None,
            ),
            commit=True,
        )

    async def _store_plan(self, plan: Plan):
        """Store plan in database. Raises on failure; see _store_goal."""
        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        tasks_json = json.dumps([
            {
                "id": task.id,
                "type": task.type.name,
                "description": task.description,
                "priority": task.priority.name,
                "status": task.status.name,
                "estimated_duration": task.estimated_duration,
                "created_at": task.created_at.isoformat(),
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "dependencies": task.dependencies,
                "result": task.result,
                "provenance": task.provenance,
            }
            for task in plan.tasks
        ])

        await self.connection.execute_query(
            """
            INSERT INTO plans
            (id, goal_id, tasks, estimated_duration, confidence, created_at, completed_at, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                tasks = EXCLUDED.tasks,
                estimated_duration = EXCLUDED.estimated_duration,
                confidence = EXCLUDED.confidence,
                completed_at = EXCLUDED.completed_at,
                status = EXCLUDED.status
            """,
            params=(
                plan.id, plan.goal_id, tasks_json,
                # estimated_duration is INTEGER and confidence NUMERIC in the
                # table this actually writes to.
                int(round(plan.estimated_duration or 0)),
                Decimal(str(round(float(plan.confidence or 0.0), 6))),
                plan.created_at, plan.completed_at, plan.status,
            ),
            commit=True,
        )

    async def _load_persistent_state(self):
        """Load goals and plans from database"""
        if not self.connection:
            return

        try:
            # Load goals
            goal_rows = await self.connection.execute_query(
                "SELECT * FROM goals WHERE status = 'active'",
                fetch_all=True
            )

            if goal_rows:
                for row in goal_rows:
                    goal = Goal(
                        id=row['id'],
                        description=row['description'],
                        # The columns are INTEGER and TIMESTAMP; the previous
                        # reader assumed a name string and epoch floats, so it
                        # could not have loaded a row even if one existed.
                        priority=priority_from_ordinal(row['priority']),
                        deadline=row['deadline'],
                        created_at=row['created_at'],
                        completed_at=row['completed_at'],
                        status=row['status'],
                        expected_novelty=0.5,
                        expected_competence_gain=0.5,
                        curiosity_value=0.5,
                        intrinsic_reward_potential=0.5,
                        state_conditions=(
                            json.loads(row['state_conditions'])
                            if isinstance(row.get('state_conditions'), str)
                            else row.get('state_conditions'))
                    )
                    self.current_goals[goal.id] = goal

            # Load plans
            plan_rows = await self.connection.execute_query(
                "SELECT * FROM plans WHERE status = 'active'",
                fetch_all=True
            )

            if plan_rows:
                for row in plan_rows:
                    tasks_data = json.loads(row['tasks'])
                    tasks = []
                    for task_data in tasks_data:
                        task = Task(
                            id=task_data["id"],
                            type=TaskType[task_data["type"]],
                            description=task_data["description"],
                            priority=Priority[task_data["priority"]],
                            status=TaskStatus[task_data["status"]],
                            estimated_duration=task_data["estimated_duration"],
                            created_at=datetime.fromisoformat(task_data["created_at"]),
                            completed_at=(datetime.fromisoformat(task_data["completed_at"])
                                          if task_data["completed_at"] else None),
                            dependencies=task_data["dependencies"],
                            result=task_data["result"],
                            provenance=task_data.get("provenance"),
                        )
                        tasks.append(task)

                    plan = Plan(
                        id=row['id'],
                        goal_id=row['goal_id'],
                        tasks=tasks,
                        estimated_duration=row['estimated_duration'],
                        confidence=float(row['confidence']) if row['confidence'] is not None else 0.0,
                        created_at=row['created_at'],
                        completed_at=row['completed_at'],
                        status=row['status']
                    )
                    self.active_plans[plan.id] = plan

        except Exception as e:
            logger.error(f"Error loading persistent state: {e}")
    
    def _suggest_tools_for_task(self, task_type: TaskType) -> List[str]:
        """Suggest appropriate tools for a task type"""
        tool_suggestions = {
            TaskType.RESEARCH: [
                "semantic_search",
                "grep_search",
                "read_file",
                "list_directory"
            ],
            TaskType.ANALYSIS: [
                "analyze_code",
                "grep_search",
                "read_file",
                "semantic_search"
            ],
            TaskType.EXECUTION: [
                "run_python",
                "run_shell_command",
                "execute_sandbox",
                "write_file"
            ],
            TaskType.VALIDATION: [
                "read_file",
                "run_python",
                "analyze_code"
            ],
            TaskType.SYNTHESIS: [
                "read_file",
                "write_file",
                "semantic_search"
            ]
        }

        suggested = tool_suggestions.get(task_type, [])
        available_tools = self.tool_registry.list_tools()

        # Return only tools that are actually registered
        return [tool for tool in suggested if tool in available_tools]

    def _enhance_task_with_tools(self, task: Task) -> Task:
        """Enhance task with appropriate tool metadata"""
        suggested_tools = self._suggest_tools_for_task(task.type)

        if suggested_tools:
            if not task.metadata:
                task.metadata = {}
            task.metadata["suggested_tools"] = suggested_tools
            task.metadata["tool_enabled"] = True
            self.stats["tools_planned"] += 1

            logger.debug(f"Task '{task.description}' enhanced with {len(suggested_tools)} tool suggestions")

        return task

    async def shutdown(self):
        """Shutdown the planning engine"""
        self.active = False
        if self.connection:
            self.connection.close()
            self.connection = None
        logger.info("Planning engine shutdown completed")