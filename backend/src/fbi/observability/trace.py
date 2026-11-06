"""The trace of one selection from end to end (``trace-v1``, Plan Maestro IA, phase P0: «trace_id de punta a punta»).

WHY THIS EXISTS
---------------
Every step that leads to a pick already writes its own row - the decision layer its checkpoints, the reviews their engine, the agents their
tokens and cost, the settlement its result - but nothing ties them together: to answer «why did PrediGol say this, with what, at what cost,
and what became of it» somebody had to know a dozen tables and the column that links each to the next. This module is that knowledge, in
one place, and it changes nothing: it reads the rows that exist, in the order the pipeline wrote them, and says which ones are not there.

THE IDENTIFIERS need no storage: they are UUIDv5 of the selection's natural key under ``NAMESPACE`` (``match_trace_id`` for a match,
``selection_trace_id`` for a selection; a pick's trace is its selection's). The same selection has the same id on every machine and every
day, so a log line, a page or a report can carry it without a column in any table. Changing the namespace or the way a name is spelled
(``_selection_name``) is a new method version, never an edit of this one.

THE SPANS, in the order the pipeline writes them (``STAGES``); each one says the table it was read in, the row(s), the moment the table
gives it (``known_at``, ``at``, ``created_at`` ... as the table has it), the versions it carries and a compact payload:

    fixture       core.fixtures                       the match and its state
    data_quality  analytics.competition_data_scores   the data class of its competition as of the first decision (filter 1 reads it), with
                  (+ analytics.fixture_validation,    the quarantine state of the match, its open quality issues and the verdict the
                  audit.data_quality_issues)          decision itself recorded for filter 1
    model         models.model_versions               the model version(s) the decisions and the pick name, with their code version
    forecast      models.predictions                  the prediction the pick was made from (``picks.picks.prediction_id``)
    price         market.market_consensus,            the de-vigged consensus each decision priced against (``price_at``, Shin), the pick's
                  market.odds_snapshots               consensus and the bookmaker snapshot it took its odds from
    decision      intel.decisions                     every checkpoint row of the selection with its ten filters, calibrator and versions
    review        ai.pick_reviews                     the reviews a decision cites (by id) and every review of the selection, per engine,
                                                      production and shadow apart
    match_run     ai.match_runs                       what the system knew of the match at the end of each pass (fixture level)
    agent_task    ai.agent_tasks                      the questions put to the agents (fixture level)
    agent_run     ai.agent_runs                       each answer: model, prompt and agent versions, tokens, cost, latency, status
    packet        ai.match_packets                    the packets the reviews and the passes cite (by id)
    evidence      (the citing rows)                   every evidence id a decision, a review or an agent run cites, with who cites it -
                                                      listed, not looked up (see below)
    pick          picks.picks                         the pick(s) the decisions name
    publication   picks.daily_set_items,              the picks of the day the selection was part of
                  intel.day_selections
    settlement    picks.pick_results                  the result of each pick
    outcome       intel.decision_outcomes             what became of each decision (profit, CLV)

WHAT IS NOT READ, and why (status ``not_read``, never ``missing``):

    cycle         ``ai.cycles`` carries no fixture, run or review id: tying a cycle to a selection would mean guessing it by its time window.
    postmortem    the post-mortem tables may be named only by the modules ``tests/unit/test_postmortem_isolation.py`` lists, with the reason;
                  this module is not among them, and adding it is a decision for the owner, not for a reader.
    attribution   the same for the attribution of the shadow (``tests/unit/test_attribution_readers.py``).
    evidence      the readers of the evidence table are counted, one by one, in the owner's guide of phase 2 (section 5 of IA_FASE2, held by
                  ``tests/unit/test_ia_fase2_docs.py``): a new reader is a line of that guide. Until the owner adds this one, the ids a trace
                  shows are the ones the citing rows recorded - whether each still resolves is not checked here.

The page's forecast (the product's probability of the match) is not read either: ``tests/unit/test_forecast_isolation.py`` keeps its table
apart from everything that decides, and the decision does not rest on it - the pick's own prediction (``forecast`` above) is what it rests on.

MANDATORY SPANS (``MANDATORY``) and when one does not apply - always from what a row recorded, never from what it might have been:

    fixture, decision, pick, model   always (a selection of the families has no pick: ``not_applicable`` in that layer)
    data_quality                     always: a decision made without a data class of its competition is a gap
    forecast                         whenever there is a pick; a pick that names no prediction is ``missing``
    price                            whenever a decision recorded a price or the pick names its consensus and snapshot
    review                           whenever a decision cites one (no decision citing a review: its ``context_status`` says why)
    settlement                       once the match is finished
    outcome                          once a pick of the selection has a final result (every decision gets one: ``fbi.intel.outcomes``)

``completeness`` says which are present; ``coverage`` gives, for one (Bogotá) day, the share of the selections decided that day - and of
the ones published that day - whose trace is complete, and the spans most often missing. That share is the P0 metric.

Nothing here writes, commits or calls anything outside the database: every statement is a SELECT, and the connection is the caller's.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_bounds
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES

VERSION: Final = "trace-v1"
NAMESPACE: Final = uuid.UUID("12b38101-0116-532d-8e9e-4ceac6609737")
"""uuid5(NAMESPACE_URL, 'https://predigolai.com/observability/trace-v1'), written out so that it never depends on being recomputed. A trace id
of ``trace-v1`` is uuid5 of this namespace and the name ``_match_name`` / ``_selection_name`` spell; another namespace is another method."""

LINE_Q: Final = Decimal("0.01")
"""How a line is spelled in a trace id: two decimals (``fbi.intel.decision.LINE_Q``), so 2.5, '2.50' and Decimal('2.500') are one selection."""

PRESENT: Final = "present"
MISSING: Final = "missing"
NOT_APPLICABLE: Final = "not_applicable"
NOT_READ: Final = "not_read"
STATUSES: Final = (PRESENT, MISSING, NOT_APPLICABLE, NOT_READ)

STAGES: Final = ("fixture", "data_quality", "model", "forecast", "price", "decision", "review", "match_run", "agent_task", "agent_run",
                 "packet", "evidence", "pick", "publication", "settlement", "outcome", "cycle", "postmortem", "attribution")
"""The kinds of span, in the order the pipeline writes them: a trace lists its spans in this order, and by time within a kind."""
MANDATORY: Final = ("fixture", "data_quality", "model", "forecast", "price", "decision", "review", "pick", "settlement", "outcome")
"""What a selection's trace must have (or say, from a row, why it does not apply) to be complete."""
MANDATORY_MATCH: Final = ("fixture", "data_quality")
"""What a match's trace (a fixture without a selection) must have."""
NOT_READ_SPANS: Final[Mapping[str, tuple[str, str]]] = {
    "cycle": ("ai.cycles", "the table carries no fixture, run or review id: tying a cycle to this selection would be a guess by time"),
    "postmortem": ("post-mortem tables", "guarded: only the readers tests/unit/test_postmortem_isolation.py lists may read them"),
    "attribution": ("intel.agent_attributions", "guarded: only the readers tests/unit/test_attribution_readers.py lists may read it"),
}

