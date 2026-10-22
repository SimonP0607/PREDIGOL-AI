"""``fbi.api.services.center_tie``: the tie of a match as the match page tells it (plan F2).

The rules under test: every score is from THIS match's home and away; a tie in progress shows the aggregate so far, summed from
its legs; a decided tie shows the audited aggregate and who went through, but only on the page of a match that is over."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.api.services import center_tie as ct

D0 = datetime(2026, 3, 3, 20, tzinfo=UTC)
A, B = 10, 20
"""The two teams of the tie; A is ``team_a_id`` (the lower id) in the stored row."""


def leg(fixture_id: int, n: int, day: int, home: int, away: int, goals: tuple[int, int] | None, *, group: str = "finished",
        status: str = "FT", extra_time: bool = False, shootout: tuple[int, int] | None = None) -> dict[str, Any]:
    return {"fixture_id": fixture_id, "leg": n, "kickoff_at": D0 + timedelta(days=day), "home_team_id": home,
            "away_team_id": away, "home": f"Team {home}", "away": f"Team {away}", "status": status,
            "status_group": group, "goals_home": None if goals is None else goals[0],
            "goals_away": None if goals is None else goals[1], "extra_time": extra_time,
            "shootout_home": None if shootout is None else shootout[0],
            "shootout_away": None if shootout is None else shootout[1]}


def tie(*, fmt: str = "two_legged", status: str = "in_progress", legs: int = 2, aggregate: tuple[int, int] | None = None,
        winner: int | None = None, decided_by: str | None = None, shootout: tuple[int, int] | None = None,
        check: str = "unknown") -> dict[str, Any]:
    return {"tie_id": 1, "format": fmt, "status": status, "legs": legs, "team_a_id": A, "team_b_id": B,
            "aggregate_a": None if aggregate is None else aggregate[0],
            "aggregate_b": None if aggregate is None else aggregate[1], "winner_team_id": winner,
            "decided_by": decided_by, "shootout_a": None if shootout is None else shootout[0],
            "shootout_b": None if shootout is None else shootout[1], "winner_check": check}


FIRST = leg(1, 1, 0, A, B, (2, 0))
"""A won the first leg at home, 2-0."""


def second(goals: tuple[int, int] | None, *, group: str = "finished", **kw: Any) -> dict[str, Any]:
    return leg(2, 2, 7, B, A, goals, group=group, **kw)


# ── a second leg, from the page of the side that hosts it ───────────────────


def test_a_second_leg_not_yet_played_shows_the_first_leg_from_the_side_that_hosts_the_second() -> None:
    view = ct.tie_view(tie(), [FIRST, second(None, group="scheduled", status="NS")], fixture_id=2, home_team_id=B,
                       status_group="scheduled")

    assert (view.format, view.state, view.leg, view.legs, view.played) == ("two_legged", "in_progress", 2, 2, 1)
    assert view.aggregate_before is not None and (view.aggregate_before.home, view.aggregate_before.away) == (0, 2)
    assert view.aggregate is not None and (view.aggregate.home, view.aggregate.away) == (0, 2), "the aggregate so far"
    assert view.outcome is None
    assert [(x.fixture_id, x.is_this) for x in view.legs_list] == [(1, False), (2, True)]


def test_a_second_leg_in_play_shows_only_what_was_before_it() -> None:
    view = ct.tie_view(tie(), [FIRST, second(None, group="live", status="2H")], fixture_id=2, home_team_id=B,
                       status_group="live")

    assert view.aggregate_before is not None and (view.aggregate_before.home, view.aggregate_before.away) == (0, 2)
    assert view.outcome is None


def test_a_decided_tie_on_the_page_of_its_last_leg_shows_the_audited_aggregate_and_who_went_through() -> None:
    row = tie(status="decided", aggregate=(3, 2), winner=A, decided_by="aggregate", check="confirmed")

    view = ct.tie_view(row, [FIRST, second((2, 1))], fixture_id=2, home_team_id=B, status_group="finished")

    assert view.aggregate is not None and (view.aggregate.home, view.aggregate.away) == (2, 3), "B hosted this one"
    assert view.outcome is not None
    assert (view.outcome.winner, view.outcome.decided_by, view.outcome.shootout, view.outcome.contradicted) == (
        "away", "aggregate", None, False)
    assert view.played == 2


def test_the_same_tie_from_the_page_of_its_first_leg_is_told_from_the_side_that_hosted_that_one() -> None:
    row = tie(status="decided", aggregate=(3, 2), winner=A, decided_by="aggregate", check="confirmed")

    view = ct.tie_view(row, [FIRST, second((2, 1))], fixture_id=1, home_team_id=A, status_group="finished")

    assert view.leg == 1 and view.aggregate_before is None, "nothing came before the first leg"
    assert view.aggregate is not None and (view.aggregate.home, view.aggregate.away) == (3, 2)
    assert view.outcome is not None and view.outcome.winner == "home"


def test_a_shoot_out_is_told_from_the_side_that_hosts_the_match() -> None:
    row = tie(status="decided", aggregate=(2, 2), winner=B, decided_by="penalties", shootout=(3, 4), check="confirmed")
    legs = [FIRST, second((2, 0), status="PEN", shootout=(4, 3))]

    view = ct.tie_view(row, legs, fixture_id=2, home_team_id=B, status_group="finished")

    assert view.outcome is not None and view.outcome.winner == "home" and view.outcome.decided_by == "penalties"
    assert view.outcome.shootout is not None and (view.outcome.shootout.home, view.outcome.shootout.away) == (4, 3)
    assert view.legs_list[1].shootout_home == 4


def test_a_contradicted_winner_is_still_the_sporting_winner_and_says_so() -> None:
    row = tie(status="decided", aggregate=(3, 2), winner=B, decided_by="walkover", check="contradicted")

    view = ct.tie_view(row, [FIRST, second((2, 1))], fixture_id=2, home_team_id=B, status_group="finished")

    assert view.outcome is not None and view.outcome.winner == "home" and view.outcome.contradicted is True


# ── what is not yet known is not told ───────────────────────────────────────


def test_the_page_of_a_match_not_yet_over_never_carries_what_the_tie_decided() -> None:
    """The stored row says 'decided' (a row that outran the page, or a match put back): the outcome and the stored aggregate
    stay out, the sum so far is what is shown."""
    row = tie(status="decided", aggregate=(9, 9), winner=A, decided_by="aggregate", check="confirmed")

    view = ct.tie_view(row, [FIRST, second(None, group="live", status="2H")], fixture_id=2, home_team_id=B,
                       status_group="live")

    assert view.outcome is None
    assert view.aggregate is not None and (view.aggregate.home, view.aggregate.away) == (0, 2)


def test_a_match_just_over_before_the_worker_decides_the_tie_shows_the_sum_without_an_outcome() -> None:
    view = ct.tie_view(tie(), [FIRST, second((1, 1))], fixture_id=2, home_team_id=B, status_group="finished")

    assert view.state == "in_progress" and view.outcome is None
    assert view.aggregate is not None and (view.aggregate.home, view.aggregate.away) == (1, 3)
    assert view.played == 2


def test_a_leg_over_without_goals_makes_the_sum_unknown_not_a_smaller_sum() -> None:
    awarded = second(None, status="AWD")  # over, awarded at the table: no goals stored

    view = ct.tie_view(tie(), [FIRST, awarded], fixture_id=2, home_team_id=B, status_group="finished")

    assert view.aggregate is None and view.aggregate_before is not None, "the first leg is before it, and it is known"
    assert view.played == 1


def test_a_decided_tie_stored_without_an_aggregate_shows_none_on_purpose() -> None:
    row = tie(status="decided", winner=A, decided_by="walkover", check="contradicted")

    view = ct.tie_view(row, [FIRST, second(None, status="AWD")], fixture_id=2, home_team_id=B, status_group="finished")

    assert view.aggregate is None and view.outcome is not None and view.outcome.decided_by == "walkover"


# ── the other formats ───────────────────────────────────────────────────────


def test_a_single_match_has_no_aggregate_and_a_decided_one_says_who_went_through() -> None:
    row = tie(fmt="single", status="decided", legs=1, winner=A, decided_by="extra_time", check="confirmed")
    only = leg(1, 1, 0, A, B, (2, 1), status="AET", extra_time=True)

    view = ct.tie_view(row, [only], fixture_id=1, home_team_id=A, status_group="finished")

    assert (view.format, view.leg, view.legs, view.aggregate, view.aggregate_before) == ("single", 1, 1, None, None)
    assert view.outcome is not None and (view.outcome.winner, view.outcome.decided_by) == ("home", "extra_time")
    assert view.legs_list[0].extra_time is True


@pytest.mark.parametrize("fmt", ["replay", "series"])
def test_a_replay_or_a_series_is_not_added_up(fmt: str) -> None:
    row = tie(fmt=fmt, status="in_progress", legs=2 if fmt == "replay" else 3)
    legs = [leg(1, 1, 0, A, B, (1, 1)), leg(2, 2, 10, B, A, None, group="scheduled", status="NS")]

    view = ct.tie_view(row, legs, fixture_id=2, home_team_id=B, status_group="scheduled")

    assert view.format == fmt and view.aggregate is None and view.aggregate_before is None
    assert view.played == 1 and len(view.legs_list) == 2


def test_a_leg_without_a_number_is_still_found_by_its_place_in_time() -> None:
    unnumbered = leg(2, 2, 7, B, A, None, group="scheduled", status="NS") | {"leg": None}

    view = ct.tie_view(tie(), [FIRST, unnumbered], fixture_id=2, home_team_id=B, status_group="scheduled")

    assert view.leg is None
    assert view.aggregate_before is not None and (view.aggregate_before.home, view.aggregate_before.away) == (0, 2)


def test_a_fixture_that_is_not_among_the_legs_of_its_tie_still_gets_a_tie_without_a_before() -> None:
    view = ct.tie_view(tie(), [FIRST], fixture_id=99, home_team_id=B, status_group="scheduled")

    assert view.leg is None and view.aggregate_before is None
    assert view.aggregate is not None and (view.aggregate.home, view.aggregate.away) == (0, 2)
