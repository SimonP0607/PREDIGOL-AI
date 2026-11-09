"""The current-price book without a database (plan Cuotas, BE-010): what an answer becomes - which types are shown and which are
hidden and why, the lines and selections of each, the best price, the fair price only where it means something (three complete
bookmakers of an exhaustive type), the Asian handicap paired Home h with Away -h, the outlier flag - always the same for the
same answer. The answers are the real ones of ``tests/fixtures/odds_book/real_answers.json``."""

from __future__ import annotations

import copy
import json
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.core.config.odds import OddsCaptureSettings
from fbi.domain.market_probability import DevigMethod
from fbi.market.consensus import BookQuote, consensus
from fbi.odds.book import (
    BUILDER_VERSION,
    MIN_FAIR_BOOKS,
    OUTLIER_EDGE,
    PURGE_AFTER,
    read_answer,
    summarize,
    summary_json,
)
from fbi.odds.book_taxonomy import BOOK_TAXONOMY_VERSION

ANSWERS = Path(__file__).parents[1] / "fixtures" / "odds_book" / "real_answers.json"
GUIDE = Path(__file__).parents[2] / "docs" / "owner" / "CUOTAS_LIBRO_VIGENTE_BE010.md"
CLASSIC = {1: "1X2", 4: "AH", 5: "OU", 8: "BTTS", 12: "DC"}


def answer(name: str = "premier_league") -> dict[str, Any]:
    data: dict[str, dict[str, Any]] = json.loads(ANSWERS.read_text(encoding="utf-8"))["answers"]
    return copy.deepcopy(data[name])


def one_book_answer(*bets: dict[str, Any], books: tuple[int, ...] = (8,)) -> dict[str, Any]:
    return {"bookmakers": [{"id": b, "name": f"book {b}", "bets": copy.deepcopy(list(bets))} for b in books]}


def bet(bet_id: int, name: str, *values: tuple[object, str]) -> dict[str, Any]:
    return {"id": bet_id, "name": name, "values": [{"value": v, "odd": o} for v, o in values]}


def summary_of(entry: dict[str, Any], bet_id: int) -> dict[str, Any]:
    shown = read_answer(entry).shown()
    assert bet_id in shown, f"bet {bet_id} is not shown"
    return summarize(shown[bet_id].spec, shown[bet_id].prices)


def group(summary: dict[str, Any], line: float | None, ways: int | None = None) -> dict[str, Any]:
    found = [g for g in summary["lines"] if g["line"] == line and g.get("ways") == ways]
    assert len(found) == 1, (line, ways, [(g["line"], g.get("ways")) for g in summary["lines"]])
    return found[0]


def selection(g: dict[str, Any], name: str) -> dict[str, Any]:
    found = [s for s in g["sels"] if s["sel"] == name]
    assert len(found) == 1, (name, [s["sel"] for s in g["sels"]])
    return found[0]


# ── which types an answer shows ─────────────────────────────────────────────────────────────────────────────────────


def test_a_real_answer_shows_every_visible_type_and_hides_the_others_for_their_reason() -> None:
    reading = read_answer(answer())
    assert len(reading.shown()) == 127, "every visible type: the Premier League answer has all 127"
    assert set(reading.hidden_by_taxonomy) == {78, 213, 215, 275, 276, 299}
    assert not reading.unknown and all(t.hidden is None for t in reading.types.values())
    assert reading.bookmakers == 10


def test_a_type_nobody_described_is_counted_not_shown() -> None:
    reading = read_answer(one_book_answer(bet(144, "Goal in 1-15 minutes", ("Yes", "3.00"), ("No", "1.30")),
                                          bet(1, "Match Winner", ("Home", "2.0"), ("Draw", "3.4"), ("Away", "3.6"))))
    assert reading.unknown == {144: "Goal in 1-15 minutes"} and set(reading.shown()) == {1}


