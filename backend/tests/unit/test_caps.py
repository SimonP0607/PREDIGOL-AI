"""A player and his national team (plan F3, ``fbi.people.caps``): which sides count, whether he played, and the record before a match."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.people import caps
from fbi.people.caps import Cap, Profile, appeared, is_senior_national, is_youth, profile

T0 = datetime(2026, 3, 20, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize("name", ["Spain U21", "Brazil U-20", "Argentina Under 23", "Japan Olympic", "Germany U19 Women",
                                  "England U17", "Italy (U18)", "Mexico Olympics", "France under-21", "Colombia U23", "Spain U20"])
def test_youth_and_olympic_sides_are_recognised(name: str) -> None:
    assert is_youth(name)
    assert not is_senior_national(name, True)


@pytest.mark.parametrize("name", ["Spain", "Brazil", "Uruguay", "USA", "United Arab Emirates", "Austria W", "Costa Rica", "Ulster U Club"])
def test_senior_sides_are_not_taken_for_youth_ones(name: str) -> None:
    assert not is_youth(name)
    assert is_senior_national(name, True)


def test_only_a_side_known_to_be_national_counts() -> None:
    assert not is_senior_national("Spain", None), "not classified: not a national team"
    assert not is_senior_national("Spain", False)
    assert is_senior_national("Spain", True)


@pytest.mark.parametrize(("is_starter", "finished", "has_stats", "minutes", "want"), [
    (True, True, False, None, True),       # a starter of a finished match played, even before the statistics arrive
    (True, True, True, 90, True),
    (True, True, True, 0, False),           # unless the statistics say he never got on
    (True, False, False, None, None),       # nothing is known until the match is over
    (False, True, True, 25, True),          # a substitute who got on
    (False, True, True, 0, False),
    (False, True, True, None, False),       # listed in the statistics with no minutes: he stayed on the bench
    (False, True, False, None, None),       # no statistics at all yet: it cannot be said
    (False, False, True, 25, None),
])
def test_whether_he_played(is_starter: bool, finished: bool, has_stats: bool, minutes: int | None, want: bool | None) -> None:
    assert appeared(is_starter=is_starter, finished=finished, has_stats=has_stats, minutes=minutes) is want


def cap(n: int, *, starter: bool = True, played: bool | None = True, minutes: int | None = 90) -> Cap:
    return Cap(fixture_id=n, kickoff=T0 + timedelta(days=n), team_id=7, is_starter=starter, appeared=played, minutes=minutes)


def test_the_record_before_a_match() -> None:
    record = [cap(1), cap(2, starter=False, minutes=20), cap(3, starter=False, played=False, minutes=None), cap(4, played=None, minutes=None),
              cap(5), cap(6, played=None, minutes=None)]
    got = profile(record, before=T0 + timedelta(days=5))
    assert got == Profile(squads=4, caps=2, starts=1, minutes=110, unknown=1, last_squad=T0 + timedelta(days=4),
                          last_cap=T0 + timedelta(days=2))


def test_only_the_matches_he_played_have_minutes() -> None:
    record = [cap(1, minutes=90), cap(2, starter=False, played=False, minutes=30), cap(3, played=None, minutes=45)]
    assert profile(record, before=T0 + timedelta(days=9)).minutes == 90


def test_a_match_is_not_in_its_own_record() -> None:
    record = [cap(1), cap(2)]
    assert profile(record, before=T0 + timedelta(days=2)).squads == 1, "strictly before the kick-off"
    assert profile(record, before=T0 + timedelta(days=2, seconds=1)).squads == 2


def test_no_record_is_an_empty_profile() -> None:
    assert profile([], before=T0) == Profile(squads=0, caps=0, starts=0, minutes=0, unknown=0, last_squad=None, last_cap=None)
    assert caps.VERSION == "caps-v1"
