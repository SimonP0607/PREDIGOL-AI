"""The reasons that put a match on Inicio's «Partidos relevantes» (in play) and «Qué se juega» (next 36 hours): chosen from the
match packet's facts and the score, never invented (plan de Inicio, 3.1b). Pure rules: no database."""

from __future__ import annotations

from typing import Any

from fbi.api.services import home_board, reading


def glance(*, kind: str | None = None, home: str | None = None, away: str | None = None,
           first: tuple[int, int] | None = None) -> reading.Glance:
    ctx: dict[str, Any] = {}
    if kind == "final":
        ctx["final"] = True
    elif kind == "second_leg":
        ctx["second_leg"] = {} if first is None else {"first_leg_score_home_side": first[0],
                                                       "first_leg_score_away_side": first[1]}
    elif kind == "friendly":
        ctx["friendly"] = True
    stakes = {"home": {"pressure": home} if home else {}, "away": {"pressure": away} if away else {}}
    return reading.glance({"fixture": {"home": {"name": "Blues"}, "away": {"name": "Reds"}}, "stakes": stakes,
                           "dossier": {"context": ctx}})


def live(g: reading.Glance | None, goals: tuple[int, int] | None = (0, 0), behind: dict[str, int] | None = None) -> list[Any]:
    return home_board.live_reasons(g, home="Blues", away="Reds", goals=goals, behind_by=behind or {})


def codes(reasons: list[Any]) -> list[str]:
    return [r.code for r in reasons]


# ── in play ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_match_with_nothing_to_say_has_no_reason() -> None:
    assert live(None) == []
    assert live(glance()) == []
    assert live(glance(home="settled", away="settled")) == []


def test_a_final_in_play() -> None:
    assert codes(live(glance(kind="final"))) == ["final"]


def test_a_second_leg_says_how_the_aggregate_stands_now() -> None:
    (reason,) = live(glance(kind="second_leg", first=(1, 2)), goals=(1, 0))
    assert reason.code == "tie"
    assert reason.params == {"home": "Blues", "away": "Reds", "first_home": 1, "first_away": 2,
                             "agg_home": 2, "agg_away": 2}


def test_a_second_leg_without_the_first_legs_score_is_not_a_reason() -> None:
    assert live(glance(kind="second_leg")) == []


def test_a_fight_for_a_table_zone_with_how_it_is_going() -> None:
    reasons = live(glance(home="relegation"), goals=(0, 1))
    assert [(r.code, r.params["team"], r.params["pressure"], r.params["state"]) for r in reasons] == [
        ("stakes", "Blues", "relegation", "behind")]


def test_both_sides_can_fight_for_something() -> None:
    reasons = live(glance(home="title", away="europe"), goals=(1, 1))
    assert [(r.params["team"], r.params["state"]) for r in reasons] == [("Blues", "level"), ("Reds", "level")]


def test_a_settled_or_mid_table_side_is_not_a_reason_and_neither_is_the_playoff() -> None:
    assert live(glance(home="settled", away="playoff")) == []
    assert live(glance(home="mid_table")) == []


def test_without_a_score_nothing_about_the_score_is_said() -> None:
    assert live(glance(home="title"), goals=None) == []
    assert codes(live(glance(kind="final"), goals=None)) == ["final"], "a final needs no score to be one"


def test_a_comeback_is_a_side_that_was_behind_and_is_now_level_or_ahead() -> None:
    (level,) = live(None, goals=(1, 1), behind={"home": 1})
    assert (level.code, level.params["team"], level.params["down_by"], level.params["state"]) == ("comeback", "Blues", 1,
                                                                                                  "level")
    (ahead,) = live(None, goals=(1, 2), behind={"away": 2})
    assert (ahead.params["team"], ahead.params["down_by"], ahead.params["state"]) == ("Reds", 2, "ahead")
    assert live(None, goals=(0, 1), behind={"home": 1}) == [], "still behind: not a comeback"
    assert live(None, goals=(1, 0), behind={}) == [], "never behind: not a comeback"


def test_two_reasons_at_most_the_strongest_first() -> None:
    reasons = live(glance(kind="final", home="title", away="title"), goals=(1, 1), behind={"home": 1})
    assert codes(reasons) == ["final", "comeback"]


def test_a_friendly_is_never_a_reason() -> None:
    assert live(glance(kind="friendly", home="title"), behind={"home": 1}, goals=(1, 1)) == []


# ── about to be played ──────────────────────────────────────────────────────────────────────────────────────────────

def stake(g: reading.Glance | None) -> Any:
    return home_board.stake_reason(g, home="Blues", away="Reds")


def test_nothing_at_stake_without_a_packet_or_a_reason() -> None:
    assert stake(None) is None
    assert stake(glance()) is None
    assert stake(glance(home="settled", away="settled")) is None
    assert stake(glance(kind="friendly", home="title")) is None


def test_a_final_is_at_stake() -> None:
    assert stake(glance(kind="final")).code == "final"


def test_a_second_leg_to_play_says_how_the_first_ended() -> None:
    reason = stake(glance(kind="second_leg", first=(0, 3)))
    assert reason.code == "first_leg"
    assert reason.params == {"home": "Blues", "away": "Reds", "first_home": 0, "first_away": 3}


def test_a_fight_in_the_table_names_the_side_and_what_for() -> None:
    reason = stake(glance(away="promotion"))
    assert (reason.code, reason.params) == ("stakes", {"team": "Reds", "pressure": "promotion"})


def test_when_both_sides_fight_for_something_both_are_named() -> None:
    reason = stake(glance(home="title", away="europe"))
    assert reason.params == {"team": "Blues", "pressure": "title", "other_team": "Reds", "other_pressure": "europe"}


def test_a_second_leg_without_its_first_leg_falls_back_to_the_table() -> None:
    assert stake(glance(kind="second_leg", home="europe")).code == "stakes"
    assert stake(glance(kind="second_leg")) is None
