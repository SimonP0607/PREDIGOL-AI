"""Elo rankings from the stored rating history - the same ratings the models read."""

from __future__ import annotations

from fbi.api.cache import shared
from fbi.api.contracts.rankings import Rankings, RatingRow
from fbi.api.envelope import Envelope, ok, unavailable
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.backtesting.walkforward import MIN_ELO_HISTORY
from fbi.catalog.segments import YOUTH_PATTERN

POOLS = ("men", "women", "youth", "all")
"""Rating pools that never play each other: a women's or an under-21 rating next to a men's one compares numbers from
separate walks (Barcelona W at 2126 above Manchester City at 2111 said nothing). A team's pool is read from its last
rated match's competition and from its own name (the provider names women's sides "... W" and youth sides "... U19")."""

LATEST_RUN = """
    SELECT elo_version, run_id, max(computed_at) AS computed_at FROM features.elo_ratings
    GROUP BY elo_version, run_id ORDER BY max(computed_at) DESC LIMIT 1
"""

RATINGS = """
    WITH r AS (
        SELECT e.team_id, e.kickoff_at, e.rating_before, e.rating_after, c.name AS competition, c.id AS competition_id,
               c.gender, c.age_group,
               row_number() OVER (PARTITION BY e.team_id ORDER BY e.kickoff_at DESC, e.fixture_id DESC) AS rn,
               count(*) OVER (PARTITION BY e.team_id) AS n
        FROM features.elo_ratings e
        JOIN core.fixtures f ON f.id = e.fixture_id
        JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
        JOIN core.competitions c ON c.id = cs.competition_id
        WHERE e.elo_version = %(v)s AND e.run_id = %(run)s
    )
    SELECT r.team_id, t.name AS team, r.rating_after AS rating, r.n AS matches, r.kickoff_at AS last_match_at,
           r.competition AS last_competition,
           r.rating_after - (SELECT r5.rating_before FROM r r5 WHERE r5.team_id = r.team_id AND r5.rn = 5)
               AS change_last5
    FROM r JOIN core.teams t ON t.id = r.team_id
    WHERE r.rn = 1 AND (%(comp)s::bigint IS NULL OR r.competition_id = %(comp)s)
      AND (%(pool)s = 'all'
           OR (%(pool)s = 'women' AND (r.gender = 'women' OR t.name ~ ' W$'))
           OR (%(pool)s = 'youth' AND (r.age_group = 'youth' OR t.name ~* %(youth)s))
           OR (%(pool)s = 'men' AND r.gender = 'men' AND r.age_group = 'senior' AND t.name !~ ' W$'
               AND t.name !~* %(youth)s))
    ORDER BY r.rating_after DESC
    LIMIT %(limit)s
"""


@shared(300)
def rankings(conn: Conn, *, competition_id: int | None, limit: int, pool: str = "men") -> Envelope[Rankings | None]:
    latest = fetch_one(conn, LATEST_RUN)
    if latest is None:
        return unavailable(None, "No Elo history has been computed: run scripts.build_features --apply.")
    rows = fetch_all(conn, RATINGS, {"v": latest["elo_version"], "run": latest["run_id"], "comp": competition_id,
                                     "limit": limit, "pool": pool if pool in POOLS else "men",
                                     "youth": YOUTH_PATTERN})
    body = Rankings(
        elo_version=latest["elo_version"], run_id=latest["run_id"], computed_at=latest["computed_at"],
        parameters="World Football Elo: K=20, home advantage 65, initial 1500, goal-margin multiplier",
        rows=[RatingRow(rank=i + 1, **r, provisional=int(r["matches"]) < MIN_ELO_HISTORY) for i, r in enumerate(rows)],
    )
    return ok(body)
