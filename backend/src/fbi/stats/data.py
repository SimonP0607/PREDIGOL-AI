"""What one competition season gives the statistics documents (plan EA): the finished matches with their settled numbers, the team
statistics the outcome view does not carry, the goals and cards with their minute, and the players' sheets. Read once per competition
season (``load_season``), then computed in memory (``fbi.stats.team``, ``fbi.stats.player``).

Every count comes from ``market.fixture_outcomes`` - the numbers the settlement rules of IA-070 read - so «more than 9.5 corners» means
the same thing here as in a settled bet. xG, possession and passes, which no rule reads, come from ``core.fixture_team_stats``
(API-Football). A NULL stays None: never a 0.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

OUTCOME_COLUMNS: Final = (
    "goals_ft_home", "goals_ft_away", "goals_1h_home", "goals_1h_away", "goals_2h_home", "goals_2h_away",
    "corners_ft_home", "corners_ft_away", "shots_ft_home", "shots_ft_away", "shots_on_target_ft_home", "shots_on_target_ft_away",
    "fouls_ft_home", "fouls_ft_away", "saves_ft_home", "saves_ft_away", "yellow_ft_home", "yellow_ft_away", "red_ft_home",
    "red_ft_away", "cards_lines_ft_home", "cards_lines_ft_away",
)

SEASONS_SQL: Final = """
SELECT cs.id, cs.season, c.id AS competition_id, c.name AS competition_name, c.country, c.type, c.competition_type,
       count(o.fixture_id) AS finished
  FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN market.fixture_outcomes o ON o.competition_season_id = cs.id AND o.goals_ft_home IS NOT NULL
 WHERE cs.is_current AND c.type <> 'friendly'
 GROUP BY cs.id, cs.season, c.id, c.name, c.country, c.type, c.competition_type
HAVING count(o.fixture_id) >= %(min_matches)s
 ORDER BY count(o.fixture_id) DESC, cs.id
"""

MATCHES_SQL: Final = f"""
SELECT o.fixture_id, o.kickoff_at, f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name,
       COALESCE(o.extra_time, false) AS extra_time, {", ".join("o." + c for c in OUTCOME_COLUMNS)}
  FROM market.fixture_outcomes o
  JOIN core.fixtures f ON f.id = o.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE o.competition_season_id = %(cs)s AND o.goals_ft_home IS NOT NULL AND o.goals_ft_away IS NOT NULL
 ORDER BY o.kickoff_at, o.fixture_id
"""

TEAM_STATS_SQL: Final = """
SELECT fixture_id, team_side, expected_goals, possession_pct, passes, passes_accurate, offsides, goals_prevented
  FROM core.fixture_team_stats
 WHERE fixture_id = ANY(%(fixtures)s) AND source = 'api-football'
"""

EVENTS_SQL: Final = """
SELECT fixture_id, seq, minute, extra_minute, team_side, event_type, detail, COALESCE(comments, '') AS comments
  FROM core.fixture_events
 WHERE fixture_id = ANY(%(fixtures)s) AND source = 'api-football' AND event_type IN ('Goal', 'Card')
 ORDER BY fixture_id, seq
"""

CLOSING_SQL: Final = """
SELECT DISTINCT ON (c.fixture_id, c.selection) c.fixture_id, c.selection, c.p_fair
  FROM market.market_consensus c JOIN core.fixtures f ON f.id = c.fixture_id
 WHERE c.fixture_id = ANY(%(fixtures)s) AND c.market_key = '1X2' AND c.line = 0 AND c.devig_method = 'shin'
       AND c.as_of < f.kickoff_at
 ORDER BY c.fixture_id, c.selection, c.as_of DESC
"""
"""The closing consensus of the result (without margin, Shin): who was the favourite."""

PLAYERS_SQL: Final = """
SELECT ps.fixture_id, f.kickoff_at, ps.provider_player_id, ps.team_side, ps.minutes, COALESCE(ps.is_substitute, false) AS substitute,
       ps.goals, ps.assists, ps.shots_total, ps.shots_on, ps.passes_total, ps.passes_key, ps.passes_accuracy_pct, ps.tackles,
       ps.blocks, ps.interceptions, ps.duels_total, ps.duels_won, ps.dribbles_attempts, ps.dribbles_success, ps.fouls_drawn,
       ps.fouls_committed, ps.yellow_cards, ps.red_cards, ps.saves, ps.goals_conceded,
       lp.position AS sheet_position, lp.is_starter, p.id AS player_id, p.name AS player_name, p.position AS profile_position
  FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.players p ON p.provider_player_id = ps.provider_player_id
  LEFT JOIN core.fixture_lineup_players lp
         ON lp.fixture_id = ps.fixture_id AND lp.team_side = ps.team_side AND lp.source = 'api-football'
        AND lp.provider_player_id = ps.provider_player_id
 WHERE f.competition_season_id = %(cs)s AND ps.source = 'api-football' AND ps.minutes > 0
       AND ps.fixture_id = ANY(%(fixtures)s)
 ORDER BY f.kickoff_at, ps.fixture_id
