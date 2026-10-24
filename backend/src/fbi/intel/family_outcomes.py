"""WHAT BECAME OF A FAMILY'S DECISION (plan F11) - ``outcome-fam-v1``: the result of its selection, the profit at the decision's own price, and its
value against the closing line. The second step of the cycle of a family in shadow (decision, settlement, post-mortem, memory).

``fbi.intel.outcomes`` settles the decisions of the pipeline through ``picks.pick_results``: a pick has a result because the settlement of the
picks gave it one. A family's decision has no pick (``fbi.intel.family_decision``), so nothing settled it, and this module is the settlement it
has. It writes the same table, ``intel.decision_outcomes``, with the same columns and the same meaning, under its own version:

    result       the status of the selection on the counts of the finished match, by the rule of the market that grades it (``fbi.market.rules``,
                 through ``fbi.picks.count_settlement.settle_numbers``: the arithmetic that will settle a pick on a family the day there is one)
    profit       win: odds - 1, half win: (odds - 1) / 2, push / void: 0, half loss: -1/2, loss: -1, per unit (``fbi.intel.outcomes.profit_per_unit``,
                 the only place that table is written); the staked profit is the stake of the decision times that, and a family's stake is zero
    CLV          ``odds x p_close - 1`` (``fbi.market.closing_value``, ``clv-v1``, the one definition in the system)

TWO THINGS THAT ARE NOT THE PIPELINE'S, ON PURPOSE.

* The counts. A decision of the pipeline is settled from the pick's result. A family's is settled from the counts of the match - goals by half,
  corners, cards - read through the one door the families read outcomes through (``fbi.families.history``, by ``fbi.families.score.load_counts``):
  a match comes through only once its result is known and, for the cards, only when the team statistics that give them are there. The decision
  waits ``WAIT`` after the kick-off, as the scoreboard does (the statistics of the cards settle some 26 hours after the match), and a count that is
  unknown leaves the decision UNSETTLED - it is tried again on the next pass, and never read as a loss.
* The closing line. ``market.market_consensus`` holds a Shin consensus for the markets the pipeline covers; the families' markets are priced
  as the decision priced them, by ``fbi.intel.family_decision.price``: the mean over the COMPLETE books of their own de-vigged probabilities, read
  from the quotes in force at the kick-off (nothing captured at or after it), three books or more. The decision and its close are the same
  arithmetic on two moments, so the value measured is the value of the price and not of the method. ``close_as_of`` is the last time the odds of the
  match were read before the kick-off, and ``close_minutes_to_ko`` says how near the close was: as everywhere in the system, a reference that has
  not been shown to BE the closing line.

Written once: ``intel.decision_outcomes`` is append-only, and a result corrected later by the provider would be a new decision's business. Zero
requests to the provider, zero AI: it reads the database.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.families import score, versus
from fbi.intel import family_decision as fd
from fbi.intel.outcomes import profit_per_unit
from fbi.market import closing_value
from fbi.market.rules import RULES_BY_MEASURE
from fbi.picks.count_settlement import settle_numbers
from fbi.picks.settlement import Status

log = structlog.get_logger(__name__)

VERSION: Final = "outcome-fam-v1"
"""The version of the outcomes of the families: the ``version`` of their rows in ``intel.decision_outcomes``."""
DECISION_VERSION: Final = fd.VERSION
WAIT: Final = timedelta(hours=30)
"""How long after the kick-off a decision waits to be settled: the statistics of the cards settle some 26 hours after the match, and a count read
before that can be short (the wait of the scoreboard, ``fbi.families.score.score``)."""
LOOKBACK: Final = timedelta(days=30)
"""How far back the kick-offs of the decisions that are looked for go. A decision whose count is still unknown after this long is left unsettled."""
BATCH: Final = 20000
"""The most decisions one pass settles."""
CHUNK: Final = 100
"""Matches whose closing quotes are read at a time."""
ERRORS_KEPT: Final = 5
CLOSE_WINDOW: Final = fd.QUOTE_WINDOW
"""How long before the kick-off a price can have been first seen and still be the one in force at the close."""
CLOSE_MIN_BOOKS: Final = versus.MIN_BOOKS
"""Complete books a closing consensus needs: the same three that a family needs to be priced at all."""

TODO_SQL: Final = """
SELECT d.id, d.fixture_id, d.market_key, d.selection, d.line, d.odds, d.stake_units, d.kickoff_at
  FROM intel.decisions d
  LEFT JOIN intel.decision_outcomes o ON o.decision_id = d.id
 WHERE d.decision_version = %(version)s AND d.pick_id IS NULL AND o.decision_id IS NULL AND d.odds IS NOT NULL
   AND d.known_at >= %(since)s - %(horizon)s::interval AND d.kickoff_at >= %(since)s AND d.kickoff_at <= %(until)s
 ORDER BY d.kickoff_at, d.id
 LIMIT %(limit)s
