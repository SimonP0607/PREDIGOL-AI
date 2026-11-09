"""The Picks board reads PrediGol Intelligence (plan PICKS, F3): the merge of two states can only take a card away from a reader."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from itertools import product
from typing import Any, get_args

import pytest

from fbi.api.contracts.common import StatusReason, UserStatus
from fbi.api.contracts.product import DecisionState, PickDecision
from fbi.api.services import picks_decision
from fbi.core.config.picks import PicksSourceSettings
from fbi.picks import user_status

NOW = datetime(2031, 6, 16, 12, 0, tzinfo=UTC)
STATUSES: tuple[UserStatus, ...] = get_args(UserStatus)
DECISIONS: tuple[DecisionState, ...] = get_args(DecisionState)


def decision(state: DecisionState) -> PickDecision:
    return PickDecision(state=state, reason="x", known_at=NOW, checkpoint="T-3h", p_calibrated=Decimal("0.48"),
                        p_raw=Decimal("0.60"), ev_calibrated=Decimal("0.10"), edge_calibrated=Decimal("0.05"),
                        odds=Decimal("2.30"), price_at=NOW)


def intel_row(state: str, reasons: list[str], **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"id": 1, "fixture_id": 7, "market_key": "OU", "selection": "Under", "line": Decimal("2.50"),
                           "known_at": NOW, "checkpoint": "T-3h", "state": state, "reasons": reasons, "filters": [],
                           "odds": Decimal("2.10"), "price_at": NOW, "p_model": Decimal("0.60"), "p_cal": Decimal("0.48"),
                           "p_market": Decimal("0.44"), "ev_cal": Decimal("0.008"), "edge_cal": Decimal("0.04")}
    return row | over


def pick_row(**over: Any) -> dict[str, Any]:
    return {"pick_id": 1, "fixture_id": 7, "market_key": "OU", "selection": "Under", "line": Decimal("2.50"),
            "p_model": Decimal("0.60")} | over


def test_a_reader_is_shown_a_card_only_when_the_board_and_intelligence_both_say_recommended() -> None:
    """Every combination: the merge never turns a card the board withholds into one a reader is shown."""
    for status, state in product(STATUSES, (*DECISIONS, None)):
        got, _, _ = picks_decision.merged(status, "value", True, None if state is None else decision(state),
                                          best_odds=Decimal("2.30"))
        shown = user_status.for_readers(got)
        assert shown == (status == "RECOMMENDED" and state == "RECOMMENDED"), (status, state, got)


@pytest.mark.parametrize(("state", "merged"), [
    ("RECOMMENDED", ("RECOMMENDED", "approved")), ("CAUTION", ("CAUTION", "downgraded")),
    ("REJECTED", ("NOT_RECOMMENDED", "rejected")), ("WATCH", ("EVALUATION", "evaluation")),
    ("ABSTAIN", ("EVALUATION", "evaluation"))])
def test_the_states_of_a_recommended_card_follow_intelligence(state: DecisionState, merged: tuple[str, str]) -> None:
    status, reason, pending = picks_decision.merged("RECOMMENDED", "value", True, decision(state), best_odds=Decimal("2.30"))
    assert (status, reason, pending) == (*merged, False), "the review that is still pending is no longer pending: Intelligence decided"


def test_a_selection_intelligence_has_not_decided_is_in_evaluation() -> None:
    assert picks_decision.merged("RECOMMENDED", "value", True, None, best_odds=Decimal("2.30")) == ("EVALUATION", "evaluation", False)


def test_the_owner_s_preview_groups_a_shadow_pick_by_the_state_intelligence_gave_it() -> None:
    reasons: dict[DecisionState, tuple[UserStatus, StatusReason]] = {
        "CAUTION": ("CAUTION", "downgraded"), "REJECTED": ("NOT_RECOMMENDED", "rejected"),
        "WATCH": ("EVALUATION", "evaluation"), "ABSTAIN": ("EVALUATION", "evaluation"),
        "RECOMMENDED": ("EVALUATION", "evaluation")}
    for state, want in reasons.items():
        got = picks_decision.merged("EVALUATION", "evaluation", False, decision(state), best_odds=Decimal("2.30"))
        assert got[:2] == want, state


def test_the_board_s_own_more_specific_states_are_kept() -> None:
    for status in ("NOT_RECOMMENDED", "CAUTION"):
        assert picks_decision.merged(status, "no_value_now", False, decision("RECOMMENDED"),
                                     best_odds=Decimal("2.30")) == (status, "no_value_now", False)


def test_a_price_above_the_ceiling_is_never_recommended() -> None:
    """risk-v1 (P5): 3.00. Intelligence judged the price it saw at ``known_at``; the card shows the price now."""
    assert picks_decision.merged("RECOMMENDED", "value", True, decision("RECOMMENDED"), best_odds=Decimal("3.00"))[0] == "RECOMMENDED"
    assert picks_decision.merged("RECOMMENDED", "value", True, decision("RECOMMENDED"), best_odds=Decimal("3.01")) == (
        "CAUTION", "downgraded", False)


def test_the_decision_is_worded_with_state_v2() -> None:
    d = picks_decision.decision_of(intel_row("CAUTELA", ["risk"]), Decimal("0.60"))
    assert (d.state, d.reason, d.p_calibrated, d.p_raw) == ("CAUTION", "risk", Decimal("0.48"), Decimal("0.60"))
    parked = picks_decision.decision_of(intel_row("INVESTIGACION", ["edge_not_validated"]), Decimal("0.60"))
    assert (parked.state, parked.reason) == ("ABSTAIN", "edge_not_validated")
    waiting = picks_decision.decision_of(intel_row("INVESTIGACION", ["price_stale"]), Decimal("0.60"))
    assert (waiting.state, waiting.reason) == ("WATCH", "price_stale")


def test_attach_judges_value_with_the_calibrated_probability_and_keeps_the_raw_one() -> None:
    rows = [pick_row(), pick_row(pick_id=2, fixture_id=8), pick_row(pick_id=3, fixture_id=9)]
    decisions = [intel_row("APROBADO", []), intel_row("INVESTIGACION", ["not_calibrated"], fixture_id=9, p_cal=None, ev_cal=None,
                                                     edge_cal=None)]
    a, undecided, uncalibrated = picks_decision.attach(rows, decisions)
    assert a["p_model"] == Decimal("0.48") and a[picks_decision.RAW_MARK] == Decimal("0.60")
    assert picks_decision.judged_value(a[picks_decision.DECISION_MARK])
    assert undecided["p_model"] == Decimal("0.60") and undecided[picks_decision.DECISION_MARK] is None
    assert not picks_decision.judged_value(undecided[picks_decision.DECISION_MARK])
    assert uncalibrated["p_model"] == Decimal("0.60"), "without a calibrated probability the raw one stays, only to be shown as such"
    assert not picks_decision.judged_value(uncalibrated[picks_decision.DECISION_MARK])
    assert rows[0]["p_model"] == Decimal("0.60"), "the rows read are not touched"


def test_the_switch_is_off_unless_it_says_intelligence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_PICKS_SOURCE", raising=False)
    assert not PicksSourceSettings().from_intelligence
    for value, on in (("intelligence", True), (" Intelligence ", True), ("1", False), ("on", False), ("intelligense", False), ("", False)):
        monkeypatch.setenv("FBI_PICKS_SOURCE", value)
        assert PicksSourceSettings().from_intelligence is on, value
