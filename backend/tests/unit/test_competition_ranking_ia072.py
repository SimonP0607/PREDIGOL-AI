"""IA-072 (AD-B01): the tie-breakers applied to results. One test per criterion that differs between regulations (UEFA-style
head-to-head reapplied, LaLiga's once, FIFA-style goal difference first, Brazil's wins first and head-to-head only between two,
Ligue 1 and Bundesliga only with both matches played, the Premier League's head-to-head only when it decides something), points
deductions, criteria the results cannot settle - and the closed seasons of production rebuilt place by place."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fbi.competitions import rules as rl
from fbi.competitions.ranking import Result, rank
from fbi.competitions.reconstruction import Match, ProviderRow, reconstruct
from fbi.competitions.rules import Ranking, Zone

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "competition_rules"
A, B, C, X, Y = 1, 2, 3, 8, 9


def ranking(*criteria: str, **h2h: object) -> Ranking:
    return Ranking.model_validate({"tiebreakers": list(criteria), "h2h": h2h})


# Three teams level on 7 points. Among them: A beat B 1-0 and C 3-0, B and C drew 2-2 - so A has 6 head-to-head points, B and
# C one each; B lost to A by one goal, C by three. Overall goal difference: A +4, B +1, C +5.
THREE_WAY = [Result(A, B, 1, 0), Result(A, C, 3, 0), Result(B, C, 2, 2), Result(A, X, 0, 0),
             Result(B, X, 1, 0), Result(B, Y, 1, 0), Result(C, Y, 4, 0), Result(C, X, 4, 0)]


def test_head_to_head_once_keeps_the_mini_league_of_all_the_tied_teams() -> None:
    t = rank(THREE_WAY, ranking("h2h_points", "h2h_goal_difference", "goal_difference", mode="once"), complete=True)
    assert t.order()[:3] == [A, B, C]  # B and C level on points between them: B's -1 against A beats C's -3
    assert t.place_of(B).decided_by == "h2h_goal_difference"


def test_head_to_head_reapplied_among_those_still_level_uefa_style() -> None:
    t = rank(THREE_WAY, ranking("h2h_points", "h2h_goal_difference", "h2h_goals_for", "goal_difference", mode="reapply"),
             complete=True)
    # A is out by head-to-head points; B and C start again between themselves: 2-2, level - then overall goal difference
    assert t.order()[:3] == [A, C, B]
    assert t.place_of(C).decided_by == "goal_difference"


def test_goal_difference_first_fifa_style_ignores_head_to_head() -> None:
    t = rank(THREE_WAY, ranking("goal_difference", "goals_for", "h2h_points"), complete=True)
    assert t.order()[:3] == [C, A, B]


def test_a_points_deduction_counts_in_the_table_and_is_shown_apart() -> None:
    t = rank(THREE_WAY, ranking("goal_difference"), complete=True, adjustments={C: -3})
    assert t.order()[:3] == [A, B, C]
    assert t.place_of(C).row.points == 4 and t.place_of(C).row.adjustment == -3


def test_brazil_wins_first_and_head_to_head_only_between_two() -> None:
    rules = rl.rules_for(71, 2026)
    assert isinstance(rules, rl.Coded)
    league = rules.rules.phase("season.league")[1].ranking
    assert league is not None and [t.criterion for t in league.tiebreakers][:4] == ["wins", "goal_difference", "goals_for",
                                                                                    "h2h_points"]
    # three teams level on everything up to goals scored: the head-to-head is skipped, the cards decide
    level = [Result(A, B, 1, 1), Result(B, C, 1, 1), Result(C, A, 1, 1)]
    t = rank(level, league, complete=True, external={"red_cards_fewer": {A: 2, B: 0, C: 1}})
    assert t.order() == [B, C, A] and t.place_of(B).decided_by == "red_cards_fewer"


def test_ligue_1_head_to_head_only_once_both_matches_are_played() -> None:
    rules = rl.rules_for(61, 2025)
    assert isinstance(rules, rl.Coded)
    _, phase = rules.rules.phase("season.league")
    assert phase.ranking is not None
    # A and B: same points and goal difference; A won the only match between them, B scored more goals overall
    results = [Result(A, B, 1, 0), Result(B, X, 3, 2), Result(A, X, 1, 0), Result(B, Y, 1, 0), Result(Y, A, 2, 1),
               Result(X, Y, 0, 0)]
    half = rank(results, phase.ranking, complete=False, legs=phase.legs_between_pair)
    assert half.order()[:2] == [B, A] and half.place_of(B).decided_by == "goals_for"
    full = rank([*results, Result(B, A, 0, 0)], phase.ranking, complete=True, legs=phase.legs_between_pair)
    assert full.order()[:2] == [A, B] and full.place_of(A).decided_by == "h2h_points"


def test_premier_league_head_to_head_only_when_the_tie_decides_something() -> None:
    rules = rl.rules_for(39, 2025)
    assert isinstance(rules, rl.Coded)
    _, phase = rules.rules.phase("season.league")
    assert phase.ranking is not None
    zones = [Zone.model_validate({"kind": "relegation", "from": 3, "to": 4})]
    # A and B level on points (4), goal difference (0) and goals (3): A won the head-to-head (2-1, 1-1)
    results = [Result(A, B, 2, 1), Result(B, A, 1, 1), Result(X, A, 1, 0), Result(B, X, 1, 0), Result(C, X, 5, 0),
               Result(C, Y, 5, 0)]
    on_the_line = rank(results, phase.ranking, complete=True, zones=zones, size=4, members=[C, A, B, X])
    assert on_the_line.order() == [C, A, B, X] and on_the_line.place_of(A).decided_by == "h2h_points"
    mid_table = rank(results, phase.ranking, complete=True, zones=[], size=4, members=[C, A, B, X])
    assert set(mid_table.place_of(A).shared_with) == {B} and mid_table.place_of(A).open_on == "exhausted"
    during = rank(results, phase.ranking, complete=False, zones=zones, size=4, members=[C, A, B, X])
    assert during.place_of(A).shared_with == (B,)


def test_laliga_two_clubs_by_head_to_head_goal_difference_more_by_a_mini_league() -> None:
    rules = rl.rules_for(140, 2025)
    assert isinstance(rules, rl.Coded)
    league = rules.rules.phase("season.league")[1].ranking
    assert league is not None and league.tiebreakers_if_two is not None
    assert league.tiebreakers_if_two[0].criterion == "h2h_goal_difference" and league.tiebreakers[0].criterion == "h2h_points"
    two = [Result(A, B, 2, 0), Result(B, A, 1, 0), Result(B, X, 3, 0), Result(A, X, 1, 1), Result(X, A, 0, 1),
           Result(X, B, 1, 1)]
    t = rank(two, league, complete=True, legs=2)
    assert t.order()[:2] == [A, B] and t.place_of(A).decided_by == "h2h_goal_difference"  # B has the better overall goals


def test_a_criterion_the_results_cannot_settle_leaves_the_tie_open_until_it_is_given() -> None:
    rules = rl.rules_for(135, 2025)  # Serie A: ... then lots
    assert isinstance(rules, rl.Coded)
    league = rules.rules.phase("season.league")[1].ranking
    assert league is not None
    level = [Result(A, B, 1, 1), Result(B, A, 2, 2)]
    open_tie = rank(level, league, complete=True)
    assert open_tie.place_of(A).open_on == "lots" and open_tie.open_ties == [(A, B)]
    drawn = rank(level, league, complete=True, external={"lots": {A: 2, B: 1}})
    assert drawn.order() == [B, A] and drawn.place_of(B).decided_by == "lots"


def test_uefa_league_phase_in_progress_uses_a_to_e_then_alphabetical() -> None:
    rules = rl.rules_for(2, 2026)
    assert isinstance(rules, rl.Coded)
    _, phase = rules.rules.phase("season.league_phase")
    assert phase.ranking is not None
    level = [Result(A, X, 1, 0), Result(B, Y, 1, 0)]
    t = rank(level, phase.ranking, complete=False, names={A: "Zeta", B: "Alfa", X: "x", Y: "y"})
    assert t.order()[:2] == [B, A] and t.place_of(B).decided_by == "alphabetical"
    final = rank(level, phase.ranking, complete=True, external={"disciplinary_points": {A: 3, B: 5},
                                                                 "club_coefficient": {A: 1.0, B: 2.0}})
    # same goals, wins and away record, opponents level too: fewer disciplinary points first
    assert final.order()[:2] == [A, B] and final.place_of(A).decided_by == "disciplinary_points"


def test_colombia_cuadrangular_a_seeded_club_wins_a_tie_then_the_phase_i_place() -> None:
    rules = rl.rules_for(239, 2026)
    assert isinstance(rules, rl.Coded)
    _, phase = rules.rules.phase("liga_ii.cuadrangulares")
    assert phase.ranking is not None
    level = [Result(A, B, 1, 1), Result(B, A, 1, 1)]
    t = rank(level, phase.ranking, complete=True, external={"seed_priority": {A: 0, B: 1}, "prior_phase_rank": {A: 4, B: 1}})
    assert t.order() == [B, A] and t.place_of(B).decided_by == "seed_priority"
    t = rank(level, phase.ranking, complete=True, external={"seed_priority": {A: 0, B: 0}, "prior_phase_rank": {A: 4, B: 7}})
    assert t.order() == [A, B] and t.place_of(A).decided_by == "prior_phase_rank"


# ── closed seasons of production, rebuilt place by place ────────────────────


def _frozen(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


FROZEN = sorted(p.name for p in FIXTURES.glob("*.json"))


def test_the_frozen_seasons_are_the_ones_described() -> None:
    assert FROZEN == ["128_2026_clausura_zonas.json", "135_2025_season_league.json", "140_2025_season_league.json",
                      "239_2026_liga_i_fase_1.json", "253_2026_season_regular.json", "262_2025_clausura_calificacion.json",
                      "39_2025_season_league.json", "78_2025_season_league.json"]


@pytest.mark.parametrize("name", FROZEN)
def test_the_rules_rebuild_the_providers_final_table_place_by_place(name: str) -> None:
    d = _frozen(name)
    answer = rl.rules_for(int(d["league_id"]), int(d["season"]))  # type: ignore[call-overload]
    assert isinstance(answer, rl.Coded)
    matches = [Match(m[0], "FT", m[1], m[2], m[3], m[4]) for m in d["matches"]]  # type: ignore[attr-defined]
    groups = {g: [ProviderRow(*row) for row in rows] for g, rows in d["tables"].items()}  # type: ignore[attr-defined]
    for c in reconstruct(answer.rules, str(d["phase"]), matches, groups):
        assert c.complete, c.group
        assert c.data_differs == (), c.group
        assert c.identical and c.same == c.teams, (c.group, c.different)


def _final(name: str) -> tuple[dict[str, object], list[tuple[int, str, str | None]]]:
    d = _frozen(name)
    answer = rl.rules_for(int(d["league_id"]), int(d["season"]))  # type: ignore[call-overload]
    assert isinstance(answer, rl.Coded)
    _, phase = answer.rules.phase(str(d["phase"]))
    assert phase.ranking is not None
    results = [Result(m[1], m[2], m[3], m[4]) for m in d["matches"] if phase.covers(m[0])]  # type: ignore[attr-defined]
    t = rank(results, phase.ranking, points=answer.rules.points, complete=True, legs=phase.legs_between_pair,
             zones=phase.zones, size=phase.teams)
    teams: dict[str, str] = d["teams"]  # type: ignore[assignment]
    return d, [(p.position, teams[str(p.team)], p.decided_by) for p in t.places]


def test_laliga_2025_26_three_way_ties_settled_by_the_mini_league() -> None:
    _, places = _final("140_2025_season_league.json")
    by_pos = {pos: (team, by) for pos, team, by in places}
    # Sevilla, Alavés and Elche on 43 points: Sevilla 13th with the worst goal difference of the three, by head-to-head
    assert [by_pos[i] for i in (13, 14, 15)] == [("Sevilla", "h2h_points"), ("Alaves", "h2h_points"), ("Elche", "h2h_points")]
    # Levante, Osasuna and Mallorca on 42: the head-to-head sends Mallorca to 18th, the first relegation place
    assert by_pos[18] == ("Mallorca", "h2h_points")


def test_serie_a_2025_26_classifica_avulsa_puts_torino_above_parma() -> None:
    _, places = _final("135_2025_season_league.json")
    by_pos = {pos: (team, by) for pos, team, by in places}
    assert by_pos[12] == ("Torino", "h2h_goal_difference") and by_pos[13] == ("Parma", "h2h_goal_difference")
