"""Plan F11 - the dependence between the families inside one match: the arithmetic by hand, the strata that keep the level of a competition out of
it, the resampling that draws competition-days, and what the verdicts say."""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from fbi.families import dependence, history
from fbi.families.dependence import AWAY_MORE, BTTS, EVENTS, HOME_MORE, OVER, PAIRS, Event, Row
from fbi.families.fit import Match

BASE = datetime(2026, 1, 5, 18, 0, tzinfo=UTC)
A, B = "goals.over_2_5", "corners.over_9_5"
PAIR = {(EVENTS[i].key, EVENTS[j].key): p for p, (i, j) in enumerate(PAIRS)}


def match_row(fixture_id: int, competition: int, day: int, a: bool, b: bool, cards: tuple[int, int] = (2, 2)) -> Row:
    """A match where "goals over 2.5" is ``a`` and "corners over 9.5" is ``b`` (the cards are the same in all of them unless said)."""
    return Row(fixture_id, competition, BASE + timedelta(days=day), (2, 1) if a else (1, 0), (5, 5) if b else (4, 5), cards)


def table(competition: int, first_id: int, both: int, first_only: int, second_only: int, neither: int) -> list[Row]:
    """A competition-half-year whose matches fall in the four cells of (goals over 2.5, corners over 9.5), each match on a day of its own."""
    rows: list[Row] = []
    fixture_id, day = first_id, 0
    for count, a, b in ((both, True, True), (first_only, True, False), (second_only, False, True), (neither, False, False)):
        for _ in range(count):
            rows.append(match_row(fixture_id, competition, day, a, b))
            fixture_id += 1
            day += 1
    return rows


def reading(rows: list[Row], **kwargs: Any) -> dependence.Reading:
    return dependence.read_totals(dependence.totals(dependence.design(rows, **kwargs)))


def test_the_events_are_the_questions_a_leg_asks_and_the_pairs_cross_the_families() -> None:
    assert [e.key for e in EVENTS] == [
        "goals.over_1_5", "goals.over_2_5", "goals.over_3_5", "goals.btts", "goals.home_more", "goals.away_more",
        "corners.over_8_5", "corners.over_9_5", "corners.over_10_5", "corners.over_11_5", "corners.home_more", "corners.away_more",
        "cards.over_3_5", "cards.over_4_5", "cards.over_5_5", "cards.home_more", "cards.away_more"]
    assert len(PAIRS) == 6 * 6 + 6 * 5 + 6 * 5 == 96
    assert all(EVENTS[i].family != EVENTS[j].family and i < j for i, j in PAIRS)
    assert len(set(dependence.COLUMNS)) == len(dependence.COLUMNS) == len(EVENTS) + len(dependence.VARIABLES)
    assert all(a in dependence.VARIABLES and b in dependence.VARIABLES for a, b in dependence.CORRELATIONS)
    assert {Event("goals", HOME_MORE).text, Event("corners", HOME_MORE).text} == {"home win", "home side has more corners"}
    assert Event("cards", OVER, 4.5).text == "cards over 4.5" and Event("goals", BTTS).text == "both teams score"


def test_an_event_is_a_strict_question_about_the_two_counts() -> None:
    home, away = np.array([2, 1, 0, 3, 0, 1], dtype=np.int64), np.array([1, 1, 0, 0, 2, 2], dtype=np.int64)
    assert Event("goals", OVER, 2.5).holds(home, away).tolist() == [True, False, False, True, False, True], "a total of 3 is over 2.5; 2 is not"
    assert Event("goals", OVER, 3.5).holds(home, away).tolist() == [False, False, False, False, False, False]
    assert Event("goals", OVER, 3.0).holds(home, away).tolist() == [False, False, False, False, False, False], "exactly on the line is not over it"
    assert Event("goals", BTTS).holds(home, away).tolist() == [True, True, False, False, False, True], "both teams have at least one"
    assert Event("corners", HOME_MORE).holds(home, away).tolist() == [True, False, False, True, False, False], "a tie is nobody's"
    assert Event("cards", AWAY_MORE).holds(home, away).tolist() == [False, False, False, False, True, True]


