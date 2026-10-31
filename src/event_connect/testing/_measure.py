"""Working out a device's timing from what was measured on it: how long it takes to answer, and
how long a value takes to settle after a change."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class Latency:
    """How long a device took to answer each of a series of requests, in seconds; None for a
    request it did not answer."""
    answers: tuple[float | None, ...]

    @property
    def answered(self) -> tuple[float, ...]:
        """The times of the requests it answered."""
        return tuple(seconds for seconds in self.answers if seconds is not None)

    @property
    def median(self) -> float | None:
        """The middle answer time; None if it answered none."""
        return statistics.median(self.answered) if self.answered else None

    @property
    def slowest(self) -> float | None:
        """The longest answer time; None if it answered none."""
        return max(self.answered, default=None)

    @property
    def unanswered(self) -> int:
        """How many requests it did not answer."""
        return sum(1 for seconds in self.answers if seconds is None)

    def __str__(self) -> str:
        if not self.answered:
            return f"no answer to {len(self.answers)} requests"
        return (f"answered {len(self.answered)} of {len(self.answers)} requests: "
                f"median {self.median:.3f} s, slowest {self.slowest:.3f} s")


@dataclass(frozen=True)
class Settling:
    """A value read again and again after a change: when, and what it was."""
    change: str
    readings: tuple[tuple[float, float], ...]
    """Seconds after the change, and the value read then."""
    tolerance: float
    """How far apart two values may be and still count as the same."""

    @property
    def settled_after(self) -> float | None:
        """Seconds after the change from which every reading stays within the tolerance of the
        last; None if the last two readings do not agree, so it had not settled."""
        if len(self.readings) < 2 or abs(self.readings[-1][1] - self.readings[-2][1]) > self.tolerance:
            return None
        final = self.readings[-1][1]
        settled = self.readings[-1][0]
        for seconds, value in reversed(self.readings):
            if abs(value - final) > self.tolerance:
                break
            settled = seconds
        return settled

    def __str__(self) -> str:
        settled = self.settled_after
        values = ", ".join(f"{seconds:.1f} s: {value:g}" for seconds, value in self.readings)
        outcome = "did not settle" if settled is None else f"settled after {settled:.1f} s"
        return f"{self.change}: {outcome} ({values})"


def recommended_refresh(settlings: tuple[Settling, ...], every: float) -> tuple[float, float] | None:
    """An `after` and an `until_stable` that follow every measured change until it settles: the
    first read when the slowest has settled, and room for one twice as slow; None when one did
    not settle.

    Args:
        every: the seconds between the readings, which `after` is rounded up to.
    """
    times = [settling.settled_after for settling in settlings]
    if not times or any(seconds is None for seconds in times):
        return None
    slowest = max(seconds for seconds in times if seconds is not None)
    after = max(every, math.ceil(slowest / every) * every)
    return after, max(after * 2, math.ceil(slowest * 2))
