"""The price rule, a YARDSTICK in shadow (plan Intelligence 2026, INT-A10, IA-054): what the price ALONE would give.

THE RULE (``price-rule-v1``). A selection of the core markets (decision-v1's: ``CORE.markets()``) is TAKEN at the first moment, inside the
window decision-v1 decides in (from ``decision.HORIZON`` to ``decision.MIN_MINUTES`` before kick-off), at which its BEST price beats the
consensus without margin by decision-v1's value threshold - ``best_odds x p_fair - 1 >= decision.EV_MIN`` (``decision.ev_of``) - with a
price from at least ``decision.MIN_BOOKS`` books, not an outlier (``<= decision.MAX_PRICE_EDGE`` over the consensus, decision-v1's own
rule) and not older than ``decision.MAX_PRICE_AGE``. Every threshold is decision-v1's, imported, never copied. No model, no calibration, no
context: the price and nothing else.

THE MEASURE is its closing-line value, the system's one definition (``fbi.market.closing_value.clv``: ``odds x p_close - 1``), against the
LAST price observed before kick-off. Two readings of the market, named in every report (``source``):

    consensus  the long history: the moments are the captures (``market.market_consensus``, Shin; T-72 h ... T-3 h) and the close is the
               system's reference (``fbi.market.closing_reference``: the last Shin consensus before kick-off, about three hours before it);
    book       the odds book as of each moment (``fbi.decision.book_price``, plan INT-A06): the moments are the asks of the captures and of the
               book's refreshes, and the close is the answer in force at kick-off (``engine.Close``; about ten minutes before it since the
               refreshes began, 9 Nov 2026). It reads the bodies from RAW, so it is meant for the era of the refreshes.

A selection whose close was not observed AFTER the price taken has no CLV - the same snapshot would be measured against itself - and is
counted apart (``not_later``), as one with no close at all is (``no_close``, or the state of the book's last answer). The mean is given with
its 95 % interval from resampling whole matches and, apart, whole days (Bogotá), with a fixed seed (``fbi.models.metrics.block_bootstrap_ci``).
The plan's gate: a report needs ``MIN_SELECTIONS`` measured selections; with fewer it is «pendiente por muestra» (``PENDING``).

NEVER A PICK. The owner's rule is that value comes from the analysis, not from a bookmaker paying more. This is the reference the analysis is
measured against (E6, E4, the deliberation): it has no path to a pick, a decision or a page. Nothing but its own read-only command imports
it, no stage of decision-v2 is called here, and it writes nothing: its SQL reads fixtures and prices, never ``picks`` nor ``intel``
(``tests/unit/test_price_rule.py``, ``tests/unit/test_decision_v2_isolation.py``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import local_day
from fbi.decision import book_price
from fbi.decision.engine import BOOK, CONSENSUS, PRICE_SOURCES, Close
from fbi.decision.families import CORE
from fbi.intel import decision
from fbi.intel.decision import LINE_Q, Key
from fbi.market import closing_reference, closing_value
from fbi.models.metrics import block_bootstrap_ci
from fbi.storage.payload_store import PayloadStore

VERSION: Final = "price-rule-v1"
ROLE: Final = "reference"
"""What the rule is for: a yardstick. It is never a source of picks and nothing publishes it."""
MARKETS: Final = tuple(sorted(CORE.markets()))
MIN_SELECTIONS: Final = 300
"""The plan's gate (INT-A10): a report with at least this many measured selections; with fewer, «pendiente por muestra»."""
REPORT: Final = "report"
PENDING: Final = "pending_sample"
SEED: Final = 20261111
REPS: Final = 2000
LEVEL: Final = 0.95
BATCH: Final = 200
"""Matches per statement: every read goes by match (the consensus' index on (fixture_id, as_of), the book's primary keys)."""
SLACK: Final = 1e-9
"""The SQL pre-filter is wider than the rule by this much, so the rule (in Python) is the one that decides at the edges."""
NO_CLOSE: Final = "no_close"
NOT_LATER: Final = "not_later"
HORIZON_MINUTES: Final = decision.HORIZON.total_seconds() / 60
EV_BANDS: Final = ((decision.EV_MIN, 0.05), (0.05, 0.10), (0.10, decision.MAX_PRICE_EDGE))
"""Bands of the price's value at the take, for the report (the last one closes at the outlier limit)."""
LEAD_BANDS: Final = ((0.0, 3.0), (3.0, 6.0), (6.0, 12.0), (12.0, 24.0), (24.0, HORIZON_MINUTES / 60))
"""Bands of hours before kick-off at the take, for the report."""