def test_the_lines_and_the_measures_are_those_of_the_families_and_the_bar_is_the_one_of_the_parlays() -> None:
    from scripts import families as cli

    from fbi.intel import decision

    assert dependence.LINES["corners"] == cli.DEFAULT_LINES["corners_ft"] and dependence.LINES["cards"] == cli.DEFAULT_LINES["cards_lines_ft"]
    assert dependence.BAR == decision.PARLAY_MIN_EV and dependence.TOLERANCE == dependence.BAR, "a parlay has to show 2 %; a dependence that big erases it"
    for measure in dependence.MEASURES.values():
        history.columns_of(measure)  # a count that grades the bets of a family, or this raises
    assert dependence.MEASURES == {"goals": "goals_ft", "corners": "corners_ft", "cards": "cards_lines_ft"}


def test_the_four_combinations_of_one_stratum_by_hand() -> None:
    """40 matches: 12 with both, 8 with only the first, 8 with only the second, 12 with neither. Each event has 20, so each combination is expected
    10 times: the lifts are 12/10, 8/10, 8/10, 12/10 and phi is (12 x 12 - 8 x 8) / (20 x 20) = 0.2."""
    r = reading(table(1, 1, 12, 8, 8, 12))
    p = PAIR[(A, B)]
    assert r.observed[p].tolist() == [12, 8, 8, 12] and r.expected[p].tolist() == [10, 10, 10, 10]
    assert r.lift[p].tolist() == pytest.approx([1.2, 0.8, 0.8, 1.2])
    assert r.phi[p] == pytest.approx(0.2)
    assert r.observed[p].sum() == r.expected[p].sum() == 40, "the four combinations are all the matches, observed or expected"


def test_two_strata_are_added_up_not_pooled() -> None:
    """The second stratum is independent (20 and 10 of 40, 5 together) and the first is not. Observed together 12 + 5 = 17 against 10 + 5 = 15
    expected; with only the first event 8 + 15 = 23 against 10 + 15 = 25; with only the second 8 + 5 = 13 against 10 + 5 = 15; with neither
    12 + 15 = 27 against 10 + 15 = 25. phi is the covariance within strata, 17 - 15 = 2, over the root of the variances within strata, 10 + 10
    and 10 + 7.5."""
    r = reading(table(1, 1, 12, 8, 8, 12) + table(2, 101, 5, 15, 5, 15))
    p = PAIR[(A, B)]
    assert r.observed[p].tolist() == [17, 23, 13, 27] and r.expected[p].tolist() == [15, 25, 15, 25]
    assert r.lift[p].tolist() == pytest.approx([17 / 15, 23 / 25, 13 / 15, 27 / 25])
    assert r.phi[p] == pytest.approx(2 / np.sqrt(20 * 17.5))


def test_the_level_of_a_competition_is_not_a_dependence_between_families() -> None:
    """Within each competition the two events are independent (10 of 40 matches have both where 20 x 20 / 40 = 10 are expected; 2 where 8 x 10 / 40 =
    2): the lift is exactly 1 and phi 0. Pooled as if the strata were one competition, the same matches read as a dependence (12 against
    28 x 30 / 80 = 10.5): that is the difference between a league that has everything often and one that has everything rarely."""
    rows = table(1, 1, 10, 10, 10, 10) + table(2, 101, 2, 6, 8, 24)
    d = dependence.design(rows)
    p = PAIR[(A, B)]
    inside = dependence.read_totals(dependence.totals(d))
    assert inside.lift[p].tolist() == pytest.approx([1.0, 1.0, 1.0, 1.0]) and inside.phi[p] == pytest.approx(0.0, abs=1e-12)
    observed, expected = dependence.cells(dependence.totals(d, pooled=True))
    assert observed[p, 0] == 12 and expected[p, 0] == pytest.approx(10.5)
    assert observed[p, 0] / expected[p, 0] == pytest.approx(12 / 10.5)


