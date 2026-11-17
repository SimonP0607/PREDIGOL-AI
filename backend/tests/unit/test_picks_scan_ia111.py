"""IA-111 (AD-E08): the scan of the price instants of the pick pipeline - its switch, its window and what each mode passes on.

``off`` (the default) is the full scan every pass made before; ``shadow`` is the same scan and only counts what a window would have missed;
``window`` reads the instants from ``SCAN_LOOKBACK`` before the last pass that committed. The candidates are evaluated by the same code
(``evaluate_captures``) in the three modes: the window only skips instants, and the evidence cache returns what a read would."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.picks import engine, pipeline

AT = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(("raw", "mode"), [(None, "off"), ("off", "off"), ("shadow", "shadow"), (" WINDOW ", "window"),
                                           ("on", "off"), ("1", "off")])
def test_the_switch_is_off_unless_it_says_shadow_or_window(monkeypatch: pytest.MonkeyPatch, raw: str | None, mode: str) -> None:
    if raw is None:
        monkeypatch.delenv(pipeline.SCAN_SWITCH, raising=False)
    else:
        monkeypatch.setenv(pipeline.SCAN_SWITCH, raw)
    monkeypatch.setattr(pipeline, "environment", lambda: __import__("os").environ)
    assert pipeline.scan_mode() == mode


class _Cur:
    def __init__(self, last: datetime | None) -> None:
        self.last = last
        self.sql = ""

    def __enter__(self) -> _Cur:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[datetime | None]:
        return (self.last,)


class _Conn:
    def __init__(self, last: datetime | None) -> None:
        self.c = _Cur(last)

    def cursor(self) -> _Cur:
        return self.c


@pytest.mark.parametrize(("last", "since"), [
    (AT - timedelta(minutes=10), AT - timedelta(minutes=10) - pipeline.SCAN_LOOKBACK),
    (AT - timedelta(days=3), AT - timedelta(days=3) - pipeline.SCAN_LOOKBACK),
    (None, AT - pipeline.SCAN_LOOKBACK)])
def test_the_window_starts_a_lookback_before_the_last_pass_that_committed(last: datetime | None, since: datetime) -> None:
    conn = _Conn(last)
    assert pipeline.scan_since(conn, at=AT) == since  # type: ignore[arg-type]
    assert "status IN ('completed', 'partial')" in conn.c.sql


def test_the_lookback_keeps_a_wide_margin_over_the_delay_measured() -> None:
    assert timedelta(hours=12) <= pipeline.SCAN_LOOKBACK


def test_the_full_scan_is_still_the_default_of_the_engine() -> None:
    report = engine.PickReport()
    assert report.since is None and report.from_old_instants == 0
    defaults = engine.evaluate_captures.__kwdefaults__ or {}
    assert defaults.get("since") is None and defaults.get("watch_since") is None and defaults.get("cache_evidence") is False


@pytest.mark.parametrize("mode", ["off", "shadow", "window"])
def test_what_each_mode_hands_the_engine(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    seen: dict[str, Any] = {}
    window = AT - timedelta(hours=25)

    def fake_evaluate(conn: Any, **kw: Any) -> engine.PickReport:
        seen.update(kw)
        raise RuntimeError("stop here")

    monkeypatch.setattr(pipeline, "scan_mode", lambda: mode)
    monkeypatch.setattr(pipeline, "scan_since", lambda conn, at: window)
    monkeypatch.setattr(pipeline, "forecast_upcoming", lambda conn, **kw: None)
    monkeypatch.setattr(pipeline, "match_forecast_enabled", lambda: False)
    monkeypatch.setattr(pipeline, "evaluate_captures", fake_evaluate)

    class Ledger:
        def __init__(self, conn: Any) -> None:
            pass

    class Conn:
        def cursor(self) -> Any:
            class C:
                def __enter__(self) -> Any:
                    return self

                def __exit__(self, *a: Any) -> None:
                    return None

                def execute(self, *a: Any) -> None:
                    return None

                def fetchone(self) -> tuple[int]:
                    return (1,)
            return C()

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(pipeline, "RunLedger", Ledger)
    with pytest.raises(RuntimeError):
        pipeline.run_pipeline(Conn(), at=AT, code_version="t", apply=False)  # type: ignore[arg-type]
    assert seen["since"] == (window if mode == "window" else None)
    assert seen["watch_since"] == (window if mode == "shadow" else None)
    assert seen["cache_evidence"] is (mode == "window")
