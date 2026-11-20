"""Requests by endpoint, lane and job (plan PM, PM-01-02): counted in memory where the daily budget is spent, written at most once a
minute, never at the cost of a request. Against fakes: no database, no network. The database side is in
``tests/integration/test_provider_endpoint_usage_db.py``."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.core.errors import QuotaExhaustedError
from fbi.providers import quota as q
from fbi.providers.api_football import build as b
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore

OK_BODY = {"response": [{"fixture": {"id": 1}}], "errors": [], "paging": {"current": 1, "total": 1}}
DAY = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen() -> Iterator[FrozenClock]:
    clock = FrozenClock(DAY)
    set_clock(clock)
    q.bind_usage_job(None)
    q.bind_usage_lane(None)
    yield clock
    set_clock(SystemClock())
    q.bind_usage_job(None)
    q.bind_usage_lane(None)


class FakeCursor:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        if self.db.fail:
            raise RuntimeError("database down")
        self.db.writes.append(params)


class FakeDb:
    """What the counter wrote: one entry per statement, its parameters."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        self.fail = False

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        class Conn:
            def cursor(inner) -> FakeCursor:  # noqa: N805 - a stand-in
                return FakeCursor(self)
        yield Conn()

    def connect(self) -> Any:
        return self._conn()

    def totals(self) -> dict[tuple[Any, ...], int]:
        out: dict[tuple[Any, ...], int] = {}
        for w in self.writes:
            keys = zip(w["days"], w["endpoints"], w["lanes"], w["jobs"], strict=True)
            for key, n in zip(keys, w["counts"], strict=True):
                out[key] = out.get(key, 0) + n
        return out


class Tick:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def counter(db: FakeDb, tick: Tick, **kw: Any) -> q.EndpointUsageCounter:
    return q.EndpointUsageCounter(connect=db.connect, clock=tick, **kw)


# ── the tags ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("raw", "clean"), [
    ("/fixtures", "/fixtures"), ("fixtures", "/fixtures"), ("/Fixtures/", "/fixtures"), ("/fixtures?id=1", "/fixtures"),
    ("/players/squads", "/players/squads"), ("/odds/live", "/odds/live"), ("/teams/statistics", "/teams/statistics"),
    ("/status", "/status"), ("/odds/../x y", "/otro"), ("/" + "a" * 80, "/otro"), ("/fixtures;drop", "/otro"),
])
def test_an_endpoint_is_a_plain_lowercase_path(raw: str, clean: str) -> None:
    assert q.normalise_endpoint(raw) == clean


def test_without_a_run_a_request_counts_under_no_job_and_no_lane() -> None:
    assert q.current_usage_tags() == (q.NO_LANE, q.NO_JOB)


def test_the_job_gives_the_provisional_lane_of_the_plan() -> None:
    q.bind_usage_job("reference_refresh")
    assert q.current_usage_tags() == ("referencia", "reference_refresh")
    q.bind_usage_job("live_odds_capture")
    assert q.current_usage_tags() == ("directo", "live_odds_capture")
    q.bind_usage_job("a_job_nobody_listed")
    assert q.current_usage_tags() == (q.NO_LANE, "a_job_nobody_listed")


def test_a_declared_lane_wins_over_the_table_pm_04_01_contract() -> None:
    q.bind_usage_job("reference_refresh")
    q.bind_usage_lane("Jugadores y referencia")
    assert q.current_usage_tags() == ("jugadores_y_referencia", "reference_refresh")
    q.bind_usage_lane(None)
    assert q.current_usage_tags() == ("referencia", "reference_refresh")


def test_every_provisional_lane_is_one_of_the_ten_of_the_plan() -> None:
    lanes = {"directo", "cuotas", "alineaciones", "resultados", "calendario", "estadisticas_contexto", "referencia", "historicos",
             "ampliacion", "reparacion"}
    assert set(q.PROVISIONAL_LANES.values()) == lanes
    measured = {"reference_refresh", "live_odds_capture", "live_match_capture", "historical_backfill", "odds_capture",
                "fixtures_sync", "context_refresh", "odds_book_refresh", "context_due", "prematch_lineups", "final_prematch",
                "results_repair", "post_match_detail", "lineup_watch", "results_sync", "catalogue_refresh"}
    assert measured <= set(q.PROVISIONAL_LANES), "every job that asked the provider in the 30 days measured on 20 Nov 2026"