SelectionKey = tuple[str, str, Decimal]
"""(market, selection, line): a selection of a match."""


# -- the rule (pure) --------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Quote:
    """One price of one selection as the market held it: the best odds, the consensus without margin (Shin), how many books, when the
    price was last confirmed and by what kind of reading."""

    best_odds: float
    p_fair: float
    n_bookmakers: int
    price_at: datetime
    confirmed_by: str = book_price.CAPTURE

    @property
    def price_ev(self) -> float:
        """The value of the best price at the consensus without margin: ``best_odds x p_fair - 1``."""
        return decision.ev_of(self.p_fair, self.best_odds)


def verdict(q: Quote, at: datetime) -> str | None:
    """None when the rule takes the price at ``at``; otherwise why not, in decision-v1's words where it has them (stage 3, then the
    value threshold). Pure."""
    if q.n_bookmakers < decision.MIN_BOOKS:
        return "thin_market"
    if q.price_ev > decision.MAX_PRICE_EDGE:
        return "price_outlier"
    if at - q.price_at > decision.MAX_PRICE_AGE:
        return "price_stale"
    if q.price_ev < decision.EV_MIN:
        return "price_below"
    return None


def in_window(at: datetime, kickoff_at: datetime) -> bool:
    """Whether ``at`` is inside the window decision-v1 decides in. Pure."""
    minutes = (kickoff_at - at).total_seconds() / 60
    return decision.MIN_MINUTES <= minutes <= HORIZON_MINUTES


Moment = tuple[datetime, Mapping[SelectionKey, Quote]]
"""A moment and the price of every selection the market held then."""


@dataclass(frozen=True, slots=True)
class Taken:
    """A selection the rule took: when, at which price, from which reading of the market."""

    key: Key
    kickoff_at: datetime
    at: datetime
    quote: Quote
    source: str

    @property
    def minutes_to_kickoff(self) -> float:
        return (self.kickoff_at - self.at).total_seconds() / 60


def first_taken(fixture_id: int, kickoff_at: datetime, moments: Iterable[Moment], *, source: str) -> dict[Key, Taken]:
    """Every selection of the match the rule takes, at the first moment it does (in time order; nothing after a moment is read to judge
    it). Pure."""
    out: dict[Key, Taken] = {}
    for at, quotes in sorted(moments, key=lambda m: m[0]):
        if not in_window(at, kickoff_at):
            continue
        for (market, selection, line), q in sorted(quotes.items()):
            key = (fixture_id, market, selection, line.quantize(LINE_Q))
            if market in MARKETS and key not in out and verdict(q, at) is None:
                out[key] = Taken(key, kickoff_at, at, q, source)
    return out


@dataclass(frozen=True, slots=True)
class Closing:
    """The last price observed of a selection before kick-off: its probability without margin, when it was observed and what it is."""

    p_fair: float
    observed_at: datetime
    reference: str


def from_reference(c: closing_reference.Close) -> Closing:
    """The system's reference of the close (the last Shin consensus before kick-off)."""
    return Closing(c.p_fair, c.as_of, closing_reference.REFERENCE)


def from_book(c: Close) -> Closing:
    """The book's last answer before kick-off (plan INT-A06)."""
    return Closing(c.p_fair, c.checked_at, c.version)


@dataclass(frozen=True, slots=True)
class Measured:
    """A taken selection and its CLV against the close; ``missing`` says why there is none."""

    taken: Taken
    close: Closing | None
    clv: float | None
    missing: str | None

    @property
    def close_minutes_to_kickoff(self) -> float | None:
        return None if self.close is None else (self.taken.kickoff_at - self.close.observed_at).total_seconds() / 60


def measure(t: Taken, close: Closing | None, *, missing: str = NO_CLOSE) -> Measured:
    """The CLV of a taken price (``closing_value.clv``), only against a close observed after it. Pure."""
    if close is None:
        return Measured(t, None, None, missing)
    if close.observed_at <= t.quote.price_at:
        return Measured(t, close, None, NOT_LATER)
    return Measured(t, close, closing_value.clv(t.quote.best_odds, close.p_fair), None)


# -- the report (pure) ------------------------------------------------------------------------------------------------------------------

def _round(x: float | None, places: int = 6) -> float | None:
    return None if x is None else round(x, places)


