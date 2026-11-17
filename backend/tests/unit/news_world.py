"""A fictitious registry of sources for the tests of the news store (IA-080): one source of each standing the policy knows, every one
under ``.invalid``.

    oficial.ejemplo.invalid     verificada_autorizada, signed by the owner -> store facts, publish summary
    sinfirma.ejemplo.invalid    verificada_autorizada, NOT signed           -> as pending: link / link
    radio.ejemplo.invalid       verificada_pendiente_derechos               -> link / link
    reservado.ejemplo.invalid   solo_referencia (reserved from AI)          -> link / link, ai_reserved
    bloqueado.ejemplo.invalid   bloqueada                                   -> nothing: never stored
    apuestas.ejemplo.invalid    the exclusion list blocks it                -> nothing: never stored
    anything else               not in the directory                        -> nothing: never stored
"""

from __future__ import annotations

from datetime import UTC, datetime

from fbi.ai import source_registry as registry
from fbi.ai.source_policy import SourcePolicy

AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)


def _source(sid: str, domain: str, state: str, *, ai: str = "permitido") -> registry.Source:
    return registry.Source(source_id=sid, domain=domain, name=sid, family="A", source_type="medio", state=state, automated_access="permitido",
                           ai_extraction=ai, storage="", publication="", authority={"convocatorias": {"level": "confirma"}},
                           last_reviewed=None, country="Colombia")


SOURCES = (
    _source("ej-oficial", "oficial.ejemplo.invalid", "verificada_autorizada"),
    _source("ej-sinfirma", "sinfirma.ejemplo.invalid", "verificada_autorizada"),
    _source("ej-radio", "radio.ejemplo.invalid", "verificada_pendiente_derechos"),
    _source("ej-reservado", "reservado.ejemplo.invalid", "solo_referencia", ai="reserva_ia_robots"),
    _source("ej-bloqueado", "bloqueado.ejemplo.invalid", "bloqueada"),
)
RULES = (registry.DomainRule("apuestas.ejemplo.invalid", "apuestas_o_pronosticos", "block"),)


def policy(*, signed: tuple[str, ...] = ("ej-oficial",)) -> SourcePolicy:
    return SourcePolicy(SOURCES, RULES, signed, directory_version="dir-ejemplo-1", exclusion_version="excl-ejemplo-1", origin="db")
