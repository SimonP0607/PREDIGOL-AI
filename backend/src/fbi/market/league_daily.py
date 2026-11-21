"""The market's margin and dispersion by competition, market and day (plan PM, PM-05-07; ``FBI_MARKET_LEAGUE_STATS``, off by default).

A MEASURE, NOT A FORECAST: nothing here prices, picks, de-vigs for a pick or decides anything. The rows say how wide the houses' margins
are in a competition and how far their prices lie apart, so the owner can tell which competitions have tight, consistent prices.

What is read: ``market.final_prematch_odds`` - the provider's last pre-match price of each house, read after kick-off (``fbi.odds.
final_prematch``), the nearest PrediGol has to a closing line. Of each finished match, three markets at one line each, the ones whose
selections are exclusive and exhaustive (``fbi.market.consensus.EXCLUSIVE``): ``1X2`` and ``BTTS`` at 0 and ``OU`` at 2.50 (the line
every house quotes; other lines are quoted by fewer houses and would compare different sets).

What is measured, by UTC day of kick-off, competition (``core.competitions.id``), market and line:

* the **margin** of each house's complete book: ``sum(1 / price) - 1`` over the selections of the market. A book that lacks a selection is
  left out, never guessed; so is a book without a margin (a stale or broken quote, as ``fbi.market.consensus`` does) and one with an
  implausible margin (``MAX_MARGIN``: a two-way book at more than 25 % is a pairing of two different bets, ``MAX_TWO_WAY_BOOK``). Of the
  day's books: mean, median and the 10th and 90th percentiles (linear interpolation, as PostgreSQL's ``percentile_cont``);
* the **dispersion** of each match with two or more complete books: the population standard deviation across houses of each
  selection's proportional fair probability (``(1 / price) / sum(1 / price)``), averaged over the selections - the definition of
  ``market.market_consensus.dispersion``. Of the day's matches: median and mean;
* the matches, the books and the median of houses per match.

When it runs: inside the nightly process of the availability matrix (``scripts.availability_refresh``, 08:00 UTC, its own process with a
512 MiB cap, away from the copies of 03:50-05:00, the statistics pass of 07:20 and the Monday 06:00 jobs), after its pass, with its own
ledger row (``market_league_stats``). Each pass measures again the last ``RECENT_DAYS`` days (the provider's last prices of a match are
read up to seven days after it) and fills the days since ``WINDOW_START`` that have no row yet, at most ``MAX_DAYS`` a pass, one day per
transaction, inside ``MAX_SECONDS``. Python holds one day of prices at a time (some ten thousand rows). Idempotent: a second pass over the
same prices changes nothing but ``measured_at``. Writes only ``market.league_daily_stats``; never deletes a row.
"""

from __future__ import annotations

import math
import os
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg

SWITCH: Final = "FBI_MARKET_LEAGUE_STATS"
JOB: Final = "market_league_stats"
METHOD_VERSION: Final = "league-margin-v1"
SOURCE: Final = "final_prematch"
LOCK: Final = 0x0C0F17

MARKETS: Final[tuple[tuple[str, Decimal, tuple[str, ...]], ...]] = (
    ("1X2", Decimal("0"), ("Home", "Draw", "Away")),
    ("BTTS", Decimal("0"), ("Yes", "No")),
    ("OU", Decimal("2.5"), ("Over", "Under")),
)
"""(market_key, line, selections): exclusive and exhaustive selections at one line (``fbi.market.consensus.EXCLUSIVE``)."""
MAX_TWO_WAY_BOOK: Final = 1.25
"""As ``fbi.market.consensus.MAX_TWO_WAY_BOOK``: the most margin a two-way book can plausibly carry."""
MAX_MARGIN: Final[Mapping[int, float]] = {2: MAX_TWO_WAY_BOOK - 1, 3: 0.40}
"""The largest margin believed, by number of selections; above it the book is left out (counted in ``Report.rejected``)."""
WINDOW_START: Final = date(2026, 10, 4)
"""The first day of ``market.final_prematch_odds`` (measured 20-nov-2026: 4,626 matches from 4-Oct-2026)."""
RECENT_DAYS: Final = 8
"""Measured again every pass: the provider keeps a match's pre-match prices seven days and they are read after it."""
MAX_DAYS: Final = 60
"""Days with no row yet filled in one pass (the first pass fills the window since ``WINDOW_START``)."""
MAX_SECONDS: Final = 4 * 60
STATEMENT_TIMEOUT: Final = "120s"


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on (``1``, ``on``, ``true``, ``yes``): born off (plan PM: everything new is born off); it is
    turned on with the audited kit (``predigolctl up``) at PM-15-03 or when the owner decides."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


