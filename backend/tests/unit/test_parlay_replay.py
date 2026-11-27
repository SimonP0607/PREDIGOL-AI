"""RP-11.1: the replay of the joint probability on the shadow's history (``fbi.parlays.replay``). Small sets checked by hand."""

from __future__ import annotations

from datetime import date

import pytest

from fbi.parlays import replay as rp

D1, D2 = date(2026, 11, 20), date(2026, 11, 21)


def leg(key: str, fixture: int, day: date, teams: tuple[int, int], p: float, result: str | None, market: float | None = None) -> rp.Leg:
    return rp.Leg(key, fixture, day, frozenset(teams), p, market, result)


def test_the_legs_that_cannot_be_replayed_are_counted_apart_never_filled_in() -> None:
    legs = [leg("a", 1, D1, (1, 2), 0.5, "win"), leg("b", 2, D1, (3, 4), 0.5, "void"), leg("c", 3, D1, (5, 6), 0.5, None), leg("d", 4, D1, (7, 8), 0.0, "win"),
            leg("e", 5, D1, (9, 10), 0.5, "half"), leg("f", 6, D1, (11, 12), 0.5, "loss")]
    kept, left = rp.usable(legs)
    assert [leg_.chain_key for leg_ in kept] == ["a", "f"]
    assert left == {"anuladas": 1, "sin_liquidar": 1, "sin_probabilidad": 1, "resultado_desconocido": 1}


def test_a_combination_is_distinct_matches_and_teams_of_the_same_day() -> None:
    legs = [leg("a", 1, D1, (1, 2), 0.5, "win"), leg("b", 1, D1, (1, 2), 0.4, "win"),  # same match as a
            leg("c", 2, D1, (2, 3), 0.5, "win"),  # shares team 2 with a
            leg("d", 3, D1, (4, 5), 0.5, "win"), leg("e", 4, D2, (6, 7), 0.5, "win")]  # another day
    combos = rp.combinations(legs)
    assert {c.chains for c in combos} == {("a", "d"), ("b", "d"), ("c", "d")}
    assert all(len(c.chains) == 2 for c in combos)


def test_three_legs_and_the_joint_and_the_result_by_hand() -> None:
    legs = [leg("a", 1, D1, (1, 2), 0.5, "win", 0.4), leg("b", 2, D1, (3, 4), 0.4, "win", 0.5), leg("c", 3, D1, (5, 6), 0.8, "loss", 0.7)]
    combos = {c.chains: c for c in rp.combinations(legs)}
    assert set(combos) == {("a", "b"), ("a", "c"), ("b", "c"), ("a", "b", "c")}
    abc = combos[("a", "b", "c")]
    assert abc.p_joint == pytest.approx(0.16) and abc.p_market_joint == pytest.approx(0.14) and abc.won is False
    assert combos[("a", "b")].won is True and combos[("a", "b")].p_joint == pytest.approx(0.2)


def test_a_missing_market_probability_leaves_the_market_joint_out() -> None:
    legs = [leg("a", 1, D1, (1, 2), 0.5, "win", 0.4), leg("b", 2, D1, (3, 4), 0.4, "win", None)]
    (c,) = rp.combinations(legs)
    assert c.p_market_joint is None


def test_the_report_counts_says_what_is_not_enough_and_never_decides_the_bound() -> None:
    legs = [leg(f"{d}{i}", 100 * d.day + i, d, (10 * d.day + 2 * i, 10 * d.day + 2 * i + 1), 0.5, "win" if (i + d.day) % 2 else "loss", 0.45)
            for d in (D1, D2) for i in range(1, 5)]
    r = rp.report(legs, rounds=200)
    assert r["version"] == rp.VERSION and r["legs"] == 8 and r["legs_replayed"] == 8
    assert r["combinations"] == 2 * (6 + 4) and r["by_size"] == {2: 12, 3: 8} and r["days"] == 2 and r["distinct_legs"] == 8
    assert r["enough"] is False and r["needed"] == 1500 and r["within_bound"] is None
    assert r["model"]["n"] == 20 and r["model"]["interval"] is not None and r["market"]["n"] == 20
    assert sum(b["n"] for b in r["bands"]) == 20
    assert r["model"]["said"] == pytest.approx(sum(c.p_joint for c in rp.combinations(legs)) / 20)


def test_the_interval_resamples_days_and_is_reproducible() -> None:
    legs = [leg(f"{d}{i}", 100 * d.day + i, d, (10 * d.day + 2 * i, 10 * d.day + 2 * i + 1), 0.6, "win" if i % 2 else "loss")
            for d in (D1, D2, date(2026, 11, 22)) for i in range(1, 4)]
    a, b = rp.report(legs, rounds=300), rp.report(legs, rounds=300)
    assert a["model"]["interval"] == b["model"]["interval"]
    low, high = a["model"]["interval"]
    assert low <= high


def test_with_one_day_there_is_no_interval_and_with_nothing_there_is_no_report_of_numbers() -> None:
    one = [leg("a", 1, D1, (1, 2), 0.5, "win"), leg("b", 2, D1, (3, 4), 0.5, "loss")]
    assert rp.report(one)["model"]["interval"] is None
    empty = rp.report([])
    assert empty["combinations"] == 0 and empty["model"]["optimism"] is None and empty["enough"] is False


def test_no_rule_of_the_parlays_is_relaxed_to_get_more_combinations() -> None:
    legs = [leg(f"x{i}", i, D1, (i, 100 + i), 0.5, "win") for i in range(1, 7)]
    assert max(len(c.chains) for c in rp.combinations(legs)) == 3
    assert len(rp.combinations(legs, max_legs=2)) == 15


def test_the_reading_of_the_script_is_held_equal_to_the_shadows_own() -> None:
    """The script restates the shadow's reading of its confirmed selections (the tracking is imported only by its own doors); the parts that decide WHICH
    selections count are the same text in both, and so is the writer."""
    from scripts import ia_parlay_replay as script

    from fbi.tracking import parlay_v6_shadow as shadow

    def flat(sql: str) -> str:
        return " ".join(sql.split())

    assert script.WRITER == shadow.CHAINS
    for part in ("WHERE s.writer = %(writer)s AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND s.known_at <= %(at)s",
                 "ORDER BY s.chain_key, s.id DESC", "WHERE t.state = 'confirmada_sombra'",
                 "LEFT JOIN intel.decisions_v2 d2 ON t.source = 'intel.decisions_v2' AND d2.id = t.source_id",
                 "LEFT JOIN intel.decisions d1 ON t.source = 'intel.decisions' AND d1.id = t.source_id",
                 "COALESCE(d2.p_market, d1.p_market)::float8 AS p_market"):
        assert part in flat(script.CONFIRMED_SQL) and part in flat(shadow.CANDIDATES_SQL), part
