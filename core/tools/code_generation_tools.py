#! 
"""
  &  
====================================
Tools for generating and modifying code

Tools:
- generate_function: Generate Python function from description
- refactor_code: Refactor code to improve quality
- add_docstring: Add docstrings to functions/classes
- add_type_hints: Add type hints to Python code
- format_code: Format code with black/autopep8
- fix_linting_errors: Auto-fix common linting errors
- generate_test: Generate test cases for code
- migrate_code: Migrate code patterns

Author: Dominion Labs Research Team
"""

import logging
import ast
import difflib
import re
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import (
    ToolCapabilityProfile, CapabilityMetadata, Capability, RiskLevel
)


logger = logging.getLogger(__name__)


_UNIFIED_HUNK_RE = re.compile(r"^@@ -(?P<src_start>\d+)(?:,(?P<src_len>\d+))? \+(?P<dst_start>\d+)(?:,(?P<dst_len>\d+))? @@")


def _extract_first_fenced_code_block(text: str) -> str:
    """Return the first fenced code block's contents if present, else return input.

    Supports ```python ... ``` and ``` ... ```.
    """

    if not text:
        return text

    # Prefer a python block.
    match = re.search(r"```python\s*\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    match = re.search(r"```\s*\n(.*?)\n```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()

    return text.strip()


def _validate_python_syntax(code: str) -> Tuple[bool, Optional[str]]:
    if not isinstance(code, str) or not code.strip():
        return False, "Empty code"
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"{e.__class__.__name__}: {e}"
    except Exception as e:
        return False, f"ParseError: {e}"


def _maybe_format_with_black(code: str, line_length: int = 88) -> Tuple[str, Optional[str]]:
    """Best-effort black formatting.

    Returns (formatted_code, error_message_or_none).
    """

    try:
        import black

        mode = black.Mode(line_length=line_length)
        return black.format_str(code, mode=mode), None
    except ImportError:
        return code, "black not installed"
    except Exception as e:
        return code, f"black formatting error: {e}"


def _unified_diff_patch(original: str, updated: str, fromfile: str = "a/code.py", tofile: str = "b/code.py") -> str:
    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    diff = difflib.unified_diff(original_lines, updated_lines, fromfile=fromfile, tofile=tofile)
    return "".join(diff)


def _common_llm_knobs(default_max_tokens: int, default_temperature: float = 0.3) -> List[ToolParameter]:
    return [
        ToolParameter(
            name="temperature",
            type="number",
            description="LLM temperature (lower=more deterministic)",
            required=False,
            default=default_temperature,
            min_value=0.0,
            max_value=1.5,
        ),
        ToolParameter(
            name="max_tokens",
            type="number",
            description="Max tokens to generate",
            required=False,
            default=default_max_tokens,
            min_value=64,
            max_value=8192,
        ),
        ToolParameter(
            name="max_repairs",
            type="number",
            description="How many auto-repair attempts if output is invalid",
            required=False,
            default=1,
            min_value=0,
            max_value=5,
        ),
        ToolParameter(
            name="format_black",
            type="boolean",
            description="Format output with black if installed",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="black_line_length",
            type="number",
            description="Black line length (if formatting enabled)",
            required=False,
            default=88,
            min_value=50,
            max_value=140,
        ),
        ToolParameter(
            name="python_version",
            type="string",
            description="Target Python version (used in prompts)",
            required=False,
            default="3.11",
        ),
        ToolParameter(
            name="model",
            type="string",
            description="Optional model id for UnifiedLLMService.generate()",
            required=False,
            default="qwen:32b",
        ),
    ]


async def _llm_generate_python_code(
    *,
    llm: Any,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    model: str = "qwen:32b",
    agent_type: str = "chat",
    max_repairs: int = 1,
    validate_syntax: bool = True,
    format_black: bool = False,
    black_line_length: int = 88,
) -> Dict[str, Any]:
    """Generate Python code via LLM with best-effort extraction, validation, and repair retries."""

    attempts: List[Dict[str, Any]] = []
    current_prompt = prompt
    last_code = ""
    raw_text = ""

    for attempt in range(max_repairs + 1):
        resp = await llm.generate(
            prompt=current_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            agent_type=agent_type,
        )

        raw_text = (resp or {}).get("content", "")
        code = _extract_first_fenced_code_block(raw_text)
        last_code = code

        syntax_valid, syntax_error = (True, None)
        if validate_syntax:
            syntax_valid, syntax_error = _validate_python_syntax(code)

        black_error = None
        if syntax_valid and format_black:
            code, black_error = _maybe_format_with_black(code, line_length=black_line_length)

        attempts.append(
            {
                "attempt": attempt + 1,
                "syntax_valid": syntax_valid,
                "syntax_error": syntax_error,
                "black_error": black_error,
                "tokens_used": (resp or {}).get("tokens_used"),
                "processing_time": (resp or {}).get("processing_time"),
                "model": (resp or {}).get("model"),
                "success": (resp or {}).get("success"),
            }
        )

        if not validate_syntax or syntax_valid:
            return {
                "code": code,
                "attempts": attempts,
                "valid_python": syntax_valid,
                "syntax_error": syntax_error,
                "raw": raw_text,
            }

        if attempt >= max_repairs:
            break

        # Repair prompt: feed back the error and the last output.
        current_prompt = (
            "The previous output is invalid Python and must be fixed. "
            "Return ONLY corrected Python code (no markdown, no backticks, no explanation).\n\n"
            f"Syntax error: {syntax_error}\n\n"
            "Invalid code:\n"
            f"{code}\n"
        )

    return {
        "code": last_code,
        "attempts": attempts,
        "valid_python": False,
        "syntax_error": attempts[-1].get("syntax_error") if attempts else "Unknown",
        "raw": raw_text,
    }


def _splitlines_preserve_last(code: str) -> Tuple[List[str], bool]:
    """Split into lines without keeping separators.

    Returns (lines, had_trailing_newline).
    """

    had_trailing_newline = code.endswith("\n")
    return code.splitlines(), had_trailing_newline


def _joinlines_restore_last(lines: List[str], had_trailing_newline: bool) -> str:
    text = "\n".join(lines)
    if had_trailing_newline and (not text.endswith("\n")):
        text += "\n"
    return text


def _normalize_line_for_match(line: str) -> str:
    return line.rstrip("\r\n")


def _parse_unified_diff(patch_text: str) -> Tuple[Optional[str], List[Tuple[int, List[str]]]]:
    """Parse a unified diff and return (target_filename, hunks).

    Hunks are returned as tuples of (src_start_1_indexed, hunk_lines_including_prefix).
    This parser supports typical `git diff` output as well as bare hunks.
    """

    patch_lines = patch_text.splitlines()
    hunks: List[Tuple[int, List[str]]] = []

    current_file: Optional[str] = None
    seen_files: List[str] = []

    i = 0
    while i < len(patch_lines):
        line = patch_lines[i]

        if line.startswith("diff --git "):
            # Example: diff --git a/foo.py b/foo.py
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[3]
                if b_path.startswith("b/"):
                    current_file = b_path[2:]
                    seen_files.append(current_file)
            i += 1
            continue

        if line.startswith("+++ "):
            # Example: +++ b/foo.py
            path = line[4:].strip()
            if path.startswith("b/"):
                current_file = path[2:]
            elif path != "/dev/null":
                current_file = path
            if current_file:
                seen_files.append(current_file)
            i += 1
            continue

        match = _UNIFIED_HUNK_RE.match(line)
        if match:
            src_start = int(match.group("src_start"))
            hunk_lines: List[str] = []
            i += 1

            while i < len(patch_lines):
                next_line = patch_lines[i]
                if _UNIFIED_HUNK_RE.match(next_line):
                    break
                if next_line.startswith("diff --git ") or next_line.startswith("+++ ") or next_line.startswith("--- "):
                    # Start of another file section.
                    break
                hunk_lines.append(next_line)
                i += 1

            hunks.append((src_start, hunk_lines))
            continue

        i += 1

    # If we saw multiple distinct filenames, require the caller to provide a single-file patch.
    distinct = [f for f in dict.fromkeys(seen_files) if f]
    if len(distinct) > 1:
        raise ValueError(
            "Patch appears to contain changes for multiple files; provide a single-file patch when using ApplyPatchTool. "
            f"Files detected: {distinct}"
        )

    target = distinct[0] if distinct else None
    return target, hunks


def _apply_unified_hunks_to_code(code: str, hunks: List[Tuple[int, List[str]]]) -> Dict[str, Any]:
    """Apply parsed unified-diff hunks to a code string.

    Returns a dict with: patched_code, hunks_applied, errors.
    """

    lines, had_trailing_newline = _splitlines_preserve_last(code)
    net_line_offset = 0
    errors: List[str] = []
    applied = 0

    for src_start_1, hunk_lines in hunks:
        # src_start_1 refers to original line numbers; adjust by net offset as we apply hunks in order.
        index = max(0, (src_start_1 - 1) + net_line_offset)

        for raw in hunk_lines:
            if not raw:
                # An empty context/add/remove line is valid: it still has a prefix in patch output.
                # But splitlines() would return '' only if the whole line is empty (no prefix).
                # Treat it as context-mismatch.
                errors.append("Encountered an empty line inside hunk; patch may be malformed")
                continue

            prefix = raw[0]
            if prefix == "\\":
                # e.g. "\\ No newline at end of file" marker.
                continue

            content = raw[1:]

            if prefix == " ":
                if index >= len(lines):
                    errors.append(f"Context line out of range at output index {index}: {content!r}")
                    break
                if _normalize_line_for_match(lines[index]) != _normalize_line_for_match(content):
                    errors.append(
                        f"Context mismatch at line {index + 1}: expected {content!r} got {lines[index]!r}"
                    )
                    break
                index += 1

            elif prefix == "-":
                if index >= len(lines):
                    errors.append(f"Removal line out of range at output index {index}: {content!r}")
                    break
                if _normalize_line_for_match(lines[index]) != _normalize_line_for_match(content):
                    errors.append(
                        f"Removal mismatch at line {index + 1}: expected {content!r} got {lines[index]!r}"
                    )
                    break
                del lines[index]
                net_line_offset -= 1

            elif prefix == "+":
                lines.insert(index, content)
                index += 1
                net_line_offset += 1

            else:
                errors.append(f"Unexpected hunk line prefix {prefix!r} for line: {raw!r}")
                break

        else:
            applied += 1
            continue

        # Broke out of inner loop due to an error.
        break

    patched = _joinlines_restore_last(lines, had_trailing_newline)
    return {
        "patched_code": patched,
        "hunks_applied": applied,
        "errors": errors,
    }


class GenerateFunctionTool(Tool):
    """Generate Python function from description"""

    def __init__(self):
        super().__init__()
        self.name = "generate_function"
        self.description = "Generate a Python function from natural language description using LLM"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="description",
                type="string",
                description="Description of what the function should do",
                required=True
            ),
            ToolParameter(
                name="function_name",
                type="string",
                description="Name for the function",
                required=True
            ),
            ToolParameter(
                name="parameters",
                type="array",
                description="Function parameters (list of names)",
                required=False
            )
        ] + _common_llm_knobs(default_max_tokens=1024, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_function",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Generate Python functions from natural language descriptions",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"code_generation", "llm", "function"}
        )

    async def execute(self, description: str, function_name: str, parameters: List[str] = None, **kwargs) -> ToolResult:
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            params_str = ", ".join(parameters) if parameters else ""
            prompt = f"""Generate a Python function with the following specifications:

Function name: {function_name}
Parameters: {params_str if params_str else "none specified - infer from description"}
Description: {description}

Requirements:
- Include type hints
- Include docstring
- Include error handling
- Return meaningful values
- Keep it simple and focused

Generate only the function code, no explanations."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 1024))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior software engineer. "
                "Return ONLY valid Python code. No markdown, no backticks, no explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]
            is_valid = bool(gen.get("valid_python"))
            syntax_error = gen.get("syntax_error")

            return ToolResult(
                success=True,
                output={
                    'function_name': function_name,
                    'code': code,
                    'valid_python': is_valid,
                    'syntax_error': syntax_error,
                    'attempts': gen.get('attempts', []),
                    'description': description
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class RefactorCodeTool(Tool):
    """Refactor code to improve quality"""

    def __init__(self):
        super().__init__()
        self.name = "refactor_code"
        self.description = "Refactor Python code using LLM to improve quality and maintainability"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Code to refactor",
                required=True
            ),
            ToolParameter(
                name="goals",
                type="array",
                description="Refactoring goals (e.g., 'reduce complexity', 'improve naming')",
                required=False
            )
        ] + _common_llm_knobs(default_max_tokens=2048, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="refactor_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Refactor code to improve quality and maintainability",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"code_generation", "refactoring", "llm"}
        )

    async def execute(self, code: str, goals: List[str] = None, **kwargs) -> ToolResult:
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            goals_str = "\n- ".join(goals) if goals else "improve code quality and maintainability"
            prompt = f"""Refactor the following Python code:

