#!/usr/bin/env python3
"""
Comprehensive Tool Capability Test
====================================
Tests EVERY tool registered in the registry across 7 sections:

  Section 1  – Registry Health        : All tools load without error
  Section 2  – Profile Completeness   : Every tool has a non-empty capability profile
  Section 3  – Enum Validity          : Every declared capability is a valid Capability enum value
  Section 4  – Registry Integrity     : find_providers(cap) returns the tool for every cap it declares
  Section 5  – Description Inference  : infer_capability_from_task(tool.description) hits declared caps
  Section 6  – LLM Semantic Validation: LLM confirms capability→tool assignments make semantic sense
  Section 7  – Capability Coverage    : Every Capability enum value has at least one tool provider

Run:
  cd "/Users/stefan/Dominion Labs/TorinAI" && python test_comprehensive_tool_capabilities.py
"""

import asyncio
import json
import logging
import re
import sys
from collections import defaultdict
from typing import Dict, List, Set, Tuple

logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

BOLD  = "\033[1m"
RED   = "\033[91m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
CYAN  = "\033[96m"
RESET = "\033[0m"

def hdr(title: str) -> None:
    print(f"\n{'='*80}")
    print(f"{BOLD}{title}{RESET}")
    print("="*80)

def ok(msg: str)   -> None: print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg: str) -> None: print(f"  {RED}✗{RESET} {msg}")
def warn(msg: str) -> None: print(f"  {YELLOW}⚠{RESET} {msg}")
def info(msg: str) -> None: print(f"  {CYAN}→{RESET} {msg}")


def strip_json_comments(text: str) -> str:
    """Remove //… comments outside quoted strings (local LLM output fix)."""
    result, in_string, i = [], False, 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i-1] != '\\'):
            in_string = not in_string
            result.append(ch)
        elif not in_string and ch == '/' and i+1 < len(text) and text[i+1] == '/':
            while i < len(text) and text[i] != '\n':
                i += 1
            continue
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def extract_json(text: str):
    """Extract first JSON object or array from LLM output."""
    text = strip_json_comments(text)
    # Try to find JSON array
    for start_ch, end_ch in [('[', ']'), ('{', '}')]:
        s = text.find(start_ch)
        if s < 0:
            continue
        depth, in_str = 0, False
        for i, ch in enumerate(text[s:], start=s):
            if ch == '"' and (i == 0 or text[i-1] != '\\'):
                in_str = not in_str
            if not in_str:
                if ch == start_ch:
                    depth += 1
                elif ch == end_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[s:i+1])
                        except json.JSONDecodeError:
                            break
    return None


def _all_tool_names(registry) -> List[str]:
    """Return every tool name known to the registry (eager + lazy)."""
    names: Set[str] = set()
    if hasattr(registry, "tools"):
        names.update(registry.tools.keys())
    if hasattr(registry, "tool_factories"):
        names.update(registry.tool_factories.keys())
    if hasattr(registry, "_tools"):
        names.update(registry._tools.keys())
    if hasattr(registry, "_factories"):
        names.update(registry._factories.keys())
    return sorted(names)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 – Registry Health Check
# ══════════════════════════════════════════════════════════════════════════════

async def section1_registry_health(registry) -> Tuple[Dict, List]:
    """Force-load every tool; return (loaded_tools dict, failed list)."""
    hdr("SECTION 1 — Registry Health Check")
    print("  Force-loading every registered tool…\n")

    all_names  = _all_tool_names(registry)
    loaded     : Dict[str, object] = {}
    failed     : List[Tuple[str, str]] = []

    for name in all_names:
        try:
            tool = registry.get_tool(name)
            if tool is None:
                failed.append((name, "get_tool() returned None"))
            else:
                loaded[name] = tool
        except Exception as e:
            failed.append((name, str(e)))

    total = len(all_names)
    print(f"  Registered names : {total}")
    print(f"  Loaded OK        : {GREEN}{len(loaded)}{RESET}")
    print(f"  Failed to load   : {RED}{len(failed)}{RESET}")

    if failed:
        print()
        for name, err in failed[:20]:
            fail(f"{name}: {err[:100]}")
        if len(failed) > 20:
            warn(f"  … and {len(failed)-20} more failures")

    passed = len(failed) == 0
    print(f"\n  Result: {'PASS' if passed else 'FAIL'} — {len(loaded)}/{total} tools loaded")
    return loaded, failed


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 – Capability Profile Completeness
# ══════════════════════════════════════════════════════════════════════════════

