"""PM-02-03: the pure parts of the nightly recalculation of the availability matrix (rules 1, 3, 4 and 5 as this measurement applies
them, the memory room of the container) and the worker's side, which only STARTS the process. The database side is proved in
``tests/integration/test_coverage_job.py``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest

import fbi.coverage.job as job
from fbi.coverage import levels
from fbi.coverage.levels import Grade
from fbi.market.settle_coverage import Coverage


def test_rule_1_a_datum_needs_both_teams_and_an_empty_value_is_not_a_zero() -> None:
    assert job.team_stat_present({"home": [5], "away": [0]})
    assert not job.team_stat_present({"home": [5], "away": [None]})
    assert not job.team_stat_present({"home": [5]})
    assert job.team_stat_present({"home": [None, 3], "away": [1]})  # two sources: one is enough per side


def test_what_a_result_settles_follows_the_columns_of_each_rule() -> None:
    full = {"goals_ft_home": 1, "goals_ft_away": 0, "goals_1h_home": 0, "goals_1h_away": 0, "corners_ft_home": 4,
            "corners_ft_away": None}
    got = job.settled_measures(full)
    assert "goals_ft" in got and "goals_1h" in got
    assert "corners_ft" not in got                      # one side missing
    assert job.settled_measures({}) == []


def test_every_datum_and_market_of_the_rules_is_measured_with_its_flag_and_settlement() -> None:
    assert set(job.DECLARED_FLAG) == set(levels.DATA)
    assert set(job.SETTLE_MEASURE) == set(levels.MARKETS) == set(job.CATALOGUE_KEY)
    assert job.SETTLE_MEASURE["players"] is None        # no rule grades a player's bet


def test_rule_5_only_the_providers_no_is_used() -> None:
    short = Grade("MI", False, "muestra_insuficiente")
    inherited = Grade("A", True, "heredado")
    assert job.apply_flag(short, False, with_data=0) == Grade("D", False, "no_entregado")
    assert job.apply_flag(inherited, False, with_data=0) == Grade("D", False, "no_entregado")
    # data that arrived wins over the flag; a «yes» changes nothing
    assert job.apply_flag(short, False, with_data=2) == short
    assert job.apply_flag(short, True, with_data=0) == short
    assert job.apply_flag(short, None, with_data=0) == short
    measured = Grade("B", True, None)
    assert job.apply_flag(measured, False, with_data=0) == measured


def test_rule_4_a_level_goes_down_only_on_the_second_miss() -> None:
    first = job.publish(Grade("B", True, None), None)
    assert (first.level, first.change, first.old_level) == ("B", "primera_medida", None)
    held = job.Published("B", False, True, None)
    miss = job.publish(Grade("D", False, None), held)
    assert (miss.level, miss.measured, miss.missed, miss.change, miss.provisional) == ("B", "D", True, "incumple_una_vez", True)
    second = job.publish(Grade("D", False, None), job.Published("B", True, True, None))
    assert (second.level, second.missed, second.change) == ("D", False, "baja")
    up = job.publish(Grade("A", False, None), job.Published("B", True, True, None))
    assert (up.level, up.missed, up.change) == ("A", False, "sube")
    same = job.publish(Grade("B", True, None), held)
    assert same.change is None and not same.missed


def test_rule_3_one_match_competitions() -> None:
    assert job.one_match([1, 2, 1])
    assert not job.one_match([1, 2, 3])
    assert not job.one_match([])


def test_median_and_share() -> None:
    assert job.median([]) is None
    assert job.median([3, 1, 2]) == 2.0
    assert job.median([4, 1, 2, 3]) == 2.5
    assert job.share(Coverage(0, 0)) is None
    assert job.share(Coverage(3, 1)) == 0.3333


def test_the_switch_is_on_unless_it_says_off() -> None:
    assert job.mode({}) == "on"
    for off in ("0", "off", "false", "no", " OFF "):
        assert job.mode({job.SWITCH: off}) == "off"
    assert job.mode({job.SWITCH: "1"}) == "on"


def test_the_pass_avoids_the_copies_and_the_statistics_pass() -> None:
    times = [(job.HOUR, job.MINUTE), *job.RETRY_TIMES]
    for hour, minute in times:
        assert not (3 <= hour < 5)                       # copies 03:30-05:00 UTC
        assert (hour, minute) != (7, 20)                 # statistics pass
        t = hour * 60 + minute
        for sync in (3 * 60 + 55, 9 * 60 + 55, 15 * 60 + 55, 21 * 60 + 55):  # fixtures_sync: 20 min before, an hour after
            assert not sync - 20 <= t <= sync + 60
    assert job.CAP_MIB == 512 and job.HEADROOM_MIB < job.CAP_MIB


def _cgroup(tmp: Path, limit: str, current: int, file: int) -> Path:
    (tmp / "memory.max").write_text(limit + "\n")
    (tmp / "memory.current").write_text(f"{current}\n")
    (tmp / "memory.stat").write_text(f"anon {current - file}\nfile {file}\nkernel 1\n")
    return tmp


def test_the_room_of_the_container_does_not_count_the_page_cache(tmp_path: Path) -> None:
    mib = 1024 * 1024
    root = _cgroup(tmp_path, str(3072 * mib), 3000 * mib, 1000 * mib)
    assert job.headroom_mib(root) == 1072.0
    assert job.headroom_mib(_cgroup(tmp_path, "max", 1, 0)) is None
    assert job.headroom_mib(tmp_path / "nothing") is None


# ── the worker only starts the process ───────────────────────────────────────────────────────────────────────────────


class _Ledger:
    opened: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, conn: object) -> None:
        pass

    def open(self, job_type: str, *, params: dict[str, Any]) -> int:
        _Ledger.opened.append({"job": job_type, **params})
        return 1

    def close(self, run_id: int, counters: Any) -> None:
        _Ledger.opened[-1]["status"] = counters.status


class _Conn:
    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, *a: object) -> _Conn:
        return self

    def fetchone(self) -> None:
        return None


@pytest.fixture()
def worker(monkeypatch: pytest.MonkeyPatch) -> Any:
    from apps.worker import scheduler

    from fbi.ingestion import ledger

    _Ledger.opened = []
    monkeypatch.setattr(ledger, "RunLedger", _Ledger)
    monkeypatch.setattr(scheduler, "_connect", lambda: _Conn())
    return scheduler


def test_the_worker_starts_the_process_with_its_cap_and_never_computes(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kw["cwd"] == worker.APP_DIR and kw["timeout"] > job.MAX_SECONDS
        assert kw["env"]["OPENBLAS_NUM_THREADS"] == "1" and kw["env"]["MALLOC_ARENA_MAX"] == "2"   # BE-093: lean address space
        return subprocess.CompletedProcess(args, 0, "{'status': 'completed'}\n", "")

    monkeypatch.setattr(worker.subprocess, "run", run)
    monkeypatch.setattr(job, "headroom_mib", lambda: 900.0)
    monkeypatch.delenv(job.SWITCH, raising=False)
    monkeypatch.setattr(job, "run_pass", lambda *a, **k: pytest.fail("the worker must not compute the matrix itself"))
    worker._availability_refresh_now()
    assert len(calls) == 1
    assert calls[0][1:] == ["-m", "scripts.availability_refresh", "--scheduled", "--no-shadow", "--max-memory-mib", "512"]


def test_without_room_it_records_a_skip_and_starts_nothing(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("no room: nothing may start"))
    monkeypatch.setattr(job, "headroom_mib", lambda: 200.0)
    monkeypatch.delenv(job.SWITCH, raising=False)
    worker._availability_refresh_now()
    assert _Ledger.opened == [{"job": "availability_refresh", "skipped": "sin_margen_de_memoria", "headroom_mib": 200.0,
                               "needed_mib": job.HEADROOM_MIB, "retry": False, "status": "aborted"}]


def test_switched_off_it_does_nothing(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(job.SWITCH, "0")
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("switched off"))
    worker._availability_refresh_now()
    assert _Ledger.opened == []


# ── BE-093: the shadow comparison in a process of its own ────────────────────────────────────────────────────────────


def test_the_shadow_comparison_starts_alone_with_its_cap_and_a_lean_environment(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (21 and 23-nov-2026): run in the pass's process, after it, the comparison died twice («process gone», no row). It now
    starts in a process of its own, from a clean address space, with one thread for the numerical libraries and two malloc arenas."""
    from fbi.coverage import shadow

    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0, "{'status': 'completed'}\n", "")

    monkeypatch.setattr(worker.subprocess, "run", run)
    monkeypatch.setattr(job, "headroom_mib", lambda: 900.0)
    monkeypatch.delenv(job.SWITCH, raising=False)
    monkeypatch.delenv(shadow.SWITCH, raising=False)
    worker._availability_shadow_now()
    assert len(calls) == 1
    args, kw = calls[0]
    assert args[1:] == ["-m", "scripts.availability_refresh", "--scheduled", "--shadow-only", "--max-memory-mib", "512"]
    assert kw["cwd"] == worker.APP_DIR and job.SHADOW_SECONDS < kw["timeout"] == shadow.PROCESS_TIMEOUT
    assert {k: kw["env"][k] for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "MALLOC_ARENA_MAX")} == {
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "MALLOC_ARENA_MAX": "2"}


