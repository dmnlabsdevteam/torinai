"""
Memory Utilities
===============
Embedding service, memory injection, and interfaces.
"""

from .embedding_service import get_embedding_service
from .memory_injector import get_memory_injector
from .interfaces import (
    # Enums
    MemoryType,
    MemoryPriority,
    MemoryStatus,
    MemoryOperation,
    AutobiographicalActionType,
    AutobiographicalImportance,

    # Dataclasses
    MemoryEntry,
    ContextData,
    MemoryItem,
    MemoryQuery,
    MemorySearchResult,
    CognitiveExperience,

    # Interfaces
    IMemoryStore,
    IContextManager,
    IMemorySystem,
)

__all__ = [
    # Services
    'get_embedding_service',
    'get_memory_injector',

    # Enums
    'MemoryType',
    'MemoryPriority',
    'MemoryStatus',
    'MemoryOperation',
    'AutobiographicalActionType',
    'AutobiographicalImportance',

    # Dataclasses
    'MemoryEntry',
    'ContextData',
    'MemoryItem',
    'MemoryQuery',
    'MemorySearchResult',
    'CognitiveExperience',

    # Interfaces
    'IMemoryStore',
    'IContextManager',
    'IMemorySystem',
]
