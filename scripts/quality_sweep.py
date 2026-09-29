"""Run the data-quality sweep: look for what can go wrong, record what is found.

    python -m scripts.quality_sweep              # verify only, writes nothing
    python -m scripts.quality_sweep --apply
    python -m scripts.quality_sweep --apply --json

Nothing is repaired. A duplicate, an impossible value, a result that cannot be
derived: each is recorded in audit.data_quality_issues with its provenance, and the
check itself is recorded in audit.data_quality_checks WITH THE DENOMINATOR it ran
against - so a coverage figure can be read without inventing one.

Exit status: 0 nothing of severity error or above, 1 something needs a human,
2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.quality.detect import sweep
from fbi.quality.issues import Severity


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="quality_sweep", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with psycopg.connect(settings.database.psycopg_url) as conn:
        ledger = RunLedger(conn)
        run_id = ledger.open("quality_sweep", params={"apply": args.apply})
        counters = RunCounters()
        report = None
        try:
            report = sweep(conn, run_id=run_id, apply=args.apply)
            counters.rows_inserted = report.issues_opened
            counters.rows_updated = report.issues_seen_again
        finally:
            ledger.close(run_id, counters,
                         notes=f"{len(report.checks)} checks" if report else "the sweep did not finish")
            conn.commit()
        assert report is not None

        if args.json:
            print(json.dumps({"run_id": run_id, "checks": [
                {"name": c.name, "scope": c.scope, "severity": c.severity.value,
                 "population": c.population, "offenders": c.offenders, "ratio": c.ratio,
                 "detail": c.detail} for c in report.checks],
                "issues_opened": report.issues_opened,
                "issues_seen_again": report.issues_seen_again}, indent=2))
        else:
            print(f"{'check':<30} {'scope':<22} {'population':>11} {'offenders':>10} {'ratio':>8}")
            for c in report.checks:
                pop = "-" if c.population is None else str(c.population)
                ratio = "-" if c.ratio is None else f"{c.ratio:.4f}"
                print(f"{c.name:<30} {c.scope:<22} {pop:>11} {c.offenders:>10} {ratio:>8}")
                if c.detail:
                    print(f"    {c.detail}")
            print(f"run {run_id}: {report.issues_opened} issue(s) opened, "
                  f"{report.issues_seen_again} seen again"
                  + ("" if args.apply else "  (nothing written: add --apply)"))

    serious = [c for c in report.checks
               if c.offenders and c.severity in (Severity.ERROR, Severity.CRITICAL)]
    return 1 if serious else 0


if __name__ == "__main__":
    sys.exit(main())
