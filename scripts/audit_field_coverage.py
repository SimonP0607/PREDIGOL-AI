"""Field coverage audit: every field the provider sends, followed API -> RAW -> NORMALIZER -> DB -> PRODUCT -> MODEL.

    python -m scripts.audit_field_coverage              # every endpoint with stored payloads, 30 payloads each
    python -m scripts.audit_field_coverage --sample 60

For each endpoint PrediGol has requested (``raw.ingestion_payloads``), a sample of stored payloads is read
from disk (never modified) and flattened to field paths (list items as ``[]``) with how often each carries a
value. Each path is followed along the chain:

* API - is it in the provider's documentation (``config/api_football/v3_contract.txt``)?
* RAW - is it in the payloads, and how often with a value?
* NORMALIZER - where our parser puts it (``fbi.truth.v2.fields.REGISTRY``: a table column, ``ignore:<why>``,
  ``useful:<why>`` = dropped although useful, ``raw:<why>`` = an endpoint we keep in RAW only);
* DB - for stored columns of match details, standings and absences: the share of the sampled entities'
  rows where the column holds a value, against the share of payload items where the field has one;
* PRODUCT / MODEL - is the column named by the code of the API (product) or of features, models,
  research, backtests and picks (model)?

Classes:

* STORED_AND_USED - normalized into a column that the product or a model reads;
* STORED_NOT_USED - normalized, read by nothing yet;
* INTENTIONALLY_IGNORED - dropped on purpose, with the reason (derivable, presentation, held elsewhere);
* UNSUPPORTED - no place in our schema: kept in RAW only (``raw:``) or never decided (unmapped);
* BUG_DROPPED_FIELD - present in RAW and useful but dropped by the normalizer, or a stored column that holds
  far fewer values than the payloads it came from.

Writes audit.truth_v2_runs (kind field_coverage), the evidence ledger (area field_coverage) and
data/truth/<stamp>-field_coverage/. 0 provider requests; nothing in core is changed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.providers.api_football.contract import by_path
from fbi.truth.v2 import fields as fl
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")
REPO = Path(__file__).resolve().parents[1]
PRODUCT_DIRS = ("api", "userdata", "parlays", "analyst", "competitions")
MODEL_DIRS = ("features", "models", "research", "backtesting", "picks", "predictions", "validation")
DB_CHECKED = {"fixtures", "fixture_results", "fixture_events", "fixture_lineups", "fixture_lineup_players",
              "fixture_team_stats", "fixture_player_stats", "standings", "player_absences", "fixture_facts",
              "fixture_player_extras"}
ONLY = {("fixture_lineup_players", "grid"): sql.SQL(" AND x.is_starter")}
"""Rows a column applies to: the grid is a starter's (substitutes have none)."""
COLUMN = re.compile(r"^core\.([a-z_]+)\.([a-z_]+)$")

PAYLOADS_SQL = """
SELECT hash, file_path, params FROM raw.ingestion_payloads
 WHERE endpoint = %(e)s AND http_status = 200 {cond}
 ORDER BY (coalesce(results_count, 0) > 0) DESC, fetched_at DESC LIMIT %(n)s
"""


