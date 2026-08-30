#!/usr/bin/env python3
"""
Test script for Slack notifications and governance system
Tests all notification types to ensure proper integration
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.integration.slack_notifier import (
    SlackNotifier,
    get_slack_notifier,
    SingletonAction,
    ActionCategory,
    DecisionTier,
    NotificationType,
    SlackChannel
)
from core.security.security_audit_worker import SecurityAuditWorker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_security_alert():
    """Test security alert notification"""
    logger.info("=" * 60)
    logger.info("TEST 1: Security Alert Notification")
    logger.info("=" * 60)

    notifier = get_slack_notifier()

    try:
        await notifier.send_security_alert(
            alert_title="Test Security Alert",
            alert_message="This is a test security alert from TorinAI notification test script",
            severity="HIGH",
            metadata={
                'test': True,
                'component': 'notification_test',
                'timestamp': '2026-01-08'
            }
        )
        logger.info("✅ Security alert sent successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Security alert failed: {e}")
        return False


async def test_governance_session():
    """Test governance session notification"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 2: Governance Session Notification")
    logger.info("=" * 60)

    notifier = get_slack_notifier()

    # Create a test action
    action = SingletonAction(
        action_id="test_action_001",
        action_category=ActionCategory.CONFIGURATION_CHANGES,
        action_type="TEST_GOVERNANCE_NOTIFICATION",
        description="This is a test governance session notification",
        decision_tier=DecisionTier.CRITICAL,
        requires_governance=True,
        requires_approval=False,
        safety_risk="HIGH",
        impact_level="HIGH"
    )

    try:
        await notifier.notify_singleton_action(
            action=action,
            commitment_contract_id="test_contract_001"
        )
        logger.info("✅ Governance session notification sent successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Governance session notification failed: {e}")
        return False


async def test_approval_request():
    """Test approval request notification"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 3: Approval Request Notification")
    logger.info("=" * 60)

    notifier = get_slack_notifier()

    # Create a test action requiring approval
    action = SingletonAction(
        action_id="test_action_002",
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="TEST_APPROVAL_REQUEST",
        description="This is a test approval request notification",
        decision_tier=DecisionTier.IMPORTANT,
        requires_governance=False,
        requires_approval=True,
        safety_risk="MODERATE",
        impact_level="MEDIUM"
    )

    try:
        await notifier.notify_singleton_action(
            action=action,
            commitment_contract_id="test_contract_002"
        )
        logger.info("✅ Approval request notification sent successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Approval request notification failed: {e}")
        return False


async def test_informational_message():
    """Test informational message notification"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 4: Informational Message Notification")
    logger.info("=" * 60)

    notifier = get_slack_notifier()

    # Create a routine action
    action = SingletonAction(
        action_id="test_action_003",
        action_category=ActionCategory.CURIOSITY_EXPLORATION,
        action_type="TEST_INFORMATIONAL_MESSAGE",
        description="This is a test informational message notification",
        decision_tier=DecisionTier.ROUTINE,
        requires_governance=False,
        requires_approval=False,
        safety_risk="LOW",
        impact_level="LOW"
    )

    try:
        await notifier.notify_singleton_action(
            action=action,
            commitment_contract_id="test_contract_003"
        )
        logger.info("✅ Informational message sent successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Informational message failed: {e}")
        return False


async def test_learning_milestone():
    """Test learning milestone notification"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 5: Learning Milestone Notification")
    logger.info("=" * 60)

    notifier = get_slack_notifier()

    try:
        await notifier.send_learning_milestone(
            milestone_title="Test Learning Milestone",
            milestone_description="TorinAI notification test: Learning milestone achieved",
            metrics={
                'test_accuracy': 0.95,
                'training_samples': 1000,
                'model_version': 'test_v1.0',
                'improvement': '+5%'
            }
        )
        logger.info("✅ Learning milestone notification sent successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Learning milestone notification failed: {e}")
        return False


async def test_security_audit_integration():
    """Test security audit worker integration with Slack"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 6: Security Audit Worker Integration")
    logger.info("=" * 60)

    # Create security audit worker
    audit_worker = SecurityAuditWorker()

    # Set up Slack notifier integration
    notifier = get_slack_notifier()
    audit_worker.set_slack_notifier(notifier)

    logger.info("✅ Security audit worker integrated with Slack notifier")

    # Note: We won't run a full audit as it requires database
    # Just verify the integration is set up correctly
    if audit_worker.slack_notifier is not None:
        logger.info("✅ Slack notifier properly configured in audit worker")
        return True
    else:
        logger.error("❌ Slack notifier not configured in audit worker")
        return False


async def test_notification_statistics():
    """Test notification statistics"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 7: Notification Statistics")
    logger.info("=" * 60)

    notifier = get_slack_notifier()
    stats = await notifier.get_statistics()

    logger.info(f"Total notifications sent: {stats['total_notifications']}")
    logger.info(f"Security alerts: {stats['security_alerts']}")
    logger.info(f"Governance sessions: {stats['governance_sessions']}")
    logger.info(f"Approval requests: {stats['approval_requests']}")
    logger.info(f"Pending approvals: {stats['pending_approvals']}")
    logger.info(f"Active governance sessions: {stats['active_governance_sessions']}")

    logger.info("✅ Statistics retrieved successfully")
    return True


async def main():
    """Run all notification tests"""
    logger.info("")
    logger.info("╔" + "=" * 58 + "╗")
    logger.info("║" + " " * 58 + "║")
    logger.info("║" + "  TorinAI Slack Notification & Governance System Test  ".center(58) + "║")
    logger.info("║" + " " * 58 + "║")
    logger.info("╚" + "=" * 58 + "╝")
    logger.info("")

    # Run all tests
    results = []

    results.append(("Security Alert", await test_security_alert()))
    await asyncio.sleep(1)  # Rate limit between tests

    results.append(("Governance Session", await test_governance_session()))
    await asyncio.sleep(1)

    results.append(("Approval Request", await test_approval_request()))
    await asyncio.sleep(1)

    results.append(("Informational Message", await test_informational_message()))
    await asyncio.sleep(1)

    results.append(("Learning Milestone", await test_learning_milestone()))
    await asyncio.sleep(1)

    results.append(("Security Audit Integration", await test_security_audit_integration()))

    results.append(("Notification Statistics", await test_notification_statistics()))

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")

    logger.info("")
    logger.info(f"Results: {passed}/{total} tests passed")

    if passed == total:
        logger.info("🎉 All tests passed successfully!")
        return 0
    else:
        logger.error(f"⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
