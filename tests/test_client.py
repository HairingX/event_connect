"""The surface every client of a device shares."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, get_protocol_members

from event_connect import (
    DataValue,
    DeviceClient,
    Identity,
    Key,
    ModelInfo,
    NotConnectedError,
    Point,
    PointsCallback,
    PollRate,
    Selector,
    Status,
    StatusBoard,
    StatusCallback,
    UnsupportedDeviceError,
    ValueCallback,
    Write,
)
from event_connect.testing import FakeClock


@dataclass(frozen=True)
class _Model:
    name: str
    manufacturer: str


class _Client:
    """The least a client can be: nothing but the shared surface, and no device behind it."""

    def __init__(self) -> None:
        self._statuses = StatusBoard(FakeClock())
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def run(self) -> None:
        await self.poll()

    async def poll(self) -> None:
        self._require_connected()

    async def refresh(self, targets: PollRate | Selector | Sequence[str] | None = None, *,
                      after: float = 0.0) -> None:
        self._require_connected()

    async def write[T](self, key: Key[T], value: T) -> bool:
        self._require_connected()
        return False

    async def write_sequence(self, writes: Sequence[Write[Any]]) -> bool:
        self._require_connected()
        return False

    def value[T](self, key: Key[T]) -> DataValue[T] | None:
        return None

    @property
    def values(self) -> Mapping[Key[Any], DataValue[Any]]:
        return {}

    def status(self, status: Status) -> DataValue[bool]:
        return self._statuses.value(status)

    def subscribe[T](self, key: Key[T], callback: ValueCallback[T], *, poll: bool = True) -> Callable[[], None]:
        raise KeyError(key)

    def subscribe_status(self, status: Status, callback: StatusCallback) -> Callable[[], None]:
        return self._statuses.subscribe(status, callback)

    def subscribe_points(self, callback: PointsCallback) -> Callable[[], None]:
        return lambda: None

    def set_polling(self, key: str, enabled: bool = True) -> None:
        pass

    def set_scheduled_polling(self, enabled: bool) -> None:
        pass

    def seconds_until_next_poll(self) -> float | None:
        self._require_connected()
        return None

    @property
    def silent(self) -> bool:
        return False

    @property
    def silent_for(self) -> float:
        return 0.0

    def diagnostics(self) -> Mapping[str, object]:
        return {}

    @property
    def points(self) -> Mapping[Key[Any], Point[Any]]:
        self._require_connected()
        return {}

    @property
    def model(self) -> _Model:
        self._require_connected()
        return _Model("Example", "Example Inc.")

    @property
    def identity(self) -> Identity:
        return {}

    def has(self, key: str) -> bool:
        return False

    def can_read(self, key: str) -> bool:
        return False

    def can_write(self, key: str) -> bool:
        return False

    def select(self, targets: Selector | Sequence[str]) -> tuple[Point[Any], ...]:
        return ()

    def instances(self, label: str) -> tuple[int, ...]:
        return ()

    @property
    def unavailable_reasons(self) -> Mapping[Key[Any], str]:
        return {}

    def consecutive_failures(self, key: str) -> int:
        return 0

    def _require_connected(self) -> None:
        if not self._connected:
            raise NotConnectedError("not connected")


class _NoModel:
    async def connect(self) -> None:
        pass


def test_a_client_with_the_shared_surface_is_a_device_client_before_it_connects() -> None:
    """`points` and `model` raise until `connect()`; telling a client must not read them."""
    client: DeviceClient = _Client()
    assert isinstance(client, DeviceClient)


def test_an_object_without_the_shared_surface_is_no_device_client() -> None:
    assert not isinstance(_NoModel(), DeviceClient)


def test_a_model_says_its_name_and_its_manufacturer() -> None:
    model: ModelInfo = _Model("Example", "Example Inc.")
    assert (model.name, model.manufacturer) == ("Example", "Example Inc.")
    assert get_protocol_members(ModelInfo) == frozenset({"name", "manufacturer"})


def test_the_shared_surface_is_what_every_client_offers() -> None:
    assert get_protocol_members(DeviceClient) == frozenset({
        "connect", "disconnect", "run", "poll", "refresh", "write", "write_sequence", "value",
        "values", "status", "subscribe", "subscribe_status", "subscribe_points", "set_polling",
        "set_scheduled_polling", "seconds_until_next_poll", "silent", "silent_for", "diagnostics",
        "points", "model", "identity", "has", "can_read", "can_write", "select", "instances",
        "unavailable_reasons", "consecutive_failures"})


def test_a_device_no_model_matches_keeps_a_copy_of_what_it_reported() -> None:
    reported = {"type": 3, "serial": "A1"}
    error = UnsupportedDeviceError("no model", reported)
    reported["type"] = 4
    assert error.identity == {"type": 3, "serial": "A1"}
    assert UnsupportedDeviceError("no model").identity == {}
