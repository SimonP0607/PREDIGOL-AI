"""Write sanitised provider payloads from the raw store into tests/fixtures/contracts.

    python -m scripts.extract_contract_fixtures
    python -m scripts.extract_contract_fixtures --out tests/fixtures/contracts --entries 2

A normaliser tested only against hand-written JSON is tested against what we BELIEVE
the provider sends. Asian Handicap's sign and the in-play bet namespace were both
found by reading real payloads. These fixtures pin the real shapes in the repository,
so the contract tests have no Internet dependency.

Trimmed to a couple of entries each and sanitised: the envelope's params are dropped
entirely, any key that looks like a credential is redacted, image URLs are replaced.
Ids, names, scores, odds and coverage flags are KEPT - they are the contract.

Exit status: 0 good, 1 an endpoint had no stored payload, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ops.contract_fixtures import DEFAULT_ENDPOINTS, extract

REPO = Path(__file__).resolve().parents[1]


def _raw_root() -> Path:
    root = Path(settings.runtime.raw_store_dir)
    return root if root.is_absolute() else REPO / root


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="extract_contract_fixtures", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(REPO / "tests" / "fixtures" / "contracts"))
    parser.add_argument("--entries", type=int, default=2)
    args = parser.parse_args()

    with psycopg.connect(settings.database.psycopg_url) as conn:
        report = extract(conn, _raw_root(), Path(args.out), endpoints=DEFAULT_ENDPOINTS,
                         max_entries=args.entries)

    for name in report.written:
        print(f"  wrote {name}")
    for problem in report.skipped:
        print(f"  SKIPPED {problem}")
    print(f"{len(report.written)} fixture(s), {report.bytes_written} bytes, "
          f"{report.redactions} redaction(s)")
    return 1 if report.skipped else 0


if __name__ == "__main__":
    sys.exit(main())
