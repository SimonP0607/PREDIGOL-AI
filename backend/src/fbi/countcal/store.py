"""The calibrators of the counts and the owner's signature (IA-095): ``intel.count_calibrators`` and
``intel.count_calibrator_signatures`` (revision 0152), append-only.

* ``save``      one fit of one family's calibrator, with the verdict of the protocol AD-B07 and its stamp. Written only by the owner's
                command (``scripts/count_calibration.py fit --write``) while ``FBI_COUNT_CALIBRATION=shadow``; nothing schedules it.
* ``sign``      the owner's CHAMPION or RETIRED on a calibrator. The code refuses a CHAMPION without VALIDADO, and so does the
                database (its trigger): nothing is promoted by itself.
* ``champions`` the calibrator each family may use at a moment: the newest CHAMPION signature not followed by a RETIRED one.

Nothing here writes ``intel.calibrators`` (the binary calibrators of one selection) or ``intel.promotions``: their readers would take a
count calibrator for one of theirs (migration 0152 says why).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.countcal import calibrator as cc
from fbi.countcal.walkforward import VALIDATED, VERDICTS

SWITCH: Final = "FBI_COUNT_CALIBRATION"
CHAMPION: Final = "CHAMPION"
RETIRED: Final = "RETIRED"


def mode() -> str:
    """``shadow`` lets the owner's command write a fit; any other word (``off``, the default) does not."""
    return "shadow" if os.environ.get(SWITCH, "off").strip().lower() == "shadow" else "off"


class NotValidatedError(ValueError):
    """A calibrator whose verdict is not VALIDADO cannot be signed CHAMPION."""


@dataclass(frozen=True, slots=True)
class Stored:
    id: int
    family: str
    params: cc.Params
    known_at: datetime
    verdict: str


INSERT_SQL: Final = """
INSERT INTO intel.count_calibrators (family, measure, version, method, params, known_at, fitted_at, train_from, train_to, n_matches,
    verdict, protocol, report, code_version)
VALUES (%(family)s, %(measure)s, %(version)s, %(method)s, %(params)s, %(known_at)s, %(fitted_at)s, %(train_from)s, %(train_to)s,
    %(n_matches)s, %(verdict)s, %(protocol)s, %(report)s, %(code_version)s)
RETURNING id
"""

SIGN_SQL: Final = """
INSERT INTO intel.count_calibrator_signatures (calibrator_id, role, signed_by, signature, at)
VALUES (%(calibrator_id)s, %(role)s, %(signed_by)s, %(signature)s, %(at)s)
RETURNING id
"""

CHAMPIONS_SQL: Final = """
SELECT DISTINCT ON (c.family) c.id, c.family, c.params, c.known_at, c.verdict, s.role
  FROM intel.count_calibrator_signatures s JOIN intel.count_calibrators c ON c.id = s.calibrator_id
 WHERE s.at <= %(at)s
 ORDER BY c.family, s.at DESC, s.id DESC
"""
"""The newest signature of each family by ``at``: the family has a champion only when that signature says CHAMPION."""


def save(conn: psycopg.Connection[Any], *, family: str, params: cc.Params, known_at: datetime, fitted_at: datetime, verdict: str,
         protocol: Mapping[str, Any], report: Mapping[str, Any], train_from: date | None, train_to: date | None,
         code_version: str | None) -> int:
    if family not in cc.FAMILIES:
        raise ValueError(f"not a family of counts: {family!r}")
    if verdict not in VERDICTS:
        raise ValueError(f"not a verdict of the protocol: {verdict!r}")
    row = conn.execute(INSERT_SQL, {
        "family": family, "measure": cc.MEASURE_OF[family], "version": cc.VERSION, "method": cc.METHOD,
        "params": json.dumps({**params.as_json(), "lines": list(cc.LADDERS[family])}), "known_at": known_at, "fitted_at": fitted_at,
        "train_from": train_from, "train_to": train_to, "n_matches": params.n_matches, "verdict": verdict,
        "protocol": json.dumps(dict(protocol)), "report": json.dumps(dict(report), default=str), "code_version": code_version,
    }).fetchone()
    assert row is not None
    return int(row[0])


def verdict_of(conn: psycopg.Connection[Any], calibrator_id: int) -> str | None:
    row = conn.execute("SELECT verdict FROM intel.count_calibrators WHERE id = %s", (calibrator_id,)).fetchone()
    return None if row is None else str(row[0])


def sign(conn: psycopg.Connection[Any], *, calibrator_id: int, role: str, signed_by: str, signature: str, at: datetime) -> int:
    """The owner's word on a calibrator. A CHAMPION needs the verdict VALIDADO (checked here and by the database)."""
    if role not in (CHAMPION, RETIRED):
        raise ValueError(f"a signature is CHAMPION or RETIRED, not {role!r}")
    verdict = verdict_of(conn, calibrator_id)
    if verdict is None:
        raise LookupError(f"no count calibrator {calibrator_id}")
    if role == CHAMPION and verdict != VALIDATED:
        raise NotValidatedError(f"calibrator {calibrator_id} is {verdict}: only a VALIDADO calibrator can be signed CHAMPION")
    row = conn.execute(SIGN_SQL, {"calibrator_id": calibrator_id, "role": role, "signed_by": signed_by, "signature": signature,
                                  "at": at}).fetchone()
    assert row is not None
    return int(row[0])


def params_of(raw: Mapping[str, Any]) -> cc.Params:
    return cc.Params(float(raw["a"]), float(raw["b"]), int(raw.get("n_matches", 0)), int(raw.get("n_events", 0)))


LATEST_SQL: Final = """
SELECT DISTINCT ON (family) family, verdict FROM intel.count_calibrators WHERE known_at <= %(at)s ORDER BY family, known_at DESC, id DESC
"""


def latest_verdicts(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, str]:
    """The verdict of the newest fit of each family by ``at``."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LATEST_SQL, {"at": at})
        return {str(r["family"]): str(r["verdict"]) for r in cur.fetchall()}


def champions(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Stored]:
    """The calibrator each family may use at ``at`` (none until the owner signs one)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CHAMPIONS_SQL, {"at": at})
        rows = cur.fetchall()
    return {str(r["family"]): Stored(int(r["id"]), str(r["family"]), params_of(r["params"]), r["known_at"], str(r["verdict"]))
            for r in rows if r["role"] == CHAMPION and r["verdict"] == VALIDATED}
