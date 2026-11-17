"""The worker's door to the tracking of loose selections (IA-109, AD-E05) and to ``parlay-v6`` (IA-110, AD-E06), both in SHADOW.

``FBI_SELECTION_SETTLE`` and ``FBI_PARLAY_V6`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker does
not even schedule their jobs. In the shadow, every ``FBI_SELECTION_SETTLE_MINUTES`` (15) one pass of ``fbi.tracking.selections`` settles the
chains of decision-v2's kept shadow on ``settle-v4`` (``intel.selection_settlements`` and the chain's moves), and every
``FBI_PARLAY_V6_MINUTES`` (15) one pass of ``fbi.tracking.parlay_v6_shadow`` builds and keeps ``parlay-v6`` (``intel.parlays_v6``). Neither publishes,
stakes or serves a reader; ``parlay-v5`` is what the product shows, and it is not touched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import psycopg

SETTLE_JOB: Final = "selection_settle_shadow"
PARLAY_JOB: Final = "parlay_v6_shadow"


def settle_mode() -> str:
    from fbi.tracking import selections as tracking

    return tracking.mode()


def parlay_mode() -> str:
    from fbi.tracking import parlay_v6_shadow as v6_shadow

    return v6_shadow.mode()


def settle(conn: psycopg.Connection[Any], *, now: datetime) -> dict[str, Any]:
    """One pass of the tracking of loose selections."""
    from fbi.tracking import selections as tracking

    return tracking.run_pass(conn, now=now).as_json()


def parlays(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None) -> dict[str, Any]:
    """One pass of ``parlay-v6`` in the shadow."""
    from fbi.tracking import parlay_v6_shadow as v6_shadow

    return v6_shadow.run_pass(conn, now=now, code_version=code_version).as_json()
