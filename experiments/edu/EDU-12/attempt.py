#!/usr/bin/env python3
"""EDU-12's one attempt path: production ingress, no sidecar.

The first version of this file WAS a sidecar. It imported
`ProbabilisticVersionSpace` and drove it directly, returning UNKNOWN for
everything else -- so it measured what the harness had been wired to rather
than what Torin can do when asked. Every number it produced is preserved in
`S0_INVALID_01.json` and none of them are evidence about the substrate.

Each item now goes to the real owner of its question:

    reasoning        AutonomousCoordinator.reason_about
                     -> NeuralSymbolicBridge (AUTO: substrate before model)
                     -> arithmetic reading / Z3, or deterministic
                        formalization / unification / proof engine

    induction        SubstrateLearning.induce_causal_structure
                     -> ProbabilisticVersionSpace

Both are the production entry points. Neither is reached by importing an
internal component.

STILL SUBJECT-AGNOSTIC. Dispatch is on `kind`, which describes the shape of the
ANSWER -- a value, a choice, a program, a causal structure -- never on which
subject the item came from. Subjects share kinds. `assert_subject_agnostic`
parses this file and fails if a subject is named.

NO FALLBACK. When the substrate produces nothing, the answer is UNKNOWN. It is
never replaced by a guess, a model consultation the condition did not
authorise, or a plausible default -- an answer that happens to be right is
indistinguishable in the score from knowledge, which makes the whole pre/post
comparison unreadable.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

UNKNOWN = "__unknown__"
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Attempt:
    """One answer, with who produced it."""

    answer: Any
    derived: bool
    basis: str
    route: List[str] = field(default_factory=list)
    model_calls: int = 0
    verified: bool = False

    @property
    def is_unknown(self) -> bool:
        return not self.derived


def _unknown(reason: str, route: Optional[List[str]] = None) -> Attempt:
    return Attempt(UNKNOWN, False, reason, route or [])


def _from_result(result) -> Dict[str, Any]:
    metadata = dict(getattr(result, "metadata", {}) or {})
    return {
        "answer": getattr(result, "answer", "") or "",
        "verified": bool(metadata.get("verified")),
        "reason": metadata.get("reason"),
        "route": list(metadata.get("route") or []),
        "model_calls": int(metadata.get("model_calls") or 0),
    }


def _premises_of(item: Dict[str, Any]) -> List[str]:
    """Whatever the item states as given, in the substrate's input form."""
    stated: List[str] = []
    for key in ("facts", "premises", "context"):
        stated += [str(f) for f in (item.get(key) or [])]
    if item.get("passage"):
        stated += [s.strip() for s in str(item["passage"]).split(".") if s.strip()]
    return stated


# ---- reasoning kinds, through the coordinator ---------------------------

async def _ask(coordinator, question: str, item: Dict[str, Any]) -> Dict[str, Any]:
    result = await coordinator.reason_about(
        question, context={"premises": _premises_of(item)})
    return _from_result(result)


async def _attempt_value(coordinator, item) -> Attempt:
    """A numeric or short answer. The prompt is the question."""
    asked = await _ask(coordinator, str(item.get("prompt", "")), item)
    if not asked["verified"] or not asked["answer"]:
        return _unknown(f"substrate did not settle it ({asked['reason']})", asked["route"])
    numbers = _NUMBER.findall(str(asked["answer"]))
    if not numbers:
        return Attempt(str(asked["answer"]).strip(), True, asked["reason"],
                       asked["route"], asked["model_calls"], asked["verified"])
    value = float(numbers[-1])
    return Attempt(int(value) if value.is_integer() else value, True,
                   asked["reason"], asked["route"], asked["model_calls"], True)


async def _attempt_choice(coordinator, item) -> Attempt:
    """A choice, answered by asking the substrate the item's own question.

    An earlier version posed `f"Is {item.get('subject','it')} {option}?"` for
    each option -- but these items carry no `subject`, so it asked "Is it yes?".
    That is a fabricated question, and an answer to it would have meant nothing.

    The generic mapping instead reads the substrate's own verdict:

        proved                  -> the affirmative option, when one is offered
        not entailed by the
        premises                -> "undetermined", when that is an option --
                                   because "the given facts do not establish
                                   this" IS undetermined, and saying so is a
                                   positive finding rather than ignorance
        anything else           -> UNKNOWN

    Options this cannot express (left/right, first/second) come back UNKNOWN.
    That is a real limit of the substrate on this item shape, and it is scored
    as one rather than guessed at.
    """
    options = [str(o) for o in (item.get("options") or [])]
    if not options:
        return _unknown("choice item declares no options")

    asked = await _ask(coordinator, str(item.get("prompt", "")), item)
    route, calls = asked["route"], asked["model_calls"]

    affirmative = next((o for o in options if o.lower() in ("yes", "true")), None)
    if asked["verified"] and affirmative:
        return Attempt(affirmative, True, asked["reason"], route, calls, True)

    undetermined = next((o for o in options if o.lower() == "undetermined"), None)
    if undetermined and asked["reason"] in ("substrate_refuted", "substrate_undecided"):
        # A POSITIVE FINDING: the premises provably do not settle it.
        return Attempt(undetermined, True, asked["reason"], route, calls, True)

    return _unknown(f"no option expressible from verdict ({asked['reason']})", route)


