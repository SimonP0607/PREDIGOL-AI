"""What a reader chose about seeing prices (plan PM, PM-14-07)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from fbi.api.contracts.common import Contract


class WellbeingState(BaseModel):
    """In ``/auth/me`` and as the answer of ``/me/wellbeing``: off (``available`` False) until ``FBI_WELLBEING``."""

    available: bool = Field(default=False, description="The owner opened the choice (FBI_WELLBEING): a reader can choose.")
    active: bool = Field(default=False, description="This reader sees no price, pick or parlay now (the mode, or a pause that runs).")
    football_only: bool = Field(default=False, description="The «solo fútbol» mode, until the reader turns it off.")
    paused_until: datetime | None = Field(default=None, description="A pause runs until then (null: none).")
    pause_can_be_lifted: bool = Field(default=False, description="Whether a pause that runs may be cut short (the owner's rule).")


class WellbeingIn(Contract):
    """What the reader chooses; a field left out stays as it is."""

    football_only: bool | None = None
    pause_days: Literal[0, 1, 7, 30] | None = Field(default=None, description="A pause of that many days from now; 0 lifts it, if the rule allows.")
