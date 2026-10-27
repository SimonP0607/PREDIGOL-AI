"""The messenger's notices on devices (plan UX, B7; section 34): the jobs that write them and ``dispatch``, which sends them.

    pick_result_alerts  a saved pick or parlay settled in the last day: «Ganado: tu pick de Local-Visitante»
    lineup_alerts       both line-ups of a match of a team the reader follows, in the three hours before it starts
    match_reminders     the bell the reader rang: «Empieza en 30 minutos», at that minute (quiet hours or not)
    digest              once a day, from 09:00 in the reader's zone: the matches of their teams and leagues today
    membership          the cover ends within a day (the e-mails of A8 go on: the important never depends on push only)
    dispatch            every tick: what is due, to every live device of its reader, with the rules of
                        ``fbi.customer.push`` - quiet hours, the daily ceiling, the categories switched off - and the push
                        services' answers (404 or 410: the device is gone)

A job writes only for readers with a live device and the category on, and each notice once (``dedup_key``). Nothing
here reads PrediGol Intelligence: what the reader saved, what they follow, the match's public facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final, Literal

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.customer import membership
from fbi.customer import push as rules
from fbi.messaging import push as protocol
from fbi.messaging import push_texts as texts

log = structlog.get_logger("messaging.push")

RESULT_WINDOW: Final = timedelta(days=1)
LINEUP_AHEAD: Final = timedelta(hours=3)
REMINDER_LEAD: Final = timedelta(minutes=10)
"""A reminder is queued up to this long before its minute; the dispatch (every tick) sends it at the minute."""
DIGEST_FROM: Final = time(9, 0)
DIGEST_UNTIL: Final = time(12, 0)
DIGEST_EXPIRES: Final = time(20, 0)
MAX_FAILURES: Final = 20
RETRY_IN: Final = timedelta(minutes=5)
BATCH: Final = 50
TIMEOUT_S: Final = 10.0

LIVE_DEVICE = ("EXISTS (SELECT 1 FROM customer.push_subscriptions s WHERE s.user_id = {u} AND s.revoked_at IS NULL)")
CATEGORY_ON = ("NOT EXISTS (SELECT 1 FROM customer.preferences p WHERE p.user_id = {u} AND %(category)s = ANY(p.push_off))")


def _for(u: str) -> str:
    return f"{LIVE_DEVICE.format(u=u)} AND {CATEGORY_ON.format(u=u)}"


@dataclass
class JobsReport:
    results: int = 0
    lineups: int = 0
    reminders: int = 0
    digests: int = 0
    membership: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.results + self.lineups + self.reminders + self.digests + self.membership


RESULTS_SQL = f"""
SELECT u.id, u.user_id, u.status, u.settled_at, th.name AS home, ta.name AS away, u.fixture_id, a.language, a.timezone
  FROM picks.user_picks u
  JOIN auth.users a ON a.id = u.user_id AND a.status = 'active'
  JOIN core.fixtures f ON f.id = u.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE u.status <> 'PENDING' AND u.settled_at > %(since)s AND u.settled_at <= %(at)s AND {_for('u.user_id')}
   AND NOT EXISTS (SELECT 1 FROM customer.push_notices n WHERE n.user_id = u.user_id AND n.dedup_key = 'result:pick:' || u.id)
 ORDER BY u.settled_at, u.id
 LIMIT 500
"""

PARLAYS_SQL = f"""
SELECT p.id, p.user_id, p.status, p.settled_at, p.name, a.language, a.timezone
  FROM picks.user_parlays p
  JOIN auth.users a ON a.id = p.user_id AND a.status = 'active'
 WHERE p.status IN ('WON', 'LOST', 'VOID', 'PARTIAL_VOID') AND p.settled_at > %(since)s AND p.settled_at <= %(at)s
   AND {_for('p.user_id')}
   AND NOT EXISTS (SELECT 1 FROM customer.push_notices n WHERE n.user_id = p.user_id AND n.dedup_key = 'result:parlay:' || p.id)
 ORDER BY p.settled_at, p.id
 LIMIT 500
