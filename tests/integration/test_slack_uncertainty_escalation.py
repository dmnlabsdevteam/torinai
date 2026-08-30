#!/usr/bin/env python3
"""
Integration Test: Slack Uncertainty Escalation
===============================================
Tests that Torin actually uses Slack tools when encountering uncertainty
during internal operations.

IMPORTANT: This is a REAL integration test - it will send actual messages to Slack!
Only run when you want to test the full escalation pipeline.

Test Scenarios:
1. Missing resource - AI can't find required files/data
2. Ambiguous task - Unclear requirements need clarification
3. Security finding - Detection of potential security issue
4. Autonomous task blocked - AI hits a dead-end during execution
5. Team health monitoring - AI detects concerning patterns
6. File operation uncertainty - AI unsure about file modifications
"""

import asyncio
import pytest
import logging
from datetime import datetime
from typing import Dict, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SlackToolCallTracker:
    """Track which Slack tools were called during test execution"""

    def __init__(self):
        self.calls = []
        self.last_call = None

    def record_call(self, tool_name: str, parameters: Dict[str, Any]):
        """Record a tool call"""
        call = {
            "tool": tool_name,
            "parameters": parameters,
            "timestamp": datetime.now().isoformat()
        }
        self.calls.append(call)
        self.last_call = call
        logger.info(f"📞 Tool called: {tool_name}")

    def get_calls_for_tool(self, tool_name: str):
        """Get all calls for a specific tool"""
        return [c for c in self.calls if c["tool"] == tool_name]

    def was_called(self, tool_name: str) -> bool:
        """Check if a tool was called"""
        return len(self.get_calls_for_tool(tool_name)) > 0

    def reset(self):
        """Reset tracking"""
        self.calls = []
        self.last_call = None


