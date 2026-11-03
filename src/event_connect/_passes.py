"""One pass at a time over what is due on a device."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class Passes:
    """Runs passes one at a time, in the order they were asked for.

    A call made while another call is running or waiting for a pass waits its turn, then makes a
    pass of its own only if something is still due, so callers that poll together cause one pass,
    not several. What a pass or a check of what is due raises reaches only the call it belongs to,
    and a call that is cancelled leaves the calls behind it to go on.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._calls = 0
        self._holder: asyncio.Task[object] | None = None

    @property
    def running(self) -> bool:
        """Whether a call holds the turn: it is running its pass, or checking whether it needs one."""
        return self._lock.locked()

    async def run(self, work: Callable[[], Awaitable[None]], *, due: Callable[[], bool]) -> bool:
        """Run `work` as a pass, after the passes of the calls before this one; then, if another
        call was running or waiting when this one was made, only if `due()` still says something
        is due. `due` is asked at most once, and never by a call that did not wait.

        Returns:
            Whether this call ran `work`.

        Raises:
            RuntimeError: `work` called `run` on this `Passes`, which would wait for itself.
        """
        if self._holder is not None and self._holder is asyncio.current_task():
            raise RuntimeError("a pass called run on its own Passes, and would wait for itself")
        # Counted rather than read from the lock: between one pass releasing the lock and the
        # next waiter taking it, the lock is free although a call is queued.
        waited = self._calls > 0
        self._calls += 1
        try:
            async with self._lock:
                self._holder = asyncio.current_task()
                try:
                    # Asked only once this call holds the lock, so that it sees what the passes
                    # queued before it have read.
                    if waited and not due():
                        return False
                    await work()
                finally:
                    self._holder = None
            return True
        finally:
            self._calls -= 1
