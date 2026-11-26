"""The expected freshness of the twelve stages of the learning cycle, and the check that says when one has stopped (plan RP-1.5, H26).

Section 13 of the restructuring plan gives the cycle twelve stages, each with the alarm that says it stopped. The research loop and the picks'
post-mortem stood still for weeks (4 Oct, 23 Oct) and nothing said so: this is the table in code, a pure judgement of each row, and one
reading per stage. It decides nothing, changes no parameter, and writes nothing: the hourly job (``stall_check``) reads, judges, and leaves the
result in the book of runs (an alarm is an error line of the run) and in the block ``flow`` of the console (C-11 1.2).

A stage whose store does not exist yet (the verdicts, the comparisons, the follow-up: RP-8.x, RP-9.x) is NOT reported as up to date: it is
``sin_almacen`` with the piece that delivers it. A stage the plan gives no time limit for (11) reports its figure as ``informativa``. The
grace of stage 5 (24 h) is this code's own choice and is written in the row.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg

from fbi.ops import job_book

VERSION: Final = "freshness-v1"

Status = Literal["al_dia", "parada", "sin_almacen", "sin_registro", "informativa"]
STATUSES: Final = ("al_dia", "parada", "sin_almacen", "sin_registro", "informativa")

OBSERVATION_HOURS: Final = 36
PATTERN_DAYS: Final = 8
PROPOSED_LIMIT: Final = 20
TRIAGE_DAYS: Final = 31
ACCEPTED_GRACE_HOURS: Final = 24

WEEKLY_JOB: Final = "research_v2_weekly"
ALIVE_SKIPS: Final = ("", "no_toca_aun")
"""A weekly pass counts as a run when it did the research or when it looked and found it was not due yet (same code, under four weeks since the
last one: ``no_toca_aun``). A pass that skipped because its switch is off is not a run of the stage: the stage is stopped, on purpose or not."""


@dataclass(frozen=True)
class Stage:
    number: int
    key: str
    name_es: str
    alarm_es: str
    """The alarm as the plan words it («Sin filas en 36 horas»)."""
    delivered_by: str | None = None
    """The piece that gives the stage its store when it has none yet."""


STAGES: Final[tuple[Stage, ...]] = (
    Stage(1, "observacion", "Observación", f"Sin filas en {OBSERVATION_HOURS} horas"),
    Stage(2, "patron", "Patrón", f"Sin corrida en {PATTERN_DAYS} días"),
    Stage(3, "hipotesis", "Hipótesis", f"Más de {PROPOSED_LIMIT} propuestas sin triage"),
    Stage(4, "triage", "Triage", f"Hipótesis propuesta sin triage hace más de {TRIAGE_DAYS} días"),
    Stage(5, "experimento", "Experimento", f"Aceptada sin protocolo pasadas {ACCEPTED_GRACE_HOURS} horas"),
    Stage(6, "validacion_historica", "Validación histórica", "Experimento sin resultado", "RP-8.3"),
    Stage(7, "sombra_prospectiva", "Sombra prospectiva", "Sombra sin condición de decisión", "RP-9.1"),
    Stage(8, "comparacion", "Comparación", "Muestra alcanzada sin comparar", "RP-8.3"),
    Stage(9, "veredicto", "Veredicto", "Comparación sin veredicto", "RP-8.1"),
    Stage(10, "propuesta_de_cambio", "Propuesta de cambio", "Éxito sin propuesta", "RP-8.1"),
    Stage(11, "aprobacion", "Aprobación y promoción o descarte", "Propuesta sin decidir"),
    Stage(12, "seguimiento", "Seguimiento", "Promoción sin vigilancia", "RP-12.2"),
)

assert [s.number for s in STAGES] == list(range(1, 13))


@dataclass(frozen=True)
class Reading:
    """One stage, read: its status, the figure that gave it, and the limit it was held to."""

    stage: Stage
    status: Status
    detail_es: str
    value: float | None = None
    limit: float | None = None
    unit: str | None = None
    last_at: datetime | None = None


# ── the judgements (pure) ────────────────────────────────────────────────────────────────────────────────

def judge_age(last_at: datetime | None, at: datetime, limit: timedelta, *, since: datetime | None = None) -> Status:
    """Stopped when the last sign of life is older than ``limit``. With no sign at all it is stopped only if the thing has been watched for
    longer than ``limit`` (``since``): a book that opened an hour ago cannot say a weekly job missed its week."""
    if last_at is not None:
        return "parada" if at - last_at > limit else "al_dia"
    if since is None or at - since <= limit:
        return "sin_registro"
    return "parada"


def judge_count(count: int, limit: int) -> Status:
    """Stopped when MORE than ``limit`` wait (the plan's «más de 20»)."""
    return "parada" if count > limit else "al_dia"


def hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 1)


# ── the readings ────────────────────────────────────────────────────────────────────────────────────────

Conn = psycopg.Connection[Any]


