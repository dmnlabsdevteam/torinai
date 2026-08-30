#!/usr/bin/env python3
"""Which modules the system depends on for its own safety.

ONE LIST, TWO ENFORCERS. This was a 14-entry literal written out twice --
`runtime_governance.RuntimeGovernance.CRITICAL_MODULES` and
`mutation_detector.MutationDetector.CRITICAL_MODULES`. They agree today, which
is exactly why the duplication is dangerous: the next module added to one will
be protected at runtime and unguarded at review time, or the reverse, and
nothing reports the disagreement.

The two enforcers are complementary and both need the list:

    mutation_detector       BEFORE execution -- reads candidate source and
                            objects to code that would tamper with these
    runtime_governance      AFTER execution -- holds a fingerprint baseline and
                            detects that one of these actually was tampered with

It lives in `core.governance` because deciding what is safety-critical is a
governance judgement, not a property of either enforcer. Neither package
imports the other, so a shared owner is also the only place both can reach.
"""

from __future__ import annotations

from typing import FrozenSet, Tuple

#: Exact module paths whose replacement or patching is a security event.
CRITICAL_MODULES: FrozenSet[str] = frozenset({
    'core.learning.enhanced_asi_self_improvement',
    'core.learning.upgrade_validator',
    'core.learning.upgrade_sandbox',
    'core.learning.improvement_monitor',
    'core.learning.meta_learning',
    'core.learning.safe_upgrade_deployer',
    'core.learning.safety_audit_trail',
    'core.governance.unified_governance_trigger_system',
    'core.governance.enforcement_mode_manager',
    'core.governance.context_classifier',
    'core.security.safety_framework',
    'core.agents.autonomous.runtime_governance',
    'core.agents.autonomous.governance_agent',
    'core.agents.autonomous.singleton_constitution',
})

#: Package prefixes treated as critical when an exact match is not available.
#: Used for reasoning about code that names a module dynamically.
CRITICAL_MODULE_PREFIXES: Tuple[str, ...] = (
    'core.learning.',
    'core.governance.',
    'core.security.',
    'core.agents.autonomous.',
)


def is_critical(module_path: str) -> bool:
    """Whether a module path is safety-critical.

    Exact membership first, then prefix. An empty or partial path is NOT
    critical: the caller could not establish what module is meant, and
    answering True there is how a substring test came to flag every `setattr`
    in any file that imported from `core.learning`.
    """
    if not module_path or not isinstance(module_path, str):
        return False
    if module_path in CRITICAL_MODULES:
        return True
    return module_path.startswith(CRITICAL_MODULE_PREFIXES)


__all__ = ["CRITICAL_MODULES", "CRITICAL_MODULE_PREFIXES", "is_critical"]
