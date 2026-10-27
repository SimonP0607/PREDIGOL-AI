"""Mis picks completo (plan UX, B5, section 30): the totals and the breakdown of the reader's own saved picks under the filter
they chose - always with their sample - and the line value of their prices. Everything is the reader's own: nothing here
reads another reader, a pick of PrediGol that the reader did not save, or anything of evaluation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.product import CompetitionBadge

Result = Literal["pending", "won", "lost", "push", "void"]
Origin = Literal["predigol", "mine"]
Band = Literal["lt1.5", "1.5-2", "2-3", "3-5", "5+"]
Sample = Literal["counts_only", "inconclusive", "conclusive"]


class PicksTally(Contract):
    """Saved picks counted as Mis picks counts them everywhere (``fbi.userdata.records``, and «Cómo le va a PrediGol» feeds the
    same rows to the same rule): a flat stake of one unit per settled pick, a void returns it, a push wins nothing. Below
    min_sample settled picks only the counts are given (plan UX, section 30)."""

    total: int = Field(description="Saved picks under the filter.")
    pending: int = Field(description="Not settled yet.")
    won: int
    lost: int
    half_won: int = Field(description="Half won (an Asian line split between a win and a push).")
    half_lost: int
    push: int = Field(description="Returned: the stake back, no profit.")
    void: int = Field(description="Voided: not a bet (a match not played, a market cancelled).")
    settled: int = Field(description="Settled with a stake - won, lost, the halves and the pushes: the n of the sample.")
    units: Decimal | None = Field(description="The profit in units, from min_sample settled picks; null below (counts only).")
    roi: Decimal | None = Field(description="Units over settled stakes, a share; null below min_sample.")
    margin: Decimal | None = Field(description="Plus or minus one standard error of the ROI, a share: 1 / sqrt(settled) (0.20 "
                                               "with 25, 0.10 with 100); null below min_sample.")
    hit_rate: Decimal | None = Field(description="Won (a half win included) over won and lost, a share; null below min_sample.")
    sample: Sample = Field(description="counts_only below min_sample settled picks; inconclusive below `conclusive` (the page "
                                       "says the sample does not allow a conclusion yet); conclusive from there.")


class MarketRow(PicksTally):
    market: str = Field(description="The kind of bet: 1X2, OU, BTTS, AH or DC.")


class CompetitionRow(PicksTally):
    competition: CompetitionBadge


class BandRow(PicksTally):
    band: Band = Field(description="The odds range of the price the reader counts - their own when they gave one: from "
                                   "(included) to (excluded): <1.5, 1.5-2, 2-3, 3-5, 5 and more.")


class MyLineValue(Contract):
    """The reader's prices against the close (``clv-v1``, ``fbi.market.closing_value``): the price they count - their own when
    they gave one - at the de-vigged (Shin) consensus of the last capture before kick-off, ``odds x p_close - 1``."""

    version: str = Field(description="The definition in force (`fbi.market.closing_value.VERSION`).")
    since: date = Field(description="Since when it is in force.")
    n: int = Field(description="Saved picks under the filter whose match started, with a price and a closing reference.")
    mean: Decimal | None = Field(description="The mean line value, a share; null below min_sample.")
    positive: Decimal | None = Field(description="The share of them above zero; null below min_sample.")
    minutes: int | None = Field(description="How long before kick-off the reference was taken, the median in minutes; null "
                                            "without any.")


class AppliedFilter(Contract):
    result: Result | None = None
    market: str | None = None
    competition: int | None = None
    origin: Origin | None = Field(default=None, description="predigol: a pick of PrediGol the reader saved; mine: a "
                                                            "selection of their own, from the market.")
    band: Band | None = None
    since: date | None = Field(default=None, description="The first day of the matches, in the reader's time zone.")
    until: date | None = Field(default=None, description="The last day of the matches, in the reader's time zone.")
    search: str | None = Field(default=None, description="Found in the teams' or the league's names, without accents.")
    active: int = Field(description="How many parts of the filter are set.")


class FilterOptions(Contract):
    """What the reader's own saved picks hold - the choices of the filter, never a value another reader has."""

    markets: list[str] = Field(description="The kinds of bet of the reader's saved picks, in the order of the catalogue.")
    competitions: list[CompetitionBadge] = Field(description="The leagues of the reader's saved picks, by name.")


class PicksDefinition(Contract):
    key: Literal["roi", "sample", "line_value"]
    version: str
    since: date


class PicksSummary(Contract):
    timezone: str = Field(description="The reader's time zone: the days of the filter are cut in it.")
    min_sample: int = Field(description="Settled picks from which units, ROI, hit rate and margin are shown (25).")
    conclusive: int = Field(description="Settled picks from which the sample allows a conclusion (100).")
    filter: AppliedFilter
    tally: PicksTally = Field(description="Every saved pick under the filter.")
    markets: list[MarketRow] = Field(description="By kind of bet, most saved first.")
    competitions: list[CompetitionRow] = Field(description="By league, most saved first.")
    bands: list[BandRow] = Field(description="By odds range, in the order of the ranges; a range with no pick is left out.")
    line_value: MyLineValue
    options: FilterOptions
    definitions: list[PicksDefinition] = Field(description="What each figure means and since when.")
