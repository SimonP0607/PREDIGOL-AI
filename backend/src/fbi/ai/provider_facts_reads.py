"""The reads of the provider's facts (IA-128, AD-C10): what API-Football already gave PrediGol about a set of matches - line-ups, injury
report history, events and coverage - read back from ``core.*`` and ``raw.league_coverage``. Read only: every statement is a SELECT.

No request reaches the provider: what is read is what the ingestion already stored (15.192 calls a day of 60.000 on 16-nov-2026; this
adds none). ``ai.evidence`` is not read here (the replay against today's statuses reads it in ``fbi.ai.unified_readers``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import provider_facts as pf

FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, th.provider_team_id AS home_provider_id, ta.provider_team_id AS away_provider_id,
       c.provider_league_id, cs.season, c.name AS competition, f.competition_season_id
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = ANY(%(fixtures)s)
"""
WINDOW_SQL: Final = "SELECT f.id FROM core.fixtures f WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s ORDER BY f.kickoff_at, f.id LIMIT %(limit)s"
LINEUPS_SQL: Final = """
SELECT l.fixture_id, l.team_side, l.source, l.fetched_at, l.first_seen_at,
       (SELECT min(a.observed_at) FROM core.fixture_lineup_arrivals a
         WHERE a.fixture_id = l.fixture_id AND a.team_side = l.team_side AND a.source = l.source AND a.starters > 0) AS arrived_at,
       COALESCE(array_agg(lp.provider_player_id ORDER BY lp.provider_player_id) FILTER (WHERE lp.is_starter), '{}') AS starters,
       COALESCE(array_agg(lp.provider_player_id ORDER BY lp.provider_player_id) FILTER (WHERE NOT lp.is_starter), '{}') AS bench
  FROM core.fixture_lineups l
  LEFT JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side AND lp.source = l.source
 WHERE l.fixture_id = ANY(%(fixtures)s)
 GROUP BY l.fixture_id, l.team_side, l.source, l.fetched_at, l.first_seen_at
"""
OBS_SQL: Final = """
SELECT o.fixture_id, o.provider_player_id, o.provider_team_id, o.observed_at, o.status, o.absence_type, o.reason
  FROM core.player_availability_obs o
 WHERE o.fixture_id = ANY(%(fixtures)s) AND o.source = 'api-football'
 ORDER BY o.fixture_id, o.provider_player_id, o.observed_at
"""
"""The reason is read to tell a suspension from an injury (``provider_facts.absence_type_of``) and dropped there: no fact keeps it."""
EVENTS_SQL: Final = """
SELECT e.fixture_id, e.seq, e.minute, e.extra_minute, e.team_side, e.provider_player_id, e.event_type, e.detail, e.fetched_at
  FROM core.fixture_events e WHERE e.fixture_id = ANY(%(fixtures)s) ORDER BY e.fixture_id, e.seq
"""
COVERAGE_SQL: Final = """
SELECT provider_league_id, season, injuries, lineups, events, observed_at FROM raw.league_coverage
 WHERE provider = 'api_football' AND (provider_league_id, season) IN (SELECT l, s FROM unnest(%(leagues)s::int[], %(seasons)s::int[]) AS u(l, s))
"""
BATCH: Final = 200
MAX_FIXTURES: Final = 6000


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET LOCAL statement_timeout = '90s'")
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def fixtures_between(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> list[int]:
    return [int(r["id"]) for r in _rows(conn, WINDOW_SQL, {"start": start, "end": end, "limit": MAX_FIXTURES})]


def facts_for(conn: psycopg.Connection[Any], fixtures: Sequence[int]) -> tuple[pf.Made, dict[int, dict[str, Any]]]:
    """Every fact of the provider about these matches (all of them, whenever they were known: ``provider_facts.as_of`` cuts them), and
    per match its coverage as facts."""
    made = pf.Made()
    coverage: dict[int, dict[str, Any]] = {}
    ids = sorted(set(fixtures))
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        params = {"fixtures": chunk}
        matches = {int(r["id"]): r for r in _rows(conn, FIXTURES_SQL, params)}
        lineups = _rows(conn, LINEUPS_SQL, params)
        obs = _rows(conn, OBS_SQL, params)
        events = _rows(conn, EVENTS_SQL, params)
        pairs = sorted({(int(m["provider_league_id"]), int(m["season"])) for m in matches.values() if m["provider_league_id"] is not None})
        cov = {(int(r["provider_league_id"]), int(r["season"])): r for r in
               (_rows(conn, COVERAGE_SQL, {"leagues": [p[0] for p in pairs], "seasons": [p[1] for p in pairs]}) if pairs else [])}
        obs_by: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for o in obs:
            obs_by[int(o["fixture_id"])].append(o)
        ev_by: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for e in events:
            ev_by[int(e["fixture_id"])].append(e)
        for lu in lineups:
            m = matches.get(int(lu["fixture_id"]))
            if m is None:
                continue
            seen, known_from = ((lu["arrived_at"], "arrival") if lu["arrived_at"] is not None else
                                (lu["first_seen_at"], "first_seen_at") if lu["first_seen_at"] is not None else (lu["fetched_at"], "fetched_at"))
            team = m["home_team_id"] if lu["team_side"] == "home" else m["away_team_id"]
            players = [(int(p), True) for p in lu["starters"] or [] if p is not None] + [(int(p), False) for p in lu["bench"] or [] if p is not None]
            pf.lineup_facts(made, fixture_id=int(m["id"]), kickoff_at=m["kickoff_at"], team_id=int(team), side=str(lu["team_side"]),
                            players=players, seen_at=seen, known_from=known_from)
        for fid, m in matches.items():
            team_of = {int(m["home_provider_id"]): int(m["home_team_id"]), int(m["away_provider_id"]): int(m["away_team_id"])}
            pf.injury_facts(made, fixture_id=fid, kickoff_at=m["kickoff_at"], team_of=team_of, observations=obs_by.get(fid, []))
            pf.event_facts(made, fixture_id=fid, kickoff_at=m["kickoff_at"], team_of={"home": int(m["home_team_id"]), "away": int(m["away_team_id"])},
                           events=ev_by.get(fid, []))
            row = cov.get((int(m["provider_league_id"]), int(m["season"]))) if m["provider_league_id"] is not None else None
            coverage[fid] = {"competition": m["competition"], "league": m["provider_league_id"], "season": m["season"],
                             "coverage": pf.coverage_facts(row)}
    return made, coverage


def coverage_by_competition(coverage: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """The coverage of the competitions of a set of matches, one line each, with how many of the matches it covers."""
    out: dict[tuple[Any, Any], dict[str, Any]] = {}
    for c in coverage.values():
        key = (c["league"], c["season"])
        line = out.setdefault(key, {"competition": c["competition"], "league": c["league"], "season": c["season"], "matches": 0,
                                    **{ds: c["coverage"][ds]["state"] for ds in pf.COVERAGE_DATASETS},
                                    "means": [v["means"] for v in c["coverage"].values() if v["means"]]})
        line["matches"] += 1
    return sorted(out.values(), key=lambda x: (-x["matches"], str(x["competition"])))
