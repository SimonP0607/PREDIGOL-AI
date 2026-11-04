"""Plan F12.6 - the search for patterns: what each piece does (worked by hand), that the standard error is the one that counts a match once, that a world
with no pattern in it gives the findings chance says and no more, that a planted pattern is found and one that does not repeat is not proposed, and what
the hypotheses say.

The database half (the rows of the decisions, the groups of each, the proposals written) is in ``tests/integration/test_pattern_search.py``."""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest
from scipy import stats

from fbi.families.versus import loss
from fbi.research import pattern_search as ps
from fbi.research.pattern_search import Obs

T0 = datetime(2035, 3, 1, 12, tzinfo=UTC)
D = Decimal


def row(fixture: int, day: float = 0.0, *, p: float = 0.5, won: int | None = 1, p_close: float | None = 0.5, clv: float | None = None,
        lead: float | None = None, **tags: tuple[str, ...]) -> Obs:
    return Obs(fixture, T0 + timedelta(days=day), p, won, p_close, clv, tags, lead)


def reference(xs: Sequence[float], clusters: Sequence[int], member: Sequence[bool]) -> tuple[float, float]:
    """The difference and its clustered standard error, written the long way: one dictionary of sums per match."""
    n1 = sum(member)
    n0 = len(xs) - n1
    m1 = sum(x for x, m in zip(xs, member, strict=True) if m) / n1
    m0 = sum(x for x, m in zip(xs, member, strict=True) if not m) / n0
    per_match: dict[int, float] = defaultdict(float)
    for x, c, m in zip(xs, clusters, member, strict=True):
        per_match[c] += (x - m1) / n1 if m else -(x - m0) / n0
    g = len(set(clusters))
    return m1 - m0, math.sqrt(g / (g - 1) * sum(v * v for v in per_match.values()))


def arrays(xs: Sequence[float], clusters: Sequence[int], member: Sequence[bool]) -> tuple[Any, Any, Any]:
    codes = {c: i for i, c in enumerate(dict.fromkeys(clusters))}
    return (np.array(xs, dtype=np.float64), np.array([codes[c] for c in clusters], dtype=np.int64), np.array(member, dtype=np.bool_))


def inside(xs: Sequence[float], clusters: Sequence[int], member: Sequence[bool], kinds: Sequence[str]) -> tuple[Any, Any, Any, Any]:
    """The same arrays with the stratum of each row as a code."""
    codes = {k: i for i, k in enumerate(dict.fromkeys(kinds))}
    return (*arrays(xs, clusters, member), np.array([codes[k] for k in kinds], dtype=np.int64))


def reference_within(xs: Sequence[float], clusters: Sequence[int], member: Sequence[bool], kinds: Sequence[str]) -> tuple[float, float, float]:
    """The two means and the clustered error of the difference inside the strata, written the long way: a list of rows for each side of each stratum,
    the weights ``in * out / (in + out)`` made one by one and one dictionary of sums per match."""
    sides: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"in": [], "out": []})
    for i, (m, k) in enumerate(zip(member, kinds, strict=True)):
        sides[k]["in" if m else "out"].append(i)
    shared = {k: v for k, v in sides.items() if v["in"] and v["out"]}
    omega = {k: len(v["in"]) * len(v["out"]) / (len(v["in"]) + len(v["out"])) for k, v in shared.items()}
    weight = {k: w / sum(omega.values()) for k, w in omega.items()}
    mean = sum(weight[k] * sum(xs[i] for i in v["in"]) / len(v["in"]) for k, v in shared.items())
    mean_rest = sum(weight[k] * sum(xs[i] for i in v["out"]) / len(v["out"]) for k, v in shared.items())
    per_match: dict[int, float] = defaultdict(float)
    for k, v in shared.items():
        rows = v["in"] + v["out"]
        pooled = sum(xs[i] for i in rows) / len(rows)
        share = len(v["in"]) / len(rows)
        stretch = math.sqrt(len(rows) / (len(rows) - 1))
        for i in v["in"]:  # where the model puts it: the stratum's mean plus the difference's share on its side
            per_match[clusters[i]] += weight[k] / len(v["in"]) * (xs[i] - pooled - (mean - mean_rest) * (1 - share)) * stretch
        for i in v["out"]:
            per_match[clusters[i]] -= weight[k] / len(v["out"]) * (xs[i] - pooled - (mean - mean_rest) * (0 - share)) * stretch
    g = len({clusters[i] for v in shared.values() for i in v["in"] + v["out"]})
    return mean, mean_rest, math.sqrt(g / (g - 1) * sum(v * v for v in per_match.values()))


# ── the groups of a decision ─────────────────────────────────────────────────────────────────────────────────────

def test_the_odds_bands_include_their_lower_edge_and_exclude_their_upper_one() -> None:
    assert [ps.odds_band(x) for x in (1.01, 1.399, 1.4, 1.699, 1.7, 1.999, 2.0, 2.499, 2.5, 3.499, 3.5, 5.999, 6.0, 40.0)] == [
        "under 1.40", "under 1.40", "1.40-1.69", "1.40-1.69", "1.70-1.99", "1.70-1.99", "2.00-2.49", "2.00-2.49", "2.50-3.49", "2.50-3.49",
        "3.50-5.99", "3.50-5.99", "6.00 and over", "6.00 and over"]


def test_a_line_is_written_the_way_a_reader_writes_it() -> None:
    assert [ps.line_text(D(x)) for x in ("2.50", "-0.50", "0.00", "-0", "3.00", "10", "0.25", "-1.5000")] == ["2.5", "-0.5", "0", "0", "3", "10", "0.25", "-1.5"]


def test_a_selection_that_backs_a_side_belongs_to_that_side_and_every_other_belongs_to_both() -> None:
    assert [ps.side_tags(m, s) for m, s in (("1X2", "Home"), ("1X2", "Away"), ("DC", "1X"), ("DC", "X2"), ("AH", "Home"), ("AH", "Away"))] == [
        ("home",), ("away",), ("home",), ("away",), ("home",), ("away",)]
    for market, selection in (("1X2", "Draw"), ("OU", "Over"), ("OU", "Under"), ("BTTS", "Yes"), ("BTTS", "No"), ("CORNERS_OU", "Over")):
        assert ps.side_tags(market, selection) == ("home", "away"), (market, selection)


def tags(**changes: Any) -> dict[str, tuple[str, ...]]:
    base: dict[str, Any] = {
        "market": "OU", "line": D("2.50"), "selection": "Over", "model": "poisson", "calibrator_role": "CHAMPION", "odds": 1.85, "context": "PARTIAL",
        "competition_type": "domestic_league", "stage_role": "league", "competition_id": 39, "home_team": 10, "away_team": 20, "home_coach": "c1",
        "away_coach": "c2", "referee_id": 7}
    return ps.tags_of(**{**base, **changes})


def test_the_groups_of_a_decision_one_for_each_dimension() -> None:
    got = tags()
    assert got == {"market": ("OU",), "market_line": ("OU 2.5",), "selection": ("OU Over",), "model": ("poisson",), "calibration_role": ("CHAMPION",),
                   "context": ("PARTIAL",), "match_type": ("domestic_league:league",), "competition": ("39",), "team": ("10", "20"),
                   "odds_band": ("1.70-1.99",), "coach": ("c1", "c2"), "referee": ("7",)}
    assert set(got) == set(ps.DIMENSIONS), "every dimension of the plan has its group"


def test_a_selection_that_backs_one_side_is_a_statement_about_that_team_and_that_coach() -> None:
    home = tags(market="1X2", selection="Home", line=D("0"))
    away = tags(market="DC", selection="X2", line=D("0"))
    assert (home["team"], home["coach"]) == (("10",), ("c1",)) and (away["team"], away["coach"]) == (("20",), ("c2",))
    assert home["selection"] == ("1X2 Home",) and home["market_line"] == ("1X2 0",)
    draw = tags(market="1X2", selection="Draw", line=D("0"))
    assert (draw["team"], draw["coach"]) == (("10", "20"), ("c1", "c2")), "the draw backs neither"


def test_what_a_decision_cannot_say_is_left_out_of_its_groups() -> None:
    got = tags(referee_id=None, odds=None, home_coach=None, away_coach=None, calibrator_role=None, stage_role=None)
    assert "referee" not in got and "odds_band" not in got and "coach" not in got
    assert got["calibration_role"] == ("none",) and got["match_type"] == ("domestic_league:unknown",)
    assert tags(home_coach=None)["coach"] == ("c2",), "one coach known is one group"
    assert "coach" not in tags(market="1X2", selection="Home", line=D("0"), home_coach=None), "the side it backs has no known coach"


def test_the_lead_time_is_a_band_that_includes_its_lower_edge_and_excludes_its_upper_one() -> None:
    assert [ps.lead_band(x) for x in (0.0, 0.99, 1.0, 2.99, 3.0, 5.99, 6.0, 11.99, 12.0, 23.99, 24.0, 47.5, None)] == [
        "under 1 h", "under 1 h", "1-3 h", "1-3 h", "3-6 h", "3-6 h", "6-12 h", "6-12 h", "12-24 h", "12-24 h", "24 h and over", "24 h and over", "-"]


def test_the_kind_of_bet_of_a_row_is_its_line_its_odds_band_and_its_lead_time() -> None:
    assert ps.stratum(row(1, market_line=("OU 2.5",), odds_band=("1.70-1.99",), lead=2.0)) == ("OU 2.5", "1.70-1.99", "1-3 h")
    assert ps.stratum(row(2)) == ("-", "-", "-"), "what a row cannot say is the same for all the rows that cannot say it"
    assert ps.stratum(row(3, market_line=("AH -0.5",), odds_band=("2.00-2.49",), lead=0.2)) != ps.stratum(row(3, market_line=("AH -0.5",),
                                                                                                          odds_band=("2.00-2.49",), lead=5.0))
    assert ps.STRATA == ("market_line", "odds_band", "lead")
    assert sorted(ps.STANDS_FOR) == sorted(ps.DIMENSIONS), "every dimension has its place in the order that says which of two identical groups the search keeps"


def test_which_groups_are_read_inside_the_kind_of_bet_and_which_only_describe_it() -> None:
    for dimension in ps.DIMENSIONS:
        structural = dimension in ("market", "market_line", "selection", "odds_band")
        assert ps.descriptive("clv", dimension) is structural and ps.adjusted("clv", dimension) is (not structural)
        for metric in ("calibration", "vs_close"):
            assert not ps.descriptive(metric, dimension) and not ps.adjusted(metric, dimension), "no difference is zero wherever the bet is"
    assert ps.STRUCTURAL == ("market", "market_line", "selection", "odds_band") and ps.ADJUSTED == ("clv",)


