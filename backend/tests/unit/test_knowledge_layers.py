"""Match Knowledge, layer by layer (plan F7, ``mk-v1``): a synthetic match, built the way the stored facts would build it.

Every test starts from the same finished match - Home 2, Away 1, a penalty and a second yellow among its events - and changes one thing
at a time, so that what a test asserts is what that change did to which layer."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.intel import tactics
from fbi.knowledge import events as ev
from fbi.knowledge import layers as mk
from fbi.knowledge.events import RawEvent

KICKOFF = datetime(2034, 4, 1, 12, tzinfo=UTC)
FETCHED = KICKOFF + timedelta(hours=3)
HOME, AWAY = 10, 20


def raw(seq: int, minute: int, side: str, kind: str, detail: str | None = None, *, player: int | None = None, name: str | None = None,
        assist: int | None = None, extra: int | None = None, comments: str | None = None) -> RawEvent:
    return RawEvent(seq=seq, minute=minute, extra_minute=extra, side=side, event_type=kind, detail=detail, comments=comments, player_id=player,
                    player_name=name or (f"P{player}" if player else None), assist_id=assist, assist_name=f"P{assist}" if assist else None)


def the_events() -> list[RawEvent]:
    return [
        raw(0, 23, "home", "Goal", "Normal Goal", player=101, assist=102),
        raw(1, 40, "away", "Card", "Yellow Card", player=201),
        raw(2, 55, "away", "Goal", "Normal Goal", player=202),
        raw(3, 60, "home", "subst", "Substitution 1", player=103, assist=104),
        raw(4, 70, "away", "subst", "Substitution 1", player=203, assist=204),
        raw(5, 78, "home", "Goal", "Penalty", player=101),
        raw(6, 85, "away", "Card", "Yellow Card", player=201),
        raw(7, 85, "away", "Card", "Red Card", player=201),
    ]


def stats(side: str, **values: Any) -> mk.TeamStats:
    base: dict[str, Any] = {"shots": 12, "shots_on_target": 5, "corners": 6, "fouls": 11, "yellow_cards": 0, "red_cards": 0,
                            "possession_pct": Decimal("55.0"), "expected_goals": Decimal("1.834")}
    return mk.TeamStats(side=side, values={**base, **values}, fetched_at=FETCHED)


def player(pid: int, side: str, minutes: int | None, rating: float | None, *, substitute: bool = False, captain: bool = False,
           goals: int | None = None, assists: int | None = None) -> mk.PlayerStat:
    return mk.PlayerStat(player_id=pid, side=side, name=f"P{pid}", minutes=minutes, rating=rating, captain=captain, substitute=substitute,
                        goals=goals, assists=assists, fetched_at=FETCHED)


def quote(market: str, selection: str, p: float, hours_before: float, *, line: int | float | str = 0, books: int = 20) -> mk.Quote:
    return mk.Quote(market=market, selection=selection, line=Decimal(str(line)), p_fair=p, books=books,
                   as_of=KICKOFF - timedelta(hours=hours_before))


def last(market: str, selection: str, odds: float, *, line: int | float | str = 0, books: int = 8, minutes_before: int = 85) -> mk.FinalQuote:
    """The provider's last pre-match price of a selection, read after the match."""
    return mk.FinalQuote(market=market, selection=selection, line=Decimal(str(line)), odds=odds, books=books,
                        as_of=KICKOFF - timedelta(minutes=minutes_before), fetched_at=FETCHED)


def decision(did: int, market: str, selection: str, state: str, *, line: int | float | str = 0, checkpoint: str = "T-1h",
             hours_before: float = 1, score: float | None = None, odds: float | None = 2.0, result: str | None = None,
             profit: float | None = None, clv: float | None = None) -> mk.Decision:
    return mk.Decision(id=did, checkpoint=checkpoint, market=market, selection=selection, line=Decimal(str(line)), state=state,
                      known_at=KICKOFF - timedelta(hours=hours_before), score=score, odds=odds, p_cal=0.52, edge_cal=0.04,
                      stake=0.5 if state in mk.LEAN_STATES else 0.0, result=result, profit=profit, clv=clv,
                      outcome_at=FETCHED if result else None)


def the_match() -> mk.Inputs:
    return mk.Inputs(
        fixture=mk.Fixture(id=1, kickoff_at=KICKOFF, status="FT", home_team_id=HOME, away_team_id=AWAY),
        result=mk.Result(goals_home=2, goals_away=1, reg_home=2, reg_away=1, settled_at=FETCHED, ht_home=1, ht_away=0, fetched_at=FETCHED),
        team_stats=[stats("home"), stats("away", yellow_cards=2, red_cards=1, possession_pct=Decimal("45.0"), expected_goals=None)],
        events=the_events(), events_fetched_at=FETCHED,
        players=[
            player(101, "home", 90, 8.4, goals=2, captain=True), player(102, "home", 90, 7.1, assists=1), player(103, "home", 60, 6.5),
            player(104, "home", 30, 6.9, substitute=True), player(105, "home", None, None, substitute=True),
            player(201, "away", 85, 5.8), player(202, "away", 90, 7.9, goals=1, captain=True), player(203, "away", 70, 6.1),
            player(204, "away", 20, None, substitute=True),
        ],
        lineups=[mk.Lineup("home", "4-3-3", 7001, "A. Coach", FETCHED), mk.Lineup("away", "4-4-2", None, " B   Coach ", FETCHED)],
        open_quotes=[quote("1X2", "Home", 0.50, 150), quote("1X2", "Draw", 0.27, 150), quote("1X2", "Away", 0.23, 150),
                     quote("OU", "Over", 0.52, 150, line="2.5"), quote("OU", "Under", 0.48, 150, line="2.5"),
                     quote("BTTS", "Yes", 0.55, 150), quote("BTTS", "No", 0.45, 150)],
        close_quotes=[quote("1X2", "Home", 0.55, 0.2), quote("1X2", "Draw", 0.26, 0.2), quote("1X2", "Away", 0.19, 0.2),
                      quote("OU", "Over", 0.50, 0.2, line="2.5"), quote("OU", "Under", 0.50, 0.2, line="2.5"),
                      quote("BTTS", "Yes", 0.53, 0.2), quote("BTTS", "No", 0.47, 0.2)],
        final_quotes=[last("1X2", "Home", 1.8), last("1X2", "Draw", 3.6), last("1X2", "Away", 5.0),
                      last("OU", "Over", 2.0, line="2.5"), last("OU", "Under", 1.85, line="2.5"),
                      last("BTTS", "Yes", 1.8), last("BTTS", "No", 1.95)],
        decisions=[
            decision(4, "1X2", "Home", "CAUTELA", score=61.2, checkpoint="T-3h", hours_before=3, result="win", profit=1.0, clv=0.03),
            decision(1, "1X2", "Home", "APROBADO", score=70.1, result="win", profit=1.0, clv=0.03),
            decision(2, "OU", "Over", "RECHAZADO", line="2.5", result="win", profit=1.0),
            decision(3, "BTTS", "No", "INVESTIGACION", result="loss", profit=-1.0),
        ],
        picks=[mk.PickTally("1X2", "win", 3, 2.4, FETCHED), mk.PickTally("1X2", "loss", 2, -2.0, FETCHED), mk.PickTally("OU", "win", 1, 0.9, FETCHED)],
        postmortems=[mk.Postmortem(id=9, decision_id=1, version="pm-v3", outcome="won", quality="GOOD", verdict="MERECIDO", created_at=FETCHED + timedelta(hours=20),
                                  causes=("price_beat_close",))],
    )


