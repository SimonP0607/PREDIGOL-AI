"""The current-price book: the prices IN FORCE of every match, for every bet type ``tax-v3`` can read (plan Cuotas, BE-010).

``market.odds_quotes`` is the price HISTORY of the 55 types ``tax-v2`` extracts; models, picks and the shadow families read it, and
it is not touched here. The explorer needs the present instead: for each upcoming match and each of the 128 visible types of
``tax-v3`` (``fbi.odds.book_taxonomy``), the odds of every bookmaker in the provider's answer in force, the best one, how many
bookmakers quote it and, where it means something, the fair price. This module builds that, one row per (match, type), into
``market.book_current`` (migration 0128).

* WHICH ANSWER: ``fbi.odds.quote_current.locate_in_force`` - the function the Match Center reads through - so the book and the
  Match Center cannot disagree: the newest pre-match ask decides (A -> B -> A reads A), an empty answer withdraws every price and
  the match's rows are deleted, an answer the extractor has not read yet waits (the older one stands in, ``newer_pending``).
* WHAT IS IN IT: the body is read back from RAW (re-hashed: a file that does not give its hash is not read) and every bookmaker's
  values are read by ``tax-v3`` (``fbi.odds.book_parse``). A value that cannot be read HIDES its type for that match, and so does
  a renamed bet or a bookmaker whose values contradict each other: shown wrong is worse than not shown.
* THE FAIR PRICE, only where the type is exhaustive and has a method (``BookSpec.fair``) and three bookmakers or more quote a
  complete book of the line: each bookmaker de-vigged on its own with ``fbi.domain.market_probability.devig`` (Shin, or in
  proportion for the count bands), the probabilities averaged; Asian handicaps pair Home h with Away -h and keep only believable
  pairs (``fbi.market.consensus.MAX_TWO_WAY_BOOK``), double chance goes through the 1X2 book it implies
  (``fbi.market.consensus.consensus``, as ``market.market_consensus`` does). On a line that can push (a whole or quarter
  handicap, a whole total, draw no bet) the fair probability is conditional on the bet being settled, as everywhere else.
  ``edge = best * p - 1``; an edge above 0.25 is flagged ``outlier`` (plan E2: such a price is suspect, not a bargain).
* BEST PRICE: the highest odds among ALL the bookmakers in force for the selection (one definition, plan E12), the lowest
  provider bookmaker id on a tie.

A cache, never a source: idempotent (a second build writes nothing; a row is rewritten only when what it says changed) and
deterministic (the same rows from the same database and RAW). The worker's job (``run_book_job``, ``odds_book_build``) runs only
while ``FBI_ODDS_BOOK`` is on, builds the matches whose asks or extractions changed since its last pass and deletes the rows of
matches that kicked off more than 6 hours ago. It asks the provider nothing. ``python -m scripts.rebuild_odds_book`` rebuilds by
hand (dry run by default).
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row, tuple_row

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.errors import InvalidOddsError
from fbi.domain.market_probability import DevigMethod, devig
from fbi.domain.odds import DecimalOdds
from fbi.market.consensus import MAX_TWO_WAY_BOOK, BookQuote, consensus
from fbi.odds.book_parse import (
    Read,
    band,
    check_book,
    group_outcomes,
    partition_complete,
    read_value,
    ways_of,
)
from fbi.odds.book_taxonomy import BOOK_TAXONOMY_VERSION, BookSpec, book_spec
from fbi.odds.quote_current import LOOKBACK, Located, locate_in_force
from fbi.odds.quote_extract import load_body
from fbi.odds.quote_parse import parse_odds
from fbi.odds.quote_taxonomy import PROVIDER, SCOPE, same_name
from fbi.storage.payload_store import PayloadStore

log = structlog.get_logger(__name__)

BUILDER_VERSION = f"bk-1/{BOOK_TAXONOMY_VERSION}"
"""Moves when the way a row is built changes (this module, the readers or the taxonomy): the job then rebuilds every row."""
SUMMARY_LAYOUT = 1
JOB = "odds_book_build"
LOCK_KEY = "fbi.odds_book_build"
PURGE_AFTER = timedelta(hours=6)
"""Rows of a match that kicked off more than this long ago are deleted (plan decision 7: a cache; the history is in RAW)."""
CHANGE_MARGIN = timedelta(minutes=15)
"""The job looks this far behind its last pass: an extraction is stamped with the start of its run and committed up to four
minutes later, so a change is never missed between two passes (a match built twice costs nothing)."""
MIN_FAIR_BOOKS = 3
OUTLIER_EDGE = 0.25
DEFAULT_PER_RUN = 1500
DEFAULT_RUN_SECONDS = 240.0
BATCH = 25

_DC_OUTCOMES = ("1X", "12", "X2")
_PARTITIONED = ("count", "range")
_ORDERED_BY_PRICE = ("player", "player_count")


# ── one answer, read (pure) ───────────────────────────────────────────────────────────────────────────────────────


@dataclass
class TypePrices:
    """The prices of one type in one answer: (provider bookmaker id, value read, odds), or why the type is not shown."""

    spec: BookSpec
    prices: list[tuple[int, Read, Decimal]] = field(default_factory=list)
    books: set[int] = field(default_factory=set)
    hidden: str | None = None


@dataclass
class AnswerReading:
    """Every bet of one answer as ``tax-v3`` reads it."""

    types: dict[int, TypePrices] = field(default_factory=dict)
    hidden_by_taxonomy: dict[int, str] = field(default_factory=dict)
    unknown: dict[int, str] = field(default_factory=dict)
    dropped: int = 0
    """Values read whose odds were not a price (the provider's "1.00" placeholders): left out, as the extractor does."""
    bookmakers: int = 0

    def shown(self) -> dict[int, TypePrices]:
        return {b: t for b, t in self.types.items() if t.hidden is None and t.prices}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_answer(entry: Mapping[str, Any]) -> AnswerReading:
    """Every bookmaker's bets of one ``response`` entry, read by ``tax-v3``. Pure: no database, no clock."""
    out = AnswerReading()
    bookmakers = entry.get("bookmakers")
    for book in bookmakers if isinstance(bookmakers, list) else []:
        if not isinstance(book, dict):
            continue
        book_id = _int(book.get("id"))
        if book_id is None:
            continue
        out.bookmakers += 1
        bets = book.get("bets")
        for bet in bets if isinstance(bets, list) else []:
            if not isinstance(bet, dict):
                continue
            bet_id = _int(bet.get("id"))
            if bet_id is None:
                continue
            name = bet.get("name") if isinstance(bet.get("name"), str) else ""
            spec = book_spec(bet_id)
            if spec is None:
                out.unknown.setdefault(bet_id, str(name))
                continue
            if not spec.visible:
                out.hidden_by_taxonomy.setdefault(bet_id, spec.hidden_reason or "hidden")
                continue
            held = out.types.setdefault(bet_id, TypePrices(spec))
            if held.hidden is not None:
                continue
            if name and not same_name(str(name), spec.name):
                held.hidden = f"renamed by the provider: {name!r}"
                continue
            if book_id in held.books:
                held.hidden = f"bookmaker {book_id} sends the type twice"
                continue
            priced, problem, dropped = _read_book(spec, bet.get("values"))
            out.dropped += dropped
            if problem is not None:
                held.hidden = problem
                continue
            if priced:
                held.books.add(book_id)
                held.prices.extend((book_id, read, odds) for read, odds in priced)
    return out


def _read_book(spec: BookSpec, values: Any) -> tuple[list[tuple[Read, Decimal]], str | None, int]:
    """One bookmaker's values of one type: what was read, the reason the type cannot be shown (or None), prices dropped."""
    priced: list[tuple[Read, Decimal]] = []
    dropped = 0
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            return [], f"a value that is not an object: {str(value)[:40]!r}", dropped
        read = read_value(spec, value.get("value"))
        if read is None:
            return [], f"unreadable value {str(value.get('value'))[:40]!r}", dropped
        odds = parse_odds(value.get("odd"))
        if odds is None:
            dropped += 1
            continue
        priced.append((read, odds))
    problem = check_book(spec, priced)
    return ([], problem, dropped) if problem else (priced, None, dropped)


# ── one type, summarised (pure) ───────────────────────────────────────────────────────────────────────────────────


Cell = dict[tuple[str, Decimal | None], dict[int, Decimal]]
"""(selection, its own line) -> provider bookmaker id -> odds: the prices of one group (line) of a type."""


def _cells(spec: BookSpec, prices: Sequence[tuple[int, Read, Decimal]]) -> dict[tuple[Decimal | None, int], Cell]:
    """The prices grouped by (group line, ways). ``ways`` is decided per bookmaker (``book_parse.ways_of``): a three-way line
    and a two-way line at the same number are two markets and never share a selection."""
    by_book: dict[int, list[tuple[Read, Decimal]]] = defaultdict(list)
    for book, read, odds in prices:
        by_book[book].append((read, odds))
    cells: dict[tuple[Decimal | None, int], Cell] = defaultdict(lambda: defaultdict(dict))
    for book, priced in by_book.items():
        ways = ways_of(spec, [r for r, _ in priced])
        for read, odds in priced:
            cells[(read.group, ways[read.group])][(read.selection, read.line)][book] = odds
    return cells


def _complete(spec: BookSpec, outcomes: tuple[str, ...], quoted: Mapping[str, Decimal]) -> bool:
    if spec.reader in _PARTITIONED:
        return partition_complete(list(quoted))
    if len(outcomes) < 2 or set(quoted) != set(outcomes):
        return False
    if spec.reader == "signed_line":
        book = sum(1 / o for o in quoted.values())
        return Decimal(1) < book <= Decimal(str(MAX_TWO_WAY_BOOK))
    return True


def fair_probabilities(spec: BookSpec, ways: int, cell: Cell) -> dict[tuple[str, Decimal | None], tuple[float, int]]:
    """(selection, line) -> (fair probability, bookmakers it is the mean of), for the selections at least ``MIN_FAIR_BOOKS``
    complete bookmakers price. Empty where the type allows no fair price."""
    if not spec.fair:
        return {}
    outcomes = group_outcomes(spec, ways)
    line_of: dict[str, Decimal | None] = dict(cell.keys())
    by_book: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for (sel, _line), books in cell.items():
        for book, odds in books.items():
            by_book[book][sel] = odds
    complete = {b: q for b, q in sorted(by_book.items()) if _complete(spec, outcomes, q)}
    if len(complete) < MIN_FAIR_BOOKS:
        return {}
    if outcomes == _DC_OUTCOMES:
        rows = consensus([BookQuote(b, "DC", s, Decimal(0), o) for b, q in complete.items() for s, o in q.items()],
                         methods=(DevigMethod.SHIN,))
        return {(r.selection, line_of[r.selection]): (r.p_fair, r.n_bookmakers) for r in rows
                if r.n_bookmakers >= MIN_FAIR_BOOKS and r.selection in line_of}
    method = DevigMethod.PROPORTIONAL if spec.fair_method == "proportional" else DevigMethod.SHIN
    collected: dict[str, list[float]] = defaultdict(list)
    for quoted in complete.values():
        try:
            fair = devig({s: DecimalOdds(o) for s, o in quoted.items()}, method)
        except InvalidOddsError:  # a book with no margin: a stale or broken quote, left out (as the consensus does)
            continue
        for sel, probability in fair.items():
            collected[sel].append(probability.probability.value)
    return {(sel, line_of[sel]): (statistics.fmean(ps), len(ps)) for sel, ps in collected.items()
            if len(ps) >= MIN_FAIR_BOOKS}


def _order(spec: BookSpec, ways: int, cell: Cell, best: Mapping[tuple[str, Decimal | None], Decimal]) -> list[
        tuple[str, Decimal | None]]:
    outcomes = group_outcomes(spec, ways)
    keys = list(cell)
    if outcomes:
        return sorted(keys, key=lambda k: (outcomes.index(k[0]) if k[0] in outcomes else len(outcomes), k[0]))
    if spec.reader in _PARTITIONED:
        return sorted(keys, key=lambda k: ((band(k[0]) or (10**6, None))[0], k[0]))
    if spec.reader == "exact_score":
        return sorted(keys, key=lambda k: tuple(int(x) for x in k[0].split(":")))
    if spec.reader in _ORDERED_BY_PRICE:
        reserved = set(spec.vocabulary.values())
        return sorted(keys, key=lambda k: (k[0] not in reserved, best[k], k[0]))
    return sorted(keys, key=lambda k: k[0])


def _float(number: Decimal) -> float:
    return float(number)


def summarize(spec: BookSpec, prices: Sequence[tuple[int, Read, Decimal]]) -> dict[str, Any]:
    """The ``summary`` of one type: lines -> selections -> the odds of each bookmaker, the best price and its bookmaker, how many
    bookmakers and, where allowed, the fair price, the difference with it and the outlier flag. Deterministic."""
    groups: list[dict[str, Any]] = []
    cells = _cells(spec, prices)
    for group, ways in sorted(cells, key=lambda k: (k[0] is not None, k[0] if k[0] is not None else Decimal(0), k[1])):
        cell = cells[(group, ways)]
        best_book = {k: min(books, key=lambda b: (-books[b], b)) for k, books in cell.items()}
        best = {k: cell[k][b] for k, b in best_book.items()}
        fair = fair_probabilities(spec, ways, cell)
        selections: list[dict[str, Any]] = []
        for key in _order(spec, ways, cell, best):
            selection, line = key
            books = cell[key]
            out: dict[str, Any] = {
                "sel": selection,
                "odds": {str(b): _float(books[b]) for b in sorted(books)},
                "best": _float(best[key]),
                "best_bk": best_book[key],
                "n": len(books),
            }
            if line != group and line is not None:
                out["line"] = _float(line)
            if key in fair:
                p, n_fair = fair[key]
                edge = float(best[key]) * p - 1.0
                out.update(fair=round(1.0 / p, 3), p=round(p, 6), n_fair=n_fair, edge=round(edge, 4),
                           outlier=edge > OUTLIER_EDGE)
            selections.append(out)
        entry: dict[str, Any] = {"line": None if group is None else _float(group), "sels": selections}
        if ways == 3 and spec.reader == "line":
            entry["ways"] = 3
        groups.append(entry)
    return {"v": SUMMARY_LAYOUT, "books": len({b for b, _, _ in prices}), "lines": groups}


def summary_json(summary: Mapping[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ── the database ──────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class BookReport:
    fixtures_seen: int = 0
    fixtures_priced: int = 0
    states: dict[str, int] = field(default_factory=dict)
    rows: int = 0
    """Rows the answers in force give (written or not)."""
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_deleted: int = 0
    rows_purged: int = 0
    prices: int = 0
    prices_dropped: int = 0
    summary_bytes: int = 0
    types: Counter[int] = field(default_factory=Counter)
    hidden_by_taxonomy: Counter[int] = field(default_factory=Counter)
    hidden_in_answer: Counter[int] = field(default_factory=Counter)
    hidden_samples: dict[int, str] = field(default_factory=dict)
    unknown_bets: dict[int, str] = field(default_factory=dict)
    no_definition: dict[int, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    """What could not be read (a RAW file missing or not giving its hash): the match shows nothing, and that is all."""
    errors: list[str] = field(default_factory=list)
    """What failed (a database error on one match): that match is left as it was."""
    failed: int = 0
    fixtures_left: int = 0
    skipped_locked: bool = False
    stopped_for_time: bool = False
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "builder": BUILDER_VERSION, "dry_run": self.dry_run, "fixtures_seen": self.fixtures_seen,
            "fixtures_priced": self.fixtures_priced, "states": dict(sorted(self.states.items())), "rows": self.rows,
            "rows_inserted": self.rows_inserted, "rows_updated": self.rows_updated, "rows_unchanged": self.rows_unchanged,
            "rows_deleted": self.rows_deleted, "rows_purged": self.rows_purged, "prices": self.prices,
            "prices_dropped": self.prices_dropped, "summary_bytes": self.summary_bytes, "types_shown": len(self.types),
            "hidden_by_taxonomy": dict(sorted(self.hidden_by_taxonomy.items())),
            "hidden_in_answer": dict(sorted(self.hidden_in_answer.items())),
            "hidden_samples": dict(sorted(self.hidden_samples.items())[:20]),
            "unknown_bets": dict(sorted(self.unknown_bets.items())[:20]),
            "no_definition": dict(sorted(self.no_definition.items())[:20]), "problems": self.problems[:20],
            "errors": self.errors[:20], "failed": self.failed, "fixtures_left": self.fixtures_left, "skipped_locked": self.skipped_locked,
            "stopped_for_time": self.stopped_for_time,
        }

    def note(self, reading: AnswerReading) -> None:
        self.prices_dropped += reading.dropped
        for bet_id in reading.hidden_by_taxonomy:
            self.hidden_by_taxonomy[bet_id] += 1
        for bet_id, name in reading.unknown.items():
            self.unknown_bets.setdefault(bet_id, name)
        for bet_id, held in reading.types.items():
            if held.hidden is not None:
                self.hidden_in_answer[bet_id] += 1
                self.hidden_samples.setdefault(bet_id, held.hidden)


@dataclass(frozen=True, slots=True)
class BookRow:
    definition_id: int
    bet_id: int
    summary: dict[str, Any]
    text: str


@dataclass(frozen=True, slots=True)
class FixtureBook:
    """What the book holds for one match: the answer in force and one row per type shown (no row: nothing in force)."""

    fixture_id: int
    kickoff_at: datetime
    state: str
    checked_at: datetime | None = None
    captured_at: datetime | None = None
    in_force_since: datetime | None = None
    provider_update_at: datetime | None = None
    newer_pending: bool = False
    payload_hash: str | None = None
    rows: tuple[BookRow, ...] = ()


PAYLOADS_SQL = "SELECT hash, file_path, fetched_at, params FROM raw.ingestion_payloads WHERE hash = ANY(%(hashes)s)"
DEFINITIONS_SQL = "SELECT provider_bet_id, id FROM market.market_definitions WHERE provider = %(p)s AND scope = %(s)s"

UPSERT_SQL = """
INSERT INTO market.book_current AS b (fixture_id, definition_id, kickoff_at, captured_at, provider_update_at, checked_at,
       in_force_since, newer_pending, payload_hash, builder_version, summary, built_at)
SELECT %(f)s, t.d, %(ko)s, %(cap)s, %(upd)s, %(chk)s, %(since)s, %(pending)s, %(hash)s, %(ver)s, t.s::jsonb, %(at)s
  FROM unnest(%(defs)s::int[], %(sums)s::text[]) AS t(d, s)
ON CONFLICT (fixture_id, definition_id) DO UPDATE SET
       kickoff_at = EXCLUDED.kickoff_at, captured_at = EXCLUDED.captured_at, provider_update_at = EXCLUDED.provider_update_at,
       checked_at = EXCLUDED.checked_at, in_force_since = EXCLUDED.in_force_since, newer_pending = EXCLUDED.newer_pending,
       payload_hash = EXCLUDED.payload_hash, builder_version = EXCLUDED.builder_version, summary = EXCLUDED.summary,
       built_at = EXCLUDED.built_at
 WHERE (b.kickoff_at, b.captured_at, b.provider_update_at, b.checked_at, b.in_force_since, b.newer_pending, b.payload_hash,
        b.builder_version, b.summary)
       IS DISTINCT FROM
       (EXCLUDED.kickoff_at, EXCLUDED.captured_at, EXCLUDED.provider_update_at, EXCLUDED.checked_at, EXCLUDED.in_force_since,
        EXCLUDED.newer_pending, EXCLUDED.payload_hash, EXCLUDED.builder_version, EXCLUDED.summary)
RETURNING (xmax = 0) AS inserted
"""
"""A row is rewritten only when what it says changed: a second build leaves every row, and its ``built_at``, as it was."""

EXISTING_SQL = """
SELECT definition_id, kickoff_at, captured_at, provider_update_at, checked_at, in_force_since, newer_pending, payload_hash,
       builder_version, summary
  FROM market.book_current WHERE fixture_id = %(f)s
"""


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _params_fixture(params: Any) -> int | None:
    try:
        return int(params["fixture"]) if isinstance(params, dict) else None
    except (KeyError, TypeError, ValueError):
        return None


def _entries_for(body: Mapping[str, Any], provider_fixture_id: int, params_fixture: int | None) -> list[Mapping[str, Any]]:
    """The ``response`` entries of a body that are this match's (one, in practice: the ask names one fixture)."""
    out: list[Mapping[str, Any]] = []
    response = body.get("response")
    for item in response if isinstance(response, list) else []:
        if not isinstance(item, dict):
            continue
        fixture = item.get("fixture")
        named = _int(fixture.get("id")) if isinstance(fixture, dict) else None
        if (named or params_fixture) == provider_fixture_id:
            out.append(item)
    return out


def definition_ids(conn: psycopg.Connection[Any]) -> dict[int, int]:
    """provider bet id -> ``market.market_definitions.id`` (pre-match). The book never writes a definition: ``tax-v2`` (the
    extractor) registers every bet it sees, so every bet of an answer it has read has one."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(DEFINITIONS_SQL, {"p": PROVIDER, "s": SCOPE})
        return {int(b): int(i) for b, i in cur.fetchall()}


def read_fixture(conn: psycopg.Connection[Any], store: PayloadStore, fixture_id: int, definitions: Mapping[int, int],
                 report: BookReport, *, verify_hashes: bool = True) -> FixtureBook | None:
    """The book of one match from the database and RAW. Writes nothing. None when the match does not exist."""
    located = locate_in_force(conn, fixture_id)
    if located is None:
        return None
    report.fixtures_seen += 1
    in_force = located.in_force

    def nothing(state: str) -> FixtureBook:
        """No row: nothing is in force (withdrawn, never asked, not read yet) or what is in force cannot be read."""
        report.states[state] = report.states.get(state, 0) + 1
        return FixtureBook(fixture_id=fixture_id, kickoff_at=located.kickoff_at, state=state,
                           checked_at=in_force.checked_at, newer_pending=in_force.newer_pending)

    if in_force.state != "priced" or not in_force.bodies or in_force.checked_at is None:
        return nothing(in_force.state)
    bodies = _bodies(conn, store, located, report, verify_hashes=verify_hashes)
    if bodies is None:
        return nothing("unreadable")
    entries = [e for body, params in bodies for e in _entries_for(body, located.provider_fixture_id, params)]
    if not entries:
        report.problems.append(f"fixture {fixture_id}: the body in force holds no entry for provider fixture "
                               f"{located.provider_fixture_id}")
        return nothing("unreadable")
    report.states[in_force.state] = report.states.get(in_force.state, 0) + 1
    merged = {"bookmakers": [b for e in entries if isinstance(e.get("bookmakers"), list) for b in e["bookmakers"]]}
    reading = read_answer(merged)
    report.note(reading)
    rows: list[BookRow] = []
    for bet_id, held in sorted(reading.shown().items()):
        definition_id = definitions.get(bet_id)
        if definition_id is None:
            report.no_definition.setdefault(bet_id, held.spec.name)
            continue
        summary = summarize(held.spec, held.prices)
        text = summary_json(summary)
        rows.append(BookRow(definition_id=definition_id, bet_id=bet_id, summary=summary, text=text))
        report.types[bet_id] += 1
        report.prices += len(held.prices)
        report.summary_bytes += len(text.encode("utf-8"))
    lead = in_force.bodies[0]
    report.fixtures_priced += 1
    report.rows += len(rows)
    return FixtureBook(fixture_id=fixture_id, kickoff_at=located.kickoff_at, state=in_force.state,
                       checked_at=in_force.checked_at, captured_at=lead.captured_at, in_force_since=lead.since,
                       provider_update_at=_instant(entries[0].get("update")), newer_pending=in_force.newer_pending,
                       payload_hash=located.payload_hashes.get(lead.extraction_id), rows=tuple(rows))


def _bodies(conn: psycopg.Connection[Any], store: PayloadStore, located: Located, report: BookReport, *,
            verify_hashes: bool) -> list[tuple[Mapping[str, Any], int | None]] | None:
    """The RAW bodies in force, lead first, with the fixture their ask named. None when one cannot be read: then nothing of
    the match is shown (a missing page could be the one with the prices)."""
    hashes = [located.payload_hashes.get(b.extraction_id) for b in located.in_force.bodies]
    if any(h is None for h in hashes):
        report.problems.append(f"fixture {located.fixture_id}: a body in force has no payload hash")
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PAYLOADS_SQL, {"hashes": hashes})
        rows = {str(r["hash"]): dict(r) for r in cur.fetchall()}
    out: list[tuple[Mapping[str, Any], int | None]] = []
    for payload_hash in hashes:
        assert payload_hash is not None
        row = rows.get(payload_hash)
        if row is None:
            report.problems.append(f"fixture {located.fixture_id}: payload {payload_hash[:12]} is not indexed")
            return None
        body, problem, _missing = load_body(store, row, verify=verify_hashes)
        if body is None:
            report.problems.append(f"fixture {located.fixture_id}: {problem}")
            return None
        out.append((body, _params_fixture(row.get("params"))))
    return out


def _columns(book: FixtureBook) -> tuple[Any, ...]:
    return (book.kickoff_at, book.captured_at, book.provider_update_at, book.checked_at, book.in_force_since,
            book.newer_pending, book.payload_hash, BUILDER_VERSION)


def write_fixture(conn: psycopg.Connection[Any], book: FixtureBook, report: BookReport, *, at: datetime) -> None:
    """Make the match's rows say what ``book`` says: rows rewritten only where something changed, rows of types no longer shown
    deleted, every row deleted when nothing is in force. The caller commits."""
    keep = [r.definition_id for r in book.rows]
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("DELETE FROM market.book_current WHERE fixture_id = %s AND definition_id <> ALL(%s::int[])",
                    (book.fixture_id, keep))
        report.rows_deleted += max(cur.rowcount, 0)
        if not book.rows:
            return
        cur.execute(UPSERT_SQL, {
            "f": book.fixture_id, "ko": book.kickoff_at, "cap": book.captured_at, "upd": book.provider_update_at,
            "chk": book.checked_at, "since": book.in_force_since, "pending": book.newer_pending, "hash": book.payload_hash,
            "ver": BUILDER_VERSION, "at": at, "defs": keep, "sums": [r.text for r in book.rows]})
        changed = [bool(r[0]) for r in cur.fetchall()]
    inserted = sum(changed)
    report.rows_inserted += inserted
    report.rows_updated += len(changed) - inserted
    report.rows_unchanged += len(book.rows) - len(changed)


def compare_fixture(conn: psycopg.Connection[Any], book: FixtureBook, report: BookReport) -> None:
    """What ``write_fixture`` would do, counted without writing (the dry run)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EXISTING_SQL, {"f": book.fixture_id})
        existing = {int(r["definition_id"]): r for r in cur.fetchall()}
    wanted = {r.definition_id: r for r in book.rows}
    report.rows_deleted += len(set(existing) - set(wanted))
    columns = _columns(book)
    for definition_id, row in wanted.items():
        held = existing.get(definition_id)
        if held is None:
            report.rows_inserted += 1
            continue
        stored = (held["kickoff_at"], held["captured_at"], held["provider_update_at"], held["checked_at"],
                  held["in_force_since"], held["newer_pending"], held["payload_hash"], held["builder_version"])
        if stored != columns or held["summary"] != json.loads(row.text):
            report.rows_updated += 1
        else:
            report.rows_unchanged += 1


def purge(conn: psycopg.Connection[Any], *, now: datetime, apply: bool = True) -> int:
    """Delete (or, ``apply=False``, count) the rows of matches that kicked off more than ``PURGE_AFTER`` ago."""
    with conn.cursor(row_factory=tuple_row) as cur:
        if apply:
            cur.execute("DELETE FROM market.book_current WHERE kickoff_at < %s", (now - PURGE_AFTER,))
            return max(cur.rowcount, 0)
        cur.execute("SELECT count(*) FROM market.book_current WHERE kickoff_at < %s", (now - PURGE_AFTER,))
        row = cur.fetchone()
    return int(row[0]) if row else 0


def build(conn: psycopg.Connection[Any], raw_root: Path | str, fixture_ids: Iterable[int], *, apply: bool,
          now: datetime | None = None, purge_old: bool = False, max_seconds: float | None = None,
          verify_hashes: bool = True, commit: bool = True) -> BookReport:
    """Build the book of ``fixture_ids`` (and, ``purge_old``, delete the rows of matches long started). ``apply=False`` is a dry
    run: everything is read and counted, nothing is written. One build at a time (an advisory lock): a second one reports
    ``skipped_locked``. Commits every ``BATCH`` matches (``commit=False`` leaves the transaction to the caller: a test)."""
    report = BookReport(dry_run=not apply)
    moment = now or clock_now()
    started = time.monotonic()
    queue = list(dict.fromkeys(fixture_ids))
    if apply:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
            locked = cur.fetchone()
        if not locked or not locked[0]:
            report.skipped_locked = True
            report.fixtures_left = len(queue)
            if commit:
                conn.commit()
            return report
    try:
        if purge_old:
            report.rows_purged = purge(conn, now=moment, apply=apply)
        definitions = definition_ids(conn)
        store = PayloadStore(raw_root)
        for index, fixture_id in enumerate(queue):
            if max_seconds is not None and time.monotonic() - started > max_seconds:
                report.stopped_for_time = True
                report.fixtures_left = len(queue) - index
                break
            try:
                with conn.transaction():
                    book = read_fixture(conn, store, fixture_id, definitions, report, verify_hashes=verify_hashes)
                    if book is not None:
                        if apply:
                            write_fixture(conn, book, report, at=moment)
                        else:
                            compare_fixture(conn, book, report)
            except psycopg.Error as exc:
                if conn.closed:
                    raise
                report.failed += 1
                report.errors.append(f"fixture {fixture_id}: {type(exc).__name__}: {str(exc)[:200]}")
                log.warning("odds_book.fixture_failed", fixture=fixture_id, error=str(exc)[:200])
            if commit and (index + 1) % BATCH == 0:
                conn.commit()
        if commit:
            conn.commit()
    finally:
        if apply:
            try:
                if conn.info.transaction_status == TransactionStatus.INERROR:
                    conn.rollback()
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
                if commit:
                    conn.commit()
            except psycopg.Error as exc:
                log.error("odds_book.unlock_failed", error=str(exc)[:200])
    if report.unknown_bets:
        log.warning("odds_book.unknown_bets", bets=sorted(report.unknown_bets.items())[:20])
    if report.hidden_in_answer:
        log.warning("odds_book.types_hidden", bets=sorted(report.hidden_samples.items())[:20])
    log.info("odds_book.built", **{k: v for k, v in report.as_dict().items() if isinstance(v, (int, bool))})
    return report


# ── which matches ─────────────────────────────────────────────────────────────────────────────────────────────────

CHANGED_SQL = """
WITH changed AS (
    SELECT f.id FROM market.odds_asks a JOIN core.fixtures f ON f.provider_fixture_id = a.provider_fixture_id
     WHERE a.asked_at >= %(since)s
    UNION
    SELECT x.fixture_id FROM market.odds_extractions x
     WHERE x.fetched_at >= %(fetched_from)s AND x.extracted_at >= %(since)s AND x.fixture_id IS NOT NULL
    UNION
    SELECT b.fixture_id FROM market.book_current b JOIN core.fixtures f ON f.id = b.fixture_id
     WHERE b.builder_version <> %(version)s OR b.kickoff_at <> f.kickoff_at
)
SELECT f.id FROM core.fixtures f JOIN changed c ON c.id = f.id
 WHERE f.kickoff_at > %(keep_from)s
 ORDER BY f.kickoff_at, f.id
"""
"""The matches whose asks or extractions moved since ``since``, plus those whose rows an older builder wrote or whose kick-off
was moved. ``odds_asks_asked_at`` and ``odds_extractions_fetched_idx`` serve it."""

HELD_SQL = """
SELECT f.id FROM core.fixtures f
 WHERE f.kickoff_at > %(from)s AND (%(until)s::timestamptz IS NULL OR f.kickoff_at < %(until)s)
   AND (EXISTS (SELECT 1 FROM market.odds_asks a WHERE a.provider_fixture_id = f.provider_fixture_id
                   AND a.asked_at >= f.kickoff_at - %(lookback)s AND a.asked_at < f.kickoff_at)
        OR EXISTS (SELECT 1 FROM market.book_current b WHERE b.fixture_id = f.id))
 ORDER BY f.kickoff_at, f.id
"""
"""Every match the book should hold from ``from`` on: asked before its kick-off, or already in the book."""

LAST_PASS_SQL = """
SELECT max(started_at) FROM raw.ingestion_runs WHERE job_type = %(job)s AND status IN ('completed', 'partial')
"""


def changed_fixtures(conn: psycopg.Connection[Any], *, since: datetime, now: datetime) -> list[int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CHANGED_SQL, {"since": since, "fetched_from": now - LOOKBACK - PURGE_AFTER - timedelta(days=1),
                                  "version": BUILDER_VERSION, "keep_from": now - PURGE_AFTER})
        return [int(r[0]) for r in cur.fetchall()]


def held_fixtures(conn: psycopg.Connection[Any], *, kickoff_from: datetime, kickoff_until: datetime | None = None) -> list[int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(HELD_SQL, {"from": kickoff_from, "until": kickoff_until, "lookback": LOOKBACK})
        return [int(r[0]) for r in cur.fetchall()]


def last_pass(conn: psycopg.Connection[Any]) -> datetime | None:
    """When the job's last finished pass started (the job ledger, ``raw.ingestion_runs``)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LAST_PASS_SQL, {"job": JOB})
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def table_bytes(conn: psycopg.Connection[Any]) -> int:
    """The size of ``market.book_current`` with its TOAST and indexes."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_total_relation_size('market.book_current')")
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def book_enabled() -> bool:
    return settings.odds.book_enabled


def run_book_job(conn: psycopg.Connection[Any], raw_root: Path | str, *, enabled: bool | None = None,
                 now: datetime | None = None, limit: int = DEFAULT_PER_RUN,
                 max_seconds: float = DEFAULT_RUN_SECONDS) -> BookReport | None:
    """The worker's pass (``odds_book_build``), as a ledger run. Does NOTHING - not even a query - while ``FBI_ODDS_BOOK`` is
    off. On, it builds the matches whose asks or extractions changed since its last finished pass (``CHANGE_MARGIN`` behind it;
    the first pass: every match the book should hold) and deletes the rows of matches long started; a quiet pass writes no
    ledger row. A pass stopped by its budget or its ``limit`` is ``aborted``, so the next one starts from the same point.
    No request to the provider."""
    if not (book_enabled() if enabled is None else enabled):
        return None
    from fbi.ingestion.ledger import RunCounters, RunLedger

    moment = now or clock_now()
    previous = last_pass(conn)
    since = previous - CHANGE_MARGIN if previous is not None else moment - LOOKBACK - PURGE_AFTER
    queue = changed_fixtures(conn, since=since, now=moment)
    old_rows = purge(conn, now=moment, apply=False)
    conn.commit()
    if not queue and not old_rows:
        return None
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"limit": limit, "max_seconds": max_seconds, "builder": BUILDER_VERSION,
                                      "since": since.isoformat(), "fixtures": len(queue)})
    counters = RunCounters()
    report: BookReport | None = None
    notes: str | None = None
    try:
        report = build(conn, raw_root, queue[:limit], apply=True, now=moment, purge_old=True, max_seconds=max_seconds)
        counters.rows_inserted = report.rows_inserted
        counters.rows_updated = report.rows_updated + report.rows_deleted + report.rows_purged  # rows changed or removed
        counters.rows_normalized = report.fixtures_seen
        counters.errors.extend(report.errors[:5])
        left = report.fixtures_left + max(len(queue) - limit, 0)
        if report.skipped_locked:
            counters.stopped_early = "another build of the book is running"
        elif left:
            counters.stopped_early = f"{left} matches left for the next pass"
        notes = json.dumps(report.as_dict(), default=str)[:2000]
    finally:
        ledger.close(run_id, counters, notes=notes)
    return report
