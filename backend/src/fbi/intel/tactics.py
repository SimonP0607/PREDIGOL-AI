"""OBSERVABLE TACTICS OF A TEAM - ``tactics-v1`` (plan F6): what the last matches of a team show about how it lines up and how a match
goes for it, said with the size of every sample.

WHAT IS HERE. Only what the provider's lists let us count, in the last ``N`` matches of the team before this one (the very matches of the
dossier's team blocks):

    formations      the formation of the starting eleven, how often each was used, how many times it changed from one match to the next,
                    the last one
    starters        how many of the eleven changed from one match to the next (rotation) and how many men started them all
    coach           whether the sample is of one coach or of several, and for how many matches the newest one has been there
    goals           scored and conceded in each quarter of an hour of the 90 minutes (the stoppage time of a half counts in the last band of
                    that half) and the late goals (the band after the 75th minute) apart
    with the score  the results of the matches in which the team scored first and in which it conceded first, how many times it led and
                    did not win or trailed and did not lose, and the results by the half-time score
    substitutions   how many, when the first one is made, and what the score was at that moment

WHAT IS NOT HERE. Positions, pressure, passes by zone, shots by period: the provider gives none (the statistics are of the whole match and
the events carry no coordinates), so no «style» (high press, low block) is inferred from what is not measured (plan, section 19, point 8).
This is not a prediction, no model reads it (``tests/unit/test_context_isolation.py``) and its status in ``intel.context_factors`` is
DESCRIPTIVE until an experiment says otherwise.

HOW A MATCH IS READ. Every rule below is a way of leaving a match out, never of guessing what it would have said.

* Everything is AS OF ``at``: the matches whose result was recorded by then, and the events and match sheets fetched by then.
* The events of a match count only if its goals of the 90 minutes ARE its score of the 90 minutes, side by side. The provider's list can be
  a live reading that was never replaced, can miss a goal or can still list one the VAR took away; a match whose list does not give the
  score is not read (``data.events.inconsistent``). Own goals are filed under the team that gets the goal (measured on production, 22 Oct
  2026: all of the 1,154 matches whose only goal was an own goal); a missed penalty and the kicks of a shoot-out are not goals; what is
  scored after the 90th minute is extra time and is left out, because the score compared with is the 90-minute one (``reg_goals``). Of the
  38,198 finished matches of the 400 days before that date (read again on 23 Oct 2026), 90.7 % had a list that gave the score, 8.9 % had
  no list at all and 0.4 % (158 matches) had one that did not.
* A squad sheet that the statistics of the same match put on the other side (``fbi.people.sides``: in 202 matches the provider gave each
  team the other's eleven) is not used for the formation or the eleven. The coach written beside it is the right one (the provider
  crosses the players, not the coach) and is used. A sheet with no formation - a third of them - counts as a match with no formation,
  never as a formation.
* The first substitution is the first of the team in the order of the provider's list; the score at that moment is the goals of the list
  before it.
* Samples are small. A rate over ten matches moves by one match: every block carries its ``n``, and the narrative must quote it.

Pure functions in the first half of the file (``read_events``, ``profile``...); the reading of the database in the second.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import reduce
from itertools import pairwise, takewhile
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.people import sides

VERSION: Final = "tactics-v1"
FACTOR: Final = "tactics_profile"
"""The name of this block in the registry of context factors (``intel.context_factors``)."""

N: Final = 10
"""Matches per team: the same ones as the dossier's team blocks (``fbi.intel.dossier.N``)."""
WINDOW: Final = timedelta(days=400)
"""How far back they may be."""

REGULATION: Final = 90
"""The minutes that count: what is scored after them is extra time."""
BANDS: Final = (("1-15", 15), ("16-30", 30), ("31-45+", 45), ("46-60", 60), ("61-75", 75), ("76-90+", 90))
"""The bands of the 90 minutes and the last minute of each. Stoppage time is filed under its half's last minute (45+2 is the 45th, 90+4
the 90th), which is how the provider lists it."""
LATE: Final = len(BANDS) - 1
"""The band of the late goals."""
EVER_PRESENT_FROM: Final = 3
"""Complete sheets needed before «men who started them all» is said."""
ELEVEN: Final = 11

STATES: Final = ("leading", "level", "trailing")

