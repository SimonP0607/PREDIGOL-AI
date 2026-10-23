"""Longitudinal memory - ``memory-v4``: what PrediGol Intelligence has seen of each team, competition, referee, coach,
player and market, accumulated day by day (``intel.entity_memory``, append-only).

One row per entity x aspect x Bogotá day, written only when something of it happened that day; each row carries the
CUMULATIVE state as of that day (the previous row + the day's delta) and the day's delta, and names the decisions and
matches it rests on. History is never rewritten: yesterday's row stays as it was written.

    team x market:<key>           decisions (INVESTIGACION or better) on its matches, by selection; settled, wins,
                                  losses, flat profit, closing-line value, post-mortem verdicts, the last ten results
    competition x market:<key>    the same per competition
    market x decisions            the same per market, every competition
    referee x discipline          matches, cards (yellow + red), fouls, penalties, cards shown to home / away sides
                                  (the entity is the person, ``entity_id`` his id in ``core.referees``)
    coach x profile               matches, formations used, wins / draws / losses, goals for / against
    player x availability         times reported out by the provider, and how often he started anyway
    team x corners | cards | xg   what the team produced and what its opponents produced against it, match by match, with the
                                  league's mean behind it (memory-v4)
    competition x corners | cards | xg
                                  the league's own mean per team in a match: the ground the teams' figures are shrunk to (memory-v4)

LATE NEWS (memory-v2, plan F0 defect 3). A match settles, a statistic arrives, a post-mortem is written after the day's row
was already written. memory-v1 looked at the day before yesterday again for exactly that, but wrote with ``ON CONFLICT DO
NOTHING``: when the entity already had a row that day, what it had learned late was thrown away. A row is never rewritten,
so now what a previous day learned late is BOOKED IN THE ROW OF THE DAY IT WAS LEARNED, under ``delta["late"][<day>]``:
fresh(<day>) minus what is already recorded for that day (its own row, and whatever earlier rows booked for it). The
numbers and the counters of the cumulative state are therefore what a recomputation from scratch would give (``last10``
lists the results in the order they were learned), and the state "as of" a day still holds only what was known by that
day (no hindsight leaks backwards). Reconciling twice books nothing twice. ``late_days`` reaches further back for a
one-off repair (``build_memory(..., late_days=30)``); the nightly cycle uses ``LATE_DAYS``.

REFEREES ARE PEOPLE (memory-v3, plan F3). memory-v2 keyed the referee by the string the provider wrote, so one man was several
entities and two men with one initial and surname were one. Now the entity is the referee of ``fbi.people`` and its id the
``entity_id``. The rows memory-v2 wrote under a string stay as they were (history is never rewritten) but nothing continues
them: the new entities begin on the first day memory-v3 runs, and the console lists only the entities of ids. A string key is
never reconciled either - the late-news pass would otherwise read "this version no longer produces it" as "the day's matches
were taken back" and book the difference against the old rows. A match the identity has not placed yet is counted when it is,
by the same late-news pass. When two referees are merged (or one is split) the days still inside the late window are
re-booked to the right person; older days stay with the person they were recorded under, and the dossier, which is computed
from the matches, is exact either way.

A streak (``last10``) is a signal to investigate, never a rule: nothing here changes a model, a filter or a pick.

MEMORY WITH A CONFIDENCE (memory-v4, plan F8). A number from three matches and a number from three hundred looked the same in
memory-v3. Now every row carries ``confidence`` (0 to 1) and ``evidence_ref`` (what it rests on, by kind: fixtures, decisions,
post-mortems). The confidence is the EFFECTIVE sample over itself plus a constant, ``n_eff / (n_eff + k)``, where ``n_eff`` counts
each piece of evidence once and then discounts it by its age: it loses half its weight after ``half_life`` days (``SPECS``: a
referee's style lasts a year, a player's availability pattern a few months). ``n_eff`` is kept in the state - carried to the next
row with the gap between the two days applied - so the row of a day says how much of the memory is recent. The late news is
weighted by the day it belongs to, not by the day it was learned. The half-lives and the ``k`` are conventions of the memory, not
parameters of any model: changing one is a new version of the memory.

CORNERS, CARDS AND XG, SHRUNK. A team with two matches that took 14 corners does not "average seven": two matches say little. The
figures of the three new aspects are shrunk toward the mean of the league(s) the team played in (``own_shrunk`` =
(weighted corners + m x league mean) / (weighted matches + m)), so a team with few matches is its league's mean and one with many
is itself; the league's own row (``competition x corners``) is where that mean comes from. ``m`` is the number of matches the league's
mean is worth (``METRICS``). A team that played in two competitions is shrunk to the mean of both weighted by its matches in each.

ITS OWN LINEAGE. memory-v4 continues nothing: its rows are built from the first day of the lineage (``LINEAGE_START``, 13 October
2026), day by day, from the data as they are (``rebuild``), and each row's "previous state" is the previous memory-v4 row.
Rows of older versions stay as history and are never read to build a new one. ``intel.entity_memory_latest`` is the view that says,
for each entity, aspect and day, which row wins (the newest version). The nightly step writes nothing until the lineage has begun
(``lineage_started``): a night that began the lineage by itself would give every entity a state that forgets the days before.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds

VERSION = "memory-v4"
LINEAGE_START = date(2026, 10, 13)
"""The first Bogotá day of memory-v4 (plan F8: "memory rebuilt from 13 October"). Nothing earlier is built, so nothing earlier is claimed."""
MAX_SOURCES = 40
LATE = "late"
LATE_DAYS = 3
"""How many days back the news learned late is looked for (a postponed match settled a couple of days after its day)."""

DECISIONS_SQL = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.*
      FROM intel.decisions d
     WHERE d.kickoff_at >= %(start)s AND d.kickoff_at < %(end)s
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
)
SELECT l.id, l.fixture_id, l.market_key, l.selection, l.state, o.result_status, o.clv::float8 AS clv,
       o.profit_flat::float8 AS profit, pm.verdict, f.home_team_id, f.away_team_id, th.name AS home_name,
       ta.name AS away_name, cs.competition_id, c.name AS competition_name
  FROM last l
  JOIN intel.decision_outcomes o ON o.decision_id = l.id
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN LATERAL (SELECT x.verdict FROM intel.postmortems x WHERE x.decision_id = l.id
                      ORDER BY x.id DESC LIMIT 1) pm ON true
 WHERE l.state <> 'RECHAZADO'
"""

