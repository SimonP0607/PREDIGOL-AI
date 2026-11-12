"""How a reader wants PrediGol shown (plan maestro UX/UI 2026, decision 8; BE-039): the clock, the way a price is written,
fewer animations and the view Inicio opens on. Presentation only - a price is stored, computed and sent in decimal whatever
the reader chose. No row in ``customer.preferences``: the defaults, which leave everything as it was before the settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import psycopg

from fbi.customer.db import write_connection

TimeFormat = Literal["24h", "12h"]
OddsFormat = Literal["decimal", "american", "fractional"]
HomeDefault = Literal["mine", "all"]

FIELDS: Final = ("time_format", "odds_format", "reduce_motion", "home_default")


@dataclass(frozen=True)
class Display:
    time_format: TimeFormat = "24h"
    odds_format: OddsFormat = "decimal"
    reduce_motion: bool = False
    home_default: HomeDefault | None = None


def read(conn: psycopg.Connection[Any], user_id: int) -> Display:
    row = conn.execute("SELECT time_format, odds_format, reduce_motion, home_default FROM customer.preferences "
                       "WHERE user_id = %s", (user_id,)).fetchone()
    if row is None:
        return Display()
    return Display(time_format=row[0], odds_format=row[1], reduce_motion=bool(row[2]), home_default=row[3])


def write(user_id: int, values: dict[str, Any], *, at: datetime) -> None:
    """Set the settings named in ``values`` (a key of FIELDS each); the others stay. ``home_default`` None is a value: back
    to the automatic rule."""
    names = [name for name in FIELDS if name in values]
    if not names:
        return
    columns = ", ".join(names)
    marks = ", ".join(["%s"] * len(names))
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in names)
    with write_connection() as conn:
        conn.execute(
            f"INSERT INTO customer.preferences (user_id, {columns}, updated_at) VALUES (%s, {marks}, %s) "
            f"ON CONFLICT (user_id) DO UPDATE SET {updates}, updated_at = EXCLUDED.updated_at",
            (user_id, *[values[name] for name in names], at))
