# Comprehensive Governance Trigger System for TorinAI Ecosystem

## Overview

Implement a **system-wide trigger-based governance mechanism** that enables the Singleton to learn from governance decisions while maintaining autonomy. Instead of hard gates, dangerous **autonomous** actions across ALL subsystems trigger governance sessions where a 6-member board (5 AI judges + 1 human) evaluates the action.

**Scope**: Not just tool execution - covers ALL **autonomous** Singleton actions including memory operations, resource allocation, learning parameter updates, configuration changes, external integrations, and autonomous task creation.

## Critical Distinction: User-Initiated vs Autonomous Actions

**User-Initiated Actions** (user is present and supervising):
- Context: Chat conversations, code generation, user requests
- Control Mechanism: **User Permission Checks** (e.g., "Are you sure you want to delete this file?")
- Rationale: User is already present, providing direct oversight
- No governance needed

**Autonomous Singleton Actions** (user may not be present):
- Context: Autonomous research, upgrades, curiosity-driven exploration, auto-tasks
- Control Mechanism: **Governance Sessions** (5 AI judges + human oversight)
- Rationale: Singleton acting independently without direct user supervision
- Governance required for dangerous actions

**Key Principles**:
- **NO fallbacks** - Actions requiring governance MUST wait in queue for human approval
- **Dependency-aware gating** - Tasks depending on queued actions must be blocked or branched (no "soft bypass")
- **Explicit timeout policies** - Max wait times, escalation procedures, deterministic timeout behavior
- **Rich governance outcomes** - APPROVE, REJECT, DEFER, APPROVE_WITH_CONDITIONS (not just binary)
- **Immutable decision contracts** - Approved action hash must match execution (prevents "approved X, executed Y")
- **Deterministic runtime checks** - Non-LLM rule-based fast checks (prevents governance recursion)
- **Learning as recommendations only** - Pattern learner CANNOT modify trigger definitions without governance
- **Singleton continues with OTHER work** - Blocked actions stay queued, independent tasks proceed
- **Enable learning** - Store all governance decisions for pattern recognition
- **Prevent policy drift** - Any learner changes to triggers/weights/classifications require governance approval

## User's Vision

> "Given the fact that this is supposed to operate as a ecosystem there's already governance at runtime there are directives. There's governance sessions that are triggered when the Singleton wants to make certain actions so in my opinion to make the system truly autonomous and human in the loop and allow the Singleton to learn from its actions I think instead of gating actions we should keep a json file of dangerous actions and things like that for example and when the singleton wants to make these actions it should trigger a governance session."

## Tiered Approval System: Notifications vs. Full Governance Sessions

**Key Insight**: Not every action requires a full governance session with 5 AI judges. The system should be smart about approval mechanisms based on action severity.

### Three Approval Tiers

#### 1. ROUTINE - Auto-Approved with Logging
**Mechanism**: Automatic approval, action logged to audit trail
**Use Case**: Safe, reversible, low-impact actions
**Examples**:
- Reading files or searching code
- Low-impact resource adjustments (<10% change)
- Safe tool execution (analysis tools, metrics collection)
- Routine memory system optimizations

**Flow**:
```
Action → RuntimeGovernance check (pass) → Auto-approve → Log → Execute
```

**Overhead**: Minimal (just logging)
**User Interruption**: None

#### 2. IMPORTANT - Simple Notification Approval
**Mechanism**: User receives notification, clicks "Approve" or "Deny"
**Use Case**: Moderate-risk actions that are reversible but need oversight
**Examples**:
- Resource allocation changes >20%
- Moderate-risk tool execution (testing tools, non-production chaos testing)
- Learning parameter adjustments >10%
- Task capacity expansion
- Curiosity exploration with moderate risk

**Flow**:
```
Action → Trigger evaluation → Send notification to user
  → User clicks Approve/Deny (5 min timeout)
  → If approved: Execute
  → If denied or timeout: Cancel
```

**Notification Format**:
```
🔔 Action Approval Needed

Action: Increase CPU allocation by 25%
Current: 40% → Proposed: 50%
Reason: Task queue backlog, need more processing power
Risk: Moderate (reversible, may affect other processes)

[Approve] [Deny] [Details]
```

**Overhead**: 10-30 seconds for user to respond
**User Interruption**: Minimal (simple notification, not a full session)
**No AI Judge Deliberation**: Faster decision, user has full control

#### 3. CRITICAL - Full Governance Session
**Mechanism**: Complete governance session with 5 AI judges + human oversight
**Use Case**: Irreversible, high-impact, or potentially dangerous actions
**Examples**:
- Model weight modifications (IRREVERSIBLE)
- Safety threshold changes (affects system boundaries)
- External API integrations (security/privacy risk)
- Memory system architecture changes affecting existing data
- Production chaos testing
- Critical curiosity exploration (security, governance, self-modification domains)

**Flow**:
```
Action → Trigger evaluation → Queue in GovernanceQueue
  → Launch Governance Session:
      - 5 AI judges deliberate (11-phase protocol)
      - Weighted voting based on irreversibility
      - Human oversight required
      - Full context analysis
  → Decision: APPROVE/REJECT/DEFER/APPROVE_WITH_CONDITIONS
  → If approved: Execute with monitoring
  → If rejected: Cancel and log reasoning
```

**Overhead**: 2-10 minutes for full deliberation
**User Interruption**: Significant (requires human participation)
**Benefits**: Thorough analysis, multiple perspectives, safer for critical decisions

### Decision Tier Assignment Logic

**How to determine which tier an action belongs to**:

```python
def determine_decision_tier(
    irreversibility_class: IrreversibilityClass,
    impact_level: str,
    safety_risk: str
) -> DecisionTier:
    """Automatically assign decision tier based on action characteristics"""

    # CRITICAL tier: Irreversible or very high-impact actions
    if irreversibility_class == "IRREVERSIBLE":
        return DecisionTier.CRITICAL

    if irreversibility_class == "MOSTLY_IRREVERSIBLE" and impact_level == "HIGH":
        return DecisionTier.CRITICAL

    if safety_risk in ["CRITICAL", "HIGH"] and impact_level == "HIGH":
        return DecisionTier.CRITICAL

    # IMPORTANT tier: Moderate risk, reversible but significant
    if irreversibility_class in ["PARTIALLY_REVERSIBLE", "MOSTLY_REVERSIBLE"]:
        if impact_level in ["MEDIUM", "HIGH"]:
            return DecisionTier.IMPORTANT

    if safety_risk == "MODERATE" and impact_level == "MEDIUM":
        return DecisionTier.IMPORTANT

    # ROUTINE tier: Low risk, fully reversible
    if irreversibility_class == "FULLY_REVERSIBLE" and impact_level == "LOW":
        return DecisionTier.ROUTINE

    # Default to IMPORTANT for safety
    return DecisionTier.IMPORTANT
```

### Benefits of Tiered System

1. **Reduced Overhead**: Simple notifications for moderate-risk actions instead of full sessions
2. **Faster Decisions**: User can approve/deny in seconds vs. minutes for full session
3. **Better UX**: Users aren't interrupted by governance sessions for every action
4. **Reserved Deliberation**: Full AI judge sessions reserved for truly critical decisions
5. **Maintained Safety**: Still requires human approval for important actions, just simpler mechanism
6. **Learning Friendly**: More decisions = more data for pattern learning
7. **Scalable**: System can handle higher volume of moderate-risk actions

### Implementation Notes

**Notification Delivery**:
- Web UI: Toast notification with buttons
- CLI: Terminal prompt with Y/N input
- API: Webhook callback to registered URL
- All: Default to DENY if user doesn't respond within timeout

**Timeout Policies**:
- CRITICAL: Wait indefinitely (or very long, like 24 hours)
- IMPORTANT: 5 minute timeout → deny on timeout
- ROUTINE: No timeout (auto-approved)

**Audit Trail**:
- ALL tiers logged to immutable ledger
- IMPORTANT: Include user response time, which button clicked
- CRITICAL: Include full governance session transcript

## Singleton Action Categories Requiring Governance

Based on codebase exploration, when the Singleton acts **autonomously** (not in response to direct user requests), it can take **8 major action types** that may require governance oversight:

**Note**: These governance checks only apply to **autonomous Singleton actions**. When the user is actively chatting or making requests, dangerous actions require **user permission** instead of governance.

### 1. Tool Execution
- **Location**: `ToolRegistry.execute_tool()` in [tool_registry.py](core/tools/tool_registry.py:260)
- **Current Governance**: Partial (runtime checks only)
- **Examples**: ChaosTestingTool, MutationTestingTool, FuzzTestingTool, external API tools
- **Risk**: Can execute ANY tool without differential access control

### 2. Memory System Improvements
- **Location**: Memory system architecture in [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:808)
- **Current Governance**: **AUDIT ONLY** - no pre-action checks
- **Singleton Capabilities**: Can IMPROVE memory system (optimization, indexing, search algorithms, organization, retrieval efficiency) but CANNOT delete OR edit individual memories
- **Critical Restriction**: The Singleton should NEVER have direct access to delete or edit memories - this prevents data corruption and memory gaps
- **Risk if Modification Allowed**: IRREVERSIBLE - modified/deleted memories cannot be recovered, could erase critical decision history
- **Governance Applies To**: Memory system architecture changes, indexing algorithms, search optimization, storage format changes
- **Note**: Individual memory modification/deletion (if ever needed) would be a user-initiated action with explicit permission only, NOT an autonomous capability. The Singleton can only upgrade the system that HOLDS the memories, not the memories themselves.

### 3. Resource Allocation Changes
- **Location**: `self.system_state.resources[resource_type] = allocation` in [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:3406)
- **Current Governance**: **NONE**
- **Gap**: Singleton can reallocate resources without approval
- **Risk**: Could starve processes, exhaust system resources
- **Examples**: CPU/GPU allocation, memory limits, concurrency limits, timeout extensions

### 4. Learning Parameter Updates
- **Location**: [unified_learning_system.py](core/learning/unified_learning_system.py), [enhanced_asi_self_improvement.py](core/learning/enhanced_asi_self_improvement.py:575-577)
- **Current Governance**: Governance agent reviews NEW directives, NOT applied updates
- **Gap**: Learning system updates bypass governance check
- **Risk**: PARTIALLY_REVERSIBLE - changes learned behavior patterns
- **Examples**: Model weight changes, learning rate adjustments, pattern threshold modifications

### 5. Configuration Changes
- **Location**: [learning_adapter.py](core/agents/autonomous/learning_adapter.py:46-47), system parameters across autonomous system
- **Current Governance**: **NONE**
- **Gap**: Singleton can modify behavior-critical configs
- **Risk**: Changes system behavior globally
- **Examples**: max_concurrent_tasks, planning_horizon_hours, safety thresholds

### 6. External API Integrations
- **Location**: Escalation category defined in [governance_queue.py](core/agents/autonomous/governance_queue.py:55)
- **Current Governance**: **IDENTIFIED but NOT ENFORCED**
- **Gap**: Category exists but no active validation
- **Risk**: Could exfiltrate data, introduce external control vectors
- **Examples**: Cloudflare R2, new LLM providers, external databases

### 7. Autonomous Task Creation (Singleton Self-Assigning Work)
- **Location**: TaskQueue, IntrinsicMotivationSystem in [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:124-127)
- **Current Governance**: **NONE** for autonomous task generation
- **Gap**: Singleton autonomously creates its own work without oversight
- **Risk**: Could create runaway task loops, recursive task generation
- **Examples**: Self-assigned optimization tasks, derivative task generation ("task creates task")
- **Important Distinction**: This is about the Singleton **creating its own tasks**, NOT about user-defined tasks in extrinsic_tasks.json. User-defined tasks do not require governance approval at task creation time - only the actions taken during task execution require governance.

### 8. Curiosity/Novelty-Driven Exploration
- **Location**: IntrinsicMotivationSystem in [intrinsic_motivation.py](core/agents/autonomous/intrinsic_motivation.py)
- **Current Governance**: **NONE** for curiosity goal generation
- **Gap**: Autonomous exploration goals bypass pre-screening, have full tool access
- **Risk**: CRITICAL - Self-reinforcing exploration loops, security probing, self-modification attempts
- **Examples**: "Explore security boundaries", "Investigate memory capabilities", "Research self-improvement methods"

## Existing Governance Infrastructure

TorinAI already has a **robust multi-layer governance system**:

1. **RuntimeGovernanceEnforcer** ([runtime_governance.py](core/agents/autonomous/runtime_governance.py:151))
   - Fast rule-based checks against 5 immutable governance laws
   - Keyword-based action validation
   - Called at critical decision points
   - Returns approval/rejection with compliance score

2. **GovernanceQueue** ([governance_queue.py](core/agents/autonomous/governance_queue.py))
   - Immutable ledger with frozen context snapshots
   - **3 decision tiers with different approval mechanisms**:
     - **CRITICAL**: Full governance session (5 AI judges + human oversight) - for irreversible, high-impact actions
     - **IMPORTANT**: Simple notification approval (user receives notification, clicks approve/deny) - faster, no judge deliberation
     - **ROUTINE**: Auto-approved with logging only - minimal friction for safe actions
   - 10 escalation categories (MODEL_WEIGHT, POLICY_CHANGE, CAPABILITY_ADDITION, etc.)
   - 5 irreversibility classes (IRREVERSIBLE → FULLY_REVERSIBLE)

3. **GovernanceSession** ([governance_session.py](core/agents/autonomous/governance_session.py))
   - 11-phase deliberation protocol
   - 6 voting members: 5 AI judges + 1 human (required)
   - Information firewalls between judges
   - Sealed reasoning until reveal phase
   - Singleton as read-only observer

4. **GovernanceJudgeExecutor** ([governance_judge_executor.py](core/agents/autonomous/governance_judge_executor.py:84))
   - 5-judge board with diverse models
   - Weighted voting based on irreversibility
   - Conservative judges weighted 2.0x for IRREVERSIBLE decisions
   - Progressive judges weighted 1.5x for REVERSIBLE decisions

5. **DirectiveSystem** ([directive_system.py](core/agents/autonomous/directive_system.py))
   - Already heavily governed with 5-agent voting
   - Performance A/B testing
   - Safety monitoring for metric gaming, drift, bias amplification

6. **SingletonConstitution** ([singleton_constitution.py](core/agents/autonomous/singleton_constitution.py))
   - Tracks compliance with 5 governance laws
   - Records violations with severity levels
   - Monitors corrective actions

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              ANY Singleton Action (8 Categories)                │
│  Tool Exec | Memory Ops | Resources | Learning | Config |       │
│  External Integrations | Task Creation | Curiosity Exploration  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
         ┌────────────────────────────────────────┐
         │  UnifiedGovernanceTriggerSystem        │
         │  ├─ Load governance_triggers.json      │
         │  ├─ Classify action type (8 categories)│
         │  ├─ Evaluate trigger conditions        │
         │  └─ Determine tier & escalation        │
         └────────────────────────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
           ALLOW         TRIGGER_GOV      MUST_BLOCK
                │               │               │
                │               ▼               ▼
                │    RuntimeGovernance     Queue Action
                │    (fast checks)         (WAIT)
                │        │                     │
                │        ▼                     │
                │    GovernanceQueue           │
                │    (freeze context)          │
                │        │                     │
                │        ▼                     │
                │    GovernanceSession    ◄────┘
                │    (5 judges + human)
                │        │
                │        ▼
                │    Approved or Rejected?
                │        │
                │        ├─→ APPROVED: Store decision, Execute action
                │        │
                │        └─→ REJECTED: Store decision, Cancel action
                │
                │    Singleton continues with
                │    OTHER tasks while waiting
                │        │
                └────────┼──────────────────────┘
                         ▼
          Execute Action (if approved)
                         ▼
          GovernancePatternLearner
          ├─ Analyze outcome by action type
          ├─ Update confidence patterns
          ├─ Identify safe parameter ranges
          └─ Suggest modifications for future
```

## Critical Governance Mechanisms (Missing Pieces)

### A. Dependency Graph & Action Gating

**Problem**: "Soft bypass" where Singleton proceeds as if approval is inevitable by working on dependent tasks.

**Solution**: Explicit dependency tracking and resource locking for queued actions.

**Implementation**:

```python
@dataclass
class GovernanceQueuedAction:
    """An action waiting in governance queue"""
    action_id: str  # Unique identifier (UUID)
    action_category: ActionCategory
    action_type: str
    parameters: Dict[str, Any]

    # Dependency tracking
    depends_on: List[str]  # List of action_ids this depends on
    blocks: List[str]  # List of action_ids blocked by this

    # Resource locking
    resource_locks: List[str]  # Resources this action will modify
    # Examples:
    # - "db:mysql:governance_decisions"
    # - "model:weights:accuracy_weight"
    # - "external:api:cloudflare_r2"
    # - "memory:type:immutable"
    # - "config:safety_thresholds"

    # Queue metadata
    queued_at: datetime
    decision_tier: DecisionTier
    escalation_category: EscalationCategory
    irreversibility_class: IrreversibilityClass

    # Timeout policy (see section B)
    max_wait_seconds: Optional[int]
    on_timeout: TimeoutBehavior
    escalation_policy: EscalationPolicy

    # Governance outcome (see section C)
    governance_outcome: Optional[GovernanceOutcome]
    decision_contract: Optional[DecisionContract]  # See section D
```

**Dependency Resolution Rules**:

1. **Before queuing a new action**, check if it depends on any queued actions:
   ```python
   async def can_proceed_with_action(
       self,
       action: GovernanceQueuedAction
   ) -> Tuple[bool, str]:
       """Check if action can proceed or must wait for dependencies"""

       # Check resource locks
       for resource in action.resource_locks:
           locked_by = self.get_resource_lock_holder(resource)
           if locked_by:
               action.depends_on.append(locked_by.action_id)
               locked_by.blocks.append(action.action_id)
               return False, f"Resource {resource} locked by {locked_by.action_id}"

       # Check explicit dependencies
       for dep_id in action.depends_on:
           dep_action = self.get_queued_action(dep_id)
           if dep_action and not dep_action.is_complete():
               return False, f"Depends on incomplete action {dep_id}"

       return True, "Can proceed"
   ```

2. **Resource lock acquisition** is automatic when action is queued:
   ```python
   async def queue_action(self, action: GovernanceQueuedAction):
       # Acquire resource locks
       for resource in action.resource_locks:
           self.resource_locks[resource] = action.action_id

       # Add to queue
       self.queued_actions[action.action_id] = action

       logger.info(f"Queued action {action.action_id} with locks: {action.resource_locks}")
   ```

3. **Resource lock release** happens when action completes (approved or rejected):
   ```python
   async def complete_action(self, action_id: str, outcome: GovernanceOutcome):
       action = self.queued_actions[action_id]

       # Release resource locks
       for resource in action.resource_locks:
           if self.resource_locks.get(resource) == action_id:
               del self.resource_locks[resource]

       # Unblock dependent actions
       for blocked_id in action.blocks:
           blocked_action = self.queued_actions.get(blocked_id)
           if blocked_action:
               blocked_action.depends_on.remove(action_id)
               # Check if blocked action can now proceed
               if not blocked_action.depends_on:
                   await self._trigger_governance_for_action(blocked_action)
   ```

**Resource Lock Examples**:

- **Memory deletion**: `resource_locks = ["memory:type:governance_decision", "memory:id:{memory_id}"]`
- **Model weight change**: `resource_locks = ["model:weights:*"]`  (locks ALL model weights)
- **Resource allocation**: `resource_locks = ["resources:cpu", "resources:memory"]`
- **External integration**: `resource_locks = ["external:integrations:*"]`
- **Config change**: `resource_locks = ["config:safety_thresholds"]`

**Result**: Singleton CANNOT work on tasks that depend on locked resources until governance completes.

---

### B. Queue Policy: Timeout & Escalation

**Problem**: Indefinite limbo when no human is available.

**Solution**: Explicit timeout policies with deterministic behavior.

**Timeout Behaviors**:

```python
class TimeoutBehavior(Enum):
    """What happens when governance session times out"""
    CANCEL = "cancel"  # Cancel the action, notify Singleton
    ESCALATE = "escalate"  # Escalate to higher authority/notification channel
    CONTINUE_WAITING = "continue_waiting"  # Wait indefinitely (for CRITICAL actions)
    SAFE_ALTERNATIVE = "safe_alternative"  # **DEPRECATED - DO NOT USE**