def test_one_unreadable_value_hides_the_whole_type_for_the_answer_and_nothing_else() -> None:
    entry = answer()
    for book in entry["bookmakers"]:
        if book["id"] == 4:  # Pinnacle
            for b in book["bets"]:
                if b["id"] == 5:
                    b["values"].append({"value": "Over 2.5 goals", "odd": "1.90"})
    reading = read_answer(entry)
    assert reading.types[5].hidden is not None and "unreadable value" in reading.types[5].hidden
    assert 5 not in reading.shown(), "the other nine bookmakers' totals are not shown either"
    assert {1, 4, 8, 12} <= set(reading.shown())


def test_a_renamed_bet_is_refused_as_the_extractor_refuses_it() -> None:
    reading = read_answer(one_book_answer(bet(8, "Both Teams To Score (90 min)", ("Yes", "1.8"), ("No", "2.0"))))
    assert reading.types[8].hidden is not None and "renamed" in reading.types[8].hidden and not reading.shown()


def test_a_bookmaker_sending_a_type_twice_hides_it() -> None:
    entry = one_book_answer(bet(8, "Both Teams Score", ("Yes", "1.8"), ("No", "2.0")),
                            bet(8, "Both Teams Score", ("Yes", "1.7"), ("No", "2.1")))
    assert read_answer(entry).types[8].hidden == "bookmaker 8 sends the type twice"


def test_a_placeholder_price_is_dropped_and_the_selection_kept_from_the_others() -> None:
    entry = one_book_answer(bet(5, "Goals Over/Under", ("Over 0.5", "1.00"), ("Under 0.5", "13.00")), books=(8, 2))
    reading = read_answer(entry)
    assert reading.dropped == 2
    s = summarize(reading.shown()[5].spec, reading.shown()[5].prices)
    assert [x["sel"] for x in group(s, 0.5)["sels"]] == ["Under"]


# ── what a type becomes ─────────────────────────────────────────────────────────────────────────────────────────────


def test_the_summary_layout() -> None:
    s = summary_of(answer(), 1)
    assert s["v"] == 2 and s["books"] == 10 and len(s["lines"]) == 1 and s["main"] is None
    g = s["lines"][0]
    assert g["line"] is None and [x["sel"] for x in g["sels"]] == ["Home", "Draw", "Away"]
    home = g["sels"][0]
    assert set(home) == {"sel", "odds", "best", "best_bk", "n", "fair", "p", "n_fair", "edge", "outlier"}
    assert home["n"] == len(home["odds"]) == 10 and home["best"] == max(home["odds"].values())
    assert home["odds"][str(home["best_bk"])] == home["best"]
    assert BUILDER_VERSION.endswith(f"/{BOOK_TAXONOMY_VERSION}") and PURGE_AFTER.total_seconds() == 6 * 3600


def test_the_main_line_is_two_and_a_half_goals_when_quoted_else_the_most_quoted_and_most_balanced() -> None:
    """``summary.main`` (layout 2, BE-011): the line the explorer shows first, decided once by the builder."""
    s = summary_of(answer(), 5)
    assert s["main"] == 2.5 and any(g["line"] == 2.5 for g in s["lines"])
    two_lines = one_book_answer(bet(80, "Cards Over/Under", ("Over 3.5", "1.50"), ("Under 3.5", "2.50"),
                                    ("Over 4.5", "1.95"), ("Under 4.5", "1.85")), books=(8, 2))
    assert summary_of(two_lines, 80)["main"] == 4.5, "both quoted by two books: the balanced line"
    wider = one_book_answer(bet(80, "Cards Over/Under", ("Over 3.5", "1.50"), ("Under 3.5", "2.50")), books=(3, 7))
    wider["bookmakers"].extend(two_lines["bookmakers"])
    assert summary_of(wider, 80)["main"] == 3.5, "four books against two: the most quoted line"
    ah = summary_of(answer(), 4)
    assert ah["main"] in {g["line"] for g in ah["lines"]}


def test_the_best_price_is_the_highest_of_all_bookmakers_and_the_lowest_id_on_a_tie() -> None:
    entry = one_book_answer(bet(8, "Both Teams Score", ("Yes", "1.80"), ("No", "2.00")), books=(11, 3, 7))
    g = group(summary_of(entry, 8), None)
    assert selection(g, "Yes")["best_bk"] == 3 and selection(g, "Yes")["n"] == 3


