"""Plan F12.5 - a variant of a family against the market: what each piece does (worked by hand), that nothing it uses is a future of the week it states,
and that on a world where the family's level is off and the market is exact the correction wins and the family as it is loses.

The database half (the history, the prices, the command) is in ``tests/integration/test_families_variants.py``."""

from __future__ import annotations

import dataclasses
import json
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import psycopg
import pytest
from scripts import families as cli

from fbi.families import bets, forecast, score, variants, versus
from fbi.families.evaluate import Row
from fbi.families.fit import OUTCOME_KNOWN_AFTER, Dispersion, estimate_dispersion, prediction
from fbi.families.variants import AS_IS, Variant

D = Decimal
T0 = datetime(2035, 1, 1, tzinfo=UTC)
CATALOGUE = frozenset({"CORNERS_OU", "CORNERS_OU_HOME", "CORNERS_OU_AWAY", "CORNERS_1X2", "CORNERS_DC"})
SPEC = variants.spec_of("corners_ft")
Truth = dict[int, tuple[float, float]]
"""The true means of each match, by fixture: (home, away)."""


def row(fixture: int, kickoff: datetime, y_home: int = 5, y_away: int = 4, mu_home: float = 5.0, mu_away: float = 4.0) -> Row:
    return Row(fixture, 1, kickoff, y_home, y_away, mu_home, mu_away, mu_home, mu_away)


# ── the variants ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_variant_is_the_family_as_it_is_or_a_recent_level_of_some_days() -> None:
    assert variants.parse("as-is") == Variant(AS_IS, 0) and variants.parse("AS-IS ") == Variant(AS_IS, 0)
    assert variants.parse("recent-level:28") == Variant("recent-level:28", 28)
    assert variants.parse("Recent-Level:07") == Variant("recent-level:7", 7), "the name is the canonical one"
    assert variants.LEVEL_DAYS == 28 and variants.MIN_LEVEL_DAYS <= variants.LEVEL_DAYS <= variants.MAX_LEVEL_DAYS
    assert (variants.MIN_LEVEL_DAYS, variants.MAX_LEVEL_DAYS) == (7, 365)
    assert variants.parse("recent-level:7").level_days == 7 and variants.parse("recent-level:365").level_days == 365, "both ends of the range are in"
    for bad in ("", "recent-level", "recent-level:", "recent-level:x", "recent-level:6", "recent-level:366", "recent-level:-28", "recent-level:\N{SUPERSCRIPT TWO}",
                "blend:28", "as-is:28"):
        with pytest.raises(ValueError, match="is not a variant"):
            variants.parse(bad)


def test_the_family_as_it_is_always_comes_first_and_every_variant_once() -> None:
    assert variants.variants_of([]) == [Variant(AS_IS)]
    got = variants.variants_of(["recent-level:28", "as-is", "recent-level:56", "recent-level:28"])
    assert [v.name for v in got] == ["as-is", "recent-level:28", "recent-level:56"]


def test_only_the_families_fitted_on_one_count_that_the_books_quote_can_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sorted(variants.specs()) == ["cards_lines_ft", "corners_ft", "yellow_ft"]
    plain = dataclasses.replace(SPEC, key="plain_corners", over_dispersed=False)
    two = dataclasses.replace(SPEC, key="two_counts", measures=("corners_ft", "yellow_ft"))
    monkeypatch.setattr(forecast, "SPECS", (*forecast.SPECS, plain, two))
    assert sorted(variants.specs()) == ["cards_lines_ft", "corners_ft", "yellow_ft"], "one that is not over-dispersed, or fitted on two counts, states other markets"
    assert variants.spec_of("cards_lines_ft").referee_kappa == 150.0
    with pytest.raises(variants.NotAFamilyError, match="goals_halves"):
        variants.spec_of("goals_halves")


# ── the weeks ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_window_starts_the_walk_forward_early_enough_and_on_a_block_boundary() -> None:
    start, end = T0 + timedelta(days=200), T0 + timedelta(days=228)
    window = variants.plan(start, end, step_days=7, burn_in_days=88)
    assert window.start == start and window.end == end
    assert start - window.first >= timedelta(days=88), "the first block still has its dispersion and its correction behind it"
    assert (start - window.first) % timedelta(days=7) == timedelta(0), "the compared kick-offs begin where a block begins"
    assert variants.block_start(start, window) == start
    assert variants.block_start(start + timedelta(days=6, hours=23), window) == start
    assert variants.block_start(start + timedelta(days=7), window) == start + timedelta(days=7)
    assert variants.block_start(window.first, window) == window.first
    for bad in ((end, start), (start, start)):
        with pytest.raises(ValueError, match="empty"):
            variants.plan(*bad, step_days=7, burn_in_days=0)
    with pytest.raises(ValueError, match="a day"):
        variants.plan(start, end, step_days=0, burn_in_days=0)


def test_the_first_block_has_the_history_it_needs_behind_it_whatever_the_step_and_the_memory() -> None:
    start, end = T0 + timedelta(days=300), T0 + timedelta(days=330)
    for step in (1, 3, 7, 10, 14):
        for burn_in in (0, 1, 6, 7, 8, 28, 88, 148, 365):
            window = variants.plan(start, end, step_days=step, burn_in_days=burn_in)
            behind = start - window.first
            assert behind % timedelta(days=step) == timedelta(0), f"step {step}, burn-in {burn_in}: the compared kick-offs begin where a block begins"
            assert timedelta(days=burn_in + step) <= behind < timedelta(days=burn_in + 2 * step), (
                f"step {step}, burn-in {burn_in}: the burn-in and one block more (the one the first day of the memory falls in), and no more")
    assert variants.plan(start, end, step_days=7, burn_in_days=-10).first == start - timedelta(days=7), "a negative memory is none"


