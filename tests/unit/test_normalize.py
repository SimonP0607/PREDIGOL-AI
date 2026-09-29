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
    INPLAY_BETS,
    PREMATCH_BETS,
    OddsParseLog,
    iter_fixtures,
    iter_odds,
    minutes_to_kickoff,
)

KICKOFF = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 15, 18, 48, tzinfo=UTC)


PREMATCH_BET_NAMES = {bet.bet_id: bet.name for bet in PREMATCH_BETS.values()}
INPLAY_BET_NAMES = {bet.bet_id: bet.name for bet in INPLAY_BETS.values()}


def payload(values: list[dict], bet_id: int = 1, name: str | None = None,
            source: str = "prematch") -> dict:
    """A payload shaped like the provider's, WITH the bet's real name.

    The name matters: the boundary checks it against the catalogue, so a fixture
    carrying a placeholder would be refused exactly as a provider rename is.
    """
    known = PREMATCH_BET_NAMES if source == "prematch" else INPLAY_BET_NAMES
    return {
        "response": [
            {
                "fixture": {"id": 1001},
                "bookmakers": [
                    {"id": 8, "name": "Bet365",
                     "bets": [{"id": bet_id,
                               "name": name if name is not None else known.get(bet_id, "Some Other Bet"),
                               "values": values}]}
                ],
            }
        ]
    }


