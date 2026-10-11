"""The selection funnel and the daily set's two new stages (REVIEW PREDIGOL B1): the funnel mirrors the daily set's
own rule check by check, a price above 3.00 is a risk stop, and the context stage (context-v2) wants the AI's day read,
the match's first pass of the day and a review of the selection (unless the AI is off); a parlay's legs, the review
only (context-v1)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fbi.picks.daily import (
    CONTEXT,
    LEG_CONTEXT,
    RISK,
    AiView,
    passing,
    product_day,
    ready,
    stage_of,
)
from fbi.picks.funnel import STAGES, first_stop, report

D = Decimal
AT = datetime(2032, 8, 1, 15, tzinfo=UTC)


def row(n: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pick_id": n, "fixture_id": n, "kickoff_at": AT + timedelta(hours=5), "fixture_status": "scheduled",
        "home_team_id": 1000 + 2 * n, "away_team_id": 1001 + 2 * n, "market_key": "1X2", "selection": "Home",
        "line": D(0), "pick_status": "qualified", "model_status": "active", "p_model": D("0.50"), "p_push": None,
        "p_fair": D("0.43"), "best_odds": D("2.30"), "price_at": AT - timedelta(minutes=20), "n_bookmakers": 5,
        "p_low": D("0.46"), "competition_id": 1}
    return base | over


def keys(rows: list[dict[str, Any]]) -> set[int]:
    return {int(r["fixture_id"]) for r in rows}


def test_each_stage_says_why() -> None:
    cases = {
        ("data", "not_scheduled"): row(1, fixture_status="live"),
        ("data", "too_close_to_kickoff"): row(2, kickoff_at=AT + timedelta(minutes=5)),
        ("data", "outside_window"): row(3, kickoff_at=AT + timedelta(hours=30)),
        ("market", "no_price"): row(4, best_odds=None),
        ("market", "stale_price"): row(5, price_at=AT - timedelta(hours=4)),
        ("market", "no_consensus"): row(6, p_fair=None),
        ("market", "few_bookmakers"): row(7, n_bookmakers=1),
        ("market", "price_outlier"): row(8, best_odds=D("3.20")),
        ("model", "not_qualified"): row(9, pick_status="shadow"),
        ("model", "model_retired"): row(10, model_status="retired"),
        ("calibration", "no_interval"): row(11, p_low=None),
        ("value", "non_positive_ev"): row(12, p_model=D("0.40")),
        ("value", "no_pessimistic_growth"): row(13, p_low=D("0.30")),
    }
    for expected, r in cases.items():
        assert first_stop(r, at=AT, source="qualified") == expected, expected
    assert first_stop(row(9, pick_status="shadow"), at=AT, source="evaluation") is None, "the owner's preview"
    assert first_stop(row(14), at=AT, source="qualified") is None


def test_the_funnel_and_the_daily_set_agree_on_what_reaches_the_risk_stage() -> None:
    rows = [row(1), row(2, p_low=D("0.30")), row(3, best_odds=None), row(4, pick_status="shadow"),
            row(5, kickoff_at=AT + timedelta(hours=30)), row(6, p_model=D("0.40")),
            row(7, best_odds=D("2.40"), p_fair=D("0.41")), row(8, best_odds=D("2.10"))]  # 8: growth just below 0
    rows += [row(1, pick_id=99, p_low=None)]  # a second model version of the same selection, unmeasured
    by_funnel = {int(r["fixture_id"]) for r in rows if first_stop(r, at=AT, source="qualified") is None}
    by_set = {x.leg.candidate.fixture_id for x in passing(rows, at=AT, source="qualified")
              if x.elg > 0 and stage_of((x.leg.candidate.kickoff_at - AT).total_seconds() / 60) is not None}
    assert by_funnel == by_set == {1, 7}


def test_the_risk_stage_caps_the_price_at_three() -> None:
    assert RISK.version == "risk-v1" and RISK.max_odds == D("3.00")
    (at_cap,) = passing([row(1, best_odds=D("3.00"), p_model=D("0.40"), p_fair=D("0.33"), p_low=D("0.38"))],
                        at=AT, source="qualified")
    (above,) = passing([row(2, best_odds=D("3.10"), p_model=D("0.40"), p_fair=D("0.32"), p_low=D("0.38"))],
                       at=AT, source="qualified")
    assert RISK.stop(at_cap) is None and RISK.stop(above) == "odds_above_cap"


def test_the_context_stage_wants_the_ais_day_its_pass_and_a_review_unless_the_ai_is_off() -> None:
    (x,) = passing([row(1)], at=AT, source="qualified")
    key = x.leg.candidate.selection_key
    day = frozenset({product_day(AT)})
    reviewed = {key: {"decision": "REJECT", "id": 1}}
    assert CONTEXT.version == "context-v2"
    assert CONTEXT.stop(x, AiView(reviews=reviewed, mode="shadow", day_passed=frozenset({1}))) == "day_not_ready", \
        "the AI has not read the whole day yet"
    assert CONTEXT.stop(x, AiView(reviews=reviewed, mode="shadow", days_ready=day)) == "no_day_pass"
    assert CONTEXT.stop(x, AiView(mode="shadow", days_ready=day, day_passed=frozenset({1}))) == "not_reviewed"
    assert CONTEXT.stop(x, AiView(reviews=reviewed, mode="shadow", days_ready=day, day_passed=frozenset({1}))) is None, \
        "read on its day and reviewed: in shadow even a rejection only goes on the record"
    assert CONTEXT.stop(x, AiView(mode="off")) is None, "the AI switched off: nothing to require (ai_off)"
    assert LEG_CONTEXT.version == "context-v1" and LEG_CONTEXT.stop(x, AiView(reviews=reviewed, mode="shadow")) is None, \
        "a parlay's leg needs the review only"
    assert LEG_CONTEXT.stop(x, AiView(mode="shadow")) == "not_reviewed"


def test_the_days_set_waits_for_the_ais_first_pass_or_six_in_the_morning() -> None:
    assert not ready(time(0, 3), opened=False, first_due=0), "before 00:05 Bogotá the AI's day is not open"
    assert not ready(time(2, 0), opened=True, first_due=12), "first passes still due: the day is not read yet"
    assert ready(time(2, 0), opened=True, first_due=0)
    assert ready(time(6, 0), opened=True, first_due=12), "from 06:00 with what has been read"


def test_the_report_counts_every_stage_and_chooses_like_the_set() -> None:
    rows = [row(n, kickoff_at=AT + timedelta(hours=2 + n), best_odds=D("2.30")) for n in range(1, 8)]
    rows += [row(8, best_odds=D("3.40"), p_model=D("0.40"), p_fair=D("0.31"), p_low=D("0.38"))]  # above the cap
    rows += [row(9, pick_status="shadow")]  # not qualified
    reviewed = {(n, "1X2", "Home", D(0)): {"decision": "APPROVE", "id": n} for n in range(1, 7)}
    ai = AiView(reviews=reviewed, mode="shadow", days_ready=frozenset({product_day(AT)}),
                day_passed=frozenset(range(1, 10)))
    rep = report(rows, at=AT, source="qualified", ai=ai, taken={})
    stages = {s.key: s for s in rep.stages}
    assert [s.key for s in rep.stages] == list(STAGES)
    assert stages["model"].reasons == {"not_qualified": 1}
    assert (stages["risk"].entered, stages["risk"].passed, dict(stages["risk"].reasons)) == (8, 7, {"odds_above_cap": 1})
    assert (stages["context"].entered, stages["context"].passed) == (7, 6)
    assert dict(stages["context"].reasons) == {"not_reviewed": 1}, "F7 was never reviewed"
    assert (stages["selection"].entered, stages["selection"].passed) == (6, 5)
    assert dict(stages["selection"].reasons) == {"day_full": 1}, "five a day, never more"
    assert len(rep.chosen) == 5 and {why for _, why, _ in rep.near} >= {"odds_above_cap", "not_reviewed", "day_full"}
    taken = report(rows, at=AT, source="qualified", ai=ai, taken={rep.chosen[0][0]: {1, 2}})
    assert len(taken.chosen) == 3 and dict(taken.stages[-1].reasons) == {"match_taken": 2, "day_full": 1}