def test_a_correction_counts_only_the_matches_known_at_the_start_of_the_block_in_its_days() -> None:
    at = T0 + timedelta(days=100)
    # 220 matches in the 28 days before, observed 20 % above what was predicted at home and 10 % below away
    inside = [row(i, at - timedelta(days=1 + i % 27, hours=8), y_home=6, y_away=4, mu_home=5.0, mu_away=4.4444444444) for i in range(220)]
    on_the_edge = row(1001, at - OUTCOME_KNOWN_AFTER, y_home=60, y_away=60)
    too_late = row(1002, at - OUTCOME_KNOWN_AFTER + timedelta(minutes=1), y_home=60, y_away=60)
    after = row(1003, at + timedelta(days=1), y_home=60, y_away=60)
    too_old = row(1004, at - timedelta(days=28, minutes=1), y_home=60, y_away=60)
    level = variants.level_at([*inside, too_late, after, too_old], at=at, days=28)
    assert level is not None and level.matches == 220 and level.at == at
    assert level.home == pytest.approx(1.2) and level.away == pytest.approx(0.9)
    # a match whose result becomes known exactly at the start of the block counts; one minute later it does not
    edge = variants.level_at([*inside, on_the_edge], at=at, days=28)
    assert edge is not None and edge.matches == 221 and edge.home > 1.2
    assert variants.known(on_the_edge) == at
    # the day the window begins counts, the minute before does not
    first_day = row(1005, at - timedelta(days=28), y_home=60, y_away=60)
    with_first_day = variants.level_at([*inside, first_day], at=at, days=28)
    with_too_old = variants.level_at([*inside, too_old], at=at, days=28)
    assert with_first_day is not None and with_first_day.matches == 221, "the first day of the window counts"
    assert with_too_old is not None and with_too_old.matches == 220, "the minute before it does not"


def test_with_fewer_matches_than_the_minimum_the_block_is_left_as_the_family_states_it() -> None:
    at = T0 + timedelta(days=100)
    few = [row(i, at - timedelta(days=2, hours=i % 12)) for i in range(variants.MIN_PAST - 1)]
    assert variants.level_at(few, at=at, days=28) is None
    assert variants.level_at([*few, row(999, at - timedelta(days=3))], at=at, days=28) is not None
    nothing = [row(i, at - timedelta(days=2), mu_home=0.0) for i in range(variants.MIN_PAST)]
    assert variants.level_at(nothing, at=at, days=28) is None, "no ratio of something to nothing"


def level_world(shift: float = 1.2) -> tuple[list[Row], variants.Window]:
    rows = [row(day * 10 + k + 1, T0 + timedelta(days=day, hours=12 + k), y_home=round(5 * shift), y_away=round(4 * shift)) for day in range(120) for k in range(10)]
    return rows, variants.plan(T0 + timedelta(days=90), T0 + timedelta(days=110), step_days=7, burn_in_days=28)


def test_the_corrected_means_are_the_familys_times_what_was_observed_over_what_it_predicted() -> None:
    rows, window = level_world(1.2)
    same, levels = variants.corrected(rows, Variant(AS_IS), window)
    assert same == rows and levels == {}
    fixed, levels = variants.corrected(rows, Variant("recent-level:28", 28), window)
    assert len(fixed) == len(rows) and [r.fixture_id for r in fixed] == [r.fixture_id for r in rows]
    for before, after in zip(rows, fixed, strict=True):
        level = levels[variants.block_start(before.kickoff_at, window)]
        if level is None:
            assert after == before, "a block with too little behind it is left as the family states it"
            continue
        assert (after.mu_home, after.mu_away) == (before.mu_home * level.home, before.mu_away * level.away)
        assert (after.y_home, after.y_away, after.base_home, after.fixture_id) == (before.y_home, before.y_away, before.base_home, before.fixture_id)
    deep = levels[window.start]
    assert deep is not None and deep.home == pytest.approx(6 / 5) and deep.away == pytest.approx(5 / 4), "observed 6 and 5 where it predicted 5 and 4"
    assert deep.matches == 27 * 10 + 7, "the 27 whole days of the 28 and the 7 matches of the last one that were known (kick-off at 18:00 or before)"
    longer = variants.corrected(rows, Variant("recent-level:35", 35), window)[1][window.start]
    assert longer is not None and longer.matches == 34 * 10 + 7, "the memory asked for, not another"
    first_block = variants.block_start(rows[0].kickoff_at, window)
    assert levels[first_block] is None, "the first block has nothing behind it"
    assert fixed[0] == rows[0], "and is left as the family states it"


def test_the_ratio_is_that_of_the_familys_own_predictions_not_of_the_corrected_ones() -> None:
    """A correction measured on corrected means would chase itself: the second week would see the first week's fix and undo it."""
    rows, window = level_world(1.2)
    _, levels = variants.corrected(rows, Variant("recent-level:28", 28), window)
    ratios = {round(lv.home, 9) for lv in levels.values() if lv is not None}
    assert ratios == {round(6 / 5, 9)}, "the same family, the same shift: the same correction every week"


def test_the_dispersion_is_measured_on_the_known_matches_of_the_days_before_the_block() -> None:
    at = T0 + timedelta(days=100)
    rng = np.random.default_rng(3)
    past = [row(i, at - timedelta(days=1 + i % 59, hours=7), y_home=int(rng.poisson(6)), y_away=int(rng.poisson(5)), mu_home=5.5, mu_away=4.5) for i in range(300)]
    spread = variants.spread_at(past, at=at, days=60, minimum=250)
    assert spread is not None and spread.matches == 300 and spread.at == at
    want = estimate_dispersion([r.y_home for r in past], [r.mu_home for r in past], [r.y_away for r in past], [r.mu_away for r in past])
    assert spread.dispersion == want
    assert variants.spread_at(past, at=at, days=60, minimum=300) == spread, "exactly the minimum is enough"
    assert variants.spread_at(past, at=at, days=60, minimum=301) is None, "a family states nothing it cannot measure"
    unknown = row(900, at - timedelta(hours=5), y_home=99, y_away=99)
    assert variants.spread_at([*past, unknown], at=at, days=60, minimum=250) == spread, "a match not yet known is not a measurement"
    first_day = row(901, at - timedelta(days=60), y_home=40, y_away=40)
    too_old = row(902, at - timedelta(days=60, minutes=1), y_home=40, y_away=40)
    with_first_day = variants.spread_at([*past, first_day], at=at, days=60, minimum=250)
    assert with_first_day is not None and with_first_day.matches == 301 and with_first_day.dispersion != spread.dispersion, "the first day of the window counts"
    assert variants.spread_at([*past, too_old], at=at, days=60, minimum=250) == spread, "the minute before it does not"
    assert variants.spread_at(past, at=at, days=10, minimum=100) is None, "only the days asked for count"
    short = variants.spread_at(past, at=at, days=10, minimum=40)
    assert short is not None and short.matches < 300 and short.dispersion != spread.dispersion


# ── what a variant states ────────────────────────────────────────────────────────────────────────────────────────

def nb_draw(rng: np.random.Generator, mean: float, alpha: float) -> int:
    return int(rng.negative_binomial(1.0 / alpha, 1.0 / (1.0 + alpha * mean)))


