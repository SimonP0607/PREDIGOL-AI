"""How much each specialist's position counts, per market family (``council-weights-v1``, part of ``council-protocol-v1``).

A weight is a pure function of two things the shadow already stores, both read AS OF a moment:

* the TRACK RECORD of the agent version in the family: the ``VERDICT`` rows of ``intel.agent_attributions`` (``attr-v1``, written by
  code: ``fbi.ai.agents.attribution``) of the selections that had settled by then, counted by the definitions of the evaluation bench
  (``fbi.ai.eval_bench.signals``: HIT / (HIT + MISS), a VOID is in neither). One selection counts once per agent version, whatever
  shadow arm (``ma-v1``, ``ma-v1-h``) the row was written for: the specialist's stance is the same in both, and counting it twice would
  double its record;
* the PROMOTION of the version for the family: the owner-signed ``CHAMPION`` row of ``intel.promotions`` (entity ``agent``) that is in
  force for the family, read through the one registry (``fbi.governance.promotions``) with the rule of ``intel.agent_champion``.

    shrunk precision  (hits + PRIOR_STRENGTH * PRIOR_PRECISION) / (hits + misses + PRIOR_STRENGTH)
    weight            0                                                    when the version is not promoted for the family
                      clamp(shrunk / PRIOR_PRECISION, MIN_WEIGHT, MAX_WEIGHT)  otherwise

A promoted version with no record weighs exactly 1 (the prior is a coin flip, and a coin flip is the neutral weight); a long record
of hits moves it up to ``MAX_WEIGHT`` and never past it, a long record of misses down to ``MIN_WEIGHT`` and never under it. Bounded
on purpose: one agent can never outweigh the others by more than ``MAX_WEIGHT / MIN_WEIGHT``, however lucky its streak.

The weight is internal to the deterministic layer: it orders and sizes the positions the protocol reads, and it never travels toward a
decision (the output of the protocol is a ``ctx-adj-v1`` adjustment, which carries no number). Nothing here writes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.agents.attribution import VERSION as ATTRIBUTION_VERSION
from fbi.ai.agents.registry import PROMOTION_NAME
from fbi.ai.contracts.mcp import family_of
from fbi.ai.eval_bench import Signals, signals
from fbi.governance import promotions as registry

VERSION: Final = "council-weights-v1"

SPECIALISTS: Final = ("match", "stats")
"""The agents whose positions the protocol weighs. The Council is the judge, not a voice: it has no weight here."""

PRIOR_PRECISION: Final = Decimal("0.5")
"""The precision the prior assumes: a coin flip. A version is assumed to have no skill until its record says otherwise, so the
shrinkage pulls every record towards "no better than chance", never towards "good"."""

PRIOR_STRENGTH: Final = 20
"""How many pseudo-selections the prior is worth. Engineering choice: with 20, a version that hit 7 of 10 is read as 0.567, not 0.7;
it takes about a hundred decided selections before the record outweighs the prior four to one. A small sample cannot buy a weight."""

MIN_WEIGHT: Final = Decimal("0.5")
"""The floor of a PROMOTED version's weight (a non-promoted one is 0, below the floor by design). A promoted agent with a bad record is
heard at half the neutral weight, never silenced: silencing it is a demotion, and a demotion is the owner's (or the roll-back's) row."""

MAX_WEIGHT: Final = Decimal("1.5")
"""The ceiling: one and a half times the neutral weight, whatever the record. Three times the floor at most between two agents."""

WEIGHT_Q: Final = Decimal("0.0001")
"""Weights and shrunk precisions are kept to four places, so that the same rows always give the same bytes."""

CHAMPION: Final = "CHAMPION"
ENDS: Final = frozenset({"CHALLENGER", "RETIRED", "REJECTED"})
"""What ends a champion, as ``intel.agent_champion`` reads it (a VALIDATED or NOT_VALIDATED row is a report and ends nothing)."""

UPSTREAM_COUNTS: Final = True
"""A promotion names a PIPELINE (``council@council-v1+match-v2``: the Council and the versions it read). A specialist version named as
an upstream of the family's champion is promoted with it: the owner signed the pipeline that reads it. Only versions the owner's row
names count; an agent version the row does not name weighs zero."""

TRACK_SQL: Final = """
SELECT DISTINCT ON (a.agent, a.agent_version, a.fixture_id, a.market_key, a.selection, a.line)
       a.agent, a.agent_version, a.market_key, a.outcome
  FROM intel.agent_attributions a
  JOIN core.fixtures f ON f.id = a.fixture_id
 WHERE a.attribution_version = %(attr)s AND a.classified_by = 'code' AND a.signal = 'VERDICT'
   AND a.agent = ANY(%(agents)s) AND a.computed_at <= %(at)s AND f.kickoff_at < %(at)s
 ORDER BY a.agent, a.agent_version, a.fixture_id, a.market_key, a.selection, a.line, a.engine, a.id
"""
"""The stance rows of the specialists that had been written by ``at`` about matches that had kicked off by then: one per selection and
agent version (the first engine in name order, deterministically). Read-only, and in the shadow only (``tests/unit/test_attribution_readers``
lists this module as a reader)."""


@dataclass(frozen=True, slots=True)
class TrackRecord:
    agent: str
    version: str
    family: str
    counts: Signals
    """``eval_bench.Signals``: only its ``verdict_*`` counts are filled (the stance rows)."""

    @property
    def hits(self) -> int:
        return self.counts.verdict_hit

    @property
    def misses(self) -> int:
        return self.counts.verdict_miss

    @property
    def voids(self) -> int:
        return self.counts.verdict_void


@dataclass(frozen=True, slots=True)
class Champion:
    """The promotion in force for a family: the record of the registry and the versions its name puts in force."""

    family: str
    model_name: str
    source_id: str
    at: datetime
    head: tuple[str, str]
    """(agent, version) of the name's head."""
    upstream: tuple[str, ...]
    """The versions the head reads (``+match-v2``)."""

    def promotes(self, agent: str, version: str) -> bool:
        if (agent, version) == self.head:
            return True
        return UPSTREAM_COUNTS and version in self.upstream


