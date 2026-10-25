"""A reader's consents: what they accepted or withdrew, on which version of which text, in which language, and when
(plan UX, A4; plan de seguridad, section 23).

Every decision is a new row of ``customer.consents`` (append-only: the database refuses an edit or a delete), with
the document's version, the sha256 of the text in the language it was read and the sentence of the box. The latest
row of a purpose is the reader's answer. The four required purposes are what the gate checks: none may be missing,
withdrawn, or given on a version a material change has replaced.

The gate (``FBI_CONSENT_GATE``) is born off. ``1`` turns it on only once no required text is a draft (the lawyer's OK
first, P5); ``drafts`` turns it on regardless, for QA and never for production. SUPER_ADMIN (the controller does not
consent to its own processing) and the synthetic journey's account (``FBI_SYNTHETIC_EMAIL``, a robot) are exempt.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.customer import legal
from fbi.customer.db import CustomerError, write_connection

GATE_ENV = "FBI_CONSENT_GATE"
Source = Literal["gate", "profile", "activation"]
LOCK_KEY = 0x434F4E53
"""``pg_advisory_xact_lock(LOCK_KEY, user_id)``: one reader's decisions are written one transaction at a time."""


@dataclass(frozen=True, slots=True)
class Consent:
    id: int
    kind: str
    granted: bool
    document: str
    version: str
    sha256: str
    locale: str
    statement: str
    source: str
    replaces_id: int | None
    at: datetime


@dataclass(frozen=True, slots=True)
class Decision:
    kind: str
    granted: bool
    version: str
    """The version of the text the reader was shown: it must be the current one (else the proof would be wrong)."""


def gate_mode() -> Literal["off", "on", "drafts"]:
    raw = os.environ.get(GATE_ENV, "").strip().lower()
    if raw == "drafts":
        return "drafts"
    return "on" if raw in {"1", "on", "true", "yes"} else "off"


def gate_enabled() -> bool:
    mode = gate_mode()
    if mode == "drafts":
        return True
    return mode == "on" and not legal.any_draft()


def exempt(email: str, *, super_admin: bool) -> bool:
    synthetic = os.environ.get("FBI_SYNTHETIC_EMAIL", "").strip().lower()
    return super_admin or bool(synthetic and email.strip().lower() == synthetic)


_COLUMNS = "id, kind, granted, document, version, sha256, locale, statement, source, replaces_id, at"


def _rows(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...]) -> list[Consent]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [Consent(**r) for r in cur.fetchall()]


def latest(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Consent]:
    """The reader's current answer per purpose."""
    rows = _rows(conn, f"""
        SELECT DISTINCT ON (kind) {_COLUMNS} FROM customer.consents
        WHERE user_id = %s ORDER BY kind, at DESC, id DESC
    """, (user_id,))
    return {r.kind: r for r in rows}


def history(conn: psycopg.Connection[Any], user_id: int, *, limit: int = 200) -> list[Consent]:
    return _rows(conn, f"SELECT {_COLUMNS} FROM customer.consents WHERE user_id = %s "
                       "ORDER BY at DESC, id DESC LIMIT %s", (user_id, limit))


def due(conn: psycopg.Connection[Any], user_id: int) -> list[str]:
    return legal.due({k: (c.granted, c.version) for k, c in latest(conn, user_id).items()})


# A reader with nothing due, remembered for a few seconds per process, so the gate costs no query on every request
# of a busy page. A decision made in this process forgets the reader at once; one made in the other process takes at
# most CLEAR_TTL_S to reach this one.
CLEAR_TTL_S = 20.0
_clear: dict[int, tuple[float, tuple[str, ...]]] = {}
_clear_lock = threading.Lock()


def _signature() -> tuple[str, ...]:
    return tuple(sorted(f"{d}:{v}" for d in legal.DOCUMENTS for v in legal.valid_versions(d)))


def due_cached(conn: psycopg.Connection[Any], user_id: int) -> list[str]:
    now = time.monotonic()
    sig = _signature()
    with _clear_lock:
        hit = _clear.get(user_id)
        if hit is not None and hit[0] > now and hit[1] == sig:
            return []
    owed = due(conn, user_id)
    with _clear_lock:
        if owed:
            _clear.pop(user_id, None)
        else:
            if len(_clear) > 10_000:
                _clear.clear()
            _clear[user_id] = (now + CLEAR_TTL_S, sig)
    return owed


def forget(user_id: int) -> None:
    with _clear_lock:
        _clear.pop(user_id, None)


def record(user_id: int, decisions: Sequence[Decision], *, locale: legal.Locale, source: Source) -> list[Consent]:
    """Writes the reader's decisions, each with the version, the sha256 and the sentence of the text shown, and
    returns their whole history. A decision equal to the current answer on the same text adds nothing."""
    if not decisions:
        raise CustomerError(422, "no_decision", "nothing to record")
    if len({d.kind for d in decisions}) != len(decisions):
        raise CustomerError(422, "duplicate_decision", "one decision per purpose")
    for d in decisions:
        purpose = legal.BY_KIND.get(d.kind)
        if purpose is None:
            raise CustomerError(422, "unknown_purpose", f"no purpose {d.kind!r}")
        if not d.granted and not purpose.withdrawable:
            raise CustomerError(422, "not_withdrawable", f"{d.kind} ends with the account, not with a withdrawal")
        if d.version != legal.current(purpose.document).version:
            raise CustomerError(409, "legal_text_changed", f"{purpose.document} has a newer version")
    forget(user_id)
    with write_connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_KEY, user_id))
        before = latest(conn, user_id)
        for d in decisions:
            doc, sentence = legal.statement(d.kind, locale)
            prev = before.get(d.kind)
            if prev is not None and prev.granted == d.granted and prev.version == doc.version and (
                    prev.sha256 == doc.sha256):
                continue
            conn.execute("""
                INSERT INTO customer.consents (user_id, kind, granted, document, version, sha256, locale, statement,
                                               source, replaces_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, d.kind, d.granted, doc.document, doc.version, doc.sha256, locale, sentence, source,
                  prev.id if prev is not None else None))
        rows = history(conn, user_id)
    forget(user_id)
    return rows
