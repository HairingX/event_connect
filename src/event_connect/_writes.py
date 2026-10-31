"""One write of a sequence."""
from __future__ import annotations

from dataclasses import dataclass

from ._key import Key


@dataclass(frozen=True)
class Write[T]:
    """One write of a sequence: `value` to the point `key` names."""
    key: Key[T]
    value: T
