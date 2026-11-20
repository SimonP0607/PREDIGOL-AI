"""PM-13-05 (OPS-010): the memory of each worker job, by sampling - what a span reports, that it is a no-op outside the worker,
that it never raises, and that the ledger keeps it under params._mem."""

from __future__ import annotations

import time
from typing import Any

import pytest

from fbi.ops import memwatch
from fbi.ops.memwatch import MIB, MemWatch


class Readings:
    """A process whose memory the test sets."""

    def __init__(self, rss: int, hwm: int) -> None:
        self.rss_value: int | None = rss
        self.hwm_value: int | None = hwm

    def rss(self) -> int | None:
        return self.rss_value

    def hwm(self) -> int | None:
        return self.hwm_value


@pytest.fixture
def proc() -> Readings:
    return Readings(rss=800 * MIB, hwm=1000 * MIB)


@pytest.fixture
def watch(proc: Readings) -> Any:
    w = MemWatch(rss=proc.rss, hwm=proc.hwm, every=3600)  # the test samples by hand
    assert w.start()
    yield w
    w.stop()


@pytest.mark.parametrize(("raw", "on"), [(None, True), ("1", True), ("", True), ("0", False), ("off", False),
                                          ("NO", False), ("false", False)])
def test_the_switch_is_on_unless_it_says_no(raw: str | None, on: bool) -> None:
    env = {} if raw is None else {memwatch.SWITCH: raw}
    assert memwatch.enabled(env) is on


def test_a_span_reports_start_end_peak_growth_and_the_raised_high_water_mark(watch: MemWatch, proc: Readings) -> None:
    watch.begin("job:fixtures_sync", "fixtures_sync")
    proc.rss_value = 1500 * MIB
    watch.sample()
    proc.rss_value, proc.hwm_value = 900 * MIB, 1500 * MIB
    out = watch.end("job:fixtures_sync")
    assert out is not None
    assert out["job"] == "fixtures_sync"
    assert (out["rss_start_mib"], out["rss_end_mib"], out["rss_max_mib"]) == (800.0, 900.0, 1500.0)
    assert (out["grew_mib"], out["peak_over_start_mib"], out["hwm_raised_mib"]) == (100.0, 700.0, 500.0)
    assert (out["overlap"], out["samples"]) == (1, 1)
    assert watch.open_spans() == 0


def test_spans_open_at_once_say_so_and_a_released_peak_is_not_growth(watch: MemWatch, proc: Readings) -> None:
    watch.begin("job:a", "a")
    watch.begin("job:b", "b")
    proc.rss_value = 1200 * MIB
    watch.sample()
    proc.rss_value = 800 * MIB
    a, b = watch.end("job:a"), watch.end("job:b")
    assert a is not None and b is not None
    assert a["overlap"] == 2 and b["overlap"] == 2
    assert a["grew_mib"] == 0.0 and a["peak_over_start_mib"] == 400.0 and a["hwm_raised_mib"] == 0.0


def test_nothing_is_measured_when_the_sampler_is_not_running(proc: Readings) -> None:
    w = MemWatch(rss=proc.rss, hwm=proc.hwm)
    w.begin("run:1", "x")
    assert w.end("run:1") is None and w.open_spans() == 0


def test_without_proc_it_does_not_start(proc: Readings) -> None:
    proc.rss_value = None
    w = MemWatch(rss=proc.rss, hwm=proc.hwm)
    assert w.start() is False and not w.running


def test_it_never_raises_into_a_job() -> None:
    def broken() -> int:
        raise RuntimeError("no /proc")

    calls = iter([MIB])
    w = MemWatch(rss=lambda: next(calls, None) or broken(), hwm=broken, every=3600)
    assert w.start()
    try:
        w.begin("job:x", "x")  # the readings raise: no span, no exception
        assert w.end("job:x") is None
        w.sample()
    except RuntimeError:  # pragma: no cover - the point of the test
        pytest.fail("memwatch raised into the caller")
    finally:
        w.stop()


def test_a_span_that_never_closed_is_forgotten(watch: MemWatch, monkeypatch: pytest.MonkeyPatch) -> None:
    watch.begin("run:9", "crashed")
    clock = time.monotonic() + memwatch.MAX_SPAN_SECONDS + 1
    monkeypatch.setattr("fbi.ops.memwatch.time.monotonic", lambda: clock)
    watch.sample()
    assert watch.open_spans() == 0 and watch.end("run:9") is None


def test_an_unknown_span_ends_as_none(watch: MemWatch) -> None:
    assert watch.end("job:never") is None


def test_the_real_proc_files_read_as_bytes_on_linux() -> None:
    rss, hwm = memwatch.rss_bytes(), memwatch.hwm_bytes()
    if rss is None:
        pytest.skip("no /proc here")
    assert rss > 0 and (hwm is None or hwm >= 0)


def test_the_ledger_keeps_the_span_under_params_mem(monkeypatch: pytest.MonkeyPatch) -> None:
    """RunLedger opens a span at open and writes what it took at close, in the same UPDATE as the outcome."""
    from fbi.ingestion.ledger import RunCounters, RunLedger

    seen: list[tuple[str, Any]] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def execute(self, sql: str, params: Any = None) -> None:
            seen.append((sql, params))

        def fetchone(self) -> tuple[int]:
            return (7,)

    class Info:
        transaction_status = None

    class Conn:
        info = Info()

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            return None

    proc = Readings(rss=500 * MIB, hwm=600 * MIB)
    w = MemWatch(rss=proc.rss, hwm=proc.hwm, every=3600)
    assert w.start()
    monkeypatch.setattr("fbi.ops.memwatch.WATCH", w)
    monkeypatch.setattr("fbi.ops.run_watchdog.timeout_for", lambda job: __import__("datetime").timedelta(hours=1))
    led = RunLedger(Conn())  # type: ignore[arg-type]
    run_id = led.open("elo_refresh")
    proc.rss_value = 700 * MIB
    led.close(run_id, RunCounters())
    w.stop()
    sql, params = seen[-1]
    assert "params || jsonb_build_object('_mem'" in sql
    mem = params[10].obj
    assert mem["job"] == "elo_refresh" and mem["grew_mib"] == 200.0 and params[11].obj == mem


def test_outside_the_worker_the_ledger_leaves_params_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    idle = MemWatch(rss=lambda: MIB, hwm=lambda: MIB)
    monkeypatch.setattr("fbi.ops.memwatch.WATCH", idle)
    assert idle.end("run:1") is None  # never started: the CASE keeps params as they were
