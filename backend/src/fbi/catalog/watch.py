"""PM-03-08 (Plan Maestro PM, DOC-010): say when the provider lists a competition the owner asked for and it did not have.

Eleven competitions the owner asked for are not in API-Football's ``/leagues`` and four more are listed with no season for years;
five cyclical ones have no edition open (``config/catalogue_watch.yaml``, guide ``docs/owner/EXPANSION_P3.md`` section 8). The
daily ``catalogue_refresh`` already stores every league the provider lists in ``raw.league_coverage``; this module compares that
with the baseline of the file, BY IDENTIFIER (a renamed competition is not new):

* ``nueva`` - a league id of a priority country that the baseline did not have;
* ``edicion`` - a season newer than ``last_season`` for a competition of ``waiting``.

It never asks the provider anything and never writes: ``findings`` is a pure function, ``read_listed`` one read-only query. The
daily check runs only with ``FBI_CATALOGUE_WATCH`` on (OFF by default; ``fbi.ingestion.catalogue_refresh``);
``python -m scripts.catalogue_watch`` runs it by hand at any time. Tracking a new competition stays the usual procedure
(candidate and batch in ``config/expansion.yaml``, probe, ``scripts.expand_leagues``).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.rows import tuple_row

ROOT = Path(__file__).resolve().parents[3]
WATCH_FILE = ROOT / "config" / "catalogue_watch.yaml"
SWITCH = "FBI_CATALOGUE_WATCH"
"""OFF by default; 1/on/true/yes turns the daily check of ``catalogue_refresh`` on. Read when the refresh runs."""

LISTED_SQL = """
SELECT DISTINCT ON (provider_league_id) provider_league_id, league_name, country,
       max(season) OVER (PARTITION BY provider_league_id) AS newest_season
  FROM raw.league_coverage
 WHERE provider = 'api_football'
 ORDER BY provider_league_id, season DESC
"""


def watch_on() -> bool:
    return os.environ.get(SWITCH, "off").strip().lower() in {"1", "on", "true", "yes"}


@dataclass(frozen=True)
class Listed:
    """One league as the provider lists it: its newest season's name and country, and that season."""

    league_id: int
    name: str
    country: str
    newest_season: int


@dataclass(frozen=True)
class Waiting:
    league_id: int
    name: str
    country: str
    kind: str
    last_season: int


@dataclass(frozen=True)
class WatchConfig:
    known: Mapping[str, frozenset[int]]
    """Priority country (the provider's spelling) -> the league ids it had on the baseline date."""
    waiting: tuple[Waiting, ...]
    missing: tuple[Mapping[str, str], ...]
    baseline_at: str


@dataclass(frozen=True)
class Finding:
    kind: str
    """``nueva`` or ``edicion``."""
    league_id: int
    name: str
    country: str
    season: int
    detail: str

    def line(self) -> str:
        return f"{self.kind} {self.league_id} {self.name} ({self.country}) {self.season}: {self.detail}"


def load(path: Path = WATCH_FILE) -> WatchConfig:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {str(country): frozenset(int(x) for x in ids or ()) for country, ids in (raw.get("known") or {}).items()}
    waiting = tuple(Waiting(int(w["league_id"]), str(w["name"]), str(w["country"]), str(w["kind"]), int(w["last_season"]))
                    for w in raw.get("waiting") or ())
    missing = tuple({str(k): str(v) for k, v in m.items()} for m in raw.get("missing") or ())
    return WatchConfig(known=known, waiting=waiting, missing=missing, baseline_at=str((raw.get("baseline") or {}).get("at", "")))


def _norm(country: str) -> str:
    return " ".join(str(country or "").split()).casefold()


def findings(listed: Iterable[Listed], config: WatchConfig) -> list[Finding]:
    """What changed against the baseline, in league id order. A league of a priority country is new only if its ID was not
    listed then; a waiting competition has news only when a season newer than its last one is listed."""
    countries = {_norm(c): c for c in config.known}
    every_known = frozenset().union(*config.known.values()) if config.known else frozenset()
    waiting = {w.league_id: w for w in config.waiting}
    out: list[Finding] = []
    for row in sorted(listed, key=lambda r: r.league_id):
        country = countries.get(_norm(row.country))
        if country is not None and row.league_id not in every_known:
            out.append(Finding("nueva", row.league_id, row.name, row.country, row.newest_season,
                               f"{country} had {len(config.known[country])} leagues on {config.baseline_at or 'the baseline'};"
                               " this id is not one of them"))
        w = waiting.get(row.league_id)
        if w is not None and row.newest_season > w.last_season:
            out.append(Finding("edicion", row.league_id, row.name, row.country, row.newest_season,
                               f"{w.kind}: newest season was {w.last_season}"))
    return out


def read_listed(conn: psycopg.Connection[Any]) -> list[Listed]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LISTED_SQL)
        return [Listed(int(r[0]), str(r[1] or ""), str(r[2] or ""), int(r[3])) for r in cur.fetchall()]


def check(conn: psycopg.Connection[Any], config: WatchConfig | None = None) -> list[Finding]:
    return findings(read_listed(conn), config or load())


def notes(found: list[Finding], limit: int = 10) -> str:
    """The ledger's short form: how many, and the first ``limit``."""
    if not found:
        return "watch: nothing new"
    head = "; ".join(f.line() for f in found[:limit])
    more = f" (+{len(found) - limit} more)" if len(found) > limit else ""
    return f"watch: {len(found)} finding(s): {head}{more}"
