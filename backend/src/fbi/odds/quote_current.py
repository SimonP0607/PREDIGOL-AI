"""The prices IN FORCE for a match, read from the price clock (plan Partidos y Match Center, F4a; problem M4).

``market.odds_quotes`` holds one row per price per DISTINCT ``/odds`` body: RAW stores identical bodies once, so when the
prices of a match go A -> B -> A the newest row of a key is B's, although the provider's last answer was A again. "The newest
row" is therefore not "the price now". This module reads the price in force the only way the data allows:

1. ``market.odds_asks`` records every pre-match ask with the hash of the body that answered it (revision 0064). The newest ask
   before kick-off says WHICH body is in force, whether that body was new or one we had seen before.
2. ``market.odds_extractions`` (unique ``payload_hash``) says which ledger row read that body, and its ``id`` is the
   ``extraction_id`` of exactly the quotes that body produced. Those rows - and only those - are the prices in force: a price the
   provider stopped quoting is not carried forward from an older body. (This rests on every body keeping all its rows: a
   compaction of ``odds_quotes`` that dropped repeated prices, which the owner's notes keep as a later option, must change this
   reader at the same time.)

The choices, each the safer of two:

* An ask that came back EMPTY (``results = 0``) withdraws every price: nothing is in force after it, even if an older body had
  prices (``withdrawn``).
* A body the extractor has not read yet (its job runs behind the capture) is skipped, and the newest body it HAS read stands in,
  flagged ``newer_pending``: an older true answer, said to be older, rather than nothing or a guess.
* ``since`` is when the answer in force started to be the answer: the first ask of the unbroken run of asks answered by the same
  body. After A -> B -> A it is the ask that brought A back, never the first time A was seen (A was not in force while B was).
  It is per body, not per price: a price that did not move between two different bodies is said to be in force since the newer
  one - an age that can only be understated, never overstated.

Known limit (documented, not hidden): ``odds_asks.payload_hash`` is the hash of the FIRST page of an answer only
(``fbi.odds.capture``: ``raws[0]``). A ``/odds?fixture=`` answer is one page in practice (the provider pages by fixtures, ten to a
page, and the ask names one), so the first page is the whole answer. For a later page the only safe evidence is a body FIRST
fetched within ``PAGE_SPREAD`` of the ask: such a page certainly answered that ask. A later page that answered it with a body seen
before cannot be told apart from an older one, so it is left out and the reading says ``partial`` - a missing page, never a
stale one. No migration is needed for this; recording every page's hash would be a change of the capture, not of this reader.

Only pre-match prices: asks before kick-off, bodies stamped by their fetch (``stamped_by = 'fetch'``) before kick-off, within
``LOOKBACK`` of it (the widest capture window is 72 h; ``fbi.odds.capture.CATCH_UP_LOOKBACK`` is 4 days). The provider's
after-the-match reading (``final_prematch``, stamped by the provider) never counts as in force: it did not exist for us before
kick-off. Database only: no provider request, nothing written.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

LOOKBACK = timedelta(days=4)
"""Asks and bodies older than this before kick-off are not read (the widest capture window is 72 h)."""
PAGE_SPREAD = timedelta(minutes=2)
"""A later page first fetched within this time after an ask was fetched by that ask (pages follow each other in seconds)."""
MAX_ASKS = 200
"""Asks of one match read at most (six windows plus catch-ups in 4 days: a few dozen at the very most)."""

CATALOG_FAMILIES: tuple[str, ...] = ("result", "goals", "goals_half", "corners", "cards", "shots")
"""The families of ``fbi.odds.quote_taxonomy`` whose prices are structured, in the order the product lists them."""

MARKET_CODES: dict[int, str] = {
    # result
    1: "result_1x2", 4: "result_asian_handicap", 12: "result_double_chance", 2: "result_draw_no_bet",
    # goals
    5: "goals_over_under", 8: "goals_btts", 16: "goals_over_under", 17: "goals_over_under",
    # goals by half (the same codes as full time: the period tells them apart)
    6: "goals_over_under", 26: "goals_over_under", 13: "result_1x2", 3: "result_1x2", 34: "goals_btts", 35: "goals_btts",
    7: "half_time_full_time", 105: "goals_over_under", 106: "goals_over_under", 107: "goals_over_under",
    108: "goals_over_under", 109: "result_draw_no_bet", 182: "result_draw_no_bet", 20: "result_double_chance",
    33: "result_double_chance", 11: "highest_scoring_half", 192: "highest_scoring_half", 193: "highest_scoring_half",
    19: "result_asian_handicap", 104: "result_asian_handicap", 22: "goals_odd_even", 63: "goals_odd_even",
    # corners: 307 and 339 are the same market under two provider ids, so they share a code and read as one
    45: "corners_over_under", 55: "corners_1x2", 57: "corners_over_under", 58: "corners_over_under",
    307: "corners_double_chance", 339: "corners_double_chance",
    # cards
    80: "cards_over_under", 82: "cards_over_under", 83: "cards_over_under", 150: "yellow_cards_over_under",
    151: "yellow_cards_over_under", 153: "yellow_cards_over_under", 154: "yellow_cards_double_chance",
    155: "yellow_cards_over_under", 156: "yellow_cards_over_under", 158: "yellow_cards_1x2", 335: "red_cards_over_under",
    # team shots
    87: "shots_on_target_over_under", 88: "shots_on_target_over_under", 89: "shots_on_target_over_under",
    211: "shots_over_under", 221: "shots_over_under", 220: "shots_over_under", 176: "shots_on_target_1x2", 340: "shots_1x2",
}
"""Provider bet id -> the stable code of the market it prices. With the period and the subject of its definition it makes the
market's key (``corners_double_chance.FT.match``), which the web translates; the API never carries words in a language.
A bet switched on by hand that is not listed here reads as ``bet_<id>``: shown, never renamed into something it is not."""

_ORDER: dict[int, int] = {bet_id: i for i, bet_id in enumerate(MARKET_CODES)}

State = Literal["priced", "withdrawn", "unread", "never_asked"]


def market_code(bet_id: int) -> str:
    return MARKET_CODES.get(bet_id, f"bet_{bet_id}")


def market_key(bet_id: int, period: str, subject: str) -> str:
    """The stable key of a market: code, period, subject (``goals_over_under.1H.home``)."""
    return f"{market_code(bet_id)}.{period}.{subject}"


def market_rank(bet_id: int) -> int:
    """Where a market comes in its category: the taxonomy's own order, unknown bets last."""
    return _ORDER.get(bet_id, len(_ORDER) + bet_id)


