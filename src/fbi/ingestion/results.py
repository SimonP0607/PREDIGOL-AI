"""Bring played fixtures to their real state: status, score, finished.

THE BUG THIS EXISTS FOR

``sync_fixtures`` only ever looks forward from now. A fixture imported while it
was still scheduled, whose kick-off then passed without another sync touching
that date, keeps ``status_short = 'NS'`` and ``status_group = 'scheduled'``
forever. Two Premier League matches sat like that for days: the database
asserted they had not been played, while they had.

Nothing downstream can be built on that. Settlement needs a score, a market
baseline needs an outcome, and a "coverage" metric that counts a played match
as upcoming is measuring nothing.

WHAT IT COSTS

Nothing extra. ``/fixtures?date=`` already returns ``goals`` and ``score``
alongside every fixture; the previous code parsed the identity and threw the
result away. So a day this system fetches for ANY reason yields its results
too.

WHAT THE PLAN LIMITS

On the free plan ``/fixtures?date=`` is served only for a three-day window
around today. A result not collected within about a day of kick-off is
therefore unreachable - not "expensive", unreachable. That is the whole
argument for the worker running daily rather than being remembered by a human,
and it is why ``lookback_days`` defaults to 1 and warns rather than silently
sweeping dates the provider will refuse.

A fixture the provider does not report as FT/AET/PEN produces no result row: a
postponed match must not acquire a 0-0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.ingestion.fixtures import PLAN_REFUSAL, STATUS_GROUP
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.base import FixtureResultRef, FootballDataProvider

log = structlog.get_logger(__name__)

PLAN_LOOKBACK_LIMIT = 1
"""Days back the free plan actually serves. Beyond this the provider refuses."""


@dataclass(frozen=True)
class StaleFixture:
    """A fixture whose kick-off has passed while the row still says otherwise."""

    provider_fixture_id: int
    kickoff_at: datetime
    status_short: str


def stale_fixtures(conn: psycopg.Connection, *, at: datetime | None = None) -> list[StaleFixture]:
    """Fixtures that kicked off but are still recorded as not started.

    The honest definition of "we are lying about this row". Used both to decide
    what to fetch and, in /health/quality, to report how much of it there is.
    """
    moment = at or now()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT f.provider_fixture_id, f.kickoff_at, f.status_short "
            "FROM core.fixtures f "
            "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE c.is_tracked AND f.kickoff_at < %s AND f.status_group IN ('scheduled', 'live') "
            "ORDER BY f.kickoff_at",
            (moment,),
        )
        return [StaleFixture(int(a), b, str(c)) for a, b, c in cur.fetchall()]


class ResultRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def apply(self, refs: list[FixtureResultRef]) -> tuple[int, int]:
        """Returns (fixtures_updated, results_written).

        Two writes per fixture and both matter: the status on core.fixtures is
        what every query filters on, and the score on core.fixture_results is
        what settlement reads. A row that got one without the other would be
        exactly the half-truth this module exists to remove, so they share a
        transaction.

        A result for a fixture we do not have is skipped, not invented: the
        date sweep sees every league on Earth and we track one.
        """
        if not refs:
            return 0, 0
        updated = written = 0
        with self._conn.cursor(row_factory=tuple_row) as cur:
            for r in refs:
                cur.execute(
                    "UPDATE core.fixtures SET status_short = %s, status_group = %s, updated_at = now() "
                    "WHERE provider_fixture_id = %s RETURNING id",
                    (r.status_short, STATUS_GROUP.get(r.status_short, "finished"), r.provider_fixture_id),
                )
                row = cur.fetchone()
                if row is None:
                    continue  # not a fixture we track
                updated += 1
                cur.execute(
                    """
                    INSERT INTO core.fixture_results
                      (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away,
                       et_goals_home, et_goals_away, pen_home, pen_away)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (fixture_id) DO UPDATE SET
                      goals_home = EXCLUDED.goals_home, goals_away = EXCLUDED.goals_away,
                      ht_goals_home = EXCLUDED.ht_goals_home, ht_goals_away = EXCLUDED.ht_goals_away,
                      et_goals_home = EXCLUDED.et_goals_home, et_goals_away = EXCLUDED.et_goals_away,
                      pen_home = EXCLUDED.pen_home, pen_away = EXCLUDED.pen_away
                    """,
                    (
                        int(row[0]), r.goals_home, r.goals_away, r.ht_goals_home, r.ht_goals_away,
                        r.et_goals_home, r.et_goals_away, r.pen_home, r.pen_away,
                    ),
                )
                written += 1
        return updated, written


async def sync_results(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    *,
    lookback_days: int = PLAN_LOOKBACK_LIMIT,
    at: datetime | None = None,
) -> RunCounters:
    """Fetch and apply results for the recent past.

    Cost: one request per calendar day, today included - today's matches finish
    during today. Idempotent: re-running writes the same score over the same
    score, and the ledger records it as an update rather than an insert.
    """
    moment = at or now()
    if lookback_days > PLAN_LOOKBACK_LIMIT:
        log.warning(
            "results.lookback_beyond_plan",
            requested=lookback_days,
            served=PLAN_LOOKBACK_LIMIT,
            hint="the free plan refuses dates further back; those requests will be spent and rejected",
        )
    ledger = RunLedger(conn)
    run_id = ledger.open("results_sync", params={"lookback_days": lookback_days}, scheduled_for=moment)
    counters = RunCounters()
    repo = ResultRepository(conn)
    try:
        for offset in range(lookback_days + 1):
            on: date = (moment - timedelta(days=offset)).date()
            try:
                refs, raw = await provider.fetch_results_by_date(on=on)
            except ProviderError as exc:
                counters.api_calls += 1  # the request was issued
                counters.errors.append(f"{on.isoformat()}: {exc}")
                level = "info" if PLAN_REFUSAL in str(exc) else "warning"
                getattr(log, level)("results.fetch_failed", date=on.isoformat(), error=str(exc))
                continue
            counters.api_calls += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [raw])
            counters.rows_normalized += len(refs)
            updated, written = repo.apply(list(refs))
            counters.rows_updated += updated
            counters.rows_inserted += written
            conn.commit()
            log.info(
                "results.synced", date=on.isoformat(),
                finished_all_leagues=len(refs), ours=updated, results_written=written,
            )
    finally:
        ledger.close(run_id, counters, notes=f"lookback={lookback_days}")
    return counters
