"""The notification of a budget alert (Plan Maestro IA, phase 0): production's month alert keeps the key and the words it
always had - an alert already sent must not be sent again after the upgrade - while the LAB's, Exa's and the projections
get their own keys, so each envelope alerts once, and say which envelope they are about."""

from __future__ import annotations

from datetime import date

from fbi.notify.service import BUDGET_SCOPES, budget_draft

MONTH = date(2026, 10, 1)


def alert(scope: str, kind: str, threshold: int, spent: float = 150.0, budget: float = 185.0) -> dict[str, object]:
    return {"month": MONTH, "scope": scope, "kind": kind, "threshold": threshold, "spent_usd": spent,
            "budget_usd": budget}


def test_the_month_alert_of_production_keeps_its_key_title_and_words() -> None:
    d = budget_draft(alert("production", "month", 50, 92.5, 185))
    assert (d.kind, d.dedup_key, d.title) == ("ai_budget", "ai_budget:2026-10:50", "Presupuesto de IA: 50 % del mes")
    assert d.body == ("Gastado US$92.50 de US$185.00 en 2026-10. "
                      "El presupuesto diario se adapta para no pasar el tope del mes.")
    assert d.payload == {"threshold": 50}
    spent_all = budget_draft(alert("production", "month", 100, 185, 185))
    assert spent_all.dedup_key == "ai_budget:2026-10:100"
    assert spent_all.body.endswith("La IA se detiene hasta el próximo mes; las reglas siguen.")


def test_every_envelope_and_kind_alerts_under_a_key_of_its_own() -> None:
    keys = {budget_draft(alert(s, k, 95)).dedup_key
            for s in ("production", "lab", "exa") for k in ("month", "projection")}
    assert len(keys) == 6, "six alerts of the same threshold are six notifications, never one swallowing another"
    assert budget_draft(alert("lab", "month", 70)).dedup_key == "ai_budget:2026-10:lab:month:70"
    assert budget_draft(alert("production", "projection", 95)).dedup_key == "ai_budget:2026-10:production:projection:95"


def test_the_alert_of_another_envelope_says_which_one_it_is_and_that_it_only_warns() -> None:
    lab = budget_draft(alert("lab", "month", 85, 12.75, 15))
    assert BUDGET_SCOPES["lab"] in lab.title and "85 %" in lab.title
    assert "US$12.75 de US$15.00" in lab.body and "no se recorta nada" in lab.body
    exa = budget_draft(alert("exa", "month", 100, 35, 35))
    assert "Exa" in exa.title and "producción sigue con el suyo" in exa.body, \
        "an Exa or LAB envelope that runs out leaves production with its own"
    projection = budget_draft(alert("production", "projection", 100, 190, 185))
    assert "proyección llega al 100 %" in projection.title and "no se recorta nada" in projection.body
    assert projection.payload == {"threshold": 100, "scope": "production"}
