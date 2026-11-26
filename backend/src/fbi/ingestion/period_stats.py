"""Statistics by half: ask the provider, keep what it says, decide what is built (plan PM, PM-05-01 and PM-05-02).

``GET /fixtures/statistics?fixture=&half=true`` gives, for each team, the match block and the first-half and second-half blocks
(``fbi.providers.api_football.period_stats``). This module is the work around it:

* ``apply_answer`` keeps one answer: up to four rows in ``core.fixture_team_stats_period`` (a half the provider did not give writes no
  row; a figure it did not send is NULL, never zero; a negative count, or a part larger than its whole, is dropped and named in
  ``dropped_fields``) and the match's row in ``core.fixture_period_asks`` (what came back and which statistics came complete in both
  halves for both teams). The newest payload wins at every row, like the match's statistics (``fbi.ingestion.details``).
* ``competition_state`` and ``fbi.core.period_rules`` decide, from the asks, which competitions are asked and which statistics are
  built (DM-13: 90 % of the matches asked, at least 5). A competition with no decision yet is asked until it has five.
* ``refresh_period_stats`` is the closing pass of the worker: each finished match of the last week, once it has settled (150 minutes
  after the kick-off), of the competitions the availability matrix grades B or better in corners - and only while ``FBI_STATS_BY_PERIOD``
  is on. ``fbi.ingestion.period_stats.fill`` (scripts.period_backfill) is the night-time fill of 2024 to 2026 (PM-05-02).
* ``load_probe_answers`` reads the answers of the PM-01-05 probe back from RAW (no request) so that what it measured counts.

Every request goes through the provider client: the day's budget and the minute limit are shared with the rest of the worker. The
closing pass counts in the lane ``estadisticas_contexto`` and the fill in ``historicos`` (``fbi.providers.lanes``).
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
import structlog
from psycopg.rows import dict_row, tuple_row

from fbi.core.clock import now
from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
from fbi.core.period_rules import MIN_SAMPLE, decide, gate
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.period_stats import (
    PERIOD_STAT_COLUMNS,
    PERIODS,
    PeriodAnswer,
    TeamPeriods,
    parse_period_answer,
)

log = structlog.get_logger(__name__)

SWITCH: Final = "FBI_STATS_BY_PERIOD"
BACKFILL_SWITCH: Final = "FBI_STATS_BY_PERIOD_FILL"
JOB: Final = "period_stats"
FILL_JOB: Final = "period_backfill"
ENDPOINT: Final = "/fixtures/statistics"
SOURCE: Final = "api-football"
SETTLE: Final = timedelta(minutes=150)
"""A match is asked once its kick-off is this far behind: the provider's statistics settle (the same wait as PM-01-05)."""
CLOSING_DAYS: Final = 7
"""The closing pass looks back a week: a match it could not ask in time (the matrix did not grade its season yet) is asked later."""
PASS_MAX: Final = 40
"""Requests of one closing pass (the pass runs every 30 minutes)."""
DAY_MAX: Final = 400
"""Requests of the closing pass in a UTC day. PM-05-01's ficha measures 110 to 200; the busiest day of November had 185 matches."""
QUIET_START: Final = time(3, 30)
QUIET_END: Final = time(5, 0)
"""No pass inside the window of the server's copies (PM-05-02's ficha: 03:50 to 05:00; the pass keeps 20 minutes more away)."""
FILL_SINCE: Final = datetime(2024, 1, 1, tzinfo=UTC)
"""The provider gives the halves from the 2024 season (``fbi.providers.api_football.integration``)."""

_TEAM_SIDES: Final = ("home", "away")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``on`` only when ``FBI_STATS_BY_PERIOD`` says so: off by default (a new visible piece is born switched off)."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "off").strip().lower() in ("1", "on", "true", "yes") else "off"


def fill_mode(env: Mapping[str, str] | None = None) -> str:
    """``on`` only when ``FBI_STATS_BY_PERIOD_FILL`` says so (the night-time fill of PM-05-02, off by default)."""
    e = os.environ if env is None else env
    return "on" if e.get(BACKFILL_SWITCH, "off").strip().lower() in ("1", "on", "true", "yes") else "off"


