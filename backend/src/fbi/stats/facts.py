"""Statistics as CITABLE FACTS: a rate with its sample, its period, the league's reference and its interval (plan RP-6.2, findings H20 and H32).

«8 of the last 10 matches went over 2.5» is not a reason: in the league the next one goes over 56.1 % of the time, and after those eight of ten
it goes over 58.8 %. A streak means something only against what the league does, and only as much as its sample allows. This module turns the
trend rows that the team documents already hold (EA-006, read through ``fbi.stats.reading``: nothing is recomputed here) into facts that carry
the five things a reader needs to weigh them:

    rate ........ hits of n (the exact fraction, never a rounded percentage)
    sample ...... n, and the document it came from (``document_id``, its ``computed_at``)
    period ...... the document's scope and context (season, home, away...)
    reference ... the league's rate for the same selection - MANDATORY: a trend without it is not a fact, it is discarded with its reason
    interval .... the document's Wilson 95 % interval

and with a WEIGHT: the distance to the league's reference measured in standard errors of that reference (``z = (rate - ref) / sqrt(ref (1 - ref) / n)``),
so a long sample far from the league weighs more than a short sample equally far. ``choose`` picks, by code and with a fixed tie-break, the fact of
most weight in favour and the one of most weight against. The percentile places a team's rate among the teams of its league (mid-rank).

No model writes any of this and none of it changes a probability: it is read-only arithmetic over stored documents.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.stats.reading import Document, TrendReading

VERSION: Final = "stat-facts-v1"

MIN_SAMPLE: Final = int(json.loads((Path(__file__).with_name("stabilization_v1.json")).read_text(encoding="utf-8"))["current_min_matches"])
"""The fewest matches a trend is read on: the one the statistics pages already use («can rise, never be lowered without the owner's decision»)."""
MIN_PEERS: Final = 8
"""The fewest teams a percentile is computed among; with fewer it is not given."""
FOR: Final = "for"
AGAINST: Final = "against"

NO_REFERENCE: Final = "sin_referencia_de_liga"
SMALL_SAMPLE: Final = "muestra_insuficiente"
NO_DOCUMENT: Final = "sin_documento"


@dataclass(frozen=True, slots=True)
class Fact:
    """A trend of a team as a citable fact. ``weight`` is signed: positive, the team does it more than the league; negative, less."""

    team_id: int
    key: str
    family: str
    rule_key: str | None
    line: float | None
    hits: int
    n: int
    rate: float
    wilson_low_pct: int
    wilson_high_pct: int
    league_pct: int
    league_rate: float
    weight: float
    percentile: int | None
    document_id: str
    computed_at: datetime | None
    scope: str
    context: str

    @property
    def side(self) -> str:
        return FOR if self.weight > 0 else AGAINST

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "team_id": self.team_id, "key": self.key, "family": self.family, "rule_key": self.rule_key, "line": self.line,
                "hits": self.hits, "n": self.n, "rate": round(self.rate, 4), "wilson_pct": [self.wilson_low_pct, self.wilson_high_pct],
                "league_pct": self.league_pct, "weight": round(self.weight, 3), "side": self.side, "percentile": self.percentile,
                "period": {"scope": self.scope, "context": self.context}, "source": {"document_id": self.document_id,
                                                                                      "computed_at": None if self.computed_at is None else self.computed_at.isoformat()}}


def weight_of(hits: int, n: int, league_pct: int) -> float:
    """The distance of the rate to the league's reference in standard errors of the reference. The league's percentage is stored as an integer, so
    the reference is held inside (0.5 %, 99.5 %) to keep the standard error from collapsing at the edges."""
    ref = min(max(league_pct / 100.0, 0.005), 0.995)
    return (hits / n - ref) / math.sqrt(ref * (1 - ref) / n)


def percentile_of(value: int, peers: Sequence[int]) -> int | None:
    """Where a rate stands among the teams of its league (mid-rank, 0 to 100); None with fewer than ``MIN_PEERS`` of them."""
    if len(peers) < MIN_PEERS:
        return None
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    return round(100 * (below + 0.5 * equal) / len(peers))


