"""The match history the feature engine reads: fixtures and, where recorded, scores.

Since GATE E (feature version fv2.1.0) the history is the VALIDATED one: a played match
the historical validation quarantined (a duplicate, a half-time score above the final
one) or left INGESTED (an extra-time result without its 90-minute score) is not read at
all - it enters no rating, no form, no fit and no backtest (``fbi.validation.historical``).
A fixture not yet validated (upcoming, or played since the last validation run) is read
as it is."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import tuple_row

from fbi.catalog.segments import CompetitionFacts, segment_of

EXCLUDED_STATES = ("QUARANTINED", "INGESTED")
"""Validation states whose result no model, rating or backtest may read."""


@dataclass(frozen=True, slots=True)
class MatchRecord:
    fixture_id: int
    kickoff_at: datetime
    competition_id: int
    competition_type: str
    season: int
    home_team_id: int
    away_team_id: int
    goals_home: int | None
    goals_away: int | None
    is_neutral: bool
    status_group: str
    reg_goals_home: int | None = None
    """Regulation (90-minute) score - what 1X2, Over/Under and BTTS settle on.
    goals_* are the final score after extra time; they differ only after extra time."""
    reg_goals_away: int | None = None
    segment: str = "other_league"
    """``fbi.catalog.segments``: top_league, other_league, domestic_cup, continental_club,
    club_friendly, national_team, women, youth. Models are judged per segment."""

    @property
    def settle_home(self) -> int | None:
        return self.reg_goals_home if self.reg_goals_home is not None else self.goals_home

    @property
    def settle_away(self) -> int | None:
        return self.reg_goals_away if self.reg_goals_away is not None else self.goals_away

    @property
    def has_result(self) -> bool:
        """A score counts only for a finished match: a postponed fixture's 0-0 is not a result."""
        return self.status_group == "finished" and self.goals_home is not None and self.goals_away is not None


def load_matches(conn: psycopg.Connection, *, competition_ids: list[int] | None = None,
                 validated: bool = True) -> list[MatchRecord]:
    """Every stored fixture (optionally restricted), oldest first, with its score if any.

    ``validated`` (the default) leaves out the played matches the historical validation
    quarantined or could not settle (``EXCLUDED_STATES``); ``False`` reads them too, for the
    audits that need to see them."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT f.id, f.kickoff_at, c.id, c.competition_type, cs.season, f.home_team_id, f.away_team_id,
                   r.goals_home, r.goals_away, (f.is_neutral OR c.neutral_venue), f.status_group,
                   r.reg_goals_home, r.reg_goals_away, c.name, c.entity_scope, c.tier
            FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
            WHERE (%s::bigint[] IS NULL OR c.id = ANY(%s::bigint[]))
              AND (NOT %s OR NOT EXISTS (SELECT 1 FROM analytics.fixture_validation v
                                          WHERE v.fixture_id = f.id AND v.state = ANY(%s)))
            ORDER BY f.kickoff_at, f.id
            """,
            (competition_ids, competition_ids, validated, list(EXCLUDED_STATES)),
        )
        segments: dict[int, str] = {}
        out: list[MatchRecord] = []
        for a, b, c, d, e, f, g, h, i, j, k, rh, ra, name, scope, tier in cur.fetchall():
            comp = int(c)
            if comp not in segments:
                segments[comp] = segment_of(CompetitionFacts(str(name), d, scope,
                                                             None if tier is None else int(tier))).value
            out.append(MatchRecord(int(a), b, comp, str(d), int(e), int(f), int(g),
                                   None if h is None else int(h), None if i is None else int(i), bool(j), str(k),
                                   None if rh is None else int(rh), None if ra is None else int(ra),
                                   segments[comp]))
        return out


@dataclass(frozen=True, slots=True)
class TeamStatsPair:
    """Shots and shots on target of both sides of one fixture, from one source."""

    home_shots: int | None
    away_shots: int | None
    home_sot: int | None
    away_sot: int | None
    source: str


STATS_PRECEDENCE = ("api-football", "football-data.co.uk")
"""When both sources report a fixture, the provider we also take lineups and
events from wins. How far the two disagree is not known yet: it is measured
once both exist for the same fixtures (data quality), not assumed."""


def load_team_stats(conn: psycopg.Connection) -> dict[int, TeamStatsPair]:
    """fixture id -> shots of both sides, from the preferred source that has both sides."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT fixture_id, source, team_side, shots, shots_on_target FROM core.fixture_team_stats")
        rows: dict[tuple[int, str], dict[str, tuple[int | None, int | None]]] = {}
        for fid, source, side, shots, sot in cur.fetchall():
            rows.setdefault((int(fid), str(source)), {})[str(side)] = (shots, sot)
    out: dict[int, TeamStatsPair] = {}
    for source in reversed(STATS_PRECEDENCE):
        for (fid, src), sides in rows.items():
            if src != source or "home" not in sides or "away" not in sides:
                continue
            (hs, hst), (as_, ast) = sides["home"], sides["away"]
            out[fid] = TeamStatsPair(hs, as_, hst, ast, src)
    return out
