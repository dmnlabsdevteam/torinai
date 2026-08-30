# TorinAI Full SOC Automation Capability Plan
**Version:** 1.0
**Date:** January 28, 2026
**Objective:** Transform TorinAI into a complete SOC automation platform capable of handling Tier 1-3 security operations

---

## Executive Summary

TorinAI currently has **70-80% of capabilities needed for full SOC automation**. This plan outlines the path to 100% coverage through targeted integrations while leveraging existing strengths:

- ✅ 246 tools (25 security-specific)
- ✅ Multi-source threat intelligence (AbuseIPDB, VirusTotal, OTX)
- ✅ Action-level governance with constitutional oversight
- ✅ Persistent memory system
- ✅ Statistical anomaly detection
- ✅ Logs already flowing to MySQL (`torinai_unified` database)

**Key Differentiator:** Unlike SOAR tools (Palo Alto XSOAR, Splunk SOAR, Swimlane), TorinAI combines automation with AI reasoning, governance, and continuous learning.

---

## Part 1: Current Capabilities Assessment

### ✅ What We Have (Production-Ready)

#### **1. Threat Intelligence (Best-in-Class)**
- Multi-source aggregation: AbuseIPDB, VirusTotal, OTX AlienVault
- Real API integrations with caching (configurable TTL)
- Threat confidence scoring and classification
- Internal threat database for custom intelligence
- **Files:** `core/security/threat_intelligence.py`, `core/tools/security_tools.py`

#### **2. Intrusion Detection & Prevention**
- Real-time intrusion detection (`DetectIntrusionTool`)
- Brute force attack detection (`DetectBruteForceTool`)
- Traffic pattern analysis for DDoS/exfiltration (`AnalyzeTrafficPatternTool`)
- Zero-day heuristic detection (`DetectZeroDayTool`)
- Automated threat response with playbooks (`AutoRespondThreatTool`)

#### **3. Behavioral Anomaly Detection**
- Statistical z-score analysis (3σ threshold)
- Multi-dimensional anomaly detection:
  - Traffic volume anomalies
  - Geographic anomalies (unusual countries)
  - Temporal anomalies (off-hours access)
  - Access pattern changes (unusual endpoints)
- Configurable baseline (7-90 days)
- Database-backed historical analysis
- **File:** `core/tools/security_tools.py:1402-1700`

#### **4. Active Defense & Blocking**
- IP blocking across multiple layers:
  - OS firewall (iptables/pf)
  - Cloudflare WAF integration
- Country-level geo-blocking
- Rate limiting
- WAF rule creation
- Block history tracking and metrics
- Governance approval for critical blocks

#### **5. Malware Analysis**
- Complete sandbox environment (`core/security/malware_sandbox.py`)
- Static analysis (file properties, signatures, strings)
- Dynamic analysis (execution monitoring)
- Behavioral monitoring (file system, network, process)
- Threat intelligence integration
- Automated reporting with ThreatLevel classification

#### **6. Log Analysis Infrastructure**
- Logs flowing to MySQL (`torinai_unified` database) ✅
- Log parsing capabilities (`ParseLogsTool`)
- Real-time log monitoring (`MonitorLogsTool`)
- Pattern recognition and attack signature detection
- Query metrics from database (`QueryMetricsTool`)

#### **7. Governance & Safety**
- Action-level constitutional oversight
- 5-judge deliberation system for critical actions
- Persistent memory of all actions
- Full audit trail
- Emergency halt capability
- **Files:** `core/agents/autonomous/governance_judge_executor.py`, `core/agents/autonomous/runtime_governance.py`

#### **8. Supporting Infrastructure**
- 221 additional tools across 17 categories
- Database tools (MySQL, Redis, R2 storage)
- Network tools (HTTP, DNS, port scanning, WebSocket)
- Monitoring tools (CPU/memory/disk, service health, distributed tracing)
- AI/ML tools (embeddings, memory, inference)
- Full code generation and analysis suite

---

## Part 2: Gap Analysis - What's Missing

### ❌ **Critical Gaps for "Full" SOC Automation**

