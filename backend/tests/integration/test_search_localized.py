"""C-10 1.1 in the database (AP-B02, AP-B07, AP-E02): «España» finds the national team Spain by its Spanish name, the senior
team comes before a more popular age-group team unless the query asks for one, and «Mundial» finds the World Cup. The names
come in through the load of our own names (``store.sync_core``), the index is refreshed, and the test's transaction is rolled
back (the shared database keeps nothing of it)."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.contracts.intelligence.search import SearchV2, SearchV2Private
from fbi.api.services import search_v2 as service
from fbi.people.identity import store
from tests.integration.helpers import scalar

pytestmark = pytest.mark.integration
_id = itertools.count(7_200_000)


@pytest.fixture
def db(migrated_database: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(migrated_database) as conn:
        yield conn
        conn.rollback()


def one(db: psycopg.Connection[Any], sql: str, *params: object) -> int:
    return int(scalar(db.execute(sql, params)))


def team(db: psycopg.Connection[Any], name: str) -> int:
    return one(db, "INSERT INTO core.teams (provider_team_id, name, country, is_national) VALUES (%s, %s, 'Spain', true) "
                   "RETURNING id", next(_id), name)


def national(answer: SearchV2Private) -> list[tuple[str, str]]:
    return [(h.label, h.matched) for h in answer.groups.national_teams.items]


def test_spanish_names_find_the_national_team_and_the_senior_one_comes_first(db: psycopg.Connection[Any]) -> None:
    senior, under21 = team(db, "Spain"), team(db, "Spain U21")
    rival = team(db, "Sampleland U21")
    league = one(db, "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, "
                     "is_tracked) VALUES (%s, 'UEFA U21 Championship', 'World', 'cup', 'national_team', 'international', "
                     "true) RETURNING id", next(_id))
    world_cup = one(db, "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                        "competition_type) VALUES (%s, 'World Cup', 'World', 'cup', 'national_team', 'international') "
                        "RETURNING id", next(_id))
    season = one(db, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", league)
    start = datetime.now(UTC) - timedelta(days=200)
    for n in range(30):  # the under-21 team is far more popular than the senior one (30 tracked matches against 0)
        db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                   "kickoff_at) VALUES (%s, %s, %s, %s, %s)", (next(_id), season, under21, rival, start + timedelta(days=n)))
    store.sync_core(db, actor="test")
    db.execute("REFRESH MATERIALIZED VIEW core.search_entries")

    found = service.build(db, "España")
    assert national(found)[:2] == [("Spain", "España"), ("Spain U21", "España Sub-21")]
    hits = found.groups.national_teams.items
    assert hits[0].alias_type == "localized" and hits[0].id == senior
    assert hits[1].rank > hits[0].rank, "without the rule the popular under-21 team would come first"

    asked = service.build(db, "España Sub-21")
    assert national(asked)[0] == ("Spain U21", "España Sub-21")
    assert national(service.build(db, "spain"))[0][0] == "Spain"

    cup = service.build(db, "Mundial")
    assert [(h.id, h.matched, h.alias_type) for h in cup.groups.competitions.items] == [(world_cup, "Mundial", "localized")]

    public = to_public(found, SearchV2).model_dump(mode="json")
    assert leaks(public, public_schema=SearchV2.model_json_schema(mode="serialization"),
                 private_schema=SearchV2Private.model_json_schema(mode="serialization")) == []
    assert public["contract_version"] == "1.1.0"
