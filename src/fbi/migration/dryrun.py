"""End-to-end dry run of the historical migration, before any request is paid for.

Creates a scratch database next to the real one, migrates it, catalogues the
two invented competitions of fbi.migration.fake_api, seeds every kind of unit,
and runs the real engine through the real client against the fake HTTP layer:

    API -> RAW (payload files) -> HASH -> NORMALISED rows -> POSTGRES
        -> LEDGER (ingestion runs) -> QUOTA (raw.provider_quota) -> IDEMPOTENCY

with an interruption in the middle (a unit left 'running' by a "crashed"
process) to prove the resume. Then it checks each link and drops the scratch
database. The real database is never touched: the scratch name is generated
and checked before anything is written.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg.rows import tuple_row

from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.backfill import add_unit, progress, run_backfill
from fbi.ingestion.details import (
    apply_coverage,
    apply_fixture_details,
    apply_injuries,
    apply_standings,
)
from fbi.ingestion.payload_store import PayloadStore, body_hash
from fbi.migration.config import ROOT
from fbi.migration.fake_api import LEAGUES, SEASONS, FakeApi, fixtures_of
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.details import (
    iter_coverage,
    iter_fixture_details,
    iter_injuries,
    iter_standings,
)
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.quota import PersistentDailyQuota
from fbi.providers.ratelimit import TokenBucket

SCRATCH_PREFIX = "fbi_dryrun_"
COUNTED_TABLES = ("core.fixtures", "core.fixture_results", "core.fixture_team_stats", "core.fixture_events",
                  "core.fixture_lineups", "core.fixture_lineup_players", "core.fixture_player_stats",
                  "core.standings", "core.player_absences", "raw.league_coverage", "raw.ingestion_payloads")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class DryRunReport:
    database: str
    requests: int = 0
    units: dict[str, int] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    kept: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)


def _dsn(admin_url: str, database: str) -> str:
    head, _, _ = admin_url.rpartition("/")
    return f"{head}/{database}"


def _migrate(dsn: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    previous = os.environ.get("FBI_DATABASE_URL")
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    out = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        for t in COUNTED_TABLES:
            cur.execute(f"SELECT count(*) FROM {t}")
            row = cur.fetchone()
            out[t] = int(row[0]) if row else 0
    return out


def _seed(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for lid, name in LEAGUES.items():
            cur.execute(
                "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                "VALUES (%s, %s, 'league', 'club', 'domestic_league')", (lid, name))
        add_unit(cur, kind="league_coverage", league_id=0, season=0, endpoint="/leagues", params={}, priority=0,
                 tier=1)
        for lid in LEAGUES:
            for s in SEASONS:
                base = {"league": lid, "season": s}
                add_unit(cur, kind="fixtures_season", league_id=lid, season=s, endpoint="/fixtures",
                         params={**base, "then_details": True}, priority=100, tier=1)
                for kind, ep in (("standings_season", "/standings"), ("injuries_season", "/injuries"),
                                 ("teams_season", "/teams")):
                    add_unit(cur, kind=kind, league_id=lid, season=s, endpoint=ep, params=base, priority=300,
                             tier=1)
        add_unit(cur, kind="players_season", league_id=9901, season=2024, endpoint="/players",
                 params={"league": 9901, "season": 2024, "page": 1}, priority=600, tier=1, page=1)
    conn.commit()


def _provider(dsn: str, store: PayloadStore, api: FakeApi) -> ApiFootballProvider:
    async def no_sleep(_s: float) -> None:
        return None

    settings = ApiFootballSettings(key="dry-run-not-a-key", plan="pro", daily_budget=7500, max_retries=0)
    quota = PersistentDailyQuota(budget=7500, connect=lambda: psycopg.connect(dsn, autocommit=True))
    return ApiFootballProvider(ApiFootballClient(settings, store, transport=api.transport(),
                                                 rate_limiter=TokenBucket(10_000, sleep=no_sleep), quota=quota))


def _replay(conn: psycopg.Connection, provider: ApiFootballProvider, store: PayloadStore) -> None:
    """Apply every stored payload again, from its file. Must change nothing."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT hash, endpoint, params, file_path, fetched_at FROM raw.ingestion_payloads ORDER BY fetched_at")
        rows = cur.fetchall()
        cur.execute("SELECT c.provider_league_id, cs.season, cs.id FROM core.competition_seasons cs "
                    "JOIN core.competitions c ON c.id = cs.competition_id")
        seasons = {(int(a), int(b)): int(c) for a, b, c in cur.fetchall()}
    for h, endpoint, params, path, fetched_at in rows:
        body = store.load(str(path))["body"]
        p = dict(params or {})
        if endpoint == "/fixtures" and "ids" in p:
            apply_fixture_details(conn, iter_fixture_details(body), payload_hash=h, fetched_at=fetched_at)
        elif endpoint == "/fixtures":
            apply_fixtures_payload(conn, provider, body, payload_hash=h, fetched_at=fetched_at, season_ids=seasons)
        elif endpoint == "/standings":
            apply_standings(conn, iter_standings(body), fetched_at=fetched_at)
        elif endpoint == "/injuries":
            apply_injuries(conn, iter_injuries(body), payload_hash=h, fetched_at=fetched_at)
        elif endpoint == "/leagues":
            apply_coverage(conn, iter_coverage(body), payload_hash=h, fetched_at=fetched_at)
    conn.commit()


