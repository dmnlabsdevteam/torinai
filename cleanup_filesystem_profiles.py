#!/usr/bin/env python3
"""Clean up duplicated capability profiles in filesystem_tools.py"""

import re

file_path = "/Users/stefan/Dominion Labs/TorinAI/core/tools/filesystem_tools.py"

with open(file_path, 'r') as f:
    content = f.read()

# Remove all capability profile blocks
# Pattern: "# Capability profile" through the closing ")"
pattern = r'\n        # Capability profile\n        self\.capability_profile = ToolCapabilityProfile\([\s\S]*?        \)\n'

matches = re.findall(pattern, content)
print(f"Found {len(matches)} capability profile blocks to remove")

# Remove all of them
content_clean = re.sub(pattern, '\n', content)

# Write cleaned version
with open(file_path, 'w') as f:
    f.write(content_clean)

print(f"✅ Cleaned up filesystem_tools.py - removed all {len(matches)} capability profiles")
print("Now we can add them back correctly, one per tool")
