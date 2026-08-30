#!/usr/bin/env python3
"""The autonomous coordinator's reasoning entry, `reason_about()`, against the
real system — proving the coordinator reasons THROUGH the authority.

reason_about() is the method every autonomous path uses to reason. It must:
  - go through the authority (`neural_bridge.reason`), never around it;
  - return the authority's own verdict (verified / derived-by-kind);
  - record provenance route [reason_about, neural_bridge, ...].

This drives the REAL `AutonomousCoordinator.reason_about` code, bound to a
minimal object carrying a real, initialised neural bridge (store_memory is
stubbed — this verifies reasoning, not memory). Run in the sandbox against the
real DB + llama-server; the whole thing is model-free.
"""

import asyncio
import sys
import types


async def run() -> int:
    from core.model_policy import set_model_policy, ModelPolicy
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)  # always substrate-first

    from core.reasoning.neural_bridge import get_neural_bridge
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.reasoning.reasoning_interfaces import ReasoningType

    bridge = get_neural_bridge()
    if hasattr(bridge, "initialize"):
        await bridge.initialize()

    # Minimal stand-in: the real reason_about method, a real bridge, a memory
    # stub that records that a store was attempted.
    stored = []

    class _Stub:
        pass
    obj = _Stub()
    obj.neural_bridge = bridge

    async def _store(mem_type, payload, *a, **k):
        stored.append((mem_type, payload))
        return True, "stub"
    obj.store_memory = _store

    reason_about = AutonomousCoordinator.reason_about.__get__(obj, _Stub)

    cases = [
        ("deductive", "is socrates mortal?",
         {"premises": ["human(socrates)"], "rules": ["human(?x) -> mortal(?x)"]},
         "mortal"),
        ("causal", "what does smoking cause?",
         {"premises": ["smoking causes lung damage"]}, "lung damage"),
        ("temporal", "does the alarm ring before breakfast?",
         {"premises": ["the alarm rings before the coffee brews",
                       "the coffee brews before breakfast"]}, "before"),
    ]

    results = []
    for kind_value, question, ctx, expect in cases:
        rt = next(t for t in ReasoningType if t.value == kind_value)
        result = await reason_about(question, ctx, rt)
        md = getattr(result, "metadata", {}) or {}
        answer = str(getattr(result, "answer", "") or "")
        route = md.get("route") or []
        ok = (md.get("verified") is True
              and md.get("kind") == kind_value
              and "reason_about" in route and "neural_bridge" in route
              and expect.lower() in answer.lower())
        results.append((kind_value, ok,
                        f"verified={md.get('verified')} kind={md.get('kind')} "
                        f"route={route} answer={answer[:50]!r}"))

    print("\n===== coordinator.reason_about() THROUGH THE AUTHORITY =====")
    passed = 0
    for kind_value, ok, detail in results:
        if ok:
            passed += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {kind_value:12} {detail}")
    print(f"  store_memory attempted: {len(stored)} time(s) (provenance recorded)")
    print(f"\n  {passed}/{len(cases)} coordinator reasoning calls verified via the authority\n")
    return 0 if passed == len(cases) else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except Exception as error:
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
