#!/usr/bin/env python3
"""
Standalone Test for Intrinsic Motivation System — SUBSTRATE, no LLM.

Intrinsic motivation is a substrate faculty. It generates goals from real
measured signals (component uncertainties + unstable beliefs), NOT from a model.
The LLM goal-generation / mutation / exploration fallback were retired on
2026-08-28; this test verifies the substrate does the job on its own and that
zero LLM calls occur.

    python test_intrinsic_motivation.py
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
logging.getLogger('transformers').setLevel(logging.ERROR)
logging.getLogger('torch').setLevel(logging.ERROR)
logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))
os.environ['SKIP_TOOL_REGISTRY_INIT'] = '1'

# Any LLM inference during goal generation is a failure — count it.
LLM = {"generate": 0, "process_request": 0}


def _install_llm_spy():
    from core.services.unified_llm import UnifiedLLMService
    og, op = UnifiedLLMService.generate, UnifiedLLMService.process_request

    async def sg(self, *a, **k):
        LLM["generate"] += 1
        return await og(self, *a, **k)

    async def sp(self, *a, **k):
        LLM["process_request"] += 1
        return await op(self, *a, **k)

    UnifiedLLMService.generate, UnifiedLLMService.process_request = sg, sp


async def test_intrinsic_motivation():
    print("=" * 80)
    print("INTRINSIC MOTIVATION — SUBSTRATE GOAL GENERATION (no LLM)")
    print("=" * 80)

    _install_llm_spy()

    from core.agents.autonomous.intrinsic_motivation import IntrinsicMotivationSystem
    motivation = IntrinsicMotivationSystem()
    await motivation.initialize()
    assert not hasattr(motivation, "llm"), "motivation must hold no llm reference"
    assert not hasattr(motivation, "set_llm"), "set_llm must be gone"
    print("✓ Created; holds no LLM reference")

    # Realistic system signals — the substrate's real inputs.
    system_context = {
        "failed_tasks": [
            {"component": "memory_agent", "status": "failed", "confidence": 0.3},
            {"component": "memory_agent", "status": "failed", "confidence": 0.7},
            {"component": "memory_agent", "status": "completed", "confidence": 0.8},
            {"component": "tool_executor", "status": "failed", "confidence": 0.4},
        ],
        "performance_metrics": {
            "memory_agent": {"prediction_error": 0.45, "current": 0.6, "baseline": 1.0},
            "reasoning_engine": {"prediction_error": 0.55, "current": 0.7, "baseline": 1.0},
        },
        "recent_errors": [
            {"component": "memory_agent", "type": "timeout"},
            {"component": "memory_agent", "type": "connection_reset"},
        ],
        "knowledge_gaps": [{"component": "reasoning_engine", "uncertainty": 0.7}],
        "security_findings": [{"component": "api_gateway", "severity": "high"}],
    }

    # 1) uncertainty quantified model-free
    cm = await motivation._quantify_component_uncertainties(system_context)
    assert cm, "expected component uncertainties from the signals"
    print(f"\n✓ Quantified uncertainty for {len(cm)} components (model-free):")
    for c, m in cm.items():
        print(f"    {c}: epistemic={m['epistemic_uncertainty']} "
              f"pred_err={m['prediction_error']} fail={m['failure_rate']}")

    # 2) real goals from those signals
    goals = await motivation.generate_curiosity_driven_goals(
        max_goals=5, system_context=system_context)
    assert goals, "substrate produced no goals from real signals"
    print(f"\n✓ Generated {len(goals)} goals from real signals:")
    for g in goals:
        assert g.description and "→" in g.description, "goal must be metric-composed"
        print(f"    [{g.priority}] {g.description}")

    # 3) honest empty — no signals, no invented goal
    empty = await motivation.generate_curiosity_driven_goals(
        max_goals=3, system_context={})
    print(f"\n✓ Empty context → {len(empty)} goals "
          f"(honest empty unless real unstable beliefs exist)")

    # 4) SEVERANCE — MiniLM is guidance, never the decider. With the embedding
    #    encoder unavailable, the SAME goal must still form (severing similarity
    #    must not change what merits investigation). MiniLM only shifts ranking.
    from core.memory.utils import embedding_service as es_mod
    orig_gen = es_mod.EmbeddingService.generate_embedding

    def _severed(self, text):
        raise RuntimeError("MiniLM severed")

    es_mod.EmbeddingService.generate_embedding = _severed
    try:
        sev = IntrinsicMotivationSystem()
        await sev.initialize()
        sev_goals = await sev.generate_curiosity_driven_goals(
            max_goals=5, system_context=system_context)
    finally:
        es_mod.EmbeddingService.generate_embedding = orig_gen

    sev_components = {g.metadata.get("target_component") for g in sev_goals}
    assert sev_goals, "severing MiniLM must not stop goals forming"
    assert "tool_executor" in sev_components, \
        "severing MiniLM must NOT change that tool_executor merits investigation"
    print(f"\n✓ MiniLM severed → {len(sev_goals)} goals STILL form "
          f"(formation AND ranking are deterministic; MiniLM only maintains the "
          f"downstream dedup/retrieval index)")

    # 5) zero LLM
    print(f"\nLLM calls: generate={LLM['generate']} "
          f"process_request={LLM['process_request']}")
    assert LLM["generate"] == 0 and LLM["process_request"] == 0, \
        "intrinsic motivation must not call the LLM"

    print("\n" + "=" * 80)
    print("PASS — the substrate generates real intrinsic goals with zero LLM")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_intrinsic_motivation())
