#!/usr/bin/env python3
"""
TorinAI Memory Module - Centralized Memory Management

Single Entry Point: MemoryAgent
Storage: PostgreSQL (hot tier + cold tier for 60+ day old memories)
Query: Intelligent tagging for "what did I do and when" queries
Logging: All memory operations logged to PostgreSQL

Architecture:
- PostgreSQL Hot Tier (memory_hot): Last 60 days of memories - thinking states,
  reasoning traces, cognitive experiences, actions, system state
- PostgreSQL Cold Tier (memory_cold): Memories 60+ days old, archived for
  long-term storage
- R2 Backups: Encrypted system data backups (backups only, not memory storage)
- Logging: All operations logged to PostgreSQL via LoggingDatabase
"""

# Memory types and interfaces from utils (import these first to avoid circular dependencies)
from .utils.interfaces import (
    MemoryType,
    MemoryPriority,
    MemoryStatus,
    MemoryOperation,
    MemoryScope,
    MemoryEntry,
    MemoryItem,
    MemoryQuery,
    ContextData,
    CognitiveExperience,
    AutobiographicalActionType,
    AutobiographicalImportance,
)


# Deferred imports to avoid circular dependency
def _get_memory_agent_class():
    """Lazy import of MemoryAgent to avoid circular imports"""
    from core.agents.memory_agent import MemoryAgent
    return MemoryAgent


async def get_memory_agent():
    """Get the memory agent singleton"""
    from core.agents.memory_agent import get_memory_agent as _get_agent
    return await _get_agent()


async def initialize_memory_agent(**kwargs):
    """Initialize the memory agent"""
    from core.agents.memory_agent import initialize_memory_agent as _init_agent
    return await _init_agent(**kwargs)


# Aliases for backwards compatibility
get_memory_manager = get_memory_agent
initialize_memory_manager = initialize_memory_agent


# Lazy-loaded class aliases
class _MemoryAgentClassProxy:
    """Proxy that exposes the MemoryAgent *class* without instantiating it.

    This preserves backwards-compatible type usage (e.g., isinstance checks,
    attribute existence) while ensuring all *instances* are created via the
    async get_memory_agent() singleton entrypoint.
    """

    def __getattr__(self, name):  # pragma: no cover - simple delegation
        return getattr(_get_memory_agent_class(), name)


# Public class aliases (for typing / isinstance / attribute checks only)
MemoryAgent = _MemoryAgentClassProxy()
MemoryManager = MemoryAgent
CentralizedMemoryManager = MemoryAgent
UnifiedMemorySystem = MemoryAgent  # Alias for unified memory system


# Singleton getter
async def get_memory_system():
    """Get memory system singleton"""
    return await get_memory_agent()


get_unified_memory = get_memory_system  # Alias

__all__ = [
    # PRIMARY INTERFACE (use these)
    'MemoryAgent',
    'get_memory_agent',
    'initialize_memory_agent',
    'UnifiedMemorySystem',
    'get_memory_system',
    'get_unified_memory',

    # DEPRECATED ALIASES (use MemoryAgent instead)
    'CentralizedMemoryManager',
    'get_memory_manager',
    'initialize_memory_manager',
    'MemoryManager',

    # Memory types and interfaces
    'MemoryType',
    'MemoryPriority',
    'MemoryStatus',
    'MemoryOperation',
    'MemoryScope',
    'MemoryEntry',
    'MemoryItem',
    'MemoryQuery',
    'ContextData',
    'CognitiveExperience',
    'AutobiographicalActionType',
    'AutobiographicalImportance',
]
