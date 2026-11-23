"""A reader's secret calendar link (Plan Maestro PM, PM-14-06; BE-084): what the reader is told of it. The secret itself appears ONCE, in
the answer of ``POST /me/calendar-feed``; afterwards only whether there is a live link, since when and when a calendar last read it."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from fbi.api.contracts.common import Contract


class CalendarFeedStatus(Contract):
    active: bool
    created_at: datetime | None = None
    last_read_at: datetime | None = Field(default=None, description="When a calendar last read the link (noted at most once an hour).")
    teams: int = Field(ge=0, description="How many followed teams the calendar carries.")


class CalendarFeedMade(Contract):
    path: str = Field(description="The secret link's path on PrediGol's own origin (``/api/v1/calendar/feed/<secret>.ics``), shown "
                      "this once: whoever has it reads the calendar; revoke it to stop it. The page joins it to its origin (and offers "
                      "the ``webcal://`` form that opens the calendar app).")
    status: CalendarFeedStatus
