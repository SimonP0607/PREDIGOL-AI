"""REVIEW PREDIGOL (11 Oct 2026), P0 - what the Match Center shows must be right before it is pretty:

* one statistics source per match (5.329 matches have rows from API-Football AND football-data.co.uk; the page got
  four rows for two teams);
* before a match is over, only the provider's CURRENT absences (a player the newest /injuries answer no longer names
  is not out any more); after it, every absence reported for it;
* every empty section carries a code the page can translate and weigh;
* the line-ups reason depends on how close the kick-off is ("about an hour before" is wrong 13 minutes before).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg

from fbi.api.services.center import lineups_reason, match_center
from tests.integration.conftest import Seed

KO = datetime(2026, 10, 10, 16, 30, tzinfo=UTC)


def _payload(db: psycopg.Connection, seed: Seed, h: str, at: datetime) -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, fetched_at, http_status, "
               "results_count, file_path, bytes) VALUES (%s, %s, 'api_football', '/injuries', '{}'::jsonb, %s, 200, 1, "
               "'x', 1) ON CONFLICT DO NOTHING", (h, seed.run_id, at))
    return h


def _fixture(db: psycopg.Connection, seed: Seed, *, status: str, group: str) -> tuple[int, int, int]:
    db.execute("UPDATE core.fixtures SET status_short = %s, status_group = %s WHERE id = %s",
               (status, group, seed.fixture_id))
    row = db.execute("SELECT f.provider_fixture_id, th.provider_team_id, ta.provider_team_id FROM core.fixtures f "
                     "JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id "
                     "WHERE f.id = %s", (seed.fixture_id,)).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


def test_one_statistics_source_per_match_api_football_first(db: psycopg.Connection, seed: Seed) -> None:
    _fixture(db, seed, status="FT", group="finished")
    for side, shots in (("home", 14), ("away", 9)):
        db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, possession_pct, "
                   "payload_hash, fetched_at) VALUES (%s, %s, 'api-football', %s, 55, %s, now())",
                   (seed.fixture_id, side, shots, seed.payload_hash))
        db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, payload_hash, fetched_at) "
                   "VALUES (%s, %s, 'football-data.co.uk', %s, %s, now() + interval '1 day')",
                   (seed.fixture_id, side, shots + 1, seed.payload_hash))
    center = match_center(db, seed.fixture_id).data
    assert center is not None
    stats = center.statistics.data
    assert [(s.side, s.shots, s.source) for s in stats] == [("home", 14, "api-football"), ("away", 9, "api-football")]
    assert all(s.possession_pct is not None for s in stats), "the source with possession, not the empty one"


def test_only_the_current_absences_before_the_match_every_one_after(db: psycopg.Connection, seed: Seed) -> None:
    pfid, home_pid, _ = _fixture(db, seed, status="NS", group="scheduled")
    old = _payload(db, seed, "inj-old", KO - timedelta(days=2))
    new = _payload(db, seed, "inj-new", KO - timedelta(hours=5))
    for player, h, at in ((9001, old, KO - timedelta(days=2)), (9002, new, KO - timedelta(hours=5))):
        db.execute("INSERT INTO core.player_absences (source, provider_fixture_id, provider_player_id, fixture_id, "
                   "provider_team_id, player_name, absence_type, reason, payload_hash, fetched_at) VALUES "
                   "('api-football', %s, %s, %s, %s, %s, 'Missing Fixture', 'Knee Injury', %s, %s)",
                   (pfid, player, seed.fixture_id, home_pid, f"Player {player}", h, at))
    db.execute("INSERT INTO core.context_checks (competition_season_id, dataset, checked_at, payload_hash, rows_seen, "
               "changed_at) VALUES (%s, 'injuries', %s, %s, 1, %s) ON CONFLICT (competition_season_id, dataset) DO "
               "UPDATE SET payload_hash = EXCLUDED.payload_hash, checked_at = EXCLUDED.checked_at",
               (seed.season_id, KO - timedelta(hours=1), new, KO - timedelta(hours=5)))
    before = match_center(db, seed.fixture_id).data
    assert before is not None
    assert [a.player for a in before.absences.data] == ["Player 9002"], "9001 is not in the newest answer any more"
    assert before.absences.data[0].side == "home" and before.absences.data[0].fetched_at is not None

    _fixture(db, seed, status="FT", group="finished")
    after = match_center(db, seed.fixture_id).data
    assert after is not None
    assert sorted(a.player or "" for a in after.absences.data) == ["Player 9001", "Player 9002"], (
        "after the match: every absence reported for it")


def test_empty_sections_carry_a_code() -> None:
    from fbi.api.services.center import _sec
    s = _sec([], "nothing", code="no_h2h")
    assert (s.status.value, s.reason, s.code) == ("empty", "nothing", "no_h2h")


def test_the_lineups_reason_depends_on_the_kickoff() -> None:
    """REVIEW point 7: 13 minutes before kick-off "usually about an hour before" is wrong."""
    assert lineups_reason(KO, "scheduled", KO - timedelta(hours=3))[1] == "lineups_usually_60m"
    assert lineups_reason(KO, "scheduled", KO - timedelta(minutes=13))[1] == "lineups_not_published"
    assert lineups_reason(KO, "scheduled", KO + timedelta(minutes=5))[1] == "lineups_not_published"
    assert lineups_reason(KO, "live", KO + timedelta(minutes=30))[1] == "lineups_none"
