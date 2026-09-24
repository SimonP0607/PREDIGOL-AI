"""The match history the feature engine reads: fixtures and, where recorded, scores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import tuple_row


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

    @property
    def has_result(self) -> bool:
        """A score counts only for a finished match: a postponed fixture's 0-0 is not a result."""
        return self.status_group == "finished" and self.goals_home is not None and self.goals_away is not None


def load_matches(conn: psycopg.Connection, *, competition_ids: list[int] | None = None) -> list[MatchRecord]:
    """Every stored fixture (optionally restricted), oldest first, with its score if any."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT f.id, f.kickoff_at, c.id, c.competition_type, cs.season, f.home_team_id, f.away_team_id,
                   r.goals_home, r.goals_away, (f.is_neutral OR c.neutral_venue), f.status_group
            FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
            WHERE (%s::bigint[] IS NULL OR c.id = ANY(%s::bigint[]))
            ORDER BY f.kickoff_at, f.id
            """,
            (competition_ids, competition_ids),
        )
        return [
            MatchRecord(int(a), b, int(c), str(d), int(e), int(f), int(g),
                        None if h is None else int(h), None if i is None else int(i), bool(j), str(k))
            for a, b, c, d, e, f, g, h, i, j, k in cur.fetchall()
        ]
