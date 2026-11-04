"""«Cómo le va a PrediGol» (plan UX, A12; section 31 of the plan): what PrediGol published and how it went, the days without
picks and why, the results by kind of bet, the line value, the forecast's calibration and what is still in evaluation - always
with its sample. Reading only: nothing here changes a pick, a model or a rule, and the evaluation set is never read."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

Period = Literal["7d", "30d", "all"]
NoPickReason = Literal["no_matches", "no_qualified_candidates", "not_chosen"]
StopKey = Literal["data", "model", "market", "calibration", "ev", "context", "risk", "correlation", "price", "final"]


class Tally(Contract):
    """The published picks of a group, counted the way Mis picks counts PrediGol's picks (``fbi.userdata.records``): a flat
    stake of one unit per settled pick, a void returns it, a push wins nothing."""

    published: int = Field(description="Picks published (items of the qualified set).")
    pending: int = Field(description="Not settled yet.")
    won: int
    lost: int
    half_won: int = Field(description="Half won (an Asian line split between a win and a push).")
    half_lost: int
    push: int = Field(description="Returned: the stake back, no profit.")
    void: int = Field(description="Voided: not a bet (a match not played, a market cancelled).")
    settled: int = Field(description="Settled with a stake - won, lost, the halves and the pushes: the n of the sample.")
    units: Decimal | None = Field(description="The profit in units, from min_sample settled picks; null below (counts "
                                              "only).")
    roi: Decimal | None = Field(description="Units over settled stakes, a share; null below min_sample.")
    margin: Decimal | None = Field(description="Plus or minus one standard error of the ROI, a share: 1 / sqrt(settled) "
                                               "(0.20 with 25, 0.10 with 100); null below min_sample.")
    conclusive: bool = Field(description="False below `conclusive` settled picks: the page says the sample does not allow "
                                         "a conclusion yet.")


class PeriodTally(Tally):
    period: Period
    since: date | None = Field(description="The first day counted, in the reader's time zone; null for the whole history.")
    until: date = Field(description="The last day counted (today, in the reader's time zone).")


class MarketTally(Tally):
    market: str = Field(description="The kind of bet (1X2, OU, BTTS, AH, DC...), or `other`: every kind with fewer than "
                                    "min_sample settled picks, together.")


class NoPickDay(Contract):
    day: date = Field(description="A product day (America/Bogota) whose qualified set had no pick.")
    reason: NoPickReason = Field(description="no_matches: no match of the followed competitions; no_qualified_candidates: no "
                                             "forecast of a model that beat the market in its own test, so nothing could be "
                                             "published; not_chosen: there were such candidates and none met the rest of "
                                             "the rule.")
    matches: int = Field(description="The day's matches of the followed competitions.")
    measured: int = Field(description="The selections PrediGol Intelligence measured for the day's matches (its decisions "
                                      "saved), in evaluation - a count, never the selections.")
    stop: StopKey | None = Field(description="Reconstructed from the decisions saved: the commonest first filter that "
                                             "stopped the day's selections (the qualified candidates' when there were "
                                             "some). Null when nothing was saved.")


class NoPickDays(Contract):
    since: date = Field(description="The first product day counted: 30 days before today, never before the daily rule "
                                    "started (4 Oct 2026).")
    until: date = Field(description="The last product day counted: yesterday (today is on Home).")
    days: int
    with_picks: int
    without: int
    reasons: dict[str, int] = Field(description="Days without picks by reason.")
    measured: int = Field(description="Selections measured in evaluation over the days without picks.")
    stops: dict[str, int] = Field(description="Of those days, how many had each commonest stop (reconstructed).")
    items: list[NoPickDay] = Field(description="The days without picks, newest first.")


class LineValue(Contract):
    version: str = Field(description="The definition in force (`fbi.market.closing_value.VERSION`).")
    since: date = Field(description="Since when it is in force; a new definition is said, and the history recomputed.")
    n: int = Field(description="Published picks whose match started and that have a closing reference.")
    mean: Decimal | None = Field(description="The mean line value, a share (odds x p_close - 1); null below min_sample.")
    positive: Decimal | None = Field(description="The share of them above zero; null below min_sample.")
    minutes: int | None = Field(description="How long before kick-off the reference was taken, the median in minutes; null "
                                            "without picks.")


class CalibrationBin(Contract):
    low: Decimal = Field(description="The range of probabilities PrediGol said, a share (0.5 to 0.6...).")
    high: Decimal
    predicted: Decimal = Field(description="The mean probability said in that range.")
    observed: Decimal = Field(description="The share of those outcomes that happened.")
    n: int


class ForecastCalibration(Contract):
    market: Literal["1X2", "OU", "BTTS"]
    line: Decimal
    state: Literal["CALIBRATED", "UNCALIBRATED"] = Field(description="What most of the market's recent forecasts were: "
                                                                     "CALIBRATED (a validated calibrator applied) or "
                                                                     "the model's own number, «sin calibrar».")
    matches: int = Field(description="Finished matches of the window with a forecast made before kick-off and a result.")
    calibrated: int = Field(description="Of them, how many forecasts were calibrated.")
    selection: str | None = Field(description="The outcome the bins measure (Over, Yes); null for 1X2, where every outcome "
                                              "counts.")
    bins: list[CalibrationBin] = Field(description="Said against happened, only for a calibrated market with "
                                                   "min_calibration matches; empty otherwise. Ranges with fewer than "
                                                   "min_bin cases are left out (`omitted`).")
    omitted: int = Field(description="Cases in the ranges left out for being too small.")


class Evaluation(Contract):
    markets: int = Field(description="Kinds of bet PrediGol Intelligence measures against the market (edge-gate-v1).")
    pairs: int = Field(description="Kind of bet x model combinations measured.")
    passed_markets: int = Field(description="Kinds of bet with a combination that beat the market out of sample.")
    passed_pairs: int
    since: date | None = Field(description="The first verdict of that test.")
    qualified: int = Field(description="Forecasts of models that beat the market in their own test - the only ones that "
                                       "can be a pick - in the window of the days without picks.")


class Definition(Contract):
    key: Literal["roi", "sample", "no_pick_day", "line_value", "calibration", "evaluation"]
    version: str
    since: date


class Transparency(Contract):
    timezone: str = Field(description="The reader's time zone, the days of the periods are cut in.")
    min_sample: int = Field(description="Settled picks from which units, ROI and its margin are shown (25).")
    conclusive: int = Field(description="Settled picks from which the sample allows a conclusion (100).")
    min_calibration: int
    min_bin: int
    calibration_days: int = Field(description="The window of the forecast's calibration, in days.")
    periods: list[PeriodTally] = Field(description="7 days, 30 days and the whole history: fixed, never the best one.")
    days: NoPickDays
    markets: list[MarketTally] = Field(description="The whole history by kind of bet, most settled first; `other` last.")
    line_value: LineValue
    forecasts: list[ForecastCalibration] = Field(description="1X2, total goals at 2.5 and both teams to score.")
    evaluation: Evaluation
    definitions: list[Definition]
    data_as_of: datetime | None = Field(description="The newest settlement among the published picks counted.")