MATCHES_SQL = """
SELECT f.id AS fixture_id, f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name,
       cs.competition_id, c.name AS competition_name, fr.referee_id, rf.name AS referee_name,
       COALESCE(r.reg_goals_home, r.goals_home) AS gh, COALESCE(r.reg_goals_away, r.goals_away) AS ga
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_referees fr ON fr.fixture_id = f.id
  LEFT JOIN core.referees rf ON rf.id = fr.referee_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND f.status_group = 'finished'
   AND (%(fixtures)s::bigint[] IS NULL OR f.id = ANY(%(fixtures)s))
"""

STATS_SQL = """
SELECT DISTINCT ON (fixture_id, team_side) fixture_id, team_side, yellow_cards, red_cards, fouls, corners,
       expected_goals::float8 AS expected_goals
  FROM core.fixture_team_stats WHERE fixture_id = ANY(%(fixtures)s)
 ORDER BY fixture_id, team_side, (source = 'api-football') DESC, fetched_at DESC
"""

PENALTIES_SQL = """
SELECT fixture_id, count(*) AS n FROM core.fixture_events
 WHERE fixture_id = ANY(%(fixtures)s) AND event_type = 'Goal' AND detail IN ('Penalty', 'Missed Penalty')
   AND COALESCE(comments, '') <> 'Penalty Shootout'
 GROUP BY 1
"""

LINEUPS_SQL = """
SELECT l.fixture_id, l.team_side, l.formation, COALESCE(l.coach_id::text, 'p' || l.provider_coach_id::text) AS coach,
       l.coach_name
  FROM core.fixture_lineups l
 WHERE l.fixture_id = ANY(%(fixtures)s) AND (l.coach_id IS NOT NULL OR l.provider_coach_id IS NOT NULL)
"""

ABSENCES_SQL = """
SELECT a.fixture_id, a.provider_player_id, max(a.player_name) AS name, bool_or(lp.is_starter) AS started,
       bool_or(lp.provider_player_id IS NOT NULL) AS in_squad
  FROM core.player_absences a
  LEFT JOIN core.fixture_lineup_players lp ON lp.fixture_id = a.fixture_id
       AND lp.provider_player_id = a.provider_player_id
 WHERE a.fixture_id = ANY(%(fixtures)s) AND a.absence_type ILIKE 'Missing%%'
 GROUP BY 1, 2
"""

STATE_SQL = """
SELECT DISTINCT ON (entity_type, entity_id, aspect) entity_type, entity_id, aspect, as_of_day, stats
  FROM intel.entity_memory
 WHERE version = %(version)s
   AND (entity_type, entity_id, aspect) IN (SELECT * FROM unnest(%(types)s::text[], %(ids)s::text[], %(aspects)s::text[]))
   AND as_of_day {cmp} %(day)s
 ORDER BY entity_type, entity_id, aspect, as_of_day DESC, id DESC
"""
PREVIOUS_SQL = STATE_SQL.format(cmp="<")
"""The latest row of THIS version before the day: memory-v4 continues its own rows and no other (a memory begun by a new version
begins again, from a day that is stated; see ``LINEAGE_START``)."""
CURRENT_SQL = STATE_SQL.format(cmp="<=")
"""The same, the day itself included: the league rows a team's figures are shrunk to."""

RECORDED_SQL = """
SELECT entity_type, entity_id, aspect, as_of_day, delta, sources
  FROM intel.entity_memory
 WHERE version = %(version)s AND as_of_day >= %(from)s AND as_of_day < %(before)s
"""
"""What is already recorded for the days being looked at again: their own rows, and the late news that the rows between
them and ``before`` booked for them (of this version: a row of another version is history, not a record to reconcile)."""

