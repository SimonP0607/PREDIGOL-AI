"""The lanes of the daily request budget (plan PM, PM-04-01; BE-060): the table, the replay of the 36 measured days, the guard in
front of every request and its switch. Against fakes: no database, no network."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.plan import ProviderPlanSettings
from fbi.core.config.providers import ApiFootballSettings
from fbi.core.errors import QuotaExhaustedError
from fbi.providers import lanes as ln
from fbi.providers import quota as q
from fbi.providers.api_football import build as b
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "quota" / "pm_04_01_peticiones_por_dia_y_trabajo.csv"
OK_BODY = {"response": [{"fixture": {"id": 1}}], "errors": [], "paging": {"current": 1, "total": 1}}
DAY = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PLAN_LANES = ("directo", "cuotas", "alineaciones", "resultados", "calendario", "estadisticas_contexto", "referencia", "historicos",
              "ampliacion", "reparacion")


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


def measured() -> list[tuple[str, int, str, int]]:
    with DATA.open(encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        return [(r["day"], 0, r["job"], int(r["requests"])) for r in rows]


# ── the table ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_table_is_the_ten_lanes_of_the_plan_in_its_order_and_the_lane_of_the_unlisted() -> None:
    names = [lane.name for lane in ln.DEFAULT_LANES]
    assert names == [*PLAN_LANES, ln.NO_LANE]
    assert [lane.priority for lane in ln.DEFAULT_LANES] == list(range(1, 12))
    assert [lane.name for lane in ln.DEFAULT_LANES if lane.vital] == ["directo", "cuotas", "alineaciones", "resultados"]


def test_every_job_that_asked_the_provider_in_the_measured_days_has_its_lane() -> None:
    asked = {job for _d, _h, job, n in measured() if n >= 10}
    assert asked <= set(ln.LANE_OF_JOB), sorted(asked - set(ln.LANE_OF_JOB))
    assert set(ln.LANE_OF_JOB.values()) == set(PLAN_LANES)
    assert q.PROVISIONAL_LANES is ln.LANE_OF_JOB, "PM-01-02 counts each request in the lane the guard decides on"


def test_a_table_that_puts_a_job_in_two_lanes_or_lacks_the_unlisted_lane_is_refused() -> None:
    twice = (ln.Lane("a", 1, 10, True, ("x",), "A"), ln.Lane("b", 2, 10, False, ("x",), "B"), ln.Lane(ln.NO_LANE, 3, 1, False, (), "-"))
    with pytest.raises(ValueError, match="two lanes"):
        ln.LanePolicy(twice)
    with pytest.raises(ValueError, match="sin_carril"):
        ln.LanePolicy((ln.Lane("a", 1, 10, True, ("x",), "A"),))


@pytest.mark.parametrize(("text", "ceilings", "ignored"), [
    ("", {}, []),
    ("referencia=9000, historicos=6000", {"referencia": 9000, "historicos": 6000}, []),
    ("REFERENCIA = 9_000", {"referencia": 9000}, []),
    ("referencia=9000,nadie=5,cuotas=mucho,", {"referencia": 9000}, ["nadie=5", "cuotas=mucho"]),
])
def test_ceilings_from_app_env_never_stop_the_worker(text: str, ceilings: dict[str, int], ignored: list[str]) -> None:
    assert ln.parse_ceilings(text) == (ceilings, ignored)
    policy, rest = ln.LanePolicy.from_settings(text)
    assert rest == ignored
    assert all(policy.ceilings[name] == n for name, n in ceilings.items())


@pytest.mark.parametrize(("word", "mode"), [(None, "off"), ("", "off"), ("off", "off"), ("0", "off"), ("enforced", "off"),
                                            ("measure", "measure"), ("MEDIR", "measure"), ("shadow", "measure"),
                                            ("enforce", "enforce"), ("on", "enforce")])
def test_the_switch_is_read_leniently_and_anything_unknown_is_off(word: str | None, mode: str) -> None:
    assert ln.lane_mode(word) == mode


def test_the_switch_is_off_by_default_and_read_from_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_APIFOOTBALL_LANES", raising=False)
    assert ProviderPlanSettings(_env_file=None).lanes_mode == "off"  # type: ignore[call-arg]
    monkeypatch.setenv("FBI_APIFOOTBALL_LANES", "measure")
    monkeypatch.setenv("FBI_APIFOOTBALL_LANE_CEILINGS", "referencia=9000")
    plan = ProviderPlanSettings(_env_file=None)  # type: ignore[call-arg]
    assert plan.lanes_mode == "measure" and plan.lane_ceilings == "referencia=9000"
    monkeypatch.setenv("FBI_APIFOOTBALL_LANES", "a typo")
    assert ProviderPlanSettings(_env_file=None).lanes_mode == "off"  # type: ignore[call-arg]


def test_the_switch_is_documented_in_the_server_template() -> None:
    text = (Path(__file__).resolve().parents[2] / "deploy" / "vps" / "app.env.example").read_text(encoding="utf-8")
    assert "# FBI_APIFOOTBALL_LANES=off" in text and "# FBI_APIFOOTBALL_LANE_CEILINGS=" in text
    assert "PM_04_CARRILES_DEL_CUPO.md" in text


# ── the decision ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_lane_is_refused_only_when_its_own_count_would_pass_its_ceiling() -> None:
    policy = ln.LanePolicy()
    assert policy.decide("referencia", lane_spent={"referencia": 14_999}).allowed
    refused = policy.decide("referencia", lane_spent={"referencia": 15_000})
    assert (refused.allowed, refused.reason, refused.lane_spent, refused.ceiling) == (False, "lane_ceiling", 15_000, 15_000)
    assert not policy.decide("referencia", lane_spent={"referencia": 14_999}, calls=2).allowed


def test_the_matches_in_play_are_never_held_back_by_what_another_lane_spent() -> None:
    policy = ln.LanePolicy()
    everything_else_spent = {lane.name: lane.ceiling for lane in ln.DEFAULT_LANES if lane.name != "directo"}
    assert policy.decide("directo", lane_spent={**everything_else_spent, "directo": 5_606}).allowed
    assert policy.decide("cuotas", lane_spent={**everything_else_spent, "cuotas": 3_217}).allowed
    assert not policy.decide("cuotas", lane_spent={"cuotas": 10_000}).allowed, "its own ceiling, and only it"


def test_a_lane_the_table_does_not_know_is_bound_by_the_unlisted_lane() -> None:
    policy = ln.LanePolicy()
    decision = policy.decide("jugadores_y_referencia", lane_spent={ln.NO_LANE: 2_000})
    assert (decision.lane, decision.allowed) == (ln.NO_LANE, False)


# ── the replay of the measured days: switching the lanes on changes nothing that works today ───────────────────────────────


def test_no_measured_day_would_have_been_limited_by_the_initial_table() -> None:
    days = ln.replay(measured(), ln.LanePolicy())
    assert len(days) == 36 and days[0].day == "2026-10-15" and days[-1].day == "2026-11-19"
    assert [d.day for d in days if d.limited] == [], "15 Oct - 19 Nov 2026, the 29 Oct included"
    by_day: dict[str, int] = {}
    for day, _h, _job, n in measured():
        by_day[day] = by_day.get(day, 0) + n
    assert {d.day: d.total for d in days} == by_day, "every request replayed, none lost"
    biggest = max(days, key=lambda d: d.total)
    assert (biggest.day, biggest.total) == ("2026-10-26", 23_324), "the largest day of the month, a Monday"
    for lane in ln.DEFAULT_LANES:  # each ceiling covers the lane's largest day, with room
        top = max(d.spent.get(lane.name, 0) for d in days)
        assert top <= lane.ceiling, (lane.name, top)


def test_the_plan_targets_would_cut_the_weekly_rounds_until_pm_04_03_and_04_04_land() -> None:
    """Why the table is not the plan's targets yet: with referencia at 9,000 and históricos at 6,000, the Monday and Tuesday
    rounds of the measured month would have been cut - the targets wait for the trims and fourteen measured days."""
    targets, _ = ln.LanePolicy.from_settings("referencia=9000,historicos=6000,estadisticas_contexto=2000")
    days = ln.replay(measured(), targets)
    limited = {d.day: d.limited for d in days if d.limited}
    assert "2026-10-20" in limited and "referencia" in limited["2026-10-20"]
    assert "2026-11-16" in limited and "historicos" in limited["2026-11-16"]
    assert all(not {"directo", "cuotas", "alineaciones", "resultados"} & set(v) for v in limited.values()), "never a vital lane"


# ── the guard ────────────────────────────────────────────────────────────────────────────────────────────────────────────


class FakeDb:
    """Answers the guard's read with ``rows`` (lane, requests); counts the reads; can fail."""

    def __init__(self, rows: dict[str, int] | None = None) -> None:
        self.rows = dict(rows or {})
        self.reads: list[dict[str, Any]] = []
        self.fail = False

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        db = self

        class Cur:
            def __enter__(self) -> Cur:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def execute(self, sql: str, params: dict[str, Any]) -> None:
                if db.fail:
                    raise RuntimeError("database down")
                assert "raw.provider_endpoint_usage" in sql
                db.reads.append(params)

            def fetchall(self) -> list[tuple[str, int]]:
                return list(db.rows.items())

        class Conn:
            def cursor(self) -> Cur:
                return Cur()

        yield Conn()

    def connect(self) -> Any:
        return self._conn()


