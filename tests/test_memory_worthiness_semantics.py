"""Retention must measure the episode, not the caller's formatting.

The filter previously derived retention from `reasoning_steps`, which is
`len(reasoning_trace)` -- a presentation property. Two identical cognitive
episodes were graded differently because one writer emitted a list of strings
and the other emitted a structured result. These oracles pin the property that
replaced it.
"""
import pytest

from core.memory.utils.memory_worthiness import (
    MemoryWorthinessMetadata, CognitionMetadata, NoveltyMetadata,
    CriticalityMetadata, QueryMetadata, OutcomeMetadata,
    QueryType, ConsequenceLevel, DecisionType, ReusabilityLevel,
)
from core.memory.utils.memory_filter import MemoryFilter


@pytest.fixture
def f():
    return MemoryFilter()


def _meta(cog=None, nov=None, out=None, crit=None, q=None):
    return MemoryWorthinessMetadata(
        cognition=cog or CognitionMetadata(),
        novelty=nov or NoveltyMetadata(),
        criticality=crit or CriticalityMetadata(
            decision_type=DecisionType.INFORMATIONAL,
            consequence_level=ConsequenceLevel.LOW,
            reusability=ReusabilityLevel.NONE),
        query=q or QueryMetadata(query_type=QueryType.FACTUAL_LOOKUP),
        outcome=out or OutcomeMetadata(),
    )


def test_verbosity_does_not_change_the_verdict(f):
    """The defect, stated directly: two callers with the same cognition and
    different trace formats must be graded the same."""
    verbose = _meta(cog=CognitionMetadata(reasoning_steps=8),
                    out=OutcomeMetadata(actionable=True))
    structured = _meta(cog=CognitionMetadata(reasoning_steps=0),
                       out=OutcomeMetadata(actionable=True))

    a, b = f._check_hard_store(verbose), f._check_hard_store(structured)
    assert a.should_store is b.should_store is True
    assert a.rule_matched == b.rule_matched, (
        "the matched rule must not depend on how the caller formatted its trace"
    )


def test_padding_alone_buys_nothing(f):
    """A long trace with no semantic content was a hard store at >= 5 steps."""
    padded = _meta(cog=CognitionMetadata(reasoning_steps=12))
    assert f._check_hard_store(padded).should_store is False
    assert f._check_hard_reject(padded).rule_matched == "trivial_factual_lookup"


@pytest.mark.parametrize("label,meta_kwargs,expected_rule", [
    ("belief contradicted", {"nov": NoveltyMetadata(contradicts_existing=True)}, "belief_revision"),
    ("had to backtrack", {"cog": CognitionMetadata(required_backtracking=True)}, "belief_revision"),
    ("uncertainty resolved", {"cog": CognitionMetadata(uncertainty_resolved=True)}, "epistemic_change"),
    ("tried several strategies", {"cog": CognitionMetadata(used_multiple_strategies=True)}, "strategy_adaptation"),
    ("affects future action", {"out": OutcomeMetadata(actionable=True)}, "behavioral_consequence"),
    ("created new knowledge", {"out": OutcomeMetadata(created_new_knowledge=True)}, "behavioral_consequence"),
    ("first occurrence", {"nov": NoveltyMetadata(first_occurrence=True)}, "novel_connection"),
    ("bridges knowledge", {"nov": NoveltyMetadata(connects_disparate_knowledge=True)}, "novel_connection"),
])
def test_semantic_signals_store_with_no_trace_at_all(f, label, meta_kwargs, expected_rule):
    """Each of these is a property of the episode. None requires the caller to
    have serialised its thinking into strings."""
    d = f._check_hard_store(_meta(**meta_kwargs))
    assert d.should_store is True, f"{label} was not retained"
    assert d.rule_matched == expected_rule


def test_genuinely_trivial_lookup_is_still_rejected(f):
    """Removing the step-count clause must not make the reject unreachable."""
    r = f._check_hard_reject(_meta())
    assert r.should_store is False
    assert r.rule_matched == "trivial_factual_lookup"


def test_a_lookup_that_changed_something_is_not_trivial(f):
    """The remaining reject clauses are about the episode, so a lookup that
    resolved uncertainty or led to action must escape it."""
    for kw in ({"cog": CognitionMetadata(uncertainty_resolved=True)},
               {"out": OutcomeMetadata(actionable=True)},
               {"nov": NoveltyMetadata(is_novel=True)}):
        assert f._check_hard_reject(_meta(**kw)).rule_matched != "trivial_factual_lookup"


def test_no_retention_rule_reads_the_step_count():
    """Asserted on the source: the count may still be RECORDED as descriptive
    metadata, but it must not appear in a store or reject decision."""
    import inspect
    for fn in (MemoryFilter._check_hard_store, MemoryFilter._check_hard_reject,
               MemoryFilter._check_soft_threshold):
        src = inspect.getsource(fn)
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        assert "reasoning_steps" not in code, (
            f"{fn.__name__} still decides retention from the trace length"
        )


def test_complexity_is_not_derived_from_trace_length():
    """Closing the direct dependency was not enough: complexity_score added
    0.4 for five trace items, and `substantive_analysis` stores at 0.3 -- so
    verbosity bought retention through complexity instead."""
    import inspect
    from core.agents.memory_agent import MemoryAgent
    src = inspect.getsource(MemoryAgent)
    body = src.split("complexity_score = 0.0", 1)[1].split("complexity_score = min(", 1)[0]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    assert "reasoning_step_count" not in code, (
        "complexity must not be purchased with trace length"
    )


