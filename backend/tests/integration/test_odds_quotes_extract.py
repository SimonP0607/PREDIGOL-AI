"""The price clock against a real PostgreSQL: RAW /odds payloads become structured quotes, once (plan F1)."""

from __future__ import annotations

import copy
import gzip
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.odds.quote_extract import (
    EXTRACTOR_VERSION,
    LOCK_KEY,
    RETRY_AFTER,
    backlog,
    pending_payloads,
    run_extraction,
    sample_extraction,
)
from fbi.odds.quote_taxonomy import (
    TAXONOMY_VERSION,
    extracted_specs,
    known_bet_ids,
    sync_definitions,
)
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_rejected, scalar

CONTRACT = Path(__file__).parents[1] / "fixtures" / "contracts" / "odds_prematch.json"
KICKOFF = datetime(2026, 10, 12, 19, 0, tzinfo=UTC)
FETCHED = KICKOFF - timedelta(hours=5)
WINDOW: dict[str, Any] = {"since": datetime(2026, 10, 10, tzinfo=UTC), "until": datetime(2026, 10, 14, tzinfo=UTC)}
"""The shared test database keeps whatever other tests committed: these tests look only at their own days."""


def real_body(provider_fixture_id: int, kickoff: datetime = KICKOFF, *, update: datetime | None = None) -> dict[str, Any]:
    body: dict[str, Any] = copy.deepcopy(json.loads(CONTRACT.read_text())["body"])
    entry = body["response"][0]
    entry["fixture"]["id"] = provider_fixture_id
    entry["fixture"]["date"] = kickoff.isoformat()
    entry["fixture"]["timestamp"] = int(kickoff.timestamp())
    entry["update"] = (update or kickoff - timedelta(days=1)).isoformat()
    return body


def small_body(provider_fixture_id: int, *bets: dict[str, Any], kickoff: datetime = KICKOFF, book: tuple[int, str] = (8, "Bet365"),
               update: datetime | None = None) -> dict[str, Any]:
    return {"get": "odds", "results": 1, "response": [{
        "fixture": {"id": provider_fixture_id, "date": kickoff.isoformat(), "timestamp": int(kickoff.timestamp())},
        "update": (update or kickoff - timedelta(days=1)).isoformat(),
        "bookmakers": [{"id": book[0], "name": book[1], "bets": list(bets)}],
    }]}


def bet(bet_id: int, name: str, *values: tuple[str, str]) -> dict[str, Any]:
    return {"id": bet_id, "name": name, "values": [{"value": v, "odd": o} for v, o in values]}


def add_fixture(db: psycopg.Connection, seed: Seed, provider_fixture_id: int, kickoff: datetime = KICKOFF) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (provider_fixture_id, seed.season_id, seed.home_team_id, seed.away_team_id, kickoff))
        return int(scalar(cur))


def add_payload(db: psycopg.Connection, seed: Seed, store: PayloadStore, body: dict[str, Any], *, fixture: int,
                fetched_at: datetime = FETCHED, page: int | None = 1, results: int = 1) -> str:
    params: dict[str, Any] = {"fixture": fixture}
    if page is not None:
        params["page"] = page
    stored = store.store(endpoint="/odds", params=params, fetched_at=fetched_at, http_status=200, body=body)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, results_count, "
            " file_path, bytes) VALUES (%s, %s, '/odds', %s::jsonb, %s, 200, %s, %s, %s)",
            (stored.hash, seed.run_id, json.dumps({k: str(v) for k, v in params.items()}), fetched_at, results,
             stored.file_path, stored.bytes_written))
    return stored.hash


def run(db: psycopg.Connection, root: Path, **kw: Any) -> Any:
    kw.setdefault("limit", 100)
    return run_extraction(db, root, commit=False, **WINDOW, **kw)


def ledger(db: psycopg.Connection, payload_hash: str) -> dict[str, Any]:
    with db.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("SELECT * FROM market.odds_extractions WHERE payload_hash = %s", (payload_hash,))
        row = cur.fetchone()
    assert row is not None, "no ledger row"
    return dict(row)


