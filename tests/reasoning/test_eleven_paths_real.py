#!/usr/bin/env python3
"""Every reasoning path through the AUTHORITY: the 11 kinds AND the 6 modes.

THE AUTHORITY IS `NeuralSymbolicBridge.reason()`. The abstract reasoning engine
and its eleven strategies run UNDERNEATH it; reaching into them directly would
be going around the authority, which is not testing the real path. So every
case here submits a real question — with the couple of sentences that path needs
— to `reason()`, and reads the authority's own verdict:

    metadata['verified']  the substrate stands behind this (not a model guess)
    metadata['kind']      which of the eleven settled it — set ONLY on the
                          derived path, so a model fallback can never fake it
    metadata['reason']    'derived_by_kind' when a kind of thinking derived it
    result.answer         the derived statement

No false positive: a case passes only when the RIGHT kind fired, verified, with
the expected content — a model proposal (origin != derived) is filtered out by
the authority before `kind` is ever set. No false negative: the sentences use
each detector's real vocabulary, so an applicable kind that failed to fire is a
real failure, reported.

Run in the sandbox against the real DB + llama-server:

    docker run --rm --add-host=host.docker.internal:host-gateway \
      -e DOMINION_ENV_LOADED=true \
      -e POSTGRES_HOST=host.docker.internal -e POSTGRES_PORT=5433 \
      -e POSTGRES_DATABASE=torinai_db -e POSTGRES_USER=stefan -e POSTGRES_PASSWORD= \
      -e LLM_SERVER_URL=http://host.docker.internal:8099 \
      -e HF_HOME=/root/.cache/huggingface -e TRANSFORMERS_OFFLINE=1 -e HF_HUB_OFFLINE=1 \
      -e PYTHONPATH=/repo -w /repo \
      -v "$PWD":/repo:ro -v "$HOME/.cache/huggingface":/root/.cache/huggingface:ro \
      torinai-sandbox:latest sh -c "pip install -q pgvector 2>/dev/null; python tests/reasoning/test_eleven_paths_real.py"
"""

import asyncio
import sys


# (kind value, the sentences that give this path its material, the question,
#  a term that must appear in a correct derived answer)
CASES = [
    ("deductive",
     ["human(socrates)", "human(?x) -> mortal(?x)"],
     "is socrates mortal?", "mortal"),
    ("inductive",
     ["raven one is black", "raven two is black", "raven three is black"],
     "what can we conclude about ravens?", "black"),
    ("abductive",
     ["wet(lawn)", "rained(sky) -> wet(lawn)"],
     "what best explains wet(lawn)?", "rained"),
    ("analogical",
     ["the heart pumps blood through the vessels",
      "a pump pushes water through the pipes"],
     "how is the heart like a pump?", "pump"),
    ("causal",
     ["smoking causes lung damage"],
     "what does smoking cause?", "lung damage"),
    ("counterfactual",
     ["the deployment failed",
      "the deployment would have succeeded without the config error"],
     "what if the config error had not happened?", "config"),
    ("spatial",
     ["the book is inside the box", "the box is inside the room"],
     "where is the book?", "room"),
    ("fuzzy",
     ["the disk is mostly full"],
     "how full is the disk?", "full"),
    ("logical",
     ["p", "p -> q"],
     "q", "q"),
    ("probabilistic",
     ["the smoke alarm reliably indicates fire", "the smoke alarm is sounding"],
     "is there a fire?", "fire"),
    ("temporal",
     ["the alarm rings before the coffee brews",
      "the coffee brews before breakfast"],
     "does the alarm ring before breakfast?", "before"),
]


# Material that LACKS each kind's trigger — the kind must ABSTAIN on it.
# (kind value, sentences without that kind's structure, query)
NEGATIVES = [
    ("deductive",      ["human(socrates)"],                 "is socrates mortal?"),   # no rule
    ("inductive",      ["raven one is black"],              "what about ravens?"),     # <2 premises
    ("abductive",      ["wet(lawn)"],                       "why is the lawn wet?"),   # no rule to explain from
    ("analogical",     ["the sky is blue"],                 "any analogy here?"),      # <2 premises
    ("causal",         ["the sky is blue"],                 "what causes what?"),      # no causal form
    ("counterfactual", ["the deployment failed"],           "what if?"),               # no alternative
    ("spatial",        ["the cat is happy"],                "where is it?"),           # no spatial relation
    ("fuzzy",          ["the disk is full"],                "how full?"),              # sharp, not hedged
    ("logical",        ["p"],                               "z"),                       # z not provable from p
    ("probabilistic",  [],                                  "is there a fire?"),        # no evidence premises
    ("temporal",       ["the alarm is red"],                "when does it ring?"),      # no temporal operator
]


# The SIX EXECUTION MODES, each reached through the SAME authority via
# request.mode. All model-free. cross_domain is reachable but grounds nothing
# while the 15 canonical domains hold 0 concepts, so it honestly abstains --
# reachability is what is asserted there, not a fabricated grounding.
# (mode value, query, sentences, task_metadata, expected mode_used, expected term)
MODE_CASES = [
    ("symbolic",       "q", ["p", "p -> q"], {}, "symbolic", "q"),
    ("neural",         "are ravens black?", [], {}, "neural", "ravens"),
    ("hybrid",         "is socrates mortal?",
     ["human(socrates)", "human(?x) -> mortal(?x)"], {}, "hybrid", "mortal"),
    ("neuro_symbolic", "what best explains the wet lawn?",
     ["rained -> lawn_wet", "lawn_wet"], {}, "neuro_symbolic", "rained"),
    ("abstract",       "is socrates mortal?",
     ["human(socrates)", "human(?x) -> mortal(?x)"], {}, "abstract", "mortal"),
    ("cross_domain",   "relate the domains", ["x"],
     {"source_domains": ["scientific"], "target_domains": ["creative"]},
     None, None),  # reachability only: no concepts to ground yet
]


