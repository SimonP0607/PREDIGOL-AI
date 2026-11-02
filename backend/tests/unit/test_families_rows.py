"""The probabilities of a family as the markets the provider prices (plan F10): only keys the catalogue has, with the outcomes in the words of
the price tables, adding up to one."""

from __future__ import annotations

import pytest

from fbi.families import derive, halves, rows
from fbi.families.fit import NO_DISPERSION, Dispersion, Prediction, prediction
from fbi.market import catalogue
from fbi.odds.quote_taxonomy import extracted_specs

KEYS = catalogue.key_defs(list(extracted_specs()))
AVAILABLE = frozenset(KEYS)


def _pred(home: float, away: float, d: Dispersion = NO_DISPERSION) -> Prediction:
    return prediction(home, away, d)


FIRST, SECOND = _pred(0.55, 0.40), _pred(0.70, 0.55)
CORNERS = _pred(5.6, 4.4, Dispersion(0.12, 0.12, 0.09))
CARDS = _pred(2.1, 2.3, Dispersion(0.10, 0.10, 0.06))


def _check_against_the_catalogue(markets: list[rows.MarketProbs]) -> None:
    assert markets
    seen: set[tuple[str, float]] = set()
    for m in markets:
        key = KEYS[m.market_key]
        assert (m.market_key, m.line) not in seen, "one set of outcomes per market and line"
        seen.add((m.market_key, m.line))
        assert len(m.outcomes) == key.n_outcomes, (m.market_key, m.outcomes)
        assert (m.line != 0.0) == key.has_line, (m.market_key, m.line)
        assert m.total == pytest.approx(1.0, abs=1e-12)
        assert all(0.0 < p < 1.0 for _, p in m.outcomes)
        assert len({s for s, _ in m.outcomes}) == len(m.outcomes)


def test_the_goals_of_the_halves_become_markets_the_catalogue_has() -> None:
    markets = rows.goals_by_half_markets(FIRST, SECOND, available=AVAILABLE)
    _check_against_the_catalogue(markets)
    assert {m.market_key for m in markets} == {
        "OU_1H", "OU_2H", "OU_HOME_1H", "OU_AWAY_1H", "OU_HOME_2H", "OU_AWAY_2H", "1X2_1H", "1X2_2H", "DNB_1H", "DNB_2H", "DC_1H", "DC_2H",
        "BTTS_1H", "BTTS_2H", "HTFT", "HSH", "HSH_HOME", "HSH_AWAY"}


def test_the_outcomes_are_named_as_the_price_tables_name_them() -> None:
    by_key = {(m.market_key, m.line): [s for s, _ in m.outcomes] for m in rows.goals_by_half_markets(FIRST, SECOND, available=AVAILABLE)}
    assert by_key[("OU_1H", 1.5)] == ["Over", "Under"]
    assert by_key[("1X2_1H", 0.0)] == ["Home", "Draw", "Away"]
    assert by_key[("DNB_2H", 0.0)] == ["Home", "Away"]
    assert by_key[("DC_1H", 0.0)] == ["1X", "12", "X2"]
    assert by_key[("BTTS_2H", 0.0)] == ["Yes", "No"]
    assert by_key[("HSH", 0.0)] == ["1st Half", "Draw", "2nd Half"] == by_key[("HSH_HOME", 0.0)]
    assert by_key[("HTFT", 0.0)] == [f"{ht}/{ft}" for ht in ("Home", "Draw", "Away") for ft in ("Home", "Draw", "Away")]