def result_of(inp: mk.Inputs) -> mk.Result:
    """The result of a match built by ``the_match`` (which always has one), for the tests that change a figure of it."""
    assert inp.result is not None
    return inp.result


def layer(k: mk.Knowledge, name: str) -> dict[str, Any]:
    return k.layers[name]


# ── a complete match ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_complete_match_has_every_layer_and_says_so() -> None:
    k = mk.build(the_match())
    assert list(k.layers) == list(mk.LAYERS)
    assert {n: layer(k, n)["status"] for n in mk.LAYERS} == {
        "c1_result": "ok", "c2_team_stats": "ok", "c3_events": "ok", "c4_players": "ok", "c5_tactics": "ok", "c6_market": "ok",
        "c7_context": "off", "c8_picks": "ok", "c9_postmortem": "ok"}
    assert k.completeness == "complete" and k.version == "mk-v1"
    assert k.quality == {"layers": {n: layer(k, n)["status"] for n in mk.LAYERS}, "events_give_the_score": True, "doubts": []}
    assert len(k.content_hash) == 64 and len(mk.digest("x")) == 64


def test_the_result_says_the_score_of_the_ninety_minutes_and_how_it_was_decided() -> None:
    data = layer(mk.build(the_match()), "c1_result")["data"]
    assert data == {"status": "FT", "kickoff": "2034-04-01T12:00:00Z", "reg": [2, 1], "outcome": "Home", "total": 3, "btts": True,
                    "decided_by": "regulation", "ht": [1, 0]}


def test_a_match_decided_in_extra_time_and_from_the_spot_keeps_all_its_scores() -> None:
    inp = the_match()
    events = [
        raw(0, 30, "home", "Goal", "Normal Goal", player=101), raw(1, 70, "away", "Goal", "Normal Goal", player=202),
        raw(2, 105, "home", "Goal", "Normal Goal", player=103), raw(3, 112, "away", "Goal", "Normal Goal", player=203),
        raw(4, 120, "home", "Goal", "Penalty", player=101, comments="Penalty Shootout", extra=1),
        raw(5, 120, "away", "Goal", "Missed Penalty", player=202, comments="Penalty Shootout", extra=2),
        raw(6, 120, "home", "Goal", "Penalty", player=103, comments="Penalty Shootout", extra=3),
        raw(7, 120, "away", "Goal", "Penalty", player=203, comments="Penalty Shootout", extra=4),
    ]
    result = mk.Result(goals_home=2, goals_away=2, reg_home=1, reg_away=1, settled_at=FETCHED, ht_home=1, ht_away=0, et_home=1, et_away=1,
                      pen_home=2, pen_away=1, fetched_at=FETCHED)
    quiet = [stats("home"), stats("away")]        # no cards in this one
    k = mk.build(replace(inp, fixture=replace(inp.fixture, status="PEN"), result=result, events=events, team_stats=quiet))
    c1, c3 = layer(k, "c1_result")["data"], layer(k, "c3_events")
    assert c1["reg"] == [1, 1] and c1["final"] == [2, 2] and c1["pen"] == [2, 1] and c1["decided_by"] == "penalties"
    assert c3["status"] == "ok"
    assert c3["data"]["by_period"] == {"1H": [1, 0], "2H": [0, 1], "ET": [1, 1], "PEN": [2, 1]}
    assert c3["data"]["check"] == {"reg": True, "ht": True, "et": True, "pen": True, "cards": True}
    assert [e["kind"] for e in c3["data"]["shootout"]] == ["shootout_goal", "shootout_miss", "shootout_goal", "shootout_goal"]
    assert c3["data"]["counts"]["shootout_goal"] == 3 and "goals" in c3["data"]
    assert all(e["period"] != "PEN" for e in c3["data"]["goals"]), "a kick of the shoot-out is not a goal of the match"


