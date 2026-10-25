"""The structured reading of a match (plan UX, A9): six sections of facts, each a stable code with its parameters and the
reference of where it comes from. The web writes them in the reader's language; no prose travels here."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

SectionKey = Literal["summary", "context", "data", "market", "risks", "conclusion"]


class ReadingFact(Contract):
    code: str = Field(description="What the fact says, as a stable name the web has a template for (e.g. ``form``, "
                                  "``stakes_pressure``, ``likely``).")
    params: dict[str, str | int | float | bool | list[str] | None] = Field(
        description="The values the template fills in: names, counts, probabilities as shares of one (0.523).")
    ref: str = Field(description="Where it comes from: ``packet:<block>`` (the match packet PrediGol Intelligence stored), "
                                 "``forecast:<market>`` (PrediGol's forecast) - every figure has one.")


class ReadingSection(Contract):
    key: SectionKey
    facts: list[ReadingFact]


class MatchReading(Contract):
    fixture_id: int
    version: str = Field(description="The rules that chose the facts: reading-v1.")
    complete: bool = Field(description="False: PrediGol has not gathered this match's context yet; the reading has only the "
                                       "forecast and says so in its risks.")
    data_at: datetime | None = Field(description="The moment of the data the context, the figures and the market come from.")
    forecast_at: datetime | None = Field(description="When PrediGol said the forecast the summary and the conclusion read.")
    sections: list[ReadingSection] = Field(description="In order: summary, context, data, market, risks, conclusion - a "
                                                       "section without facts is left out (risks never is).")
