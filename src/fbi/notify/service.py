"""The notifier: events in the database -> deduplicated messages -> a channel.

Events are read, never pushed: a shadow pick created, a pick settled, the
first real odds capture, a failed capture, a silent worker, a thin quota. Each
becomes one audit.notifications row keyed by the event, so re-running is
free. Then queued rows go to the configured channel; with none configured
they are marked 'skipped' with the reason, which is what the web app shows.

Messages are informational. A shadow pick is announced as research output
with its reasons for not qualifying, never as a bet to place.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.core.clock import now

log = structlog.get_logger(__name__)

SEND_BATCH = 20
WEB_BASE = os.environ.get("FBI_WEB_BASE_URL", "http://localhost:5173")

# Every kind collect() drafts. audit.notifications.kind is CHECKed against this same list (revision 0067). The two
# run-watchdog kinds were drafted from 5 Oct 2026 05:45 UTC without it: the database refused them, and the refusal
# rolled back every other message of the run, every run, until 6 Oct 01:35 UTC - logged only as notify.failed.
KINDS = ("shadow_pick", "pick_settled", "first_capture", "capture_failed", "worker_down", "run_recovered",
         "job_failing", "ai_budget")


@dataclass(frozen=True, slots=True)
class Draft:
    kind: str
    dedup_key: str
    title: str
    body: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"notification kind {self.kind!r} is not in KINDS (and not in the database CHECK)")


class Channel(Protocol):
    name: str

    def send(self, title: str, body: str) -> None:
        """Deliver or raise ChannelError."""


class ChannelError(RuntimeError):
    """Delivery failed. The message says why without any credential in it."""


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._token = token
        self._chat_id = chat_id
        self._http = httpx.Client(base_url="https://api.telegram.org", timeout=15.0, transport=transport)

    def send(self, title: str, body: str) -> None:
        try:
            r = self._http.post(f"/bot{self._token}/sendMessage", json={
                "chat_id": self._chat_id, "text": f"{title}\n\n{body}"[:4000], "disable_web_page_preview": True})
        except httpx.HTTPError as exc:
            # The URL carries the token: report the error class only.
            raise ChannelError(f"telegram unreachable ({type(exc).__name__})") from None
        if r.status_code != 200:
            raise ChannelError(f"telegram answered HTTP {r.status_code}")

    def close(self) -> None:
        self._http.close()


def channel_from_env(transport: httpx.BaseTransport | None = None) -> TelegramChannel | None:
    token, chat = os.environ.get("FBI_TELEGRAM_BOT_TOKEN"), os.environ.get("FBI_TELEGRAM_CHAT_ID")
    if token and chat:
        return TelegramChannel(token, chat, transport=transport)
    return None


def _fmt_pct(x: Any) -> str:
    return f"{float(x) * 100:.1f}%" if x is not None else "—"


REPEATED_FAILURES_SQL = """
SELECT job_type, max(started_at) AS last_at, (array_agg(last_error ORDER BY started_at DESC))[1] AS last_error
  FROM (SELECT job_type, status, started_at, last_error,
               row_number() OVER (PARTITION BY job_type ORDER BY started_at DESC) AS rn
          FROM raw.ingestion_runs WHERE started_at > %s - interval '2 days' AND status <> 'running') x
 WHERE rn <= 3
 GROUP BY job_type HAVING count(*) = 3 AND bool_and(status = 'failed')
