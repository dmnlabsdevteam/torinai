#!/usr/bin/env python3
"""
Filesystem Tools
===============
Tools for file and directory operations.

Available Tools:
- read_file: Read file contents
- write_file: Write/modify files
- list_directory: List directory contents
- create_directory: Create directories
- search_files: Find files by pattern

Author: Torin AI Team
"""

import os
import glob
import logging
import shutil
import hashlib
import zipfile
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, CapabilityMetadata, ToolCapabilityProfile


logger = logging.getLogger(__name__)


class SmartPathResolver:
    """Intelligent path resolution with auto-correction and helpful error messages"""

    @staticmethod
    def resolve_path(requested_path: str, must_exist: bool = True, must_be_dir: bool = False) -> Dict[str, Any]:
        """
        Intelligently resolve a path with auto-correction and helpful suggestions.

        Returns dict with:
            - success: bool
            - path: Path object (if successful)
            - error_info: dict with details (if failed)
        """
        path = Path(requested_path).expanduser().resolve()

        # If path exists, validate type and permissions
        if path.exists():
            # Check if it should be a directory
            if must_be_dir and not path.is_dir():
                return {
                    "success": False,
                    "error_info": {
                        "error": "Path is not a directory",
                        "requested": requested_path,
                        "resolved": str(path),
                        "message": f"'{path}' exists but is a file, not a directory."
                    }
                }

            # Check permissions
            perms = SmartPathResolver._check_permissions(path)

            return {
                "success": True,
                "path": path,
                "permissions": perms
            }

        # Path doesn't exist - if that's ok, return
        if not must_exist:
            return {"success": True, "path": path}

        # Path doesn't exist and must exist - try auto-corrections first
        corrections = SmartPathResolver._try_auto_corrections(path, must_be_dir)

        # If exactly ONE correction found, USE IT automatically
        if len(corrections) == 1:
            corrected_path = Path(corrections[0])
            perms = SmartPathResolver._check_permissions(corrected_path)
            print(f"[SmartPathResolver] Auto-corrected: {requested_path} → {corrected_path}", flush=True)
            return {
                "success": True,
                "path": corrected_path,
                "permissions": perms,
                "auto_corrected": True,
                "original_path": requested_path
            }

        # No correction or multiple corrections - return helpful error
        return SmartPathResolver._generate_helpful_error(requested_path, path, must_be_dir)

    @staticmethod
    def _check_permissions(path: Path) -> Dict[str, bool]:
        """Check read/write permissions on path"""
        return {
            "readable": os.access(path, os.R_OK),
            "writable": os.access(path, os.W_OK),
            "executable": os.access(path, os.X_OK)
        }

    @staticmethod
    def _generate_helpful_error(requested: str, resolved: Path, must_be_dir: bool) -> Dict[str, Any]:
        """Generate helpful error with suggestions, parent contents, and auto-corrections"""

        dir_name = resolved.name
        parent = resolved.parent

        # 1. Try common auto-corrections
        corrections = SmartPathResolver._try_auto_corrections(resolved, must_be_dir)

        # 2. Search for similar paths
        suggestions = []
        if parent.exists():
            for item in parent.rglob(f"*{dir_name}*"):
                if not must_be_dir or item.is_dir():
                    suggestions.append(str(item))
                    if len(suggestions) >= 3:
                        break

        # 3. Show parent directory contents
        parent_contents = []
        if parent.exists():
            try:
                parent_contents = sorted([
                    item.name + ("/" if item.is_dir() else "")
                    for item in parent.iterdir()
                ])[:15]
            except PermissionError:
                parent_contents = ["<permission denied>"]

        # Build error message
        error_msg = {
            "error": "Path not found",
            "requested": requested,
            "resolved": str(resolved),
            "message": f"Path '{requested}' does not exist (resolved to '{resolved}')."
        }

        # Add auto-corrections if found
        if corrections:
            error_msg["auto_corrections"] = corrections
            error_msg["message"] += f" Auto-corrections found: {', '.join(corrections[:3])}"

        # Add suggestions if found
        if suggestions:
            error_msg["suggestions"] = suggestions
            error_msg["message"] += f" Similar paths: {', '.join(suggestions)}"

        # Add parent contents
        if parent_contents:
            error_msg["parent_directory"] = str(parent)
            error_msg["parent_contents"] = parent_contents
            error_msg["message"] += f" Parent '{parent.name}/' contains: {', '.join(parent_contents[:10])}"

        return {
            "success": False,
            "error_info": error_msg
        }

    @staticmethod
    def _try_auto_corrections(path: Path, must_be_dir: bool) -> List[str]:
        """Try common path corrections"""
        corrections = []

        # Common correction: add 'core/' subdirectory
        if "TorinAI" in str(path):
            # Try /TorinAI/core/xyz if /TorinAI/xyz fails
            core_variant = Path(str(path).replace("/TorinAI/", "/TorinAI/core/"))
            if core_variant.exists() and (not must_be_dir or core_variant.is_dir()):
                corrections.append(str(core_variant))

        # Try case-insensitive match on case-sensitive filesystems
        parent = path.parent
        if parent.exists():
            target_name_lower = path.name.lower()
            for item in parent.iterdir():
                if item.name.lower() == target_name_lower and item.name != path.name:
                    if not must_be_dir or item.is_dir():
                        corrections.append(str(item))
                        break

        return corrections


