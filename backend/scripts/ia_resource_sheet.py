"""The sheet of resources of a wave (RP-13.3, ``resource-sheet-v1``) from the command line. Reading only.

    python -m scripts.ia_resource_sheet                                    # the last 7 days
    python -m scripts.ia_resource_sheet --moment 2026-11-27T12:00:00Z      # 7 days before and 7 after a deploy, and the alarms
    python -m scripts.ia_resource_sheet --days 14 --cap 185 --json

Memory of the worker, runs that did not end well, calls to the data provider and AI spend, measured before and after a deploy; it says which rule
of section 20 of the plan the deployed piece breaks and switches nothing off (that is the audited kit and the owner). With a moment still in
the future of its second window the sheet says the window is incomplete. ``--dsn`` overrides the database. Exit status: 0 done, 3 an alarm raised,
2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ops import resource_sheet as rs

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"


def month_start(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def build(conn: psycopg.Connection[Any], *, now: datetime, days: int, moment: datetime | None, cap: Decimal) -> dict[str, Any]:
    """One sheet (no moment) or the pair before/after a moment with the alarms. The connection is the caller's and is only read."""
    if moment is None:
        s = rs.read(conn, since=now - timedelta(days=days), until=now, month_since=month_start(now))
        return {"version": rs.VERSION, "window": rs.as_dict(s), "alarms": []}
    b0, b1, a0, a1 = rs.window(moment, days)
    complete = a1 <= now
    before = rs.read(conn, since=b0, until=b1, month_since=month_start(b1))
    after = rs.read(conn, since=a0, until=min(a1, now), month_since=month_start(min(a1, now)))
    alarms = rs.judge(before, after, cap_usd=cap)
    return {"version": rs.VERSION, "moment": moment.isoformat(), "after_window_complete": complete, "before": rs.as_dict(before),
            "after": rs.as_dict(after), "alarms": [{"code": a.code, "detail": a.detail} for a in alarms]}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_resource_sheet", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--moment", help="the deploy's moment (ISO 8601, UTC)")
    ap.add_argument("--cap", type=Decimal, default=Decimal(185), help="the AI's monthly cap in USD (the plan's 185)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days must be at least 1")
    moment = None
    if args.moment:
        try:
            moment = datetime.fromisoformat(args.moment.replace("Z", "+00:00"))
        except ValueError:
            ap.error("--moment must be an ISO 8601 date and time")
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = build(conn, now=datetime.now(UTC), days=args.days, moment=moment, cap=args.cap)
        conn.rollback()
    if args.as_json:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(render(doc))
    return 3 if doc["alarms"] else 0


def render(doc: dict[str, Any]) -> str:
    lines = [f"Hoja de recursos ({doc['version']})"]
    for key in ("window", "before", "after"):
        if key not in doc:
            continue
        w = doc[key]
        m, b, p, a = w["memory"], w["bad_runs"], w["provider_requests"], w["ai_spend_usd"]
        lines += [f"\n{key}: {w['since']} → {w['until']} ({w['days']} días, {w['runs']} ejecuciones)",
                  f"  memoria: pico {m['peak_mib']} MiB de {m['limit_mib']} (en {m['runs_with_memory']} ejecuciones medidas); "
                  + ", ".join(f"{j['job']} {j['peak_mib']}" for j in m["top_jobs"]),
                  f"  sin buen fin: {b['total']} ({b['per_day']} al día) {b['by_status']}",
                  f"  peticiones al proveedor: {p['total']} ({p['per_day']} al día; el día de más carga {p['busiest_day']})",
                  f"  gasto de IA: {a['window']} USD en la ventana; {a['month']} USD en el mes"]
    if doc.get("moment"):
        lines.append(f"\nVentana posterior {'completa' if doc['after_window_complete'] else 'INCOMPLETA'}.")
    lines.append("\nAlarmas: " + ("ninguna." if not doc["alarms"] else ""))
    lines += [f"  - {a['code']}: {a['detail']}" for a in doc["alarms"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
