"""A point for tests: no protocol, only whether it can be read and written."""
from __future__ import annotations

from dataclasses import KW_ONLY, dataclass

from .._point import Point


@dataclass(frozen=True, eq=False)
class FakePoint[T](Point[T]):
    """A point that can be read, written, or both, as it is told, and lives nowhere."""
    _: KW_ONLY
    can_read: bool = True
    can_write: bool = False

    @property
    def readable(self) -> bool:
        """Whether it was told it can be read."""
        return self.can_read

    @property
    def writable(self) -> bool:
        """Whether it was told it can be written."""
        return self.can_write
