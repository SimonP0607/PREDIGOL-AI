"""Plan F9 - the catalogue of markets: what a bet is graded ON, the keys that follow from it, and the verdicts of the matrix.

Nothing here touches the database: the rules, the keys and the verdicts are pure functions of the taxonomy and of the facts.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from fbi.market import catalogue, matrix, rules
from fbi.market.rules import RULES, RULES_BY_KEY, Decision, explain, rule_for
from fbi.odds.quote_taxonomy import BetSpec, extracted_specs, known_bet_ids, spec_for

# the period of a bet the taxonomy parks is read from its NAME (the provider's catalogue), so the bets this file reasons about are named
NAMES = {
    77: "Total Corners (1st Half)", 84: "Total Corners (3 way) (1st Half)", 125: "Corners Asian Handicap (1st Half)",
    126: "Corners Asian Handicap (2nd Half)", 127: "Total Corners (2nd Half)", 128: "Total Corners (3 way) (2nd Half)",
    130: "Corners 1x2 (1st Half)", 131: "Corners 1x2 (2nd Half)", 132: "Home Total Corners (1st Half)",
    133: "Home Total Corners (2nd Half)", 134: "Away Total Corners (1st Half)", 135: "Away Total Corners (2nd Half)",
}
ALL_SPECS = [spec_for(b, NAMES.get(b, "")) for b in sorted(known_bet_ids())]


def _spec(name: str, family: str, period: str = "FT", subject: str = "match", kind: str = "over_under", **kw: object) -> BetSpec:
    return BetSpec(bet_id=900_000, name=name, family=family, period=period, subject=subject, kind=kind, extract=True, **kw)  # type: ignore[arg-type]


# ── the rules ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_rule_is_a_measure_and_a_version() -> None:
    for r in RULES:
        assert r.key == f"{r.measure}@v{r.version}"
        assert re.fullmatch(r"[a-z][a-z0-9_]*@v[0-9]+", r.key)
        assert r.liquidable == bool(r.columns)
        assert len(r.columns) in (0, 2, 4), "a measure is a pair (home, away), or two pairs for the two halves"
        assert (not r.liquidable) == (r.reason != rules.OK), "a rule that cannot grade says why; one that can says ok"
    assert len(RULES_BY_KEY) == len(RULES)


def test_the_corners_of_a_half_cannot_be_graded_and_the_rule_says_so() -> None:
    """The provider gives corners as a total of the match: a bet on one half has nothing to be graded on."""
    for key in ("corners_1h@v1", "corners_2h@v1"):
        assert not RULES_BY_KEY[key].liquidable
        assert RULES_BY_KEY[key].reason == rules.NO_PERIOD_DATA
    halves = [s for s in ALL_SPECS if s.family == "corners" and s.period in ("1H", "2H")]
    assert len(halves) >= 10, "the taxonomy parks a dozen bets on the corners of a half"
    for s in halves:
        decision = explain(s)
        assert decision.reason == rules.NO_PERIOD_DATA and not decision.liquidable, s
        assert rule_for(s) is None and catalogue.market_key_for(s) is None, "no key is made for a market that cannot be graded"


def test_the_conventions_of_the_cards_are_separate_versioned_rules() -> None:
    measures = {r.measure for r in RULES if r.family == "cards"}
    assert {"cards_lines_ft", "cards_lines_1h", "cards_lines_2h", "yellow_ft", "yellow_1h", "yellow_2h", "red_ft",
            "cards_points_ft"} <= measures
    for name, measure in (("Cards Over/Under", "cards_lines_ft"), ("Yellow Over/Under", "yellow_ft"),
                          ("Red Cards Over/Under", "red_ft"), ("Booking Points Over/Under", "cards_points_ft")):
        decision = explain(_spec(name, "cards"))
        assert decision.rule is not None and decision.rule.measure == measure, name
    # the cards of one half, and the booking points / dismissals of a half (not kept by period), are told apart
    assert explain(_spec("Yellow Over/Under (1st Half)", "cards", "1H")).rule == RULES_BY_KEY["yellow_1h@v1"]
    assert explain(_spec("Red Cards (1st Half)", "cards", "1H")).reason == rules.NO_PERIOD_DATA
    assert explain(_spec("Booking Points (2nd Half)", "cards", "2H")).reason == rules.NO_PERIOD_DATA


def test_every_extracted_bet_can_be_graded() -> None:
    """A bet whose prices are captured and that no rule can grade is captured for nothing."""
    assert extracted_specs()
    for s in extracted_specs():
        assert rule_for(s) is not None, f"{s.bet_id} {s.name}: {explain(s).reason}"


def test_a_bet_without_a_rule_always_says_why() -> None:
    reasons = {rules.NO_PERIOD_DATA, rules.NO_DATA, rules.NOT_UNDERSTOOD, rules.KIND_NOT_GRADED, rules.PLAYER_LEVEL, rules.OUT_OF_SCOPE}
    seen: set[str] = set()
    for s in ALL_SPECS:
        decision = explain(s)
        if rule_for(s) is None:
            assert decision.reason in reasons, (s.bet_id, decision.reason)
            seen.add(decision.reason)
        else:
            assert decision.reason == rules.OK
    assert {rules.NOT_UNDERSTOOD, rules.PLAYER_LEVEL, rules.OUT_OF_SCOPE, rules.NO_PERIOD_DATA} <= seen


def test_the_kind_of_a_bet_must_fit_its_measure() -> None:
    assert explain(_spec("Corners both teams", "corners", kind="both_teams_score")).reason == rules.KIND_NOT_GRADED
    assert explain(_spec("HT/FT", "goals_half", kind="half_time_full_time")).rule == RULES_BY_KEY["goals_halves@v1"]
    assert explain(_spec("Highest half", "goals_half", "1H", kind="highest_scoring_half")).reason == rules.KIND_NOT_GRADED
    assert explain(_spec("Anything", "goals", kind="unspecified")).reason == rules.NOT_UNDERSTOOD
    assert explain(_spec("Anytime scorer", "players", kind="over_under")) == Decision(None, rules.PLAYER_LEVEL)


# ── the keys ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_keys_follow_from_the_taxonomy_and_never_collide() -> None:
    keys = catalogue.key_defs(ALL_SPECS)  # raises when two different markets ask for one key
    assert len(keys) >= 40
    for k, kd in keys.items():
        assert re.fullmatch(r"[A-Z0-9][A-Z0-9_]*", k), k
        assert kd.key == k and kd.n_outcomes in (2, 3, 9)
    assert not {"1X2", "OU", "BTTS", "DC", "AH"} & set(keys), "the five markets of the pipeline keep the keys they have"
    for example in ("OU_1H", "OU_HOME_2H", "1X2_1H", "HTFT", "CORNERS_OU", "CARDS_OU_HOME", "YELLOW_OU_1H", "SOT_1X2", "DNB", "BTTS_2H"):
        assert example in keys, example


def test_two_listings_of_one_market_share_a_key() -> None:
    """The provider lists 'Corners. Double Chance' twice (307 and 339): one market, one key."""
    a, b = spec_for(307, ""), spec_for(339, "")
    assert catalogue.market_key_for(a) == catalogue.market_key_for(b) == "CORNERS_DC"
    assert len([k for k in catalogue.key_defs(ALL_SPECS) if k == "CORNERS_DC"]) == 1


def test_the_legacy_keys_are_left_as_they_are() -> None:
    for bet_id, key in ((1, "1X2"), (5, "OU"), (8, "BTTS"), (12, "DC"), (4, "AH")):
        assert catalogue.market_key_for(spec_for(bet_id, "")) == key


# ── the verdicts ─────────────────────────────────────────────────────────────────────────────────────────────────────────

BASE = {"curated": None, "n_bets": 3, "in_principle": True, "dominant_reason": rules.OK, "n_extracted": 2, "price_fixtures": 100,
        "houses_median": 5.0, "price_coverage": 0.9, "results_n": 6000, "model_enabled": False, "edge_validated": False,
        "parent_viable": False}


@pytest.mark.parametrize(("change", "expected"), [
    ({}, (matrix.INVESTIGAR, matrix.HIGH, "priced")),
    ({"price_coverage": 0.5, "results_n": 1500}, (matrix.INVESTIGAR, matrix.MEDIUM, "priced")),
    ({"price_coverage": 0.3}, (matrix.INVESTIGAR, matrix.LOW, "priced")),
    ({"results_n": 200}, (matrix.INVESTIGAR, matrix.LOW, "priced")),
    ({"houses_median": 1.0}, (matrix.NO_VIABLE, "", "thin_price")),
    ({"houses_median": 1.0, "parent_viable": True}, (matrix.INVESTIGAR, matrix.LOW, "after_parent")),
    ({"price_fixtures": 0}, (matrix.NO_VIABLE, "", "no_prices_in_window")),
    ({"n_extracted": 0}, (matrix.INVESTIGAR, matrix.LOW, "not_extracted")),
    ({"n_extracted": 0, "houses_median": 1.0}, (matrix.NO_VIABLE, "", "thin_price")),
    ({"in_principle": False, "dominant_reason": rules.NO_PERIOD_DATA}, (matrix.NO_VIABLE, "", "no_period_data")),
    ({"n_bets": 0}, (matrix.NO_VIABLE, "", "not_offered")),
    ({"model_enabled": True}, (matrix.PARCIAL, "", "edge_not_validated")),
    ({"model_enabled": True, "edge_validated": True}, (matrix.LISTO, "", "edge_validated")),
    ({"curated": (matrix.NO_VIABLE, "", "rejected_backtest"), "model_enabled": True}, (matrix.NO_VIABLE, "", "rejected_backtest")),
])
def test_the_verdict_a_row_earns(change: dict[str, object], expected: tuple[str, str, str]) -> None:
    v = matrix.judge(**{**BASE, **change})  # type: ignore[arg-type]
    assert (v.verdict, v.priority, v.reason) == expected


def test_a_price_is_not_measured_against_one_house() -> None:
    """One house is the price, not a reference for it: the minimum is two."""
    assert matrix.MIN_HOUSES == 2


# ── the matrix ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _facts() -> matrix.Facts:
    defs = {s.bet_id: matrix.DefRow(s.bet_id, s, None) for s in ALL_SPECS}
    return matrix.Facts(at=datetime(2026, 1, 1, tzinfo=UTC), price_days=8, outcome_days=365, defs=defs, prices={},
                        first_seen={}, fixture_competition={}, finished_window=0, finished_by_type={}, finished_by_competition={},
                        measures={r.measure: matrix.MeasureStats() for r in RULES if r.liquidable}, competitions={}, keys_enabled={},
                        edge={}, calibrated={}, decisions={}, discovery={}, cards={})


def test_every_bet_is_in_exactly_one_row_of_the_matrix() -> None:
    placed = [d.spec.bet_id for rows in matrix._row_bets(_facts()).values() for d in rows]
    assert len(placed) == len(set(placed)), "a bet in two rows would be counted twice"
    assert sorted(placed) == sorted(known_bet_ids()), "a bet in no row would be missing from the matrix"


def test_the_rows_name_only_bets_the_taxonomy_knows() -> None:
    known = known_bet_ids()
    keys = [r.key for r in matrix.ROWS]
    assert len(keys) == len(set(keys))
    for row in matrix.ROWS:
        assert set(row.bets) <= known, (row.key, sorted(set(row.bets) - known))
        assert row.group in matrix.GROUPS
        assert row.parent is None or row.parent in keys
    explicit = [b for row in matrix.ROWS for b in row.bets]
    assert len(explicit) == len(set(explicit)), "a bet named by two rows"


def test_the_matrix_without_data_has_a_verdict_for_every_row() -> None:
    rows = matrix.build_rows(_facts())
    assert [r["key"] for r in rows] == [r.key for r in matrix.ROWS]
    for r in rows:
        assert r["verdict"] in (matrix.LISTO, matrix.PARCIAL, matrix.INVESTIGAR, matrix.NO_VIABLE)
        assert r["verdict"] != matrix.INVESTIGAR or r["priority"], "a row worth investigating says how urgently"
    by = {r["key"]: r for r in rows}
    assert by["corners.half"]["verdict"] == matrix.NO_VIABLE and by["corners.half"]["reason"] == rules.NO_PERIOD_DATA
    assert by["players"]["reason"] == rules.PLAYER_LEVEL and by["futures"]["reason"] == "not_offered"
    assert by["goals.team_total"]["reason"] == "rejected_backtest" and by["goals.exact_score"]["reason"] == "low_information"