def sample_rows(seed: int = 1, strata: int = 4, size: int = 14) -> list[Row]:
    """Matches with counts of every kind, several on the same day, in several competitions and both halves of a year."""
    rng = np.random.default_rng(seed)
    rows: list[Row] = []
    fixture_id = 0
    for s in range(strata):
        competition, half = 1 + s // 2, s % 2
        for _ in range(size):
            fixture_id += 1
            day = int(rng.integers(0, 40)) + 181 * half
            rows.append(Row(fixture_id, competition, BASE + timedelta(days=day), (int(rng.poisson(1.5)), int(rng.poisson(1.2))),
                            (int(rng.poisson(5)), int(rng.poisson(4.5))), (int(rng.poisson(2)), int(rng.poisson(2.3)))))
    return rows


def test_a_match_taken_twice_counts_twice_and_one_taken_never_does_not_count() -> None:
    """The weights of a resample are the number of times each match is taken: the sums with those weights are the sums of the matches written out."""
    rows = sample_rows()
    d = dependence.design(rows, min_stratum=1)
    ordered = sorted(rows, key=lambda r: (dependence.stratum_of(r), dependence.day_of(r), r.fixture_id))
    weights = np.random.default_rng(3).integers(0, 4, d.matches).astype(np.float64)
    weights[d.starts] = np.maximum(weights[d.starts], 1.0)  # every stratum keeps at least one match, as a resample does
    written_out = [r for r, w in zip(ordered, weights, strict=True) for _ in range(int(w))]
    weighted, copied = dependence.totals(d, weights), dependence.totals(dependence.design(written_out, min_stratum=1))
    assert weighted.n == copied.n == weights.sum()
    np.testing.assert_allclose(weighted.t, copied.t)
    np.testing.assert_allclose(weighted.g, copied.g)
    np.testing.assert_allclose(weighted.h, copied.h)
    assert d.strata == 4 and (weights == 0).any() and (weights > 1).any(), "the example has matches taken never and more than once"


def test_the_correlation_is_the_one_inside_the_strata() -> None:
    rows = sample_rows(seed=2, strata=4, size=40)
    d = dependence.design(rows)
    matrix = dependence.correlation_matrix(dependence.totals(d))
    z, bounds = d.z, [*d.starts.tolist(), d.matches]
    centred = np.vstack([z[a:b] - z[a:b].mean(axis=0) for a, b in itertools.pairwise(bounds)])
    first = len(EVENTS)
    for x in range(first, z.shape[1]):
        for y in range(first, z.shape[1]):
            by_hand = float((centred[:, x] * centred[:, y]).sum() / np.sqrt((centred[:, x] ** 2).sum() * (centred[:, y] ** 2).sum()))
            assert matrix[x, y] == pytest.approx(by_hand, abs=1e-12), (dependence.COLUMNS[x], dependence.COLUMNS[y])
    assert np.allclose(np.diag(matrix)[first:], 1.0)


def test_a_stratum_that_is_too_small_is_left_out_and_said() -> None:
    rows = table(1, 1, 12, 8, 8, 12) + table(2, 101, 3, 2, 2, 3)
    d = dependence.design(rows)
    assert (d.matches, d.strata, d.dropped) == (40, 1, 10)
    d = dependence.design(rows, min_stratum=10)
    assert (d.matches, d.strata, d.dropped) == (50, 2, 0)
    assert dependence.design([], min_stratum=1).matches == 0