def world(*, days: int = 230, per_day: int = 12, shift: float = 1.35, alpha: float = 0.1, seed: int = 7) -> tuple[list[Row], Truth]:
    """Matches of every day: the family's means are the truth divided by ``shift`` (its level is off), the counts come from the truth."""
    rng = np.random.default_rng(seed)
    rows: list[Row] = []
    truth: Truth = {}
    for day in range(days):
        for k in range(per_day):
            fixture = day * per_day + k + 1
            true_home, true_away = (5.2 + 0.4 * (k % 4)) * shift, (4.4 + 0.3 * (k % 3)) * shift
            kickoff = T0 + timedelta(days=day, hours=11 + (k % 9))
            rows.append(Row(fixture, 1, kickoff, nb_draw(rng, true_home, alpha), nb_draw(rng, true_away, alpha), true_home / shift, true_away / shift,
                            true_home / shift, true_away / shift))
            truth[fixture] = (true_home, true_away)
    return rows, truth


WINDOW = variants.plan(T0 + timedelta(days=200), T0 + timedelta(days=228), step_days=7, burn_in_days=60 + 28)
TUNING = {"dispersion_days": 60, "min_dispersion": 40}


def stated(rows: list[Row], variant: Variant) -> variants.Forecasts:
    return variants.forecasts(rows, variant, SPEC, available=CATALOGUE, window=WINDOW, **TUNING)


def probabilities(f: variants.Forecasts) -> dict[tuple[int, str, Decimal, str], float]:
    return {(r.fixture_id, r.key, r.line, r.selection): r.p for r in f.rows}


def test_a_variant_states_the_markets_the_books_quote_and_each_market_adds_up_to_one() -> None:
    rows, _ = world(days=230)
    f = stated(rows, Variant("recent-level:28", 28))
    in_window = [r for r in rows if WINDOW.start <= r.kickoff_at < WINDOW.end]
    assert f.matches == len(in_window) and f.without_spread == 0 and f.corrected_matches == len(in_window)
    assert {r.model for r in f.rows} == {"recent-level:28"}, "the name of the variant is the name of the model"
    assert {r.key for r in f.rows} == {"CORNERS_OU", "CORNERS_OU_HOME", "CORNERS_OU_AWAY", "CORNERS_1X2"}, "double chance has no consensus to be set against"
    assert {(r.key, r.line) for r in f.rows if r.key == "CORNERS_OU"} == {("CORNERS_OU", D(str(x))) for x in (8.5, 9.5, 10.5, 11.5, 12.5)}
    by_market: dict[tuple[int, str, Decimal], float] = defaultdict(float)
    for r in f.rows:
        by_market[(r.fixture_id, r.key, r.line)] += r.p
    assert all(total == pytest.approx(1.0) for total in by_market.values())
    kickoff = {x.fixture_id: x.kickoff_at for x in in_window}
    for r in f.rows:
        assert r.known_at == variants.block_start(kickoff[r.fixture_id], WINDOW) and r.known_at <= kickoff[r.fixture_id], "stated at the start of its week"


def test_the_family_as_it_is_states_the_means_of_the_walk_forward_untouched() -> None:
    rows, _ = world(days=230)
    f = stated(rows, Variant(AS_IS))
    assert f.corrected_matches == 0 and f.levels == {}
    sample = next(r for r in rows if r.kickoff_at >= WINDOW.start)
    at = variants.block_start(sample.kickoff_at, WINDOW)
    spread = variants.spread_at(rows, at=at, days=60, minimum=40)
    assert spread is not None
    want = prediction(sample.mu_home, sample.mu_away, spread.dispersion)
    over = next(r.p for r in f.rows if r.fixture_id == sample.fixture_id and r.key == "CORNERS_OU" and r.line == D("9.5") and r.selection == "Over")
    assert over == pytest.approx(float(want.pmf_total[10:].sum()))


def test_a_block_without_enough_matches_to_measure_the_dispersion_states_nothing() -> None:
    rows, _ = world(days=230)
    f = variants.forecasts(rows, Variant(AS_IS), SPEC, available=CATALOGUE, window=WINDOW, dispersion_days=60, min_dispersion=10_000)
    assert f.rows == [] and f.without_spread == f.matches > 0


def test_the_first_blocks_of_a_short_history_are_stated_as_the_family_does_and_are_not_counted_as_corrected() -> None:
    rows, _ = world(days=230)
    short = variants.plan(WINDOW.start, WINDOW.end, step_days=7, burn_in_days=0)
    assert WINDOW.start - short.first == timedelta(days=7)
    base = [r for r in rows if r.kickoff_at >= short.first]  # what the walk-forward gives: nothing before its first block
    tuning = {"dispersion_days": 7, "min_dispersion": 40}
    own = variants.forecasts(base, Variant(AS_IS), SPEC, available=CATALOGUE, window=short, **tuning)
    fixed = variants.forecasts(base, Variant("recent-level:28", 28), SPEC, available=CATALOGUE, window=short, **tuning)
    blocks = [short.start + timedelta(days=7 * i) for i in range(4)]
    assert fixed.matches == own.matches == 336 and fixed.without_spread == 0
    assert [fixed.levels[b] is not None for b in blocks] == [False, False, True, True], "200 matches behind it, or the block is left alone"
    assert [lv.matches for lv in (fixed.levels[blocks[2]], fixed.levels[blocks[3]]) if lv is not None] == [251, 335], "the days it has, no more"
    assert fixed.corrected_matches == 168, "only the matches of the two blocks that were corrected are counted as such"
    before, after = probabilities(own), probabilities(fixed)
    starts = {r.fixture_id: variants.block_start(r.kickoff_at, short) for r in base}
    assert before.keys() == after.keys()
    assert all(before[k] == after[k] for k in before if starts[k[0]] in blocks[:2]), "a block with too little behind it is the family's, to the digit"
    assert all(before[k] != after[k] for k in before if starts[k[0]] in blocks[2:] and k[1] == "CORNERS_OU" and k[3] == "Over"), "the others are not"


def test_the_window_includes_its_first_instant_and_excludes_its_last() -> None:
    rows, _ = world(days=230)
    edges = [row(900_001, WINDOW.start - timedelta(minutes=1)), row(900_002, WINDOW.start), row(900_003, WINDOW.end - timedelta(minutes=1)),
             row(900_004, WINDOW.end)]
    inside = sum(1 for r in rows if WINDOW.start <= r.kickoff_at < WINDOW.end)
    for variant in (Variant(AS_IS), Variant("recent-level:28", 28)):
        f = stated([*rows, *edges], variant)
        said = {r.fixture_id for r in f.rows}
        assert {900_002, 900_003} <= said and not {900_001, 900_004} & said, variant.name
        assert f.matches == inside + 2, variant.name


