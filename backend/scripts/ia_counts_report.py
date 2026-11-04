"""The corners and the cards of the AI's shadow, as the Statistics Agent left them (Plan Maestro IA, phase 4).

    python -m scripts.ia_counts_report            # reads only; prints the report as JSON; writes nothing

For each engine of the shadow (``ma-v1`` and ``ma-v1-h`` read the Statistics Agent's assessments, ``cs-v1`` none) over the finished matches of the last
``fbi.ai.shadow.WINDOW``: the settled reviews of corners and cards of the whole match, the CLV of each arm (by what the Statistics Agent said: its
stance, or ``none``), the abstentions, and the model against the market (Brier and log loss on the same rows). The verdict is always ``not_judged``: the
plan asks for 14 days of evaluations and a person reads them (``fbi.ai.shadow.counts_report``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import psycopg

from fbi.ai import shadow
from fbi.core.config import settings
from fbi.families import score


def main() -> int:
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.read_only = True
        report = shadow.counts_report(conn, score, at=datetime.now(UTC))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
