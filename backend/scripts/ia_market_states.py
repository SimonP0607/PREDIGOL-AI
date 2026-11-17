"""The catalogue of markets with a state (AD-E01, IA-070), from the command line. Read only: nothing here writes to the database.

    python -m scripts.ia_market_states report             # measure now and print the state of every market (and why)
    python -m scripts.ia_market_states report --json      # the same, the whole snapshot as JSON
    python -m scripts.ia_market_states snapshot --out src/fbi/api/services/market_states.json   # measure and write the file the product reads
    python -m scripts.ia_market_states snapshot --from-export facts.json --measured-at 2026-11-17T02:30:00Z --out ...
    python -m scripts.ia_market_states check              # the stored snapshot judged again under this code: 0 equal, 1 drift

``report`` and ``snapshot`` open the connection read only, with a statement timeout of 95 s, and run six bounded queries
(``fbi.api.services.market_status.queries``). ``--from-export`` builds the snapshot from the rows of those same queries exported as JSON
(``json_agg`` of each one, as the measurement of 17-nov-2026 was taken from production). The file only reaches the product in a
reviewed commit: a market changes state when someone reads the diff, never by itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

import psycopg

from fbi.api.services import market_status as ms
from fbi.core.config import settings

STATEMENT_TIMEOUT_MS = 95_000


def _measure(dsn: str | None) -> tuple[ms.Facts, list[ms.MarketStatus]]:
    with psycopg.connect(dsn or settings.database.psycopg_url,
                         options=f"-c TimeZone=UTC -c statement_timeout={STATEMENT_TIMEOUT_MS} "
                                 "-c default_transaction_read_only=on") as conn:
        conn.read_only = True
        facts = ms.collect(conn)
    return facts, ms.build(facts)


def _from_export(path: str, measured_at: str) -> tuple[ms.Facts, list[ms.MarketStatus]]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    at = datetime.fromisoformat(measured_at.replace("Z", "+00:00")).astimezone(UTC)
    facts = ms.facts_from_rows(at, raw)
    return facts, ms.build(facts)


def render(snap: dict) -> str:
    """The owner's table: one line per market that has a key or a price, then the parked bets counted by family."""
    lines = [f"Catálogo {snap['catalog_version']} · medido {snap['measured_at']} · partidos con precio (14 d): {snap['base_fixtures']}",
             "Estados: " + ", ".join(f"{k} {v}" for k, v in snap["counts"].items()), "",
             f"{'mercado':<18}{'estado':<16}{'motivo':<26}{'casas':>6}{'precio':>8}{'liquid.':>9}{'modelo':>8}  calibrador"]
    parked: dict[str, dict[str, int]] = {}
    for m in snap["markets"]:
        ev = m["evidence"]
        if m["key"].startswith("bet_") and not ev["priced_fixtures"]:
            fam = parked.setdefault(f"{m['family']} → {m['state']} ({m['reason']})", {"n": 0})
            fam["n"] += 1
            continue
        share = "-" if not ev["priced_finished"] else f"{100 * ev['settleable'] / ev['priced_finished']:.1f}%"
        books = "-" if ev["books_median"] is None else f"{ev['books_median']:g}"
        lines.append(f"{m['key']:<18}{m['state']:<16}{m['reason']:<26}{books:>6}{ev['priced_fixtures']:>8}{share:>9}"
                     f"{ev['model_fixtures']:>8}  {','.join(ev['champions']) or '-'}")
    lines += ["", "Apuestas sin clave (sin extracción de cuotas al libro), por familia:"]
    lines += [f"  {k}: {v['n']}" for k, v in sorted(parked.items())]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_market_states", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="measure and print (read only)")
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--dsn")
    snp = sub.add_parser("snapshot", help="measure (or read an export) and write the snapshot file")
    snp.add_argument("--out", required=True)
    snp.add_argument("--dsn")
    snp.add_argument("--from-export")
    snp.add_argument("--measured-at", help="with --from-export: when the export was taken (ISO 8601, UTC)")
    chk = sub.add_parser("check", help="judge the stored snapshot again under this code")
    chk.add_argument("--snapshot", default=str(ms.SNAPSHOT))
    args = ap.parse_args(argv)

    if args.command == "check":
        with open(args.snapshot, encoding="utf-8") as fh:
            data = json.load(fh)
        catalogue = ms.parse_snapshot(data)
        drift = [(m["key"], m["state"], m["reason"], catalogue.status(m["key"]).state, catalogue.status(m["key"]).reason)
                 for m in data["markets"]
                 if (m["state"], m["reason"]) != (catalogue.status(m["key"]).state, catalogue.status(m["key"]).reason)]
        for row in drift:
            print("DRIFT {}: stored {}/{}, judged {}/{}".format(*row))
        print(f"{len(data['markets'])} markets, {len(drift)} drift ({data['catalog_version']} measured {data['measured_at']})")
        return 1 if drift else 0

    if args.command == "snapshot" and args.from_export:
        if not args.measured_at:
            ap.error("--from-export needs --measured-at")
        facts, statuses = _from_export(args.from_export, args.measured_at)
    else:
        facts, statuses = _measure(args.dsn)
    snap = ms.snapshot(facts, statuses)
    if args.command == "snapshot":
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(ms.dump_snapshot(snap))
        print(render(snap))
        return 0
    print(json.dumps(snap, ensure_ascii=False, indent=1) if args.json else render(snap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
