"""A point as its behaviour declares it: what is accepted, what is refused, and the parts it is
built from."""
from __future__ import annotations

import pickle
from collections.abc import Callable
from datetime import date, datetime, time
from enum import IntEnum
from typing import Any

import pytest

from event_connect import (
    Change,
    Key,
    Labels,
    Limits,
    PollRate,
    Pulse,
    Refresh,
    Transform,
    Transforms,
    Unit,
    WriteKind,
    select,
)
from event_connect.testing import FakePoint


class Mode(IntEnum):
    OFF = 0
    ON = 1


def _refused(match: str, key: Key[Any] | str = Key("p", int), **fields: Any) -> None:
    with pytest.raises(ValueError, match=match):
        FakePoint(key, **fields)  # pyright: ignore[reportArgumentType]


# ========================================================================== valid points


@pytest.mark.parametrize("fields", [
    {},
    {"can_write": True, "limits": Limits(5, 35, 0.5), "on_write": Refresh(["a", "b"], after=2, until_stable=30)},
    {"on_change": Refresh(Labels(kind="alarm"))},
    {"poll_always": True, "poll_rate": PollRate.STATIC, "unit": Unit.CELSIUS},
    {"can_read": False, "can_write": True, "write_kind": WriteKind.COMMAND, "read_back_after": 1.0},
], ids=lambda f: "-".join(sorted(f)) or "plain")
def test_a_valid_point_is_accepted(fields: dict[str, Any]) -> None:
    FakePoint(Key("p", float), **fields)


@pytest.mark.parametrize("value_type", [bool, int, float, str, date, datetime, time, Mode])
def test_every_value_type_is_accepted(value_type: type[Any]) -> None:
    FakePoint(Key("p", value_type))


# =========================================================================== refused points


def test_a_point_needs_a_side() -> None:
    _refused("read side, a write side, or both", can_read=False)


@pytest.mark.parametrize("key", ["", " padded ", "trailing "])
def test_a_key_must_be_a_clean_non_empty_string(key: str) -> None:
    _refused("non-empty string", Key(key, int))


def test_a_key_must_be_a_key_not_only_its_text() -> None:
    _refused("must be a Key", "p")


def test_a_value_type_no_device_holds_is_refused() -> None:
    _refused("not bytes", Key("p", bytes))


@pytest.mark.parametrize("value_type", [bool, str, Mode])
def test_number_only_features_are_refused_on_other_types(value_type: type[Any]) -> None:
    _refused("deadband applies to numbers", Key("p", value_type), deadband=1)
    _refused("limits apply to numbers", Key("p", value_type), can_write=True, limits=Limits(0, 1))


def test_limits_need_a_write_side() -> None:
    _refused("limits describe writes", limits=Limits(0, 1))


def test_deadband_cannot_be_negative() -> None:
    _refused("deadband cannot be negative", deadband=-1)


def test_deadband_needs_a_read_side() -> None:
    _refused("deadband filters reads", can_read=False, can_write=True, deadband=1)


def test_poll_always_needs_a_read_side() -> None:
    _refused("poll_always", can_read=False, can_write=True, poll_always=True)


def test_no_point_is_polled_at_the_scan_rate() -> None:
    _refused("PollRate.SCAN", poll_rate=PollRate.SCAN)


def test_a_command_needs_a_write_side() -> None:
    _refused("COMMAND is written", write_kind=WriteKind.COMMAND)


def test_only_a_command_can_pulse() -> None:
    _refused("only a COMMAND can pulse", can_write=True, pulse=Pulse(0, 1))


def test_a_pulse_returns_to_a_value_of_the_key_type() -> None:
    _refused("idle value", can_write=True, write_kind=WriteKind.COMMAND, pulse=Pulse("off", 1))


def test_on_write_needs_a_write_side() -> None:
    _refused("on_write re-reads after a write", on_write=Refresh(["a"]))


def test_on_change_needs_a_read_side() -> None:
    _refused("on_change reacts to reads", can_read=False, can_write=True, on_change=Refresh(["a"]))


def test_on_write_has_no_change_to_wait_for() -> None:
    _refused("`when` belongs to on_change", can_write=True, on_write=Refresh(["a"], when=Change.RISING))


def test_re_reading_until_stable_after_a_write_needs_an_interval() -> None:
    _refused("on_write re-reads until stable", can_write=True, read_back_after=0,
             on_write=Refresh(["a"], until_stable=10))


def test_read_back_after_needs_a_write_side() -> None:
    _refused("read_back_after describes writes", read_back_after=1)


@pytest.mark.parametrize("seconds", [-1.0, float("inf"), float("nan")])
def test_read_back_after_must_be_a_finite_number_of_seconds(seconds: float) -> None:
    _refused("read_back_after must be a finite", can_write=True, read_back_after=seconds)