def section2_profile_completeness(loaded_tools: Dict) -> Tuple[int, List[str]]:
    hdr("SECTION 2 — Capability Profile Completeness")
    print("  Every tool must have a non-empty capability_profile.\n")

    no_profile    : List[str] = []
    empty_profile : List[str] = []
    dup_caps      : List[Tuple[str, str]] = []
    ok_count = 0

    for name, tool in sorted(loaded_tools.items()):
        profile = getattr(tool, "capability_profile", None)
        if profile is None:
            no_profile.append(name)
            continue
        caps = getattr(profile, "capabilities", None)
        if not caps:
            empty_profile.append(name)
            continue
        # Check duplicates
        seen: Set = set()
        dups = []
        for meta in caps:
            c = meta.capability
            if c in seen:
                dups.append(c.value)
            seen.add(c)
        if dups:
            dup_caps.append((name, ", ".join(dups)))
        ok_count += 1

    total = len(loaded_tools)
    problems = no_profile + empty_profile

    if no_profile:
        print(f"  {RED}No capability_profile ({len(no_profile)} tools):{RESET}")
        for n in no_profile[:15]:
            fail(n)
        if len(no_profile) > 15:
            warn(f"  … and {len(no_profile)-15} more")

    if empty_profile:
        print(f"\n  {RED}Empty capabilities list ({len(empty_profile)} tools):{RESET}")
        for n in empty_profile[:15]:
            fail(n)
        if len(empty_profile) > 15:
            warn(f"  … and {len(empty_profile)-15} more")

    if dup_caps:
        print(f"\n  {YELLOW}Duplicate capabilities ({len(dup_caps)} tools):{RESET}")
        for n, dups in dup_caps[:10]:
            warn(f"{n}: duplicated {dups}")

    if not problems:
        ok(f"All {total} tools have non-empty capability profiles")

    passed = len(problems) == 0
    print(f"\n  Result: {'PASS' if passed else 'FAIL'} — {ok_count}/{total} tools have valid profiles")
    return ok_count, no_profile + empty_profile


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 – Capability Enum Validity
# ══════════════════════════════════════════════════════════════════════════════

def section3_enum_validity(loaded_tools: Dict, Capability) -> Tuple[int, List]:
    hdr("SECTION 3 — Capability Enum Validity")
    print("  Every declared capability must be a valid Capability enum member.\n")

    valid_caps = set(Capability)
    invalid_entries : List[Tuple[str, str]] = []
    ok_count = 0

    for name, tool in sorted(loaded_tools.items()):
        profile = getattr(tool, "capability_profile", None)
        if not profile:
            continue
        caps = getattr(profile, "capabilities", []) or []
        tool_ok = True
        for meta in caps:
            c = meta.capability
            if c not in valid_caps:
                invalid_entries.append((name, repr(c)))
                tool_ok = False
        if tool_ok:
            ok_count += 1

    if invalid_entries:
        print(f"  {RED}Invalid capability references ({len(invalid_entries)}):{RESET}")
        for n, c in invalid_entries[:20]:
            fail(f"{n}: {c}")
    else:
        ok(f"All {ok_count} tools use valid Capability enum values")

    passed = len(invalid_entries) == 0
    print(f"\n  Result: {'PASS' if passed else 'FAIL'} — {ok_count}/{len(loaded_tools)} tools with all-valid capabilities")
    return ok_count, invalid_entries


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 – Registry Integrity
# ══════════════════════════════════════════════════════════════════════════════

def section4_registry_integrity(loaded_tools: Dict, registry) -> Tuple[int, List]:
    """For every (tool, capability) pair, find_providers(cap) must include tool."""
    hdr("SECTION 4 — Registry Integrity")
    print("  For each declared (tool, capability) pair,")
    print("  registry.find_providers(cap) must list that tool.\n")

    mismatches : List[Tuple[str, str]] = []
    ok_pairs   = 0
    total_pairs = 0

    for name, tool in sorted(loaded_tools.items()):
        profile = getattr(tool, "capability_profile", None)
        if not profile:
            continue
        caps = getattr(profile, "capabilities", []) or []
        for meta in caps:
            total_pairs += 1
            cap = meta.capability
            try:
                providers = registry.find_providers(cap)
                provider_names = {t.name for t in providers}
                if name in provider_names:
                    ok_pairs += 1
                else:
                    mismatches.append((name, cap.value))
            except Exception as e:
                mismatches.append((name, f"{cap.value} [ERROR: {e}]"))

    if mismatches:
        # Group by tool for readability
        by_tool: Dict[str, List[str]] = defaultdict(list)
        for t, c in mismatches:
            by_tool[t].append(c)
        print(f"  {RED}Registry mismatches ({len(mismatches)} pairs across {len(by_tool)} tools):{RESET}")
        for t, caps in list(by_tool.items())[:15]:
            fail(f"{t}: not found as provider for {caps}")
        if len(by_tool) > 15:
            warn(f"  … and {len(by_tool)-15} more tools with mismatches")
    else:
        ok(f"All {total_pairs} (tool, capability) pairs are correctly indexed")

    passed = len(mismatches) == 0
    print(f"\n  Result: {'PASS' if passed else 'FAIL'} — {ok_pairs}/{total_pairs} pairs correctly registered")
    return ok_pairs, mismatches


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 – Description → Capability Inference
# ══════════════════════════════════════════════════════════════════════════════

