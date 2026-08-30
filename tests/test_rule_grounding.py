"""Learned rules become planning operators only when they are entitled to.

Grounding is the join between the two halves: rules are lifted, the planner is
propositional. The join is also where the execution gate could be quietly
widened, so admissibility is checked here rather than assumed from the caller.

Every test runs model-free; composition that reached for a model would not be
evidence of anything the substrate owns.
"""
import pytest

from core.learning.rule_grounding import (
    DEFAULT_MAX_OPERATORS, GroundOperator, constants_in, ground_for_problem,
    ground_rule,
)
from core.learning.rule_induction import (
    CandidateRule, Fact, RuleEffects, TrainingExample, get_rule_inducer,
)
from core.learning.rule_store import EpistemicStatus, StoredRule, from_json, to_json
from core.model_policy import (
    ModelPolicy, assert_model_free, reset_model_telemetry, set_model_policy,
)
from core.reasoning.temporal_reasoning import PlanningStatus, TemporalReasoningSystem

F = Fact.parse


@pytest.fixture(autouse=True)
def strict():
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()
    yield
    assert_model_free("rule grounding")
    set_model_policy(previous)
    reset_model_telemetry()


def move_example(who, a, b, evidence_id, opened=True, path=True, acted=True, at=True):
    before = []
    if at:
        before.append(F(f"AT({who},{a})"))
    if path:
        before.append(F(f"PATH({a},{b})"))
    if opened:
        before.append(F(f"OPEN({b})"))
    before = tuple(before)
    ok = opened and path and acted and at
    after = (tuple(f for f in before if f != F(f"AT({who},{a})"))
             + (F(f"AT({who},{b})"),)) if ok else before
    return TrainingExample(
        before=before, action=F(f"MOVE({who},{a},{b})") if acted else None,
        after=after, positive=ok, evidence_id=evidence_id,
    )


@pytest.fixture
def move_rule():
    """Includes the counter-demonstration for acting from elsewhere.

    Without it AT(?X,?A) is minimized away as unsupported and the rule lets an
    agent move from a room it is not in -- correct induction from an incomplete
    corpus, and invisible until something composes the rule.
    """
    teaching = [
        move_example("a", "R1", "R2", "t1"), move_example("b", "R3", "R4", "t2"),
        move_example("c", "R5", "R6", "n1", opened=False),
        move_example("d", "R7", "R8", "n2", path=False),
        move_example("e", "R9", "R10", "n3", acted=False),
        move_example("h", "R15", "R16", "n4", at=False),
    ]
    return get_rule_inducer().induce(teaching).rule


WORLD = [F("AT(z,HALL)"), F("PATH(HALL,LAB)"), F("OPEN(LAB)"),
         F("PATH(LAB,VAULT)"), F("OPEN(VAULT)")]
GOAL = [F("AT(z,VAULT)")]


def stored(rule, status=EpistemicStatus.VALIDATED, rule_id="rule_test"):
    return StoredRule(rule_id=rule_id, rule=rule, status=status)


# ------------------------------------------------------------- admissibility

@pytest.mark.parametrize("status", [
    EpistemicStatus.CANDIDATE, EpistemicStatus.SUPPORTED, EpistemicStatus.REFUTED,
])
def test_only_validated_rules_become_operators(move_rule, status):
    """The ablation proved this gate causally controls derivation. Planning must
    not widen it."""
    report = ground_for_problem([stored(move_rule, status)], WORLD, GOAL)
    assert report.operators == []
    assert "not executable" in next(iter(report.rules_skipped.values()))


def test_a_validated_rule_is_grounded(move_rule):
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL)
    assert report.operators
    assert report.rules_used == ["rule_test"]


def test_a_rule_with_no_action_is_not_a_planning_operator():
    """A rule recording what follows is not a rule about what the agent can do.
    Offering it would let the planner 'achieve' a goal by asserting the world
    changes on its own."""
    inference_only = CandidateRule(
        body=frozenset({Fact("NAL", ("?X",))}),
        effects=RuleEffects(add={Fact("ZOR", ("?X",))}),
    )
    report = ground_for_problem([stored(inference_only)], [F("NAL(a)")], [F("ZOR(a)")])
    assert report.operators == []
    assert "no action recorded" in next(iter(report.rules_skipped.values()))


