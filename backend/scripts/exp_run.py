"""The experiments of the plan, when each is due and running the ones that are (RP-8.3, ``exp-conditions-v1``).

    python -m scripts.exp_run --status                 # reading only: every experiment, its sample, whether it is due and why
    python -m scripts.exp_run --due                    # run every experiment that is due, one after another, and write each verdict
    python -m scripts.exp_run --experiment EXP-E1      # run that one, only if it is due
    python -m scripts.exp_run --due --dry-run          # say which would run

It is what the launcher of RP-1.6 runs OUTSIDE the worker (``python -m scripts.experiment_run experiments_due``): one at a time, under a ceiling of memory and of time,
with its row in the book of runs. An experiment runs only when its condition is met (the sample fixed in its protocol is there, the model code changed, four weeks passed
with more matches, or the protocol has a new version) and its verdict is written only if its protocol was registered before the result. An experiment that has not said
how it counts or how it runs is listed as such and never launched. Nothing here changes a model, a forecast, a pick or a threshold. Exit status: 0 done or nothing due,
1 an experiment failed, 2 usage. ``--dsn`` overrides the database.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime

import psycopg

from fbi.core.clock import now
from fbi.research import exp_conditions as ec
from fbi.research import verdicts
from fbi.research.exp_protocol import EXPERIMENTS

READ_ONLY = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=120000"


def load_plugins() -> None:
    ec.load_plugins()


def status_lines(states: Sequence[ec.Due]) -> list[str]:
    out = [f"Experimentos del plan ({ec.VERSION})"]
    for d in states:
        sample = "-" if d.sample is None else f"{d.sample}/{d.required}"
        out.append(f"  {d.experiment:<7} {'TOCA' if d.due else '    '} {d.code:<18} muestra {sample:<11} {d.why}")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="exp_run", description=(__doc__ or "").split("\n\n")[0])
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true")
    group.add_argument("--due", action="store_true")
    group.add_argument("--experiment", choices=sorted(EXPERIMENTS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    from fbi.core.config import settings as platform

    dsn = args.dsn or platform.database.psycopg_url
    load_plugins()
    at: datetime = now()
    if args.status:
        with psycopg.connect(dsn, options=READ_ONLY) as conn:
            sys.stdout.write("\n".join([*status_lines(ec.survey(conn, at=at)), f"Sin veredicto decidido: {', '.join(verdicts.pending(conn)) or 'ninguno'}"]) + "\n")
        return 0
    failed = 0
    with psycopg.connect(dsn, options="-c TimeZone=UTC") as conn:
        todo = ec.due_now(conn, at=at) if args.due else [ec.check(conn, args.experiment, at=at)]
        if not todo:
            sys.stdout.write("Ningún experimento toca.\n")
            return 0
        for d in todo:
            if not d.due:
                sys.stdout.write(f"{d.experiment}: no toca - {d.why}\n")
                continue
            if args.dry_run:
                sys.stdout.write(f"{d.experiment}: correría ({d.code}) - {d.why}\n")
                continue
            try:
                v = ec.run(conn, d.experiment, at=at, due=d)
                conn.commit()
                sys.stdout.write(f"{d.experiment}: {v.verdict} (n={v.n}) - {v.reason}\n")
            except Exception as exc:  # one experiment failing must not stop the next one, and the book must say so
                conn.rollback()
                failed += 1
                sys.stdout.write(f"{d.experiment}: FALLÓ - {type(exc).__name__}: {exc}\n"[:400])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