def in_quiet_window(at: datetime) -> bool:
    t = at.astimezone(UTC).time()
    return QUIET_START <= t < QUIET_END


# --- keeping one answer ---------------------------------------------------------------------------------------------------------------


def _clean_block(values: Mapping[str, Decimal | int | None]) -> tuple[list[Decimal | int | None], list[str]]:
    """The row of one team and half, in ``PERIOD_STAT_COLUMNS`` order, and the columns dropped from it: a negative count is not a
    statistic, and a part larger than its whole cannot be stored (the table refuses it)."""
    row: dict[str, Decimal | int | None] = {}
    dropped: list[str] = []
    for name in PERIOD_STAT_COLUMNS:
        value = values.get(name)
        if value is not None and value < 0:
            dropped.append(name)
            value = None
        row[name] = value
    for part, whole in (("shots_on_target", "shots"), ("passes_accurate", "passes")):
        if row[part] is not None and row[whole] is not None and row[part] > row[whole]:  # type: ignore[operator]
            dropped.append(part)
            row[part] = None
    return [row[name] for name in PERIOD_STAT_COLUMNS], sorted(set(dropped))


def _side_of(team: TeamPeriods, home: int, away: int) -> str | None:
    return "home" if team.provider_team_id == home else "away" if team.provider_team_id == away else None


UPSERT_PERIOD_SQL = (
    "INSERT INTO core.fixture_team_stats_period (fixture_id, team_side, period, source, "
    + ", ".join(PERIOD_STAT_COLUMNS)
    + ", payload_hash, fetched_at, dropped_fields) VALUES (%s, %s, %s, %s, "
    + ", ".join(["%s"] * len(PERIOD_STAT_COLUMNS))
    + ", %s, %s, %s) ON CONFLICT (fixture_id, team_side, period, source) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in PERIOD_STAT_COLUMNS)
    + ", payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at, dropped_fields = EXCLUDED.dropped_fields "
    "WHERE core.fixture_team_stats_period.fetched_at <= EXCLUDED.fetched_at"
)

UPSERT_ASK_SQL = (
    "INSERT INTO core.fixture_period_asks (fixture_id, channel, asked_at, outcome, filled, sums_ok, sums_off, payload_hash, run_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (fixture_id) DO UPDATE SET channel = EXCLUDED.channel, "
    "asked_at = EXCLUDED.asked_at, outcome = EXCLUDED.outcome, filled = EXCLUDED.filled, sums_ok = EXCLUDED.sums_ok, "
    "sums_off = EXCLUDED.sums_off, payload_hash = EXCLUDED.payload_hash, run_id = EXCLUDED.run_id "
    "WHERE core.fixture_period_asks.asked_at <= EXCLUDED.asked_at"
)


def apply_answer(cur: psycopg.Cursor[Any], *, fixture_id: int, home_provider_id: int, away_provider_id: int, answer: PeriodAnswer,
                 payload_hash: str, fetched_at: datetime, channel: str, run_id: int | None = None) -> int:
    """Keep one answer in the caller's transaction: the rows of every half the provider gave and the match's ask. Returns the rows
    written. A team the answer names that is neither of the match's teams is ignored (its rows cannot be placed)."""
    written = 0
    for team in answer.teams:
        side = _side_of(team, home_provider_id, away_provider_id)
        if side is None:
            continue
        for period in PERIODS:
            block = team.block(period)
            if block is None:
                continue
            values, dropped = _clean_block(block)
            cur.execute(UPSERT_PERIOD_SQL, (fixture_id, side, period, SOURCE, *values, payload_hash, fetched_at, dropped))
            written += max(cur.rowcount, 0)
    ok, off = answer.sums()
    cur.execute(UPSERT_ASK_SQL, (fixture_id, channel, fetched_at, answer.outcome, sorted(answer.filled()), sorted(ok), sorted(off),
                                 payload_hash, run_id))
    return written


# --- what each competition has been asked ---------------------------------------------------------------------------------------------