def facts_of(doc: Document, *, peers: Mapping[str, Sequence[int]] | None = None, min_sample: int = MIN_SAMPLE) -> tuple[list[Fact], list[dict[str, Any]]]:
    """The facts of one team document and what was left out with its reason. A trend needs its league reference and ``min_sample`` matches."""
    if doc.status != "ok" or doc.document_id is None:
        return [], [{"team_id": doc.entity_id, "key": None, "reason": NO_DOCUMENT}]
    facts: list[Fact] = []
    left: list[dict[str, Any]] = []
    for t in doc.trends:
        if t.league_pct is None:
            left.append({"team_id": doc.entity_id, "key": t.key, "reason": NO_REFERENCE})
        elif t.n < min_sample:
            left.append({"team_id": doc.entity_id, "key": t.key, "reason": SMALL_SAMPLE, "n": t.n})
        else:
            facts.append(_fact(doc, t, peers))
    return facts, left


def _fact(doc: Document, t: TrendReading, peers: Mapping[str, Sequence[int]] | None) -> Fact:
    assert t.league_pct is not None and doc.document_id is not None
    return Fact(doc.entity_id, t.key, t.family, t.rule_key, t.line, t.hits, t.n, t.hits / t.n, t.wilson_low, t.wilson_high, t.league_pct,
                t.league_pct / 100.0, weight_of(t.hits, t.n, t.league_pct), None if peers is None or t.key not in peers else percentile_of(t.pct, peers[t.key]),
                doc.document_id, doc.computed_at, doc.scope, doc.context)


def choose(facts: Iterable[Fact], key: str) -> dict[str, Fact | None]:
    """For one trend (by its code), the fact of most weight in favour and the one of most weight against, among the facts of the teams of the
    match. The order is fixed - weight, then the team's id - so the same documents always give the same choice."""
    same = [f for f in facts if f.key == key]
    favour = sorted((f for f in same if f.weight > 0), key=lambda f: (-f.weight, f.team_id))
    against = sorted((f for f in same if f.weight < 0), key=lambda f: (f.weight, f.team_id))
    return {FOR: favour[0] if favour else None, AGAINST: against[0] if against else None}


def for_match(documents: Sequence[Document], *, peers: Mapping[str, Sequence[int]] | None = None,
              min_sample: int = MIN_SAMPLE) -> dict[str, Any]:
    """The facts of a match from the documents of its teams: every fact, the choice by trend code and what was left out. Pure."""
    facts: list[Fact] = []
    left: list[dict[str, Any]] = []
    for d in documents:
        f, lf = facts_of(d, peers=peers, min_sample=min_sample)
        facts += f
        left += lf
    by_key: dict[str, dict[str, Any]] = {}
    for key in sorted({f.key for f in facts}):
        picked = choose(facts, key)
        by_key[key] = {side: None if fact is None else fact.as_json() for side, fact in picked.items()}
    return {"version": VERSION, "min_sample": min_sample, "facts": [f.as_json() for f in facts], "chosen": by_key, "left_out": left}


PEERS_SQL: Final = """
SELECT it->>'key', (it->>'pct')::int
  FROM analytics.stat_documents d, jsonb_array_elements(d.doc->'trends'->'items') it
 WHERE d.kind = 'team' AND d.competition_season_id = %(cs)s AND d.scope = %(scope)s AND d.context = %(context)s
   AND d.computed_at <= %(as_of)s AND it->>'key' = ANY(%(keys)s) AND (it->>'n')::int >= %(min_sample)s
"""
"""The rate of every team of the league for each trend, to place a team among them. One indexed read of the documents in force at the cut-off."""


def peers(conn: psycopg.Connection[Any], *, competition_season_id: int, scope: str, context: str, keys: Sequence[str], as_of: datetime,
          min_sample: int = MIN_SAMPLE) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PEERS_SQL, {"cs": competition_season_id, "scope": scope, "context": context, "as_of": as_of, "keys": list(keys),
                                "min_sample": min_sample})
        for key, pct in cur.fetchall():
            out[str(key)].append(int(pct))
    return dict(out)
