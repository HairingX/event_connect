"""One pass at a time over what is due on a device."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class Passes:
    """Runs passes one at a time: a call made during a pass waits for it, then makes a pass of its
    own only if something is still due, so callers that poll together cause one pass, not several.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        """Whether a pass is running now."""
        return self._lock.locked()

    async def run(self, work: Callable[[], Awaitable[None]], *, due: Callable[[], bool]) -> bool:
        """Run `work` as a pass, after any pass already running; then only if `due()` still says
        something is due. Returns whether this call ran it."""
        waited = self._lock.locked()
        async with self._lock:
            # Asked only once this call holds the lock, so that it sees what the passes queued
            # before it have read.
            if waited and not due():
                return False
            await work()
        return True
