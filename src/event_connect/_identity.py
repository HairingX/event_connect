"""What a device reports about itself."""
from __future__ import annotations

from collections.abc import Mapping

Identity = Mapping[str, int | float | str | bool | None]
"""What a device reports about itself, by name: such as its type, serial number or firmware."""
