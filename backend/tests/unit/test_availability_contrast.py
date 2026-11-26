"""RP-4.4 (second tranche): how often a report of availability is contradicted by the official match sheet, by level of source
(``fbi.ai.availability_contrast``). The pure parts over reports known by hand: a report of «out» who is on the sheet is contradicted at the level of the source
that decided him; few reports at a level give a rate and no verdict. The database side is ``tests/integration/test_availability_contrast.py``."""

from __future__ import annotations

import pytest

from fbi.ai import availability_contrast as ac


def obs(pid: int, status: str, basis: str, *, on_sheet: bool, started: bool = False, fixture: int = 1) -> ac.Obs:
    return ac.Obs(fixture, pid, status, basis, on_sheet, started)


def test_wilson_is_the_interval_of_a_proportion_and_nothing_for_no_reports() -> None:
    assert ac.wilson(0, 0) is None
    share, low, high = ac.wilson(10, 100) or (0.0, 0.0, 0.0)
    assert share == pytest.approx(0.10) and low == pytest.approx(0.0552, abs=1e-3) and high == pytest.approx(0.1744, abs=1e-3)
    zero = ac.wilson(0, 40)
    assert zero is not None and zero[0] == 0.0 and zero[1] == 0.0 and 0.0 < zero[2] < 0.10, "no hits in 40 still leaves room for a few"
    full = ac.wilson(5, 5)
    assert full is not None and full[2] == 1.0 and full[1] < 1.0


def test_a_report_of_out_on_the_sheet_is_contradicted_at_the_level_that_decided() -> None:
    rows = [obs(1, "baja", "proveedor", on_sheet=True, started=True), obs(2, "baja", "proveedor", on_sheet=False),
            obs(3, "sancionado", "proveedor", on_sheet=False), obs(4, "baja", "un_medio", on_sheet=True), obs(5, "baja", "oficial", on_sheet=False)]
    doc = ac.summarize(rows)
    assert doc["reports"] == 5 and doc["fixtures_with_reports"] == 1
    prov, media, official = doc["contradicted_out"]["proveedor"], doc["contradicted_out"]["un_medio"], doc["contradicted_out"]["oficial"]
    assert (prov["n"], prov["hits"]) == (3, 1) and prov["share"] == pytest.approx(1 / 3)
    assert (media["n"], media["hits"]) == (1, 1) and (official["n"], official["hits"]) == (1, 0)
    assert doc["contradicted_out"]["dos_origenes"]["n"] == 0 and doc["contradicted_out"]["dos_origenes"]["share"] is None


def test_a_level_with_few_reports_has_a_rate_and_no_verdict() -> None:
    few = [obs(i, "baja", "proveedor", on_sheet=False) for i in range(ac.MIN_REPORTS - 1)]
    enough = [*few, obs(99, "baja", "proveedor", on_sheet=True)]
    assert ac.summarize(few)["contradicted_out"]["proveedor"]["enough"] is False
    doc = ac.summarize(enough)
    assert doc["contradicted_out"]["proveedor"]["enough"] is True
    assert "sin veredicto" in "\n".join(ac.lines(ac.summarize(few)))
    assert "sin veredicto" not in "\n".join(ac.lines(doc))


def test_a_doubt_is_counted_by_where_he_ended_and_never_as_right_or_wrong() -> None:
    rows = [obs(1, "duda", "proveedor", on_sheet=True, started=True), obs(2, "duda", "proveedor", on_sheet=True), obs(3, "duda", "proveedor", on_sheet=False),
            obs(4, "duda", "un_medio", on_sheet=False)]
    doc = ac.summarize(rows)
    assert doc["doubt"]["proveedor"] == {"eleven": 1, "bench": 1, "off_sheet": 1} and doc["doubt"]["un_medio"] == {"eleven": 0, "bench": 0, "off_sheet": 1}
    assert doc["contradicted_out"]["proveedor"]["n"] == 0


def test_a_man_a_source_called_available_and_off_the_sheet_is_counted_apart() -> None:
    rows = [obs(1, "disponible", "oficial", on_sheet=True), obs(2, "disponible", "oficial", on_sheet=False)]
    doc = ac.summarize(rows)
    assert (doc["available_but_absent"]["oficial"]["n"], doc["available_but_absent"]["oficial"]["hits"]) == (2, 1)
    assert doc["contradicted_out"]["oficial"]["n"] == 0


def test_the_table_is_in_spanish_and_levels_come_in_order_of_precedence() -> None:
    assert ac.LEVELS == ("oficial", "proveedor", "dos_origenes", "un_medio")
    text = "\n".join(ac.lines(ac.summarize([obs(1, "baja", "oficial", on_sheet=True)])))
    assert "baja/sancionado · oficial: 1 de 1 desmentidos" in text and "baja/sancionado · un medio: sin reportes" in text and "120 min" not in text
    assert "90 min antes del saque" in text
