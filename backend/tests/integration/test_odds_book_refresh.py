"""The book refreshes against a real PostgreSQL (plan Cuotas, BE-011): an ask through the real provider client (a mock transport)
becomes RAW, a ``market.book_asks`` row and the match's book - and NOTHING the models, the picks or the Match Center read moves.

The proof of the plan's promise: ``odds_quotes``, ``odds_snapshots``, ``market_consensus`` (and the extractor's ledger, the
capture's asks and ``quote_current``) are row for row the same before and after a refresh; a body a refresh fetched first and the
capture fetched again is the capture's, stamped and extracted exactly as a body the refresh never saw; the capture planner's
catch-up ignores the refreshes. And the book reads both tables with the A -> B -> A rule."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.market.consensus import recompute_from_snapshots
from fbi.odds.book import locate_book_in_force
from fbi.odds.book_refresh import (
    JOB,
    RefreshReport,
    RefreshTask,
    ask_and_build,
    budget_now,
    candidates,
    refresh_only_points,
)
from fbi.odds.capture import OddsCaptureService
from fbi.odds.quote_current import locate_in_force, read_in_force
from fbi.odds.quote_extract import pending_payloads, run_extraction
from fbi.odds.quote_taxonomy import sync_definitions
from fbi.odds.repository import OddsRepository
from fbi.odds.schedule import CapturePlanner, ScheduledFixture
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.quota import ReportedQuota, record_reported
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_odds_book import ask, fingerprint, real_body, rows
from tests.integration.test_odds_quotes_extract import add_fixture, add_payload

KO = datetime(2026, 10, 22, 19, 0, tzinfo=UTC)
WINDOW: dict[str, Any] = {"since": KO - timedelta(days=5), "until": KO}
MODEL_TABLES = {
    "market.odds_snapshots": "fixture_id, bookmaker_id, market_key, selection, line, captured_at",
    "market.market_consensus": "fixture_id, market_key, selection, line, as_of, devig_method",
    "market.odds_quotes": "fixture_id, bookmaker_id, definition_id, selection, line, captured_at",
    "market.odds_extractions": "id",
    "market.odds_asks": "provider_fixture_id, asked_at",
    "market.market_definitions": "id",
}


@pytest.fixture()
def held(db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection]:
    """The test's connection with its commits held (the job and the capture commit as the worker's do; here everything stays in
    the test's transaction, rolled back at the end). The clock is restored after."""
    monkeypatch.setattr(db, "commit", lambda: None)
    try:
        yield db
    finally:
        set_clock(SystemClock())


def provider_for(root: Path, bodies: dict[int, dict[str, Any]], *, headers: dict[str, str] | None = None,
                 calls: list[int] | None = None) -> ApiFootballProvider:
    """The real provider and client over a mock transport: the answer of each fixture asked for."""

    def handler(request: httpx.Request) -> httpx.Response:
        pid = int(request.url.params["fixture"])
        if calls is not None:
            calls.append(pid)
        return httpx.Response(200, json=bodies[pid], headers=headers or {})

    async def no_sleep(_seconds: float) -> None:
        return None

    settings = ApiFootballSettings(key="k" * 32, plan="pro", daily_budget=1000, max_retries=0)
    client = ApiFootballClient(settings, PayloadStore(root), transport=httpx.MockTransport(handler),
                               rate_limiter=TokenBucket(settings.per_minute_limit, sleep=no_sleep),
                               quota=DailyQuota(budget=1000), sleep=no_sleep)
    return ApiFootballProvider(client)


async def refresh(conn: psycopg.Connection, root: Path, provider: ApiFootballProvider, tasks: list[RefreshTask], *,
                  at: datetime, floor: int = 0) -> RefreshReport:
    set_clock(FrozenClock(at))
    client = provider._client  # the provider's own client: its quota headers, as the job reads them
    try:
        return await ask_and_build(conn, provider, tasks, raw_root=root, report=RefreshReport(due=len(tasks)),
                                   floor=floor, reported=lambda: client.reported_quota, at=at)
    finally:
        await provider.aclose()


