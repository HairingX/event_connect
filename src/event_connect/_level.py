"""Which of a device's points are used: a level a consumer chooses, from the points that are
certain to those still being tried."""
from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from ._certainty import Certainty
from ._point import Point


class Level(StrEnum):
    """How certain a point must be to be used, and whether candidates are tried."""

    VERIFIED = "verified"
    """Only points read on a unit of the model."""
    DOCUMENTED = "documented"
    """Points read on a unit of the model, and points stated in its documentation."""
    TEST = "test"
    """Every point, whatever its certainty, with each candidate in place of the point it
    replaces."""

    def admits(self, certainty: Certainty) -> bool:
        """Whether a point of `certainty` is used at this level."""
        match self:
            case Level.VERIFIED:
                return certainty is Certainty.VERIFIED
            case Level.DOCUMENTED:
                return certainty in (Certainty.VERIFIED, Certainty.REPORTED)
            case Level.TEST:
                return True


def candidates_in_place[P: Point[Any]](points: Iterable[P], level: Level) -> tuple[P, ...]:
    """`points` as `level` has them, whatever their certainty, in the order given: at TEST every
    candidate, and no point a candidate among them replaces; below it, no candidate."""
    given = tuple(points)
    if level is not Level.TEST:
        return tuple(point for point in given if point.candidate is None)
    replaced = {point.candidate.replaces for point in given
                if point.candidate is not None and point.candidate.replaces is not None}
    return tuple(point for point in given if point.candidate is not None or point.key not in replaced)


def points_at[P: Point[Any]](points: Iterable[P], level: Level) -> tuple[P, ...]:
    """The points `level` uses, in the order given: those of `candidates_in_place` whose certainty
    it admits."""
    return tuple(point for point in candidates_in_place(points, level) if level.admits(point.certainty))