def quotes(values: list[dict], bet_id: int = 1, name: str | None = None,
           source: str = "prematch", **kwargs: object) -> list:
    return list(
        iter_odds(
            payload(values, bet_id, name, source),
            kickoff_at=KICKOFF,
            captured_at=CAPTURED,
            payload_hash="h1",
            source=source,  # type: ignore[arg-type]
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


def _result_body(status: str, goals: tuple[int, int], extratime: tuple[int | None, int | None],
                 penalty: tuple[int | None, int | None] = (None, None)) -> dict:
    return {"response": [{
        "fixture": {"id": 77, "status": {"short": status}},
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {"halftime": {"home": 0, "away": 0}, "extratime": {"home": extratime[0], "away": extratime[1]},
                  "penalty": {"home": penalty[0], "away": penalty[1]}},
    }]}


def test_an_extra_time_result_keeps_its_breakdown() -> None:
    from fbi.providers.api_football.normalize import iter_fixture_results

    (r,) = list(iter_fixture_results(_result_body("AET", (3, 1), (1, 0))))
    assert (r.goals_home, r.goals_away, r.et_goals_home, r.et_goals_away) == (3, 1, 1, 0)


def test_an_extra_time_result_without_its_breakdown_is_not_stored() -> None:
    """`goals` includes extra time. Without the extra-time goals the 90-minute
    score markets settle on is unknown: better awaited than wrong."""
    from fbi.providers.api_football.normalize import iter_fixture_results

    assert list(iter_fixture_results(_result_body("AET", (2, 1), (None, None)))) == []
    assert list(iter_fixture_results(_result_body("PEN", (1, 1), (None, None), (4, 3)))) == []
    assert list(iter_fixture_results(_result_body("AET", (1, 0), (2, 0)))) == [], "more ET goals than final goals"
    (ft,) = list(iter_fixture_results(_result_body("FT", (2, 2), (None, None))))
    assert ft.et_goals_home is None, "no extra time in a regular match is not missing data"


# ── asian handicap: the sign the provider does not send ─────────────────────
#
# Shape and values taken verbatim from our own raw store (BetVictor and
# Marathonbet, /odds, fixture of 2026-09-28). The provider repeats the HOME
# handicap on both rows of a pair; what makes that the right reading is that
# every pair below devigs to 1.090, while reading the away row as its own signed
# handicap devigs the same pairs to 0.47, which no bookmaker could offer.

BETVICTOR_ASIAN_HANDICAP = [
    {"value": "Home -0.75", "odd": "2.53"}, {"value": "Away -0.75", "odd": "1.44"},
    {"value": "Home -0.5", "odd": "2.13"}, {"value": "Away -0.5", "odd": "1.61"},
    {"value": "Home -0.25", "odd": "1.86"}, {"value": "Away -0.25", "odd": "1.81"},
    {"value": "Home +0", "odd": "1.59"}, {"value": "Away +0", "odd": "2.17"},
    {"value": "Home +0.25", "odd": "1.44"}, {"value": "Away +0.25", "odd": "2.53"},
]


def test_the_away_row_of_a_handicap_pair_is_stored_with_the_opposite_sign() -> None:
    result = quotes(BETVICTOR_ASIAN_HANDICAP, bet_id=4)
    assert [(q.selection, str(q.line.normalize())) for q in result] == [
        ("Home", "-0.75"), ("Away", "0.75"),
        ("Home", "-0.5"), ("Away", "0.5"),
        ("Home", "-0.25"), ("Away", "0.25"),
        ("Home", "0"), ("Away", "0"),
        ("Home", "0.25"), ("Away", "-0.25"),
    ], "the stored line is the handicap that applies to the stored side"
    assert all(q.market_key == "AH" for q in result)


def test_the_reading_of_the_payload_is_the_only_one_that_devigs() -> None:
    """The measurement that settles how bet 4 must be read.

    Pair each 'Home X' with 'Away X' and every line of the bookmaker devigs to
    the same ~1.090 book. Pair 'Home X' with 'Away -X' instead - i.e. treat the
    provider number as a per-side signed handicap - and the same prices devig to
    around 0.47, a book that pays out more than it takes. Only the first reading
    describes a real price list, so the boundary negates the away row.
    """
    result = quotes(BETVICTOR_ASIAN_HANDICAP, bet_id=4)
    priced = {(q.selection, q.line): q.odds_decimal for q in result}

    as_read = [
        (priced[("Home", line)], priced[("Away", -line)])
        for line in sorted({ln for side, ln in priced if side == "Home"})
        if ("Away", -line) in priced
    ]
    alternative = [
        (priced[("Home", line)], priced[("Away", line)])
        for line in sorted({ln for side, ln in priced if side == "Home"})
        if ("Away", line) in priced
    ]

    def books(pairs: list[tuple[Decimal, Decimal]]) -> list[Decimal]:
        return [round(1 / a + 1 / b, 3) for a, b in pairs]

    read = books(as_read)
    assert len(read) == 5
    assert all(Decimal("1.08") <= b <= Decimal("1.10") for b in read), read
    assert max(read) - min(read) <= Decimal("0.001"), "one consistent margin across every line"

    wrong = books(alternative)
    assert min(wrong) < 1, wrong
    assert max(wrong) - min(wrong) > Decimal("0.3"), "and no consistent margin at all"


MARATHONBET_WIDE_HANDICAPS = [
    {"value": "Home -1.25", "odd": "3.50"}, {"value": "Away -1.25", "odd": "1.22"},
    {"value": "Home +1.25", "odd": "1.08"}, {"value": "Away +1.25", "odd": "5.50"},
]


def test_a_wide_handicap_makes_the_wrong_reading_pay_more_than_it_takes() -> None:
    """Same demonstration where the lines are far apart, so it is unmistakable.

    Read correctly, both pairs are a ~1.106 book. Read as a per-side signed
    handicap, one pair becomes a 0.468 book - a bookmaker handing out money.
    """
    priced = {(q.selection, q.line): q.odds_decimal for q in quotes(MARATHONBET_WIDE_HANDICAPS, bet_id=4)}
    correct = [round(1 / priced[("Home", ln)] + 1 / priced[("Away", -ln)], 3)
               for ln in (Decimal("-1.25"), Decimal("1.25"))]
    wrong = [round(1 / priced[("Home", ln)] + 1 / priced[("Away", ln)], 3)
             for ln in (Decimal("-1.25"), Decimal("1.25"))]
    assert all(Decimal("1.10") <= b <= Decimal("1.11") for b in correct), correct
    assert wrong == [Decimal("0.468"), Decimal("1.746")], wrong


def test_a_whole_and_a_quarter_handicap_both_survive_the_boundary() -> None:
    result = quotes(
        [{"value": "Home -1", "odd": "3.14"}, {"value": "Away -1.25", "odd": "1.22"}], bet_id=4
    )
    assert [(q.selection, str(q.line.normalize())) for q in result] == [("Home", "-1"), ("Away", "1.25")]


def test_an_asian_handicap_selection_without_a_number_is_refused_not_guessed() -> None:
    log = OddsParseLog()
    result = quotes([{"value": "Home", "odd": "1.90"}], bet_id=4, parse_log=log)
    assert result == []
    assert log.rejected == [("AH", "Home", "not a selection of this market")]


def test_a_line_that_is_not_a_quarter_multiple_is_refused() -> None:
    log = OddsParseLog()
    assert quotes([{"value": "Home -0.3", "odd": "1.90"}], bet_id=4, parse_log=log) == []
    assert quotes([{"value": "Over 2.4", "odd": "1.90"}], bet_id=5, parse_log=log) == []
    assert [r[1] for r in log.rejected] == ["Home -0.3", "Over 2.4"]


def test_an_over_under_line_is_never_negative() -> None:
    log = OddsParseLog()
    assert quotes([{"value": "Over -2.5", "odd": "1.90"}], bet_id=5, parse_log=log) == []
    assert log.rejected_total == 1


def test_a_bet_we_do_not_model_is_recorded_rather_than_ignored() -> None:
    """Corners Asian Handicap is bet 56. It is NOT our AH market, and the fact
    that the provider offered it is information: market.provider_markets is
    where it belongs, so the parse log names it."""
    log = OddsParseLog()
    body = payload([{"value": "Home -1.5", "odd": "1.90"}], bet_id=56, name="Corners Asian Handicap")
    assert list(
        iter_odds(body, kickoff_at=KICKOFF, captured_at=CAPTURED, payload_hash="h1",
                  source="prematch", parse_log=log)
    ) == []
    assert log.unmapped_bets == {(56, "Corners Asian Handicap"): 1}


def test_the_four_markets_that_already_worked_still_work() -> None:
    assert [q.selection for q in quotes(
        [{"value": "Home", "odd": "2.10"}, {"value": "Draw", "odd": "3.40"}, {"value": "Away", "odd": "3.60"}],
        bet_id=1)] == ["Home", "Draw", "Away"]
    assert [(q.selection, str(q.line.normalize())) for q in quotes(
        [{"value": "Over 2.5", "odd": "1.90"}, {"value": "Under 2.5", "odd": "1.95"}],
        bet_id=5)] == [("Over", "2.5"), ("Under", "2.5")]
    assert [q.selection for q in quotes(
        [{"value": "Yes", "odd": "1.80"}, {"value": "No", "odd": "2.00"}], bet_id=8)] == ["Yes", "No"]
    assert [q.selection for q in quotes(
        [{"value": "Home/Draw", "odd": "1.30"}, {"value": "Draw/Away", "odd": "2.10"}],
        bet_id=12)] == ["1X", "X2"]
    assert all(q.line == Decimal(0) for q in quotes([{"value": "Home", "odd": "2.10"}], bet_id=1))


# ── pre-match and in-play are different id namespaces ───────────────────────


def test_an_in_play_payload_is_not_read_with_the_prematch_id_map() -> None:
    """The bug that had not fired yet, because /odds/live had never run.

    In-play bet 5 is "Extra Time Double Result". Under one shared id map it would
    have been stored as our Over/Under series - real prices, wrong market, and no
    way to tell afterwards.
    """
    log = OddsParseLog()
    result = quotes([{"value": "Over 2.5", "odd": "1.90"}], bet_id=5, source="live",
                    name="Extra Time Double Result", parse_log=log)
    assert result == [], "an extra-time market is not our Over/Under"
    assert log.unmapped_bets == {(5, "Extra Time Double Result"): 1}


def test_the_in_play_ids_of_the_markets_we_model_are_their_own() -> None:
    """Full-match in-play equivalents, from /odds/live/bets."""
    assert {k: b.bet_id for k, b in INPLAY_BETS.items()} == {
        "1X2": 59, "AH": 33, "OU": 36, "BTTS": 69, "DC": 72
    }
    assert {k: b.bet_id for k, b in PREMATCH_BETS.items()} == {
        "1X2": 1, "AH": 4, "OU": 5, "BTTS": 8, "DC": 12
    }
    assert set(INPLAY_BETS) == set(PREMATCH_BETS), "the same markets, different numbers"


def test_a_live_handicap_is_read_with_the_in_play_id() -> None:
    result = quotes([{"value": "Home -0.25", "odd": "1.92"}, {"value": "Away -0.25", "odd": "1.88"}],
                    bet_id=33, source="live")
    assert [(q.market_key, q.selection, str(q.line.normalize()), q.source) for q in result] == [
        ("AH", "Home", "-0.25", "live"), ("AH", "Away", "0.25", "live")
    ]


def test_a_bet_the_provider_has_renamed_is_refused_and_recorded() -> None:
    """A rename is the cheapest possible signal that the catalogue moved under
    us. Accepting the id anyway is how a renumbering becomes silent corruption.
    """
    log = OddsParseLog()
    assert quotes([{"value": "Over 2.5", "odd": "1.90"}], bet_id=5,
                  name="Goals Over/Under 1st Half", parse_log=log) == []
    assert log.renamed_bets == [(5, "Goals Over/Under", "Goals Over/Under 1st Half")]


def test_a_difference_of_case_or_spacing_is_not_a_rename() -> None:
    assert len(quotes([{"value": "Yes", "odd": "1.80"}], bet_id=8, name="both teams  score")) == 1


def test_a_payload_without_a_bet_name_is_still_read() -> None:
    """The name is a check, not a requirement: a payload that omits it must not
    cost us the price."""
    assert len(quotes([{"value": "Home", "odd": "2.10"}], bet_id=1, name="")) == 1
