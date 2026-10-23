"""The events of a match, read (plan F7, ``fbi.knowledge.events``): goal, own goal, penalty, shoot-out, second yellow, VAR, period.

The lines used here have the shape of the ones measured on production (23 Oct 2026); where a rule rests on a count, the test says which."""

from __future__ import annotations

import pytest

from fbi.knowledge import events as ev
from fbi.knowledge.events import RawEvent


def raw(seq: int, minute: int, event_type: str, detail: str | None = None, *, side: str | None = "home", comments: str | None = None,
        player: int | None = None, extra: int | None = None, assist: int | None = None, name: str | None = None) -> RawEvent:
    return RawEvent(seq=seq, minute=minute, extra_minute=extra, side=side, event_type=event_type, detail=detail, comments=comments,
                    player_id=player, player_name=name, assist_id=assist)


def read(*lines: RawEvent, extra_time: bool = False) -> list[ev.Event]:
    return ev.normalize(lines, extra_time=extra_time)


# ── what each line is ────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("event_type", "detail", "comments", "kind", "known"), [
    ("Goal", "Normal Goal", None, ev.GOAL, True),
    ("Goal", "Penalty", None, ev.PENALTY_GOAL, True),
    ("Goal", "Missed Penalty", None, ev.PENALTY_MISSED, True),
    ("Goal", "Own Goal", None, ev.OWN_GOAL, True),
    ("Goal", "Penalty", "Penalty Shootout", ev.SHOOTOUT_GOAL, True),
    ("Goal", "Missed Penalty", "Penalty Shootout", ev.SHOOTOUT_MISS, True),
    ("Goal", "Normal Goal", "Penalty Shootout", ev.GOAL, True),     # a comment never turns a normal goal into a kick
    ("Goal", None, None, ev.OTHER, False),                          # 3 junk lines at minute 0, no side, no player
    ("scorer", None, None, ev.OTHER, False),                        # 6 junk lines
    ("Card", "Yellow Card", "Foul", ev.YELLOW, True),
    ("Card", "Red Card", "Violent conduct", ev.RED, True),
    ("Card", "Second Yellow Card", None, ev.SECOND_YELLOW, True),   # 100 lines say it outright
    ("Card", None, None, ev.CARD_UNKNOWN, False),                   # 243 lines
    ("subst", "Substitution 3", None, ev.SUBSTITUTION, True),
    ("Var", "Goal cancelled", None, ev.VAR_GOAL_CANCELLED, True),
    ("Var", "Goal Disallowed - offside", "Offside", ev.VAR_GOAL_CANCELLED, True),
    ("Var", "Goal Disallowed - Foul", None, ev.VAR_GOAL_CANCELLED, True),
    ("Var", "Goal Disallowed - handball", None, ev.VAR_GOAL_CANCELLED, True),
    ("Var", "Goal Disallowed - video review", None, ev.VAR_GOAL_CANCELLED, True),
    ("Var", "Goal Disallowed", None, ev.VAR_GOAL_CANCELLED, True),
    ("Var", "Goal confirmed", None, ev.VAR_GOAL_CONFIRMED, True),
    ("Var", "Penalty confirmed", None, ev.VAR_PENALTY_AWARDED, True),
    ("Var", "Penalty awarded", None, ev.VAR_PENALTY_AWARDED, True),
    ("Var", "Penalty cancelled", None, ev.VAR_PENALTY_CANCELLED, True),
    ("Var", "Card upgrade", None, ev.VAR_CARD_UPGRADED, True),
    ("Var", "Card upgrade confirmed", None, ev.VAR_CARD_UPGRADED, True),
    ("Var", "Card upgrade cancelled", None, ev.VAR_CARD_CANCELLED, True),
    ("Var", "Red card cancelled", None, ev.VAR_CARD_CANCELLED, True),
    ("Var", "Card reviewed", None, ev.VAR_CARD_REVIEWED, True),
    ("Var", "Red card confirmed", None, ev.VAR_CARD_REVIEWED, True),
    ("Var", None, None, ev.VAR_OTHER, False),                       # 171 lines
    ("Var", "Something new", None, ev.VAR_OTHER, False),
])
def test_what_each_line_of_the_provider_is(event_type: str, detail: str | None, comments: str | None, kind: str, known: bool) -> None:
    assert ev.kind_of(event_type, detail, comments) == (kind, known)