def test_asian_handicap_pairs_home_h_with_away_minus_h_in_one_group() -> None:
    """Plan E1 in the data model: the provider's "Home -0.25" 1.67 and "Away -0.25" 2.20 are the two sides of ONE bet, home
    -0.25 against away +0.25 - never home -0.25 against away -0.25."""
    s = summary_of(answer(), 4)
    for g in s["lines"]:
        home, away = selection(g, "Home"), selection(g, "Away")
        assert "line" not in home and away.get("line", g["line"]) == -g["line"], g["line"]
    quarter = group(s, -0.25)
    home, away = selection(quarter, "Home"), selection(quarter, "Away")
    assert away["line"] == 0.25
    both = set(home["odds"]) & set(away["odds"])
    assert len(both) >= 3 and "p" in home and "p" in away
    for book in both:
        assert 1.0 < 1 / home["odds"][book] + 1 / away["odds"][book] <= 1.25, f"bookmaker {book}: a believable two-way book"


def test_a_fair_price_needs_three_complete_bookmakers() -> None:
    match = ("Home", "2.10"), ("Draw", "3.40"), ("Away", "3.60")
    two = summary_of(one_book_answer(bet(1, "Match Winner", *match), books=(8, 2)), 1)
    assert all("fair" not in x for x in two["lines"][0]["sels"])
    three = summary_of(one_book_answer(bet(1, "Match Winner", *match), books=(8, 2, 3)), 1)
    assert all(x["n_fair"] == MIN_FAIR_BOOKS == 3 for x in three["lines"][0]["sels"])
    entry = one_book_answer(bet(1, "Match Winner", *match), books=(8, 2, 3))
    entry["bookmakers"][2]["bets"][0]["values"] = entry["bookmakers"][2]["bets"][0]["values"][:2]
    incomplete = summary_of(entry, 1)
    assert all("fair" not in x for x in incomplete["lines"][0]["sels"]), "a bookmaker without the draw is not a book"


def test_no_fair_price_where_the_type_has_no_method() -> None:
    s = summary_of(answer(), 10)  # exact score: nine bookmakers, never every score
    assert all("fair" not in x for g in s["lines"] for x in g["sels"])
    s = summary_of(answer(), 92)  # anytime scorer: one bookmaker, one-sided
    assert all("fair" not in x for g in s["lines"] for x in g["sels"])


def test_the_edge_and_the_outlier_flag() -> None:
    match = ("Home", "2.10"), ("Draw", "3.40"), ("Away", "3.60")
    entry = one_book_answer(bet(1, "Match Winner", *match), books=(8, 2, 3))
    entry["bookmakers"].append({"id": 99, "name": "odd one", "bets": [bet(1, "Match Winner", ("Home", "3.50"))]})
    g = summary_of(entry, 1)["lines"][0]
    home = selection(g, "Home")
    assert home["best"] == 3.5 and home["best_bk"] == 99 and home["n"] == 4 and home["n_fair"] == 3
    assert home["edge"] == round(3.5 * home["p"] - 1, 4) and home["edge"] > OUTLIER_EDGE and home["outlier"] is True
    draw = selection(g, "Draw")
    assert draw["outlier"] is False and draw["edge"] < 0, "the best price of the consensus books is below the fair one"


@pytest.mark.parametrize("name", ["premier_league", "copa_del_rey"])
def test_the_fair_price_of_the_five_classic_markets_is_the_consensus_one(name: str) -> None:
    """The same estimator as ``market.market_consensus`` (Shin per bookmaker, then the mean; double chance through its 1X2):
    the book and the consensus give the same probability, from the same number of bookmakers."""
    entry = answer(name)
    shown = read_answer(entry).shown()
    quotes = [BookQuote(book, CLASSIC[b], r.selection, r.line if r.line is not None else Decimal(0), odds)
              for b in CLASSIC if b in shown for book, r, odds in shown[b].prices]
    expected = {(r.market_key, r.selection, r.line): r for r in consensus(quotes, methods=(DevigMethod.SHIN,))}
    compared = 0
    for bet_id, market in CLASSIC.items():
        if bet_id not in shown:
            continue
        for g in summarize(shown[bet_id].spec, shown[bet_id].prices)["lines"]:
            for x in g["sels"]:
                line = Decimal(str(x.get("line", g["line"] if g["line"] is not None else 0)))
                row = expected.get((market, x["sel"], line))
                if "p" not in x:
                    assert row is None or row.n_bookmakers < 3, (market, x["sel"], line)
                    continue
                assert row is not None, (market, x["sel"], line)
                assert x["p"] == pytest.approx(row.p_fair, abs=1e-6) and x["n_fair"] == row.n_bookmakers
                compared += 1
    assert compared >= (60 if name == "premier_league" else 3)