def replace_outcome(r: Row) -> Row:
    return Row(r.fixture_id, r.competition_id, r.kickoff_at, r.y_home + 9, r.y_away + 9, r.mu_home, r.mu_away, r.base_home, r.base_away, r.with_referee)


def test_no_number_of_a_week_changes_when_what_happens_from_that_week_on_does() -> None:
    """The point of the reading: everything a block states was known when it began. Change the outcomes of every match whose result is not known by
    the start of the second block (and the ones before) and the forecasts of the first two blocks must be identical; the later ones, which did
    see those matches, must differ."""
    rows, _ = world(days=230)
    t = WINDOW.start + timedelta(days=7)
    changed = [replace_outcome(r) if variants.known(r) > t else r for r in rows]
    assert sum(1 for a, b in zip(rows, changed, strict=True) if a != b) > 100
    for variant in (Variant(AS_IS), Variant("recent-level:28", 28)):
        before, after = probabilities(stated(rows, variant)), probabilities(stated(changed, variant))
        assert before.keys() == after.keys()
        starts = {r.fixture_id: variants.block_start(r.kickoff_at, WINDOW) for r in rows}
        same = [k for k in before if starts[k[0]] <= t]
        later = [k for k in before if starts[k[0]] > t]
        assert same and later
        assert all(before[k] == after[k] for k in same), f"{variant.name}: a forecast of the block of {t.date()} or before moved with later results"
        assert any(abs(before[k] - after[k]) > 1e-9 for k in later), f"{variant.name}: the later blocks do use the matches that were played"


# ── the reading ──────────────────────────────────────────────────────────────────────────────────────────────────

def pair(fixture: int, p_model: float, p_market: float, won: int, *, key: str = "CORNERS_OU", line: str = "9.5", selection: str = "Over",
         ref: str = "close") -> versus.Pair:
    return versus.Pair("m", ref, key, fixture, p_model, p_market, won, 5, D(line), selection)


def test_the_main_line_of_a_match_is_the_one_the_market_gives_closest_to_one_in_two() -> None:
    pairs = [
        pair(1, 0.7, 0.62, 1, line="8.5"), pair(1, 0.5, 0.48, 0, line="9.5"), pair(1, 0.3, 0.33, 0, line="10.5"),
        pair(1, 0.3, 0.38, 1, line="9.5", selection="Under"),
        pair(2, 0.9, 0.97, 1, line="9.5"), pair(2, 0.8, 0.90, 1, line="10.5"),                   # 0.97 is outside the band: 10.5 is the main line
        pair(3, 0.5, 0.25, 1, line="9.5"), pair(3, 0.5, 0.75, 0, line="10.5"),                   # a tie: the lower line
        pair(4, 0.5, 0.5, 1, line="9.5", ref="h24"), pair(4, 0.6, 0.4, 1, line="10.5", ref="h24"),
        pair(5, 0.5, 0.4, 1, key="CORNERS_OU_HOME", line="4.5"), pair(5, 0.5, 0.5, 0, key="CORNERS_OU_HOME", line="5.5"),
        pair(5, 0.5, 0.45, 1, key="CORNERS_OU_AWAY", line="3.5"),
        pair(6, 0.5, 0.4, 1, key="CORNERS_1X2", line="0", selection="Home"), pair(6, 0.3, 0.3, 0, key="CORNERS_1X2", line="0", selection="Draw"),
        pair(6, 0.2, 0.3, 0, key="CORNERS_1X2", line="0", selection="Away"),
    ]
    groups = variants.groups_of(pairs)
    main = {k: sorted((p.fixture_id, str(p.line)) for p in v) for k, v in groups.items() if k[2] == variants.MAIN}
    assert main == {("close", "total", "main"): [(1, "9.5"), (2, "10.5"), (3, "9.5")], ("h24", "total", "main"): [(4, "9.5")],
                    ("close", "home", "main"): [(5, "5.5")], ("close", "away", "main"): [(5, "3.5")]}
    every = {k: sorted((p.fixture_id, str(p.line)) for p in v) for k, v in groups.items() if k[2] == variants.ALL}
    assert every[("close", "total", "all")] == [(1, "10.5"), (1, "8.5"), (1, "9.5"), (2, "10.5"), (2, "9.5"), (3, "10.5"), (3, "9.5")]
    assert every[("h24", "total", "all")] == [(4, "10.5"), (4, "9.5")] and every[("close", "home", "all")] == [(5, "4.5"), (5, "5.5")]
    assert [p.selection for p in groups[("close", "result", "all")]] == ["Home", "Draw", "Away"], "who has more: the three outcomes, every one a row"
    assert all(p.selection in ("Over", "Home", "Draw", "Away") for v in groups.values() for p in v), "the Under is the Over's complement and is left out"
    assert ("close", "result", "main") not in groups


def test_the_main_line_does_not_depend_on_the_model() -> None:
    """Two variants state different probabilities for the same rows; the line each is read at is the market's choice, the same for both."""
    a = [pair(1, 0.9, 0.62, 1, line="8.5"), pair(1, 0.1, 0.49, 0, line="9.5")]
    b = [pair(1, 0.1, 0.62, 1, line="8.5"), pair(1, 0.9, 0.49, 0, line="9.5")]
    def pick(pairs: list[versus.Pair]) -> list[str]:
        return [str(p.line) for p in variants.groups_of(pairs)[("close", "total", "main")]]

    assert pick(a) == pick(b) == ["9.5"]


def test_the_numbers_of_the_design_are_the_ones_the_guide_says() -> None:
    assert (variants.MIN_PAST, variants.STEP_DAYS, variants.DISPERSION_DAYS, variants.MIN_SIGNAL) == (200, 7, 120, 30)
    assert variants.MAIN_BAND == (0.08, 0.92) and variants.VERSION == "variants-v1"


def test_the_main_line_is_one_the_market_gives_inside_the_band_edges_included_and_a_match_with_none_has_no_main_line() -> None:
    lo, hi = variants.MAIN_BAND
    pairs = [pair(1, 0.5, lo, 0, line="9.5"), pair(2, 0.5, hi, 1, line="9.5"), pair(3, 0.5, lo - 0.001, 0, line="9.5"),
             pair(4, 0.5, hi + 0.001, 1, line="9.5"), pair(5, 0.5, 0.97, 1, line="8.5"), pair(5, 0.5, 0.03, 0, line="12.5")]
    groups = variants.groups_of(pairs)
    assert sorted(p.fixture_id for p in groups[("close", "total", "main")]) == [1, 2], "the band is closed at both ends; outside it a line says nothing"
    assert sorted(p.fixture_id for p in groups[("close", "total", "all")]) == [1, 2, 3, 4, 5, 5], "but every line counts in the other reading"
    assert variants.groups_of([pair(6, 0.5, 0.99, 1)]).get(("close", "total", "main")) is None