# ── pure measures ──────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Price:
    fixture_id: int
    competition_id: int
    day: date
    bookmaker_id: int
    market_key: str
    line: Decimal
    selection: str
    odds: Decimal


@dataclass(frozen=True, slots=True)
class DayStat:
    """One row of ``market.league_daily_stats``."""

    day: date
    competition_id: int
    market_key: str
    line: Decimal
    n_fixtures: int
    n_books: int
    books_median: float
    margin_mean: float
    margin_median: float
    margin_p10: float
    margin_p90: float
    dispersion_median: float | None
    dispersion_mean: float | None
    n_dispersion: int


def book_margin(prices: Mapping[str, Decimal], selections: Sequence[str]) -> float | None:
    """The margin of one house's book: ``sum(1 / price) - 1``; ``None`` when a selection is missing or the margin is not believable."""
    if set(prices) != set(selections):
        return None
    margin = sum(1 / float(prices[s]) for s in selections) - 1
    if margin <= 0 or margin > MAX_MARGIN.get(len(selections), 0.40):
        return None
    return margin


def fair(prices: Mapping[str, Decimal], selections: Sequence[str]) -> dict[str, float]:
    """The proportional fair probability of each selection of a complete book."""
    implied = {s: 1 / float(prices[s]) for s in selections}
    total = sum(implied.values())
    return {s: p / total for s, p in implied.items()}


