"""A whole competition season read at once (plan F2): stages, ties, the slot of every fixture, and the witness.

The shapes are real ones: the Liga MX (Apertura and Clausura, each with its own liguilla), a Champions League (qualifying
rounds, a group stage, two-legged knock-outs, a final), a cup with replays, a World Cup (third-place match), and the
AFC Champions League Two of 2020 that used one round label for two different rounds.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fbi.competitions import seasons
from fbi.competitions import stages as stg
from fbi.competitions import ties as tl
from fbi.competitions.seasons import SeasonFixture, build_season, fingerprint

D0 = datetime(2025, 8, 1, 19, tzinfo=UTC)
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def fx(fid: int, rnd: str | None, home: int, away: int, day: int, gh: int | None = None, ga: int | None = None,
       status: str = "FT") -> SeasonFixture:
    return SeasonFixture(fixture_id=fid, round=rnd, home=home, away=away, kickoff_at=D0 + timedelta(days=day),
                         status=status, goals_home=gh, goals_away=ga, ft_home=gh if status == "FT" else None,
                         ft_away=ga if status == "FT" else None,
                         settled_at=D0 + timedelta(days=day, hours=3) if gh is not None else None)


def test_the_apertura_and_the_clausura_are_never_mixed() -> None:
    rows = [
        fx(1, "Apertura - 1", 1, 2, 0, 1, 0), fx(2, "Apertura - 1", 3, 4, 0, 0, 0),
        fx(3, "Apertura - Semi-finals", 1, 3, 20, 2, 0), fx(4, "Apertura - Semi-finals", 3, 1, 23, 1, 1),
        fx(5, "Apertura - Final", 1, 2, 30, 1, 0), fx(6, "Apertura - Final", 2, 1, 33, 0, 0),
        fx(7, "Clausura - 1", 3, 2, 60, 1, 1), fx(8, "Clausura - 1", 1, 4, 60, 2, 0),
        fx(9, "Clausura - Semi-finals", 3, 4, 90, 1, 0), fx(10, "Clausura - Semi-finals", 4, 3, 93, 0, 0),
    ]
    build = build_season(rows, now=NOW)
    assert build.stages["Apertura"].reading.kind == "league" and build.stages["Apertura"].tie_format is None
    assert build.stages["Apertura - Semi-finals"].tie_format == "two_legged"
    apertura = build.tie_of(3)
    assert apertura is not None and (apertura.winner, apertura.check) == (1, "confirmed")  # team 1 plays the final
    # team 3 lost the Apertura semi-final and plays the Clausura: that is no evidence it went on
    assert apertura.loser == 3
    clausura = build.tie_of(9)
    assert clausura is not None and clausura.stage == "Clausura - Semi-finals" and clausura.winner == 3
    assert {t.stage for t in build.ties} == {"Apertura - Semi-finals", "Apertura - Final", "Clausura - Semi-finals"}


def test_a_champions_league_season_reads_in_order() -> None:
    rows = [
        # a two-legged qualifying round whose winner (1) goes on to the group stage and whose loser (2) does not
        fx(1, "3rd Qualifying Round", 1, 2, 0, 1, 0), fx(2, "3rd Qualifying Round", 2, 1, 7, 1, 1),
        fx(3, "Group Stage - 1", 1, 3, 30, 0, 0), fx(4, "Group Stage - 1", 4, 5, 30, 2, 1),
        fx(5, "Round of 16", 1, 4, 100, 1, 0), fx(6, "Round of 16", 4, 1, 107, 0, 0),
        fx(7, "Quarter-finals", 1, 6, 130, 2, 0), fx(8, "Quarter-finals", 6, 1, 137, 1, 1),
        fx(9, "Final", 1, 7, 200, 1, 1, "PEN"),
    ]
    rows[-1] = replace(rows[-1], pen_home=4, pen_away=3)
    build = build_season(rows, now=NOW)
    qualifying = build.tie_of(1)
    assert qualifying is not None and (qualifying.winner, qualifying.check) == (1, "confirmed")
    assert build.stages["3rd Qualifying Round"].reading.kind == "qualifying"
    assert build.stages["Group Stage"].reading.role == "group" and build.stages["Group Stage"].tie_format is None
    last16 = build.tie_of(5)
    assert last16 is not None and (last16.winner, last16.check) == (1, "confirmed")
    final = build.tie_of(9)
    assert final is not None and (final.winner, final.decided_by, final.shootout) == (1, "penalties", (4, 3))
    assert final.check == "unknown"  # nothing comes after a final
    assert [t.stage for t in build.ties].count("Round of 16") == 1


def test_the_third_place_match_does_not_say_who_went_through_the_semi_finals() -> None:
    rows = [
        fx(1, "Semi-finals", 1, 2, 0, 2, 0), fx(2, "Semi-finals", 3, 4, 0, 1, 0),
        fx(3, "3rd Place Final", 2, 4, 3, 1, 0),  # the two losers of the semi-finals
        fx(4, "Final", 1, 3, 4, 2, 2, "PEN"),
    ]
    rows[3] = replace(rows[3], pen_home=5, pen_away=4)
    build = build_season(rows, now=NOW)
    assert build.stages["3rd Place Final"].reading.role == "third_place"
    semi_a, semi_b = build.tie_of(1), build.tie_of(2)
    assert semi_a is not None and semi_b is not None
    assert (semi_a.winner, semi_a.check) == (1, "confirmed") and (semi_b.winner, semi_b.check) == (3, "confirmed")


def test_the_replays_of_a_round_belong_to_the_ties_of_that_round() -> None:
    rows = [
        fx(1, "1st Round", 1, 2, 0, 2, 2), fx(2, "1st Round", 3, 4, 0, 1, 0), fx(3, "1st Round", 5, 6, 0, 0, 3),
        fx(4, "1st Round Replays", 2, 1, 4, 0, 1),
        fx(5, "2nd Round", 1, 3, 20, 1, 0),
    ]
    build = build_season(rows, now=NOW)
    replays = build.stages["1st Round Replays"]
    assert replays.reading.replay and replays.reading.base == "1st Round" and replays.ties == 0
    assert build.stages["1st Round"].ties == 3 and build.stages["1st Round"].tie_format == "single"
    tie = build.tie_of(1)
    assert tie is not None and tie.format == "replay" and tie.fixture_ids == (1, 4)
    assert (tie.winner, tie.check) == (1, "confirmed")
    assert build.slots[4].tie == ("1st Round", 1, 2) and build.slots[4].leg == 2 and build.slots[4].stage == "1st Round Replays"


def test_a_round_label_used_twice_in_a_season_does_not_make_a_loser_a_winner() -> None:
    # AFC Champions League Two 2020: the "Play-off Round" label covers the ties of two different rounds; team 5 played
    # the earlier round (the second preliminary round), then lost its play-off tie, and plays nothing after it
    rows = [
        fx(1, "2nd Preliminary Round", 5, 7, 0, 1, 0), fx(2, "2nd Preliminary Round", 7, 5, 7, 0, 0),
        fx(3, "Play-off Round", 5, 6, 20, 1, 0), fx(4, "Play-off Round", 6, 5, 27, 3, 0),
        fx(5, "Group Stage - 1", 6, 8, 60, 2, 0),
    ]
    build = build_season(rows, now=NOW)
    tie = build.tie_of(3)
    assert tie is not None and tie.winner == 6 and tie.check == "confirmed"  # the group stage is the witness


def test_a_cancelled_or_replaced_fixture_belongs_to_no_tie_and_says_why() -> None:
    rows = [
        fx(1, "Quarter-finals", 1, 2, 0, status="PST"), fx(2, "Quarter-finals", 1, 2, 40, 1, 0),
        fx(3, "Quarter-finals", 2, 1, 47, 0, 0), fx(4, "Quarter-finals", 2, 1, 49, status="CANC"),
    ]
    build = build_season(rows, now=NOW)
    assert build.dropped == {1: "rescheduled", 4: "cancelled"}
    assert build.slots[1].tie is None and build.slots[4].tie is None and build.slots[1].stage == "Quarter-finals"
    tie = build.tie_of(2)
    assert tie is not None and tie.fixture_ids == (2, 3) and tie.winner == 1


def test_every_fixture_has_a_slot_and_every_leg_maps_back_to_its_tie() -> None:
    rows = [
        fx(1, "Regular Season - 1", 1, 2, 0, 1, 0), fx(2, "Regular Season - 2", 2, 1, 7, 0, 0),
        fx(3, "Quarter-finals", 1, 2, 30, 1, 0), fx(4, "Quarter-finals", 2, 1, 37, 2, 0),
        fx(5, None, 3, 4, 40, 1, 1),
    ]
    build = build_season(rows, now=NOW)
    assert set(build.slots) == {1, 2, 3, 4, 5}
    assert build.slots[5].stage == "" and build.stages[""].reading.kind == "unresolved"
    assert build.slots[1].tie is None and build.slots[1].leg is None
    for tie in build.ties:
        for fixture_id, leg in tie.legs:
            assert build.slots[fixture_id].tie == (tie.stage, *tie.key) and build.slots[fixture_id].leg == leg
    assert build.tie_of(1) is None and build.tie_of(99) is None


def test_the_record_of_a_stage_says_what_it_holds() -> None:
    rows = [fx(1, "Quarter-finals", 1, 2, 0, 1, 0), fx(2, "Quarter-finals", 2, 1, 7, 1, 1),
            fx(3, "Quarter-finals", 3, 4, 1, 2, 0), fx(4, "Quarter-finals", 4, 3, 8, 0, 0)]
    record = build_season(rows, now=NOW).stages["Quarter-finals"]
    assert (record.fixtures, record.ties, record.tie_format, record.tie_reason) == (4, 2, "two_legged", None)
    assert (record.first_kickoff_at, record.last_kickoff_at) == (D0, D0 + timedelta(days=8))


def test_a_stage_that_is_not_a_bracket_keeps_its_matches_out_of_ties() -> None:
    rows = [fx(1, "Playoffs", 1, 2, 0, 1, 0), fx(2, "Playoffs", 1, 3, 3, 0, 0), fx(3, "Playoffs", 2, 3, 6, 1, 1)]
    build = build_season(rows, now=NOW)
    assert build.stages["Playoffs"].tie_format == "not_a_bracket" and build.ties == ()
    assert build.stages["Playoffs"].tie_reason == "a_team_plays_several_opponents"
    assert all(s.tie is None for s in build.slots.values())


def test_an_empty_season_is_empty() -> None:
    build = build_season([], now=NOW)
    assert build.stages == {} and build.ties == () and build.slots == {} and build.dropped == {}


def test_a_stage_of_replays_whose_round_is_not_in_the_season_stands_alone() -> None:
    # the provider lists the replays of a round and not the round itself: their ties are built in the stage that holds them
    rows = [fx(1, "1st Round Replays", 2, 1, 4, 0, 1), fx(2, "1st Round Replays", 4, 3, 4, 2, 2),
            fx(5, "2nd Round", 1, 3, 20, 1, 0)]
    build = build_season(rows, now=NOW)
    replays = build.stages["1st Round Replays"]
    assert replays.reading.replay and replays.ties == 2 and replays.tie_format == "single"
    tie = build.tie_of(1)
    assert tie is not None and tie.stage == "1st Round Replays" and (tie.winner, tie.check) == (1, "confirmed")
    assert build.slots[1].tie == ("1st Round Replays", 1, 2)
    assert seasons.tie_base("1st Round Replays", replays.reading, {"1st Round Replays": []}) == "1st Round Replays"
    assert seasons.tie_base("1st Round Replays", replays.reading, {"1st Round Replays": [], "1st Round": []}) == "1st Round"


def _quarter_finals(second_leg: tuple[int, int] = (1, 1)) -> list[SeasonFixture]:
    return [fx(1, "Quarter-finals", 1, 2, 0, 1, 0), fx(2, "Quarter-finals", 2, 1, 7, *second_leg),
            fx(3, "Semi-finals", 1, 3, 30)]


def test_the_fingerprint_of_a_build_is_the_same_for_the_same_season_in_any_order() -> None:
    rows = _quarter_finals()
    a = fingerprint(build_season(rows, now=NOW))
    assert a == fingerprint(build_season(list(reversed(rows)), now=NOW))
    assert len(a) == 32 and a == fingerprint(build_season(rows, now=NOW + timedelta(minutes=5)))


def test_the_fingerprint_changes_when_anything_a_build_says_changes() -> None:
    base = fingerprint(build_season(_quarter_finals(), now=NOW))
    assert fingerprint(build_season(_quarter_finals((2, 1)), now=NOW)) != base  # a result corrected: another winner
    assert fingerprint(build_season(_quarter_finals()[:2], now=NOW)) != base  # a fixture the provider removed
    renamed = [replace(r, round="Round of 16") if r.fixture_id == 3 else r for r in _quarter_finals()]
    assert fingerprint(build_season(renamed, now=NOW)) != base  # a round renamed
    # a fixture's own id is part of the answer: the slot of each fixture is what the builder writes
    assert fingerprint(build_season([replace(r, fixture_id=r.fixture_id + 10) for r in _quarter_finals()], now=NOW)) != base


def test_the_fingerprint_notices_that_time_alone_turned_a_tie_unresolved() -> None:
    # a second leg that was scheduled and never played: waiting for it is right for a few days and wrong after that
    rows = [fx(1, "Quarter-finals", 1, 2, 0, 1, 0), fx(2, "Quarter-finals", 2, 1, 7, status="NS"),
            fx(3, "Quarter-finals", 3, 4, 0, 2, 0), fx(4, "Quarter-finals", 4, 3, 7, 0, 0)]
    soon = build_season(rows, now=D0 + timedelta(days=8))
    late = build_season(rows, now=D0 + timedelta(days=30))
    waiting, given_up = soon.tie_of(1), late.tie_of(1)
    assert waiting is not None and given_up is not None
    assert (waiting.status, given_up.status) == ("in_progress", "unresolved")
    assert fingerprint(soon) != fingerprint(late)


def test_the_fingerprint_follows_the_versions_of_the_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    build = build_season(_quarter_finals(), now=NOW)
    before = fingerprint(build)
    monkeypatch.setattr(tl, "VERSION", "ties-99")
    assert fingerprint(build) != before
    monkeypatch.undo()
    assert fingerprint(build) == before
    monkeypatch.setattr(stg, "VERSION", "stages-99")
    assert fingerprint(build) != before