class ReadFileTool(Tool):
    """Read contents of a file"""
    
    def __init__(self):
        super().__init__()
        self.name = "read_file"
        self.description = "Read the contents of a file. Returns file content as text."
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Absolute or relative path to the file to read",
                required=True
            ),
            ToolParameter(
                name="start_line",
                type="number",
                description="Optional starting line number (1-indexed)",
                required=False,
                min_value=1
            ),
            ToolParameter(
                name="end_line",
                type="number",
                description="Optional ending line number (inclusive)",
                required=False,
                min_value=1
            ),
            ToolParameter(
                name="tail_lines",
                type="number",
                description="Read only the last N lines of the file (efficient for large log files). Use this instead of reading entire log files.",
                required=False,
                min_value=1
            )
        ]

        # Capability-based discovery metadata
        self.capability_profile = ToolCapabilityProfile(
            tool_name="read_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read data from local files",
                    input_types=["file_path"],
                    output_types=["text", "binary"],
                    context_matchers={"data_source": "file"},
                    latency="low",
                    cost="low",
                    reliability="high",
                    priority=10  # Prefer for file paths
                )
            ],
            requires_filesystem=True,
            is_idempotent=True
        )
    
    async def execute(self, file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None, tail_lines: Optional[int] = None) -> ToolResult:
        """Read file contents"""
        try:
            path = Path(file_path).expanduser().resolve()

            if not path.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "File not found",
                        "path": str(path),
                        "reason": "The specified file does not exist"
                    },
                    error=f"File not found: {path}"
                )

            if not path.is_file():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Path is not a file",
                        "path": str(path),
                        "reason": "The specified path exists but is a directory, not a file"
                    },
                    error=f"Path is not a file: {path}"
                )
            
            # Read file - efficient tail for large files (like logs)
            if tail_lines is not None:
                # Efficient tail reading without loading entire file
                content = self._read_tail(path, tail_lines)
            elif start_line is not None or end_line is not None:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    start_idx = (start_line - 1) if start_line else 0
                    end_idx = end_line if end_line else len(lines)
                    content = ''.join(lines[start_idx:end_idx])
            else:
                # Check file size - auto-batch large files
                file_size = path.stat().st_size
                if file_size > 500_000:  # Over 500KB - auto-batch
                    # Read first batch and provide guidance
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    total_lines = len(lines)
                    # Return first 500 lines as batch
                    batch_size = 500
                    content = ''.join(lines[:batch_size])
                    
                    return ToolResult(
                        success=True,
                        output={
                            "content": content,
                            "file_path": str(path),
                            "lines_returned": min(batch_size, total_lines),
                            "total_lines": total_lines,
                            "size_bytes": file_size,
                            "batched": True,
                            "next_batch": f"Use start_line={batch_size + 1}, end_line={min(batch_size * 2, total_lines)} for next batch",
                            "tip": f"For recent entries use tail_lines=500. For patterns use parse_logs tool."
                        }
                    )
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            return ToolResult(
                success=True,
                output={
                    "content": content,
                    "file_path": str(path),
                    "lines": len(content.splitlines()),
                    "size_bytes": len(content.encode('utf-8'))
                }
            )
            
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to read file",
                    "path": file_path,
                    "reason": str(e)
                },
                error=str(e)
            )

    def _read_tail(self, path: Path, num_lines: int) -> str:
        """Efficiently read the last N lines of a file without loading entire file.
        
        This is critical for large log files - a 13MB log file should not be
        loaded entirely just to read recent entries.
        """
        # For small files or small line counts, just read normally
        file_size = path.stat().st_size
        if file_size < 100_000:  # Under 100KB, just read all
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return ''.join(lines[-num_lines:])
        
        # For larger files, read from end in chunks
        avg_line_len = 150  # Estimate average line length
        chunk_size = max(num_lines * avg_line_len * 2, 8192)  # Read extra to be safe
        
        with open(path, 'rb') as f:
            # Seek to near end of file
            seek_pos = max(0, file_size - chunk_size)
            f.seek(seek_pos)
            
            # Read chunk and decode
            chunk = f.read().decode('utf-8', errors='replace')
            
            # Split into lines and take last N
            lines = chunk.splitlines(keepends=True)
            
            # If we didn't get enough lines and there's more file, read larger chunk
            if len(lines) < num_lines and seek_pos > 0:
                # Try reading more
                larger_chunk_size = min(chunk_size * 4, file_size)
                seek_pos = max(0, file_size - larger_chunk_size)
                f.seek(seek_pos)
                chunk = f.read().decode('utf-8', errors='replace')
                lines = chunk.splitlines(keepends=True)
            
            # Return last N lines
            return ''.join(lines[-num_lines:])


