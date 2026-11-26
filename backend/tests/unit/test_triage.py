"""RP-8.2: the triage groups hypotheses by variable and direction with plain rules, gives each a destination and a reason, never invents a group for what no
rule reads, and its fingerprint changes when the proposal does. Titles are the real ones of the 96 waiting hypotheses."""

from __future__ import annotations

import pytest

from fbi.research import triage as tr


def item(i: int, title: str, *, n: int | None = None, text: str = "", status: str = "PROPOSED") -> tr.Item:
    return tr.Item(i, title, text, status, "ai", "models", n)


@pytest.mark.parametrize(("title", "group"), [
    ("Sobreestimación sistemática de la probabilidad de empate en 1X2", "p_model_draw"),
    ("Calibrar hacia el mercado la probabilidad de empate en 1X2 (sobreestimación sistemática)", "p_model_draw"),
    ("Encoger p_model hacia el mercado en apuestas al empate y a cuotas largas", "p_model_draw"),
    ("Encoger las probabilidades del modelo hacia el mercado en cuotas altas (>=3.4)", "p_model_high_odds"),
    ("Calibrar p_model en cuotas largas (≥3.5) con encogimiento hacia el mercado", "p_model_high_odds"),
    ("Sobreconfianza del modelo en Under y AH con p_model muy por encima del mercado", "p_model_lines_under_ah"),
    ("Calibrar la probabilidad del modelo en líneas extremas de hándicap asiático y over/under", "p_model_lines_under_ah"),
    ("Las ausencias no reportadas de titulares como feature de alineación", "unreported_absences"),
    ("Señal de 'ausencia no reportada' por titulares habituales como feature", "unreported_absences"),
    ("Cambio de horario (kickoff_changed) como señal de bloqueo o descuento de confianza", "kickoff_changed"),
    ("Los picks con kickoff_changed concentran los errores de ejecución", "kickoff_changed"),
    ("Familia de líneas AH/DC correlacionadas cuenta como una sola apuesta con edge inflado", "correlated_lines"),
    ("El revisor APPROVE con confianza alta y sin señales falla en cuotas altas", "reviewer_too_lenient"),
    ("El revisor rechaza picks con CLV positivo y buen log loss del modelo: auditar su regla de rechazo", "reviewer_too_strict"),
    ("Encoger p_model hacia el mercado cuando la divergencia es muy grande (p_model/p_close > 2)", "p_model_divergence"),
])
def test_the_real_titles_land_in_the_group_they_are_about(title: str, group: str) -> None:
    assert tr.classify(item(1, title))[0] == group


def test_a_signal_and_a_blend_name_their_own_group_and_what_no_rule_reads_is_not_guessed() -> None:
    assert tr.classify(item(1, "La señal 'nothing_to_play_for' anticipa pérdidas: probar exigirla como filtro")) == ("signal:nothing_to_play_for", "exigir_como_filtro")
    assert tr.classify(item(2, "dixon_coles adds information to the close in domestic_cup: test a blend")) == ("blend:dixon_coles:domestic_cup", "mezclar_con_el_cierre")
    assert tr.classify(item(3, "El modelo es peor que el mercado en Serie A")) == (tr.UNCLASSIFIED, "?")


def test_the_same_variable_the_same_way_is_one_group_with_one_representative_and_the_rest_are_merged_into_it() -> None:
    items = [item(10, "Sobreestimación sistemática de la probabilidad de empate en 1X2", n=300), item(11, "Calibración del modelo en empates: p_model sobreestima frente al cierre", n=900),
             item(12, "Sesgo de empate sobrestimado en el modelo en 1X2", n=900)]
    decisions = {d.id: d for d in tr.propose(items)}
    assert decisions[11].destination == "experiment" and decisions[11].rule is None  # most matches, then the oldest
    for i in (10, 12):
        assert (decisions[i].destination, decisions[i].rule, decisions[i].merged_into) == ("archive", "duplicada", 11)
        assert "#11" in decisions[i].reason


