#!/usr/bin/env python3
"""Add capability profiles to filesystem tools"""

import re

# Filesystem tools with their capabilities
FILESYSTEM_TOOLS = [
    ("ReadFileTool", "read_file", ["READ_DATA"]),
    ("WriteFileTool", "write_file", ["WRITE_DATA"]),
    ("ListDirectoryTool", "list_directory", ["LIST_DATA"]),
    ("CreateDirectoryTool", "create_directory", ["WRITE_DATA"]),
    ("SearchFilesTool", "search_files", ["SEARCH_DATA"]),
    ("MoveFileTool", "move_file", ["MOVE_DATA"]),
    ("CopyFileTool", "copy_file", ["COPY_DATA"]),
    ("DeleteFileTool", "delete_file", ["DELETE_DATA"]),
    ("AtomicWriteFileTool", "atomic_write_file", ["WRITE_DATA"]),
    ("ValidatePathTool", "validate_path", ["VALIDATE_DATA"]),
    ("CalculateChecksumTool", "calculate_checksum", ["VALIDATE_DATA"]),
    ("GetFileInfoTool", "get_file_info", ["READ_DATA"]),
    ("CompressFileTool", "compress_file", ["COMPRESS_DATA"]),
    ("DecompressFileTool", "decompress_file", ["DECOMPRESS_DATA"]),
    ("FindDuplicateFilesTool", "find_duplicate_files", ["SEARCH_DATA", "VALIDATE_DATA"]),
    ("SyncDirectoryTool", "sync_directory", ["COPY_DATA", "VALIDATE_DATA"])
]

CAPABILITY_DESCRIPTIONS = {
    "READ_DATA": "Read data from files",
    "WRITE_DATA": "Write data to files or create directories",
    "LIST_DATA": "List directory contents",
    "SEARCH_DATA": "Search for files by criteria",
    "MOVE_DATA": "Move or rename files",
    "COPY_DATA": "Copy files or directories",
    "DELETE_DATA": "Delete files or directories",
    "VALIDATE_DATA": "Validate file integrity or paths",
    "COMPRESS_DATA": "Compress files",
    "DECOMPRESS_DATA": "Decompress files"
}

def generate_capability_profile(tool_name, capabilities):
    """Generate capability profile code"""
    cap_lines = []
    for cap in capabilities:
        desc = CAPABILITY_DESCRIPTIONS.get(cap, f"{cap.lower()} capability")
        cap_lines.append(f"""                CapabilityMetadata(
                    capability=Capability.{cap},
                    description="{desc}"
                )""")

    caps_str = ",\n".join(cap_lines)

    profile = f"""
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="{tool_name}",
            capabilities=[
{caps_str}
            ]
        )
"""
    return profile

# Read file
file_path = "/Users/stefan/Dominion Labs/TorinAI/core/tools/filesystem_tools.py"
with open(file_path, 'r') as f:
    content = f.read()

# Check if imports exist
if "from .capabilities import" not in content:
    # Add imports after other imports
    import_line = "from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata\n"
    # Find the last import line
    import_match = re.search(r'(from .*? import .*?\n)+', content)
    if import_match:
        insert_pos = import_match.end()
        content = content[:insert_pos] + import_line + content[insert_pos:]
        print("✓ Added capability imports")

# Process each tool
for class_name, tool_name, capabilities in FILESYSTEM_TOOLS:
    # Skip if already has profile
    if f'tool_name="{tool_name}"' in content:
        print(f"  ⏭ {class_name} already has profile")
        continue

    print(f"Adding profile to {class_name}...")

    # Find the class and its parameters closing bracket
    class_pattern = rf'class {class_name}\(Tool\):.*?        \](\n\n    async def execute)'

    match = re.search(class_pattern, content, re.DOTALL)
    if not match:
        print(f"  ⚠ Could not find {class_name}")
        continue

    # Generate the profile
    profile = generate_capability_profile(tool_name, capabilities)

    # Insert the profile before "async def execute"
    replacement = match.group(0).replace(
        '\n\n    async def execute',
        profile + '\n    async def execute'
    )

    content = content.replace(match.group(0), replacement)
    print(f"  ✓ Added profile to {class_name}")

# Write back
with open(file_path, 'w') as f:
    f.write(content)

print(f"\n✅ Added capability profiles to filesystem tools!")