EVIDENCE_NOTE: Final = ("cited by the rows listed; not looked up: the readers of ai.evidence are the ones the owner's guide of phase 2 counts "
                         "(tests/unit/test_ia_fase2_docs.py)")
TEXT_CUT: Final = 160
"""A string in a payload is cut to this many characters: a trace is a map, the rows are where the whole text lives."""


# ── identifiers ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def spell_line(line: Decimal | float | int | str | None) -> str:
    """A line as a trace id spells it: two decimals, no sign on zero. ``None`` is the line of a market without one (0)."""
    value = Decimal(0) if line is None else Decimal(str(line))
    q = value.quantize(LINE_Q)
    return "0.00" if q == 0 else str(q)


def _match_name(fixture_id: int) -> str:
    return f"match:{int(fixture_id)}"


def _selection_name(fixture_id: int, market_key: str, selection: str, line: Decimal | float | int | str | None) -> str:
    return f"selection:{int(fixture_id)}:{market_key}:{selection}:{spell_line(line)}"


def match_trace_id(fixture_id: int) -> uuid.UUID:
    """The trace id of a match: the same on every machine, for ever (under ``trace-v1``)."""
    return uuid.uuid5(NAMESPACE, _match_name(fixture_id))


def selection_trace_id(fixture_id: int, market_key: str, selection: str, line: Decimal | float | int | str | None) -> uuid.UUID:
    """The trace id of a selection - and of every pick and decision of it. Market and selection are taken as written (case included)."""
    return uuid.uuid5(NAMESPACE, _selection_name(fixture_id, market_key, selection, line))


# ── the shapes ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Span:
    """One step of the path: where it was read, which row(s), when, under which versions, and a compact payload."""

    kind: str
    status: str
    source: str
    row_ids: tuple[str, ...] = ()
    at: datetime | None = None
    versions: Mapping[str, str] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "status": self.status, "source": self.source, "row_ids": list(self.row_ids),
                "at": None if self.at is None else self.at.isoformat(), "versions": dict(self.versions), "payload": dict(self.payload),
                "note": self.note}


@dataclass(frozen=True, slots=True)
class Trace:
    """The spans of one selection (or of one match, when no selection was asked for), in ``STAGES`` order."""

    version: str
    anchor: str
    scope: str
    """``selection`` or ``match``."""
    trace_id: uuid.UUID | None
    match_trace_id: uuid.UUID | None
    fixture_id: int | None
    market_key: str | None
    selection: str | None
    line: str | None
    decision_version: str
    spans: tuple[Span, ...]

    def of_kind(self, kind: str) -> tuple[Span, ...]:
        return tuple(s for s in self.spans if s.kind == kind)

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "anchor": self.anchor, "scope": self.scope,
                "trace_id": None if self.trace_id is None else str(self.trace_id),
                "match_trace_id": None if self.match_trace_id is None else str(self.match_trace_id),
                "fixture_id": self.fixture_id, "market_key": self.market_key, "selection": self.selection, "line": self.line,
                "decision_version": self.decision_version, "completeness": completeness(self).as_json(),
                "spans": [s.as_json() for s in self.spans]}


@dataclass(frozen=True, slots=True)
class Completeness:
    """Which mandatory spans a trace has. A kind is ``missing`` when any of its spans is (one review cited and not found is enough)."""

    required: tuple[str, ...]
    present: tuple[str, ...]
    not_applicable: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing

    def as_json(self) -> dict[str, Any]:
        return {"complete": self.complete, "required": list(self.required), "present": list(self.present),
                "not_applicable": list(self.not_applicable), "missing": list(self.missing)}


@dataclass(frozen=True, slots=True)
class CoverageUnit:
    """The share of complete traces among one population of a day."""

    population: str
    total: int
    complete: int
    missing: tuple[tuple[str, int], ...]
    """The mandatory spans missing, most common first: (kind, how many traces lack it)."""
    incomplete: tuple[str, ...]
    """The trace ids that are not complete (the first ``SAMPLE``), to look at with ``show``."""

    @property
    def share(self) -> float | None:
        """None when there is nothing to judge: zero of zero is not 100 %."""
        return None if self.total == 0 else self.complete / self.total

    def as_json(self) -> dict[str, Any]:
        return {"population": self.population, "total": self.total, "complete": self.complete, "share": self.share,
                "missing": [{"kind": k, "traces": n} for k, n in self.missing], "incomplete": list(self.incomplete)}


@dataclass(frozen=True, slots=True)
class Coverage:
    version: str
    day: date
    decision_version: str
    selections: CoverageUnit
    """Every selection with a decision whose ``known_at`` falls on the day."""
    published: CoverageUnit
    """The selections of the picks of the day (``picks.daily_set_items`` of that day's sets and ``intel.day_selections`` of that day)."""

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "day": self.day.isoformat(), "decision_version": self.decision_version,
                "selections": self.selections.as_json(), "published": self.published.as_json()}


SAMPLE: Final = 20


# ── pure rules ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def required_kinds(scope: str) -> tuple[str, ...]:
    if scope == "selection":
        return MANDATORY
    if scope == "match":
        return MANDATORY_MATCH
    raise ValueError(f"unknown scope {scope!r}")


def kind_status(spans: Iterable[Span]) -> str:
    """The status of one kind from its spans: any missing -> missing; else any present -> present; else all not applicable -> not
    applicable; nothing at all (or only ``not_read``) -> missing: a mandatory kind the assembly said nothing about is not there."""
    statuses = {s.status for s in spans}
    if MISSING in statuses:
        return MISSING
    if PRESENT in statuses:
        return PRESENT
    if statuses == {NOT_APPLICABLE}:
        return NOT_APPLICABLE
    return MISSING


def completeness(trace: Trace) -> Completeness:
    required = required_kinds(trace.scope)
    by_kind = {k: kind_status(trace.of_kind(k)) for k in required}
    return Completeness(required=required,
                        present=tuple(k for k in required if by_kind[k] == PRESENT),
                        not_applicable=tuple(k for k in required if by_kind[k] == NOT_APPLICABLE),
                        missing=tuple(k for k in required if by_kind[k] == MISSING))


