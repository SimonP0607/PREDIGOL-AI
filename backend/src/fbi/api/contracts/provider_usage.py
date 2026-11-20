"""What the provider's requests went to, for the owner's console (plan PM, PM-04-05; BE-076): today, the last days, the lanes, the
endpoints and the competitions, the margin and the guards. Read-only; nothing here asks the provider anything."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from fbi.api.contracts.common import Contract


class UsageDay(Contract):
    day: date
    spent: int = Field(description="Requests sent that UTC day (raw.provider_quota, the day's own ledger).")
    budget: int
    exhausted: bool = Field(description="The day reached our budget: not a normal day (29 Oct 2026, OPS-009).")


class UsageWindow(Contract):
    """The window's figures, as annex F of the plan measures them (raw.provider_quota)."""

    since: date
    until: date = Field(description="The last day of the window, included.")
    days: int = Field(description="Days with a row in the window.")
    mean: float
    median: float
    max: int
    max_day: date | None
    max_normal: int = Field(description="The largest day that did not reach the budget.")
    max_normal_day: date | None
    exhausted_days: int


class UsageToday(Contract):
    day: date
    spent: int = Field(description="Requests sent today so far (raw.provider_quota).")
    counted: int = Field(description="The same requests counted by endpoint and lane (raw.provider_endpoint_usage, PM-01-02).")
    budget: int = Field(description="Our daily budget (FBI_APIFOOTBALL_DAILY_BUDGET, never above the plan).")
    provider_limit: int = Field(description="The plan's daily limit.")
    elapsed: float = Field(description="Share of the UTC day gone, 0-1.")
    projected: int = Field(description="Today's requests at today's pace until 24:00 UTC.")
    margin: int = Field(description="Budget minus the projection.")
    margin_pct: float = Field(description="That margin as a share of the budget, in %.")
    last_request_at: datetime | None = Field(description="When the day's ledger last counted a request.")


class LaneUsage(Contract):
    lane: str
    label: str
    priority: int
    ceiling: int
    vital: bool
    today: int
    max_day: int = Field(description="The largest day of the window by this lane (from 20 Nov 2026, when the counter started).")
    share: float = Field(description="Today as a share of the ceiling, in %.")


class EndpointUsage(Contract):
    endpoint: str
    lane: str
    today: int
    window: int = Field(description="Requests in the window (from 20 Nov 2026).")


class CompetitionUsage(Contract):
    league_id: int
    competition_id: int | None
    name: str | None
    country: str | None
    responses: int = Field(description="New answers stored in the window that name this league (raw.ingestion_payloads): NOT "
                                        "requests - an answer equal to one already stored is not stored again.")


class UsageGuards(Contract):
    lanes_mode: str = Field(description="FBI_APIFOOTBALL_LANES: off | measure | enforce.")
    dynamic_limits: bool = Field(description="FBI_APIFOOTBALL_DYNAMIC_LIMITS.")
    emergency_reserve: int
    account_guard: bool = Field(description="FBI_APIFOOTBALL_ACCOUNT_GUARD: an account refusal inside an HTTP 200 pauses the worker.")
    account_pause_seconds: int
    quiet_minutes: float | None = Field(description="Minutes since the last request counted: a long silence while matches are "
                                                    "on may be a pause, which lives in the worker's memory and is not stored.")


class ProviderUsage(Contract):
    provider: str
    generated_at: datetime
    today: UsageToday
    window: UsageWindow
    days: list[UsageDay]
    lanes: list[LaneUsage]
    endpoints: list[EndpointUsage]
    competitions: list[CompetitionUsage]
    counted_since: date | None = Field(description="The first day the counter by endpoint and lane has (PM-01-02).")
    guards: UsageGuards