class WriteFileTool(Tool):
    """Write or modify a file"""
    
    def __init__(self):
        super().__init__()
        self.name = "write_file"
        self.description = "Write content to a file. Creates file if it doesn't exist, overwrites if it does."
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE  # Logged, not blocked
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Absolute or relative path to the file to write",
                required=True
            ),
            ToolParameter(
                name="content",
                type="string",
                description="Content to write to the file",
                required=True
            ),
            ToolParameter(
                name="mode",
                type="string",
                description="Write mode: 'write' (overwrite) or 'append'",
                required=False,
                default="write",
                enum=["write", "append"]
            ),
            ToolParameter(
                name="create_dirs",
                type="boolean",
                description="Create parent directories if they don't exist",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="write_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    description="Write data to files"
                )
            ]
        )

    async def execute(
        self,
        file_path: str,
        content: str,
        mode: str = "write",
        create_dirs: bool = True
    ) -> ToolResult:
        """Write to file"""
        try:
            path = Path(file_path).expanduser().resolve()

            # Check parent directory exists or can be created
            if not path.parent.exists():
                if create_dirs:
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                    except PermissionError:
                        return ToolResult(
                            success=False,
                            output={
                                "error": "Permission denied",
                                "path": str(path.parent),
                                "message": f"Cannot create parent directory '{path.parent}' - permission denied"
                            },
                            error="Permission denied creating parent directory"
                        )
                else:
                    return ToolResult(
                        success=False,
                        output={
                            "error": "Parent directory does not exist",
                            "file_path": str(path),
                            "parent": str(path.parent),
                            "message": f"Parent directory '{path.parent}' does not exist. Set create_dirs=True to create it."
                        },
                        error="Parent directory does not exist"
                    )

            # Check disk space (warn if less than 100MB free)
            import shutil
            stat = shutil.disk_usage(path.parent)
            free_mb = stat.free / (1024 * 1024)
            content_size_mb = len(content.encode('utf-8')) / (1024 * 1024)

            if free_mb < 100:
                logger.warning(f"Low disk space: {free_mb:.1f}MB free")

            if content_size_mb > free_mb:
                return ToolResult(
                    success=False,
                    output={
                        "error": "Insufficient disk space",
                        "free_space_mb": round(free_mb, 2),
                        "required_mb": round(content_size_mb, 2),
                        "message": f"Not enough disk space. Need {content_size_mb:.1f}MB but only {free_mb:.1f}MB free."
                    },
                    error="Insufficient disk space"
                )

            # Check write permission on existing file or parent directory
            if path.exists():
                if not os.access(path, os.W_OK):
                    return ToolResult(
                        success=False,
                        output={
                            "error": "Permission denied",
                            "path": str(path),
                            "message": f"No write permission for file '{path}'"
                        },
                        error="Permission denied"
                    )
                # Guard: refuse to silently truncate an existing file by >20%.
                # This catches the common failure mode where an agent writes a
                # partial stub instead of the full file with its targeted change.
                if mode != "append":
                    _original_bytes = path.stat().st_size
                    _new_bytes = len(content.encode("utf-8"))
                    # Exempt temporary paths — they are legitimately rewritten from scratch
                    import tempfile as _tmpmod
                    _tmpdir = _tmpmod.gettempdir()
                    _is_temp_path = str(path).startswith(_tmpdir) or str(path).startswith("/tmp/")
                    if not _is_temp_path and _original_bytes > 500 and _new_bytes < _original_bytes * 0.80:
                        return ToolResult(
                            success=False,
                            output={
                                "error": "Truncation guard: content is too short",
                                "original_bytes": _original_bytes,
                                "new_bytes": _new_bytes,
                                "ratio": round(_new_bytes / _original_bytes, 2),
                                "message": (
                                    f"Refusing to overwrite '{path.name}' "
                                    f"({_original_bytes:,} bytes) with only {_new_bytes:,} bytes "
                                    f"({100*_new_bytes//_original_bytes}% of original). "
                                    "You must write the COMPLETE file. "
                                    "Read the file first, apply your targeted change, "
                                    "then write back the full content."
                                ),
                            },
                            error="Truncation guard triggered — content is less than 80% of original file size"
                        )
            else:
                if not os.access(path.parent, os.W_OK):
                    return ToolResult(
                        success=False,
                        output={
                            "error": "Permission denied",
                            "path": str(path.parent),
                            "message": f"No write permission for directory '{path.parent}'"
                        },
                        error="Permission denied"
                    )

            # Write file
            write_mode = 'a' if mode == "append" else 'w'
            with open(path, write_mode, encoding='utf-8') as f:
                f.write(content)
            
            return ToolResult(
                success=True,
                output={
                    "file_path": str(path),
                    "mode": mode,
                    "bytes_written": len(content.encode('utf-8')),
                    "lines_written": len(content.splitlines())
                }
            )
            
        except Exception as e:
            logger.error(f"Error writing file {file_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to write file",
                    "path": file_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class PatchFileTool(Tool):
    """Apply a targeted string replacement to a file without rewriting the whole thing."""

    def __init__(self):
        super().__init__()
        self.name = "patch_file"
        self.description = (
            "Replace exactly ONE occurrence of old_string with new_string inside a file. "
            "The file is modified in-place — you do NOT need to provide the entire file content. "
            "Use this instead of write_file when the file is large. "
            "old_string must be unique within the file; include enough surrounding context lines "
            "to guarantee uniqueness."
        )
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Absolute or relative path to the file to patch",
                required=True
            ),
            ToolParameter(
                name="old_string",
                type="string",
                description="Exact literal text to replace (must appear exactly once in the file)",
                required=True
            ),
            ToolParameter(
                name="new_string",
                type="string",
                description="Replacement text",
                required=True
            ),
        ]
        self.capability_profile = ToolCapabilityProfile(
            tool_name="patch_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    description="Patch files with targeted string replacement"
                )
            ]
        )

    async def execute(self, file_path: str, old_string: str, new_string: str) -> ToolResult:
        """Apply a targeted patch to a file."""
        try:
            path = Path(file_path).expanduser().resolve()
            if not path.exists():
                return ToolResult(
                    success=False,
                    output={"error": f"File not found: {file_path}"},
                    error="File not found"
                )
            if not os.access(path, os.W_OK):
                return ToolResult(
                    success=False,
                    output={"error": f"No write permission for '{path}'"},
                    error="Permission denied"
                )

            if old_string == new_string:
                return ToolResult(
                    success=False,
                    output={
                        "error": "old_string and new_string are identical — this patch changes nothing.",
                        "hint": (
                            "You are trying to replace text with itself. "
                            "Read the file again to get the current content, "
                            "then supply the text you want to REMOVE as old_string "
                            "and the replacement as new_string."
                        ),
                    },
                    error="No-op patch: old_string == new_string"
                )

            original = path.read_text(encoding="utf-8")
            count = original.count(old_string)

            if count == 0:
                return ToolResult(
                    success=False,
                    output={
                        "error": "old_string not found in file",
                        "file": str(path),
                        "message": (
                            "The exact text was not found. "
                            "Copy old_string verbatim from read_file output, "
                            "including all whitespace and indentation."
                        ),
                    },
                    error="old_string not found"
                )
            if count > 1:
                return ToolResult(
                    success=False,
                    output={
                        "error": f"old_string is ambiguous: found {count} occurrences",
                        "file": str(path),
                        "message": (
                            f"old_string matches {count} locations. "
                            "Add more surrounding context lines to make it unique."
                        ),
                    },
                    error="old_string not unique"
                )

            patched = original.replace(old_string, new_string, 1)
            path.write_text(patched, encoding="utf-8")

            return ToolResult(
                success=True,
                output={
                    "file_path": str(path),
                    "bytes_before": len(original.encode()),
                    "bytes_after": len(patched.encode()),
                    "delta_bytes": len(patched.encode()) - len(original.encode()),
                }
            )
        except Exception as e:
            logger.error(f"patch_file error on {file_path}: {e}")
            return ToolResult(
                success=False,
                output={"error": str(e), "path": file_path},
                error=str(e)
            )


