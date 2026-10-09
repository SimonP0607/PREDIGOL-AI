"""What the owner reads after a day of learning is plain Spanish (9 Oct 2026, the first day on the server).

The narratives, notes and lessons of that day said "Coincido con la clase CONTEXT_ERROR", "la dejó en DOWNGRADE",
"(1X2 Draw)", "quedó en estado OUTDATED", "DATOS: ...", "Según la nota 10, ...", "provider: 24 confirmadas", and two
narratives were cut mid-word at 900 characters. These are the sentences as they were written that day.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fbi.ai.learning import notes_for
from fbi.ai.pick_postmortem import _who
from fbi.ai.text import CODE, fit, narrative_of, selection_es, shown, words


def test_codes_a_model_copied_into_its_prose_become_words() -> None:
    assert words("Coincido con la clase CONTEXT_ERROR, porque la ventaja dependía de un solo modelo.") == \
        "Coincido con la clase «error de contexto», porque la ventaja dependía de un solo modelo."
    assert words("la revisión la dejó en DOWNGRADE; el partido terminó 0-0") == \
        "la revisión la dejó en «cautela»; el partido terminó 0-0"
    assert words("El servidor marca EXECUTION_ERROR por titulares ausentes") == \
        "El servidor marca «error de ejecución» por titulares ausentes"
    assert words("la decisión fue RECHAZAR, sin señales activas") == "la decisión fue «rechazar», sin señales activas"
    assert words("Estoy de acuerdo con la clasificación MARKET_ERROR: el mercado") == \
        "Estoy de acuerdo con la clasificación «el mercado sabía algo»: el mercado"


def test_a_code_in_brackets_after_its_own_word_is_dropped_and_selections_are_named() -> None:
    assert words("La evidencia de bajas quedó desactualizada (OUTDATED) y no debe usarse.") == \
        "La evidencia de bajas quedó desactualizada y no debe usarse."
    assert words("Se seleccionó el empate (1X2 Draw) del Fluminense - Coritiba") == \
        "Se seleccionó el empate (1X2 empate) del Fluminense - Coritiba"
    assert words("Habrían ganado: Ceara - Criciuma (1X2 Home).") == "Habrían ganado: Ceara - Criciuma (1X2 local)."


def test_labels_and_note_numbers_are_not_for_the_owner() -> None:
    assert words("DATOS: El partido terminó 1-0 para el local.") == "El partido terminó 1-0 para el local."
    assert words("Según la nota 10, hubo titulares habituales ausentes sin reporte.") == \
        "Hubo titulares habituales ausentes sin reporte."
    assert words("La nota 8 indica que una pérdida no es un patrón; conviene seguir acumulando muestra.") == \
        "Una pérdida no es un patrón; conviene seguir acumulando muestra."
    assert words("Merece vigilarse (notas 13 y 14).") == "Merece vigilarse."
    assert words("provider: 24 confirmadas y 2 desmentidas por la alineación.") == \
        "Proveedor de datos: 24 confirmadas y 2 desmentidas por la alineación."


def test_plain_text_is_left_alone() -> None:
    for text in ("Sin cambios.", "Un rumor probable, confirmado después.", "La cautela fue correcta.",
                 "Rechazar fue lo correcto en el 1X2."):
        assert words(text) == text


def test_a_stored_text_is_shown_in_words_line_by_line() -> None:
    stored = ("Coincido con la clase NORMAL_VARIANCE.\n- Vigilar el DOWNGRADE de cuotas altas.\n"
              "- La evidencia quedó en estado OUTDATED.")
    out = shown(stored)
    assert out is not None and CODE.search(out) is None
    assert out.split("\n")[0] == "Coincido con la clase «varianza normal»."
    assert out.split("\n")[2] == "- La evidencia quedó en estado «desactualizada»."


def test_a_long_narrative_ends_on_a_full_sentence() -> None:
    summary = ("Se apostó al empate a cuota 3.64. " * 30) + "No coincido con la clase: me inclino por varianza normal, " \
        "con una ventaja pequeña"
    assert len(summary) > 900
    read = narrative_of({"summary": summary, "agrees_with_class": False, "lessons": []}, max_lessons=2)
    assert read is not None
    text = read[0]
    assert len(text) <= 900 and text.endswith(".")
    assert not text.endswith("co"), "9 Oct 2026: a narrative ended 'varianza normal, co'"
    assert fit("palabra " * 200, 100).endswith("…")


def test_selections_and_the_days_notes_are_in_spanish() -> None:
    assert selection_es("1X2", "Home", Decimal(0)) == "1X2 local"
    assert selection_es("OU", "Over", Decimal("2.50")) == "OU más de 2.5"
    assert selection_es("AH", "Away", Decimal("-0.25")) == "AH visitante -0.25"

    def pm(i: int, verdict: str, **over: Any) -> dict[str, Any]:
        base = {"id": i, "fixture_id": i, "market_key": "1X2", "selection": "Home", "line": Decimal(0), "roles": [],
                "decision": {"caution": "DOWNGRADE", "rejected": "REJECT"}.get(verdict.split("_")[0]),
                "settled": "loss" if verdict.endswith(("lost", "correctly")) else "win", "verdict": verdict,
                "classification": None, "odds": Decimal("2.0"), "close_odds": None, "clv": None, "p_model": 0.5,
                "p_market": 0.45, "answers": {"model": {"data": {"p_close": 0.456}}}, "evidence": {},
                "match": f"M{i}"}
        return base | over

    rows = [pm(1, "rejected_would_have_won"),
            pm(2, "caution_lost", answers={"model": {"data": {"p_close": 0.456}},
                                          "key_absence": {"answer": "sí", "detail": "A. Canobbio (local)"}})]
    checks = [{"id": 9, "tier": "provider", "verdict": "right"}, {"id": 9, "tier": "provider", "verdict": "wrong"}]
    notes = {n.kind: n for n in notes_for(rows, checks, [])}
    assert "M1 (1X2 local)" in notes["rejected"].body
    assert notes["injuries"].title.startswith("1 pérdida con"), "not '1 pérdidas'"
    assert notes["news"].body == "El proveedor de datos: 1 confirmadas y 1 desmentidas por la alineación."
    assert "+4,4 puntos" in notes["model"].body, "a decimal comma"


def test_a_report_from_the_provider_names_the_player_not_its_english_reason() -> None:
    assert _who({"tier": "provider", "claim": "Guga (Fluminense): Missing Fixture - Inactive"}) == "Guga (Fluminense)"
    assert _who({"tier": "media", "claim": "Arrieta no jugaría: molestia muscular"}) == \
        "Arrieta no jugaría: molestia muscular"


def test_a_narrative_stored_cut_mid_word_is_shown_up_to_its_last_whole_word() -> None:
    from fbi.ai.text import DISAGREES, OLD_CUT

    head = "La cuota no se movió y el resultado es compatible con varianza normal. " * 20
    cut = (head + "No coincido con la clase: me inclino por varianza normal, con todo")[:OLD_CUT]
    assert len(cut) == OLD_CUT
    stored = cut + " (el revisor no comparte la clase del servidor)\n- Vigilar las cuotas altas."
    first = (shown(stored) or "").split("\n")[0]
    assert first.endswith("…" + DISAGREES) and not first.endswith(" co" + DISAGREES)
    whole = "Una frase completa."
    assert shown(whole) == whole


def test_what_evolucion_lists_as_findings_is_said_in_spanish() -> None:
    from fbi.api.services.ai_layer import UNREPORTED, finding_text

    assert finding_text({"kind": "news_signal", "hypothesis": UNREPORTED,
                         "evidence": {"side": "away", "player": "C. Velarde"}}) == \
        "Un titular habitual faltó sin que nadie lo reportara: C. Velarde (visitante)."
    assert finding_text({"kind": "context_error", "hypothesis": "Guga (Fluminense): Missing Fixture - Inactive",
                         "evidence": {"tier": "provider"}}) == "Reportado fuera y fue titular: Guga (Fluminense)."
    assert finding_text({"kind": "team_pattern", "hypothesis": "Los reportes de bajas de nivel 'provider' deberían "
                         "pesar menos.", "evidence": {}}) == \
        "Los reportes de bajas de nivel «el proveedor de datos» deberían pesar menos."
    assert finding_text({"kind": "model_failure", "hypothesis": None, "evidence": {}}) is None
