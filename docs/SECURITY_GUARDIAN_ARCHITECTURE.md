# TorinAI Security Guardian Architecture
**Date**: 2026-02-05
**Role**: System-Level Security Guardian

---

## 🛡️ **Core Principle**

**TorinAI is NOT a siloed service protecting only itself.**

**TorinAI IS the system security guardian protecting ALL services on the host machine.**

---

## 🎯 **Authorization & Scope**

### **Identity & Permission**
```python
# System Prompt (establishes role and permission):
"You are TorinAI, created by Dominion Labs"
```

**What This Means:**
- ✅ TorinAI was created by Dominion Labs
- ✅ TorinAI has permission to protect Dominion Labs services
- ✅ TorinAI operates at system level, not service level
- ✅ TorinAI is the security guardian for the entire deployment environment

**Governance:**
- Still respects human oversight via governance system
- Critical actions require approval
- Auto-blocks are logged and can be reviewed
- Human can override or adjust security policies

---

## 🏗️ **Corrected Architecture**

```
┌───────────────────────────────────────────────────────────────┐
│                    Host System (Your Computer)                 │
│                                                                │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                      TorinAI                             │  │
│  │              System Security Guardian                     │  │
│  │                                                           │  │
│  │  Role: Protect ALL services on this system               │  │
│  │  Authority: "Created by Dominion Labs"                   │  │
│  │  Scope: System-wide monitoring & defense                 │  │
│  │                                                           │  │
│  │  ┌─────────────────────────────────────────────────┐    │  │
│  │  │     Integrated Security System                   │    │  │
│  │  │                                                  │    │  │
│  │  │  📡 Monitors:                                    │    │  │
│  │  │     - System logs (/var/log/*)                  │    │  │
│  │  │     - Dominion Labs application logs            │    │  │
│  │  │     - MySQL database activity                   │    │  │
│  │  │     - Network traffic (all services)            │    │  │
│  │  │     - Auth attempts (all services)              │    │  │
│  │  │     - API endpoints (all services)              │    │  │
│  │  │                                                  │    │  │
│  │  │  🛡️ Protects:                                    │    │  │
│  │  │     - ThreatIntelligenceEngine (IP reputation)  │    │  │
│  │  │     - RealTimeFirewallManager (OS firewall)     │    │  │
│  │  │     - CloudflareWAFManager (WAF rules)          │    │  │
│  │  │     - ThreatBlockingEngine (coordinated block)  │    │  │
│  │  │     - SecurityController (request validation)   │    │  │
│  │  │                                                  │    │  │
│  │  │  ⚖️ Governs:                                     │    │  │
│  │  │     - Human approval for critical actions       │    │  │
│  │  │     - Policy-based auto-blocking                │    │  │
│  │  │     - Audit logging for all actions             │    │  │
│  │  └─────────────────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────┘  │
│                              │                                 │
│              Monitors & Protects Everything Below              │
│                              ↓                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                    Protected Services                     │ │
│  │                                                           │ │
│  │  🌐 Dominion Labs (Web API, Frontend)                    │ │
│  │     - Application logs → TorinAI monitoring              │ │
│  │     - API endpoints → TorinAI protection                 │ │
│  │     - Malicious requests → Auto-blocked by TorinAI       │ │
│  │                                                           │ │
│  │  🗄️ MySQL Database (Shared)                              │ │
│  │     - Query logs → TorinAI monitoring                    │ │
│  │     - SQL injection → Detected & blocked                 │ │
│  │     - Anomalous queries → Flagged for review             │ │
│  │                                                           │ │
│  │  🖥️ System Services                                       │ │
│  │     - SSH attempts → Monitored                           │ │
│  │     - System logs → Analyzed                             │ │
│  │     - Network traffic → Inspected                        │ │
│  │                                                           │ │
│  │  🌍 Network Layer                                         │ │
│  │     - Inbound connections → Firewall filtered            │ │
│  │     - Malicious IPs → Blocked at OS level                │ │
│  │     - DDoS attacks → Mitigated via Cloudflare            │ │
│  └──────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

---

## 🔄 **How Protection Works**

### **Scenario 1: Attack on Dominion Labs**
```
1. Malicious IP 1.2.3.4 sends SQL injection to Dominion Labs API
2. ✅ TorinAI SecurityAuditWorker monitors system logs
3. ✅ Detects SQL injection pattern in Dominion Labs logs
4. ✅ Queries ThreatIntelligenceEngine: IP has 90% malicious score
5. ✅ ThreatBlockingEngine coordinates response:
   - Blocks IP at OS firewall (iptables/pf)
   - Adds IP to Cloudflare WAF blocklist
   - Notifies via Slack