def count(db: psycopg.Connection, sql: str, *args: object) -> int:
    with db.cursor() as cur:
        cur.execute(sql, args)
        return int(scalar(cur))


# ── the migration ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_migration_creates_the_four_tables_and_the_partitions(db: psycopg.Connection) -> None:
    for table in ("market_families", "market_definitions", "odds_extractions", "odds_quotes"):
        assert count(db, "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'market' AND table_name = %s",
                     table) == 1, table
    assert count(db, "SELECT count(*) FROM market.market_families") == 16
    parts = count(db, "SELECT count(*) FROM pg_inherits WHERE inhparent = 'market.odds_quotes'::regclass")
    assert parts == 8, "seven monthly partitions (2026-09 .. 2027-03) and the default one"


def test_the_quotes_table_refuses_what_a_quote_cannot_be(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810001)
    body = small_body(810001, bet(45, "Corners Over Under", ("Over 9.5", "1.90")))
    add_payload(db, seed, PayloadStore(tmp_path), body, fixture=810001)
    assert run(db, tmp_path).quotes_written == 1
    with db.cursor() as cur:
        cur.execute("SELECT fixture_id, bookmaker_id, definition_id, extraction_id FROM market.odds_quotes")
        fixture_id, bookmaker_id, definition_id, extraction_id = cur.fetchone()  # type: ignore[misc]
    insert = ("INSERT INTO market.odds_quotes (fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, "
              " captured_at, minutes_to_ko, extraction_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")
    base = [fixture_id, bookmaker_id, definition_id, "Over", "10.5", "1.9", FETCHED, 60, extraction_id]

    def with_(index: int, value: object) -> list[object]:
        row: list[object] = list(base)
        row[index] = value
        return row

    for index, value, why in ((5, "1.0", "odds of exactly 1 are not a price"), (5, "1000", "odds of 1000 or more are refused"),
                              (4, "10.3", "a line is a multiple of a quarter"), (3, "x" * 61, "a selection fits its column"),
                              (7, -1, "minutes to kick-off are never negative")):
        with must_be_rejected(db, why) as cur:
            cur.execute(insert, with_(index, value))
    with must_be_rejected(db, "the same price twice at the same instant") as cur:
        cur.execute(insert, with_(4, "9.5"))


# ── the registry ────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_registry_classifies_every_bet_and_syncing_again_changes_nothing(db: psycopg.Connection) -> None:
    ids = sync_definitions(db)
    assert set(ids) == set(known_bet_ids()) and len(ids) == 338
    assert count(db, "SELECT count(*) FROM market.market_definitions WHERE extract") == len(extracted_specs())
    assert count(db, "SELECT count(*) FROM market.market_definitions WHERE family = 'unclassified' AND extract") == 0
    with db.cursor() as cur:
        cur.execute("SELECT max(classified_at) FROM market.market_definitions")
        first = cur.fetchone()[0]  # type: ignore[index]
    assert sync_definitions(db) == ids
    with db.cursor() as cur:
        cur.execute("SELECT max(classified_at) FROM market.market_definitions")
        assert cur.fetchone()[0] == first, "nothing was rewritten"  # type: ignore[index]


def test_a_definition_edited_by_hand_survives_until_the_taxonomy_version_moves(db: psycopg.Connection) -> None:
    sync_definitions(db)
    with db.cursor() as cur:
        cur.execute("UPDATE market.market_definitions SET extract = false WHERE provider_bet_id = 45")
    sync_definitions(db)
    assert count(db, "SELECT count(*) FROM market.market_definitions WHERE provider_bet_id = 45 AND extract") == 0
    with db.cursor() as cur:
        cur.execute("UPDATE market.market_definitions SET taxonomy_version = 'tax-old' WHERE provider_bet_id = 45")
    sync_definitions(db)
    assert count(db, "SELECT count(*) FROM market.market_definitions WHERE provider_bet_id = 45 AND extract "
                     "AND taxonomy_version = %s", TAXONOMY_VERSION) == 1


