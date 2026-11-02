"""HEAD-TO-HEAD, IN CONTEXT - ``h2h-v2`` (plan F6): the earlier meetings of two sides, each weighed by how much it says about the
match being described, and read by ONE function for the AI packet and for the match page.

Until F6 there were two head-to-heads. The packet read the last eight meetings by their 90-minute score; the page read the last
eight by their final score (extra time in) and counted a match as played from its stored group instead of from the result row. A
2-2 that went to penalties was a draw in one and a 3-2 in the other, and a meeting whose result had been recorded after the packet's
moment was in the page and not in the packet. And neither said what a meeting WAS: a friendly between reserve sides six years ago
counted as much as the cup tie of last month, played in the other team's ground, under another coach.

``head_to_head`` reads the meetings once - finished (``FT`` / ``AET`` / ``PEN``), kicked off before the match, result recorded by the
moment asked (``settled_at <= at``, like every pre-match reader) - and ``weigh`` gives each one a weight that is the product of four
plain factors:

    recency      0.5 ** (age / three years): a meeting loses half its weight every three years
    competition  same competition 1.0 · same kind (league, cup, continental, international) 0.85 · another official kind 0.6 ·
                 a friendly when the match is not one 0.25 (friendlies are the ids the catalogue has pinned)
    ground       the home side of the match was home then too 1.0 · it was away 0.8 · neutral ground 0.9 (every meeting 1.0 when the
                 match itself is on neutral ground: there is no ground to mirror)
    coaches      for each side, the coach on its bench that day is the one it has now 1.0 · not known 0.9 · another one 0.75

The weights are NOT fitted to anything. They are round numbers chosen so that a reader can say why a meeting counts for what it
counts, and they are written into the block (``weights``). They are a description: the factor is ``h2h_weighted`` in
``intel.context_factors`` and stays DESCRIPTIVE until an experiment shows the weighted record predicts a result better than the form
and the market already do (``fbi.intel.factors``). The effective sample size is Kish's, ``(sum w)^2 / sum w^2``: eight meetings of
which three carry nearly all the weight are three meetings, and the block says so (``n_effective``).

Everything is read as of ``at``: a result recorded later, a bench sheet fetched later, are not in it. The ages are counted from the
KICK-OFF of the match, not from ``at``, so a block does not change from one pass to the next while nothing else does (the packet is
stored by the hash of its content). Pure apart from ``head_to_head`` (three small queries).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.ai.context import PastMatch, form
from fbi.catalog.scopes import FRIENDLY_LEAGUES
from fbi.core import match_state

VERSION: Final = "h2h-v2"
"""The shape of the block (``HeadToHead.as_packet`` / ``as_api``): a change to it, or to a weight, bumps this."""

FACTOR: Final = "h2h_weighted"
"""The name of this block in ``intel.context_factors``."""

N: Final = 8
"""Meetings read: the last eight, as the packet and the page always did."""

HALF_LIFE_DAYS: Final = 1095
SCOPE_WEIGHT: Final[dict[str, float]] = {"same_competition": 1.0, "same_kind": 0.85, "other_official": 0.6, "friendly": 0.25}
GROUND_WEIGHT: Final[dict[str, float]] = {"same": 1.0, "reversed": 0.8, "neutral": 0.9}
COACH_WEIGHT: Final[dict[str, float]] = {"same": 1.0, "unknown": 0.9, "changed": 0.75}
WEIGHTS: Final[dict[str, Any]] = {"half_life_days": HALF_LIFE_DAYS, "competition": SCOPE_WEIGHT, "ground": GROUND_WEIGHT,
                                  "coach_per_side": COACH_WEIGHT, "fitted": False}

COACH_WINDOW_DAYS: Final = 400
"""A side's coach NOW is the one on its newest bench sheet within this many days before the match."""

NOTE_LOW: Final = "el historial directo pesa poco frente a la forma y el mercado"
NOTE_HIGH: Final = "historial amplio; aun así, plantillas y entrenadores cambian"
NOTE_DESCRIPTIVE: Final = (
    "Pesos fijos y redondos, no ajustados a ningún dato: describen cuánto dice cada cruce sobre este partido (reciente, de la misma "
    "competición, en el mismo campo, con los mismos entrenadores). Una descripción no es una señal: nadie ha probado que este registro "
    "ponderado prediga mejor que la forma y el mercado.")

