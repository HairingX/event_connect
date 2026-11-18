"""A clock for tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone


class FakeClock:
    """A clock that moves only when told to, so scheduling can be tested without waiting.

    A `sleep()` waits on this clock, not in real time, in one of two ways:

    - By default it returns once `advance()` has moved the clock to its end; sleeps that end
      together return in the order they began. For a loop in a task of its own: the test moves
      the clock, then lets that task run.
    - With `autojump`, it moves the clock to its own end at once, and returns as soon as the other
      tasks ready to run have had a turn. For a call the test awaits that pauses inside it: the
      call returns without waiting, and the clock shows the pause. Never with a loop that sleeps
      in a task of its own, which would then move the clock on without end.

    `sleeps` records the seconds of every sleep, in the order they were asked for.
    """

    def __init__(self, monotonic: float = 1000.0,
                 now: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc), *, autojump: bool = False) -> None:
        if now.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware start time")
        self._monotonic = monotonic
        self._now = now
        self._autojump = autojump
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []
        self.sleeps: list[float] = []
        """The seconds of every `sleep()` so far, in the order asked; a test may clear it."""

    def monotonic(self) -> float:
        """The scheduling clock's seconds."""
        return self._monotonic

    def now(self) -> datetime:
        """The wall clock's time."""
        return self._now

    async def sleep(self, seconds: float) -> None:
        """Return once the clock has moved `seconds` on; at once, after the other ready tasks, for
        `seconds` of 0 or less."""
        self.sleeps.append(seconds)
        if seconds <= 0 or self._autojump:
            if seconds > 0:
                self.advance(seconds)
            await asyncio.sleep(0)
            return
        sleeper = (self._monotonic + seconds, asyncio.get_running_loop().create_future())
        self._sleepers.append(sleeper)
        try:
            await sleeper[1]
        finally:
            if sleeper in self._sleepers:
                self._sleepers.remove(sleeper)

    def advance(self, seconds: float) -> None:
        """Move both clocks forwards by `seconds`, and wake every sleep that has then ended; each
        returns once its task next runs."""
        if seconds < 0:
            raise ValueError("a clock cannot be advanced backwards; use jump_wall() for that")
        self._monotonic += seconds
        self._now += timedelta(seconds=seconds)
        ended = sorted((s for s in self._sleepers if s[0] <= self._monotonic), key=lambda s: s[0])
        for sleeper in ended:
            self._sleepers.remove(sleeper)
            future = sleeper[1]
            # A sleep left behind by an event loop that has since closed cannot be woken.
            if not future.done() and not future.get_loop().is_closed():
                future.set_result(None)

    def jump_wall(self, seconds: float) -> None:
        """Move only the wall clock, forwards or backwards; no sleep ends by it."""
        self._now += timedelta(seconds=seconds)
