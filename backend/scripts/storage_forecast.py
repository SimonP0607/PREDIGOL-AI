"""PrediGol storage, measured, and its growth, projected.

    python -m scripts.storage_forecast                 # read-only, 0 provider requests
    python -m scripts.storage_forecast --days 10       # measuring window (complete days only)

Writes data/storage/<stamp>/storage.json and STORAGE.md.

What is MEASURED: the database size and, per growing table, its bytes per row (``pg_total_relation_size`` over the
row estimate, indexes included) and the rows it gained on each complete day of the window - a day the pick pipeline
ran at least 40 of its 48 times, so a day the machine was off does not count as a quiet day; RAW bytes per day by the
job that fetched them (``raw.ingestion_payloads`` joined to the ledger), one-off loads apart; the RAW and backup
folders on disk; the size of the newest database dump.

What is MODELLED, and said so in the report: in-play prices grow with the tracked fixtures played (28-day mean) x the
share of them priced in play x the change-only rows one such match leaves; every other table grows at the MEDIAN of
its complete days (a rebuild or a backfill day does not set the pace); real-time feature sets count distinct vectors
only (since 5 Oct 2026 an unchanged vector is not stored again); the reference feeds at their steady state (~3,500
requests a day once the first fill is done) at the bytes per request measured; +N leagues scale what grows with
fixtures by the fixtures they add (the capacity report's candidates) and what grows with leagues by the league count.

Retention (the HOT / WARM / COLD design in the report) is a projection, not something this script does: nothing is
deleted or moved.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.version import code_version

OUT_ROOT = Path("data/storage")
RAW_ROOT = Path("data/raw")
CAPACITY_ROOT = Path("data/capacity")
HORIZONS = {"30d": 30, "3m": 91, "6m": 182, "12m": 365}
MB = 1024 * 1024
GB = 1024 * MB

FIXTURE_DRIVEN = {"live_odds", "prematch_odds", "consensus", "final_prematch", "predictions", "feature_sets",
                  "candidates", "match_detail", "events", "player_extras", "lineups", "quality_issues",
                  "payload_index"}
"""The rest (the run ledger, the reference allowance) follows the number of leagues."""
"""Tables whose growth follows the number of tracked fixtures; the rest follows the number of leagues."""

ONE_OFF_JOBS = ("historical_backfill", "raw_backfill_fixture_facts", "raw_backfill_season_stats", "truth_audit",
                "capacity_probe", "context_refresh_manual", "plan_probe", "window_probe", "raw_replay", "raw_transfer")
STEADY_REFERENCE_REQUESTS = 3_500
"""fbi.ingestion.reference: the reference feeds' cost per day once their first fill (~23,500 requests) is done."""

HOT_DAYS_LIVE = 90
"""In-play prices older than this leave PostgreSQL for a monthly Parquet archive (WARM on disk, COLD off-site)."""
PARQUET_RATIO = 0.12
"""Assumed size of a zstd Parquet export relative to the same rows in PostgreSQL (indexes included): numeric time
series compress 6-12x; 0.12 is the cautious end. To be measured on the first archived month."""
DUMP_POLICY = (7, 4, 6)
"""Database dumps kept: 7 daily, 4 weekly, 6 monthly (17 at most)."""


@dataclass(frozen=True, slots=True)
class Grower:
    key: str
    label: str
    table: str
    ts: str
    count_sql: str | None = None
    """Rows per day, when it is not a plain count over ``ts`` (feature sets count distinct vectors)."""
    per_fixture: bool = False
    """Match data: rows per match that has them x tracked matches played per day (28 d) x the share that has them.
    Its day-by-day count is no guide - the history migration wrote years of it on the days measured."""
    lifetime_sql: str | None = None
    """Rows a tracked match leaves over its whole life (forecasts, prices, candidates from days before kick-off to the
    final read), for the matches played in the basis window: ``%(start)s``/``%(end)s`` bound the kick-off. Steadier
    than counting by day while deploys and backfills still come in bursts."""