Side = Literal["home", "away"]
Ground = Literal["same", "reversed", "neutral"]
Scope = Literal["same_competition", "same_kind", "other_official", "friendly"]

MEETINGS_SQL: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, f.home_team_id, f.away_team_id, th.name AS home, ta.name AS away,
       c.id AS competition_id, c.name AS competition, c.provider_league_id, c.competition_type AS competition_kind,
       (f.is_neutral OR c.neutral_venue OR COALESCE(k.neutral, false)) AS neutral,
       r.goals_home, r.goals_away, r.reg_goals_home, r.reg_goals_away, r.pen_home, r.pen_away,
       (r.et_goals_home IS NOT NULL OR r.et_goals_away IS NOT NULL OR f.status_short = ANY(%(extra_time)s)) AS extra_time
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_venue_class k ON k.fixture_id = f.id AND k.rule_version = %(rule)s
 WHERE ((f.home_team_id = %(a)s AND f.away_team_id = %(b)s) OR (f.home_team_id = %(b)s AND f.away_team_id = %(a)s))
   AND f.kickoff_at < %(kickoff)s AND r.settled_at <= %(at)s AND f.status_short = ANY(%(finished)s)
   AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
 ORDER BY f.kickoff_at DESC, f.id DESC LIMIT %(limit)s
"""
"""The meetings: played to a result (the stored states ``FT`` / ``AET`` / ``PEN``), before the match, with their result recorded
by ``at``. The same rows for the packet and for the page."""

BENCH_OF_MEETINGS_SQL: Final = """
SELECT DISTINCT ON (l.fixture_id, l.team_side) l.fixture_id, l.team_side, l.provider_coach_id, l.coach_name
  FROM core.fixture_lineups l
 WHERE l.fixture_id = ANY(%(fixtures)s) AND l.fetched_at <= %(at)s
   AND (l.provider_coach_id IS NOT NULL OR btrim(coalesce(l.coach_name, '')) <> '')
 ORDER BY l.fixture_id, l.team_side, l.fetched_at DESC, l.source
"""
"""The coach on each bench in the meetings: the newest match sheet fetched by ``at`` that names one."""

BENCH_NOW_SQL: Final = """
WITH s AS (
    SELECT CASE WHEN l.team_side = 'home' THEN f.home_team_id ELSE f.away_team_id END AS team_id, f.kickoff_at,
           l.fetched_at, l.source, l.provider_coach_id, l.coach_name
      FROM core.fixture_lineups l JOIN core.fixtures f ON f.id = l.fixture_id
     WHERE ((l.team_side = 'home' AND f.home_team_id = ANY(%(teams)s)) OR (l.team_side = 'away' AND f.away_team_id = ANY(%(teams)s)))
       AND f.kickoff_at <= %(kickoff)s AND f.kickoff_at >= %(kickoff)s - make_interval(days => %(window)s)
       AND l.fetched_at <= %(at)s AND (l.provider_coach_id IS NOT NULL OR btrim(coalesce(l.coach_name, '')) <> '')
)
SELECT DISTINCT ON (team_id) team_id, provider_coach_id, coach_name FROM s
 ORDER BY team_id, kickoff_at DESC, fetched_at DESC, source
"""
"""The coach each side has NOW: on the newest bench sheet fetched by ``at`` - the sheet of the match itself once it is out, else the
last match's."""


# ── coaches ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _norm(name: str | None) -> str | None:
    if not name or not name.strip():
        return None
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().split()) or None


@dataclass(frozen=True, slots=True)
class Coach:
    """A coach as a match sheet names him: the provider's id when it gave one, the name always (folded for comparing)."""

    provider_id: int | None
    name: str | None

    def same_as(self, other: Coach | None) -> bool | None:
        """Is it the same man? By the provider's id when both sheets have one, else by the folded name; None when neither can be
        compared - nothing is guessed."""
        if other is None:
            return None
        if self.provider_id is not None and other.provider_id is not None:
            return self.provider_id == other.provider_id
        a, b = _norm(self.name), _norm(other.name)
        if a is not None and b is not None:
            return a == b
        return None


def _coach(provider_id: Any, name: Any) -> Coach | None:
    pid = None if provider_id is None else int(provider_id)
    cleaned = None if name is None or not str(name).strip() else str(name).strip()
    return None if pid is None and cleaned is None else Coach(pid, cleaned)