"""
"""The decisions of the families that have no outcome yet, with a kick-off in the window (never one of the pipeline's: that is its own query)."""

CLOSE_QUOTES_SQL: Final = """
SELECT DISTINCT ON (q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line)
       q.fixture_id, q.bookmaker_id, d.market_key, d.kind, q.selection, q.line, q.odds_decimal, q.captured_at
  FROM market.odds_quotes q
  JOIN core.fixtures x ON x.id = q.fixture_id
  JOIN market.market_definitions d ON d.id = q.definition_id
 WHERE q.fixture_id = ANY(%(fixtures)s::bigint[]) AND d.scope = 'prematch' AND d.market_key = ANY(%(keys)s::text[])
   AND d.kind = ANY(%(kinds)s::text[]) AND q.captured_at >= x.kickoff_at - %(window)s::interval AND q.captured_at < x.kickoff_at
 ORDER BY q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line, q.captured_at DESC
"""
"""The last quote in force of every selection at every book at the kick-off of its match: nothing captured at or after it is read."""

CLOSE_READ_SQL: Final = """
SELECT m.fixture_id, max(m.as_of) AS observed_at
  FROM market.market_consensus m JOIN core.fixtures x ON x.id = m.fixture_id
 WHERE m.fixture_id = ANY(%(fixtures)s::bigint[]) AND m.as_of < x.kickoff_at AND m.as_of >= x.kickoff_at - %(window)s::interval
 GROUP BY m.fixture_id
"""
"""The last time the odds of each match were read before it kicked off."""

INSERT_SQL: Final = (
    "INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, close_p_fair, close_odds, close_as_of, "
    "close_minutes_to_ko, clv, version, computed_at) VALUES (%(id)s, %(at)s, %(status)s, %(flat)s, %(staked)s, %(p)s, %(odds)s, %(as_of)s, "
    "%(minutes)s, %(clv)s, %(version)s, %(at)s) ON CONFLICT (decision_id) DO NOTHING")

UNIT_Q: Final = Decimal("0.0001")
P_Q: Final = Decimal("0.000001")
ODDS_Q: Final = Decimal("0.001")


@dataclass(frozen=True, slots=True)
class Open:
    """A decision of a family that has no outcome yet."""

    id: int
    fixture_id: int
    key: str
    selection: str
    line: Decimal
    odds: Decimal
    stake: Decimal
    kickoff_at: datetime


@dataclass(frozen=True, slots=True)
class Outcome:
    """What became of a decision, as ``intel.decision_outcomes`` holds it."""

    decision_id: int
    result_status: str
    profit_flat: Decimal
    profit_staked: Decimal
    close_p_fair: Decimal | None
    close_odds: Decimal | None
    close_as_of: datetime | None
    close_minutes_to_ko: int | None
    clv: Decimal | None


def outcome(row: Open, status: Status, close: fd.Priced | None, read_at: datetime | None) -> Outcome:
    """The outcome of a decision from its settled status and, when there was one, the closing consensus.

    ``close`` is the consensus and the best price of the selection at the kick-off; with fewer than ``CLOSE_MIN_BOOKS`` complete books behind it
    there is no closing value (a price from one or two books is not a consensus). ``read_at`` is the last time the odds of the match were read
    before it started; without it, the instant the newest quote of the close was first seen."""
    unit = profit_per_unit(status.value, row.odds)
    flat, staked = unit.quantize(UNIT_Q), (unit * row.stake).quantize(UNIT_Q)
    if close is None or close.books < CLOSE_MIN_BOOKS:
        return Outcome(row.id, status.value, flat, staked, None, None, None, None, None)
    p_close = Decimal(repr(close.p_fair)).quantize(P_Q)
    as_of = read_at if read_at is not None else close.newest_quote
    return Outcome(row.id, status.value, flat, staked, p_close, Decimal(repr(close.best_odds)).quantize(ODDS_Q), as_of,
                   int((row.kickoff_at - as_of).total_seconds() // 60), closing_value.clv(row.odds, p_close).quantize(P_Q))


# ── what is read ─────────────────────────────────────────────────────────────────────────────────────────────────────

def load_open(conn: psycopg.Connection[Any], *, at: datetime, wait: timedelta = WAIT, lookback: timedelta = LOOKBACK,
              limit: int = BATCH) -> list[Open]:
    """The decisions of the families still to settle: kicked off between ``lookback`` and ``wait`` ago."""
    params = {"version": DECISION_VERSION, "since": at - lookback, "until": at - wait, "horizon": fd.HORIZON, "limit": limit}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TODO_SQL, params)
        return [Open(int(r["id"]), int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"]), Decimal(r["odds"]),
                     Decimal(r["stake_units"]), r["kickoff_at"]) for r in cur.fetchall()]


def closing(conn: psycopg.Connection[Any], rows: Sequence[Open]) -> tuple[dict[fd.PriceKey, fd.Priced], dict[int, datetime]]:
    """The consensus and the best price of every selection the decisions are about at the kick-off of their matches, and when the odds of each match
    were last read before it. A few matches at a time."""
    wanted: dict[int, set[str]] = defaultdict(set)
    for r in rows:
        wanted[r.fixture_id].add(r.key)
    priced: dict[fd.PriceKey, fd.Priced] = {}
    read: dict[int, datetime] = {}
    ordered = sorted(wanted)
    for start in range(0, len(ordered), CHUNK):
        chunk = ordered[start:start + CHUNK]
        keys = sorted(set().union(*(wanted[i] for i in chunk)))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(CLOSE_QUOTES_SQL, {"fixtures": chunk, "keys": keys, "kinds": list(versus.OUTCOMES), "window": CLOSE_WINDOW})
            quotes = [fd.AsOfQuote("close", int(r["fixture_id"]), int(r["bookmaker_id"]), str(r["market_key"]), str(r["kind"]), str(r["selection"]),
                                   Decimal(r["line"]), float(r["odds_decimal"]), r["captured_at"]) for r in cur.fetchall()]
            cur.execute(CLOSE_READ_SQL, {"fixtures": chunk, "window": CLOSE_WINDOW})
            read.update({int(r["fixture_id"]): r["observed_at"] for r in cur.fetchall()})
        priced.update(fd.price(quotes))
    return priced, read


# ── a pass ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class SettleReport:
    open: int = 0
    settled: int = 0
    ungradable: int = 0
    unreadable: int = 0
    no_close: int = 0
    failed: int = 0
    by_result: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"open": self.open, "settled": self.settled, "ungradable": self.ungradable, "unreadable": self.unreadable,
                "no_close": self.no_close, "failed": self.failed, "by_result": self.by_result, "errors": self.errors[:ERRORS_KEPT]}


def grade(rows: Sequence[Open], counts: Mapping[int, Mapping[str, int | None]]) -> tuple[dict[int, Status], int, int]:
    """The status of each decision on the counts of its match: (status by decision id, how many could not be graded yet, how many are about a
    market the settlement cannot read). A count that is unknown leaves the decision without a status - never a loss."""
    graded: dict[int, Status] = {}
    ungradable = unreadable = 0
    for r in rows:
        try:
            kind, subject = score.key_shape(r.key)
            rule = RULES_BY_MEASURE[score.measure_of(r.key)]
            values = counts.get(r.fixture_id)
            status = None if values is None else settle_numbers(rule, kind, subject, r.selection, r.line, values)
        except (ValueError, KeyError):  # a market or a selection the rules cannot read: counted, never a reason to stop the pass
            unreadable += 1
            continue
        if status is None or status is Status.PENDING:
            ungradable += 1
        else:
            graded[r.id] = status
    return graded, ungradable, unreadable


def settle(conn: psycopg.Connection[Any], *, at: datetime, wait: timedelta = WAIT, lookback: timedelta = LOOKBACK, limit: int = BATCH,
           write: bool = True) -> SettleReport:
    """Settle the decisions of the families that kicked off at least ``wait`` before ``at``. Idempotent (a decision with an outcome is not looked
    at again); commits nothing itself. A decision whose count is unknown is left as it is, and one the database refuses costs only itself.
    With ``write=False`` it reads and grades and writes nothing."""
    report = SettleReport()
    rows = load_open(conn, at=at, wait=wait, lookback=lookback, limit=limit)
    report.open = len(rows)
    if not rows:
        return report
    measures = score.measures_to_read(r.key for r in rows if _readable(r.key))
    counts: Mapping[int, Mapping[str, int | None]] = (
        score.load_counts(conn, measures, since=min(r.kickoff_at for r in rows), until=max(r.kickoff_at for r in rows)) if measures else {})
    graded, report.ungradable, report.unreadable = grade(rows, counts)
    if not graded:
        return report
    settled = [r for r in rows if r.id in graded]
    priced, read = closing(conn, settled)
    for r in settled:
        close = priced.get((r.fixture_id, r.key, r.line, r.selection))
        o = outcome(r, graded[r.id], close, read.get(r.fixture_id))
        if o.clv is None:
            report.no_close += 1
        if not write:
            report.settled += 1
            report.by_result[o.result_status] = report.by_result.get(o.result_status, 0) + 1
            continue
        try:
            with conn.transaction():  # a savepoint: a row the database refuses costs that row, not the rest of the pass
                wrote = _insert(conn, o, at=at)
        except Exception as exc:  # research: one decision that cannot be written never costs the others
            report.failed += 1
            report.errors.append(f"{r.id}/{r.fixture_id}/{r.key}/{r.selection}/{r.line}: {type(exc).__name__}: {exc}"[:300])
            log.error("family_outcomes.decision_failed", decision=r.id, fixture=r.fixture_id, key=r.key, error=type(exc).__name__, detail=str(exc)[:300])
            continue
        if wrote:
            report.settled += 1
            report.by_result[o.result_status] = report.by_result.get(o.result_status, 0) + 1
    return report


def _readable(key: str) -> bool:
    try:
        score.key_shape(key)
        score.measure_of(key)
    except ValueError:
        return False
    return True


def _insert(conn: psycopg.Connection[Any], o: Outcome, *, at: datetime) -> bool:
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {"id": o.decision_id, "at": at, "status": o.result_status, "flat": o.profit_flat, "staked": o.profit_staked,
                                 "p": o.close_p_fair, "odds": o.close_odds, "as_of": o.close_as_of, "minutes": o.close_minutes_to_ko, "clv": o.clv,
                                 "version": VERSION})
        return cur.rowcount > 0


def run_step(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    """The step of the nightly job: nothing while the switch of the families' decisions is ``off``; in ``shadow`` the settlement of the decisions
    whose match is over. A step of its own in the job (``fbi.intel.cycle.run_nightly``): if it raises, the job writes it in its record and the
    others still run."""
    chosen = fd.mode()
    if chosen == "off":
        return {"mode": chosen}
    return {"mode": chosen, **settle(conn, at=at).as_dict()}
