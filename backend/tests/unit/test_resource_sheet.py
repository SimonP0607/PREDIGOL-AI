"""RP-13.3: the sheet of resources measures memory, runs that did not end well, provider requests and AI spend, and the rules of section 20 raise
their alarm between the window before a deploy and the window after it."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fbi.ops import resource_sheet as rs

T = datetime(2026, 11, 20, tzinfo=UTC)


def run(job: str, status: str = "completed", day: int = 20, calls: int = 0, rss: float | None = None, hwm: float | None = None) -> dict[str, Any]:
    return {"job": job, "status": status, "day": date(2026, 11, day), "api_calls": calls, "rss_max_mib": rss, "hwm_mib": hwm}


def sheet(rows: list[dict[str, Any]], *, days: int = 7, spend: str = "0", month: str | None = None) -> rs.Sheet:
    return rs.sheet_of(rows, since=T, until=T + timedelta(days=days), spend=Decimal(spend), month_spend=None if month is None else Decimal(month))


def test_the_sheet_counts_memory_bad_runs_requests_and_spend() -> None:
    s = sheet([run("period_backfill", "aborted", calls=40, rss=2700.5, hwm=2800), run("period_backfill", "interrupted", calls=10, rss=2600),
               run("fixtures_sync", calls=500, rss=900), run("fixtures_sync", calls=700, day=21, rss=950), run("results_sync", "failed", day=21),
               run("odds_capture", "stale", day=21)], spend="46.43", month="142.89")
    assert s.runs == 6 and s.runs_with_memory == 4
    assert s.peak_mib == 2700.5 and s.hwm_mib == 2800
    assert s.top_jobs[0] == ("period_backfill", 2700.5) and s.top_jobs[1] == ("fixtures_sync", 950)
    assert (s.bad_runs, s.bad_by_status) == (4, {"aborted": 1, "interrupted": 1, "failed": 1, "stale": 1})
    assert s.api_calls == 1250 and s.busiest_day_calls == 700
    assert s.spend_usd == Decimal("46.43") and s.month_spend_usd == Decimal("142.89")


def test_the_busiest_day_is_the_day_with_most_requests() -> None:
    s = sheet([run("a", calls=300, day=20), run("b", calls=400, day=20), run("c", calls=650, day=21)])
    assert s.busiest_day_calls == 700 and s.calls_per_day == round(1350 / 7, 1)


def test_an_empty_window_is_all_zeros_and_no_peak_not_a_made_up_one() -> None:
    s = sheet([])
    assert (s.runs, s.api_calls, s.bad_runs, s.peak_mib, s.hwm_mib, s.top_jobs) == (0, 0, 0, None, None, ())


def test_more_than_3000_extra_requests_a_day_raises_the_alarm_and_exactly_3000_does_not() -> None:
    before = sheet([run("a", calls=1000)])
    assert [a.code for a in rs.judge(before, sheet([run("a", calls=4001)]), cap_usd=Decimal(185))] == ["peticiones_adicionales"]
    assert rs.judge(before, sheet([run("a", calls=4000)]), cap_usd=Decimal(185)) == []


def test_the_spend_cap_alarm_uses_the_month_when_known_and_the_window_otherwise() -> None:
    quiet = sheet([])
    assert [a.code for a in rs.judge(quiet, sheet([], month="185.00"), cap_usd=Decimal(185))] == ["tope_de_gasto"]
    assert rs.judge(quiet, sheet([], month="184.99"), cap_usd=Decimal(185)) == []
    assert [a.code for a in rs.judge(quiet, sheet([], spend="190"), cap_usd=Decimal(185))] == ["tope_de_gasto"]


def test_memory_near_the_limit_and_a_step_up_in_the_peak_are_two_alarms() -> None:
    before = sheet([run("a", rss=2000)])
    near = rs.judge(before, sheet([run("a", rss=2800)]), cap_usd=Decimal(185))
    assert [a.code for a in near] == ["memoria_cerca_del_limite", "memoria_sube"]
    assert rs.judge(before, sheet([run("a", rss=2100)]), cap_usd=Decimal(185)) == []
    assert [a.code for a in rs.judge(before, sheet([run("a", rss=2128)]), cap_usd=Decimal(185))] == ["memoria_sube"]


def test_a_peak_that_was_already_high_and_did_not_rise_is_near_the_limit_but_not_a_step() -> None:
    before = sheet([run("a", rss=2900)])
    assert [a.code for a in rs.judge(before, sheet([run("a", rss=2890)]), cap_usd=Decimal(185))] == ["memoria_cerca_del_limite"]


def test_more_runs_without_a_good_end_a_day_is_an_alarm_and_fewer_is_not() -> None:
    before = sheet([run("a", "aborted"), run("a", "aborted")])
    assert [a.code for a in rs.judge(before, sheet([run("a", "aborted")] * 3), cap_usd=Decimal(185))] == ["abortadas_empeoran"]
    assert rs.judge(before, sheet([run("a", "aborted")]), cap_usd=Decimal(185)) == []
    assert rs.judge(sheet([]), sheet([]), cap_usd=Decimal(185)) == []


def test_the_two_windows_around_a_deploy_meet_at_its_moment() -> None:
    b0, b1, a0, a1 = rs.window(T, 7)
    assert (b1, a0) == (T, T) and b0 == T - timedelta(days=7) and a1 == T + timedelta(days=7)


def test_every_alarm_code_is_listed() -> None:
    quiet = sheet([run("a", rss=1000)])
    big = sheet([run("a", "aborted", calls=9000, rss=3000)], month="999")
    assert {a.code for a in rs.judge(quiet, big, cap_usd=Decimal(185))} == set(rs.ALARMS)
