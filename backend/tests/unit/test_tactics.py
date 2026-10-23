"""The observable tactics of a team (``fbi.intel.tactics``, plan F6): how a match is read from the provider's events, and the profile of
five hand-made matches whose every figure can be counted by eye."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fbi.intel import tactics as tc

D0 = datetime(2026, 10, 20, 20, tzinfo=UTC)


def goal(minute: int, side: str | None, detail: str = "Normal Goal", comments: str | None = None) -> tc.Ev:
    return tc.Ev(minute, side, "Goal", detail, comments)


def sub(minute: int, side: str, n: int = 1) -> tc.Ev:
    return tc.Ev(minute, side, "subst", f"Substitution {n}")


# ── the bands ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("minute", "band"), [
    (0, 0), (1, 0), (15, 0), (16, 1), (30, 1), (31, 2), (45, 2), (46, 3), (60, 3), (61, 4), (75, 4), (76, 5), (90, 5),
    (91, None), (105, None), (120, None), (-1, None)])
def test_a_minute_belongs_to_one_band_and_extra_time_to_none(minute: int, band: int | None) -> None:
    assert tc.band_of(minute) == band


def test_the_bands_cover_the_ninety_minutes_once() -> None:
    assert [last for _, last in tc.BANDS] == [15, 30, 45, 60, 75, 90] and tc.BANDS[tc.LATE][0] == "76-90+"
    assert [tc.band_of(m) for m in range(1, 91)].count(None) == 0


# ── one match's events ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_goals_of_the_ninety_minutes_in_order_seen_from_each_side() -> None:
    events = [goal(10, "home"), goal(55, "away"), goal(88, "home")]
    home = tc.read_events(events, "home", 2, 1)
    assert home is not None and [(g.minute, g.mine) for g in home.goals] == [(10, True), (55, False), (88, True)]
    away = tc.read_events(events, "away", 1, 2)
    assert away is not None and [(g.minute, g.mine) for g in away.goals] == [(10, False), (55, True), (88, False)]
    assert tc.read_events(events, "home", 1, 2) is None, "the events are 2-1 for the home side, not 1-2"


def test_events_that_do_not_give_the_score_are_not_read() -> None:
    assert tc.read_events([goal(10, "home")], "home", 2, 0) is None, "a goal missing from the list"
    assert tc.read_events([goal(10, "home"), goal(20, "home")], "home", 1, 0) is None, "a goal the VAR took away and the list kept"
    assert tc.read_events([goal(10, None)], "home", 1, 0) is None, "a goal of nobody"
    assert tc.read_events([], "home", 1, 0) is None


def test_a_match_without_goals_is_read_when_the_score_is_nil_nil() -> None:
    out = tc.read_events([tc.Ev(30, "away", "Card", "Yellow Card"), sub(70, "home")], "home", 0, 0)
    assert out is not None and out.goals == () and out.subs == (tc.Sub(70, 0),)
    assert out.first_goal_is_mine() is None and out.led_and_trailed() == (False, False)


def test_an_own_goal_counts_for_the_side_it_is_filed_under_which_is_the_one_that_gets_it() -> None:
    events = [goal(40, "home", "Own Goal")]
    assert [g.mine for g in (tc.read_events(events, "home", 1, 0) or tc.Reading((), ())).goals] == [True]
    assert [g.mine for g in (tc.read_events(events, "away", 0, 1) or tc.Reading((), ())).goals] == [False]
    assert tc.read_events(events, "home", 0, 1) is None, "read the other way round the list is not the score"


def test_a_missed_penalty_and_a_shoot_out_are_not_goals_and_extra_time_is_not_the_ninety_minutes() -> None:
    events = [goal(30, "home", "Missed Penalty"), goal(44, "away"), goal(105, "home"), goal(120, "away", "Penalty", "Penalty Shootout"),
              goal(120, "home", "Missed Penalty", "Penalty Shootout")]
    out = tc.read_events(events, "home", 0, 1)
    assert out is not None and [(g.minute, g.mine) for g in out.goals] == [(44, False)]
    assert tc.read_events(events, "home", 1, 1) is None, "the score of the 90 minutes is not the score after extra time"


def test_stoppage_time_is_the_last_minute_of_its_half() -> None:
    out = tc.read_events([goal(45, "home"), goal(90, "away")], "home", 1, 1)  # 45+3 and 90+5 are listed with minute 45 and 90
    assert out is not None and [tc.band_of(g.minute) for g in out.goals] == [2, 5]


def test_a_substitution_carries_the_lead_the_team_had_when_it_was_made() -> None:
    events = [sub(30, "home"), goal(35, "away"), sub(46, "home", 2), sub(50, "away"), goal(60, "home"), goal(61, "home"),
              sub(62, "home", 3), tc.Ev(80, "home", "Card", "Red Card")]
    out = tc.read_events(events, "home", 2, 1)
    assert out is not None and out.subs == (tc.Sub(30, 0), tc.Sub(46, -1), tc.Sub(62, 1)), "the rival's substitution is not the team's"
    assert out.led_and_trailed() == (True, True)
    other = tc.read_events(events, "away", 1, 2)
    assert other is not None and other.subs == (tc.Sub(50, 1),), "seen from the away side the lead is its own: its goal at 35 is the first"


def test_states_of_the_lead() -> None:
    assert [tc.state_of(x) for x in (2, 1, 0, -1, -3)] == ["leading", "leading", "level", "trailing", "trailing"]


# ── five matches ────────────────────────────────────────────────────────────────────────────────────────────────────────

S1 = frozenset(range(1, 12))
S2 = frozenset([*range(1, 11), 12])  # one man out of S1 (11) and one in (12)
S3 = frozenset([*range(1, 10), 13, 14])  # two men out of S2 (10, 12) and two in


def played(fid: int, days: int, side: str, gf: int, ga: int, events: list[tc.Ev], *, ht: tuple[int, int] | None, sheet: tc.SheetState = "ok",
           formation: str | None = None, starters: frozenset[int] | None = None, coach: str | None = None) -> tc.Played:
    reading = tc.read_events(events, side, gf, ga)
    return tc.Played(fixture_id=fid, kickoff=D0 - timedelta(days=days), side=side, gf=gf, ga=ga, half_time=ht, sheet=sheet,
                     formation=formation, starters=starters, coach=coach, events="ok" if reading is not None else "inconsistent",
                     reading=reading)


def five() -> list[tc.Played]:
    """Newest first. M1 won 2-1 at home after conceding first; M2 lost 0-2 away; M3 drew 1-1 at home after leading; M4 won 3-0 away with no
    formation on its sheet; M5 drew 0-0 at home on a crossed sheet."""
    return [
        played(5, 1, "home", 2, 1, [goal(10, "away"), goal(30, "home"), tc.Ev(55, "home", "Card", "Yellow Card"), sub(60, "home"),
                                    sub(62, "away"), sub(75, "home", 2), goal(88, "home")],
               ht=(1, 1), formation="4-3-3", starters=S1, coach="id:7"),
        played(4, 8, "away", 0, 2, [goal(30, "home"), sub(46, "away"), sub(70, "away", 2), sub(78, "away", 3), goal(80, "home")],
               ht=(0, 1), formation="4-3-3", starters=S2, coach="id:7"),
        played(3, 15, "home", 1, 1, [goal(20, "home"), sub(65, "home"), goal(90, "away")],
               ht=(1, 0), formation="4-2-3-1", starters=S3, coach="id:7"),
        played(2, 22, "away", 3, 0, [goal(5, "away"), goal(40, "away", "Penalty"), sub(60, "away"), sub(70, "away", 2), goal(76, "away")],
               ht=(2, 0), formation=None, starters=None, coach="id:9"),
        played(1, 29, "home", 0, 0, [tc.Ev(44, "away", "Card", "Yellow Card"), sub(70, "home")],
               ht=(0, 0), sheet="crossed", formation=None, starters=None, coach="id:9"),
    ]


def test_the_profile_of_five_matches() -> None:
    p = tc.profile(77, five())
    assert (p["team_id"], p["n"], p["fixtures"]) == (77, 5, [5, 4, 3, 2, 1])
    assert p["read"] == {"events": [5, 4, 3, 2, 1], "sheets": [5, 4, 3, 2, 1]}, "a crossed sheet was read, for its coach"
    assert p["data"] == {"sheets": {"none": 0, "crossed": 1, "without_formation": 1, "without_the_eleven": 1},
                         "events": {"none": 0, "inconsistent": 0}}

    f = p["formations"]
    assert f == {"n": 3, "main": "4-3-3", "main_count": 2, "last": "4-3-3", "distinct": 2, "changes": 1,
                 "counts": {"4-3-3": 2, "4-2-3-1": 1}}, "the change is between the third and the second match: the others have a gap"

    s = p["starters"]
    assert s == {"n": 3, "pairs": 2, "changes": [1, 2], "avg_changes": 1.5, "ever_present": 9}, "newest pair first"

    assert p["coach"] == {"n": 5, "distinct": 2, "newest_matches": 3}

    g = p["goals"]
    assert g["bands"] == ["1-15", "16-30", "31-45+", "46-60", "61-75", "76-90+"]
    assert g["for"] == [1, 2, 1, 0, 0, 2] and g["against"] == [1, 1, 0, 0, 0, 2]
    assert (g["total_for"], g["total_against"], g["n"]) == (6, 4, 5), "the scores 2-1, 0-2, 1-1, 3-0 and 0-0"
    assert g["late"] == {"for": 2, "against": 2, "matches_for": 2, "matches_against": 2}

    w = p["with_the_score"]
    assert w["n"] == 5 and w["goalless"] == 1
    assert w["scored_first"] == {"n": 2, "wins": 1, "draws": 1, "losses": 0}
    assert w["conceded_first"] == {"n": 2, "wins": 1, "draws": 0, "losses": 1}
    assert w["led_and_did_not_win"] == 1 and w["trailed_and_did_not_lose"] == 1
    assert w["half_time"] == {"n": 5, "leading": {"n": 2, "wins": 1, "draws": 1, "losses": 0},
                              "level": {"n": 2, "wins": 1, "draws": 1, "losses": 0},
                              "trailing": {"n": 1, "wins": 0, "draws": 0, "losses": 1}}

    u = p["substitutions"]
    assert (u["n"], u["with_substitutions"], u["per_match"]) == (5, 5, 1.8)
    assert u["first_minute"] == {"mean": 60.2, "median": 60.0}
    assert u["first_by_state"] == {"leading": {"n": 2, "mean_minute": 62.5}, "level": {"n": 2, "mean_minute": 65.0},
                                   "trailing": {"n": 1, "mean_minute": 46.0}}


def test_the_profile_does_not_depend_on_the_order_the_matches_arrive_in_and_is_plain_json() -> None:
    a, b = tc.profile(77, five()), tc.profile(77, five()[::-1])
    assert a == b
    assert json.loads(json.dumps(a)) == a


def test_an_empty_sample_says_so() -> None:
    assert tc.profile(5, []) == {"team_id": 5, "n": 0, "fixtures": []}


def test_a_match_whose_events_do_not_give_the_score_is_in_the_sample_but_not_in_what_the_events_say() -> None:
    matches = five()
    broken = tc.Played(fixture_id=4, kickoff=matches[1].kickoff, side="away", gf=0, ga=2, half_time=(0, 1), sheet="ok",
                       formation="4-3-3", starters=S2, coach="id:7", events="inconsistent", reading=None)
    p = tc.profile(77, [matches[0], broken, *matches[2:]])
    assert p["n"] == 5 and 4 in p["fixtures"] and 4 not in p["read"]["events"]
    assert p["data"]["events"] == {"none": 0, "inconsistent": 1}
    assert p["goals"]["n"] == 4 and p["goals"]["total_against"] == 2, "the 0-2 is not counted"
    assert p["with_the_score"]["half_time"]["n"] == 5, "the break comes from the result, not from the events"
    assert p["formations"]["n"] == 3, "and neither does the formation"


def test_the_ties_of_the_main_formation_go_to_the_newest_and_a_gap_is_not_a_change() -> None:
    ms = [tc.Played(i, D0 - timedelta(days=i), "home", 1, 0, formation=f) for i, f in
          ((1, "4-4-2"), (2, "3-5-2"), (3, None), (4, "3-5-2"), (5, "4-4-2"))]
    out = tc.formations(ms)
    assert out["main"] == "4-4-2" and out["main_count"] == 2 and out["last"] == "4-4-2" and out["distinct"] == 2
    assert out["changes"] == 2, "5 to 4 and 2 to 1; between 4 and 2 a match has no formation, so nothing is compared"
    assert tc.formations([tc.Played(1, D0, "home", 1, 0)]) == {"n": 0}


def test_ever_present_is_said_only_from_three_sheets() -> None:
    two = [tc.Played(i, D0 - timedelta(days=i), "home", 1, 0, starters=s) for i, s in ((1, S1), (2, S2))]
    assert "ever_present" not in tc.starters(two) and tc.starters(two)["changes"] == [1]
    assert tc.starters([tc.Played(1, D0, "home", 1, 0)]) == {"n": 0}


def test_half_time_results_count_without_events() -> None:
    ms = [tc.Played(1, D0, "home", 2, 0, half_time=(1, 0)), tc.Played(2, D0 - timedelta(days=3), "away", 1, 1, half_time=None)]
    out = tc.with_the_score(ms, [])
    assert out == {"half_time": {"n": 1, "leading": {"n": 1, "wins": 1, "draws": 0, "losses": 0},
                                 "level": {"n": 0, "wins": 0, "draws": 0, "losses": 0},
                                 "trailing": {"n": 0, "wins": 0, "draws": 0, "losses": 0}}, "n": 0}


def test_the_coach_of_a_sheet_is_his_id_else_his_name() -> None:
    assert tc.coach_key(12, "A. Coach") == "id:12"
    assert tc.coach_key(None, "  A.   Coach ") == "name:a. coach"
    assert tc.coach_key(None, None) is None and tc.coach_key(None, "   ") is None


def test_the_note_says_what_it_is_not() -> None:
    assert "descripciones" in tc.NOTE and "no son predicciones" in tc.NOTE and "ningún modelo las lee" in tc.NOTE
    assert "«estilo»" in tc.NOTE and "no da posiciones ni presión" in tc.NOTE