"""


@dataclass(frozen=True, slots=True)
class Season:
    id: int
    season: int
    competition_id: int
    competition_name: str
    country: str | None
    finished: int


@dataclass(frozen=True, slots=True)
class Event:
    minute: int
    extra: int | None
    side: str | None
    kind: str
    detail: str
    comments: str


@dataclass(slots=True)
class Match:
    fixture_id: int
    kickoff_at: datetime
    home_id: int
    away_id: int
    home_name: str
    away_name: str
    extra_time: bool
    numbers: dict[str, int | None]
    team_stats: dict[str, dict[str, float | None]] = field(default_factory=dict)
    events: list[Event] | None = None
    """None: the provider gave no list of events for the match."""
    closing: dict[str, float] = field(default_factory=dict)
    """The closing consensus of the result: Home, Draw, Away (empty: no consensus before the kick-off)."""


@dataclass(frozen=True, slots=True)
class PlayerLine:
    fixture_id: int
    kickoff_at: datetime
    player_id: int
    player_name: str
    team_side: str
    minutes: int
    starter: bool
    position: str | None
    """G, D, M or F from the sheet; None when the sheet did not say."""
    profile_position: str | None
    counts: dict[str, float | None]


@dataclass(slots=True)
class SeasonData:
    season: Season
    matches: list[Match]
    players: list[PlayerLine]


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def seasons(conn: psycopg.Connection[Any], *, min_matches: int) -> list[Season]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SEASONS_SQL, {"min_matches": min_matches})
        return [Season(int(r["id"]), int(r["season"]), int(r["competition_id"]), str(r["competition_name"]),
                       r["country"], int(r["finished"])) for r in cur.fetchall()]


PLAYER_EXTRAS_SQL: Final = """
SELECT DISTINCT ON (fixture_id, provider_player_id) fixture_id, provider_player_id, offsides, dribbled_past, penalties_won,
       penalties_committed, penalties_saved
  FROM core.fixture_player_extras
 WHERE fixture_id = ANY(%(fixtures)s)
 ORDER BY fixture_id, provider_player_id, observed_at DESC
"""
"""The latest extras of each player and match (plan PM, PM-05-05): read only with ``FBI_STATS_PROVIDER_EXTRAS`` on (``fbi.stats.extras``)."""

PLAYER_COUNTS: Final = (
    "goals", "assists", "shots_total", "shots_on", "passes_total", "passes_key", "passes_accuracy_pct", "tackles", "blocks",
    "interceptions", "duels_total", "duels_won", "dribbles_attempts", "dribbles_success", "fouls_drawn", "fouls_committed",
    "yellow_cards", "red_cards", "saves", "goals_conceded",
)
EXTRA_COUNTS: Final = ("offsides", "dribbled_past", "penalties_won", "penalties_committed", "penalties_saved")
"""``fbi.stats.extras.PLAYER_COLUMNS`` (a test keeps them equal: the data layer does not import the documents')."""


def load_season(conn: psycopg.Connection[Any], season: Season, *, extras: bool = False) -> SeasonData:
    """One competition season, read once. ``extras`` (``FBI_STATS_PROVIDER_EXTRAS``, PM-05-05): each player line also carries his
    extras of the match (``fbi.stats.extras.PLAYER_COLUMNS``; absent when the provider sent none)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MATCHES_SQL, {"cs": season.id})
        matches = [Match(int(r["fixture_id"]), r["kickoff_at"], int(r["home_team_id"]), int(r["away_team_id"]), str(r["home_name"]),
                         str(r["away_name"]), bool(r["extra_time"]),
                         {c: (None if r[c] is None else int(r[c])) for c in OUTCOME_COLUMNS}) for r in cur.fetchall()]
        by_id = {m.fixture_id: m for m in matches}
        fixtures = list(by_id)
        if not fixtures:
            return SeasonData(season, [], [])
        cur.execute(TEAM_STATS_SQL, {"fixtures": fixtures})
        for r in cur.fetchall():
            by_id[int(r["fixture_id"])].team_stats[str(r["team_side"])] = {
                "xg": _num(r["expected_goals"]), "possession": _num(r["possession_pct"]), "passes": _num(r["passes"]),
                "passes_accurate": _num(r["passes_accurate"]), "offsides": _num(r["offsides"]),
                "goals_prevented": _num(r["goals_prevented"])}
        events: dict[int, list[Event]] = defaultdict(list)
        cur.execute(EVENTS_SQL, {"fixtures": fixtures})
        for r in cur.fetchall():
            events[int(r["fixture_id"])].append(Event(int(r["minute"]), None if r["extra_minute"] is None else int(r["extra_minute"]),
                                                      r["team_side"], str(r["event_type"]), str(r["detail"] or ""),
                                                      str(r["comments"])))
        for fid, evs in events.items():
            by_id[fid].events = evs
        cur.execute(CLOSING_SQL, {"fixtures": fixtures})
        for r in cur.fetchall():
            by_id[int(r["fixture_id"])].closing[str(r["selection"])] = float(r["p_fair"])
        extra: dict[tuple[int, int], dict[str, float | None]] = {}
        if extras:
            cur.execute(PLAYER_EXTRAS_SQL, {"fixtures": fixtures})
            extra = {(int(r["fixture_id"]), int(r["provider_player_id"])): {c: _num(r[c]) for c in EXTRA_COUNTS}
                     for r in cur.fetchall()}
        cur.execute(PLAYERS_SQL, {"cs": season.id, "fixtures": fixtures})
        players = [PlayerLine(int(r["fixture_id"]), r["kickoff_at"], int(r["player_id"]), str(r["player_name"]), str(r["team_side"]),
                              int(r["minutes"]), bool(r["is_starter"]) if r["is_starter"] is not None else not bool(r["substitute"]),
                              r["sheet_position"] if r["sheet_position"] in ("G", "D", "M", "F") else None, r["profile_position"],
                              {**{c: _num(r[c]) for c in PLAYER_COUNTS},
                               **extra.get((int(r["fixture_id"]), int(r["provider_player_id"])), {})}) for r in cur.fetchall()]
    return SeasonData(season, matches, players)