WRITTEN_SQL = "SELECT entity_type, entity_id, aspect FROM intel.entity_memory WHERE as_of_day = %(day)s AND version = %(version)s"

POSTMORTEMS_SQL = """
SELECT DISTINCT ON (decision_id) decision_id, id FROM intel.postmortems
 WHERE decision_id = ANY(%(decisions)s) ORDER BY decision_id, id DESC
"""
"""The post-mortem each decision rests on, the newest: part of what a row of decisions names as its evidence."""

STARTED_SQL = "SELECT EXISTS (SELECT 1 FROM intel.entity_memory WHERE version = %(version)s AND as_of_day < %(day)s)"

Delta = dict[str, Any]
EKey = tuple[str, str, str]
Row = dict[str, Any]


@dataclass(frozen=True)
class Spec:
    """How a kind of memory ages and how much evidence it takes to trust it (conventions of the memory, not model parameters)."""

    half_life: float
    """Days after which a piece of evidence has lost half its weight."""
    k: float
    """The effective sample at which the confidence is one half."""
    count: str
    """The field of the delta that counts the pieces of evidence."""
    decayed: tuple[str, ...] = ()
    """Further fields of the delta that are also kept with the weight of age (``w_<field>`` in the state)."""


@dataclass(frozen=True)
class Metric:
    """A figure of a match that both sides report, taken to a team's memory and to its league's."""

    aspect: str
    prior_weight: float
    """How many matches the league's mean is worth when a team's figure is shrunk to it."""
    pair: Callable[[Row, Row], tuple[float, float] | None]
    """(home, away) from the two sides' statistics, or None when the match does not say it."""


def _corners(h: Row, a: Row) -> tuple[float, float] | None:
    if h.get("corners") is None or a.get("corners") is None:
        return None
    return int(h["corners"]), int(a["corners"])


def _cards(h: Row, a: Row) -> tuple[float, float] | None:
    """Yellow + red, a side the source did not report taken as none (the way the referee's row counts them) - but only when both
    sides have a line of statistics: a match with no statistics says nothing about cards."""
    if not h or not a:
        return None
    return (int(h.get("yellow_cards") or 0) + int(h.get("red_cards") or 0),
            int(a.get("yellow_cards") or 0) + int(a.get("red_cards") or 0))


def _xg(h: Row, a: Row) -> tuple[float, float] | None:
    if h.get("expected_goals") is None or a.get("expected_goals") is None:
        return None
    return float(h["expected_goals"]), float(a["expected_goals"])


METRICS: dict[str, Metric] = {
    # m = within-team variance over between-team variance of the figure, read from football in general (a match of corners varies by
    # about 3 around a team's mean, the teams' means by about 1; cards 1.2 and 0.4; xG 0.65 and 0.25). Measured on the stored matches
    # in the owner's guide; changing one is a new version of the memory.
    "corners": Metric("corners", 6.0, _corners),
    "cards": Metric("cards", 9.0, _cards),
    "xg": Metric("xg", 7.0, _xg),
}

DECISIONS_TEAM = Spec(half_life=90, k=30, count="decisions")
DECISIONS_COMPETITION = Spec(half_life=90, k=60, count="decisions")
DECISIONS_MARKET = Spec(half_life=180, k=100, count="decisions")
REFEREE = Spec(half_life=365, k=20, count="matches")
COACH = Spec(half_life=365, k=10, count="matches")
PLAYER = Spec(half_life=120, k=5, count="reported_out")
TEAM_FIGURES = Spec(half_life=180, k=10, count="matches", decayed=("own", "opp"))
LEAGUE_FIGURES = Spec(half_life=365, k=60, count="matches", decayed=("total",))

DERIVED = ("own_rate", "opp_rate", "own_shrunk", "opp_shrunk", "prior", "prior_matches", "rate")
"""The fields of a state that are computed from the others each time: never carried over from the previous row."""


def spec_for(key: EKey) -> Spec | None:
    """The convention of a kind of memory; None for a kind that has none (its row carries no confidence)."""
    kind, _, aspect = key
    if aspect in METRICS:
        return TEAM_FIGURES if kind == "team" else LEAGUE_FIGURES if kind == "competition" else None
    if aspect.startswith("market:"):
        return DECISIONS_TEAM if kind == "team" else DECISIONS_COMPETITION if kind == "competition" else None
    return {("market", "decisions"): DECISIONS_MARKET, ("referee", "discipline"): REFEREE, ("coach", "profile"): COACH,
            ("player", "availability"): PLAYER}.get((kind, aspect))


