#!/usr/bin/env python3
"""
Integration Module Init
Core integration framework for Torin AI cross-domain capabilities
"""

from .universal_domain_master import (
    UniversalDomainMaster, DomainIntegrationResult,
    CrossDomainQuery
)

__all__ = [
    'UniversalDomainMaster',
    'DomainIntegrationResult',
    'CrossDomainQuery',
]