def settlement_expected(status_group: str | None) -> bool:
    """A pick is settled once its match is finished; a scheduled, live, cancelled or postponed one has nothing to settle yet."""
    return status_group == "finished"


def outcome_expected(result_status: str | None) -> bool:
    """Every decision gets an outcome once its pick has a final result (``fbi.intel.outcomes``); a pending result has none to give."""
    return result_status is not None and result_status != "pending"


def order(spans: Iterable[Span]) -> tuple[Span, ...]:
    """``STAGES`` order, then time (a span without one last), then row id: the same rows always print the same way."""
    rank = {k: i for i, k in enumerate(STAGES)}
    return tuple(sorted(spans, key=lambda s: (rank.get(s.kind, len(STAGES)), s.at is None, 0.0 if s.at is None else s.at.timestamp(),
                                               s.row_ids)))


def plain(value: Any) -> Any:
    """A payload value in JSON's words: numbers as floats, moments as ISO text, long strings cut."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str):
        return value if len(value) <= TEXT_CUT else value[: TEXT_CUT - 1] + "…"
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [plain(v) for v in value]
    return value


def compact(row: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {k: plain(row.get(k)) for k in keys if row.get(k) is not None}


def compact_filters(filters: Any) -> list[dict[str, Any]]:
    """The ten filters of a decision, each with its verdict and why (``fbi.intel.decision._f``), without the data they carry."""
    if not isinstance(filters, list):
        return []
    out: list[dict[str, Any]] = []
    for f in filters:
        if isinstance(f, Mapping):
            out.append({k: plain(f[k]) for k in ("n", "key", "ok", "effect", "why") if k in f})
    return out


def _versions(row: Mapping[str, Any], names: Mapping[str, str]) -> dict[str, str]:
    """``{label: column}`` -> the labels whose column has a value."""
    return {label: str(row[col]) for label, col in names.items() if row.get(col) is not None}


def _ids(values: Iterable[Any]) -> list[int]:
    return sorted({int(v) for v in values if v is not None})


# ── SQL ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_short, f.status_group, f.competition_season_id, f.updated_at, cs.competition_id
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.id = %(fixture)s
"""
DATA_SCORE_SQL: Final = """
SELECT competition_season_id, computed_at, rule_version, class, score, quarantined
  FROM analytics.competition_data_scores
 WHERE competition_season_id = %(season)s AND (%(at)s::timestamptz IS NULL OR computed_at <= %(at)s)
 ORDER BY computed_at DESC LIMIT 1
"""
"""The newest data class of the competition as of the first decision - the one filter 1 read (``fbi.intel.decision.QUALITY_SQL``)."""
VALIDATION_SQL: Final = "SELECT fixture_id, state, rule_version, failed, validated_at FROM analytics.fixture_validation WHERE fixture_id = %(fixture)s"
ISSUES_SQL: Final = """
SELECT id, code, severity, status, detected_at FROM audit.data_quality_issues
 WHERE entity_type = 'fixture' AND entity_id = %(fixture)s AND status IN ('open', 'acknowledged')
 ORDER BY detected_at, id
"""

DECISION_COLUMNS: Final = """
d.id, d.decision_version, d.known_at, d.checkpoint, d.fixture_id, d.kickoff_at, d.market_key, d.selection, d.line, d.pick_id, d.model_name,
d.model_version_id, d.odds, d.bookmaker_id, d.price_at, d.n_bookmakers, d.p_model, d.p_cal, d.calibrator_id, d.calibrator_role,
c.version AS calibrator_version, c.method AS calibrator_method, d.p_market, d.ev_cal, d.edge_cal, d.filters, d.state, d.reasons, d.score,
d.score_version, d.stake_units, d.stake_version, d.context_status, d.review_id, d.evidence_ids, d.input_hash, d.code_version, d.created_at
"""
DECISION_ANCHOR_SQL: Final = """
SELECT d.id, d.decision_version, d.fixture_id, d.market_key, d.selection, d.line
  FROM intel.decisions d WHERE d.id = %(id)s AND d.decision_version = ANY(%(versions)s)
"""
"""The selection of one decision, in whichever layer it is (``versions`` names both)."""
SELECTION_DECISIONS_SQL: Final = f"""
SELECT {DECISION_COLUMNS}
  FROM intel.decisions d LEFT JOIN intel.calibrators c ON c.id = d.calibrator_id
 WHERE d.fixture_id = %(fixture)s AND d.market_key = %(market)s AND d.selection = %(selection)s AND d.line = %(line)s
   AND d.decision_version = %(version)s
 ORDER BY d.known_at, d.id
"""
MATCH_DECISIONS_SQL: Final = f"""
SELECT {DECISION_COLUMNS}
  FROM intel.decisions d LEFT JOIN intel.calibrators c ON c.id = d.calibrator_id
 WHERE d.fixture_id = %(fixture)s AND d.decision_version = %(version)s
 ORDER BY d.known_at, d.id
"""
OUTCOMES_SQL: Final = """
SELECT o.decision_id, o.settled_at, o.result_status, o.profit_flat, o.profit_staked, o.clv, o.close_odds, o.close_as_of, o.version, o.computed_at
  FROM intel.decision_outcomes o JOIN intel.decisions d ON d.id = o.decision_id
 WHERE o.decision_id = ANY(%(ids)s) AND d.decision_version = %(version)s
"""

PICK_SQL: Final = """
SELECT id, candidate_id, fixture_id, market_key, selection, line, model_version_id, calibrator_id, prediction_id, decision_rule_version,
       code_version, bookmaker_id, market_odds, odds_captured_at, odds_payload_hash, consensus_method, consensus_as_of, p_calibrated,
       p_market_fair, ev, edge, stake_units, mode, status, created_at, published_at, data_cutoff_ts
  FROM picks.picks WHERE id = ANY(%(ids)s)
"""
PICK_RESULTS_SQL: Final = """
SELECT pick_id, result_status, profit_units, settled_at, settled_by, settlement_basis, rule_version
  FROM picks.pick_results WHERE pick_id = ANY(%(ids)s)
"""
DAILY_ITEMS_SQL: Final = """
SELECT i.set_id, i.rank, i.pick_id, i.stage, i.selected_at, i.odds, i.status, i.profit_units, i.settled_at,
       s.day, s.source, s.rule_version, s.status AS set_status
  FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id
 WHERE i.pick_id = ANY(%(ids)s)
"""
DAY_SELECTIONS_SQL: Final = """
SELECT id, day, rule_version, kind, rank, decision_ids, selected_at, odds, stake_units
  FROM intel.day_selections WHERE decision_ids && %(ids)s::bigint[]
"""