def task(fixture_id: int, pid: int, at: datetime, point: int = 120) -> RefreshTask:
    return RefreshTask(fixture_id, pid, KO, point, int((KO - at).total_seconds() // 60))


def seed_capture(db: psycopg.Connection, seed: Seed, root: Path, pid: int, at: datetime) -> tuple[int, str]:
    """A match with the capture's answer A at ``at``: RAW, read by the extractor, asked, its 1X2 snapshots and consensus."""
    fixture_id = add_fixture(db, seed, pid, KO)
    a = add_payload(db, seed, PayloadStore(root), real_body(pid), fixture=pid, fetched_at=at)
    assert run_extraction(db, root, commit=False, limit=50, now=at + timedelta(minutes=5), **WINDOW).payloads_ok == 1
    ask(db, pid, at, a)
    bookmaker = {int(x): int(y) for x, y in db.execute("SELECT provider_bookmaker_id, id FROM market.bookmakers").fetchall()}
    for book in real_body(pid)["response"][0]["bookmakers"]:
        for bet in book["bets"]:
            if bet["id"] == 1:
                for v in bet["values"]:
                    db.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
                               "odds_decimal, captured_at, minutes_to_ko, source, payload_hash) "
                               "VALUES (%s, %s, '1X2', %s, 0, %s, %s, %s, 'prematch', %s)",
                               (fixture_id, bookmaker[book["id"]], v["value"], v["odd"], at,
                                int((KO - at).total_seconds() // 60), a))
    assert recompute_from_snapshots(db, fixture_ids=[fixture_id])[1] > 0
    return fixture_id, a


def payload_run(db: psycopg.Connection, payload_hash: str) -> tuple[str, datetime]:
    row = db.execute("SELECT r.job_type, p.fetched_at FROM raw.ingestion_payloads p JOIN raw.ingestion_runs r "
                     "ON r.id = p.run_id WHERE p.hash = %s", (payload_hash,)).fetchone()
    assert row is not None
    return str(row[0]), row[1]


def book_asks(db: psycopg.Connection, pid: int) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM market.book_asks WHERE provider_fixture_id = %s ORDER BY asked_at", (pid,))
        return [dict(r) for r in cur.fetchall()]


# ── the tables ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_migration_adds_the_book_asks_the_providers_count_and_the_books_column(db: psycopg.Connection) -> None:
    def columns(table: str) -> list[str]:
        schema, name = table.split(".")
        return [r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                                         "AND table_name = %s ORDER BY ordinal_position", (schema, name)).fetchall()]

    assert columns("market.book_asks") == columns("market.odds_asks"), "the shape of the capture's asks"
    assert columns("raw.provider_reported_quota") == ["provider", "quota_date", "observed_at", "requests_limit",
                                                      "requests_remaining", "minute_limit", "minute_remaining"]
    assert "books" in columns("market.book_current")
    keys = " ".join(r[0] for r in db.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'book_asks'").fetchall())
    assert "(provider_fixture_id, asked_at)" in keys and "book_asks_asked_at" in keys


# ── a refresh moves nothing the models read ────────────────────────────────────────────────────────────────────────


async def test_a_refresh_writes_raw_its_ask_and_the_book_and_nothing_the_models_read(
        held: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    pid, t1, t2 = 850001, KO - timedelta(hours=30), KO - timedelta(minutes=118)
    fixture_id, a = seed_capture(held, seed, tmp_path, pid, t1)
    current_before = read_in_force(held, fixture_id)
    before = {t: fingerprint(held, t, o) for t, o in MODEL_TABLES.items()}
    assert before["market.odds_quotes"][0] > 0 and before["market.market_consensus"][0] > 0

    b_body = real_body(pid, bump="0.07")
    report = await refresh(held, tmp_path, provider_for(tmp_path, {pid: b_body}), [task(fixture_id, pid, t2)], at=t2)
    assert (report.asked, report.priced, report.api_calls, report.payloads, report.fixtures_built) == (1, 1, 1, 1, 1)
    assert report.stopped_early is None and not report.errors
    [asked] = book_asks(held, pid)
    assert (asked["asked_at"], asked["window_minutes"], asked["results"], asked["run_id"]) == (t2, 120, 1, report.run_id)
    b = asked["payload_hash"]
    assert b != a and payload_run(held, b) == (JOB, t2), "RAW and the payload index, under the refresh's run"
    assert scalar(held.execute("SELECT count(*) FROM market.odds_asks WHERE provider_fixture_id = %s", (pid,))) == 1

    assert not [p for p in pending_payloads(held, limit=100, **WINDOW) if p["hash"] == b], "the extractor never reads it"
    assert run_extraction(held, tmp_path, commit=False, limit=100, now=t2 + timedelta(minutes=5), **WINDOW).payloads_seen == 0
    assert {t: fingerprint(held, t, o) for t, o in MODEL_TABLES.items()} == before
    current_after = read_in_force(held, fixture_id)
    assert current_after == current_before, "quote_current (the Match Center) still reads the capture's answer"

    book = rows(held, fixture_id)
    assert {r["payload_hash"] for r in book.values()} == {b} and {r["checked_at"] for r in book.values()} == {t2}
    assert {r["captured_at"] for r in book.values()} == {t2}
    with held.cursor() as cur:
        cur.execute("SELECT status, api_calls, payloads_stored, rows_written FROM raw.ingestion_runs WHERE id = %s",
                    (report.run_id,))
        assert cur.fetchone() == ("completed", 1, 1, 1)


async def test_a_body_a_refresh_fetched_first_is_the_captures_when_the_capture_fetches_it_again(
        held: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    """RAW keeps a body once. Without the claim the capture's answer would stay the refresh's: never extracted, missing from
    the Match Center. With it, the index row, the extraction and the quotes are those of a world where the refresh never asked
    - compared with a twin match the refresh did not touch."""
    pid, twin = 850011, 850012
    t_refresh, t_capture = KO - timedelta(minutes=239), KO - timedelta(minutes=179)
    fixture_id = add_fixture(held, seed, pid, KO)
    twin_id = add_fixture(held, seed, twin, KO)
    body = {pid: real_body(pid, name="serie_a"), twin: real_body(twin, name="serie_a")}
    await refresh(held, tmp_path, provider_for(tmp_path, body), [task(fixture_id, pid, t_refresh, 240)], at=t_refresh)
    claimed = book_asks(held, pid)[0]["payload_hash"]
    assert payload_run(held, claimed) == (JOB, t_refresh)

    set_clock(FrozenClock(t_capture))
    capture = provider_for(tmp_path, body)
    service = OddsCaptureService(held, capture, CapturePlanner((180,), 12, 45), raw_root=str(tmp_path))
    try:
        result = await service.capture([ScheduledFixture(pid, KO), ScheduledFixture(twin, KO)], at=t_capture)
    finally:
        await capture.aclose()
    assert result.executed == 2 and not result.errors
    assert payload_run(held, claimed) == ("odds_capture", t_capture), "the capture's row, at the capture's instant"
    twin_hash = scalar(held.execute("SELECT payload_hash FROM market.odds_asks WHERE provider_fixture_id = %s", (twin,)))
    assert payload_run(held, twin_hash) == ("odds_capture", t_capture)

    report = run_extraction(held, tmp_path, commit=False, limit=100, now=t_capture + timedelta(minutes=5), **WINDOW)
    assert report.payloads_ok == 2, report.as_dict()
    with held.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload_hash, fixture_id, captured_at, stamped_by, quotes_written, bookmakers, status "
                    "FROM market.odds_extractions WHERE payload_hash = ANY(%s)", ([claimed, twin_hash],))
        ledger = {r.pop("payload_hash"): r for r in cur.fetchall()}
        cur.execute("SELECT fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, captured_at, minutes_to_ko "
                    "FROM market.odds_quotes WHERE fixture_id = ANY(%s)", ([fixture_id, twin_id],))
        quotes = cur.fetchall()
    assert ledger[claimed]["captured_at"] == ledger[twin_hash]["captured_at"] == t_capture
    assert {k: v for k, v in ledger[claimed].items() if k != "fixture_id"} == \
           {k: v for k, v in ledger[twin_hash].items() if k != "fixture_id"}
    mine = sorted(tuple(q[k] for k in q if k != "fixture_id") for q in quotes if q["fixture_id"] == fixture_id)
    theirs = sorted(tuple(q[k] for k in q if k != "fixture_id") for q in quotes if q["fixture_id"] == twin_id)
    assert mine == theirs and mine, "the same quotes, stamped at the capture's instant, as the match the refresh never saw"
    located = locate_in_force(held, fixture_id)
    assert located is not None and located.in_force.checked_at == t_capture and located.in_force.bodies[0].captured_at == t_capture
    book = locate_book_in_force(held, fixture_id)
    assert book is not None and book.in_force.checked_at == t_capture
    assert book.in_force.bodies[0].since == t_refresh, "the book knows the body since the refresh's ask"


def test_the_capture_planners_catch_up_ignores_the_refreshes(held: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    pid = 850021
    add_fixture(held, seed, pid, KO)
    t_capture, t_refresh = KO - timedelta(hours=30), KO - timedelta(hours=5)
    ask(held, pid, t_capture, None, results=0)
    run_id = scalar(held.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES (%s, %s, 'completed') "
                                 "RETURNING id", (JOB, JOB)))
    stored = PayloadStore(tmp_path).store(endpoint="/odds", params={"fixture": pid, "page": 1}, fetched_at=t_refresh,
                                          http_status=200, body=real_body(pid))
    held.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, results_count, "
                 "file_path, bytes) VALUES (%s, %s, '/odds', %s::jsonb, %s, 200, 1, %s, %s)",
                 (stored.hash, run_id, json.dumps({"fixture": str(pid), "page": "1"}), t_refresh, stored.file_path,
                  stored.bytes_written))
    asked = OddsRepository(held).last_asked(provider_fixture_ids=[pid], since=KO - timedelta(days=4))
    assert asked == {pid: t_capture}, "the T-5 h refresh is not an ask of the capture: its catch-up still asks"


# ── the book reads both tables ─────────────────────────────────────────────────────────────────────────────────────


def refresh_payload(db: psycopg.Connection, root: Path, body: dict[str, Any], pid: int, at: datetime) -> str:
    """A body as a refresh leaves it: in RAW and the index under a run of the refresh job."""
    run_id = scalar(db.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES (%s, %s, 'completed') "
                               "RETURNING id", (JOB, JOB)))
    stored = PayloadStore(root).store(endpoint="/odds", params={"fixture": pid, "page": 1}, fetched_at=at, http_status=200,
                                      body=body)
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, results_count, "
               "file_path, bytes) VALUES (%s, %s, '/odds', %s::jsonb, %s, 200, %s, %s, %s) ON CONFLICT (hash) DO NOTHING",
               (stored.hash, run_id, json.dumps({"fixture": str(pid), "page": "1"}), at,
                len(body.get("response") or []), stored.file_path, stored.bytes_written))
    return stored.hash


def book_ask(db: psycopg.Connection, pid: int, at: datetime, payload_hash: str | None, results: int = 1) -> None:
    db.execute("INSERT INTO market.book_asks (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, results, quotes, "
               "payload_hash) VALUES (%s, %s, %s, 120, %s, 0, %s)",
               (pid, at, int((KO - at).total_seconds() // 60), results, payload_hash))


def test_the_book_reads_the_newest_ask_of_either_table_a_b_a_included(held: psycopg.Connection, seed: Seed,
                                                                         tmp_path: Path) -> None:
    from fbi.odds.book import build

    pid = 850031
    t1, t2, t3, t4, t5 = (KO - timedelta(hours=h) for h in (30, 20, 10, 5, 2))
    fixture_id, a = seed_capture(held, seed, tmp_path, pid, t1)
    b = refresh_payload(held, tmp_path, real_body(pid, bump="0.05"), pid, t2)
    book_ask(held, pid, t2, b)
    build(held, tmp_path, [fixture_id], apply=True, now=t2 + timedelta(minutes=1), commit=False)
    one = rows(held, fixture_id)[1]
    assert (one["payload_hash"], one["checked_at"], one["captured_at"]) == (b, t2, t2), "the refresh's newer answer"
    assert read_in_force(held, fixture_id).in_force.checked_at == t1, "while the Match Center keeps the capture's"  # type: ignore[union-attr]

    ask(held, pid, t3, a)  # the capture's next window: A again
    build(held, tmp_path, [fixture_id], apply=True, now=t3 + timedelta(minutes=1), commit=False)
    one = rows(held, fixture_id)[1]
    assert (one["payload_hash"], one["checked_at"], one["in_force_since"], one["captured_at"]) == (a, t3, t3, t1)

    book_ask(held, pid, t4, a)  # a refresh answered A too: RAW keeps no second copy
    build(held, tmp_path, [fixture_id], apply=True, now=t4 + timedelta(minutes=1), commit=False)
    one = rows(held, fixture_id)[1]
    assert (one["payload_hash"], one["checked_at"], one["in_force_since"]) == (a, t4, t3), "one unbroken run of A"

    book_ask(held, pid, t5, None, results=0)  # and then the provider withdrew the match
    report = build(held, tmp_path, [fixture_id], apply=True, now=t5 + timedelta(minutes=1), commit=False)
    assert report.states == {"withdrawn": 1} and rows(held, fixture_id) == {}


def test_without_a_book_ask_the_book_reads_exactly_what_quote_current_reads(held: psycopg.Connection, seed: Seed,
                                                                            tmp_path: Path) -> None:
    pid = 850041
    fixture_id, _ = seed_capture(held, seed, tmp_path, pid, KO - timedelta(hours=30))
    late = add_payload(held, seed, PayloadStore(tmp_path), real_body(pid, bump="0.1"), fixture=pid,
                       fetched_at=KO - timedelta(hours=20))
    ask(held, pid, KO - timedelta(hours=20), late)  # not extracted yet: the older one stands in
    assert locate_book_in_force(held, fixture_id) == locate_in_force(held, fixture_id)


# ── the budget, the floor and which matches ────────────────────────────────────────────────────────────────────────


async def test_the_refresh_stops_as_soon_as_the_provider_says_the_floor_is_reached(
        held: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    pids = (850051, 850052)
    at = KO - timedelta(minutes=118)
    sync_definitions(held)  # the bet registry the extractor keeps (production has it): the book never writes one
    ids = [add_fixture(held, seed, pid, KO) for pid in pids]
    calls: list[int] = []
    provider = provider_for(tmp_path, {pid: real_body(pid, name="copa_del_rey") for pid in pids}, calls=calls,
                            headers={"x-ratelimit-requests-limit": "75000", "x-ratelimit-requests-remaining": "5999"})
    report = await refresh(held, tmp_path, provider, [task(f, p, at) for f, p in zip(ids, pids, strict=True)], at=at,
                           floor=6000)
    assert calls == [pids[0]] and report.asked == 1, "one ask, then the provider's count said stop"
    assert report.stopped_early is not None and "5999" in report.stopped_early
    status = scalar(held.execute("SELECT status FROM raw.ingestion_runs WHERE id = %s", (report.run_id,)))
    assert status == "aborted" and len(rows(held, ids[0])) > 0, "the match asked still gets its book"


def test_todays_budget_counts_the_refreshes_our_quota_and_the_providers(held: psycopg.Connection, seed: Seed) -> None:
    at = datetime(2027, 3, 3, 15, 0, tzinfo=UTC)
    day = at.replace(hour=0)
    for minute in range(3):
        held.execute("INSERT INTO market.book_asks (provider_fixture_id, asked_at, minutes_to_ko, results) "
                     "VALUES (850061, %s, 100, 1)", (day + timedelta(hours=1, minutes=minute),))
    held.execute("INSERT INTO market.book_asks (provider_fixture_id, asked_at, minutes_to_ko, results) "
                 "VALUES (850061, %s, 100, 1)", (day - timedelta(minutes=5),))  # yesterday's
    held.execute("INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) VALUES ('api_football', %s, 1234, 60000) "
                 "ON CONFLICT (provider, quota_date) DO UPDATE SET spent = 1234", (at.date(),))
    record_reported(held, ReportedQuota(at - timedelta(minutes=1), 75000, 52000, 450, 400))
    record_reported(held, ReportedQuota(at - timedelta(minutes=9), 75000, 53000, 450, 400))  # older: changes nothing
    set_clock(FrozenClock(at))
    budget = budget_now(held, at=at, daily_budget=8000, reserve=6000, our_budget=60000, prematch_windows=(180,))
    assert (budget.spent_today, budget.ours_left, budget.provider_left) == (3, 60000 - 1234, 52000)
    assert budget.floor >= 6000 and budget.allowance == 8000 - 3


def test_the_refreshes_ask_the_captures_matches_that_the_provider_has_priced(held: psycopg.Connection, seed: Seed) -> None:
    at = datetime(2027, 3, 3, 12, 0, tzinfo=UTC)
    comp = scalar(held.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                               "is_tracked) VALUES (99001, 'Liga de prueba', 'league', 'club', 'domestic_league', true) "
                               "RETURNING id"))
    season = scalar(held.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id",
                                 (comp,)))

    def fixture(pid: int, minutes: int, status: str = "NS") -> int:
        return int(scalar(held.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
            "status_short) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (pid, season, seed.home_team_id, seed.away_team_id, at + timedelta(minutes=minutes), status))))

    priced, unpriced, far, started = fixture(850071, 100), fixture(850072, 100), fixture(850073, 6000), fixture(850074, -10, "1H")
    ko = at + timedelta(minutes=100)
    held.execute("INSERT INTO market.odds_asks (provider_fixture_id, asked_at, minutes_to_ko, results) VALUES "
                 "(850071, %s, 300, 1), (850072, %s, 300, 0)", (ko - timedelta(minutes=300), ko - timedelta(minutes=300)))
    held.execute("INSERT INTO market.book_asks (provider_fixture_id, asked_at, minutes_to_ko, results) VALUES (850071, %s, 200, 1)",
                 (ko - timedelta(minutes=200),))
    found = {c.fixture_id: c for c in candidates(held, at=at, points=refresh_only_points((180,)), tolerance=45)}
    assert priced in found and unpriced in found and far not in found and started not in found
    assert found[priced].priced and not found[unpriced].priced
    assert found[priced].last_asked == ko - timedelta(minutes=200), "the newest ask of either table"
    held.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (comp,))
    again = candidates(held, at=at, points=refresh_only_points((180,)), tolerance=45)
    assert not {c.fixture_id for c in again} & {priced, unpriced}, "a competition no longer followed is not asked"