async def dry_run(admin_url: str, *, keep: bool = False, work_dir: Path | None = None) -> DryRunReport:
    name = f"{SCRATCH_PREFIX}{uuid.uuid4().hex[:10]}"
    if not name.startswith(SCRATCH_PREFIX):  # the only database this function ever writes to
        raise RuntimeError("refusing to run outside a scratch database")
    report = DryRunReport(name)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = _dsn(admin_url, name)
    tmp = tempfile.TemporaryDirectory(prefix="fbi-dryrun-raw-") if work_dir is None else None
    raw_root = Path(tmp.name) if tmp is not None else Path(work_dir or ".")
    try:
        _migrate(dsn)
        store = PayloadStore(raw_root)
        api = FakeApi()
        with psycopg.connect(dsn) as conn:
            _seed(conn)
            provider = _provider(dsn, store, api)
            try:
                # 1. A first run stops at its allowance ...
                first = await run_backfill(conn, provider, max_requests=5, daily_budget=7500)
                # ... and a process "dies" holding a unit.
                with conn.cursor() as cur:
                    cur.execute("UPDATE raw.backfill_tasks SET status = 'running', started_at = now() - %s "
                                "WHERE id = (SELECT id FROM raw.backfill_tasks WHERE status = 'pending' "
                                "ORDER BY id LIMIT 1) RETURNING id", (timedelta(hours=1),))
                    crashed = cur.fetchone()
                conn.commit()
                # 2. The next runs carry on until nothing is pending (details are created on the way).
                runs = [first]
                for _ in range(20):
                    r = await run_backfill(conn, provider, max_requests=1000, daily_budget=7500)
                    runs.append(r)
                    if r.attempted == 0:
                        break
                states = progress(conn)
                with conn.cursor(row_factory=tuple_row) as cur:
                    cur.execute("SELECT kind, count(*) FROM raw.backfill_tasks GROUP BY kind")
                    report.units = {str(k): int(v) for k, v in cur.fetchall()}
                    cur.execute("SELECT coalesce(sum(requests_spent), 0) FROM raw.backfill_tasks")
                    spent_units = int(cur.fetchone()[0])  # type: ignore[index]
                    cur.execute("SELECT coalesce(sum(api_calls), 0) FROM raw.ingestion_runs "
                                "WHERE job_type = 'historical_backfill'")
                    spent_ledger = int(cur.fetchone()[0])  # type: ignore[index]
                    cur.execute("SELECT coalesce(sum(spent), 0) FROM raw.provider_quota")
                    spent_quota = int(cur.fetchone()[0])  # type: ignore[index]
                    cur.execute("SELECT status FROM raw.backfill_tasks WHERE id = %s",
                                (crashed[0] if crashed else -1,))
                    resumed = cur.fetchone()
                report.requests = len(api.calls)
                report.rows = _counts(conn)
                expected_fixtures = sum(len(fixtures_of(lid, s)) for lid in LEAGUES for s in SEASONS)
                c = report.checks
                c.append(Check("every unit completed", set(states) == {"done"}, str(states)))
                c.append(Check("API: one request per unit", report.requests == spent_units,
                               f"{report.requests} requests made, {spent_units} recorded on units"))
                c.append(Check("LEDGER: runs account for every request", spent_ledger == report.requests,
                               f"ingestion runs recorded {spent_ledger}"))
                c.append(Check("QUOTA: the persistent counter saw every request", spent_quota == report.requests,
                               f"raw.provider_quota spent {spent_quota}"))
                c.append(Check("RESUME: a unit left running by a dead process was finished",
                               crashed is not None and resumed is not None and resumed[0] == "done",
                               f"unit {crashed[0] if crashed else None} -> {resumed[0] if resumed else None}"))
                with conn.cursor(row_factory=tuple_row) as cur:
                    cur.execute("SELECT hash, file_path FROM raw.ingestion_payloads")
                    payloads = cur.fetchall()
                bad = [h for h, fp in payloads if body_hash(store.load(str(fp))["body"]) != h]
                c.append(Check("RAW+HASH: every payload file re-hashes to its recorded hash",
                               not bad and len(payloads) == report.requests,
                               f"{len(payloads)} payloads, {len(bad)} mismatched"))
                r = report.rows
                c.append(Check("NORMALISED: every fixture, result and detail block landed",
                               r["core.fixtures"] == expected_fixtures and r["core.fixture_results"] == expected_fixtures
                               and r["core.fixture_team_stats"] == 2 * expected_fixtures
                               and r["core.fixture_lineups"] == 2 * expected_fixtures
                               and r["core.fixture_events"] > 0 and r["core.fixture_player_stats"] > 0
                               and r["raw.league_coverage"] == len(LEAGUES) * len(SEASONS)
                               and r["core.standings"] > 0 and r["core.player_absences"] > 0,
                               ", ".join(f"{k.split('.')[1]}={v}" for k, v in r.items())))
                before = dict(r)
                _replay(conn, provider, store)
                again = await run_backfill(conn, provider, max_requests=1000, daily_budget=7500)
                after = _counts(conn)
                c.append(Check("IDEMPOTENCY: replaying every payload and running again changes nothing",
                               after == before and again.attempted == 0 and len(api.calls) == report.requests,
                               f"rows unchanged: {after == before}; extra requests: {len(api.calls) - report.requests}"))
                kinds = Counter(k for k in report.units)
                c.append(Check("every unit kind exercised", len(kinds) == 7, ", ".join(sorted(kinds))))
            finally:
                await provider.aclose()
    finally:
        if keep:
            report.kept = True
        else:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                              "AND pid <> pg_backend_pid()", (name,))
                admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        if tmp is not None:
            tmp.cleanup()
    return report
