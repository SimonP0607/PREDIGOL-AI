"""Ties (plan F2): pairings of a knock-out stage, and who went through, with the rules of the sport and nothing assumed.

Every case is a real one or a plain shape of one (the Europa League's 2018 CSKA Sofia - Riga, the FA Cup's replays,
the MLS Cup's best-of-three, the 2020 Europa League's single-leg last 16, the 2025-26 AFC Champions League's West ties
after the postponements, Leipzig - Spartak Moscow's walkover).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.competitions import ties as tl
from fbi.competitions.ties import Match, build_stage_ties, match_winner, single_outcome

D0 = datetime(2025, 3, 1, 19, tzinfo=UTC)
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
A, B, C, D, E, F = 1, 2, 3, 4, 5, 6


def m(fid: int, home: int, away: int, day: int, gh: int | None = None, ga: int | None = None, status: str = "FT", *,
      ft: tuple[int, int] | None = None, et: tuple[int, int] | None = None, pens: tuple[int, int] | None = None,
      replay: bool = False, home_winner: bool | None = None, away_winner: bool | None = None) -> Match:
    """A fixture ``day`` days after D0. A finished match has its 90-minute score unless ``ft`` says otherwise."""
    if ft is None and status == "FT" and gh is not None and ga is not None:
        ft = (gh, ga)
    return Match(fixture_id=fid, home=home, away=away, kickoff_at=D0 + timedelta(days=day), status=status,
                 goals_home=gh, goals_away=ga, ft_home=ft[0] if ft else None, ft_away=ft[1] if ft else None,
                 et_home=et[0] if et else None, et_away=et[1] if et else None,
                 pen_home=pens[0] if pens else None, pen_away=pens[1] if pens else None,
                 home_winner=home_winner, away_winner=away_winner,
                 settled_at=D0 + timedelta(days=day, hours=3) if gh is not None else None, in_replay_stage=replay)


def one(stage: str, matches: list[Match], *, advanced: dict[int, datetime] | None = None,
        now: datetime = NOW) -> tl.StageTies:
    return build_stage_ties(stage, matches, now=now, advanced=advanced)


def later(*teams: int, day: int = 100) -> dict[int, datetime]:
    return {t: D0 + timedelta(days=day) for t in teams}


# ── one match ───────────────────────────────────────────────────────────────


def test_a_single_match_is_decided_by_the_goals() -> None:
    [tie] = one("Round of 16", [m(1, A, B, 0, 2, 1)]).ties
    assert (tie.format, tie.status, tie.winner, tie.decided_by) == ("single", "decided", A, "normal_time")
    assert (tie.aggregate_a, tie.aggregate_b, tie.legs, tie.played) == (2, 1, ((1, 1),), 1)
    assert tie.decided_at == D0 + timedelta(hours=3)


def test_extra_time_decides_a_single_match() -> None:
    [tie] = one("Round of 16", [m(1, A, B, 0, 1, 2, "AET", ft=(1, 1), et=(0, 1))]).ties
    assert (tie.winner, tie.decided_by) == (B, "extra_time")


def test_a_shootout_decides_a_match_that_ended_level() -> None:
    [tie] = one("Round of 16", [m(1, A, B, 0, 1, 1, "PEN", pens=(3, 4))]).ties
    assert (tie.winner, tie.decided_by, tie.shootout, tie.aggregate_a, tie.aggregate_b) == (B, "penalties", (3, 4), 1, 1)


def test_a_match_that_was_level_with_no_shootout_stored_has_no_winner_until_the_next_round_says() -> None:
    match = m(1, A, B, 0, 1, 1)  # the provider keeps "FT" for a match decided on penalties, and stores no shoot-out
    [tie] = one("Round of 16", [match]).ties
    assert (tie.status, tie.winner, tie.reason) == ("unresolved", None, "level_without_shootout")
    [settled] = one("Round of 16", [match], advanced=later(B)).ties
    assert (settled.status, settled.winner, settled.decided_by, settled.check) == ("decided", B, "penalties", "confirmed")
    assert set(settled.flags) == {"shootout_not_stored", "settled_by_next_round"}
    [unsure] = one("Round of 16", [match], advanced=later(A, B)).ties
    assert (unsure.status, unsure.reason) == ("unresolved", "level_without_shootout_evidence_inconclusive")


def test_the_providers_winner_flag_settles_a_level_match() -> None:
    [tie] = one("Final", [m(1, A, B, 0, 0, 0, away_winner=True)]).ties
    assert (tie.winner, tie.decided_by, tie.flags) == (B, "penalties", ("shootout_not_stored",))


def test_a_match_decided_off_the_pitch_says_so() -> None:
    [tie] = one("Round of 16", [m(1, A, B, 0, 0, 3, "AWD")]).ties
    assert (tie.winner, tie.decided_by) == (B, "walkover")


def test_a_walkover_with_no_score_is_settled_only_by_the_next_round() -> None:
    walkover = m(1, A, B, 0, None, None, "WO")
    [tie] = one("Round of 16", [walkover]).ties
    assert (tie.status, tie.reason, tie.played) == ("unresolved", "awarded_without_score", 1)
    [settled] = one("Round of 16", [walkover], advanced=later(A)).ties
    assert (settled.winner, settled.decided_by, settled.check) == (A, "walkover", "confirmed")


def test_a_match_not_played_yet_is_scheduled() -> None:
    [tie] = one("Round of 16", [m(1, A, B, 2000, status="NS")]).ties
    assert (tie.status, tie.played, tie.winner, tie.aggregate_a) == ("scheduled", 0, None, None)


def test_match_winner_reports_the_shootout_from_the_home_side_of_the_match() -> None:
    assert match_winner(m(1, A, B, 0, 2, 2, "PEN", pens=(5, 4))) == (A, "penalties", (5, 4))
    assert match_winner(m(1, A, B, 0)) == (None, None, None)


# ── the provider's extra-time score ─────────────────────────────────────────


def test_a_shootout_means_the_sides_were_level_so_the_extra_time_total_is_the_score() -> None:
    # Riga - CSKA Sofia, 19 Jul 2018: 1-0 at 90 minutes, no goals in extra time, a shoot-out; the provider sent
    # extratime = the running total (1-0) and goals = fulltime + extratime = 2-0
    match = m(1, A, B, 0, 2, 0, "PEN", ft=(1, 0), et=(1, 0), pens=(3, 5))
    # the match alone is not level (1-0 or 2-0): it is the second leg, so it is the aggregate that must be
    [tie] = one("1st Qualifying Round", [m(0, B, A, -7, 1, 0), match]).ties
    assert tie.format == "two_legged"
    assert (tie.winner, tie.decided_by, tie.flags) == (B, "penalties", ("score_repaired",))
    assert (tie.aggregate_a, tie.aggregate_b) == (1, 1)  # not 2-1 for the side that lost the shoot-out
    assert tie.shootout == (5, 3)  # as (team A, team B); team A is the home side of the first leg


def test_the_shootout_beats_a_score_that_cannot_be_true_for_a_single_match() -> None:
    # a single match decided on penalties cannot have ended 3-2
    match = m(1, A, B, 0, 3, 2, "PEN", ft=(1, 1), et=(2, 1), pens=(2, 4))
    out = single_outcome(match)
    assert (out.winner, out.how, out.shootout) == (B, "penalties", (2, 4))
    # of the readings - the total 3-2, the extra-time block as a running total 2-1, the 90 minutes 1-1 - only the
    # 90 minutes (extra time without goals) is level
    assert out.score == (1, 1) and out.flags == ("score_repaired",)


def test_a_score_no_reading_of_the_blocks_can_make_level_is_left_unknown_not_published_wrong() -> None:
    match = m(1, A, B, 0, 2, 1, "PEN", pens=(4, 3))  # no ft/et blocks to read anything else from
    [tie] = one("Round of 16", [match]).ties
    assert (tie.winner, tie.decided_by) == (A, "penalties")
    assert (tie.aggregate_a, tie.aggregate_b) == (None, None)
    assert tie.flags == ("score_inconsistent_with_shootout",)


def test_a_match_stored_as_extra_time_cannot_have_ended_level() -> None:
    match = m(1, A, B, 0, 2, 2, "AET", ft=(1, 1), et=(2, 1))  # running total read as the goals
    out = single_outcome(match)
    assert out.winner == A and out.how == "extra_time" and out.flags == ("score_repaired",)
    assert out.score == (2, 1)


# ── two legs ────────────────────────────────────────────────────────────────


def test_two_legs_are_decided_by_the_aggregate() -> None:
    legs = [m(1, A, B, 0, 1, 0), m(2, B, A, 7, 2, 0)]
    [tie] = one("Quarter-finals", legs).ties
    assert (tie.format, tie.status, tie.winner, tie.decided_by) == ("two_legged", "decided", B, "aggregate")
    assert (tie.aggregate_a, tie.aggregate_b, tie.legs, tie.played) == (1, 2, ((1, 1), (2, 2)), 2)
    assert tie.decided_at == D0 + timedelta(days=7, hours=3)


def test_the_first_leg_is_the_earlier_match_whatever_order_the_fixtures_come_in() -> None:
    [tie] = one("Quarter-finals", [m(2, B, A, 7, 2, 0), m(1, A, B, 0, 1, 0)]).ties
    assert (tie.team_a, tie.team_b, tie.legs) == (A, B, ((1, 1), (2, 2)))


def test_the_second_legs_extra_time_counts_in_the_aggregate() -> None:
    legs = [m(1, A, B, 0, 1, 1), m(2, B, A, 7, 2, 1, "AET", ft=(1, 1), et=(1, 0))]
    [tie] = one("Quarter-finals", legs).ties
    assert (tie.winner, tie.decided_by, tie.aggregate_a, tie.aggregate_b) == (B, "extra_time", 2, 3)


def test_a_level_aggregate_is_settled_by_the_shootout_of_the_second_leg() -> None:
    legs = [m(1, A, B, 0, 1, 0), m(2, B, A, 7, 1, 0, "PEN", pens=(4, 5))]
    [tie] = one("Quarter-finals", legs).ties
    assert (tie.winner, tie.decided_by, tie.shootout, tie.flags) == (A, "penalties", (5, 4), ())
    assert (tie.aggregate_a, tie.aggregate_b) == (1, 1)


def test_the_away_goals_rule_is_never_assumed_only_found() -> None:
    # 2-1 and 1-0: level on aggregate (2-2... here 2-2), B scored more away goals
    legs = [m(1, A, B, 0, 2, 1), m(2, B, A, 7, 1, 0)]
    [open_tie] = one("Round of 16", legs).ties
    assert (open_tie.status, open_tie.reason) == ("unresolved", "level_on_aggregate")
    [by_away_goals] = one("Round of 16", legs, advanced=later(B)).ties
    assert (by_away_goals.winner, by_away_goals.decided_by, by_away_goals.check) == (B, "away_goals", "confirmed")
    # the same scores in a competition without the rule: the OTHER side went through, so it was not away goals
    [elsewhere] = one("Round of 16", legs, advanced=later(A)).ties
    assert (elsewhere.winner, elsewhere.decided_by) == (A, "tiebreak")


def test_a_level_aggregate_no_later_round_can_settle_stays_open_with_the_reason() -> None:
    legs = [m(1, A, B, 0, 1, 1), m(2, B, A, 7, 0, 0)]
    [tie] = one("Final", legs, advanced=later(A, B)).ties
    assert (tie.status, tie.reason) == ("unresolved", "level_on_aggregate_evidence_inconclusive")


def test_legs_that_do_not_swap_the_ground_are_flagged_not_refused() -> None:
    legs = [m(1, A, B, 0, 1, 0), m(2, A, B, 7, 0, 2)]
    pairs = [m(3, C, D, 0, 1, 0), m(4, D, C, 7, 1, 1)]
    [tie, _] = sorted(one("Quarter-finals", legs + pairs).ties, key=lambda t: t.team_a)
    assert tie.flags == ("legs_not_swapped",) and tie.winner == B and (tie.aggregate_a, tie.aggregate_b) == (1, 2)


def test_a_first_leg_alone_is_a_tie_in_progress_while_the_second_is_to_come() -> None:
    legs = [m(1, A, B, 0, 1, 0), m(2, B, A, 7, status="NS")]
    [tie] = one("Quarter-finals", legs, now=D0 + timedelta(days=1)).ties  # the second leg is still ahead
    assert (tie.status, tie.played, tie.winner, tie.aggregate_a, tie.aggregate_b) == ("in_progress", 1, None, 1, 0)


def test_a_round_of_two_legs_with_one_leg_listed_is_waiting_for_it() -> None:
    matches = [m(1, A, B, 0, 1, 0), m(2, B, A, 7, 1, 1), m(3, C, D, 0, 2, 0)]  # C - D has only a first leg
    result = one("Round of 16", matches, now=D0 + timedelta(days=1))
    tie = next(t for t in result.ties if t.team_a == C)
    assert (tie.status, tie.flags) == ("in_progress", ("second_leg_not_listed",))
    assert result.format == "two_legged"


def test_a_leg_that_never_came_and_a_witness_that_agrees_makes_the_one_match_the_tie() -> None:
    # the 2020 Europa League's last 16: four ties were one match after the pandemic broke the calendar
    matches = [m(1, A, B, 0, 1, 0), m(2, B, A, 7, 1, 1), m(3, C, D, 0, 2, 0)]
    [_, single] = sorted(one("Round of 16", matches, advanced=later(A, C)).ties, key=lambda t: t.team_a)
    assert (single.winner, single.check, single.played) == (C, "confirmed", 1)
    assert "single_leg_in_two_legged_round" in single.flags
    unwitnessed = next(t for t in one("Round of 16", matches, advanced=later(A)).ties if t.team_a == C)
    assert (unwitnessed.status, unwitnessed.reason) == ("unresolved", "second_leg_missing")
    disagreeing = next(t for t in one("Round of 16", matches, advanced=later(A, D)).ties if t.team_a == C)
    assert (disagreeing.status, disagreeing.reason) == ("unresolved", "second_leg_missing")


def test_a_postponed_first_leg_and_a_played_second_one_is_decided_by_the_second_if_the_next_round_agrees() -> None:
    matches = [m(1, A, B, 0, status="PST"), m(2, B, A, 7, 0, 3), m(3, C, D, 0, 1, 0), m(4, D, C, 7, 0, 0)]
    result = one("Quarter-finals", matches, advanced=later(A, C))
    postponed = next(t for t in result.ties if t.team_a == A)
    assert (postponed.winner, postponed.check, postponed.legs) == (A, "confirmed", ((1, 1), (2, 2)))
    assert (postponed.aggregate_a, postponed.aggregate_b, postponed.played) == (3, 0, 1)


def test_a_postponed_match_that_was_scheduled_again_is_one_fixture() -> None:
    matches = [m(1, A, B, 0, status="PST"), m(2, A, B, 40, 1, 0), m(3, B, A, 47, 0, 0)]
    result = one("Quarter-finals", matches)
    [tie] = result.ties
    assert result.dropped == (1,) and tie.fixture_ids == (2, 3) and tie.winner == A


def test_a_cancelled_match_is_in_no_tie() -> None:
    result = one("Quarter-finals", [m(1, A, B, 0, 1, 0), m(2, B, A, 7, 1, 1), m(3, B, A, 9, status="CANC")])
    [tie] = result.ties
    assert tie.fixture_ids == (1, 2) and result.dropped == (3,)


def test_a_tie_waiting_for_a_match_that_kicked_off_days_ago_says_why() -> None:
    never = one("Round of 16", [m(1, A, B, 0, status="NS")], now=D0 + timedelta(days=30)).ties[0]
    assert (never.status, never.reason) == ("unresolved", "never_played")
    postponed = one("Quarter-finals", [m(1, A, B, 0, status="PST"), m(2, B, A, 7, status="PST")],
                    now=D0 + timedelta(days=30)).ties[0]
    assert (postponed.status, postponed.reason) == ("unresolved", "postponed_for_good")
    abandoned = one("Round of 16", [m(1, A, B, 0, status="ABD")], now=D0 + timedelta(days=30)).ties[0]
    assert (abandoned.status, abandoned.reason) == ("unresolved", "abandoned")


def test_two_legs_with_a_walkover_leg_are_open_until_the_next_round_says() -> None:
    legs = [m(1, A, B, 0, None, None, "WO"), m(2, B, A, 7, None, None, "WO")]  # Leipzig - Spartak Moscow, March 2022
    [open_tie] = one("Round of 16", legs).ties
    assert (open_tie.status, open_tie.reason, open_tie.played) == ("unresolved", "awarded_without_score", 2)
    [settled] = one("Round of 16", legs, advanced=later(A)).ties
    assert (settled.winner, settled.decided_by) == (A, "walkover")


# ── replays and series ──────────────────────────────────────────────────────


def test_a_replay_decides_a_first_match_that_ended_level() -> None:
    first, replay = m(1, A, B, 0, 2, 2), m(2, B, A, 4, 0, 1, replay=True)
    others = [m(3, C, D, 0, 3, 0), m(4, E, F, 0, 1, 0)]
    result = one("1st Round", [first, replay, *others])
    tie = next(t for t in result.ties if t.format == "replay")
    assert (tie.winner, tie.decided_by, tie.legs) == (A, "normal_time", ((1, 1), (2, 2)))
    assert result.format == "single"  # a replay does not make a round two-legged
    assert sum(1 for t in result.ties if t.format == "single") == 2


def test_a_replay_can_go_to_penalties_and_the_shootout_is_oriented_to_the_first_matchs_home_side() -> None:
    first, replay = m(1, A, B, 0, 1, 1), m(2, B, A, 4, 0, 0, "PEN", pens=(5, 4), replay=True)
    result = one("1st Round", [first, replay, m(3, C, D, 0, 3, 0), m(4, E, F, 0, 1, 0)])
    tie = next(t for t in result.ties if t.format == "replay")
    assert (tie.winner, tie.decided_by, tie.shootout) == (B, "penalties", (4, 5))


def test_a_second_match_between_the_same_sides_in_a_round_of_single_matches_is_a_replay_even_in_the_same_stage() -> None:
    result = one("1st Round", [m(1, A, B, 0, 1, 1), m(2, B, A, 4, 2, 0), m(3, C, D, 0, 3, 0), m(4, E, F, 0, 1, 0)])
    tie = next(t for t in result.ties if t.format == "replay")
    assert (tie.winner, tie.team_a) == (B, A)


def test_a_best_of_three_is_a_series() -> None:
    games = [m(1, A, B, 0, 1, 0), m(2, B, A, 3, 2, 0), m(3, A, B, 6, 2, 1)]
    other = [m(4, C, D, 0, 1, 0), m(5, D, C, 3, 1, 0), m(6, C, D, 6, 0, 0, "PEN", pens=(5, 4))]
    result = one("MLS Cup - Conference Semi-finals", games + other)
    assert result.format == "series"
    first = next(t for t in result.ties if t.team_a == A)
    assert (first.format, first.winner, first.decided_by, first.aggregate_a, first.aggregate_b) == ("series", A, "series", 2, 1)
    assert next(t for t in result.ties if t.team_a == C).winner == C


# ── what is not a bracket ───────────────────────────────────────────────────


def test_a_team_in_two_pairings_means_the_stage_is_not_a_bracket() -> None:
    result = one("Playoffs", [m(1, A, B, 0, 1, 0), m(2, A, C, 3, 0, 0), m(3, B, C, 6, 2, 2)])
    assert result.format == "not_a_bracket" and result.ties == () and result.reason == "a_team_plays_several_opponents"


def test_a_stage_of_only_cancelled_matches_is_empty() -> None:
    result = one("Final", [m(1, A, B, 0, status="CANC")])
    assert result.format == "empty" and result.ties == () and result.dropped == (1,)


def test_four_matches_between_two_sides_are_unresolved_not_invented() -> None:
    result = one("Finals", [m(i, A if i % 2 else B, B if i % 2 else A, i, 1, 0) for i in range(1, 5)] + [m(9, C, D, 0, 1, 0)])
    tie = next(t for t in result.ties if t.team_a in (A, B))
    assert (tie.status, tie.reason) == ("unresolved", "too_many_matches")


# ── the next round as a witness ─────────────────────────────────────────────


def test_a_winner_is_confirmed_when_it_plays_on_and_the_loser_does_not() -> None:
    [tie] = one("Round of 16", [m(1, A, B, 0, 1, 0)], advanced=later(A)).ties
    assert tie.check == "confirmed"


def test_a_winner_the_next_round_contradicts_stays_the_winner_on_the_pitch_and_says_so() -> None:
    # Southampton won the 2026 Championship play-off semi-final on the pitch and were expelled for spying
    [tie] = one("Semi-finals", [m(1, A, B, 0, 1, 0)], advanced=later(B)).ties
    assert (tie.winner, tie.check) == (A, "contradicted")


def test_a_team_that_played_the_round_before_under_the_same_label_is_no_witness() -> None:
    # the AFC Champions League Two 2020 "Play-off Round" label was used twice: a loser's earlier match is not "later"
    before = {B: D0 - timedelta(days=14)}
    [tie] = one("Play-off Round", [m(1, A, B, 0, 1, 0)], advanced=before).ties
    assert tie.check == "unknown"


def test_a_winner_with_no_witness_at_all_is_simply_unknown() -> None:
    assert one("Final", [m(1, A, B, 0, 1, 0)]).ties[0].check == "unknown"
    assert one("Final", [m(1, A, B, 0, 1, 0)], advanced={}).ties[0].check == "unknown"


def test_the_version_of_the_rules_is_stored_with_the_ties() -> None:
    assert tl.VERSION == "ties-2"
