"""The worker's door to the evaluation cycle (IA-105..IA-108, AD-D06, AD-D07, AD-D08, AD-D03): its switch, its cadences and its passes.

``FBI_EVAL_CYCLE`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker schedules neither job and
nothing of ``fbi.evalcycle`` is imported. In the shadow:

* ``eval_cycle_shadow`` every ``FBI_EVAL_CYCLE_MINUTES`` (5 by default: E4's window is 10 minutes wide): the match read again, E1, E2,
  E4 and the chains of the cycle of states (``fbi.evalcycle.run.run_pass``);
* ``eval_cycle_e3`` every ``FBI_EVAL_CYCLE_E3_SECONDS`` (60 by default, 30 to 120): E3 for the official line-ups that arrived
  (``run_line_ups``), so that E3 ends within two minutes of the line-up's first sighting.

The passes ``first``, ``pre`` and ``final`` (``fbi.ai.day``) keep running as they are: the cycle is a shadow beside them until the owner
signs their retirement. With the cycle on, decision-v2's own pass can keep only its mirror (``FBI_DECISION_V2_TRIGGERS=mirror``): E1 and
E4 adopt the moment that pass kept when there is one, so nothing is decided twice either way.

Only the worker's scheduler imports this module; nothing it writes is read by a decision, a pick or a page.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import psycopg

SWITCH: Final = "FBI_EVAL_CYCLE"
JOB: Final = "eval_cycle_shadow"
JOB_E3: Final = "eval_cycle_e3"


def mode(env: Mapping[str, str] | None = None) -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


def _number(env: Mapping[str, str] | None, name: str, default: int, low: int, high: int) -> int:
    e = os.environ if env is None else env
    try:
        value = int(e.get(name, str(default)).strip())
    except ValueError:
        return default
    return value if low <= value <= high else default


def every_minutes(env: Mapping[str, str] | None = None) -> int:
    """The main pass's cadence: 1 to 10 minutes (E4's window is 10 minutes wide), 5 by default."""
    return _number(env, "FBI_EVAL_CYCLE_MINUTES", 5, 1, 10)


def e3_every_seconds(env: Mapping[str, str] | None = None) -> int:
    """E3's cadence: 30 to 120 seconds, 60 by default (E3 must end within two minutes of the line-up's first sighting)."""
    return _number(env, "FBI_EVAL_CYCLE_E3_SECONDS", 60, 30, 120)


def _estimates(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> Mapping[str, Any] | None:
    """The estimated starters of a match as of ``at`` (IA-094's reading, the same function its job keeps them with)."""
    from fbi.ai.gates import typed_visible
    from fbi.shadowjobs import lineup_estimate

    return lineup_estimate.estimate_fixture(conn, fixture_id, at=at, typed=typed_visible(conn))


def run(conn: psycopg.Connection[Any], *, now: datetime, raw_root: str | Path, code_version: str | None) -> dict[str, Any]:
    """One main pass (the RAW store is where the odds book's answers and the line-ups' answers are read from)."""
    from fbi.evalcycle import run as cycle
    from fbi.storage.payload_store import PayloadStore

    return cycle.run_pass(conn, now=now, store=PayloadStore(raw_root), estimates=_estimates, code_version=code_version).as_json()


def run_e3(conn: psycopg.Connection[Any], *, now: datetime, raw_root: str | Path, code_version: str | None) -> dict[str, Any]:
    """One E3 pass."""
    from fbi.evalcycle import run as cycle
    from fbi.storage.payload_store import PayloadStore

    return cycle.run_line_ups(conn, now=now, store=PayloadStore(raw_root), code_version=code_version).as_json()
