"""Stock phrases and repetitions (IA-117, AD-F04, ``repeat-check-v1``): the masked template, the closed list of formulas Doc 1 counted, the
share of a template in the recent chronicles, the same sentence as the team's previous chronicle, the mandatory facts exempt, ``shadow``
measures and drops nothing, ``on`` drops like a sentence without support and records why, ``off`` does nothing."""

from __future__ import annotations

from typing import Any

from fbi.chronicle import repetition as rp
from fbi.chronicle import verify
from tests.unit.test_chronicle_verify import CLAIMS, GOOD, PLAN, chronicle

VERDICT = verify.verify(chronicle(GOOD), PLAN, CLAIMS)
FORM = GOOD["como_llega"][1][0]
"""«El Getafe solo ha sacado 1 empate en sus últimos 5 partidos, con 4 derrotas.» (not mandatory)"""
MANDATORY = GOOD["que_se_juega"][0][0]
"""The engine's «nada en juego» (mandatory)."""
LINEUPS = GOOD["que_falta"][0][0]


def corpus_with(*texts: str, size: int = 25, previous: dict[str, list[str]] | None = None) -> rp.Corpus:
    rows = [{"metrics": {"repetition": {"templates": [rp.key(rp.mask(t, PLAN.names)) for t in texts]}}} for _ in range(size)]
    prev = {side: {"id": 900 + i, "metrics": {"repetition": {"exact": [rp.key(rp.exact(t)) for t in said]}}}
            for i, (side, said) in enumerate((previous or {}).items())}
    return rp.corpus_of(rows, prev)


def report(v: verify.Verdict) -> dict[str, Any]:
    out: dict[str, Any] = v.metrics["repetition"]
    return out


# ── the keys of a sentence ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_template_masks_names_numbers_and_figures_and_the_exact_key_keeps_them() -> None:
    a = rp.mask("El Getafe suma 10 puntos en 5 partidos.", ["Getafe"])
    b = rp.mask("El Osasuna suma 31 puntos en 12 partidos.", ["Osasuna"])
    assert a == b == "el <n> suma # puntos en # partidos"
    assert rp.exact("El Getafe suma 10 puntos.") != rp.exact("El Getafe suma 11 puntos."), "numbers are what changed"
    assert "<cifra>" in rp.mask("PrediGol da un 31 % [cifra forecast-v2 0123456789ab].", [])


def test_the_formulas_doc_1_counted_are_recognised_in_both_languages() -> None:
    assert rp.generic_formula("Las alineaciones oficiales aún no se conocen.", "") is not None
    assert rp.generic_formula("Alineaciones no confirmadas.", "") is not None
    assert rp.generic_formula("Sin datos suficientes para valorar al Getafe.", "") is not None
    assert rp.generic_formula("", "The official line-ups are not out yet.") is not None
    assert rp.generic_formula("Según nuestro modelo el partido está igualado.", "") is not None
    assert rp.generic_formula("El Getafe suma 10 puntos.", "Getafe have 10 points.") is None


# ── shadow measures, on drops, off nothing ──────────────────────────────────────────────────────────────────────────────────

def test_the_switch_is_shadow_by_default_and_reads_only_its_three_words() -> None:
    assert rp.mode({}) == "shadow" and rp.mode({rp.SWITCH: " ON "}) == "on" and rp.mode({rp.SWITCH: "off"}) == "off"
    assert rp.mode({rp.SWITCH: "enforce"}) == "shadow"


def test_shadow_measures_every_sentence_and_drops_nothing() -> None:
    v, version = rp.apply(VERDICT, PLAN, corpus_with(FORM), mode_word="shadow")
    assert version is None and v.content == VERDICT.content and v.dropped == VERDICT.dropped
    rep = report(v)
    assert rep["version"] == rp.VERSION and rep["mode"] == "shadow" and rep["dropped"] == 0
    assert rep["sentences"] == VERDICT.metrics["kept"] and rep["corpus"] == 25
    assert [d["where"] for d in rep["would_drop"]] == ["como_llega[1]"]
    assert rep["generic"] >= 2, "the template carried by every recent chronicle, and the line-ups' formula"
    assert rep["thresholds"]["signed"] is False
    assert len(rep["templates"]) == rep["sentences"] and rep["exact"]


