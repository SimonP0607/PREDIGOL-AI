"""The scenarios engine (IA-082, plan piece AD-B02, ``scenarios-v2``): what is proved is never contradicted - not by any way the matches
left can end (checked by brute force on small tables), not by the simulation (a proved objective is 0 or 1 there) - ties always count
against the claim, deductions and postponed or unscheduled matches are counted, a conditional zone is never decided, a competition
without coded rules asserts nothing, and ``SIN_OBJETIVO_DEMOSTRADO`` is emitted only when every objective is proved."""

from __future__ import annotations

import itertools
import random
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pytest

from fbi.competitions import rules as rl
from fbi.competitions import scenarios as sc
from fbi.competitions.rules import CompetitionRules, Points

AT = datetime(2026, 11, 16, 12, tzinfo=UTC)
SOURCE = {"publisher": "Test federation", "title": "Test regulation", "url": "https://example.org/rules.pdf",
          "checked_at": "2026-11-16", "applies_to": "season 2026"}


def make_rules(teams: int, zones: list[dict[str, Any]], *, gaps: tuple[str, ...] = (), schedule: str = "double_round_robin",
               matches_per_team: int | None = None, tiebreakers: tuple[str, ...] = ("goal_difference", "goals_for", "lots"),
               groups: int | None = None, group_size: int | None = None) -> CompetitionRules:
    phase: dict[str, Any] = {"key": "league", "name": "League", "format": "groups" if groups else "league",
                             "rounds": ["Regular Season - *"], "schedule": schedule,
                             "ranking": {"tiebreakers": list(tiebreakers)}, "zones": zones}
    if groups:
        phase.update(groups=groups, group_size=group_size)
    else:
        phase["teams"] = teams
    if matches_per_team is not None:
        phase["matches_per_team"] = matches_per_team
    return CompetitionRules.model_validate({
        "schema": "competition-rules/1", "league_id": 9999, "competition": "Test League", "country": "Testland", "version": 1,
        "seasons": [2026], "sources": [SOURCE], "tournaments": [{"key": "season", "name": "Season", "phases": [phase]}],
        "gaps": [{"topic": t, "reason": "not read for this test, on purpose"} for t in gaps]})


def coded(rules: CompetitionRules) -> rl.Coded:
    return rl.Coded(rules.league_id, 2026, rl.RulesFile("9999_test/v1.yaml", "0" * 64, rules))


def round_robin(teams: list[int], *, legs: int = 2) -> list[tuple[int, int]]:
    pairs = [(h, a) for h, a in itertools.permutations(teams, 2)]
    return pairs if legs == 2 else [(h, a) for h, a in pairs if h < a]


def fixtures(pairs: list[tuple[int, int]], results: dict[int, tuple[int, int]]) -> list[sc.Fixture]:
    out = []
    for i, (h, a) in enumerate(pairs):
        r = results.get(i)
        out.append(sc.Fixture(i + 1, f"Regular Season - {i + 1}", h, a, None if r is None else r[0], None if r is None else r[1]))
    return out


def board(points: dict[int, int], pending: list[tuple[int, int]], phantom: dict[int, int] | None = None) -> sc.Board:
    return sc.Board(points, tuple(sorted(points)), tuple(pending), phantom or {}, Points())


# ── the certification, by hand ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_team_out_of_reach_of_everybody_has_secured_the_title() -> None:
    b = board({1: 30, 2: 20, 3: 18, 4: 10}, [(1, 2), (3, 4), (2, 3)])
    assert sc.certify(b, 1, 1).state == "conseguido"
    assert sc.certify(b, 4, 1).state == "descartado"


def test_a_tie_on_points_counts_against_the_claim_both_ways() -> None:
    # 2 can reach 30 exactly: level with 1, so 1 has not secured it, and 2 is not out of it
    b = board({1: 30, 2: 27, 3: 0}, [(2, 3)])
    assert sc.certify(b, 1, 1).state == "abierto"
    assert sc.certify(b, 2, 1).state == "abierto"
    b2 = board({1: 31, 2: 27, 3: 0}, [(2, 3)])
    assert sc.certify(b2, 1, 1).state == "conseguido"
    assert sc.certify(b2, 2, 1).state == "descartado"