def test_a_label_needs_a_name() -> None:
    _refused("a label needs a name", labels={"": 1})


def test_every_problem_is_named_in_one_error() -> None:
    with pytest.raises(ValueError) as caught:
        FakePoint(Key("p", bool), deadband=-1, read_back_after=1)
    message = str(caught.value)
    assert "deadband applies to numbers" in message and "read_back_after describes writes" in message


# ================================================================================== parts


def test_a_key_is_its_text_wherever_it_goes() -> None:
    key = Key("temperature", float)
    assert key == "temperature" and hash(key) == hash("temperature") and {"temperature": 1}[key] == 1
    assert repr(key) == "'temperature'"
    copied = pickle.loads(pickle.dumps(key))
    assert (copied, copied.type) == ("temperature", float) and isinstance(copied, Key)


def test_labels_are_a_frozen_copy() -> None:
    labels = {"room": 1}
    point = FakePoint(Key("p", int), labels=labels)
    labels["room"] = 2
    assert point.labels == {"room": 1}
    with pytest.raises(TypeError):
        point.labels["room"] = 3  # pyright: ignore[reportIndexIssue]


def test_a_point_names_the_states_of_its_key() -> None:
    assert FakePoint(Key("p", Mode)).states == (Mode.OFF, Mode.ON)
    assert FakePoint(Key("p", int)).states == ()


def test_labels_match_when_every_pair_is_present() -> None:
    assert Labels(room=1, kind="t").matches({"room": 1, "kind": "t", "extra": 9})
    assert not Labels(room=1, kind="t").matches({"room": 1})


def test_labels_compare_by_content() -> None:
    assert Labels(a=1, b=2) == Labels(b=2, a=1) and hash(Labels(a=1)) == hash(Labels(a=1))


def test_empty_labels_select_nothing_and_are_refused() -> None:
    with pytest.raises(ValueError):
        Labels()


def test_a_selection_keeps_the_order_of_the_points() -> None:
    points = [FakePoint(Key(name, int), labels={"group": group}) for name, group in
              (("a", 1), ("b", 2), ("c", 1))]
    assert [p.key for p in select(points, Labels(group=1))] == ["a", "c"]
    assert [p.key for p in select(points, ("c", "a"))] == ["a", "c"]


def test_refresh_takes_keys_or_labels() -> None:
    assert Refresh(["a", "b"]).targets == ("a", "b")
    assert Refresh(Labels(room=1)).targets == Labels(room=1)


@pytest.mark.parametrize("build,error", [
    (lambda: Refresh("ab"), TypeError),
    (lambda: Refresh([]), ValueError),
    (lambda: Refresh(["a"], after=-1), ValueError),
    (lambda: Refresh(["a"], until_stable=0), ValueError),
    (lambda: Refresh(["a"], after=0, until_stable=10), ValueError),
])
def test_a_contradictory_refresh_is_refused(build: Callable[[], object], error: type[Exception]) -> None:
    with pytest.raises(error):
        build()


def test_a_change_refresh_waits_not_at_all_unless_told() -> None:
    point = FakePoint(Key("p", int), on_change=Refresh(["a"]))
    assert point.on_change is not None and point.on_change.after == 0.0


def test_a_refresh_reacts_to_any_change_unless_told_otherwise() -> None:
    assert Refresh(["a"]).when is Change.ANY


@pytest.mark.parametrize("build", [
    lambda: Limits(5, 1),
    lambda: Limits(step=0),
    lambda: Pulse(0, 0),
])
def test_contradictory_limits_and_pulses_are_refused(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


def test_limits_say_why_a_value_may_not_be_written() -> None:
    limits = Limits(10, 20)
    assert limits.problem(15) is None
    assert limits.problem(9) == "9 is below the minimum 10"
    assert limits.problem(21) == "21 is above the maximum 20"


@pytest.mark.parametrize("transform", [Transforms.INVERT_BOOL, Transforms.SECONDS_AS_MINUTES,
                                       Transforms.MINUTES_AS_HOURS, Transforms.HOURS_AS_DAYS])
@pytest.mark.parametrize("value", [0, 1, 60, 1440])
def test_every_built_in_transform_round_trips(transform: Transform, value: int) -> None:
    assert transform.write(transform.read(value)) == pytest.approx(value)  # pyright: ignore[reportUnknownMemberType]


def test_every_unit_has_a_plain_ascii_code() -> None:
    for unit in Unit:
        assert unit.code.isascii() and " " not in unit.code


def test_a_millivolt_is_written_as_the_si_and_ucum_do() -> None:
    assert (str(Unit.MILLIVOLT), Unit.MILLIVOLT.code) == ("mV", "mV")
