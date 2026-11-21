"""The facts of a match's «importance» - where it stands in its competition - said as facts, never as a probability (plan PM, PM-05-08).

``FBI_MATCH_IMPORTANCE_FACTS`` (off by default): nothing a reader sees reads these facts yet. They are built for the fact sheet of the
chronicle and the competition's page; the packet and the pages that carry them come when the switch is turned on with the audited kit,
by agreement with the Intelligence session that owns them.

DESCRIPTION, NOT PREDICTION. Nothing here estimates what a team needs, what it is likely to get or what is «at stake»: that is a forecast
and needs its own protocol and the owner's signature (DM-14, «Qué se juega»). These facts say only what the schedule and the stored
tables already say:

* **the stage** of the match, from the words of its round label (``fbi.competitions.stages``): its name, kind (league, knock-out,
  qualifying), role (league, group, knock-out, final ...), the teams that start a knock-out round when the label says it and, for a
  knock-out round of a power of two, the rounds still to play before the final;
* **the match day** of a league-like stage: this match's day, the last day the PUBLISHED schedule of the stage has, how many days come
  after this one, whether it is the last one, and for each team how many matches of the stage it still has after this one. «Published»
  is what PrediGol has stored for the stage at the moment asked (``core.fixtures`` created by then): a schedule the provider publishes
  in parts (play-offs drawn later) shows fewer days, and ``schedule`` says so;
* **the home and away tables**: from the stored table the match is shown with (``fbi.competitions.tables.match_tables``: the newest
  snapshot taken before kick-off and at or before the moment asked), the home side's place among the home records of its table and the
  away side's among the away records - points 3/1/0 of those matches, then goal difference and goals scored in them. It is NOT the
  official table and is never called so (``RULE``).

AS OF A MOMENT, like every pre-match reader: no snapshot taken after kick-off or after ``at``; no fixture created after ``at``; nothing of
the match's own result. Reads ``core.fixtures``, ``core.standings`` (and what ``match_tables`` reads); writes nothing; 0 requests.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.competitions import stages as stg
from fbi.competitions.context import reading_of
from fbi.competitions.tables import match_tables

SWITCH: Final = "FBI_MATCH_IMPORTANCE_FACTS"
VERSION: Final = "importance-facts-v1"
RULE: Final = (
    "Hechos descriptivos, no una probabilidad. Fase: de la etiqueta de la ronda. Jornadas: del calendario publicado y guardado de la "
    "fase en el momento de la consulta. Puesto como local (o visitante): entre los registros como local (o visitante) de la misma tabla "
    "guardada antes del saque, por puntos 3/1/0 de esos partidos, luego diferencia de goles y goles a favor en ellos; no es la tabla "
    "oficial.")
TABLES: Final = ("core.fixtures", "core.standings")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on (``1``, ``on``, ``true``, ``yes``): born off."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


# ── pure facts ─────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StageMatch:
    """A match of the same stage, as the schedule stored it."""

    fixture_id: int
    home: int
    away: int
    kickoff: datetime
    match_day: int | None


@dataclass(frozen=True, slots=True)
class MatchDays:
    match_day: int
    last_published: int
    after: int
    is_last: bool
    left_home: int
    left_away: int
    schedule: str
    """``publicado``: what the stored schedule of the stage has at the moment asked (never «the whole season» unless it is)."""

    def as_json(self) -> dict[str, Any]:
        return {"match_day": self.match_day, "last_published": self.last_published, "after": self.after, "is_last": self.is_last,
                "matches_left_after": {"home": self.left_home, "away": self.left_away}, "schedule": self.schedule}


def match_days(fixture_id: int, home: int, away: int, kickoff: datetime, match_day: int, stage_matches: Sequence[StageMatch]) -> MatchDays:
    """Of a league-like stage: this match's day, the last day published, the days after it and each team's matches after it."""
    days = [m.match_day for m in stage_matches if m.match_day is not None] + [match_day]
    last = max(days)
    later = [m for m in stage_matches if m.fixture_id != fixture_id and (m.kickoff, m.fixture_id) > (kickoff, fixture_id)]
    return MatchDays(
        match_day=match_day, last_published=last, after=last - match_day, is_last=match_day == last,
        left_home=sum(1 for m in later if home in (m.home, m.away)), left_away=sum(1 for m in later if away in (m.home, m.away)),
        schedule="publicado")


def rounds_to_final(reading: stg.Reading) -> int | None:
    """Knock-out rounds after this one before the final (a final: 0), when the label names the teams that start it as a power of
    two; ``None`` otherwise (a numbered round, a play-off: the label does not say)."""
    if reading.role == "final":
        return 0
    teams = reading.teams
    if reading.kind != "knockout" or teams is None or teams < 4 or teams & (teams - 1):
        return None
    return int(math.log2(teams)) - 1


@dataclass(frozen=True, slots=True)
class SideRecord:
    team_id: int
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int

    @property
    def points(self) -> int:
        return 3 * self.wins + self.draws


@dataclass(frozen=True, slots=True)
class SidePlace:
    team_id: int
    side: str
    position: int
    of: int
    record: SideRecord

    def as_json(self) -> dict[str, Any]:
        r = self.record
        return {"team_id": self.team_id, "side": self.side, "position": self.position, "of": self.of, "played": r.played,
                "wins": r.wins, "draws": r.draws, "losses": r.losses, "points": r.points, "goals_for": r.goals_for,
                "goals_against": r.goals_against}


def side_place(team_id: int, side: str, records: Sequence[SideRecord]) -> SidePlace | None:
    """The team's place among these records (one table, one side): points, then goal difference, then goals scored; teams level on
    all three share the better place. ``None`` when the team has no record (a table without the home/away split) or has played no
    match on that side yet: a place among records of nothing says nothing (measured 21-nov-2026: the stored table of the Liga BetPlay's
    quadrangulars had 0 played for its eight teams two match days in)."""
    mine = next((r for r in records if r.team_id == team_id), None)
    if mine is None or mine.played == 0:
        return None

    def key(r: SideRecord) -> tuple[int, int, int]:
        return (r.points, r.goals_for - r.goals_against, r.goals_for)

    better = sum(1 for r in records if key(r) > key(mine))
    return SidePlace(team_id=team_id, side=side, position=better + 1, of=len(records), record=mine)


@dataclass(frozen=True, slots=True)
class ImportanceFacts:
    fixture_id: int
    at: datetime
    stage: dict[str, Any]
    match_days: MatchDays | None
    home_place: SidePlace | None
    away_place: SidePlace | None
    table_snapshot_at: datetime | None

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "fixture_id": self.fixture_id, "as_of": self.at.isoformat(), "stage": self.stage,
                "match_days": None if self.match_days is None else self.match_days.as_json(),
                "home_table": None if self.home_place is None else self.home_place.as_json(),
                "away_table": None if self.away_place is None else self.away_place.as_json(),
                "table_snapshot_at": None if self.table_snapshot_at is None else self.table_snapshot_at.isoformat(),
                "rule": RULE, "sources": list(TABLES)}


def stage_facts(round_label: str | None, leg: int | None) -> dict[str, Any]:
    reading = reading_of(round_label)
    if reading is None:
        return {"name": stg.stage_of(round_label) or None, "kind": "unresolved", "role": None, "teams": None, "round_no": None,
                "rounds_to_final": None, "leg": leg}
    return {"name": reading.stage, "kind": reading.kind, "role": reading.role, "teams": reading.teams, "round_no": reading.round_no,
            "rounds_to_final": rounds_to_final(reading), "leg": leg}


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL: Final = """
SELECT f.id, f.competition_season_id, f.round, f.kickoff_at, f.home_team_id, f.away_team_id, f.leg
  FROM core.fixtures f WHERE f.id = %(fixture)s