def test_two_rivals_who_play_each_other_cannot_both_win_it() -> None:
    # 1 has 30 and nothing left; 2 and 3 have 28 and play each other once: at most one of them passes 1 (a draw leaves both on 29)
    b = board({1: 30, 2: 28, 3: 28, 4: 0}, [(2, 3)])
    assert sc.certify(b, 1, 2) == sc.Certificate("conseguido", True)  # within the first two whatever happens
    assert sc.certify(b, 1, 1).state == "abierto"


def test_a_deduction_counts() -> None:
    rules = make_rules(4, [{"kind": "champion", "from": 1, "to": 1}])
    pairs = round_robin([1, 2, 3, 4])
    results = {i: (1, 0) if h == 1 else (0, 1) if a == 1 else (1, 1) for i, (h, a) in enumerate(pairs)}
    played = fixtures(pairs, results)
    plain = sc.evaluate(coded(rules), played, at=AT)
    sanctioned = sc.evaluate(coded(rules), played, at=AT, adjustments={1: -15})
    row = next(r for r in plain["tables"][0]["teams"] if r["team"] == 1)
    assert row["objetivos"][0]["estado"] == "conseguido"
    row = next(r for r in sanctioned["tables"][0]["teams"] if r["team"] == 1)
    assert row["puntos"] == 3 and row["objetivos"][0]["estado"] == "descartado"  # the others have 4 (four draws)


def test_a_postponed_match_is_still_to_play_and_an_unscheduled_one_is_counted_as_any_result() -> None:
    rules = make_rules(4, [{"kind": "champion", "from": 1, "to": 1}], matches_per_team=6)
    pairs = round_robin([1, 2, 3, 4])
    # 1 has won its five played matches; its sixth (1 v 2, index 0) was postponed; 2 has 3 wins and the postponed match
    results = {i: ((1, 0) if h == 1 else (0, 1)) if 1 in (h, a) else (2, 0) if h == 2 else (0, 2) if a == 2 else (1, 1)
               for i, (h, a) in enumerate(pairs) if i != 0}
    reading = sc.evaluate(coded(rules), fixtures(pairs, results), at=AT)
    table = reading["tables"][0]
    assert table["pending"] == 1
    team1 = next(r for r in table["teams"] if r["team"] == 1)
    assert team1["partidos_restantes"] == 1
    # the same season with the postponed match taken off the calendar: the regulation says six matches, so it is a phantom match
    missing = [f for f in fixtures(pairs, results) if f.id != 1]
    table2 = sc.evaluate(coded(rules), missing, at=AT)["tables"][0]
    assert table2["phantom"] == {"1": 1, "2": 1}
    assert next(r for r in table2["teams"] if r["team"] == 1)["puntos_maximos"] == team1["puntos_maximos"]


def test_a_conditional_zone_is_positioned_but_never_decided() -> None:
    rules = make_rules(4, [{"kind": "continental", "from": 1, "to": 2, "conditional": True}])
    pairs = round_robin([1, 2, 3, 4])
    results = {i: (3, 0) if h < a else (0, 3) for i, (h, a) in enumerate(pairs)}
    reading = sc.evaluate(coded(rules), fixtures(pairs, results), at=AT)
    for row in reading["tables"][0]["teams"]:
        o = row["objetivos"][0]
        assert o["estado"] in ("conseguido", "descartado")  # every match played: the places are known
        assert o["decidido"] == {"valor": False, "demostrado": False, "motivos": ["zona_condicional"]}
    assert not any(v["demostrado"] for v in reading["teams"].values())


