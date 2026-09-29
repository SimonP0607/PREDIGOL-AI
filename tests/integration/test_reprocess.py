"""Re-deriving detail state from the raw store, without touching the provider.

core.fixture_detail_coverage arrived after 1,025 detail units had already run, so
it was empty for fixtures whose detail we DO have. Treating those as
never-fetched would have cost about a thousand requests and produced a worse
answer, because a re-fetch today cannot say what a payload contained last week.
The payloads are still on disk, so the table can be filled exactly.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from fbi.ingestion.payload_store import PayloadStore
from fbi.migration.completeness import fixtures_missing_detail
from fbi.ops.reprocess import reprocess_fixture_details
from tests.integration.conftest import Seed

FETCHED = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
LEAGUE = 39
SEASON = 2025


def detail_body(fixture_id: int, *, blocks: set[str], shots: int = 11, on_target: int = 4,
                starters: int = 11) -> dict:
    """A /fixtures?ids= response, shaped like the provider's."""
    entry: dict = {
        "fixture": {"id": fixture_id, "date": "2026-02-01T15:00:00+00:00",
                    "status": {"short": "FT"}},
        "league": {"id": LEAGUE, "season": SEASON},
        "teams": {"home": {"id": 501}, "away": {"id": 502}},
    }
    if "statistics" in blocks:
        entry["statistics"] = [
            {"team": {"id": 501}, "statistics": [{"type": "Total Shots", "value": shots},
                                                 {"type": "Shots on Goal", "value": on_target}]}
        ]
    if "events" in blocks:
        entry["events"] = [{"time": {"elapsed": 23, "extra": None}, "team": {"id": 501},
                            "player": {"id": 9001, "name": "A Player"},
                            "assist": {"id": None, "name": None}, "type": "Goal",
                            "detail": "Normal Goal", "comments": None}]
    if "lineups" in blocks:
        entry["lineups"] = [{
            "team": {"id": 501}, "formation": "4-3-3",
            "coach": {"id": 77, "name": "A Coach"},
            "startXI": [{"player": {"id": 8000 + n, "name": f"S{n}", "number": n + 1,
                                    "pos": "M", "grid": "2:1"}} for n in range(starters)],
            "substitutes": [{"player": {"id": 8100 + n, "name": f"B{n}", "number": 20 + n,
                                        "pos": "M", "grid": None}} for n in range(5)],
        }]
    if "players" in blocks:
        entry["players"] = [{
            "team": {"id": 501},
            "players": [{"player": {"id": 8000, "name": "S0"},
                         "statistics": [{"games": {"minutes": 90, "rating": "7.1",
                                                   "captain": False, "substitute": False}}]}],
        }]
    return {"response": [entry], "errors": [], "results": 1}


@pytest.fixture()
def raw_root(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.data_quality_issues")
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 83000 AND 83999")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE endpoint = '/fixtures' AND params ? 'ids'")
    db.commit()


def _store(db: psycopg.Connection, seed: Seed, raw_root: Path, body: dict, *,
           ids: str, fetched_at: datetime) -> str:
    """Put a payload in the raw store and index it, exactly as ingestion does."""
    store = PayloadStore(raw_root)
    stored = store.store(endpoint="/fixtures", params={"ids": ids}, fetched_at=fetched_at,
                         http_status=200, body=body)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, "
            " http_status, results_count, file_path, bytes) "
            "VALUES (%s,%s,'/fixtures',%s::jsonb,%s,200,1,%s,%s) ON CONFLICT (hash) DO NOTHING",
            (stored.hash, seed.run_id, json.dumps({"ids": ids}), fetched_at, stored.file_path,
             stored.bytes_written),
        )
    db.commit()
    return stored.hash


@pytest.fixture()
def fixture_83000(db: psycopg.Connection, seed: Seed) -> int:
    with db.cursor() as cur:
        cur.execute("UPDATE core.teams SET provider_team_id = 501 WHERE id = %s", (seed.home_team_id,))
        cur.execute("UPDATE core.teams SET provider_team_id = 502 WHERE id = %s", (seed.away_team_id,))
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
            "away_team_id, kickoff_at, status_short, status_group) "
            "VALUES (83000,%s,%s,%s,'2026-02-01T15:00Z','FT','finished') RETURNING id",
            (seed.season_id, seed.home_team_id, seed.away_team_id),
        )
        row = cur.fetchone()
    assert row is not None
    db.commit()
    return int(row[0])


def test_verify_only_writes_nothing(db: psycopg.Connection, seed: Seed, raw_root: Path,
                                    fixture_83000: int) -> None:
    payload_hash = _store(db, seed, raw_root, detail_body(83000, blocks={"statistics", "events"}),
                          ids="83000", fetched_at=FETCHED)
    report = reprocess_fixture_details(db, raw_root, apply=False, hashes=[payload_hash])
    assert (report.payloads_seen, report.payloads_applied, report.fixtures_touched) == (1, 1, 1)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_detail_coverage")
        assert cur.fetchone() == (0,)


