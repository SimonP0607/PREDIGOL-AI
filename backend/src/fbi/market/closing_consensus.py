"""The consensus of the REAL close of the market (plan RP-1.4, finding H7, ``closing-consensus-v1``).

``fbi.market.closing_reference`` names the reference every closing-line value of the system is measured against: the last consensus WE captured
before kick-off, a median of ~175 minutes before it. The provider keeps each bookmaker's last pre-match price for a week and the platform reads it
after the match (``market.final_prematch_odds``, a median of ~85 minutes before kick-off): it is nearer the close, and it exists for most matches.
This module builds the objective consensus of it - each bookmaker's LAST price, stamped in the last hour before kick-off, de-vigged per book and
averaged by ``fbi.market.consensus`` (the one de-vig of the system) - and stores it beside the other one, never instead of it:

    market.closing_consensus      per match / market / selection / line / method: the fair probability, how many books, and the minutes before
                                  kick-off it stands for (the median of the books' stamps, and the nearest).
    intel.decision_real_close     per settled decision: ``clv_real`` = ``closing_value.clv(odds, p_fair)`` at that real close.

The reference that was "the close" is renamed in the words of the screens "reference prior to the close" (``REFERENCE_PRIOR``); its numbers, its
column names and its history are not touched. Nothing here is read before a match and no decision reads it: the real close does not exist then.

A consensus of fewer than ``MIN_BOOKS`` books is not a consensus and is not stored (the same three as the families); a price is never guessed.
``run`` computes the matches of a window that have none yet (the backfill is the same call over a long window: it is idempotent); ``settle`` writes
``clv_real`` for every decision that has both its outcome and a real close, in either order of arrival.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.market import closing_reference, closing_value, consensus

VERSION: Final = "closing-consensus-v1"
REFERENCE: Final = "consensus-of-last-prematch-prices-in-last-hour"
"""The name of the real close, stored with every ``clv_real``."""
REFERENCE_PRIOR: Final = closing_reference.REFERENCE
"""What used to be called "the close": the last consensus captured before kick-off. Its name is unchanged; only its role in the words is."""
WINDOW_MINUTES: Final = 60
"""A price counts as the real close when the provider stamped it at most this long before kick-off."""
TARGET_MINUTES: Final = 30
"""The plan's acceptance: the closing consensus stands for a minute at most this far from kick-off in 80 % of the matches with a price."""
TARGET_SHARE: Final = 0.8
MIN_BOOKS: Final = 3
CHUNK: Final = 200
"""Matches read and written at a time."""
BATCH: Final = 20000
P_Q: Final = Decimal("0.000001")

FIXTURES_SQL: Final = """
SELECT DISTINCT p.fixture_id
  FROM market.final_prematch_odds p
 WHERE p.fetched_at >= %(since)s AND p.fetched_at < %(until)s AND p.fixture_id > %(after)s AND p.minutes_to_ko <= %(window)s
   AND NOT EXISTS (SELECT 1 FROM market.closing_consensus c WHERE c.fixture_id = p.fixture_id)
 ORDER BY p.fixture_id
 LIMIT %(limit)s
"""
"""The next matches (after the last one read) whose last prices were read in the window and that have no closing consensus yet."""

QUOTES_SQL: Final = """
SELECT p.fixture_id, p.bookmaker_id, p.market_key, p.selection, p.line, p.odds_decimal, p.minutes_to_ko
  FROM market.final_prematch_odds p
 WHERE p.fixture_id = ANY(%(fixtures)s::bigint[]) AND p.minutes_to_ko <= %(window)s AND p.market_key = ANY(%(markets)s::text[])
"""

INSERT_SQL: Final = (
    "INSERT INTO market.closing_consensus (fixture_id, market_key, selection, line, devig_method, p_fair, n_bookmakers, minutes_to_ko, "
    "newest_minutes_to_ko, best_odds, version, computed_at) VALUES (%(fixture)s, %(market)s, %(selection)s, %(line)s, %(method)s, %(p)s, %(n)s, "
    "%(median)s, %(newest)s, %(best)s, %(version)s, %(at)s) ON CONFLICT DO NOTHING")

SETTLE_SQL: Final = """
SELECT d.id, d.fixture_id, d.odds, c.p_fair, c.n_bookmakers, c.minutes_to_ko
  FROM intel.decision_outcomes o
  JOIN intel.decisions d ON d.id = o.decision_id
  JOIN market.closing_consensus c ON c.fixture_id = d.fixture_id AND c.market_key = d.market_key AND c.selection = d.selection
   AND c.line = d.line AND c.devig_method = 'shin'
  LEFT JOIN intel.decision_real_close r ON r.decision_id = d.id
 WHERE r.decision_id IS NULL AND d.odds IS NOT NULL
 ORDER BY d.id
 LIMIT %(limit)s
"""
"""The decisions that have an outcome and a real close and no ``clv_real`` yet (a decision with no real close is simply not in it)."""

SETTLE_INSERT_SQL: Final = (
    "INSERT INTO intel.decision_real_close (decision_id, fixture_id, real_p_fair, real_minutes_to_ko, n_bookmakers, clv_real, reference, version, "
    "computed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (decision_id) DO NOTHING")


