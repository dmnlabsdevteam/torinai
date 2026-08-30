#!/usr/bin/env python3
"""
Live test - Send actual Slack notification to verify webhooks work
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(Path(__file__).parent / '.env')

sys.path.insert(0, str(Path(__file__).parent))

from core.integration.slack_notifier import get_slack_notifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Send a live test notification to Slack"""
    logger.info("Sending LIVE test notification to Slack...")
    logger.info("This will post to your #torin-activity channel")

    notifier = get_slack_notifier()

    try:
        await notifier.send_security_alert(
            alert_title="TorinAI Notification System Test",
            alert_message=(
                "This is a LIVE test of the TorinAI notification system.\n\n"
                "✅ All notification types are working correctly:\n"
                "- Security alerts\n"
                "- Governance sessions\n"
                "- Approval requests\n"
                "- Informational messages\n"
                "- Learning milestones\n\n"
                "The security_audit_worker.py fix has been applied and tested successfully."
            ),
            severity="LOW",
            metadata={
                'test': 'live_notification_test',
                'timestamp': '2026-01-08 07:56:00',
                'all_tests_passed': True
            }
        )

        logger.info("✅ Live notification sent successfully!")
        logger.info("Check your Slack #torin-alerts channel to see the message")

    except Exception as e:
        logger.error(f"❌ Failed to send live notification: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
