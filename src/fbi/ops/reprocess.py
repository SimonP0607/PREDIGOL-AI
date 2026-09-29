"""Re-derive normalized state from the raw payloads already on disk.

The architecture's promise is that RAW is the record and everything else is
derived from it. This is where that promise pays for itself.

``core.fixture_detail_coverage`` (revision 0028) records, per fixture and
dataset, whether the provider's payload carried the block at all. Every detail
payload we have ever fetched is still in the raw store, so that table can be
filled EXACTLY, from what the provider actually sent, without spending a single
request. The alternative - treating every fixture as never-fetched and asking
again - would have cost about 1,025 requests on Tier 1 alone and produced a worse
answer, because a re-fetch today cannot tell us what a payload contained a week
ago.

Replaying also back-fills the quality issues that the old code dropped in
silence: the contradictions it nulled, the line-ups short of eleven starters, the
statistic types it had no column for. Nothing is invented - every issue carries
the hash of the payload it was read from, and ``fetched_at`` stays the instant the
provider answered.

Idempotent by construction: every writer in ``ingestion.details`` refuses a
payload older than what is stored for that fixture, so replaying in ascending
``fetched_at`` order converges on the same state however often it runs.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.core.errors import FbiError
from fbi.ingestion.details import apply_fixture_details
from fbi.ingestion.payload_store import PayloadStore, body_hash
from fbi.providers.api_football.details import iter_fixture_details

log = structlog.get_logger(__name__)

DETAIL_ENDPOINT = "/fixtures"


class ReprocessError(FbiError):
    """The raw store does not hold what the index says it holds."""


@dataclass
class ReprocessReport:
    payloads_seen: int = 0
    payloads_applied: int = 0
    payloads_missing_file: int = 0
    payloads_not_rehashing: int = 0
    fixtures_touched: int = 0
    coverage_rows: int = 0
    issues_opened: int = 0
    issues_seen_again: int = 0
    skipped_stale: int = 0
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"payloads_seen": self.payloads_seen, "payloads_applied": self.payloads_applied,
                "payloads_missing_file": self.payloads_missing_file,
                "payloads_not_rehashing": self.payloads_not_rehashing,
                "fixtures_touched": self.fixtures_touched, "coverage_rows": self.coverage_rows,
                "issues_opened": self.issues_opened, "issues_seen_again": self.issues_seen_again,
                "skipped_stale": self.skipped_stale, "problems": self.problems[:20]}


def detail_payloads(conn: psycopg.Connection, *, limit: int | None = None,
                    hashes: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """Every stored ``/fixtures?ids=`` payload, oldest first.

    Oldest first matters: the writers only accept a payload at least as new as
    what is stored, so replaying in fetch order reproduces the history rather
    than fighting it. ``hashes`` narrows the replay to named payloads, for when a
    single batch needs re-deriving rather than the whole store.
    """
    sql = ("SELECT hash, endpoint, params, fetched_at, file_path, results_count "
           "FROM raw.ingestion_payloads "
           "WHERE endpoint = %s AND params ? 'ids' AND http_status = 200 ")
    params: list[object] = [DETAIL_ENDPOINT]
    if hashes is not None:
        sql += "AND hash = ANY(%s) "
        params.append(list(hashes))
    sql += "ORDER BY fetched_at, hash"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _bodies(store: PayloadStore, rows: list[dict[str, Any]], report: ReprocessReport,
            *, verify: bool) -> Iterator[tuple[dict[str, Any], dict[str, Any], datetime]]:
    for row in rows:
        report.payloads_seen += 1
        file_path = str(row["file_path"])
        try:
            envelope = store.load(file_path)
        except FileNotFoundError:
            report.payloads_missing_file += 1
            report.problems.append(f"{file_path}: indexed but not in the raw store")
            continue
        body = envelope.get("body")
        if verify and body_hash(body) != row["hash"]:
            report.payloads_not_rehashing += 1
            report.problems.append(f"{file_path}: does not re-hash to {str(row['hash'])[:12]}")
            continue
        if not isinstance(body, dict):
            report.problems.append(f"{file_path}: the stored body is not an object")
            continue
        yield row, body, row["fetched_at"]


def reprocess_fixture_details(
    conn: psycopg.Connection,
    raw_root: Path,
    *,
    apply: bool,
    limit: int | None = None,
    hashes: Sequence[str] | None = None,
    verify_hashes: bool = True,
) -> ReprocessReport:
    """Re-apply every stored detail payload. No provider call is made.

    ``apply=False`` reads and verifies everything and writes nothing, so the
    report can be inspected before touching the database.
    """
    report = ReprocessReport()
    store = PayloadStore(raw_root)
    rows = detail_payloads(conn, limit=limit, hashes=hashes)
    for row, body, fetched_at in _bodies(store, rows, report, verify=verify_hashes):
        details = list(iter_fixture_details(body))
        if not details:
            continue
        if not apply:
            report.payloads_applied += 1
            report.fixtures_touched += len(details)
            continue
        rep = apply_fixture_details(conn, details, payload_hash=str(row["hash"]),
                                   fetched_at=fetched_at, run_id=None)
        report.payloads_applied += 1
        report.fixtures_touched += rep.fixtures
        report.coverage_rows += rep.coverage_rows
        report.issues_opened += rep.issues_opened
        report.issues_seen_again += rep.issues_seen_again
        report.skipped_stale += rep.stale
        conn.commit()  # a checkpoint per payload: a crash resumes, never restarts
    if report.problems:
        log.warning("reprocess.problems", count=len(report.problems), first=report.problems[:3])
    log.info("reprocess.finished", **report.as_dict())
    if not apply:
        conn.rollback()
    return report


# ── coverage from what is already normalized ─────────────────────────────────

DATASET_SOURCES: tuple[tuple[str, str], ...] = (
    ("events", "core.fixture_events"),
    ("lineups", "core.fixture_lineups"),
    ("team_statistics", "core.fixture_team_stats"),
    ("player_statistics", "core.fixture_player_stats"),
)

DERIVE = """
INSERT INTO core.fixture_detail_coverage
    (fixture_id, source, dataset, block_present, rows_written, payload_hash, fetched_at)
