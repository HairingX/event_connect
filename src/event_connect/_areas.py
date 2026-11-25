"""Raw reads of a device's address areas, register by register, and what changed between two."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import NamedTuple


@dataclass(frozen=True)
class Area:
    """A run of `count` registers of one address space from number `start`, read as raw numbers.

    `space` is the protocol's own name for the address space, such as "input", "holding",
    "datapoint" or "setpoint"; the numbers are those the device's model gives its points.

    Raises:
        ValueError: the space is empty, `start` is negative, or `count` is below 1.
    """
    space: str
    start: int
    count: int

    def __post_init__(self) -> None:
        if not self.space:
            raise ValueError("an area's space must not be empty")
        if self.start < 0:
            raise ValueError(f"an area cannot start below 0, got {self.start}")
        if self.count < 1:
            raise ValueError(f"an area holds at least one register, got {self.count}")

    @property
    def end(self) -> int:
        """The first number after the area."""
        return self.start + self.count

    def addresses(self) -> tuple[RawAddress, ...]:
        """Every register of the area, in order."""
        return tuple(RawAddress(self.space, number) for number in range(self.start, self.end))

    def __str__(self) -> str:
        return f"{self.space} {self.start}-{self.end - 1}" if self.count > 1 else f"{self.space} {self.start}"


class RawAddress(NamedTuple):
    """One register: its address space, as an `Area` names it, and its number."""
    space: str
    number: int

    def __str__(self) -> str:
        return f"{self.space} {self.number}"


@dataclass(frozen=True)
class Snapshot:
    """What one read of areas found: the register word at each address the device has, and the
    addresses it said it has none at.

    Raises:
        ValueError: `taken_at` is not timezone-aware UTC, an address is both read and missing, or
            a word is outside 0-65535.
    """
    taken_at: datetime
    """When the read ended - timezone-aware UTC."""
    values: Mapping[RawAddress, int]
    """The word read at each address."""
    missing: frozenset[RawAddress]
    """The addresses the device said it has none at."""

    def __init__(self, taken_at: datetime, values: Mapping[RawAddress, int], missing: Iterable[RawAddress]) -> None:
        if taken_at.utcoffset() != timedelta(0):
            raise ValueError(f"taken_at must be timezone-aware UTC, got {taken_at.isoformat()}")
        object.__setattr__(self, "taken_at", taken_at)
        object.__setattr__(self, "values", MappingProxyType(dict(values)))
        object.__setattr__(self, "missing", frozenset(missing))
        both = sorted(self.missing.intersection(self.values))
        if both:
            raise ValueError(f"read and missing at once: {', '.join(map(str, both))}")
        outside = sorted(address for address, word in self.values.items() if not 0 <= word <= 0xFFFF)
        if outside:
            raise ValueError(f"words outside 0-65535 at {', '.join(map(str, outside))}")

    def as_plain(self) -> dict[str, object]:
        """The snapshot as plain data: the time in ISO 8601; by space, each word by its number's
        text, and the missing numbers in order."""
        values: dict[str, dict[str, int]] = {}
        for address, word in sorted(self.values.items()):
            values.setdefault(address.space, {})[str(address.number)] = word
        missing: dict[str, list[int]] = {}
        for address in sorted(self.missing):
            missing.setdefault(address.space, []).append(address.number)
        return {"taken_at": self.taken_at.isoformat(), "values": values, "missing": missing}


@dataclass(frozen=True)
class RegisterChange:
    """One register that differs between two snapshots; None where the device had none."""
    address: RawAddress
    before: int | None
    after: int | None
    bits: tuple[int, ...]
    """The bits that flipped, the lowest first, counted from 0; none unless both are words."""

    def as_plain(self) -> dict[str, object]:
        """The change as plain data."""
        return {"space": self.address.space, "number": self.address.number, "before": self.before,
                "after": self.after, "bits": list(self.bits)}


def difference(before: Snapshot, after: Snapshot) -> tuple[RegisterChange, ...]:
    """Every register both snapshots read, as a word or as missing, that differs between them;
    ordered by space, then number."""
    read_before = before.missing.union(before.values)
    changes: list[RegisterChange] = []
    for address in sorted(after.missing.union(after.values).intersection(read_before)):
        old, new = before.values.get(address), after.values.get(address)
        if old != new:
            changes.append(RegisterChange(address, old, new, _flipped(old, new)))
    return tuple(changes)


def _flipped(before: int | None, after: int | None) -> tuple[int, ...]:
    if before is None or after is None:
        return ()
    differ = before ^ after
    return tuple(bit for bit in range(differ.bit_length()) if differ >> bit & 1)
