"""The provider's own catalogue of bets and bookmakers, kept as data.

API-Football offers 338 pre-match bet types and 266 in-play ones. We model five.
For a long time the other 599 were invisible: a bet that arrived in a payload
and was not in our id map was skipped without trace, so "we do not model this"
and "we lost this" looked identical from the outside.

``market.provider_markets`` fixes that. Every bet the provider is known to offer
gets a row, mapped to one of our markets or explicitly to none, with where we
learned it from:

``catalogue``  it was listed by /odds/bets or /odds/live/bets.
``observed``   it turned up inside a real payload. An ``observed`` bet that the
               catalogue never mentioned is a provider change, not our bug.

Pre-match and in-play bet ids are SEPARATE namespaces - pre-match 4 is Asian
Handicap, in-play 4 is "Extra Time Total Corners (3 Ways) (1st Half)" - so
``scope`` is part of the key and the two are never merged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.core.errors import ConfigError
from fbi.providers.api_football.normalize import BETS_BY_SOURCE

log = structlog.get_logger(__name__)

PROVIDER = "api-football"
PROVIDER_VERSION = "v3.9.3"

SCOPES: dict[str, str] = {"prematch": "bets_prematch.json", "inplay": "bets_inplay.json"}
"""Our scope name -> the catalogue file that lists it."""

ODDS_SOURCE_OF_SCOPE: dict[str, str] = {"prematch": "prematch", "inplay": "live"}
"""The schema calls the in-play namespace 'inplay'; OddsQuote.source calls the
same thing 'live'. One translation, in one place."""

BOOKMAKERS_FILE = "bookmakers.json"


@dataclass
class CatalogueReport:
    scope: str
    rows_in_file: int = 0
    inserted: int = 0
    refreshed: int = 0
    mapped: int = 0
    renamed: list[tuple[int, str, str]] = field(default_factory=list)
    """(bet_id, the name on record, the name the file now gives). A populated
    list means the provider renumbered or renamed: worth a quality event."""
    vanished: list[tuple[int, str]] = field(default_factory=list)
    """Bets we have on record that this catalogue no longer lists. Kept, never
    deleted: prices captured under them are still real."""

    def as_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "rows_in_file": self.rows_in_file, "inserted": self.inserted,
                "refreshed": self.refreshed, "mapped": self.mapped,
                "renamed": [list(r) for r in self.renamed], "vanished": [list(v) for v in self.vanished]}


def _entries(path: Path) -> list[tuple[int, str]]:
    if not path.is_file():
        raise ConfigError(f"{path}: catalogue file not found")
    raw = json.loads(path.read_text())
    body = raw.get("response") if isinstance(raw, dict) else raw
    if not isinstance(body, list):
        raise ConfigError(f"{path}: expected a list of bets, or an object with a 'response' list")
    out: list[tuple[int, str]] = []
    for item in body:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            continue
        name = item.get("name")
        out.append((int(item["id"]), str(name) if isinstance(name, str) and name.strip() else ""))
    if not out:
        raise ConfigError(f"{path}: no bets in the file")
    return out


def _mapping_for(scope: str) -> dict[int, str]:
    """bet id -> our market key, for this scope only."""
    source = ODDS_SOURCE_OF_SCOPE[scope]
    return {bet.bet_id: key for key, bet in BETS_BY_SOURCE[source].items()}


def load_bet_catalogue(
    conn: psycopg.Connection,
    *,
    directory: Path,
    scopes: Sequence[str] | None = None,
    provider: str = PROVIDER,
    provider_version: str = PROVIDER_VERSION,
) -> list[CatalogueReport]:
    """Upsert both bet catalogues. Idempotent; reports what changed.

    Nothing is ever deleted. A bet that disappears from the provider's list is
    reported as ``vanished`` and left in place, because any price we captured
    under it happened.
    """
    reports: list[CatalogueReport] = []
    for scope in scopes or list(SCOPES):
        report = CatalogueReport(scope=scope)
        entries = _entries(directory / SCOPES[scope])
        report.rows_in_file = len(entries)
        mapping = _mapping_for(scope)
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT provider_bet_id, name FROM market.provider_markets "
                        "WHERE provider = %s AND scope = %s", (provider, scope))
            on_record: dict[int, str] = dict(cur.fetchall())
            for bet_id, name in entries:
                previous = on_record.get(bet_id)
                if previous is not None and name and previous != name:
                    report.renamed.append((bet_id, previous, name))
                market_key = mapping.get(bet_id)
                if market_key is not None:
                    report.mapped += 1
                cur.execute(
                    "INSERT INTO market.provider_markets (provider, scope, provider_bet_id, name, "
                    " market_key, source, provider_version) VALUES (%s,%s,%s,%s,%s,'catalogue',%s) "
                    "ON CONFLICT (provider, scope, provider_bet_id) DO UPDATE SET "
                    "  name = EXCLUDED.name, market_key = EXCLUDED.market_key, "
                    "  source = 'catalogue', last_seen_at = now() "
                    "RETURNING (xmax = 0) AS was_insert",
                    (provider, scope, bet_id, name, market_key, provider_version),
                )
                row = cur.fetchone()
                if row is not None and row[0]:
                    report.inserted += 1
                else:
                    report.refreshed += 1
            listed = {bet_id for bet_id, _ in entries}
            report.vanished = sorted((b, n) for b, n in on_record.items() if b not in listed)
        if report.renamed or report.vanished:
            log.warning("provider_markets.catalogue_moved", scope=scope,
                        renamed=len(report.renamed), vanished=len(report.vanished))
        log.info("provider_markets.loaded", **report.as_dict())
        reports.append(report)
    return reports


def record_observed_bets(
    conn: psycopg.Connection,
    bets: Mapping[tuple[int, str], int],
    *,
    scope: str,
    provider: str = PROVIDER,
) -> list[tuple[int, str]]:
    """Register bets seen inside a real payload. Returns the ones that were new.

    Takes ``OddsParseLog.unmapped_bets`` directly. An existing ``catalogue`` row
    keeps that source and its mapping - an observation confirms a bet, it never
    unmaps one; ``last_seen_at`` moves either way, because that is the honest
    record of when the provider last offered it.
    """
    if scope not in SCOPES:
        raise ConfigError(f"unknown scope {scope!r}")
    new: list[tuple[int, str]] = []
    with conn.cursor(row_factory=tuple_row) as cur:
        for (bet_id, name), _count in sorted(bets.items()):
            cur.execute(
                "INSERT INTO market.provider_markets (provider, scope, provider_bet_id, name, "
                " market_key, source) VALUES (%s,%s,%s,%s,NULL,'observed') "
                "ON CONFLICT (provider, scope, provider_bet_id) DO UPDATE SET "
                "  last_seen_at = now(), "
                "  name = CASE WHEN market.provider_markets.name = '' THEN EXCLUDED.name "
                "              ELSE market.provider_markets.name END "
                "RETURNING (xmax = 0) AS was_insert",
                (provider, scope, bet_id, name),
            )
            row = cur.fetchone()
            if row is not None and row[0]:
                new.append((bet_id, name))
    if new:
        log.warning("provider_markets.observed_bet_not_in_catalogue", scope=scope,
                    bets=[f"{b}:{n}" for b, n in new])
    return new


def load_bookmakers(conn: psycopg.Connection, *, directory: Path) -> int:
    """Upsert the provider's bookmaker list. Names only.

    ``is_sharp``, ``consensus_weight`` and ``is_active`` are OUR judgements about
    a bookmaker, not the provider's, so they are never written here.
    """
    entries = _entries(directory / BOOKMAKERS_FILE)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s,%s) "
            "ON CONFLICT (provider_bookmaker_id) DO UPDATE SET name = EXCLUDED.name",
            entries,
        )
    log.info("provider_markets.bookmakers_loaded", count=len(entries))
    return len(entries)
