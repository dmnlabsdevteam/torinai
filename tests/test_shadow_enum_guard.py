#!/usr/bin/env python3
"""Architectural guard: one concept, one enum.

Torin has been broken three separate times by the same defect — an Enum defined
twice with near-identical members. Enum equality is identity-based, so the
copies compare unequal while printing the same string, and the failure surfaces
as a plausible negative result rather than an error:

  ReasoningStrategy  (universal_domain_master vs cross_domain_reasoner)
      strategies.get(context.strategy) -> None
      -> "Unsupported reasoning strategy", success=False, confidence=0.0
      -> all SEVEN cross-domain strategies unreachable, reading as
         "these domains have nothing in common"

  ConceptType        (universal_domain_master vs domain_types)
      12 members each, 10 shared; relation/rule vs relationship/structure
      -> a concept typed by one was untypeable by the other

  MemoryType         (core_types vs memory.utils.interfaces)
      identical members, different classes
      -> EPISODIC == EPISODIC -> False, silently, while both print 'episodic'

These tests fail on the CLASS of defect, not on the three known instances, so a
fourth cannot be introduced quietly.
"""

import ast
import os
from collections import defaultdict

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(REPO, "core")

#: KNOWN DEBT, not permission.
#:
#: Each of these is a real shadow enum found by this guard on the day it was
#: written. They are listed so a NEW one fails immediately rather than being
#: lost in a long-red test — not because duplication is acceptable here. The
#: list should only ever shrink; adding to it needs the same justification as
#: adding any second authority for one concept.
#:
#: Resolved so far: ConceptType, ReasoningStrategy, DomainType (all collapsed
#: onto their owning module), MemoryType (the core_types copy deleted).
KNOWN_SHADOW_DEBT = {
    "ActionCategory",     # slack_notifier vs unified_governance_trigger_system
    "AgentType",          # security_types vs agents vs unified_llm
    "AlertSeverity",      # security_types vs health_interfaces vs monitoring_coordinator
    "AttackType",         # security_training_pipeline vs active_defense_types
    "DecisionTier",       # slack_notifier vs unified_governance_trigger_system
    "DecisionType",       # memory_worthiness vs autonomous_interfaces
    "DeviceType",         # lightweight_llm vs unified_llm
    "EvolutionType",      # directive_types vs directive_evolution_engine
    "ExperimentStatus",   # hypothesis_testing vs chaos.types
    "HealthStatus",       # FIVE definitions across learning/health/system
    "LogicType",          # logical_integration vs advanced_proof_engine
    "PatternType",        # memory_worthiness vs digital_footprint
    "Priority",           # security_types vs autonomous.shared_types
    "RecoveryAction",     # security_types vs system_watchdog vs recovery_manager
    "ServiceStatus",      # service_configuration vs environment_state
    "TestStatus",         # testing_validation_tools vs directive_ab_testing
    "ViolationSeverity",  # governance_agent vs commitment_contracts
}


def _enum_definitions():
    """Every `class X(Enum)` under core/, as name -> [file:line]."""
    found = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(CORE):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {
                    b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                    for b in node.bases
                }
                if bases & {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}:
                    rel = os.path.relpath(path, REPO)
                    found[node.name].append(f"{rel}:{node.lineno}")
    return found


def test_no_new_shadow_enum():
    """The guard. A NEW Enum name with two definitions fails immediately."""
    dupes = {
        name: sites
        for name, sites in _enum_definitions().items()
        if len(sites) > 1 and name not in KNOWN_SHADOW_DEBT
    }
    assert not dupes, (
        "Enum defined more than once — identity-based equality means the copies "
        "compare unequal while printing the same value, so the failure surfaces "
        "as a plausible negative result rather than an error:\n"
        + "\n".join(f"  {n}: {', '.join(s)}" for n, s in sorted(dupes.items()))
    )


