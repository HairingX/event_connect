"""The two clocks the library uses, behind one object that can be replaced."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """A monotonic clock to schedule by, and a wall clock to stamp values with."""

    def monotonic(self) -> float:
        """Seconds on a clock that never goes backwards; only differences mean anything."""
        ...

    def now(self) -> datetime:
        """The current time, timezone-aware UTC."""
        ...


class SystemClock:
    """The real clocks."""

    def monotonic(self) -> float:
        """Seconds on the system's monotonic clock."""
        return time.monotonic()

    def now(self) -> datetime:
        """The system's time, timezone-aware UTC."""
        return datetime.now(timezone.utc)
