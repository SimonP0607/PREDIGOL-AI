"""Memory with a confidence (plan F8, ``memory-v4``), without a database: how evidence ages, how much of it is enough, how the figures of a
team are shrunk toward its league's, and what a row says it rests on.

The queries and the lineage are tested on a real database in tests/integration/test_intel_memory_v4.py."""

from __future__ import annotations

import random
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
    spec = memory.TEAM_FIGURES["corners"]  # half-life 180 days, counts matches, keeps what the team produced (own) and conceded (opp)
    prev = {"n_eff": 4.0, "w_own": 40.0, "w_opp": 20.0}
    delta = {"matches": 1, "own": 9, "opp": 7}
    got = memory.weights(prev, DAY, delta, DAY + timedelta(days=180), spec)
    assert got == {"matches": pytest.approx(3.0), "own": pytest.approx(29.0), "opp": pytest.approx(17.0)}
    same_day = memory.weights(prev, DAY, delta, DAY, spec)
    assert same_day == {"matches": 5.0, "own": 49.0, "opp": 27.0}, "no gap, no ageing"


def test_the_first_row_of_an_entity_has_nothing_to_carry() -> None:
    assert memory.weights(None, None, {"matches": 2, "own": 11, "opp": 9}, DAY, memory.TEAM_FIGURES["xg"]) == {"matches": 2.0, "own": 11.0, "opp": 9.0}


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
    state, _ = memory.settle(prev, DAY, {"matches": 1, "own": 5, "opp": 5, "by_competition": {"7": 1}}, DAY, memory.TEAM_FIGURES["corners"])
    assert "own_shrunk" not in state and "prior" not in state and "own_rate" not in state
    assert state["matches"] == 4 and state["by_competition"] == {"7": 1}


@pytest.mark.parametrize(("key", "spec"), [
    (("team", "1", "market:OU"), memory.DECISIONS_TEAM), (("competition", "9", "market:1X2"), memory.DECISIONS_COMPETITION),
    (("market", "1X2", "decisions"), memory.DECISIONS_MARKET), (("referee", "3", "discipline"), memory.REFEREE),
    (("coach", "4", "profile"), memory.COACH), (("player", "5", "availability"), memory.PLAYER),
    (("team", "1", "corners"), memory.TEAM_FIGURES["corners"]), (("team", "1", "cards"), memory.TEAM_FIGURES["cards"]),
    (("team", "1", "xg"), memory.TEAM_FIGURES["xg"]),
    (("competition", "9", "corners"), memory.LEAGUE_FIGURES), (("competition", "9", "xg"), memory.LEAGUE_FIGURES),
])
def test_every_kind_of_row_the_memory_writes_has_its_convention(key: memory.EKey, spec: memory.Spec) -> None:
    assert memory.spec_for(key) is spec


def test_a_kind_nobody_wrote_has_none() -> None:
    assert memory.spec_for(("fixture", "1", "corners")) is None and memory.spec_for(("team", "1", "mystery")) is None
    assert memory.spec_for(("referee", "1", "corners")) is None, "a referee has no corners: the figures are the teams' and the leagues'"


def test_the_conventions_are_sane() -> None:
    for spec in (memory.DECISIONS_TEAM, memory.DECISIONS_COMPETITION, memory.DECISIONS_MARKET, memory.REFEREE, memory.COACH, memory.PLAYER,
                 *memory.TEAM_FIGURES.values(), memory.LEAGUE_FIGURES):
        assert spec.half_life > 0 and spec.k > 0 and spec.count
    assert all(memory.LEAGUE_FIGURES.k > team.k for team in memory.TEAM_FIGURES.values()), \
        "a league's mean needs more matches than a team's before it is trusted"
    assert set(memory.METRICS) == {"corners", "cards", "xg"} == set(memory.TEAM_FIGURES)
    assert all(m.prior_weight > 0 for m in memory.METRICS.values())


def conventions() -> dict[str, float]:
    """Every number of the memory that is a convention and not a count: half-life and k of each kind of row, and the weight of each league."""
    out: dict[str, float] = {}
    for name, spec in (("decisions of a team", memory.DECISIONS_TEAM), ("decisions of a competition", memory.DECISIONS_COMPETITION),
                       ("decisions of a market", memory.DECISIONS_MARKET), ("referee", memory.REFEREE), ("coach", memory.COACH),
                       ("player", memory.PLAYER), ("figures of a league", memory.LEAGUE_FIGURES)):
        out[f"{name}: half-life"], out[f"{name}: k"] = spec.half_life, spec.k
    for aspect, spec in memory.TEAM_FIGURES.items():
        out[f"{aspect} of a team: half-life"], out[f"{aspect} of a team: k"] = spec.half_life, spec.k
    for aspect, metric in memory.METRICS.items():
        out[f"{aspect}: matches a league's mean is worth"] = metric.prior_weight
    return out


