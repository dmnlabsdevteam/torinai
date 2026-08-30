#!/usr/bin/env python3
"""
Causal Traceability Gate  (v2)
===============================

Every claimed artifact must have a verifiable causal chain:

    tool_call ──writes──► artifact ──read_by──► downstream_tool (optional)

Formally:
    ∀ claimed artifact A:
        ∃ tool_call T  such that T produced A   (filesystem evidence required)
        ∃ tool_output O such that O supports A   (stdout alone is not sufficient)

Design principles (addresses 9 identified weaknesses):
    1. Weak links require filesystem verification (mtime >= tool timestamp).
       "print('model.py created')" → stdout alone → rejected as weak link.
    2. Downstream usage is tracked: artifact written but never consumed → warning.
    3. Full provenance graph is built: Tool → Artifact → Tool.
    4. Path normalization via os.path.realpath() before all hash lookups.
    5. Filesystem evidence is authoritative; stdout is corroborating only.
    6. Score = strong_links / total_artifacts.  Weak links do NOT contribute to
       score.  Multiple weak links cannot inflate score above 0.
    7. Hard fail: weak candidate demoted to none if file not on disk or
       file mtime predates the tool call timestamp.

Hard failures (block VERIFIED):
    EXECUTION / SECURITY_REMEDIATION tasks:
      - Any claimed artifact with link_strength == "none"
      - Any weak link that fails filesystem verification (demoted to none)
      - agent-provided artifact_hashes that don't match actual disk content
    All tasks:
      - hash mismatch between claimed and actual content

Warnings (non-blocking):
    - Weak causal links (basename evidence, no exact path match)
    - Artifacts that exist and are causally linked but never used downstream
    - RESEARCH / ANALYSIS tasks with untraced artifacts
"""

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Tool categories
_WRITE_TOOLS = {"write_file", "create_file"}
_CODE_TOOLS  = {"run_python", "run_shell_command", "execute_command", "run_script"}
_READ_TOOLS  = {"read_file", "run_python", "run_shell_command", "execute_command", "run_script"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CausalLink:
    """
    Verified causal link between an artifact and the tool call that produced it.

    link_strength values:
        "strong" — write_file/create_file with exact normalized path match
                   AND file exists on disk at verification time
        "weak"   — code tool with basename mention in params/output AND
                   file confirmed on disk with mtime >= tool call time
        "none"   — no verifiable connection (untraced)

    NOTE: A "weak" candidate that fails mtime/existence check is demoted to "none".
    Stdout mentions alone (e.g. echo / print statements) are NEVER sufficient for
    a weak link — the file must independently exist on disk.
    """
    artifact_path: str
    artifact_realpath: str = ""             # os.path.realpath(artifact_path)
    producing_tool: Optional[str] = None
    tool_call_index: int = -1
    tool_call_timestamp: Optional[float] = None  # epoch seconds from tool_result
    link_strength: str = "none"             # "strong" | "weak" | "none"
    file_exists: bool = False
    file_mtime: Optional[float] = None
    mtime_verified: Optional[bool] = None   # True if mtime >= tool_call_timestamp
    content_hash_on_disk: Optional[str] = None
    content_hash_claimed: Optional[str] = None
    hash_match: Optional[bool] = None
    untraced: bool = True
    used_by: List[int] = field(default_factory=list)  # indices of downstream tool calls

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact":          self.artifact_path,
            "producing_tool":    self.producing_tool,
            "tool_call_index":   self.tool_call_index,
            "link_strength":     self.link_strength,
            "file_exists":       self.file_exists,
            "file_mtime":        self.file_mtime,
            "mtime_verified":    self.mtime_verified,
            "hash_on_disk":      (self.content_hash_on_disk[:16] + "...") if self.content_hash_on_disk else None,
            "hash_claimed":      (self.content_hash_claimed[:16] + "...") if self.content_hash_claimed else None,
            "hash_match":        self.hash_match,
            "untraced":          self.untraced,
            "used_by_tools":     self.used_by,
        }


