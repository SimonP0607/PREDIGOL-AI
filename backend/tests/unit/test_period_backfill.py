"""PM-05-02: the night's window and its arithmetic (``scripts.period_backfill``)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from scripts import period_backfill as pb


def at(h: int, m: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 11, day, h, m, tzinfo=UTC)


@pytest.mark.parametrize(("hour", "minute", "inside"), [(22, 29, False), (22, 30, True), (23, 59, True), (0, 0, True), (3, 24, True),
                                                        (3, 25, False), (12, 0, False)])
def test_the_window_runs_from_2230_to_0325_utc(hour: int, minute: int, inside: bool) -> None:
    assert pb.in_window(at(hour, minute)) is inside


def test_the_stop_is_the_next_0325() -> None:
    assert pb.stop_time(at(22, 31)) == at(3, 25, day=25)
    assert pb.stop_time(at(1, 0)) == at(3, 25)
    assert pb.stop_time(at(3, 25)) == at(3, 25, day=25)


def test_the_stop_is_before_the_copies_start() -> None:
    assert time(3, 50) > pb.STOP_AT  # the lane's quiet window and the copies' 03:50


@pytest.mark.parametrize(("requests", "nights"), [(0, 0), (1, 1), (5_000, 1), (5_001, 2), (53_500, 11)])
def test_nights_needed(requests: int, nights: int) -> None:
    assert pb.nights_needed(requests) == nights


def test_the_pace_stays_under_a_fifth_of_the_per_minute_limit() -> None:
    assert 60 / pb.PACE_SECONDS <= 40


# ── OPS-027: the night's caps whatever the number of starts, the stop order, the Monday's room, the finish date ─────────────────────────

import threading  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, ClassVar  # noqa: E402

from fbi.ingestion import period_stats as ps  # noqa: E402


@pytest.mark.parametrize(("h", "m", "day", "start_day"), [(22, 30, 24, 24), (23, 59, 24, 24), (0, 0, 25, 24), (3, 24, 25, 24), (12, 0, 25, 24),
                                                          (22, 29, 25, 24), (22, 30, 25, 25)])
def test_the_night_starts_at_the_last_2230(h: int, m: int, day: int, start_day: int) -> None:
    assert pb.night_start(at(h, m, day=day)) == at(22, 30, day=start_day)


@pytest.mark.parametrize(("done", "requested", "room"), [(0, 5_000, 5_000), (1_300, 5_000, 3_700), (4_999, 5_000, 1), (5_000, 5_000, 0),
                                                         (6_200, 5_000, 0), (0, 300, 300), (4_900, 300, 100)])
def test_a_start_asks_only_what_the_night_has_left(done: int, requested: int, room: int) -> None:
    assert pb.night_room(done, requested) == room


def test_the_fill_window_of_the_scheduler_is_the_one_of_the_process() -> None:
    for hour in range(24):
        for minute in (0, 15, 29, 30, 31, 59):
            moment = at(hour, minute)
            assert ps.fill_window_open(moment) is pb.in_window(moment), moment


def test_the_headroom_the_fill_asks_is_twice_the_peak_it_measured_and_below_the_matrix_one() -> None:
    from fbi.coverage import job

    assert ps.FILL_HEADROOM_MIB == 2 * 64 and ps.FILL_HEADROOM_MIB < job.HEADROOM_MIB


def test_the_finish_date_counts_a_sunday_night_short() -> None:
    thursday = datetime(2026, 11, 26, tzinfo=UTC).date()
    assert pb.finish_estimate(0, thursday)["nights"] == 0
    assert pb.finish_estimate(5_000, thursday) == {"nights": 1, "first_night": "2026-11-26", "ends_on": "2026-11-27"}
    # Thursday, Friday, Saturday at 5,000, then Sunday at 3,700: 18,700 asked in four nights.
    assert pb.finish_estimate(18_700, thursday)["nights"] == 4
    assert pb.finish_estimate(18_701, thursday)["nights"] == 5
    out = pb.finish_estimate(46_000, thursday)
    assert out["nights"] == 10 and out["ends_on"] == "2026-12-06"


class Cur:
    def __init__(self, quota: int | None, jobs: dict[str, int]) -> None:
        self.quota, self.jobs, self.last = quota, jobs, ""

    def __enter__(self) -> Cur:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.last = sql

    def fetchone(self) -> tuple[int] | None:
        return None if self.quota is None else (self.quota,)

    def fetchall(self) -> list[tuple[str, int]]:
        return list(self.jobs.items())


class Conn:
    def __init__(self, quota: int | None = 1_000, jobs: dict[str, int] | None = None) -> None:
        self.quota, self.jobs = quota, jobs or {}

    def cursor(self) -> Cur:
        return Cur(self.quota, self.jobs)

    def commit(self) -> None:
        return None


MON = datetime(2026, 11, 23, 0, 30, tzinfo=UTC)
WED = datetime(2026, 11, 25, 0, 30, tzinfo=UTC)


def guard(conn: Conn, now: datetime = WED, **kw: Any) -> pb.Guard:
    return pb.Guard(conn, until=now + timedelta(hours=3), budget=60_000, lane_ceiling=8_000, scheduled=True, clock_fn=lambda: now, **kw)


def test_the_guard_stops_at_60_percent_of_the_budget_or_at_the_emergency_reserve_whichever_comes_first() -> None:
    assert guard(Conn(quota=35_999)).__call__() is True
    g = guard(Conn(quota=36_000))
    assert g() is False and g.reason is not None and "36000" in g.reason
    # with a small budget the reserve of 7,000 comes first: 10,000 - 7,000 = 3,000
    small = pb.Guard(Conn(quota=3_000), until=WED + timedelta(hours=3), budget=10_000, lane_ceiling=8_000, scheduled=True,
                     clock_fn=lambda: WED, reserve=7_000)
    assert small() is False
    assert small.total_limit() == 3_000
    assert guard(Conn(), reserve=7_000).total_limit() == 36_000


def test_the_guard_keeps_the_days_cap_of_the_fill_whatever_the_starts() -> None:
    assert guard(Conn(jobs={"period_backfill": 4_999}))() is True
    g = guard(Conn(jobs={"period_backfill": 5_000}))
    assert g() is False and g.reason == "tope del dia 5000/5000"


def test_on_a_monday_the_fill_leaves_the_weekly_round_its_room_in_the_lane() -> None:
    # before the round: 8,000 - 100 - 6,700 = 1,200 for the fill
    assert guard(Conn(jobs={"period_backfill": 1_199}), MON)() is True
    g = guard(Conn(jobs={"period_backfill": 1_200}), MON)
    assert g() is False and g.reason is not None and "ronda semanal" in g.reason
    # the round has spent 2,886 already: the room it still needs is 3,814, so the fill has 8,000 - 100 - 2,886 - 3,814 = 1,200 less what it took
    assert guard(Conn(jobs={"historical_backfill": 2_886}), MON)() is True
    assert guard(Conn(jobs={"historical_backfill": 2_886, "period_backfill": 1_200}), MON)() is False
    # the round is done (6,616): nothing is kept; the lane's own margin applies
    assert guard(Conn(jobs={"historical_backfill": 6_616, "period_backfill": 1_000}), MON)() is True
    assert guard(Conn(jobs={"historical_backfill": 6_616, "period_backfill": 1_300}), MON)() is False
    # any other day: only the margin
    assert guard(Conn(jobs={"historical_backfill": 1_000, "period_backfill": 5_000 - 1}), WED)() is True


def test_the_lane_message_names_the_lane_on_an_ordinary_day() -> None:
    g = guard(Conn(jobs={"historical_backfill": 7_900}))
    assert g() is False and g.reason is not None and "historicos" in g.reason and "ronda" not in g.reason


def test_a_stop_file_ends_the_pass_at_the_next_request(tmp_path: Path) -> None:
    path = tmp_path / pb.STOP_FILE
    g = guard(Conn(), stop_path=path)
    assert g() is True
    path.write_text("")
    assert g() is False and g.reason is not None and pb.STOP_FILE in g.reason
    path.unlink()
    g2 = guard(Conn(), stop_path=path)
    assert g2() is True  # taking the file away lets the next start go on


def test_a_sigterm_ends_the_pass_at_the_next_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pb, "STOP_REQUESTED", False)
    g = guard(Conn())
    assert g() is True
    pb.request_stop()
    assert g() is False and g.reason is not None and "senal" in g.reason


def test_the_stop_file_lives_in_the_raw_store_directory() -> None:
    assert pb.stop_file("/app/data/raw") == Path("/app/data/raw/PARAR_period_backfill")


# ── the scheduler's start ────────────────────────────────────────────────────────────────────────────────────────────

import subprocess  # noqa: E402


class _SchedConn:
    def __enter__(self) -> _SchedConn:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, *a: object) -> _SchedConn:
        return self

    def fetchone(self) -> None:
        return None


class _Ledger:
    opened: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, conn: object) -> None:
        pass

    def open(self, job_type: str, *, params: dict[str, Any]) -> int:
        _Ledger.opened.append({"job": job_type, **params})
        return 1

    def close(self, run_id: int, counters: Any) -> None:
        return None


@pytest.fixture()
def worker(monkeypatch: pytest.MonkeyPatch) -> Any:
    from apps.worker import scheduler

    from fbi.ingestion import ledger

    _Ledger.opened = []
    monkeypatch.setattr(ledger, "RunLedger", _Ledger)
    monkeypatch.setattr(scheduler, "_connect", lambda: _SchedConn())
    monkeypatch.setenv(ps.BACKFILL_SWITCH, "on")
    return scheduler


def test_the_fill_starts_with_128_mib_free_where_the_matrix_would_not(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The night of 25-nov-2026 found 134.6 MiB free, the old 384 asked, and the fill was skipped; its measured peak is 61.7 MiB."""
    from fbi.coverage import job

    calls: list[list[str]] = []

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kw["env"]["MALLOC_ARENA_MAX"] == "2" and kw["timeout"] >= 5 * 3600 - 1
        return subprocess.CompletedProcess(args, 0, "{}\n", "")

    monkeypatch.setattr(worker.subprocess, "run", run)
    monkeypatch.setattr(worker, "_period_backfill_running", lambda: False)
    monkeypatch.setattr(job, "headroom_mib", lambda: 134.6)
    worker._period_backfill_now()
    assert len(calls) == 1 and calls[0][1:5] == ["-m", "scripts.period_backfill", "run", "--scheduled"]
    assert _Ledger.opened == []


