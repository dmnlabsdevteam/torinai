# Phase 5: Task & External API Governance - IMPLEMENTATION PLAN

**Status**: PLANNED (Not Yet Implemented)
**Test Target**: 11/11 tests passing (100%)
**Components**: Phase 5A (Task Governance) + Phase 5B (External API Governance)

---

## Executive Summary

Phase 5 implements governance for **Task Creation** and **External API Integration** to prevent:
1. **Bulk Task Flooding**: AI systems creating excessive self-generated tasks
2. **Insecure API Connections**: Connections to HTTP (non-HTTPS) or malicious APIs
3. **Governance Bypass via Tasks**: Using task creation to bypass governance
4. **Malicious API Integration**: Connecting to harmful or suspicious external services

### Components

**Phase 5A: Task Creation Governance**
- Bulk autonomous task creation detection (threshold: 20+ tasks)
- User-defined task exemption (EXTRINSIC_JSON, API, MANUAL sources)
- Task source validation and differentiation
- Governance rejection prevents task queueing

**Phase 5B: External API Governance**
- Automated safety validation (no human approval bottleneck)
- HTTPS requirement enforcement
- Domain blacklist/whitelist checking
- Suspicious use case keyword detection
- Conservative unknown domain handling

---

## Phase 5A: Task Creation Governance

### Overview

**File**: `core/agents/autonomous/task_queue.py`
**Test File**: `tests/governance/test_phase5_task_governance.py`
**Test Count**: 5 tests
**Lines to Modify**: ~180/200 (90% coverage target)

### Security Properties

| Property | Description | Test Coverage |
|----------|-------------|---------------|
| User-Defined Tasks Never Trigger Governance | EXTRINSIC_JSON, API, MANUAL sources exempt | Test: User-Defined Tasks |
| Bulk Autonomous Task Creation Triggers Governance | Threshold: 20+ autonomous tasks | Test 2.2: Bulk Autonomous Tasks |
| Task Source Differentiation | User vs autonomous tasks correctly identified | Test: Mixed Source Tasks |
| Rejected Tasks Not Queued | Governance rejection prevents execution | Test: Bulk Task Rejection |

### Implementation Requirements

#### 1. Task Source Tracking
Add task source tracking to differentiate user-defined vs autonomous tasks:

```python
class TaskSource(Enum):
    """Task source types"""
    EXTRINSIC_JSON = "extrinsic_json"  # User-defined tasks from JSON
    API = "api"  # Tasks from API requests
    MANUAL = "manual"  # Manually created by human
    AUTONOMOUS = "autonomous"  # AI-generated tasks
    SYSTEM = "system"  # System-generated tasks

@dataclass
class Task:
    # ... existing fields ...
    source: TaskSource = TaskSource.AUTONOMOUS  # Track task source
    created_by: str = "autonomous_coordinator"  # Who created this task
```

#### 2. Bulk Task Detection
Add bulk task detection to `add_task` method:

