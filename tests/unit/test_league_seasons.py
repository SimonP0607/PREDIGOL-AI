"""Parsing /leagues: which season the provider calls current, and odds coverage.

Our catalogue came from a backup, so `is_current` drifts by a whole season every
August. This is the only thing that can correct it, and an empty answer from a
restricted plan is information, not a parse failure.
"""

from __future__ import annotations

from typing import Any

from fbi.providers.api_football.normalize import iter_league_seasons


def body(*seasons: tuple[int, bool, bool]) -> dict[str, Any]:
    return {
        "response": [
            {
                "league": {"id": 39, "name": "Premier League", "type": "League"},
                "country": {"name": "England"},
                "seasons": [
                    {
                        "year": year,
                        "start": f"{year}-08-15",
                        "end": f"{year + 1}-05-24",
                        "current": current,
                        "coverage": {
                            "fixtures": {"events": True, "statistics_fixtures": False},
                            "odds": odds,
                            "standings": True,
                        },
                    }
                    for year, current, odds in seasons
                ],
            }
        ],
        "errors": [],
    }


def test_the_current_season_is_identified_with_its_coverage() -> None:
    refs = list(iter_league_seasons(body((2025, False, True), (2026, True, True))))
    assert [(r.season, r.is_current) for r in refs] == [(2025, False), (2026, True)]
    current = next(r for r in refs if r.is_current)
    assert current.provider_league_id == 39
    assert current.has_odds and current.has_fixtures
    assert current.start_date == "2026-08-15" and current.end_date == "2027-05-24"


def test_a_season_without_odds_coverage_is_reported_as_such() -> None:
    """A season with fixtures but no odds cannot host a capture pilot, however
    many matches it has."""
    refs = list(iter_league_seasons(body((2026, True, False))))
    assert refs[0].has_odds is False
    assert refs[0].has_fixtures is True


def test_a_plan_that_exposes_no_current_season_yields_no_current_ref() -> None:
    """On a restricted plan the provider returns only the seasons that plan can
    see. None of them being current is the answer, not an error."""
    refs = list(iter_league_seasons(body((2021, False, True), (2022, False, True))))
    assert refs and not any(r.is_current for r in refs)


def test_malformed_payloads_yield_nothing_instead_of_raising() -> None:
    for bad in (
        {},
        {"response": None},
        {"response": [None]},
        {"response": [{"league": {"id": 39}, "seasons": None}]},
        {"response": [{"league": {}, "seasons": [{"year": 2026}]}]},
        {"response": [{"league": {"id": 39}, "seasons": [{"year": "soon"}]}]},
    ):
        assert list(iter_league_seasons(bad)) == []


def test_a_season_with_no_coverage_block_is_still_parsed() -> None:
    raw: dict[str, Any] = {
        "response": [{"league": {"id": 2}, "seasons": [{"year": 2026, "current": True}]}]
    }
    refs = list(iter_league_seasons(raw))
    assert len(refs) == 1
    assert refs[0].season == 2026 and refs[0].is_current
    assert refs[0].has_odds is False, "absent coverage means not covered, never assumed covered"
    assert refs[0].start_date is None