async def _attempt_program(coordinator, item) -> Attempt:
    """Route a programming item to the capability that owns code, and grade it
    by RUNNING what comes back.

    THIS USED TO RETURN UNKNOWN WITHOUT ASKING. It carried the comment "writing
    a program is not something the substrate does without a model" -- an
    absence claim baked into the harness and never checked. The whole
    programming column was therefore my harness declining to try, not a
    measurement of Torin, which is exactly what made the first baseline
    inadmissible.

    Now the tool registry is asked and whatever it reports is the result. When
    a model is required and the running condition has detached it, the owner
    says so and that is recorded as a typed cause with a real route -- which is
    a finding. "The capability needs a teacher" and "the harness never asked"
    are different facts and must not share a score.
    """
    from core.tools.tool_registry import get_tool_registry

    route = ["tool_registry"]
    entry = item.get("entry") or "solution"
    tool, parameters = _program_request(item, entry)
    route.append(tool)

    try:
        result = await get_tool_registry().execute_tool(tool, parameters)
    except Exception as e:
        return _unknown(f"{type(e).__name__} from {tool}: {str(e)[:70]}", route)

    if not getattr(result, "success", False):
        return _unknown(f"{tool} declined: {str(getattr(result, 'error', ''))[:70]}",
                        route)

    source = _extract_source(getattr(result, "output", None))
    if not source:
        return _unknown(f"{tool} returned no source", route)

    passed, detail = _run_against_tests(source, entry, item)
    if not passed:
        # A program that does not pass its own tests is WRONG, not unknown --
        # the substrate committed to something and the world disagreed.
        return Attempt(detail, True, f"produced by {tool}; failed its tests", route, 0, False)
    return Attempt(True, True, f"produced by {tool}; passed its tests", route, 0, True)


def _program_request(item, entry):
    """Which code capability this item calls for, and with what arguments.

    Repair routes to the same capability as writing, because repairing a
    semantically broken function means producing a corrected one. An earlier
    version sent it to `optimize_code`, which takes `code` and an optimisation
    level and is an OPTIMISER -- optimising `sum(values) / 0` does not make it
    compute an average, and the item failed on a parameter error rather than on
    anything about Torin.

    There is no model-free repair capability in this substrate: the tools that
    need no model (`refactor_code`, `format_code`, `apply_patch`,
    `compile_typecheck_gate`) all transform code whose intent is already given.
    Recovering intent from a wrong implementation is what needs the teacher.
    """
    description = str(item.get("prompt", ""))
    if item.get("kind") == "repair" and item.get("broken"):
        description = f"{description}. The broken implementation is:\n{item['broken']}"
    return "generate_function", {"description": description, "function_name": entry}


def _extract_source(output) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("code", "source", "function", "result", "optimized_code"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _run_against_tests(source: str, entry: str, item) -> tuple:
    """Grade by EXECUTION. Resemblance to a reference solution is not evidence.

    Runs in this process against the item's declared cases; a program that
    raises is a failure with the exception recorded, not an absence.
    """
    namespace: Dict[str, Any] = {}
    try:
        exec(compile(source, f"<{entry}>", "exec"), namespace)
    except Exception as e:
        return False, f"source did not compile: {type(e).__name__}"

    function = namespace.get(entry)
    if not callable(function):
        return False, f"no callable named {entry!r} was defined"

    for case in item.get("tests") or []:
        try:
            produced = function(*case.get("args", []))
        except Exception as e:
            return False, f"raised {type(e).__name__} on {case.get('args')}"
        if produced != case.get("expected"):
            return False, f"{case.get('args')} -> {produced!r}, expected {case.get('expected')!r}"
    return True, "all cases passed"


# ---- induction kinds, through the learning authority --------------------

def _attempt_causal_structure(authority, item) -> Attempt:
    space = authority.induce_causal_structure(item.get("observations") or [])
    if space is None:
        return _unknown("no usable trials supplied", ["learning_authority"])
    best, mass = space.most_probable()
    return Attempt({"requires": sorted(best.requires), "forbids": sorted(best.forbids)},
                   True, f"version space MAP, posterior {mass:.3f}",
                   ["learning_authority", "probabilistic_version_space"], 0, True)


def _attempt_intervention(authority, item) -> Attempt:
    space = authority.induce_causal_structure(item.get("observations") or [])
    if space is None:
        return _unknown("no usable trials supplied", ["learning_authority"])
    probability = space.probability_of_success(frozenset(item.get("query") or []))
    return Attempt(probability >= 0.5, True, f"predicted P(success)={probability:.3f}",
                   ["learning_authority", "probabilistic_version_space"], 0, True)


async def attempt(item: Dict[str, Any], coordinator, authority) -> Attempt:
    """Answer one exam item through the owner of its kind of question."""
    kind = item.get("kind")
    if kind == "causal_structure":
        return _attempt_causal_structure(authority, item)
    if kind == "intervention":
        return _attempt_intervention(authority, item)
    if kind == "choice":
        return await _attempt_choice(coordinator, item)
    if kind == "value":
        return await _attempt_value(coordinator, item)
    if kind in ("program", "repair"):
        return await _attempt_program(coordinator, item)
    return _unknown(f"no owner for item kind {kind!r}")


# ---- the invariant this module must satisfy -----------------------------

def assert_subject_agnostic(subject_names: Sequence[str]) -> List[str]:
    """This file may not name a subject, and may not branch on one."""
    tree = ast.parse(Path(__file__).read_text())
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            for name in subject_names:
                if name.lower() in node.id.lower():
                    violations.append(f"references subject {name} at line {node.lineno}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for name in subject_names:
                if re.fullmatch(rf"\s*{re.escape(name)}\s*", node.value, re.IGNORECASE):
                    violations.append(f"contains subject literal {name!r}")
    return violations


__all__ = ["attempt", "Attempt", "UNKNOWN", "assert_subject_agnostic"]
