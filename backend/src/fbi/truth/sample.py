"""Which entities the truth audit asks the provider about.

A sample, stratified so no kind of football is left out: every segment of
``fbi.catalog.segments`` (top leagues, other leagues, domestic cups, continental club
competitions, club friendlies, national teams, women's and youth football), and
within each, matches just played, matches about to be played and matches from past
seasons. Random within a stratum, with the seed recorded, so a run can be repeated
on the same rows.

The fixture lists themselves are not sampled: every current season's full list is
compared (one request per season), because a missing fixture can only be found by
looking at all of them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.catalog.segments import CompetitionFacts, Segment, segment_of


@dataclass(frozen=True, slots=True)
class SampleSize:
    recent_finished: int = 6
    upcoming: int = 4
    historical: int = 4
    historical_seasons: int = 3
    """Past competition-seasons per segment whose full fixture list is compared."""
    standings_seasons: int = 0
    """0 = every current league season."""
    teams: int = 6
    players: int = 8
    coaches: int = 3
    squads: int = 3


@dataclass
class Sample:
    seed: float
    segments: dict[int, str] = field(default_factory=dict)
    """competition id -> segment."""
    detail_fixtures: list[int] = field(default_factory=list)
    """Provider fixture ids compared field by field, detail included (/fixtures?ids=)."""
    upcoming_fixtures: list[int] = field(default_factory=list)
    """Provider fixture ids whose odds and injuries are compared."""
    current_seasons: list[tuple[int, int]] = field(default_factory=list)
    """(provider league, season) whose whole fixture list is compared."""
    historical_seasons: list[tuple[int, int]] = field(default_factory=list)
    standings_seasons: list[tuple[int, int]] = field(default_factory=list)
    teams: list[int] = field(default_factory=list)
    players: list[tuple[int, int]] = field(default_factory=list)
    """(provider player id, season)."""
    coaches: list[int] = field(default_factory=list)
    squads: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed, "segments": {str(k): v for k, v in self.segments.items()},
            "detail_fixtures": self.detail_fixtures, "upcoming_fixtures": self.upcoming_fixtures,
            "current_seasons": self.current_seasons, "historical_seasons": self.historical_seasons,
            "standings_seasons": self.standings_seasons, "teams": self.teams, "players": self.players,
            "coaches": self.coaches, "squads": self.squads,
        }


COMPETITIONS_SQL = """
SELECT c.id, c.provider_league_id, c.name, c.competition_type, c.entity_scope, c.tier, c.type
  FROM core.competitions c WHERE c.is_tracked ORDER BY c.id
"""

FIXTURES_SQL = """
SELECT f.provider_fixture_id, cs.competition_id, f.kickoff_at, f.status_group, cs.is_current
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE cs.competition_id = ANY(%(comps)s)
   AND (   (f.status_group = 'finished' AND f.kickoff_at BETWEEN %(at)s - interval '7 days' AND %(at)s)
        OR (f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %(at)s AND %(at)s + interval '7 days')
        OR (f.status_group = 'finished' AND NOT cs.is_current))
"""

SEASONS_SQL = """
SELECT c.id AS competition_id, c.provider_league_id, cs.season, cs.is_current, c.type,
       EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = cs.id) AS has_fixtures
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked
"""

TEAMS_SQL = """
SELECT DISTINCT t.provider_team_id, cs.competition_id
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
 WHERE cs.is_current AND cs.competition_id = ANY(%(comps)s)
"""

PLAYERS_SQL = """
SELECT DISTINCT ON (ps.provider_player_id) ps.provider_player_id, cs.season, cs.competition_id
  FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.kickoff_at > %(at)s - interval '60 days' AND ps.provider_player_id > 0 AND COALESCE(ps.minutes, 0) > 0
   AND cs.competition_id = ANY(%(comps)s)
 ORDER BY ps.provider_player_id, f.kickoff_at DESC
