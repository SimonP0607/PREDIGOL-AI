"""The coach, the usual formation and the referee of a match, said as calculated context facts (plan RP-4.4, first tranche, finding H19, ``people-facts-v1``).

``FBI_PEOPLE_FACTS`` (off by default): nothing is written until the switch is turned on with the audited kit. The facts are PRIVATE and enter no probability: the
registry of factors holds them as descriptive (``fbi.intel.factor_block``), so no sentence and no decision may rest on them.

WHAT IS SAID, for a match about to kick off, from what the database already knows as of the moment asked:

* COACH (each side): who sits on the bench according to the newest match sheet (``fbi.people.current_coach``), since which match he has done so and how many days
  that is before this match. «Since» is the first match of his run in the window the rule reads (a bit over a year), so a run that fills the window is said
  «al menos»: the day the coach changed is never invented. A team with no sheet naming a coach has no fact.
* FORMATION (each side): the formation the team has used most in its last ``WINDOW`` match sheets that name one, with how many of them, and how many sheets
  named none. Fewer than ``MIN_SHEETS`` sheets with a formation: no fact (a count of two says nothing about habit).
* REFEREE (the match): the referee the provider had named by this moment, as the person it identified or as the text it wrote, and when it was seen. A match
  with nobody named has no fact, and the absence is counted (the audit found the referee known before kick-off in 54 % of the matches; the plan measures whether
  asking later raises it, which is not decided here).

NOT HERE (RP-4.4, next tranches): the single state of each player (available, doubtful, out, suspended, called up) with the highest-level source, «one card from
suspension» where the regulation is coded, and the test that asks for the referee closer to kick-off.

Facts, never readings: «lleva 41 días», not «le ha cambiado el equipo». Reads the coach through ``fbi.people.current_coach_store``, the referee through
``fbi.people.officials`` and the sheets in ``core``; writes ``ai.evidence`` only through ``fbi.ai.evidence.store`` and only when on. 0 requests.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import evidence, factor_schema
from fbi.ai.stakes_facts import AHEAD, MATCHES_SQL, Match
from fbi.people import current_coach, current_coach_store, officials

SWITCH: Final = "FBI_PEOPLE_FACTS"
VERSION: Final = "people-facts-v1"
SOURCE_NAME: Final = "PrediGol · planillas y árbitro del proveedor (people-facts-v1)"
WINDOW: Final = 10
"""The sheets of a team that count for its usual formation."""
MIN_SHEETS: Final = 4
"""Sheets with a formation that a habit needs."""
MAX_CLAIM: Final = 420
TABLES: Final = ("core.fixtures", "core.fixture_lineups", "core.coach_careers", "core.fixture_officials", "ai.evidence")
RULE: Final = "Hechos de las planillas y del proveedor, no un juicio: quién está en el banquillo y desde cuándo, la formación más usada y el árbitro nombrado."

FORMATIONS_SQL: Final = """
SELECT f.kickoff_at, l.formation
  FROM core.fixtures f
  JOIN core.fixture_lineups l ON l.fixture_id = f.id AND l.team_side = CASE WHEN f.home_team_id = %(team)s THEN 'home' ELSE 'away' END
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
   AND f.kickoff_at < %(kickoff)s AND f.kickoff_at <= %(at)s AND f.status_group = 'finished'
 ORDER BY f.kickoff_at DESC
 LIMIT %(window)s