@dataclass
class ProvenanceNode:
    """Node in the provenance graph — either a tool call or an artifact."""
    node_type: str          # "tool" | "artifact"
    label: str              # tool name or artifact basename
    index: int              # tool_results index or link index


@dataclass
class ProvenanceEdge:
    """Directed edge in the provenance graph."""
    src: ProvenanceNode
    dst: ProvenanceNode
    edge_type: str          # "writes" | "reads"


@dataclass
class ProvenanceGraph:
    """Full causal graph: ToolCall → Artifact → ToolCall."""
    nodes: List[ProvenanceNode] = field(default_factory=list)
    edges: List[ProvenanceEdge] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        tool_nodes     = [n for n in self.nodes if n.node_type == "tool"]
        artifact_nodes = [n for n in self.nodes if n.node_type == "artifact"]
        write_edges    = [e for e in self.edges if e.edge_type == "writes"]
        read_edges     = [e for e in self.edges if e.edge_type == "reads"]
        return {
            "tool_nodes":      len(tool_nodes),
            "artifact_nodes":  len(artifact_nodes),
            "write_edges":     len(write_edges),
            "read_edges":      len(read_edges),
            "chains":          self._count_chains(),
        }

    def _count_chains(self) -> int:
        """Count artifact nodes that have both an inbound write and outbound read."""
        artifacts_written = {
            e.dst.index for e in self.edges if e.edge_type == "writes"
        }
        artifacts_read = {
            e.src.index for e in self.edges if e.edge_type == "reads"
        }
        return len(artifacts_written & artifacts_read)


