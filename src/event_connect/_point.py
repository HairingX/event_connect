"""What a device has: its points, declared by how they behave - not where they live or how they
are encoded, which each protocol adds."""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field, replace
from datetime import date, datetime, time
from enum import Enum, IntEnum, auto
from types import MappingProxyType
from typing import Any

from ._key import Key, is_key, is_state_type
from ._unit import Unit

# ================================================================================== enums


class PollRate(Enum):
    """How fresh a point must be kept."""
    FAST = auto()
    MEDIUM = auto()
    SLOW = auto()
    RARE = auto()
    STATIC = auto()
    """Read when connecting, when triggered or on request - never on a timer."""
    SCAN = auto()
    """How often what identifies the unit is read again, to find out whether it has changed.

    No point is polled at it.
    """


DEFAULT_INTERVALS: Mapping[PollRate, float | None] = MappingProxyType({
    PollRate.FAST: 10.0,
    PollRate.MEDIUM: 30.0,
    PollRate.SLOW: 60.0,
    PollRate.RARE: 900.0,
    PollRate.STATIC: None,
    PollRate.SCAN: 900.0,
})
"""Seconds between reads per poll rate, used when a model does not set its own."""


class WriteKind(Enum):
    """What a write means."""
    STATE = auto()
    """A setting. Writes that queue up collapse to the newest value."""
    COMMAND = auto()
    """An action. Every write is sent, in order, however many there are."""


class Change(Enum):
    """Which change of a trigger point sets off its refresh."""
    ANY = auto()
    RISING = auto()
    """The value increased - for a boolean, went from False to True."""
    FALLING = auto()


# ============================================================================== selectors


class Labels:
    """Selects every point carrying all of these labels: `Labels(room=3)`."""
    __slots__ = ("pairs",)

    def __init__(self, **labels: str | int) -> None:
        if not labels:
            raise ValueError("Labels() needs at least one label to select by")
        self.pairs: tuple[tuple[str, str | int], ...] = tuple(sorted(labels.items()))

    def matches(self, labels: Mapping[str, str | int]) -> bool:
        """Whether `labels` carry every pair of these."""
        return all(labels.get(name) == value for name, value in self.pairs)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Labels) and other.pairs == self.pairs

    def __hash__(self) -> int:
        return hash(self.pairs)

    def __repr__(self) -> str:
        return "Labels(" + ", ".join(f"{name}={value!r}" for name, value in self.pairs) + ")"


Selector = Labels | tuple[str, ...]
"""Which points: those with these labels, or these keys."""


def selector(targets: Labels | Sequence[str]) -> Selector:
    """`targets` as a selector: labels as they are, keys as a tuple.

    Raises:
        TypeError: a single string, which would select its characters.
        ValueError: no keys.
    """
    if isinstance(targets, Labels):
        return targets
    if isinstance(targets, str):
        # A bare string is a sequence of characters - almost certainly a mistake.
        raise TypeError(f"give keys as a list or tuple, not the single string {targets!r}")
    keys = tuple(targets)
    if not keys:
        raise ValueError("an empty list of keys selects nothing")
    return keys


def select[P: Point[Any]](points: Sequence[P], targets: Selector) -> tuple[P, ...]:
    """The points of `points` that `targets` names, in the order of `points`."""
    if isinstance(targets, Labels):
        return tuple(point for point in points if targets.matches(point.labels))
    wanted = set(targets)
    return tuple(point for point in points if point.key in wanted)


# ======================================================================= behaviour parts


@dataclass(frozen=True)
class Limits:
    """What may be written, in the units a user sees. Also the entity's min / max / step."""
    min: float | None = None
    max: float | None = None
    step: float | None = None

    def __post_init__(self) -> None:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min {self.min} is greater than max {self.max}")
        if self.step is not None and not self.step > 0:
            raise ValueError(f"step must be positive, got {self.step}")

    def problem(self, value: float) -> str | None:
        """Why `value` may not be written, or None if it may."""
        if self.min is not None and value < self.min:
            return f"{value} is below the minimum {self.min}"
        if self.max is not None and value > self.max:
            return f"{value} is above the maximum {self.max}"
        return None