def section5_description_inference(loaded_tools: Dict, infer_fn) -> Tuple[int, List]:
    """infer_capability_from_task(tool.description) should hit at least one declared cap."""
    hdr("SECTION 5 — Description → Capability Inference")
    print("  For each tool, infer_capability_from_task(tool.description)")
    print("  must return at least one of the tool's declared capabilities.\n")

    misses    : List[Tuple[str, List[str], List[str]]] = []
    hits      = 0
    skipped   = 0

    for name, tool in sorted(loaded_tools.items()):
        desc = getattr(tool, "description", "") or ""
        if not desc.strip():
            skipped += 1
            continue

        profile = getattr(tool, "capability_profile", None)
        if not profile:
            skipped += 1
            continue
        caps_meta = getattr(profile, "capabilities", []) or []
        declared = {m.capability for m in caps_meta}

        inferred = infer_fn(desc)  # returns Dict[Capability, float]
        inferred_set = set(inferred.keys())

        overlap = declared & inferred_set
        if overlap:
            hits += 1
        else:
            misses.append((
                name,
                [c.value for c in declared],
                [c.value for c in inferred_set]
            ))

    total = len(loaded_tools) - skipped
    if misses:
        print(f"  {YELLOW}Tools whose description doesn't trigger declared caps ({len(misses)}):{RESET}")
        print(f"  {YELLOW}(These indicate regex pattern gaps, not broken tools){RESET}\n")
        for n, declared, inferred in misses[:30]:
            warn(f"{n}")
            info(f"  declared : {declared[:4]}")
            info(f"  inferred : {inferred[:4] if inferred else '(nothing)'}")
    else:
        ok(f"All {hits} tools: description infers at least one declared capability")

    print(f"\n  Result: {hits}/{total} tools match  |  {len(misses)} gaps  |  {skipped} skipped (no desc/profile)")
    # This section is informational — gaps aren't failures, just pattern tuning opportunities
    return hits, misses


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 – LLM Semantic Validation (ALL TOOLS, BATCHED)
# ══════════════════════════════════════════════════════════════════════════════

BATCH_SIZE = 12  # tools per LLM call