NOTE: Final = (
    "Lo observable de los últimos partidos de cada equipo, con el tamaño de cada muestra (n): formación inicial, rotación del once, goles "
    "por tramo de 15 minutos, resultado según quién marca primero y cómo se llega al descanso, y el primer cambio según el marcador. Son "
    "descripciones: no son predicciones, ningún modelo las lee y con diez partidos una diferencia pequeña es ruido. El proveedor no da "
    "posiciones ni presión, así que no se deduce un «estilo» (presión alta, bloque bajo). Un partido cuyos eventos no reproducen su "
    "marcador, o cuya hoja de alineación el proveedor cruzó, no se usa para eso (ver data).")

SheetState = Literal["none", "crossed", "ok"]
EventsState = Literal["none", "inconsistent", "ok"]


# ── reading the events of one match ──────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Ev:
    """One line of the provider's list of events of a match, in the order the provider gave."""

    minute: int
    side: str | None
    kind: str
    detail: str | None = None
    comments: str | None = None


@dataclass(frozen=True, slots=True)
class Goal:
    """A goal of the 90 minutes: its minute and whether the team of the profile got it."""

    minute: int
    mine: bool


@dataclass(frozen=True, slots=True)
class Sub:
    """A substitution of the team in the 90 minutes and the lead at that moment (its goals minus the other side's)."""

    minute: int
    lead: int


@dataclass(frozen=True, slots=True)
class Reading:
    """What the events of a match say, once they are known to give its score."""

    goals: tuple[Goal, ...]
    subs: tuple[Sub, ...]

    def first_goal_is_mine(self) -> bool | None:
        return self.goals[0].mine if self.goals else None

    def led_and_trailed(self) -> tuple[bool, bool]:
        """Was the team ahead at some moment? Was it behind at some moment?"""
        lead, led, trailed = 0, False, False
        for g in self.goals:
            lead += 1 if g.mine else -1
            led = led or lead > 0
            trailed = trailed or lead < 0
        return led, trailed


def is_goal(e: Ev) -> bool:
    """A goal on the scoreboard: a missed penalty and the kicks of a shoot-out are not."""
    return e.kind == "Goal" and e.detail != "Missed Penalty" and e.comments != "Penalty Shootout"


def read_events(events: Iterable[Ev], side: str, gf: int, ga: int) -> Reading | None:
    """The goals of the 90 minutes, in the order they were scored, and the team's substitutions with the lead of each, seen from ``side``
    (``home`` or ``away``) - or None when those goals are not the score ``gf`` - ``ga`` of the team and its rival. ``events`` are in the
    provider's order. Own goals count for the side they are filed under, which is the one that gets the goal."""
    goals: list[Goal] = []
    subs: list[Sub] = []
    lead = mine = theirs = 0
    for e in events:
        if e.minute > REGULATION:
            continue
        if is_goal(e):
            if e.side not in sides.SIDES:
                return None
            ours = e.side == side
            goals.append(Goal(e.minute, ours))
            if ours:
                mine += 1
                lead += 1
            else:
                theirs += 1
                lead -= 1
        elif e.kind.lower() == "subst" and e.side == side:
            subs.append(Sub(e.minute, lead))
    return Reading(tuple(goals), tuple(subs)) if (mine, theirs) == (gf, ga) else None


def band_of(minute: int) -> int | None:
    """The index in ``BANDS`` of a minute of the 90, None for extra time."""
    if minute < 0 or minute > REGULATION:
        return None
    return next(i for i, (_, last) in enumerate(BANDS) if minute <= last)


def state_of(lead: int) -> str:
    return "leading" if lead > 0 else "trailing" if lead < 0 else "level"


# ── one team, one match ──────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Played:
    """A match of the team as the profile sees it. Built by ``played_by``; tests build them by hand."""

    fixture_id: int
    kickoff: datetime
    side: str
    gf: int
    ga: int
    half_time: tuple[int, int] | None = None
    """The score at the break, team first."""
    sheet: SheetState = "none"
    formation: str | None = None
    """Only from a sheet that is not crossed."""
    starters: frozenset[int] | None = None
    """The eleven, only from a sheet that is not crossed and has them all."""
    coach: str | None = None
    """A key for the coach written on the sheet (his id, else his name): the sheet's, even when it is crossed."""
    events: EventsState = "none"
    reading: Reading | None = None


def _avg(xs: Sequence[float | int], places: int = 1) -> float | None:
    return round(sum(xs) / len(xs), places) if xs else None


