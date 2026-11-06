"""What a reader keeps of their notices on their devices, and the rules every notice obeys (plan UX, B7; section 34).

    devices      the browsers the reader allowed: subscribed with a known push service only (no request to an address a
                 client chose), listed, revoked by the reader; at most MAX_DEVICES live at once
    categories   the result of what they saved, their teams' line-ups, the day's summary and their account: on until the
                 reader switches one off. Reminders exist only when the reader rings a match's bell
    bells        «avísame N minutos antes» (15, 30 or 60) on a match that has not started and starts within 7 days; at
                 most MAX_ALERTS at once
    queue        ``queue`` writes a notice once per reader and key, with its quiet hours and its expiry; the messenger
                 sends it (``fbi.messaging.push_jobs.dispatch``)
    rules        quiet hours 22:00-08:00 in the reader's zone: what falls inside waits for 08:00 and is dropped if it is
                 no longer useful by then - a reminder the reader asked for goes anyway; at most DAILY_CAP a day of
                 results, line-ups and summaries; the account's notices and the reader's own test are not counted

Nothing is offered or sent unless FBI_PUSH is on (on while the line is absent: the owner approved the plan; =0 stops
everything without a deploy) AND the owner has set PrediGol's VAPID key (P12). Nothing of PrediGol Intelligence reads
any of this; the words of a notice come from what the reader saved or follows and the match's public facts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.core.env import environment
from fbi.customer.db import CustomerError, write_connection
from fbi.messaging import push as protocol
from fbi.messaging import push_texts as texts
from fbi.messaging.templates import BROWSERS as BROWSER_WORDS
from fbi.messaging.templates import SYSTEMS as SYSTEM_WORDS

log = structlog.get_logger("customer.push")

SWITCH: Final = "FBI_PUSH"
CATEGORIES: Final = ("result", "lineup", "digest", "account")
"""What a reader can switch off. ``reminder`` exists only when they ring a bell; ``test`` is their own."""
CAPPED: Final = ("result", "lineup", "digest")
DAILY_CAP: Final = 3
QUIET_START: Final = time(22, 0)
QUIET_END: Final = time(8, 0)
ALERT_MINUTES: Final = (15, 30, 60)
ALERT_AHEAD: Final = timedelta(days=7)
MAX_ALERTS: Final = 30
MAX_DEVICES: Final = 10
TESTS_PER_DAY: Final = 3
RETENTION: Final = timedelta(days=90)
"""Sent and dropped notices, then deleted (with the product events' retention switch, FBI_EVENTS_PURGE)."""
REVOKED_RETENTION: Final = timedelta(days=30)
FAMILIES: Final = ("chrome", "firefox", "safari", "edge", "other")
SYSTEMS: Final = ("android", "ios", "windows", "macos", "linux", "other")
_ON: Final = frozenset({"1", "on", "true", "yes"})

Category = Literal["result", "lineup", "digest", "reminder", "account", "test"]
PAGE: Final = re.compile(r"^/([A-Za-z0-9_?=&#.-][A-Za-z0-9/_?=&#.-]{0,198})?$")
"""The page of PrediGol a notice opens: a path, never another site (not even ``//host``) - customer.push_notices.url."""


def enabled() -> bool:
    """``FBI_PUSH``: on while absent or empty, off for =0 (or a value it cannot read)."""
    raw = environment().get(SWITCH)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in _ON


def available() -> bool:
    """Whether notices can be offered and sent: the switch on and PrediGol's VAPID key set (P12)."""
    if not enabled():
        return False
    try:
        return protocol.vapid_from_env() is not None
    except protocol.PushError:
        log.error("push.bad_vapid_key")
        return False


def zone_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "America/Bogota")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("America/Bogota")


def quiet_until(at: datetime, zone: str | None) -> datetime | None:
    """The end of the quiet hours ``at`` falls in (22:00-08:00 in the reader's zone), or None outside them."""
    tz = zone_of(zone)
    local = at.astimezone(tz)
    if local.time() >= QUIET_START:
        end = datetime.combine(local.date() + timedelta(days=1), QUIET_END, tzinfo=tz)
    elif local.time() < QUIET_END:
        end = datetime.combine(local.date(), QUIET_END, tzinfo=tz)
    else:
        return None
    return end.astimezone(UTC)