def test_only_the_best_evidenced_groups_go_to_experiment_and_the_rest_are_kept_not_discarded() -> None:
    titles = ["Sobreestimación de empate en 1X2", "Cuotas altas: encoger p_model hacia el mercado", "Sobreconfianza del modelo en Under y AH", "Ausencias no reportadas como feature",
              "Cambio de horario (kickoff_changed) como señal", "El revisor rechaza picks con CLV positivo"]
    items = [item(i + 1, t, n=1000 - 100 * i) for i, t in enumerate(titles)]
    decisions = tr.propose(items, max_experiments=3)
    assert [d.destination for d in decisions] == ["experiment", "experiment", "experiment", "keep", "keep", "keep"]
    assert all(d.rule is None for d in decisions), "a group that did not make the cut is kept, never archived for it"


def test_what_no_rule_reads_is_kept_for_a_person() -> None:
    (d,) = tr.propose([item(1, "El modelo es peor que el mercado en Serie A")])
    assert (d.destination, d.rule, d.group) == ("keep", None, tr.UNCLASSIFIED)


def test_the_rules_of_archive_fire_on_what_they_name() -> None:
    weather = item(1, "El clima como feature del modelo de goles")
    lowers = item(2, "Cuotas altas: bajar el umbral de aprobación del revisor para recuperar picks")
    plain_one = item(3, "Cuotas altas: encoger p_model hacia el mercado", n=50)
    d = {x.id: x for x in tr.propose([weather, lowers, plain_one])}
    assert (d[1].destination, d[1].rule) == ("archive", "no_comprobable")
    assert (d[2].destination, d[2].rule) == ("archive", "fuera_de_alcance")
    assert d[3].destination == "experiment"


def test_answered_and_unreachable_come_from_measurements_and_without_them_do_not_fire() -> None:
    items = [item(1, "Sobreestimación de empate en 1X2"), item(2, "Cuotas altas: encoger p_model hacia el mercado")]
    assert {d.rule for d in tr.propose(items)} == {None}
    d = {x.id: x for x in tr.propose(items, answered={"p_model_draw": "EXP-E1"}, unreachable={"p_model_high_odds": "200 partidos por temporada"})}
    assert (d[1].rule, "EXP-E1" in d[1].reason) == ("ya_respondida", True)
    assert (d[2].rule, "200 partidos" in d[2].reason) == ("sin_muestra", True)


def test_a_hypothesis_that_is_not_waiting_is_not_read() -> None:
    items = [item(1, "Sobreestimación de empate en 1X2", status="ACCEPTED"), item(2, "Sobreestimación de empate en 1X2")]
    assert [d.id for d in tr.propose(items)] == [2]


def test_every_waiting_hypothesis_gets_exactly_one_destination_and_the_counts_add_up() -> None:
    items = [item(i, t) for i, t in enumerate(["Sobreestimación de empate", "Calibrar empate", "Empates sobreestimados", "Ausencias no reportadas como feature", "Algo raro", "El clima manda"], 1)]
    decisions = tr.propose(items)
    s = tr.summary(decisions)
    assert sorted(d.id for d in decisions) == [1, 2, 3, 4, 5, 6]
    assert s["total"] == 6 and sum(s["by_destination"].values()) == 6
    assert s["by_rule"]["duplicada"] == 2 and s["by_rule"]["no_comprobable"] == 1
    assert sum(g["n"] for g in s["groups"]) == 6


def test_the_fingerprint_follows_the_proposal_and_the_plain_text_has_no_accents_or_case() -> None:
    a = tr.propose([item(1, "Sobreestimación de empate")])
    b = tr.propose([item(1, "Sobreestimación de empate"), item(2, "Calibrar empate")])
    assert tr.plan_fingerprint(a) == tr.plan_fingerprint(list(a)) != tr.plan_fingerprint(b)
    assert len(tr.plan_fingerprint(a)) == 64
    assert tr.plain("  Cuotas   LARGAS: Sobreestimación ") == "cuotas largas: sobreestimacion"


def test_the_five_rules_of_the_plan_are_the_rules_of_the_code() -> None:
    assert tr.RULES == ("duplicada", "ya_respondida", "no_comprobable", "sin_muestra", "fuera_de_alcance")
    assert tr.UNTRIAGED_LIMIT == 20