#### **Gap 1: SIEM Query Interface**
**Problem:** Can access MySQL logs, but no high-level SIEM query interface
**Impact:** Analysts can't use familiar query languages (SPL, KQL)
**Effort:** Medium (4-6 weeks)

**What We Need:**
- SQL-based alert ingestion pipeline
- Query builder for common SOC use cases
- Alert correlation engine
- Pre-built detection rules library

**Advantage:** We already have the data in MySQL! Just need better query interface.

#### **Gap 2: EDR/XDR Integration**
**Problem:** Can't isolate hosts or gather endpoint telemetry
**Impact:** Limited incident response capabilities
**Effort:** High (8-12 weeks for 2-3 EDR platforms)

**What We Need:**
- CrowdStrike Falcon API integration (Priority 1)
- SentinelOne API integration (Priority 2)
- Microsoft Defender API (Priority 3)
- Capabilities: Host isolation, process termination, file quarantine, telemetry collection

#### **Gap 3: Ticketing System Integration**
**Problem:** Can't automatically create/update tickets
**Impact:** Manual ticket creation, no workflow tracking
**Effort:** Low (2-4 weeks)

**What We Need:**
- ServiceNow REST API integration
- Jira REST API integration
- PagerDuty integration for on-call
- Slack notifications (already have `SendSlackMessageTool` ✅)

#### **Gap 4: Enhanced Playbook Library**
**Problem:** Have playbook execution, but limited pre-built playbooks
**Impact:** Customers need to build their own
**Effort:** Medium (4-8 weeks)

**What We Need:**
- 20+ pre-built playbooks for common scenarios:
  - Phishing email investigation
  - Malware outbreak response
  - Credential compromise
  - Data exfiltration
  - DDoS mitigation
  - Insider threat investigation
- Playbook marketplace/repository
- Visual playbook editor

#### **Gap 5: Alert Correlation Engine**
**Problem:** Process alerts individually, not as related incidents
**Impact:** Miss multi-stage attacks
**Effort:** Medium (6-8 weeks)

**What We Need:**
- Time-window correlation (events within N minutes)
- Entity-based correlation (same user/host/IP)
- Attack chain detection (MITRE ATT&CK mapping)
- Incident clustering and deduplication

---

## Part 3: Implementation Roadmap

### **Phase 1: Complete Core SOC Operations (8 weeks)**
**Goal:** Enable full Tier 1 SOC automation with existing MySQL logs

**Week 1-2: SIEM Query Enhancement**
- [ ] Build SQL query templates for common SOC queries
- [ ] Create alert ingestion pipeline from `torinai_unified` DB
- [ ] Implement alert deduplication
- [ ] Add alert enrichment workflow (IP → threat intel → anomaly check)

**Week 3-4: Alert Triage Automation**
- [ ] Build automated triage engine using existing tools:
  - Pull alerts from MySQL
  - Enrich with `CheckIPThreatIntelligenceTool`
  - Analyze with `AnalyzeAnomalyTool`
  - Detect patterns with `DetectIntrusionTool`
  - Auto-classify (True Positive / False Positive)
- [ ] Implement feedback loop for analyst corrections
- [ ] Build triage dashboard

**Week 5-6: Ticketing Integration**
- [ ] ServiceNow REST API connector
- [ ] Jira REST API connector
- [ ] Auto-ticket creation for escalated threats
- [ ] Bidirectional sync (ticket updates → TorinAI)
- [ ] PagerDuty integration for critical alerts

**Week 7-8: Pre-Built Playbook Library**
- [ ] Implement 10 core playbooks:
  1. Malicious IP investigation
  2. Brute force attack response
  3. Phishing email analysis
  4. Malware outbreak containment
  5. DDoS mitigation
  6. Credential compromise response
  7. Data exfiltration investigation
  8. Port scan response
  9. Web application attack response
  10. Insider threat investigation
- [ ] Playbook testing and validation
- [ ] Documentation and examples

