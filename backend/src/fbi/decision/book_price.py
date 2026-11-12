"""The odds book's price as of a moment, for the core markets of decision-v2: its second price source, in SHADOW (plan Intelligence 2026,
INT-A06, IA-037).

TWO SOURCES, ONE WAY OF PRICING. decision-v2's core family reads its price as decision-v1 does (``fbi.intel.decision.CANDIDATES_SQL``): the
newest Shin consensus of a CAPTURE (``market.market_consensus``), so the price is as old as the last of the six capture windows (T-72 h ...
T-3 h) - the source ``consensus``, the default and the evidence of P1. The source ``book`` is the price IN FORCE in the odds book at the
moment (plan Cuotas, BE-010 and BE-011): the answer the provider last gave for the match, to a capture (``market.odds_asks``) or to a book
refresh (``market.book_asks``), chosen by the book's own rule (``fbi.odds.quote_current.choose_in_force``: the newest ask decides, A -> B -> A
reads A, an empty answer withdraws every price) and priced EXACTLY as a capture is priced into the consensus: the provider's body read by the
capture's normaliser (``iter_odds``) and de-vigged by ``fbi.market.consensus.consensus`` (Shin). The two sources differ in WHEN the price was
confirmed, never in how it is computed: on 286 capture bodies of 9-11 Nov 2026 the consensus rebuilt this way is the stored one to the last
digit (24,115 selections; ``docs/owner/IA_037_PRECIO_CON_EDAD.md``).

THE AGE of a book price is the time since the ask that confirmed the answer in force (``checked_at``), as the book and the explorer count it
(``fbi.odds.freshness``): a price that did not change is not an old price. Beside it, the provider's own stamp of that answer (``update``):
when the provider last moved its prices - information, not a filter.

THE CLOSE, for the closing-line value: the answer in force just before kick-off, with how far from kick-off its ask came and the provider's
stamp (``engine.Close``). A measurement of the replay: it did not exist at the moment of a decision and no stage reads it.

WHAT IT READS. The asks of both tables and the RAW index rows of their bodies, by match and time (primary keys), the bookmakers' ids, and the
bodies from the RAW store on disk (``fbi.storage.payload_store``, re-hashed before they are believed). Not the extractor's ledger nor
``market.odds_quotes``: a refresh's body is never extracted (``quote_extract`` skips it), and reading every body from RAW prices the two kinds
alike. Known limits, the book's own: an answer is its first page (``odds_asks.payload_hash`` is the first page's; a ``/odds?fixture=`` answer
is one page in practice), and the few minutes the extractor runs behind a capture are not modelled. Nothing is written; nothing that decides,
publishes or serves users reaches this module (``tests/unit/test_decision_v2_isolation.py``).
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.decision.engine import BOOK, Close
from fbi.decision.families import Candidate
from fbi.domain.market_probability import DevigMethod
from fbi.intel.decision import LINE_Q, Key
from fbi.market.consensus import CONSENSUS_MARKETS, BookQuote, consensus
from fbi.odds.quote_current import LOOKBACK, Ask, InForce, Reading, choose_in_force
from fbi.odds.quote_extract import load_body
from fbi.providers.api_football.normalize import iter_odds
from fbi.storage.payload_store import PayloadStore

VERSION: Final = "book-price-v1"
CAPTURE: Final = "capture"
REFRESH: Final = "refresh"
UNREADABLE: Final = "unreadable"
"""The state of an answer whose body is in force but could not be read from RAW: then nothing of the match is priced (as the book does)."""
NOT_QUOTED: Final = "not_quoted"
"""Why a selection has no book price when the answer in force does not price it."""
UNKNOWN_BOOKMAKER: Final = 1_000_000_000
"""A bookmaker of an answer the database does not list (a refresh can bring one no capture saw yet) takes this plus its provider id: the
consensus breaks a tie of best prices on the lowest id, so an unlisted bookmaker never wins a tie over a listed one."""
JUST_BEFORE: Final = timedelta(microseconds=1)

FIXTURES_SQL: Final = "SELECT id, provider_fixture_id, kickoff_at FROM core.fixtures WHERE id = ANY(%(ids)s::bigint[])"
ASKS_SQL: Final = """
SELECT 'capture' AS kind, provider_fixture_id, asked_at, results, payload_hash FROM market.odds_asks
 WHERE provider_fixture_id = ANY(%(pids)s::bigint[]) AND asked_at >= %(lo)s AND asked_at < %(hi)s
