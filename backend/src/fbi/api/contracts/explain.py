"""«Explícame» (plan UX, B9): the frequent questions about a match, a pick and the reader's parlay, answered from what PrediGol
already keeps - its structured reading (A9), its forecast, the state of a pick (B3) and the parlay's own check - with no model,
no AI and no web search. No prose travels here: every line is a stable code the web words in the reader's language
(``explain.say.<code>``) or a fact of the match's reading, which the web writes with the reading's own template. An answer
that lacks the data it needs says so («no tengo ese dato») instead of guessing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.reading import ReadingFact
from fbi.api.contracts.records import LegInBody

ExplainEntity = Literal["match", "pick", "parlay"]
ExplainIntent = Literal["no_pick", "forecast", "risks", "caution", "probability"]
"""no_pick «¿Por qué no hay pick?» and forecast «¿Qué significa este pronóstico?» of a match; risks «¿Qué puede salir mal?» of a
match or a pick; caution «¿Por qué cautela?» of a pick; probability «¿Por qué baja la probabilidad de mi parlay?» of the
reader's parlay."""
ExplainLink = Literal["transparency", "why_pick", "glossary"]
Param = str | int | float | bool | list[str] | list[float] | None


class ExplainLine(Contract):
    say: str | None = Field(default=None, description="A sentence of «Explícame» as a stable code the web words "
                                                      "(``explain.say.<code>``); null when the line is a fact.")
    params: dict[str, Param] = Field(default_factory=dict, description="The values its template fills in: names, "
                                                                        "counts, probabilities as shares of one.")
    fact: ReadingFact | None = Field(default=None, description="Or a fact of the match's structured reading (A9), "
                                                               "written with the reading's own template.")


class Explanation(Contract):
    version: str = Field(description="The rules that wrote the answer: explain-v1.")
    entity: ExplainEntity
    item_id: int | None = Field(description="The match or the pick; null for the parlay being built (the slip).")
    intent: ExplainIntent
    answered: bool = Field(description="False: PrediGol does not have what this question needs - the lines say what is "
                                       "missing («no tengo ese dato»), never a guess.")
    lines: list[ExplainLine]
    terms: list[str] = Field(description="Glossary terms worth a tap, by their key in the web's glossary.")
    links: list[ExplainLink] = Field(description="Where to read more: «Cómo le va a PrediGol», the pick's «¿Por qué este "
                                                 "pick?», the glossary.")


class SlipIn(BaseModel):
    """The parlay being built: its legs as the slip holds them (the same as POST /me/parlays/validate)."""

    model_config = ConfigDict(extra="forbid")
    legs: list[LegInBody] = Field(min_length=1, max_length=12)
