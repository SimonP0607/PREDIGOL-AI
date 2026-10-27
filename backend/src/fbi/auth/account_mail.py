"""The e-mails of an account (plan UX, A7): its one-use links, and what it is told about its security - a sign-in from
a device it has not used before, a change of its credentials (plan UX, section 33).

Each is a row of the queue (``fbi.messaging.outbox``), written in the caller's transaction, so the e-mail exists only
if what it tells happened. Nothing is queued while FBI_SELF_SERVICE is off - except a new sign-in's notice on the
reader's devices (plan UX, B7: ``fbi.customer.push``), which needs only push. A sign-in notice names the browser
family and the system from a closed list - never the IP, never the user agent (plan UX, section 19).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import psycopg

from fbi.auth import tokens
from fbi.customer import push
from fbi.messaging import outbox

Change = Literal["password", "password_reset", "password_admin", "mfa_on", "mfa_off", "mfa_reset", "recovery_codes"]
LINK_TEMPLATES: dict[str, str] = {"invite": "invitation", "reset": "password_reset", "unlock": "account_unlock"}
KNOWN_DEVICE_DAYS = 90
"""A device seen in a completed sign-in within this long is known (sessions are kept 90 days after they end)."""


def enqueue_link(conn: psycopg.Connection[Any], user_id: int, purpose: str, grant: int) -> int | None:
    """The e-mail of a link (fbi.auth.tokens.issue): the queue keeps only the number of the token's row."""
    template = LINK_TEMPLATES[purpose]
    return outbox.enqueue(conn, user_id=user_id, template=template, params={"grant": str(grant)},
                          dedup_key=f"{template}:{grant}")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _robot(email: str) -> bool:
    """The synthetic journey's account signs in every 15 minutes: it is never told anything."""
    synthetic = os.environ.get("FBI_SYNTHETIC_EMAIL", "").strip().lower()
    return bool(synthetic and email.strip().lower() == synthetic)


def device_family(user_agent: str | None) -> tuple[str, str]:
    """The browser family and the system of a user agent, from the closed lists of the sign-in notice
    (fbi.messaging.templates.BROWSERS and SYSTEMS): what a person recognises, nothing that identifies a device."""
    ua = user_agent or ""
    if "Android" in ua:
        system = "android"
    elif any(k in ua for k in ("iPhone", "iPad", "iPod")):
        system = "ios"
    elif "Windows" in ua:
        system = "windows"
    elif "CrOS" in ua:
        system = "chromeos"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        system = "macos"
    elif "Linux" in ua:
        system = "linux"
    else:
        system = "other"
    if "SamsungBrowser" in ua:
        browser = "samsung"
    elif any(k in ua for k in ("Edg/", "EdgA/", "EdgiOS/")):
        browser = "edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "opera"
    elif "Firefox/" in ua or "FxiOS/" in ua:
        browser = "firefox"
    elif "CriOS/" in ua or "Chrome/" in ua:
        browser = "chrome"
    elif "Safari/" in ua and "Version/" in ua:
        browser = "safari"
    else:
        browser = "other"
    return browser, system


def notify_new_device(conn: psycopg.Connection[Any], user: dict[str, Any], *, session_id: str,
                      user_agent: str | None) -> bool:
    """A completed sign-in from a browser and system the account has not signed in with in 90 days: the account is
    told (``new_sign_in``) by e-mail while FBI_SELF_SERVICE is on, and on its devices when it receives notices (plan
    UX, B7). Not its first sign-in ever (that one is the account's own activation or first visit), not the synthetic
    journey's account. True when a notice was queued."""
    email = tokens.self_service_enabled()
    if not (email or push.available()) or _robot(str(user["email"])):
        return False
    family = device_family(user_agent)
    rows = conn.execute("""
        SELECT user_agent FROM auth.sessions
         WHERE user_id = %s AND id <> %s AND stage = 'full'
           AND created_at > now() - make_interval(days => %s)
    """, (user["id"], session_id, KNOWN_DEVICE_DAYS)).fetchall()
    if not rows or any(device_family(r[0]) == family for r in rows):
        return False
    browser, system = family
    queued = False
    if email:
        outbox.enqueue(conn, user_id=int(user["id"]), template="new_sign_in",
                       params={"browser": browser, "system": system, "when": _now_iso()},
                       dedup_key=f"new_sign_in:{session_id[:24]}")
        queued = True
    if push.sign_in_notice(conn, user_id=int(user["id"]), language=user.get("language"), zone=user.get("timezone"),
                           browser=browser, system=system, session_id=session_id, at=datetime.now(UTC)):
        queued = True
    return queued


def notify_change(conn: psycopg.Connection[Any], user: dict[str, Any], change: Change) -> bool:
    """A change of the account's credentials it is told about (``security_change``). True when one was queued."""
    if not tokens.self_service_enabled() or _robot(str(user["email"])):
        return False
    outbox.enqueue(conn, user_id=int(user["id"]), template="security_change",
                   params={"change": change, "when": _now_iso()},
                   dedup_key=f"security_change:{user['id']}:{change}:{uuid.uuid4().hex[:12]}")
    return True