MODELS_SQL: Final = """
SELECT v.id, v.version, v.code_version, v.status, v.created_at, r.name AS model
  FROM models.model_versions v JOIN models.model_registry r ON r.id = v.model_id
 WHERE v.id = ANY(%(ids)s)
"""
PREDICTIONS_SQL: Final = """
SELECT id, model_version_id, calibrator_id, p_raw, p_calibrated, p_lo, p_hi, feature_set_hash, data_cutoff_ts, created_at, backtest_session_id
  FROM models.predictions WHERE id = ANY(%(ids)s)
"""

CONSENSUS_SQL: Final = """
SELECT as_of, devig_method, p_fair, n_bookmakers, overround, best_odds, best_bookmaker_id, dispersion
  FROM market.market_consensus
 WHERE fixture_id = %(fixture)s AND market_key = %(market)s AND selection = %(selection)s AND line = %(line)s AND as_of = ANY(%(as_of)s)
"""
SNAPSHOT_SQL: Final = """
SELECT bookmaker_id, odds_decimal, captured_at, minutes_to_ko, source, payload_hash
  FROM market.odds_snapshots
 WHERE fixture_id = %(fixture)s AND bookmaker_id = %(bookmaker)s AND market_key = %(market)s AND selection = %(selection)s
   AND line = %(line)s AND captured_at = %(captured)s
"""

REVIEW_COLUMNS: Final = """
r.id, r.reviewed_at, r.fixture_id, r.pick_id, r.market_key, r.selection, r.line, r.engine, r.engine_version, r.provider, r.model, r.packet_id,
r.input_hash, r.decision, r.confidence, r.cost_usd, r.mode, r.status, r.error, r.evidence_ids, r.usage_ids
"""
CITED_REVIEWS_SQL: Final = f"SELECT {REVIEW_COLUMNS} FROM ai.pick_reviews r WHERE r.id = ANY(%(ids)s)"
"""The reviews a decision cites, by the id it recorded: whatever engine they are, they are what it read."""
PRODUCTION_REVIEWS_SQL: Final = f"""
SELECT {REVIEW_COLUMNS} FROM ai.pick_reviews r
 WHERE r.fixture_id = %(fixture)s AND (%(market)s::text IS NULL OR (r.market_key = %(market)s AND r.selection = %(selection)s AND r.line = %(line)s))
   AND r.engine IN ('rules', 'llm', 'combined')
 ORDER BY r.reviewed_at, r.id
"""
"""The reviews of production (``fbi.ai.config.PRODUCTION_ENGINES``) of the selection - or of the match when no market is given."""
SHADOW_REVIEWS_SQL: Final = f"""
SELECT {REVIEW_COLUMNS} FROM ai.pick_reviews r
 WHERE r.fixture_id = %(fixture)s AND (%(market)s::text IS NULL OR (r.market_key = %(market)s AND r.selection = %(selection)s AND r.line = %(line)s))
   AND r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1')
 ORDER BY r.reviewed_at, r.id
"""
"""The reviews of the shadow (``fbi.ai.config.SHADOW_ENGINES``), read apart and labelled so: a trace shows them, nothing counts them."""

AGENT_RUNS_SQL: Final = """
SELECT id, run_kind, reason, parent_run_id, task_kind, pass_kind, started_at, finished_at, known_at, model, effort, agent, agent_version,
       prompt_version, schema_version, router_version, attempt, evidence_ids, verdict, input_tokens, output_tokens, cached_tokens,
       cache_write_tokens, thinking_tokens, batch_id, cost_usd, workspace, latency_ms, queue_ms, status, error
  FROM ai.agent_runs WHERE fixture_id = %(fixture)s ORDER BY started_at, id
"""
AGENT_TASKS_SQL: Final = """
SELECT id, agent, agent_version, prompt_version, schema_version, model, effort, input_version, pass_kind, run_kind, task_kind, router_version,
       priority, est_cost_usd, state, created_at, started_at, finished_at, attempts, batch_id, last_run_id
  FROM ai.agent_tasks WHERE fixture_id = %(fixture)s ORDER BY created_at, id
"""
MATCH_RUNS_SQL: Final = """
SELECT id, run_kind, pass_kind, known_at, created_at, state_version, package_version, package_hash, packet_id, elapsed_ms, blocking, flags
  FROM ai.match_runs WHERE fixture_id = %(fixture)s ORDER BY known_at, id
"""
PACKETS_SQL: Final = """
SELECT id, fixture_id, packet_version, as_of, built_at, packet_hash, missing, approx_tokens
  FROM ai.match_packets WHERE id = ANY(%(ids)s)
"""
DAY_SELECTIONS_OF_DAY_SQL: Final = """
SELECT DISTINCT d.fixture_id, d.market_key, d.selection, d.line
  FROM intel.decisions d
 WHERE d.known_at >= %(start)s AND d.known_at < %(end)s AND d.decision_version = %(version)s
 ORDER BY 1, 2, 3, 4
"""
PUBLISHED_OF_DAY_SQL: Final = """
SELECT DISTINCT d.fixture_id, d.market_key, d.selection, d.line
  FROM intel.day_selections s JOIN intel.decisions d ON d.id = ANY(s.decision_ids)
 WHERE s.day = %(day)s AND d.decision_version = %(version)s
UNION
SELECT DISTINCT p.fixture_id, p.market_key, p.selection, p.line
  FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id JOIN picks.picks p ON p.id = i.pick_id
 WHERE s.day = %(day)s
 ORDER BY 1, 2, 3, 4
"""


# ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _all(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, dict(params))
        return list(cur.fetchall())


