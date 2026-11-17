"""A player's availability as a STATE with its source and date, never a medical detail (plan 2026, AD-H05, ``IA-091``).

What a profile (C-09) shows of a player who may miss a match is one of four words - ``disponible``, ``duda``, ``baja``,
``sancionado`` - with where it comes from, how firm that source is and when PrediGol learned it. What the player has, how long
he will be out and any medical text are personal health data (Ley 1581 de 2012, art. 5): they are read here only to tell a
suspension from an injury and are never returned. ``Report`` has no field for them, and ``State`` neither.

Two origins are unified:

* the provider's injury report (``core.player_availability_obs``, the history of ``/injuries``; ``fbi.ai.absences`` reads it as
  of a moment): ``Missing Fixture`` is out - ``sancionado`` when the reason is a card or a suspension, ``baja`` otherwise -, and
  ``Questionable`` is ``duda``. A season whose report was asked for and does not name a player of the squad says he is
  ``disponible`` (basis ``proveedor``, dated by that check);
* the facts of the press and of official sources about the match (``ai.evidence``: ``injury``, ``suspension``, ``doubtful`` with
  the assertion ``out``, ``doubtful`` or ``available``), with their level: an official source (league, federation, club) is
  ``oficial``; a fact confirmed by two outlets ``dos_origenes``; one outlet ``un_medio``. A rumour, a contradicted or an
  outdated fact changes nothing.

PRECEDENCE: ``oficial`` > ``proveedor`` > ``dos_origenes`` > ``un_medio``; between two reports of the same level, the newer one.
Pure: the reads are in ``fbi.api.repositories.profiles``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

VERSION: Final = "availability-v1"

Status = Literal["disponible", "duda", "baja", "sancionado"]
Basis = Literal["oficial", "proveedor", "dos_origenes", "un_medio"]

RANK: Final[dict[str, int]] = {"oficial": 0, "proveedor": 1, "dos_origenes": 2, "un_medio": 3}
"""Lower wins."""

PROVIDER_SOURCE: Final = "API-Football (parte de bajas)"

_SUSPENSION: Final = re.compile(r"\b(red card|yellow cards?|suspend\w*|suspension|ban(ned)?|sanci\w+|tarjeta\w*)\b", re.IGNORECASE)
"""The provider's reasons that are a suspension, not an injury (``Red Card``, ``Yellow Cards``, ``Suspended``)."""

OFFICIAL_TIERS: Final = frozenset({"official", "competition", "club"})
PRESS_STATUSES: Final = frozenset({"CONFIRMED", "PROBABLE"})
"""``RUMOR``, ``CONTRADICTORY`` and ``OUTDATED`` never change a state."""


@dataclass(frozen=True, slots=True)
class Report:
    """One statement about one player for one match: only the state, its basis, its source's name and when it was learned."""

    provider_player_id: int
    name: str
    status: Status
    basis: Basis
    source: str
    known_at: datetime
    fixture_id: int | None = None
    implied: bool = False
    """True for «disponible» because a checked report does not name him: any statement of the same basis wins over it."""


@dataclass(frozen=True, slots=True)
class State:
    provider_player_id: int
    name: str
    status: Status
    basis: Basis
    source: str
    known_at: datetime
    fixture_id: int | None


def provider_status(absence_type: str | None, reason: str | None) -> Status | None:
    """The state the provider's report gives (None: a type it does not name). ``reason`` decides only suspension or not."""
    kind = (absence_type or "").strip().lower()
    if kind == "questionable":
        return "duda"
    if kind == "missing fixture":
        return "sancionado" if reason and _SUSPENSION.search(reason) else "baja"
    return None


def press_status(kind: str | None, assertion: str | None) -> Status | None:
    """The state a typed fact of the press gives (None: it says nothing about availability)."""
    a = (assertion or "").strip().lower()
    if a == "available":
        return "disponible"
    if a == "doubtful" or (kind == "doubtful" and a in ("", "out")):
        return "duda"
    if a == "out":
        return "sancionado" if kind == "suspension" else "baja"
    return None


def press_basis(status: str | None, tier: str | None) -> Basis | None:
    """How firm a fact of the press is (None: it does not count - a rumour, a contradiction, an outdated fact)."""
    if (status or "") not in PRESS_STATUSES or tier == "provider":  # the provider's own report is read from its history
        return None
    if (tier or "") in OFFICIAL_TIERS:
        return "oficial"
    return "dos_origenes" if status == "CONFIRMED" else "un_medio"


def wins(a: Report, b: Report) -> bool:
    """Whether report ``a`` decides over ``b``."""
    return (RANK[a.basis], a.implied, -a.known_at.timestamp()) < (RANK[b.basis], b.implied, -b.known_at.timestamp())


def resolve(reports: Iterable[Report]) -> dict[int, State]:
    """provider player id -> the state that decides: by precedence, then a statement before an implied «disponible», then
    recency."""
    best: dict[int, Report] = {}
    for r in reports:
        old = best.get(r.provider_player_id)
        if old is None or wins(r, old):
            best[r.provider_player_id] = r
    return {pid: State(r.provider_player_id, r.name, r.status, r.basis, r.source, r.known_at, r.fixture_id)
            for pid, r in best.items()}


def provider_reports(rows: Iterable[Mapping[str, object]], *, fixture_id: int) -> list[Report]:
    """The provider's listings (``fbi.ai.absences.absences_as_of`` rows) as reports; the reason is read and dropped here."""
    out: list[Report] = []
    for r in rows:
        status = provider_status(_text(r.get("absence_type")), _text(r.get("reason")))
        pid, at = r.get("provider_player_id"), r.get("fetched_at")
        if status is None or not isinstance(pid, int) or not isinstance(at, datetime):
            continue
        out.append(Report(pid, _text(r.get("player_name")) or str(pid), status, "proveedor", PROVIDER_SOURCE, at, fixture_id))
    return out


def press_reports(rows: Iterable[Mapping[str, object]]) -> list[Report]:
    """Typed facts of ``ai.evidence`` as reports. The claim's text is never read here (the query does not select it)."""
    out: list[Report] = []
    for r in rows:
        status = press_status(_text(r.get("kind")), _text(r.get("assertion")))
        basis = press_basis(_text(r.get("status")), _text(r.get("source_tier")))
        pid, at = r.get("provider_player_id"), r.get("known_at")
        if status is None or basis is None or not isinstance(pid, int) or not isinstance(at, datetime):
            continue
        fixture = r.get("fixture_id")
        out.append(Report(pid, _text(r.get("player_name")) or str(pid), status, basis,
                          _text(r.get("source_name")) or _text(r.get("source_domain")) or "prensa", at,
                          fixture if isinstance(fixture, int) else None))
    return out


def available_by_default(squad: Iterable[tuple[int, str]], *, checked_at: datetime | None, fixture_id: int) -> list[Report]:
    """Each man of the squad as ``disponible`` when the provider's report of the season was asked for (at ``checked_at``): a
    report that does not name him says so. Without a check, nothing - not knowing is not «available»."""
    if checked_at is None:
        return []
    return [Report(pid, name, "disponible", "proveedor", PROVIDER_SOURCE, checked_at, fixture_id, implied=True)
            for pid, name in squad]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
