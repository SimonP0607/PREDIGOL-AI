"""The worker's door to the evaluation after the match (IA-112, AD-K01): its switch, its cadence and one pass.

``FBI_SELECTION_EVAL`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker does not even schedule the
job. In the shadow, every ``FBI_SELECTION_EVAL_MINUTES`` (60 by default) one pass of ``fbi.evalpass.store`` appends to
``intel.selection_evaluations`` the evaluation of every selection settled in the last seven days that has none yet. Database only: no
provider, no model; it decides, stakes and publishes nothing, and nothing a reader opens reads it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

import psycopg

from fbi.evalpass import store

SWITCH: Final = store.SWITCH
JOB: Final = "selection_eval_shadow"


def mode(env: Mapping[str, str] | None = None) -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


def every_minutes(env: Mapping[str, str] | None = None) -> int:
    """The cadence: 15 to 360 minutes, 60 by default; anything else is the default."""
    e = os.environ if env is None else env
    try:
        value = int(e.get("FBI_SELECTION_EVAL_MINUTES", str(store.EVERY)).strip())
    except ValueError:
        return store.EVERY
    return value if 15 <= value <= 360 else store.EVERY


def run(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None) -> dict[str, Any]:
    return store.run_pass(conn, now=now, code_version=code_version).as_json()
