"""The odds explorer's pure parts (plan Cuotas, BE-011): the market keys and families built from ``tax-v3``, the board's order and
its cursor, how one summary selection becomes a price of the contract, the movement's outlier rule, and the web's switch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.api import switches
from fbi.api.contracts.auth import Me
from fbi.api.problem import ApiError
from fbi.api.services.odds_explorer import (
    decode_cursor,
    encode_cursor,
    movement_points,
    read_of,
    selection_price,
    sort_key,
)
from fbi.odds.book_markets import FAMILY_ORDER, PLAYER_SELECTION, index, market_key
from fbi.odds.book_taxonomy import book_spec, book_specs

KO = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
NOW = KO - timedelta(hours=2)


def spec(bet_id: int) -> Any:
    found = book_spec(bet_id)
    assert found is not None
    return found


# ── the markets ─────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("bet_id", "key"), [(45, "corners.total"), (77, "corners.total"), (57, "corners.total.home"),
                                            (105, "goals.total.home"), (1, "result.1x2"), (13, "result.1x2"),
                                            (54, "result.1x2.m0_10"), (218, "player.anytime_scorer.away"),
                                            (267, "keeper.saves")])
def test_a_market_is_the_type_key_without_its_period(bet_id: int, key: str) -> None:
    assert market_key(spec(bet_id)) == key


def test_every_visible_type_is_in_exactly_one_market_and_a_key_and_period_name_one_market() -> None:
    idx = index()
    visible = [s for s in book_specs() if s.visible]
    assert sorted(s.bet_id for m in idx.markets for s in m.specs) == sorted(s.bet_id for s in visible)
    for s in visible:
        found = idx.find(market_key(s), s.period)
        assert found is not None and s in found.specs
    assert [s.bet_id for s in idx.find("corners.double_chance", "FT").specs] == [307, 339], "one market, lower id first"  # type: ignore[union-attr]
    assert idx.find("result.1x2", "FT").family == "result"  # type: ignore[union-attr]
    assert idx.find("result.1x2", "1H").family == idx.find("result.1x2", "2H").family == "goals_half"  # type: ignore[union-attr]
    assert idx.periods_of("result.1x2") == ("FT", "1H", "2H")
    assert idx.find("corners.total", "1H").periods == ("FT", "1H")  # type: ignore[union-attr]
    assert idx.find("result.1x2.m0_10", "INTERVAL") is not None and idx.find("result.1x2", "INTERVAL") is None


def test_the_families_come_in_the_explorers_order_and_the_markets_in_the_taxonomys() -> None:
    families = list(dict.fromkeys(m.family for m in index().markets))
    assert families == [f for f in FAMILY_ORDER if f in families]
    result = [m.key for m in index().markets if m.family == "result"]
    assert result[:3] == ["result.1x2", "result.draw_no_bet", "result.asian_handicap"]
    one_x_two = index().find("result.1x2", "FT")
    assert one_x_two is not None and one_x_two.parlay and one_x_two.fair and not one_x_two.has_line
    halves = index().find("result.1x2", "1H")
    assert halves is not None and not halves.parlay, "only the five markets of the whole match go to Mi Parlay"


# ── the board's order and cursor ────────────────────────────────────────────────────────────────────────────────────


def row(fid: int, *, league: int | None = 39, name: str = "Premier League", minutes: int = 60,
        edge: str | None = None) -> dict[str, Any]:
    return {"fixture_id": fid, "kickoff_at": KO + timedelta(minutes=minutes), "provider_league_id": league,
            "competition_name": name, "edge": None if edge is None else Decimal(edge)}


def test_the_board_orders_by_time_by_the_owners_competition_priority_or_by_edge() -> None:
    rows = [row(1, league=999, name="A league", minutes=10), row(2, minutes=50), row(3, league=2, name="Champions", minutes=90)]
    assert [r["fixture_id"] for r in sorted(rows, key=lambda r: sort_key(r, "time"))] == [1, 2, 3]
    assert [r["fixture_id"] for r in sorted(rows, key=lambda r: sort_key(r, "competition"))] == [3, 2, 1], \
        "comp-priority-v1: the Champions League and the Premier League (group 1) before the rest, then by name"
    edged = [row(1, edge="0.01"), row(2, edge="0.05"), row(3, edge="0.05", minutes=10)]
    assert [r["fixture_id"] for r in sorted(edged, key=lambda r: sort_key(r, "edge"))] == [3, 2, 1]


@pytest.mark.parametrize("sort", ["time", "competition", "edge"])
def test_a_cursor_gives_back_the_key_it_was_made_of(sort: str) -> None:
    key = sort_key(row(7, edge="0.0312"), sort)
    cursor = encode_cursor(sort, key)
    assert decode_cursor(cursor, sort) == key
    assert all(c.isalnum() or c in "-_" for c in cursor), "safe in a URL as it is"


@pytest.mark.parametrize("cursor", ["", "not-a-cursor", "eyJzIjoidGltZSJ9", encode_cursor("edge", (Decimal("1"), "x", 1))])
def test_a_cursor_the_board_did_not_give_is_refused(cursor: str) -> None:
    with pytest.raises(ApiError) as refused:
        decode_cursor(cursor, "time")
    assert refused.value.status == 422 and refused.value.code == "invalid_cursor"


# ── a selection of the book as the contract says it ─────────────────────────────────────────────────────────────────


def sel(name: str, best: float, *, line: float | None = None, fair: bool = False, outlier: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"sel": name, "odds": {"8": best, "3": best - 0.05}, "best": best, "best_bk": 8, "n": 2}
    if line is not None:
        out["line"] = line
    if fair:
        out.update(fair=1.95, p=0.512821, n_fair=3, edge=round(best * 0.512821 - 1, 4), outlier=outlier)
    return out


def test_an_asian_handicaps_away_side_carries_its_own_line_and_a_quarter_never_goes_to_mi_parlay() -> None:
    ah = spec(4)
    home = selection_price(ah, -0.5, sel("Home", 1.9, fair=True), state="current", kickoff_at=KO, moment=NOW)
    away = selection_price(ah, -0.5, sel("Away", 2.0, line=0.5, fair=True), state="current", kickoff_at=KO, moment=NOW)
    assert (home.line, away.line) == (Decimal("-0.5"), Decimal("0.5"))
    assert home.parlay_ok and away.parlay_ok
    assert home.fair_odds == Decimal("1.95") and home.price_edge == Decimal(str(round(1.9 * 0.512821 - 1, 4)))
    quarter = selection_price(ah, -0.25, sel("Home", 1.9), state="current", kickoff_at=KO, moment=NOW)
    assert not quarter.parlay_ok and quarter.fair_odds is None and quarter.price_edge is None
    assert not selection_price(ah, -0.5, sel("Home", 1.9), state="stale", kickoff_at=KO, moment=NOW).parlay_ok
    assert not selection_price(ah, -0.5, sel("Home", 1.9, fair=True, outlier=True), state="current", kickoff_at=KO,
                               moment=NOW).parlay_ok
    assert not selection_price(ah, -0.5, sel("Home", 1.9), state="current", kickoff_at=KO, moment=KO).parlay_ok


def test_a_player_market_names_the_player_apart_and_keeps_its_own_outcomes() -> None:
    first_scorer = spec(93)
    salah = selection_price(first_scorer, None, sel("Mohamed Salah", 5.5), state="current", kickoff_at=KO, moment=NOW)
    assert (salah.selection, salah.player, salah.line) == (PLAYER_SELECTION, "Mohamed Salah", None)
    nobody = selection_price(first_scorer, None, sel("No Goalscorer", 12.0), state="current", kickoff_at=KO, moment=NOW)
    assert (nobody.selection, nobody.player) == ("No Goalscorer", None)
    shots = selection_price(spec(240), 2, sel("Bukayo Saka", 1.8), state="current", kickoff_at=KO, moment=NOW)
    assert (shots.selection, shots.player, shots.line) == (PLAYER_SELECTION, "Bukayo Saka", Decimal("2"))
    assert not shots.parlay_ok and not salah.parlay_ok


# ── the movement ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_stored_price_reads_as_the_book_reads_it() -> None:
    ah = read_of(spec(4), "Away", Decimal("0.25"))
    assert (ah.selection, ah.line, ah.group) == ("Away", Decimal("0.25"), Decimal("-0.25"))
    assert read_of(spec(4), "Home", Decimal("-0.25")).group == Decimal("-0.25")
    total = read_of(spec(5), "Over", Decimal("2.5"))
    assert (total.line, total.group) == (Decimal("2.5"), Decimal("2.5"))
    one = read_of(spec(1), "Home", Decimal("0"))
    assert (one.line, one.group) == (None, None)


def snapshot(at: datetime, book: int, home: str, draw: str, away: str) -> list[dict[str, Any]]:
    return [{"captured_at": at, "bookmaker": book, "selection": s, "line": Decimal(0), "odds": Decimal(o)}
            for s, o in (("Home", home), ("Draw", draw), ("Away", away))]


def test_the_movement_is_the_best_price_of_each_capture_with_the_outliers_left_out() -> None:
    t1, t2 = KO - timedelta(hours=24), KO - timedelta(hours=3)
    rows = (snapshot(t1, 8, "2.00", "3.40", "3.80") + snapshot(t1, 3, "2.05", "3.30", "3.70")
            + snapshot(t1, 11, "1.98", "3.50", "3.75")
            + snapshot(t2, 8, "2.10", "3.40", "3.60") + snapshot(t2, 3, "2.08", "3.30", "3.55")
            + snapshot(t2, 11, "1.70", "3.00", "9.00"))  # a book with its margin, and 9.00 far above the fair price
    series = movement_points(spec(1), rows, None)
    home = series[("Home", None)]
    assert [(p.at, p.best_odds, p.bookmaker_id, p.n_books) for p in home] == [
        (t1, Decimal("2.05"), 3, 3), (t2, Decimal("2.1"), 8, 3)]
    away = series[("Away", None)]
    assert away[1].best_odds == Decimal("3.6") and away[1].n_books == 2, "the 9.00 is an outlier, never the best price"
    two_books = snapshot(t1, 8, "2.00", "3.40", "9.00") + snapshot(t1, 3, "2.05", "3.30", "3.70")
    assert movement_points(spec(1), two_books, None)[("Away", None)][0].best_odds == Decimal("9"), \
        "without three complete books there is no fair price to call anything an outlier"


# ── the web's switch ────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "on"), [(None, False), ("", False), ("0", False), ("off", False), ("si", False),
                                          ("1", True), ("on", True), (" TRUE ", True), ("yes", True)])
def test_the_explorer_is_off_unless_the_owner_says_on(value: str | None, on: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    if value is None:
        monkeypatch.delenv(switches.ODDS_EXPLORER, raising=False)
    else:
        monkeypatch.setenv(switches.ODDS_EXPLORER, value)
    assert switches.odds_explorer_on() is on


def test_me_says_the_explorer_is_off_by_default() -> None:
    assert Me.model_fields["odds_explorer"].default is False