async def test_each_task_keeps_its_own_job() -> None:
    seen: dict[str, tuple[str, str]] = {}

    async def job(name: str) -> None:
        q.bind_usage_job(name)
        await asyncio.sleep(0)
        seen[name] = q.current_usage_tags()

    await asyncio.gather(job("odds_capture"), job("fixtures_sync"), job("reference_refresh"))
    assert seen == {"odds_capture": ("cuotas", "odds_capture"), "fixtures_sync": ("calendario", "fixtures_sync"),
                    "reference_refresh": ("referencia", "reference_refresh")}
    assert q.current_usage_tags() == (q.NO_LANE, q.NO_JOB), "a task's job does not leak into its parent"


# ── the counter ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_requests_wait_in_memory_and_one_statement_writes_them_once_a_minute() -> None:
    db, tick = FakeDb(), Tick()
    c = counter(db, tick)
    q.bind_usage_job("odds_capture")
    for _ in range(50):
        c.record("/odds")
    c.record("/fixtures")
    assert db.writes == [] and c.pending_requests == 51, "no write per request"
    tick.t = 59.9
    c.record("/odds")
    assert db.writes == []
    tick.t = 60.0
    c.record("/odds")
    assert len(db.writes) == 1 and c.pending_requests == 0
    assert db.totals() == {(DAY.date(), "/fixtures", "cuotas", "odds_capture"): 1, (DAY.date(), "/odds", "cuotas", "odds_capture"): 52}
    assert db.writes[0]["endpoints"] == sorted(db.writes[0]["endpoints"]), "keys sorted: two processes lock them in one order"


def test_a_flush_that_fails_keeps_the_counts_for_the_next_and_never_raises() -> None:
    db, tick = FakeDb(), Tick()
    c = counter(db, tick)
    c.record("/status")
    db.fail = True
    assert c.flush() == 0
    assert c.pending_requests == 1
    c.record("/status")
    db.fail = False
    assert c.flush() == 2
    assert db.totals() == {(DAY.date(), "/status", q.NO_LANE, q.NO_JOB): 2}


def test_the_day_is_the_utc_day_of_the_request(frozen: FrozenClock) -> None:
    db, tick = FakeDb(), Tick()
    c = counter(db, tick)
    frozen._at = datetime(2026, 11, 20, 23, 59, 59, tzinfo=UTC)
    c.record("/odds/live")
    frozen._at = datetime(2026, 11, 21, 0, 0, 1, tzinfo=UTC)
    c.record("/odds/live")
    c.flush()
    assert {k[0].isoformat(): n for k, n in db.totals().items()} == {"2026-11-20": 1, "2026-11-21": 1}


def test_memory_is_bounded_and_what_does_not_fit_is_counted_as_dropped() -> None:
    db, tick = FakeDb(), Tick()
    c = counter(db, tick, max_keys=3)
    for e in ("/a", "/b", "/c", "/d", "/a"):
        c.record(e)
    assert c.pending_requests == 4 and c.dropped == 1
    c.flush()
    assert sum(db.totals().values()) == 4


def test_threads_recording_at_once_lose_nothing() -> None:
    db, tick = FakeDb(), Tick()
    c = counter(db, tick, flush_every=0.0)  # every record may flush: the worst case for the lock
    jobs = ["odds_capture", "reference_refresh", "live_match_capture", "fixtures_sync"]

    def work(job: str) -> None:
        q.bind_usage_job(job)
        for i in range(2_000):
            c.record("/odds" if i % 2 else "/fixtures")

    threads = [threading.Thread(target=work, args=(job,)) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c.flush()
    totals = db.totals()
    assert sum(totals.values()) == 8_000
    assert {k[3]: 0 for k in totals} == dict.fromkeys(jobs, 0)
    for job in jobs:
        assert sum(n for k, n in totals.items() if k[3] == job) == 2_000


# ── the client ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def client(tmp_path: Path, handler: Any, usage: q.EndpointUsageCounter | None, *, budget: int = 100,
           max_retries: int = 2) -> ApiFootballClient:
    settings = ApiFootballSettings(key="k" * 32, plan="pro", daily_budget=budget, max_retries=max_retries, timeout_seconds=1.0)

    async def no_sleep(_s: float) -> None:
        return None

    return ApiFootballClient(settings, PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
                             rate_limiter=TokenBucket(settings.per_minute_limit, sleep=no_sleep), quota=DailyQuota(budget=budget),
                             sleep=no_sleep, usage=usage)