def test_the_words_are_read_whatever_their_case_or_spaces() -> None:
    assert ev.kind_of(" goal ", " OWN GOAL ", None) == (ev.OWN_GOAL, True)
    assert ev.kind_of("Goal", "Penalty", " penalty shootout ") == (ev.SHOOTOUT_GOAL, True)


def test_every_kind_that_can_come_out_is_in_the_list_of_kinds() -> None:
    seen = {ev.kind_of(t, d, c)[0] for t, d, c in [
        ("Goal", "Normal Goal", None), ("Goal", "Penalty", None), ("Goal", "Missed Penalty", None), ("Goal", "Own Goal", None),
        ("Goal", "Penalty", "Penalty Shootout"), ("Goal", "Missed Penalty", "Penalty Shootout"), ("Card", "Yellow Card", None),
        ("Card", "Red Card", None), ("Card", "Second Yellow Card", None), ("Card", None, None), ("subst", "Substitution 1", None),
        ("Var", "Goal cancelled", None), ("Var", "Goal confirmed", None), ("Var", "Penalty awarded", None), ("Var", "Penalty cancelled", None),
        ("Var", "Card upgrade", None), ("Var", "Red card cancelled", None), ("Var", "Card reviewed", None), ("Var", None, None),
        ("scorer", None, None)]}
    assert seen <= set(ev.KINDS)
    assert set(ev.KINDS) - seen == set()      # and none of the kinds is dead


# ── own goal, penalty, shoot-out ─────────────────────────────────────────────────────────────────────────────────────────


def test_an_own_goal_counts_for_the_side_the_provider_filed_it_under_and_belongs_to_the_other_mans_team() -> None:
    # Measured: the 1,154 matches whose only goal was an own goal have it filed under the team that GETS the goal.
    out = read(raw(0, 33, "Goal", "Own Goal", side="away", player=7, name="Defender of home"))
    (e,) = out
    assert (e.kind, e.side, e.player_side, e.period) == (ev.OWN_GOAL, "away", "home", ev.FIRST_HALF)
    assert ev.regulation_goals(out) == (0, 1)       # the goal is the away side's
    assert e.as_dict()["player_side"] == "home"      # it is said, because it is not the filing side


def test_a_penalty_of_the_match_is_a_goal_and_a_missed_one_is_not() -> None:
    out = read(raw(0, 12, "Goal", "Penalty"), raw(1, 55, "Goal", "Missed Penalty", side="away"))
    assert [e.kind for e in out] == [ev.PENALTY_GOAL, ev.PENALTY_MISSED]
    assert ev.regulation_goals(out) == (1, 0)


def test_the_kicks_of_a_shoot_out_are_not_goals_of_the_match_and_have_their_own_period() -> None:
    lines = [raw(0, 20, "Goal", "Normal Goal", side="home"), raw(1, 100, "Goal", "Normal Goal", side="away")]
    kicks = [("Penalty", "home", 1), ("Missed Penalty", "away", 2), ("Penalty", "home", 3), ("Penalty", "away", 4)]
    lines += [raw(2 + i, 120, "Goal", d, side=s, comments="Penalty Shootout", extra=n, player=900 + i) for i, (d, s, n) in enumerate(kicks)]
    out = read(*lines, extra_time=True)
    assert [e.period for e in out] == [ev.FIRST_HALF, ev.EXTRA_TIME, *[ev.PENALTIES] * 4]
    assert [e.kind for e in out[2:]] == [ev.SHOOTOUT_GOAL, ev.SHOOTOUT_MISS, ev.SHOOTOUT_GOAL, ev.SHOOTOUT_GOAL]
    by = ev.goals_by_period(out)
    assert by[ev.EXTRA_TIME] == {"home": 0, "away": 1}
    assert by[ev.PENALTIES] == {"home": 2, "away": 1}       # the converted kicks, apart from the goals of the match
    assert ev.regulation_goals(out) == (1, 0)