def test_a_match_decided_in_extra_time_alone() -> None:
    inp = the_match()
    result = mk.Result(goals_home=2, goals_away=1, reg_home=1, reg_away=1, settled_at=FETCHED, ht_home=0, ht_away=0, et_home=1, et_away=0)
    events = [raw(0, 50, "home", "Goal", "Normal Goal", player=101), raw(1, 80, "away", "Goal", "Normal Goal", player=202),
              raw(2, 101, "home", "Goal", "Normal Goal", player=103)]
    k = mk.build(replace(inp, fixture=replace(inp.fixture, status="AET"), result=result, events=events, team_stats=[stats("home"), stats("away")]))
    assert layer(k, "c1_result")["data"]["decided_by"] == "extra_time"
    assert layer(k, "c3_events")["data"]["by_period"] == {"1H": [0, 0], "2H": [1, 1], "ET": [1, 0]}
    assert layer(k, "c3_events")["data"]["check"] == {"reg": True, "ht": True, "et": True, "cards": True}


# ── the events ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_events_are_read_by_the_rules_and_listed_by_what_they_are() -> None:
    c3 = layer(mk.build(the_match()), "c3_events")
    data = c3["data"]
    assert data["rules"] == "events-v1" and data["n"] == 8
    assert data["counts"] == {"goal": 2, "penalty_goal": 1, "yellow": 2, "second_yellow": 1, "sub": 2}
    assert data["by_period"] == {"1H": [1, 0], "2H": [1, 1]}
    assert [(e["minute"], e["kind"], e["side"]) for e in data["goals"]] == [(23, "goal", "home"), (55, "goal", "away"), (78, "penalty_goal", "home")]
    assert [(e["minute"], e["kind"]) for e in data["cards"]] == [(40, "yellow"), (85, "yellow"), (85, "second_yellow")]
    pair = [e for e in data["cards"] if e["minute"] == 85]
    assert pair[0]["pair"] == pair[1]["seq"] and pair[1]["pair"] == pair[0]["seq"], "the two lines of a dismissal for two yellows are linked"
    assert "sub" not in {e["kind"] for k in ("goals", "cards") for e in data[k]}, "a substitution is counted, not listed"


def test_an_own_goal_counts_for_the_side_that_gets_it_and_is_the_other_sides_man() -> None:
    inp = the_match()
    events = the_events()
    events[5] = raw(5, 78, "home", "Goal", "Own Goal", player=205)     # filed under the team that gets the goal
    k = mk.build(replace(inp, events=events))
    goals = layer(k, "c3_events")["data"]["goals"]
    own = next(g for g in goals if g["kind"] == "own_goal")
    assert own["side"] == "home" and own["player_side"] == "away" and own["player"] == 205
    assert layer(k, "c3_events")["status"] == "ok", "it still gives the score: 2-1"
    story = layer(k, "c5_tactics")["data"]["story"]
    assert story["first_goal"] == {"minute": 23, "side": "home"}


def test_events_that_do_not_give_the_score_are_kept_but_not_trusted() -> None:
    inp = the_match()
    k = mk.build(replace(inp, events=the_events()[:1] + the_events()[1:2] + the_events()[3:]))      # the away goal is missing from the list
    c3 = layer(k, "c3_events")
    assert c3["status"] == "partial" and "events_do_not_give_the_score" in c3["notes"]
    assert c3["data"]["check"]["reg"] is False and c3["data"]["check"]["listed"] == [2, 0]
    assert k.quality["events_give_the_score"] is False and "events_do_not_give_the_score" in k.quality["doubts"]
    assert k.completeness == "partial"
    c5 = layer(k, "c5_tactics")
    assert "story" not in c5["data"] and "story_not_told" in c5["notes"], "no story is told from a list that does not give the score"
    assert c5["data"]["home"]["subs"] == [[60, None]], "the substitutions are still there, with no lead"


def test_the_break_the_extra_time_and_the_cards_are_checked_against_what_the_provider_said_of_them() -> None:
    inp = the_match()
    k = mk.build(replace(inp, result=replace(result_of(inp), ht_home=0, ht_away=0)))             # the break score the lists do not give
    c3 = layer(k, "c3_events")
    assert c3["data"]["check"]["ht"] is False and "ht_differs" in c3["notes"] and c3["status"] == "partial"
    k = mk.build(replace(inp, team_stats=[stats("home"), stats("away", yellow_cards=1, red_cards=1)]))
    assert layer(k, "c3_events")["data"]["check"]["cards"] is False
    assert layer(k, "c3_events")["status"] == "ok", "a disagreement over the cards does not shake the goals"
    assert "cards_differ_from_the_statistics" in k.quality["doubts"]


def test_a_goal_with_nobody_in_it_still_counts_and_says_so() -> None:
    inp = the_match()
    events = the_events()
    events[0] = raw(0, 23, "home", "Goal", "Normal Goal")
    k = mk.build(replace(inp, events=events))
    assert layer(k, "c3_events")["status"] == "ok"
    assert layer(k, "c4_players")["data"]["goals_with_no_player"] == 1
    assert "lines_with_no_player" in k.quality["doubts"]


def test_no_events_is_a_missing_layer_not_an_empty_one() -> None:
    k = mk.build(replace(the_match(), events=(), events_fetched_at=None))
    assert layer(k, "c3_events") == {"status": "missing", "sources": ["core.fixture_events"], "notes": ["no_events"]}
    assert k.events == () and k.completeness == "partial"
    assert layer(k, "c5_tactics")["data"]["home"]["formation"] == "4-3-3", "the formations do not depend on the events"
    assert "story" not in layer(k, "c5_tactics")["data"]


# ── statistics and players ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_statistics_are_kept_by_side_with_short_names_and_without_what_the_provider_left_empty() -> None:
    data = layer(mk.build(the_match()), "c2_team_stats")["data"]
    assert data["home"] == {"shots": 12, "on_target": 5, "corners": 6, "fouls": 11, "yellow": 0, "red": 0, "possession": 55.0, "xg": 1.83}
    assert "xg" not in data["away"] and data["away"]["yellow"] == 2 and data["away"]["possession"] == 45.0


