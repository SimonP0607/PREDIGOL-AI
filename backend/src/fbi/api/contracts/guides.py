"""The welcome tour and the guides of each screen (plan UX-032): what the page reads and sends. Only the memory of what each
reader has seen; what the guides say lives in the page."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract
from fbi.customer.guides import MAX_VERSION, GuideKey, GuideStatus


class GuideState(Contract):
    guide: GuideKey
    version: int = Field(description="The version of the content the reader saw.")
    status: GuideStatus = Field(description="pending: the screen was visited and the guide not yet shown. in_progress, "
                                            "completed or skipped. Within a version the status never goes down.")
    step: int = Field(description="The last step reached (0-based): to resume, and to know where it was skipped.")
    first_seen_at: datetime = Field(description="The first visit to the screen.")
    started_at: datetime | None
    completed_at: datetime | None
    skipped_at: datetime | None


class GuideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, le=MAX_VERSION)
    status: GuideStatus
    step: int = Field(default=0, ge=0, le=9)
