"""The data truth audit V2 - repeatable, read-mostly checks of what PrediGol holds.

    python -m scripts.audit_data_truth baseline     # counts, spans and latest stamps of every table (read only)

The provider-facing audits have their own commands: ``scripts.audit_standings``,
``scripts.audit_team_stats``, ``scripts.audit_player_stats``. Every report lands under
``data/truth/<stamp>-<kind>/`` (JSON + Markdown); nothing in core, market or features is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.baseline import baseline, markdown

REPORTS = Path("data/truth")


def _connect() -> psycopg.Connection[Any]:
    return psycopg.connect(settings.database.psycopg_url,
                           options="-c default_transaction_read_only=on -c statement_timeout=600000 -c TimeZone=UTC")


def write_report(kind: str, body: dict[str, Any], md: str) -> Path:
    at = now()
    folder = REPORTS / f"{at:%Y%m%dT%H%M%SZ}-{kind}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{kind}.json").write_text(json.dumps(body, indent=1, default=str))
    (folder / f"{kind}.md").write_text(md)
    return folder


def cmd_baseline() -> int:
    with _connect() as conn:
        b = baseline(conn, at=now())
    md = markdown(b)
    folder = write_report("baseline", b, md)
    print(md)
    print(json.dumps(b["extra"], default=str, indent=1))
    print(f"report: {folder}")
    return 0


COMMANDS = {"baseline": cmd_baseline}


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_data_truth", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()
    return COMMANDS[args.command]()


if __name__ == "__main__":
    sys.exit(main())
