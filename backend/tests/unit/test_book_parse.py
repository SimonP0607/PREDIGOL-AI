"""The readers of ``tax-v3`` (plan Cuotas, phase 2), one format at a time, on values as the provider sent them (cut from the four
real answers of the audit, 7-8 Nov 2026). A value a reader does not recognise is None - never a plausible neighbour."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.odds.book_parse import (
    Read,
    band,
    check_book,
    format_number,
    group_outcomes,
    partition_complete,
    read_value,
    ways_of,
)
from fbi.odds.book_taxonomy import BookSpec, book_spec

D = Decimal


def spec(bet_id: int) -> BookSpec:
    found = book_spec(bet_id)
    assert found is not None
    return found


def read(bet_id: int, value: object) -> Read | None:
    return read_value(spec(bet_id), value)


def sel(bet_id: int, value: object) -> tuple[str, Decimal | None, Decimal | None]:
    got = read(bet_id, value)
    assert got is not None, value
    return got.selection, got.line, got.group


# ── plain ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_plain_reads_the_shared_words_as_the_price_history_stores_them() -> None:
    assert sel(1, "Home") == ("Home", None, None) and sel(1, " draw ") == ("Draw", None, None)
    assert sel(12, "Home/Draw") == ("1X", None, None) and sel(12, "Draw/Away") == ("X2", None, None)
    assert sel(339, "Home/Away") == ("12", None, None)
    assert sel(8, "Yes") == ("Yes", None, None) and sel(21, "Even") == ("Even", None, None)
    assert sel(2, "Away") == ("Away", None, None)


def test_plain_refuses_what_is_not_its_word_and_an_integer_alias() -> None:
    assert read(1, "Home win") is None and read(8, "Maybe") is None
    assert read(1, 1) is None, "an integer 1 is not 'Home'"
    assert read(1, None) is None and read(1, "") is None


def test_plain_vocabularies_of_their_own() -> None:
    assert sel(11, "1st Half")[0] == "1st Half" and sel(193, "2nd Half")[0] == "2nd Half" and sel(192, "Draw")[0] == "Draw"
    assert sel(14, "No goal")[0] == "No goal" and sel(185, "Away")[0] == "Away"
    assert sel(24, "Draw/Yes")[0] == "Draw/Yes" and sel(24, "Away/No")[0] == "Away/No"
    assert sel(47, "1 by 4+")[0] == "1 by 4+" and sel(47, "Score Draw")[0] == "Score Draw"
    assert sel(97, "FreeKick")[0] == "FreeKick" and sel(97, "OwnGoal")[0] == "OwnGoal"


def test_draw_is_no_goal_where_its_price_is_the_0_0_score() -> None:
    """Winning Margin and First Goal Method: "Draw" was priced exactly as the 0:0 exact score of the same bookmaker in every answer
    of the samples (17.00, 8.50, 12.00, 15.00), so it is read as the 0-0 it is, not as a draw."""
    assert sel(47, "Draw")[0] == "No goal" and sel(97, "Draw")[0] == "No goal"
    assert read(47, "1 by 5") is None


# ── lines ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_line_reads_totals_including_quarter_and_whole_lines() -> None:
    assert sel(5, "Over 2.5") == ("Over", D("2.5"), D("2.5"))
    assert sel(6, "Under 1.75") == ("Under", D("1.75"), D("1.75"))
    assert sel(45, "Over 10") == ("Over", D(10), D(10)) and sel(57, "Under 4.0") == ("Under", D(4), D(4))
    assert sel(297, "Over 0.5") == ("Over", D("0.5"), D("0.5"))


def test_line_refuses_a_negative_a_non_quarter_and_a_missing_line() -> None:
    assert read(5, "Over -1.5") is None and read(5, "Over 2.3") is None and read(5, "Over") is None
    assert read(45, "Exactly 10") is None, "bet 45 is a two-way total: it has no 'Exactly'"


def test_three_way_totals_read_exactly_at_whole_lines_only() -> None:
    assert sel(85, "Exactly 9") == ("Exactly", D(9), D(9)) and sel(77, "Exactly 4") == ("Exactly", D(4), D(4))
    assert read(77, "Exactly 4.5") is None, "nothing can be exactly 4.5 corners"
    assert read(85, "Over 9.5") is None, "Total Corners (3 way) only has whole lines"


def test_a_race_is_a_word_and_a_whole_target() -> None:
    assert sel(247, "Home 3") == ("Home", D(3), D(3)) and sel(247, "Draw 9") == ("Draw", D(9), D(9))
    assert read(247, "Home 3.5") is None and read(247, "Over 3") is None


def test_asian_handicap_prints_the_home_handicap_on_both_rows_and_the_away_row_is_negated() -> None:
    """Measured on the samples: every same-number pair is a believable two-way book (bets 4, 19, 104, 56 and 81). The away row
    gets the line that applies to it, and both rows of a pair are grouped by the home handicap (plan E1)."""
    assert sel(4, "Home -0.25") == ("Home", D("-0.25"), D("-0.25"))
    assert sel(4, "Away -0.25") == ("Away", D("0.25"), D("-0.25"))
    assert sel(56, "Away +2") == ("Away", D(-2), D(2)) and sel(81, "Home +0") == ("Home", D(0), D(0))
    level = read(19, "Away +0")
    assert level is not None and level.line == 0 and str(level.line) == "0", "a level line is 0, never -0"
    assert read(4, "Draw -0.25") is None and read(4, "Home -0.3") is None


def test_european_handicap_keeps_the_home_handicap_on_its_three_rows() -> None:
    """Handicap Result: "Home -1" 13.00, "Draw -1" 7.50, "Away -1" 1.17 is ONE three-way market at home -1 (book 1.065)."""
    assert sel(9, "Home -1") == ("Home", D(-1), D(-1)) and sel(9, "Away -1") == ("Away", D(-1), D(-1))
    assert sel(239, "Draw +2") == ("Draw", D(2), D(2)) and sel(79, "Away +0") == ("Away", D(0), D(0))
    assert read(9, "Home -0.5") is None, "a three-way handicap is a whole number"


def test_result_and_total_and_total_and_btts() -> None:
    assert sel(25, "Draw/Over 3.5") == ("Draw/Over", D("3.5"), D("3.5"))
    assert sel(25, "Away/Under 1.5") == ("Away/Under", D("1.5"), D("1.5"))
    assert sel(49, "o/yes 2.5") == ("Over/Yes", D("2.5"), D("2.5")) and sel(49, "u/no 2.5") == ("Under/No", D("2.5"), D("2.5"))
    assert read(25, "Draw/Over") is None and read(49, "o/maybe 2.5") is None


# ── scores, half-time / full-time, counts, bands ────────────────────────────────────────────────────────────────────


def test_exact_score_and_ht_ft() -> None:
    assert sel(10, "2:1") == ("2:1", None, None) and sel(31, "0:0") == ("0:0", None, None)
    assert read(10, "2-1") is None and read(10, "Any other") is None
    assert sel(7, "Home/Draw") == ("Home/Draw", None, None) and sel(7, "away/away") == ("Away/Away", None, None)
    assert read(7, "Home/Over") is None


def test_count_reads_integers_and_more_n_as_n_or_more() -> None:
    assert sel(38, 0) == ("0", None, None) and sel(38, 5) == ("5", None, None) and sel(40, "2") == ("2", None, None)
    assert sel(38, "more 6") == ("6+", None, None) and sel(46, "more 5") == ("5+", None, None)
    assert read(38, True) is None and read(38, -1) is None and read(38, "less 2") is None


def test_range_reads_both_phrasings_as_bands() -> None:
    assert [sel(295, v)[0] for v in ("Under 6", "6 - 8", "9 - 11", "12 - 14", "Over 14")] == ["0-5", "6-8", "9-11", "12-14", "15+"]
    assert [sel(349, v)[0] for v in ("Under 2 goals", "2 or 3 goals", "Over 3 goals")] == ["0-1", "2-3", "4+"]
    assert read(295, "8 - 6") is None and read(295, "Under 0") is None


def test_bands_and_partitions() -> None:
    assert band("3") == (3, 3) and band("6+") == (6, None) and band("6-8") == (6, 8) and band("x") is None
    assert partition_complete(["0", "1", "2", "3+"]) and partition_complete(["0-5", "6-8", "9-11", "12-14", "15+"])
    assert not partition_complete(["0", "1", "3+"]), "a gap"
    assert not partition_complete(["1", "2", "3+"]), "0 missing"
    assert not partition_complete(["0", "1", "2"]), "no open last band"


# ── players ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_player_names_and_the_outcomes_a_scorer_market_adds() -> None:
    assert sel(92, "Bradley Barcola") == ("Bradley Barcola", None, None)
    assert sel(231, "Mikael Egill Ellertsson")[0] == "Mikael Egill Ellertsson"
    assert sel(93, "No Goalscorer") == ("No Goalscorer", None, None)
    assert read(92, "No Goalscorer") is not None and sel(92, "N'Golo Kanté")[0] == "N'Golo Kanté"
    assert read(92, "Player 7") is None and read(92, "Dario Osorio - 2") is None and read(92, "X") is None


def test_player_count_is_a_name_and_a_threshold() -> None:
    assert sel(240, "Dario Osorio - 2") == ("Dario Osorio", D(2), D(2))
    assert sel(267, "Alisson Becker - 4") == ("Alisson Becker", D(4), D(4))
    assert sel(266, "Virgil van Dijk - 1") == ("Virgil van Dijk", D(1), D(1))
    assert read(240, "Dario Osorio") is None and read(240, "- 2") is None


# ── one bookmaker's values together ─────────────────────────────────────────────────────────────────────────────────


def priced(bet_id: int, *pairs: tuple[object, str]) -> list[tuple[Read, Decimal]]:
    out = []
    for value, odds in pairs:
        got = read(bet_id, value)
        assert got is not None
        out.append((got, D(odds)))
    return out


def test_a_selection_quoted_twice_at_two_prices_is_refused() -> None:
    assert check_book(spec(1), priced(1, ("Home", "2.00"), ("Away", "3.00"), ("Home", "2.10"))) is not None
    assert check_book(spec(1), priced(1, ("Home", "2.00"), ("Home", "2.00"))) is None, "the same price twice is harmless"


def test_bands_that_overlap_are_refused() -> None:
    """"more 6" read as "6 or more" is contradicted by a bookmaker that also quotes exactly 6."""
    assert check_book(spec(38), priced(38, (5, "6.50"), (6, "13.00"), ("more 6", "7.00"))) is not None
    assert check_book(spec(38), priced(38, (5, "6.50"), (6, "13.00"), ("more 7", "15.00"))) is None


def test_total_corners_first_half_keeps_three_way_and_two_way_lines_apart() -> None:
    """Bet 77: Bet365 quotes Over 4 / Exactly 4 / Under 4 (2.38, 5.00, 2.20: a three-way book of 1.075), Pinnacle Over 4 / Under 4
    (1.90, 1.87: a two-way book of 1.061). The same words, two markets."""
    bet365 = priced(77, ("Exactly 4", "5.00"), ("Over 4", "2.38"), ("Under 4", "2.20"))
    pinnacle = priced(77, ("Over 4", "1.90"), ("Under 4", "1.87"), ("Over 4.5", "2.20"), ("Under 4.5", "1.61"))
    assert ways_of(spec(77), [r for r, _ in bet365]) == {D(4): 3}
    assert ways_of(spec(77), [r for r, _ in pinnacle]) == {D(4): 2, D("4.5"): 2}
    assert check_book(spec(77), bet365) is None and check_book(spec(77), pinnacle) is None
    missing_exactly = priced(77, ("Over 4", "2.38"), ("Under 4", "2.20"))
    assert check_book(spec(77), missing_exactly) is not None, "a 'two-way' line with no margin is a three-way line cut short"
    assert group_outcomes(spec(77), 3) == ("Over", "Exactly", "Under") and group_outcomes(spec(77), 2) == ("Over", "Under")
    assert group_outcomes(spec(247), 3) == ("Home", "Draw", "Away")


def test_format_number() -> None:
    assert [format_number(D(x)) for x in ("2.50", "-0.25", "10", "0", "-0", "1.830")] == ["2.5", "-0.25", "10", "0", "0", "1.83"]


@pytest.mark.parametrize("bet_id", [78, 213, 215, 275, 276, 299, 61, 224, 225, 298])
def test_a_hidden_type_has_no_reader_worth_trusting(bet_id: int) -> None:
    assert not spec(bet_id).visible and spec(bet_id).hidden_reason
