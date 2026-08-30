#!/usr/bin/env python3
"""Fix log_test_result() calls in Phase 3 tests"""

import re

# Read the test file
with open('tests/test_governance_phase3.py', 'r') as f:
    content = f.read()

# Pattern 1: Fix passed tests - add assertions_failed=0 after assertions_passed=N
# Match: assertions_passed=N,\n followed by description or )
pattern1 = r'(assertions_passed=\d+),(\s+)(description=)'
replacement1 = r'\1, assertions_failed=0,\2\3'
content = re.sub(pattern1, replacement1, content)

# Pattern 2: Fix failed tests - add assertions_passed and assertions_failed after duration_ms
# Match status="failed" blocks that don't have assertions_passed
pattern2 = r'(status="failed",\s+duration_ms=duration_ms,)(\s+)(error_message=|description=)'
replacement2 = r'\1\2assertions_passed=0, assertions_failed=1,\2\3'
content = re.sub(pattern2, replacement2, content)

# Write back
with open('tests/test_governance_phase3.py', 'w') as f:
    f.write(content)

print("Fixed log_test_result() calls")