def test_on_drops_the_stock_sentence_like_one_without_support_and_says_why() -> None:
    v, version = rp.apply(VERDICT, PLAN, corpus_with(FORM), mode_word="on")
    assert version == rp.VERIFY_WITH_RULE == "chronicle-verify-v2"
    assert v.content is not None and [s["text"] for s in v.content["es"]["como_llega"]] == [GOOD["como_llega"][0][0]]
    assert len(v.content["en"]["como_llega"]) == 1, "the English goes with the Spanish"
    dropped = [d for d in v.dropped if d.where == "como_llega[1]"]
    assert dropped and dropped[0].why.startswith("coletilla") and v.status == "partial"
    assert v.metrics["kept"] == VERDICT.metrics["kept"] - 1 and report(v)["dropped"] == 1


def test_a_mandatory_fact_is_never_dropped_for_repetition() -> None:
    v, _ = rp.apply(VERDICT, PLAN, corpus_with(MANDATORY), mode_word="on")
    assert v.content == VERDICT.content and report(v)["exempt"] == 1 and report(v)["would_drop"] == []


def test_the_same_sentence_as_the_teams_previous_chronicle_is_a_repetition() -> None:
    v, _ = rp.apply(VERDICT, PLAN, corpus_with(size=0, previous={"home": [FORM]}), mode_word="shadow")
    rep = report(v)
    assert rep["repeated"] == 1 and rep["repeat_rate"] is not None and rep["previous_chronicles"] == {"home": 900}
    assert rep["would_drop"][0]["why"].startswith("repetida")
    other_numbers = FORM.replace("1 empate", "2 empates")
    v2, _ = rp.apply(VERDICT, PLAN, corpus_with(size=0, previous={"home": [other_numbers]}), mode_word="shadow")
    assert report(v2)["repeated"] == 0, "a sentence with other numbers tells something new"


def test_a_small_corpus_measures_no_share_and_off_does_nothing() -> None:
    v, _ = rp.apply(VERDICT, PLAN, corpus_with(FORM, size=rp.MIN_CORPUS - 1), mode_word="on")
    assert report(v)["would_drop"] == [] and v.content == VERDICT.content
    same, version = rp.apply(VERDICT, PLAN, corpus_with(FORM), mode_word="off")
    assert same is VERDICT and version is None


def test_when_on_drops_every_sentence_the_chronicle_abstains() -> None:
    every = [t[0] for section in GOOD.values() for t in section]
    plain = verify.verify(chronicle({"como_llega": GOOD["como_llega"]}), PLAN, CLAIMS)
    v, _ = rp.apply(plain, PLAN, corpus_with(*every), mode_word="on")
    assert v.content is None and v.status == "rejected" and v.abstention == "VERIFICACION_VACIA"


def test_a_row_the_rule_never_measured_is_not_in_the_corpus() -> None:
    c = rp.corpus_of([{"metrics": {}}, {"metrics": {"repetition": {"templates": ["a"]}}}, {"metrics": None}])
    assert c.size == 1 and c.templates == {"a": 1}


def test_opening_with_what_changed_is_measured_against_the_previous_plan() -> None:
    assert rp.opens_with_change(VERDICT.content or {}, PLAN) is None, "no previous plan"
    from fbi.chronicle import plan as cp
    from tests.unit.test_chronicle_plan import inp, reading
    from tests.unit.test_chronicle_verify import FIG

    seen = cp.build(inp(scenarios=reading(away_no_objective=True), figures=(FIG,)))
    old = frozenset(f.key for f in seen.facts)
    again = cp.build(inp(scenarios=reading(away_no_objective=True), figures=(FIG,), previous=old))
    assert rp.opens_with_change(VERDICT.content or {}, again) is False
    fresh = cp.build(inp(scenarios=reading(away_no_objective=True), figures=(FIG,), previous=frozenset({"zzz"})))
    assert rp.opens_with_change(VERDICT.content or {}, fresh) is True