# ── a second yellow ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_yellow_and_a_red_of_the_same_man_at_the_same_minute_are_a_dismissal_for_two_yellows() -> None:
    # Measured: 18,676 of the 42,584 reds have a yellow of the same man at the same minute, and the provider's own statistics count both.
    out = read(raw(0, 30, "Card", "Yellow Card", player=5), raw(1, 70, "Card", "Yellow Card", player=5, comments="Foul"),
               raw(2, 70, "Card", "Red Card", player=5, comments="Foul"))
    assert [e.kind for e in out] == [ev.YELLOW, ev.YELLOW, ev.SECOND_YELLOW]
    assert out[2].pair_seq == 1 and out[1].pair_seq == 2 and out[0].pair_seq is None
    assert ev.FLAG_SECOND_OF_PAIR in out[1].flags and ev.FLAG_SECOND_OF_PAIR not in out[0].flags
    assert {e.kind for e in out if e.kind in ev.DISMISSALS} == {ev.SECOND_YELLOW}


def test_a_red_of_a_man_booked_at_another_minute_is_a_red_and_says_so() -> None:
    # 1,529 reds have a yellow of the same man at another minute: a straight red after a booking, or a second yellow listed with one line.
    out = read(raw(0, 30, "Card", "Yellow Card", player=5), raw(1, 70, "Card", "Red Card", player=5))
    assert [e.kind for e in out] == [ev.YELLOW, ev.RED]
    assert out[1].flags == (ev.FLAG_AFTER_YELLOW,) and out[1].pair_seq is None


def test_a_straight_red_and_a_red_with_no_man_are_just_reds() -> None:
    out = read(raw(0, 10, "Card", "Red Card", player=5), raw(1, 80, "Card", "Red Card", player=None), raw(2, 80, "Card", "Yellow Card"))
    assert [e.kind for e in out] == [ev.RED, ev.RED, ev.YELLOW]
    assert all(e.pair_seq is None for e in out)
    assert [e.flags for e in out] == [(), (ev.FLAG_NO_PLAYER,), (ev.FLAG_NO_PLAYER,)], "and a card with nobody in it says so"


def test_the_100_lines_that_say_second_yellow_stand_alone() -> None:
    out = read(raw(0, 61, "Card", "Second Yellow Card", player=8))
    assert out[0].kind == ev.SECOND_YELLOW and out[0].pair_seq is None and not out[0].flags


def test_a_yellow_pairs_with_one_red_only_and_a_pair_needs_the_same_side() -> None:
    out = read(raw(0, 40, "Card", "Yellow Card", player=5), raw(1, 40, "Card", "Red Card", player=5),
               raw(2, 40, "Card", "Red Card", player=5),                       # a second red line of the same minute finds the yellow taken
               raw(3, 50, "Card", "Yellow Card", player=6, side="home"), raw(4, 50, "Card", "Red Card", player=6, side="away"))
    assert [e.kind for e in out] == [ev.YELLOW, ev.SECOND_YELLOW, ev.RED, ev.YELLOW, ev.RED]
    assert out[1].pair_seq == 0 and out[0].pair_seq == 1 and out[2].pair_seq is None


def test_the_yellow_may_come_after_the_red_in_the_list_and_it_is_the_same_dismissal() -> None:
    # Measured: 50 of the 41,179 reds with a player have the yellow of the same minute AFTER them in the list, and 40 of those men had been
    # booked earlier: a second yellow listed the other way round (a real match: yellow 39', red 63', yellow 63').
    out = read(raw(0, 39, "Card", "Yellow Card", player=5), raw(1, 63, "Card", "Red Card", player=5), raw(2, 63, "Card", "Yellow Card", player=5))
    assert [e.kind for e in out] == [ev.YELLOW, ev.SECOND_YELLOW, ev.YELLOW]
    assert out[1].pair_seq == 2 and out[2].pair_seq == 1 and out[0].pair_seq is None
    assert ev.FLAG_SECOND_OF_PAIR in out[2].flags and not out[1].flags, "it is not 'a red after a booking': the booking is the one beside it"


