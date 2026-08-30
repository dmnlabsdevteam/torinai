#!/bin/bash
# Run Slack Integration Tests
# ============================
# This script runs real integration tests that will send messages to Slack.
# Make sure SLACK_BOT_TOKEN is configured in .env.production before running.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Slack Uncertainty Escalation - Integration Test Suite        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if .env.production exists
if [ ! -f "../../.env.production" ]; then
    echo -e "${RED}❌ ERROR: .env.production not found${NC}"
    echo "Please create .env.production with SLACK_BOT_TOKEN"
    exit 1
fi

# Check if SLACK_BOT_TOKEN is set
if ! grep -q "SLACK_BOT_TOKEN=" ../../.env.production; then
    echo -e "${YELLOW}⚠️  WARNING: SLACK_BOT_TOKEN not found in .env.production${NC}"
    echo "Some tests may fail without bot token configured"
    echo ""
fi

echo -e "${YELLOW}⚠️  WARNING: This will send REAL messages to Slack!${NC}"
echo ""
echo "Test scenarios that will execute:"
echo "  1. Missing Resource - System logs not found"
echo "  2. Ambiguous Task - Vague security improvement request"
echo "  3. Security Finding - Credentials file detected"
echo "  4. Autonomous Task Blocked - Database connection failed"
echo "  5. Concerning Team Metrics - Low activity detected"
echo "  6. File Modification Uncertainty - Production config change"
echo "  7. Slack Monitoring Tools - Team analysis"
echo ""

read -p "Continue? (yes/no): " -r
echo
if [[ ! $REPLY =~ ^[Yy]es$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo -e "${GREEN}Starting test suite...${NC}"
echo ""

# Activate virtual environment if it exists
if [ -d "../../venv_torin" ]; then
    echo "Activating virtual environment..."
    source ../../venv_torin/bin/activate
fi

# Set Python path
export PYTHONPATH="../../:$PYTHONPATH"

# Run specific scenario or all
if [ -z "$1" ]; then
    echo "Running all scenarios..."
    python test_slack_uncertainty_escalation.py
else
    echo "Running specific scenario: $1"
    pytest -v -s test_slack_uncertainty_escalation.py::$1
fi

echo ""
echo -e "${GREEN}✅ Test suite complete!${NC}"
echo -e "${BLUE}Check your Slack workspace for the messages.${NC}"