def test_double_chance_goes_through_the_1x2_book_it_implies() -> None:
    s = summary_of(answer(), 12)
    sels = {x["sel"]: x for x in s["lines"][0]["sels"]}
    assert set(sels) == {"1X", "12", "X2"} and all("p" in x for x in sels.values())
    assert sum(x["p"] for x in sels.values()) == pytest.approx(2.0, abs=1e-5), "a fair double chance book sums to 2"


def test_exact_goals_are_de_vigged_in_proportion_and_a_band_needs_three_bookmakers() -> None:
    """Bet 38 in the Premier League answer: William Hill lists 0-5 and "6 or more", Bet365 and Betano 0-6 and "7 or more"."""
    g = summary_of(answer(), 38)["lines"][0]
    assert [x["sel"] for x in g["sels"]] == ["0", "1", "2", "3", "4", "5", "6", "6+", "7+"]
    assert all(x["n_fair"] == 3 for x in g["sels"] if x["sel"] in {"0", "1", "2", "3", "4", "5"})
    assert all("fair" not in x for x in g["sels"] if x["sel"] in {"6", "6+", "7+"})


def test_corners_of_the_first_half_never_compare_a_three_way_line_with_a_two_way_one() -> None:
    s = summary_of(answer(), 77)
    three, two = group(s, 4.0, 3), group(s, 4.0)
    assert [x["sel"] for x in three["sels"]] == ["Over", "Exactly", "Under"]
    assert [x["sel"] for x in two["sels"]] == ["Over", "Under"]
    assert set(selection(three, "Over")["odds"]).isdisjoint(selection(two, "Over")["odds"])


def test_players_are_ordered_by_price_and_a_scorer_markets_no_goalscorer_first() -> None:
    g = summary_of(answer(), 93)["lines"][0]
    assert g["sels"][0]["sel"] == "No Goalscorer"
    prices = [x["best"] for x in g["sels"][1:]]
    assert prices == sorted(prices)
    counts = summary_of(answer(), 240)
    assert all(g["line"] is not None and g["line"] >= 1 for g in counts["lines"]), "the threshold is the line"


def test_the_book_is_deterministic_whatever_the_order_the_bookmakers_come_in() -> None:
    entry = answer()
    first = {b: summary_json(summarize(t.spec, t.prices)) for b, t in read_answer(entry).shown().items()}
    again = {b: summary_json(summarize(t.spec, t.prices)) for b, t in read_answer(answer()).shown().items()}
    assert first == again
    shuffled = answer()
    random.Random(7).shuffle(shuffled["bookmakers"])
    for book in shuffled["bookmakers"]:
        random.Random(book["id"]).shuffle(book["bets"])
    assert {b: summary_json(summarize(t.spec, t.prices)) for b, t in read_answer(shuffled).shown().items()} == first


# ── the switch and the guide ────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "on"), [("0", False), ("off", False), ("", False), ("maybe", False), ("false", False),
                                          ("1", True), ("on", True), (" TRUE ", True), ("yes", True)])
def test_the_switch_is_off_unless_it_says_on(value: str, on: bool) -> None:
    assert OddsCaptureSettings(odds_book=value).book_enabled is on
    assert OddsCaptureSettings().book_enabled is False or OddsCaptureSettings().odds_book != "0"


def test_the_owner_guide_says_what_the_code_does() -> None:
    text = " ".join(GUIDE.read_text(encoding="utf-8").split())
    for needed in ("FBI_ODDS_BOOK", "market.book_current", "python -m scripts.rebuild_odds_book", "--apply", "--fixture",
                   "--since", "odds_book_build", "6 h", "0128", "tax-v3"):
        assert needed in text, needed