# ── the data ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Meeting:
    """One earlier meeting of the two sides, as stored."""

    fixture_id: int
    kickoff_at: datetime
    home_team_id: int
    away_team_id: int
    home: str
    away: str
    competition_id: int
    competition: str
    competition_kind: str | None
    friendly: bool
    neutral: bool
    goals_home: int
    goals_away: int
    reg_goals_home: int
    reg_goals_away: int
    extra_time: bool
    pen_home: int | None
    pen_away: int | None
    coach_home: Coach | None = None
    """The coach on the bench of the meeting's home side that day (None: no sheet by ``at``)."""
    coach_away: Coach | None = None


@dataclass(frozen=True, slots=True)
class Situation:
    """The match being described."""

    home_team_id: int
    away_team_id: int
    kickoff_at: datetime
    competition_id: int | None = None
    competition_kind: str | None = None
    friendly: bool = False
    neutral: bool = False
    coach_home: Coach | None = None
    coach_away: Coach | None = None


@dataclass(frozen=True, slots=True)
class Weighed:
    """A meeting seen from the match being described: in regulation time, from its HOME side's point of view, with its weight."""

    meeting: Meeting
    age_days: int
    scope: Scope
    ground: Ground
    home_side_was: Literal["home", "away", "neutral"]
    coach_changed_home: bool | None
    coach_changed_away: bool | None
    goals_home_side: int
    goals_away_side: int
    result: Literal["W", "D", "L"]
    w_recency: float
    w_scope: float
    w_ground: float
    w_coach: float

    @property
    def weight(self) -> float:
        return self.w_recency * self.w_scope * self.w_ground * self.w_coach


# ── weighing (pure) ──────────────────────────────────────────────────────────────────────────────────────────────────────


def scope_of(m: Meeting, now: Situation) -> Scope:
    """What kind of meeting it was, against the kind of match being described."""
    if m.friendly:
        return "same_kind" if now.friendly else "friendly"
    if now.friendly:
        return "other_official"
    if now.competition_id is not None and m.competition_id == now.competition_id:
        return "same_competition"
    if now.competition_kind is not None and m.competition_kind == now.competition_kind:
        return "same_kind"
    return "other_official"


def _side_weight(changed: bool | None) -> float:
    return COACH_WEIGHT["unknown"] if changed is None else COACH_WEIGHT["changed"] if changed else COACH_WEIGHT["same"]


def weigh_one(m: Meeting, now: Situation) -> Weighed:
    """One meeting, from the point of view of the match's home side. Pure."""
    age = max(0, (now.kickoff_at - m.kickoff_at).days)
    same_ground = m.home_team_id == now.home_team_id
    home_side_was: Literal["home", "away", "neutral"] = "neutral" if m.neutral else "home" if same_ground else "away"
    ground: Ground = "same" if now.neutral else "neutral" if m.neutral else "same" if same_ground else "reversed"
    gh, ga = (m.reg_goals_home, m.reg_goals_away) if same_ground else (m.reg_goals_away, m.reg_goals_home)
    # the coach of each CURRENT side then, against the one it has now
    then_home = m.coach_home if same_ground else m.coach_away
    then_away = m.coach_away if same_ground else m.coach_home
    changed_home = None if now.coach_home is None or then_home is None else _flip(then_home.same_as(now.coach_home))
    changed_away = None if now.coach_away is None or then_away is None else _flip(then_away.same_as(now.coach_away))
    scope = scope_of(m, now)
    return Weighed(
        meeting=m, age_days=age, scope=scope, ground=ground, home_side_was=home_side_was,
        coach_changed_home=changed_home, coach_changed_away=changed_away, goals_home_side=gh, goals_away_side=ga,
        result="W" if gh > ga else "D" if gh == ga else "L",
        w_recency=0.5 ** (age / HALF_LIFE_DAYS), w_scope=SCOPE_WEIGHT[scope], w_ground=GROUND_WEIGHT[ground],
        w_coach=_side_weight(changed_home) * _side_weight(changed_away))


def _flip(same: bool | None) -> bool | None:
    return None if same is None else not same


def relevance(n_effective: float, last_age_days: int | None) -> str:
    """How much the head-to-head is worth, in the words the narrative reads: few, old or minor meetings weigh little."""
    if last_age_days is None:
        return "nula"
    return "baja" if n_effective < 2.0 or last_age_days > 730 else "media" if n_effective < 4.0 else "alta"


