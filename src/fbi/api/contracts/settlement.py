"""How fast each match's bets were settled after it ended (picks.settlement_latency)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from fbi.api.contracts.common import Contract


class SettlementRow(Contract):
    fixture_id: int
    home: str
    away: str
    competition: str
    kickoff_at: datetime
    status_short: str
    last_in_play_at: datetime | None = Field(description="The last state seen in play: the provider had not "
                                                         "finished the match yet.")
    observed_finished_at: datetime | None = Field(description="The first state seen ended (or the result row, for "
                                                              "a match not followed live).")
    result_stored_at: datetime | None
    settled_at: datetime
    delay_seconds: int | None = Field(description="settled_at - observed_finished_at.")
    path: str = Field(description="live_follow, results_repair or pipeline.")
    picks_settled: int
    items_settled: int = Field(description="Picks of the day, parlay legs and users' records settled with them.")


class WaitingSettlement(Contract):
    """A match that ended and still has bets open: none for long, unless a human must decide."""

    fixture_id: int
    home: str
    away: str
    kickoff_at: datetime
    status_short: str
    open_picks: int
    open_items: int
    ended_at: datetime | None
    review_reason: str | None = Field(description="Why a human must decide (postponed, abandoned...), if so.")


class SettlementLatency(Contract):
    days: int
    matches: int
    mean_seconds: float | None
    median_seconds: float | None
    p90_seconds: float | None
    max_seconds: int | None
    by_path: dict[str, int]
    rows: list[SettlementRow]
    waiting: list[WaitingSettlement]
