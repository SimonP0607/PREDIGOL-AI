"""Odds: which fixtures have prices, and everything captured for one of them."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from fbi.api.contracts.matches import MatchSummary
from fbi.api.contracts.odds import (
    ConsensusQuote,
    FixtureOdds,
    NearCloseQuote,
    OddsPoint,
    OddsSeries,
)
from fbi.api.envelope import DataStatus, Envelope, listing, ok, section
from fbi.api.repositories import Conn
from fbi.api.repositories import fixtures as fixtures_repo
from fbi.api.repositories import odds as repo
from fbi.api.services.matches import NO_MARKET_DATA, quote, summary
from fbi.core.clock import now

NO_SNAPSHOTS = (
    "No odds snapshot has been captured yet. The capturer records prices only inside "
    "real pre-match windows; none has coincided with a tracked fixture so far."
)


def list_fixtures_with_odds(conn: Conn, *, limit: int, offset: int) -> Envelope[list[MatchSummary]]:
    ids = repo.fixtures_with_odds(conn, limit=limit, offset=offset)
    rows, _ = fixtures_repo.list_fixtures(
        conn, fixtures_repo.FixtureFilter(fixture_ids=ids or [-1]), limit=limit, offset=0, order="desc")
    moment = now()
    items = [summary(r, moment) for r in rows]
    newest = max((i.odds.last_captured_at for i in items if i.odds.last_captured_at), default=None)
    return listing(items, empty_reason=NO_SNAPSHOTS, total=repo.count_fixtures_with_odds(conn),
                   limit=limit, offset=offset, data_as_of=newest)


def fixture_odds(conn: Conn, fixture_id: int, *, market_key: str | None) -> Envelope[FixtureOdds]:
    row = fixtures_repo.get_fixture(conn, fixture_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    board = [quote(q) for q in fixtures_repo.latest_quotes(conn, fixture_id)
             if market_key is None or q["market_key"] == market_key]

    grouped: dict[tuple[Any, ...], list[OddsPoint]] = defaultdict(list)
    names: dict[tuple[Any, ...], str] = {}
    for r in repo.series(conn, fixture_id, market_key):
        key = (r["bookmaker_id"], r["market_key"], r["selection"], r["line"])
        names[key] = r["bookmaker"]
        grouped[key].append(OddsPoint(captured_at=r["captured_at"], odds_decimal=Decimal(r["odds_decimal"]),
                                      minutes_to_ko=r["minutes_to_ko"], source=r["source"],
                                      payload_hash=r["payload_hash"]))
    series = [OddsSeries(bookmaker_id=k[0], bookmaker=names[k], market_key=k[1], selection=k[2], line=k[3],
                         points=pts) for k, pts in grouped.items()]
    near = [NearCloseQuote(**n) for n in repo.near_close(conn, fixture_id)]
    cons = [ConsensusQuote(**c) for c in repo.consensus(conn, fixture_id)]
    return ok(FixtureOdds(
        match=summary(row),
        board=section(board) if board else section(board, status=DataStatus.EMPTY, reason=NO_MARKET_DATA),
        series=section(series) if series else section(series, status=DataStatus.EMPTY, reason=NO_MARKET_DATA),
        near_close=section(near) if near else section(
            near, status=DataStatus.EMPTY,
            reason="No near-close capture for this fixture. Near-close is the snapshot closest to "
                   "kick-off our cadence allowed - it is not a closing line."),
        consensus=section(cons) if cons else section(
            cons, status=DataStatus.NOT_AVAILABLE,
            reason="No de-vigged market consensus has been computed for this fixture."),
    ))