6. ✅ Attack blocked system-wide in <1 second
7. ✅ Both TorinAI AND Dominion Labs protected
```

**Result**: **Dominion Labs is protected by TorinAI** ✅

---

### **Scenario 2: Shared Database Attack**
```
1. Attacker attempts SQL injection via compromised service
2. ✅ TorinAI monitors MySQL query logs (system-wide)
3. ✅ Detects malicious query pattern
4. ✅ SecurityController validates and blocks the query
5. ✅ Source IP blocked via ThreatBlockingEngine
6. ✅ Database protected for ALL services
```

**Result**: **Shared resources protected** ✅

---

### **Scenario 3: System-Wide Brute Force**
```
1. Attacker brute-forces SSH/API endpoints
2. ✅ TorinAI monitors auth logs (/var/log/auth.log)
3. ✅ Detects 100 failed login attempts from IP 5.6.7.8
4. ✅ Queries ThreatIntelligenceEngine
5. ✅ Blocks IP system-wide
6. ✅ SSH, Dominion Labs API, TorinAI all protected
```

**Result**: **System-wide protection** ✅

---

## 📂 **What TorinAI Monitors**

### **1. System Logs**
```python
# TorinAI reads system logs to detect threats
MONITORED_LOGS = [
    "/var/log/auth.log",           # SSH, login attempts
    "/var/log/syslog",              # System events
    "/var/log/apache2/access.log",  # Web server access
    "/var/log/apache2/error.log",   # Web server errors
    "/var/log/mysql/error.log",     # Database errors
    "/var/log/mysql/slow-query.log" # Slow/suspicious queries
]
```

---

### **2. Application Logs**
```python
# Dominion Labs application logs
DOMINION_LABS_LOGS = [
    "/Users/stefan/Dominion Labs/logs/api.log",
    "/Users/stefan/Dominion Labs/logs/error.log",
    "/Users/stefan/Dominion Labs/logs/security.log"
]

# TorinAI's own logs
TORINAI_LOGS = [
    "/Users/stefan/Dominion Labs/TorinAI/logs/torin_main.log",
    "/Users/stefan/Dominion Labs/TorinAI/logs/security.log"
]
```

---

### **3. Database Activity**
```python
# Monitor MySQL for ALL services
async def monitor_database_activity(self):
    """Monitor database queries for suspicious patterns"""
    # Query MySQL slow query log
    # Detect SQL injection patterns
    # Flag anomalous queries (unusual tables, DROP/DELETE, etc.)
    # Works for both TorinAI and Dominion Labs queries
```

---

### **4. Network Traffic**
```python
# OS-level network monitoring
async def monitor_network_traffic(self):
    """Monitor network connections at OS level"""
    # Track incoming connections (all services)
    # Identify connection patterns
    # Detect DDoS, port scans, brute force
    # Works across all services on the machine
```

---

## 🔧 **Implementation Requirements**

### **Phase 1: System-Wide Log Monitoring**

**Add to SecurityAuditWorker:**
```python
class SecurityAuditWorker:
    def __init__(self, config: Dict[str, Any] = None):
        # ... existing init ...

        # System-wide monitoring configuration
        self.monitor_system_logs = config.get('monitor_system_logs', True)
        self.system_log_paths = config.get('system_log_paths', [
            "/var/log/auth.log",
            "/var/log/syslog",
            "/Users/stefan/Dominion Labs/logs/",  # Dominion Labs logs
        ])

        # Log parsers for different services
        self.log_parsers = {
            'dominion_labs': DominionLabsLogParser(),
            'mysql': MySQLLogParser(),
            'system': SystemLogParser()
        }

    async def monitor_system_wide_logs(self):
        """Monitor logs from ALL services on the system"""
        while self.monitoring_active:
            for log_path in self.system_log_paths:
                try:
                    # Read and parse logs
                    findings = await self._parse_log_file(log_path)

                    # Detect threats across all services
                    for finding in findings:
                        await self._handle_security_finding(finding)

                except Exception as e:
                    logger.error(f"Failed to monitor {log_path}: {e}")

            await asyncio.sleep(5)  # Check every 5 seconds

    async def _parse_log_file(self, log_path: str) -> List[SecurityAuditFinding]:
        """Parse log file and extract security events"""
        findings = []

        # Detect which service this log belongs to
        if 'Dominion Labs' in log_path:
            parser = self.log_parsers['dominion_labs']
        elif 'mysql' in log_path:
            parser = self.log_parsers['mysql']
        else:
            parser = self.log_parsers['system']

        # Parse and detect threats
        events = await parser.parse(log_path)
        for event in events:
            if event.is_suspicious:
                finding = SecurityAuditFinding(
                    finding_id=str(uuid.uuid4()),
                    category=event.category,
                    severity=event.severity,
                    title=f"Threat detected in {event.service}",
                    description=event.description,
                    affected_components=[event.service],
                    metadata={
                        'source_service': event.service,
                        'log_file': log_path,
                        'ip_address': event.ip_address,
                        'timestamp': event.timestamp
                    }
                )
                findings.append(finding)

        return findings
```

---

### **Phase 2: Service Identification**

**TorinAI knows about protected services:**
```python
# Configuration in config.yaml
protected_services:
  - name: "dominion_labs"
    type: "web_api"
    log_paths:
      - "/Users/stefan/Dominion Labs/logs/api.log"
      - "/Users/stefan/Dominion Labs/logs/error.log"
    endpoints:
      - "http://localhost:8000"
    protection_level: "high"  # Auto-block critical threats

  - name: "mysql"
    type: "database"
    log_paths:
      - "/var/log/mysql/error.log"
      - "/var/log/mysql/slow-query.log"
    protection_level: "critical"  # Zero tolerance

  - name: "torinai"
    type: "autonomous_system"
    log_paths:
      - "/Users/stefan/Dominion Labs/TorinAI/logs/"
    protection_level: "high"