@dataclass(frozen=True, slots=True)
class HeadToHead:
    """The meetings of a pair as seen from one match, newest first, with everything derived from them."""

    situation: Situation
    rows: tuple[Weighed, ...]
    version: str = VERSION

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def weight_total(self) -> float:
        return sum(r.weight for r in self.rows)

    @property
    def n_effective(self) -> float:
        """Kish's effective sample size of the weights: 8 meetings of equal weight are 8, 3 carrying all of it are 3."""
        total = self.weight_total
        squares = sum(r.weight**2 for r in self.rows)
        return 0.0 if squares == 0 else total**2 / squares

    @property
    def last_age_days(self) -> int | None:
        return None if not self.rows else self.rows[0].age_days

    @property
    def relevance(self) -> str:
        return relevance(self.n_effective, self.last_age_days)

    def record(self, rows: Sequence[Weighed] | None = None) -> dict[str, int]:
        """The raw count in regulation time, from the match's home side's point of view."""
        rs = self.rows if rows is None else rows
        return {"n": len(rs), "home_side_wins": sum(r.result == "W" for r in rs), "draws": sum(r.result == "D" for r in rs),
                "away_side_wins": sum(r.result == "L" for r in rs)}

    def same_venue(self) -> dict[str, int] | None:
        """The record of the meetings in which this match's home side was at home, too; nothing when the match is on neutral
        ground (there is no home to mirror)."""
        if self.situation.neutral:
            return None
        return self.record([r for r in self.rows if r.home_side_was == "home"])

    def weighted(self) -> dict[str, float] | None:
        """The same record with each meeting by its weight (shares that add up to one) and the weighted goals per meeting."""
        total = self.weight_total
        if not self.rows or total <= 0:
            return None
        share = {k: sum(r.weight for r in self.rows if r.result == k) / total for k in ("W", "D", "L")}
        return {"home_side_win": round(share["W"], 3), "draw": round(share["D"], 3), "away_side_win": round(share["L"], 3),
                "goals_home_side_pg": round(sum(r.weight * r.goals_home_side for r in self.rows) / total, 2),
                "goals_away_side_pg": round(sum(r.weight * r.goals_away_side for r in self.rows) / total, 2)}

    def coaches(self) -> dict[str, int]:
        """How many meetings had BOTH benches as they are now, how many had one of them changed, how many cannot be told."""
        both = changed = unknown = 0
        for r in self.rows:
            states = (r.coach_changed_home, r.coach_changed_away)
            if any(s is True for s in states):
                changed += 1
            elif all(s is False for s in states):
                both += 1
            else:
                unknown += 1
        return {"both_same": both, "some_changed": changed, "unknown": unknown}

    def as_packet(self, *, status: str = "DESCRIPTIVE") -> dict[str, Any]:
        """The block of the AI packet (``content["h2h"]``). ``n`` and ``home_view`` are what it always carried (the 90-minute
        form of the home side in these meetings); the rest is new in packet-v8."""
        home_id = self.situation.home_team_id
        block: dict[str, Any] = {
            "version": self.version, "status": status, "n": self.n, "n_effective": round(self.n_effective, 1),
            "last_days_ago": self.last_age_days, "relevance": self.relevance,
            "note": NOTE_HIGH if self.relevance == "alta" else NOTE_LOW,
            "home_view": form(home_id, [PastMatch(r.meeting.kickoff_at, r.meeting.home_team_id, r.meeting.away_team_id,
                                                  r.meeting.reg_goals_home, r.meeting.reg_goals_away) for r in self.rows]),
        }
        if not self.rows:
            return block
        block |= {
            "oldest_days_ago": max(r.age_days for r in self.rows),
            "record": self.record(), "weighted": self.weighted(), "same_venue": self.same_venue(),
            "coaches": self.coaches(),
            "meetings": [{
                "fixture_id": r.meeting.fixture_id, "days_ago": r.age_days, "competition": r.meeting.competition,
                "scope": r.scope, "home_side_was": r.home_side_was, "goals_home_side": r.goals_home_side,
                "goals_away_side": r.goals_away_side, "after_extra_time": r.meeting.extra_time,
                "coach_changed": {"home": r.coach_changed_home, "away": r.coach_changed_away},
                "weight": round(r.weight, 2)} for r in self.rows],
            "weights": WEIGHTS, "weights_note": NOTE_DESCRIPTIVE,
        }
        return block

    def as_api(self) -> list[dict[str, Any]]:
        """The rows of the match page's head-to-head: the meeting as it was played (``goals_*`` is the final score, extra time in),
        the 90 minutes, how it was decided, and what the meeting weighs for this match."""
        return [{
            "fixture_id": r.meeting.fixture_id, "kickoff_at": r.meeting.kickoff_at, "competition": r.meeting.competition,
            "home": r.meeting.home, "away": r.meeting.away, "goals_home": r.meeting.goals_home,
            "goals_away": r.meeting.goals_away, "regulation_goals_home": r.meeting.reg_goals_home,
            "regulation_goals_away": r.meeting.reg_goals_away, "after_extra_time": r.meeting.extra_time,
            "penalties_home": r.meeting.pen_home, "penalties_away": r.meeting.pen_away, "scope": r.scope,
            "home_side_was": r.home_side_was, "weight": round(r.weight, 2)} for r in self.rows]


