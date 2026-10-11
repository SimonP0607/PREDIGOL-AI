"""The response shape every product endpoint returns.

    {"status": "ok" | "empty" | "insufficient_data" | "not_available",
     "data": ..., "reason": "..." | null, "meta": {...}}

The four statuses are not decoration; the frontend renders each differently
and none of them may be faked with a zero:

  ok                 data is present and means what it says.
  empty              the question is valid and the answer is "nothing" -
                     no fixtures on that date, no snapshots for that match.
  insufficient_data  the thing exists but the sample is too small to report
                     honestly - a Brier score over 3 matches, an ROI over 0
                     settled picks.
  not_available      the capability has not produced anything yet - no model
                     has been trained, the pick engine has never run.

Whenever the status is not ``ok`` a human-readable ``reason`` is mandatory:
it is what the UI shows in place of the number.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fbi.core.clock import now

API_VERSION: Literal["v1"] = "v1"


class DataStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_AVAILABLE = "not_available"


class Meta(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime = Field(default_factory=now)
    api_version: Literal["v1"] = API_VERSION
    count: int | None = None
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    data_as_of: datetime | None = Field(
        default=None, description="Newest timestamp among the rows the answer was built from."
    )


class Section[T](BaseModel):
    """An honest sub-answer inside a composite response (Overview, Match Center).

    Same four statuses as the envelope, so a page can show one panel as
    "No captured market data yet." while the rest of the page is live.
    """

    model_config = ConfigDict(frozen=True)

    status: DataStatus
    data: T
    reason: str | None = None
    code: str | None = None
    """A stable name for the reason (e.g. ``not_started``, ``lineups_not_published``), so a page can say it in its
    reader's language and with the right weight - an expected absence is not an error (REVIEW, 11 Oct 2026)."""

    @model_validator(mode="after")
    def _reason_when_not_ok(self) -> Section[T]:
        if self.status is not DataStatus.OK and not self.reason:
            raise ValueError(f"status {self.status} needs a reason the UI can show")
        return self


class Envelope[T](BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DataStatus
    data: T
    reason: str | None = None
    meta: Meta = Field(default_factory=Meta)

    @model_validator(mode="after")
    def _reason_when_not_ok(self) -> Envelope[T]:
        if self.status is not DataStatus.OK and not self.reason:
            raise ValueError(f"status {self.status} needs a reason the UI can show")
        return self


def ok[T](data: T, **meta: object) -> Envelope[T]:
    return Envelope[T](status=DataStatus.OK, data=data, meta=Meta(**meta))  # type: ignore[arg-type]


def listing[T](items: list[T], *, empty_reason: str, **meta: object) -> Envelope[list[T]]:
    """A list answer: ``ok`` when there is something, ``empty`` with the reason otherwise."""
    meta.setdefault("count", len(items))
    if items:
        return Envelope[list[T]](status=DataStatus.OK, data=items, meta=Meta(**meta))  # type: ignore[arg-type]
    return Envelope[list[T]](
        status=DataStatus.EMPTY, data=items, reason=empty_reason, meta=Meta(**meta)  # type: ignore[arg-type]
    )


def unavailable[T](
    data: T, reason: str, *, status: DataStatus = DataStatus.NOT_AVAILABLE, **meta: object
) -> Envelope[T]:
    return Envelope[T](status=status, data=data, reason=reason, meta=Meta(**meta))  # type: ignore[arg-type]


def section[T](data: T, *, status: DataStatus = DataStatus.OK, reason: str | None = None,
               code: str | None = None) -> Section[T]:
    return Section[T](status=status, data=data, reason=reason, code=code)