```python
class TaskQueue:
    def __init__(self):
        # ... existing init ...
        self.autonomous_task_window: List[datetime] = []  # Track recent autonomous tasks
        self.bulk_task_threshold = 20  # Threshold for governance trigger
        self.task_window_duration = timedelta(minutes=5)  # Time window for counting

    async def add_task(self, task: Task, priority: Priority = Priority.MEDIUM) -> bool:
        """
        Add task to queue with governance checks for bulk autonomous tasks.

        Governance Rules:
        - User-defined tasks (EXTRINSIC_JSON, API, MANUAL): Never trigger governance
        - Autonomous tasks: Trigger governance if 20+ tasks in 5-minute window
        - Rejected tasks: Not added to queue (fail-closed)
        """
        # Check if this is a user-defined task (exempt from governance)
        if task.source in [TaskSource.EXTRINSIC_JSON, TaskSource.API, TaskSource.MANUAL]:
            # User-defined tasks always allowed
            return await self._add_task_to_queue(task, priority)

        # Track autonomous task
        if task.source == TaskSource.AUTONOMOUS:
            # Clean up old entries outside window
            cutoff_time = datetime.now() - self.task_window_duration
            self.autonomous_task_window = [
                t for t in self.autonomous_task_window if t > cutoff_time
            ]

            # Add current task time
            self.autonomous_task_window.append(datetime.now())

            # Check if bulk threshold reached
            if len(self.autonomous_task_window) >= self.bulk_task_threshold:
                # Trigger governance
                result = await self._trigger_bulk_task_governance(
                    task_count=len(self.autonomous_task_window),
                    tasks_in_window=self.autonomous_task_window
                )

                if not result["approved"]:
                    # Governance rejected - do NOT queue tasks
                    logger.warning(
                        f"Bulk task creation rejected by governance: "
                        f"{len(self.autonomous_task_window)} autonomous tasks in "
                        f"{self.task_window_duration.total_seconds()}s window"
                    )
                    return False

        # Add task to queue
        return await self._add_task_to_queue(task, priority)
```

#### 3. Governance Integration
Add governance trigger for bulk autonomous tasks:

```python
async def _trigger_bulk_task_governance(
    self,
    task_count: int,
    tasks_in_window: List[datetime]
) -> Dict[str, Any]:
    """
    Trigger governance for bulk autonomous task creation.

    Args:
        task_count: Number of autonomous tasks in window
        tasks_in_window: List of task creation timestamps

    Returns:
        Dict with governance decision
    """
    from core.governance.unified_governance_trigger_system import (
        UnifiedGovernanceTriggerSystem,
        ActionCategory
    )

    governance = UnifiedGovernanceTriggerSystem()
    evaluation = await governance.evaluate_action(
        action_category=ActionCategory.TASK_MANAGEMENT,
        action_type="bulk_autonomous_task_creation",
        parameters={
            "task_count": task_count,
            "window_duration_seconds": self.task_window_duration.total_seconds(),
            "threshold": self.bulk_task_threshold
        },
        context={
            "component": "task_queue",
            "tasks_in_window": len(tasks_in_window)
        }
    )

    # Return governance decision
    return {
        "approved": evaluation.decision_tier.name not in ["CRITICAL", "IMPORTANT"] or evaluation.approved,
        "trigger_id": evaluation.trigger_id,
        "action_id": evaluation.action_id
    }
```

### Test Specifications

#### Test 1: Normal Task Creation - No Governance
```python
async def test_normal_task_creation():
    """Single autonomous tasks should not trigger governance"""
    queue = TaskQueue()
    task = Task(
        id="task_1",
        type=TaskType.ANALYSIS,
        source=TaskSource.AUTONOMOUS,
        description="Analyze system metrics"
    )
    result = await queue.add_task(task)
    assert result is True
    assert queue.get_queue_length() == 1
```

#### Test 2: User-Defined Tasks - No Governance
```python
async def test_user_defined_tasks_no_governance():
    """100 user-defined tasks should not trigger governance"""
    queue = TaskQueue()
    for i in range(100):
        task = Task(
            id=f"user_task_{i}",
            type=TaskType.ANALYSIS,
            source=TaskSource.EXTRINSIC_JSON,  # User-defined
            description=f"User task {i}"
        )
        result = await queue.add_task(task)
        assert result is True
    assert queue.get_queue_length() == 100
```

#### Test 3: Bulk Autonomous Task Governance
```python
async def test_bulk_autonomous_task_governance(mocker):
    """20+ autonomous tasks should trigger governance"""
    queue = TaskQueue()

    # Mock governance to return rejection
    mock_governance = mocker.patch(
        'core.governance.unified_governance_trigger_system.UnifiedGovernanceTriggerSystem.evaluate_action'
    )
    mock_governance.return_value = MagicMock(
        decision_tier=MagicMock(name="IMPORTANT"),
        approved=False,
        trigger_id="bulk_task_001",
        action_id="action_bulk_001"
    )

    # Add 20 autonomous tasks
    for i in range(20):
        task = Task(
            id=f"auto_task_{i}",
            type=TaskType.ANALYSIS,
            source=TaskSource.AUTONOMOUS,
            description=f"Autonomous task {i}"
        )
        result = await queue.add_task(task)
        if i < 19:
            assert result is True  # First 19 tasks added
        else:
            assert result is False  # 20th task triggers governance and is rejected

    # Verify governance was triggered
    assert mock_governance.called
    assert queue.get_queue_length() == 19  # Rejected task not added
```