def test_resolved_shadows_stay_resolved():
    """The ones already collapsed must not reappear.

    ReasoningType, ReasoningMode and InferenceMethod joined this list on
    2026-08-24. ReasoningType had THREE definitions (reasoning_interfaces,
    abstract_reasoning_engine, unified_quantum_reasoning_system) and
    ReasoningMode had three meanings under one name -- routing, uncertainty, and
    a mislabelled copy of ReasoningType in enhanced_logical_agent.
    """
    defs = _enum_definitions()
    for name in ("ConceptType", "ReasoningStrategy", "DomainType", "MemoryType",
                 "ReasoningType", "ReasoningMode", "InferenceMethod"):
        sites = defs.get(name, [])
        assert len(sites) <= 1, (
            f"{name} was collapsed to one authority and has been redefined: "
            f"{', '.join(sites)}"
        )


def test_shadow_debt_does_not_grow():
    """Every debt entry must still be a real duplicate.

    Keeps the list honest: an entry that has been fixed is removed rather than
    left behind granting silent permission for a future redefinition.
    """
    defs = _enum_definitions()
    stale = [n for n in KNOWN_SHADOW_DEBT if len(defs.get(n, [])) <= 1]
    assert not stale, (
        f"KNOWN_SHADOW_DEBT lists names that are no longer duplicated: {stale}. "
        f"Remove them so the guard covers them again."
    )


def test_concept_type_has_one_authority():
    """ConceptType is domain_types'. Everything else imports it."""
    from core.domain.domain_types import ConceptType as canonical
    from core.integration.universal_domain_master import ConceptType as master
    from core.domain import ConceptType as pkg

    assert master is canonical, "universal_domain_master must import, not redeclare"
    assert pkg is canonical, "core.domain must re-export the canonical enum"


def test_reasoning_strategy_has_one_authority():
    """The reasoner owns the strategies, so it owns the vocabulary naming them."""
    from core.domain.cross_domain_reasoner import ReasoningStrategy as canonical
    from core.integration.universal_domain_master import ReasoningStrategy as master

    assert master is canonical

    # The dispatch table must actually accept what the master sends. This is
    # the check that would have caught the original defect.
    from core.domain.cross_domain_reasoner import CrossDomainReasoner

    reasoner = CrossDomainReasoner.__new__(CrossDomainReasoner)
    reasoner.__init__(domain_registry=None, universal_ontology=None)
    for member in canonical:
        assert member in reasoner.strategies, (
            f"{member} has no handler; a strategy the master can send but the "
            f"reasoner cannot dispatch returns success=False, which is "
            f"indistinguishable from 'no mappings found'"
        )


@pytest.mark.asyncio
async def test_persisted_concept_kinds_deserialize():
    """Every stored concept_kind must round-trip through the canonical enum."""
    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(REPO) / ".env.production", override=True)

    from core.database import get_database_manager
    from core.domain.domain_types import ConceptType

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    rows = await db.execute_query(
        "SELECT DISTINCT concept_kind FROM unified.concepts WHERE concept_kind IS NOT NULL",
        fetch_all=True,
    ) or []
    bad = []
    for row in rows:
        try:
            ConceptType(row["concept_kind"])
        except ValueError:
            bad.append(row["concept_kind"])
    assert not bad, (
        f"stored concept_kind values that no longer deserialize: {bad}. "
        f"Renaming a member orphans every row carrying the old string."
    )


def test_ontology_maps_every_canonical_concept_type():
    """The compatibility table must cover the whole vocabulary.

    A member missing here is silently incompatible with every universal
    category rather than raising, so the concept simply never maps.
    """
    import inspect

    from core.domain.domain_types import ConceptType
    from core.domain.universal_ontology import UniversalOntology

    src = inspect.getsource(UniversalOntology._are_types_compatible)
    missing = [m.name for m in ConceptType if f"ConceptType.{m.name}" not in src]
    assert not missing, (
        f"ConceptType members absent from the ontology compatibility map: "
        f"{missing}. They cannot map to any universal category."
    )