# ── which body is in force (pure) ─────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Ask:
    """One pre-match ask (``market.odds_asks``): when, how many entries came back, the hash of the first page."""

    asked_at: datetime
    results: int
    payload_hash: str | None


@dataclass(frozen=True, slots=True)
class Reading:
    """What the extractor's ledger (``market.odds_extractions``) says of one body."""

    extraction_id: int
    payload_hash: str
    status: str
    fixture_id: int | None
    captured_at: datetime | None
    stamped_by: str
    page: int
    fetched_at: datetime

    def usable(self, fixture_id: int, kickoff_at: datetime) -> bool:
        return (self.status == "ok" and self.fixture_id == fixture_id and self.stamped_by == "fetch"
                and self.captured_at is not None and self.captured_at < kickoff_at)


@dataclass(frozen=True, slots=True)
class Body:
    """A body whose quotes are in force: its ledger row, and since when it has been the answer."""

    extraction_id: int
    captured_at: datetime
    since: datetime
    page: int


@dataclass(frozen=True, slots=True)
class InForce:
    state: State
    checked_at: datetime | None = None
    """The ask whose answer is in force (``withdrawn``: the empty ask)."""
    bodies: tuple[Body, ...] = ()
    newer_pending: bool = False
    """A newer ask brought a body the extractor has not read yet: what is in force is the newest one it has read."""
    partial: bool = False
    """The match has later pages that cannot be tied to the ask in force: they are left out (see the module docstring)."""


