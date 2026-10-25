"""The owner's notices about the readers' side (plan UX, A5): counts and a link to the console, never a reader's
address, alias or words (``tests/integration/test_messaging.py`` writes distinctive ones and looks for them).

The messenger drafts them every cycle into ``audit.notifications`` (the API's role may insert there); the worker's
notifier sends every queued row to the owner's channel, as it does with its own (fbi.notify.service). A notice is
keyed so that drafting it again is free:

    ticket_new        a request opened since the last notice (privacy now, support from A14)   - per newest request
    privacy_due       open privacy requests within 3 business days of their legal deadline     - once a day (Bogotá)
                      or past it
    outbox_failing    messages that failed in 24 h, or waiting over an hour while sending is on - once a day (UTC)
                      (also: sending switched on without a provider)
    synthetic_failed  the synthetic journey failed twice in a row or more                       - once per streak

    membership_due    covers ending today, accounts in their grace, accounts limited in the last day and «will
                      not renew» among those ending (A8) - counts only, the names in the console - once a morning
                      (Bogotá, from 07:00), and only when there is something to say

``ai_user_budget`` (A11) is an accepted kind already; its phase drafts it.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.customer import events, membership, workdays
from fbi.customer.privacy import bogota_today
from fbi.messaging.templates import long_date, web_base
from fbi.notify.service import Draft

log = structlog.get_logger(__name__)

DUE_WITHIN_BUSINESS_DAYS = 3
STUCK_AFTER = timedelta(hours=1)
SYNTHETIC_STREAK = 2
KIND_WORDS: dict[str, tuple[str, str]] = {
    "privacy_query": ("consulta", "consultas"),
    "privacy_claim": ("reclamo", "reclamos"),
    "privacy_deletion": ("solicitud de borrado", "solicitudes de borrado"),
    "support": ("pregunta de soporte", "preguntas de soporte"),
}


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _day(value: date) -> str:
    return long_date(value.isoformat(), "es")


def ticket_new(conn: psycopg.Connection[Any]) -> list[Draft]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT coalesce(max((payload->>'last_id')::bigint), 0) AS last FROM audit.notifications "
                    "WHERE kind = 'ticket_new'")
        last = int((cur.fetchone() or {"last": 0})["last"])
        cur.execute("SELECT id, kind, coalesce(extended_to, due_on) AS deadline FROM customer.support_tickets "
                    "WHERE id > %s AND status = 'open' ORDER BY id", (last,))
        rows = cur.fetchall()
    if not rows:
        return []
    kinds = Counter(str(r["kind"]) for r in rows)
    parts = [_n(n, *KIND_WORDS.get(k, ("solicitud", "solicitudes"))) for k, n in sorted(kinds.items())]
    deadlines = [r["deadline"] for r in rows if r["deadline"] is not None]
    nearest = f" Plazo más cercano: {_day(min(deadlines))}." if deadlines else ""
    newest = int(rows[-1]["id"])
    return [Draft(
        "ticket_new", f"ticket_new:{newest}",
        f"{_n(len(rows), 'solicitud nueva', 'solicitudes nuevas')} de lectores",
        f"{', '.join(parts)}.{nearest} Respóndelas desde la consola: {web_base()}/admin/users",
        {"last_id": newest, "count": len(rows)})]


def privacy_due(conn: psycopg.Connection[Any], *, at: datetime) -> list[Draft]:
    today = bogota_today(at)
    limit = workdays.add_business_days(today, DUE_WITHIN_BUSINESS_DAYS)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT coalesce(extended_to, due_on) AS deadline FROM customer.support_tickets "
                    "WHERE status = 'open' AND kind LIKE 'privacy\\_%%' AND coalesce(extended_to, due_on) <= %s",
                    (limit,))
        deadlines = [r["deadline"] for r in cur.fetchall()]
    if not deadlines:
        return []
    late = sum(1 for d in deadlines if d < today)
    soon = len(deadlines) - late
    lines = []
    if soon:
        lines.append(f"{_n(soon, 'solicitud vence', 'solicitudes vencen')} en {DUE_WITHIN_BUSINESS_DAYS} días hábiles "
                     f"o menos (la más cercana: {_day(min(d for d in deadlines if d >= today))}).")
    if late:
        lines.append(f"{_n(late, 'solicitud ya venció', 'solicitudes ya vencieron')} sin respuesta.")
    return [Draft(
        "privacy_due", f"privacy_due:{today.isoformat()}",
        "Solicitudes de privacidad cerca de su plazo legal",
        " ".join(lines) + f" Ley 1581: respóndelas desde la consola: {web_base()}/admin/users",
        {"soon": soon, "late": late})]


def outbox_failing(conn: psycopg.Connection[Any], *, at: datetime, sending: bool, provider: bool) -> list[Draft]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT count(*) FILTER (WHERE status = 'failed' AND updated_at > %s - interval '24 hours') AS failed,
                   count(*) FILTER (WHERE status = 'queued' AND created_at < %s) AS stuck,
                   (SELECT last_error FROM customer.messages_outbox
                     WHERE status IN ('failed', 'queued') AND last_error IS NOT NULL
                     ORDER BY updated_at DESC LIMIT 1) AS last_error
              FROM customer.messages_outbox
             WHERE status IN ('failed', 'queued')
        """, (at, at - STUCK_AFTER))
        row = cur.fetchone() or {"failed": 0, "stuck": 0, "last_error": None}
    failed = int(row["failed"] or 0)
    stuck = int(row["stuck"] or 0) if sending else 0
    lines = []
    if sending and not provider:
        lines.append("El envío está encendido (FBI_EMAIL_SEND) pero falta la clave o el remitente de Resend: "
                     "nada sale.")
    if failed:
        lines.append(f"{_n(failed, 'correo falló', 'correos fallaron')} en las últimas 24 h.")
    if stuck:
        lines.append(f"{_n(stuck, 'correo espera', 'correos esperan')} en la cola desde hace más de una hora.")
    if not lines:
        return []
    cause = f" Última causa: {row['last_error']}." if row["last_error"] else ""
    return [Draft(
        "outbox_failing", f"outbox_failing:{at:%Y-%m-%d}", "Correo a lectores: hay envíos con problemas",
        " ".join(lines) + cause + f" Mira la cola en la consola: {web_base()}/admin/messages",
        {"failed": failed, "stuck": stuck, "provider": provider})]


