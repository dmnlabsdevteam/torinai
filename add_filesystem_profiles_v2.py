#!/usr/bin/env python3
"""Add capability profiles to filesystem tools - improved version"""

import re

# Filesystem tools with their capabilities
FILESYSTEM_TOOLS = {
    "ReadFileTool": ("read_file", ["READ_DATA"], "Read data from files"),
    "WriteFileTool": ("write_file", ["WRITE_DATA"], "Write data to files"),
    "ListDirectoryTool": ("list_directory", ["LIST_DATA"], "List directory contents"),
    "CreateDirectoryTool": ("create_directory", ["WRITE_DATA"], "Create directories"),
    "SearchFilesTool": ("search_files", ["SEARCH_DATA"], "Search for files by criteria"),
    "MoveFileTool": ("move_file", ["MOVE_DATA"], "Move or rename files"),
    "CopyFileTool": ("copy_file", ["COPY_DATA"], "Copy files or directories"),
    "DeleteFileTool": ("delete_file", ["DELETE_DATA"], "Delete files or directories"),
    "AtomicWriteFileTool": ("atomic_write_file", ["WRITE_DATA"], "Atomically write data to files"),
    "ValidatePathTool": ("validate_path", ["VALIDATE_DATA"], "Validate file paths"),
    "CalculateChecksumTool": ("calculate_checksum", ["VALIDATE_DATA"], "Validate file integrity with checksums"),
    "GetFileInfoTool": ("get_file_info", ["READ_DATA"], "Read file metadata and information"),
    "CompressFileTool": ("compress_file", ["COMPRESS_DATA"], "Compress files and directories"),
    "DecompressFileTool": ("decompress_file", ["DECOMPRESS_DATA"], "Decompress archive files"),
    "FindDuplicateFilesTool": ("find_duplicate_files", ["SEARCH_DATA", "VALIDATE_DATA"], "Search for and identify duplicate files"),
    "SyncDirectoryTool": ("sync_directory", ["COPY_DATA", "VALIDATE_DATA"], "Synchronize directories with validation")
}

def generate_capability_profile(tool_name, capabilities, descriptions):
    """Generate capability profile code with proper indentation"""
    cap_blocks = []
    cap_desc_map = {
        "READ_DATA": "Read data from files",
        "WRITE_DATA": descriptions,
        "LIST_DATA": descriptions,
        "SEARCH_DATA": descriptions.split("for")[0].strip() if "for" in descriptions else descriptions,
        "MOVE_DATA": descriptions,
        "COPY_DATA": descriptions,
        "DELETE_DATA": descriptions,
        "VALIDATE_DATA": descriptions,
        "COMPRESS_DATA": descriptions,
        "DECOMPRESS_DATA": descriptions
    }

    for cap in capabilities:
        desc = cap_desc_map.get(cap, descriptions)
        cap_blocks.append(f"""                CapabilityMetadata(
                    capability=Capability.{cap},
                    description="{desc}"
                )""")

    caps_str = ",\n".join(cap_blocks)

    return f"""
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="{tool_name}",
            capabilities=[
{caps_str}
            ]
        )
"""

# Read file
file_path = "/Users/stefan/Dominion Labs/TorinAI/core/tools/filesystem_tools.py"
with open(file_path, 'r') as f:
    lines = f.readlines()

# Process line by line
output_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    output_lines.append(line)

    # Check if this is a class definition we care about
    match = re.match(r'^class (\w+)\(Tool\):', line)
    if match:
        class_name = match.group(1)
        if class_name in FILESYSTEM_TOOLS:
            # Find the end of self.parameters = [...]
            # Continue until we find the closing bracket at indentation level 8 spaces
            while i < len(lines):
                i += 1
                current_line = lines[i]
                output_lines.append(current_line)

                # Look for "]" at the right indentation (end of parameters list)
                if re.match(r'^        \]\s*$', current_line):
                    # Found end of parameters list
                    # Add capability profile
                    tool_name, capabilities, description = FILESYSTEM_TOOLS[class_name]
                    profile = generate_capability_profile(tool_name, capabilities, description)
                    output_lines.append(profile)
                    print(f"✓ Added profile to {class_name}")
                    break

                # Safety: if we hit another method/class definition, stop
                if re.match(r'^    (async )?def |^class ', current_line):
                    print(f"⚠ Could not find parameters end for {class_name}")
                    break

    i += 1

# Write back
with open(file_path, 'w') as f:
    f.writelines(output_lines)

print(f"\n✅ Added capability profiles to filesystem tools!")
