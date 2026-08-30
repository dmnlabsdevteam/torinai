import unittest
from core.security.security_types import SecurityLevel, ThreatType, ValidationResult, AlertSeverity, RecoveryAction, Priority, AgentType


class TestSecurityTypes(unittest.TestCase):

    def test_security_level(self):
        self.assertIn(SecurityLevel.PUBLIC, SecurityLevel)
        self.assertIn(SecurityLevel.INTERNAL, SecurityLevel)
        self.assertIn(SecurityLevel.CONFIDENTIAL, SecurityLevel)
        self.assertIn(SecurityLevel.RESTRICTED, SecurityLevel)
        self.assertIn(SecurityLevel.TOP_SECRET, SecurityLevel)

    def test_threat_type(self):
        self.assertIn(ThreatType.INJECTION, ThreatType)
        self.assertIn(ThreatType.MANIPULATION, ThreatType)
        self.assertIn(ThreatType.EXTRACTION, ThreatType)
        self.assertIn(ThreatType.CORRUPTION, ThreatType)
        self.assertIn(ThreatType.DENIAL_OF_SERVICE, ThreatType)
        self.assertIn(ThreatType.ILLEGAL_CONTENT, ThreatType)
        self.assertIn(ThreatType.CONFIDENTIAL_BREACH, ThreatType)
        self.assertIn(ThreatType.PII_EXPOSURE, ThreatType)
        self.assertIn(ThreatType.MALICIOUS_PATTERN, ThreatType)
        self.assertIn(ThreatType.RATE_LIMIT_EXCEEDED, ThreatType)

    def test_validation_result(self):
        self.assertIn(ValidationResult.ALLOWED, ValidationResult)
        self.assertIn(ValidationResult.BLOCKED, ValidationResult)
        self.assertIn(ValidationResult.SANITIZED, ValidationResult)
        self.assertIn(ValidationResult.WARNING, ValidationResult)
        self.assertIn(ValidationResult.ERROR, ValidationResult)

    def test_alert_severity(self):
        self.assertIn(AlertSeverity.INFO, AlertSeverity)
        self.assertIn(AlertSeverity.WARNING, AlertSeverity)
        self.assertIn(AlertSeverity.ERROR, AlertSeverity)
        self.assertIn(AlertSeverity.CRITICAL, AlertSeverity)

    def test_recovery_action(self):
        self.assertIn(RecoveryAction.BLOCK_REQUEST, RecoveryAction)
        self.assertIn(RecoveryAction.SANITIZE_CONTENT, RecoveryAction)
        self.assertIn(RecoveryAction.LOG_EVENT, RecoveryAction)
        self.assertIn(RecoveryAction.ALERT_ADMIN, RecoveryAction)
        self.assertIn(RecoveryAction.RATE_LIMIT, RecoveryAction)
        self.assertIn(RecoveryAction.TERMINATE_SESSION, RecoveryAction)
        self.assertIn(RecoveryAction.QUARANTINE_USER, RecoveryAction)

    def test_priority(self):
        self.assertIn(Priority.LOW, Priority)
        self.assertIn(Priority.MEDIUM, Priority)
        self.assertIn(Priority.HIGH, Priority)
        self.assertIn(Priority.CRITICAL, Priority)

    def test_agent_type(self):
        self.assertIn(AgentType.HUNTER, AgentType)
        self.assertIn(AgentType.ANALYZER, AgentType)
        self.assertIn(AgentType.SCRUBBER, AgentType)
        self.assertIn(AgentType.VALIDATOR, AgentType)
        self.assertIn(AgentType.GUARDIAN, AgentType)
        self.assertIn(AgentType.NETWORK_HUNTER, AgentType)
        self.assertIn(AgentType.BROWSER_SCRUBBER, AgentType)
        self.assertIn(AgentType.API_CLEANER, AgentType)

if __name__ == '__main__':
    unittest.main()