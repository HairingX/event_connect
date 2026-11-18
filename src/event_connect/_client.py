"""What every client of a device offers, whatever its protocol: one way to use them all."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from ._events import ValueCallback
from ._identity import Identity
from ._key import Key
from ._point import Point, PollRate, Selector
from ._status import Status, StatusCallback
from ._value import DataValue
from ._writes import Write

PointsCallback = Callable[[frozenset[Key[Any]], frozenset[Key[Any]]], None]
"""Called with the keys the unit has gained and the keys it has lost, once its points changed."""


class ModelInfo(Protocol):
    """Which model a device is."""

    @property
    def name(self) -> str:
        """The model's name, as its manufacturer writes it."""
        ...

    @property
    def manufacturer(self) -> str:
        """Who makes it."""
        ...


@runtime_checkable
class DeviceClient(Protocol):
    """A device as a consumer uses it: its points, their values and what changes them, polling and
    writes.

    `poll`, `refresh` and `write` raise `NotConnectedError` until `connect()`, and again from
    `disconnect()` until the next `connect()`; `points`, `model` and `seconds_until_next_poll` raise
    it until the first `connect()`.
    """

    async def connect(self) -> None:
        """Reach the device, learn what it has, and read every value once.

        Raises:
            CannotConnectError: the device could not be reached.
            UnsupportedDeviceError: the device is not one the client knows.
        """
        ...

    async def disconnect(self) -> None:
        """Let go of the device: `Status.CONNECTED` turns False."""
        ...

    async def run(self) -> None:
        """Poll whenever something is due, until cancelled; it never ends by itself.

        While the client is not connected - before `connect()`, or after `disconnect()` - it
        waits until it is. A poll that raises is logged, and polling goes on after a pause: the
        first failure in a row at error level with its traceback, the ones after it at debug
        level, and the first poll that succeeds after them at info level.
        """
        ...

    async def poll(self) -> None:
        """Read whatever is due; nothing when nothing is."""
        ...

    async def refresh(self, targets: PollRate | Selector | Sequence[str] | None = None, *,
                      after: float = 0.0) -> None:
        """Read a poll rate's points, a selection, or everything - now, or `after` seconds from now."""
        ...

    async def write[T](self, key: Key[T], value: T) -> bool:
        """Write `value` to `key`; whether the device took it.

        Raises:
            ReadOnlyError: the client is read-only.
            KeyError: the device has no such key.
            InvalidValueError: the point refuses the value.
        """
        ...

    async def write_sequence(self, writes: Sequence[Write[Any]]) -> bool:
        """Write several values in order, stopping at the first refusal; whether all were taken.

        Every value is checked before anything is sent.
        """
        ...

    def value[T](self, key: Key[T]) -> DataValue[T] | None:
        """The current value of `key`; None while the device has none."""
        ...

    @property
    def values(self) -> Mapping[Key[Any], DataValue[Any]]:
        """The current value of each key the device has, among those read."""
        ...

    def status(self, status: Status) -> DataValue[bool]:
        """The current value of `status`."""
        ...

    def subscribe[T](self, key: Key[T], callback: ValueCallback[T], *, poll: bool = True) -> Callable[[], None]:
        """Call `callback` on every change of `key`'s value or quality, starting with the current
        value; with `poll`, `key` is also read on its schedule. Returns the unsubscriber.

        Raises:
            KeyError: no model the client knows has `key`.
        """
        ...

    def subscribe_status(self, status: Status, callback: StatusCallback) -> Callable[[], None]:
        """Call `callback` on every change of `status`, starting with its current value. Returns
        the unsubscriber."""
        ...

    def subscribe_points(self, callback: PointsCallback) -> Callable[[], None]:
        """Call `callback` whenever the points the device has change. Returns the unsubscriber."""
        ...

    def set_polling(self, key: str, enabled: bool = True) -> None:
        """Read `key` on its schedule even without a subscriber; False stops that."""
        ...

    def set_scheduled_polling(self, enabled: bool) -> None:
        """Whether points are read on their schedule; off, only what a refresh or a write asks
        for is read."""
        ...

    def seconds_until_next_poll(self) -> float | None:
        """Seconds until `poll()` has something to do, 0 if it has now; None if it never will."""
        ...

    @property
    def silent(self) -> bool:
        """Whether the device left the latest request unanswered."""
        ...

    @property
    def silent_for(self) -> float:
        """Seconds since the device first left a request unanswered since its last answer; 0 while
        it answers."""
        ...

    def diagnostics(self) -> Mapping[str, object]:
        """Counters for a bug report; never an address or a credential."""
        ...

    @property
    def points(self) -> Mapping[Key[Any], Point[Any]]:
        """The points the device has, by key."""
        ...

    @property
    def model(self) -> ModelInfo:
        """The model of the device."""
        ...

    @property
    def identity(self) -> Identity:
        """What the device reported about itself."""
        ...

    def has(self, key: str) -> bool:
        """Whether the device has `key`."""
        ...

    def can_read(self, key: str) -> bool:
        """Whether the device has `key`, and it can be read."""
        ...

    def can_write(self, key: str) -> bool:
        """Whether the device has `key`, and it can be written."""
        ...

    def select(self, targets: Selector | Sequence[str]) -> tuple[Point[Any], ...]:
        """The points `targets` selects, among those the device has."""
        ...

    def instances(self, label: str) -> tuple[int, ...]:
        """The numbers of the instances of `label` the device has a point of."""
        ...

    @property
    def unavailable_reasons(self) -> Mapping[Key[Any], str]:
        """The keys its model declares that the device does not have, with the reason."""
        ...

    def consecutive_failures(self, key: str) -> int:
        """How many reads of `key` in a row have failed."""
        ...