FROZEN = {
    "memory-v4": {
        "decisions of a team: half-life": 90, "decisions of a team: k": 30,
        "decisions of a competition: half-life": 90, "decisions of a competition: k": 60,
        "decisions of a market: half-life": 180, "decisions of a market: k": 100,
        "referee: half-life": 365, "referee: k": 20, "coach: half-life": 365, "coach: k": 10, "player: half-life": 120, "player: k": 5,
        "figures of a league: half-life": 365, "figures of a league: k": 60,
        "corners of a team: half-life": 180, "corners of a team: k": 15, "cards of a team: half-life": 180, "cards of a team: k": 38,
        "xg of a team: half-life": 180, "xg of a team: k": 10,
        "corners: matches a league's mean is worth": 15, "cards: matches a league's mean is worth": 38, "xg: matches a league's mean is worth": 10,
    },
}


def test_a_convention_of_the_memory_changes_only_with_a_new_version_of_it() -> None:
    """The half-lives, the constants of confidence and the weights of the leagues are conventions: a row written with one and a row written
    with another are not comparable. Changing one means a version of the memory of its own and a rebuild, so this test names the numbers
    of every version: to change one, add the new version here and set ``memory.VERSION`` to it."""
    assert memory.VERSION in FROZEN, "a new version of the memory has to say which numbers it is built with"
    assert conventions() == FROZEN[memory.VERSION]


def test_the_weights_are_the_ones_measured_on_the_stored_matches_not_the_first_guess() -> None:
    """23 Oct 2026, ``scripts.memory priors`` over the last 365 days: 15.3 / 14.7, 37.0 / 38.5 and 7.9 / 11.4 (produced / conceded).
    The first draft guessed 6, 9 and 7; the measurement is what the memory is built on."""
    measured = {"corners": (14.7, 15.3), "cards": (37.0, 38.5), "xg": (7.9, 11.4)}
    for aspect, (low, high) in measured.items():
        weight = memory.METRICS[aspect].prior_weight
        assert low - 1 <= weight <= high + 1.5, (aspect, weight)


# ── how many matches a league's mean is worth ───────────────────────────────────────────────────────────────────────────


def simulate(rng: random.Random, *, competitions: int, teams: int, matches: int, within: float, between: float) -> dict[int, dict[int, list[float]]]:
    """Teams whose true mean differs from their competition's by ``between`` (standard deviation), each match off its team's mean by ``within``."""
    return {c: {t: [mean + rng.gauss(0, within) for _ in range(matches)]
                for t, mean in ((t, 5 + rng.gauss(0, between)) for t in range(teams))} for c in range(competitions)}


def test_the_variances_of_a_known_world_are_recovered_and_their_ratio_is_the_weight_of_the_league() -> None:
    world = simulate(random.Random(7), competitions=30, teams=18, matches=30, within=3.0, between=1.0)
    got = memory.variance_components(world)
    assert got is not None and (got.competitions, got.teams, got.matches) == (30, 30 * 18, 30 * 18 * 30)
    assert got.within == pytest.approx(9.0, rel=0.03) and got.between == pytest.approx(1.0, rel=0.1)
    assert got.prior_weight == pytest.approx(9.0, rel=0.1), "a match varies by 3 around its team, the teams by 1: the league's mean is worth about 9"


def test_teams_that_play_a_different_number_of_matches_are_weighed_by_the_matches_they_have() -> None:
    rng = random.Random(11)
    world = {c: {t: [m + rng.gauss(0, 2.0) for _ in range(rng.choice([6, 12, 40]))] for t, m in ((t, 4 + rng.gauss(0, 1.5)) for t in range(16))}
             for c in range(40)}
    got = memory.variance_components(world)
    assert got is not None
    assert got.within == pytest.approx(4.0, rel=0.05) and got.between == pytest.approx(2.25, rel=0.1)


