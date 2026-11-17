"""Rights and moderation of the news (IA-102, plan piece AD-G05): ``moderation-v1``.

PUBLICATION BY SOURCE. What of an article may ever be shown is its source's ``publish_level`` (the copy written when it was seen and the
policy in force, the stricter: ``fbi.news.readers.effective_publish``): ``summary`` (PrediGol's own text, attributed, with the link),
``link`` (outlet, date and URL only) or ``none`` (nothing - the item is left out of every public projection). Without a permission the
strictest row decides (``fbi.ai.source_policy``). No picture of a third party, ever: a story shows a monogram or a graphic of its own.

THE PRIVATE QUEUE. A story goes to ``en_moderacion`` (a new version; hidden from every public projection; seen only in the owner's console,
``require_admin``) when a RULE says a person must look at it first (``RULES``):

* ``texto_lesion`` - it has an own text and it is about an injury (a health datum is sensitive: Ley 1581 de 2012, art. 5);
* ``salud_rechazado`` - a text was refused for a medical detail or a time off (the facts carry one: a person checks what may be said);
* ``derechos_retirados`` - it has an own text and no source of it may publish a summary any more.

WITHDRAWAL AT A REQUEST, WITH A REGISTER. The owner records who asked (a kind, never a person's contact) and why, and withdraws the story:
a new version ``retirada`` (only the owner withdraws: a CHECK of 0146) and a row of ``news.moderation_log``. Putting it back is another
version and another row; approving a story of the queue too. Nothing is deleted, ever - the register and every version stay.

A new version is the newest one copied with only its status changed, under the same advisory lock as ``fbi.news.store`` (the key space
``NEWS`` and the story's key), so a moderation act and a pass of the pipeline never write the same version twice. Plain SQL: this package
imports nothing of ``fbi.ai`` or ``fbi.news``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "moderation-v1"
LOCK_SPACE: Final = 0x4E455753
"""The key space of ``fbi.news.store``'s advisory locks (``NEWS``): the same lock for the same story."""
RULES: Final[dict[str, str]] = {
    "texto_lesion": "texto propio de una lesión: revisar que diga solo el estado, la fuente y la fecha",
    "salud_rechazado": "un texto se rechazó por un detalle médico o un plazo: revisar qué puede decirse",
    "derechos_retirados": "tiene texto propio y ninguna de sus fuentes permite ya publicar un resumen",
}
Requester = Literal["sistema", "titular_derechos", "persona_mencionada", "club", "medio", "dueno", "otro"]
REQUESTERS: Final = ("sistema", "titular_derechos", "persona_mencionada", "club", "medio", "dueno", "otro")
Action = Literal["flag", "request", "withdraw", "restore", "approve", "dismiss"]
STORY_COLUMNS: Final = ("first_seen_at", "event_at", "valid_until", "claim_type", "category", "level", "lang", "country", "headline_es",
                        "headline_en", "summary_es", "summary_en", "text_version")
"""What a moderation act copies unchanged from the newest version (0146): everything but the status, its reason and who decided."""


class ModerationError(ValueError):
    """An act the state of the story does not allow (withdrawing what is withdrawn, approving what is not in the queue ...)."""


@dataclass(frozen=True, slots=True)
class Current:
    id: int
    story_key: str
    version: int
    status: str


NEWEST_SQL: Final = "SELECT id, story_key, version, status FROM news.stories WHERE story_key = %s ORDER BY version DESC LIMIT 1"
NEW_VERSION_SQL: Final = f"""
INSERT INTO news.stories (story_key, version, previous_id, at, {", ".join(STORY_COLUMNS)}, status, status_reason, decided_by, written_by)
SELECT story_key, version + 1, id, %(at)s, {", ".join(STORY_COLUMNS)}, %(status)s, %(reason)s, %(decided_by)s, %(written_by)s
  FROM news.stories WHERE id = %(id)s
RETURNING id
"""
INSERT_LOG: Final = ("INSERT INTO news.moderation_log (story_key, story_id, at, action, rule, reason, requested_by, reference, decided_by, "
                     "actor_user_id, written_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id")


def current(conn: psycopg.Connection[Any], story_key: str) -> Current | None:
    with conn.cursor() as cur:
        cur.execute(NEWEST_SQL, (story_key,))
        row = cur.fetchone()
    return None if row is None else Current(int(row[0]), str(row[1]), int(row[2]), str(row[3]))


def _lock(conn: psycopg.Connection[Any], story_key: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (LOCK_SPACE, story_key))


