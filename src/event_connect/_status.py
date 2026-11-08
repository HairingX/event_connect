"""What a client knows about its device, apart from the device's points."""
from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from enum import Enum, auto

from ._clock import Clock
from ._value import DataValue, Quality

_LOGGER = logging.getLogger(__name__)


class Status(Enum):
    """What the client itself knows about its device, apart from the device's points."""
    CONNECTED = auto()
    """True while the device answers."""
    WRITE_PENDING = auto()
    """True from the first queued write until the last one has finished."""


StatusCallback = Callable[[Status, DataValue[bool] | None, DataValue[bool]], None]
"""Called with the status, its previous value (None the first time) and the new value."""


class StatusBoard:
    """Each `Status` of one device, as a value its subscribers are told every change of.

    Every status starts False.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._values = {status: DataValue(False, Quality.GOOD, clock.now()) for status in Status}
        self._callbacks: dict[Status, list[StatusCallback]] = {status: [] for status in Status}
        self._holders = {status: 0 for status in Status}

    def value(self, status: Status) -> DataValue[bool]:
        """What is known of `status` now."""
        return self._values[status]

    def set(self, status: Status, value: bool) -> None:
        """Set `status`, telling its subscribers if it changes."""
        old = self._values[status]
        if old.value is value:
            return
        new = DataValue(value, Quality.GOOD, self._clock.now())
        self._values[status] = new
        for callback in list(self._callbacks[status]):
            _tell(callback, status, old, new)

    def holding(self, status: Status) -> AbstractContextManager[None]:
        """Hold `status` True while inside; it turns False only when the last of those holding it
        leaves, so that overlapping work, such as two writes at once, shows as one."""
        return _Holding(self._holders, status, self.set)

    def subscribe(self, status: Status, callback: StatusCallback) -> Callable[[], None]:
        """Call `callback` on every change of `status`, starting with its current value; a
        callback that raises is logged and kept from the others.

        Returns the unsubscriber.
        """
        callbacks = self._callbacks[status]
        callbacks.append(callback)
        _tell(callback, status, None, self._values[status])

        def unsubscribe() -> None:
            if callback in callbacks:
                callbacks.remove(callback)

        return unsubscribe


def _tell(callback: StatusCallback, status: Status, old: DataValue[bool] | None, new: DataValue[bool]) -> None:
    try:
        callback(status, old, new)
    except Exception:
        _LOGGER.exception("a subscriber to %s raised", status)


class _Holding(AbstractContextManager[None]):
    def __init__(self, holders: dict[Status, int], status: Status, set_status: Callable[[Status, bool], None]) -> None:
        self._holders = holders
        self._status = status
        self._set = set_status

    def __enter__(self) -> None:
        self._holders[self._status] += 1
        self._set(self._status, True)

    def __exit__(self, *exc: object) -> None:
        self._holders[self._status] -= 1
        if not self._holders[self._status]:
            self._set(self._status, False)
