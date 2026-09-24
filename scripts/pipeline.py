"""Run the decision pipeline once: forecasts, evaluation of captured prices, settlement.

    python -m scripts.pipeline            # dry run: everything computed, then rolled back
    python -m scripts.pipeline --apply    # keep it (the worker does this every 30 minutes)

Database only - zero provider requests. Forecasts use the hyper-parameters of
the latest backtest session; picks stay in shadow (publishing is disabled in
the schema); settlement is on the 90-minute score.
"""

from __future__ import annotations

import argparse
from collections import Counter

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.picks.pipeline import run_pipeline


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        r = run_pipeline(conn, at=now(), code_version=code_version(), apply=args.apply)
    f, p, s = r.forecast, r.picks, r.settlement
    assert f is not None and p is not None and s is not None
    print(f"forecast at {f.at.isoformat()}: {f.targets} upcoming tracked fixture(s); "
          f"{f.written} prediction rows written, {f.unchanged} unchanged")
    for model, n in sorted(f.predicted.items()):
        print(f"  {model}: {n} fixture(s)")
    for model, why in f.skipped_models.items():
        print(f"  {model}: skipped - {why}")
    for (model, reason), n in Counter((m, w) for _, m, w in f.uncovered).most_common():
        print(f"  not forecast ({model}) x{n}: {reason}")
    if f.newest_result_at:
        print(f"  newest result behind these forecasts: {f.newest_result_at.isoformat()}")
    print(f"captured prices: {p.instants} consensus instant(s); {p.candidates} new candidate(s), "
          f"{p.already_evaluated} already evaluated; selected {p.selected} (qualified {p.qualified}), "
          f"rejected {p.rejected}")
    for why, n in sorted(p.reasons.items(), key=lambda kv: -kv[1]):
        print(f"  rejected x{n}: {why}")
    print(f"settlement: {s.open_picks} open pick(s); settled {s.settled} {dict(s.by_status)}; "
          f"pending {s.still_pending} ({s.needs_review} need review)")
    print("applied" if args.apply else "dry run - rolled back (use --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
