"""Which keys are due for a read, and when: no I/O, no timer, no sleep."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ._clock import Clock
from ._point import Point, PollRate
from ._value import DataValue, Quality, Value

GATHER_WITHIN = 1.0
"""Seconds ahead of its rhythm a key is read with others that are due, so that keys read together
stay together: their rhythms otherwise drift apart by the moments between their records, and each
is read on its own."""
GATHER_SHARE = 0.1
"""The most of its interval a key is read ahead of its rhythm."""


@dataclass(frozen=True, slots=True)
class _Pending:
    """An extra read scheduled by `refresh`, waiting to be consumed by `record`."""
    not_before: float
    """Monotonic time the read may happen at the earliest."""
    after: float
    """The `after` it was scheduled with - reused as the interval while following."""
    follow_deadline: float | None
    """Monotonic time the following this read may start ends, if it starts any."""


@dataclass(slots=True)
class _Following:
    """A key re-read until its value settles, driven forward by successive `record` calls."""
    deadline: float
    """Monotonic time following ends, whatever happens."""
    after: float
    """Seconds between reads while following."""
    baseline: tuple[Value, Quality] | None = None
    """The previous successful read; `None` until the first one lands."""


class Scheduler:
    """The schedule of one device: poll intervals, pending refreshes, following.

    Each key keeps its own rhythm: a read a refresh or a retry asked for does not move the next
    regular one. Whenever a key is due on its rhythm, the keys due within a second, at most a tenth
    of their interval, are read with it, and take its rhythm. Whether, and when, a failed read is
    tried again is the protocol's to say, as it alone knows what a failure means: it says so when it
    records the read.
    """

    def __init__(self, clock: Clock, poll_intervals: Mapping[PollRate, float]) -> None:
        """Plan by `poll_intervals`, the seconds between reads of each poll rate a point is read at
        on a timer.

        Raises:
            ValueError: an interval is not a finite number above 0, or one is given for
                `PollRate.STATIC`, which is never read on a timer.
        """
        self._clock = clock
        self._intervals = checked_intervals(poll_intervals)

        self._scheduled = True
        self._points: dict[str, Point[Any]] = {}
        self._polled: dict[str, bool] = {}
        self._last_regular: dict[str, float] = {}
        """When each key was last read on its own rhythm."""
        self._pending: dict[str, _Pending] = {}
        self._following: dict[str, _Following] = {}
        self._retry_at: dict[str, float] = {}
        self._failures: dict[str, int] = {}

    # ------------------------------------------------------------------------------- points

    def set_points(self, points: Iterable[Point[Any]]) -> None:
        """Adopts the readable points of a (re)resolved model.

        State for a key that persists is kept; a new key starts unpolled.

        Raises:
            ValueError: naming every readable point whose poll rate has no interval.
        """
        new_points: dict[str, Point[Any]] = {point.key: point for point in points if point.readable}
        unplanned = [f"{key!r} ({point.poll_rate.name})" for key, point in new_points.items()
                     if point.poll_rate is not None and point.poll_rate is not PollRate.STATIC
                     and point.poll_rate not in self._intervals]
        if unplanned:
            raise ValueError("no interval for the poll rate of " + ", ".join(unplanned))
        for key in list(self._points):
            if key not in new_points:
                self._polled.pop(key, None)
                self._last_regular.pop(key, None)
                self._pending.pop(key, None)
                self._following.pop(key, None)
                self._retry_at.pop(key, None)
                self._failures.pop(key, None)
        for key in new_points:
            if key not in self._points:
                self._polled[key] = False
        self._points = new_points

    # -------------------------------------------------------------------------------- polled

    def set_polled(self, key: str, polled: bool) -> None:
        """Whether `key` takes part in scheduling: timer reads and non-forced refreshes."""
        self._require(key)
        self._polled[key] = polled

    def is_polled(self, key: str) -> bool:
        """Whether `key` takes part in scheduling."""
        self._require(key)
        return self._polled[key]

    def set_scheduled(self, enabled: bool) -> None:
        """Whether polled keys are read on their intervals; a refresh is read either way."""
        self._scheduled = enabled

    # ----------------------------------------------------------------------------- intervals

    def interval(self, key: str) -> float | None:
        """Seconds between regular reads of `key`: its poll rate's; None for a key never read on a
        timer."""
        self._require(key)
        poll_rate = self._points[key].poll_rate
        return None if poll_rate is None else self.rate_interval(poll_rate)

    def rate_interval(self, poll_rate: PollRate) -> float | None:
        """Seconds between reads at `poll_rate`; None for `PollRate.STATIC`, which is never read on
        a timer.

        Raises:
            KeyError: `poll_rate` has no interval.
        """
        if poll_rate is PollRate.STATIC:
            return None
        return self._intervals[poll_rate]

    # ------------------------------------------------------------------------------ refresh

    def refresh(self, keys: Iterable[str], *, after: float = 0.0, until_stable: float | None = None,
                force: bool = False) -> None:
        """Schedules an extra read of `keys`, not before `now + after`.

        `force` reads even an unpolled key; `until_stable` re-reads every `after` seconds while
        the value changes, until `until_stable` seconds pass."""
        if after < 0:
            raise ValueError(f"after cannot be negative, got {after}")
        if until_stable is not None:
            if not until_stable > 0:
                raise ValueError(f"until_stable must be positive or None, got {until_stable}")
            if not after > 0:
                raise ValueError("until_stable needs a positive after to re-read at")

        keys = list(keys)
        for key in keys:
            self._require(key)

        now = self._clock.monotonic()
        not_before = now + after
        follow_deadline = now + until_stable if until_stable is not None else None
        for key in keys:
            if not force and not self._polled.get(key, False):
                continue
            self._pending[key] = _merge(self._pending.get(key),
                                         _Pending(not_before, after, follow_deadline))

    def reset(self, keys: Iterable[str] | None = None) -> None:
        """Forgets the last attempt of `keys` (or all of them), so they are due as if never read;
        clears their pending refreshes and following too."""
        targets = list(self._points) if keys is None else list(keys)
        for key in targets:
            self._require(key)
        for key in targets:
            self._last_regular.pop(key, None)
            self._pending.pop(key, None)
            self._following.pop(key, None)
            self._retry_at.pop(key, None)
            self._failures.pop(key, None)

    # ---------------------------------------------------------------------------------- read

    def record(self, key: str, value: DataValue[Any] | None, *, success: bool,
               retry_after: float | None = None) -> None:
        """Reports the outcome of a read attempt for `key`; may consume a pending refresh and
        advance following.

        Args:
            retry_after: seconds after which the protocol asks for `key` to be read again, sooner
                than its rhythm would; None leaves it to the rhythm, and ends one asked for before.
        """
        self._require(key)
        if retry_after is not None and not (math.isfinite(retry_after) and retry_after >= 0):
            raise ValueError(f"retry_after must be a finite number >= 0, got {retry_after}")
        now = self._clock.monotonic()
        refresh = self._pending.get(key)
        asked = (refresh is not None and refresh.not_before <= now) or self._retry_at.get(key, math.inf) <= now
        if self._regular_due(key) - (0.0 if asked else self._gather(key)) <= now:
            self._last_regular[key] = now
        self._record_outcome(key, success, now, retry_after)

        pending = self._pending.get(key)
        if pending is None or pending.not_before > now:
            return
        del self._pending[key]
        if pending.follow_deadline is not None and key not in self._following:
            self._following[key] = _Following(pending.follow_deadline, pending.after)
        if key in self._following:
            self._advance_following(key, value, success, now)

    def keys(self) -> list[str]:
        """Every key it schedules."""
        return list(self._points)

    def consecutive_failures(self, key: str) -> int:
        """How many reads of `key` in a row have failed."""
        self._require(key)
        return self._failures.get(key, 0)

    def _record_outcome(self, key: str, success: bool, now: float, retry_after: float | None) -> None:
        if success:
            self._failures.pop(key, None)
        else:
            self._failures[key] = self._failures.get(key, 0) + 1
        if retry_after is None:
            self._retry_at.pop(key, None)
        else:
            self._retry_at[key] = now + retry_after

    def _advance_following(self, key: str, value: DataValue[Any] | None, success: bool, now: float) -> None:
        following = self._following[key]
        sample = (value.value, value.quality) if success and value is not None else None
        if sample is not None:
            if following.baseline is not None and _agree(following.baseline, sample, self._points[key].deadband):
                del self._following[key]
                return
            following.baseline = sample
        if now < following.deadline:
            self._pending[key] = _Pending(now + following.after, following.after, following.deadline)
        else:
            del self._following[key]

    # ---------------------------------------------------------------------------------- due

    def due(self) -> list[str]:
        """Keys to read now, in priority order: pending refreshes and the retries a protocol asked
        for, never-read, most overdue."""
        now = self._clock.monotonic()
        order = {key: index for index, key in enumerate(self._points)}
        asked = {key: pending.not_before for key, pending in self._pending.items() if pending.not_before <= now}
        for key, at in self._retry_at.items():
            if at <= now:
                asked[key] = min(at, asked.get(key, at))
        ready = sorted(asked, key=lambda key: (asked[key], order[key]))
        seen = set(ready)
        regular = self._regular_times()
        never = [key for key, due in regular.items() if key not in seen and due == -math.inf]
        overdue = sorted((key for key, due in regular.items() if key not in seen and -math.inf < due <= now),
                         key=lambda key: (regular[key], order[key]))
        if not (never or overdue):
            return ready
        taken = seen.union(never, overdue)
        soon = sorted((key for key, due in regular.items() if key not in taken and due - self._gather(key) <= now),
                      key=lambda key: (regular[key], order[key]))
        return ready + never + overdue + soon

    def next_due(self) -> float | None:
        """The monotonic time `due()` would next return something; `None` if nothing ever will."""
        now = self._clock.monotonic()
        candidates = [pending.not_before for pending in self._pending.values()]
        candidates += self._retry_at.values()
        candidates += [max(due, now) for due in self._regular_times().values()]
        return min(candidates) if candidates else None

    def _regular_times(self) -> dict[str, float]:
        """When each polled key is next due on its own rhythm: -inf if never read; keys that never
        will be are left out."""
        if not self._scheduled:
            return {}
        times: dict[str, float] = {}
        for key in self._points:
            if self._polled.get(key, False):
                due = self._regular_due(key)
                if due < math.inf:
                    times[key] = due
        return times

    def _gather(self, key: str) -> float:
        """Seconds ahead of its rhythm `key` may be read with others."""
        interval = self.interval(key)
        return 0.0 if interval is None else min(GATHER_WITHIN, GATHER_SHARE * interval)

    def _regular_due(self, key: str) -> float:
        last = self._last_regular.get(key)
        if last is None:
            return -math.inf
        interval = self.interval(key)
        return math.inf if interval is None else last + interval

    # -------------------------------------------------------------------------------- internal

    def _require(self, key: str) -> None:
        if key not in self._points:
            raise KeyError(key)


def checked_intervals(poll_intervals: Mapping[PollRate, float]) -> Mapping[PollRate, float]:
    """A read-only copy of `poll_intervals`, once each is found to be an interval a rate can be
    read at.

    Raises:
        ValueError: naming every interval that is not a finite number above 0, and
            `PollRate.STATIC`, which is never read on a timer, if it is given one.
    """
    problems = [f"{poll_rate.name} is never read on a timer, and takes no interval"
                for poll_rate in poll_intervals if poll_rate is PollRate.STATIC]
    problems += [f"the interval of {poll_rate.name} must be a finite number above 0, got {seconds}"
                 for poll_rate, seconds in poll_intervals.items()
                 if poll_rate is not PollRate.STATIC and not (math.isfinite(seconds) and seconds > 0)]
    if problems:
        raise ValueError("; ".join(problems))
    return MappingProxyType(dict(poll_intervals))


def _merge(existing: _Pending | None, incoming: _Pending) -> _Pending:
    """Combines two pending refreshes: earliest `not_before`, latest follow deadline."""
    if existing is None:
        return incoming
    not_before = min(existing.not_before, incoming.not_before)
    if incoming.follow_deadline is None:
        return _Pending(not_before, existing.after, existing.follow_deadline)
    if existing.follow_deadline is None or incoming.follow_deadline >= existing.follow_deadline:
        return _Pending(not_before, incoming.after, incoming.follow_deadline)
    return _Pending(not_before, existing.after, existing.follow_deadline)


def _agree(before: tuple[Value, Quality], after: tuple[Value, Quality], deadband: float | None) -> bool:
    """Whether two reads in a row agree: the same quality, and values no further apart than the
    deadband, or equal."""
    if before[1] is not after[1]:
        return False
    old, new = before[0], after[0]
    if deadband is not None and isinstance(old, (int, float)) and isinstance(new, (int, float)) \
            and not isinstance(old, bool) and not isinstance(new, bool):
        return abs(new - old) <= deadband
    return old == new
