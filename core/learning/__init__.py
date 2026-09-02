#!/usr/bin/env python3
"""
TorinAI Learning System Initialization

Imports here are unguarded on purpose. A learning package that imports
successfully while its own components are None is worse than one that fails:
the None travels to an unrelated call site and fails there instead, so the
traceback names a consumer rather than the broken import. Every consumer of
these names (ImprovementScope alone has 54) would have to defend itself
against a package that claims to have loaded.

If an import here fails, the package fails, at the line responsible.
"""

import logging

logger = logging.getLogger(__name__)

# THE AUTHORITY FOR LEARNING is the substrate -- induction, epistemic
# status, active teaching, learning under noise, analogical transfer,
# hidden-cause detection -- reached through `get_learning_authority()`.
#
# `UnifiedLearningSystem` IS this authority. The correct model-free
# ILearningAuthority (once a separate `SubstrateLearning` in a deleted
# learning_authority.py) was folded into it, and the meta-learning strategies
# are first-class parts of it. Anything else that learns is a CONTRIBUTOR:
# it proposes through `contribute()` and enters as a CANDIDATE with no evidence
# roots. `get_learning_authority()` and `get_unified_learning_system()` return
# the one object.
from .unified_learning_system import (Admission, Contribution, ContributionKind,
                                     UnifiedLearningSystem,
                                     get_learning_authority,
                                     get_unified_learning_system)
from ..memory import MemoryManager as AGIMemorySystem
from .learning_interfaces import ILearningSystem, LearningType
from .enhanced_asi_self_improvement import ImprovementScope

# Retained alias: core.reasoning imports this name.
MasterLearningSystem = UnifiedLearningSystem

__all__ = [
    # The one learning authority (UnifiedLearningSystem IS it).
    'UnifiedLearningSystem',
    'get_learning_authority',
    'get_unified_learning_system',
    'Contribution',
    'ContributionKind',
    'Admission',
    'MasterLearningSystem',
    'AGIMemorySystem',
    'ILearningSystem',
    'LearningType',
    'ImprovementScope',
    'get_unified_learning_system',
]