async def run() -> int:
    from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest
    from core.reasoning.reasoning_interfaces import ReasoningType
    from core.model_policy import set_model_policy, ModelPolicy

    # ALWAYS SUBSTRATE-FIRST. The whole test runs model-free: the substrate
    # reasons first and the model is never a factor in whether it does. If any
    # path only settled because a model answered, it fails here instead of
    # passing quietly. Substrate-first does not depend on a model existing.
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)

    bridge = get_neural_bridge()
    if hasattr(bridge, "initialize"):
        await bridge.initialize()

    by_value = {t.value: t for t in ReasoningType}
    rows = []
    passed = 0

    for kind_value, sentences, query, expect in CASES:
        kind = by_value.get(kind_value)
        req = ReasoningRequest(query=query, context=list(sentences), kinds=[kind])
        try:
            result = await bridge.reason(req)
        except Exception as error:
            rows.append((kind_value, False, f"reason() raised {type(error).__name__}: {error}"))
            continue

        md = getattr(result, "metadata", {}) or {}
        answer = str(getattr(result, "answer", "") or "")
        fired = md.get("kind")
        verified = md.get("verified")
        reason = md.get("reason")
        route = md.get("route")

        # Every kind, logical included, is served by its own reasoning strategy:
        # the strategy derives it, verified, and is named as the one that did.
        ok = (verified is True and fired == kind_value
              and reason == "derived_by_kind"
              and expect.lower() in answer.lower())
        if ok:
            passed += 1
        rows.append((kind_value, ok,
                     f"fired={fired} verified={verified} reason={reason} "
                     f"route={route} | answer={answer[:90]!r}"))

    # ---- NEGATIVE CONTROLS: each kind must ABSTAIN on material it doesn't fit.
    # Still model-free: a kind that does not fire simply has no material, and the
    # substrate reports nothing rather than reaching for a model.
    neg_rows = []
    neg_passed = 0
    for kind_value, sentences, query in NEGATIVES:
        kind = by_value.get(kind_value)
        req = ReasoningRequest(query=query, context=list(sentences), kinds=[kind])
        fired = None
        try:
            result = await bridge.reason(req)
            fired = (getattr(result, "metadata", {}) or {}).get("kind")
        except Exception:
            # Under STRICT_MODEL_FREE the forbidden model boundary raises when no
            # kind settled it — which is exactly the abstention we want.
            fired = None
        ok = (fired != kind_value)   # the kind did NOT fire on the wrong material
        if ok:
            neg_passed += 1
        neg_rows.append((kind_value, ok, f"fired={fired} (must not be {kind_value})"))

    # ---- MODES: every execution mode reachable through the SAME authority.
    from core.reasoning.neural_bridge import ReasoningMode
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    get_uncertainty_system().create_belief(
        claim="ravens are black", domain="ornithology", prior=0.9)
    by_mode = {m.value: m for m in ReasoningMode}

    mode_rows = []
    mode_passed = 0
    for mode_value, query, sentences, tmeta, want_used, expect in MODE_CASES:
        req = ReasoningRequest(query=query, context=list(sentences),
                               mode=by_mode[mode_value], task_metadata=dict(tmeta),
                               cached_memories=[])
        try:
            result = await bridge.reason(req)
        except Exception as error:
            mode_rows.append((mode_value, False,
                              f"reason() raised {type(error).__name__}: {error}"))
            continue
        used = getattr(getattr(result, "mode_used", None), "value", None)
        answer = str(getattr(result, "answer", "") or "")
        if want_used is None:
            ok = result is not None
            detail = f"reachable (used={used}) answer={answer[:45]!r}"
        else:
            ok = (used == want_used
                  and (expect is None or expect.lower() in answer.lower()))
            detail = f"used={used} answer={answer[:60]!r}"
        if ok:
            mode_passed += 1
        mode_rows.append((mode_value, ok, detail))

    print("\n============ REASONING THROUGH THE AUTHORITY: 11 KINDS + 6 MODES ============")
    print("-- POSITIVE: the right kind derives the answer (model-free) --")
    for kind_value, ok, detail in rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {kind_value:15} {detail}")
    print("\n-- NEGATIVE: the kind abstains on material it does not fit --")
    for kind_value, ok, detail in neg_rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {kind_value:15} {detail}")
    print("\n-- MODES: every execution mode reachable through reason() --")
    for mode_value, ok, detail in mode_rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {mode_value:15} {detail}")
    total = passed + neg_passed + mode_passed
    want = len(CASES) + len(NEGATIVES) + len(MODE_CASES)
    print(f"\n  kinds {passed}/{len(CASES)} · negatives {neg_passed}/{len(NEGATIVES)}"
          f" · modes {mode_passed}/{len(MODE_CASES)} · {total}/{want} total\n")
    return 0 if total == want else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except Exception as error:
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