"""


def pick_result_alerts(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    done = 0
    params = {"since": at - RESULT_WINDOW, "at": at, "category": "result"}
    with conn.cursor(row_factory=dict_row) as cur:
        picks = cur.execute(RESULTS_SQL, params).fetchall()
        parlays = cur.execute(PARLAYS_SQL, params).fetchall()
    for r in picks:
        w = texts.pick_result(str(r["status"]), r["home"], r["away"], texts.locale_of(r["language"]))
        if rules.queue(conn, user_id=int(r["user_id"]), category="result", key=f"result:pick:{r['id']}", title=w.title,
                       body=w.body, url=f"/matches/{r['fixture_id']}#postmatch", at=at,
                       expires_at=r["settled_at"] + RESULT_WINDOW, zone=r["timezone"]):
            done += 1
    for r in parlays:
        w = texts.parlay_result(str(r["status"]), r["name"], texts.locale_of(r["language"]))
        if rules.queue(conn, user_id=int(r["user_id"]), category="result", key=f"result:parlay:{r['id']}", title=w.title,
                       body=w.body, url="/my-picks", at=at, expires_at=r["settled_at"] + RESULT_WINDOW, zone=r["timezone"]):
            done += 1
    return done


LINEUPS_SQL = f"""
SELECT DISTINCT v.user_id, f.id AS fixture_id, f.kickoff_at, th.name AS home, ta.name AS away, a.language, a.timezone
  FROM customer.favorites v
  JOIN core.fixtures f ON f.home_team_id = v.team_id OR f.away_team_id = v.team_id
  JOIN auth.users a ON a.id = v.user_id AND a.status = 'active'
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE v.kind = 'team' AND f.status_group = 'scheduled' AND f.kickoff_at > %(at)s AND f.kickoff_at <= %(until)s
   AND (SELECT count(DISTINCT l.team_side) FROM core.fixture_lineups l WHERE l.fixture_id = f.id) = 2
   AND {_for('v.user_id')}
   AND NOT EXISTS (SELECT 1 FROM customer.push_notices n WHERE n.user_id = v.user_id AND n.dedup_key = 'lineup:' || f.id)
 LIMIT 2000
"""


def lineup_alerts(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    done = 0
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(LINEUPS_SQL, {"at": at, "until": at + LINEUP_AHEAD, "category": "lineup"}).fetchall()
    for r in rows:
        w = texts.lineups(r["home"], r["away"], r["kickoff_at"], r["timezone"], texts.locale_of(r["language"]))
        if rules.queue(conn, user_id=int(r["user_id"]), category="lineup", key=f"lineup:{r['fixture_id']}", title=w.title,
                       body=w.body, url=f"/matches/{r['fixture_id']}#lineups", at=at, expires_at=r["kickoff_at"],
                       zone=r["timezone"]):
            done += 1
    return done


REMINDERS_SQL = f"""
SELECT m.user_id, m.fixture_id, m.minutes_before, f.kickoff_at, th.name AS home, ta.name AS away, a.language, a.timezone
  FROM customer.match_alerts m
  JOIN core.fixtures f ON f.id = m.fixture_id
  JOIN auth.users a ON a.id = m.user_id AND a.status = 'active'
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.status_group = 'scheduled' AND f.kickoff_at > %(at)s
   AND f.kickoff_at - make_interval(mins => m.minutes_before) <= %(lead)s
   AND {LIVE_DEVICE.format(u='m.user_id')}
   AND NOT EXISTS (SELECT 1 FROM customer.push_notices n WHERE n.user_id = m.user_id
                    AND n.dedup_key = 'reminder:' || m.fixture_id || ':' || m.minutes_before)
"""


def match_reminders(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    done = 0
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(REMINDERS_SQL, {"at": at, "lead": at + REMINDER_LEAD}).fetchall()
    for r in rows:
        minutes = int(r["minutes_before"])
        w = texts.reminder(minutes, r["home"], r["away"], texts.locale_of(r["language"]))
        if rules.queue(conn, user_id=int(r["user_id"]), category="reminder", key=f"reminder:{r['fixture_id']}:{minutes}",
                       title=w.title, body=w.body, url=f"/matches/{r['fixture_id']}", at=at, expires_at=r["kickoff_at"],
                       zone=r["timezone"], not_before=r["kickoff_at"] - timedelta(minutes=minutes)):
            done += 1
    return done


DIGEST_READERS_SQL = f"""
SELECT a.id AS user_id, a.language, a.timezone FROM auth.users a
 WHERE a.status = 'active' AND {_for('a.id')}
   AND EXISTS (SELECT 1 FROM customer.favorites v WHERE v.user_id = a.id)
