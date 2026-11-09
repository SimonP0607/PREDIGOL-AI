"""The price clock: structure the prices already sitting in RAW (plan F1).

Every ``/odds`` answer the capture ever stored is a gzipped file indexed by ``raw.ingestion_payloads``. The live pipeline reads
five of the bet types in it. This job reads the same files and writes the structured bets that
``market.market_definitions`` marks ``extract`` into ``market.odds_quotes``, with a ledger row per payload
(``market.odds_extractions``). It asks the provider nothing, writes nothing the pipeline reads, and can be run any number of
times: the ledger's unique ``payload_hash`` makes a second run a no-op, and a new ``EXTRACTOR_VERSION`` (a taxonomy or a
parser change) reads the payloads again and REPLACES what the older version wrote for them (derived rows only: the RAW file
is the evidence and is never touched).

Two instants, and the honest one is chosen:

* a payload fetched BEFORE kick-off stamps its quotes with the instant it was fetched (when we knew the price);
* a payload fetched AFTER kick-off (the provider keeps pre-match prices for 7 days and ``final_prematch`` reads them back)
  stamps them with the provider's own ``update`` stamp, and only if that is before kick-off. An answer with no usable stamp
  writes nothing: it could be an in-play price filed as a pre-match one, the failure the live pipeline was built to avoid.

``minutes_to_ko`` is measured against the kick-off the payload itself carried: the kick-off at the time of the capture, not the
one a later reschedule left in ``core.fixtures``.

What is NOT in the series, by construction: RAW stores identical bodies once, so a body that comes back after a different one
(A, B, A) has one row for A. ``market.odds_asks`` (since revision 0064) knows every ask and the payload that answered it, which
is how a reader recovers "what was in force at the third ask".

Nor what the explorer's book refreshes ask (plan Cuotas, BE-011): a payload indexed under a run of ``odds_book_refresh``
(``fbi.odds.book_refresh``) is never read here, so the series - and ``odds_snapshots``, ``market_consensus`` and
``quote_current``, which never see those asks either - hold exactly what the capture's windows brought. A body a refresh fetched
first and a capture fetched again is the capture's (``RunLedger.record_payloads`` gives it the row) and is read as always.
"""

from __future__ import annotations

import json
import math
import time
import zlib
from collections.abc import Mapping, Sequence
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
from fbi.odds.quote_parse import parse_odds, parse_selection
from fbi.odds.quote_taxonomy import (
    PROVIDER,
    SCOPE,
    TAXONOMY_VERSION,
    BetSpec,
    extracted_specs,
    known_bet_ids,
    same_name,
    sync_definitions,
)
from fbi.storage.payload_store import PayloadStore, body_hash

log = structlog.get_logger(__name__)

EXTRACTOR_VERSION = f"qx-1/{TAXONOMY_VERSION}"
"""Moves when the way a payload is read changes (this module, the parser or the taxonomy)."""

ENDPOINT = "/odds"
SKIPPED_JOB = "odds_book_refresh"
"""The ledger job whose payloads are never structured: the book refreshes (BE-011), for the explorer's book only."""
LOCK_KEY = "fbi.odds_quotes_extract"
RETRY_AFTER = timedelta(hours=2)
RETRY_WINDOW = timedelta(days=14)
"""A payload whose fixture we did not know, or that failed, is read again for two weeks, no more often than this."""
SMALLINT_MAX = 32000
SAMPLES_PER_BET = 5


@dataclass(frozen=True, slots=True)
class ParsedQuote:
    provider_bookmaker_id: int
    bookmaker_name: str
    provider_bet_id: int
    selection: str
    line: Decimal
    odds: Decimal


