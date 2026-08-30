#!/usr/bin/env python3
"""Moved to `core.semantics.sentence_machine`.

Seven runtime call sites in `core/semantics/conversation.py` imported this out
of `experiments/`, so the live reading path depended on an experiment directory.
It is a runtime component and now lives in core; this re-export keeps EDU-13 and
EDU-14 running against the same object rather than a copy that can drift.
"""

from core.semantics.sentence_machine import *          # noqa: F401,F403
from core.semantics.sentence_machine import (AFFIRMS, DENIES, FLAGS,  # noqa: F401
                                             INSTRUCTIONS, SentenceMachine,
                                             tokenize)
