#!/usr/bin/env python3
"""Semantic identity of a learned rule.

WHY THIS EXISTS. `record_induction` minted `rule_{uuid4()}` on every call, so
inducing the same hypothesis from the same demonstrations twice produced two
rules. Measured on the live store: three `reasoning_pattern` rows for what is
one generalization. At the scale education is about to run at, repeated lessons
would not strengthen a hypothesis -- they would manufacture thousands of copies
of it, and every support count, validation history and competence estimate
computed over them would be counting duplicates.

IDENTITY IS MEANING, NOT HISTORY. The fingerprint hashes what the rule SAYS:

    domain_id, rule_kind, schema version,
    canonical action, preconditions, add effects, delete effects

and nothing about where it came from -- not rule_id, status, timestamps,
evidence, confidence, supersession or usage. Two inductions that reach the same
hypothesis from different evidence must land on one rule and accumulate support
on it; a genuinely revised hypothesis (AT(X,A) added as a precondition) has
different meaning, so a different fingerprint and a rightful new identity.

RULE IDS ARE NOT REPLACED. The frozen EDU-01/EDU-02 manifests reference
`rule_dccaff4cba0f` and `rule_edbe5a8b4ad8`; rewriting those would trade
historical reproducibility for cosmetic consistency. The fingerprint is a
durable column beside the id, and legacy ids keep resolving.

ALPHA-RENAMING. `MOVE(?X0,?X2,?X1)` and `MOVE(?A,?C,?B)` are the same rule, so
variable NAMES cannot enter the hash -- otherwise UUID duplication is simply
replaced by variable-name duplication. Canonical form is the lexicographically
smallest serialization over every renaming of the rule's variables, which is
canonical by construction rather than by a tie-breaking heuristic that has to
be argued about.
"""

from __future__ import annotations

import hashlib
import json
from itertools import permutations
from typing import Any, Dict, Optional, Tuple

from .rule_induction import VARIABLE_PREFIX, CandidateRule, Fact, is_variable

#: Bumped only when the canonical FORM changes, which changes every fingerprint.
#: Recorded in the hash so rules fingerprinted under different rules of
#: canonicalisation can never collide silently.
FINGERPRINT_VERSION = 1

#: n! renamings are enumerated. Real induced rules carry a handful of variables;
#: beyond this the enumeration is refused rather than silently truncated to a
#: non-canonical form, because a fingerprint that is only usually canonical is
#: worse than none.
MAX_VARIABLES = 8


def _variables(rule: CandidateRule) -> Tuple[str, ...]:
    seen = []
    for fact in sorted(rule.body, key=str) + sorted(rule.effects.add, key=str) \
            + sorted(rule.effects.delete, key=str):
        for arg in fact.args:
            if is_variable(arg) and arg not in seen:
                seen.append(arg)
    for output in rule.outputs:
        for arg in (output.variable, *output.inputs):
            if is_variable(arg) and arg not in seen:
                seen.append(arg)
    return tuple(seen)


def _render(rule: CandidateRule, mapping: Dict[str, str]) -> Dict[str, Any]:
    """One serialization of the rule under a given variable renaming.

    Sorted, so `AT ∧ OPEN ∧ PATH` and `PATH ∧ AT ∧ OPEN` are one hypothesis:
    conjunction is commutative and an identity that depended on literal order
    would split a rule from itself.
    """
    def facts(collection):
        return sorted(str(f.substitute(mapping)) for f in collection)

    action = rule.action.substitute(mapping) if rule.action else None
    rendered: Dict[str, Any] = {
        "action": str(action) if action else None,
        # preconditions, not body: the action is already named above, and
        # listing it twice would let its presence in the body change identity.
        "preconditions": facts(rule.preconditions),
        "add": facts(rule.effects.add),
        "delete": facts(rule.effects.delete),
    }
    # WHAT THE ACTION PRODUCES IS PART OF WHAT THE RULE MEANS. Two rules that
    # agree on every literal and disagree on which function makes the value are
    # two different predictions, and one fingerprint for both would let
    # `record_induction` keep whichever was stored first and discard the other
    # in silence.
    #
    # The key is omitted entirely when there are no outputs, so every rule
    # learned before outputs existed keeps the fingerprint it was stored under.
    if rule.outputs:
        rendered["outputs"] = sorted(
            str(output.substitute(mapping)) for output in rule.outputs)
    return rendered


def canonical_form(
    rule: CandidateRule,
    *,
    domain_id: Optional[str] = None,
    rule_kind: str = "state_transition",
) -> Dict[str, Any]:
    """The rule's meaning, in a form independent of how it was written."""
    variables = _variables(rule)
    if len(variables) > MAX_VARIABLES:
        raise ValueError(
            f"rule carries {len(variables)} variables; canonicalisation "
            f"enumerates renamings and refuses beyond {MAX_VARIABLES} rather "
            f"than emitting a form that is not canonical")

    slots = [f"{VARIABLE_PREFIX}V{i}" for i in range(len(variables))]
    best = None
    for order in permutations(range(len(variables))):
        mapping = {variables[source]: slots[target]
                   for target, source in enumerate(order)}
        rendered = _render(rule, mapping)
        key = json.dumps(rendered, sort_keys=True)
        if best is None or key < best[0]:
            best = (key, rendered)

    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "domain_id": domain_id or None,
        "rule_kind": rule_kind,
        "rule": best[1] if best else _render(rule, {}),
    }


def semantic_fingerprint(
    rule: CandidateRule,
    *,
    domain_id: Optional[str] = None,
    rule_kind: str = "state_transition",
) -> str:
    """SHA-256 over the canonical form. The full digest, not a prefix."""
    form = canonical_form(rule, domain_id=domain_id, rule_kind=rule_kind)
    return hashlib.sha256(
        json.dumps(form, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["canonical_form", "semantic_fingerprint",
           "FINGERPRINT_VERSION", "MAX_VARIABLES"]