def _decision_delta(rows: list[dict[str, Any]]) -> Delta:
    d: Delta = {"decisions": len(rows), "by_state": dict(Counter(r["state"] for r in rows)),
                "by_selection": dict(Counter(r["selection"] for r in rows)), "settled": 0, "wins": 0, "losses": 0,
                "voids": 0, "profit_flat": 0.0, "clv_sum": 0.0, "clv_n": 0,
                "verdicts": dict(Counter(r["verdict"] for r in rows if r.get("verdict"))), "results": []}
    for r in rows:
        res = r["result_status"]
        if res in ("push", "void"):
            d["voids"] += 1
            d["results"].append("N")
        else:
            d["settled"] += 1
            won = res in ("win", "half_win")
            d["wins" if won else "losses"] += 1
            d["results"].append("W" if won else "L")
        d["profit_flat"] += float(r["profit"] or 0)
        if r["clv"] is not None:
            d["clv_sum"] += float(r["clv"])
            d["clv_n"] += 1
    return d


def day_deltas(conn: psycopg.Connection[Any], day: date) -> tuple[dict[EKey, Delta], dict[EKey, str], dict[EKey, list[int]]]:
    """What the data say today about one Bogotá day: the delta, the name and the sources of every entity x aspect."""
    start, end = day_bounds(day)
    deltas: dict[EKey, Delta] = {}
    names: dict[EKey, str] = {}
    sources: dict[EKey, list[int]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DECISIONS_SQL, {"start": start, "end": end})
        decisions = [dict(r) for r in cur.fetchall()]
    groups: dict[EKey, list[dict[str, Any]]] = defaultdict(list)
    for r in decisions:
        aspect = f"market:{r['market_key']}"
        for team, name in ((r["home_team_id"], r["home_name"]), (r["away_team_id"], r["away_name"])):
            k = ("team", str(team), aspect)
            groups[k].append(r)
            names[k] = str(name)
        k = ("competition", str(r["competition_id"]), aspect)
        groups[k].append(r)
        names[k] = str(r["competition_name"])
        k = ("market", str(r["market_key"]), "decisions")
        groups[k].append(r)
        names[k] = str(r["market_key"])
    for k, rows in groups.items():
        deltas[k] = _decision_delta(rows)
        sources[k] = [int(r["id"]) for r in rows][:MAX_SOURCES]

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MATCHES_SQL, {"start": start, "end": end, "fixtures": None})
        matches = {int(r["fixture_id"]): dict(r) for r in cur.fetchall()}
        fids = sorted(matches)
        stats: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        pens: dict[int, int] = {}
        lineups: list[dict[str, Any]] = []
        absences: list[dict[str, Any]] = []
        if fids:
            cur.execute(STATS_SQL, {"fixtures": fids})
            for r in cur.fetchall():
                stats[int(r["fixture_id"])][str(r["team_side"])] = dict(r)
            cur.execute(PENALTIES_SQL, {"fixtures": fids})
            pens = {int(r["fixture_id"]): int(r["n"]) for r in cur.fetchall()}
            cur.execute(LINEUPS_SQL, {"fixtures": fids})
            lineups = [dict(r) for r in cur.fetchall()]
            cur.execute(ABSENCES_SQL, {"fixtures": fids})
            absences = [dict(r) for r in cur.fetchall()]

    for fid, m in matches.items():
        ref = m.get("referee_id")
        if ref is not None:
            k = ("referee", str(ref), "discipline")
            h, a = stats.get(fid, {}).get("home") or {}, stats.get(fid, {}).get("away") or {}
            d = deltas.setdefault(k, {"matches": 0, "cards": 0, "cards_home": 0, "cards_away": 0, "reds": 0,
                                      "fouls": 0, "fouls_matches": 0, "penalties": 0})
            d["matches"] += 1
            if h or a:
                ch = int(h.get("yellow_cards") or 0) + int(h.get("red_cards") or 0)
                ca = int(a.get("yellow_cards") or 0) + int(a.get("red_cards") or 0)
                d["cards"] += ch + ca
                d["cards_home"] += ch
                d["cards_away"] += ca
                d["reds"] += int(h.get("red_cards") or 0) + int(a.get("red_cards") or 0)
                if h.get("fouls") is not None and a.get("fouls") is not None:
                    d["fouls"] += int(h["fouls"]) + int(a["fouls"])
                    d["fouls_matches"] += 1
            d["penalties"] += pens.get(fid, 0)
            names[k] = str(m.get("referee_name") or ref)
            sources[k].append(fid)
    for lu in lineups:
        fid = int(lu["fixture_id"])
        played = matches.get(fid)
        if played is None:
            continue
        m = played
        side = str(lu["team_side"])
        gf, ga = (int(m["gh"]), int(m["ga"])) if side == "home" else (int(m["ga"]), int(m["gh"]))
        k = ("coach", str(lu["coach"]), "profile")
        d = deltas.setdefault(k, {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0,
                                  "home": 0, "away": 0, "formations": {}})
        d["matches"] += 1
        d["wins" if gf > ga else "draws" if gf == ga else "losses"] += 1
        d["goals_for"] += gf
        d["goals_against"] += ga
        d[side] += 1
        if lu.get("formation"):
            d["formations"][str(lu["formation"])] = d["formations"].get(str(lu["formation"]), 0) + 1
        names[k] = str(lu.get("coach_name") or lu["coach"])
        sources[k].append(fid)
    for ab in absences:
        k = ("player", str(ab["provider_player_id"]), "availability")
        d = deltas.setdefault(k, {"reported_out": 0, "started_anyway": 0, "in_squad_anyway": 0})
        d["reported_out"] += 1
        if ab.get("started"):
            d["started_anyway"] += 1
        if ab.get("in_squad"):
            d["in_squad_anyway"] += 1
        names[k] = str(ab.get("name") or ab["provider_player_id"])
        sources[k].append(int(ab["fixture_id"]))

    for fid, m in matches.items():
        sides = stats.get(fid, {})
        h, a = sides.get("home") or {}, sides.get("away") or {}
        comp = str(m["competition_id"])
        for metric in METRICS.values():
            pair = metric.pair(h, a)
            if pair is None:
                continue
            for team, name, own, opp in ((m["home_team_id"], m["home_name"], pair[0], pair[1]),
                                         (m["away_team_id"], m["away_name"], pair[1], pair[0])):
                k = ("team", str(team), metric.aspect)
                d = deltas.setdefault(k, {"matches": 0, "own": 0, "opp": 0, "by_competition": {}})
                d["matches"] += 1
                d["own"] = round(d["own"] + own, 6)
                d["opp"] = round(d["opp"] + opp, 6)
                d["by_competition"][comp] = d["by_competition"].get(comp, 0) + 1
                names[k] = str(name)
                sources[k].append(fid)
            k = ("competition", comp, metric.aspect)
            d = deltas.setdefault(k, {"matches": 0, "total": 0})
            d["matches"] += 1
            d["total"] = round(d["total"] + pair[0] + pair[1], 6)
            names[k] = str(m["competition_name"])
            sources[k].append(fid)

    return deltas, names, sources


