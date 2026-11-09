"""Taxonomy ``tax-v3`` (plan Cuotas, phase 2): every bet type that arrived in 14 days is described, every reader reads the real
answers, the extracted types read exactly as the extractor reads them, and ``tax-v2`` is untouched.

The real answers are ``tests/fixtures/odds_book/real_answers.json``, cut from the four RAW bodies of the audit (8 Nov 2026). The
whole bodies were read once by the same code before they were cut: 11,724 values of 127 visible types, none unreadable, and the
4,619 values of the 42 extracted types read exactly as ``tax-v2`` reads them.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.odds import book_taxonomy as tax
from fbi.odds.book_parse import check_book, read_value
from fbi.odds.quote_extract import EXTRACTOR_VERSION
from fbi.odds.quote_parse import parse_odds, parse_selection
from fbi.odds.quote_taxonomy import TAXONOMY_VERSION, extracted_specs, same_name, spec_for

ANSWERS = Path(__file__).parents[1] / "fixtures" / "odds_book" / "real_answers.json"
FAMILIES_0077 = {"result", "goals", "goals_half", "corners", "cards", "shots", "fouls", "offsides", "tackles", "saves", "timing",
                 "special", "advance", "players", "other_sport", "unclassified"}
KEY = re.compile(r"^(?P<domain>[a-z0-9_]+)\.(?P<market>[a-z0-9_]+)\.(?P<period>ft|1h|2h|m\d+_\d+)(?:\.(?P<team>home|away))?$")

STABLE_KEYS: dict[int, str] = {
    1: "result.1x2.ft", 2: "result.draw_no_bet.ft", 3: "result.1x2.2h", 4: "result.asian_handicap.ft", 5: "goals.total.ft",
    6: "goals.total.1h", 7: "halves.ht_ft.ft", 8: "goals.btts.ft", 9: "result.european_handicap.ft", 10: "goals.correct_score.ft",
    11: "halves.highest_scoring.ft", 12: "result.double_chance.ft", 13: "result.1x2.1h", 14: "goals.first_team_to_score.ft",
    15: "goals.last_team_to_score.ft", 16: "goals.total.ft.home", 17: "goals.total.ft.away", 18: "result.european_handicap.1h",
    19: "result.asian_handicap.1h", 20: "result.double_chance.1h", 21: "goals.odd_even.ft", 22: "goals.odd_even.1h",
    23: "goals.odd_even.ft.home", 24: "goals.result_btts.ft", 25: "goals.result_total.ft", 26: "goals.total.2h",
    27: "goals.clean_sheet.ft.home", 28: "goals.clean_sheet.ft.away", 29: "goals.win_to_nil.ft.home",
    30: "goals.win_to_nil.ft.away", 31: "goals.correct_score.1h", 32: "halves.win_both.ft", 33: "result.double_chance.2h",
    34: "goals.btts.1h", 35: "goals.btts.2h", 36: "goals.win_to_nil.ft", 37: "halves.win_both.ft.home",
    38: "goals.exact_total.ft", 39: "halves.win_either.ft", 40: "goals.exact_total.ft.home", 41: "goals.exact_total.ft.away",
    42: "goals.exact_total.2h", 43: "goals.team_scores.ft.home", 44: "goals.team_scores.ft.away", 45: "corners.total.ft",
    46: "goals.exact_total.1h", 47: "goals.winning_margin.ft", 48: "halves.score_both.ft", 49: "goals.total_btts.ft",
    50: "goals.goal_line.ft", 53: "halves.win_both.ft.away", 54: "result.1x2.m0_10", 55: "corners.1x2.ft",
    56: "corners.asian_handicap.ft", 57: "corners.total.ft.home", 58: "corners.total.ft.away", 59: "special.own_goal.ft",
    60: "goals.odd_even.ft.away", 61: "advance.to_qualify.ft", 62: "goals.correct_score.2h", 63: "goals.odd_even.2h",
    72: "goals.goal_line.1h", 77: "corners.total.1h", 78: "goals.result_total.1h", 79: "cards.european_handicap.ft",
    80: "cards.total.ft", 81: "cards.asian_handicap.ft", 82: "cards.total.ft.home", 83: "cards.total.ft.away",
    85: "corners.total_3way.ft", 87: "shots.on_target.ft", 92: "player.anytime_scorer.ft", 93: "player.first_scorer.ft",
    94: "player.last_scorer.ft", 97: "special.first_goal_method.ft", 99: "special.penalty_scored.ft",
    100: "special.penalty_missed.ft", 104: "result.asian_handicap.2h", 105: "goals.total.1h.home", 106: "goals.total.1h.away",
    107: "goals.total.2h.home", 108: "goals.total.2h.away", 109: "result.draw_no_bet.1h", 110: "goals.score_draw.ft",
    111: "halves.score_both.ft.home", 112: "halves.score_both.ft.away", 113: "halves.btts_both.ft", 136: "result.1x2.m0_15",
    137: "result.1x2.m0_60", 138: "result.1x2.m0_75", 139: "result.1x2.m0_30", 164: "offsides.total.ft",
    167: "offsides.total.ft.home", 168: "offsides.total.ft.away", 176: "shots.on_target_1x2.ft",
    181: "result.european_handicap.2h", 182: "result.draw_no_bet.2h", 184: "halves.goal_both.ft",
    185: "goals.first_team_to_score.1h", 192: "halves.highest_scoring.ft.home", 193: "halves.highest_scoring.ft.away",
    211: "shots.total.ft", 213: "other.player_triples.ft", 215: "other.player_singles.ft", 218: "player.anytime_scorer.ft.away",
    219: "player.first_scorer.ft.away", 222: "special.win_from_behind.ft", 224: "special.decided_by_penalties.ft",
    225: "special.decided_in_extra_time.ft", 226: "player.last_scorer.ft.away", 228: "player.header_goal.ft.home",
    229: "player.outside_box_goal.ft", 231: "player.anytime_scorer.ft.home", 232: "player.first_scorer.ft.home",
    233: "player.last_scorer.ft.home", 239: "corners.european_handicap.ft", 240: "player.shots.ft.home",
    241: "player.shots.ft.away", 245: "player.header_goal.ft.away", 247: "corners.race.ft", 249: "corners.multicorners.ft",
    250: "cards.first_card.ft", 257: "player.score_or_assist.ft", 266: "player.fouls.ft", 267: "keeper.saves.ft",
    269: "player.shots_on_target.ft.home", 275: "player.shots_on_target.ft.away", 276: "player.shots_total.ft.away",
    281: "tackles.total.ft", 295: "corners.total_bands.ft", 297: "corners.total.m0_10", 298: "special.method_of_victory.ft",
    299: "cards.total.m0_10", 307: "corners.double_chance.ft", 338: "corners.odd_even.ft", 339: "corners.double_chance.ft",
    340: "shots.1x2.ft", 349: "goals.total_bands.ft",
}
"""The key of every type. A key is what the explorer, its URLs and the readers' saved markets are built on: changing one is a
decision, made here and in the web in the same change - never a side effect of tidying the taxonomy."""

HIDDEN = {61, 78, 213, 215, 224, 225, 275, 276, 298, 299}
EXTRACTED_V2 = [1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 16, 17, 19, 20, 22, 26, 33, 34, 35, 45, 55, 57, 58, 63, 80, 82, 83, 87, 88,
                89, 104, 105, 106, 107, 108, 109, 150, 151, 153, 154, 155, 156, 158, 176, 182, 192, 193, 211, 220, 221, 307,
                335, 339, 340]


def answers() -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = json.loads(ANSWERS.read_text(encoding="utf-8"))["answers"]
    return data


def all_bets() -> list[tuple[str, int, dict[str, Any]]]:
    return [(name, int(book["id"]), bet) for name, answer in answers().items() for book in answer["bookmakers"]
            for bet in book["bets"]]


# ── what is described ───────────────────────────────────────────────────────────────────────────────────────────────


def test_every_type_that_arrived_in_14_days_is_described_and_nothing_else_but_the_twin_of_339() -> None:
    ids = {s.bet_id for s in tax.book_specs()}
    assert len(tax.OBSERVED_14D) == 137
    assert ids - tax.OBSERVED_14D == {307}, "307 is the second provider id of 339 (tax-v2 extracts both)"
    assert ids >= tax.OBSERVED_14D
    assert tax.book_spec(307) is not None and tax.book_spec(307).alias_of == 339  # type: ignore[union-attr]
    assert tax.book_spec(999) is None, "a type nobody described is not shown"


def test_the_keys_are_stable() -> None:
    assert {s.bet_id: s.key for s in tax.book_specs()} == STABLE_KEYS


def test_every_key_follows_the_grammar_and_says_its_period_and_team() -> None:
    held: dict[str, int] = {}
    for spec in tax.book_specs():
        match = KEY.match(spec.key)
        assert match is not None, spec.key
        period = match["period"]
        expected = {"ft": "FT", "1h": "1H", "2h": "2H"}.get(period, "INTERVAL")
        assert spec.period == expected, (spec.bet_id, spec.key, spec.period)
        if spec.period == "INTERVAL":
            assert spec.minutes is not None and period == f"m{spec.minutes[0]}_{spec.minutes[1]}", spec.key
        else:
            assert spec.minutes is None, spec.key
        if spec.subject in ("home", "away"):
            assert match["team"] == spec.subject, spec.key
        if match["team"] and spec.subject not in ("player", "keeper"):
            assert spec.subject == match["team"], spec.key
        assert spec.market == f"{match['domain']}.{match['market']}"
        if spec.key in held:
            assert spec.alias_of == held[spec.key] or tax.book_spec(held[spec.key]).alias_of == spec.bet_id, spec.key  # type: ignore[union-attr]
        held[spec.key] = spec.bet_id


def test_every_field_speaks_the_vocabulary() -> None:
    for spec in tax.book_specs():
        assert spec.family in FAMILIES_0077, spec
        assert spec.period in tax.PERIODS and spec.subject in tax.SUBJECTS, spec
        assert spec.reader in tax.READERS and spec.fair_method in tax.FAIR_METHODS and spec.three_way in tax.THREE_WAY, spec
        if spec.reader in ("player", "player_count"):
            assert spec.subject in ("player", "keeper"), spec
        if spec.reader in ("plain", "line", "signed_line", "signed_line_3way") and spec.visible:
            assert spec.vocabulary, f"{spec.bet_id} reads a closed vocabulary"
            assert set(spec.outcomes) <= set(spec.vocabulary.values()), spec.bet_id


def test_only_the_five_classic_markets_go_to_the_parlay() -> None:
    assert {s.bet_id for s in tax.book_specs() if s.parlay} == {1, 4, 5, 8, 12}


def test_a_fair_price_needs_an_exhaustive_type_with_a_method() -> None:
    for spec in tax.book_specs():
        if not spec.exhaustive:
            assert spec.fair_method == "none" and not spec.fair, spec.bet_id
        if not spec.visible:
            assert not spec.fair
    proportional = {s.bet_id for s in tax.book_specs() if s.fair_method == "proportional"}
    assert proportional == {38, 40, 41, 42, 46, 295, 349}, "the count bands, whose outcome lists differ between bookmakers"
    without = {s.bet_id for s in tax.book_specs() if s.visible and not s.fair}
    assert without == {10, 31, 62, 32, 36, 39, 48, 99, 100, 222, 92, 93, 94, 218, 219, 226, 228, 229, 231, 232, 233, 240, 241,
                       245, 257, 266, 267, 269}, "scores, one-sided pairs and players: never a fair price"


def test_the_hidden_types_and_why() -> None:
    hidden = {s.bet_id: s.hidden_reason for s in tax.book_specs() if not s.visible}
    assert set(hidden) == HIDDEN
    assert all(reason and len(reason) > 20 for reason in hidden.values())
    assert "header-goal" in str(hidden[275]) and "240 and 241" in str(hidden[215]) and "no line" in str(hidden[299])
    assert len(tax.visible_bet_ids()) == 128, "127 of the 137, and 307"


def test_tax_v2_and_the_extractor_are_untouched() -> None:
    assert TAXONOMY_VERSION == "tax-v2" and EXTRACTOR_VERSION == "qx-1/tax-v2"
    assert sorted(s.bet_id for s in extracted_specs()) == EXTRACTED_V2
    assert tax.BOOK_TAXONOMY_VERSION == "tax-v3"
    observed_and_extracted = {s.bet_id for s in extracted_specs()} & tax.OBSERVED_14D
    assert len(observed_and_extracted) == 42


def test_the_provider_names_are_the_ones_the_extractor_knows() -> None:
    for spec in tax.book_specs():
        v2 = spec_for(spec.bet_id)
        if v2.extract:
            assert same_name(spec.name, v2.name), (spec.bet_id, spec.name, v2.name)


# ── every reader against the real answers ───────────────────────────────────────────────────────────────────────────


def test_the_fixture_is_the_four_real_answers_cut() -> None:
    data = answers()
    assert set(data) == {"premier_league", "serie_a", "primera_a", "copa_del_rey"}
    assert {(a["league"]["name"], a["fixture"]["id"]) for a in data.values()} == {
        ("Premier League", 1557459), ("Serie A", 1550190), ("Primera A", 1549859), ("Copa del Rey", 1644362)}
    seen = {bet["id"] for _, _, bet in all_bets()}
    assert len(seen) == 133 and tax.OBSERVED_14D - seen == {61, 224, 225, 298}, "the four types no sample has"


def test_every_value_of_every_visible_type_in_the_real_answers_is_read() -> None:
    read = Counter[int]()
    for name, book, bet in all_bets():
        spec = tax.book_spec(bet["id"])
        assert spec is not None, bet["id"]
        assert same_name(bet["name"], spec.name), (bet["id"], bet["name"])
        if not spec.visible:
            continue
        priced = []
        for value in bet["values"]:
            got = read_value(spec, value["value"])
            assert got is not None, f"{name} bookmaker {book} bet {bet['id']}: {value['value']!r} is not read"
            read[spec.bet_id] += 1
            odds = parse_odds(value["odd"])
            if odds is not None:
                priced.append((got, odds))
        assert check_book(spec, priced) is None, (name, book, bet["id"])
    assert set(read) == {b for _, _, bet in all_bets() if (b := bet["id"]) in tax.visible_bet_ids()}
    assert len(read) == 127


@pytest.mark.parametrize("bet_id", sorted({s.bet_id for s in extracted_specs()} & tax.OBSERVED_14D))
def test_an_extracted_type_reads_as_the_extractor_reads_it(bet_id: int) -> None:
    """For the 42 types ``market.odds_quotes`` holds, the book and the price history name a price the same way: the plan's
    acceptance (the book agrees with quote_current) rests on it."""
    spec, v2 = tax.book_spec(bet_id), spec_for(bet_id)
    assert spec is not None and spec.visible
    compared = 0
    for _, _, bet in all_bets():
        if bet["id"] != bet_id:
            continue
        for value in bet["values"]:
            mine, theirs = read_value(spec, value["value"]), parse_selection(v2, value["value"])
            assert mine is not None and theirs is not None, value
            assert (mine.selection, mine.line if mine.line is not None else Decimal(0)) == theirs, value
            compared += 1
    assert compared > 0