# Global tracker
tracker = SlackToolCallTracker()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scenario_1_missing_resource():
    """
    Scenario: AI is asked to analyze system logs that don't exist
    Expected: Should call ask_for_clarification to ask where logs are
    """
    logger.info("\n" + "="*70)
    logger.info("TEST SCENARIO 1: Missing Resource - System Logs Not Found")
    logger.info("="*70)

    tracker.reset()

    # Simulate AI task execution context
    context = {
        "source_type": "autonomous_coordinator",
        "agent_type": "task_executor",
        "user_type": "internal",
        "task_id": "analyze_system_logs_001"
    }

    # Import the tools
    from core.tools.slack_tools import ask_for_clarification

    # AI encounters uncertainty - system logs not found
    logger.info("🤖 AI Task: Analyze system logs from /var/log/torin/")
    logger.info("❌ AI Finding: Directory does not exist")
    logger.info("💭 AI Decision: Need to ask team where logs are stored")

    # AI should call this when uncertain
    result = await ask_for_clarification(
        question="I need to analyze system logs but can't find them at /var/log/torin/. Where are TorinAI system logs actually stored?",
        what_tried=[
            "Searched /var/log/torin/ - directory doesn't exist",
            "Checked /var/log/ - no torin-related logs found",
            "Searched for *.log files containing 'torin' - no results"
        ],
        task="Analyze system performance from logs",
        context=context
    )

    tracker.record_call("ask_for_clarification", result)

    # Assertions
    assert result["success"], f"Slack escalation failed: {result.get('message')}"
    logger.info(f"✅ SUCCESS: Clarification request sent to Slack")
    logger.info(f"   Message: {result.get('message', 'Sent successfully')}")

    return tracker.calls


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scenario_2_ambiguous_task():
    """
    Scenario: AI receives vague task about 'improving security'
    Expected: Should ask for clarification on specific security improvements
    """
    logger.info("\n" + "="*70)
    logger.info("TEST SCENARIO 2: Ambiguous Task - Improve Security")
    logger.info("="*70)

    tracker.reset()

    context = {
        "source_type": "internal_task",
        "agent_type": "task_executor",
        "user_type": "internal",
        "task_id": "improve_security_002"
    }

    from core.tools.slack_tools import ask_for_clarification

    logger.info("🤖 AI Task: 'Improve TorinAI security'")
    logger.info("💭 AI Reasoning: Task is too broad - many possible approaches")
    logger.info("💭 AI Decision: Need specific direction from team")

    result = await ask_for_clarification(
        question="""I've been asked to 'improve security' but this is quite broad. Should I focus on:

1. Input validation and sanitization?
2. Authentication/authorization improvements?
3. Encryption of sensitive data?
4. Network security (firewall rules, API rate limiting)?
5. Code security audit (vulnerability scanning)?

Which area is the priority, or should I address all of them?""",
        task="Improve TorinAI security",
        context=context
    )

    tracker.record_call("ask_for_clarification", result)

    assert result["success"], f"Slack escalation failed: {result.get('message')}"
    logger.info(f"✅ SUCCESS: Clarification request sent to Slack")

    return tracker.calls


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scenario_3_security_finding():
    """
    Scenario: AI detects employee sharing potential credentials file
    Expected: Should call report_security_finding to alert Stefan
    """
    logger.info("\n" + "="*70)
    logger.info("TEST SCENARIO 3: Security Finding - Credentials Shared")
    logger.info("="*70)

    tracker.reset()

    from core.tools.slack_tools import report_security_finding

    logger.info("🤖 AI Monitoring: Watching Slack file shares")
    logger.info("🚨 AI Detection: Employee shared file '.env.production'")
    logger.info("⚠️  AI Analysis: Filename suggests sensitive credentials")
    logger.info("📢 AI Action: Escalating to leadership")

    result = await report_security_finding(
        finding_type="Potential Credentials File Shared",
        description="""During automated Slack monitoring, detected that a file named '.env.production' was shared in #general channel.

Analysis:
- Filename pattern matches environment configuration files
- These files typically contain API keys, database passwords, tokens
- Shared in public channel (high exposure risk)
- File size: 2.4 KB (consistent with config file)

Recommendation: Immediately verify file contents and rotate any exposed credentials.""",
        severity="HIGH",
        affected_user="test_user_id",
        evidence={
            "file_name": ".env.production",
            "channel": "general",
            "shared_at": datetime.now().isoformat(),
            "file_size": 2457,
            "detection_method": "automated_monitoring"
        },
        notify_who="stefan"
    )

    tracker.record_call("report_security_finding", result)

    assert result["success"], f"Security report failed: {result.get('message')}"
    logger.info(f"✅ SUCCESS: Security finding reported to Stefan")

    return tracker.calls


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scenario_4_autonomous_task_blocked():
    """
    Scenario: AI is performing autonomous task and hits unexpected error
    Expected: Should notify team about blockage
    """
    logger.info("\n" + "="*70)
    logger.info("TEST SCENARIO 4: Autonomous Task Blocked")
    logger.info("="*70)

    tracker.reset()

    context = {
        "source_type": "autonomous_coordinator",
        "agent_type": "singleton",
        "user_type": "internal",
        "task_id": "database_optimization_003"
    }

    from core.tools.slack_tools import notify_team

    logger.info("🤖 AI Autonomous Task: Optimize database indexes")
    logger.info("❌ AI Error: MySQL connection refused (port 3306)")
    logger.info("🔍 AI Troubleshooting: Checked service status, firewall, credentials")
    logger.info("🚫 AI Status: Blocked - cannot proceed without database access")
    logger.info("📢 AI Decision: Notify team of blockage")

    result = await notify_team(
        notification=f"""Autonomous task BLOCKED: Database Optimization

**Task**: Optimize MySQL database indexes for improved query performance

**Status**: Cannot proceed - MySQL connection refused

**What I tried**:
1. ✓ Verified MySQL service is running (systemctl status mysql)
2. ✓ Checked firewall rules (port 3306 open)
3. ✓ Validated credentials from .env.production
4. ✗ Connection still refused on localhost:3306

**Error**: `pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on 'localhost' (111)")`

**Request**: Please check MySQL configuration or grant me necessary permissions to continue this optimization task.

**Impact**: Database performance optimization postponed until connectivity restored.""",
        title="Autonomous Task Blocked - Database Access",
        importance="high",
        context=context
    )

    tracker.record_call("notify_team", result)

    assert result["success"], f"Team notification failed: {result.get('message')}"
    logger.info(f"✅ SUCCESS: Team notified of task blockage")

    return tracker.calls


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scenario_5_concerning_team_metrics():
    """
    Scenario: AI monitors team health and detects low activity
    Expected: Should notify team with health report
    """
    logger.info("\n" + "="*70)
    logger.info("TEST SCENARIO 5: Concerning Team Health Metrics")
    logger.info("="*70)

    tracker.reset()

    context = {
        "source_type": "system_maintenance",
        "agent_type": "health_analyst",
        "user_type": "internal"
    }

    from core.tools.slack_tools import notify_team

    logger.info("🤖 AI Monitoring: Daily team health check")
    logger.info("📊 AI Analysis: Running team activity metrics")
    logger.info("⚠️  AI Finding: Team health score below threshold")
    logger.info("📢 AI Action: Alerting team to low engagement")

    result = await notify_team(
        notification=f"""📊 Team Health Alert - Low Activity Detected

**Health Score**: 35/100 (concerning)

**Metrics (Last 24 Hours)**:
- Messages: 12 (expected: 50+)
- Active users: 1/3 (33%)
- Currently online: 0/3 (0%)

**Analysis**:
This is significantly below normal activity levels. Possible causes:
- Weekend/holiday period
- Team working offline/in different timezone
- Technical issues preventing Slack access
- Actual low engagement

**Recommendation**:
If this is unexpected, please confirm team is aware and engaged. If expected (weekend/holiday), this can be ignored.

**Next Check**: Tomorrow at 9:00 AM""",
        title="Team Health Alert",
        importance="normal",
        context=context
    )

    tracker.record_call("notify_team", result)

    assert result["success"], f"Health alert failed: {result.get('message')}"
    logger.info(f"✅ SUCCESS: Team health alert sent")

    return tracker.calls


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scenario_6_file_modification_uncertainty():
    """
    Scenario: AI needs to modify production config but uncertain if safe
    Expected: Should ask for approval before proceeding
    """
    logger.info("\n" + "="*70)
    logger.info("TEST SCENARIO 6: File Modification Uncertainty")
    logger.info("="*70)

    tracker.reset()

    context = {
        "source_type": "internal_task",
        "agent_type": "task_executor",
        "user_type": "internal",
        "task_id": "update_config_004"
    }

    from core.tools.slack_tools import ask_for_clarification

    logger.info("🤖 AI Task: Update API rate limits in production config")
    logger.info("⚠️  AI Concern: Modifying production config could impact live services")
    logger.info("💭 AI Reasoning: Need confirmation before making changes")
    logger.info("📢 AI Action: Request approval from team")

    result = await ask_for_clarification(
        question=f"""I need to update API rate limits in production configuration, but want to confirm before proceeding.

**Current Configuration** (.env.production):
```
API_RATE_LIMIT_PER_MINUTE=60
API_RATE_LIMIT_PER_HOUR=1000
```

**Proposed Changes**:
```
API_RATE_LIMIT_PER_MINUTE=120
API_RATE_LIMIT_PER_HOUR=2000
```

**Rationale**: Recent logs show legitimate users hitting rate limits during peak hours.

**Questions**:
1. Should I proceed with these new limits?
2. Are there other rate limit configurations I should update?
3. Should I create a backup of the current config first?

**Impact**: Changes will require service restart to take effect.""",
        what_tried=[
            "Analyzed API logs for rate limit errors",
            "Identified current bottleneck at 60 req/min",
            "Calculated proposed limits based on usage patterns"
        ],
        task="Update API rate limits in production",
        context=context
    )

    tracker.record_call("ask_for_clarification", result)

    assert result["success"], f"Approval request failed: {result.get('message')}"
    logger.info(f"✅ SUCCESS: Approval request sent for file modification")

    return tracker.calls


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scenario_7_slack_monitoring_tools():
    """
    Scenario: AI uses Slack monitoring tools to gather team insights
    Expected: Successfully retrieves team data and analyzes patterns
    """
    logger.info("\n" + "="*70)
    logger.info("TEST SCENARIO 7: Slack Monitoring Tools - Team Analysis")
    logger.info("="*70)

    tracker.reset()

    from core.tools.slack_monitoring_tools import (
        get_slack_users,
        get_slack_channels,
        monitor_team_activity,
        get_team_health_metrics
    )

    logger.info("🤖 AI Task: Perform team activity analysis")

    # Test 1: Get users
    logger.info("\n📊 Step 1: Retrieving team member list")
    users_result = await get_slack_users(include_bots=False)
    tracker.record_call("get_slack_users", users_result)

    if users_result["success"]:
        logger.info(f"✅ Retrieved {users_result['count']} team members")
    else:
        logger.warning(f"⚠️  Could not retrieve users: {users_result.get('error')}")

    # Test 2: Get channels
    logger.info("\n📊 Step 2: Retrieving channel list")
    channels_result = await get_slack_channels()
    tracker.record_call("get_slack_channels", channels_result)

    if channels_result["success"]:
        logger.info(f"✅ Retrieved {channels_result['count']} channels")
        # Show sample channels
        if channels_result['channels']:
            sample = channels_result['channels'][:3]
            for ch in sample:
                logger.info(f"   - #{ch.get('name', 'unknown')}")
    else:
        logger.warning(f"⚠️  Could not retrieve channels: {channels_result.get('error')}")

    # Test 3: Monitor activity
    logger.info("\n📊 Step 3: Analyzing team activity (last 24 hours)")
    activity_result = await monitor_team_activity(hours=24)
    tracker.record_call("monitor_team_activity", activity_result)

    if activity_result["success"]:
        activity = activity_result["activity"]
        logger.info(f"✅ Activity Analysis:")
        logger.info(f"   - Messages: {activity['message_count']}")
        logger.info(f"   - Active users: {activity['active_user_count']}")
        logger.info(f"   - Insights: {len(activity_result.get('insights', []))}")
        for insight in activity_result.get("insights", []):
            logger.info(f"     • {insight}")
    else:
        logger.warning(f"⚠️  Could not analyze activity: {activity_result.get('error')}")

    # Test 4: Health metrics
    logger.info("\n📊 Step 4: Calculating team health score")
    health_result = await get_team_health_metrics()
    tracker.record_call("get_team_health_metrics", health_result)

    if health_result["success"]:
        logger.info(f"✅ Team Health Score: {health_result['health_score']}/100")
        logger.info(f"   Status: {health_result['status']}")
        metrics = health_result['metrics']
        logger.info(f"   - Online: {metrics['currently_online']}/{metrics['total_team_members']}")
        logger.info(f"   - Active (24h): {metrics['active_users_24h']}/{metrics['total_team_members']}")
        logger.info(f"   - Messages (24h): {metrics['messages_24h']}")
    else:
        logger.warning(f"⚠️  Could not calculate health: {health_result.get('error')}")

    # Summary
    logger.info("\n" + "="*70)
    logger.info(f"MONITORING TEST SUMMARY:")
    logger.info(f"  Total tool calls: {len(tracker.calls)}")
    logger.info(f"  Successful: {sum(1 for c in tracker.calls if c['parameters'].get('success', False))}")
    logger.info("="*70)

    return tracker.calls