def simulated(n: int, weight: float, seed: int, *, copies: int = 1) -> list[versus.Pair]:
    """Rows where what happens is the market's logit moved ``weight`` of the way to the model's."""
    rng = np.random.default_rng(seed)
    p_market = rng.uniform(0.25, 0.75, n)
    p_model = np.clip(p_market + rng.normal(0.0, 0.08, n), 0.05, 0.95)
    z = np.log(p_market / (1 - p_market)) + weight * (np.log(p_model / (1 - p_model)) - np.log(p_market / (1 - p_market)))
    won = rng.random(n) < 1.0 / (1.0 + np.exp(-z))
    return [pair(i, float(p_model[i]), float(p_market[i]), int(won[i])) for i in range(n) for _ in range(copies)]


def test_the_extra_signal_is_zero_when_the_model_adds_nothing_and_its_weight_when_it_does() -> None:
    nothing = variants.extra_signal(simulated(4000, 0.0, 11))
    assert nothing is not None and abs(nothing["coef"]) < 3 * nothing["se"] and 0.05 < nothing["se"] < 0.2
    assert nothing["se"] > 1.3 * nothing["market_slope_se"], "the model's gap to the market varies less than the market does, so it is measured with less precision"
    assert abs(nothing["market_slope"] - 1.0) < 3 * nothing["market_slope_se"], "the market is calibrated: it keeps its weight"
    half = variants.extra_signal(simulated(4000, 0.5, 12))
    assert half is not None and abs(half["coef"] - 0.5) < 3 * half["se"] and half["coef"] > 3 * half["se"]
    assert abs(half["market_slope"] - 1.0) < 3 * half["market_slope_se"], "the model's weight is on top of the market's, which keeps its own"
    full = variants.extra_signal(simulated(4000, 1.0, 13))
    assert full is not None and abs(full["coef"] - 1.0) < 3 * full["se"]


def test_the_standard_error_of_the_extra_signal_is_clustered_by_match() -> None:
    """The same rows said twice are the same observation of how right the model was: the error of the estimate must not shrink."""
    once = variants.extra_signal(simulated(1500, 0.3, 21))
    twice = variants.extra_signal(simulated(1500, 0.3, 21, copies=2))
    assert once is not None and twice is not None
    assert twice["coef"] == pytest.approx(once["coef"], abs=1e-6) and twice["se"] == pytest.approx(once["se"], rel=1e-6)


def test_the_extra_signal_needs_rows_and_both_outcomes() -> None:
    assert variants.extra_signal(simulated(variants.MIN_SIGNAL - 1, 0.5, 5)) is None
    assert variants.extra_signal(simulated(variants.MIN_SIGNAL, 0.5, 5)) is not None, "exactly the minimum is enough"
    all_won = [pair(i, 0.5 + (i % 7) / 50, 0.5, 1) for i in range(100)]
    assert variants.extra_signal(all_won) is None


def test_a_variant_against_the_family_is_the_log_loss_it_saves_on_the_same_rows_by_match() -> None:
    reference = [pair(1, 0.6, 0.5, 1), pair(1, 0.5, 0.5, 1, line="10.5"), pair(2, 0.6, 0.5, 0), pair(3, 0.6, 0.5, 1)]
    other = [pair(1, 0.7, 0.5, 1), pair(1, 0.6, 0.5, 1, line="10.5"), pair(2, 0.5, 0.5, 0), pair(3, 0.6, 0.5, 1), pair(9, 0.9, 0.5, 1)]
    got = variants.paired(reference, other)
    saved = [math.log(0.7 / 0.6), math.log(0.6 / 0.5), math.log((1 - 0.5) / (1 - 0.6)), 0.0]
    mean = sum(saved) / 4
    per_match = {1: saved[0] + saved[1] - 2 * mean, 2: saved[2] - mean, 3: saved[3] - mean}
    assert got["n"] == 4 and got["fixtures"] == 3, "the row of the match the reference does not have is not compared"
    assert got["gain"] == pytest.approx(mean) and got["gain"] > 0
    assert got["se"] == pytest.approx(math.sqrt(sum(v * v for v in per_match.values())) / 4)
    swapped = variants.paired(other, reference)
    assert swapped["gain"] == pytest.approx(-mean) and swapped["n"] == 4
    assert variants.paired(reference, [pair(7, 0.5, 0.5, 1)]) == {"n": 0, "fixtures": 0, "gain": None, "se": None}
    # the three outcomes of a 1X2 are three rows of one market, each compared with its own
    outcomes = {"Home": (0.5, 0.6, 1), "Draw": (0.3, 0.25, 0), "Away": (0.2, 0.15, 0)}
    said_by_the_family = [pair(1, before, 0.3, won, key="CORNERS_1X2", line="0", selection=name) for name, (before, _, won) in outcomes.items()]
    said_by_the_variant = [pair(1, after, 0.3, won, key="CORNERS_1X2", line="0", selection=name) for name, (_, after, won) in outcomes.items()]
    gain = variants.paired(said_by_the_family, said_by_the_variant)
    want = [math.log(0.6 / 0.5), math.log(0.75 / 0.7), math.log(0.85 / 0.8)]
    assert gain["n"] == 3 and gain["fixtures"] == 1 and gain["gain"] == pytest.approx(sum(want) / 3)


def test_a_bet_is_taken_only_on_a_forecast_stated_a_day_before_the_kick_off() -> None:
    start = T0 + timedelta(days=5)
    kickoffs = {1: start + timedelta(hours=24), 2: start + timedelta(hours=23, minutes=59), 3: start + timedelta(days=6)}
    graded = [score.Graded(score.Row(f, "m", "CORNERS_OU", D("9.5"), "Over", 0.5, start), 1) for f in (1, 2, 3)]
    assert [g.row.fixture_id for g in variants.early(graded, kickoffs)] == [1, 3]
    assert timedelta(hours=24) == bets.PICK_LEAD


# ── the whole reading on a world with a known answer ─────────────────────────────────────────────────────────────

