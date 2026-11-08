"""How a protocol rides out a device that is busy, slow or silent, assembled from standard parts:
how long to wait between tries, when to stop trying, and when to stop asking altogether.

Every part decides and nothing more: it sends nothing and sleeps for nothing, so a protocol keeps
its own I/O, and a decision can be tested without a device.
"""
from __future__ import annotations

import math
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast, runtime_checkable

# =================================================================================== waits


@runtime_checkable
class Wait(Protocol):
    """How long to wait before a try, by how many tries came before it."""

    def delay(self, attempt: int) -> float:
        """Seconds to wait before try number `attempt + 1`; `attempt` counts from 1.

        A number for every attempt, however many came before it: never raises.
        """
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
        """`start` times `factor` to the power of the tries before this one, capped at `max`;
        without `max`, at the largest float."""
        cap = sys.float_info.max if self.max is None else self.max
        if self.start == 0 or cap == 0:
            return 0.0
        exponent = max(0, attempt - 1)
        # Compared as logarithms: the power itself overflows a float long before a try count
        # stops growing.
        if exponent * math.log(self.factor) >= math.log(cap / self.start):
            return cap
        try:
            seconds = self.start * self.factor ** exponent
        except OverflowError:  # the power alone, where `start` would have brought it under `cap`
            return cap
        return min(seconds, cap)


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
    """Try again after `wait`, until `stop` gives up; without a `stop`, never give up.

    A subclass may decide differently, in `next_delay`, or check something before each try, in
    `ready`.
    """
    wait: Wait
    stop: Stop | None = None

    def next_delay(self, attempts: int, elapsed: float) -> float | None:
        """Seconds until the next try after `attempts` tries, `elapsed` seconds after the first;
        None when it is time to give up."""
        if self.stop is not None and self.stop.stops(attempts, elapsed):
            return None
        return self.wait.delay(attempts)

    async def ready(self) -> bool:
        """Whether a try that is due may be made now; a try it refuses waits for the next delay.

        Always True here.
        """
        return True


NO_RETRY = Retry(Fixed(0), Attempts(1))
"""One try, and none again."""


# ========================================================================= circuit breaker


@dataclass(frozen=True)
class CircuitBreaker:
    """Stop asking a device that has left `after` requests in a row unanswered, for a `pause`
    that grows by `pause`'s own rule each time it opens again; then let one request through as a
    probe, which closes it if answered and opens it again if not.

    With a `retry`, each pause is its next delay instead, counted in openings and timed from the
    first since the last answer; when it gives up, the breaker stays open until it is reset.

    The settings only: each device keeps its own `Breaker` of them.
    """
    after: int = 3
    pause: Wait = field(default_factory=lambda: Fixed(60.0))
    retry: Retry | None = None

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
        self._first_opened_at: float | None = None
        self._pause = 0.0
        self._open_until: float | None = None
        self._probing = False
        self.opened = 0
        """How many times it has opened."""

    @property
    def unanswered_in_a_row(self) -> int:
        """Requests left unanswered since the last answer."""
        return self._unanswered

    @property
    def is_open(self) -> bool:
        """Whether requests are refused, or wait for a probe, rather than sent."""
        return self._open_until is not None

    @property
    def gave_up(self) -> bool:
        """Whether its `retry` gave up: no probe goes until it is reset."""
        return self._open_until == math.inf

    @property
    def openings(self) -> int:
        """How many times it has opened since the last answer or reset."""
        return self._openings

    def open_for(self, now: float) -> float:
        """Seconds until a probe may go; 0 while closed or once one may."""
        return 0.0 if self._open_until is None else max(0.0, self._open_until - now)

    def attempt(self, now: float) -> Attempt | None:
        """One request, if it may be sent now; None if not. Used as a context manager, it
        releases a probe whose outcome it was never told, as when the request was cancelled."""
        probe = self.is_open
        return Attempt(self, probe) if self.allows(now) else None

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
        self.reset()

    def reset(self) -> None:
        """Close the breaker without an answer, as when the device is connected afresh."""
        self._unanswered = 0
        self._openings = 0
        self._first_opened_at = None
        self._open_until = None
        self._probing = False

    def postpone(self, now: float) -> None:
        """Let no probe through for another pause as long as the last, without counting an
        opening, as when a retry is not ready."""
        if self._open_until is None:
            return
        self._probing = False
        self._open_until = now + self._pause

    def released(self) -> None:
        """Note that a request let through was not sent after all, or its outcome is unknown, as
        when it was cancelled: a probe may go again, and nothing else changes."""
        self._probing = False

    def unanswered(self, now: float) -> None:
        """Note a request left unanswered: the breaker opens after `after` in a row, or at once
        after a probe."""
        self._unanswered += 1
        if self._probing or self._unanswered >= self._settings.after:
            self._probing = False
            self._openings += 1
            self.opened += 1
            if self._first_opened_at is None:
                self._first_opened_at = now
            self._pause = self._next_pause(now)
            self._open_until = now + self._pause

    def _next_pause(self, now: float) -> float:
        retry = self._settings.retry
        if retry is None:
            return self._settings.pause.delay(self._openings)
        assert self._first_opened_at is not None
        delay = retry.next_delay(self._openings, now - self._first_opened_at)
        return math.inf if delay is None else delay


class Attempt:
    """One request a `Breaker` let through, to be told its outcome."""

    def __init__(self, breaker: Breaker, probe: bool) -> None:
        self._breaker = breaker
        self._probe = probe
        self._told = False

    def answered(self) -> None:
        """The request was answered."""
        self._told = True
        self._breaker.answered()

    def unanswered(self, now: float) -> None:
        """The request was left unanswered."""
        self._told = True
        self._breaker.unanswered(now)

    def __enter__(self) -> Attempt:
        return self

    def __exit__(self, *exc: object) -> None:
        if self._probe and not self._told:
            self._breaker.released()