def test_the_days_of_a_competition_are_the_unit_that_is_drawn_inside_its_stratum() -> None:
    """Stratum 1 (competition 1, first half): days 1, 2 (two matches), 3. Stratum 2 (competition 1, second half): days 1, 2. Stratum 3
    (competition 2): one day."""
    h2 = 200
    rows = [
        Row(1, 1, BASE + timedelta(days=1), (1, 1), (5, 5), (2, 2)), Row(2, 1, BASE + timedelta(days=2), (1, 1), (5, 5), (2, 2)),
        Row(3, 1, BASE + timedelta(days=2), (1, 1), (5, 5), (2, 2)), Row(4, 1, BASE + timedelta(days=3), (1, 1), (5, 5), (2, 2)),
        Row(5, 1, BASE + timedelta(days=h2 + 1), (1, 1), (5, 5), (2, 2)), Row(6, 1, BASE + timedelta(days=h2 + 2), (1, 1), (5, 5), (2, 2)),
        Row(7, 2, BASE + timedelta(days=1), (1, 1), (5, 5), (2, 2))]
    d = dependence.design(rows, min_stratum=1)
    assert d.starts.tolist() == [0, 4, 6] and d.strata == 3 and d.clusters == 6
    assert d.cluster.tolist() == [0, 1, 1, 2, 3, 4, 5], "the two matches of one day are one unit"
    assert d.first.tolist() == [0, 0, 0, 3, 3, 5] and d.span.tolist() == [3, 3, 3, 2, 2, 1]
    for seed in range(25):
        taken = dependence.draw_clusters(d, np.random.default_rng(seed))
        assert taken[:3].sum() == 3 and taken[3:5].sum() == 2 and taken[5] == 1, "each stratum draws as many days as it has, among its own"
        assert (taken == np.floor(taken)).all()
        assert dependence.draw(d, np.random.default_rng(seed)).tolist() == [taken[c] for c in d.cluster]


def test_the_matches_are_joined_by_fixture_and_only_those_with_the_three_counts_stay() -> None:
    def m(fixture_id: int, home: int, away: int, day: int = 0) -> Match:
        return Match(fixture_id, BASE + timedelta(days=day), 10, 20, home, away)

    histories = {"goals": {1: [m(1, 2, 1), m(2, 0, 0), m(3, 1, 1, 5)], 2: [m(4, 3, 0)]},
                 "corners": {1: [m(1, 6, 4), m(3, 5, 5, 5)], 2: [m(4, 7, 3), m(9, 1, 1)]},
                 "cards": {1: [m(1, 2, 3), m(2, 1, 1), m(3, 0, 1, 5)], 2: [m(4, 1, 0), m(8, 2, 2)]}}
    rows, coverage = dependence.join(histories)
    assert coverage == {"goals": 4, "corners": 4, "cards": 5, "joined": 3}
    assert [(r.fixture_id, r.competition_id, r.goals, r.corners, r.cards) for r in rows] == [
        (1, 1, (2, 1), (6, 4), (2, 3)), (3, 1, (1, 1), (5, 5), (0, 1)), (4, 2, (3, 0), (7, 3), (1, 0))]
    later, coverage = dependence.join(histories, since=BASE + timedelta(days=1))
    assert [r.fixture_id for r in later] == [3] and coverage["joined"] == 1 and coverage["goals"] == 4


def test_the_history_is_read_through_the_door_of_the_families(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, datetime, datetime]] = []

    def load(conn: Any, measure: str, *, since: datetime, cutoff: datetime, **kwargs: Any) -> dict[int, list[Match]]:
        assert conn == "connection" and not kwargs, "nothing is asked of the door but the window: neutral venue and referee stay off"
        asked.append((measure, since, cutoff))
        return {}

    monkeypatch.setattr(history, "load", load)
    got = dependence.read("connection", since=BASE, cutoff=BASE + timedelta(days=9))  # type: ignore[arg-type]
    assert got == {"goals": {}, "corners": {}, "cards": {}}
    assert asked == [("goals_ft", BASE, BASE + timedelta(days=9)), ("corners_ft", BASE, BASE + timedelta(days=9)),
                     ("cards_lines_ft", BASE, BASE + timedelta(days=9))]


def test_the_status_of_a_combination_is_equivalence_or_a_clear_miss_or_neither() -> None:
    t = dependence.TOLERANCE
    inside, outside_low, outside_high = 1.0 - t, 1.0 - t - 1e-9, 1.0 + t + 1e-9
    assert dependence.cell_status(1.0, 1.0 - t, 1.0 + t) == dependence.NEGLIGIBLE, "the whole interval inside, the ends included"
    assert dependence.cell_status(1.0, outside_low, 1.0) == dependence.BORDERLINE, "an interval that leaves the tolerance but does not clear it"
    assert dependence.cell_status(0.9, 0.85, inside - 1e-9) == dependence.TOO_HIGH, "even the top of the interval is below: the product overstates"
    assert dependence.cell_status(0.9, 0.85, inside) == dependence.BORDERLINE, "the top just reaches the tolerance"
    assert dependence.cell_status(1.1, outside_high, 1.2) == dependence.TOO_LOW, "even the bottom is above: the product understates"
    assert dependence.cell_status(1.1, 1.0 + t, 1.2) == dependence.BORDERLINE
    assert dependence.cell_status(None, 0.9, 1.1) == dependence.BORDERLINE == dependence.cell_status(1.0, None, 1.1)
    assert dependence.cell_status(1.05, 1.01, 1.09, tolerance=0.1) == dependence.NEGLIGIBLE, "the tolerance can be moved"