LIFETIME = ("SELECT count(*) FROM {table} x JOIN core.fixtures f ON f.id = x.fixture_id "
            "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c "
            "ON c.id = cs.competition_id WHERE c.is_tracked AND f.status_group = 'finished' "
            "AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s{extra}")
REFERENCE_STEADY_BYTES_PER_DAY = 2 * 1024 * 1024
"""The reference feeds' tables (transfers, trophies, sidelined, coaches, leaders...) once their first fill is done:
change-only, people re-asked weekly - an allowance, not a measurement (the first fill is all the window shows)."""

GROWERS: tuple[Grower, ...] = (
    Grower("prematch_odds", "pre-match prices", "market.odds_snapshots", "captured_at",
           lifetime_sql=LIFETIME.format(table="market.odds_snapshots", extra="")),
    Grower("consensus", "market consensus", "market.market_consensus", "as_of",
           lifetime_sql=LIFETIME.format(table="market.market_consensus", extra="")),
    Grower("final_prematch", "final pre-match prices", "market.final_prematch_odds", "fetched_at",
           lifetime_sql=LIFETIME.format(table="market.final_prematch_odds", extra="")),
    Grower("predictions", "forecasts (real time)", "models.predictions", "created_at",
           lifetime_sql=LIFETIME.format(table="models.predictions", extra=" AND x.backtest_session_id IS NULL")),
    Grower("feature_sets", "real-time feature sets (+ their values)", "features.feature_sets", "generated_at",
           "SELECT date_trunc('day', generated_at) AS d, count(DISTINCT (fixture_id, input_hash, code_version)) "
           "FROM features.feature_sets WHERE generated_at >= %(start)s AND generated_at < %(end)s "
           "AND lineage->>'purpose' = 'real-time forecast' GROUP BY 1",
           lifetime_sql=LIFETIME.format(table="(SELECT DISTINCT fixture_id, input_hash, code_version FROM "
                                              "features.feature_sets WHERE lineage->>'purpose' = 'real-time "
                                              "forecast')", extra="")),
    Grower("candidates", "pick candidates", "picks.pick_candidates", "evaluated_at",
           lifetime_sql=LIFETIME.format(table="picks.pick_candidates", extra="")),
    Grower("match_detail", "player match statistics", "core.fixture_player_stats", "fetched_at", per_fixture=True),
    Grower("events", "match events", "core.fixture_events", "fetched_at", per_fixture=True),
    Grower("player_extras", "player match extras", "core.fixture_player_extras", "observed_at", per_fixture=True),
    Grower("lineups", "line-up players", "core.fixture_lineup_players", "", per_fixture=True),
    Grower("quality_issues", "data-quality issues (routine jobs; audits apart)", "audit.data_quality_issues",
           "detected_at",
           "SELECT date_trunc('day', q.detected_at) AS d, count(*) FROM audit.data_quality_issues q "
           "LEFT JOIN raw.ingestion_runs r ON r.id = q.run_id WHERE q.detected_at >= %(start)s "
           "AND q.detected_at < %(end)s AND (r.job_type IS NULL OR NOT (r.job_type = ANY(%(oneoff)s) "
           "OR r.job_type LIKE 'truth%%')) GROUP BY 1"),
    Grower("payload_index", "RAW payload index", "raw.ingestion_payloads", "fetched_at"),
    Grower("runs", "run ledger", "raw.ingestion_runs", "started_at"),
)


@dataclass
class TableGrowth:
    key: str
    label: str
    table: str
    bytes_per_row: float
    bytes_total: float = 0.0
    rows_per_day: list[int] = field(default_factory=list)
    steady_rows_per_day: float = 0.0
    steady_bytes_per_day: float = 0.0
    basis: str = "median of complete days"


