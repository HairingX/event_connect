"""The standard parts a protocol assembles its riding out of a busy, slow or silent device from."""
from __future__ import annotations

import asyncio
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from event_connect import (
    NO_RETRY,
    Attempts,
    Breaker,
    CircuitBreaker,
    Exponential,
    Fixed,
    Jitter,
    Retry,
    Steps,
    Stop,
    Wait,
    Within,
)



def _unanswered(breaker: Breaker, now: float) -> None:
    """Send one request through `breaker`, which is let through, and leave it unanswered."""
    attempt = breaker.attempt(now)
    assert attempt is not None, f"no request was let through at {now}"
    with attempt:
        attempt.unanswered(now)


def _answered(breaker: Breaker, now: float) -> None:
    """Send one request through `breaker`, which is let through, and answer it."""
    attempt = breaker.attempt(now)
    assert attempt is not None, f"no request was let through at {now}"
    with attempt:
        attempt.answered()


def _allows(breaker: Breaker, now: float) -> bool:
    """Whether `breaker` lets a request through at `now`, holding it untold as a probe would be."""
    return breaker.attempt(now) is not None


# =================================================================================== waits


def test_a_fixed_wait_is_the_same_every_time() -> None:
    assert [Fixed(2).delay(n) for n in (1, 2, 5)] == [2, 2, 2]


def test_an_exponential_wait_grows_by_its_factor_up_to_its_max() -> None:
    assert [Exponential(0.5, factor=2, max=3).delay(n) for n in (1, 2, 3, 4, 5)] == [0.5, 1, 2, 3, 3]


@pytest.mark.parametrize("wait", [
    Exponential(2.0, max=10.0),
    Exponential(2, factor=2, max=10),
    Exponential(0.5, factor=3.0, max=0.5),
    Steps(1, then=Exponential(2.0, max=10.0)),
    Jitter(Exponential(2.0, max=10.0), rand=lambda: 1.0),
])
def test_a_wait_with_a_max_stays_at_it_however_many_tries_came_before(wait: Wait) -> None:
    capped = wait.delay(50)
    assert [wait.delay(n) for n in (1024, 1025, 2000, 10 ** 6)] == [capped] * 4


def test_an_exponential_wait_without_a_max_grows_to_the_largest_float_and_no_further() -> None:
    wait = Exponential(0.2)
    assert wait.delay(1025) == wait.delay(10 ** 6) == sys.float_info.max


def test_an_exponential_wait_from_nothing_or_to_nothing_is_zero() -> None:
    assert Exponential(0, max=10).delay(10 ** 6) == 0
    assert Exponential(2, max=0).delay(10 ** 6) == 0


def test_a_breaker_asks_again_at_its_max_after_hours_of_silence() -> None:
    breaker = CircuitBreaker(after=3, retry=Retry(Exponential(2.0, max=10.0))).breaker()
    now = 0.0
    for _ in range(3):
        _unanswered(breaker, now)
    for _ in range(2000):
        now += breaker.open_for(now)
        _unanswered(breaker, now)
    assert breaker.openings == 2001 and breaker.open_for(now) == 10.0


def test_steps_are_taken_in_turn_then_the_last_again() -> None:
    assert [Steps(0.5, 1, 2).delay(n) for n in (1, 2, 3, 4)] == [0.5, 1, 2, 2]


def test_steps_go_on_with_another_wait_counted_from_its_start() -> None:
    wait = Steps(0.5, then=Exponential(1, factor=2))
    assert [wait.delay(n) for n in (1, 2, 3, 4)] == [0.5, 1, 2, 4]


def test_jitter_spreads_a_wait_either_way_by_up_to_its_spread() -> None:
    assert Jitter(Fixed(10), spread=0.2, rand=lambda: 0.0).delay(1) == pytest.approx(8)  # pyright: ignore[reportUnknownMemberType]
    assert Jitter(Fixed(10), spread=0.2, rand=lambda: 1.0).delay(1) == pytest.approx(12)  # pyright: ignore[reportUnknownMemberType]


def test_every_wait_is_a_wait() -> None:
    waits: list[Wait] = [Fixed(1), Exponential(1), Steps(1), Jitter(Fixed(1))]
    assert all(isinstance(wait, Wait) for wait in waits)