def test_a_competition_without_coded_rules_asserts_nothing() -> None:
    answer = rl.NotCoded(82, 2026, "not_yet_coded", "no file")
    reading = sc.evaluate(answer, [sc.Fixture(1, "Regular Season - 1", 1, 2)], at=AT)
    assert reading["status"] == sc.NOT_CODED == "reglamento_no_codificado"
    assert reading["tables"] == [] and reading["teams"] == {}
    assert sc.stakes_for(reading, 1) == []


def test_no_objective_is_proved_only_without_gaps_and_with_everything_decided() -> None:
    zones = [{"kind": "champion", "from": 1, "to": 1}, {"kind": "relegation", "last": 1}]
    pairs = round_robin([1, 2, 3, 4, 5])
    # 1 wins everything, 5 loses everything, 2-3-4 draw among themselves; one match left: 2 v 3 (the last pair 2-3 index)
    results = {}
    for i, (h, a) in enumerate(pairs):
        if 1 in (h, a):
            results[i] = (4, 0) if h == 1 else (0, 4)
        elif 5 in (h, a):
            results[i] = (0, 3) if h == 5 else (3, 0)
        else:
            results[i] = (1, 1)
    last = next(i for i, p in enumerate(pairs) if p == (3, 4))
    del results[last]
    reading = sc.evaluate(coded(make_rules(5, zones)), fixtures(pairs, results), at=AT)
    facts = reading["teams"]
    assert facts["1"]["hecho"] == sc.FACT_NO_OBJECTIVE  # champion already, safe
    assert facts["5"]["hecho"] == sc.FACT_NO_OBJECTIVE  # relegated already
    assert facts["3"]["hecho"] == sc.FACT_NO_OBJECTIVE  # neither champion nor last, whatever 3 v 4 gives
    fresh = sc.evaluate(coded(make_rules(5, zones)), fixtures(pairs, {}), at=AT)["teams"]["3"]
    assert fresh["hecho"] is None and fresh["demostrado"] is False
    assert "objetivo_abierto:season.league:titulo" in fresh["motivos"]
    gapped = sc.evaluate(coded(make_rules(5, zones, gaps=("continental",))), fixtures(pairs, results), at=AT)
    assert gapped["teams"]["1"]["hecho"] is None
    assert gapped["teams"]["1"]["motivos"] == ["hueco_reglamento:continental"]


def test_a_finished_table_is_decided_by_the_regulations_tiebreakers_and_an_open_tie_stays_open() -> None:
    zones = [{"kind": "champion", "from": 1, "to": 1}]
    pairs = round_robin([1, 2, 3], legs=1)  # (1,2), (1,3), (2,3)
    results = {0: (2, 2), 1: (3, 0), 2: (0, 1)}  # 1: 4 pts +3; 2: 1 pt; 3: 3 pts... 1 is champion
    r = sc.evaluate(coded(make_rules(3, zones, schedule="single_round_robin")), fixtures(pairs, results), at=AT)
    states = {row["team"]: row["objetivos"][0]["estado"] for row in r["tables"][0]["teams"]}
    assert states == {1: "conseguido", 2: "descartado", 3: "descartado"}
    level = {0: (1, 1), 1: (1, 1), 2: (1, 1)}  # all level on everything: lots decide, not given
    r2 = sc.evaluate(coded(make_rules(3, zones, schedule="single_round_robin")), fixtures(pairs, level), at=AT)
    assert {row["objetivos"][0]["estado"] for row in r2["tables"][0]["teams"]} == {"abierto"}


def test_the_provider_points_differ_and_only_what_both_prove_is_claimed() -> None:
    zones = [{"kind": "champion", "from": 1, "to": 1}]
    pairs = round_robin([1, 2, 3], legs=1)
    results = {0: (1, 0), 1: (1, 0)}  # 1 has 6, 2 has 0, 3 has 0; 2 v 3 left
    provider = {"Table": [sc.ProviderRow(1, 6, 2), sc.ProviderRow(2, 3, 1), sc.ProviderRow(3, 0, 1)]}
    rules = make_rules(3, zones, schedule="single_round_robin")
    r = sc.evaluate(coded(rules), fixtures(pairs, results), at=AT, provider=provider)
    t = r["tables"][0]
    assert "datos_discrepantes" in t["flags"] and t["provider_differences"][0]["team"] == 2
    one = next(row for row in t["teams"] if row["team"] == 1)
    # with our results 2 can reach 3 (< 6): secured; with the provider's 3 points 2 can reach 6: level, not secured
    assert one["objetivos"][0]["estado"] == "abierto"