def test_a_pair_is_as_bad_as_its_worst_combination() -> None:
    n, b, hi, lo = dependence.NEGLIGIBLE, dependence.BORDERLINE, dependence.TOO_HIGH, dependence.TOO_LOW
    assert dependence.pair_verdict([n, n, n, n]) == dependence.NEGLIGIBLE
    assert dependence.pair_verdict([n, n, b, n]) == dependence.BORDERLINE
    assert dependence.pair_verdict([n, b, hi, n]) == dependence.MATERIAL, "one combination off for sure is enough"
    assert dependence.pair_verdict([lo, n, n, n]) == dependence.MATERIAL
    assert set(dependence.PAIR_WORDS) == {dependence.NEGLIGIBLE, dependence.BORDERLINE, dependence.MATERIAL}
    assert set(dependence.CELL_WORDS) == {n, b, hi, lo}


def test_what_a_parlay_at_the_bar_is_really_worth() -> None:
    assert dependence.worth_at_the_bar(1.0) == pytest.approx(0.02), "independent: it is worth what the product says"
    assert dependence.worth_at_the_bar(0.95) == pytest.approx(1.02 * 0.95 - 1.0) and dependence.worth_at_the_bar(0.95) < 0.0
    assert dependence.worth_at_the_bar(1 / 1.02) == pytest.approx(0.0), "a lift of 0.98 leaves nothing of the 2 %"


def synthetic(*, dependent: bool, seed: int, levels: tuple[float, ...] = (0.6, 1.0, 1.6), size: int = 600) -> list[Row]:
    """Three competitions that differ in how much happens in all of them (the level multiplies every count), and a latent dominance ``u`` that,
    when ``dependent``, gives the home side more goals and corners and fewer cards, and the away side the opposite."""
    rng = np.random.default_rng(seed)
    rows: list[Row] = []
    fixture_id = 0
    for competition, level in enumerate(levels, start=1):
        for k in range(size):
            fixture_id += 1
            u = float(rng.normal()) if dependent else 0.0
            goals = (int(rng.poisson(1.4 * level * np.exp(0.25 * u))), int(rng.poisson(1.1 * level * np.exp(-0.25 * u))))
            corners = (int(rng.poisson(5.2 * level * np.exp(0.2 * u))), int(rng.poisson(4.4 * level * np.exp(-0.2 * u))))
            cards = (int(rng.poisson(2.0 * level * np.exp(-0.2 * u))), int(rng.poisson(2.3 * level * np.exp(0.2 * u))))
            rows.append(Row(fixture_id, competition, BASE + timedelta(days=k % 170, hours=k % 5), goals, corners, cards))
    return rows


def by_name(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(p["first"], p["second"]): p for p in report["pairs"]}


def test_a_dominant_side_is_found_in_who_has_more_and_not_in_the_totals() -> None:
    report = dependence.measure(synthetic(dependent=True, seed=4), replicates=60)
    corr = {(c["a"], c["b"]): c for c in report["correlations"]}
    diff = corr[("corners_diff", "cards_diff")]
    assert diff["high"] < -0.1 and diff["low"] < diff["r"] < diff["high"], "more corners for a side, fewer cards: a clear negative correlation"
    assert corr[("goals_diff", "corners_diff")]["low"] > 0.05 and corr[("goals_diff", "cards_diff")]["high"] < -0.05
    pair = by_name(report)[("corners.home_more", "cards.home_more")]
    assert pair["phi"] < -0.05 and pair["phi_high"] < 0.0 and pair["verdict"] == dependence.MATERIAL
    both = pair["cells"]["both"]
    assert both["lift"] < 0.9 and both["high"] < 1.0 - dependence.TOLERANCE and both["status"] == dependence.TOO_HIGH
    assert both["worth_at_the_bar"] == pytest.approx(1.02 * both["lift"] - 1.0) and both["worth_at_the_bar"] < -0.08
    only = pair["cells"]["first_only"]
    assert only["lift"] > 1.0 and only["status"] == dependence.TOO_LOW, "the combination that went the other way is more frequent than the product says"


