"""Who is told what, and when a change is a change."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import event_connect as core
from event_connect import (
    Change,
    Clock,
    DataValue,
    Key,
    Quality,
    Subscriptions,
    SystemClock,
    changed,
    stale,
)
from event_connect.testing import FakeClock, FakePoint

_WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _good(value: Any) -> DataValue[Any]:
    return DataValue[Any](value, Quality.GOOD, _WHEN)


def _told(subscriptions: Subscriptions, key: Key[Any]) -> list[Any]:
    seen: list[Any] = []
    subscriptions.add(key, lambda _key, _old, new: seen.append(new.value), polls=True)
    return seen


def test_a_subscriber_is_told_a_change_and_not_the_same_value_again() -> None:
    point = FakePoint(Key("p", int))
    subscriptions = Subscriptions()
    seen = _told(subscriptions, point.key)
    for value in (1, 1, 2):
        subscriptions.report(point, _good(value))
    assert seen == [1, 2]


def test_a_change_of_quality_is_always_told() -> None:
    point = FakePoint(Key("p", int))
    subscriptions = Subscriptions()
    seen: list[Quality] = []
    subscriptions.add(point.key, lambda _key, _old, new: seen.append(new.quality), polls=True)
    subscriptions.report(point, _good(1))
    subscriptions.report(point, stale(_good(1), _WHEN))
    assert seen == [Quality.GOOD, Quality.STALE]


def test_a_change_inside_the_deadband_is_not_told() -> None:
    point = FakePoint(Key("p", float), deadband=0.5)
    subscriptions = Subscriptions()
    seen = _told(subscriptions, point.key)
    for value in (20.0, 20.3, 20.6):
        subscriptions.report(point, _good(value))
    assert seen == [20.0, 20.6]


def test_a_raising_subscriber_does_not_keep_the_others_from_being_told() -> None:
    point = FakePoint(Key("p", int))
    subscriptions = Subscriptions()

    def raising(_key: Key[Any], _old: DataValue[Any] | None, _new: DataValue[Any]) -> None:
        raise RuntimeError("boom")

    subscriptions.add(point.key, raising, polls=True)
    seen = _told(subscriptions, point.key)
    subscriptions.report(point, _good(1))
    assert seen == [1]


@pytest.mark.parametrize("old,new,when,expected", [
    (1, 2, Change.ANY, True),
    (1, 1, Change.ANY, False),
    (1, 2, Change.RISING, True),
    (2, 1, Change.RISING, False),
    (2, 1, Change.FALLING, True),
    (False, True, Change.RISING, True),
    ("a", "b", Change.RISING, False),
])
def test_a_change_matches_its_direction(old: Any, new: Any, when: Change, expected: bool) -> None:
    assert changed(_good(old), _good(new), when) is expected


def test_only_good_values_compare_as_a_change() -> None:
    assert not changed(stale(_good(1), _WHEN), _good(2), Change.ANY)


def test_a_stale_value_keeps_the_last_good_one_and_its_time() -> None:
    later = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert stale(_good(5), later) == DataValue(5, Quality.STALE, _WHEN)
    assert stale(None, later) == DataValue(None, Quality.STALE, later)


def test_the_system_clock_satisfies_the_protocol() -> None:
    clock: Clock = SystemClock()
    assert isinstance(clock, Clock) and clock.now().tzinfo is not None
    assert clock.monotonic() <= clock.monotonic()


def test_a_fake_clock_moves_both_clocks_only_when_told() -> None:
    clock = FakeClock()
    start = (clock.monotonic(), clock.now())
    clock.advance(5)
    assert clock.monotonic() == start[0] + 5 and (clock.now() - start[1]).total_seconds() == 5


def test_the_package_imports_nothing_but_the_standard_library() -> None:
    root = Path(core.__file__).parent
    allowed = {"__future__", "collections", "dataclasses", "datetime", "enum", "importlib", "logging", "math", "statistics", "time",
               "types", "typing"}
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                assert node.module.split(".")[0] in allowed, f"{path.name} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in allowed, f"{path.name} imports {alias.name}"