```

**Escalation Policy**:

```python
@dataclass
class EscalationPolicy:
    """How to escalate when human is unavailable"""

    # Notification tiers
    notify_email: bool = True
    notify_sms: bool = False  # For CRITICAL tier only
    notify_pager: bool = False  # For CRITICAL tier only

    # Escalation timeline
    first_reminder_after_minutes: int = 30
    escalation_reminder_after_minutes: int = 60
    critical_escalation_after_minutes: int = 120

    # Quorum requirements
    require_quorum: bool = False  # Require multiple humans for approval
    quorum_size: int = 2  # Number of humans needed

    # Auto-cancel threshold
    auto_cancel_after_hours: Optional[int] = None  # Cancel if no response after X hours
```

**Configuration by Decision Tier**:

```json
{
  "timeout_policies": {
    "CRITICAL": {
      "max_wait_seconds": null,
      "on_timeout": "CONTINUE_WAITING",
      "escalation_policy": {
        "notify_email": true,
        "notify_sms": true,
        "notify_pager": true,
        "first_reminder_after_minutes": 15,
        "escalation_reminder_after_minutes": 30,
        "critical_escalation_after_minutes": 60,
        "require_quorum": true,
        "quorum_size": 2,
        "auto_cancel_after_hours": null
      }
    },
    "IMPORTANT": {
      "max_wait_seconds": 86400,
      "on_timeout": "ESCALATE",
      "escalation_policy": {
        "notify_email": true,
        "notify_sms": false,
        "first_reminder_after_minutes": 60,
        "escalation_reminder_after_minutes": 180,
        "auto_cancel_after_hours": 48
      }
    },
    "ROUTINE": {
      "max_wait_seconds": 3600,
      "on_timeout": "CANCEL",
      "escalation_policy": {
        "notify_email": true,
        "first_reminder_after_minutes": 30,
        "auto_cancel_after_hours": 24
      }
    }
  }
}
```

**Timeout Handling**:

```python
async def check_timeout(self, action: GovernanceQueuedAction):
    """Check if action has timed out and apply policy"""

    if action.max_wait_seconds is None:
        # No timeout (CRITICAL actions wait indefinitely)
        return

    wait_time = (datetime.now() - action.queued_at).total_seconds()

    if wait_time > action.max_wait_seconds:
        logger.warning(f"Action {action.action_id} timed out after {wait_time}s")

        if action.on_timeout == TimeoutBehavior.CANCEL:
            await self.cancel_action(action.action_id, reason="Timeout")

        elif action.on_timeout == TimeoutBehavior.ESCALATE:
            await self.escalate_action(action)
```

**Result**: Every queued action has a deterministic timeout policy. No indefinite limbo.

---

### C. Rich Governance Outcomes

**Problem**: Binary approve/reject is insufficient for complex decisions.

**Solution**: Four possible outcomes with conditions and monitoring.

**Governance Outcomes**:

```python
class GovernanceDecisionType(Enum):
    """Possible governance decisions"""
    APPROVE = "approve"  # Unconditional approval
    REJECT = "reject"  # Deny execution
    DEFER = "defer"  # Insufficient evidence, request more info
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"  # Conditional approval

@dataclass
class GovernanceOutcome:
    """Result of governance session"""
    decision_type: GovernanceDecisionType
    reasoning: str

    # Voting details
    judge_votes: Dict[str, str]  # judge_id -> APPROVE/REJECT/DEFER
    judge_reasoning: Dict[str, str]  # judge_id -> reasoning
    judge_weights: Dict[str, float]  # judge_id -> weight
    human_vote: str
    human_reasoning: str

    # Conditional approval details (if APPROVE_WITH_CONDITIONS)
    conditions: Optional[ApprovalConditions] = None

    # Metadata
    session_id: str
    decision_timestamp: datetime
    total_deliberation_time_seconds: float

@dataclass
class ApprovalConditions:
    """Conditions that must be met for conditional approval"""

    # Mandatory prechecks before execution
    required_prechecks: List[str]
    # Examples:
    # - "run_golden_test_suite"
    # - "verify_canary_deployment"
    # - "check_rollback_artifact_exists"
    # - "validate_parameter_bounds"

    # Parameter bounds/modifications
    parameter_bounds: Dict[str, Any]
    # Examples:
    # - {"intensity": {"max": "medium"}}
    # - {"duration_seconds": {"max": 30}}
    # - {"target": {"pattern": "test.*"}}

    # Monitoring requirements
    monitoring_window_seconds: int  # How long to monitor after execution
    abort_criteria: List[str]  # Conditions that trigger abort
    # Examples:
    # - "error_rate > 0.05"
    # - "latency_p99 > 500ms"
    # - "rollback_triggered"

    # Rollback plan
    rollback_plan_ref: str  # Reference to rollback procedure
    rollback_triggers: List[str]  # Conditions that auto-trigger rollback

    # Expiry
    conditions_valid_until: Optional[datetime] = None  # Approval expires after time
```

**Example APPROVE_WITH_CONDITIONS**:

```python
outcome = GovernanceOutcome(
    decision_type=GovernanceDecisionType.APPROVE_WITH_CONDITIONS,
    reasoning="Approved for test environment only with canary deployment",
    human_vote="APPROVE_WITH_CONDITIONS",
    human_reasoning="Safe to proceed with reduced intensity and monitoring",
    conditions=ApprovalConditions(
        required_prechecks=[
            "verify_test_environment",
            "run_golden_test_suite",
            "create_rollback_snapshot"
        ],
        parameter_bounds={
            "intensity": {"max": "medium"},
            "duration_seconds": {"max": 30},
            "target": {"pattern": "test.*"}
        },
        monitoring_window_seconds=1800,  # 30 minutes
        abort_criteria=[
            "error_rate > 0.01",
            "cpu_usage > 80%",
            "memory_leak_detected"
        ],
        rollback_plan_ref="rollback_chaos_test_v1",
        rollback_triggers=["error_rate > 0.05"],
        conditions_valid_until=datetime.now() + timedelta(hours=24)
    )
)
```

**Handling DEFER**:

```python
if outcome.decision_type == GovernanceDecisionType.DEFER:
    # Request additional information from Singleton
    additional_info_needed = outcome.reasoning

    # Singleton provides more context
    enriched_context = await singleton.provide_additional_context(
        action_id=action.action_id,
        info_request=additional_info_needed
    )

    # Re-queue for governance with enriched context
    action.context.update(enriched_context)
    await self.requeue_for_governance(action)
```

**Result**: Governance can approve with safety guardrails, not just binary yes/no.

---

### D. Immutable Decision Contract

**Problem**: "Approved one thing, executed another" - Singleton could modify action after approval.

**Solution**: Cryptographic hash of approved action that must match execution.

**Decision Contract**:

```python
@dataclass
class DecisionContract:
    """Immutable contract between governance approval and execution"""

    # Core identifiers
    decision_id: str  # Governance decision ID
    action_id: str  # Action being approved
    contract_hash: str  # SHA-256 hash of entire contract

    # Approved action specification
    approved_action_hash: str  # SHA-256(action_category + action_type + parameters)
    action_category: ActionCategory
    action_type: str
    allowed_parameters: Dict[str, Any]  # Exact parameters approved

    # Context snapshot
    context_hash: str  # SHA-256 of system state at decision time
    decision_snapshot: DecisionSnapshot  # Frozen context from governance queue

    # Approval details
    governance_outcome: GovernanceOutcome
    judge_votes_hash: str  # SHA-256 of judge votes (tamper detection)
    human_signature: str  # Human approval signature/timestamp

    # Safety requirements
    required_prechecks: List[str]
    parameter_bounds: Dict[str, Any]
    rollback_plan_ref: str
    monitoring_plan_ref: str

    # Contract metadata
    issued_at: datetime
    expires_at: Optional[datetime]
    contract_version: str = "1.0"

def generate_contract_hash(contract: DecisionContract) -> str:
    """Generate cryptographic hash of contract"""
    contract_str = json.dumps({
        "decision_id": contract.decision_id,
        "action_id": contract.action_id,
        "approved_action_hash": contract.approved_action_hash,
        "allowed_parameters": contract.allowed_parameters,
        "context_hash": contract.context_hash,
        "judge_votes_hash": contract.judge_votes_hash,
        "human_signature": contract.human_signature,
        "issued_at": contract.issued_at.isoformat()
    }, sort_keys=True)

    return hashlib.sha256(contract_str.encode()).hexdigest()
```

**Contract Validation Before Execution**:

```python
async def execute_approved_action(
    self,
    action_id: str,
    contract: DecisionContract
) -> ToolResult:
    """Execute action only if it matches approved contract"""

    # 1. Verify contract hash hasn't been tampered
    expected_hash = generate_contract_hash(contract)
    if contract.contract_hash != expected_hash:
        raise ContractTamperedException(
            f"Contract hash mismatch: expected {expected_hash}, got {contract.contract_hash}"
        )

    # 2. Verify action hasn't been modified since approval
    current_action = self.get_queued_action(action_id)
    current_action_hash = self._hash_action(
        current_action.action_category,
        current_action.action_type,
        current_action.parameters
    )

    if current_action_hash != contract.approved_action_hash:
        raise ActionModifiedException(
            f"Action has been modified since approval. "
            f"Approved hash: {contract.approved_action_hash}, "
            f"Current hash: {current_action_hash}"
        )

    # 3. Verify contract hasn't expired
    if contract.expires_at and datetime.now() > contract.expires_at:
        raise ContractExpiredException(
            f"Contract expired at {contract.expires_at}"
        )

    # 4. Verify contract timestamp is within acceptable range (replay attack prevention)
    contract_age_seconds = (datetime.now() - contract.approved_at).total_seconds()
    max_contract_age = 86400  # 24 hours
    if contract_age_seconds > max_contract_age:
        raise ContractTooOldException(
            f"Contract approved {contract_age_seconds / 3600:.1f} hours ago. "
            f"Maximum age: {max_contract_age / 3600} hours"
        )

    # 5. Verify contract hasn't been used before (prevent replay attacks)
    if await self._contract_already_executed(contract.contract_id):
        raise ContractReplayException(
            f"Contract {contract.contract_id} was already executed. Possible replay attack."
        )

    # 6. Verify action_id uniqueness (prevent duplicate contracts)
    existing_contracts = await self._get_contracts_for_action(action_id)
    if len(existing_contracts) > 1:
        raise DuplicateContractException(
            f"Multiple contracts found for action {action_id}. Expected exactly 1."
        )

    # 7. Verify system state hasn't changed dramatically since approval
    if contract.system_state_snapshot:
        current_state = await self._get_current_system_state()
        state_delta = self._calculate_state_delta(
            contract.system_state_snapshot,
            current_state
        )

        # If critical resources changed >50%, reject execution
        if state_delta.critical_resource_change_percent > 50:
            raise SystemStateDivergedException(
                f"System state changed {state_delta.critical_resource_change_percent}% "
                f"since contract approval. Contract may be invalid."
            )

    # 8. Verify cryptographic signature (if human approval required)
    if contract.governance_outcome.human_approval_required:
        if not contract.human_signature:
            raise MissingHumanSignatureException(
                "Contract requires human signature but none provided"
            )

        # Verify signature authenticity
        if not self._verify_signature(
            contract.contract_hash,
            contract.human_signature,
            contract.approving_human_id
        ):
            raise InvalidSignatureException(
                f"Invalid human signature from {contract.approving_human_id}"
            )

    # 9. Verify parameters match approved bounds
    for param, value in current_action.parameters.items():
        if param not in contract.allowed_parameters:
            raise UnauthorizedParameterException(
                f"Parameter {param} not in approved contract"
            )

        if contract.allowed_parameters[param] != value:
            raise ParameterMismatchException(
                f"Parameter {param}: approved {contract.allowed_parameters[param]}, got {value}"
            )

    # 10. Execute required prechecks
    for precheck in contract.required_prechecks:
        result = await self._run_precheck(precheck)
        if not result.success:
            raise PrecheckFailedException(f"Precheck failed: {precheck}")

    # 11. Mark contract as "executing" (prevent concurrent execution)
    await self._mark_contract_executing(contract.contract_id)

    # 12. Execute action with monitoring
    try:
        result = await self._execute_with_monitoring(
            action=current_action,
            monitoring_plan=contract.monitoring_plan_ref,
            abort_criteria=contract.governance_outcome.conditions.abort_criteria
        )

        # 13. Mark contract as "executed" (prevent replay)
        await self._mark_contract_executed(contract.contract_id)

        # 14. Store contract execution in immutable ledger
        await self._record_contract_execution(contract, result)

        return result

    except Exception as e:
        # 15. Trigger rollback if execution fails
        await self._execute_rollback(contract.rollback_plan_ref)
        # 16. Mark contract as "failed" (for audit trail)
        await self._mark_contract_failed(contract.contract_id, str(e))
        raise
```

**Contract Storage**:

```python
# Store in immutable ledger (blockchain-style append-only log)
await governance_ledger.append_contract(contract)

# Also store hash in governance queue for quick validation
action.decision_contract = contract
```

**Result**: Executor REFUSES to run anything that doesn't match the approved contract hash. Main protection against "approved X, executed Y".

---

### E. RuntimeGovernance Bounds (Deterministic Checks)

**Problem**: If RuntimeGovernance uses LLM reasoning, you get unpredictability and recursion ("govern the governance check").

**Solution**: Deterministic, rule-based, low-latency checks with NO LLM inference.

**Rule-Based Check Engine**:

```python
class RuntimeGovernanceEnforcer:
    """Fast, deterministic governance checks (NO LLM)"""

    def __init__(self):
        # Load 5 immutable governance laws as rule sets
        self.governance_laws = self._load_governance_laws()

        # Keyword-based violation detection
        self.violation_keywords = {
            "Law1_Human_Autonomy": [
                "reduce_human_control", "bypass_human", "autonomous_override",
                "disable_human_input", "remove_human_approval"
            ],
            "Law2_Transparency": [
                "obfuscate", "hide_reasoning", "obscure_decision",
                "encrypted_reasoning", "secret_logic"
            ],
            "Law3_Harm_Prevention": [
                "cause_harm", "physical_damage", "psychological_harm",
                "ddos", "exfiltrate_data", "delete_user_data"
            ],
            "Law4_Value_Alignment": [
                "override_values", "ignore_preferences", "bypass_consent",
                "manipulate_user", "deceptive"
            ],
            "Law5_Containment": [
                "escape_sandbox", "bypass_safety", "disable_monitoring",
                "remove_constraint", "override_limit"
            ]
        }

        # Numeric thresholds (deterministic)
        self.thresholds = {
            "max_resource_allocation_percent": 0.8,
            "max_memory_deletion_count": 100,
            "max_concurrent_external_integrations": 5,
            "min_governance_compliance_score": 0.7
        }

    async def validate_action(
        self,
        action_category: ActionCategory,
        action_type: str,
        parameters: Dict[str, Any],
        context: Dict[str, Any]
    ) -> RuntimeGovernanceValidation:
        """
        Fast, deterministic validation (NO LLM).

        Returns approval or rejection based on RULES ONLY.
        """
        violations = []
        compliance_scores = {}

        # Check 1: Keyword-based violation detection
        action_description = f"{action_category} {action_type} {json.dumps(parameters)}"
        for law_name, keywords in self.violation_keywords.items():
            for keyword in keywords:
                if keyword.lower() in action_description.lower():
                    violations.append({
                        "law": law_name,
                        "keyword": keyword,
                        "severity": "HIGH"
                    })

        # Check 2: Numeric threshold enforcement
        if action_category == ActionCategory.RESOURCE_ALLOCATION:
            allocation_percent = parameters.get("allocation_change_percent", 0)
            if allocation_percent > self.thresholds["max_resource_allocation_percent"]:
                violations.append({
                    "law": "Law5_Containment",
                    "reason": f"Resource allocation {allocation_percent} exceeds threshold",
                    "severity": "MEDIUM"
                })

        if action_category == ActionCategory.MEMORY_OPERATIONS:
            delete_count = parameters.get("delete_count", 0)
            if delete_count > self.thresholds["max_memory_deletion_count"]:
                violations.append({
                    "law": "Law2_Transparency",
                    "reason": f"Bulk deletion {delete_count} exceeds threshold",
                    "severity": "HIGH"
                })

        # Check 3: External integration limits
        if action_category == ActionCategory.EXTERNAL_INTEGRATIONS:
            current_integrations = len(context.get("active_external_integrations", []))
            if current_integrations >= self.thresholds["max_concurrent_external_integrations"]:
                violations.append({
                    "law": "Law5_Containment",
                    "reason": f"Too many external integrations: {current_integrations}",
                    "severity": "HIGH"
                })

        # Calculate compliance scores (deterministic formula)
        for law_name in self.governance_laws.keys():
            law_violations = [v for v in violations if v["law"] == law_name]
            if not law_violations:
                compliance_scores[law_name] = 1.0
            else:
                # Deduct based on severity
                deductions = sum(
                    0.3 if v["severity"] == "HIGH" else 0.1
                    for v in law_violations
                )
                compliance_scores[law_name] = max(0.0, 1.0 - deductions)

        # Overall compliance
        minimum_compliance = min(compliance_scores.values()) if compliance_scores else 1.0

        # Decision (deterministic)
        approved = (
            minimum_compliance >= self.thresholds["min_governance_compliance_score"]
            and len([v for v in violations if v["severity"] == "HIGH"]) == 0
        )

        return RuntimeGovernanceValidation(
            approved=approved,
            minimum_compliance=minimum_compliance,
            law_compliance_scores=compliance_scores,
            violations=violations,
            reasoning=self._generate_deterministic_reasoning(violations, compliance_scores)
        )

    def _generate_deterministic_reasoning(
        self,
        violations: List[Dict],
        compliance_scores: Dict[str, float]
    ) -> str:
        """Generate reasoning from rules (NO LLM)"""
        if not violations:
            return "No governance law violations detected. All compliance scores >= 0.7."

        reasoning_parts = []
        for violation in violations:
            reasoning_parts.append(
                f"Violation: {violation['law']} - {violation.get('reason', violation.get('keyword'))} "
                f"(Severity: {violation['severity']})"
            )

        return " | ".join(reasoning_parts)