SELECT d.fixture_id, %(source)s, %(dataset)s, true, d.rows_written, d.payload_hash, d.fetched_at
  FROM (
    SELECT fixture_id,
           count(*)                                            AS rows_written,
           (array_agg(payload_hash ORDER BY fetched_at DESC))[1] AS payload_hash,
           max(fetched_at)                                      AS fetched_at
      FROM {table}
     WHERE source = %(source)s
     GROUP BY fixture_id
  ) AS d
ON CONFLICT (fixture_id, source, dataset) DO NOTHING
"""


def derive_coverage_from_stored_detail(conn: psycopg.Connection, *, source: str = "api-football") -> dict[str, int]:
    """Fill coverage for fixtures whose detail is already normalized.

    Why this is needed as well as replaying payloads: ``PayloadStore`` deduplicates
    identical bodies, so a payload fetched twice keeps the FIRST fetch time in the
    index while the rows derived from the second carry the later one. Replaying the
    indexed payload then looks stale - the writers refuse to go backwards, which is
    right - and 1,809 fixtures that DO have events, line-ups, team statistics and
    player statistics were left with no coverage row and would have been requested
    again.

    So coverage is also derived from the normalized rows themselves. Each detail
    table carries its own ``payload_hash`` and ``fetched_at``, so the provenance is
    real: no timestamp is invented and nothing is backdated. Existing coverage rows
    are never overwritten, because a row written from a replayed payload knows
    something this cannot - which blocks were ABSENT.
    """
    written: dict[str, int] = {}
    with conn.cursor() as cur:
        for dataset, table in DATASET_SOURCES:
            cur.execute(DERIVE.format(table=table), {"source": source, "dataset": dataset})
            written[dataset] = max(cur.rowcount, 0)
    conn.commit()
    log.info("reprocess.coverage_derived", **written)
    return written


# ── identity from what is already normalized ─────────────────────────────────

DERIVE_PLAYERS = """
INSERT INTO core.players (provider_player_id, name, position, source_payload_hash, source_fetched_at)
SELECT d.provider_player_id, d.name, d.position, d.payload_hash, d.fetched_at
  FROM (
    SELECT p.provider_player_id,
           (array_agg(p.name ORDER BY p.fetched_at DESC))[1]         AS name,
           (array_agg(p.position ORDER BY p.fetched_at DESC))[1]     AS position,
           (array_agg(p.payload_hash ORDER BY p.fetched_at DESC))[1] AS payload_hash,
           max(p.fetched_at)                                          AS fetched_at
      FROM (
        SELECT lp.provider_player_id, lp.player_name AS name, lp.position, l.payload_hash, l.fetched_at
          FROM core.fixture_lineup_players lp
          JOIN core.fixture_lineups l
            ON l.fixture_id = lp.fixture_id AND l.team_side = lp.team_side AND l.source = lp.source
         WHERE lp.source = %(source)s AND lp.player_name IS NOT NULL
        UNION ALL
        SELECT ps.provider_player_id, ps.player_name, NULL, ps.payload_hash, ps.fetched_at
          FROM core.fixture_player_stats ps
         WHERE ps.source = %(source)s AND ps.player_name IS NOT NULL
      ) AS p
     GROUP BY p.provider_player_id
  ) AS d
