"""The storage projection: retention, the dump policy and the +N leagues scaling, checked on numbers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import storage_forecast as sf

GB = sf.GB


def test_the_dump_policy_keeps_seven_daily_four_weekly_six_monthly() -> None:
    assert [sf.dumps_kept(d) for d in (0, 1, 7, 30, 91, 365)] == [0, 1, 8, 12, 14, 17]


def test_without_retention_everything_grows_linearly() -> None:
    v = sf.project(db0=10 * GB, raw0=1 * GB, archive0=0, db_per_day=0.2 * GB, live_per_day=0.1 * GB,
                   raw_per_day=0.1 * GB, dump_ratio=0.06, days=100, retention=False, live0=0.5 * GB)
    assert v["db"] == pytest.approx(30 * GB) and v["raw"] == pytest.approx(11 * GB) and v["archive"] == 0
    assert v["backup"] == pytest.approx(sf.dumps_kept(100) * 0.06 * 30 * GB + 11 * GB)
    assert v["total"] == pytest.approx(v["db"] + v["raw"] + v["archive"] + v["backup"])


def _run(days: int, retention: bool) -> dict[str, float]:
    return sf.project(db0=10 * GB, raw0=0.0, archive0=0.0, db_per_day=0.2 * GB, live_per_day=0.1 * GB,
                      raw_per_day=0.0, dump_ratio=0.0, live0=0.5 * GB, days=days, retention=retention)


def test_retention_moves_aged_in_play_prices_to_a_smaller_archive() -> None:
    assert _run(30, True) == _run(30, False), "nothing has aged out yet"
    late = _run(365, True)
    aged = 0.5 * GB + 0.1 * GB * 365 - 0.1 * GB * sf.HOT_DAYS_LIVE
    assert late["archive"] == pytest.approx(aged * sf.PARQUET_RATIO)
    assert late["db"] == pytest.approx(10 * GB - 0.5 * GB + 0.1 * GB * sf.HOT_DAYS_LIVE + 0.1 * GB * 365)
    assert late["db"] < _run(365, False)["db"]


def test_plus_n_leagues_scales_fixture_and_league_driven_growth(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    cap = tmp_path / "20261005T000000Z"
    cap.mkdir()
    (cap / "capacity.json").write_text(json.dumps({
        "measured": {"tracked_competitions": 100},
        "scenarios": [{"added_leagues": 50, "added_fixtures_per_day_mean": 40.0}]}))
    monkeypatch.setattr(sf, "CAPACITY_ROOT", tmp_path)
    measured = {
        "database_bytes": 10 * GB, "raw": {"on_disk_bytes": GB, "steady_bytes_per_day": 100 * sf.MB},
        "backups": {"dump_ratio": 0.06}, "live_model": {"fixtures_per_day_28d": 80.0},
        "tables": [{"key": "live_odds", "steady_bytes_per_day": 100 * sf.MB, "bytes_total": 0.5 * GB},
                   {"key": "transfers", "steady_bytes_per_day": 10 * sf.MB, "bytes_total": 0.0}]}
    f = sf.forecast(measured, added_leagues=50)
    assert f["fixture_factor"] == 1.5 and f["league_factor"] == 1.5
    cur, plus = f["scenarios"]["current"]["12m"], f["scenarios"]["plus_50"]["12m"]
    assert plus["db"] - 10 * GB == pytest.approx((cur["db"] - 10 * GB) * 1.5, rel=1e-6)
    assert f["scenarios"]["current_retention"]["12m"]["db"] < cur["db"]