def test_the_probabilities_are_those_of_the_derivations() -> None:
    by_key = {(m.market_key, m.line): dict(m.outcomes) for m in rows.goals_by_half_markets(FIRST, SECOND, available=AVAILABLE)}
    assert by_key[("OU_1H", 0.5)]["Over"] == pytest.approx(derive.count_line(FIRST.pmf_total, 0.5).over, abs=1e-5)
    h, x, a = derive.result(SECOND)
    assert (by_key[("1X2_2H", 0.0)]["Home"], by_key[("1X2_2H", 0.0)]["Draw"], by_key[("1X2_2H", 0.0)]["Away"]) == pytest.approx((h, x, a), abs=1e-5)
    assert by_key[("BTTS_1H", 0.0)]["Yes"] == pytest.approx(derive.both_score(FIRST), abs=1e-5)
    cells = halves.half_time_full_time(FIRST, SECOND)
    assert by_key[("HTFT", 0.0)]["Draw/Home"] == pytest.approx(cells["X/1"], abs=1e-5)
    best = halves.highest_scoring_half(FIRST.pmf_total, SECOND.pmf_total)
    assert by_key[("HSH", 0.0)]["2nd Half"] == pytest.approx(best[2], abs=1e-5)


def test_corners_become_the_markets_of_the_corners() -> None:
    markets = rows.count_markets(CORNERS, prefix="CORNERS", total_lines=(8.5, 9.5, 10.5), side_lines=(3.5, 4.5, 5.5), available=AVAILABLE)
    _check_against_the_catalogue(markets)
    assert {m.market_key for m in markets} == {"CORNERS_OU", "CORNERS_OU_HOME", "CORNERS_OU_AWAY", "CORNERS_1X2", "CORNERS_DC"}
    assert sorted(m.line for m in markets if m.market_key == "CORNERS_OU") == [8.5, 9.5, 10.5]
    over = {m.line: dict(m.outcomes)["Over"] for m in markets if m.market_key == "CORNERS_OU"}
    assert over[8.5] > over[9.5] > over[10.5]


def test_cards_and_their_kinds_only_get_the_keys_the_catalogue_has() -> None:
    cards = rows.count_markets(CARDS, prefix="CARDS", total_lines=(3.5, 4.5), side_lines=(1.5, 2.5), available=AVAILABLE)
    assert {m.market_key for m in cards} == {"CARDS_OU", "CARDS_OU_HOME", "CARDS_OU_AWAY"}, "there is no 1X2 or double chance of the cards"
    yellow = rows.count_markets(CARDS, prefix="YELLOW", total_lines=(2.5, 3.5), side_lines=(1.5,), available=AVAILABLE)
    assert {m.market_key for m in yellow} == {"YELLOW_OU", "YELLOW_OU_HOME", "YELLOW_OU_AWAY", "YELLOW_1X2", "YELLOW_DC"}
    red = rows.count_markets(_pred(0.09, 0.11), prefix="RED", total_lines=(0.5,), side_lines=(0.5,), available=AVAILABLE)
    assert {m.market_key for m in red} == {"RED_OU"}
    for markets in (cards, yellow, red):
        _check_against_the_catalogue(markets)


def test_a_family_never_invents_a_key() -> None:
    assert rows.goals_by_half_markets(FIRST, SECOND, available=frozenset()) == []
    only_total = rows.count_markets(CORNERS, prefix="CORNERS", total_lines=(9.5,), side_lines=(4.5,), available=frozenset({"CORNERS_OU"}))
    assert [m.market_key for m in only_total] == ["CORNERS_OU"]
    only = rows.goals_by_half_markets(FIRST, SECOND, available=frozenset({"HTFT"}))
    assert [m.market_key for m in only] == ["HTFT"]


def test_a_probability_is_never_zero_or_one_and_the_set_still_adds_up() -> None:
    sure = _pred(0.02, 0.02)  # a half in which almost nothing happens
    markets = rows.half_markets(sure, period="1H", total_lines=(0.5, 1.5, 2.5), side_lines=(0.5,), available=AVAILABLE)
    for m in markets:
        assert m.total == pytest.approx(1.0, abs=1e-12) and all(0.0 < p < 1.0 for _, p in m.outcomes)
    tail = next(m for m in markets if m.market_key == "OU_1H" and m.line == 2.5)
    assert dict(tail.outcomes)["Over"] >= rows.CLIP / 2
