"""Which keys are due for a read, and when: no I/O, no timer, no sleep."""
from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ._clock import Clock
from ._point import DEFAULT_INTERVALS, Point, PollRate
from ._value import DataValue, Quality, Value

_LOGGER = logging.getLogger(__name__)


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
    """The schedule of one device: poll intervals, overrides, pending refreshes, following.

    Each key keeps its own rhythm: a read a refresh or a retry asked for does not move the next
    regular one. A polled key whose read failed is read again `retry_after` seconds later, then
    after twice as long at each further failure, but never later than its next regular read.
    """

    def __init__(self, clock: Clock, poll_intervals: Mapping[PollRate, float | None] = DEFAULT_INTERVALS,
                 *, min_poll_interval: float = 0.0, retry_after: float = 0.0) -> None:
        """Args:
            retry_after: seconds before a failed read is tried again; 0 waits for the next
                regular read.
        """
        if min_poll_interval < 0:
            raise ValueError(f"min_poll_interval cannot be negative, got {min_poll_interval}")
        if not (math.isfinite(retry_after) and retry_after >= 0):
            raise ValueError(f"retry_after must be a finite number >= 0, got {retry_after}")
        model_intervals: dict[PollRate, float | None] = {}
        for poll_rate in PollRate:
            default = poll_intervals.get(poll_rate, DEFAULT_INTERVALS[poll_rate])
            if default is not None:
                if not default > 0:
                    raise ValueError(f"the model's default for {poll_rate.name} must be positive or "
                                      f"None, got {default}")
                if default < min_poll_interval:
                    raise ValueError(f"the model's default for {poll_rate.name} ({default}s) is "
                                      f"below the floor min_poll_interval={min_poll_interval}s - a model bug")
            model_intervals[poll_rate] = default

        self._clock = clock
        self._min_poll_interval = min_poll_interval
        self._retry_after = retry_after
        self._model_intervals = model_intervals
        self._rate_overrides: dict[PollRate, float] = {}
        self._key_overrides: dict[str, float] = {}
        self._warned: set[PollRate | str] = set()

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

        State for a key that persists is kept; a new key starts unpolled."""
        new_points: dict[str, Point[Any]] = {point.key: point for point in points if point.readable}
        for key in list(self._points):
            if key not in new_points:
                self._polled.pop(key, None)
                self._last_regular.pop(key, None)
                self._key_overrides.pop(key, None)
                self._pending.pop(key, None)
                self._following.pop(key, None)
                self._retry_at.pop(key, None)
                self._failures.pop(key, None)
                self._warned.discard(key)
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

    def set_poll_interval(self, target: PollRate | str, seconds: float | None) -> float | None:
        """Overrides the interval of a poll rate or a single key; returns the value actually stored,
        clamped to the device floor. `None` removes the override."""
        if isinstance(target, str):
            self._require(target)
        if seconds is not None:
            if not seconds > 0:
                raise ValueError(f"an interval must be positive or None, got {seconds}")
            if seconds < self._min_poll_interval:
                if target not in self._warned:
                    _LOGGER.warning("interval %.3gs for %r is below the floor %.3gs; clamped",
                                     seconds, target, self._min_poll_interval)
                    self._warned.add(target)
                seconds = self._min_poll_interval

        if isinstance(target, PollRate):
            if seconds is None:
                self._rate_overrides.pop(target, None)
            else:
                self._rate_overrides[target] = seconds
        else:
            if seconds is None:
                self._key_overrides.pop(target, None)
            else:
                self._key_overrides[target] = seconds
        return seconds

    def interval(self, key: str) -> float | None:
        """The effective interval: key override, else poll rate override, else model default."""
        self._require(key)
        if key in self._key_overrides:
            return self._key_overrides[key]
        return self.rate_interval(self._points[key].poll_rate)

    def rate_interval(self, poll_rate: PollRate) -> float | None:
        """The effective interval of a poll rate: its override, else the model default."""
        if poll_rate in self._rate_overrides:
            return self._rate_overrides[poll_rate]
        return self._model_intervals[poll_rate]

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

    def record(self, key: str, value: DataValue[Any] | None, *, success: bool) -> None:
        """Reports the outcome of a read attempt for `key`; may consume a pending refresh and
        advance following."""
        self._require(key)
        now = self._clock.monotonic()
        if self._regular_due(key) <= now:
            self._last_regular[key] = now
        self._record_outcome(key, success, now)

        pending = self._pending.get(key)
        if pending is None or pending.not_before > now:
            return
        del self._pending[key]
        if pending.follow_deadline is not None and key not in self._following:
            self._following[key] = _Following(pending.follow_deadline, pending.after)
        if key in self._following:
            self._advance_following(key, value, success, now)

    def consecutive_failures(self, key: str) -> int:
        """How many reads of `key` in a row have failed."""
        self._require(key)
        return self._failures.get(key, 0)

    def _record_outcome(self, key: str, success: bool, now: float) -> None:
        if success:
            self._failures.pop(key, None)
            self._retry_at.pop(key, None)
            return
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        if not self._retry_after or not self._polled.get(key, False):
            return
        wait = self._retry_after * 2 ** (failures - 1)
        interval = self.interval(key)
        if interval is not None:
            wait = min(wait, interval)
        self._retry_at[key] = now + wait

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
        """Keys to read now, in priority order: pending refreshes and retries, never-read, most
        overdue."""
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
        return ready + never + overdue

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
