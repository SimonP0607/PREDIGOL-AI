"""PM-13-05 (OPS-026): what the worker hands back after a heavy run, the cap on malloc arenas, the switch, and the statistics catch-up that
a restart no longer repeats."""

from __future__ import annotations

from typing import Any

import pytest

from fbi.ops import memrelease
from fbi.ops.memrelease import MIB, Release
from fbi.ops.memwatch import MemWatch


class Process:
    """A process whose resident memory the test moves: the collector and the trim each take some of it."""

    def __init__(self, rss_mib: float = 2000.0, gc_frees: float = 10.0, trim_frees: float = 300.0) -> None:
        self.rss_mib = rss_mib
        self.gc_frees = gc_frees
        self.trim_frees = trim_frees
        self.blocks = 5_000_000
        self.now = 1000.0
        self.calls: list[str] = []

    def rss(self) -> int:
        return int(self.rss_mib * MIB)

    def collect(self) -> int:
        self.calls.append("collect")
        self.rss_mib -= self.gc_frees
        self.blocks -= 1000
        return 42

    def trim(self) -> bool:
        self.calls.append("trim")
        self.rss_mib -= self.trim_frees
        return True

    def blocks_now(self) -> int:
        return self.blocks

    def clock(self) -> float:
        self.now += 0.5
        return self.now

    def release(self, gap: float = 300.0) -> Release:
        return Release(rss=self.rss, collect=self.collect, trim=self.trim, blocks=self.blocks_now, clock=self.clock, gap=gap)


HEAVY = {"grew_mib": 120.0, "peak_over_start_mib": 400.0}
LIGHT = {"grew_mib": 2.0, "peak_over_start_mib": 30.0}


@pytest.mark.parametrize(("raw", "on"), [(None, True), ("1", True), ("", True), ("0", False), ("off", False), ("NO", False), ("false", False)])
def test_the_switch_is_on_unless_it_says_no(raw: str | None, on: bool) -> None:
    env = {} if raw is None else {memrelease.SWITCH: raw}
    assert memrelease.enabled(env) is on


@pytest.mark.parametrize(("mem", "heavy"), [(HEAVY, True), (LIGHT, False), ({"grew_mib": 50.0}, True), ({"peak_over_start_mib": 150.0}, True),
                                             ({"grew_mib": 49.9, "peak_over_start_mib": 149.9}, False), ({}, False),
                                             ({"grew_mib": "x"}, False), ({"grew_mib": None, "peak_over_start_mib": None}, False)])
def test_a_run_is_heavy_when_it_grew_the_process_or_went_far_over_its_start(mem: dict[str, Any], heavy: bool) -> None:
    assert memrelease.is_heavy(mem) is heavy


def test_a_heavy_run_is_followed_by_the_collector_then_the_trim_and_says_what_each_gave_back() -> None:
    p = Process(rss_mib=2000.0, gc_frees=10.0, trim_frees=300.0)
    out = p.release().after(HEAVY)
    assert p.calls == ["collect", "trim"]
    assert out is not None
    assert (out["rss_before_mib"], out["rss_after_mib"], out["freed_mib"], out["freed_by_trim_mib"]) == (2000.0, 1690.0, 310.0, 300.0)
    assert (out["trimmed"], out["collected"], out["blocks_before"], out["blocks_after"]) == (True, 42, 5_000_000, 4_999_000)
    assert out["seconds"] > 0


def test_a_light_run_costs_nothing() -> None:
    p = Process()
    assert p.release().after(LIGHT) is None
    assert p.calls == []


def test_two_ends_close_together_release_once() -> None:
    p = Process()
    rel = p.release(gap=300.0)
    assert rel.after(HEAVY) is not None
    assert rel.after(HEAVY) is None
    assert p.calls == ["collect", "trim"]
    p.now += 301
    assert rel.after(HEAVY) is not None


def test_it_never_raises_into_a_job() -> None:
    def boom() -> int:
        raise RuntimeError("collector")

    rel = Release(rss=lambda: 1, collect=boom, trim=lambda: True, blocks=lambda: 1)
    assert rel.after(HEAVY) is None


def test_without_a_reading_of_the_process_it_still_trims_and_reports_without_figures_in_mib() -> None:
    p = Process()
    rel = Release(rss=lambda: None, collect=p.collect, trim=p.trim, blocks=p.blocks_now, clock=p.clock)
    out = rel.after(HEAVY)
    assert out is not None and "freed_mib" not in out and out["trimmed"] is True


