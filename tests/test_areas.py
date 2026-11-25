"""Raw reads of areas, and what changed between two."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from event_connect import Area, RawAddress, RegisterChange, Snapshot, difference

AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def dp(number: int) -> RawAddress:
    return RawAddress("datapoint", number)


def sp(number: int) -> RawAddress:
    return RawAddress("setpoint", number)


def test_an_area_runs_from_its_start_for_its_count() -> None:
    area = Area("datapoint", 20, 3)
    assert (area.end, area.addresses()) == (23, (dp(20), dp(21), dp(22)))


def test_an_area_and_an_address_are_named_by_their_space_and_numbers() -> None:
    assert (str(Area("datapoint", 20, 4)), str(Area("setpoint", 7, 1)), str(sp(7))) == (
        "datapoint 20-23", "setpoint 7", "setpoint 7")


@pytest.mark.parametrize(("space", "start", "count", "problem"), [
    ("", 0, 1, "space"), ("datapoint", -1, 1, "below 0"), ("datapoint", 0, 0, "at least one")])
def test_an_area_has_a_space_a_start_from_0_and_a_register(space: str, start: int, count: int, problem: str) -> None:
    with pytest.raises(ValueError, match=problem):
        Area(space, start, count)


def test_a_snapshot_holds_the_words_read_and_the_addresses_missing() -> None:
    snapshot = Snapshot(AT, {dp(20): 1, sp(30): 5}, [dp(22)])
    assert (dict(snapshot.values), snapshot.missing) == ({dp(20): 1, sp(30): 5}, frozenset({dp(22)}))


def test_a_snapshot_holds_no_address_both_read_and_missing() -> None:
    with pytest.raises(ValueError, match="read and missing at once: datapoint 22"):
        Snapshot(AT, {dp(22): 3}, [dp(22)])


@pytest.mark.parametrize("word", [-1, 0x10000])
def test_a_snapshot_holds_register_words(word: int) -> None:
    with pytest.raises(ValueError, match="words outside 0-65535 at datapoint 20"):
        Snapshot(AT, {dp(20): word}, [])


def test_a_snapshot_is_plain_data_by_space() -> None:
    snapshot = Snapshot(AT, {dp(21): 0, dp(20): 1, sp(30): 5}, [dp(23), dp(22)])
    assert snapshot.as_plain() == {
        "taken_at": "2026-01-01T00:00:00+00:00",
        "values": {"datapoint": {"20": 1, "21": 0}, "setpoint": {"30": 5}},
        "missing": {"datapoint": [22, 23]},
    }


def test_the_difference_is_every_register_that_changed_by_space_and_number_with_its_bits() -> None:
    before = Snapshot(AT, {dp(20): 0b0101, dp(21): 0, dp(23): 7, sp(30): 5, sp(31): 6}, [dp(22)])
    after = Snapshot(LATER, {dp(20): 0b0110, dp(21): 0, dp(22): 9, sp(30): 5, sp(31): 7}, [dp(23)])
    assert difference(before, after) == (
        RegisterChange(dp(20), 0b0101, 0b0110, (0, 1)),
        RegisterChange(dp(22), None, 9, ()),
        RegisterChange(dp(23), 7, None, ()),
        RegisterChange(sp(31), 6, 7, (0,)),
    )
    assert difference(after, after) == ()


def test_a_register_only_one_snapshot_read_is_no_change() -> None:
    before = Snapshot(AT, {dp(20): 1, dp(21): 2}, [])
    after = Snapshot(LATER, {dp(21): 3, dp(22): 4}, [dp(19)])
    assert difference(before, after) == (RegisterChange(dp(21), 2, 3, (0,)),)


def test_a_change_is_plain_data() -> None:
    assert RegisterChange(sp(31), 6, 7, (0,)).as_plain() == {
        "space": "setpoint", "number": 31, "before": 6, "after": 7, "bits": [0]}


@pytest.mark.parametrize("at", [datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))],
                         ids=["naive", "not-utc"])
def test_a_snapshot_is_taken_at_a_utc_time(at: datetime) -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        Snapshot(at, {}, [])
