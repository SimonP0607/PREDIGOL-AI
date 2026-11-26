"""Rest, congestion and the next match of each side, said as calculated context facts (plan RP-4.3, finding H18, ``calendar-facts-v1``).

``FBI_CALENDAR_FACTS`` (off by default): nothing is written until the switch is turned on with the audited kit. The facts are PRIVATE and enter no
probability: the plan's rule for this piece is that none of them is an argument of a forecast (their effect is still unproven: the registry of
factors holds them as descriptive, RP-4.5).

WHAT IS SAID. For each side of a match about to kick off, from the team's whole calendar (every competition the provider lists for it, followed or not:
``fbi.competitions.team_calendar``) as known at the moment asked:

* the days of rest since its previous match, and where and against whom it was played;
* how many matches it played in the 14 days before, and how many of them in a competition PrediGol does not follow;
* its next match after this one, how many days away, and whether it is within 4 days.

Facts, not readings: «descansó 3,0 días», never «llega cansado». A calendar that is not whole (never read, read more than 96 hours ago, a match of the last
fortnight still marked to-be-played after its kick-off) says so in the fact, and the numbers are then «a lo sumo» for rest and «al menos» for matches
(``TeamCalendar.state``); a team with no previous match in the 60 days before the match has no rest fact. A side with nothing to say produces no fact:
the absence is counted (``Counts``) and never filled in.

SECOND TRANCHE (RP-4.3, ``fbi.ai.minutes_facts``, the same switch): the minutes of the usual starters in the 14 days before the match and, when the team's own
history shows the pattern and the rest is short, a probable rotation. The rotation is the only fact of this switch that is not a confirmed fact: it carries
``certainty = "probable"`` and the schema gives it the category ``informacion_probable`` (``factor_schema.category_of``).

Reads the calendar through ``fbi.competitions.team_calendar`` and the matches in ``core.fixtures``; writes ``ai.evidence`` only through ``fbi.ai.evidence.store`` and only
when on. 0 requests.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import evidence, factor_schema, minutes_facts
from fbi.ai.stakes_facts import AHEAD, MATCHES_SQL, Match
from fbi.competitions import team_calendar as tc

SWITCH: Final = "FBI_CALENDAR_FACTS"
VERSION: Final = "calendar-facts-v1"
SOURCE_NAME: Final = "PrediGol · calendario del equipo (team-calendar-reader-1)"
CLOSE_NEXT: Final = timedelta(days=4)
"""«Next match within 4 days»: the plan's threshold for the fact of a short turnaround."""
MAX_CLAIM: Final = 560
TABLES: Final = ("core.fixtures", *tc.TABLES, *minutes_facts.TABLES, "ai.evidence")
RULE: Final = ("Hechos de calendario, no un juicio sobre el estado físico: días desde el último partido en cualquier competición, partidos en los 14 días "
               "anteriores y próximo partido, del calendario conocido en el momento de la lectura.")
WHY: Final[Mapping[str, str]] = {
    "never_fetched": "el calendario del equipo nunca se leyó",
    "stale": "el calendario del equipo se leyó hace más de 96 horas",
    "unconfirmed_match": "un partido de las dos últimas semanas sigue sin confirmarse",
}


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on (``1``, ``on``, ``true``, ``yes``): born off."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


@dataclass(frozen=True, slots=True)
class SideFact:
    """One side's schedule situation, as numbers and the sentence that says them."""

    match: Match
    team: int
    side: str
    claim: str
    calculation: Mapping[str, Any]
    kind: str = "schedule"
    claim_type: str = "SCHEDULE"
    story: str = "calendar"
    """The first word of the story key: each kind of fact of a side is its own story."""
    certainty: str | None = None
    """``probable`` for a regularity of the history, never an announced fact; None for a calculated fact."""


@dataclass(slots=True)
class Counts:
    matches: int = 0
    facts: int = 0
    created: int = 0
    whole: int = 0
    not_whole: int = 0
    no_previous: int = 0
    minutes: int = 0
    rotation: int = 0
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "matches": self.matches, "facts": self.facts, "created": self.created, "whole": self.whole,
                "not_whole": self.not_whole, "no_previous": self.no_previous, "minutes": self.minutes,
                "rotation": self.rotation, "errors": self.errors}