**Deliverable:** Tier 1 SOC automation MVP
- Automated alert triage (80% reduction in manual work)
- Threat intelligence enrichment (sub-second)
- Automated blocking for confirmed threats
- Ticket creation for escalation
- 10 ready-to-use playbooks

---

### **Phase 2: EDR Integration & Advanced Response (10 weeks)**
**Goal:** Enable host-level incident response and forensics

**Week 9-12: CrowdStrike Falcon Integration (Priority 1)**
- [ ] CrowdStrike Falcon API authentication
- [ ] Implement core EDR tools:
  - `IsolateHostTool` (network containment)
  - `GetHostTelemetryTool` (process, network, file activity)
  - `TerminateProcessTool` (kill malicious processes)
  - `QuarantineFileTool` (isolate malicious files)
  - `GetDetectionsTool` (pull CrowdStrike alerts)
- [ ] Integration with governance (approve host isolation)
- [ ] Testing with sandbox environment

**Week 13-15: SentinelOne Integration (Priority 2)**
- [ ] SentinelOne API authentication
- [ ] Implement same tool set as CrowdStrike
- [ ] Multi-EDR orchestration layer (abstract API differences)
- [ ] Testing and validation

**Week 16-18: Incident Response Playbooks**
- [ ] Build 10 advanced playbooks leveraging EDR:
  1. Ransomware outbreak response
  2. Living-off-the-land (LOLBin) attack
  3. Lateral movement investigation
  4. Privilege escalation detection
  5. Memory-based malware analysis
  6. Advanced persistent threat (APT) investigation
  7. Fileless malware response
  8. Supply chain attack investigation
  9. Zero-day exploit response
  10. Insider threat with data exfiltration
- [ ] Multi-stage incident response workflows
- [ ] Automated forensics collection

**Deliverable:** Tier 2 SOC automation
- Host isolation and containment
- Endpoint telemetry collection
- Advanced incident response playbooks
- Multi-EDR support

---

### **Phase 3: Alert Correlation & Advanced Analytics (6 weeks)**
**Goal:** Detect multi-stage attacks and reduce alert fatigue

**Week 19-21: Alert Correlation Engine**
- [ ] Time-based correlation (events within time window)
- [ ] Entity-based correlation (same user/host/IP)
- [ ] MITRE ATT&CK framework mapping
- [ ] Attack chain detection (initial access → execution → exfiltration)
- [ ] Incident clustering and deduplication

**Week 22-24: Advanced Analytics & ML**
- [ ] Threat score prediction model
- [ ] False positive prediction model
- [ ] Automated alert tuning (reduce FP rate over time)
- [ ] Threat actor profiling
- [ ] Attack pattern recognition

**Deliverable:** Tier 3 SOC automation
- Multi-stage attack detection
- 90%+ alert reduction through correlation
- Predictive threat scoring
- Continuous improvement via ML

---

## Part 4: Technical Implementation Details

### **4.1 SIEM Query Enhancement (MySQL-Based)**

Since logs are already in MySQL `torinai_unified`, we'll build a SIEM query layer on top.

**Database Schema (Assumed - needs validation):**
```sql
-- Main tables expected in torinai_unified
CREATE TABLE IF NOT EXISTS security_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(255) UNIQUE,
    timestamp DATETIME,
    event_type VARCHAR(100),
    severity VARCHAR(20),
    source_ip VARCHAR(45),
    dest_ip VARCHAR(45),
    source_port INT,
    dest_port INT,
    protocol VARCHAR(20),
    user_id VARCHAR(255),
    host_id VARCHAR(255),
    action VARCHAR(100),
    result VARCHAR(100),
    message TEXT,
    raw_log JSON,
    INDEX idx_timestamp (timestamp),
    INDEX idx_source_ip (source_ip),
    INDEX idx_event_type (event_type),
    INDEX idx_severity (severity)
);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    alert_id VARCHAR(255) UNIQUE,
    created_at DATETIME,
    updated_at DATETIME,
    alert_type VARCHAR(100),
    severity VARCHAR(20),
    status VARCHAR(50), -- NEW, INVESTIGATING, TRUE_POSITIVE, FALSE_POSITIVE, RESOLVED
    source_ip VARCHAR(45),
    dest_ip VARCHAR(45),
    user_id VARCHAR(255),
    host_id VARCHAR(255),
    description TEXT,
    threat_intel JSON,
    anomaly_score FLOAT,
    assigned_to VARCHAR(255),
    ticket_id VARCHAR(100),
    metadata JSON,
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_source_ip (source_ip)
);

CREATE TABLE IF NOT EXISTS threat_intel_cache (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    ip_address VARCHAR(45) UNIQUE,
    threat_score INT,
    confidence VARCHAR(20),
    sources JSON,
    last_updated DATETIME,
    INDEX idx_ip (ip_address),
    INDEX idx_last_updated (last_updated)
);
```

