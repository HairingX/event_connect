"""Devices described by their points, independent of protocol: keys, values and their quality,
how each point behaves, when it is read, and what a write or a change sets off.

Nothing here performs I/O or knows a protocol; a protocol package builds its points and client
on these. Support for tests and for measuring a device's timing is in `event_connect.testing`.
"""
from importlib.metadata import version as _installed_version

from ._certainty import Certainty
from ._client import DeviceClient, ModelInfo, PointsCallback
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
from ._events import Subscriber, Subscriptions, ValueCallback, changed, should_poll, tell
from ._identity import Identity
from ._key import Key, is_key, is_state_type
from ._level import Level, candidates_in_place, points_at
from ._point import (
    VALUE_TYPES,
    Candidate,
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
    WriteRange,
    is_instance,
    select,
    selector,
)
from ._passes import Passes
from ._reachability import Reachability
from ._resilience import (
    NO_RETRY,
    AnyOf,
    Attempt,
    Attempts,
    Breaker,
    CircuitBreaker,
    Exponential,
    Fixed,
    Jitter,
    Retry,
    Steps,
    Stop,
    Wait,
    Within,
)
from ._scheduler import Scheduler
from ._status import Status, StatusBoard, StatusCallback
from ._timing import Timing
from ._unit import Unit
from ._value import DataValue, Quality, Value, stale
from ._writes import Write

__version__ = _installed_version("event_connect")
__all__ = [
    "NO_RETRY",
    "VALUE_TYPES",
    "AnyOf",
    "Attempt",
    "Attempts",
    "AuthenticationError",
    "Breaker",
    "CannotConnectError",
    "Candidate",
    "Certainty",
    "Change",
    "CircuitBreaker",
    "ClientError",
    "Clock",
    "DataValue",
    "DeviceClient",
    "Exponential",
    "Fixed",
    "Identity",
    "InvalidValueError",
    "Jitter",
    "Key",
    "Labels",
    "Level",
    "Limits",
    "ModelError",
    "ModelInfo",
    "NotConnectedError",
    "Passes",
    "Point",
    "PointsCallback",
    "PollRate",
    "Pulse",
    "Quality",
    "Reachability",
    "ReadOnlyError",
    "Refresh",
    "Retry",
    "Scheduler",
    "Selector",
    "Status",
    "StatusBoard",
    "StatusCallback",
    "Steps",
    "Stop",
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
    "Wait",
    "Within",
    "Write",
    "WriteKind",
    "WriteRange",
    "candidates_in_place",
    "changed",
    "is_instance",
    "is_key",
    "is_state_type",
    "points_at",
    "select",
    "selector",
    "should_poll",
    "stale",
    "tell",
]
