"""How fast each match's bets were settled after it ended, and what still waits (Admin -> Picks)."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from fbi.api.contracts.settlement import SettlementLatency, SettlementRow, WaitingSettlement
from fbi.api.envelope import Envelope, ok
from fbi.api.repositories import Conn, fetch_all
from fbi.core import match_state
from fbi.core.clock import now as clock_now

ROWS_SQL = """
SELECT DISTINCT ON (l.fixture_id) l.fixture_id, th.name AS home, ta.name AS away, c.name AS competition,
       l.kickoff_at, l.status_short, l.last_in_play_at, l.observed_finished_at, l.result_stored_at,
       l.settled_at, l.delay_seconds, l.path,
       sum(l.picks_settled) OVER (PARTITION BY l.fixture_id) AS picks_settled,
       sum(l.items_settled) OVER (PARTITION BY l.fixture_id) AS items_settled
  FROM picks.settlement_latency l
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE l.settled_at >= %(since)s
 ORDER BY l.fixture_id, l.settled_at
"""
"""Per match, its FIRST settlement (when its bets stopped saying "pending"), with everything settled for it."""

WAITING_SQL = """
WITH ended AS (
    SELECT f.id, f.kickoff_at, f.status_short, th.name AS home, ta.name AS away
      FROM core.fixtures f
      JOIN core.teams th ON th.id = f.home_team_id
      JOIN core.teams ta ON ta.id = f.away_team_id
     WHERE upper(f.status_short) = ANY(%(ended)s) AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(at)s
)
SELECT e.id AS fixture_id, e.home, e.away, e.kickoff_at, e.status_short,
       (SELECT count(*) FROM picks.picks p WHERE p.fixture_id = e.id AND p.status <> 'settled') AS open_picks,
       (SELECT count(*) FROM picks.daily_set_items i WHERE i.fixture_id = e.id AND i.status = 'PENDING')
     + (SELECT count(*) FROM picks.parlay_legs l WHERE l.fixture_id = e.id AND l.status = 'PENDING')
     + (SELECT count(*) FROM picks.user_picks u WHERE u.fixture_id = e.id AND u.status = 'PENDING') AS open_items,
       COALESCE((SELECT min(s.observed_at) FROM core.fixture_live_states s
                  WHERE s.fixture_id = e.id AND s.status_short = ANY(%(ended)s)),
                (SELECT r.settled_at FROM core.fixture_results r WHERE r.fixture_id = e.id)) AS ended_at,
       (SELECT pr.review_reason FROM picks.pick_results pr JOIN picks.picks p ON p.id = pr.pick_id
         WHERE p.fixture_id = e.id AND pr.review_reason IS NOT NULL LIMIT 1) AS review_reason
  FROM ended e
"""


def latency(conn: Conn, *, days: int, at: datetime | None = None) -> Envelope[SettlementLatency]:
    moment = at or clock_now()
    since = moment - timedelta(days=days)
    rows = [SettlementRow(**r) for r in fetch_all(conn, ROWS_SQL, {"since": since})]
    rows.sort(key=lambda r: r.settled_at, reverse=True)
    delays = sorted(r.delay_seconds for r in rows if r.delay_seconds is not None)
    by_path: dict[str, int] = {}
    for r in rows:
        by_path[r.path] = by_path.get(r.path, 0) + 1
    waiting = [WaitingSettlement(**r) for r in fetch_all(conn, WAITING_SQL, {
        "since": since, "at": moment, "ended": sorted(match_state.ENDED)}) if r["open_picks"] or r["open_items"]]
    waiting.sort(key=lambda w: w.kickoff_at, reverse=True)
    body = SettlementLatency(
        days=days, matches=len(rows),
        mean_seconds=round(statistics.fmean(delays), 1) if delays else None,
        median_seconds=float(statistics.median(delays)) if delays else None,
        p90_seconds=float(delays[min(len(delays) - 1, int(0.9 * len(delays)))]) if delays else None,
        max_seconds=delays[-1] if delays else None, by_path=by_path, rows=rows[:300], waiting=waiting[:200])
    return ok(body, count=len(rows))
