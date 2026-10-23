"""Memory with a confidence (plan F8, ``memory-v4``), without a database: how evidence ages, how much of it is enough, how the figures of a
team are shrunk toward its league's, and what a row says it rests on.

The queries and the lineage are tested on a real database in tests/integration/test_intel_memory_v4.py."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from fbi.intel import memory

DAY = date(2026, 10, 20)


# ── age ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_piece_of_evidence_loses_half_its_weight_after_the_half_life() -> None:
    assert memory.decay(0, 90) == 1.0
    assert memory.decay(90, 90) == pytest.approx(0.5)
    assert memory.decay(180, 90) == pytest.approx(0.25)
    assert memory.decay(-5, 90) == 1.0, "evidence from the future counts in full: age is never negative"


def test_the_weight_carries_the_row_before_aged_by_the_days_between_the_two_and_adds_the_days_own_evidence() -> None:
    spec = memory.TEAM_FIGURES  # half-life 180 days, counts matches, keeps what the team produced (own) and conceded (opp)
    prev = {"n_eff": 4.0, "w_own": 40.0, "w_opp": 20.0}
    delta = {"matches": 1, "own": 9, "opp": 7}
    got = memory.weights(prev, DAY, delta, DAY + timedelta(days=180), spec)
    assert got == {"matches": pytest.approx(3.0), "own": pytest.approx(29.0), "opp": pytest.approx(17.0)}  # type: ignore[comparison-overlap]
    same_day = memory.weights(prev, DAY, delta, DAY, spec)
    assert same_day == {"matches": 5.0, "own": 49.0, "opp": 27.0}, "no gap, no ageing"


def test_the_first_row_of_an_entity_has_nothing_to_carry() -> None:
    assert memory.weights(None, None, {"matches": 2, "own": 11, "opp": 9}, DAY, memory.TEAM_FIGURES) == {"matches": 2.0, "own": 11.0, "opp": 9.0}


def test_news_learned_late_weighs_what_its_own_day_weighs_not_what_the_day_it_was_learned_weighs() -> None:
    spec = memory.REFEREE  # half-life 365 days
    delta = {"matches": 0, "late": {(DAY - timedelta(days=365)).isoformat(): {"matches": 2}, (DAY - timedelta(days=1)).isoformat(): {"matches": 1}}}
    got = memory.weights(None, None, delta, DAY, spec)
    assert got["matches"] == pytest.approx(2 * 0.5 + 1 * memory.decay(1, 365))


def test_the_weight_never_goes_negative_when_the_news_takes_back_more_than_the_row_has() -> None:
    delta = {"decisions": 0, "late": {DAY.isoformat(): {"decisions": -3}}}
    assert memory.weights({"n_eff": 1.0}, DAY, delta, DAY, memory.DECISIONS_TEAM) == {"decisions": 0.0}


# ── confidence ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_confidence_is_nothing_without_evidence_one_half_at_k_and_never_certainty() -> None:
    assert memory.confidence_of(0.0, 30) == 0.0
    assert memory.confidence_of(30.0, 30) == 0.5
    assert memory.confidence_of(3.0, 30) < memory.confidence_of(300.0, 30) < 1.0
    assert memory.confidence_of(1e9, 30) <= 1.0


def test_settle_adds_the_numbers_stores_the_weighted_sample_and_says_how_far_to_trust_it() -> None:
    state, confidence = memory.settle(None, None, {"matches": 1, "cards": 4}, DAY, memory.REFEREE)
    assert state["matches"] == 1 and state["cards"] == 4 and state["cards_per_match"] == 4.0
    assert state["n_eff"] == 1.0 and confidence == pytest.approx(1 / 21, abs=1e-4)
    again, later = memory.settle(state, DAY, {"matches": 1, "cards": 2}, DAY + timedelta(days=365), memory.REFEREE)
    assert again["matches"] == 2 and again["cards"] == 6, "the counters are the counters: they do not age"
    assert again["n_eff"] == pytest.approx(1.5), "the sample does: the first match is a year old"
    assert later == pytest.approx(1.5 / 21.5, abs=1e-4)


def test_a_kind_of_memory_without_a_convention_has_a_state_and_no_confidence() -> None:
    state, confidence = memory.settle(None, None, {"matches": 1}, DAY, None)
    assert state["matches"] == 1 and "n_eff" not in state and confidence is None


def test_a_state_never_inherits_a_figure_that_is_computed_from_the_others() -> None:
    """The shrunk figure of the row before was computed against a league that may no longer have evidence: it is computed again or absent."""
    prev = {"n_eff": 3.0, "w_own": 30.0, "w_opp": 24.0, "matches": 3, "own": 30, "opp": 24, "own_shrunk": 9.5, "prior": 10.0, "prior_matches": 3,
            "own_rate": 10.0}
    state, _ = memory.settle(prev, DAY, {"matches": 1, "own": 5, "opp": 5, "by_competition": {"7": 1}}, DAY, memory.TEAM_FIGURES)
    assert "own_shrunk" not in state and "prior" not in state and "own_rate" not in state
    assert state["matches"] == 4 and state["by_competition"] == {"7": 1}


@pytest.mark.parametrize(("key", "spec"), [
    (("team", "1", "market:OU"), memory.DECISIONS_TEAM), (("competition", "9", "market:1X2"), memory.DECISIONS_COMPETITION),
    (("market", "1X2", "decisions"), memory.DECISIONS_MARKET), (("referee", "3", "discipline"), memory.REFEREE),
    (("coach", "4", "profile"), memory.COACH), (("player", "5", "availability"), memory.PLAYER),
    (("team", "1", "corners"), memory.TEAM_FIGURES), (("team", "1", "cards"), memory.TEAM_FIGURES), (("team", "1", "xg"), memory.TEAM_FIGURES),
    (("competition", "9", "corners"), memory.LEAGUE_FIGURES), (("competition", "9", "xg"), memory.LEAGUE_FIGURES),
])
def test_every_kind_of_row_the_memory_writes_has_its_convention(key: memory.EKey, spec: memory.Spec) -> None:
    assert memory.spec_for(key) is spec


def test_a_kind_nobody_wrote_has_none() -> None:
    assert memory.spec_for(("fixture", "1", "corners")) is None and memory.spec_for(("team", "1", "mystery")) is None
    assert memory.spec_for(("referee", "1", "corners")) is None, "a referee has no corners: the figures are the teams' and the leagues'"


def test_the_conventions_are_sane() -> None:
    for spec in (memory.DECISIONS_TEAM, memory.DECISIONS_COMPETITION, memory.DECISIONS_MARKET, memory.REFEREE, memory.COACH, memory.PLAYER,
                 memory.TEAM_FIGURES, memory.LEAGUE_FIGURES):
        assert spec.half_life > 0 and spec.k > 0 and spec.count
    assert memory.LEAGUE_FIGURES.k > memory.TEAM_FIGURES.k, "a league's mean needs more matches than a team's before it is trusted"
    assert set(memory.METRICS) == {"corners", "cards", "xg"} and all(m.prior_weight > 0 for m in memory.METRICS.values())


# ── what a match says ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_corners_are_a_pair_only_when_both_sides_report_them() -> None:
    corners = memory.METRICS["corners"].pair
    assert corners({"corners": 5}, {"corners": 7}) == (5, 7)
    assert corners({"corners": 0}, {"corners": 3}) == (0, 3), "zero is a number"
    assert corners({"corners": 5}, {"corners": None}) is None and corners({"corners": None}, {"corners": 2}) is None and corners({}, {}) is None


def test_cards_are_yellow_plus_red_of_a_side_that_has_a_line_of_statistics() -> None:
    cards = memory.METRICS["cards"].pair
    assert cards({"yellow_cards": 2, "red_cards": 1}, {"yellow_cards": 3, "red_cards": None}) == (3, 3)
    assert cards({"yellow_cards": None, "red_cards": None, "corners": 4}, {"yellow_cards": 1}) == (0, 1), "a line that says nothing of cards: none"
    assert cards({}, {"yellow_cards": 1}) is None and cards({"yellow_cards": 1}, {}) is None, "no line for a side: the match says nothing of cards"


def test_xg_is_a_pair_of_numbers_only_when_both_sides_report_it() -> None:
    xg = memory.METRICS["xg"].pair
    assert xg({"expected_goals": 1.8}, {"expected_goals": 0.6}) == (1.8, 0.6)
    assert xg({"expected_goals": 0.0}, {"expected_goals": 0.5}) == (0.0, 0.5)
    assert xg({"expected_goals": 1.8}, {"expected_goals": None}) is None


# ── shrinkage ───────────────────────────────────────────────────────────────────────────────────────────────────────────


LEAGUE = {"n_eff": 50.0, "w_total": 1000.0}  # 20 corners in a match: 10 for each team


def test_a_league_figure_is_the_mean_per_team_in_a_match() -> None:
    assert memory.league_rate(LEAGUE) == 10.0
    assert memory.league_rate({"n_eff": 0.0, "w_total": 0.0}) is None and memory.league_rate(None) is None and memory.league_rate({}) is None
    assert memory.figures(LEAGUE, "corners", {}) == {"rate": 10.0}


def test_a_team_with_two_matches_is_close_to_its_league_and_one_with_many_is_itself() -> None:
    m = memory.METRICS["corners"].prior_weight
    few = {"n_eff": 2.0, "w_own": 14.0, "w_opp": 18.0, "by_competition": {"7": 2}}   # 7 and 9 a match
    many = {"n_eff": 60.0, "w_own": 420.0, "w_opp": 540.0, "by_competition": {"7": 60}}  # the same 7 and 9, sixty times
    a = memory.figures(few, "corners", {"7": LEAGUE})
    b = memory.figures(many, "corners", {"7": LEAGUE})
    assert a["own_rate"] == b["own_rate"] == 7.0 and a["opp_rate"] == b["opp_rate"] == 9.0, "as they are"
    assert a["prior"] == 10.0 and a["prior_matches"] == 2
    assert a["own_shrunk"] == pytest.approx((14 + m * 10) / (2 + m), abs=1e-4) and a["opp_shrunk"] == pytest.approx((18 + m * 10) / (2 + m), abs=1e-4)
    assert b["own_shrunk"] == pytest.approx((420 + m * 10) / (60 + m), abs=1e-4)
    assert abs(a["own_shrunk"] - 10.0) < abs(a["own_rate"] - 10.0), "few matches: pulled toward the league"
    assert abs(b["own_shrunk"] - 7.0) < 0.3 < abs(a["own_shrunk"] - 7.0), "many: it stays near itself"


def test_a_team_that_played_in_two_leagues_is_shrunk_to_the_mean_of_both_weighted_by_its_matches() -> None:
    leagues = {"1": {"n_eff": 10.0, "w_total": 160.0}, "2": {"n_eff": 10.0, "w_total": 240.0}}  # 8 and 12 per team
    got = memory.figures({"n_eff": 4.0, "w_own": 36.0, "w_opp": 36.0, "by_competition": {"1": 3, "2": 1}}, "corners", leagues)
    assert got["prior"] == pytest.approx((3 * 8 + 1 * 12) / 4) == 9.0 and got["prior_matches"] == 4


def test_a_league_with_no_evidence_gives_no_ground_to_shrink_to_and_the_team_keeps_only_its_own_figure() -> None:
    got = memory.figures({"n_eff": 3.0, "w_own": 24.0, "w_opp": 21.0, "by_competition": {"9": 3}}, "cards", {})
    assert got == {"own_rate": 8.0, "opp_rate": 7.0}
    partly = memory.figures({"n_eff": 3.0, "w_own": 24.0, "w_opp": 21.0, "by_competition": {"9": 2, "7": 1}}, "cards", {"7": LEAGUE})
    assert partly["prior"] == 10.0 and partly["prior_matches"] == 1, "the matches of a league nobody has seen are not guessed"


def test_a_state_with_no_evidence_has_no_figures() -> None:
    assert memory.figures({"n_eff": 0.0}, "corners", {}) == {} and memory.figures({}, "xg", {}) == {}


# ── what a row rests on ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_decision_rows_name_their_decisions_and_the_post_mortems_that_judged_them_newest_first() -> None:
    assert memory.evidence_ref(("team", "1", "market:1X2"), [1, 5, 3, 5], [9, 8]) == {"decisions": [5, 3, 1], "postmortems": [9, 8]}
    assert memory.evidence_ref(("market", "OU", "decisions"), [2], []) == {"decisions": [2]}, "no post-mortem yet: none named"
    assert memory.evidence_ref(("competition", "9", "market:BTTS"), [4, 3], [7]) == {"decisions": [4, 3], "postmortems": [7]}


def test_every_other_row_names_its_matches() -> None:
    for key in (("team", "1", "corners"), ("competition", "9", "xg"), ("referee", "3", "discipline"), ("coach", "4", "profile"),
                ("player", "5", "availability")):
        assert memory.evidence_ref(key, [11, 30, 12], [99]) == {"fixtures": [30, 12, 11]}, key


def test_the_evidence_is_a_sample_of_at_most_the_sources_a_row_names() -> None:
    ids = list(range(1, memory.MAX_SOURCES + 25))
    named = memory.evidence_ref(("team", "1", "corners"), ids, [])["fixtures"]
    assert len(named) == memory.MAX_SOURCES and named[0] == ids[-1], "the newest first, the oldest dropped"


def test_a_row_rests_on_decisions_or_on_matches_never_on_both() -> None:
    assert memory.rests_on_decisions(("team", "1", "market:OU")) and memory.rests_on_decisions(("market", "1X2", "decisions"))
    assert not memory.rests_on_decisions(("team", "1", "cards")) and not memory.rests_on_decisions(("referee", "1", "discipline"))


def test_the_lineage_begins_on_the_day_the_plan_says() -> None:
    assert memory.VERSION == "memory-v4" and date(2026, 10, 13) == memory.LINEAGE_START