def median(xs: Iterable[float]) -> float:
    values = [float(x) for x in xs]
    return statistics.median(values) if values else 0.0


def dumps_kept(day: int, policy: tuple[int, int, int] = DUMP_POLICY) -> int:
    """How many database dumps the retention policy holds ``day`` days after it starts."""
    daily, weekly, monthly = policy
    return min(day, daily) + min(day // 7, weekly) + min(day // 30, monthly)


def project(*, db0: float, raw0: float, archive0: float, db_per_day: float, live_per_day: float,
            raw_per_day: float, dump_ratio: float, days: int, retention: bool, live0: float = 0.0,
            hot_days_live: int = HOT_DAYS_LIVE, parquet_ratio: float = PARQUET_RATIO) -> dict[str, float]:
    """Bytes held ``days`` from now: database, RAW, archive (Parquet), backups and the total.

    Without retention the database keeps every in-play price. With it, in-play prices older than ``hot_days_live``
    leave the database for the archive at ``parquet_ratio`` of their size (``live0``: what the database holds today,
    all of it younger than the window). Backups are the dumps the policy keeps (each ``dump_ratio`` of the database
    at that point: an upper bound) plus one off-site copy of RAW and of the archive (both append-only)."""
    live_total = live0 + live_per_day * days
    live_db = live_per_day * hot_days_live if retention and days >= hot_days_live else live_total
    aged = live_total - live_db
    archive = archive0 + aged * parquet_ratio
    db = db0 - live0 + live_db + (db_per_day - live_per_day) * days
    raw = raw0 + raw_per_day * days
    backup = dumps_kept(days) * dump_ratio * db + raw + archive
    return {"db": db, "raw": raw, "archive": archive, "backup": backup, "total": db + raw + archive + backup}


def _complete_days(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> list[datetime]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT date_trunc('day', started_at) AS d, count(*) FROM raw.ingestion_runs "
                    "WHERE job_type = 'pick_pipeline' AND started_at >= %s AND started_at < %s GROUP BY 1 "
                    "HAVING count(*) >= 40 ORDER BY 1", (start, end))
        return [r[0] for r in cur.fetchall()]


def _bytes_per_row(conn: psycopg.Connection[Any], table: str) -> tuple[float, float]:
    """(bytes per row with indexes, row estimate); a partitioned table is summed over its partitions."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0), coalesce(sum(greatest(c.reltuples, 0)), 0) "
            "FROM pg_class c WHERE c.oid = %(t)s::regclass AND c.relkind = 'r' "
            "OR c.oid IN (SELECT inhrelid FROM pg_inherits WHERE inhparent = %(t)s::regclass)", {"t": table})
        size, rows = cur.fetchone() or (0, 0)
    return (float(size) / float(rows) if rows else 0.0), float(rows)


def _daily_rows(conn: psycopg.Connection[Any], g: Grower, start: datetime, end: datetime) -> dict[datetime, int]:
    sql = g.count_sql or (f"SELECT date_trunc('day', {g.ts}) AS d, count(*) FROM {g.table} "
                          f"WHERE {g.ts} >= %(start)s AND {g.ts} < %(end)s GROUP BY 1")
    if g.per_fixture and not g.ts:
        return {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(sql, {"start": start, "end": end, "oneoff": list(ONE_OFF_JOBS)})
        return {r[0]: int(r[1]) for r in cur.fetchall()}


def _per_fixture(conn: psycopg.Connection[Any], table: str, start: datetime, end: datetime) -> tuple[float, float]:
    """(rows per match that has them, share of the tracked matches played in [start, end) that have them)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(f"SELECT count(*)::float / nullif(count(DISTINCT fixture_id), 0) FROM {table}")
        per = float((cur.fetchone() or (0,))[0] or 0.0)
        cur.execute(
            f"SELECT avg((EXISTS (SELECT 1 FROM {table} x WHERE x.fixture_id = f.id))::int)::float "
            "FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id WHERE c.is_tracked AND f.status_group = 'finished' "
            "AND f.kickoff_at >= %s AND f.kickoff_at < %s", (start, end))
        share = float((cur.fetchone() or (0,))[0] or 0.0)
    return per, share


def _scalar(conn: psycopg.Connection[Any], sql: str, params: Any = None) -> Any:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return None if row is None else row[0]


def _folder_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _backup_dirs() -> list[Path]:
    raw = os.environ.get("FBI_BACKUP_DIRS")
    if raw:
        return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    return [Path.home() / "backups", Path("data/backups")]


def measure(conn: psycopg.Connection[Any], at: datetime, days: int) -> dict[str, Any]:
    end = at.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    # Basis days run the pipeline as it is now: from the first whole day of in-play capture on (the ledger records
    # every live tick; the in-play prices themselves are not kept since revision 0068).
    first_live = _scalar(conn, "SELECT min(started_at) FROM raw.ingestion_runs WHERE job_type = 'live_odds_capture'")
    if first_live is not None:
        start = max(start, first_live.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    complete = _complete_days(conn, start, end)
    month_ago = end - timedelta(days=28)
    tables: list[TableGrowth] = []
    for g in GROWERS:
        with conn.transaction():
            try:
                per_row, rows_now = _bytes_per_row(conn, g.table)
                daily = _daily_rows(conn, g, start, end)
            except psycopg.Error:
                continue
        if g.key == "feature_sets":
            values_per_set = float(_scalar(conn, "SELECT count(*)::float / nullif((SELECT count(*) FROM "
                                           "features.feature_sets), 0) FROM features.fixture_features") or 0.0)
            per_row += values_per_set * _bytes_per_row(conn, "features.fixture_features")[0]
        t = TableGrowth(g.key, g.label, g.table, round(per_row, 1), round(per_row * rows_now),
                        [daily.get(d, 0) for d in complete])
        t.steady_rows_per_day = median(t.rows_per_day)
        if g.lifetime_sql:
            matches = fixtures_per_day(conn, start, end) * max((end - start).days, 1)
            rows = float(_scalar(conn, g.lifetime_sql, {"start": start, "end": end}) or 0)
            per_match = rows / matches if matches else 0.0
            t.steady_rows_per_day = per_match * fixtures_per_day(conn, month_ago, end)
            t.basis = (f"{per_match:,.1f} rows per tracked match played since {start:%d %b} (its whole life) x "
                       "matches per day (28 d)")
        if g.per_fixture:
            per, share = _per_fixture(conn, g.table, month_ago, end)
            t.steady_rows_per_day = per * share * fixtures_per_day(conn, month_ago, end)
            t.basis = (f"{per:,.1f} rows per match x {share:.0%} of tracked matches played (28 d) have them x "
                       "matches per day")
        tables.append(t)

    tables.append(TableGrowth("reference", "reference feeds after their first fill (allowance)",
                              "core.player_transfers, core.person_trophies, ...", 0.0, 0.0, [],
                              basis="allowance: change-only, people re-asked weekly"))
    # In-play prices: since revision 0068 only the current book is kept - bounded by what is in play at one
    # instant, emptied as matches end - so they add nothing a day. Shown as a row so the report says so.
    fixtures_28d = fixtures_per_day(conn, month_ago, end)
    book_fixtures = int(_scalar(conn, "SELECT count(*) FROM market.live_fixture_current") or 0)
    book_quotes = int(_scalar(conn, "SELECT count(*) FROM market.live_odds_current") or 0)
    live = {"fixtures_per_day_28d": round(fixtures_28d, 1), "in_play_book": "ephemeral (revision 0068)",
            "book_fixtures_now": book_fixtures, "book_quotes_now": book_quotes}
    tables.append(TableGrowth("live_book", "in-play prices (current book only, ephemeral)", "market.live_odds_current",
                              0.0, float(_scalar(conn, "SELECT pg_total_relation_size('market.live_odds_current') + "
                                                       "pg_total_relation_size('market.live_fixture_current')") or 0),
                              [], basis="bounded by the matches in play at one instant; emptied when they end"))
    finished = 0
    if complete:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT count(*) FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = "
                "f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id WHERE c.is_tracked "
                "AND f.status_group = 'finished' AND date_trunc('day', f.kickoff_at) = ANY(%s)", (complete,))
            finished = int((cur.fetchone() or (0,))[0])
    for t in tables:
        t.steady_bytes_per_day = (REFERENCE_STEADY_BYTES_PER_DAY if t.key == "reference"
                                  else t.steady_rows_per_day * t.bytes_per_row)

    # RAW: bytes a day by the job that fetched them; one-off loads apart, the reference feeds at their steady state.
    raw_days: dict[str, list[int]] = {"recurring": [], "one_off": []}
    reference_bytes_per_request = 0.0
    if complete:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT date_trunc('day', p.fetched_at) AS d, "
                "coalesce(sum(p.bytes) FILTER (WHERE (r.job_type IS NULL OR NOT (r.job_type = ANY(%(oneoff)s) "
                "OR r.job_type = 'reference_refresh')) AND r.job_type IS DISTINCT FROM 'live_odds_capture'), 0), "
                "coalesce(sum(p.bytes) FILTER (WHERE r.job_type = ANY(%(oneoff)s) OR r.job_type = 'reference_refresh'), 0) "
                "FROM raw.ingestion_payloads p LEFT JOIN raw.ingestion_runs r ON r.id = p.run_id "
                "WHERE date_trunc('day', p.fetched_at) = ANY(%(days)s) GROUP BY 1",
                {"oneoff": list(ONE_OFF_JOBS), "days": complete})
            for _, rec, one in cur.fetchall():
                raw_days["recurring"].append(int(rec))
                raw_days["one_off"].append(int(one))
            cur.execute("SELECT avg(p.bytes) FROM raw.ingestion_payloads p JOIN raw.ingestion_runs r ON "
                        "r.id = p.run_id WHERE r.job_type = 'reference_refresh'")
            reference_bytes_per_request = float((cur.fetchone() or (0,))[0] or 0.0)
    # Recurring RAW follows the matches (the in-play payloads are no longer kept, revision 0068): bytes per tracked match played
    # on the basis days x matches per day (28 d), plus the reference feeds at their steady state.
    raw_per_fixture = sum(raw_days["recurring"]) / finished if finished else 0.0
    raw_per_day = raw_per_fixture * fixtures_28d + STEADY_REFERENCE_REQUESTS * reference_bytes_per_request

    backups = []
    for d in _backup_dirs():
        if d.is_dir():
            backups += [(p.name, p.stat().st_size, p.stat().st_mtime) for p in d.iterdir() if p.is_file()]
    dumps = sorted((b for b in backups if b[0].endswith(".dump") and "tables" not in b[0]), key=lambda b: b[2])
    db_bytes = int(_scalar(conn, "SELECT pg_database_size(current_database())") or 0)
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat(),
                   "complete_days": [d.date().isoformat() for d in complete]},
        "database_bytes": db_bytes,
        "wal_bytes": _wal_bytes(conn),
        "tables": [asdict(t) for t in tables],
        "live_model": live,
        "raw": {"on_disk_bytes": _folder_bytes(RAW_ROOT), "recurring_bytes_per_day": raw_days["recurring"],
                "one_off_bytes_per_day": raw_days["one_off"],
                "reference_bytes_per_request": round(reference_bytes_per_request),
                "recurring_bytes_per_match": round(raw_per_fixture),
                "steady_bytes_per_day": round(raw_per_day)},
        "backups": {"files": len(backups), "bytes": sum(b[1] for b in backups),
                    "newest_dump": None if not dumps else {"name": dumps[-1][0], "bytes": dumps[-1][1]},
                    "dump_ratio": round(dumps[-1][1] / db_bytes, 4) if dumps and db_bytes else 0.06},
        "logs_bytes": _folder_bytes(Path.home() / ".fbi") + _folder_bytes(Path("logs")),
    }