UNION ALL
SELECT 'refresh' AS kind, provider_fixture_id, asked_at, results, payload_hash FROM market.book_asks
 WHERE provider_fixture_id = ANY(%(pids)s::bigint[]) AND asked_at >= %(lo)s AND asked_at < %(hi)s
"""
"""Every ask of the matches in the window that can hold their pre-match answers. The primary keys (provider_fixture_id, asked_at) of both
tables serve it (measured with EXPLAIN in production, 11 Nov 2026)."""
INDEX_SQL: Final = """
SELECT hash, file_path, http_status, results_count, params FROM raw.ingestion_payloads WHERE hash = ANY(%(hashes)s::text[])
"""
"""The RAW index rows of the bodies the asks brought (its primary key, the hash)."""
BOOKMAKERS_SQL: Final = "SELECT provider_bookmaker_id, id FROM market.bookmakers WHERE provider_bookmaker_id IS NOT NULL"


@dataclass(frozen=True, slots=True)
class TaggedAsk:
    """One ask for a match's pre-match odds, of the capture or of a book refresh."""

    kind: str
    asked_at: datetime
    results: int
    payload_hash: str | None


@dataclass(frozen=True, slots=True)
class Indexed:
    """A body's row of the RAW index (``raw.ingestion_payloads``)."""

    payload_hash: str
    file_path: str
    http_status: int
    results_count: int
    params: Mapping[str, Any]

    @property
    def named_fixture(self) -> int | None:
        """The match the ask named (``/odds?fixture=``)."""
        try:
            return int(self.params["fixture"])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def page(self) -> int:
        try:
            return int(self.params.get("page") or 1)
        except (TypeError, ValueError):
            return 1


@dataclass(frozen=True, slots=True)
class Quoted:
    """The consensus of one selection in an answer, as ``market.market_consensus`` would hold it (Shin)."""

    best_odds: float
    p_fair: float
    n_bookmakers: int
    overround: float
    dispersion: float | None
    best_bookmaker_id: int


SelectionKey = tuple[str, str, Decimal]
"""(market, selection, line): a selection of a match."""


@dataclass(frozen=True, slots=True)
class Answer:
    """What the book held for one match at a moment: the state of the answer in force (``quote_current.State``, or ``UNREADABLE``), the ask
    that confirmed it and its kind, since when it has been the answer, the provider's own stamp and the consensus of every selection it prices."""

    fixture_id: int
    state: str
    checked_at: datetime | None = None
    confirmed_by: str | None = None
    since: datetime | None = None
    payload_hash: str | None = None
    provider_update_at: datetime | None = None
    prices: Mapping[SelectionKey, Quoted] = field(default_factory=dict)

    def price(self, key: Key) -> Quoted | None:
        return self.prices.get((key[1], key[2], key[3]))


# -- the answer in force (pure) -----------------------------------------------------------------------------------------------------------

def readings(asks: Sequence[TaggedAsk], index: Mapping[str, Indexed], *, fixture_id: int,
             provider_fixture_id: int) -> tuple[dict[str, Reading], dict[int, str]]:
    """Every body the asks brought as a reading of the book's rule, from its RAW index row: usable when the provider answered with entries
    (HTTP 200, results) an ask that named this match, first seen at the first ask that brought it. Returns the readings by hash and the hash of
    each reading's id (the ids are negative: no extraction stands behind them, as in ``fbi.odds.book``). Pure."""
    first: dict[str, datetime] = {}
    for a in asks:
        if a.payload_hash:
            first[a.payload_hash] = min(first.get(a.payload_hash, a.asked_at), a.asked_at)
    out: dict[str, Reading] = {}
    ids: dict[int, str] = {}
    for n, payload_hash in enumerate(sorted(first), start=1):
        row = index.get(payload_hash)
        ok = row is not None and row.http_status == 200 and row.results_count > 0 and row.named_fixture == provider_fixture_id
        out[payload_hash] = Reading(extraction_id=-n, payload_hash=payload_hash, status="ok" if ok else UNREADABLE,
                                    fixture_id=fixture_id if ok else None, captured_at=first[payload_hash], stamped_by="fetch",
                                    page=1 if row is None else row.page, fetched_at=first[payload_hash])
        ids[-n] = payload_hash
    return out, ids