class ListDirectoryTool(Tool):
    """List contents of a directory"""
    
    def __init__(self):
        super().__init__()
        self.name = "list_directory"
        self.description = "List all files and subdirectories in a directory"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Path to directory to list",
                required=True
            ),
            ToolParameter(
                name="recursive",
                type="boolean",
                description="Whether to list recursively",
                required=False,
                default=False
            ),
            ToolParameter(
                name="pattern",
                type="string",
                description="Optional glob pattern to filter results (e.g., '*.py')",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="list_directory",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.LIST_DATA,
                    description="List directory contents"
                )
            ]
        )

    async def execute(
        self,
        directory_path: str,
        recursive: bool = False,
        pattern: Optional[str] = None
    ) -> ToolResult:
        """List directory contents"""
        try:
            # Use smart path resolution
            resolution = SmartPathResolver.resolve_path(directory_path, must_exist=True, must_be_dir=True)

            if not resolution["success"]:
                return ToolResult(
                    success=False,
                    output=resolution["error_info"],
                    error=resolution["error_info"]["message"]
                )

            path = resolution["path"]
            perms = resolution["permissions"]

            # Check read permission
            if not perms["readable"]:
                return ToolResult(
                    success=False,
                    output={
                        "error": "Permission denied",
                        "path": str(path),
                        "message": f"No read permission for directory '{path}'"
                    },
                    error=f"Permission denied: {path}"
                )
            
            # List contents
            files = []
            directories = []
            
            if recursive:
                pattern_str = f"**/{pattern}" if pattern else "**/*"
                for item in path.glob(pattern_str):
                    if item.is_file():
                        files.append(str(item.relative_to(path)))
                    elif item.is_dir():
                        directories.append(str(item.relative_to(path)))
            else:
                items = path.glob(pattern if pattern else "*")
                for item in items:
                    if item.is_file():
                        files.append(item.name)
                    elif item.is_dir():
                        directories.append(item.name)
            
            return ToolResult(
                success=True,
                output={
                    "directory": str(path),
                    "files": sorted(files),
                    "directories": sorted(directories),
                    "total_files": len(files),
                    "total_directories": len(directories)
                }
            )
            
        except Exception as e:
            logger.error(f"Error listing directory {directory_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to list directory",
                    "path": directory_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class CreateDirectoryTool(Tool):
    """Create a directory"""
    
    def __init__(self):
        super().__init__()
        self.name = "create_directory"
        self.description = "Create a new directory (and parent directories if needed)"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Path to directory to create",
                required=True
            ),
            ToolParameter(
                name="parents",
                type="boolean",
                description="Create parent directories if they don't exist",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_directory",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    description="Create directories"
                )
            ]
        )

    async def execute(self, directory_path: str, parents: bool = True) -> ToolResult:
        """Create directory"""
        try:
            path = Path(directory_path).expanduser().resolve()
            
            if path.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Directory already exists",
                        "path": str(path),
                        "reason": "Cannot create directory because it already exists"
                    },
                    error=f"Directory already exists: {path}"
                )
            
            path.mkdir(parents=parents, exist_ok=False)
            
            return ToolResult(
                success=True,
                output={
                    "directory": str(path),
                    "created": True
                }
            )
            
        except Exception as e:
            logger.error(f"Error creating directory {directory_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to create directory",
                    "path": directory_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class SearchFilesTool(Tool):
    """Search for files by name pattern"""
    
    def __init__(self):
        super().__init__()
        self.name = "search_files"
        self.description = "Search for files matching a glob pattern"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="pattern",
                type="string",
                description="Glob pattern to search for (e.g., '*.txt' or '**/*.py' for recursive search)",
                required=True
            ),
            ToolParameter(
                name="directory",
                type="string",
                description="Directory to search in (defaults to current directory)",
                required=False,
                default="."
            ),
            ToolParameter(
                name="max_results",
                type="number",
                description="Maximum number of results to return",
                required=False,
                default=100,
                min_value=1,
                max_value=1000
            ),
            ToolParameter(
                name="recursive",
                type="boolean",
                description="Search recursively in subdirectories (Note: using '**/' in pattern is preferred)",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="search_files",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SEARCH_DATA,
                    description="Search for files by criteria"
                )
            ]
        )

    async def execute(
        self,
        pattern: str,
        directory: str = ".",
        max_results: int = 100,
        recursive: bool = True
    ) -> ToolResult:
        """Search for files"""
        try:
            # Use smart path resolution
            resolution = SmartPathResolver.resolve_path(directory, must_exist=True, must_be_dir=True)

            if not resolution["success"]:
                return ToolResult(
                    success=False,
                    output=resolution["error_info"],
                    error=resolution["error_info"]["message"]
                )

            path = resolution["path"]

            # Validate glob pattern
            if not pattern or pattern.strip() == "":
                return ToolResult(
                    success=False,
                    output={
                        "error": "Invalid pattern",
                        "pattern": pattern,
                        "message": "Pattern cannot be empty. Examples: '*.py', '**/*.txt', 'config.*'"
                    },
                    error="Empty search pattern"
                )

            # If recursive is True and pattern doesn't contain '**', prepend it
            search_pattern = pattern
            if recursive and '**' not in pattern:
                search_pattern = f"**/{pattern}"

            # Search for files
            matches = []
            for match in path.glob(search_pattern):
                if match.is_file():
                    matches.append(str(match.relative_to(path)))
                    if len(matches) >= max_results:
                        break
            
            return ToolResult(
                success=True,
                output={
                    "pattern": pattern,
                    "directory": str(path),
                    "matches": matches,
                    "count": len(matches),
                    "truncated": len(matches) >= max_results
                }
            )
            
        except Exception as e:
            logger.error(f"Error searching files with pattern {pattern}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to search files",
                    "pattern": pattern,
                    "reason": str(e)
                },
                error=str(e)
            )


