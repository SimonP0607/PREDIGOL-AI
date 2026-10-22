"""Freeze what the platform shows today: every admin page and product endpoint as JSON,
plus exact row counts, into a dated folder. Reads only.

    python -m scripts.baseline_snapshot --label pre-critical-rebuild
    python -m scripts.baseline_snapshot --label legacy-research-run --out data/baselines

Exit status: 0 written (failures are listed in manifest.json), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.ops.baseline import snapshot


def _admin_client() -> Any:
    """The API in-process, as an operator. Only this offline process is signed in."""
    from fastapi.testclient import TestClient

    from fbi.api.app import create_app
    from fbi.api.security import optional_principal
    from fbi.auth.roles import permissions_for
    from fbi.auth.service import Principal

    app = create_app()
    operator = Principal(user_id=0, email="operator@localhost", display_name="Baseline snapshot",
                         role="SUPER_ADMIN", language="en", timezone="UTC", session_id="0" * 64,
                         session_expires_at=datetime.now(UTC) + timedelta(hours=2),
                         permissions=permissions_for("SUPER_ADMIN"))
    app.dependency_overrides[optional_principal] = lambda: operator
    return TestClient(app, headers={"x-requested-with": "predigol"})


def main() -> int:
    parser = argparse.ArgumentParser(prog="baseline_snapshot", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--out", type=Path, default=Path("data/baselines"))
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url,
                         options="-c default_transaction_read_only=on -c statement_timeout=300000") as conn:
        report = snapshot(conn, args.out, label=args.label, client=_admin_client())
    print(json.dumps({"folder": str(report.folder), "endpoints": len(report.endpoints),
                      "non_200": {k: v for k, v in report.endpoints.items() if v != 200},
                      "failures": report.failures, "tables": len(report.tables)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
