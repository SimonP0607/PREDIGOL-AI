"""The worker's door to ``credibility-v2`` (IA-126, AD-C08): its switch, its cadence and one snapshot kept by version.

``FBI_SOURCE_CREDIBILITY`` = ``off`` (the default; any word not understood is ``off``) or ``shadow``. Off, the worker does not even
schedule the job. In the shadow, once a day (``FBI_SOURCE_CREDIBILITY_HOURS``, 24 by default) the credibility of every source by type
of fact, as of the moment of the pass, is appended to ``ai.source_credibility`` (revision 0162, append-only): one row per source, tier
and type, with its sample, its rate, its Wilson 95 % interval and whether it reaches the registered minimum. A second pass at the same
moment writes nothing (``source_credibility_once``).

Database only: no provider, no model. It changes no status, no confidence, no tier, no domain and nothing a reader, a packet, a decision
or a pick reads; the engine's confidence keeps reading ``credibility-v1``. The owner reads the rows with ``scripts/ia_credibility.py``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.evidence import credibility
from fbi.evidence.credibility_reads import snapshot

SWITCH: Final = "FBI_SOURCE_CREDIBILITY"
JOB: Final = "source_credibility_shadow"
EVERY_HOURS: Final = 24

INSERT_SQL: Final = """
INSERT INTO ai.source_credibility (version, digest, as_of, outlet, tier, fact_type, resolved, corroborated, value, basis, prior,
                                   rate, ci_low, ci_high, sufficient, min_resolved, typed, detail, code_version)
VALUES (%(version)s, %(digest)s, %(as_of)s, %(outlet)s, %(tier)s, %(fact_type)s, %(resolved)s, %(corroborated)s, %(value)s, %(basis)s,
        %(prior)s, %(rate)s, %(ci_low)s, %(ci_high)s, %(sufficient)s, %(min_resolved)s, %(typed)s, %(detail)s, %(code_version)s)
ON CONFLICT ON CONSTRAINT source_credibility_once DO NOTHING
"""


def mode(env: Mapping[str, str] | None = None) -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


def every_hours(env: Mapping[str, str] | None = None) -> int:
    """The cadence: 6 to 168 hours, 24 by default; anything else is the default."""
    e = os.environ if env is None else env
    try:
        value = int(e.get("FBI_SOURCE_CREDIBILITY_HOURS", str(EVERY_HOURS)).strip())
    except ValueError:
        return EVERY_HOURS
    return value if 6 <= value <= 168 else EVERY_HOURS


def rows_of(snap: Mapping[str, Any], *, code_version: str | None) -> list[dict[str, Any]]:
    """The rows of ``ai.source_credibility`` of one snapshot (pure)."""
    out = []
    for c in snap["credibilities"]:
        ci = c["ci95"]
        out.append({"version": credibility.VERSION, "digest": snap["digest"], "as_of": snap["at"], "outlet": str(c["outlet"])[:253],
                    "tier": c["tier"], "fact_type": c["fact_type"], "resolved": c["resolved"], "corroborated": c["corroborated"],
                    "value": c["value"], "basis": c["basis"], "prior": c["prior"], "rate": c["rate"],
                    "ci_low": None if ci is None else ci[0], "ci_high": None if ci is None else ci[1], "sufficient": c["sufficient"],
                    "min_resolved": c["min_resolved"], "typed": snap["typed"], "detail": Jsonb({"word": c["word"]}),
                    "code_version": code_version})
    return out


def run(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None, typed: bool | None = None,
        record: bool = True) -> dict[str, Any]:
    """One snapshot as of ``now``; with ``record`` its rows appended (the caller's connection commits). ``typed`` is the one question every
    reader of ``ai.evidence`` asks (``fbi.ai.gates.typed_visible``) - asked here when the caller does not answer it."""
    if typed is None:
        from fbi.ai.gates import typed_visible

        typed = typed_visible(conn)
    snap = snapshot(conn, at=now, typed=typed)
    rows = rows_of(snap, code_version=code_version)
    written = 0
    if record and rows:
        with conn.cursor(row_factory=tuple_row) as cur:
            for row in rows:
                cur.execute(INSERT_SQL, row)
                written += max(cur.rowcount, 0)
    return {"version": credibility.VERSION, "at": snap["at"], "claims": snap["claims"], "rows": len(rows), "written": written,
            "sufficient": sum(1 for r in rows if r["sufficient"]), "differences": snap["replay"]["by_reason"], "typed": typed}
