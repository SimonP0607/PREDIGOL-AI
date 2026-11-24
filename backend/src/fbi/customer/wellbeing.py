"""A reader's «solo fútbol» mode and voluntary pause (Plan Maestro PM, PM-14-07, OP-46): ``customer.wellbeing`` (migration 0176).

Two choices of the reader's own, both ending the same way - no price, no pick, no parlay anywhere - and both only theirs:

* ``football_only`` - the mode, on until they turn it off;
* a pause - the same until a date they chose (1, 7 or 30 days). A pause is a cooling-off: ``cut_short`` is False, so once set it can
  be extended but never shortened or lifted before its date (``PAUSE_CAN_BE_LIFTED``; the owner decides whether this stays).

Nothing is inferred and nothing is kept but the flag and the date: no counter, no reason, no reading of how often prices were looked at.
Behind ``FBI_WELLBEING`` (off by default): off, nothing here is read and nothing is hidden.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.customer.db import CustomerError, write_connection

PAUSE_DAYS: Final = (1, 7, 30)
PAUSE_CAN_BE_LIFTED: Final = False
"""False: a pause that was set runs until its date (the point of a cooling-off). The owner's decision; flipping it needs no migration."""


@dataclass(frozen=True)
class Wellbeing:
    football_only: bool = False
    paused_until: datetime | None = None

    def active(self, at: datetime) -> bool:
        """Whether this reader sees no price at ``at``: the mode is on, or a pause has not ended."""
        return self.football_only or (self.paused_until is not None and self.paused_until > at)

    def paused(self, at: datetime) -> bool:
        return self.paused_until is not None and self.paused_until > at


def read(conn: psycopg.Connection[Any], user_id: int) -> Wellbeing:
    row = conn.execute("SELECT football_only, paused_until FROM customer.wellbeing WHERE user_id = %s", (user_id,)).fetchone()
    return Wellbeing() if row is None else Wellbeing(football_only=bool(row[0]), paused_until=row[1])


def write(user_id: int, *, football_only: bool | None, pause_days: int | None, at: datetime) -> Wellbeing:
    """Set the choices named (None leaves one as it is) and return what stands. A pause that has not ended is never shortened and,
    unless ``PAUSE_CAN_BE_LIFTED``, the mode cannot be turned off while it runs."""
    if pause_days is not None and pause_days != 0 and pause_days not in PAUSE_DAYS:
        raise CustomerError(422, "invalid_pause", f"a pause is {', '.join(str(d) for d in PAUSE_DAYS)} days (0 lifts it)")
    with write_connection() as conn:
        now_row = conn.execute("SELECT football_only, paused_until FROM customer.wellbeing WHERE user_id = %s FOR UPDATE",
                               (user_id,)).fetchone()
        current = Wellbeing() if now_row is None else Wellbeing(football_only=bool(now_row[0]), paused_until=now_row[1])
        mode = current.football_only if football_only is None else football_only
        until = current.paused_until
        if pause_days is not None:
            asked = None if pause_days == 0 else at + timedelta(days=pause_days)
            if current.paused(at) and not PAUSE_CAN_BE_LIFTED and (asked is None or asked < current.paused_until):  # type: ignore[operator]
                raise CustomerError(409, "pause_running", "a pause that is running cannot be shortened or lifted")
            until = asked
        conn.execute(
            "INSERT INTO customer.wellbeing (user_id, football_only, paused_until, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET football_only = EXCLUDED.football_only, "
            "paused_until = EXCLUDED.paused_until, updated_at = EXCLUDED.updated_at",
            (user_id, mode, until, at, at))
    return Wellbeing(football_only=mode, paused_until=until)


def forget(conn: psycopg.Connection[Any], user_id: int) -> None:
    """The account anonymised (A7): the choice goes."""
    conn.execute("DELETE FROM customer.wellbeing WHERE user_id = %s", (user_id,))


ENV: Final = "FBI_WELLBEING"


def enabled() -> bool:
    """``FBI_WELLBEING``, born off (the same line ``fbi.api.switches.wellbeing_on`` reads): the notices read it without the API."""
    return os.environ.get(ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def hidden_prices(conn: psycopg.Connection[Any], at: datetime) -> frozenset[int]:
    """The readers who see no price, pick or parlay at ``at`` - empty while the line is off, so a notice that asks changes nothing.
    A notice that mentions a pick or a parlay (a result, a summary of the week) is not made for them."""
    if not enabled():
        return frozenset()
    rows = conn.execute("SELECT user_id FROM customer.wellbeing WHERE football_only OR paused_until > %s", (at,)).fetchall()
    return frozenset(int(r[0]) for r in rows)


__all__ = ["ENV", "PAUSE_CAN_BE_LIFTED", "PAUSE_DAYS", "Wellbeing", "enabled", "forget", "hidden_prices", "read", "write"]