def weigh(meetings: Sequence[Meeting], now: Situation) -> HeadToHead:
    """The meetings (newest first) weighed against the match being described. Pure."""
    return HeadToHead(now, tuple(weigh_one(m, now) for m in meetings))


# ── from the database ────────────────────────────────────────────────────────────────────────────────────────────────────


def is_friendly(provider_league_id: int | None) -> bool:
    """A friendly, by the ids the catalogue has pinned (``fbi.catalog.scopes.FRIENDLY_LEAGUES``): the provider flags none, and a
    rule that reads names is the drift that module exists to undo."""
    return provider_league_id is not None and int(provider_league_id) in FRIENDLY_LEAGUES


def head_to_head(conn: psycopg.Connection[Any], *, home_team_id: int, away_team_id: int, kickoff: datetime, at: datetime,
                 competition_id: int | None = None, competition_kind: str | None = None,
                 provider_league_id: int | None = None, neutral: bool = False, rule: str | None = None,
                 limit: int = N) -> HeadToHead:
    """The head-to-head of a match as it can be said at ``at``: the last ``limit`` finished meetings of the two sides that kicked
    off before the match and had their result recorded by ``at``, each weighed against the match."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MEETINGS_SQL, {"a": home_team_id, "b": away_team_id, "kickoff": kickoff, "at": at, "limit": limit,
                                   "rule": rule, "finished": sorted(match_state.FINISHED),
                                   "extra_time": sorted(match_state.AFTER_EXTRA_TIME)})
        rows = [dict(r) for r in cur.fetchall()]
        benches: dict[tuple[int, str], Coach | None] = {}
        if rows:
            cur.execute(BENCH_OF_MEETINGS_SQL, {"fixtures": [int(r["fixture_id"]) for r in rows], "at": at})
            benches = {(int(r["fixture_id"]), str(r["team_side"])): _coach(r["provider_coach_id"], r["coach_name"])
                       for r in cur.fetchall()}
        cur.execute(BENCH_NOW_SQL, {"teams": [home_team_id, away_team_id], "kickoff": kickoff, "at": at,
                                    "window": COACH_WINDOW_DAYS})
        now_coach = {int(r["team_id"]): _coach(r["provider_coach_id"], r["coach_name"]) for r in cur.fetchall()}
    meetings = [Meeting(
        fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"], home_team_id=int(r["home_team_id"]),
        away_team_id=int(r["away_team_id"]), home=str(r["home"]), away=str(r["away"]),
        competition_id=int(r["competition_id"]), competition=str(r["competition"]),
        competition_kind=None if r["competition_kind"] is None else str(r["competition_kind"]),
        friendly=is_friendly(r["provider_league_id"]),
        neutral=bool(r["neutral"]), goals_home=int(r["goals_home"]), goals_away=int(r["goals_away"]),
        reg_goals_home=int(r["reg_goals_home"]), reg_goals_away=int(r["reg_goals_away"]), extra_time=bool(r["extra_time"]),
        pen_home=None if r["pen_home"] is None else int(r["pen_home"]),
        pen_away=None if r["pen_away"] is None else int(r["pen_away"]),
        coach_home=benches.get((int(r["fixture_id"]), "home")), coach_away=benches.get((int(r["fixture_id"]), "away")))
        for r in rows]
    situation = Situation(
        home_team_id=home_team_id, away_team_id=away_team_id, kickoff_at=kickoff, competition_id=competition_id,
        competition_kind=competition_kind, friendly=is_friendly(provider_league_id), neutral=neutral,
        coach_home=now_coach.get(home_team_id), coach_away=now_coach.get(away_team_id))
    return weigh(meetings, situation)
