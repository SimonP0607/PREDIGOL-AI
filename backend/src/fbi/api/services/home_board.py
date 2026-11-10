"""What Inicio's general layer reads from ``/home`` besides what is in play (plan de Inicio, section 4 and 3.1): the rules that
choose a block's matches live here, on the server, and the web only draws what comes. Reading only: nothing in this module
computes a probability, prices a selection or chooses a pick.

**Últimos resultados** - the matches that ended in the last 24 hours, the most recent first, six at most. A match is over when
the match feed says so (``fixture_results`` with its group ``finished``) or when the fixture feed's last word is a final
(``FT``, ``AET`` or ``PEN``; the same three the match feed's finished group must carry): the live board drops a match the moment that final arrives, and the result has to be here at once -
never a gap where the match is in neither block. A cancelled, postponed or abandoned match is not a result.

**Partidos relevantes** - of the matches in play, only those with a reason, and the reason is computed here from what is stored:
a final; the second leg of a tie and how the aggregate stands now; a side fighting for the title, Europe, relegation or
promotion (the packet's ``stakes``) and how it is going; or a comeback (a side that was behind and is now level or ahead,
read from the fixture feed's own states). A match with no reason is not shown: nothing is made up to fill the block. Four at
most, by competition priority.

Both blocks, and what is left for «En vivo», go in PrediGol's own order of competitions (``board_group``): the Champions League
and the big leagues first, then the continental cups and Colombia's Primera A, then the national-team tournaments, then the rest;
inside a group by the competition's tier and then by kick-off (plan de Inicio, D2).

**Qué se juega** - the matches not yet started in the next 36 hours with something at stake, one sentence each: a final, the
first leg's result before a second leg, or a side fighting for the title, Europe, relegation or promotion. No line about rest
or the next match (those belong to a match's own page). Four at most, by competition priority.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.contracts.center import LiveMatch
from fbi.api.contracts.product import (
    CompetitionBadge,
    HomeAtStake,
    HomeReason,
    HomeRelevant,
    HomeResult,
    TeamBadge,
)
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services import reading
from fbi.intel import day_priority

RESULTS_WINDOW: Final = timedelta(hours=24)
"""Results: the last 24 hours (plan de Inicio, section 4)."""
RESULTS_MAX: Final = 6
FINALS: Final = ("FT", "AET", "PEN")
"""The statuses of a match that was played to its end: a final after 90 minutes, after extra time and after the shoot-out."""

RESULTS_SQL = """
WITH last_state AS (
  SELECT DISTINCT ON (s.fixture_id) s.fixture_id, s.status_short, s.goals_home, s.goals_away
    FROM core.fixture_live_states s
   WHERE s.observed_at >= %(since)s
   ORDER BY s.fixture_id, s.observed_at DESC
)
SELECT f.id AS fixture_id, f.kickoff_at,
       CASE WHEN f.status_group = 'finished' THEN f.status_short ELSE l.status_short END AS status,
       COALESCE(r.goals_home, l.goals_home) AS goals_home, COALESCE(r.goals_away, l.goals_away) AS goals_away,
       r.pen_home, r.pen_away,
       c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag,
       f.home_team_id, th.name AS home_name, th.logo_url AS home_logo,
       f.away_team_id, ta.name AS away_name, ta.logo_url AS away_logo
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
  LEFT JOIN last_state l ON l.fixture_id = f.id
 WHERE c.is_tracked AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(at)s
   AND ((r.fixture_id IS NOT NULL AND f.status_group = 'finished' AND f.status_short = ANY(%(finals)s))
        OR (l.status_short = ANY(%(finals)s) AND l.goals_home IS NOT NULL AND l.goals_away IS NOT NULL))
 ORDER BY f.kickoff_at DESC, c.tier NULLS LAST, f.id DESC
 LIMIT %(limit)s
