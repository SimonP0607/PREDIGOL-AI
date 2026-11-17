"""Availability as a state with its source and date, never a medical detail (AD-H05, IA-091)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from fbi.people import availability as av

AT = datetime(2026, 11, 21, 16, 0, tzinfo=UTC)


@pytest.mark.parametrize(("kind", "reason", "status"), [
    ("Missing Fixture", "Knee Injury", "baja"),
    ("Missing Fixture", "Inactive", "baja"),
    ("Missing Fixture", "Red Card", "sancionado"),
    ("Missing Fixture", "Yellow Cards", "sancionado"),
    ("Missing Fixture", "Suspended", "sancionado"),
    ("Questionable", "Muscle Injury", "duda"),
    ("Something Else", "Knee Injury", None),
    (None, None, None),
])
def test_the_providers_report_gives_a_state(kind: str | None, reason: str | None, status: str | None) -> None:
    assert av.provider_status(kind, reason) == status


@pytest.mark.parametrize(("kind", "assertion", "status"), [
    ("injury", "out", "baja"), ("suspension", "out", "sancionado"), ("doubtful", None, "duda"),
    ("injury", "doubtful", "duda"), ("injury", "available", "disponible"), ("injury", "info", None),
    ("lineup", "starts", None),
])
def test_a_fact_of_the_press_gives_a_state(kind: str, assertion: str | None, status: str | None) -> None:
    assert av.press_status(kind, assertion) == status


@pytest.mark.parametrize(("status", "tier", "basis"), [
    ("CONFIRMED", "official", "oficial"), ("PROBABLE", "club", "oficial"), ("CONFIRMED", "media", "dos_origenes"),
    ("PROBABLE", "media", "un_medio"), ("RUMOR", "official", None), ("CONTRADICTORY", "media", None),
    ("OUTDATED", "media", None), ("CONFIRMED", "provider", None),
])
def test_a_rumour_a_contradiction_or_an_old_fact_never_counts(status: str, tier: str, basis: str | None) -> None:
    assert av.press_basis(status, tier) == basis


def r(status: str, basis: str, hours: int, *, implied: bool = False) -> av.Report:
    return av.Report(7, "J. Ejemplo", status, basis, "s", AT - timedelta(hours=hours), 1, implied=implied)  # type: ignore[arg-type]


def test_precedence_official_then_provider_then_two_outlets_then_one() -> None:
    assert av.resolve([r("duda", "un_medio", 1), r("baja", "proveedor", 5)])[7].status == "baja"
    assert av.resolve([r("disponible", "oficial", 9), r("baja", "proveedor", 1)])[7].status == "disponible"
    assert av.resolve([r("baja", "dos_origenes", 1), r("duda", "un_medio", 0)])[7].status == "baja"


def test_between_two_of_the_same_level_the_newer_decides() -> None:
    assert av.resolve([r("duda", "un_medio", 5), r("baja", "un_medio", 1)])[7].status == "baja"


def test_a_listing_beats_the_implied_available_of_a_later_check() -> None:
    """The season's report was asked for after he was listed and still lists him: he is out, not «disponible»."""
    states = av.resolve([r("disponible", "proveedor", 1, implied=True), r("sancionado", "proveedor", 4)])
    assert states[7].status == "sancionado"


def test_not_knowing_is_not_available() -> None:
    assert av.available_by_default([(7, "J. Ejemplo")], checked_at=None, fixture_id=1) == []
    [one] = av.available_by_default([(7, "J. Ejemplo")], checked_at=AT, fixture_id=1)
    assert (one.status, one.basis, one.implied) == ("disponible", "proveedor", True)


def test_nothing_medical_survives_a_report() -> None:
    """The reason (a diagnosis) is read to tell a suspension from an injury and dropped: no field can carry it."""
    rows = [{"provider_player_id": 7, "player_name": "J. Ejemplo", "absence_type": "Missing Fixture",
             "reason": "Rotura de ligamento cruzado", "fetched_at": AT}]
    [report] = av.provider_reports(rows, fixture_id=1)
    assert "Rotura" not in repr(report) and report.status == "baja"
    press = [{"provider_player_id": 7, "kind": "injury", "assertion": "out", "status": "CONFIRMED", "source_tier": "media",
              "source_name": "Diario Ejemplo", "known_at": AT, "fixture_id": 1, "claim": "seis meses de baja"}]
    [fact] = av.press_reports(press)
    assert "seis meses" not in repr(fact) and fact.basis == "dos_origenes"
    for cls in (av.Report, av.State):
        names = {f.name for f in dataclasses.fields(cls)}
        assert not names & {"reason", "claim", "diagnosis", "type", "absence_type", "end_date", "return_date"}
