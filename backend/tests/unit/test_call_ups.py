"""Call-ups of national teams: official only from a source the registry authorises (AD-H06, IA-092)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fbi.ai import source_policy
from fbi.people import call_ups

AT = datetime(2026, 11, 21, 16, 0, tzinfo=UTC)


def test_no_official_source_of_the_pinned_registry_permits_call_ups() -> None:
    """Directory v2 (16-nov-2026): no official source is authorised and signed, so none is permitted."""
    policy = source_policy.load(None)
    assert policy is not None
    assert call_ups.permitted_official_domains(policy) == []
    assert call_ups.official_state(0) == "ninguna_fuente_oficial_autorizada"


def test_an_authorised_signed_official_source_that_confirms_call_ups_is_permitted() -> None:
    base = source_policy.load(None)
    assert base is not None
    official = next(s for s in base.by_domain.values() if s.source_type == "oficial")
    authorised = replace(official, state="verificada_autorizada", automated_access="permitido_robots",
                         ai_extraction="sin_reserva_conocida", authority={"convocatorias": {"level": "confirma"}})
    policy = source_policy.SourcePolicy([authorised], [], [authorised.source_id], directory_version="t",
                                        exclusion_version="t", origin="test")
    assert call_ups.permitted_official_domains(policy) == [authorised.domain]
    unsigned = source_policy.SourcePolicy([authorised], [], [], directory_version="t", exclusion_version="t", origin="test")
    assert call_ups.permitted_official_domains(unsigned) == []
    informs = replace(authorised, authority={"convocatorias": {"level": "informa"}})
    only_informs = source_policy.SourcePolicy([informs], [], [informs.source_id], directory_version="t",
                                              exclusion_version="t", origin="test")
    assert call_ups.permitted_official_domains(only_informs) == []
    robots = replace(authorised, automated_access="restringido_robots")
    closed = source_policy.SourcePolicy([robots], [], [robots.source_id], directory_version="t", exclusion_version="t",
                                        origin="test")
    assert call_ups.permitted_official_domains(closed) == []
    assert call_ups.official_state(1) == "sin_comunicado_ingerido"


def test_a_matchs_squad_comes_before_the_providers_list_and_only_when_recent() -> None:
    squad = call_ups.Candidate("plantilla_proveedor", AT - timedelta(days=2), None, 30)
    match = call_ups.Candidate("convocados_ultimo_partido", AT - timedelta(days=40), 9, 23)
    assert call_ups.choose([squad, match], now=AT) == match
    old = replace(match, seen_at=AT - timedelta(days=call_ups.RECENT_DAYS + 1))
    assert call_ups.choose([squad, old], now=AT) == squad
    assert call_ups.choose([replace(squad, players=0)], now=AT) is None
    assert call_ups.choose([], now=AT) is None