class Tick:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def guard(db: FakeDb, mode: ln.LaneMode, *, tick: Tick | None = None, counter: q.EndpointUsageCounter | None = None,
          ceilings: str = "") -> q.LaneGuard:
    policy, _ = ln.LanePolicy.from_settings(ceilings)
    return q.LaneGuard(policy=policy, mode=mode, connect=db.connect, counter=counter, clock=tick or Tick())


def test_measure_decides_and_counts_but_refuses_nothing() -> None:
    db = FakeDb({"referencia": 15_000})
    g = guard(db, "measure")
    q.bind_usage_job("reference_refresh")
    decision = g.check()
    assert decision.allowed is False and decision.reason == "lane_ceiling"
    g.check()
    assert g.would_limit == {"referencia": 2}


def test_enforce_refuses_a_lane_past_its_ceiling_as_a_spent_budget_and_lets_the_others_through() -> None:
    db = FakeDb({"referencia": 15_000, "directo": 4_000})
    g = guard(db, "enforce")
    q.bind_usage_job("reference_refresh")
    with pytest.raises(q.LaneLimitedError, match="referencia") as caught:
        g.check()
    assert isinstance(caught.value, QuotaExhaustedError), "the jobs already stop on a spent budget"
    q.bind_usage_job("live_odds_capture")
    assert g.check().allowed
    q.bind_usage_job("odds_capture")
    assert g.check().allowed


