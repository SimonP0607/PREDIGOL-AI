"""The before/after comparison of the neutral-venue rule (fbi.backtesting.neutral_ab; plan F0, defect 1).

Three things are held here. The arithmetic of the verdict (``decide``): which layer's interval settles what, at the edges.
The ratings of each arm: they must be the feature engine's own, or the test would be of some other model. And the whole
comparison on worlds whose truth is planted: where the labelled matches really have no home advantage the rule must come
out as justified, where they have one after all it must not, and where there are too few it must say nothing.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from fbi.backtesting.neutral_ab import (
    PROTOCOL,
    AbResult,
    Paired,
    Pooled,
    Protocol,
    _dataset_hash,
    compare,
    decide,
    elo_inputs,
    evaluate,
    pooled_scores,
)
from fbi.features.data import MatchRecord
from fbi.features.elo import EloParams
from fbi.features.engine import walk_forward
from tests.neutral_synth import SCALED, START, world

P = Protocol()
OFFSET = timedelta(minutes=60)


# ------------------------------------------------------------------------------------------------------ the arithmetic


def paired(n: int, lo: float, hi: float) -> Paired:
    return Paired(n=n, blocks=n, loss_a=1.0, loss_b=1.0, diff=(lo + hi) / 2, lo=lo, hi=hi, brier_a=0.6, brier_b=0.6,
                  rps_a=0.2, rps_b=0.2, ece_a=0.02, ece_b=0.02, home_rate=0.4, home_bias_a=0.0, home_bias_b=0.0)


GOOD = paired(400, -0.030, -0.010)
"""Better with the rule, beyond doubt."""
NOT_WORSE = paired(400, -0.004, 0.004)
CLEAN_CONTROL = paired(100_000, -0.0001, 0.0001)


def test_the_rule_is_justified_when_the_labelled_matches_are_better_and_nothing_else_is_worse() -> None:
    d = decide(P, GOOD, {"poisson": paired(60, -0.05, -0.01)}, CLEAN_CONTROL, {"third_country": paired(300, -0.04, -0.01)})
    assert d.verdict == "justified"
    assert "better" in d.reasons[0]
    assert d.notes == ()


def test_not_worse_is_enough_but_it_is_said_as_not_worse() -> None:
    d = decide(P, NOT_WORSE, {}, CLEAN_CONTROL, {})
    assert d.verdict == "justified"
    assert "not worse" in d.reasons[0] and "better" not in d.reasons[0]


def test_an_interval_that_reaches_above_the_margin_says_nothing() -> None:
    assert decide(P, paired(400, -0.01, P.margin), {}, CLEAN_CONTROL, {}).verdict == "justified", "the margin itself passes"
    d = decide(P, paired(400, -0.01, P.margin + 0.0001), {}, CLEAN_CONTROL, {})
    assert d.verdict == "inconclusive"
    assert "margin" in d.reasons[0]


def test_an_interval_wholly_above_zero_is_harm() -> None:
    assert decide(P, paired(400, 1e-9, 0.02), {}, CLEAN_CONTROL, {}).verdict == "not_justified"
    assert decide(P, paired(400, 0.0, 0.02), {}, CLEAN_CONTROL, {}).verdict == "inconclusive", "touching zero is not harm"


def test_too_few_labelled_matches_is_inconclusive_not_a_verdict() -> None:
    assert decide(P, None, {}, CLEAN_CONTROL, {}).verdict == "inconclusive"
    d = decide(P, paired(P.min_primary - 1, -0.2, -0.1), {}, CLEAN_CONTROL, {})
    assert d.verdict == "inconclusive"
    assert str(P.min_primary) in d.reasons[0]
    assert decide(P, paired(P.min_primary, -0.2, -0.1), {}, CLEAN_CONTROL, {}).verdict == "justified"


def test_a_small_sample_cannot_prove_harm_either() -> None:
    assert decide(P, paired(P.min_primary - 1, 0.1, 0.3), {}, CLEAN_CONTROL, {}).verdict == "inconclusive"


def test_a_goal_model_with_enough_matches_can_veto() -> None:
    harmed = paired(P.min_guard, 0.002, 0.05)
    d = decide(P, GOOD, {"poisson": paired(60, -0.05, -0.01), "dixon_coles": harmed}, CLEAN_CONTROL, {})
    assert d.verdict == "not_justified"
    assert "dixon_coles" in d.reasons[0]


def test_a_goal_model_with_too_few_matches_is_noted_not_counted() -> None:
    d = decide(P, GOOD, {"poisson": paired(P.min_guard - 1, 0.002, 0.05)}, CLEAN_CONTROL, {})
    assert d.verdict == "justified"
    assert len(d.notes) == 1 and "poisson" in d.notes[0] and str(P.min_guard - 1) in d.notes[0]


def test_the_matches_the_rule_does_not_touch_are_held_to_a_tight_margin() -> None:
    edge = P.control_margin
    assert decide(P, GOOD, {}, paired(5000, edge + 1e-9, edge + 0.001), {}).verdict == "not_justified"
    assert decide(P, GOOD, {}, paired(5000, edge, edge + 0.001), {}).verdict == "inconclusive", "reaching above the margin"
    assert decide(P, GOOD, {}, paired(5000, -0.001, edge), {}).verdict == "justified"
    # below the margin but above zero is the price of the ratings moving: allowed, since it cannot be told from noise
    assert decide(P, GOOD, {}, paired(5000, 0.0002, 0.0004), {}).verdict == "justified"


def test_one_kind_of_evidence_that_does_worse_vetoes_the_rule() -> None:
    bad = paired(P.min_basis, 0.004, 0.03)
    d = decide(P, GOOD, {}, CLEAN_CONTROL, {"third_country": paired(500, -0.05, -0.02), "shared_ground": bad})
    assert d.verdict == "not_justified"
    assert "shared_ground" in d.reasons[0]


def test_a_kind_of_evidence_with_few_matches_is_noted_not_judged() -> None:
    d = decide(P, GOOD, {}, CLEAN_CONTROL, {"semi_pair_ground": paired(P.min_basis - 1, 0.01, 0.2)})
    assert d.verdict == "justified"
    assert len(d.notes) == 1 and "semi_pair_ground" in d.notes[0]


def test_harm_settles_it_even_when_the_labelled_sample_is_small() -> None:
    d = decide(P, paired(10, -0.1, 0.1), {"poisson": paired(80, 0.01, 0.05)}, None, {})
    assert d.verdict == "not_justified"


def test_no_control_and_no_kinds_is_still_a_verdict() -> None:
    assert decide(P, GOOD, {}, None, {}).verdict == "justified"


# ------------------------------------------------------------------------------------------------------- the scoring


def test_compare_reports_after_minus_before_and_where_each_arm_leans() -> None:
    y = np.array([0, 0, 1, 2, 0, 0], dtype=np.int64)
    p_a = np.tile([0.40, 0.30, 0.30], (6, 1))
    p_b = np.tile([0.55, 0.25, 0.20], (6, 1))
    days = [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 4), date(2020, 1, 4)]
    r = compare(p_a, p_b, y, days, P)
    assert r is not None
    want = float(np.mean([math.log(p_a[i, y[i]]) - math.log(p_b[i, y[i]]) for i in range(6)]))
    assert r.diff == pytest.approx(want)
    assert r.loss_b - r.loss_a == pytest.approx(want)
    assert (r.n, r.blocks) == (6, 4)
    assert r.lo <= r.diff <= r.hi
    assert r.home_rate == pytest.approx(4 / 6)
    assert r.home_bias_a == pytest.approx(0.40 - 4 / 6) and r.home_bias_b == pytest.approx(0.55 - 4 / 6)


def test_compare_of_nothing_is_nothing() -> None:
    assert compare(np.empty((0, 3)), np.empty((0, 3)), np.empty(0, dtype=np.int64), [], P) is None


def test_the_pooled_arrays_select_by_label_and_by_kind_of_evidence() -> None:
    d1, d2 = date(2020, 1, 1), date(2020, 1, 2)
    pooled = Pooled(fixture_ids=[10, 11, 12], days=[d1, d1, d2], primary=[True, False, True], y=[0, 1, 2],
                    p_a=[(0.5, 0.3, 0.2), (0.4, 0.3, 0.3), (0.3, 0.3, 0.4)],
                    p_b=[(0.6, 0.2, 0.2), (0.4, 0.3, 0.3), (0.2, 0.3, 0.5)])
    _, _, y, days = pooled.arrays(primary=True)
    assert list(y) == [0, 2] and days == [d1, d2]
    _, b, y, _ = pooled.arrays(primary=True, subset={12})
    assert list(y) == [2] and b[0, 2] == pytest.approx(0.5)
    a, _, y, days = pooled.arrays(primary=False)
    assert list(y) == [1] and a.shape == (1, 3) and days == [d1]
    assert pooled.arrays()[2].shape == (3,)
    assert pooled.arrays(primary=True, subset=set())[0].shape == (0, 3)


# --------------------------------------------------------------------------------------- the ratings of each arm


def history(seed: int = 5, teams: int = 8, rounds: int = 75, neutral_share: float = 0.2) -> list[MatchRecord]:
    """Weekly rounds among a few sides - enough for the 60-match memory to be exceeded, with several matches kicking off at
    the very same minute, some of them neutral, and a tail of fixtures not played yet."""
    rng = random.Random(seed)
    out: list[MatchRecord] = []
    fid = 0
    for r in range(rounds):
        order = list(range(1, teams + 1))
        rng.shuffle(order)
        for k in range(teams // 2):
            fid += 1
            played = r < rounds - 2
            out.append(MatchRecord(
                fixture_id=fid, kickoff_at=START + timedelta(days=7 * r), competition_id=1,
                competition_type="domestic_league", season=2015, home_team_id=order[2 * k], away_team_id=order[2 * k + 1],
                goals_home=rng.randint(0, 4) if played else None, goals_away=rng.randint(0, 3) if played else None,
                is_neutral=rng.random() < neutral_share, status_group="finished" if played else "scheduled"))
    return out


def test_the_ratings_of_each_arm_are_the_feature_engines_own() -> None:
    matches = history()
    vectors, _ = walk_forward(matches, [(m, m.kickoff_at - OFFSET) for m in matches if m.has_result])
    own = elo_inputs(matches, EloParams(), OFFSET)
    assert len(own) == len(vectors) > 150
    assert len(own) < len(matches), "a fixture not played has no rating difference to report"
    for v in vectors:
        diff, known = own[v.fixture_id]
        assert diff == pytest.approx(v.values["elo_diff"], abs=1e-9)
        assert known == int(min(v.values["home_history_n"] or 0, v.values["away_history_n"] or 0))
    assert max(k for _, k in own.values()) == 60, "the memory cap of the engine is the cap here too"


def test_a_result_that_lands_after_the_cut_off_is_not_in_the_ratings() -> None:
    # side 1 plays again three and a half hours after kicking off: its first result (known at +3h) lands after the cut-off
    # of the second match (kick-off - 1h = +2.5h), so the second match is rated from the starting ratings
    def match(fid: int, hours: float, home: int, away: int, gh: int, ga: int) -> MatchRecord:
        return MatchRecord(fixture_id=fid, kickoff_at=START + timedelta(hours=hours), competition_id=1,
                           competition_type="domestic_league", season=2015, home_team_id=home, away_team_id=away,
                           goals_home=gh, goals_away=ga, is_neutral=False, status_group="finished")

    pair = [match(1, 0, 1, 2, 3, 0), match(2, 3.5, 1, 3, 0, 0), match(3, 24 * 3, 1, 3, 1, 1)]
    own = elo_inputs(pair, EloParams(), OFFSET)
    assert own[2] == (0.0, 0), "nothing was known about either side yet"
    assert own[3][0] != 0.0 and own[3][1] == 1, "side 1 has two results, side 3 one: the smaller is what counts"
    vectors, _ = walk_forward(pair, [(m, m.kickoff_at - OFFSET) for m in pair])
    assert [v.values["elo_diff"] for v in vectors] == pytest.approx([own[m.fixture_id][0] for m in pair])


def test_a_neutral_flag_moves_the_ratings_it_feeds() -> None:
    matches = history()
    plain = [replace(m, is_neutral=False) for m in matches]
    flagged, unflagged = elo_inputs(matches, EloParams(), OFFSET), elo_inputs(plain, EloParams(), OFFSET)
    assert flagged.keys() == unflagged.keys()
    assert any(flagged[k][0] != unflagged[k][0] for k in flagged)
    assert all(flagged[k][1] == unflagged[k][1] for k in flagged), "how many matches a side has played is not a rating"


# ----------------------------------------------------------------------------------------------- the whole comparison


def run(seed: int, **kw: object) -> AbResult:
    before, after = world(seed, **kw)  # type: ignore[arg-type]
    bases = {m.fixture_id: "third_country" for m in after if m.is_neutral}
    return evaluate(before, after, bases, SCALED, labels={"made": "up"})


def test_where_the_labelled_matches_really_have_no_home_advantage_the_rule_is_justified() -> None:
    r = run(2, share=0.3, really_neutral=True)
    assert r.decision.verdict == "justified", r.decision
    assert r.primary is not None and r.primary.n >= SCALED.min_primary
    assert r.primary.hi < 0, "the matches are priced better, not merely not worse"
    assert r.primary.home_bias_a > r.primary.home_bias_b, "before, the arm over-rates the home side where there is none"
    assert r.guards["poisson"].diff < 0, "and so does the production goal model, though it sees fewer of them"
    assert r.counts["labelled_priced_by_both"] == r.primary.n


def test_where_the_labelled_matches_have_a_home_advantage_after_all_the_rule_is_not_justified() -> None:
    # the labels are wrong: the arm that takes the home advantage out is the one that is penalised
    r = run(1, share=0.3, really_neutral=False)
    assert r.decision.verdict == "not_justified", r.decision
    assert r.primary is not None and r.primary.diff > 0
    assert any("poisson" in why for why in r.decision.reasons), "the production goal model sees it"


@pytest.mark.parametrize("seed", [6, 7])
def test_a_wrong_label_that_happens_to_look_harmless_is_still_not_promoted(seed: int) -> None:
    # in these two worlds the labelled matches are priced no worse (even a little better) by luck, but the interval is far
    # too wide to rule out harm: the margin is on the upper end of the interval, not on the point estimate
    r = run(seed, share=0.3, really_neutral=False)
    assert r.primary is not None and r.primary.diff < 0.006 and r.primary.hi > SCALED.margin
    assert r.decision.verdict == "inconclusive", r.decision


def test_with_a_handful_of_labelled_matches_there_is_no_verdict() -> None:
    r = run(3, share=0.01, really_neutral=True)
    assert r.decision.verdict == "inconclusive"
    assert r.primary is not None and r.primary.n < SCALED.min_primary


def test_when_the_rule_labels_nothing_nothing_changes() -> None:
    before, _ = world(4, share=0.0, really_neutral=True, weeks=120)
    r = evaluate(before, before, {}, SCALED)
    assert r.primary is None and r.guards == {}
    assert r.decision.verdict == "inconclusive"
    assert r.control is not None and r.control.n > 500
    assert r.control.diff == 0.0 and r.control.loss_a == r.control.loss_b, "the same matches priced the same way"


def test_a_match_both_arms_already_treat_as_neutral_is_not_the_rules_doing() -> None:
    before, after = world(2, share=0.3, really_neutral=True)
    already = {m.fixture_id for m in before if m.fixture_id % 40 == 0}  # flagged by something else, in both arms
    rule = [m for m in after if m.is_neutral and m.fixture_id not in already and m.kickoff_at >= SCALED.test_from]
    before = [replace(m, is_neutral=True) if m.fixture_id in already else m for m in before]
    after = [replace(m, is_neutral=True) if m.fixture_id in already else m for m in after]
    r = evaluate(before, after, {}, SCALED)
    assert r.counts["labelled_in_window"] == len(rule)
    assert r.primary is not None and r.primary.n <= len(rule)


def test_the_mapping_is_fitted_on_results_known_by_the_cut_off_and_no_others(monkeypatch: pytest.MonkeyPatch) -> None:
    # a result is known three hours after kick-off. A match that kicked off 90 minutes before the cut-off of the first block
    # has no result yet and must not be in the fit; one that kicked off five hours before has, and must be.
    import fbi.backtesting.neutral_ab as module
    from fbi.models.elo_ologit import fit_ologit as real_fit

    seen: list[int] = []

    def spy(obs: object) -> object:
        seen.append(len(obs))  # type: ignore[arg-type]
        return real_fit(obs)  # type: ignore[arg-type]

    monkeypatch.setattr(module, "fit_ologit", spy)
    base, _ = world(8, share=0.0, really_neutral=True, weeks=100)
    first = min(m.kickoff_at for m in base if m.kickoff_at >= datetime(2017, 1, 1, tzinfo=UTC))
    proto = replace(SCALED, test_from=first, goal_kinds=())

    def fits_after(extra_hours_before_first: float | None) -> int:
        matches = list(base)
        if extra_hours_before_first is not None:
            matches.append(replace(base[-1], fixture_id=10_000, home_team_id=1, away_team_id=2,
                                   kickoff_at=first - timedelta(hours=extra_hours_before_first)))
            matches.sort(key=lambda m: (m.kickoff_at, m.fixture_id))
        seen.clear()
        pooled_scores(matches, matches, set(), proto, end=first)
        return seen[0]

    alone = fits_after(None)
    # every side plays once a round, so a match of round r is rated from r results behind it: the first ten rounds are not
    # rated (MIN_ELO_HISTORY) and do not train the mapping; every round before the first target's is known
    round_of = {m.fixture_id: (m.kickoff_at - START).days // 7 for m in base}
    first_round = round_of[next(m.fixture_id for m in base if m.kickoff_at == first)]
    assert alone == sum(1 for m in base if 10 <= round_of[m.fixture_id] < first_round) > 100
    assert fits_after(1.5) == alone, "kicked off 90 minutes before the cut-off: result not known yet"
    assert fits_after(5.0) == alone + 1, "kicked off five hours before: result known"


def test_matches_flagged_in_both_arms_are_priced_the_same_way_in_both() -> None:
    _, flagged = world(4, share=0.3, really_neutral=True, weeks=120)
    r = evaluate(flagged, flagged, {}, SCALED)
    assert r.counts["labelled_in_window"] == 0 and r.primary is None
    assert r.control is not None and r.control.n > 500
    assert r.control.diff == 0.0 and r.control.brier_a == r.control.brier_b and r.control.rps_a == r.control.rps_b


def test_both_arms_must_hold_the_same_matches_in_the_same_order() -> None:
    before, after = world(5, share=0.1, really_neutral=True, weeks=30)
    with pytest.raises(ValueError, match="same fixtures"):
        pooled_scores(before, after[:-1], set(), SCALED)
    with pytest.raises(ValueError, match="same fixtures"):
        pooled_scores(before, list(reversed(after)), set(), SCALED)


def test_the_result_is_a_plain_document_that_names_its_protocol() -> None:
    r = run(2, share=0.3, really_neutral=True)
    doc = r.as_dict()
    json.dumps(doc, allow_nan=False)  # what is stored is jsonb: no NaN, nothing numpy
    assert doc["protocol"] == PROTOCOL == "neutral-ab-v1"
    assert doc["verdict"] == r.decision.verdict and doc["reasons"] and "notes" in doc
    assert set(doc) >= {"window", "counts", "labels", "primary", "guards", "control", "bases", "headline", "seconds"}
    assert doc["labels"] == {"made": "up"}
    assert doc["primary"]["n"] == r.primary.n  # type: ignore[union-attr]
    assert set(doc["bases"]) == {"third_country"}
    spec = SCALED.as_dict()
    assert spec["protocol"] == PROTOCOL and spec["margin"] == SCALED.margin and spec["elo"]["home_advantage"] == 65


def test_the_fingerprint_of_the_data_follows_the_flags_and_not_the_order() -> None:
    _, after = world(6, share=0.2, really_neutral=True, weeks=10)
    base = _dataset_hash(after)
    assert _dataset_hash(list(reversed(after))) == base
    flipped = [replace(m, is_neutral=not m.is_neutral) if m.fixture_id == after[3].fixture_id else m for m in after]
    assert _dataset_hash(flipped) != base
    assert _dataset_hash(after[:-1]) != base
