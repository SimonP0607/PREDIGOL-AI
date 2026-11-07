"""The structured reading of a match (plan UX, A9): six sections of facts, each a stable code with its parameters and the
reference of where it comes from. The web writes them in the reader's language; no prose travels here - but for the narrative
(plan UX, A11; its v2, UX-025, is the chronicle), written in Spanish and English by PrediGol's AI and checked sentence by
sentence against the match's facts and its news before it may be shown."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

SectionKey = Literal["summary", "context", "data", "market", "risks", "conclusion"]
NarrativeKey = Literal["summary", "home", "away", "h2h", "risks"]
"""The sections of the chronicle (narrative v2): the lead, a paragraph for each side, the head-to-head and the risks."""
ReadingSectionKey = Literal["summary", "context", "data", "market", "risks", "conclusion", "key_points", "value", "factors"]


class ReadingFact(Contract):
    code: str = Field(description="What the fact says, as a stable name the web has a template for (e.g. ``form``, "
                                  "``stakes_pressure``, ``likely``).")
    params: dict[str, str | int | float | bool | list[str] | None] = Field(
        description="The values the template fills in: names, counts, probabilities as shares of one (0.523).")
    ref: str = Field(description="Where it comes from: ``packet:<block>`` (the match packet PrediGol Intelligence stored), "
                                 "``forecast:<market>`` (PrediGol's forecast) or ``pick:<id>`` (a pick PrediGol published, "
                                 "with the numbers it was frozen with) - every figure has one.")


class ReadingSection(Contract):
    key: ReadingSectionKey
    facts: list[ReadingFact]


class NarrativeSentence(Contract):
    text: str = Field(description="One sentence in the section's language.")
    refs: list[str] = Field(description="What it rests on: ``P:<block>`` - a fact of this reading (``P:form.home``, "
                                        "``P:forecast.1X2``) - or ``E:<id>``, a news item of the match. Never empty.")


class NarrativeSection(Contract):
    key: NarrativeKey
    sentences: list[NarrativeSentence] = Field(description="The paragraph: its sentences in order, each with what it rests on.")


class NarrativeSource(Contract):
    name: str = Field(description="The outlet of a piece of news the chronicle tells, as PrediGol recorded it.")


class ReadingNarrative(Contract):
    version: str = Field(description="The prompt and the checks that wrote it: user-narrative-v3 (the chronicle).")
    written_at: datetime = Field(description="When PrediGol's AI wrote it.")
    data_at: datetime = Field(description="The moment of the data it was written from: «Escrito con datos de las 12:30».")
    es: list[NarrativeSection] = Field(description="The sections in Spanish, in order: summary, home, away, h2h, risks - each only "
                                                   "when the match has something to say there.")
    en: list[NarrativeSection] = Field(description="The same sections in English: the same sentences, references and numbers.")
    sources: list[NarrativeSource] = Field(default_factory=list, description=(
        "The outlets of the news the chronicle tells (none when it tells none): «Fuentes» under the text."))


class MatchReading(Contract):
    fixture_id: int
    version: str = Field(description="The rules that chose the facts: reading-v1.")
    complete: bool = Field(description="False: PrediGol has not gathered this match's context yet; the reading has only the "
                                       "forecast and says so in its risks.")
    data_at: datetime | None = Field(description="The moment of the data the context, the figures and the market come from.")
    forecast_at: datetime | None = Field(description="When PrediGol said the forecast the summary and the conclusion read.")
    sections: list[ReadingSection] = Field(description=(
        "In order: summary, context, data, market, risks, conclusion - a section without facts is left out (risks never "
        "is) - and then the three derived from them (plan de cierre UX, 2.1), each only when it has facts: key_points (three "
        "to five, never padded), value (why a pick PrediGol published for this match has value: only with such a pick that a "
        "reader may see) and factors (what stands out). The narrative never reads them."))
    narrative: ReadingNarrative | None = Field(default=None, description=(
        "The narrative (A11): the same reading written as prose, Spanish and English, by PrediGol's AI from these facts and the "
        "match's verified news, and shown only once every sentence passed the server's checks. Null while there is none for "
        "THIS reading (written from another packet or other facts), while the owner keeps it off (FBI_USER_NARRATIVE) or "
        "when it failed its checks - the web then shows the facts above."))
