"""The chronicle after the official line-up and the why of each selection (IA-116, AD-F03): by template and without a model; the trap
«a player out who ends up starting» corrects the chronicle at its hour without rewriting it; the earlier version stays legible; every
phrase of an explanation traces back to the decision, the chronicle or the update; no betting language."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.chronicle import update as up
from fbi.chronicle import verify
from fbi.lifecycle import machine
from fbi.narrative.job import FORBIDDEN, SYSTEM_TOKENS, fold
from tests.unit.test_chronicle_verify import CLAIMS, GOOD, PLAN, chronicle

SEEN = datetime(2026, 11, 17, 18, 5, tzinfo=UTC)
CHRONICLE: dict[str, Any] = verify.verify(chronicle(GOOD), PLAN, CLAIMS).content or {}
assert CHRONICLE


def lineup(*, home: dict[str, bool], away: dict[str, bool] | None = None, sides: tuple[str, ...] = ("away", "home")) -> up.LineUp:
    players = [up.Player("home", 100 + i, n, s) for i, (n, s) in enumerate(home.items())]
    players += [up.Player("away", 200 + i, n, s) for i, (n, s) in enumerate((away or {}).items())]
    return up.LineUp(31, "sheet:1,2,3", SEEN, SEEN + timedelta(seconds=40), tuple(players), sides)


XI_WITH_HIM = lineup(home={"Mauro Arambarri": True, "David Soria": True}, away={"Sergio Herrera": True})
"""The trap: the provider gave Arambarri as out (the chronicle says so) and he starts."""


def sel(market: str = "1X2", selection: str = "Home", line: float = 0.0, state: str = "retirada",
        reason: str = "alineacion_en_contra") -> up.Selection:
    return up.Selection(501, market, selection, line, state, reason, "retirada", 77)


# ── the paragraph ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_trap_a_player_out_who_ends_up_starting_is_told_and_supersedes_the_chronicle() -> None:
    u = up.paragraph(PLAN, XI_WITH_HIM, CHRONICLE, chronicle_id=9)
    told = u.told["P:absences.home.1"]
    assert "figura como titular" in told["es"] and "starting line-up" in told["en"] and told["facts"] == ["P:absences.home.1", "A:home"]
    assert ("jugadores", 0) in u.superseded, "the chronicle's «Arambarri es baja» is outdated, at the update's hour"
    assert u.content["version"] == up.VERSION and u.content["lineup_at"] == SEEN.isoformat() and u.content["base_chronicle_id"] == 9


def test_the_paragraph_opens_with_the_hour_in_bogota_and_says_which_sides_are_known() -> None:
    both = up.paragraph(PLAN, XI_WITH_HIM, CHRONICLE, chronicle_id=9)
    assert both.content["es"][0] == "Las alineaciones oficiales se conocieron a las 13:05 (hora de Bogotá)."
    one = up.paragraph(PLAN, lineup(home={"Mauro Arambarri": False}, sides=("home",)), CHRONICLE, chronicle_id=9)
    assert one.content["es"][0].startswith("La alineación oficial de Getafe se conoció a las 13:05")
    assert "P:absences.away.1" not in one.told, "a side whose sheet is not known says nothing of its players"


def test_a_player_out_who_is_not_listed_confirms_the_chronicle_and_supersedes_nothing() -> None:
    u = up.paragraph(PLAN, lineup(home={"David Soria": True}, away={"Ante Budimir": False}), CHRONICLE, chronicle_id=9)
    assert "no figura en la alineación oficial, como indicaba" in u.told["P:absences.home.1"]["es"]
    assert ("jugadores", 0) not in u.superseded
    assert "empieza en el banco" in u.told["P:absences.away.1"]["es"] and ("riesgos", 1) in u.superseded


def test_a_name_the_sheet_spells_another_way_is_never_guessed() -> None:
    u = up.paragraph(PLAN, lineup(home={"M. Arambarri": True}), CHRONICLE, chronicle_id=9)
    assert "P:absences.home.1" in u.content["unplaced"] and "P:absences.home.1" not in u.told


def test_the_earlier_version_stays_legible_as_it_was() -> None:
    u = up.paragraph(PLAN, XI_WITH_HIM, CHRONICLE, chronicle_id=9)
    new = up.content_of(CHRONICLE, u, [])
    assert new["es"] == CHRONICLE["es"] and new["en"] == CHRONICLE["en"], "the update is added, never written over the chronicle"
    assert {"section": "jugadores", "index": 0} in new["actualizacion"]["superseded"]
    assert {"section": "riesgos", "index": 1} in new["actualizacion"]["superseded"], "Budimir, in doubt, is not listed"
    alone = up.content_of(None, u, [])
    assert "es" not in alone and alone["actualizacion"]["es"], "an abstained chronicle still gets its paragraph"


# ── the why of a selection ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_why_comes_from_the_decision_and_cites_the_chronicle_by_index_or_the_update() -> None:
    u = up.paragraph(PLAN, XI_WITH_HIM, CHRONICLE, chronicle_id=9)
    w = up.why(sel(), PLAN, CHRONICLE, u, chronicle_id=9, at=SEEN)
    first = w["phrases"][0]
    assert first["origin"] == {"kind": "decision", "verdict_id": 501, "decision_id": 77, "state": "retirada", "reason": "alineacion_en_contra"}
    assert first["es"] == ("Tras la alineación oficial, «victoria de Getafe» queda retirada: la alineación oficial deja fuera a jugadores "
                           "de los que depende.")
    kinds = [p["origin"]["kind"] for p in w["phrases"][1:]]
    assert kinds and set(kinds) <= {"chronicle", "update"} and len(kinds) <= up.MAX_CITED
    for p in w["phrases"][1:]:
        o = p["origin"]
        if o["kind"] == "chronicle":
            assert p["es"] == CHRONICLE["es"][o["section"]][o["index"]]["text"], "copied as the verifier let it stand"
    assert all("baja" not in p["es"] or p["origin"]["kind"] != "chronicle" for p in w["phrases"]), \
        "the outdated «es baja» is never cited: the explanation cannot contradict the line-up"
    assert up.without_origin([w]) == []


def test_a_phrase_without_its_origin_is_found() -> None:
    assert up.without_origin([{"phrases": [{"es": "x"}, {"es": "y", "origin": {"kind": "model"}}]}]) == ["x", "y"]


def test_the_why_of_a_goals_market_cites_only_what_is_pertinent_to_goals() -> None:
    u = up.paragraph(PLAN, XI_WITH_HIM, CHRONICLE, chronicle_id=9)
    w = up.why(sel("OU", "Over", 2.5, "confirmada_sombra", "cumple_todo"), PLAN, CHRONICLE, u, chronicle_id=9, at=SEEN)
    assert "«más de 2,5 goles» queda confirmada en la sombra: cumple todos los criterios" in w["phrases"][0]["es"]
    by = PLAN.by_id()
    for p in w["phrases"][1:]:
        if p["origin"]["kind"] == "chronicle":
            facts = CHRONICLE["es"][p["origin"]["section"]][p["origin"]["index"]]["facts"]
            assert any("OU" in by[f].markets for f in facts)


def test_every_reason_e3_can_give_has_its_words() -> None:
    reasons = {r for s in ("confirmada_sombra", "pendiente_alineaciones", "retirada", "en_evaluacion") for r in machine.REASONS[s]}
    assert reasons - set(up.REASON_WORDS) <= {"autorizada_por_dueno", "sin_motivo_conocido"}


def test_no_template_carries_betting_language_certainty_or_a_code() -> None:
    pairs = [*up.TEMPLATES.values(), *up.STATE_WORDS.values(), *up.REASON_WORDS.values(), up.UNKNOWN_REASON]
    pairs += [up.label(sel(m, x), PLAN) for m, x in (("1X2", "Home"), ("OU", "Under"), ("BTTS", "Yes"), ("DC", "1X"), ("AH", "Away"))]
    for es, en in pairs:
        for lang, t in (("es", es), ("en", en)):
            text = t.format(player="Ana", team="Getafe")
            assert FORBIDDEN[lang].search(fold(text)) is None, text
            assert SYSTEM_TOKENS.search(text) is None, text


def test_no_model_is_called_here() -> None:
    tree = ast.parse(inspect.getsource(up))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | {
        n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {m for m in imported if m.startswith(("fbi.ai", "httpx", "anthropic"))}, imported