def _one(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    rows = _all(conn, sql, params)
    return rows[0] if rows else None


@dataclass
class _Selection:
    fixture_id: int
    market_key: str | None
    selection: str | None
    line: Decimal | None


def _resolve(conn: psycopg.Connection[Any], *, pick_id: int | None, decision_id: int | None, fixture_id: int | None, market_key: str | None,
             selection: str | None, line: Decimal | float | int | str | None, decision_version: str) -> tuple[str, _Selection | None, str, Span | None]:
    """The anchor asked for -> (anchor label, the selection it names or None, the decision layer, a span saying the anchor is not there)."""
    anchors = [a for a in (pick_id, decision_id, fixture_id) if a is not None]
    if len(anchors) != 1:
        raise ValueError("name exactly one of pick_id, decision_id, fixture_id")
    if pick_id is not None:
        row = _one(conn, PICK_SQL, {"ids": [int(pick_id)]})
        if row is None:
            return f"pick:{pick_id}", None, decision_version, Span("pick", MISSING, "picks.picks", (str(pick_id),), note="no such pick")
        return (f"pick:{pick_id}", _Selection(int(row["fixture_id"]), str(row["market_key"]), str(row["selection"]), Decimal(row["line"])),
                decision_version, None)
    if decision_id is not None:
        row = _one(conn, DECISION_ANCHOR_SQL, {"id": int(decision_id), "versions": [DECISION_CORE, DECISION_FAMILIES]})
        if row is None:
            return (f"decision:{decision_id}", None, decision_version,
                    Span("decision", MISSING, "intel.decisions", (str(decision_id),), note="no such decision in either layer"))
        return (f"decision:{decision_id}", _Selection(int(row["fixture_id"]), str(row["market_key"]), str(row["selection"]), Decimal(row["line"])),
                str(row["decision_version"]), None)
    assert fixture_id is not None
    if (market_key is None) != (selection is None):
        raise ValueError("a selection needs both market_key and selection (line defaults to 0)")
    if market_key is None:
        if line is not None:
            raise ValueError("a line needs market_key and selection")
        return f"fixture:{fixture_id}", _Selection(int(fixture_id), None, None, None), decision_version, None
    return (f"fixture:{fixture_id}", _Selection(int(fixture_id), market_key, selection, Decimal(spell_line(line))), decision_version, None)


def trace_of(conn: psycopg.Connection[Any], *, pick_id: int | None = None, decision_id: int | None = None, fixture_id: int | None = None,
             market_key: str | None = None, selection: str | None = None, line: Decimal | float | int | str | None = None,
             decision_version: str = DECISION_CORE) -> Trace:
    """The trace of a pick, of a decision, of a selection (fixture + market + selection [+ line, 0 by default]) or of a match (fixture alone).

    A pick and a decision are traced as their selection: every checkpoint, every pick and every review of it. ``decision_version`` is the
    layer read for a pick or a fixture (a decision brings its own). Read-only: SELECTs on the caller's connection, nothing committed."""
    anchor, sel, version, absent = _resolve(conn, pick_id=pick_id, decision_id=decision_id, fixture_id=fixture_id, market_key=market_key,
                                            selection=selection, line=line, decision_version=decision_version)
    if sel is None:
        assert absent is not None
        spans = [absent] + [Span(k, MISSING, "", note=f"the anchor {anchor} was not found: nothing to follow") for k in MANDATORY
                            if k != absent.kind]
        return Trace(VERSION, anchor, "selection", None, None, None, None, None, None, version, order(spans))
    return _assemble(conn, anchor, sel, version)


def _assemble(conn: psycopg.Connection[Any], anchor: str, sel: _Selection, version: str) -> Trace:
    scope = "match" if sel.market_key is None else "selection"
    families = version == DECISION_FAMILIES
    spans: list[Span] = []
    fid = sel.fixture_id
    key = {"fixture": fid, "market": sel.market_key, "selection": sel.selection, "line": sel.line}

    # fixture
    fx = _one(conn, FIXTURE_SQL, {"fixture": fid})
    if fx is None:
        spans.append(Span("fixture", MISSING, "core.fixtures", (str(fid),), note="no such fixture"))
    else:
        spans.append(Span("fixture", PRESENT, "core.fixtures", (str(fid),), fx["kickoff_at"],
                          payload=compact(fx, ("status_short", "status_group", "competition_id", "competition_season_id", "updated_at"))))

    # decisions (read first: the moment of the first one is what the data class is read as of)
    decisions = _all(conn, MATCH_DECISIONS_SQL if scope == "match" else SELECTION_DECISIONS_SQL, key | {"version": version})
    first_at = decisions[0]["known_at"] if decisions else None

    # data quality
    if fx is not None:
        spans.append(_data_quality(conn, fx, first_at, decisions))
    else:
        spans.append(Span("data_quality", MISSING, "analytics.competition_data_scores", note="no fixture to read it for"))

    for d in decisions:
        spans.append(_decision_span(d))
    if not decisions:
        spans.append(Span("decision", MISSING, "intel.decisions", note=f"no decision of the {'match' if scope == 'match' else 'selection'} "
                                                                       f"under {version}"))

    # picks
    pick_ids = _ids(d["pick_id"] for d in decisions)
    if anchor.startswith("pick:"):
        pick_ids = _ids([*pick_ids, int(anchor.split(":", 1)[1])])
    picks = {int(p["id"]): p for p in _all(conn, PICK_SQL, {"ids": pick_ids})} if pick_ids else {}
    for pid in pick_ids:
        p = picks.get(pid)
        if p is None:
            spans.append(Span("pick", MISSING, "picks.picks", (str(pid),), note="named by a decision, not found"))
            continue
        spans.append(Span("pick", PRESENT, "picks.picks", (str(pid),), p["created_at"],
                          _versions(p, {"rule": "decision_rule_version", "code": "code_version"}),
                          compact(p, ("candidate_id", "prediction_id", "market_odds", "bookmaker_id", "odds_captured_at", "p_calibrated",
                                      "p_market_fair", "ev", "edge", "stake_units", "mode", "status", "published_at"))))
    if not pick_ids and scope == "selection":
        spans.append(Span("pick", NOT_APPLICABLE if families else MISSING, "picks.picks",
                          note="a decision of the families never becomes a pick" if families else "no decision names a pick"))

    # model and forecast
    spans.extend(_models(conn, decisions, list(picks.values()), scope))
    spans.extend(_forecasts(conn, list(picks.values()), scope, families))

    # price
    if scope == "selection":
        spans.extend(_prices(conn, key, decisions, list(picks.values())))

    # reviews
    reviews, review_spans = _reviews(conn, key, decisions, scope)
    spans.extend(review_spans)

    # the agents (fixture level)
    runs = _all(conn, AGENT_RUNS_SQL, {"fixture": fid})
    spans.extend(_agent_runs(runs))
    spans.extend(_agent_tasks(_all(conn, AGENT_TASKS_SQL, {"fixture": fid})))
    match_runs = _all(conn, MATCH_RUNS_SQL, {"fixture": fid})
    spans.extend(_match_runs(match_runs))
    spans.extend(_packets(conn, _ids([*(r["packet_id"] for r in reviews), *(m["packet_id"] for m in match_runs)])))

    # evidence
    cited: dict[int, list[str]] = {}
    for d in decisions:
        for e in d["evidence_ids"] or ():
            cited.setdefault(int(e), []).append(f"decision {d['id']}")
    for r in reviews:
        for e in r["evidence_ids"] or ():
            cited.setdefault(int(e), []).append(f"review {r['id']}")
    for run in runs:
        for e in run["evidence_ids"] or ():
            cited.setdefault(int(e), []).append(f"agent run {run['id']}")
    spans.extend(cited_evidence(cited))

    # publication, settlement, outcome
    spans.extend(_publication(conn, pick_ids, _ids(d["id"] for d in decisions)))
    if scope == "selection":
        results = {int(r["pick_id"]): r for r in _all(conn, PICK_RESULTS_SQL, {"ids": pick_ids})} if pick_ids else {}
        spans.extend(_settlement(fx, pick_ids, results))
        spans.extend(_outcomes(conn, decisions, results, version))

    for kind, (source, note) in NOT_READ_SPANS.items():
        spans.append(Span(kind, NOT_READ, source, note=note))

    trace_id = match_trace_id(fid) if scope == "match" else selection_trace_id(fid, str(sel.market_key), str(sel.selection), sel.line)
    return Trace(VERSION, anchor, scope, trace_id, match_trace_id(fid), fid, sel.market_key, sel.selection,
                 None if sel.line is None else spell_line(sel.line), version, order(spans))


def _data_quality(conn: psycopg.Connection[Any], fx: Mapping[str, Any], first_at: datetime | None, decisions: Sequence[Mapping[str, Any]]) -> Span:
    score = _one(conn, DATA_SCORE_SQL, {"season": fx["competition_season_id"], "at": first_at})
    validation = _one(conn, VALIDATION_SQL, {"fixture": fx["id"]})
    issues = _all(conn, ISSUES_SQL, {"fixture": fx["id"]})
    recorded = next((f for f in compact_filters(decisions[0]["filters"]) if f.get("key") == "data"), None) if decisions else None
    payload: dict[str, Any] = {
        "validation_state": None if validation is None else validation["state"],
        "open_issues": len(issues), "issue_codes": sorted({str(i["code"]) for i in issues}),
        "decision_filter": recorded,
    }
    versions = {} if validation is None else {"validation_rule": str(validation["rule_version"])}
    if score is None:
        return Span("data_quality", MISSING, "analytics.competition_data_scores", (), None, versions, payload,
                    note="no data class of the competition" + ("" if first_at is None else " as of the first decision"))
    payload |= {"class": score["class"], "score": plain(score["score"]), "as_of": plain(first_at)}
    return Span("data_quality", PRESENT, "analytics.competition_data_scores",
                (f"{score['competition_season_id']}@{score['computed_at'].isoformat()}",), score["computed_at"],
                versions | {"data_rule": str(score["rule_version"])}, payload)


def _decision_span(d: Mapping[str, Any]) -> Span:
    versions = _versions(d, {"decision": "decision_version", "code": "code_version", "score": "score_version", "stake": "stake_version",
                             "calibrator": "calibrator_version", "calibrator_method": "calibrator_method", "calibrator_role": "calibrator_role"})
    payload = compact(d, ("checkpoint", "state", "reasons", "pick_id", "model_name", "model_version_id", "odds", "bookmaker_id", "price_at",
                          "n_bookmakers", "p_model", "p_cal", "calibrator_id", "p_market", "ev_cal", "edge_cal", "score", "stake_units",
                          "context_status", "review_id", "evidence_ids", "input_hash"))
    payload["filters"] = compact_filters(d["filters"])
    payload["selection_trace_id"] = str(selection_trace_id(int(d["fixture_id"]), str(d["market_key"]), str(d["selection"]), d["line"]))
    return Span("decision", PRESENT, "intel.decisions", (str(d["id"]),), d["known_at"], versions, payload)


def _models(conn: psycopg.Connection[Any], decisions: Sequence[Mapping[str, Any]], picks: Sequence[Mapping[str, Any]], scope: str) -> list[Span]:
    ids = _ids([*(d["model_version_id"] for d in decisions), *(p["model_version_id"] for p in picks)])
    if not ids:
        return [Span("model", MISSING if scope == "selection" else NOT_APPLICABLE, "models.model_versions",
                     note="no decision or pick records a model version")]
    found = {int(r["id"]): r for r in _all(conn, MODELS_SQL, {"ids": ids})}
    spans = []
    for mid in ids:
        r = found.get(mid)
        if r is None:
            spans.append(Span("model", MISSING, "models.model_versions", (str(mid),), note="named, not found"))
        else:
            spans.append(Span("model", PRESENT, "models.model_versions", (str(mid),), r["created_at"],
                              {"model": str(r["model"]), "version": str(r["version"]), "code": str(r["code_version"])},
                              compact(r, ("status",))))
    return spans


def _forecasts(conn: psycopg.Connection[Any], picks: Sequence[Mapping[str, Any]], scope: str, families: bool) -> list[Span]:
    if not picks:
        if scope == "match":
            return []
        return [Span("forecast", NOT_APPLICABLE, "models.predictions",
                     note="a decision of the families rests on no pick" if families else "no pick to read the prediction of")]
    ids = _ids(p["prediction_id"] for p in picks)
    found = {int(r["id"]): r for r in _all(conn, PREDICTIONS_SQL, {"ids": ids})} if ids else {}
    spans = []
    for p in picks:
        if p["prediction_id"] is None:
            spans.append(Span("forecast", MISSING, "models.predictions", note=f"pick {p['id']} names no prediction"))
            continue
        r = found.get(int(p["prediction_id"]))
        if r is None:
            spans.append(Span("forecast", MISSING, "models.predictions", (str(p["prediction_id"]),), note=f"named by pick {p['id']}, not found"))
            continue
        spans.append(Span("forecast", PRESENT, "models.predictions", (str(r["id"]),), r["created_at"],
                          {"model_version_id": str(r["model_version_id"]), "features": str(r["feature_set_hash"])},
                          compact(r, ("p_raw", "p_calibrated", "p_lo", "p_hi", "calibrator_id", "data_cutoff_ts")) | {"pick_id": int(p["id"])}))
    return spans


def _prices(conn: psycopg.Connection[Any], key: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]],
            picks: Sequence[Mapping[str, Any]]) -> list[Span]:
    wanted: dict[tuple[datetime, str], list[str]] = {}
    for d in decisions:
        if d["price_at"] is not None:
            wanted.setdefault((d["price_at"], "shin"), []).append(f"decision {d['id']}")
    for p in picks:
        if p["consensus_as_of"] is not None and p["consensus_method"] is not None:
            wanted.setdefault((p["consensus_as_of"], str(p["consensus_method"])), []).append(f"pick {p['id']}")
    spans: list[Span] = []
    if wanted:
        rows = _all(conn, CONSENSUS_SQL, dict(key) | {"as_of": sorted({a for a, _ in wanted})})
        found = {(r["as_of"], str(r["devig_method"])): r for r in rows}
        for (as_of, method), users in sorted(wanted.items()):
            row_id = f"{key['fixture']}/{key['market']}/{key['selection']}/{spell_line(key['line'])}@{as_of.isoformat()}/{method}"
            r = found.get((as_of, method))
            if r is None:
                spans.append(Span("price", MISSING, "market.market_consensus", (row_id,), as_of, {"devig": method},
                                  {"used_by": users}, note="the consensus a row says it priced against is not there"))
            else:
                spans.append(Span("price", PRESENT, "market.market_consensus", (row_id,), as_of, {"devig": method},
                                  compact(r, ("p_fair", "n_bookmakers", "overround", "best_odds", "best_bookmaker_id", "dispersion"))
                                  | {"used_by": users}))
    for p in picks:
        snap = _one(conn, SNAPSHOT_SQL, dict(key) | {"bookmaker": p["bookmaker_id"], "captured": p["odds_captured_at"]})
        row_id = f"{key['fixture']}/{p['bookmaker_id']}/{key['market']}/{key['selection']}/{spell_line(key['line'])}@{p['odds_captured_at'].isoformat()}"
        if snap is None:
            spans.append(Span("price", MISSING, "market.odds_snapshots", (row_id,), p["odds_captured_at"], payload={"used_by": [f"pick {p['id']}"]},
                              note="the snapshot the pick took its odds from is not there (pruned, or never captured)"))
        else:
            spans.append(Span("price", PRESENT, "market.odds_snapshots", (row_id,), snap["captured_at"], payload=compact(
                snap, ("odds_decimal", "minutes_to_ko", "source", "payload_hash")) | {"used_by": [f"pick {p['id']}"]}))
    if not spans:
        spans.append(Span("price", NOT_APPLICABLE, "market.market_consensus",
                          note="no decision recorded a price (filter 3) and no pick names one"))
    return spans


