#!/usr/bin/env bash
# Run 7 launcher — fully detached from terminal
cd "/Users/stefan/Dominion Labs/TorinAI"
source venv_torin/bin/activate
LOG="logs/shadow_run7_$(date +%Y%m%d_%H%M%S).log"
nohup python shadow_mode_test.py --suite task > "$LOG" 2>&1 &
echo "Run 7 PID=$!  log=$LOG"
disown