@dataclass
class ParsedEntry:
    """One ``response`` entry of a payload: one fixture's prices."""

    provider_fixture_id: int | None = None
    kickoff_at: datetime | None = None
    provider_update_at: datetime | None = None
    bookmakers: int = 0
    bets_seen: int = 0
    bets_extracted: int = 0
    refused: int = 0
    quotes: list[ParsedQuote] = field(default_factory=list)
    renamed: list[tuple[int, str, str]] = field(default_factory=list)
    unknown_bets: dict[int, str] = field(default_factory=dict)
    refused_by_bet: dict[int, int] = field(default_factory=dict)
    refused_samples: dict[int, list[str]] = field(default_factory=dict)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _instant(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            return _aware(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _refuse(entry: ParsedEntry, bet_id: int, value: Any) -> None:
    entry.refused += 1
    entry.refused_by_bet[bet_id] = entry.refused_by_bet.get(bet_id, 0) + 1
    samples = entry.refused_samples.setdefault(bet_id, [])
    if len(samples) < SAMPLES_PER_BET:
        text = repr(value)[:80]
        if text not in samples:
            samples.append(text)


def parse_body(body: Mapping[str, Any], definitions: Mapping[int, BetSpec],
               known_bets: frozenset[int]) -> list[ParsedEntry]:
    """Every extractable price of a ``/odds`` body. Pure: no database, no clock.

    ``definitions`` are the bets to extract (bet id -> spec); ``known_bets`` is every bet the registry has a row for, extracted
    or parked, so that a bet nobody has seen before is reported rather than ignored.
    """
    entries: list[ParsedEntry] = []
    response = body.get("response")
    for item in response if isinstance(response, list) else []:
        if not isinstance(item, dict):
            continue
        fixture = item.get("fixture")
        entry = ParsedEntry()
        if isinstance(fixture, dict):
            fixture_id = fixture.get("id")
            if isinstance(fixture_id, int) and not isinstance(fixture_id, bool):
                entry.provider_fixture_id = fixture_id
            entry.kickoff_at = _instant(fixture.get("timestamp")) or _instant(fixture.get("date"))
        entry.provider_update_at = _instant(item.get("update"))
        bookmakers = item.get("bookmakers")
        for book in bookmakers if isinstance(bookmakers, list) else []:
            if not isinstance(book, dict):
                continue
            book_id, book_name = book.get("id"), book.get("name")
            if not isinstance(book_id, int) or isinstance(book_id, bool) or not isinstance(book_name, str):
                continue
            entry.bookmakers += 1
            bets = book.get("bets")
            for bet in bets if isinstance(bets, list) else []:
                if not isinstance(bet, dict):
                    continue
                bet_id = bet.get("id")
                if not isinstance(bet_id, int) or isinstance(bet_id, bool):
                    continue
                raw_name = bet.get("name")
                bet_name = raw_name if isinstance(raw_name, str) else ""
                entry.bets_seen += 1
                spec = definitions.get(bet_id)
                if spec is None:
                    if bet_id not in known_bets:
                        entry.unknown_bets.setdefault(bet_id, bet_name)
                    continue
                raw_values = bet.get("values")
                values = raw_values if isinstance(raw_values, list) else []
                if bet_name and not same_name(bet_name, spec.name):
                    entry.renamed.append((bet_id, spec.name, bet_name))
                    entry.refused += len(values)
                    entry.refused_by_bet[bet_id] = entry.refused_by_bet.get(bet_id, 0) + len(values)
                    continue
                entry.bets_extracted += 1
                for value in values:
                    if not isinstance(value, dict):
                        _refuse(entry, bet_id, value)
                        continue
                    parsed = parse_selection(spec, value.get("value"))
                    odds = parse_odds(value.get("odd"))
                    if parsed is None or odds is None:
                        _refuse(entry, bet_id, (value.get("value"), value.get("odd")))
                        continue
                    entry.quotes.append(ParsedQuote(book_id, book_name, bet_id, parsed[0], parsed[1], odds))
        entries.append(entry)
    return entries


def minutes_to_ko(kickoff_at: datetime, captured_at: datetime) -> int:
    """Whole minutes before kick-off, floored at 0 (same rule as the live pipeline)."""
    return max(0, math.floor((kickoff_at - captured_at).total_seconds() / 60.0))


@dataclass(frozen=True, slots=True)
class Stamp:
    captured_at: datetime | None
    stamped_by: str  # fetch | provider_update | none


NO_STAMP = Stamp(None, "none")


def stamp_for(fetched_at: datetime, kickoff_at: datetime, provider_update_at: datetime | None) -> Stamp:
    """When the quotes of a payload are said to have been captured (see the module docstring)."""
    if fetched_at < kickoff_at:
        return Stamp(fetched_at, "fetch")
    if provider_update_at is not None and provider_update_at < kickoff_at:
        return Stamp(provider_update_at, "provider_update")
    return NO_STAMP


@dataclass(frozen=True, slots=True)
class Verdict:
    """What can be done with one entry of a payload: ``ok`` writes its quotes; the others write none and say why."""

    status: str  # ok | empty | no_fixture | after_kickoff | error
    detail: str | None = None
    provider_fixture_id: int | None = None
    fixture_id: int | None = None
    kickoff_at: datetime | None = None
    stamp: Stamp = NO_STAMP


def judge(entry: ParsedEntry, params_fixture: int | None, fetched_at: datetime,
          fixtures: Mapping[int, tuple[int, datetime | None]]) -> Verdict:
    """Pure: the fixture, the kick-off and the stamp of an entry, or the reason it cannot be filed."""
    provider_fixture_id = entry.provider_fixture_id or params_fixture
    if provider_fixture_id is None:
        return Verdict("error", "the answer does not name its fixture")
    fixture = fixtures.get(provider_fixture_id)
    if fixture is None:
        return Verdict("no_fixture", f"fixture {provider_fixture_id} is not in core.fixtures", provider_fixture_id)
    fixture_id, fixture_kickoff = fixture
    kickoff = entry.kickoff_at or (_aware(fixture_kickoff) if fixture_kickoff else None)
    if kickoff is None:
        return Verdict("error", "no kick-off in the payload or in core.fixtures", provider_fixture_id, fixture_id)
    stamp = stamp_for(fetched_at, kickoff, entry.provider_update_at)
    if stamp.captured_at is None:
        return Verdict("after_kickoff", "fetched after kick-off and the provider's update stamp is not before it",
                       provider_fixture_id, fixture_id, kickoff, stamp)
    return Verdict("ok", None, provider_fixture_id, fixture_id, kickoff, stamp)


@dataclass
class ExtractionReport:
    payloads_seen: int = 0
    payloads_ok: int = 0
    payloads_empty: int = 0
    payloads_no_fixture: int = 0
    payloads_after_kickoff: int = 0
    payloads_failed: int = 0
    payloads_missing_file: int = 0
    quotes_written: int = 0
    quotes_offered: int = 0
    quotes_refused: int = 0
    quotes_replaced: int = 0
    renamed_bets: dict[int, str] = field(default_factory=dict)
    unknown_bets: dict[int, str] = field(default_factory=dict)
    refused_by_bet: dict[int, int] = field(default_factory=dict)
    refused_samples: dict[int, list[str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    skipped_locked: bool = False
    stopped_for_time: bool = False
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "payloads_seen": self.payloads_seen, "payloads_ok": self.payloads_ok,
            "payloads_empty": self.payloads_empty, "payloads_no_fixture": self.payloads_no_fixture,
            "payloads_after_kickoff": self.payloads_after_kickoff, "payloads_failed": self.payloads_failed,
            "payloads_missing_file": self.payloads_missing_file, "quotes_written": self.quotes_written,
            "quotes_offered": self.quotes_offered, "quotes_refused": self.quotes_refused,
            "quotes_replaced": self.quotes_replaced,
            "renamed_bets": self.renamed_bets, "unknown_bets": self.unknown_bets,
            "refused_by_bet": dict(sorted(self.refused_by_bet.items(), key=lambda kv: -kv[1])[:20]),
            "refused_samples": dict(list(self.refused_samples.items())[:20]),
            "problems": self.problems[:20], "skipped_locked": self.skipped_locked,
            "stopped_for_time": self.stopped_for_time, "dry_run": self.dry_run,
        }

    def note(self, entry: ParsedEntry) -> None:
        """Fold what an entry taught: bets nobody classified, bets that changed name, values nobody could read."""
        for bet_id, name in entry.unknown_bets.items():
            self.unknown_bets.setdefault(bet_id, name)
        for bet_id, _expected, got in entry.renamed:
            self.renamed_bets.setdefault(bet_id, got)
        self.quotes_offered += len(entry.quotes)
        self.quotes_refused += entry.refused
        for bet_id, count in entry.refused_by_bet.items():
            self.refused_by_bet[bet_id] = self.refused_by_bet.get(bet_id, 0) + count
        for bet_id, samples in entry.refused_samples.items():
            kept = self.refused_samples.setdefault(bet_id, [])
            for sample in samples:
                if len(kept) < SAMPLES_PER_BET and sample not in kept:
                    kept.append(sample)

    def merge(self, other: ExtractionReport) -> None:
        """Add what one payload did. A payload that failed midway is never merged: its counters die with its savepoint."""
        for name in ("payloads_ok", "payloads_empty", "payloads_no_fixture", "payloads_after_kickoff", "payloads_failed",
                     "quotes_written", "quotes_offered", "quotes_refused", "quotes_replaced"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for bet_id, name in other.unknown_bets.items():
            self.unknown_bets.setdefault(bet_id, name)
        for bet_id, name in other.renamed_bets.items():
            self.renamed_bets.setdefault(bet_id, name)
        for bet_id, refused in other.refused_by_bet.items():
            self.refused_by_bet[bet_id] = self.refused_by_bet.get(bet_id, 0) + refused
        for bet_id, samples in other.refused_samples.items():
            kept = self.refused_samples.setdefault(bet_id, [])
            for sample in samples:
                if len(kept) < SAMPLES_PER_BET and sample not in kept:
                    kept.append(sample)

    def count(self, status: str) -> None:
        if status == "ok":
            self.payloads_ok += 1
        elif status == "empty":
            self.payloads_empty += 1
        elif status == "no_fixture":
            self.payloads_no_fixture += 1
        elif status == "after_kickoff":
            self.payloads_after_kickoff += 1
        else:
            self.payloads_failed += 1


@dataclass(frozen=True, slots=True)
class Registry:
    """The registry as the database holds it: what to extract, and every bet it has a row for."""

    extract: dict[int, tuple[int, BetSpec]]
    known: frozenset[int]

    @property
    def specs(self) -> dict[int, BetSpec]:
        return {bet_id: spec for bet_id, (_, spec) in self.extract.items()}


def registry_from_taxonomy() -> Registry:
    """The registry as the taxonomy module states it (definition ids are 0): for a dry run on a database that has not got
    ``market.market_definitions`` yet. Nothing is written with these ids."""
    return Registry(extract={spec.bet_id: (0, spec) for spec in extracted_specs()}, known=known_bet_ids())


def load_registry(conn: psycopg.Connection) -> Registry:
    """``market.market_definitions`` (prematch), as BetSpecs. The database is the authority: a definition switched on or
    off by the owner is honoured until the taxonomy version moves."""
    extract: dict[int, tuple[int, BetSpec]] = {}
    known: set[int] = set()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM market.market_definitions WHERE provider = %s AND scope = %s",
                    (PROVIDER, SCOPE))
        for row in cur.fetchall():
            bet_id = int(row["provider_bet_id"])
            known.add(bet_id)
            if not row["extract"]:
                continue
            spec = BetSpec(bet_id=bet_id, name=str(row["name"]), family=str(row["family"]),
                           period=str(row["period"]), subject=str(row["subject"]), kind=str(row["kind"]),
                           schema=str(row["schema"]), has_line=bool(row["has_line"]),
                           line_is_signed=bool(row["line_is_signed"]),
                           away_line_negated=bool(row["away_line_negated"]), status=str(row["status"]),
                           extract=True, market_key=row["market_key"])
            extract[bet_id] = (int(row["id"]), spec)
    return Registry(extract=extract, known=frozenset(known))


_NOT_REFRESHED = ("NOT EXISTS (SELECT 1 FROM raw.ingestion_runs r WHERE r.id = p.run_id AND r.job_type = %(skipped)s)")
"""A payload a book refresh indexed is not the extractor's (BE-011); the runs' primary key answers it."""

_PENDING_FROM = (
    "FROM raw.ingestion_payloads p LEFT JOIN market.odds_extractions x ON x.payload_hash = p.hash "
    "WHERE p.endpoint = %(endpoint)s AND p.http_status = 200 AND p.results_count > 0 "
    "  AND (%(since)s::timestamptz IS NULL OR p.fetched_at >= %(since)s) "
    "  AND (%(until)s::timestamptz IS NULL OR p.fetched_at < %(until)s) "
    "  AND " + _NOT_REFRESHED + " "
)


def pending_payloads(conn: psycopg.Connection, *, limit: int, since: datetime | None = None,
                     until: datetime | None = None, version: str = EXTRACTOR_VERSION,
                     now: datetime | None = None) -> list[dict[str, Any]]:
    """RAW ``/odds`` payloads still to read: never read first (oldest first), then those read by an older extractor and
    those read and not finished (fixture unknown, error) within the retry window - both no more often than ``RETRY_AFTER``.
    A payload that keeps failing therefore never starves the ones nobody has read."""
    moment = now or clock_now()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT p.hash, p.params, p.fetched_at, p.file_path, p.results_count " + _PENDING_FROM +
            "  AND (x.id IS NULL "
            "       OR (x.extractor_version <> %(version)s AND x.extracted_at < %(retry_before)s) "
            "       OR (x.status IN ('no_fixture', 'error') AND x.extracted_at < %(retry_before)s "
            "           AND p.fetched_at > %(window_start)s)) "
            "ORDER BY (x.id IS NOT NULL), p.fetched_at, p.hash LIMIT %(limit)s",
            {"endpoint": ENDPOINT, "since": since, "until": until, "version": version,
             "retry_before": moment - RETRY_AFTER, "window_start": moment - RETRY_WINDOW, "limit": limit,
             "skipped": SKIPPED_JOB},
        )
        return [dict(r) for r in cur.fetchall()]


def backlog(conn: psycopg.Connection, *, version: str = EXTRACTOR_VERSION) -> int:
    """How many readable ``/odds`` payloads the current extractor has not finished: the number the coverage view shows."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT count(*) " + _PENDING_FROM +
            "  AND (x.id IS NULL OR x.extractor_version <> %(version)s OR x.status IN ('no_fixture', 'error'))",
            {"endpoint": ENDPOINT, "since": None, "until": None, "version": version, "skipped": SKIPPED_JOB},
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _ensure_bookmakers(conn: psycopg.Connection, quotes: Sequence[ParsedQuote]) -> dict[int, int]:
    """provider bookmaker id -> ours. A bookmaker we never saw is added; an existing one is NEVER renamed by a replay of an old
    payload (the live pipeline owns the names)."""
    seen = {q.provider_bookmaker_id: q.bookmaker_name for q in quotes}
    if not seen:
        return {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.executemany(
            "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) "
            "ON CONFLICT (provider_bookmaker_id) DO NOTHING", list(seen.items()))
        cur.execute("SELECT provider_bookmaker_id, id FROM market.bookmakers WHERE provider_bookmaker_id = ANY(%s)",
                    (list(seen),))
        return {int(a): int(b) for a, b in cur.fetchall()}


def _fixtures(conn: psycopg.Connection, provider_ids: Sequence[int]) -> dict[int, tuple[int, datetime | None]]:
    if not provider_ids:
        return {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT provider_fixture_id, id, kickoff_at FROM core.fixtures "
                    "WHERE provider_fixture_id = ANY(%s)", (list(provider_ids),))
        return {int(a): (int(b), c) for a, b, c in cur.fetchall()}


def _ledger(conn: psycopg.Connection, *, payload_hash: str, fetched_at: datetime, page: int | None,
            provider_fixture_id: int | None, at: datetime, entry: ParsedEntry | None = None,
            verdict: Verdict | None = None, status: str | None = None, detail: str | None = None) -> int:
    """The ledger row of a payload, inserted or (when a newer extractor reads it again) rewritten. Returns its id; the quote
    count starts at 0 and is set once the quotes are in."""
    entry = entry or ParsedEntry()
    verdict = verdict or Verdict("error")
    stamp = verdict.stamp
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fixture_id, "
            " page, fetched_at, provider_update_at, kickoff_at, captured_at, stamped_by, bookmakers, bets_seen, "
            " bets_extracted, quotes_written, quotes_refused, status, detail, extracted_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s) "
            "ON CONFLICT (payload_hash) DO UPDATE SET "
            " extractor_version = EXCLUDED.extractor_version, provider_fixture_id = EXCLUDED.provider_fixture_id, "
            " fixture_id = EXCLUDED.fixture_id, page = EXCLUDED.page, provider_update_at = EXCLUDED.provider_update_at, "
            " kickoff_at = EXCLUDED.kickoff_at, captured_at = EXCLUDED.captured_at, stamped_by = EXCLUDED.stamped_by, "
            " bookmakers = EXCLUDED.bookmakers, bets_seen = EXCLUDED.bets_seen, bets_extracted = EXCLUDED.bets_extracted, "
            " quotes_written = 0, quotes_refused = EXCLUDED.quotes_refused, status = EXCLUDED.status, "
            " detail = EXCLUDED.detail, extracted_at = EXCLUDED.extracted_at "
            "RETURNING id",
            (payload_hash, EXTRACTOR_VERSION, provider_fixture_id or verdict.provider_fixture_id or 0,
             verdict.fixture_id, page, fetched_at, entry.provider_update_at, verdict.kickoff_at,
             stamp.captured_at, stamp.stamped_by, min(entry.bookmakers, SMALLINT_MAX),
             min(entry.bets_seen, SMALLINT_MAX), min(entry.bets_extracted, SMALLINT_MAX), entry.refused,
             status or verdict.status, detail if detail is not None else verdict.detail, at),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _forget_previous(conn: psycopg.Connection, payload_hash: str) -> int:
    """A payload read again by a newer extractor REPLACES what the older one wrote for it: the quotes of its previous 'ok'
    reading go (they are derived rows, and the RAW file that produced them is untouched). Without this a corrected reading
    would sit beside the wrong one."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM market.odds_quotes q USING market.odds_extractions x "
            "WHERE x.payload_hash = %s AND x.status = 'ok' AND x.captured_at IS NOT NULL AND x.fixture_id IS NOT NULL "
            "  AND q.extraction_id = x.id AND q.fixture_id = x.fixture_id AND q.captured_at = x.captured_at",
            (payload_hash,))
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def _insert_quotes(conn: psycopg.Connection, *, fixture_id: int, captured_at: datetime, minutes: int,
                   extraction_id: int, rows: Sequence[tuple[int, int, str, Decimal, Decimal]]) -> int:
    """rows: (bookmaker_id, definition_id, selection, line, odds). Returns how many were new."""
    if not rows:
        return 0
    cols = list(zip(*rows, strict=True))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO market.odds_quotes (fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, "
            " captured_at, minutes_to_ko, extraction_id) "
            "SELECT %s, t.b, t.d, t.s, t.l, t.o, %s, %s, %s "
            "FROM unnest(%s::int[], %s::int[], %s::text[], %s::numeric[], %s::numeric[]) AS t(b, d, s, l, o) "
            "ON CONFLICT DO NOTHING",
            (fixture_id, captured_at, minutes, extraction_id, list(cols[0]), list(cols[1]), list(cols[2]),
             list(cols[3]), list(cols[4])),
        )
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def _param_int(params: Any, key: str) -> int | None:
    if isinstance(params, dict):
        try:
            return int(params[key])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _detail_for(entry: ParsedEntry) -> str | None:
    """What a reader of the ledger needs to see at a glance: renamed bets refused, the bets whose values nobody could read."""
    parts: list[str] = []
    if entry.renamed:
        parts.append("renamed bets refused: " + ", ".join(f"{b} ({e!r} -> {g!r})" for b, e, g in entry.renamed[:5]))
    worst = sorted(entry.refused_by_bet.items(), key=lambda kv: -kv[1])[:5]
    if worst:
        parts.append("values refused by bet: " + ", ".join(f"{b} x{n}" for b, n in worst))
    return "; ".join(parts) or None


def extract_one(conn: psycopg.Connection, row: Mapping[str, Any], body: Mapping[str, Any], registry: Registry,
                report: ExtractionReport, *, at: datetime | None = None, dry_run: bool = False) -> None:
    """Read one payload and write its prices and its ledger row. The caller commits.

    A body names one fixture. If one ever names several, the first is the ledger's subject and every entry's prices are
    still written under their own fixture.
    """
    payload_hash = str(row["hash"])
    fetched_at = _aware(row["fetched_at"])
    params_fixture = _param_int(row.get("params"), "fixture")
    page = _param_int(row.get("params"), "page")

    entries = parse_body(body, registry.specs, registry.known)
    for entry in entries:
        report.note(entry)
    if len(entries) > 1:
        log.warning("odds_quotes.payload_names_several_fixtures", payload=payload_hash[:12], entries=len(entries))

    if not entries:
        verdicts = [(ParsedEntry(provider_fixture_id=params_fixture),
                     Verdict("empty", "the answer has no response entries", params_fixture))]
    else:
        ids = [i for i in {e.provider_fixture_id or params_fixture for e in entries} if i is not None]
        known = _fixtures(conn, ids)
        verdicts = [(e, judge(e, params_fixture, fetched_at, known)) for e in entries]

    lead_entry, lead = verdicts[0]
    report.count(lead.status)
    extraction_id = 0
    if not dry_run:
        report.quotes_replaced += _forget_previous(conn, payload_hash)
        extraction_id = _ledger(conn, payload_hash=payload_hash, fetched_at=fetched_at, page=page,
                                provider_fixture_id=params_fixture, at=at or clock_now(), entry=lead_entry, verdict=lead,
                                detail=_detail_for(lead_entry) if lead.status == "ok" else lead.detail)

    written = 0
    for entry, verdict in verdicts:
        if verdict.status != "ok" or verdict.stamp.captured_at is None or verdict.fixture_id is None \
                or verdict.kickoff_at is None:
            continue
        if dry_run:
            written += len(entry.quotes)
            continue
        bookmakers = _ensure_bookmakers(conn, entry.quotes)
        specs = registry.extract
        rows = [(bookmakers[q.provider_bookmaker_id], specs[q.provider_bet_id][0], q.selection, q.line, q.odds)
                for q in entry.quotes if q.provider_bookmaker_id in bookmakers and q.provider_bet_id in specs]
        written += _insert_quotes(
            conn, fixture_id=verdict.fixture_id, captured_at=verdict.stamp.captured_at,
            minutes=minutes_to_ko(verdict.kickoff_at, verdict.stamp.captured_at), extraction_id=extraction_id,
            rows=rows)
    if written and not dry_run:
        with conn.cursor() as cur:
            cur.execute("UPDATE market.odds_extractions SET quotes_written = %s WHERE id = %s",
                        (written, extraction_id))
    report.quotes_written += written


def record_failure(conn: psycopg.Connection, row: Mapping[str, Any], reason: str, *, at: datetime | None = None) -> None:
    """A payload that could not be read or filed gets a ledger row saying so, so that it is retried on the ledger's cadence
    (not on every run, ahead of payloads nobody has read) and shows up in the coverage view. A payload an older extractor
    read well keeps its good reading: only the note and the retry clock move."""
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, page, "
                " fetched_at, stamped_by, status, detail, extracted_at) "
                "VALUES (%s, %s, %s, %s, %s, 'none', 'error', %s, %s) "
                "ON CONFLICT (payload_hash) DO UPDATE SET detail = EXCLUDED.detail, extracted_at = EXCLUDED.extracted_at, "
                " extractor_version = CASE WHEN market.odds_extractions.status = 'ok' "
                "                          THEN market.odds_extractions.extractor_version "
                "                          ELSE EXCLUDED.extractor_version END, "
                " status = CASE WHEN market.odds_extractions.status = 'ok' THEN 'ok' ELSE 'error' END",
                (str(row["hash"]), EXTRACTOR_VERSION, _param_int(row.get("params"), "fixture") or 0,
                 _param_int(row.get("params"), "page"), _aware(row["fetched_at"]), reason[:500], at or clock_now()))
    except psycopg.Error as exc:  # the failure of the failure: logged, never raised
        log.error("odds_quotes.ledger_failed", payload=str(row["hash"])[:12], error=str(exc)[:200])


