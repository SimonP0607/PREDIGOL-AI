"""CIERRE DEL DÍA, read back: the history of closed days and one day with its revisions (Admin -> IA e
investigación, Evolución -> AYER)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fbi.api.contracts.ai_layer import DailyReview, DailyReviewDay, DailyReviewRevision
from fbi.api.envelope import DataStatus, Envelope, listing, ok, unavailable
from fbi.api.repositories import Conn, fetch_all

HISTORY_SQL = """
SELECT DISTINCT ON (day) day, revision, built_at, complete, content,
       count(*) OVER (PARTITION BY day) AS revisions
  FROM ai.daily_reviews
 WHERE day >= (SELECT COALESCE(max(day), current_date) FROM ai.daily_reviews) - %(days)s
 ORDER BY day DESC, revision DESC
"""

DAY_SQL = "SELECT * FROM ai.daily_reviews WHERE day = %(day)s ORDER BY revision DESC"


def _headline(r: dict[str, Any]) -> DailyReviewDay:
    c = r["content"] or {}
    daily = c.get("daily_picks") or {}
    return DailyReviewDay(
        day=r["day"], revisions=int(r["revisions"]), built_at=r["built_at"], complete=bool(r["complete"]),
        matches=int((c.get("matches") or {}).get("tracked") or 0),
        played=int((c.get("matches") or {}).get("played") or 0),
        daily_won=int(daily.get("won") or 0), daily_lost=int(daily.get("lost") or 0),
        daily_pending=int(daily.get("pending") or 0), daily_pnl_units=float(daily.get("pnl_units") or 0),
        shadow_roi=(c.get("shadow") or {}).get("roi"), ai_usd=float((c.get("costs") or {}).get("ai_usd") or 0))


def history(conn: Conn, *, days: int) -> Envelope[list[DailyReviewDay]]:
    rows = [_headline(r) for r in fetch_all(conn, HISTORY_SQL, {"days": days})]
    return listing(rows, empty_reason="No day has been closed yet: the first close is at 23:59 Bogotá.",
                   total=len(rows), limit=days, offset=0)


def day_review(conn: Conn, *, day: date) -> Envelope[DailyReview | None]:
    rows = fetch_all(conn, DAY_SQL, {"day": day})
    if not rows:
        return unavailable(None, f"{day.isoformat()} has not been closed yet.", status=DataStatus.EMPTY)
    newest = rows[0]
    return ok(DailyReview(
        day=newest["day"], revision=int(newest["revision"]), kind=newest["kind"], built_at=newest["built_at"],
        complete=bool(newest["complete"]), content=newest["content"] or {},
        revisions=[DailyReviewRevision(revision=int(r["revision"]), kind=r["kind"], built_at=r["built_at"],
                                       complete=bool(r["complete"]), pending_fixtures=list(r["pending_fixtures"] or []))
                   for r in rows]))

