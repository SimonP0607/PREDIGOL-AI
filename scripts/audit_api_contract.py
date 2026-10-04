"""API-Football v3 contract audit: every documented endpoint, parameter and field against what PrediGol requests and stores.

    python -m scripts.audit_api_contract                    # RAW statistics + observed fields (3 payloads per form)
    python -m scripts.audit_api_contract --sample 8
    python -m scripts.audit_api_contract --export config/api_football/v3_contract.json   # the documented side only

Sources: ``config/api_football/v3_contract.txt`` (the provider's OpenAPI v3.9.3: 38 GET operations, their
parameters, update frequencies, recommended calls, pagination, id batch limits and documented response
fields), the integration map (``fbi.providers.api_football.integration``: who requests each endpoint, how
often, where its data lands, who reads it) and ``raw.ingestion_payloads`` (what was actually requested,
with which parameter forms, how often). For each requested endpoint a sample of stored payloads gives the
field paths the provider really sends, compared with the documented ones: documented and seen, documented
and never seen in the sample, sent but not documented.

Writes audit.truth_v2_runs (kind api_contract), the evidence ledger (area api_contract) and
data/truth/<stamp>-api_contract/ (api_contract.json, api_contract.md). 0 provider requests; nothing in
core is changed. ``--export`` writes the documented contract as JSON and touches no database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.providers.api_football.contract import Endpoint, endpoints
from fbi.providers.api_football.integration import USES
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")

RAW_SQL = """
SELECT endpoint, count(*) AS payloads, min(fetched_at) AS first, max(fetched_at) AS last,
       count(*) FILTER (WHERE fetched_at > now() - interval '7 days') AS last_7d,
       count(*) FILTER (WHERE fetched_at > now() - interval '1 day') AS last_24h
  FROM raw.ingestion_payloads GROUP BY 1
"""

FORMS_SQL = """
SELECT endpoint, coalesce((SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(params) k), '') AS form,
       count(*) AS n, max(fetched_at) AS last
  FROM raw.ingestion_payloads GROUP BY 1, 2
"""

SAMPLE_SQL = """
SELECT hash, file_path, fetched_at FROM raw.ingestion_payloads
 WHERE endpoint = %(e)s AND coalesce((SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(params) k), '')
       = %(f)s AND coalesce(results_count, 1) > 0
 ORDER BY fetched_at DESC LIMIT %(n)s