**New Tools to Build:**

**1. AlertIngestionTool**
```python
class AlertIngestionTool(Tool):
    """
    Ingest security events from MySQL and create alerts

    Query patterns:
    - Failed login attempts (>5 in 5 min)
    - Port scans (>20 ports in 1 min)
    - Data exfiltration (>100MB upload)
    - Brute force (>10 failed auth in 10 min)
    - Suspicious process execution
    - Anomalous network traffic
    """

    async def execute(self, time_window_minutes: int = 5) -> ToolResult:
        # Query security_events table
        # Apply detection rules
        # Create alerts in alerts table
        # Return new alerts for processing
```

**2. AlertEnrichmentTool**
```python
class AlertEnrichmentTool(Tool):
    """
    Enrich alert with threat intel and context

    For each alert:
    1. Check threat_intel_cache (if recent)
    2. If not cached, call CheckIPThreatIntelligenceTool
    3. Run AnalyzeAnomalyTool for behavioral context
    4. Query related events (same IP/user/host)
    5. Calculate composite risk score
    6. Update alert with enrichment data
    """
```

**3. AlertTriageTool**
```python
class AlertTriageTool(Tool):
    """
    Automated alert triage and classification

    Decision tree:
    - Threat intel score > 80 → TRUE_POSITIVE
    - Anomaly z-score > 3 → INVESTIGATING
    - Known FP pattern → FALSE_POSITIVE
    - Otherwise → Use AI reasoning with governance

    Actions on TRUE_POSITIVE:
    - Block IP (if governance approves)
    - Create ticket
    - Execute response playbook
    - Store in memory for learning
    """
```

---

### **4.2 EDR Integration Architecture**

**Design Pattern: Abstract EDR Interface**

```python
# core/security/edr_integration.py

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class HostInfo:
    host_id: str
    hostname: str
    ip_address: str
    os_type: str
    os_version: str
    last_seen: datetime
    status: str  # online, offline, isolated

@dataclass
class ProcessInfo:
    process_id: int
    process_name: str
    command_line: str
    user: str
    parent_process_id: int
    start_time: datetime
    network_connections: List[Dict]

class EDRProvider(ABC):
    """Abstract base class for EDR integrations"""

    @abstractmethod
    async def isolate_host(self, host_id: str, reason: str) -> bool:
        """Isolate host from network"""
        pass

    @abstractmethod
    async def unisolate_host(self, host_id: str) -> bool:
        """Remove host isolation"""
        pass

    @abstractmethod
    async def get_host_info(self, host_id: str) -> HostInfo:
        """Get host information"""
        pass

    @abstractmethod
    async def get_running_processes(self, host_id: str) -> List[ProcessInfo]:
        """Get running processes on host"""
        pass

    @abstractmethod
    async def terminate_process(self, host_id: str, process_id: int) -> bool:
        """Terminate process on host"""
        pass

    @abstractmethod
    async def quarantine_file(self, host_id: str, file_path: str) -> bool:
        """Quarantine file on host"""
        pass

    @abstractmethod
    async def get_detections(self, time_range_hours: int = 24) -> List[Dict]:
        """Get EDR detections"""
        pass

class CrowdStrikeProvider(EDRProvider):
    """CrowdStrike Falcon API implementation"""

    def __init__(self, client_id: str, client_secret: str, base_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.access_token = None

    async def _authenticate(self):
        """OAuth2 authentication with CrowdStrike"""
        # Implement OAuth2 flow
        pass

    async def isolate_host(self, host_id: str, reason: str) -> bool:
        """
        POST /devices/entities/devices-actions/v2
        {
          "action_name": "contain",
          "ids": [host_id]
        }
        """
        pass

    # Implement other methods...

class SentinelOneProvider(EDRProvider):
    """SentinelOne API implementation"""
    # Similar implementation for SentinelOne
    pass

class EDRManager:
    """Unified EDR management across multiple providers"""

    def __init__(self):
        self.providers: Dict[str, EDRProvider] = {}

    def register_provider(self, name: str, provider: EDRProvider):
        self.providers[name] = provider

    async def isolate_host(self, host_id: str, reason: str, provider: str = None) -> bool:
        """Isolate host using specified provider or auto-detect"""
        if provider:
            return await self.providers[provider].isolate_host(host_id, reason)

        # Auto-detect which EDR manages this host
        for prov in self.providers.values():
            try:
                info = await prov.get_host_info(host_id)
                if info:
                    return await prov.isolate_host(host_id, reason)
            except:
                continue

        return False
```

