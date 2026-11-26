"""The store of verdicts of the plan's experiments (plan RP-8.1, finding H24).

An experiment (``fbi.research.exp_protocol``, EXP-E1 ... EXP-E8) is judged by arithmetic against thresholds fixed before its data. This module is
where that judgement is WRITTEN DOWN, once and for good, in ``analytics.experiment_verdicts`` (append-only, migration 0183):

* ``record`` refuses a verdict that does not stand on a registered protocol: it goes through ``exp_protocol.admit`` (the protocol exists, the fingerprint
  the result carries is the registered one, the result was computed after the signature). The table keeps the fingerprint so that the claim can be
  audited later by anyone.
* A verdict is never edited: a newer one of the same experiment supersedes the older one (``latest``); the older stays as history.
* ``NaN`` is stored as ``NULL`` (an «insufficient» verdict before the sample is there has no mean); a decided verdict (``exito``, ``abandono``) must
  carry its mean and its interval, as the table demands.

It decides nothing about a model, a forecast, a pick or a threshold. A verdict of success promotes nothing by itself.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.types.json import Jsonb

from fbi.research import exp_protocol
from fbi.research.exp_protocol import Judgement, ProtocolRefusedError, Verdict
from fbi.research.protocol import Protocol, fingerprint

VERSION: Final = "experiment-verdicts-v1"
RECORDERS: Final = ("system", "owner")
VERDICTS: Final[tuple[Verdict, ...]] = ("exito", "abandono", "insuficiente")

Recorder = Literal["system", "owner"]


class VerdictRefusedError(ValueError):
    """A verdict that cannot be written: not a number where one is required, an unknown recorder, a reason too short."""


@dataclass(frozen=True, slots=True)
class Stored:
    """One verdict as it is kept."""

    id: int
    experiment: str
    protocol_version: str
    protocol_fingerprint: str
    verdict: str
    reason: str
    n: int
    mean: float | None
    low: float | None
    high: float | None
    adjusted_p: float | None
    thresholds: dict[str, Any]
    population: dict[str, Any]
    computed_at: datetime
    recorded_at: datetime
    recorded_by: str


_COLUMNS: Final = ("id, experiment, protocol_version, protocol_fingerprint, verdict, reason, n, mean, low, high, adjusted_p, thresholds, population, "
                   "computed_at, recorded_at, recorded_by")


def _number(x: float | None) -> float | None:
    """NaN and infinities are not figures: they are stored as «no figure»."""
    return None if x is None or not math.isfinite(x) else float(x)


def _stored(row: tuple[Any, ...]) -> Stored:
    return Stored(*row)


def record(conn: psycopg.Connection[Any], experiment: str, judgement: Judgement, *, claimed_fingerprint: str, computed_at: datetime,
           population: Mapping[str, Any] | None = None, thresholds: Mapping[str, Any] | None = None, recorded_by: Recorder = "system",
           registry: Mapping[str, Protocol] | None = None) -> Stored:
    """Write the verdict of ``experiment`` after checking it stands on its registered protocol.

    Raises ``ProtocolRefusedError`` (no protocol, another fingerprint, computed before the signature) or ``VerdictRefusedError`` (anything else the
    table would refuse, said before the database says it). ``thresholds`` default to the audit's own (``exp_protocol.THRESHOLDS``)."""
    if recorded_by not in RECORDERS:
        raise VerdictRefusedError(f"quien registra debe ser uno de {RECORDERS}, no {recorded_by!r}")
    if judgement.verdict not in VERDICTS:
        raise VerdictRefusedError(f"veredicto desconocido: {judgement.verdict!r}")
    if computed_at.tzinfo is None:
        raise VerdictRefusedError("la fecha del cálculo debe llevar zona horaria")
    protocol = exp_protocol.admit(experiment, claimed_fingerprint=claimed_fingerprint, computed_at=computed_at, registry=registry)
    mean, low, high = _number(judgement.mean), _number(judgement.low), _number(judgement.high)
    if judgement.verdict != "insuficiente" and (mean is None or low is None or high is None or low > high):
        raise VerdictRefusedError(f"{experiment}: un veredicto de {judgement.verdict} lleva su media y su intervalo")
    if len(judgement.reason.strip()) < 10:
        raise VerdictRefusedError(f"{experiment}: el veredicto lleva su motivo")
    fixed = dict(exp_protocol.THRESHOLDS.get(experiment, {}) if thresholds is None else thresholds)
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO analytics.experiment_verdicts (experiment, protocol_version, protocol_fingerprint, verdict, reason, n, mean, low, "
                    f"high, adjusted_p, thresholds, population, computed_at, recorded_by) "
                    f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
                    (experiment, protocol.version, fingerprint(protocol), judgement.verdict, judgement.reason.strip(), judgement.n, mean, low, high,
                     _number(judgement.adjusted_p), Jsonb(fixed), Jsonb(dict(population or {})), computed_at, recorded_by))
        row = cur.fetchone()
    assert row is not None
    return _stored(row)


def latest(conn: psycopg.Connection[Any]) -> list[Stored]:
    """The current verdict of each experiment that has one (the newest of each), in the order of the plan."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM analytics.experiment_verdicts_latest ORDER BY length(experiment), experiment")
        return [_stored(r) for r in cur.fetchall()]


def history(conn: psycopg.Connection[Any], experiment: str) -> list[Stored]:
    """Every verdict of one experiment, the newest first: what was concluded and what superseded it."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM analytics.experiment_verdicts WHERE experiment = %s ORDER BY id DESC", (experiment,))
        return [_stored(r) for r in cur.fetchall()]


def pending(conn: psycopg.Connection[Any]) -> list[str]:
    """The experiments of the plan that have no decided verdict yet (none, or only «insuficiente»): what is still open."""
    decided = {v.experiment for v in latest(conn) if v.verdict != "insuficiente"}
    return [k for k in exp_protocol.EXPERIMENTS if k not in decided]


__all__ = ["VERSION", "ProtocolRefusedError", "Stored", "VerdictRefusedError", "history", "latest", "pending", "record"]
