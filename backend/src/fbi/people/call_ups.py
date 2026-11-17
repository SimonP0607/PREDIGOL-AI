"""The latest squad of a national team for its profile (plan 2026, AD-H06, ``IA-092``): official only when the registry allows it.

A call-up is OFFICIAL only when it comes from the federation's own communiqué read from a source the registry of sources
(``fbi.ai.source_registry``, AD-C01) lets PrediGol read automatically and extract from: state ``verificada_autorizada``, signed by
the owner, not reserved from AI, automated access not restricted, and authority ``confirma`` for ``convocatorias``. On
16-nov-2026 no official source meets that (of 671 official sources in directory v2: 559 ``verificada_pendiente_derechos``, 72
``bloqueada``, 40 ``no_comprobada``; the three authorised sources are outlets that only ``informa``), and the ingestion of official
facts (AD-C03) is not delivered. So the profile serves, labelled as such, what the PROVIDER says:

* ``convocados_ultimo_partido`` - the matchday squad (starters and bench) of the side's latest match with a line-up, when it is
  at most ``RECENT_DAYS`` old: who was actually called for that match;
* ``plantilla_proveedor`` - otherwise, the provider's squad list (``/players/squads``) when seen within ``RECENT_DAYS``;

and says why it is not official (``ninguna_fuente_oficial_autorizada`` or ``sin_comunicado_ingerido``). A list that is not
official never counts as one: its ``level`` is ``proveedor``. Minors are not linked to external ids (nothing here links ids).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal, Protocol


class Standing(Protocol):
    """What this module reads of ``fbi.ai.source_policy.Standing`` (described, not imported: ``fbi.people`` does not import ``fbi.ai``,
    ``tests/unit/test_architecture.py``)."""

    @property
    def authorised(self) -> bool: ...
    @property
    def automated_access(self) -> str: ...
    @property
    def authority(self) -> Mapping[str, Mapping[str, str]]: ...


class _Source(Protocol):
    @property
    def source_type(self) -> str: ...


class SourcePolicy(Protocol):
    """What this module reads of ``fbi.ai.source_policy.SourcePolicy``: its records by domain and the standing of a domain."""

    @property
    def by_domain(self) -> Mapping[str, _Source]: ...
    def standing(self, url_or_domain: str | None) -> Standing: ...

VERSION: Final = "call-ups-v1"
RECENT_DAYS: Final = 120
"""A national side plays a window every one to three months: a list older than this is not «recent»."""

Basis = Literal["comunicado_oficial", "convocados_ultimo_partido", "plantilla_proveedor"]
OfficialState = Literal["ninguna_fuente_oficial_autorizada", "sin_comunicado_ingerido"]


RESTRICTED_ACCESS: Final = frozenset({"restringido_robots", "prohibido_terminos"})


def permits_call_ups(standing: Standing) -> bool:
    """Whether a source may be read for an official call-up: authorised and signed, readable by machine, and it CONFIRMS them."""
    if not standing.authorised or standing.automated_access in RESTRICTED_ACCESS:
        return False
    entry = standing.authority.get("convocatorias") or {}
    return entry.get("level") == "confirma"


def permitted_official_domains(policy: SourcePolicy | None) -> list[str]:
    """The official sources (``tipo = oficial``) the registry in force lets PrediGol read for call-ups."""
    if policy is None:
        return []
    out: list[str] = []
    for domain, source in policy.by_domain.items():
        if source.source_type != "oficial":
            continue
        if permits_call_ups(policy.standing(domain)):
            out.append(domain)
    return sorted(out)


def official_state(permitted: int) -> OfficialState:
    return "ninguna_fuente_oficial_autorizada" if permitted == 0 else "sin_comunicado_ingerido"


@dataclass(frozen=True, slots=True)
class Candidate:
    basis: Basis
    seen_at: datetime
    fixture_id: int | None
    players: int


def choose(candidates: Iterable[Candidate], *, now: datetime, recent_days: int = RECENT_DAYS) -> Candidate | None:
    """The list to show: a match's squad before the provider's squad list, the newest of each, only if recent and not empty."""
    floor = now - timedelta(days=recent_days)
    kept = [c for c in candidates if c.players > 0 and floor <= c.seen_at <= now]
    order = {"comunicado_oficial": 0, "convocados_ultimo_partido": 1, "plantilla_proveedor": 2}
    kept.sort(key=lambda c: (order[c.basis], -c.seen_at.timestamp()))
    return kept[0] if kept else None
