"""One llama lock per process, or ggml-blas races and the process SIGSEGVs.

These tests previously asserted on log strings ("Initializing asyncio.Lock for
llama inference") that the module has never emitted -- it logs "Global llama
inference lock initialized", and only on first creation, so the assertion could
not hold once any earlier import had already built the lock.

Log text is also the wrong invariant. What has to be true is that every caller
receives the SAME lock object: two locks serialise nothing, and the failure
they exist to prevent is a crash, not a missing message.
"""
import asyncio
import threading

import pytest

from core.services import llama_lock
from core.services.llama_lock import get_llama_lock, get_llama_thread_lock


def test_the_thread_lock_is_one_object_for_the_process():
    first = get_llama_thread_lock()
    second = get_llama_thread_lock()

    assert isinstance(first, type(threading.Lock()))
    assert first is second, "two threading locks serialise nothing"


@pytest.mark.asyncio
async def test_the_async_lock_is_one_object_for_the_process():
    first = get_llama_lock()
    second = get_llama_lock()

    assert isinstance(first, asyncio.Lock)
    assert first is second, "two asyncio locks serialise nothing"


@pytest.mark.asyncio
async def test_the_async_lock_is_built_on_first_use_not_at_import():
    """asyncio.Lock binds to the running loop, so building it at import time
    would tie the process to whichever loop happened to exist then."""
    llama_lock._llama_async_lock = None

    assert llama_lock._llama_async_lock is None
    created = get_llama_lock()
    assert llama_lock._llama_async_lock is created


@pytest.mark.asyncio
async def test_the_async_lock_actually_excludes():
    """The property the whole module exists for: while one holder has it, no
    second holder gets in."""
    lock = get_llama_lock()
    order = []

    async def hold(name, delay):
        async with lock:
            order.append(f"{name}:enter")
            await asyncio.sleep(delay)
            order.append(f"{name}:exit")

    await asyncio.gather(hold("a", 0.05), hold("b", 0.0))

    # Whoever went first must have exited before the other entered.
    assert order[1].endswith(":exit"), f"holders overlapped: {order}"
