"""IA-068 (AD-D02): ``lifecycle-map-v1`` - the cycle read off today's layers. The map covers every reason code decision-v1 writes, a
rejection before kick-off is not final, the decisions of the last ten minutes do not count, a review only takes a selection down, the
match closes what is open, and a chain derived earlier is always a prefix of the chain derived later (so the shadow writer never has to
rewrite one)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.intel import decision as decision_v1
from fbi.intel import state_v2
from fbi.lifecycle import derive, machine, reader, store
from fbi.lifecycle.derive import Decision, Evaluation, Fixture, History, Key, Outcome, Review

KO = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
KEY = Key.of(990001, "OU", "over", "2.5")
_ids = iter(range(1, 10_000))


def dec(minutes_before: float, state: str, *reasons: str, context: str = "FULL", checkpoint: str = "T-6h",
        layer: str = "decision-v1") -> Decision:
    return Decision(next(_ids), layer, KO - timedelta(minutes=minutes_before), checkpoint, state, tuple(reasons), context, KO)


def played(status: str = "FT") -> Fixture:
    return Fixture(KEY.fixture_id, KO, status, "finished" if status in ("FT", "AET", "PEN") else None)


UPCOMING = Fixture(KEY.fixture_id, KO, "NS", "scheduled")
AFTER = KO + timedelta(days=4)


def states(rows: list[derive.Row]) -> list[tuple[str, str]]:
    return [(r.step.state, r.step.reason) for r in rows]


@pytest.mark.parametrize(("state", "reasons", "context", "checkpoint", "expected"), [
    ("APROBADO", (), "FULL", "T-3h", ("confirmada_sombra", "cumple_todo")),
    ("PICK_PREMIUM", ("risk",), "FULL", "T-3h", ("confirmada_sombra", "cumple_todo")),
    ("INVESTIGACION", ("edge_not_validated",), "FULL", "T-3h", ("confirmada_sombra", "cumple_salvo_validacion")),
    ("INVESTIGACION", ("edge_not_validated", "ai_reject"), "FULL", "T-3h", ("en_evaluacion", "revision_en_contra")),
    ("INVESTIGACION", ("family_research", "family_shadow_only"), "LIMITED", "T-3h", ("confirmada_sombra", "cumple_salvo_validacion")),
    ("INVESTIGACION", ("ev_unknown", "family_research", "not_calibrated", "risk"), "LIMITED", "T-3h", ("en_evaluacion", "sin_calibrar")),
    ("INVESTIGACION", ("price_stale", "risk"), "FULL", "T-6h", ("en_evaluacion", "precio_antiguo")),
    ("CAUTELA", ("risk",), "FULL", "T-6h", ("en_evaluacion", "riesgo")),
    ("CAUTELA", ("price_not_fresh", "risk"), "FULL", "T-60m", ("en_evaluacion", "precio_antiguo")),
    ("CAUTELA", ("key_absence_reported",), "FULL", "T-3h", ("pendiente_alineaciones", "baja_por_confirmar")),
    ("CAUTELA", ("key_absence_reported",), "FULL", "lineups", ("en_evaluacion", "baja_por_confirmar")),
    ("CAUTELA", ("key_absence_reported", "risk"), "FULL", "T-3h", ("en_evaluacion", "baja_por_confirmar")),
    ("RECHAZADO", ("ev_cal_below", "risk"), "PENDING", "T-36h", ("en_evaluacion", "valor_insuficiente")),
    ("RECHAZADO", ("data", "ev_cal_below", "risk"), "FULL", "T-12h", ("en_evaluacion", "datos_insuficientes")),
    ("RECHAZADO", ("ev_cal_below", "risk", "thin_market"), "FULL", "T-12h", ("en_evaluacion", "mercado_estrecho")),
    ("CAUTELA", ("risk",), "PENDING", "T-24h", ("en_investigacion", "contexto_pendiente")),
    ("APROBADO", (), "PENDING", "T-24h", ("en_investigacion", "contexto_pendiente")),
    ("RECHAZADO", (), "FULL", "T-24h", ("en_evaluacion", "sin_motivo_conocido")),
    ("CAUTELA", ("a_code_nobody_knows",), "FULL", "T-24h", ("en_evaluacion", "sin_motivo_conocido")),
])
def test_one_decision_maps_to_one_state_and_one_closed_reason(state: str, reasons: tuple[str, ...], context: str, checkpoint: str,
                                                               expected: tuple[str, str]) -> None:
    """The cases are the reason sets production writes (16-nov-2026, 14 days of decision-v1 and decision-fam-v1)."""
    got = derive.map_decision(Decision(1, "decision-v1", KO, checkpoint, state, reasons, context))
    assert got == expected
    assert got[1] in machine.REASONS[got[0]]


def test_the_map_knows_every_reason_code_decision_v1_writes() -> None:
    assert set(derive.BLOCKER_OF) == set(state_v2.REASON_EFFECT) - {"edge_not_validated"}
    assert all(v in machine.BLOCKERS for v in derive.BLOCKER_OF.values())
    assert derive.APPROVED == decision_v1.APPROVED
    assert timedelta(minutes=decision_v1.MIN_MINUTES) == derive.LAST_WORD


def test_a_rejection_before_kick_off_is_not_final_and_the_last_word_closes_it() -> None:
    h = History(KEY, decisions=[dec(36 * 60, "RECHAZADO", "no_price"), dec(12 * 60, "CAUTELA", "risk"),
                                dec(6 * 60, "RECHAZADO", "ev_cal_below")])
    assert states(derive.derive(h, played(), now=AFTER)) == [
        ("detectado", "candidato_nuevo"), ("en_evaluacion", "sin_precio"), ("en_evaluacion", "riesgo"),
        ("en_evaluacion", "valor_insuficiente"), ("descartada", "valor_insuficiente")]


def test_a_confirmed_selection_plays_settles_and_is_evaluated() -> None:
    d1, d2 = dec(24 * 60, "CAUTELA", "risk", context="PENDING"), dec(90, "INVESTIGACION", "edge_not_validated", checkpoint="T-90m")
    h = History(KEY, decisions=[d1, d2], outcomes={d2.id: Outcome(d2.id, KO + timedelta(hours=41), "win")},
                evaluations={d2.id: Evaluation(d2.id, KO + timedelta(hours=44), "intel.postmortems", 7)})
    rows = derive.derive(h, played(), now=AFTER)
    assert states(rows) == [("detectado", "candidato_nuevo"), ("en_investigacion", "contexto_pendiente"),
                            ("confirmada_sombra", "cumple_salvo_validacion"), ("en_juego", "saque"), ("liquidada", "resultado"),
                            ("evaluada", "evaluacion_posterior")]
    assert rows[4].step.settlement_result == "win" and rows[4].source == "intel.decision_outcomes"
    assert (rows[5].source, rows[5].source_id) == ("intel.postmortems", 7)
    assert [r.known_at for r in rows] == sorted(r.known_at for r in rows)
    assert machine.public_state(derive.steps_of(rows)) is None, "the shadow writer never makes a selection public"


def test_the_decisions_of_the_last_ten_minutes_do_not_withdraw_a_confirmed_selection() -> None:
    d1 = dec(90, "INVESTIGACION", "edge_not_validated", checkpoint="T-90m")
    late = dec(8, "RECHAZADO", "data", "price_not_fresh", checkpoint="lineups")
    h = History(KEY, decisions=[d1, late], outcomes={late.id: Outcome(late.id, KO + timedelta(hours=40), "loss")})
    rows = derive.derive(h, played(), now=AFTER)
    assert states(rows)[-3:] == [("confirmada_sombra", "cumple_salvo_validacion"), ("en_juego", "saque"), ("liquidada", "resultado")]
    assert rows[-1].source_id == late.id, "every row of the selection settles the same bet"


def test_a_confirmed_selection_that_loses_its_price_is_withdrawn_and_closes_withdrawn() -> None:
    h = History(KEY, decisions=[dec(180, "INVESTIGACION", "edge_not_validated", checkpoint="T-3h"),
                                dec(60, "CAUTELA", "price_not_fresh", checkpoint="T-60m"),
                                dec(30, "CAUTELA", "price_not_fresh", "risk", checkpoint="lineups")])
    assert states(derive.derive(h, played(), now=AFTER))[1:] == [
        ("confirmada_sombra", "cumple_salvo_validacion"), ("retirada", "precio_antiguo"), ("descartada", "retirada_al_saque")]


def test_a_withdrawn_selection_can_come_back() -> None:
    h = History(KEY, decisions=[dec(180, "APROBADO", checkpoint="T-3h"), dec(90, "CAUTELA", "risk", checkpoint="T-90m"),
                                dec(60, "APROBADO", checkpoint="T-60m")])
    assert states(derive.derive(h, played(), now=AFTER))[1:] == [
        ("confirmada_sombra", "cumple_todo"), ("retirada", "riesgo"), ("confirmada_sombra", "cumple_todo"), ("en_juego", "saque")]


def test_a_review_only_takes_a_selection_down_and_says_it_was_a_model() -> None:
    confirmed = dec(180, "INVESTIGACION", "edge_not_validated", checkpoint="T-3h")
    h = History(KEY, decisions=[confirmed], reviews=[Review(5, KO - timedelta(minutes=120), "REJECT"),
                                                      Review(6, KO - timedelta(minutes=100), "APPROVE")])
    rows = derive.derive(h, UPCOMING, now=KO - timedelta(minutes=50))
    assert states(rows)[-1] == ("retirada", "revision_en_contra") and rows[-1].step.actor == "model"
    evaluating = History(KEY, decisions=[dec(180, "CAUTELA", "risk")], reviews=[Review(7, KO - timedelta(minutes=120), "REJECT")])
    assert [r.step.actor for r in derive.derive(evaluating, UPCOMING, now=KO - timedelta(minutes=50))] == ["code", "code"]


def test_a_match_that_will_not_be_played_closes_its_selections() -> None:
    h = History(KEY, decisions=[dec(180, "APROBADO", checkpoint="T-3h")])
    cancelled = Fixture(KEY.fixture_id, KO, "CANC", "cancelled")
    assert states(derive.derive(h, cancelled, now=KO + timedelta(hours=1)))[-2:] == [
        ("retirada", "partido_no_jugado"), ("descartada", "partido_no_jugado")]
    postponed = Fixture(KEY.fixture_id, KO, "PST", "postponed")
    assert states(derive.derive(h, postponed, now=KO + timedelta(days=1)))[-1] == ("confirmada_sombra", "cumple_todo"), \
        "a postponed match may still be played: it waits"
    assert states(derive.derive(h, postponed, now=KO + timedelta(days=3, minutes=1)))[-1] == ("descartada", "partido_no_jugado")
    assert states(derive.derive(h, Fixture(KEY.fixture_id, KO, "NS", "scheduled"), now=KO + timedelta(hours=2)))[-1] == \
        ("confirmada_sombra", "cumple_todo"), "no kick-off seen yet: nothing is closed on the clock alone"


def test_a_shadow_pick_never_decided_is_detected_and_discarded_at_kick_off() -> None:
    h = History(KEY, detected_at=KO - timedelta(hours=30), detected_pick=42)
    rows = derive.derive(h, played(), now=AFTER)
    assert states(rows) == [("detectado", "candidato_nuevo"), ("descartada", "sin_decision")]
    assert (rows[0].source, rows[0].source_id) == ("picks.picks", 42)
    assert derive.derive(History(KEY), played(), now=AFTER) == []


def test_two_models_at_one_moment_count_once_and_identical_rows_are_one_step() -> None:
    a, b = dec(300, "CAUTELA", "risk"), dec(300, "CAUTELA", "risk")
    h = History(KEY, decisions=[a, b, dec(200, "CAUTELA", "risk"), dec(100, "CAUTELA", "risk")])
    assert states(derive.derive(h, UPCOMING, now=KO - timedelta(minutes=50))) == [("detectado", "candidato_nuevo"),
                                                                                   ("en_evaluacion", "riesgo")]


def _scenarios() -> list[History]:
    out = []
    for seed in range(60):
        pattern = [("RECHAZADO", ("ev_cal_below",)), ("CAUTELA", ("risk",)), ("INVESTIGACION", ("edge_not_validated",)),
                   ("APROBADO", ()), ("CAUTELA", ("key_absence_reported",)), ("INVESTIGACION", ("price_stale",))]
        decs = [dec(2000 - 30 * i - seed, *pattern[(seed + i * (seed % 5 + 1)) % len(pattern)][:1],
                    *pattern[(seed + i * (seed % 5 + 1)) % len(pattern)][1], context="PENDING" if i == 0 and seed % 3 == 0 else "FULL")
                for i in range(seed % 7 + 1)]
        last = decs[-1].id
        out.append(History(KEY, detected_at=KO - timedelta(hours=40) if seed % 2 else None, detected_pick=seed if seed % 2 else None,
                           decisions=decs, reviews=[Review(900 + seed, KO - timedelta(minutes=500 + seed), "DOWNGRADE")] if seed % 4 == 0 else [],
                           outcomes={last: Outcome(last, KO + timedelta(hours=40), "push")},
                           evaluations={last: Evaluation(last, KO + timedelta(hours=45), "intel.family_postmortems", 3)}))
    return out


def test_a_chain_derived_earlier_is_a_prefix_of_the_chain_derived_later() -> None:
    """What makes the writer append-only in practice: at any moment it only adds rows (production, 16-nov: 85.730 checks, 0 failures)."""
    for h in _scenarios():
        final = states(derive.derive(h, played(), now=AFTER))
        for minutes in (-2000, -1500, -600, -120, -45, -5, 30, 41 * 60, 46 * 60):
            t = KO + timedelta(minutes=minutes)
            fx = played() if t >= KO else UPCOMING
            early = states(derive.derive(derive.as_of(h, t), fx, now=t))
            assert final[:len(early)] == early, (minutes, early, final)
        machine.check_chain(derive.steps_of(derive.derive(h, played(), now=AFTER)))


def test_the_same_inputs_give_the_same_chain() -> None:
    for h in _scenarios()[:10]:
        assert derive.derive(h, played(), now=AFTER) == derive.derive(h, played(), now=AFTER)


def test_the_writer_appends_a_prefix_and_never_rewrites() -> None:
    h = _scenarios()[5]
    rows = derive.derive(h, played(), now=AFTER)
    kept = [store.Stored(i, r.step.state, r.step.reason, r.source, r.source_id) for i, r in enumerate(rows[:2], start=1)]
    assert store.plan([], rows) == ("new", rows)
    assert store.plan(kept, rows) == ("extended", rows[2:])
    full = [store.Stored(i, r.step.state, r.step.reason, r.source, r.source_id) for i, r in enumerate(rows, start=1)]
    assert store.plan(full, rows) == ("unchanged", [])
    other = [store.Stored(1, "detectado", "candidato_nuevo", "core.fixtures", None)]
    assert store.plan(other, rows) == ("divergent", [])
    assert store.plan([*full, full[-1]], rows) == ("divergent", [])


@pytest.mark.parametrize(("line", "text"), [("2.5", "2.50"), ("-0.25", "-0.25"), ("0", "0.00"), (Decimal("1"), "1.00")])
def test_the_chain_key_is_what_the_table_computes(line: str | Decimal, text: str) -> None:
    """The CHECK is ``writer|fixture|market|selection|line::text``; a NUMERIC(6,2) prints with two decimals."""
    assert store.chain_key("lifecycle-shadow-v1", Key.of(5, "AH", "home", line)) == f"lifecycle-shadow-v1|5|AH|home|{text}"


def test_the_switch_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(store.SWITCH, raising=False)
    assert store.mode() == "off"
    for word, expected in (("shadow", "shadow"), (" SHADOW ", "shadow"), ("on", "off"), ("1", "off"), ("off", "off")):
        monkeypatch.setenv(store.SWITCH, word)
        assert store.mode() == expected


def test_the_reader_groups_markets_by_family() -> None:
    assert [reader.family_of(m) for m in ("CORNERS_OU", "CORNERS_1X2", "CARDS_OU", "OU_1H", "1X2_2H", "OU", "AH", "BTTS")] == \
        ["corners", "corners", "cards", "goals_halves", "goals_halves", "core", "core", "core"]
