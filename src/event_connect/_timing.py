"""How a device's points are read: the seconds between reads per poll rate, and how long a write
takes to show."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._clock import Clock
from ._point import Point, PollRate
from ._scheduler import Scheduler, checked_intervals


@dataclass(frozen=True, kw_only=True)
class Timing:
    """When a device's points are read, and how long its writes take to show."""
    poll_intervals: Mapping[PollRate, float]
    """Seconds between reads per poll rate a point is read at on a timer; `PollRate.STATIC` has
    none."""
    read_back_after: float
    """Seconds from a write until a read shows it."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "poll_intervals", checked_intervals(self.poll_intervals))
        if not (math.isfinite(self.read_back_after) and self.read_back_after >= 0):
            raise ValueError(f"read_back_after must be a finite number >= 0, got {self.read_back_after}")

    @property
    def fastest_interval(self) -> float | None:
        """The shortest of its intervals; None when no poll rate is read on a timer."""
        return min(self.poll_intervals.values(), default=None)

    def scheduler(self, clock: Clock) -> Scheduler:
        """A scheduler that plans by this timing."""
        return Scheduler(clock, self.poll_intervals)

    def written_point_delay(self, point: Point[Any]) -> float:
        """Seconds after writing `point` before it is read back: `read_back_after`, whatever its
        `on_write` says."""
        return self.read_back_after

    def on_write_delay(self, point: Point[Any]) -> float:
        """Seconds after writing `point` before the points its `on_write` names are read: the
        refresh's `after`, or `read_back_after` where it has none."""
        if point.on_write is not None and point.on_write.after is not None:
            return point.on_write.after
        return self.read_back_after