def local_day(at: datetime, zone: str | None) -> date:
    return at.astimezone(zone_of(zone)).date()


def day_bounds(day: date, zone: str | None) -> tuple[datetime, datetime]:
    tz = zone_of(zone)
    start = datetime.combine(day, time(0, 0), tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


# ── the queue ─────────────────────────────────────────────────────────────────────────

def queue(conn: psycopg.Connection[Any], *, user_id: int, category: Category, key: str, title: str, body: str,
          url: str, at: datetime, expires_at: datetime, zone: str | None, not_before: datetime | None = None) -> int | None:
    """One notice in the caller's transaction, once per reader and key: its id, or None when it was queued before or
    would arrive too late to be of use. Inside the quiet hours it waits for their end - not a reminder the reader asked
    for, not their own test."""
    if not PAGE.fullmatch(url):
        raise ValueError("a notice opens a page of PrediGol")
    start = max(not_before or at, at)
    if category not in ("reminder", "test"):
        start = quiet_until(start, zone) or start
    if start >= expires_at:
        return None
    row = conn.execute("""
        INSERT INTO customer.push_notices (user_id, category, dedup_key, title, body, url, created_at, not_before, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, dedup_key) DO NOTHING RETURNING id
    """, (user_id, category, key, title[:120], body[:300], url, at, start, expires_at)).fetchone()
    return int(row[0]) if row else None


def sign_in_notice(conn: psycopg.Connection[Any], *, user_id: int, language: str | None, zone: str | None,
                   browser: str, system: str, session_id: str, at: datetime) -> bool:
    """A sign-in from a browser and system the account had not used (``fbi.auth.account_mail``), on the reader's devices
    too when they receive notices and keep the account's category on - in the caller's transaction. The e-mail goes
    regardless: security never depends on push alone."""
    if not available():
        return False
    live = conn.execute("SELECT 1 FROM customer.push_subscriptions WHERE user_id = %s AND revoked_at IS NULL LIMIT 1",
                        (user_id,)).fetchone()
    if live is None or "account" in push_off(conn, user_id):
        return False
    locale = texts.locale_of(language)
    words_b = BROWSER_WORDS.get(browser, BROWSER_WORDS["other"])
    words_s = SYSTEM_WORDS.get(system, SYSTEM_WORDS["other"])
    device = f"{words_b[locale]} en {words_s[locale]}" if locale == "es" else f"{words_b[locale]} on {words_s[locale]}"
    w = texts.new_sign_in(device, locale)
    return queue(conn, user_id=user_id, category="account", key=f"account:sign_in:{session_id[:24]}", title=w.title,
                 body=w.body, url="/profile#security", at=at, expires_at=at + timedelta(days=1), zone=zone) is not None


# ── what the reader keeps ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Device:
    id: int
    family: str
    system: str
    installed: bool
    created_at: datetime
    last_ok_at: datetime | None


@dataclass(frozen=True)
class State:
    available: bool
    public_key: str | None
    devices: list[Device]
    categories: dict[str, bool]


DEVICES_SQL = """
SELECT id, family, system, installed, created_at, last_ok_at FROM customer.push_subscriptions
 WHERE user_id = %s AND revoked_at IS NULL ORDER BY created_at DESC, id DESC
"""


def push_off(conn: psycopg.Connection[Any], user_id: int) -> frozenset[str]:
    row = conn.execute("SELECT push_off FROM customer.preferences WHERE user_id = %s", (user_id,)).fetchone()
    return frozenset(row[0] or ()) if row else frozenset()


def state(conn: psycopg.Connection[Any], user_id: int) -> State:
    """The reader's devices and categories, and whether push can be offered at all (with the key the browser subscribes
    with)."""
    on = available()
    vapid = protocol.vapid_from_env() if on else None
    with conn.cursor(row_factory=dict_row) as cur:
        devices = [Device(**r) for r in cur.execute(DEVICES_SQL, (user_id,)).fetchall()]
    off = push_off(conn, user_id)
    return State(available=on, public_key=vapid.public if vapid else None, devices=devices,
                 categories={c: c not in off for c in CATEGORIES})


def _off() -> CustomerError:
    return CustomerError(404, "push_off", "notices on devices are not available")


def subscribe(user_id: int, *, endpoint: str, device_key: str, auth_secret: str, family: str, system: str,
              installed: bool, at: datetime) -> Device:
    """A browser allowed by the reader. The same browser again keeps its row; a browser another account had (a shared
    device) is that account's no longer (``replaced``). 422 ``unknown_push_service`` for an address that is not a known
    push service, ``bad_key`` for keys that cannot encrypt; 404 ``push_off``."""
    if not available():
        raise _off()
    if not protocol.allowed_endpoint(endpoint):
        raise CustomerError(422, "unknown_push_service", "not the address of a known push service")
    try:
        protocol.public_key_from(device_key)
        if len(protocol.b64url_decode(auth_secret)) != 16:
            raise protocol.PushError("auth")
    except (protocol.PushError, ValueError) as exc:
        raise CustomerError(422, "bad_key", "the browser's keys cannot be used") from exc
    device_key, auth_secret = device_key.rstrip("="), auth_secret.rstrip("=")
    family = family if family in FAMILIES else "other"
    system = system if system in SYSTEMS else "other"
    with write_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('customer.push_subscriptions'), %s)", (user_id % 2**31,))
        live = cur.execute("SELECT id, user_id FROM customer.push_subscriptions WHERE endpoint = %s AND revoked_at IS NULL",
                           (endpoint,)).fetchone()
        if live and int(live["user_id"]) == user_id:
            cur.execute("UPDATE customer.push_subscriptions SET installed = installed OR %s, family = %s, system = %s "
                        "WHERE id = %s RETURNING id, family, system, installed, created_at, last_ok_at",
                        (installed, family, system, live["id"]))
            row = cur.fetchone()
            assert row is not None
            return Device(**row)
        if live:
            conn.execute("UPDATE customer.push_subscriptions SET revoked_at = %s, revoked_reason = 'replaced' WHERE id = %s",
                         (at, live["id"]))
        # past the ceiling, the oldest of the reader's own browsers gives way
        conn.execute("""
            UPDATE customer.push_subscriptions SET revoked_at = %s, revoked_reason = 'replaced'
             WHERE id IN (SELECT id FROM customer.push_subscriptions WHERE user_id = %s AND revoked_at IS NULL
                           ORDER BY created_at DESC, id DESC OFFSET %s)
        """, (at, user_id, MAX_DEVICES - 1))
        cur.execute("""
            INSERT INTO customer.push_subscriptions (user_id, endpoint, p256dh, auth, family, system, installed,
                                                     created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, family, system, installed, created_at, last_ok_at
        """, (user_id, endpoint, device_key, auth_secret, family, system, installed, at))
        row = cur.fetchone()
        assert row is not None
    log.info("push.subscribed", user_id=user_id, family=family, system=system, installed=installed)
    return Device(**row)