@dataclass(frozen=True, slots=True)
class Stamped:
    """One bookmaker's last price of a selection and how long before kick-off the provider stamped it."""

    quote: consensus.BookQuote
    minutes_to_ko: int


@dataclass(frozen=True, slots=True)
class Row:
    """A closing consensus of one selection: what ``market.closing_consensus`` keeps."""

    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    method: str
    p_fair: Decimal
    n_bookmakers: int
    minutes_to_ko: int
    newest_minutes_to_ko: int
    best_odds: Decimal | None


def _group(market: str, line: Decimal) -> tuple[str, Decimal]:
    """The two sides of an Asian handicap are quoted at opposite lines; they belong to one book."""
    return market, abs(line) if market == "AH" else line


def rows(fixture_id: int, stamped: Sequence[Stamped], *, min_books: int = MIN_BOOKS) -> list[Row]:
    """The closing consensus of a match from the last prices of its books (pure)."""
    minutes: dict[tuple[str, Decimal], dict[int, int]] = defaultdict(dict)
    for s in stamped:
        key = _group(s.quote.market_key, s.quote.line)
        book = s.quote.bookmaker_id
        minutes[key][book] = min(minutes[key].get(book, s.minutes_to_ko), s.minutes_to_ko)
    out: list[Row] = []
    for r in consensus.consensus([s.quote for s in stamped]):
        if r.n_bookmakers < min_books or not 0 < r.p_fair < 1:
            continue
        stamps = list(minutes[_group(r.market_key, r.line)].values())
        out.append(Row(fixture_id, r.market_key, r.selection, r.line, r.method, Decimal(str(r.p_fair)).quantize(P_Q), r.n_bookmakers,
                       int(statistics.median(stamps)), min(stamps), r.best_odds))
    return out


def read(conn: psycopg.Connection[Any], fixtures: Sequence[int]) -> dict[int, list[Stamped]]:
    """The last prices stamped in the window, by match (one read of the captured-after-the-match table)."""
    by_fixture: dict[int, list[Stamped]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(QUOTES_SQL, {"fixtures": list(fixtures), "window": WINDOW_MINUTES, "markets": consensus.CONSENSUS_MARKETS})
        for r in cur.fetchall():
            quote = consensus.BookQuote(int(r["bookmaker_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"]),
                                        Decimal(r["odds_decimal"]))
            by_fixture[int(r["fixture_id"])].append(Stamped(quote, int(r["minutes_to_ko"])))
    return by_fixture


def store(conn: psycopg.Connection[Any], found: Iterable[Row], *, at: datetime) -> int:
    n = 0
    with conn.cursor() as cur:
        for r in found:
            cur.execute(INSERT_SQL, {"fixture": r.fixture_id, "market": r.market_key, "selection": r.selection, "line": r.line, "method": r.method,
                                     "p": r.p_fair, "n": r.n_bookmakers, "median": r.minutes_to_ko, "newest": r.newest_minutes_to_ko,
                                     "best": r.best_odds, "version": VERSION, "at": at})
            n += max(cur.rowcount, 0)
    return n


def run(conn: psycopg.Connection[Any], *, at: datetime, days: int = 3, limit: int = BATCH, commit: bool = False) -> dict[str, int]:
    """Compute and store the closing consensus of every match whose last prices were read in the last ``days`` days and has none.

    Walks the matches by id in chunks, so a match with too few books (it has no consensus, and never will) cannot hold back the ones after it.
    The backfill is the same call with a long window and ``commit`` (a chunk at a time, so a long run is not one transaction); inside the nightly
    job the caller owns the transaction."""
    since, until = at - timedelta(days=days), at
    after, seen, rows_written = 0, 0, 0
    while seen < limit:
        with conn.cursor() as cur:
            cur.execute(FIXTURES_SQL, {"since": since, "until": until, "after": after, "window": WINDOW_MINUTES, "limit": CHUNK})
            fixtures = [int(r[0]) for r in cur.fetchall()]
        if not fixtures:
            break
        stamped = read(conn, fixtures)
        for fid in fixtures:
            rows_written += store(conn, rows(fid, stamped.get(fid, ())), at=at)
        if commit:
            conn.commit()
        seen += len(fixtures)
        after = fixtures[-1]
    return {"matches": seen, "rows": rows_written}


def settle(conn: psycopg.Connection[Any], *, at: datetime, limit: int = BATCH) -> int:
    """``clv_real`` of every settled decision that has a real close and none stored yet."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SETTLE_SQL, {"limit": limit})
        todo = cur.fetchall()
    n = 0
    with conn.cursor() as cur:
        for r in todo:
            p = Decimal(r["p_fair"])
            clv = closing_value.clv(Decimal(r["odds"]), p).quantize(Decimal("0.000001"))
            cur.execute(SETTLE_INSERT_SQL, (int(r["id"]), int(r["fixture_id"]), p, int(r["minutes_to_ko"]), int(r["n_bookmakers"]), clv, REFERENCE,
                                            VERSION, at))
            n += max(cur.rowcount, 0)
    return n


def step(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, int]:
    """The nightly step: the closing consensus of the matches read in the last three days, then the value of every decision against it."""
    made = run(conn, at=at)
    return {**made, "decisions": settle(conn, at=at)}


MEASURE_SQL: Final = """
WITH priced AS (
    SELECT p.fixture_id FROM market.final_prematch_odds p
     WHERE p.fetched_at >= %(since)s AND p.fetched_at < %(until)s GROUP BY p.fixture_id
), real AS (
    SELECT c.fixture_id, min(c.minutes_to_ko) AS median_min, min(c.newest_minutes_to_ko) AS newest_min, max(c.n_bookmakers) AS books
      FROM market.closing_consensus c JOIN priced USING (fixture_id) WHERE c.devig_method = 'shin' GROUP BY c.fixture_id
), prior AS (
    SELECT m.fixture_id, extract(epoch FROM f.kickoff_at - max(m.as_of)) / 60 AS minutes
      FROM market.market_consensus m JOIN core.fixtures f ON f.id = m.fixture_id JOIN priced pr ON pr.fixture_id = m.fixture_id
     WHERE m.devig_method = 'shin' AND m.as_of < f.kickoff_at GROUP BY m.fixture_id, f.kickoff_at
)
SELECT (SELECT count(*) FROM priced) AS priced,
       (SELECT count(*) FROM real) AS with_close,
       (SELECT count(*) FROM real WHERE median_min <= %(target)s) AS within_target,
       (SELECT count(*) FROM real WHERE median_min <= %(window)s) AS within_window,
       (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY median_min) FROM real) AS real_median_minutes,
       (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY minutes) FROM prior) AS prior_median_minutes,
       (SELECT count(*) FROM prior) AS with_prior
