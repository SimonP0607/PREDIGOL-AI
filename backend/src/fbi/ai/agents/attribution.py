"""The MECHANICAL attribution (Plan Maestro IA, section 12, phase 5): which agent, in which version, was right or wrong about each settled selection of the
shadow - computed by code, from the shadow reviews and the result, with no model.

For every selection a shadow engine reviewed (``ma-v1``, ``ma-v1-h``, ``cs-v1``) and that has settled, the stance of each agent is read from the review the
orchestrator stored BEFORE the kick-off: the Council's verdict (and the signals that drove it), the Match Agent's and the Statistics Agent's stance (and,
when their run is stored, the signals that drove it). Each stance becomes rows of ``intel.agent_attributions``:

    outcome        HIT when the stance pointed the way the result went, MISS when it did not, VOID when the agent took no side (``ABSTAIN``, ``NEUTRAL``)
                   or the selection was void. In favour = ``APPROVE``/``SUPPORT``; against = ``DOWNGRADE``/``REJECT`` and ``CONCERN``/``REJECT_SIGNAL``.
    toward_close   whether the stance pointed the way the closing line went (the CLV of the post-mortem ``pm-v6``): the plan's «hacia el cierre».
    calibration    whether the model's probability was closer to the result than the closing fair probability (Brier) - «mejor o peor calibrado que el mercado».
    error_class    for a MISS, in the words of the post-mortem (``fbi.intel.pm_questions.CLASSES``): the post-mortem's own class for a stance in favour that
                   lost; for a stance against a selection that won, ``NORMAL_VARIANCE`` when the market moved away from it anyway (the CLV was negative) and
                   ``UNKNOWN`` otherwise - the ambiguous rows are the ones the Post-Match Reviewer (``pmr-v1``) may classify, as a second row.

What is measured is the CODE the agent wrote. Nothing in a narrative is read here, and nothing here changes a pick, a filter, a decision, a prompt or a
model: the table is read by the Console and by the Learning Analyst only. The computation is a pure function of the rows it reads (``rows_for``), written
the same way by the daily step (``source = 'live'``) and by the recomputation of an earlier day of the shadow (``source = 'batch'``), and idempotent: the
unique key of the table makes the second to arrive write nothing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai.calendar import day_bounds
from fbi.ai.contracts.base import SIGNAL_CODES

VERSION: Final = "attr-v1"
"""The rule of this module (``attribution_version``). A different rule is a new version: its rows are written beside the old ones, never over them."""
SOURCES: Final = ("live", "batch")
AGENT_OF_LABEL: Final = {"match": "match", "stats": "stats"}
"""``assessment_label`` is ``<agent>_<mode>`` (``match_evaluation``): the agent is its first word."""
COUNCIL: Final = "council"
FOR_STANCES: Final = frozenset({"APPROVE", "SUPPORT"})
AGAINST_STANCES: Final = frozenset({"DOWNGRADE", "REJECT", "CONCERN", "REJECT_SIGNAL"})
NO_SIDE: Final = frozenset({"ABSTAIN", "NEUTRAL"})
WON: Final = frozenset({"win", "half_win"})
LOST: Final = frozenset({"loss", "half_loss"})
SETTLED: Final = frozenset({*WON, *LOST, "push", "void"})
EPSILON: Final = 1e-6
"""Two Brier scores closer than this are equal."""

Polarity = Literal["FOR", "AGAINST", "NONE"]
Outcome = Literal["HIT", "MISS", "VOID"]

SHADOW_REVIEWS_SQL: Final = """
SELECT r.id AS review_id, r.fixture_id, r.market_key, r.selection, r.line, r.engine, r.packet_id, r.output,
       pm.id AS postmortem_id, pm.settled, pm.clv, pm.p_model, pm.p_market, pm.p_close, pm.loss_class
  FROM (SELECT DISTINCT ON (x.fixture_id, x.market_key, x.selection, x.line, x.engine)
               x.id, x.fixture_id, x.market_key, x.selection, x.line, x.engine, x.packet_id, x.output
          FROM ai.pick_reviews x
          JOIN core.fixtures f ON f.id = x.fixture_id
         WHERE x.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND x.mode = 'shadow' AND x.status = 'ok'
           AND x.reviewed_at < f.kickoff_at AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s AND f.status_group = 'finished'
         ORDER BY x.fixture_id, x.market_key, x.selection, x.line, x.engine, x.reviewed_at DESC, x.id DESC) r
  JOIN intel.selection_postmortems pm
    ON pm.fixture_id = r.fixture_id AND pm.market_key = r.market_key AND pm.selection = r.selection AND pm.line = r.line
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.engine
"""
"""The newest ``ok`` review of each selection and shadow engine before the kick-off, with the post-mortem of the selection (the newest ``pm-v6``): the
result, the CLV and the probabilities are the post-mortem's, which the rules built from stored facts."""