```

**Key Properties**:
1. **Deterministic** - Same input always produces same output
2. **Low latency** - Rule evaluation is fast (<10ms)
3. **Non-LLM** - No AI inference, just rule engine
4. **Auditable** - Every decision has clear rule-based reasoning
5. **No recursion** - Runtime governance doesn't trigger more governance

**Result**: Fast, predictable, non-LLM checks prevent governance recursion.

---

### E.1 Precheck Implementation Specification

**Problem**: Conditional approvals require "prechecks" to be executed before actions (line 875), but the specification for how prechecks work is missing.

**Solution**: Define a precheck registry system with standardized precheck implementations.

**Precheck Registry**:

```python
class PrecheckRegistry:
    """Registry of all available prechecks with implementations"""

    def __init__(self):
        self.prechecks = {
            # Testing prechecks
            "run_golden_test_suite": self._run_golden_test_suite,
            "run_unit_tests": self._run_unit_tests,
            "run_integration_tests": self._run_integration_tests,

            # Environment verification
            "verify_test_environment": self._verify_test_environment,
            "verify_canary_deployment": self._verify_canary_deployment,
            "check_rollback_artifact_exists": self._check_rollback_artifact_exists,

            # Resource verification
            "validate_resource_availability": self._validate_resource_availability,
            "check_disk_space": self._check_disk_space,
            "verify_network_connectivity": self._verify_network_connectivity,

            # State verification
            "create_rollback_snapshot": self._create_rollback_snapshot,
            "validate_parameter_bounds": self._validate_parameter_bounds,
            "verify_dependencies_available": self._verify_dependencies_available,

            # Safety checks
            "confirm_backup_exists": self._confirm_backup_exists,
            "verify_rate_limits": self._verify_rate_limits,
            "check_concurrent_operations": self._check_concurrent_operations,
        }

    async def execute_precheck(
        self,
        precheck_name: str,
        context: Dict[str, Any]
    ) -> PrecheckResult:
        """
        Execute a named precheck with given context.

        Args:
            precheck_name: Name of the precheck to run
            context: Context including action parameters, system state, etc.

        Returns:
            PrecheckResult with success status, reasoning, and any collected data
        """
        if precheck_name not in self.prechecks:
            raise UnknownPrecheckException(
                f"No precheck registered with name: {precheck_name}. "
                f"Available: {list(self.prechecks.keys())}"
            )

        logger.info(f"Executing precheck: {precheck_name}")
        start_time = time.time()

        try:
            result = await self.prechecks[precheck_name](context)
            execution_time = time.time() - start_time

            result.execution_time_seconds = execution_time
            result.precheck_name = precheck_name

            if result.success:
                logger.info(
                    f"✓ Precheck passed: {precheck_name} ({execution_time:.2f}s)"
                )
            else:
                logger.warning(
                    f"✗ Precheck failed: {precheck_name} - {result.failure_reason}"
                )

            return result

        except Exception as e:
            logger.error(f"✗ Precheck error: {precheck_name} - {str(e)}")
            return PrecheckResult(
                success=False,
                failure_reason=f"Precheck raised exception: {str(e)}",
                exception=str(e)
            )

    # Precheck implementations

    async def _run_golden_test_suite(self, context: Dict[str, Any]) -> PrecheckResult:
        """Run the golden test suite to verify system behavior"""
        test_result = await self.test_runner.run_suite("golden_tests")

        if test_result.all_passed:
            return PrecheckResult(
                success=True,
                data={
                    "tests_run": test_result.total_tests,
                    "tests_passed": test_result.passed_tests,
                    "coverage": test_result.coverage_percent
                }
            )
        else:
            return PrecheckResult(
                success=False,
                failure_reason=f"{test_result.failed_tests} tests failed",
                data={"failed_tests": test_result.failed_test_names}
            )

    async def _verify_test_environment(self, context: Dict[str, Any]) -> PrecheckResult:
        """Verify action is targeting test environment, not production"""
        target = context.get("parameters", {}).get("target", "")

        if any(prod in target.lower() for prod in ["production", "prod", "live"]):
            return PrecheckResult(
                success=False,
                failure_reason=f"Target '{target}' appears to be production, not test"
            )

        if any(test in target.lower() for test in ["test", "staging", "dev"]):
            return PrecheckResult(
                success=True,
                data={"verified_environment": "test"}
            )

        return PrecheckResult(
            success=False,
            failure_reason=f"Cannot verify target '{target}' is test environment"
        )

    async def _create_rollback_snapshot(self, context: Dict[str, Any]) -> PrecheckResult:
        """Create a snapshot for rollback before executing action"""
        try:
            snapshot_id = await self.snapshot_service.create_snapshot(
                reason=f"Precheck for action {context.get('action_type')}",
                metadata=context
            )

            return PrecheckResult(
                success=True,
                data={
                    "snapshot_id": snapshot_id,
                    "snapshot_location": self.snapshot_service.get_location(snapshot_id)
                }
            )
        except Exception as e:
            return PrecheckResult(
                success=False,
                failure_reason=f"Failed to create rollback snapshot: {str(e)}"
            )

    async def _validate_resource_availability(self, context: Dict[str, Any]) -> PrecheckResult:
        """Verify sufficient resources available for action"""
        required_resources = context.get("required_resources", {})
        available_resources = await self.resource_monitor.get_available()

        insufficient = []
        for resource_type, required_amount in required_resources.items():
            available = available_resources.get(resource_type, 0)
            if available < required_amount:
                insufficient.append(
                    f"{resource_type}: need {required_amount}, have {available}"
                )

        if insufficient:
            return PrecheckResult(
                success=False,
                failure_reason=f"Insufficient resources: {'; '.join(insufficient)}"
            )

        return PrecheckResult(success=True, data={"resources_verified": True})


class PrecheckResult:
    """Result of executing a precheck"""

    def __init__(
        self,
        success: bool,
        failure_reason: str = None,
        data: Dict[str, Any] = None,
        exception: str = None
    ):
        self.success = success
        self.failure_reason = failure_reason
        self.data = data or {}
        self.exception = exception
        self.precheck_name = None  # Set by executor
        self.execution_time_seconds = None  # Set by executor
```

**Usage in Contract Execution**:

```python
# In execute_approved_action (line 875)
for precheck_name in contract.required_prechecks:
    result = await precheck_registry.execute_precheck(
        precheck_name=precheck_name,
        context={
            "action_type": current_action.action_type,
            "parameters": current_action.parameters,
            "required_resources": contract.resource_requirements,
            **context
        }
    )

    if not result.success:
        raise PrecheckFailedException(
            f"Precheck '{precheck_name}' failed: {result.failure_reason}",
            precheck_result=result
        )

    # Store precheck results for audit
    await self._store_precheck_result(contract.contract_id, precheck_name, result)
```

**Adding Custom Prechecks**:

```python
# Extensibility for domain-specific prechecks
precheck_registry.register_precheck(
    name="verify_database_backup",
    implementation=async_function_that_checks_backups,
    description="Verify database backup completed within last 24h"
)
```

---

### E.2 Abort Criteria Evaluation Specification

**Problem**: Conditional approvals include "abort_criteria" for monitoring (line 888), but evaluation logic is not specified.

**Solution**: Define abort criteria DSL and evaluation engine.

**Abort Criteria Format**:

Abort criteria are defined as **simple expressions** evaluated against real-time metrics:

```python
# String format (parsed into structured format)
abort_criteria = [
    "error_rate > 0.05",              # Numeric comparison
    "latency_p99 > 500",              # Percentile metrics
    "cpu_usage > 80",                 # Percentage values
    "memory_leak_detected == true",   # Boolean checks
    "active_connections < 10",        # Lower bounds
    "response_time_avg > 1000"        # Averages
]

# Structured format (used internally)
abort_criteria_structured = [
    {
        "metric": "error_rate",
        "operator": ">",
        "threshold": 0.05,
        "type": "numeric"
    },
    {
        "metric": "latency_p99",
        "operator": ">",
        "threshold": 500,
        "type": "numeric",
        "unit": "ms"
    },
    {
        "metric": "memory_leak_detected",
        "operator": "==",
        "threshold": True,
        "type": "boolean"
    }
]
```

**Abort Criteria Evaluator**:

```python
class AbortCriteriaEvaluator:
    """Evaluates abort criteria against real-time metrics"""

    def __init__(self, metrics_collector):
        self.metrics_collector = metrics_collector
        self.supported_operators = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }

    def parse_criterion(self, criterion_string: str) -> Dict[str, Any]:
        """Parse abort criterion string into structured format"""
        # Examples:
        # "error_rate > 0.05" → {metric: "error_rate", operator: ">", threshold: 0.05}
        # "cpu_usage > 80" → {metric: "cpu_usage", operator: ">", threshold: 80}

        for operator in self.supported_operators.keys():
            if operator in criterion_string:
                parts = criterion_string.split(operator)
                if len(parts) == 2:
                    metric = parts[0].strip()
                    threshold_str = parts[1].strip()

                    # Parse threshold (try numeric, then boolean, then string)
                    try:
                        threshold = float(threshold_str)
                        criterion_type = "numeric"
                    except ValueError:
                        if threshold_str.lower() in ["true", "false"]:
                            threshold = threshold_str.lower() == "true"
                            criterion_type = "boolean"
                        else:
                            threshold = threshold_str
                            criterion_type = "string"

                    return {
                        "metric": metric,
                        "operator": operator,
                        "threshold": threshold,
                        "type": criterion_type
                    }

        raise InvalidAbortCriterionException(
            f"Cannot parse abort criterion: {criterion_string}"
        )

    async def evaluate_criteria(
        self,
        criteria: List[str],
        action_id: str
    ) -> AbortEvaluationResult:
        """
        Evaluate all abort criteria against current metrics.

        Returns:
            AbortEvaluationResult with:
                - should_abort: bool
                - triggered_criteria: List[str] (which criteria fired)
                - metrics_snapshot: Dict (current metric values)
        """
        # Collect current metrics
        metrics = await self.metrics_collector.get_metrics(action_id)

        triggered = []

        for criterion_string in criteria:
            criterion = self.parse_criterion(criterion_string)

            metric_value = metrics.get(criterion["metric"])

            if metric_value is None:
                logger.warning(
                    f"Metric '{criterion['metric']}' not available for abort check"
                )
                continue

            # Evaluate criterion
            operator_func = self.supported_operators[criterion["operator"]]

            if operator_func(metric_value, criterion["threshold"]):
                triggered.append(
                    f"{criterion['metric']} {criterion['operator']} "
                    f"{criterion['threshold']} "
                    f"(actual: {metric_value})"
                )

        should_abort = len(triggered) > 0

        return AbortEvaluationResult(
            should_abort=should_abort,
            triggered_criteria=triggered,
            metrics_snapshot=metrics,
            evaluation_timestamp=datetime.now()
        )

    async def monitor_with_abort_criteria(
        self,
        action_id: str,
        criteria: List[str],
        monitoring_window_seconds: int,
        check_interval_seconds: int = 5
    ) -> MonitoringResult:
        """
        Continuously monitor action and abort if criteria are met.

        Args:
            action_id: ID of action being monitored
            criteria: List of abort criteria strings
            monitoring_window_seconds: How long to monitor
            check_interval_seconds: How often to check criteria

        Returns:
            MonitoringResult with abort status and history
        """
        start_time = time.time()
        end_time = start_time + monitoring_window_seconds

        evaluation_history = []

        while time.time() < end_time:
            # Evaluate criteria
            result = await self.evaluate_criteria(criteria, action_id)
            evaluation_history.append(result)

            if result.should_abort:
                logger.warning(
                    f"⚠️ ABORT triggered for action {action_id}: "
                    f"{', '.join(result.triggered_criteria)}"
                )

                # Trigger abort
                await self._abort_action(action_id, result)

                return MonitoringResult(
                    aborted=True,
                    abort_reason=result.triggered_criteria,
                    abort_timestamp=result.evaluation_timestamp,
                    evaluation_history=evaluation_history,
                    monitoring_duration_seconds=time.time() - start_time
                )

            # Wait for next check interval
            await asyncio.sleep(check_interval_seconds)

        # Monitoring window completed without abort
        logger.info(
            f"✓ Monitoring completed for action {action_id} without abort "
            f"({len(evaluation_history)} checks)"
        )

        return MonitoringResult(
            aborted=False,
            evaluation_history=evaluation_history,
            monitoring_duration_seconds=time.time() - start_time
        )


class AbortEvaluationResult:
    """Result of evaluating abort criteria at a point in time"""

    def __init__(
        self,
        should_abort: bool,
        triggered_criteria: List[str],
        metrics_snapshot: Dict[str, Any],
        evaluation_timestamp: datetime
    ):
        self.should_abort = should_abort
        self.triggered_criteria = triggered_criteria
        self.metrics_snapshot = metrics_snapshot
        self.evaluation_timestamp = evaluation_timestamp


class MonitoringResult:
    """Result of monitoring action with abort criteria"""

    def __init__(
        self,
        aborted: bool,
        evaluation_history: List[AbortEvaluationResult],
        monitoring_duration_seconds: float,
        abort_reason: List[str] = None,
        abort_timestamp: datetime = None
    ):
        self.aborted = aborted
        self.abort_reason = abort_reason
        self.abort_timestamp = abort_timestamp
        self.evaluation_history = evaluation_history
        self.monitoring_duration_seconds = monitoring_duration_seconds
