"""What Intelligence reads of the statistics documents (plan RP-6.1, finding H32): ``stats-reading-v1``.

The team, player and league documents the nightly pass writes (``analytics.stat_documents``, ``fbi.stats.job``, plan EA) are the figures the
statistics pages draw (C-13). 91,864 of them sat unread by Intelligence, whose texts and decisions kept averaging the same matches again
with another window and another rounding. This module is the ONE way Intelligence reads them: the figure exactly as the document holds it,
with its sample, the calculation version, the document's identifier and the date it was computed. It computes nothing:

* ``read`` answers the document IN FORCE at a cut-off (``as_of``): the row is replaced by every nightly pass, so a document computed after
  the cut-off is not read (``after_cutoff``) - the reading never leaks a figure from the future into a text or a decision about a past moment;
* a figure the document does not publish (``sin_datos``, ``sin_cobertura``) is NOT a value: it comes back with its ``missing_reason`` and
  ``value`` None, never as a zero and never filled in;
* ``document_id`` names the document (kind, entity, competition season, scope, context, calculation version) so a fact built on it can cite it
  and a check can find it again; ``computed_at`` is its ``known_at``.

``tests/unit/test_stats_reading_architecture.py`` forbids the packages of Intelligence to import the modules that CALCULATE these figures
(``fbi.stats.team``, ``player``, ``data``, ``extras``, ``job``, ``expected_table``); ``tests/integration/test_stats_reading_db.py`` holds every
reading equal to the answer of C-13 for the same entity. It writes nothing and decides nothing: it is a read of stored data, one indexed SELECT."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "stats-reading-v1"
KINDS: Final[tuple[str, ...]] = ("team", "player")
Status = Literal["ok", "no_document", "after_cutoff"]

DOC_SQL: Final = """
SELECT kind, entity_id, competition_season_id, scope, context, calc_version, sample, doc, computed_at
  FROM analytics.stat_documents
 WHERE kind = %(kind)s AND entity_id = %(entity)s AND competition_season_id = %(cs)s AND scope = %(scope)s AND context = %(context)s