def choose_in_force(asks: Sequence[Ask], readings: Mapping[str, Reading], *, fixture_id: int, kickoff_at: datetime,
                    later_pages: Sequence[Reading] = ()) -> InForce:
    """Which body (or bodies) answered the newest readable ask. ``asks`` in any order; ``readings`` by payload hash;
    ``later_pages`` the ledger rows of the match's pages 2+ (any). Pure: no database, no clock."""
    ordered = sorted((a for a in asks if a.asked_at < kickoff_at), key=lambda a: a.asked_at, reverse=True)
    if not ordered:
        return InForce("never_asked")
    skipped = False
    for index, ask in enumerate(ordered):
        if ask.results <= 0:
            return InForce("withdrawn", checked_at=ask.asked_at, newer_pending=skipped)
        reading = readings.get(ask.payload_hash) if ask.payload_hash else None
        if reading is None or not reading.usable(fixture_id, kickoff_at):
            skipped = True
            continue
        assert reading.captured_at is not None
        bodies = [Body(reading.extraction_id, reading.captured_at,
                       _run_start(ordered, index, reading.captured_at), reading.page)]
        pages = [p for p in later_pages if p.usable(fixture_id, kickoff_at) and p.page >= 2]
        fetched_here = [p for p in pages if ask.asked_at <= p.fetched_at < ask.asked_at + PAGE_SPREAD]
        for page in sorted(fetched_here, key=lambda p: (p.page, p.fetched_at)):
            assert page.captured_at is not None
            bodies.append(Body(page.extraction_id, page.captured_at, page.captured_at, page.page))
        return InForce("priced", checked_at=ask.asked_at, bodies=tuple(bodies), newer_pending=skipped,
                       partial=bool(pages) and not fetched_here)
    return InForce("unread", checked_at=ordered[0].asked_at, newer_pending=True)


def _run_start(ordered: Sequence[Ask], index: int, captured_at: datetime) -> datetime:
    """The first ask of the run of asks answered by the same body as ``ordered[index]`` (newest first). A run that reaches the
    oldest ask read goes back to the body's first sighting."""
    payload = ordered[index].payload_hash
    j = index
    while j + 1 < len(ordered) and ordered[j + 1].payload_hash == payload and ordered[j + 1].results > 0:
        j += 1
    if j + 1 < len(ordered):
        return max(ordered[j].asked_at, captured_at)
    return captured_at


# ── the database ──────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CurrentQuote:
    """One price in force: the bookmaker, the market (bet and its definition), the selection, the line, the odds."""

    bookmaker_id: int
    bookmaker: str
    bet_id: int
    family: str
    period: str
    subject: str
    kind: str
    has_line: bool
    market_key: str | None
    provider_name: str
    selection: str
    line: Decimal
    odds: Decimal
    captured_at: datetime
    since: datetime


@dataclass(frozen=True, slots=True)
class CurrentBook:
    fixture_id: int
    kickoff_at: datetime
    in_force: InForce
    quotes: tuple[CurrentQuote, ...]


FIXTURE_SQL = "SELECT id, provider_fixture_id, kickoff_at FROM core.fixtures WHERE id = %(f)s"

ASKS_SQL = """
SELECT asked_at, results, payload_hash FROM market.odds_asks
 WHERE provider_fixture_id = %(pid)s AND asked_at >= %(lo)s AND asked_at < %(ko)s
 ORDER BY asked_at DESC LIMIT %(limit)s
"""
"""The primary key (provider_fixture_id, asked_at) serves it."""

READINGS_SQL = """
SELECT id, payload_hash, status, fixture_id, captured_at, stamped_by, coalesce(page, 1) AS page, fetched_at
  FROM market.odds_extractions WHERE payload_hash = ANY(%(hashes)s)
"""
"""The unique payload_hash serves it."""

LATER_PAGES_SQL = """
SELECT id, payload_hash, status, fixture_id, captured_at, stamped_by, page, fetched_at
  FROM market.odds_extractions
 WHERE fixture_id = %(f)s AND captured_at >= %(lo)s AND captured_at < %(ko)s AND page >= 2
   AND status = 'ok' AND stamped_by = 'fetch'
"""
"""``odds_extractions_fixture_idx`` (fixture_id, captured_at) serves it."""

QUOTES_SQL = """
SELECT q.bookmaker_id, b.name AS bookmaker, d.provider_bet_id AS bet_id, d.family, d.period, d.subject, d.kind,
       d.has_line, d.market_key, d.name AS provider_name, q.selection, q.line, q.odds_decimal AS odds, q.captured_at,
       q.extraction_id
  FROM market.odds_quotes q
  JOIN market.market_definitions d ON d.id = q.definition_id
  JOIN market.bookmakers b ON b.id = q.bookmaker_id
 WHERE q.fixture_id = %(f)s AND q.extraction_id = ANY(%(x)s)
   AND q.captured_at >= %(lo)s AND q.captured_at <= %(hi)s
   AND d.scope = 'prematch' AND d.family = ANY(%(families)s)
"""
"""The quotes of exactly the bodies in force. The ``captured_at`` bounds are those bodies' own instants: they prune the monthly
partitions, and the primary key (fixture_id, ...) finds the rows."""


