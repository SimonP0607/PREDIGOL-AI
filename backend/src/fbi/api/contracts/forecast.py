"""PrediGol's forecast of a match, apart from its value and from any pick (plan F5).

Three answers that used to be one: what PrediGol expects (a probability and the interval around it), whether that is well paid
(the decision layer's edge and expected value, which need a price) and what was frozen as a recommendation (a pick). A user who
may see the forecast gets the first and nothing else; the Admin Console's preview gets the three side by side, so that the
difference is visible.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.envelope import Section

Calibration = Literal["CALIBRATED", "UNCALIBRATED"]
Basis = Literal["champion", "no_champion", "needs_price", "not_applicable"]


class ForecastOutcome(Contract):
    selection: str
    probability: Decimal = Field(description="What PrediGol states: the model's own probability while the forecast is "
                                             "UNCALIBRATED, the champion calibrator's output when it is CALIBRATED.")
    low: Decimal | None = Field(description="The low end of the interval the model measured (null: it measured none).")
    high: Decimal | None
    likely: bool = Field(description="The most probable outcome of its market.")
    fair_odds: Decimal | None = Field(
        default=None, description="1 / probability. Admin preview only: a forecast is not a price, and a user is never "
                                  "shown a number that reads as odds to take.")
    model_probability: Decimal | None = Field(
        default=None, description="The model's own number before calibration. Admin preview only.")


class ForecastMarket(Contract):
    market: str
    line: Decimal
    family: str = Field(description="RESULT, TOTAL_GOALS, BOTH_TEAMS_SCORE (F10 adds more).")
    model: str
    calibration: Calibration = Field(description="UNCALIBRATED means PrediGol states the model's own number and says so: "
                                                 "calibration exists only where a champion calibrator does.")
    basis: Basis
    known_at: datetime = Field(description="When PrediGol said it. A newer set replaces it only when it moved.")
    data_cutoff_at: datetime = Field(description="The cut-off of the data the model used.")
    outcomes: list[ForecastOutcome]


class ValueRow(Contract):
    """The decision layer's newest evaluation of a selection of the match. Needs a price; admin preview only."""

    market: str
    selection: str
    line: Decimal
    state: str
    odds: Decimal | None
    probability: Decimal | None = Field(description="The calibrated probability the evaluation used (null: not calibrated).")
    market_probability: Decimal | None
    edge: Decimal | None
    ev: Decimal | None
    reasons: list[str] = Field(default_factory=list)
    known_at: datetime


class PickRow(Contract):
    """A pick frozen for the match (shadow or qualified). Admin preview only."""

    id: int
    market: str
    selection: str
    line: Decimal
    status: str
    mode: str
    odds: Decimal
    probability: Decimal | None


class MatchForecast(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    forecast: Section[list[ForecastMarket]]
    value: Section[list[ValueRow]] | None = Field(
        default=None, description="Admin preview only; null for a user. The forecast is not a value: this is.")
    picks: Section[list[PickRow]] | None = Field(
        default=None, description="Admin preview only; null for a user. Neither a forecast nor a value is a pick: this is.")