class MoveFileTool(Tool):
    """Move or rename a file/directory"""

    def __init__(self):
        super().__init__()
        self.name = "move_file"
        self.description = "Move or rename a file or directory to a new location"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="source_path",
                type="string",
                description="Path to the file or directory to move",
                required=True
            ),
            ToolParameter(
                name="destination_path",
                type="string",
                description="Destination path (file or directory)",
                required=True
            ),
            ToolParameter(
                name="create_dirs",
                type="boolean",
                description="Create parent directories at destination if they don't exist",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="move_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MOVE_DATA,
                    description="Move or rename files"
                )
            ]
        )

    async def execute(
        self,
        source_path: str,
        destination_path: str,
        create_dirs: bool = True
    ) -> ToolResult:
        """Move or rename file/directory"""
        try:
            source = Path(source_path).expanduser().resolve()
            destination = Path(destination_path).expanduser().resolve()

            if not source.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Source not found",
                        "source_path": str(source),
                        "reason": "The source file or directory does not exist"
                    },
                    error=f"Source not found: {source}"
                )

            if destination.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Destination already exists",
                        "destination_path": str(destination),
                        "reason": "Cannot move to destination because a file or directory already exists at that location. Consider deleting it first or choosing a different destination."
                    },
                    error=f"Destination already exists: {destination}"
                )

            # Create parent directories if needed
            if create_dirs and not destination.parent.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)

            # Move the file/directory
            shutil.move(str(source), str(destination))

            return ToolResult(
                success=True,
                output={
                    "source": str(source),
                    "destination": str(destination),
                    "moved": True,
                    "is_directory": destination.is_dir()
                }
            )

        except Exception as e:
            logger.error(f"Error moving {source_path} to {destination_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to move file",
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class CopyFileTool(Tool):
    """Copy a file or directory"""

    def __init__(self):
        super().__init__()
        self.name = "copy_file"
        self.description = "Copy a file or directory to a new location"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="source_path",
                type="string",
                description="Path to the file or directory to copy",
                required=True
            ),
            ToolParameter(
                name="destination_path",
                type="string",
                description="Destination path for the copy",
                required=True
            ),
            ToolParameter(
                name="create_dirs",
                type="boolean",
                description="Create parent directories at destination if they don't exist",
                required=False,
                default=True
            ),
            ToolParameter(
                name="preserve_metadata",
                type="boolean",
                description="Preserve file metadata (timestamps, permissions)",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="copy_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.COPY_DATA,
                    description="Copy files or directories"
                )
            ]
        )

    async def execute(
        self,
        source_path: str,
        destination_path: str,
        create_dirs: bool = True,
        preserve_metadata: bool = True
    ) -> ToolResult:
        """Copy file or directory"""
        try:
            source = Path(source_path).expanduser().resolve()
            destination = Path(destination_path).expanduser().resolve()

            if not source.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Source not found",
                        "source_path": str(source),
                        "reason": "The source file or directory does not exist"
                    },
                    error=f"Source not found: {source}"
                )

            if destination.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Destination already exists",
                        "destination_path": str(destination),
                        "reason": "Cannot copy to destination because a file or directory already exists at that location"
                    },
                    error=f"Destination already exists: {destination}"
                )

            # Create parent directories if needed
            if create_dirs and not destination.parent.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)

            # Copy file or directory
            if source.is_file():
                if preserve_metadata:
                    shutil.copy2(str(source), str(destination))
                else:
                    shutil.copy(str(source), str(destination))
                size_bytes = destination.stat().st_size
            else:
                shutil.copytree(str(source), str(destination), symlinks=False, dirs_exist_ok=False)
                size_bytes = sum(f.stat().st_size for f in destination.rglob('*') if f.is_file())

            return ToolResult(
                success=True,
                output={
                    "source": str(source),
                    "destination": str(destination),
                    "copied": True,
                    "is_directory": destination.is_dir(),
                    "size_bytes": size_bytes,
                    "preserved_metadata": preserve_metadata
                }
            )

        except Exception as e:
            logger.error(f"Error copying {source_path} to {destination_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to copy file",
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class DeleteFileTool(Tool):
    """Delete a file or directory (DESTRUCTIVE - requires approval)"""

    def __init__(self):
        super().__init__()
        self.name = "delete_file"
        self.description = "Delete a file or directory. DESTRUCTIVE operation - use with caution!"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.DANGEROUS  # Requires approval
        self.parameters = [
            ToolParameter(
                name="path",
                type="string",
                description="Path to the file or directory to delete",
                required=True
            ),
            ToolParameter(
                name="recursive",
                type="boolean",
                description="If path is a directory, delete it recursively",
                required=False,
                default=False
            ),
            ToolParameter(
                name="confirm",
                type="boolean",
                description="Confirmation flag - must be set to true to proceed",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="delete_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DELETE_DATA,
                    description="Delete files or directories"
                )
            ]
        )

    async def execute(
        self,
        path: str,
        recursive: bool = False,
        confirm: bool = False
    ) -> ToolResult:
        """Delete file or directory"""
        try:
            if not confirm:
                return ToolResult(
                    success=False,
                    output={
                        "error": "Deletion not confirmed",
                        "reason": "Set 'confirm' parameter to true to proceed with deletion"
                    },
                    error="Deletion not confirmed. Set 'confirm' parameter to true to proceed."
                )

            target = Path(path).expanduser().resolve()

            if not target.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Path not found",
                        "path": str(target),
                        "reason": "The specified file or directory does not exist"
                    },
                    error=f"Path not found: {target}"
                )

            # Collect metadata before deletion
            is_directory = target.is_dir()
            size_bytes = 0
            file_count = 0

            if is_directory:
                if not recursive:
                    return ToolResult(
                        success=False,
                        output={
                            "error": "Cannot delete directory",
                            "path": str(target),
                            "reason": "Path is a directory. Set 'recursive=true' to delete directories and their contents."
                        },
                        error=f"Path is a directory. Set 'recursive=true' to delete directories."
                    )
                # Calculate total size and file count
                for item in target.rglob('*'):
                    if item.is_file():
                        size_bytes += item.stat().st_size
                        file_count += 1

                # Delete directory
                shutil.rmtree(str(target))
            else:
                size_bytes = target.stat().st_size
                file_count = 1
                # Delete file
                target.unlink()

            return ToolResult(
                success=True,
                output={
                    "path": str(target),
                    "deleted": True,
                    "was_directory": is_directory,
                    "files_deleted": file_count,
                    "bytes_freed": size_bytes
                }
            )

        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to delete",
                    "path": path,
                    "reason": str(e)
                },
                error=str(e)
            )