def test_the_shadow_comparison_without_room_records_a_skip_and_off_does_nothing(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.coverage import shadow

    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("no room: nothing may start"))
    monkeypatch.setattr(job, "headroom_mib", lambda: 200.0)
    monkeypatch.delenv(job.SWITCH, raising=False)
    monkeypatch.delenv(shadow.SWITCH, raising=False)
    worker._availability_shadow_now(retry=True)
    assert _Ledger.opened == [{"job": "availability_shadow", "skipped": "sin_margen_de_memoria", "headroom_mib": 200.0,
                               "needed_mib": job.HEADROOM_MIB, "retry": True, "status": "aborted"}]
    _Ledger.opened = []
    monkeypatch.setenv(shadow.SWITCH, "0")
    worker._availability_shadow_now()
    assert _Ledger.opened == []


def test_the_shadow_comparison_does_nothing_once_the_day_has_one(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.coverage import shadow

    class Done(_Conn):
        def fetchone(self) -> tuple[int]:  # type: ignore[override]
            return (1,)

    monkeypatch.setattr(worker, "_connect", lambda: Done())
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("done today: nothing may start"))
    monkeypatch.delenv(job.SWITCH, raising=False)
    monkeypatch.delenv(shadow.SWITCH, raising=False)
    worker._availability_shadow_now(retry=True)
    worker._availability_refresh_now(retry=True)