def _review_span(r: Mapping[str, Any], *, cited_by: Sequence[str]) -> Span:
    payload = compact(r, ("engine", "decision", "confidence", "status", "mode", "cost_usd", "packet_id", "pick_id", "input_hash", "error"))
    payload |= {"evidence_cited": len(r["evidence_ids"] or ()), "usage_ids": plain(list(r["usage_ids"] or ())),
                "shadow": str(r["engine"]) in SHADOW_ENGINE_NAMES}
    if cited_by:
        payload["cited_by"] = list(cited_by)
    return Span("review", PRESENT, "ai.pick_reviews", (str(r["id"]),), r["reviewed_at"],
                _versions(r, {"engine": "engine_version", "provider": "provider", "model": "model"}), payload)


SHADOW_ENGINE_NAMES: Final = frozenset({"ma-v1", "ma-v1-h", "cs-v1"})
"""The engines ``SHADOW_REVIEWS_SQL`` names (held equal to ``fbi.ai.config.SHADOW_ENGINES`` by a test)."""
PRODUCTION_ENGINE_NAMES: Final = frozenset({"rules", "llm", "combined"})
"""The engines ``PRODUCTION_REVIEWS_SQL`` names (held equal to ``fbi.ai.config.PRODUCTION_ENGINES`` by a test)."""