# ── arithmetic on deltas (late news = what the data say now minus what is recorded) ─────────────────────────────────────


def _plus(a: Delta, b: Delta) -> Delta:
    out: Delta = dict(a)
    for k, v in b.items():
        if k == "results":
            out[k] = [*(out.get(k) or []), *v]
        elif isinstance(v, dict):
            c: Counter[str] = Counter(out.get(k) or {})
            c.update(v)
            out[k] = {x: n for x, n in c.items() if n}
        elif isinstance(v, (int, float)):
            total = (out.get(k) or 0) + v
            out[k] = round(float(total), 6) if isinstance(total, float) else total
    return out


def _minus(a: Delta, b: Delta) -> Delta:
    """``a`` less ``b``. The results (an ordered list) lose the entries ``b`` already has; counters and numbers subtract."""
    out: Delta = dict(a)
    for k, v in b.items():
        if k == "results":
            left: Counter[str] = Counter(v)
            kept: list[str] = []
            for x in out.get(k) or []:
                if left[x] > 0:
                    left[x] -= 1
                else:
                    kept.append(x)
            out[k] = kept
        elif isinstance(v, dict):
            c: Counter[str] = Counter(out.get(k) or {})
            c.subtract(v)
            out[k] = {x: n for x, n in c.items() if n}
        elif isinstance(v, (int, float)):
            total = (out.get(k) or 0) - v
            out[k] = round(float(total), 6) if isinstance(total, float) else total
    return out


def _empty(d: Delta) -> bool:
    """Nothing in it: every number is 0, every counter and list empty."""
    for v in d.values():
        if isinstance(v, (dict, list)):
            if v:
                return False
        elif isinstance(v, (int, float)) and abs(v) > 1e-9:
            return False
    return True


def _clean(d: Delta) -> Delta:
    """Without the zero entries, so a late delta says only what changed."""
    out: Delta = {}
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            if v:
                out[k] = v
        elif isinstance(v, (int, float)) and abs(v) > 1e-9:
            out[k] = v
    return out


def is_legacy(key: EKey) -> bool:
    """A key memory-v3 no longer produces: a referee under the string the provider wrote (memory-v2). Its rows are history and
    nothing reconciles them - they are not "taken back", they were superseded by the referee's id."""
    return key[0] == "referee" and not key[1].isdigit()


def late_news(fresh: Delta | None, recorded: Delta | None) -> Delta:
    """What a day learned after its row was written: today's delta less what is already recorded for it."""
    return _clean(_minus(fresh or {}, recorded or {}))


