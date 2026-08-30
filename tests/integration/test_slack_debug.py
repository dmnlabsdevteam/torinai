#!/usr/bin/env python3
"""Quick debug test for Slack integration"""

import pytest
import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_direct_slack():
    """Test Slack notifier directly"""
    from core.integration.slack_notifier import get_slack_notifier, SlackChannel

    slack = get_slack_notifier()

    logger.info("Testing direct Slack notification...")
    result = await slack.send_notification(
        message="Test message from debug script",
        title="Debug Test",
        channel=SlackChannel.ACTIVITY,
        severity="info"
    )

    logger.info(f"Result: {result}")
    return result

@pytest.mark.asyncio
async def test_slack_tools():
    """Test slack_tools functions"""
    from core.tools.slack_tools import ask_for_clarification

    context = {
        "source_type": "internal",
        "agent_type": "test",
        "user_type": "internal"
    }

    logger.info("Testing ask_for_clarification...")
    result = await ask_for_clarification(
        question="Test question from debug script",
        task="Debug testing",
        context=context
    )

    logger.info(f"Result: {result}")
    return result

async def main():
    logger.info("="*70)
    logger.info("SLACK DEBUG TEST")
    logger.info("="*70)

    # Test 1: Direct slack notifier
    logger.info("\n1. Testing SlackNotifier directly...")
    r1 = await test_direct_slack()

    # Test 2: Through slack_tools
    logger.info("\n2. Testing through slack_tools...")
    r2 = await test_slack_tools()

    logger.info("\n" + "="*70)
    logger.info("RESULTS:")
    logger.info(f"  Direct SlackNotifier: {r1}")
    logger.info(f"  Through slack_tools: {r2}")
    logger.info("="*70)

if __name__ == "__main__":
    asyncio.run(main())
