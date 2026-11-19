"""Which points a level uses: by their certainty, and with candidates only at the Test level."""
from __future__ import annotations

from enum import IntEnum
from typing import Any

import pytest

from event_connect import Candidate, Certainty, Key, Level, PollRate, candidates_in_place, points_at
from event_connect.testing import FakePoint


class Coil(IntEnum):
    NONE = 0
    REHEAT = 1


REHEAT = Key("reheat", bool)
COIL = Key("coil", Coil)
PREHEAT = Key("preheat", bool)
AIR = Key("air", int)


def _point(key: Key[Any], certainty: Certainty = Certainty.REPORTED,
           candidate: Candidate | None = None) -> FakePoint[Any]:
    return FakePoint(key, poll_rate=PollRate.MEDIUM, certainty=certainty, candidate=candidate)


def _keys(points: tuple[FakePoint[Any], ...]) -> list[str]:
    return [str(point.key) for point in points]


# ================================================================================ certainty


@pytest.mark.parametrize(("level", "admitted"), [
    (Level.VERIFIED, {Certainty.VERIFIED}),
    (Level.DOCUMENTED, {Certainty.VERIFIED, Certainty.REPORTED}),
    (Level.TEST, set(Certainty)),
])
def test_a_level_admits_the_certainties_it_names(level: Level, admitted: set[Certainty]) -> None:
    assert {certainty for certainty in Certainty if level.admits(certainty)} == admitted


def test_a_level_is_stored_and_read_back_by_its_text() -> None:
    assert [str(level) for level in Level] == ["verified", "documented", "test"]
    assert Level("documented") is Level.DOCUMENTED


def test_each_level_uses_the_points_of_the_certainties_it_admits_in_the_order_given() -> None:
    points = (_point(Key("guess", int), Certainty.INFERRED), _point(Key("seen", int), Certainty.VERIFIED),
              _point(Key("stated", int)))
    assert _keys(points_at(points, Level.VERIFIED)) == ["seen"]
    assert _keys(points_at(points, Level.DOCUMENTED)) == ["seen", "stated"]
    assert _keys(points_at(points, Level.TEST)) == ["guess", "seen", "stated"]


# =============================================================================== candidates


def test_below_the_test_level_no_candidate_is_used_and_the_point_it_replaces_is() -> None:
    points = (_point(REHEAT), _point(COIL, candidate=Candidate(replaces=REHEAT)), _point(AIR, candidate=Candidate()))
    for level in (Level.VERIFIED, Level.DOCUMENTED):
        assert _keys(candidates_in_place(points, level)) == ["reheat"]
    assert _keys(points_at(points, Level.DOCUMENTED)) == ["reheat"]


def test_at_the_test_level_a_candidate_takes_the_place_of_the_point_it_replaces() -> None:
    points = (_point(REHEAT), _point(PREHEAT), _point(COIL, candidate=Candidate(replaces=REHEAT)),
              _point(AIR, candidate=Candidate()))
    assert _keys(points_at(points, Level.TEST)) == ["preheat", "coil", "air"]


def test_a_candidate_of_the_same_key_reads_it_from_its_own_place() -> None:
    today = _point(PREHEAT)
    candidate = _point(PREHEAT, candidate=Candidate(replaces=PREHEAT))
    assert points_at((today, candidate), Level.DOCUMENTED) == (today,)
    assert points_at((today, candidate), Level.TEST) == (candidate,)


def test_a_candidate_replacing_a_key_none_of_the_points_has_replaces_nothing() -> None:
    points = (_point(PREHEAT), _point(COIL, candidate=Candidate(replaces=REHEAT)))
    assert _keys(points_at(points, Level.TEST)) == ["preheat", "coil"]


def test_candidates_in_place_keeps_every_certainty_and_points_at_leaves_out_what_the_level_does_not_admit() -> None:
    points = (_point(REHEAT, Certainty.INFERRED), _point(COIL, Certainty.INFERRED, Candidate(replaces=REHEAT)),
              _point(AIR, Certainty.VERIFIED))
    assert _keys(candidates_in_place(points, Level.VERIFIED)) == ["reheat", "air"]
    assert _keys(points_at(points, Level.VERIFIED)) == ["air"]
    assert _keys(points_at(points, Level.TEST)) == ["coil", "air"]


def test_a_point_is_no_candidate_unless_it_says_so() -> None:
    assert _point(REHEAT).candidate is None


@pytest.mark.parametrize("replaces", ["reheat", Key("", bool), Key(" reheat", bool)])
def test_a_candidate_replaces_a_point_by_a_clean_key(replaces: Any) -> None:
    with pytest.raises(ValueError, match="a candidate replaces a point by its Key"):
        _point(COIL, candidate=Candidate(replaces=replaces))
