"""Launch an experiment in the operations container (RP-1.6): one at a time, under a ceiling of memory and of time, with its row in the book.

    python -m scripts.experiment_run research_v2                   # when it is due, outside match hours, 2048 MB, 2 h
    python -m scripts.experiment_run research_v2 --dry-run         # say what it would do
    python -m scripts.experiment_run research_v2 --force           # ignore "not due" (the freeze still holds), still under the guards
    python -m scripts.experiment_run research_v2 --allow-match-hours --memory-mb 1536 --timeout-s 3600

Only the jobs listed in ``fbi.research.launcher.JOBS`` can be launched. Exit status: 0 completed or skipped (not due), 1 the experiment failed
(error, memory ceiling or time ceiling), 3 refused (another experiment runs, or match hours), 2 usage error. ``--dsn`` overrides the database
(the operations container's own by default).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from fbi.core.clock import now
from fbi.research import launcher

OK, FAILED, USAGE, REFUSED = 0, 1, 2, 3


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="experiment_run", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("job", choices=sorted(launcher.JOBS))
    ap.add_argument("--memory-mb", type=int)
    ap.add_argument("--timeout-s", type=int)
    ap.add_argument("--allow-match-hours", action="store_true", help="the owner's order to run while a match is on")
    ap.add_argument("--force", action="store_true", help="run even if it is not due (a freeze for audit still stops it)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    for name in ("memory_mb", "timeout_s"):
        v = getattr(args, name)
        if v is not None and v < 1:
            ap.error(f"--{name.replace('_', '-')} must be positive")
    from fbi.core.config import settings as platform

    dsn = args.dsn or platform.database.psycopg_url

    def connect() -> psycopg.Connection[Any]:
        return psycopg.connect(dsn, options="-c TimeZone=UTC")

    gate = launcher.research_gate if launcher.JOBS[args.job].gate == "research_v2" else None
    out = launcher.launch(args.job, connect=connect, at=now(), memory_mb=args.memory_mb, timeout_s=args.timeout_s,
                          allow_match_hours=args.allow_match_hours, force=args.force, dry_run=args.dry_run, gate=gate)
    sys.stdout.write(f"{args.job}: {out.status} - {out.reason} (peak {out.peak_mb} MB, {out.seconds:.0f} s)\n")
    if out.extra.get("tail") and out.status == "failed":
        sys.stdout.write(f"  last lines: {out.extra['tail']}\n")
    if out.refused:
        return REFUSED
    return OK if out.ok else FAILED


if __name__ == "__main__":
    raise SystemExit(main())