"""

PAIRS_SQL: Final = """
SELECT count(*) AS decisions, avg(o.clv)::float8 AS clv_prior, avg(r.clv_real)::float8 AS clv_real,
       avg(abs(r.clv_real - o.clv))::float8 AS mean_abs_difference
  FROM intel.decision_real_close r JOIN intel.decision_outcomes o ON o.decision_id = r.decision_id
 WHERE o.settled_at >= %(since)s AND o.settled_at < %(until)s AND o.clv IS NOT NULL
"""


def measure(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> dict[str, Any]:
    """Where the real close stands against the plan's acceptance (80 % of the matches with a price within 30 minutes) and against the prior one."""
    window = {"since": since, "until": until}
    with conn.cursor(row_factory=dict_row) as cur:
        a = cur.execute(MEASURE_SQL, {**window, "target": TARGET_MINUTES, "window": WINDOW_MINUTES}).fetchone() or {}
        b = cur.execute(PAIRS_SQL, window).fetchone() or {}
    with_close = int(a.get("with_close") or 0)
    share = None if not with_close else int(a["within_target"]) / with_close
    return {
        "version": VERSION, "reference": REFERENCE, "reference_prior": REFERENCE_PRIOR,
        "since": since.isoformat(), "until": until.isoformat(),
        "matches_with_price": int(a.get("priced") or 0), "matches_with_real_close": with_close,
        "within_target": int(a.get("within_target") or 0), "target_minutes": TARGET_MINUTES, "share_within_target": share,
        "meets_acceptance": share is not None and share >= TARGET_SHARE,
        "real_median_minutes": a.get("real_median_minutes"), "prior_median_minutes": a.get("prior_median_minutes"),
        "decisions_with_both": int(b.get("decisions") or 0), "clv_prior_mean": b.get("clv_prior"), "clv_real_mean": b.get("clv_real"),
        "mean_abs_difference": b.get("mean_abs_difference"),
    }


def lines(doc: Mapping[str, Any]) -> list[str]:
    """The measure in Spanish."""

    def f(v: Any, digits: int = 1) -> str:
        return "sin dato" if v is None else f"{float(v):.{digits}f}"

    share = doc["share_within_target"]
    return [
        f"Cierre real del mercado · {doc['since'][:10]} a {doc['until'][:10]}",
        f"Partidos con precio {doc['matches_with_price']}; con consenso del cierre real {doc['matches_with_real_close']}; a {doc['target_minutes']} min "
        f"o menos del inicio {doc['within_target']} ({'sin dato' if share is None else f'{share:.0%}'}; la meta es {TARGET_SHARE:.0%}: "
        f"{'cumple' if doc['meets_acceptance'] else 'no cumple'})",
        f"Mediana de minutos al inicio: cierre real {f(doc['real_median_minutes'])}; referencia previa {f(doc['prior_median_minutes'])}",
        f"Decisiones con ambos valores {doc['decisions_with_both']}; CLV medio contra la referencia previa {f(doc['clv_prior_mean'], 4)}, "
        f"contra el cierre real {f(doc['clv_real_mean'], 4)}; diferencia absoluta media {f(doc['mean_abs_difference'], 4)}",
    ]


__all__ = ["REFERENCE", "REFERENCE_PRIOR", "VERSION", "Row", "Stamped", "lines", "measure", "read", "rows", "run", "settle", "step", "store"]
