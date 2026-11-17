"""The cycle of states of a selection read off its evaluations (IA-105, AD-D06 with AD-D02). Pure.

Every verdict of ``intel.eval_verdicts`` (E1 and E2 read, E3 and E4 judge) is a step of the selection's chain under the writer
``eval-cycle-v1`` - the same machine (``fbi.lifecycle.machine``) and the same closing at kick-off as the chains read off the layers
(``fbi.lifecycle.derive``):

* the first verdict opens the chain at ``detectado``;
* a verdict that says what the chain already says is not a new row; one the machine has no move for is folded the way ``derive`` folds
  a layer's word: a waiting or confirmed selection that falls back to evaluation is ``retirada`` (its reason), a withdrawn one stays
  withdrawn until it comes back or closes;
* at kick-off a confirmed selection is ``en_juego``; any other open one is ``descartada`` with what held it (a selection still waiting for
  its line-up: ``sin_alineacion_a_tiempo``); a match that will not be played closes them all (``partido_no_jugado``).

Unlike decision-v1's rows, an E3 or E4 verdict inside the last ten minutes counts: it is code reading the line-up, not decision-v1's floor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from fbi.lifecycle import derive, machine
from fbi.lifecycle.derive import Fixture, Row
from fbi.lifecycle.machine import Step

WRITER: Final = "eval-cycle-v1"
LAYER: Final = "decision-v2"
SOURCE: Final = "intel.eval_verdicts"


@dataclass(frozen=True, slots=True)
class Verdict:
    id: int
    known_at: datetime
    state: str
    reason: str
    evaluation: str
    evaluation_version: int


def _played(f: Fixture, now: datetime) -> bool:
    return now >= f.kickoff_at and ((f.status_short or "") in derive.STARTED_STATUS or f.status_group in ("live", "finished"))


def _not_played(f: Fixture, now: datetime) -> bool:
    status = f.status_short or ""
    return status in derive.NOT_PLAYED or (status in derive.DEFERRED and now >= f.kickoff_at + derive.DEFERRED_GRACE)


def chain(verdicts: Sequence[Verdict], fixture: Fixture, *, now: datetime) -> list[Row]:
    """The chain of one selection as of ``now``; every row checked by the machine (``machine.IllegalTransitionError`` otherwise)."""
    seen = sorted((v for v in verdicts if v.known_at < fixture.kickoff_at and v.known_at <= now), key=lambda v: (v.known_at, v.id))
    if not seen:
        return []
    rows: list[Row] = []

    def state() -> str | None:
        return rows[-1].step.state if rows else None

    def emit(step: Step, at: datetime, source: str, source_id: int | None) -> None:
        machine.check(state(), step)
        last = rows[-1].known_at if rows else None
        rows.append(Row(step, at if last is None or at >= last else last, source, source_id, LAYER))

    emit(Step("detectado", "candidato_nuevo"), seen[0].known_at, SOURCE, seen[0].id)
    for v in seen:
        cur = state()
        target, reason = v.state, v.reason
        if cur == "retirada" and target in ("en_evaluacion", "en_investigacion"):
            continue
        if cur in ("pendiente_alineaciones", "confirmada_sombra") and target in ("en_evaluacion", "en_investigacion"):
            target = "retirada"
            reason = reason if reason in machine.REASONS["retirada"] else "sin_motivo_conocido"
        if target == "retirada" and cur not in ("pendiente_alineaciones", "confirmada_sombra"):
            continue  # only what was waiting or confirmed can be withdrawn; the evaluation's word is kept in its verdict
        if rows and (target, reason) == (rows[-1].step.state, rows[-1].step.reason):
            continue
        if cur == target and target not in machine.REPEATABLE:
            continue
        if reason not in machine.REASONS.get(target, ()):
            reason = "sin_motivo_conocido" if "sin_motivo_conocido" in machine.REASONS.get(target, ()) else reason
        if machine.problems(cur, Step(target, reason, evaluation=v.evaluation, evaluation_version=v.evaluation_version)):
            continue
        emit(Step(target, reason, evaluation=v.evaluation, evaluation_version=v.evaluation_version), v.known_at, SOURCE, v.id)
    cur = state()
    if cur in machine.OPEN and _not_played(fixture, now):
        if cur in ("pendiente_alineaciones", "confirmada_sombra"):
            emit(Step("retirada", "partido_no_jugado"), fixture.kickoff_at, "core.fixtures", fixture.id)
        emit(Step("descartada", "partido_no_jugado"), fixture.kickoff_at, "core.fixtures", fixture.id)
    elif cur in machine.OPEN and _played(fixture, now):
        if cur == "confirmada_sombra":
            emit(Step("en_juego", "saque"), fixture.kickoff_at, "core.fixtures", fixture.id)
        else:
            reason = rows[-1].step.reason
            emit(Step("descartada", derive.closing_reason(str(cur), reason)), fixture.kickoff_at, "core.fixtures", fixture.id)
    return rows
