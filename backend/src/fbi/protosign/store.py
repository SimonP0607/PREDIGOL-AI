"""The register of the owner's signatures of protocols (IA-143, AD-K07): ``ai.protocol_signatures`` (revision 0166, append-only).

    read     ``signatures`` (every row, oldest first), ``in_force`` (the row that signs a protocol AS IT IS NOW, or None) and ``is_signed``
             - what the readers that used to write ``signed_by_owner: False`` by hand read now. A database without the table (behind the
             code) reads as «not signed», never as an error.
    write    ``sign``: ONE row, the owner's (``scripts/ia_protocols.py sign --confirm-owner``); refused when the fingerprint is not the one in
             force, the reason is not the owner's words or the key is unknown. Signing a fingerprint already signed writes nothing and says
             which row covers it. The caller commits.

Nothing here turns anything on: no job, route or agent changes a switch, a threshold or a version because a row exists, and only the
owner's command writes the table (``tests/unit/test_protocol_signatures.py`` holds both)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.protosign import DECIDED_BY, Signable, catalog, current, sign_problems
from fbi.protosign import in_force as counts

TABLE: Final = "ai.protocol_signatures"
EXISTS_SQL: Final = "SELECT to_regclass('ai.protocol_signatures') IS NOT NULL AS ok"
ROWS_SQL: Final = """
SELECT id, protocol_key, protocol_version, framework, fingerprint, reason, decided_by, signed_at, code_version
  FROM ai.protocol_signatures
 WHERE %(keys)s::text[] IS NULL OR protocol_key = ANY(%(keys)s::text[])
 ORDER BY id
"""
INSERT_SQL: Final = """
INSERT INTO ai.protocol_signatures (protocol_key, protocol_version, framework, fingerprint, reason, decided_by, code_version)
VALUES (%(key)s, %(version)s, %(framework)s, %(fingerprint)s, %(reason)s, 'owner', %(code)s)
ON CONFLICT ON CONSTRAINT protocol_signatures_once DO NOTHING
RETURNING id
"""


def exists(conn: psycopg.Connection[Any]) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EXISTS_SQL)
        row = cur.fetchone()
    return bool(row and row["ok"])


def signatures(conn: psycopg.Connection[Any], keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """The stored signatures (of ``keys``, or all), oldest first; [] without the table."""
    if not exists(conn):
        return []
    wanted = None if keys is None else sorted(set(keys))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROWS_SQL, {"keys": wanted})
        return [dict(r) for r in cur.fetchall()]


def in_force_of(signable: Signable, rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """The first stored row that signs the protocol as it is now, or None. Pure."""
    return next((r for r in rows if counts(signable, r)), None)


def in_force(conn: psycopg.Connection[Any], key: str) -> dict[str, Any] | None:
    """The owner's signature of the protocol ``key`` in the fingerprint the code has now, or None (none, or only of other fingerprints)."""
    signable = current(key)
    return in_force_of(signable, signatures(conn, [key]))


def is_signed(conn: psycopg.Connection[Any], key: str) -> bool:
    return in_force(conn, key) is not None


def overview(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """Every protocol of the catalog with its signature in force (or None) and how many stored signatures are of other fingerprints."""
    rows = signatures(conn)
    out = []
    for key, s in catalog().items():
        mine = [r for r in rows if r["protocol_key"] == key]
        found = in_force_of(s, mine)
        out.append({**s.head(), "signed_by_owner": found is not None, "signature": found,
                    "other_fingerprints": sum(1 for r in mine if not counts(s, r))})
    return out


def sign(conn: psycopg.Connection[Any], key: str, *, fingerprint: str, reason: str, code_version: str | None = None) -> dict[str, Any]:
    """THE OWNER'S ACTION: one row of ``ai.protocol_signatures`` (the caller commits). ``written`` False: that fingerprint was already
    signed (``row`` is the one that signs it), nothing written twice. Raises ValueError for what ``sign_problems`` refuses."""
    found = sign_problems(key, fingerprint, reason)
    if found:
        raise ValueError("; ".join(found))
    s = current(key)
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {"key": s.key, "version": s.version, "framework": s.framework, "fingerprint": s.fingerprint,
                                 "reason": reason.strip(), "code": code_version})
        row = cur.fetchone()
    if row is not None:
        return {"written": True, "row": int(row[0])}
    kept = in_force(conn, key)
    return {"written": False, "row": None if kept is None else int(kept["id"])}


__all__ = ["DECIDED_BY", "EXISTS_SQL", "INSERT_SQL", "ROWS_SQL", "TABLE", "exists", "in_force", "in_force_of", "is_signed", "overview",
           "sign", "signatures"]