def test_the_three_results_of_a_match() -> None:
    zones = [{"kind": "next_phase", "from": 1, "to": 2}]
    pairs = round_robin([1, 2, 3, 4], legs=1)  # 6 matches
    results = {0: (1, 0), 1: (1, 0), 3: (1, 0), 4: (0, 1)}  # left: (1,4) idx 2 and (3,4) idx 5
    r = sc.evaluate(coded(make_rules(4, zones, schedule="single_round_robin")), fixtures(pairs, results), at=AT, focus=[3])
    match = r["tables"][0]["matches"]["3"]
    assert set(match) == {"home", "away"}
    assert match["home"]["team"] == 1 and set(match["home"]["objetivos"][0]) >= {"victoria", "empate", "derrota"}


def test_stakes_for_flattens_one_row_per_objective() -> None:
    zones = [{"kind": "champion", "from": 1, "to": 1}, {"kind": "relegation", "last": 1}]
    pairs = round_robin([1, 2, 3, 4])
    r = sc.evaluate(coded(make_rules(4, zones)), fixtures(pairs, {}), at=AT)
    rows = sc.stakes_for(r, 2)
    assert [x["objetivo"] for x in rows] == ["titulo", "evitar_descenso"]
    assert set(rows[0]) >= {"team", "objetivo", "necesita", "depende_de", "decidido", "computed_at"}
    assert rows[0]["decidido"]["demostrado"] is False and rows[0]["estado"] == "abierto"


def test_groups_come_from_the_provider_tables_or_nothing_is_asserted() -> None:
    zones = [{"kind": "next_phase", "from": 1, "to": 1, "per_group": True}]
    rules = make_rules(4, zones, groups=2, group_size=2, schedule="double_round_robin")
    pairs = [(1, 2), (2, 1), (3, 4), (4, 3)]
    fx = fixtures(pairs, {0: (1, 0)})
    none = sc.evaluate(coded(rules), fx, at=AT)
    assert none["tables"] == [] and none["skipped"][0]["reason"] == "grupos_no_identificados"
    assert all(v["hecho"] is None for v in none["teams"].values())
    hint = {"A": [sc.ProviderRow(1, 3, 1), sc.ProviderRow(2, 0, 1)], "B": [sc.ProviderRow(3, 0, 0), sc.ProviderRow(4, 0, 0)],
            "All": [sc.ProviderRow(t, 0, 0) for t in (1, 2, 3, 4)]}
    some = sc.evaluate(coded(rules), fx, at=AT, provider=hint)
    assert sorted(t["group"] for t in some["tables"]) == ["A", "B"]


# ── brute force: the certificate against every way the matches left can end ─────────────────────────────────────────────────────


def _outcomes(b: sc.Board) -> list[dict[int, int]]:
    out = []
    for combo in itertools.product(((3, 0), (1, 1), (0, 3)), repeat=len(b.pending)):
        pts = dict(b.points)
        for (h, a), (gh, ga) in zip(b.pending, combo, strict=True):
            pts[h] += gh
            pts[a] += ga
        out.append(pts)
    return out


