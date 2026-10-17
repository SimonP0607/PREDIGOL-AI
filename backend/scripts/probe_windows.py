"""Measure what the provider can actually see for THIS account, today.

    python -m scripts.probe_windows --dry-run          # what it would ask, no request
    python -m scripts.probe_windows --yes
    python -m scripts.probe_windows --yes --json

The live scheduler rests on claims about horizons. On the Free plan the result
horizon was THREE DAYS, and nothing in the code knew: eight fixtures we had prices
for stayed permanently 'NS'. An upgrade does not automatically widen every range,
so this asks instead of assuming, and writes the answer down with the date it was
measured - a stale measurement presented as a capability is how the three-day
horizon went unnoticed.

Costs one request per date offset, one per sampled fixture, and one for /odds/live:
about eighteen by default.

Exit status: 0 good, 2 usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.odds.windows_probe import DEFAULT_DATE_OFFSETS, candidate_odds_fixtures, probe_windows


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="probe_windows", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="spend the requests")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--offsets", default="", help="comma-separated day offsets from today")
    parser.add_argument("--fixtures", type=int, default=4, help="how many upcoming fixtures to price")
    args = parser.parse_args()

    offsets = (tuple(int(x) for x in args.offsets.split(",") if x.strip())
               if args.offsets else DEFAULT_DATE_OFFSETS)

    with psycopg.connect(settings.database.psycopg_url) as conn:
        sample = candidate_odds_fixtures(conn, limit=args.fixtures)
        if args.dry_run or not args.yes:
            total = len(offsets) + len(sample) + 1
            print(f"would spend {total} request(s): {len(offsets)} date(s) {list(offsets)}, "
                  f"{len(sample)} fixture(s) {[f'{f} at T-{m}m' for f, m in sample]}, 1 /odds/live")
            if not args.yes:
                print("add --yes to spend them")
            return 0

        from fbi.providers.api_football.build import build_client

        async def go() -> None:
            client = build_client()
            try:
                report = await probe_windows(conn, client, date_offsets=offsets, odds_fixtures=sample)
            finally:
                await client.aclose()
            if args.json:
                print(json.dumps(report.as_dict(), indent=2))
                return
            print(f"measured at {report.measured_at} in {report.requests} request(s)")
            print(f"{'offset':>7} {'date':<12} {'results':>8}  errors")
            for d in report.dates:
                print(f"{d.offset_days:>+7} {d.on.isoformat():<12} {d.results:>8}  "
                      f"{d.provider_errors or ''}")
            print(f"fixture list visible from {report.earliest_visible_offset:+} to "
                  f"{report.latest_visible_offset:+} days"
                  if report.earliest_visible_offset is not None else "no date returned a fixture list")
            print(f"{'fixture':>10} {'T-minutes':>10} {'books':>6} {'bets':>6}  errors")
            for o in report.odds:
                print(f"{o.provider_fixture_id:>10} {o.minutes_to_kickoff:>10} {o.bookmakers:>6} "
                      f"{o.bets:>6}  {o.provider_errors or ''}")
            if report.furthest_priced_minutes is not None:
                days = report.furthest_priced_minutes / 1440
                print(f"prices exist as far out as T-{report.furthest_priced_minutes} minutes "
                      f"({days:.1f} days)")
            else:
                print("no sampled fixture had prices")
            print(f"/odds/live: {'answered' if report.live_answered else 'refused'} - {report.live_detail}")

        asyncio.run(go())
    return 0


if __name__ == "__main__":
    sys.exit(main())