# ── the measures ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_three_measures_of_a_row() -> None:
    r = row(1, p=0.6, won=1, p_close=0.55, clv=0.04)
    assert ps.measure("calibration", r) == pytest.approx(0.4)
    assert ps.measure("vs_close", r) == pytest.approx(loss(0.55, 1) - loss(0.6, 1)) and ps.measure("vs_close", r) == pytest.approx(math.log(0.6 / 0.55))
    assert ps.measure("clv", r) == 0.04
    lost = row(2, p=0.6, won=0, p_close=0.55)
    assert ps.measure("calibration", lost) == pytest.approx(-0.6)
    assert ps.measure("vs_close", lost) == pytest.approx(math.log(0.40 / 0.45)), "the system gave the loser more than the close did: it read it worse"


def test_the_log_loss_is_the_one_of_the_scoreboard_of_the_families() -> None:
    """Written in this package so as not to import that one (the import closed a loop of packages that ``test_architecture`` keeps from growing);
    held equal here, ends included (a probability is kept off 0 and 1)."""
    for p, won in itertools.product((0.0, 1e-9, 1e-6, 0.05, 0.3, 0.5, 0.97, 1.0 - 1e-6, 1.0), (0, 1)):
        assert ps.loss(p, won) == loss(p, won), (p, won)
    assert ps.measure("vs_close", row(1, p=1.0, won=0, p_close=0.0)) == loss(0.0, 0) - loss(1.0, 0)


def test_a_row_that_cannot_be_read_for_a_measure_is_not_one_of_its_rows() -> None:
    half_won = row(1, won=None, p_close=0.5, clv=0.1)
    assert ps.measure("calibration", half_won) is None and ps.measure("vs_close", half_won) is None and ps.measure("clv", half_won) == 0.1
    assert ps.measure("vs_close", row(2, p_close=None)) is None and ps.measure("clv", row(2, clv=None)) is None
    with pytest.raises(ValueError, match="not a measure"):
        ps.measure("roi", row(3))


def test_only_a_win_or_a_loss_with_no_stake_to_come_back_can_be_read_against_a_probability() -> None:
    assert ps.readable("win", 0.0, D("2.5")) and ps.readable("loss", 0.0, D("-0.5")) and ps.readable("win", 0.0, D("0"))
    assert not ps.readable("push", 0.0, D("2")) and not ps.readable("half_win", 0.0, D("2.25")) and not ps.readable("void", 0.0, D("2.5"))
    assert not ps.readable("win", 0.1, D("2.5")), "a probability that a stake comes back is not the probability of a win"
    assert not ps.readable("win", 0.0, D("2.25")) and not ps.readable("loss", 0.0, D("-0.75")), "a quarter line settles in halves"
    assert not ps.readable("half_win", 0.0, D("2.5")) and not ps.readable("half_loss", 0.0, D("-0.5")), "a half win is not a win, whatever line it is read on"


# ── the arithmetic ───────────────────────────────────────────────────────────────────────────────────────────────

def test_with_every_row_its_own_match_the_difference_is_the_familiar_one() -> None:
    xs = [1.0, 2.0, 4.0, 3.0, 0.0, 1.0, 5.0, 2.0, 2.0, 6.0]
    member = [True] * 4 + [False] * 6
    got = ps.contrast(*arrays(xs, list(range(10)), member))
    assert got is not None
    a, b = xs[:4], xs[4:]
    ma, mb = sum(a) / 4, sum(b) / 6
    welch = math.sqrt(sum((x - ma) ** 2 for x in a) / 16 + sum((x - mb) ** 2 for x in b) / 36)
    assert got.delta == pytest.approx(ma - mb) == pytest.approx(2.5 - 2.6667, abs=1e-3)
    assert got.se == pytest.approx(welch * math.sqrt(10 / 9)), "the familiar error, with the few matches their due"
    assert (got.n, got.matches, got.n_rest, got.matches_rest) == (4, 4, 6, 6)
    assert got.mean == pytest.approx(ma) and got.mean_rest == pytest.approx(mb)
    assert got.z == pytest.approx(got.delta / got.se)


def test_with_several_rows_in_a_match_the_error_is_the_one_that_adds_a_match_up_before_it_squares() -> None:
    rng = np.random.default_rng(5)
    clusters = [int(c) for c in rng.integers(0, 40, size=150)]
    xs = [float(v) for v in rng.normal(size=150) + np.array(clusters) * 0.03]
    member = [bool(m) for m in (rng.random(150) < 0.3)]
    want_delta, want_se = reference(xs, clusters, member)
    got = ps.contrast(*arrays(xs, clusters, member))
    assert got is not None
    assert got.delta == pytest.approx(want_delta) and got.se == pytest.approx(want_se)
    assert got.matches == len({c for c, m in zip(clusters, member, strict=True) if m}) and got.matches_rest == len({c for c, m in zip(clusters, member, strict=True) if not m})


def test_a_match_with_rows_in_the_group_and_in_the_rest_is_counted_in_both() -> None:
    xs, clusters, member = [1.0, 3.0, 2.0, 2.0, 5.0, 1.0], [0, 0, 1, 1, 2, 3], [True, False, True, False, True, False]
    got = ps.contrast(*arrays(xs, clusters, member))
    assert got is not None and (got.matches, got.matches_rest, got.n, got.n_rest) == (3, 3, 3, 3), "matches 0 and 1 have a row on each side"
    want_delta, want_se = reference(xs, clusters, member)
    assert got.delta == pytest.approx(want_delta) and got.se == pytest.approx(want_se)


def test_swapping_the_group_and_the_rest_changes_the_sign_and_nothing_else() -> None:
    rng = np.random.default_rng(9)
    clusters = [int(c) for c in rng.integers(0, 30, size=120)]
    xs = [float(v) for v in rng.normal(size=120)]
    member = [bool(m) for m in (rng.random(120) < 0.4)]
    a = ps.contrast(*arrays(xs, clusters, member))
    b = ps.contrast(*arrays(xs, clusters, [not m for m in member]))
    assert a is not None and b is not None
    assert b.delta == pytest.approx(-a.delta) and b.se == pytest.approx(a.se) and b.z == pytest.approx(-a.z)
    assert (b.n, b.matches) == (a.n_rest, a.matches_rest) and b.mean == pytest.approx(a.mean_rest)


def test_the_numbering_of_the_matches_does_not_matter() -> None:
    rng = np.random.default_rng(2)
    clusters = [int(c) for c in rng.integers(0, 25, size=90)]
    xs = [float(v) for v in rng.normal(size=90)]
    member = [bool(m) for m in (rng.random(90) < 0.5)]
    renamed = [(c * 7 + 3) % 101 for c in clusters]
    a, b = ps.contrast(*arrays(xs, clusters, member)), ps.contrast(*arrays(xs, renamed, member))
    assert a is not None and b is not None and a.se == pytest.approx(b.se) and a.delta == pytest.approx(b.delta)


def test_a_difference_that_cannot_be_measured_is_none() -> None:
    assert ps.contrast(*arrays([1.0, 2.0, 3.0], [0, 1, 2], [True, True, True])) is None, "nothing to compare with"
    assert ps.contrast(*arrays([1.0, 2.0, 3.0], [0, 1, 2], [False, False, False])) is None, "an empty group"
    assert ps.contrast(*arrays([1.0, 2.0, 3.0, 4.0], [0, 0, 0, 0], [True, False, True, False])) is None, "one match is one observation"
    assert ps.contrast(*arrays([2.0] * 6, [0, 1, 2, 3, 4, 5], [True, False, True, False, True, False])) is None, "every row the same: no spread to divide by"


