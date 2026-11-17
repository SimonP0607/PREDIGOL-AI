"""What the LAB of ``AD-B07`` reads from production, as read-only ``COPY ... TO STDOUT`` statements (IA-095).

Each statement is self-contained (the window is written in as literals made by the caller, never text from anywhere) so it can run
with ``psql`` in a read-only transaction and bring a small CSV out; ``fbi.countcal.walkforward`` reads the files, nothing here
connects.

* ``market_statement``   the books' probability of «over» without margin, as ``fbi.families.versus`` builds it: the last price of each
  book before the kick-off, only COMPLETE books (Over and Under at that line, one definition, a margin in (1, ``MAX_OVERROUND``]),
  each book de-vigged in proportion, the mean of the books and how many; only half lines. The family's own rule (3 books or more)
  is applied by the reader, so the file also shows the thinner markets.
* ``referee_statement``  the referee each match had ``REFEREE_LEAD`` before its kick-off: the newest sighting in
  ``core.fixture_officials`` by then, through its alias to the referee the platform settled on (F3 and IA-071: a merge moves aliases,
  so a merged referee is read as the one he was merged into). A match whose referee was only seen later has none.
* ``nulls_statement``    how many matches with a corners or cards price finished without the count the rule needs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.countcal.calibrator import FAMILY_OF_KEY

MAX_OVERROUND: Final = 1.25
PRICE_WINDOW: Final = timedelta(days=10)
REFEREE_LEAD: Final = timedelta(hours=3)
KEYS: Final = tuple(FAMILY_OF_KEY)


def _ts(t: datetime) -> str:
    if t.tzinfo is None:
        raise ValueError("an instant needs its time zone")
    return f"TIMESTAMPTZ '{t.astimezone(UTC).isoformat()}'"


def _keys() -> str:
    for k in KEYS:
        if not k.replace("_", "").isalnum():
            raise ValueError(f"not a market key: {k!r}")
    return "ARRAY[" + ", ".join(f"'{k}'" for k in KEYS) + "]::text[]"


def market_statement(*, start: datetime, end: datetime) -> str:
    """One row per (match, market key, half line): ``p_over`` (mean of the complete books, margin removed) and ``books``."""
    return (
        "COPY (WITH fx AS (SELECT id, kickoff_at FROM core.fixtures "
        f"WHERE kickoff_at >= {_ts(start)} AND kickoff_at < {_ts(end)}), "
        "last AS (SELECT DISTINCT ON (q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line) "
        "q.fixture_id, q.bookmaker_id, q.definition_id, d.market_key, q.selection, q.line, q.odds_decimal "
        "FROM fx JOIN market.odds_quotes q ON q.fixture_id = fx.id JOIN market.market_definitions d ON d.id = q.definition_id "
        f"WHERE d.scope = 'prematch' AND d.kind = 'over_under' AND d.market_key = ANY({_keys()}) "
        f"AND q.captured_at <= fx.kickoff_at AND q.captured_at >= fx.kickoff_at - INTERVAL '{PRICE_WINDOW.days} days' "
        "AND q.odds_decimal > 1 "
        "ORDER BY q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line, q.captured_at DESC), "
        "book AS (SELECT fixture_id, bookmaker_id, market_key, line, count(*) AS n, count(DISTINCT definition_id) AS defs, "
        "max(CASE WHEN selection = 'Over' THEN 1 / odds_decimal END) AS io, "
        "max(CASE WHEN selection = 'Under' THEN 1 / odds_decimal END) AS iu "
        "FROM last GROUP BY fixture_id, bookmaker_id, market_key, line) "
        "SELECT fixture_id, market_key, line, round(avg(io / (io + iu))::numeric, 6) AS p_over, count(*) AS books "
        "FROM book WHERE n = 2 AND defs = 1 AND io IS NOT NULL AND iu IS NOT NULL "
        f"AND io + iu > 1 AND io + iu <= {MAX_OVERROUND} AND mod(line, 1) = 0.5 "
        "GROUP BY fixture_id, market_key, line ORDER BY fixture_id, market_key, line) "
        "TO STDOUT WITH (FORMAT csv, HEADER true)")


REFEREE_SELECT: Final = (
    "SELECT DISTINCT ON (o.fixture_id) o.fixture_id, a.referee_id, "
    "to_char(o.observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS') || '+00:00' AS seen_at "
    "FROM core.fixture_officials o JOIN core.fixtures f ON f.id = o.fixture_id "
    "LEFT JOIN core.referee_aliases a ON a.id = o.alias_id "
    "WHERE f.kickoff_at >= {start} AND f.kickoff_at < {end} AND o.role = 'referee' "
    "AND o.observed_at <= f.kickoff_at - INTERVAL '{lead} hours' "
    "ORDER BY o.fixture_id, o.observed_at DESC")
"""The referee of each match as the newest sighting ``REFEREE_LEAD`` before its kick-off (a sighting without alias: taken off)."""


def referee_statement(*, start: datetime, end: datetime) -> str:
    """One row per match with a kick-off in ``[start, end)`` whose referee was designated ``REFEREE_LEAD`` before it."""
    lead = int(REFEREE_LEAD.total_seconds() // 3600)
    return f"COPY ({REFEREE_SELECT.format(start=_ts(start), end=_ts(end), lead=lead)}) TO STDOUT WITH (FORMAT csv, HEADER true)"


def referee_known(conn: psycopg.Connection[Any], *, start: datetime, end: datetime) -> dict[int, int]:
    """The same read, through a connection: match -> the referee designated in time (the ones taken off are left out)."""
    lead = int(REFEREE_LEAD.total_seconds() // 3600)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(REFEREE_SELECT.format(start=_ts(start), end=_ts(end), lead=lead))
        return {int(r[0]): int(r[1]) for r in cur.fetchall() if r[1] is not None}


def nulls_statement(*, start: datetime, end: datetime) -> str:
    """Matches with a price of the family (any book) that finished, and how many of them lack the count the rule reads. The quotes are
    read through their definitions (the index on ``definition_id``), never by a scan of the price table."""
    return (
        "COPY (WITH priced AS (SELECT DISTINCT q.fixture_id, "
        "CASE WHEN d.market_key LIKE 'CORNERS%' THEN 'corners' ELSE 'cards' END AS family "
        "FROM market.market_definitions d JOIN market.odds_quotes q ON q.definition_id = d.id "
        f"WHERE d.scope = 'prematch' AND d.market_key = ANY({_keys()}) "
        f"AND q.captured_at >= {_ts(start - PRICE_WINDOW)} AND q.captured_at < {_ts(end)}) "
        "SELECT p.family, count(*) AS priced_finished, count(*) FILTER (WHERE (p.family = 'corners' AND o.corners_ft_home IS NULL) "
        "OR (p.family = 'cards' AND o.cards_lines_ft_home IS NULL)) AS without_count "
        "FROM priced p JOIN market.fixture_outcomes o ON o.fixture_id = p.fixture_id "
        f"WHERE o.kickoff_at >= {_ts(start)} AND o.kickoff_at < {_ts(end)} "
        "GROUP BY p.family ORDER BY p.family) TO STDOUT WITH (FORMAT csv, HEADER true)")
