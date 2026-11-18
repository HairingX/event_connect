"""A library's timing: what it accepts, and the schedule and waits it gives."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

from event_connect import Key, PollRate, Refresh, Timing
from event_connect.testing import FakeClock, FakePoint


@pytest.mark.parametrize("fields", [
    {"poll_intervals": {PollRate.FAST: 10.0}, "read_back_after": -1.0},
    {"poll_intervals": {PollRate.FAST: 10.0}, "read_back_after": float("nan")},
    {"poll_intervals": {PollRate.FAST: 0.0}, "read_back_after": 1.0},
    {"poll_intervals": {PollRate.FAST: float("inf")}, "read_back_after": 1.0},
    {"poll_intervals": {PollRate.STATIC: 10.0}, "read_back_after": 1.0},
])
def test_a_timing_that_cannot_be_meant_is_refused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Timing(**fields)


@pytest.mark.parametrize("missing", ["poll_intervals", "read_back_after"])
def test_a_timing_says_both_its_intervals_and_its_read_back(missing: str) -> None:
    fields: dict[str, Any] = {"poll_intervals": {PollRate.FAST: 10.0}, "read_back_after": 1.0}
    del fields[missing]
    with pytest.raises(TypeError):
        Timing(**fields)


def test_a_timing_is_given_by_name() -> None:
    build = cast(Callable[..., object], Timing)
    with pytest.raises(TypeError):
        build({PollRate.FAST: 10.0}, 1.0)


def test_a_timing_keeps_a_frozen_copy_of_its_intervals() -> None:
    intervals = {PollRate.FAST: 5.0}
    timing = Timing(poll_intervals=intervals, read_back_after=1.0)
    intervals[PollRate.FAST] = 1.0
    assert timing.poll_intervals[PollRate.FAST] == 5.0


def test_its_scheduler_plans_by_its_intervals() -> None:
    clock = FakeClock()
    scheduler = Timing(poll_intervals={PollRate.FAST: 5.0}, read_back_after=1.0).scheduler(clock)
    scheduler.set_points([FakePoint(Key("a", int), poll_rate=PollRate.FAST)])
    assert scheduler.interval("a") == 5.0


def test_its_fastest_interval_is_the_shortest_of_its_rates() -> None:
    timing = Timing(poll_intervals={PollRate.SLOW: 60.0, PollRate.FAST: 10.0, PollRate.RARE: 900.0},
                    read_back_after=1.0)
    assert timing.fastest_interval == 10.0


def test_a_timing_that_reads_nothing_on_a_timer_has_no_fastest_interval() -> None:
    assert Timing(poll_intervals={}, read_back_after=1.0).fastest_interval is None


def _written(**fields: Any) -> FakePoint[int]:
    return FakePoint(Key("p", int), can_write=True, poll_rate=PollRate.MEDIUM, **fields)


def test_a_written_point_is_read_back_after_the_timing_s_wait_whatever_its_on_write_says() -> None:
    timing = Timing(poll_intervals={PollRate.MEDIUM: 30.0}, read_back_after=1.0)
    assert timing.written_point_delay(_written(on_write=Refresh(["a"], after=3.0))) == 1.0
    assert timing.written_point_delay(_written()) == 1.0


def test_what_a_write_disturbs_is_read_after_the_refresh_s_wait_or_else_the_timing_s() -> None:
    timing = Timing(poll_intervals={PollRate.MEDIUM: 30.0}, read_back_after=1.0)
    assert timing.on_write_delay(_written(on_write=Refresh(["a"], after=3.0))) == 3.0
    assert timing.on_write_delay(_written(on_write=Refresh(["a"]))) == 1.0
    assert timing.on_write_delay(_written()) == 1.0


def test_a_timing_has_no_single_read_back_delay() -> None:
    assert not hasattr(Timing(poll_intervals={}, read_back_after=1.0), "read_back_delay")


@pytest.mark.parametrize("gone", ["offline_after", "min_poll_interval"])
def test_a_timing_says_nothing_of_reachability_or_a_floor(gone: str) -> None:
    fields: dict[str, Any] = {"poll_intervals": {PollRate.FAST: 10.0}, "read_back_after": 1.0, gone: 1.0}
    with pytest.raises(TypeError):
        Timing(**fields)
