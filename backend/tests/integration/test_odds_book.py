"""The current-price book against a real PostgreSQL (plan Cuotas, BE-010): a real answer stored in RAW, read by the real extractor,
asked by the capture's ledger, becomes ``market.book_current`` - and nothing else moves.

The answer in force is the one ``fbi.odds.quote_current`` says (A -> B -> A reads A, an empty answer withdraws), the extracted
types agree with the Match Center's prices one by one, a second build writes nothing, the rows of matches long started go, and
with ``FBI_ODDS_BOOK`` off the worker's job does not even ask the database a question.
"""

from __future__ import annotations

import copy
import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.market.consensus import recompute_from_snapshots
from fbi.odds.book import BUILDER_VERSION, JOB, build, held_fixtures, run_book_job, table_bytes
from fbi.odds.book_taxonomy import book_spec
from fbi.odds.quote_current import read_in_force
from fbi.odds.quote_extract import run_extraction
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_rejected, scalar
from tests.integration.test_odds_quotes_extract import add_fixture, add_payload

ANSWERS = Path(__file__).parents[1] / "fixtures" / "odds_book" / "real_answers.json"
KO = datetime(2026, 10, 22, 19, 0, tzinfo=UTC)
T1, T2, T3, T4 = (KO - timedelta(hours=h) for h in (30, 20, 10, 5))
WINDOW: dict[str, Any] = {"since": KO - timedelta(days=5), "until": KO}


def real_body(pid: int, kickoff: datetime = KO, *, name: str = "premier_league", bump: str | None = None) -> dict[str, Any]:
    """A real answer of the audit, as the provider sends it, for our test match. ``bump``: every price of Match Winner and of
    Goals Over/Under moved, so the body (and its hash) differs."""
    entry = copy.deepcopy(json.loads(ANSWERS.read_text(encoding="utf-8"))["answers"][name])
    for key in ("payload_hash", "captured_at"):
        entry.pop(key)
    entry["fixture"].update(id=pid, date=kickoff.isoformat(), timestamp=int(kickoff.timestamp()))
    entry["update"] = (kickoff - timedelta(days=1, hours=2)).isoformat()
    if bump:
        for book in entry["bookmakers"]:
            for bet in book["bets"]:
                if bet["id"] in (1, 5):
                    for value in bet["values"]:
                        value["odd"] = str(Decimal(value["odd"]) + Decimal(bump))
    return {"get": "odds", "parameters": {"fixture": str(pid)}, "errors": [], "results": 1,
            "paging": {"current": 1, "total": 1}, "response": [entry]}


def ask(db: psycopg.Connection, pid: int, asked_at: datetime, payload_hash: str | None, results: int = 1,
        kickoff: datetime = KO) -> None:
    db.execute("INSERT INTO market.odds_asks (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, results, quotes, "
               "payload_hash) VALUES (%s, %s, %s, NULL, %s, 0, %s)",
               (pid, asked_at, int((kickoff - asked_at).total_seconds() // 60), results, payload_hash))


def extract(db: psycopg.Connection, root: Path, *, now: datetime | None = None, commit: bool = False) -> None:
    report = run_extraction(db, root, commit=commit, limit=50, now=now, **WINDOW)
    assert report.payloads_failed == 0, report.as_dict()


def seeded(db: psycopg.Connection, seed: Seed, root: Path, pid: int, *, name: str = "premier_league") -> tuple[int, str]:
    """A match, body A in RAW fetched at T1 and read by the extractor, and the ask T1 -> A."""
    fixture_id = add_fixture(db, seed, pid, KO)
    a = add_payload(db, seed, PayloadStore(root), real_body(pid, name=name), fixture=pid, fetched_at=T1)
    extract(db, root)
    ask(db, pid, T1, a)
    return fixture_id, a


def rows(db: psycopg.Connection, fixture_id: int) -> dict[int, dict[str, Any]]:
    """bet id -> the row of the book."""
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT d.provider_bet_id, b.*, b.summary::text AS text FROM market.book_current b "
                    "JOIN market.market_definitions d ON d.id = b.definition_id WHERE b.fixture_id = %s", (fixture_id,))
        return {int(r["provider_bet_id"]): dict(r) for r in cur.fetchall()}


def odds_of(row: dict[str, Any], selection: str, line: float | None = None) -> dict[str, float]:
    for group in row["summary"]["lines"]:
        for s in group["sels"]:
            if s["sel"] == selection and s.get("line", group["line"]) == line:
                return dict(s["odds"])
    raise AssertionError(f"{selection} {line} not in the row")


def do_build(db: psycopg.Connection, root: Path, fixture_ids: list[int], **kw: Any) -> Any:
    kw.setdefault("apply", True)
    kw.setdefault("now", KO - timedelta(hours=1))
    return build(db, root, fixture_ids, commit=False, **kw)


def fingerprint(db: psycopg.Connection, table: str, order: str) -> tuple[int, str]:
    with db.cursor() as cur:
        cur.execute(f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY {order}), '')) FROM {table} t")
        n, digest = cur.fetchone()  # type: ignore[misc]
    return int(n), str(digest)