def test_one_side_of_the_statistics_is_a_partial_layer_and_none_is_a_missing_one() -> None:
    inp = the_match()
    one = layer(mk.build(replace(inp, team_stats=[stats("home")])), "c2_team_stats")
    assert one["status"] == "partial" and one["notes"] == ["no_away"] and list(one["data"]) == ["home"]
    empty = layer(mk.build(replace(inp, team_stats=[stats("home", **dict.fromkeys(mk.TEAM_STAT_KEYS)), stats("away", **dict.fromkeys(mk.TEAM_STAT_KEYS))])),
                  "c2_team_stats")
    assert empty["status"] == "missing" and empty["notes"] == ["no_figures"]
    assert layer(mk.build(replace(inp, team_stats=())), "c2_team_stats")["status"] == "missing"


def test_the_players_layer_is_a_few_men_not_the_squad() -> None:
    data = layer(mk.build(the_match()), "c4_players")["data"]
    assert data["home"] == {
        "listed": 5, "played": 4, "started": 3, "came_on": 1, "captain": 101,
        "top": [{"p": 101, "name": "P101", "rating": 8.4, "min": 90, "g": 2}, {"p": 102, "name": "P102", "rating": 7.1, "min": 90, "a": 1},
                {"p": 104, "name": "P104", "rating": 6.9, "min": 30}]}
    assert data["away"]["played"] == 4 and data["away"]["top"][0] == {"p": 202, "name": "P202", "rating": 7.9, "min": 90, "g": 1}
    assert "goals_with_no_player" not in data


def test_players_without_minutes_or_ratings_say_so() -> None:
    inp = the_match()
    k = mk.build(replace(inp, players=[player(1, "home", None, None), player(2, "away", None, None)]))
    c4 = layer(k, "c4_players")
    assert c4["status"] == "partial" and set(c4["notes"]) == {"no_minutes", "no_ratings"}
    assert layer(mk.build(replace(inp, players=())), "c4_players")["status"] == "missing"
    assert layer(mk.build(replace(inp, players=[player(1, "home", 90, 7.0)])), "c4_players")["notes"][0] == "no_away"


# ── tactics ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_story_of_the_score_and_the_substitutions_with_the_lead_of_each_side() -> None:
    c5 = layer(mk.build(the_match()), "c5_tactics")
    assert c5["status"] == "ok"
    data = c5["data"]
    assert data["home"] == {"formation": "4-3-3", "coach": "id:7001", "subs": [[60, 0]]}, "1-1 when the home side changed a man"
    assert data["away"] == {"formation": "4-4-2", "coach": "name:b coach", "subs": [[70, 0]]}
    assert data["story"] == {
        "ahead": {"home": True, "away": False}, "lead_changes": 0, "minutes": {"home_ahead": 44, "level": 46, "away_ahead": 0},
        "first_goal": {"minute": 23, "side": "home"}, "last_goal": 78, "first_dismissal": {"minute": 85, "side": "away", "lead": -1}}, (
        "the lead of the first dismissal is the one of the side that lost the man")


def test_a_substitution_is_made_with_the_lead_seen_from_the_side_that_makes_it() -> None:
    events = [raw(0, 10, "away", "Goal", "Normal Goal", player=202), raw(1, 20, "home", "subst", "Substitution 1", player=103, assist=104),
              raw(2, 30, "away", "subst", "Substitution 1", player=203, assist=204)]
    inp = the_match()
    k = mk.build(replace(inp, events=events, result=replace(result_of(inp), goals_home=0, goals_away=1, reg_home=0, reg_away=1, ht_home=0, ht_away=1)))
    data = layer(k, "c5_tactics")["data"]
    assert data["home"]["subs"] == [[20, -1]] and data["away"]["subs"] == [[30, 1]]


def test_a_comeback_switches_the_side_that_is_ahead() -> None:
    events = [raw(0, 10, "away", "Goal", "Normal Goal", player=202), raw(1, 30, "home", "Goal", "Normal Goal", player=101),
              raw(2, 50, "home", "Goal", "Normal Goal", player=101), raw(3, 80, "away", "Goal", "Normal Goal", player=202)]
    inp = the_match()
    k = mk.build(replace(inp, events=events, result=replace(result_of(inp), goals_home=2, goals_away=2, reg_home=2, reg_away=2, ht_home=1, ht_away=1)))
    story = layer(k, "c5_tactics")["data"]["story"]
    assert story["ahead"] == {"home": True, "away": True} and story["lead_changes"] == 1
    assert story["minutes"] == {"home_ahead": 30, "level": 40, "away_ahead": 20}
    assert story["first_goal"] == {"minute": 10, "side": "away"}


def test_stoppage_time_counts_as_the_last_minute_of_the_ninety() -> None:
    events = [raw(0, 90, "home", "Goal", "Normal Goal", player=101, extra=4), raw(1, 94, "home", "Goal", "Normal Goal", player=101)]
    inp = the_match()
    k = mk.build(replace(inp, events=events, result=replace(result_of(inp), goals_home=2, goals_away=0, reg_home=2, reg_away=0, ht_home=0, ht_away=0)))
    story = layer(k, "c5_tactics")["data"]["story"]
    assert story["minutes"] == {"home_ahead": 0, "level": 90, "away_ahead": 0}, "a goal at 90+4 changes the score for no minute of the 90"
    assert "late_minute" in json.dumps(layer(k, "c3_events")) and "odd_minutes" in k.quality["doubts"]


def test_a_crossed_sheet_gives_no_formation_but_keeps_its_coach() -> None:
    k = mk.build(replace(the_match(), sheets_crossed=True))
    c5 = layer(k, "c5_tactics")
    assert c5["status"] == "partial" and "sheets_crossed" in c5["notes"] and "formation_missing" in c5["notes"]
    assert "formation" not in c5["data"]["home"] and c5["data"]["home"]["coach"] == "id:7001"
    assert "sheets_crossed" in k.quality["doubts"]


def test_the_coach_key_is_the_one_the_tactics_profile_uses() -> None:
    for coach_id, name in ((7001, "A. Coach"), (None, " B   Coach "), (None, None), (None, "  "), (0, None)):
        assert mk.coach_key(coach_id, name) == tactics.coach_key(coach_id, name)


