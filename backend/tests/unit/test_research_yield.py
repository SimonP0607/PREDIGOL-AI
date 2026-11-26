"""RP-9.8: the counters of EXP-E8 (``research-yield-v1``): level of each match, cost by the ledger's research path, facts, and the sample check."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fbi.ai import cost_paths
from fbi.ai import research_yield as ry
from fbi.research import exp_protocol

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def entry(fid: int, *, league: int | None, tier: int | None, market: bool) -> dict[str, object]:
    return {
        "fixture_id": fid,
        "kickoff_at": "2026-11-27T20:00:00+00:00",
        "competition_id": 1,
        "competition": "X",
        "country": None,
        "tier": tier,
        "home": "H",
        "away": "A",
        "has_market": market,
        "odds_at": None,
        "n_bookmakers": None,
        "priority": 1.0,
        "important": False,
        "provider_league_id": league,
    }


def call(
    cid: int,
    *,
    fixture: int | None,
    purpose: str,
    usd: str,
    tier: str = "bulk",
    prompt: str | None = None,
) -> cost_paths.Call:
    return cost_paths.Call(cid, NOW, purpose, tier, "p", "m", prompt, "ok", Decimal(usd), fixture)


def test_the_protocol_names_the_same_criteria() -> None:
    assert exp_protocol.E8.segments == ry.CRITERIA
    assert exp_protocol.E8.min_sample.startswith(
        f"{ry.REQUIRED_PER_CRITERION} partidos por criterio"
    )


def test_levels_follow_the_research_order() -> None:
    plans = [
        [
            entry(1, league=239, tier=3, market=False),
            entry(2, league=None, tier=1, market=True),
            entry(3, league=None, tier=3, market=True),
            entry(4, league=None, tier=None, market=False),
        ]
    ]
    assert ry.levels(plans) == {1: "A", 2: "B", 3: "C", 4: "D"}


def test_only_the_research_calls_with_a_match_are_costed() -> None:
    calls = [
        call(1, fixture=7, purpose="web_search", usd="0.01", tier="search"),
        call(2, fixture=7, purpose="evidence_extraction", usd="0.002"),
        call(3, fixture=7, purpose="pick_review", usd="0.5"),
        call(4, fixture=None, purpose="web_search", usd="0.01", tier="search"),
    ]
    assert ry.costs(calls) == {7: (Decimal("0.012"), 2)}


def test_a_match_with_no_cost_and_no_fact_is_not_in_a_divisor() -> None:
    rows = ry.matches({1: "A", 2: "A", 3: "B"}, {1: (Decimal("0.10"), 3)}, {1: (4, 2), 3: (0, 0)})
    doc = ry.report(rows, since=NOW, until=NOW)
    a = doc["levels"]["A"]
    assert (a["matches"], a["researched"], a["not_researched"], a["facts"], a["confirmed"]) == (
        2,
        1,
        1,
        4,
        2,
    )
    assert (
        a["confirmed_per_match"] == 2.0
        and abs(a["confirmed_per_usd"] - 20.0) < 1e-9
        and a["confirmed_share"] == 0.5
    )
    assert doc["levels"]["B"]["researched"] == 0 and doc["levels"]["B"]["confirmed_per_usd"] is None


def test_the_sample_check_does_not_let_a_few_matches_pass() -> None:
    few = ry.report(
        ry.matches({1: "A"}, {1: (Decimal("0.1"), 1)}, {1: (1, 1)}), since=NOW, until=NOW
    )
    assert few["progress"]["enough"] is False and "insuficiente" in "\n".join(ry.lines(few))
    many = ry.report(
        [ry.Match(i, "B", Decimal("0.01"), 1, 1, 1) for i in range(300)], since=NOW, until=NOW
    )
    assert many["progress"]["enough"] is True and "suficiente" in "\n".join(ry.lines(many))


def test_a_cost_with_no_confirmed_fact_gives_no_ratio_per_dollar_but_a_cost_per_fact() -> None:
    doc = ry.report(
        ry.matches({1: "A"}, {1: (Decimal("0.5"), 2)}, {1: (3, 0)}), since=NOW, until=NOW
    )
    assert doc["total"]["confirmed_per_usd"] == 0.0 and doc["total"]["usd_per_confirmed"] is None