@pytest.mark.parametrize("build", [
    lambda: Fixed(-1),
    lambda: Fixed(float("inf")),
    lambda: Exponential(1, factor=0.5),
    lambda: Exponential(1, max=float("nan")),
    lambda: Steps(),
    lambda: Steps(-1),
    lambda: Jitter(Fixed(1), spread=2),
    lambda: Attempts(0),
    lambda: Within(-1),
    lambda: CircuitBreaker(after=0, retry=NO_RETRY),
])
def test_a_part_that_cannot_be_meant_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


# =================================================================================== stops


def test_attempts_stop_after_that_many_tries() -> None:
    assert [Attempts(3).stops(n, 0) for n in (1, 2, 3)] == [False, False, True]


def test_within_stops_once_its_time_has_passed() -> None:
    assert [Within(7.5).stops(1, seconds) for seconds in (7.0, 7.5)] == [False, True]


def test_stops_combine_and_give_up_at_the_first() -> None:
    stop: Stop = Attempts(5) | Within(10)
    assert stop.stops(5, 1) and stop.stops(2, 10) and not stop.stops(2, 1)
    assert (Attempts(5) | Within(10) | Attempts(2)).stops(2, 0)


# =================================================================================== retry


def test_a_retry_waits_by_its_wait_until_its_stop_gives_up() -> None:
    retry = Retry(wait=Steps(0.5, then=Fixed(1)), stop=Within(3))
    assert [retry.next_delay(n, elapsed) for n, elapsed in ((1, 0), (2, 0.5), (3, 1.5), (4, 3.0))] == [0.5, 1, 1, None]


def test_no_retry_tries_once() -> None:
    assert NO_RETRY.next_delay(1, 0) is None


def test_a_retry_without_a_stop_never_gives_up() -> None:
    retry = Retry(Fixed(5))
    assert [retry.next_delay(n, 10.0 ** n) for n in (1, 10, 100)] == [5, 5, 5]


def test_a_retry_is_ready_unless_it_says_otherwise() -> None:
    @dataclass(frozen=True)
    class Offline(Retry):
        async def ready(self) -> bool:
            return False

    assert asyncio.run(Retry(Fixed(5)).ready())
    assert not asyncio.run(Offline(Fixed(5)).ready())


# ========================================================================= circuit breaker


@pytest.mark.parametrize("args,fields", [
    ((), {"after": 3}),
    ((), {"retry": NO_RETRY}),
    ((3, NO_RETRY), {}),
])
def test_a_breaker_is_given_every_setting_by_name(args: tuple[Any, ...], fields: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        CircuitBreaker(*args, **fields)


def test_a_breaker_has_one_count_of_openings_and_hides_its_bookkeeping() -> None:
    breaker = CircuitBreaker(after=1, retry=NO_RETRY).breaker()
    for name in ("opened", "allows", "answered", "unanswered", "released"):
        assert not hasattr(breaker, name), name


def test_a_breaker_lets_everything_through_while_the_device_answers() -> None:
    breaker = CircuitBreaker(after=3, retry=NO_RETRY).breaker()
    _unanswered(breaker, 0)
    _answered(breaker, 1)
    _unanswered(breaker, 1)
    _unanswered(breaker, 2)
    assert _allows(breaker, 2) and not breaker.is_open


def test_a_breaker_opens_after_that_many_unanswered_in_a_row() -> None:
    breaker = CircuitBreaker(after=3, retry=Retry(Fixed(60))).breaker()
    for now in (0, 1, 2):
        _unanswered(breaker, now)
    assert breaker.is_open and not _allows(breaker, 30) and breaker.open_for(30) == 32


def test_after_its_pause_a_breaker_lets_one_probe_through() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Fixed(10))).breaker()
    _unanswered(breaker, 0)
    assert _allows(breaker, 10)
    assert not _allows(breaker, 10), "a second request went through beside the probe"


def test_an_answered_probe_closes_the_breaker() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Fixed(10))).breaker()
    _unanswered(breaker, 0)
    _answered(breaker, 10)
    assert not breaker.is_open and _allows(breaker, 10) and _allows(breaker, 10)


def test_an_unanswered_probe_opens_the_breaker_again_for_a_growing_pause() -> None:
    breaker = CircuitBreaker(after=3, retry=Retry(Exponential(10, factor=2))).breaker()
    for now in (0, 1, 2):
        _unanswered(breaker, now)
    assert breaker.open_for(2) == 10
    _unanswered(breaker, 12)
    assert breaker.open_for(12) == 20 and breaker.openings == 2


