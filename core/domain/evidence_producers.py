#!/usr/bin/env python3
"""Evidence producers — adapters from tool output to EvidenceEnvelope.

These live here rather than inside the tools deliberately. `conduct_research`
should know how to research and nothing about concepts: it produces findings,
this module wraps them as evidence, and ConceptIngestionService retains all
semantic authority. A tool that decided what a concept is would become a second
authority over the semantic layer.

The lineage these build is what makes root-evidence independence meaningful:

    source A (independent observation)  ─┐
    source B (independent observation)  ─┼─→ synthesis (derived from A, B, C)
    source C (independent observation)  ─┘

Three genuinely independent sources contribute three roots. One source producing
three findings, two summaries and a memory still resolves to one root, because
every derivative declares the source it came from.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .concept_ingestion import (
    _ROOT_SOURCES,
    EvidenceEnvelope,
    EvidenceSourceType,
    IngestionResult,
    get_concept_ingestion_service,
)

logger = logging.getLogger(__name__)


def _stable_id(prefix: str, *parts: str) -> str:
    """Deterministic evidence id.

    Deterministic so re-processing the same research output reinforces the same
    concepts through the same roots rather than minting fresh ids that would
    each look like independent corroboration.
    """
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()
    return f"{prefix}_{digest[:24]}"


#: Query parameters that identify a referrer or campaign rather than a document.
#: Stripped so the same page reached from two places is one source.
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "ref", "referrer", "source", "src",
})


def canonical_source_key(locator: str) -> str:
    """Canonical identity of an underlying source observation.

    THE ROOT INVARIANT:

        same underlying source observation  -> same epistemic root
        different question / summary / extraction -> different derivative
                                                     envelope, SAME root

    Root ids must therefore be a function of the source alone. They previously
    included the research topic, so one DOI encountered under "fuel cells" and
    again under "electrochemistry" produced two envelope ids and counted as two
    independent roots -- corroboration manufactured by asking a second question.

    Normalises: scheme and host case, `www.`, default ports, trailing slash,
    URL fragments, tracking parameters, and the several spellings of a DOI.
    """
    raw = str(locator or "").strip()
    if not raw:
        return ""

    low = raw.lower()

    # DOIs: doi:10.x, https://doi.org/10.x, https://dx.doi.org/10.x -> 10.x
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if low.startswith(prefix):
            return "doi:" + low[len(prefix):].strip("/")
    if low.startswith("10.") and "/" in low:
        return "doi:" + low.strip("/")

    if "://" not in low:
        return low.strip("/")

    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    parts = urlsplit(low)
    host = parts.netloc
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":80") or host.endswith(":443"):
        host = host.rsplit(":", 1)[0]

    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k not in _TRACKING_PARAMS
    ))
    path = parts.path.rstrip("/") or "/"

    # Fragment dropped: it addresses a location within one document, not a
    # different document.
    return urlunsplit(("https", host, path, query, ""))


def _source_identity(result: Dict[str, Any]) -> Tuple[str, str]:
    """(source_name, canonical_source_key) for one research result."""
    name = str(result.get("source") or result.get("api") or "unknown_source")
    raw = result.get("doi") or result.get("url") or result.get("id") or name
    return name, (canonical_source_key(raw) or name.lower())


#: Sentence boundaries. Deliberately simple: the statement reader declines
#: anything it cannot parse, so an over-split sentence costs a decline, never a
#: wrong assertion.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _statements(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(str(text or "")) if s.strip()]


async def submit_research_result(
    topic: str,
    output: Dict[str, Any],
    *,
    producer: str = "conduct_research",
    request_id: Optional[str] = None,
) -> List[IngestionResult]:
    """Turn one `conduct_research` payload into evidence and ingest it.

    Args:
        topic:   what was researched.
        output:  the tool's `output` dict — expects `raw_results` (per-source)
                 and optionally `synthesis`.
        producer: tool name, recorded as interpretation provenance.
        request_id: caller's id for this research operation, if any.

    Returns one IngestionResult per envelope submitted.

    Raises rather than returning empty when the payload has no usable sources:
    a research call that produced nothing and one whose output could not be read
    are different failures, and only the second is a defect here.
    """
    service = get_concept_ingestion_service()
    await service._ready()

    raw = output.get("raw_results") or output.get("results") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise TypeError(
            f"research output raw_results has type {type(raw).__name__}; "
            f"expected a list of per-source results"
        )

    categories = [str(c).strip().lower() for c in (output.get("categories") or [])
                  if str(c).strip()]
    if not categories:
        raise ValueError(
            f"research on {topic!r} carries no categories; TopicClassifier "
            f"assigns them deterministically and a concept must belong "
            f"somewhere, so inventing a domain here is how one topic acquired 21")
    domain = categories[0]

    results: List[IngestionResult] = []
    source_ids: List[str] = []

    # 1. One ROOT envelope per independent source.
    for entry in raw:
        if not isinstance(entry, dict):
            # A source we cannot attribute is not an independent observation.
            logger.warning(
                "Skipping unattributable research result of type %s for topic %r",
                type(entry).__name__, topic,
            )
            continue
        name, locator = _source_identity(entry)
        content = str(
            entry.get("snippet") or entry.get("summary") or entry.get("description")
            or entry.get("title") or entry.get("data") or ""
        ).strip()
        if not content:
            logger.info("Source %s returned no content for %r; not evidence", name, topic)
            continue

        # ROOT ID IS TOPIC-FREE. The same source met under a different
        # research question must resolve to the same epistemic root.
        eid = _stable_id("ev_src", locator)
        envelope = EvidenceEnvelope(
            evidence_id=eid,
            source_type=EvidenceSourceType.RESEARCH_FINDING,
            source_id=locator,
            producer=producer,
            content=content,
            structured_data={
                # `domain` and `statements` are what the deterministic reader
                # needs. The categories come from TopicClassifier, which is
                # keyword matching -- so the domain a research concept lands in
                # is decided without a model, the same as its structure.
                "domain": domain,
                "statements": _statements(content),
                **{k: v for k, v in entry.items()
                   if k in ("concepts", "title", "url", "authors", "published", "quality")},
            },
        )
        source_ids.append(eid)
        results.append(await service.ingest(envelope))

    if not source_ids:
        logger.warning(
            "Research on %r produced no attributable sources; no evidence recorded",
            topic,
        )
        return results

    # 2. The synthesis is DERIVATIVE. It restates the sources, so it carries
    #    their ids and resolves to their roots rather than adding one of its own.
    synthesis = str(output.get("synthesis") or "").strip()
    if synthesis:
        results.append(await service.ingest(EvidenceEnvelope(
            evidence_id=_stable_id("ev_synthesis", topic, request_id or "", *source_ids),
            source_type=EvidenceSourceType.MEMORY_RETROSPECTIVE,
            source_id=f"synthesis:{topic}",
            producer=producer,
            content=synthesis,
            structured_data={"domain": domain, "statements": _statements(synthesis)},
            derived_from=tuple(source_ids),
        )))

    total = sum(r.accepted for r in results)
    logger.info(
        "Research %r: %d source envelope(s) + synthesis -> %d concept(s) accepted",
        topic, len(source_ids), total,
    )
    return results


__all__ = ["submit_research_result", "submit_learned_rule",
           "submit_demonstration", "submit_tool_capability",
           "submit_tool_invocation", "submit_perception",
           "canonical_source_key"]


async def submit_learned_rule(
    stored,
    derived_from,
    *,
    producer: str = "rule_induction",
) -> "IngestionResult":
    """Project an induced rule into the semantic layer as structure.

    THE TWO LEARNING SYSTEMS DID NOT MEET. Rule induction writes operators to
    unified.learned_rules keyed on predicate identity; concept ingestion writes
    structures to unified.concept_relations keyed on concept id. Both are real
    learning systems, and nothing carried a result from one to the other -- so
    "what Torin has learned" had two answers depending on which store you asked.

    The cost was measurable: CrossDomainGrounder searched 44 learned structures
    for a routing problem structurally identical to MOVE and returned NO_MATCH,
    because the MOVE operator had no representation in the graph it searches.
    Transfer was blocked by absence, not by a weak matcher.

    DERIVATIVE, never a root. A rule is a generalization OF demonstrations, so
    it declares the evidence it was induced from. Ingesting it as a root would
    let the rule count as fresh support for the very concepts its training
    examples already supported.

    The projection is structural: the action is the hub, and each precondition
    and effect becomes an edge. That is the shape the analogy matcher reads --
    a rule with fewer than MIN_STRUCTURE_EDGES edges is not searchable, and
    saying so is more useful than filing an unusable structure.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    service = get_concept_ingestion_service()
    await service._ready()

    rule = stored.rule
    if rule.action is None:
        raise ValueError(
            f"{stored.rule_id}: no action recorded. A rule that describes what "
            f"follows rather than what the agent can do has no operator "
            f"structure to project, and filing it would put a non-operator in "
            f"the store the planner's analogies are drawn from")

    domain = getattr(stored, "domain_id", None)
    if not domain:
        raise ValueError(
            f"{stored.rule_id}: no domain_id. A concept must belong somewhere, "
            f"and inventing a domain for it is how one topic acquired 21")

    action = rule.action
    by_role = {
        "requires": [f for f in sorted(rule.body, key=str) if f != action],
        "adds": sorted(rule.effects.add, key=str),
        "removes": sorted(rule.effects.delete, key=str),
    }

    # Supplied by the caller, which holds the store. `evidence_roots` is a
    # query on RuleStore, not a field on the record -- reading it off the record
    # would silently capture a bound method and file a rule with no lineage.
    roots = tuple(dict.fromkeys(derived_from or ()))
    if not roots:
        raise ValueError(
            f"{stored.rule_id}: no induction roots supplied. A derivative "
            f"source with no lineage cannot be distinguished from a root")

    # PREDICATES, not ground atoms. `AT(?X0, ?X2)` carries variable names bound
    # by this rule alone; `at` is the relation another domain can correspond to.
    operator = {
        "action": action.predicate,
        "arity": action.arity,
        "domain": domain,
        **{role: [{"predicate": f.predicate, "arity": f.arity} for f in facts]
           for role, facts in by_role.items()},
    }

    envelope = EvidenceEnvelope(
        evidence_id=_stable_id("indrule", stored.rule_id),
        source_type=EvidenceSourceType.INDUCED_RULE,
        source_id=stored.rule_id,
        content=(f"{action.predicate} is an operation: " + "; ".join(
            f"{role} {fact}" for role, facts in by_role.items() for fact in facts)),
        producer=producer,
        structured_data={
            "operator": operator,
            "rule_id": stored.rule_id,
            "epistemic_status": getattr(stored.status, "value", str(stored.status)),
        },
        derived_from=roots,
    )
    return await service.ingest(envelope)


