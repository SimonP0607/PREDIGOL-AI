"""RP-4.3: rest, congestion and the next match of each side as calculated facts (``fbi.ai.calendar_facts``). The calendars are built by hand, so every
number is known: the rest counts every competition, the 14 days count the matches outside what PrediGol follows, a calendar that is not whole says so and its numbers
become «a lo sumo» and «al menos», a side with no previous match has no fact, and no fact judges the condition of a team. The database side is
``tests/integration/test_calendar_facts.py``."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fbi.ai import calendar_facts as cf
from fbi.ai import factor_schema
from fbi.ai import stakes_facts as sf
from fbi.competitions import team_calendar as tc

AT = datetime(2026, 11, 26, 12, tzinfo=UTC)
KICKOFF = datetime(2026, 11, 28, 20, tzinfo=UTC)
MATCH = sf.Match(10, KICKOFF, 1, 2)


def played(fid: int, days_before: float, *, followed: bool = True, home: bool = True, competition: str = "Liga", opponent: str = "Rival") -> tc.Match:
    return tc.Match(fid, KICKOFF - timedelta(days=days_before), "finished", followed, home, opponent, competition, "Colombia", "domestic_league", 2026, "R1", 1, 0)


def coming(fid: int, days_after: float, *, competition: str = "Copa") -> tc.Match:
    return tc.Match(fid, KICKOFF + timedelta(days=days_after), "scheduled", False, True, "Otro", competition, "Colombia", "domestic_cup", 2026, "R1", None, None)


def calendar(*matches: tc.Match, fetched: datetime | None = AT - timedelta(hours=6)) -> tc.TeamCalendar:
    return tc.TeamCalendar(team_id=1, at=AT, matches=tuple(sorted(matches, key=lambda m: m.kickoff_at)), fetched_at=fetched)


def test_the_rest_counts_every_competition_and_says_where_the_last_match_was_played() -> None:
    cal = calendar(played(1, 3.0, followed=False, home=False, competition="Copa Libertadores", opponent="Boca"), played(2, 9.0))
    fact = cf.side_fact(cal, MATCH, "home", "Leones")
    assert fact is not None
    assert "3,0 días desde su último partido (Copa Libertadores, fuera, contra Boca)" in fact.claim
    assert fact.calculation["rest_days"] == 3.0 and fact.calculation["previous"]["followed"] is False
    assert "a lo sumo" not in fact.claim and "Calendario incompleto" not in fact.claim


def test_the_fortnight_counts_matches_and_names_those_outside_what_predigol_follows() -> None:
    cal = calendar(played(1, 3.0), played(2, 6.0, followed=False), played(3, 10.0, followed=False), played(4, 13.9), played(5, 15.0))
    fact = cf.side_fact(cal, MATCH, "home", "Leones")
    assert fact is not None
    assert "4 partidos en los 14 días anteriores, 2 en competiciones que PrediGol no sigue" in fact.claim
    assert (fact.calculation["played_14d"], fact.calculation["outside_14d"]) == (4, 2)


def test_the_next_match_is_said_with_its_distance_and_the_four_day_threshold() -> None:
    near = cf.side_fact(calendar(played(1, 3.0), coming(9, 3.0)), MATCH, "away", "Tigres")
    far = cf.side_fact(calendar(played(1, 3.0), coming(9, 5.5)), MATCH, "away", "Tigres")
    none = cf.side_fact(calendar(played(1, 3.0)), MATCH, "away", "Tigres")
    assert near is not None and far is not None and none is not None
    assert "su siguiente partido (Copa) es en 3,0 días, a 4 días o menos" in near.claim and near.calculation["next"]["within_4_days"] is True
    assert "es en 5,5 días" in far.claim and "a 4 días o menos" not in far.claim and far.calculation["next"]["within_4_days"] is False
    assert "siguiente partido" not in none.claim and none.calculation["next"] is None


def test_a_calendar_that_is_not_whole_says_so_and_its_numbers_become_bounds() -> None:
    old_unconfirmed = tc.Match(7, KICKOFF - timedelta(days=3), "scheduled", False, True, "X", "Copa", None, None, None, None, None, None)
    cases = (
        (calendar(played(1, 3.0), fetched=AT - timedelta(days=6)), "el calendario del equipo se leyó hace más de 96 horas"),
        (calendar(played(1, 3.0), fetched=None), "el calendario del equipo nunca se leyó"),
        (calendar(played(1, 3.0), old_unconfirmed), "un partido de las dos últimas semanas sigue sin confirmarse"),
    )
    for cal, why in cases:
        fact = cf.side_fact(cal, MATCH, "home", "Leones")
        assert fact is not None and fact.calculation["whole"] is False
        assert "a lo sumo 3,0 días" in fact.claim and "al menos 1 partido" in fact.claim
        assert f"Calendario incompleto: {why}." in fact.claim


def test_a_side_with_no_previous_match_has_no_fact() -> None:
    assert cf.side_fact(calendar(coming(9, 3.0)), MATCH, "home", "Leones") is None
    assert cf.side_fact(calendar(), MATCH, "home", "Leones") is None


def test_a_fact_describes_the_schedule_and_never_judges_the_condition_of_a_team() -> None:
    fact = cf.side_fact(calendar(played(1, 2.0), played(2, 4.0), played(3, 6.0), coming(9, 3.0)), MATCH, "home", "Leones")
    assert fact is not None
    assert not re.search(r"cansad|fatig|fresc|descansad|rendir|desgast|favorit|ventaja|desventaja", fact.claim, re.I), fact.claim
    assert len(fact.claim) <= cf.MAX_CLAIM


def test_the_item_is_complete_under_the_schema_and_valid_until_kickoff() -> None:
    fact = cf.side_fact(calendar(played(1, 3.0)), MATCH, "home", "Leones")
    assert fact is not None
    item = cf.item_of(fact, at=AT)
    assert (item.kind, item.claim_type, item.origin, item.subject_type, item.subject_id, item.side) == ("schedule", "SCHEDULE", "own_calc", "TEAM", 1, "home")
    assert item.fresh_until == KICKOFF and item.published_at is not None and item.published_at <= AT
    assert factor_schema.missing(item.fact_view()) == []


def test_the_switch_is_born_off() -> None:
    assert cf.mode({}) == "off" and cf.mode({cf.SWITCH: "no"}) == "off" and cf.mode({cf.SWITCH: "1"}) == "on"