def unsubscribe(user_id: int, *, at: datetime, endpoint: str | None = None, device_id: int | None = None) -> bool:
    """A browser the reader stops (its address, from that browser; or its id, from the list of another). Only the
    reader's own; idempotent. True when one was live."""
    if endpoint is None and device_id is None:
        raise CustomerError(422, "no_device", "which device")
    with write_connection() as conn:
        n = conn.execute("""
            UPDATE customer.push_subscriptions SET revoked_at = %s, revoked_reason = 'unsubscribed'
             WHERE user_id = %s AND revoked_at IS NULL AND (endpoint = %s OR id = %s)
        """, (at, user_id, endpoint, device_id)).rowcount
    return n > 0


def set_categories(user_id: int, values: Mapping[str, bool]) -> dict[str, bool]:
    """Switch categories on or off (only those named). 422 ``unknown_category``."""
    unknown = sorted(set(values) - set(CATEGORIES))
    if unknown:
        raise CustomerError(422, "unknown_category", f"no category {unknown[0]!r}")
    with write_connection() as conn:
        off = set(push_off(conn, user_id))
        for category, on in values.items():
            (off.discard if on else off.add)(category)
        conn.execute("""
            INSERT INTO customer.preferences (user_id, push_off) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET push_off = EXCLUDED.push_off, updated_at = now()
        """, (user_id, sorted(off)))
    return {c: c not in off for c in CATEGORIES}