def market_of(truth: Truth, rows: list[Row]) -> tuple[dict[versus.FairKey, tuple[float, int]], dict[versus.FairKey, tuple[float, int]]]:
    """A market that knows the truth exactly: the exact distribution of each match, the same at both moments, five books, no margin."""
    fair: dict[versus.FairKey, tuple[float, int]] = {}
    best: dict[versus.FairKey, tuple[float, int]] = {}
    for r in rows:
        if not WINDOW.start <= r.kickoff_at < WINDOW.end:
            continue
        home, away = truth[r.fixture_id]
        exact = prediction(home, away, Dispersion(0.1, 0.1, 0.0))
        for probs in SPEC.build([exact], CATALOGUE):
            if probs.market_key == "CORNERS_DC":
                continue
            for selection, p in probs.outcomes:
                for ref, _ in versus.REFERENCES:
                    key = (ref, r.fixture_id, probs.market_key, D(str(probs.line)), selection)
                    fair[key] = (p, 5)
                    best[key] = (1.0 / max(p, 1e-9), 5)
    return fair, best


def read(rows: list[Row], truth: Truth, names: tuple[str, ...] = ("as-is", "recent-level:28")) -> dict[str, Any]:
    fair, best = market_of(truth, rows)
    forecasts = [stated(rows, variants.parse(n)) for n in names]
    return variants.assess(forecasts, rows, measure="corners_ft", kickoffs={r.fixture_id: r.kickoff_at for r in rows}, fair=fair, best=best)


def test_when_the_level_is_off_and_the_market_is_exact_the_correction_closes_the_gap_and_the_family_as_it_is_does_not() -> None:
    rows, truth = world(days=230, shift=1.35)
    report = read(rows, truth)
    assert report["reference"] == "as-is" and list(report["variants"]) == ["as-is", "recent-level:28"]
    old, new = report["variants"]["as-is"]["versus"], report["variants"]["recent-level:28"]["versus"]
    for ref in ("close", "h24"):
        before, after = old[ref]["total"]["main"], new[ref]["total"]["main"]
        assert before["n"] == after["n"] > 250 and before["fixtures"] == after["fixtures"]
        assert before["mean_p_market"] == pytest.approx(after["mean_p_market"]), "the same market, the same line, whatever the variant says"
        assert before["market_minus_model"] < -5 * before["se"] < 0, "a family 26 % short is worse than the exact market, beyond doubt"
        assert abs(after["market_minus_model"]) < 3 * after["se"], "corrected, it is indistinguishable from the market that knows the truth"
        assert after["observed"] == pytest.approx(after["mean_p_model"], abs=0.04) and abs(before["observed"] - before["mean_p_model"]) > 0.08
        won = report["paired"]["recent-level:28"][ref]["total"]["main"]
        assert won["gain"] > 5 * won["se"] > 0 and won["n"] == after["n"]
        assert won["gain"] == pytest.approx(after["market_minus_model"] - before["market_minus_model"]), "the same rows, the same market: the difference of the gaps"
    assert {"home", "away", "total", "result"} <= set(old["close"])
    for subject in ("home", "away", "result"):
        before, after = old["close"][subject]["all"], new["close"][subject]["all"]
        assert before["n"] == after["n"] > 600 and before["mean_p_market"] == pytest.approx(after["mean_p_market"])
        assert abs(after["market_minus_model"]) < 3 * after["se"], f"{subject}: corrected, it is the market's equal"
        assert after["observed"] == pytest.approx(after["mean_p_model"], abs=0.03), f"{subject}: it says what happened"
        if subject != "result":  # who has more is a comparison of the two sides, and both are short by the same factor
            assert before["market_minus_model"] < -4 * before["se"] < 0, f"{subject}: the family 26 % short loses to the exact market"
    assert report["variants"]["as-is"]["corrected_matches"] == 0 and report["variants"]["recent-level:28"]["corrected_matches"] == report["variants"]["as-is"]["matches"]
    levels = report["variants"]["recent-level:28"]["levels"]
    assert levels and all(1.28 < lv["home"] < 1.42 and 1.28 < lv["away"] < 1.42 for lv in levels), "it found the 35 % the family was short by"
    signal = new["close"]["total"]["main"]["signal"]
    assert signal is not None and abs(signal["coef"]) < 3 * signal["se"], "the exact market has everything: the model adds nothing to it"
    assert set(report["bets"]["models"]) <= {"as-is", "recent-level:28"}
    assert report["bets"]["models"]["as-is"]["taken"] > report["bets"]["models"]["recent-level:28"]["taken"], "the stale family sees value the exact market does not have"


def test_a_bet_needs_a_forecast_stated_a_day_before_and_the_dispersion_of_a_right_level_is_the_smaller_one() -> None:
    rows, truth = world(days=230, shift=1.35)
    report = read(rows, truth)
    inside = [r for r in rows if WINDOW.start <= r.kickoff_at < WINDOW.end]
    early = [r for r in inside if variants.block_start(r.kickoff_at, WINDOW) + bets.PICK_LEAD <= r.kickoff_at]
    assert 0 < len(early) < len(inside), "the first day of every week has no forecast stated a day before"
    taken = {name: m["taken"] for name, m in report["bets"]["models"].items()}
    assert all(n <= 4 * len(early) for n in taken.values()), "one bet per market of each match stated a day before, and four markets are priced"
    assert taken["as-is"] > 0.9 * 4 * len(early), "a family 26 % short sees value in nearly every market of every match"
    old, new = report["variants"]["as-is"]["dispersion"], report["variants"]["recent-level:28"]["dispersion"]
    assert [d["at"] for d in old] == [d["at"] for d in new] and len(old) == 4
    for a, b in zip(old, new, strict=True):
        assert b["total"] < 0.5 * a["total"], f"the dispersion of {a['at'][:10]}: a family with its level right has far less to explain as noise"
        assert a["matches"] == b["matches"] > 600


