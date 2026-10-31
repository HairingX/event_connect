"""Devices described by their points, independent of protocol: keys, values and their quality,
how each point behaves, when it is read, and what a write or a change sets off.

Nothing here performs I/O or knows a protocol; a protocol package builds its points and client
on these. Support for tests and for measuring a device's timing is in `event_connect.testing`.
"""
from importlib.metadata import version as _installed_version

from ._certainty import Certainty
from ._clock import Clock, SystemClock
from ._errors import (
    AuthenticationError,
    CannotConnectError,
    ClientError,
    InvalidValueError,
    ModelError,
    NotConnectedError,
    ReadOnlyError,
    UnsupportedDeviceError,
)
from ._events import Subscriber, Subscriptions, ValueCallback, changed, tell
from ._key import Key, is_key, is_state_type
from ._point import (
    DEFAULT_INTERVALS,
    VALUE_TYPES,
    Change,
    Labels,
    Limits,
    Point,
    PollRate,
    Pulse,
    Refresh,
    Selector,
    Transform,
    Transforms,
    WriteKind,
    is_instance,
    select,
    selector,
)
from ._reachability import Reachability
from ._scheduler import Scheduler
from ._status import Status, StatusCallback
from ._timing import DEFAULT_TIMING, Timing
from ._unit import Unit
from ._value import DataValue, Quality, Value, stale
from ._writes import Write

__version__ = _installed_version("event_connect")
__all__ = [
    "DEFAULT_INTERVALS",
    "DEFAULT_TIMING",
    "VALUE_TYPES",
    "AuthenticationError",
    "CannotConnectError",
    "Certainty",
    "Change",
    "ClientError",
    "Clock",
    "DataValue",
    "InvalidValueError",
    "Key",
    "Labels",
    "Limits",
    "ModelError",
    "NotConnectedError",
    "Point",
    "PollRate",
    "Pulse",
    "Quality",
    "ReadOnlyError",
    "Reachability",
    "Refresh",
    "Scheduler",
    "Selector",
    "Status",
    "StatusCallback",
    "Subscriber",
    "Subscriptions",
    "SystemClock",
    "Timing",
    "Transform",
    "Transforms",
    "Unit",
    "UnsupportedDeviceError",
    "Value",
    "ValueCallback",
    "Write",
    "WriteKind",
    "changed",
    "is_instance",
    "is_key",
    "is_state_type",
    "select",
    "selector",
    "stale",
    "tell",
]
