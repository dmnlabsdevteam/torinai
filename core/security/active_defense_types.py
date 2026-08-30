#!/usr/bin/env python3
"""
Active Defense Data Structures - Military-Grade Security Types
Extended security types for active threat blocking and real-time defense
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .security_types import SecurityLevel, ThreatType, AlertSeverity, Priority


# ================================================================================================
# ACTIVE DEFENSE ENUMS
# ================================================================================================

class AttackType(Enum):
    """Types of attacks detected"""
    BRUTE_FORCE = "brute_force"           # Login brute force attempts
    SQL_INJECTION = "sql_injection"        # SQL injection attacks
    XSS_ATTACK = "xss_attack"             # Cross-site scripting
    CSRF_ATTACK = "csrf_attack"           # Cross-site request forgery
    PATH_TRAVERSAL = "path_traversal"     # Directory traversal attacks
    COMMAND_INJECTION = "command_injection" # OS command injection
    DDOS = "ddos"                         # DDoS attack
    PORT_SCAN = "port_scan"               # Port scanning
    VULNERABILITY_SCAN = "vulnerability_scan" # Vulnerability scanning
    API_ABUSE = "api_abuse"               # API rate limit abuse
    BOT_ATTACK = "bot_attack"             # Automated bot attacks
    CREDENTIAL_STUFFING = "credential_stuffing" # Credential stuffing
    ZERO_DAY = "zero_day"                 # Zero-day exploit attempt
    MALWARE_UPLOAD = "malware_upload"     # Malicious file upload
    DATA_EXFILTRATION = "data_exfiltration" # Data theft attempt


class DefenseAction(Enum):
    """Actions taken in defense"""
    BLOCK_IP = "block_ip"                 # Block IP address
    BLOCK_COUNTRY = "block_country"       # Geo-blocking
    BLOCK_ASN = "block_asn"               # Block entire ASN
    RATE_LIMIT = "rate_limit"             # Apply rate limiting
    CHALLENGE = "challenge"               # Issue CAPTCHA/JS challenge
    QUARANTINE = "quarantine"             # Quarantine suspicious activity
    TERMINATE_SESSION = "terminate_session" # Force session termination
    DROP_CONNECTION = "drop_connection"   # Drop TCP connection
    REJECT_REQUEST = "reject_request"     # Reject HTTP request
    LOG_ONLY = "log_only"                 # Log without blocking
    ALERT_ADMIN = "alert_admin"           # Alert administrator
    ESCALATE = "escalate"                 # Escalate to human review


class BlockDuration(Enum):
    """Duration for blocking actions"""
    TEMPORARY_5M = 300                    # 5 minutes
    TEMPORARY_1H = 3600                   # 1 hour
    TEMPORARY_24H = 86400                 # 24 hours
    TEMPORARY_7D = 604800                 # 7 days
    PERMANENT = -1                        # Permanent block


class ThreatConfidence(Enum):
    """Confidence level in threat assessment"""
    LOW = "low"                           # 0-30% confidence
    MEDIUM = "medium"                     # 30-60% confidence
    HIGH = "high"                         # 60-85% confidence
    CRITICAL = "critical"                 # 85-100% confidence


class FirewallRuleAction(Enum):
    """Firewall rule actions"""
    ACCEPT = "accept"
    DROP = "drop"
    REJECT = "reject"
    LOG = "log"
    REDIRECT = "redirect"


class FirewallChain(Enum):
    """Firewall chains for iptables/nftables"""
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    FORWARD = "FORWARD"
    PREROUTING = "PREROUTING"
    POSTROUTING = "POSTROUTING"


class WAFRuleMode(Enum):
    """Cloudflare WAF rule modes"""
    BLOCK = "block"
    CHALLENGE = "challenge"
    JS_CHALLENGE = "js_challenge"
    MANAGED_CHALLENGE = "managed_challenge"
    LOG = "log"
    ALLOW = "allow"


class ThreatIntelSource(Enum):
    """Threat intelligence sources"""
    ABUSEIPDB = "abuseipdb"
    VIRUSTOTAL = "virustotal"
    OTX_ALIENVAULT = "otx_alienvault"
    SHODAN = "shodan"
    CROWDSEC = "crowdsec"
    FAIL2BAN = "fail2ban"
    INTERNAL = "internal"
    CLOUDFLARE = "cloudflare"


# ================================================================================================
# CORE DATA STRUCTURES
# ================================================================================================

@dataclass
class BlockedEntity:
    """Represents a blocked IP, network, or country"""
    entity_id: str
    entity_type: str  # "ip", "network", "country", "asn"
    entity_value: str
    reason: str
    attack_type: AttackType
    blocked_at: float = field(default_factory=lambda: datetime.now().timestamp())
    expires_at: Optional[float] = None
    block_count: int = 1
    defense_action: DefenseAction = DefenseAction.BLOCK_IP
    confidence: ThreatConfidence = ThreatConfidence.HIGH
    source: str = "active_defense"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FirewallRule:
    """OS firewall rule (iptables/pf)"""
    rule_id: str
    chain: FirewallChain
    action: FirewallRuleAction
    protocol: Optional[str] = None  # tcp, udp, icmp, all
    source_ip: Optional[str] = None
    source_port: Optional[int] = None
    dest_ip: Optional[str] = None
    dest_port: Optional[int] = None
    interface: Optional[str] = None
    comment: str = ""
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    priority: int = 100
    active: bool = True


@dataclass
class WAFRule:
    """Cloudflare WAF rule"""
    rule_id: str
    zone_id: str
    description: str
    expression: str  # Cloudflare rule expression
    action: WAFRuleMode
    priority: int = 1
    enabled: bool = True
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    cloudflare_rule_id: Optional[str] = None  # ID from Cloudflare API
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ThreatIntelligence:
    """Threat intelligence data"""
    intel_id: str
    ip_address: str
    reputation_score: float  # 0.0 = clean, 1.0 = highly malicious
    confidence: ThreatConfidence
    sources: List[ThreatIntelSource]
    threat_types: List[AttackType]
    first_seen: float
    last_seen: float
    report_count: int = 0
    country: Optional[str] = None
    asn: Optional[int] = None
    isp: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AttackPattern:
    """Detected attack pattern"""
    pattern_id: str
    attack_type: AttackType
    signature: str  # Pattern signature/hash
    indicators: List[str]  # IOCs (Indicators of Compromise)
    frequency: int  # How many times detected
    severity: AlertSeverity
    first_detected: float
    last_detected: float
    affected_endpoints: List[str] = field(default_factory=list)
    source_ips: Set[str] = field(default_factory=set)
    success_rate: float = 0.0  # Percentage of successful attempts
    mitigation_applied: bool = False


@dataclass
class IncidentReport:
    """Security incident report"""
    incident_id: str
    attack_type: AttackType
    severity: AlertSeverity
    confidence: ThreatConfidence
    
    # Attack details
    source_ip: str
    target: str
    start_time: float
    end_time: Optional[float] = None
    request_count: int = 0
    
    # Response details
    actions_taken: List[DefenseAction] = field(default_factory=list)
    blocked: bool = False
    mitigated: bool = False
    
    # Context
    user_agent: Optional[str] = None
    attack_vectors: List[str] = field(default_factory=list)
    payload_samples: List[str] = field(default_factory=list)
    
    # Analysis
    threat_intelligence: Optional[ThreatIntelligence] = None
    attack_pattern: Optional[AttackPattern] = None
    damage_assessment: str = ""
    recommendations: List[str] = field(default_factory=list)
    
    # Metadata
    analyst_notes: str = ""
    reported_to: List[str] = field(default_factory=list)
    resolution: Optional[str] = None


@dataclass
class DDoSAttackMetrics:
    """DDoS attack detection metrics"""
    requests_per_second: float
    unique_ips: int
    bandwidth_mbps: float
    connection_count: int
    syn_flood_rate: float
    udp_flood_rate: float
    http_flood_rate: float
    average_packet_size: float
    top_source_countries: List[Tuple[str, int]]
    detection_threshold_exceeded: bool
    attack_duration_seconds: float
    estimated_botnet_size: int


@dataclass
class DefensePolicy:
    """Active defense policy configuration"""
    policy_id: str
    name: str
    enabled: bool = True
    
    # Thresholds
    block_threshold_score: float = 0.7  # Threat score to trigger blocking
    rate_limit_threshold: int = 100  # Requests per minute
    brute_force_attempts: int = 5  # Failed login attempts
    
    # Actions
    auto_block_enabled: bool = True
    auto_rate_limit_enabled: bool = True
    geo_blocking_enabled: bool = False
    challenge_suspicious_enabled: bool = True
    
    # Durations
    default_block_duration: BlockDuration = BlockDuration.TEMPORARY_1H
    escalation_block_duration: BlockDuration = BlockDuration.TEMPORARY_24H
    permanent_block_threshold: int = 3  # Blocks before permanent
    
    # Whitelists/Blacklists
    whitelisted_ips: Set[str] = field(default_factory=set)
    whitelisted_countries: Set[str] = field(default_factory=set)
    blacklisted_ips: Set[str] = field(default_factory=set)
    blacklisted_countries: Set[str] = field(default_factory=set)
    blacklisted_asns: Set[int] = field(default_factory=set)
    
    # Threat Intelligence
    use_threat_intel: bool = True
    intel_sources: List[ThreatIntelSource] = field(default_factory=lambda: [
        ThreatIntelSource.ABUSEIPDB,
        ThreatIntelSource.CLOUDFLARE,
        ThreatIntelSource.INTERNAL
    ])
    
    # Notifications
    alert_on_block: bool = True
    alert_on_ddos: bool = True
    alert_email: Optional[str] = None
    alert_webhook: Optional[str] = None


@dataclass
class DefenseMetrics:
    """Active defense system metrics"""
    # Blocking stats
    total_blocks: int = 0
    active_blocks: int = 0
    temporary_blocks: int = 0
    permanent_blocks: int = 0
    
    # Attack stats
    attacks_detected: int = 0
    attacks_mitigated: int = 0
    ddos_attacks_blocked: int = 0
    
    # By type
    blocks_by_type: Dict[AttackType, int] = field(default_factory=dict)
    blocks_by_country: Dict[str, int] = field(default_factory=dict)
    
    # Firewall stats
    firewall_rules_active: int = 0
    waf_rules_active: int = 0
    
    # Performance
    avg_detection_time_ms: float = 0.0
    avg_response_time_ms: float = 0.0
    false_positive_rate: float = 0.0
    
    # Timing
    start_time: float = field(default_factory=lambda: datetime.now().timestamp())
    last_update: float = field(default_factory=lambda: datetime.now().timestamp())


# ================================================================================================
# HELPER FUNCTIONS
# ================================================================================================

def create_default_defense_policy() -> DefensePolicy:
    """Create default defense policy with reasonable defaults"""
    return DefensePolicy(
        policy_id="default_policy",
        name="Default Active Defense Policy",
        enabled=True,
        block_threshold_score=0.7,
        rate_limit_threshold=100,
        brute_force_attempts=5,
        auto_block_enabled=True,
        auto_rate_limit_enabled=True,
        geo_blocking_enabled=False,
        challenge_suspicious_enabled=True,
        default_block_duration=BlockDuration.TEMPORARY_1H,
        use_threat_intel=True
    )


def calculate_threat_score(
    intel: Optional[ThreatIntelligence],
    attack_history: int,
    confidence: ThreatConfidence
) -> float:
    """Calculate overall threat score (0.0 - 1.0)"""
    score = 0.0
    
    # Threat intelligence contribution (0-0.6)
    if intel:
        score += intel.reputation_score * 0.6
    
    # Attack history contribution (0-0.25)
    if attack_history > 0:
        score += min(attack_history * 0.05, 0.25)
    
    # Confidence contribution (0-0.15)
    confidence_scores = {
        ThreatConfidence.LOW: 0.05,
        ThreatConfidence.MEDIUM: 0.08,
        ThreatConfidence.HIGH: 0.12,
        ThreatConfidence.CRITICAL: 0.15
    }
    score += confidence_scores.get(confidence, 0.0)
    
    return min(score, 1.0)


def should_block(threat_score: float, policy: DefensePolicy) -> bool:
    """Determine if entity should be blocked based on threat score"""
    return threat_score >= policy.block_threshold_score and policy.auto_block_enabled


def determine_block_duration(
    threat_score: float,
    previous_blocks: int,
    policy: DefensePolicy
) -> BlockDuration:
    """Determine appropriate block duration"""
    # Permanent block after threshold
    if previous_blocks >= policy.permanent_block_threshold:
        return BlockDuration.PERMANENT
    
    # Escalate based on threat score and history
    if threat_score >= 0.9 or previous_blocks >= 2:
        return policy.escalation_block_duration
    
    return policy.default_block_duration
