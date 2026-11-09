"""The Picks board reads PrediGol Intelligence's decision (plan PICKS, F3, decision 1: one source of truth for a pick).

WHY. The board used to decide on its own: the pick engine's RAW probability (``picks.picks.p_calibrated`` holds the raw one, the
column's name notwithstanding) against the best price now. Intelligence decides the same selection with the CALIBRATED probability
(``cal-logit2-v1``) and ten filters, and the two disagreed by 7 to 13 points on what they flagged (F2, Q1). With
``FBI_PICKS_SOURCE=intelligence`` each card carries Intelligence's newest ``decision-v1`` row of its selection: the board's
value gate, EV and edge are computed with the calibrated probability, and the state a reader or the owner sees is the merge of
the board's own state and Intelligence's, below.

WHAT IT CAN AND CANNOT DO. It reads; it writes nothing and changes no decision, model, threshold, filter or settlement. And it can
only take a card AWAY from a reader: a reader is shown a card when the board's own rules (published pick, value now, the applied
review) AND Intelligence both say RECOMMENDED. A selection Intelligence has not decided is EVALUATION - nothing approves it. The
owner's preview keeps every card, labelled with both states.

    board's state     Intelligence (state-v2)          merged state            reason
    RECOMMENDED       RECOMMENDED                      RECOMMENDED             approved
    RECOMMENDED       CAUTION                          CAUTION                 downgraded
    RECOMMENDED       REJECTED                         NOT_RECOMMENDED         rejected
    RECOMMENDED       WATCH or ABSTAIN, or no decision EVALUATION              evaluation
    EVALUATION        CAUTION                          CAUTION                 downgraded      (the owner's preview groups by it)
    EVALUATION        REJECTED                         NOT_RECOMMENDED         rejected
    EVALUATION        any other                        EVALUATION              evaluation      (a shadow pick is never a recommendation)
    NOT_RECOMMENDED, CAUTION                           unchanged                               (the board's own, more specific reason)

A price above ``RISK.max_odds`` (3.00, ``risk-v1``, P5) is never RECOMMENDED here either, whatever the decision said when the
price was lower: it is CAUTION.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, get_args

from fbi.api.contracts.common import StatusReason, UserStatus
from fbi.api.contracts.product import DecisionState, PickDecision
from fbi.api.repositories import Row
from fbi.intel import state_v2
from fbi.picks.daily import RISK

Q6: Final = Decimal("0.000001")
RAW_MARK: Final = "intel_p_raw"
DECISION_MARK: Final = "intel_decision"
"""The keys the row carries once ``attach`` has read Intelligence's decision into it."""

NO_CALIBRATED: Final = "no_calibrated_probability"
"""``value_reason`` of a card whose selection has no calibrated probability: Intelligence has no champion calibrator for its market
and model, or has not decided it. The board cannot judge its value."""

_STATES: Final = frozenset(get_args(DecisionState))
_FROM_DECISION: Final[dict[str, tuple[UserStatus, StatusReason]]] = {
    "RECOMMENDED": ("RECOMMENDED", "approved"),
    "CAUTION": ("CAUTION", "downgraded"),
    "REJECTED": ("NOT_RECOMMENDED", "rejected"),
    "WATCH": ("EVALUATION", "evaluation"),
    "ABSTAIN": ("EVALUATION", "evaluation"),
}


def _dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def decision_of(row: Row, raw: Decimal) -> PickDecision:
    """The decision as the contract carries it: state-v2 of the ``decision-v1`` row (``fbi.intel.state_v2.classify``)."""
    state, reason = state_v2.classify(row)
    assert state in _STATES
    return PickDecision(
        state=state, reason=reason, known_at=row["known_at"], checkpoint=row["checkpoint"], p_calibrated=_dec(row["p_cal"]),
        p_raw=raw, ev_calibrated=_dec(row["ev_cal"]), edge_calibrated=_dec(row["edge_cal"]), odds=_dec(row["odds"]),
        price_at=row["price_at"])


def attach(rows: list[Row], decisions: list[Row]) -> list[Row]:
    """The board's candidate rows with Intelligence's decision read into each: ``p_model`` becomes the calibrated probability (so
    the value gate, the EV and the edge are computed with it), the raw one is kept under ``RAW_MARK`` and the decision under
    ``DECISION_MARK`` (None when Intelligence has not decided the selection, or has no calibrated probability for it - the raw
    probability stays then, only to be shown as «sin calibrar», never to judge value)."""
    by_selection = {(int(d["fixture_id"]), d["market_key"], d["selection"], Decimal(d["line"])): d for d in decisions}
    out: list[Row] = []
    for r in rows:
        raw = Decimal(str(r["p_model"]))
        d = by_selection.get((int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"])))
        decision = None if d is None else decision_of(d, raw)
        calibrated = None if decision is None else decision.p_calibrated
        out.append(r | {RAW_MARK: raw, DECISION_MARK: decision,
                        "p_model": raw if calibrated is None else calibrated})
    return out


def merged(status: UserStatus, reason: StatusReason, pending: bool, decision: PickDecision | None,
           *, best_odds: Decimal | None) -> tuple[UserStatus, StatusReason, bool]:
    """The state of a card once Intelligence's decision is read (see the module's table)."""
    if status in ("NOT_RECOMMENDED", "CAUTION"):
        return status, reason, pending
    verdict = _FROM_DECISION[decision.state] if decision is not None else ("EVALUATION", "evaluation")
    if status == "EVALUATION" and verdict[0] == "RECOMMENDED":
        return "EVALUATION", "evaluation", False
    cap = RISK.max_odds
    if verdict[0] == "RECOMMENDED" and best_odds is not None and cap is not None and best_odds > cap:
        return "CAUTION", "downgraded", False
    return verdict[0], verdict[1], False


def judged_value(decision: PickDecision | None) -> bool:
    """Whether the board can judge the card's value: Intelligence decided it and has a calibrated probability for it."""
    return decision is not None and decision.p_calibrated is not None


def quantized(v: Decimal | None) -> Decimal | None:
    return None if v is None else v.quantize(Q6, ROUND_HALF_UP)
