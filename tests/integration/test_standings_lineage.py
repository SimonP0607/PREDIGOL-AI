"""Standings lineage from RAW (scripts.repair_standings_lineage): a table snapshot written before revision 0048 is
traced only to a payload whose rows it holds value for value - never to the nearest file by time alone - and a
snapshot the old writer left short (one row per team) is traced and reported, not filled in."""

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


def row(rank: int, team: int, points: int, won: int, lost: int, gf: int, ga: int, form: str) -> dict[str, Any]:
    return {"rank": rank, "team": {"id": team}, "points": points, "group": "Premier League", "form": form,
            "all": {"played": 2, "win": won, "draw": 0, "lose": lost, "goals": {"for": gf, "against": ga}}}


def answer(*tables: list[dict[str, Any]]) -> dict[str, Any]:
    return {"response": [{"league": {"id": 39, "season": 2025, "standings": list(tables)}}]}


def table(leader_points: int) -> dict[str, Any]:
    return answer([row(1, 33, leader_points, 2, 0, 4, 1, "WW"), row(2, 40, 3, 1, 1, 3, 3, "WL")])


def test_a_snapshot_is_traced_only_to_the_payload_whose_rows_it_holds(db: psycopg.Connection, seed: Seed,
                                                                      tmp_path: Path) -> None:
    from scripts.repair_standings_lineage import repair

    store = PayloadStore(tmp_path)
    later, short = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
    first = table(6)
    # Two tables under one label (the provider does this): the second is "Premier League #2" to the parser.
    two = answer([row(1, 33, 6, 2, 0, 4, 1, "WW"), row(2, 40, 3, 1, 1, 3, 3, "WL")],
                 [row(1, 33, 3, 1, 0, 2, 0, "W")])
    hashes = []
    for body, at in ((first, T0), (two, short)):
        stored = store.store(endpoint="/standings", params={"league": 39, "season": 2025}, fetched_at=at,
                             http_status=200, body=body)
        hashes.append(stored.hash)
        db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                   "results_count, file_path, bytes) VALUES (%s, %s, '/standings', %s, %s, 200, 1, %s, %s)",
                   (stored.hash, seed.run_id, Jsonb({"league": "39", "season": "2025"}), at, stored.file_path,
                    stored.bytes_written))
    assert apply_standings(db, iter_standings(first), fetched_at=T0) == 2, "written as before 0048: no payload"
    assert apply_standings(db, iter_standings(table(7)), fetched_at=later) == 2, "a table no stored payload says"
    # The pre-0048 writer kept one row per team: the second table's row was dropped.
    assert apply_standings(db, iter_standings(answer(two["response"][0]["league"]["standings"][0])),
                           fetched_at=short) == 2
    db.commit()
    try:
        dry = repair(db, tmp_path, apply=False)
        assert (dry.snapshots, dry.rows, dry.traced, len(dry.untraced)) == (3, 6, 2, 1)
        assert (dry.incomplete, dry.rows_missing, dry.exact_instant) == (1, 1, 2)
        assert db.execute("SELECT count(*) FROM core.standings WHERE competition_season_id = %s "
                          "AND payload_hash IS NOT NULL", (seed.season_id,)).fetchone() == (0,), \
            "a dry run writes nothing"
        done = repair(db, tmp_path, apply=True)
        assert (done.traced, done.rows_traced, done.problems) == (2, 4, [])
        rows = db.execute("SELECT snapshot_at, payload_hash FROM core.standings WHERE competition_season_id = %s "
                          "ORDER BY snapshot_at, team_id", (seed.season_id,)).fetchall()
        assert rows == [(T0, hashes[0]), (T0, hashes[0]), (later, None), (later, None),
                        (short, hashes[1]), (short, hashes[1])], "the short snapshot is traced, not filled in"
        audit = db.execute("SELECT entity_id, provider_ref, before_value, after_value, evidence LIKE '%%lacks 1%%' "
                           "FROM audit.data_repairs WHERE rule = 'standings_lineage' ORDER BY id").fetchall()
        assert audit == [(seed.season_id, 39, None, hashes[0], False), (seed.season_id, 39, None, hashes[1], True)]
        again = repair(db, tmp_path, apply=True)
        assert (again.snapshots, again.traced) == (1, 0), "idempotent: only the table no payload says is left"
    finally:
        db.rollback()
        db.execute("DELETE FROM audit.data_repairs WHERE rule = 'standings_lineage'")
        db.execute("DELETE FROM core.standings WHERE competition_season_id = %s AND snapshot_at IN (%s, %s, %s)",
                   (seed.season_id, T0, later, short))
        db.execute("DELETE FROM raw.ingestion_payloads WHERE hash = ANY(%s)", (hashes,))
        db.commit()