def _reviews(conn: psycopg.Connection[Any], key: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]],
             scope: str) -> tuple[list[dict[str, Any]], list[Span]]:
    cited: dict[int, list[str]] = {}
    for d in decisions:
        if d["review_id"] is not None:
            cited.setdefault(int(d["review_id"]), []).append(f"decision {d['id']}")
    rows: dict[int, dict[str, Any]] = {}
    if cited:
        rows |= {int(r["id"]): r for r in _all(conn, CITED_REVIEWS_SQL, {"ids": sorted(cited)})}
    for sql in (PRODUCTION_REVIEWS_SQL, SHADOW_REVIEWS_SQL):
        rows |= {int(r["id"]): r for r in _all(conn, sql, key)}
    spans = [_review_span(r, cited_by=cited.get(rid, [])) for rid, r in rows.items()]
    spans += [Span("review", MISSING, "ai.pick_reviews", (str(rid),), note=f"cited by {', '.join(users)}, not found")
              for rid, users in sorted(cited.items()) if rid not in rows]
    if not cited and scope == "selection":
        statuses = sorted({str(d["context_status"]) for d in decisions})
        spans.append(Span("review", NOT_APPLICABLE, "ai.pick_reviews",
                          note="no decision cites a review" + (f" (context: {', '.join(statuses)})" if statuses else "")))
    return list(rows.values()), spans


def _agent_runs(runs: Sequence[Mapping[str, Any]]) -> list[Span]:
    if not runs:
        return [Span("agent_run", MISSING, "ai.agent_runs", note="no agent run recorded for the fixture (optional span)")]
    return [Span("agent_run", PRESENT, "ai.agent_runs", (str(r["id"]),), r["started_at"],
                 _versions(r, {"agent": "agent_version", "prompt": "prompt_version", "schema": "schema_version", "router": "router_version",
                               "model": "model"}),
                 compact(r, ("agent", "task_kind", "pass_kind", "run_kind", "status", "verdict", "known_at", "finished_at", "attempt",
                             "input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens", "thinking_tokens", "cost_usd",
                             "latency_ms", "queue_ms", "batch_id", "parent_run_id", "workspace", "error"))
                 | {"evidence_cited": len(r["evidence_ids"] or ())}) for r in runs]


def _agent_tasks(tasks: Sequence[Mapping[str, Any]]) -> list[Span]:
    if not tasks:
        return [Span("agent_task", MISSING, "ai.agent_tasks", note="no agent task recorded for the fixture (optional span)")]
    return [Span("agent_task", PRESENT, "ai.agent_tasks", (str(t["id"]),), t["created_at"],
                 _versions(t, {"agent": "agent_version", "prompt": "prompt_version", "schema": "schema_version", "router": "router_version",
                               "model": "model", "input": "input_version"}),
                 compact(t, ("agent", "task_kind", "pass_kind", "run_kind", "state", "attempts", "priority", "est_cost_usd", "started_at",
                             "finished_at", "last_run_id", "batch_id"))) for t in tasks]


def _match_runs(runs: Sequence[Mapping[str, Any]]) -> list[Span]:
    if not runs:
        return [Span("match_run", MISSING, "ai.match_runs", note="no match run recorded for the fixture (optional span)")]
    return [Span("match_run", PRESENT, "ai.match_runs", (str(r["id"]),), r["known_at"],
                 _versions(r, {"state": "state_version", "package": "package_version"}),
                 compact(r, ("run_kind", "pass_kind", "packet_id", "elapsed_ms", "blocking", "flags", "package_hash"))) for r in runs]