def spread(xs: Sequence[float]) -> dict[str, Any]:
    """n, mean and the 10th, 50th and 90th percentiles (nearest rank), None without values. Pure."""
    s = sorted(xs)
    if not s:
        return {"n": 0, "mean": None, "p10": None, "p50": None, "p90": None}

    def q(f: float) -> float | None:
        return _round(s[min(len(s) - 1, int(f * len(s)))])

    return {"n": len(s), "mean": _round(sum(s) / len(s)), "p10": q(0.1), "p50": q(0.5), "p90": q(0.9)}


def interval(values: Sequence[float], blocks: Sequence[object]) -> dict[str, Any]:
    """The mean and its 95 % interval from resampling whole blocks (matches or days) with the fixed seed. Pure and deterministic."""
    if not values:
        return {"mean": None, "low": None, "high": None, "blocks": 0}
    mean, low, high, n = block_bootstrap_ci(list(values), list(blocks), draws=REPS, level=LEVEL, seed=SEED)
    return {"mean": _round(mean), "low": _round(low), "high": _round(high), "blocks": n}


def _band(x: float, bands: Sequence[tuple[float, float]]) -> str:
    for lo, hi in bands:
        if lo <= x < hi or (x == hi and (lo, hi) == bands[-1]):
            return f"{lo:g}-{hi:g}"
    return "other"


def _by(ok: Sequence[Measured], label: Callable[[Measured], object]) -> dict[str, Any]:
    groups: dict[str, list[Measured]] = defaultdict(list)
    for m in ok:
        groups[str(label(m))].append(m)
    return {g: {"selections": len(ms), "matches": len({m.taken.key[0] for m in ms}),
                **interval([m.clv for m in ms if m.clv is not None], [m.taken.key[0] for m in ms])}
            for g, ms in sorted(groups.items())}


def rule() -> dict[str, Any]:
    """The rule's parameters as a report states them (all decision-v1's)."""
    return {"version": VERSION, "markets": list(MARKETS), "ev_min": decision.EV_MIN, "max_price_edge": decision.MAX_PRICE_EDGE,
            "min_books": decision.MIN_BOOKS, "max_price_age_minutes": decision.MAX_PRICE_AGE.total_seconds() / 60,
            "window_minutes": [decision.MIN_MINUTES, HORIZON_MINUTES], "taken": "the first moment in the window"}


def gate(measured: int) -> dict[str, Any]:
    """The plan's gate: a report from ``MIN_SELECTIONS`` measured selections, «pendiente por muestra» below. Pure."""
    return {"min_selections": MIN_SELECTIONS, "selections": measured, "verdict": REPORT if measured >= MIN_SELECTIONS else PENDING}


def summarise(measured: Sequence[Measured], *, source: str, since: datetime, until: datetime,
              population: Mapping[str, int]) -> dict[str, Any]:
    """The report of the rule over a window of kick-offs: what it took, its CLV with the intervals by match and by day, its parts (the
    price's value at the take, the drift of the consensus to the close) and its distribution by market, value band and lead. Pure."""
    ok = [m for m in measured if m.clv is not None]
    clvs = [m.clv for m in ok if m.clv is not None]
    matches = [m.taken.key[0] for m in ok]
    days = [local_day(m.taken.kickoff_at).isoformat() for m in ok]
    return {
        "version": VERSION, "source": source, "role": ROLE, "kickoff": {"from": since.isoformat(), "to": until.isoformat()},
        "rule": rule(), "population": dict(population),
        "taken": {"selections": len(measured), "matches": len({m.taken.key[0] for m in measured}),
                  "by_market": dict(sorted(Counter(m.taken.key[1] for m in measured).items())),
                  "confirmed_by": dict(sorted(Counter(m.taken.quote.confirmed_by for m in measured).items())),
                  "minutes_to_kickoff": spread([m.taken.minutes_to_kickoff for m in measured])},
        "measured": {"selections": len(ok), "matches": len(set(matches)), "days": len(set(days)),
                     "without_clv": dict(sorted(Counter(str(m.missing) for m in measured if m.clv is None).items()))},
        "clv": {"by_match": interval(clvs, matches), "by_day": interval(clvs, days), "median": spread(clvs)["p50"],
                "positive": _round(sum(1 for c in clvs if c > 0) / len(clvs), 4) if clvs else None,
                "seed": SEED, "reps": REPS, "level": LEVEL, "definition": closing_value.VERSION},
        "price_ev_at_take": spread([m.taken.quote.price_ev for m in ok]),
        "p_drift_pp": spread([(m.close.p_fair - m.taken.quote.p_fair) * 100 for m in ok if m.close is not None]),
        "close": {"reference": dict(sorted(Counter(m.close.reference for m in ok if m.close is not None).items())),
                  "minutes_to_kickoff": spread([x for m in ok if (x := m.close_minutes_to_kickoff) is not None]),
                  "minutes_after_take": spread([(m.close.observed_at - m.taken.quote.price_at).total_seconds() / 60
                                                for m in ok if m.close is not None])},
        "by_market": _by(ok, lambda m: m.taken.key[1]),
        "by_price_ev": _by(ok, lambda m: _band(m.taken.quote.price_ev, EV_BANDS)),
        "by_lead_hours": _by(ok, lambda m: _band(m.taken.minutes_to_kickoff / 60, LEAD_BANDS)),
        "gate": gate(len(ok)),
    }