def test_the_shadow_comparison_avoids_the_pass_the_copies_and_the_fixtures_sync() -> None:
    from fbi.coverage import shadow

    starts = [(shadow.HOUR, shadow.MINUTE), *shadow.RETRY_TIMES]
    assert all((h, m) > (job.HOUR, job.MINUTE + 15) for h, m in starts)          # after the pass (15 minutes of budget)
    assert all(not (3 * 60 + 30 <= h * 60 + m <= 5 * 60) for h, m in starts)      # never in the copies
    syncs = [h * 60 + 58 for h in (4, 10, 16, 22)]                                # fixtures_sync, about :58 every six hours
    assert all(not (f - 20 <= h * 60 + m <= f + 10) for h, m in starts for f in syncs)
    assert (7, 20) not in starts
    assert shadow.PROCESS_TIMEOUT < 20 * 60                                       # under the run watchdog of availability_shadow


def test_the_peak_is_this_process_not_the_worker_it_was_forked_from(tmp_path: Path) -> None:
    """Regression: ``ru_maxrss`` keeps the peak of the parent across exec, so the pass's row read 3.065,4 MiB - the worker's."""
    from scripts.availability_refresh import peak_mib

    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmPeak:\t  300000 kB\nVmHWM:\t   92160 kB\nVmRSS:\t   80000 kB\n", encoding="ascii")
    assert peak_mib(str(status)) == 90.0
    assert peak_mib(str(tmp_path / "none")) > 0                                    # no /proc: ru_maxrss
