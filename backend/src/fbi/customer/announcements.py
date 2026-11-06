"""The owner's communiqués to readers (closing plan 4.3).

Four closed kinds - ``maintenance``, ``incident``, ``update`` and ``general`` (there is no «promotion») - written by the
owner in both languages and sent to the places he chooses: the banner of the app between two dates, the entries of
Novedades (only an update), the Telegram channel when one is configured, and an e-mail only if the communiqué is critical
(a maintenance or an incident). Everything works without Telegram.

A communiqué is a draft until the owner publishes it, and publishing takes two steps: the preview (which shows exactly
what each destination will say, how many e-mails would be queued, and gives a code that lives ten minutes) and the
publication (that code and the typed word ``PUBLICAR``). A day holds at most ``FBI_ANNOUNCE_DAILY_CAP`` publications
(three by default). A published communiqué is retracted, never deleted, and every step is a line of an append-only record.
It is the owner's words: nothing here is computed from the models, the picks or a reader's data.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.customer.db import CustomerError

log = structlog.get_logger(__name__)

Kind = Literal["maintenance", "incident", "update", "general"]
KINDS: Final = ("maintenance", "incident", "update", "general")
CRITICAL_KINDS: Final = ("maintenance", "incident")
PHRASE: Final = "PUBLICAR"
"""The word the owner types to publish: a second, deliberate step after the preview."""
CONFIRM_TTL: Final = timedelta(minutes=10)
DEFAULT_DAILY_CAP: Final = 3
MAX_DAYS: Final = 90
"""A communiqué is shown for at most this long."""
EMAIL_TEXT_MAX: Final = 200
"""An e-mail's template keeps short strings (fbi.messaging.templates.MAX_PARAM): the text of a critical communiqué."""
EMAIL_BATCH: Final = 5000

COLUMNS: Final = ("id, kind, title_es, title_en, body_es, body_en, starts_at, ends_at, to_banner, to_updates, to_telegram, "
                  "to_email, critical, status, created_by, created_at, published_by, published_at, retracted_by, "
                  "retracted_at, confirm_expires_at")


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("FBI_ANNOUNCE_DAILY_CAP", str(DEFAULT_DAILY_CAP))))
    except ValueError:
        return DEFAULT_DAILY_CAP


@dataclass(frozen=True, slots=True)
class Content:
    kind: str
    title_es: str
    title_en: str
    body_es: str
    body_en: str
    starts_at: datetime
    ends_at: datetime
    to_banner: bool = True
    to_updates: bool = False
    to_telegram: bool = False
    to_email: bool = False
    critical: bool = False


def _bad(code: str, message: str) -> CustomerError:
    return CustomerError(422, code, message)


def validate(c: Content, *, at: datetime | None = None) -> Content:
    """The rules of the plan, as the database also holds them; the answer says which one is broken."""
    if c.kind not in KINDS:
        raise _bad("bad_kind", "the kind is maintenance, incident, update or general")
    for name, value, low, high in (("title_es", c.title_es, 3, 80), ("title_en", c.title_en, 3, 80),
                                   ("body_es", c.body_es, 3, 600), ("body_en", c.body_en, 3, 600)):
        text = value.strip()
        if not low <= len(text) <= high:
            raise _bad("bad_text", f"{name}: between {low} and {high} characters")
        if "<" in text or ">" in text or any(ord(ch) < 32 and ch not in "\n" for ch in text):
            raise _bad("bad_text", f"{name}: plain text only")
    if c.ends_at <= c.starts_at:
        raise _bad("bad_dates", "it ends after it starts")
    if c.ends_at - c.starts_at > timedelta(days=MAX_DAYS):
        raise _bad("bad_dates", f"it is shown for at most {MAX_DAYS} days")
    if not (c.to_banner or c.to_updates or c.to_telegram or c.to_email):
        raise _bad("no_destination", "choose at least one destination")
    if c.to_updates and c.kind != "update":
        raise _bad("updates_only_updates", "only an update goes to Novedades")
    if c.critical and c.kind not in CRITICAL_KINDS:
        raise _bad("critical_kind", "only a maintenance or an incident can be critical")
    if c.to_email and not c.critical:
        raise _bad("email_critical_only", "an e-mail goes only if the communiqué is critical")
    if c.to_email and max(len(c.title_es.strip()), len(c.title_en.strip())) > EMAIL_TEXT_MAX:
        raise _bad("email_too_long", f"for an e-mail, titles of at most {EMAIL_TEXT_MAX} characters")
    if c.to_email and any(len(t.strip()) > EMAIL_TEXT_MAX for t in (c.body_es, c.body_en)):
        raise _bad("email_too_long", f"for an e-mail, the text is at most {EMAIL_TEXT_MAX} characters")
    return c