def _days(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def side_fact(cal: tc.TeamCalendar, match: Match, side: str, name: str) -> SideFact | None:
    """The schedule fact of one side, or None when the calendar shows no previous match (nothing is said by guessing)."""
    kickoff = match.kickoff
    team = match.home_id if side == "home" else match.away_id
    previous = cal.previous(kickoff)
    if previous is None:
        return None
    state = cal.state(kickoff)
    rest = cal.rest_days(kickoff)
    played = cal.played_within(kickoff, tc.FORTNIGHT)
    outside = sum(1 for m in played if not m.followed)
    ahead = cal.next_after(kickoff)
    gap = None if ahead is None else (ahead.kickoff_at - kickoff).total_seconds() / 86400
    close = ahead is not None and ahead.kickoff_at - kickoff <= CLOSE_NEXT
    exact = state.complete
    at_most, at_least = ("" if exact else "a lo sumo "), ("" if exact else "al menos ")

    where = "en casa" if previous.home else "fuera"
    parts = [f"{name}: {at_most}{_days(rest or 0.0)} días desde su último partido ({previous.competition}, {where}"
             + (f", contra {previous.opponent}" if previous.opponent else "") + ")"]
    parts.append(f"{at_least}{len(played)} partido{'' if len(played) == 1 else 's'} en los 14 días anteriores"
                 + (f", {outside} en competiciones que PrediGol no sigue" if outside else ""))
    if ahead is not None and gap is not None:
        parts.append(f"su siguiente partido ({ahead.competition}) es {'en' if gap >= 1 else 'a'} {_days(gap)} días"
                     + (", a 4 días o menos" if close else ""))
    claim = "; ".join(parts) + "."
    if not exact:
        claim += f" Calendario incompleto: {WHY.get(str(state.reason), str(state.reason))}."
    if len(claim) > MAX_CLAIM:
        claim = claim[: MAX_CLAIM - 1].rstrip() + "…"
    calculation = {
        "version": VERSION, "reader": tc.VERSION, "rule": RULE, "team": team, "side": side, "whole": exact, "reason": state.reason,
        "calendar_fetched_at": None if state.fetched_at is None else state.fetched_at.isoformat(),
        "rest_days": rest, "previous": {"kickoff": previous.kickoff_at.isoformat(), "competition": previous.competition, "home": previous.home,
                                        "followed": previous.followed},
        "played_14d": len(played), "outside_14d": outside,
        "next": None if ahead is None else {"kickoff": ahead.kickoff_at.isoformat(), "competition": ahead.competition,
                                            "gap_days": round(gap or 0.0, 1), "within_4_days": close}}
    return SideFact(match, team, side, claim, calculation)


def item_of(fact: SideFact, *, at: datetime) -> evidence.EvidenceIn:
    """The fact as the item the store takes: complete in the seven attributes, or ``store`` refuses it. Its date is the calendar's own read (the moment
    asked when the calendar was never read, which is said in the fact)."""
    fetched = fact.calculation.get("calendar_fetched_at")
    published = at if fetched is None else min(at, datetime.fromisoformat(str(fetched)))
    probable = fact.certainty is not None
    attributes: dict[str, Any] = {"calculation": VERSION if fact.story == "calendar" else minutes_facts.VERSION, **fact.calculation}
    if fact.certainty is not None:
        attributes["certainty"] = fact.certainty
    return evidence.EvidenceIn(
        fixture_id=fact.match.fixture_id, team_id=fact.team, kind=fact.kind, claim=fact.claim, origin="own_calc",
        source_name=SOURCE_NAME if fact.story == "calendar" else minutes_facts.SOURCE_NAME,
        retrieved_at=at, story_key=f"{fact.story}:{fact.match.fixture_id}:{fact.team}", assertion="info", published_at=published,
        confidence=0.6 if probable else 0.95, relevance=0.4 if probable else (0.6 if fact.calculation.get("whole", True) else 0.4),
        attributes=attributes, claim_type=fact.claim_type,
        subject_type="TEAM", subject_id=fact.team, fresh_until=fact.match.kickoff, side=fact.side, fact_schema=factor_schema.VERSION)


@dataclass(frozen=True, slots=True)
class Read:
    match: Match
    competition: str
    home: str
    away: str
    facts: list[SideFact]


def collect(conn: psycopg.Connection[Any], *, at: datetime, ahead: timedelta = AHEAD) -> list[Read]:
    """The facts of the matches that kick off within ``ahead`` of ``at``, as of ``at``. Reads only."""
    out: list[Read] = []
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(MATCHES_SQL, {"at": at, "until": at + ahead}).fetchall()
    for r in rows:
        match = Match(int(r["fixture_id"]), r["kickoff_at"], int(r["home_team_id"]), int(r["away_team_id"]))
        facts: list[SideFact] = []
        for side, team, name in (("home", match.home_id, r["home_name"]), ("away", match.away_id, r["away_name"])):
            cal = tc.load(conn, team_id=team, at=at, kickoff=match.kickoff)
            if (fact := side_fact(cal, match, side, str(name))) is not None:
                facts.append(fact)
            facts += [SideFact(match, team, side, d.claim, d.calculation, d.kind, d.claim_type, d.story, d.certainty)
                      for d in minutes_facts.facts_of(minutes_facts.load(conn, team_id=team, at=at, kickoff=match.kickoff), match.kickoff,
                                                      cal.rest_days(match.kickoff), str(name))]
        out.append(Read(match, str(r["competition"]), str(r["home_name"]), str(r["away_name"]), facts))
    return out


def run(conn: psycopg.Connection[Any], *, at: datetime, write: bool | None = None, ahead: timedelta = AHEAD) -> Counts:
    """The facts of the matches that kick off within ``ahead`` of ``at``. Nothing is written unless ``write`` (default: the switch is ``on``); a fact the
    store refuses is counted in ``errors`` and does not stop the others. The caller commits."""
    do_write = mode() == "on" if write is None else write
    counts = Counts()
    for read in collect(conn, at=at, ahead=ahead):
        counts.matches += 1
        counts.facts += len(read.facts)
        counts.no_previous += 2 - sum(1 for f in read.facts if f.story == "calendar")
        for fact in read.facts:
            if fact.story == "calendar":
                counts.whole += int(bool(fact.calculation["whole"]))
                counts.not_whole += int(not fact.calculation["whole"])
            counts.minutes += int(fact.story == "minutes")
            counts.rotation += int(fact.story == "rotation")
            if not do_write:
                continue
            try:
                with conn.transaction():
                    _, created = evidence.store(conn, item_of(fact, at=at), at=at)
            except (factor_schema.IncompleteFactError, psycopg.Error, ValueError) as exc:
                counts.errors.append(f"{read.match.fixture_id}:{fact.side}:{type(exc).__name__}")
                continue
            counts.created += int(created)
    return counts


__all__ = ["AHEAD", "CLOSE_NEXT", "SWITCH", "TABLES", "VERSION", "Counts", "Read", "SideFact", "collect", "item_of", "mode", "run", "side_fact"]
