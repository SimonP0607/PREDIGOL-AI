"""PM-12-06: the models judged by competition and by coverage level (``fbi.backtesting.segments``) - the owner's private command.

    python -m scripts.model_segments show [--source forecast --source prediction] [--market 1X2] [--kind competition] [--top 40]
    python -m scripts.model_segments check [--session 4]       # the segments add back to the global figures; a LAB session's runs too
    python -m scripts.model_segments verdicts --league 239     # the newest stored verdicts of one competition (what state 5 reads)
    python -m scripts.model_segments run                       # compute and append the report (what the weekly batch does)

Inside the worker's container (``docker exec predigol-worker python -m scripts.model_segments ...``). ``show``, ``check`` and
``verdicts`` read only (a READ ONLY connection, 90 s per statement) and print; ``run`` appends one report to
``analytics.evaluation_reports`` and ``analytics.evaluation_segments`` and nothing else. 0 provider requests; no pick, model, threshold
or forecast changes. ``check`` exits 1 when a reproduction fails.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any


def _line(s: dict[str, Any]) -> str:
    ci = "" if s["log_loss_low"] is None else f" [{s['log_loss_low']:.4f}; {s['log_loss_high']:.4f}]"
    sk = "" if s["skill_high"] is None else f" [{s['skill_low']:+.4f}; {s['skill_high']:+.4f}]"
    return (f"{s['source']:10} {s['model'][:28]:28} {s['market']:4} {s['kind']:11} {str(s['key'])[:14]:14} n {s['n']:>5} "
            f"días {s['days']:>3}  log loss {s['log_loss']:.4f}{ci}  Brier {s['brier']:.4f}  habilidad {s['skill']:+.4f}{sk}  "
            f"{s['verdict']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    show = sub.add_parser("show")
    show.add_argument("--source", action="append", choices=("forecast", "prediction"))
    show.add_argument("--market", choices=("1X2", "OU", "BTTS"))
    show.add_argument("--kind", choices=("global", "competition", "level"))
    show.add_argument("--top", type=int, default=40, help="the segments with most matches (0: all)")
    show.add_argument("--json", action="store_true")
    for p in (show, sub.add_parser("check"), sub.add_parser("run")):
        p.add_argument("--from", dest="start", type=date.fromisoformat, help="first Bogotá day of kick-off (default 2026-10-23)")
        p.add_argument("--at", type=datetime.fromisoformat)
    check = sub.choices["check"]
    check.add_argument("--session", type=int, help="also a LAB session: its runs' global 1X2 figures against the stored ones")
    verdicts = sub.add_parser("verdicts")
    verdicts.add_argument("--league", type=int, required=True, help="the provider's league id")
    args = parser.parse_args(argv)

    import psycopg

    from fbi.backtesting import segments as sg
    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.core.version import code_version

    write = args.cmd == "run"
    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name=sg.JOB) as conn:
        if not write:
            conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '90s'")
        if args.cmd == "verdicts":
            found = conn.execute("SELECT id FROM core.competitions WHERE provider_league_id = %s", (args.league,)).fetchone()
            if found is None:
                print({"error": "competicion_desconocida"})
                return 1
            rows = conn.execute(sg.LATEST_SQL, {"key": str(found[0])}).fetchall()
            print({"league": args.league, "competition_id": int(found[0]), "verdicts": [list(r) for r in rows] or "sin_veredicto"})
            return 0
        at = args.at or now()
        start = args.start or sg.FIRST_DAY
        sources: tuple[str, ...] = tuple(getattr(args, "source", None) or ("forecast", "prediction"))
        session = getattr(args, "session", None)
        if session is not None:
            sources = (*sources, "backtest")
        rep = sg.report(conn, at=at, start=start, sources=sources, session=session)
        if args.cmd == "run":
            report_id = sg.store(conn, rep, code_version=code_version())
            conn.commit()
            print({"report_id": report_id, "segments": len(rep["segments"]), "reproduced": rep["reproduced"], "counts": rep["counts"]})
            return 0
        if args.cmd == "check":
            for r in rep["reproduction"]:
                print(r)
            for r in rep.get("backtest_reproduction", []):
                print({"backtest": True, **r})
            ok = rep["reproduced"] and all(r["reproduced"] for r in rep.get("backtest_reproduction", []))
            print({"reproducido": ok, "comprobaciones": len(rep["reproduction"]) + len(rep.get("backtest_reproduction", []))})
            return 0 if ok else 1
        chosen = [sg.public(s) for s in rep["segments"] if (args.market is None or s["market"] == args.market)
                  and (args.kind is None or s["kind"] == args.kind)]
        chosen.sort(key=lambda s: (s["kind"] != "global", -s["n"]))
        if args.top:
            chosen = chosen[: args.top]
        if args.json:
            print(json.dumps({**{k: v for k, v in rep.items() if k != "segments"}, "segments": chosen}, ensure_ascii=False,
                             default=str))
            return 0
        print(rep["notice_es"])
        print({"periodo": [rep["period_from"], rep["period_to"]], "necesarios": rep["needed"], "incompletos": rep["incomplete"],
               "reproducido": rep["reproduced"]})
        for c in rep["counts"]:
            print(c)
        for s in chosen:
            print(_line(s))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