# -- reading the market (read-only) -----------------------------------------------------------------------------------------------------

FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at FROM core.fixtures f
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s AND NOT (COALESCE(f.status_short, '') = ANY(%(bad)s))
 ORDER BY f.id
"""
"""The matches of the window that were to be played (decision-v1's ``BAD_STATUS`` left out: postponed, cancelled, abandoned...)."""

WINDOW: Final = """
  FROM unnest(%(ids)s::bigint[], %(kickoffs)s::timestamptz[]) AS f(id, kickoff_at)
  JOIN LATERAL (SELECT c.fixture_id, c.market_key, c.selection, c.line, c.as_of, c.best_odds, c.p_fair, c.n_bookmakers
                  FROM market.market_consensus c
                 WHERE c.fixture_id = f.id AND c.as_of >= f.kickoff_at - %(horizon)s AND c.as_of <= f.kickoff_at - %(lead)s
                   AND c.devig_method = 'shin' AND c.market_key = ANY(%(markets)s)) m ON true
"""
"""The Shin consensus of the core markets captured inside each match's window: a range of the index on (fixture_id, as_of) per match."""
SEEN_SQL: Final = f"""
SELECT m.fixture_id, count(DISTINCT (m.market_key, m.selection, m.line)) AS selections, count(DISTINCT m.as_of) AS moments
{WINDOW} GROUP BY m.fixture_id
"""
"""How many selections and captures of each match the window holds (the population the rule chose from)."""
PRICES_SQL: Final = f"""
SELECT m.fixture_id, m.market_key, m.selection, m.line, m.as_of, m.best_odds::float8 AS best_odds, m.p_fair::float8 AS p_fair,
       m.n_bookmakers
{WINDOW} WHERE m.n_bookmakers >= %(min_books)s AND m.best_odds * m.p_fair - 1 BETWEEN %(ev_low)s AND %(ev_high)s
 ORDER BY m.fixture_id, m.as_of, m.market_key, m.selection, m.line
"""
"""The captured prices the rule could take - a pre-filter a hair wider than the rule (``SLACK``), which ``verdict`` applies exactly."""


def _batches[T](items: Sequence[T], size: int = BATCH) -> list[Sequence[T]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def read_fixtures(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> dict[int, datetime]:
    """fixture id -> kick-off, for the matches of the window that were to be played."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"since": since, "until": until, "bad": sorted(decision.BAD_STATUS)})
        return {int(r["id"]): r["kickoff_at"] for r in cur.fetchall()}


def _params(chunk: Sequence[tuple[int, datetime]]) -> dict[str, Any]:
    return {"ids": [f for f, _ in chunk], "kickoffs": [k for _, k in chunk], "markets": list(MARKETS), "horizon": decision.HORIZON,
            "lead": timedelta(minutes=decision.MIN_MINUTES), "min_books": decision.MIN_BOOKS, "ev_low": decision.EV_MIN - SLACK,
            "ev_high": decision.MAX_PRICE_EDGE + SLACK}


def consensus_moments(rows: Iterable[Mapping[str, Any]]) -> dict[int, list[Moment]]:
    """The rows of ``PRICES_SQL`` as the moments of each match (one per capture). Pure."""
    found: dict[int, dict[datetime, dict[SelectionKey, Quote]]] = defaultdict(dict)
    for r in rows:
        moment = found[int(r["fixture_id"])].setdefault(r["as_of"], {})
        moment[(str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"])).quantize(LINE_Q))] = Quote(
            float(r["best_odds"]), float(r["p_fair"]), int(r["n_bookmakers"]), r["as_of"], book_price.CAPTURE)
    return {f: sorted(ms.items(), key=lambda m: m[0]) for f, ms in found.items()}


def measure_consensus(conn: psycopg.Connection[Any], fixtures: Mapping[int, datetime]) -> tuple[list[Measured], dict[str, int]]:
    """The long history: the rule over the captures of these matches and its CLV against the system's close. Read-only."""
    ordered = sorted(fixtures.items())
    seen = {"matches_with_price": 0, "selections_with_price": 0, "moments": 0}
    taken: dict[Key, Taken] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for chunk in _batches(ordered):
            params = _params(chunk)
            cur.execute(SEEN_SQL, params)
            for r in cur.fetchall():
                seen["matches_with_price"] += 1
                seen["selections_with_price"] += int(r["selections"])
                seen["moments"] += int(r["moments"])
            cur.execute(PRICES_SQL, params)
            for fid, moments in consensus_moments(cur.fetchall()).items():
                taken |= first_taken(fid, fixtures[fid], moments, source=CONSENSUS)
    keys = sorted(taken)
    closes = closing_reference.closing_probabilities(conn, keys)
    measured = [measure(taken[k], None if (c := closes.get(k)) is None else from_reference(c)) for k in keys]
    return measured, {"matches": len(fixtures), **seen}


def book_moments(reader: book_price.BookReader, fixture_id: int) -> list[Moment]:
    """The answer the book held of the match at each of its asks inside the window, priced (a withdrawn, unreadable or never-asked answer
    prices nothing). Pure over the reader (it reads the bodies from RAW once each)."""
    if fixture_id not in reader.fixtures:
        return []
    kickoff_at = reader.fixtures[fixture_id][1]
    out: list[Moment] = []
    for at in sorted({a.asked_at for a in reader.asks.get(fixture_id, ())}):
        if not in_window(at, kickoff_at):
            continue
        answer = reader.answer_at(fixture_id, at)
        if answer.state != "priced" or answer.checked_at is None:
            continue
        checked_at, kind = answer.checked_at, answer.confirmed_by or book_price.CAPTURE
        out.append((at, {k: Quote(q.best_odds, q.p_fair, q.n_bookmakers, checked_at, kind) for k, q in answer.prices.items()}))
    return out


def measure_book(reader: book_price.BookReader) -> tuple[list[Measured], dict[str, int]]:
    """The rule over the book's answers of the reader's matches and its CLV against the book's last answer before kick-off. Pure over the
    reader."""
    measured: list[Measured] = []
    seen = {"matches_with_price": 0, "selections_with_price": 0, "moments": 0}
    for fid in sorted(reader.fixtures):
        kickoff_at = reader.fixtures[fid][1]
        moments = book_moments(reader, fid)
        if moments:
            seen["matches_with_price"] += 1
            seen["selections_with_price"] += len({k for _, qs in moments for k in qs})
            seen["moments"] += len(moments)
        taken = first_taken(fid, kickoff_at, moments, source=BOOK)
        if not taken:
            continue
        last = reader.close(fid)
        closes = book_price.close_of(last, kickoff_at)
        why = book_price.NOT_QUOTED if last.state == "priced" else last.state
        for k in sorted(taken):
            c = closes.get(k[1:])
            measured.append(measure(taken[k], None if c is None else from_book(c), missing=why))
    return measured, seen


def report(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, source: str = CONSENSUS,
           store: PayloadStore | None = None) -> dict[str, Any]:
    """The rule's report over the matches that kicked off in ``[since, until)``, read from the captures (``consensus``) or from the odds
    book (``book``, which reads the answers' bodies from the RAW ``store``). Read-only: nothing is written."""
    if source not in PRICE_SOURCES:
        raise ValueError(f"source must be one of {PRICE_SOURCES}")
    if source == BOOK and store is None:
        raise ValueError("the book's answers are read from the RAW store: give the store")
    fixtures = read_fixtures(conn, since=since, until=until)
    if source == CONSENSUS:
        found, population = measure_consensus(conn, fixtures)
        return summarise(found, source=source, since=since, until=until, population=population)
    measured: list[Measured] = []
    seen: Counter[str] = Counter()
    problems: list[str] = []
    bodies = unreadable = 0
    for chunk in _batches(sorted(fixtures), size=BATCH // 4):
        reader = book_price.read(conn, store, chunk)
        batch, counts = measure_book(reader)
        measured += batch
        seen.update(counts)
        bodies += len(reader.bodies)
        unreadable += sum(1 for v in reader.bodies.values() if v is None)
        problems += reader.problems[: max(0, 5 - len(problems))]
    out = summarise(measured, source=source, since=since, until=until, population={"matches": len(fixtures), **seen})
    out["reader"] = {"version": book_price.VERSION, "bodies_read": bodies, "unreadable": unreadable, "problems": problems}
    return out