def tally(matches: Iterable[Played]) -> dict[str, int]:
    """The results of these matches (90 minutes) for the team."""
    wins = draws = losses = 0
    for m in matches:
        if m.gf > m.ga:
            wins += 1
        elif m.gf == m.ga:
            draws += 1
        else:
            losses += 1
    return {"n": wins + draws + losses, "wins": wins, "draws": draws, "losses": losses}


def data_quality(matches: Sequence[Played]) -> dict[str, Any]:
    """Why the samples are smaller than the matches: what was not there or was not used."""
    ok = [m for m in matches if m.sheet == "ok"]
    return {
        "sheets": {"none": sum(m.sheet == "none" for m in matches), "crossed": sum(m.sheet == "crossed" for m in matches),
                   "without_formation": sum(not m.formation for m in ok),
                   "without_the_eleven": sum(m.starters is None for m in ok)},
        "events": {"none": sum(m.events == "none" for m in matches),
                   "inconsistent": sum(m.events == "inconsistent" for m in matches)},
    }


def formations(newest_first: Sequence[Played]) -> dict[str, Any]:
    forms = [m.formation for m in newest_first if m.formation]
    if not forms:
        return {"n": 0}
    counts = Counter(forms)
    best = max(counts.values())
    changes = sum(1 for a, b in pairwise(newest_first[::-1]) if a.formation and b.formation and a.formation != b.formation)
    return {"n": len(forms), "main": next(f for f in forms if counts[f] == best), "main_count": best, "last": forms[0],
            "distinct": len(counts), "changes": changes, "counts": dict(counts.most_common())}


def starters(newest_first: Sequence[Played]) -> dict[str, Any]:
    """Rotation: the men of one match's eleven who were not in the eleven of the match before it, for every pair of consecutive
    matches that both have their eleven."""
    oldest_first = newest_first[::-1]
    complete = [m.starters for m in oldest_first if m.starters is not None]
    if not complete:
        return {"n": 0}
    changes = [len(b - a) for a, b in pairwise(m.starters for m in oldest_first) if a is not None and b is not None]
    out: dict[str, Any] = {"n": len(complete), "pairs": len(changes), "changes": changes[::-1], "avg_changes": _avg(changes)}
    if len(complete) >= EVER_PRESENT_FROM:
        out["ever_present"] = len(reduce(lambda a, b: a & b, complete))
    return out


def coach_block(newest_first: Sequence[Played]) -> dict[str, Any]:
    """Is the sample of one coach? The sheets say who sat on the bench; the newest one's matches are counted back from the latest."""
    keys = [m.coach for m in newest_first if m.coach]
    if not keys:
        return {"n": 0}
    return {"n": len(keys), "distinct": len(set(keys)), "newest_matches": len(list(takewhile(lambda k: k == keys[0], keys)))}


def goals_block(read: Sequence[tuple[Played, Reading]]) -> dict[str, Any]:
    if not read:
        return {"n": 0}
    scored, conceded = [0] * len(BANDS), [0] * len(BANDS)
    late_for = late_against = 0
    for _, r in read:
        scored_late = conceded_late = False
        for g in r.goals:
            band = band_of(g.minute)
            if band is None:
                continue
            (scored if g.mine else conceded)[band] += 1
            if band == LATE:
                scored_late, conceded_late = scored_late or g.mine, conceded_late or not g.mine
        late_for += scored_late
        late_against += conceded_late
    return {"n": len(read), "bands": [label for label, _ in BANDS], "for": scored, "against": conceded,
            "total_for": sum(scored), "total_against": sum(conceded),
            "late": {"for": scored[LATE], "against": conceded[LATE], "matches_for": late_for, "matches_against": late_against}}