"""
"""A job whose last three runs all failed: one failure is noise, three in a row is a broken job."""


def collect(conn: psycopg.Connection, *, at: datetime) -> list[Draft]:
    drafts: list[Draft] = []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT p.id, th.name || ' v ' || ta.name AS fixture, f.kickoff_at, p.market_key, p.selection, p.line,
                   p.market_odds, b.name AS bookmaker, p.p_calibrated, p.p_market_fair, p.ev, p.status,
                   p.qualification, m.name AS model, pr.result_status, pr.profit_units, p.fixture_id
            FROM picks.picks p
            JOIN core.fixtures f ON f.id = p.fixture_id
            JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
            JOIN market.bookmakers b ON b.id = p.bookmaker_id
            JOIN models.model_versions v ON v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id
            LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
            WHERE p.created_at > %s - interval '7 days'
            """,
            (at,),
        )
        for p in cur.fetchall():
            sel = f"{p['market_key']} {p['selection']}" + (f" {p['line']}" if Decimal(p["line"]) != 0 else "")
            reasons = "; ".join((p["qualification"] or {}).get("reasons", [])) or "qualified"
            link = f"{WEB_BASE}/matches/{p['fixture_id']}"
            drafts.append(Draft(
                "shadow_pick", f"pick:{p['id']}:created", f"SHADOW pick #{p['id']} — research only, not a bet",
                f"{p['fixture']} ({p['kickoff_at']:%d %b %H:%M} UTC)\n{sel} at {p['market_odds']} ({p['bookmaker']})\n"
                f"{p['model']}: {_fmt_pct(p['p_calibrated'])} vs market {_fmt_pct(p['p_market_fair'])}; "
                f"EV {_fmt_pct(p['ev'])}\nNot qualified: {reasons}\n{link}",
                {"pick_id": p["id"]}))
            if p["status"] == "settled" and p["result_status"] not in (None, "pending"):
                drafts.append(Draft(
                    "pick_settled", f"pick:{p['id']}:settled", f"Shadow pick #{p['id']} settled: {p['result_status']}",
                    f"{p['fixture']} · {sel} at {p['market_odds']}\nResult on the 90-minute score: "
                    f"{p['result_status']} ({p['profit_units']} u, hypothetical)\n{link}", {"pick_id": p["id"]}))
        cur.execute("SELECT min(captured_at) AS first, count(*) AS n FROM market.odds_snapshots")
        first = cur.fetchone()
        if first and first["n"]:
            drafts.append(Draft("first_capture", "first_capture", "First real odds captured",
                                f"{first['n']} price(s) stored; the first at {first['first']:%d %b %H:%M} UTC. "
                                f"Lineage: raw payload -> hash -> snapshot.\n{WEB_BASE}/odds", {}))
        cur.execute("SELECT id, started_at, last_error FROM raw.ingestion_runs WHERE job_type = 'odds_capture' "
                    "AND status = 'failed' AND started_at > %s - interval '2 days'", (at,))
        for r in cur.fetchall():
            drafts.append(Draft("capture_failed", f"run:{r['id']}:failed", f"Odds capture run {r['id']} failed",
                                f"At {r['started_at']:%d %b %H:%M} UTC: {(r['last_error'] or '')[:300]}", {}))
        cur.execute("SELECT id, job_type, status, last_error, finished_at FROM raw.ingestion_runs "
                    "WHERE status IN ('interrupted', 'stale') AND finished_at > %s - interval '2 days' "
                    "AND last_error LIKE '%%run watchdog%%'", (at,))
        for r in cur.fetchall():
            drafts.append(Draft("run_recovered", f"run:{r['id']}:{r['status']}",
                                f"Run {r['id']} ({r['job_type']}) closed as {r['status']} by the run watchdog",
                                (r["last_error"] or "")[-400:], {"run_id": r["id"]}))
        cur.execute(REPEATED_FAILURES_SQL, (at,))
        for r in cur.fetchall():
            drafts.append(Draft("job_failing", f"job_failing:{r['job_type']}:{r['last_at']:%Y%m%d%H}",
                                f"{r['job_type']}: the last 3 runs failed",
                                f"Last at {r['last_at']:%d %b %H:%M} UTC: {(r['last_error'] or '')[:300]}",
                                {"job_type": r["job_type"]}))
        cur.execute("SELECT to_regclass('ai.budget_alerts') IS NOT NULL AS present")
        present = cur.fetchone()
        if present and present["present"]:
            cur.execute("SELECT month, threshold, spent_usd, budget_usd, created_at FROM ai.budget_alerts "
                        "WHERE created_at > %s - interval '40 days'", (at,))
            for r in cur.fetchall():
                drafts.append(Draft(
                    "ai_budget", f"ai_budget:{r['month']:%Y-%m}:{r['threshold']}",
                    f"Presupuesto de IA: {r['threshold']} % del mes",
                    f"Gastado US${r['spent_usd']:.2f} de US${r['budget_usd']:.2f} en {r['month']:%Y-%m}. "
                    + ("La IA se detiene hasta el próximo mes; las reglas siguen." if r["threshold"] >= 100 else
                       "El presupuesto diario se adapta para no pasar el tope del mes."),
                    {"threshold": int(r["threshold"])}))
        cur.execute("SELECT worker_id, last_beat_at, tick_interval_s FROM raw.worker_heartbeats "
                    "ORDER BY last_beat_at DESC LIMIT 1")
        hb = cur.fetchone()
        if hb and hb["last_beat_at"] < at - timedelta(seconds=2 * int(hb["tick_interval_s"]) + 300):
            drafts.append(Draft("worker_down", f"worker_down:{hb['last_beat_at']:%Y%m%d%H}",
                                "Worker silent", f"No heartbeat since {hb['last_beat_at']:%d %b %H:%M} UTC: "
                                "captures and syncs are not running.", {}))
    return drafts


@dataclass
class NotifyReport:
    drafted: int = 0
    new: int = 0
    refused: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0


def run_notifier(conn: psycopg.Connection, channel: Channel | None, *, at: datetime | None = None) -> NotifyReport:
    at = at or now()
    report = NotifyReport()
    drafts = collect(conn, at=at)
    report.drafted = len(drafts)
    with conn.cursor() as cur:
        for d in drafts:
            try:
                # A savepoint per message: one the database refuses is reported, and does not take the rest of
                # the run's messages with it.
                with conn.transaction():
                    cur.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body, payload) "
                                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (dedup_key) DO NOTHING",
                                (d.kind, d.dedup_key, d.title, d.body, json.dumps(d.payload)))
            except psycopg.Error as exc:
                report.refused += 1
                log.error("notify.draft_refused", kind=d.kind, dedup_key=d.dedup_key, error=type(exc).__name__,
                          detail=str(exc).splitlines()[0][:200])
                continue
            report.new += max(cur.rowcount, 0)
        cur.execute("SELECT id, title, body FROM audit.notifications WHERE status = 'queued' ORDER BY id LIMIT %s",
                    (SEND_BATCH,))
        queued = cur.fetchall()
        for nid, title, body in queued:
            if channel is None:
                cur.execute("UPDATE audit.notifications SET status = 'skipped', last_error = %s WHERE id = %s",
                            ("no channel configured (FBI_TELEGRAM_BOT_TOKEN / FBI_TELEGRAM_CHAT_ID unset)", nid))
                report.skipped += 1
                continue
            try:
                channel.send(title, body)
            except ChannelError as exc:
                cur.execute("UPDATE audit.notifications SET status = 'failed', attempts = attempts + 1, "
                            "last_error = %s, channel = %s WHERE id = %s", (str(exc), channel.name, nid))
                report.failed += 1
                continue
            cur.execute("UPDATE audit.notifications SET status = 'sent', attempts = attempts + 1, sent_at = now(), "
                        "channel = %s, last_error = NULL WHERE id = %s", (channel.name, nid))
            report.sent += 1
    conn.commit()
    log.info("notify.done", drafted=report.drafted, new=report.new, refused=report.refused, sent=report.sent,
             skipped=report.skipped, failed=report.failed)
    return report
