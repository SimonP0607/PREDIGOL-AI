"""Cuts of the statistics by context, and a player's rates (plan RP-6.3, finding H32): ``stats-cuts-v1``.

The documents of the nightly pass already hold, for every team, a body per scope (the season and the last 5, 10 and 20) and per context
(``all``, ``home``, ``away``), the goals of each half, and for every player his minutes, starts and rates per 90. This module reads those
SAME documents (through ``fbi.stats.reading``: nothing is recomputed) and arranges them as cuts, each with its own sample:

* **venue**: the team at home and the team away, each a cut of its own document with its own sample and its own trend facts
  (``fbi.stats.facts``, so the league's reference and the interval travel with them);
* **halves**: the goals for and against of the first and the second half per match, over the matches that have both halves;
* **player**: minutes, appearances, starts, the share of appearances he started, and every rate per 90 with the minutes behind it.

A cut under the minimum sample is marked ``insuficiente`` and keeps its figures (a reader can see how little there is); it is never filled in
and never dropped silently. A player's cut is DESCRIPTIVE: it carries no forecast, and nothing here is public. The cut by the strength of
the rival (thirds) is not in the documents: it needs the rival's strength at the date of each match, which a document does not store, and it
is reported as ``not_in_documents`` rather than invented (the piece that computes it is named in the registry).

It writes nothing and decides nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import psycopg

from fbi.stats import facts, reading, team
from fbi.stats.reading import Document

VERSION: Final = "stats-cuts-v1"

VENUES: Final = ("home", "away")
MIN_MATCHES: Final = team.MIN_MATCHES
"""The sample a team cut is read on: the one the statistics pages use. A halves cut counts the matches that have both halves."""
MIN_MINUTES: Final = 450
"""Five full matches: under it a player's rates per 90 are marked ``insuficiente`` (the pages' own ``min_nineties`` is 5 nineties for a percentile)."""
NOT_IN_DOCUMENTS: Final = "not_in_documents"
INSUFFICIENT: Final = "insuficiente"
OK: Final = "ok"


@dataclass(frozen=True, slots=True)
class Cut:
    """One cut: what it is, how much it stands on, whether that is enough, and its figures (a plain mapping, citable)."""

    name: str
    sample: int
    state: str
    document_id: str | None = None
    computed_at: datetime | None = None
    values: Mapping[str, float] = field(default_factory=dict)
    reason: str | None = None
    facts: tuple[facts.Fact, ...] = ()


@dataclass(frozen=True, slots=True)
class TeamCuts:
    scope: str
    home: Cut
    away: Cut
    halves: Cut
    rival_strength: Cut


@dataclass(frozen=True, slots=True)
class PlayerRates:
    player_id: int
    cut: Cut
    appearances: int = 0
    starts: int = 0
    minutes: int = 0
    start_share: float | None = None
    rates: Mapping[str, float] = field(default_factory=dict)
    forecast: None = None
    """Descriptive only: a player's cut never carries a forecast."""


def state_of(sample: int, minimum: int) -> str:
    return OK if sample >= minimum else INSUFFICIENT


def venue_cut(doc: Document, *, min_sample: int = MIN_MATCHES) -> Cut:
    """The team at home (or away) from the document of that context: its sample is the document's, its facts are the document's trends."""
    if doc.status != "ok":
        return Cut(doc.context, 0, "sin_documento", doc.document_id, doc.computed_at, reason=doc.status)
    found, _dropped = facts.facts_of(doc, min_sample=min_sample)
    return Cut(doc.context, doc.sample, state_of(doc.sample, min_sample), doc.document_id, doc.computed_at,
               {r.key: r.value for r in doc.readings if r.value is not None}, facts=tuple(found))


def halves_cut(doc: Document, *, min_sample: int = MIN_MATCHES) -> Cut:
    """The goals of each half per match, over the matches that have both halves. The block is the document's ``halves``."""
    block = doc.body.get("halves") if doc.status == "ok" else None
    if not isinstance(block, Mapping) or "missing_reason" in block or not isinstance(block.get("matches_with_data"), int):
        why = block.get("missing_reason") if isinstance(block, Mapping) else None
        return Cut("halves", 0, "sin_datos", doc.document_id, doc.computed_at, reason=str(why) if why else doc.status)
    n = int(block["matches_with_data"])
    keys = ("goals_for_1h", "goals_against_1h", "goals_for_2h", "goals_against_2h")
    values = {k: float(block[k]) for k in keys if isinstance(block.get(k), (int, float))}
    return Cut("halves", n, state_of(n, min_sample), doc.document_id, doc.computed_at, values)