def match_dispersion(books: Sequence[Mapping[str, Decimal]], selections: Sequence[str]) -> float | None:
    """Of the complete books of one match: the population standard deviation across houses of each selection's fair probability,
    averaged over the selections; ``None`` with fewer than two books."""
    if len(books) < 2:
        return None
    fairs = [fair(b, selections) for b in books]
    return statistics.fmean(statistics.pstdev([f[s] for f in fairs]) for s in selections)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear interpolation between the closest ranks, as PostgreSQL's ``percentile_cont``."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("no values")
    pos = q * (len(ordered) - 1)
    low = math.floor(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


@dataclass
class Summary:
    stats: list[DayStat] = field(default_factory=list)
    rejected: int = 0
    """Books left out for a missing selection or a margin that is not believable."""


def summarise(prices: Iterable[Price]) -> Summary:
    """The rows of ``market.league_daily_stats`` for these prices (one or more days, any competitions)."""
    selections_of = {(m, line): sels for m, line, sels in MARKETS}
    books: dict[tuple[date, int, str, Decimal], dict[int, dict[int, dict[str, Decimal]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict)))
    for p in prices:
        key = (p.market_key, p.line)
        if key not in selections_of or p.selection not in selections_of[key]:
            continue
        books[(p.day, p.competition_id, p.market_key, p.line)][p.fixture_id][p.bookmaker_id][p.selection] = p.odds
    out = Summary()
    for (day, competition_id, market_key, line), fixtures in sorted(books.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        selections = selections_of[(market_key, line)]
        margins: list[float] = []
        per_match: list[int] = []
        dispersions: list[float] = []
        for by_book in fixtures.values():
            complete = []
            for book in by_book.values():
                m = book_margin(book, selections)
                if m is None:
                    out.rejected += 1
                    continue
                margins.append(m)
                complete.append(book)
            if not complete:
                continue
            per_match.append(len(complete))
            d = match_dispersion(complete, selections)
            if d is not None:
                dispersions.append(d)
        if not per_match:
            continue
        out.stats.append(DayStat(
            day=day, competition_id=competition_id, market_key=market_key, line=line, n_fixtures=len(per_match),
            n_books=len(margins), books_median=float(statistics.median(per_match)),
            margin_mean=statistics.fmean(margins), margin_median=percentile(margins, 0.5),
            margin_p10=percentile(margins, 0.1), margin_p90=percentile(margins, 0.9),
            dispersion_median=percentile(dispersions, 0.5) if dispersions else None,
            dispersion_mean=statistics.fmean(dispersions) if dispersions else None,
            n_dispersion=len(dispersions),
        ))
    return out


def days_due(today: date, measured: Iterable[date], *, start: date = WINDOW_START) -> list[date]:
    """The days a pass measures: the last ``RECENT_DAYS`` before today (always), then the oldest days since ``start`` without a row,
    at most ``MAX_DAYS`` in all. Today is never measured: its matches are not over."""
    recent = [today - timedelta(days=n) for n in range(1, RECENT_DAYS + 1) if today - timedelta(days=n) >= start]
    have = set(measured)
    missing = [start + timedelta(days=n) for n in range((today - start).days)]
    missing = [d for d in missing if d not in have and d not in recent]
    return (sorted(recent, reverse=True) + missing)[:max(MAX_DAYS, len(recent))]


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

_MARKET_FILTER: Final = " OR ".join(f"(o.market_key = '{m}' AND o.line = {line})" for m, line, _ in MARKETS)

PRICES_SQL: Final = f"""
SELECT o.fixture_id, cs.competition_id, o.bookmaker_id, o.market_key, o.line, o.selection, o.odds_decimal
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN market.final_prematch_odds o ON o.fixture_id = f.id
 WHERE f.kickoff_at >= (%(day)s::date)::timestamp AT TIME ZONE 'UTC'
   AND f.kickoff_at < (%(day)s::date + 1)::timestamp AT TIME ZONE 'UTC'
   AND f.status_group = 'finished'
   AND ({_MARKET_FILTER})
"""

MEASURED_SQL: Final = "SELECT DISTINCT day FROM market.league_daily_stats WHERE day >= %s AND source = %s"

UPSERT_SQL: Final = """
INSERT INTO market.league_daily_stats (day, competition_id, market_key, line, n_fixtures, n_books, books_median, margin_mean,
       margin_median, margin_p10, margin_p90, dispersion_median, dispersion_mean, n_dispersion, source, method_version, measured_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (day, competition_id, market_key, line) DO UPDATE SET
       n_fixtures = EXCLUDED.n_fixtures, n_books = EXCLUDED.n_books, books_median = EXCLUDED.books_median,
       margin_mean = EXCLUDED.margin_mean, margin_median = EXCLUDED.margin_median, margin_p10 = EXCLUDED.margin_p10,
       margin_p90 = EXCLUDED.margin_p90, dispersion_median = EXCLUDED.dispersion_median, dispersion_mean = EXCLUDED.dispersion_mean,
       n_dispersion = EXCLUDED.n_dispersion, source = EXCLUDED.source, method_version = EXCLUDED.method_version,
       measured_at = EXCLUDED.measured_at
"""


@dataclass
class Report:
    days: int = 0
    rows: int = 0
    prices: int = 0
    rejected: int = 0
    stopped: str = ""
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"days": self.days, "rows": self.rows, "prices": self.prices, "rejected": self.rejected, "stopped": self.stopped,
                "method_version": METHOD_VERSION}


def _r(x: float | None, places: int) -> Decimal | None:
    return None if x is None else Decimal(str(round(x, places)))


def measure_day(conn: psycopg.Connection, day: date, *, at: datetime) -> tuple[int, int, int]:
    """Measure one day and write its rows (the caller commits). Returns (prices read, rows written, books rejected)."""
    rows = conn.execute(PRICES_SQL, {"day": day}).fetchall()
    prices = [Price(fixture_id=r[0], competition_id=r[1], day=day, bookmaker_id=r[2], market_key=r[3], line=Decimal(r[4]),
                    selection=r[5], odds=Decimal(r[6])) for r in rows]
    summary = summarise(prices)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, [
            (s.day, s.competition_id, s.market_key, s.line, s.n_fixtures, s.n_books, _r(s.books_median, 1),
             _r(s.margin_mean, 5), _r(s.margin_median, 5), _r(s.margin_p10, 5), _r(s.margin_p90, 5),
             _r(s.dispersion_median, 6), _r(s.dispersion_mean, 6), s.n_dispersion, SOURCE, METHOD_VERSION, at)
            for s in summary.stats])
    return len(prices), len(summary.stats), summary.rejected


