"""What a post-mortem of one selection starts from (plan F8, ``fbi.intel.pm_facts``): a selection that the picks, the AI and the decision
layer all priced is ONE candidate whose price taken is chosen by a stated order and whose other prices stay visible, and the facts a loss is
classified by are read from the review, the packet and the match's findings exactly as the first post-mortem by selection read them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fbi.intel.pm_facts import build_facts, resolve
from fbi.intel.pm_questions import classify

KEY = (1, "1X2", "Home", Decimal("0.00"))
KICKOFF = datetime(2032, 8, 1, 20, tzinfo=UTC)
REVIEWED = KICKOFF - timedelta(hours=6)


def item(**kw: Any) -> dict[str, Any]:
    return {"role": "daily_pick", "odds": Decimal("2.10"), "bookmaker_id": 7, "p_model": Decimal("0.55"), "p_market": Decimal("0.46"),
            "price_at": KICKOFF - timedelta(hours=8), "selected_at": KICKOFF - timedelta(hours=7)} | kw


def review(**kw: Any) -> dict[str, Any]:
    return {"review_id": 90, "decision": "APPROVE", "odds": Decimal("2.00"), "bookmaker_id": 8, "p_model": Decimal("0.52"),
            "p_market": Decimal("0.47"), "reviewed_at": REVIEWED, "packet_id": 5, "output": {}} | kw


def decision(**kw: Any) -> dict[str, Any]:
    return {"id": 300, "odds": Decimal("2.05"), "bookmaker_id": 9, "price_at": KICKOFF - timedelta(hours=5),
            "p_model": Decimal("0.50"), "p_cal": Decimal("0.48"), "p_market": Decimal("0.45"), "known_at": KICKOFF - timedelta(hours=4),
            "state": "CAUTELA", "checkpoint": "T-4h", "score": Decimal("61.5"), "context_status": "PARTIAL", "context": {},
            "decision_result": "loss", "decision_clv": Decimal("-0.02")} | kw


def candidate(**parts: Any):
    return resolve(KEY, item=parts.get("item"), review=parts.get("review"), decision=parts.get("decision"),
                   roles=parts.get("roles", set()), ai_studied=parts.get("ai", True))


def facts(c: Any, **kw: Any):
    args: dict[str, Any] = {"settled": "loss", "kickoff": KICKOFF, "findings": None, "packet": None, "p_close": 0.44,
                            "close_odds": 2.0, "first_lineup": None} | kw
    return build_facts(c, **args)


# ── which price is the price taken ──────────────────────────────────────────

def test_the_price_taken_is_the_one_a_person_saw_then_the_one_the_decision_froze_then_the_one_a_reviewer_read() -> None:
    c = candidate(item=item(), decision=decision(), review=review())
    assert (c.odds, c.bookmaker_id, c.price_from) == (2.10, 7, "item")
    assert set(c.prices) == {"item", "decision", "review"} and c.prices["review"]["odds"] == 2.00 and c.prices["decision"]["bookmaker_id"] == 9
    c = candidate(decision=decision(), review=review())
    assert (c.odds, c.bookmaker_id, c.price_from) == (2.05, 9, "decision")
    c = candidate(review=review())
    assert (c.odds, c.bookmaker_id, c.price_from) == (2.00, 8, "review")
    c = candidate(decision=decision(odds=None), review=review())
    assert c.price_from == "review", "a part that has no price does not take it"


def test_the_probability_is_read_from_the_same_part_as_the_price_and_a_decisions_is_the_calibrated_one() -> None:
    assert candidate(item=item(), decision=decision(), review=review()).p_model == 0.55
    c = candidate(decision=decision(), review=review())
    assert (c.p_model, c.p_market) == (0.48, 0.45), "calibrated, as the decision layer judges it"
    assert candidate(decision=decision(p_cal=None)).p_model == 0.50, "the raw one when there is no calibrated"
    assert candidate(review=review()).p_model == 0.52


def test_the_age_of_a_price_is_known_only_where_it_is_recorded() -> None:
    assert candidate(item=item()).taken_at == KICKOFF - timedelta(hours=7)
    assert candidate(decision=decision()).taken_at == KICKOFF - timedelta(hours=4)
    c = candidate(review=review())
    assert c.price_at is None and c.taken_at is None, "a review reads the consensus of every market: no age"


def test_why_a_selection_was_studied_is_every_part_that_looked_at_it() -> None:
    c = candidate(item=item(), decision=decision(), review=review(decision="REJECT"), roles={"daily_pick", "llm"})
    assert c.roles == {"daily_pick", "llm", "decision", "reviewed", "rejected"}
    assert candidate(decision=decision(), ai=False).roles == {"decision"} and not candidate(decision=decision(), ai=False).ai_studied


def test_a_decision_without_a_review_row_still_says_what_its_review_decided() -> None:
    c = candidate(decision=decision(context={"review": {"decision": "DOWNGRADE"}}), ai=False)
    assert c.review_decision == "DOWNGRADE" and c.review_id is None
    assert candidate(decision=decision(context={"review": {"decision": "DOWNGRADE"}}), review=review()).review_decision == "APPROVE", \
        "the review row, when there is one, is what the review decided"


# ── the facts a loss is classified by ───────────────────────────────────────

def test_a_price_older_than_three_hours_when_it_was_taken_is_a_stale_price_but_only_where_the_age_is_recorded() -> None:
    stale_item = candidate(item=item(price_at=KICKOFF - timedelta(hours=12), selected_at=KICKOFF - timedelta(hours=8)))
    assert facts(stale_item).stale_price and classify(facts(stale_item)) == "EXECUTION_ERROR"
    assert not facts(candidate(item=item())).stale_price, "an hour old: fine"
    old_decision = candidate(decision=decision(price_at=KICKOFF - timedelta(hours=9), known_at=KICKOFF - timedelta(hours=4)))
    assert facts(old_decision).stale_price
    assert not facts(candidate(review=review())).stale_price, "a review's price has no recorded age: never judged stale"


def test_a_key_absence_counts_on_the_chosen_side_only_and_for_both_on_a_total() -> None:
    packet = {"quality": {}, "absences": {"home": {"players": [{"key": True, "name": "Nine", "type": "Missing Fixture"},
                                                              {"key": True, "name": "Maybe", "type": "Questionable"},
                                                              {"key": False, "name": "Bench"}]},
                                          "away": {"players": [{"key": True, "name": "Keeper", "type": "Missing Fixture"}]}}}
    home = facts(candidate(review=review()), packet=packet)
    assert home.key_absence == ["Nine (local)"], "a doubt is not an absence, a bench player is not a key one, the other side is not ours"
    assert classify(home) == "CONTEXT_ERROR", "a known key absence on the chosen side that the review approved"
    total = resolve((1, "OU", "Over", Decimal("2.5")), item=None, review=review(), decision=None, roles=set(), ai_studied=True)
    both = build_facts(total, settled="loss", kickoff=KICKOFF, findings=None, packet=packet, p_close=0.5, close_odds=2.0, first_lineup=None)
    assert both.key_absence == ["Nine (local)", "Keeper (visitante)"]


def test_a_report_that_proved_wrong_hurts_the_pick_only_when_it_made_the_opponent_look_weaker() -> None:
    wrong_for_the_away_side = {"evidence": [{"verdict": "wrong", "side": "away", "tier": "official", "claim": "Keeper: out"}]}
    wrong_for_our_side = {"evidence": [{"verdict": "wrong", "side": "home", "tier": "official", "claim": "Nine: out"}]}
    assert facts(candidate(review=review()), findings=wrong_for_the_away_side).information_failed
    assert not facts(candidate(review=review()), findings=wrong_for_our_side).information_failed
    missing = {"missing_information": [{"side": "home", "player": "Nine", "player_id": 9}, {"side": "away", "player": "Keeper"}]}
    f = facts(candidate(review=review()), findings=missing)
    assert f.information == ["titular habitual ausente sin reporte: Nine (local)"], "an unreported absence counts on our side only"
    assert f.lineup_changed is False
    assert facts(candidate(review=review()), findings=wrong_for_the_away_side).lineup_changed, "a player reported out who started"


def test_the_lineups_that_came_after_the_last_review_change_the_picture_unless_the_review_had_seen_them() -> None:
    first = KICKOFF - timedelta(hours=1)
    assert facts(candidate(review=review()), first_lineup=first).lineup_changed
    assert not facts(candidate(review=review(output={"lineups_seen": True})), first_lineup=first).lineup_changed
    assert not facts(candidate(review=review()), first_lineup=REVIEWED - timedelta(hours=1)).lineup_changed, "before the review: it saw them"
    assert not facts(candidate(decision=decision(), ai=False), first_lineup=first).lineup_changed, "no review time, no claim"


def test_the_quality_of_the_competition_and_the_signals_of_the_review_are_read_and_a_null_in_its_output_is_not_a_crash() -> None:
    unfit = {"quality": {"competition_score": {"class": "PRODUCT_ONLY"}}, "absences": None}
    assert facts(candidate(review=review()), packet=unfit).data_unfit and classify(facts(candidate(review=review()), packet=unfit)) == "DATA_ERROR"
    quarantined = {"quality": {"fixture_validation": {"state": "QUARANTINED"}}}
    assert facts(candidate(review=review()), packet=quarantined).data_unfit
    output = {"negative_evidence": [{"code": "edge_within_noise"}], "uncertainties": [{"code": "kickoff_changed"}, {"code": "lineups_confirmed"}],
              "contradictions": None}
    f = facts(candidate(review=review(output=output)))
    assert f.edge_in_noise and f.kickoff_changed and f.ignored == ["edge_within_noise", "kickoff_changed"]
    assert facts(candidate(review=review(output={"negative_evidence": None}))).ignored == []


def test_the_closing_numbers_are_the_ones_given_and_the_decision_is_what_the_review_said() -> None:
    f = facts(candidate(item=item(), review=review(decision="REJECT")), p_close=0.44, close_odds=2.0)
    assert (f.odds, f.close_odds, f.p_close, f.decision) == (2.10, 2.0, 0.44, "REJECT")
    assert f.price_move == 0.05 and f.clv == round(2.10 * 0.44 - 1, 4)
