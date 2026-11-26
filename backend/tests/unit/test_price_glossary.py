"""RP-10.1: the ten concepts of price have one definition each in both languages, the two references of the market have their names, the fields C-14 gives them
exist, and the numbers a selection carries agree with each other (``fbi.market.price_glossary``, ``scripts/ia_price_concepts``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from scripts import ia_price_concepts as cli

from fbi.api.contracts.intelligence.market_probs import Implied, MarketMarks, SelectionMarks
from fbi.api.services import market_probs as mp
from fbi.market import price_glossary as pg
from fbi.market.rule_text import TEXT_BY_KEY

MOMENT = datetime(2034, 3, 1, 12, tzinfo=UTC)


def test_there_are_ten_concepts_each_with_both_languages_and_a_place_where_it_lives() -> None:
    assert len(pg.CONCEPTS) == pg.KEY_COUNT == 10 and len({c.key for c in pg.CONCEPTS}) == 10
    for c in pg.CONCEPTS:
        assert all(x.strip() for x in (c.es, c.en, c.definition_es, c.definition_en, c.lives_in)), c.key
    assert [r.key for r in pg.REFERENCES] == ["previous", "real_close"]
    assert "tres horas" in pg.REFERENCES[0].definition_es and "última hora" in pg.REFERENCES[1].definition_es


def test_the_validated_probability_is_said_not_to_exist_yet() -> None:
    (c,) = [c for c in pg.CONCEPTS if c.key == "validated_probability"]
    assert not c.exists_today and c.contract_field is None and "Hoy no existe ninguna" in c.definition_es
    assert all(c.exists_today for c in pg.CONCEPTS if c.key != "validated_probability")


def test_every_field_the_glossary_names_exists_in_the_contract() -> None:
    fields = {
        "implied.value": "value" in Implied.model_fields, "implied.fair_odds": "fair_odds" in Implied.model_fields,
        "implied.books": "books" in Implied.model_fields, "best_implied": "best_implied" in SelectionMarks.model_fields,
        "best_odds": "best_odds" in SelectionMarks.model_fields, "price_age_minutes": "price_age_minutes" in SelectionMarks.model_fields,
        "settlement": "settlement" in MarketMarks.model_fields}
    named = {c.contract_field for c in pg.CONCEPTS if c.contract_field}
    assert named <= set(fields) and all(fields[f] for f in named), {f for f in named if not fields.get(f)}


def test_the_card_serves_each_language() -> None:
    es, en = pg.card("es"), pg.card("en")
    assert len(es) == len(en) == 10 and es[3]["name"] == "Cuota justa equivalente" and en[3]["name"] == "Equivalent fair odds"
    assert pg.references("en")[1]["name"] == "Real close"


def test_the_builder_says_the_fair_odds_the_age_and_the_reference() -> None:
    imp = mp._implied((0.4, 7, MOMENT - timedelta(minutes=12, seconds=30)), MOMENT)
    assert imp.reference == "consenso_vigente" and imp.fair_odds == 2.5 and imp.age_minutes == 12 and imp.books == 7
    edge = mp._implied((1.0, 3, MOMENT), MOMENT)
    assert edge.fair_odds is None, "a probability of one has no fair odds above one"
    assert mp._age_minutes(MOMENT + timedelta(minutes=5), MOMENT) == 0, "a capture dated after the moment never gives a negative age"


def test_the_settlement_text_comes_from_the_rule_and_a_market_without_a_rule_has_none() -> None:
    s = mp._settlement("goals_ft@v1")
    assert s is not None and s.rule == "goals_ft@v1" and s.text_es and s.text_en and s.may_differ is False and s.differ_es is None
    assert mp._settlement(None) is None and mp._settlement("no_such@v9") is None
    cards = [k for k, t in TEXT_BY_KEY.items() if t.may_differ]
    assert cards and mp._settlement(cards[0]) is not None and mp._settlement(cards[0]).may_differ is True  # type: ignore[union-attr]


def selection(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"selection": "Home", "best_odds": 2.0, "best_implied": 0.5, "price_age_minutes": 3,
                            "implied": {"value": 0.4, "books": 5, "as_of": "x", "reference": "consenso_vigente", "fair_odds": 2.5, "age_minutes": 3}}
    return base | over


def test_a_coherent_selection_has_no_problem_and_carries_eight_concepts() -> None:
    sel, market = selection(), {"settlement": {"rule": "goals_ft@v1"}}
    assert pg.problems(sel) == []
    assert pg.present(sel, market) == {"fair_probability", "houses", "fair_odds", "implied_probability", "best_price", "current_odds", "price_age",
                                       "settlement_rule"}


def test_the_incoherences_are_named() -> None:
    assert pg.problems(selection(implied={"value": 0.4, "books": 5, "fair_odds": 3.0})) == ["fair_odds is not one over the fair probability"]
    assert "a fair price from fewer than three houses" in pg.problems(selection(implied={"value": 0.4, "books": 2, "fair_odds": 2.5}))
    assert pg.problems(selection(best_implied=0.7)) == ["best_implied is not one over best_odds"]
    assert pg.problems(selection(price_age_minutes=-1)) == ["a negative age"]
    assert pg.problems({"selection": "x", "best_odds": 2.0, "implied": {"missing_reason": "sin_datos"}}) == [], "an absent concept is not a problem"


def test_the_report_counts_what_travels_and_says_which_concepts_the_board_cannot_produce() -> None:
    answer = {"markets": {"items": [{"settlement": {"rule": "x"}, "selections": [selection(), selection(selection="Draw")]}]}}
    doc = cli.report([answer, {"markets": {"items": []}}])
    assert doc["matches"] == 2 and doc["selections"] == 2 and doc["matches_with_all_producible"] == 1 and doc["coherent"] is True
    assert doc["not_produced_by_the_board"] == ["publication_odds", "validated_probability"]
    assert doc["carried"]["fair_odds"] == 2
    bad = cli.report([{"markets": {"items": [{"selections": [selection(best_implied=0.9)]}]}}])
    assert bad["coherent"] is False and "\n".join(cli.lines(bad)).count("best_implied") == 1