"""


def _result(r: dict[str, Any]) -> HomeResult:
    pens = r["pen_home"] is not None and r["pen_away"] is not None
    return HomeResult(
        fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
        competition=CompetitionBadge(id=r["competition_id"], name=r["competition_name"], country=r["competition_country"],
                                     logo_url=r["competition_logo"], flag_url=r["competition_flag"]),
        home=TeamBadge(id=r["home_team_id"], name=r["home_name"], logo_url=r["home_logo"]),
        away=TeamBadge(id=r["away_team_id"], name=r["away_name"], logo_url=r["away_logo"]),
        status=r["status"],
        goals_home=int(r["goals_home"]), goals_away=int(r["goals_away"]),
        pens_home=int(r["pen_home"]) if pens else None, pens_away=int(r["pen_away"]) if pens else None)


def results(conn: Conn, *, at: datetime) -> list[HomeResult]:
    """The last 24 hours' results, newest first, six at most."""
    rows = fetch_all(conn, RESULTS_SQL, {"since": at - RESULTS_WINDOW, "at": at, "finals": list(FINALS),
                                         "limit": RESULTS_MAX})
    return [_result(r) for r in rows]


# ── what a match is playing for: the reasons ──────────────────────────────────────────────────────────────────────────

RELEVANT_MAX: Final = 4
AT_STAKE_MAX: Final = 4
REASONS_MAX: Final = 2
"""A match in play shows two reasons at most: the strongest first."""
AT_STAKE_WINDOW: Final = timedelta(hours=36)
AT_STAKE_SCAN: Final = 150
"""How many of the next 36 hours' matches are read for a reason (by competition priority): more than the day's matches of the
leagues that matter, and one query for their packets."""
HISTORY_WINDOW: Final = timedelta(hours=4)
"""A comeback is read from the states of the last four hours: longer than a match, shorter than a day."""
STAKES: Final = frozenset({"title", "europe", "relegation", "promotion"})
"""What counts as «something at stake» in a table (the packet's ``stakes.pressure``): not a settled season, not mid-table, and not
the play-off whose meaning depends on the competition."""

BOARD_EXTRA: Final[dict[int, int]] = {239: 2}
"""Competitions Inicio's general layer puts in a group of its own, over ``fbi.intel.day_priority`` (which orders the picks of the day
and is not touched): Colombia's Primera A (API-Football league 239) goes with the continental cups, so the readers of
Colombia keep it near the top (decision D2)."""


def board_group(provider_league_id: int | None) -> int:
    """The priority group (1 to 4) of a competition on Inicio's general layer: PrediGol's competition priority
    (``day_priority``, comp-priority-v1) with ``BOARD_EXTRA`` raised to its group."""
    group = day_priority.group_of(provider_league_id)
    extra = None if provider_league_id is None else BOARD_EXTRA.get(int(provider_league_id))
    return group if extra is None else min(group, extra)


def board_groups() -> dict[str, list[int]]:
    """The league ids of groups 1 to 3, for a query to order by (group 4 is every other one)."""
    out: dict[str, list[int]] = {"g1": [], "g2": [], "g3": []}
    for leagues in day_priority.GROUPS.values():
        for league in leagues:
            out[f"g{board_group(league)}"].append(league)
    for league in BOARD_EXTRA:
        if league not in out[f"g{board_group(league)}"]:
            out[f"g{board_group(league)}"].append(league)
    return out


TIERS_SQL = "SELECT id, tier, provider_league_id FROM core.competitions WHERE id = ANY(%(ids)s)"

TRAILED_SQL = """
WITH states AS (
    SELECT s.fixture_id, s.goals_home, s.goals_away,
           min(s.goals_home) OVER later AS later_home, min(s.goals_away) OVER later AS later_away
      FROM core.fixture_live_states s
     WHERE s.fixture_id = ANY(%(ids)s) AND s.observed_at >= %(since)s
       AND s.goals_home IS NOT NULL AND s.goals_away IS NOT NULL
    WINDOW later AS (PARTITION BY s.fixture_id ORDER BY s.observed_at DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
)
SELECT fixture_id,
       COALESCE(max(goals_away - goals_home), 0) AS home_down_by,
       COALESCE(max(goals_home - goals_away), 0) AS away_down_by
  FROM states
 WHERE goals_home <= COALESCE(later_home, goals_home) AND goals_away <= COALESCE(later_away, goals_away)
 GROUP BY fixture_id
"""
"""The most each side was behind in the match so far, from the fixture feed's states that stood: one whose goals no later state took
back. The feed gives a goal when it is scored and takes it back when the referee or the VAR annuls it (0-1, then 0-0), and a
deficit that was taken back was never one - without this, «iba perdiendo por 1 gol y ya empata» was said of a match that never
had a goal (UX-098). Of the 23 finished matches read on 10-nov-2026, 8 had a state the feed later took back."""

