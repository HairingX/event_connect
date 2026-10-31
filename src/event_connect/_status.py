"""What a client knows about its device, apart from the device's points."""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto

from ._value import DataValue


class Status(Enum):
    """What the client itself knows about its device, apart from the device's points."""
    CONNECTED = auto()
    """True while the device answers."""
    WRITE_PENDING = auto()
    """True from the first queued write until the last one has finished."""


StatusCallback = Callable[[Status, DataValue[bool] | None, DataValue[bool]], None]
"""Called with the status, its previous value (None the first time) and the new value."""
