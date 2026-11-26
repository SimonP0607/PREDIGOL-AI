"""The nightly audit of the eight coherence tests over what PrediGol states (plan RP-2.2, ``coherence-battery-v1``). Read-only.

    python -m scripts.ia_coherence_audit --hours 72 [--json] [--save DIR]

For the matches that kick off in the next ``--hours`` and have a page forecast, the single figure of every market (``forecast-v2``) is computed as
of now and the eight tests of ``fbi.forecasting.battery`` run over each match. The report says how many matches were checked, how many are not
publishable (a match with one violation), which tests broke, which had nothing to compare (a test with zero comparisons proves nothing), and each
violation linked to the seal of the figures it compares. ``--save`` also writes the full report as ``coherence-<UTC date>.json`` in that directory.

The connection is READ ONLY (nothing is asked of a provider or a model, nothing is written to the database). It runs outside the worker. Exit 0 when
no match is left unpublishable, 1 when there is a violation (the report is printed all the same), 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.forecasting import battery_audit
from fbi.forecasting.market_reader import figures_at
from fbi.intel.calibration import calibration_state
from scripts.ia_single_figure import FIXTURES_SQL, PAGE_VERSION

OK, VIOLATION, CANNOT = 0, 1, 2
READ_ONLY: Final = "-c default_transaction_read_only=on -c statement_timeout=95000 -c TimeZone=UTC"


def audit(conn: psycopg.Connection[Any], *, at: datetime, hours: int, limit: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        ids = [int(r["fixture_id"]) for r in cur.execute(
            FIXTURES_SQL, {"at": at, "until": at + timedelta(hours=hours), "page": PAGE_VERSION, "limit": limit}).fetchall()]
    sets = figures_at(conn, ids, at=at, cal=calibration_state(conn, at=at)) if ids else {}
    audits = [battery_audit.audit_match(fs) for _, fs in sorted(sets.items())]
    out = battery_audit.summary(audits)
    broken = [a for a in audits if not a["publishable"]]
    out |= {"at": at.isoformat(), "hours": hours, "examples": [{"fixture_id": a["fixture_id"], **v} for a in broken for v in a["violations"]
                                                               ][: battery_audit.EXAMPLES], "unpublishable": [a["fixture_id"] for a in broken]}
    return out


def render(r: dict[str, Any]) -> str:
    lines = [f"Batería de coherencia ({r['version']}) · {r['at']} · {r['matches']} partidos en {r['hours']} h · {r['figures']} cifras",
             f"  partidos no publicables: {r['not_publishable']}"]
    for t, d in r["tests"].items():
        state = f"{d['violations']} violaciones en {d['comparisons']} comparaciones" if d["ran"] else "sin nada que comparar (no prueba nada)"
        lines.append(f"  prueba {t} · {d['name']} (tolerancia {d['tolerance']}): {state}")
    lines += [f"  partido {e['fixture_id']} · prueba {e['test']} · {e['rule']}: {e['detail']}" for e in r["examples"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--save", default=None, metavar="DIR")
    ap.add_argument("--dsn", default=None)
    args = ap.parse_args(argv)
    try:
        if args.dsn:
            dsn = args.dsn
        else:
            from fbi.core.config import settings
            dsn = settings.database.psycopg_url
        with psycopg.connect(dsn, options=READ_ONLY) as conn:
            report = audit(conn, at=datetime.now(UTC), hours=args.hours, limit=args.limit)
    except (psycopg.Error, ValueError) as exc:
        sys.stderr.write(f"cannot run: {type(exc).__name__}: {exc}\n")
        return CANNOT
    if args.save:
        path = Path(args.save) / f"coherence-{datetime.now(UTC):%Y-%m-%d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n" if args.as_json else render(report))
    return VIOLATION if report["not_publishable"] else OK


if __name__ == "__main__":
    sys.exit(main())