**New EDR Tools:**

```python
# core/tools/edr_tools.py

class IsolateHostTool(Tool):
    """Isolate host from network via EDR"""

    def __init__(self):
        self.name = "isolate_host"
        self.description = "Isolate a compromised host from the network"
        self.category = ToolCategory.SECURITY
        self.safety_level = ToolSafety.CRITICAL  # Requires governance approval
        self.parameters = [
            ToolParameter(name="host_id", type="string", required=True),
            ToolParameter(name="reason", type="string", required=True),
            ToolParameter(name="edr_provider", type="string", required=False)
        ]

    async def execute(self, host_id: str, reason: str, edr_provider: str = None) -> ToolResult:
        try:
            from core.security.edr_integration import get_edr_manager

            edr = get_edr_manager()
            success = await edr.isolate_host(host_id, reason, edr_provider)

            if success:
                # Log to database
                from core.database import get_database_manager
                db = get_database_manager()
                await db.execute(
                    "INSERT INTO edr_actions (action_type, host_id, reason, timestamp, result) VALUES (%s, %s, %s, NOW(), %s)",
                    ("isolate", host_id, reason, "success")
                )

                return ToolResult(
                    success=True,
                    output={
                        "host_id": host_id,
                        "status": "isolated",
                        "reason": reason
                    }
                )
            else:
                return ToolResult(success=False, error="Failed to isolate host")

        except Exception as e:
            logger.error(f"Host isolation failed: {e}")
            return ToolResult(success=False, error=str(e))

# Similar tools for:
# - UnisolateHostTool
# - GetHostTelemetryTool
# - TerminateProcessTool
# - QuarantineFileTool
# - GetEDRDetectionsTool
```

---

### **4.3 Ticketing Integration**

**ServiceNow Integration:**

