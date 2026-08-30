"""The substrate's shell activity, surfaced in the dedicated terminal.

Every command the substrate runs was captured through a PIPE and returned as a
tool result, which reaches `logs/torin_main.log` and nothing else. The window
that started the run -- the one that owns every subprocess in the tree -- showed
no sign that a command had been executed at all. Watching the system work meant
tailing a file in a second window, which is exactly the split the dedicated
terminal exists to remove.

This is the one place that decides how an executed command is shown. Emitting
from each call site instead would put the truncation rule, the redaction rule
and the formatting in three places, and they would drift.

WHAT IS SHOWN IS WHAT RAN. The command is echoed verbatim, the exit code is the
real one, and output is never summarised -- only truncated, and only with an
explicit marker saying how much was withheld. An empty stream is reported as
empty rather than omitted, because "the command printed nothing" and "we did not
show you what it printed" are different facts.
"""
import os
import re
import shutil
import sys
from typing import Optional

#: Per-stream ceiling. A build log is not worth 40,000 lines in the terminal,
#: but the cut is always declared -- silent truncation would make a partial
#: reading look complete.
MAX_LINES = 40
MAX_CHARS = 4000

_ORANGE = "\033[38;5;208m"
_CYAN = "\033[38;5;51m"
_GREEN = "\033[38;5;46m"
_RED = "\033[38;5;196m"
_GRAY = "\033[38;5;240m"
_OFF = "\033[0m"

#: Values that must never reach the screen. The substrate runs commands that
#: carry credentials in argv; the terminal is shoulder-surfable and the scroll
#: buffer outlives the process.
_SECRET = re.compile(
    r"""(?ix)
    (
      (?:password|passwd|secret|token|api[_-]?key|access[_-]?key|
         auth|bearer|private[_-]?key)
      \s*[=:]\s*
    )
    (\S+)
    """
)


def enabled() -> bool:
    """Emit only when there is a dedicated terminal attached to emit to.

    TORIN_SHELL is set by TorinAI/.torinshell/.zshrc and inherited by the
    process `torin` starts, so it is a direct answer to "did this run come from
    the dedicated terminal". stdout is NOT consulted: `torin` pipes it through a
    colouriser, so isatty() is False even when a terminal is right there.
    """
    override = os.getenv("TORIN_COMMAND_ECHO")
    if override is not None:
        return override.strip().lower() in ("1", "true", "yes", "on")
    return os.getenv("TORIN_SHELL") == "1"


def _redact(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}***", text)


def _clip(text: str) -> tuple[str, Optional[str]]:
    """Return (shown, note). `note` states what was withheld, or None."""
    lines = text.splitlines()
    withheld = []

    if len(lines) > MAX_LINES:
        withheld.append(f"{len(lines) - MAX_LINES} more line(s)")
        lines = lines[:MAX_LINES]

    shown = "\n".join(lines)
    if len(shown) > MAX_CHARS:
        withheld.append(f"{len(shown) - MAX_CHARS} more character(s)")
        shown = shown[:MAX_CHARS]

    return shown, (" · ".join(withheld) if withheld else None)


def _stream(label: str, text: str, colour: str) -> None:
    if not text.strip():
        print(f"  {_GRAY}{label}: (empty){_OFF}", file=sys.stderr)
        return
    shown, note = _clip(_redact(text))
    print(f"  {colour}{label}{_OFF}", file=sys.stderr)
    for line in shown.splitlines():
        print(f"    {line}", file=sys.stderr)
    if note:
        print(f"    {_GRAY}… {note} withheld (full output is in the tool "
              f"result){_OFF}", file=sys.stderr)


def show(
    command: str,
    exit_code: Optional[int],
    stdout: str = "",
    stderr: str = "",
    duration_sec: Optional[float] = None,
    cwd: Optional[str] = None,
    tool: Optional[str] = None,
) -> None:
    """Print one executed command and its real result. Never raises.

    Emission is a side effect of reporting, so a failure here must not change
    what the caller returns: a broken terminal cannot be allowed to fail a
    command that actually succeeded.
    """
    if not enabled():
        return

    try:
        width = shutil.get_terminal_size((72, 24)).columns
        rule = "─" * max(24, min(width, 72))

        ok = exit_code == 0
        mark = f"{_GREEN}✓{_OFF}" if ok else f"{_RED}✗{_OFF}"
        code = "0" if ok else str(exit_code)

        meta = [f"exit {code}"]
        if duration_sec is not None:
            meta.append(f"{duration_sec:.2f}s")
        if tool:
            meta.append(tool)

        print(f"\n{_GRAY}{rule}{_OFF}", file=sys.stderr)
        print(f"{mark} {_ORANGE}${_OFF} {_redact(command)}", file=sys.stderr)
        if cwd:
            print(f"  {_GRAY}in {cwd}{_OFF}", file=sys.stderr)
        print(f"  {_GRAY}{' · '.join(meta)}{_OFF}", file=sys.stderr)

        _stream("stdout", stdout, _CYAN)
        if stderr.strip():
            _stream("stderr", stderr, _RED)
        print(f"{_GRAY}{rule}{_OFF}", file=sys.stderr)

    except Exception:
        # Reporting must never break execution.
        pass
