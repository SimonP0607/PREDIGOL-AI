"""AD-K01 (IA-112): the one evaluation after the match of a selection, ``eval-sel-v1`` - case by case, repeated, and against the outcomes."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.evaluation import selection as sel
from fbi.evaluation.selection import (
    Decided,
    Fact,
    Inputs,
    Match,
    PlayerDay,
    Point,
    Settled,
    evaluate,
)
from fbi.lifecycle import derive

KO = datetime(2026, 11, 10, 20, 0, tzinfo=UTC)


def decided(**kw: object) -> Decided:
    base = Decided(layer="decision-v1", source="intel.decisions", decision_id=7, fixture_id=990001, market_key="OU", selection="Over",
                   line=Decimal("2.50"), known_at=KO - timedelta(hours=1), kickoff_at=KO, checkpoint="T-60m", state="INVESTIGACION",
                   p_model=0.58, p_cal=0.55, p_market=0.50, odds=Decimal("2.050"), evidence_ids=(), reasons=("ev_cal_below",),
                   context_status="FULL")
    return replace(base, **kw)  # type: ignore[arg-type]


def settled(result: str = "win", **kw: object) -> Settled:
    base = Settled(result=result, settled_at=KO + timedelta(hours=3), source="intel.decision_outcomes", version="outcome-v1",
                   close_p_fair=Decimal("0.500000"), close_minutes_to_ko=170, stored_clv=Decimal("0.025000"))
    return replace(base, **kw)  # type: ignore[arg-type]


def match(**kw: object) -> Match:
    base = Match(status="FT", reg_home=2, reg_away=1, lineup_at=None, players={}, rederived="win")
    return replace(base, **kw)  # type: ignore[arg-type]


def inputs(**kw: object) -> Inputs:
    base = Inputs(decided=decided(), settled=settled(), match=match())
    return replace(base, **kw)  # type: ignore[arg-type]


# ── the four cases of the ficha ──────────────────────────────────────────────────────────────────────────────────────

def test_won_without_value_is_luck_not_a_good_decision() -> None:
    ev = evaluate(inputs(decided=decided(odds=Decimal("1.900")), settled=settled("win", stored_clv=Decimal("-0.050000"))))
    assert ev.row["clv"] == Decimal("-0.050000") and ev.row["price_quality"] == "BAD"
    assert ev.row["verdict"] == "SUERTE" and ev.row["hit"] == 1
    assert ev.detail["value"]["notice_es"] == "Un acierto no valida el mercado."


def test_lost_with_value_is_variance_not_an_error() -> None:
    ev = evaluate(inputs(settled=settled("loss"), match=match(reg_home=0, reg_away=1, rederived="loss")))
    assert ev.row["clv"] == Decimal("0.025000") and ev.row["price_quality"] == "GOOD"
    assert ev.row["verdict"] == "VARIANZA" and ev.row["hit"] == 0
    assert ev.row["log_loss"] == round(-math.log(1 - 0.55), 6) and ev.row["brier"] == round(0.55**2, 6)
    assert ev.row["market_log_loss"] == round(-math.log(0.5), 6)


def test_a_void_is_null_and_not_scored() -> None:
    ev = evaluate(inputs(settled=settled("void"), match=match(status="CANC", reg_home=None, reg_away=None, rederived="void")))
    assert ev.row["verdict"] == "NULO" and ev.row["hit"] is None and ev.row["log_loss"] is None and ev.row["market_log_loss"] is None
    assert ev.detail["happened"]["not_scored_why"] == "resultado_no_completo"


def test_a_postponed_match_settled_void_at_72_h_is_null_and_its_later_result_is_a_parity_difference() -> None:
    """The match was postponed, the outcome was void 72 h after the first kick-off (settle-v3) and then it was played: the
    evaluation keeps the settlement of record and says the result it would have now."""
    ev = evaluate(inputs(settled=settled("void"), match=match(rederived="win")))
    assert ev.row["result"] == "void" and ev.row["verdict"] == "NULO"
    assert ev.row["parity"] == "difiere"
    assert ev.detail["parity"]["differences"] == [{"what": "resultado", "stored": "void", "settle_v4": "win"}]


def test_half_results_and_pushes_are_counted_never_scored() -> None:
    for r in ("half_win", "half_loss", "push"):
        ev = evaluate(inputs(settled=settled(r), match=match(rederived=r)))
        assert ev.row["hit"] is None and ev.row["brier"] is None
    assert evaluate(inputs(settled=settled("half_win"), match=match(rederived="half_win"))).row["verdict"] == "MERECIDO"
    assert evaluate(inputs(settled=settled("push"), match=match(rederived="push"))).row["verdict"] == "NULO"


def test_without_a_close_the_verdict_has_no_data() -> None:
    ev = evaluate(inputs(settled=settled("win", close_p_fair=None, stored_clv=None)))
    assert ev.row["clv"] is None and ev.row["p_close"] is None and ev.row["price_quality"] == "UNKNOWN"
    assert ev.row["verdict"] == "SIN_DATOS" and ev.row["parity"] == "igual"


# ── repetition and parity ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_same_selection_evaluated_twice_gives_the_same_row() -> None:
    x = inputs(facts=(Fact(5, "injury", None, 77), Fact(3, "lineup", "starts", 78)),
               match=match(players={77: PlayerDay(True, False, 0), 78: PlayerDay(True, True, 90)}))
    a, b = evaluate(x), evaluate(x)
    assert a.row == b.row and a.detail == b.detail
    shuffled = replace(x, facts=tuple(reversed(x.facts)))
    assert evaluate(shuffled).row["input_hash"] == a.row["input_hash"]
    assert evaluate(replace(x, settled=settled("loss"))).row["input_hash"] != a.row["input_hash"]


def test_parity_with_the_outcomes_is_equal_when_both_agree_and_says_which_differs() -> None:
    assert evaluate(inputs()).detail["parity"] == {"status": "igual", "checked": ["clv", "resultado"], "differences": [],
                                                   "outcome_version": "outcome-v1"}
    ev = evaluate(inputs(settled=settled(stored_clv=Decimal("0.030000"))))
    assert ev.row["parity"] == "difiere" and ev.detail["parity"]["differences"][0]["what"] == "clv"
    v2 = evaluate(inputs(decided=decided(layer="decision-v2", source="intel.decisions_v2", state="RECOMMENDED"),
                         settled=settled(source="settle-v4", version="settle-v4", stored_clv=None)))
    assert v2.row["parity"] == "sin_referencia" and v2.row["taken"] is True


def test_clv_is_the_one_definition() -> None:
    from fbi.market import closing_value

    ev = evaluate(inputs())
    assert ev.row["clv"] == closing_value.clv(Decimal("2.050"), Decimal("0.500000")).quantize(Decimal("0.000001"))


# ── the facts the decision cited ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("fact", "day", "expected"), [
    (Fact(1, "injury", None, 9), None, ("sostenido", "no_jugo")),
    (Fact(1, "injury", "out", 9), PlayerDay(True, False, 0), ("sostenido", "no_jugo")),
    (Fact(1, "suspension", None, 9), PlayerDay(True, True, 90), ("contradicho", "jugo")),
    (Fact(1, "injury", None, 9), PlayerDay(True, False, 12), ("contradicho", "jugo")),
    (Fact(1, "injury", None, 9), PlayerDay(True, False, None), ("no_evaluable", "minutos_desconocidos")),
    (Fact(1, "lineup", "starts", 9), PlayerDay(True, True, 90), ("sostenido", "fue_titular")),
    (Fact(1, "lineup", "starts", 9), PlayerDay(True, False, 30), ("contradicho", "no_fue_titular")),
    (Fact(1, "lineup", "available", 9), PlayerDay(True, False, 0), ("sostenido", "convocado")),
    (Fact(1, "lineup", "available", 9), None, ("contradicho", "no_convocado")),
    (Fact(1, "doubtful", "doubtful", 9), PlayerDay(True, True, 90), ("no_evaluable", "duda_sin_afirmacion")),
    (Fact(1, "news", "info", 9), None, ("no_evaluable", "sin_regla")),
    (Fact(1, "coach", None, None), None, ("no_evaluable", "sin_regla")),
    (Fact(1, "injury", None, None), None, ("no_evaluable", "sin_jugador_identificado")),
])
def test_each_fact_is_judged_by_what_the_provider_says_the_player_did(fact: Fact, day: PlayerDay | None,
                                                                         expected: tuple[str, str]) -> None:
    players = {42: PlayerDay(True, True, 90)} | ({9: day} if day is not None else {})
    assert sel.judge_fact(fact, match(players=players)) == expected


def test_without_the_official_line_up_no_fact_is_judged_and_none_is_matched_by_name() -> None:
    assert sel.judge_fact(Fact(1, "injury", None, 9), match(players={})) == ("no_evaluable", "sin_alineacion_oficial")
    ev = evaluate(inputs(facts=(Fact(1, "injury", None, 9), Fact(2, "news", None, None))))
    assert (ev.row["evidence_held"], ev.row["evidence_contradicted"], ev.row["evidence_unevaluable"]) == (0, 0, 2)


# ── the line-up ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_line_up_effect_compares_the_decision_before_it_with_the_one_that_stood() -> None:
    seen = KO - timedelta(minutes=55)
    stood = decided(known_at=KO - timedelta(minutes=15), checkpoint="T-15m", state="RECHAZADO", p_cal=0.50)
    ev = evaluate(inputs(decided=stood, before_lineup=Point(KO - timedelta(hours=3), "CAUTELA", 0.55),
                         match=match(lineup_at=seen, players={1: PlayerDay(True, True, 90)}), estimate=(19, 22)))
    lineup = ev.detail["lineup"]
    assert ev.row["lineup_changed"] is True and lineup["why"] == "comparada" and lineup["p_change_pp"] == -5.0
    assert lineup["estimate"] == {"hits": 19, "of": 22, "share": round(19 / 22, 4)}


@pytest.mark.parametrize(("lineup_at", "players", "known_at", "why"), [
    (None, {}, KO - timedelta(hours=1), "sin_alineacion_oficial"),
    (None, {1: PlayerDay(True, True, 90)}, KO - timedelta(hours=1), "hora_de_la_alineacion_desconocida"),
    (KO + timedelta(minutes=5), {1: PlayerDay(True, True, 90)}, KO - timedelta(hours=1), "sin_alineacion_oficial_antes_del_saque"),
    (KO - timedelta(minutes=40), {1: PlayerDay(True, True, 90)}, KO - timedelta(hours=1), "sin_decision_tras_la_alineacion"),
    (KO - timedelta(minutes=40), {1: PlayerDay(True, True, 90)}, KO - timedelta(minutes=15), "sin_decision_previa"),
])
def test_the_line_up_effect_says_why_it_cannot_compare(lineup_at: datetime | None, players: dict[int, PlayerDay],
                                                        known_at: datetime, why: str) -> None:
    ev = evaluate(inputs(decided=decided(known_at=known_at), match=match(lineup_at=lineup_at, players=players)))
    assert ev.row["lineup_changed"] is None and ev.detail["lineup"]["why"] == why
    assert ev.detail["lineup"]["estimate"] == {"why": "sin_estimacion", "piece": "AD-D04"}


# ── which decision stands, and who would take it ─────────────────────────────────────────────────────────────────────

def test_the_standing_decision_is_the_last_one_ten_minutes_before_kick_off() -> None:
    assert sel.LAST_WORD == derive.LAST_WORD
    rows = [(KO - timedelta(hours=3), "a"), (KO - timedelta(minutes=10), "b"), (KO - timedelta(minutes=9), "c")]
    assert sel.standing(rows, KO) == "b"
    assert sel.standing([(KO - timedelta(minutes=5), "x")], KO) is None


def test_a_decision_after_kick_off_is_refused() -> None:
    with pytest.raises(ValueError, match="before kick-off"):
        evaluate(inputs(decided=decided(known_at=KO)))


@pytest.mark.parametrize(("state", "reasons", "taken"), [
    ("APROBADO", (), True), ("PICK_DEL_DIA", (), True), ("INVESTIGACION", ("edge_not_validated",), True),
    ("INVESTIGACION", ("edge_not_validated", "ev_cal_below"), False), ("CAUTELA", ("risk",), False), ("RECHAZADO", ("data",), False),
])
def test_the_selections_the_layer_would_take_are_the_ones_the_cycle_confirms_in_the_shadow(state: str, reasons: tuple[str, ...],
                                                                                          taken: bool) -> None:
    d = decided(state=state, reasons=reasons)
    assert d.taken is taken and evaluate(inputs(decided=d)).row["taken"] is taken


def test_the_seal_follows_the_figure_the_decision_judged() -> None:
    assert evaluate(inputs()).row["seal"] == "calibrada"
    ev = evaluate(inputs(decided=decided(p_cal=None)))
    assert ev.row["seal"] == "sin_calibrar" and ev.row["p_judged"] == Decimal("0.580000")


def test_no_language_model_and_no_write_in_the_pure_module() -> None:
    import inspect

    text = inspect.getsource(sel)
    for word in ("anthropic", "openai", "INSERT", "UPDATE", "psycopg"):
        assert word not in text


def test_the_verdict_is_the_post_mortems_rule_on_every_pair() -> None:
    from fbi.intel.postmortem import verdict_of

    for result in sel.RESULTS:
        for quality in ("GOOD", "NEUTRAL", "BAD", "UNKNOWN"):
            assert sel.verdict_of(result, quality) == verdict_of(result, quality), (result, quality)