VERSIONS_SQL: Final = """
SELECT DISTINCT ON (fixture_id, packet_id) fixture_id, packet_id, package_hash, agents
  FROM ai.match_runs WHERE run_kind = 'shadow' AND fixture_id = ANY(%(fixtures)s)
 ORDER BY fixture_id, packet_id, created_at DESC, id DESC
"""
"""What the pass of the shadow recorded about the agents that ran: each one's version (``agents``) and the hash of the package they read."""

RUNS_SQL: Final = """
SELECT DISTINCT ON (fixture_id, agent, package_hash) id, fixture_id, agent, agent_version, package_hash, output
  FROM ai.agent_runs
 WHERE run_kind = 'shadow' AND task_kind = 'evaluation' AND agent IN ('match', 'stats') AND status = 'ok' AND fixture_id = ANY(%(fixtures)s)
 ORDER BY fixture_id, agent, package_hash, id DESC
"""
"""The evaluations of the Match and the Statistics agents: the signals that drove each stance are in ``output.candidates``."""

INSERT_SQL: Final = """
INSERT INTO intel.agent_attributions (attribution_version, classified_by, fixture_id, market_key, selection, line, engine, agent, agent_version, signal,
    stance, outcome, error_class, settled, toward_close, calibration, clv, review_id, run_id, postmortem_id, basis_id, source, computed_at)
VALUES (%(version)s, 'code', %(fixture_id)s, %(market_key)s, %(selection)s, %(line)s, %(engine)s, %(agent)s, %(agent_version)s, %(signal)s,
    %(stance)s, %(outcome)s, %(error_class)s, %(settled)s, %(toward_close)s, %(calibration)s, %(clv)s, %(review_id)s, %(run_id)s, %(postmortem_id)s,
    NULL, %(source)s, %(at)s)
ON CONFLICT (fixture_id, market_key, selection, line, engine, agent, agent_version, signal, attribution_version, classified_by) DO NOTHING
"""


@dataclass(frozen=True, slots=True)
class Item:
    """What the rule reads about ONE selection and ONE shadow engine: the review, the post-mortem and what the pass recorded about the agents."""

    review_id: int
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    engine: str
    output: Mapping[str, Any]
    postmortem_id: int
    settled: str
    clv: Decimal | None
    p_model: Decimal | None
    p_market: Decimal | None
    p_close: Decimal | None
    loss_class: str | None
    versions: Mapping[str, str] = field(default_factory=dict)
    """agent -> version, from the pass of the shadow."""
    runs: Mapping[str, tuple[int, Mapping[str, Any]]] = field(default_factory=dict)
    """agent -> (``ai.agent_runs.id``, its stored output), for the Match and the Statistics agents of that pass."""


@dataclass(frozen=True, slots=True)
class Row:
    """One row of ``intel.agent_attributions`` as the rule writes it (``classified_by = 'code'``)."""

    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    engine: str
    agent: str
    agent_version: str
    signal: str
    stance: str
    outcome: Outcome
    error_class: str
    settled: str
    toward_close: bool | None
    calibration: str | None
    clv: Decimal | None
    review_id: int
    run_id: int | None
    postmortem_id: int

    @property
    def key(self) -> tuple[Any, ...]:
        """What the unique index of the table says a row is."""
        return (self.fixture_id, self.market_key, self.selection, self.line, self.engine, self.agent, self.agent_version, self.signal)


# -- the rule (pure) ------------------------------------------------------------------------------------------------------------------

