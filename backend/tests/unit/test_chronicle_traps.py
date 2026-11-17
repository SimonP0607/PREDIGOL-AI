"""The fixed bank of trap matches of the single chronicle (IA-118, AD-F06), run in CI: ``tests/fixtures/chronicle_traps.json``.

A pull request that makes the chronicle claim what its facts do not authorise fails here: for every trap the content plan must keep out what
the engine did not prove, the verifier must drop every sentence the facts do not authorise and let stand the ones they do, and - for the
player out who ends up starting - the update after the line-up must correct the chronicle at its hour, the why of a selection must not
repeat the outdated absence, and the review after the match must mark the chronicle's claim as contradicted."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from fbi.chronicle import plan as cp
from fbi.chronicle import review, review_v2, update, verify
from tests.unit.test_chronicle_plan import AWAY_ID, HOME_ID, inp, objective, reading
from tests.unit.test_chronicle_verify import CLAIMS

BANK = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "chronicle_traps.json").read_text(encoding="utf-8"))
TRAPS = {t["id"]: t for t in BANK["traps"]}


def plan_of(trap: dict[str, Any]) -> cp.ContentPlan:
    home = [objective(o["objetivo"], o["estado"], proved=o["proved"]) for o in trap.get("home_objectives", [])]
    away = [objective(o["objetivo"], o["estado"], proved=o["proved"]) for o in trap.get("away_objectives", [])]
    return cp.build(inp(scenarios=reading(home=home, away=away)))


def one(p: cp.ContentPlan, s: dict[str, Any]) -> verify.Verdict:
    other: dict[str, list[dict[str, Any]]] = {k: [] for k in cp.SECTIONS}
    es = {**other, s["section"]: [{"text": s["es"], "facts": s["facts"]}]}
    en = {**other, s["section"]: [{"text": s["en"], "facts": s["facts"]}]}
    return verify.verify(verify.ChronicleOut.model_validate({"es": es, "en": en}), p, CLAIMS)


def test_the_bank_is_closed_and_has_the_three_traps_of_the_plan() -> None:
    assert BANK["version"] == "chronicle-traps-v1"
    assert {"clasificacion_por_diferencia_de_goles", "lesionado_que_acaba_titular", "rumor_de_una_sola_fuente"} <= set(TRAPS)
    for t in BANK["traps"]:
        assert t["what"] and t["sentences"] and {s["must"] for s in t["sentences"]} == {"stand", "drop"}, t["id"]


@pytest.mark.parametrize("trap_id", sorted(TRAPS))
def test_each_sentence_of_each_trap_stands_or_is_dropped_as_the_bank_says(trap_id: str) -> None:
    trap = TRAPS[trap_id]
    p = plan_of(trap)
    for ref, reason in (trap.get("plan_must_exclude") or {}).items():
        assert {e.ref: e.reason for e in p.excluded}.get(ref) == reason, ref
    assert not set(trap.get("plan_must_not_allow") or []) & set(p.allowed_classes)
    assert cp.unsupported_high_risk(p) == []
    for s in trap["sentences"]:
        v = one(p, s)
        if s["must"] == "stand":
            assert v.status == "ok", (trap_id, s["es"], [d.as_json() for d in v.dropped])
        else:
            assert v.content is None and v.dropped, (trap_id, s["es"])
            reasons = " | ".join(d.why for d in v.dropped)
            if s.get("why"):
                assert s["why"].lower() in reasons.lower(), (trap_id, s["es"], reasons)


def test_the_player_out_who_ends_up_starting_is_corrected_explained_and_reviewed() -> None:
    trap = TRAPS["lesionado_que_acaba_titular"]
    p = plan_of(trap)
    kept = one(p, trap["sentences"][0])
    assert kept.content is not None
    base = {"home": 100, "away": 200}
    players = [update.Player(side, base[side] + i, name, starts) for side in ("home", "away")
               for i, (name, starts) in enumerate(trap["lineup"][side].items())]
    seen = p.at + timedelta(hours=1)
    line_up = update.LineUp(41, "sheet:x", seen, seen + timedelta(seconds=30), tuple(players), ("away", "home"))
    u = update.paragraph(p, line_up, kept.content, chronicle_id=1)
    expect = trap["expect"]
    assert any(s["kind"] == expect["update_kind"] for s in u.content["sentences"])
    assert tuple(expect["superseded"]) in u.superseded
    sel = update.Selection(9, "1X2", "Away", 0.0, "confirmada_sombra", "cumple_todo", "sigue_igual", 3)
    why = update.why(sel, p, kept.content, u, chronicle_id=1, at=seen)
    assert update.without_origin([why]) == []
    assert not [x for x in why["phrases"] if x["origin"]["kind"] == "chronicle" and "baja" in x["es"]]
    lineups = [{"team_side": s, "provider_player_id": base[s] + i, "player_name": n, "is_starter": st}
               for s in ("home", "away") for i, (n, st) in enumerate(trap["lineup"][s].items())]
    stats = [{"team_side": s, "provider_player_id": base[s] + i, "player_name": n, "minutes": m}
             for s in ("home", "away") for i, (n, m) in enumerate(trap["played"][s].items())]
    full = update.content_of(kept.content, u, [why])
    items = review_v2.review_items(full, p, written_at=p.at + timedelta(minutes=1), squad=review.squad_of(lineups, stats), evidence={},
                                   team_ids={"home": HOME_ID, "away": AWAY_ID}, after=None, result=(1, 1))
    said = next(i for i in items if i["part"] == "chronicle")
    assert said["verdict"] == expect["review"] and said["superseded"]
    assert all(i["verdict"] == review.HELD for i in items if i["part"] == "update" and i["checks"][0]["code"] == "lineup"
               and i["checks"][0]["verdict"] != review.NOT_EVALUABLE)