"""

STAGE_MATCHES_SQL: Final = """
SELECT f.id, f.home_team_id, f.away_team_id, f.kickoff_at, f.round
  FROM core.fixtures f
 WHERE f.competition_season_id = %(cs)s AND f.created_at <= %(at)s AND f.status_group <> 'cancelled'
"""
"""The stage's schedule as stored by the moment asked (filtered to the stage in Python: the label is the stage). A cancelled match is
not part of the schedule; a postponed one still is."""

SIDES_SQL: Final = """
SELECT team_id, home_played, home_wins, home_draws, home_losses, home_goals_for, home_goals_against,
       away_played, away_wins, away_draws, away_losses, away_goals_for, away_goals_against
  FROM core.standings
 WHERE competition_season_id = %(cs)s AND snapshot_at = %(at)s AND group_key = %(group)s
"""


def _records(rows: Sequence[Mapping[str, Any]], side: str) -> list[SideRecord]:
    out = []
    for r in rows:
        vals = [r[f"{side}_{n}"] for n in ("played", "wins", "draws", "losses", "goals_for", "goals_against")]
        if any(v is None for v in vals):
            continue
        out.append(SideRecord(int(r["team_id"]), *(int(v) for v in vals)))
    return out


def facts_of(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> ImportanceFacts | None:
    """The facts of one match as of ``at`` (``None`` for an unknown match). Reads only; whatever the switch says (the switch decides
    who may see them, not whether they can be computed: the owner's command reads them with it off)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURE_SQL, {"fixture": fixture_id})
        fx = cur.fetchone()
        if fx is None:
            return None
        cs, label, kickoff = int(fx["competition_season_id"]), fx["round"], fx["kickoff_at"]
        home, away = int(fx["home_team_id"]), int(fx["away_team_id"])
        stage = stage_facts(label, fx["leg"])
        days: MatchDays | None = None
        day = stg.match_day_of(label)
        if stage["kind"] == "league" and day is not None:
            cur.execute(STAGE_MATCHES_SQL, {"cs": cs, "at": at})
            name = stg.stage_of(label)
            same = [StageMatch(int(r["id"]), int(r["home_team_id"]), int(r["away_team_id"]), r["kickoff_at"], stg.match_day_of(r["round"]))
                    for r in cur.fetchall() if stg.stage_of(r["round"]) == name]
            days = match_days(fixture_id, home, away, kickoff, day, same)
    found = match_tables(conn, cs, label, kickoff, home, away, not_after=min(at, kickoff))
    home_place = away_place = None
    snapshot = None
    if found is not None:
        snapshot = found.snapshot_at
        with conn.cursor(row_factory=dict_row) as cur:
            groups = {team: found.choice.keys.get(team) for team in (home, away)}
            for team, side in ((home, "home"), (away, "away")):
                group = groups[team]
                if group is None:
                    continue
                cur.execute(SIDES_SQL, {"cs": cs, "at": snapshot, "group": group})
                place = side_place(team, side, _records(cur.fetchall(), side))
                if side == "home":
                    home_place = place
                else:
                    away_place = place
    return ImportanceFacts(fixture_id=fixture_id, at=at, stage=stage, match_days=days, home_place=home_place, away_place=away_place,
                           table_snapshot_at=snapshot)
