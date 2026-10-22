"""A frozen picture of what the platform says today, before anything is rebuilt.

The critical rebuild re-derives results, features, ratings, predictions and backtests.
Its whole argument is a comparison - *the new pipeline against the old one* - so the
old one's answers have to be kept exactly as the pages showed them, not reconstructed
later from whatever survives in the tables.

``snapshot`` therefore asks the API itself: every admin page and product endpoint
that takes no path parameter is called in-process as an operator, and its JSON is
written as served. Next to it go exact row counts for every table, so "what did we
have" has a number, not a memory. Nothing is written to the database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

SCHEMAS = ("core", "market", "raw", "analytics", "audit", "features", "models", "picks", "auth")
EXACT_COUNT_LIMIT = 20_000_000
"""Above this estimated size a table is reported with its planner estimate, marked as such."""

SKIP_PATHS = frozenset({"/api/v1/admin/analyst/ask", "/api/v1/search"})
"""Not reads (or calling an external model), or meaningless without a query: never snapshotted."""

PRODUCT_PREVIEW = ("/api/v1/home", "/api/v1/picks", "/api/v1/parlays/daily", "/api/v1/parlays/multiday",
                   "/api/v1/odds/best")
"""Product endpoints also captured with ?preview=shadow: the labelled admin preview."""


@dataclass
class SnapshotReport:
    folder: Path
    endpoints: dict[str, int] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)


def table_counts(conn: psycopg.Connection[Any]) -> dict[str, dict[str, Any]]:
    """Exact ``count(*)`` per table (partition parents only), or the estimate above the limit."""
    out: dict[str, dict[str, Any]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT n.nspname, c.relname, c.reltuples::bigint FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p') AND NOT c.relispartition "
            "ORDER BY 1, 2",
            (list(SCHEMAS),),
        )
        rels = [(str(a), str(b), int(c)) for a, b, c in cur.fetchall()]
        for schema, name, estimate in rels:
            key = f"{schema}.{name}"
            if estimate > EXACT_COUNT_LIMIT:
                out[key] = {"rows": estimate, "exact": False}
                continue
            cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(name)))
            row = cur.fetchone()
            out[key] = {"rows": int(row[0]) if row else 0, "exact": True}
    return out


def readable_paths(spec: dict[str, Any]) -> list[str]:
    """Every GET path without a path parameter, admin and product, from the OpenAPI document."""
    paths: list[str] = []
    for path, ops in sorted(spec.get("paths", {}).items()):
        if "{" in path or "get" not in ops or path in SKIP_PATHS:
            continue
        if path.startswith("/api/v1/auth"):
            continue
        paths.append(path)
    return paths


def _slug(path: str, preview: bool) -> str:
    name = path.removeprefix("/api/v1/").replace("/", "__") or "root"
    return f"{name}__shadow" if preview else name


def snapshot(conn: psycopg.Connection[Any], out_root: Path, *, label: str, client: Any) -> SnapshotReport:
    """``client`` is the API in-process, signed in as an operator: the caller builds it, so ops does not import api."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = out_root / f"{stamp}-{label}"
    (folder / "api").mkdir(parents=True, exist_ok=False)
    report = SnapshotReport(folder)
    spec = client.get("/openapi.json").json()
    targets = [(p, False) for p in readable_paths(spec)] + [(p, True) for p in PRODUCT_PREVIEW]
    for path, preview in targets:
        try:
            resp = client.get(path, params={"preview": "shadow"} if preview else None)
        except Exception as exc:  # a page that cannot be computed is recorded, not fatal
            report.failures[path + ("?preview=shadow" if preview else "")] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        key = _slug(path, preview)
        report.endpoints[key] = resp.status_code
        (folder / "api" / f"{key}.json").write_text(json.dumps(resp.json(), indent=1, sort_keys=True, default=str))
    report.tables = table_counts(conn)
    (folder / "counts.json").write_text(json.dumps(report.tables, indent=1, sort_keys=True))
    (folder / "manifest.json").write_text(json.dumps(
        {"label": label, "taken_at": stamp, "endpoints": report.endpoints, "failures": report.failures},
        indent=1, sort_keys=True))
    return report
