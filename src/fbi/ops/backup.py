"""Backups that are proven by restoring them.

A backup folder (data/backups/<UTC stamp>/) holds:

  db.dump        pg_dump custom format of the application database
  raw.tar        the raw payload store (already gzipped files; tar, no recompression)
  manifest.json  sha256 and size of both files; per table the row count and an
                 order-independent content fingerprint; per raw file its sha256;
                 the Alembic revision, server and tool versions

``restore_test`` restores the dump into a scratch database created for the
purpose, recomputes every table's fingerprint and compares; extracts the raw
archive to a temporary directory, re-hashes every file, and checks that every
raw.ingestion_payloads row of the RESTORED database points at a file that
exists and whose body still hashes to the recorded hash. Only then is the
backup called good. The scratch database and directory are removed unless
``keep`` is set; nothing else is touched.

Credentials: the password reaches pg_dump/pg_restore through the environment
of the child process only; it is never on a command line, in a log or in the
manifest.

Where the host has no PostgreSQL client tools (the WSL machine: Postgres runs in
Docker Desktop and apt needs a password), set ``FBI_PG_CONTAINER=fbi-postgres``:
pg_dump and pg_restore then run inside that container through ``docker`` (or
``docker.exe`` from WSL), connecting over its local socket - no password is
passed at all - and the dump streams through stdout/stdin.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import tuple_row

from fbi.ingestion.payload_store import PayloadStore, body_hash

MANIFEST = "manifest.json"
DUMP = "db.dump"
RAW = "raw.tar"
SESSION_SETTINGS = ("SET TIME ZONE 'UTC'", "SET extra_float_digits = 1", "SET DateStyle = 'ISO, YMD'",
                    "SET IntervalStyle = 'postgres'")
"""Row text depends on these; both fingerprints are computed under the same ones."""


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


PG_CONTAINER_ENV = "FBI_PG_CONTAINER"


def _libpq(url: str) -> tuple[list[str], dict[str, str]]:
    """Connection arguments for the pg_* tools and the environment carrying the password."""
    info = conninfo_to_dict(url)
    args = []
    for key, flag in (("host", "--host"), ("port", "--port"), ("user", "--username")):
        if info.get(key):
            args.append(f"{flag}={info[key]}")
    env = dict(os.environ)
    if info.get("password"):
        env["PGPASSWORD"] = str(info["password"])
    return args, env


def pg_command(tool: str, url: str) -> tuple[list[str], dict[str, str]]:
    """argv prefix and environment to run ``tool`` (pg_dump / pg_restore) against ``url``.

    The host's own binary when there is one; otherwise, with FBI_PG_CONTAINER set,
    the container's, through docker - as the URL's user, over the container's
    local socket, so no password travels anywhere."""
    local = shutil.which(tool)
    if local:
        args, env = _libpq(url)
        return [local, *args], env
    container = os.environ.get(PG_CONTAINER_ENV, "").strip()
    docker = shutil.which("docker") or shutil.which("docker.exe")
    if container and docker:
        user = conninfo_to_dict(url).get("user") or "postgres"
        return [docker, "exec", "-i", container, tool, f"--username={user}"], dict(os.environ)
    raise FileNotFoundError(f"{tool} is not installed here; install the PostgreSQL client or set "
                            f"{PG_CONTAINER_ENV} to the database container's name")


def _dbname(url: str) -> str:
    return str(conninfo_to_dict(url).get("dbname") or "")


def _with_db(url: str, dbname: str) -> str:
    head, _, _ = url.rpartition("/")
    return f"{head}/{dbname}"


def tables(conn: psycopg.Connection) -> list[tuple[str, str]]:
    """Every ordinary or partitioned table outside the system schemas - partitions
    are counted through their parent, never twice."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition "
            "AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%' "
            "AND n.nspname NOT LIKE 'pg_temp%' ORDER BY 1, 2")
        return [(str(a), str(b)) for a, b in cur.fetchall()]