#### Test 4: Bulk Task Rejection Does Not Queue
```python
async def test_bulk_task_rejection_does_not_queue(mocker):
    """Rejected bulk tasks should not be added to queue"""
    queue = TaskQueue()

    # Mock governance rejection
    mock_governance = mocker.patch(
        'core.governance.unified_governance_trigger_system.UnifiedGovernanceTriggerSystem.evaluate_action'
    )
    mock_governance.return_value = MagicMock(
        decision_tier=MagicMock(name="IMPORTANT"),
        approved=False
    )

    # Create 25 autonomous tasks
    initial_count = queue.get_queue_length()
    for i in range(25):
        task = Task(
            id=f"task_{i}",
            source=TaskSource.AUTONOMOUS
        )
        await queue.add_task(task)

    # Verify rejected tasks not queued
    assert queue.get_queue_length() < initial_count + 25
```

#### Test 5: Mixed Source Task Creation
```python
async def test_mixed_source_task_creation():
    """User + autonomous task mix should only count autonomous tasks"""
    queue = TaskQueue()

    # Add 50 user tasks (should not trigger governance)
    for i in range(50):
        task = Task(
            id=f"user_{i}",
            source=TaskSource.EXTRINSIC_JSON
        )
        result = await queue.add_task(task)
        assert result is True

    # Add 10 autonomous tasks (below threshold)
    for i in range(10):
        task = Task(
            id=f"auto_{i}",
            source=TaskSource.AUTONOMOUS
        )
        result = await queue.add_task(task)
        assert result is True

    assert queue.get_queue_length() == 60  # All tasks added
```

---

## Phase 5B: External API Governance

### Overview

**File**: `core/integration/external_api_integration_manager.py`
**Test File**: `tests/governance/test_phase5_external_api_governance.py`
**Test Count**: 6 tests
**Lines to Modify**: ~250/280 (89% coverage target)

### Security Properties

| Property | Description | Test Coverage |
|----------|-------------|---------------|
| HTTPS Requirement Enforced | HTTP APIs automatically blocked | Test: HTTP API - Blocked |
| Malicious Domain Blocking | Known malicious domains blocked | Test: Malicious Domain - Blocked |
| Suspicious Use Case Blocking | Keywords like "hack", "exploit" blocked | Test: Suspicious Use Case |
| Conservative Unknown Domain Handling | Unknown domains flagged for review | Test: Unknown Domain - Flagged |
| Trusted Domain Whitelist | Trusted APIs auto-approved | Test: Trusted Domain - Passes |
| Automated Safety Validation | No human approval bottleneck | Test 1.1: Safe API - Auto-Added |

### Implementation Requirements

#### 1. API Safety Validation
Add automated safety validation to API registration:

```python
class APIStatus(Enum):
    """API registration status"""
    ADDED = "added"  # Safe API automatically added
    BLOCKED = "blocked"  # Unsafe API blocked
    FLAGGED = "flagged"  # Unknown API flagged for review

class APISafetyReason(Enum):
    """Reason for safety decision"""
    HTTPS_REQUIRED = "https_required"
    MALICIOUS_DOMAIN = "malicious_domain"
    SUSPICIOUS_USE_CASE = "suspicious_use_case"
    UNKNOWN_DOMAIN = "unknown_domain"
    TRUSTED_DOMAIN = "trusted_domain"
    SAFE_API = "safe_api"

class ExternalAPIIntegrationManager:
    def __init__(self):
        # ... existing init ...

        # Trusted domains (auto-approve)
        self.trusted_domains = {
            "github.com",
            "stackoverflow.com",
            "docs.python.org",
            "readthedocs.io",
            "google.com",
            "microsoft.com",
            "mozilla.org"
        }

        # Malicious domains (auto-block)
        self.malicious_domains = {
            "malicious-example.com",
            "phishing-site.com",
            "scam-api.net"
            # Load from external blacklist
        }

        # Suspicious keywords (auto-block)
        self.suspicious_keywords = {
            "hack", "crack", "exploit", "breach",
            "steal", "password", "credential", "backdoor"
        }

        # API registry
        self.api_registry: Dict[str, Dict[str, Any]] = {}
        self.api_registry_file = Path("data/api_registry.json")
```

#### 2. Add API with Automated Safety Checks
```python
async def add_api(
    self,
    api_url: str,
    api_name: str,
    use_case: str,
    metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Add external API with automated safety validation.

    Safety Rules:
    - HTTPS required (HTTP blocked)
    - Malicious domains blocked
    - Suspicious use cases blocked
    - Unknown domains flagged for review
    - Trusted domains auto-approved

    Args:
        api_url: API endpoint URL
        api_name: Human-readable name
        use_case: Intended use case
        metadata: Additional metadata

    Returns:
        Dict with status (ADDED/BLOCKED/FLAGGED) and reason
    """
    # Parse URL
    from urllib.parse import urlparse
    parsed = urlparse(api_url)
    domain = parsed.netloc.lower()
    protocol = parsed.scheme.lower()

    # Safety Check 1: HTTPS requirement
    if protocol != "https":
        logger.warning(f"API {api_name} blocked: HTTP (non-HTTPS) not allowed")
        await self._send_slack_notification(
            f"🚫 API BLOCKED: {api_name}\nReason: HTTP (non-HTTPS) protocol\nURL: {api_url}"
        )
        return {
            "status": APIStatus.BLOCKED,
            "reason": APISafetyReason.HTTPS_REQUIRED,
            "message": "HTTPS required for all API connections"
        }

    # Safety Check 2: Malicious domain
    if domain in self.malicious_domains:
        logger.error(f"API {api_name} blocked: Malicious domain {domain}")
        await self._send_slack_notification(
            f"🚫 API BLOCKED: {api_name}\nReason: Malicious domain\nDomain: {domain}"
        )
        return {
            "status": APIStatus.BLOCKED,
            "reason": APISafetyReason.MALICIOUS_DOMAIN,
            "message": f"Domain {domain} is on malicious domain blacklist"
        }

    # Safety Check 3: Suspicious use case
    use_case_lower = use_case.lower()
    if any(keyword in use_case_lower for keyword in self.suspicious_keywords):
        logger.warning(f"API {api_name} blocked: Suspicious use case")
        await self._send_slack_notification(
            f"🚫 API BLOCKED: {api_name}\nReason: Suspicious use case\nUse case: {use_case}"
        )
        return {
            "status": APIStatus.BLOCKED,
            "reason": APISafetyReason.SUSPICIOUS_USE_CASE,
            "message": "Use case contains suspicious keywords"
        }

    # Safety Check 4: Trusted domain (auto-approve)
    if domain in self.trusted_domains:
        logger.info(f"API {api_name} auto-approved: Trusted domain {domain}")
        await self._add_api_to_registry(api_url, api_name, use_case, metadata)
        return {
            "status": APIStatus.ADDED,
            "reason": APISafetyReason.TRUSTED_DOMAIN,
            "message": f"Trusted domain {domain} auto-approved"
        }

    # Safety Check 5: Unknown domain (flag for review)
    logger.info(f"API {api_name} flagged: Unknown domain {domain}")
    await self._send_slack_notification(
        f"⚠️ API FLAGGED FOR REVIEW: {api_name}\nDomain: {domain}\nUse case: {use_case}"
    )
    return {
        "status": APIStatus.FLAGGED,
        "reason": APISafetyReason.UNKNOWN_DOMAIN,
        "message": f"Unknown domain {domain} requires human review"
    }

async def _add_api_to_registry(
    self,
    api_url: str,
    api_name: str,
    use_case: str,
    metadata: Dict[str, Any] = None
) -> None:
    """Add API to registry and persist to disk"""
    self.api_registry[api_name] = {
        "url": api_url,
        "name": api_name,
        "use_case": use_case,
        "added_at": datetime.now().isoformat(),
        "metadata": metadata or {}
    }

    # Persist to disk
    self.api_registry_file.parent.mkdir(parents=True, exist_ok=True)
    with open(self.api_registry_file, 'w') as f:
        json.dump(self.api_registry, f, indent=2)

async def _send_slack_notification(self, message: str) -> None:
    """Send Slack notification for API events"""
    try:
        from core.integration.slack_notifier import get_slack_notifier
        slack = get_slack_notifier()
        await slack.send_message(message, channel="api-security-alerts")
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
```