def test_without_a_dominant_side_the_families_do_not_depend_even_though_the_competitions_differ() -> None:
    """Independent given the competition: the totals of the three families still go up and down together BETWEEN the competitions (a league that
    has more of everything), and that is not a dependence between the families of a match."""
    report = dependence.measure(synthetic(dependent=False, seed=6, size=2000), replicates=60)
    for c in report["correlations"]:
        assert abs(c["r"]) < 0.05 and c["low"] <= c["r"] <= c["high"] and c["high"] - c["low"] < 0.1, (c["a"], c["b"], "within a stratum: nothing a match has")
    totals_ = {(c["a"], c["b"]): c for c in report["correlations"]}
    assert totals_[("goals_total", "corners_total")]["pooled"] > 0.2, "pooled, the level of the competition reads as a dependence"
    assert totals_[("corners_total", "cards_total")]["pooled"] > 0.2 and abs(totals_[("corners_total", "cards_total")]["r"]) < 0.05
    assert report["summary"][dependence.MATERIAL] <= 2, "96 pairs are judged at once: one or two may be called by chance, not a quarter of them"
    assert all(abs(p["phi"]) < 0.05 for p in report["pairs"])


def test_the_report_is_complete_ready_for_json_and_the_same_every_time() -> None:
    rows = synthetic(dependent=True, seed=8, size=300)
    report = dependence.measure(rows, replicates=30, coverage={"goals": 900, "corners": 900, "cards": 900, "joined": 900})
    json.dumps(report, allow_nan=False)
    assert report["version"] == "dependence-v1" and len(report["pairs"]) == 96 and len(report["correlations"]) == 6
    s = report["summary"]
    assert s["pairs"] == 96 and s[dependence.NEGLIGIBLE] + s[dependence.BORDERLINE] + s[dependence.MATERIAL] == 96
    assert set(report["events"]) == {e.key for e in EVENTS} and all(0.0 < v["rate"] < 1.0 for v in report["events"].values())
    for event in EVENTS:
        counts = [getattr(r, event.family) for r in rows]
        seen = event.holds(np.array([c[0] for c in counts], dtype=np.int64), np.array([c[1] for c in counts], dtype=np.int64))
        assert report["events"][event.key]["rate"] == pytest.approx(float(seen.mean())), f"{event.key}: the rate is the share of the matches in which it happened"
    assert report["data"]["matches"] == 900 and report["data"]["dropped"] == 0 and report["data"]["strata"] == 3 and report["data"]["coverage"]["joined"] == 900
    c = report["criterion"]
    assert (c["tolerance"], c["bar"], c["level"], c["replicates"], c["seed"], c["min_stratum"]) == (0.02, 0.02, 0.95, 30, 11, 30)
    for p in report["pairs"]:
        assert set(p["cells"]) == set(dependence.CELLS)
        assert sum(x["observed"] for x in p["cells"].values()) == pytest.approx(900) == sum(x["expected"] for x in p["cells"].values())
        assert dependence.pair_verdict(x["status"] for x in p["cells"].values()) == p["verdict"]
    assert dependence.measure(rows, replicates=30) == {**report, "data": {**report["data"], "coverage": {}}}, "a fixed seed: the same history, the same numbers"
    other = dependence.measure(rows, replicates=30, seed=12)
    first, second = report["pairs"][0]["cells"]["both"], other["pairs"][0]["cells"]["both"]
    assert first["lift"] == second["lift"] and (first["low"], first["high"]) != (second["low"], second["high"]), "the seed moves the intervals, not the estimates"


