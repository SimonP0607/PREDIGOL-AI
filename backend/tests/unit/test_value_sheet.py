"""RP-12.1: the value sheet per AI process (value-sheet-v1) - useful unit written in advance, costs from the ledger's report, nothing decided."""

from __future__ import annotations

from typing import Any

from fbi.ai import value_sheet as vs


def cap(key: str, usd: str, calls: int) -> dict[str, Any]:
    return {"key": key, "spent_usd": usd, "calls": calls}


def report(caps: list[dict[str, Any]], ledger: str, loose: str = "0.00") -> dict[str, Any]:
    return {"capabilities": caps, "total": {"ledger_usd": ledger}, "unattributed": {"usd": loose}}


def r4(selections: int = 601, common: int = 600, agree_reject: int = 540, kept_settled: int = 40, rejected_settled: int = 12) -> dict[str, Any]:
    return {"engines": {"llm": {"selections": selections, "kept": {"settled": kept_settled, "roi_pct": 3.0},
                               "rejected": {"settled": rejected_settled, "roi_pct": -8.0}}},
            "pairs": {"rules_vs_llm": {"common": common, "agree_on_reject_or_not": {"counted": agree_reject, "cases": common}}}}


COUNTS = vs.Counts(fixtures=692, fixtures_with_web_facts=269, web_facts=1000, web_facts_confirmed=200, web_facts_probable=300,
                   chronicles_written=100, chronicles_valid=90)
CAPS = [cap("production.review", "26.20", 2000), cap("research.search", "8.00", 700), cap("research.extraction", "1.00", 900),
        cap("production.brief", "6.00", 2000), cap("chronicles.chronicle", "2.00", 100), cap("narrator.pick_why", "0.23", 5)]


def doc() -> dict[str, Any]:
    return vs.sheet(report(CAPS, "43.43"), r4(), COUNTS, days=7)


def by_key(d: dict[str, Any], key: str) -> dict[str, Any]:
    return next(x for x in d["processes"] if x["key"] == key)


def test_every_process_has_a_unit_and_a_useful_unit_or_the_reason_it_has_none() -> None:
    assert len({p.key for p in vs.PROCESSES}) == len(vs.PROCESSES)
    for p in vs.PROCESSES:
        assert p.unit and p.capabilities
        assert (p.useful is None) == (p.why_not_useful is not None), p.key


def test_the_review_line_counts_what_it_changed_and_what_it_rejected_against_what_it_kept() -> None:
    x = by_key(doc(), "revision_candidatos")
    assert (x["cost_usd"], x["units"], x["useful"]) == ("26.20", 601, 60)
    assert x["cost_per_unit_usd"] == "0.044" and x["cost_per_useful_usd"] == "0.437"
    assert x["useful_share"]["cases"] == 600 and x["useful_share"]["counted"] == 60 and x["useful_share"]["ci95_wilson_pct"]
    assert x["rejected_vs_kept"]["rejected_settled"] == 12 and x["rejected_vs_kept"]["kept_settled"] == 40


def test_research_adds_search_and_extraction_and_counts_confirmed_facts_per_match() -> None:
    x = by_key(doc(), "busqueda_web")
    assert x["cost_usd"] == "9.00" and x["calls"] == 1600 and (x["units"], x["useful"]) == (269, 200)
    assert x["fixtures_covered"]["counted"] == 269 and x["fixtures_covered"]["cases"] == 692
    assert x["cost_per_useful_usd"] == "0.045" and x["web_facts"]["probable"] == 300


def test_a_process_without_a_measurable_unit_says_so_instead_of_inventing_one() -> None:
    d = doc()
    x = by_key(d, "lectura_partido")
    assert x["state"] == vs.NO_USEFUL_UNIT and x["useful"] is None and x["cost_per_useful_usd"] is None and x["why_not_useful"]
    assert {"lectura_partido", "deliberacion_sombra", "aprendizaje_y_postmortem", "banco_de_pruebas"} <= set(d["without_useful_unit"])


def test_what_no_process_claims_goes_to_otros_and_the_total_reconciles_with_the_ledger() -> None:
    d = doc()
    assert d["otros"] == {"capabilities": ["narrator.pick_why"], "cost_usd": "0.23"}
    assert d["total"]["sheet_usd"] == "43.43" and d["total"]["reconciles"] is True
    off = vs.sheet(report(CAPS, "50.00"), r4(), COUNTS, days=7)
    assert off["total"]["reconciles"] is False


def test_loose_spend_is_added_so_the_sheet_never_hides_a_row_no_capability_claims() -> None:
    d = vs.sheet(report(CAPS, "44.43", loose="1.00"), r4(), COUNTS, days=30)
    assert d["sin_capacidad_usd"] == "1.00" and d["total"]["sheet_usd"] == "44.43" and d["total"]["reconciles"] is True


def test_an_empty_window_is_without_sample_not_a_measurement() -> None:
    d = vs.sheet(report([], "0"), {}, vs.Counts(), days=7)
    x = by_key(d, "revision_candidatos")
    assert x["state"] == "sin_muestra" and x["cost_per_unit_usd"] is None and x["useful_share"]["cases"] == 0
    assert d["total"]["reconciles"] is None


def test_it_decides_nothing_and_prints_each_rate_with_its_cases() -> None:
    d = doc()
    assert d["decides"] is False and d["version"] == "value-sheet-v1"
    text = "\n".join(vs.lines(d))
    assert "no decide nada" in text and "60/600" in text and "IC95" in text and "sin unidad útil medible" in text


