"""Keep the current season's context fresh: league tables and injury reports.

Both were only ever fetched by the historical backfill, once per season: on
3 Oct 2026 the newest Premier League table in the database was from 29 Sep,
and an injury reported on Thursday for Saturday's match was not there. The
Match Center's "context" was therefore context for a week ago.

Two jobs share this module.

``refresh_context`` - every active season, every twelve hours: one ``/standings``
(leagues only; a cup has no table) and one ``/injuries`` per season, about 400
requests a day against a 60,000 guard.

``refresh_due_context`` - every half hour, only what a match made due. The
provider updates tables **every hour** and injuries **every four hours**
(``docs/api-football/06_UPDATE_FREQUENCIES.md``). A twelve-hour cycle therefore
left a table up to half a day behind the match that changed it. Now:

* a league's table is re-requested hourly from the moment its last match can
  have ended (kick-off + 2 h) until the provider's table changes after that
  moment, for at most a day;
* a season's injury list is re-requested every four hours while one of its
  matches kicks off in the next 48 hours.

Every request is recorded in ``core.context_checks`` - when it was asked, and
when its content last changed - whatever the answer. An unchanged table hashes
to the payload already stored, writes no snapshot row, and would otherwise be
indistinguishable from a table nobody asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError, QuotaExhaustedError
from fbi.core.logging import get_logger
from fbi.ingestion.details import apply_injuries, apply_standings_outcome
from fbi.ingestion.fixtures import ActiveSeason, active_seasons
from fbi.ingestion.ledger import RunCounters, RunLedger

log = get_logger(__name__)

MATCH_LENGTH = timedelta(hours=2)
"""Kick-off to final whistle, generously: the moment a table can first reflect a match."""
TABLE_RECHECK = timedelta(minutes=55)
"""Just under the provider's hourly table update, so each of its updates is seen once."""
TABLE_FOLLOW_FOR = timedelta(hours=24)
"""How long after a match a table that has not changed keeps being re-requested."""
INJURY_RECHECK = timedelta(hours=4)
INJURY_LOOKAHEAD = timedelta(hours=48)


def _league_type(conn: psycopg.Connection) -> dict[int, str]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT provider_league_id, type FROM core.competitions WHERE is_tracked")
        return {int(a): str(b) for a, b in cur.fetchall()}


def record_check(conn: psycopg.Connection, *, competition_season_id: int, dataset: str, checked_at: datetime,
                 payload_hash: str | None, rows_seen: int | None, rows_skipped: int = 0) -> None:
    """When this dataset of this season was last asked for, and when its answer last changed."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO core.context_checks (competition_season_id, dataset, checked_at, payload_hash, rows_seen, "
            "rows_skipped, changed_at) VALUES (%(cs)s, %(ds)s, %(at)s, %(h)s, %(n)s, %(sk)s, %(at)s) "
            "ON CONFLICT (competition_season_id, dataset) DO UPDATE SET "
            "  changed_at = CASE WHEN core.context_checks.payload_hash IS DISTINCT FROM EXCLUDED.payload_hash "
            "                    THEN EXCLUDED.checked_at ELSE core.context_checks.changed_at END, "
            "  checked_at = GREATEST(core.context_checks.checked_at, EXCLUDED.checked_at), "
            "  payload_hash = EXCLUDED.payload_hash, rows_seen = EXCLUDED.rows_seen, "
            "  rows_skipped = EXCLUDED.rows_skipped "
            "WHERE core.context_checks.checked_at <= EXCLUDED.checked_at",
            {"cs": competition_season_id, "ds": dataset, "at": checked_at, "h": payload_hash, "n": rows_seen,
             "sk": rows_skipped},
        )


@dataclass
class _Totals:
    tables: int = 0
    injuries: int = 0
    unknown_rows: int = 0

    def notes(self) -> str:
        text = f"{self.tables} tables, {self.injuries} absence rows"
        if self.unknown_rows:
            text += f", {self.unknown_rows} table rows for teams not in core.teams"
        return text


async def _refresh_one(conn: psycopg.Connection, provider: Any, ledger: RunLedger, run_id: int,
                       counters: RunCounters, totals: _Totals, season: ActiveSeason, what: str) -> bool:
    """One request for one dataset of one season. False when the run must stop (quota)."""
    try:
        if what == "standings":
            refs, raw = await provider.fetch_standings(league_id=season.provider_league_id, season=season.season)
        else:
            absences, raw = await provider.fetch_injuries(league_id=season.provider_league_id, season=season.season)
    except QuotaExhaustedError as exc:
        counters.errors.append(str(exc))
        counters.stopped_early = "quota"
        return False
    except ProviderError as exc:
        counters.api_calls += 1
        counters.errors.append(f"{season.name} {season.season} {what}: {exc}")
        return True
    counters.api_calls += 1
    counters.payloads_stored += ledger.record_payloads(run_id, [raw])
    observed = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
    if what == "standings":
        outcome = apply_standings_outcome(conn, refs, fetched_at=observed, payload_hash=raw.payload_hash)
        n = outcome.written
        totals.tables += 1 if n else 0
        totals.unknown_rows += len(outcome.unknown_teams)
        record_check(conn, competition_season_id=season.competition_season_id, dataset="standings",
                     checked_at=raw.fetched_at, payload_hash=raw.payload_hash, rows_seen=len(refs),
                     rows_skipped=len(outcome.unknown_teams))
    else:
        n = apply_injuries(conn, absences, payload_hash=raw.payload_hash, fetched_at=observed)
        totals.injuries += n
        record_check(conn, competition_season_id=season.competition_season_id, dataset="injuries",
                     checked_at=raw.fetched_at, payload_hash=raw.payload_hash, rows_seen=len(absences))
    counters.rows_inserted += n
    conn.commit()
    return True


async def refresh_context(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None,
                          max_requests: int = 400) -> RunCounters:
    moment = at or now()
    seasons = active_seasons(conn)
    kinds = _league_type(conn)
    ledger = RunLedger(conn)
    run_id = ledger.open("context_refresh", params={"seasons": len(seasons)}, scheduled_for=moment)
    counters = RunCounters()
    totals = _Totals()
    try:
        for s in seasons:
            for what in ("standings", "injuries"):
                if what == "standings" and kinds.get(s.provider_league_id) != "league":
                    continue
                if counters.api_calls >= max_requests:
                    counters.stopped_early = f"request cap {max_requests}"
                    break
                if not await _refresh_one(conn, provider, ledger, run_id, counters, totals, s, what):
                    break
            if counters.stopped_early:
                break
    finally:
        ledger.close(run_id, counters, notes=totals.notes())
        conn.commit()
    log.info("context_refresh.done", seasons=len(seasons), requests=counters.api_calls, tables=totals.tables,
             absences=totals.injuries, errors=len(counters.errors))
    return counters


DUE_TABLES_SQL = """
SELECT cs.id, c.provider_league_id, cs.season, c.name
  FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN LATERAL (
        SELECT max(f.kickoff_at) + %(match)s AS last_end
          FROM core.fixtures f
         WHERE f.competition_season_id = cs.id AND f.status_group = 'finished'
           AND f.kickoff_at > %(at)s - %(follow)s - %(match)s
  ) m ON m.last_end IS NOT NULL
  LEFT JOIN core.context_checks k ON k.competition_season_id = cs.id AND k.dataset = 'standings'
 WHERE c.is_tracked AND cs.is_current AND c.type = 'league'
   AND m.last_end <= %(at)s AND m.last_end > %(at)s - %(follow)s
   AND (k.changed_at IS NULL OR k.changed_at < m.last_end)
   AND (k.checked_at IS NULL OR k.checked_at < %(at)s - %(recheck)s)
 ORDER BY m.last_end