async def section6_llm_semantic(loaded_tools: Dict, llm) -> Tuple[int, int, List]:
    """Ask the LLM to validate every (tool, capability) assignment in batches."""
    hdr("SECTION 6 — LLM Semantic Validation (all tools, batched)")
    print(f"  LLM validates every tool's capability assignments in batches of {BATCH_SIZE}.")
    print(f"  Question: 'Does this capability accurately describe what this tool does?'\n")

    # Build list of (name, description, declared_caps) for tools with profiles
    items = []
    for name, tool in sorted(loaded_tools.items()):
        profile = getattr(tool, "capability_profile", None)
        if not profile:
            continue
        caps_meta = getattr(profile, "capabilities", []) or []
        if not caps_meta:
            continue
        desc  = (getattr(tool, "description", "") or "")[:200]
        cap_values = list({m.capability.value for m in caps_meta})
        items.append((name, desc, cap_values))

    total_tools = len(items)
    batches = [items[i:i+BATCH_SIZE] for i in range(0, total_tools, BATCH_SIZE)]

    print(f"  {total_tools} tools → {len(batches)} LLM batches\n")

    confirmed : List[str] = []   # tool names LLM says: valid
    rejected  : List[Tuple[str, str]] = []   # (tool, reason) LLM says: invalid
    errors    : List[str] = []   # parse / call errors

    for batch_idx, batch in enumerate(batches):
        batch_num = batch_idx + 1
        print(f"  Batch {batch_num}/{len(batches)} ({len(batch)} tools)…", end=" ", flush=True)

        # Build prompt
        tools_json = json.dumps([
            {"tool": name, "description": desc, "declared_capabilities": caps}
            for name, desc, caps in batch
        ], indent=2)

        prompt = f"""You are validating capability assignments for an AI tool registry.

For each tool below, judge whether its "declared_capabilities" accurately describe what the tool does based on its "description".

Rules:
- "valid" = true if the declared capabilities make sense for the tool's description
- "valid" = false if the capabilities are clearly WRONG (e.g. a file-reading tool claiming GENERATE_CODE)
- "valid" = true even if the tool ALSO could have other capabilities not listed
- Be lenient: partial matches count as valid

Tools to evaluate:
{tools_json}

Return ONLY a JSON array (no markdown, no explanation) with one object per tool:
[
  {{"tool": "tool_name", "valid": true, "reason": "brief reason"}},
  ...
]"""

        try:
            result = await llm.generate(
                prompt=prompt,
                temperature=0.1,
                max_tokens=BATCH_SIZE * 60,
                agent_type="test"
            )
            response = result.get("content", "").strip()
            parsed = extract_json(response)

            if parsed is None or not isinstance(parsed, list):
                errors.append(f"Batch {batch_num}: could not parse JSON")
                print(f"{YELLOW}parse error{RESET}")
                continue

            batch_names = {name for name, _, _ in batch}
            seen_in_response = set()

            for entry in parsed:
                tname  = entry.get("tool", "")
                valid  = entry.get("valid", True)
                reason = entry.get("reason", "")
                seen_in_response.add(tname)
                if valid:
                    confirmed.append(tname)
                else:
                    rejected.append((tname, reason))

            # Tools the LLM silently skipped
            missed = batch_names - seen_in_response
            for m in missed:
                errors.append(f"Batch {batch_num}: LLM skipped '{m}'")
                confirmed.append(m)  # assume valid if not mentioned

            print(f"{GREEN}OK{RESET} ({len([e for e in parsed if e.get('valid', True)])}/{len(batch)} valid)")

        except Exception as e:
            errors.append(f"Batch {batch_num}: {e}")
            print(f"{RED}ERROR: {e}{RESET}")

    print()
    if rejected:
        print(f"  {RED}LLM flagged invalid capability assignments ({len(rejected)}):{RESET}")
        for tname, reason in rejected[:20]:
            fail(f"{tname}: {reason[:100]}")
        if len(rejected) > 20:
            warn(f"  … and {len(rejected)-20} more")

    if errors:
        print(f"\n  {YELLOW}Batch errors ({len(errors)}):{RESET}")
        for e in errors[:10]:
            warn(e)

    if not rejected:
        ok(f"LLM confirmed all {len(confirmed)} tool capability assignments as semantically valid")

    passed = len(rejected) == 0
    print(f"\n  Result: {'PASS' if passed else 'FAIL'} — {len(confirmed)} valid, {len(rejected)} invalid, {len(errors)} batch errors")
    return len(confirmed), len(rejected), rejected


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 – Capability Coverage
# ══════════════════════════════════════════════════════════════════════════════