def polarity_of(stance: str) -> Polarity:
    """Which side a stance took: in favour of the selection, against it, or none."""
    if stance in FOR_STANCES:
        return "FOR"
    if stance in AGAINST_STANCES:
        return "AGAINST"
    return "NONE"


def outcome_of(polarity: Polarity, settled: str) -> Outcome:
    """HIT when the stance pointed the way the result went; VOID when no side was taken or the selection was not decided."""
    if polarity == "NONE" or settled not in WON | LOST:
        return "VOID"
    won = settled in WON
    return "HIT" if (polarity == "FOR") == won else "MISS"


def toward_close_of(polarity: Polarity, clv: Decimal | None) -> bool | None:
    """Whether the stance pointed the way the closing line went: a stance in favour wants a positive CLV, one against a negative CLV."""
    if polarity == "NONE" or clv is None or clv == 0:
        return None
    return (clv > 0) == (polarity == "FOR")


def calibration_of(settled: str, p_model: Decimal | None, p_market: Decimal | None, p_close: Decimal | None) -> str | None:
    """Whether the model was closer to the result than the market: the Brier score of ``p_model`` against the closing fair probability (the Shin consensus),
    or the probability of the market when there is no closing one."""
    reference = p_close if p_close is not None else p_market
    if p_model is None or reference is None or settled not in WON | LOST:
        return None
    y = 1.0 if settled in WON else 0.0
    gap = (float(p_model) - y) ** 2 - (float(reference) - y) ** 2
    return "MODEL_BETTER" if gap < -EPSILON else "MARKET_BETTER" if gap > EPSILON else "EQUAL"


def class_of(polarity: Polarity, outcome: Outcome, clv: Decimal | None, loss_class: str | None) -> str:
    """The class of a MISS (``NONE`` for anything else), in the words of the post-mortem."""
    if outcome != "MISS":
        return "NONE"
    if polarity == "FOR":
        return loss_class or "UNKNOWN"
    if clv is not None and clv < 0:
        return "NORMAL_VARIANCE"  # rejected, it won, and the market was moving away from it: the result was luck, not a misreading
    return "UNKNOWN"


def _drivers_of(run: Mapping[str, Any] | None, candidate: str) -> list[str]:
    """The signals a stored evaluation says drove the stance on a candidate (the closed list only)."""
    if not run:
        return []
    for entry in run.get("candidates") or []:
        if isinstance(entry, Mapping) and entry.get("candidate") == candidate:
            return [s for s in entry.get("drivers") or [] if isinstance(s, str) and s in SIGNAL_CODES]
    return []


def stances_of(item: Item) -> list[tuple[str, str, str, int | None, list[str]]]:
    """``(agent, version, stance, run_id, drivers)`` for each agent whose stance the review recorded: the Council's verdict and drivers, and the stance of each
    assessment the Council read. An agent whose version the pass did not record is not attributed (a version nobody knows cannot be proposed a hypothesis)."""
    out: list[tuple[str, str, str, int | None, list[str]]] = []
    verdict = item.output.get("verdict")
    council_version = item.versions.get(COUNCIL)
    if isinstance(verdict, str) and council_version:
        drivers = [s for s in item.output.get("drivers") or [] if isinstance(s, str) and s in SIGNAL_CODES]
        out.append((COUNCIL, council_version, verdict, None, drivers))
    assessment = item.output.get("assessment")
    candidate = str(item.output.get("candidate") or "")
    if isinstance(assessment, Mapping):
        for label, stance in sorted(assessment.items()):
            agent = AGENT_OF_LABEL.get(str(label).split("_", 1)[0])
            version = item.versions.get(agent) if agent else None
            if agent and version and isinstance(stance, str):
                run = item.runs.get(agent)
                out.append((agent, version, stance, None if run is None else run[0], _drivers_of(None if run is None else run[1], candidate)))
    return out