```python
# core/integration/servicenow_integration.py

class ServiceNowIntegration:
    """ServiceNow REST API integration"""

    def __init__(self, instance_url: str, username: str, password: str):
        self.instance_url = instance_url
        self.auth = (username, password)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def create_incident(
        self,
        short_description: str,
        description: str,
        severity: str,
        category: str = "Security",
        assignment_group: str = "SOC Team"
    ) -> Dict[str, Any]:
        """
        Create security incident in ServiceNow

        POST /api/now/table/incident
        {
          "short_description": "Malicious IP detected",
          "description": "IP 1.2.3.4 detected...",
          "impact": "2",
          "urgency": "2",
          "category": "Security",
          "assignment_group": "SOC Team"
        }
        """
        url = f"{self.instance_url}/api/now/table/incident"

        # Map severity to ServiceNow impact/urgency
        impact_map = {
            "CRITICAL": "1",
            "HIGH": "2",
            "MEDIUM": "3",
            "LOW": "4"
        }

        payload = {
            "short_description": short_description,
            "description": description,
            "impact": impact_map.get(severity, "3"),
            "urgency": impact_map.get(severity, "3"),
            "category": category,
            "assignment_group": assignment_group,
            "caller_id": "TorinAI"  # System user
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, auth=self.auth, headers=self.headers) as resp:
                if resp.status == 201:
                    data = await resp.json()
                    return {
                        "success": True,
                        "ticket_number": data["result"]["number"],
                        "sys_id": data["result"]["sys_id"]
                    }
                else:
                    return {"success": False, "error": await resp.text()}

    async def update_incident(self, sys_id: str, updates: Dict[str, Any]) -> bool:
        """Update existing incident"""
        url = f"{self.instance_url}/api/now/table/incident/{sys_id}"

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, json=updates, auth=self.auth, headers=self.headers) as resp:
                return resp.status == 200

    async def add_work_note(self, sys_id: str, note: str) -> bool:
        """Add work note to incident"""
        return await self.update_incident(sys_id, {"work_notes": note})

    async def close_incident(self, sys_id: str, close_notes: str) -> bool:
        """Close incident"""
        return await self.update_incident(sys_id, {
            "state": "6",  # Resolved
            "close_notes": close_notes,
            "close_code": "Resolved by automation"
        })
```

**New Ticketing Tools:**

