"""How certain it is that a point is what its model says."""
from __future__ import annotations

from enum import StrEnum


class Certainty(StrEnum):
    """How certain it is that a point's place, conversion and meaning are right."""

    VERIFIED = "verified"
    """Read on a unit of the model."""
    REPORTED = "reported"
    """Stated in documentation of the model; not read on a unit of it."""
    INFERRED = "inferred"
    """Worked out from documentation that does not state it, such as the order of a group of
    points; not read on a unit of the model, and not stated anywhere."""