COMPETITION_ASKED_SQL = """
SELECT cs.competition_id, count(*) AS asked
  FROM core.fixture_period_asks a JOIN core.fixtures f ON f.id = a.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 GROUP BY 1
"""
COMPETITION_FILLED_SQL = """
SELECT cs.competition_id, s AS stat, count(*) AS n
  FROM core.fixture_period_asks a JOIN core.fixtures f ON f.id = a.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 CROSS JOIN LATERAL unnest(a.filled) AS s
 GROUP BY 1, 2
"""


@dataclass
class CompetitionState:
    asked: int = 0
    filled: Counter[str] = field(default_factory=Counter)

    def gate(self) -> str:
        return gate(self.asked, self.filled)

    def add(self, answer: PeriodAnswer) -> None:
        self.asked += 1
        self.filled.update(answer.filled())


def closed_competitions(states: Mapping[int, CompetitionState]) -> list[int]:
    """The competitions whose decision is taken and builds no statistic: they are not asked again."""
    return sorted(cid for cid, state in states.items() if state.gate() == "closed")


def competition_state(conn: psycopg.Connection) -> dict[int, CompetitionState]:
    """Per competition (our id): how many matches were asked and how many carried each statistic in both halves for both teams."""
    states: dict[int, CompetitionState] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(COMPETITION_ASKED_SQL)
        for competition_id, asked in cur.fetchall():
            states[int(competition_id)] = CompetitionState(asked=int(asked))
        cur.execute(COMPETITION_FILLED_SQL)
        for competition_id, stat, n in cur.fetchall():
            states.setdefault(int(competition_id), CompetitionState()).filled[str(stat)] = int(n)
    return states


# --- which matches are asked ----------------------------------------------------------------------------------------------------------

ELIGIBLE_CTE = """
WITH graded AS (
    SELECT DISTINCT x.competition_season_id AS season_id FROM analytics.coverage_cells x
     WHERE x.datum = 'corners' AND x.phase_key = 'todas'),
ab AS (
    SELECT DISTINCT x.competition_season_id AS season_id FROM analytics.coverage_cells x
     WHERE x.datum = 'corners' AND x.phase_key = 'todas' AND x.level IN ('A', 'B')),
comp_ab AS (
    SELECT DISTINCT s.competition_id FROM ab JOIN core.competition_seasons s ON s.id = ab.season_id)
"""
"""The competitions the availability matrix (PM-02-03) grades A or B in corners - the statistics PM-05-01's ficha names - by season: a
season graded A or B, or a season the matrix has not graded (it keeps the last two) of a competition that has an A or B season."""

TARGETS_SQL = ELIGIBLE_CTE + """
SELECT f.id AS fixture_id, f.provider_fixture_id, f.kickoff_at, cs.competition_id, th.provider_team_id AS home_provider_id,
       ta.provider_team_id AS away_provider_id
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.status_group = 'finished' AND c.is_tracked
   AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s
   AND (f.competition_season_id IN (SELECT season_id FROM ab)
        OR (f.competition_season_id NOT IN (SELECT season_id FROM graded) AND cs.competition_id IN (SELECT competition_id FROM comp_ab)))
   AND cs.competition_id <> ALL(%(skip)s::bigint[])
   AND NOT EXISTS (SELECT 1 FROM core.fixture_period_asks a WHERE a.fixture_id = f.id)
 ORDER BY f.kickoff_at {order}, f.id
 LIMIT %(limit)s
"""


@dataclass(frozen=True, slots=True)
class Target:
    fixture_id: int
    provider_fixture_id: int
    kickoff_at: datetime
    competition_id: int
    home_provider_id: int
    away_provider_id: int


def targets(conn: psycopg.Connection, *, since: datetime, until: datetime, limit: int, newest_first: bool = False,
            skip: Sequence[int] = ()) -> list[Target]:
    """Finished matches of the eligible competitions not asked yet, oldest first (the closing pass) or newest first (the fill).
    ``skip``: competitions left out (those whose decision is taken and builds nothing: asking them again buys nothing)."""
    sql = TARGETS_SQL.format(order="DESC" if newest_first else "ASC")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"since": since, "until": until, "limit": limit, "skip": list(skip)})
        return [Target(int(r["fixture_id"]), int(r["provider_fixture_id"]), r["kickoff_at"], int(r["competition_id"]),
                       int(r["home_provider_id"]), int(r["away_provider_id"])) for r in cur.fetchall()]


