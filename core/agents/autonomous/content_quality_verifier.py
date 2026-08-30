#!/usr/bin/env python3
"""
Content Quality Verification Layer
====================================

Detects hollow, fabricated, or low-effort task outputs that pass structural
checks but contain no real substance. Sits at Layer 5.5 in the verification
pipeline — after reality checks (environment truth) and before acceptance
criteria (field presence).

Problem it solves:
  The LLM can satisfy file-existence checks, section-header checks, and
  minimum word-count checks while producing a document that is entirely
  generic hallucination, full of placeholder text, and contains no findings
  from the actual research tools it called.

Verification checks:
  1. PlaceholderDetection    — [URL to ...], X kilometers, TODO, TBD, etc.
  2. DuplicateSections       — same header twice (file-append bug)
  3. StubSections            — headers with only short bullets, no prose
  4. ToolGrounding           — web_search/fetch_page findings must appear in doc
  5. GenericContent          — paragraphs with zero specificity (soft)
  6. TaskSpecificChecks      — per-type quality signals

Failure semantics:
  hard_failures — provably hollow: each added to hard_gate_failures, blocks VERIFIED
  warnings      — quality concerns: recorded in issues, non-blocking

Hard failures:
  - ALL tasks:              placeholder text found in document
  - ALL tasks:              duplicate section headers (file appended, not rewritten)
  - RESEARCH (>50% stubs):  majority of sections have no prose
  - RESEARCH/ANALYSIS/SEC:  web_search returned data but <10% appears in doc
  - SECURITY_REMEDIATION:   no CVE IDs, file paths, or config changes documented
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Compiled patterns — module-level for performance
# ---------------------------------------------------------------------------

# Placeholder patterns: (compiled_re, is_hard_failure)
_PLACEHOLDER_PATTERNS: List[Tuple[re.Pattern, bool]] = [
    # Bracketed: [URL to ...], [INSERT ...], [citation needed], [source]
    (
        re.compile(
            r'\[(?:URL\s+to\b|INSERT\b|FILL\s+IN\b|ADD\s+HERE\b|PLACEHOLDER\b|'
            r'TODO\b|TBD\b|citation\s+needed|your\s+[^\]]{0,40}|'
            r'reference\s+here|link\s+here|see\s+here|source)[^\]]{0,80}\]',
            re.IGNORECASE,
        ),
        True,
    ),
    # Angle-bracket stubs: <placeholder>, <insert here>, <your content>
    (
        re.compile(
            r'<(?:placeholder|insert\s+here|your[^>]{0,30}|fill[^>]{0,30}|todo|tbd)>',
            re.IGNORECASE,
        ),
        True,
    ),
    # Single uppercase letter + unit: "X kilometers", "Y meters", "N items"
    (
        re.compile(
            r'\b([A-Z])\s+(?:kilometer|meter|mile|foot|feet|pound|kilogram|'
            r'unit|item|percent|hour|day|week|month|year|dollar|byte|watt|volt|'
            r'kelvin|degree)s?\b',
        ),
        True,
    ),
    # Variable ranges: "A to B degrees", "X to Y kilometers"
    (
        re.compile(
            r'\b([A-Z])\s+to\s+([A-Z])\s+(?:degree|meter|kilometer|percent|unit)s?\b',
        ),
        True,
    ),
    # Prose stubs
    (re.compile(r'\b(?:TODO|TBD|FIXME|PLACEHOLDER|INSERT\s+HERE|FILL\s+IN)\b'), True),
    # "(details to be added)" phrasing
    (
        re.compile(
            r'\((?:details|content|information|data|results?)\s+to\s+be\s+'
            r'(?:added|filled|inserted|provided)\)',
            re.IGNORECASE,
        ),
        True,
    ),
    # Standalone bracket citations in prose (not already caught above)
    (
        re.compile(r'\[(?:source|reference|citation|link|see\s+here)\]', re.IGNORECASE),
        True,
    ),
]

# Markdown header extractor
_RE_MD_HEADER = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)

# Research tool names whose outputs must be grounded in the document
_RESEARCH_TOOLS = frozenset({
    "web_search", "fetch_page", "http_request", "conduct_research",
})

# Task types that require tool grounding checks
_GROUNDING_TASK_TYPES = frozenset({"RESEARCH", "ANALYSIS", "SECURITY_REMEDIATION"})

# Stopwords excluded from word-level grounding fallback matching.
# These are so generic that finding them in a document proves nothing.
_GROUNDING_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can",
    "more", "most", "some", "any", "all", "this", "that", "these", "those",
    "its", "their", "our", "your", "his", "her", "we", "they", "it",
    "not", "no", "nor", "so", "yet", "both", "either", "neither",
    "new", "old", "key", "main", "major", "top", "big", "large", "small",
    "advanced", "modern", "latest", "recent", "current", "future", "next",
    "first", "second", "third", "last", "into", "about", "than", "then",
    "when", "what", "which", "who", "how", "why", "where",
    "becomes", "become", "becoming", "making", "makes", "made",
    "using", "uses", "used", "times", "time", "way", "ways",
    "year", "years", "day", "days", "world", "global", "international",
    "based", "including", "include", "provides", "provide",
})

# Named entity extractor: multi-word capitalized phrases
_RE_CAPITALIZED_PHRASE = re.compile(r'(?:[A-Z][a-z]{2,}\s+){1,3}[A-Z][a-z]{2,}')

# Numbers with optional units
_RE_NUMBER_WITH_UNIT = re.compile(
    r'\b\d[\d,.]*\s*'
    r'(?:%|billion|million|trillion|thousand|GB|TB|MB|KB|ms|'
    r'seconds?|minutes?|hours?|days?|years?|km|kg|GHz|MHz)?\b'
)

# Quoted strings from research output
_RE_QUOTED = re.compile(r'"([^"]{5,80})"')

# Month+year temporal references
_RE_MONTH_YEAR = re.compile(
    r'\b(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s+\d{4}\b'
)

# Technical acronyms (3-6 uppercase letters)
_RE_ACRONYM = re.compile(r'\b[A-Z]{3,6}\b')

# URLs appearing in document text
_RE_URL_IN_TEXT = re.compile(r'https?://\S+')

# Generic, ungrounded hedge language
_RE_GENERIC_HEDGE = re.compile(
    r'\b(?:this technology|this approach|this method|this system|'
    r'this solution|this framework|this concept|this tool|this platform|'
    r'it is (?:important|worth noting|well known|clear that|evident)|'
    r'research shows|studies have shown|experts believe|'
    r'in general|generally speaking|as we know|it is widely|'
    r'one of the most|highly advanced|cutting.edge|state.of.the.art|'
    r'leverages? (?:emerging|advanced|cutting.edge|novel))\b',
    re.IGNORECASE,
)

# Specificity signals that redeem a generic paragraph
_RE_SPECIFICITY = re.compile(
    r'\b(?:\d[\d,.]+|CVE-\d{4}-\d+|'
    r'Figure\s+\d|Table\s+\d|Section\s+\d|Algorithm\s+\d|Appendix\s+[A-Z]|'
    r'percent|million|billion|ms|GHz|GB|TB)\b',
    re.IGNORECASE,
)

# Common English uppercase words to exclude from acronym extraction
_COMMON_UPPERCASE = frozenset({
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN",
    "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM",
    "HIS", "HOW", "ITS", "NOW", "OLD", "SEE", "TWO", "WHO", "DID",
    "YES", "YET", "USE", "TOO", "NEW", "WITH", "FROM", "THIS", "THAT",
    "THEY", "BEEN", "HAVE", "WILL", "WOULD", "COULD", "SHOULD", "WHICH",
})


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ContentQualityResult:
    """
    Aggregated result from all content quality checks.

    passed        — False if any hard_failure is present
    score         — 0.0–1.0, blended into validation_score in completion_protocol
    hard_failures — provably hollow content; each becomes a hard_gate_failure
    warnings      — quality concerns; recorded in issues, non-blocking
    detail        — per-check breakdown dict for logging
    """
    passed: bool
    score: float
    hard_failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main verifier class
# ---------------------------------------------------------------------------

class ContentQualityVerifier:
    """
    Content Quality Verification Layer — document substance checks.

    Stateless: every verify() call is independent.
    Duck-typed on proposal to avoid circular imports.

    Expected proposal attributes (all optional — graceful if absent):
        proposal.sources_consulted : List[str]
        proposal.key_findings      : List[str] | str
        proposal.summary           : str
        proposal.files_created     : List[str]
        proposal.files_modified    : List[str]
    """

    def __init__(self, workspace_root: str = "/Users/stefan/Dominion Labs/TorinAI"):
        self.workspace_root = workspace_root

    # =========================================================================
    # Public entry point
    # =========================================================================

    async def verify(
        self,
        proposal: Any,
        task_description: str,
        task_type: str,
        tool_results: List[Dict[str, Any]],
        output_doc_paths: Optional[List[str]] = None,
    ) -> ContentQualityResult:
        """
        Run all content quality checks and return aggregated result.

        Parameters
        ----------
        proposal         : CompletionProposal (duck-typed)
        task_description : original task description string
        task_type        : TaskType name e.g. "RESEARCH", "EXECUTION"
        tool_results     : list of tool call records from executor
                           schema: {"tool": str, "parameters": dict,
                                    "success": bool, "output": str|dict}
        output_doc_paths : paths to documents written during the task
        """
        task_upper = (task_type or "UNKNOWN").upper()
        doc_paths = list(output_doc_paths or [])

        # Also include files from proposal fields as candidate doc paths
        for attr in ("files_created", "files_modified"):
            for p in (getattr(proposal, attr, None) or []):
                if isinstance(p, str) and p and p not in doc_paths:
                    doc_paths.append(p)

        doc_texts = self._read_doc_texts(doc_paths)

        hard_failures: List[str] = []
        warnings: List[str] = []
        detail: Dict[str, Any] = {}
        scores: List[float] = []

        # ── Check 0: Minimum document length (hard gate) ───────────────────
        # A one-page stub is not an acceptable research/synthesis output.
        # Count words across all document text (exclude markdown headers/bullets).
        _MIN_WORDS_RESEARCH = 2500  # hard gate for RESEARCH/SYNTHESIS tasks
        _MIN_WORDS_SOFT     = 400   # warning for all other tasks
        _all_doc_text = "\n".join(doc_texts)
        # Strip markdown headers, bullet leaders, and code fences for word count
        import re as _re_wc
        _prose_text = _re_wc.sub(r'^#+\s.*$', '', _all_doc_text, flags=_re_wc.MULTILINE)
        _prose_text = _re_wc.sub(r'^[-*>\s]+', '', _prose_text, flags=_re_wc.MULTILINE)
        _prose_text = _re_wc.sub(r'```.*?```', '', _prose_text, flags=_re_wc.DOTALL)
        _word_count = len(_prose_text.split())
        detail["word_count"] = _word_count

        if doc_texts and task_upper in ("RESEARCH", "SYNTHESIS", "ANALYSIS"):
            if _word_count < _MIN_WORDS_RESEARCH:
                hard_failures.append(
                    f"Document too short: {_word_count} words of prose. "
                    f"A {task_upper} task requires at least {_MIN_WORDS_RESEARCH} words of "
                    f"substantive content. The current document is a shallow stub — rewrite it "
                    f"with full paragraphs, specific findings from your research, named sources, "
                    f"and depth in every section. This is not a bullet-point summary; it is a "
                    f"professional technical document."
                )
                scores.append(0.0)
            elif _word_count < _MIN_WORDS_RESEARCH * 2:
                warnings.append(
                    f"Document is short ({_word_count} words) — consider expanding with more "
                    f"depth, analysis, and source-grounded detail."
                )
                scores.append(0.7)
            else:
                scores.append(1.0)
        elif doc_texts and _word_count < _MIN_WORDS_SOFT:
            warnings.append(
                f"Document is very short ({_word_count} words) — may lack sufficient depth."
            )
            scores.append(0.7)

        # ── Check 1: Placeholder text ──────────────────────────────────────
        ph_score, ph_hard, ph_warn, ph_detail = self._check_placeholder_text(doc_texts)
        scores.append(ph_score)
        hard_failures.extend(ph_hard)
        warnings.extend(ph_warn)
        detail["placeholder_text"] = ph_detail

        # ── Check 2: Duplicate sections ────────────────────────────────────
        dup_score, dup_hard, dup_warn, dup_detail = self._check_duplicate_sections(doc_texts)
        scores.append(dup_score)
        hard_failures.extend(dup_hard)
        warnings.extend(dup_warn)
        detail["duplicate_sections"] = dup_detail

        # ── Check 3: Stub-only sections ────────────────────────────────────
        stub_score, stub_hard, stub_warn, stub_detail = self._check_stub_sections(
            doc_texts, task_upper
        )
        scores.append(stub_score)
        hard_failures.extend(stub_hard)
        warnings.extend(stub_warn)
        detail["stub_sections"] = stub_detail

        # ── Check 4: Tool grounding (research-type tasks only) ─────────────
        if task_upper in _GROUNDING_TASK_TYPES:
            gr_score, gr_hard, gr_warn, gr_detail = self._check_tool_grounding(
                tool_results, doc_texts, task_upper
            )
            scores.append(gr_score)
            hard_failures.extend(gr_hard)
            warnings.extend(gr_warn)
            detail["tool_grounding"] = gr_detail

        # ── Check 5: Generic / ungrounded paragraphs (always soft) ─────────
        gen_score, _, gen_warn, gen_detail = self._check_generic_content(doc_texts)
        scores.append(gen_score)
        warnings.extend(gen_warn)
        detail["generic_content"] = gen_detail

        # ── Check 6: Task-type-specific signals ────────────────────────────
        ts_score, ts_hard, ts_warn, ts_detail = self._check_task_specific(
            doc_texts, tool_results, task_upper, proposal
        )
        scores.append(ts_score)
        hard_failures.extend(ts_hard)
        warnings.extend(ts_warn)
        detail["task_specific"] = ts_detail

        # ── Aggregate ──────────────────────────────────────────────────────
        if not doc_texts:
            warnings.append("No output documents found — content quality could not be checked")
            overall_score = 0.7
        else:
            overall_score = sum(scores) / len(scores) if scores else 1.0

        passed = len(hard_failures) == 0

        if hard_failures:
            logger.warning(
                "[CONTENT_QUALITY] %d hard failure(s): %s",
                len(hard_failures), hard_failures[:3],
            )
        if warnings:
            logger.info(
                "[CONTENT_QUALITY] %d warning(s): %s",
                len(warnings), warnings[:3],
            )
        logger.info(
            "[CONTENT_QUALITY] passed=%s score=%.3f hard=%d warnings=%d docs=%d",
            passed, overall_score, len(hard_failures), len(warnings), len(doc_texts),
        )

        return ContentQualityResult(
            passed=passed,
            score=overall_score,
            hard_failures=hard_failures,
            warnings=warnings,
            detail=detail,
        )

    # =========================================================================
    # Check 1 — Placeholder text
    # =========================================================================

    def _check_placeholder_text(
        self, doc_texts: List[str]
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        hard_failures: List[str] = []
        warnings: List[str] = []
        all_matches: List[Dict[str, Any]] = []

        for doc_idx, raw_text in enumerate(doc_texts):
            # Strip fenced code blocks — code legitimately uses single-letter vars.
            # But keep the bracketed URL patterns even inside code blocks, since
            # [URL to ...] is never valid code.
            text_no_code = re.sub(r'```.*?```', '[CODE_BLOCK]', raw_text, flags=re.DOTALL)
            text_no_code = re.sub(r'`[^`\n]{1,200}`', '[INLINE_CODE]', text_no_code)

            for pattern, is_hard in _PLACEHOLDER_PATTERNS:
                for m in pattern.finditer(text_no_code):
                    line_no = text_no_code[: m.start()].count('\n') + 1
                    all_matches.append({
                        "text": m.group(0)[:80],
                        "line": line_no,
                        "doc": doc_idx,
                        "hard": is_hard,
                    })
                    if len(all_matches) >= 15:
                        break
                if len(all_matches) >= 15:
                    break
            if len(all_matches) >= 15:
                break

        reported = all_matches[:5]
        overflow = len(all_matches) - len(reported)

        for match in reported:
            msg = (
                f"Placeholder text found in document (line {match['line']}): "
                f"\"{match['text']}\""
            )
            if match["hard"]:
                hard_failures.append(msg)
            else:
                warnings.append(msg)

        if overflow > 0:
            hard_failures.append(
                f"...and {overflow} additional placeholder(s) found in document"
            )

        score = max(0.0, 1.0 - 0.2 * len(all_matches)) if all_matches else 1.0
        return score, hard_failures, warnings, {
            "count": len(all_matches),
            "examples": [m["text"] for m in all_matches[:4]],
        }

    # =========================================================================
    # Check 2 — Duplicate sections
    # =========================================================================

    def _check_duplicate_sections(
        self, doc_texts: List[str]
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        hard_failures: List[str] = []
        warnings: List[str] = []
        all_duplicates: List[str] = []

        for text in doc_texts:
            # ── Header duplicates ──────────────────────────────────────────
            headers = _RE_MD_HEADER.findall(text)  # [(level, text), ...]
            seen_headers: Dict[str, int] = {}       # normalized → first occurrence

            for _level, hdr_text in headers:
                norm = self._normalize_header(hdr_text)
                if norm in seen_headers:
                    all_duplicates.append(f"Section header: \"{hdr_text.strip()[:60]}\"")
                else:
                    seen_headers[norm] = 1

            # ── Large content block duplicates ────────────────────────────
            # Sliding 300-char windows at 150-char stride; fingerprint each
            seen_chunks: Dict[str, int] = {}
            stride = 150
            window = 300
            for i in range(0, max(0, len(text) - window), stride):
                chunk = text[i: i + window]
                if len(chunk.strip()) < 100:
                    continue
                fp = hashlib.md5(
                    re.sub(r'\s+', ' ', chunk.strip().lower()).encode()
                ).hexdigest()[:16]
                if fp in seen_chunks:
                    char_pos = i
                    all_duplicates.append(
                        f"[duplicate content block ~char {char_pos}]"
                    )
                    break  # one report per document is enough
                seen_chunks[fp] = i

        if all_duplicates:
            for dup in all_duplicates[:4]:
                hard_failures.append(
                    f"Duplicate content in document (model appended instead of "
                    f"rewriting): {dup}"
                )
            if len(all_duplicates) > 4:
                hard_failures.append(
                    f"...and {len(all_duplicates) - 4} more duplicate(s) found"
                )

        score = 1.0 if not all_duplicates else 0.0
        return score, hard_failures, warnings, {
            "duplicate_count": len(all_duplicates),
            "examples": all_duplicates[:4],
        }

    # =========================================================================
    # Check 3 — Stub-only sections
    # =========================================================================

    def _check_stub_sections(
        self, doc_texts: List[str], task_type: str
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        hard_failures: List[str] = []
        warnings: List[str] = []
        stub_headers: List[str] = []
        total_sections = 0

        for text in doc_texts:
            sections = self._extract_sections(text)
            total_sections += len(sections)

            for header, body in sections:
                body_stripped = body.strip()
                if not body_stripped:
                    continue

                lines = [l.strip() for l in body_stripped.splitlines() if l.strip()]

                # Bullet lines: start with -, *, or "N. " / "N) "
                bullet_lines = [
                    l for l in lines if re.match(r'^(?:[-*+]|\d+[.)]) ', l)
                ]
                # Prose lines: not a bullet, not a header, has ≥6 words
                prose_lines = [
                    l for l in lines
                    if not re.match(r'^(?:[-*+]|\d+[.)]) ', l)
                    and not re.match(r'^#{1,4}\s', l)
                    and len(l.split()) >= 6
                ]

                if not prose_lines and bullet_lines:
                    # Only bullets — check if they're all short (stub-like)
                    all_short = all(len(l.split()) <= 6 for l in bullet_lines)
                    if all_short:
                        stub_headers.append(header)

        if total_sections == 0:
            return 1.0, [], [], {"stubs": 0, "total": 0, "ratio": 0.0}

        stub_ratio = len(stub_headers) / total_sections

        if stub_ratio > 0.5 and task_type == "RESEARCH":
            hard_failures.append(
                f"{len(stub_headers)} of {total_sections} sections are stub-only "
                f"(header + short bullets, no prose). Expected substantive written "
                f"analysis in each section. Stubs: {stub_headers[:3]}"
            )
        elif stub_headers:
            for h in stub_headers[:3]:
                warnings.append(
                    f"Section \"{h}\" contains only short bullet items — "
                    "no substantive prose found"
                )

        score = max(0.2, 1.0 - stub_ratio * 0.8)
        return score, hard_failures, warnings, {
            "stubs": len(stub_headers),
            "total": total_sections,
            "ratio": round(stub_ratio, 2),
            "stub_headers": stub_headers[:6],
        }

    # =========================================================================
    # Check 4 — Tool grounding
    # =========================================================================

    def _check_tool_grounding(
        self,
        tool_results: List[Dict[str, Any]],
        doc_texts: List[str],
        task_type: str,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        hard_failures: List[str] = []
        warnings: List[str] = []

        # Determine which tool categories are relevant
        relevant_tools = set(_RESEARCH_TOOLS)
        if task_type == "ANALYSIS":
            relevant_tools |= {"read_file", "list_directory", "run_python",
                                "run_shell_command", "grep_search", "search_files"}

        # Filter to successful calls only
        research_calls = [
            tr for tr in tool_results
            if tr.get("tool") in relevant_tools and tr.get("success")
        ]

        if not research_calls:
            warnings.append(
                f"No successful research/analysis tool calls found for {task_type} "
                "task — tool grounding check skipped"
            )
            return 0.75, [], warnings, {
                "research_calls": 0,
                "skipped": True,
                "reason": "no_successful_research_tools",
            }

        # Extract atoms from all tool outputs
        all_atoms: List[str] = []
        for tr in research_calls:
            output = tr.get("output") or ""
            if not isinstance(output, str):
                output = str(output)
            atoms = self._extract_research_atoms(output)
            all_atoms.extend(atoms)

        # Deduplicate preserving order
        seen: Dict[str, None] = {}
        unique_atoms: List[str] = []
        for a in all_atoms:
            key = a.lower()
            if key not in seen:
                seen[key] = None
                unique_atoms.append(a)

        if not unique_atoms:
            warnings.append(
                "Research tool outputs contained no extractable named entities or "
                "numbers — grounding check skipped"
            )
            return 0.8, [], warnings, {
                "research_calls": len(research_calls),
                "atoms_extracted": 0,
                "skipped": True,
                "reason": "no_extractable_atoms",
            }

        # Check overlap with document text
        combined_doc = "\n".join(doc_texts).lower()

        def _word_in_doc(w: str) -> bool:
            """Check if word (or its singular/plural stem) appears in document."""
            if w in combined_doc:
                return True
            # Plural → singular: "systems" → "system", "weapons" → "weapon"
            if w.endswith('s') and len(w) > 4 and w[:-1] in combined_doc:
                return True
            # Singular → plural: "system" → "systems"
            if not w.endswith('s') and (w + 's') in combined_doc:
                return True
            return False

        def _atom_matches(atom: str) -> bool:
            """Exact substring OR word-level partial match (≥40% content words found)."""
            atom_l = atom.lower()
            if atom_l in combined_doc:
                return True
            # Word-level fallback for multi-word capitalized phrases:
            # article titles like "Tactical Weapon Systems" will never appear verbatim
            # in a document, but "tactical" and "weapon" will if the topic was researched.
            # Uses stemming fallback (systems↔system) and a 40% threshold so that
            # a single matching content word in a 2-word phrase counts.
            words = atom_l.split()
            if len(words) >= 2:
                content = [w for w in words if w not in _GROUNDING_STOPWORDS and len(w) > 3]
                if content:
                    n_found = sum(1 for w in content if _word_in_doc(w))
                    return n_found / len(content) >= 0.40
            return False

        matched   = [a for a in unique_atoms if     _atom_matches(a)]
        unmatched = [a for a in unique_atoms if not _atom_matches(a)]
        grounding_ratio = len(matched) / len(unique_atoms)

        # Secondary check: URLs in doc that came from tool results
        doc_urls = set(_RE_URL_IN_TEXT.findall(combined_doc))
        tool_text = " ".join(
            str(tr.get("output", "")) for tr in research_calls
        )
        tool_urls = set(_RE_URL_IN_TEXT.findall(tool_text.lower()))
        grounded_url_count = len(doc_urls & tool_urls)

        detail = {
            "research_calls": len(research_calls),
            "atoms_extracted": len(unique_atoms),
            "atoms_matched": len(matched),
            "grounding_ratio": round(grounding_ratio, 3),
            "doc_urls": len(doc_urls),
            "grounded_urls": grounded_url_count,
            "example_matched": matched[:5],
            "example_unmatched": unmatched[:5],
        }

        if grounding_ratio < 0.05:
            # Hard fail only when truly zero grounding — document is pure hallucination
            # with no connection to actual research. The 5% threshold (vs old 10%)
            # accounts for design/synthesis docs where company names and article titles
            # extracted from search results are not expected to appear verbatim.
            hard_failures.append(
                f"Tool grounding failure: {len(research_calls)} research tool "
                f"call(s) returned real data but only {grounding_ratio:.0%} of "
                f"extracted findings appear in the output document. The document "
                f"appears to be pure hallucination with no connection to actual "
                f"research results."
            )
            score = 0.0
        elif grounding_ratio < 0.10:
            warnings.append(
                f"Very low tool grounding ({grounding_ratio:.0%}): document barely "
                "reflects research findings — expand with specific facts from sources"
            )
            score = 0.3
        elif grounding_ratio < 0.20:
            warnings.append(
                f"Low tool grounding ({grounding_ratio:.0%}): research tool "
                "findings are poorly reflected in the output document"
            )
            score = 0.6
        elif grounding_ratio < 0.35:
            warnings.append(
                f"Moderate tool grounding ({grounding_ratio:.0%}): some research "
                "findings appear in the document but coverage is limited"
            )
            score = 0.7
        else:
            score = 1.0

        return score, hard_failures, warnings, detail

    # =========================================================================
    # Check 5 — Generic / ungrounded paragraphs
    # =========================================================================

    def _check_generic_content(
        self, doc_texts: List[str]
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """Always soft (warnings only). Caps at 3 reports."""
        warnings: List[str] = []
        generic_count = 0

        for text in doc_texts:
            # Split on blank lines
            paragraphs = re.split(r'\n{2,}', text)
            for para in paragraphs:
                para = para.strip()
                # Skip headings, code blocks, very short paragraphs
                if para.startswith('#') or para.startswith('```'):
                    continue
                word_count = len(para.split())
                if word_count < 20:
                    continue

                hedge_hits = len(_RE_GENERIC_HEDGE.findall(para))
                specificity_hits = len(_RE_SPECIFICITY.findall(para))

                if hedge_hits >= 2 and specificity_hits == 0:
                    generic_count += 1
                    if len(warnings) < 3:
                        preview = para[:120].replace('\n', ' ')
                        warnings.append(
                            f"Paragraph appears generic/ungrounded (no data, figures, "
                            f"or specific claims): \"{preview}...\""
                        )

        if generic_count > 3 and len(warnings) == 3:
            warnings.append(
                f"...and {generic_count - 3} more generic paragraphs found"
            )

        score = max(0.5, 1.0 - 0.12 * generic_count)
        return score, [], warnings, {"generic_paragraph_count": generic_count}

    # =========================================================================
    # Check 6 — Task-type-specific checks
    # =========================================================================

    def _check_task_specific(
        self,
        doc_texts: List[str],
        tool_results: List[Dict[str, Any]],
        task_type: str,
        proposal: Any,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        if task_type == "RESEARCH":
            return self._check_research_specific(doc_texts, tool_results, proposal)
        elif task_type == "ANALYSIS":
            return self._check_analysis_specific(doc_texts, tool_results)
        elif task_type == "PLANNING":
            return self._check_planning_specific(doc_texts)
        elif task_type == "SECURITY_REMEDIATION":
            return self._check_security_specific(doc_texts, tool_results)
        return 1.0, [], [], {"skipped": True, "task_type": task_type}

    def _check_research_specific(
        self,
        doc_texts: List[str],
        tool_results: List[Dict[str, Any]],
        proposal: Any,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        hard_failures: List[str] = []
        warnings: List[str] = []
        combined_doc = "\n".join(doc_texts).lower()

        # ── Sources: must not all be placeholders ──────────────────────────
        sources = list(getattr(proposal, "sources_consulted", None) or [])
        if sources:
            placeholder_src = [
                s for s in sources
                if isinstance(s, str)
                and re.search(r'\[|placeholder|url to|insert|fill in', s, re.IGNORECASE)
            ]
            if placeholder_src and len(placeholder_src) == len(sources):
                hard_failures.append(
                    f"All {len(sources)} listed source(s) are placeholder text, "
                    f"not real URLs or references: {placeholder_src[:2]}"
                )
            elif placeholder_src:
                warnings.append(
                    f"{len(placeholder_src)} of {len(sources)} source(s) look like "
                    f"placeholder text: {placeholder_src[:2]}"
                )

        # ── Key findings must have substance ──────────────────────────────
        key_findings = getattr(proposal, "key_findings", None) or []
        if isinstance(key_findings, str):
            key_findings = [key_findings]
        stub_findings = [
            f for f in key_findings
            if isinstance(f, str) and len(f.split()) < 6
        ]
        if key_findings and len(stub_findings) == len(key_findings):
            warnings.append(
                f"All key_findings are too brief (< 6 words each), suggesting "
                f"no real analysis: {stub_findings[:3]}"
            )

        # ── Capability gap / gap analysis must be present ─────────────────
        _RE_GAP = re.compile(
            r'\b(?:capability\s+gap|gap|limitation|shortcoming|deficiency|'
            r'addresses|identified\s+gap|missing\s+capability|'
            r'lacking|insufficient|not\s+currently|cannot\s+currently)\b',
            re.IGNORECASE,
        )
        if not _RE_GAP.search(combined_doc):
            warnings.append(
                "Document does not appear to identify or discuss a capability gap "
                "(no gap/limitation/deficiency language found)"
            )

        # ── References / sources must include at least one real URL ──────────
        # Check both the document body and proposal.sources_consulted.
        # "Wikipedia: Military technology" is not a citation — it has no URL.
        _full_doc = "\n".join(doc_texts)
        _doc_urls = _RE_URL_IN_TEXT.findall(_full_doc)
        _src_urls = [
            s for s in sources
            if isinstance(s, str) and re.search(r'https?://', s)
        ]
        if not _doc_urls and not _src_urls:
            hard_failures.append(
                "No real URLs found in the document or sources list. "
                "A research document must cite actual sources with URLs "
                "(e.g. 'https://www.defensenews.com/...'). "
                "Vague references like 'Wikipedia: Military technology' are not acceptable. "
                "Go back to your web_search results and copy the actual URLs into "
                "a Sources Consulted section."
            )

        # ── References section must not be all fake ───────────────────────
        ref_match = re.search(
            r'#+\s+(?:references?|sources?\s+consulted)\s*\n(.*?)(?=\n#+|\Z)',
            _full_doc,
            re.IGNORECASE | re.DOTALL,
        )
        if ref_match:
            ref_body = ref_match.group(1)
            real_urls = _RE_URL_IN_TEXT.findall(ref_body)
            fake_refs = re.findall(r'\[URL\s+to[^\]]*\]', ref_body, re.IGNORECASE)
            if fake_refs and not real_urls:
                hard_failures.append(
                    f"References section contains only placeholder citations "
                    f"({len(fake_refs)} fake URL(s), 0 real URLs): "
                    f"{fake_refs[:2]}"
                )

        score = 1.0 if not hard_failures else 0.2
        return score, hard_failures, warnings, {
            "sources_checked": len(sources),
            "placeholder_sources": len(
                [s for s in sources
                 if isinstance(s, str)
                 and re.search(r'\[|placeholder|url to|insert', s, re.IGNORECASE)]
            ),
            "stub_findings": len(stub_findings),
            "has_gap_language": bool(_RE_GAP.search(combined_doc)),
        }

    def _check_analysis_specific(
        self,
        doc_texts: List[str],
        tool_results: List[Dict[str, Any]],
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        warnings: List[str] = []

        # Files that were read should be referenced in the document
        read_calls = [
            tr for tr in tool_results
            if tr.get("tool") in (
                "read_file", "list_directory", "grep_search", "search_files"
            )
            and tr.get("success")
        ]
        if not read_calls:
            return 1.0, [], [], {"file_references_checked": False}

        filenames: List[str] = []
        for tr in read_calls:
            params = tr.get("parameters") or {}
            path = (
                params.get("path") or params.get("file_path")
                or params.get("directory") or ""
            )
            if path:
                filenames.append(os.path.basename(str(path)))

        combined_doc = "\n".join(doc_texts).lower()
        referenced = [f for f in filenames if f.lower() in combined_doc]
        ratio = len(referenced) / len(filenames) if filenames else 1.0

        if ratio < 0.25 and filenames:
            warnings.append(
                f"Analysis document references only {ratio:.0%} of the files "
                f"that were read ({len(referenced)}/{len(filenames)}). "
                f"Findings may not be grounded in actual file analysis."
            )

        score = max(0.5, ratio)
        return score, [], warnings, {
            "files_read": len(filenames),
            "files_referenced": len(referenced),
            "ratio": round(ratio, 2),
        }

    def _check_planning_specific(
        self, doc_texts: List[str]
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        warnings: List[str] = []
        combined_doc = "\n".join(doc_texts)

        has_iso_date = bool(re.search(r'\b\d{4}-\d{2}-\d{2}\b', combined_doc))
        has_quarter = bool(re.search(r'\bQ[1-4]\s+\d{4}\b', combined_doc))
        has_month_year = bool(
            re.search(
                r'\b(?:January|February|March|April|May|June|July|August|'
                r'September|October|November|December)\s+\d{4}\b',
                combined_doc,
            )
        )
        has_milestone = bool(
            re.search(
                r'\b(?:Phase\s+\d|Milestone\s+\d|Sprint\s+\d|Week\s+\d|'
                r'Step\s+\d|Deliverable|by\s+end\s+of|deadline|due\s+date)\b',
                combined_doc,
                re.IGNORECASE,
            )
        )

        has_dates = has_iso_date or has_quarter or has_month_year

        if not has_dates and not has_milestone:
            warnings.append(
                "Planning document contains no concrete dates, quarter references, "
                "milestones, or phase definitions — plan lacks time-bound deliverables"
            )
            score = 0.65
        elif not has_dates:
            warnings.append(
                "Planning document has milestones but no concrete dates or "
                "quarter references"
            )
            score = 0.8
        else:
            score = 1.0

        return score, [], warnings, {
            "has_iso_date": has_iso_date,
            "has_quarter": has_quarter,
            "has_month_year": has_month_year,
            "has_milestone": has_milestone,
        }

    def _check_security_specific(
        self,
        doc_texts: List[str],
        tool_results: List[Dict[str, Any]],
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        hard_failures: List[str] = []
        warnings: List[str] = []
        combined_doc = "\n".join(doc_texts)

        has_cve = bool(re.search(r'\bCVE-\d{4}-\d+\b', combined_doc))
        has_file_path = bool(
            re.search(r'/[a-zA-Z0-9_/.-]{5,}(?:\.[a-z]{1,10})\b', combined_doc)
        )
        has_config_change = bool(
            re.search(
                r'\b(?:set|changed|updated|patched|fixed|disabled|enabled|'
                r'configured|modified|hardened|restricted|removed|added)\s+\w+',
                combined_doc,
                re.IGNORECASE,
            )
        )
        has_patch_tool_call = any(
            tr.get("tool") in ("patch_file", "write_file", "run_shell_command",
                               "run_python", "execute_command")
            and tr.get("success")
            for tr in tool_results
        )

        if not has_cve and not has_file_path and not has_config_change:
            hard_failures.append(
                "Security remediation document contains no specific CVE IDs, "
                "file paths modified, or documented configuration changes. "
                "Cannot verify that remediation actually occurred."
            )
        elif not has_patch_tool_call:
            warnings.append(
                "Security remediation claimed but no file-write or command-execution "
                "tool calls succeeded — remediation may not have been applied"
            )

        score = 0.0 if hard_failures else (0.8 if warnings else 1.0)
        return score, hard_failures, warnings, {
            "has_cve": has_cve,
            "has_file_path": has_file_path,
            "has_config_change": has_config_change,
            "has_patch_tool_call": has_patch_tool_call,
        }

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _read_doc_texts(paths: List[str]) -> List[str]:
        """Read document files; silently skip unreadable or directory paths."""
        texts: List[str] = []
        for path in paths:
            if not path or not isinstance(path, str):
                continue
            try:
                if not os.path.isfile(path):
                    continue
                with open(path, "r", errors="replace") as fh:
                    content = fh.read()
                if content.strip():
                    texts.append(content)
            except OSError:
                pass
        return texts

    @staticmethod
    def _extract_research_atoms(text: str) -> List[str]:
        """
        Extract named entities, numbers, and quoted strings from tool output.
        These are the concrete data points that should appear in the document
        if the research was actually incorporated.
        """
        atoms: List[str] = []

        # Multi-word capitalized phrases (named entities)
        atoms += _RE_CAPITALIZED_PHRASE.findall(text)

        # Numbers with units (specific data points)
        for m in _RE_NUMBER_WITH_UNIT.finditer(text):
            val = m.group(0).strip()
            if val and re.search(r'\d', val):  # must contain at least one digit
                atoms.append(val)

        # Quoted strings (direct source quotes)
        atoms += _RE_QUOTED.findall(text)

        # Month+year temporal references
        atoms += _RE_MONTH_YEAR.findall(text)

        # Technical acronyms — exclude common English uppercase words
        for m in _RE_ACRONYM.finditer(text):
            acr = m.group(0)
            if acr not in _COMMON_UPPERCASE:
                atoms.append(acr)

        # Deduplicate preserving order
        seen: Dict[str, None] = {}
        result: List[str] = []
        for atom in atoms:
            key = atom.strip().lower()
            if key and len(key) > 2 and key not in seen:
                seen[key] = None
                result.append(atom.strip())

        return result

    @staticmethod
    def _extract_sections(text: str) -> List[Tuple[str, str]]:
        """Split markdown into (header_text, body) pairs."""
        sections: List[Tuple[str, str]] = []
        matches = list(_RE_MD_HEADER.finditer(text))
        for i, m in enumerate(matches):
            header_text = m.group(2).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
            sections.append((header_text, body))
        return sections

    @staticmethod
    def _normalize_header(header: str) -> str:
        """Normalize header text for duplicate comparison."""
        h = header.lower().strip()
        h = re.sub(r'[^\w\s]', '', h)
        h = re.sub(r'\s+', ' ', h).strip()
        return h