def test_the_counts_are_read_at_most_every_fifteen_seconds_and_what_was_let_through_is_added_meanwhile() -> None:
    tick = Tick()
    db = FakeDb({"calendario": 1_498})
    g = guard(db, "enforce", tick=tick)
    q.bind_usage_job("fixtures_sync")
    g.check()
    g.check()
    with pytest.raises(q.LaneLimitedError):
        g.check()  # 1,498 read + 2 let through = the ceiling of 1,500
    assert len(db.reads) == 1
    tick.t = 15.0
    db.rows = {"calendario": 10}
    assert g.check().allowed and len(db.reads) == 2


def test_what_this_process_still_holds_in_memory_counts_too() -> None:
    usage = q.EndpointUsageCounter(connect=FakeDb().connect, clock=Tick(), flush_every=10_000)
    q.bind_usage_job("fixtures_sync")
    for _ in range(5):
        usage.record("/fixtures")
    g = guard(FakeDb({"calendario": 1_495}), "enforce", counter=usage)
    with pytest.raises(q.LaneLimitedError):
        g.check()


def test_the_day_starts_again_at_midnight_utc(frozen: FrozenClock) -> None:
    db = FakeDb({"historicos": 8_000})
    g = guard(db, "enforce")
    q.bind_usage_job("historical_backfill")
    with pytest.raises(q.LaneLimitedError):
        g.check()
    frozen.advance(hours=12)  # 00:00 UTC of the next day: a new read, at once
    db.rows = {}
    assert g.check().allowed
    assert [r["day"] for r in db.reads] == [DAY.date(), DAY.date() + timedelta(days=1)]