"""

DIGEST_MATCHES_SQL = """
SELECT f.id, f.kickoff_at, th.name AS home, ta.name AS away
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND f.kickoff_at > %(at)s AND f.status_group = 'scheduled'
   AND (EXISTS (SELECT 1 FROM customer.favorites v WHERE v.user_id = %(u)s AND v.kind = 'team'
                 AND v.team_id IN (f.home_team_id, f.away_team_id))
        OR EXISTS (SELECT 1 FROM customer.favorites v WHERE v.user_id = %(u)s AND v.kind = 'league'
                    AND v.league_id = cs.competition_id))
 ORDER BY f.kickoff_at, f.id
 LIMIT 50
"""


def digest(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """The day's summary: from 09:00 to 12:00 in the reader's zone, once a day, when their teams or leagues play."""
    done = 0
    with conn.cursor(row_factory=dict_row) as cur:
        readers = cur.execute(DIGEST_READERS_SQL, {"category": "digest"}).fetchall()
    for r in readers:
        zone = r["timezone"]
        local = at.astimezone(rules.zone_of(zone))
        if not DIGEST_FROM <= local.time() < DIGEST_UNTIL:
            continue
        day = local.date()
        key = f"digest:{day.isoformat()}"
        seen = conn.execute("SELECT 1 FROM customer.push_notices WHERE user_id = %s AND dedup_key = %s",
                            (r["user_id"], key)).fetchone()
        if seen:
            continue
        start, end = rules.day_bounds(day, zone)
        with conn.cursor(row_factory=dict_row) as cur:
            matches = cur.execute(DIGEST_MATCHES_SQL, {"start": start, "end": end, "at": at, "u": r["user_id"]}).fetchall()
        if not matches:
            continue
        first = matches[0]
        w = texts.digest(first["home"], first["away"], len(matches) - 1, texts.locale_of(r["language"]))
        expires = datetime.combine(day, DIGEST_EXPIRES, tzinfo=rules.zone_of(zone)).astimezone(UTC)
        if rules.queue(conn, user_id=int(r["user_id"]), category="digest", key=key, title=w.title, body=w.body,
                       url="/home", at=at, expires_at=expires, zone=zone):
            done += 1
    return done


MEMBERSHIP_SQL = f"""
SELECT a.id, a.email, a.role, a.language, a.timezone FROM auth.users a
 WHERE a.status = 'active' AND {_for('a.id')}
   AND (SELECT max(ends_at) FROM customer.membership_periods p WHERE p.user_id = a.id) > %(at)s
   AND (SELECT max(ends_at) FROM customer.membership_periods p WHERE p.user_id = a.id) <= %(until)s
