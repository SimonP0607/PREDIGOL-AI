"""What a reader chose about seeing prices, as the API says it (plan PM, PM-14-07)."""

from __future__ import annotations

from fbi.api.contracts.wellbeing import WellbeingState
from fbi.core.clock import now
from fbi.customer import wellbeing


def state_of(w: wellbeing.Wellbeing) -> WellbeingState:
    """The choice and whether it is in force now (a pause that ended is not shown)."""
    at = now()
    return WellbeingState(available=True, active=w.active(at), football_only=w.football_only,
                          paused_until=w.paused_until if w.paused(at) else None,
                          pause_can_be_lifted=wellbeing.PAUSE_CAN_BE_LIFTED)
