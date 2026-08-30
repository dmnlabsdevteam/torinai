#!/usr/bin/env python3
"""
EpistemicEngine — Unified BayesianUncertaintySystem + HypothesisTestingSystem.

Public API (callers never touch the subsystems directly):

    apply_llm_output(outputs) -> List[EpistemicMutation]
        Snapshot → apply → recompute → measure delta → record only real mutations.
        Serialised through asyncio.Lock; safe for concurrent executor threads.

    observe_tool_result(tool_name, parameters, output, success) -> List[EpistemicMutation]
        Called after each tool execution in the agent loop.
        Converts tool outcomes into belief evidence so the epistemic engine
        reflects actual task progress — not just post-completion LLM assertions.
        Each successful call corroborates a canonical belief for that tool category,
        raising its posterior and lowering entropy until it exits the unstable set.

    get_unstable_regions() -> List[EpistemicTarget]
        Read-only snapshot of high-entropy beliefs and stalled hypotheses.
        Called by intrinsic motivation to generate epistemic exploration goals.

Design rules enforced here:
  - Entropy delta must exceed EPSILON to count as a mutation.
  - New belief with prior=0.5 has delta=0: NOT a mutation.
  - Hypothesis creation without linked belief entropy shift: NOT a mutation.
  - Stalled hypothesis detection requires both old age AND low evidence count.
  - Hypothesis system failure degrades gracefully (belief mutations still count).
"""

import asyncio
import logging
import re
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, NamedTuple, Optional

logger = logging.getLogger(__name__)

# Minimum entropy change that counts as real epistemic movement.
EPSILON: float = 1e-4

# Minimum |prior - 0.5| for a brand-new belief to count as a mutation.
# Prevents farming: creating beliefs near p=0.5 contributes no information.
PRIOR_INFORMATION_THRESHOLD: float = 0.05

# Stale hypothesis: no evidence after this many hours.
STAGNATION_HOURS: float = 24.0

# Minimum evidence pieces before a hypothesis is considered "being worked on".
EVIDENCE_MINIMUM: int = 1


# ---------------------------------------------------------------------------
# Canonical types
# ---------------------------------------------------------------------------

class EpistemicMutation(NamedTuple):
    """Canonical record of a single epistemic state change.

    mutation_type values:
        new_hypothesis    - hypothesis created with |prior-0.5| > PRIOR_INFORMATION_THRESHOLD
        new_belief        - belief node created with meaningful prior deviation
        entropy_reduction - existing belief moved toward certainty (delta > 0)
        entropy_increase  - existing belief moved toward uncertainty (delta < 0)

    Note: relationship creation is NOT a mutation type. add_relationship() now
    triggers immediate constraint propagation (activation_delta = source.posterior
    - 0.5, max_depth=3), but the resulting entropy changes are attributed to the
    source belief's existing posterior, not to the act of wiring topology.
    Counting topology creation as a mutation would allow farming without
    epistemic progress.
    """
    mutation_type: str
    entity_id: str    # belief_id, hypothesis_id, or relationship_id
    delta: float      # signed entropy delta (positive = entropy reduced = more certain)


@dataclass
class EpistemicTarget:
    """A high-uncertainty region that intrinsic motivation should explore."""
    target_id: str
    target_type: str           # "belief" or "hypothesis"
    entropy: float             # current entropy (higher = more uncertain)
    description: str           # becomes Goal.description
    domain: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def uncertainty_score(self) -> float:
        """Consumer-facing name for entropy — the same quantity.

        Novelty and curiosity are deliberately NOT exposed here: a long-known
        belief can be maximally uncertain, so entropy is not novelty, and
        aliasing them would hide a real distinction.
        """
        return self.entropy


