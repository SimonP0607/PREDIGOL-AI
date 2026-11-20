"""Dynamic limits, automatic pauses and the emergency reserve over the lanes (plan PM, PM-04-02; BE-061), and the account's pause:
an error about the ACCOUNT inside an HTTP 200 stops every request of the process (the correction of PM-01-03). Against fakes: no
database, no network."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.plan import ProviderPlanSettings
from fbi.core.config.providers import ApiFootballSettings
from fbi.core.errors import CircuitOpenError, ProviderAccountError, ProviderError, RateLimitError
from fbi.providers import lanes as ln
from fbi.providers import quota as q
from fbi.providers.api_football import build as b
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.circuit import AccountPause, account_refusal
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore

DAY29 = Path(__file__).resolve().parents[1] / "fixtures" / "quota" / "pm_04_02_29_octubre_por_hora.csv"
OK_BODY = {"response": [{"fixture": {"id": 1}}], "errors": [], "paging": {"current": 1, "total": 1}}
NOON = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
BUDGET = 60_000
VITAL = ("directo", "cuotas", "alineaciones", "resultados")


@pytest.fixture(autouse=True)
def frozen() -> Iterator[FrozenClock]:
    clock = FrozenClock(NOON)
    set_clock(clock)
    q.bind_usage_job(None)
    q.bind_usage_lane(None)
    yield clock
    set_clock(SystemClock())
    q.bind_usage_job(None)
    q.bind_usage_lane(None)


def dynamic(reserve: int = ln.DEFAULT_EMERGENCY_RESERVE) -> ln.LanePolicy:
    return ln.LanePolicy.from_settings(budget=BUDGET, reserve=reserve, dynamic=True)[0]


def at(hour: int, minute: int = 0) -> datetime:
    return NOON.replace(hour=hour, minute=minute)


# ── the thresholds ───────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("total", "paused"), [
    (35_999, set()),
    (36_000, {"historicos", "ampliacion", "reparacion", "sin_carril"}),
    (44_999, {"historicos", "ampliacion", "reparacion", "sin_carril"}),
    (45_000, {"historicos", "ampliacion", "reparacion", "sin_carril", "referencia"}),
    (52_800, {"historicos", "ampliacion", "reparacion", "sin_carril", "referencia", "calendario", "estadisticas_contexto"}),
])
def test_the_lanes_pause_lowest_first_at_60_75_and_88_percent(total: int, paused: set[str]) -> None:
    policy = dynamic()
    refused = {lane.name for lane in policy.lanes
               if not policy.decide(lane.name, lane_spent={}, total_spent=total, at=at(12)).allowed}
    assert refused == paused


def test_the_vital_lanes_never_pause_and_alone_spend_the_emergency_reserve() -> None:
    policy = dynamic()
    for name in VITAL:
        assert policy.decide(name, lane_spent={}, total_spent=59_999, at=at(4, 30)).allowed, name
    decision = policy.decide("calendario", lane_spent={}, total_spent=52_999 - 1, at=at(12))
    assert decision.allowed is False and decision.reason == "paused_88"
    reserve_only = ln.LanePolicy.from_settings(budget=BUDGET, reserve=20_000, dynamic=True)[0]
    blocked = reserve_only.decide("calendario", lane_spent={}, total_spent=40_000, at=at(12))
    assert (blocked.allowed, blocked.reason) == (False, "emergency_reserve"), "the reserve binds below the 88 % pause too"


def test_no_fill_runs_between_0350_and_0500_utc() -> None:
    policy = dynamic()
    for name in ("historicos", "ampliacion"):
        assert policy.decide(name, lane_spent={}, total_spent=0, at=at(3, 49)).allowed
        assert policy.decide(name, lane_spent={}, total_spent=0, at=at(3, 50)).reason == "quiet_hours"
        assert policy.decide(name, lane_spent={}, total_spent=0, at=at(4, 59)).reason == "quiet_hours"
        assert policy.decide(name, lane_spent={}, total_spent=0, at=at(5, 0)).allowed
    assert policy.decide("referencia", lane_spent={}, total_spent=0, at=at(4)).allowed, "only the fills wait"


def test_without_the_dynamic_limits_only_the_ceilings_decide() -> None:
    policy = ln.LanePolicy.from_settings(budget=BUDGET, reserve=7_000, dynamic=False)[0]
    assert policy.decide("historicos", lane_spent={}, total_spent=59_000, at=at(4)).allowed


def test_a_table_where_a_vital_lane_would_pause_is_refused() -> None:
    lanes = tuple(ln.Lane(x.name, x.priority, x.ceiling, x.vital, x.jobs, x.label,
                          0.5 if x.name == "directo" else x.pause_at, x.quiet) for x in ln.DEFAULT_LANES)
    with pytest.raises(ValueError, match="vital lane never pauses"):
        ln.LanePolicy(lanes, budget=BUDGET, dynamic=True)


def test_the_switches_are_off_by_default_and_the_reserve_is_seven_thousand(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FBI_APIFOOTBALL_DYNAMIC_LIMITS", "FBI_APIFOOTBALL_EMERGENCY_RESERVE"):
        monkeypatch.delenv(name, raising=False)
    plan = ProviderPlanSettings(_env_file=None)  # type: ignore[call-arg]
    assert plan.dynamic_limits_on is False and plan.emergency_reserve == 7_000
    monkeypatch.setenv("FBI_APIFOOTBALL_DYNAMIC_LIMITS", "on")
    assert ProviderPlanSettings(_env_file=None).dynamic_limits_on is True  # type: ignore[call-arg]
    text = (Path(__file__).resolve().parents[2] / "deploy" / "vps" / "app.env.example").read_text(encoding="utf-8")
    for line in ("# FBI_APIFOOTBALL_DYNAMIC_LIMITS=off", "# FBI_APIFOOTBALL_EMERGENCY_RESERVE=7000",
                 "# FBI_APIFOOTBALL_ACCOUNT_GUARD=on", "# FBI_APIFOOTBALL_ACCOUNT_PAUSE_SECONDS=900"):
        assert line in text, line


# ── the guard over the day ───────────────────────────────────────────────────────────────────────────────────────────────


class FakeDb:
    def __init__(self, lanes: dict[str, int], total: int) -> None:
        self.lanes, self.total = dict(lanes), total
        self.sql: list[str] = []

    def connect(self) -> Any:
        db = self

        class Cur:
            last = ""

            def __enter__(self) -> Cur:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def execute(self, sql: str, params: dict[str, Any]) -> None:
                db.sql.append(sql)
                Cur.last = sql

            def fetchall(self) -> list[tuple[str, int]]:
                return list(db.lanes.items())

            def fetchone(self) -> tuple[int] | None:
                return (db.total,)

        class Conn:
            def __enter__(self) -> Conn:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def cursor(self) -> Cur:
                return Cur()

        return Conn()


class Tick:
    t = 0.0

    def __call__(self) -> float:
        return self.t


def test_the_guard_reads_the_budget_total_and_pauses_the_reference_at_75_percent_then_resumes_at_midnight(
    frozen: FrozenClock,
) -> None:
    db = FakeDb({"referencia": 9_000, "directo": 3_000}, total=45_100)
    tick = Tick()
    g = q.LaneGuard(policy=dynamic(), mode="enforce", connect=db.connect, counter=None, clock=tick)
    q.bind_usage_job("reference_refresh")
    with pytest.raises(q.LaneLimitedError, match="75 % of the budget"):
        g.check()
    assert any("raw.provider_quota" in s for s in db.sql), "the total is the budget's own count"
    q.bind_usage_job("live_odds_capture")
    assert g.check().allowed
    frozen.advance(hours=12)  # 00:00 UTC of the next day
    db.lanes, db.total = {}, 0
    q.bind_usage_job("reference_refresh")
    assert g.check().allowed


def test_the_total_never_reads_below_what_the_lanes_already_counted() -> None:
    db = FakeDb({"referencia": 40_000}, total=0)
    g = q.LaneGuard(policy=dynamic(), mode="enforce", connect=db.connect, counter=None, clock=Tick())
    q.bind_usage_job("historical_backfill")
    with pytest.raises(q.LaneLimitedError, match="60 %"):
        g.check()


# ── the simulation of 29 Oct 2026 ────────────────────────────────────────────────────────────────────────────────────────


def day29(*, account_guard: bool) -> list[tuple[str, int, str, int]]:
    """Every request that left on 29 Oct 2026, by hour and job: ``api_calls`` plus, for the two captures that do not count their
    failed attempts (OPS-009), their errors - 60,042 in all, the 60,000 of the budget. With the account's pause, the refused hours
    (04:45 to 21:31) send one request every 15 minutes: four an hour."""
    rows: list[tuple[str, int, str, int]] = []
    with DAY29.open(encoding="utf-8") as fh:
        for r in csv.DictReader(line for line in fh if not line.startswith("#")):
            hour, job = int(r["hour"]), r["job"]
            sent = int(r["api_calls"]) + (int(r["errors"]) if job in ("odds_capture", "live_odds_capture") else 0)
            if account_guard and 5 <= hour <= 21:
                continue
            rows.append(("2026-10-29", hour, job, sent))
    if account_guard:
        rows += [("2026-10-29", hour, "odds_capture", 4) for hour in range(5, 22)]
    return rows


def test_29_oct_as_it_was_the_budget_ran_out_at_21h_and_stopped_everything() -> None:
    rows = day29(account_guard=False)
    assert sum(n for *_x, n in rows) == 60_042
    no_lanes = ln.LanePolicy(tuple(ln.Lane(x.name, x.priority, 10**9, x.vital, x.jobs, x.label) for x in ln.DEFAULT_LANES))
    (day,) = ln.replay(rows, no_lanes, daily_budget=BUDGET)
    assert sum(day.refused.values()) == 42, "what was asked after 21:32 UTC, every lane alike"


def test_29_oct_with_the_lanes_alone_the_live_lane_lasts_the_day_but_the_odds_burn_their_ceiling() -> None:
    (day,) = ln.replay(day29(account_guard=False), dynamic(), daily_budget=BUDGET)
    assert day.refused.get("directo", 0) == 0, "the matches in play are followed to 23:59"
    assert day.total - sum(day.refused.values()) < BUDGET - ln.DEFAULT_EMERGENCY_RESERVE, "the budget is never spent"
    assert day.refused["cuotas"] > 30_000, "refusals of a lapsed account still fill the odds lane: why the pause is needed"


def test_29_oct_with_the_account_pause_live_and_odds_go_on_to_the_end_of_the_day() -> None:
    """The acceptance criterion of PM-04-02: in the simulation of 29 Oct, the live lane and the odds keep going to the end of the
    day - nothing of theirs is refused, by a lane or by the budget, and the budget keeps more than 50,000 requests."""
    (day,) = ln.replay(day29(account_guard=True), dynamic(), daily_budget=BUDGET)
    assert {lane: day.refused.get(lane, 0) for lane in VITAL} == dict.fromkeys(VITAL, 0)
    assert day.limited == []
    assert day.total < 10_000 and BUDGET - day.total > 50_000


# ── the account's pause (the correction of PM-01-03) ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("errors", "paid", "reason"), [
    ({"requests": "You have reached the request limit for the day, Go to https://dashboard.api-football.com"}, True, "requests"),
    ({"requests": "You have reached the request limit for the day"}, False, "requests"),
    ({"plan": "Free plans do not have access to this season, try from 2022 to 2024."}, True, "plan"),
    ({"plan": "Free plans do not have access to this season, try from 2022 to 2024."}, False, None),
    ({"token": "Error/Missing application key."}, True, "token"),
    ({"access": "Your account is suspended"}, True, "access"),
    ({"league": "The League field must contain an integer."}, True, None),
    ({"season": "The Season field must contain 4 characters. Example: 2019"}, True, None),
])
def test_an_account_refusal_is_told_from_a_request_error(errors: dict[str, str], paid: bool, reason: str | None) -> None:
    assert account_refusal(errors, paid_plan=paid) == reason


def test_the_pause_holds_every_request_then_lets_one_try_again(frozen: FrozenClock) -> None:
    pause = AccountPause(seconds=900)
    pause.before_call()
    pause.trip("plan")
    with pytest.raises(ProviderAccountError, match="900s"):
        pause.before_call()
    frozen.advance(seconds=899)
    with pytest.raises(ProviderAccountError):
        pause.before_call()
    frozen.advance(seconds=1)
    pause.before_call()
    off = AccountPause(enabled=False)
    off.trip("plan")
    off.before_call()


def client(tmp_path: Path, handler: Any, pause: AccountPause | None, *, plan: str = "ultra") -> ApiFootballClient:
    settings = ApiFootballSettings(key="k" * 32, plan=plan, daily_budget=1_000, max_retries=2, timeout_seconds=1.0)

    async def no_sleep(_s: float) -> None:
        return None

    return ApiFootballClient(settings, PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
                             rate_limiter=TokenBucket(settings.per_minute_limit, sleep=no_sleep),
                             quota=DailyQuota(budget=1_000), sleep=no_sleep, account_pause=pause)


LAPSED = {"get": "fixtures", "response": [], "results": 0,
          "errors": {"plan": "Free plans do not have access to the Ids parameter."}}


async def test_a_lapsed_account_inside_a_200_stops_the_process_and_spends_nothing_more(tmp_path: Path,
                                                                                       frozen: FrozenClock) -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200, json=LAPSED)

    pause = AccountPause(seconds=900)
    c = client(tmp_path, handler, pause)
    async with c:
        with pytest.raises(ProviderAccountError) as first:
            await c.get("/odds", {"fixture": 1})
        assert isinstance(first.value, CircuitOpenError), "every job already stops on an open circuit"
        assert "do not have access" not in str(first.value), "never read as a per-season refusal by the backfill"
        for fixture in range(2, 50):  # the rest of the capture's plan: nothing goes out, nothing is spent
            with pytest.raises(ProviderAccountError):
                await c.get("/odds", {"fixture": fixture})
        assert sent == ["/odds"] and c._quota.spent == 1
        frozen.advance(seconds=900)
        with pytest.raises(ProviderAccountError):
            await c.get("/odds", {"fixture": 50})  # one try after the pause, still refused: paused again
        assert len(sent) == 2 and c._quota.spent == 2 and pause.trips == 2


async def test_when_the_account_is_back_the_requests_go_on(tmp_path: Path, frozen: FrozenClock) -> None:
    answers = iter([httpx.Response(200, json=LAPSED), httpx.Response(200, json=OK_BODY)])
    pause = AccountPause(seconds=900)
    c = client(tmp_path, lambda r: next(answers), pause)
    async with c:
        with pytest.raises(ProviderAccountError):
            await c.get("/fixtures", {"ids": "1"})
        frozen.advance(seconds=900)
        assert (await c.get("/fixtures", {"ids": "1"})).http_status == 200


async def test_on_the_free_plan_a_plan_error_is_the_requests_own_and_pauses_nothing(tmp_path: Path) -> None:
    pause = AccountPause(seconds=900)
    c = client(tmp_path, lambda r: httpx.Response(200, json=LAPSED), pause, plan="free")
    async with c:
        with pytest.raises(ProviderError) as caught:
            await c.get("/fixtures", {"league": 39, "season": 2025})
        assert not isinstance(caught.value, CircuitOpenError) and "do not have access" in str(caught.value)
    assert pause.paused_until is None


async def test_the_per_minute_limit_is_still_a_rate_limit_and_a_request_error_still_a_plain_error(tmp_path: Path) -> None:
    pause = AccountPause(seconds=900)
    minute = {"errors": {"rateLimit": "Too many requests. Your rate limit is 10 requests per minute."}, "response": []}
    c = client(tmp_path, lambda r: httpx.Response(200, json=minute), pause)
    async with c:
        with pytest.raises(RateLimitError):
            await c.get("/fixtures", {"ids": "1"})
    bad = {"errors": {"league": "The League field must contain an integer."}, "response": []}
    c = client(tmp_path, lambda r: httpx.Response(200, json=bad), pause)
    async with c:
        with pytest.raises(ProviderError) as caught:
            await c.get("/standings", {"league": "x", "season": 2026})
        assert not isinstance(caught.value, CircuitOpenError)
    assert pause.paused_until is None


async def test_without_the_pause_the_client_is_what_it_was(tmp_path: Path) -> None:
    c = client(tmp_path, lambda r: httpx.Response(200, json=LAPSED), None)
    async with c:
        for fixture in (1, 2):
            with pytest.raises(ProviderError) as caught:
                await c.get("/odds", {"fixture": fixture})
            assert not isinstance(caught.value, CircuitOpenError)
        assert c._quota.spent == 2


def test_build_gives_one_pause_per_process_and_none_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b, "_account_pause", None)

    class Cfg:
        account_guard_on = True
        account_pause_seconds = 600.0

    monkeypatch.setattr(b, "settings", type("S", (), {"api_football": Cfg()})())
    first = b.build_account_pause()
    assert first is not None and first.seconds == 600.0 and b.build_account_pause() is first
    Cfg.account_guard_on = False
    assert b.build_account_pause() is None


@pytest.mark.parametrize(("word", "on"), [(None, True), ("on", True), ("0", False), ("off", False), ("no", False)])
def test_the_account_guard_is_on_unless_it_says_off(monkeypatch: pytest.MonkeyPatch, word: str | None, on: bool) -> None:
    if word is None:
        monkeypatch.delenv("FBI_APIFOOTBALL_ACCOUNT_GUARD", raising=False)
    else:
        monkeypatch.setenv("FBI_APIFOOTBALL_ACCOUNT_GUARD", word)
    cfg = ApiFootballSettings(_env_file=None, key="k" * 32)  # type: ignore[call-arg]
    assert cfg.account_guard_on is on and cfg.account_pause_seconds == 900.0
