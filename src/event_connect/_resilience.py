"""How a protocol rides out a device that is busy, slow or silent, assembled from standard parts:
how long to wait between tries, when to stop trying, and when to stop asking altogether.

Every part decides and nothing more: it sends nothing and sleeps for nothing, so a protocol keeps
its own I/O, and a decision can be tested without a device.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast, runtime_checkable

# =================================================================================== waits


@runtime_checkable
class Wait(Protocol):
    """How long to wait before a try, by how many tries came before it."""

    def delay(self, attempt: int) -> float:
        """Seconds to wait before try number `attempt + 1`; `attempt` counts from 1."""
        ...


def _seconds(name: str, value: float) -> None:
    if not (math.isfinite(value) and value >= 0):
        raise ValueError(f"{name} must be a finite number >= 0, got {value}")


@dataclass(frozen=True)
class Fixed:
    """The same wait every time."""
    seconds: float

    def __post_init__(self) -> None:
        _seconds("seconds", self.seconds)

    def delay(self, attempt: int) -> float:
        """`seconds`, whatever the attempt."""
        return self.seconds


@dataclass(frozen=True)
class Exponential:
    """A wait that grows by `factor` at each try, from `start`, to at most `max`."""
    start: float
    factor: float = 2.0
    max: float | None = None

    def __post_init__(self) -> None:
        _seconds("start", self.start)
        if not (math.isfinite(self.factor) and self.factor >= 1):
            raise ValueError(f"factor must be a finite number >= 1, got {self.factor}")
        if self.max is not None:
            _seconds("max", self.max)

    def delay(self, attempt: int) -> float:
        """`start` times `factor` to the power of the tries before this one, capped at `max`."""
        seconds = self.start * self.factor ** max(0, attempt - 1)
        return seconds if self.max is None else min(seconds, self.max)


@dataclass(frozen=True, init=False)
class Steps:
    """The given waits in turn, then `then`'s, or the last given one again."""
    seconds: tuple[float, ...]
    then: Wait | None

    def __init__(self, *seconds: float, then: Wait | None = None) -> None:
        if not seconds:
            raise ValueError("Steps needs at least one wait")
        for value in seconds:
            _seconds("a step", value)
        object.__setattr__(self, "seconds", tuple(seconds))
        object.__setattr__(self, "then", then)

    def delay(self, attempt: int) -> float:
        """The `attempt`th step; after the last, `then`'s wait counted on from 1, or the last step."""
        index = max(0, attempt - 1)
        if index < len(self.seconds):
            return self.seconds[index]
        if self.then is None:
            return self.seconds[-1]
        return self.then.delay(index - len(self.seconds) + 1)


@dataclass(frozen=True)
class Jitter:
    """Another wait, spread at random by up to `spread` of it either way, so that devices that
    failed together do not try again together."""
    wait: Wait
    spread: float = 0.1
    rand: Callable[[], float] = field(default=random.random, compare=False)
    """A number from 0 to 1; replaceable, so that a test can fix it."""

    def __post_init__(self) -> None:
        if not 0 <= self.spread <= 1:
            raise ValueError(f"spread must be from 0 to 1, got {self.spread}")

    def delay(self, attempt: int) -> float:
        """The wait's delay, times a factor from 1 - `spread` to 1 + `spread`."""
        return self.wait.delay(attempt) * (1 + self.spread * (2 * self.rand() - 1))


# =================================================================================== stops


@runtime_checkable
class Stop(Protocol):
    """When to give up trying."""

    def stops(self, attempts: int, elapsed: float) -> bool:
        """Whether to give up after `attempts` tries, `elapsed` seconds after the first."""
        ...


class _Combinable:
    def __or__(self, other: Stop) -> AnyOf:
        """Give up as soon as either would."""
        return AnyOf((cast(Stop, self), other))


@dataclass(frozen=True)
class Attempts(_Combinable):
    """Give up after this many tries in all, the first among them."""
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"count must be at least 1, got {self.count}")

    def stops(self, attempts: int, elapsed: float) -> bool:
        """Whether `count` tries have been made."""
        return attempts >= self.count


@dataclass(frozen=True)
class Within(_Combinable):
    """Give up once this many seconds have passed since the first try."""
    seconds: float

    def __post_init__(self) -> None:
        _seconds("seconds", self.seconds)

    def stops(self, attempts: int, elapsed: float) -> bool:
        """Whether `seconds` have passed."""
        return elapsed >= self.seconds


@dataclass(frozen=True)
class AnyOf(_Combinable):
    """Give up as soon as any of these would: `Attempts(5) | Within(10)`."""
    parts: tuple[Stop, ...]

    def stops(self, attempts: int, elapsed: float) -> bool:
        """Whether any of them gives up."""
        return any(part.stops(attempts, elapsed) for part in self.parts)


# =================================================================================== retry


@dataclass(frozen=True)
class Retry:
    """Try again after `wait`, until `stop` gives up."""
    wait: Wait
    stop: Stop

    def next_delay(self, attempts: int, elapsed: float) -> float | None:
        """Seconds until the next try after `attempts` tries, `elapsed` seconds after the first;
        None when it is time to give up."""
        if self.stop.stops(attempts, elapsed):
            return None
        return self.wait.delay(attempts)


NO_RETRY = Retry(Fixed(0), Attempts(1))
"""One try, and none again."""


# ========================================================================= circuit breaker


@dataclass(frozen=True)
class CircuitBreaker:
    """Stop asking a device that has left `after` requests in a row unanswered, for a `pause`
    that grows by `pause`'s own rule each time it opens again; then let one request through as a
    probe, which closes it if answered and opens it again if not.

    The settings only: each device keeps its own `Breaker` of them.
    """
    after: int = 3
    pause: Wait = field(default_factory=lambda: Fixed(60.0))

    def __post_init__(self) -> None:
        if self.after < 1:
            raise ValueError(f"after must be at least 1, got {self.after}")

    def breaker(self) -> Breaker:
        """A breaker of these settings, closed."""
        return Breaker(self)


class Breaker:
    """The state of one device's circuit breaker: closed, open until a time, or letting a probe
    through. It is told every request's outcome, and asked before each whether to send it."""

    def __init__(self, settings: CircuitBreaker) -> None:
        self._settings = settings
        self._unanswered = 0
        self._openings = 0
        self._open_until: float | None = None
        self._probing = False
        self.opened = 0
        """How many times it has opened."""

    @property
    def is_open(self) -> bool:
        """Whether requests are refused, or wait for a probe, rather than sent."""
        return self._open_until is not None

    def open_for(self, now: float) -> float:
        """Seconds until a probe may go; 0 while closed or once one may."""
        return 0.0 if self._open_until is None else max(0.0, self._open_until - now)

    def allows(self, now: float) -> bool:
        """Whether a request may be sent now: always while closed; once the pause is over, one
        probe, and nothing more until its outcome is told."""
        if self._open_until is None:
            return True
        if self._probing or now < self._open_until:
            return False
        self._probing = True
        return True

    def answered(self) -> None:
        """Note an answer: the breaker closes."""
        self._unanswered = 0
        self._openings = 0
        self._open_until = None
        self._probing = False

    def unanswered(self, now: float) -> None:
        """Note a request left unanswered: the breaker opens after `after` in a row, or at once
        after a probe."""
        self._unanswered += 1
        if self._probing or self._unanswered >= self._settings.after:
            self._probing = False
            self._openings += 1
            self.opened += 1
            self._open_until = now + self._settings.pause.delay(self._openings)
