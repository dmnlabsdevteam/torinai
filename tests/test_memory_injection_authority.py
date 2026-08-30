#!/usr/bin/env python3
"""One relevance authority for memory injection.

The invariant:

    ONE policy decides whether and what memory enters cognition.
    MANY consumers decide only WHERE it goes.

Placement legitimately differs — task-start injection and reasoning-call
injection happen at different lifecycle points. Relevance must not.

Torin had THREE independent answers to "should prior context enter cognition":

  1. MemoryInjectionPolicy.decide()          consulted only by the coordinator
  2. MemoryInjector._should_search_memories() its own keyword/complexity gate
  3. GeneralPurposeExecutor task-start block  NO gate at all, hardcoded
                                              min_similarity=0.7, limit=3

They did not agree, and the disagreement was not theoretical — see
POSTGRES_PASSWORD_FINDING below. Keep that case permanently: it is the concrete
proof that three independent relevance decisions were untenable, and the
regression fixture for anyone tempted to add a fourth.

Run:  venv_torin/bin/python tests/test_memory_injection_authority.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory.utils.memory_injection_policy import (  # noqa: E402
    get_memory_injection_policy,
    _CONTEXT_MIN_RELEVANCE,
)

# The case that exposed the split. A real security finding, verbatim: the old
# executor path would have injected memory (it had no gate and always
# retrieved), the old injector heuristic said True, and the canonical policy —
# before task_execution was a recognised context — said False. Same query,
# three answers, decided by whichever path happened to reach it.
POSTGRES_PASSWORD_FINDING = (
    "[AUTHENTICATION:HIGH] Security-critical env var missing: POSTGRES_PASSWORD. "
    "Environment variable 'POSTGRES_PASSWORD' is not set; service may fall back "
    "to insecure defaults. Remediation: Set POSTGRES_PASSWORD in the .env file "
    "with a strong random value"
)

failures = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    policy = get_memory_injection_policy()

    print("\nONE AUTHORITY")
    plan_task = policy.decide(query=POSTGRES_PASSWORD_FINDING, context_type="task_execution")
    check(
        "task execution is a recognised production context",
        plan_task.enabled,
        f"reasons={plan_task.reason_codes}",
    )
    check(
        "the regression fixture is decided by policy, not by call path",
        "context:task_execution" in plan_task.reason_codes,
        "a decision must carry the reason it was made",
    )

    print("\nBEHAVIOURAL PARITY (unification must not move retrieval population)")
    check(
        "task_execution keeps the executor's historical 0.7 floor",
        plan_task.min_relevance == 0.7,
        f"min_relevance={plan_task.min_relevance}",
    )
    check(
        "other contexts keep their 0.5 floor",
        policy.decide(query="analyse the failure modes here", context_type="analysis").min_relevance == 0.5,
    )
    check(
        "the parity value is declared in one table, not inlined",
        _CONTEXT_MIN_RELEVANCE.get("task_execution") == 0.7,
    )

    print("\nTWO GATES STAY SEPARATE")
    check(
        "pre-retrieval (enabled) is not the same question as post-retrieval (min_relevance)",
        hasattr(plan_task, "enabled") and hasattr(plan_task, "min_relevance"),
        "'is memory useful here' vs 'is THIS memory relevant enough'",
    )

    print("\nA SKIP IS DISTINGUISHABLE FROM A MISS")
    empty = policy.decide(query="", context_type="task_execution")
    check(
        "declining to search states why",
        (not empty.enabled) and bool(empty.reason_codes),
        f"reasons={empty.reason_codes}",
    )
    trivial = policy.decide(query="list files", context_type="reasoning")
    check(
        "a routine request is declined on the reasoning path",
        not trivial.enabled,
        f"reasons={trivial.reason_codes}",
    )

    print("\nDEFERRED ON PURPOSE — task-start selectivity is a separate change")
    check(
        "task_execution is still unconditionally worthy (parity with the old executor)",
        policy.decide(query="list files", context_type="task_execution").enabled,
        "complexity is the wrong question; the real one is 'could prior "
        "experience materially alter this execution' — to be measured, not guessed",
    )

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all checks passed — one relevance authority, parity preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