# ── ties ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def tie(**change: Any) -> mk.Tie:
    base: dict[str, Any] = {"id": 5, "format": "two_legged", "status": "decided", "legs": 2, "team_a_id": AWAY, "team_b_id": HOME,
                            "aggregate_a": 3, "aggregate_b": 4, "winner_team_id": HOME, "decided_by": "aggregate"}
    return mk.Tie(**(base | change))


def test_only_the_leg_that_closed_a_tie_tells_what_the_tie_came_to() -> None:
    inp = the_match()
    first = layer(mk.build(replace(inp, fixture=replace(inp.fixture, leg=1, tie_id=5), tie=tie())), "c1_result")["data"]["tie"]
    assert first == {"format": "two_legged", "legs": 2, "leg": 1}, "a first leg says nothing of what happened after it"
    second = layer(mk.build(replace(inp, fixture=replace(inp.fixture, leg=2, tie_id=5), tie=tie())), "c1_result")["data"]["tie"]
    assert second == {"format": "two_legged", "legs": 2, "leg": 2, "aggregate": [4, 3], "winner": "home", "decided_by": "aggregate"}, (
        "the aggregate is seen from the home side of THIS match")
    away_first = replace(inp, fixture=replace(inp.fixture, leg=2, home_team_id=AWAY, away_team_id=HOME), tie=tie(shootout_a=4, shootout_b=2, decided_by="penalties"))
    shown = layer(mk.build(away_first), "c1_result")["data"]["tie"]
    assert shown["aggregate"] == [3, 4] and shown["winner"] == "away" and shown["shootout"] == [4, 2]


def test_a_tie_not_decided_yet_or_contradicted_is_told_as_it_is() -> None:
    inp = the_match()
    open_tie = layer(mk.build(replace(inp, fixture=replace(inp.fixture, leg=2), tie=tie(status="open"))), "c1_result")["data"]["tie"]
    assert open_tie == {"format": "two_legged", "legs": 2, "leg": 2}
    single = tie(format="single", legs=1, aggregate_a=None, aggregate_b=None, winner_team_id=AWAY, winner_check="contradicted")
    shown = layer(mk.build(replace(inp, tie=single)), "c1_result")["data"]["tie"]
    assert shown == {"format": "single", "legs": 1, "winner": "away", "decided_by": "aggregate", "contradicted": True}


def test_the_corrections_the_provider_made_are_part_of_the_result() -> None:
    inp = the_match()
    later = FETCHED + timedelta(days=2)
    c1 = layer(mk.build(replace(inp, revisions=[mk.Revision(later, "result_changed", ("goals_home", "ht_goals_home")),
                                              mk.Revision(FETCHED + timedelta(days=1), "status_changed", ("status_short",))])), "c1_result")
    assert c1["data"]["revisions"] == {"n": 2, "last": "2034-04-03T15:00:00Z", "kinds": ["result_changed", "status_changed"],
                                       "fields": ["goals_home", "ht_goals_home", "status_short"]}
    assert c1["known_at"] == "2034-04-03T15:00:00Z" and "core.fixture_result_revisions" in c1["sources"]


def test_a_finished_match_with_no_result_row_is_minimal() -> None:
    k = mk.build(replace(the_match(), result=None))
    assert layer(k, "c1_result") == {"status": "missing", "sources": ["core.fixtures"], "data": {"status": "FT", "kickoff": "2034-04-01T12:00:00Z"},
                                     "notes": ["no_result_row"]}
    assert k.completeness == "minimal" and "no_result" in k.quality["doubts"]
    assert layer(k, "c3_events")["status"] == "partial" and "score_unknown" in layer(k, "c3_events")["notes"]


def test_a_match_with_a_result_and_nothing_else_is_minimal() -> None:
    inp = the_match()
    k = mk.build(mk.Inputs(fixture=inp.fixture, result=inp.result))
    assert k.completeness == "minimal" and all(layer(k, n)["status"] == "missing" for n in ("c2_team_stats", "c3_events", "c4_players", "c5_tactics", "c6_market", "c8_picks", "c9_postmortem"))
    assert layer(k, "c7_context") == {"status": "off", "notes": ["decided_by_the_owner"]}
    assert k.known_at == result_of(inp).settled_at, "known at the newest moment any layer was known"


# ── the market ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_market_is_read_from_a_week_before_to_the_last_snapshot_and_then_to_the_last_prices() -> None:
    data = layer(mk.build(the_match()), "c6_market")["data"]
    assert data["1X2"] == {"p": {"Away": [0.23, 0.19], "Draw": [0.27, 0.26], "Home": [0.5, 0.55]}, "books": 20, "close_at": "2034-04-01T11:48:00Z",
                           "min_to_ko": 12, "open_at": "2034-03-26T06:00:00Z",
                           "final": {"odds": {"Away": 5.0, "Draw": 3.6, "Home": 1.8}, "books": 8, "at": "2034-04-01T10:35:00Z", "min_to_ko": 85}}
    assert data["OU"]["line"] == 2.5 and data["OU"]["p"] == {"Over": [0.52, 0.5], "Under": [0.48, 0.5]}
    assert data["OU"]["final"]["odds"] == {"Over": 2.0, "Under": 1.85}
    assert "AH" not in data and set(data) == {"1X2", "OU", "BTTS"}


def test_a_selection_with_no_opening_has_none_and_a_market_missing_makes_the_layer_partial() -> None:
    inp = the_match()
    k = mk.build(replace(inp, open_quotes=[q for q in inp.open_quotes if q.selection != "Draw"],
                        close_quotes=[q for q in inp.close_quotes if q.market != "BTTS"],
                        final_quotes=[q for q in inp.final_quotes if q.market != "BTTS"]))
    c6 = layer(k, "c6_market")
    assert c6["data"]["1X2"]["p"]["Draw"] == [None, 0.26]
    assert c6["status"] == "partial" and c6["notes"] == ["no_BTTS"]
    nothing = layer(mk.build(replace(inp, close_quotes=(), final_quotes=())), "c6_market")
    assert nothing == {"status": "missing", "sources": ["market.market_consensus", "market.final_prematch_odds"]}


