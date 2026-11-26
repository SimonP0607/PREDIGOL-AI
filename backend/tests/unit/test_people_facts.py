"""RP-4.4 (first tranche): the coach, the usual formation and the referee of a match as calculated context facts (``fbi.ai.people_facts``). Pure functions over
small inputs known by hand: a fact says what the sheets and the provider say and no more; too little evidence gives no fact; every fact is complete under the
schema of RP-4.1. The database side is ``tests/integration/test_people_facts.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.ai import factor_schema
from fbi.ai import people_facts as pf
from fbi.people import current_coach, officials

AT = datetime(2026, 11, 20, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(days=1)
MATCH = pf.Match(10, KICKOFF, 1, 2)


def coach(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"coach_name": "M. Entrenador", "source": "lineup", "since": "2026-10-10", "as_of": "2026-11-15", "streak": 5, "fresh": True,
                            "fixture_id": 77, "rules_version": current_coach.RULES_VERSION}
    return {**base, **over}


def sheets(*formations: str | None) -> list[dict[str, Any]]:
    return [{"kickoff_at": AT - timedelta(days=7 * (i + 1)), "formation": f} for i, f in enumerate(formations)]


def referee(identity: str | None = officials.ID, **over: Any) -> officials.RefereeAsOf:
    base: dict[str, Any] = {"identity": identity, "name": "A. Arbitro", "referee_id": 5 if identity == officials.ID else None, "country": "Argentina",
                            "spelling": "Árbitro, A.", "seen_at": AT - timedelta(hours=20), "placed": True}
    return officials.RefereeAsOf(**{**base, **over})


def test_the_coach_is_said_with_the_match_he_started_and_the_days_since() -> None:
    fact = pf.coach_fact(coach(), MATCH, "home", "Leones")
    assert fact is not None and fact.kind == "coach" and fact.side == "home" and fact.team == 1
    assert "Leones: en el banquillo M. Entrenador desde el partido del 2026-10-10" in fact.claim
    assert "42 días antes de este partido" in fact.claim and "5 planillas seguidas" in fact.claim and "al menos" not in fact.claim
    assert fact.calculation["days"] == 42 and fact.calculation["at_least"] is False and fact.calculation["coach"] == "M. Entrenador"


def test_a_run_that_fills_the_window_is_said_at_least_and_a_stale_sheet_is_said_too() -> None:
    long = pf.coach_fact(coach(since="2025-11-01", streak=40), MATCH, "away", "Tigres")
    assert long is not None and "al menos" in long.claim and long.calculation["at_least"] is True and long.team == 2
    stale = pf.coach_fact(coach(fresh=False, as_of="2026-07-01"), MATCH, "home", "Leones")
    assert stale is not None and "de hace más de" in stale.claim and "2026-07-01" in stale.claim
    one = pf.coach_fact(coach(streak=1), MATCH, "home", "Leones")
    assert one is not None and "1 planilla seguida" in one.claim


@pytest.mark.parametrize("over", [{"coach_name": None}, {"source": "provider_career"}, {"since": None}, {"as_of": None}, {"source": None}])
def test_a_team_without_a_coach_on_a_sheet_has_no_coach_fact(over: dict[str, Any]) -> None:
    assert pf.coach_fact(coach(**over), MATCH, "home", "Leones") is None


def test_the_usual_formation_is_the_most_used_and_the_blank_sheets_are_counted() -> None:
    fact = pf.formation_fact(sheets("4-3-3", "4-3-3", "4-2-3-1", "4-3-3", None, "4-3-3"), MATCH, "home", "Leones")
    assert fact is not None and fact.kind == "formation"
    assert "formación más usada 4-3-3, en 4 de sus últimas 5 planillas con formación" in fact.claim and "1 planilla sin formación" in fact.claim
    assert fact.calculation["usual"] == "4-3-3" and fact.calculation["formations"] == {"4-3-3": 4, "4-2-3-1": 1} and fact.calculation["blank"] == 1
    assert fact.published_at == AT - timedelta(days=7), "a fact is as old as the newest sheet it read"


def test_a_tie_between_formations_is_said_as_no_dominant_one() -> None:
    fact = pf.formation_fact(sheets("4-3-3", "4-4-2", "4-3-3", "4-4-2"), MATCH, "away", "Tigres")
    assert fact is not None and "sin una dominante" in fact.claim and "4-3-3 y 4-4-2" in fact.claim and fact.calculation["usual"] is None


def test_fewer_sheets_with_a_formation_than_a_habit_needs_give_no_fact() -> None:
    assert pf.formation_fact(sheets("4-3-3", "4-3-3", "4-3-3"), MATCH, "home", "Leones") is None
    assert pf.formation_fact(sheets("4-3-3", None, "4-3-3", None, "  ", "4-3-3"), MATCH, "home", "Leones") is None
    assert pf.formation_fact([], MATCH, "home", "Leones") is None


def test_the_referee_is_said_as_the_person_or_as_the_text_the_provider_wrote() -> None:
    person = pf.referee_fact(referee(), MATCH, "Leones", "Tigres", at=AT)
    assert person is not None and person.kind == "referee" and person.side == "match" and person.team is None
    assert person.claim == "Árbitro de Leones contra Tigres: Árbitro, A., de Argentina; identificado como persona (visto el 2026-11-19)."
    assert person.calculation["hours_before_kickoff"] == 44.0 and person.published_at == AT - timedelta(hours=20)
    text = pf.referee_fact(referee(officials.TEXT, name="X. Y.", spelling=None, country=None), MATCH, "Leones", "Tigres", at=AT)
    assert text is not None and "X. Y.; tal como lo escribió el proveedor, sin identificar" in text.claim


def test_nobody_named_is_no_referee_fact() -> None:
    assert pf.referee_fact(referee(None, name=None), MATCH, "Leones", "Tigres", at=AT) is None


def test_every_fact_is_complete_under_the_schema_and_valid_until_kickoff() -> None:
    made = [pf.coach_fact(coach(), MATCH, "home", "Leones"), pf.formation_fact(sheets("4-3-3", "4-3-3", "4-3-3", "4-3-3"), MATCH, "away", "Tigres"),
            pf.referee_fact(referee(), MATCH, "Leones", "Tigres", at=AT)]
    for fact in made:
        assert fact is not None
        item = pf.item_of(fact, at=AT)
        assert item.origin == "own_calc" and item.kind in factor_schema.KINDS and item.side in factor_schema.SIDES
        assert item.fact_schema == factor_schema.VERSION and item.fresh_until == KICKOFF and item.subject_type in ("TEAM", "MATCH")
        assert item.attributes["calculation"] == pf.VERSION and len(item.claim) <= pf.MAX_CLAIM
    keys = {pf.item_of(f, at=AT).story_key for f in made if f is not None}
    assert keys == {"coach:10:1", "formation:10:2", "referee:10"}


def test_the_switch_is_off_unless_it_says_on() -> None:
    assert pf.mode({}) == "off" and pf.mode({pf.SWITCH: "0"}) == "off" and pf.mode({pf.SWITCH: "maybe"}) == "off"
    assert pf.mode({pf.SWITCH: "on"}) == "on" and pf.mode({pf.SWITCH: " 1 "}) == "on"
