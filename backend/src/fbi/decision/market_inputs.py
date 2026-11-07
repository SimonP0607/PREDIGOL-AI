"""The market's signals (``fbi.market.signals``, market-signals-v1) as RISK inputs of decision-v2 (``engine.MarketRisk``).

The only door between the signals and the engine: the engine never imports the signals module, it takes the plain values built here.
A signal never reaches a probability, a price or a value - it can only add a CAUTION in the risk stage. Read-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from fbi.decision.engine import MarketRisk
from fbi.intel.decision import Key
from fbi.market import signals


def from_signals(s: signals.MarketSignals) -> MarketRisk:
    return MarketRisk(s.status, s.side, s.steam, s.movement_points, s.stale, s.version)


def read(conn: psycopg.Connection[Any], key: Key, *, at: datetime, p_model: float | None) -> MarketRisk | None:
    """The signals of one selection as of ``at`` relative to ``p_model`` (None for an unknown fixture)."""
    found = signals.read_signals(conn, key, at=at, p_model=p_model)
    return None if found is None else from_signals(found)
