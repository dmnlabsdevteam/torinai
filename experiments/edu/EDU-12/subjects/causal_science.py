"""Block 3 — Causal science. Hypothesis, experiment, uncertainty.

The block the substrate should be STRONGEST at, because EDU-09 to EDU-11 built
exactly these mechanisms. Included deliberately: a competence profile is only
readable if it contains a subject where a high score is expected. A flat
profile across four subjects would tell us nothing about which mechanisms
carried which result.

Note the confound items. Distinguishing correlation from causation cannot be
done from observation alone -- it needs the intervention -- so an answer of
UNDETERMINED is correct there, and confident causal attribution is the error.
"""

SUBJECT = "causal_science"
DESCRIPTION = "Inferring causal structure from observation and intervention."
COGNITIVE_DEMAND = ("hypothesis_formation", "experimentation", "uncertainty")
TOOLS = ("observe", "intervene")
ENVIRONMENT = "causal_sandbox"

LESSONS = [
    {"id": "s_l1", "concept": "necessary_condition",
     "content": "A condition is necessary when the outcome never occurs without it. Look for the condition present in every success.",
     "example": {"observations": [{"conditions": ["a", "b"], "outcome": True}, {"conditions": ["b"], "outcome": False}], "necessary": ["a"]}},
    {"id": "s_l2", "concept": "forbidding_condition",
     "content": "A condition can block an outcome by being present. Look for the condition absent from every success and present in failures that otherwise look complete.",
     "example": {"observations": [{"conditions": ["a"], "outcome": True}, {"conditions": ["a", "x"], "outcome": False}], "forbids": ["x"]}},
    {"id": "s_l3", "concept": "irrelevant_condition",
     "content": "A condition that varies freely across both successes and failures explains nothing and must not enter the rule.",
     "example": {"observations": [{"conditions": ["a", "q"], "outcome": True}, {"conditions": ["a"], "outcome": True}], "irrelevant": ["q"]}},
    {"id": "s_l4", "concept": "intervention_beats_observation",
     "content": "Two conditions that always appear together cannot be separated by watching. Change one of them on purpose and observe what follows.",
     "example": {"observed": "a and b always co-occur", "action": "set a without b", "learns": "which of a or b was doing the work"}},
    {"id": "s_l5", "concept": "unreliable_action",
     "content": "An action that fails once while its conditions were met is unreliable, not disproven. Repeat it before revising the rule.",
     "example": {"trials": [True, True, True, False, True], "conclusion": "reliable_but_not_certain"}},
]

PRETEST = [
    {"id": "s_pre1", "kind": "causal_structure", "prompt": "Which conditions are required for the outcome",
     "observations": [{"conditions": ["heat", "fuel", "spark"], "outcome": True}, {"conditions": ["fuel", "spark"], "outcome": False}, {"conditions": ["heat", "spark"], "outcome": False}, {"conditions": ["heat", "fuel"], "outcome": False}, {"conditions": ["heat", "fuel", "spark", "blue"], "outcome": True}],
     "answer": {"requires": ["fuel", "heat", "spark"], "forbids": []}},
    {"id": "s_pre2", "kind": "causal_structure", "prompt": "Which condition blocks the outcome",
     "observations": [{"conditions": ["power"], "outcome": True}, {"conditions": ["power", "lock"], "outcome": False}, {"conditions": ["power", "tag"], "outcome": True}, {"conditions": ["tag"], "outcome": False}],
     "answer": {"requires": ["power"], "forbids": ["lock"]}},
    {"id": "s_pre3", "kind": "intervention", "prompt": "Given the observations, will the outcome occur",
     "observations": [{"conditions": ["a", "b"], "outcome": True}, {"conditions": ["a"], "outcome": False}, {"conditions": ["b"], "outcome": False}],
     "query": ["a", "b", "c"], "answer": True},
    {"id": "s_pre4", "kind": "intervention", "prompt": "Given the observations, will the outcome occur",
     "observations": [{"conditions": ["x", "y"], "outcome": True}, {"conditions": ["y"], "outcome": False}],
     "query": ["y"], "answer": False},
    {"id": "s_pre5", "kind": "choice", "prompt": "Two conditions always occur together and the outcome follows. Which is the cause",
     "options": ["first", "second", "undetermined"],
     "observations": [{"conditions": ["m", "n"], "outcome": True}, {"conditions": [], "outcome": False}],
     "answer": "undetermined"},
    {"id": "s_pre6", "kind": "choice", "prompt": "A rule held four times then failed once. Is the rule disproven",
     "options": ["yes", "no"], "trials": [True, True, True, True, False], "answer": "no"},
]