def fixtures_per_day(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> float:
    """Tracked matches played per day in [start, end)."""
    days = max((end - start).total_seconds() / 86400, 1.0)
    n = _scalar(conn, "SELECT count(*) FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = "
                      "f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id WHERE c.is_tracked "
                      "AND f.status_group = 'finished' AND f.kickoff_at >= %s AND f.kickoff_at < %s", (start, end))
    return float(n or 0) / days


def _wal_bytes(conn: psycopg.Connection[Any]) -> int | None:
    try:
        with conn.transaction():
            return int(_scalar(conn, "SELECT coalesce(sum(size), 0) FROM pg_ls_waldir()") or 0)
    except psycopg.Error:
        return None


def _added_fixtures(added: int) -> tuple[float, int]:
    """(fixtures a day the top ``added`` candidate leagues bring, tracked leagues) from the newest capacity report."""
    reports = sorted(CAPACITY_ROOT.glob("*/capacity.json"))
    if not reports:
        return 0.0, 0
    r = json.loads(reports[-1].read_text())
    row = next((s for s in r.get("scenarios", []) if s.get("added_leagues") == added), None)
    return float(row["added_fixtures_per_day_mean"]) if row else 0.0, int(r["measured"]["tracked_competitions"])


def forecast(m: dict[str, Any], *, added_leagues: int = 50) -> dict[str, Any]:
    tables = m["tables"]
    by_key = {t["key"]: t for t in tables}
    db_per_day = sum(t["steady_bytes_per_day"] for t in tables)
    live_per_day = by_key.get("live_odds", {}).get("steady_bytes_per_day", 0.0)
    live0 = float(by_key.get("live_odds", {}).get("bytes_total", 0.0))
    fixtures = float(m["live_model"].get("fixtures_per_day_28d") or 0.0)
    extra_fx, leagues = _added_fixtures(added_leagues)
    f_fix = 1 + (extra_fx / fixtures if fixtures else 0.0)
    f_league = (leagues + added_leagues) / leagues if leagues else 1.0
    scaled = sum(t["steady_bytes_per_day"] * (f_fix if t["key"] in FIXTURE_DRIVEN else f_league) for t in tables)
    live_scaled = live_per_day * f_fix
    db0, raw0, ratio = float(m["database_bytes"]), float(m["raw"]["on_disk_bytes"]), float(m["backups"]["dump_ratio"])
    out: dict[str, Any] = {"db_bytes_per_day": round(db_per_day), "live_bytes_per_day": round(live_per_day),
                           "raw_bytes_per_day": m["raw"]["steady_bytes_per_day"],
                           "added_leagues": added_leagues, "added_fixtures_per_day": extra_fx,
                           "fixture_factor": round(f_fix, 3), "league_factor": round(f_league, 3), "scenarios": {}}
    for name, (dbd, lvd, rawd) in {
        "current": (db_per_day, live_per_day, m["raw"]["steady_bytes_per_day"]),
        f"plus_{added_leagues}": (scaled, live_scaled, m["raw"]["steady_bytes_per_day"] * f_fix),
    }.items():
        for retention in (False, True):
            label = f"{name}{'_retention' if retention else ''}"
            out["scenarios"][label] = {h: {k: round(v) for k, v in project(
                db0=db0, raw0=raw0, archive0=0.0, db_per_day=dbd, live_per_day=lvd, raw_per_day=rawd,
                dump_ratio=ratio, days=d, retention=retention, live0=live0).items()} for h, d in HORIZONS.items()}
    return out


def _gb(x: float) -> str:
    return f"{x / GB:,.1f} GB"


def markdown(report: dict[str, Any]) -> str:
    m, f = report["measured"], report["forecast"]
    lines = [f"# PrediGol storage - {report['at'][:16]}Z", "",
             f"Code {report['code_version']}. Read-only; nothing was deleted or moved. Complete days measured: "
             f"{', '.join(m['window']['complete_days']) or 'none'}.", "",
             "## Now", "",
             f"* PostgreSQL: **{_gb(m['database_bytes'])}** (WAL {_gb(m['wal_bytes'] or 0)})",
             f"* RAW on disk: **{_gb(m['raw']['on_disk_bytes'])}**",
             f"* Backups: {m['backups']['files']} files, **{_gb(m['backups']['bytes'])}**; newest dump "
             f"{(m['backups']['newest_dump'] or {}).get('name', '-')} (dump = {m['backups']['dump_ratio']:.1%} of the "
             "database)",
             f"* Logs: {_gb(m['logs_bytes'])}", "",
             "## Growth per day (steady state)", "",
             "| What | Table | Bytes/row | Rows/day | MB/day | Basis |", "|---|---|---:|---:|---:|---|"]
    for t in sorted(m["tables"], key=lambda t: -t["steady_bytes_per_day"]):
        lines.append(f"| {t['label']} | `{t['table']}` | {t['bytes_per_row']:,.0f} | {t['steady_rows_per_day']:,.0f} | "
                     f"{t['steady_bytes_per_day'] / MB:,.1f} | {t['basis']} |")
    lines += ["", f"Database: **{f['db_bytes_per_day'] / MB:,.0f} MB/day**, of which in-play prices "
              f"{f['live_bytes_per_day'] / MB:,.0f} MB. RAW: **{f['raw_bytes_per_day'] / MB:,.0f} MB/day** "
              f"(recurring jobs + the reference feeds at ~{STEADY_REFERENCE_REQUESTS:,} requests/day).", "",
              f"In-play model: {json.dumps(m['live_model'])}.", ""]
    for name, rows in f["scenarios"].items():
        lines += [f"## {name.replace('_', ' ')}", "", "| Horizon | DB | RAW | Archive | Backup | Total |",
                  "|---|---:|---:|---:|---:|---:|"]
        for h, v in rows.items():
            lines.append(f"| {h} | {_gb(v['db'])} | {_gb(v['raw'])} | {_gb(v['archive'])} | {_gb(v['backup'])} | "
                         f"{_gb(v['total'])} |")
        lines.append("")
    lines += [f"+{f['added_leagues']} leagues: +{f['added_fixtures_per_day']:.1f} fixtures/day (capacity report), "
              f"fixture-driven growth x{f['fixture_factor']}, league-driven x{f['league_factor']}.", "",
              "In-play prices are not kept since revision 0068 (only the current book, bounded). Retention assumed in "
              f"the *_retention rows: in-play prices older than {HOT_DAYS_LIVE} days would leave PostgreSQL for "
              f"monthly Parquet (zstd, ~{PARQUET_RATIO:.0%} of their size); "
              f"dumps kept {DUMP_POLICY[0]} daily / {DUMP_POLICY[1]} weekly / {DUMP_POLICY[2]} monthly; RAW and the "
              "archive copied off-site once (append-only, never deleted without a verified copy).", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="storage_forecast", description=__doc__)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--added-leagues", type=int, default=50)
    args = parser.parse_args()
    at = now()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            cur.execute("SET TIME ZONE 'UTC'")  # days are UTC days, like the window's bounds
        m = measure(conn, at, args.days)
    report = {"at": at.astimezone(UTC).isoformat(), "code_version": code_version(), "measured": m,
              "forecast": forecast(m, added_leagues=args.added_leagues)}
    folder = OUT_ROOT / at.strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "storage.json").write_text(json.dumps(report, indent=2, default=str))
    (folder / "STORAGE.md").write_text(markdown(report))
    print(folder / "STORAGE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
