"""What a measurement of a device's timing says."""
from __future__ import annotations

from event_connect.testing import Latency, Settling, recommended_refresh


def test_a_latency_tells_the_median_the_slowest_and_the_unanswered() -> None:
    latency = Latency((0.2, None, 0.4, 0.3))
    assert (latency.median, latency.slowest, latency.unanswered) == (0.3, 0.4, 1)
    assert str(latency) == "answered 3 of 4 requests: median 0.300 s, slowest 0.400 s"


def test_a_device_that_never_answered_has_no_latency() -> None:
    latency = Latency((None, None))
    assert latency.median is None and latency.slowest is None
    assert str(latency) == "no answer to 2 requests"


def test_a_value_settles_from_the_first_reading_that_stays_near_the_last() -> None:
    settling = Settling("low to high", ((0.5, 1300), (1.0, 1900), (1.5, 2190), (2.0, 2205), (2.5, 2200)), 20)
    assert settling.settled_after == 1.5
    assert str(settling).startswith("low to high: settled after 1.5 s")


def test_a_value_still_changing_has_not_settled() -> None:
    assert Settling("x", ((0.5, 1300), (1.0, 1900)), 20).settled_after is None
    assert Settling("x", ((0.5, 1300),), 20).settled_after is None


def test_the_recommended_refresh_reads_when_the_slowest_has_settled_and_allows_twice_as_long() -> None:
    fast = Settling("a", ((0.5, 1), (1.0, 1), (1.5, 1)), 0)
    slow = Settling("b", ((0.5, 1), (1.0, 5), (2.2, 9), (2.7, 9)), 0)
    assert recommended_refresh((fast, slow), every=0.5) == (2.5, 5)


def test_nothing_is_recommended_when_a_change_did_not_settle() -> None:
    assert recommended_refresh((Settling("a", ((0.5, 1), (1.0, 5)), 0),), every=0.5) is None
    assert recommended_refresh((), every=0.5) is None