@dataclass
class CausalTraceResult:
    """Aggregated result from the causal traceability gate."""
    passed: bool
    score: float
    hard_failures: List[str]       = field(default_factory=list)
    warnings: List[str]            = field(default_factory=list)
    causal_links: List[CausalLink] = field(default_factory=list)
    graph: Optional[ProvenanceGraph] = None
    detail: Dict[str, Any]         = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class CausalTraceabilityGate:
    """
    Causal traceability verification (v2).

    Stateless — every verify() call is independent.

    The `proposal` argument is duck-typed to avoid circular imports.
    Expected attributes:
        proposal.files_created   : List[str]
        proposal.files_modified  : List[str]
        proposal.artifact_hashes : Dict[str, str]   (path → sha256hex)
        proposal.summary         : str
        proposal.claimed_outputs : Dict[str, Any]
    """

    def __init__(self, workspace_root: str = "/Users/stefan/Dominion Labs/TorinAI"):
        self.workspace_root = workspace_root

    # =========================================================================
    # Public entry point
    # =========================================================================

    def verify(
        self,
        proposal: Any,
        task_type: str,
        tool_results: List[Dict[str, Any]],
    ) -> "CausalTraceResult":
        """Verify causal traceability for all claimed artifacts."""
        is_impl_task = task_type.upper() in ("EXECUTION", "SECURITY_REMEDIATION")

        claimed_files = self._get_claimed_files(proposal)
        # Normalize all claimed hash keys to realpath immediately (fix #4)
        artifact_hashes_claimed: Dict[str, str] = self._normalize_hash_keys(
            getattr(proposal, "artifact_hashes", None) or {}
        )

        if not claimed_files and not is_impl_task:
            return CausalTraceResult(
                passed=True, score=1.0,
                detail={"note": "no non-report artifacts to trace"},
            )

        # Build causal links (filesystem evidence required, not just stdout)
        links = self._build_causal_links(
            claimed_files, artifact_hashes_claimed, tool_results
        )

        # Detect downstream artifact usage and build provenance graph
        graph = self._build_provenance_graph(links, tool_results)

        hard_failures: List[str] = []
        warnings: List[str] = []

        # ── Rule 1: untraced / demoted artifacts ─────────────────────────────
        for lk in links:
            if lk.untraced:
                msg = (
                    f"No causal trace: '{lk.artifact_path}' has no verified "
                    "tool call that produced it (stdout-only mentions are rejected)"
                )
                if is_impl_task:
                    hard_failures.append(msg)
                else:
                    warnings.append(msg)

        # ── Rule 2: hash mismatches ───────────────────────────────────────────
        for lk in links:
            if lk.hash_match is False:
                hard_failures.append(
                    f"Hash mismatch for '{lk.artifact_path}': "
                    f"agent claimed {(lk.content_hash_claimed or '')[:16]}... "
                    f"but disk SHA256 is {(lk.content_hash_on_disk or '')[:16]}... — "
                    "file content does not match completion-time claim"
                )

        # ── Rule 3: weak links (non-blocking, score penalty via scoring rule) ─
        for lk in links:
            if lk.link_strength == "weak":
                warnings.append(
                    f"Weak causal link for '{lk.artifact_path}': "
                    f"basename matched in {lk.producing_tool} output "
                    f"(file confirmed on disk, mtime_verified={lk.mtime_verified})"
                )

        # ── Rule 4: artifacts written but never consumed ──────────────────────
        for lk in links:
            if lk.link_strength == "strong" and not lk.used_by:
                warnings.append(
                    f"Artifact '{lk.artifact_path}' was written (strong link) "
                    "but never read by any downstream tool call — it may be unused"
                )

        # ── Rule 5: orphan execution ──────────────────────────────────────────
        if is_impl_task and claimed_files:
            code_calls_success = [
                i for i, r in enumerate(tool_results)
                if r.get("tool") in _CODE_TOOLS and r.get("success")
            ]
            if code_calls_success:
                connected = {
                    lk.tool_call_index for lk in links if lk.tool_call_index >= 0
                }
                all_disconnected = all(i not in connected for i in code_calls_success)
                no_verified_link = not any(
                    lk.link_strength in ("strong", "weak") for lk in links
                )
                if all_disconnected and no_verified_link:
                    warnings.append(
                        f"{len(code_calls_success)} code tool call(s) ran but none "
                        "are causally connected to any claimed artifact — "
                        "execution appears unrelated to claimed implementation"
                    )

        # ── Score: strong_links / total_artifacts  (fix #6) ──────────────────
        # Weak links deliberately excluded from numerator — they are warnings,
        # not verified proof. A weak link contributes 0 to score.
        if links:
            strong_count = sum(
                1 for lk in links
                if lk.link_strength == "strong" and lk.hash_match is not False
            )
            score = strong_count / len(links)
        else:
            score = 1.0 if not is_impl_task else 0.5

        passed = len(hard_failures) == 0

        if hard_failures:
            logger.warning("[CAUSAL] %d hard failure(s): %s", len(hard_failures), hard_failures[:2])
        if warnings:
            logger.info("[CAUSAL] %d warning(s): %s", len(warnings), warnings[:2])

        return CausalTraceResult(
            passed=passed,
            score=score,
            hard_failures=hard_failures,
            warnings=warnings,
            causal_links=links,
            graph=graph,
            detail={
                "total_artifacts": len(claimed_files),
                "strong_links":    sum(1 for lk in links if lk.link_strength == "strong"),
                "weak_links":      sum(1 for lk in links if lk.link_strength == "weak"),
                "untraced":        sum(1 for lk in links if lk.untraced),
                "hash_mismatches": sum(1 for lk in links if lk.hash_match is False),
                "provenance":      graph.summary(),
                "links":           [lk.to_dict() for lk in links],
            },
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_claimed_files(self, proposal: Any) -> List[str]:
        """Collect all non-report claimed files from the proposal."""
        seen: Dict[str, None] = {}
        for attr in ("files_created", "files_modified"):
            for p in (getattr(proposal, attr, None) or []):
                if not isinstance(p, str) or not p:
                    continue
                if "output-file" in p or "CloudDocs" in p:
                    continue
                seen[p] = None
        return list(seen)

    def _normalize_hash_keys(self, raw: Dict[str, str]) -> Dict[str, str]:
        """
        Re-key the agent-supplied hash dict using os.path.realpath.
        Fixes: ./file.py vs file.py vs /abs/path/file.py all map to the same key.
        """
        out: Dict[str, str] = {}
        for k, v in raw.items():
            try:
                rp = os.path.realpath(
                    k if os.path.isabs(k) else os.path.join(self.workspace_root, k)
                )
                out[rp] = v
            except Exception:
                out[k] = v
        return out

    def _build_causal_links(
        self,
        claimed_files: List[str],
        artifact_hashes_claimed: Dict[str, str],  # keys are realpaths
        tool_results: List[Dict[str, Any]],
    ) -> List["CausalLink"]:
        """
        Build one CausalLink per claimed file.

        Link strength rules:
            strong — write_file/create_file with exact normalized path + file exists
            weak   — code tool with basename in params/output AND file exists AND
                     file mtime >= tool call timestamp (fix #1 and #5)
            none   — anything else, including stdout-only mentions without disk proof

        Filesystem evidence is always the ground truth.  Stdout alone is never
        sufficient for a weak link (fixes #5 — no trusting tool stdout).
        """
        links: List[CausalLink] = []

        for path in claimed_files:
            realpath = os.path.realpath(
                path if os.path.isabs(path)
                else os.path.join(self.workspace_root, path)
            )
            basename = os.path.basename(path).lower()

            lk = CausalLink(artifact_path=path, artifact_realpath=realpath)

            # ── Disk state (authoritative) ────────────────────────────────────
            lk.file_exists = os.path.exists(realpath)
            if lk.file_exists:
                try:
                    lk.file_mtime = os.path.getmtime(realpath)
                except OSError:
                    pass
                lk.content_hash_on_disk = self._hash_file(realpath)

            # ── Claimed hash verification (fix #4 — normalized key lookup) ───
            claimed_hash = artifact_hashes_claimed.get(realpath)
            if claimed_hash:
                lk.content_hash_claimed = claimed_hash
                if lk.content_hash_on_disk is not None:
                    lk.hash_match = (lk.content_hash_on_disk == claimed_hash)

            # ── Find best tool call link ──────────────────────────────────────
            best_strength = "none"
            best_idx = -1
            best_tool: Optional[str] = None
            best_ts: Optional[float] = None

            for i, r in enumerate(tool_results):
                if not r.get("success"):
                    continue
                tool_name: str = r.get("tool", "")
                params = r.get("parameters") or {}
                # Tool timestamp (epoch seconds). Callers should populate this;
                # fall back to None if absent so we can still do the disk check.
                tool_ts: Optional[float] = r.get("timestamp") or r.get("started_at")

                if tool_name in _WRITE_TOOLS:
                    # Strong candidate: exact normalized path match + file on disk
                    written_path_raw = str(params.get("path", ""))
                    written_real = os.path.realpath(
                        written_path_raw if os.path.isabs(written_path_raw)
                        else os.path.join(self.workspace_root, written_path_raw)
                    )
                    if written_real == realpath and lk.file_exists:
                        best_strength = "strong"
                        best_idx = i
                        best_tool = tool_name
                        best_ts = tool_ts
                        break  # can't do better

                elif tool_name in _CODE_TOOLS and best_strength != "strong":
                    # Weak candidate:
                    #   a) file must exist on disk (stdout alone is not enough)
                    #   b) basename (or full path) must appear in params or output
                    #   c) file mtime must be >= tool call timestamp if available
                    if not lk.file_exists:
                        continue  # (fix #5) reject stdout-only claims

                    output    = str(r.get("output", "") or "")
                    param_str = str(params).lower()
                    out_lower = output.lower()
                    path_mentioned = (
                        basename in out_lower
                        or basename in param_str
                        or path in output
                        or realpath in output
                    )
                    if not path_mentioned:
                        continue

                    # mtime gate (fix #1)
                    if tool_ts is not None and lk.file_mtime is not None:
                        if lk.file_mtime < tool_ts:
                            # File predates this tool call — it was pre-existing
                            continue
                    # Accept as weak (keep looking for strong)
                    best_strength = "weak"
                    best_idx = i
                    best_tool = tool_name
                    best_ts = tool_ts

            lk.producing_tool = best_tool
            lk.tool_call_index = best_idx
            lk.tool_call_timestamp = best_ts
            lk.link_strength = best_strength
            lk.untraced = (best_strength == "none")

            # mtime_verified flag for diagnostics
            if best_strength == "weak" and best_ts is not None and lk.file_mtime is not None:
                lk.mtime_verified = (lk.file_mtime >= best_ts)
            elif best_strength == "strong":
                lk.mtime_verified = True  # write_file guarantees causality

            links.append(lk)

        return links

    def _build_provenance_graph(
        self,
        links: List["CausalLink"],
        tool_results: List[Dict[str, Any]],
    ) -> ProvenanceGraph:
        """
        Build a full Tool → Artifact → Tool provenance graph.

        For each link that has a producing tool:
            ToolNode(producing_tool, index) ──writes──► ArtifactNode(path, link_idx)

        Then scan ALL subsequent tool calls for reads of each artifact:
            ArtifactNode ──reads──► ToolNode(consumer, j)

        Fixes #2 (artifact usage tracking) and #3 (provenance graph).
        """
        graph = ProvenanceGraph()
        artifact_nodes: Dict[int, ProvenanceNode] = {}  # link_idx → node

        # Phase 1: write edges
        for link_idx, lk in enumerate(links):
            if lk.link_strength == "none":
                continue
            art_node = ProvenanceNode(
                node_type="artifact",
                label=os.path.basename(lk.artifact_path),
                index=link_idx,
            )
            artifact_nodes[link_idx] = art_node
            graph.nodes.append(art_node)

            tool_node = ProvenanceNode(
                node_type="tool",
                label=lk.producing_tool or "unknown",
                index=lk.tool_call_index,
            )
            # Deduplicate tool nodes by index
            existing = next(
                (n for n in graph.nodes if n.node_type == "tool" and n.index == lk.tool_call_index),
                None,
            )
            if existing is None:
                graph.nodes.append(tool_node)
                existing = tool_node
            graph.edges.append(ProvenanceEdge(src=existing, dst=art_node, edge_type="writes"))

        # Phase 2: read edges (downstream usage)
        for link_idx, lk in enumerate(links):
            if link_idx not in artifact_nodes:
                continue
            art_node = artifact_nodes[link_idx]
            basename_lower = os.path.basename(lk.artifact_path).lower()

            # Only consider tool calls AFTER the producing call
            start_from = lk.tool_call_index + 1
            for j in range(start_from, len(tool_results)):
                r = tool_results[j]
                if not r.get("success"):
                    continue
                tool_name = r.get("tool", "")
                if tool_name not in _READ_TOOLS:
                    continue
                params = r.get("parameters") or {}
                param_str = str(params).lower()
                output_str = str(r.get("output", "") or "").lower()
                if (
                    basename_lower in param_str
                    or lk.artifact_path in str(params)
                    or lk.artifact_realpath in str(params)
                    or basename_lower in output_str
                ):
                    lk.used_by.append(j)
                    consumer_node = ProvenanceNode(
                        node_type="tool", label=tool_name, index=j
                    )
                    existing = next(
                        (n for n in graph.nodes if n.node_type == "tool" and n.index == j),
                        None,
                    )
                    if existing is None:
                        graph.nodes.append(consumer_node)
                        existing = consumer_node
                    graph.edges.append(
                        ProvenanceEdge(src=art_node, dst=existing, edge_type="reads")
                    )

        return graph

    @staticmethod
    def _hash_file(path: str) -> Optional[str]:
        """SHA256 of file contents. Returns None on I/O error."""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None