def _merge_one(prev: dict[str, Any] | None, delta: Delta) -> dict[str, Any]:
    out: dict[str, Any] = dict(prev or {})
    for k, v in delta.items():
        if k == "results":
            out["last10"] = (list(out.get("last10") or []) + list(v))[-10:]
        elif isinstance(v, dict):
            c = Counter(out.get(k) or {})
            c.update(v)
            out[k] = {x: n for x, n in c.items() if n}
        elif isinstance(v, (int, float)):
            out[k] = round(float(out.get(k) or 0) + float(v), 6) if isinstance(v, float) else int(out.get(k) or 0) + v
    if out.get("clv_n"):
        out["clv_mean"] = round(float(out["clv_sum"]) / int(out["clv_n"]), 6)
    if out.get("settled"):
        out["hit_rate"] = round(int(out.get("wins") or 0) / int(out["settled"]), 4)
        out["roi_flat"] = round(float(out.get("profit_flat") or 0) / int(out["settled"]), 4)
    if out.get("matches"):
        if "cards" in out:
            out["cards_per_match"] = round(float(out["cards"]) / int(out["matches"]), 3)
        if "fouls" in out and out.get("fouls_matches"):
            out["fouls_per_match"] = round(float(out["fouls"]) / int(out["fouls_matches"]), 3)
        if "penalties" in out:
            out["penalties_per_match"] = round(float(out["penalties"]) / int(out["matches"]), 3)
    if out.get("reported_out"):
        out["started_anyway_rate"] = round(int(out.get("started_anyway") or 0) / int(out["reported_out"]), 4)
    return out


def merge(prev: dict[str, Any] | None, delta: Delta) -> dict[str, Any]:
    """Cumulative state: numbers add, counters add, ``results`` keeps the last ten; derived rates recomputed.
    The day's own delta first, then the news booked in it for earlier days (``delta["late"]``), oldest day first."""
    own = {k: v for k, v in delta.items() if k != LATE}
    state = _merge_one(prev, own)
    late: dict[str, Delta] = delta.get(LATE) or {}
    for day in sorted(late):
        state = _merge_one(state, late[day])
    return state


# ── age and confidence (memory-v4) ──────────────────────────────────────────────────────────────────────────────────────


def _w(field_name: str, spec: Spec) -> str:
    """Where the weighted copy of a field lives in the state: the count of evidence is ``n_eff``, the others ``w_<field>``."""
    return "n_eff" if field_name == spec.count else f"w_{field_name}"


def decay(days: float, half_life: float) -> float:
    """The weight left to a piece of evidence ``days`` old: one half after ``half_life`` days (evidence from the future counts in full)."""
    return float(0.5 ** (max(days, 0.0) / half_life))


def weights(prev: dict[str, Any] | None, prev_day: date | None, delta: Delta, day: date, spec: Spec) -> dict[str, float]:
    """The weighted evidence of a row: what the previous row had, aged by the days between the two, plus the day's own evidence at
    full weight, plus the news learned late at the weight of the day it belongs to (not of the day it was learned)."""
    fields = (spec.count, *spec.decayed)
    carried = 1.0 if prev_day is None else decay((day - prev_day).days, spec.half_life)
    out = {f: float((prev or {}).get(_w(f, spec)) or 0.0) * carried for f in fields}
    for f in fields:
        out[f] += float(delta.get(f) or 0)
    for iso, booked in (delta.get(LATE) or {}).items():
        weight = decay((day - date.fromisoformat(iso)).days, spec.half_life)
        for f in fields:
            out[f] += float(booked.get(f) or 0) * weight
    return {f: max(round(v, 6), 0.0) for f, v in out.items()}


def confidence_of(n_eff: float, k: float) -> float:
    """The effective sample over itself plus a constant: 0 with no evidence, one half at ``k``, never 1."""
    return round(n_eff / (n_eff + k), 4) if n_eff > 0 else 0.0


def settle(prev: dict[str, Any] | None, prev_day: date | None, delta: Delta, day: date,
           spec: Spec | None) -> tuple[dict[str, Any], float | None]:
    """The cumulative state of a row and its confidence: ``merge`` (the numbers add up) plus the weight of age. A kind of memory with no
    convention (``spec`` None) has a state and no confidence."""
    carried = {k: v for k, v in (prev or {}).items() if k not in DERIVED}
    state = merge(carried, delta)
    if spec is None:
        return state, None
    for f, v in weights(prev, prev_day, delta, day, spec).items():
        state[_w(f, spec)] = v
    return state, confidence_of(float(state["n_eff"]), spec.k)


def league_rate(state: dict[str, Any] | None) -> float | None:
    """A league's mean per team in a match, from its weighted evidence; None while it has none."""
    n = float((state or {}).get("n_eff") or 0)
    return None if n <= 0 else float((state or {}).get("w_total") or 0) / (2 * n)


def prior_of(by_competition: dict[str, int], leagues: dict[str, dict[str, Any]]) -> tuple[float | None, int]:
    """The mean a team is shrunk to: the means of the leagues it played in, each weighted by its matches there, and how many of its
    matches have a mean to be shrunk to (a league with no evidence yet counts for nothing)."""
    total = weight = 0.0
    for competition, n in by_competition.items():
        rate = league_rate(leagues.get(competition))
        if rate is None or n <= 0:
            continue
        total += n * rate
        weight += n
    return (total / weight, int(weight)) if weight else (None, 0)


