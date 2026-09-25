"""Match detail is read the way the provider documents it - and nothing is guessed.

Shapes follow the API-Football v3 documentation samples for /fixtures (with
events, lineups, statistics and players), /injuries, /leagues and /standings.
"""

from __future__ import annotations

from decimal import Decimal

from fbi.providers.api_football.details import (
    integer,
    iter_coverage,
    iter_fixture_details,
    iter_injuries,
    iter_standings,
    number,
)

FIXTURE = {
    "fixture": {"id": 215662, "status": {"short": "FT"}},
    "teams": {"home": {"id": 463}, "away": {"id": 1315}},
    "events": [
        {"time": {"elapsed": 25, "extra": None}, "team": {"id": 463}, "player": {"id": 1485, "name": "Bastia"},
         "assist": {"id": None, "name": None}, "type": "Goal", "detail": "Normal Goal", "comments": None},
        {"time": {"elapsed": 90, "extra": 3}, "team": {"id": 1315}, "player": {"id": 3, "name": "X"},
         "assist": {"id": 4, "name": "Y"}, "type": "Card", "detail": "Yellow Card", "comments": "Foul"},
        {"time": {"elapsed": None}, "type": "Goal"},
    ],
    "lineups": [{
        "team": {"id": 463}, "coach": {"id": 2407, "name": "Coach"}, "formation": "4-4-2",
        "startXI": [{"player": {"id": 35931, "name": "Keeper", "number": 13, "pos": "G", "grid": "1:1"}}],
        "substitutes": [{"player": {"id": 5, "name": "Bench", "number": 20, "pos": "D", "grid": None}}],
    }],
    "statistics": [{"team": {"id": 463}, "statistics": [
        {"type": "Shots on Goal", "value": 3}, {"type": "Total Shots", "value": 9},
        {"type": "Ball Possession", "value": "32%"}, {"type": "Goalkeeper Saves", "value": None},
        {"type": "Passes %", "value": "70%"}, {"type": "expected_goals", "value": "1.25"},
        {"type": "Something New", "value": 7},
    ]}],
    "players": [{"team": {"id": 463}, "players": [{"player": {"id": 35931, "name": "Keeper"}, "statistics": [{
        "games": {"minutes": 90, "rating": "6.3", "captain": False, "substitute": False},
        "shots": {"total": None, "on": None}, "goals": {"total": None, "conceded": 1, "saves": 4},
        "passes": {"total": 17, "key": 0, "accuracy": "68%"}, "cards": {"yellow": 0, "red": 0},
    }]}]}],
}


def test_numbers_are_read_not_guessed() -> None:
    assert number("32%") == 32 and number("1.25") == Decimal("1.25") and number(7) == 7
    assert number("") is None and number(None) is None and number("N/A") is None and number(True) is None
    assert integer("7") == 7 and integer("1.5") is None and integer(0) == 0


def test_a_fixture_detail_carries_every_block_it_was_sent() -> None:
    (d,) = iter_fixture_details({"response": [FIXTURE]})
    assert d.provider_fixture_id == 215662
    assert d.blocks_present == {"events", "lineups", "statistics", "players"}
    (stats,) = d.stats
    assert stats.values["shots_on_target"] == 3 and stats.values["shots"] == 9
    assert stats.values["possession_pct"] == 32 and stats.values["expected_goals"] == Decimal("1.25")
    assert stats.values["saves"] is None, "not reported is None, never 0"
    assert "passes_pct" not in stats.values, "derivable, not stored twice"
    assert stats.unknown_types == ("something new",)
    assert [(e.minute, e.extra_minute, e.event_type) for e in d.events] == [(25, None, "Goal"), (90, 3, "Card")]
    assert d.events[1].provider_assist_id == 4 and d.events[1].comments == "Foul"
    (lu,) = d.lineups
    assert lu.formation == "4-4-2" and [(p.provider_player_id, p.is_starter) for p in lu.players] == [
        (35931, True), (5, False)]
    (ps,) = d.players
    assert ps.values["rating"] == Decimal("6.3") and ps.values["saves"] == 4
    assert ps.values["passes_accuracy_pct"] == 68 and ps.values["shots_total"] is None


def test_an_absent_block_is_not_an_empty_one() -> None:
    body = {"response": [{"fixture": {"id": 1}, "events": []}]}
    (d,) = iter_fixture_details(body)
    assert d.blocks_present == {"events"} and d.events == () and d.stats == ()


def test_injuries_coverage_and_standings_follow_the_documented_shapes() -> None:
    (a,) = iter_injuries({"response": [{"player": {"id": 865, "name": "D. Costa", "type": "Missing Fixture",
                                                    "reason": "Broken ankle"}, "team": {"id": 157},
                                         "fixture": {"id": 686314}}]})
    assert (a.provider_player_id, a.provider_fixture_id, a.absence_type) == (865, 686314, "Missing Fixture")
    cov = list(iter_coverage({"response": [{"league": {"id": 39, "name": "Premier League", "type": "League"},
                                            "country": {"name": "England"}, "seasons": [
        {"year": 2010, "start": "2010-08-14", "end": "2011-05-17", "current": False, "coverage": {
            "fixtures": {"events": True, "lineups": True, "statistics_fixtures": False,
                         "statistics_players": False},
            "standings": True, "players": True, "injuries": False, "predictions": True, "odds": False}}]}]}))
    assert len(cov) == 1 and cov[0].flags["statistics_fixtures"] is False and cov[0].flags["events"] is True
    assert cov[0].flags["top_scorers"] is None, "a flag the payload omits is unknown, not false"
    (st,) = iter_standings({"response": [{"league": {"id": 39, "season": 2019, "standings": [[
        {"rank": 1, "team": {"id": 40}, "points": 70, "group": "Premier League", "form": "WWDLW",
         "all": {"played": 29, "win": 22, "draw": 4, "lose": 3, "goals": {"for": 66, "against": 21}}}]]}}]})
    assert (st.rank, st.points, st.goals_for, st.goals_against, st.form) == (1, 70, 66, 21, "WWDLW")