def test_a_bet_that_is_off_in_the_registry_is_not_extracted(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    sync_definitions(db)
    with db.cursor() as cur:
        cur.execute("UPDATE market.market_definitions SET extract = false WHERE provider_bet_id = 45")
    add_fixture(db, seed, 810002)
    body = small_body(810002, bet(45, "Corners Over Under", ("Over 9.5", "1.90")), bet(55, "Corners 1x2", ("Home", "2.0")))
    add_payload(db, seed, PayloadStore(tmp_path), body, fixture=810002)
    report = run(db, tmp_path)
    assert report.quotes_written == 1
    assert count(db, "SELECT count(*) FROM market.odds_quotes q JOIN market.market_definitions d ON d.id = q.definition_id "
                     "WHERE d.provider_bet_id = 45") == 0


# ── one payload, once ───────────────────────────────────────────────────────────────────────────────────────────


def test_a_payload_is_structured_once_and_a_second_run_does_nothing(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id = add_fixture(db, seed, 810010)
    digest = add_payload(db, seed, PayloadStore(tmp_path), real_body(810010), fixture=810010)

    first = run(db, tmp_path)
    assert first.payloads_seen == 1 and first.payloads_ok == 1 and first.payloads_failed == 0
    assert first.quotes_written == 601 and first.quotes_refused == 8, "601 prices; 8 values at '1.00' are not prices"
    row = ledger(db, digest)
    assert row["status"] == "ok" and row["stamped_by"] == "fetch" and row["extractor_version"] == EXTRACTOR_VERSION
    assert row["fixture_id"] == fixture_id and row["captured_at"] == FETCHED and row["kickoff_at"] == KICKOFF
    assert row["quotes_written"] == 601 and row["quotes_refused"] == 8 and row["bookmakers"] == 5
    assert row["page"] == 1 and row["provider_fixture_id"] == 810010
    assert count(db, "SELECT count(*) FROM market.odds_quotes WHERE extraction_id = %s", row["id"]) == 601

    second = run(db, tmp_path)
    assert second.payloads_seen == 0 and second.quotes_written == 0
    assert count(db, "SELECT count(*) FROM market.odds_quotes WHERE extraction_id = %s", row["id"]) == 601
    assert count(db, "SELECT count(*) FROM market.odds_extractions WHERE payload_hash = %s", digest) == 1


def test_the_quotes_carry_the_instant_of_the_fetch_and_the_kickoff_of_the_payload(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810011)
    add_payload(db, seed, PayloadStore(tmp_path), real_body(810011), fixture=810011, fetched_at=KICKOFF - timedelta(hours=3, seconds=30))
    with db.cursor() as cur:  # a reschedule after the capture must not change what the capture knew
        cur.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE provider_fixture_id = 810011", (KICKOFF + timedelta(days=2),))
    run(db, tmp_path)
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT captured_at, minutes_to_ko FROM market.odds_quotes q JOIN core.fixtures f ON f.id = q.fixture_id "
                    "WHERE f.provider_fixture_id = 810011")
        assert cur.fetchall() == [(KICKOFF - timedelta(hours=3, seconds=30), 180)]


def test_the_quotes_are_the_readings_of_the_structured_families(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810012)
    add_payload(db, seed, PayloadStore(tmp_path), real_body(810012), fixture=810012)
    run(db, tmp_path)
    with db.cursor() as cur:
        cur.execute(
            "SELECT d.provider_bet_id, q.selection, q.line, q.odds_decimal FROM market.odds_quotes q "
            "JOIN market.market_definitions d ON d.id = q.definition_id JOIN market.bookmakers b ON b.id = q.bookmaker_id "
            "WHERE b.provider_bookmaker_id = 8 AND d.provider_bet_id IN (1, 4, 5, 7, 11, 12, 16, 22, 34, 26)")
        rows = {(a, b, c): d for a, b, c, d in cur.fetchall()}
    assert rows[(1, "Home", 0)] > 1 and rows[(12, "1X", 0)] > 1
    assert (4, "Home", -1.25) in rows and (4, "Away", 1.25) in rows, "the away row of a handicap is negated"
    assert (5, "Over", 2.5) in rows and (5, "Under", 2.5) in rows
    assert (7, "Home/Draw", 0) in rows
    assert (16, "Over", 1.5) in rows
    assert (26, "Over", 2.5) in rows or (26, "Under", 2.5) in rows


# ── the instant: before and after kick-off ──────────────────────────────────────────────────────────────────────


def test_a_payload_fetched_after_kickoff_is_filed_under_the_providers_own_update_stamp(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810020)
    update = KICKOFF - timedelta(minutes=2)
    digest = add_payload(db, seed, PayloadStore(tmp_path), real_body(810020, update=update), fixture=810020,
                         fetched_at=KICKOFF + timedelta(hours=1))
    report = run(db, tmp_path)
    row = ledger(db, digest)
    assert report.payloads_ok == 1 and row["stamped_by"] == "provider_update" and row["captured_at"] == update
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT captured_at, minutes_to_ko FROM market.odds_quotes WHERE extraction_id = %s", (row["id"],))
        assert cur.fetchall() == [(update, 2)]


def test_a_payload_fetched_after_kickoff_without_a_usable_stamp_writes_nothing(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    """It might be an in-play price filed as a pre-match one."""
    add_fixture(db, seed, 810021)
    digest = add_payload(db, seed, PayloadStore(tmp_path), real_body(810021, update=KICKOFF + timedelta(minutes=1)),
                         fixture=810021, fetched_at=KICKOFF + timedelta(hours=1))
    report = run(db, tmp_path)
    row = ledger(db, digest)
    assert report.payloads_after_kickoff == 1 and report.quotes_written == 0
    assert row["status"] == "after_kickoff" and row["stamped_by"] == "none" and row["captured_at"] is None
    assert count(db, "SELECT count(*) FROM market.odds_quotes WHERE extraction_id = %s", row["id"]) == 0
    assert run(db, tmp_path).payloads_seen == 0, "a final decision is not asked again"


# ── a fixture we do not have yet ────────────────────────────────────────────────────────────────────────────────


def test_a_payload_for_a_fixture_not_known_yet_is_retried_on_the_ledgers_cadence_and_then_filed(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    digest = add_payload(db, seed, PayloadStore(tmp_path), real_body(810030), fixture=810030)
    now = FETCHED + timedelta(minutes=1)
    report = run(db, tmp_path, now=now)
    assert report.payloads_no_fixture == 1 and ledger(db, digest)["status"] == "no_fixture"

    assert run(db, tmp_path, now=now + timedelta(minutes=5)).payloads_seen == 0, "too soon to ask again"
    add_fixture(db, seed, 810030)
    later = run(db, tmp_path, now=now + RETRY_AFTER + timedelta(minutes=1))
    assert later.payloads_ok == 1 and later.quotes_written == 601
    assert ledger(db, digest)["status"] == "ok"
    assert count(db, "SELECT count(*) FROM market.odds_extractions WHERE payload_hash = %s", digest) == 1, "the row is updated"


def test_the_payloads_nobody_has_read_come_before_the_ones_that_keep_failing(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    store = PayloadStore(tmp_path)
    old = FETCHED - timedelta(days=1)
    stuck = [add_payload(db, seed, store, real_body(810040 + i), fixture=810040 + i, fetched_at=old + timedelta(minutes=i))
             for i in range(3)]
    now = old + timedelta(hours=1)
    assert run(db, tmp_path, now=now).payloads_no_fixture == 3
    add_fixture(db, seed, 810050)
    fresh = add_payload(db, seed, store, real_body(810050), fixture=810050, fetched_at=FETCHED)
    later = now + RETRY_AFTER + timedelta(minutes=5)
    picked = [r["hash"] for r in pending_payloads(db, limit=2, now=later, **WINDOW)]
    assert picked[0] == fresh, "unread first, although it is newer"
    assert set(picked[1:]) <= set(stuck)


def test_a_payload_that_keeps_failing_is_not_retried_for_ever(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    digest = add_payload(db, seed, PayloadStore(tmp_path), real_body(810060), fixture=810060)
    far = FETCHED + timedelta(days=15)
    assert run(db, tmp_path, now=FETCHED + timedelta(hours=1)).payloads_no_fixture == 1
    assert run(db, tmp_path, now=far).payloads_seen == 0, "after the retry window the verdict stands"
    assert ledger(db, digest)["status"] == "no_fixture"


# ── a better reading replaces the older one ─────────────────────────────────────────────────────────────────────


def test_a_newer_extractor_version_replaces_what_the_older_one_wrote(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810070)
    digest = add_payload(db, seed, PayloadStore(tmp_path), real_body(810070), fixture=810070)
    run(db, tmp_path)
    before = ledger(db, digest)
    with db.cursor() as cur:  # the older reading was wrong about one selection and had missed another price
        cur.execute("UPDATE market.odds_quotes SET selection = 'Wrong' WHERE extraction_id = %s AND selection = 'Draw' "
                    "AND definition_id = (SELECT id FROM market.market_definitions WHERE provider_bet_id = 1)", (before["id"],))
        cur.execute("DELETE FROM market.odds_quotes WHERE extraction_id = %s AND selection = 'Over' AND line = 2.5", (before["id"],))
        cur.execute("UPDATE market.odds_extractions SET extractor_version = 'qx-0/old' WHERE id = %s", (before["id"],))
    assert count(db, "SELECT count(*) FROM market.odds_quotes WHERE selection = 'Wrong'") > 0

    report = run(db, tmp_path, now=before["extracted_at"] + RETRY_AFTER + timedelta(minutes=1))
    after = ledger(db, digest)
    assert report.payloads_ok == 1 and report.quotes_replaced > 0
    assert after["id"] == before["id"] and after["extractor_version"] == EXTRACTOR_VERSION
    assert count(db, "SELECT count(*) FROM market.odds_quotes WHERE selection = 'Wrong'") == 0, "the wrong reading is gone"
    assert count(db, "SELECT count(*) FROM market.odds_quotes WHERE extraction_id = %s", before["id"]) == 601
    assert after["quotes_written"] == 601


def test_a_payload_is_replaced_only_by_its_own_extraction(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    """Another payload of the same fixture keeps its rows when the first is read again."""
    add_fixture(db, seed, 810071)
    store = PayloadStore(tmp_path)
    a = add_payload(db, seed, store, real_body(810071), fixture=810071, fetched_at=FETCHED)
    other = real_body(810071)
    other["response"][0]["bookmakers"][0]["bets"][0]["values"][0]["odd"] = "9.99"
    b = add_payload(db, seed, store, other, fixture=810071, fetched_at=FETCHED + timedelta(hours=1))
    run(db, tmp_path)
    rows_b = count(db, "SELECT count(*) FROM market.odds_quotes WHERE extraction_id = %s", ledger(db, b)["id"])
    with db.cursor() as cur:
        cur.execute("UPDATE market.odds_extractions SET extractor_version = 'qx-0/old' WHERE payload_hash = %s", (a,))
    run(db, tmp_path, now=datetime.now(UTC) + timedelta(days=1))
    assert count(db, "SELECT count(*) FROM market.odds_quotes WHERE extraction_id = %s", ledger(db, b)["id"]) == rows_b
    assert ledger(db, a)["extractor_version"] == EXTRACTOR_VERSION


def test_a_price_that_moved_is_a_new_row_not_an_overwrite(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id = add_fixture(db, seed, 810072)
    store = PayloadStore(tmp_path)
    first = small_body(810072, bet(45, "Corners Over Under", ("Over 9.5", "1.90"), ("Under 9.5", "1.90")))
    second = small_body(810072, bet(45, "Corners Over Under", ("Over 9.5", "1.80"), ("Under 9.5", "2.00")))
    add_payload(db, seed, store, first, fixture=810072, fetched_at=FETCHED)
    add_payload(db, seed, store, second, fixture=810072, fetched_at=FETCHED + timedelta(hours=2))
    run(db, tmp_path)
    with db.cursor() as cur:
        cur.execute("SELECT captured_at, odds_decimal FROM market.odds_quotes WHERE fixture_id = %s AND selection = 'Over' "
                    "ORDER BY captured_at", (fixture_id,))
        assert cur.fetchall() == [(FETCHED, Decimal("1.90")), (FETCHED + timedelta(hours=2), Decimal("1.80"))]
        cur.execute("SELECT odds_decimal FROM market.odds_quotes WHERE fixture_id = %s AND selection = 'Over' "
                    "AND captured_at <= %s ORDER BY captured_at DESC LIMIT 1", (fixture_id, FETCHED + timedelta(hours=1)))
        assert cur.fetchone() == (Decimal("1.90"),), "as of a cut-off, the price in force"


# ── what goes wrong ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_renamed_bet_is_refused_and_the_ledger_says_so(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810080)
    body = small_body(810080, bet(45, "Corners Over Under", ("Over 9.5", "1.90")),
                      bet(80, "Booking Points Over/Under", ("Over 3.5", "1.80")))
    digest = add_payload(db, seed, PayloadStore(tmp_path), body, fixture=810080)
    report = run(db, tmp_path)
    assert report.quotes_written == 1 and report.renamed_bets == {80: "Booking Points Over/Under"}
    assert "renamed bets refused" in ledger(db, digest)["detail"]


def test_a_bet_nobody_classified_is_registered_as_unclassified(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810081)
    body = small_body(810081, bet(9999, "A Market Born Today", ("Yes", "2.00")))
    add_payload(db, seed, PayloadStore(tmp_path), body, fixture=810081)
    report = run(db, tmp_path)
    assert report.unknown_bets == {9999: "A Market Born Today"}
    with db.cursor() as cur:
        cur.execute("SELECT name, family, extract, status FROM market.market_definitions WHERE provider_bet_id = 9999")
        assert cur.fetchone() == ("A Market Born Today", "unclassified", False, "NOT_MODELABLE")


def test_a_payload_whose_file_is_missing_is_recorded_and_not_asked_for_on_every_run(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810090)
    store = PayloadStore(tmp_path)
    digest = add_payload(db, seed, store, real_body(810090), fixture=810090)
    (tmp_path / db.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (digest,)).fetchone()[0]).unlink()  # type: ignore[index]
    now = FETCHED + timedelta(minutes=1)
    report = run(db, tmp_path, now=now)
    assert report.payloads_missing_file == 1 and "not in the RAW store" in report.problems[0]
    row = ledger(db, digest)
    assert row["status"] == "error" and "not in the RAW store" in row["detail"]
    assert run(db, tmp_path, now=now + timedelta(minutes=2)).payloads_seen == 0
    assert run(db, tmp_path, now=now + RETRY_AFTER + timedelta(minutes=1)).payloads_missing_file == 1


def test_a_corrupt_file_and_a_file_that_is_not_its_payload_are_failures_not_data(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810091)
    add_fixture(db, seed, 810092)
    store = PayloadStore(tmp_path)
    corrupt = add_payload(db, seed, store, real_body(810091), fixture=810091, fetched_at=FETCHED)
    swapped = add_payload(db, seed, store, real_body(810092), fixture=810092, fetched_at=FETCHED + timedelta(minutes=1))

    def path(h: str) -> Path:
        stored = db.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (h,)).fetchone()
        assert stored is not None
        return tmp_path / stored[0]

    path(corrupt).write_bytes(b"this is not gzip")
    impostor = {"body": real_body(810092, update=KICKOFF - timedelta(days=3))}
    with gzip.open(path(swapped), "wb") as fh:
        fh.write(json.dumps(impostor).encode())

    report = run(db, tmp_path)
    assert report.payloads_failed == 2 and report.quotes_written == 0
    assert "unreadable" in ledger(db, corrupt)["detail"] and "does not re-hash" in ledger(db, swapped)["detail"]
    assert count(db, "SELECT count(*) FROM market.odds_quotes") == 0


def test_a_truncated_gzip_is_a_failure_too(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810093)
    digest = add_payload(db, seed, PayloadStore(tmp_path), real_body(810093), fixture=810093)
    file = tmp_path / db.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (digest,)).fetchone()[0]  # type: ignore[index]
    file.write_bytes(file.read_bytes()[: file.stat().st_size // 2])
    report = run(db, tmp_path)
    assert report.payloads_failed == 1 and ledger(db, digest)["status"] == "error"


def test_one_bad_payload_does_not_stop_the_good_ones(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810094)
    add_fixture(db, seed, 810095)
    store = PayloadStore(tmp_path)
    bad = add_payload(db, seed, store, real_body(810094), fixture=810094, fetched_at=FETCHED)
    good = add_payload(db, seed, store, real_body(810095), fixture=810095, fetched_at=FETCHED + timedelta(minutes=1))
    (tmp_path / db.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (bad,)).fetchone()[0]).write_bytes(b"x")  # type: ignore[index]
    report = run(db, tmp_path)
    assert report.payloads_failed == 1 and report.payloads_ok == 1
    assert ledger(db, good)["status"] == "ok" and ledger(db, bad)["status"] == "error"


def test_an_answer_with_no_prices_is_final(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810096)
    digest = add_payload(db, seed, PayloadStore(tmp_path), {"get": "odds", "results": 1, "response": []}, fixture=810096)
    report = run(db, tmp_path)
    assert report.payloads_empty == 1 and ledger(db, digest)["status"] == "empty"
    assert run(db, tmp_path).payloads_seen == 0


def test_a_page_of_the_same_fixture_is_its_own_payload(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810097)
    store = PayloadStore(tmp_path)
    one = small_body(810097, bet(45, "Corners Over Under", ("Over 9.5", "1.90")), book=(8, "Bet365"))
    two = small_body(810097, bet(45, "Corners Over Under", ("Over 9.5", "1.95")), book=(7, "William Hill"))
    a = add_payload(db, seed, store, one, fixture=810097, page=1)
    b = add_payload(db, seed, store, two, fixture=810097, page=2)
    report = run(db, tmp_path)
    assert report.quotes_written == 2
    assert (ledger(db, a)["page"], ledger(db, b)["page"]) == (1, 2)


# ── how the job behaves ─────────────────────────────────────────────────────────────────────────────────────────


def test_two_runs_cannot_overlap(db: psycopg.Connection, migrated_database: str, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810100)
    add_payload(db, seed, PayloadStore(tmp_path), real_body(810100), fixture=810100)
    with psycopg.connect(migrated_database, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        try:
            report = run(db, tmp_path)
            assert report.skipped_locked and report.payloads_seen == 0
        finally:
            other.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
    assert not run(db, tmp_path).skipped_locked, "the lock is free again, and a run releases it when it ends"
    assert not run(db, tmp_path).skipped_locked


def test_a_run_stops_between_payloads_when_its_time_is_up(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    store = PayloadStore(tmp_path)
    for i in range(3):
        add_fixture(db, seed, 810110 + i)
        add_payload(db, seed, store, real_body(810110 + i), fixture=810110 + i, fetched_at=FETCHED + timedelta(minutes=i))
    report = run(db, tmp_path, max_seconds=0)
    assert report.stopped_for_time and report.payloads_seen == 1 and report.payloads_ok == 1
    assert run(db, tmp_path).payloads_ok == 2, "the next run takes up where it stopped"


def test_the_oldest_payloads_go_first_and_the_limit_is_respected(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    store = PayloadStore(tmp_path)
    hashes = []
    for i in range(4):
        add_fixture(db, seed, 810120 + i)
        hashes.append(add_payload(db, seed, store, real_body(810120 + i), fixture=810120 + i, fetched_at=FETCHED + timedelta(minutes=i)))
    report = run(db, tmp_path, limit=2)
    assert report.payloads_ok == 2
    assert {h for h in hashes if count(db, "SELECT count(*) FROM market.odds_extractions WHERE payload_hash = %s", h)} == set(hashes[:2])


def test_the_backlog_counts_what_the_current_extractor_has_not_finished(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    base = backlog(db)
    add_fixture(db, seed, 810130)
    add_payload(db, seed, PayloadStore(tmp_path), real_body(810130), fixture=810130)
    assert backlog(db) == base + 1
    run(db, tmp_path)
    assert backlog(db) == base


def test_a_dry_run_reads_real_payloads_and_writes_nothing(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    add_fixture(db, seed, 810140)
    add_payload(db, seed, PayloadStore(tmp_path), real_body(810140), fixture=810140)
    report = sample_extraction(db, tmp_path, sample=10, **WINDOW)
    assert report.dry_run and report.payloads_seen == 1 and report.payloads_ok == 1 and report.quotes_written == 601
    assert report.refused_by_bet == {5: 6, 16: 1, 17: 1}
    assert count(db, "SELECT count(*) FROM market.odds_extractions") == 0
    assert count(db, "SELECT count(*) FROM market.odds_quotes") == 0
    assert count(db, "SELECT count(*) FROM market.market_definitions") == 0, "not even the registry"


def test_a_failure_in_the_database_is_recorded_and_the_run_goes_on(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import fbi.odds.quote_extract as module

    add_fixture(db, seed, 810150)
    add_fixture(db, seed, 810151)
    store = PayloadStore(tmp_path)
    a = add_payload(db, seed, store, real_body(810150), fixture=810150, fetched_at=FETCHED)
    b = add_payload(db, seed, store, real_body(810151), fixture=810151, fetched_at=FETCHED + timedelta(minutes=1))
    real = module._insert_quotes
    calls: list[int] = []

    def flaky(conn: psycopg.Connection, **kw: Any) -> int:
        calls.append(1)
        if len(calls) == 1:
            conn.execute("SELECT 1/0")  # a database error in the middle of a payload
        return real(conn, **kw)

    monkeypatch.setattr(module, "_insert_quotes", flaky)
    report = run(db, tmp_path)
    assert report.payloads_failed == 1 and report.payloads_ok == 1
    assert ledger(db, a)["status"] == "error" and "DivisionByZero" in ledger(db, a)["detail"]
    assert ledger(db, b)["status"] == "ok"
    assert count(db, "SELECT count(*) FROM market.odds_quotes q JOIN market.odds_extractions x ON x.id = q.extraction_id "
                     "WHERE x.payload_hash = %s", a) == 0, "nothing of the failed payload is left half written"


def test_the_admin_view_reports_what_is_structured_and_what_waits(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    from fbi.api.services.intelligence import price_clock

    store = PayloadStore(tmp_path)
    add_fixture(db, seed, 810160)
    add_payload(db, seed, store, real_body(810160), fixture=810160, fetched_at=FETCHED)
    run(db, tmp_path)
    waiting = add_payload(db, seed, store, real_body(810160, update=KICKOFF - timedelta(days=2)), fixture=810160,
                          fetched_at=FETCHED + timedelta(hours=1))
    add_payload(db, seed, store, {"get": "odds", "response": [{"fixture": {"id": 424242}, "bookmakers": []}]}, fixture=424242,
                fetched_at=FETCHED + timedelta(hours=2))
    run(db, tmp_path, limit=1)

    view = price_clock(db).data
    assert view is not None
    assert view["extractor"] == EXTRACTOR_VERSION and view["backlog"] >= 1
    statuses = {(row["status"], row["version"]): row for row in view["ledger"]}
    assert statuses[("ok", EXTRACTOR_VERSION)]["quotes"] >= 601
    assert view["quotes"]["fixtures"] >= 1 and view["quotes"]["gigabytes"] >= 0
    families = {f["key"]: f for f in view["families"]}
    assert families["goals_half"]["extracted"] > 0 and families["goals_half"]["quotes"] > 0
    assert families["players"]["extracted"] == 0 and families["players"]["bets"] > 0
    bets = {b["bet_id"]: b for b in view["bets"]}
    assert bets[5]["quotes"] > 0 and bets[5]["family"] == "goals" and bets[7]["quotes"] > 0
    assert bets[45]["quotes"] == 0, "extracted but not in this payload: shown, with no prices"
    assert any(issue["status"] == "ok" and "values refused by bet" in issue["detail"] for issue in view["issues"])
    assert waiting  # still unread: the backlog counts it
