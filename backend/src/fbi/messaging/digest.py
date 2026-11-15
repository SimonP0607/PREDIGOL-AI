"""The weekly summary by e-mail (plan UX, B8; section 33): asked for apart, left in one click, by its own sender.

* **Only with consent.** A reader gets it only while their latest decision on ``marketing_email`` is a grant (an optional
  purpose of the processing policy, never ticked beforehand); leaving it - from the profile or in one click from any
  summary (fbi.messaging.unsubscribe) - takes effect at once: the queue checks the consent again when a summary leaves.
* **Its own flow.** Commercial e-mail leaves by ``FBI_DIGEST_FROM``, a sender on another domain than the account's
  (``FBI_EMAIL_FROM``): a summary marked as spam must not drag the security e-mails down. Without that sender nothing is
  queued and nothing queued leaves.
* **Spread over the week.** Each reader has a day (their account's number modulo 7, Monday first) and it leaves from 09:00
  in their time zone; at most ``FBI_DIGEST_DAILY_CAP`` (30) are queued a day, under the queue's own cap (90 a day: Resend
  Free allows 100), and commercial e-mail is the last of the queue's priorities.
* **Honest content.** How the reader's saved picks of the week ended (counts; units and rates need the sample of Mis
  picks), their teams' matches of the next seven days and the Novedades of the week by their titles. No odds, no promise,
  no urgency, no pixel.

``FBI_DIGEST`` is born off (plan UX, section 41) and needs ``FBI_EMAIL_SEND`` (A5, after P2 and P3): while any of the three
is missing the profile does not even offer the box (``offered``) and nothing is queued. ``FBI_DIGEST=0`` is the rollback:
nothing more is queued and nothing queued leaves.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.customer import updates
from fbi.messaging.outbox import enqueue, sending_enabled

log = structlog.get_logger(__name__)

ENV = "FBI_DIGEST"
FROM_ENV = "FBI_DIGEST_FROM"
CAP_ENV = "FBI_DIGEST_DAILY_CAP"
DEFAULT_CAP = 30
FROM_HOUR = 9
"""The summary leaves from 09:00 in the reader's time zone, on their day."""
WINDOW = timedelta(days=7)
TEMPLATE = "weekly_digest"
PURPOSE = "marketing_email"
MAX_NEWS = 3
ADDRESS = re.compile(r"<?([^<>@\s]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})>?\s*$")


def enabled() -> bool:
    """FBI_DIGEST, born off."""
    return os.environ.get(ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def _domain(address: str) -> str | None:
    m = ADDRESS.search(address.strip())
    return m.group(2).lower() if m else None


def sender() -> str | None:
    """The commercial sender, when it is one: an address on another domain than the account's sender."""
    commercial = os.environ.get(FROM_ENV, "").strip()
    domain = _domain(commercial)
    if domain is None:
        return None
    account = _domain(os.environ.get("FBI_EMAIL_FROM", ""))
    return commercial if domain != account else None


def offered() -> bool:
    """Whether the summary can really reach a reader now: the switch, the e-mail on (A5) and the commercial sender. The
    profile offers the box only then; a reader can always leave."""
    return enabled() and sending_enabled() and sender() is not None


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get(CAP_ENV, str(DEFAULT_CAP))))
    except ValueError:
        return DEFAULT_CAP


SUBSCRIBED_SQL = """
SELECT c.granted FROM customer.consents c
 WHERE c.user_id = %s AND c.kind = 'marketing_email'
 ORDER BY c.at DESC, c.id DESC LIMIT 1
"""


def subscribed(conn: psycopg.Connection[Any], user_id: int) -> bool:
    row = conn.execute(SUBSCRIBED_SQL, (user_id,)).fetchone()
    return bool(row and row[0])


def send_check(conn: psycopg.Connection[Any], user_id: int) -> str | None:
    """Why a queued summary must not leave now, or None: the switch off, no commercial sender, or the reader left."""
    if not enabled():
        return "the weekly summary is switched off (FBI_DIGEST)"
    if sender() is None:
        return "no commercial sender (FBI_DIGEST_FROM on its own domain)"
    if not subscribed(conn, user_id):
        return "the reader left the weekly summary (marketing_email withdrawn)"
    return None


# ── the weekly job ────────────────────────────────────────────────────────────────────

@dataclass
class DigestReport:
    queued: int = 0
    capped: bool = False
    off: str | None = None
    """Why nothing was queued: the switch, the e-mail or the sender."""


CANDIDATES_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (c.user_id) c.user_id, c.granted
      FROM customer.consents c
     WHERE c.kind = 'marketing_email'
     ORDER BY c.user_id, c.at DESC, c.id DESC)
