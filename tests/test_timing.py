"""A library's timing: what it accepts, and the schedule and waits it gives."""
from __future__ import annotations

from typing import Any

import pytest

from event_connect import DEFAULT_TIMING, Key, PollRate, Refresh, Timing
from event_connect.testing import FakeClock, FakePoint


@pytest.mark.parametrize("fields", [
    {"read_back_after": -1.0},
    {"min_poll_interval": float("nan")},
    {"retry_after": float("inf")},
    {"offline_after": -1.0},
])
def test_a_timing_that_cannot_be_meant_is_refused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Timing(**fields)


def test_a_timing_keeps_a_frozen_copy_of_its_intervals() -> None:
    intervals = {PollRate.FAST: 5.0}
    timing = Timing(poll_intervals=intervals)
    intervals[PollRate.FAST] = 1.0
    assert timing.poll_intervals[PollRate.FAST] == 5.0


def test_its_scheduler_plans_by_its_intervals_and_retries() -> None:
    clock = FakeClock()
    scheduler = Timing(poll_intervals={PollRate.FAST: 5.0}, retry_after=2.0).scheduler(clock)
    scheduler.set_points([FakePoint(Key("a", int), poll_rate=PollRate.FAST)])
    scheduler.set_polled("a", True)
    scheduler.record("a", None, success=False)
    assert scheduler.interval("a") == 5.0
    assert scheduler.next_due() == clock.monotonic() + 2.0


def test_a_write_shows_after_the_refresh_s_wait_then_the_point_s_then_the_timing_s() -> None:
    def point(**fields: Any) -> FakePoint[int]:
        return FakePoint(Key("p", int), can_write=True, **fields)

    assert DEFAULT_TIMING.read_back_delay(point(on_write=Refresh(["a"], after=3.0), read_back_after=2.0)) == 3.0
    assert DEFAULT_TIMING.read_back_delay(point(on_write=Refresh(["a"]), read_back_after=2.0)) == 2.0
    assert DEFAULT_TIMING.read_back_delay(point(on_write=Refresh(["a"]))) == DEFAULT_TIMING.read_back_after
