"""The synthetic journey of the worker (plan UX, A2), once, by hand - to see it work before switching it on, or to
look again after an alert.

    python -m scripts.synthetic_journey            walk it and print each step (no ledger row)
    python -m scripts.synthetic_journey --ledger   the same, and write the ledger row the worker would write

It reads the same configuration as the worker (FBI_SYNTHETIC_BASE_URL, FBI_SYNTHETIC_EMAIL and
FBI_SYNTHETIC_PASSWORD_FILE or FBI_SYNTHETIC_PASSWORD; fbi.ops.synthetic) and prints step names, statuses and times -
never the password, never a body. The account is the owner's to create (a USER without a second factor).
Exit status: 0 every step passed, 1 a step failed, 2 not configured.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from fbi.core.config import settings
from fbi.ops.synthetic import config_from_env, run_once, walk


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", action="store_true", help="write the ledger row the worker would write")
    args = parser.parse_args()
    cfg = config_from_env()
    if cfg is None:
        print("not configured: FBI_SYNTHETIC_BASE_URL, FBI_SYNTHETIC_EMAIL and its password are needed",
              file=sys.stderr)
        return 2
    if args.ledger:
        with psycopg.connect(settings.database.psycopg_url, connect_timeout=5) as conn:
            steps = run_once(conn, cfg)
    else:
        steps = walk(cfg)
    for step in steps:
        status = step.status if step.status is not None else "-"
        print(f"{'ok  ' if step.ok else 'FAIL'} {step.name:<14} {status!s:>4} {step.ms:>6} ms {step.note}")
    return 0 if steps and all(s.ok for s in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