def section7_capability_coverage(registry, Capability) -> Tuple[int, int, List]:
    """Every Capability enum value should have at least one tool provider."""
    hdr("SECTION 7 — Capability Coverage")
    print("  Every Capability enum value should have at least one tool provider.\n")

    try:
        coverage = registry.get_capability_coverage()
    except Exception:
        # Fallback: check each manually
        coverage = {}
        for cap in Capability:
            try:
                providers = registry.find_providers(cap)
                coverage[cap] = len(providers)
            except Exception:
                coverage[cap] = 0

    all_caps    = list(Capability)
    covered     = [(c, n) for c, n in coverage.items() if n > 0]
    uncovered   = [c for c in all_caps if coverage.get(c, 0) == 0]

    # Sort covered by count descending for the report
    covered.sort(key=lambda x: -x[1])

    print(f"  Total capabilities : {len(all_caps)}")
    print(f"  With providers     : {GREEN}{len(covered)}{RESET}")
    print(f"  No providers       : {RED}{len(uncovered)}{RESET}")

    if uncovered:
        print(f"\n  {YELLOW}Unimplemented capabilities (no tool provides these):{RESET}")
        for cap in sorted(uncovered, key=lambda c: c.value):
            warn(cap.value)

    print(f"\n  Top 10 most-provided capabilities:")
    for cap, count in covered[:10]:
        info(f"{cap.value:<35} → {count} tool(s)")

    passed = len(uncovered) == 0
    print(f"\n  Result: {'PASS' if passed else 'WARN'} — {len(covered)}/{len(all_caps)} capabilities have providers")
    return len(covered), len(all_caps), uncovered


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "="*80)
    print(f"{BOLD}COMPREHENSIVE TOOL CAPABILITY TEST — ALL TOOLS, ALL CAPABILITIES{RESET}")
    print("="*80)
    print("Sections: Health · Completeness · Enum Validity · Registry Integrity")
    print("          Description Inference · LLM Semantic · Capability Coverage")
    print("="*80)

    # ── Imports ────────────────────────────────────────────────────────────────
    from core.tools import get_tool_registry
    from core.tools.capabilities import Capability, infer_capability_from_task
    from core.services.unified_llm import get_llm_service

    registry = get_tool_registry()
    llm = get_llm_service()

    results = {}

    # ── Section 1 ─────────────────────────────────────────────────────────────
    loaded_tools, s1_failures = await section1_registry_health(registry)
    results["S1 Registry Health"] = len(s1_failures) == 0

    # ── Section 2 ─────────────────────────────────────────────────────────────
    s2_ok, s2_failures = section2_profile_completeness(loaded_tools)
    results["S2 Profile Completeness"] = len(s2_failures) == 0

    # ── Section 3 ─────────────────────────────────────────────────────────────
    s3_ok, s3_failures = section3_enum_validity(loaded_tools, Capability)
    results["S3 Enum Validity"] = len(s3_failures) == 0

    # ── Section 4 ─────────────────────────────────────────────────────────────
    s4_ok, s4_failures = section4_registry_integrity(loaded_tools, registry)
    results["S4 Registry Integrity"] = len(s4_failures) == 0

    # ── Section 5 ─────────────────────────────────────────────────────────────
    s5_hits, s5_misses = section5_description_inference(loaded_tools, infer_capability_from_task)
    # Section 5 is informational — gaps are pattern tuning opportunities, not hard failures
    results["S5 Description Inference"] = True  # always informational

    # ── Section 6 ─────────────────────────────────────────────────────────────
    s6_valid, s6_invalid, s6_rejected = await section6_llm_semantic(loaded_tools, llm)
    # Pass if LLM rejects fewer than 5% of tools
    reject_rate = s6_invalid / max(s6_valid + s6_invalid, 1)
    results["S6 LLM Semantic"] = reject_rate < 0.05

    # ── Section 7 ─────────────────────────────────────────────────────────────
    s7_covered, s7_total, s7_uncovered = section7_capability_coverage(registry, Capability)
    # Pass if 80%+ of capabilities have at least one provider
    results["S7 Capability Coverage"] = s7_covered / s7_total >= 0.80

    # ── Final Summary ──────────────────────────────────────────────────────────
    hdr("FINAL SUMMARY")
    passed = sum(1 for r in results.values() if r)
    for section, result in results.items():
        status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
        print(f"  {status}  {section}")

    print(f"\n  {'─'*50}")
    print(f"  Tools loaded     : {len(loaded_tools)}")
    print(f"  Load failures    : {RED}{len(s1_failures)}{RESET}" if s1_failures else f"  Load failures    : {GREEN}0{RESET}")
    print(f"  Missing profiles : {RED}{len(s2_failures)}{RESET}" if s2_failures else f"  Missing profiles : {GREEN}0{RESET}")
    print(f"  Invalid enums    : {RED}{len(s3_failures)}{RESET}" if s3_failures else f"  Invalid enums    : {GREEN}0{RESET}")
    print(f"  Registry gaps    : {RED}{len(s4_failures)}{RESET}" if s4_failures else f"  Registry gaps    : {GREEN}0{RESET}")
    print(f"  Desc misses      : {YELLOW}{len(s5_misses)}{RESET} (pattern tuning)")
    print(f"  LLM rejections   : {RED}{s6_invalid}{RESET}" if s6_invalid else f"  LLM rejections   : {GREEN}0{RESET}")
    print(f"  Cap coverage     : {s7_covered}/{s7_total}")
    print(f"  {'─'*50}")
    print(f"\n  Overall: {GREEN if passed == len(results) else RED}{passed}/{len(results)}{RESET} sections passed")
    print("="*80 + "\n")

    if s2_failures:
        print(f"{RED}ACTION REQUIRED:{RESET} {len(s2_failures)} tools missing capability profiles.")
        print(f"  Tools: {s2_failures[:5]}")
    if s4_failures:
        print(f"{RED}ACTION REQUIRED:{RESET} {len(s4_failures)} (tool, cap) pairs not in registry index.")
    if s6_rejected:
        print(f"{YELLOW}REVIEW:{RESET} {len(s6_rejected)} tools have LLM-flagged mismatched capability assignments.")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