def test_each_device_keeps_its_own_breaker() -> None:
    settings = CircuitBreaker(after=1, retry=NO_RETRY)
    first, second = settings.breaker(), settings.breaker()
    _unanswered(first, 0)
    assert first.is_open and not second.is_open


def test_a_breaker_counts_the_unanswered_since_the_last_answer() -> None:
    breaker = CircuitBreaker(after=5, retry=NO_RETRY).breaker()
    _unanswered(breaker, 0)
    _unanswered(breaker, 1)
    assert breaker.unanswered_in_a_row == 2
    _answered(breaker, 2)
    assert breaker.unanswered_in_a_row == 0


def test_an_attempt_tells_the_breaker_its_outcome() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Fixed(10))).breaker()
    attempt = breaker.attempt(0)
    assert attempt is not None
    with attempt:
        attempt.unanswered(0)
    assert breaker.is_open and breaker.attempt(5) is None


def test_a_probe_whose_outcome_is_never_told_is_released() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Fixed(10))).breaker()
    _unanswered(breaker, 0)
    with pytest.raises(KeyboardInterrupt):
        attempt = breaker.attempt(10)
        assert attempt is not None
        with attempt:
            raise KeyboardInterrupt
    assert breaker.is_open
    probe = breaker.attempt(10)
    assert probe is not None
    with probe:
        probe.answered()
    assert not breaker.is_open


def test_a_request_let_through_a_closed_breaker_releases_no_probe() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Fixed(10))).breaker()
    before = breaker.attempt(0)
    assert before is not None
    _unanswered(breaker, 0)
    assert _allows(breaker, 10)
    with before:
        pass
    assert not _allows(breaker, 10), "leaving a request sent while closed let a second probe through"


def test_each_pause_is_the_retry_s_next_delay_timed_from_the_first_opening() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Exponential(2), Within(5))).breaker()
    _unanswered(breaker, 100)
    assert breaker.open_for(100) == 2
    _unanswered(breaker, 102)
    assert breaker.open_for(102) == 4 and breaker.openings == 2
    _unanswered(breaker, 106)
    assert breaker.gave_up and breaker.open_for(106) == math.inf


def test_attempts_in_a_breaker_s_retry_count_openings_so_n_give_n_minus_one_probes() -> None:
    breaker = CircuitBreaker(after=3, retry=Retry(Exponential(2, max=10), Attempts(8))).breaker()
    now, sent, probes = 0.0, 0, 0
    while not breaker.gave_up:
        now += breaker.open_for(now)
        probes += breaker.is_open
        sent += 1
        _unanswered(breaker, now)
    assert (sent, probes, breaker.openings) == (10, 7, 8)


def test_a_breaker_whose_retry_gave_up_lets_nothing_through_until_reset() -> None:
    breaker = CircuitBreaker(after=1, retry=NO_RETRY).breaker()
    _unanswered(breaker, 0)
    assert breaker.gave_up and breaker.attempt(10 ** 9) is None
    breaker.reset()
    assert not breaker.is_open and not breaker.gave_up and _allows(breaker, 10 ** 9)


def test_a_reset_starts_the_retry_over() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Exponential(2))).breaker()
    _unanswered(breaker, 0)
    _unanswered(breaker, 2)
    breaker.reset()
    _unanswered(breaker, 50)
    assert breaker.open_for(50) == 2 and breaker.openings == 1


def test_a_postponed_probe_waits_the_same_pause_again_without_counting_an_opening() -> None:
    breaker = CircuitBreaker(after=1, retry=Retry(Exponential(2))).breaker()
    _unanswered(breaker, 0)
    _unanswered(breaker, 2)
    assert _allows(breaker, 6)
    breaker.postpone(6)
    assert not _allows(breaker, 9) and breaker.open_for(6) == 4 and breaker.openings == 2 and _allows(breaker, 10)


def test_postponing_a_closed_breaker_changes_nothing() -> None:
    breaker = CircuitBreaker(after=1, retry=NO_RETRY).breaker()
    breaker.postpone(0)
    assert not breaker.is_open and _allows(breaker, 0)
