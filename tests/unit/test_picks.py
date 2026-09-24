"""Value, decision rule, qualification and settlement - each on known cases."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.domain.market_probability import DevigMethod, FairProbability
from fbi.domain.odds import DecimalOdds
from fbi.domain.probability import Probability
from fbi.picks.rules import RULE_V1, VersionEvidence, decide, qualify
from fbi.picks.settlement import MatchState, Status, market_outcome, profit, settle
from fbi.picks.value import assess

D = Decimal


def fair(p: float) -> FairProbability:
    return FairProbability(Probability(p), DevigMethod.SHIN, 1.03)


# ---------------------------------------------------------------- value engine


def test_the_three_value_numbers_answer_three_questions() -> None:
    a = assess(Probability(0.55), DecimalOdds(D("2.10")), fair(0.46))
    assert a.probability_edge is not None and a.probability_edge.value == D("0.090000")
    assert a.price_edge is not None and a.price_edge.value == pytest.approx(D("2.10") * D("0.46") - 1, abs=D("1e-6"))
    assert a.expected_value.per_unit == D("0.155000")
    assert a.model_fair_odds == D("1.818")
    assert a.kelly_fraction == (D("0.155") / D("1.10")).quantize(D("0.000001"))


def test_without_a_consensus_only_the_model_side_exists() -> None:
    a = assess(Probability(0.4), DecimalOdds(D("2.00")), None)
    assert a.probability_edge is None and a.price_edge is None
    assert a.expected_value.per_unit == D("-0.200000")
    assert a.kelly_fraction == 0, "no stake is implied by a negative expectation"


def test_the_lower_bound_gives_less_credit() -> None:
    a = assess(Probability(0.55), DecimalOdds(D("2.10")), fair(0.46), p_lo=Probability(0.45))
    assert a.ev_at_lower_bound is not None and a.ev_at_lower_bound.per_unit < a.expected_value.per_unit


# --------------------------------------------------------------- decision rule


@pytest.mark.parametrize(
    ("p", "odds", "f", "market", "why"),
    [
        (0.55, "2.10", 0.46, "1X2", None),
        (0.55, "2.10", None, "1X2", "no de-vigged market consensus"),
        (0.80, "1.40", 0.66, "1X2", "outside [1.50, 5.00]"),
        (0.50, "2.05", 0.47, "1X2", "expected value"),
        (0.48, "2.30", 0.47, "1X2", "probability edge"),
        (0.55, "2.10", 0.46, "DC", "not covered"),
    ],
)
def test_the_rule_names_the_first_thing_that_failed(p: float, odds: str, f: float | None, market: str,
                                                    why: str | None) -> None:
    a = assess(Probability(p), DecimalOdds(D(odds)), fair(f) if f is not None else None)
    reason = decide(a, market)
    if why is None:
        assert reason is None
    else:
        assert reason is not None and why in reason


def test_the_rule_is_versioned_and_describable() -> None:
    d = RULE_V1.as_dict()
    assert d["version"] == "shadow-rule-v1" and d["min_ev"] == "0.05"


# --------------------------------------------------------------- qualification


def test_a_model_that_lost_to_the_market_cannot_qualify() -> None:
    q = qualify(VersionEvidence(7, "1X2", "worse", 1744, "pinnacle/closing/shin"))
    assert not q.qualified and "worse" in q.reasons[0]


def test_qualification_needs_a_backtest_a_win_and_a_sample() -> None:
    assert not qualify(VersionEvidence(None, "1X2", None, None, None)).qualified
    assert not qualify(VersionEvidence(7, "1X2", "better", 300, "pinnacle/closing/shin")).qualified
    assert qualify(VersionEvidence(7, "1X2", "better", 1744, "pinnacle/closing/shin")).qualified


# ------------------------------------------------------------------ settlement

FT = "FT"


def s(market: str, sel: str, line: str, home: int, away: int, status: str = FT, odds: str = "2.00"):
    return settle(market, sel, D(line), D(odds), D(1), MatchState(status, home, away))


def test_1x2_btts_and_double_chance() -> None:
    assert s("1X2", "Home", "0", 2, 1).status is Status.WIN
    assert s("1X2", "Draw", "0", 2, 1).status is Status.LOSS
    assert s("BTTS", "Yes", "0", 1, 1).status is Status.WIN
    assert s("BTTS", "No", "0", 0, 3).status is Status.WIN
    assert s("DC", "X2", "0", 1, 1).status is Status.WIN
    assert s("DC", "1X", "0", 0, 1).status is Status.LOSS


@pytest.mark.parametrize(
    ("sel", "line", "total", "expected"),
    [
        ("Over", "2.5", 3, Status.WIN), ("Over", "2.5", 2, Status.LOSS),
        ("Over", "3.0", 3, Status.PUSH), ("Under", "3.0", 3, Status.PUSH),
        ("Over", "2.75", 3, Status.HALF_WIN), ("Over", "2.75", 2, Status.LOSS), ("Over", "2.75", 4, Status.WIN),
        ("Over", "2.25", 2, Status.HALF_LOSS), ("Under", "2.25", 2, Status.HALF_WIN),
        ("Under", "2.75", 3, Status.HALF_LOSS), ("Under", "2.75", 2, Status.WIN),
    ],
)
def test_over_under_whole_half_and_quarter_lines(sel: str, line: str, total: int, expected: Status) -> None:
    assert s("OU", sel, line, total, 0).status is expected


@pytest.mark.parametrize(
    ("sel", "line", "home", "away", "expected"),
    [
        ("Home", "-0.5", 1, 0, Status.WIN), ("Home", "-0.5", 1, 1, Status.LOSS),
        ("Home", "-1.0", 1, 0, Status.PUSH), ("Home", "-0.75", 1, 0, Status.HALF_WIN),
        ("Home", "-0.75", 2, 0, Status.WIN), ("Home", "-0.25", 1, 1, Status.HALF_LOSS),
        ("Away", "+0.25", 1, 1, Status.HALF_WIN), ("Away", "+0.75", 1, 0, Status.HALF_LOSS),
        ("Away", "+1.5", 2, 1, Status.WIN), ("Home", "0", 0, 0, Status.PUSH),
    ],
)
def test_asian_handicap_quarter_lines(sel: str, line: str, home: int, away: int, expected: Status) -> None:
    assert s("AH", sel, line, home, away).status is expected


def test_profit_follows_the_status() -> None:
    assert profit(Status.WIN, D("2.10"), D(1)) == D("1.1000")
    assert profit(Status.HALF_WIN, D("2.10"), D(1)) == D("0.5500")
    assert profit(Status.HALF_LOSS, D("2.10"), D(1)) == D("-0.5000")
    assert profit(Status.PUSH, D("2.10"), D(1)) == 0 and profit(Status.VOID, D("2.10"), D(1)) == 0


def test_extra_time_and_penalties_do_not_change_a_90_minute_market() -> None:
    """1-1 at 90 minutes, 2-1 after extra time, or 1-1 and a shoot-out: 1X2 is a draw either way.
    The caller passes the regulation score (core.fixture_results.reg_goals_*)."""
    assert s("1X2", "Draw", "0", 1, 1, status="AET").status is Status.WIN
    assert s("1X2", "Draw", "0", 1, 1, status="PEN").status is Status.WIN
    assert s("OU", "Over", "2.5", 1, 1, status="AET").status is Status.LOSS


def test_cancelled_is_void_and_the_ambiguous_stay_pending_with_a_reason() -> None:
    void = s("1X2", "Home", "0", 0, 0, status="CANC")
    assert void.status is Status.VOID and void.profit_units == 0 and void.is_final
    for status in ("PST", "SUSP", "ABD", "AWD", "WO"):
        r = settle("1X2", "Home", D(0), D(2), D(1), MatchState(status, 3, 0))
        assert r.status is Status.PENDING and r.review_reason and "not inferred" in r.review_reason, status
        assert r.profit_units is None
    live = settle("1X2", "Home", D(0), D(2), D(1), MatchState("2H", 1, 0))
    assert live.status is Status.PENDING and live.review_reason is None, "in play is simply not over"


def test_a_finished_match_without_a_regulation_score_is_not_guessed() -> None:
    r = settle("1X2", "Home", D(0), D(2), D(1), MatchState("AET", None, None))
    assert r.status is Status.PENDING and "regulation score" in (r.review_reason or "")


def test_an_unknown_market_or_line_is_refused_not_approximated() -> None:
    assert settle("CS", "1-0", D(0), D(8), D(1), MatchState(FT, 1, 0)).status is Status.PENDING
    with pytest.raises(ValueError):
        market_outcome("OU", "Over", D("2.1"), 2, 1)
