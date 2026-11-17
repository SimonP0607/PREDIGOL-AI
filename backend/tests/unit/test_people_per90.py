"""Observed rates per 90 with their sample and interval (AD-H07, IA-090)."""

from __future__ import annotations

import math

import pytest

from fbi.people import per90


def lines(*items: tuple[int, int | None]) -> list[per90.Line]:
    return [per90.Line(m, {"shots": v}) for m, v in items]


def test_a_rate_counts_only_the_matches_that_report_it() -> None:
    rt = per90.rate("shots", lines((90, 4), (90, None), (90, 2), (90, 3), (90, 1), (90, 0)))
    assert (rt.count, rt.matches, rt.minutes) == (10, 5, 450)
    assert rt.value == 2.0 and rt.sample_ok


def test_below_the_minimum_there_is_no_rate_and_without_any_report_no_zero() -> None:
    few = per90.rate("shots", lines((90, 3), (90, 1)))
    assert few.value is None and few.minutes == 180 and few.matches == 2 and not few.sample_ok
    none = per90.rate("shots", lines((90, None), (90, None)))
    assert none.value is None and none.matches == 0


def test_the_interval_is_the_poisson_score_interval() -> None:
    low, high = per90.score_interval(10, 450)
    z = per90.Z95
    t = 5.0
    assert low == pytest.approx((10 + z * z / 2 - z * math.sqrt(10 + z * z / 4)) / t)
    assert high == pytest.approx((10 + z * z / 2 + z * math.sqrt(10 + z * z / 4)) / t)
    assert low < 2.0 < high
    zero_low, zero_high = per90.score_interval(0, 900)
    assert zero_low == 0.0 and zero_high > 0


def test_an_interval_needs_minutes() -> None:
    with pytest.raises(ValueError):
        per90.score_interval(1, 0)


def test_the_profile_does_not_import_the_player_engine() -> None:
    import ast
    from pathlib import Path

    src = Path(per90.__file__).resolve().parents[1]
    for path in (src / "people" / "per90.py", src / "api" / "services" / "profiles.py",
                 src / "api" / "repositories" / "profiles.py", src / "people" / "availability.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m == "fbi.players" or m.startswith("fbi.players.") for m in mods), path