@dataclass(frozen=True, slots=True)
class Weight:
    agent: str
    version: str
    family: str
    weight: Decimal
    promoted: bool
    hits: int
    misses: int
    voids: int
    shrunk_precision: Decimal
    promotion_id: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"agent": self.agent, "agent_version": self.version, "family": self.family, "weight": str(self.weight),
                "promoted": self.promoted, "promotion_id": self.promotion_id, "hits": self.hits, "misses": self.misses,
                "voids": self.voids, "shrunk_precision": str(self.shrunk_precision)}


# -- pure ------------------------------------------------------------------------------------------------------------------------------

def shrunk_precision(hits: int, misses: int) -> Decimal:
    """The record's precision pulled towards ``PRIOR_PRECISION`` by ``PRIOR_STRENGTH`` pseudo-selections."""
    if hits < 0 or misses < 0:
        raise ValueError("a count is not negative")
    value = (Decimal(hits) + PRIOR_STRENGTH * PRIOR_PRECISION) / (Decimal(hits + misses) + PRIOR_STRENGTH)
    return value.quantize(WEIGHT_Q)


def weight_of(agent: str, version: str, family: str, *, record: TrackRecord | None, champion: Champion | None) -> Weight:
    """The weight of one agent version in one family. Zero when the family's champion does not promote the version."""
    hits = record.hits if record is not None else 0
    misses = record.misses if record is not None else 0
    voids = record.voids if record is not None else 0
    shrunk = shrunk_precision(hits, misses)
    promoted = champion is not None and champion.promotes(agent, version)
    if not promoted:
        return Weight(agent, version, family, Decimal(0), False, hits, misses, voids, shrunk)
    raw = shrunk / PRIOR_PRECISION
    bounded = min(MAX_WEIGHT, max(MIN_WEIGHT, raw)).quantize(WEIGHT_Q)
    return Weight(agent, version, family, bounded, True, hits, misses, voids, shrunk, champion.source_id if champion else None)


def champion_of(records: Iterable[registry.Promotion], family: str, *, at: datetime) -> Champion | None:
    """The family's champion as of ``at``, by the rule of ``intel.agent_champion``: the newest CHAMPION row of the family, unless a later
    row of the same name ended it. Only effective, owner-signed rows promote; a name that is not the registry's grammar promotes nothing."""
    rows = [r for r in registry.history_of(records, "agent", family, at=at) if r.effective]
    newest = next((r for r in reversed(rows) if r.decision == CHAMPION), None)
    if newest is None or newest.decided_by != "owner" or newest.version is None:
        return None
    later = rows[rows.index(newest) + 1:]
    if any(r.version == newest.version and r.decision in ENDS for r in later):
        return None
    parsed = PROMOTION_NAME.fullmatch(newest.version)
    if parsed is None:
        return None
    upstream = tuple(u for u in parsed["upstream"].split("+") if u)
    return Champion(family, newest.version, newest.source_id, newest.at, (parsed["agent"], parsed["version"]), upstream)


def records_from(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], TrackRecord]:
    """(agent, version, family) -> its record, from the rows of ``TRACK_SQL``. A market of no family of the plan is not counted."""
    grouped: dict[tuple[str, str, str], list[tuple[bool, str, int]]] = defaultdict(list)
    for r in rows:
        family = family_of(str(r["market_key"]))
        if family is None:
            continue
        grouped[(str(r["agent"]), str(r["agent_version"]), family)].append((True, str(r["outcome"]), 1))
    return {k: TrackRecord(k[0], k[1], k[2], signals(v)) for k, v in sorted(grouped.items())}


@dataclass(frozen=True, slots=True)
class Book:
    """What the weights are computed from, as of one moment: every specialist's record and every family's champion."""

    at: datetime
    records: Mapping[tuple[str, str, str], TrackRecord]
    champions: Mapping[str, Champion | None]

    def weight(self, agent: str, version: str, family: str) -> Weight:
        return weight_of(agent, version, family, record=self.records.get((agent, version, family)), champion=self.champions.get(family))


def book_from(*, at: datetime, track_rows: Iterable[Mapping[str, Any]], promotions: Sequence[registry.Promotion],
              families: Iterable[str]) -> Book:
    return Book(at, records_from(track_rows), {f: champion_of(promotions, f, at=at) for f in sorted(set(families))})


# -- reading ---------------------------------------------------------------------------------------------------------------------------

def read_book(conn: psycopg.Connection[Any], *, at: datetime, families: Iterable[str]) -> Book:
    """The book as of ``at`` (read-only): the specialists' records and the champions of ``families``."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TRACK_SQL, {"attr": ATTRIBUTION_VERSION, "agents": list(SPECIALISTS), "at": at})
        rows = [dict(r) for r in cur.fetchall()]
    promotions = registry.all_promotions(conn, at=at, entity_type="agent")
    return book_from(at=at, track_rows=rows, promotions=promotions, families=families)


__all__ = ["MAX_WEIGHT", "MIN_WEIGHT", "PRIOR_PRECISION", "PRIOR_STRENGTH", "SPECIALISTS", "VERSION", "Book", "Champion", "TrackRecord",
           "Weight", "book_from", "champion_of", "read_book", "records_from", "shrunk_precision", "weight_of"]
