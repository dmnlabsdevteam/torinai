#!/usr/bin/env python3
"""Unit tests for executor runtime preflight + tool filtering.

These tests are intentionally lightweight (no LLM calls) and validate that
`GeneralPurposeExecutor`:
- filters Slack tools when Slack is not configured
- filters Slack API tools when only webhooks are configured
- enforces a minimum observable action for extrinsic JSON tasks
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _clear_slack_env(monkeypatch):
    for k in [
        "SLACK_BOT_TOKEN",
        "SLACK_WEBHOOK_URL",
        "SLACK_WEBHOOK_TORIN_UPGRADES",
        "SLACK_WEBHOOK_TORIN_ALERTS",
        "SLACK_WEBHOOK_TORIN_DECISIONS",
        "SLACK_WEBHOOK_TORIN_ACTIVITY",
        "SLACK_WEBHOOK_CRITICAL",
    ]:
        monkeypatch.delenv(k, raising=False)


def _unconfigured_executor():
    """An executor whose Slack settings are absent from BOTH sources.

    Clearing os.environ alone is not enough: .env.production genuinely
    configures Slack, and the executor reads it as a fallback. Blanking the
    file view too is what actually describes an unconfigured deployment. (It
    used to be enough by accident — load_dotenv pushed the file into
    os.environ, so the test was really asserting against whatever survived
    that mutation.)
    """
    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor

    executor = GeneralPurposeExecutor(torin_brain=object())
    executor._env_loaded = True
    executor._dotenv_values = {}
    return executor


def test_filters_all_slack_tools_when_unconfigured(monkeypatch):
    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor

    _clear_slack_env(monkeypatch)

    executor = _unconfigured_executor()
    tools = {
        "search_slack_messages": object(),
        "send_slack_message": object(),
        "read_file": object(),
    }

    filtered = executor._filter_tools_by_runtime_config(tools)

    assert "read_file" in filtered
    assert "search_slack_messages" not in filtered
    assert "send_slack_message" not in filtered


def test_filters_slack_api_tools_without_bot_token(monkeypatch):
    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor

    _clear_slack_env(monkeypatch)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.invalid/webhook")

    executor = _unconfigured_executor()   # webhook comes from the env above
    tools = {
        "search_slack_messages": object(),
        "get_slack_channels": object(),
        "send_slack_message": object(),
        "notify_dominion_labs_team": object(),
        "read_file": object(),
    }

    filtered = executor._filter_tools_by_runtime_config(tools)

    assert "read_file" in filtered
    # Webhook-based tools should remain
    assert "send_slack_message" in filtered
    assert "notify_dominion_labs_team" in filtered
    # Bot-token tools should be removed
    assert "search_slack_messages" not in filtered
    assert "get_slack_channels" not in filtered