def _reading(row: Mapping[str, Any]) -> Reading:
    return Reading(extraction_id=int(row["id"]), payload_hash=str(row["payload_hash"]), status=str(row["status"]),
                   fixture_id=int(row["fixture_id"]) if row["fixture_id"] is not None else None,
                   captured_at=row["captured_at"], stamped_by=str(row["stamped_by"]), page=int(row["page"] or 1),
                   fetched_at=row["fetched_at"])


@dataclass(frozen=True, slots=True)
class Located:
    """Which answer of a match is in force, and the RAW body behind every ledger row the choice looked at."""

    fixture_id: int
    provider_fixture_id: int
    kickoff_at: datetime
    in_force: InForce
    payload_hashes: Mapping[int, str]
    """extraction id -> payload hash, for every reading ``choose_in_force`` was given (the bodies in force among them)."""


def locate_in_force(conn: psycopg.Connection[Any], fixture_id: int) -> Located | None:
    """The answer in force of a match (``choose_in_force`` over its asks and the extractor's ledger). None when the match does
    not exist. Database only; nothing written. ``read_in_force`` and the current-price book (``fbi.odds.book``) both read the
    prices in force through this one function, so the two cannot disagree about which answer that is."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURE_SQL, {"f": fixture_id})
        fixture = cur.fetchone()
        if fixture is None:
            return None
        kickoff: datetime = fixture["kickoff_at"]
        lo = kickoff - LOOKBACK
        cur.execute(ASKS_SQL, {"pid": int(fixture["provider_fixture_id"]), "lo": lo, "ko": kickoff, "limit": MAX_ASKS})
        asks = [Ask(r["asked_at"], int(r["results"]), r["payload_hash"]) for r in cur.fetchall()]
        hashes = sorted({a.payload_hash for a in asks if a.payload_hash})
        readings: dict[str, Reading] = {}
        later: list[Reading] = []
        if hashes:
            cur.execute(READINGS_SQL, {"hashes": hashes})
            readings = {r.payload_hash: r for r in map(_reading, cur.fetchall())}
            cur.execute(LATER_PAGES_SQL, {"f": fixture_id, "lo": lo, "ko": kickoff})
            later = [_reading(r) for r in cur.fetchall()]
    in_force = choose_in_force(asks, readings, fixture_id=fixture_id, kickoff_at=kickoff, later_pages=later)
    payload_hashes = {r.extraction_id: r.payload_hash for r in (*readings.values(), *later)}
    return Located(fixture_id=fixture_id, provider_fixture_id=int(fixture["provider_fixture_id"]), kickoff_at=kickoff,
                   in_force=in_force, payload_hashes=payload_hashes)


def read_in_force(conn: psycopg.Connection[Any], fixture_id: int) -> CurrentBook | None:
    """The match's prices in force, in the structured families. None when the match does not exist."""
    located = locate_in_force(conn, fixture_id)
    if located is None:
        return None
    kickoff, in_force = located.kickoff_at, located.in_force
    with conn.cursor(row_factory=dict_row) as cur:
        quotes: list[CurrentQuote] = []
        if in_force.bodies:
            since = {b.extraction_id: b.since for b in in_force.bodies}
            cur.execute(QUOTES_SQL, {"f": fixture_id, "x": sorted(since),
                                     "lo": min(b.captured_at for b in in_force.bodies),
                                     "hi": max(b.captured_at for b in in_force.bodies),
                                     "families": list(CATALOG_FAMILIES)})
            for r in cur.fetchall():
                quotes.append(CurrentQuote(
                    bookmaker_id=int(r["bookmaker_id"]), bookmaker=str(r["bookmaker"]), bet_id=int(r["bet_id"]),
                    family=str(r["family"]), period=str(r["period"]), subject=str(r["subject"]), kind=str(r["kind"]),
                    has_line=bool(r["has_line"]), market_key=r["market_key"], provider_name=str(r["provider_name"]),
                    selection=str(r["selection"]), line=Decimal(r["line"]), odds=Decimal(r["odds"]),
                    captured_at=r["captured_at"], since=since[int(r["extraction_id"])]))
    return CurrentBook(fixture_id=fixture_id, kickoff_at=kickoff, in_force=in_force, quotes=tuple(quotes))