def figures(state: dict[str, Any], aspect: str, leagues: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a row of corners, cards or xG says once its state is known, computed again each time: a team's figure per match as it is
    (weighted by age) and shrunk toward its league's; a league's mean per team in a match."""
    n = float(state.get("n_eff") or 0)
    if n <= 0:
        return {}
    if "w_total" in state:
        return {"rate": round(float(state["w_total"]) / (2 * n), 4)}
    own, opp = float(state.get("w_own") or 0), float(state.get("w_opp") or 0)
    out: dict[str, Any] = {"own_rate": round(own / n, 4), "opp_rate": round(opp / n, 4)}
    prior, covered = prior_of(state.get("by_competition") or {}, leagues)
    if prior is not None:
        m = METRICS[aspect].prior_weight
        out |= {"prior": round(prior, 4), "prior_matches": covered, "own_shrunk": round((own + m * prior) / (n + m), 4),
                "opp_shrunk": round((opp + m * prior) / (n + m), 4)}
    return out


def rests_on_decisions(key: EKey) -> bool:
    """Do the ``sources`` of this kind of row name decisions (the team's, the league's and the market's rows of the decision layer) or
    matches (everything else)?"""
    return key[2].startswith("market:") or key[0] == "market"


def evidence_ref(key: EKey, sources: list[int], postmortems: list[int]) -> dict[str, list[int]]:
    """What a row rests on, by kind, newest first (a sample: the first ``MAX_SOURCES``): the decisions and the post-mortems that judged
    them, or the matches. The ids are the ones the day's rows name as ``sources``."""
    if rests_on_decisions(key):
        out: dict[str, list[int]] = {"decisions": sorted(set(sources), reverse=True)[:MAX_SOURCES]}
        if postmortems:
            out["postmortems"] = sorted(set(postmortems), reverse=True)[:MAX_SOURCES]
        return out
    return {"fixtures": sorted(set(sources), reverse=True)[:MAX_SOURCES]}


def _without_late(delta: Delta) -> Delta:
    return {k: v for k, v in delta.items() if k != LATE}


def _late_for(conn: psycopg.Connection[Any], start: date, before: date, days: list[date]) -> dict[date, dict[EKey, tuple[Delta, set[int]]]]:
    """What is recorded for each of ``days``: per day and entity x aspect, the delta (its own row's plus the late news
    booked for it in later rows, all before ``before``) and the sources already named."""
    out: dict[date, dict[EKey, tuple[Delta, set[int]]]] = {d: {} for d in days}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RECORDED_SQL, {"from": start, "before": before, "version": VERSION})
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        key = (str(r["entity_type"]), str(r["entity_id"]), str(r["aspect"]))
        delta: Delta = dict(r["delta"] or {})
        srcs = {int(x) for x in (r["sources"] or []) if isinstance(x, int)}
        if r["as_of_day"] in out:
            have, seen = out[r["as_of_day"]].get(key, ({}, set()))
            out[r["as_of_day"]][key] = (_plus(have, _without_late(delta)), seen | srcs)
        for iso, booked in (delta.get(LATE) or {}).items():
            d = date.fromisoformat(iso)
            if d in out:
                have, seen = out[d].get(key, ({}, set()))
                out[d][key] = (_plus(have, booked), seen | srcs)
    return out


def _states(conn: psycopg.Connection[Any], sql: str, keys: list[EKey], day: date) -> dict[EKey, tuple[date, dict[str, Any]]]:
    """The latest state of each key of this version (before the day, or up to it), with the day of the row that holds it."""
    if not keys:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"version": VERSION, "types": [k[0] for k in keys], "ids": [k[1] for k in keys],
                          "aspects": [k[2] for k in keys], "day": day})
        return {(str(r["entity_type"]), str(r["entity_id"]), str(r["aspect"])): (r["as_of_day"], dict(r["stats"] or {}))
                for r in cur.fetchall()}


def lineage_started(conn: psycopg.Connection[Any], day: date) -> bool:
    """Is there a row of this version before ``day``? The nightly step builds on one: a night that began the lineage by itself would
    give every entity a state that forgets the days between ``LINEAGE_START`` and itself."""
    with conn.cursor() as cur:
        cur.execute(STARTED_SQL, {"version": VERSION, "day": day})
        row = cur.fetchone()
    return bool(row and row[0])