def _packets(conn: psycopg.Connection[Any], ids: Sequence[int]) -> list[Span]:
    if not ids:
        return [Span("packet", NOT_APPLICABLE, "ai.match_packets", note="no review or match run cites a packet")]
    found = {int(r["id"]): r for r in _all(conn, PACKETS_SQL, {"ids": list(ids)})}
    return [Span("packet", PRESENT, "ai.match_packets", (str(i),), found[i]["as_of"], {"packet": str(found[i]["packet_version"])},
                 compact(found[i], ("built_at", "packet_hash", "missing", "approx_tokens")))
            if i in found else Span("packet", MISSING, "ai.match_packets", (str(i),), note="cited, not found") for i in ids]


def cited_evidence(cited: Mapping[int, Sequence[str]]) -> list[Span]:
    """The evidence the trace's rows cite, one span per id with who cites it, ``not_read``: the table itself is not this module's to read
    (see the module), so nothing here says whether an id still resolves."""
    if not cited:
        return [Span("evidence", NOT_APPLICABLE, "ai.evidence", note="nothing in the trace cites evidence")]
    return [Span("evidence", NOT_READ, "ai.evidence", (str(eid),), payload={"cited_by": sorted(set(cited[eid]))},
                 note=EVIDENCE_NOTE) for eid in sorted(cited)]


def _publication(conn: psycopg.Connection[Any], pick_ids: Sequence[int], decision_ids: Sequence[int]) -> list[Span]:
    spans: list[Span] = []
    if pick_ids:
        for i in _all(conn, DAILY_ITEMS_SQL, {"ids": list(pick_ids)}):
            spans.append(Span("publication", PRESENT, "picks.daily_set_items", (f"{i['set_id']}/{i['rank']}",), i["selected_at"],
                              {"rule": str(i["rule_version"])},
                              compact(i, ("day", "source", "set_status", "rank", "pick_id", "stage", "odds", "status", "profit_units",
                                          "settled_at"))))
    if decision_ids:
        for s in _all(conn, DAY_SELECTIONS_SQL, {"ids": list(decision_ids)}):
            spans.append(Span("publication", PRESENT, "intel.day_selections", (str(s["id"]),), s["selected_at"], {"rule": str(s["rule_version"])},
                              compact(s, ("day", "kind", "rank", "decision_ids", "odds", "stake_units"))))
    if not spans:
        spans.append(Span("publication", NOT_APPLICABLE, "picks.daily_set_items", note="not among the picks of any day (optional span)"))
    return spans


def _settlement(fx: Mapping[str, Any] | None, pick_ids: Sequence[int], results: Mapping[int, Mapping[str, Any]]) -> list[Span]:
    status = None if fx is None else fx["status_group"]
    if not settlement_expected(status):
        return [Span("settlement", NOT_APPLICABLE, "picks.pick_results", note=f"the match is not finished ({status or 'unknown'})")]
    if not pick_ids:
        return [Span("settlement", NOT_APPLICABLE, "picks.pick_results", note="no pick to settle")]
    spans = []
    for pid in pick_ids:
        r = results.get(pid)
        if r is None:
            spans.append(Span("settlement", MISSING, "picks.pick_results", (str(pid),), note="the match is finished and the pick has no result"))
        else:
            spans.append(Span("settlement", PRESENT, "picks.pick_results", (str(pid),), r["settled_at"],
                              _versions(r, {"rule": "rule_version"}),
                              compact(r, ("result_status", "profit_units", "settled_by", "settlement_basis"))))
    return spans


def _outcomes(conn: psycopg.Connection[Any], decisions: Sequence[Mapping[str, Any]], results: Mapping[int, Mapping[str, Any]],
              version: str) -> list[Span]:
    due = [d for d in decisions if d["pick_id"] is not None and outcome_expected((results.get(int(d["pick_id"])) or {}).get("result_status"))]
    if not due:
        return [Span("outcome", NOT_APPLICABLE, "intel.decision_outcomes", note="no decision whose pick has a final result")]
    found = {int(o["decision_id"]): o for o in _all(conn, OUTCOMES_SQL, {"ids": [int(d["id"]) for d in due], "version": version})}
    spans = []
    for d in due:
        o = found.get(int(d["id"]))
        if o is None:
            spans.append(Span("outcome", MISSING, "intel.decision_outcomes", (str(d["id"]),), note="its pick is settled and it has no outcome"))
        else:
            spans.append(Span("outcome", PRESENT, "intel.decision_outcomes", (str(d["id"]),), o["computed_at"], {"outcome": str(o["version"])},
                              compact(o, ("result_status", "profit_flat", "profit_staked", "clv", "close_odds", "close_as_of", "settled_at"))))
    return spans


# ── coverage ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def unit_of(population: str, traces: Sequence[Trace]) -> CoverageUnit:
    """The share of complete traces among ``traces``, and what the others lack (pure)."""
    lacking: Counter[str] = Counter()
    incomplete: list[str] = []
    complete = 0
    for t in traces:
        c = completeness(t)
        if c.complete:
            complete += 1
        else:
            lacking.update(c.missing)
            incomplete.append(str(t.trace_id))
    return CoverageUnit(population, len(traces), complete, tuple(sorted(lacking.items(), key=lambda kv: (-kv[1], kv[0]))),
                        tuple(incomplete[:SAMPLE]))


def coverage(conn: psycopg.Connection[Any], day: date, *, decision_version: str = DECISION_CORE) -> Coverage:
    """The P0 metric for one day (Bogotá, ``fbi.ai.calendar``): the share of the selections decided that day, and of the ones published that
    day, whose trace is complete. Each selection is traced once, whichever population it is in."""
    start, end = day_bounds(day)
    decided = _all(conn, DAY_SELECTIONS_OF_DAY_SQL, {"start": start, "end": end, "version": decision_version})
    published = _all(conn, PUBLISHED_OF_DAY_SQL, {"day": day, "version": decision_version})
    cache: dict[tuple[int, str, str, str], Trace] = {}

    def traced(rows: Sequence[Mapping[str, Any]]) -> list[Trace]:
        out = []
        for r in rows:
            k = (int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), spell_line(r["line"]))
            if k not in cache:
                cache[k] = trace_of(conn, fixture_id=k[0], market_key=k[1], selection=k[2], line=k[3], decision_version=decision_version)
            out.append(cache[k])
        return out

    return Coverage(VERSION, day, decision_version, unit_of("selections", traced(decided)), unit_of("published", traced(published)))