def rows_for(item: Item) -> list[Row]:
    """Every row the rule writes for one selection and engine: for each agent, one row for its stance (signal ``VERDICT``) and one for each signal that
    drove it. Pure: the same item gives the same rows, in the same order."""
    settled = item.settled if item.settled in SETTLED else "void"
    calibration = calibration_of(settled, item.p_model, item.p_market, item.p_close)
    rows: dict[tuple[Any, ...], Row] = {}
    for agent, version, stance, run_id, drivers in stances_of(item):
        pol = polarity_of(stance)
        outcome = outcome_of(pol, settled)
        for signal in ["VERDICT", *drivers]:
            row = Row(fixture_id=item.fixture_id, market_key=item.market_key, selection=item.selection, line=item.line, engine=item.engine, agent=agent,
                      agent_version=version, signal=signal, stance=stance, outcome=outcome,
                      error_class=class_of(pol, outcome, item.clv, item.loss_class), settled=settled,
                      toward_close=toward_close_of(pol, item.clv), calibration=calibration, clv=item.clv, review_id=item.review_id, run_id=run_id,
                      postmortem_id=item.postmortem_id)
            rows.setdefault(row.key, row)
    return sorted(rows.values(), key=lambda r: (r.key[:5], r.agent, r.signal != "VERDICT", r.signal))


# -- reading and writing --------------------------------------------------------------------------------------------------------------

def load(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> list[Item]:
    """The settled selections of the shadow whose match kicked off in ``[since, until)``, each with what the pass recorded about its agents."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SHADOW_REVIEWS_SQL, {"since": since, "until": until})
        found = [dict(r) for r in cur.fetchall()]
        if not found:
            return []
        fixtures = sorted({int(r["fixture_id"]) for r in found})
        passes = {(int(r["fixture_id"]), int(r["packet_id"])): dict(r) for r in cur.execute(VERSIONS_SQL, {"fixtures": fixtures}).fetchall()
                  if r["packet_id"] is not None}
        runs: dict[tuple[int, str], dict[str, Any]] = {}
        for r in cur.execute(RUNS_SQL, {"fixtures": fixtures}).fetchall():
            runs[(int(r["fixture_id"]), str(r["package_hash"]))] = runs.get((int(r["fixture_id"]), str(r["package_hash"])), {}) | {str(r["agent"]): dict(r)}
    items: list[Item] = []
    for r in found:
        packet = passes.get((int(r["fixture_id"]), int(r["packet_id"]))) if r["packet_id"] is not None else None
        if packet is None:
            continue  # a review of a pass the shadow did not record: no agent version to attribute to
        versions = {str(a.get("agent")): str(a.get("version")) for a in packet["agents"] or [] if isinstance(a, Mapping) and a.get("version")}
        same_package = runs.get((int(r["fixture_id"]), str(packet["package_hash"])), {})
        items.append(Item(
            review_id=int(r["review_id"]), fixture_id=int(r["fixture_id"]), market_key=str(r["market_key"]), selection=str(r["selection"]),
            line=Decimal(r["line"]), engine=str(r["engine"]), output=dict(r["output"] or {}), postmortem_id=int(r["postmortem_id"]),
            settled=str(r["settled"]), clv=_dec(r["clv"]), p_model=_dec(r["p_model"]), p_market=_dec(r["p_market"]), p_close=_dec(r["p_close"]),
            loss_class=r["loss_class"], versions=versions,
            runs={agent: (int(run["id"]), dict(run["output"] or {})) for agent, run in same_package.items()}))
    return items


def _dec(x: Any) -> Decimal | None:
    return None if x is None else Decimal(x)


def store(conn: psycopg.Connection[Any], rows: Iterable[Row], *, at: datetime, source: str) -> int:
    """Append the rows; the ones already there (the unique key) are left as they are. Returns how many were written. Does not commit."""
    if source not in SOURCES:
        raise ValueError(f"source is one of {SOURCES}")
    written = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(INSERT_SQL, {
                "version": VERSION, "fixture_id": r.fixture_id, "market_key": r.market_key, "selection": r.selection, "line": r.line, "engine": r.engine,
                "agent": r.agent, "agent_version": r.agent_version, "signal": r.signal, "stance": r.stance, "outcome": r.outcome,
                "error_class": r.error_class, "settled": r.settled, "toward_close": r.toward_close, "calibration": r.calibration, "clv": r.clv,
                "review_id": r.review_id, "run_id": r.run_id, "postmortem_id": r.postmortem_id, "source": source, "at": at})
            written += cur.rowcount
    return written


@dataclass(slots=True)
class Report:
    """What one computation did."""

    selections: int = 0
    rows: int = 0
    written: int = 0
    skipped: int = 0
    """Settled selections whose pass left no agent version to attribute to (no row for them)."""


def compute(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, at: datetime, source: str = "live") -> Report:
    """Attribute every settled selection of the shadow whose match kicked off in ``[since, until)``. Idempotent. Does not commit."""
    items = load(conn, since=since, until=until)
    rows = [row for item in items for row in rows_for(item)]
    return Report(selections=len(items), rows=len(rows), written=store(conn, rows, at=at, source=source),
                  skipped=sum(1 for item in items if not rows_for(item)))


def attribute_day(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> Report:
    """The daily step (``ai_learn``): the matches of one Bogotá day, as «live»."""
    start, end = day_bounds(day)
    return compute(conn, since=start, until=end, at=at, source="live")


def recompute(conn: psycopg.Connection[Any], *, first: date, last: date, at: datetime) -> Report:
    """The same rule over the days before the step existed (or before it was switched on): marked «batch». The rows are the ones the daily step would
    have written; the ones that exist already are left alone. Does not commit."""
    total = Report()
    day = first
    while day <= last:
        start, end = day_bounds(day)
        r = compute(conn, since=start, until=end, at=at, source="batch")
        total.selections += r.selections
        total.rows += r.rows
        total.written += r.written
        total.skipped += r.skipped
        day += timedelta(days=1)
    return total


# -- the metrics of the plan ----------------------------------------------------------------------------------------------------------

COVERAGE_SQL: Final = """
WITH reviewed AS (
    SELECT DISTINCT r.fixture_id
      FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
     WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND r.mode = 'shadow' AND r.status = 'ok' AND r.reviewed_at < f.kickoff_at
       AND f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s)
SELECT count(*) AS settled_with_runs,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM intel.agent_attributions a WHERE a.fixture_id = reviewed.fixture_id
                                         AND a.attribution_version = %(version)s AND a.classified_by = 'code')) AS attributed
  FROM reviewed