def _new_version(conn: psycopg.Connection[Any], base: Current, *, at: datetime, status: str, reason: str | None, decided_by: str,
                 written_by: str) -> int:
    with conn.cursor() as cur:
        cur.execute(NEW_VERSION_SQL, {"at": at, "status": status, "reason": reason, "decided_by": decided_by, "written_by": written_by,
                                      "id": base.id})
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _log(conn: psycopg.Connection[Any], *, story_key: str, story_id: int | None, at: datetime, action: Action, reason: str,
         requested_by: str, decided_by: str, written_by: str, rule: str | None = None, reference: str | None = None,
         actor_user_id: int | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(INSERT_LOG, (story_key, story_id, at, action, rule, " ".join(reason.split())[:500], requested_by,
                                 None if not (reference or "").strip() else " ".join(str(reference).split())[:200], decided_by,
                                 actor_user_id, written_by))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def flag(conn: psycopg.Connection[Any], story_key: str, rule: str, *, at: datetime, detail: str | None = None) -> bool:
    """Send a story to the private queue by a rule. False (nothing written) when it is already in the queue or withdrawn."""
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}")
    reason = (RULES[rule] + (f" ({detail})" if detail else ""))[:500]
    with conn.transaction():
        _lock(conn, story_key)
        base = current(conn, story_key)
        if base is None or base.status != "activa":
            return False
        new_id = _new_version(conn, base, at=at, status="en_moderacion", reason=reason, decided_by="system", written_by=VERSION)
        _log(conn, story_key=story_key, story_id=new_id, at=at, action="flag", rule=rule, reason=reason, requested_by="sistema",
             decided_by="system", written_by=VERSION)
    return True


def _owner_act(conn: psycopg.Connection[Any], story_key: str, *, action: Action, status: str, allowed: Sequence[str], at: datetime,
               reason: str, requested_by: str, reference: str | None, actor_user_id: int | None, written_by: str) -> int:
    if requested_by not in REQUESTERS or requested_by == "sistema":
        raise ModerationError(f"unknown requester {requested_by!r}")
    clean = " ".join((reason or "").split())
    if len(clean) < 3:
        raise ModerationError("a reason is required")
    with conn.transaction():
        _lock(conn, story_key)
        base = current(conn, story_key)
        if base is None:
            raise ModerationError("no_such_story")
        if base.status not in allowed:
            raise ModerationError(f"{action} is not possible from {base.status}")
        story_id = base.id
        if status != base.status:
            story_id = _new_version(conn, base, at=at, status=status, reason=None if status == "activa" else clean[:500],
                                    decided_by="owner", written_by=written_by)
        return _log(conn, story_key=story_key, story_id=story_id, at=at, action=action, reason=clean, requested_by=requested_by,
                    decided_by="owner", reference=reference, actor_user_id=actor_user_id, written_by=written_by)


def request(conn: psycopg.Connection[Any], story_key: str, *, at: datetime, reason: str, requested_by: Requester,
            reference: str | None = None, actor_user_id: int | None = None, written_by: str = "console") -> int:
    """Record a request of withdrawal (who asked and why) and put the story in the queue at once: hidden until the owner decides."""
    return _owner_act(conn, story_key, action="request", status="en_moderacion", allowed=("activa", "en_moderacion"), at=at,
                      reason=reason, requested_by=requested_by, reference=reference, actor_user_id=actor_user_id, written_by=written_by)


def withdraw(conn: psycopg.Connection[Any], story_key: str, *, at: datetime, reason: str, requested_by: Requester,
             reference: str | None = None, actor_user_id: int | None = None, written_by: str = "console") -> int:
    """The owner withdraws a story (a new version ``retirada``) and the register says why and at whose request."""
    return _owner_act(conn, story_key, action="withdraw", status="retirada", allowed=("activa", "en_moderacion"), at=at, reason=reason,
                      requested_by=requested_by, reference=reference, actor_user_id=actor_user_id, written_by=written_by)


def restore(conn: psycopg.Connection[Any], story_key: str, *, at: datetime, reason: str, actor_user_id: int | None = None,
            written_by: str = "console") -> int:
    """Put a withdrawn story back (a new version ``activa``): the withdrawal stays in the register."""
    return _owner_act(conn, story_key, action="restore", status="activa", allowed=("retirada",), at=at, reason=reason,
                      requested_by="dueno", reference=None, actor_user_id=actor_user_id, written_by=written_by)


def approve(conn: psycopg.Connection[Any], story_key: str, *, at: datetime, reason: str, actor_user_id: int | None = None,
            written_by: str = "console") -> int:
    """Take a story out of the queue as it is (a new version ``activa``)."""
    return _owner_act(conn, story_key, action="approve", status="activa", allowed=("en_moderacion",), at=at, reason=reason,
                      requested_by="dueno", reference=None, actor_user_id=actor_user_id, written_by=written_by)