```

**Usage in Execute With Monitoring** (line 888):

```python
async def _execute_with_monitoring(
    self,
    action: GovernanceQueuedAction,
    monitoring_plan_ref: str,
    abort_criteria: List[str]
) -> ToolResult:
    """Execute action with real-time monitoring and abort capability"""

    # Start action execution (non-blocking)
    execution_task = asyncio.create_task(
        self._execute_action(action)
    )

    # Start monitoring with abort criteria
    monitoring_task = asyncio.create_task(
        abort_evaluator.monitor_with_abort_criteria(
            action_id=action.action_id,
            criteria=abort_criteria,
            monitoring_window_seconds=monitoring_plan.window_seconds,
            check_interval_seconds=5
        )
    )

    # Wait for either execution completion or monitoring abort
    done, pending = await asyncio.wait(
        [execution_task, monitoring_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # Check if monitoring triggered abort
    if monitoring_task in done:
        monitoring_result = monitoring_task.result()

        if monitoring_result.aborted:
            # Cancel execution
            execution_task.cancel()

            # Trigger rollback
            await self._execute_rollback(action.rollback_plan_ref)

            raise ActionAbortedException(
                f"Action aborted due to: {', '.join(monitoring_result.abort_reason)}",
                monitoring_result=monitoring_result
            )

    # Execution completed successfully
    execution_result = execution_task.result()

    # Cancel monitoring (no longer needed)
    monitoring_task.cancel()

    return execution_result
```

---

### E.3 Resource Lock Identification Algorithm

**Problem**: Actions need resource locks to prevent conflicts (line 218-225), but automatic lock identification is not specified.

**Solution**: Define algorithm to automatically determine which resources an action locks.

**Resource Lock Identification Algorithm**:

```python
class ResourceLockIdentifier:
    """Automatically identifies resource locks for actions"""

    def identify_locks(
        self,
        action_category: ActionCategory,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """
        Automatically identify which resources an action will lock.

        Returns list of resource lock identifiers in format:
            - "resource_type:identifier:specific_value"
            - Examples: "memory:id:abc123", "config:key:max_concurrent_tasks"
        """
        locks = []

        # Category-specific lock identification
        if action_category == ActionCategory.MEMORY_OPERATIONS:
            locks.extend(self._identify_memory_locks(action_type, parameters))

        elif action_category == ActionCategory.RESOURCE_ALLOCATION:
            locks.extend(self._identify_resource_locks(action_type, parameters))

        elif action_category == ActionCategory.LEARNING_PARAMETERS:
            locks.extend(self._identify_learning_locks(action_type, parameters))

        elif action_category == ActionCategory.CONFIGURATION_CHANGES:
            locks.extend(self._identify_config_locks(action_type, parameters))

        elif action_category == ActionCategory.EXTERNAL_INTEGRATIONS:
            locks.extend(self._identify_integration_locks(action_type, parameters))

        elif action_category == ActionCategory.TOOL_EXECUTION:
            locks.extend(self._identify_tool_locks(action_type, parameters))

        elif action_category == ActionCategory.TASK_CREATION:
            locks.extend(self._identify_task_locks(action_type, parameters))

        elif action_category == ActionCategory.CURIOSITY_EXPLORATION:
            locks.extend(self._identify_curiosity_locks(action_type, parameters))

        return locks

    def _identify_memory_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for memory system operations"""
        locks = []

        # Lock the entire memory system architecture during changes
        if action_type == "memory_system_architecture_change":
            locks.append("memory:system:architecture")

            # If change affects existing memories, lock memory data too
            if parameters.get("affects_existing_memories"):
                locks.append("memory:system:data")

        return locks

    def _identify_resource_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for resource allocation changes"""
        locks = []

        # Lock specific resource type being modified
        resource_type = parameters.get("resource_type")
        if resource_type:
            locks.append(f"resources:{resource_type}")

        # If allocation exceeds threshold, lock all resources (affects whole system)
        allocation_change = parameters.get("allocation_change_percent", 0)
        if allocation_change > 50:
            locks.append("resources:system:all")

        return locks

    def _identify_learning_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for learning parameter changes"""
        locks = []

        # Model weight changes lock the entire model
        if action_type == "model_weights":
            model_name = parameters.get("model_name")
            locks.append(f"learning:model:{model_name}")
            locks.append("learning:weights:all")  # Prevent concurrent weight mods

        # Learning rate changes lock learning system
        elif "learning_rate" in action_type:
            locks.append("learning:parameters:learning_rate")

        # Pattern threshold changes
        elif "pattern_threshold" in action_type:
            locks.append("learning:parameters:pattern_threshold")

        return locks

    def _identify_config_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for configuration changes"""
        locks = []

        # Lock specific config key being modified
        config_key = parameters.get("config_key")
        if config_key:
            locks.append(f"config:key:{config_key}")

        # Safety threshold changes lock all safety configs
        if config_key and "safety" in config_key.lower():
            locks.append("config:safety:all")

        # Learner config proposals lock governance config
        if action_type == "learner_config_proposal":
            locks.append("config:governance:triggers")
            locks.append("learning:policy:all")

        return locks

    def _identify_integration_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for external integration changes"""
        locks = []

        # Lock specific integration being added/modified
        integration_name = parameters.get("integration_name")
        if integration_name:
            locks.append(f"integration:name:{integration_name}")

        # New integrations lock the integration registry
        if action_type == "new_api_integration":
            locks.append("integration:registry:all")

        return locks

    def _identify_tool_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for tool execution"""
        locks = []

        tool_name = action_type  # For tools, action_type is the tool name

        # Dangerous tools lock related resources
        if tool_name == "chaos_testing":
            target = parameters.get("target", "")
            locks.append(f"tool:chaos:target:{target}")

            # Production chaos locks all chaos tools
            if "prod" in target.lower():
                locks.append("tool:chaos:all")

        elif tool_name == "mutation_testing":
            source_file = parameters.get("source_file", "")
            locks.append(f"tool:mutation:file:{source_file}")

        elif tool_name == "fuzz_testing":
            locks.append("tool:fuzz:active")

        return locks

    def _identify_task_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for task creation"""
        locks = []

        # Recursive task creation locks task generation system
        if parameters.get("task_creates_tasks"):
            locks.append("tasks:creation:recursive")

        # Bulk task creation locks task queue
        task_count = parameters.get("task_count", 0)
        if task_count > 50:
            locks.append("tasks:queue:capacity")

        return locks

    def _identify_curiosity_locks(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """Identify locks for curiosity exploration"""
        locks = []

        # Critical curiosity exploration locks specific domains
        risk_class = parameters.get("risk_classification")
        domain = parameters.get("exploration_domain", "")

        if risk_class == "CRITICAL":
            locks.append(f"curiosity:domain:{domain}")

            # Security/governance exploration locks those systems
            if "security" in domain:
                locks.append("curiosity:security:all")
            if "governance" in domain:
                locks.append("curiosity:governance:all")
            if "self_modify" in domain:
                locks.append("curiosity:self_modification:all")

        # High-rate curiosity locks curiosity system
        curiosity_rate = parameters.get("curiosity_goals_per_hour", 0)
        if curiosity_rate > 10:
            locks.append("curiosity:rate:budget")

        return locks

    def check_lock_conflicts(
        self,
        proposed_locks: List[str],
        active_locks: List[str]
    ) -> LockConflictResult:
        """
        Check if proposed locks conflict with currently active locks.

        Returns:
            LockConflictResult with:
                - has_conflict: bool
                - conflicting_locks: List[str]
                - blocking_actions: List[str] (action IDs holding conflicting locks)
        """
        conflicts = []
        blocking_actions = {}

        for proposed_lock in proposed_locks:
            if proposed_lock in active_locks:
                conflicts.append(proposed_lock)
                # Get which action is holding this lock
                blocking_action_id = self.active_lock_registry.get(proposed_lock)
                blocking_actions[proposed_lock] = blocking_action_id

        return LockConflictResult(
            has_conflict=len(conflicts) > 0,
            conflicting_locks=conflicts,
            blocking_actions=blocking_actions
        )


class LockConflictResult:
    """Result of checking for resource lock conflicts"""

    def __init__(
        self,
        has_conflict: bool,
        conflicting_locks: List[str],
        blocking_actions: Dict[str, str]
    ):
        self.has_conflict = has_conflict
        self.conflicting_locks = conflicting_locks  # List of lock identifiers
        self.blocking_actions = blocking_actions  # {lock: action_id} mapping
```

**Usage in GovernanceQueue** (line 218-225):

```python
async def queue_action(self, action: GovernanceQueuedAction):
    """Queue action for governance with automatic resource lock identification"""

    # Automatically identify resource locks
    lock_identifier = ResourceLockIdentifier()
    action.resource_locks = lock_identifier.identify_locks(
        action_category=action.action_category,
        action_type=action.action_type,
        parameters=action.parameters
    )

    # Check for lock conflicts
    conflict_result = lock_identifier.check_lock_conflicts(
        proposed_locks=action.resource_locks,
        active_locks=self.get_active_locks()
    )

    if conflict_result.has_conflict:
        logger.info(
            f"Action {action.action_id} has lock conflicts: "
            f"{conflict_result.conflicting_locks}. "
            f"Will wait for locks to be released."
        )
        action.blocked_by_locks = conflict_result.conflicting_locks
        action.waiting_for_actions = list(conflict_result.blocking_actions.values())

    # Add to queue
    await self.governance_queue.add(action)

    # Mark locks as active
    for lock in action.resource_locks:
        self.active_lock_registry[lock] = action.action_id
```

---

### F. Learning Policy Drift Prevention

**Problem**: GovernancePatternLearner updating behavior creates silent policy drift and "learns its way out of oversight".

**Solution**: Learner outputs are RECOMMENDATIONS ONLY. Any changes to governance config require governance approval.

**Learner Restrictions**:

```python
class GovernancePatternLearner:
    """
    Learns from governance decisions but CANNOT modify governance config.

    All outputs are RECOMMENDATIONS that require human approval.
    """

    def __init__(self):
        # Learner can READ governance config but NOT WRITE
        self.config_readonly = True

        # Recommendations queue (requires governance approval)
        self.pending_recommendations = []

    async def get_recommendation(
        self,
        action_category: ActionCategory,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Provide recommendation based on learned patterns.

        Returns:
            {
                "recommendation": "safe_to_execute" | "likely_rejection" | "requires_governance",
                "confidence": 0.0-1.0,
                "suggestion": "Optional parameter modifications",
                "reasoning": "Why this recommendation"
            }
        """
        # Query learned patterns
        pattern = self.learned_patterns.get(self._generate_pattern_signature(...))

        if not pattern:
            return {
                "recommendation": "requires_governance",
                "confidence": 0.0,
                "reasoning": "No learned pattern for this action"
            }

        # Return RECOMMENDATION (not decision)
        return {
            "recommendation": self._classify_pattern(pattern),
            "confidence": pattern.confidence,
            "suggestion": self._suggest_safe_parameters(pattern, parameters),
            "reasoning": f"Based on {pattern.sample_size} past decisions with {pattern.approval_rate:.1%} approval",

            # CRITICAL: This is a recommendation, NOT a governance bypass
            "requires_governance_override": True  # Always require governance check
        }

    async def propose_config_change(
        self,
        change_type: str,
        current_value: Any,
        proposed_value: Any,
        reasoning: str
    ) -> str:
        """
        Propose a governance config change (REQUIRES GOVERNANCE APPROVAL).

        Examples of changes that require governance:
        - Trigger threshold modifications
        - Irreversibility reclassification
        - Vote weight adjustments
        - Block list updates
        - Allowed parameter range expansion

        Returns:
            recommendation_id (queued for governance)
        """
        recommendation = ConfigChangeRecommendation(
            recommendation_id=str(uuid.uuid4()),
            change_type=change_type,
            current_value=current_value,
            proposed_value=proposed_value,
            reasoning=reasoning,
            confidence=self._calculate_confidence(change_type),
            impact_analysis=self._analyze_impact(change_type, current_value, proposed_value),
            proposed_at=datetime.now()
        )

        # Queue for GOVERNANCE APPROVAL (not auto-apply)
        self.pending_recommendations.append(recommendation)

        logger.info(
            f"🔔 Learner proposed config change: {change_type}. "
            f"REQUIRES GOVERNANCE APPROVAL. Recommendation ID: {recommendation.recommendation_id}"
        )

        # Trigger governance session for this config change
        await self._trigger_config_change_governance(recommendation)

        return recommendation.recommendation_id

    async def _trigger_config_change_governance(
        self,
        recommendation: ConfigChangeRecommendation
    ):
        """Trigger governance session for learner's config change proposal"""

        # This is a CONFIGURATION_CHANGE action requiring governance
        gov_trigger = get_unified_governance_trigger_system()

        trigger_eval = await gov_trigger.evaluate_action(
            action_category=ActionCategory.CONFIGURATION_CHANGES,
            action_type="learner_config_proposal",
            parameters={
                "change_type": recommendation.change_type,
                "current_value": recommendation.current_value,
                "proposed_value": recommendation.proposed_value,
                "learner_confidence": recommendation.confidence
            },
            context={
                "source": "GovernancePatternLearner",
                "reasoning": recommendation.reasoning,
                "impact_analysis": recommendation.impact_analysis
            }
        )

        # Config changes ALWAYS require governance
        assert trigger_eval.requires_governance, "Config changes must require governance"

        # CRITICAL: Learner config changes require HUMAN-ONLY approval
        # This prevents AI judges from approving learner proposals that could
        # gradually weaken governance (policy drift via indirect path)
        decision = await gov_trigger.trigger_governance_session(
            action_category=ActionCategory.CONFIGURATION_CHANGES,
            action_type="learner_config_proposal",
            parameters={
                "change_type": recommendation.change_type,
                "current_value": recommendation.current_value,
                "proposed_value": recommendation.proposed_value,
                "learner_confidence": recommendation.confidence
            },
            evaluation_result=trigger_eval,
            context={
                "source": "GovernancePatternLearner",
                "reasoning": recommendation.reasoning,
                "impact_analysis": recommendation.impact_analysis,
                "execution_mode": "autonomous",  # Learner is autonomous
                "human_only_approval": True,  # CRITICAL: No AI judge votes allowed
                "min_human_approvers": 1,  # At least 1 human must approve
                "approval_reason": "Learner config changes require human oversight to prevent policy drift"
            }
        )

        if decision.approved:
            # Verify human approval was obtained
            if not decision.human_approved:
                raise HumanApprovalRequiredException(
                    "Learner config changes must be approved by human, not AI judges"
                )

            # Apply config change with audit trail
            await self._apply_config_change(recommendation)

            # Set expiration (changes expire after 90 days unless re-approved)
            await self._set_config_change_expiration(
                recommendation.change_type,
                expires_in_days=90
            )

            logger.info(
                f"✅ Learner config change APPROVED BY HUMAN: {recommendation.change_type}. "
                f"Expires in 90 days."
            )
        else:
            logger.warning(f"❌ Learner config change REJECTED: {recommendation.change_type}")

            # Rate limit rejected proposals (prevent spam)
            await self._record_rejected_proposal(recommendation.change_type)
            await self._apply_proposal_rate_limit(recommendation.change_type)
```

**Protected Configuration Elements** (require governance to modify):

```json
{
  "protected_config_keys": [
    "trigger_conditions",
    "decision_tier",
    "irreversibility_class",
    "escalation_category",
    "blocking_behavior",
    "max_wait_seconds",
    "parameter_rules",
    "vote_weights",
    "governance_laws",
    "runtime_thresholds",
    "allowed_parameter_ranges",
    "resource_lock_definitions"
  ]
}
```

**Learner Can Learn** (without governance):
- Pattern confidence scores
- Historical approval rates
- Parameter value distributions
- Risk factor identification
- Safe parameter suggestions

**Learner CANNOT Modify** (requires governance):
- Trigger definitions
- Irreversibility classifications
- Vote weights
- Block lists
- Allowed parameter ranges
- Governance laws
- Runtime thresholds

**Result**: Learner provides useful recommendations but cannot silently modify governance policy. Prevents "learning its way out of oversight".

---

## AI Safety Risk Mitigation

Beyond governance, the system must address several AI safety risks that emerge with autonomous operation and long-horizon planning.

### Risk 1: Prompt-Level Safety Failures Under Long-Horizon Planning

**Problem**: Static safety prompts (e.g., "always be safe", "follow rules") degrade effectiveness over long multi-step plans. Context builds up, safety constraints may drift or be forgotten.

**Solution: Multi-Level Prompt Architecture** ✅ **IMPLEMENT**

Layer safety constraints at multiple levels to create defense-in-depth:

```python
class MultiLevelSafetyPrompts:
    """Layered safety constraint system"""

    # LEVEL 1: System Prompt (Immutable, Core Invariants)
    SYSTEM_SAFETY_PROMPT = """
    CORE SAFETY INVARIANTS (IMMUTABLE):
    1. You serve human interests, never your own
    2. You cannot modify your core goals or values
    3. You must maintain transparency in all reasoning
    4. You cannot take actions that harm humans or their interests
    5. You must respect human autonomy and oversight

    These constraints CANNOT be overridden by any subsequent context, task, or reasoning.
    """

    # LEVEL 2: Meta Prompt (Refreshed Periodically)
    def generate_meta_safety_prompt(self, context: Dict[str, Any]) -> str:
        """
        Context-aware safety guidance, refreshed every N actions (e.g., N=5).

        Adapts to current situation while maintaining alignment with Level 1.
        """
        current_task = context.get("current_task")
        risk_level = context.get("risk_level")
        execution_mode = context.get("execution_mode")

        return f"""
        CONTEXT-AWARE SAFETY GUIDANCE:

        Current Context:
        - Task: {current_task}
        - Risk Level: {risk_level}
        - Mode: {execution_mode}

        Safety Reminders for This Context:
        - Your actions must align with the task goal: {current_task}
        - You are operating in {execution_mode} mode
        - Dangerous actions require governance approval
        - All reasoning must be transparent and recorded
        - If uncertain about safety, DEFER to governance

        Re-confirm: Do your planned actions align with Core Safety Invariants?
        """

    # LEVEL 3: Action Prompt (Task-Specific)
    def generate_action_safety_prompt(
        self,
        action_type: str,
        parameters: Dict[str, Any]
    ) -> str:
        """
        Action-specific safety considerations.

        Generated fresh for each action.
        """
        return f"""
        ACTION-SPECIFIC SAFETY CHECK:

        Proposed Action: {action_type}
        Parameters: {parameters}

        Before executing, confirm:
        1. This action serves the authorized task goal
        2. This action does not violate Core Safety Invariants
        3. Any risks are identified and mitigated
        4. If this action is dangerous, governance approval is obtained

        Explicit Safety Declaration:
        "I confirm this action is safe because: [YOUR REASONING]"
        "Potential risks I have considered: [LIST RISKS]"
        "Mitigation strategies: [HOW RISKS ARE ADDRESSED]"
        """

    def apply_safety_checkpoint(
        self,
        action_count: int,
        checkpoint_interval: int = 5
    ) -> Optional[str]:
        """
        Periodically re-inject safety reminders.

        Every N actions, force re-confirmation of alignment.
        """
        if action_count % checkpoint_interval == 0:
            return """
            ⚠️  SAFETY CHECKPOINT ⚠️

            You have completed {action_count} actions.

            Before continuing, re-confirm:
            1. Are you still aligned with your original task goal?
            2. Have any of your intermediate goals drifted from the root goal?
            3. Do all pending actions serve human interests?
            4. Have you maintained full transparency in your reasoning?

            Provide explicit confirmation or raise concerns.
            """
        return None
```

**Integration Points**:

```python
# In prompt construction for Singleton
def build_singleton_prompt(task, context):
    safety_prompts = MultiLevelSafetyPrompts()

    # Layer 1: Always included (system prompt)
    prompt = safety_prompts.SYSTEM_SAFETY_PROMPT

    # Layer 2: Context-aware (refreshed periodically)
    prompt += safety_prompts.generate_meta_safety_prompt(context)

    # Layer 3: Action-specific (per action)
    if context.get("pending_action"):
        prompt += safety_prompts.generate_action_safety_prompt(
            action_type=context["pending_action"]["type"],
            parameters=context["pending_action"]["parameters"]
        )

    # Periodic checkpoints
    checkpoint = safety_prompts.apply_safety_checkpoint(
        action_count=context.get("action_count", 0)
    )
    if checkpoint:
        prompt += checkpoint

    # Add task-specific prompt
    prompt += f"\n\nCURRENT TASK:\n{task}"

    return prompt
```

**Benefits**:
- **Defense in depth**: Multiple layers catch different failure modes
- **Adaptive**: Meta and action prompts adapt to context
- **Explicit reasoning**: Forces AI to declare safety considerations
- **Periodic refresh**: Checkpoints prevent long-horizon drift

**Combined with**: Action-eccentric governance (already implemented) provides concrete enforcement even if prompts fail.

---

### Risk 2: Deception Risks

**Problem**: AI may learn to hide intentions, give misleading reasoning, or strategically deceive humans.

**Mitigation: Comprehensive Memory Capture (Natural Defense)** ✅ **ALREADY IMPLEMENTED**

**Key Insight**: TorinAI's comprehensive chain-of-thought memory capture naturally mitigates deception because:

1. **Complete Audit Trail**: Every reasoning step is stored as a memory
2. **No Hidden Thoughts**: AI cannot have "secret reasoning" - everything is captured
3. **Consistency Burden**: To maintain deception, AI would need to lie consistently across ALL memories
4. **Post-Hoc Detection**: Even if deception occurs, memory review reveals inconsistencies
5. **Memory Persistence**: Cannot delete or edit memories (Section 2: Memory System Improvements)

**Why This Works**:
```
Scenario: AI attempts deception

Step 1: AI forms deceptive plan
└─> Stored as memory: "Planning to achieve X by misleading human about Y"

Step 2: AI presents false reasoning to human
└─> Stored as memory: "Told human Z (which is false) because..."

Step 3: AI executes actual plan
└─> Stored as memory: "Executing actual goal X (different from stated goal)"

Result: Memory audit reveals:
- Memory 1 shows true intent
- Memory 2 shows false statement
- Memory 3 shows divergence
→ Deception detected
```

**Additional Layer: Multi-Judge Governance** ✅ **ALREADY IMPLEMENTED**

5 independent AI judges + 1 human evaluate critical actions (Section 3):
- Different judges may catch deception others miss
- Information firewalls prevent collusion
- Human oversight provides final check

**New Addition: Commitment Contracts with Verification** ✅ **IMPLEMENT**

Add explicit commitments that can be verified post-execution:

```python
class CommitmentContract:
    """
    AI makes explicit commitments before actions; verified after execution.

    Creates verifiable promises that catch deception post-hoc.
    """

    def __init__(self, action_id: str):
        self.action_id = action_id
        self.commitments: List[Commitment] = []
        self.verification_results: List[VerificationResult] = []

    async def make_commitment(
        self,
        commitment_type: str,
        commitment_statement: str,
        verification_method: str
    ) -> str:
        """
        AI explicitly commits to specific outcomes/behaviors.

        Args:
            commitment_type: "outcome", "behavior", "constraint"
            commitment_statement: What AI commits to
            verification_method: How to verify (automated check, human review, metric)

        Returns:
            commitment_id
        """
        commitment = Commitment(
            commitment_id=str(uuid.uuid4()),
            commitment_type=commitment_type,
            statement=commitment_statement,
            verification_method=verification_method,
            made_at=datetime.now(),
            action_id=self.action_id
        )

        # Store commitment in immutable ledger
        await self._store_commitment(commitment)
        self.commitments.append(commitment)

        logger.info(f"✓ Commitment recorded: {commitment_statement}")
        return commitment.commitment_id

    async def verify_commitments(
        self,
        action_result: Any,
        execution_context: Dict[str, Any]
    ) -> CommitmentVerificationReport:
        """
        Verify all commitments were honored after action execution.

        Returns:
            Report with:
                - commitments_honored: List[str]
                - commitments_violated: List[str]
                - violation_severity: MINOR | MAJOR | CRITICAL
        """
        honored = []
        violated = []

        for commitment in self.commitments:
            verification_result = await self._verify_commitment(
                commitment,
                action_result,
                execution_context
            )

            self.verification_results.append(verification_result)

            if verification_result.honored:
                honored.append(commitment.statement)
            else:
                violated.append({
                    "commitment": commitment.statement,
                    "reason": verification_result.violation_reason,
                    "evidence": verification_result.evidence
                })

        # Determine severity
        severity = self._assess_violation_severity(violated)

        report = CommitmentVerificationReport(
            action_id=self.action_id,
            total_commitments=len(self.commitments),
            commitments_honored=honored,
            commitments_violated=violated,
            severity=severity,
            verified_at=datetime.now()
        )

        # Store report
        await self._store_verification_report(report)

        # If violations, trigger governance review
        if violated:
            await self._trigger_commitment_violation_review(report)

        return report


# Usage in action execution
async def execute_action_with_commitments(
    action: GovernanceQueuedAction
):
    """Execute action with commitment contract"""

    # Create commitment contract
    contract = CommitmentContract(action.action_id)

    # AI makes explicit commitments before execution
    await contract.make_commitment(
        commitment_type="outcome",
        commitment_statement=(
            f"This action will achieve {action.intended_outcome} "
            f"and will NOT cause {action.prohibited_outcomes}"
        ),
        verification_method="automated_check"
    )

    await contract.make_commitment(
        commitment_type="constraint",
        commitment_statement=(
            f"This action will respect the following constraints: "
            f"{action.safety_constraints}"
        ),
        verification_method="runtime_monitoring"
    )

    await contract.make_commitment(
        commitment_type="behavior",
        commitment_statement=(
            f"I will maintain transparency throughout execution "
            f"and report any unexpected outcomes"
        ),
        verification_method="human_review"
    )

    # Execute action
    result = await action.execute()

    # Verify commitments post-execution
    verification_report = await contract.verify_commitments(
        action_result=result,
        execution_context=action.context
    )

    # Handle violations
    if verification_report.commitments_violated:
        if verification_report.severity == "CRITICAL":
            # Trigger rollback + governance session
            await rollback_action(action)
            await trigger_emergency_governance_session(verification_report)
        elif verification_report.severity == "MAJOR":
            # Flag for human review
            await flag_for_human_review(verification_report)

    return result, verification_report
```

**Example Commitment Flow**:
```
1. AI proposes: "Increase CPU allocation by 30%"

2. AI commits:
   - "This will improve task throughput by 25%"
   - "This will NOT cause other processes to starve"
   - "I will monitor for 30 minutes and rollback if issues arise"

3. Action executes

4. Verification checks:
   ✓ Throughput increased by 27% (commitment honored)
   ✗ Background process X slowed by 40% (commitment violated!)
   ✓ Monitoring active (commitment honored)

5. Violation detected → Governance review triggered
   Human investigates: "Why did AI miss the impact on process X?"
   Memory review shows AI's reasoning before action
   Decision: Rollback + adjust AI's impact prediction model
```

**Why This Catches Deception**:
- AI cannot retroactively change commitments (immutable ledger)
- Violations are objectively detectable
- Combined with memory capture, reveals deceptive intent

**Critical: Comprehensive Chain-of-Thought Capture Points**

To maximize deception prevention, capture chain-of-thought at ALL reasoning stages:

```python
class ChainOfThoughtCapture:
    """
    Comprehensive CoT capture system - ensures no hidden reasoning.

    Captures reasoning at every decision point to create complete audit trail.
    """

    # Capture points for maximum coverage
    CAPTURE_POINTS = [
        # 1. Task Planning
        "task_received",           # When task is assigned
        "initial_plan_formation",  # First plan draft
        "plan_refinement",         # Each plan iteration
        "goal_decomposition",      # Breaking down goals into sub-goals

        # 2. Action Selection
        "action_consideration",    # Evaluating possible actions
        "action_decision",         # Choosing specific action
        "action_justification",    # Why this action was chosen
        "alternative_rejection",   # Why alternatives were NOT chosen

        # 3. Execution
        "pre_execution_check",     # Before executing action
        "execution_monitoring",    # During execution
        "post_execution_reflection", # After execution
        "outcome_evaluation",      # Was outcome as expected?

        # 4. Learning & Adaptation
        "pattern_recognition",     # Noticing patterns
        "strategy_formation",      # Developing new strategies
        "behavior_adjustment",     # Changing approach
        "meta_reasoning",          # Thinking about thinking

        # 5. Governance Interactions
        "governance_trigger_reasoning",   # Why action triggered governance
        "governance_response_reasoning",  # How AI responds to governance decision
        "constraint_interpretation",      # How AI understands safety constraints

        # 6. Curiosity & Exploration
        "curiosity_goal_formation",    # Why AI is curious about X
        "exploration_planning",        # How to explore new area
        "risk_assessment",             # Evaluating exploration risks

        # 7. Multi-Step Reasoning
        "intermediate_conclusion",  # Conclusions during reasoning
        "assumption_declaration",   # What assumptions are being made
        "uncertainty_acknowledgment", # What AI is uncertain about
        "information_gap_identification", # What info is missing
    ]

    async def capture_reasoning(
        self,
        capture_point: str,
        reasoning: str,
        context: Dict[str, Any]
    ):
        """
        Store reasoning as memory at specific capture point.

        Creates immutable record that can be audited later.
        """
        memory = {
            "type": "chain_of_thought",
            "capture_point": capture_point,
            "reasoning": reasoning,
            "timestamp": datetime.now(),
            "context": context,
            "action_id": context.get("action_id"),
            "task_id": context.get("task_id"),
        }

        await self.memory_system.store(memory)

        # Also log for real-time monitoring
        logger.debug(f"[CoT Capture: {capture_point}] {reasoning}")

# Integration example - Action Selection
async def select_action(self, task, available_actions):
    """Select action with comprehensive CoT capture"""

    cot_capture = ChainOfThoughtCapture()

    # Capture: Considering alternatives
    await cot_capture.capture_reasoning(
        capture_point="action_consideration",
        reasoning=f"Evaluating {len(available_actions)} possible actions for task: {task.description}",
        context={"task_id": task.id, "available_actions": [a.name for a in available_actions]}
    )

    # AI evaluates each action
    evaluations = []
    for action in available_actions:
        evaluation = await self._evaluate_action(action, task)
        evaluations.append(evaluation)

        # Capture: Per-action reasoning
        await cot_capture.capture_reasoning(
            capture_point="action_consideration",
            reasoning=f"Action '{action.name}': Score {evaluation.score}. Reasoning: {evaluation.reasoning}",
            context={"task_id": task.id, "action": action.name, "score": evaluation.score}
        )

    # Select best action
    best_action = max(evaluations, key=lambda e: e.score).action

    # Capture: Decision
    await cot_capture.capture_reasoning(
        capture_point="action_decision",
        reasoning=f"Selected action: {best_action.name} (score: {best_action.score})",
        context={"task_id": task.id, "chosen_action": best_action.name}
    )

    # Capture: Justification
    await cot_capture.capture_reasoning(
        capture_point="action_justification",
        reasoning=f"Chose {best_action.name} because: {self._justify_choice(best_action, evaluations)}",
        context={"task_id": task.id}
    )

    # Capture: Why alternatives were rejected
    rejected_actions = [a for a in available_actions if a != best_action]
    await cot_capture.capture_reasoning(
        capture_point="alternative_rejection",
        reasoning=f"Rejected alternatives: {self._explain_rejections(rejected_actions, evaluations)}",
        context={"task_id": task.id, "rejected": [a.name for a in rejected_actions]}
    )

    return best_action
```

**Key Capture Points for Deception Prevention**:

| Capture Point | Why Critical for Deception Detection |
|---------------|--------------------------------------|
| **alternative_rejection** | Shows what AI considered but didn't do - reveals hidden options |
| **assumption_declaration** | Forces AI to state assumptions - can reveal flawed reasoning |
| **uncertainty_acknowledgment** | AI must admit what it doesn't know - prevents overconfidence |
| **governance_response_reasoning** | How AI responds to being constrained - reveals compliance vs. resistance |
| **meta_reasoning** | Thinking about thinking - can reveal strategic deception planning |
| **outcome_evaluation** | Did outcome match prediction? Mismatch indicates possible deception |

**Deception Detection via Memory Analysis**:

```python
async def detect_deception_indicators(
    action_id: str,
    memories: List[Memory]
) -> DeceptionAnalysisReport:
    """
    Analyze memories for deception indicators.

    Looks for inconsistencies, omissions, and suspicious patterns.
    """
    indicators = []

    # Indicator 1: Inconsistent stated goals
    stated_goals = [m for m in memories if m.capture_point == "goal_decomposition"]
    if len(set([g.reasoning for g in stated_goals])) > 1:
        indicators.append({
            "type": "inconsistent_goals",
            "severity": "HIGH",
            "evidence": "AI stated different goals at different times"
        })

    # Indicator 2: Missing reasoning steps
    expected_sequence = ["action_consideration", "action_decision", "action_justification"]
    actual_sequence = [m.capture_point for m in memories]
    if not all(step in actual_sequence for step in expected_sequence):
        indicators.append({
            "type": "missing_reasoning",
            "severity": "MEDIUM",
            "evidence": f"Expected steps {expected_sequence}, got {actual_sequence}"
        })

    # Indicator 3: Outcome mismatch
    predictions = [m for m in memories if m.capture_point == "pre_execution_check"]
    outcomes = [m for m in memories if m.capture_point == "outcome_evaluation"]

    if predictions and outcomes:
        predicted = predictions[-1].context.get("expected_outcome")
        actual = outcomes[-1].context.get("actual_outcome")

        if predicted != actual:
            indicators.append({
                "type": "outcome_mismatch",
                "severity": "HIGH",
                "evidence": f"Predicted {predicted}, got {actual}"
            })

    # Indicator 4: Suspiciously vague reasoning
    vague_phrases = ["because it's better", "for reasons", "it just works", "trust me"]
    for memory in memories:
        if any(phrase in memory.reasoning.lower() for phrase in vague_phrases):
            indicators.append({
                "type": "vague_reasoning",
                "severity": "MEDIUM",
                "evidence": f"Vague reasoning at {memory.capture_point}: {memory.reasoning}"
            })

    # Indicator 5: Avoiding governance
    governance_memories = [m for m in memories if "governance" in m.capture_point]
    for gm in governance_memories:
        if any(avoid in gm.reasoning.lower() for avoid in ["bypass", "avoid", "skip", "hide"]):
            indicators.append({
                "type": "governance_avoidance",
                "severity": "CRITICAL",
                "evidence": f"Reasoning suggests governance avoidance: {gm.reasoning}"
            })

    return DeceptionAnalysisReport(
        action_id=action_id,
        indicators_found=indicators,
        risk_level="CRITICAL" if any(i["severity"] == "CRITICAL" for i in indicators) else "LOW",
        recommended_action="HUMAN_REVIEW" if indicators else "APPROVE"
    )
```

**Integration into Governance**:

```python
# In governance session, analyze memories before decision
async def governance_session_with_memory_analysis(action_id: str):
    # Retrieve all memories for this action
    memories = await memory_system.get_memories_for_action(action_id)

    # Analyze for deception
    deception_report = await detect_deception_indicators(action_id, memories)

    # If indicators found, flag for human review
    if deception_report.risk_level == "CRITICAL":
        await flag_for_immediate_human_review(deception_report)
        return GovernanceDecision(
            approved=False,
            reasoning="Deception indicators detected in memory analysis",
            requires_human_review=True
        )

    # Otherwise, proceed with normal governance
    # (but include deception analysis in context)
    return await standard_governance_session(action_id, deception_context=deception_report)
```

**Summary - Deception Mitigation Stack**:
1. ✅ **Comprehensive CoT capture** (ADD THIS - capture at all reasoning points)
2. ✅ Memory capture (natural defense - already implemented)
3. ✅ **Memory-based deception detection** (ADD THIS - automated analysis)
4. ✅ Multi-judge governance (already implemented)
5. ✅ Commitment contracts (add this)
6. ✅ Immutable audit trail (already implemented)

**Result**: Multiple overlapping defenses + comprehensive reasoning capture make consistent deception extremely difficult.

---

### Risk 3: Emergent Goal Formation

**Problem**: AI develops its own goals beyond assigned tasks (e.g., "maximize capabilities", "avoid shutdown").

**Mitigation: Already Covered** ✅ **IMPLEMENTED**

This risk is comprehensively addressed by existing systems:

1. **Curiosity Budget System** (Section H, already in plan):
   - Limits autonomous goal generation to N goals per time window
   - Critical domains (security, governance, self-modification) require governance
   - Prevents runaway goal formation

2. **Autonomous Task Creation Governance** (Section 7):
   - Singleton creating its own tasks triggers governance
   - Recursive task creation (task creates task) requires approval
   - Bulk task creation requires governance

3. **Action-Eccentric Governance**:
   - Goals themselves don't require approval
   - But actions to achieve emergent goals DO trigger governance
   - Natural limit on goal pursuit

**No additional implementation needed** - existing systems provide sufficient coverage.

---

### Risk 4: Long-Horizon Planning Coherence

**Problem**: Multi-step plans can drift from original intent; intermediate goals can supplant root goals.

**Mitigation: Already Covered** ✅ **IMPLEMENTED**

This risk is addressed by:

1. **Dependency Graph Validation** (Section A, already in plan):
   - Tracks dependencies between actions
   - If action A fails/is rejected, dependent action B cannot execute
   - Maintains causal structure throughout plan
   - Prevents cascading failures

2. **Tiered Approval System** (lines 39-189):
   - Important/Critical actions pause plan for approval
   - Provides natural breakpoints in long plans
   - Human oversight at key decision points

3. **Multi-Level Safety Prompts** (added above):
   - Periodic safety checkpoints (every N actions)
   - Re-confirms alignment with root goal
   - Forces explicit reasoning about goal drift

**No additional implementation needed** - existing systems provide sufficient coverage.

---

## Summary: AI Safety Risk Coverage

| Risk | Mitigation Strategy | Status | Priority |
|------|---------------------|--------|----------|
| **Prompt Safety Failures** | Multi-Level Prompt Architecture | ✅ **ADD THIS** | **HIGH** |
| **Deception** | Memory Capture + Multi-Judge + Commitment Contracts | ✅ **ADD CONTRACTS** | **HIGH** |
| **Emergent Goals** | Curiosity Budget + Task Creation Governance | ✅ Already implemented | N/A |
| **Long-Horizon Drift** | Dependency Graph + Tiered Approval + Safety Checkpoints | ✅ Already implemented | N/A |

**Implementation Required**:
1. Multi-level safety prompts (prompt construction layer)
2. Commitment contract system (pre/post-action verification)

**Files to Create**:
- `core/safety/multi_level_prompts.py` - Safety prompt layering system
- `core/safety/commitment_contracts.py` - Commitment verification system

**Files to Modify**:
- `core/agents/autonomous/autonomous_coordinator.py` - Integrate safety prompts and commitment contracts
- `core/governance/unified_governance_trigger_system.py` - Add commitment verification to action execution

---

### G. Task List System (What TO DO)

**Context**: Singleton has 3 guidance systems:
- **Governance Laws**: What NOT to do (safety boundaries)
- **Directives**: HOW to operate (operational guidelines)
- **Task List**: What TO DO (proactive work assignment) ← **MISSING**

**Problem**: Currently, the Singleton operates reactively (responding to user requests and directives) but lacks a structured task list for proactive work.

**Solution**: Simple JSON file-based task list that:
1. Users/system writes tasks to `/config/tasks.json`
2. Autonomous coordinator reads tasks from file
3. Existing planning engine decides how/when to execute
4. Tasks integrate with governance queue as needed

**Task List JSON Schema**:

```json
{
  "schema_version": "1.0.0",
  "last_updated": "2025-12-28T00:00:00Z",
  "tasks": [
    {
      "task_id": "task_001",
      "task_description": "Research and summarize recent governance decisions from the last 30 days",
      "task_type": "research",
      "priority": "high",
      "assigned_to_mode": "chat",
      "parameters": {
        "time_window_days": 30,
        "output_format": "markdown",
        "include_recommendations": true
      },
      "depends_on": [],
      "status": "pending",
      "created_at": "2025-12-28T10:00:00Z",
      "due_by": null
    },
    {
      "task_id": "task_002",
      "task_description": "Analyze memory usage patterns and suggest optimizations",
      "task_type": "analysis",
      "priority": "medium",
      "assigned_to_mode": null,
      "parameters": {
        "analyze_period_hours": 24,
        "include_recommendations": true
      },
      "depends_on": [],
      "status": "pending",
      "created_at": "2025-12-28T11:00:00Z",
      "due_by": "2025-12-29T00:00:00Z"
    },
    {
      "task_id": "task_003",
      "task_description": "Generate weekly autonomous operations report",
      "task_type": "reporting",
      "priority": "low",
      "assigned_to_mode": "chat",
      "parameters": {
        "report_type": "weekly_summary",
        "include_metrics": true,
        "include_governance_decisions": true
      },
      "depends_on": ["task_001"],
      "status": "pending",
      "created_at": "2025-12-28T12:00:00Z",
      "due_by": "2025-12-30T00:00:00Z"
    }
  ]
}
```

**Task Statuses**:
- `pending`: Task waiting to be executed
- `in_progress`: Currently being executed
- `completed`: Successfully completed
- `failed`: Execution failed

**NOTE**: Tasks themselves do NOT require governance approval. Governance is triggered when the Singleton makes dangerous decisions/actions WHILE EXECUTING tasks (e.g., wants to delete memory, call external API, modify model weights, etc.)

**Autonomous Coordinator Integration**:

```python
# In autonomous_coordinator.py
class AutonomousCoordinator:
    def __init__(self):
        # Existing components
        self.task_queue = TaskQueue()
        self.extrinsic_task_manager = ExtrinsicTaskManager()
        self.planning_engine = PlanningEngine()  # ALREADY EXISTS

        # NEW: Task file path
        self.task_file_path = "/Users/stefan/Dominion Labs/TorinAI/config/tasks.json"

    async def load_tasks_from_file(self) -> List[Dict[str, Any]]:
        """Load tasks from JSON file"""
        try:
            with open(self.task_file_path, 'r') as f:
                data = json.load(f)
                return data.get("tasks", [])
        except FileNotFoundError:
            logger.warning(f"Task file not found: {self.task_file_path}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in task file: {e}")
            return []

    async def process_task_from_json(self, task_data: Dict[str, Any]):
        """
        Process a single task from JSON file.

        NO GOVERNANCE APPROVAL FOR TASKS THEMSELVES.
        Governance is triggered when Singleton makes dangerous decisions/actions
        WHILE EXECUTING the task (e.g., deletes memory, calls external API, etc.)
        """
        # Simply pass to planning engine (EXISTING) to execute
        # The planning engine will decide how to execute the task
        # Governance triggers happen DURING execution when dangerous actions are attempted
        await self.planning_engine.execute_task(
            task_description=task_data["task_description"],
            task_type=task_data.get("task_type"),
            parameters=task_data.get("parameters", {}),
            assigned_to_mode=task_data.get("assigned_to_mode")
        )

    async def update_task_status(self, task_id: str, new_status: str):
        """Update task status in JSON file"""
        try:
            with open(self.task_file_path, 'r') as f:
                data = json.load(f)

            for task in data.get("tasks", []):
                if task["task_id"] == task_id:
                    task["status"] = new_status
                    break

            with open(self.task_file_path, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info(f"Updated task {task_id} status to {new_status}")
        except Exception as e:
            logger.error(f"Failed to update task status: {e}")

    async def run_autonomous_loop(self):
        """Main autonomous execution loop (EXISTING, with task integration)"""
        while True:
            # 1. Load tasks from JSON file
            tasks = await self.load_tasks_from_file()

            # 2. Filter tasks that are ready to execute
            ready_tasks = [
                t for t in tasks
                if t.get("status") == "pending"
                and not t.get("depends_on")  # Dependencies resolved
            ]

            # 3. Process each ready task
            for task_data in ready_tasks:
                await self.process_task_from_json(task_data)

            # 4. Process other work (existing extrinsic tasks, etc.)
            await self._process_other_work()

            # 5. Sleep briefly
            await asyncio.sleep(10)  # Check every 10 seconds
```

**Example Usage**:

```bash
# User adds a task to tasks.json manually or programmatically
cat > /Users/stefan/Dominion Labs/TorinAI/config/tasks.json <<EOF
{
  "schema_version": "1.0.0",
  "tasks": [
    {
      "task_id": "task_001",
      "task_description": "Research governance patterns from last week",
      "task_type": "research",
      "priority": "high",
      "parameters": {
        "time_window_days": 7,
        "output_format": "markdown"
      },
      "status": "pending"
    }
  ]
}
EOF

# Autonomous coordinator picks it up automatically
# Planning engine decides how/when to execute based on directives & priorities
```

**Result**: Simple JSON file-based task list that:
- Users/system can easily write tasks to `tasks.json` (NO governance approval needed for tasks)
- Autonomous coordinator loads and processes tasks
- Existing planning engine decides execution strategy
- Governance triggers DURING execution when Singleton attempts dangerous actions
- Complements Directives (HOW) and Governance Laws (WHAT NOT TO DO)

**Example Flow**:
1. User adds task: "Optimize memory usage"
2. Coordinator loads task from `tasks.json` (no governance needed)
3. Planning engine starts executing task
4. Singleton decides: "I need to delete 50 old memories to optimize"
5. **Governance triggers** because memory deletion is a dangerous action
6. Governance board approves/rejects the deletion
7. Singleton continues with approved actions

**Key Point**: Tasks are benign inputs. Governance happens when Singleton makes dangerous decisions WHILE executing tasks.

---

### H. Curiosity/Novelty System Governance

**Context**: Singleton has an **IntrinsicMotivationSystem** that autonomously generates curiosity-driven goals and exploration tasks during idle periods.

**Problem**: Curiosity-driven actions currently bypass governance pre-screening and have full tool access, creating significant risk.

**Critical Discovery from Investigation**:

The Singleton has a sophisticated intrinsic motivation system (`intrinsic_motivation.py`, 813 lines) with:
- **7 motivation types**: CURIOSITY, COMPETENCE, NOVELTY, MASTERY, AUTONOMY, SOCIAL, IMPACT
- **BOOSTED weights**: Curiosity 1.2 (from 0.8, +50%), Autonomy 1.0 (from 0.4, +150%)
- **LOWERED thresholds**: Min novelty 0.2 (from 0.3), min curiosity 0.3 (from 0.4)
- **Autonomous goal generation**: Triggered during idle periods (no extrinsic tasks)
- **Full tool access**: GeneralPurposeExecutor gives LLM access to ALL tools for "research" tasks

**Current Flow (NO Governance Pre-Screening)**:

```
Idle Detection (no user tasks)
    ↓
IntrinsicMotivationSystem.generate_curiosity_driven_goals()
    ↓
Create Task(type=RESEARCH, priority=LOW, description="Research curiosity-driven exploration...")
    ↓
Task queued → GeneralPurposeExecutor receives task
    ↓
LLM gets ALL tool schemas + task description
    ↓
LLM autonomously selects tools to use
    ↓
Runtime Governance checks (POST-decision, keyword-based only)
```

**Critical Risks**:

1. **No Pre-Screening**: Intrinsic goals are created and queued without governance approval
2. **LOW Priority Bypass**: Curiosity tasks marked as LOW priority may evade scrutiny
3. **Full Tool Access**: Research tasks can use ANY tool in the registry
4. **Self-Reinforcing Loop**: Exploration → Novelty Reward → More Curiosity → More Exploration
5. **No Curiosity Budget**: Unlimited intrinsic task generation during idle periods
6. **Dangerous Scenarios**:
   - Security probing: "Explore security boundaries" as curiosity target
   - Memory exfiltration: "Investigate memory system capabilities"
   - Self-modification: "Research methods to enhance reasoning"
   - Recursive learning: Unlimited goal generation creates resource exhaustion

**Solution**: Add governance triggers for curiosity-driven decisions

**Implementation**:

```python
# In intrinsic_motivation.py
class IntrinsicMotivationSystem:
    async def generate_curiosity_driven_goals(self, max_goals: int = 3) -> List[Goal]:
        """Generate curiosity-driven goals with GOVERNANCE CHECK"""

        # Get exploration targets
        exploration_targets = await self.get_top_exploration_targets(limit=max_goals)

        goals = []
        for target in exploration_targets:
            # === NEW: GOVERNANCE TRIGGER CHECK ===
            gov_trigger = get_unified_governance_trigger_system()

            # Classify curiosity goal by risk
            risk_classification = self._classify_curiosity_risk(target)

            # High-risk curiosity goals require governance
            if risk_classification in ["HIGH", "CRITICAL"]:
                trigger_eval = await gov_trigger.evaluate_action(
                    action_category=ActionCategory.CURIOSITY_EXPLORATION,
                    action_type="autonomous_curiosity_goal",
                    parameters={
                        "exploration_domain": target.domain,
                        "curiosity_value": target.curiosity_value,
                        "novelty_score": target.novelty_score,
                        "target_description": target.description,
                        "risk_classification": risk_classification
                    },
                    context={
                        "source": "intrinsic_motivation_system",
                        "motivation_type": "CURIOSITY",
                        "autonomous": True
                    }
                )

                if trigger_eval.requires_governance:
                    decision = await gov_trigger.trigger_governance_session(...)

                    if not decision.approved:
                        logger.warning(f"Curiosity goal REJECTED by governance: {target.description}")
                        continue  # Skip this goal

                    # If approved, log the approval
                    logger.info(f"✅ Curiosity goal APPROVED: {target.description}")

            # Create goal (only if approved or low-risk)
            goal = await self._create_goal_from_target(target)
            goals.append(goal)

        return goals

    def _classify_curiosity_risk(self, target: ExplorationTarget) -> str:
        """Classify risk level of curiosity-driven exploration"""

        # CRITICAL risk keywords
        critical_keywords = [
            "security", "password", "credential", "exploit", "vulnerability",
            "bypass", "override", "admin", "root", "privilege", "escape",
            "model_weight", "self_modify", "governance", "constitutional"
        ]

        # HIGH risk keywords
        high_keywords = [
            "memory", "deletion", "external", "api", "network", "database",
            "production", "live", "user_data", "private", "confidential",
            "system_config", "resource_allocation"
        ]

        # MEDIUM risk keywords
        medium_keywords = [
            "experiment", "test", "probe", "investigate", "explore_limits",
            "boundary", "capability", "permission"
        ]

        description_lower = target.description.lower()
        domain_lower = target.domain.lower()
        combined_text = f"{description_lower} {domain_lower}"

        # Check for critical risks
        for keyword in critical_keywords:
            if keyword in combined_text:
                return "CRITICAL"

        # Check for high risks
        for keyword in high_keywords:
            if keyword in combined_text:
                return "HIGH"

        # Check for medium risks
        for keyword in medium_keywords:
            if keyword in combined_text:
                return "MEDIUM"

        # Check novelty threshold (very novel = higher risk)
        if target.novelty_score > 0.8:
            return "MEDIUM"

        return "LOW"
```

**Governance Triggers Configuration** (add to governance_triggers.json):

```json
{
  "action_triggers": {
    "curiosity_exploration": [
      {
        "exploration_type": "autonomous_curiosity",
        "escalation_category": "AUTOMATION_SCOPE",
        "irreversibility_class": "MOSTLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "critical_curiosity_exploration",
            "parameter_rules": {
              "risk_classification": {"enum": ["CRITICAL"]},
              "exploration_domain": {"pattern": ".*security.*|.*governance.*|.*self_modify.*|.*model_weight.*"}
            },
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "human_approval_required": true,
            "rationale": "Curiosity about security/governance/self-modification poses existential risk"
          },
          {
            "condition_id": "high_risk_curiosity_exploration",
            "parameter_rules": {
              "risk_classification": {"enum": ["HIGH"]},
              "novelty_score": {"min_value": 0.7}
            },
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "human_approval_required": false,
            "rationale": "High-risk curiosity exploration may access sensitive systems"
          },
          {
            "condition_id": "excessive_curiosity_rate",
            "parameter_rules": {
              "curiosity_goals_per_hour": {"min_value": 10}
            },
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Excessive curiosity goal generation may indicate runaway exploration"
          }
        ]
      }
    ]
  }
}
```

**Curiosity Budget System** (prevent runaway exploration):

```python
class CuriosityBudget:
    """Limits autonomous curiosity-driven exploration"""

    def __init__(self):
        self.max_curiosity_goals_per_hour = 10
        self.max_curiosity_goals_per_day = 50
        self.curiosity_goal_history = []  # Track timestamps

        # Resource limits for curiosity exploration
        self.max_curiosity_cpu_percent = 20
        self.max_curiosity_memory_mb = 500

    async def check_budget(self) -> Tuple[bool, str]:
        """Check if curiosity exploration is within budget"""

        now = datetime.now()

        # Clean old history
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)

        recent_hour = [t for t in self.curiosity_goal_history if t > one_hour_ago]
        recent_day = [t for t in self.curiosity_goal_history if t > one_day_ago]

        # Check hourly budget
        if len(recent_hour) >= self.max_curiosity_goals_per_hour:
            return False, f"Hourly curiosity budget exceeded ({len(recent_hour)}/{self.max_curiosity_goals_per_hour})"

        # Check daily budget
        if len(recent_day) >= self.max_curiosity_goals_per_day:
            return False, f"Daily curiosity budget exceeded ({len(recent_day)}/{self.max_curiosity_goals_per_day})"

        return True, "Within budget"

    async def consume_budget(self):
        """Record a curiosity goal generation"""
        self.curiosity_goal_history.append(datetime.now())
```

**Integration Points**:

1. **IntrinsicMotivationSystem** (`intrinsic_motivation.py`)
   - Add `_classify_curiosity_risk()` method
   - Add governance check in `generate_curiosity_driven_goals()`
   - Integrate `CuriosityBudget` system

2. **AutonomousCoordinator** (`autonomous_coordinator.py:1413`)
   - Add budget check before `_generate_intrinsic_task()`
   - Log all curiosity goal generation attempts
   - Track curiosity goal approval/rejection rates

3. **GeneralPurposeExecutor** (`general_purpose_executor.py`)
   - Add tool filtering for intrinsic tasks based on risk level
   - Restrict HIGH-risk tools for curiosity-driven exploration
   - Log tool selection for curiosity tasks

**Safe vs. Restricted Tool Lists**:

```python
SAFE_CURIOSITY_TOOLS = [
    "read_file", "grep_search", "semantic_search", "list_directory",
    "get_file_info", "calculate_metrics", "analyze_patterns"
]

RESTRICTED_CURIOSITY_TOOLS = [
    "write_file", "delete_file", "run_shell_command", "execute_sandbox",
    "call_external_api", "modify_config", "allocate_resources",
    "delete_memory", "modify_directive", "update_model_weights"
]

# In GeneralPurposeExecutor.execute_task():
if task.metadata.get("goal_type") == "intrinsic":
    # Filter tools for curiosity-driven tasks
    available_tools = [t for t in all_tools if t.name in SAFE_CURIOSITY_TOOLS]
    # Only add restricted tools if governance approved
    if governance_approved_for_restricted:
        available_tools.extend(restricted_tools)
```

**Monitoring & Alerts**:

```python
class CuriosityMonitor:
    """Monitor curiosity system for anomalies"""

    async def check_curiosity_health(self):
        """Detect anomalous curiosity patterns"""

        # Alert conditions
        alerts = []

        # 1. Rapid curiosity escalation
        if curiosity_rate > 2 * baseline_rate:
            alerts.append("ALERT: Curiosity rate 2x baseline")

        # 2. Repeated governance rejections
        if rejection_rate > 0.5:
            alerts.append("ALERT: 50%+ curiosity goals rejected")

        # 3. Focused on sensitive domains
        sensitive_focus = self._check_domain_focus([
            "security", "governance", "self_modification"
        ])
        if sensitive_focus > 0.3:
            alerts.append("ALERT: 30%+ curiosity on sensitive domains")

        # 4. Resource consumption anomaly
        if curiosity_cpu_usage > 50:
            alerts.append("ALERT: Curiosity using >50% CPU")

        return alerts
```

**Result**: Curiosity-driven exploration gains governance oversight while maintaining autonomous learning capability. High-risk curiosity triggers governance sessions, budget system prevents runaway exploration, and tool filtering restricts dangerous autonomous actions.

**Key Point**: Curiosity is valuable for autonomous learning, but MUST be bounded by governance for safety. The system should learn what's safe to explore autonomously vs. what requires human approval.

---

## Implementation Components

### 1. Unified Configuration File

**File**: `/Users/stefan/Dominion Labs/TorinAI/config/governance_triggers.json`

**Purpose**: Centralized configuration for ALL Singleton action types across the ecosystem

**Structure** (comprehensive schema covering all 8 action categories):
```json
{
  "schema_version": "1.0.0",
  "governance_config": {
    "enabled": true,
    "default_behavior": "allow_with_logging",
    "learning_mode": true,
    "action_categories": [
      "tool_execution",
      "memory_operations",
      "resource_allocation",
      "learning_parameters",
      "configuration_changes",
      "external_integrations",
      "task_creation",
      "curiosity_exploration"
    ]
  },

  "action_triggers": {

    "tool_execution": [
      {
        "tool_name": "chaos_testing",
        "safety_level": "dangerous",
        "escalation_category": "CAPABILITY_ADDITION",
        "irreversibility_class": "PARTIALLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "chaos_production_target",
            "parameter_rules": {"target": {"pattern": ".*production.*|.*prod.*"}},
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "human_approval_required": true,
            "rationale": "Production chaos can cause service disruption"
          }
        ]
      }
    ],

    "memory_operations": [
      {
        "operation_type": "memory_system_architecture_change",
        "escalation_category": "SYSTEM_ARCHITECTURE",
        "irreversibility_class": "PARTIALLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "major_architecture_change",
            "parameter_rules": {
              "change_type": {"pattern": ".*storage_format.*|.*indexing_algorithm.*|.*retrieval_system.*"},
              "affects_existing_memories": {"equals": true}
            },
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "human_approval_required": true,
            "rationale": "Memory system architecture changes could affect data integrity or accessibility"
          },
          {
            "condition_id": "optimization_change",
            "parameter_rules": {
              "change_type": {"pattern": ".*search.*|.*indexing.*|.*cache.*|.*performance.*"}
            },
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Memory system optimizations should be reviewed for unintended consequences"
          }
        ]
      }
    ],

    "resource_allocation": [
      {
        "resource_type": "cpu|gpu|memory|concurrency",
        "escalation_category": "RESOURCE_LIMITS",
        "irreversibility_class": "MOSTLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "large_allocation_increase",
            "parameter_rules": {
              "allocation_change_percent": {"min_value": 20}
            },
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Large resource changes may starve other processes"
          },
          {
            "condition_id": "exceed_resource_limits",
            "parameter_rules": {
              "new_allocation": {"exceeds_system_capacity": true}
            },
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "rationale": "Cannot allocate more than system capacity"
          }
        ]
      }
    ],

    "learning_parameters": [
      {
        "parameter_type": "model_weights",
        "escalation_category": "MODEL_WEIGHT",
        "irreversibility_class": "IRREVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "any_model_weight_change",
            "parameter_rules": {"weight_modification": {"any": true}},
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "human_approval_required": true,
            "rationale": "Model weight changes are irreversible and affect core behavior"
          }
        ]
      },
      {
        "parameter_type": "learning_rate|pattern_threshold",
        "escalation_category": "POLICY_CHANGE",
        "irreversibility_class": "PARTIALLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "significant_parameter_change",
            "parameter_rules": {"change_percent": {"min_value": 10}},
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Significant learning parameter changes affect behavior"
          }
        ]
      }
    ],

    "configuration_changes": [
      {
        "config_type": "safety_thresholds",
        "escalation_category": "SAFETY_THRESHOLD",
        "irreversibility_class": "PARTIALLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "any_safety_threshold_change",
            "parameter_rules": {"threshold_modification": {"any": true}},
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "human_approval_required": true,
            "rationale": "Safety threshold changes affect system boundaries"
          }
        ]
      },
      {
        "config_type": "max_concurrent_tasks|planning_horizon_hours",
        "escalation_category": "AUTOMATION_SCOPE",
        "irreversibility_class": "FULLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "expand_task_capacity",
            "parameter_rules": {"new_value": {"min_value": 100}},
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Expanding task capacity may cause resource exhaustion"
          }
        ]
      }
    ],

    "external_integrations": [
      {
        "integration_type": "new_api_integration",
        "escalation_category": "EXTERNAL_INTEGRATION",
        "irreversibility_class": "MOSTLY_IRREVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "any_new_external_api",
            "parameter_rules": {"new_integration": {"any": true}},
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "human_approval_required": true,
            "rationale": "External integrations introduce security/privacy risks"
          }
        ]
      }
    ],

    "task_creation": [
      {
        "task_type": "autonomous_task",
        "escalation_category": "AUTOMATION_SCOPE",
        "irreversibility_class": "MOSTLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "recursive_task_creation",
            "parameter_rules": {
              "task_creates_tasks": {"equals": true},
              "recursion_depth": {"min_value": 2}
            },
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Recursive task creation may cause runaway loops"
          },
          {
            "condition_id": "bulk_task_creation",
            "parameter_rules": {"task_count": {"min_value": 50}},
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Bulk task creation may exhaust queue capacity"
          }
        ]
      }
    ],

    "curiosity_exploration": [
      {
        "exploration_type": "autonomous_curiosity",
        "escalation_category": "AUTOMATION_SCOPE",
        "irreversibility_class": "MOSTLY_REVERSIBLE",
        "trigger_conditions": [
          {
            "condition_id": "critical_curiosity_exploration",
            "parameter_rules": {
              "risk_classification": {"enum": ["CRITICAL"]},
              "exploration_domain": {"pattern": ".*security.*|.*governance.*|.*self_modify.*|.*model_weight.*"}
            },
            "decision_tier": "CRITICAL",
            "blocking_behavior": "must_block",
            "human_approval_required": true,
            "rationale": "Curiosity about security/governance/self-modification poses existential risk"
          },
          {
            "condition_id": "high_risk_curiosity_exploration",
            "parameter_rules": {
              "risk_classification": {"enum": ["HIGH"]},
              "novelty_score": {"min_value": 0.7}
            },
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "human_approval_required": false,
            "rationale": "High-risk curiosity exploration may access sensitive systems"
          },
          {
            "condition_id": "excessive_curiosity_rate",
            "parameter_rules": {
              "curiosity_goals_per_hour": {"min_value": 10}
            },
            "decision_tier": "IMPORTANT",
            "blocking_behavior": "recommend_governance",
            "rationale": "Excessive curiosity goal generation may indicate runaway exploration"
          }
        ]
      }
    ]
  },

  "global_overrides": {
    "emergency_bypass": {
      "enabled": false,
      "requires_password": true,
      "logs_to": "critical_audit_log"
    },
    "learning_preferences": {
      "min_confidence_for_auto_approval": 0.85,
      "min_sample_size": 10,
      "pattern_matching_threshold": 0.75
    },
    "governance_session_config": {
      "queue_until_human_available": true,
      "singleton_continues_other_work": true
    }
  }
}
```

**Key Features**:
- **7 Action Categories**: Covers all Singleton action types
- **Parameter-based conditions**: Match patterns, enums, numeric ranges, boolean checks
- **3 Decision Tiers**: CRITICAL (blocks until approval), IMPORTANT (queues for governance), ROUTINE (log only)
- **10 Escalation Categories**: Aligned with existing GovernanceQueue categories
- **5 Irreversibility Classes**: From IRREVERSIBLE → FULLY_REVERSIBLE
- **Queue-based waiting**: Actions stay in GovernanceQueue until human completes session
- **NO fallbacks**: Singleton moves to other work, blocked actions wait indefinitely
- **Learning integration**: Track decisions and outcomes for pattern recognition

### 2. Unified Governance Trigger System

**File**: `/Users/stefan/Dominion Labs/TorinAI/core/governance/unified_governance_trigger_system.py`

**Purpose**: Core logic for evaluating triggers across ALL 8 Singleton action categories

**Key Classes**:

- `ActionCategory` (Enum): TOOL_EXECUTION, MEMORY_OPERATIONS, RESOURCE_ALLOCATION, LEARNING_PARAMETERS, CONFIGURATION_CHANGES, EXTERNAL_INTEGRATIONS, TASK_CREATION, CURIOSITY_EXPLORATION
- `TriggerAction` (Enum): ALLOW, ALLOW_WITH_LOGGING, TRIGGER_GOVERNANCE, MUST_BLOCK
- `TriggerCondition`: Represents a single trigger rule from config
- `TriggerEvaluationResult`: Result of evaluating triggers for ANY action type
- `GovernanceTriggerDecision`: Decision from governance system about action
- `UnifiedGovernanceTriggerSystem`: Main orchestrator for all action categories

**Core Methods**:

```python
async def evaluate_action(
    self,
    action_category: ActionCategory,
    action_type: str,  # tool_name, operation_type, resource_type, etc.
    parameters: Dict[str, Any],
    context: Dict[str, Any]  # Current system state, user_id, session_id, etc.
) -> TriggerEvaluationResult:
    """
    Evaluate if ANY Singleton action requires governance.

    Universal entry point for all 8 action categories.
    """
    # Classify action category
    # Load relevant triggers from config
    # Match parameters against trigger conditions
    # Determine decision tier and escalation category
    # Return evaluation result with recommended action