def test_a_red_pairs_with_the_nearest_yellow_before_it_and_only_then_with_one_after() -> None:
    out = read(raw(0, 70, "Card", "Yellow Card", player=5), raw(1, 70, "Card", "Red Card", player=5), raw(2, 70, "Card", "Yellow Card", player=5))
    assert [e.kind for e in out] == [ev.YELLOW, ev.SECOND_YELLOW, ev.YELLOW]
    assert out[1].pair_seq == 0 and out[0].pair_seq == 1 and out[2].pair_seq is None


def test_a_goal_or_a_card_with_nobody_in_it_says_so_and_still_counts() -> None:
    # Measured (last 400 days): 3,303 normal goals, 63 own goals and 331 penalties with neither a player id nor a name.
    out = read(raw(0, 10, "Goal", "Normal Goal"), raw(1, 20, "Goal", "Normal Goal", name="A. Player"), raw(2, 30, "Goal", "Normal Goal", player=7),
               raw(3, 40, "Goal", "Own Goal", side="away"), raw(4, 50, "Card", "Yellow Card", side="away"),
               raw(5, 60, "subst", "Substitution 1"), raw(6, 70, "Var", "Goal cancelled"),
               raw(7, 120, "Goal", "Penalty", comments="Penalty Shootout"), raw(8, 120, "Goal", "Missed Penalty", comments="Penalty Shootout", player=9),
               extra_time=True)
    assert [ev.FLAG_NO_PLAYER in e.flags for e in out] == [True, False, False, True, True, False, False, True, False]
    assert ev.regulation_goals(out) == (3, 1), "a goal nobody scored is still in the score"
    assert out[0].as_dict()["flags"] == [ev.FLAG_NO_PLAYER]


def test_the_second_yellows_do_not_change_what_the_cards_total() -> None:
    out = read(raw(0, 70, "Card", "Yellow Card", player=5), raw(1, 70, "Card", "Red Card", player=5))
    k = ev.counts(out)
    assert k[ev.YELLOW] == 1 and k[ev.SECOND_YELLOW] == 1 and ev.RED not in k     # one yellow line + one dismissal line, as the provider counts


# ── VAR ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_goal_the_var_took_away_is_a_decision_with_no_goal_beside_it() -> None:
    # Measured: for 2,251 of 2,253 sides with such a decision the goals of the list ARE the score (the provider removes the goal).
    out = read(raw(0, 17, "Goal", "Normal Goal", side="home"), raw(1, 64, "Var", "Goal Disallowed - offside", side="away"))
    assert [e.kind for e in out] == [ev.GOAL, ev.VAR_GOAL_CANCELLED]
    assert ev.regulation_goals(out) == (1, 0)


def test_a_line_with_words_the_table_has_not_met_is_kept_and_flagged() -> None:
    out = read(raw(0, 5, "Var", "Brand new decision"), raw(1, 6, "Card", None), raw(2, 7, "scorer", None, side=None))
    assert [e.kind for e in out] == [ev.VAR_OTHER, ev.CARD_UNKNOWN, ev.OTHER]
    assert all(ev.FLAG_UNKNOWN_DETAIL in e.flags for e in out)
    assert ev.FLAG_NO_SIDE in out[2].flags


