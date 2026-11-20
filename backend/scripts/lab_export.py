"""PM-12-02 (OPS-013): take the LAB off the server - a read-only export to Parquet with a manifest, for the owner's laptop.

    python -m scripts.lab_export plan [--session 4] [--since 2026-01-01]          # what would leave, row counts; writes nothing
    python -m scripts.lab_export run --session 4 [--out /tmp/predigol-lab]        # export (one consistent read-only snapshot)
    python scripts/lab_export.py verify <folder>                                  # on the laptop: the files match the manifest

What may leave is a CLOSED list (``TABLES``): football data, prices, model versions and the LAB's own backtests - schemas
``core``, ``market``, ``features``, ``models`` and ``analytics`` only, and inside them only the tables listed. ``auth`` and
``customer`` (accounts, payments, anything about a person) are refused by name, before the database is asked anything, and the
worker's database role has no access to them either. Nothing else can be named: an unknown table is an error.

Every read happens in ONE transaction, ``REPEATABLE READ READ ONLY`` with ``default_transaction_read_only`` and a statement
timeout: the snapshot is consistent across tables and a write is impossible. Rows are streamed (a server-side cursor, 20,000 at a
time) into one Parquet file per table, so memory stays flat. The run stops before it passes ``--max-bytes`` (5 GB by default:
the card's temporary space).

``manifest.jsonl``, one JSON object per line: a ``run`` line (when, code version, snapshot, filters, the list version), one
``table`` line per file (rows, columns and their Parquet types, bytes, SHA-256, the exact query) and an ``end`` line. ``verify``
re-hashes the files against it and needs nothing but the standard library, so it runs on the laptop as is.

It refuses to run during the nightly copy (03:30-05:00 UTC). Leave 20 minutes around a ``fixtures_sync`` too (their hours move:
read them before). It changes nothing on the server: no table, no file outside ``--out``, no provider request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

VERSION = "lab-export-v1"
ALLOWED_SCHEMAS = frozenset({"core", "market", "features", "models", "analytics"})
FORBIDDEN_SCHEMAS = frozenset({"auth", "customer"})
BATCH = 20_000
MAX_BYTES = 5 * 1024**3
STATEMENT_TIMEOUT = "300s"
COPY_WINDOW = (time(3, 30), time(5, 0))
"""UTC: PITR at 03:30, the daily copy at 04:15 (backend/deploy/vps/systemd). No export starts inside it."""

_SESSION_FIXTURES = ("fixture_id IN (SELECT s.fixture_id FROM analytics.backtest_samples s "
                     "JOIN analytics.backtest_runs r ON r.id = s.backtest_run_id WHERE r.session_id = %(session)s)")
_SINCE_FIXTURES = "fixture_id IN (SELECT f.id FROM core.fixtures f WHERE f.kickoff_at >= %(since)s)"


@dataclass(frozen=True, slots=True)
class TableSpec:
    """A table that may leave. ``filters``: the SQL predicate for each filter it understands (``session``: a backtest
    session; ``since``: matches from that date). ``needs_filter``: never exported whole (too big for the laptop)."""

    name: str
    what: str
    filters: Mapping[str, str] = field(default_factory=dict)
    needs_filter: bool = False

    @property
    def schema(self) -> str:
        return self.name.split(".", 1)[0]


TABLES: dict[str, TableSpec] = {t.name: t for t in (
    TableSpec("core.competitions", "competiciones del catálogo"),
    TableSpec("core.competition_seasons", "temporadas de cada competición"),
    TableSpec("core.teams", "equipos"),
    TableSpec("core.fixtures", "partidos (calendario, estado, marcador)",
              {"session": _SESSION_FIXTURES.replace("fixture_id IN", "id IN"),
               "since": "kickoff_at >= %(since)s"}, needs_filter=True),
    TableSpec("core.fixture_results", "resultados (90', prórroga, penaltis)",
              {"session": _SESSION_FIXTURES, "since": _SINCE_FIXTURES}, needs_filter=True),
    TableSpec("core.fixture_team_stats", "estadísticas de equipo por partido",
              {"session": _SESSION_FIXTURES, "since": _SINCE_FIXTURES}, needs_filter=True),
    TableSpec("market.bookmakers", "casas de apuestas"),
    TableSpec("models.model_registry", "familias de modelos"),
    TableSpec("models.model_versions", "versiones de modelo (hiperparámetros, variables)"),
    TableSpec("models.predictions", "probabilidades guardadas de cada versión",
              {"session": "backtest_session_id = %(session)s"}, needs_filter=True),
    TableSpec("analytics.backtest_sessions", "sesiones del LAB", {"session": "id = %(session)s"}),
    TableSpec("analytics.backtest_runs", "ejecuciones del LAB y sus métricas", {"session": "session_id = %(session)s"}),
    TableSpec("analytics.backtest_samples", "cada partido y selección de una ejecución del LAB",
              {"session": "backtest_run_id IN (SELECT r.id FROM analytics.backtest_runs r WHERE r.session_id = %(session)s)"},
              needs_filter=True),
)}
"""The closed list (``lab-export-v1``). Adding a table is a PR that changes this list and its test."""


class ExportRefusedError(ValueError):
    """The request names something that may not leave, or cannot be exported safely."""


def check_table(name: str) -> TableSpec:
    schema = name.split(".", 1)[0] if "." in name else ""
    if schema in FORBIDDEN_SCHEMAS:
        raise ExportRefusedError(f"{name}: the {schema} schema never leaves the server")
    spec = TABLES.get(name)
    if spec is None:
        raise ExportRefusedError(f"{name}: not in the closed list of lab-export ({', '.join(sorted(TABLES))})")
    if spec.schema not in ALLOWED_SCHEMAS:  # pragma: no cover - the list is checked by its test
        raise ExportRefusedError(f"{name}: schema {spec.schema} is not exportable")
    return spec


def select_tables(names: Sequence[str] | None, filters: Mapping[str, Any]) -> list[TableSpec]:
    """The tables a run exports: ``names`` (all of the list when None) - each checked - minus those that need a filter none of
    the given ones applies to, when no name was given; naming such a table without its filter is refused."""
    chosen = [check_table(n) for n in names] if names else list(TABLES.values())
    out: list[TableSpec] = []
    for spec in chosen:
        usable = [f for f in filters if f in spec.filters]
        if spec.needs_filter and not usable:
            if names:
                raise ExportRefusedError(f"{spec.name}: too big to leave whole; give one of {sorted(spec.filters)}")
            continue
        out.append(spec)
    return out


def query_for(spec: TableSpec, filters: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The exact SELECT of a table (its identifier from the closed list, never from the user) and its parameters."""
    clauses = [spec.filters[f] for f in filters if f in spec.filters]
    sql = f"SELECT * FROM {spec.name}" + (" WHERE " + " AND ".join(f"({c})" for c in clauses) if clauses else "")
    return sql, {f: v for f, v in filters.items() if f in spec.filters}


