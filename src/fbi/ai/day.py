"""The AI's day: today's matches (America/Bogota) with a market, prepared the day before, opened at 00:05, and the
three passes each of them gets.

    first  from 00:05 Bogotá      the fixtures, which have a market, how fresh their prices are, the packet, the L1
                                  brief, the web for the matches worth it, the candidates' reviews
    pre    6 to 4 h before        (until 90 min before) the matches still relevant again: new news, squad changes,
           kick-off               injuries, suspensions, strong price moves - the web only for escalated matches and
                                  only when the cached answer is stale
    final  after the line-ups     (100 to 10 min before; it waits for the confirmed line-ups until 50 min before) the
                                  XI, the goalkeeper, the formation, definitive absences, the updated market

A pass runs once per match and day (``ai.fixture_passes``): what an earlier pass already paid for is reused, never
asked again. A match WITHOUT a market gets no model and no search: its analysis stays the models' numbers with
"mercado no observado". A match that gains a market later in the day enters the day then.

The day is PREPARED the day before (after the morning's learning, ``prepare_day``): its fixtures, which have a market
already, their priority, the important ones - no model, no search, nothing about the day itself that is not known
yet. It is OPENED from 00:05 Bogotá (``open_day``) with the same reading at that moment and the day's budget.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import DAY_TZ, day_bounds, local_day
from fbi.ai.config import AiSettings
from fbi.ai.usage import budget

VERSION = "day-v1"
OPENS_AT = time(0, 5)
MARKET_LOOKBACK = timedelta(hours=36)
"""A price is part of the market for this long (the packet's own look-back)."""
STALE_ODDS = timedelta(hours=12)
MIN_LEAD = timedelta(minutes=10)
PRE_FROM = timedelta(hours=6)
PRE_UNTIL = timedelta(minutes=90)
PRE_AFTER_FIRST = timedelta(hours=2)
"""A second pass this soon after the first would read the same things: it waits, or is left to the last one."""
FINAL_FROM = timedelta(minutes=100)
FINAL_WAIT_UNTIL = timedelta(minutes=50)
IMPORTANT_BOOKMAKERS = 10
PassKind = Literal["first", "pre", "final"]
RunKind = Literal["first", "pre", "final", "request"]
"""A pass, or the owner's "run now" for one match of the day (paid like a pass, not recorded as one)."""
PASSES: tuple[PassKind, ...] = ("first", "pre", "final")

UNIVERSE_SQL = """
SELECT f.id, f.kickoff_at, c.id AS competition_id, c.name AS competition, c.country, c.tier, c.competition_type,
       th.name AS home, ta.name AS away, m.odds_at, m.n_bookmakers
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN LATERAL (SELECT max(mc.as_of) AS odds_at, max(mc.n_bookmakers) AS n_bookmakers
                       FROM market.market_consensus mc
                      WHERE mc.fixture_id = f.id AND mc.devig_method = 'shin' AND mc.as_of <= %(at)s
                        AND mc.as_of >= %(since)s) m ON true
 WHERE c.is_tracked AND (f.status_group = 'scheduled' OR NOT %(scheduled_only)s)
   AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
 ORDER BY f.kickoff_at, f.id
"""

DONE_SQL = """
SELECT fixture_id, pass, finished_at FROM ai.fixture_passes WHERE fixture_id = ANY(%(fixtures)s) AND day = %(day)s
"""

LINEUPS_SQL = """
SELECT DISTINCT fixture_id FROM core.fixture_lineups WHERE fixture_id = ANY(%(fixtures)s) AND fetched_at <= %(at)s
"""


@dataclass(frozen=True)
class DayFixture:
    fixture_id: int
    kickoff_at: datetime
    competition_id: int
    competition: str
    country: str | None
    tier: int | None
    home: str
    away: str
    has_market: bool
    odds_at: datetime | None
    n_bookmakers: int | None
    priority: float
    important: bool

    def as_json(self, *, at: datetime) -> dict[str, Any]:
        d = asdict(self)
        d["kickoff_at"] = self.kickoff_at.isoformat()
        d["odds_at"] = None if self.odds_at is None else self.odds_at.isoformat()
        d["odds_age_minutes"] = None if self.odds_at is None else int((at - self.odds_at).total_seconds() // 60)
        d["odds_stale"] = self.odds_at is not None and at - self.odds_at > STALE_ODDS
        return d


def priority_of(tier: int | None, n_bookmakers: int | None, competition_type: str | None) -> float:
    """Which matches of the day matter most when there is not enough for all (the web, the stronger models):
    the competition's level and the depth of its market. Candidates are added by the cycle."""
    p = {1: 20.0, 2: 10.0}.get(tier or 0, 4.0 if tier else 0.0)
    if competition_type and competition_type not in ("domestic_league", "domestic_cup"):
        p += 8.0  # continental and international competitions
    return p + min(float(n_bookmakers or 0), 20.0)


def universe(conn: psycopg.Connection[Any], *, day: date, at: datetime,
             scheduled_only: bool = True) -> list[DayFixture]:
    """Every tracked, scheduled fixture of the Bogotá day (or every one, ``scheduled_only=False``, to look back at
    the day), and whether it has a market as of ``at``."""
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(UNIVERSE_SQL, {"start": start, "end": end, "at": at, "since": at - MARKET_LOOKBACK,
                                   "scheduled_only": scheduled_only})
        rows = [dict(r) for r in cur.fetchall()]
    out = []
    for r in rows:
        n = None if r["n_bookmakers"] is None else int(r["n_bookmakers"])
        has_market = r["odds_at"] is not None
        out.append(DayFixture(
            int(r["id"]), r["kickoff_at"], int(r["competition_id"]), str(r["competition"]), r["country"],
            None if r["tier"] is None else int(r["tier"]), str(r["home"]), str(r["away"]), has_market, r["odds_at"], n,
            priority_of(r["tier"], n, r["competition_type"]),
            has_market and (r["tier"] == 1 or (r["competition_type"] or "") not in ("domestic_league", "domestic_cup"))
            and (n or 0) >= IMPORTANT_BOOKMAKERS))
    return out


def opened(at: datetime) -> bool:
    """Whether the Bogotá day of ``at`` has started for the AI (from 00:05)."""
    return at.astimezone(DAY_TZ).time() >= OPENS_AT


def _plan(conn: psycopg.Connection[Any], *, day: date, at: datetime, stage: str, settings: AiSettings,
          fixtures: list[DayFixture]) -> int | None:
    with_market = [f for f in fixtures if f.has_market]
    notes = {"important": [f.fixture_id for f in fixtures if f.important],
             "stale_odds": [f.fixture_id for f in with_market if f.odds_at is not None and at - f.odds_at > STALE_ODDS],
             "competitions": len({f.competition_id for f in with_market}),
             "first_kickoff": None if not fixtures else min(f.kickoff_at for f in fixtures).isoformat(),
             "last_kickoff": None if not fixtures else max(f.kickoff_at for f in fixtures).isoformat()}
    b = budget(conn, at=at, settings=settings).as_json() if stage == "opened" else {}
    ranked = sorted(fixtures, key=lambda f: (-int(f.has_market), -f.priority, f.kickoff_at))
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.day_plans (day, stage, created_at, version, fixtures_total, fixtures_with_market, "
                    "universe, budget, notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (day, stage) DO NOTHING RETURNING id",
                    (day, stage, at, VERSION, len(fixtures), len(with_market),
                     Jsonb([f.as_json(at=at) for f in ranked]), Jsonb(b), Jsonb(notes)))
        row = cur.fetchone()
    return None if row is None else int(row[0])


def open_day(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings) -> int | None:
    """The day's plan at its opening (once): its universe as known at 00:05 (or whenever the worker first runs
    that day) and the day's budget. Returns the new plan's id, None when it was already opened or it is before
    00:05."""
    if not opened(at):
        return None
    day = local_day(at)
    return _plan(conn, day=day, at=at, stage="opened", settings=settings, fixtures=universe(conn, day=day, at=at))


def prepare_day(conn: psycopg.Connection[Any], *, day: date, at: datetime, settings: AiSettings) -> int | None:
    """A coming day prepared without any model or search: its fixtures, those with a market already, priorities and
    the important ones. Nothing about the day is analysed before it opens."""
    if day <= local_day(at):
        return None
    return _plan(conn, day=day, at=at, stage="prepared", settings=settings, fixtures=universe(conn, day=day, at=at))


@dataclass(frozen=True)
class Due:
    fixture: DayFixture
    pass_kind: RunKind


def due_pass(kickoff: datetime, *, at: datetime, done: dict[str, datetime], lineups_confirmed: bool
             ) -> PassKind | None:
    """The pass a match of the day needs now, if any (pure)."""
    lead = kickoff - at
    if lead <= MIN_LEAD:
        return None
    if "first" not in done:
        return "first"
    if "final" not in done and lead <= FINAL_FROM and (lineups_confirmed or lead <= FINAL_WAIT_UNTIL):
        return "final"
    if "pre" not in done and "final" not in done and PRE_UNTIL < lead <= PRE_FROM \
            and at - done["first"] >= PRE_AFTER_FIRST:
        return "pre"
    return None


def due_passes(conn: psycopg.Connection[Any], *, at: datetime, only: set[int] | None = None) -> list[Due]:
    """The passes due now for today's matches with a market, highest priority first."""
    if not opened(at):
        return []
    day = local_day(at)
    fixtures = [f for f in universe(conn, day=day, at=at) if f.has_market and (only is None or f.fixture_id in only)]
    if not fixtures:
        return []
    ids = [f.fixture_id for f in fixtures]
    done: dict[int, dict[str, datetime]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(DONE_SQL, {"fixtures": ids, "day": day})
        for fid, kind, finished in cur.fetchall():
            done.setdefault(int(fid), {})[str(kind)] = finished
        cur.execute(LINEUPS_SQL, {"fixtures": ids, "at": at})
        confirmed = {int(r[0]) for r in cur.fetchall()}
    out = []
    for f in sorted(fixtures, key=lambda f: (-f.priority, f.kickoff_at)):
        kind = due_pass(f.kickoff_at, at=at, done=done.get(f.fixture_id, {}),
                        lineups_confirmed=f.fixture_id in confirmed)
        if kind is not None:
            out.append(Due(f, kind))
    return out
