#!/usr/bin/env python3
"""Semantic extraction — a typed subsystem, not a prompt helper.

Torin performs three operations that can all be expressed as prompts and must
NOT therefore share an execution mode or an output contract:

    GENERATIVE REASONING      may deliberate, explore, hypothesise
    STRUCTURED INTERPRETATION must satisfy a typed output contract
    VERIFICATION              an independent authority decides acceptance

Concept extraction is the second. It was implemented as the first, and the
consequence was measured rather than argued. On the live server, extracting from
one paragraph:

    reasoning mode      ~3545 tokens   ~100 s   INTERMITTENTLY no payload
    extraction mode         90 tokens    0.7 s   5/5 byte-identical

With deliberation on, the answer is whatever survives after reasoning consumes
the budget; three of six control-corpus queries returned nothing and the graph
was built incompletely. Note that `response_format: json_schema` did NOT fix it:
a schema constrains what an answer may look like IF one is produced, it does not
make the model allocate budget to producing one.

Two independent questions, therefore two enums:

    did extraction EXECUTE correctly?      ExtractionExecutionStatus
    what did a successful extraction SEE?  ExtractionSemanticOutcome

Collapsing them puts TIMEOUT and NO_CONCEPTS in one namespace, and `0 concepts`
then means both "this evidence contains none" and "we never read it".
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .domain_types import ConceptType

logger = logging.getLogger(__name__)


class ExtractionExecutionStatus(Enum):
    """Did the extraction operation execute correctly?"""
    SUCCESS = "success"
    TIMEOUT = "timeout"
    MODEL_ERROR = "model_error"
    CLIENT_ERROR = "client_error"
    EMPTY_CONTENT = "empty_content"
    PARSE_ERROR = "parse_error"
    SCHEMA_VIOLATION = "schema_violation"


class ExtractionSemanticOutcome(Enum):
    """What a SUCCESSFUL extraction observed. UNKNOWN whenever it did not run."""
    CONCEPTS_FOUND = "concepts_found"
    NO_CONCEPTS = "no_concepts"
    UNKNOWN = "unknown"


#: Execution failures worth one more attempt. NO_CONCEPTS is deliberately absent:
#: retrying until concepts appear is not retry, it is sampling until the answer
#: is liked.
RETRYABLE = frozenset({
    ExtractionExecutionStatus.TIMEOUT,
    ExtractionExecutionStatus.CLIENT_ERROR,
    ExtractionExecutionStatus.MODEL_ERROR,
    ExtractionExecutionStatus.EMPTY_CONTENT,
    ExtractionExecutionStatus.PARSE_ERROR,
})


@dataclass(frozen=True)
class ExtractionResult:
    """One attempt to interpret one observation.

    Invariants, asserted in __post_init__ because they are the whole point:

        SUCCESS + CONCEPTS_FOUND  -> candidates > 0
        SUCCESS + NO_CONCEPTS     -> candidates == 0, a legitimate negative
        anything else             -> semantic_outcome is UNKNOWN and an empty
                                     candidate list is NOT evidence of absence
    """
    execution_status: ExtractionExecutionStatus
    semantic_outcome: ExtractionSemanticOutcome
    evidence_id: str
    extractor_id: str
    extractor_version: str

    candidates: Tuple[Any, ...] = ()
    attempt_id: str = field(default_factory=lambda: f"ext_{uuid.uuid4().hex[:16]}")
    attempt_number: int = 1
    model_id: Optional[str] = None
    execution_mode: str = "unknown"
    prompt_version: str = "v0"

    latency_ms: int = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    failure_reason: Optional[str] = None
    request_hash: Optional[str] = None
    output_hash: Optional[str] = None

    def __post_init__(self):
        ok = self.execution_status is ExtractionExecutionStatus.SUCCESS
        if not ok and self.semantic_outcome is not ExtractionSemanticOutcome.UNKNOWN:
            raise ValueError(
                f"{self.execution_status.value} cannot carry a semantic outcome "
                f"of {self.semantic_outcome.value}: extraction did not run, so "
                f"nothing was observed"
            )
        if ok and self.semantic_outcome is ExtractionSemanticOutcome.CONCEPTS_FOUND \
                and not self.candidates:
            raise ValueError("CONCEPTS_FOUND with no candidates")
        if ok and self.semantic_outcome is ExtractionSemanticOutcome.NO_CONCEPTS \
                and self.candidates:
            raise ValueError("NO_CONCEPTS with candidates present")

    @property
    def is_retryable(self) -> bool:
        return self.execution_status in RETRYABLE

    @property
    def observed_absence(self) -> bool:
        """True only when an empty result MEANS the evidence held no concepts."""
        return (self.execution_status is ExtractionExecutionStatus.SUCCESS
                and self.semantic_outcome is ExtractionSemanticOutcome.NO_CONCEPTS)



async def record_attempt(db, result: ExtractionResult) -> None:
    """Persist an attempt. Separate from evidence, and never a root."""
    await db.execute_query(
        """INSERT INTO unified.extraction_attempts
               (attempt_id, evidence_id, extractor_id, extractor_version, model_id,
                execution_mode, prompt_version, execution_status, semantic_outcome,
                failure_reason, finish_reason, candidate_count, attempt_number,
                latency_ms, prompt_tokens, completion_tokens, request_hash, output_hash)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
           ON CONFLICT (attempt_id) DO NOTHING""",
        (result.attempt_id, result.evidence_id, result.extractor_id,
         result.extractor_version, result.model_id, result.execution_mode,
         result.prompt_version, result.execution_status.value,
         result.semantic_outcome.value, result.failure_reason, result.finish_reason,
         len(result.candidates), result.attempt_number, result.latency_ms,
         result.prompt_tokens, result.completion_tokens, result.request_hash,
         result.output_hash),
        commit=True)


__all__ = [
    "ExtractionExecutionStatus", "ExtractionSemanticOutcome", "ExtractionResult",
]