```

---

### **Phase 3: Cross-Service Threat Response**

**When threat detected in ANY service:**
```python
async def _handle_security_finding(self, finding: SecurityAuditFinding):
    """Handle security finding from ANY service"""

    # Extract source service
    source_service = finding.metadata.get('source_service', 'unknown')
    ip_address = finding.metadata.get('ip_address')

    logger.warning(f"🚨 Security threat detected in {source_service}")

    # Query threat intelligence
    if ip_address and self.threat_intel:
        intel = await self.threat_intel.get_ip_intelligence(ip_address)
        finding.metadata['threat_score'] = intel.threat_score
        finding.metadata['confidence'] = intel.confidence

    # Auto-block if critical and high confidence
    if (finding.severity == AuditSeverity.CRITICAL and
        intel.threat_score > 80 and
        self.threat_blocking):

        result = await self.threat_blocking.analyze_and_block(
            ip_address=ip_address,
            attack_type=AttackType.from_category(finding.category),
            evidence={
                'source_service': source_service,
                'finding': finding.to_dict()
            }
        )

        if result['blocked']:
            logger.info(f"✅ Blocked {ip_address} - protects ALL services system-wide")

            # Notify via Slack
            if self.slack_notifier:
                await self.slack_notifier.send_alert(
                    f"🛡️ TorinAI blocked malicious IP {ip_address}\n"
                    f"Source: {source_service}\n"
                    f"Threat: {finding.title}\n"
                    f"Protection: System-wide (all services protected)"
                )
```

---

## 🎯 **Governance Integration**

**TorinAI still respects governance even as system guardian:**

```python
# Before auto-blocking, check governance policy
from core.agents.autonomous.runtime_governance import get_runtime_governance

async def auto_block_with_governance(self, ip_address: str, threat_level: str):
    """Auto-block with governance approval"""

    governance = get_runtime_governance()

    # Check if auto-blocking is allowed
    approval = await governance.check_action_approval(
        action_type="security_block",
        action_details={
            "ip_address": ip_address,
            "threat_level": threat_level,
            "scope": "system_wide"
        }
    )

    if approval.approved or approval.auto_approved:
        # Governance says OK - execute block
        await self.threat_blocking.block_ip(ip_address)
        logger.info(f"✅ Blocked {ip_address} (governance approved)")
    else:
        # Governance requires human approval
        logger.warning(f"⏸️ Block {ip_address} pending human approval")
        await self._request_human_approval(ip_address, threat_level)
```

---

## 📊 **Benefits of System Guardian Architecture**

### **Before** (Siloed Protection):
```
Dominion Labs: No active security ❌
MySQL: No monitoring ❌
System: No threat intelligence ❌
TorinAI: Protected only itself ⚠️
```

**Protection**: 25% (TorinAI only)

---

### **After** (System Guardian):
```
Dominion Labs: Protected by TorinAI ✅
MySQL: Monitored by TorinAI ✅
System: Threat intel & firewall ✅
TorinAI: Protected ✅
```

**Protection**: 100% (entire system)

---

## 🔒 **Security Boundaries**

**TorinAI CAN:**
- ✅ Monitor ALL logs on the system
- ✅ Block IPs at OS firewall (affects all services)
- ✅ Query threat intelligence for any IP
- ✅ Protect shared resources (MySQL, network)
- ✅ Coordinate defense across services
- ✅ Log all security actions

**TorinAI CANNOT (without governance):**
- ❌ Make system changes without approval (governed)
- ❌ Block critical infrastructure IPs
- ❌ Disable services
- ❌ Modify firewall in production mode (test_mode=True)

**Governance Ensures:**
- Human oversight for critical decisions
- Audit trail of all actions
- Policy-based automation
- Override capabilities

---

## ✅ **Summary**

**Corrected Understanding:**

1. ✅ TorinAI is a **system security guardian**, not a siloed service
2. ✅ TorinAI protects **ALL services** on the host machine
3. ✅ Authorization comes from "created by Dominion Labs"
4. ✅ Governance provides human oversight
5. ✅ OS firewall blocks are system-wide (already correct)
6. ✅ SecurityAuditWorker should monitor system-wide logs
7. ✅ ThreatBlockingEngine protects all services

**Implementation Priority:**
1. Initialize integrated security system (enables capability)
2. Add system-wide log monitoring to SecurityAuditWorker
3. Configure protected services (Dominion Labs, MySQL, etc.)
4. Enable cross-service threat response
5. Integrate governance for oversight

**Result**: TorinAI as true system guardian protecting entire deployment ✅

---

**Architecture Corrected**: 2026-02-05
**Role**: System Security Guardian (not siloed service)
**Scope**: Entire host machine (all services)
