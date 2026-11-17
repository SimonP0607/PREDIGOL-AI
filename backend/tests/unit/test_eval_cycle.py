"""The evaluation cycle E1-E4 (IA-105..IA-108, plan pieces AD-D06, AD-D07, AD-D08, AD-D03), its pure parts:

* the clock: E1 is decision-v2's kept shadow's and the estimated starters'; decision-v2's last decision is their E4 (T-20 to decision-v1's
  floor of 10 min, never lowered) and E4 runs at T-5 since the owner's decision of 17-nov-2026 (IA-142), deciding nothing; a simulated clock over three matches (one whose kick-off is brought forward, one whose line-up never comes, one with the line-up
  at T-75) fires each evaluation when it should and never twice; a fact never triggers two E2;
* the dependencies: the example of Doc 1 (1.0 shot on target per 90: 63 % playing the whole match, 53.7 % with 85 % of starts), the three
  groups, the shift of a striker and its sign, consulting the table against recomputing it from scratch within the preregistered tolerance;
* E3: the fixed cases (a key starter out, the line-up as estimated, the price gone old, no line-up), what a withdrawal alerts and with
  which «antes -> ahora»;
* the chain of states read off the verdicts, legal by the machine, closed at kick-off.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.decision import shadow
from fbi.evalcycle import alerts, chain, clock, conditions, dependency, players, reevaluate
from fbi.evalcycle.dependency import Matrix, PlayerInput
from fbi.evalcycle.reevaluate import Decided, Priced, Standing
from fbi.intel import decision
from fbi.lifecycle import machine
from fbi.lifecycle.derive import Fixture
from fbi.shadowjobs import lineup_estimate

K = datetime(2032, 9, 20, 20, 0, tzinfo=UTC)
OU = ("OU", "Over", Decimal("2.50"))
HOME = ("1X2", "Home", Decimal("0.00"))
STRIKER = 9


# ── the clock ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_e4_is_at_t5_and_the_last_decision_stops_at_decision_v1s_floor() -> None:
    from fbi.shadowjobs import eval_cycle

    assert (clock.E1_FROM, clock.E1_UNTIL, clock.DECIDE_FROM) == (shadow.E1_FROM, shadow.E1_UNTIL, shadow.E4_FROM)
    assert (lineup_estimate.E1_FROM, lineup_estimate.E1_UNTIL, lineup_estimate.E4_FROM, lineup_estimate.E4_UNTIL) == (
        clock.E1_FROM, clock.E1_UNTIL, clock.DECIDE_FROM, clock.DECISION_FLOOR), "the estimated starters keep decision-v2's windows"
    assert clock.DECISION_FLOOR == shadow.E4_UNTIL == timedelta(minutes=decision.MIN_MINUTES) == timedelta(minutes=10), (
        "decision-v1's floor is imported and never lowered")
    assert timedelta(minutes=5) == clock.E4_FROM and timedelta(0) == clock.E4_UNTIL and clock.VERSION == "eval-clock-v2", "the owner's T-5"
    assert clock.window(K, K - timedelta(hours=13)) == "E1" and clock.window(K, K - timedelta(hours=11)) is None
    assert clock.window(K, K - timedelta(minutes=15)) is None and clock.window(K, K - timedelta(minutes=5)) == "E4"
    assert clock.window(K, K - timedelta(minutes=1)) == "E4" and clock.window(K, K) is None, "E4 is due until kick-off, never after"
    assert clock.last_decision(K, K - timedelta(minutes=20)) and clock.last_decision(K, K - timedelta(minutes=11))
    assert not clock.last_decision(K, K - timedelta(minutes=10)) and not clock.last_decision(K, K - timedelta(minutes=21))
    assert clock.decides(K, K - timedelta(minutes=11)) and not clock.decides(K, K - timedelta(minutes=9))
    assert not clock.decides(K, K - clock.E4_FROM), "nothing decides at T-5: E4 judges with the last decision"
    assert timedelta(minutes=eval_cycle.every_minutes({})) <= clock.E4_FROM - clock.E4_UNTIL, "a pass falls inside E4's window"
    assert eval_cycle.every_minutes({"FBI_EVAL_CYCLE_MINUTES": "10"}) == 5, "a cadence wider than E4's window is refused"
    assert timedelta(minutes=2) == clock.E3_DEADLINE


def arrival(side: str, at: datetime, starters: str = "a", n: int = 11) -> clock.Arrival:
    return clock.Arrival(side, at, (starters * 64)[:64], n)


def simulate(kickoffs: dict[datetime, datetime], lineups: dict[datetime, dict[str, clock.Arrival]], *, start: datetime, end: datetime
             ) -> list[tuple[datetime, str, str]]:
    """A match minute by minute as the two passes see it: the kick-off in force at each minute (it may move) and the line-up arrivals by
    then. Returns (minute, evaluation, key) of every evaluation that fires."""
    fired: list[tuple[datetime, str, str]] = []
    done: set[str] = set()
    e3_keys: list[str] = []
    t = start
    while t <= end:
        kickoff = kickoffs[max(k for k in kickoffs if k <= t)]
        due = clock.window(kickoff, t)
        if due is not None and due not in done:
            done.add(due)
            fired.append((t, due, "ventana"))
        newest: dict[str, clock.Arrival] = {}
        for at in sorted(x for x in lineups if x <= t):
            newest.update(lineups[at])
        lu = clock.plan_line_up(newest, e3_keys, now=t, kickoff_at=kickoff)
        if lu is not None:
            e3_keys.append(lu.key)
            fired.append((t, "E3", lu.cause))
            assert t - lu.trigger_at < clock.E3_DEADLINE, "the minute pass reaches a line-up within two minutes"
        t += timedelta(minutes=1)
    return fired


def test_a_simulated_clock_fires_each_evaluation_once_and_e3_within_two_minutes() -> None:
    start = K - timedelta(hours=26)
    # 1) the kick-off is brought forward by an hour, 3 hours before the first one: E4 follows the new kick-off
    early = K - timedelta(hours=1)
    fired = simulate({start: K, K - timedelta(hours=3): early}, {}, start=start, end=K)
    assert [(e, t) for t, e, _ in fired] == [("E1", K - timedelta(hours=24)), ("E4", early - timedelta(minutes=5))]
    # 2) no line-up ever: no E3, E1 and E4 once each
    fired = simulate({start: K}, {}, start=start, end=K)
    assert [e for _, e, _ in fired] == ["E1", "E4"]
    # 3) the line-up at T-75 (both sides), a corrected starter at T-30: E3 twice, the second a correction
    lineups = {K - timedelta(minutes=75): {"home": arrival("home", K - timedelta(minutes=75)), "away": arrival("away", K - timedelta(minutes=75))},
               K - timedelta(minutes=30): {"home": arrival("home", K - timedelta(minutes=30), "b")}}
    fired = simulate({start: K}, lineups, start=start, end=K + timedelta(minutes=5))
    assert [(e, c) for _, e, c in fired] == [("E1", "ventana"), ("E3", "alineacion_oficial"), ("E3", "correccion_alineacion"),
                                             ("E4", "ventana")]
    assert [t for t, e, _ in fired if e == "E3"] == [K - timedelta(minutes=75), K - timedelta(minutes=30)]


def test_one_side_alone_waits_three_minutes_and_nothing_runs_after_kick_off() -> None:
    home = {"home": arrival("home", K - timedelta(minutes=20))}
    assert clock.plan_line_up(home, [], now=K - timedelta(minutes=19), kickoff_at=K) is None
    due = clock.plan_line_up(home, [], now=K - timedelta(minutes=17), kickoff_at=K)
    assert due is not None and due.sides == ("home",) and due.key.endswith("away:-")
    both = {**home, "away": arrival("away", K - timedelta(minutes=16))}
    again = clock.plan_line_up(both, [due.key], now=K - timedelta(minutes=16), kickoff_at=K)
    assert again is not None and again.cause == "correccion_alineacion" and again.sides == ("away", "home")
    assert clock.plan_line_up(both, [], now=K, kickoff_at=K) is None
    assert clock.plan_line_up({"home": arrival("home", K - timedelta(minutes=20), n=10)}, [], now=K - timedelta(minutes=5),
                              kickoff_at=K) is None, "a sheet without eleven starters is not the line-up"


def test_a_fact_is_looked_at_once_and_recalculates_only_what_touches_the_model() -> None:
    e1 = K - timedelta(hours=20)
    facts = [clock.Fact(1, "injury", 77, e1 + timedelta(hours=1)), clock.Fact(2, "news", None, e1 + timedelta(hours=2)),
             clock.Fact(3, "news", STRIKER, e1 + timedelta(hours=3)), clock.Fact(4, "lineup", None, e1 - timedelta(hours=1))]
    now = e1 + timedelta(hours=4)
    calls = clock.plan_facts(facts, [], frozenset({STRIKER}), e1_at=e1, now=now, kickoff_at=K)
    assert [(c.fact.evidence_id, c.action, c.reason) for c in calls] == [
        (1, "recalcula", "variable_del_modelo"), (2, "anota", "no_toca_el_modelo"), (3, "recalcula", "dependencia_declarada")]
    assert clock.plan_facts(facts, [1, 2, 3], frozenset({STRIKER}), e1_at=e1, now=now, kickoff_at=K) == [], "a fact never triggers two E2"
    assert clock.facts_key(calls) == clock.facts_key(list(reversed(calls)))
    assert clock.plan_facts(facts, [], frozenset(), e1_at=None, now=now, kickoff_at=K) == [], "no E2 before E1"
    assert clock.plan_facts(facts, [], frozenset(), e1_at=e1, now=K - timedelta(minutes=5), kickoff_at=K) == [], "a late fact is E4's"
    assert clock.plan_facts(facts, [], frozenset(), e1_at=e1, now=K - timedelta(minutes=15), kickoff_at=K), "E2 runs until E4 opens (T-5)"


# ── the dependencies ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_doc_1s_example_one_shot_on_target_per_90() -> None:
    assert players.prop_over(1.0, 0.0, p_start=1.0, minutes_start=90) == pytest.approx(0.632, abs=5e-4)
    assert players.prop_over(1.0, 0.0, p_start=0.85, minutes_start=90) == pytest.approx(0.537, abs=5e-4), "53 % in Doc 1, rounded down"
    assert players.prop_over(1.0, 0.0, p_start=0.0, minutes_start=90) == 0.0


def side(team: str, base: int, rate: float, *, striker: PlayerInput | None = None) -> list[PlayerInput]:
    men = [PlayerInput(base + j, team, "M", 0.92, 0.05, 85.0, 20.0, rate, 0.10) for j in range(10 if striker else 11)]
    return [striker, *men] if striker else men


def scene(p_start: float = 0.6, absence: str | None = "duda") -> tuple[Matrix, list[PlayerInput]]:
    striker = PlayerInput(STRIKER, "home", "F", p_start, 0.2, 85.0, 20.0, 0.60, 0.15, absence)
    return Matrix(1.6, 1.0, -0.05, "dixon_coles"), side("home", 100, 0.12, striker=striker) + side("away", 200, 0.11)


def test_the_three_groups_and_who_holds_up_a_selection() -> None:
    assert dependency.group_of("player_shots_on") == dependency.group_of("keeper_saves") == dependency.ALWAYS
    assert dependency.group_of("CORNERS") == dependency.NEVER
    assert {dependency.group_of(k) for k in ("1X2", "DC", "OU", "AH", "BTTS", "OU_HOME", "CARDS")} == {dependency.DECLARED}
    m, men = scene()
    deps = dependency.dependencies([(OU, 0.55), (HOME, 0.50), (("CORNERS", "Over", Decimal("9.50")), 0.5),
                                    (("player_shots", "Over", Decimal("0.50")), 0.5), (("CARDS", "Over", Decimal("4.50")), 0.5)], m, men)
    ou, home, corners, prop, cards = deps
    assert ou.status == home.status == dependency.COMPUTED and ou.waits and home.waits, "the striker is in doubt"
    assert [p.provider_player_id for p in ou.players] == [STRIKER], "only who moves it by two points or more is listed"
    s = ou.players[0]
    assert s.shift_without < -dependency.MATERIAL < 0 < dependency.MATERIAL < s.shift_full
    assert s.p_without == pytest.approx(0.55 + s.shift_without) and s.p_full == pytest.approx(0.55 + s.shift_full)
    assert (corners.group, corners.status, corners.waits) == (dependency.NEVER, dependency.NOT_APPLICABLE, False)
    assert (prop.group, prop.waits) == (dependency.ALWAYS, True), "a player's prop always waits"
    assert (cards.status, cards.waits) == (dependency.NO_MATRIX, False)
    sure = dependency.dependencies([(OU, 0.55)], *scene(p_start=0.97, absence=None))[0]
    assert sure.players and not sure.waits, "a certain starter is listed but leaves nothing to wait for"
    assert dependency.dependencies([(OU, 0.55)], m, [])[0].status == dependency.NO_ESTIMATE
    assert dependency.dependencies([(OU, 0.55)], None, men)[0].status == dependency.NO_MATRIX


@pytest.mark.parametrize("xi_home", [frozenset(range(100, 111)), frozenset([STRIKER, *range(100, 110)]),
                                     frozenset([STRIKER, *range(100, 105), *range(106, 111)])])
def test_consulting_the_table_is_recomputing_it_within_the_preregistered_tolerance(xi_home: frozenset[int]) -> None:
    m, men = scene()
    away = frozenset(range(200, 211))
    for key, p in ((OU, 0.55), (HOME, 0.48), (("AH", "Away", Decimal("0.25")), 0.40), (("BTTS", "Yes", Decimal("0.00")), 0.52)):
        dep = dependency.dependencies([(key, p)], m, men)[0]
        got = dependency.apply(dep, {"home": xi_home, "away": away})
        again = dependency.recompute(dep, men, {"home": xi_home, "away": away})
        assert got.p is not None and again is not None
        assert abs(got.p - again) <= dependency.TOLERANCE == 0.01, (key, got.p, again)
    dep = dependency.dependencies([(OU, 0.55)], m, men)[0]
    assert dependency.apply(dep, {"away": away}).unseen == (STRIKER,), "a side not read yet is not guessed"


# ── E3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

AWAY_XI = frozenset(range(200, 211))
WITHOUT = {"home": frozenset(range(100, 111)), "away": AWAY_XI}
WITH = {"home": frozenset([STRIKER, *range(100, 110)]), "away": AWAY_XI}
WAITING = Standing("pendiente_alineaciones", "depende_de_alineacion", 0.55, 2.0)


def ou_dependency() -> dependency.Dependency:
    return dependency.dependencies([(OU, 0.55)], *scene())[0]


def approved(p: float = 0.55, odds: float = 2.0, state: str = "vigente") -> Decided:
    return Decided(7, "confirmada_sombra", "cumple_todo", p, odds, 0.50, state)


def test_e1_never_confirms_blind_what_the_line_up_decides() -> None:
    dep = ou_dependency()
    assert reevaluate.reading("confirmada_sombra", "cumple_todo", dep) == reevaluate.Reading("pendiente_alineaciones",
                                                                                            "depende_de_alineacion", "espera_alineacion")
    assert reevaluate.reading("en_evaluacion", "valor_insuficiente", dep).state == "en_evaluacion"
    sure = dependency.dependencies([(OU, 0.55)], *scene(p_start=0.97, absence=None))[0]
    assert reevaluate.reading("confirmada_sombra", "cumple_todo", sure).state == "confirmada_sombra"


def test_a_key_starter_out_withdraws_and_the_alert_says_before_and_now() -> None:
    o = reevaluate.reassess(WAITING, ou_dependency(), WITHOUT, approved(), None)
    assert (o.verdict, o.state, o.reason, o.cause) == ("retirada", "retirada", "alineacion_en_contra", "alineacion")
    assert o.p_after is not None and o.p_after < 0.55 and o.lineup["missing"] == [STRIKER]
    a = alerts.withdrawn(1, OU, WAITING, o, decision_id=7)
    assert a is not None and a.kind == "retirada" and a.cause == "alineacion_en_contra"
    assert a.before["state"] == "pendiente_alineaciones" and a.after["state"] == "retirada" and a.after["players_out"] == [STRIKER]
    again = alerts.withdrawn(1, OU, WAITING, o, decision_id=7)
    assert again is not None and a.dedupe_key == again.dedupe_key, "the same alert is the same key: it is written once"
    assert a.before["p"] == 0.55 and a.after["p"] == round(o.p_after, 4)


def test_the_line_up_as_estimated_confirms() -> None:
    o = reevaluate.reassess(WAITING, ou_dependency(), WITH, approved(), None)
    assert (o.verdict, o.state, o.reason) == ("confirmada", "confirmada_sombra", "cumple_todo")
    assert alerts.withdrawn(1, OU, WAITING, o, decision_id=7) is None
    confirmed = Standing("confirmada_sombra", "cumple_todo", 0.55, 2.0)
    assert reevaluate.reassess(confirmed, None, WITH, approved(), None).verdict == "sigue_igual"
    assert reevaluate.reassess(confirmed, None, WITH, approved(p=0.57, odds=2.1), None).verdict == "modificada"


def test_an_old_price_or_a_decision_against_withdraws() -> None:
    o = reevaluate.reassess(WAITING, ou_dependency(), WITH, approved(state="antiguo"), None)
    assert (o.verdict, o.reason, o.cause) == ("retirada", "precio_antiguo", "precio")
    late = reevaluate.reassess(WAITING, ou_dependency(), WITH, None, Priced(None, None, "sin_precio"))
    assert (late.verdict, late.reason) == ("retirada", "sin_precio")
    against = reevaluate.reassess(WAITING, ou_dependency(), WITH, Decided(8, "en_evaluacion", "baja_clave_confirmada", 0.55, 2.0, 0.5,
                                                                        "vigente"), None)
    assert (against.verdict, against.reason, against.cause) == ("retirada", "baja_clave_confirmada", "decision_en_contra")


def test_no_line_up_keeps_it_waiting_and_a_late_line_up_reads_the_price_again() -> None:
    o = reevaluate.reassess(WAITING, ou_dependency(), {}, approved(), None)
    assert (o.verdict, o.state) == ("pendiente", "pendiente_alineaciones"), "never confirmed without its line-up"
    late = reevaluate.reassess(WAITING, ou_dependency(), WITH, None, Priced(2.0, 0.50, "vigente"))
    assert late.verdict == "confirmada", "under decision-v2's floor the last decision stands and the price is read again"


def test_what_was_not_confirmed_is_confirmed_only_by_a_new_approval_with_its_value() -> None:
    st = Standing("en_evaluacion", "valor_insuficiente", 0.50, 2.0)
    assert reevaluate.reassess(st, None, WITH, None, Priced(2.0, 0.5, "vigente")).verdict == "sigue_igual"
    assert reevaluate.reassess(st, None, WITH, approved(), None).verdict == "confirmada"
    weak = reevaluate.reassess(st, ou_dependency(), WITHOUT, approved(), None)
    assert (weak.state, weak.reason) == ("en_evaluacion", "valor_insuficiente")
    withdrawn = Standing("retirada", "alineacion_en_contra", 0.47, 2.0)
    assert reevaluate.reassess(withdrawn, None, WITH, Decided(9, "en_evaluacion", "valor_insuficiente", 0.5, 2.0, 0.5, "vigente"),
                               None).state == "retirada", "withdrawn it stays until it comes back"


# ── E4: the match read again ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_match_read_again_says_what_changed() -> None:
    from fbi.ai.final_reread import Reading

    at = K - timedelta(minutes=15)
    known = conditions.Known(K, "NS", 5)
    same = conditions.check(known, Reading(1, at, K, "NS"), 5, at=at)
    assert same.verdict.ok and same.changes == () and not same.stops
    moved = conditions.check(known, Reading(1, at, K - timedelta(hours=1), "NS"), 5, at=at)
    assert [(c.kind, c.cause) for c in moved.changes] == [("cambio_horario", "saque_adelantado")]
    assert moved.changes[0].before == {"kickoff_at": K.isoformat()}
    off = conditions.check(known, Reading(1, at, K, "PST"), 6, at=at)
    assert off.stops and {(c.kind, c.cause) for c in off.changes} == {("cambio_condiciones", "aplazado"),
                                                                     ("cambio_condiciones", "cambio_de_sede")}
    assert alerts.changed(1, off.changes[0]).key is None


# ── the chain ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def v(i: int, minutes: int, state: str, reason: str, ev: str) -> chain.Verdict:
    return chain.Verdict(i, K - timedelta(minutes=minutes), state, reason, ev, 1)


def test_the_chain_of_a_withdrawn_selection_is_legal_and_closes_at_kick_off() -> None:
    vs = [v(1, 20 * 60, "pendiente_alineaciones", "depende_de_alineacion", "E1"),
          v(2, 19, "retirada", "alineacion_en_contra", "E3"),
          v(3, 15, "en_evaluacion", "valor_insuficiente", "E4")]
    played = Fixture(1, K, "FT", "finished")
    rows = chain.chain(vs, played, now=K + timedelta(hours=3))
    steps = [r.step for r in rows]
    machine.check_chain(steps)
    assert [(s.state, s.reason) for s in steps] == [("detectado", "candidato_nuevo"), ("pendiente_alineaciones", "depende_de_alineacion"),
                                                     ("retirada", "alineacion_en_contra"), ("descartada", "retirada_al_saque")]
    assert steps[2].evaluation == "E3" and rows[2].source == chain.SOURCE and rows[-1].source == "core.fixtures"
    waiting = chain.chain(vs[:1], played, now=K + timedelta(hours=3))
    assert waiting[-1].step.reason == "sin_alineacion_a_tiempo", "still waiting at kick-off: «Descartada: sin alineación»"
    confirmed = chain.chain([vs[0], v(4, 19, "confirmada_sombra", "cumple_todo", "E3")], played, now=K + timedelta(hours=3))
    assert confirmed[-1].step.state == "en_juego"
    assert chain.chain(vs, Fixture(1, K, "PST", "postponed"), now=K + timedelta(days=4))[-1].step.reason == "partido_no_jugado"
    assert chain.chain(vs, played, now=K - timedelta(minutes=18))[-1].step.state == "retirada", "nothing later than now"
