"""A dropped signed metric comes back from RAW, with its trail; a row a newer payload owns is left alone."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from scripts.repair_signed_team_stats import repair

from fbi.ingestion.payload_store import PayloadStore
from tests.integration.conftest import Seed

FETCHED = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)


def test_goals_prevented_is_restored_from_the_payload_it_was_dropped_from(db: psycopg.Connection, seed: Seed,
                                                                           tmp_path: Path) -> None:
    pf, home, away = db.execute(
        "SELECT f.provider_fixture_id, th.provider_team_id, ta.provider_team_id FROM core.fixtures f "
        "JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id WHERE f.id = %s",
        (seed.fixture_id,)).fetchone()  # type: ignore[misc]
    body = {"response": [{"fixture": {"id": pf}, "statistics": [
        {"team": {"id": home}, "statistics": [{"type": "Total Shots", "value": 9},
                                              {"type": "goals_prevented", "value": -0.48}]},
        {"team": {"id": away}, "statistics": [{"type": "Total Shots", "value": 4},
                                              {"type": "goals_prevented", "value": "0.31"}]}]}]}
    store = PayloadStore(tmp_path)
    stored = store.store(endpoint="/fixtures", params={"ids": str(pf)}, fetched_at=FETCHED, http_status=200,
                         body=body)
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
               "VALUES (%s, %s, '/fixtures', %s, 200, %s, %s)",
               (stored.hash, seed.run_id, FETCHED, stored.file_path, stored.bytes_written))
    for side, shots, gp, dropped in (("home", 9, None, ["goals_prevented"]), ("away", 4, Decimal("0.31"), [])):
        db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, goals_prevented, "
                   "payload_hash, fetched_at, dropped_fields) VALUES (%s, %s, 'api-football', %s, %s, %s, %s, %s)",
                   (seed.fixture_id, side, shots, gp, stored.hash, FETCHED, dropped))
    db.execute("INSERT INTO audit.data_quality_issues (code, severity, entity_type, entity_id, provider_entity_id, "
               "payload_hash, field, observed, detail, fingerprint) VALUES ('PROVIDER_INCONSISTENCY', 'warning', "
               "'team_statistics', %s, %s, %s, 'goals_prevented', '-0.48', "
               "'goals_prevented arrived negative, which is not a statistic', 'signed-test')",
               (seed.fixture_id, home, stored.hash))

    report = repair(db, store)
    assert (report.rows, report.restored, report.unreadable, report.issues_resolved) == (1, 1, [], 1)
    row = db.execute("SELECT goals_prevented, dropped_fields FROM core.fixture_team_stats WHERE fixture_id = %s "
                     "AND team_side = 'home'", (seed.fixture_id,)).fetchone()
    assert row == (Decimal("-0.480"), [])
    trail = db.execute("SELECT before_value, after_value, evidence FROM audit.data_repairs "
                       "WHERE rule = 'team_stats_signed_metric' AND entity_id = %s", (seed.fixture_id,)).fetchone()
    assert trail is not None and trail[0] is None and trail[1] == "-0.48" and stored.hash in trail[2]
    status = db.execute("SELECT status, resolution FROM audit.data_quality_issues WHERE fingerprint = 'signed-test'"
                        ).fetchone()
    assert status is not None and status[0] == "resolved" and "signed" in status[1]
    again = repair(db, store)
    assert (again.rows, again.restored) == (0, 0), "idempotent"


def test_a_payload_whose_bytes_do_not_match_its_hash_is_not_used(db: psycopg.Connection, seed: Seed,
                                                                  tmp_path: Path) -> None:
    store = PayloadStore(tmp_path)
    stored = store.store(endpoint="/fixtures", params={"ids": "1"}, fetched_at=FETCHED, http_status=200,
                         body={"response": []})
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
               "VALUES ('not-the-hash-of-those-bytes', %s, '/fixtures', %s, 200, %s, 1)",
               (seed.run_id, FETCHED, stored.file_path))
    db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, payload_hash, fetched_at, "
               "dropped_fields) VALUES (%s, 'home', 'api-football', 3, 'not-the-hash-of-those-bytes', %s, "
               "'{goals_prevented}')", (seed.fixture_id, FETCHED))
    report = repair(db, store)
    assert report.restored == 0 and report.unreadable == ["not-the-hash"]