def build_memory(conn: psycopg.Connection[Any], *, day: date, at: datetime, late_days: int = LATE_DAYS) -> int:
    """Write the day's memory rows (idempotent) and book in them what the ``late_days`` before it learned late.
    Returns how many rows were written. An entity that already has a row for ``day`` is left as it is."""
    deltas, names, sources = day_deltas(conn, day)
    days = [day - timedelta(days=n) for n in range(late_days, 0, -1)]
    recorded = _late_for(conn, days[0], day, days) if days else {}
    late: dict[EKey, dict[str, Delta]] = defaultdict(dict)
    late_ids: dict[EKey, list[int]] = defaultdict(list)
    for d0 in days:
        fresh, fnames, fsources = day_deltas(conn, d0)
        have = recorded.get(d0, {})
        for key in sorted({*fresh, *have}):
            if is_legacy(key):
                continue
            news = late_news(fresh.get(key), have.get(key, ({}, set()))[0])
            if _empty(news):
                continue
            late[key][d0.isoformat()] = news
            names.setdefault(key, fnames.get(key, ""))
            every = fsources.get(key, [])
            # What the news rests on: the sources the row of that day did not name; when it named them all (a statistic
            # arrived for a match it already had), the news is about one of them and the row names every one.
            late_ids[key].extend([i for i in every if i not in have.get(key, ({}, set()))[1]] or every)
            deltas.setdefault(key, {})
    for key, booked in late.items():
        deltas[key] = {**deltas[key], LATE: booked}
        ids = list(dict.fromkeys(late_ids[key]))
        own = [i for i in sources.get(key, []) if i not in ids]
        sources[key] = [*own[: max(MAX_SOURCES - len(ids), 0)], *ids]

    if not deltas:
        return 0
    with conn.cursor() as cur:
        cur.execute(WRITTEN_SQL, {"day": day, "version": VERSION})
        written = {(str(a), str(b), str(c)) for a, b, c in cur.fetchall()}
    keys = [k for k in deltas if k not in written]
    if not keys:
        return 0

    previous = _states(conn, PREVIOUS_SQL, keys, day)
    states: dict[EKey, dict[str, Any]] = {}
    confidence: dict[EKey, float | None] = {}
    for k in keys:
        before = previous.get(k)
        states[k], confidence[k] = settle(None if before is None else before[1], None if before is None else before[0],
                                          deltas[k], day, spec_for(k))
    # The teams' figures are shrunk to their leagues': the leagues written today are in ``states``, the ones that did not play today
    # (or already have their row) are the latest row of the lineage, today's included.
    leagues: dict[str, dict[str, dict[str, Any]]] = {a: {} for a in METRICS}
    wanted: dict[EKey, None] = {}
    for k, state in states.items():
        if k[0] == "team" and k[2] in METRICS:
            for competition in state.get("by_competition") or {}:
                league = ("competition", str(competition), k[2])
                if league in states:
                    leagues[k[2]][str(competition)] = states[league]
                else:
                    wanted[league] = None
    for k, (_, state) in _states(conn, CURRENT_SQL, list(wanted), day).items():
        leagues[k[2]][k[1]] = state
    for k, state in states.items():
        if k[2] in METRICS and k[0] in ("team", "competition"):
            state |= figures(state, k[2], leagues[k[2]])

    decisions = [i for k in keys if rests_on_decisions(k) for i in sources.get(k, [])]
    judged: dict[int, int] = {}
    if decisions:
        with conn.cursor() as cur:
            cur.execute(POSTMORTEMS_SQL, {"decisions": sorted(set(decisions))})
            judged = {int(a): int(b) for a, b in cur.fetchall()}
    n = 0
    with conn.cursor() as cur:
        for k in keys:
            ids = sources.get(k, [])[:MAX_SOURCES]
            evidence = evidence_ref(k, ids, [judged[i] for i in ids if i in judged])
            cur.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, "
                        "built_at, version, stats, delta, sources, confidence, evidence_ref) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (entity_type, entity_id, aspect, as_of_day, version) DO NOTHING",
                        (k[0], k[1], names.get(k), k[2], day, at, VERSION, Jsonb(states[k]), Jsonb(deltas[k]), Jsonb(ids),
                         confidence[k], Jsonb(evidence)))
            n += max(cur.rowcount, 0)
    return n


# ── the lineage: built from its first day, day by day ───────────────────────────────────────────────────────────────────


@dataclass
class RebuildReport:
    days: int = 0
    rows: int = 0
    first: date | None = None
    last: date | None = None
    by_day: dict[date, int] = field(default_factory=dict)
    stopped: str | None = None
    """Why it stopped before ``end``: ``time`` (the budget given ran out); None when it reached ``end``."""


def rebuild(conn: psycopg.Connection[Any], *, start: date, end: date, at: datetime, commit: Callable[[], None] | None = None,
            max_seconds: float | None = None, clock: Callable[[], float] = time.monotonic) -> RebuildReport:
    """Build the memory of every day from ``start`` to ``end`` (both included), oldest first, each day on the rows of the days before
    it. Idempotent and resumable: a day that is written is skipped, so a run that stopped (``max_seconds``) is continued by running it
    again. There is no late news to book - every day is built from the data as they are now - so ``late_days`` is 0, and ``commit``
    (the CLI's ``conn.commit``) makes each day durable before the next begins."""
    report = RebuildReport()
    began = clock()
    day = start
    while day <= end:
        if max_seconds is not None and report.days and clock() - began > max_seconds:
            report.stopped = "time"
            break
        rows = build_memory(conn, day=day, at=at, late_days=0)
        if commit is not None:
            commit()
        report.days += 1
        report.rows += rows
        report.by_day[day] = rows
        report.first = report.first or day
        report.last = day
        day += timedelta(days=1)
    return report