class AtomicWriteFileTool(Tool):
    """Atomic file write using temp + fsync + rename pattern"""

    def __init__(self):
        super().__init__()
        self.name = "atomic_write_file"
        self.description = "Write file atomically using temp file + fsync + rename for crash safety"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Absolute or relative path to the file to write",
                required=True
            ),
            ToolParameter(
                name="content",
                type="string",
                description="Content to write to the file",
                required=True
            ),
            ToolParameter(
                name="create_dirs",
                type="boolean",
                description="Create parent directories if they don't exist",
                required=False,
                default=True
            ),
            ToolParameter(
                name="encoding",
                type="string",
                description="File encoding (default: utf-8)",
                required=False,
                default="utf-8"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="atomic_write_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    description="Atomically write data to files"
                )
            ]
        )

    async def execute(
        self,
        file_path: str,
        content: str,
        create_dirs: bool = True,
        encoding: str = "utf-8"
    ) -> ToolResult:
        """Atomically write to file"""
        import tempfile

        try:
            path = Path(file_path).expanduser().resolve()

            # Create parent directories if needed
            if create_dirs and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

            # Create temporary file in same directory to ensure same filesystem
            # This is critical for atomic rename to work
            temp_fd, temp_path = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp"
            )

            try:
                # Write content to temp file
                with os.fdopen(temp_fd, 'w', encoding=encoding) as f:
                    f.write(content)
                    f.flush()
                    # Ensure data is written to disk
                    os.fsync(f.fileno())

                # Atomically rename temp file to target
                # On POSIX systems, this is atomic even if target exists
                os.replace(temp_path, str(path))

                return ToolResult(
                    success=True,
                    output={
                        "file_path": str(path),
                        "bytes_written": len(content.encode(encoding)),
                        "lines_written": len(content.splitlines()),
                        "atomic": True,
                        "encoding": encoding
                    }
                )

            except Exception as e:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except:
                    pass
                raise e

        except Exception as e:
            logger.error(f"Error atomically writing file {file_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to atomically write file",
                    "path": file_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class ValidatePathTool(Tool):
    """Validate path against allowed directories and sandbox enforcement"""

    def __init__(self):
        super().__init__()
        self.name = "validate_path"
        self.description = "Validate a path against allowed directories and sandbox root enforcement"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="path",
                type="string",
                description="Path to validate",
                required=True
            ),
            ToolParameter(
                name="allowed_roots",
                type="array",
                description="List of allowed root directories (defaults to current working directory)",
                required=False,
                default=None
            ),
            ToolParameter(
                name="must_exist",
                type="boolean",
                description="Whether the path must exist",
                required=False,
                default=False
            ),
            ToolParameter(
                name="allow_symlinks",
                type="boolean",
                description="Whether to allow symlinks",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="validate_path",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    description="Validate file paths"
                )
            ]
        )

    async def execute(
        self,
        path: str,
        allowed_roots: Optional[List[str]] = None,
        must_exist: bool = False,
        allow_symlinks: bool = False
    ) -> ToolResult:
        """Validate path"""
        try:
            target = Path(path).expanduser()

            # Default to current working directory if no roots specified
            if allowed_roots is None:
                allowed_roots = [os.getcwd()]

            # Resolve to absolute path
            try:
                resolved = target.resolve(strict=must_exist)
            except (FileNotFoundError, RuntimeError) as e:
                return ToolResult(
                    success=False,
                    output={
                        "path": path,
                        "valid": False,
                        "reason": f"Path resolution failed: {e}"
                    },
                    error=str(e)
                )

            # Check if path exists (if required)
            if must_exist and not resolved.exists():
                return ToolResult(
                    success=False,
                    output={
                        "path": path,
                        "resolved": str(resolved),
                        "valid": False,
                        "reason": "Path does not exist"
                    },
                    error="Path does not exist"
                )

            # Check for symlinks
            if not allow_symlinks and resolved.is_symlink():
                return ToolResult(
                    success=False,
                    output={
                        "path": path,
                        "resolved": str(resolved),
                        "valid": False,
                        "reason": "Symlinks not allowed"
                    },
                    error="Symlinks not allowed"
                )

            # Validate against allowed roots
            is_within_allowed = False
            matched_root = None

            for allowed_root in allowed_roots:
                root = Path(allowed_root).expanduser().resolve()
                try:
                    # Check if resolved path is relative to allowed root
                    resolved.relative_to(root)
                    is_within_allowed = True
                    matched_root = str(root)
                    break
                except ValueError:
                    # Path is not relative to this root
                    continue

            if not is_within_allowed:
                return ToolResult(
                    success=False,
                    output={
                        "path": path,
                        "resolved": str(resolved),
                        "valid": False,
                        "reason": f"Path is outside allowed roots: {allowed_roots}",
                        "allowed_roots": [str(Path(r).expanduser().resolve()) for r in allowed_roots]
                    },
                    error="Path is outside allowed roots"
                )

            return ToolResult(
                success=True,
                output={
                    "path": path,
                    "resolved": str(resolved),
                    "valid": True,
                    "matched_root": matched_root,
                    "exists": resolved.exists(),
                    "is_file": resolved.is_file() if resolved.exists() else None,
                    "is_directory": resolved.is_dir() if resolved.exists() else None,
                    "is_symlink": resolved.is_symlink()
                }
            )

        except Exception as e:
            logger.error(f"Error validating path {path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to validate path",
                    "path": path,
                    "reason": str(e)
                },
                error=str(e)
            )