@dataclass(frozen=True)
class Transform:
    """A conversion applied after scaling on read, and before it on write. Always a pair."""
    read: Callable[[float], float]
    write: Callable[[float], float]
    name: str = ""


class Transforms:
    """Transforms most devices need."""
    INVERT_BOOL = Transform(read=lambda v: 1 - v, write=lambda v: 1 - v, name="invert_bool")
    """The device says 0 for on. Also for a BOOL or a bit."""
    SECONDS_AS_MINUTES = Transform(read=lambda s: s / 60, write=lambda m: m * 60, name="seconds_as_minutes")
    MINUTES_AS_HOURS = Transform(read=lambda m: m / 60, write=lambda h: h * 60, name="minutes_as_hours")
    HOURS_AS_DAYS = Transform(read=lambda h: h / 24, write=lambda d: d * 24, name="hours_as_days")


@dataclass(frozen=True)
class Pulse[T]:
    """A command that returns to its idle value by itself: write, wait `after`, write `idle`."""
    idle: T
    after: float

    def __post_init__(self) -> None:
        if not self.after > 0:
            raise ValueError(f"a pulse needs a positive duration, got {self.after}")


@dataclass(frozen=True)
class Refresh:
    """Read `targets` again `after` seconds after this point is written, or changes.

    With `until_stable`, keep re-reading them every `after` seconds while they still change,
    for at most that many seconds.
    """
    targets: Selector
    after: float | None = None
    """Seconds to wait. None waits, after a write, as long as the written point takes to read
    back, and after a change not at all."""
    until_stable: float | None = None
    when: Change = Change.ANY
    """Which change sets it off; only a change has one."""

    def __init__(self, targets: Labels | Sequence[str], after: float | None = None,
                 until_stable: float | None = None, *, when: Change = Change.ANY) -> None:
        object.__setattr__(self, "targets", selector(targets))
        object.__setattr__(self, "after", after)
        object.__setattr__(self, "until_stable", until_stable)
        object.__setattr__(self, "when", when)
        if after is not None and after < 0:
            raise ValueError(f"after cannot be negative, got {after}")
        if until_stable is not None and not until_stable > 0:
            raise ValueError(f"until_stable must be positive, got {until_stable}")
        if until_stable is not None and after is not None and not after > 0:
            raise ValueError("until_stable needs a positive after to re-read at")


# ================================================================================== point


VALUE_TYPES: tuple[type[object], ...] = (bool, int, float, str, date, datetime, time)
"""The types a point's value can have, besides an `IntEnum` naming states."""


@dataclass(frozen=True, eq=False)
class Point[T]:
    """One value a device has, by how it behaves: when it is read, what may be written, and what a
    write or a change of it sets off.

    A protocol subclasses it with where the value lives and how it is encoded, and says whether it
    can be read and written. `key` must never change once a consumer has stored it.
    """
    key: Key[T]
    _: KW_ONLY
    limits: Limits | None = None
    unit: Unit | None = None
    poll_rate: PollRate = PollRate.MEDIUM
    poll_always: bool = False
    """Read even when no consumer asked for it - a value the device model itself depends on."""
    deadband: float | None = None
    """Changes smaller than this, from the last value reported, are not reported."""
    write_kind: WriteKind = WriteKind.STATE
    pulse: Pulse[T] | None = None
    read_back_after: float | None = None
    """Seconds from a write until a read shows it, where this point differs from its device."""
    on_write: Refresh | None = None
    on_change: Refresh | None = None
    labels: Mapping[str, str | int] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))
        if self.on_change is not None and self.on_change.after is None:
            object.__setattr__(self, "on_change", replace(self.on_change, after=0.0))
        problems = self.problems()
        if problems:
            raise ValueError(f"point {self.key!r}: " + "; ".join(problems))

    @property
    def readable(self) -> bool:
        """Whether the point can be read; its protocol says."""
        raise NotImplementedError

    @property
    def writable(self) -> bool:
        """Whether the point can be written; its protocol says."""
        raise NotImplementedError

    @property
    def states(self) -> tuple[IntEnum, ...]:
        """The states this point can hold, in the order its IntEnum declares them; none for a key
        that names no states."""
        value_type: type[object] = self.key.type
        if not is_state_type(value_type):
            return ()
        return tuple(value_type)

    def problems(self) -> list[str]:
        """Everything wrong with the point, so one error names every mistake at once.

        A protocol adds its own to these.
        """
        return [*_shape_problems(self), *_type_problems(self), *_read_problems(self),
                *_write_problems(self)]