def synthetic_failed(conn: psycopg.Connection[Any]) -> list[Draft]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, status, started_at, last_error FROM raw.ingestion_runs "
                    "WHERE job_type = 'synthetic_journey' AND status <> 'running' ORDER BY started_at DESC, id DESC "
                    "LIMIT 50")
        runs = cur.fetchall()
    streak = []
    for run in runs:
        if run["status"] != "failed":
            break
        streak.append(run)
    if len(streak) < SYNTHETIC_STREAK:
        return []
    first, last = streak[-1], streak[0]
    error = str(last["last_error"] or "")[:200]
    return [Draft(
        "synthetic_failed", f"synthetic_failed:{first['id']}",
        f"El recorrido sintético falló {len(streak)} veces seguidas",
        f"Desde {first['started_at']:%d %b %H:%M} UTC un lector no podría completar el recorrido (entrar, Inicio, "
        f"partido, Picks, Mis picks). Último error: {error or '—'}. Corridas: {web_base()}/admin/system",
        {"runs": len(streak), "first_run_id": int(first["id"])})]


MORNING_HOUR = 7
"""The owner's membership notice waits for the morning in Bogotá: «each morning the day's count» (section 22)."""


def membership_due(conn: psycopg.Connection[Any], *, at: datetime) -> list[Draft]:
    local = at.astimezone(events.BOGOTA)
    if local.hour < MORNING_HOUR:
        return []
    today = local.date()
    counts = membership.owner_counts(conn, at=at, today_bounds=events.day_bounds(today))
    if not any(counts.values()):
        return []
    lines = []
    if counts["ending_today"]:
        lines.append(f"{_n(counts['ending_today'], 'membresía termina', 'membresías terminan')} hoy.")
    if counts["in_grace"]:
        lines.append(f"{_n(counts['in_grace'], 'cuenta está', 'cuentas están')} en sus 3 días de gracia.")
    if counts["expired_today"]:
        lines.append(f"{_n(counts['expired_today'], 'cuenta pasó', 'cuentas pasaron')} a acceso limitado en el "
                     "último día.")
    if counts["will_not_renew"]:
        lines.append(f"{_n(counts['will_not_renew'], 'dijo', 'dijeron')} que no renovará.")
    return [Draft(
        "membership_due", f"membership_due:{today.isoformat()}",
        "Vencimientos de membresía de hoy",
        " ".join(lines) + f" Los nombres, en la consola: {web_base()}/admin/users?membership=due",
        counts)]


def collect(conn: psycopg.Connection[Any], *, at: datetime, sending: bool, provider: bool) -> list[Draft]:
    return [*ticket_new(conn), *privacy_due(conn, at=at),
            *outbox_failing(conn, at=at, sending=sending, provider=provider), *synthetic_failed(conn),
            *membership_due(conn, at=at)]


def write(conn: psycopg.Connection[Any], drafts: list[Draft]) -> int:
    """Insert the drafts that are new (one savepoint each, so a refused one keeps the others). Commits."""
    new = 0
    for d in drafts:
        try:
            with conn.transaction():
                cur = conn.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body, payload) "
                                   "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (dedup_key) DO NOTHING",
                                   (d.kind, d.dedup_key, d.title, d.body, json.dumps(d.payload)))
                new += max(cur.rowcount, 0)
        except psycopg.Error as exc:
            log.error("notices.refused", kind=d.kind, error=type(exc).__name__)
    conn.commit()
    if new:
        log.info("notices.drafted", new=new, kinds=sorted({d.kind for d in drafts}))
    return new
