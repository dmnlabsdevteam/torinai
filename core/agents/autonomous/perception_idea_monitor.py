"""Perception-to-Idea Monitor

Captures inspiration signals from environment events and emergent pattern analysis
and synthesizes creative goal seeds using the quantum reasoning engine's divergent
creative capabilities.

Signals considered:
- Novel entities / behaviors (novelty score, classification)
- Unmet needs (resource inefficiency, repeated failure patterns, missing capabilities)
- Repeated user themes (recurring requests, topics) – placeholder hooks

Produces:
- Creative goal seed dicts with rationale and source signal aggregation

Config keys (optional):
perception_idea_monitor: {
  "enabled": true,
  "min_novelty": 0.65,
  "min_pattern_strength": 0.5,
  "aggregation_window_sec": 900,
  "cooldown_sec": 300,
  "max_signals": 50,
  "max_seeds_per_cycle": 3
}
"""
from __future__ import annotations  # noqa

# flake8: noqa  # (Module has intentional long descriptive lines; focus lint on core system separately)

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Set
import logging

logger = logging.getLogger(__name__)

@dataclass
class InspirationSignal:
    signal_id: str
    signal_type: str  # e.g., novel_entity, emergent_pattern, unmet_need, repeated_theme
    content: Dict[str, Any]
    novelty: float = 0.0
    strength: float = 0.0
    timestamp: float = field(default_factory=lambda: time.time())
    sources: List[str] = field(default_factory=list)

    def score(self) -> float:
        # Weighted combination (tunable)
        return 0.6 * self.novelty + 0.4 * self.strength

@dataclass
class GoalSeed:
    seed_id: str
    description: str
    rationale: str
    sources: List[str]
    inspiration_signals: List[str]
    created_at: float = field(default_factory=lambda: time.time())
    priority_hint: str = "medium"