def test_the_books_and_the_value_asked_for_are_the_ones_that_count() -> None:
    rows, truth = world(days=230, shift=1.35)
    fair, best = market_of(truth, rows)  # five books behind every price
    forecasts = [stated(rows, variants.parse(n)) for n in ("as-is", "recent-level:28")]
    kickoffs = {r.fixture_id: r.kickoff_at for r in rows}

    def assess(**kwargs: Any) -> dict[str, Any]:
        return variants.assess(forecasts, rows, measure="corners_ft", kickoffs=kickoffs, fair=fair, best=best, **kwargs)

    def taken(report: dict[str, Any]) -> dict[str, int]:
        return {name: m["taken"] for name, m in report["bets"]["models"].items()}

    five, six = assess(min_books=5), assess(min_books=6)
    assert five["variants"]["as-is"]["versus"] and five["paired"]["recent-level:28"] and taken(five)["as-is"] > 0
    assert six["variants"]["as-is"]["versus"] == {} and six["paired"]["recent-level:28"] == {} and taken(six) == {"as-is": 0, "recent-level:28": 0}, (
        "a consensus of fewer books than asked for is no consensus: nothing to compare with and no bet")
    assert six["bets"]["criterion"]["min_books"] == 6
    wanted = assess(min_ev=0.2)
    assert wanted["bets"]["criterion"]["min_ev"] == 0.2
    assert taken(wanted)["as-is"] < taken(assess())["as-is"] and taken(wanted)["recent-level:28"] < taken(assess())["recent-level:28"], "a higher value, fewer bets"


def test_what_cannot_be_settled_is_counted_apart_for_every_variant_and_is_not_read() -> None:
    start = T0 + timedelta(days=5)
    base = [row(1, start + timedelta(days=2), 7, 4), row(2, start + timedelta(days=2), 5, 4)]  # 11 and 9 corners; the match 3 has no count at all

    def said(model: str) -> list[score.Row]:
        return [score.Row(1, model, "CORNERS_OU", D("11"), "Over", 0.5, start),    # 11 corners on a whole line 11: the stake comes back
                score.Row(2, model, "CORNERS_OU", D("8.5"), "Over", 0.6, start),   # 9 corners: a win
                score.Row(3, model, "CORNERS_OU", D("8.5"), "Over", 0.6, start),   # nothing to settle it with
                score.Row(3, model, "CORNERS_OU", D("8.5"), "Under", 0.4, start)]
    stated_by = [variants.Forecasts(Variant(AS_IS, 0), rows=said(AS_IS)), variants.Forecasts(Variant("recent-level:28", 28), rows=said("recent-level:28"))]
    kickoffs = {1: start + timedelta(days=2), 2: start + timedelta(days=2), 3: start + timedelta(days=2)}
    fair = {(ref, 2, "CORNERS_OU", D("8.5"), "Over"): (0.55, 4) for ref, _ in versus.REFERENCES}
    report = variants.assess(stated_by, base, measure="corners_ft", kickoffs=kickoffs, fair=fair, best={})
    assert report["left_out"] == {"pushed": 2, "ungradable": 4}, "one that comes back and two with nothing to settle them, for each of the two variants"
    for name in ("as-is", "recent-level:28"):
        for ref, _ in versus.REFERENCES:
            assert report["variants"][name]["versus"][ref]["total"]["all"]["n"] == 1, "only the row that was settled is set against the books"
    clean = variants.assess([variants.Forecasts(Variant(AS_IS, 0), rows=said(AS_IS)[1:2])], base, measure="corners_ft", kickoffs=kickoffs, fair=fair, best={})
    assert clean["left_out"] == {"pushed": 0, "ungradable": 0}


def test_the_two_runs_of_the_same_data_are_the_same_reading() -> None:
    rows, truth = world(days=230, shift=1.2, seed=3)
    assert read(rows, truth) == read(rows, truth)


def test_the_reading_prints_a_line_per_variant_moment_and_subject() -> None:
    rows, truth = world(days=230, shift=1.35)
    report = read(rows, truth)
    report.update({"version": variants.VERSION, "family": "corners_ft", "params": {"referee_kappa": 0.0},
                   "window": {"start": WINDOW.start.isoformat(), "end": WINDOW.end.isoformat(), "step_days": 7},
                   "criterion": {"min_books": 3, "references": ["close", "h24"]}})
    text = variants.render(report)
    assert "referee" not in text, "a family with no referee has nothing to say about one"
    assert text.startswith("corners_ft (variants-v1)") and "recent-level:28 against as-is on the same rows" in text
    assert text.count("close total  recent-level:28") == 2, "the main line and every line"
    assert "market minus model" in text and "signal" in text and "level of the block of" in text
    assert "the plan's criterion for a family to decide in shadow" in text


def test_the_reading_is_printed_in_percent_and_log_loss_with_the_sign_of_the_gap_as_it_is() -> None:
    main = {"n": 5, "fixtures": 5, "mean_p_model": 0.55, "mean_p_market": 0.5, "observed": 0.6, "log_loss_model": 0.7, "log_loss_market": 0.69,
            "market_minus_model": -0.0123, "se": 0.0045, "mean_books": 4.0, "signal": None}
    every = {**main, "n": 12, "market_minus_model": 0.0207, "se": 0.0111, "signal": {"coef": 0.35, "se": 0.27, "market_slope": 1.0, "market_slope_se": 0.1}}
    report = {"version": variants.VERSION, "family": "corners_ft", "reference": AS_IS, "left_out": {"pushed": 2, "ungradable": 0},
              "window": {"start": "2035-02-01T00:00:00+00:00", "end": "2035-03-01T00:00:00+00:00", "step_days": 7},
              "criterion": {"min_books": 3, "references": ["close", "h24"]}, "bets": bets.report([], {}, {}),
              "params": {"xi": 0.0019, "penalty": 32.0, "referee_kappa": 150.0}, "history": {"window_with_referee": 7},
              "variants": {AS_IS: {"level_days": 0, "matches": 10, "corrected_matches": 0, "without_dispersion": 1, "levels": [],
                                   "versus": {"close": {"total": {"main": main, "all": every}}}},
                           "recent-level:28": {"level_days": 28, "matches": 10, "corrected_matches": 9, "without_dispersion": 1, "versus": {},
                                               "levels": [{"at": "2035-02-08T00:00:00+00:00", "home": 1.2346, "away": 0.9, "matches": 250}]}},
              "paired": {"recent-level:28": {"close": {"total": {"main": {"n": 20, "fixtures": 20, "gain": 0.0123, "se": 0.0034}, "all": {"n": 0}}}}}}
    lines = variants.render(report).split("\n")
    assert lines[0] == ("corners_ft (variants-v1): the family and its variants set against the books, kick-offs 2035-02-01T00:00 to 2035-03-01T00:00 UTC, "
                        "a forecast per 7 days with what was known at the start of each; the books' own probability, margin removed, 3+ books")
    assert "  the referee's multiplier (kappa 150) is part of the family's means: it was applied to 7 of 10 matches" in lines
    assert "  as-is: 10 matches; without a dispersion to state with: 1" in lines
    assert "  recent-level:28: 10 matches, corrected in 9 of them; without a dispersion to state with: 1" in lines
    assert "      level of the block of 2035-02-08: home x1.235, away x0.900 (250 matches)" in lines
    assert ("  close total  as-is            n     5  model said  55.0 %  market  50.0 %  happened  60.0 %  log loss 0.7000 / 0.6900  "
            "market minus model -0.0123 ± 0.0045  signal   n/a") in lines
    assert ("  close total  as-is            n    12  model said  55.0 %  market  50.0 %  happened  60.0 %  log loss 0.7000 / 0.6900  "
            "market minus model +0.0207 ± 0.0111  signal +0.35 ± 0.27") in lines
    heads = [ln for ln in lines if ln.startswith(("main line", "every line"))]
    assert [h.split(";")[0] for h in heads] == ["main line of each match (the Over the market gives closest to one in two)", "every line, the Over of each"]
    assert all("positive means the model was better" in h and "0 = adds nothing to the market, 1 = full weight on top" in h for h in heads)
    assert "recent-level:28 against as-is on the same rows (log loss it saves per row, positive: better than as-is):" in lines
    assert "  close total  main  n    20  saves +0.0123 ± 0.0034" in lines and not any("total  all " in ln for ln in lines), "a group with no row is not printed"
    assert lines[-1] == "left out: {'pushed': 2, 'ungradable': 0}" and "no forecast stored 24 hours or more" in lines[-2]
    clean = {**report, "left_out": {"pushed": 0, "ungradable": 0}}
    assert "left out" not in variants.render(clean)