def test_the_level_of_the_interval_is_the_one_asked_for() -> None:
    """The same resamples read at 80 % give narrower intervals than at 95 %, inside them, and say the level they were read at."""
    rows = synthetic(dependent=True, seed=8, size=300)
    wide, narrow = dependence.measure(rows, replicates=60), dependence.measure(rows, replicates=60, level=0.80)
    assert wide["criterion"]["level"] == 0.95 and narrow["criterion"]["level"] == 0.80
    for a, b in zip(intervals_of(wide)["lift"], intervals_of(narrow)["lift"], strict=True):
        assert a[0] == b[0], "the estimate does not depend on the level"
        assert a[1] <= b[1] <= b[0] <= b[2] <= a[2], "the 80 % interval sits inside the 95 % one and holds the estimate"
    widths = [(a[2] - a[1], b[2] - b[1]) for a, b in zip(intervals_of(wide)["phi"], intervals_of(narrow)["phi"], strict=True)]
    assert all(b < a for a, b in widths) and 0.6 < sum(b for _, b in widths) / sum(a for a, _ in widths) < 0.8, "1.28 / 1.96 of the width, about"


def test_a_history_that_is_too_short_measures_nothing_and_says_so() -> None:
    report = dependence.measure(table(1, 1, 12, 8, 8, 12))
    assert report["pairs"] == [] and report["correlations"] == [] and report["summary"]["pairs"] == 0
    text = dependence.render(report)
    assert "40 matches" in text and "at least 300 matches in two strata are needed" in text
    json.dumps(report, allow_nan=False)
    assert dependence.measure([])["data"]["matches"] == 0


def test_the_text_names_the_data_the_correlations_the_tally_and_the_pairs_that_depend_most() -> None:
    report = dependence.measure(synthetic(dependent=True, seed=4), replicates=40, coverage={"goals": 2000, "corners": 1900, "cards": 1850, "joined": 1800})
    text = dependence.render(report, top=2)
    s = report["summary"]
    assert "dependence-v1" in text and "1800 matches with the goals, the corners and the cards known" in text and "2000 had goals, 1900 corners, 1850 cards" in text
    assert "in 3 strata (a competition in a half-year, UTC; 0 matches left out in strata of fewer than 30)" in text
    assert "40 resamples of the" in text and "competition-days, seed 11" in text and "intervals 95 %" in text
    assert "corners_diff   ~ cards_diff" in text and "(pooled " in text
    assert f"{s['pairs']} pairs of events of two families" in text and f"{s[dependence.MATERIAL]} material (some combination off by more than 2 %)" in text
    assert text.count("-> ") == 2, "two pairs were asked for"
    top = max(report["pairs"], key=lambda p: abs(p["phi"]))
    assert report["events"][top["first"]]["text"] in text and report["events"][top["second"]]["text"] in text
    assert "the product overstates it" in text and "the product understates it" in text and "%)" in text
    assert text.count("\n        ") == 8, "four combinations under each of the two pairs"


def intervals_of(report: dict[str, Any]) -> dict[str, list[tuple[float, float, float]]]:
    """Every figure of a report that has an interval, as (estimate, low, high): the phi of the pairs, the lifts of their combinations, the correlations."""
    pairs = report["pairs"]
    return {"phi": [(p["phi"], p["phi_low"], p["phi_high"]) for p in pairs],
            "lift": [(c["lift"], c["low"], c["high"]) for p in pairs for c in (p["cells"][name] for name in dependence.CELLS)],
            "correlation": [(c["r"], c["low"], c["high"]) for c in report["correlations"]]}