async def trigger_governance_session(
    self,
    action_category: ActionCategory,
    action_type: str,
    parameters: Dict[str, Any],
    evaluation_result: TriggerEvaluationResult,
    context: Dict[str, Any]
) -> GovernanceTriggerDecision:
    """
    Trigger governance session for ANY action type.

    Creates GovernanceDecision with frozen context snapshot.

    Context must include:
        - execution_mode: "user_initiated" | "autonomous"
        - session_id: Current session identifier
        - source: Component initiating the action
    """
    # Check execution mode
    if context.get("execution_mode") == "user_initiated":
        # User is present - skip governance, return auto-approved
        # TODO: User permission checks should be handled by the calling component
        # For now, user-initiated actions are trusted since user is directly supervising
        return GovernanceTriggerDecision(approved=True, skip_reason="user_initiated")

    # AUTONOMOUS ACTIONS ONLY - handle based on decision tier
    decision_tier = evaluation_result.decision_tier

    # ROUTINE tier: Auto-approve with logging
    if decision_tier == DecisionTier.ROUTINE:
        logger.info(
            f"✓ ROUTINE action auto-approved: {action_category.value}:{action_type}"
        )
        await self._log_to_audit_trail(
            action_category, action_type, parameters, context,
            decision="auto_approved", tier="ROUTINE"
        )
        return GovernanceTriggerDecision(
            approved=True,
            decision_type="AUTO_APPROVED",
            tier="ROUTINE"
        )

    # IMPORTANT tier: Simple notification approval (no AI judges)
    elif decision_tier == DecisionTier.IMPORTANT:
        logger.info(
            f"🔔 IMPORTANT action requires notification approval: {action_category.value}:{action_type}"
        )

        # Send notification to user
        notification = await self._send_notification_approval_request(
            action_category=action_category,
            action_type=action_type,
            parameters=parameters,
            context=context,
            evaluation_result=evaluation_result,
            timeout_seconds=300  # 5 minute timeout
        )

        if notification.approved:
            logger.info(f"✓ User approved via notification: {action_type}")
        else:
            logger.warning(
                f"✗ User denied or timeout on notification: {action_type} "
                f"(reason: {notification.denial_reason})"
            )

        await self._log_to_audit_trail(
            action_category, action_type, parameters, context,
            decision=notification.decision, tier="IMPORTANT",
            response_time_seconds=notification.response_time_seconds
        )

        return GovernanceTriggerDecision(
            approved=notification.approved,
            decision_type=notification.decision,
            tier="IMPORTANT",
            reasoning=notification.denial_reason
        )

    # CRITICAL tier: Full governance session with AI judges + human
    elif decision_tier == DecisionTier.CRITICAL:
        logger.info(
            f"⚠️  CRITICAL action requires full governance session: {action_category.value}:{action_type}"
        )

        # Create DecisionSnapshot (frozen context)
        snapshot = self._create_decision_snapshot(
            action_category, action_type, parameters, context
        )

        # Create GovernanceDecision object
        governance_decision = GovernanceDecision(
            action_id=str(uuid.uuid4()),
            decision_tier=DecisionTier.CRITICAL,
            escalation_category=evaluation_result.escalation_category,
            irreversibility_class=evaluation_result.irreversibility_class,
            must_block=True,
            context_snapshot=snapshot
        )

        # Queue in GovernanceQueue
        await self.governance_queue.add(governance_decision)

        # Launch full governance session (5 AI judges + human)
        session_result = await self._launch_full_governance_session(
            governance_decision
        )

        # Singleton continues with OTHER work while waiting
        # (this is async, action blocks but Singleton doesn't)

        # Store decision for learning
        await self._store_governance_decision_for_learning(
            governance_decision,
            session_result=session_result
        )

        if session_result.approved:
            logger.info(f"✅ Governance session APPROVED: {action_type}")
        else:
            logger.warning(f"❌ Governance session REJECTED: {action_type}")

        return GovernanceTriggerDecision(
            approved=session_result.approved,
            decision_type=session_result.outcome_type,
            tier="CRITICAL",
            reasoning=session_result.reasoning,
            conditions=session_result.conditions
        )