def test_below_128_mib_the_first_start_records_a_skip_and_a_retry_only_logs_it(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.coverage import job

    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("no room: nothing may start"))
    monkeypatch.setattr(worker, "_period_backfill_running", lambda: False)
    monkeypatch.setattr(job, "headroom_mib", lambda: 90.0)
    worker._period_backfill_now()
    assert _Ledger.opened == [{"job": "period_backfill", "skipped": "sin_margen_de_memoria", "headroom_mib": 90.0, "needed_mib": 128,
                               "retry": False}]
    worker._period_backfill_now(retry=True)
    assert len(_Ledger.opened) == 1


def test_two_starts_of_the_same_worker_never_run_two_processes(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.coverage import job

    monkeypatch.setattr(job, "headroom_mib", lambda: 900.0)
    monkeypatch.setattr(worker, "_period_backfill_running", lambda: False)
    calls: list[int] = []
    inside = threading.Event()
    release = threading.Event()

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(1)
        inside.set()
        assert release.wait(5)
        return subprocess.CompletedProcess(args, 0, "{}\n", "")

    monkeypatch.setattr(worker.subprocess, "run", run)
    first = threading.Thread(target=worker._period_backfill_now)
    first.start()
    assert inside.wait(5)
    worker._period_backfill_now(retry=True)  # the second start finds the first one on it and leaves
    release.set()
    first.join(5)
    assert calls == [1]


def test_switched_off_the_fill_never_starts(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ps.BACKFILL_SWITCH, "off")
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("switched off"))
    worker._period_backfill_now()
    assert _Ledger.opened == []