AT_STAKE_SQL = """
SELECT f.id AS fixture_id, f.kickoff_at,
       c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag,
       f.home_team_id, th.name AS home_name, th.logo_url AS home_logo,
       f.away_team_id, ta.name AS away_name, ta.logo_url AS away_logo
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at > %(at)s AND f.kickoff_at <= %(until)s
 ORDER BY CASE WHEN c.provider_league_id = ANY(%(g1)s) THEN 1 WHEN c.provider_league_id = ANY(%(g2)s) THEN 2
               WHEN c.provider_league_id = ANY(%(g3)s) THEN 3 ELSE 4 END,
          c.tier NULLS LAST, f.kickoff_at, f.id
 LIMIT %(limit)s
"""


def _side_pressures(g: reading.Glance) -> dict[str, str]:
    """For each side of the match that fights for something (``STAKES``): what for."""
    out: dict[str, str] = {}
    for f in g.context:
        side, pressure = f.params.get("side"), f.params.get("pressure")
        if f.code == "stakes_pressure" and side in ("home", "away") and pressure in STAKES:
            out[str(side)] = str(pressure)
    return out


def _first_leg(g: reading.Glance) -> tuple[int, int] | None:
    """The first leg's score from the point of view of this match's home side, when the packet knows it."""
    for f in g.context:
        home, away = f.params.get("home_goals"), f.params.get("away_goals")
        if f.code == "first_leg" and isinstance(home, int) and isinstance(away, int):
            return home, away
    return None


def _state(mine: int, theirs: int) -> str:
    return "ahead" if mine > theirs else "behind" if mine < theirs else "level"


def live_reasons(g: reading.Glance | None, *, home: str, away: str, goals: tuple[int, int] | None,
                 behind_by: dict[str, int]) -> list[HomeReason]:
    """Why a match in play is worth looking at now, the strongest first and two at most; none when there is no reason.

    ``behind_by``: the most each side ("home", "away") was behind so far. Without a score nothing about the score is said."""
    if g is not None and g.kind == "friendly":
        return []
    out: list[HomeReason] = []
    if g is not None and g.kind == "final":
        out.append(HomeReason(code="final", params={}))
    elif g is not None and g.kind == "second_leg" and goals is not None and (first := _first_leg(g)) is not None:
        out.append(HomeReason(code="tie", params={
            "home": home, "away": away, "first_home": first[0], "first_away": first[1],
            "agg_home": first[0] + goals[0], "agg_away": first[1] + goals[1]}))
    if goals is not None:
        for side, team in (("home", home), ("away", away)):
            mine, theirs = goals if side == "home" else (goals[1], goals[0])
            if behind_by.get(side, 0) > 0 and mine >= theirs:
                out.append(HomeReason(code="comeback", params={
                    "team": team, "side": side, "down_by": behind_by[side], "state": _state(mine, theirs)}))
        if g is not None:
            for side, pressure in _side_pressures(g).items():
                mine, theirs = goals if side == "home" else (goals[1], goals[0])
                out.append(HomeReason(code="stakes", params={
                    "team": home if side == "home" else away, "side": side, "pressure": pressure,
                    "state": _state(mine, theirs)}))
    return out[:REASONS_MAX]