def load_body(store: PayloadStore, row: Mapping[str, Any], *, verify: bool) -> tuple[dict[str, Any] | None, str | None, bool]:
    """(body, problem, file_is_missing) of one indexed payload."""
    file_path = str(row["file_path"])
    try:
        envelope = store.load(file_path)
    except FileNotFoundError:
        return None, f"{file_path}: indexed but not in the RAW store", True
    except (OSError, ValueError, EOFError, zlib.error) as exc:
        return None, f"{file_path}: unreadable ({type(exc).__name__})", False
    body = envelope.get("body")
    if not isinstance(body, dict):
        return None, f"{file_path}: the stored body is not an object", False
    if verify and body_hash(body) != row["hash"]:
        return None, f"{file_path}: does not re-hash to {str(row['hash'])[:12]}", False
    return body, None, False


def run_extraction(conn: psycopg.Connection, raw_root: Path | str, *, limit: int = 200, batch: int = 25,
                   since: datetime | None = None, until: datetime | None = None, max_seconds: float | None = None,
                   verify_hashes: bool = True, now: datetime | None = None, commit: bool = True) -> ExtractionReport:
    """Structure up to ``limit`` pending payloads. Safe to call from two places at once: only one runs, the other reports
    ``skipped_locked`` and does nothing. Commits every ``batch`` payloads, so a stop loses at most one batch of work and never
    leaves a payload half read. ``commit=False`` leaves the transaction to the caller (a test that rolls back)."""
    report = ExtractionReport()
    started = time.monotonic()
    moment = now or clock_now()

    def settle() -> None:
        if commit:
            conn.commit()

    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        locked = cur.fetchone()
    if not locked or not locked[0]:
        report.skipped_locked = True
        settle()
        return report
    try:
        sync_definitions(conn)
        settle()
        registry = load_registry(conn)
        rows = pending_payloads(conn, limit=limit, since=since, until=until, now=moment)
        settle()
        store = PayloadStore(raw_root)
        in_batch = 0
        for row in rows:
            report.payloads_seen += 1
            body, problem, missing = load_body(store, row, verify=verify_hashes)
            if body is None:
                if missing:
                    report.payloads_missing_file += 1
                else:
                    report.payloads_failed += 1
                report.problems.append(problem or "unreadable")
                record_failure(conn, row, problem or "unreadable", at=moment)
            else:
                one = ExtractionReport()
                try:
                    with conn.transaction():
                        extract_one(conn, row, body, registry, one, at=moment)
                    report.merge(one)
                except psycopg.Error as exc:
                    if conn.closed:  # the connection is gone: stop, do not fail every payload that is left
                        raise
                    report.payloads_failed += 1
                    reason = f"{type(exc).__name__}: {str(exc)[:300]}"
                    report.problems.append(f"{str(row['hash'])[:12]}: {reason}")
                    log.warning("odds_quotes.payload_failed", payload=str(row["hash"])[:12], error=reason[:200])
                    record_failure(conn, row, reason, at=moment)
            in_batch += 1
            if in_batch >= batch:
                settle()
                in_batch = 0
            if max_seconds is not None and time.monotonic() - started > max_seconds:
                report.stopped_for_time = True
                break
        settle()
        if report.unknown_bets:
            sync_definitions(conn, observed=sorted(report.unknown_bets.items()))
            settle()
            log.warning("odds_quotes.unknown_bets", bets=sorted(report.unknown_bets.items())[:20])
        if report.renamed_bets:
            log.warning("odds_quotes.renamed_bets", bets=sorted(report.renamed_bets.items())[:20])
    finally:
        try:
            if conn.info.transaction_status == TransactionStatus.INERROR:
                conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
            settle()
        except psycopg.Error as exc:
            log.error("odds_quotes.unlock_failed", error=str(exc)[:200])
    log.info("odds_quotes.extracted", **{k: v for k, v in report.as_dict().items() if isinstance(v, (int, bool))})
    return report


