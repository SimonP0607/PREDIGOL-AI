"""Football-Data match statistics land in core.fixture_team_stats as observed:
blank stays NULL, an impossible value is dropped, a replay changes nothing and
an older download never overwrites a newer one."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import psycopg

from fbi.ingestion.historical_odds import MatchReport, OurFixture, write_matched_stats
from fbi.providers.football_data.parse import FDRow
from tests.integration.conftest import Seed

T = datetime(2025, 8, 20, 12, 0, tzinfo=UTC)


def _report(seed: Seed, home: dict[str, int | None], away: dict[str, int | None]) -> MatchReport:
    row = FDRow("E0", date(2025, 8, 16), "Home", "Away", 1, 0, (), home, away)
    ours = OurFixture(seed.fixture_id, date(2025, 8, 16), seed.home_team_id, "Home", seed.away_team_id, "Away", 1, 0)
    report = MatchReport()
    report.matched.append((row, ours))
    return report


def _rows(db: psycopg.Connection, seed: Seed) -> dict[str, tuple[object, ...]]:
    with db.cursor() as cur:
        cur.execute("SELECT team_side, shots, shots_on_target, corners, red_cards, fetched_at "
                    "FROM core.fixture_team_stats WHERE fixture_id = %s AND source = 'football-data.co.uk'",
                    (seed.fixture_id,))
        return {str(r[0]): tuple(r[1:]) for r in cur.fetchall()}


def test_statistics_are_written_as_observed(db: psycopg.Connection, seed: Seed) -> None:
    report = _report(seed, {"shots": 12, "shots_on_target": 15, "corners": None, "red_cards": 0},
                     {"shots": None, "shots_on_target": None})
    assert write_matched_stats(db, report, payload_hash=seed.payload_hash, fetched_at=T) == 1
    rows = _rows(db, seed)
    assert set(rows) == {"home"}, "a side with no statistic at all writes nothing"
    assert rows["home"][:4] == (12, None, None, 0), "on target above total is the source's error: dropped"


def test_replay_is_idempotent_and_older_data_never_wins(db: psycopg.Connection, seed: Seed) -> None:
    newer = _report(seed, {"shots": 12, "shots_on_target": 4}, {"shots": 9, "shots_on_target": 3})
    write_matched_stats(db, newer, payload_hash=seed.payload_hash, fetched_at=T)
    first = _rows(db, seed)
    write_matched_stats(db, newer, payload_hash=seed.payload_hash, fetched_at=T)
    assert _rows(db, seed) == first
    older = _report(seed, {"shots": 99, "shots_on_target": 1}, {"shots": 1, "shots_on_target": 0})
    write_matched_stats(db, older, payload_hash=seed.payload_hash, fetched_at=T - timedelta(days=3))
    assert _rows(db, seed) == first