def test_only_teams_and_competitions_with_enough_matches_count() -> None:
    world = {1: {t: [float(t + i % 2) for i in range(6)] for t in range(10)},     # ten teams with six matches: counts
             2: {t: [1.0, 2.0, 3.0] for t in range(30)},                             # thirty teams with three matches: none counts
             3: {t: [float(t)] * 9 for t in range(4)}}                               # a league of four: too few teams
    got = memory.variance_components(world)
    assert got is not None and (got.competitions, got.teams, got.matches) == (1, 10, 60)
    assert memory.variance_components(world, min_matches=7) is None, "nothing qualifies"
    assert memory.variance_components({}) is None


def test_teams_that_do_not_differ_have_no_weight_to_measure() -> None:
    rng = random.Random(3)
    world = {1: {t: [rng.gauss(5, 2) for _ in range(12)] for t in range(14)}}  # one population: whatever differs is chance
    got = memory.variance_components(world, min_matches=5, min_teams=8)
    assert got is not None and abs(got.between) < 0.1 * got.within, "whatever the teams differ by is chance: next to the noise of a match it is nothing"
    flat = {1: {t: [4.0, 6.0] * 4 for t in range(10)}}  # every team has exactly the same matches: no difference between them at all
    same = memory.variance_components(flat)
    assert same is not None and same.between <= 0 and same.prior_weight is None, "never a division by zero, never a made-up weight"


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
    many = {"n_eff": 300.0, "w_own": 2100.0, "w_opp": 2700.0, "by_competition": {"7": 300}}  # the same 7 and 9, three hundred times
    a = memory.figures(few, "corners", {"7": LEAGUE})
    b = memory.figures(many, "corners", {"7": LEAGUE})
    assert a["own_rate"] == b["own_rate"] == 7.0 and a["opp_rate"] == b["opp_rate"] == 9.0, "as they are"
    assert a["prior"] == 10.0 and a["prior_matches"] == 2
    assert a["own_shrunk"] == pytest.approx((14 + m * 10) / (2 + m), abs=1e-4) and a["opp_shrunk"] == pytest.approx((18 + m * 10) / (2 + m), abs=1e-4)
    assert b["own_shrunk"] == pytest.approx((2100 + m * 10) / (300 + m), abs=1e-4)
    assert abs(a["own_shrunk"] - 10.0) < abs(a["own_rate"] - 10.0), "few matches: pulled toward the league"
    assert abs(b["own_shrunk"] - 7.0) < 0.3 < abs(a["own_shrunk"] - 7.0), "many: it stays near itself"


def test_a_team_that_played_in_two_leagues_is_shrunk_to_the_mean_of_both_weighted_by_its_matches() -> None:
    leagues = {"1": {"n_eff": 10.0, "w_total": 160.0}, "2": {"n_eff": 10.0, "w_total": 240.0}}  # 8 and 12 per team
    got = memory.figures({"n_eff": 4.0, "w_own": 36.0, "w_opp": 36.0, "by_competition": {"1": 3, "2": 1}}, "corners", leagues)
    assert got["prior"] == pytest.approx((3 * 8 + 1 * 12) / 4) == 9.0 and got["prior_matches"] == 4


@pytest.mark.parametrize("aspect", ["corners", "cards", "xg"])
def test_the_confidence_of_a_figure_is_the_share_of_it_that_is_the_team_itself_and_the_rest_is_its_league(aspect: str) -> None:
    """Why the constant of the confidence of these rows is the weight of the league: a row that says 38 % is 38 % the team and 62 % its
    league, whatever the age of its matches."""
    spec = memory.spec_for(("team", "1", aspect))
    assert spec is not None and spec.k == memory.METRICS[aspect].prior_weight
    state: dict[str, object] = {}
    previous: date | None = None
    confidence: float | None = None
    for day in (DAY - timedelta(days=200), DAY - timedelta(days=60), DAY):  # three matches a time, the oldest has lost part of its weight
        state, confidence = memory.settle(state or None, previous, {"matches": 3, "own": 3 * 6.0, "opp": 3 * 5.0, "by_competition": {"7": 3}}, day, spec)
        previous = day
    assert confidence is not None and 0 < confidence < 1 and state["matches"] == 9
    got = memory.figures(state, aspect, {"7": {"n_eff": 80.0, "w_total": 80 * 2 * 4.0}})  # a league of 4 a team
    assert got["prior"] == 4.0 and got["own_rate"] == pytest.approx(6.0, abs=1e-3)
    for side, rate in (("own_shrunk", "own_rate"), ("opp_shrunk", "opp_rate")):
        assert got[side] == pytest.approx(confidence * got[rate] + (1 - confidence) * got["prior"], abs=2e-3), side


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
