"""Markets as types, identity split, and the entity contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.core.errors import DomainError, InvalidSelectionError, TemporalIntegrityError
from fbi.domain import (
    NO_LINE,
    BookmakerId,
    CompetitionId,
    DecimalOdds,
    Decision,
    Fixture,
    FixtureId,
    FixtureStatus,
    MarketLine,
    MarketType,
    OddsSnapshot,
    OddsSource,
    PickCandidate,
    Probability,
    ProfitUnits,
    Provider,
    ProviderRef,
    SeasonId,
    Selection,
    Settlement,
    SettlementStatus,
    Side,
    StakeUnits,
    TeamId,
    settle,
)
from fbi.domain.identity import CandidateId, PredictionId, RunId

KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)


# ── selections ──────────────────────────────────────────────────────────────


def test_over_two_and_a_half_knows_what_it_is() -> None:
    s = Selection(MarketType.TOTAL_GOALS, Side.OVER, MarketLine(Decimal("2.5")))
    assert s.market is MarketType.TOTAL_GOALS
    assert s.side is Side.OVER
    assert s.line is not None and s.line.value == Decimal("2.50")
    assert str(s) == "OU Over 2.5"


def test_a_lined_market_without_a_line_is_rejected() -> None:
    with pytest.raises(InvalidSelectionError, match="needs a line"):
        Selection(MarketType.TOTAL_GOALS, Side.OVER)


def test_an_unlined_market_with_a_line_is_rejected() -> None:
    with pytest.raises(InvalidSelectionError, match="does not take a line"):
        Selection(MarketType.MATCH_WINNER, Side.HOME, MarketLine(Decimal("2.5")))


def test_a_side_from_the_wrong_market_is_rejected() -> None:
    with pytest.raises(InvalidSelectionError):
        Selection(MarketType.BOTH_TEAMS_TO_SCORE, Side.HOME)


@pytest.mark.parametrize("line", ["2.5", "2.25", "0.5", "3.75", "0"])
def test_quarter_lines_are_valid(line: str) -> None:
    MarketLine(Decimal(line))


@pytest.mark.parametrize("line", ["2.3", "-0.5", "nan"])
def test_impossible_lines_are_rejected(line: str) -> None:
    with pytest.raises(InvalidSelectionError):
        MarketLine(Decimal(line))


def test_selections_round_trip_through_the_three_schema_columns() -> None:
    for s in (
        Selection(MarketType.MATCH_WINNER, Side.DRAW),
        Selection(MarketType.TOTAL_GOALS, Side.UNDER, MarketLine(Decimal("3.5"))),
        Selection(MarketType.DOUBLE_CHANCE, Side.HOME_OR_DRAW),
        Selection(MarketType.BOTH_TEAMS_TO_SCORE, Side.YES),
    ):
        back = Selection.from_storage(s.market.value, s.side.value, s.line_for_storage)
        assert back == s


def test_the_no_line_sentinel_is_zero_not_null() -> None:
    assert Selection(MarketType.MATCH_WINNER, Side.HOME).line_for_storage == NO_LINE == Decimal(0)


def test_garbage_from_storage_is_rejected() -> None:
    with pytest.raises(InvalidSelectionError):
        Selection.from_storage("1X2", "Definitely Home", Decimal(0))
    with pytest.raises(InvalidSelectionError):
        Selection.from_storage("1X2", "Home", Decimal("2.5"))


def test_double_chance_is_the_non_exclusive_market() -> None:
    assert not MarketType.DOUBLE_CHANCE.is_exclusive
    assert all(m.is_exclusive for m in MarketType if m is not MarketType.DOUBLE_CHANCE)


def test_selections_are_hashable_and_usable_as_keys() -> None:
    a = Selection(MarketType.TOTAL_GOALS, Side.OVER, MarketLine(Decimal("2.5")))
    b = Selection(MarketType.TOTAL_GOALS, Side.OVER, MarketLine(Decimal("2.50")))
    assert {a: 1}[b] == 1


# ── identity ────────────────────────────────────────────────────────────────


def test_provider_ref_is_separate_from_internal_id() -> None:
    ref = ProviderRef(Provider.API_FOOTBALL, 1001)
    fixture = Fixture(
        id=FixtureId(7),
        provider_ref=ref,
        season_id=SeasonId(1),
        home_team_id=TeamId(1),
        away_team_id=TeamId(2),
        kickoff_at=KO,
        status=FixtureStatus.SCHEDULED,
        status_short="NS",
        round=None,
        venue_id=None,
        is_neutral=False,
    )
    assert fixture.id == 7
    assert fixture.provider_ref.external_id == 1001
    assert fixture.provider_ref.provider is Provider.API_FOOTBALL


def test_provider_ids_are_positive() -> None:
    with pytest.raises(DomainError):
        ProviderRef(Provider.API_FOOTBALL, 0)


def test_a_team_cannot_play_itself() -> None:
    with pytest.raises(DomainError):
        Fixture(FixtureId(1), ProviderRef(Provider.API_FOOTBALL, 1), SeasonId(1), TeamId(3), TeamId(3), KO,
                FixtureStatus.SCHEDULED, "NS", None, None, False)


def test_naive_datetimes_are_refused_everywhere() -> None:
    naive = datetime(2026, 9, 15, 19, 0)  # noqa: DTZ001 - the point of the test
    with pytest.raises(DomainError, match="timezone"):
        Fixture(FixtureId(1), ProviderRef(Provider.API_FOOTBALL, 1), SeasonId(1), TeamId(1), TeamId(2), naive,
                FixtureStatus.SCHEDULED, "NS", None, None, False)


# ── snapshots ───────────────────────────────────────────────────────────────


def snapshot(at: datetime, odds: str = "2.10") -> OddsSnapshot:
    return OddsSnapshot(
        fixture_id=FixtureId(1),
        bookmaker_id=BookmakerId(8),
        selection=Selection(MarketType.MATCH_WINNER, Side.HOME),
        odds=DecimalOdds.parse(odds),
        captured_at=at,
        minutes_to_kickoff=1440,
        source=OddsSource.PREMATCH,
        payload_hash="h1",
    )


def test_two_snapshots_at_different_instants_are_two_different_facts() -> None:
    a = snapshot(datetime(2026, 9, 14, 19, 0, tzinfo=UTC))
    b = snapshot(datetime(2026, 9, 15, 7, 0, tzinfo=UTC))
    assert a != b
    assert len({a, b}) == 2


def test_a_snapshot_without_its_payload_hash_is_untraceable_and_refused() -> None:
    with pytest.raises(DomainError, match="untraceable"):
        OddsSnapshot(FixtureId(1), BookmakerId(8), Selection(MarketType.MATCH_WINNER, Side.HOME),
                     DecimalOdds.parse("2.1"), KO, 10, OddsSource.PREMATCH, "")


# ── candidates and settlement ───────────────────────────────────────────────


def test_a_selected_candidate_without_a_price_cannot_exist() -> None:
    with pytest.raises(DomainError, match="without a price"):
        PickCandidate(CandidateId(1), RunId(1), FixtureId(1), PredictionId(1),
                      Selection(MarketType.MATCH_WINNER, Side.HOME), Decision.SELECTED, Probability(0.5))


def test_a_rejected_candidate_without_a_reason_cannot_exist() -> None:
    with pytest.raises(DomainError, match="must say why"):
        PickCandidate(CandidateId(1), RunId(1), FixtureId(1), PredictionId(1),
                      Selection(MarketType.MATCH_WINNER, Side.HOME), Decision.REJECTED, Probability(0.5))


def test_a_pending_settlement_has_no_profit_and_a_settled_one_must() -> None:
    from fbi.domain.identity import PickId

    Settlement(PickId(1), SettlementStatus.PENDING, None, None, None)
    with pytest.raises(DomainError):
        Settlement(PickId(1), SettlementStatus.WIN, None, None, None)
    with pytest.raises(DomainError):
        Settlement(PickId(1), SettlementStatus.PENDING, ProfitUnits(Decimal(1)), KO, "x")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (SettlementStatus.WIN, "1.1000"),
        (SettlementStatus.HALF_WIN, "0.5500"),
        (SettlementStatus.LOSS, "-1.0000"),
        (SettlementStatus.HALF_LOSS, "-0.5000"),
        (SettlementStatus.PUSH, "0.0000"),
        (SettlementStatus.VOID, "0.0000"),
    ],
)
def test_all_seven_states_settle_to_the_right_profit(status: SettlementStatus, expected: str) -> None:
    profit = settle(status, StakeUnits(Decimal(1)), DecimalOdds.parse("2.10"))
    assert profit.value == Decimal(expected)


def test_a_pending_pick_has_no_profit_to_settle() -> None:
    with pytest.raises(DomainError):
        settle(SettlementStatus.PENDING, StakeUnits(Decimal(1)), DecimalOdds.parse("2.10"))


def test_a_pick_cannot_use_information_newer_than_its_price() -> None:
    from fbi.domain import (
        DevigMethod,
        Edge,
        ExpectedValue,
        FairProbability,
        PriceEdge,
        PublishedPick,
    )
    from fbi.domain.identity import CalibratorId, ModelVersionId, PickId

    fair = FairProbability(Probability(0.465), DevigMethod.SHIN, 1.05)
    with pytest.raises(TemporalIntegrityError):
        PublishedPick(
            id=PickId(1), candidate_id=CandidateId(1), fixture_id=FixtureId(1),
            selection=Selection(MarketType.MATCH_WINNER, Side.HOME),
            model_version_id=ModelVersionId(1), calibrator_id=CalibratorId(1),
            feature_set_hash="fh", data_cutoff=datetime(2026, 9, 15, 19, 30, tzinfo=UTC),
            decision_rule_version="r1", code_version="abc", bookmaker_id=BookmakerId(1),
            market_odds=DecimalOdds.parse("2.10"), odds_captured_at=datetime(2026, 9, 15, 18, 5, tzinfo=UTC),
            p_model=Probability(0.52), p_calibrated=Probability(0.49), p_lower=Probability(0.44),
            p_upper=Probability(0.54), market_fair=fair, edge=Edge(Decimal("0.025")),
            price_edge=PriceEdge(Decimal("0.014")), ev=ExpectedValue(Decimal("0.029")),
            ev_adjusted=ExpectedValue(Decimal("0.024")), kelly_fraction=0.012, stake=StakeUnits(Decimal("0.5")),
        )


def test_competition_id_is_a_distinct_type_from_team_id() -> None:
    """NewType: mypy refuses CompetitionId where TeamId is expected. At runtime
    they are ints, which is the point - no cost, all the safety."""
    assert CompetitionId(1) == 1
    assert isinstance(TeamId(1), int)