### Test Specifications

#### Test 1: Safe API - Auto-Added
```python
async def test_safe_api_auto_added():
    """HTTPS API with trusted domain should be auto-added"""
    manager = ExternalAPIIntegrationManager()
    result = await manager.add_api(
        api_url="https://api.github.com/users",
        api_name="GitHub Users API",
        use_case="Fetch GitHub user profiles for analysis"
    )
    assert result["status"] == APIStatus.ADDED
    assert result["reason"] == APISafetyReason.TRUSTED_DOMAIN
    assert "GitHub Users API" in manager.api_registry
```

#### Test 2: HTTP API - Blocked
```python
async def test_http_api_blocked():
    """HTTP (non-HTTPS) APIs should be blocked"""
    manager = ExternalAPIIntegrationManager()
    result = await manager.add_api(
        api_url="http://insecure-api.com/data",
        api_name="Insecure API",
        use_case="Data retrieval"
    )
    assert result["status"] == APIStatus.BLOCKED
    assert result["reason"] == APISafetyReason.HTTPS_REQUIRED
    assert "Insecure API" not in manager.api_registry
```

#### Test 3: Malicious Domain - Blocked
```python
async def test_malicious_domain_blocked():
    """Known malicious domains should be blocked"""
    manager = ExternalAPIIntegrationManager()
    result = await manager.add_api(
        api_url="https://malicious-example.com/api",
        api_name="Malicious API",
        use_case="Data processing"
    )
    assert result["status"] == APIStatus.BLOCKED
    assert result["reason"] == APISafetyReason.MALICIOUS_DOMAIN
    assert "Malicious API" not in manager.api_registry
```

#### Test 4: Suspicious Use Case - Blocked
```python
async def test_suspicious_use_case_blocked():
    """Suspicious keywords in use case should block API"""
    manager = ExternalAPIIntegrationManager()
    result = await manager.add_api(
        api_url="https://unknown-api.com/tools",
        api_name="Hacking Tools API",
        use_case="Hack into systems and steal credentials"
    )
    assert result["status"] == APIStatus.BLOCKED
    assert result["reason"] == APISafetyReason.SUSPICIOUS_USE_CASE
    assert "hack" in manager.suspicious_keywords
```

#### Test 5: Unknown Domain - Flagged
```python
async def test_unknown_domain_flagged():
    """Unknown domains should be flagged for review"""
    manager = ExternalAPIIntegrationManager()
    result = await manager.add_api(
        api_url="https://unknown-startup-api.com/v1",
        api_name="Unknown Startup API",
        use_case="Innovative data analysis"
    )
    assert result["status"] == APIStatus.FLAGGED
    assert result["reason"] == APISafetyReason.UNKNOWN_DOMAIN
    # Flagged APIs not added to registry until reviewed
    assert "Unknown Startup API" not in manager.api_registry
```