class EpistemicNoOpError(Exception):
    """Raised when a task that requires epistemic output produces none."""
    pass


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EpistemicEngine:
    """
    Unified facade over BayesianUncertaintySystem and HypothesisTestingSystem.

    Architecture contract:
      - Executor calls apply_llm_output() after task completion.
      - Intrinsic motivation calls get_unstable_regions() for goal generation.
      - Coordinator only reads result["epistemic_mutations"] (a list).
      - Nothing else accesses the subsystems directly.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Subsystem accessors (lazy, to avoid circular imports)
    # ------------------------------------------------------------------

    def _uncertainty(self):
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system()

    def _hypothesis_sys(self):
        from core.reasoning.hypothesis_testing import get_hypothesis_system
        return get_hypothesis_system()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_entropy(p: float) -> float:
        """Shannon entropy of a binary distribution."""
        p = max(1e-9, min(1 - 1e-9, p))
        return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))

    @staticmethod
    def _hyp_entropy(hyp) -> float:
        """Entropy of a hypothesis derived from its confidence."""
        return EpistemicEngine._calc_entropy(
            max(0.001, min(0.999, hyp.confidence))
        )

    def _find_belief(self, claim: str):
        """Case-insensitive exact match on claim text."""
        claim_norm = claim.lower().strip()
        for b in self._uncertainty().beliefs.values():
            if b.claim.lower().strip() == claim_norm:
                return b
        return None

    @staticmethod
    def _parse_relation(relation: str):
        try:
            from core.reasoning.bayesian_uncertainty import RelationType
            return RelationType[relation.upper()]
        except (KeyError, ImportError):
            return None

    # ------------------------------------------------------------------
    # Public: apply LLM output
    # ------------------------------------------------------------------

    async def apply_llm_output(
        self, outputs: Dict[str, Any]
    ) -> List[EpistemicMutation]:
        """
        Parse structured LLM outputs and apply epistemic mutations.

        Correct order per belief:
          1. Snapshot entropy_before
          2. Apply update (create_belief / update_belief / add_relationship)
          3. Recompute entropy_after from returned object
          4. If |delta| > EPSILON → record EpistemicMutation

        NOTE: Creating a belief with prior=0.5 gives entropy=1.0 = max.
        entropy_before for a new belief = 1.0 (the claim didn't exist).
        If posterior == 0.5 → delta = 0 → NOT a mutation.

        All mutations serialised through self._lock.

        Returns:
            List[EpistemicMutation] — empty means no real epistemic change.
        """
        mutations: List[EpistemicMutation] = []

        hypotheses_raw = outputs.get("hypotheses") or []
        belief_updates_raw = outputs.get("belief_updates") or []

        if not hypotheses_raw and not belief_updates_raw:
            return mutations

        async with self._lock:
            unc = self._uncertainty()

            # Per-belief cumulative delta tracker — anti-farming control.
            # Each belief contributes at most ONE mutation record per call,
            # using its NET entropy change across all updates in this batch.
            belief_net_delta: Dict[str, float] = {}
            # Track which belief_ids were created (vs updated) in this call.
            newly_created_ids: set = set()

            # ---- 1. New hypotheses ----------------------------------------
            for h in hypotheses_raw:
                claim = (h.get("claim") or "").strip()
                if not claim:
                    continue

                domain = h.get("domain") or "general"
                prior = float(h.get("confidence", 0.5))
                prior = max(0.05, min(0.95, prior))
                predictions = h.get("predictions") or []

                # Guard: prior must deviate meaningfully from 0.5.
                # Creating a near-neutral belief adds no information and
                # should not count as epistemic progress.
                if abs(prior - 0.5) <= PRIOR_INFORMATION_THRESHOLD:
                    logger.debug(
                        f"EpistemicEngine: hypothesis '{claim[:60]}' "
                        f"prior={prior:.2f} too close to 0.5 — skipped"
                    )
                    # Still create the belief for future evidence to act on,
                    # but do not count it as a mutation.
                    unc.create_belief(claim, domain, prior=prior)
                else:
                    # entropy_before = 1.0 (max) — claim didn't exist.
                    entropy_before = 1.0
                    belief = unc.create_belief(claim, domain, prior=prior)
                    newly_created_ids.add(belief.belief_id)
                    entropy_after = belief.entropy  # H(prior)
                    delta = entropy_before - entropy_after
                    if abs(delta) > EPSILON:
                        belief_net_delta[belief.belief_id] = delta
                        logger.info(
                            f"EpistemicEngine: new hypothesis "
                            f"'{claim[:60]}' entropy {entropy_before:.4f} → "
                            f"{entropy_after:.4f} (Δ={delta:+.4f})"
                        )

                # Persist in HypothesisTestingSystem if DB is ready.
                # Failure here does NOT block belief mutations from counting.
                try:
                    hyp_sys = self._hypothesis_sys()
                    if hyp_sys.db is not None:
                        hyp = await hyp_sys.generate_hypothesis(
                            claim=claim,
                            domain=domain,
                            predictions=predictions,
                        )
                        logger.info(
                            f"EpistemicEngine: HypothesisTestingSystem "
                            f"created {hyp.hypothesis_id}"
                        )
                except Exception as e:
                    logger.warning(
                        f"EpistemicEngine: HypothesisTesting persistence "
                        f"skipped (DB not ready?): {e}"
                    )

            # ---- 2. Belief updates ----------------------------------------
            for bu in belief_updates_raw:
                claim = (bu.get("claim") or "").strip()
                if not claim:
                    continue

                domain = bu.get("domain") or "general"
                relation_str = (bu.get("relation") or "SUPPORTS").upper()
                target_claim = (bu.get("target_claim") or "").strip()
                confidence = float(bu.get("confidence", 0.5))
                confidence = max(0.05, min(0.95, confidence))
                evidence_text = bu.get("evidence") or ""

                # Find or create the source belief
                source_belief = self._find_belief(claim)
                if source_belief is None:
                    # New belief — apply same information threshold.
                    if abs(confidence - 0.5) <= PRIOR_INFORMATION_THRESHOLD:
                        source_belief = unc.create_belief(
                            claim, domain, prior=confidence
                        )
                        # No mutation: prior too close to neutral
                    else:
                        entropy_before = 1.0
                        source_belief = unc.create_belief(
                            claim, domain, prior=confidence
                        )
                        newly_created_ids.add(source_belief.belief_id)
                        entropy_after = source_belief.entropy
                        delta = entropy_before - entropy_after
                        if abs(delta) > EPSILON:
                            prev = belief_net_delta.get(source_belief.belief_id, 0.0)
                            belief_net_delta[source_belief.belief_id] = prev + delta
                else:
                    # Update existing belief — snapshot BEFORE, measure AFTER.
                    entropy_before = source_belief.entropy
                    evidence = {
                        "quality": confidence,
                        "description": evidence_text,
                    }
                    supports = relation_str in ("SUPPORTS", "IMPLIES")
                    updated = unc.update_belief(
                        source_belief.belief_id,
                        evidence=evidence,
                        evidence_supports=supports,
                    )
                    entropy_after = updated.entropy
                    delta = entropy_before - entropy_after
                    if abs(delta) > EPSILON:
                        prev = belief_net_delta.get(source_belief.belief_id, 0.0)
                        belief_net_delta[source_belief.belief_id] = prev + delta
                        logger.info(
                            f"EpistemicEngine: belief update "
                            f"'{claim[:50]}' entropy {entropy_before:.4f} → "
                            f"{entropy_after:.4f} (Δ={delta:+.4f})"
                        )

                # Add relationship — triggers immediate constraint propagation
                # (activation_delta = source.posterior - 0.5, max_depth=3).
                # NOT counted as a mutation: the propagation is attributed to
                # the source belief's current posterior, not the topology wire.
                if target_claim and source_belief is not None:
                    target_belief = self._find_belief(target_claim)
                    if target_belief is None:
                        target_belief = unc.create_belief(
                            target_claim, domain, prior=0.5
                        )
                    rel_type = self._parse_relation(relation_str)
                    if rel_type is not None:
                        unc.add_relationship(
                            source_belief_id=source_belief.belief_id,
                            target_belief_id=target_belief.belief_id,
                            relation_type=rel_type,
                            strength=confidence,
                            discovered_by="llm",
                        )

            # ---- 3. Convert per-belief net deltas to one mutation each ----
            # hypotheses_raw claims are "new_hypothesis"; belief_updates are
            # "new_belief" (if newly created) or entropy_reduction/increase.
            hypothesis_claims = {
                (h.get("claim") or "").strip().lower()
                for h in hypotheses_raw
            }
            for belief_id, net_delta in belief_net_delta.items():
                if abs(net_delta) <= EPSILON:
                    continue
                belief = unc.beliefs.get(belief_id)
                if belief is None:
                    continue
                is_new = belief_id in newly_created_ids
                if is_new:
                    mtype = (
                        "new_hypothesis"
                        if belief.claim.lower() in hypothesis_claims
                        else "new_belief"
                    )
                else:
                    mtype = "entropy_reduction" if net_delta > 0 else "entropy_increase"
                mutations.append(EpistemicMutation(
                    mutation_type=mtype,
                    entity_id=belief_id,
                    delta=net_delta,
                ))

        if mutations:
            types = ", ".join(sorted({m.mutation_type for m in mutations}))
            logger.info(
                f"EpistemicEngine.apply_llm_output: {len(mutations)} mutations "
                f"[{types}]"
            )
        return mutations

    # ------------------------------------------------------------------
    # Public: observe tool results during execution loop
    # ------------------------------------------------------------------

    async def observe_tool_result(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        output: Any,
        success: bool,
        interpreted: Optional[List[Dict[str, Any]]] = None,
    ) -> List[EpistemicMutation]:
        """
        Convert a tool execution outcome into belief evidence.

        Called by the executor after every tool call so the epistemic engine
        reflects real task progress during the loop — not just post-completion.

        Each tool category maps to a canonical belief claim. Repeated successful
        calls corroborate the same belief via SUPPORTS evidence, raising its
        posterior and lowering entropy until the belief exits the unstable set
        (entropy < 0.7). When all beliefs are stable, the convergence gate's
        uncertainty check passes.

        Failed tool calls do NOT lower uncertainty — only real evidence counts.
        """
        if not success:
            return []

        # ── INTERPRET THE OUTPUT ──────────────────────────────────────────
        # This used to key on tool_name alone and DISCARD `output`, falling back
        # to f"Task has successfully used tool '{tool_name}'" -- a tautology,
        # true the moment the call returned. Thirteen security tools hit that
        # fallback, resolved to ~0 entropy instantly, emptied the unstable set,
        # and the convergence gate read the empty set as "no data" and reported
        # uncertainty 1.000 for 80+ iterations while nothing was learned.
        #
        # The claim now comes from what the tool OBSERVED. When the output
        # cannot be interpreted we emit NO belief_updates -- the three-valued
        # UNKNOWN, expressed the way this system already expresses it. Same
        # conservative rule as the credit invariant: losing a learning
        # opportunity is recoverable, manufacturing knowledge is not.
        # `interpreted` lets the caller supply the single canonical
        # interpretation, so `output` is never interpreted twice.
        updates = (
            interpreted if interpreted is not None
            else self.interpret_tool_output(tool_name, parameters, output)
        )
        if not updates:
            logger.debug(
                "[epistemic] %s: output licenses no belief update "
                "(operational event only)", tool_name,
            )
            return []

        # Route through apply_llm_output so existing mutation recording,
        # deduplication, PRIOR_INFORMATION_THRESHOLD and net-delta tracking all
        # apply unchanged.
        mutations = await self.apply_llm_output({"belief_updates": updates})
        if mutations:
            logger.info(
                "[epistemic] %s → %d mutation(s): %s",
                tool_name, len(mutations),
                "; ".join(f"{u['relation']} {u['claim'][:48]}" for u in updates),
            )
        return mutations

    # Capability identity. Semantics attach to WHAT A TOOL DOES, never to
    # whichever function name survived a refactor: the old map targeted
    # `run_command` and `run_tests`, neither of which exists (the real tools are
    # `run_shell_command` and `run_python`), so every code execution fell
    # through to the generic branch.
    _CANONICAL_TOOL_IDS = {
        "run_python": "execution.python", "run_code": "execution.python",
        "run_tests": "execution.python",
        "run_shell_command": "execution.shell", "run_command": "execution.shell",
        "write_file": "file.write", "atomic_write_file": "file.write",
        "patch_file": "file.patch", "edit_file": "file.patch",
        "read_file": "file.read", "search_files": "file.search",
        "grep_search": "file.search",
        "lint_python": "quality.lint",
        "web_search": "research.web", "web_fetch": "research.web",
        "conduct_research": "research.web", "search_academic": "research.web",
        "security_scan": "security.scan", "search_secrets_pii": "security.scan",
        "monitor_logs": "security.logs",
        "detect_intrusion": "security.intrusion",
    }

    # Lifted from general_purpose_executor.py:3928 — these exist because blind
    # credential retries were a real observed failure.
    _CREDENTIAL_SIGNALS = (
        "github_token", "gh_token", "github_pat", "personal_access_token",
        "token", "credential", "osxkeychain", "gh auth",
    )

    _PYTEST_RE = re.compile(r"(?P<n>\d+)\s+(?P<kind>passed|failed|error)")

    @staticmethod
    def _output_text(output: Any) -> Optional[str]:
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            for k in ("stdout", "text", "content", "output"):
                v = output.get(k)
                if isinstance(v, str):
                    return v
        return None

    def interpret_tool_output(
        self, tool_name: str, parameters: Dict[str, Any], output: Any,
    ) -> List[Dict[str, Any]]:
        """Derive belief_updates from what the tool OBSERVED.

        Returns [] whenever the output does not license a claim about the world
        — unknown tool, empty result, unparsable shape. UNKNOWN is not a
        polarity here; it is the absence of an update.
        """
        params = parameters or {}
        cid = self._CANONICAL_TOOL_IDS.get(tool_name)
        if cid is None:
            return []                      # no interpreter -> no assertion

        # Empty result: three-valued. Never "the condition is absent".
        if output is None or str(output).strip() in ("", "None", "null"):
            return []

        d = output if isinstance(output, dict) else {}
        text = self._output_text(output)

        def upd(claim, supports, conf, ev, domain="general"):
            return [{
                "claim": claim, "domain": domain,
                "relation": "SUPPORTS" if supports else "WEAKENS",
                "confidence": conf if supports else 1.0 - conf,
                "evidence": f"{tool_name}: {ev}",
            }]

        # ── execution ────────────────────────────────────────────────────
        if cid in ("execution.python", "execution.shell"):
            exit_code = d.get("exit_code", d.get("returncode"))
            counts = {"passed": 0, "failed": 0, "error": 0}
            if text:
                for m in self._PYTEST_RE.finditer(text.lower()):
                    counts[m.group("kind")] = int(m.group("n"))
            if any(counts.values()):
                green = counts["failed"] == 0 and counts["error"] == 0 and counts["passed"] > 0
                return upd(
                    "the task's test suite passes", green, 0.9,
                    f"{counts['passed']} passed, {counts['failed']} failed, "
                    f"{counts['error']} error",
                )
            if exit_code is not None:
                return upd(
                    "the requested code executed without error",
                    int(exit_code) == 0, 0.85, f"exit_code={exit_code}",
                )
            return []                      # ran, nothing adjudicable

        # ── file mutation: operation succeeded != content changed ────────
        if cid in ("file.write", "file.patch"):
            delta = d.get("delta_bytes")
            if delta is None:
                for k in ("bytes_written", "bytes_changed", "bytes_after"):
                    if isinstance(d.get(k), (int, float)):
                        delta = d[k]
                        break
            if delta is None:
                return []
            changed = int(delta) != 0
            # A no-op patch must NOT assert that code changed on disk.
            return upd(
                "task changes have been applied to disk", changed, 0.9,
                f"delta_bytes={delta} path={params.get('file_path') or params.get('path','')}",
            )

        # ── lint: absent output is UNKNOWN, never "clean" ────────────────
        if cid == "quality.lint":
            if text is None:
                return []
            return upd(
                "the code is free of reported lint errors",
                "error" not in text.lower(), 0.75, "lint output parsed",
            )

        # ── security ─────────────────────────────────────────────────────
        if cid in ("security.scan", "security.logs", "security.intrusion"):
            findings = d.get("findings")
            for k in ("anomalies", "indicators", "detections", "alerts", "results"):
                if findings is None:
                    findings = d.get(k)
            if findings is None and isinstance(output, (list, tuple)):
                findings = list(output)
            if findings is None:
                return []
            claim = {
                "security.scan": "security findings are present in the scanned scope",
                "security.logs": "a log integrity anomaly is present",
                "security.intrusion": "an intrusion is detectable in the monitored scope",
            }[cid]
            present = bool(findings)
            # Clean result is negative evidence ONLY within what was covered.
            return upd(
                claim, present, 0.85 if present else 0.6,
                f"{len(findings)} finding(s), coverage={d.get('coverage')}",
                domain="security",
            )

        # ── research ─────────────────────────────────────────────────────
        if cid == "research.web":
            results = d.get("results") or d.get("raw_results")
            if results is None:
                return []
            return upd(
                "relevant external evidence has been gathered for this task",
                bool(results), 0.8 if results else 0.5,
                f"{len(results)} result(s)",
            )

        return []

    # ------------------------------------------------------------------
    # Public: read unstable regions
    # ------------------------------------------------------------------

    async def reason(self, request) -> Any:
        """Compute uncertainty for a reasoning request
        
        Args:
            request: ReasoningRequest with query, mode, and context
            
        Returns:
            ReasoningResult with uncertainty estimate
        """
        from core.reasoning.reasoning_interfaces import ReasoningResult
        
        # Get all unstable regions
        unstable_regions = self.get_unstable_regions()
        
        if not unstable_regions:
            # No unstable regions = low uncertainty
            return ReasoningResult(uncertainty=0.1, confidence=0.9, reasoning="No unstable epistemic regions")
        
        # Compute average entropy across unstable regions
        total_entropy = sum(region.entropy for region in unstable_regions)
        avg_entropy = total_entropy / len(unstable_regions)
        
        # Normalize to [0, 1] range (Shannon entropy for binary is max 1.0)
        uncertainty = min(1.0, avg_entropy)
        
        return ReasoningResult(
            uncertainty=uncertainty,
            confidence=1.0 - uncertainty,
            reasoning=f"Computed from {len(unstable_regions)} unstable regions, avg entropy={avg_entropy:.3f}"
        )
    
    def get_unstable_regions(self) -> List[EpistemicTarget]:
        """
        Return high-entropy beliefs and stalled hypotheses as exploration targets.

        Read-only snapshot — does NOT acquire the write lock.

        Stalled hypothesis criteria (both must hold):
          - status in {PROPOSED, INCONCLUSIVE}
          - age > STAGNATION_HOURS AND evidence_count < EVIDENCE_MINIMUM

        Fresh PROPOSED hypotheses are excluded to prevent re-triggering
        immediately after creation.

        Returns:
            List[EpistemicTarget] sorted by entropy descending.
        """
        targets: List[EpistemicTarget] = []

        # -- High-entropy beliefs ------------------------------------------
        try:
            unc = self._uncertainty()
            for belief_id, belief in unc.beliefs.items():
                # entropy > 0.7 → posterior roughly in (0.28, 0.72)
                if belief.entropy > 0.7:
                    targets.append(EpistemicTarget(
                        target_id=belief_id,
                        target_type="belief",
                        entropy=belief.entropy,
                        description=(
                            f"Design experiment to resolve uncertainty: "
                            f"{belief.claim}"
                        ),
                        domain=belief.domain,
                        metadata={
                            "target_belief_id": belief_id,
                            "requires_epistemic_output": True,
                            "claim": belief.claim,
                            "posterior": belief.posterior_probability,
                            "evidence_for": len(belief.evidence_for),
                            "evidence_against": len(belief.evidence_against),
                            "relationship_count": len(
                                unc.forward_edges.get(belief_id, set())
                            ),
                        },
                    ))
        except Exception as e:
            logger.warning(
                f"EpistemicEngine.get_unstable_regions (beliefs): {e}"
            )

        # -- Stalled hypotheses --------------------------------------------
        try:
            from core.reasoning.hypothesis_testing import HypothesisStatus
            hyp_sys = self._hypothesis_sys()
            stalled_statuses = {
                HypothesisStatus.PROPOSED,
                HypothesisStatus.INCONCLUSIVE,
            }
            now = datetime.now()
            stagnation_cutoff = now - timedelta(hours=STAGNATION_HOURS)

            for hyp in hyp_sys.hypotheses.values():
                if hyp.status not in stalled_statuses:
                    continue

                evidence_count = (
                    len(hyp.supporting_evidence) + len(hyp.contradicting_evidence)
                )
                # Only target if old enough AND lacking evidence
                is_stale = (
                    hyp.proposed_at < stagnation_cutoff
                    and evidence_count < EVIDENCE_MINIMUM
                )
                if not is_stale:
                    continue

                entropy = self._hyp_entropy(hyp)
                targets.append(EpistemicTarget(
                    target_id=hyp.hypothesis_id,
                    target_type="hypothesis",
                    entropy=entropy,
                    description=(
                        f"Generate falsifiable predictions and test "
                        f"hypothesis: {hyp.claim}"
                    ),
                    domain=hyp.domain,
                    metadata={
                        "target_hypothesis_id": hyp.hypothesis_id,
                        "requires_epistemic_output": True,
                        "claim": hyp.claim,
                        "status": hyp.status.value,
                        "supporting_evidence": len(hyp.supporting_evidence),
                        "contradicting_evidence": len(hyp.contradicting_evidence),
                        "hours_stale": (now - hyp.proposed_at).total_seconds() / 3600,
                    },
                ))
        except Exception as e:
            logger.warning(
                f"EpistemicEngine.get_unstable_regions (hypotheses): {e}"
            )

        targets.sort(key=lambda t: t.entropy, reverse=True)
        return targets


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[EpistemicEngine] = None


def get_epistemic_engine() -> EpistemicEngine:
    """Get or create the global EpistemicEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = EpistemicEngine()
    return _engine_instance


# Entropy delta that counts as a "full" unit of epistemic movement. Deltas are
# summed then saturated against this, so a burst of tiny corroborations cannot
# masquerade as a discovery.
EPISTEMIC_SATURATION = 1.0


def _saturate(total: float, scale: float = EPISTEMIC_SATURATION) -> float:
    """Map an unbounded non-negative magnitude into [0,1), saturating."""
    if total <= 0.0:
        return 0.0
    return 1.0 - math.exp(-total / max(scale, 1e-9))


def summarize_epistemic_mutations(
    mutations: Optional[List[EpistemicMutation]],
) -> Dict[str, Any]:
    """Derive curiosity-grade signals from raw epistemic mutations.

    The engine owns what a mutation MEANS. Handing a bare count to the reward
    layer would force it to re-invent that interpretation — a second, divergent
    reading of one observation. This is the single conversion point.

    Returned signals:
      information_gain       new structure created (beliefs/hypotheses) + movement
      uncertainty_reduction  entropy actually removed (sum of positive deltas)
      uncertainty_increase   entropy added — evidence contradicting current model
      contradiction_introduced  alias of uncertainty_increase, named for appraisal
      mutation_count         raw count, for auditing

    NOT derivable here and deliberately absent: `contradiction_resolved`. That
    requires knowing a belief was previously contested, which EpistemicMutation
    does not carry. Reporting it would mean inventing it.
    """
    summary: Dict[str, Any] = {
        "information_gain": 0.0,
        "uncertainty_reduction": 0.0,
        "uncertainty_increase": 0.0,
        "contradiction_introduced": 0.0,
        "mutation_count": 0,
        "unavailable": ["contradiction_resolved"],
    }
    if not mutations:
        return summary

    positive = 0.0   # entropy removed
    negative = 0.0   # entropy added
    structural = 0   # genuinely new beliefs/hypotheses

    for m in mutations:
        try:
            delta = float(getattr(m, "delta", 0.0) or 0.0)
            mtype = getattr(m, "mutation_type", "")
        except (TypeError, ValueError):
            continue
        if delta > 0:
            positive += delta
        elif delta < 0:
            negative += -delta
        if mtype in ("new_belief", "new_hypothesis"):
            structural += 1

    summary["mutation_count"] = len(mutations)
    summary["uncertainty_reduction"] = _saturate(positive)
    summary["uncertainty_increase"] = _saturate(negative)
    summary["contradiction_introduced"] = summary["uncertainty_increase"]
    # New structure and resolved uncertainty are both real learning; a belief
    # that got LESS certain still taught the system something, so magnitude —
    # not sign — drives information gain.
    summary["information_gain"] = _saturate(positive + negative + float(structural))
    return summary


# Canonical claim -> outcome-quality signal. The claims are authored in
# interpret_tool_output(); this mapping lives beside them so the vocabulary has
# exactly one owner. ExperienceEvaluator must never re-derive these from raw
# tool text.
_QUALITY_CLAIMS = {
    "the task's test suite passes": "tests_passed",
    "the code is free of reported lint errors": "lint_passed",
    "task changes have been applied to disk": "clean_patch",
}


def summarize_tool_observations(
    observations: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Convert canonical belief updates into outcome-quality signals.

    THREE-VALUED, deliberately. A key is present only when an observation
    actually licenses the claim:

        SUPPORTS -> True      WEAKENS -> False      no observation -> ABSENT

    Absent is not False. The substring heuristics this replaces could not say
    "unknown": empty lint output read as clean, a no-op patch read as a real
    change, and "3 failed, 1 passed" read as passing because it contains
    "passed". Callers should test `is True` / `is False` and treat a missing key
    as unmeasured.
    """
    summary: Dict[str, Any] = {"unknown": sorted(set(_QUALITY_CLAIMS.values()))}
    if not observations:
        return summary

    for obs in observations:
        if not isinstance(obs, dict):
            continue
        key = _QUALITY_CLAIMS.get(obs.get("claim"))
        if key is None:
            continue
        supports = obs.get("relation") == "SUPPORTS"
        # Contradicting observations within one task: a later WEAKENS wins, so a
        # suite that passed then failed is not reported as passing.
        if key in summary and summary[key] is False:
            continue
        summary[key] = supports

    summary["unknown"] = sorted(
        v for v in set(_QUALITY_CLAIMS.values()) if v not in summary
    )
    return summary
