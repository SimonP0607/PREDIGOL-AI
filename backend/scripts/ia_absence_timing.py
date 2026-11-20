"""How long before kick-off an absence (injury or suspension) reaches PrediGol, by each channel already in use (IA-150, plan PM,
PM-06-03). Read only.

    python -m scripts.ia_absence_timing                       # the last 30 days, as a table
    python -m scripts.ia_absence_timing --days 30 --json      # the same figures, as JSON
    python -m scripts.ia_absence_timing --sample 20 --json    # plus 20 cases (ids and times) to check by hand
    python -m scripts.ia_absence_timing --since 2026-10-25 --until 2026-11-21

It reads through a connection the server keeps READ ONLY, with a 90-second statement timeout, and calls no provider and no site.
Channels, figures and what stays out until the owner signs (DM-05, DM-07, DM-08): ``fbi.ingestion.absence_timing``. Explained in
docs/owner/IA_150_TIEMPO_DE_LLEGADA_DE_BAJAS.md. No name, no reason of an absence, no claim's text is printed.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.ingestion.absence_timing import report

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=90000 -c TimeZone=UTC"

NAMES = {"proveedor_parte": "proveedor · parte de bajas", "proveedor_periodos": "proveedor · periodos de baja",
         "alineacion": "alineación oficial (confirma)"}


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, list):
        return f"[{_fmt(value[0])}; {_fmt(value[1])}]"
    return str(value)


def render(data: dict[str, Any]) -> str:
    w = data["window"]
    lines = [f"Llegada de las bajas por vía: partidos con saque del {w['since'][:10]} al {w['until'][:10]} "
             f"(medido {w['measured_at'][:16]} UTC; {data['version']})",
             f"Bajas: {data['absences']} ({', '.join(f'{k} {v}' for k, v in data['kinds'].items())}); "
             f"competiciones con parte del proveedor: {data['leagues_with_provider_report']}", "",
             "vía | bajas | antes del saque | después | mediana h antes | p10 | p90 | IC95 mediana | muestra"]
    for c in data["channels"]:
        lines.append(" | ".join((NAMES[c["channel"]], str(c["absences"]), str(c["before_kickoff"]), str(c["after_kickoff"]),
                                 _fmt(c["median_h"]), _fmt(c["p10_h"]), _fmt(c["p90_h"]), _fmt(c["median_ci95_h"]),
                                 "pequeña" if c["small_sample"] else "ok")))
    lines += ["", "frente al parte del proveedor | pares | adelanto mediano h | IC95 | antes en | IC95 | solo esta vía | muestra"]
    for c in data["against_provider_report"]:
        lines.append(" | ".join((NAMES[c["channel"]], str(c["pairs"]), _fmt(c["median_lead_h"]), _fmt(c["median_lead_ci95_h"]),
                                 _fmt(c["earlier_share"]), _fmt(c["earlier_share_ci95"]),
                                 str(c["only_this_channel_before_kickoff"]), "pequeña" if c["small_sample"] else "ok")))
    lines += ["", "Pendiente de firma (no medido): " + "; ".join(data["pending_signature"])]
    return "\n".join(lines)


def _day(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), time(0), tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="days back from --until (1 to 90)")
    parser.add_argument("--since", type=_day, help="first kick-off day (YYYY-MM-DD); overrides --days")
    parser.add_argument("--until", type=_day, help="kick-offs before this day (YYYY-MM-DD; default: now)")
    parser.add_argument("--sample", type=int, default=0, help="also list this many cases to check by hand (0 to 50)")
    parser.add_argument("--json", action="store_true", help="JSON instead of a table")
    args = parser.parse_args(argv)
    moment = datetime.now(UTC)
    until = args.until or moment
    since = args.since or until - timedelta(days=max(1, min(90, args.days)))
    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY) as conn:
        data = report(conn, since=since, until=until, measured_at=moment, sample_size=max(0, min(50, args.sample)))
    print(json.dumps(data, default=str, ensure_ascii=False, indent=2) if args.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