"""

DUE_INJURIES_SQL = """
SELECT cs.id, c.provider_league_id, cs.season, c.name
  FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.context_checks k ON k.competition_season_id = cs.id AND k.dataset = 'injuries'
 WHERE c.is_tracked AND cs.is_current
   AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = cs.id
                  AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %(at)s AND %(at)s + %(ahead)s)
   AND (k.checked_at IS NULL OR k.checked_at < %(at)s - %(recheck)s)
 ORDER BY c.provider_league_id
"""


def due_seasons(conn: psycopg.Connection, *, at: datetime) -> dict[str, list[ActiveSeason]]:
    """What a match has made due right now: tables to re-read, injury lists to re-read."""
    out: dict[str, list[ActiveSeason]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(DUE_TABLES_SQL, {"at": at, "match": MATCH_LENGTH, "follow": TABLE_FOLLOW_FOR,
                                     "recheck": TABLE_RECHECK})
        out["standings"] = [ActiveSeason(int(a), int(b), int(c), str(d)) for a, b, c, d in cur.fetchall()]
        cur.execute(DUE_INJURIES_SQL, {"at": at, "ahead": INJURY_LOOKAHEAD, "recheck": INJURY_RECHECK})
        out["injuries"] = [ActiveSeason(int(a), int(b), int(c), str(d)) for a, b, c, d in cur.fetchall()]
    return out


async def refresh_due_context(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None,
                              max_requests: int = 150) -> RunCounters:
    """Only the tables a finished match changed and the injury lists of the next two days."""
    moment = at or now()
    due = due_seasons(conn, at=moment)
    counters = RunCounters()
    if not any(due.values()):
        return counters  # nothing due: no run row, no request
    ledger = RunLedger(conn)
    run_id = ledger.open("context_due", params={k: len(v) for k, v in due.items()}, scheduled_for=moment)
    totals = _Totals()
    try:
        for what in ("standings", "injuries"):
            for s in due[what]:
                if counters.api_calls >= max_requests:
                    counters.stopped_early = f"request cap {max_requests}"
                    break
                if not await _refresh_one(conn, provider, ledger, run_id, counters, totals, s, what):
                    break
            if counters.stopped_early:
                break
    finally:
        ledger.close(run_id, counters, notes=totals.notes())
        conn.commit()
    log.info("context_due.done", tables_due=len(due["standings"]), injuries_due=len(due["injuries"]),
             requests=counters.api_calls, tables=totals.tables, absences=totals.injuries)
    return counters
