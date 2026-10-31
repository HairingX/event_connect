"""Support for testing what is built on these points, and for working out a device's timing: a
clock that moves only when told, a point without a protocol, and what a measurement says."""
from ._clock import FakeClock
from ._measure import Latency, Settling, recommended_refresh
from ._point import FakePoint

__all__ = ["FakeClock", "FakePoint", "Latency", "Settling", "recommended_refresh"]
