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
    reg_goals_home: int | None = None
    """Regulation (90-minute) score - what 1X2, Over/Under and BTTS settle on.
    goals_* are the final score after extra time; they differ only after extra time."""
    reg_goals_away: int | None = None

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


def load_matches(conn: psycopg.Connection, *, competition_ids: list[int] | None = None) -> list[MatchRecord]:
    """Every stored fixture (optionally restricted), oldest first, with its score if any."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT f.id, f.kickoff_at, c.id, c.competition_type, cs.season, f.home_team_id, f.away_team_id,
                   r.goals_home, r.goals_away, (f.is_neutral OR c.neutral_venue), f.status_group,
                   r.reg_goals_home, r.reg_goals_away
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
                        None if h is None else int(h), None if i is None else int(i), bool(j), str(k),
                        None if rh is None else int(rh), None if ra is None else int(ra))
            for a, b, c, d, e, f, g, h, i, j, k, rh, ra in cur.fetchall()
        ]
