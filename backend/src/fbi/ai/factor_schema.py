"""The one schema of a context fact (plan RP-4.1, finding H16, ``context-fact-v1``). Pure: nothing here reads a database, a clock or a setting.

Every fact about a match from outside the numbers carries SEVEN attributes and belongs to ONE of FIVE categories (plan section 9):

    source          who says it                      ``source_name`` (and ``source_url`` when it is a web page)
    source date     when the source said it          ``published_at`` (the day of the calculation for a calculated fact)
    entity          who or what it is about          ``subject_type`` + ``subject_id`` (a match, a team, a player, a referee, a competition)
    state           how far it is confirmed          ``status`` (CONFIRMED, PROBABLE, RUMOR, CONTRADICTORY, OUTDATED): the server decides it
    validity        until when it holds              ``fresh_until``
    evidence        the quote or the calculation     ``claim`` with its ``source_url`` / ``payload_hash``, or the calculation in ``attributes``
    relation        whom it affects and how          ``side``: the home side, the away side, both or the match as a whole

The categories (``CATEGORIES``) are the plan's: a CONFIRMED FACT (the provider, the official line-up, the club, the competition or our own
calculation), PROBABLE INFORMATION (a reliable outlet with no official confirmation: «según [medio]»), a RUMOUR (a source with no tier or an
aggregator), a TACTICAL INTERPRETATION (an analyst's reading of facts: only the text can write it, in its own section, with «Interpretación:» in
front) and a HYPOTHESIS (an unproven relation between a factor and the result: only the registry of factors, never as an argument). Only the first
three can be given to an item of evidence; ``category_of`` gives them by CODE from what the server stored, and a model never assigns one. The
category is DERIVED, not stored: the state of an item changes as it is corroborated or goes stale, and the content of evidence never changes.

WHAT IS NEW AND WHAT IS NOT. A fact written under this schema (``fact_schema = 'context-fact-v1'``) is complete or it is refused (``missing``): no
source, no date, no entity, no validity, no side, a web claim without its address. The facts written before stay as they are (``fact_schema`` is
NULL, nothing is rewritten) and are counted apart by ``fbi.ai.factor_counts``. The kinds the plan adds (``NEW_KINDS``: what is at stake,
rotation, a statement, the referee, the formation, the competition's format) and the origin «own calculation» (``own_calc``) exist only under it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

VERSION: Final = "context-fact-v1"

Category = Literal["hecho_confirmado", "informacion_probable", "rumor", "interpretacion_tactica", "hipotesis"]
CATEGORIES: Final[tuple[Category, ...]] = ("hecho_confirmado", "informacion_probable", "rumor", "interpretacion_tactica", "hipotesis")
EVIDENCE_CATEGORIES: Final[tuple[Category, ...]] = ("hecho_confirmado", "informacion_probable", "rumor")
"""The ones an item of evidence can be: the last two are written by the text and by the registry of factors, never given to evidence."""

SIDES: Final = ("home", "away", "both", "match")
"""Whom a fact affects: the home side, the away side, both of them, or the match as a whole (the referee, the weather, the format)."""

OLD_KINDS: Final = ("injury", "suspension", "doubtful", "lineup", "coach", "news", "transfer", "motivation", "weather", "travel", "schedule", "other")
NEW_KINDS: Final = ("stakes", "rotation", "statement", "referee", "formation", "format")
KINDS: Final = (*OLD_KINDS, *NEW_KINDS)
OLD_ORIGINS: Final = ("provider", "web", "owner")
ORIGINS: Final = (*OLD_ORIGINS, "own_calc")

ATTRIBUTES: Final = ("source", "source_date", "entity", "state", "validity", "evidence", "relation")
"""The seven attributes, in the plan's order."""

OFFICIAL_ORIGINS: Final = frozenset({"provider", "owner", "own_calc"})


@dataclass(frozen=True, slots=True)
class FactView:
    """What a context fact says in the seven attributes, as the schema reads it from a stored or a new item."""

    origin: str
    kind: str
    status: str | None
    source_name: str | None
    source_url: str | None
    published_at: datetime | None
    subject_type: str | None
    subject_id: int | None
    fresh_until: datetime | None
    claim: str | None
    payload_hash: str | None
    attributes: Mapping[str, Any]
    side: str | None
    fact_schema: str | None = None


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def missing(fact: FactView) -> list[str]:
    """The attributes of the seven the fact does not have (empty: complete). The state is the server's and always exists, so it is never missing."""
    out: list[str] = []
    if _blank(fact.source_name) or (fact.origin == "web" and _blank(fact.source_url)):
        out.append("source")
    if fact.published_at is None:
        out.append("source_date")
    if fact.subject_type is None or fact.subject_id is None:
        out.append("entity")
    if fact.fresh_until is None:
        out.append("validity")
    no_calculation = fact.origin == "own_calc" and not fact.attributes.get("calculation")
    no_address = fact.origin == "web" and _blank(fact.source_url)
    if _blank(fact.claim) or no_calculation or no_address:
        out.append("evidence")
    if fact.side not in SIDES:
        out.append("relation")
    return out


class IncompleteFactError(ValueError):
    """A fact written under ``context-fact-v1`` that lacks some of the seven attributes: it is refused, never completed by guessing."""

    def __init__(self, absent: list[str]) -> None:
        super().__init__("a context fact needs all seven attributes; missing: " + ", ".join(absent))
        self.absent = absent


def require(fact: FactView) -> None:
    """Refuse a fact that is not complete (the entry check of everything written under the schema)."""
    absent = missing(fact)
    if absent:
        raise IncompleteFactError(absent)


def category_of(status: str | None, origin: str, tier: str | None = None) -> Category | None:
    """The category of an item of evidence by CODE, from what the server stored (the table of correspondence of RP-4.1).

    ===============================================================  =====================
    our own calculation, the owner's note                             hecho_confirmado
    the server's status CONFIRMED (an official source, the           hecho_confirmado
    provider's confirmed line-up, two independent outlets)
    PROBABLE (one outlet or journalist, the provider's report)        informacion_probable
    RUMOR (an aggregator, a social post, an unknown site)             rumor
    CONTRADICTORY, OUTDATED                                           None: no category,
                                                                      so neither argued nor shown as a fact
    ===============================================================  =====================

    A source with no tier or an aggregator never rises above a rumour here: the status ladder already holds it there. ``tier`` is read only to say
    so: a PROBABLE item of an aggregator or of an unknown source is a rumour.
    """
    if origin in ("own_calc", "owner"):
        return "hecho_confirmado"
    if status == "CONFIRMED":
        return "hecho_confirmado"
    if status == "PROBABLE":
        return "rumor" if tier in ("aggregator", "social", "unknown") else "informacion_probable"
    if status == "RUMOR":
        return "rumor"
    return None


LEVEL_CATEGORY: Final[dict[str, Category]] = {"oficial": "hecho_confirmado", "dos_origenes": "hecho_confirmado", "declaracion": "informacion_probable",
                                              "un_medio": "informacion_probable", "rumor": "rumor"}
"""The same table read from the level of confirmation C-07 shows (``fbi.api.contracts.intelligence.vocab.ConfirmationLevel``)."""


def category_of_level(level: str | None) -> Category | None:
    return None if level is None else LEVEL_CATEGORY.get(level)


__all__ = ["ATTRIBUTES", "CATEGORIES", "EVIDENCE_CATEGORIES", "KINDS", "LEVEL_CATEGORY", "NEW_KINDS", "ORIGINS", "SIDES", "VERSION", "Category",
           "FactView", "IncompleteFactError", "category_of", "category_of_level", "missing", "require"]
