"""How long before kick-off the official line-ups reach us, per competition (IA-069, plan piece AD-D05). Read only.

    python -m scripts.ia_lineup_timing                 # the last 14 days, as a table
    python -m scripts.ia_lineup_timing --days 30
    python -m scripts.ia_lineup_timing --json          # the same figures, as JSON

It reads through a connection the server keeps READ ONLY, with a 90-second statement timeout, and needs no provider call.
For each competition: matches played, with both line-ups, with them before kick-off, and the minutes between the first
sighting of both sides and the kick-off (median, p10, p90); how many were seen first by the watch (``FBI_LINEUP_WATCH``);
how many had a starter changed before kick-off; and the closing check (line-up rows with ``first_seen_at``). The official
publication is not compared: no permitted source dates it (AD-C02). Explained in docs/owner/IA_069_ALINEACION_A_TIEMPO.md.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.ingestion.lineup_timing import report

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=90000 -c TimeZone=UTC"


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def render(data: dict[str, Any]) -> str:
    w, o, fs = data["window"], data["overall"], data["first_seen"]
    lines = [f"Alineaciones oficiales: {w['start'][:10]} a {w['end'][:10]} (medido {w['measured_at'][:16]} UTC)",
             f"Total: {o['played']} partidos jugados, {o['with_lineups']} con las dos alineaciones, "
             f"{o['before_kickoff']} antes del saque; minutos antes del saque: mediana {_fmt(o['median_min'])}, "
             f"p10 {_fmt(o['p10_min'])}, p90 {_fmt(o['p90_min'])}; vistas antes por el sondeo: {o['first_by_watch']}; "
             f"con un titular cambiado antes del saque: {o['starter_changed']}",
             f"first_seen_at: {fs['with_first_seen']} de {fs['rows']} filas de alineación ({fs['without_first_seen']} sin él)",
             f"Publicación oficial: {data['official_note']}", "",
             "competición | tipo | jugados | con alineación | antes del saque | mediana | p10 | p90 | sondeo primero | "
             "titular cambiado | muestra"]
    for r in data["competitions"]:
        lines.append(" | ".join((str(r["competition"]), _fmt(r["type"]), str(r["played"]), str(r["with_lineups"]),
                                 str(r["before_kickoff"]), _fmt(r["median_min"]), _fmt(r["p10_min"]), _fmt(r["p90_min"]),
                                 str(r["first_by_watch"]), str(r["starter_changed"]),
                                 "pequeña" if r["small_sample"] else "ok")))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=14, help="days back from now (1 to 90)")
    parser.add_argument("--json", action="store_true", help="JSON instead of a table")
    args = parser.parse_args(argv)
    days = max(1, min(90, args.days))
    moment = datetime.now(UTC)
    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY) as conn:
        data = report(conn, start=moment - timedelta(days=days), end=moment, now=moment)
    print(json.dumps(data, default=str, ensure_ascii=False, indent=2) if args.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
