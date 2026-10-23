"""Plan F4 on a built world: the packet counts the matches a team plays in every competition, says when it can be sure of them and
never says more than it knew at its moment (``packet-v7``).

Two teams meet in a league PrediGol follows. Each has also played, or is about to play, a cup or a continental tie in a
competition PrediGol does not follow: those are known only from the list the provider gives for the team
(``core.calendar_matches``), read by the feed. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import packet as packet_module
from fbi.ai.packet import PacketBuilder
from fbi.competitions import team_calendar as calendar_reader
from tests.integration.calendar_helpers import (
    AT,
    FRESH,
    KICKOFF,
    World,
    cup_tie,
    known_competition,
    own_followed,
    read,
    world,
)
from tests.integration.conftest import Seed


def schedule(db: psycopg.Connection[Any], w: World, at: datetime = AT) -> dict[str, Any]:
    built = PacketBuilder(db).build(w.fixture_id, at=at)
    assert built is not None
    assert built.version == packet_module.PACKET_VERSION == "packet-v8"
    block = built.content["schedule"]
    assert isinstance(block, dict)
    return block


# ── the figures ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_cup_tie_the_platform_does_not_follow_changes_the_rest_of_a_team_whose_list_is_whole(db: psycopg.Connection[Any],
                                                                                                seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=2.0)
    read(db, seed, w.home, [own_followed(w, "home", 8.0), cup_tie(w, "home", days_before=2.0)], FRESH)
    read(db, seed, w.away, [own_followed(w, "away", 2.0)], FRESH)
    s = schedule(db, w)
    home, away = s["home"], s["away"]
    assert home["rest_days"] == 2.0 and home["previous_kickoff"] == (KICKOFF - timedelta(days=2)).isoformat(), \
        "the cup tie of two days ago, not the league match of eight"
    assert (home["matches_last_7d"], home["matches_last_14d"], home["matches_last_30d"], home["outside_last_14d"]) == (1, 2, 2, 1)
    assert away["rest_days"] == 2.0 and away["outside_last_14d"] == 0 and away["matches_last_14d"] == 1
    assert [(m["competition"], m["followed"], m["days_before"]) for m in home["recent"]] == [
        ("Copa del Rey", False, 2.0), ("Calendar League", True, 8.0)]
    cal = s["calendar"]
    assert cal["complete"] is True and cal["scope"] == "provider_calendar"
    assert cal["rest_days"] == "exact" and cal["matches_last_14d"] == "exact" and cal["next_match"] == "listed"
    assert cal["home"]["complete"] and cal["away"]["complete"] and cal["home"]["fetched_at"] == FRESH.isoformat()
    assert cal["home"]["age_hours"] == 20.0 and cal["home"]["reason"] is None
    assert s["flags"] == ["home_short_rest", "away_short_rest"], "two days each: both short, and nobody is better rested"


def test_a_side_whose_list_was_never_read_keeps_the_bounds_of_before(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=2.0)
    s = schedule(db, w)
    assert s["home"]["rest_days"] == 8.0 and s["away"]["rest_days"] == 2.0, "what is recorded stays"
    cal = s["calendar"]
    assert cal["complete"] is False and cal["scope"] == "tracked_competitions"
    assert cal["rest_days"] == "at_most" and cal["matches_last_14d"] == "at_least" and cal["next_match"] == "known_only"
    assert cal["home"] == {"complete": False, "reason": "never_fetched", "fetched_at": None, "age_hours": None}
    assert s["flags"] == ["away_short_rest"], "a short rest survives; 'home is better rested' does not"


def test_the_rest_gap_is_claimed_only_when_both_calendars_are_whole(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read(db, seed, w.home, [own_followed(w, "home", 8.0), cup_tie(w, "home", days_before=2.0)], FRESH)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], FRESH)
    s = schedule(db, w)
    assert s["home"]["rest_days"] == 2.0 and s["away"]["rest_days"] == 7.0
    assert s["calendar"]["complete"] is True
    assert s["flags"] == ["home_short_rest", "home_rest_disadvantage"], "five days less rest, and both lists say so"

    stale = AT - timedelta(days=10)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], stale)  # an older reading never replaces a newer one ...
    assert schedule(db, w)["flags"] == ["home_short_rest", "home_rest_disadvantage"]
    db.execute("DELETE FROM core.calendar_fetches WHERE provider_team_id = %s", (w.away,))  # ... so take the newer one away
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], stale)
    mixed = schedule(db, w)
    assert mixed["calendar"]["complete"] is False
    assert mixed["calendar"]["away"]["reason"] == "stale" and mixed["calendar"]["away"]["age_hours"] == 240.0
    assert mixed["calendar"]["home"]["complete"] is True
    assert mixed["calendar"]["note"].startswith("Only a side whose calendar says complete: true"), "said to the reader"
    assert mixed["calendar"]["rest_days"] == "at_most"
    assert mixed["flags"] == ["home_short_rest"], "the gap is not claimed: the away rest of seven days may be shorter"


def test_a_match_the_list_has_not_confirmed_makes_the_calendar_doubtful(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    kickoff_passed = cup_tie(w, "home", days_before=3.0, short="NS")  # kicked off three days ago and the list still says to-be-played
    read(db, seed, w.home, [own_followed(w, "home", 8.0), kickoff_passed], FRESH)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], FRESH)
    s = schedule(db, w)
    assert s["calendar"]["home"]["reason"] == "unconfirmed_match" and s["calendar"]["complete"] is False
    assert s["home"]["rest_days"] == 8.0, "a match that is not known to have been played is not rest"


def test_the_next_match_can_be_a_continental_tie(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=7.0, away_last=7.0)
    tie = cup_tie(w, "home", days_after=3.0, league=2, name="Champions League")
    read(db, seed, w.home, [own_followed(w, "home", 7.0), tie], FRESH)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], FRESH)
    s = schedule(db, w)
    nxt = s["home"]["next_match"]
    assert (nxt["competition"], nxt["followed"], nxt["days_after"], nxt["home"]) == ("Champions League", False, 3.0, True)
    assert nxt["provider_fixture_id"] == s["home"]["upcoming"][0]["provider_fixture_id"]
    assert s["away"]["next_match"] is None and s["away"]["upcoming"] == []


# ── what the packet may know at its moment ───────────────────────────────────────────────────────────────────────────────


def test_a_list_read_after_the_moment_is_not_known_at_it_but_a_match_already_played_is_a_fact(db: psycopg.Connection[Any],
                                                                                              seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    later = AT + timedelta(hours=1)
    announced = cup_tie(w, "home", days_after=2.0, name="Supercopa")
    read(db, seed, w.home, [own_followed(w, "home", 8.0), cup_tie(w, "home", days_before=2.0), announced], later)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], later)
    s = schedule(db, w)
    assert s["home"]["rest_days"] == 2.0, "a match played before the moment is a fact whenever it was recorded"
    assert s["calendar"]["home"] == {"complete": False, "reason": "never_fetched", "fetched_at": None, "age_hours": None}, \
        "but nobody had read the list by then"
    assert s["home"]["next_match"] is None and s["home"]["upcoming"] == [], "a match announced after the moment did not exist yet"
    again = schedule(db, w, at=later + timedelta(hours=1))
    assert again["home"]["next_match"] is not None and again["calendar"]["home"]["fetched_at"] == later.isoformat()


def test_a_match_whose_kickoff_is_after_the_moment_is_not_rest_yet(db: psycopg.Connection[Any],
                                                                                    seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    in_play_at_the_moment = cup_tie(w, "home", days_before=0.0, short="FT")  # kicks off with the match itself: after AT
    read(db, seed, w.home, [own_followed(w, "home", 8.0), in_play_at_the_moment], FRESH)
    s = schedule(db, w)
    assert s["home"]["rest_days"] == 8.0 and s["home"]["recent"][0]["followed"] is True


def test_the_calendar_names_the_competition_and_nothing_that_could_leak_a_result(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    tie = cup_tie(w, "home", days_after=3.0, league=known_competition(db, "Known Cup"), name="Known Cup")
    read(db, seed, w.home, [own_followed(w, "home", 8.0), cup_tie(w, "home", days_before=2.0), tie], FRESH)
    s = schedule(db, w)
    recent, upcoming = s["home"]["recent"][0], s["home"]["upcoming"][0]
    assert set(recent) == {"provider_fixture_id", "kickoff_at", "days_before", "competition", "type", "followed", "home"}
    assert set(upcoming) == {"provider_fixture_id", "kickoff_at", "days_after", "competition", "type", "followed", "home"}
    assert upcoming["type"] == "domestic_cup", "the classification of a competition PrediGol knows about"
    assert recent["type"] is None, "and none for a competition it has never been told about"
    text = repr(s)
    assert "Other FC" not in text and "goals" not in text and "result" not in text, "no score and no opponent in the packet"


def test_the_same_inputs_give_the_same_packet(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read(db, seed, w.home, [own_followed(w, "home", 8.0), cup_tie(w, "home", days_before=2.0)], FRESH)
    first = PacketBuilder(db).build(w.fixture_id, at=AT)
    second = PacketBuilder(db).build(w.fixture_id, at=AT)
    assert first is not None and second is not None and first.hash == second.hash


def test_a_calendar_that_cannot_be_read_is_named_and_costs_the_packet_nothing_else(db: psycopg.Connection[Any], seed: Seed,
                                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db, home_last=8.0, away_last=7.0)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise psycopg.errors.UndefinedTable("the calendar is not there")

    monkeypatch.setattr(calendar_reader, "load", broken)
    built = PacketBuilder(db).build(w.fixture_id, at=AT)
    assert built is not None
    assert built.content["schedule"] == {"error": "UndefinedTable"} and "schedule" in built.missing
    assert built.content["fixture"]["id"] == w.fixture_id and "form" in built.content, "the rest of the packet is there"
