"""The worker's door to the reduced Council (IA-124, AD-D10): its switch, its cadence and one pass.

``FBI_COUNCIL_REDUCED`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker does not even schedule the
job and nothing of ``fbi.councilpass`` is imported. In the shadow, every ``FBI_COUNCIL_REDUCED_MINUTES`` (30 by default) one pass of
``fbi.councilpass.store`` appends to ``ai.council_reduced`` the reduced Council of every pass of the shadow that has none yet: the rules by
default, the judge only where a material contradiction with value and time is recorded. Database only: no provider, no model; it decides,
stakes and publishes nothing, and nothing a reader opens reads it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

import psycopg

SWITCH: Final = "FBI_COUNCIL_REDUCED"
JOB: Final = "council_reduced_shadow"
EVERY: Final = 30


def mode(env: Mapping[str, str] | None = None) -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


def every_minutes(env: Mapping[str, str] | None = None) -> int:
    """The cadence: 10 to 240 minutes, 30 by default; anything else is the default."""
    e = os.environ if env is None else env
    try:
        value = int(e.get("FBI_COUNCIL_REDUCED_MINUTES", str(EVERY)).strip())
    except ValueError:
        return EVERY
    return value if 10 <= value <= 240 else EVERY


def run(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None) -> dict[str, Any]:
    from fbi.councilpass import store

    return store.run_pass(conn, now=now, code_version=code_version).as_json()