# ── the table ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_migration_creates_the_book_with_its_keys(db: psycopg.Connection) -> None:
    with db.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = 'market' AND tablename = 'book_current' ORDER BY 1")
        indexes = " ".join(r[0] for r in cur.fetchall())
    assert "UNIQUE INDEX book_current_pkey ON market.book_current USING btree (fixture_id, definition_id)" in indexes
    assert "book_current_definition_kickoff_idx ON market.book_current USING btree (definition_id, kickoff_at)" in indexes
    assert "book_current_kickoff_idx ON market.book_current USING btree (kickoff_at)" in indexes
    assert table_bytes(db) > 0, "the empty table and its indexes"


def test_the_table_refuses_what_a_row_of_the_book_cannot_be(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id, a = seeded(db, seed, tmp_path, 840001)
    do_build(db, tmp_path, [fixture_id])
    held = [r["definition_id"] for r in rows(db, fixture_id).values()]
    insert = ("INSERT INTO market.book_current (fixture_id, definition_id, kickoff_at, captured_at, checked_at, in_force_since, "
              "payload_hash, builder_version, summary) VALUES (%s, %s, %s, %s, %s, %s, %s, 'x', %s::jsonb)")
    other = scalar(db.execute("SELECT id FROM market.market_definitions WHERE id <> ALL(%s) ORDER BY id LIMIT 1", (held,)))
    with db.transaction(force_rollback=True):
        db.execute(insert, [fixture_id, other, KO, T1, T1, T1, a, '{"v": 1}'])  # the row the cases below spoil is a good one
    base = [fixture_id, other, KO, T1, T1, T1, a, '{"v": 1}']
    for index, value, why in ((7, "[1, 2]", "a summary is an object"), (3, KO + timedelta(minutes=1), "captured after kick-off"),
                              (5, T1 - timedelta(hours=1), "in force before it was captured"),
                              (6, "no-such-payload", "a body that is not in RAW")):
        row: list[object] = list(base)
        row[index] = value
        with must_be_rejected(db, why) as cur:
            cur.execute(insert, row)


# ── the book of one match ───────────────────────────────────────────────────────────────────────────────────────────


def test_the_book_of_a_match_is_its_answer_in_force_read_back_from_raw(db: psycopg.Connection, seed: Seed,
                                                                       tmp_path: Path) -> None:
    fixture_id, a = seeded(db, seed, tmp_path, 840010)
    report = do_build(db, tmp_path, [fixture_id])
    assert report.fixtures_priced == 1 and report.states == {"priced": 1} and not report.problems and not report.errors
    book = rows(db, fixture_id)
    assert len(book) == report.rows_inserted == 127, "every visible type of the answer"
    assert not ({78, 213, 215, 275, 276, 299} & set(book)), "the hidden types are not in the book"
    one = book[1]
    assert (one["payload_hash"], one["captured_at"], one["checked_at"], one["in_force_since"]) == (a, T1, T1, T1)
    assert one["kickoff_at"] == KO and one["builder_version"] == BUILDER_VERSION and one["newer_pending"] is False
    assert one["provider_update_at"] == KO - timedelta(days=1, hours=2)
    assert one["summary"]["books"] == 10 and len(odds_of(one, "Home")) == 10
    assert all(r["summary"]["v"] == 2 and r["books"] == r["summary"]["books"] for r in book.values())
    assert {r["definition_id"] for r in book.values()} == {
        scalar(db.execute("SELECT id FROM market.market_definitions WHERE provider_bet_id = %s AND scope = 'prematch'", (b,)))
        for b in book}


def test_the_book_agrees_with_the_match_center_on_every_extracted_price(db: psycopg.Connection, seed: Seed,
                                                                        tmp_path: Path) -> None:
    """Plan phase 3, acceptance: for the types ``market.odds_quotes`` holds, the book and ``quote_current`` (what the Match Center
    shows) give the same price for every bookmaker, selection and line."""
    fixture_id, _ = seeded(db, seed, tmp_path, 840020)
    do_build(db, tmp_path, [fixture_id])
    current = read_in_force(db, fixture_id)
    assert current is not None and current.in_force.state == "priced" and current.quotes
    provider_of: dict[int, int] = {int(a): int(b) for a, b in db.execute(
        "SELECT id, provider_bookmaker_id FROM market.bookmakers").fetchall()}
    theirs = {(q.bet_id, q.selection, float(q.line), str(provider_of[q.bookmaker_id]), float(q.odds)) for q in current.quotes}
    book = rows(db, fixture_id)
    extracted = {q.bet_id for q in current.quotes}
    mine = set()
    for bet_id in extracted:
        spec = book_spec(bet_id)
        assert spec is not None
        for group in book[bet_id]["summary"]["lines"]:
            for s in group["sels"]:
                line = s.get("line", group["line"])
                for bookmaker, odds in s["odds"].items():
                    mine.add((bet_id, s["sel"], 0.0 if line is None else float(line), bookmaker, float(odds)))
    assert mine == theirs
    assert len(extracted) == 42 and len(theirs) == 571, "the 42 extracted types of the answer, every price of them"


def test_after_a_b_a_the_book_reads_a(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    pid = 840030
    fixture_id = add_fixture(db, seed, pid, KO)
    store = PayloadStore(tmp_path)
    a = add_payload(db, seed, store, real_body(pid), fixture=pid, fetched_at=T1)
    b = add_payload(db, seed, store, real_body(pid, bump="0.05"), fixture=pid, fetched_at=T2)
    extract(db, tmp_path)
    ask(db, pid, T1, a)
    ask(db, pid, T2, b)
    ask(db, pid, T3, a)  # the provider answered A again: RAW keeps no second copy, the ask says so
    do_build(db, tmp_path, [fixture_id])
    one = rows(db, fixture_id)[1]
    assert (one["payload_hash"], one["captured_at"], one["checked_at"], one["in_force_since"]) == (a, T1, T3, T3)
    original = json.loads(ANSWERS.read_text(encoding="utf-8"))["answers"]["premier_league"]
    bet365 = next(v for bk in original["bookmakers"] if bk["id"] == 8 for bet in bk["bets"] if bet["id"] == 1
                  for v in bet["values"] if v["value"] == "Home")
    assert odds_of(one, "Home")["8"] == float(bet365["odd"]), "A's price, not B's"

    ask(db, pid, T4, b)  # and then B for good
    report = do_build(db, tmp_path, [fixture_id])
    one = rows(db, fixture_id)[1]
    assert (one["payload_hash"], one["captured_at"], one["checked_at"]) == (b, T2, T4)
    assert odds_of(one, "Home")["8"] == float(Decimal(bet365["odd"]) + Decimal("0.05"))
    assert report.rows_updated == 127 and report.rows_inserted == 0, "every row now says B"


def test_an_empty_answer_withdraws_every_price_of_the_match(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id, _ = seeded(db, seed, tmp_path, 840040)
    do_build(db, tmp_path, [fixture_id])
    assert len(rows(db, fixture_id)) == 127
    ask(db, 840040, T2, None, results=0)
    report = do_build(db, tmp_path, [fixture_id])
    assert report.states == {"withdrawn": 1} and report.rows_deleted == 127
    assert rows(db, fixture_id) == {}


def test_an_answer_the_extractor_has_not_read_yet_waits_and_the_older_one_stands_in(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id, a = seeded(db, seed, tmp_path, 840050)
    late = add_payload(db, seed, PayloadStore(tmp_path), real_body(840050, bump="0.10"), fixture=840050, fetched_at=T2)
    ask(db, 840050, T2, late)
    do_build(db, tmp_path, [fixture_id])
    one = rows(db, fixture_id)[1]
    assert one["payload_hash"] == a and one["newer_pending"] is True and one["checked_at"] == T1


def test_an_ask_after_kick_off_is_not_pre_match_and_a_match_never_asked_has_no_book(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id = add_fixture(db, seed, 840060, KO)
    report = do_build(db, tmp_path, [fixture_id])
    assert report.states == {"never_asked": 1} and rows(db, fixture_id) == {}
    a = add_payload(db, seed, PayloadStore(tmp_path), real_body(840060), fixture=840060, fetched_at=KO + timedelta(minutes=5))
    extract(db, tmp_path)
    ask(db, 840060, KO + timedelta(minutes=5), a)
    assert do_build(db, tmp_path, [fixture_id]).states == {"never_asked": 1}


def test_a_raw_file_that_does_not_give_its_hash_shows_nothing(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id, a = seeded(db, seed, tmp_path, 840070)
    do_build(db, tmp_path, [fixture_id])
    path = tmp_path / scalar(db.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (a,)))
    envelope = json.loads(gzip.decompress(path.read_bytes()))
    envelope["body"]["response"][0]["bookmakers"] = envelope["body"]["response"][0]["bookmakers"][:1]
    path.write_bytes(gzip.compress(json.dumps(envelope).encode()))
    report = do_build(db, tmp_path, [fixture_id])
    assert any("re-hash" in p for p in report.problems) and rows(db, fixture_id) == {}
    assert report.states == {"unreadable": 1} and report.rows_deleted == 127


# ── a cache: twice the same, nothing else touched ──────────────────────────────────────────────────────────────────


def test_building_twice_writes_nothing_the_second_time(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id, _ = seeded(db, seed, tmp_path, 840080)
    first = do_build(db, tmp_path, [fixture_id], now=KO - timedelta(hours=2))
    before = rows(db, fixture_id)
    second = do_build(db, tmp_path, [fixture_id], now=KO - timedelta(hours=1))
    assert (second.rows_inserted, second.rows_updated, second.rows_deleted) == (0, 0, 0)
    assert second.rows_unchanged == first.rows_inserted == 127
    after = rows(db, fixture_id)
    assert after == before, "not even built_at moved"


def test_the_book_is_deterministic(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    fixture_id, _ = seeded(db, seed, tmp_path, 840090)
    do_build(db, tmp_path, [fixture_id], now=KO - timedelta(hours=3))
    first = {b: {k: v for k, v in r.items() if k != "built_at"} for b, r in rows(db, fixture_id).items()}
    db.execute("DELETE FROM market.book_current WHERE fixture_id = %s", (fixture_id,))
    do_build(db, tmp_path, [fixture_id], now=KO - timedelta(hours=1))
    again = {b: {k: v for k, v in r.items() if k != "built_at"} for b, r in rows(db, fixture_id).items()}
    assert again == first


def test_the_book_moves_nothing_the_models_the_picks_or_the_match_center_read(
        db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    """odds_snapshots, market_consensus and odds_quotes (and the extractor's ledger and the registry) are the same row for row
    before and after a dry run and a build."""
    fixture_id, a = seeded(db, seed, tmp_path, 840100)
    bookmaker: dict[int, int] = {int(a): int(b) for a, b in db.execute(
        "SELECT provider_bookmaker_id, id FROM market.bookmakers").fetchall()}
    entry = real_body(840100)["response"][0]
    for book in entry["bookmakers"]:
        for bet in book["bets"]:
            if bet["id"] == 1:
                for v in bet["values"]:
                    db.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
                               "odds_decimal, captured_at, minutes_to_ko, source, payload_hash) "
                               "VALUES (%s, %s, '1X2', %s, 0, %s, %s, %s, 'prematch', %s)",
                               (fixture_id, bookmaker[book["id"]], v["value"], v["odd"], T1, 1800, a))
    assert recompute_from_snapshots(db, fixture_ids=[fixture_id])[1] > 0
    tables = {"market.odds_snapshots": "fixture_id, bookmaker_id, market_key, selection, line, captured_at",
              "market.market_consensus": "fixture_id, market_key, selection, line, as_of, devig_method",
              "market.odds_quotes": "fixture_id, bookmaker_id, definition_id, selection, line, captured_at",
              "market.odds_extractions": "id", "market.market_definitions": "id", "market.odds_asks": "provider_fixture_id, asked_at",
              "raw.ingestion_payloads": "hash"}
    before = {t: fingerprint(db, t, o) for t, o in tables.items()}
    assert before["market.odds_quotes"][0] >= 571 and before["market.market_consensus"][0] > 0
    do_build(db, tmp_path, [fixture_id], apply=False)
    do_build(db, tmp_path, [fixture_id])
    assert {t: fingerprint(db, t, o) for t, o in tables.items()} == before
    assert len(rows(db, fixture_id)) == 127


def test_the_dry_run_counts_what_the_build_would_do_and_writes_nothing(db: psycopg.Connection, seed: Seed,
                                                                       tmp_path: Path) -> None:
    fixture_id, _ = seeded(db, seed, tmp_path, 840110)
    dry = do_build(db, tmp_path, [fixture_id], apply=False)
    assert dry.dry_run and dry.rows_inserted == 127 and rows(db, fixture_id) == {}
    wet = do_build(db, tmp_path, [fixture_id])
    assert (wet.rows_inserted, wet.rows, wet.summary_bytes) == (dry.rows_inserted, dry.rows, dry.summary_bytes)
    again = do_build(db, tmp_path, [fixture_id], apply=False)
    assert (again.rows_inserted, again.rows_updated, again.rows_unchanged) == (0, 0, 127)
    ask(db, 840110, T2, None, results=0)
    assert do_build(db, tmp_path, [fixture_id], apply=False).rows_deleted == 127 and len(rows(db, fixture_id)) == 127


def test_the_rows_of_matches_that_kicked_off_six_hours_ago_are_deleted(db: psycopg.Connection, seed: Seed,
                                                                       tmp_path: Path) -> None:
    old, _ = seeded(db, seed, tmp_path, 840120)
    do_build(db, tmp_path, [old])
    recent_ko = KO + timedelta(hours=2)
    recent = add_fixture(db, seed, 840121, recent_ko)
    r = add_payload(db, seed, PayloadStore(tmp_path), real_body(840121, recent_ko, name="copa_del_rey"), fixture=840121,
                    fetched_at=T1)
    extract(db, tmp_path)
    ask(db, 840121, T1, r, kickoff=recent_ko)
    do_build(db, tmp_path, [recent])
    kept = len(rows(db, recent))
    report = do_build(db, tmp_path, [], purge_old=True, now=KO + timedelta(hours=6, minutes=30))
    assert report.rows_purged == 127 and rows(db, old) == {} and len(rows(db, recent)) == kept > 0
    assert recent in held_fixtures(db, kickoff_from=KO) and old not in held_fixtures(db, kickoff_from=KO + timedelta(hours=1))


# ── the worker's job ────────────────────────────────────────────────────────────────────────────────────────────────


def test_with_the_switch_off_the_job_does_not_even_ask_the_database(db: psycopg.Connection, tmp_path: Path) -> None:
    assert db.info.transaction_status == TransactionStatus.IDLE
    assert run_book_job(db, tmp_path, enabled=False) is None
    assert run_book_job(db, tmp_path) is None, "FBI_ODDS_BOOK is off unless it says on"
    assert db.info.transaction_status == TransactionStatus.IDLE, "no query was sent"


@pytest.fixture()
def held(db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection]:
    """The test's connection with its commits held: the job commits as the worker's does, and here everything stays in the
    test's transaction, rolled back at the end (nothing reaches the other tests). The clock is the job's, frozen."""
    monkeypatch.setattr(db, "commit", lambda: None)
    try:
        yield db
    finally:
        set_clock(SystemClock())


def test_the_job_builds_what_changed_purges_and_records_its_passes(held: psycopg.Connection, seed: Seed,
                                                                    tmp_path: Path) -> None:
    conn, store = held, PayloadStore(tmp_path)
    now = datetime(2027, 2, 10, 12, 0, tzinfo=UTC)
    ko1, ko2, ko_old = now + timedelta(hours=20), now + timedelta(hours=30), now - timedelta(hours=8)
    f1, f2, f_old = (add_fixture(conn, seed, pid, ko) for pid, ko in ((840201, ko1), (840202, ko2), (840203, ko_old)))
    a1 = add_payload(conn, seed, store, real_body(840201, ko1, name="copa_del_rey"), fixture=840201, fetched_at=now - timedelta(hours=2))
    a2 = add_payload(conn, seed, store, real_body(840202, ko2, name="copa_del_rey"), fixture=840202, fetched_at=now - timedelta(hours=3))
    a3 = add_payload(conn, seed, store, real_body(840203, ko_old, name="copa_del_rey"), fixture=840203,
                     fetched_at=ko_old - timedelta(hours=3))
    report = run_extraction(conn, tmp_path, commit=False, limit=50, now=now - timedelta(hours=1),
                            since=now - timedelta(days=2), until=now + timedelta(days=2))
    assert report.payloads_ok == 3
    ask(conn, 840201, now - timedelta(hours=2), a1, kickoff=ko1)
    ask(conn, 840202, now - timedelta(hours=3), a2, kickoff=ko2)
    ask(conn, 840203, ko_old - timedelta(hours=3), a3, kickoff=ko_old)
    build(conn, tmp_path, [f_old], apply=True, now=ko_old - timedelta(hours=1))  # built while it was to come
    assert rows(conn, f_old)

    set_clock(FrozenClock(now))
    first = run_book_job(conn, tmp_path, enabled=True)
    assert first is not None and first.fixtures_seen == 2 and first.fixtures_priced == 2 and first.rows_purged > 0
    assert rows(conn, f1) and rows(conn, f2) and rows(conn, f_old) == {}, "the started match is purged, not rebuilt"

    set_clock(FrozenClock(now + timedelta(minutes=30)))
    assert run_book_job(conn, tmp_path, enabled=True) is None, "nothing changed and nothing to purge: no pass recorded"

    b1 = add_payload(conn, seed, store, real_body(840201, ko1, name="copa_del_rey", bump="0.03"), fixture=840201,
                     fetched_at=now + timedelta(minutes=35))
    run_extraction(conn, tmp_path, commit=False, limit=50, now=now + timedelta(minutes=36), since=now - timedelta(days=2),
                   until=now + timedelta(days=2))
    ask(conn, 840201, now + timedelta(minutes=35), b1, kickoff=ko1)
    set_clock(FrozenClock(now + timedelta(minutes=40)))
    third = run_book_job(conn, tmp_path, enabled=True)
    assert third is not None and third.fixtures_seen == 1, "only the match whose answer changed"
    assert rows(conn, f1)[1]["payload_hash"] == b1 and rows(conn, f2)[1]["payload_hash"] == a2

    with conn.cursor() as cur:
        cur.execute("SELECT status, rows_written FROM raw.ingestion_runs WHERE job_type = %s AND started_at >= %s "
                    "ORDER BY started_at", (JOB, now))
        passes = cur.fetchall()
    assert [p[0] for p in passes] == ["completed", "completed"] and passes[0][1] > 0