def rival_strength_cut() -> Cut:
    """Thirds of the rival's strength: the documents do not carry it, so the cut says so instead of guessing."""
    return Cut("rival_strength", 0, "sin_datos", reason=NOT_IN_DOCUMENTS)


def team_cuts(docs: Mapping[str, Document], *, scope: str = "season", min_sample: int = MIN_MATCHES) -> TeamCuts:
    """The cuts of a team from its documents by context (``home``, ``away``); the halves come from the document of the home cut's twin ``all``."""
    anywhere = docs.get("all") or next(iter(docs.values()), None)
    missing = Document("no_document", "team", 0, 0, scope, "all")
    return TeamCuts(scope, venue_cut(docs.get("home", missing), min_sample=min_sample),
                    venue_cut(docs.get("away", missing), min_sample=min_sample),
                    halves_cut(anywhere or missing, min_sample=min_sample), rival_strength_cut())


def read_team_cuts(conn: psycopg.Connection[Any], *, team_id: int, competition_season_id: int, scope: str = "season",
                   as_of: datetime | None = None, min_sample: int = MIN_MATCHES) -> TeamCuts:
    """Read the team's three documents (``all``, ``home``, ``away``) at the cut-off and arrange the cuts. Read only: three indexed SELECTs."""
    docs = {c: reading.read(conn, kind="team", entity_id=team_id, competition_season_id=competition_season_id, scope=scope, context=c, as_of=as_of)
            for c in ("all", *VENUES)}
    return team_cuts(docs, scope=scope, min_sample=min_sample)


def player_rates(doc: Document, *, min_minutes: int = MIN_MINUTES) -> PlayerRates:
    """A player's minutes, starts and rates per 90 from his document. Under ``min_minutes`` the cut is marked ``insuficiente``; no forecast."""
    pid = doc.entity_id
    if doc.status != "ok":
        return PlayerRates(pid, Cut("player", 0, "sin_documento", doc.document_id, doc.computed_at, reason=doc.status))
    body = doc.body
    appearances = int(body["appearances"]) if isinstance(body.get("appearances"), int) else 0
    starts = int(body["starts"]) if isinstance(body.get("starts"), int) else 0
    minutes = int(body["minutes"]) if isinstance(body.get("minutes"), int) else 0
    rates = {r.key: r.value for r in doc.readings if r.unit == "por_90" and r.value is not None}
    share = round(starts / appearances, 4) if appearances > 0 else None
    cut = Cut("player", minutes, state_of(minutes, min_minutes), doc.document_id, doc.computed_at, rates,
              None if minutes >= min_minutes else "minutos_insuficientes")
    return PlayerRates(pid, cut, appearances, starts, minutes, share, rates)


def read_player_rates(conn: psycopg.Connection[Any], *, player_id: int, competition_season_id: int, scope: str = "season",
                      as_of: datetime | None = None, min_minutes: int = MIN_MINUTES) -> PlayerRates:
    doc = reading.read(conn, kind="player", entity_id=player_id, competition_season_id=competition_season_id, scope=scope, context="all", as_of=as_of)
    return player_rates(doc, min_minutes=min_minutes)


def available(cuts: Sequence[Cut]) -> int:
    """How many cuts a match can use: the ones with enough sample (the indicator «cuts available per match»)."""
    return sum(1 for c in cuts if c.state == OK)


__all__ = ["INSUFFICIENT", "MIN_MATCHES", "MIN_MINUTES", "NOT_IN_DOCUMENTS", "OK", "VERSION", "Cut", "PlayerRates", "TeamCuts", "available",
           "halves_cut", "player_rates", "read_player_rates", "read_team_cuts", "rival_strength_cut", "state_of", "team_cuts", "venue_cut"]
