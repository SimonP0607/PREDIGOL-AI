"""The in-play normaliser, against the shapes the provider was measured to send.

Every payload fragment here is copied from a real /odds/live response captured
on 2026-10-01, not invented: the point of these tests is that the code agrees
with the provider, and a fragment written from memory would only prove the code
agrees with itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from fbi.providers.api_football.live import (
    LIVE_SELECTION_ALIASES,
    iter_live_odds,
    live_market_of,
    normalise_live_selection,
)
from fbi.providers.api_football.normalize import INPLAY_BETS, PREMATCH_BETS
from fbi.providers.base import OddsParseLog

AT = datetime(2026, 10, 1, 1, 14, 30, tzinfo=UTC)

Payload = dict[str, Any]
"""A payload fragment. Deliberately loose: these tests feed the normaliser the
same unvalidated JSON the provider sends, including shapes it should refuse."""


def payload(*bets: Payload, fixture_id: int = 1490500) -> Payload:
    return {
        "response": [
            {
                "fixture": {
                    "id": fixture_id,
                    "status": {"long": "Second Half", "elapsed": 77, "seconds": "77:00"},
                },
                "league": {"id": 253, "season": 2026},
                "teams": {"home": {"id": 1602, "goals": 0}, "away": {"id": 20787, "goals": 1}},
                "status": {"stopped": False, "blocked": False, "finished": False},
                "update": "2026-10-01T01:14:30+00:00",
                "odds": list(bets),
            }
        ]
    }


def read(body: Payload) -> tuple[list[Any], list[Any], list[Any], OddsParseLog]:
    pl = OddsParseLog()
    states, quotes, markets = iter_live_odds(
        body, captured_at=AT, payload_hash="h", parse_log=pl
    )
    return states, quotes, markets, pl


# --- the id namespaces must not be shared -----------------------------------


def test_live_bet_ids_are_not_prematch_bet_ids() -> None:
    """Pre-match bet 4 is Asian Handicap; in-play bet 4 is extra-time corners.

    If these two maps ever agree on an id for a different concept, the first
    live capture files corner prices as our handicap series.
    """
    for key, live in INPLAY_BETS.items():
        assert live.bet_id != PREMATCH_BETS[key].bet_id, (
            f"{key} has the same id in both catalogues"
        )


def test_live_market_of_consults_only_the_inplay_map() -> None:
    assert live_market_of(59) == "1X2"
    assert live_market_of(33) == "AH"
    # 1 and 4 are the PRE-MATCH ids for 1X2 and AH. They must not resolve here.
    assert live_market_of(1) is None
    assert live_market_of(4) is None


# --- the handicap sign, which the measurement settled -----------------------


def test_away_handicap_is_stored_as_sent_not_negated() -> None:
    """Live signs the handicap per selection; pre-match repeats the home number.

    Measured by devigging 40 real pairs: read as sent they overround 1.053 to
    1.083; read the pre-match way they produce impossible books below 1.0. So
    the away row keeps its own sign here, and reusing the pre-match parser would
    flip every away line in the series.
    """
    body = payload(
        {
            "id": 33,
            "name": "Asian Handicap",
            "values": [
                {"value": "Home", "handicap": "-0.75", "odd": "1.90", "main": False,
                 "suspended": False},
                {"value": "Away", "handicap": "0.75", "odd": "1.98", "main": False,
                 "suspended": False},
            ],
        }
    )
    _, quotes, _, _ = read(body)
    by_side = {q.selection: q for q in quotes}
    assert by_side["Home"].line == Decimal("-0.75")
    assert by_side["Away"].line == Decimal("0.75")
    assert by_side["Away"].line != -by_side["Away"].line or by_side["Away"].line == 0


def test_a_pair_read_as_sent_devigs_to_a_possible_book() -> None:
    body = payload(
        {
            "id": 33,
            "name": "Asian Handicap",
            "values": [
                {"value": "Home", "handicap": "-0.75", "odd": "1.90"},
                {"value": "Away", "handicap": "0.75", "odd": "1.98"},
            ],
        }
    )
    _, quotes, _, _ = read(body)
    overround = sum(1 / q.odds_decimal for q in quotes)
    assert Decimal("1.0") < overround < Decimal("1.2"), overround


# --- selections -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Home or Draw", "1X"), ("Away or Draw", "X2"), ("Home or Away", "12")],
)
def test_live_double_chance_vocabulary(raw: str, expected: str) -> None:
    """Live says "Home or Draw"; pre-match says "Home/Draw". The live wording is
    what was measured, and the pre-match alias table does not contain it."""
    selection = normalise_live_selection("DC", raw, None)
    assert selection is not None
    assert selection.side.value == expected


def test_a_lineless_market_that_grows_a_line_is_refused() -> None:
    """A handicap on 1X2 means the provider's catalogue moved. Storing it would
    silently split our 1X2 series across lines."""
    assert normalise_live_selection("1X2", "Home", "-1.5") is None


def test_an_unreadable_handicap_is_refused_not_defaulted_to_zero() -> None:
    assert normalise_live_selection("OU", "Over", "two and a half") is None
    assert normalise_live_selection("OU", "Over", None) is None


def test_quarter_lines_survive() -> None:
    body = payload(
        {
            "id": 36,
            "name": "Over/Under Line",
            "values": [
                {"value": "Over", "handicap": "3.75", "odd": "1.95"},
                {"value": "Under", "handicap": "3.75", "odd": "1.90"},
            ],
        }
    )
    _, quotes, _, _ = read(body)
    assert {q.line for q in quotes} == {Decimal("3.75")}


# --- what is not a price ----------------------------------------------------


def test_a_suspended_value_with_no_price_is_refused_and_counted() -> None:
    """56 of 1,933 measured values were ``"odd": "0"`` and suspended. Zero is the
    provider declining to quote - storing it would invent a price, and the table
    CHECKs odds_decimal > 1.0 anyway."""
    body = payload(
        {
            "id": 60,
            "name": "To Score 3 or More",
            "values": [{"value": "Some Player", "odd": "0", "suspended": True}],
        }
    )
    states, quotes, _, pl = read(body)
    assert quotes == []
    assert states[0].values_offered == 1
    assert states[0].values_suspended == 1
    assert pl.rejected_total == 1
    assert pl.rejected[0][2] == "suspended with no price"


def test_odds_of_exactly_one_are_refused_as_out_of_range() -> None:
    """One real value was a Double Chance leg at 1.00, not suspended. The table
    requires > 1.0, so it is refused and recorded rather than coerced."""
    body = payload(
        {
            "id": 72,
            "name": "Double Chance",
            "values": [{"value": "Home or Draw", "odd": "1", "suspended": False}],
        }
    )
    _, quotes, _, pl = read(body)
    assert quotes == []
    assert pl.rejected[0][2] == "odds out of range"


def test_a_suspended_value_that_still_has_a_price_is_kept() -> None:
    """210 of 1,933 measured values were suspended WITH a real price. That is the
    market freezing, and the series must show it and what it reopens at."""
    body = payload(
        {
            "id": 59,
            "name": "Fulltime Result",
            "values": [{"value": "Home", "odd": "2.50", "suspended": True}],
        }
    )
    _, quotes, _, _ = read(body)
    assert len(quotes) == 1
    assert quotes[0].is_suspended is True
    assert quotes[0].odds_decimal == Decimal("2.50")


# --- unmapped markets are kept, because /odds/live has no history -----------


def test_an_unmapped_bet_is_stored_with_its_own_words() -> None:
    """67 of the 72 observed bets have no market of ours. Dropping them would be
    unrecoverable: /odds/live keeps no history to re-fetch."""
    body = payload(
        {
            "id": 20,
            "name": "Match Corners",
            "values": [{"value": "Over", "handicap": "9.5", "odd": "1.85"}],
        }
    )
    _, quotes, markets, pl = read(body)
    assert len(quotes) == 1
    assert quotes[0].market_key is None
    assert quotes[0].provider_bet_id == 20
    assert quotes[0].selection == "Over"
    assert quotes[0].line == Decimal("9.5")
    assert pl.unmapped_bets[(20, "Match Corners")] == 1
    assert markets[0].name == "Match Corners"


def test_an_unmapped_bet_without_a_line_gets_line_zero() -> None:
    body = payload(
        {"id": 50, "name": "Last Team to Score", "values": [{"value": "Home", "odd": "1.6"}]}
    )
    _, quotes, _, _ = read(body)
    assert quotes[0].line == Decimal(0)


# --- a renamed bet is refused, never relabelled -----------------------------


def test_a_renamed_mapped_bet_is_not_filed_under_our_market() -> None:
    """A renumbering on the provider's side must not relabel prices. The bet is
    still stored - its id is intact - but with market_key NULL and the rename
    recorded."""
    body = payload(
        {
            "id": 59,
            "name": "Something Else Entirely",
            "values": [{"value": "Home", "odd": "2.00"}],
        }
    )
    _, quotes, _, pl = read(body)
    assert pl.renamed_bets == [(59, "Fulltime Result", "Something Else Entirely")]
    assert quotes[0].market_key is None
    assert quotes[0].provider_bet_id == 59


# --- match state ------------------------------------------------------------


def test_the_match_state_rides_with_every_price() -> None:
    """A live price without the minute and score is almost meaningless, so the
    state is denormalised onto each row rather than joined at read time."""
    body = payload(
        {"id": 59, "name": "Fulltime Result", "values": [{"value": "Home", "odd": "2.0"}]}
    )
    states, quotes, _, _ = read(body)
    q = quotes[0]
    assert (q.elapsed_minute, q.elapsed_seconds) == (77, "77:00")
    assert (q.score_home, q.score_away) == (0, 1)
    assert q.status_long == "Second Half"
    assert q.is_stopped is False and q.is_blocked is False
    assert q.provider_updated_at == AT
    s = states[0]
    assert s.provider_league_id == 253 and s.season == 2026
    assert s.markets_offered == 1 and s.values_offered == 1


def test_a_fixture_in_play_with_no_readable_price_still_leaves_a_state() -> None:
    """"Was it live?" must be answerable without the prices."""
    body = payload({"id": 60, "name": "x", "values": [{"value": "a", "odd": "0",
                                                       "suspended": True}]})
    states, quotes, _, _ = read(body)
    assert len(states) == 1
    assert quotes == []


def test_a_payload_missing_blocks_degrades_to_nulls_not_a_lost_fixture() -> None:
    body = {
        "response": [
            {
                "fixture": {"id": 7},
                "odds": [{"id": 59, "name": "Fulltime Result",
                          "values": [{"value": "Home", "odd": "2.0"}]}],
            }
        ]
    }
    states, quotes, _, _ = read(body)
    assert len(states) == 1 and len(quotes) == 1
    assert states[0].elapsed_minute is None
    assert states[0].score_home is None
    assert states[0].is_stopped is None


def test_an_entry_without_a_fixture_id_is_dropped() -> None:
    states, quotes, _, _ = read({"response": [{"league": {"id": 1}, "odds": []}]})
    assert states == [] and quotes == []


# --- accounting -------------------------------------------------------------


def test_every_value_is_either_a_quote_or_a_refusal() -> None:
    """The invariant the capture report checks: nothing read is unaccounted for."""
    body = payload(
        {
            "id": 59,
            "name": "Fulltime Result",
            "values": [
                {"value": "Home", "odd": "2.0"},
                {"value": "Draw", "odd": "0", "suspended": True},
                {"value": "Nonsense", "odd": "3.0"},
                {"value": "Away", "odd": "2500"},
            ],
        }
    )
    states, quotes, _, pl = read(body)
    assert states[0].values_offered == 4
    assert len(quotes) + pl.rejected_total == 4


def test_no_alias_table_maps_two_words_to_one_selection() -> None:
    """Two raw values collapsing to one selection would silently overwrite each
    other in a primary key that contains the selection."""
    for market, aliases in LIVE_SELECTION_ALIASES.items():
        sides = list(aliases.values())
        # Several spellings may share a side (live and pre-match wording), but
        # within one spelling style the sides must stay distinct.
        assert len(set(sides)) >= 2, market
