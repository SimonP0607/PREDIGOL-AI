"""The odds probe's base query (BE-062, PM-04-03): a finished match whose row reached the base after its kick-off - a competition
tracked later, a friendly the provider listed after it was played - is counted apart, never as «not asked»."""

from __future__ import annotations

from datetime import timedelta

import psycopg
from psycopg.rows import dict_row
from scripts import coverage_probe as cp

from fbi.core.clock import now
from tests.integration.conftest import Seed


def test_late_rows_are_counted_apart(db: psycopg.Connection, seed: Seed) -> None:
    found = db.execute("SELECT c.provider_league_id FROM core.fixtures f JOIN core.competition_seasons cs "
                       "ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id "
                       "WHERE f.id = %s", (seed.fixture_id,)).fetchone()
    assert found is not None
    league = found[0]
    at = now()
    kickoff = at - timedelta(days=2)
    db.execute("UPDATE core.fixtures SET status_group = 'finished', kickoff_at = %s, created_at = %s WHERE id = %s",
               (kickoff, kickoff + timedelta(hours=3), seed.fixture_id))

    def base() -> dict[str, int]:
        with db.cursor(row_factory=dict_row) as cur:
            cur.execute(cp.ODDS_BASE_SQL, {"leagues": [league], "at": at, "days": cp.ODDS_DAYS, "lead": cp.ODDS_LEAD_MINUTES})
            (row,) = cur.fetchall()
            return {k: int(v) for k, v in row.items() if k != "league"}

    assert base() == {"finished": 0, "asked": 0, "asked_with_prices": 0, "with_closing": 0, "late": 1}
    db.execute("UPDATE core.fixtures SET created_at = %s WHERE id = %s", (kickoff - timedelta(days=5), seed.fixture_id))
    assert base() == {"finished": 1, "asked": 0, "asked_with_prices": 0, "with_closing": 0, "late": 0}
    db.rollback()