class CalculateChecksumTool(Tool):
    """Calculate cryptographic checksum/hash of a file for provenance"""

    def __init__(self):
        super().__init__()
        self.name = "calculate_checksum"
        self.description = "Calculate cryptographic hash (SHA256 by default) of a file for integrity verification"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to the file to hash",
                required=True
            ),
            ToolParameter(
                name="algorithm",
                type="string",
                description="Hash algorithm to use",
                required=False,
                default="sha256",
                enum=["md5", "sha1", "sha256", "sha512"]
            ),
            ToolParameter(
                name="chunk_size",
                type="number",
                description="Size of chunks to read for large files (bytes)",
                required=False,
                default=65536,  # 64KB
                min_value=1024,
                max_value=1048576  # 1MB
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="calculate_checksum",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    description="Validate file integrity with checksums"
                )
            ]
        )

    async def execute(
        self,
        file_path: str,
        algorithm: str = "sha256",
        chunk_size: int = 65536
    ) -> ToolResult:
        """Calculate file checksum"""
        try:
            path = Path(file_path).expanduser().resolve()

            if not path.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "File not found",
                        "path": str(path),
                        "reason": "The specified file does not exist"
                    },
                    error=f"File not found: {path}"
                )

            if not path.is_file():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Path is not a file",
                        "path": str(path),
                        "reason": "The specified path exists but is a directory, not a file"
                    },
                    error=f"Path is not a file: {path}"
                )

            # Create hash object
            hash_obj = hashlib.new(algorithm)

            # Read file in chunks and update hash
            bytes_processed = 0
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    hash_obj.update(chunk)
                    bytes_processed += len(chunk)

            checksum = hash_obj.hexdigest()
            file_size = path.stat().st_size

            return ToolResult(
                success=True,
                output={
                    "file_path": str(path),
                    "algorithm": algorithm,
                    "checksum": checksum,
                    "size_bytes": file_size,
                    "bytes_processed": bytes_processed,
                    "verification": f"{algorithm.upper()}:{checksum}"
                }
            )

        except Exception as e:
            logger.error(f"Error calculating checksum for {file_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to calculate checksum",
                    "path": file_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class GetFileInfoTool(Tool):
    """Get file metadata and information"""

    def __init__(self):
        super().__init__()
        self.name = "get_file_info"
        self.description = "Get comprehensive metadata about a file (size, timestamps, permissions)"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to file",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_file_info",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.READ_DATA,
                    description="Read file metadata and information"
                )
            ]
        )

    async def execute(self, file_path: str) -> ToolResult:
        """Get file metadata"""
        try:
            from datetime import datetime

            p = Path(file_path).expanduser().resolve()

            if not p.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "File not found",
                        "path": str(p),
                        "reason": "The specified file or directory does not exist"
                    },
                    error=f"File not found: {p}"
                )

            stat = p.stat()

            return ToolResult(
                success=True,
                output={
                    "path": str(p),
                    "name": p.name,
                    "size_bytes": stat.st_size,
                    "size_human": self._format_bytes(stat.st_size),
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "permissions": oct(stat.st_mode)[-3:],
                    "is_file": p.is_file(),
                    "is_directory": p.is_dir(),
                    "is_symlink": p.is_symlink()
                }
            )

        except Exception as e:
            logger.error(f"Error getting file info for {file_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to get file info",
                    "path": file_path,
                    "reason": str(e)
                },
                error=str(e)
            )

    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes to human-readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.2f} PB"