def in_force(asks: Sequence[TaggedAsk], found: Mapping[str, Reading], *, fixture_id: int, kickoff_at: datetime, at: datetime) -> InForce:
    """The answer in force at ``at``: the book's rule over the asks made by then (never one after it). Pure."""
    return choose_in_force([Ask(a.asked_at, a.results, a.payload_hash) for a in asks if a.asked_at <= at], found, fixture_id=fixture_id,
                           kickoff_at=kickoff_at)


def kind_of(asks: Sequence[TaggedAsk], checked_at: datetime | None) -> str | None:
    """The kind of the ask made at ``checked_at`` (the capture's when both tables hold one at that instant). Pure."""
    kinds = {a.kind for a in asks if a.asked_at == checked_at}
    return None if not kinds else CAPTURE if CAPTURE in kinds else min(kinds)


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _entry_fixture(entry: Mapping[str, Any]) -> int | None:
    fixture = entry.get("fixture")
    named = fixture.get("id") if isinstance(fixture, Mapping) else fixture
    return named if isinstance(named, int) else None


def provider_stamp(body: Mapping[str, Any], provider_fixture_id: int) -> datetime | None:
    """The provider's ``update`` stamp of the match's entry in a body (when it last moved those prices). Pure."""
    response = body.get("response")
    for entry in response if isinstance(response, list) else []:
        if isinstance(entry, Mapping) and _entry_fixture(entry) == provider_fixture_id:
            return _instant(entry.get("update"))
    return None


def price_body(body: Mapping[str, Any], *, provider_fixture_id: int, kickoff_at: datetime,
               bookmakers: Mapping[int, int]) -> tuple[dict[SelectionKey, Quoted], datetime | None]:
    """The consensus (Shin) of every selection one body prices for the match - as the capture's consensus is computed from the same body:
    the capture's normaliser (``iter_odds``), the consensus markets, the bookmakers' own ids - and the provider's stamp. Pure."""
    quotes = [q for q in iter_odds(dict(body), kickoff_at=kickoff_at, captured_at=kickoff_at, payload_hash="", source="prematch")
              if q.provider_fixture_id == provider_fixture_id and q.market_key in CONSENSUS_MARKETS]
    rows = consensus([BookQuote(bookmakers.get(q.provider_bookmaker_id, UNKNOWN_BOOKMAKER + q.provider_bookmaker_id), q.market_key,
                                q.selection, Decimal(q.line), q.odds_decimal) for q in quotes], methods=(DevigMethod.SHIN,))
    prices = {(r.market_key, r.selection, Decimal(r.line).quantize(LINE_Q)):
              Quoted(float(r.best_odds), round(r.p_fair, 6), int(r.n_bookmakers), round(r.overround, 5),
                     None if r.dispersion is None else round(r.dispersion, 6), int(r.best_bookmaker_id))
              for r in rows}  # rounded as market.market_consensus stores them (``consensus.write_consensus``): the same numbers to the digit
    return prices, provider_stamp(body, provider_fixture_id)


# -- the book of a set of matches ---------------------------------------------------------------------------------------------------------

Priced = tuple[dict[SelectionKey, Quoted], datetime | None]