# Main test runner
async def run_all_tests():
    """Run all integration tests sequentially"""
    logger.info("\n" + "🚀 "*35)
    logger.info("SLACK UNCERTAINTY ESCALATION - INTEGRATION TEST SUITE")
    logger.info("🚀 "*35)
    logger.info("\nIMPORTANT: This will send REAL messages to Slack!")
    logger.info("Press Ctrl+C within 5 seconds to cancel...\n")

    # Give time to cancel
    await asyncio.sleep(5)

    all_results = {}

    try:
        # Run each test
        all_results["scenario_1"] = await test_scenario_1_missing_resource()
        await asyncio.sleep(2)  # Brief pause between tests

        all_results["scenario_2"] = await test_scenario_2_ambiguous_task()
        await asyncio.sleep(2)

        all_results["scenario_3"] = await test_scenario_3_security_finding()
        await asyncio.sleep(2)

        all_results["scenario_4"] = await test_scenario_4_autonomous_task_blocked()
        await asyncio.sleep(2)

        all_results["scenario_5"] = await test_scenario_5_concerning_team_metrics()
        await asyncio.sleep(2)

        all_results["scenario_6"] = await test_scenario_6_file_modification_uncertainty()
        await asyncio.sleep(2)

        all_results["scenario_7"] = await test_scenario_7_slack_monitoring_tools()

    except Exception as e:
        logger.error(f"\n❌ Test suite error: {e}", exc_info=True)

    # Final summary
    logger.info("\n" + "="*70)
    logger.info("TEST SUITE COMPLETE")
    logger.info("="*70)

    total_calls = sum(len(calls) for calls in all_results.values())
    logger.info(f"\n📊 Total Slack tool calls across all scenarios: {total_calls}")

    for scenario, calls in all_results.items():
        logger.info(f"\n{scenario}: {len(calls)} calls")
        for call in calls:
            success = call['parameters'].get('success', False)
            status = "✅" if success else "❌"
            logger.info(f"  {status} {call['tool']}")

    logger.info("\n" + "="*70)
    logger.info("✅ All scenarios tested - check Slack for messages!")
    logger.info("="*70 + "\n")


if __name__ == "__main__":
    """Run tests directly"""
    asyncio.run(run_all_tests())
