"""PM-05-01: the answer of ``/fixtures/statistics?half=true`` read as the PM-01-05 probe read it, on six REAL answers kept from the
probe (``tests/fixtures/period_stats``): a Premier League match with everything, one without fouls and red cards (Serie A), one without
expected goals (J1 and K League 1), one where first half + second half is not the match (a blocked shot), and the Libertadores. The
rule that decides what is built (DM-13) is the probe's, and the numbers are held equal to the probe's own."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import coverage_probe as probe

from fbi.core import period_rules as rules
from fbi.providers.api_football import period_stats as ps
from fbi.providers.api_football.details import STAT_TYPES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "period_stats"
NAMES = ("typical", "no_fouls", "no_xg", "sum_off", "kleague", "libertadores")


def load(name: str) -> tuple[int, dict[str, Any]]:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return int(data["fixture"]), data["body"]


def answer(name: str) -> ps.PeriodAnswer:
    fixture, body = load(name)
    return ps.parse_period_answer(body, fixture)


def test_the_numbers_are_the_probes() -> None:
    assert rules.BUILD_SHARE == probe.BUILD_SHARE == 0.90
    assert rules.MIN_SAMPLE == probe.MIN_SAMPLE == 5
    assert rules.STATS == ps.PERIOD_STAT_COLUMNS
    assert set(ps.COUNTED) <= set(ps.PERIOD_STAT_COLUMNS)
    assert set(ps.PERIOD_STAT_COLUMNS) <= set(STAT_TYPES.values())


@pytest.mark.parametrize("name", NAMES)
def test_it_reads_halves_and_fills_exactly_as_the_probe_does(name: str) -> None:
    """The decision DM-13 was taken on ``judge_half``: the same answer gives the same halves and, type by type, the same filled."""
    fixture, body = load(name)
    a = ps.parse_period_answer(body, fixture)
    judged = probe.judge_half(body)
    assert a.halves == judged.halves
    assert a.outcome == "with_halves"
    column = dict(STAT_TYPES)
    probe_filled = {column[t.lower()] for t in judged.present - judged.empty if t.lower() in column and column[t.lower()] in ps.PERIOD_STAT_COLUMNS}
    assert set(a.filled()) == probe_filled, (set(a.filled()) ^ probe_filled)
    # first half + second half = the match, as the probe counts it
    ok, off = a.sums()
    probe_ok = {column[t.lower()] for t, v in judged.sums.items() if v and t.lower() in column}
    probe_off = {column[t.lower()] for t, v in judged.sums.items() if not v and t.lower() in column}
    assert set(ok) >= probe_ok & set(ps.COUNTED) and set(off) >= probe_off & set(ps.COUNTED)


def test_a_typical_match_carries_everything_and_adds_up() -> None:
    a = answer("typical")
    assert a.halves and len(a.teams) == 2
    assert {"corners", "shots", "yellow_cards", "red_cards", "possession_pct", "expected_goals", "saves", "fouls",
            "offsides"} <= set(a.filled())
    ok, off = a.sums()
    assert {"corners", "shots", "yellow_cards"} <= set(ok) and not off
    first = a.teams[0].first
    assert first is not None and isinstance(first["possession_pct"], Decimal) and isinstance(first["corners"], int)


def test_an_empty_figure_is_not_a_zero() -> None:
    """Serie A: fouls and red cards come ``null`` in both halves: not filled, and the value is None, never 0."""
    a = answer("no_fouls")
    assert "fouls" not in a.filled() and "red_cards" not in a.filled()
    for team in a.teams:
        assert team.first is not None and team.first["fouls"] is None and team.second is not None and team.second["red_cards"] is None
    assert "corners" in a.filled()


def test_expected_goals_missing_in_k_league() -> None:
    a = answer("kleague")
    assert "expected_goals" not in a.filled() and "corners" in a.filled()
    assert "expected_goals" not in answer("no_xg").filled()


def test_a_sum_that_does_not_add_up_is_named() -> None:
    ok, off = answer("sum_off").sums()
    assert "shots_blocked" in off and "corners" in ok


def test_an_answer_without_a_half_is_not_halves() -> None:
    fixture, body = load("typical")
    broken = json.loads(json.dumps(body))
    del broken["response"][1]["statistics_2h"]
    a = ps.parse_period_answer(broken, fixture)
    assert not a.halves and a.outcome == "without_halves" and a.filled() == frozenset() and a.sums() == (frozenset(), frozenset())
    assert a.teams[0].second is not None and a.teams[1].second is None, "the half it did give is kept for the rows"
    empty_block = json.loads(json.dumps(body))
    empty_block["response"][0]["statistics_1h"] = []
    assert ps.parse_period_answer(empty_block, fixture).outcome == "without_halves"
    assert ps.parse_period_answer({"response": []}, fixture).outcome == "empty"
    assert ps.parse_period_answer({}, fixture).outcome == "empty"
    one_team = json.loads(json.dumps(body))
    one_team["response"] = one_team["response"][:1]
    assert ps.parse_period_answer(one_team, fixture).outcome == "without_halves", "a half needs both teams"


def test_a_value_is_read_like_the_match_statistics_are() -> None:
    body = {"response": [{"team": {"id": 1}, "statistics": [{"type": "Ball Possession", "value": "61%"}, {"type": "Corner Kicks", "value": 4},
                                                              {"type": "Free Kicks", "value": 3}, {"type": "Fouls", "value": ""}],
                          "statistics_1h": [{"type": "Ball Possession", "value": "57%"}, {"type": "Corner Kicks", "value": 0}],
                          "statistics_2h": [{"type": "Ball Possession", "value": "65%"}, {"type": "Corner Kicks", "value": 4}]}]}
    team = ps.parse_period_answer(body, 9).teams[0]
    assert team.total is not None and team.total["possession_pct"] == Decimal(61) and team.total["fouls"] is None
    assert "free_kicks" not in team.total and len(team.total) == 3
    assert team.first is not None and team.first["corners"] == 0, "zero stays zero"


@pytest.mark.parametrize(("asked", "filled", "expect"), [
    (4, {"corners": 4}, "probation"),
    (5, {"corners": 5}, "build"),
    (10, {"corners": 9, "fouls": 5}, "build"),
    (10, {"corners": 8, "fouls": 5}, "closed"),
    (0, {}, "probation"),
    (100, {"corners": 90}, "build"),
    (100, {"corners": 89}, "closed"),
])
def test_the_gate_of_a_competition(asked: int, filled: dict[str, int], expect: str) -> None:
    assert rules.gate(asked, filled) == expect


def test_a_statistic_is_built_at_ninety_percent_and_five_matches_never_lower() -> None:
    assert rules.built(10, {"corners": 9}, "corners")
    assert not rules.built(10, {"corners": 8}, "corners"), "80 % is not 90 %: the probe's rule is not lowered"
    assert not rules.built(4, {"corners": 4}, "corners"), "four matches asked: no decision"
    assert not rules.built(10, {"corners": 10}, "nonexistent")
    assert rules.built(110, {"corners": 99}, "corners"), "exactly 90 %: no float rounding decides it"
    d = rules.decide(20, {"corners": 18, "fouls": 17})
    assert d["corners"].build and not d["fouls"].build and d["corners"].share == 0.9
