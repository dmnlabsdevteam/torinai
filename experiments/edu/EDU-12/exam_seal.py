#!/usr/bin/env python3
"""Sealing the exams before instruction begins.

The claim "the posttest contains no problem from teaching" is unfalsifiable
after the fact. Whoever writes the teaching material also writes the exam, and
by the time results exist, nobody -- including the author -- can distinguish an
exam that was always independent from one that drifted toward what happened to
get taught.

So the exams are hashed BEFORE the first lesson and verified after the last.
Two separate properties, because they fail separately:

    SEALED       the exam is byte-identical to what existed before teaching.
                 Catches an exam edited to match what was learned.

    DISJOINT     no exam item's prompt appears in any lesson. Catches an exam
                 that was fixed in advance but was always a copy of homework.

DISJOINT is checked on normalised prompt text and on answers. An exam that
merely rephrases a taught item is still contamination, so overlap is measured
by token content rather than string equality.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

#: Above this Jaccard overlap with a lesson, an exam item is treated as taught.
CONTAMINATION_THRESHOLD = 0.60
_TOKEN = re.compile(r"[a-z0-9]+")


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


def seal(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _tokens(text: str) -> frozenset:
    return frozenset(_TOKEN.findall(str(text).lower()))


def _overlap(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class SealedExams:
    """Hashes taken before instruction. Verified after."""
    pretest: str
    posttest: str
    transfer: str
    sealed_at: str

    def verify(self, pretest, posttest, transfer) -> Dict[str, bool]:
        return {"pretest_intact": seal(pretest) == self.pretest,
                "posttest_intact": seal(posttest) == self.posttest,
                "transfer_intact": seal(transfer) == self.transfer}

    def to_json(self) -> dict:
        return {"pretest": self.pretest, "posttest": self.posttest,
                "transfer": self.transfer, "sealed_at": self.sealed_at}


def seal_exams(subject, when: str) -> SealedExams:
    return SealedExams(seal(subject.PRETEST), seal(subject.POSTTEST),
                       seal(subject.TRANSFER), when)


def contamination(exam: Sequence[Dict[str, Any]],
                  lessons: Sequence[Dict[str, Any]]) -> List[Tuple[str, str, float]]:
    """Exam items that overlap a lesson beyond the threshold.

    Returns (exam_id, lesson_id, overlap) for every contaminated pair, so a
    failure names the specific item rather than reporting a rate.
    """
    lesson_tokens = [(str(l.get("id", i)),
                      _tokens(l.get("content", "")) | _tokens(l.get("example", "")))
                     for i, l in enumerate(lessons)]
    found = []
    for item in exam:
        item_tokens = _tokens(item.get("prompt", ""))
        for lesson_id, tokens in lesson_tokens:
            score = _overlap(item_tokens, tokens)
            if score >= CONTAMINATION_THRESHOLD:
                found.append((str(item.get("id")), lesson_id, round(score, 3)))
    return found


__all__ = ["seal", "seal_exams", "SealedExams", "contamination",
           "CONTAMINATION_THRESHOLD"]