ON CONFLICT (provider_player_id) DO NOTHING
"""

DERIVE_COACHES = """
INSERT INTO core.coaches (provider_coach_id, name, source_payload_hash, source_fetched_at)
SELECT d.provider_coach_id, d.name, d.payload_hash, d.fetched_at
  FROM (
    SELECT l.provider_coach_id,
           (array_agg(l.coach_name ORDER BY l.fetched_at DESC))[1]  AS name,
           (array_agg(l.payload_hash ORDER BY l.fetched_at DESC))[1] AS payload_hash,
           max(l.fetched_at)                                         AS fetched_at
      FROM core.fixture_lineups l
     WHERE l.source = %(source)s AND l.provider_coach_id IS NOT NULL AND l.coach_name IS NOT NULL
     GROUP BY l.provider_coach_id
  ) AS d
ON CONFLICT (provider_coach_id) DO NOTHING
"""

LINK_COACHES = """
UPDATE core.fixture_lineups l SET coach_id = c.id
  FROM core.coaches c
 WHERE l.provider_coach_id = c.provider_coach_id AND l.coach_id IS NULL
"""


def derive_identity_from_stored_detail(conn: psycopg.Connection, *,
                                       source: str = "api-football") -> dict[str, int]:
    """Players and coaches from the line-ups and statistics already stored.

    The same reasoning as ``derive_coverage_from_stored_detail``: every one of
    these rows already carries the payload it came from and the instant it was
    observed, so identity can be established exactly, for nothing, without asking
    the provider for names it has already sent us.

    ``DO NOTHING`` on conflict: a row written from /players or /coachs holds more
    than a line-up ever will, and must not be replaced by less.
    """
    written: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(DERIVE_PLAYERS, {"source": source})
        written["players"] = max(cur.rowcount, 0)
        cur.execute(DERIVE_COACHES, {"source": source})
        written["coaches"] = max(cur.rowcount, 0)
        cur.execute(LINK_COACHES)
        written["lineups_linked"] = max(cur.rowcount, 0)
    conn.commit()
    log.info("reprocess.identity_derived", **written)
    return written


TEAMS_ENDPOINT = "/teams"


def reprocess_teams(conn: psycopg.Connection, raw_root: Path, *, apply: bool,
                    verify_hashes: bool = True) -> ReprocessReport:
    """Normalise the /teams payloads that were only ever stored as bytes.

    Fifty-four of them, 1,604 teams, fetched and discarded because the unit wrote
    zero rows by design. Re-reading them costs nothing and fills core.teams and
    core.venues with what the provider already told us.
    """
    from fbi.ingestion.identity import apply_teams
    from fbi.providers.api_football.details import iter_teams

    report = ReprocessReport()
    store = PayloadStore(raw_root)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT hash, endpoint, params, fetched_at, file_path, results_count "
                    "FROM raw.ingestion_payloads WHERE endpoint = %s AND http_status = 200 "
                    "ORDER BY fetched_at, hash", (TEAMS_ENDPOINT,))
        rows = [dict(r) for r in cur.fetchall()]
    for row, body, fetched_at in _bodies(store, rows, report, verify=verify_hashes):
        teams = list(iter_teams(body))
        if not teams:
            continue
        report.payloads_applied += 1
        report.fixtures_touched += len(teams)
        if not apply:
            continue
        params = row["params"] if isinstance(row["params"], dict) else {}
        league, season = params.get("league"), params.get("season")
        season_id = _competition_season(conn, league, season)
        rep = apply_teams(conn, teams, payload_hash=str(row["hash"]), fetched_at=fetched_at,
                          competition_season_id=season_id)
        report.coverage_rows += rep.rows
        conn.commit()
    if not apply:
        conn.rollback()
    log.info("reprocess.teams_finished", **report.as_dict())
    return report


def _competition_season(conn: psycopg.Connection, league: Any, season: Any) -> int | None:
    try:
        league_id, season_year = int(league), int(season)
    except (TypeError, ValueError):
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cs.id FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE c.provider_league_id = %s AND cs.season = %s", (league_id, season_year))
        row = cur.fetchone()
    return int(row[0]) if row else None