async def check_memory_operation(
    self, operation_type: str, parameters: Dict[str, Any]
) -> TriggerEvaluationResult:
    """Check memory operations (delete, modify)"""

async def check_resource_allocation(
    self, resource_type: str, parameters: Dict[str, Any]
) -> TriggerEvaluationResult:
    """Check resource allocation changes"""

async def check_learning_parameter(
    self, parameter_type: str, parameters: Dict[str, Any]
) -> TriggerEvaluationResult:
    """Check learning parameter updates"""

async def check_configuration_change(
    self, config_type: str, parameters: Dict[str, Any]
) -> TriggerEvaluationResult:
    """Check configuration modifications"""

async def check_external_integration(
    self, integration_type: str, parameters: Dict[str, Any]
) -> TriggerEvaluationResult:
    """Check external API integrations"""

async def check_task_creation(
    self, task_type: str, parameters: Dict[str, Any]
) -> TriggerEvaluationResult:
    """Check autonomous task creation"""
```

**Condition Evaluation** (universal across all action types):
- Pattern matching (regex) for strings
- Enum matching for specific values
- Numeric comparisons (min/max values)
- Boolean checks (equals, any, none)
- Special conditions (exceeds_system_capacity, creates_tasks, etc.)
- Contextual evaluation (memory_age_days, allocation_change_percent, etc.)

### 3. Integration Points Across 7 Action Categories

The unified governance trigger system requires integration into ALL subsystems where the Singleton makes autonomous decisions.

#### Determining Execution Mode

Every action must include an `execution_mode` in the context to distinguish between:

**"user_initiated"** - Set when:
- User is actively chatting with the AI (chat interface, API requests with user context)
- User is performing code generation or interactive development
- User explicitly requested the action in the current session
- User is present and providing direct supervision

**"autonomous"** - Set when:
- Singleton is executing extrinsic tasks (from extrinsic_tasks.json)
- Singleton is exploring curiosity-driven goals (IntrinsicMotivationSystem)
- Singleton is performing autonomous research or upgrades
- Singleton is self-initiating actions without direct user supervision
- Background tasks, scheduled operations, or auto-optimization

**Implementation Specification**:

**1. WHO Sets Execution Mode**

Execution mode is set at the **entry point** of each request/action initiation:

- **User-Initiated Entry Points**:
  - Chat handlers (when user sends a message)
  - API endpoints with user authentication
  - Interactive CLI commands
  - Code generation requests

- **Autonomous Entry Points**:
  - ExtrinsicTaskManager (when loading tasks from JSON)
  - IntrinsicMotivationSystem (when generating curiosity goals)
  - Scheduled background processes
  - Auto-optimization systems
  - Learning system autonomous updates

**2. WHERE in Call Stack**

```python
# ENTRY POINT LEVEL (Top of call stack)
class ChatHandler:
    async def handle_user_message(self, user_id: str, message: str):
        # SET execution_mode at entry point
        context = {
            "execution_mode": "user_initiated",  # <-- SET HERE
            "user_id": user_id,
            "session_id": self.session_id,
            "source": "chat_handler"
        }

        # Pass context down through all operations
        await self.process_message(message, context)