class PerceptionIdeaMonitor:
    def __init__(self, quantum_engine: Any, config: Optional[Dict[str, Any]] = None,
                 create_goal_callback: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self.quantum_engine = quantum_engine
        self.config = config or {}
        self.create_goal_callback = create_goal_callback

        monitor_cfg = self.config.get("perception_idea_monitor", {})
        self.enabled: bool = monitor_cfg.get("enabled", True)
        self.min_novelty: float = monitor_cfg.get("min_novelty", 0.65)
        self.min_pattern_strength: float = monitor_cfg.get("min_pattern_strength", 0.5)
        self.aggregation_window: int = monitor_cfg.get("aggregation_window_sec", 900)
        self.cooldown_sec: int = monitor_cfg.get("cooldown_sec", 300)
        self.max_signals: int = monitor_cfg.get("max_signals", 50)
        self.max_seeds_per_cycle: int = monitor_cfg.get("max_seeds_per_cycle", 3)

        self.signals: List[InspirationSignal] = []
        self.generated_seeds: List[GoalSeed] = []
        self.last_generation_ts: float = 0.0
        self._lock = asyncio.Lock()
        self.persistence_enabled = monitor_cfg.get("persist_seeds", False)
        # Persistence callback (no annotation on assignment for runtime compatibility)
        self._persist_func = monitor_cfg.get("seed_persist_callback")

    def add_environment_event(self, event: Dict[str, Any]):
        if not self.enabled:
            return
        try:
            novelty = event.get("data", {}).get("novelty", 0.0)
            if novelty < self.min_novelty and event.get("event_type") != "opportunity_identified":
                return
            signal = InspirationSignal(
                signal_id=str(uuid.uuid4()),
                signal_type="environment_event",
                content=event,
                novelty=novelty,
                strength=event.get("data", {}).get("significance", 0.5),
                sources=["environment"]
            )
            self._store_signal(signal)
        except Exception as e:
            logger.error(f"Error adding environment event signal: {e}")

    def add_emergent_behavior(self, behavior: Dict[str, Any]):
        if not self.enabled:
            return
        try:
            novelty = 0.7 if behavior.get("type") == "novel" else behavior.get("pattern_strength", 0.0)
            strength = behavior.get("pattern_strength", 0.5)
            if novelty < self.min_novelty and strength < self.min_pattern_strength:
                return
            signal = InspirationSignal(
                signal_id=str(uuid.uuid4()),
                signal_type="emergent_behavior",
                content=behavior,
                novelty=novelty,
                strength=strength,
                sources=["emergent_analysis"]
            )
            self._store_signal(signal)
        except Exception as e:
            logger.error(f"Error adding emergent behavior signal: {e}")

    def add_unmet_need(self, descriptor: Dict[str, Any]):
        if not self.enabled:
            return
        try:
            signal = InspirationSignal(
                signal_id=str(uuid.uuid4()),
                signal_type="unmet_need",
                content=descriptor,
                novelty=descriptor.get("novelty", 0.5),
                strength=descriptor.get("severity", 0.6),
                sources=["internal_assessment"]
            )
            self._store_signal(signal)
        except Exception as e:
            logger.error(f"Error adding unmet need signal: {e}")

    def add_repeated_theme(self, theme: Dict[str, Any]):
        if not self.enabled:
            return
        try:
            signal = InspirationSignal(
                signal_id=str(uuid.uuid4()),
                signal_type="repeated_theme",
                content=theme,
                novelty=theme.get("novelty", 0.4),
                strength=theme.get("frequency_strength", 0.7),
                sources=["user_interactions"]
            )
            self._store_signal(signal)
        except Exception as e:
            logger.error(f"Error adding repeated theme signal: {e}")

    def _store_signal(self, signal: InspirationSignal):
        try:
            cutoff = time.time() - self.aggregation_window
            self.signals = [s for s in self.signals if s.timestamp >= cutoff]
            self.signals.append(signal)
            if len(self.signals) > self.max_signals:
                self.signals = sorted(self.signals, key=lambda s: s.score(), reverse=True)[: self.max_signals]
        except Exception as e:
            logger.error(f"Error storing signal: {e}")

    async def maybe_generate_goal_seeds(self) -> List[GoalSeed]:
        if not self.enabled:
            return []
        async with self._lock:
            now = time.time()
            if now - self.last_generation_ts < self.cooldown_sec:
                return []
            if not self.signals:
                return []
            # Rank & slice signals
            ranked = sorted(self.signals, key=lambda s: s.score(), reverse=True)
            top_signals = ranked[: min(len(ranked), 12)]

            # Extract concept tokens with richer semantic variants
            def concept_from(sig: InspirationSignal) -> Optional[str]:
                if sig.signal_type == "emergent_behavior":
                    return str(sig.content.get("classification") or sig.content.get("type") or "emergent")
                if sig.signal_type == "environment_event":
                    return str(sig.content.get("event_type") or "event")
                return str(sig.content.get("description") or sig.content.get("name") or sig.signal_type)

            concepts = list({c for c in (concept_from(s) for s in top_signals) if c})
            if not concepts:
                return []

            # Build divergent subsets (pairwise + triples + full) limited by max seeds
            subsets: List[List[str]] = []
            # Single anchors
            for c in concepts[:4]:
                subsets.append([c])
            # Pairwise combos
            for i in range(min(len(concepts), 5)):
                for j in range(i+1, min(len(concepts), 6)):
                    subsets.append([concepts[i], concepts[j]])
            # Triple (first three if available)
            if len(concepts) >= 3:
                subsets.append(concepts[:3])
            # Full set
            subsets.append(concepts)

            # Deduplicate subset signatures
            seen: Set[str] = set()
            unique_subsets: List[List[str]] = []
            for ss in subsets:
                key = "|".join(sorted(ss))
                if key not in seen:
                    seen.add(key)
                    unique_subsets.append(ss)

            # Limit by configured divergence cap
            unique_subsets = unique_subsets[: max(self.max_seeds_per_cycle, 1)]

            seeds: List[GoalSeed] = []
            rationale_base = "Synthesized from signals: " + ", ".join(sorted({s.signal_type for s in top_signals}))

            for idx, subset in enumerate(unique_subsets):
                creative_desc = None
                if hasattr(self.quantum_engine, 'creative_synthesis'):
                    try:
                        ct = await self.quantum_engine.creative_synthesis(subset)
                        creative_desc = getattr(ct, 'content', None)
                    except Exception as e:
                        logger.debug(f"Subset creative synthesis failed for {subset}: {e}")
                base_desc = creative_desc or f"Explore synergy: {', '.join(subset)}"
                focus = subset[-1]
                seed = GoalSeed(
                    seed_id=str(uuid.uuid4()),
                    description=f"{base_desc} -> Focus: {focus}",
                    rationale=rationale_base,
                    sources=list({src for s in top_signals for src in s.sources}),
                    inspiration_signals=[s.signal_id for s in top_signals],
                    priority_hint="high" if idx == 0 else ("medium" if idx < 3 else "low")
                )
                seeds.append(seed)
            # Fallback: ensure at least one seed
            if not seeds:
                seeds.append(GoalSeed(
                    seed_id=str(uuid.uuid4()),
                    description=f"Explore synergy: {', '.join(concepts[:3])}",
                    rationale=rationale_base,
                    sources=list({src for s in top_signals for src in s.sources}),
                    inspiration_signals=[s.signal_id for s in top_signals],
                    priority_hint="medium"
                ))
            self.generated_seeds.extend(seeds)
            self.last_generation_ts = now
            # Persist seeds if configured
            if self.persistence_enabled:
                for seed in seeds:
                    try:
                        if self._persist_func:
                            self._persist_func(seed)
                    except Exception as e:
                        logger.warning(f"Seed persistence failed for {seed.seed_id}: {e}")
            # Optionally create goals immediately
            if self.create_goal_callback:
                for seed in seeds:
                    try:
                        self.create_goal_callback({
                            "description": seed.description,
                            "rationale": seed.rationale,
                            "sources": seed.sources,
                            "inspiration_signals": seed.inspiration_signals,
                            "priority_hint": seed.priority_hint,
                            "seed_id": seed.seed_id
                        })
                    except Exception as e:
                        logger.error(f"Failed to create goal from seed {seed.seed_id}: {e}")
            logger.info(f"Generated {len(seeds)} creative goal seeds from {len(top_signals)} signals")
            return seeds

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "signal_count": len(self.signals),
            "recent_seeds": [s.seed_id for s in self.generated_seeds[-5:]],
            "last_generation_age": time.time() - self.last_generation_ts,
        }
