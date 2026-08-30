#!/usr/bin/env python3
"""
Embedding Critic
================
Deterministic stand-in for the LLM critic used in completion verification.

The LLM critic answers three questions, and every one returns a boolean:

    "does this output answer this question?"      -> answered:  bool
    "is this claim supported by the evidence?"    -> grounded:  bool
    "is this requirement substantively covered?"  -> covered:   bool

A closed output space does not need an 8-billion-parameter language model.
This computes the same three judgements from sentence-embedding similarity
using all-MiniLM-L6-v2 — already loaded for memory, 384 dimensions, CPU, no
network, no generation.

It is weaker than an LLM judge on genuinely subtle wording. Whether that
matters is an empirical question, which is why `CriticComparison` exists: run
both, record where they disagree, and decide from evidence rather than
argument.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Cosine-similarity thresholds. Deliberately conservative: the failure mode we
# care about is a task claiming success falsely, so err toward "not answered".
ANSWERED_THRESHOLD = 0.45
GROUNDED_THRESHOLD = 0.40
COVERED_THRESHOLD = 0.42

# Below this, a requirement is judged mentioned-but-not-substantive
DEPTH_SUBSTANTIAL = 0.60


@dataclass
class CriticJudgement:
    """One judgement, in the same shape the LLM critic returns."""
    verdict: bool
    confidence: float
    similarity: float
    detail: str = ""


class EmbeddingCritic:
    """Semantic verification via sentence embeddings. No generation."""

    def __init__(self):
        self._svc = None
        # Segment embeddings cached per output document. A completion check asks
        # ~22 questions against the SAME output; without this the same segments
        # are re-embedded for every question (462 embeddings where 42 suffice).
        self._segment_cache: Dict[int, Tuple[List[str], List[List[float]]]] = {}

    def _service(self):
        if self._svc is None:
            from core.memory.utils.embedding_service import get_embedding_service
            self._svc = get_embedding_service()
        return self._svc

    def reset_cache(self) -> None:
        """Drop cached segment embeddings. Call between tasks."""
        self._segment_cache.clear()

    def _segment_embeddings(self, haystack: str) -> Optional[List[List[float]]]:
        """Embeddings for every passage of `haystack`, computed once and reused.

        Batched in a single encode() call rather than one per segment.
        """
        key = hash(haystack)
        cached = self._segment_cache.get(key)
        if cached is not None:
            return cached[1]

        segments = [
            s.strip() for s in re.split(r"\n\s*\n|(?<=[.!?])\s{2,}", haystack) if s.strip()
        ] or [haystack]
        segments = segments[:40]

        try:
            vectors = self._service().batch_embed([s[:4000] for s in segments])
        except Exception as e:
            logger.debug(f"Batch embedding failed: {e}")
            return None
        if not vectors:
            return None

        self._segment_cache[key] = (segments, vectors)
        return vectors

    # ------------------------------------------------------------------ core

    def _embed(self, text: str) -> Optional[List[float]]:
        if not text or not text.strip():
            return None
        try:
            return self._service().generate_embedding(text[:4000])
        except Exception as e:
            logger.debug(f"Embedding failed: {e}")
            return None

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        import numpy as np
        va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))

    def _best_segment_similarity(self, needle: str, haystack: str) -> Optional[float]:
        """Highest similarity between `needle` and any passage of `haystack`.

        Whole-document similarity dilutes: a long output that answers the
        question in one paragraph scores low against the full text. Comparing
        against segments finds the paragraph that actually addresses it.

        Returns None when nothing could be embedded — deliberately distinct
        from a low score. Cosine is genuinely negative for unrelated text
        (~-0.05), so clamping the floor to 0.0 made "unrelated" and "embedding
        failed" indistinguishable.
        """
        nv = self._embed(needle)
        if nv is None:
            return None

        vectors = self._segment_embeddings(haystack)
        if not vectors:
            return None

        best = None
        for sv in vectors:
            sim = self._cosine(nv, sv)
            best = sim if best is None else max(best, sim)
        return best

    # ------------------------------------------------------- the three layers

    def is_answered(self, question: str, output: str) -> CriticJudgement:
        sim = self._best_segment_similarity(question, output)
        if sim is None:
            return CriticJudgement(False, 0.0, 0.0, "no signal — embedding unavailable")
        verdict = sim >= ANSWERED_THRESHOLD
        return CriticJudgement(
            verdict=verdict,
            confidence=min(1.0, sim / ANSWERED_THRESHOLD) if verdict else 1.0 - sim,
            similarity=round(sim, 4),
            detail=f"best passage similarity {sim:.3f} vs threshold {ANSWERED_THRESHOLD}",
        )

    def is_grounded(self, claim: str, evidence: str) -> CriticJudgement:
        sim = self._best_segment_similarity(claim, evidence)
        if sim is None:
            return CriticJudgement(False, 0.0, 0.0, "no signal — embedding unavailable")
        verdict = sim >= GROUNDED_THRESHOLD
        return CriticJudgement(
            verdict=verdict,
            confidence=min(1.0, sim / GROUNDED_THRESHOLD) if verdict else 1.0 - sim,
            similarity=round(sim, 4),
            detail="evidence" if verdict else "fabricated",
        )

    def is_covered(self, requirement: str, output: str) -> CriticJudgement:
        sim = self._best_segment_similarity(requirement, output)
        if sim is None:
            return CriticJudgement(False, 0.0, 0.0, "no signal — embedding unavailable")
        verdict = sim >= COVERED_THRESHOLD
        depth = "substantial" if sim >= DEPTH_SUBSTANTIAL else ("mention" if verdict else "none")
        return CriticJudgement(
            verdict=verdict,
            confidence=min(1.0, sim / COVERED_THRESHOLD) if verdict else 1.0 - sim,
            similarity=round(sim, 4),
            detail=depth,
        )


@dataclass
class CriticComparison:
    """Records where the embedding critic and the LLM critic disagree.

    The point is to decide empirically whether the 8B is contributing, rather
    than assuming either way.
    """
    agreements: int = 0
    disagreements: int = 0
    samples: List[Dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        layer: str,
        subject: str,
        llm_verdict: bool,
        emb: CriticJudgement,
    ) -> None:
        agreed = (llm_verdict == emb.verdict)
        if agreed:
            self.agreements += 1
        else:
            self.disagreements += 1
            logger.info(
                f"[critic-disagree] {layer}: llm={llm_verdict} emb={emb.verdict} "
                f"(sim={emb.similarity:.3f}) on {subject[:80]!r}"
            )
        if len(self.samples) < 200:
            self.samples.append({
                "layer": layer,
                "subject": subject[:200],
                "llm": llm_verdict,
                "embedding": emb.verdict,
                "similarity": emb.similarity,
                "agreed": agreed,
            })

    @property
    def agreement_rate(self) -> Optional[float]:
        total = self.agreements + self.disagreements
        return round(self.agreements / total, 4) if total else None

    def summary(self) -> Dict[str, Any]:
        return {
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "agreement_rate": self.agreement_rate,
            "sample_count": len(self.samples),
        }


_critic: Optional[EmbeddingCritic] = None
_comparison: Optional[CriticComparison] = None


def get_embedding_critic() -> EmbeddingCritic:
    global _critic
    if _critic is None:
        _critic = EmbeddingCritic()
    return _critic


def get_critic_comparison() -> CriticComparison:
    global _comparison
    if _comparison is None:
        _comparison = CriticComparison()
    return _comparison


__all__ = [
    "EmbeddingCritic", "CriticJudgement", "CriticComparison",
    "get_embedding_critic", "get_critic_comparison",
]