class Libc:
    def __init__(self, ok: int = 1) -> None:
        self.ok = ok
        self.mallopt_calls: list[tuple[int, int]] = []
        self.trims: list[int] = []

    def mallopt(self, param: int, value: int) -> int:
        self.mallopt_calls.append((param, value))
        return self.ok

    def malloc_trim(self, pad: int) -> int:
        self.trims.append(pad)
        return 1


def test_the_arena_cap_asks_glibc_for_two_arenas() -> None:
    libc = Libc()
    assert memrelease.cap_arenas(libc=libc) is True
    assert libc.mallopt_calls == [(-8, 2)]  # M_ARENA_MAX
    assert memrelease.cap_arenas(libc=Libc(ok=0)) is False


def test_the_trim_calls_malloc_trim_with_zero_padding() -> None:
    libc = Libc()
    assert memrelease.malloc_trim(libc=libc) is True
    assert libc.trims == [0]


def test_without_glibc_both_do_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memrelease, "_libc", lambda: None)
    assert memrelease.cap_arenas() is False
    assert memrelease.malloc_trim() is False

    class NoSymbol:
        pass

    assert memrelease.cap_arenas(libc=NoSymbol()) is False
    assert memrelease.malloc_trim(libc=NoSymbol()) is False


class Readings:
    def __init__(self, rss: int, hwm: int) -> None:
        self.rss_value = rss
        self.hwm_value = hwm

    def rss(self) -> int:
        return self.rss_value

    def hwm(self) -> int:
        return self.hwm_value


def test_the_report_of_a_run_carries_the_release_but_its_own_figures_are_the_runs() -> None:
    p = Process(rss_mib=1500.0, trim_frees=200.0)
    proc = Readings(rss=800 * MIB, hwm=1000 * MIB)
    watch = MemWatch(rss=proc.rss, hwm=proc.hwm, every=3600, release=p.release().after)
    assert watch.start()
    try:
        watch.begin("run:1", "pick_pipeline")
        proc.rss_value = 1500 * MIB
        watch.sample()
        out = watch.end("run:1")
    finally:
        watch.stop()
    assert out is not None
    assert (out["rss_start_mib"], out["rss_end_mib"], out["grew_mib"]) == (800.0, 1500.0, 700.0)
    assert out["release"]["freed_by_trim_mib"] == 200.0


def test_a_watch_without_a_release_reports_as_before() -> None:
    proc = Readings(rss=800 * MIB, hwm=1000 * MIB)
    watch = MemWatch(rss=proc.rss, hwm=proc.hwm, every=3600)
    assert watch.start()
    try:
        watch.begin("run:1", "x")
        proc.rss_value = 1500 * MIB
        out = watch.end("run:1")
    finally:
        watch.stop()
    assert out is not None and "release" not in out


def test_start_wires_the_release_and_the_cap_only_with_the_switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ops import memwatch

    caps: list[bool] = []
    def cap(*a: Any, **k: Any) -> bool:
        caps.append(True)
        return True

    monkeypatch.setattr(memrelease, "cap_arenas", cap)
    monkeypatch.setattr(memwatch, "WATCH", MemWatch(rss=lambda: 1, hwm=lambda: 1, every=3600))
    monkeypatch.setenv(memrelease.SWITCH, "0")
    memwatch.start()
    memwatch.WATCH.stop()
    assert caps == [] and memwatch.WATCH.release is None
    monkeypatch.setenv(memrelease.SWITCH, "1")
    memwatch.start()
    memwatch.WATCH.stop()
    assert caps == [True] and memwatch.WATCH.release == memrelease.RELEASE.after


# ── the statistics catch-up after a restart ──────────────────────────────────────────────────────────────────────────


class _Conn:
    def __init__(self, row: tuple[int] | None, fail: bool = False) -> None:
        self.row = row
        self.fail = fail
        self.sql = ""

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> _Conn:
        if self.fail:
            raise RuntimeError("no answer")
        self.sql = sql
        self.params = params
        return self

    def fetchone(self) -> tuple[int] | None:
        return self.row


@pytest.mark.parametrize(("row", "fail", "needed"), [((1,), False, False), (None, False, True), (None, True, True)])
def test_a_restart_schedules_the_catch_up_only_when_no_full_pass_ended_lately(monkeypatch: pytest.MonkeyPatch, row: Any, fail: bool,
                                                                               needed: bool) -> None:
    from apps.worker import scheduler

    conn = _Conn(row, fail)
    monkeypatch.setattr(scheduler, "_connect", lambda: conn)
    assert scheduler._stats_pass_needed() is needed
    if not fail:
        assert "stopped_reason IS NULL" in conn.sql and conn.params == (scheduler.STATS_CATCH_UP_HOURS,)
