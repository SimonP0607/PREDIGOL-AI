"""The factual review of the single chronicle (IA-118, AD-F06, ``chronicle-review-v2``) on its CITED facts: support sentence by sentence (a
fact not in the plan, not planned or known later is ``sin_apoyo``), an absence against who played (v1's own judgement), what the engine
proved against its reading after the match, the update after the line-up against the sheet, and the metrics of each chronicle."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fbi.chronicle import plan as cp
from fbi.chronicle import review, review_v2, update, verify
from tests.unit.test_chronicle_plan import AWAY_ID, HOME_ID, inp, objective, reading
from tests.unit.test_chronicle_update import XI_WITH_HIM
from tests.unit.test_chronicle_verify import CLAIMS, GOOD, PLAN, chronicle

WRITTEN = PLAN.at + timedelta(minutes=5)
TEAMS = {"home": HOME_ID, "away": AWAY_ID}


def squad(*, home: dict[str, int], away: dict[str, int] | None = None, starters: tuple[str, ...] = ()) -> review.Squad:
    people = [("home", 100 + i, n, m) for i, (n, m) in enumerate(home.items())]
    people += [("away", 200 + i, n, m) for i, (n, m) in enumerate((away or {}).items())]
    lineups = [{"team_side": s, "provider_player_id": pid, "player_name": n, "is_starter": n in starters} for s, pid, n, _ in people]
    stats = [{"team_side": s, "provider_player_id": pid, "player_name": n, "minutes": m} for s, pid, n, m in people]
    return review.squad_of(lineups, stats)


def judge(text: str, facts: list[str], plan: cp.ContentPlan = PLAN, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"written_at": WRITTEN, "squad": squad(home={"David Soria": 90}), "evidence": {}, "team_ids": TEAMS,
                            "after": None, "result": (1, 0)}
    base.update(kw)
    return review_v2.judge_sentence(text, facts, plan, **base)


def test_a_sentence_is_supported_only_by_planned_facts_known_before_it_was_written() -> None:
    assert review_v2.support(["P:form.home"], PLAN, written_at=WRITTEN) is None
    assert "no está en el plan" in str(review_v2.support(["P:invented"], PLAN, written_at=WRITTEN))
    assert "después" in str(review_v2.support(["P:form.home"], PLAN, written_at=PLAN.at - timedelta(days=1)))
    assert review_v2.support([], PLAN, written_at=WRITTEN) == "no cita ningún hecho"
    assert judge("x", ["P:invented"])["verdict"] == review_v2.UNSUPPORTED


def test_an_absence_is_judged_against_who_played() -> None:
    played = judge("Arambarri es baja.", ["P:absences.home.1"], squad=squad(home={"Mauro Arambarri": 75}))
    assert played["verdict"] == review.CONTRADICTED and played["supported"]
    out = judge("Arambarri es baja.", ["P:absences.home.1"], squad=squad(home={"Mauro Arambarri": 0}))
    assert out["verdict"] == review.HELD
    assert judge("El Getafe ganó 0-2.", ["P:results.home.1"])["verdict"] == review.NOT_EVALUABLE, "history describes"


def test_what_the_engine_proved_is_checked_against_its_reading_after_the_match() -> None:
    lost = cp.build(inp(scenarios=reading(home=[objective("evitar_descenso", "descartado", proved=True)])))
    fid = "S:home.general.evitar_descenso"
    f = lost.by_id()[fid]
    after_same = reading(home=[objective("evitar_descenso", "descartado", proved=True)])
    after_other = reading(home=[objective("evitar_descenso", "abierto", proved=False)])
    assert review_v2.check_scenario(f, after=after_same, team_ids=TEAMS, result=(0, 1)).verdict == review.HELD
    assert review_v2.check_scenario(f, after=after_other, team_ids=TEAMS, result=(0, 1)).verdict == review.CONTRADICTED
    assert review_v2.check_scenario(f, after=None, team_ids=TEAMS, result=(0, 1)).verdict == review.NOT_CHECKABLE
    nothing = PLAN.by_id()["S:away.sin_objetivo"]
    assert review_v2.check_scenario(nothing, after=reading(away_no_objective=True), team_ids=TEAMS, result=(1, 0)).verdict == review.HELD
    assert review_v2.check_scenario(nothing, after=reading(), team_ids=TEAMS, result=(1, 0)).verdict == review.CONTRADICTED


def test_what_this_result_does_is_checked_with_the_score() -> None:
    effects = {"7001": {"home": {"objetivos": [{"objetivo": "evitar_descenso", "condicional": False,
                                                "victoria": {"estado": "abierto"}, "empate": {"estado": "abierto"},
                                                "derrota": {"estado": "descartado"}}]}}}
    p = cp.build(inp(scenarios=reading(home=[objective("evitar_descenso", "abierto", proved=False)], effects=effects)))
    f = next(x for x in p.facts if x.kind == "scenario.result_effect")
    after = reading(home=[objective("evitar_descenso", "descartado", proved=True)])
    assert review_v2.check_scenario(f, after=after, team_ids=TEAMS, result=(0, 2)).verdict == review.HELD
    assert review_v2.check_scenario(f, after=after, team_ids=TEAMS, result=(1, 0)).verdict == review.NOT_EVALUABLE


def test_the_update_after_the_line_up_is_checked_against_the_sheet() -> None:
    content = verify.verify(chronicle(GOOD), PLAN, CLAIMS).content
    u = update.paragraph(PLAN, XI_WITH_HIM, content, chronicle_id=9)
    sentence = next(s for s in u.content["sentences"] if s["kind"] == "absence.out:titular")
    started = squad(home={"Mauro Arambarri": 90}, starters=("Mauro Arambarri",))
    benched = squad(home={"Mauro Arambarri": 0})
    assert review_v2.check_update(sentence, PLAN, started).verdict == review.HELD
    assert review_v2.check_update(sentence, PLAN, benched).verdict == review.CONTRADICTED


def test_the_metrics_of_a_chronicle_and_its_update() -> None:
    content = verify.verify(chronicle(GOOD), PLAN, CLAIMS).content
    assert content is not None
    u = update.paragraph(PLAN, XI_WITH_HIM, content, chronicle_id=9)
    full = update.content_of(content, u, [])
    s = squad(home={"Mauro Arambarri": 90, "David Soria": 90}, starters=("Mauro Arambarri",))
    items = review_v2.review_items(full, PLAN, written_at=WRITTEN, squad=s, evidence={}, team_ids=TEAMS, after=None, result=(1, 0))
    m = review_v2.metrics_of({"support": 1.0, "proposed": 12, "kept": 12, "mandatory": 4, "mandatory_cited": 4,
                              "repetition": {"generic_rate": 0.08, "repeat_rate": 0.0, "mode": "shadow"}}, items)
    assert m["version"] == review_v2.METRICS_VERSION and m["unsupported"] == 0 and m["support_audit"] == 1.0
    assert m["plan_coverage"] == 1.0 and m["generic_rate"] == 0.08 and m["update_sentences"] == len(u.content["sentences"])
    arambarri = next(i for i in items if i["part"] == "chronicle" and i["section"] == "jugadores")
    assert arambarri["superseded"] and arambarri["verdict"] == review.CONTRADICTED, "the chronicle was wrong and the update said so"
    assert m["contradicted"] >= 1 and m["held"] >= 1


def test_the_switch_is_off_by_default() -> None:
    assert review_v2.mode({}) == "off" and review_v2.mode({review_v2.SWITCH: "shadow"}) == "shadow"
    assert review_v2.VERSION == "chronicle-review-v2" and review_v2.SETTLE == review.SETTLE