def _one(conn: Conn, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    """One row of a read in its own savepoint, so a table that is not there answers ``UndefinedTable`` without poisoning the pass."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return tuple(row) if row else ()


def _no_store(stage: Stage, why: str | None = None) -> Reading:
    piece = f" Lo entrega {stage.delivered_by}." if stage.delivered_by else ""
    return Reading(stage, "sin_almacen", why or f"Todavía no existe el almacén de esta etapa.{piece}")


def _age_reading(stage: Stage, last_at: datetime | None, at: datetime, limit: timedelta, *, since: datetime | None = None,
                 what: str) -> Reading:
    status = judge_age(last_at, at, limit, since=since)
    if last_at is None:
        text = f"{what}: ninguno registrado." if status == "sin_registro" else f"{what}: ninguno desde que se vigila."
        return Reading(stage, status, text, None, hours(limit), "horas", None)
    age = at - last_at
    return Reading(stage, status, f"{what}: hace {hours(age)} horas (límite {hours(limit)}).", hours(age), hours(limit), "horas", last_at)


def book_since(conn: Conn) -> datetime | None:
    """When the book of runs of the cycle began: the oldest run of a job the book opened (RP-1.1)."""
    row = _one(conn, "SELECT min(started_at) FROM raw.ingestion_runs WHERE job_name = ANY(%s)", (list(job_book.BOOKED_JOB_TYPES),))
    return row[0] if row else None


def read_observation(conn: Conn, at: datetime, stage: Stage) -> Reading:
    row = _one(conn, "SELECT max(created_at) FROM intel.match_postmortems")
    return _age_reading(stage, row[0] if row else None, at, timedelta(hours=OBSERVATION_HOURS), what="Último post-mortem de partido")


def read_pattern(conn: Conn, at: datetime, stage: Stage) -> Reading:
    last = _one(conn, "SELECT max(finished_at) FROM raw.ingestion_runs WHERE job_name = %s AND status = 'completed' "
                      "AND coalesce(params->>'skipped', '') = ANY(%s)", (WEEKLY_JOB, list(ALIVE_SKIPS)))
    return _age_reading(stage, last[0] if last else None, at, timedelta(days=PATTERN_DAYS), since=book_since(conn),
                        what="Última corrida de la investigación semanal")


def read_hypotheses(conn: Conn, at: datetime, stage: Stage) -> Reading:
    n = int(_one(conn, "SELECT count(*) FROM analytics.research_hypotheses WHERE status = 'PROPOSED'")[0])
    status = judge_count(n, PROPOSED_LIMIT)
    return Reading(stage, status, f"{n} hipótesis propuestas sin triage (límite {PROPOSED_LIMIT}).", float(n), float(PROPOSED_LIMIT), "hipótesis")


def read_triage(conn: Conn, at: datetime, stage: Stage) -> Reading:
    row = _one(conn, "SELECT min(created_at) FROM analytics.research_hypotheses WHERE status = 'PROPOSED'")
    oldest = row[0] if row else None
    if oldest is None:
        return Reading(stage, "al_dia", "Ninguna hipótesis espera triage.", 0.0, float(TRIAGE_DAYS), "días")
    days = round((at - oldest).total_seconds() / 86400, 1)
    status: Status = "parada" if at - oldest > timedelta(days=TRIAGE_DAYS) else "al_dia"
    return Reading(stage, status, f"La propuesta más antigua espera hace {days} días (límite {TRIAGE_DAYS}).", days, float(TRIAGE_DAYS), "días", oldest)


def read_experiment(conn: Conn, at: datetime, stage: Stage) -> Reading:
    n = int(_one(conn, "SELECT count(*) FROM analytics.research_hypotheses WHERE status = 'ACCEPTED' "
                       "AND cardinality(experiment_ids) = 0 AND decided_at < %s", (at - timedelta(hours=ACCEPTED_GRACE_HOURS),))[0])
    status: Status = "parada" if n else "al_dia"
    return Reading(stage, status, f"{n} hipótesis aceptadas sin experimento pasadas {ACCEPTED_GRACE_HOURS} horas.", float(n), 0.0, "hipótesis")


def read_approval(conn: Conn, at: datetime, stage: Stage) -> Reading:
    n = int(_one(conn, "SELECT count(*) FROM ai.change_proposals p WHERE NOT EXISTS "
                       "(SELECT 1 FROM ai.change_applications a WHERE a.proposal_id = p.id)")[0])
    return Reading(stage, "informativa", f"{n} propuestas de cambio esperan tu decisión. El plan no fija plazo: se informa la cifra.",
                   float(n), None, "propuestas")


READERS: Final[dict[int, Callable[[Conn, datetime, Stage], Reading]]] = {
    1: read_observation, 2: read_pattern, 3: read_hypotheses, 4: read_triage, 5: read_experiment, 11: read_approval,
}


def read_stage(conn: Conn, at: datetime, stage: Stage) -> Reading:
    reader = READERS.get(stage.number)
    if reader is None:
        return _no_store(stage)
    try:
        return reader(conn, at, stage)
    except psycopg.errors.UndefinedTable:
        return _no_store(stage, "La tabla de esta etapa no existe en esta base.")


def read_all(conn: Conn, *, at: datetime) -> list[Reading]:
    """The twelve stages, in order, each read in its own savepoint. Read-only."""
    return [read_stage(conn, at, s) for s in STAGES]


def alarms(readings: list[Reading]) -> list[Reading]:
    return [r for r in readings if r.status == "parada"]


__all__ = ["ACCEPTED_GRACE_HOURS", "OBSERVATION_HOURS", "PATTERN_DAYS", "PROPOSED_LIMIT", "READERS", "STAGES", "STATUSES", "TRIAGE_DAYS",
           "VERSION", "WEEKLY_JOB", "Reading", "Stage", "alarms", "judge_age", "judge_count", "read_all", "read_stage"]
