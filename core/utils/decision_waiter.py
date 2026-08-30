
#!/usr/bin/env python3
import asyncio
from typing import Dict, Optional

class DecisionWaiter:
    """In-process async waiter for approval/decline decisions by notification id."""
    def __init__(self) -> None:
        self._futures: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def wait(self, notif_id: str, timeout: Optional[float] = None) -> bool:
        """Wait for decision. Returns True if approved, False if declined/timeout."""
        async with self._lock:
            fut = self._futures.get(notif_id)
            if not fut:
                fut = asyncio.get_event_loop().create_future()
                self._futures[notif_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout) if timeout else await fut
        except asyncio.TimeoutError:
            return False
        finally:
            async with self._lock:
                self._futures.pop(notif_id, None)

    async def set(self, notif_id: str, approved: bool) -> None:
        async with self._lock:
            fut = self._futures.get(notif_id)
        if fut and not fut.done():
            fut.set_result(bool(approved))