"""

COACHES_SQL = """
SELECT DISTINCT l.provider_coach_id, cs.competition_id
  FROM core.fixture_lineups l
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.kickoff_at > %(at)s - interval '60 days' AND l.provider_coach_id > 0
   AND cs.competition_id = ANY(%(comps)s)
"""


def _pick(rng: random.Random, items: list[Any], n: int) -> list[Any]:
    if n <= 0 or not items:
        return []
    return rng.sample(items, min(n, len(items)))


DEFAULT_SIZE = SampleSize()


def draw(conn: psycopg.Connection, *, at: datetime, seed: float, size: SampleSize = DEFAULT_SIZE) -> Sample:
    rng = random.Random(seed)
    sample = Sample(seed=seed)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COMPETITIONS_SQL)
        comps = cur.fetchall()
        for c in comps:
            sample.segments[int(c["id"])] = segment_of(CompetitionFacts(
                str(c["name"]), c["competition_type"], c["entity_scope"], c["tier"])).value
        by_segment: dict[str, list[int]] = {}
        for cid, seg in sample.segments.items():
            by_segment.setdefault(seg, []).append(cid)
        all_comps = list(sample.segments)

        cur.execute(FIXTURES_SQL, {"comps": all_comps, "at": at})
        fixtures = cur.fetchall()
        cur.execute(SEASONS_SQL)
        seasons = cur.fetchall()
        cur.execute(TEAMS_SQL, {"comps": all_comps})
        teams = cur.fetchall()
        cur.execute(PLAYERS_SQL, {"comps": all_comps, "at": at})
        players = cur.fetchall()
        cur.execute(COACHES_SQL, {"comps": all_comps, "at": at})
        coaches = cur.fetchall()

    for seg in Segment:
        ids = set(by_segment.get(seg.value, []))
        if not ids:
            continue
        mine = [f for f in fixtures if f["competition_id"] in ids]
        recent = [f["provider_fixture_id"] for f in mine if f["status_group"] == "finished" and f["kickoff_at"] <= at
                  and f["is_current"]]
        upcoming = [f["provider_fixture_id"] for f in mine if f["status_group"] == "scheduled"]
        old = [f["provider_fixture_id"] for f in mine if f["status_group"] == "finished" and not f["is_current"]]
        sample.detail_fixtures += _pick(rng, recent, size.recent_finished) + _pick(rng, old, size.historical)
        sample.upcoming_fixtures += _pick(rng, upcoming, size.upcoming)
        past = [(int(s["provider_league_id"]), int(s["season"])) for s in seasons
                if s["competition_id"] in ids and not s["is_current"] and s["has_fixtures"]]
        sample.historical_seasons += _pick(rng, past, size.historical_seasons)
        sample.teams += _pick(rng, sorted({int(t["provider_team_id"]) for t in teams if t["competition_id"] in ids}),
                              size.teams)
        sample.players += _pick(rng, sorted({(int(p["provider_player_id"]), int(p["season"])) for p in players
                                             if p["competition_id"] in ids}), size.players)
        sample.coaches += _pick(rng, sorted({int(c["provider_coach_id"]) for c in coaches
                                             if c["competition_id"] in ids}), size.coaches)
    sample.current_seasons = sorted({(int(s["provider_league_id"]), int(s["season"])) for s in seasons
                                     if s["is_current"]})
    leagues = sorted({(int(s["provider_league_id"]), int(s["season"])) for s in seasons
                      if s["is_current"] and s["type"] == "league" and s["has_fixtures"]})
    sample.standings_seasons = leagues if size.standings_seasons <= 0 else _pick(rng, leagues, size.standings_seasons)
    sample.squads = _pick(rng, sample.teams, size.squads * 4)
    sample.detail_fixtures = sorted(set(sample.detail_fixtures))
    sample.upcoming_fixtures = sorted(set(sample.upcoming_fixtures))
    return sample
