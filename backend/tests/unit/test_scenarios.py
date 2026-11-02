"""The scenarios of a match (``fbi.intel.scenarios``, plan F6): what the match alone does to a table or to a tie - the arithmetic, checked
against a brute-force count for every result and margin the match could end on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.ai.context import TableRow
from fbi.competitions import context as cx
from fbi.intel import scenarios as sc

SNAPSHOT = datetime(2026, 10, 20, 9, tzinfo=UTC)
TITLE, EUROPA, DROP = "Promotion - Champions League", "Promotion - Europa League", "Relegation"


def table() -> list[TableRow]:
    return [TableRow(1, 1, 15, 8, TITLE), TableRow(2, 2, 13, 8, TITLE), TableRow(3, 3, 10, 8, EUROPA),
            TableRow(4, 4, 10, 8, EUROPA), TableRow(5, 5, 7, 8, None), TableRow(6, 6, 3, 8, DROP)]


# ── the table ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_what_each_result_does_to_the_two_sides_when_nobody_else_moves() -> None:
    out = sc.table_effect(table(), 3, 5, snapshot_at=SNAPSHOT, group="Premier League")
    assert out is not None
    assert (out["basis"], out["teams"], out["group"], out["snapshot_at"]) == (
        "this_match_alone", 6, "Premier League", SNAPSHOT.isoformat())
    assert out["home"] == {"team_id": 3, "rank_now": 3, "points_now": 10, "played": 8, "zone_now": EUROPA}
    win = out["after"]["home_win"]
    assert (win["home"]["points"], win["home"]["rank_best"], win["home"]["rank_worst"]) == (13, 2, 3)
    assert [z["description"] for z in win["home"]["zones"]] == [TITLE, EUROPA], "13 points tie the second place: both zones are possible"
    assert [z["kind"] for z in win["home"]["zones"]] == ["europe", "europe"], "the provider's words, and the kind the stakes read"
    assert (win["away"]["points"], win["away"]["rank_best"], win["away"]["rank_worst"]) == (7, 5, 5)
    draw = out["after"]["draw"]
    assert (draw["home"]["points"], draw["home"]["rank_best"], draw["home"]["rank_worst"]) == (11, 3, 3)
    assert (draw["away"]["points"], draw["away"]["rank_best"], draw["away"]["rank_worst"]) == (8, 5, 5)
    loss = out["after"]["away_win"]
    assert (loss["home"]["points"], loss["home"]["rank_best"], loss["home"]["rank_worst"]) == (10, 3, 5)
    assert (loss["away"]["points"], loss["away"]["rank_best"], loss["away"]["rank_worst"]) == (10, 3, 5)
    assert [z["description"] for z in loss["away"]["zones"]] == [EUROPA, None], "the fifth place has no zone"
    assert [z["kind"] for z in loss["away"]["zones"]] == ["europe", None]


def brute_force(rows: list[TableRow], home: int, away: int, dh: int, da: int, team: int) -> tuple[int, int]:
    """The best and worst place of ``team`` by counting every other side's points after the result."""
    points = {r.team_id: r.points + (dh if r.team_id == home else da if r.team_id == away else 0) for r in rows}
    mine = points[team]
    others = [p for t, p in points.items() if t != team]
    return 1 + sum(p > mine for p in others), 1 + sum(p >= mine for p in others)


@pytest.mark.parametrize(("home", "away"), [(1, 2), (3, 4), (5, 6), (6, 1), (4, 5), (2, 6)])
def test_the_intervals_are_the_count_of_the_teams_with_more_points_and_with_as_many(home: int, away: int) -> None:
    rows = table()
    out = sc.table_effect(rows, home, away)
    assert out is not None and "unavailable" not in out
    for result, dh, da in sc.RESULTS:
        for side, team in (("home", home), ("away", away)):
            got = out["after"][result][side]
            assert (got["rank_best"], got["rank_worst"]) == brute_force(rows, home, away, dh, da, team), (result, side)
            assert got["rank_best"] <= got["rank_worst"]


def test_a_win_never_leaves_a_side_worse_than_a_draw_and_a_loss_never_better() -> None:
    out = sc.table_effect(table(), 4, 3)
    assert out is not None
    for side in ("home", "away"):
        pts = {r: out["after"][r][side]["points"] for r in ("home_win", "draw", "away_win")}
        best = {r: out["after"][r][side]["rank_best"] for r in pts}
        worst = {r: out["after"][r][side]["rank_worst"] for r in pts}
        order = ("home_win", "draw", "away_win") if side == "home" else ("away_win", "draw", "home_win")
        assert pts[order[0]] > pts[order[1]] > pts[order[2]]
        assert best[order[0]] <= best[order[1]] <= best[order[2]]
        assert worst[order[0]] <= worst[order[1]] <= worst[order[2]]


def test_a_table_that_is_not_ordered_by_points_is_not_read() -> None:
    rows = table()
    rows[2] = TableRow(3, 3, 4, 8, EUROPA)  # third place with 4 points, below teams that have 7 and 10
    out = sc.table_effect(rows, 3, 5, snapshot_at=SNAPSHOT)
    assert out == {"version": sc.VERSION, "unavailable": sc.TABLE_UNAVAILABLE, "group": None,
                   "snapshot_at": SNAPSHOT.isoformat()}


def test_a_side_that_is_not_in_the_table_has_no_scenarios() -> None:
    assert sc.table_effect(table(), 3, 99) is None
    assert sc.table_effect(table(), 3, 3) is None
    assert sc.table_effect([], 1, 2) is None