# --------------------------------------------------------------------------
# Exemption: records are not candidates for retention.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tags,expected_class", [
    (["task_outcome", "meta_learning"], "task outcome"),
    (["outcome_success"], "task outcome"),
    (["governance_block", "safety_validation"], "governance decision"),
    (["safety_validation"], "safety event"),
    (["meta_learning", "strategy_adaptation"], "learning update"),
    (["cross_domain_mapping"], "mapping verdict"),
    (["critical_failure"], "critical failure"),
])
def test_record_classes_bypass_worthiness(f, tags, expected_class):
    """These events are evidence that something happened. Judging them by
    novelty produced survivorship bias: failures scored high-consequence and
    were kept, ordinary successes were discarded, so the measured success rate
    could never rise."""
    reason = f.exemption_for(tags=tags)
    assert reason is not None, f"{tags} was not exempt"
    assert expected_class in reason


def test_observation_events_remain_exempt(f):
    """The pre-existing raw_event exemption must survive consolidation."""
    assert f.exemption_for(tags=["x"], raw_event={"event": "health_measured"})


def test_ordinary_reasoning_is_still_evaluated(f):
    """Exemption must not swallow the episodes worthiness exists to judge."""
    assert f.exemption_for(tags=["reasoning", "neural", "multi_step"]) is None
    assert f.exemption_for(tags=[], raw_event=None) is None


def test_exemption_policy_lives_in_one_place():
    """The memory agent must consult the filter rather than carry a second copy
    of the policy that can drift from it."""
    import inspect
    from core.agents.memory_agent import MemoryAgent
    src = inspect.getsource(MemoryAgent.store_memory)
    assert "exemption_for" in src


# --------------------------------------------------------------------------
# Calibration must measure something that still has semantics.
# --------------------------------------------------------------------------

def test_calibration_no_longer_compares_a_count_to_itself(f):
    """It compared claimed_steps against len(reasoning_trace) -- two readings of
    the same number, measuring a caller disagreeing with itself about a value
    that no longer means anything."""
    import inspect
    src = inspect.getsource(f._calibration_check)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "len(reasoning_trace)" not in code
    assert "claimed_steps" not in code


def test_calibration_flags_uncorroborated_complexity(f):
    """A high self-assessed complexity with no semantic property behind it is
    the drift worth catching."""
    before = f.metrics.calibration_mismatches
    f.policy.setdefault("calibration_settings", {})["sample_rate"] = 1.0
    f._calibration_check(_meta(cog=CognitionMetadata(complexity_score=0.9)), None)
    assert f.metrics.calibration_mismatches == before + 1

    # ... and does not fire when the claim is backed by a real signal.
    mid = f.metrics.calibration_mismatches
    f._calibration_check(
        _meta(cog=CognitionMetadata(complexity_score=0.9, uncertainty_resolved=True)), None)
    assert f.metrics.calibration_mismatches == mid


# --------------------------------------------------------------------------
# The policy file is the stated contract. It must match the implementation.
# --------------------------------------------------------------------------

def _declared_and_implemented():
    import json, re, inspect
    pol = json.load(open("config/memory_filtering_policy.json"))
    declared = set()

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("name"), str):
                declared.add(o["name"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(pol)
    src = "".join(inspect.getsource(getattr(MemoryFilter, m)) for m in
                  ("_check_hard_store", "_check_hard_reject", "_check_soft_threshold"))
    implemented = set(re.findall(r'rule_matched="([a-z_]+)"', src))
    # Sentinels, not rules.
    implemented -= {"none", "below_soft_thresholds"}
    return declared, implemented


def test_policy_declares_no_rule_the_code_does_not_implement():
    """`deep_reasoning` and `multi_level_inference` were still declared after
    being removed from the code -- an operator reading the policy would believe
    retention depended on reasoning-step counts that nothing reads."""
    declared, implemented = _declared_and_implemented()
    # Calibration checks are declared under their own section and are not rules.
    phantom = declared - implemented - {"complexity_corroboration"}
    assert not phantom, f"policy declares rules that do not exist: {sorted(phantom)}"


def test_every_implemented_rule_is_declared():
    """The five semantic rules that replaced the verbosity ones must appear in
    the stated contract, not only in code."""
    declared, implemented = _declared_and_implemented()
    undeclared = implemented - declared
    assert not undeclared, f"implemented but undeclared: {sorted(undeclared)}"


def test_no_orphaned_thresholds_in_policy():
    """`min_reasoning_steps` remained as a tunable knob that controlled
    nothing."""
    import json
    text = open("config/memory_filtering_policy.json").read()
    assert "min_reasoning_steps" not in text
    pol = json.load(open("config/memory_filtering_policy.json"))

    def find(o, key):
        if isinstance(o, dict):
            if key in o:
                return o[key]
            for v in o.values():
                r = find(v, key)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v, key)
                if r is not None:
                    return r
        return None

    assert find(pol, "min_likely_reference_count") is not None, (
        "the threshold the soft rule actually reads must be declared"
    )
