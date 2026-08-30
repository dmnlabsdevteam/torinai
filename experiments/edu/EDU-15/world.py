#!/usr/bin/env python3
"""The world that supplies truth: execution, not assertion.

The teacher may say `print(4 + 3)` produces 7. That is instructional material.
Only running it establishes that it does. Every claim in this experiment that
something WORKS comes from here.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SANDBOX_IMAGE = "python:3.11-slim"   # lesson snippets need no dependencies


@dataclass
class Execution:
    """What actually happened when code ran."""

    ran: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    error: Optional[str] = None


@dataclass
class Grade:
    """Behavioural grade for one task. Source text is never compared."""

    task_id: str
    passed: bool
    cases_passed: int
    cases_total: int
    failures: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def summary(self) -> str:
        return f"{self.cases_passed}/{self.cases_total}"


def execute(code: str, timeout: int = 20) -> Execution:
    """Run a snippet in an isolated container and report what it did."""
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "snippet.py"
        path.write_text(code, encoding="utf-8")
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", "--network", "none",
                 "--cpus", "0.5", "--memory", "256m",
                 "-v", f"{path}:/snippet.py:ro",
                 SANDBOX_IMAGE, "python", "/snippet.py"],
                capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return Execution(ran=False, error=f"timed out after {timeout}s")
        except Exception as error:                       # docker absent, etc.
            return Execution(ran=False, error=f"{type(error).__name__}: {error}")
        return Execution(
            ran=True,
            stdout=result.stdout.decode(errors="replace"),
            stderr=result.stderr.decode(errors="replace"),
            exit_code=result.returncode,
        )


def grade(task, source: str, timeout: int = 30) -> Grade:
    """Run the hidden tests against the submitted function.

    GRADES BEHAVIOUR. The harness builds a driver that imports nothing, defines
    the candidate, calls it with each hidden input and compares the result. How
    the student wrote it -- `total += x` or `total = total + x` -- cannot affect
    the outcome, which is the point: this measures programming competence, not
    imitation of the teacher's syntax.
    """
    cases = [{"args": list(args), "expected": expected} for args, expected in task.tests]
    driver = (
        f"{source}\n\n"
        "import json\n"
        f"__cases = json.loads({json.dumps(json.dumps(cases))})\n"
        "__results = []\n"
        "for __c in __cases:\n"
        "    try:\n"
        f"        __got = {task.entry}(*__c['args'])\n"
        "        __results.append({'ok': __got == __c['expected'],\n"
        "                          'got': repr(__got), 'expected': repr(__c['expected']),\n"
        "                          'args': repr(__c['args'])})\n"
        "    except Exception as __e:\n"
        "        __results.append({'ok': False, 'got': f'{type(__e).__name__}: {__e}',\n"
        "                          'expected': repr(__c['expected']), 'args': repr(__c['args'])})\n"
        "print('__GRADE__' + json.dumps(__results))\n"
    )

    run = execute(driver, timeout=timeout)
    if not run.ran:
        return Grade(task.task_id, False, 0, len(cases), error=run.error)

    marker = "__GRADE__"
    if marker not in run.stdout:
        detail = (run.stderr or run.stdout).strip().splitlines()
        return Grade(task.task_id, False, 0, len(cases),
                     error=detail[-1][:200] if detail else "no result produced")

    results = json.loads(run.stdout.split(marker, 1)[1].strip().splitlines()[0])
    passed = sum(1 for r in results if r["ok"])
    failures = [f"{task.entry}({r['args']}) -> {r['got']}, expected {r['expected']}"
                for r in results if not r["ok"]]
    return Grade(task.task_id, passed == len(cases), passed, len(cases), failures)


def available() -> Tuple[bool, str]:
    """Whether the world can supply truth at all."""
    run = execute("print('ok')", timeout=30)
    if run.ran and run.stdout.strip() == "ok":
        return True, "sandbox executes"
    return False, run.error or f"exit={run.exit_code} stderr={run.stderr[:120]}"
