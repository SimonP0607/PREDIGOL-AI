"""RP-4.2: what each team plays for, as a calculated fact (``fbi.ai.stakes_facts``). The readings are the REAL engine's (``scenarios-v2``) over small
tables whose outcome is known by hand: a secured title, a lost title, an open place, a regulation not coded, a team in no table. A fact is complete under
the schema of RP-4.1, never predicts and never says more than the engine proved. The database side is ``tests/integration/test_stakes_facts.py``."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.ai import factor_schema
from fbi.ai import stakes_facts as sf
from fbi.competitions import rules as rl
from fbi.competitions import scenarios as sc

from .test_scenarios_v2_ia082 import coded, fixtures, make_rules

AT = datetime(2026, 11, 20, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(days=1)
ZONES: list[dict[str, Any]] = [{"kind": "champion", "from": 1, "to": 1}, {"kind": "relegation", "from": 4, "to": 4}]


def reading(results: dict[int, tuple[int, int]], pairs: list[tuple[int, int]], *, focus: tuple[int, ...] = ()) -> dict[str, Any]:
    out = sc.evaluate(coded(make_rules(4, ZONES)), fixtures(pairs, results), at=AT, focus=focus, sims=50)
    out["input_hash"] = "h" * 64
    return out


# the table by hand: team 1 has won everything, team 4 has lost everything, one round (3 matches) is left
PAIRS = [(1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4), (2, 1), (3, 1), (4, 1), (3, 2), (4, 2), (4, 3)]
PLAYED = {0: (3, 0), 1: (3, 0), 2: (3, 0), 3: (1, 0), 4: (1, 0), 5: (1, 0), 6: (0, 2), 7: (0, 2), 8: (0, 2), 9: (0, 0), 10: (0, 0), 11: (0, 0)}
MATCH = sf.Match(10, KICKOFF, 1, 4)
NAMES = {1: "Leones", 4: "Tigres"}


def test_a_secured_title_and_a_lost_relegation_are_said_as_proved() -> None:
    r = reading(PLAYED, PAIRS)
    facts, why = sf.facts_of(r, MATCH, NAMES)
    assert why is None and [f.side for f in facts] == ["home", "away"]
    home, away = facts
    assert "ya tiene asegurado ganar el título" in home.claim and "Leones" in home.claim
    assert "ya no puede ganar el título" in away.claim
    assert "evitar el descenso" in away.claim and "ya no puede" in away.claim
    assert home.calculation["reading_hash"] == "h" * 64 and home.calculation["engine"] == sc.VERSION


def test_what_is_open_comes_first_and_the_points_and_matches_left_are_said() -> None:
    pairs = PAIRS[:-3]  # the last round is not scheduled at all: every team has matches it can still play
    r = reading({k: v for k, v in PLAYED.items() if k < 3}, pairs)
    facts, _ = sf.facts_of(r, sf.Match(1, KICKOFF, 2, 3), {2: "Dos", 3: "Tres"})
    assert facts
    claim = facts[0].claim
    assert re.search(r"\d+ puntos y \d+ partidos? por jugar", claim)
    assert "sigue en juego ganar el título" in claim and "ya no puede" not in claim


def test_a_regulation_not_coded_and_a_missing_reading_produce_no_fact_and_say_why() -> None:
    uncoded = sc.evaluate(rl.NotCoded(9999, 2026, "not_yet_coded", "none"), [], at=AT)
    assert sf.facts_of(uncoded, MATCH, NAMES) == ([], sc.NOT_CODED)
    assert sf.facts_of(None, MATCH, NAMES) == ([], "no_reading")


def test_a_team_in_no_table_gets_no_fact() -> None:
    r = reading(PLAYED, PAIRS)
    facts, why = sf.facts_of(r, sf.Match(10, KICKOFF, 77, 88), {})
    assert (facts, why) == ([], "no_table")


def test_nothing_at_stake_is_said_only_when_the_engine_proved_it() -> None:
    r = reading(PLAYED, PAIRS)
    r["teams"]["1"] = {"hecho": sc.FACT_NO_OBJECTIVE, "demostrado": True, "motivos": []}
    fact = sf.fact_of(r, MATCH, "home", "Leones")
    assert fact is not None and sc.FACT_NO_OBJECTIVE in fact.claim and fact.calculation["no_objective"] is True
    r["teams"]["1"] = {"hecho": None, "demostrado": False, "motivos": ["objetivo_abierto:x"]}
    other = sf.fact_of(r, MATCH, "home", "Leones")
    assert other is not None and sc.FACT_NO_OBJECTIVE not in other.claim and other.calculation["no_objective"] is False


def test_a_conditional_zone_is_never_said_as_decided() -> None:
    r = reading(PLAYED, PAIRS)
    for t in r["tables"]:
        for row in t["teams"]:
            for o in row["objetivos"]:
                o["condicional"] = True
    fact = sf.fact_of(r, MATCH, "home", "Leones")
    assert fact is not None and "depende de otra competición y no está decidido" in fact.claim
    assert "ya tiene asegurado" not in fact.claim and "ya no puede" not in fact.claim


def test_the_effect_of_each_result_of_this_match_travels_in_the_calculation() -> None:
    pairs = PAIRS[:-3]
    r = reading({k: v for k, v in PLAYED.items() if k < 3}, pairs, focus=(4,))
    fact = sf.fact_of(r, sf.Match(4, KICKOFF, 2, 3), "home", "Dos")
    assert fact is not None
    assert fact.calculation["by_result"], "the engine read the three results of this match"


def test_a_fact_says_a_situation_never_a_prediction() -> None:
    r = reading(PLAYED, PAIRS)
    facts, _ = sf.facts_of(r, MATCH, NAMES)
    forbidden = re.compile(r"rendir|motivad|ganará|perderá|favorit|probable|se espera|deber[ií]a|presi[oó]n|nada que perder", re.I)
    for f in facts:
        assert not forbidden.search(f.claim), f.claim
        assert len(f.claim) <= sf.MAX_CLAIM
        assert f.relevance <= 1


def test_the_item_is_complete_under_the_schema_of_a_context_fact() -> None:
    r = reading(PLAYED, PAIRS)
    facts, _ = sf.facts_of(r, MATCH, NAMES)
    for f in facts:
        item = sf.item_of(f, at=AT)
        assert (item.kind, item.origin, item.fact_schema, item.subject_type, item.subject_id) == ("stakes", "own_calc", factor_schema.VERSION, "TEAM", f.team)
        assert item.fresh_until == KICKOFF and item.side == f.side and item.attributes["calculation"] == sf.VERSION
        assert factor_schema.missing(item.fact_view()) == []
        assert factor_schema.category_of("PROBABLE", item.origin) == "hecho_confirmado"


def test_the_switch_is_born_off() -> None:
    assert sf.mode({}) == "off"
    assert sf.mode({sf.SWITCH: "maybe"}) == "off"
    assert sf.mode({sf.SWITCH: "ON"}) == "on"


@pytest.mark.parametrize("n,expected", [(1, "1 partido"), (2, "2 partidos")])
def test_the_sentence_agrees_in_number(n: int, expected: str) -> None:
    s = sf.Stake("t", 1, 3, 20, n, ("ascender",), (), (), ())
    assert expected in sf.sentence(s, name="Equipo", multiple=False)


def test_two_objectives_of_one_kind_say_how_far_up_each_is_so_the_sentence_never_names_one_thing_twice() -> None:
    """A table with two continental places (as the Brazilian league has) used to say «ya tiene asegurado lograr una plaza continental, lograr una plaza
    continental» and, with one secured and one open, «sigue en juego lograr una plaza continental; ya tiene asegurado lograr una plaza continental»."""
    row = {"team": 7, "puesto": 3, "puntos": 66, "partidos_restantes": 2, "objetivos": [
        {"objetivo": "plaza_continental", "terminar_entre_los": 4, "estado": "conseguido", "decidido": {"demostrado": True}},
        {"objetivo": "plaza_continental", "terminar_entre_los": 2, "estado": "abierto", "decidido": {"demostrado": False}},
        {"objetivo": "evitar_descenso", "terminar_entre_los": 16, "estado": "conseguido", "decidido": {"demostrado": True}}]}
    reading_ = {"status": "ok", "tables": [{"key": "liga", "teams": [row]}]}
    (stake,) = sf.stakes_of(reading_, 7)
    assert stake.secured == ("lograr una plaza continental (entre los 4 primeros)", "evitar el descenso")
    assert stake.open == ("lograr una plaza continental (entre los 2 primeros)",)
    text = sf.sentence(stake, name="Cruzeiro", multiple=False)
    assert "sigue en juego lograr una plaza continental (entre los 2 primeros)" in text
    assert "ya tiene asegurado lograr una plaza continental (entre los 4 primeros) y evitar el descenso" in text


def test_an_objective_alone_in_its_kind_keeps_its_plain_phrase() -> None:
    row = {"team": 7, "puesto": 1, "puntos": 10, "partidos_restantes": 1, "objetivos": [
        {"objetivo": "titulo", "terminar_entre_los": 1, "estado": "abierto", "decidido": {"demostrado": False}}]}
    (stake,) = sf.stakes_of({"status": "ok", "tables": [{"key": "liga", "teams": [row]}]}, 7)
    assert stake.open == ("ganar el título",)
