"""Whether a device answers, as its consumers see it."""
from __future__ import annotations

import logging

import pytest

from event_connect import Key, PollRate, Reachability, Scheduler
from event_connect.testing import FakeClock, FakePoint


def test_a_device_does_not_answer_until_it_has_answered() -> None:
    assert not Reachability(FakeClock(), offline_after_intervals=3, fastest_interval=10.0).reachable


def test_one_lost_answer_is_not_an_outage() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0)
    reachability.answered()
    reachability.unanswered()
    assert reachability.reachable and reachability.silent
    clock.advance(29.0)
    reachability.unanswered()
    assert reachability.reachable


def test_silence_for_the_whole_period_is_an_outage() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0)
    reachability.answered()
    reachability.unanswered()
    clock.advance(30.0)
    reachability.unanswered()
    assert not reachability.reachable and reachability.silent_for == 30.0


def test_an_answer_ends_the_silence_at_once() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0)
    reachability.answered()
    reachability.unanswered()
    clock.advance(30.0)
    reachability.unanswered()
    reachability.answered()
    assert reachability.reachable and not reachability.silent and reachability.silent_for == 0.0


def test_the_silence_is_counted_from_the_first_unanswered_request_not_the_last_answer() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0)
    reachability.answered()
    clock.advance(900.0)
    reachability.unanswered()
    assert reachability.reachable


def test_with_nothing_read_on_a_timer_the_first_silence_is_an_outage() -> None:
    reachability = Reachability(FakeClock(), offline_after_intervals=1, fastest_interval=None)
    reachability.answered()
    reachability.unanswered()
    assert not reachability.reachable


def test_noting_an_outcome_returns_nothing_as_reachable_says_it() -> None:
    reachability = Reachability(FakeClock(), offline_after_intervals=3, fastest_interval=10.0)
    assert reachability.answered() is None and reachability.unanswered() is None


@pytest.mark.parametrize(("intervals", "fastest"), [(0, 10.0), (3, 0.0), (3, -1.0), (3, float("nan")),
                                                     (3, float("inf"))])
def test_a_grace_that_cannot_be_meant_is_refused(intervals: int, fastest: float) -> None:
    with pytest.raises(ValueError):
        Reachability(FakeClock(), offline_after_intervals=intervals, fastest_interval=fastest)


def test_a_device_read_every_ten_seconds_may_miss_three_reads_before_it_is_lost() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0)
    reachability.answered()
    reachability.unanswered()
    clock.advance(29.5)
    reachability.unanswered()
    assert reachability.reachable
    clock.advance(0.5)
    reachability.unanswered()
    assert not reachability.reachable


def test_one_missed_read_of_the_fastest_interval_can_be_all_a_device_is_allowed() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, offline_after_intervals=1, fastest_interval=10.0)
    reachability.answered()
    reachability.unanswered()
    clock.advance(9.0)
    reachability.unanswered()
    assert reachability.reachable
    clock.advance(1.0)
    reachability.unanswered()
    assert not reachability.reachable


def _scheduler(clock: FakeClock) -> Scheduler:
    scheduler = Scheduler(clock, poll_intervals={PollRate.FAST: 10.0, PollRate.RARE: 900.0})
    scheduler.set_points([FakePoint(Key("fast", int), poll_rate=PollRate.FAST),
                          FakePoint(Key("rare", int), poll_rate=PollRate.RARE)])
    for key in ("fast", "rare"):
        scheduler.set_polled(key, True)
        scheduler.record(key, None, success=True)
    return scheduler


def test_what_failed_while_the_device_was_silent_is_due_once_it_answers() -> None:
    clock = FakeClock()
    scheduler = _scheduler(clock)
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0)
    reachability.answered(scheduler)
    clock.advance(10)
    scheduler.record("fast", None, success=False)
    reachability.unanswered()
    clock.advance(10)
    reachability.answered(scheduler)
    assert scheduler.due() == ["fast"]


def test_after_an_outage_everything_is_due_once_the_device_answers() -> None:
    clock = FakeClock()
    scheduler = _scheduler(clock)
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0)
    reachability.answered(scheduler)
    reachability.unanswered()
    clock.advance(30)
    reachability.unanswered()
    reachability.answered(scheduler)
    assert sorted(scheduler.due()) == ["fast", "rare"]


def test_a_first_answer_is_no_recovery() -> None:
    clock = FakeClock()
    scheduler = _scheduler(clock)
    reachability = Reachability(clock, offline_after_intervals=1, fastest_interval=None)
    reachability.unanswered()
    reachability.answered(scheduler)
    assert scheduler.due() == []


def test_an_outage_and_its_end_are_logged_once_each(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    reachability = Reachability(clock, offline_after_intervals=3, fastest_interval=10.0, name="The unit")
    with caplog.at_level(logging.INFO, logger="event_connect"):
        reachability.unanswered()
        reachability.answered()
        for _ in range(4):
            reachability.unanswered()
            clock.advance(15)
            reachability.unanswered()
        reachability.answered()
    assert [r.getMessage() for r in caplog.records] == [
        "The unit stopped answering 30 s ago", "The unit answers again, after 60 s"]
