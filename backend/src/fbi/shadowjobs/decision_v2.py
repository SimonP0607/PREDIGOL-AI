"""The worker's door to decision-v2's kept shadow (IA-093, AD-D01): its switch, its cadence and one pass.

``FBI_DECISION_V2`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker does not even schedule
the job and nothing of ``fbi.decision`` is imported. In the shadow, every ``FBI_DECISION_V2_MINUTES`` (5 by default: E4's window is
10 minutes wide) one pass of ``fbi.decision.shadow`` decides the moments due - E1, E4 and the mirror of decision-v1's moments - and
keeps them in ``intel.decision_v2_moments`` and ``intel.decisions_v2``. ``FBI_DECISION_V2_TRIGGERS`` (``E1,E4,mirror`` by default) can
leave some out.

This module is the ONE importer of decision-v2 outside its own package and its command (``tests/unit/test_decision_v2_isolation.py``):
it decides nothing, stakes nothing, publishes nothing and serves no reader; only the worker's scheduler imports it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import psycopg

SWITCH: Final = "FBI_DECISION_V2"
JOB: Final = "decision_v2_shadow"
DEFAULT_TRIGGERS: Final = ("E1", "E4", "mirror")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


def every_minutes(env: Mapping[str, str] | None = None) -> int:
    """The cadence: 1 to 10 minutes (E4's window is 10 minutes wide), 5 by default; anything else is the default."""
    e = os.environ if env is None else env
    try:
        value = int(e.get("FBI_DECISION_V2_MINUTES", "5").strip())
    except ValueError:
        return 5
    return value if 1 <= value <= 10 else 5


def triggers(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The moments the pass decides (``E1``, ``E4``, ``mirror``); words it does not know are left out, and nothing known means all."""
    e = os.environ if env is None else env
    asked = tuple(t.strip() for t in e.get("FBI_DECISION_V2_TRIGGERS", ",".join(DEFAULT_TRIGGERS)).split(",") if t.strip())
    known = tuple(t for t in DEFAULT_TRIGGERS if t in asked)
    return known or DEFAULT_TRIGGERS


def run(conn: psycopg.Connection[Any], *, now: datetime, raw_root: str | Path, code_version: str | None) -> dict[str, Any]:
    """One pass of the kept shadow (the RAW store is where the odds book's answers are read from)."""
    from fbi.decision import shadow
    from fbi.storage.payload_store import PayloadStore

    return shadow.run_pass(conn, now=now, store=PayloadStore(raw_root), triggers=triggers(), code_version=code_version).as_json()