@dataclass
class BookReader:
    """The odds book of a set of matches, read once from the database and answered as of any moment (``answer_at``). Each body is read
    from RAW once (``bodies``, by hash). Read-only."""

    store: PayloadStore | None
    fixtures: Mapping[int, tuple[int, datetime]]
    """fixture id -> (provider fixture id, kick-off)."""
    asks: Mapping[int, Sequence[TaggedAsk]]
    """fixture id -> its asks in the window before kick-off, oldest first."""
    index: Mapping[str, Indexed]
    bookmakers: Mapping[int, int]
    """provider bookmaker id -> ``market.bookmakers.id``."""
    verify: bool = True
    bodies: dict[str, Priced | None] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def _priced(self, payload_hash: str, provider_fixture_id: int, kickoff_at: datetime) -> Priced | None:
        if payload_hash in self.bodies:
            return self.bodies[payload_hash]
        row = self.index.get(payload_hash)
        out: Priced | None = None
        if row is None or self.store is None:
            self.problems.append(f"{payload_hash[:12]}: " + ("not in the RAW index" if row is None else "no RAW store given"))
        else:
            body, problem, _missing = load_body(self.store, {"file_path": row.file_path, "hash": payload_hash}, verify=self.verify)
            if body is None:
                self.problems.append(problem or f"{payload_hash[:12]}: unreadable")
            else:
                out = price_body(body, provider_fixture_id=provider_fixture_id, kickoff_at=kickoff_at, bookmakers=self.bookmakers)
        self.bodies[payload_hash] = out
        return out

    def answer_at(self, fixture_id: int, at: datetime) -> Answer:
        """What the book held for the match at ``at``."""
        if fixture_id not in self.fixtures:
            return Answer(fixture_id, "never_asked")
        provider_fixture_id, kickoff_at = self.fixtures[fixture_id]
        mine = self.asks.get(fixture_id, ())
        found, ids = readings(mine, self.index, fixture_id=fixture_id, provider_fixture_id=provider_fixture_id)
        chosen = in_force(mine, found, fixture_id=fixture_id, kickoff_at=kickoff_at, at=at)
        kind = kind_of(mine, chosen.checked_at)
        if chosen.state != "priced" or not chosen.bodies or chosen.checked_at is None:
            return Answer(fixture_id, chosen.state, checked_at=chosen.checked_at, confirmed_by=kind)
        lead = chosen.bodies[0]
        payload_hash = ids[lead.extraction_id]
        priced = self._priced(payload_hash, provider_fixture_id, kickoff_at)
        if priced is None:
            return Answer(fixture_id, UNREADABLE, checked_at=chosen.checked_at, confirmed_by=kind, payload_hash=payload_hash)
        prices, stamp = priced
        return Answer(fixture_id, "priced", chosen.checked_at, kind, lead.since, payload_hash, stamp, prices)

    def answers_at(self, fixture_ids: Iterable[int], at: datetime) -> dict[int, Answer]:
        return {f: self.answer_at(f, at) for f in sorted(set(fixture_ids))}

    def close(self, fixture_id: int) -> Answer:
        """The answer in force at kick-off: the last one before it."""
        if fixture_id not in self.fixtures:
            return Answer(fixture_id, "never_asked")
        return self.answer_at(fixture_id, self.fixtures[fixture_id][1] - JUST_BEFORE)


def read(conn: psycopg.Connection[Any], store: PayloadStore | None, fixture_ids: Iterable[int], *, verify: bool = True) -> BookReader:
    """The book of these matches: their asks of both tables in the window before kick-off, the RAW index of their bodies and the bookmakers'
    ids - four reads, each by key. Read-only."""
    ids = sorted(set(fixture_ids))
    if not ids:
        return BookReader(store, {}, {}, {}, {}, verify)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"ids": ids})
        fixtures = {int(r["id"]): (int(r["provider_fixture_id"]), r["kickoff_at"]) for r in cur.fetchall()
                    if r["provider_fixture_id"] is not None and r["kickoff_at"] is not None}
        if not fixtures:
            return BookReader(store, {}, {}, {}, {}, verify)
        by_provider = {pid: fid for fid, (pid, _) in fixtures.items()}
        kickoffs = [ko for _, ko in fixtures.values()]
        cur.execute(ASKS_SQL, {"pids": sorted(by_provider), "lo": min(kickoffs) - LOOKBACK, "hi": max(kickoffs)})
        asks: dict[int, list[TaggedAsk]] = defaultdict(list)
        for r in cur.fetchall():
            fid = by_provider[int(r["provider_fixture_id"])]
            kickoff_at = fixtures[fid][1]
            if kickoff_at - LOOKBACK <= r["asked_at"] < kickoff_at:
                asks[fid].append(TaggedAsk(str(r["kind"]), r["asked_at"], int(r["results"]), r["payload_hash"]))
        hashes = sorted({a.payload_hash for xs in asks.values() for a in xs if a.payload_hash})
        index: dict[str, Indexed] = {}
        if hashes:
            cur.execute(INDEX_SQL, {"hashes": hashes})
            index = {str(r["hash"]): Indexed(str(r["hash"]), str(r["file_path"]), int(r["http_status"] or 0), int(r["results_count"] or 0),
                                             r["params"] if isinstance(r["params"], Mapping) else {}) for r in cur.fetchall()}
        cur.execute(BOOKMAKERS_SQL)
        bookmakers = {int(r["provider_bookmaker_id"]): int(r["id"]) for r in cur.fetchall()}
    ordered = {f: sorted(xs, key=lambda a: (a.asked_at, a.kind)) for f, xs in asks.items()}
    return BookReader(store, fixtures, ordered, index, bookmakers, verify)


