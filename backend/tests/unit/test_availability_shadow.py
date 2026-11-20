"""PM-02-06: what a discrepancy is (pure) and the switch of the shadow comparison."""

from __future__ import annotations

from fbi.coverage import shadow


def test_a_discrepancy_is_a_subject_the_two_sides_read_differently() -> None:
    found = shadow.compare(7, "cuotas", {"a": True, "b": True, "c": False}, {"a": True, "b": False, "d": True},
                           reasons={"b": "menos_de_3_casas"})
    assert [(f.subject, f.shown, f.matrix, f.reason) for f in found] == [
        ("b", True, False, "menos_de_3_casas"), ("d", False, True, "solo_matriz")]
    assert shadow.compare(7, "x", {"a": True}, {"a": True}) == []


def test_the_report_counts_by_module_and_reason() -> None:
    r = shadow.ShadowReport()
    r.add(shadow.compare(1, "cuotas", {"a": True, "b": True}, {}, reasons={"a": "menos_de_3_casas"}))
    assert r.findings == 2 and r.by_module == {"cuotas": 2}
    assert r.as_json()["by_reason"] == {"cuotas:menos_de_3_casas": 1, "cuotas:solo_modulo": 1}


def test_a_subject_fits_the_table() -> None:
    assert shadow._subject("corners_over_under.FT.match:Over:9.5") == "corners_over_under.FT.match:Over:9.5"
    assert shadow._subject("Más/Menos 2.5") == "M_s_Menos_2.5"
    assert len(shadow._subject("x" * 300)) == 96


def test_the_switch_is_on_unless_it_says_off() -> None:
    assert shadow.mode({}) == "on"
    assert shadow.mode({shadow.SWITCH: "0"}) == "off"
    assert shadow.SAMPLE == 500