async def submit_demonstration(
    example,
    *,
    domain_id: str,
    source_type: "EvidenceSourceType",
    producer: str,
    source_id: Optional[str] = None,
) -> "IngestionResult":
    """Record one observed state transition as a ROOT observation.

    A demonstration is where the substrate's semantic layer touches the world:
    facts held, an action was taken, facts changed. Everything downstream --
    the induced rule, the operator structure, the cross-domain correspondence
    -- is a generalization OF this, and must declare it.

    Without this the chain has no floor. `learned_rule_evidence` recorded the
    demonstration ids that induced a rule, but nothing recorded the
    demonstrations themselves as evidence, so projecting the rule raised
    `dangling lineage: <rule> -> mv_d1, which is not recorded`. That refusal is
    correct: a derivative whose ancestors are missing cannot be told apart from
    a root, and treating it as one would let a rule corroborate itself.

    THE ENVELOPE ID IS THE DEMONSTRATION'S OWN ID, not a minted one. It is
    already the foreign key in `unified.learned_rule_evidence`, and a second
    identity for one observation is a second root for it.

    Only the OBSERVED delta becomes an edge. The before-state is not projected
    as `requires`: a demonstration shows which facts happened to hold, and
    which of them the action needed is precisely what induction decides. An
    observation that asserted requirement would answer the question the learner
    exists to answer.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    if source_type not in _ROOT_SOURCES:
        raise ValueError(
            f"{source_type.value} is derivative; a demonstration is a fresh "
            f"observation and recording it as anything else would make the "
            f"rule induced from it depend on a lineage that does not exist")

    evidence_id = getattr(example, "evidence_id", None)
    if not evidence_id:
        raise ValueError(
            "demonstration carries no evidence_id; the rule store keys its "
            "induction basis on that id, and minting one here would file the "
            "observation under an identity nothing else refers to")
    if not domain_id:
        raise ValueError(f"{evidence_id}: no domain_id; a concept must belong somewhere")

    service = get_concept_ingestion_service()
    await service._ready()

    action = getattr(example, "action", None)
    effects = example.observed_effects
    # The action is the hub, so it is not also listed as a state atom: one
    # predicate proposed twice under two kinds is one concept whose kind
    # depends on which candidate happened to persist first.
    atoms = {f.predicate: f.arity for f in (*example.before, *example.after)}

    observation = {
        "domain": domain_id,
        "action": ({"predicate": action.predicate, "arity": action.arity}
                   if action else None),
        "atoms": [{"predicate": p, "arity": a} for p, a in sorted(atoms.items())],
        "adds": [{"predicate": f.predicate, "arity": f.arity}
                 for f in sorted(effects.add, key=str)],
        "removes": [{"predicate": f.predicate, "arity": f.arity}
                    for f in sorted(effects.delete, key=str)],
    }

    rendered = "; ".join(filter(None, (
        "holds " + ", ".join(str(f) for f in sorted(example.before, key=str)),
        f"action {action}" if action else "no action taken",
        "adds " + ", ".join(str(f) for f in sorted(effects.add, key=str)) if effects.add else "",
        "removes " + ", ".join(str(f) for f in sorted(effects.delete, key=str)) if effects.delete else "",
    )))

    return await service.ingest(EvidenceEnvelope(
        evidence_id=evidence_id,
        source_type=source_type,
        source_id=source_id or f"{domain_id}:{evidence_id}",
        producer=producer,
        content=rendered,
        structured_data={
            "observation": observation,
            "positive": bool(getattr(example, "positive", True)),
        },
    ))


async def submit_tool_capability(tool, *, domain: str = "tools") -> "IngestionResult":
    """Project one tool's DECLARED capability into the semantic layer.

    A tool is an operator the substrate can invoke, and its parameter list is a
    precondition list in a different notation. Until this existed, the concept
    graph knew about operators Torin had LEARNED and nothing about the 371 it
    could already perform -- so cross-domain grounding could recognise an
    unfamiliar situation as a learned rule but never as something it had a tool
    for.

    IMPORTED_KNOWLEDGE, and a root: the declaration is read from the tool
    itself, which is the origin of that claim. It is not a restatement of
    anything earlier, so it has no lineage to declare.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    name = str(getattr(tool, "name", "") or "").strip()
    if not name:
        raise ValueError(f"{type(tool).__name__} has no name; a tool with no "
                         f"identity cannot be an operator in the store")

    parameters = getattr(tool, "parameters", None) or []
    required, optional = [], []
    for parameter in parameters:
        label = str(getattr(parameter, "name", "") or "").strip()
        if not label:
            continue
        (required if getattr(parameter, "required", True) else optional).append(label)

    profile = getattr(tool, "capability_profile", None)
    provides = sorted({
        getattr(c.capability, "value", str(c.capability))
        for c in (getattr(profile, "capabilities", None) or [])
    }) if profile else []

    service = get_concept_ingestion_service()
    await service._ready()
    return await service.ingest(EvidenceEnvelope(
        evidence_id=_stable_id("toolcap", name),
        source_type=EvidenceSourceType.IMPORTED_KNOWLEDGE,
        source_id=f"tool:{name}",
        producer="tool_registry",
        content=(f"{name} requires {required or 'nothing'}, "
                 f"accepts {optional or 'nothing'}, provides {provides or 'nothing'}"),
        structured_data={"capability": {
            "tool": name,
            "domain": str(getattr(getattr(tool, "category", None), "value", domain)),
            "description": str(getattr(tool, "description", "") or ""),
            "safety": str(getattr(getattr(tool, "safety_level", None), "value", "")
                          or "undeclared"),
            "required": required,
            "optional": optional,
            "provides": provides,
        }},
    ))


