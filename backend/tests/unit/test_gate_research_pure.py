"""The arithmetic of the gate of research v2 (``fbi.ai.gate_research``) that needs no database: what counts as the same fact for v1 and for
research v2, how the shares are made, what a report says. The gate on a built world is ``tests/integration/test_gate_research.py``."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from fbi.ai import gate_research as g
from fbi.ai.gate_a import Check

NOW = datetime(2032, 10, 20, 17, 0, tzinfo=UTC)


# ── the same fact, said by v1 and by research v2 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("assertion", "kind", "want"), [
    ("out", "injury", "out"),
    ("out", "suspension", "out"),  # a suspended player and an injured one are both out
    ("doubtful", "doubtful", "doubtful"),
    ("doubtful", "injury", "doubtful"),
    ("available", "injury", "plays"),
    ("starts", "lineup", "plays"),
])
def test_what_is_said_about_a_player_is_out_in_doubt_or_plays(assertion: str, kind: str, want: str) -> None:
    assert g.fact_of("home", kind, assertion, "A. Striker") == ("home", "striker", want)


def test_a_player_is_his_surname_whatever_the_spelling() -> None:
    names = ["Alexandre Lacazette", "A. Lacazette", "lacazette", "Álexandre  Lacazette"]
    assert {g.fact_of("away", "injury", "out", n) for n in names} == {("away", "lacazette", "out")}


@pytest.mark.parametrize(("kind", "want"), [("coach", "coach"), ("lineup", "lineup"), ("schedule", "schedule"), ("news", "news"),
                                            ("other", "news"), ("injury", "news"), ("suspension", "news")])
def test_what_says_nothing_about_who_plays_is_a_fact_of_the_side_by_its_kind(kind: str, want: str) -> None:
    assert g.fact_of("home", kind, "info", None) == ("home", "team", want)


def test_a_player_named_in_a_piece_of_information_is_not_a_fact_about_who_plays() -> None:
    """«Striker is in great form» (assertion ``info``) says nothing about availability: it is news about the side, however many players it names."""
    assert g.fact_of("home", "news", "info", "A. Striker") == ("home", "team", "news")
    assert g.fact_of("home", "news", "info", "B. Midfielder") == ("home", "team", "news")


def test_an_item_without_a_player_that_says_a_player_is_out_is_a_fact_about_the_team() -> None:
    assert g.fact_of("away", "injury", "out", None) == ("away", "team", "out")
    assert g.fact_of("away", "injury", "out", "") == ("away", "team", "out")


def row(**over: object) -> dict[str, object]:
    return {"fixture_id": 1, "home_team_id": 10, "away_team_id": 20, "team_id": 10, "kind": "injury",
            "attributes": {"player_name": "A. Striker", "assertion": "out"}} | over


def test_the_side_of_an_item_is_the_side_of_its_team_and_an_item_of_no_side_is_a_fact_of_the_match() -> None:
    assert g._facts([row()]) == {(1, "home", "striker", "out")}
    assert g._facts([row(team_id=20)]) == {(1, "away", "striker", "out")}
    assert g._facts([row(team_id=None)]) == {(1, "match", "striker", "out")}, "it is not a fact of either side"
    assert g._facts([row(team_id=30)]) == {(1, "match", "striker", "out")}


def test_an_item_that_does_not_say_what_it_asserts_is_information_not_an_absence() -> None:
    """Rows written before the assertion existed, or by a collector that did not set it: «injury» in the kind alone says nothing about who plays."""
    assert g._facts([row(attributes={"player_name": "A. Striker"})]) == {(1, "home", "team", "news")}
    assert g._facts([row(attributes=None)]) == {(1, "home", "team", "news")}
    assert g._facts([row(attributes={"assertion": "out"}, kind="coach")]) == {(1, "home", "team", "out")}


# ── the shares ───────────────────────────────────────────────────────────────────────────────────────────────────────

def facts(*items: tuple[int, str, str, str]) -> frozenset[g.Fact]:
    return frozenset(items)


def test_coverage_is_the_share_of_the_facts_of_v1_that_research_v2_also_found() -> None:
    v1 = facts((1, "home", "striker", "out"), (1, "away", "team", "news"), (2, "home", "keeper", "doubtful"), (2, "home", "team", "coach"))
    v2 = facts((1, "home", "striker", "out"), (2, "home", "keeper", "doubtful"), (2, "home", "team", "coach"), (2, "away", "team", "news"))
    c = g.Coverage(2, v1, v2)
    assert c.rate == Decimal("0.7500") and c.found == facts((1, "home", "striker", "out"), (2, "home", "keeper", "doubtful"),
                                                            (2, "home", "team", "coach"))
    assert c.missed == [(1, "away", "team", "news")]
    assert c.rate_players == Decimal("1.0000"), "both facts about players were found"
    j = c.as_json()
    assert j["coverage_pct"] == "75.00" and j["only_v2"] == 1 and j["facts_per_match_v1"] == 2.0 and j["facts_per_match_v2"] == 2.0


def test_a_fact_found_for_another_match_is_not_found() -> None:
    c = g.Coverage(2, facts((1, "home", "striker", "out")), facts((2, "home", "striker", "out")))
    assert c.rate == Decimal("0.0000") and c.missed == [(1, "home", "striker", "out")]


def test_a_fact_of_the_other_side_is_not_found() -> None:
    c = g.Coverage(1, facts((1, "home", "striker", "out")), facts((1, "away", "striker", "out")))
    assert c.rate == Decimal("0.0000")


def test_coverage_of_players_leaves_out_the_facts_of_the_team() -> None:
    v1 = facts(*((1, "home", f"p{k}", "out") for k in range(10)), *((1, "home", "team", c) for c in ("coach", "lineup", "news", "schedule")))
    v2 = facts(*((1, "home", f"p{k}", "out") for k in range(9)), *((1, "home", "team", c) for c in ("coach", "lineup", "news", "schedule")))
    c = g.Coverage(1, v1, v2)
    assert c.rate == Decimal("0.9286") and c.rate_players == Decimal("0.9000")


def test_with_no_facts_of_v1_there_is_no_share() -> None:
    c = g.Coverage(0, facts(), facts((1, "home", "team", "news")))
    assert c.rate is None and c.rate_players is None
    assert g.check_coverage(c).ok is None and g.check_players(c).ok is None


def test_the_gate_asks_95_percent_of_all_the_facts_and_95_percent_of_those_about_players() -> None:
    players = [(1, "home", f"p{k}", "out") for k in range(20)]
    team = [(1, "away", "team", "news")] * 1 + [(k, "away", "team", "news") for k in range(2, 82)]  # 80 + 1 distinct facts of the sides
    v1 = facts(*players, *team)
    just_enough = g.Coverage(1, v1, v1 - {players[0], players[1]})  # 2 of 101: 98.02 % of all, 90 % of the players
    assert just_enough.rate is not None and just_enough.rate >= g.COVERAGE_MIN
    assert g.check_coverage(just_enough).ok is True
    assert g.check_players(just_enough).ok is False, "ninety percent of the players is not enough even when the whole is"
    exactly = g.Coverage(1, v1, v1)
    assert g.check_coverage(exactly).ok is True and g.check_players(exactly).ok is True


def test_95_percent_exactly_passes_and_one_fact_less_does_not() -> None:
    v1 = facts(*((k, "home", "team", "news") for k in range(100)))
    at = g.Coverage(100, v1, frozenset(sorted(v1)[:95]))
    below = g.Coverage(100, v1, frozenset(sorted(v1)[:94]))
    assert at.rate == Decimal("0.9500") and g.check_coverage(at).ok is True
    assert below.rate == Decimal("0.9400") and g.check_coverage(below).ok is False


def test_exactly_95_percent_of_the_players_passes_and_one_less_does_not() -> None:
    v1 = facts(*((1, "home", f"p{k}", "out") for k in range(100)))
    at = g.Coverage(1, v1, frozenset(sorted(v1)[:95]))
    below = g.Coverage(1, v1, frozenset(sorted(v1)[:94]))
    assert at.rate_players == Decimal("0.9500") and g.check_players(at).ok is True
    assert below.rate_players == Decimal("0.9400") and g.check_players(below).ok is False


def test_the_sample_counts_the_matches_v1_found_facts_for_not_the_matches_of_the_week() -> None:
    thin = g.Coverage(40, facts(*((m % 3, "home", f"p{m}", "out") for m in range(80))), facts())
    assert g.check_sample(thin).ok is None, "forty matches in the week, and facts of v1 for three of them: there is nothing to compare for the rest"
    assert g.check_sample(thin).detail["fixtures_with_facts_of_v1"] == 3


def test_the_sample_must_have_enough_matches_and_facts() -> None:
    few_matches = g.Coverage(10, facts(*((1, "home", f"p{k}", "out") for k in range(80))), facts())
    assert g.check_sample(few_matches).ok is None, "80 facts of a single match are not a sample"
    few_facts = g.Coverage(40, facts(*((m, "home", "team", "news") for m in range(40))), facts())
    assert g.check_sample(few_facts).ok is None
    enough = g.Coverage(40, facts(*((m, side, "team", "news") for m in range(40) for side in ("home", "away"))), facts())
    assert g.check_sample(enough).ok is True


def test_the_floors_of_the_sample_are_inclusive() -> None:
    def sample(fixtures: int, n: int) -> g.Coverage:
        return g.Coverage(fixtures, facts(*((m % fixtures, "home", f"p{m}", "out") for m in range(n))), facts())

    assert g.check_sample(sample(g.MIN_FIXTURES, g.MIN_FACTS)).ok is True
    assert g.check_sample(sample(g.MIN_FIXTURES - 1, g.MIN_FACTS)).ok is None
    assert g.check_sample(sample(g.MIN_FIXTURES, g.MIN_FACTS - 1)).ok is None


def test_searches_are_compared_by_what_research_v2_would_have_paid_alone() -> None:
    s = g.Searches(totals=Counter({"web_searches": 10, "v2_paid": 3, "v2_shared": 5, "v2_reused": 6, "v2_demand": 8}))
    assert s.v1 == 10 and s.v2_alone == 8, "what the cache answered would have been paid for without v1 beside it"
    assert g.check_searches(s).ok is True
    assert s.reuse == Decimal("0.4286")
    assert s.as_json()["saved"] == 2 and s.as_json()["saved_pct"] == "20.00"


def test_as_many_searches_as_v1_is_not_fewer() -> None:
    s = g.Searches(totals=Counter({"web_searches": 10, "v2_paid": 4, "v2_shared": 6}))
    assert s.v2_alone == 10 and g.check_searches(s).ok is False


def test_with_no_search_of_v1_there_is_nothing_to_compare() -> None:
    assert g.check_searches(g.Searches()).ok is None
    assert g.check_searches(g.Searches(totals=Counter({"v2_paid": 3}))).ok is None


# ── what a report says ───────────────────────────────────────────────────────────────────────────────────────────────

def window(stable: int) -> g.Window:
    return g.Window(date(2032, 10, 13), date(2032, 10, 19), None if not stable else date(2032, 10, 19 - stable + 1), "x", stable,
                    date(2032, 10, 20 + 8 - max(stable, 0) - 1))


def test_only_a_pass_or_a_failure_is_recordable() -> None:
    for verdict, recordable in ((g.PASS, True), (g.FAIL, True), (g.PENDING_TIME, False)):
        assert g.GateReport(verdict, NOW, window(7)).recordable is recordable


def test_the_report_names_its_verdict_the_window_and_what_each_check_said() -> None:
    report = g.GateReport(g.FAIL, NOW, window(7), (Check("coverage", "Research v2 encontró ≥ 95 %", False, {}), Check("sample", "muestra", None, {})),
                          pending=("nada",), consequence="se corrige")
    lines = report.lines()
    assert lines[0] == "GATE DE RESEARCH V2 · NO PASA"
    assert "2032-10-13 a 2032-10-19" in lines[1]
    assert "  [NO] Research v2 encontró ≥ 95 %" in lines and "  [PENDIENTE] muestra" in lines
    assert "  Falta: nada" in lines and lines[-1] == "Consecuencia: se corrige"
    doc = report.as_json()
    assert doc["gate"] == "research_v2" and doc["recorded_only_if"] == "PASA or NO PASA" and [c["id"] for c in doc["checks"]] == ["coverage", "sample"]


def test_a_claim_out_of_the_shadow_is_answered_with_the_switch_off_and_the_rest_with_a_better_comparison() -> None:
    leak = g.consequence([Check("shadow_invisible", "x", False, {})])
    assert "FBI_AI_RESEARCH_V2=off" in leak
    other = g.consequence([Check("coverage", "x", False, {}), Check("fewer_searches", "y", False, {})])
    assert "sigue en sombra" in other and "FBI_AI_RESEARCH_V2=off" not in other
    assert "vuelve a empezar" in leak and "vuelve a empezar" in other


def test_the_window_is_seven_days_and_the_floors_can_only_make_the_gate_harder() -> None:
    assert g.WINDOW_DAYS == 7 and Decimal("0.95") == g.COVERAGE_MIN, "the plan: ≥ 95 % of v1's evidences, one week in parallel"
    assert (g.MIN_FIXTURES, g.MIN_FACTS) == (30, 50), "the floors that the guide of the owner states: changing them is changing that guide"
    assert g.MIN_FACTS >= g.MIN_FIXTURES


# ── the command line ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_command_line_has_one_command_and_the_options_of_gate_a_that_make_sense_here() -> None:
    from scripts import ia_research_gate as cli

    assert cli.parse_day("2026-11-03") == date(2026, 11, 3)
    with pytest.raises(ValueError, match="not a day"):
        cli.parse_day("3 Nov")
    args = cli.build_parser().parse_args(["evaluate", "--through", "2026-11-03", "--changed-on", "2026-11-01", "--changed-on", "2026-11-02",
                                          "--record", "--json", "--dsn", "postgresql://x"])
    assert (args.command, args.through, args.changed_on, args.record, args.as_json, args.dsn) == \
        ("evaluate", "2026-11-03", ["2026-11-01", "2026-11-02"], True, True, "postgresql://x")
    assert cli.COMMANDS == ("evaluate",)
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["revert", "research_v2"])
    assert (cli.OK, cli.NO, cli.CANNOT, cli.PENDING) == (0, 1, 2, 3)
