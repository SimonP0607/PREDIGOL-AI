"""How long before kick-off each competition's official line-ups reach us (IA-069, plan piece AD-D05). Read only.

For every tracked match played in the window, the first arrival of each side (``core.fixture_lineup_arrivals``), when both
sides were known, and whether a starter changed before kick-off; summarised per competition: matches played, with a line-up,
with it before kick-off, and the minutes between the first sighting of BOTH sides and the kick-off (median, p10, p90).

What "publication at the provider" means here: the first time one of our reads saw it. The true publication is earlier by at
most the gap between our reads - the watch's interval (``FBI_LINEUP_WATCH_MINUTES``) when the watch saw it first, up to the
10 minutes of the pre-match read otherwise - so ``first_by_watch`` says how much of the figure has the finer resolution.

The official publication (the competition's or the club's own) is NOT compared: no permitted source dates it yet (AD-C02).
The column is there, empty, and says so.

Also the closing check of the piece: of the line-up rows of matches played in the window, how many have ``first_seen_at``.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

SMALL_SAMPLE: Final = 10
OFFICIAL_NOTE: Final = "sin fuente permitida que feche la publicación oficial (AD-C02)"

MATCHES_SQL = """
WITH side AS (
    SELECT a.fixture_id, a.team_side, min(a.observed_at) AS first_at,
           (array_agg(a.channel ORDER BY a.observed_at, a.id))[1] AS first_channel,
           count(DISTINCT a.starters_hash) FILTER (WHERE a.observed_at < a.kickoff_at) AS starter_versions
      FROM core.fixture_lineup_arrivals a
     WHERE a.kickoff_at >= %(start)s - interval '1 day' AND a.kickoff_at < %(end)s + interval '1 day'
     GROUP BY a.fixture_id, a.team_side
)
SELECT f.id AS fixture_id, f.kickoff_at, c.id AS competition_id, c.name AS competition, c.type AS competition_type,
       count(s.team_side) AS sides, min(s.first_at) AS first_at,
       CASE WHEN count(s.team_side) = 2 THEN max(s.first_at) END AS both_at,
       (array_agg(s.first_channel ORDER BY s.first_at) FILTER (WHERE s.first_at IS NOT NULL))[1] AS first_channel,
       coalesce(bool_or(s.starter_versions > 1), false) AS starter_changed
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN side s ON s.fixture_id = f.id
 WHERE c.is_tracked AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND f.kickoff_at <= %(now)s
   AND f.status_group IN ('finished', 'live')
 GROUP BY f.id, f.kickoff_at, c.id, c.name, c.type
"""

FIRST_SEEN_SQL = """
SELECT count(*) AS rows, count(l.first_seen_at) AS with_first_seen,
       count(*) FILTER (WHERE l.first_seen_at IS NULL) AS without_first_seen
  FROM core.fixture_lineups l JOIN core.fixtures f ON f.id = l.fixture_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND f.kickoff_at <= %(now)s
"""


@dataclass(frozen=True, slots=True)
class MatchTiming:
    fixture_id: int
    kickoff_at: datetime
    competition_id: int
    competition: str
    competition_type: str | None
    sides: int
    first_at: datetime | None
    both_at: datetime | None
    first_channel: str | None
    starter_changed: bool

    @property
    def minutes_before(self) -> float | None:
        """Kick-off minus the moment both sides were known, in minutes (negative: after kick-off). None without both."""
        if self.both_at is None:
            return None
        return (self.kickoff_at - self.both_at).total_seconds() / 60


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (pos - low), 1)


def summarise(matches: Iterable[MatchTiming]) -> list[dict[str, Any]]:
    """One row per competition, most matches first. Pure."""
    groups: dict[tuple[int, str, str | None], list[MatchTiming]] = defaultdict(list)
    for m in matches:
        groups[(m.competition_id, m.competition, m.competition_type)].append(m)
    rows: list[dict[str, Any]] = []
    for (cid, name, ctype), ms in groups.items():
        known = [m for m in ms if m.minutes_before is not None]
        minutes = [m.minutes_before for m in known if m.minutes_before is not None]
        before = [x for x in minutes if x > 0]
        rows.append({
            "competition_id": cid, "competition": name, "type": ctype, "played": len(ms),
            "with_lineups": len(known), "before_kickoff": len(before),
            "share_before_kickoff": round(len(before) / len(ms), 3) if ms else None,
            "median_min": round(statistics.median(minutes), 1) if minutes else None,
            "p10_min": _quantile(minutes, 0.10), "p90_min": _quantile(minutes, 0.90),
            "first_by_watch": sum(1 for m in known if m.first_channel == "lineup_watch"),
            "starter_changed": sum(1 for m in ms if m.starter_changed),
            "small_sample": len(known) < SMALL_SAMPLE, "official": None,
        })
    rows.sort(key=lambda r: (-int(r["played"]), str(r["competition"])))
    return rows


def overall(matches: Sequence[MatchTiming]) -> dict[str, Any]:
    minutes = [m.minutes_before for m in matches if m.minutes_before is not None]
    return {"played": len(matches), "with_lineups": len(minutes), "before_kickoff": sum(1 for x in minutes if x > 0),
            "median_min": round(statistics.median(minutes), 1) if minutes else None,
            "p10_min": _quantile(minutes, 0.10), "p90_min": _quantile(minutes, 0.90),
            "first_by_watch": sum(1 for m in matches if m.minutes_before is not None and m.first_channel == "lineup_watch"),
            "starter_changed": sum(1 for m in matches if m.starter_changed)}


def load(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, now: datetime) -> list[MatchTiming]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MATCHES_SQL, {"start": start, "end": end, "now": now})
        return [MatchTiming(int(r["fixture_id"]), r["kickoff_at"], int(r["competition_id"]), str(r["competition"]),
                            r["competition_type"], int(r["sides"]), r["first_at"], r["both_at"], r["first_channel"],
                            bool(r["starter_changed"])) for r in cur.fetchall()]


def first_seen_coverage(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, now: datetime) -> dict[str, int]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIRST_SEEN_SQL, {"start": start, "end": end, "now": now})
        row = cur.fetchone() or {}
    return {k: int(row.get(k) or 0) for k in ("rows", "with_first_seen", "without_first_seen")}


def report(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, now: datetime) -> dict[str, Any]:
    matches = load(conn, start=start, end=end, now=now)
    return {"window": {"start": start.isoformat(), "end": end.isoformat(), "measured_at": now.isoformat()},
            "overall": overall(matches), "competitions": summarise(matches),
            "first_seen": first_seen_coverage(conn, start=start, end=end, now=now), "official_note": OFFICIAL_NOTE}