"""


def membership_tomorrow(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """The cover ends within a day: one notice per period (the e-mails of A8 go on regardless)."""
    with conn.cursor(row_factory=dict_row) as cur:
        users = cur.execute(MEMBERSHIP_SQL, {"at": at, "until": at + timedelta(days=1), "category": "account"}).fetchall()
    if not users:
        return 0
    by_id = {int(u["id"]): u for u in users}
    done = 0
    for user_id, m in membership.of_many(conn, users, at).items():
        if m.period_id is None or m.ends_at is None or m.state in ("suspended", "exempt", "none"):
            continue
        u = by_id[user_id]
        w = texts.membership_tomorrow(texts.locale_of(u["language"]))
        if rules.queue(conn, user_id=user_id, category="account", key=f"account:membership:{m.period_id}",
                       title=w.title, body=w.body, url="/profile#membership", at=at, expires_at=m.ends_at,
                       zone=u["timezone"]):
            done += 1
    return done


JOBS = (("results", pick_result_alerts), ("lineups", lineup_alerts), ("reminders", match_reminders),
        ("digests", digest), ("membership", membership_tomorrow))


def collect(conn: psycopg.Connection[Any], *, at: datetime) -> JobsReport:
    """Every job once (the start of a messenger cycle). Each one's failure is recorded and the others go on; nothing is
    written while push is not available."""
    report = JobsReport()
    if not rules.available():
        return report
    for name, job in JOBS:
        try:
            setattr(report, name, job(conn, at=at))
            conn.commit()
        except Exception as exc:  # one job's failure stops neither the others nor the cycle
            conn.rollback()
            report.errors.append(f"push_{name}: {type(exc).__name__}"[:200])
            log.error("push.job_failed", job=name, error=type(exc).__name__)
    return report


# ── dispatch ──────────────────────────────────────────────────────────────────────────

Outcome = Literal["sent", "gone", "too_large", "later", "refused"]
"""The push service's answer: 201 sent; 404 or 410 the subscription is gone (revoked, never tried again); 413 too large;
429 and 5xx try later; anything else refused."""


@dataclass(frozen=True)
class Delivery:
    outcome: Outcome
    status: int
    retry_after: int | None = None


def send(client: httpx.Client, *, endpoint: str, device_key: str, auth_secret: str, payload: dict[str, Any],
         vapid: protocol.Vapid, ttl: int, urgency: Literal["low", "normal", "high"] = "normal",
         topic: str | None = None) -> Delivery:
    """One notice to one device. Never raises for an answer of the push service: the outcome says what to do."""
    if not protocol.allowed_endpoint(endpoint):
        return Delivery("refused", 0)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    try:
        body = protocol.encrypt(data, device_key, auth_secret)
    except protocol.PushError:
        return Delivery("too_large" if len(data) > protocol.MAX_PAYLOAD else "refused", 0)
    headers = {"TTL": str(max(0, ttl)), "Urgency": urgency, "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "Authorization": protocol.vapid_authorization(endpoint, vapid)}
    if topic:
        headers["Topic"] = topic[:32]
    try:
        r = client.post(endpoint, content=body, headers=headers)
    except httpx.HTTPError:
        return Delivery("later", 0)
    if r.status_code in (200, 201, 202):
        return Delivery("sent", r.status_code)
    if r.status_code in (404, 410):
        return Delivery("gone", r.status_code)
    if r.status_code == 413:
        return Delivery("too_large", r.status_code)
    if r.status_code == 429 or r.status_code >= 500:
        raw = r.headers.get("retry-after", "")
        return Delivery("later", r.status_code, int(raw) if raw.isdigit() else None)
    return Delivery("refused", r.status_code)



@dataclass
class DispatchReport:
    sent: int = 0
    devices: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    later: int = 0
    gone: int = 0

    def drop(self, why: str) -> None:
        self.dropped[why] = self.dropped.get(why, 0) + 1


DUE_SQL = """
SELECT n.id, n.user_id, n.category, n.dedup_key, n.title, n.body, n.url, n.expires_at, a.timezone,
       COALESCE((SELECT p.push_off FROM customer.preferences p WHERE p.user_id = n.user_id), '{}') AS push_off
  FROM customer.push_notices n JOIN auth.users a ON a.id = n.user_id
 WHERE n.status = 'queued' AND n.not_before <= %s
 ORDER BY n.not_before, n.id
 LIMIT %s
 FOR UPDATE OF n SKIP LOCKED