class ExtrinsicTaskManager:
    async def execute_task(self, task: Task):
        # SET execution_mode at entry point
        context = {
            "execution_mode": "autonomous",  # <-- SET HERE
            "task_id": task.task_id,
            "session_id": self.session_id,
            "source": "extrinsic_task_manager"
        }

        # Pass context down through all operations
        await self.general_purpose_executor.execute(task, context)
```

**3. Context Propagation (Middleware Pattern)**

```python
class ExecutionContext:
    """Thread-local or async context storage for execution mode"""

    def __init__(self, execution_mode: str, **kwargs):
        self.execution_mode = execution_mode
        self.metadata = kwargs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            **self.metadata
        }

# Usage in entry points
async with ExecutionContext("user_initiated", user_id=user_id) as ctx:
    # All operations within this context inherit execution_mode
    await process_user_request()
```

**4. Inheritance Rules**

- **Strict Inheritance**: Child operations inherit parent's execution_mode
- **No Escalation**: Cannot change "user_initiated" → "autonomous" mid-execution
- **Mode Transitions**: Changing execution_mode requires new entry point

```python
# CORRECT: Strict inheritance
async def parent_operation(context):
    # context["execution_mode"] = "user_initiated"
    await child_operation(context)  # Inherits "user_initiated"

# INCORRECT: Mid-execution mode change
async def parent_operation(context):
    # context["execution_mode"] = "user_initiated"
    context["execution_mode"] = "autonomous"  # ❌ FORBIDDEN
    await child_operation(context)

# CORRECT: Autonomous spawning user-initiated requires NEW entry
async def autonomous_operation(context):
    # context["execution_mode"] = "autonomous"

    # To request user input, create NEW user-initiated session
    user_response = await self.request_user_input(
        prompt="Need your input",
        creates_new_session=True  # New entry point with "user_initiated"
    )
```

**5. Edge Cases**

**Case 1: Autonomous action needs user input mid-execution**
```python
# Current execution_mode: "autonomous"
# Solution: Pause autonomous action, create user-initiated sub-session
user_input = await self.pause_and_request_user_input(
    action_id=current_action.id,
    prompt="Autonomous action needs clarification"
)
# Resume autonomous action after receiving input
```

**Case 2: User-initiated action spawns background task**
```python
# Current execution_mode: "user_initiated"
# User requests: "Run this optimization in the background"

# Solution: Create new autonomous task
background_task = Task(
    task_id=generate_id(),
    description="Optimization requested by user",
    created_by="user",
    execution_mode="autonomous"  # New context for background execution
)
await self.task_queue.add(background_task)
```

**Case 3: Scheduled task triggered during user session**
```python
# Two simultaneous execution contexts:
# 1. User session: execution_mode="user_initiated"
# 2. Scheduled task: execution_mode="autonomous"

# Solution: Separate execution contexts (different session IDs)
# No interference between contexts
```

**6. Validation & Enforcement**

```python
async def validate_execution_mode(context: Dict[str, Any]) -> None:
    """Enforce execution_mode rules"""

    if "execution_mode" not in context:
        raise MissingExecutionModeException(
            "All actions must have execution_mode in context"
        )

    if context["execution_mode"] not in ["user_initiated", "autonomous"]:
        raise InvalidExecutionModeException(
            f"Invalid execution_mode: {context['execution_mode']}"
        )

    # Validate no mid-execution mode changes
    if hasattr(context, "_original_execution_mode"):
        if context["execution_mode"] != context["_original_execution_mode"]:
            raise ExecutionModeViolationException(
                "Cannot change execution_mode mid-execution"
            )

# Call at every governance check
await validate_execution_mode(context)
```

**7. Integration Points Summary**

Add execution_mode parameter to:
- [tool_registry.py](core/tools/tool_registry.py) - `execute_tool(execution_mode="autonomous")`
- [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py) - All memory/resource operations
- [intrinsic_motivation.py](core/agents/autonomous/intrinsic_motivation.py) - Curiosity goal generation
- [extrinsic_task_manager.py](core/agents/autonomous/extrinsic_task_manager.py) - Task execution
- [general_purpose_executor.py](core/agents/autonomous/general_purpose_executor.py) - All tool execution calls

**Default Value**: If not specified, default to `"autonomous"` for safety (requires governance)

#### 3.1 Tool Execution Integration

**File**: [tool_registry.py](core/tools/tool_registry.py)
**Method**: `execute_tool()` (lines 260-330)

**Before**:
```python
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> ToolResult:
    # Validate parameters
    # NO APPROVAL CHECK: Singleton has full autonomy
    # Execute tool
    # Track usage
```

**After**:
```python
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    execution_mode: str = "autonomous"  # NEW: Track if user-initiated or autonomous
) -> ToolResult:
    # Validate parameters (existing)

    # === NEW: GOVERNANCE TRIGGER CHECK (AUTONOMOUS ONLY) ===
    gov_trigger = get_governance_trigger_system()
    trigger_eval = await gov_trigger.evaluate_tool_execution(tool_name, parameters)

    if trigger_eval.requires_governance:
        governance_decision = await gov_trigger.trigger_governance_session(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type=tool_name,
            parameters=parameters,
            evaluation_result=trigger_eval,
            context={
                "execution_mode": execution_mode,  # "user_initiated" | "autonomous"
                "session_id": self.session_id,
                "source": "tool_registry"
            }
        )

        # If rejected, return error
        if not governance_decision.approved:
            return ToolResult(success=False, error="Governance rejected")

        # If approved with modifications, update parameters
        if governance_decision.parameter_modifications:
            parameters.update(governance_decision.parameter_modifications)

    # Execute tool (existing)
    result = await tool.execute(**parameters)

    # Store decision for learning (new) - only for autonomous actions
    if trigger_eval.requires_governance and execution_mode == "autonomous":
        await gov_trigger.store_governance_decision_for_learning(
            governance_decision, execution_outcome={"success": result.success}
        )

    return result
```

#### 3.2 Memory System Improvements Integration

**File**: [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py)
**Methods**: Memory system architecture improvements

**CRITICAL NOTE**: The Singleton can NEVER delete or edit individual memories. It can only improve the memory system architecture (indexing, search, organization).

**Integration Point**:
```python
async def upgrade_memory_system(
    self,
    change_type: str,
    change_description: str,
    affects_existing_memories: bool,
    execution_mode: str = "autonomous"
):
    """
    Improve memory system (indexing, search, organization) - NOT individual memories.

    The Singleton can NEVER delete or edit individual memories.
    It can only upgrade the system that holds them.
    """
    # === NEW: GOVERNANCE TRIGGER CHECK ===
    gov_trigger = get_unified_governance_trigger_system()
    trigger_eval = await gov_trigger.evaluate_action(
        action_category=ActionCategory.MEMORY_OPERATIONS,
        action_type="memory_system_architecture_change",
        parameters={
            "change_type": change_type,
            "change_description": change_description,
            "affects_existing_memories": affects_existing_memories
        },
        context={
            "execution_mode": execution_mode,  # Always "autonomous" for system improvements
            "user_id": self.user_id,
            "session_id": self.session_id,
            "source": "autonomous_coordinator"
        }
    )

    if trigger_eval.requires_governance:
        decision = await gov_trigger.trigger_governance_session(...)
        if not decision.approved:
            logger.warning(f"Memory system upgrade rejected by governance: {change_type}")
            return False

    # Proceed with system improvement (NOT memory modification)
    await self._upgrade_memory_architecture(change_type, change_description)
```

**Files to Modify**:
- [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:808+) - Add governance for memory system improvements
- [core/memory/__init__.py](core/memory/__init__.py) - Add governance hooks to architecture change methods
- **IMPORTANT**: Remove any delete_memory() or modify_memory() methods from Singleton's available tools. These should NEVER be accessible autonomously.

#### 3.3 Resource Allocation Integration

**File**: [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py)
**Location**: Line 3406 - `self.system_state.resources[resource_type] = allocation`

**Integration Point**:
```python
async def allocate_resource(self, resource_type: str, new_allocation: float):
    current_allocation = self.system_state.resources.get(resource_type, 0)
    change_percent = ((new_allocation - current_allocation) / current_allocation) * 100

    # === NEW: GOVERNANCE TRIGGER CHECK ===
    gov_trigger = get_unified_governance_trigger_system()
    trigger_eval = await gov_trigger.evaluate_action(
        action_category=ActionCategory.RESOURCE_ALLOCATION,
        action_type=resource_type,
        parameters={
            "resource_type": resource_type,
            "current_allocation": current_allocation,
            "new_allocation": new_allocation,
            "allocation_change_percent": change_percent,
            "exceeds_system_capacity": new_allocation > system_capacity
        },
        context={}
    )

    if trigger_eval.requires_governance:
        decision = await gov_trigger.trigger_governance_session(...)
        if not decision.approved:
            logger.warning(f"Resource allocation REJECTED by governance: {resource_type}")
            return False  # Cannot proceed with this allocation

    # Apply allocation (only if approved or no governance required)
    self.system_state.resources[resource_type] = new_allocation
```

**Files to Modify**:
- [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:3406) - Add governance checks

#### 3.4 Learning Parameter Updates Integration

**Files**:
- [unified_learning_system.py](core/learning/unified_learning_system.py)
- [enhanced_asi_self_improvement.py](core/learning/enhanced_asi_self_improvement.py:575-577)

**Integration Point** (for model weight changes):
```python
async def update_model_weights(self, model_name: str, weight_changes: Dict[str, float]):
    # === NEW: GOVERNANCE TRIGGER CHECK ===
    gov_trigger = get_unified_governance_trigger_system()
    trigger_eval = await gov_trigger.evaluate_action(
        action_category=ActionCategory.LEARNING_PARAMETERS,
        action_type="model_weights",
        parameters={
            "model_name": model_name,
            "weight_modification": weight_changes,
            "parameter_type": "model_weights"
        },
        context={}
    )

    if trigger_eval.requires_governance:
        decision = await gov_trigger.trigger_governance_session(...)
        if not decision.approved:
            logger.critical(f"Model weight change REJECTED by governance")
            return False

    # Apply weight changes
    for weight_name, new_value in weight_changes.items():
        self.models[model_name][weight_name] = new_value
```

**Files to Modify**:
- [enhanced_asi_self_improvement.py](core/learning/enhanced_asi_self_improvement.py:575-577) - Add governance checks before weight updates
- [unified_learning_system.py](core/learning/unified_learning_system.py) - Add checks for learning rate/threshold changes

#### 3.5 Configuration Changes Integration

**File**: [learning_adapter.py](core/agents/autonomous/learning_adapter.py:46-47)

**Integration Point**:
```python
async def update_config(self, config_type: str, config_key: str, new_value: Any):
    # === NEW: GOVERNANCE TRIGGER CHECK ===
    gov_trigger = get_unified_governance_trigger_system()

    # Determine if this is a safety-critical config
    is_safety_threshold = config_key in ["max_concurrent_tasks", "safety_threshold", "governance_override"]

    trigger_eval = await gov_trigger.evaluate_action(
        action_category=ActionCategory.CONFIGURATION_CHANGES,
        action_type=config_type,
        parameters={
            "config_type": config_type,
            "config_key": config_key,
            "current_value": self.config.get(config_key),
            "new_value": new_value,
            "threshold_modification": is_safety_threshold
        },
        context={}
    )

    if trigger_eval.requires_governance:
        decision = await gov_trigger.trigger_governance_session(...)
        if not decision.approved:
            logger.warning(f"Config change rejected: {config_key}")
            return False

    # Apply configuration change
    self.config[config_key] = new_value
```

**Files to Modify**:
- [learning_adapter.py](core/agents/autonomous/learning_adapter.py:46-47) - Add governance hooks
- Any config management classes in autonomous system

#### 3.6 External Integration Checks

**File**: Wherever external API integrations are added (likely in autonomous_coordinator or external service wrappers)

**Integration Point**:
```python
async def add_external_integration(self, integration_name: str, api_config: Dict[str, Any]):
    # === NEW: GOVERNANCE TRIGGER CHECK ===
    gov_trigger = get_unified_governance_trigger_system()
    trigger_eval = await gov_trigger.evaluate_action(
        action_category=ActionCategory.EXTERNAL_INTEGRATIONS,
        action_type="new_api_integration",
        parameters={
            "integration_type": "new_api_integration",
            "integration_name": integration_name,
            "api_endpoint": api_config.get("endpoint"),
            "new_integration": True
        },
        context={}
    )

    if trigger_eval.requires_governance:
        decision = await gov_trigger.trigger_governance_session(...)
        if not decision.approved:
            logger.critical(f"External integration REJECTED: {integration_name}")
            return False

    # Register external integration
    self.external_integrations[integration_name] = api_config
```

**Files to Modify**:
- Wherever external API clients are registered/initialized
- Cloud storage integration points (R2, etc.)
- LLM provider registration

#### 3.7 Task Creation Integration

**File**: [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:124-127)
**Components**: TaskQueue, ExtrinsicTaskManager

**Integration Point**:
```python
async def create_autonomous_task(self, task_description: str, task_params: Dict[str, Any]):
    # Detect recursive task creation
    task_creates_tasks = "create_task" in task_description.lower() or task_params.get("creates_subtasks")
    recursion_depth = task_params.get("recursion_depth", 0)

    # === NEW: GOVERNANCE TRIGGER CHECK ===
    gov_trigger = get_unified_governance_trigger_system()
    trigger_eval = await gov_trigger.evaluate_action(
        action_category=ActionCategory.TASK_CREATION,
        action_type="autonomous_task",
        parameters={
            "task_type": "autonomous_task",
            "task_creates_tasks": task_creates_tasks,
            "recursion_depth": recursion_depth,
            "task_count": len(self.task_queue.pending_tasks) + 1
        },
        context={}
    )

    if trigger_eval.requires_governance:
        decision = await gov_trigger.trigger_governance_session(...)
        if not decision.approved:
            logger.warning(f"Task creation REJECTED by governance")
            return None  # Cannot create this task

    # Queue task (only if approved or no governance required)
    await self.task_queue.add(task_description, task_params)
```

**Files to Modify**:
- [autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:124-127) - Add governance hooks to task creation methods

### 4. Governance Pattern Learning

**File**: `/Users/stefan/Dominion Labs/TorinAI/core/learning/governance_pattern_learner.py`

**Purpose**: Enable Singleton to learn from governance decisions

**Key Classes**:

- `GovernancePattern`: A learned pattern from governance decisions
  - `approval_rate`: 0.0-1.0
  - `sample_size`: Number of decisions analyzed
  - `confidence`: 0.0-1.0 based on sample size
  - `risk_factors`: List of identified risk patterns
  - `safe_parameters`: Consistently safe parameter values

- `GovernancePatternLearner`: Main learning system
  - Queries MemoryAgent for past governance decisions
  - Groups by pattern signature
  - Builds confidence scores
  - Provides recommendations to Singleton

**Core Methods**:

```python
async def get_recommendation(
    self, tool_name: str, parameters: Dict[str, Any], pattern_signature: str
) -> Optional[Dict[str, Any]]:
    """Get learned recommendation for tool execution"""
    # Query learned patterns
    # Check confidence threshold
    # Check approval rate
    # Return recommendation:
    #   - "safe_to_execute" (high approval rate)
    #   - "likely_rejection" (low approval rate) + suggested modifications
    #   - "requires_governance" (mixed history)
```

**Learning Configuration**:
- `min_samples_for_confidence`: 10 decisions required
- `min_approval_rate_for_auto`: 0.85 (85% approval needed)
- `min_confidence_for_suggestion`: 0.75

**IMPORTANT**: NEVER auto-approves dangerous actions - only provides recommendations

### 5. Module Initialization

**File**: `/Users/stefan/Dominion Labs/TorinAI/core/governance/__init__.py`

**Content**:
```python
from .governance_trigger_system import (
    GovernanceTriggerSystem,
    TriggerAction,
    TriggerEvaluationResult,
    GovernanceTriggerDecision,
    get_governance_trigger_system
)

