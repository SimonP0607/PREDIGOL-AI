"""The team list leads with the teams that play, not with names that sort first ("'t Zand", " Johnstone Burgh")."""

from __future__ import annotations

import psycopg

from fbi.api.repositories.catalog import list_teams
from tests.integration.conftest import Seed


def test_teams_with_matches_come_before_names_that_sort_first(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (990771, '''t Zand (no matches)')")
    rows = list_teams(db, q=None, competition_id=None, limit=500, offset=0)
    names = [r["name"] for r in rows]
    played = [r["name"] for r in rows if r["fixtures"] > 0]
    assert played and names.index(played[0]) < names.index("'t Zand (no matches)")