"""
"""The newest finished sheets of a team before the match (a sheet whose formation is null counts as a sheet with none)."""


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on (``1``, ``on``, ``true``, ``yes``): born off."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


@dataclass(frozen=True, slots=True)
class PeopleFact:
    """One fact: its kind, the match, the side, the sentence that says it and the calculation behind it."""

    match: Match
    kind: str
    side: str
    team: int | None
    claim: str
    calculation: Mapping[str, Any]
    published_at: datetime


@dataclass(slots=True)
class Counts:
    matches: int = 0
    facts: int = 0
    created: int = 0
    no_coach: int = 0
    no_formation: int = 0
    no_referee: int = 0
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "matches": self.matches, "facts": self.facts, "created": self.created, "no_coach": self.no_coach,
                "no_formation": self.no_formation, "no_referee": self.no_referee, "errors": self.errors}


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CLAIM else text[: MAX_CLAIM - 1].rstrip() + "…"


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


# ── pure facts ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def coach_fact(coach: Mapping[str, Any], match: Match, side: str, name: str) -> PeopleFact | None:
    """The coach of a side from the rule's answer (``CurrentCoach.as_dict``), or None when it has none or names nobody."""
    who = coach.get("coach_name")
    since, as_of = coach.get("since"), coach.get("as_of")
    if not who or coach.get("source") != "lineup" or since is None or as_of is None:
        return None
    start = date.fromisoformat(str(since))
    days = (match.kickoff.astimezone(UTC).date() - start).days
    streak = int(coach.get("streak") or 0)
    window_edge = days >= current_coach.LOOKBACK_DAYS - 30
    at_least = "al menos " if window_edge else ""
    fresh = bool(coach.get("fresh"))
    claim = (f"{name}: en el banquillo {who} desde el partido del {start.isoformat()} ({at_least}{days} días antes de este partido; "
             f"{streak} planilla{'' if streak == 1 else 's'} seguida{'' if streak == 1 else 's'} con su nombre)"
             + ("" if fresh else f"; la última planilla es del {as_of}, de hace más de {current_coach.FRESH_DAYS} días") + ".")
    team = match.home_id if side == "home" else match.away_id
    calc = {"version": VERSION, "rule": RULE, "reader": coach.get("rules_version"), "team": team, "side": side, "coach": who, "since": start.isoformat(),
            "days": days, "at_least": window_edge, "streak": streak, "fresh": fresh, "as_of": str(as_of), "fixture": coach.get("fixture_id")}
    return PeopleFact(match, "coach", side, team, _clip(claim), calc, _midnight(date.fromisoformat(str(as_of))))


def formation_fact(rows: Sequence[Mapping[str, Any]], match: Match, side: str, name: str) -> PeopleFact | None:
    """The usual formation of a side from its newest sheets (``kickoff_at`` newest first, ``formation`` or None), or None with too few sheets that name one."""
    named = [str(r["formation"]).strip() for r in rows if r["formation"] and str(r["formation"]).strip()]
    if len(named) < MIN_SHEETS:
        return None
    ranked = Counter(named).most_common()
    top, used = ranked[0]
    tied = [f for f, n in ranked if n == used]
    blank = len(rows) - len(named)
    if len(tied) > 1:
        shown = " y ".join(sorted(tied))
        claim = f"{name}: sus {len(named)} últimas formaciones conocidas se reparten sin una dominante ({shown}, {used} veces cada una)"
    else:
        claim = f"{name}: formación más usada {top}, en {used} de sus últimas {len(named)} planillas con formación"
    claim += f"; {blank} planilla{'' if blank == 1 else 's'} sin formación." if blank else "."
    team = match.home_id if side == "home" else match.away_id
    calc = {"version": VERSION, "rule": RULE, "team": team, "side": side, "window": WINDOW, "sheets": len(rows), "named": len(named), "blank": blank,
            "formations": dict(ranked), "usual": None if len(tied) > 1 else top, "used": used}
    newest = max(r["kickoff_at"] for r in rows)
    return PeopleFact(match, "formation", side, team, _clip(claim), calc, newest)


def referee_fact(ref: officials.RefereeAsOf, match: Match, home: str, away: str, *, at: datetime) -> PeopleFact | None:
    """The referee of the match as the provider had named him, or None when nobody is named at ``at``."""
    if ref.identity is None or not ref.name:
        return None
    shown = ref.spelling or ref.name
    where = f", de {ref.country}" if ref.country else ""
    how = "identificado como persona" if ref.identity == officials.ID else "tal como lo escribió el proveedor, sin identificar"
    seen = f" (visto el {ref.seen_at.astimezone(UTC).date().isoformat()})" if ref.seen_at else ""
    lead = round((match.kickoff - (ref.seen_at or at)).total_seconds() / 3600, 1)
    claim = f"Árbitro de {home} contra {away}: {shown}{where}; {how}{seen}."
    calc = {"version": VERSION, "rule": RULE, "referee": ref.name, "identity": ref.identity, "referee_id": ref.referee_id,
            "seen_at": None if ref.seen_at is None else ref.seen_at.isoformat(), "hours_before_kickoff": lead}
    published = at if ref.seen_at is None else min(at, ref.seen_at)
    return PeopleFact(match, "referee", "match", None, _clip(claim), calc, published)


