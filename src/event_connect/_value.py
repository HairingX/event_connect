"""A value together with how far it can be trusted, when the device said it, and what it said."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum, auto
from typing import Any

Value = float | int | str | bool | date | time | None
"""What a point holds once decoded; a `datetime` is a `date`."""


class Quality(Enum):
    """How far a value can be trusted."""

    GOOD = auto()
    """The device answered with a valid value."""
    NO_DATA = auto()
    """The answer means "no reading": a sentinel, an out-of-range value, or an unnamed enum.

    Show as unknown.
    """
    OFFLINE = auto()
    """The register exists, but what is behind it is not answering. Expected to come back."""
    STALE = auto()
    """The last attempt failed - timeout, busy, another error. The value is the last good one."""
    MISSING = auto()
    """This unit does not have the register (0x02). Permanent until a rescan."""


@dataclass(frozen=True)
class DataValue[T]:
    """A point's value, how far it can be trusted, and when the device said it."""
    value: T | None
    """None unless the quality is GOOD, or STALE after a good value."""
    quality: Quality
    timestamp: datetime
    """When the device answered - timezone-aware UTC. For STALE, when it last answered."""
    raw: tuple[int, ...] = ()
    """What the device answered, or took in a write, in wire order, as the protocol counts it:
    registers, bits or bytes. Empty when it did not answer. Kept for NO_DATA too, so a state no
    enum names can still be told."""

    @property
    def is_good(self) -> bool:
        """Whether the device answered with a valid value."""
        return self.quality is Quality.GOOD


def stale(previous: DataValue[Any] | None, now: datetime) -> DataValue[Any]:
    """The last good value, marked STALE and keeping the time it was good."""
    if previous is not None and previous.quality in (Quality.GOOD, Quality.STALE):
        return DataValue(previous.value, Quality.STALE, previous.timestamp)
    return DataValue(None, Quality.STALE, now)