def test_a_count_that_cannot_be_read_never_costs_a_request() -> None:
    db = FakeDb()
    db.fail = True
    g = guard(db, "enforce")
    q.bind_usage_job("reference_refresh")
    assert g.check().allowed


# ── in the client ────────────────────────────────────────────────────────────────────────────────────────────────────────


def client(tmp_path: Path, handler: Any, lanes: q.LaneGuard | None, slept: list[float]) -> ApiFootballClient:
    settings = ApiFootballSettings(key="k" * 32, plan="pro", daily_budget=100, max_retries=2, timeout_seconds=1.0)

    async def no_sleep(s: float) -> None:
        slept.append(s)

    return ApiFootballClient(settings, PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
                             rate_limiter=TokenBucket(settings.per_minute_limit, sleep=no_sleep), quota=DailyQuota(budget=100),
                             sleep=no_sleep, lanes=lanes)


async def test_a_refused_lane_spends_nothing_and_sends_nothing_and_the_live_lane_goes_on_without_waiting(tmp_path: Path) -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200, json=OK_BODY)

    slept: list[float] = []
    c = client(tmp_path, handler, guard(FakeDb({"referencia": 15_000}), "enforce"), slept)
    async with c:
        q.bind_usage_job("reference_refresh")
        with pytest.raises(q.LaneLimitedError):
            await c.get("/players/teams", {"player": 1})
        assert sent == [] and c._quota.spent == 0
        q.bind_usage_job("live_match_capture")
        assert (await c.get("/fixtures", {"ids": "1"})).http_status == 200
    assert sent == ["/fixtures"] and c._quota.spent == 1 and slept == []


async def test_without_a_guard_the_client_is_what_it_was(tmp_path: Path) -> None:
    c = client(tmp_path, lambda r: httpx.Response(200, json=OK_BODY), None, [])
    q.bind_usage_job("reference_refresh")
    async with c:
        assert (await c.get("/players/teams", {"player": 1})).http_status == 200


def test_build_gives_no_guard_while_off_and_one_per_process_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b, "_lane_guard", None)
    monkeypatch.setattr(b, "_usage_counter", None)
    monkeypatch.setattr("atexit.register", lambda *a: None)

    class Plan:
        lanes_mode = "off"
        lane_ceilings = "referencia=9000"
        effective_budget = 60_000
        emergency_reserve = 7_000
        dynamic_limits_on = False

    monkeypatch.setattr(b, "settings", type("S", (), {"provider_plan": Plan()})())
    assert b.build_lane_guard() is None
    Plan.lanes_mode = "measure"
    first = b.build_lane_guard()
    assert first is not None and first.mode == "measure" and first.policy.ceilings["referencia"] == 9000
    assert b.build_lane_guard() is first
    monkeypatch.setattr(b, "_lane_guard", None)
    monkeypatch.setenv(b.USAGE_SWITCH, "off")
    monkeypatch.setattr(b, "_usage_counter", None)
    assert b.build_lane_guard() is None, "no counts to read without the usage counter"


# ── the read-only script ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_report_marks_a_day_over_a_ceiling_and_says_whether_a_vital_lane_was_cut(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import quota_lanes as script

    class Cur:
        def __enter__(self) -> Cur:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: dict[str, Any]) -> None:
            assert "raw.provider_endpoint_usage" in sql and params["until"] == DAY.date()

        def fetchall(self) -> list[tuple[Any, str, int]]:
            return [(DAY.date() - timedelta(days=2), "referencia", 14_000), (DAY.date() - timedelta(days=2), "directo", 3_000),
                    (DAY.date() - timedelta(days=1), "referencia", 15_200)]

    class Conn:
        def cursor(self) -> Cur:
            return Cur()

    script.report(Conn(), 14)
    out = capsys.readouterr().out
    assert "2026-11-18 | 17000 |" in out and "2026-11-19 | 15200 |" in out and "referencia:200" in out
    assert "# 2 day(s): 1 with a lane limited, 0 with a vital lane limited" in out