def stake_reason(g: reading.Glance | None, *, home: str, away: str) -> HomeReason | None:
    """What a match not yet played is about, in one reason: a final, the first leg's result, or a fight for the title, Europe,
    relegation or promotion; None when the packet says nothing of the sort."""
    if g is None or g.kind == "friendly":
        return None
    if g.kind == "final":
        return HomeReason(code="final", params={})
    first = _first_leg(g)
    if g.kind == "second_leg" and first is not None:
        return HomeReason(code="first_leg", params={"home": home, "away": away, "first_home": first[0],
                                                    "first_away": first[1]})
    pressures = _side_pressures(g)
    if not pressures:
        return None
    sides = [s for s in ("home", "away") if s in pressures]
    names = {"home": home, "away": away}
    params: dict[str, str | int | float | bool | None] = {"team": names[sides[0]], "pressure": pressures[sides[0]]}
    if len(sides) == 2:
        params["other_team"], params["other_pressure"] = names[sides[1]], pressures[sides[1]]
    return HomeReason(code="stakes", params=params)


# ── the two blocks ────────────────────────────────────────────────────────────────────────────────────────────────────

def _goals(m: LiveMatch) -> tuple[int, int] | None:
    return None if m.goals_home is None or m.goals_away is None else (m.goals_home, m.goals_away)


def _priority(conn: Conn, live: list[LiveMatch]) -> dict[int, tuple[int, int, int, int]]:
    """The order of matches in play on the general layer: the competition's group (``board_group``), its tier, then kick-off."""
    comps = {int(r["id"]): (board_group(r["provider_league_id"]), r["tier"] if r["tier"] is not None else 10_000)
             for r in fetch_all(conn, TIERS_SQL, {"ids": sorted({m.competition_id for m in live
                                                                 if m.competition_id is not None})})}
    return {m.fixture_id: (*comps.get(m.competition_id or -1, (4, 10_000)), int(m.kickoff_at.timestamp()), m.fixture_id)
            for m in live}


def by_priority(conn: Conn, live: list[LiveMatch]) -> list[LiveMatch]:
    """The matches in play in the general layer's order of competitions (the order of «En vivo»)."""
    if not live:
        return []
    order = _priority(conn, live)
    return sorted(live, key=lambda m: order[m.fixture_id])


def relevant(conn: Conn, live: list[LiveMatch], *, at: datetime) -> list[HomeRelevant]:
    """The matches in play that have a reason, by competition priority (then kick-off), four at most."""
    if not live:
        return []
    ids = [m.fixture_id for m in live]
    seen = reading.glances(conn, ids, at=at)
    trailed = {int(r["fixture_id"]): {"home": int(r["home_down_by"]), "away": int(r["away_down_by"])}
               for r in fetch_all(conn, TRAILED_SQL, {"ids": ids, "since": at - HISTORY_WINDOW})}
    order = _priority(conn, live)
    found: list[HomeRelevant] = []
    for m in sorted(live, key=lambda m: order[m.fixture_id]):
        reasons = live_reasons(seen.get(m.fixture_id), home=m.home.name, away=m.away.name, goals=_goals(m),
                               behind_by=trailed.get(m.fixture_id, {}))
        if reasons:
            found.append(HomeRelevant(match=m, reasons=reasons))
    return found[:RELEVANT_MAX]


def at_stake(conn: Conn, *, at: datetime) -> list[HomeAtStake]:
    """The matches not yet started in the next 36 hours with something at stake, by competition priority, four at most."""
    rows = fetch_all(conn, AT_STAKE_SQL, {"at": at, "until": at + AT_STAKE_WINDOW, "limit": AT_STAKE_SCAN,
                                          **board_groups()})
    seen = reading.glances(conn, [int(r["fixture_id"]) for r in rows], at=at)
    out: list[HomeAtStake] = []
    for r in rows:
        reason = stake_reason(seen.get(int(r["fixture_id"])), home=r["home_name"], away=r["away_name"])
        if reason is None:
            continue
        out.append(HomeAtStake(
            fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
            competition=CompetitionBadge(id=r["competition_id"], name=r["competition_name"],
                                         country=r["competition_country"], logo_url=r["competition_logo"],
                                         flag_url=r["competition_flag"]),
            home=TeamBadge(id=r["home_team_id"], name=r["home_name"], logo_url=r["home_logo"]),
            away=TeamBadge(id=r["away_team_id"], name=r["away_name"], logo_url=r["away_logo"]),
            reason=reason))
        if len(out) == AT_STAKE_MAX:
            break
    return out