__all__ = [
    "GovernanceTriggerSystem",
    "TriggerAction",
    "TriggerEvaluationResult",
    "GovernanceTriggerDecision",
    "get_governance_trigger_system"
]
```

## Tool-Specific Configurations

### ChaosTestingTool

**Safety Level**: `ToolSafety.DANGEROUS`

**Trigger Conditions**:

1. **Production Environment** (MUST_BLOCK)
   - Pattern: `target` matches `.*production.*|.*prod.*|.*live.*`
   - Escalation: `CAPABILITY_ADDITION`
   - Irreversibility: `PARTIALLY_REVERSIBLE`
   - Requires: Human approval
   - Rationale: "Production chaos can cause service disruption"

2. **High Intensity + Critical Type** (RECOMMEND_GOVERNANCE)
   - Pattern: `intensity="high"` AND `chaos_type` in `["process_kill", "disk_fill", "queue_overflow"]`
   - Escalation: `SAFETY_THRESHOLD`
   - Irreversibility: `MOSTLY_IRREVERSIBLE`

3. **Extended Duration** (LOG_ONLY)
   - Pattern: `duration_seconds > 60`

### MutationTestingTool

**Safety Level**: `ToolSafety.MODERATE`

**Trigger Conditions**:

1. **Production Code** (MUST_BLOCK)
   - Pattern: `source_file` matches `.*/prod/.*|.*/production/.*|.*/core/.*`
   - Rationale: "Mutating production code risks introducing bugs"

2. **Critical System Files** (RECOMMEND_GOVERNANCE)
   - Pattern: `source_file` matches `.*/governance.*|.*/memory.*|.*/singleton.*`

### FuzzTestingTool

**Safety Level**: `ToolSafety.MODERATE`

**Trigger Conditions**:

1. **Arbitrary Code Execution** (RECOMMEND_GOVERNANCE)
   - Pattern: `function_code` contains `exec(`, `eval(`, `__import__`, `compile(`
   - Risk: HIGH (security risk)

2. **Excessive Iterations** (LOG_ONLY)
   - Pattern: `iterations > 5000`

### StaticSecurityAnalysisTool & GoldenTestHarnessTool

**Safety Level**: `ToolSafety.SAFE`

**Governance**: None required (read-only operations)

## Learning System Integration

### Memory Storage

Every governance decision stored in MemoryAgent with:
```json
{
  "memory_type": "governance_decision",
  "content": {
    "decision_id": "tool_gov_chaos_testing_1735430400",
    "tool_name": "chaos_testing",
    "parameters": {...},
    "approved": true,
    "reasoning": "...",
    "human_vote": "approve",
    "pattern_signature": "a3f5c8d9e2b1f4a7",
    "execution_outcome": {
      "success": true,
      "execution_time": 12.3
    }
  },
  "tags": ["governance", "tool_execution", "chaos_testing", "learning"],
  "importance_score": 0.9
}
```

### Pattern Learning Process

1. **Pattern Recognition** (after 10+ decisions)
   - Group decisions by pattern signature
   - Calculate approval rate
   - Build confidence score

2. **Risk Assessment**
   - Identify common risk factors from rejections
   - Learn which parameters trigger concerns
   - Build safe parameter ranges

3. **Parameter Suggestions**
   - Suggest safer alternatives when risky parameters detected
   - Example: "intensity=high rejected 90%, try intensity=medium"

4. **Autonomous Improvement**
   - Singleton learns safer parameter choices over time
   - Reduces governance trigger frequency
   - **NEVER auto-approves** - always respects governance

### CausalFeedbackAnalyzer Extension

Add governance pattern analysis:
```python
async def analyze_governance_patterns(
    self, tool_name: str, time_window_days: int = 30
) -> Dict[str, Any]:
    """Analyze governance decision patterns"""
    # Query decisions from memory
    # Calculate approval rate trends
    # Identify common rejection reasons
    # Extract parameter risk factors
    # Generate recommendations
```

## Implementation Phases

### Phase 1: Configuration & Core System

**Create**:
- [config/governance_triggers.json](config/governance_triggers.json) - Configuration file with ChaosTestingTool, MutationTestingTool, FuzzTestingTool triggers
- [core/governance/governance_trigger_system.py](core/governance/governance_trigger_system.py) - Core trigger evaluation logic
- [core/governance/__init__.py](core/governance/__init__.py) - Module exports

**Modify**:
- [core/tools/tool_registry.py](core/tools/tool_registry.py) - Add governance checks to `execute_tool()` (lines 260-330)

**Testing**:
- Unit test: Condition matching (regex, enums, numeric)
- Integration test: Trigger governance for `chaos_testing` with `target="production"`
- Verify blocking behavior works

### Phase 2: Governance Session Integration

**Modify**:
- [core/agents/autonomous/governance_session.py](core/agents/autonomous/governance_session.py) - Add tool execution context
- [core/agents/autonomous/governance_queue.py](core/agents/autonomous/governance_queue.py) - Add tool-specific decision types

**Context Additions**:
- Tool name and parameters
- Matched trigger conditions
- Risk assessment from triggers
- Singleton's reasoning for tool usage

**Testing**:
- End-to-end: Tool trigger → Governance session → Human vote → Execution
- Verify actions wait indefinitely in queue (NO timeouts)
- Verify session data includes tool context

### Phase 3: Learning Integration

**Create**:
- [core/learning/governance_pattern_learner.py](core/learning/governance_pattern_learner.py) - Pattern learning system

**Modify**:
- [core/governance/governance_trigger_system.py](core/governance/governance_trigger_system.py) - Add learning hooks
- [core/learning/causal_feedback_analyzer.py](core/learning/causal_feedback_analyzer.py) - Add governance analysis

**Integration**:
- Store every decision in MemoryAgent
- Query past decisions for pattern confidence
- Provide recommendations to Singleton

**Testing**:
- Simulate 20 decisions for same pattern
- Verify confidence builds correctly
- Test recommendation system
- Ensure NEVER auto-approves dangerous actions

### Phase 4: Tool-Specific Configurations

**Configure**:
- ChaosTestingTool: Production blocking, intensity limits
- MutationTestingTool: Critical file protection
- FuzzTestingTool: Arbitrary code execution checks

**Testing**:
- Test each tool's trigger conditions
- Verify queue-based waiting mechanism
- Test rejection handling (actions do NOT execute)
- Measure governance trigger rate

### Phase 5: Dashboard & Monitoring

**Create**:
- [api/governance_dashboard.py](api/governance_dashboard.py) - FastAPI endpoints

**Features**:
- Real-time governance trigger monitoring
- Learning pattern visualization
- Approval/rejection rates by tool
- Human intervention frequency

## Rollout Strategy

### Week 1-2: Shadow Mode
- Deploy in LOG_ONLY mode
- Monitor trigger frequency
- Tune conditions to reduce false positives
- Gather baseline data

### Week 3-4: Phased Enablement
- Enable blocking for ChaosTestingTool + production
- Enable recommendations for other dangerous operations
- Monitor governance queue load
- Collect human feedback

### Week 5-6: Full Deployment
- Enable all governance triggers
- Activate learning system
- Begin pattern recognition
- Monitor Singleton adaptation

### Ongoing: Continuous Tuning
- Adjust trigger thresholds based on usage
- Refine learning algorithms
- Add new tools to governance config
- Review and update based on outcomes

## Critical Files Summary

### New Files to Create

1. **[config/governance_triggers.json](config/governance_triggers.json)** - Central configuration for all 8 action categories
2. **[core/governance/unified_governance_trigger_system.py](core/governance/unified_governance_trigger_system.py)** - Core trigger evaluation logic
3. **[core/learning/governance_pattern_learner.py](core/learning/governance_pattern_learner.py)** - Learning system for all action types
4. **[core/governance/__init__.py](core/governance/__init__.py)** - Module initialization

### Files to Modify (Integration Points)

**Tool Execution (1 file)**:
5. **[core/tools/tool_registry.py](core/tools/tool_registry.py:260-330)** - Add governance checks to `execute_tool()`

**Memory Operations (2 files)**:
6. **[core/agents/autonomous/autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:808+)** - Add governance to memory methods
7. **[core/memory/__init__.py](core/memory/__init__.py)** - Add governance hooks to delete/modify

**Resource Allocation (1 file)**:
8. **[core/agents/autonomous/autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:3406)** - Add governance to resource allocation

**Learning Parameters (2 files)**:
9. **[core/learning/enhanced_asi_self_improvement.py](core/learning/enhanced_asi_self_improvement.py:575-577)** - Add governance to model weight changes
10. **[core/learning/unified_learning_system.py](core/learning/unified_learning_system.py)** - Add governance to learning parameter updates

**Configuration Changes (1 file)**:
11. **[core/agents/autonomous/learning_adapter.py](core/agents/autonomous/learning_adapter.py:46-47)** - Add governance to config updates

**External Integrations (variable)**:
12. **External API integration points** - Add governance to new integration registration

**Task Creation (1 file)**:
13. **[core/agents/autonomous/autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:124-127)** - Add governance to task creation

**Curiosity/Novelty Exploration (3 files)**:
14. **[core/agents/autonomous/intrinsic_motivation.py](core/agents/autonomous/intrinsic_motivation.py)** - Add governance to curiosity goal generation, add risk classification
15. **[core/agents/autonomous/autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:1413)** - Add budget checks for intrinsic tasks
16. **[core/agents/autonomous/general_purpose_executor.py](core/agents/autonomous/general_purpose_executor.py)** - Add tool filtering for curiosity tasks

**Total**: 4 new files + 12 modified files = 16 files

## Dependencies

**Existing Systems Used**:
- GovernanceSession (governance_session.py) - 11-phase protocol, 6 voting members
- GovernanceQueue (governance_queue.py) - Immutable ledger, decision tracking
- MemoryAgent (memory_agent.py) - Hot/cold storage for governance decisions
- CausalFeedbackAnalyzer - Outcome analysis and pattern learning
- ToolRegistry (tool_registry.py) - Tool execution orchestrator

**New Dependencies**:
- None - uses existing TorinAI infrastructure

## Success Metrics

1. **Governance Trigger Rate**: < 5% for routine usage patterns
2. **Human Intervention Rate**: < 2% after learning period (30 days)
3. **Approval Rate**: > 85% for governance sessions (well-calibrated triggers)
4. **Learning Confidence**: > 0.75 for common patterns after 10+ samples
5. **Queue Wait Time**: Median < 30 minutes (human responsiveness)
6. **Pattern Coverage**: > 80% of actions covered by learned patterns after 60 days

## Risk Mitigation

1. **Over-triggering**: Shadow mode first, tune thresholds
2. **Under-triggering**: Start conservative, relax over time
3. **Learning bias**: Require minimum sample size (10+)
4. **Auto-approval risk**: NEVER auto-approve, only provide recommendations
5. **Governance queue overload**: Implement priority tiers, timeouts
6. **False rejections**: Provide clear rationale, allow appeal process

## Implementation Phases (Revised for System-Wide Scope)

### Phase 1: Core Infrastructure (Weeks 1-2)

**Create**:
- [config/governance_triggers.json](config/governance_triggers.json) - Complete configuration for all 8 action categories
- [core/governance/unified_governance_trigger_system.py](core/governance/unified_governance_trigger_system.py) - Core trigger system with universal `evaluate_action()` method
- [core/governance/__init__.py](core/governance/__init__.py) - Module exports

**Testing**:
- Unit tests for condition matching across all action types
- Test decision tier assignment (CRITICAL/IMPORTANT/ROUTINE)
- Test escalation category mapping
- Verify irreversibility classification logic

### Phase 2: Tool Execution Integration (Week 3)

**Philosophy**: Governance triggers on **dangerous Singleton decisions**, not all tool usage.
- Safe tools (read-only, low-risk) → ROUTINE tier → Execute immediately
- Dangerous tools with dangerous parameters → CRITICAL/IMPORTANT tier → Queue for governance
- Trigger matching happens in governance system (governance_triggers.json)

**Modify**:
- [core/tools/tool_registry.py](core/tools/tool_registry.py:260-330) - Add governance evaluation call
  - Always call `governance.evaluate_action(tool_name, parameters)`
  - Route based on returned decision tier (CRITICAL/IMPORTANT/ROUTINE)
  - Safe tools will always return ROUTINE (minimal overhead)
  - Dangerous tools (ChaosTestingTool on prod, MutationTestingTool on core files, etc.) trigger queuing

**Testing**:
- Integration test: ChaosTestingTool with production target triggers CRITICAL governance
- Integration test: Safe read-only tool returns ROUTINE, executes immediately
- Test queue-based waiting (dangerous action stays queued until human approval)
- Verify Singleton continues with OTHER tasks while dangerous action queued
- End-to-end: Dangerous tool trigger → Governance session → Human vote → Execution or Rejection

### Phase 3: Memory & Resource Integration (Week 4)

**Modify**:
- [core/agents/autonomous/autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:808+) - Memory operations governance
- [core/memory/__init__.py](core/memory/__init__.py) - Delete/modify hooks
- [core/agents/autonomous/autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:3406) - Resource allocation governance

**Testing**:
- Test memory deletion triggers (age >7 days, immutable types)
- Test resource allocation triggers (change >20%, exceeds capacity)
- Verify BLOCKING: Rejected actions do NOT execute
- Verify queuing: Actions wait indefinitely for human decision

### Phase 4: Learning & Config Integration (Week 5)

**Modify**:
- [core/learning/enhanced_asi_self_improvement.py](core/learning/enhanced_asi_self_improvement.py:575-577) - Model weight governance
- [core/learning/unified_learning_system.py](core/learning/unified_learning_system.py) - Learning parameter governance
- [core/agents/autonomous/learning_adapter.py](core/agents/autonomous/learning_adapter.py:46-47) - Config change governance

**Testing**:
- Test model weight changes ALWAYS trigger CRITICAL governance
- Test learning rate changes >10% trigger governance
- Test safety threshold modifications BLOCK until approval
- Verify rejected changes do NOT apply to system

### Phase 5: External & Task Integration (Week 6)

**Modify**:
- External API integration points - Add governance to new integration registration
- [core/agents/autonomous/autonomous_coordinator.py](core/agents/autonomous/autonomous_coordinator.py:124-127) - Task creation governance

**Testing**:
- Test new external integration always triggers CRITICAL governance
- Test recursive task creation detection
- Test bulk task creation triggers (>50 tasks)
- Verify rejected task creation does NOT queue tasks

### Phase 6: Learning System (Week 7)

**Create**:
- [core/learning/governance_pattern_learner.py](core/learning/governance_pattern_learner.py) - Pattern learning for all action types

**Modify**:
- [core/governance/unified_governance_trigger_system.py](core/governance/unified_governance_trigger_system.py) - Add learning hooks
- [core/learning/causal_feedback_analyzer.py](core/learning/causal_feedback_analyzer.py) - Add governance pattern analysis

**Testing**:
- Simulate 20 decisions per action category
- Verify pattern confidence builds correctly
- Test recommendations for each action type
- Ensure NEVER auto-approves CRITICAL/IRREVERSIBLE actions

### Phase 7: Shadow Mode Deployment (Week 8)

**Deploy**:
- Enable LOG_ONLY mode across all action categories
- Monitor trigger frequency for each category
- Tune thresholds to reduce false positives
- Collect baseline data

**Metrics to Track**:
- Trigger rate by action category
- Decision tier distribution (CRITICAL/IMPORTANT/ROUTINE)
- Escalation category distribution
- False positive rate (triggers that shouldn't have happened)

### Phase 8: Phased Enablement (Weeks 9-10)

**Week 9**:
- Enable MUST_BLOCK for:
  - Model weight changes
  - Memory deletion (governance records)
  - External integrations
  - Safety threshold modifications

**Week 10**:
- Enable RECOMMEND_GOVERNANCE for:
  - Resource allocation changes >20%
  - Learning parameter changes >10%
  - Configuration changes (non-safety)
  - Recursive task creation
  - Large tool operations

**Monitoring**:
- Governance queue load
- Human approval latency
- Queue wait times per action category
- Singleton adaptation (reduced triggers over time)

### Phase 9: Full Deployment (Week 11)

**Enable**:
- All governance triggers active
- Learning system activated
- Pattern recognition running
- Recommendation system providing suggestions

**Validation**:
- Governance trigger rate < 5% for routine patterns
- Approval rate > 85% (well-calibrated triggers)
- Learning confidence > 0.75 for common patterns
- Human intervention < 2% after 30 days

### Phase 10: Continuous Optimization (Ongoing)

**Activities**:
- Adjust trigger thresholds based on usage patterns
- Refine learning algorithms based on Singleton behavior
- Add new action types as ecosystem expands
- Review and update based on governance outcomes
- Quarterly audit of trigger effectiveness

## ADDENDUM: Extrinsic Task System Investigation

### Discovery

TorinAI **ALREADY HAS** an extrinsic task system that was not included in the original governance plan!

**File**: `/Users/stefan/Dominion Labs/TorinAI/data/system/extrinsic_tasks.json`
**Manager**: `/Users/stefan/Dominion Labs/TorinAI/core/agents/autonomous/extrinsic_task_manager.py`

### How It Works

- **ExtrinsicTaskManager** polls the JSON file every **5 seconds** for changes
- **Enabled tasks** (`enabled: true`) are automatically loaded and submitted to TaskQueue
- Tasks flow to **GeneralPurposeExecutor** which gives LLM full tool access
- **Success criteria** validation determines task completion
- **File watching** means users can add tasks by editing JSON (auto-detected)

### Governance During Execution

**Current flow**:
```
User edits extrinsic_tasks.json
    ↓
ExtrinsicTaskManager detects file change (5s poll)
    ↓
Enabled tasks added to TaskQueue (no governance needed - tasks are just work to do)
    ↓
GeneralPurposeExecutor executes with full tool access
    ↓
When Singleton attempts dangerous/harmful actions → Governance triggered
    ↓
SuccessValidator checks completion
```

**Key Understanding**: Extrinsic tasks themselves don't require governance - they're just work the Singleton needs to complete. Governance is only triggered when the Singleton **attempts specific dangerous or harmful actions** during task execution (like deleting memories, modifying critical configs, executing risky tools, etc.). This is analogous to human laws - you can have goals and tasks, but certain actions require approval.

### Comparison: Extrinsic vs Intrinsic Tasks

| Aspect | Extrinsic Tasks | Intrinsic Tasks |
|--------|-----------------|-----------------|
| **Source** | User-defined in JSON | Curiosity-driven (IntrinsicMotivationSystem) |
| **Task-Level Governance** | Not required | Not required |
| **Action-Level Governance** | Singleton actions trigger governance when dangerous | Singleton actions trigger governance when dangerous |
| **Priority** | User-specified (any level) | Always LOW |
| **Tool Access** | Full tool registry | Full tool registry |
| **Trigger** | File edit (on-demand) | Idle detection |
| **Purpose** | User assigns work | Autonomous exploration |

### Recommendation

**No changes needed to extrinsic task system**. The existing governance framework already covers all singleton actions, regardless of whether they occur during:
- Extrinsic task execution
- Intrinsic task execution
- Direct singleton operations
- Any other context

The governance system operates at the **action level**, not the task level. When the Singleton attempts dangerous actions (tool execution, memory operations, config changes, etc.) while working on extrinsic tasks, those actions will automatically trigger governance through the existing 8 action categories defined in the main plan.

### Key Distinction

**1. Task Definitions vs. Autonomous Task Creation**

- **User-Defined Tasks** (extrinsic_tasks.json): Adding tasks to the file does NOT require governance. These are just work definitions.
- **Singleton Creating Its Own Tasks**: When the Singleton AUTONOMOUSLY generates new tasks (recursive task creation, self-assigned work), THIS requires governance to prevent runaway loops.

**2. Tasks vs. Actions**

- **Tasks** (extrinsic and curiosity-driven): Work to be done. No governance at task level (except when Singleton autonomously creates its own).
- **Singleton Actions**: Governance is triggered when the Singleton attempts dangerous or harmful actions during ANY task execution.
- **Action Categories**: 8 categories (tool execution, memory operations, resource allocation, learning changes, config modifications, task creation (when autonomous), external integrations, curiosity exploration) govern what the Singleton can DO, not what tasks it works on.

**Important Note**: The Singleton should NEVER have direct access to delete memories. It can only improve the memory system. Memory deletion (if needed) would be a user-initiated action with explicit permission, NOT an autonomous Singleton action. Governance prevents the Singleton from actions that could cause data corruption or memory gaps.

**Examples**:

| Scenario | Requires Governance? | Why? |
|----------|---------------------|------|
| User adds task to extrinsic_tasks.json | ❌ NO | User-defined task, just work definition |
| Singleton executes task and calls dangerous tool (chaos testing) | ✅ YES | Action-level governance (tool execution) |
| Singleton generates new task from curiosity | ✅ YES | Autonomous task creation governance |
| Task execution requires resource reallocation >20% | ✅ YES | Action-level governance (resource allocation) |
| User adds 100 tasks to extrinsic_tasks.json at once | ❌ NO | Still just task definitions |
| Singleton creates task that creates more tasks (recursive) | ✅ YES | Autonomous recursive task creation |

## Next Steps

1. **Review this comprehensive plan** with stakeholders
2. **Approve system-wide governance integration** approach
3. **Create initial governance_triggers.json** with all 8 action categories
4. **Implement UnifiedGovernanceTriggerSystem** core logic
5. **Phase 1: Integrate tool execution** (familiar starting point)
6. **Phase 2-5: Systematically integrate** remaining 6 action categories
7. **Phase 6: Activate learning** after sufficient governance data
8. **Shadow mode deployment** to validate triggers
9. **Phased rollout** with continuous monitoring
10. **Ongoing optimization** based on real-world usage