SELECT u.id, u.timezone
  FROM latest l
  JOIN auth.users u ON u.id = l.user_id
  LEFT JOIN customer.preferences p ON p.user_id = u.id
 WHERE l.granted AND u.status = 'active' AND u.role <> 'SUPER_ADMIN' AND u.email <> %s
   AND coalesce(p.email_status, 'ok') = 'ok'
 ORDER BY u.id
"""
QUEUED_TODAY_SQL = "SELECT count(*) FROM customer.messages_outbox WHERE template = %s AND created_at >= %s"
EXISTS_SQL = "SELECT 1 FROM customer.messages_outbox WHERE dedup_key = %s"
PICKS_SQL = """
SELECT count(*) FILTER (WHERE status IN ('WIN', 'HALF_WIN')) AS won,
       count(*) FILTER (WHERE status IN ('LOSS', 'HALF_LOSS')) AS lost,
       count(*) FILTER (WHERE status IN ('PUSH', 'VOID')) AS void
  FROM picks.user_picks
 WHERE user_id = %s AND settled_at >= %s AND settled_at < %s
"""
TEAMS_SQL = "SELECT team_id FROM customer.favorites WHERE user_id = %s AND kind = 'team' AND notify"
MATCHES_SQL = """
SELECT count(*) FROM core.fixtures f
 WHERE f.status_group = 'scheduled' AND f.kickoff_at > %s AND f.kickoff_at <= %s
   AND (f.home_team_id = ANY(%s) OR f.away_team_id = ANY(%s))
"""


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def day_of(user_id: int) -> int:
    """The reader's day of the week (0 Monday ... 6 Sunday): the week's summaries spread over the seven days."""
    return user_id % 7


def due_now(user_id: int, zone: str | None, at: datetime) -> bool:
    local = at.astimezone(_zone(zone))
    return local.weekday() == day_of(user_id) and local.hour >= FROM_HOUR


def dedup_key(user_id: int, zone: str | None, at: datetime) -> str:
    """One summary per reader and ISO week of their time zone."""
    iso = at.astimezone(_zone(zone)).isocalendar()
    return f"weekly_digest:{user_id}:{iso.year}-W{iso.week:02d}"


def params_for(conn: psycopg.Connection[Any], user_id: int, zone: str | None, at: datetime) -> dict[str, str]:
    """The summary's counts, written into the queue (short strings: never a name, an address or an odd)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PICKS_SQL, (user_id, at - WINDOW, at))
        picks = cur.fetchone() or {"won": 0, "lost": 0, "void": 0}
    teams = [int(r[0]) for r in conn.execute(TEAMS_SQL, (user_id,)).fetchall()]
    matches = 0
    if teams:
        row = conn.execute(MATCHES_SQL, (at, at + WINDOW, teams, teams)).fetchone()
        matches = int(row[0]) if row else 0
    local_day = at.astimezone(_zone(zone)).date()
    news = [u.id for u in updates.between(local_day - timedelta(days=6), local_day)][:MAX_NEWS]
    return {"won": str(int(picks["won"])), "lost": str(int(picks["lost"])), "void": str(int(picks["void"])),
            "matches": str(matches), "follows": "yes" if teams else "no", "news": ",".join(news) or "-"}


def queue(conn: psycopg.Connection[Any], *, at: datetime) -> DigestReport:
    """The summaries owed now: each consenting reader once a week, on their day, from 09:00 in their zone, at most the
    day's cap. Commits each one."""
    report = DigestReport()
    if not enabled():
        report.off = "FBI_DIGEST off"
        return report
    if not sending_enabled():
        report.off = "FBI_EMAIL_SEND off"
        return report
    if sender() is None:
        report.off = "no commercial sender (FBI_DIGEST_FROM)"
        return report
    midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute(QUEUED_TODAY_SQL, (TEMPLATE, midnight)).fetchone()
    used = int(row[0]) if row else 0
    cap = daily_cap()
    synthetic = os.environ.get("FBI_SYNTHETIC_EMAIL", "").strip().lower() or "-"
    candidates = conn.execute(CANDIDATES_SQL, (synthetic,)).fetchall()
    conn.commit()
    for user_id, zone in candidates:
        if not due_now(int(user_id), zone, at):
            continue
        key = dedup_key(int(user_id), zone, at)
        if conn.execute(EXISTS_SQL, (key,)).fetchone() is not None:
            continue
        if used >= cap:
            report.capped = True
            log.info("digest.capped", cap=cap)
            break
        params = params_for(conn, int(user_id), zone, at)
        if enqueue(conn, user_id=int(user_id), template=TEMPLATE, params=params, dedup_key=key) is not None:
            report.queued += 1
            used += 1
        conn.commit()
    return report