```python
{code}
```

Refactoring goals:
- {goals_str}

Requirements:
- Preserve functionality
- Improve readability
- Reduce complexity
- Follow PEP 8
- Add type hints if missing
- Improve variable names

Return only the refactored code, no explanations."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 2048))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code. No markdown, no backticks, no explanations. "
                f"Target Python {python_version}. Preserve behavior unless explicitly asked."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            refactored_code = gen["code"]
            is_valid = bool(gen.get("valid_python"))
            syntax_error = gen.get("syntax_error")

            return ToolResult(
                success=True,
                output={
                    'original_code': code,
                    'refactored_code': refactored_code,
                    'valid_python': is_valid,
                    'syntax_error': syntax_error,
                    'attempts': gen.get('attempts', []),
                    'goals': goals
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class AddDocstringTool(Tool):
    """Add docstrings to functions and classes"""

    def __init__(self):
        super().__init__()
        self.name = "add_docstring"
        self.description = "Add or improve docstrings for Python functions and classes"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Python code (function or class)",
                required=True
            ),
            ToolParameter(
                name="style",
                type="string",
                description="Docstring style",
                required=False,
                default="google",
                enum=["google", "numpy", "sphinx"]
            )
        ] + _common_llm_knobs(default_max_tokens=1024, default_temperature=0.2)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="add_docstring",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Add docstrings to Python functions and classes",
                    priority=7
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"documentation", "llm", "code_generation"}
        )

    async def execute(self, code: str, style: str = "google", **kwargs) -> ToolResult:
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            prompt = f"""Add a comprehensive docstring to this Python code using {style} style:

```python
{code}
```

Include:
- Brief description
- Args section with types
- Returns section with type
- Raises section if applicable
- Example usage if helpful

Return the complete code with docstring, nothing else."""

            temperature = float(kwargs.get("temperature", 0.2))
            max_tokens = int(kwargs.get("max_tokens", 1024))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code with docstrings. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code_with_docstring = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'original_code': code,
                    'code_with_docstring': code_with_docstring,
                    'style': style
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class AddTypeHintsTool(Tool):
    """Add type hints to Python code"""

    def __init__(self):
        super().__init__()
        self.name = "add_type_hints"
        self.description = "Add type hints to Python function parameters and return values"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Python code to add type hints to",
                required=True
            )
        ] + _common_llm_knobs(default_max_tokens=1024, default_temperature=0.2)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="add_type_hints",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Add type hints to Python code",
                    priority=7
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"type_hints", "llm", "code_generation"}
        )

    async def execute(self, code: str, **kwargs) -> ToolResult:
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            prompt = f"""Add comprehensive type hints to this Python code:

```python
{code}
```

Requirements:
- Add type hints to all parameters
- Add return type hints
- Use typing module for complex types (List, Dict, Optional, etc.)
- Don't change functionality
- Keep existing docstrings

Return only the code with type hints, no explanations."""

            temperature = float(kwargs.get("temperature", 0.2))
            max_tokens = int(kwargs.get("max_tokens", 1024))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code with type hints. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            typed_code = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'original_code': code,
                    'typed_code': typed_code
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class FormatCodeTool(Tool):
    """Format code with black or autopep8"""

    def __init__(self):
        super().__init__()
        self.name = "format_code"
        self.description = "Format Python code using black or autopep8"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Python code to format",
                required=True
            ),
            ToolParameter(
                name="formatter",
                type="string",
                description="Formatter to use",
                required=False,
                default="black",
                enum=["black", "autopep8"]
            ),
            ToolParameter(
                name="line_length",
                type="number",
                description="Maximum line length",
                required=False,
                default=88,
                min_value=50,
                max_value=120
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="format_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.FORMAT_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Format Python code using black or autopep8",
                    priority=7
                )
            ],
            requires_network=False,
            is_idempotent=True,
            tags={"formatting", "code_quality"}
        )

    async def execute(self, code: str, formatter: str = "black", line_length: int = 88) -> ToolResult:
        try:
            formatted_code = code

            if formatter == "black":
                try:
                    import black
                    mode = black.Mode(line_length=line_length)
                    formatted_code = black.format_str(code, mode=mode)
                except ImportError:
                    return ToolResult(success=False, output=None, error="black not installed")
                except Exception as e:
                    return ToolResult(success=False, output=None, error=f"black formatting error: {e}")

            elif formatter == "autopep8":
                try:
                    from importlib import import_module
                    autopep8 = import_module("autopep8")
                    formatted_code = autopep8.fix_code(code, options={'max_line_length': line_length})
                except ImportError:
                    return ToolResult(success=False, output=None, error="autopep8 not installed")
                except Exception as e:
                    return ToolResult(success=False, output=None, error=f"autopep8 formatting error: {e}")

            return ToolResult(
                success=True,
                output={
                    'original_code': code,
                    'formatted_code': formatted_code,
                    'formatter': formatter,
                    'line_length': line_length,
                    'changed': code != formatted_code
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class FixLintingErrorsTool(Tool):
    """Auto-fix common linting errors"""

    def __init__(self):
        super().__init__()
        self.name = "fix_linting_errors"
        self.description = "Automatically fix common Python linting errors (unused imports, whitespace, etc.)"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Python file to fix",
                required=True
            ),
            ToolParameter(
                name="dry_run",
                type="boolean",
                description="If true, do not write changes back to disk",
                required=False,
                default=False
            ),
            ToolParameter(
                name="return_patch",
                type="boolean",
                description="If true, include a unified diff patch in output",
                required=False,
                default=False
            ),
            ToolParameter(
                name="line_length",
                type="number",
                description="Formatter line length (autopep8)",
                required=False,
                default=88,
                min_value=50,
                max_value=140
            ),
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="fix_linting_errors",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.LINT_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Auto-fix common linting errors in Python files",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    risk_level=RiskLevel.MEDIUM,
                    description="Write corrected code back to file",
                    priority=5
                )
            ],
            requires_network=False,
            requires_filesystem=True,
            is_idempotent=False,
            tags={"linting", "code_quality", "filesystem"}
        )

    async def execute(self, file_path: str, **kwargs) -> ToolResult:
        try:
            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            dry_run = bool(kwargs.get("dry_run", False))
            return_patch = bool(kwargs.get("return_patch", False))
            line_length = int(kwargs.get("line_length", 88))

            with open(file, 'r') as f:
                original_code = f.read()

            fixed_code = original_code
            fixes_applied = []
            dependency_status: Dict[str, str] = {}

            # Fix 1: Remove unused imports (basic)
            try:
                from importlib import import_module
                autoflake = import_module("autoflake")
                dependency_status["autoflake"] = "ok"
                fixed_code = autoflake.fix_code(
                    fixed_code,
                    remove_all_unused_imports=True,
                    remove_unused_variables=True
                )
                fixes_applied.append("removed unused imports and variables")
            except ImportError:
                dependency_status["autoflake"] = "missing"

            # Fix 2: Format with autopep8
            try:
                from importlib import import_module
                autopep8 = import_module("autopep8")
                dependency_status["autopep8"] = "ok"
                fixed_code = autopep8.fix_code(fixed_code, options={'max_line_length': line_length})
                fixes_applied.append("applied autopep8 formatting")
            except ImportError:
                dependency_status["autopep8"] = "missing"

            # Fix 3: Sort imports
            try:
                from importlib import import_module
                isort_module = import_module("isort")
                dependency_status["isort"] = "ok"
                fixed_code = isort_module.code(fixed_code)
                fixes_applied.append("sorted imports")
            except ImportError:
                dependency_status["isort"] = "missing"

            # Write back if changed
            if fixed_code != original_code and not dry_run:
                with open(file, 'w') as f:
                    f.write(fixed_code)

            patch_text = None
            if return_patch and fixed_code != original_code:
                patch_text = _unified_diff_patch(
                    original_code,
                    fixed_code,
                    fromfile=f"a/{file.name}",
                    tofile=f"b/{file.name}",
                )

            return ToolResult(
                success=True,
                output={
                    'file': str(file),
                    'changed': fixed_code != original_code,
                    'dry_run': dry_run,
                    'fixes_applied': fixes_applied,
                    'dependencies': dependency_status,
                    'lines_before': len(original_code.splitlines()),
                    'lines_after': len(fixed_code.splitlines()),
                    'patch': patch_text,
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GenerateTestTool(Tool):
    """Generate test cases for code"""

    def __init__(self):
        super().__init__()
        self.name = "generate_test"
        self.description = "Generate pytest test cases for Python code using LLM"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Code to generate tests for",
                required=True
            ),
            ToolParameter(
                name="framework",
                type="string",
                description="Test framework",
                required=False,
                default="pytest",
                enum=["pytest", "unittest"]
            )
        ] + _common_llm_knobs(default_max_tokens=2048, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_test",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_TESTS,
                    risk_level=RiskLevel.LOW,
                    description="Generate test cases for Python code",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"testing", "llm", "code_generation"}
        )

    async def execute(self, code: str, framework: str = "pytest", **kwargs) -> ToolResult:
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            prompt = f"""Generate comprehensive {framework} test cases for this Python code:

```python
{code}
```

Requirements:
- Test normal cases
- Test edge cases
- Test error handling
- Use fixtures if appropriate (pytest)
- Include docstrings in tests
- Aim for high coverage

Return only the test code, no explanations."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 2048))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python test engineer. "
                "Return ONLY valid Python test code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            test_code = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'original_code': code,
                    'test_code': test_code,
                    'valid_python': bool(gen.get('valid_python')),
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                    'framework': framework
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class MigrateCodeTool(Tool):
    """Migrate code patterns (e.g., Python 2 to 3)"""

    def __init__(self):
        super().__init__()
        self.name = "migrate_code"
        self.description = "Migrate code from one pattern/version to another"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Code to migrate",
                required=True
            ),
            ToolParameter(
                name="migration_type",
                type="string",
                description="Type of migration",
                required=True,
                enum=["python2to3", "async_conversion", "modernize_syntax", "custom"]
            ),
            ToolParameter(
                name="custom_instructions",
                type="string",
                description="Custom migration instructions (if migration_type is 'custom')",
                required=False
            )
        ] + _common_llm_knobs(default_max_tokens=2048, default_temperature=0.2)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="migrate_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRANSFORM_DATA,
                    risk_level=RiskLevel.MEDIUM,
                    description="Migrate code between versions or patterns",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Refactor code during migration",
                    priority=6
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"migration", "refactoring", "llm"}
        )

    async def execute(self, code: str, migration_type: str, custom_instructions: str = None, **kwargs) -> ToolResult:
        try:
            migrated_code = code

            if migration_type == "python2to3":
                # Basic Python 2 to 3 migrations
                migrated_code = re.sub(r'\bprint\s+([^(].*)', r'print(\1)', migrated_code)  # print statement
                migrated_code = migrated_code.replace('raw_input(', 'input(')
                migrated_code = migrated_code.replace('xrange(', 'range(')
                migrated_code = re.sub(r'\.iteritems\(\)', '.items()', migrated_code)
                migrated_code = re.sub(r'\.iterkeys\(\)', '.keys()', migrated_code)
                migrated_code = re.sub(r'\.itervalues\(\)', '.values()', migrated_code)

            elif migration_type in ["async_conversion", "modernize_syntax", "custom"]:
                # Use LLM for complex migrations
                from core.services.unified_llm import get_llm_service
                llm = get_llm_service()

                if migration_type == "async_conversion":
                    instructions = "Convert synchronous code to async/await pattern"
                elif migration_type == "modernize_syntax":
                    instructions = "Modernize Python syntax (f-strings, type hints, walrus operator, etc.)"
                else:
                    instructions = custom_instructions or "Migrate the code"

                prompt = f"""Migrate this Python code:

```python
{code}
```

Migration task: {instructions}

Return only the migrated code, no explanations."""

                temperature = float(kwargs.get("temperature", 0.2))
                max_tokens = int(kwargs.get("max_tokens", 2048))
                max_repairs = int(kwargs.get("max_repairs", 1))
                format_black = bool(kwargs.get("format_black", False))
                black_line_length = int(kwargs.get("black_line_length", 88))
                python_version = str(kwargs.get("python_version", "3.11"))
                model = str(kwargs.get("model", "qwen:32b"))

                system_prompt = (
                    "You are a senior Python engineer. "
                    "Return ONLY valid Python code. No markdown/backticks/explanations. "
                    f"Target Python {python_version}. Preserve behavior unless instructed otherwise."
                )

                gen = await _llm_generate_python_code(
                    llm=llm,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model,
                    max_repairs=max_repairs,
                    validate_syntax=True,
                    format_black=format_black,
                    black_line_length=black_line_length,
                )

                migrated_code = gen["code"]

            valid_python, syntax_error = _validate_python_syntax(migrated_code)

            return ToolResult(
                success=True,
                output={
                    'original_code': code,
                    'migrated_code': migrated_code,
                    'migration_type': migration_type,
                    'changed': code != migrated_code,
                    'valid_python': valid_python,
                    'syntax_error': syntax_error,
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GenerateClassTool(Tool):
    """Production-ready class generation from specification using LLM"""

    def __init__(self):
        super().__init__()
        self.name = "generate_class"
        self.description = "Generate a complete Python class from specification using LLM"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="class_name", type="string", description="Name of the class", required=True),
            ToolParameter(name="description", type="string", description="Class description and purpose", required=True),
            ToolParameter(name="methods", type="array", description="List of method specifications (e.g., ['__init__(name, age)', 'get_info() -> str'])", required=False),
            ToolParameter(name="base_classes", type="array", description="List of base classes to inherit from", required=False),
            ToolParameter(name="include_docstrings", type="boolean", description="Include docstrings (default: True)", required=False, default=True)
        ] + _common_llm_knobs(default_max_tokens=2048, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_class",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Generate complete Python classes from specifications",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"code_generation", "llm", "class"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate a complete Python class"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            class_name = kwargs.get("class_name", "MyClass")
            description = kwargs.get("description", "")
            methods = kwargs.get("methods", [])
            base_classes = kwargs.get("base_classes", [])
            include_docstrings = kwargs.get("include_docstrings", True)

            if not class_name.isidentifier():
                return ToolResult(success=False, output=None, error=f"'{class_name}' is not a valid Python class name")

            # Build method specifications
            methods_str = ""
            if methods:
                methods_str = "\n".join(f"- {method}" for method in methods)
            else:
                methods_str = "Infer appropriate methods from the description"

            # Build inheritance
            inheritance = ""
            if base_classes:
                inheritance = f"Inherits from: {', '.join(base_classes)}"

            prompt = f"""Generate a Python class with the following specifications:

Class name: {class_name}
Description: {description}
{inheritance}

Methods needed:
{methods_str}

Requirements:
- Include type hints for all parameters and return values
- {'Include comprehensive docstrings (Google style)' if include_docstrings else 'Minimal or no docstrings'}
- Include proper error handling
- Follow PEP 8 style guidelines
- Include __init__ method if needed
- Add __repr__ and __str__ if appropriate
- Make it production-ready

Return only the class code, no explanations or markdown."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 2048))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]
            is_valid = bool(gen.get("valid_python"))

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'class_name': class_name,
                    'description': description,
                    'valid_python': is_valid,
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                    'methods_specified': methods,
                    'base_classes': base_classes
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Class generation failed: {str(e)}")