"""

SCOREBOARD_SQL: Final = """
SELECT agent, agent_version, engine, outcome, count(*) AS n
  FROM intel.agent_attributions
 WHERE signal = 'VERDICT' AND classified_by = 'code' AND attribution_version = %(version)s AND computed_at >= %(since)s
 GROUP BY agent, agent_version, engine, outcome
"""


def coverage(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> dict[str, Any]:
    """Gate B's figure: of the matches that finished in the window and that a shadow engine reviewed with an answer, the ones with attributions. The plan asks
    for 95 %. ``None`` as the share when there are none: zero of zero is not 100 %."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(COVERAGE_SQL, {"since": since, "until": until, "version": VERSION})
        row = cur.fetchone()
    total, done = (int(row[0]), int(row[1])) if row else (0, 0)
    return {"version": VERSION, "settled_with_runs": total, "attributed": done, "share": None if total == 0 else round(done / total, 4)}


def scoreboard(conn: psycopg.Connection[Any], *, since: datetime) -> list[dict[str, Any]]:
    """Hits and misses per agent, version and arm (the stance rows only: one per selection), from ``since`` on."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SCOREBOARD_SQL, {"version": VERSION, "since": since})
        rows = [dict(r) for r in cur.fetchall()]
    table: dict[tuple[str, str, str], Counter[str]] = {}
    for r in rows:
        table.setdefault((str(r["agent"]), str(r["agent_version"]), str(r["engine"])), Counter())[str(r["outcome"])] += int(r["n"])
    out = []
    for (agent, version, engine), c in sorted(table.items()):
        decided = c["HIT"] + c["MISS"]
        out.append({"agent": agent, "agent_version": version, "engine": engine, "hits": c["HIT"], "misses": c["MISS"], "voids": c["VOID"],
                    "hit_rate": None if decided == 0 else round(c["HIT"] / decided, 4)})
    return out


__all__ = ["VERSION", "Item", "Report", "Row", "attribute_day", "calibration_of", "class_of", "compute", "coverage", "load", "outcome_of", "polarity_of",
           "recompute", "rows_for", "scoreboard", "store", "toward_close_of"]