def send_test(user_id: int, *, title: str, body: str, at: datetime) -> int:
    """The reader's own test, now (no quiet hours, not counted): 409 ``no_device`` without a live device, 429
    ``too_many_tests`` past TESTS_PER_DAY in a day, 404 ``push_off``."""
    if not available():
        raise _off()
    with write_connection() as conn:
        live = conn.execute("SELECT count(*) FROM customer.push_subscriptions WHERE user_id = %s AND revoked_at IS NULL",
                            (user_id,)).fetchone()
        if not live or not int(live[0]):
            raise CustomerError(409, "no_device", "no device receives notices")
        tests = conn.execute("SELECT count(*) FROM customer.push_notices WHERE user_id = %s AND category = 'test' "
                             "AND created_at > %s", (user_id, at - timedelta(days=1))).fetchone()
        if tests and int(tests[0]) >= TESTS_PER_DAY:
            raise CustomerError(429, "too_many_tests", "enough tests for today")
        notice = queue(conn, user_id=user_id, category="test", key=f"test:{int(at.timestamp() * 1000)}", title=title,
                       body=body, url="/profile#notifications", at=at, expires_at=at + timedelta(minutes=10), zone=None)
    assert notice is not None
    return notice


# ── the bell of a match ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Alert:
    fixture_id: int
    on: bool
    minutes_before: int | None
    kickoff_at: datetime | None


def alert(conn: psycopg.Connection[Any], user_id: int, fixture_id: int) -> Alert:
    row = conn.execute("""
        SELECT f.kickoff_at, a.minutes_before FROM core.fixtures f
          LEFT JOIN customer.match_alerts a ON a.fixture_id = f.id AND a.user_id = %s
         WHERE f.id = %s
    """, (user_id, fixture_id)).fetchone()
    if row is None:
        raise CustomerError(404, "not_found", "no such match")
    return Alert(fixture_id=fixture_id, on=row[1] is not None, minutes_before=row[1], kickoff_at=row[0])


BELLS_SQL = """
SELECT a.fixture_id, f.kickoff_at, a.minutes_before FROM customer.match_alerts a
  JOIN core.fixtures f ON f.id = a.fixture_id
 WHERE a.user_id = %s AND f.kickoff_at > %s AND f.status_group = 'scheduled'
 ORDER BY f.kickoff_at, a.fixture_id
"""


def bells(conn: psycopg.Connection[Any], user_id: int, at: datetime) -> list[Alert]:
    """The bells the reader rang for matches still to be played, soonest first (Home's «Tus avisos»)."""
    return [Alert(fixture_id=int(r[0]), on=True, minutes_before=int(r[2]), kickoff_at=r[1])
            for r in conn.execute(BELLS_SQL, (user_id, at)).fetchall()]


def set_alert(user_id: int, fixture_id: int, *, minutes_before: int, at: datetime) -> Alert:
    """Ring a match's bell (or change its minutes). 404 ``not_found``; 422 ``bad_minutes``, ``match_started`` once it
    has started, ``too_far`` more than 7 days ahead, ``too_many_alerts`` past MAX_ALERTS bells to come; 404 ``push_off``."""
    if not available():
        raise _off()
    if minutes_before not in ALERT_MINUTES:
        raise CustomerError(422, "bad_minutes", f"{', '.join(map(str, ALERT_MINUTES))} minutes before")
    with write_connection() as conn:
        row = conn.execute("SELECT kickoff_at, status_group FROM core.fixtures WHERE id = %s", (fixture_id,)).fetchone()
        if row is None:
            raise CustomerError(404, "not_found", "no such match")
        kickoff, group = row
        if group != "scheduled" or kickoff <= at:
            raise CustomerError(422, "match_started", "the match has started")
        if kickoff - at > ALERT_AHEAD:
            raise CustomerError(422, "too_far", "a bell is rung within the 7 days before the match")
        n = conn.execute("""
            SELECT count(*) FROM customer.match_alerts a JOIN core.fixtures f ON f.id = a.fixture_id
             WHERE a.user_id = %s AND f.kickoff_at > %s AND a.fixture_id <> %s
        """, (user_id, at, fixture_id)).fetchone()
        if n and int(n[0]) >= MAX_ALERTS:
            raise CustomerError(422, "too_many_alerts", f"at most {MAX_ALERTS} bells at once")
        conn.execute("""
            INSERT INTO customer.match_alerts (user_id, fixture_id, minutes_before, created_at) VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, fixture_id) DO UPDATE SET minutes_before = EXCLUDED.minutes_before
        """, (user_id, fixture_id, minutes_before, at))
        # a reminder already queued for other minutes gives way to the new one
        conn.execute("DELETE FROM customer.push_notices WHERE user_id = %s AND category = 'reminder' AND status = 'queued' "
                     "AND dedup_key LIKE %s", (user_id, f"reminder:{fixture_id}:%"))
    return Alert(fixture_id=fixture_id, on=True, minutes_before=minutes_before, kickoff_at=kickoff)