def run_pass(conn: psycopg.Connection, *, now: datetime, days: Sequence[date] | None = None,
             deadline: float | None = None) -> Report:
    """One pass: the days due (or ``days``), one transaction each, under an advisory lock, inside ``MAX_SECONDS`` and ``deadline``
    (a ``time.monotonic()`` instant the process must not pass)."""
    report = Report()
    started = time.monotonic()
    stop_at = started + MAX_SECONDS if deadline is None else min(started + MAX_SECONDS, deadline)
    conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
    got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
    if not got or not got[0]:
        conn.rollback()
        report.stopped = "otro_pase_en_curso"
        return report
    try:
        if days is None:
            measured = [r[0] for r in conn.execute(MEASURED_SQL, (WINDOW_START, SOURCE)).fetchall()]
            due = days_due(now.date(), measured)
        else:
            due = list(days)
        conn.commit()
        for day in due:
            if time.monotonic() >= stop_at:
                report.stopped = "presupuesto_de_tiempo"
                break
            try:
                n_prices, n_rows, rejected = measure_day(conn, day, at=now)
                conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                report.errors.append(f"{day.isoformat()}: {type(exc).__name__}: {exc}"[:300])
                continue
            report.days += 1
            report.prices += n_prices
            report.rows += n_rows
            report.rejected += rejected
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        conn.commit()
    return report


READ_SQL: Final = """
SELECT s.competition_id, c.provider_league_id, c.name, s.market_key, s.line, sum(s.n_fixtures) AS fixtures, sum(s.n_books) AS books,
       round(sum(s.margin_mean * s.n_books) / sum(s.n_books), 5) AS margin_mean,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY s.margin_median)::numeric, 5) AS margin_median_of_days,
       round(sum(s.dispersion_mean * s.n_dispersion) / nullif(sum(s.n_dispersion), 0), 6) AS dispersion_mean,
       count(*) AS days, max(s.measured_at) AS measured_at
  FROM market.league_daily_stats s
  LEFT JOIN core.competitions c ON c.id = s.competition_id
 WHERE s.day >= %(since)s AND s.day < %(until)s AND (%(competition)s::bigint IS NULL OR c.provider_league_id = %(competition)s)
 GROUP BY 1, 2, 3, 4, 5
 ORDER BY sum(s.n_fixtures) DESC, 2, 4
"""
"""The owner's reading (``scripts.market_league_stats show``): by competition and market over a span of days, the mean margin weighted
by books, the median of the daily medians and the mean dispersion weighted by matches."""


def read(conn: psycopg.Connection, *, since: date, until: date, competition: int | None = None) -> list[dict[str, Any]]:
    cur = conn.execute(READ_SQL, {"since": since, "until": until, "competition": competition})
    names = [d.name for d in cur.description or ()]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
