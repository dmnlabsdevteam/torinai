#!/usr/bin/env python3
"""EDU-16: a 30-minute English lesson, taught by the model, attested by the world.

    The teacher may propose what class a word belongs to and state the rule
    that separates it. It may not settle the matter. A class becomes evidence
    only when a sentence that DEPENDS on it reads -- and the same class makes
    a wrong sentence fail, which is what stops a permissive parser from
    agreeing with everything.

Four competences, measured apart:

    PRETEST    before any teaching
    ASSISTED   while the teacher is reachable
    SUBSTRATE  with the teacher BLOCKED (model policy STRICT_MODEL_FREE)
    TRANSFER   held-out words and sentences that appeared in no lesson
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import curriculum
import world as edu_world

BUDGET_SECONDS = 30 * 60


@dataclass
class Telemetry:
    pretest_words: str = ""
    pretest_sentences: str = ""
    assisted_words: str = ""
    substrate_words: str = ""
    substrate_sentences: str = ""
    transfer_sentences: str = ""
    model_calls_instruction: int = 0
    model_calls_exam: int = 0
    model_reaches_blocked_in_exam: int = 0
    proposals: int = 0
    confirmations: int = 0
    contradictions: int = 0
    undecided_after: int = 0
    false_confidence: int = 0
    lessons_delivered: int = 0
    elapsed: float = 0.0
    limits: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)


class Teacher:
    """The model under contract. Everything it returns is a proposal."""

    def __init__(self, telemetry: Telemetry):
        self.t = telemetry
        self._svc = None

    async def _service(self):
        if self._svc is None:
            from core.services.unified_llm import get_llm_service
            svc = get_llm_service()
            if hasattr(svc, "__await__"):
                svc = await svc
            await svc.initialize()
            self._svc = svc
        return self._svc

    async def teach(self, lesson_id: str, concept: str, brief: str,
                    vocabulary: Dict[str, str]) -> str:
        svc = await self._service()
        self.t.model_calls_instruction += 1
        words = ", ".join(sorted(vocabulary))
        prompt = (
            f"Lesson {lesson_id}. Concept: {concept}.\n{brief}\n\n"
            f"You may use only these words: {words}.\n"
            f"Give a short explanation a beginner could follow, then two "
            f"contrasting example sentences, then one counterexample that is "
            f"WRONG and say what makes it wrong.\n"
            f"End with a line of the form:\n"
            f"RULE: <one sentence stating how to recognise a {concept}>")
        try:
            reply = await asyncio.wait_for(
                svc.generate(prompt=prompt, system_prompt=curriculum.TEACHER_CONTRACT,
                             max_tokens=400, temperature=0.3, enable_thinking=False),
                timeout=240)
        except asyncio.TimeoutError:
            return ""
        text = str((reply or {}).get("content") or "")
        return text.split("</think>", 1)[-1].strip()

    async def classify(self, words: List[str], concept: str) -> Dict[str, str]:
        """Ask the teacher which of these words belong to the class.

        A PROPOSAL. Nothing here is recorded as known; the world decides.
        """
        svc = await self._service()
        self.t.model_calls_instruction += 1
        prompt = (f"Which of these words are examples of a {concept}? "
                  f"Words: {', '.join(words)}.\n"
                  f"Answer with one line per word in the form WORD: YES or "
                  f"WORD: NO. Nothing else.")
        try:
            reply = await asyncio.wait_for(
                svc.generate(prompt=prompt, system_prompt=curriculum.TEACHER_CONTRACT,
                             max_tokens=200, temperature=0.0, enable_thinking=False),
                timeout=240)
        except asyncio.TimeoutError:
            return {}
        text = str((reply or {}).get("content") or "").split("</think>", 1)[-1]
        out: Dict[str, str] = {}
        for line in text.splitlines():
            hit = re.match(r"\s*([\w'-]+)\s*[:=-]\s*(YES|NO)\b", line.strip(), re.I)
            if hit and hit.group(1).lower() in {w.lower() for w in words}:
                out[hit.group(1).lower()] = hit.group(2).upper()
        return out


async def verify_proposal(word: str, word_class: str, talk, lexicon,
                          t: Telemetry) -> bool:
    """Put the proposed class to the world.

    A class earns its standing by making a TRUE sentence read and a FALSE one
    fail. Only the first would be satisfied by a parser that accepts anything,
    which is exactly the failure this experiment started from.
    """
    probes = {
        "NOUN":      (f"the {word} is heavy", f"the {word} is open"),
        "ADJECTIVE": (f"the vault is {word}", f"the pump is {word}"),
        "VERB":      (f"the pump {word} water", f"the valve {word} air"),
    }[word_class]

    lexicon.propose(word, word_class, "teacher")
    t.proposals += 1

    supported = 0
    for sentence in probes:
        reading, _ = await talk.read(sentence)
        if reading:
            supported += 1

    if supported:
        lexicon.confirm(word, f"{probes[0]} reads")
        t.confirmations += 1
        return True
    lexicon.refute(word, f"neither {probes[0]!r} nor {probes[1]!r} reads")
    t.contradictions += 1
    return False


async def measure_words(words: Dict[str, str], talk, lexicon,
                        induction=None, observations=None) -> Tuple[int, Dict]:
    """Classify each word: frames first, then any induced rule. UNDECIDED is an answer."""
    right, detail = 0, {}
    for word, truth in words.items():
        verdict = await edu_world.classify(word, curriculum.FRAMES, talk,
                                           induction, observations)
        detail[word] = {"truth": truth, "verdict": verdict.verdict,
                        "fitted": list(verdict.fitted)}
        right += verdict.verdict == truth
    return right, detail


async def measure_sentences(talk) -> Tuple[int, Dict]:
    right, detail = 0, {}
    for sentence, stage, expected in curriculum.HELD_OUT_SENTENCES:
        ok, got = await edu_world.read_sentence(sentence, expected, talk)
        detail[sentence] = {"stage": stage, "expected": list(expected), "got": got}
        right += ok
    return right, detail


async def run() -> Telemetry:
    from core.database import get_database_manager
    from core.model_policy import (ModelPolicy, model_telemetry,
                                   reset_model_telemetry, set_model_policy)
    from core.semantics.conversation import Conversation
    import core.semantics.lexicon as lexmod
    from core.semantics.lexicon import Lexicon

    await get_database_manager().initialize()
    started = time.time()
    t = Telemetry()

    # FROZEN START. The lexicon is emptied so nothing from an earlier run can
    # be mistaken for something learned in this one.
    lexmod._lexicon = Lexicon(path=Path("data") / "lexicon_edu16.json")
    lexmod._lexicon.clear()
    lexicon = lexmod._lexicon
    talk = Conversation()
    reset_model_telemetry()

    # ── PRE-TEST, teacher detached ──────────────────────────────────────────
    print("── PRE-TEST (teacher detached) " + "─" * 40, flush=True)
    right, detail = await measure_words(curriculum.HELD_OUT, talk, lexicon)
    t.pretest_words = f"{right}/{len(curriculum.HELD_OUT)}"
    t.detail["pretest_words"] = detail
    sright, sdetail = await measure_sentences(talk)
    t.pretest_sentences = f"{sright}/{len(curriculum.HELD_OUT_SENTENCES)}"
    t.detail["pretest_sentences"] = sdetail
    print(f"   held-out words     {t.pretest_words}")
    print(f"   held-out sentences {t.pretest_sentences}", flush=True)

    # ── LESSONS ─────────────────────────────────────────────────────────────
    teacher = Teacher(t)
    for lesson_id, concept, brief in curriculum.LESSONS:
        if time.time() - started > BUDGET_SECONDS * 0.75:
            t.limits.append(f"ran out of budget before {lesson_id}")
            break
        print(f"\n── {lesson_id} " + "─" * 52, flush=True)
        lesson = await teacher.teach(lesson_id, concept, brief, curriculum.TAUGHT)
        if not lesson:
            t.limits.append(f"teacher produced no lesson for {lesson_id}")
            continue
        t.lessons_delivered += 1
        rule = next((l for l in lesson.splitlines() if l.strip().upper().startswith("RULE:")), "")
        print("   teacher:", lesson.replace("\n", " ")[:130])
        if rule:
            print("  ", rule.strip()[:120])

        if concept not in ("NOUN", "ADJECTIVE", "VERB"):
            continue        # L4/L5 build on classes already established

        # The teacher proposes which taught words are of this class; the world
        # decides whether the proposal survives.
        candidates = sorted(curriculum.TAUGHT)
        verdicts = await teacher.classify(candidates, concept)
        for word, answer in verdicts.items():
            if answer != "YES":
                continue
            await verify_proposal(word, concept, talk, lexicon, t)
        lexicon.save()
        print(f"   proposals={t.proposals} confirmed={t.confirmations} "
              f"refuted={t.contradictions}", flush=True)

    # ── INDUCE A RULE FROM WHAT SURVIVED ────────────────────────────────────
    # From the CONFIRMED entries only. A proposal the world refuted is not
    # evidence and must not shape the rule that generalises from it.
    from core.semantics.class_induction import induce
    confirmed = {e.word: e.word_class for e in lexicon.known()
                 if e.status == "confirmed"}
    induction = induce(confirmed)
    print("\n── INDUCED RULES (from confirmed evidence) " + "─" * 28, flush=True)
    for rule in induction.rules:
        print("  ", rule.describe())
    if induction.unseparated:
        print("   no feature separates:", induction.unseparated)
    t.detail["induced_rules"] = [r.describe() for r in induction.rules]
    t.detail["unseparated"] = [list(p) for p in induction.unseparated]

    # ── EXPOSURE: meet the new words used in sentences ──────────────────────
    print("\n── EXPOSURE (reading sentences that use unseen words) " + "─" * 17, flush=True)
    from core.semantics.class_induction import observe
    observations = []
    read_count = 0
    from core.semantics.class_induction import class_from_observations
    for sentence in curriculum.EXPOSURE:
        reading, _src = await talk.read(sentence)
        if not reading:
            continue
        read_count += 1
        fresh = observe(sentence, reading[0])
        observations.extend(fresh)

        # WHAT ONE SENTENCE TEACHES MUST BE AVAILABLE TO THE NEXT.
        #
        # Observations were kept for the exam while the READER consulted the
        # lexicon, so nothing learned from "the tank is cold" could help read
        # "the tank pushes water" -- and the verb sentences stayed unreadable
        # because their noun anchor was never recorded. Reading a sentence is
        # how a word enters the lexicon; that is the whole mechanism.
        for sighting in fresh:
            settled = class_from_observations(sighting.word, observations)
            if settled and not lexicon.entry(sighting.word):
                lexicon.propose(sighting.word, settled, "observed")
                lexicon.confirm(sighting.word, f"seen as {sighting.slot} in {sentence!r}")
    t.detail["exposure_read"] = f"{read_count}/{len(curriculum.EXPOSURE)}"
    print(f"   sentences read {read_count}/{len(curriculum.EXPOSURE)}, "
          f"{len(observations)} word sightings", flush=True)

    # ── ASSISTED, teacher still reachable ───────────────────────────────────
    print("\n── ASSISTED (teacher reachable) " + "─" * 39, flush=True)
    right, detail = await measure_words(curriculum.HELD_OUT, talk, lexicon,
                                        induction, observations)
    t.assisted_words = f"{right}/{len(curriculum.HELD_OUT)}"
    t.detail["assisted_words"] = detail
    print(f"   held-out words {t.assisted_words}", flush=True)

    # ── TEACHER-OFF EXAM ────────────────────────────────────────────────────
    print("\n── TEACHER-OFF EXAM (STRICT_MODEL_FREE) " + "─" * 31, flush=True)
    before = _llm(model_telemetry())
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    try:
        right, detail = await measure_words(curriculum.HELD_OUT, talk, lexicon,
                                            induction, observations)
        t.substrate_words = f"{right}/{len(curriculum.HELD_OUT)}"
        t.detail["exam_words"] = detail
        t.undecided_after = sum(1 for d in detail.values() if d["verdict"] is None)
        t.false_confidence = sum(1 for d in detail.values()
                                 if d["verdict"] is not None and d["verdict"] != d["truth"])
        sright, sdetail = await measure_sentences(talk)
        t.substrate_sentences = f"{sright}/{len(curriculum.HELD_OUT_SENTENCES)}"
        t.detail["exam_sentences"] = sdetail
        transfer = sum(1 for s, d in sdetail.items()
                       if d["stage"] in ("L4", "L5") and d["got"] in d["expected"])
        t.transfer_sentences = f"{transfer}/" + str(sum(
            1 for _s, stage, _e in curriculum.HELD_OUT_SENTENCES if stage in ("L4", "L5")))
    finally:
        set_model_policy(previous)
    after = _llm(model_telemetry())
    t.model_calls_exam = after["executed"] - before["executed"]
    t.model_reaches_blocked_in_exam = after["blocked"] - before["blocked"]
    print(f"   held-out words     {t.substrate_words}")
    print(f"   held-out sentences {t.substrate_sentences}", flush=True)

    lexicon.save()
    t.elapsed = time.time() - started
    return t


def _llm(snapshot) -> Dict[str, int]:
    blob = json.loads(json.dumps(snapshot, default=str))

    def find(node):
        if isinstance(node, dict):
            if "llm" in node and isinstance(node["llm"], dict) and "attempts" in node["llm"]:
                return node["llm"]
            for v in node.values():
                got = find(v)
                if got:
                    return got
        return None

    llm = find(blob) or {}
    return {"executed": int(llm.get("executed", 0)), "blocked": int(llm.get("blocked", 0)),
            "attempts": int(llm.get("attempts", 0))}


if __name__ == "__main__":
    t = asyncio.run(run())
    print("\n" + "=" * 68)
    print(f"elapsed                          : {t.elapsed/60:.1f} min")
    print(f"PRETEST   words / sentences      : {t.pretest_words} / {t.pretest_sentences}")
    print(f"ASSISTED  words                  : {t.assisted_words}")
    print(f"SUBSTRATE words / sentences      : {t.substrate_words} / {t.substrate_sentences}")
    print(f"TRANSFER  (L4/L5 sentences)      : {t.transfer_sentences}")
    print("-" * 68)
    print(f"lessons delivered                : {t.lessons_delivered}")
    print(f"proposals / confirmed / refuted  : {t.proposals} / {t.confirmations} / {t.contradictions}")
    print(f"model calls during instruction   : {t.model_calls_instruction}")
    print(f"model calls during exam          : {t.model_calls_exam}  (must be 0)")
    print(f"model reaches BLOCKED in exam    : {t.model_reaches_blocked_in_exam}")
    print(f"still UNDECIDED after teaching   : {t.undecided_after}")
    print(f"false confidence (wrong class)   : {t.false_confidence}")
    for limit in t.limits:
        print("LIMIT:", limit)
    print("=" * 68)
    Path("experiments/edu/EDU-16/result.json").write_text(
        json.dumps({k: v for k, v in t.__dict__.items()}, indent=2, default=str))