def dismiss(conn: psycopg.Connection[Any], story_key: str, *, at: datetime, reason: str, requested_by: Requester,
            reference: str | None = None, actor_user_id: int | None = None, written_by: str = "console") -> int:
    """The owner turns down a request of withdrawal: recorded, and the story comes out of the queue (a new version ``activa``)."""
    return _owner_act(conn, story_key, action="dismiss", status="activa", allowed=("en_moderacion",), at=at, reason=reason,
                      requested_by=requested_by, reference=reference, actor_user_id=actor_user_id, written_by=written_by)


# ── reading (private) ───────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Act:
    id: int
    story_key: str
    story_id: int | None
    at: datetime
    action: str
    rule: str | None
    reason: str
    requested_by: str
    reference: str | None
    decided_by: str
    actor_user_id: int | None


QUEUE_SQL: Final = """
SELECT s.* FROM (
    SELECT DISTINCT ON (story_key) story_key, id, version, at, status, status_reason, claim_type, category, level, lang, country,
           headline_es, summary_es
      FROM news.stories
     WHERE story_key IN (SELECT story_key FROM news.stories WHERE status = ANY(%(statuses)s) AND at >= %(since)s)
     ORDER BY story_key, version DESC
) s
 WHERE s.status = ANY(%(statuses)s)
 ORDER BY s.at DESC, s.id DESC
 LIMIT %(limit)s
"""
LOG_SQL: Final = ("SELECT id, story_key, story_id, at, action, rule, reason, requested_by, reference, decided_by, actor_user_id "
                  "FROM news.moderation_log WHERE story_key = ANY(%(keys)s) ORDER BY id DESC LIMIT %(limit)s")
STORY_SQL: Final = ("SELECT story_key, id, version, at, status, status_reason, claim_type, category, level, lang, country, headline_es, "
                    "summary_es FROM news.stories WHERE story_key = %s ORDER BY version DESC LIMIT 1")
ITEMS_SQL: Final = """
WITH linked AS (
    SELECT DISTINCT ON (s.item_id) s.item_id, s.story_key, s.active FROM news.item_story s
     WHERE s.item_id IN (SELECT item_id FROM news.item_story WHERE story_key = %(key)s)
     ORDER BY s.item_id, s.id DESC
)
SELECT DISTINCT ON (i.url_sha256) i.id, i.canonical_url, i.source_name, i.source_domain, i.source_state, i.publish_level, i.ai_reserved,
       i.published_at, i.seen_at
  FROM linked l JOIN news.items i ON i.id = l.item_id
 WHERE l.story_key = %(key)s AND l.active
 ORDER BY i.url_sha256, i.version DESC
 LIMIT 100
"""
"""The articles of a story for the owner: outlet, link, dates and what was copied of the policy - never the outlet's title."""
TEXTS_SQL: Final = ("SELECT at, outcome, problems, metrics, cost_usd FROM news.story_texts WHERE story_key = %(key)s "
                    "ORDER BY id DESC LIMIT 20")


def queue(conn: psycopg.Connection[Any], *, since: datetime, statuses: Sequence[str] = ("en_moderacion",),
          limit: int = 100) -> list[dict[str, Any]]:
    """The stories whose newest version is in one of ``statuses`` (the queue by default; ``retirada`` for the withdrawn), newest first,
    each with its register. Private: the console only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(QUEUE_SQL, {"statuses": list(statuses), "since": since, "limit": max(1, min(int(limit), 200))})
        rows = cur.fetchall()
    acts = log_of(conn, [str(r["story_key"]) for r in rows])
    for r in rows:
        r["log"] = [a for a in acts if a.story_key == r["story_key"]]
    return rows


def story_for_owner(conn: psycopg.Connection[Any], story_key: str) -> dict[str, Any] | None:
    """One story as the owner sees it: its newest version, its articles, its attempts of own text and its register."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STORY_SQL, (story_key,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(ITEMS_SQL, {"key": story_key})
        row["items"] = sorted(cur.fetchall(), key=lambda r: (r["published_at"] or r["seen_at"], r["id"]), reverse=True)
        cur.execute(TEXTS_SQL, {"key": story_key})
        row["texts"] = cur.fetchall()
    row["log"] = log_of(conn, [story_key])
    return row


def log_of(conn: psycopg.Connection[Any], story_keys: Sequence[str], *, limit: int = 500) -> list[Act]:
    if not story_keys:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LOG_SQL, {"keys": list(story_keys), "limit": limit})
        return [Act(**r) for r in cur.fetchall()]


__all__ = ["REQUESTERS", "RULES", "VERSION", "Act", "Current", "ModerationError", "approve", "current", "dismiss", "flag", "log_of", "queue",
           "request", "restore", "story_for_owner", "withdraw"]
