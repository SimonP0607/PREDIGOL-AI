"""Plan F0, defect 10, on a built world: the packet does not present an incomplete calendar as complete.

Home's last RECORDED match is eight days before kick-off - but it also played a cup tie two days ago in a competition the
platform does not follow, so it is not rested. Away's last recorded match is two days before. The old packet claimed
"away has a rest disadvantage" (8.0 against 2.0); the real rests are 2.0 against 2.0 or less.
The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai.packet import PACKET_VERSION, PacketBuilder

from .conftest import Seed
from .helpers import scalar

AT = datetime(2032, 10, 5, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(hours=6)


def _world(db: psycopg.Connection[Any], seed: Seed, *, home_rest_days: float, away_rest_days: float) -> int:
    cur = db.cursor()
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                "competition_type, is_tracked) VALUES (98910, 'Calendar League', 'Colombia', 'league', 'club', "
                "'domestic_league', true) RETURNING id")
    comp = scalar(cur)
    cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2032, true) "
                "RETURNING id", (comp,))
    season = scalar(cur)
    teams = []
    for i in range(3):
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                    (989200 + i, f"Calendar {i}"))
        teams.append(scalar(cur))
    home, away, other = teams
    for n, (team, days) in enumerate(((home, home_rest_days), (away, away_rest_days))):
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                    "away_team_id, kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', "
                    "'finished')", (9892000 + n, season, team, other, KICKOFF - timedelta(days=days)))
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group) VALUES (9892100, %s, %s, %s, %s, 'NS', 'scheduled') "
                "RETURNING id", (season, home, away, KICKOFF))
    return int(scalar(cur))


def test_the_packet_says_the_calendar_is_incomplete_and_claims_no_rest_gap(db: psycopg.Connection[Any],
                                                                            seed: Seed) -> None:
    fixture = _world(db, seed, home_rest_days=8.0, away_rest_days=2.0)
    packet = PacketBuilder(db).build(fixture, at=AT)
    assert packet is not None and packet.version == PACKET_VERSION == "packet-v6"
    schedule = packet.content["schedule"]
    assert schedule["home"]["rest_days"] == 8.0 and schedule["away"]["rest_days"] == 2.0, "what is recorded stays"
    assert schedule["calendar"]["scope"] == "tracked_competitions" and schedule["calendar"]["complete"] is None
    assert schedule["calendar"]["rest_days"] == "at_most" and schedule["calendar"]["matches_last_14d"] == "at_least"
    assert schedule["flags"] == ["away_short_rest"], "a short rest survives; 'home is better rested' does not"
    assert "home_rest_disadvantage" not in schedule["flags"] and "away_rest_disadvantage" not in schedule["flags"]


def test_a_gap_that_used_to_be_flagged_is_not(db: psycopg.Connection[Any], seed: Seed) -> None:
    fixture = _world(db, seed, home_rest_days=3.5, away_rest_days=7.0)
    packet = PacketBuilder(db).build(fixture, at=AT)
    assert packet is not None
    assert packet.content["schedule"]["flags"] == [], "3.5 against 7.0 was 'home_rest_disadvantage'"