# ── the command ──────────────────────────────────────────────────────────────────────────────────────────────────

NOW = datetime(2035, 3, 1, 12, tzinfo=UTC)


class Connection:
    """What the command opens: it records how it was opened and whether it was given back."""

    seen: ClassVar[dict[str, Any]] = {}

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.seen["closed"] = True

    def rollback(self) -> None:
        self.seen["rolled_back"] = True


def stub_the_reading(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    Connection.seen = seen

    def connect(url: str, **kwargs: Any) -> Connection:
        seen["options"] = kwargs.get("options")
        return Connection()

    def run(conn: Connection, **kwargs: Any) -> dict[str, Any]:
        seen["asked"] = kwargs
        return {"version": variants.VERSION, "family": kwargs["family"], "reference": AS_IS, "variants": {}, "paired": {}, "left_out": {}, "params": {"referee_kappa": 0.0},
                "window": {"start": kwargs["start"].isoformat(), "end": kwargs["end"].isoformat(), "step_days": kwargs["step_days"]},
                "criterion": {"min_books": kwargs["min_books"], "references": ["close", "h24"]}, "bets": bets.report([], {}, {})}

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(variants, "run", run)
    monkeypatch.setattr(cli, "clock_now", lambda: NOW)
    return seen


def test_the_variant_command_reads_through_a_connection_that_cannot_write_and_passes_what_it_was_asked(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    seen = stub_the_reading(monkeypatch)
    out = tmp_path / "reading.json"
    assert cli.main(["variant", "--family", "cards_lines_ft", "--variant", "recent-level:56", "--variant", "RECENT-LEVEL:28", "--since", "2035-02-01",
                     "--until", "2035-02-22T12:00", "--step-days", "14", "--dispersion-days", "90", "--min-books", "4", "--min-ev", "0.05",
                     "--out", str(out), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert json.loads(out.read_text(encoding="utf-8")) == printed and printed["family"] == "cards_lines_ft"
    asked = seen["asked"]
    assert [v.name for v in asked["variants"]] == ["as-is", "recent-level:56", "recent-level:28"], "the family as it is first, then in the order asked"
    assert (asked["start"], asked["end"]) == (datetime(2035, 2, 1, tzinfo=UTC), datetime(2035, 2, 22, 12, tzinfo=UTC)), "a day without a zone is UTC"
    assert (asked["step_days"], asked["dispersion_days"], asked["min_books"], asked["min_ev"]) == (14, 90, 4, 0.05)
    assert seen["options"] == "-c default_transaction_read_only=on", "it reads; it cannot write by mistake"
    assert seen["rolled_back"] and seen["closed"]


def test_the_variant_command_by_default_reads_the_last_four_weeks_with_the_recent_level_of_four_weeks(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = stub_the_reading(monkeypatch)
    assert cli.main(["variant", "--family", "corners_ft"]) == 0
    asked = seen["asked"]
    assert [v.name for v in asked["variants"]] == ["as-is", "recent-level:28"]
    assert asked["end"] == NOW - timedelta(hours=30) and asked["start"] == asked["end"] - timedelta(days=28), "the statistics of the cards need 30 hours to settle"
    assert (asked["step_days"], asked["dispersion_days"], asked["min_books"], asked["min_ev"]) == (7, 120, 3, 0.03)
    assert (variants.STEP_DAYS, variants.DISPERSION_DAYS, versus.MIN_BOOKS, bets.MIN_EV) == (7, 120, 3, 0.03), "the defaults are the ones of the code"
    text = capsys.readouterr().out
    assert text.startswith("corners_ft (variants-v1)"), "text unless --json"
    assert cli.main(["variant", "--family", "corners_ft", "--days", "14", "--wait-hours", "48"]) == 0
    capsys.readouterr()
    assert seen["asked"]["end"] == NOW - timedelta(hours=48) and seen["asked"]["start"] == seen["asked"]["end"] - timedelta(days=14)


def test_the_variant_command_refuses_what_it_cannot_read_before_it_opens_the_database(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = stub_the_reading(monkeypatch)
    for bad in (["--family", "goals_halves"], ["--family", "corners_ft", "--variant", "blend:28"], ["--family", "corners_ft", "--variant", "recent-level:3"],
                ["--family", "corners_ft", "--since", "last week"], ["--family", "corners_ft", "--until", "2035-13-45"], []):
        with pytest.raises(SystemExit) as stopped:
            cli.main(["variant", *bad])
        assert stopped.value.code == 2, bad
        assert "options" not in seen, "nothing was opened"
    assert "is not a variant" in capsys.readouterr().err


def test_a_window_that_is_empty_is_said_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(conn: Connection, **kwargs: Any) -> dict[str, Any]:
        variants.plan(kwargs["start"], kwargs["end"], step_days=7, burn_in_days=0)  # raises: the window is empty
        return {}

    stub_the_reading(monkeypatch)
    monkeypatch.setattr(variants, "run", run)
    with pytest.raises(SystemExit, match="variant: the window is empty"):
        cli.main(["variant", "--family", "corners_ft", "--since", "2035-02-22", "--until", "2035-02-01"])
