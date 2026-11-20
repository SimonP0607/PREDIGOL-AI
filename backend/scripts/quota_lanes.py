"""The lanes of the daily request budget, read without asking the provider anything (plan PM, PM-04-01; BE-060).

    python -m scripts.quota_lanes show                    the table in force here: switch, ceilings, priorities
    python -m scripts.quota_lanes report [--days 14]      each measured day by lane against its ceiling (raw.provider_endpoint_usage)
    python -m scripts.quota_lanes simulate [--since D]    the ledger's days replayed through the lanes (raw.ingestion_runs, by hour)

``report`` is the evidence of the card's acceptance criterion: fourteen days in which no lane - the vital ones above all - would
have been limited. It reads the counts the usage counter (PM-01-02) writes since 20 Nov 2026, whatever ``FBI_APIFOOTBALL_LANES``
says, so the days can be measured before the switch is turned to ``measure``. ``simulate`` replays the older days from the ledger
(``api_calls`` per hour and job: it does not count the attempts that failed - on 29 Oct 2026 most of them, see OPS-009).

Read-only connection; 0 requests to the provider. Exit 0 always, unless the database cannot be read (1).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.providers.lanes import DEFAULT_LANES, LanePolicy, replay

USAGE_BY_DAY = """
SELECT usage_date, lane, sum(requests)::bigint FROM raw.provider_endpoint_usage
 WHERE provider = 'api_football' AND usage_date >= %(since)s AND usage_date < %(until)s
 GROUP BY 1, 2 ORDER BY 1, 2
"""
LEDGER_BY_HOUR = """
SELECT (started_at AT TIME ZONE 'UTC')::date, extract(hour FROM started_at AT TIME ZONE 'UTC')::int, job_type,
       coalesce(sum(api_calls), 0)::bigint
  FROM raw.ingestion_runs WHERE started_at >= %(since)s AND started_at < %(until)s AND api_calls > 0
 GROUP BY 1, 2, 3
"""


def _policy() -> LanePolicy:
    policy, ignored = LanePolicy.from_settings(settings.provider_plan.lane_ceilings)
    if ignored:
        print(f"# FBI_APIFOOTBALL_LANE_CEILINGS: ignored {', '.join(ignored)}")
    return policy


def show() -> None:
    plan = settings.provider_plan
    policy = _policy()
    print(f"FBI_APIFOOTBALL_LANES={plan.lanes_mode}  budget={plan.effective_budget}")
    print("priority | lane | ceiling | vital | jobs")
    for lane in policy.lanes:
        default = next(d.ceiling for d in DEFAULT_LANES if d.name == lane.name)
        mark = "" if lane.ceiling == default else f" (table {default})"
        print(f"{lane.priority} | {lane.name} | {lane.ceiling}{mark} | {'yes' if lane.vital else 'no'} | {', '.join(lane.jobs) or '-'}")


def _connect() -> Any:
    conn = psycopg.connect(settings.database.psycopg_url)
    conn.execute("SET default_transaction_read_only = on")
    conn.execute("SET statement_timeout = '90s'")
    return conn


def _print_days(days: Sequence[tuple[str, dict[str, int], dict[str, int]]], policy: LanePolicy) -> None:
    names = [lane.name for lane in policy.lanes]
    print("day | total | " + " | ".join(names) + " | limited")
    limited_days = 0
    vital_days = 0
    for day, spent, refused in days:
        cut = [n for n in names if refused.get(n, 0) > 0]
        limited_days += bool(cut)
        vital_days += any(policy.lane(n).vital for n in cut)
        cells = " | ".join(str(spent.get(n, 0)) for n in names)
        print(f"{day} | {sum(spent.values())} | {cells} | {', '.join(f'{n}:{refused[n]}' for n in cut) or '-'}")
    print(f"# {len(days)} day(s): {limited_days} with a lane limited, {vital_days} with a vital lane limited")


def report(conn: Any, days: int) -> None:
    policy = _policy()
    until = now().date()
    since = until - timedelta(days=days)
    by_day: dict[str, dict[str, int]] = {}
    with conn.cursor() as cur:
        cur.execute(USAGE_BY_DAY, {"since": since, "until": until})
        for day, lane, n in cur.fetchall():
            by_day.setdefault(str(day), {})[str(lane)] = int(n)
    rows = []
    for day, spent in sorted(by_day.items()):
        refused = {name: max(0, n - policy.lane(name).ceiling) for name, n in spent.items()}
        rows.append((day, spent, refused))
    print(f"# complete UTC days {since} .. {until - timedelta(days=1)} from raw.provider_endpoint_usage (PM-01-02)")
    _print_days(rows, policy)


def simulate(conn: Any, since: date, until: date) -> None:
    policy = _policy()
    with conn.cursor() as cur:
        cur.execute(LEDGER_BY_HOUR, {"since": since, "until": until})
        rows = [(str(d), int(h), str(job), int(n)) for d, h, job, n in cur.fetchall()]
    print(f"# {since} .. {until - timedelta(days=1)} replayed hour by hour from raw.ingestion_runs.api_calls")
    _print_days([(d.day, d.spent, d.refused) for d in replay(rows, policy)], policy)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="quota_lanes", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int, default=14, choices=range(1, 61), metavar="1..60")
    sp = sub.add_parser("simulate")
    sp.add_argument("--since", type=date.fromisoformat, default=None)
    sp.add_argument("--until", type=date.fromisoformat, default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "show":
        show()
        return 0
    try:
        with _connect() as conn:
            if args.command == "report":
                report(conn, args.days)
            else:
                until = args.until or now().date()
                simulate(conn, args.since or until - timedelta(days=30), until)
    except psycopg.Error as exc:
        print(f"quota_lanes: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
