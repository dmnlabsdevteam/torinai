"""Shared semantic vocabulary. One canonical reading of a surface form.

Two declared readings, because identity and retrieval have opposite failure
modes -- see `lexical_normalization.match_key`.
"""

from .lexical_normalization import (canonical_label, canonical_term, match_key,
                                    normalise, singularise)

__all__ = ["canonical_label", "canonical_term", "match_key", "normalise",
           "singularise"]
