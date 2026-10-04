"""Historical validation: every finished match's state and every competition-season's data score.

    python -m scripts.validate_history

Database only, no provider request; one ledger run (historical_validation). See
fbi.validation.historical for the rules and docs/rebuild/MODEL_READY_DATASET.md for what
the approved population is used for.
"""

from __future__ import annotations

import json

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.validation.historical import run_validation


def main() -> int:
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.execute("SET statement_timeout = '600s'")
        report = run_validation(conn, at=now())
    print(json.dumps({"fixtures": report.fixtures, "states": report.states, "failed": report.failed,
                      "seasons": report.seasons, "classes": report.classes}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
