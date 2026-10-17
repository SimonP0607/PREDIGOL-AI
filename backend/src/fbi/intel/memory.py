"""Longitudinal memory - ``memory-v1``: what PrediGol Intelligence has seen of each team, competition, referee, coach,
player and market, accumulated day by day (``intel.entity_memory``, append-only).

One row per entity x aspect x Bogotá day, written only when something of it happened that day; each row carries the
CUMULATIVE state as of that day (the previous row + the day's delta) and the day's delta, and names the decisions and
matches it rests on. History is never rewritten: yesterday's row stays as it was written.

    team x market:<key>           decisions (INVESTIGACION or better) on its matches, by selection; settled, wins,
                                  losses, flat profit, closing-line value, post-mortem verdicts, the last ten results
    competition x market:<key>    the same per competition
    market x decisions            the same per market, every competition
    referee x discipline          matches, cards (yellow + red), fouls, penalties, cards shown to home / away sides
    coach x profile               matches, formations used, wins / draws / losses, goals for / against
    player x availability         times reported out by the provider, and how often he started anyway

A streak (``last10``) is a signal to investigate, never a rule: nothing here changes a model, a filter or a pick.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds

VERSION = "memory-v1"
MAX_SOURCES = 40

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
  LEFT JOIN intel.postmortems pm ON pm.decision_id = l.id
 WHERE l.state <> 'RECHAZADO'
"""

MATCHES_SQL = """
SELECT f.id AS fixture_id, f.home_team_id, f.away_team_id, ff.referee,
       COALESCE(r.reg_goals_home, r.goals_home) AS gh, COALESCE(r.reg_goals_away, r.goals_away) AS ga
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  LEFT JOIN core.fixture_facts_latest ff ON ff.fixture_id = f.id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND f.status_group = 'finished'
   AND (%(fixtures)s::bigint[] IS NULL OR f.id = ANY(%(fixtures)s))
"""

STATS_SQL = """
SELECT DISTINCT ON (fixture_id, team_side) fixture_id, team_side, yellow_cards, red_cards, fouls
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

PREVIOUS_SQL = """
SELECT DISTINCT ON (entity_type, entity_id, aspect) entity_type, entity_id, aspect, stats
  FROM intel.entity_memory
 WHERE (entity_type, entity_id, aspect) IN (SELECT * FROM unnest(%(types)s::text[], %(ids)s::text[], %(aspects)s::text[]))
   AND as_of_day < %(day)s AND version = %(version)s
 ORDER BY entity_type, entity_id, aspect, as_of_day DESC
"""

Delta = dict[str, Any]
EKey = tuple[str, str, str]


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


def merge(prev: dict[str, Any] | None, delta: Delta) -> dict[str, Any]:
    """Cumulative state: numbers add, counters add, ``results`` keeps the last ten; derived rates recomputed."""
    out: dict[str, Any] = dict(prev or {})
    for k, v in delta.items():
        if k == "results":
            out["last10"] = (list(out.get("last10") or []) + list(v))[-10:]
        elif isinstance(v, dict):
            c = Counter(out.get(k) or {})
            c.update(v)
            out[k] = dict(c)
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


def build_memory(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> int:
    """Write the day's memory rows (idempotent). Returns how many were written."""
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
        ref = m.get("referee")
        if ref:
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
            names[k] = str(ref)
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

    if not deltas:
        return 0
    keys = list(deltas)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PREVIOUS_SQL, {"types": [k[0] for k in keys], "ids": [k[1] for k in keys],
                                   "aspects": [k[2] for k in keys], "day": day, "version": VERSION})
        previous = {(str(r["entity_type"]), str(r["entity_id"]), str(r["aspect"])): dict(r["stats"] or {})
                    for r in cur.fetchall()}
    n = 0
    with conn.cursor() as cur:
        for k in keys:
            delta = deltas[k]
            state = merge(previous.get(k), delta)
            cur.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, "
                        "built_at, version, stats, delta, sources) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (entity_type, entity_id, aspect, as_of_day, version) DO NOTHING",
                        (k[0], k[1], names.get(k), k[2], day, at, VERSION, Jsonb(state), Jsonb(delta),
                         Jsonb(sources[k][:MAX_SOURCES])))
            n += max(cur.rowcount, 0)
    return n
