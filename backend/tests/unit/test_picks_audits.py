"""The read-only audits of the PICKS plan (F1, F6): what they count, on rows whose answer is known."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from scripts.audit_picks_module import board_figures, bogota_day, started_figures
from scripts.audit_settlement import day_sums, tally

from fbi.picks import resettlement

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=UTC)


def card(fixture: int, market: str, selection: str, line: str = "0", odds: str | None = "2.00",
         value_now: bool = True, reason: str | None = None, age_h: float | None = 0.5) -> dict[str, Any]:
    return {"fixture_id": fixture, "market_key": market, "selection": selection, "line": Decimal(line),
            "best_odds": None if odds is None else Decimal(odds), "value_now": value_now, "value_reason": reason,
            "price_at": None if age_h is None else NOW - timedelta(hours=age_h)}


def test_the_board_figures_of_section_2() -> None:
    cards = [
        card(1, "OU", "Under", "2.5"), card(1, "OU", "Under", "3.5", value_now=False, reason="stale_price", age_h=4),
        card(1, "OU", "Over", "1.5", odds="3.40", age_h=2),
        card(2, "BTTS", "No", value_now=False, reason="stale_price", age_h=5),
        card(2, "1X2", "Away", odds="4.10", value_now=False, reason="non_positive_ev"),
        card(3, "AH", "Home", "-0.5", odds=None, age_h=None),
    ]
    f = board_figures(cards, NOW)
    assert (f["cards"], f["fixtures"]) == (6, 3)
    assert f["outside_rule_now"] == 3 and f["outside_rule_reasons"] == {"stale_price": 2, "non_positive_ev": 1}
    # OU Under on 2.5 and 3.5 is one idea on two lines
    assert f["repeated_on_another_line"] == 1
    assert (f["cards_per_fixture_median"], f["cards_per_fixture_max"]) == (2, 3)
    assert f["above_3_00"] == 2
    assert (f["goals_under"], f["goals_over"], f["btts_no"], f["btts_yes"]) == (2, 1, 1, 0)
    assert f["price_age_hours"] == {"under_1": 2, "1_to_3": 1, "over_3": 2, "no_price": 1, "newest_minutes": 30}


def test_the_started_list_counts_candidates_by_match() -> None:
    assert started_figures([{"fixture_id": 1}] * 25 + [{"fixture_id": 2}]) == {
        "candidates": 26, "fixtures": 2, "max_per_fixture": 25}
    assert started_figures([]) == {"candidates": 0, "fixtures": 0, "max_per_fixture": 0}


def test_the_bogota_day_starts_at_local_midnight() -> None:
    start, end = bogota_day(datetime(2026, 11, 8, 3, 0, tzinfo=UTC))  # 22:00 on the 7th in Bogotá
    assert start.isoformat() == "2026-11-07T00:00:00-05:00" and end - start == timedelta(days=1)


def row(status: str, profit: str | None, home: int | None, away: int | None, *, fixture: int = 10,
        short: str = "FT", basis: str | None = "regulation_90") -> dict[str, Any]:
    return {"k1": 1, "k2": None, "fixture_id": fixture, "market_key": "1X2", "selection": "Home",
            "line": Decimal(0), "price": Decimal("2.10"), "stake": Decimal(1), "status": status,
            "profit": None if profit is None else Decimal(profit), "settled_at": NOW, "basis": basis,
            "status_short": short, "reg_goals_home": home, "reg_goals_away": away, "et_goals_home": None,
            "et_goals_away": None, "ft_goals_home": None, "ft_goals_away": None, "taken_kickoff": NOW}


def test_a_stored_result_is_same_held_explained_or_unexplained() -> None:
    pick = next(k for k in resettlement.SINGLES if k.name == "pick")
    rows = [
        row("win", "1.1000", 2, 0),                    # same
        row("loss", "-1.0000", 2, 0, fixture=11),      # the score says win, no correction recorded: unexplained
        row("loss", "-1.0000", 2, 0, fixture=12),      # the same, but the result was corrected: explained
        row("win", "1.1000", None, None, short="PST"),  # the match no longer settles: held
    ]
    t = tally(pick, rows, NOW + timedelta(hours=3), revised={12})
    assert (t["examined"], t["same"], t["explained"], t["unexplained"]) == (4, 1, 1, 1)
    assert t["held"] == {"no_longer_settles": 1}
    (e,) = t["examples"]
    assert e["fixture_id"] == 11 and e["stored"] == ["loss", "-1.0000"] and e["now"][0] == "win"


def test_a_day_adds_up_when_every_item_counts_once() -> None:
    base = {"day": "2026-11-07", "source": "evaluation", "rule_version": "daily-set-v5", "units": Decimal("-0.27")}
    good = {**base, "items": 5, "won": 2, "lost": 2, "voids": 1, "open": 0, "halves": 1, "other": 0}
    bad = {**base, "items": 5, "won": 2, "lost": 2, "voids": 0, "open": 0, "halves": 0, "other": 1}
    (g, b) = day_sums([good, bad])
    assert g["adds_up"] is True and g["voids"] == 1 and g["units"] == "-0.27"
    assert b["adds_up"] is False