def test_the_last_prices_are_what_the_consensus_lacks_when_it_has_nothing_and_add_to_it_when_it_has() -> None:
    """The worker was down: no snapshot of the market exists, but the provider's last prices were read after the match. They say what the
    market was, without a probability or an opening to go with them."""
    inp = the_match()
    alone = layer(mk.build(replace(inp, open_quotes=(), close_quotes=())), "c6_market")
    assert alone["status"] == "ok" and "notes" not in alone
    assert alone["data"]["1X2"] == {"final": {"odds": {"Away": 5.0, "Draw": 3.6, "Home": 1.8}, "books": 8, "at": "2034-04-01T10:35:00Z", "min_to_ko": 85}}
    assert alone["data"]["OU"]["line"] == 2.5 and set(alone["data"]["OU"]) == {"final", "line"}
    assert alone["known_at"] == "2034-04-01T15:00:00Z", "known when it was read, after the match: that is when we learned it"
    # and the other way round: the consensus without the last prices is what it always was
    without = layer(mk.build(replace(inp, final_quotes=())), "c6_market")
    assert "final" not in without["data"]["1X2"] and without["known_at"] == "2034-04-01T11:48:00Z"
    assert layer(mk.build(inp), "c6_market")["known_at"] == "2034-04-01T15:00:00Z"
    # only some markets priced after the match: the layer is as complete as the markets it has, from either source
    two = [q for q in inp.final_quotes if q.market != "BTTS"]
    part = layer(mk.build(replace(inp, close_quotes=[q for q in inp.close_quotes if q.market != "BTTS"], final_quotes=two)), "c6_market")
    assert part["status"] == "partial" and part["notes"] == ["no_BTTS"]
    btts = layer(mk.build(replace(inp, close_quotes=[q for q in inp.close_quotes if q.market != "BTTS"])), "c6_market")
    assert btts["status"] == "ok" and set(btts["data"]["BTTS"]) == {"final"}, "BTTS known by its last prices only is still BTTS known"


def test_the_last_prices_are_read_at_the_line_the_consensus_reads_and_by_themselves_at_the_main_line_rule() -> None:
    inp = the_match()
    # a line with more books than the consensus's must not take its place: the two views describe the same bet
    wide = [*inp.final_quotes, last("OU", "Over", 1.4, line="1.5", books=30), last("OU", "Under", 3.0, line="1.5", books=30)]
    assert layer(mk.build(replace(inp, final_quotes=wide)), "c6_market")["data"]["OU"]["final"]["odds"] == {"Over": 2.0, "Under": 1.85}
    # the consensus reads 2.5 and nobody priced 2.5 after the match: no last price for that line (the data says so by not having it)
    other = [q for q in inp.final_quotes if q.market != "OU"] + [last("OU", "Over", 1.4, line="1.5"), last("OU", "Under", 3.0, line="1.5")]
    ou = layer(mk.build(replace(inp, final_quotes=other)), "c6_market")["data"]["OU"]
    assert "final" not in ou and ou["line"] == 2.5
    # without a consensus the last prices choose: 2.5 whenever quoted, else the most quoted and the most even
    alone = replace(inp, open_quotes=(), close_quotes=())
    assert layer(mk.build(replace(alone, final_quotes=wide)), "c6_market")["data"]["OU"]["line"] == 2.5
    thin = [last("OU", "Over", 1.4, line="1.5", books=5), last("OU", "Under", 3.0, line="1.5", books=5),
            last("OU", "Over", 1.95, line="3.5", books=9), last("OU", "Under", 1.9, line="3.5", books=9),
            last("OU", "Over", 2.8, line="4.5", books=9), last("OU", "Under", 1.45, line="4.5", books=9)]
    chosen = layer(mk.build(replace(alone, final_quotes=thin)), "c6_market")["data"]["OU"]
    assert chosen["line"] == 3.5 and chosen["final"]["odds"] == {"Over": 1.95, "Under": 1.9}, "as many books: the closest to even"
    handicap = [last("AH", "Home", 1.95, line="-0.5", books=7), last("AH", "Away", 1.9, line="-0.5", books=7),
                last("AH", "Home", 1.55, line="-1.5", books=7), last("AH", "Away", 2.45, line="-1.5", books=7)]
    assert layer(mk.build(replace(alone, final_quotes=handicap)), "c6_market")["data"]["AH"]["line"] == -0.5


def test_the_books_of_a_market_are_the_most_that_priced_any_of_its_selections() -> None:
    inp = the_match()
    uneven = [q if q.selection != "Draw" else replace(q, books=3) for q in inp.final_quotes]
    assert layer(mk.build(replace(inp, final_quotes=uneven)), "c6_market")["data"]["1X2"]["final"]["books"] == 8
    only_draw = [q for q in inp.final_quotes if q.market != "1X2" or q.selection == "Draw"]
    thin = layer(mk.build(replace(inp, final_quotes=only_draw)), "c6_market")["data"]["1X2"]["final"]
    assert thin["odds"] == {"Draw": 3.6}, "a selection nobody priced is not invented"