def with_the_score(newest_first: Sequence[Played], read: Sequence[tuple[Played, Reading]]) -> dict[str, Any]:
    """The results by who scored first and by the score at the break. The first needs the events; the second only the result."""
    at_break = [(m, m.half_time) for m in newest_first if m.half_time is not None]
    out: dict[str, Any] = {
        "half_time": {"n": len(at_break),
                      "leading": tally(m for m, h in at_break if h[0] > h[1]), "level": tally(m for m, h in at_break if h[0] == h[1]),
                      "trailing": tally(m for m, h in at_break if h[0] < h[1])}}
    if not read:
        return out | {"n": 0}
    ahead = [(m, r.led_and_trailed()) for m, r in read]
    return out | {
        "n": len(read),
        "scored_first": tally(m for m, r in read if r.first_goal_is_mine() is True),
        "conceded_first": tally(m for m, r in read if r.first_goal_is_mine() is False),
        "goalless": sum(not r.goals for _, r in read),
        "led_and_did_not_win": sum(led and m.gf <= m.ga for m, (led, _) in ahead),
        "trailed_and_did_not_lose": sum(trailed and m.gf >= m.ga for m, (_, trailed) in ahead),
    }


def substitutions(read: Sequence[tuple[Played, Reading]]) -> dict[str, Any]:
    if not read:
        return {"n": 0}
    firsts = [r.subs[0] for _, r in read if r.subs]
    minutes = [s.minute for s in firsts]
    by_state = {state: [s.minute for s in firsts if state_of(s.lead) == state] for state in STATES}
    return {
        "n": len(read), "with_substitutions": len(firsts), "per_match": _avg([len(r.subs) for _, r in read]),
        "first_minute": {"mean": _avg(minutes), "median": round(float(statistics.median(minutes)), 1) if minutes else None},
        "first_by_state": {state: {"n": len(ms), "mean_minute": _avg(ms)} for state, ms in by_state.items()},
    }


def profile(team_id: int, played: Sequence[Played]) -> dict[str, Any]:
    """The profile of one team from its last matches (any order): the block of the packet."""
    if not played:
        return {"team_id": team_id, "n": 0, "fixtures": []}
    newest_first = sorted(played, key=lambda m: m.kickoff, reverse=True)
    read = [(m, m.reading) for m in newest_first if m.reading is not None]
    return {
        "team_id": team_id, "n": len(newest_first), "fixtures": [m.fixture_id for m in newest_first],
        "read": {"events": [m.fixture_id for m, _ in read], "sheets": [m.fixture_id for m in newest_first if m.sheet != "none"]},
        "data": data_quality(newest_first),
        "formations": formations(newest_first), "starters": starters(newest_first), "coach": coach_block(newest_first),
        "goals": goals_block(read), "with_the_score": with_the_score(newest_first, read), "substitutions": substitutions(read),
    }


# ── reading the database ─────────────────────────────────────────────────────────────────────────────────────────────────

MATCHES_SQL = """
SELECT f.id, f.kickoff_at, (f.home_team_id = %(team)s) AS at_home,
       COALESCE(r.reg_goals_home, r.goals_home) AS gh, COALESCE(r.reg_goals_away, r.goals_away) AS ga,
       r.ht_goals_home AS hth, r.ht_goals_away AS hta
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at < %(kickoff)s
   AND f.kickoff_at >= %(kickoff)s - %(window)s AND r.settled_at <= %(at)s
 ORDER BY f.kickoff_at DESC LIMIT %(n)s
"""
"""The matches of the dossier's team blocks (``fbi.intel.dossier.MATCHES_SQL``): the same rows, so a profile and a block cite the same
matches (a test holds them to it)."""

EVENTS_SQL = """
SELECT e.fixture_id, e.minute, e.team_side, e.event_type, e.detail, e.comments
  FROM core.fixture_events e
 WHERE e.fixture_id = ANY(%(fixtures)s) AND e.fetched_at <= %(at)s
 ORDER BY e.fixture_id, e.minute, e.extra_minute NULLS FIRST, e.seq
"""

SHEETS_SQL = """
SELECT l.fixture_id, l.team_side, l.formation, l.coach_id, l.coach_name,
       array_agg(lp.provider_player_id ORDER BY lp.provider_player_id) FILTER (WHERE lp.is_starter) AS starters
  FROM core.fixture_lineups l
  LEFT JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side AND lp.source = l.source
 WHERE l.fixture_id = ANY(%(fixtures)s) AND l.fetched_at <= %(at)s
 GROUP BY l.fixture_id, l.team_side, l.formation, l.coach_id, l.coach_name
"""