async def test_every_attempt_the_budget_accepts_is_counted_and_close_writes_them(tmp_path: Path) -> None:
    db, tick = FakeDb(), Tick()
    usage = counter(db, tick)
    answers = iter([httpx.Response(500), httpx.Response(200, json=OK_BODY), httpx.Response(200, json=OK_BODY)])
    c = client(tmp_path, lambda r: next(answers), usage)
    q.bind_usage_job("fixtures_sync")
    async with c:
        await c.get("/fixtures", {"date": "2026-11-20"})  # 500, then 200: two requests left the building
        await c.get("/standings", {"league": 39, "season": 2026})
        assert db.writes == [], "nothing written while the minute is not over"
    assert db.totals() == {(DAY.date(), "/fixtures", "calendario", "fixtures_sync"): 2,
                           (DAY.date(), "/standings", "calendario", "fixtures_sync"): 1}
    assert c._quota.spent == 3, "the same three the daily budget counted"


async def test_a_request_the_budget_refuses_is_not_counted(tmp_path: Path) -> None:
    db, tick = FakeDb(), Tick()
    usage = counter(db, tick)
    c = client(tmp_path, lambda r: httpx.Response(200, json=OK_BODY), usage, budget=1)
    async with c:
        await c.get("/odds", {"fixture": 1})
        with pytest.raises(QuotaExhaustedError):
            await c.get("/odds", {"fixture": 2})
    assert sum(db.totals().values()) == 1


async def test_a_counter_that_breaks_never_costs_the_request(tmp_path: Path) -> None:
    class Broken(q.EndpointUsageCounter):
        def record(self, endpoint: str, calls: int = 1) -> None:
            raise RuntimeError("boom")

        def flush(self) -> int:
            raise RuntimeError("boom")

    c = client(tmp_path, lambda r: httpx.Response(200, json=OK_BODY), Broken(connect=FakeDb().connect))
    async with c:
        response = await c.get("/odds", {"fixture": 1})
    assert response.http_status == 200


async def test_without_a_counter_the_client_counts_nothing_and_works(tmp_path: Path) -> None:
    c = client(tmp_path, lambda r: httpx.Response(200, json=OK_BODY), None)
    async with c:
        assert (await c.get("/odds", {"fixture": 1})).http_status == 200


# ── the switch ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "on"), [(None, True), ("on", True), ("1", True), ("", True), ("0", False), ("off", False),
                                           ("OFF", False), ("false", False), ("no", False)])
def test_the_switch_is_on_unless_it_says_off(monkeypatch: pytest.MonkeyPatch, value: str | None, on: bool) -> None:
    if value is None:
        monkeypatch.delenv(b.USAGE_SWITCH, raising=False)
    else:
        monkeypatch.setenv(b.USAGE_SWITCH, value)
    assert b.usage_enabled() is on


def test_one_counter_per_process_and_none_while_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b, "_usage_counter", None)
    monkeypatch.setattr(b.atexit, "register", lambda *a: None)
    monkeypatch.setenv(b.USAGE_SWITCH, "off")
    assert b.build_usage_counter() is None
    monkeypatch.setenv(b.USAGE_SWITCH, "on")
    first = b.build_usage_counter()
    assert first is not None and b.build_usage_counter() is first


def test_the_switch_is_documented_in_the_server_template() -> None:
    example = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "app.env.example"
    text = example.read_text(encoding="utf-8")
    assert f"# {b.USAGE_SWITCH}=on" in text and "PM_01_02_CONSUMO_POR_ENDPOINT.md" in text
