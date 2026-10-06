"""Follow tracked matches while they are played: state, events, statistics, line-ups.

One /fixtures?ids= request covers up to 20 fixtures and carries everything the
Match Center shows - status, minute, score, events, team statistics, line-ups
and player statistics - so following every tracked match in play costs
ceil(n / 20) requests a minute: about 3,000 a day on a full Saturday, against a
75,000 plan.

Which matches: tracked fixtures that kicked off in the last three hours (or
start within two minutes) and are not known to be over, plus anything the odds
feed reported in play in the last few minutes. Kick-off alone is not enough -
the fixture row says 'NS' until something moves it, which is exactly what this
does.

Everything written goes through the writers that already exist and are
monotonic on the fetch instant: the fixture status and final score through
``apply_fixtures_payload``, the detail through ``apply_fixture_details``. A
live tick can therefore never overwrite a later full-time payload, and the
full-time payload replaces the last live one. What the existing tables could
not hold - the score and minute DURING play - goes to core.fixture_live_states,
one row per change.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.core.logging import get_logger
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.details import apply_fixture_details
from fbi.ingestion.fixtures import tracked_season_ids
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.normalize import canonical_status
from fbi.providers.api_football.provider import MAX_IDS
from fbi.providers.base import RawResponse

log = get_logger(__name__)

FOLLOW_AFTER_KICKOFF = timedelta(hours=3)
FOLLOW_BEFORE_KICKOFF = timedelta(minutes=2)
ODDS_FEED_RECENT = timedelta(minutes=5)

FOLLOW_SQL = """
SELECT f.id, f.provider_fixture_id
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked
   AND f.kickoff_at BETWEEN %(at)s - %(after)s AND %(at)s + %(before)s
   AND f.status_group IN ('scheduled', 'live')
UNION
SELECT f.id, f.provider_fixture_id
  FROM market.live_fixture_current s
  JOIN core.fixtures f ON f.id = s.fixture_id
 WHERE s.captured_at > %(at)s - %(recent)s
   AND NOT COALESCE(s.is_finished, false)
   AND f.status_group IN ('scheduled', 'live')
ORDER BY 2
"""


@dataclass(frozen=True, slots=True)
class LiveMatchState:
    provider_fixture_id: int
    status_short: str
    elapsed: int | None
    extra: int | None
    goals_home: int | None
    goals_away: int | None

    def key(self) -> tuple[Any, ...]:
        return (self.status_short, self.elapsed, self.extra, self.goals_home, self.goals_away)


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v)
    return None


def iter_live_states(body: dict[str, Any]) -> Iterator[LiveMatchState]:
    """One state per fixture in a /fixtures response. A fixture without an id or a
    status is skipped: a state is never guessed."""
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        fx: dict[str, Any] = entry["fixture"] if isinstance(entry.get("fixture"), dict) else {}
        status: dict[str, Any] = fx["status"] if isinstance(fx.get("status"), dict) else {}
        fid, short = _int(fx.get("id")), status.get("short")
        if fid is None or not isinstance(short, str) or not short:
            continue
        goals: dict[str, Any] = entry["goals"] if isinstance(entry.get("goals"), dict) else {}
        yield LiveMatchState(fid, canonical_status(short), _int(status.get("elapsed")), _int(status.get("extra")),
                             _int(goals.get("home")), _int(goals.get("away")))


def fixtures_to_follow(conn: psycopg.Connection, *, at: datetime) -> list[tuple[int, int]]:
    """(fixture_id, provider_fixture_id) for every tracked match that may be in play."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(FOLLOW_SQL, {"at": at, "after": FOLLOW_AFTER_KICKOFF,
                                 "before": FOLLOW_BEFORE_KICKOFF, "recent": ODDS_FEED_RECENT})
        return [(int(a), int(b)) for a, b in cur.fetchall()]


def write_states(conn: psycopg.Connection, states: Sequence[LiveMatchState], *,
                 observed_at: datetime, payload_hash: str) -> int:
    """Append a row for each fixture whose state differs from its last one. Returns rows written."""
    if not states:
        return 0
    written = 0
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT provider_fixture_id, id FROM core.fixtures WHERE provider_fixture_id = ANY(%s)",
                    ([s.provider_fixture_id for s in states],))
        ids = {int(a): int(b) for a, b in cur.fetchall()}
        for s in states:
            fixture_id = ids.get(s.provider_fixture_id)
            if fixture_id is None:
                continue
            cur.execute(
                "SELECT status_short, elapsed, extra, goals_home, goals_away, observed_at "
                "FROM core.fixture_live_states WHERE fixture_id = %s ORDER BY observed_at DESC LIMIT 1",
                (fixture_id,),
            )
            last = cur.fetchone()
            if last is not None and (tuple(last[:5]) == s.key() or last[5] >= observed_at):
                continue  # unchanged, or a newer state is already held
            cur.execute(
                "INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, extra, "
                "goals_home, goals_away, payload_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (fixture_id, observed_at) DO NOTHING",
                (fixture_id, observed_at, s.status_short, s.elapsed, s.extra, s.goals_home, s.goals_away,
                 payload_hash),
            )
            written += max(cur.rowcount, 0)
    return written