"""
"""The primary key of the table: one row, one document."""


def document_id(kind: str, entity_id: int, competition_season_id: int, scope: str, context: str, calc_version: str) -> str:
    """The identifier of a document, citable and stable: ``stat:team:42:7:u10:all:stats-docs-v1``."""
    return f"stat:{kind}:{entity_id}:{competition_season_id}:{scope}:{context}:{calc_version}"


@dataclass(frozen=True, slots=True)
class Reading:
    """One figure of a document, as the document holds it."""

    key: str
    unit: str | None
    better: str | None
    value: float | None
    missing_reason: str | None
    matches_with_data: int
    percentile: int | None
    league_value: float | None


@dataclass(frozen=True, slots=True)
class TrendReading:
    """One trend row of a team document (EA-006), as the document holds it: how often the team's matches settled a selection, with the league's
    reference. ``league_pct`` is None when the document has no reference for it (``missing_reason`` says why)."""

    key: str
    family: str
    rule_key: str | None
    line: float | None
    hits: int
    n: int
    pct: int
    wilson_low: int
    wilson_high: int
    league_pct: int | None
    league_missing_reason: str | None


@dataclass(frozen=True, slots=True)
class Document:
    """A statistics document read for Intelligence: its identity, its calculation, its date and its figures."""

    status: Status
    kind: str
    entity_id: int
    competition_season_id: int
    scope: str
    context: str
    calc_version: str | None = None
    document_id: str | None = None
    sample: int = 0
    computed_at: datetime | None = None
    readings: tuple[Reading, ...] = ()
    trends: tuple[TrendReading, ...] = ()
    body: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)
    """The document's body as stored, for the cuts that read a block the figures do not carry (halves, a player's starts)."""

    def get(self, key: str) -> Reading | None:
        return next((r for r in self.readings if r.key == key), None)

    def value(self, key: str) -> float | None:
        r = self.get(key)
        return None if r is None else r.value

    def citation(self, key: str) -> dict[str, Any] | None:
        """What a fact built on a figure cites: the key, the document and its date (the fact's ``known_at``), the calculation and the sample."""
        r = self.get(key)
        if r is None or r.value is None:
            return None
        return {"source": "C-13", "key": r.key, "document_id": self.document_id, "calc_version": self.calc_version,
                "known_at": None if self.computed_at is None else self.computed_at.isoformat(),
                "matches_with_data": r.matches_with_data, "value": r.value}


def _number(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None  # a ``Missing`` is a dict, not a value
    return float(x)


def _int(x: Any) -> int | None:
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _missing_reason(x: Any) -> str | None:
    return str(x["missing_reason"]) if isinstance(x, Mapping) and "missing_reason" in x else None


def readings_of(doc: Mapping[str, Any], keys: Iterable[str] | None = None) -> tuple[Reading, ...]:
    """The figures of a document body (``figures`` of a team's or a player's), in the document's own order. Pure."""
    wanted = None if keys is None else frozenset(keys)
    out: list[Reading] = []
    figures = doc.get("figures")
    if not isinstance(figures, list):
        return ()
    for f in figures:
        if not isinstance(f, Mapping) or not isinstance(f.get("key"), str):
            continue
        key = str(f["key"])
        if wanted is not None and key not in wanted:
            continue
        value = _number(f.get("value"))
        out.append(Reading(key, _str(f.get("unit")), _str(f.get("better")), value, None if value is not None else _missing_reason(f.get("value")),
                           int(f.get("matches_with_data") or 0), _int(f.get("percentile")), _number(f.get("league_value"))))
    return tuple(out)


def _str(x: Any) -> str | None:
    return x if isinstance(x, str) else None


def trends_of(doc: Mapping[str, Any]) -> tuple[TrendReading, ...]:
    """The trend rows of a team document body (``trends.items``), in the document's own order. A row that does not carry its counts is not read.
    Pure."""
    block = doc.get("trends")
    items = block.get("items") if isinstance(block, Mapping) else None
    if not isinstance(items, list):
        return ()
    out: list[TrendReading] = []
    for t in items:
        if not isinstance(t, Mapping) or not isinstance(t.get("key"), str):
            continue
        hits, n, pct = _int(t.get("hits")), _int(t.get("n")), _int(t.get("pct"))
        low, high = _int(t.get("wilson_low")), _int(t.get("wilson_high"))
        if hits is None or n is None or n < 1 or pct is None or low is None or high is None:
            continue
        league = t.get("league_pct")
        out.append(TrendReading(str(t["key"]), str(t.get("family") or ""), _str(t.get("rule_key")), _number(t.get("line")), hits, n, pct, low, high,
                                _int(league), None if _int(league) is not None else _missing_reason(league)))
    return tuple(out)


def document_of(row: Mapping[str, Any], *, as_of: datetime | None = None, keys: Iterable[str] | None = None) -> Document:
    """A row of ``analytics.stat_documents`` as a ``Document`` at the cut-off ``as_of`` (None: no cut-off). Pure."""
    kind, entity, cs = str(row["kind"]), int(row["entity_id"]), int(row["competition_season_id"])
    scope, context = str(row["scope"]), str(row["context"])
    computed_at = row["computed_at"]
    if as_of is not None and computed_at > as_of:
        return Document("after_cutoff", kind, entity, cs, scope, context)
    version = str(row["calc_version"])
    body = row["doc"] if isinstance(row["doc"], Mapping) else {}
    return Document("ok", kind, entity, cs, scope, context, version, document_id(kind, entity, cs, scope, context, version),
                    int(row.get("sample") or 0), computed_at, readings_of(body, keys), trends_of(body), body)


def read(conn: psycopg.Connection[Any], *, kind: str, entity_id: int, competition_season_id: int, scope: str = "season",
         context: str = "all", as_of: datetime | None = None, keys: Iterable[str] | None = None) -> Document:
    """The document of an entity in a competition season, scope and context, as it stood at ``as_of``. Read only: one SELECT by the primary key."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DOC_SQL, {"kind": kind, "entity": entity_id, "cs": competition_season_id, "scope": scope, "context": context})
        row = cur.fetchone()
    if row is None:
        return Document("no_document", kind, entity_id, competition_season_id, scope, context)
    return document_of(row, as_of=as_of, keys=keys)


__all__ = ["DOC_SQL", "KINDS", "VERSION", "Document", "Reading", "TrendReading", "document_id", "document_of", "read", "readings_of", "trends_of"]
