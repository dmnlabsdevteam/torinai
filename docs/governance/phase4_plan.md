# Phase 4: Decision Queue & Approval Workflow - Implementation Plan

**Status**: 📋 PLANNING
**Phase**: 4 of 6
**Dependencies**: Phase 3 Complete (100% test success)
**Estimated Duration**: 8-10 hours
**Target**: User-facing governance decision management system

---

## Executive Summary

Phase 4 builds the user-facing decision queue and approval workflow system, enabling human oversight of CRITICAL tier governance decisions and visibility into IMPORTANT tier notifications. This closes the governance loop by providing users with the tools to review, approve, deny, or defer actions that have been queued by the governance system.

**Key Deliverable**: A complete decision queue system with MySQL persistence, API endpoints, frontend UI, and notification infrastructure.

---

## Goals

### Primary Goals

1. **Decision Queue Backend**
   - MySQL-backed persistent queue
   - Session-based decision tracking
   - Auto-expiration after configurable timeout
   - Batch operations support

2. **API Endpoints**
   - List queued decisions (with filtering)
   - Get decision details
   - Approve/deny/defer actions
   - Batch approve/deny
   - Get pending count

3. **Frontend UI**
   - Decision list view (table/card format)
   - Decision detail modal
   - Approve/deny/defer buttons
   - Batch selection and operations
   - Real-time updates (WebSocket)

4. **Notification System**
   - IMPORTANT tier notifications (non-blocking)
   - Email integration (SendGrid/SMTP)
   - Slack integration (webhook)
   - Dashboard widget (pending count badge)

5. **Audit Trail Enhancement**
   - Link decisions to original autonomous operations
   - Track approval/denial timestamps and reasons
   - Generate compliance reports
   - Export to CSV/JSON

### Secondary Goals

6. **User Experience**
   - Search and filter decisions
   - Sort by date, priority, category
   - Decision history view
   - Mobile-responsive UI

7. **Security**
   - Role-based access control (admin/viewer)
   - Decision approval signatures
   - Audit log immutability
   - Rate limiting on API endpoints

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React/Vue)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Decision     │  │ Notification │  │ Audit Trail  │      │
│  │ Queue View   │  │ Widget       │  │ View         │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │ WebSocket + REST API
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  Decision Queue API Layer                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Queue        │  │ Notification │  │ Audit Trail  │      │
│  │ Manager      │  │ Service      │  │ Service      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  MySQL Database Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ governance_  │  │ governance_  │  │ governance_  │      │
│  │ decisions    │  │ notifications│  │ audit_log    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              External Notification Services                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Email        │  │ Slack        │  │ WebSocket    │      │
│  │ (SendGrid)   │  │ (Webhook)    │  │ (Internal)   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### Table 1: `governance_decisions`

Stores all queued governance decisions (CRITICAL tier).