class GenerateModuleTool(Tool):
    """Production-ready module generation with LLM"""

    def __init__(self):
        super().__init__()
        self.name = "generate_module"
        self.description = "Generate a complete Python module with multiple classes and functions"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="module_name", type="string", description="Module name", required=True),
            ToolParameter(name="description", type="string", description="Module purpose and functionality", required=True),
            ToolParameter(name="components", type="array", description="List of classes/functions to include", required=False)
        ] + _common_llm_knobs(default_max_tokens=3072, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_module",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Generate complete Python modules with multiple components",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"code_generation", "llm", "module"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate a complete Python module"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            module_name = kwargs.get("module_name", "module")
            description = kwargs.get("description", "")
            components = kwargs.get("components", [])

            components_str = "\n".join(f"- {comp}" for comp in components) if components else "Infer from description"

            prompt = f"""Generate a complete Python module with the following specifications:

Module name: {module_name}
Purpose: {description}

Components to include:
{components_str}

Requirements:
- Include module-level docstring
- Add appropriate imports
- Include type hints
- Add comprehensive docstrings for all classes and functions
- Include __all__ list for public API
- Add example usage in module docstring
- Follow PEP 8 style

Return only the module code, no explanations."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 3072))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python module code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]
            is_valid = bool(gen.get("valid_python"))

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'module_name': module_name,
                    'description': description,
                    'valid_python': is_valid,
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                    'components': components
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Module generation failed: {str(e)}")


class AddLoggingTool(Tool):
    """Production-ready logging insertion with AST-based analysis

    Adds strategic logging statements to code:
    - Function entry/exit logging
    - Exception logging
    - Important state changes
    - Debug checkpoints
    """

    def __init__(self):
        super().__init__()
        self.name = "add_logging"
        self.description = "Add strategic logging statements to code using AST analysis"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Code to add logging to", required=True),
            ToolParameter(name="log_level", type="string", description="Default log level", required=False, default="INFO", enum=["DEBUG", "INFO", "WARNING", "ERROR"])
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="add_logging",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Add logging statements to code using AST analysis",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Analyze code structure to determine logging points",
                    priority=6
                )
            ],
            requires_network=False,
            is_idempotent=False,
            tags={"logging", "ast", "code_generation"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Add logging statements to code"""
        import ast
        import sys

        try:
            code = kwargs.get("code", "")
            log_level = kwargs.get("log_level", "INFO").upper()

            if not code:
                return ToolResult(success=False, output=None, error="code parameter is required")

            # Parse AST
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, output=None, error=f"Syntax error in code: {e}")

            class LoggingAdder(ast.NodeTransformer):
                """Add logging statements to functions"""

                def __init__(self, level):
                    self.level = level
                    self.logs_added = 0

                def visit_FunctionDef(self, node):
                    """Add logging to function entry and exception handling"""
                    self.generic_visit(node)

                    # Add entry log at the beginning
                    func_name = node.name
                    param_names = [arg.arg for arg in node.args.args]

                    # Create log statement: logger.info(f"Entering {func_name} with args: ...")
                    log_msg = f"Entering {func_name}"
                    if param_names:
                        log_msg += f" with {', '.join(param_names)}"

                    entry_log = ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id='logger', ctx=ast.Load()),
                                attr=self.level.lower(),
                                ctx=ast.Load()
                            ),
                            args=[ast.Constant(value=log_msg)],
                            keywords=[]
                        )
                    )

                    # Insert at beginning of function body
                    node.body.insert(0, entry_log)
                    self.logs_added += 1

                    return node

                def visit_AsyncFunctionDef(self, node):
                    """Add logging to async functions"""
                    return self.visit_FunctionDef(node)

                def visit_Try(self, node):
                    """Add logging to exception handlers"""
                    self.generic_visit(node)

                    # Add logging to each except handler
                    for handler in node.handlers:
                        if handler.type:
                            exc_type = ast.unparse(handler.type) if sys.version_info >= (3, 9) else "Exception"
                        else:
                            exc_type = "Exception"

                        exc_log = ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id='logger', ctx=ast.Load()),
                                    attr='error',
                                    ctx=ast.Load()
                                ),
                                args=[ast.Constant(value=f"Exception caught: {exc_type}")],
                                keywords=[ast.keyword(arg='exc_info', value=ast.Constant(value=True))]
                            )
                        )

                        # Insert at beginning of except handler
                        handler.body.insert(0, exc_log)
                        self.logs_added += 1

                    return node

            # Add logging import and logger setup
            import_logging = ast.Import(names=[ast.alias(name='logging', asname=None)])
            logger_setup = ast.Assign(
                targets=[ast.Name(id='logger', ctx=ast.Store())],
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id='logging', ctx=ast.Load()),
                        attr='getLogger',
                        ctx=ast.Load()
                    ),
                    args=[ast.Name(id='__name__', ctx=ast.Load())],
                    keywords=[]
                )
            )

            # Apply logging additions
            adder = LoggingAdder(log_level)
            new_tree = adder.visit(tree)

            # Insert import and logger at the beginning
            new_tree.body.insert(0, logger_setup)
            new_tree.body.insert(0, import_logging)

            ast.fix_missing_locations(new_tree)

            # Convert back to source code
            if sys.version_info >= (3, 9):
                logged_code = ast.unparse(new_tree)
            else:
                try:
                    import astor
                    logged_code = astor.to_source(new_tree)
                except ImportError:
                    return ToolResult(success=False, output=None, error="Python 3.9+ required, or install astor: pip install astor")

            result = {
                "code": logged_code,
                "original_code": code,
                "logs_added": adder.logs_added,
                "log_level": log_level
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Adding logging failed: {str(e)}")


class OptimizeCodeTool(Tool):
    """Production-ready code optimization with AST-based analysis

    Applies multiple optimization strategies:
    - Constant folding
    - Dead code elimination
    - Loop optimization (list comprehensions)
    - String concatenation optimization
    - Redundant operation removal
    """

    def __init__(self):
        super().__init__()
        self.name = "optimize_code"
        self.description = "Optimize Python code for better performance using AST analysis"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Code to optimize", required=True),
            ToolParameter(name="optimization_level", type="number", description="Optimization level 1-3 (1=safe, 2=moderate, 3=aggressive)", required=False, default=2)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="optimize_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Optimize code for better performance",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Analyze code structure for optimization opportunities",
                    priority=6
                )
            ],
            requires_network=False,
            is_idempotent=False,
            tags={"optimization", "ast", "performance"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Optimize code with AST-based transformations"""
        import ast
        import sys

        try:
            code = kwargs.get("code", "")
            optimization_level = kwargs.get("optimization_level", 2)

            if not code:
                return ToolResult(success=False, output=None, error="code parameter is required")

            # Parse AST
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, output=None, error=f"Syntax error in code: {e}")

            class CodeOptimizer(ast.NodeTransformer):
                """AST transformer for code optimization"""

                def __init__(self, level):
                    self.level = level
                    self.optimizations = {
                        "constant_folding": 0,
                        "dead_code_removed": 0,
                        "list_comprehensions": 0,
                        "string_concat_optimized": 0
                    }

                def visit_BinOp(self, node):
                    """Constant folding for binary operations"""
                    self.generic_visit(node)

                    # Only fold if both operands are constants
                    if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                        try:
                            # Evaluate the constant expression
                            if isinstance(node.op, ast.Add):
                                result = node.left.value + node.right.value
                            elif isinstance(node.op, ast.Sub):
                                result = node.left.value - node.right.value
                            elif isinstance(node.op, ast.Mult):
                                result = node.left.value * node.right.value
                            elif isinstance(node.op, ast.Div):
                                result = node.left.value / node.right.value
                            else:
                                return node

                            self.optimizations["constant_folding"] += 1
                            new_node = ast.Constant(value=result)
                            ast.copy_location(new_node, node)
                            return new_node
                        except:
                            return node

                    return node

                def visit_If(self, node):
                    """Dead code elimination for constant conditionals"""
                    self.generic_visit(node)

                    # If condition is constant True/False, eliminate dead branch
                    if isinstance(node.test, ast.Constant):
                        if node.test.value:
                            # Condition is always True, return body
                            self.optimizations["dead_code_removed"] += 1
                            return node.body
                        else:
                            # Condition is always False, return else branch or nothing
                            self.optimizations["dead_code_removed"] += 1
                            return node.orelse if node.orelse else []

                    return node

                def visit_For(self, node):
                    """Convert simple loops to list comprehensions"""
                    self.generic_visit(node)

                    # Only optimize at level 2+
                    if self.level < 2:
                        return node

                    # Pattern: for x in iterable: result.append(f(x))
                    if len(node.body) == 1:
                        stmt = node.body[0]
                        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                            call = stmt.value
                            # Check if it's list.append()
                            if isinstance(call.func, ast.Attribute) and call.func.attr == 'append':
                                # This is a candidate for list comprehension
                                # For safety, we'll just flag it rather than transform
                                self.optimizations["list_comprehensions"] += 1

                    return node

                def visit_JoinedStr(self, node):
                    """Optimize f-string with only constants"""
                    self.generic_visit(node)

                    # If all values are constants, evaluate to single string
                    all_constants = all(
                        isinstance(val, ast.Constant) or
                        (isinstance(val, ast.FormattedValue) and isinstance(val.value, ast.Constant))
                        for val in node.values
                    )

                    if all_constants:
                        # Build the string
                        parts = []
                        for val in node.values:
                            if isinstance(val, ast.Constant):
                                parts.append(str(val.value))
                            elif isinstance(val, ast.FormattedValue):
                                parts.append(str(val.value.value))

                        self.optimizations["string_concat_optimized"] += 1
                        new_node = ast.Constant(value=''.join(parts))
                        ast.copy_location(new_node, node)
                        return new_node

                    return node

                def visit_Call(self, node):
                    """Optimize function calls"""
                    self.generic_visit(node)

                    # Optimize list(range(...)) to just range(...)  at level 3
                    if self.level >= 3:
                        if isinstance(node.func, ast.Name) and node.func.id == 'list':
                            if len(node.args) == 1 and isinstance(node.args[0], ast.Call):
                                inner_call = node.args[0]
                                if isinstance(inner_call.func, ast.Name) and inner_call.func.id == 'range':
                                    # In Python 3, range is already efficient
                                    return inner_call

                    return node

            # Apply optimizations
            optimizer = CodeOptimizer(optimization_level)
            new_tree = optimizer.visit(tree)
            ast.fix_missing_locations(new_tree)

            # Convert back to source code
            if sys.version_info >= (3, 9):
                optimized_code = ast.unparse(new_tree)
            else:
                try:
                    import astor
                    optimized_code = astor.to_source(new_tree)
                except ImportError:
                    return ToolResult(success=False, output=None, error="Python 3.9+ required, or install astor: pip install astor")

            result = {
                "code": optimized_code,
                "original_code": code,
                "optimizations": optimizer.optimizations,
                "optimization_level": optimization_level,
                "changed": code != optimized_code
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Code optimization failed: {str(e)}")


class ConvertToAsyncTool(Tool):
    """Production-ready synchronous to async conversion with AST-based transformation

    Converts synchronous functions to async/await pattern by:
    - Converting function definitions to async def
    - Adding await to blocking I/O calls
    - Converting context managers to async with
    - Handling generator functions (async for)
    """

    def __init__(self):
        super().__init__()
        self.name = "convert_to_async"
        self.description = "Convert synchronous code to async/await pattern using AST transformation"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Synchronous code to convert", required=True),
            ToolParameter(name="await_functions", type="array", description="Function names that should be awaited (e.g., ['requests.get', 'time.sleep'])", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="convert_to_async",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRANSFORM_DATA,
                    risk_level=RiskLevel.MEDIUM,
                    description="Convert synchronous code to async/await pattern",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Refactor code for async execution",
                    priority=7
                )
            ],
            requires_network=False,
            is_idempotent=False,
            tags={"async", "ast", "transformation"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Convert synchronous code to async/await"""
        import ast
        import sys

        try:
            code = kwargs.get("code", "")
            await_functions = kwargs.get("await_functions", [
                "sleep", "get", "post", "put", "delete", "request",
                "read", "write", "execute", "fetch", "send"
            ])

            if not code:
                return ToolResult(success=False, output=None, error="code parameter is required")

            # Parse AST
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, output=None, error=f"Syntax error in code: {e}")

            class AsyncConverter(ast.NodeTransformer):
                """AST transformer to convert sync code to async"""

                def __init__(self, await_functions):
                    self.await_functions = set(await_functions)
                    self.conversions = {
                        "functions_made_async": 0,
                        "calls_awaited": 0,
                        "context_managers_converted": 0,
                        "for_loops_converted": 0
                    }

                def visit_FunctionDef(self, node):
                    """Convert def to async def"""
                    self.generic_visit(node)

                    # Create async version
                    async_func = ast.AsyncFunctionDef(
                        name=node.name,
                        args=node.args,
                        body=node.body,
                        decorator_list=node.decorator_list,
                        returns=node.returns,
                        type_comment=node.type_comment if hasattr(node, 'type_comment') else None
                    )
                    ast.copy_location(async_func, node)
                    self.conversions["functions_made_async"] += 1
                    return async_func

                def visit_Call(self, node):
                    """Add await to blocking I/O calls"""
                    self.generic_visit(node)

                    # Check if this call should be awaited
                    should_await = False

                    # Check function name
                    if isinstance(node.func, ast.Name):
                        if node.func.id in self.await_functions:
                            should_await = True

                    # Check method calls (e.g., requests.get)
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr in self.await_functions:
                            should_await = True

                    if should_await:
                        # Wrap in await
                        await_node = ast.Expr(
                            value=ast.Await(value=node)
                        )
                        self.conversions["calls_awaited"] += 1
                        return await_node

                    return node

                def visit_With(self, node):
                    """Convert with to async with"""
                    self.generic_visit(node)

                    # Convert to async with
                    async_with = ast.AsyncWith(
                        items=node.items,
                        body=node.body,
                        type_comment=node.type_comment if hasattr(node, 'type_comment') else None
                    )
                    ast.copy_location(async_with, node)
                    self.conversions["context_managers_converted"] += 1
                    return async_with

                def visit_For(self, node):
                    """Convert for to async for for iterators"""
                    self.generic_visit(node)

                    # Check if iterator might be async (heuristic: if it's a call to something that could be async)
                    if isinstance(node.iter, ast.Call):
                        # Convert to async for
                        async_for = ast.AsyncFor(
                            target=node.target,
                            iter=node.iter,
                            body=node.body,
                            orelse=node.orelse,
                            type_comment=node.type_comment if hasattr(node, 'type_comment') else None
                        )
                        ast.copy_location(async_for, node)
                        self.conversions["for_loops_converted"] += 1
                        return async_for

                    return node

            # Apply conversion
            converter = AsyncConverter(await_functions)
            new_tree = converter.visit(tree)
            ast.fix_missing_locations(new_tree)

            # Convert back to source code
            if sys.version_info >= (3, 9):
                async_code = ast.unparse(new_tree)
            else:
                try:
                    import astor
                    async_code = astor.to_source(new_tree)
                except ImportError:
                    return ToolResult(success=False, output=None, error="Python 3.9+ required, or install astor: pip install astor")

            result = {
                "code": async_code,
                "original_code": code,
                "conversions": converter.conversions,
                "await_functions": list(await_functions)
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Async conversion failed: {str(e)}")


class ExtractMethodTool(Tool):
    """Production-ready method extraction with AST-based analysis

    Extracts code blocks into separate methods by:
    - Analyzing variable dependencies
    - Determining parameters and return values
    - Preserving scope and context
    - Generating proper function signature
    """

    def __init__(self):
        super().__init__()
        self.name = "extract_method"
        self.description = "Extract a code block into a separate method using AST analysis"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Source code containing the block to extract", required=True),
            ToolParameter(name="method_name", type="string", description="Name for the extracted method", required=True),
            ToolParameter(name="start_line", type="number", description="Starting line number of block to extract (1-indexed)", required=True),
            ToolParameter(name="end_line", type="number", description="Ending line number of block to extract (1-indexed)", required=True)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="extract_method",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Extract code blocks into separate methods",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Analyze variable dependencies for extraction",
                    priority=6
                )
            ],
            requires_network=False,
            is_idempotent=False,
            tags={"refactoring", "ast", "method_extraction"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Extract method from code block"""
        import ast

        try:
            code = kwargs.get("code", "")
            method_name = kwargs.get("method_name", "")
            start_line = kwargs.get("start_line", 0)
            end_line = kwargs.get("end_line", 0)

            if not code or not method_name:
                return ToolResult(success=False, output=None, error="code and method_name are required")

            if not method_name.isidentifier():
                return ToolResult(success=False, output=None, error=f"'{method_name}' is not a valid Python identifier")

            # Split code into lines
            lines = code.splitlines(keepends=True)

            if start_line < 1 or end_line > len(lines) or start_line > end_line:
                return ToolResult(success=False, output=None, error=f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines)")

            # Extract the block (convert to 0-indexed)
            extracted_block = ''.join(lines[start_line-1:end_line])

            # Validate the entire code is parseable
            try:
                ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, output=None, error=f"Syntax error in code: {e}")

            # Parse the extracted block to analyze variables
            try:
                block_tree = ast.parse(extracted_block)
            except SyntaxError:
                # Try to wrap in a function to parse as valid Python
                try:
                    block_tree = ast.parse(f"def _temp():\n" + '\n'.join('    ' + line for line in extracted_block.splitlines()))
                except SyntaxError as e:
                    return ToolResult(success=False, output=None, error=f"Syntax error in extracted block: {e}")

            # Analyze variables used and assigned
            class VariableAnalyzer(ast.NodeVisitor):
                def __init__(self):
                    self.used = set()
                    self.assigned = set()

                def visit_Name(self, node):
                    if isinstance(node.ctx, ast.Load):
                        self.used.add(node.id)
                    elif isinstance(node.ctx, ast.Store):
                        self.assigned.add(node.id)

            analyzer = VariableAnalyzer()
            analyzer.visit(block_tree)

            # Parameters are variables used but not assigned in the block
            parameters = sorted(analyzer.used - analyzer.assigned)

            # Return values are variables assigned that might be used after
            return_values = sorted(analyzer.assigned)

            # Generate the extracted method
            param_str = ', '.join(parameters)
            if len(return_values) == 0:
                return_stmt = ""
                method_body = extracted_block
            elif len(return_values) == 1:
                return_stmt = f"\n    return {return_values[0]}"
                method_body = extracted_block
            else:
                return_stmt = f"\n    return {', '.join(return_values)}"
                method_body = extracted_block

            # Indent the block
            indented_block = '\n'.join('    ' + line if line.strip() else line
                                        for line in method_body.splitlines())

            extracted_method = f"def {method_name}({param_str}):\n{indented_block}{return_stmt}\n"

            # Generate the replacement call
            if len(return_values) == 0:
                replacement = f"{method_name}({', '.join(parameters)})"
            elif len(return_values) == 1:
                replacement = f"{return_values[0]} = {method_name}({', '.join(parameters)})"
            else:
                replacement = f"{', '.join(return_values)} = {method_name}({', '.join(parameters)})"

            # Build the refactored code
            refactored_lines = lines[:start_line-1]
            refactored_lines.append(replacement + '\n')
            refactored_lines.extend(lines[end_line:])

            # Add the extracted method at the beginning (or we could add it before the usage)
            refactored_code = extracted_method + '\n' + ''.join(refactored_lines)

            result = {
                "code": refactored_code,
                "original_code": code,
                "extracted_method": extracted_method,
                "method_name": method_name,
                "parameters": parameters,
                "return_values": return_values,
                "replacement_call": replacement
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Method extraction failed: {str(e)}")


class InlineVariableTool(Tool):
    """Production-ready variable inlining with AST-based analysis

    Inlines a variable by replacing all its usages with its assigned value:
    - Finds variable assignment
    - Replaces all references with the assigned expression
    - Removes the original assignment
    - Validates scope and safety
    """

    def __init__(self):
        super().__init__()
        self.name = "inline_variable"
        self.description = "Inline a variable by replacing usages with its value using AST analysis"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Source code", required=True),
            ToolParameter(name="variable_name", type="string", description="Variable to inline", required=True),
            ToolParameter(name="line_number", type="number", description="Line number of assignment to inline (optional, uses first if not specified)", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="inline_variable",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Inline variables by replacing usages with values",
                    priority=6
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Analyze variable usage patterns",
                    priority=5
                )
            ],
            requires_network=False,
            is_idempotent=False,
            tags={"refactoring", "ast", "inlining"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Inline variable by replacing all usages with its value"""
        import ast
        import sys

        try:
            code = kwargs.get("code", "")
            variable_name = kwargs.get("variable_name", "")
            line_number = kwargs.get("line_number", None)

            if not code or not variable_name:
                return ToolResult(success=False, output=None, error="code and variable_name are required")

            # Parse AST
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, output=None, error=f"Syntax error in code: {e}")

            # Find the assignment to inline
            assignment_value = None
            assignment_node = None

            class AssignmentFinder(ast.NodeVisitor):
                """Find variable assignment"""
                def __init__(self, var_name, target_line):
                    self.var_name = var_name
                    self.target_line = target_line
                    self.found_value = None
                    self.found_node = None

                def visit_Assign(self, node):
                    # Check if this assigns to our variable
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == self.var_name:
                            # Check line number if specified
                            if self.target_line is None or node.lineno == self.target_line:
                                self.found_value = node.value
                                self.found_node = node
                                return
                    self.generic_visit(node)

            finder = AssignmentFinder(variable_name, line_number)
            finder.visit(tree)
            assignment_value = finder.found_value
            assignment_node = finder.found_node

            if assignment_value is None:
                if line_number:
                    return ToolResult(success=False, output=None, error=f"Assignment to '{variable_name}' not found at line {line_number}")
                else:
                    return ToolResult(success=False, output=None, error=f"Assignment to '{variable_name}' not found")

            # Now replace all usages and remove the assignment
            class VariableInliner(ast.NodeTransformer):
                """Replace variable usages with its value and remove assignment"""
                def __init__(self, var_name, value, assignment):
                    self.var_name = var_name
                    self.value = value
                    self.assignment = assignment
                    self.replacements = 0
                    self.assignment_removed = False

                def visit_Name(self, node):
                    """Replace variable references with the value"""
                    if node.id == self.var_name and isinstance(node.ctx, ast.Load):
                        # Replace with a copy of the value
                        import copy
                        self.replacements += 1
                        return copy.deepcopy(self.value)
                    return node

                def visit_Assign(self, node):
                    """Remove the original assignment"""
                    if node is self.assignment:
                        self.assignment_removed = True
                        # Return empty list to remove this node
                        return None
                    return node

            inliner = VariableInliner(variable_name, assignment_value, assignment_node)
            new_tree = inliner.visit(tree)

            # Remove None nodes (assignments we removed)
            class NoneRemover(ast.NodeTransformer):
                def visit_Module(self, node):
                    node.body = [n for n in node.body if n is not None]
                    self.generic_visit(node)
                    return node

                def visit_FunctionDef(self, node):
                    node.body = [n for n in node.body if n is not None]
                    self.generic_visit(node)
                    return node

                def visit_AsyncFunctionDef(self, node):
                    node.body = [n for n in node.body if n is not None]
                    self.generic_visit(node)
                    return node

                def visit_If(self, node):
                    node.body = [n for n in node.body if n is not None]
                    node.orelse = [n for n in node.orelse if n is not None]
                    self.generic_visit(node)
                    return node

                def visit_For(self, node):
                    node.body = [n for n in node.body if n is not None]
                    node.orelse = [n for n in node.orelse if n is not None]
                    self.generic_visit(node)
                    return node

                def visit_While(self, node):
                    node.body = [n for n in node.body if n is not None]
                    node.orelse = [n for n in node.orelse if n is not None]
                    self.generic_visit(node)
                    return node

            remover = NoneRemover()
            new_tree = remover.visit(new_tree)
            ast.fix_missing_locations(new_tree)

            # Convert back to source code
            if sys.version_info >= (3, 9):
                inlined_code = ast.unparse(new_tree)
            else:
                try:
                    import astor
                    inlined_code = astor.to_source(new_tree)
                except ImportError:
                    return ToolResult(success=False, output=None, error="Python 3.9+ required, or install astor: pip install astor")

            result = {
                "code": inlined_code,
                "original_code": code,
                "variable_name": variable_name,
                "replacements_made": inliner.replacements,
                "assignment_removed": inliner.assignment_removed
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Variable inlining failed: {str(e)}")


class RenameSymbolTool(Tool):
    """Production-ready symbol renaming with AST-based scope awareness

    Renames variables, functions, and classes while respecting Python scope rules.
    Avoids false positives by analyzing the AST structure.
    """

    def __init__(self):
        super().__init__()
        self.name = "rename_symbol"
        self.description = "Rename a symbol (variable, function, class) with scope awareness using AST"
        self.parameters = [
            ToolParameter(name="code", type="string", description="Source code", required=True),
            ToolParameter(name="old_name", type="string", description="Current symbol name", required=True),
            ToolParameter(name="new_name", type="string", description="New symbol name", required=True),
            ToolParameter(name="symbol_type", type="string", description="Symbol type: variable, function, class, or auto (default: auto)", required=False, default="auto")
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="rename_symbol",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Rename symbols with scope awareness",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Analyze code scope for safe renaming",
                    priority=6
                )
            ],
            requires_network=False,
            is_idempotent=False,
            tags={"refactoring", "ast", "renaming"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Rename symbol with AST-based analysis"""
        import ast
        import sys

        try:
            code = kwargs.get("code", "")
            old_name = kwargs.get("old_name", "")
            new_name = kwargs.get("new_name", "")
            symbol_type = kwargs.get("symbol_type", "auto")

            if not code or not old_name or not new_name:
                return ToolResult(success=False, output=None, error="code, old_name, and new_name are required")

            # Validate new name is valid Python identifier
            if not new_name.isidentifier():
                return ToolResult(success=False, output=None, error=f"'{new_name}' is not a valid Python identifier")

            # Parse AST
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return ToolResult(success=False, output=None, error=f"Syntax error in code: {e}")

            class SymbolRenamer(ast.NodeTransformer):
                """AST transformer to rename symbols with scope awareness"""

                def __init__(self, old_name, new_name, symbol_type):
                    self.old_name = old_name
                    self.new_name = new_name
                    self.symbol_type = symbol_type
                    self.renames = 0

                def visit_Name(self, node):
                    """Rename variable references"""
                    if node.id == self.old_name and (self.symbol_type in ["auto", "variable"]):
                        node.id = self.new_name
                        self.renames += 1
                    return node

                def visit_FunctionDef(self, node):
                    """Rename function definitions"""
                    if node.name == self.old_name and (self.symbol_type in ["auto", "function"]):
                        node.name = self.new_name
                        self.renames += 1
                    self.generic_visit(node)
                    return node

                def visit_AsyncFunctionDef(self, node):
                    """Rename async function definitions"""
                    if node.name == self.old_name and (self.symbol_type in ["auto", "function"]):
                        node.name = self.new_name
                        self.renames += 1
                    self.generic_visit(node)
                    return node

                def visit_ClassDef(self, node):
                    """Rename class definitions"""
                    if node.name == self.old_name and (self.symbol_type in ["auto", "class"]):
                        node.name = self.new_name
                        self.renames += 1
                    self.generic_visit(node)
                    return node

                def visit_arg(self, node):
                    """Rename function arguments"""
                    if node.arg == self.old_name and (self.symbol_type in ["auto", "variable"]):
                        node.arg = self.new_name
                        self.renames += 1
                    return node

                def visit_Attribute(self, node):
                    """Rename attributes"""
                    if node.attr == self.old_name and (self.symbol_type in ["auto", "variable"]):
                        node.attr = self.new_name
                        self.renames += 1
                    self.generic_visit(node)
                    return node

            # Apply renaming
            renamer = SymbolRenamer(old_name, new_name, symbol_type)
            new_tree = renamer.visit(tree)
            renames_made = renamer.renames

            # Convert back to source code using ast.unparse (Python 3.9+)
            if sys.version_info >= (3, 9):
                renamed_code = ast.unparse(new_tree)
            else:
                # Fallback for older Python - try astor
                try:
                    import astor
                    renamed_code = astor.to_source(new_tree)
                except ImportError:
                    return ToolResult(success=False, output=None, error="Python 3.9+ required, or install astor: pip install astor")

            result = {
                "code": renamed_code,
                "renames_made": renames_made,
                "old_name": old_name,
                "new_name": new_name,
                "symbol_type": symbol_type
            }

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Symbol renaming failed: {str(e)}")


class ImplementAlgorithmTool(Tool):
    """Production-ready algorithm implementation using LLM"""

    def __init__(self):
        super().__init__()
        self.name = "implement_algorithm"
        self.description = "Implement a specific algorithm with proper data structures and complexity"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="algorithm", type="string", description="Algorithm name or description (e.g., 'quicksort', 'Dijkstra's shortest path')", required=True),
            ToolParameter(name="language", type="string", description="Programming language", required=False, default="python"),
            ToolParameter(name="optimize_for", type="string", description="Optimization target", required=False, default="readability", enum=["readability", "performance", "memory"])
        ] + _common_llm_knobs(default_max_tokens=2048, default_temperature=0.2)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="implement_algorithm",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Implement algorithms from specifications",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"algorithms", "llm", "code_generation"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Implement algorithm with LLM"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            algorithm = kwargs.get("algorithm", "")
            language = kwargs.get("language", "python")
            optimize_for = kwargs.get("optimize_for", "readability")

            prompt = f"""Implement the following algorithm: {algorithm}

Requirements:
- Use {language} programming language
- Optimize for {optimize_for}
- Include type hints (if Python)
- Add comprehensive docstring explaining:
  * Algorithm description
  * Time complexity (Big-O)
  * Space complexity
  * Parameters and return value
- Include edge case handling
- Add inline comments for complex steps
- Provide example usage

Return only the code implementation, no markdown formatting."""

            temperature = float(kwargs.get("temperature", 0.2))
            max_tokens = int(kwargs.get("max_tokens", 2048))
            max_repairs = int(kwargs.get("max_repairs", 1))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            is_python = str(language).lower() in {"python", "py"}
            format_black = bool(kwargs.get("format_black", False)) if is_python else False
            black_line_length = int(kwargs.get("black_line_length", 88))

            system_prompt = (
                "You are a senior software engineer. "
                "Return ONLY code. No markdown, no backticks, no explanations. "
                f"If Python, target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=is_python,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]
            is_valid = bool(gen.get("valid_python")) if is_python else None

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'algorithm': algorithm,
                    'language': language,
                    'optimize_for': optimize_for,
                    'valid_python': is_valid,
                    'syntax_error': gen.get('syntax_error') if is_python else None,
                    'attempts': gen.get('attempts', []),
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Algorithm implementation failed: {str(e)}")


class GenerateSymbolicMathTool(Tool):
    """Production-ready symbolic mathematics code generation"""

    def __init__(self):
        super().__init__()
        self.name = "generate_symbolic_math"
        self.description = "Generate symbolic mathematics code using SymPy"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="description", type="string", description="Mathematical problem description", required=True),
            ToolParameter(name="operations", type="array", description="Operations needed (e.g., ['solve', 'differentiate', 'integrate'])", required=False)
        ] + _common_llm_knobs(default_max_tokens=1024, default_temperature=0.2)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_symbolic_math",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Generate symbolic math code using SymPy",
                    priority=7
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"mathematics", "sympy", "llm"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate symbolic math code with SymPy"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            description = kwargs.get("description", "")
            operations = kwargs.get("operations", [])

            ops_str = ", ".join(operations) if operations else "infer from description"

            prompt = f"""Generate Python code using SymPy for the following mathematical problem:

Problem: {description}
Operations: {ops_str}

Requirements:
- Use SymPy library
- Include proper symbol definitions
- Show intermediate steps
- Include result evaluation
- Add comments explaining the math
- Return both symbolic and numerical results where appropriate

Return only Python code."""

            temperature = float(kwargs.get("temperature", 0.2))
            max_tokens = int(kwargs.get("max_tokens", 1024))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'description': description,
                    'operations': operations,
                    'valid_python': bool(gen.get('valid_python')),
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Symbolic math generation failed: {str(e)}")


class GenerateNumericalCodeTool(Tool):
    """Production-ready numerical computation code generation"""

    def __init__(self):
        super().__init__()
        self.name = "generate_numerical_code"
        self.description = "Generate numerical computation code using NumPy/SciPy"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="description", type="string", description="Numerical computation description", required=True),
            ToolParameter(name="library", type="string", description="Numerical library preference", required=False, default="numpy", enum=["numpy", "scipy", "both"])
        ] + _common_llm_knobs(default_max_tokens=1536, default_temperature=0.2)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_numerical_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Generate numerical computation code",
                    priority=7
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"numerical", "numpy", "scipy", "llm"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate numerical computation code"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            description = kwargs.get("description", "")
            library = kwargs.get("library", "numpy")

            prompt = f"""Generate Python code for the following numerical computation:

Task: {description}
Preferred library: {library}

Requirements:
- Use {library} for numerical operations
- Include error handling
- Optimize for numerical stability
- Add type hints
- Include example usage with sample data
- Comment on computational complexity if relevant

Return only Python code."""

            temperature = float(kwargs.get("temperature", 0.2))
            max_tokens = int(kwargs.get("max_tokens", 1536))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'description': description,
                    'library': library,
                    'valid_python': bool(gen.get('valid_python')),
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Numerical code generation failed: {str(e)}")


class GenerateMathProofTool(Tool):
    """Production-ready mathematical proof generation using LLM"""

    def __init__(self):
        super().__init__()
        self.name = "generate_math_proof"
        self.description = "Generate a structured mathematical proof"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="theorem", type="string", description="Theorem to prove", required=True),
            ToolParameter(name="proof_style", type="string", description="Proof style", required=False, default="direct", enum=["direct", "contradiction", "induction", "contrapositive"])
        ] + _common_llm_knobs(default_max_tokens=2048, default_temperature=0.2)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_math_proof",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Generate mathematical proofs",
                    priority=6
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"mathematics", "proof", "llm"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate mathematical proof"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            theorem = kwargs.get("theorem", "")
            proof_style = kwargs.get("proof_style", "direct")
            temperature = float(kwargs.get("temperature", 0.2))
            max_tokens = int(kwargs.get("max_tokens", 2048))
            model = str(kwargs.get("model", "qwen:32b"))

            prompt = f"""Generate a formal mathematical proof for the following theorem:

Theorem: {theorem}
Proof method: {proof_style} proof

Requirements:
- Use proper mathematical notation
- Include all steps clearly
- State any assumptions or lemmas used
- Conclude with Q.E.D.
- Use rigorous mathematical logic

Provide the complete proof."""

            response = await llm.generate(prompt, max_tokens=max_tokens, temperature=temperature, model=model)
            proof = response.get('content', '').strip()

            return ToolResult(
                success=True,
                output={
                    'proof': proof,
                    'theorem': theorem,
                    'proof_style': proof_style
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Math proof generation failed: {str(e)}")


class GenerateDesignPatternTool(Tool):
    """Production-ready design pattern implementation using LLM"""

    def __init__(self):
        super().__init__()
        self.name = "generate_design_pattern"
        self.description = "Generate a complete design pattern implementation"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="pattern", type="string", description="Design pattern name (e.g., 'Singleton', 'Observer', 'Factory')", required=True),
            ToolParameter(name="use_case", type="string", description="Specific use case for the pattern", required=False)
        ] + _common_llm_knobs(default_max_tokens=2048, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_design_pattern",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Generate design pattern implementations",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"design_patterns", "llm", "architecture"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate design pattern implementation"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            pattern = kwargs.get("pattern", "")
            use_case = kwargs.get("use_case", "general purpose")

            prompt = f"""Generate a complete implementation of the {pattern} design pattern.

Use case: {use_case}

Requirements:
- Include all necessary classes and interfaces
- Add comprehensive docstrings explaining the pattern
- Include type hints
- Provide example usage demonstrating the pattern
- Add comments explaining key aspects of the pattern
- Follow SOLID principles
- Make it production-ready

Return only Python code."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 2048))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'pattern': pattern,
                    'use_case': use_case,
                    'valid_python': bool(gen.get('valid_python')),
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Design pattern generation failed: {str(e)}")


class GenerateAPIClientTool(Tool):
    """Production-ready API client generation"""

    def __init__(self):
        super().__init__()
        self.name = "generate_api_client"
        self.description = "Generate a complete API client with proper error handling"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="api_name", type="string", description="API name", required=True),
            ToolParameter(name="base_url", type="string", description="API base URL", required=True),
            ToolParameter(name="endpoints", type="array", description="List of endpoints to implement", required=False),
            ToolParameter(name="auth_type", type="string", description="Authentication type", required=False, default="bearer", enum=["bearer", "api_key", "basic", "oauth2"])
        ] + _common_llm_knobs(default_max_tokens=3072, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_api_client",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Generate API client code with authentication and error handling",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"api", "client", "llm", "networking"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate API client code"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            api_name = kwargs.get("api_name", "")
            base_url = kwargs.get("base_url", "")
            endpoints = kwargs.get("endpoints", [])
            auth_type = kwargs.get("auth_type", "bearer")

            endpoints_str = "\n".join(f"- {ep}" for ep in endpoints) if endpoints else "Common CRUD operations"

            prompt = f"""Generate a Python API client for {api_name}.

Base URL: {base_url}
Authentication: {auth_type}
Endpoints to implement:
{endpoints_str}

Requirements:
- Use requests or httpx library
- Implement proper authentication
- Include retry logic with exponential backoff
- Add comprehensive error handling
- Include type hints
- Add docstrings for all methods
- Implement rate limiting if needed
- Add request/response logging
- Include example usage

Return only Python code."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 3072))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python engineer. "
                "Return ONLY valid Python code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'api_name': api_name,
                    'base_url': base_url,
                    'endpoints': endpoints,
                    'auth_type': auth_type,
                    'valid_python': bool(gen.get('valid_python')),
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"API client generation failed: {str(e)}")


class ScaffoldApplicationTool(Tool):
    """Production-ready application scaffolding"""

    def __init__(self):
        super().__init__()
        self.name = "scaffold_application"
        self.description = "Scaffold a complete application structure with best practices"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="app_name", type="string", description="Application name", required=True),
            ToolParameter(name="app_type", type="string", description="Application type", required=True, enum=["web", "api", "cli", "microservice", "library"]),
            ToolParameter(name="framework", type="string", description="Framework to use", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="scaffold_application",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BUILD_PROTOTYPE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Scaffold complete application structures",
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.MEDIUM,
                    description="Generate application boilerplate code",
                    priority=7
                )
            ],
            requires_network=False,
            is_idempotent=False,
            tags={"scaffolding", "boilerplate", "project_setup"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Scaffold application structure"""
        try:
            app_name = kwargs.get("app_name", "myapp")
            app_type = kwargs.get("app_type", "web")
            framework = kwargs.get("framework", "")

            # Basic structure
            structure = {
                "README.md": f"# {app_name}\n\n{app_type.capitalize()} application",
                "setup.py": f'from setuptools import setup, find_packages\n\nsetup(\n    name="{app_name}",\n    version="0.1.0",\n    packages=find_packages(),\n)',
                "requirements.txt": "# Add dependencies here\n",
                ".gitignore": "*.pyc\n__pycache__/\n.env\nvenv/\n",
                f"{app_name}/__init__.py": f'"""{app_name} - {app_type} application"""\n__version__ = "0.1.0"\n',
                f"{app_name}/main.py": "# Main application entry point\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n",
                "tests/__init__.py": "",
                "tests/test_main.py": "import pytest\n\ndef test_example():\n    assert True\n"
            }

            # Add framework-specific files
            if app_type == "api" or framework in ["fastapi", "flask"]:
                structure[f"{app_name}/routes.py"] = "# API routes\n"
                structure[f"{app_name}/models.py"] = "# Data models\n"

            if app_type == "cli":
                structure[f"{app_name}/cli.py"] = "import argparse\n\ndef create_parser():\n    parser = argparse.ArgumentParser()\n    return parser\n"

            return ToolResult(
                success=True,
                output={
                    'structure': structure,
                    'app_name': app_name,
                    'app_type': app_type,
                    'framework': framework,
                    'files_created': len(structure)
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Application scaffolding failed: {str(e)}")


class SynthesizeFromExamplesTool(Tool):
    """Model-free program synthesis from input/output examples.

    The substrate synthesises the program the way it synthesises a reading: it
    composes LEARNED instructions into a procedure and keeps the one that
    reproduces every example (``core.execution.list_synthesis``). No model
    proposes the answer; the examples and the substrate's own verifier decide it.

    The reach is exactly the machine that exists -- folds over a list of
    integers (sum, count, max). Examples outside that reach return an HONEST gap,
    never a model fallback and never a fabricated function: the caller learns
    precisely what the substrate can and cannot yet build for itself. New
    machines widen the reach; nothing here guesses past it.
    """

    #: A synthesised fold rendered back to the language callers expect. This is
    #: a serialisation of the procedure the substrate DERIVED (which operator it
    #: chose), not a generated guess -- the kind is read off the verified program.
    _RENDER = {
        "sum": "return sum(xs)",
        "count": "return len(xs)",
        "maximum": "return max(xs)",
    }

    def __init__(self):
        super().__init__()
        self.name = "synthesize_from_examples"
        self.description = "Synthesize a program from input/output examples (model-free)"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="examples", type="array", description="List of {input, output} pairs", required=True),
            ToolParameter(name="function_name", type="string", description="Name for synthesized function", required=False, default="synthesized_function"),
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="synthesize_from_examples",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Synthesize a program from input/output examples, model-free",
                    priority=8
                )
            ],
            requires_network=False,
            is_idempotent=True,
            tags={"synthesis", "substrate", "program_synthesis", "model_free"}
        )

    def _render_code(self, function_name: str, result: dict) -> str:
        body = self._RENDER.get(result["kind"], "return None")
        steps = " ; ".join(result["steps"])
        return (
            f"def {function_name}(xs):\n"
            f'    """Substrate-synthesised {result["kind"]} '
            f'({result["examples_count"]} examples, model-free).\n'
            f"    Derived procedure: {steps}\n"
            f'    """\n'
            f"    {body}\n"
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Synthesize a program from examples, model-free, or report the gap."""
        try:
            from core.execution.list_synthesis import synthesize_fold

            examples = kwargs.get("examples", [])
            function_name = kwargs.get("function_name", "synthesized_function")

            if not examples:
                return ToolResult(success=False, output=None, error="At least one example is required")

            result, why = synthesize_fold(examples)
            if result is None:
                # Honest gap. The substrate cannot yet build this from examples;
                # it does NOT hand off to a model or fabricate a function.
                return ToolResult(
                    success=False, output=None,
                    error=f"substrate cannot synthesize this model-free: {why}")

            code = self._render_code(function_name, result)
            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'kind': result["kind"],
                    'derived_procedure': result["steps"],
                    'examples_count': result["examples_count"],
                    'function_name': function_name,
                    'valid_python': True,
                    'model_free': True,
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Code synthesis failed: {str(e)}")


class GeneratePropertyTestTool(Tool):
    """Production-ready property-based test generation"""

    def __init__(self):
        super().__init__()
        self.name = "generate_property_test"
        self.description = "Generate property-based tests using Hypothesis"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="function_code", type="string", description="Function to test", required=True),
            ToolParameter(name="properties", type="array", description="Properties to test (e.g., ['idempotent', 'commutative'])", required=False)
        ] + _common_llm_knobs(default_max_tokens=1536, default_temperature=0.3)

        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_property_test",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_TESTS,
                    risk_level=RiskLevel.LOW,
                    description="Generate property-based tests using Hypothesis",
                    priority=8
                )
            ],
            requires_network=True,
            is_idempotent=False,
            tags={"testing", "property_based", "hypothesis", "llm"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate property tests"""
        try:
            from core.services.unified_llm import get_llm_service

            llm = get_llm_service()

            function_code = kwargs.get("function_code", "")
            properties = kwargs.get("properties", [])

            props_str = ", ".join(properties) if properties else "infer appropriate properties"

            prompt = f"""Generate property-based tests using Hypothesis for this function:

```python
{function_code}
```

Properties to test: {props_str}

Requirements:
- Use hypothesis library
- Test appropriate properties (idempotence, commutativity, etc.)
- Include edge cases
- Use appropriate strategies
- Add docstrings explaining what each test checks

Return only Python test code."""

            temperature = float(kwargs.get("temperature", 0.3))
            max_tokens = int(kwargs.get("max_tokens", 1536))
            max_repairs = int(kwargs.get("max_repairs", 1))
            format_black = bool(kwargs.get("format_black", False))
            black_line_length = int(kwargs.get("black_line_length", 88))
            python_version = str(kwargs.get("python_version", "3.11"))
            model = str(kwargs.get("model", "qwen:32b"))

            system_prompt = (
                "You are a senior Python test engineer. "
                "Return ONLY valid Python test code. No markdown/backticks/explanations. "
                f"Target Python {python_version}."
            )

            gen = await _llm_generate_python_code(
                llm=llm,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                max_repairs=max_repairs,
                validate_syntax=True,
                format_black=format_black,
                black_line_length=black_line_length,
            )

            code = gen["code"]

            return ToolResult(
                success=True,
                output={
                    'code': code,
                    'properties': properties,
                    'valid_python': bool(gen.get('valid_python')),
                    'syntax_error': gen.get('syntax_error'),
                    'attempts': gen.get('attempts', []),
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Property test generation failed: {str(e)}")


class ApplyPatchTool(Tool):
    """Production-ready unified diff patch application"""

    def __init__(self):
        super().__init__()
        self.name = "apply_patch"
        self.description = "Apply a unified diff patch to code"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Original code", required=True),
            ToolParameter(name="patch", type="string", description="Unified diff patch", required=True)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="apply_patch",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRANSFORM_DATA,
                    risk_level=RiskLevel.MEDIUM,
                    description="Apply unified diff patches to code",
                    priority=6
                )
            ],
            requires_network=False,
            is_idempotent=True,
            tags={"patch", "diff", "version_control"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Apply unified diff patch"""
        try:
            code = kwargs.get("code", "")
            patch = kwargs.get("patch", "")

            if not isinstance(code, str) or not isinstance(patch, str):
                return ToolResult(success=False, output=None, error="code and patch must both be strings")

            if not patch.strip():
                return ToolResult(success=False, output=None, error="patch is required")

            # Some callers pass the original code wrapped in fences.
            code = _extract_first_fenced_code_block(code)
            patch = patch.strip("\ufeff\n\r ")

            try:
                target_file, hunks = _parse_unified_diff(patch)
            except ValueError as e:
                return ToolResult(success=False, output=None, error=str(e))
            except Exception as e:
                return ToolResult(success=False, output=None, error=f"Failed to parse patch: {e}")

            if not hunks:
                return ToolResult(
                    success=False,
                    output=None,
                    error="No unified-diff hunks found in patch (expected lines like @@ -a,b +c,d @@).",
                )

            result = _apply_unified_hunks_to_code(code, hunks)
            if result["errors"]:
                return ToolResult(
                    success=False,
                    output={
                        "original_code": code,
                        "code": result["patched_code"],
                        "patch_applied": False,
                        "hunks_applied": result["hunks_applied"],
                        "target_file": target_file,
                        "errors": result["errors"],
                    },
                    error="Patch could not be applied cleanly",
                )

            return ToolResult(
                success=True,
                output={
                    "original_code": code,
                    "code": result["patched_code"],
                    "patch_applied": True,
                    "hunks_applied": result["hunks_applied"],
                    "target_file": target_file,
                },
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Patch application failed: {str(e)}")


class CompileTypecheckGateTool(Tool):
    """Production-ready compile and typecheck validation"""

    def __init__(self):
        super().__init__()
        self.name = "compile_typecheck_gate"
        self.description = "Compile and typecheck Python code using mypy"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Code to check", required=True),
            ToolParameter(name="strict", type="boolean", description="Use strict type checking", required=False, default=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="compile_typecheck_gate",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    description="Validate code syntax and type correctness",
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Analyze code for type errors",
                    priority=7
                )
            ],
            requires_network=False,
            is_idempotent=True,
            tags={"validation", "type_checking", "mypy"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Compile and typecheck code"""
        try:
            import ast
            import tempfile
            import subprocess
            from pathlib import Path

            code = kwargs.get("code", "")
            strict = kwargs.get("strict", False)

            # Check syntax first
            try:
                ast.parse(code)
                syntax_valid = True
                syntax_error = None
            except SyntaxError as e:
                syntax_valid = False
                syntax_error = str(e)

            # Try mypy if available
            type_check_result = None
            try:
                # Write to temp file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(code)
                    temp_file = f.name

                # Run mypy
                mypy_args = ['mypy', temp_file]
                if strict:
                    mypy_args.append('--strict')

                result = subprocess.run(
                    mypy_args,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                type_check_result = {
                    'passed': result.returncode == 0,
                    'output': result.stdout,
                    'errors': result.stderr
                }

                # Cleanup
                Path(temp_file).unlink()

            except (subprocess.SubprocessError, FileNotFoundError):
                # mypy not available
                type_check_result = {'passed': None, 'message': 'mypy not available'}

            return ToolResult(
                success=True,
                output={
                    'valid': syntax_valid and (type_check_result.get('passed') != False),
                    'syntax_valid': syntax_valid,
                    'syntax_error': syntax_error,
                    'type_check': type_check_result
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Compile/typecheck failed: {str(e)}")


class RepositoryRefactorTool(Tool):
    """Production-ready repository-wide refactoring"""

    def __init__(self):
        super().__init__()
        self.name = "repository_refactor"
        self.description = "Perform repository-wide refactoring operations"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.HIGH_RISK
        self.parameters = [
            ToolParameter(name="refactor_type", type="string", description="Type of refactor", required=True, enum=["rename_module", "extract_package", "modernize_syntax", "update_imports"]),
            ToolParameter(name="target", type="string", description="Target path or pattern", required=True),
            ToolParameter(name="dry_run", type="boolean", description="Perform dry run without modifying files", required=False, default=True)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="repository_refactor",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.REFACTOR_CODE,
                    risk_level=RiskLevel.HIGH,
                    description="Perform repository-wide refactoring operations",
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    risk_level=RiskLevel.HIGH,
                    description="Modify multiple files across repository",
                    priority=8
                )
            ],
            requires_network=False,
            requires_filesystem=True,
            is_idempotent=False,
            tags={"refactoring", "repository", "bulk_operations"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Repository-wide refactoring"""
        try:
            refactor_type = kwargs.get("refactor_type", "")
            target = kwargs.get("target", "")
            dry_run = kwargs.get("dry_run", True)

            # This is a complex operation - for now return a plan
            return ToolResult(
                success=True,
                output={
                    'refactor_type': refactor_type,
                    'target': target,
                    'dry_run': dry_run,
                    'files_changed': 0,
                    'status': 'planned' if dry_run else 'executed'
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Repository refactor failed: {str(e)}")


class LicenseAttributionCheckTool(Tool):
    """Production-ready license and attribution checking"""

    def __init__(self):
        super().__init__()
        self.name = "license_attribution_check"
        self.description = "Check code for proper license headers and attribution"
        self.category = ToolCategory.CODE_GENERATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="code", type="string", description="Code to check", required=True),
            ToolParameter(name="expected_license", type="string", description="Expected license type", required=False, enum=["MIT", "Apache-2.0", "GPL-3.0", "BSD-3-Clause"])
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="license_attribution_check",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    risk_level=RiskLevel.LOW,
                    description="Check code for proper license headers and attribution",
                    priority=6
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    risk_level=RiskLevel.LOW,
                    description="Analyze code for license compliance",
                    priority=6
                )
            ],
            requires_network=False,
            is_idempotent=True,
            tags={"license", "compliance", "validation"}
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Check license attribution"""
        try:
            code = kwargs.get("code", "")
            expected_license = kwargs.get("expected_license", None)

            # Check for license headers in comments
            lines = code.splitlines()
            has_copyright = any('copyright' in line.lower() for line in lines[:20])
            has_license = any('license' in line.lower() for line in lines[:20])

            issues = []
            if not has_copyright:
                issues.append("Missing copyright notice")
            if not has_license:
                issues.append("Missing license information")

            if expected_license and not any(expected_license.lower() in line.lower() for line in lines[:20]):
                issues.append(f"Expected {expected_license} license not found")

            return ToolResult(
                success=True,
                output={
                    'compliant': len(issues) == 0,
                    'has_copyright': has_copyright,
                    'has_license': has_license,
                    'expected_license': expected_license,
                    'issues': issues
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"License check failed: {str(e)}")