def test_rows_of_one_match_that_say_the_same_thing_are_one_piece_of_news_not_two() -> None:
    rng = np.random.default_rng(11)
    base = [float(v) for v in rng.normal(size=80)]
    member_once = [i < 30 for i in range(80)]
    once = ps.contrast(*arrays(base, list(range(80)), member_once))
    twice_as_rows = ps.contrast(*arrays([x for x in base for _ in range(2)], list(range(160)), [m for m in member_once for _ in range(2)]))
    twice_as_matches = ps.contrast(*arrays([x for x in base for _ in range(2)], [i // 2 for i in range(160)], [m for m in member_once for _ in range(2)]))
    assert once is not None and twice_as_rows is not None and twice_as_matches is not None
    assert twice_as_rows.se == pytest.approx(once.se / math.sqrt(2), rel=0.02), "counted as two matches, the news looks twice as certain"
    assert twice_as_matches.se == pytest.approx(once.se, rel=0.02), "counted as one, it is what it was"
    assert twice_as_matches.delta == pytest.approx(once.delta) and twice_as_matches.matches == once.matches


def test_the_chance_of_a_z_when_there_is_nothing_to_find() -> None:
    assert ps.two_sided_p(3.0) == pytest.approx(0.0026998, rel=1e-4) and ps.two_sided_p(-3.0) == ps.two_sided_p(3.0) and ps.two_sided_p(0.0) == 1.0
    assert ps.student_two_sided_p(3.0, 29) == pytest.approx(2 * stats.t.sf(3.0, 29)) == pytest.approx(0.0055, abs=1e-4), "with 30 matches, twice as often"
    assert ps.student_two_sided_p(3.0, 1_000_000) == pytest.approx(ps.two_sided_p(3.0), rel=1e-3), "with very many, the normal"
    assert ps.student_two_sided_p(1.0, 1) == pytest.approx(0.5), "two matches: the Cauchy, whose tail is known"
    assert ps.student_two_sided_p(3.0, 2) == pytest.approx(1 - 3 / math.sqrt(11))
    assert ps.student_two_sided_p(-2.2, 40) == ps.student_two_sided_p(2.2, 40)
    assert ps.student_two_sided_p(3.0, 29) > ps.student_two_sided_p(3.0, 99) > ps.student_two_sided_p(3.0, 999) > ps.two_sided_p(3.0)


def test_the_bar_a_z_must_clear_after_all_the_comparisons() -> None:
    assert ps.corrected_z(1) == pytest.approx(1.959964, abs=1e-5)
    assert ps.corrected_z(1000) == pytest.approx(4.0556, abs=1e-3), "a thousand comparisons: 0.05 / 1000 for each"
    assert ps.corrected_z(10) < ps.corrected_z(100) < ps.corrected_z(10_000)
    assert ps.corrected_z(0) == ps.MIN_Z, "nothing was compared: the plan's bar"


def test_inside_one_stratum_the_difference_is_the_plain_one() -> None:
    rng = np.random.default_rng(3)
    clusters = [int(c) for c in rng.integers(0, 35, size=140)]
    xs = [float(v) for v in rng.normal(size=140)]
    member = [bool(m) for m in (rng.random(140) < 0.3)]
    plain = ps.contrast(*arrays(xs, clusters, member))
    one = ps.contrast(*inside(xs, clusters, member, ["only"] * 140))
    assert plain is not None and one is not None
    assert (one.n, one.matches, one.n_rest, one.matches_rest) == (plain.n, plain.matches, plain.n_rest, plain.matches_rest)
    assert one.mean == pytest.approx(plain.mean) and one.mean_rest == pytest.approx(plain.mean_rest) and one.delta == pytest.approx(plain.delta)
    assert one.se == pytest.approx(plain.se, rel=0.15), "the spread is measured from the pooled mean and stretched for the mean being estimated: close, not equal"


def test_inside_the_strata_the_difference_is_the_average_of_the_differences_weighted_by_the_rows_of_both() -> None:
    # stratum A: the group has 1 and 3, the rest 0, 2 and 2 (means 2 and 4/3); B: the group has 10, the rest 4 and 6 (means 10 and 5);
    # C has only the rest and D only the group: nothing to compare with there. Every row is its own match.
    xs = [1.0, 3.0, 0.0, 2.0, 2.0, 10.0, 4.0, 6.0, 100.0, 100.0, 50.0]
    member = [True, True, False, False, False, True, False, False, False, False, True]
    kinds = ["A"] * 5 + ["B"] * 3 + ["C"] * 2 + ["D"]
    got = ps.contrast(*inside(xs, list(range(11)), member, kinds))
    assert got is not None
    # the weights are in*out/(in+out): 2*3/5 = 6/5 for A and 1*2/3 = 2/3 for B, that is 9/14 and 5/14 once they add up to one
    assert got.mean == pytest.approx(9 / 14 * 2 + 5 / 14 * 10) == pytest.approx(68 / 14)
    assert got.mean_rest == pytest.approx(9 / 14 * (4 / 3) + 5 / 14 * 5) == pytest.approx(37 / 14)
    assert got.delta == pytest.approx(9 / 14 * (2 - 4 / 3) + 5 / 14 * (10 - 5)) == pytest.approx(31 / 14)
    assert (got.n, got.matches, got.n_rest, got.matches_rest) == (3, 3, 5, 5), "the rows of C and D take no part and are not counted"
    mean, mean_rest, se = reference_within(xs, list(range(11)), member, kinds)
    assert got.mean == pytest.approx(mean) and got.mean_rest == pytest.approx(mean_rest) and got.se == pytest.approx(se)
    alone = ps.contrast(*inside(xs[:8], list(range(8)), member[:8], kinds[:8]))
    assert alone is not None and alone.delta == pytest.approx(got.delta) and alone.se == pytest.approx(got.se), "without C and D it is the same answer"


def test_inside_the_strata_with_several_rows_in_a_match_the_error_adds_the_match_up_across_the_strata() -> None:
    rng = np.random.default_rng(6)
    clusters = [int(c) for c in rng.integers(0, 45, size=200)]
    kinds = [f"k{int(k)}" for k in rng.integers(0, 12, size=200)]
    xs = [float(v) + int(k[1:]) * 0.4 for v, k in zip(rng.normal(size=200), kinds, strict=True)]
    member = [bool(m) for m in (rng.random(200) < 0.3)]
    got = ps.contrast(*inside(xs, clusters, member, kinds))
    mean, mean_rest, se = reference_within(xs, clusters, member, kinds)
    assert got is not None
    assert got.mean == pytest.approx(mean) and got.mean_rest == pytest.approx(mean_rest) and got.se == pytest.approx(se)
    assert got.delta == pytest.approx(got.mean - got.mean_rest)


def test_without_a_stratum_that_holds_both_sides_there_is_nothing_to_compare() -> None:
    xs, clusters = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], list(range(6))
    assert ps.contrast(*inside(xs, clusters, [True, True, True, False, False, False], ["a", "a", "a", "b", "b", "b"])) is None, "the group is its own kind of bet"
    assert ps.contrast(*inside(xs, clusters, [True, False, True, False, True, False], ["a", "b", "c", "d", "e", "f"])) is None, "one row of a kind"
    assert ps.contrast(*inside([], [], [], [])) is None
    assert ps.contrast(*inside([1.0, 2.0, 3.0], [0, 0, 0], [True, False, True], ["a", "a", "a"])) is None, "all in one match: one observation"


def structured_world(rng: np.random.Generator, *, matches: int = 240, kinds: int = 30, shift: float = 0.0, confound: float = 0.0) -> tuple[Any, Any, Any, Any]:
    """Rows whose value is set by the KIND of bet (strongly), the match's share and noise. The group is an eighth of the matches; with ``confound`` the
    matches that play the kinds of high value are likelier to be in it. ``shift`` is a real difference the group adds inside every kind."""
    per = rng.integers(1, 7, size=matches)
    clusters = np.repeat(np.arange(matches), per).astype(np.int64)
    level = rng.normal(0.0, 2.0, kinds)
    kind = rng.integers(0, kinds, size=clusters.size).astype(np.int64)
    share = rng.normal(0.0, 0.5, matches)
    values = level[kind] + share[clusters] + rng.normal(0.0, 1.0, clusters.size)
    typical = np.bincount(clusters, weights=level[kind]) / per
    odds = np.exp(confound * (typical - typical.mean()))
    in_group = np.zeros(matches, dtype=np.bool_)
    in_group[rng.choice(matches, size=matches // 8, replace=False, p=odds / odds.sum())] = True
    member = in_group[clusters]
    return values + shift * member, clusters, member, kind


def z_scores(seed: int, worlds: int = 160, **world: Any) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    rng = np.random.default_rng(seed)
    raw, within, delta = [], [], []
    for _ in range(worlds):
        values, clusters, member, kind = structured_world(rng, **world)
        a, b = ps.contrast(values, clusters, member), ps.contrast(values, clusters, member, kind)
        assert a is not None and b is not None
        raw.append(a.z)
        within.append(b.z)
        delta.append(b.delta)
    return np.array(raw), np.array(within), np.array(delta)


def test_inside_the_strata_a_group_that_differs_by_nothing_but_the_kinds_it_plays_gives_the_z_of_no_difference() -> None:
    raw, within, _ = z_scores(31)
    assert abs(float(within.mean())) < 0.25 and 0.8 < float(within.std()) < 1.25 and float(np.mean(np.abs(within) > 3)) <= 0.02, "a z, as a z should be"
    assert 0.8 < float(raw.std()) < 1.4, "(with no structure in the group the plain z is a z as well)"


def test_inside_the_strata_a_group_that_plays_the_kinds_of_high_value_is_not_a_pattern_and_the_plain_difference_says_it_is() -> None:
    raw, within, _ = z_scores(32, confound=1.0)
    assert float(raw.mean()) > 2.0 and float(np.mean(raw > 3)) > 0.3, "the plain difference takes the kinds it plays for the group's doing"
    assert abs(float(within.mean())) < 0.25 and 0.8 < float(within.std()) < 1.25 and float(np.mean(np.abs(within) > 3)) <= 0.02


def test_inside_the_strata_a_real_difference_is_recovered_and_the_standard_error_does_not_hide_it() -> None:
    _, within, delta = z_scores(33, shift=0.6, confound=1.0)
    assert float(delta.mean()) == pytest.approx(0.6, abs=0.08), "the 0.6 that was put in, whatever the kinds the group plays"
    assert float(np.mean(within > 3)) > 0.4 and float(within.mean()) > 2.0, "and it clears the bar often with 30 matches of the group among 240"


# ── the search ───────────────────────────────────────────────────────────────────────────────────────────────────

def clv_world(*, matches: int = 400, seed: int = 7, groups: int = 8, shift: dict[str, float] | None = None, shift_days: tuple[float, float] = (0, 1e9),
              icc: float = 0.5, days: int = 120) -> list[Obs]:
    """``matches`` matches with 1 to 4 rows each. The value of a row is the match's share plus its own (``icc`` of the variance is the match's) plus the
    ``shift`` of the competition it is played in, from the day ``shift_days[0]`` to ``shift_days[1]``; competition ``c0`` ... ``c{groups-1}``; a row has
    a selection, which is not tied to the match."""
    rng = np.random.default_rng(seed)
    rows: list[Obs] = []
    for m in range(matches):
        day = m * days / matches
        comp = f"c{m % groups}"
        share = rng.normal(0.0, math.sqrt(icc))
        extra = (shift or {}).get(comp, 0.0) if shift_days[0] <= day < shift_days[1] else 0.0
        for _ in range(1 + int(rng.integers(0, 4))):
            x = float(share + rng.normal(0.0, math.sqrt(1.0 - icc)) + extra)
            rows.append(row(m, day, won=None, p_close=None, clv=x, competition=(comp,), selection=(f"s{int(rng.integers(0, 4))}",),
                            odds_band=(f"b{int(rng.integers(0, 3))}",)))
    return rows


def found(report: dict[str, Any]) -> list[tuple[str, str]]:
    return [(f["dimension"], f["value"]) for f in report["found"]]


def test_a_planted_difference_is_found_with_its_numbers_and_nothing_else_is() -> None:
    report = ps.search(clv_world(shift={"c3": 0.6}), metrics=("clv",), dimensions=("competition",))
    assert found(report) == [("competition", "c3")]
    f = report["found"][0]
    assert f["metric"] == "clv" and f["delta"] > 0 and f["z"] >= 3 and f["stable"] is True and f["survives_correction"] is True
    assert f["matches"] == 50 and f["n"] > f["matches"] and f["matches_rest"] == 350 and f["mean"] - f["mean_rest"] == pytest.approx(f["delta"])
    assert 0.3 < f["delta"] < 0.9, "the 0.6 that was put in"
    assert all(h is not None and h["z"] >= 1.0 and h["delta"] > 0 for h in f["halves"])
    assert report["tests"] == 8 and len(report["found"]) + len(report["nearest"]) == 8, "eight competitions: one found, the other seven are the nearest"
    assert report["rows"]["by_measure"]["clv"]["matches"] == 400 and report["rows"]["decisions"] == len(clv_world())


def test_a_difference_in_the_other_direction_is_found_with_its_sign() -> None:
    report = ps.search(clv_world(shift={"c5": -0.6}), metrics=("clv",), dimensions=("competition",))
    assert found(report) == [("competition", "c5")] and report["found"][0]["delta"] < 0 and report["found"][0]["z"] <= -3


def test_the_groups_that_are_too_small_are_counted_and_not_tested() -> None:
    report = ps.search(clv_world(matches=300, groups=12), metrics=("clv",), min_matches=30)
    cover = report["coverage"]["clv"]
    assert cover["competition"] == {"groups": 12, "tested": 0, "same": 0}, "25 matches each: below the minimum"
    assert cover["selection"] == {"groups": 4, "tested": 4, "same": 0} and cover["odds_band"] == {"groups": 3, "tested": 3, "same": 0}
    assert cover["team"] == {"groups": 0, "tested": 0, "same": 0} and cover["referee"] == {"groups": 0, "tested": 0, "same": 0}, "nobody tagged"
    assert report["tests"] == 7
    again = ps.search(clv_world(matches=300, groups=12), metrics=("clv",), min_matches=25)
    assert again["coverage"]["clv"]["competition"] == {"groups": 12, "tested": 12, "same": 0}, "the minimum is a parameter, and exactly the minimum is enough"
    assert ps.search(clv_world(matches=300, groups=12), metrics=("clv",), min_matches=26)["coverage"]["clv"]["competition"]["tested"] == 0


def test_the_rest_needs_its_matches_as_much_as_the_group() -> None:
    rows = clv_world(matches=59, groups=2)  # 30 and 29 matches
    cover = ps.search(rows, metrics=("clv",), min_matches=30)["coverage"]["clv"]["competition"]
    assert cover == {"groups": 2, "tested": 0, "same": 0}, "the group of 30 has a rest of 29, the group of 29 has none to speak of"


def test_a_world_with_nothing_in_it_finds_what_chance_says_and_no_more() -> None:
    clustered = naive = 0
    expected = 0.0
    tested = 0
    for seed in range(200):
        rows = clv_world(matches=360, seed=seed, groups=9)
        report = ps.search(rows, metrics=("clv",))
        clustered += len(report["found"])
        expected += report["expected_by_chance"]
        tested += report["tests"]
        alone = [Obs(i, r.kickoff_at, r.p, r.won, r.p_close, r.clv, r.tags) for i, r in enumerate(rows)]  # every row its own match
        naive += len(ps.search(alone, metrics=("clv",))["found"])
    assert tested == 200 * 16, "nine competitions, four selections and three odds bands in each of two hundred worlds"
    assert expected == pytest.approx(tested * 0.004, rel=0.15), "four in a thousand: the tails of a t with 40 matches, a little heavier than the normal's 2.7"
    assert clustered <= expected + 5 * math.sqrt(expected) + 3, f"{clustered} findings where chance says {expected:.1f}"
    assert naive >= 3 * max(clustered, expected), f"counting every row as news ({naive}) finds several times what there is; counting the match ({clustered}) does not"


def test_a_difference_that_shows_in_one_half_only_is_found_but_does_not_repeat() -> None:
    both = ps.search(clv_world(shift={"c2": 0.7}), metrics=("clv",), dimensions=("competition",))
    first = ps.search(clv_world(shift={"c2": 2.0}, shift_days=(0, 60)), metrics=("clv",), dimensions=("competition",))
    second = ps.search(clv_world(shift={"c2": 2.0}, shift_days=(60, 1e9)), metrics=("clv",), dimensions=("competition",))
    assert [f["stable"] for f in both["found"]] == [True]
    for one_half in (first, second):
        assert ("competition", "c2") in found(one_half), "big enough overall to reach the bar"
        match = next(f for f in one_half["found"] if f["value"] == "c2")
        assert match["stable"] is False and not ps.proposals(one_half), "but it does not repeat: it is not proposed"


def test_a_difference_with_too_few_matches_in_a_half_cannot_be_checked_and_is_not_proposed() -> None:
    report = ps.search(clv_world(shift={"c4": 0.7}), metrics=("clv",), half_min_matches=26)
    f = next(x for x in report["found"] if x["value"] == "c4")
    assert f["stable"] is None and f["halves"] == [None, None], "25 matches of the group in each half, 26 asked for"
    assert not ps.proposals(report)
    assert ps.search(clv_world(shift={"c4": 0.7}), metrics=("clv",), half_min_matches=25)["found"][0]["stable"] is True


def test_every_comparison_is_counted_and_chance_is_added_up_with_the_tail_of_each() -> None:
    rows = clv_world(matches=240, groups=3)  # three competitions of 80 matches against a rest of 160, then 4 selections and 3 bands of other sizes
    report = ps.search(rows, metrics=("clv",), dimensions=("competition",))
    assert report["tests"] == 3
    each = [ps.student_two_sided_p(3.0, 80 - 1)] * 3
    assert report["expected_by_chance"] == pytest.approx(sum(each))
    wide = ps.search(rows, metrics=("clv",), dimensions=("competition", "selection", "odds_band"))
    assert wide["tests"] == 3 + 4 + 3 and wide["expected_by_chance"] > report["expected_by_chance"]
    assert wide["corrected_z"] == pytest.approx(ps.corrected_z(10)) and wide["corrected_z"] > report["corrected_z"]
    both = ps.search(rows, metrics=("clv", "calibration"), dimensions=("competition",))
    assert both["tests"] == 3, "the calibration of rows with no result is not a measure: only the value of the price is compared"


def test_a_dimension_with_two_groups_is_asked_once_because_each_is_the_other_seen_from_the_other_side() -> None:
    rows = clv_world(matches=240, groups=2, shift={"c1": 0.8})
    report = ps.search(rows, metrics=("clv",), dimensions=("competition",))
    assert report["coverage"]["clv"]["competition"] == {"groups": 2, "tested": 1, "same": 0} and report["tests"] == 1
    assert [(f["value"], f["delta"] < 0) for f in report["found"]] == [("c0", True)], "the first of the two, whose rest is the other"
    assert len(ps.proposals(report)) == 1, "one hypothesis, not its mirror image as well"
    three = ps.search(clv_world(matches=240, groups=3, shift={"c1": 0.8}), metrics=("clv",), dimensions=("competition",))
    assert three["coverage"]["clv"]["competition"] == {"groups": 3, "tested": 3, "same": 0}, "with three groups the rest of each is a mixture: all are asked"
    teams = [row(m, m * 0.5, clv=float(m % 5), team=("a", "b")) for m in range(80)]
    assert ps.search(teams, metrics=("clv",), min_matches=1)["coverage"]["clv"]["team"] == {"groups": 2, "tested": 0, "same": 1}, (
        "two groups that share every row are not two halves of a split: here each has no rest, nothing is asked, and the second is the first again")


def test_a_finding_survives_the_correction_only_when_its_own_tail_is_smaller_than_the_share_of_each_comparison() -> None:
    mild = ps.search(clv_world(shift={"c1": 0.45}), metrics=("clv",))
    strong = ps.search(clv_world(shift={"c1": 0.9}), metrics=("clv",))
    for report in (mild, strong):
        f = report["found"][0]
        assert f["survives_correction"] == (f["p"] <= report["criterion"]["alpha"] / report["tests"])
    assert strong["found"][0]["survives_correction"] is True
    assert any(not f["survives_correction"] for f in mild["found"] + mild["nearest"]), "most of what is near the bar does not survive it"


def test_the_search_is_the_same_twice_and_does_not_depend_on_the_order_of_the_rows() -> None:
    rows = clv_world(shift={"c3": 0.5})
    once = ps.search(rows, metrics=("clv",))
    assert once == ps.search(rows, metrics=("clv",))
    shuffled = list(rows)
    np.random.default_rng(1).shuffle(shuffled)
    other = ps.search(shuffled, metrics=("clv",))
    assert [(f["dimension"], f["value"], round(f["z"], 9)) for f in other["found"]] == [(f["dimension"], f["value"], round(f["z"], 9)) for f in once["found"]]
    assert other["tests"] == once["tests"] and other["expected_by_chance"] == pytest.approx(once["expected_by_chance"])


def test_a_search_over_nothing_says_so() -> None:
    report = ps.search([])
    assert report["tests"] == 0 and report["found"] == [] and report["nearest"] == [] and report["expected_by_chance"] == 0.0
    assert report["rows"] == {"decisions": 0, "matches": 0, "by_measure": {m: {"rows": 0, "matches": 0, "mean": None} for m in ps.METRICS}}
    assert report["criterion"]["split"] is None
    assert report["criterion"]["within"] == {"measures": ["clv"], "strata": ["market_line", "odds_band", "lead"],
                                             "descriptive": ["market", "market_line", "selection", "odds_band"]}


def test_the_search_refuses_a_measure_or_a_dimension_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="not a measure"):
        ps.search([], metrics=("roi",))
    with pytest.raises(ValueError, match="not a dimension"):
        ps.search([], dimensions=("weather",))


def test_the_names_of_the_groups_come_with_the_findings() -> None:
    report = ps.search(clv_world(shift={"c3": 0.6}), metrics=("clv",), labels={("competition", "c3"): "Championship"})
    assert report["found"][0]["label"] == "Championship" and report["found"][0]["value"] == "c3"
    assert ps.search(clv_world(shift={"c3": 0.6}), metrics=("clv",))["found"][0]["label"] == "c3", "without a name, the group's own"


def test_a_group_made_of_the_very_rows_of_another_is_tested_once_and_the_report_says_what_else_it_is() -> None:
    rng = np.random.default_rng(14)
    rows = []
    for m in range(300):
        market = ("1X2", "OU", "BTTS")[m % 3]
        rows.append(row(m, m * 0.4, clv=float(rng.normal(0.0, 1.0) + (0.9 if market == "OU" else 0.0)), market=(market,), market_line=(f"{market} 0",)))
    report = ps.search(rows, metrics=("clv",), dimensions=("market", "market_line"))
    assert report["coverage"]["clv"] == {"market": {"groups": 3, "tested": 3, "same": 0}, "market_line": {"groups": 3, "tested": 0, "same": 3}}
    assert report["tests"] == 3, "three questions, not six"
    [ou] = [f for f in report["found"] if f["value"] == "OU"]
    assert ou["dimension"] == "market" and ou["same_rows_as"] == [["market_line", "OU 0"]], "the first dimension of the plan stands for the others"
    assert {f["dimension"] for f in report["found"] + report["nearest"]} == {"market"}
    line = next(x for x in ps.render(report).splitlines() if x.startswith("  clv         Mercado          OU "))
    assert line.endswith("[descriptive]  (the same rows as Mercado y línea OU 0)")
    assert "Mercado 3/3, Mercado y línea 3/0 +3" in ps.render(report)


def test_when_a_competition_is_the_only_one_of_its_type_the_competition_is_the_group_that_is_named() -> None:
    rng = np.random.default_rng(15)
    rows = []
    for m in range(240):
        comp = ("cup", "league_a", "league_b")[m % 3]
        kind = "domestic_cup:unknown" if comp == "cup" else "domestic_league:unknown"
        rows.append(row(m, m * 0.5, clv=float(rng.normal(0.0, 1.0) + (0.9 if comp == "cup" else 0.0)), competition=(comp,), match_type=(kind,)))
    report = ps.search(rows, metrics=("clv",), dimensions=("competition", "match_type"))
    [cup] = [f for f in report["found"] if f["delta"] > 0]
    assert (cup["dimension"], cup["value"], cup["same_rows_as"]) == ("competition", "cup", [["match_type", "domestic_cup:unknown"]])
    assert report["coverage"]["clv"]["match_type"] == {"groups": 2, "tested": 0, "same": 1}, "the type of the cup is the competition again, and the other type is its mirror: nothing is asked of the match type"


def kind_world(*, shift: dict[str, float] | None = None, seed: int = 5, matches: int = 480) -> list[Obs]:
    """The value of a price is set by its odds band (b0 high, b1 middle, b2 low) and the competitions play different mixes of bands: c0 mostly b0, c1 mostly
    b2, the others a little of each. ``shift`` adds a real difference to a competition inside every band."""
    rng = np.random.default_rng(seed)
    level = {"b0": 0.8, "b1": 0.0, "b2": -0.8}
    mixes = {"c0": [0.8, 0.15, 0.05], "c1": [0.05, 0.15, 0.8]} | {f"c{k}": [0.34, 0.33, 0.33] for k in range(2, 6)}
    rows = []
    for m in range(matches):
        comp = f"c{m % 6}"
        share = rng.normal(0.0, 0.5)
        for _ in range(1 + int(rng.integers(0, 3))):
            band = f"b{int(rng.choice(3, p=mixes[comp]))}"
            x = level[band] + share + rng.normal(0.0, 0.7) + (shift or {}).get(comp, 0.0)
            rows.append(row(m, m * 120 / matches, clv=float(x), competition=(comp,), odds_band=(band,), selection=(f"s{int(rng.integers(0, 4))}",)))
    return rows


def test_a_competition_that_plays_other_prices_is_not_a_pattern_when_the_prices_are_compared_alike() -> None:
    rows = kind_world()
    report = ps.search(rows, metrics=("clv",), dimensions=("competition", "odds_band"))
    assert {f["dimension"] for f in report["found"]} == {"odds_band"}, "the bands differ by construction: that is the price itself, not the competitions"
    assert all(f["descriptive"] and not f["within_strata"] for f in report["found"])
    table = ps._table(rows, "clv", ("competition",))
    for comp in ("c0", "c1"):
        plain = ps.contrast(table.values, table.clusters, ps._members(int(table.values.shape[0]), table.groups[("competition", comp)]))
        assert plain is not None and abs(plain.z) > 5, "without the comparison inside the bands they would have been findings"
    assert not ps.proposals(report), "and the bands, which only describe the price, are not proposed"


def test_a_real_difference_inside_the_bands_is_found_whatever_prices_the_competition_plays() -> None:
    report = ps.search(kind_world(shift={"c0": 0.5}), metrics=("clv",), dimensions=("competition", "odds_band"))
    [f] = [x for x in report["found"] if x["dimension"] == "competition"]
    assert f["value"] == "c0" and f["within_strata"] is True and f["descriptive"] is False and 0.3 < f["delta"] < 0.7 and f["stable"] is True
    [p] = ps.proposals(report)
    assert p.key == "pattern2:clv:competition:c0:up" and "dentro del mismo mercado y línea, rango de cuota y antelación" in p.rationale


def test_the_lead_time_is_one_of_the_things_the_price_is_compared_alike_on() -> None:
    """The same competition takes its prices early and the rest late, and the early ones are worse by a fixed amount: with the lead times in the strata the
    competition is no pattern; without them (rows that do not say it) it is."""
    rng = np.random.default_rng(12)
    early, late = [], []
    for m in range(400):
        comp = "c0" if m % 4 == 0 else "c1" if m % 4 == 1 else "c2"
        hours = 30.0 if (comp == "c0" and m % 8 != 0) or (comp != "c0" and m % 10 == 0) else 0.5
        x = float(rng.normal(0.0, 0.5) + (-0.5 if hours > 24 else 0.0))
        early.append(row(m, m * 0.3, clv=x, lead=hours, competition=(comp,)))
        late.append(row(m, m * 0.3, clv=x, competition=(comp,)))
    said = ps.search(early, metrics=("clv",), dimensions=("competition",))
    unsaid = ps.search(late, metrics=("clv",), dimensions=("competition",))
    assert not said["found"], "compared with the prices taken at the same time before the kick-off, c0 is like the others"
    assert any(f["value"] == "c0" and f["z"] < -3 for f in unsaid["found"]), "and if the rows do not say it, it looks like a pattern"


def test_the_nearest_misses_are_listed_the_nearest_first_and_at_most_ten() -> None:
    report = ps.search(clv_world(matches=480, groups=8), metrics=("clv",))
    assert len(report["nearest"]) == min(ps.NEAREST, report["tests"] - len(report["found"]))
    zs = [abs(f["z"]) for f in report["nearest"]]
    assert zs == sorted(zs, reverse=True) and all(z < 3 for z in zs)
    assert all(f["stable"] is None for f in report["nearest"]), "the repetition is checked only for what reaches the bar"


def calibration_world() -> list[Obs]:
    """Three competitions of 180 matches each; in ``c1`` it happens 20 points more often than the system says, and the close knows. Beside each settled
    decision, one of a stake that came back (only the price counts: it has no result to be read against a probability)."""
    rng = np.random.default_rng(4)
    rows = []
    for m in range(540):
        comp = f"c{m % 3}"
        p = float(rng.uniform(0.3, 0.6))
        happens = p + (0.2 if comp == "c1" else 0.0)
        rows.append(row(m, m * 0.22, p=p, won=1 if rng.random() < happens else 0, p_close=happens, competition=(comp,)))
        rows.append(row(10_000 + m, m * 0.22, p=0.5, won=None, p_close=None, clv=0.0, competition=(comp,)))
    return rows


def test_calibration_and_the_gap_to_the_close_are_read_from_the_rows_that_settled() -> None:
    rows = calibration_world()
    report = ps.search(rows, metrics=("calibration", "vs_close"), dimensions=("competition",))
    assert report["rows"]["by_measure"]["calibration"]["rows"] == 540 and report["rows"]["by_measure"]["vs_close"]["rows"] == 540
    assert report["tests"] == 6
    got = {(f["metric"], f["value"]): f for f in report["found"] + report["nearest"]}
    assert got[("calibration", "c1")]["delta"] > 0.1 > 0 > got[("calibration", "c0")]["delta"], "c1 happens more than it says, the others do not"
    assert got[("vs_close", "c1")]["delta"] < 0 < got[("vs_close", "c0")]["delta"], "the close read c1 better than the system"
    found = {(f["metric"], f["value"]): f for f in report["found"]}
    assert found[("calibration", "c1")]["stable"] is True and found[("calibration", "c1")]["z"] > 3
    assert found[("vs_close", "c1")]["z"] < -3


# ── the edges: where a threshold is exactly met, and the numbers the report keeps for each finding ───────────────────

def test_the_chance_of_each_finding_is_the_tail_of_a_t_with_the_matches_of_the_smaller_side_less_one() -> None:
    report = ps.search(clv_world(shift={"c3": 0.6}), metrics=("clv",), dimensions=("competition",))
    seen = report["found"] + report["nearest"]
    assert len(seen) == 8 and all(f["matches"] < f["matches_rest"] for f in seen)
    for f in seen:
        assert f["p"] == pytest.approx(ps.student_two_sided_p(f["z"], f["matches"] - 1)), "the group is the smaller side: its matches, less one"
        assert f["p"] > ps.two_sided_p(f["z"]), "and the tail is heavier than the normal's"
    rng = np.random.default_rng(16)
    rows = [row(m, m * 0.1, clv=float(rng.normal() + (0.4 if m < 40 else 0.0)), competition=("c",) if m < 40 else ()) for m in range(75)]
    [f] = (report := ps.search(rows, metrics=("clv",), dimensions=("competition",), min_matches=30))["found"] + report["nearest"]
    assert (f["matches"], f["matches_rest"]) == (40, 35)
    assert f["p"] == pytest.approx(ps.student_two_sided_p(f["z"], 34)), "here the rest is the smaller side: its 35 matches, less one"


def test_the_chance_expected_is_the_tail_of_every_comparison_at_the_bar_that_was_asked() -> None:
    rows = clv_world(matches=240, groups=3)  # three competitions of 80 matches against a rest of 160
    for bar in (2.0, 3.0, 4.5):
        report = ps.search(rows, metrics=("clv",), dimensions=("competition",), min_z=bar)
        assert report["tests"] == 3 and report["criterion"]["min_z"] == bar
        assert report["expected_by_chance"] == pytest.approx(3 * ps.student_two_sided_p(bar, 79))


def test_a_finding_between_the_plain_chance_and_the_share_of_each_comparison_reaches_the_bar_and_does_not_survive() -> None:
    report = ps.search(clv_world(shift={"c1": 0.4}, seed=8), metrics=("clv",), dimensions=("competition",), min_z=2.0)
    alpha, share = report["criterion"]["alpha"], report["criterion"]["alpha"] / report["tests"]
    by = {f["value"]: f for f in report["found"]}
    assert set(by) == {"c1", "c7"}
    assert by["c1"]["p"] <= share and by["c1"]["survives_correction"] is True
    assert share < by["c7"]["p"] <= alpha and by["c7"]["survives_correction"] is False, "a chance of 1 in 70 is rare for one question and ordinary for eight"


def test_a_finding_whose_chance_is_just_under_the_share_of_each_comparison_survives_the_correction() -> None:
    report = ps.search(clv_world(shift={"c1": 0.35}, seed=7), metrics=("clv",), dimensions=("competition",), min_z=2.0)
    share = report["criterion"]["alpha"] / report["tests"]
    [f] = report["found"]
    assert f["value"] == "c1" and share / 2 < f["p"] <= share, "(0.00618 of the 0.00625 each of the eight comparisons may use)"
    assert f["survives_correction"] is True


def test_a_group_and_a_rest_of_exactly_the_minimum_of_matches_are_tested_and_one_match_fewer_is_not() -> None:
    rng = np.random.default_rng(17)
    rows = [row(m, m * 0.1, clv=float(rng.normal()), competition=("c",) if m < 30 else ()) for m in range(60)]

    def tested(some: Sequence[Obs], minimum: int = 30) -> int:
        return int(ps.search(some, metrics=("clv",), dimensions=("competition",), min_matches=minimum)["coverage"]["clv"]["competition"]["tested"])

    assert tested(rows) == 1, "thirty matches of one row each in the group and thirty in the rest: exactly the minimum on both sides"
    assert tested(rows[:59]) == 0, "a rest of 29"
    assert tested(rows[1:]) == 0, "a group of 29"
    assert tested(rows, 31) == 0


def test_a_difference_exactly_as_large_as_the_bar_reaches_it() -> None:
    rows = clv_world(matches=480, groups=8)
    near = ps.search(rows, metrics=("clv",))["nearest"][0]
    here = (near["dimension"], near["value"])
    assert here not in found(ps.search(rows, metrics=("clv",)))
    at_the_bar = ps.search(rows, metrics=("clv",), min_z=abs(near["z"]))
    assert here in found(at_the_bar), "a |z| equal to the bar is a finding"
    [entry] = [f for f in at_the_bar["found"] if (f["dimension"], f["value"]) == here]
    assert entry["stable"] is not None and all(h is not None for h in entry["halves"]), "and it is read in its two halves like any other"
    assert here not in found(ps.search(rows, metrics=("clv",), min_z=math.nextafter(abs(near["z"]), math.inf)))


def halves_by_hand(rows: Sequence[Obs], report: dict[str, Any], f: dict[str, Any]) -> list[ps.Contrast | None]:
    """The two halves of a finding worked out from the rows themselves: the rows of the measure on each side of the split, the group among them, the
    matches as they come and, for a finding read inside the kinds of bet, the kind of bet of each row."""
    split = datetime.fromisoformat(report["criterion"]["split"])
    out: list[ps.Contrast | None] = []
    for early in (True, False):
        chosen = [r for r in rows if ps.measure(f["metric"], r) is not None and (r.kickoff_at < split) is early]
        xs = [float(x) for r in chosen if (x := ps.measure(f["metric"], r)) is not None]
        clusters = [r.fixture_id for r in chosen]
        member = [f["value"] in r.tags.get(f["dimension"], ()) for r in chosen]
        if f["within_strata"]:
            out.append(ps.contrast(*inside(xs, clusters, member, ["|".join(ps.stratum(r)) for r in chosen])))
        else:
            out.append(ps.contrast(*arrays(xs, clusters, member)))
    return out


def test_each_half_of_a_finding_is_the_same_question_asked_of_the_rows_of_that_half() -> None:
    checked = 0
    worlds = ((kind_world(shift={"c0": 0.5}), ("clv",), ("competition", "odds_band")), (calibration_world(), ("calibration", "vs_close"), ("competition",)))
    for rows, metrics, dimensions in worlds:
        report = ps.search(rows, metrics=metrics, dimensions=dimensions)
        for f in report["found"]:
            for half, want in zip(f["halves"], halves_by_hand(rows, report, f), strict=True):
                assert half is not None and want is not None, (f["metric"], f["value"])
                assert half["matches"] == want.matches and half["delta"] == pytest.approx(want.delta) and half["z"] == pytest.approx(want.z)
                checked += 1
    assert checked >= 8, "(the competition read inside the bands, the bands as they come, and the two measures that are read as they come)"
    inside_the_bands = ps.search(kind_world(shift={"c0": 0.5}), metrics=("clv",), dimensions=("competition",))["found"][0]
    assert inside_the_bands["within_strata"] and all(0.2 < h["delta"] < 0.8 for h in inside_the_bands["halves"]), (
        "c0 plays the dear bands: read as it comes, its halves would be above 1; inside the bands they are the 0.5 that was put in")


def test_the_matches_of_the_kept_rows_are_numbered_from_zero() -> None:
    clusters = np.array([5, 9, 5, 7, 9, 12], dtype=np.int64)
    assert ps._recode(clusters, np.array([True, True, True, False, True, False])).tolist() == [0, 1, 0, 1]
    assert ps._recode(clusters, np.array([False, False, False, True, False, True])).tolist() == [0, 1]


def test_each_half_must_reach_the_bar_of_its_own_and_exactly_the_bar_is_enough() -> None:
    rows = clv_world(shift={"c2": 0.7})
    base = ps.search(rows, metrics=("clv",), dimensions=("competition",))
    [f] = base["found"]
    assert f["stable"] is True and all(h is not None and h["delta"] > 0 for h in f["halves"])
    weakest = min(abs(h["z"]) for h in f["halves"] if h is not None)
    assert 1.0 < weakest < 6.0
    exact = ps.search(rows, metrics=("clv",), dimensions=("competition",), half_min_z=weakest)["found"][0]
    assert exact["stable"] is True, "a half with exactly the |z| asked for is enough"
    above = ps.search(rows, metrics=("clv",), dimensions=("competition",), half_min_z=math.nextafter(weakest, math.inf))["found"][0]
    assert above["stable"] is False and all(h["delta"] > 0 for h in above["halves"]), "the same sign in both halves is not enough when one half is weaker than the bar"


def planted_in_two_dimensions(kept: int = 20) -> list[Obs]:
    """The model ``m_a`` is forty matches 1.5 lower in value and ``kept`` of them are also the ones with no calibrator: with twenty, exactly half of the
    rows of the larger group are the smaller one."""
    rng = np.random.default_rng(31)
    rows = []
    for m in range(240):
        in_a, in_b = m < 40, m < kept
        rows.append(row(m, m * 0.3, clv=float(rng.normal() - (1.5 if in_a else 0.0)), model=("m_a" if in_a else ("m_b", "m_c")[m % 2],),
                        calibration_role=("none" if in_b else ("CHAMPION", "CHALLENGER")[m % 2],)))
    return rows


def test_a_finding_that_shares_exactly_half_of_the_rows_of_a_larger_one_says_so_and_the_larger_one_does_not() -> None:
    report = ps.search(planted_in_two_dimensions(), metrics=("clv",), dimensions=("model", "calibration_role"), min_matches=20)
    position = {(f["dimension"], f["value"]): i for i, f in enumerate(report["found"])}
    big, small = position[("model", "m_a")], position[("calibration_role", "none")]
    assert big < small, "the larger |z| first"
    assert report["found"][small]["overlaps"] == [big], "twenty rows of forty: half of the rows of either, and half is enough"
    assert report["found"][big]["overlaps"] == [], "the larger one is not said to overlap the smaller: it is the smaller that repeats it"
    fewer = ps.search(planted_in_two_dimensions(19), metrics=("clv",), dimensions=("model", "calibration_role"), min_matches=19)
    assert [f["overlaps"] for f in fewer["found"] if f["dimension"] == "calibration_role" and f["value"] == "none"] == [[]], "19 of 40 is less than half"


def test_findings_of_two_measures_are_never_each_others_overlap() -> None:
    rng = np.random.default_rng(32)
    rows = []
    for m in range(300):
        low = m % 5 == 0
        rows.append(row(m, m * 0.3, p=0.5, won=int(rng.random() < (0.15 if low else 0.5)), p_close=0.5, clv=float(rng.normal() - (1.0 if low else 0.0)),
                        model=("m_a" if low else ("m_b", "m_c")[m % 2],)))
    report = ps.search(rows, metrics=("calibration", "clv"), dimensions=("model",))
    assert {(f["metric"], f["value"]) for f in report["found"]} >= {("calibration", "m_a"), ("clv", "m_a")}
    assert all(f["overlaps"] == [] for f in report["found"]), "the same rows measured two ways are two findings, not one said twice"


def test_the_overlap_of_two_groups_is_the_part_of_the_rows_of_either_that_both_share() -> None:
    a = np.array([1, 1, 1, 1, 0, 0], dtype=np.bool_)
    b = np.array([0, 0, 1, 1, 1, 1], dtype=np.bool_)
    inner = np.array([1, 1, 0, 0, 0, 0], dtype=np.bool_)
    assert ps._overlap(a, b) == pytest.approx(2 / 6) == ps._overlap(b, a)
    assert ps._overlap(a, a) == 1.0 and ps._overlap(a, ~a) == 0.0
    assert ps._overlap(a, inner) == pytest.approx(2 / 4), "a group inside another is the share of the larger one it is"
    assert ps._overlap(np.zeros(4, dtype=np.bool_), np.zeros(4, dtype=np.bool_)) == 0.0


def test_a_dimension_of_two_groups_is_a_split_in_two_only_when_the_groups_cover_every_row() -> None:
    rng = np.random.default_rng(33)
    apart = [row(m, m * 0.3, clv=float(rng.normal()), competition=(("a", "b")[m // 40],) if m < 80 else ()) for m in range(120)]
    every = [row(m, m * 0.3, clv=float(rng.normal()), competition=(("a", "b")[m % 2],)) for m in range(120)]
    ask: dict[str, Any] = {"metrics": ("clv",), "dimensions": ("competition",), "min_matches": 30}
    assert ps.search(apart, **ask)["coverage"]["clv"]["competition"] == {"groups": 2, "tested": 2, "same": 0}, "forty with no competition at all: two groups, not two halves"
    assert ps.search(every, **ask)["coverage"]["clv"]["competition"] == {"groups": 2, "tested": 1, "same": 0}


def test_the_lead_table_counts_a_match_once_however_many_decisions_were_taken_in_a_band() -> None:
    rows = [row(1, clv=-0.10, lead=0.5), row(1, clv=-0.30, lead=0.6), row(2, clv=0.0, lead=0.2), row(2, clv=0.1, lead=5.0)]
    got = ps.by_lead(rows)
    assert [(b["band"], b["decisions"], b["matches"]) for b in got] == [("under 1 h", 3, 2), ("3-6 h", 1, 1)]
    assert got[0]["mean"] == pytest.approx(-0.4 / 3)


# ── the text ─────────────────────────────────────────────────────────────────────────────────────────────────────

WINDOW = {"start": "2035-01-01T00:00:00+00:00", "end": "2035-04-01T00:00:00+00:00", "days": 90, "selected_only": False}


def test_the_text_of_a_search_says_what_was_read_how_many_questions_were_asked_and_what_came_nearest() -> None:
    report = ps.search(clv_world(shift={"c3": 0.8}), metrics=("clv",), dimensions=("competition", "selection"))
    lines = ps.render({**report, "window": {**WINDOW, "selected_only": True}}).splitlines()
    assert lines[0] == "pattern search search-v1"
    assert lines[1] == "  decisions with kick-off 2035-01-01 to 2035-04-01 (90 days, picks only)"
    assert lines[2] == f"  settled decisions read: {report['rows']['decisions']:,} in 400 matches"
    assert lines[3].startswith("    clv ") and lines[3].endswith(" rows in    400 matches, mean " + f"{100 * report['rows']['by_measure']['clv']['mean']:+.3f} %")
    assert "|z| >= 3 with at least 30 matches in the group and in the rest" in lines[4] and "the same sign with |z| >= 1 in each half" in lines[4]
    assert lines[5] == (f"  comparisons made: {report['tests']}. By chance alone {report['expected_by_chance']:.1f} of them would reach |z| >= 3; "
                        f"to stay significant after all of them a group with many matches needs |z| of about {report['corrected_z']:.1f}")
    assert lines[6] == ("  clv: a group is compared with the rest inside each (market_line, odds_band, lead) [adjusted]; the groups of Mercado, Mercado y línea, "
                        "Selección, Rango de cuota are read as they come [descriptive: how the price is built, never proposed]")
    assert lines[7] == "  groups found / groups with enough matches to be tested, by dimension (+ those with the very rows of another group, tested once):"
    assert lines[8] == "    clv          Competición 8/8, Selección 4/4"
    assert lines[9] == f"FOUND, |z| >= 3: {len(report['found'])}"
    top = report["found"][0]
    assert lines[10].startswith("  clv         Competición      c3 ") and "matches   50 rows" in lines[10]
    assert f"diff {100 * top['delta']:+.3f}" in lines[10] and f"z {top['z']:+.1f}" in lines[10] and lines[10].endswith("repeats  SURVIVES the correction  [adjusted]")
    nearest = lines[lines.index(f"NEAREST of the rest ({len(report['nearest'])}):") + 1:]
    assert len(nearest) == len(report["nearest"]) == 10
    assert all("halves n/a/n/a -" in line for line in nearest), "a group below the bar is not read in its halves"
    zs = [abs(float(line.split(" z ")[1].split()[0])) for line in nearest]
    assert zs == sorted(zs, reverse=True), "the nearest first"
    assert sum(line.endswith("[descriptive]") for line in nearest) == sum(1 for f in report["nearest"] if f["dimension"] == "selection"), (
        "the groups that are the structure itself are marked as what they are")


def test_a_difference_that_does_not_repeat_says_so_with_its_two_halves_and_one_that_cannot_be_checked_says_that() -> None:
    first = ps.search(clv_world(shift={"c2": 2.0}, shift_days=(0, 60)), metrics=("clv",), dimensions=("competition",))
    [f] = first["found"]
    line = next(x for x in ps.render(first).splitlines() if x.startswith("  clv         Competición      c2 "))
    assert f"halves {f['halves'][0]['z']:+.1f}/{f['halves'][1]['z']:+.1f} does not repeat" in line
    short = ps.search(clv_world(shift={"c4": 0.7}), metrics=("clv",), half_min_matches=26)
    line = next(x for x in ps.render(short).splitlines() if x.startswith("  clv         Competición      c4 "))
    assert "halves n/a/n/a not assessable" in line, "25 matches in each half where 26 are asked for"


def test_the_value_of_the_price_is_listed_by_lead_time_when_the_rows_say_it() -> None:
    taken = [(-0.02, 0.2), (-0.04, 0.5), (-0.06, 2.0), (-0.08, 30.0), (-0.10, 40.0), (0.50, None), (None, 5.0)]
    rows = [row(m, m * 0.1, clv=c, lead=h) for m, (c, h) in enumerate(taken)] + [row(99, 0.0, clv=-0.04, lead=0.8)]
    got = ps.by_lead(rows)
    assert [(b["band"], b["decisions"], b["matches"]) for b in got] == [("under 1 h", 3, 3), ("1-3 h", 1, 1), ("24 h and over", 2, 2), ("-", 1, 1)], (
        "the bands in the order of the clock, the rows that do not say it last; a decision with no price to value is not in any")
    assert [b["mean"] for b in got] == [pytest.approx(-0.10 / 3), pytest.approx(-0.06), pytest.approx(-0.09), pytest.approx(0.50)]
    text = ps.render(ps.search(rows, metrics=("clv",), dimensions=("competition",))).splitlines()
    block = text[text.index("  the value of the price (clv) by lead time, how long before the kick-off the decision was taken:") + 1:][:4]
    assert block == ["    under 1 h           3 decisions in     3 matches, mean -3.33 %", "    1-3 h               1 decisions in     1 matches, mean -6.00 %",
                     "    24 h and over       2 decisions in     2 matches, mean -9.00 %", "    -                   1 decisions in     1 matches, mean +50.00 %"]
    assert ps.by_lead([row(1, clv=0.1), row(2, clv=0.2)]) == [], "nobody says it: no table"
    assert ps.search(rows, metrics=("calibration",))["lead"] == [] and "by lead time" not in ps.render(ps.search(rows, metrics=("calibration",)))


def test_the_price_is_written_in_percent_and_the_other_measures_as_they_are() -> None:
    rows = [row(m, m * 0.5, p=0.4, won=m % 2, p_close=0.45, clv=0.02, competition=("c",)) for m in range(60)]
    measures = [x for x in ps.render(ps.search(rows, dimensions=("competition",))).splitlines() if " rows in " in x]
    assert [x.split()[0] for x in measures] == ["calibration", "vs_close", "clv"]
    assert measures[0].endswith("mean +0.100") and measures[2].endswith("mean +2.000 %")


def test_a_search_over_nothing_is_written_without_a_window_and_without_findings() -> None:
    lines = ps.render(ps.search([])).splitlines()
    assert lines[1] == "  settled decisions read: 0 in 0 matches" and not any("kick-off" in x for x in lines)
    assert lines[2].endswith("0 rows in      0 matches, mean -") and "    clv          no groups" in lines
    assert lines[-2:] == ["FOUND, |z| >= 3: 0", "NEAREST of the rest (0):"]


# ── the hypotheses ───────────────────────────────────────────────────────────────────────────────────────────────

def one_report(**changes: Any) -> dict[str, Any]:
    f = {"metric": "calibration", "dimension": "competition", "value": "5", "label": "Championship", "n": 133, "matches": 24, "mean": -0.031,
         "n_rest": 4155, "matches_rest": 886, "mean_rest": 0.012, "delta": -0.043, "se": 0.012, "z": -3.6, "p": 0.0014,
         "halves": [{"matches": 11, "delta": -0.04, "z": -2.0}, {"matches": 13, "delta": -0.046, "z": -2.4}], "stable": True, "survives_correction": False,
         "within_strata": False, "descriptive": False, "same_rows_as": [], "overlaps": []}
    return {"version": ps.VERSION, "tests": 180, "expected_by_chance": 0.6, "criterion": {"min_z": 3.0, "alpha": 0.05}, "found": [{**f, **changes}]}


def test_only_what_repeats_in_both_halves_is_proposed_the_surest_first_and_at_most_five() -> None:
    many = [{**one_report()["found"][0], "dimension": ps.DIMENSIONS[i], "value": str(i), "z": -(3.1 + i / 10), "stable": i != 2} for i in range(9)]
    report = {**one_report(), "found": many}
    got = ps.proposals(report)
    assert len(got) == 5 and [p.evidence["z"] for p in got] == [-3.1, -3.2, -3.4, -3.5, -3.6], "the one that does not repeat (2) is not among them"
    assert len(ps.proposals(report, limit=2)) == 2
    assert not ps.proposals({**one_report(stable=None)}) and not ps.proposals({**one_report(stable=False)})


def test_a_hypothesis_says_what_was_seen_how_many_comparisons_were_made_and_that_it_is_not_a_rule() -> None:
    [p] = ps.proposals(one_report())
    assert p.key == "pattern2:calibration:competition:5:down" and p.target == "models"
    assert p.title == "Competición Championship: ocurre menos de lo que el sistema dice"
    assert "sobrestima sus probabilidades más que en el resto" in p.hypothesis and "competición Championship" in p.hypothesis
    for text in ("24 partidos (133 decisiones)", "-0.031 frente a +0.012 en el resto", "diferencia -0.043, z -3.6", "las dos mitades de la ventana",
                 "180 comparaciones", "por azar se esperarían 0.6", "|z| ≥ 3", "puede ser el reflejo de otra", "Un patrón no es una regla"):
        assert text in p.rationale, text
    assert "corrigiendo por todas las comparaciones" not in p.rationale
    assert "sigue siendo significativa corrigiendo por todas las comparaciones" in ps.proposals(one_report(survives_correction=True))[0].rationale
    assert p.evidence == {"group": "Competición: Championship", "measure": "calibración", "z": -3.6, "delta": -0.043, "tests": 180, "expected_by_chance": 0.6,
                          "n_matches": 24, "impact": "-0.031 frente a +0.012 en el resto en 24 partidos", "investigation_cost": ps.INVESTIGATION,
                          "pattern_version": ps.VERSION}


def test_the_hypotheses_of_each_measure_and_direction_read_as_what_they_are() -> None:
    up = ps.proposals(one_report(delta=0.04, z=3.4, mean=0.05, mean_rest=0.01))[0]
    assert up.key.endswith(":up") and up.title.endswith("ocurre más de lo que el sistema dice") and "subestima" in up.hypothesis
    better = ps.proposals(one_report(metric="vs_close", delta=0.02, z=3.3, mean=0.011, mean_rest=-0.009))[0]
    assert better.target == "models" and better.title.endswith("el sistema lee mejor que el cierre") and "aporta información frente al cierre" in better.hypothesis
    worse = ps.proposals(one_report(metric="vs_close", delta=-0.02, z=-3.3))[0]
    assert worse.title.endswith("el sistema lee peor que el cierre") and "no debería generar candidatos" in worse.hypothesis
    price_up = ps.proposals(one_report(metric="clv", delta=0.05, z=3.2, mean=-0.01, mean_rest=-0.06))[0]
    assert price_up.target == "pick_engine" and "bate el cierre" in price_up.title and "-1.0 % frente a -6.0 % en el resto" in price_up.rationale
    price_down = ps.proposals(one_report(metric="clv", delta=-0.05, z=-3.2))[0]
    assert "pierde contra el cierre" in price_down.title and "elegir más cerca del cierre" in price_down.hypothesis


def two_groups_of_rows_that_overlap() -> list[Obs]:
    """Sixty matches of the model ``m_a`` (CLV 0.9 lower) of which fifty-five are also the ones with no calibrator, and as many other matches as that
    with it: two dimensions that name almost the same rows."""
    rng = np.random.default_rng(8)
    rows = []
    for m in range(360):
        low = m % 6 == 0
        model = "m_a" if low else ("m_b", "m_c")[m % 2]
        role = "none" if (low and m % 36 != 0) or (not low and m % 72 == 1) else ("CHAMPION", "CHALLENGER")[(m // 2) % 2]
        rows.append(row(m, m / 3.0, clv=float(rng.normal(0.0, 1.0) + (-0.9 if low else 0.0)), model=(model,), calibration_role=(role,)))
    return rows


def test_two_findings_that_share_most_of_their_rows_are_proposed_as_one() -> None:
    report = ps.search(two_groups_of_rows_that_overlap(), metrics=("clv",), dimensions=("model", "calibration_role"))
    named = {(f["dimension"], f["value"]): i for i, f in enumerate(report["found"])}
    a, none = named[("model", "m_a")], named[("calibration_role", "none")]
    assert report["found"][none]["overlaps"] == [a] or report["found"][a]["overlaps"] == [none], "the smaller of the two shares most of its rows with the larger"
    [p] = ps.proposals(report)
    chosen, left = ps.triage(report)
    assert len(chosen) == 1 and [why for _, why in left] == ["shares most of its rows with a larger finding"]
    assert (chosen[0]["dimension"], chosen[0]["value"]) in {("model", "m_a"), ("calibration_role", "none")} and p.key.startswith("pattern2:clv:")


def test_every_dimension_has_its_name_in_the_hypotheses_and_every_measure_its_target() -> None:
    assert set(ps.DIMENSION_ES) == set(ps.DIMENSIONS) and set(ps.TARGET) == set(ps.METRICS)
    from fbi.research.evolution import TARGETS
    assert set(ps.TARGET.values()) <= set(TARGETS)
    for dimension in ps.DIMENSIONS:
        assert ps.DIMENSION_ES[dimension] in ps.proposals(one_report(dimension=dimension))[0].title


def test_what_is_written_for_the_owner_fits_the_columns_and_the_card_of_the_page() -> None:
    from fbi.research import hypotheses

    assert ps.LABEL_CHARS == 60, "a name is cut at sixty characters: the longest title is then 138 of the 160 the column has, and the longest chip 77 of 90"
    for dimension, metric, inside in itertools.product(ps.DIMENSIONS, ps.METRICS, (False, True)):
        [p] = ps.proposals(one_report(label="x" * 400, dimension=dimension, metric=metric, within_strata=inside, survives_correction=True, z=-12.3456))
        assert len(p.title) <= hypotheses.MAX_TITLE and len(p.hypothesis) <= hypotheses.MAX_HYPOTHESIS and len(p.rationale) <= hypotheses.MAX_RATIONALE, (
            dimension, metric, inside)
        chips = [k for k in p.evidence if k not in hypotheses.APART and k != "pattern_version"]
        assert sorted(chips) == ["delta", "expected_by_chance", "group", "measure", "tests", "z"] and len(chips) <= hypotheses.MAX_CHIPS
        assert set(hypotheses.APART) <= set(p.evidence), "the three the card shows apart"
        assert len(p.evidence["group"]) <= hypotheses.MAX_CHIP and "x" * (ps.LABEL_CHARS + 1) not in p.title + p.hypothesis + p.evidence["group"]


def test_a_decision_with_no_calibrator_is_named_for_the_owner_and_keyed_by_what_it_is() -> None:
    report = ps.search(two_groups_of_rows_that_overlap(), metrics=("clv",), dimensions=("calibration_role",))
    [none] = [f for f in report["found"] if f["value"] == "none"]
    assert none["label"] == "ninguno (sin calibrar)", "the report names it the way the owner reads it; the value stays what the database says"
    [p] = ps.proposals({**one_report(), "found": [{**one_report()["found"][0], "dimension": "calibration_role", "value": "none", "label": none["label"]}]})
    assert p.title.startswith("Calibrador ninguno (sin calibrar): ") and p.evidence["group"] == "Calibrador: ninguno (sin calibrar)"
    assert p.key == "pattern2:calibration:calibration_role:none:down", "the key is the value, so that it does not change if the words do"
    given = ps.search(two_groups_of_rows_that_overlap(), metrics=("clv",), dimensions=("calibration_role",), labels={("calibration_role", "none"): "x"})
    assert [f["label"] for f in given["found"] if f["value"] == "none"] == ["x"], "a name that is given wins over the one the module has"


def test_two_searches_that_see_the_same_group_propose_it_once() -> None:
    assert ps.proposals(one_report())[0].key == ps.proposals(one_report(z=-3.9, delta=-0.05))[0].key
    assert ps.proposals(one_report())[0].key != ps.proposals(one_report(delta=0.04))[0].key, "the other direction is another question"


def triaged(**per_finding: Any) -> dict[str, Any]:
    """A report whose findings are the given changes to the one of ``one_report``, in the order given (the largest ``z`` first)."""
    base = one_report()["found"][0]
    return {**one_report(), "found": [{**base, **changes} for changes in per_finding.values()]}


def test_what_repeats_is_proposed_unless_it_only_describes_the_price_or_a_larger_finding_says_it_already() -> None:
    report = triaged(
        a={"value": "a", "label": "A", "z": -6.0, "descriptive": True},
        b={"value": "b", "dimension": "market", "z": -5.0, "stable": False},
        c={"value": "c", "dimension": "model", "z": -4.5},
        d={"value": "d", "dimension": "model", "z": 4.1, "delta": 0.05},
        e={"value": "e", "dimension": "model", "metric": "vs_close", "z": -3.9},
        f={"value": "f", "dimension": "referee", "z": -3.5, "overlaps": [2]},
        g={"value": "g", "dimension": "coach", "z": -3.4, "overlaps": [5]})
    chosen, left = ps.triage(report)
    assert [f["value"] for f in chosen] == ["c", "e", "g"]
    assert [(f["value"], why) for f, why in left] == [
        ("a", "descriptive: how the price is built"),
        ("d", "a larger finding in the same dimension says it already"),
        ("f", "shares most of its rows with a larger finding")], "b does not repeat: it is not a candidate and is not listed; g overlaps only with f, which was not proposed"
    assert [p.key for p in ps.proposals(report)] == ["pattern2:calibration:model:c:down", "pattern2:vs_close:model:e:down", "pattern2:calibration:coach:g:down"]


def test_a_search_proposes_at_most_the_limit_and_says_which_it_left_for_that() -> None:
    report = triaged(**{f"k{i}": {"value": f"k{i}", "dimension": ps.DIMENSIONS[i], "z": -(5.0 - i / 10)} for i in range(7)})
    chosen, left = ps.triage(report, limit=5)
    assert len(chosen) == 5 and [(f["value"], why) for f, why in left] == [("k5", "beyond the 5 proposals of a search"), ("k6", "beyond the 5 proposals of a search")]
    assert len(ps.proposals(report, limit=3)) == 3 and len(ps.triage(report, limit=3)[1]) == 4


# ── the weekly job ───────────────────────────────────────────────────────────────────────────────────────────────

class Untouched:
    """A connection that fails at the first touch: what proves that a step with its switch off reads nothing."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the connection was used ({name})")


def switch(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(ps, "environment", lambda: {} if value is None else {ps.SWITCH: value})


def test_the_weekly_step_is_off_unless_the_switch_says_otherwise_and_off_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    switch(monkeypatch, None)
    assert ps.mode() == "off" and ps.weekly(Untouched(), at=T0) == {"mode": "off"}  # type: ignore[arg-type]
    for value in ("off", "", " ", "yes", "1", "true", "on", "reports", "proposed"):
        switch(monkeypatch, value)
        assert ps.mode() == "off", f"{value!r} is not a setting: the search does not run"
    for value, want in (("report", "report"), (" Report ", "report"), ("PROPOSE", "propose"), ("propose", "propose")):
        switch(monkeypatch, value)
        assert ps.mode() == want
    assert ps.MODES == ("off", "report", "propose")


def test_the_summary_the_weekly_run_keeps_is_small_and_says_what_was_read_asked_and_found() -> None:
    base = one_report()["found"][0]
    found = [{**base, "value": str(i), "label": f"Group {i}", "z": -(3.0 + i), "stable": [True, False, None][i % 3], "survives_correction": i < 2} for i in range(7)]
    report = {"version": ps.VERSION, "rows": {"decisions": 9540, "matches": 921}, "tests": 180, "expected_by_chance": 0.5949, "found": found}
    got = ps.summary(report)
    assert {k: v for k, v in got.items() if k != "top"} == {"version": ps.VERSION, "decisions": 9540, "matches": 921, "tests": 180, "expected_by_chance": 0.6,
                                                             "found": 7, "descriptive": 0, "repeating": 3, "survive_correction": 2}
    assert len(got["top"]) == ps.TOP == 5 and got["top"][0] == {"measure": "calibration", "dimension": "competition", "group": "Group 0", "z": -3.0,
                                                                  "repeats": True}
    assert ps.summary({**report, "found": [{**base, "label": "x" * 300}]})["top"][0]["group"] == "x" * ps.LABEL_CHARS
    mixed = ps.summary({**report, "found": [{**base, "label": "price", "z": -9.0, "descriptive": True}, *found[:2]]})
    assert (mixed["found"], mixed["descriptive"], mixed["repeating"]) == (3, 1, 1) and [t["group"] for t in mixed["top"]] == ["Group 0", "Group 1"], (
        "what only describes the price is counted, and is not among the largest findings the record keeps")


def test_the_weekly_job_ends_with_the_search_for_patterns_which_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.intel import cycle

    seen: dict[str, Any] = {}

    def fake(conn: Any, job: str, at: datetime, steps: Any) -> cycle.RunReport:
        seen.update(job=job, steps=steps)
        return cycle.RunReport()

    monkeypatch.setattr(cycle, "_run", fake)
    switch(monkeypatch, None)
    cycle.run_weekly(Untouched(), at=T0)  # type: ignore[arg-type]
    assert seen["job"] == "weekly" and [name for name, _ in seen["steps"]] == ["catalogue", "discovery", "learning_analyst", "matrix", "patterns"]
    assert dict(seen["steps"])["patterns"]() == {"mode": "off"}, "off: the step does nothing, and it does not fail the run"
