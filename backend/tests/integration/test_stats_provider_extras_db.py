"""PM-05-05 (BE-068) against a real database: with the extras asked for, the pass reads ``core.fixture_player_extras`` (the latest row of
each player and match) and the team's offsides and goals prevented, and C-13 reads the figures back; without them nothing changes."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.services import stats_profile
from fbi.stats import data as sd
from fbi.stats import job

from .conftest import Seed
from .test_stats_documents_db import T0, _league, _season


def _players(db: psycopg.Connection[Any], seed: Seed, cs: int) -> int:
    """A forward of the home side in every match, with his line and - twice, the newer one counting - his extras."""
    cur = db.cursor()
    cur.execute("INSERT INTO core.players (provider_player_id, name, position) VALUES (987500, 'Delantero EA', 'Attacker') RETURNING id")
    pid = cur.fetchone()[0]  # type: ignore[index]
    cur.execute("SELECT id, kickoff_at FROM core.fixtures WHERE competition_season_id = %s AND status_group = 'finished'", (cs,))
    for fid, ko in cur.fetchall():
        cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, player_name, minutes, "
                    "is_substitute, goals, payload_hash, fetched_at) VALUES (%s, 'api-football', 987500, 'home', 'Delantero EA', 90, "
                    "false, 1, %s, %s)", (fid, seed.payload_hash, ko))
        for hours, offsides in ((3, 5), (4, 1)):
            cur.execute("INSERT INTO core.fixture_player_extras (fixture_id, provider_player_id, observed_at, team_side, offsides, "
                        "dribbled_past, penalties_won, penalties_committed, penalties_saved, payload_hash, normalizer_version) "
                        "VALUES (%s, 987500, %s, 'home', %s, 2, 0, 0, NULL, %s, 't')", (fid, ko + timedelta(hours=hours), offsides,
                                                                                       seed.payload_hash))
    db.execute("UPDATE core.fixture_team_stats SET offsides = 2, goals_prevented = 0.5 WHERE fixture_id IN "
               "(SELECT id FROM core.fixtures WHERE competition_season_id = %s)", (cs,))
    return int(pid)


def test_the_extras_are_read_and_served_only_when_asked(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, ids, _ = _league(db, seed)
    pid = _players(db, seed, cs)
    season = _season(db, cs)
    plain = sd.load_season(db, season)
    assert "offsides" not in plain.players[0].counts, "off: the player lines are what they were"
    assert plain.matches[0].team_stats["home"]["offsides"] == 2.0
    data = sd.load_season(db, season, extras=True)
    assert data.players[0].counts["offsides"] == 1.0, "the latest extras of the match"
    job.write_season(db, data, 7, T0 + timedelta(days=120), extras=True, goals_prevented=True)
    at = T0 + timedelta(days=120, hours=1)
    player = stats_profile.build_player(db, pid, at=at).entities[0].player
    assert not isinstance(player, Missing)
    got = {f.key: f for f in player.provider_extras}
    assert got["offsides"].value == pytest.approx(1.0) and got["dribbled_past"].value == pytest.approx(2.0)
    assert got["offsides"].origin == "api_football" and got["offsides"].matches_with_data == 90
    team = stats_profile.build_team(db, ids[0], scope="season", context="all", at=at).entities[0].team
    assert not isinstance(team, Missing)
    assert {f.key: f.value for f in team.provider_extras} == {"offsides": 2.0, "goals_prevented": 0.5}
    job.write_season(db, plain, 8, T0 + timedelta(days=121))
    team = stats_profile.build_team(db, ids[0], scope="season", context="all", at=at + timedelta(days=1)).entities[0].team
    assert not isinstance(team, Missing) and team.provider_extras == [], "off again: the documents of before"


def test_the_goals_prevented_probe_reads_the_stored_figures(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import goals_prevented_probe as probe

    cs, _ids, _ = _league(db, seed)
    # coherent with the opponent's xG minus the goals conceded (home: 0.8 - 1 = -0.2; away: 1.7 - 2 = -0.3), a little noise
    db.execute("UPDATE core.fixture_team_stats s SET goals_prevented = CASE WHEN s.team_side = 'home' THEN -0.1 ELSE -0.4 END "
               "WHERE fixture_id IN (SELECT id FROM core.fixtures WHERE competition_season_id = %s)", (cs,))
    db.execute("UPDATE core.fixtures SET kickoff_at = now() - interval '10 days' WHERE competition_season_id = %s "
               "AND status_group = 'finished'", (cs,))
    with db.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(probe.PROBE_SQL, {"days": 60, "near": probe.NEAR_ZERO, "max_abs": probe.MAX_ABS})
        row = dict(cur.fetchone() or {})
    assert row["with_gp"] == row["both"] == 180 and row["out_of_range"] == 0
    assert float(row["sign_agreement"]) == 1.0
    got = probe.verdict(row)
    assert got["verdict"] == "FAIL" and any("muestra" in r for r in got["reasons"]), "180 < 200: never published on a small sample"
