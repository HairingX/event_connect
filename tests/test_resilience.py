"""The standard parts a protocol assembles its riding out of a busy, slow or silent device from."""
from __future__ import annotations

from collections.abc import Callable

import pytest

from event_connect import (
    NO_RETRY,
    Attempts,
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

# =================================================================================== waits


def test_a_fixed_wait_is_the_same_every_time() -> None:
    assert [Fixed(2).delay(n) for n in (1, 2, 5)] == [2, 2, 2]


def test_an_exponential_wait_grows_by_its_factor_up_to_its_max() -> None:
    assert [Exponential(0.5, factor=2, max=3).delay(n) for n in (1, 2, 3, 4, 5)] == [0.5, 1, 2, 3, 3]


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
    lambda: CircuitBreaker(after=0),
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


# ========================================================================= circuit breaker


def test_a_breaker_lets_everything_through_while_the_device_answers() -> None:
    breaker = CircuitBreaker(after=3).breaker()
    breaker.unanswered(0)
    breaker.answered()
    breaker.unanswered(1)
    breaker.unanswered(2)
    assert breaker.allows(2) and not breaker.is_open


def test_a_breaker_opens_after_that_many_unanswered_in_a_row() -> None:
    breaker = CircuitBreaker(after=3, pause=Fixed(60)).breaker()
    for now in (0, 1, 2):
        breaker.unanswered(now)
    assert breaker.is_open and not breaker.allows(30) and breaker.open_for(30) == 32


def test_after_its_pause_a_breaker_lets_one_probe_through() -> None:
    breaker = CircuitBreaker(after=1, pause=Fixed(10)).breaker()
    breaker.unanswered(0)
    assert breaker.allows(10)
    assert not breaker.allows(10), "a second request went through beside the probe"


def test_an_answered_probe_closes_the_breaker() -> None:
    breaker = CircuitBreaker(after=1, pause=Fixed(10)).breaker()
    breaker.unanswered(0)
    breaker.allows(10)
    breaker.answered()
    assert not breaker.is_open and breaker.allows(10) and breaker.allows(10)


def test_an_unanswered_probe_opens_the_breaker_again_for_a_growing_pause() -> None:
    breaker = CircuitBreaker(after=3, pause=Exponential(10, factor=2)).breaker()
    for now in (0, 1, 2):
        breaker.unanswered(now)
    assert breaker.open_for(2) == 10
    breaker.allows(12)
    breaker.unanswered(12)
    assert breaker.open_for(12) == 20 and breaker.opened == 2


def test_each_device_keeps_its_own_breaker() -> None:
    settings = CircuitBreaker(after=1)
    first, second = settings.breaker(), settings.breaker()
    first.unanswered(0)
    assert first.is_open and not second.is_open


def test_a_released_probe_lets_another_through() -> None:
    breaker = CircuitBreaker(after=1, pause=Fixed(10)).breaker()
    breaker.unanswered(0)
    breaker.allows(10)
    breaker.released()
    assert breaker.allows(10) and breaker.is_open


def test_a_breaker_counts_the_unanswered_since_the_last_answer() -> None:
    breaker = CircuitBreaker(after=5).breaker()
    breaker.unanswered(0)
    breaker.unanswered(1)
    assert breaker.unanswered_in_a_row == 2
    breaker.answered()
    assert breaker.unanswered_in_a_row == 0


def test_an_attempt_tells_the_breaker_its_outcome() -> None:
    breaker = CircuitBreaker(after=1, pause=Fixed(10)).breaker()
    attempt = breaker.attempt(0)
    assert attempt is not None
    with attempt:
        attempt.unanswered(0)
    assert breaker.is_open and breaker.attempt(5) is None


def test_a_probe_whose_outcome_is_never_told_is_released() -> None:
    breaker = CircuitBreaker(after=1, pause=Fixed(10)).breaker()
    breaker.unanswered(0)
    with pytest.raises(KeyboardInterrupt):
        attempt = breaker.attempt(10)
        assert attempt is not None
        with attempt:
            raise KeyboardInterrupt
    probe = breaker.attempt(10)
    assert probe is not None
    with probe:
        probe.answered()
    assert not breaker.is_open