@pytest.mark.parametrize("seed", range(60))
def test_the_certificate_holds_in_every_outcome_and_is_exact_when_it_says_so(seed: int) -> None:
    rnd = random.Random(seed)
    teams = list(range(1, rnd.randint(4, 6) + 1))
    points = {t: rnd.randint(0, 12) for t in teams}
    pending = rnd.sample([(h, a) for h, a in itertools.permutations(teams, 2)], rnd.randint(1, 6))
    b = board(points, pending)
    outcomes = _outcomes(b)
    for t in teams:
        for n in range(1, len(teams)):
            cert = sc.certify(b, t, n)
            worst_in = [1 + sum(1 for u in teams if u != t and p[u] >= p[t]) for p in outcomes]  # ties against
            best_in = [1 + sum(1 for u in teams if u != t and p[u] > p[t]) for p in outcomes]  # ties for
            if cert.state == "conseguido":
                assert all(w <= n for w in worst_in), (seed, t, n)
            elif cert.state == "descartado":
                assert all(x > n for x in best_in), (seed, t, n)
            elif cert.exact:
                assert any(w > n for w in worst_in) and any(x <= n for x in best_in), (seed, t, n)
            secure = sc.points_that_secure(b, t, n)
            if secure is not None:
                for p in outcomes:
                    if p[t] >= secure:
                        assert 1 + sum(1 for u in teams if u != t and p[u] >= p[t]) <= n, (seed, t, n, secure)


# ── the property: what is proved is 0 or 1 in the simulation ─────────────────────────────────────────────────────────────────────


def _matrix(rng: np.random.Generator) -> np.ndarray:
    lam_h, lam_a = rng.uniform(0.6, 2.2), rng.uniform(0.5, 1.8)
    k = np.arange(8)
    ph = np.exp(-lam_h) * lam_h ** k / np.array([float(np.prod(np.arange(1, i + 1))) for i in k])
    pa = np.exp(-lam_a) * lam_a ** k / np.array([float(np.prod(np.arange(1, i + 1))) for i in k])
    m = np.outer(ph, pa)
    return m / m.sum()


@pytest.mark.parametrize("seed", range(12))
def test_what_is_proved_is_never_contradicted_by_the_simulation(seed: int) -> None:
    rnd = random.Random(seed)
    rng = np.random.default_rng(seed)
    teams = list(range(1, 9))
    zones = [{"kind": "champion", "from": 1, "to": 1}, {"kind": "next_phase", "from": 1, "to": 4},
             {"kind": "relegation_playoff", "from": 6, "to": 6}, {"kind": "relegation", "last": 2}]
    pairs = round_robin(teams)
    played = rnd.randint(len(pairs) - 14, len(pairs) - 3)
    results = {i: (rnd.randint(0, 3), rnd.randint(0, 3)) for i in rnd.sample(range(len(pairs)), played)}
    fx = fixtures(pairs, results)
    scores = {f.id: _matrix(rng) for f in fx if not f.played}
    r = sc.evaluate(coded(make_rules(8, zones)), fx, at=AT, scores=scores, sims=300, seed=seed)
    assert r["contradicciones"] == 0
    t = r["tables"][0]
    assert t["simulation"]["status"] == "ok"
    for row in t["teams"]:
        for o in row["objetivos"]:
            if o["estado"] == "conseguido":
                assert o["probabilidad"] == 1.0
            elif o["estado"] == "descartado":
                assert o["probabilidad"] == 0.0


def test_the_simulation_is_reproducible_with_its_seed() -> None:
    teams = [1, 2, 3, 4]
    pairs = round_robin(teams)
    fx = fixtures(pairs, dict.fromkeys(range(6), (1, 0)))
    rng = np.random.default_rng(3)
    scores = {f.id: _matrix(rng) for f in fx if not f.played}
    rules = make_rules(4, [{"kind": "champion", "from": 1, "to": 1}])
    a = sc.evaluate(coded(rules), fx, at=AT, scores=scores, sims=200, seed=7)
    b = sc.evaluate(coded(rules), fx, at=AT, scores=scores, sims=200, seed=7)
    assert a["tables"] == b["tables"]
    missing = sc.evaluate(coded(rules), fx, at=AT, scores={}, sims=200)
    assert missing["tables"][0]["simulation"]["status"] == "sin_modelo"


def test_the_rules_reader_is_used_by_day() -> None:
    assert isinstance(rl.rules_for(239, 2026, on=date(2026, 11, 14)), rl.Coded)
    assert isinstance(rl.rules_for(82, 2026), rl.NotCoded)