CROSSED_SQL = """
SELECT l.fixture_id, l.team_side, count(*) AS men, count(*) FILTER (WHERE s.team_side <> l.team_side) AS apart
  FROM core.fixture_lineup_players l
  JOIN core.fixture_player_stats s ON s.fixture_id = l.fixture_id AND s.source = l.source AND s.provider_player_id = l.provider_player_id
 WHERE l.provider_player_id > 0 AND l.fixture_id = ANY(%(fixtures)s) AND s.fetched_at <= %(at)s
 GROUP BY l.fixture_id, l.team_side
HAVING count(*) FILTER (WHERE s.team_side <> l.team_side) > 0
"""
"""``fbi.people.player_history.SHEETS_SQL`` with the moment: the statistics of the same match that were fetched by ``at`` say which squad
sheets are the other side's, by the rule of ``fbi.people.sides``. A statistic fetched later was not known then."""


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def crossed_sheets(conn: psycopg.Connection[Any], fixtures: Sequence[int], *, at: datetime) -> frozenset[int]:
    """The matches among ``fixtures`` whose squad sheets, as the statistics fetched by ``at`` show, are the other side's. The provider
    crosses both sheets of a match, so a match with one of them crossed has both."""
    return frozenset(int(r["fixture_id"]) for r in _rows(conn, CROSSED_SQL, {"fixtures": list(fixtures), "at": at})
                     if sides.is_crossed(int(r["men"]), int(r["apart"])))


def coach_key(coach_id: Any, name: Any) -> str | None:
    """A key for the coach of a sheet: his id when the sheet has one, else his name as written."""
    if coach_id is not None:
        return f"id:{int(coach_id)}"
    text = " ".join(str(name or "").split()).lower()
    return f"name:{text}" if text else None


def played_by(conn: psycopg.Connection[Any], team: int, *, kickoff: datetime, at: datetime, n: int = N) -> list[Played]:
    """The last ``n`` matches of ``team`` before ``kickoff`` as known at ``at``, newest first, with what the provider's lists say."""
    matches = _rows(conn, MATCHES_SQL, {"team": team, "kickoff": kickoff, "window": WINDOW, "at": at, "n": n})
    if not matches:
        return []
    fixtures = [int(m["id"]) for m in matches]
    events: dict[int, list[Ev]] = defaultdict(list)
    for r in _rows(conn, EVENTS_SQL, {"fixtures": fixtures, "at": at}):
        events[int(r["fixture_id"])].append(Ev(int(r["minute"]), r["team_side"], str(r["event_type"]), r["detail"], r["comments"]))
    sheets = {(int(r["fixture_id"]), str(r["team_side"])): r for r in _rows(conn, SHEETS_SQL, {"fixtures": fixtures, "at": at})}
    crossed = crossed_sheets(conn, fixtures, at=at)
    out: list[Played] = []
    for m in matches:
        fid = int(m["id"])
        side = sides.HOME if m["at_home"] else sides.AWAY
        gf, ga = (int(m["gh"]), int(m["ga"])) if side == sides.HOME else (int(m["ga"]), int(m["gh"]))
        ht = None if m["hth"] is None or m["hta"] is None else (
            (int(m["hth"]), int(m["hta"])) if side == sides.HOME else (int(m["hta"]), int(m["hth"])))
        sheet = sheets.get((fid, side))
        state: SheetState = "none" if sheet is None else "crossed" if fid in crossed else "ok"
        usable = sheet if sheet is not None and state == "ok" else None
        men = [int(p) for p in (usable or {}).get("starters") or []]
        listed = events.get(fid)
        reading = read_events(listed, side, gf, ga) if listed else None
        out.append(Played(
            fixture_id=fid, kickoff=m["kickoff_at"], side=side, gf=gf, ga=ga, half_time=ht, sheet=state,
            formation=" ".join(str((usable or {}).get("formation") or "").split()) or None,
            starters=frozenset(men) if len(men) == ELEVEN else None,
            coach=coach_key(sheet["coach_id"], sheet["coach_name"]) if sheet is not None else None,
            events="none" if not listed else "ok" if reading is not None else "inconsistent", reading=reading))
    return out


def block(conn: psycopg.Connection[Any], *, home: int, away: int, kickoff: datetime, at: datetime,
          status: str = "DESCRIPTIVE") -> dict[str, Any]:
    """The block of the packet (``dossier.tactics``): the profile of each side as of ``at``."""
    return {"version": VERSION, "status": status, "note": NOTE,
            "home": profile(home, played_by(conn, home, kickoff=kickoff, at=at)),
            "away": profile(away, played_by(conn, away, kickoff=kickoff, at=at))}