@dataclass
class LiveMatchReport:
    followed: int = 0
    requests: int = 0
    states_written: int = 0
    fixtures_updated: int = 0
    results_written: int = 0
    detail_fixtures: int = 0
    errors: list[str] = field(default_factory=list)
    run_id: int | None = None


STALE_SQL = """
SELECT f.id, f.provider_fixture_id
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked
   AND f.status_group IN ('scheduled', 'live')
   AND f.kickoff_at BETWEEN %(at)s - %(oldest)s AND %(at)s - %(after)s
 ORDER BY f.kickoff_at DESC
"""
STALE_AFTER = timedelta(hours=3)
STALE_OLDEST = timedelta(days=30)


def stale_to_repair(conn: psycopg.Connection, *, at: datetime) -> list[tuple[int, int]]:
    """Tracked fixtures that kicked off over three hours ago and still say they have
    not finished: what the date sweep missed (a day the worker was down, a date the
    provider filed differently). Newest first, so a cap spends on the freshest."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(STALE_SQL, {"at": at, "after": STALE_AFTER, "oldest": STALE_OLDEST})
        return [(int(a), int(b)) for a, b in cur.fetchall()]


async def repair_stale_results(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None,
                               max_requests: int = 5) -> LiveMatchReport:
    """Fetch the fixtures the results sync left behind by id - status, score and
    detail in one request per 20 - instead of widening the date sweep."""
    moment = at or now()
    return await _follow(conn, provider, stale_to_repair(conn, at=moment), job_type="results_repair",
                         moment=moment, max_requests=max_requests)


POST_MATCH_SQL = """
SELECT f.id, f.provider_fixture_id,
       CASE WHEN f.kickoff_at <= %(at)s - %(late)s THEN 'late' ELSE 'settled' END AS stage
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'finished'
   AND f.kickoff_at BETWEEN %(at)s - %(oldest)s AND %(at)s - %(settled)s
   AND NOT EXISTS (
       SELECT 1 FROM core.fixture_detail_coverage d
        WHERE d.fixture_id = f.id AND d.dataset = 'team_statistics'
          AND d.fetched_at >= f.kickoff_at + CASE WHEN f.kickoff_at <= %(at)s - %(late)s
                                                  THEN %(late)s ELSE %(settled)s END)
   AND NOT EXISTS (
       SELECT 1 FROM core.detail_asks a
        WHERE a.fixture_id = f.id
          AND a.stage = CASE WHEN f.kickoff_at <= %(at)s - %(late)s THEN 'late' ELSE 'settled' END)
 ORDER BY f.kickoff_at DESC
"""
POST_MATCH_SETTLED = timedelta(minutes=150)
"""Kick-off to a detail worth keeping: the final whistle, plus the provider's own corrections.