def words_in(dirs: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for sub in dirs:
        for f in (REPO / "src" / "fbi" / sub).rglob("*.py"):
            out.update(re.findall(r"[a-z_][a-z0-9_]+", f.read_text(errors="ignore")))
    return out


def load(conn: psycopg.Connection[Any], raw_root: Path, endpoint: str, n: int) -> list[tuple[str, dict[str, Any]]]:
    cond = "AND params ? 'ids'" if endpoint == "/fixtures" else ""
    with conn.cursor() as cur:
        cur.execute(PAYLOADS_SQL.format(cond=cond), {"e": endpoint, "n": n})
        rows = cur.fetchall()
    out = []
    for h, path, _ in rows:
        f = Path(path) if Path(path).is_absolute() else raw_root / path
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        doc = json.loads(data)
        body = doc.get("body", doc) if isinstance(doc, dict) else {}
        if isinstance(body, dict) and body.get("response"):
            out.append((str(h), body))
    return out


@dataclass
class Field:
    endpoint: str
    path: str
    documented: bool
    seen: int
    present: int
    rule: str
    product: bool | None
    model: bool | None
    db_rows: int | None = None
    db_filled: int | None = None
    klass: str = ""
    why: str = ""

    @property
    def raw_share(self) -> float:
        return self.present / self.seen if self.seen else 0.0

    @property
    def db_share(self) -> float | None:
        return None if not self.db_rows else (self.db_filled or 0) / self.db_rows


def classify(f: Field) -> None:
    rule = f.rule
    if rule.startswith(("core.", "market.", "raw.league_coverage")):
        if f.db_share is not None and f.raw_share >= 0.5 and f.db_share < 0.5 * f.raw_share:
            f.klass, f.why = "BUG_DROPPED_FIELD", (f"stored column holds a value in {f.db_share:.0%} of rows, the payloads "
                                                   f"in {f.raw_share:.0%} of items")
        else:
            f.klass = "STORED_AND_USED" if (f.product or f.model) else "STORED_NOT_USED"
    elif rule.startswith("ignore:"):
        f.klass, f.why = "INTENTIONALLY_IGNORED", rule[7:]
    elif rule.startswith("useful:"):
        f.klass, f.why = ("BUG_DROPPED_FIELD", rule[7:]) if f.present else ("UNSUPPORTED", "useful but never sent")
    elif rule.startswith("raw:"):
        f.klass, f.why = "UNSUPPORTED", rule[4:]
    else:
        f.klass, f.why = "UNSUPPORTED", "unmapped: no decision taken"


def db_fill(conn: psycopg.Connection[Any], fields: list[Field], hashes: list[str], fixture_ids: list[int]) -> None:
    """Rows of the sampled entities and how many hold a value, for each stored column we can tie to them."""
    for f in fields:
        m = COLUMN.match(f.rule)
        if not m or m.group(1) not in DB_CHECKED:
            continue
        table, column = m.group(1), m.group(2)
        ident = sql.Identifier("core", table)
        col = sql.Identifier(column)
        if table == "fixtures":
            q = sql.SQL("SELECT count(*), count({c}) FROM {t} WHERE provider_fixture_id = ANY(%s)").format(c=col, t=ident)
            args: tuple[Any, ...] = (fixture_ids,)
        elif table in ("standings", "player_absences"):
            q = sql.SQL("SELECT count(*), count({c}) FROM {t} WHERE payload_hash = ANY(%s)").format(c=col, t=ident)
            args = (hashes,)
        else:
            q = sql.SQL("SELECT count(*), count(x.{c}) FROM {t} x JOIN core.fixtures fx ON fx.id = x.fixture_id "
                        "WHERE fx.provider_fixture_id = ANY(%s){only}").format(
                c=col, t=ident, only=ONLY.get((table, column), sql.SQL("")))
            args = (fixture_ids,)
        try:
            with conn.cursor() as cur:
                cur.execute(q, args)
                row = cur.fetchone()
        except psycopg.Error:
            continue  # a column the registry names that the table lacks shows as unchecked, not as a pass
        if row is not None:
            f.db_rows, f.db_filled = int(row[0]), int(row[1])


def audit(conn: psycopg.Connection[Any], *, sample: int) -> list[Field]:
    raw_root = Path(settings.runtime.raw_store_dir)
    raw_root = raw_root if raw_root.is_absolute() else REPO / raw_root
    product, model = words_in(PRODUCT_DIRS), words_in(MODEL_DIRS)
    contract = by_path()
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT endpoint FROM raw.ingestion_payloads")
        requested = sorted(str(r[0]) for r in cur.fetchall() if str(r[0]) in contract)
    out: list[Field] = []
    for endpoint in requested:
        payloads = load(conn, raw_root, endpoint, sample)
        bodies = [b for _, b in payloads]
        documented = {p.replace("response[].", "", 1).replace("response.", "", 1)
                      for p, _ in contract[endpoint].fields()}
        rows = fl.inventory(endpoint, bodies, used_columns=set())
        fields: list[Field] = []
        for r in rows:
            col = r.rule.split(" ")[0].split(".")[-1] if r.rule.startswith(("core.", "market.", "raw.league")) else None
            fields.append(Field(endpoint, r.path, r.path in documented, r.seen, r.present, r.rule,
                                (col in product) if col else None, (col in model) if col else None))
        ids = sorted({int(i) for _, b in payloads for i in _fixture_ids(b)})
        db_fill(conn, fields, [h for h, _ in payloads], ids)
        for f in fields:
            classify(f)
        out += fields
    return out


def _fixture_ids(body: dict[str, Any]) -> list[int]:
    out = []
    for item in fl.items_of(body):
        fx = item.get("fixture") if isinstance(item, dict) else None
        if isinstance(fx, dict) and isinstance(fx.get("id"), int):
            out.append(fx["id"])
    return out


def evidence(fields: list[Field]) -> list[Evidence]:
    out: list[Evidence] = []
    by_endpoint: dict[str, list[Field]] = {}
    for f in fields:
        by_endpoint.setdefault(f.endpoint, []).append(f)
    for endpoint, fs in by_endpoint.items():
        dropped = [f for f in fs if f.klass == "BUG_DROPPED_FIELD"]
        if dropped:
            out.append(Evidence(
                key=f"field_coverage:{endpoint}:dropped", area="field_coverage", issue_type="BUG_DROPPED_FIELD",
                severity="medium", at_fault="predigol", entity=endpoint,
                claim=f"{endpoint}: {len(dropped)} field(s) the provider sends with values and that a page, a market or "
                      "a model could use are dropped by our normalizer (or kept far less often than sent)",
                api={"fields": [{"path": f.path, "present": f"{f.present}/{f.seen}", "why": f.why} for f in dropped]},
                fix="store them from RAW (new columns or tables; no new requests) and normalize them from now on"))
        unmapped = [f for f in fs if f.klass == "UNSUPPORTED" and f.rule == "unmapped" and f.present]
        if unmapped:
            out.append(Evidence(
                key=f"field_coverage:{endpoint}:unmapped", area="field_coverage", issue_type="UNSUPPORTED_FIELD",
                severity="low", at_fault="predigol", entity=endpoint, status="MONITOR",
                claim=f"{endpoint}: {len(unmapped)} field(s) with values have no decision (store or ignore)",
                api={"fields": [{"path": f.path, "present": f"{f.present}/{f.seen}"} for f in unmapped[:40]]}))
        unused = [f for f in fs if f.klass == "STORED_NOT_USED" and f.present]
        if unused:
            out.append(Evidence(
                key=f"field_coverage:{endpoint}:stored_not_used", area="field_coverage", issue_type="STORED_NOT_USED",
                severity="info", at_fault="none", entity=endpoint, status="ACCEPTED",
                claim=f"{endpoint}: {len(unused)} stored field(s) are read by no page and no model yet",
                db={"fields": [{"path": f.path, "column": f.rule} for f in unused[:40]]}))
    return out


def markdown(fields: list[Field], summary: dict[str, Any]) -> str:
    lines = ["# Field coverage: API -> RAW -> normalizer -> DB -> product -> model", "",
             ", ".join(f"{k} {v}" for k, v in sorted(summary["classes"].items())), "",
             "| Endpoint | Field | Documented | RAW (with value / seen) | Normalizer | DB (filled / rows) | Product | "
             "Model | Class | Why |", "|---|---|---|---|---|---|---|---|---|---|"]

    def yn(v: bool | None) -> str:
        return "-" if v is None else "yes" if v else "no"

    for f in fields:
        db = "-" if f.db_rows is None else f"{f.db_filled}/{f.db_rows}"
        lines.append(f"| {f.endpoint} | `{f.path}` | {yn(f.documented)} | {f.present}/{f.seen} | {f.rule[:70]} | {db} | "
                     f"{yn(f.product)} | {yn(f.model)} | **{f.klass}** | {f.why[:90]} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=30, help="payloads read per endpoint")
    args = ap.parse_args(argv)
    at = now()
    with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '300s'")
        run = V2Run(conn, None, "field_coverage", at, params={"sample": args.sample})
        fields = audit(conn, sample=args.sample)
        items = evidence(fields)
        codes = record_all(conn, items, at=at, run_id=run.run_id)
        clear_unseen(conn, area="field_coverage", scope_prefix="field_coverage:", seen=[e.key for e in items], at=at)
        summary = {
            "fields": len(fields), "endpoints": len({f.endpoint for f in fields}),
            "classes": dict(Counter(f.klass for f in fields)),
            "documented": sum(1 for f in fields if f.documented),
            "undocumented": sum(1 for f in fields if not f.documented),
            "bug_dropped": [f"{f.endpoint} {f.path}" for f in fields if f.klass == "BUG_DROPPED_FIELD"],
            "evidence": len(codes),
        }
        folder = write_report(REPORTS, "field_coverage", at,
                              {"summary": summary, "fields": [asdict(f) for f in fields]}, markdown(fields, summary))
        status = run.finish(summary, report_dir=folder)
    print(json.dumps({**summary, "report": str(folder), "run_status": status}, indent=1, default=str))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