```python
class CreateTicketTool(Tool):
    """Create security incident ticket"""

    async def execute(
        self,
        title: str,
        description: str,
        severity: str,
        alert_id: str = None,
        system: str = "servicenow"
    ) -> ToolResult:
        try:
            if system == "servicenow":
                from core.integration.servicenow_integration import get_servicenow
                sn = get_servicenow()
                result = await sn.create_incident(title, description, severity)

                if result["success"]:
                    # Update alert with ticket number
                    if alert_id:
                        from core.database import get_database_manager
                        db = get_database_manager()
                        await db.execute(
                            "UPDATE alerts SET ticket_id = %s WHERE alert_id = %s",
                            (result["ticket_number"], alert_id)
                        )

                    return ToolResult(success=True, output=result)

            elif system == "jira":
                # Jira implementation
                pass

        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

---

## Part 5: Customer Value Proposition

### **What We're Building vs. Competitors**

| Capability | Palo Alto XSOAR | Splunk SOAR | Swimlane | **TorinAI** |
|------------|----------------|-------------|----------|-------------|
| **Automation** | ✅ Rule-based | ✅ Rule-based | ✅ Rule-based | ✅ AI reasoning |
| **Action-Level Governance** | ❌ | ❌ | ❌ | ✅ Constitutional oversight |
| **Persistent Memory** | ❌ | ❌ | ❌ | ✅ Learns from incidents |
| **Statistical Anomaly Detection** | ❌ | ⚠️ Basic | ❌ | ✅ Z-score, multi-dimensional |
| **Multi-Source Threat Intel** | ⚠️ Via integrations | ⚠️ Via integrations | ⚠️ Via integrations | ✅ Native (AbuseIPDB, VT, OTX) |
| **Malware Sandbox** | ❌ | ❌ | ❌ | ✅ Built-in |
| **Price** | $150K-500K/year | $100K-400K/year | $75K-300K/year | **$75K-250K/year** |

### **Unique Selling Points**

**1. AI-Powered Decision Making**
- Not just rule-based automation
- AI reasons about threats using 246 tools
- Adapts to new attack patterns
- Learns from analyst feedback

**2. Constitutional Governance**
- Every action validated before execution
- 5-judge system for critical actions
- Prevents automation disasters
- Full audit trail for compliance

**3. Built-In Capabilities**
- No need to integrate 10+ tools
- Threat intel included (AbuseIPDB, VirusTotal, OTX)
- Malware sandbox included
- Statistical anomaly detection included

**4. Continuous Learning**
- Persistent memory system
- Gets smarter with each incident
- Reduces false positives over time
- Customizes to your environment

---

## Part 6: Go-To-Market Strategy

### **Target Customers (Phase 1)**

**Ideal Customer Profile:**
- Company size: 500-5,000 employees
- Industry: Technology, Financial Services, Healthcare
- SOC team size: 3-10 analysts
- Pain points:
  - Alert fatigue (200+ alerts/day)
  - 85-95% false positive rate
  - Shortage of skilled analysts
  - Slow incident response (2-4 hours MTTR)
- Budget: $150K-300K/year for SOAR
- Tech stack: Splunk/Elastic/Sentinel + CrowdStrike/SentinelOne

**Initial Target: Series B-D Startups**
- Growth stage, building security program
- Don't want enterprise SOAR pricing
- Need fast deployment (weeks, not months)
- Want modern AI-powered solution
- Decision maker: CISO, Head of Security

### **Customer Acquisition Strategy**

**Step 1: Pilot Program (First 5 Customers)**
- Free 90-day pilot
- Full-service setup and configuration
- Weekly check-ins and optimization
- Success criteria:
  - 70%+ alert reduction
  - 60%+ faster MTTR
  - 80%+ analyst satisfaction

**Step 2: Case Studies**
- Document quantitative results
- Video testimonials from CISOs
- Public launch case study
- Security conference presentation

**Step 3: Demand Generation**
- Content: "SOAR vs. AI-Powered SOC Automation"
- Webinar: "Reducing Alert Fatigue with AI"
- Podcast: CISO interviews
- Dark Reading / BleepingComputer articles

**Step 4: Sales Motion**
- Inbound: Free assessment (analyze their alerts)
- Outbound: Target Series B-D startups via LinkedIn
- Proof of concept: 2-week POC with real alerts
- Close: $150K-250K ACV, annual contract

---

## Part 7: Success Metrics

### **Product Metrics**

**Alert Processing:**
- Target: Process 500+ alerts/day
- Target: <1 second per alert for enrichment
- Target: <5 seconds for triage decision

**Accuracy:**
- Target: >95% true positive detection rate
- Target: <5% false positive rate (after 30 days)
- Target: >90% analyst agreement with AI decisions

**Performance:**
- Target: <2 second response time for threat intel lookup
- Target: <5 second response time for anomaly analysis
- Target: <10 seconds for full alert triage

**Automation Rate:**
- Target: >80% of alerts auto-triaged (no analyst intervention)
- Target: >50% of true positives auto-blocked
- Target: >90% of tickets auto-created

### **Business Metrics**

**Customer Outcomes:**
- 70-85% reduction in alert volume (through deduplication + FP reduction)
- 60-75% reduction in MTTR (Mean Time To Respond)
- 3-4 hours/day saved per analyst
- ROI: 200-300% in year 1

**Revenue:**
- Phase 1 (Months 1-6): 3-5 pilot customers, $0 ARR
- Phase 2 (Months 7-12): Convert pilots, add 5-10 new customers, $500K-1M ARR
- Phase 3 (Months 13-18): 15-25 customers, $2M-3M ARR
- Phase 4 (Months 19-24): 30-50 customers, $4M-6M ARR

**Customer Acquisition:**
- CAC: $25K-40K (includes sales + POC + onboarding)
- LTV: $650K (avg 3-year contract × $150K-250K/year)
- LTV:CAC ratio: 16:1-26:1 (excellent)

---

## Part 8: Implementation Priorities

### **What to Build First (Ranked by Customer Value)**

**Priority 1: Alert Triage Automation (Weeks 1-4)**
- Highest pain point for SOC teams
- Leverages existing capabilities (threat intel, anomaly detection, governance)
- Quick win: 70-80% alert reduction
- Easy to demo and prove value

**Priority 2: Ticketing Integration (Weeks 5-6)**
- Second highest pain point (manual ticket creation)
- Low effort (REST APIs)
- High perceived value
- Enables workflow automation

**Priority 3: Pre-Built Playbooks (Weeks 7-8)**
- Customers need turnkey solution
- Showcases governance + memory + reasoning
- Differentiates from competitors
- Enables faster deployment

**Priority 4: CrowdStrike EDR Integration (Weeks 9-12)**
- Most common EDR platform
- Enables incident response automation
- High-value use cases (host isolation, process termination)
- Opens Tier 2 SOC market

**Priority 5: Alert Correlation (Weeks 19-21)**
- Advanced capability
- Further reduces alert fatigue
- Detects multi-stage attacks
- Justifies premium pricing

---

## Part 9: Technical Validation Checklist

Before starting implementation, validate these assumptions:

### **Database Schema Validation**
- [ ] Confirm `torinai_unified` database exists
- [ ] Confirm log tables exist (security_events, alerts, etc.)
- [ ] Confirm table schemas match assumptions
- [ ] Confirm log ingestion is working (check row counts)
- [ ] Confirm indexes exist for performance

**Action:** Run this query:
```sql
SHOW TABLES FROM torinai_unified;
DESCRIBE torinai_unified.security_events;
SELECT COUNT(*) FROM torinai_unified.security_events WHERE timestamp > NOW() - INTERVAL 24 HOUR;
```

### **Existing Tool Validation**
- [ ] Test `CheckIPThreatIntelligenceTool` with real IP
- [ ] Test `AnalyzeAnomalyTool` with sample data
- [ ] Test `DetectIntrusionTool` with sample logs
- [ ] Test `BlockIPAddressTool` in sandbox
- [ ] Test `MySQLQueryTool` against torinai_unified
- [ ] Test governance system with critical action

**Action:** Create `tests/integration/test_soc_automation.py`

### **API Access Validation**
- [ ] Confirm AbuseIPDB API key works (test query)
- [ ] Confirm VirusTotal API key works (test query)
- [ ] Confirm OTX API key works (test query)
- [ ] Confirm Cloudflare WAF API access
- [ ] Obtain ServiceNow dev instance
- [ ] Obtain CrowdStrike sandbox account

---

## Part 10: Next Steps

### **Immediate Actions (This Week)**

1. **Validate Database Schema**
   - Run SQL queries to confirm log tables
   - Check sample data
   - Identify any schema gaps

2. **Create Test Environment**
   - Set up test MySQL database
   - Generate synthetic alerts
   - Test existing security tools

3. **Customer Discovery**
   - Interview 5 SOC analysts
   - Ask about alert triage workflow
   - Identify top 3 pain points
   - Validate our solution addresses them

4. **Pitch Deck Update**
   - Replace "3 products" with "SOC Automation Platform"
   - Add "80% alert reduction" customer outcome
   - Add governance differentiator
   - Add technical architecture diagram
   - Include customer discovery insights

### **Phase 1 Kickoff (Next Week)**

1. **Team Roles**
   - Product Lead: Define requirements, customer interviews
   - Tech Lead: Architecture design, code reviews
   - Engineer 1: Alert triage automation
   - Engineer 2: Ticketing integration
   - Engineer 3: Playbook library

2. **Setup**
   - Create GitHub project board
   - Set up development environment
   - Create test cases
   - Design database schemas

3. **Week 1 Goals**
   - SIEM query templates built
   - Alert ingestion pipeline working
   - First automated triage test passing

---

## Conclusion

TorinAI is **70-80% complete for full SOC automation**. With focused execution on the roadmap above, we can achieve 100% coverage in 18-24 weeks.

**Our competitive advantage:**
1. ✅ Already built the hard parts (governance, memory, AI reasoning, threat intel)
2. ✅ Logs already in MySQL (most companies don't have this!)
3. ✅ 246 tools providing broad capabilities
4. ✅ Unique differentiators (action-level governance, persistent memory)

**The missing pieces (SIEM UI, EDR connectors, ticketing) are:**
- Well-defined APIs
- 2-4 weeks each
- Standard REST/HTTP integrations
- No novel research needed

**This is buildable. This is sellable. This is fundable.**

The question isn't "Can we do it?" but "Do we want to focus on SOC automation?"

If yes → Execute this plan → Become the AI-powered SOAR platform

If unsure → Pilot with 3 SOC teams in next 60 days → Let customer validation decide

---

**Plan Version:** 1.0
**Last Updated:** January 28, 2026
**Next Review:** After Phase 1 completion