```sql
CREATE TABLE governance_decisions (
    -- Primary key
    decision_id VARCHAR(36) PRIMARY KEY,  -- UUID

    -- Decision metadata
    trigger_id VARCHAR(50) NOT NULL,
    action_category VARCHAR(50) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    decision_tier VARCHAR(20) NOT NULL,  -- CRITICAL, IMPORTANT, ROUTINE

    -- Action context
    parameters JSON NOT NULL,  -- Original action parameters
    evaluation_result JSON NOT NULL,  -- Full governance evaluation
    action_context JSON,  -- Additional context (session, user, etc.)

    -- Status tracking
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',  -- PENDING, APPROVED, DENIED, DEFERRED, EXPIRED
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,  -- Auto-deny after this time

    -- Resolution tracking
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(100),  -- User ID or 'SYSTEM'
    resolution_reason TEXT,  -- Why approved/denied

    -- Session tracking
    session_id VARCHAR(100),
    autonomous_operation_id VARCHAR(36),  -- Link to original operation

    -- Indexes
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_trigger_id (trigger_id),
    INDEX idx_session_id (session_id),
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### Table 2: `governance_notifications`

Stores IMPORTANT tier notifications (non-blocking).

```sql
CREATE TABLE governance_notifications (
    -- Primary key
    notification_id VARCHAR(36) PRIMARY KEY,  -- UUID

    -- Notification metadata
    trigger_id VARCHAR(50) NOT NULL,
    action_category VARCHAR(50) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    decision_tier VARCHAR(20) NOT NULL,  -- Always IMPORTANT

    -- Action context
    parameters JSON NOT NULL,
    evaluation_result JSON NOT NULL,

    -- Notification delivery
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    acknowledged_at TIMESTAMP,

    -- Delivery channels
    email_sent BOOLEAN DEFAULT FALSE,
    slack_sent BOOLEAN DEFAULT FALSE,
    websocket_sent BOOLEAN DEFAULT FALSE,

    -- Session tracking
    session_id VARCHAR(100),

    -- Indexes
    INDEX idx_created_at (created_at),
    INDEX idx_read_at (read_at),
    INDEX idx_trigger_id (trigger_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### Table 3: `governance_audit_log`

Immutable audit trail for all governance actions.

```sql
CREATE TABLE governance_audit_log (
    -- Primary key
    audit_id VARCHAR(36) PRIMARY KEY,  -- UUID

    -- Event metadata
    event_type VARCHAR(50) NOT NULL,  -- DECISION_CREATED, DECISION_APPROVED, etc.
    decision_id VARCHAR(36),
    notification_id VARCHAR(36),

    -- Event details
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor VARCHAR(100) NOT NULL,  -- User ID or 'SYSTEM'
    action_taken VARCHAR(100) NOT NULL,
    details JSON,

    -- Integrity
    signature VARCHAR(256),  -- HMAC signature for immutability

    -- Indexes
    INDEX idx_timestamp (timestamp),
    INDEX idx_decision_id (decision_id),
    INDEX idx_event_type (event_type),
    INDEX idx_actor (actor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### Table 4: `governance_config`

User-configurable governance settings.

```sql
CREATE TABLE governance_config (
    -- Primary key
    config_key VARCHAR(100) PRIMARY KEY,

    -- Configuration value
    config_value JSON NOT NULL,

    -- Metadata
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),

    -- Description
    description TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Default configs
INSERT INTO governance_config (config_key, config_value, description) VALUES
('decision_expiration_hours', '24', 'Hours before queued decisions auto-expire'),
('notification_channels', '{"email": true, "slack": true, "websocket": true}', 'Enabled notification channels'),
('batch_operation_limit', '50', 'Max decisions in batch operations'),
('auto_cleanup_days', '90', 'Days to keep resolved decisions before archival');
```

---

## API Endpoints

### Base URL: `/api/v1/governance`

All endpoints require authentication. Response format is JSON.

---

### 1. List Queued Decisions

**Endpoint**: `GET /api/v1/governance/decisions`

**Query Parameters**:
- `status` (optional): Filter by status (PENDING, APPROVED, DENIED, DEFERRED, EXPIRED)
- `action_category` (optional): Filter by category (MEMORY_OPERATIONS, RESOURCE_ALLOCATION, etc.)
- `limit` (optional, default: 50): Number of results
- `offset` (optional, default: 0): Pagination offset
- `sort` (optional, default: created_at): Sort field (created_at, expires_at, decision_tier)
- `order` (optional, default: desc): Sort order (asc, desc)

**Response**:
```json
{
  "success": true,
  "data": {
    "decisions": [
      {
        "decision_id": "550e8400-e29b-41d4-a716-446655440000",
        "trigger_id": "mem_ops_001",
        "action_category": "MEMORY_OPERATIONS",
        "action_type": "upgrade_memory_system",
        "decision_tier": "CRITICAL",
        "parameters": {
          "change_type": "indexing_algorithm",
          "new_algorithm": "vector_search"
        },
        "status": "PENDING",
        "created_at": "2026-01-02T12:34:56Z",
        "expires_at": "2026-01-03T12:34:56Z",
        "time_remaining_hours": 23.5,
        "session_id": "session_123"
      }
    ],
    "total": 15,
    "limit": 50,
    "offset": 0
  }
}
```

---

### 2. Get Decision Details

**Endpoint**: `GET /api/v1/governance/decisions/{decision_id}`

**Response**:
```json
{
  "success": true,
  "data": {
    "decision_id": "550e8400-e29b-41d4-a716-446655440000",
    "trigger_id": "mem_ops_001",
    "action_category": "MEMORY_OPERATIONS",
    "action_type": "upgrade_memory_system",
    "decision_tier": "CRITICAL",
    "parameters": {
      "change_type": "indexing_algorithm",
      "new_algorithm": "vector_search",
      "rollback_plan": "Switch back to B-tree indexing"
    },
    "evaluation_result": {
      "trigger_id": "mem_ops_001",
      "trigger_name": "Memory System Architecture Change",
      "decision_tier": "CRITICAL",
      "rationale": "Memory system architecture changes can affect all memories",
      "requires_rollback_plan": true
    },
    "action_context": {
      "session_id": "session_123",
      "autonomous_operation_id": "op_456",
      "reason": "Improve search performance for semantic queries"
    },
    "status": "PENDING",
    "created_at": "2026-01-02T12:34:56Z",
    "expires_at": "2026-01-03T12:34:56Z",
    "time_remaining_hours": 23.5
  }
}
```

---

### 3. Approve Decision

**Endpoint**: `POST /api/v1/governance/decisions/{decision_id}/approve`

**Request Body**:
```json
{
  "reason": "Approved after reviewing rollback plan. Vector search will improve semantic query performance.",
  "execute_immediately": true
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "decision_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "APPROVED",
    "resolved_at": "2026-01-02T13:00:00Z",
    "resolved_by": "user_stefan",
    "execution_result": {
      "success": true,
      "output": "Memory system upgraded to vector_search indexing",
      "execution_time": 2.34
    }
  }
}
```

---

### 4. Deny Decision

**Endpoint**: `POST /api/v1/governance/decisions/{decision_id}/deny`

**Request Body**:
```json
{
  "reason": "Rollback plan insufficient. Need more testing before production deployment."
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "decision_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "DENIED",
    "resolved_at": "2026-01-02T13:00:00Z",
    "resolved_by": "user_stefan"
  }
}
```

---

### 5. Defer Decision

**Endpoint**: `POST /api/v1/governance/decisions/{decision_id}/defer`

**Request Body**:
```json
{
  "defer_hours": 12,
  "reason": "Need to consult with team before approving"
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "decision_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "DEFERRED",
    "new_expires_at": "2026-01-03T01:00:00Z",
    "time_remaining_hours": 35.5
  }
}
```

---

### 6. Batch Approve

**Endpoint**: `POST /api/v1/governance/decisions/batch/approve`

**Request Body**:
```json
{
  "decision_ids": [
    "550e8400-e29b-41d4-a716-446655440000",
    "660e8400-e29b-41d4-a716-446655440001"
  ],
  "reason": "Batch approval for low-risk memory optimizations",
  "execute_immediately": true
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "approved": 2,
    "failed": 0,
    "results": [
      {
        "decision_id": "550e8400-e29b-41d4-a716-446655440000",
        "status": "APPROVED",
        "execution_result": {"success": true}
      },
      {
        "decision_id": "660e8400-e29b-41d4-a716-446655440001",
        "status": "APPROVED",
        "execution_result": {"success": true}
      }
    ]
  }
}
```

---

### 7. Get Pending Count

**Endpoint**: `GET /api/v1/governance/decisions/pending/count`

**Response**:
```json
{
  "success": true,
  "data": {
    "pending": 15,
    "by_category": {
      "MEMORY_OPERATIONS": 5,
      "RESOURCE_ALLOCATION": 3,
      "LEARNING_PARAMETERS": 7
    },
    "expiring_soon": 2  // Expiring in next 1 hour
  }
}
```

---

### 8. List Notifications

**Endpoint**: `GET /api/v1/governance/notifications`

**Query Parameters**:
- `unread_only` (optional, default: false): Only unread notifications
- `limit` (optional, default: 50): Number of results
- `offset` (optional, default: 0): Pagination offset

**Response**:
```json
{
  "success": true,
  "data": {
    "notifications": [
      {
        "notification_id": "770e8400-e29b-41d4-a716-446655440002",
        "trigger_id": "mem_ops_004",
        "action_category": "MEMORY_OPERATIONS",
        "action_type": "change_ranking_weights",
        "decision_tier": "IMPORTANT",
        "parameters": {
          "weights": {"recency": 0.8, "capability_suppression": 0.2}
        },
        "created_at": "2026-01-02T14:30:00Z",
        "read_at": null,
        "acknowledged_at": null
      }
    ],
    "total": 8,
    "unread": 3
  }
}
```

---

### 9. Mark Notification as Read

**Endpoint**: `POST /api/v1/governance/notifications/{notification_id}/read`

**Response**:
```json
{
  "success": true,
  "data": {
    "notification_id": "770e8400-e29b-41d4-a716-446655440002",
    "read_at": "2026-01-02T15:00:00Z"
  }
}
```

---

### 10. Get Audit Log

**Endpoint**: `GET /api/v1/governance/audit`

**Query Parameters**:
- `start_date` (optional): Filter by start date (ISO 8601)
- `end_date` (optional): Filter by end date (ISO 8601)
- `event_type` (optional): Filter by event type
- `actor` (optional): Filter by actor
- `limit` (optional, default: 100): Number of results
- `offset` (optional, default: 0): Pagination offset

**Response**:
```json
{
  "success": true,
  "data": {
    "audit_entries": [
      {
        "audit_id": "880e8400-e29b-41d4-a716-446655440003",
        "event_type": "DECISION_APPROVED",
        "decision_id": "550e8400-e29b-41d4-a716-446655440000",
        "timestamp": "2026-01-02T13:00:00Z",
        "actor": "user_stefan",
        "action_taken": "APPROVE",
        "details": {
          "reason": "Approved after reviewing rollback plan",
          "execution_result": {"success": true}
        }
      }
    ],
    "total": 342
  }
}
```

---

## Backend Implementation

### File Structure

```
core/governance/
├── decision_queue.py           # DecisionQueueManager class
├── notification_service.py     # NotificationService class
├── audit_trail.py              # AuditTrailService class
└── api/
    ├── __init__.py
    ├── routes.py               # FastAPI/Flask routes
    ├── schemas.py              # Pydantic schemas
    └── websocket.py            # WebSocket handler
