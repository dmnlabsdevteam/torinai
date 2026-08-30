#!/usr/bin/env python3
"""Learning a causal structure when reality is unreliable.

A deterministic version space eliminates any hypothesis an observation
contradicts. That is correct only when a contradiction is impossible under a
true hypothesis -- and in a stochastic world it is merely unlikely. One failure
of a correct rule would delete the correct rule.

So belief is a DISTRIBUTION, and the two things that could explain a
disappointing outcome are represented separately:

    STRUCTURE     which conditions the action requires, and which it forbids
    RELIABILITY   how often it works when the structure IS satisfied

A failure under satisfied preconditions is evidence about RELIABILITY. It is
evidence about STRUCTURE only in so far as some other structure explains the
observation better. That separation is the credit invariant applied to a
probabilistic world: never debit a hypothesis for variance it predicts.

EVERY HYPOTHESIS CARRIES ITS OWN RATES. This is the part that has to be right.
An earlier version kept ONE global reliability and ONE global leak, and split
each observation between them in proportion to the posterior's belief that the
structure held. That is not a posterior, it is a fractional-credit
approximation, and it fails in a specific measurable way: while belief is still
diffuse, half of every violated-structure failure is charged to reliability.
Most discriminating experiments DO violate the true structure -- that is what
makes them discriminating -- so reliability collapses, and once reliability is
indistinguishable from leak no situation separates any hypothesis from any
other, expected information gain goes to zero, and learning stops. Measured:
reliability 0.05 against a true 0.90, with 0% convergence.

Giving each structure its own rates removes the approximation entirely. A
hypothesis is then a complete generative model -- a structure plus the two
rates it needs -- and the posterior over structures is the exact
Beta-Bernoulli marginal likelihood, accumulated by the chain rule. The true
structure wins because it is the one that can explain the failures as
non-firing (leak stays near zero) and the successes as firing (reliability
stays near one). A structure that is missing a precondition has to explain both
with a single muddled rate, and pays for it on every observation.

UNKNOWN CHANGES NOTHING. An observation the observer could not resolve has the
same likelihood under every hypothesis, so it cancels exactly -- and it must
not touch the rate counts either. Reading UNKNOWN as failure is the single most
tempting corruption available here, because the other two values are both
usable.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Tuple

#: WEAKLY ASYMMETRIC, AND IT HAS TO BE.
#:
#: With Beta(1,1) on both rates, satisfying a structure and violating it both
#: predict success at 0.50 -- so no experiment distinguishes any hypothesis
#: from any other, expected information gain is exactly zero everywhere, and
#: the learner correctly refuses to take a single observation. Measured: 0%
#: convergence in all three conditions with reliability pinned at 0.500.
#:
#: What these priors encode is the DEFINITION of a precondition -- satisfying
#: one makes the action more likely to work than violating it -- and nothing
#: about WHICH conditions those are. Three pseudo-counts each, so two real
#: observations outweigh them. A prior over the structure itself would be
#: deciding the experiment; this is what makes it a learning problem at all.
RELIABILITY_PRIOR = (2.0, 1.0)     # mean 0.667 -- satisfied structures tend to work
LEAK_PRIOR = (1.0, 2.0)            # mean 0.333 -- violated ones tend not to


@dataclass
class StructuralHypothesis:
    """One candidate causal structure. Carries polarity, not just requirements.

    `forbids` exists because a condition can gate an action by its ABSENCE --
    a door that must not be locked, an account that must not be suspended. A
    language that can only accumulate requirements cannot express that, and no
    amount of evidence would let the learner discover it.
    """
    requires: FrozenSet[str]
    forbids: FrozenSet[str]

    def fires(self, conditions) -> bool:
        return self.requires <= conditions and not (self.forbids & conditions)

    def key(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        return tuple(sorted(self.requires)), tuple(sorted(self.forbids))


@dataclass
class ProbabilisticVersionSpace:
    """A posterior over structures, each with its own execution rates."""

    hypotheses: List[StructuralHypothesis]
    log_posterior: List[float] = field(default_factory=list)

    #: Per hypothesis: successes/failures observed in situations where THAT
    #: hypothesis fires, and separately where it does not. Four counts each.
    fire_alpha: List[float] = field(default_factory=list)
    fire_beta: List[float] = field(default_factory=list)
    leak_alpha: List[float] = field(default_factory=list)
    leak_beta: List[float] = field(default_factory=list)

    observations: int = 0
    unknown_observations: int = 0

    def __post_init__(self):
        count = len(self.hypotheses)
        if not self.log_posterior:
            self.log_posterior = [-math.log(count)] * count
        if not self.fire_alpha:
            self.fire_alpha = [RELIABILITY_PRIOR[0]] * count
            self.fire_beta = [RELIABILITY_PRIOR[1]] * count
            self.leak_alpha = [LEAK_PRIOR[0]] * count
            self.leak_beta = [LEAK_PRIOR[1]] * count

    # ---- rates -----------------------------------------------------------

    def rate_for(self, index: int, fires: bool) -> float:
        """Posterior-predictive success probability for one hypothesis."""
        if fires:
            return self.fire_alpha[index] / (self.fire_alpha[index] + self.fire_beta[index])
        return self.leak_alpha[index] / (self.leak_alpha[index] + self.leak_beta[index])

    @property
    def reliability(self) -> float:
        """P(success | structure satisfied), marginalised over structures.

        Posterior-weighted, so it means what it says only once the posterior
        has an opinion -- which is correct. An estimate of "how often it works
        when the rule holds" is not defined independently of which rule holds.
        """
        return sum(p * self.rate_for(i, True)
                   for i, p in enumerate(self.posterior()))

    @property
    def leak(self) -> float:
        """P(success | structure violated), marginalised over structures."""
        return sum(p * self.rate_for(i, False)
                   for i, p in enumerate(self.posterior()))

    def rates_of_most_probable(self) -> Tuple[float, float]:
        """The winning structure's own two rates, unmixed."""
        posterior = self.posterior()
        best = max(range(len(posterior)), key=posterior.__getitem__)
        return self.rate_for(best, True), self.rate_for(best, False)

    # ---- posterior -------------------------------------------------------

    def posterior(self) -> List[float]:
        largest = max(self.log_posterior)
        weights = [math.exp(lp - largest) for lp in self.log_posterior]
        total = sum(weights)
        return [w / total for w in weights]

    def entropy(self) -> float:
        return -sum(p * math.log(p) for p in self.posterior() if p > 0.0)

    def mass_on(self, requires, forbids) -> float:
        target = (tuple(sorted(requires)), tuple(sorted(forbids)))
        return sum(p for h, p in zip(self.hypotheses, self.posterior())
                   if h.key() == target)

    def most_probable(self) -> Tuple[StructuralHypothesis, float]:
        posterior = self.posterior()
        best = max(range(len(posterior)), key=posterior.__getitem__)
        return self.hypotheses[best], posterior[best]

    # ---- prediction ------------------------------------------------------

    def probability_of_success(self, conditions) -> float:
        """Marginal P(success), over the whole posterior. Used for calibration."""
        conditions = frozenset(conditions)
        return sum(p * self.rate_for(i, self.hypotheses[i].fires(conditions))
                   for i, p in enumerate(self.posterior()))

    # ---- update ----------------------------------------------------------

    def observe(self, conditions, outcome: str) -> Dict[str, Any]:
        """Fold one observation in. `outcome` is 'success', 'failure' or 'unknown'."""
        conditions = frozenset(conditions)
        self.observations += 1

        if outcome == "unknown":
            # EXACTLY NOTHING. Equal likelihood under every hypothesis, so the
            # posterior is unchanged, and the rate counts must not move either
            # -- an attempt whose result was never established is not a trial
            # of anything.
            self.unknown_observations += 1
            return {"outcome": outcome, "posterior_changed": False,
                    "entropy": self.entropy()}

        succeeded = outcome == "success"
        before = self.entropy()
        fired = [h.fires(conditions) for h in self.hypotheses]

        # Score BEFORE updating counts: the likelihood of this observation
        # under each hypothesis is its predictive rate given everything seen
        # so far. Chain rule -- the product over observations is the exact
        # marginal likelihood with the rates integrated out.
        for i, fires in enumerate(fired):
            rate = self.rate_for(i, fires)
            likelihood = rate if succeeded else (1.0 - rate)
            self.log_posterior[i] += math.log(max(likelihood, 1e-12))

        # Then each hypothesis books the trial against ITS OWN account. No
        # fractional credit: a hypothesis that says this situation satisfies
        # the structure records a reliability trial, one that says it does not
        # records a leak trial, and the posterior decides between them by how
        # well those stories hold up -- not by splitting the evidence.
        for i, fires in enumerate(fired):
            if fires and succeeded:
                self.fire_alpha[i] += 1.0
            elif fires:
                self.fire_beta[i] += 1.0
            elif succeeded:
                self.leak_alpha[i] += 1.0
            else:
                self.leak_beta[i] += 1.0

        return {"outcome": outcome, "posterior_changed": True,
                "entropy": self.entropy(), "entropy_reduced": before - self.entropy(),
                "structure_satisfied_belief": round(
                    sum(p for p, f in zip(self.posterior(), fired) if f), 4)}

    # ---- experiment selection -------------------------------------------

    def expected_information_gain(self, conditions) -> float:
        """Expected entropy reduction from running this situation.

        Naturally values REPLICATION: repeating a situation whose outcome is
        still uncertain carries information, because the rates that would
        explain it have not yet resolved. A deterministic version space could
        never want a repeat -- the second run tells it nothing it did not
        already record.
        """
        conditions = frozenset(conditions)
        posterior = self.posterior()
        rates = [self.rate_for(i, h.fires(conditions))
                 for i, h in enumerate(self.hypotheses)]

        p_success = sum(p * r for p, r in zip(posterior, rates))
        if p_success <= 0.0 or p_success >= 1.0:
            return 0.0

        def entropy_after(succeeded: bool, marginal: float) -> float:
            total = 0.0
            for p, rate in zip(posterior, rates):
                weight = p * (rate if succeeded else (1.0 - rate)) / marginal
                if weight > 0.0:
                    total -= weight * math.log(weight)
            return total

        expected = (p_success * entropy_after(True, p_success)
                    + (1.0 - p_success) * entropy_after(False, 1.0 - p_success))
        return self.entropy() - expected

    # ---- durability ------------------------------------------------------

    def to_json(self) -> str:
        """Belief must survive a restart, or it was never really held."""
        return json.dumps({
            "hypotheses": [[sorted(h.requires), sorted(h.forbids)] for h in self.hypotheses],
            "log_posterior": self.log_posterior,
            "fire": [self.fire_alpha, self.fire_beta],
            "leak": [self.leak_alpha, self.leak_beta],
            "observations": self.observations,
            "unknown_observations": self.unknown_observations,
        })

    @classmethod
    def from_json(cls, payload: str) -> "ProbabilisticVersionSpace":
        data = json.loads(payload)
        space = cls(
            hypotheses=[StructuralHypothesis(frozenset(r), frozenset(f))
                        for r, f in data["hypotheses"]],
            log_posterior=list(data["log_posterior"]),
            fire_alpha=list(data["fire"][0]), fire_beta=list(data["fire"][1]),
            leak_alpha=list(data["leak"][0]), leak_beta=list(data["leak"][1]),
        )
        space.observations = data["observations"]
        space.unknown_observations = data["unknown_observations"]
        return space


__all__ = ["StructuralHypothesis", "ProbabilisticVersionSpace",
           "RELIABILITY_PRIOR", "LEAK_PRIOR"]
