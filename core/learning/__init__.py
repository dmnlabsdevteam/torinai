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
# `UnifiedLearningSystem` below is a CONTRIBUTOR to it, not the owner. It was
# the declared authority while referencing the substrate's learners zero times,
# and while the stack with the experimental evidence behind it answered to
# nobody. Anything it proposes enters through `SubstrateLearning.contribute()`
# as a CANDIDATE with no evidence roots.
from .learning_authority import (Admission, Contribution, ContributionKind,
                                 SubstrateLearning, get_learning_authority)
from .unified_learning_system import UnifiedLearningSystem, get_unified_learning_system
from ..memory import MemoryManager as AGIMemorySystem
from .learning_interfaces import ILearningSystem, LearningType
from .enhanced_asi_self_improvement import ImprovementScope

# Retained alias: core.reasoning imports this name.
MasterLearningSystem = UnifiedLearningSystem

__all__ = [
    # The authority.
    'SubstrateLearning',
    'get_learning_authority',
    'Contribution',
    'ContributionKind',
    'Admission',
    # A contributor to it.
    'UnifiedLearningSystem',
    'MasterLearningSystem',
    'AGIMemorySystem',
    'ILearningSystem',
    'LearningType',
    'ImprovementScope',
    'get_unified_learning_system',
]