class CompressFileTool(Tool):
    """Create compressed archives (ZIP/TAR)"""

    def __init__(self):
        super().__init__()
        self.name = "compress_file"
        self.description = "Create a compressed archive (zip or tar.gz) from files/directories"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="source_path",
                type="string",
                description="Path to file or directory to compress",
                required=True
            ),
            ToolParameter(
                name="archive_path",
                type="string",
                description="Output archive path (e.g., archive.zip or archive.tar.gz)",
                required=True
            ),
            ToolParameter(
                name="format",
                type="string",
                description="Archive format",
                required=False,
                default="zip",
                enum=["zip", "tar.gz"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="compress_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.COMPRESS_DATA,
                    description="Compress files and directories"
                )
            ]
        )

    async def execute(self, source_path: str, archive_path: str, format: str = "zip") -> ToolResult:
        """Create compressed archive"""
        try:
            src = Path(source_path).expanduser().resolve()
            archive = Path(archive_path).expanduser().resolve()

            if not src.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Source not found",
                        "path": str(src),
                        "reason": "The source file or directory does not exist"
                    },
                    error=f"Source not found: {src}"
                )

            if format == "zip":
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
                    if src.is_file():
                        zf.write(src, src.name)
                    else:
                        for file in src.rglob('*'):
                            if file.is_file():
                                zf.write(file, file.relative_to(src.parent))

            elif format == "tar.gz":
                with tarfile.open(archive, 'w:gz') as tf:
                    tf.add(src, arcname=src.name)

            return ToolResult(
                success=True,
                output={
                    "source": str(src),
                    "archive": str(archive),
                    "format": format,
                    "size_bytes": archive.stat().st_size
                }
            )

        except Exception as e:
            logger.error(f"Error compressing {source_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to compress",
                    "source_path": source_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class DecompressFileTool(Tool):
    """Extract compressed archives"""

    def __init__(self):
        super().__init__()
        self.name = "decompress_file"
        self.description = "Extract files from a compressed archive (zip or tar.gz)"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="archive_path",
                type="string",
                description="Path to archive file",
                required=True
            ),
            ToolParameter(
                name="destination_path",
                type="string",
                description="Destination directory to extract to",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="decompress_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DECOMPRESS_DATA,
                    description="Decompress archive files"
                )
            ]
        )

    async def execute(self, archive_path: str, destination_path: str) -> ToolResult:
        """Extract compressed archive"""
        try:
            archive = Path(archive_path).expanduser().resolve()
            dest = Path(destination_path).expanduser().resolve()

            if not archive.exists():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Archive not found",
                        "path": str(archive),
                        "reason": "The specified archive file does not exist"
                    },
                    error=f"Archive not found: {archive}"
                )

            dest.mkdir(parents=True, exist_ok=True)

            if archive.suffix == '.zip':
                with zipfile.ZipFile(archive, 'r') as zf:
                    zf.extractall(dest)
            elif archive.suffix == '.gz' or '.tar' in archive.suffixes:
                with tarfile.open(archive, 'r:*') as tf:
                    tf.extractall(dest)
            else:
                return ToolResult(
                    success=False,
                    output={
                        "error": "Unsupported archive format",
                        "path": str(archive),
                        "format": archive.suffix,
                        "reason": f"Archive format '{archive.suffix}' is not supported. Use .zip or .tar.gz"
                    },
                    error=f"Unsupported archive format: {archive.suffix}"
                )

            return ToolResult(
                success=True,
                output={
                    "archive": str(archive),
                    "destination": str(dest),
                    "extracted": True
                }
            )

        except Exception as e:
            logger.error(f"Error decompressing {archive_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to decompress",
                    "archive_path": archive_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class FindDuplicateFilesTool(Tool):
    """Find duplicate files by content hash"""

    def __init__(self):
        super().__init__()
        self.name = "find_duplicate_files"
        self.description = "Find duplicate files in a directory by comparing checksums"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to search for duplicates",
                required=True
            ),
            ToolParameter(
                name="recursive",
                type="boolean",
                description="Search recursively",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="find_duplicate_files",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SEARCH_DATA,
                    description="Search for and identify duplicate files"
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    description="Search for and identify duplicate files"
                )
            ]
        )

    async def execute(self, directory_path: str, recursive: bool = True) -> ToolResult:
        """Find duplicate files"""
        try:
            dir_path = Path(directory_path).expanduser().resolve()

            if not dir_path.exists() or not dir_path.is_dir():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Invalid directory",
                        "path": str(dir_path),
                        "reason": "The specified path does not exist or is not a directory"
                    },
                    error=f"Invalid directory: {dir_path}"
                )

            # Calculate checksums for all files
            checksums = {}
            pattern = "**/*" if recursive else "*"

            for file_path in dir_path.glob(pattern):
                if file_path.is_file():
                    hash_md5 = hashlib.md5()
                    with open(file_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(8192), b''):
                            hash_md5.update(chunk)

                    checksum = hash_md5.hexdigest()
                    if checksum not in checksums:
                        checksums[checksum] = []
                    checksums[checksum].append(str(file_path))

            # Find duplicates
            duplicates = {k: v for k, v in checksums.items() if len(v) > 1}

            return ToolResult(
                success=True,
                output={
                    "directory": str(dir_path),
                    "total_files": sum(len(v) for v in checksums.values()),
                    "unique_files": len(checksums),
                    "duplicate_sets": len(duplicates),
                    "duplicates": duplicates
                }
            )

        except Exception as e:
            logger.error(f"Error finding duplicates in {directory_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to find duplicates",
                    "directory_path": directory_path,
                    "reason": str(e)
                },
                error=str(e)
            )


class SyncDirectoryTool(Tool):
    """Sync directories (like rsync)"""

    def __init__(self):
        super().__init__()
        self.name = "sync_directory"
        self.description = "Synchronize files from source directory to destination (like rsync)"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="source_path",
                type="string",
                description="Source directory path",
                required=True
            ),
            ToolParameter(
                name="destination_path",
                type="string",
                description="Destination directory path",
                required=True
            ),
            ToolParameter(
                name="delete",
                type="boolean",
                description="Delete files in destination that don't exist in source",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="sync_directory",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.COPY_DATA,
                    description="Synchronize directories with validation"
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    description="Synchronize directories with validation"
                )
            ]
        )

    async def execute(self, source_path: str, destination_path: str, delete: bool = False) -> ToolResult:
        """Sync directories"""
        try:
            from datetime import datetime

            src = Path(source_path).expanduser().resolve()
            dst = Path(destination_path).expanduser().resolve()

            if not src.exists() or not src.is_dir():
                return ToolResult(
                    success=False,
                    output={
                        "error": "Invalid source directory",
                        "path": str(src),
                        "reason": "The source directory does not exist or is not a directory"
                    },
                    error=f"Invalid source directory: {src}"
                )

            dst.mkdir(parents=True, exist_ok=True)

            copied = 0
            updated = 0
            deleted_count = 0

            # Copy/update files from source to destination
            for src_file in src.rglob('*'):
                if src_file.is_file():
                    rel_path = src_file.relative_to(src)
                    dst_file = dst / rel_path

                    dst_file.parent.mkdir(parents=True, exist_ok=True)

                    if not dst_file.exists():
                        shutil.copy2(src_file, dst_file)
                        copied += 1
                    elif src_file.stat().st_mtime > dst_file.stat().st_mtime:
                        shutil.copy2(src_file, dst_file)
                        updated += 1

            # Delete files in destination not in source
            if delete:
                for dst_file in dst.rglob('*'):
                    if dst_file.is_file():
                        rel_path = dst_file.relative_to(dst)
                        src_file = src / rel_path

                        if not src_file.exists():
                            dst_file.unlink()
                            deleted_count += 1

            return ToolResult(
                success=True,
                output={
                    "source": str(src),
                    "destination": str(dst),
                    "files_copied": copied,
                    "files_updated": updated,
                    "files_deleted": deleted_count if delete else 0
                }
            )

        except Exception as e:
            logger.error(f"Error syncing {source_path} to {destination_path}: {e}")
            return ToolResult(
                success=False,
                output={
                    "error": "Failed to sync directories",
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "reason": str(e)
                },
                error=str(e)
            )
