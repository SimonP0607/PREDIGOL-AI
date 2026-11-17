"""The match read again (IA-105, AD-D06; the incident of 12 Nov 2026): what changed in its kick-off or its conditions since the cycle last
read it. Pure.

E4 reads the match again with ``fbi.ai.final_reread`` (IA-061, ``reread-v1``: the kick-off and the state stored now and whether the in-play
feed sees it playing) and its venue, and holds them against what the newest evaluation knew. Between evaluations the main pass does the
same every few minutes, so a kick-off moved after E1 is seen before E4, not in an audit days later.

Each change is ONE of:

    cambio_horario      the kick-off is earlier (``saque_adelantado``) or later (``saque_retrasado``)
    cambio_condiciones  the match is postponed (``aplazado``), cancelled or abandoned (``cancelado``), suspended (``suspendido``),
                        already started (``ya_empezado``) or its venue changed (``cambio_de_sede``)

with the value of before and the value of now. ``stops`` says whether the match will not be played as scheduled: its waiting and confirmed
selections are then withdrawn (``partido_no_jugado``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from fbi.ai import final_reread

KICKOFF: Final = "cambio_horario"
CONDITIONS: Final = "cambio_condiciones"
STOP_REASONS: Final = frozenset({"postponed", "cancelled", "suspended", "finished"})
CAUSE_OF: Final = {"postponed": "aplazado", "cancelled": "cancelado", "suspended": "suspendido", "finished": "ya_empezado",
                   "started": "ya_empezado", "kickoff_unknown": "saque_sin_hora"}


@dataclass(frozen=True, slots=True)
class Known:
    """What the newest evaluation of the match read."""

    kickoff_at: datetime
    status: str | None
    venue_id: int | None


@dataclass(frozen=True, slots=True)
class Change:
    kind: str
    cause: str
    before: dict[str, Any]
    after: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Check:
    verdict: final_reread.Verdict
    venue_now: int | None
    changes: tuple[Change, ...]

    @property
    def stops(self) -> bool:
        return self.verdict.reason in STOP_REASONS

    def record(self) -> dict[str, Any]:
        return {**self.verdict.record(), "venue_id": self.venue_now,
                "changes": [{"kind": c.kind, "cause": c.cause, "before": c.before, "after": c.after} for c in self.changes]}


def _iso(x: datetime | None) -> str | None:
    return None if x is None else x.isoformat()


def check(known: Known, reading: final_reread.Reading | None, venue_now: int | None, *, at: datetime) -> Check:
    """The match now (``reading``, ``venue_now``) against what the cycle last knew. Pure."""
    verdict = final_reread.judge(known.kickoff_at, known.status, reading, at=at)
    changes: list[Change] = []
    now_kickoff = None if reading is None else reading.kickoff_at
    if now_kickoff is not None and now_kickoff != known.kickoff_at:
        changes.append(Change(KICKOFF, "saque_adelantado" if now_kickoff < known.kickoff_at else "saque_retrasado",
                              {"kickoff_at": _iso(known.kickoff_at)}, {"kickoff_at": _iso(now_kickoff)}))
    cause = CAUSE_OF.get(verdict.reason or "")
    status_now = None if reading is None else reading.status
    if cause is not None and status_now != known.status:
        changes.append(Change(CONDITIONS, cause, {"status": known.status}, {"status": status_now}))
    elif verdict.reason == "started" and reading is not None and reading.in_play_at is not None:
        changes.append(Change(CONDITIONS, "ya_empezado", {"status": known.status, "in_play_at": None},
                              {"status": status_now, "in_play_at": _iso(reading.in_play_at)}))
    if known.venue_id is not None and venue_now is not None and venue_now != known.venue_id:
        changes.append(Change(CONDITIONS, "cambio_de_sede", {"venue_id": known.venue_id}, {"venue_id": venue_now}))
    return Check(verdict, venue_now, tuple(changes))
