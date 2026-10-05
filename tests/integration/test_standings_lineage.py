"""Standings lineage from RAW (scripts.repair_standings_lineage): a table snapshot written before revision 0048 is
traced only to a payload that reproduces it value for value - never to the nearest file by time alone."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fbi.ingestion.details import apply_standings
from fbi.ingestion.payload_store import PayloadStore
from fbi.providers.api_football.details import iter_standings
from tests.integration.conftest import Seed

T0 = datetime(2026, 9, 29, 4, 40, tzinfo=UTC)


def table(leader_points: int) -> dict[str, Any]:
    def row(rank: int, team: int, points: int, won: int, lost: int, gf: int, ga: int, form: str) -> dict[str, Any]:
        return {"rank": rank, "team": {"id": team}, "points": points, "group": "Premier League", "form": form,
                "all": {"played": 2, "win": won, "draw": 0, "lose": lost, "goals": {"for": gf, "against": ga}}}

    return {"response": [{"league": {"id": 39, "season": 2025, "standings": [[
        row(1, 33, leader_points, 2, 0, 4, 1, "WW"), row(2, 40, 3, 1, 1, 3, 3, "WL")]]}}]}


def test_a_snapshot_is_traced_only_to_the_payload_that_reproduces_it(db: psycopg.Connection, seed: Seed,
                                                                     tmp_path: Path) -> None:
    from scripts.repair_standings_lineage import repair

    body = table(6)
    stored = PayloadStore(tmp_path).store(endpoint="/standings", params={"league": 39, "season": 2025},
                                          fetched_at=T0, http_status=200, body=body)
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
               "results_count, file_path, bytes) VALUES (%s, %s, '/standings', %s, %s, 200, 1, %s, %s)",
               (stored.hash, seed.run_id, Jsonb({"league": "39", "season": "2025"}), T0, stored.file_path,
                stored.bytes_written))
    later = T0 + timedelta(hours=1)
    assert apply_standings(db, iter_standings(body), fetched_at=T0) == 2, "written as before 0048: no payload"
    assert apply_standings(db, iter_standings(table(7)), fetched_at=later) == 2, "a table no stored payload says"
    db.commit()
    try:
        dry = repair(db, tmp_path, apply=False)
        assert (dry.snapshots, dry.rows, dry.traced, len(dry.untraced)) == (2, 4, 1, 1)
        assert db.execute("SELECT count(*) FROM core.standings WHERE competition_season_id = %s "
                          "AND payload_hash IS NOT NULL", (seed.season_id,)).fetchone() == (0,), "a dry run writes nothing"
        done = repair(db, tmp_path, apply=True)
        assert (done.traced, done.rows_traced, done.exact_instant, done.problems) == (1, 2, 1, [])
        rows = db.execute("SELECT snapshot_at, payload_hash FROM core.standings WHERE competition_season_id = %s "
                          "ORDER BY snapshot_at, team_id", (seed.season_id,)).fetchall()
        assert rows == [(T0, stored.hash), (T0, stored.hash), (later, None), (later, None)]
        audit = db.execute("SELECT entity_id, provider_ref, before_value, after_value FROM audit.data_repairs "
                           "WHERE rule = 'standings_lineage'").fetchall()
        assert audit == [(seed.season_id, 39, None, stored.hash)]
        again = repair(db, tmp_path, apply=True)
        assert (again.snapshots, again.traced) == (1, 0), "idempotent: only the table no payload says is left"
    finally:
        db.rollback()
        db.execute("DELETE FROM audit.data_repairs WHERE rule = 'standings_lineage'")
        db.execute("DELETE FROM core.standings WHERE competition_season_id = %s AND snapshot_at IN (%s, %s)",
                   (seed.season_id, T0, later))
        db.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (stored.hash,))
        db.commit()