def test_the_main_line_is_two_and_a_half_when_quoted_and_otherwise_the_most_quoted_and_most_even() -> None:
    def q(line: str, over: float, books: int) -> list[mk.Quote]:
        return [quote("OU", "Over", over, 0.2, line=line, books=books), quote("OU", "Under", 1 - over, 0.2, line=line, books=books)]

    assert mk.main_line("OU", q("1.5", 0.8, 30) + q("2.5", 0.55, 4) + q("3.5", 0.3, 30)) == Decimal("2.5"), "2.5 whenever it is quoted"
    assert mk.main_line("OU", q("1.5", 0.8, 30) + q("3.5", 0.45, 30) + q("4.5", 0.2, 30)) == Decimal("3.5"), "as many books: the closest to even"
    assert mk.main_line("OU", q("1.5", 0.8, 10) + q("3.5", 0.45, 30)) == Decimal("3.5"), "more books beat a better balance"
    ah = [quote("AH", "Home", 0.62, 0.2, line="-0.5", books=12), quote("AH", "Away", 0.38, 0.2, line="-0.5", books=12),
          quote("AH", "Home", 0.51, 0.2, line="-1", books=12), quote("AH", "Away", 0.49, 0.2, line="-1", books=12)]
    assert mk.main_line("AH", ah) == Decimal("-1")
    assert mk.main_line("AH", []) is None
    k = mk.build(replace(the_match(), close_quotes=[*the_match().close_quotes, *ah]))
    assert layer(k, "c6_market")["data"]["AH"]["line"] == -1.0


# ── the picks and the post-mortems ───────────────────────────────────────────────────────────────────────────────────────


def test_the_decisions_are_told_at_their_last_checkpoint_and_the_ones_that_matter_are_listed() -> None:
    c8 = layer(mk.build(the_match()), "c8_picks")
    assert c8["status"] == "ok"
    d = c8["data"]["decisions"]
    assert d["n"] == 4 and d["lines"] == 3
    assert d["states"] == {"APROBADO": {"n": 1, "win": 1}, "RECHAZADO": {"n": 1, "win": 1}, "INVESTIGACION": {"n": 1, "loss": 1}}, (
        "the last checkpoint of each line counts: the first one of the home win was only CAUTELA")
    assert d["top"] == [{"id": 1, "cp": "T-1h", "market": "1X2", "sel": "Home", "line": 0.0, "state": "APROBADO", "score": 70.1, "odds": 2.0, "p": 0.52,
                         "edge": 0.04, "stake": 0.5, "result": "win", "profit": 1.0, "clv": 0.03}]
    assert c8["data"]["picks"] == {"n": 6, "by_market": {"1X2": {"n": 5, "profit": 0.4, "win": 3, "loss": 2}, "OU": {"n": 1, "profit": 0.9, "win": 1}}}


def test_a_decision_not_settled_yet_makes_the_layer_partial() -> None:
    inp = the_match()
    open_decision = decision(7, "1X2", "Away", "CAUTELA", score=55.0)
    k = mk.build(replace(inp, decisions=[*inp.decisions, open_decision]))
    assert layer(k, "c8_picks")["status"] == "partial" and layer(k, "c8_picks")["notes"] == ["not_settled_yet"]
    pending = mk.build(replace(inp, picks=[mk.PickTally("1X2", "pending", 2, 0.0)]))
    assert layer(pending, "c8_picks")["status"] == "partial"
    assert layer(mk.build(replace(inp, decisions=(), picks=())), "c8_picks")["status"] == "missing"


def test_the_postmortems_are_counted_by_verdict_and_the_decisions_that_matter_come_first() -> None:
    inp = the_match()
    more = [mk.Postmortem(id=10, decision_id=3, version="pm-v3", outcome="lost", quality="BAD", verdict="VARIANZA", created_at=FETCHED + timedelta(hours=21)),
            mk.Postmortem(id=8, decision_id=1, version="pm-v2", outcome="won", quality="NEUTRAL", verdict="SUERTE", created_at=FETCHED + timedelta(hours=5))]
    c9 = layer(mk.build(replace(inp, postmortems=[*inp.postmortems, *more])), "c9_postmortem")
    assert c9["status"] == "ok" and c9["known_at"] == "2034-04-02T12:00:00Z"
    assert c9["data"]["n"] == 2 and c9["data"]["version"] == "pm-v3"
    assert c9["data"]["verdicts"] == {"MERECIDO": 1, "VARIANZA": 1}, "the newest post-mortem of a decision is the one that counts"
    assert [i["decision"] for i in c9["data"]["items"]] == [1, 3]
    assert c9["data"]["items"][0] == {"decision": 1, "outcome": "won", "quality": "GOOD", "verdict": "MERECIDO", "market": "1X2", "sel": "Home",
                                      "line": 0.0, "state": "APROBADO", "causes": ["price_beat_close"]}


def test_a_postmortem_of_a_selection_counts_whether_or_not_a_decision_judged_it_and_an_old_row_and_a_new_one_are_one() -> None:
    """Plan F8 (pm-v6): the post-mortem is about the SELECTION, whoever looked at it. A row of the AI's selection has no decision; a row of
    pm-v6 about the selection an older row was about (through its decision) replaces it; the review's verdict and the class of a loss show."""
    inp = the_match()
    no_decision = mk.Postmortem(id=20, decision_id=None, version="pm-v6", outcome="lost", quality="UNKNOWN", verdict="SIN_DATOS",
                                created_at=FETCHED + timedelta(hours=30), market="BTTS", selection="Yes", line=0.0,
                                review_verdict="approved_lost", loss_class="MODEL_ERROR")
    newer = mk.Postmortem(id=21, decision_id=1, version="pm-v6", outcome="won", quality="GOOD", verdict="MERECIDO",
                          created_at=FETCHED + timedelta(hours=31), market="1X2", selection="Home", line=0.0, review_verdict="approved_won")
    c9 = layer(mk.build(replace(inp, postmortems=[*inp.postmortems, no_decision, newer])), "c9_postmortem")
    assert c9["status"] == "ok" and c9["data"]["n"] == 2, "decision 1's old row (pm-v3) and the pm-v6 row about the same selection are one"
    assert c9["data"]["version"] == "pm-v6" and c9["data"]["verdicts"] == {"MERECIDO": 1, "SIN_DATOS": 1}
    assert c9["data"]["review_verdicts"] == {"approved_won": 1, "approved_lost": 1}
    first, second = c9["data"]["items"]
    assert first["decision"] == 1 and first["review_verdict"] == "approved_won" and first["state"] == "APROBADO" and "class" not in first
    assert second == {"decision": None, "outcome": "lost", "quality": "UNKNOWN", "verdict": "SIN_DATOS", "market": "BTTS", "sel": "Yes",
                      "line": 0.0, "review_verdict": "approved_lost", "class": "MODEL_ERROR"}, "after the ones a decision judged"