def test_rules_stored_before_action_existed_read_back_and_are_excluded(move_rule):
    """v1 encodings genuinely do not record the action. Reading them is right;
    inferring one would invent provenance."""
    v1 = to_json(move_rule)
    v1["schema_version"] = 1
    v1.pop("action")

    recovered = from_json(v1)
    assert recovered.action is None
    assert recovered.body == move_rule.body

    report = ground_for_problem([stored(recovered)], WORLD, GOAL)
    assert report.operators == []


def test_an_unreadable_schema_version_is_still_refused(move_rule):
    payload = to_json(move_rule)
    payload["schema_version"] = 99
    with pytest.raises(ValueError):
        from_json(payload)


# ------------------------------------------------------------------ grounding

def test_constants_exclude_variables(move_rule):
    assert constants_in(WORLD) == {"z", "HALL", "LAB", "VAULT"}
    assert constants_in(move_rule.body) == set()


def test_the_action_is_separated_from_the_preconditions(move_rule):
    """The gap that blocked planning: MOVE and OPEN were both body literals with
    nothing saying which one the agent performs."""
    assert move_rule.action is not None
    assert move_rule.action.predicate == "MOVE"
    assert {f.predicate for f in move_rule.preconditions} == {"AT", "OPEN", "PATH"}
    assert move_rule.action not in move_rule.preconditions


def test_grounding_truncation_is_reported_not_silent(move_rule):
    """A planner quietly missing operators would report UNREACHABLE for a goal
    it was never given the means to reach.

    The bound is 2 rather than 5 because grounding now enumerates each variable
    over the terms that can stand where it stands rather than over every
    constant, so this rule yields 4 operators instead of 27. What is under test
    is that hitting the bound is reported, not how many operators the rule has.
    """
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL, limit=2)
    assert report.truncated is True
    assert report.complete is False
    assert len(report.operators) <= 2


def test_a_complete_grounding_says_so(move_rule):
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL)
    assert report.complete is True


def test_operators_carry_the_rule_that_produced_them(move_rule):
    report = ground_for_problem([stored(move_rule, rule_id="rule_abc")], WORLD, GOAL)
    assert all(o.rule_id == "rule_abc" for o in report.operators)
    assert all(o.bindings for o in report.operators)


def test_a_problem_with_no_constants_grounds_nothing(move_rule):
    assert ground_for_problem([stored(move_rule)], [], []).operators == []


# ------------------------------------------------------ composition end to end

def test_a_learned_rule_composes_into_a_multi_step_plan(move_rule):
    """The frontier claim: acquire a single-step transition from demonstrations,
    then compose it toward a goal across a map never demonstrated."""
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in GOAL],
        {"conditions": [f.to_formula() for f in WORLD]},
        report.to_actions(),
    )

    assert result.status is PlanningStatus.PLAN_FOUND
    assert [s["action"] for s in result.steps] == [
        "MOVE(z, HALL, LAB)", "MOVE(z, LAB, VAULT)"]


def test_the_plan_traces_back_to_the_learned_rule(move_rule):
    report = ground_for_problem([stored(move_rule, rule_id="rule_xyz")], WORLD, GOAL)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in GOAL],
        {"conditions": [f.to_formula() for f in WORLD]},
        report.to_actions(),
    )
    assert {a["rule_id"] for a in result.actions} == {"rule_xyz"}


def test_composition_fails_honestly_when_the_goal_is_unreachable(move_rule):
    """A sealed vault must produce a proof, not a plan."""
    sealed = [f for f in WORLD if f != F("OPEN(VAULT)")]
    report = ground_for_problem([stored(move_rule)], sealed, GOAL)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in GOAL],
        {"conditions": [f.to_formula() for f in sealed]},
        report.to_actions(),
    )
    assert result.status is PlanningStatus.UNREACHABLE
    assert result.steps == []


def test_an_incomplete_corpus_yields_an_overgeneral_operator():
    """Recorded because composition found it and single-rule evaluation could
    not: without a counter-demonstration of acting from elsewhere, AT is
    minimized away and the agent can move from a room it is not in."""
    without_counter = [
        move_example("a", "R1", "R2", "t1"), move_example("b", "R3", "R4", "t2"),
        move_example("c", "R5", "R6", "n1", opened=False),
        move_example("d", "R7", "R8", "n2", path=False),
        move_example("e", "R9", "R10", "n3", acted=False),
    ]
    rule = get_rule_inducer().induce(without_counter).rule
    assert "AT" not in {f.predicate for f in rule.preconditions}, (
        "this documents the gap; if induction changes, revisit the corpus"
    )