def test_the_intervals_are_calibrated_on_matches_with_no_dependence() -> None:
    """The guide says the resamples estimate the real error and the 95 % intervals hold the truth almost always when they should. Forty simulated
    histories in which the families do NOT depend on each other (the competitions differ in level, which is not a dependence): the true phi and
    correlation are 0 and the true lifts 1. For each kind of figure the error that the resamples estimate (half the width of the interval over
    1.96) is within a fifth of the real spread of the estimate across the histories, and the interval holds the truth between 88 and 99.5 % of the
    time. An interval half as wide, or twice as wide, would fail one of the two."""
    truth = {"phi": 0.0, "lift": 1.0, "correlation": 0.0}
    runs = [intervals_of(dependence.measure(synthetic(dependent=False, seed=900 + k, size=400), replicates=100)) for k in range(40)]
    for name, value in truth.items():
        found = np.array([run[name] for run in runs])
        estimate, low, high = found[..., 0], found[..., 1], found[..., 2]
        real = estimate.std(axis=0, ddof=1)
        ratio = float(np.nanmedian(((high - low) / (2 * 1.96)).mean(axis=0) / real))
        coverage = float(np.mean((low <= value) & (value <= high)))
        assert 0.8 <= ratio <= 1.25, f"{name}: the resamples estimate {ratio:.2f} times the real error"
        assert 0.88 <= coverage <= 0.995, f"{name}: the intervals hold the truth {coverage:.3f} of the times"
        assert abs(float(estimate.mean()) - value) < 0.01, f"{name}: the estimates are not centred on the truth"


def shared_days(seed: int, day_effect: float, *, competitions: int = 3, days: int = 60, per_day: tuple[int, int] = (6, 12)) -> list[Row]:
    """Matches whose three counts, on both sides, rise and fall together with the day of their competition (the weather, the weekend, the same
    referees) as much as ``day_effect`` says, and are independent of each other otherwise."""
    rng = np.random.default_rng(seed)
    rows: list[Row] = []
    fixture_id = 0
    for competition, level in enumerate((0.7, 1.0, 1.5)[:competitions], start=1):
        for day in range(days):
            factor = float(np.exp(rng.normal(0.0, day_effect))) if day_effect else 1.0
            for k in range(int(rng.integers(*per_day))):
                fixture_id += 1
                goals = (int(rng.poisson(1.4 * level * factor)), int(rng.poisson(1.1 * level * factor)))
                corners = (int(rng.poisson(5.2 * level * factor)), int(rng.poisson(4.4 * level * factor)))
                cards = (int(rng.poisson(2.0 * level * factor)), int(rng.poisson(2.3 * level * factor)))
                rows.append(Row(fixture_id, competition, BASE + timedelta(days=3 * day, hours=k), goals, corners, cards))
    return rows


def one_cluster_per_match(d: dependence.Design) -> dependence.Design:
    """The same design with every match drawn on its own, as if the matches of a day had nothing in common."""
    n = d.matches
    sizes = np.diff(np.append(d.starts, n))
    stratum = np.repeat(np.arange(d.starts.size), sizes)
    return replace(d, cluster=np.arange(n, dtype=np.intp), first=d.starts[stratum].astype(np.intp), span=sizes[stratum].astype(np.intp))


def spread_of(resamples: list[dependence.Reading]) -> Any:
    """How much each phi and each correlation moves across the resamples."""
    return np.nanstd(np.stack([np.concatenate([r.phi, r.correlation]) for r in resamples]), axis=0, ddof=1)


def test_resampling_whole_days_widens_the_intervals_when_the_days_share_something_and_changes_nothing_when_they_do_not() -> None:
    """The unit that is drawn is the competition-day. Where every match of a day moves with the day, drawing matches one by one would understate the
    error; drawing days does not. Where the days have nothing in common the two are the same. (Twelve histories each; the median over the
    figures of how much wider the intervals are drawing days than drawing matches.)"""
    mean_ratio: dict[float, float] = {}
    least: dict[float, float] = {}
    for day_effect in (0.0, 0.6):
        ratios: list[float] = []
        for k in range(12):
            d = dependence.design(shared_days(700 + k, day_effect))
            by_day = spread_of(dependence.bootstrap(d, replicates=80, seed=k))
            by_match = spread_of(dependence.bootstrap(one_cluster_per_match(d), replicates=80, seed=k))
            ratios.append(float(np.nanmedian(by_day / by_match)))
        mean_ratio[day_effect], least[day_effect] = float(np.mean(ratios)), min(ratios)
    assert 0.97 <= mean_ratio[0.0] <= 1.03, "days with nothing in common: drawing days or matches is the same"
    assert mean_ratio[0.6] >= 1.05 and least[0.6] >= 1.03, "days that move together: the intervals have to be wider, in every history"
