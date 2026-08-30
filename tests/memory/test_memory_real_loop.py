#!/usr/bin/env python3
"""Memory against the REAL system: store → reason() → recall into cognition.

Not a CRUD smoke test. This drives the actual reasoning entry point
(`NeuralSymbolicBridge.reason`) and asserts that a memory written to the store
is (a) retrievable, and (b) INJECTED INTO COGNITION on a later, related,
above-floor query — i.e. it lands in `request.context` where the eleven kinds of
thinking read their premises. Injection runs before the model, so the cognition
assertion holds whether or not the LLM produces an answer.

Run inside the sandbox against the real DB + llama-server:

    docker run --rm --add-host=host.docker.internal:host-gateway \
      -e POSTGRES_HOST=host.docker.internal \
      -e LLM_SERVER_URL=http://host.docker.internal:8099 \
      -e PYTHONPATH=/repo -w /repo \
      -v "$PWD":/repo:ro -v "$HOME/.cache":/root/.cache \
      torinai-sandbox:latest python tests/memory/test_memory_real_loop.py

Exit 0 = all assertions held. Non-zero = a real failure, printed.
"""

import asyncio
import hashlib
import sys
import time


def _tok(seed: str) -> str:
    return "zrl" + hashlib.sha1(seed.encode()).hexdigest()[:8]


async def _cleanup(agent, memory_id: str) -> None:
    try:
        store = getattr(agent, "postgres_storage", None)
        if store and hasattr(store, "delete_memory"):
            await store.delete_memory(memory_id)
    except Exception:
        pass  # best effort; the row is harmless if it lingers


async def run() -> int:
    from core.memory import get_memory_agent
    from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest
    from core.memory.utils.memory_injection_policy import get_memory_injection_policy

    results: list[tuple[bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((ok, name))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))

    agent = await get_memory_agent()
    await agent.initialize()
    bridge = get_neural_bridge()
    if hasattr(bridge, "initialize"):
        await bridge.initialize()

    # ISOLATION: drop rows left by earlier runs so ranking is deterministic and
    # this run's memory is the unambiguous top match for its own scenario.
    try:
        _okp, prior = await agent.search_memories(
            query="orbital telemetry buffer downlink scheduler ring allocator", limit=25)
        for r in (prior or []):
            if "real_loop_test" in (getattr(r, "tags", None) or []):
                await agent.postgres_storage.delete_memory(r.memory_id)
    except Exception:
        pass

    tok = _tok(str(time.time()))
    # A UNIQUE scenario (distinctive nouns + a per-run token) so nothing already
    # in the store competes with it semantically -- the memory that reaches
    # cognition must be THIS one, not a neighbour on a well-trodden topic.
    claim = (f"the {tok} orbital telemetry buffer overflows when the {tok} "
             f"downlink scheduler starves the ring allocator and the flush never runs")

    # ---- 1. STORE ----------------------------------------------------------
    ok, mem_id = await agent.store_memory(
        content=claim, tags=["reasoning", "real_loop_test"], importance_score=0.9)
    check("store_memory persists the conclusion", bool(ok) and bool(mem_id),
          f"id={mem_id}")

    # ---- 2. RETRIEVE (wait until embedded/searchable) ----------------------
    # Above the injection COMPLEXITY_FLOOR (0.35) by construction — the unique
    # nouns keep it ranking to THIS memory, the hint words (why/how/root cause/
    # investigate) and clauses carry the complexity score over the floor — so a
    # 0-injection here is a real failure, not the policy correctly declining.
    probe_q = (f"why does the {tok} orbital telemetry buffer keep overflowing, "
               f"and how does the {tok} downlink scheduler starve the ring "
               f"allocator, and what is the root cause I should investigate to fix it")
    found = None
    sim = 0.0
    for i in range(20):
        _ok, res = await agent.search_memories(query=probe_q, limit=5)
        hit = next((r for r in (res or []) if getattr(r, "memory_id", None) == mem_id), None)
        if hit is not None:
            found = hit
            sim = float(getattr(hit, "similarity_score", 0.0) or 0.0)
            break
        await asyncio.sleep(0.5)
    check("stored memory is retrievable by paraphrase", found is not None,
          f"similarity={sim:.3f} after {i * 0.5:.1f}s")

    # ---- 3. POLICY warrants injection for an above-floor query -------------
    # The cognition assertion is only meaningful if the policy admits this query;
    # a below-floor query correctly gets no memory. Assert the gate is open here.
    plan = get_memory_injection_policy().decide(query=probe_q)
    warranted = bool(getattr(plan, "enabled", False))
    complexity = getattr(plan, "complexity", None)
    check("injection policy warrants this query (>= floor)", warranted,
          f"complexity={complexity} reasons={getattr(plan, 'reason_codes', None)}")

    # ---- 4. REACHES COGNITION via the real reason() loop -------------------
    # Injection prepends recalled claims into request.context before any model
    # runs. Assert the distinctive token lands there — memory reached cognition.
    req = ReasoningRequest(query=probe_q, cached_memories=None)
    await bridge.reason(req)
    ctx = req.context or []
    reached = any(tok in str(c) for c in ctx)
    check("memory reached cognition (injected into reason() context)", reached,
          f"context items={len(ctx)}; first={str(ctx[0])[:80] if ctx else '—'}")

    # ---- 5. AND a routine query is correctly DECLINED (the other half) ------
    # A trivial request must not drag memory into cognition. This is the skip
    # behaviour the retired `test_query_skip.py` only printed; asserted here.
    skip_plan = get_memory_injection_policy().decide(query="list files")
    check("routine query is declined (no injection below floor)",
          not bool(getattr(skip_plan, "enabled", True)),
          f"complexity={getattr(skip_plan, 'complexity', None)} "
          f"reasons={getattr(skip_plan, 'reason_codes', None)}")

    await _cleanup(agent, mem_id)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n  {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except Exception as error:
        import traceback
        traceback.print_exc()
        print(f"\n  ERROR: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
