"""The published picks one by one (plan de cierre UX, 1.5): the list behind the counts of «Cómo le va a PrediGol».

Every pick PrediGol published - an item of a day's ``qualified`` set, the only set a reader is ever shown; no query here names
the ``evaluation`` set - as it was frozen when it was chosen (the price taken, the probability said, the market's own) and how it
ended (win, loss, half, returned, void, pending, and the regular-time score once the match has one). Newest kick-off first, a
page at a time with the cursor Mis picks uses (``fbi.api.services.records``), so a page never repeats or skips a pick.

The list is cut like the counts are: matches that start before the end of the reader's today (``period_bounds``), so its total is
the page's «all» period's ``published`` - a test and ``scripts/transparency_check.py`` both hold the two to it. Reading only:
nothing here computes a probability, prices a selection or changes a pick.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from fbi.api.contracts.transparency import PickResult, PublishedPick
from fbi.api.envelope import Envelope, listing
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services.records import decode_cursor, encode_cursor
from fbi.core.clock import now
from fbi.userdata.records import period_bounds

LIST_KIND: Final = "t"
MAX_LIMIT: Final = 50
DEFAULT_LIMIT: Final = 20

# A rank is 1 to 5 (``picks.daily_set_items``): set id x 10 + rank is one number per item, ordered like (set, rank) - the
# id the cursor carries beside the kick-off.
PICKS_SQL = """
SELECT s.day, i.set_id, i.rank, i.market_key, i.selection, i.line, i.odds, i.p_model, i.p_market, i.selected_at,
       i.status, i.profit_units, f.kickoff_at, c.name AS competition, c.country, th.name AS home, ta.name AS away,
       r.reg_goals_home AS score_home, r.reg_goals_away AS score_away, i.set_id * 10 + i.rank AS position
  FROM picks.daily_set_items i
  JOIN picks.daily_sets s ON s.id = i.set_id AND s.source = 'qualified'
  JOIN core.fixtures f ON f.id = i.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.kickoff_at < %(until)s
   AND (%(after_at)s::timestamptz IS NULL
        OR (f.kickoff_at, i.set_id * 10 + i.rank) < (%(after_at)s::timestamptz, %(after_id)s::bigint))
 ORDER BY f.kickoff_at DESC, i.set_id * 10 + i.rank DESC
 LIMIT %(limit)s
"""

TOTAL_SQL = """
SELECT count(*)::int AS n
  FROM picks.daily_set_items i
  JOIN picks.daily_sets s ON s.id = i.set_id AND s.source = 'qualified'
  JOIN core.fixtures f ON f.id = i.fixture_id
 WHERE f.kickoff_at < %(until)s
"""


def _pick(r: dict[str, Any]) -> PublishedPick:
    result: PickResult = r["status"]
    settled = result != "PENDING" and r["profit_units"] is not None
    return PublishedPick(
        day=r["day"], kickoff_at=r["kickoff_at"], published_at=r["selected_at"], competition=r["competition"],
        country=r["country"], home=r["home"], away=r["away"], market=r["market_key"], selection=r["selection"],
        line=Decimal(r["line"]), odds=Decimal(r["odds"]), p_model=Decimal(r["p_model"]), p_market=Decimal(r["p_market"]),
        result=result, units=Decimal(r["profit_units"]) if settled else None,
        score_home=r["score_home"], score_away=r["score_away"])


def published_picks(conn: Conn, *, tz: str, limit: int = DEFAULT_LIMIT, cursor: str | None = None,
                    at: datetime | None = None) -> Envelope[list[PublishedPick]]:
    """A page of the published picks, newest kick-off first, for a reader in ``tz`` (their today is where the list ends);
    ``meta.total`` counts every one and ``meta.next_cursor`` leads to the next page."""
    after_at, after_id = decode_cursor(LIST_KIND, cursor)
    _, until = period_bounds("all", at=at or now(), tz=tz)
    rows = fetch_all(conn, PICKS_SQL, {"until": until, "after_at": after_at, "after_id": after_id, "limit": limit + 1})
    more = len(rows) > limit
    rows = rows[:limit]
    total = fetch_one(conn, TOTAL_SQL, {"until": until})
    n = int(total["n"]) if total else 0
    next_cursor = encode_cursor(LIST_KIND, rows[-1]["kickoff_at"], int(rows[-1]["position"])) if more else None
    reason = "PrediGol has not published a pick yet." if n == 0 else "No more picks after this one."
    return listing([_pick(r) for r in rows], empty_reason=reason, total=n, limit=limit,
                   offset=0 if cursor is None else None, next_cursor=next_cursor)