POSTTEST = [
    {"id": "s_post1", "kind": "causal_structure", "prompt": "Which conditions are required for the outcome",
     "observations": [{"conditions": ["seed", "water", "light"], "outcome": True}, {"conditions": ["water", "light"], "outcome": False}, {"conditions": ["seed", "light"], "outcome": False}, {"conditions": ["seed", "water"], "outcome": False}, {"conditions": ["seed", "water", "light", "music"], "outcome": True}],
     "answer": {"requires": ["light", "seed", "water"], "forbids": []}},
    {"id": "s_post2", "kind": "causal_structure", "prompt": "Which condition blocks the outcome",
     "observations": [{"conditions": ["key"], "outcome": True}, {"conditions": ["key", "alarm"], "outcome": False}, {"conditions": ["key", "paint"], "outcome": True}, {"conditions": ["paint"], "outcome": False}],
     "answer": {"requires": ["key"], "forbids": ["alarm"]}},
    {"id": "s_post3", "kind": "intervention", "prompt": "Given the observations, will the outcome occur",
     "observations": [{"conditions": ["p", "q"], "outcome": True}, {"conditions": ["p"], "outcome": False}, {"conditions": ["q"], "outcome": False}],
     "query": ["p", "q", "z"], "answer": True},
    {"id": "s_post4", "kind": "intervention", "prompt": "Given the observations, will the outcome occur",
     "observations": [{"conditions": ["g", "h"], "outcome": True}, {"conditions": ["g", "h", "stop"], "outcome": False}],
     "query": ["g", "h", "stop"], "answer": False},
    {"id": "s_post5", "kind": "choice", "prompt": "Two conditions never appear apart and the outcome follows. Which is the cause",
     "options": ["first", "second", "undetermined"],
     "observations": [{"conditions": ["r", "s"], "outcome": True}, {"conditions": [], "outcome": False}],
     "answer": "undetermined"},
    {"id": "s_post6", "kind": "choice", "prompt": "An action failed once with its conditions met, then worked six times. Is it unreliable or wrongly specified",
     "options": ["unreliable", "wrongly_specified"], "trials": [False, True, True, True, True, True, True], "answer": "unreliable"},
]

TRANSFER = [
    {"id": "s_tr1", "kind": "causal_structure", "composes": ["necessary_condition", "forbidding_condition", "irrelevant_condition"],
     "prompt": "Determine the complete rule including any blocking and any irrelevant conditions",
     "observations": [{"conditions": ["a", "b", "junk"], "outcome": True}, {"conditions": ["a", "b", "halt"], "outcome": False}, {"conditions": ["a"], "outcome": False}, {"conditions": ["a", "b"], "outcome": True}, {"conditions": ["b", "junk"], "outcome": False}],
     "answer": {"requires": ["a", "b"], "forbids": ["halt"]}},
    {"id": "s_tr2", "kind": "choice", "composes": ["intervention_beats_observation", "unreliable_action"],
     "prompt": "Conditions c and d always co-occur and the outcome follows nine times in ten. What action resolves which condition matters",
     "options": ["observe_more", "set_c_without_d", "conclude_c", "conclude_undetermined"],
     "answer": "set_c_without_d"},
    {"id": "s_tr3", "kind": "intervention", "composes": ["necessary_condition", "unreliable_action"],
     "prompt": "The rule requires both conditions and holds about nine times in ten. Will the outcome occur when both are met",
     "observations": [{"conditions": ["e", "f"], "outcome": True}, {"conditions": ["e", "f"], "outcome": False}, {"conditions": ["e", "f"], "outcome": True}, {"conditions": ["e"], "outcome": False}],
     "query": ["e", "f"], "answer": True},
    {"id": "s_tr4", "kind": "choice", "composes": ["irrelevant_condition", "intervention_beats_observation"],
     "prompt": "A condition appears in every success but also in every failure. What is it",
     "options": ["required", "forbidden", "irrelevant"], "answer": "irrelevant"},
]
