"""The price of a pick now, beside the price it was taken at (plan CUOTAS, phase 6).

A pick of the day carries the price frozen when it entered the set; a pick a reader saved carries the price they counted
(their own, else the one we showed). This module reads the newest consensus price of the same selection, so a screen can say
«tomada a 2,30 · ahora 2,15 (-6,5 %)» with the hour of the second one.

It is a MOVE of the price, never a verdict: no probability, no value, no edge, no state is read or written, and a pick's
status never depends on it. Only a match still to be played has a price now; a started or finished one is the record as it
was taken (the closing reference of «Mis picks» is another thing, ``clv-v1``). The price comes with its own hour and how fresh
it is (no bookmaker is named: the price is a reference, not an offer), by the same limits as the picks board (one hour fresh, ``GateConfig.max_price_age`` aging, older stale), so an old
price is never presented as the current one.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Literal

from fbi.api.contracts.records import PriceNow
from fbi.api.repositories import Conn, fetch_all
from fbi.core import match_state
from fbi.parlays.engine import GateConfig

FRESH: Final = timedelta(hours=1)
"""Fresh up to here; a test keeps it equal to the picks board's (``fbi.api.services.product.PRICE_FRESH``)."""
LOOKBACK: Final = timedelta(hours=36)
"""The same look-back as a saved pick or a parlay leg takes its price from (``fbi.userdata.records.SNAPSHOT_LOOKBACK``)."""

Key = tuple[int, str, str, Decimal]
"""fixture, market key, selection, line."""

PRICE_NOW_SQL = """
SELECT v.n, m.best_odds, m.as_of
  FROM unnest(%(fixtures)s::bigint[], %(markets)s::text[], %(selections)s::text[], %(lines)s::numeric[])
       WITH ORDINALITY AS v(fixture_id, market_key, selection, line, n)
  JOIN LATERAL (
        SELECT c.best_odds, c.as_of FROM market.market_consensus c
         WHERE c.fixture_id = v.fixture_id AND c.market_key = v.market_key AND c.selection = v.selection
           AND c.line = v.line AND c.devig_method = 'shin' AND c.as_of <= %(at)s AND c.as_of >= %(since)s
           AND c.best_odds IS NOT NULL
         ORDER BY c.as_of DESC LIMIT 1) m ON true
"""
"""The newest Shin consensus of each selection asked, in one statement."""


def freshness(as_of: datetime, at: datetime, cfg: GateConfig | None = None) -> Literal["fresh", "aging", "stale"]:
    age = at - as_of
    if age <= FRESH:
        return "fresh"
    return "aging" if age <= (cfg or GateConfig()).max_price_age else "stale"


def has_price_now(status_short: str | None, kickoff_at: datetime, at: datetime) -> bool:
    """Only a match still to be played has a price now."""
    return match_state.phase(status_short, kickoff_at, at) is match_state.Phase.SCHEDULED and kickoff_at > at


def change(taken: Decimal, now: Decimal) -> Decimal:
    """now / taken - 1, four decimals: -0.0652 is a price that fell 6.52 %. Positive: a better price than the one taken."""
    return (now / taken - 1).quantize(Decimal("0.0001"))


def read(conn: Conn, asked: Mapping[int, tuple[Key, Decimal | None]], *, at: datetime) -> dict[int, PriceNow]:
    """The price now of each asked selection: ``asked`` maps a caller's index to (selection, the price taken). Missing from the
    answer: no consensus price in the look-back. ``change`` is null while no price was taken."""
    if not asked:
        return {}
    order = list(asked)
    keys = [asked[i][0] for i in order]
    rows = fetch_all(conn, PRICE_NOW_SQL, {
        "fixtures": [k[0] for k in keys], "markets": [k[1] for k in keys], "selections": [k[2] for k in keys],
        "lines": [k[3] for k in keys], "at": at, "since": at - LOOKBACK})
    out: dict[int, PriceNow] = {}
    for r in rows:
        index = order[int(r["n"]) - 1]
        taken = asked[index][1]
        odds = Decimal(r["best_odds"])
        out[index] = PriceNow(odds=odds, as_of=r["as_of"], freshness=freshness(r["as_of"], at),
                              change=None if taken is None else change(Decimal(taken), odds))
    return out