def item_of(fact: PeopleFact, *, at: datetime) -> evidence.EvidenceIn:
    """The fact as the item the store takes: complete in the seven attributes, or ``store`` refuses it."""
    if fact.kind == "referee":
        key, subject, sid, claim_type = f"referee:{fact.match.fixture_id}", "MATCH", fact.match.fixture_id, "OTHER"
    else:
        key, subject, sid, claim_type = (f"{fact.kind}:{fact.match.fixture_id}:{fact.team}", "TEAM", int(fact.team or 0),
                                         "COACH" if fact.kind == "coach" else "OTHER")
    return evidence.EvidenceIn(
        fixture_id=fact.match.fixture_id, team_id=fact.team, kind=fact.kind, claim=fact.claim, origin="own_calc", source_name=SOURCE_NAME, retrieved_at=at,
        story_key=key, assertion="info", published_at=fact.published_at, confidence=0.9, relevance=0.5, attributes={"calculation": VERSION, **fact.calculation},
        claim_type=claim_type, subject_type=subject, subject_id=sid, fresh_until=fact.match.kickoff, side=fact.side, fact_schema=factor_schema.VERSION)


# ── database ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Read:
    match: Match
    competition: str
    home: str
    away: str
    facts: list[PeopleFact]
    missing: list[str]


def collect(conn: psycopg.Connection[Any], *, at: datetime, ahead: timedelta = AHEAD) -> list[Read]:
    """The facts of the matches that kick off within ``ahead`` of ``at``, as of ``at``. Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(MATCHES_SQL, {"at": at, "until": at + ahead}).fetchall()
        teams = sorted({int(r[k]) for r in rows for k in ("home_team_id", "away_team_id")})
        coaches = current_coach_store.current_coach(conn, teams, now=at)
        out: list[Read] = []
        for r in rows:
            match = Match(int(r["fixture_id"]), r["kickoff_at"], int(r["home_team_id"]), int(r["away_team_id"]))
            facts: list[PeopleFact] = []
            missing: list[str] = []
            for side, team, name in (("home", match.home_id, str(r["home_name"])), ("away", match.away_id, str(r["away_name"]))):
                c = coach_fact(coaches.get(team, {}), match, side, name)
                (facts.append(c) if c is not None else missing.append(f"coach:{side}"))
                sheets = cur.execute(FORMATIONS_SQL, {"team": team, "kickoff": match.kickoff, "at": at, "window": WINDOW}).fetchall()
                f = formation_fact(sheets, match, side, name)
                (facts.append(f) if f is not None else missing.append(f"formation:{side}"))
            ref = referee_fact(officials.referee_as_of(conn, match.fixture_id, at), match, str(r["home_name"]), str(r["away_name"]), at=at)
            (facts.append(ref) if ref is not None else missing.append("referee"))
            out.append(Read(match, str(r["competition"]), str(r["home_name"]), str(r["away_name"]), facts, missing))
    return out


def run(conn: psycopg.Connection[Any], *, at: datetime, write: bool | None = None, ahead: timedelta = AHEAD) -> Counts:
    """The facts of the matches that kick off within ``ahead`` of ``at``. Nothing is written unless ``write`` (default: the switch is ``on``); a fact the store
    refuses is counted in ``errors`` and does not stop the others. The caller commits."""
    do_write = mode() == "on" if write is None else write
    counts = Counts()
    for read in collect(conn, at=at, ahead=ahead):
        counts.matches += 1
        counts.facts += len(read.facts)
        counts.no_coach += sum(1 for m in read.missing if m.startswith("coach"))
        counts.no_formation += sum(1 for m in read.missing if m.startswith("formation"))
        counts.no_referee += int("referee" in read.missing)
        if not do_write:
            continue
        for fact in read.facts:
            try:
                with conn.transaction():
                    _, created = evidence.store(conn, item_of(fact, at=at), at=at)
            except (factor_schema.IncompleteFactError, psycopg.Error, ValueError) as exc:
                counts.errors.append(f"{read.match.fixture_id}:{fact.kind}:{fact.side}:{type(exc).__name__}")
                continue
            counts.created += int(created)
    return counts


__all__ = ["AHEAD", "MAX_CLAIM", "SWITCH", "TABLES", "VERSION", "Counts", "Match", "PeopleFact", "Read", "coach_fact", "collect", "formation_fact", "item_of", "mode",
           "referee_fact", "run"]