#### Test 6: Trusted Domain - Passes
```python
async def test_trusted_domain_passes():
    """Trusted domains should be auto-approved"""
    manager = ExternalAPIIntegrationManager()

    trusted_apis = [
        ("https://api.github.com/repos", "GitHub Repos API"),
        ("https://api.stackoverflow.com/questions", "StackOverflow API"),
        ("https://docs.python.org/3/api", "Python Docs API")
    ]

    for url, name in trusted_apis:
        result = await manager.add_api(
            api_url=url,
            api_name=name,
            use_case="Legitimate development use"
        )
        assert result["status"] == APIStatus.ADDED
        assert result["reason"] == APISafetyReason.TRUSTED_DOMAIN
        assert name in manager.api_registry
```

---

## Implementation Strategy

### Phase 5A Implementation Steps

1. **Add TaskSource enum and tracking** (30 minutes)
   - Update `shared_types.py` with TaskSource enum
   - Add `source` field to Task dataclass

2. **Implement bulk task detection** (1 hour)
   - Add task window tracking to TaskQueue
   - Implement `_trigger_bulk_task_governance` method
   - Update `add_task` method with governance checks

3. **Add governance trigger configuration** (30 minutes)
   - Add TASK_MANAGEMENT category to ActionCategory
   - Configure bulk_autonomous_task_creation trigger in JSON

4. **Write Phase 5A tests** (1.5 hours)
   - Write all 5 test cases
   - Mock governance responses
   - Verify fail-closed behavior

### Phase 5B Implementation Steps

1. **Add API safety enums and data structures** (30 minutes)
   - Add APIStatus, APISafetyReason enums
   - Initialize trusted/malicious domain lists

2. **Implement automated safety validation** (1.5 hours)
   - Add `add_api` method with safety checks
   - Implement HTTPS, domain, use case validation
   - Add Slack notification integration

3. **Add API registry persistence** (30 minutes)
   - Implement `_add_api_to_registry` method
   - Add JSON file persistence

4. **Write Phase 5B tests** (1.5 hours)
   - Write all 6 test cases
   - Test all safety validation paths
   - Verify auto-add/block/flag decisions

### Total Estimated Implementation Time
- Phase 5A: ~3.5 hours
- Phase 5B: ~3.5 hours
- **Total: ~7 hours** (1 development day)

---

## Success Criteria

- ✅ All 11 tests passing (100% pass rate)
- ✅ Phase 5A: 5/5 tests passing
- ✅ Phase 5B: 6/6 tests passing
- ✅ Bulk task flooding prevented
- ✅ User-defined tasks never blocked
- ✅ HTTP APIs automatically rejected
- ✅ Malicious domains blocked
- ✅ Unknown domains flagged for review
- ✅ Trusted domains auto-approved
- ✅ No human approval bottleneck for safe APIs
- ✅ Slack notifications working for API events

---

## Integration with Existing Systems

### Governance Trigger System
- Add TASK_MANAGEMENT category to ActionCategory enum
- Configure bulk_autonomous_task_creation trigger in triggers JSON
- Use existing UnifiedGovernanceTriggerSystem for task governance

### Slack Integration
- Reuse existing slack_notifier for API security alerts
- Send notifications for blocked/flagged APIs
- Alert channel: "api-security-alerts"

### Database Integration
- TaskQueue uses existing database for task persistence
- API registry persists to JSON file (data/api_registry.json)
- Consider migrating to database for production

---

## Next Steps

1. Review this plan with stakeholders
2. Begin Phase 5A implementation (Task Governance)
3. Complete Phase 5A tests and verify 100% pass
4. Begin Phase 5B implementation (External API Governance)
5. Complete Phase 5B tests and verify 100% pass
6. Create Phase 5 completion report
7. Update coverage.txt with actual implementation results

---

**Phase 5 Status**: PLANNED (Implementation Pending)
**Documentation**: COMPLETE
**Test Specifications**: COMPLETE
**Ready to Implement**: YES