def test_a_match_with_only_the_old_rows_says_what_it_always_said() -> None:
    """The content of a match whose post-mortems are all of the decision layer's own is the same as before F8: no new keys, the same hash."""
    c9 = layer(mk.build(the_match()), "c9_postmortem")
    assert "review_verdicts" not in c9["data"] and set(c9["data"]["items"][0]) == {"decision", "outcome", "quality", "verdict", "market", "sel",
                                                                                   "line", "state", "causes"}


# ── hashes, order and moments ────────────────────────────────────────────────────────────────────────────────────────────


def test_reading_the_same_facts_later_says_the_same_thing() -> None:
    inp = the_match()
    later = timedelta(days=3)
    shifted = replace(
        inp, events_fetched_at=FETCHED + later, team_stats=[replace(t, fetched_at=t.fetched_at + later) for t in inp.team_stats],
        players=[replace(p, fetched_at=FETCHED + later) for p in inp.players], lineups=[replace(s, fetched_at=FETCHED + later) for s in inp.lineups],
        final_quotes=[replace(q, fetched_at=q.fetched_at + later) for q in inp.final_quotes],
        result=replace(inp.result, settled_at=FETCHED + later, fetched_at=FETCHED + later) if inp.result else None)
    a, b = mk.build(inp), mk.build(shifted)
    assert a.content_hash == b.content_hash, "the moments are not part of what the match says"
    assert a.known_at < b.known_at and layer(a, "c3_events")["known_at"] != layer(b, "c3_events")["known_at"]
    assert layer(a, "c6_market")["known_at"] != layer(b, "c6_market")["known_at"]


def test_what_the_match_says_changing_changes_the_hash() -> None:
    inp = the_match()
    base = mk.build(inp).content_hash
    moved = the_events()
    moved[2] = raw(2, 56, "away", "Goal", "Normal Goal", player=202)
    assert mk.build(replace(inp, events=moved)).content_hash != base
    assert mk.build(replace(inp, result=replace(result_of(inp), ht_home=0, ht_away=0))).content_hash != base
    assert mk.build(replace(inp, sheets_crossed=True)).content_hash != base
    assert mk.build(replace(inp, postmortems=())).content_hash != base
    assert mk.build(replace(inp, final_quotes=[replace(q, odds=q.odds + 0.05) for q in inp.final_quotes])).content_hash != base
    assert mk.build(replace(inp, final_quotes=inp.final_quotes[1:])).content_hash != base


def test_the_order_the_facts_arrive_in_changes_nothing() -> None:
    inp = the_match()
    rng = random.Random(7)

    def shuffled(items: Any) -> list[Any]:
        out = list(items)
        rng.shuffle(out)
        return out

    mixed = replace(inp, events=shuffled(inp.events), team_stats=shuffled(inp.team_stats), players=shuffled(inp.players),
                    lineups=shuffled(inp.lineups), open_quotes=shuffled(inp.open_quotes), close_quotes=shuffled(inp.close_quotes),
                    final_quotes=shuffled(inp.final_quotes), decisions=shuffled(inp.decisions), picks=shuffled(inp.picks), postmortems=shuffled(inp.postmortems))
    assert mk.build(mixed).content_hash == mk.build(inp).content_hash
    assert mk.build(inp).content_hash == mk.build(inp).content_hash


def test_every_layer_is_plain_json_and_survives_a_round_trip() -> None:
    k = mk.build(the_match())
    text = mk.canonical({"layers": k.layers, "quality": k.quality})
    assert json.loads(text) == {"layers": k.layers, "quality": k.quality}
    assert all(set(layer(k, n)) <= {"status", "known_at", "sources", "data", "notes"} for n in mk.LAYERS)
    assert all(layer(k, n)["status"] in mk.STATUSES for n in mk.LAYERS)
    assert k.completeness in mk.COMPLETENESS


def test_known_at_is_the_newest_moment_any_layer_was_known() -> None:
    inp = the_match()
    k = mk.build(inp)
    assert k.known_at == FETCHED + timedelta(hours=20), "the post-mortem was written 20 hours after the rest"
    assert max(mk.layer_known(layer(k, n)) or KICKOFF for n in mk.LAYERS) == k.known_at


def test_the_hash_of_what_a_build_read_is_stable_and_depends_on_every_part() -> None:
    sig = {"fixture": "a", "events": [1, "b"], "rules": mk.RULES}
    assert mk.signature_hash(sig) == mk.signature_hash(dict(reversed(list(sig.items())))), "the order of the keys is not part of it"
    assert mk.signature_hash(sig) != mk.signature_hash({**sig, "events": [2, "b"]})
    assert mk.RULES == {"layers": "mk-v1", "events": ev.VERSION, "sides": "sides-v1"}


def test_nothing_in_a_layer_is_a_decimal_or_a_datetime() -> None:
    def walk(value: Any) -> None:
        assert not isinstance(value, (Decimal, datetime)), value
        if isinstance(value, dict):
            for k, v in value.items():
                assert isinstance(k, str)
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    k = mk.build(the_match())
    walk(k.layers)
    walk(k.quality)


@pytest.mark.parametrize("status", ["FT", "AET", "PEN", "AWD", "WO"])
def test_every_finished_status_builds_without_failing(status: str) -> None:
    inp = the_match()
    k = mk.build(replace(inp, fixture=replace(inp.fixture, status=status)))
    assert k.layers["c1_result"]["data"]["status"] == status