def _shape_problems(point: Point[Any]) -> list[str]:
    found: list[str] = []
    if not point.key or point.key != point.key.strip():
        found.append("the key must be a non-empty string without surrounding spaces")
    if not point.readable and not point.writable:
        found.append("it needs a read side, a write side, or both")
    if any(not name for name in point.labels):
        found.append("a label needs a name")
    return found


def _is_number(value_type: type[object]) -> bool:
    return value_type in (int, float)


def _type_problems(point: Point[Any]) -> list[str]:
    if not is_key(point.key):
        return [f"the key must be a Key naming the value's type, such as Key({str(point.key)!r}, float)"]
    value_type: type[object] = point.key.type
    found: list[str] = []
    if not is_state_type(value_type) and value_type not in VALUE_TYPES:
        found.append(f"a value is a bool, int, float, str, date, datetime, time or IntEnum, "
                     f"not {value_type.__name__}")
    if not _is_number(value_type):
        if point.deadband is not None:
            found.append(f"a deadband applies to numbers, not to {value_type.__name__}")
        if point.limits is not None:
            found.append(f"limits apply to numbers, not to {value_type.__name__}")
    return found


def _read_problems(point: Point[Any]) -> list[str]:
    found: list[str] = []
    if point.poll_rate is PollRate.SCAN:
        found.append("PollRate.SCAN is how often a scan is checked, not a poll rate a point can have")
    if point.deadband is not None:
        if point.deadband < 0:
            found.append(f"deadband cannot be negative, got {point.deadband}")
        if not point.readable:
            found.append("a deadband filters reads, but it has no read side")
    if point.poll_always and not point.readable:
        found.append("poll_always=True asks for reads, but it has no read side")
    if point.on_change is not None:
        if not point.readable:
            found.append("on_change reacts to reads, but it has no read side")
        if point.on_change.until_stable is not None and not point.on_change.after:
            found.append("on_change re-reads until stable, which needs a positive after to re-read at")
    return found


def _write_problems(point: Point[Any]) -> list[str]:
    found: list[str] = []
    if point.read_back_after is not None:
        if not point.writable:
            found.append("read_back_after describes writes, but it has no write side")
        if not (math.isfinite(point.read_back_after) and point.read_back_after >= 0):
            found.append(f"read_back_after must be a finite number >= 0, got {point.read_back_after}")
    if point.limits is not None and not point.writable:
        found.append("limits describe writes, but it has no write side")
    if point.write_kind is WriteKind.COMMAND and not point.writable:
        found.append("a COMMAND is written, but it has no write side")
    if point.pulse is not None and point.write_kind is not WriteKind.COMMAND:
        found.append("only a COMMAND can pulse")
    if point.pulse is not None and not is_instance(point.pulse.idle, point.key.type):
        found.append(f"the pulse's idle value {point.pulse.idle!r} is not a {point.key.type.__name__}")
    if point.on_write is not None:
        if not point.writable:
            found.append("on_write re-reads after a write, but it has no write side")
        if point.on_write.when is not Change.ANY:
            found.append("on_write has no change to wait for; `when` belongs to on_change")
        after = point.on_write.after if point.on_write.after is not None else point.read_back_after
        if point.on_write.until_stable is not None and after is not None and not after > 0:
            found.append("on_write re-reads until stable, which needs a positive after to re-read at")
    return found


def is_instance(value: object, value_type: type[object]) -> bool:
    """Whether `value` is of `value_type`, where an int counts as a float and a bool as neither."""
    if isinstance(value, bool) and value_type is not bool:
        return False
    if value_type is float:
        return isinstance(value, (int, float))
    return isinstance(value, value_type)

