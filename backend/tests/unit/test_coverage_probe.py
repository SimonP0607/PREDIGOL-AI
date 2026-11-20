"""PM-01-04 and PM-01-05: the coverage probes judge the provider's answers without a database or a request."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from scripts.coverage_probe import (
    BUILD_SHARE,
    HALF_LEAGUES,
    KEY_TYPES,
    MIN_SAMPLE,
    ODDS_LEAGUES,
    CompetitionHalves,
    OddsEvidence,
    OddsLive,
    build_parser,
    classify,
    half_targets,
    judge_half,
    judge_odds_fixture,
    odds_calls,
    render_half,
    render_odds,
)


def stats(**values: Any) -> list[dict[str, Any]]:
    return [{"type": k.replace("_", " ") if k != "expected_goals" else k, "value": v} for k, v in values.items()]


def team(total: dict[str, Any], first: dict[str, Any] | None, second: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"team": {"id": 1}, "statistics": stats(**total)}
    if first is not None:
        out["statistics_1h"] = stats(**first)
    if second is not None:
        out["statistics_2h"] = stats(**second)
    return out


FULL = {"Corner_Kicks": 5, "Fouls": 7, "expected_goals": "1.3", "Ball_Possession": "76%"}
H1 = {"Corner_Kicks": 2, "Fouls": 2, "expected_goals": "0.54", "Ball_Possession": "76%"}
H2 = {"Corner_Kicks": 3, "Fouls": 5, "expected_goals": "0.76", "Ball_Possession": "76%"}


def test_an_answer_with_both_halves_and_all_types() -> None:
    answer = judge_half({"response": [team(FULL, H1, H2), team(FULL, H1, H2)]})
    assert answer.answered and answer.halves
    assert answer.empty == frozenset()
    assert {"Corner Kicks", "Fouls", "expected_goals"} <= answer.present
    assert answer.sums["Corner Kicks"] and answer.sums["Fouls"]


def test_fouls_empty_in_a_half_are_not_delivered_never_zero() -> None:
    """The Champions and Primera A answers of 19 Nov 2026: fouls null by half."""
    h1 = {**H1, "Fouls": None}
    answer = judge_half({"response": [team(FULL, h1, H2), team(FULL, H1, H2)]})
    assert answer.halves
    assert answer.empty == frozenset({"Fouls"})
    assert "Fouls" not in answer.sums


def test_no_halves_and_no_answer() -> None:
    without = judge_half({"response": [team(FULL, None, None), team(FULL, None, None)]})
    assert without.answered and not without.halves and without.empty == without.present
    nothing = judge_half({"response": [], "results": 0})
    assert not nothing.answered and not nothing.halves


def test_halves_that_do_not_add_up_are_reported() -> None:
    answer = judge_half({"response": [team(FULL, {**H1, "Corner_Kicks": 4}, H2), team(FULL, H1, H2)]})
    assert answer.sums["Corner Kicks"] is False


def test_the_decision_per_datum_needs_the_share_and_a_sample() -> None:
    comp = CompetitionHalves(239, "Primera A")
    assert comp.decision("Corner Kicks") == "sin muestra"
    good = judge_half({"response": [team(FULL, H1, H2), team(FULL, H1, H2)]})
    fouls_empty = judge_half({"response": [team(FULL, {**H1, "Fouls": None}, H2), team(FULL, H1, H2)]})
    for _ in range(MIN_SAMPLE):
        comp.add(good)
    comp.add(fouls_empty)
    assert comp.share_halves() == 1.0
    assert comp.decision("Corner Kicks") == "construir"
    assert comp.share_filled("Fouls") == MIN_SAMPLE / (MIN_SAMPLE + 1)
    assert (comp.decision("Fouls") == "construir") is (MIN_SAMPLE / (MIN_SAMPLE + 1) >= BUILD_SHARE)
    assert comp.decision("Red Cards") == "no construir"
    text = render_half([comp], since=datetime(2026, 11, 19, tzinfo=UTC), until=datetime(2026, 11, 26, tzinfo=UTC),
                       at=datetime(2026, 11, 20, tzinfo=UTC), pending=0)
    assert "Primera A (239)" in text and all(t in text for t in KEY_TYPES)
    assert comp.as_dict()["types"]["Corner Kicks"]["decision"] == "construir"


def test_targets_are_finished_unasked_and_settled() -> None:
    at = datetime(2026, 11, 20, 12, tzinfo=UTC)
    rows = [{"fixture": 1, "asked": False, "kickoff_at": at - timedelta(hours=5)},
            {"fixture": 2, "asked": True, "kickoff_at": at - timedelta(hours=5)},
            {"fixture": 3, "asked": False, "kickoff_at": at - timedelta(hours=1)}]
    assert [r["fixture"] for r in half_targets(rows, at=at)] == [1]


def test_odds_causes() -> None:
    nothing_live = OddsLive()
    # odds: false and every match priced -> the flag is wrong
    assert classify(False, OddsEvidence(36, 36, 36, 36), nothing_live)[0] == "bandera_falsa_publica"
    # odds: true, tracked two days ago: almost nothing asked
    assert classify(True, OddsEvidence(30, 2, 2, 6), OddsLive(league_results=3, fixtures_asked=2,
                                                              fixtures_with_prices=2))[0] == "no_se_pidio"
    # odds: true, asked nearly all, prices for few: the provider does not publish them
    assert classify(True, OddsEvidence(92, 87, 12, 13), nothing_live)[0] == "no_publica"
    # no finished match: today's answers decide
    assert classify(False, OddsEvidence(0, 0, 0, 0), OddsLive(league_results=40))[0] == "bandera_falsa_publica"
    assert classify(True, OddsEvidence(0, 0, 0, 0), OddsLive(league_results=0, fixtures_asked=1))[0] == "no_publica"
    assert classify(True, OddsEvidence(0, 0, 0, 0), nothing_live)[0] == "sin_evidencia"


def test_an_odds_fixture_answer() -> None:
    body = {"response": [{"bookmakers": [{"id": 8, "bets": [{"id": 1, "values": []}, {"id": 5}]},
                                         {"id": 11, "bets": []}]}]}
    assert judge_odds_fixture(body) == (True, True, {8})
    assert judge_odds_fixture({"response": []}) == (False, False, set())
    rows = [{"league": 3, "name": "UEFA Europa League", "flag": False, "cause": "bandera_falsa_publica", "why": "x"}]
    assert "**bandera_falsa_publica**" in render_odds(rows, at=datetime(2026, 11, 20, tzinfo=UTC), requests=4)


def test_the_lists_and_the_command_line() -> None:
    assert len(HALF_LEAGUES) == 12 and {239, 2, 13} <= set(HALF_LEAGUES)
    assert len(ODDS_LEAGUES) == 21 == len(set(ODDS_LEAGUES))
    args = build_parser().parse_args(["half", "run", "--max-requests", "40", "--since", "2026-11-19"])
    assert (args.probe, args.command, args.max_requests) == ("half", "run", 40)
    assert args.since == datetime(2026, 11, 19, tzinfo=UTC)
    assert build_parser().parse_args(["odds"]).max_requests == 60


def test_the_odds_requests_put_every_league_page_first_and_take_matches_in_turn() -> None:
    """PM-01-04: one page per competition first, then the matches one competition at a time in turn; a 60-request cap cuts
    matches, never a competition."""
    meta: dict[int, dict[str, Any]] = {1: {"season": 2026}, 2: {"season": 2026}, 3: {"season": None}}
    ahead = {1: [11, 12, 13], 2: [21], 3: [31, 32]}
    calls = odds_calls([1, 2, 3], meta, ahead)
    assert [(k, lg) for k, lg, _ in calls] == [("league", 1), ("league", 2), ("fixture", 1), ("fixture", 2),
                                                 ("fixture", 3), ("fixture", 1), ("fixture", 3), ("fixture", 1)]
    assert calls[0][2] == {"league": "1", "season": "2026"} and calls[2][2] == {"fixture": "11"}
    every = odds_calls(list(ODDS_LEAGUES), {lg: {"season": 2026} for lg in ODDS_LEAGUES},
                       {lg: [lg * 10 + i for i in range(3)] for lg in ODDS_LEAGUES})
    assert len(every) == 84 and {lg for k, lg, _ in every[:60] if k == "league"} == set(ODDS_LEAGUES)
