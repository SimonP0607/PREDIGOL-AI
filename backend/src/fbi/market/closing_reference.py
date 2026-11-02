"""WHICH price is "the close" of a selection - the reference every post-mortem judges a price against (plan F8.7).

``fbi.market.closing_value`` holds the two formulas (CLV and the price move). This module holds the other half of the
definition: WHICH closing price goes into them, and the only SQL that picks it for a post-mortem.

    the closing fair probability   the LAST de-vigged (Shin) consensus captured before kick-off
                                   (``market.market_consensus``, ``devig_method = 'shin'``, ``as_of < kickoff_at``).
                                   It is what CLV is measured at, and ``intel.decision_outcomes`` picks it the same way
                                   (its SQL stays where it is - one batch of 20,000 rows - and
                                   ``tests/integration/test_closing_reference.py`` holds the two to the same numbers).
    the same book's last price     the provider's last pre-match price of the SAME bookmaker the price was taken at
                                   (``market.final_prematch_odds``, read after the match, stamped before kick-off).
                                   It is what the PRICE MOVE is measured against.

THE REFERENCE IS NEAR THE CLOSE, NOT THE CLOSE. Measured in production on 23 Oct 2026 (F7, 38,121 matches): the last consensus
before kick-off is a median of ~175 minutes before it, while the provider's last pre-match price is a median of ~85 minutes before
it and exists for 72 % of the matches. The consensus is the reference because it is what every other number of the system
(``decision_outcomes.clv``, ``pick_line_value.lv_devigged``, the walk-forward gate, the score, the memory) already uses; changing
it would make the old and the new rows incomparable and is the owner's decision, not a silent one. What changes here is that the
reference is NAMED and stored beside the number: every post-mortem keeps ``close_minutes_to_ko`` and says so when the reference is far
from kick-off (``FAR_FROM_KICKOFF``), and ``python -m scripts.postmortems closes`` measures both references over the same selections
so that the decision can be taken with numbers.

Pure reads: nothing here writes, and nothing here is read before a match (the close does not exist before it).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

REFERENCE = "last-shin-consensus-before-kickoff"
"""The name of the reference, stored with every post-mortem (``evidence.close.reference``)."""

FAR_FROM_KICKOFF = 120
"""Minutes. A reference captured earlier than this before kick-off is flagged ``far`` in the evidence: the close it stands for
may have moved since (the CLV against it is value against a near-close price, as everywhere else in the system)."""

BATCH = 400

Key = tuple[int, str, str, Decimal]
"""(fixture, market, selection, line) - the key of a selection everywhere in the system."""

BookKey = tuple[int, int, str, str, Decimal]
"""(fixture, bookmaker, market, selection, line)."""

CLOSE_SQL = """
SELECT k.ord, m.p_fair::float8 AS p_fair, m.best_odds::float8 AS best_odds, m.as_of, f.kickoff_at
  FROM unnest(%(fixtures)s::bigint[], %(markets)s::text[], %(selections)s::text[], %(lines)s::numeric[])
       WITH ORDINALITY AS k(fixture_id, market_key, selection, line, ord)
  JOIN core.fixtures f ON f.id = k.fixture_id
  JOIN LATERAL (SELECT c.p_fair, c.best_odds, c.as_of FROM market.market_consensus c
                 WHERE c.fixture_id = k.fixture_id AND c.market_key = k.market_key AND c.selection = k.selection
                   AND c.line = k.line AND c.devig_method = 'shin' AND c.as_of < f.kickoff_at
                 ORDER BY c.as_of DESC LIMIT 1) m ON true
"""
"""The closing fair probability of each selection of a batch: the last Shin consensus before its kick-off."""

SAME_BOOK_SQL = """
SELECT k.ord, p.odds_decimal::float8 AS odds, p.minutes_to_ko
  FROM unnest(%(fixtures)s::bigint[], %(books)s::int[], %(markets)s::text[], %(selections)s::text[], %(lines)s::numeric[])
       WITH ORDINALITY AS k(fixture_id, bookmaker_id, market_key, selection, line, ord)
  JOIN market.final_prematch_odds p ON p.fixture_id = k.fixture_id AND p.bookmaker_id = k.bookmaker_id
   AND p.market_key = k.market_key AND p.selection = k.selection AND p.line = k.line
"""
"""The provider's last pre-match price at the bookmaker a price was taken at, for each selection of a batch."""


@dataclass(frozen=True, slots=True)
class Close:
    """The closing fair probability of a selection and how near kick-off it was captured."""

    p_fair: float
    best_odds: float | None
    as_of: datetime
    minutes_to_ko: int

    @property
    def far(self) -> bool:
        return self.minutes_to_ko > FAR_FROM_KICKOFF

    def evidence(self) -> dict[str, Any]:
        return {"reference": REFERENCE, "as_of": self.as_of.isoformat(), "minutes_to_ko": self.minutes_to_ko,
                "far": self.far, "best_odds": self.best_odds}


@dataclass(frozen=True, slots=True)
class BookClose:
    """The provider's last pre-match price at one bookmaker and how near kick-off it was stamped."""

    odds: float
    minutes_to_ko: int


def _chunks[T](items: Sequence[T]) -> list[Sequence[T]]:
    return [items[i:i + BATCH] for i in range(0, len(items), BATCH)]


def closing_probabilities(conn: psycopg.Connection[Any], keys: Sequence[Key]) -> dict[Key, Close]:
    """The closing fair probability of every selection that has one (the others are absent from the result)."""
    found: dict[Key, Close] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for chunk in _chunks(list(keys)):
            cur.execute(CLOSE_SQL, {"fixtures": [k[0] for k in chunk], "markets": [k[1] for k in chunk],
                                    "selections": [k[2] for k in chunk], "lines": [k[3] for k in chunk]})
            for r in cur.fetchall():
                minutes = int((r["kickoff_at"] - r["as_of"]).total_seconds() // 60)
                found[chunk[int(r["ord"]) - 1]] = Close(float(r["p_fair"]), None if r["best_odds"] is None
                                                        else float(r["best_odds"]), r["as_of"], minutes)
    return found


def same_book_closes(conn: psycopg.Connection[Any], keys: Sequence[BookKey]) -> dict[BookKey, BookClose]:
    """The provider's last pre-match price at the bookmaker of each price taken (absent when it was not read)."""
    found: dict[BookKey, BookClose] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for chunk in _chunks(list(keys)):
            cur.execute(SAME_BOOK_SQL, {"fixtures": [k[0] for k in chunk], "books": [k[1] for k in chunk],
                                        "markets": [k[2] for k in chunk], "selections": [k[3] for k in chunk],
                                        "lines": [k[4] for k in chunk]})
            for r in cur.fetchall():
                found[chunk[int(r["ord"]) - 1]] = BookClose(float(r["odds"]), int(r["minutes_to_ko"]))
    return found