def _log(conn: psycopg.Connection[Any], announcement_id: int, action: str, actor: int | None,
         detail: Mapping[str, Any] | None = None) -> None:
    conn.execute("INSERT INTO customer.announcement_log (announcement_id, action, actor_user_id, detail) "
                 "VALUES (%s, %s, %s, %s)", (announcement_id, action, actor, Json(dict(detail or {}))))


def _row(conn: psycopg.Connection[Any], announcement_id: int, *, lock: bool = False) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(f"SELECT {COLUMNS}, confirm_hash FROM customer.announcements WHERE id = %s"
                          + (" FOR UPDATE" if lock else ""), (announcement_id,)).fetchone()
    if row is None:
        raise CustomerError(404, "not_found", "no such communiqué")
    return row


def create(conn: psycopg.Connection[Any], actor: int, content: Content) -> int:
    c = validate(content)
    row = conn.execute("""
        INSERT INTO customer.announcements (kind, title_es, title_en, body_es, body_en, starts_at, ends_at,
                                            to_banner, to_updates, to_telegram, to_email, critical, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (c.kind, c.title_es.strip(), c.title_en.strip(), c.body_es.strip(), c.body_en.strip(), c.starts_at, c.ends_at,
          c.to_banner, c.to_updates, c.to_telegram, c.to_email, c.critical, actor)).fetchone()
    assert row is not None
    _log(conn, int(row[0]), "created", actor, {"kind": c.kind})
    return int(row[0])


def edit(conn: psycopg.Connection[Any], actor: int, announcement_id: int, content: Content) -> None:
    """Only a draft is edited; a published communiqué is retracted and written again. Editing voids a code asked for."""
    current = _row(conn, announcement_id, lock=True)
    if current["status"] != "draft":
        raise CustomerError(409, "not_a_draft", "only a draft is edited")
    c = validate(content)
    conn.execute("""
        UPDATE customer.announcements SET kind = %s, title_es = %s, title_en = %s, body_es = %s, body_en = %s,
               starts_at = %s, ends_at = %s, to_banner = %s, to_updates = %s, to_telegram = %s, to_email = %s,
               critical = %s, confirm_hash = NULL, confirm_expires_at = NULL
         WHERE id = %s
    """, (c.kind, c.title_es.strip(), c.title_en.strip(), c.body_es.strip(), c.body_en.strip(), c.starts_at, c.ends_at,
          c.to_banner, c.to_updates, c.to_telegram, c.to_email, c.critical, announcement_id))
    _log(conn, announcement_id, "edited", actor)


def get(conn: psycopg.Connection[Any], announcement_id: int) -> dict[str, Any]:
    row = _row(conn, announcement_id)
    row.pop("confirm_hash", None)
    return row


def listing(conn: psycopg.Connection[Any], *, limit: int = 100) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"SELECT {COLUMNS} FROM customer.announcements ORDER BY id DESC LIMIT %s",
                           (limit,)).fetchall()


def log_of(conn: psycopg.Connection[Any], announcement_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("SELECT action, actor_user_id, detail, at FROM customer.announcement_log "
                           "WHERE announcement_id = %s ORDER BY id", (announcement_id,)).fetchall()


# ── what each destination will say ────────────────────────────────────────────────────────────

def telegram_text(row: Mapping[str, Any]) -> tuple[str, str]:
    """The channel's post: Spanish first, then English, the owner's words as he wrote them."""
    title = f"{row['title_es']} / {row['title_en']}"
    return title, f"{row['body_es']}\n\n{row['body_en']}"


def readers_for_email(conn: psycopg.Connection[Any]) -> list[int]:
    """Every active reader whose address works: a critical communiqué reaches them whatever they chose for optional mail
    (an address that bounced or complained gets nothing)."""
    rows = conn.execute("""
        SELECT u.id FROM auth.users u LEFT JOIN customer.preferences p ON p.user_id = u.id
         WHERE u.role = 'USER' AND u.status = 'active' AND COALESCE(p.email_status, 'ok') = 'ok'
         ORDER BY u.id LIMIT %s
    """, (EMAIL_BATCH,)).fetchall()
    return [int(r[0]) for r in rows]


def email_params(row: Mapping[str, Any]) -> dict[str, str]:
    return {"title_es": row["title_es"], "title_en": row["title_en"], "body_es": row["body_es"], "body_en": row["body_en"]}


def preview(conn: psycopg.Connection[Any], announcement_id: int) -> dict[str, Any]:
    """What publishing would do, destination by destination: nothing is sent or changed."""
    row = _row(conn, announcement_id)
    destinations: dict[str, Any] = {}
    if row["to_banner"]:
        destinations["banner"] = {"from": row["starts_at"], "until": row["ends_at"],
                                  "es": {"title": row["title_es"], "body": row["body_es"]},
                                  "en": {"title": row["title_en"], "body": row["body_en"]}}
    if row["to_updates"]:
        destinations["updates"] = {"es": row["title_es"], "en": row["title_en"]}
    if row["to_telegram"]:
        title, body = telegram_text(row)
        destinations["telegram"] = {"title": title, "body": body, "configured": telegram_configured()}
    if row["to_email"]:
        destinations["email"] = {"recipients": len(readers_for_email(conn)), "critical": True,
                                 "es": row["title_es"], "en": row["title_en"]}
    return {"id": announcement_id, "kind": row["kind"], "status": row["status"], "destinations": destinations,
            "published_today": published_today(conn), "daily_cap": daily_cap()}


def telegram_configured() -> bool:
    return bool(os.environ.get("FBI_TELEGRAM_BOT_TOKEN") and os.environ.get("FBI_TELEGRAM_CHANNEL_ID"))


def published_today(conn: psycopg.Connection[Any], at: datetime | None = None) -> int:
    day = (at or datetime.now(UTC)).astimezone(UTC).date()
    row = conn.execute("SELECT count(*) FROM customer.announcements WHERE (published_at AT TIME ZONE 'UTC')::date = %s",
                       (day,)).fetchone()
    return int(row[0]) if row else 0


# ── the double confirmation ───────────────────────────────────────────────────────────────────

def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def ask_to_publish(conn: psycopg.Connection[Any], actor: int, announcement_id: int, *,
                   at: datetime | None = None) -> tuple[str, datetime, dict[str, Any]]:
    """Step 1: the preview and the code that step 2 needs (ten minutes). A new code voids the previous one."""
    now = at or datetime.now(UTC)
    row = _row(conn, announcement_id, lock=True)
    if row["status"] != "draft":
        raise CustomerError(409, "not_a_draft", "only a draft is published")
    if row["ends_at"] <= now:
        raise _bad("already_over", "its end has passed")
    code = secrets.token_urlsafe(12)
    expires = now + CONFIRM_TTL
    conn.execute("UPDATE customer.announcements SET confirm_hash = %s, confirm_expires_at = %s WHERE id = %s",
                 (_hash(code), expires, announcement_id))
    shown = preview(conn, announcement_id)
    _log(conn, announcement_id, "previewed", actor)
    return code, expires, shown


@dataclass(frozen=True, slots=True)
class Published:
    id: int
    emails_queued: int
    telegram: bool
    """Whether the Telegram post is still to be made (the caller makes it after the commit and records its fate)."""


def publish(conn: psycopg.Connection[Any], actor: int, announcement_id: int, *, code: str, phrase: str,
            at: datetime | None = None) -> Published:
    """Step 2: the code of the preview and the typed word. The daily cap is checked here, in the same transaction."""
    now = at or datetime.now(UTC)
    row = _row(conn, announcement_id, lock=True)
    if row["status"] != "draft":
        raise CustomerError(409, "not_a_draft", "only a draft is published")
    if phrase.strip() != PHRASE:
        raise CustomerError(422, "bad_phrase", f"type {PHRASE} to confirm")
    stored, expires = row.get("confirm_hash"), row.get("confirm_expires_at")
    if not stored or expires is None or expires <= now:
        raise CustomerError(409, "confirmation_expired", "ask for the preview again: its code lasts ten minutes")
    if not hmac.compare_digest(str(stored), _hash(code.strip())):
        raise CustomerError(403, "bad_code", "that is not the code of this preview")
    if row["ends_at"] <= now:
        raise _bad("already_over", "its end has passed")
    if published_today(conn, now) >= daily_cap():
        raise CustomerError(429, "daily_cap", f"at most {daily_cap()} communiqués a day")
    conn.execute("UPDATE customer.announcements SET status = 'published', published_by = %s, published_at = %s, "
                 "confirm_hash = NULL, confirm_expires_at = NULL WHERE id = %s", (actor, now, announcement_id))
    queued = 0
    if row["to_email"]:
        queued = _queue_emails(conn, announcement_id, row)
    _log(conn, announcement_id, "published", actor, {"banner": row["to_banner"], "updates": row["to_updates"],
                                                    "telegram": row["to_telegram"], "email": row["to_email"]})
    if queued:
        _log(conn, announcement_id, "emails", actor, {"queued": queued})
    log.info("announcement.published", id=announcement_id, kind=row["kind"], emails=queued)
    return Published(id=announcement_id, emails_queued=queued, telegram=bool(row["to_telegram"]))


def _queue_emails(conn: psycopg.Connection[Any], announcement_id: int, row: Mapping[str, Any]) -> int:
    from fbi.messaging import outbox

    params = email_params(row)
    queued = 0
    for user_id in readers_for_email(conn):
        if outbox.enqueue(conn, user_id=user_id, template="critical_notice", params=params,
                          dedup_key=f"announcement:{announcement_id}:{user_id}") is not None:
            queued += 1
    return queued


def post_to_channel(row: Mapping[str, Any], *, transport: httpx.BaseTransport | None = None) -> tuple[bool, str | None]:
    """Post to the Telegram channel; (sent, reason). Never raises: a channel that fails is a line in the record, not a
    failed publication (the banner, Novedades and e-mail do not depend on it)."""
    from fbi.notify.service import ChannelError, TelegramChannel

    token, channel = os.environ.get("FBI_TELEGRAM_BOT_TOKEN"), os.environ.get("FBI_TELEGRAM_CHANNEL_ID")
    if not token or not channel:
        return False, "not_configured"
    chan = TelegramChannel(token, channel, transport=transport)
    try:
        title, body = telegram_text(row)
        chan.send(title, body)
        return True, None
    except ChannelError as exc:
        return False, str(exc)[:120]
    finally:
        chan.close()


def record_telegram(conn: psycopg.Connection[Any], announcement_id: int, actor: int | None, *, sent: bool,
                    reason: str | None = None) -> None:
    _log(conn, announcement_id, "telegram", actor, {"sent": sent, **({"reason": reason} if reason else {})})


def retract(conn: psycopg.Connection[Any], actor: int, announcement_id: int, *, at: datetime | None = None) -> None:
    """Hide a published communiqué again (the banner and the entry go; the record stays)."""
    now = at or datetime.now(UTC)
    row = _row(conn, announcement_id, lock=True)
    if row["status"] != "published":
        raise CustomerError(409, "not_published", "only a published communiqué is retracted")
    conn.execute("UPDATE customer.announcements SET status = 'retracted', retracted_by = %s, retracted_at = %s "
                 "WHERE id = %s", (actor, now, announcement_id))
    _log(conn, announcement_id, "retracted", actor)


# ── what readers see ──────────────────────────────────────────────────────────────────────────

def active_banners(conn: psycopg.Connection[Any], at: datetime | None = None) -> list[dict[str, Any]]:
    """The banners to show now: published, to the banner, between their dates; the most urgent kinds first."""
    now = at or datetime.now(UTC)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("""
            SELECT id, kind, title_es, title_en, body_es, body_en, starts_at, ends_at, critical
              FROM customer.announcements
             WHERE status = 'published' AND to_banner AND starts_at <= %s AND ends_at > %s
             ORDER BY array_position(ARRAY['incident', 'maintenance', 'update', 'general'], kind), id DESC
             LIMIT 3
        """, (now, now)).fetchall()


def published_updates(conn: psycopg.Connection[Any], at: datetime | None = None) -> list[dict[str, Any]]:
    """The entries of Novedades that the owner wrote in the console (newest first): published updates, once they start."""
    now = at or datetime.now(UTC)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("""
            SELECT id, title_es, title_en, body_es, body_en, published_at, starts_at
              FROM customer.announcements
             WHERE status = 'published' AND to_updates AND starts_at <= %s
             ORDER BY starts_at DESC, id DESC LIMIT 50
        """, (now,)).fetchall()


# ── the bot: a welcome and the links, no conversation ─────────────────────────────────────────

WELCOME = ("¡Hola! Este es el canal de avisos de PrediGol: aquí publicamos mantenimientos, incidencias y novedades.\n"
           "Hello! This is PrediGol's notices channel: maintenance, incidents and news.")


def bot_welcome(update: Mapping[str, Any]) -> tuple[str, str] | None:
    """(chat id, text) when the update is someone pressing /start in a private chat; None for anything else. The bot never
    answers a conversation, never stores what it is told and never asks for anything."""
    message = update.get("message")
    if not isinstance(message, Mapping):
        return None
    text, chat = message.get("text"), message.get("chat")
    if not isinstance(text, str) or not isinstance(chat, Mapping) or chat.get("type") != "private":
        return None
    if text.split("@", 1)[0].strip().split(" ", 1)[0] != "/start" or not isinstance(chat.get("id"), int):
        return None
    base = os.environ.get("FBI_WEB_BASE_URL", "").rstrip("/")
    links = f"\n\n{base}\n{base}/novedades" if base.startswith("https://") else ""
    return str(chat["id"]), WELCOME + links


def send_welcome(chat_id: str, text: str, *, transport: httpx.BaseTransport | None = None) -> bool:
    token = os.environ.get("FBI_TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    try:
        with httpx.Client(base_url="https://api.telegram.org", timeout=10.0, transport=transport) as http:
            return http.post(f"/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text,
                                                              "disable_web_page_preview": True}).status_code == 200
    except httpx.HTTPError:
        return False


def webhook_secret_ok(given: str) -> bool:
    expected = os.environ.get("FBI_TELEGRAM_WEBHOOK_SECRET", "")
    return len(expected) >= 24 and hmac.compare_digest(expected.encode(), given.encode())
