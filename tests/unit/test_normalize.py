"""Normalisation: drop what cannot be parsed, never substitute it.

The legacy `_parse_avg` fell back to the season TOTAL when the per-match average
was missing, producing expected_goals of 108.0, 94.0, 90.0, 55.0 and 15.0 goals
per match. Those values then drove the Over/Under heuristic. The tests below
pin the opposite behaviour: unparsable input disappears and is counted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.providers.api_football.normalize import (
    iter_fixtures,
    iter_odds,
    minutes_to_kickoff,
)

KICKOFF = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 15, 18, 48, tzinfo=UTC)


def payload(values: list[dict], bet_id: int = 1) -> dict:
    return {
        "response": [
            {
                "fixture": {"id": 1001},
                "bookmakers": [
                    {"id": 8, "name": "Bet365", "bets": [{"id": bet_id, "name": "x", "values": values}]}
                ],
            }
        ]
    }


def quotes(values: list[dict], bet_id: int = 1, **kwargs: object) -> list:
    return list(
        iter_odds(
            payload(values, bet_id),
            kickoff_at=KICKOFF,
            captured_at=CAPTURED,
            payload_hash="h1",
            source="prematch",
            **kwargs,  # type: ignore[arg-type]
        )
    )


def test_a_1x2_payload_becomes_three_quotes() -> None:
    result = quotes([{"value": "Home", "odd": "2.10"}, {"value": "Draw", "odd": "3.40"}, {"value": "Away", "odd": "3.60"}])
    assert [q.selection for q in result] == ["Home", "Draw", "Away"]
    assert result[0].odds_decimal == Decimal("2.10")
    assert result[0].line == Decimal("0"), "a market without a line stores 0, never NULL"
    assert result[0].minutes_to_ko == 12
    assert result[0].payload_hash == "h1"


def test_over_under_keeps_its_line() -> None:
    result = quotes(
        [{"value": "Over 2.5", "odd": "1.90"}, {"value": "Under 2.5", "odd": "1.95"}], bet_id=5
    )
    assert [(q.selection, q.line) for q in result] == [
        ("Over", Decimal("2.5")),
        ("Under", Decimal("2.5")),
    ]


def test_two_different_lines_do_not_collapse_into_one() -> None:
    """If the line were defaulted to 0, Over 1.5 and Over 3.5 would become the
    same row and the PK would silently discard one of them."""
    result = quotes(
        [{"value": "Over 1.5", "odd": "1.30"}, {"value": "Over 3.5", "odd": "4.20"}], bet_id=5
    )
    assert {q.line for q in result} == {Decimal("1.5"), Decimal("3.5")}


@pytest.mark.parametrize(
    "value",
    [
        {"value": "Over", "odd": "1.90"},          # OU with no line -> dropped, not defaulted to 0
        {"value": "Over 2.5", "odd": "not-a-number"},
        {"value": "Over 2.5", "odd": None},
        {"value": None, "odd": "1.90"},
    ],
)
def test_unparsable_values_are_dropped_not_guessed(value: dict) -> None:
    assert quotes([value], bet_id=5) == []


@pytest.mark.parametrize("odd", ["1.0", "0.5", "-2.0", "1000", "0"])
def test_implausible_prices_are_dropped(odd: str) -> None:
    assert quotes([{"value": "Home", "odd": odd}]) == []


def test_an_unknown_selection_label_is_dropped() -> None:
    assert quotes([{"value": "Definitely Home", "odd": "2.10"}]) == []


def test_double_chance_labels_are_canonicalised() -> None:
    result = quotes(
        [{"value": "Home/Draw", "odd": "1.30"}, {"value": "Draw/Away", "odd": "1.45"}], bet_id=12
    )
    assert [q.selection for q in result] == ["1X", "X2"]


def test_untracked_markets_are_ignored() -> None:
    assert quotes([{"value": "Home", "odd": "2.10"}], market_filter={"OU"}) == []
    assert len(quotes([{"value": "Home", "odd": "2.10"}], market_filter={"1X2"})) == 1


def test_an_unmapped_bet_id_is_ignored() -> None:
    assert quotes([{"value": "Home", "odd": "2.10"}], bet_id=9999) == []


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        (datetime(2026, 9, 15, 18, 48, tzinfo=UTC), 12),
        (datetime(2026, 9, 14, 19, 0, tzinfo=UTC), 1440),
        (datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 0),
        (datetime(2026, 9, 15, 19, 30, tzinfo=UTC), 0),  # never negative
    ],
)
def test_minutes_to_kickoff(captured: datetime, expected: int) -> None:
    assert minutes_to_kickoff(KICKOFF, captured) == expected


def test_a_malformed_payload_yields_nothing_instead_of_raising() -> None:
    for body in ({}, {"response": None}, {"response": [None]}, {"response": [{"bookmakers": None}]}):
        assert list(
            iter_odds(
                body, kickoff_at=KICKOFF, captured_at=CAPTURED, payload_hash="h", source="prematch"
            )
        ) == []


def test_fixtures_are_parsed_and_bad_rows_skipped() -> None:
    body = {
        "response": [
            {
                "fixture": {"id": 1001, "date": "2026-09-15T19:00:00+00:00", "status": {"short": "NS"}},
                "league": {"id": 39, "season": 2025},
                "teams": {"home": {"id": 33}, "away": {"id": 40}},
            },
            {"fixture": {"id": 2}, "league": {}, "teams": {}},
        ]
    }
    result = list(iter_fixtures(body))
    assert len(result) == 1
    assert result[0].provider_fixture_id == 1001
    assert result[0].provider_league_id == 39
    assert result[0].kickoff_at == KICKOFF
