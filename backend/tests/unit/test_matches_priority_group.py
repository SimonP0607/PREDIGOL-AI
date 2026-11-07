"""GET /matches says each competition's priority group (UX-029, plan Partidos P1): the list orders by it.

The group is the owner's ``comp-priority-v1`` (``fbi.intel.day_priority``), read, never redefined here: LaLiga and the
Champions League are group 1, the club cups 2, the national-team tournaments 3, and «1. Division» (Cyprus) - which the
alphabet put above them - group 4.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from fbi.api.contracts.common import CompetitionRef
from fbi.api.services.matches import summary
from fbi.intel import day_priority

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=UTC)


def _row(provider_league_id: int, name: str) -> dict[str, Any]:
    return {
        "id": 1, "provider_fixture_id": 101, "kickoff_at": NOW + timedelta(hours=2), "status_short": "NS",
        "status_group": "scheduled", "round": "Regular Season - 12",
        "competition_id": 7, "competition_name": name, "competition_country": "Spain",
        "provider_league_id": provider_league_id, "season": 2026, "competition_type": "domestic_league",
        "is_tracked": True,
        "home_id": 10, "home_name": "Sevilla", "home_provider_id": 536,
        "away_id": 11, "away_name": "Betis", "away_provider_id": 543,
        "goals_home": None,
        "odds_snapshots": 0, "odds_bookmakers": 0, "odds_markets": 0, "odds_first_at": None, "odds_last_at": None,
        "near_close_snapshots": 0, "predictions": 0,
    }


@pytest.mark.parametrize(("league", "group"), [(140, 1), (2, 1), (3, 2), (32, 3), (318, 4)])
def test_each_competition_carries_the_owners_priority_group(league: int, group: int) -> None:
    out = summary(_row(league, "x"), NOW)
    assert out.competition.priority_group == group == day_priority.group_of(league)


def test_every_listed_league_has_its_group_and_any_other_is_four() -> None:
    for group, leagues in day_priority.GROUPS.items():
        for league in leagues:
            assert summary(_row(league, "x"), NOW).competition.priority_group == group
    assert summary(_row(999_999, "x"), NOW).competition.priority_group == day_priority.DEFAULT_GROUP == 4


def test_the_field_is_additive_and_bounded() -> None:
    ref = CompetitionRef(id=1, name="x", country=None, provider_league_id=1, season=2026, competition_type="cup",
                         is_tracked=False)
    assert ref.priority_group == 4
    with pytest.raises(ValidationError):
        CompetitionRef(id=1, name="x", country=None, provider_league_id=1, season=2026, competition_type="cup",
                       is_tracked=False, priority_group=5)
    schema = CompetitionRef.model_json_schema()["properties"]["priority_group"]
    assert schema["minimum"] == 1 and schema["maximum"] == 4 and "comp-priority-v1" in schema["description"]
