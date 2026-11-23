"""The owner's private evaluation board (plan PM, PM-12-01 and PM-12-06; IA-153): the weekly board (PrediGol's forecast, the market and
the provider on the same matches, Brier split into reliability and resolution, paired differences with intervals) and the newest report
by competition and coverage level. Read only; private (``require_admin``) and 404 while ``FBI_EVALUATION_BOARD`` is off."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract


class Interval(Contract):
    value: float | None
    low: float | None = Field(description="95 % interval, whole Bogotá days resampled; null with one day.")
    high: float | None


class SourceScore(Contract):
    source: Literal["modelo", "mercado", "proveedor"]
    n: int = Field(description="Matches scored: the ones every source of the market shares.")
    days: int
    log_loss: Interval
    brier: Interval
    reliability: Interval = Field(description="Murphy: how far the stated probabilities are from the frequencies seen (lower is better).")
    resolution: Interval = Field(description="Murphy: how far the frequencies of each bin are from the overall one (higher is better).")
    uncertainty: float = Field(description="Murphy: that of the outcomes themselves.")
    residual: float = Field(description="Brier - (reliability - resolution + uncertainty): what ten bins cannot see.")


class PairedDifference(Contract):
    a: str
    b: str
    metric: Literal["log_loss", "brier"]
    n: int
    value: float | None = Field(description="Mean of a minus b per match: negative, a scored better.")
    low: float | None
    high: float | None
    verdict: Literal["modelo_mejor", "modelo_peor", "indistinguible", "insuficiente"]


class Window(Contract):
    from_day: date = Field(alias="from")
    to_day: date = Field(alias="to")
    matches: int = Field(description="Finished matches with the model's forecast.")
    with_each: dict[str, int] = Field(description="Of those, how many each source has a whole set for.")
    common: int
    sources: list[SourceScore]
    pairs: list[PairedDifference]


class MarketBoard(Contract):
    market: Literal["1X2", "OU", "BTTS"]
    line: float
    week: Window
    cumulative: Window


class WeeklyBoard(Contract):
    report_id: int
    version: str
    period_from: date
    period_to: date
    cumulative_from: date
    computed_at: datetime
    markets: list[MarketBoard]


class SegmentCount(Contract):
    source: str
    kind: str
    verdict: Literal["apta", "sin_habilidad", "insuficiente"]
    segments: int


class CompetitionVerdict(Contract):
    competition_id: int
    name: str | None
    model: str
    market: str
    n: int
    days: int
    log_loss: float
    log_loss_low: float | None
    log_loss_high: float | None
    skill: float = Field(description="Log loss minus that of the competition's own frequencies: negative is better.")
    skill_low: float | None
    skill_high: float | None
    verdict: Literal["apta", "sin_habilidad", "insuficiente"]


class SegmentsSummary(Contract):
    report_id: int
    version: str
    period_from: date
    period_to: date
    computed_at: datetime
    needed: int = Field(description="Matches a competition needs before a verdict is given (AD-K02's sample).")
    reproduced: bool = Field(description="The segments add back to the global figures.")
    counts: list[SegmentCount]
    competitions: list[CompetitionVerdict] = Field(description="What a reader is shown (forecast-v1), by competition, most matches first.")


class EvaluationBoard(Contract):
    weekly: WeeklyBoard | None = Field(description="Null until the first weekly board is computed.")
    segments: SegmentsSummary | None = Field(description="Null until the first report by competition is computed.")
    notice_es: str
