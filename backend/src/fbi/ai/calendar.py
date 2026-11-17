"""The AI layer's calendar: its day and its month are Bogotá's (America/Bogota, the product's day), never UTC.

A day of work starts at 00:05 Bogotá (``fbi.ai.day``); the budget's day and month are cut at Bogotá midnight
(``fbi.ai.usage``); the learning reads the finished Bogotá day. The functions live in ``fbi.core.calendar`` (a leaf, so the
cycle's readers outside the AI layer can use them without importing it); this module keeps the AI layer's name for them."""

from __future__ import annotations

from fbi.core.calendar import (
    DAY_TZ as DAY_TZ,
)
from fbi.core.calendar import (
    day_bounds as day_bounds,
)
from fbi.core.calendar import (
    day_start as day_start,
)
from fbi.core.calendar import (
    days_in_month as days_in_month,
)
from fbi.core.calendar import (
    days_left_in_month as days_left_in_month,
)
from fbi.core.calendar import (
    local_day as local_day,
)
from fbi.core.calendar import (
    month_start as month_start,
)
from fbi.core.calendar import (
    next_month as next_month,
)

__all__ = ["DAY_TZ", "day_bounds", "day_start", "days_in_month", "days_left_in_month", "local_day", "month_start", "next_month"]
