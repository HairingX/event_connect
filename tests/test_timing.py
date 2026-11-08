"""A library's timing: what it accepts, and the schedule and waits it gives."""
from __future__ import annotations

from typing import Any

import pytest

from event_connect import DEFAULT_TIMING, Key, PollRate, Refresh, Timing
from event_connect.testing import FakeClock, FakePoint


@pytest.mark.parametrize("fields", [
    {"read_back_after": -1.0},
    {"min_poll_interval": float("nan")},
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


def test_its_scheduler_plans_by_its_intervals() -> None:
    clock = FakeClock()
    scheduler = Timing(poll_intervals={PollRate.FAST: 5.0}).scheduler(clock)
    scheduler.set_points([FakePoint(Key("a", int), poll_rate=PollRate.FAST)])
    assert scheduler.interval("a") == 5.0


def _written(**fields: Any) -> FakePoint[int]:
    return FakePoint(Key("p", int), can_write=True, **fields)


def test_a_written_point_is_read_back_after_the_timing_s_wait_whatever_its_on_write_says() -> None:
    timing = Timing(read_back_after=1.0)
    assert timing.written_point_delay(_written(on_write=Refresh(["a"], after=3.0))) == 1.0
    assert timing.written_point_delay(_written()) == 1.0


def test_what_a_write_disturbs_is_read_after_the_refresh_s_wait_or_else_the_timing_s() -> None:
    timing = Timing(read_back_after=1.0)
    assert timing.on_write_delay(_written(on_write=Refresh(["a"], after=3.0))) == 3.0
    assert timing.on_write_delay(_written(on_write=Refresh(["a"]))) == 1.0
    assert timing.on_write_delay(_written()) == 1.0


def test_a_timing_has_no_single_read_back_delay() -> None:
    assert not hasattr(DEFAULT_TIMING, "read_back_delay")
