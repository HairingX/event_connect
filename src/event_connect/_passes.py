"""One pass at a time over what is due on a device."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class Passes:
    """Runs passes one at a time: a call made while another call is running or waiting for a
    pass waits its turn, then makes a pass of its own only if something is still due, so callers
    that poll together cause one pass, not several.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._calls = 0

    @property
    def running(self) -> bool:
        """Whether a pass is running now."""
        return self._lock.locked()

    async def run(self, work: Callable[[], Awaitable[None]], *, due: Callable[[], bool]) -> bool:
        """Run `work` as a pass, after the passes of the calls before this one; then, if another
        call was running or waiting when this one was made, only if `due()` still says something
        is due. Returns whether this call ran it."""
        # Counted rather than read from the lock: between one pass releasing the lock and the
        # next waiter taking it, the lock is free although a call is queued.
        waited = self._calls > 0
        self._calls += 1
        try:
            async with self._lock:
                # Asked only once this call holds the lock, so that it sees what the passes queued
                # before it have read.
                if waited and not due():
                    return False
                await work()
            return True
        finally:
            self._calls -= 1