def asked_today(conn: psycopg.Connection, *, at: datetime, channel: str) -> int:
    day = at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_period_asks WHERE channel = %s AND asked_at >= %s", (channel, day))
        row = cur.fetchone()
    return int(row[0]) if row else 0


# --- asking ---------------------------------------------------------------------------------------------------------------------------


@dataclass
class PeriodReport:
    run_id: int | None = None
    candidates: int = 0
    requests: int = 0
    with_halves: int = 0
    without_halves: int = 0
    empty: int = 0
    rows: int = 0
    skipped_closed: int = 0
    errors: list[str] = field(default_factory=list)
    stopped: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "candidates": self.candidates, "requests": self.requests, "with_halves": self.with_halves,
                "without_halves": self.without_halves, "empty": self.empty, "rows": self.rows, "skipped_closed": self.skipped_closed,
                "errors": self.errors[:5], "stopped": self.stopped}


async def ask_targets(conn: psycopg.Connection, provider: Any, wanted: Sequence[Target], *, job_type: str, channel: str,
                      max_requests: int, at: datetime, states: dict[int, CompetitionState] | None = None,
                      pace_seconds: float = 0.0, keep_going: Callable[[], bool] | None = None,
                      sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> PeriodReport:
    """Ask each match of ``wanted`` once, up to ``max_requests``, keeping every answer as it comes. A competition whose decision is
    taken while the pass runs (its fifth match answered) and has no statistic built is left alone for the rest of it."""
    report = PeriodReport(candidates=len(wanted))
    if not wanted:
        return report
    states = competition_state(conn) if states is None else states
    ledger = RunLedger(conn)
    run_id = ledger.open(job_type, params={"candidates": len(wanted), "max_requests": max_requests, "channel": channel},
                         scheduled_for=at)
    report.run_id = run_id
    counters = RunCounters()
    try:
        for target in wanted:
            if report.requests >= max_requests:
                report.stopped = counters.stopped_early = f"request cap {max_requests}"
                break
            if keep_going is not None and not keep_going():
                report.stopped = counters.stopped_early = "time or lane budget"
                break
            state = states.setdefault(target.competition_id, CompetitionState())
            if state.gate() == "closed":
                report.skipped_closed += 1
                continue
            if pace_seconds and report.requests:
                await sleep(pace_seconds)
            report.requests += 1
            counters.api_calls += 1
            try:
                raw = await provider.fetch_raw(ENDPOINT, {"fixture": str(target.provider_fixture_id), "half": "true"})
            except (QuotaExhaustedError, CircuitOpenError) as exc:  # our budget or the provider's account: stop here
                counters.errors.append(f"{target.provider_fixture_id}: {type(exc).__name__}")
                report.errors.append(f"{target.provider_fixture_id}: {type(exc).__name__}")
                report.stopped = counters.stopped_early = type(exc).__name__
                break
            except ProviderError as exc:  # one failed match must not lose the others
                message = f"{target.provider_fixture_id}: {type(exc).__name__}: {exc}"[:300]
                counters.errors.append(message)
                report.errors.append(message)
                continue
            counters.payloads_stored += ledger.record_payloads(run_id, [raw])
            conn.commit()  # the payload's index row stays whatever happens to the rows below
            answer = parse_period_answer(raw.body, target.provider_fixture_id)
            observed_at = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
            try:
                with conn.transaction(), conn.cursor() as cur:
                    rows = apply_answer(cur, fixture_id=target.fixture_id, home_provider_id=target.home_provider_id,
                                        away_provider_id=target.away_provider_id, answer=answer, payload_hash=raw.payload_hash,
                                        fetched_at=observed_at, channel=channel, run_id=run_id)
            except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as exc:
                message = f"{target.provider_fixture_id}: not applied: {type(exc).__name__}: {exc}"[:300]
                counters.errors.append(message)
                report.errors.append(message)
                log.error("period_stats.not_applied", fixture=target.provider_fixture_id, error=type(exc).__name__, detail=str(exc)[:200])
                continue
            conn.commit()
            state.add(answer)
            report.rows += rows
            counters.rows_inserted += rows
            if answer.outcome == "with_halves":
                report.with_halves += 1
            elif answer.outcome == "without_halves":
                report.without_halves += 1
            else:
                report.empty += 1
    finally:
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            conn.rollback()
        ledger.close(run_id, counters, notes=f"PM-05-01: {report.requests} request(s): {report.with_halves} with halves, "
                                              f"{report.without_halves} without, {report.empty} empty")
        conn.commit()
    return report


async def refresh_period_stats(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None,
                               max_requests: int = PASS_MAX, day_max: int = DAY_MAX) -> PeriodReport:
    """The closing pass: the finished matches of the last week, settled, of the eligible competitions, once each. Only while the switch
    is on, never inside the copies' window and never past the day's cap."""
    moment = at or now()
    if mode() != "on" or in_quiet_window(moment):
        return PeriodReport()
    room = day_max - asked_today(conn, at=moment, channel="closing")
    if room <= 0:
        return PeriodReport(stopped="day cap")
    states = competition_state(conn)
    wanted = targets(conn, since=moment - timedelta(days=CLOSING_DAYS), until=moment - SETTLE, limit=min(max_requests, room) * 2,
                     skip=closed_competitions(states))
    return await ask_targets(conn, provider, wanted, job_type=JOB, channel="closing", max_requests=min(max_requests, room), at=moment,
                             states=states)


# --- the answers of the PM-01-05 probe, read back from RAW ----------------------------------------------------------------------------

PROBE_ANSWERS_SQL = """
SELECT DISTINCT ON (f.id) f.id AS fixture_id, f.provider_fixture_id, th.provider_team_id AS home_provider_id,
       ta.provider_team_id AS away_provider_id, p.hash, p.file_path, p.fetched_at, p.run_id
  FROM raw.ingestion_payloads p
  JOIN core.fixtures f ON f.provider_fixture_id = (p.params->>'fixture')::bigint
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE p.endpoint = %(endpoint)s AND p.params->>'half' = 'true' AND p.params->>'fixture' ~ '^[0-9]+$'
   AND NOT EXISTS (SELECT 1 FROM core.fixture_period_asks a WHERE a.fixture_id = f.id)
 ORDER BY f.id, p.fetched_at DESC
 LIMIT %(limit)s
"""


def load_probe_answers(conn: psycopg.Connection, store: Any, *, limit: int = 5000) -> dict[str, int]:
    """Keep, with no request, every ``half=true`` answer the RAW index holds for a match that has no ask yet (the probe of PM-01-05):
    what it measured counts for the decision and its figures are stored. ``store`` is the RAW ``PayloadStore``."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PROBE_ANSWERS_SQL, {"endpoint": ENDPOINT, "limit": limit})
        found = cur.fetchall()
    done: Counter[str] = Counter()
    for r in found:
        try:
            body = (store.load(str(r["file_path"])) or {}).get("body") or {}
        except (OSError, ValueError) as exc:
            done["unreadable"] += 1
            log.warning("period_stats.probe_unreadable", path=str(r["file_path"]), error=type(exc).__name__)
            continue
        answer = parse_period_answer(body, int(r["provider_fixture_id"]))
        with conn.transaction(), conn.cursor() as cur:
            apply_answer(cur, fixture_id=int(r["fixture_id"]), home_provider_id=int(r["home_provider_id"]),
                         away_provider_id=int(r["away_provider_id"]), answer=answer, payload_hash=str(r["hash"]),
                         fetched_at=r["fetched_at"], channel="probe", run_id=None)
        done[answer.outcome] += 1
    conn.commit()
    return dict(done)


def probation_left(states: Mapping[int, CompetitionState], competition_id: int) -> int:
    """How many more matches a competition is asked before it has a decision (0 once decided)."""
    return max(0, MIN_SAMPLE - states.get(competition_id, CompetitionState()).asked)


def stats_built(state: CompetitionState) -> list[str]:
    """The statistics of a competition that are built, for the reports."""
    return [s for s, d in decide(state.asked, state.filled).items() if d.build]