def fingerprints(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    """schema.table -> {rows, md5}: md5 over the sorted md5s of every row's text."""
    out: dict[str, dict[str, Any]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        for stmt in SESSION_SETTINGS:
            cur.execute(stmt)
        for schema, name in tables(conn):
            cur.execute(sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) FROM "
                                "(SELECT md5(t::text) AS h FROM {}.{} t) s").format(sql.Identifier(schema),
                                                                                   sql.Identifier(name)))
            row = cur.fetchone()
            assert row is not None
            out[f"{schema}.{name}"] = {"rows": int(row[0]), "md5": str(row[1])}
    return out


def _alembic_revision(conn: psycopg.Connection) -> str | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT to_regclass('public.alembic_version')")
        reg = cur.fetchone()
        if reg is None or reg[0] is None:
            return None
        cur.execute("SELECT version_num FROM public.alembic_version")
        row = cur.fetchone()
        return None if row is None else str(row[0])


def _tool_version(tool: str, url: str) -> str:
    argv, env = pg_command(tool, url)
    base = [a for a in argv if not a.startswith("--")]
    out = subprocess.run([*base, "--version"], capture_output=True, text=True, check=True, env=env)
    return out.stdout.strip()


def raw_files(root: Path) -> dict[str, str]:
    """relative path -> sha256 for every file under the raw store."""
    if not root.is_dir():
        return {}
    return {str(p.relative_to(root)): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


@dataclass
class BackupReport:
    folder: Path
    manifest: dict[str, Any]
    seconds: float = 0.0


def create_backup(db_url: str, raw_root: Path, out_root: Path, *, label: str = "") -> BackupReport:
    started = datetime.now(UTC)
    stamp = started.strftime("%Y%m%dT%H%M%SZ") + (f"-{label}" if label else "")
    folder = out_root / stamp
    folder.mkdir(parents=True, exist_ok=False)
    dump_argv, env = pg_command("pg_dump", db_url)
    dbname = _dbname(db_url)
    with psycopg.connect(db_url) as conn:
        before = fingerprints(conn)
        revision = _alembic_revision(conn)
        server = str(conn.info.parameter_status("server_version"))
        # a consistent snapshot: the dump runs in its own transaction; comparing the
        # fingerprints taken before and after tells whether anything wrote meanwhile
        with (folder / DUMP).open("wb") as out:
            proc = subprocess.run([*dump_argv, "--format=custom", "--no-owner", "--no-privileges",
                                   f"--dbname={dbname}"], env=env, stdout=out, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {proc.stderr.decode(errors='replace').strip()[-300:]}")
        after = fingerprints(conn)
    changed = sorted(k for k in after if before.get(k) != after.get(k))
    files = raw_files(raw_root)
    with tarfile.open(folder / RAW, "w", format=tarfile.PAX_FORMAT) as tar:
        for rel in sorted(files):
            info = tar.gettarinfo(str(raw_root / rel), arcname=rel)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with (raw_root / rel).open("rb") as fh:
                tar.addfile(info, fh)
    manifest: dict[str, Any] = {
        "created_at": started.isoformat(),
        "database": dbname,
        "alembic_revision": revision,
        "server_version": server,
        "pg_dump": _tool_version("pg_dump", db_url),
        "files": {DUMP: {"sha256": sha256_file(folder / DUMP), "bytes": (folder / DUMP).stat().st_size},
                  RAW: {"sha256": sha256_file(folder / RAW), "bytes": (folder / RAW).stat().st_size}},
        "tables": after,
        "rows_total": sum(v["rows"] for v in after.values()),
        "changed_during_dump": changed,
        "raw_store": {"root": str(raw_root), "files": len(files),
                      "bytes": sum((raw_root / r).stat().st_size for r in files), "sha256": files},
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return BackupReport(folder, manifest, (datetime.now(UTC) - started).total_seconds())


def verify_files(folder: Path) -> list[str]:
    manifest = json.loads((folder / MANIFEST).read_text())
    problems = []
    for name, meta in manifest["files"].items():
        p = folder / name
        if not p.is_file():
            problems.append(f"{name}: missing")
        elif sha256_file(p) != meta["sha256"]:
            problems.append(f"{name}: sha256 differs from the manifest")
    return problems


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class RestoreReport:
    folder: Path
    scratch_db: str
    checks: list[Check] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


def restore_test(folder: Path, admin_url: str, *, keep: bool = False) -> RestoreReport:
    """Restore into a scratch database on the admin URL's server and prove it."""
    started = datetime.now(UTC)
    manifest = json.loads((folder / MANIFEST).read_text())
    scratch = f"fbi_restore_{secrets.token_hex(4)}"
    report = RestoreReport(folder, scratch)
    c = report.checks
    problems = verify_files(folder)
    c.append(Check("FILES: dump and raw archive match the manifest", not problems, "; ".join(problems) or "sha256 ok"))
    if problems:
        return report
    restore_argv, env = pg_command("pg_restore", admin_url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
    work = Path(tempfile.mkdtemp(prefix="fbi-restore-"))
    try:
        with (folder / DUMP).open("rb") as dump:
            proc = subprocess.run([*restore_argv, "--no-owner", "--no-privileges", "--exit-on-error",
                                   f"--dbname={scratch}"], env=env, stdin=dump, capture_output=True, text=True)
        c.append(Check("RESTORE: pg_restore into a new, empty database", proc.returncode == 0,
                       proc.stderr.strip()[-300:] or f"into {scratch}"))
        if proc.returncode != 0:
            return report
        scratch_url = _with_db(admin_url, scratch)
        with psycopg.connect(scratch_url) as conn:
            restored = fingerprints(conn)
            revision = _alembic_revision(conn)
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute("SELECT hash, file_path FROM raw.ingestion_payloads")
                index = [(str(h), str(p)) for h, p in cur.fetchall()]
        expected: dict[str, dict[str, Any]] = manifest["tables"]
        diff = sorted(k for k in set(expected) | set(restored) if expected.get(k) != restored.get(k))
        c.append(Check("TABLES: every table's row count and content fingerprint", not diff,
                       f"{len(restored)} tables, {sum(v['rows'] for v in restored.values())} rows"
                       + (f"; differ: {', '.join(diff[:8])}" if diff else "; identical")))
        c.append(Check("SCHEMA: the Alembic revision came back", revision == manifest["alembic_revision"],
                       f"{revision}"))
        raw_dir = work / "raw"
        raw_dir.mkdir()
        with tarfile.open(folder / RAW) as tar:
            tar.extractall(raw_dir, filter="data")
        got = raw_files(raw_dir)
        want: dict[str, str] = manifest["raw_store"]["sha256"]
        bad_files = sorted(k for k in set(want) | set(got) if want.get(k) != got.get(k))
        c.append(Check("RAW: every archived file re-hashes to its manifest sha256", not bad_files,
                       f"{len(got)} files" + (f"; differ: {', '.join(bad_files[:5])}" if bad_files else "")))
        present = [(h, p) for h, p in index if (raw_dir / p).is_file()]
        missing = len(index) - len(present)
        store = PayloadStore(raw_dir)
        mismatched = [p for h, p in present if body_hash(store.load(p)["body"]) != h]
        c.append(Check("LINEAGE: every payload the restored index names exists and re-hashes", not mismatched
                       and missing == 0,
                       f"{len(index)} index rows: {len(present)} files present and verified"
                       f"{'' if not mismatched else f', {len(mismatched)} MISMATCHED'}"
                       f"{'' if missing == 0 else f', {missing} not in this raw store'}"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if not keep:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                              "AND pid <> pg_backend_pid()", (scratch,))
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(scratch)))
        report.seconds = (datetime.now(UTC) - started).total_seconds()
    return report