The live follower's last read lands at the final whistle, when the statistics are still
being completed and the timeline still corrected: the truth audit found 63% of last
week's matches with their detail read only then (passes, possession and events that the
provider has since changed). One more read, once the match has settled, costs one
request per 20 matches."""
POST_MATCH_LATE = timedelta(hours=26)
"""Kick-off to the late read. The settled read was not the provider's last word: on 5 Oct 2026 the truth audits found
team statistics revised after it (passes 444 -> 434, a red card count withdrawn), players identified in line-ups that
had come without ids, and a line-up published 21 hours after the match. A second read a day later costs one request
per 20 matches."""
POST_MATCH_OLDEST = timedelta(days=7)


def post_match_to_refresh(conn: psycopg.Connection, *, at: datetime) -> list[tuple[int, int]]:
    """Finished tracked matches of the last week whose detail was not read at their current stage: once settled
    (kick-off + 150 min), and once more a day later (kick-off + 26 h). A stage asked is done (``core.detail_asks``),
    so an answer identical to the last one is not asked for again."""
    return [(fid, pid) for fid, pid, _ in post_match_stages(conn, at=at)]


def post_match_stages(conn: psycopg.Connection, *, at: datetime) -> list[tuple[int, int, str]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(POST_MATCH_SQL, {"at": at, "settled": POST_MATCH_SETTLED, "late": POST_MATCH_LATE,
                                     "oldest": POST_MATCH_OLDEST})
        return [(int(a), int(b), str(c)) for a, b, c in cur.fetchall()]


def record_detail_asks(conn: psycopg.Connection, asks: Sequence[tuple[int, str]], *, at: datetime,
                       payload_hash: str | None, run_id: int | None) -> None:
    """One row per (fixture, stage) asked; asking again updates the time."""
    if not asks:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO core.detail_asks (fixture_id, stage, asked_at, payload_hash, run_id) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (fixture_id, stage) DO UPDATE SET asked_at = EXCLUDED.asked_at, "
            "payload_hash = EXCLUDED.payload_hash, run_id = EXCLUDED.run_id",
            [(fid, stage, at, payload_hash, run_id) for fid, stage in asks])


async def refresh_post_match(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None,
                             max_requests: int = 10) -> LiveMatchReport:
    """Read each finished match once more after it settled, and once more a day later: final statistics, events,
    line-ups."""
    moment = at or now()
    due = post_match_stages(conn, at=moment)
    stage_of = {pid: (fid, stage) for fid, pid, stage in due}

    def asked(provider_ids: Sequence[int], raw: RawResponse, run_id: int | None) -> None:
        record_detail_asks(conn, [stage_of[p] for p in provider_ids if p in stage_of], at=moment,
                           payload_hash=raw.payload_hash, run_id=run_id)

    return await _follow(conn, provider, [(fid, pid) for fid, pid, _ in due], job_type="post_match_detail",
                         moment=moment, max_requests=max_requests, on_batch=asked)


async def capture_live_matches(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None,
                               max_requests: int = 10) -> LiveMatchReport:
    """One pass over every match that may be in play. Opens its own ledger run
    only when there is something to follow, so an empty night writes nothing."""
    moment = at or now()
    return await _follow(conn, provider, fixtures_to_follow(conn, at=moment), job_type="live_match_capture",
                         moment=moment, max_requests=max_requests)


async def _follow(conn: psycopg.Connection, provider: Any, follow: list[tuple[int, int]], *, job_type: str,
                  moment: datetime, max_requests: int,
                  on_batch: Callable[[Sequence[int], RawResponse, int | None], None] | None = None) -> LiveMatchReport:
    report = LiveMatchReport()
    report.followed = len(follow)
    if not follow:
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(job_type, params={"fixtures": len(follow)}, scheduled_for=moment)
    report.run_id = run_id
    counters = RunCounters()
    season_ids = tracked_season_ids(conn)
    provider_ids = [p for _, p in follow]
    try:
        for start in range(0, len(provider_ids), MAX_IDS):
            if report.requests >= max_requests:
                # A cap is a plan, not an error: the run is 'aborted' (capped), not 'partial' (5 Oct 2026).
                counters.stopped_early = (f"request cap {max_requests} reached; "
                                          f"{len(provider_ids) - start} fixtures not followed this pass")
                break
            batch = provider_ids[start:start + MAX_IDS]
            try:
                details, raw = await provider.fetch_fixture_details(provider_fixture_ids=batch)
            except ProviderError as exc:
                report.requests += 1
                counters.api_calls += 1
                counters.errors.append(str(exc))
                report.errors.append(str(exc))
                log.warning("live_match.fetch_failed", error=str(exc))
                continue
            report.requests += 1
            counters.api_calls += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [raw])
            observed_at = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
            outcome = apply_fixtures_payload(conn, provider, raw.body, payload_hash=raw.payload_hash,
                                             fetched_at=observed_at, season_ids=season_ids)
            report.fixtures_updated += outcome.fixtures_updated
            report.results_written += outcome.results_written
            rep = apply_fixture_details(conn, details, payload_hash=raw.payload_hash,
                                        fetched_at=observed_at, run_id=run_id)
            report.detail_fixtures += rep.fixtures
            report.states_written += write_states(conn, list(iter_live_states(raw.body)),
                                                  observed_at=observed_at, payload_hash=raw.payload_hash)
            if on_batch is not None:
                on_batch(batch, raw, run_id)
            conn.commit()
        counters.rows_normalized = report.detail_fixtures
        counters.rows_inserted = report.states_written
        counters.rows_updated = report.fixtures_updated + report.results_written
    finally:
        ledger.close(run_id, counters, notes=f"{report.followed} followed, {report.requests} requests")
        conn.commit()
    log.info(f"{job_type}.done", followed=report.followed, requests=report.requests,
             states=report.states_written, fixtures_updated=report.fixtures_updated,
             results=report.results_written)
    return report