def in_copy_window(moment: datetime) -> bool:
    t = moment.astimezone(UTC).time()
    return COPY_WINDOW[0] <= t < COPY_WINDOW[1]


# ── Parquet ──────────────────────────────────────────────────────────────────────────────────────────────────────────

_PG_TYPES: dict[int, str] = {
    16: "bool", 20: "int64", 21: "int64", 23: "int64", 26: "int64", 700: "float64", 701: "float64", 1700: "float64",
    25: "string", 1043: "string", 1042: "string", 19: "string", 2950: "string", 114: "json", 3802: "json",
    1082: "date", 1114: "timestamp", 1184: "timestamptz",
}
"""Postgres type OID -> how the column is written. ``numeric`` becomes float64 (the LAB reads it as a double); json, jsonb,
arrays and anything not listed are written as text (JSON for structures), never dropped."""


def column_kind(oid: int) -> str:
    return _PG_TYPES.get(oid, "text")


def _cell(kind: str, value: Any) -> Any:
    if value is None:
        return None
    if kind == "float64":
        return float(value)
    if kind in ("json", "text"):
        return value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)
    if kind == "string":
        return str(value)
    return value


def arrow_type(kind: str) -> Any:
    import pyarrow as pa

    return {"bool": pa.bool_(), "int64": pa.int64(), "float64": pa.float64(), "date": pa.date32(),
            "timestamp": pa.timestamp("us"), "timestamptz": pa.timestamp("us", tz="UTC")}.get(kind, pa.string())


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_parquet(path: Path, names: Sequence[str], kinds: Sequence[str], batches: Iterator[list[tuple[Any, ...]]]) -> int:
    """Stream the rows into one Parquet file; returns the rows written (an empty table still gets its file and schema)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([pa.field(n, arrow_type(k)) for n, k in zip(names, kinds, strict=True)])
    rows = 0
    with pq.ParquetWriter(path, schema, compression="zstd") as writer:
        for batch in batches:
            cols = [pa.array([_cell(k, r[i]) for r in batch], type=arrow_type(k)) for i, k in enumerate(kinds)]
            writer.write_table(pa.Table.from_arrays(cols, schema=schema))
            rows += len(batch)
    return rows


# ── the run ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _connect() -> Any:
    import psycopg

    from fbi.core.config import settings

    conn = psycopg.connect(settings.database.psycopg_url)
    # One snapshot for every table, and a write impossible: the transaction psycopg opens on the first statement is
    # REPEATABLE READ READ ONLY, and the session default is read-only too.
    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    conn.read_only = True
    conn.execute("SET default_transaction_read_only = on")
    conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
    return conn


def _filters(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if args.session is not None:
        out["session"] = int(args.session)
    if args.since is not None:
        out["since"] = datetime.combine(date.fromisoformat(args.since), time(0), tzinfo=UTC)
    return out


def plan(conn: Any, specs: Sequence[TableSpec], filters: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    with conn.cursor() as cur:
        for spec in specs:
            sql, params = query_for(spec, filters)
            cur.execute(f"SELECT count(*) FROM ({sql}) q", params)
            row = cur.fetchone()
            out.append({"table": spec.name, "rows": int(row[0]) if row else 0, "what": spec.what})
    return out


def run(conn: Any, specs: Sequence[TableSpec], filters: Mapping[str, Any], *, out: Path, max_bytes: int,
        at: datetime, code_version: str) -> Path:
    folder = out / f"{at:%Y%m%dT%H%M%SZ}"
    folder.mkdir(parents=True, exist_ok=False)
    manifest = folder / "manifest.jsonl"
    with conn.cursor() as cur:
        cur.execute("SELECT pg_current_snapshot()::text, current_database(), now()")
        snap, db, db_now = cur.fetchone()
    total_rows = total_bytes = 0
    stopped: str | None = None
    with manifest.open("w", encoding="utf-8") as mf:
        def line(obj: Mapping[str, Any]) -> None:
            mf.write(json.dumps(obj, default=str, ensure_ascii=False, sort_keys=True) + "\n")
            mf.flush()

        line({"kind": "run", "version": VERSION, "at": at.isoformat(), "code_version": code_version, "database": db,
              "snapshot": snap, "snapshot_time": db_now, "isolation": "repeatable read, read only",
              "filters": dict(filters), "tables": [s.name for s in specs], "max_bytes": max_bytes})
        for spec in specs:
            sql, params = query_for(spec, filters)
            path = folder / f"{spec.name}.parquet"
            with conn.cursor(name=f"lab_{spec.name.replace('.', '_')}") as cur:
                cur.itersize = BATCH
                cur.execute(sql, params)
                desc = cur.description or []
                names = [d.name for d in desc]
                kinds = [column_kind(int(d.type_code)) for d in desc]

                def batches(c: Any = cur) -> Iterator[list[tuple[Any, ...]]]:
                    while chunk := c.fetchmany(BATCH):
                        yield chunk

                rows = write_parquet(path, names, kinds, batches())
            size = path.stat().st_size
            total_rows += rows
            total_bytes += size
            line({"kind": "table", "table": spec.name, "file": path.name, "rows": rows, "bytes": size,
                  "sha256": sha256_of(path), "query": sql, "params": params,
                  "columns": [{"name": n, "pg_oid": int(d.type_code), "as": k} for n, d, k in zip(names, desc, kinds, strict=True)]})
            if total_bytes > max_bytes:
                stopped = f"max bytes {max_bytes} passed after {spec.name}"
                break
        line({"kind": "end", "finished_at": datetime.now(UTC).isoformat(), "rows": total_rows, "bytes": total_bytes,
              "stopped": stopped})
    conn.rollback()
    return folder


def verify(folder: Path) -> list[str]:
    """Problems found re-hashing ``folder`` against its manifest (empty: every file is the one exported)."""
    lines = [json.loads(x) for x in (folder / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    problems = []
    if not lines or lines[0].get("kind") != "run" or lines[-1].get("kind") != "end":
        problems.append("manifest without its run and end lines (the export did not finish)")
    for t in (x for x in lines if x.get("kind") == "table"):
        path = folder / t["file"]
        if not path.exists():
            problems.append(f"{t['file']}: missing")
        elif sha256_of(path) != t["sha256"]:
            problems.append(f"{t['file']}: SHA-256 differs from the manifest")
        schema = str(t["table"]).split(".", 1)[0]
        if schema in FORBIDDEN_SCHEMAS or schema not in ALLOWED_SCHEMAS:
            problems.append(f"{t['table']}: schema {schema} should never have left")
    return problems


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lab_export", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--table", action="append", help="only this table of the closed list (repeatable)")
        p.add_argument("--session", type=int, help="one backtest session of the LAB (analytics.backtest_sessions.id)")
        p.add_argument("--since", help="matches from this date (YYYY-MM-DD)")
        if name == "run":
            p.add_argument("--out", type=Path, default=Path("/tmp/predigol-lab"))
            p.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    v = sub.add_parser("verify")
    v.add_argument("folder", type=Path)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "verify":
        problems = verify(args.folder)
        for p in problems:
            print("PROBLEM: " + p)
        print("ok: every file matches the manifest" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1
    filters = _filters(args)
    try:
        specs = select_tables(args.table, filters)
    except ExportRefusedError as exc:
        print(f"REFUSED: {exc}")
        return 2
    at = datetime.now(UTC)
    if args.cmd == "run" and in_copy_window(at):
        print("REFUSED: 03:30-05:00 UTC is the nightly copy; run it later")
        return 2
    conn = _connect()
    try:
        if args.cmd == "plan":
            for r in plan(conn, specs, filters):
                print(f"{r['table']:32} {r['rows']:>12,} rows   {r['what']}")
            print(f"{len(specs)} table(s), filters {filters or 'none'}; nothing written")
            return 0
        from fbi.core.version import code_version

        folder = run(conn, specs, filters, out=args.out, max_bytes=args.max_bytes, at=at, code_version=code_version())
    finally:
        conn.close()
    end = json.loads((folder / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    print(f"exported to {folder}: {end['rows']:,} rows, {end['bytes']:,} bytes"
          + (f"; STOPPED: {end['stopped']}" if end["stopped"] else ""))
    return 0 if not end["stopped"] else 1


if __name__ == "__main__":
    sys.exit(main())