#: Invocation SHAPES already submitted in this process. A tool called ten
#: thousand times with the same arguments is one observation about that tool
#: repeated, not ten thousand independent ones -- and the envelope id already
#: collapses them in the store. This only stops the redundant round trip.
_SEEN_INVOCATIONS: set = set()


async def submit_tool_invocation(
    tool_name: str,
    parameters: Dict[str, Any],
    succeeded: bool,
    *,
    category: str = "tools",
) -> Optional["IngestionResult"]:
    """Record that a tool was actually invoked, and how it went.

    Separate from the tool's declaration on purpose. A tool that is registered
    and has never run, and one that has done work, are different epistemic
    states, and a store that cannot tell them apart reports coverage it does not
    have. The declaration proposes the operator; this is what OBSERVES it.

    Keyed on the invocation SHAPE -- tool, argument names, outcome -- not on the
    argument values. Values are the instance; the shape is what recurs, and
    minting a root per value would let one tool called in a loop out-corroborate
    every other source in the store.

    Returns None when this shape has already been recorded in this process.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    name = str(tool_name or "").strip()
    if not name:
        raise ValueError("a tool invocation with no tool name has nothing to observe")

    supplied = sorted(str(k) for k in (parameters or {}))
    key = (name, tuple(supplied), bool(succeeded))
    if key in _SEEN_INVOCATIONS:
        return None
    _SEEN_INVOCATIONS.add(key)

    service = get_concept_ingestion_service()
    await service._ready()
    return await service.ingest(EvidenceEnvelope(
        evidence_id=_stable_id("toolobs", name, ",".join(supplied), str(bool(succeeded))),
        source_type=EvidenceSourceType.TOOL_OBSERVATION,
        source_id=f"tool:{name}",
        producer="tool_registry",
        content=(f"{name} was invoked with {supplied or 'no arguments'} and "
                 f"{'succeeded' if succeeded else 'failed'}"),
        structured_data={"capability": {
            "tool": name,
            "domain": category,
            "required": supplied,
            "provides": [f"{name}_{'succeeded' if succeeded else 'failed'}"],
        }},
    ))


async def submit_perception(
    source: str,
    data_type: str,
    content: Dict[str, Any],
    *,
    domain: str = "substrate",
) -> Optional["IngestionResult"]:
    """Record a perceived state of something the substrate can name.

    PERCEPTION's live producer is health monitoring: a named component observed
    in a named condition. That is already a subject and a state -- the typed
    fields carry it, so nothing has to interpret the message text.

    Returns None when the input names no subject. A perception with nothing to
    be about is not evidence of anything, and filing it under the source name
    would make `health_monitoring` a concept.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    payload = content or {}
    subject = str(payload.get("component") or payload.get("subject") or "").strip()
    if not subject:
        return None
    state = str(payload.get("severity") or payload.get("status")
                or payload.get("state") or "").strip()

    concepts = [{"label": subject, "kind": "entity", "domains": [domain],
                 "description": str(payload.get("message") or "")[:400],
                 "relationships": [["has_status", state]] if state else []}]
    if state:
        concepts.append({"label": state, "kind": "state", "domains": [domain]})

    service = get_concept_ingestion_service()
    await service._ready()
    return await service.ingest(EvidenceEnvelope(
        evidence_id=_stable_id("percept", source, data_type, subject, state),
        source_type=EvidenceSourceType.PERCEPTION,
        source_id=f"{source}:{data_type}",
        producer=str(source),
        content=f"{subject} observed as {state or 'unspecified'} via {source}",
        structured_data={"concepts": concepts},
    ))