JOB = "odds_quotes_extract"
DEFAULT_MIN_FREE_GB = 8.0
DEFAULT_MAX_TABLE_GB = 25.0


def table_bytes(conn: psycopg.Connection) -> int:
    """The size of ``market.odds_quotes`` with its partitions and indexes."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT coalesce(sum(pg_total_relation_size(relid)), 0) FROM pg_partition_tree('market.odds_quotes') "
                    "WHERE isleaf")
        row = cur.fetchone()
    return int(row[0]) if row else 0


def run_extraction_job(conn: psycopg.Connection, raw_root: Path | str, *, limit: int = 300, max_seconds: float = 240.0,
                       min_free_gb: float = DEFAULT_MIN_FREE_GB, max_table_gb: float = DEFAULT_MAX_TABLE_GB,
                       since: datetime | None = None, until: datetime | None = None) -> ExtractionReport | None:
    """The scheduled job: one bounded pass over the payloads nobody has structured yet, as a ledger run.

    It does nothing - and writes no ledger row - when nothing is pending, so a quiet day leaves no noise. It refuses to
    start (and says so in its ledger run) when the disk is nearly full or the price clock's table has outgrown its budget:
    structuring is a cost, the RAW payloads lose nothing by waiting.
    """
    import shutil

    from fbi.ingestion.ledger import RunCounters, RunLedger

    if not pending_payloads(conn, limit=1, since=since, until=until):
        conn.commit()
        return None
    conn.commit()
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"limit": limit, "max_seconds": max_seconds, "extractor": EXTRACTOR_VERSION})
    counters = RunCounters()
    report: ExtractionReport | None = None
    notes: str | None = None
    try:
        free_gb = shutil.disk_usage(raw_root).free / 1e9
        used_gb = table_bytes(conn) / 1e9
        conn.commit()
        if free_gb < min_free_gb:
            counters.stopped_early = f"the disk has {free_gb:.1f} GB free (< {min_free_gb:g} GB): not extracting"
        elif used_gb > max_table_gb:
            counters.stopped_early = f"market.odds_quotes is {used_gb:.1f} GB (> {max_table_gb:g} GB budget): not extracting"
        else:
            report = run_extraction(conn, raw_root, limit=limit, max_seconds=max_seconds, since=since, until=until)
            counters.rows_inserted = report.quotes_written
            counters.rows_normalized = report.quotes_offered
            counters.payloads_stored = 0
            counters.errors.extend(report.problems[:5])
            if report.skipped_locked:
                counters.stopped_early = "another extraction is running"
            elif report.stopped_for_time:
                counters.stopped_early = f"time budget of {max_seconds:g} s reached"
            notes = json.dumps({k: v for k, v in report.as_dict().items() if k != "problems"}, default=str)[:2000]
    finally:
        ledger.close(run_id, counters, notes=notes)
    return report


def sample_extraction(conn: psycopg.Connection, raw_root: Path | str, *, sample: int = 200,
                      since: datetime | None = None, until: datetime | None = None,
                      verify_hashes: bool = False) -> ExtractionReport:
    """A DRY RUN on real data: read up to ``sample`` indexed ``/odds`` payloads (newest first) with the taxonomy as the
    registry and report what would be structured and what would be refused - without writing anything and without needing
    the price clock's tables. The first look at a database that has not been migrated yet."""
    report = ExtractionReport(dry_run=True)
    registry = registry_from_taxonomy()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT p.hash, p.params, p.fetched_at, p.file_path, p.results_count FROM raw.ingestion_payloads p "
            "WHERE p.endpoint = %(endpoint)s AND p.http_status = 200 AND p.results_count > 0 "
            "  AND (%(since)s::timestamptz IS NULL OR p.fetched_at >= %(since)s) "
            "  AND (%(until)s::timestamptz IS NULL OR p.fetched_at < %(until)s) AND " + _NOT_REFRESHED + " "
            "ORDER BY p.fetched_at DESC, p.hash LIMIT %(limit)s",
            {"endpoint": ENDPOINT, "since": since, "until": until, "limit": sample, "skipped": SKIPPED_JOB})
        rows = [dict(r) for r in cur.fetchall()]
    store = PayloadStore(raw_root)
    for row in rows:
        report.payloads_seen += 1
        body, problem, missing = load_body(store, row, verify=verify_hashes)
        if body is None:
            if missing:
                report.payloads_missing_file += 1
            else:
                report.payloads_failed += 1
            report.problems.append(problem or "unreadable")
            continue
        extract_one(conn, row, body, registry, report, dry_run=True)
    return report
