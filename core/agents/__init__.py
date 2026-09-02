#!/usr/bin/env python3
"""
TorinAI Agents Module

Two things live here now: the autonomous coordinator (the substrate SELF) and
the agent factory (`agents.py`). There is no "logical agent" and no
"research agent": logical/formal reasoning is reasoning SUBSTRATE
(`core.reasoning.logical_integration`) that any agent shares, and
research is a TOOL (`conduct_research`). An agent is a lightweight copy
of the substrate that shares its deputies (reasoning, learning, memory), so it
does not need its own specialised agent classes.
"""

from . import autonomous

try:
    from .autonomous import AutonomousCoordinator, create_autonomous_system
    AutonomousAgent = AutonomousCoordinator
    create_autonomous_agent = create_autonomous_system
except ImportError:
    AutonomousAgent = None
    create_autonomous_agent = None

from .agents import AgentCoordinator, get_agent_coordinator

__all__ = ["autonomous"]

if 'AutonomousAgent' in globals() and AutonomousAgent is not None:
    __all__.extend(["AutonomousAgent", "create_autonomous_agent"])

__all__.extend(["AgentCoordinator", "get_agent_coordinator"])