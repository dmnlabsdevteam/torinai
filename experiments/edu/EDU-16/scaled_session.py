#!/usr/bin/env python3
"""A sustained teaching run: read English until it stops learning.

Not a fixed lesson list. The teacher writes sentences in the shapes the
substrate can represent, the substrate reads them, and every word seen standing
in a slot enters the lexicon. Growth is measured against wall-clock, and the run
stops when the budget is spent or when reading stops adding anything.

    A sentence teaches only if it READS. One the teacher wrote badly teaches
    nothing, and is counted as a sentence that taught nothing.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus as corpus_mod
import curriculum

BUDGET_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30 * 60


class Teacher:
    def __init__(self):
        self._svc = None
        self.calls = 0

    async def say(self, prompt: str, max_tokens: int = 400) -> str:
        if self._svc is None:
            from core.services.unified_llm import get_llm_service
            svc = get_llm_service()
            if hasattr(svc, "__await__"):
                svc = await svc
            await svc.initialize()
            self._svc = svc
        self.calls += 1
        try:
            reply = await asyncio.wait_for(
                self._svc.generate(prompt=prompt, system_prompt=curriculum.TEACHER_CONTRACT,
                                   max_tokens=max_tokens, temperature=0.6,
                                   enable_thinking=False),
                timeout=300)
        except asyncio.TimeoutError:
            return ""
        return str((reply or {}).get("content") or "").split("</think>", 1)[-1].strip()


async def main() -> None:
    from core.database import get_database_manager
    from core.semantics.class_induction import class_from_observations, observe
    from core.semantics.conversation import Conversation
    from core.semantics.lexicon import Lexicon
    import core.semantics.lexicon as lexmod

    await get_database_manager().initialize()
    lexmod._lexicon = Lexicon(path=Path("data") / "lexicon_scaled.json")
    lexmod._lexicon.clear()
    lexicon = lexmod._lexicon
    talk = Conversation()
    teacher = Teacher()

    started = time.time()
    offered = read_ok = 0
    observations: List = []
    by_shape: Counter = Counter()
    unreadable_examples: List[str] = []
    checkpoints: List[Dict] = []

    print(f"budget {BUDGET_SECONDS}s | shapes {len(corpus_mod.SHAPES)} | "
          f"domains {len(corpus_mod.DOMAINS)}", flush=True)

    rounds = 0
    while time.time() - started < BUDGET_SECONDS:
        rounds += 1
        for domain in corpus_mod.DOMAINS:
            if time.time() - started >= BUDGET_SECONDS:
                break
            for shape_name, shape in corpus_mod.SHAPES:
                if time.time() - started >= BUDGET_SECONDS:
                    break
                sentences = await corpus_mod.generate(teacher, domain, shape_name, shape)
                for sentence in sentences:
                    offered += 1
                    reading, _src = await talk.read(sentence)
                    if not reading:
                        if len(unreadable_examples) < 12:
                            unreadable_examples.append(f"{shape_name}: {sentence}")
                        continue
                    read_ok += 1
                    by_shape[shape_name] += 1
                    fresh = observe(sentence, reading[0])
                    observations.extend(fresh)
                    for sighting in fresh:
                        settled = class_from_observations(sighting.word, observations)
                        if settled and not lexicon.entry(sighting.word):
                            lexicon.propose(sighting.word, settled, "read")
                            lexicon.confirm(sighting.word, f"seen as {sighting.slot}")

                elapsed = time.time() - started
                counts = Counter(e.word_class for e in lexicon.known())
                checkpoints.append({"t": round(elapsed, 1), "offered": offered,
                                    "read": read_ok, "words": len(list(lexicon.known())),
                                    **{k: counts.get(k, 0) for k in
                                       ("NOUN", "ADJECTIVE", "VERB")}})
                print(f"  [{elapsed/60:5.1f}m] {domain:22} {shape_name:12} "
                      f"read {read_ok:5}/{offered:5}  vocabulary {len(list(lexicon.known())):5} "
                      f"(N{counts.get('NOUN',0)} A{counts.get('ADJECTIVE',0)} "
                      f"V{counts.get('VERB',0)})", flush=True)
                lexicon.save()

    elapsed = time.time() - started
    counts = Counter(e.word_class for e in lexicon.known())
    print("\n" + "=" * 70)
    print(f"elapsed                : {elapsed/60:.1f} min over {rounds} round(s)")
    print(f"sentences offered      : {offered}")
    print(f"sentences READ         : {read_ok}  ({100*read_ok/max(offered,1):.0f}%)")
    print(f"vocabulary acquired    : {len(list(lexicon.known()))}")
    print(f"  nouns/adjectives/verbs: {counts.get('NOUN',0)} / "
          f"{counts.get('ADJECTIVE',0)} / {counts.get('VERB',0)}")
    print(f"teacher calls          : {teacher.calls}")
    print("read by shape          :", dict(by_shape))
    if unreadable_examples:
        print("unreadable examples    :")
        for line in unreadable_examples[:8]:
            print("   -", line)
    print("=" * 70)
    Path("experiments/edu/EDU-16/scaled_result.json").write_text(json.dumps(
        {"elapsed_min": elapsed / 60, "offered": offered, "read": read_ok,
         "vocabulary": len(list(lexicon.known())), "by_class": dict(counts),
         "by_shape": dict(by_shape), "teacher_calls": teacher.calls,
         "checkpoints": checkpoints, "unreadable": unreadable_examples}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
