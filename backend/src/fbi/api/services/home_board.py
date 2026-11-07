"""What Inicio's general layer reads from ``/home`` besides what is in play (plan de Inicio, section 4 and 3.1): the rules that
choose a block's matches live here, on the server, and the web only draws what comes. Reading only: nothing in this module
computes a probability, prices a selection or chooses a pick.

**Últimos resultados** - the matches that ended in the last 24 hours, the most recent first, six at most. A match is over when
the match feed says so (``fixture_results`` with its group ``finished``) or when the fixture feed's last word is a final
(``FT``, ``AET`` or ``PEN``; the same three the match feed's finished group must carry): the live board drops a match the moment that final arrives, and the result has to be here at once -
never a gap where the match is in neither block. A cancelled, postponed or abandoned match is not a result.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.contracts.product import CompetitionBadge, HomeResult, TeamBadge
from fbi.api.repositories import Conn, fetch_all

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
