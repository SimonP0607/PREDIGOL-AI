"""Reading one provider ``value`` / ``odd`` pair of a structured bet (plan F1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.odds.quote_parse import MAX_SELECTION_CHARS, parse_odds, parse_selection
from fbi.odds.quote_taxonomy import BetSpec, spec_for
from fbi.providers.api_football.normalize import _selection


def spec(bet_id: int) -> BetSpec:
    found = spec_for(bet_id)
    assert found.extract, bet_id
    return found


D = Decimal


# ── the five bets the pipeline reads: its own function decides ──────────────────────────────────────────────────


@pytest.mark.parametrize(("bet_id", "market", "value"), [
    (1, "1X2", "Home"), (1, "1X2", "Draw"), (1, "1X2", "Away"), (1, "1X2", "X"),
    (8, "BTTS", "Yes"), (8, "BTTS", "no"),
    (12, "DC", "Home/Draw"), (12, "DC", "Home/Away"), (12, "DC", "Draw/Away"),
    (5, "OU", "Over 2.5"), (5, "OU", "Under 0.5"), (5, "OU", "Over 3"), (5, "OU", "Over 2.3"), (5, "OU", "Over"),
    (4, "AH", "Home -1.25"), (4, "AH", "Away -1.25"), (4, "AH", "Home +0"), (4, "AH", "Away +0"),
    (4, "AH", "Away +0.75"), (4, "AH", "Home"), (4, "AH", "Draw -1"),
])
def test_the_five_are_read_exactly_as_the_pipeline_reads_them(bet_id: int, market: str, value: str) -> None:
    """Same words, same lines, same refusals: the new series and ``odds_snapshots`` cannot disagree about a row."""
    theirs = _selection(market, value)
    ours = parse_selection(spec(bet_id), value)
    if theirs is None:
        assert ours is None
    else:
        assert ours == (theirs.side.value, theirs.line_for_storage)


def test_the_asian_handicap_away_row_is_negated() -> None:
    """The provider repeats the HOME handicap on both rows of a pair: 'Away -0.25' is the away team at +0.25."""
    assert parse_selection(spec(4), "Home -0.25") == ("Home", D("-0.25"))
    assert parse_selection(spec(4), "Away -0.25") == ("Away", D("0.25"))
    assert parse_selection(spec(4), "Away +1.5") == ("Away", D("-1.5"))


# ── closed vocabularies ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("bet_id", "value", "expected"), [
    (13, "Home", "Home"), (13, "Draw", "Draw"), (13, "Away", "Away"), (55, "draw", "Draw"),
    (2, "Home", "Home"), (2, "Away", "Away"),
    (34, "Yes", "Yes"), (35, "No", "No"),
    (22, "Odd", "Odd"), (63, "Even", "Even"),
    (20, "Home/Draw", "1X"), (33, "Home/Away", "12"), (154, "Draw/Away", "X2"),
])
def test_closed_vocabularies_map_to_the_words_the_snapshots_use(bet_id: int, value: str, expected: str) -> None:
    assert parse_selection(spec(bet_id), value) == (expected, D(0))


def test_double_chance_words_are_the_same_whatever_the_bet() -> None:
    """Bet 12 goes through the pipeline's reader, bet 20 through the generic one: the words must agree."""
    for value in ("Home/Draw", "Home/Away", "Draw/Away"):
        assert parse_selection(spec(12), value) == parse_selection(spec(20), value)


@pytest.mark.parametrize(("bet_id", "value"), [
    (13, "Home or Draw"), (13, ""), (13, "   "), (13, None), (13, 1), (13, True), (2, "Draw"), (34, "Maybe"), (22, "Odd/Even"),
    (20, "Home"),
])
def test_what_is_not_in_the_vocabulary_is_refused_never_guessed(bet_id: int, value: object) -> None:
    """An integer 1 must not become 'Home' by way of the alias '1': only strings are read in a closed vocabulary."""
    assert parse_selection(spec(bet_id), value) is None


