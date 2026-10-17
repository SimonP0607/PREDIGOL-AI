"""BOOKMAKER_COVERAGE_REPORT: which bookmakers price which competitions, markets and countries.

    python -m scripts.odds_coverage              # the last 14 days of played matches
    python -m scripts.odds_coverage --days 30

Database only: no provider request. Writes data/odds_coverage/<stamp>/REPORT.md and
report.json and prints the summary. Exit status 1 when a competition with played matches
was never asked for (our gap, not the provider's).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.market.coverage import DEFAULT_DAYS, build_report, is_critical, render_markdown


def main() -> int:
    parser = argparse.ArgumentParser(prog="odds_coverage", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--out", type=Path, default=Path("data/odds_coverage"))
    args = parser.parse_args()
    at = now()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET statement_timeout = '300s'")
        report = build_report(conn, at=at, days=args.days)
    folder = args.out / f"{at:%Y%m%dT%H%M%S}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "REPORT.md").write_text(render_markdown(report), encoding="utf-8")
    (folder / "report.json").write_text(json.dumps(report.as_dict(), indent=1, default=str), encoding="utf-8")
    print(json.dumps({"folder": str(folder), **report.summary()}, indent=1, default=str))
    return 1 if is_critical(report) else 0


if __name__ == "__main__":
    sys.exit(main())