def test_teams_level_on_points_can_end_anywhere_between_their_tied_places() -> None:
    rows = [TableRow(1, 1, 9, 4, None), TableRow(2, 2, 6, 4, None), TableRow(3, 3, 6, 4, None), TableRow(4, 4, 6, 4, None),
            TableRow(5, 5, 0, 4, None)]
    out = sc.table_effect(rows, 2, 5)
    assert out is not None
    # a defeat leaves the home side on 6 points, level with the two others on 6: any place from the second to the fourth
    assert (out["after"]["away_win"]["home"]["rank_best"], out["after"]["away_win"]["home"]["rank_worst"]) == (2, 4)
    # a win takes it to 9, level with the leader
    assert (out["after"]["home_win"]["home"]["rank_best"], out["after"]["home_win"]["home"]["rank_worst"]) == (1, 2)
    # a draw takes it to 7: second, alone
    assert (out["after"]["draw"]["home"]["rank_best"], out["after"]["draw"]["home"]["rank_worst"]) == (2, 2)


# ── the tie ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

HOME, AWAY = 10, 20
D0 = datetime(2026, 2, 17, 20, tzinfo=UTC)


def second_leg(first_leg: tuple[int, int] | None) -> cx.TieAsOf:
    earlier = [] if first_leg is None else [cx.EarlierLeg(
        fixture_id=1, leg=1, kickoff_at=D0 - timedelta(days=7), home_team_id=AWAY, away_team_id=HOME, status="FT",
        goals_home=first_leg[0], goals_away=first_leg[1])]
    return cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="two_legged", earlier=earlier)


@pytest.mark.parametrize("lead", range(-5, 6))
def test_every_statement_about_the_second_leg_agrees_with_the_count_for_every_margin(lead: int) -> None:
    home_goals, away_goals = (max(0, lead), max(0, -lead)) if lead != 0 else (1, 1)
    # the first leg was at AWAY's ground: its goals are the first number, HOME's the second
    out = sc.tie_reading(second_leg((away_goals, home_goals)))
    assert out is not None and out["lead_home_side"] == lead == home_goals - away_goals
    h, a = out["home_side"], out["away_side"]
    for margin in range(-9, 10):
        total = lead + margin
        assert (margin >= h["ahead_if_margin_at_least"]) == (total > 0)
        assert (margin == h["level_if_margin"]) == (total == 0)
        assert (margin <= h["behind_if_margin_at_most"]) == (total < 0)
        away_margin = -margin
        assert (away_margin >= a["ahead_if_margin_at_least"]) == (total < 0)
        assert (away_margin == a["level_if_margin"]) == (total == 0)
        assert (away_margin <= a["behind_if_margin_at_most"]) == (total > 0)
    # "can lose by up to d": the largest defeat that leaves the side ahead on aggregate; "needs to win by at least": the smallest win
    for side, own in (("home_side", lead), ("away_side", -lead)):
        stays_ahead = [d for d in range(0, 12) if own - d > 0]
        assert out[side]["can_lose_by_up_to"] == (max(stays_ahead) if stays_ahead else None), side
        wins_needed = [m for m in range(1, 12) if own + m > 0]
        assert out[side]["needs_to_win_by_at_least"] == (min(wins_needed) if own <= 0 else None), side
    assert out["if_level"] == "competition_rules", "what happens on a level aggregate is the competition's rule: never assumed"


def test_a_second_leg_the_home_side_leads_by_two() -> None:
    out = sc.tie_reading(second_leg((0, 2)))
    assert out is not None
    assert out["aggregate_before"] == {"home_side": 2, "away_side": 0}
    assert out["home_side"]["can_lose_by_up_to"] == 1 and out["home_side"]["needs_to_win_by_at_least"] is None
    assert out["away_side"]["needs_to_win_by_at_least"] == 3 and out["away_side"]["can_lose_by_up_to"] is None


def test_a_second_leg_without_the_first_result_says_it_does_not_know() -> None:
    out = sc.tie_reading(second_leg(None))
    assert out is not None and out["aggregate"] == "unknown" and "lead_home_side" not in out


def test_the_other_kinds_of_tie_are_passed_through() -> None:
    first = cx.tie_as_of(home=HOME, away=AWAY, leg=1, stored_format="two_legged", earlier=[])
    assert sc.tie_reading(first) == {"version": sc.VERSION, "kind": "first_leg"}
    single = cx.tie_as_of(home=HOME, away=AWAY, leg=1, stored_format="single", earlier=[])
    assert sc.tie_reading(single) == {"version": sc.VERSION, "kind": "single_match"}
    replay = cx.tie_as_of(home=HOME, away=AWAY, leg=2, stored_format="replay", earlier=[])
    assert sc.tie_reading(replay) == {"version": sc.VERSION, "kind": "replay", "decides_the_tie": True}
    assert sc.tie_reading(None) is None


def test_the_block_of_the_packet() -> None:
    assert sc.scenarios_block(None, None) is None
    block = sc.scenarios_block({"basis": "this_match_alone"}, None)
    assert block == {"version": sc.VERSION, "status": "DESCRIPTIVE", "table": {"basis": "this_match_alone"}, "tie": None,
                     "note": sc.NOTE}
    assert "no son probabilidades" in sc.NOTE and "los demás partidos no se simulan" in sc.NOTE