def clear_alert(user_id: int, fixture_id: int) -> None:
    """The bell off (and its reminder, while it waits). Idempotent."""
    with write_connection() as conn:
        conn.execute("DELETE FROM customer.match_alerts WHERE user_id = %s AND fixture_id = %s", (user_id, fixture_id))
        conn.execute("DELETE FROM customer.push_notices WHERE user_id = %s AND category = 'reminder' AND status = 'queued' "
                     "AND dedup_key LIKE %s", (user_id, f"reminder:{fixture_id}:%"))


# ── the reader's own copy, the anonymised account, retention ──────────────────────────

def export_rows(conn: psycopg.Connection[Any], user_id: int) -> dict[str, list[dict[str, Any]]]:
    """The reader's devices (never the push service's address or the keys: they would let anyone send to that browser),
    their bells and their notices, for the copy of their data (A4)."""
    with conn.cursor(row_factory=dict_row) as cur:
        devices = cur.execute("""
            SELECT family, system, installed, created_at, last_ok_at, revoked_at, revoked_reason
              FROM customer.push_subscriptions WHERE user_id = %s ORDER BY created_at DESC, id DESC
        """, (user_id,)).fetchall()
        bells = cur.execute("SELECT fixture_id, minutes_before, created_at FROM customer.match_alerts WHERE user_id = %s "
                            "ORDER BY created_at DESC", (user_id,)).fetchall()
        notices = cur.execute("""
            SELECT category, title, body, url, created_at, status, sent_at, devices, dropped
              FROM customer.push_notices WHERE user_id = %s ORDER BY created_at DESC, id DESC
        """, (user_id,)).fetchall()
    return {"push_devices": list(devices), "match_alerts": list(bells), "push_notices": list(notices)}


def forget(conn: psycopg.Connection[Any], user_id: int) -> None:
    """The account anonymised (A7): its devices, bells and notices go."""
    conn.execute("DELETE FROM customer.push_notices WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM customer.match_alerts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM customer.push_subscriptions WHERE user_id = %s", (user_id,))


@dataclass(frozen=True)
class PurgeReport:
    mode: Literal["off", "dry", "on"]
    notices: int
    devices: int


def purge(conn: psycopg.Connection[Any], *, at: datetime, mode: Literal["off", "dry", "on"]) -> PurgeReport:
    """Notices sent or dropped more than 90 days ago and browsers revoked more than 30 days ago: counted (``dry``) or
    deleted (``on``), with the product events' retention switch (FBI_EVENTS_PURGE). The caller commits."""
    if mode == "off":
        return PurgeReport("off", 0, 0)
    notices_sql = "FROM customer.push_notices WHERE status <> 'queued' AND created_at < %s"
    devices_sql = "FROM customer.push_subscriptions WHERE revoked_at IS NOT NULL AND revoked_at < %s"
    if mode == "dry":
        n = conn.execute(f"SELECT count(*) {notices_sql}", (at - RETENTION,)).fetchone()
        d = conn.execute(f"SELECT count(*) {devices_sql}", (at - REVOKED_RETENTION,)).fetchone()
        return PurgeReport("dry", int(n[0]) if n else 0, int(d[0]) if d else 0)
    n_del = conn.execute(f"DELETE {notices_sql}", (at - RETENTION,)).rowcount
    d_del = conn.execute(f"DELETE {devices_sql}", (at - REVOKED_RETENTION,)).rowcount
    return PurgeReport("on", max(n_del, 0), max(d_del, 0))
