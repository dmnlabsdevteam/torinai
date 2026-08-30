#!/usr/bin/env python3
"""Which layer owns each subsystem: the always-on guardian, or the substrate.

THE ONE DECLARATION OF OWNERSHIP. The health system's real defect was that no
process knew which components were its to grade, so the guardian reported the
substrate's cognition as failed the moment the operator stopped the substrate.
Ownership is the boundary: a component belongs to exactly one process --

    'substrate'  runs and is graded WITH the substrate (cognition, the
                 request-validation/safety/governance that gates the substrate's
                 own actions, its tools and surface). Off when the substrate is.

    'system'     always-on, owned by the guardian (active defense, database,
                 storage, network, backup, and the observability apparatus
                 itself). Graded whether or not the substrate is running.

This module has NO heavy dependencies on purpose: both the health monitor and
the dashboard CLI import it, so the classification lives in one place and neither
pays to import the other's world to answer "whose component is this?".
"""

from __future__ import annotations

#: Components that live with the substrate. Everything not listed is a system
#: (guardian) concern. Kept as names, not derived from a component 'type', so a
#: single subsystem can be reclassified without moving it in a taxonomy.
SUBSTRATE_OWNED_COMPONENTS = frozenset({
    # Cognition -- only alive with the substrate
    "memory", "learning", "reasoning", "agents", "llm", "quantum",
    "execution", "intelligence", "domain",
    # Security/policy that gates the substrate's OWN actions
    "security", "safety", "governance",
    # Substrate capabilities and its own surface
    "tools", "api_surface", "simulation", "optimization", "chaos",
})


def component_owner(component: str) -> str:
    """'substrate' if the component lives with the substrate, else 'system'.

    A sub-component is written 'parent.child' (e.g. 'reasoning.proof_engine')
    and inherits its parent's owner, so the whole of a substrate subsystem is
    classified together rather than only its top-level name.
    """
    top = component.split(".", 1)[0]
    return "substrate" if top in SUBSTRATE_OWNED_COMPONENTS else "system"


__all__ = ["SUBSTRATE_OWNED_COMPONENTS", "component_owner"]