def test_coverage_is_established_without_a_single_request(
    db: psycopg.Connection, seed: Seed, raw_root: Path, fixture_83000: int
) -> None:
    """The point of the exercise: what the provider sent, recorded from the bytes
    it sent, at no cost in quota."""
    _store(db, seed, raw_root, detail_body(83000, blocks={"statistics", "events"}),
           ids="83000", fetched_at=FETCHED)
    assert fixtures_missing_detail(db, league_id=LEAGUE, season=SEASON) == [83000]

    report = reprocess_fixture_details(db, raw_root, apply=True)
    assert report.coverage_rows == 4
    with db.cursor() as cur:
        cur.execute("SELECT dataset, block_present, rows_written FROM core.fixture_detail_coverage "
                    "ORDER BY dataset")
        assert cur.fetchall() == [("events", True, 1), ("lineups", False, 0),
                                  ("player_statistics", False, 0), ("team_statistics", True, 1)]
    assert fixtures_missing_detail(db, league_id=LEAGUE, season=SEASON) == [], \
        "the fixture has been fetched; what is absent is absent at the provider"


def test_replaying_recovers_the_issues_the_old_code_dropped(
    db: psycopg.Connection, seed: Seed, raw_root: Path, fixture_83000: int
) -> None:
    """A contradiction and a short line-up, both silently absorbed when the
    payload was first applied, both recoverable because the bytes were kept."""
    _store(db, seed, raw_root,
           detail_body(83000, blocks={"statistics", "lineups"}, shots=5, on_target=7, starters=9),
           ids="83000", fetched_at=FETCHED)
    reprocess_fixture_details(db, raw_root, apply=True)
    with db.cursor() as cur:
        cur.execute("SELECT code, field, observed, payload_hash IS NOT NULL "
                    "FROM audit.data_quality_issues ORDER BY code, field")
        rows = cur.fetchall()
    codes = {(c, f) for c, f, _o, _p in rows}
    assert ("PROVIDER_INCONSISTENCY", "shots_on_target") in codes
    assert ("INCOMPLETE_LINEUP", "starters") in codes
    assert all(has_payload for *_rest, has_payload in rows), \
        "every recovered issue names the payload it was read from"


def test_replaying_twice_changes_nothing(db: psycopg.Connection, seed: Seed, raw_root: Path,
                                         fixture_83000: int) -> None:
    _store(db, seed, raw_root, detail_body(83000, blocks={"statistics"}), ids="83000",
           fetched_at=FETCHED)
    first = reprocess_fixture_details(db, raw_root, apply=True)
    second = reprocess_fixture_details(db, raw_root, apply=True)
    assert first.coverage_rows == 4
    assert second.issues_opened == 0 and second.issues_seen_again > 0
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_detail_coverage")
        assert cur.fetchone() == (4,)


def test_the_newest_payload_wins_however_the_replay_is_ordered(
    db: psycopg.Connection, seed: Seed, raw_root: Path, fixture_83000: int
) -> None:
    """Payloads are replayed oldest first, so the state ends up as history left
    it: the later payload's line-ups block is what counts."""
    _store(db, seed, raw_root, detail_body(83000, blocks={"statistics"}), ids="83000",
           fetched_at=FETCHED)
    _store(db, seed, raw_root, detail_body(83000, blocks={"statistics", "lineups"}),
           ids="83000", fetched_at=FETCHED + timedelta(hours=2))
    reprocess_fixture_details(db, raw_root, apply=True)
    with db.cursor() as cur:
        cur.execute("SELECT block_present FROM core.fixture_detail_coverage WHERE dataset = 'lineups'")
        assert cur.fetchone() == (True,)


def test_a_payload_whose_file_is_gone_is_reported_not_skipped_silently(
    db: psycopg.Connection, seed: Seed, raw_root: Path, fixture_83000: int
) -> None:
    payload_hash = _store(db, seed, raw_root, detail_body(83000, blocks={"statistics"}),
                          ids="83000", fetched_at=FETCHED)
    with db.cursor() as cur:
        cur.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (payload_hash,))
        row = cur.fetchone()
    assert row is not None
    (raw_root / str(row[0])).unlink()
    report = reprocess_fixture_details(db, raw_root, apply=True)
    assert report.payloads_missing_file == 1
    assert "indexed but not in the raw store" in report.problems[0]


def test_a_tampered_file_is_refused(db: psycopg.Connection, seed: Seed, raw_root: Path,
                                    fixture_83000: int) -> None:
    """Re-deriving from RAW is only trustworthy if RAW is what it claims to be."""
    payload_hash = _store(db, seed, raw_root, detail_body(83000, blocks={"statistics"}),
                          ids="83000", fetched_at=FETCHED)
    with db.cursor() as cur:
        cur.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (payload_hash,))
        row = cur.fetchone()
    assert row is not None
    path = raw_root / str(row[0])
    body = detail_body(83000, blocks={"statistics"}, shots=999)
    store = PayloadStore(raw_root)
    envelope = store.load(str(row[0]))
    envelope["body"] = body
    import gzip
    path.write_bytes(gzip.compress(json.dumps(envelope).encode()))

    report = reprocess_fixture_details(db, raw_root, apply=True)
    assert report.payloads_not_rehashing == 1
    assert report.payloads_applied == 0
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_detail_coverage")
        assert cur.fetchone() == (0,), "nothing derived from bytes that are not the provider's"