```

---

### Class 1: DecisionQueueManager

**File**: `core/governance/decision_queue.py`

**Purpose**: Manage decision queue lifecycle (create, approve, deny, defer, expire)

**Key Methods**:

```python
class DecisionQueueManager:
    async def queue_decision(
        self,
        trigger_id: str,
        action_category: str,
        action_type: str,
        decision_tier: str,
        parameters: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        session_id: Optional[str] = None,
        action_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Queue a new decision. Returns decision_id."""

    async def get_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        """Get decision details by ID."""

    async def list_decisions(
        self,
        status: Optional[str] = None,
        action_category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        sort: str = "created_at",
        order: str = "desc"
    ) -> Dict[str, Any]:
        """List decisions with filtering and pagination."""

    async def approve_decision(
        self,
        decision_id: str,
        resolved_by: str,
        reason: str,
        execute_immediately: bool = True
    ) -> Dict[str, Any]:
        """Approve a decision and optionally execute the action."""

    async def deny_decision(
        self,
        decision_id: str,
        resolved_by: str,
        reason: str
    ) -> Dict[str, Any]:
        """Deny a decision."""

    async def defer_decision(
        self,
        decision_id: str,
        defer_hours: int,
        reason: str
    ) -> Dict[str, Any]:
        """Defer a decision (extend expiration time)."""

    async def batch_approve(
        self,
        decision_ids: List[str],
        resolved_by: str,
        reason: str,
        execute_immediately: bool = True
    ) -> Dict[str, Any]:
        """Batch approve multiple decisions."""

    async def get_pending_count(self) -> Dict[str, int]:
        """Get count of pending decisions by category."""

    async def cleanup_expired(self) -> int:
        """Auto-deny expired decisions. Returns count."""
```

**Integration with autonomous_coordinator.py**:

```python
# In autonomous_coordinator.py, when governance triggers:

if evaluation.decision_tier.name == "CRITICAL":
    # Queue decision instead of immediate return
    from core.governance.decision_queue import DecisionQueueManager

    queue = DecisionQueueManager()
    decision_id = await queue.queue_decision(
        trigger_id=evaluation.trigger_id,
        action_category=ActionCategory.MEMORY_OPERATIONS.name,
        action_type="upgrade_memory_system",
        decision_tier=evaluation.decision_tier.name,
        parameters={"change_type": change_type, **parameters},
        evaluation_result=evaluation.dict(),
        session_id=self.session_id,
        action_context={"reason": reason}
    )

    return ToolResult(
        success=False,
        output=None,
        requires_approval=True,
        approval_message=f"QUEUED_FOR_GOVERNANCE: Decision {decision_id}",
        metadata={"decision_id": decision_id}
    )
```

---

### Class 2: NotificationService

**File**: `core/governance/notification_service.py`

**Purpose**: Handle IMPORTANT tier notifications across multiple channels

**Key Methods**:

```python
class NotificationService:
    async def send_notification(
        self,
        trigger_id: str,
        action_category: str,
        action_type: str,
        decision_tier: str,
        parameters: Dict[str, Any],
        evaluation_result: Dict[str, Any],
        session_id: Optional[str] = None
    ) -> str:
        """Send notification across all enabled channels. Returns notification_id."""

    async def send_email(
        self,
        notification_id: str,
        subject: str,
        body: str,
        recipient: str
    ) -> bool:
        """Send email notification via SendGrid/SMTP."""

    async def send_slack(
        self,
        notification_id: str,
        message: str,
        channel: str
    ) -> bool:
        """Send Slack notification via webhook."""

    async def send_websocket(
        self,
        notification_id: str,
        data: Dict[str, Any]
    ) -> bool:
        """Broadcast notification via WebSocket."""

    async def mark_read(self, notification_id: str) -> bool:
        """Mark notification as read."""

    async def mark_acknowledged(self, notification_id: str) -> bool:
        """Mark notification as acknowledged."""

    async def list_notifications(
        self,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List notifications with filtering."""
```

**Email Template Example**:

```html
Subject: [TorinAI Governance] Memory Ranking Weights Changed

Body:
TorinAI has executed a memory ranking weight change that triggered governance notification.

Trigger: mem_ops_004 - Memory Ranking Weight Change
Category: MEMORY_OPERATIONS
Decision Tier: IMPORTANT (notification only, action executed)

Details:
- Action Type: change_ranking_weights
- Old Weights: {"recency": 0.5, "capability_suppression": 0.5}
- New Weights: {"recency": 0.8, "capability_suppression": 0.2}

Rationale:
Memory ranking weight changes >15% can affect which memories surface in queries. This action has been logged for audit purposes.

View full details: https://torinai.app/governance/notifications/{notification_id}
```

**Slack Webhook Example**:

```json
{
  "text": "🚨 TorinAI Governance Notification",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "Memory Ranking Weights Changed"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Trigger:* mem_ops_004"
        },
        {
          "type": "mrkdwn",
          "text": "*Category:* MEMORY_OPERATIONS"
        },
        {
          "type": "mrkdwn",
          "text": "*Tier:* IMPORTANT"
        }
      ]
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "View Details"
          },
          "url": "https://torinai.app/governance/notifications/{notification_id}"
        }
      ]
    }
  ]
}
```

---

### Class 3: AuditTrailService

**File**: `core/governance/audit_trail.py`

**Purpose**: Immutable audit logging for all governance actions

**Key Methods**:

```python
class AuditTrailService:
    async def log_event(
        self,
        event_type: str,
        actor: str,
        action_taken: str,
        details: Dict[str, Any],
        decision_id: Optional[str] = None,
        notification_id: Optional[str] = None
    ) -> str:
        """Log an audit event. Returns audit_id."""

    async def get_audit_log(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get audit log entries with filtering."""

    async def verify_integrity(self, audit_id: str) -> bool:
        """Verify audit entry signature for immutability."""

    async def export_to_csv(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> str:
        """Export audit log to CSV. Returns file path."""

    async def generate_compliance_report(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Generate compliance report with statistics."""
```

**Event Types**:
- `DECISION_CREATED`: New decision queued
- `DECISION_APPROVED`: Decision approved by user
- `DECISION_DENIED`: Decision denied by user
- `DECISION_DEFERRED`: Decision deferred
- `DECISION_EXPIRED`: Decision auto-expired
- `NOTIFICATION_SENT`: IMPORTANT tier notification sent
- `NOTIFICATION_READ`: Notification marked as read
- `BATCH_APPROVED`: Batch approval executed
- `CONFIG_CHANGED`: Governance configuration changed

---

## Frontend Implementation

### Technology Stack

- **Framework**: React or Vue.js
- **State Management**: Redux/Vuex or React Context
- **UI Components**: Material-UI or Ant Design
- **WebSocket**: Socket.IO client
- **Data Fetching**: Axios or Fetch API
- **Real-time Updates**: WebSocket + polling fallback

---

### Component 1: DecisionQueueView

**File**: `frontend/src/components/governance/DecisionQueueView.jsx`

**Features**:
- Table view of all queued decisions
- Filters (status, category, date range)
- Sort by date, priority, category
- Batch selection (checkboxes)
- Action buttons (Approve, Deny, Defer)
- Real-time updates via WebSocket

**UI Layout**:

```
┌─────────────────────────────────────────────────────────────┐
│ Decision Queue (15 Pending)                          [Filter]│
├─────────────────────────────────────────────────────────────┤
│ [√] ID      | Category  | Action Type     | Created | Status│
├─────────────────────────────────────────────────────────────┤
│ [ ] 550e... | MEMORY    | upgrade_memory  | 1h ago  | PEND. │
│ [ ] 660e... | RESOURCE  | allocate_res.   | 2h ago  | PEND. │
│ [ ] 770e... | LEARNING  | change_lr       | 3h ago  | PEND. │
├─────────────────────────────────────────────────────────────┤
│ [Batch Approve] [Batch Deny] [Refresh]             Page 1/3 │
└─────────────────────────────────────────────────────────────┘
```

---

### Component 2: DecisionDetailModal

**File**: `frontend/src/components/governance/DecisionDetailModal.jsx`

**Features**:
- Full decision details
- Parameter visualization (JSON tree view)
- Evaluation rationale display
- Action buttons (Approve, Deny, Defer)
- Defer hours input
- Approval reason textarea

**UI Layout**:

```
┌─────────────────────────────────────────────────────────────┐
│ Decision Details                                         [X] │
├─────────────────────────────────────────────────────────────┤
│ Decision ID: 550e8400-e29b-41d4-a716-446655440000           │
│ Trigger: mem_ops_001 - Memory System Architecture Change    │
│ Category: MEMORY_OPERATIONS                                 │
│ Tier: CRITICAL                                              │
│                                                             │
│ Parameters:                                                 │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ {                                                       │ │
│ │   "change_type": "indexing_algorithm",                 │ │
│ │   "new_algorithm": "vector_search",                    │ │
│ │   "rollback_plan": "Switch back to B-tree indexing"    │ │
│ │ }                                                       │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Rationale:                                                  │
│ Memory system architecture changes can affect all memories. │
│ Requires rollback plan for safe deployment.                │
│                                                             │
│ Reason (optional):                                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ [Textarea for approval/denial reason]                   │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ [✓ Approve] [✗ Deny] [⏸ Defer for ___ hours]             │
└─────────────────────────────────────────────────────────────┘
```

---

### Component 3: NotificationWidget

**File**: `frontend/src/components/governance/NotificationWidget.jsx`

**Features**:
- Badge showing pending count
- Dropdown with recent notifications
- "Mark all as read" button
- Click to view full details

**UI Layout**:

```
┌─────────────────────────────────────────────────────────────┐
│                                      [🔔 3]  [User Menu ▼]  │
│                                       │                      │
│                                       ▼                      │
│                        ┌──────────────────────────────────┐ │
│                        │ Notifications (3 unread)         │ │
│                        ├──────────────────────────────────┤ │
│                        │ 🟡 Memory ranking weights changed│ │
│                        │    2 minutes ago                 │ │
│                        ├──────────────────────────────────┤ │
│                        │ 🟡 Resource allocation adjusted  │ │
│                        │    15 minutes ago                │ │
│                        ├──────────────────────────────────┤ │
│                        │ ⚪ Learning rate updated          │ │
│                        │    1 hour ago (read)             │ │
│                        ├──────────────────────────────────┤ │
│                        │ [Mark all as read] [View all]    │ │
│                        └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

### Component 4: AuditTrailView

**File**: `frontend/src/components/governance/AuditTrailView.jsx`

**Features**:
- Timeline view of all governance events
- Filters (date range, event type, actor)
- Export to CSV button
- Compliance report generation

**UI Layout**:

```
┌─────────────────────────────────────────────────────────────┐
│ Audit Trail                         [Date Range ▼] [Export] │
├─────────────────────────────────────────────────────────────┤
│ ● 2026-01-02 13:00 - user_stefan APPROVED decision 550e...  │
│   Reason: "Approved after reviewing rollback plan"          │
│                                                             │
│ ● 2026-01-02 12:34 - SYSTEM CREATED decision 550e...       │
│   Trigger: mem_ops_001 (Memory System Architecture)         │
│                                                             │
│ ● 2026-01-02 11:15 - user_stefan DENIED decision 660e...   │
│   Reason: "Insufficient testing"                            │
├─────────────────────────────────────────────────────────────┤
│                                                  Page 1/15  │
└─────────────────────────────────────────────────────────────┘
```

---

## WebSocket Integration

**File**: `core/governance/api/websocket.py`

**Events**:

1. **decision_created**: New decision queued
2. **decision_updated**: Decision status changed
3. **notification_new**: New IMPORTANT tier notification
4. **pending_count_changed**: Pending decision count changed

**Client Subscription**:

```javascript
// Frontend WebSocket client
const socket = io('wss://torinai.app/governance');

socket.on('decision_created', (data) => {
  console.log('New decision queued:', data);
  // Update UI to show new decision
  dispatch(addDecision(data));
  // Show notification badge
  dispatch(incrementPendingCount());
});

socket.on('decision_updated', (data) => {
  console.log('Decision updated:', data);
  // Update decision in UI
  dispatch(updateDecision(data));
});

socket.on('notification_new', (data) => {
  console.log('New notification:', data);
  // Show notification in widget
  dispatch(addNotification(data));
  // Play sound or show toast
  showToast(`New governance notification: ${data.trigger_id}`);
});
```

---

## Testing Strategy

### Test Suite: `tests/governance/test_phase4_decision_queue.py`

**Categories**:

1. **Decision Queue Tests (10 tests)**
   - Create decision
   - Approve decision
   - Deny decision
   - Defer decision
   - Batch approve
   - List decisions with filters
   - Get pending count
   - Auto-expire decisions
   - Verify integrity

2. **Notification Tests (6 tests)**
   - Send email notification
   - Send Slack notification
   - Send WebSocket notification
   - Mark as read
   - List notifications
   - Filter unread

3. **Audit Trail Tests (4 tests)**
   - Log event
   - Verify signature
   - Export to CSV
   - Generate compliance report

4. **API Tests (8 tests)**
   - List decisions endpoint
   - Get decision details endpoint
   - Approve endpoint
   - Deny endpoint
   - Defer endpoint
   - Batch approve endpoint
   - Pending count endpoint
   - WebSocket connection

**Total**: 28 tests

**Target**: 100% test coverage for Phase 4

---

## Deployment Checklist

### Database

- [ ] Create governance_decisions table
- [ ] Create governance_notifications table
- [ ] Create governance_audit_log table
- [ ] Create governance_config table
- [ ] Insert default config values
- [ ] Set up indexes for performance
- [ ] Configure backup schedule

### Backend

- [ ] Implement DecisionQueueManager
- [ ] Implement NotificationService
- [ ] Implement AuditTrailService
- [ ] Implement API routes
- [ ] Implement WebSocket handler
- [ ] Configure email service (SendGrid/SMTP)
- [ ] Configure Slack webhook
- [ ] Set up cron job for auto-expiration

### Frontend

- [ ] Implement DecisionQueueView
- [ ] Implement DecisionDetailModal
- [ ] Implement NotificationWidget
- [ ] Implement AuditTrailView
- [ ] Set up WebSocket client
- [ ] Configure API client
- [ ] Add mobile-responsive CSS
- [ ] Test on all browsers

### Integration

- [ ] Integrate DecisionQueueManager with autonomous_coordinator.py
- [ ] Integrate NotificationService with governance triggers
- [ ] Integrate AuditTrailService with all governance actions
- [ ] Test end-to-end flow (trigger → queue → approve → execute)
- [ ] Test WebSocket real-time updates
- [ ] Test email notifications
- [ ] Test Slack notifications

### Security

- [ ] Add authentication middleware
- [ ] Add role-based access control
- [ ] Add rate limiting
- [ ] Add CSRF protection
- [ ] Add audit log integrity verification
- [ ] Test security controls

### Documentation

- [ ] API documentation (OpenAPI/Swagger)
- [ ] User guide for decision queue
- [ ] Admin guide for configuration
- [ ] WebSocket integration guide
- [ ] Troubleshooting guide

---

## Success Criteria

Phase 4 is complete when:

- ✅ All 28 tests passing (100%)
- ✅ Decision queue persists to MySQL
- ✅ API endpoints functional and documented
- ✅ Frontend UI renders correctly
- ✅ WebSocket real-time updates working
- ✅ Email notifications sending
- ✅ Slack notifications sending
- ✅ Audit trail logging all events
- ✅ Auto-expiration working
- ✅ Batch operations functional
- ✅ Mobile-responsive UI
- ✅ Security controls validated

---

## Next Phase Preview

**Phase 5: Advanced Governance Features**

- AI-assisted decision recommendations
- Risk scoring for decisions
- Governance policy templates
- Multi-user approval workflows
- Decision execution scheduling
- Rollback automation
- Governance analytics dashboard

---

**Phase 4 Status**: 📋 READY TO IMPLEMENT
**Estimated Duration**: 8-10 hours
**Dependencies**: Phase 3 Complete ✅