# ── the period ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("minute", "extra_time", "period", "flags"), [
    (0, False, ev.FIRST_HALF, ()), (45, False, ev.FIRST_HALF, ()), (46, False, ev.SECOND_HALF, ()), (90, False, ev.SECOND_HALF, ()),
    (91, False, ev.SECOND_HALF, (ev.FLAG_LATE_MINUTE,)),          # 164 events in 73 matches that ended in regular time
    (91, True, ev.EXTRA_TIME, ()), (105, True, ev.EXTRA_TIME, ()), (106, True, ev.EXTRA_TIME, ()), (120, True, ev.EXTRA_TIME, ()),
    (130, True, ev.EXTRA_TIME, (ev.FLAG_MINUTE_OUT_OF_RANGE,)),   # 56 junk lines above 120
])
def test_the_period_follows_the_clock_and_whether_the_match_went_to_extra_time(minute: int, extra_time: bool, period: str,
                                                                             flags: tuple[str, ...]) -> None:
    assert ev.period_of(minute, shootout=False, extra_time=extra_time) == (period, flags)


def test_stoppage_time_is_the_period_it_is_added_to() -> None:
    out = read(raw(0, 45, "Card", "Yellow Card", extra=4), raw(1, 90, "Goal", "Normal Goal", extra=6, side="away"))
    assert [e.period for e in out] == [ev.FIRST_HALF, ev.SECOND_HALF]
    assert out[1].extra_minute == 6


def test_the_kick_number_of_an_old_shoot_out_is_not_a_minute() -> None:
    (e,) = read(raw(0, 120, "Goal", "Penalty", comments="Penalty Shootout", extra=3), extra_time=True)
    assert e.period == ev.PENALTIES and e.extra_minute == 3        # kept as the provider gave it; the period is what says it is a kick


# ── the whole list ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_nothing_is_dropped_the_provider_order_is_kept_and_reading_twice_is_the_same() -> None:
    lines = [raw(3, 80, "subst", "Substitution 2", player=1, assist=2), raw(0, 10, "Goal", "Normal Goal"), raw(2, 70, "Card", "Yellow Card", player=3),
             raw(1, 33, "Var", "Goal confirmed", side=None)]
    once = ev.normalize(lines, extra_time=False)
    assert [e.seq for e in once] == [0, 1, 2, 3] and len(once) == len(lines)
    assert ev.normalize(reversed(lines), extra_time=False) == once         # the order of the input does not matter: ``seq`` does
    assert ev.normalize(lines, extra_time=False) == once


def test_a_substitution_keeps_who_goes_off_and_who_comes_on() -> None:
    (e,) = read(raw(0, 60, "subst", "Substitution 1", player=10, assist=20, name="Out", side="away"))
    assert (e.kind, e.player_id, e.assist_id, e.player_side) == (ev.SUBSTITUTION, 10, 20, "away")


def test_goals_by_period_and_the_counts() -> None:
    out = read(raw(0, 10, "Goal", "Normal Goal", side="home"), raw(1, 44, "Goal", "Penalty", side="away"), raw(2, 50, "Goal", "Own Goal", side="home"),
               raw(3, 91, "Goal", "Normal Goal", side="away"), raw(4, 30, "Card", "Yellow Card"), raw(5, 31, "Card", "Yellow Card"), extra_time=True)
    by = ev.goals_by_period(out)
    assert by[ev.FIRST_HALF] == {"home": 1, "away": 1} and by[ev.SECOND_HALF] == {"home": 1, "away": 0}
    assert by[ev.EXTRA_TIME] == {"home": 0, "away": 1}
    assert ev.regulation_goals(out) == (2, 1)
    assert ev.counts(out) == {ev.GOAL: 2, ev.OWN_GOAL: 1, ev.PENALTY_GOAL: 1, ev.YELLOW: 2}


def test_a_goal_with_no_side_counts_for_no_one() -> None:
    out = read(raw(0, 10, "Goal", "Normal Goal", side=None))
    assert ev.regulation_goals(out) == (0, 0) and ev.FLAG_NO_SIDE in out[0].flags


def test_the_compact_form_leaves_out_what_is_empty() -> None:
    (e,) = read(raw(0, 10, "Goal", "Normal Goal", player=4, name="N. Scorer", assist=9))
    assert e.as_dict() == {"seq": 0, "kind": ev.GOAL, "period": ev.FIRST_HALF, "minute": 10, "side": "home", "player": 4, "name": "N. Scorer", "assist": 9}