# ── over / under with a line ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("value", "expected"), [
    ("Over 2.5", ("Over", D("2.5"))), ("Under 0.5", ("Under", D("0.5"))), ("over 10.5", ("Over", D("10.5"))),
    ("Over 1", ("Over", D(1))), ("Under 2", ("Under", D(2))), ("Over 2.25", ("Over", D("2.25"))),
    ("Over 2.75", ("Over", D("2.75"))), ("  Over   3.5 ", ("Over", D("3.5"))),
])
def test_a_total_is_a_side_and_a_line(value: str, expected: tuple[str, Decimal]) -> None:
    assert parse_selection(spec(45), value) == expected


@pytest.mark.parametrize("value", [
    "Over 2.3",        # nobody quotes a third of a goal
    "Over -1.5",       # a total is never negative
    "Over",            # no line
    "2.5",             # no side
    "Exactly 2.5",     # not a side
    "Over 2,5",        # a comma is not a decimal point
    "Over 99999",      # cannot be a line
    "Over 1e2",        # no exponents
    "",
    None,
    2.5,
])
def test_a_total_that_cannot_be_read_is_refused(value: object) -> None:
    assert parse_selection(spec(45), value) is None


def test_the_team_and_half_totals_use_the_same_reader() -> None:
    for bet_id in (6, 26, 16, 17, 105, 106, 107, 108, 57, 58, 80, 82, 87, 211):
        assert parse_selection(spec(bet_id), "Under 1.5") == ("Under", D("1.5")), bet_id


def test_a_signed_handicap_schema_negates_the_away_row_and_accepts_negative_lines() -> None:
    """The 'ah' schema is for the relatives of bet 4 once their convention has been measured on their own prices."""
    handicap = BetSpec(bet_id=1, name="x", family="result", schema="ah", has_line=True, line_is_signed=True,
                       away_line_negated=True)
    assert parse_selection(handicap, "Home -0.75") == ("Home", D("-0.75"))
    assert parse_selection(handicap, "Away -0.75") == ("Away", D("0.75"))
    assert parse_selection(handicap, "Home +0") == ("Home", D(0))
    assert parse_selection(handicap, "Away +0") == ("Away", D(0))
    assert parse_selection(handicap, "Home -0.8") is None
    unsigned = BetSpec(bet_id=1, name="x", family="result", schema="ou", has_line=True)
    assert parse_selection(unsigned, "Over -0.5") is None


# ── free text ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_text_bets_keep_the_providers_words() -> None:
    assert parse_selection(spec(7), "Home/Draw") == ("Home/Draw", D(0))
    assert parse_selection(spec(7), "  Draw/Draw ") == ("Draw/Draw", D(0))
    assert parse_selection(spec(11), "1st Half") == ("1st Half", D(0))
    assert parse_selection(spec(11), "Draw") == ("Draw", D(0))


def test_a_number_is_a_selection_of_a_text_bet_but_not_of_a_closed_one() -> None:
    assert parse_selection(spec(7), 3) == ("3", D(0))
    assert parse_selection(spec(7), True) is None
    assert parse_selection(spec(7), None) is None


def test_a_selection_longer_than_the_column_is_refused() -> None:
    assert parse_selection(spec(7), "x" * MAX_SELECTION_CHARS) is not None
    assert parse_selection(spec(7), "x" * (MAX_SELECTION_CHARS + 1)) is None


def test_an_unknown_schema_reads_nothing() -> None:
    odd = BetSpec(bet_id=1, name="x", family="result", schema="nope")
    assert parse_selection(odd, "Home") is None


# ── the odds ────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("raw", "expected"), [
    ("1.90", D("1.90")), ("2", D(2)), (2.5, D("2.5")), (D("3.25"), D("3.25")), (" 4.10 ", D("4.10")),
    ("1.001", D("1.001")), ("999.999", D("999.999")),
])
def test_odds_inside_the_range_are_read(raw: object, expected: Decimal) -> None:
    assert parse_odds(raw) == expected


@pytest.mark.parametrize("raw", ["1.0", "1.00", "0.95", "0", "-2", "1000", "5000", "abc", "", None, "NaN", "Infinity"])
def test_odds_outside_the_range_or_unreadable_are_refused(raw: object) -> None:
    assert parse_odds(raw) is None
