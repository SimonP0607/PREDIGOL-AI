"""The observability rail's alerts (Plan Maestro IA, P3) from the command line: calibration drift and the CLV trend (``drift-v1``,
``fbi.observability.drift``) and the cost alerts (``cost-alerts-v1``, ``fbi.observability.cost_alerts``) of one Bogotá day, each with its
evidence.

    python -m scripts.ia_alerts day --day 2026-11-06
    python -m scripts.ia_alerts day --day 2026-11-06 --json

REPORT ONLY: it reads, writes no row, sends no message and switches nothing off - an alert is for a person to look at. A day that is not
over is read as of now, and the report says so. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 no alert, 1 at least one alert (WATCH, DRIFT or ALERT), 2 could not run (usage error).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai.calendar import day_start
from fbi.ai.config import AiSettings
from fbi.observability import cost_alerts, drift

COMMANDS = ("day",)
NONE, ALERTS, CANNOT = 0, 1, 2


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_alerts", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--day", required=True, metavar="YYYY-MM-DD", help="the Bogotá day to report")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the whole report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def lines(doc: dict[str, Any]) -> list[str]:
    out = [f"ALERTAS IA · {drift.VERSION} · {cost_alerts.VERSION} · día {doc['day']} (Bogotá) · leído a {doc['as_of']}"
           + ("" if doc["complete_day"] else " · DÍA SIN TERMINAR")]
    alerts = doc["alerts"]
    if not alerts:
        out.append("Sin alertas.")
    for a in alerts:
        out.append(f"[{a['severity']}] {a['rule']} · {a['subject']}: {a['summary']}")
    out.append(f"Sin muestra suficiente (no son alertas): {doc['insufficient']} reglas o celdas.")
    out.append("Solo informe: nada se apaga ni se cambia por estas alertas.")
    return out


def run(conn: psycopg.Connection[Any], *, day: date, now: datetime, settings: AiSettings) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready, with its lines) and the exit status. Reads only; the connection is the caller's."""
    end = day_start(day + timedelta(days=1))
    if day_start(day) > now:
        return {"error": f"{day} has not started yet"}, CANNOT
    at = min(end, now)
    d = drift.report(conn, day=day, at=at)
    c = cost_alerts.report(conn, day=day, at=at, settings=settings)
    alerts = d.alerts() + c.alerts()
    alerts.sort(key=lambda a: -max(drift.SEVERITY.get(a["severity"], 0), cost_alerts.SEVERITY.get(a["severity"], 0)))
    insufficient = d.as_json()["insufficient"] + sum(1 for f in c.findings if f.status == cost_alerts.INSUFFICIENT)
    doc: dict[str, Any] = {"day": day.isoformat(), "as_of": at.isoformat(), "complete_day": at >= end, "report_only": True,
                           "versions": [drift.VERSION, cost_alerts.VERSION], "alerts": alerts, "insufficient": insufficient,
                           "drift": d.as_json(), "cost": c.as_json()}
    doc["lines"] = lines(doc)
    return doc, ALERTS if alerts else NONE


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        day = parse_day(args.day)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        doc, code = run(conn, day=day, now=datetime.now(UTC), settings=AiSettings.from_env())
        conn.rollback()  # it only read
    if args.as_json or "lines" not in doc:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("\n".join(doc["lines"]) + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
