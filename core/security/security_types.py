#!/usr/bin/env python3
"""
TorinAI Security Types - Core Security Data Structures and Enums
Consolidated security types for the autonomous security system
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple, Union, Callable
from dataclasses import dataclass, field
from enum import Enum

# ================================================================================================
# UNIFIED ENUMS AND DATA STRUCTURES
# ================================================================================================

class SecurityLevel(Enum):
    """Unified security levels across all security components"""
    PUBLIC = "public"              # Basic security for public content
    INTERNAL = "internal"          # Internal company use
    CONFIDENTIAL = "confidential"  # Confidential information
    RESTRICTED = "restricted"      # Restricted access
    TOP_SECRET = "top_secret"      # Highest security level
    
    # Compatibility mappings
    LOW = "public"                 # safety.py compatibility
    MEDIUM = "internal"            # safety.py compatibility  
    HIGH = "confidential"          # safety.py compatibility
    CRITICAL = "top_secret"        # safety.py compatibility
    
    PERMISSIVE = "public"          # security.py compatibility
    BALANCED = "internal"          # security.py compatibility
    SECURE = "top_secret"          # security.py compatibility

class ThreatType(Enum):
    """Types of security threats"""
    INJECTION = "injection"                    # Code/SQL injection attempts
    MANIPULATION = "manipulation"              # Data manipulation attempts
    EXTRACTION = "extraction"                  # Information extraction attempts
    CORRUPTION = "corruption"                  # Data corruption attempts
    DENIAL_OF_SERVICE = "dos"                 # DoS attacks
    ILLEGAL_CONTENT = "illegal_content"       # Illegal activity content
    CONFIDENTIAL_BREACH = "confidential_breach" # Confidential info exposure
    PII_EXPOSURE = "pii_exposure"             # Personal info exposure
    MALICIOUS_PATTERN = "malicious_pattern"   # Harmful behavior patterns
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded" # Rate limiting violations

class ContentType(Enum):
    """Types of content being processed"""
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    CODE = "code"
    DATA = "data"

class ValidationResult(Enum):
    """Results of validation operations"""
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    SANITIZED = "sanitized"
    WARNING = "warning"
    ERROR = "error"

class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class RecoveryAction(Enum):
    """Types of recovery actions"""
    BLOCK_REQUEST = "block_request"
    SANITIZE_CONTENT = "sanitize_content"
    LOG_EVENT = "log_event"
    ALERT_ADMIN = "alert_admin"
    RATE_LIMIT = "rate_limit"
    TERMINATE_SESSION = "terminate_session"
    QUARANTINE_USER = "quarantine_user"

class Priority(Enum):
    """Priority levels for security operations"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AgentType(Enum):
    """Swarm agent types for digital footprint scrubbing"""
    HUNTER = "hunter"              # Finds digital traces
    ANALYZER = "analyzer"          # Analyzes trace content
    SCRUBBER = "scrubber"          # Removes traces
    VALIDATOR = "validator"        # Validates cleanup
    GUARDIAN = "guardian"          # Monitors for new traces
    
    # External operation specialists
    NETWORK_HUNTER = "network_hunter"      # Scans network logs and connections
    BROWSER_SCRUBBER = "browser_scrubber"  # Cleans browser data and cookies
    API_CLEANER = "api_cleaner"            # Removes API tokens and call logs
    DNS_GUARDIAN = "dns_guardian"          # Monitors and cleans DNS queries
    PROXY_AGENT = "proxy_agent"            # Handles proxy/VPN trace cleanup
    WEB_TRACER = "web_tracer"              # Specialized web search trace cleanup

class ContentCategory(Enum):
    """Categories of content filtering"""
    ILLEGAL_DRUGS = "illegal_drugs"
    VIOLENCE = "violence"
    ILLEGAL_ACTIVITIES = "illegal_activities"
    CONFIDENTIAL_INFO = "confidential_info"
    PII_DATA = "pii_data"
    SYSTEM_EXPLOITS = "system_exploits"
    MALICIOUS_CODE = "malicious_code"

# ================================================================================================
# CORE DATA STRUCTURES
# ================================================================================================

