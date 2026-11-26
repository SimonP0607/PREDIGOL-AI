"""RP-10.4: every settlement rule has its words in Spanish and English, the houses' possible differences are marked, and the discrepancy
between card conventions is counted on real cases."""

from __future__ import annotations

import pytest

from fbi.market import rule_text
from fbi.market.rules import RULES, RULES_BY_KEY


def test_every_rule_has_a_text_and_every_text_a_rule() -> None:
    assert {r.key for r in RULES} == set(rule_text.TEXT_BY_KEY)


def test_every_text_is_written_in_both_languages() -> None:
    for t in rule_text.TEXTS:
        assert t.es.strip() and t.en.strip(), t.key
        assert t.es != t.en, f"{t.key}: the two languages are the same text"
        assert bool(t.differ_es) == bool(t.differ_en) == t.may_differ, t.key


def test_the_conventions_the_provider_does_not_state_are_marked() -> None:
    marked = {t.key for t in rule_text.TEXTS if t.may_differ}
    assert {"cards_lines_ft@v1", "cards_lines_1h@v1", "cards_lines_2h@v1", "cards_points_ft@v1", "yellow_ft@v1", "corners_ft@v1"} <= marked
    assert not {"goals_ft@v1", "goals_1h@v1", "shots_ft@v1", "fouls_ft@v1", "offsides_ft@v1", "saves_ft@v1"} & marked


def test_a_card_says_what_it_grades_and_how_a_house_may_differ() -> None:
    c = rule_text.card(RULES_BY_KEY["cards_lines_ft@v1"], "en")
    assert c["may_differ"] and "every card shown counts one" in c["text"] and "house" in c["differ_note"]
    es = rule_text.card(RULES_BY_KEY["goals_ft@v1"])
    assert es["may_differ"] is False and "differ_note" not in es and "90 minutos" in es["text"]


def test_a_rule_without_data_says_so() -> None:
    c = rule_text.card(RULES_BY_KEY["corners_1h@v1"])
    assert c["liquidable"] is False and "no se puede liquidar" in c["text"]


def test_the_cards_listed_are_the_rules_in_force() -> None:
    keys = [c["rule"] for c in rule_text.cards()]
    assert "corners_1h@v1" in keys and "corners_1h@v2" not in keys  # the version behind a switch is not in force
    assert len(rule_text.cards(in_force=False)) == len(RULES)


def test_a_real_case_of_the_two_conventions() -> None:
    # Match A: 3 yellows and a straight red -> PrediGol counts 4 cards; yellows only: 3; the red counting two: 5.
    # Match B: 2 yellows, no dismissal -> every convention says 2.
    # Match C: 4 yellows, 1 red (after a second yellow) -> 5 cards; yellows only 4; red double 6.
    d = rule_text.discrepancy([(4, 3, 1, 1), (2, 2, 0, 1), (5, 4, 1, 1)], lines=(2.5, 3.5, 4.5, 5.5))
    assert d["matches"] == 3
    only_y = d["conventions"]["solo_amarillas"]
    assert only_y["total_differs"] == 2 and only_y["total_differs_pct"] == pytest.approx(0.6667, abs=1e-4)
    # over 3.5: A 4>3.5 yes vs 3>3.5 no -> differs; over 4.5: C 5>4.5 yes vs 4>4.5 no -> differs; 2.5 and 5.5 nobody differs
    assert {k: v["differs"] for k, v in only_y["by_line"].items()} == {"2.5": 0, "3.5": 1, "4.5": 1, "5.5": 0}
    double = d["conventions"]["roja_doble"]
    assert double["total_differs"] == 2
    # over 4.5: A 4 vs 5 differs; over 5.5: C 5 vs 6 differs; over 3.5: all over in both; 2.5 the same
    assert {k: v["differs"] for k, v in double["by_line"].items()} == {"2.5": 0, "3.5": 0, "4.5": 1, "5.5": 1}


def test_without_matches_there_is_no_percentage_invented() -> None:
    d = rule_text.discrepancy([])
    assert d["matches"] == 0
    assert all(c["total_differs_pct"] is None for c in d["conventions"].values())
    assert all(v["pct"] is None for c in d["conventions"].values() for v in c["by_line"].values())
