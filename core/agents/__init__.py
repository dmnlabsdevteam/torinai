#!/usr/bin/env python3
"""
TorinAI Agents Module
Intelligent agent systems including logical, chat, and autonomous agents with quantum reasoning capabilities.
"""

# Import agent types
from . import logical
from . import autonomous

# Import specific agent classes
# EnhancedLogicalAgent subclasses core.agents.chat.base_agent.BaseAgent, and
# neither that module nor any BaseAgent exists in this codebase, so the logical
# package deliberately does not export the name. Importing it in the same
# statement as the working logical agent let one dead name null out a live one:
# LogicalAgent and create_logical_agent were both set to None even though
# LogicalIntegrationSystem imports and runs fine.
try:
    from .logical import LogicalIntegrationAgent, create_logical_integration_agent
    # Create aliases for backwards compatibility
    LogicalAgent = LogicalIntegrationAgent
    create_logical_agent = create_logical_integration_agent
except ImportError as _e:
    # Log rather than discard: a swallowed ImportError here is exactly how a
    # whole subsystem goes dark without anyone noticing.
    import logging as _logging
    _logging.getLogger(__name__).warning("logical agents unavailable: %s", _e)
    LogicalAgent = None
    create_logical_agent = None

try:
    from .autonomous import AutonomousCoordinator, create_autonomous_system
    # Create aliases for backwards compatibility
    AutonomousAgent = AutonomousCoordinator
    create_autonomous_agent = create_autonomous_system
except ImportError:
    AutonomousAgent = None
    create_autonomous_agent = None


# agents.py defines create_agent_coordinator, never create_agents_system --
# a name that exists nowhere in the codebase. The bare except bound it to None
# and the __all__ guard hid it, so the entire multi-agent subsystem was
# invisible to production code.
from .agents import AgentCoordinator, create_agent_coordinator

CHAT_AVAILABLE = False

__all__ = [
    "logical",
    "autonomous"
]

# Add conditionally available exports
if 'LogicalAgent' in globals() and LogicalAgent is not None:
    __all__.extend(["LogicalAgent", "create_logical_agent"])

if 'AutonomousAgent' in globals() and AutonomousAgent is not None:
    __all__.extend(["AutonomousAgent", "create_autonomous_agent"])

__all__.extend(["AgentCoordinator", "create_agent_coordinator"])