@dataclass
class SecurityContext:
    """Unified security context for all operations"""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    operation: Optional[str] = None
    data_sensitivity: SecurityLevel = SecurityLevel.INTERNAL
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    
    # Content-specific context
    content_type: Optional[str] = None
    content_length: int = 0
    
    # Operation context
    request_count: int = 0
    last_activity: float = field(default_factory=lambda: datetime.now().timestamp())

@dataclass
class SecurityThreat:
    """Unified threat detection data structure"""
    threat_id: str
    threat_type: ThreatType
    severity: AlertSeverity
    description: str
    
    # Detection details
    detected_at: float = field(default_factory=lambda: datetime.now().timestamp())
    detected_by: str = "security_master"
    
    # Context
    context: Optional[SecurityContext] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    # Response
    blocked: bool = False
    sanitized: bool = False
    actions_taken: List[RecoveryAction] = field(default_factory=list)
    
    # Resolution
    resolved: bool = False
    resolved_at: Optional[float] = None
    resolution_notes: str = ""

# Legacy compatibility alias
ThreatReport = SecurityThreat

@dataclass
class DigitalTrace:
    """Digital trace for footprint scrubbing"""
    trace_id: str
    location: str
    trace_type: str
    risk_level: Priority
    content_size: int
    last_accessed: datetime
    
    # Metadata
    discovered_at: float = field(default_factory=lambda: datetime.now().timestamp())
    cleaned: bool = False
    cleaned_at: Optional[float] = None

@dataclass
class SwarmAgent:
    """Individual agent in the digital footprint scrubbing swarm"""
    agent_id: str
    agent_type: AgentType
    specialization: str
    capabilities: List[str]
    status: str = "active"
    performance_rating: float = 1.0
    
    # Statistics
    traces_found: int = 0
    traces_cleaned: int = 0
    operations_performed: int = 0
    last_activity: float = field(default_factory=lambda: datetime.now().timestamp())

@dataclass
class SecurityPolicy:
    """Unified security policy configuration"""
    # General settings
    security_level: SecurityLevel = SecurityLevel.INTERNAL
    max_input_length: int = 10000
    max_output_length: int = 50000
    
    # Rate limiting
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000
    
    # Content filtering
    enable_content_filtering: bool = True
    enable_pii_detection: bool = True
    enable_illegal_content_blocking: bool = True
    content_strictness_multiplier: float = 1.0
    
    # System security
    enable_injection_detection: bool = True
    enable_path_traversal_detection: bool = True
    enable_response_sanitization: bool = True
    
    # Digital footprint
    enable_footprint_monitoring: bool = True
    enable_real_time_cleanup: bool = True
    footprint_scan_interval: int = 300  # 5 minutes
    
    # Session management
    require_authentication: bool = True
    session_timeout: int = 86400  # 24 hours
    max_concurrent_sessions: int = 10
    
    # Logging and monitoring
    log_all_operations: bool = True
    log_security_events: bool = True
    alert_on_threats: bool = True
    
    # Allowed operations and patterns
    allowed_operations: List[str] = field(default_factory=list)
    blocked_patterns: List[str] = field(default_factory=list)
    allowed_file_types: List[str] = field(default_factory=lambda: [".txt", ".md", ".py", ".js", ".json"])

@dataclass
class SecurityMetrics:
    """Security system metrics and statistics"""
    # General metrics
    total_requests: int = 0
    blocked_requests: int = 0
    sanitized_responses: int = 0
    
    # Threat metrics
    threats_detected: int = 0
    threats_by_type: Dict[str, int] = field(default_factory=dict)
    critical_threats: int = 0
    
    # Content filtering metrics
    content_filtered: int = 0
    illegal_content_blocked: int = 0
    pii_detected: int = 0
    confidential_breaches: int = 0
    
    # Digital footprint metrics
    traces_found: int = 0
    traces_cleaned: int = 0
    real_time_cleanups: int = 0
    monitoring_cycles: int = 0
    
    # Performance metrics
    average_response_time: float = 0.0
    system_uptime: float = 0.0

__all__ = [
    # Enums
    'SecurityLevel', 'ThreatType', 'ContentType', 'ValidationResult', 
    'AlertSeverity', 'RecoveryAction', 'Priority', 'AgentType', 'ContentCategory',
    
    # Data structures
    'SecurityContext', 'SecurityThreat', 'ThreatReport', 'DigitalTrace', 
    'SwarmAgent', 'SecurityPolicy', 'SecurityMetrics'
]