# -- the candidates, priced by the book (pure) ----------------------------------------------------------------------------------------------

PRICE_FIELDS: Final = ("best_odds", "p_fair", "n_bookmakers", "overround", "dispersion", "best_bookmaker_id", "price_at")
"""The fields of a candidate's row that hold its price (``fbi.intel.decision.CANDIDATES_SQL``): all of them are replaced, none is kept."""


def book_fields(answer: Answer | None, key: Key) -> dict[str, Any]:
    """The price fields of a candidate's row as the book gives them for the selection, with where they come from; the price fields empty
    and the reason when the book has no price for it. Pure."""
    quoted = None if answer is None else answer.price(key)
    held: dict[str, Any] = {"price_source": BOOK, "price_confirmed_by": None if answer is None else answer.confirmed_by,
                            "provider_update_at": None if answer is None else answer.provider_update_at,
                            "price_since": None if answer is None else answer.since}
    if answer is None or quoted is None:
        reason = "never_asked" if answer is None else NOT_QUOTED if answer.state == "priced" else answer.state
        return held | dict.fromkeys(PRICE_FIELDS) | {"price_missing": reason}
    return held | {"best_odds": quoted.best_odds, "p_fair": quoted.p_fair, "n_bookmakers": quoted.n_bookmakers, "overround": quoted.overround,
                   "dispersion": quoted.dispersion, "best_bookmaker_id": quoted.best_bookmaker_id, "price_at": answer.checked_at,
                   "price_missing": None}


def priced(candidates: Sequence[Candidate], answers: Mapping[int, Answer], *, family: str) -> list[Candidate]:
    """The candidates of ``family`` with the book's price in place of the one they were read with (every model row of a selection takes
    the same price, as the consensus gives them one); the candidates of other families as they are. Pure: nothing given is changed."""
    out: list[Candidate] = []
    for c in candidates:
        if c.family.name != family:
            out.append(c)
            continue
        fields = book_fields(answers.get(c.key[0]), c.key)
        out.append(dataclasses.replace(c, models={m: {**row, **fields} for m, row in c.models.items()}))
    return out


def close_of(answer: Answer, kickoff_at: datetime) -> dict[SelectionKey, Close]:
    """The close of every selection the last answer before kick-off prices. Pure."""
    if answer.state != "priced" or answer.checked_at is None:
        return {}
    checked_at = answer.checked_at
    stamp = answer.provider_update_at

    def minutes(moment: datetime) -> float:
        return round((kickoff_at - moment).total_seconds() / 60, 2)

    return {k: Close(q.best_odds, q.p_fair, q.n_bookmakers, checked_at, minutes(checked_at), answer.confirmed_by or CAPTURE, stamp,
                     None if stamp is None else minutes(stamp), VERSION) for k, q in answer.prices.items()}


def closes(reader: BookReader, fixture_ids: Iterable[int]) -> dict[Key, Close]:
    """The close of every selection of these matches: the book's last price before kick-off (a measurement, never an input)."""
    out: dict[Key, Close] = {}
    for fid in sorted(set(fixture_ids)):
        if fid not in reader.fixtures:
            continue
        for (market, selection, line), c in close_of(reader.close(fid), reader.fixtures[fid][1]).items():
            out[(fid, market, selection, line)] = c
    return out
