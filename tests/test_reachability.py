"""Whether a device answers, as its consumers see it."""
from __future__ import annotations

import pytest

from event_connect import Reachability
from event_connect.testing import FakeClock


def test_a_device_does_not_answer_until_it_has_answered() -> None:
    assert not Reachability(FakeClock(), 30.0).reachable


def test_one_lost_answer_is_not_an_outage() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, 30.0)
    reachability.answered()
    assert reachability.unanswered() and reachability.silent
    clock.advance(29.0)
    assert reachability.unanswered()


def test_silence_for_the_whole_period_is_an_outage() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, 30.0)
    reachability.answered()
    reachability.unanswered()
    clock.advance(30.0)
    assert not reachability.unanswered()
    assert reachability.silent_for == 30.0


def test_an_answer_ends_the_silence_at_once() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, 30.0)
    reachability.answered()
    reachability.unanswered()
    clock.advance(30.0)
    reachability.unanswered()
    assert reachability.answered() and not reachability.silent and reachability.silent_for == 0.0


def test_the_silence_is_counted_from_the_first_unanswered_request_not_the_last_answer() -> None:
    clock = FakeClock()
    reachability = Reachability(clock, 30.0)
    reachability.answered()
    clock.advance(900.0)
    assert reachability.unanswered()


def test_no_grace_counts_the_first_silence_as_an_outage() -> None:
    reachability = Reachability(FakeClock(), 0.0)
    reachability.answered()
    assert not reachability.unanswered()


def test_a_grace_that_cannot_be_meant_is_refused() -> None:
    with pytest.raises(ValueError):
        Reachability(FakeClock(), float("nan"))
