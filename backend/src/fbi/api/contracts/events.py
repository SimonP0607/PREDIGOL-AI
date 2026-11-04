"""Product analytics (plan UX, A6): the browser's batch of events and the owner's view of them."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=41, description="An event of the closed catalog (fbi/customer/events_catalog.json).")
    props: dict[str, Any] = Field(default_factory=dict, description="Only the catalog's properties of this event.")


class EventsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[EventIn] = Field(max_length=20)


class EventsRecorded(Contract):
    recorded: int = Field(description="0 when nothing is recorded: the switch, the account (owner, robot), consent.")


class UsageRow(Contract):
    name: str
    group: str
    events_7d: int
    subjects_7d: int
    events_30d: int
    subjects_30d: int


class FunnelStep(Contract):
    step: Literal["activated", "onboarding_started", "onboarding_completed", "first_value"]
    subjects: int


class LifecycleRate(Contract):
    n: int
    of: int = Field(description="The cohort's size.")
    value: float | None = Field(description="None while the cohort is under 30 readers: never a share of a handful.")


class LifecycleMetrics(Contract):
    day: date | None = Field(description="The newest day of the lifecycle's calculation (B11); None before the first.")
    states: dict[str, int] = Field(description="Readers in each state on that day.")
    renewal_30d: LifecycleRate = Field(description="Memberships that ended in 30 days and have a later period.")
    activation_7d: LifecycleRate = Field(description="Accounts of 7-90 days that activated within 7 days.")
    retention_d7: LifecycleRate = Field(description="Accounts of 14-90 days active between their day 7 and 13.")
    retention_d30: LifecycleRate = Field(description="Accounts of 37-90 days active between their day 30 and 36.")


class ProductOverview(Contract):
    mode: Literal["off", "on", "consent"] = Field(description="FBI_PRODUCT_EVENTS: off records nothing.")
    purge: Literal["off", "dry", "on"] = Field(description="FBI_EVENTS_PURGE: dry counts, on deletes (the owner's OK).")
    min_subjects: int = Field(description="Global figures need at least this many readers active in 30 days.")
    status: Literal["ok", "insufficient_data", "empty"]
    active_30d: int
    active: dict[str, int] = Field(description="Readers active today (d1), in 7 days (d7) and in 30 days (d30).")
    usage: list[UsageRow]
    funnel: list[FunnelStep]
    devices: dict[str, int] = Field(description="Sessions started in 7 days by device class.")
    days_active_per_week: float | None
    errors_per_active: float | None
    dau_mau: float | None = Field(description="Only from 100 readers active in 30 days.")
    lifecycle: LifecycleMetrics | None = Field(default=None, description="The customers' lifecycle (B11).")
