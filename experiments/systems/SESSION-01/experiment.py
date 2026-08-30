#!/usr/bin/env python3
"""SESSION-01 — does proposal quality decay across repeated calls?

An unresolved observation from EDU-08: five model-teacher trials run inside one
process converged 1/5, while five run as separate processes converged 3/5, and
one in-process trial proposed nothing at all.

This experiment does not explain that. It LOCALIZES it. The candidate causes --
model sampling, llama-server state, conversation state, KV-cache behaviour,
request construction, the wrapper -- are not distinguishable from the EDU-08
data, and guessing between them would attach a cause to a correlation.

Three conditions, everything else held identical (prompt, temperature,
structured-extraction path, world, version space, candidate budget):

    A  PERSISTENT   one process, one service instance, N calls in sequence
    B  FRESH_PROC   a new Python process per call
    C  FRESH_STATE  one process, a NEW service instance per call

A vs B isolates "anything that persists in this process" from "anything that
persists in the server". B vs C isolates the wrapper's own state from the
process's.

The measurement is proposal quality AGAINST CALL INDEX. If quality falls with
position only in A, there is a session effect to chase. If it falls in all
three, the proposer is simply noisy and EDU-08's spread was sampling.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.learning.llm_teacher import LLMTeacher  # noqa: E402
from core.learning.rule_induction import (  # noqa: E402
    CandidateRule, Fact, RuleEffects)

CALLS = int(os.environ.get("SESSION01_CALLS", "10"))
ACTION = Fact("TRANSFER", ("?X", "?A", "?B"))
PRE = {"LOCATED": Fact("LOCATED", ("?X", "?A")),
       "ROUTE": Fact("ROUTE", ("?A", "?B")),
       "AVAILABLE": Fact("AVAILABLE", ("?B",))}
EFFECTS = RuleEffects(add=frozenset([Fact("LOCATED", ("?X", "?B"))]),
                      delete=frozenset([Fact("LOCATED", ("?X", "?A"))]))
SPACE = [CandidateRule(body=frozenset([ACTION] + [PRE[n] for n in chosen]),
                       effects=EFFECTS, action=ACTION)
         for size in range(len(PRE) + 1)
         for chosen in combinations(sorted(PRE), size)]

PREDICATES = ("LOCATED", "ROUTE", "AVAILABLE", "TRANSFER")
CONSTANTS = ("p", "DOCK", "AISLE", "VAULT")


async def one_call(teacher) -> dict:
    """One proposal round. Identical every time."""
    session = await teacher.propose(SPACE, PREDICATES, CONSTANTS, count=4)
    return {"proposed": session.proposed,
            "admitted": len(session.admitted),
            "unparseable": session.unparseable}


async def persistent(calls: int) -> list:
    """A: one process, one service instance, calls in sequence."""
    from core.services.unified_llm import get_llm_service
    teacher = LLMTeacher(llm_service=get_llm_service())
    return [await one_call(teacher) for _ in range(calls)]


async def fresh_state(calls: int) -> list:
    """C: one process, a new service instance per call."""
    from core.services.unified_llm import UnifiedLLMService
    out = []
    for _ in range(calls):
        out.append(await one_call(LLMTeacher(llm_service=UnifiedLLMService())))
    return out


def fresh_process(calls: int) -> list:
    """B: a new interpreter per call."""
    here = Path(__file__).resolve()
    out = []
    for _ in range(calls):
        proc = subprocess.run(
            [sys.executable, str(here), "--single"],
            capture_output=True, text=True, cwd=str(here.parents[3]))
        line = next((l for l in proc.stdout.splitlines() if l.startswith("{")), None)
        out.append(json.loads(line) if line else
                   {"proposed": 0, "admitted": 0, "unparseable": 0, "error": "no output"})
    return out


def describe(name: str, results: list) -> dict:
    admitted = [r["admitted"] for r in results]
    first_half = admitted[: len(admitted) // 2] or [0]
    second_half = admitted[len(admitted) // 2:] or [0]
    return {
        "condition": name,
        "calls": len(results),
        "admitted_by_call": admitted,
        "total_admitted": sum(admitted),
        "zero_proposal_calls": sum(1 for r in results if r["proposed"] == 0),
        "mean_first_half": round(statistics.mean(first_half), 2),
        "mean_second_half": round(statistics.mean(second_half), 2),
        # Positive means later calls did WORSE.
        "decay": round(statistics.mean(first_half) - statistics.mean(second_half), 2),
    }


async def main() -> int:
    if "--single" in sys.argv:
        from core.services.unified_llm import get_llm_service
        result = await one_call(LLMTeacher(llm_service=get_llm_service()))
        print(json.dumps(result))
        return 0

    print(f"SESSION-01: {CALLS} identical proposal calls per condition\n")

    report = {}
    a = await persistent(CALLS)
    report["A_persistent"] = describe("A_persistent", a)
    print("A persistent :", report["A_persistent"]["admitted_by_call"])

    c = await fresh_state(CALLS)
    report["C_fresh_state"] = describe("C_fresh_state", c)
    print("C fresh state:", report["C_fresh_state"]["admitted_by_call"])

    b = fresh_process(CALLS)
    report["B_fresh_process"] = describe("B_fresh_process", b)
    print("B fresh proc :", report["B_fresh_process"]["admitted_by_call"])

    print("\n{:<16}{:>10}{:>12}{:>12}{:>8}".format(
        "condition", "admitted", "1st half", "2nd half", "decay"))
    for key in ("A_persistent", "B_fresh_process", "C_fresh_state"):
        d = report[key]
        print("{:<16}{:>10}{:>12}{:>12}{:>8}".format(
            key, d["total_admitted"], d["mean_first_half"],
            d["mean_second_half"], d["decay"]))

    decays = {k: report[k]["decay"] for k in report}
    only_persistent = (decays["A_persistent"] > 0.5
                       and decays["B_fresh_process"] <= 0.5
                       and decays["C_fresh_state"] <= 0.5)
    print("\nreading:")
    if only_persistent:
        print("  quality falls with call index ONLY when process and service "
              "persist -> a session-state effect to chase")
    elif all(v <= 0.5 for v in decays.values()):
        print("  no decay in any condition -> EDU-08's spread was sampling "
              "noise, not session state")
    else:
        print("  decay is not confined to the persistent condition -> not a "
              "session effect; look at the proposer or the server")

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "experiment": "SESSION-01",
        "question": ("does proposal quality decay across repeated calls, and if "
                     "so which layer retains the state"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "calls_per_condition": CALLS,
        "conditions": report,
        "decays": decays,
        "confined_to_persistent": only_persistent,
        "note": ("localizes only. Candidate causes -- sampling, server state, "
                 "conversation state, KV cache, request construction, wrapper "
                 "-- are not distinguished by this design beyond which layer "
                 "must persist for the effect to appear."),
    }, indent=2))
    print(f"\nmanifest -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