"""


def _type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int | float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def leaf_paths(value: Any, prefix: str) -> Iterator[tuple[str, str]]:
    """Leaf field paths of a JSON value in the contract's notation ("response[].fixture.id")."""
    if isinstance(value, dict):
        if not value:
            yield prefix, "object"
        for k, v in value.items():
            yield from leaf_paths(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(value, list):
        if not value:
            yield prefix + "[]", "array"
        for item in value:
            yield from leaf_paths(item, prefix + "[]")
    else:
        yield prefix, _type(value)


def documented(e: Endpoint) -> dict[str, str]:
    return dict(e.fields())


def export(path: Path) -> None:
    out: list[dict[str, Any]] = []
    for e in endpoints():
        out.append({
            "path": e.path, "tag": e.tag, "operation_id": e.operation_id, "summary": e.summary,
            "update_frequency": e.update_frequency, "recommended_calls": e.recommended_calls,
            "page_size": e.page_size, "requires_a_param": e.requires_a_param, "needs_no_param": e.needs_no_param,
            "batch_limits": e.batch_limits,
            "params": [{"name": p.name, "in": p.where, "required": p.required, "type": p.type, "format": p.format,
                        "enum": list(p.enum), "pattern": p.pattern, "minimum": p.minimum, "maximum": p.maximum,
                        "min_length": p.min_length, "max_length": p.max_length, "description": p.description}
                       for p in e.params],
            "responses": e.responses,
            "fields": [{"path": f, "type": t} for f, t in e.fields()],
            "envelope": [{"path": f, "type": t} for f, t in e.envelope],
            "use_cases": e.use_cases,
            "description": e.description,
        })
    path.write_text(json.dumps({"source": "config/api_football/v3_contract.txt (API-Football OpenAPI v3.9.3)",
                                "endpoints": out}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {path}: {len(out)} endpoints, {sum(len(x['fields']) for x in out)} documented response fields")


def audit(conn: psycopg.Connection[Any], *, sample: int) -> dict[str, Any]:
    from fbi.ingestion.payload_store import PayloadStore

    store = PayloadStore(settings.runtime.raw_store_dir)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RAW_SQL)
        raw = {r["endpoint"]: dict(r) for r in cur.fetchall()}
        cur.execute(FORMS_SQL)
        forms: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in cur.fetchall():
            forms[r["endpoint"]].append(dict(r))
    rows = []
    for e in endpoints():
        use = USES[e.path]
        doc = documented(e)
        seen: dict[str, set[str]] = defaultdict(set)
        sampled = unreadable = 0
        for form in forms.get(e.path, []):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(SAMPLE_SQL, {"e": e.path, "f": form["form"], "n": sample})
                files = cur.fetchall()
            for f in files:
                try:
                    body = store.load(str(f["file_path"]))["body"]
                except (OSError, ValueError, KeyError):
                    unreadable += 1
                    continue
                sampled += 1
                for p, t in leaf_paths(body.get("response") if isinstance(body, dict) else None, "response"):
                    seen[p].add(t)
        stats = raw.get(e.path)
        doc_seen = sorted(p for p in doc if p in seen)
        doc_unseen = sorted(p for p in doc if p not in seen)
        extra = sorted(p for p in seen if p not in doc)
        rows.append({
            "path": e.path, "tag": e.tag, "summary": e.summary, "status": use.status, "utility": use.utility,
            "update_frequency": e.update_frequency, "recommended_calls": e.recommended_calls,
            "our_cadence": use.cadence, "page_size": e.page_size, "batch_limits": e.batch_limits,
            "requires_a_param": e.requires_a_param,
            "params": [p.name for p in e.query_params], "params_required": [p.name for p in e.query_params if p.required],
            "forms_used": sorted((f["form"] or "<none>") + f" x{f['n']}" for f in forms.get(e.path, [])),
            "raw": None if stats is None else {k: stats[k] for k in ("payloads", "first", "last", "last_7d", "last_24h")},
            "requested_by": list(use.requested_by), "stored_in": list(use.stored_in), "read_by": list(use.read_by),
            "covered_by": use.covered_by, "gaps": list(use.gaps), "notes": use.notes, "fixed": list(use.fixed),
            "fields_documented": len(doc), "payloads_sampled": sampled, "unreadable": unreadable,
            "fields_seen": len(seen), "documented_seen": len(doc_seen), "documented_unseen": doc_unseen,
            "undocumented_seen": extra,
            "type_differences": sorted(f"{p}: documented {doc[p]}, seen {'/'.join(sorted(seen[p]))}"
                                       for p in doc_seen
                                       if doc[p] not in ("null", "array", "object") and seen[p] - {doc[p], "null"}),
        })
    known = {e.path for e in endpoints()}
    others = sorted(k for k in raw if k not in known)
    requested_without_raw = [x["path"] for x in rows if x["status"] in ("FULL", "PARTIAL") and x["raw"] is None]
    raw_without_use = [x["path"] for x in rows if x["status"] in ("MISSING", "COVERED") and x["raw"] is not None]
    return {"endpoints": rows, "other_raw_endpoints": others, "requested_without_raw": requested_without_raw,
            "raw_without_use": raw_without_use}


def evidence(result: dict[str, Any]) -> list[Evidence]:
    out: list[Evidence] = []
    for x in result["endpoints"]:
        key = f"api_contract:{x['path']}"
        if x["status"] == "MISSING" and x["utility"] in ("high", "medium"):
            out.append(Evidence(
                key=f"{key}:missing", area="api_contract", issue_type="MISSING_ENDPOINT",
                severity="medium" if x["utility"] == "medium" else "high", at_fault="none", entity=x["path"],
                claim=f"{x['path']} ({x['summary']}) is never requested and what it serves is not obtained otherwise"
                      + (f": {x['notes']}" if x["notes"] else ""),
                api={"update_frequency": x["update_frequency"], "recommended_calls": x["recommended_calls"],
                     "params": x["params"], "fields_documented": x["fields_documented"]}))
        if x["status"] in ("PARTIAL", "COVERED") and x["gaps"]:
            out.append(Evidence(
                key=f"{key}:gaps", area="api_contract", issue_type="API_CONTRACT_GAP", severity="low",
                at_fault="none", entity=x["path"], status="MONITOR",
                claim=f"{x['path']} is {x['status'].lower()}: " + "; ".join(x["gaps"]),
                db={"stored_in": x["stored_in"], "read_by": x["read_by"], "forms_used": x["forms_used"]}))
        if x["undocumented_seen"]:
            out.append(Evidence(
                key=f"{key}:undocumented", area="api_contract", issue_type="UNSUPPORTED_FIELD", severity="info",
                at_fault="provider", entity=x["path"], status="MONITOR",
                claim=f"{x['path']}: the provider sends {len(x['undocumented_seen'])} field(s) its documentation's "
                      f"example does not show (in {x['payloads_sampled']} stored payloads)",
                api={"fields": x["undocumented_seen"][:60]}))
    for path in result["requested_without_raw"]:
        out.append(Evidence(
            key=f"api_contract:{path}:no_raw", area="api_contract", issue_type="API_CONTRACT_GAP", severity="low",
            at_fault="predigol", entity=path,
            claim=f"{path}: the integration map says it is requested, but no RAW payload of it is stored"))
    return out


def markdown(result: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = ["# API-Football v3 contract audit", "",
             f"{summary['endpoints']} documented endpoints: " + ", ".join(f"{k} {v}" for k, v in
                                                                         sorted(summary["status"].items())) + ".",
             "", "| Endpoint | Status | Utility | Documented frequency / recommended | Our cadence | Params "
                 "(required) | Forms used (RAW) | RAW payloads | Fields documented / seen / doc-unseen / extra |",
             "|---|---|---|---|---|---|---|---|---|"]
    for x in result["endpoints"]:
        raw = x["raw"]
        lines.append(
            f"| `{x['path']}` | {x['status']} | {x['utility']} | {x['update_frequency'] or '-'} / "
            f"{x['recommended_calls'] or '-'} | {x['our_cadence'] or '-'} | {', '.join(x['params']) or '-'} "
            f"({', '.join(x['params_required']) or '-'}) | {'; '.join(x['forms_used']) or '-'} | "
            f"{raw['payloads'] if raw else 0} | {x['fields_documented']} / {x['fields_seen']} / "
            f"{len(x['documented_unseen'])} / {len(x['undocumented_seen'])} |")
    lines += ["", "## Fields sent but not in the documentation's examples", ""]
    for x in result["endpoints"]:
        if x["undocumented_seen"]:
            lines.append(f"* `{x['path']}` ({len(x['undocumented_seen'])}): "
                         + ", ".join(f"`{p}`" for p in x["undocumented_seen"][:40])
                         + (" ..." if len(x["undocumented_seen"]) > 40 else ""))
    lines += ["", "## Documented fields not seen in the sampled payloads", ""]
    for x in result["endpoints"]:
        if x["documented_unseen"] and x["payloads_sampled"]:
            lines.append(f"* `{x['path']}` ({len(x['documented_unseen'])}): "
                         + ", ".join(f"`{p}`" for p in x["documented_unseen"][:40]))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=3, help="payloads read per endpoint and parameter form")
    ap.add_argument("--export", help="write the documented contract as JSON to this path and stop")
    args = ap.parse_args(argv)
    if args.export:
        export(Path(args.export))
        return 0
    at = now()
    with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '300s'")
        run = V2Run(conn, None, "api_contract", at, params={"sample": args.sample})
        result = audit(conn, sample=args.sample)
        items = evidence(result)
        codes = record_all(conn, items, at=at, run_id=run.run_id)
        clear_unseen(conn, area="api_contract", scope_prefix="api_contract:", seen=[ev.key for ev in items], at=at)
        summary = {
            "endpoints": len(result["endpoints"]),
            "status": dict(Counter(x["status"] for x in result["endpoints"])),
            "missing_useful": [x["path"] for x in result["endpoints"]
                               if x["status"] == "MISSING" and x["utility"] != "low"],
            "fields_documented": sum(x["fields_documented"] for x in result["endpoints"]),
            "fields_seen": sum(x["fields_seen"] for x in result["endpoints"]),
            "documented_unseen": sum(len(x["documented_unseen"]) for x in result["endpoints"] if x["payloads_sampled"]),
            "undocumented_seen": sum(len(x["undocumented_seen"]) for x in result["endpoints"]),
            "payloads_sampled": sum(x["payloads_sampled"] for x in result["endpoints"]),
            "other_raw_endpoints": len(result["other_raw_endpoints"]),
            "requested_without_raw": result["requested_without_raw"], "raw_without_use": result["raw_without_use"],
            "evidence": len(codes),
        }
        folder = write_report(REPORTS, "api_contract", at, {"summary": summary, **result}, markdown(result, summary))
        status = run.finish(summary, report_dir=folder)
    print(json.dumps({**summary, "report": str(folder), "status": status}, indent=1, default=str))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
