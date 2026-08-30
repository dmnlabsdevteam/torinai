import logging

from core.capability import CapabilityStatus

logger = logging.getLogger(__name__)

#!/usr/bin/env python3
"""
TorinAI Logical Agents Module
Logical reasoning and proof agents.
"""

# Use deferred imports to avoid circular import issues
def get_logical_integration_agent():
    """Get the logical integration class with deferred import.

    This imported LogicalIntegrationAgent from logical_integration, which
    defines no such name -- the alias is created in this module. Deferring the
    import moved the failure to call time, where a missing name reads as a
    runtime fault instead.
    """
    from .logical_integration import LogicalIntegrationSystem
    return LogicalIntegrationSystem

def get_enhanced_logical_agent():
    """Get EnhancedLogicalAgent class with deferred import"""
    from .enhanced_logical_agent import EnhancedLogicalAgent
    return EnhancedLogicalAgent

def create_logical_integration_agent(*args, **kwargs):
    """Create a logical integration instance.

    logical_integration exposes get_logical_integration(); there is no
    create_logical_integration_agent for this to delegate to, so every call
    raised ImportError.
    """
    from .logical_integration import get_logical_integration
    return get_logical_integration(*args, **kwargs)

def create_enhanced_logical_agent(*args, **kwargs):
    """Create EnhancedLogicalAgent instance"""
    from .enhanced_logical_agent import create_enhanced_logical_agent as _create
    return _create(*args, **kwargs)

# Try to import and expose classes, but gracefully handle circular imports
# The class in logical_integration.py is LogicalIntegrationSystem. The name
# LogicalIntegrationAgent exists nowhere, so this import could never succeed --
# it bound the class to None while the paired factories stayed callable, so
# `is not None` guards passed and the failure was deferred to call time.
from .logical_integration import LogicalIntegrationSystem, get_logical_integration
LogicalIntegrationAgent = LogicalIntegrationSystem   # documented alias
_LOGICAL_INTEGRATION_AVAILABLE = True

# EnhancedLogicalAgent is genuinely unavailable: it subclasses
# core.agents.chat.base_agent, and core/agents/chat/ does not exist.
# Represented explicitly rather than bound to None.
try:
    from .enhanced_logical_agent import EnhancedLogicalAgent
    _ENHANCED_LOGICAL_AVAILABLE = True
    ENHANCED_LOGICAL_STATUS = CapabilityStatus.ok("enhanced_logical_agent")
except ImportError as e:
    _ENHANCED_LOGICAL_AVAILABLE = False
    ENHANCED_LOGICAL_STATUS = CapabilityStatus.missing(
        "enhanced_logical_agent",
        f"missing dependency: {e}",
        module="core.agents.chat.base_agent",
    )
    logger.warning("enhanced_logical_agent unavailable: %s", e)

__all__ = [
    'LogicalIntegrationSystem', 'LogicalIntegrationAgent',
    'get_logical_integration', 'create_logical_integration_agent',
    'ENHANCED_LOGICAL_STATUS',
    'get_logical_integration_agent', 'get_enhanced_logical_agent'
]