"""How a library plans the reads of its devices: one profile, set by the library, that a client
can be given another of."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ._clock import Clock
from ._point import DEFAULT_INTERVALS, Point, PollRate
from ._scheduler import Scheduler


@dataclass(frozen=True)
class Timing:
    """When a device's points are read, and how long its writes take to show.

    A library sets one for its devices, as measured on them; a client may be given another.
    """
    poll_intervals: Mapping[PollRate, float | None] = field(default_factory=lambda: DEFAULT_INTERVALS)
    """Seconds between reads per poll rate; a rate left out keeps its default."""
    min_poll_interval: float = 0.0
    """The shortest interval any point may be read at, however it is overridden."""
    read_back_after: float = 1.0
    """Seconds from a write until a read shows it, unless a point says otherwise."""
    retry_after: float = 1.0
    """Seconds before a failed read is tried again, doubled at each further failure up to the
    point's interval; 0 waits for the next regular read."""
    offline_after: float = 30.0
    """Seconds a device may go without answering before it counts as not answering; a single
    lost answer then does not make it unavailable."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "poll_intervals", MappingProxyType(dict(self.poll_intervals)))
        for name in ("min_poll_interval", "read_back_after", "retry_after", "offline_after"):
            seconds: float = getattr(self, name)
            if not (math.isfinite(seconds) and seconds >= 0):
                raise ValueError(f"{name} must be a finite number >= 0, got {seconds}")

    def scheduler(self, clock: Clock) -> Scheduler:
        """A scheduler that plans by this timing."""
        return Scheduler(clock, self.poll_intervals, min_poll_interval=self.min_poll_interval,
                         retry_after=self.retry_after)

    def read_back_delay(self, point: Point[Any]) -> float:
        """Seconds after writing `point` before what its write disturbs is read."""
        if point.on_write is not None and point.on_write.after is not None:
            return point.on_write.after
        return point.read_back_after if point.read_back_after is not None else self.read_back_after


DEFAULT_TIMING = Timing()
"""A timing for a device nothing has been measured on: the default poll intervals, a second for a
write to show, a failed read tried again after a second, and half a minute of silence before the
device counts as not answering."""
