#!/usr/bin/env python3
"""
Global Llama Inference Lock
===========================
Prevents concurrent llama_decode calls across multiple Llama() instances.

The ggml-blas backend shares state across all Llama instances in a process.
Concurrent llama_decode calls cause race conditions and SIGSEGV crashes.

This module provides a single asyncio.Lock that UnifiedLLMService must acquire
before calling any Llama inference.
"""

import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Global lock for all llama inference operations
# Using threading.Lock for thread-safety + asyncio wrapper
_llama_thread_lock = threading.Lock()
_llama_async_lock: Optional[asyncio.Lock] = None


def get_llama_lock() -> asyncio.Lock:
    """
    Get the global asyncio lock for llama inference.
    
    Must be acquired before ANY llama_decode/generate call.
    This ensures only one model computes at a time, preventing
    ggml-blas race conditions.
    """
    global _llama_async_lock
    if _llama_async_lock is None:
        _llama_async_lock = asyncio.Lock()
        logger.info("Global llama inference lock initialized")
    return _llama_async_lock


def get_llama_thread_lock() -> threading.Lock:
    """
    Get the global threading lock for synchronous llama operations.
    Use this when not in an async context.
    """
    return _llama_thread_lock