"""


def _sent_today(conn: psycopg.Connection[Any], user_id: int, zone: str | None, at: datetime) -> int:
    start, end = rules.day_bounds(rules.local_day(at, zone), zone)
    row = conn.execute("SELECT count(*) FROM customer.push_notices WHERE user_id = %s AND status = 'sent' "
                       "AND category = ANY(%s) AND sent_at >= %s AND sent_at < %s",
                       (user_id, list(rules.CAPPED), start, end)).fetchone()
    return int(row[0]) if row else 0


def _drop(conn: psycopg.Connection[Any], notice_id: int, why: str) -> None:
    conn.execute("UPDATE customer.push_notices SET status = 'dropped', dropped = %s WHERE id = %s", (why, notice_id))


def dispatch(conn: psycopg.Connection[Any], *, at: datetime, client: httpx.Client | None = None,
             vapid: protocol.Vapid | None = None, limit: int = BATCH) -> DispatchReport:
    """What is due, notice by notice (each committed on its own). Nothing while push is not available."""
    report = DispatchReport()
    if not rules.available():
        return report
    key = vapid or protocol.vapid_from_env()
    if key is None:
        return report
    with conn.cursor(row_factory=dict_row) as cur:
        due = cur.execute(DUE_SQL, (at, limit)).fetchall()
    if not due:
        conn.commit()  # nothing locked is kept: the next tick looks again
        return report
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT_S, follow_redirects=False)
    try:
        for n in due:
            _one(conn, http, key, n, at, report)
            conn.commit()
    finally:
        if own:
            http.close()
    return report


def _one(conn: psycopg.Connection[Any], http: httpx.Client, vapid: protocol.Vapid, n: dict[str, Any], at: datetime,
         report: DispatchReport) -> None:
    category, zone = str(n["category"]), n["timezone"]
    if at >= n["expires_at"]:
        _drop(conn, n["id"], "expired")
        report.drop("expired")
        return
    if category in rules.CATEGORIES and category in (n["push_off"] or ()):
        _drop(conn, n["id"], "category_off")
        report.drop("category_off")
        return
    if category not in ("reminder", "test"):
        wait = rules.quiet_until(at, zone)
        if wait is not None:
            if wait >= n["expires_at"]:
                _drop(conn, n["id"], "expired")
                report.drop("expired")
            else:
                conn.execute("UPDATE customer.push_notices SET not_before = %s WHERE id = %s", (wait, n["id"]))
            return
    if category in rules.CAPPED and _sent_today(conn, int(n["user_id"]), zone, at) >= rules.DAILY_CAP:
        _drop(conn, n["id"], "daily_cap")
        report.drop("daily_cap")
        return
    with conn.cursor(row_factory=dict_row) as cur:
        devices = cur.execute("SELECT id, endpoint, p256dh, auth FROM customer.push_subscriptions "
                              "WHERE user_id = %s AND revoked_at IS NULL ORDER BY id", (n["user_id"],)).fetchall()
    if not devices:
        _drop(conn, n["id"], "no_device")
        report.drop("no_device")
        return
    payload = {"title": n["title"], "body": n["body"], "url": n["url"], "tag": n["dedup_key"], "category": category}
    ttl = int(max(60, min((n["expires_at"] - at).total_seconds(), 86_400)))
    urgency: Literal["low", "normal", "high"] = "high" if category in ("reminder", "account", "test") else "normal"
    sent = later = 0
    for d in devices:
        result = send(http, endpoint=d["endpoint"], device_key=d["p256dh"], auth_secret=d["auth"],
                      payload=payload, vapid=vapid, ttl=ttl, urgency=urgency)
        if result.outcome == "sent":
            sent += 1
            conn.execute("UPDATE customer.push_subscriptions SET last_ok_at = %s, failures = 0 WHERE id = %s", (at, d["id"]))
        elif result.outcome == "gone":
            report.gone += 1
            conn.execute("UPDATE customer.push_subscriptions SET revoked_at = %s, revoked_reason = 'gone' "
                         "WHERE id = %s AND revoked_at IS NULL", (at, d["id"]))
        else:
            # A failure more; the twentieth in a row revokes the device ('failing') - and a device revoked now is not
            # one to try again in five minutes.
            row = conn.execute("""
                UPDATE customer.push_subscriptions SET failures = failures + 1,
                       revoked_at = CASE WHEN failures + 1 >= %s THEN %s END,
                       revoked_reason = CASE WHEN failures + 1 >= %s THEN 'failing' END
                 WHERE id = %s AND revoked_at IS NULL
             RETURNING revoked_at IS NULL
            """, (MAX_FAILURES, at, MAX_FAILURES, d["id"])).fetchone()
            if result.outcome == "later" and row is not None and row[0]:
                later += 1
    if sent:
        conn.execute("UPDATE customer.push_notices SET status = 'sent', sent_at = %s, devices = %s WHERE id = %s",
                     (at, sent, n["id"]))
        report.sent += 1
        report.devices += sent
    elif later and at + RETRY_IN < n["expires_at"]:
        conn.execute("UPDATE customer.push_notices SET not_before = %s WHERE id = %s", (at + RETRY_IN, n["id"]))
        report.later += 1
    else:
        _drop(conn, n["id"], "failed")
        report.drop("failed")
