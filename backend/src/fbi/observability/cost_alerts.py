"""The cost alerts of the AI layer (``cost-alerts-v1``, Plan Maestro IA, P3: the observability rail).

REPORT ONLY. This module reads the ledger the AI already writes and says OK / WATCH / ALERT with its evidence. It writes nothing - not even
``ai.budget_alerts`` or ``ai.envelope_alerts``, which ``fbi.ai.budget_v3.check_alerts`` owns - and nothing it says degrades, stops or
switches anything: the budget's states (``budget_v3.state_of``) are the only thing that acts on money, and they do not read this.

PER AGENT VERSION AND DAY (``ai.agent_runs`` of the bench's ``RUN_KINDS``, by Bogotá day of ``started_at``):

    figures                   runs, cost, cost per run, matches (distinct ``fixture_id``), cost per match, and over the window that ends
                              on the day the cost per USEFUL SIGNAL by the bench's own definition (``fbi.ai.eval_bench``: a signal row of
                              ``intel.agent_attributions`` whose outcome is HIT) - figures, not rules: the plan sets no threshold for them
    cost_per_match_agent      the day's cost per match above ``FACTOR`` times the median of the same figure over the ``BASELINE_DAYS``
                              before it (the plan's rule, section 22: «coste por partido > 2x la mediana de 14 días») -> ALERT

PRODUCTION AS A WHOLE:

    cost_per_match_production the day's production spend (``budget_v3.costs_by_day``: the production workspace and the analyst) per
                              match with a market of the day's opened plan (``ai.day_plans``; the budget's unit cost), against
                              ``FACTOR`` x the median of the ``BASELINE_DAYS`` before -> ALERT
    cache_hit_low             the real-time cacheable input (``gate_a.CACHE_SQL``: production, Anthropic, not Batch, ok) read from the
                              cache - reads / (reads + writes), gate A's definition - below ``CACHE_HIT_MIN`` on each of the
                              ``CACHE_DAYS`` days ending on the day (the plan's alarm, section 28: «salta si sus aciertos bajan del 40 %
                              tres días seguidos») -> ALERT. A day with less than ``MIN_CACHEABLE_TOKENS`` of cacheable input measured
                              nothing and breaks the streak
    envelope_projection       production's month projected by ``budget_v3.forecast`` (as of the day's end) against
                              ``FBI_AI_MONTHLY_BUDGET_USD``; the LAB's month (spent + its typical day, ``budget_v3.lab_day``, for each day
                              left) against its allocation; both together against the joint ceiling. ``PROJECTION_WATCH`` % -> WATCH,
                              ``PROJECTION_ALERT`` % -> ALERT (the thresholds of ``budget_v3.PROJECTION_ALERTS``)

MINIMUMS (engineering choices of this module, not the plan's): a baseline needs ``MIN_BASELINE_DAYS`` days with matches, and a day
``MIN_DAY_MATCHES`` matches, or the rule is INSUFFICIENT and says why. Changing any constant is ``cost-alerts-v2``, never an edit."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.ai import budget_v3, eval_bench, gate_a
from fbi.ai.calendar import day_start, days_left_in_month
from fbi.ai.config import AiSettings

VERSION: Final = "cost-alerts-v1"

OK: Final = "OK"
WATCH: Final = "WATCH"
ALERT: Final = "ALERT"
INSUFFICIENT: Final = "INSUFFICIENT"
SEVERITY: Final = {INSUFFICIENT: 0, OK: 0, WATCH: 1, ALERT: 2}

FACTOR: Final = Decimal(2)
"""The plan's (section 22)."""
BASELINE_DAYS: Final = 14
"""The plan's (section 22)."""
MIN_BASELINE_DAYS: Final = 7
MIN_DAY_MATCHES: Final = 5
CACHE_HIT_MIN: Final = gate_a.CACHE_HIT_MIN
"""40 %: the plan's (section 28), the same figure gate A judges by."""
CACHE_DAYS: Final = 3
"""The plan's (section 28)."""
MIN_CACHEABLE_TOKENS: Final = 10_000
PROJECTION_WATCH, PROJECTION_ALERT = budget_v3.PROJECTION_ALERTS

_USD: Final = Decimal("0.000001")


def _usd(x: Decimal | None) -> str | None:
    return None if x is None else str(x.quantize(_USD))


def _pct(x: Decimal | None) -> str | None:
    return None if x is None else f"{(x * 100).quantize(Decimal('0.01'))}"


@dataclass(frozen=True)
class Finding:
    """One rule on one subject."""

    rule: str
    subject: str
    status: str
    summary: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {"rule": self.rule, "version": VERSION, "severity": self.status, "subject": self.subject, "summary": self.summary,
                "evidence": dict(self.evidence)}


# ── the pure rules ────────────────────────────────────────────────────────────────────────────────────────────────────


def ratio(cost: Decimal, n: int) -> Decimal | None:
    return None if n <= 0 else cost / n


def cost_jump(rule: str, subject: str, *, day: date, today: tuple[Decimal, int],
              history: Mapping[date, tuple[Decimal, int]]) -> Finding:
    """The day's cost per match against ``FACTOR`` x the median of the ``BASELINE_DAYS`` before it. ``today`` and ``history`` are
    (cost, matches) per day; a baseline day without matches is not a day of the baseline."""
    first = day - timedelta(days=BASELINE_DAYS)
    base = {d: c / n for d, (c, n) in sorted(history.items()) if first <= d < day and n > 0}
    cost, matches = today
    per = ratio(cost, matches)
    ev: dict[str, Any] = {"day": day.isoformat(), "cost_usd": _usd(cost), "matches": matches, "cost_per_match_usd": _usd(per),
                          "baseline_days": len(base), "baseline_from": first.isoformat(), "factor": str(FACTOR),
                          "baseline_per_day_usd": {d.isoformat(): _usd(v) for d, v in base.items()}}
    if len(base) < MIN_BASELINE_DAYS:
        return Finding(rule, subject, INSUFFICIENT, f"{len(base)} baseline days with matches, {MIN_BASELINE_DAYS} needed", ev)
    median = Decimal(statistics.median(base.values()))
    ev |= {"baseline_median_usd": _usd(median), "threshold_usd": _usd(median * FACTOR)}
    if matches < MIN_DAY_MATCHES or per is None:
        return Finding(rule, subject, INSUFFICIENT, f"{matches} matches on the day, {MIN_DAY_MATCHES} needed", ev)
    ev["ratio_to_median"] = None if median <= 0 else str((per / median).quantize(Decimal("0.01")))
    if per > median * FACTOR:
        return Finding(rule, subject, ALERT, f"cost per match {per:.4f} USD over {matches} matches, above {FACTOR} x the "
                                             f"{BASELINE_DAYS}-day median {median:.4f} USD", ev)
    return Finding(rule, subject, OK, "within the rule", ev)


def cache_streak(*, day: date, per_day: Mapping[date, tuple[int, int]]) -> Finding:
    """``per_day``: (cache reads, cache writes) of the real-time cacheable input. ALERT when each of the ``CACHE_DAYS`` days ending on
    ``day`` measured (>= ``MIN_CACHEABLE_TOKENS``) and read less than ``CACHE_HIT_MIN``."""
    days = [day - timedelta(days=k) for k in range(CACHE_DAYS - 1, -1, -1)]
    shown: dict[str, Any] = {}
    low = 0
    measured = 0
    for d in days:
        reads, writes = per_day.get(d, (0, 0))
        total = reads + writes
        hit = None if total <= 0 else Decimal(reads) / Decimal(total)
        ok_size = total >= MIN_CACHEABLE_TOKENS
        shown[d.isoformat()] = {"read": reads, "written": writes, "hit_rate_pct": _pct(hit), "measured": ok_size}
        if ok_size:
            measured += 1
            if hit is not None and hit < CACHE_HIT_MIN:
                low += 1
    ev = {"days": shown, "minimum_hit_rate_pct": _pct(CACHE_HIT_MIN), "days_needed": CACHE_DAYS,
          "min_cacheable_tokens": MIN_CACHEABLE_TOKENS}
    subject = "production real-time cacheable input"
    if measured < CACHE_DAYS:
        return Finding("cache_hit_low", subject, INSUFFICIENT,
                       f"{measured} of the last {CACHE_DAYS} days had >= {MIN_CACHEABLE_TOKENS} cacheable tokens", ev)
    if low == CACHE_DAYS:
        return Finding("cache_hit_low", subject, ALERT,
                       f"cache hit rate below {_pct(CACHE_HIT_MIN)} % on each of the last {CACHE_DAYS} days", ev)
    return Finding("cache_hit_low", subject, OK, f"{low} of the last {CACHE_DAYS} days below the minimum", ev)


def envelope(subject: str, *, projected: Decimal, cap: Decimal, evidence: Mapping[str, Any]) -> Finding:
    ev = dict(evidence) | {"projected_usd": _usd(projected), "cap_usd": _usd(cap),
                           "thresholds_pct": [PROJECTION_WATCH, PROJECTION_ALERT]}
    if cap <= 0:
        return Finding("envelope_projection", subject, INSUFFICIENT, "no envelope to project against", ev)
    share = projected / cap
    ev["share_pct"] = _pct(share)
    status = ALERT if share * 100 >= PROJECTION_ALERT else WATCH if share * 100 >= PROJECTION_WATCH else OK
    summary = f"projected {projected:.2f} USD, {_pct(share)} % of {cap:.2f} USD"
    return Finding("envelope_projection", subject, status, summary, ev)


def lab_projection(*, spent_month: Decimal, typical_day: Decimal, day: date) -> Decimal:
    """The LAB's month by its last day: what it spent up to the end of ``day`` and a typical day for each day after it."""
    return spent_month + typical_day * (days_left_in_month(day) - 1)


# ── the ledger (read-only) ────────────────────────────────────────────────────────────────────────────────────────────

MATCHES_SQL: Final = """
SELECT r.agent, r.agent_version, (r.started_at AT TIME ZONE 'America/Bogota')::date AS day,
       count(DISTINCT r.fixture_id) AS matches
  FROM ai.agent_runs r
 WHERE r.run_kind = ANY(%(kinds)s) AND r.started_at >= %(since)s AND r.started_at < %(until)s AND r.fixture_id IS NOT NULL
 GROUP BY 1, 2, 3
"""
"""The matches each agent version ran on per day, over the bench's runs (``eval_bench.RUN_KINDS``)."""


@dataclass(frozen=True)
class AgentDay:
    agent: str
    version: str
    day: date
    runs: int
    cost: Decimal
    matches: int

    def as_json(self) -> dict[str, Any]:
        return {"day": self.day.isoformat(), "runs": self.runs, "cost_usd": _usd(self.cost), "cost_per_run_usd": _usd(ratio(self.cost, self.runs)),
                "matches": self.matches, "cost_per_match_usd": _usd(ratio(self.cost, self.matches))}


def agent_days(cells: Sequence[eval_bench.Cell], matches: Mapping[tuple[str, str, date], int]) -> list[AgentDay]:
    out: list[AgentDay] = []
    for c in cells:
        assert c.day is not None
        out.append(AgentDay(c.agent, c.version, c.day, c.runs, c.cost, matches.get((c.agent, c.version, c.day), 0)))
    return out


def agent_findings(days: Sequence[AgentDay], *, day: date, useful: Mapping[tuple[str, str], tuple[int, Decimal | None]]
                   ) -> list[Finding]:
    """The plan's cost-per-match rule for every agent version that ran on ``day``, with its figures of the day as evidence."""
    by_version: dict[tuple[str, str], dict[date, AgentDay]] = defaultdict(dict)
    for a in days:
        by_version[(a.agent, a.version)][a.day] = a
    out: list[Finding] = []
    for (agent, version), ds in sorted(by_version.items()):
        today = ds.get(day)
        if today is None:
            continue
        f = cost_jump("cost_per_match_agent", f"{agent} {version}", day=day, today=(today.cost, today.matches),
                      history={d: (a.cost, a.matches) for d, a in ds.items() if d != day})
        signals, per_useful = useful.get((agent, version), (0, None))
        ev = dict(f.evidence) | {"today": today.as_json(), "window_useful_signals": signals,
                                 "window_cost_per_useful_signal_usd": _usd(per_useful)}
        out.append(Finding(f.rule, f.subject, f.status, f.summary, ev))
    return out


@dataclass(frozen=True)
class CostReport:
    day: date
    at: datetime
    findings: tuple[Finding, ...]
    agents: tuple[AgentDay, ...]

    def alerts(self) -> list[dict[str, Any]]:
        return sorted((f.as_json() for f in self.findings if SEVERITY[f.status] > 0), key=lambda a: -SEVERITY[a["severity"]])

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "day": self.day.isoformat(), "at": self.at.isoformat(),
                "findings": [f.as_json() for f in self.findings],
                "agents_today": [{"agent": a.agent, "agent_version": a.version, **a.as_json()} for a in self.agents if a.day == self.day]}


def report(conn: psycopg.Connection[Any], *, day: date, at: datetime, settings: AiSettings) -> CostReport:
    """cost-alerts-v1 for the Bogotá day ``day`` as of ``at`` (the day's end, or now if the day is not over). Reads only."""
    first = day - timedelta(days=BASELINE_DAYS)
    since, until = day_start(first), min(day_start(day + timedelta(days=1)), at)
    bench = eval_bench.report(conn, first=first, last=day, at=at)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(MATCHES_SQL, {"kinds": list(eval_bench.RUN_KINDS), "since": since, "until": until})
        matches = {(str(a), str(v), d): int(n) for a, v, d, n in cur.fetchall()}
        cur.execute(gate_a.CACHE_SQL, {"since": day_start(day - timedelta(days=CACHE_DAYS - 1)), "until": until})
        cache = {r[0]: (int(r[1]), int(r[2])) for r in cur.fetchall()}
    cells = [c for a in bench.agents for c in a.days]
    useful = {(a.agent, a.version): (a.signals.useful, a.signals.cost_per_useful(a.totals.cost))
              for a in bench.agents if a.signals is not None}
    adays = agent_days(cells, matches)
    findings = agent_findings(adays, day=day, useful=useful)

    costs = budget_v3.costs_by_day(conn, "production", since, until)
    opened = budget_v3.plans(conn, first, day).opened
    findings.append(cost_jump("cost_per_match_production", "production (Claude + analyst) per match with a market", day=day,
                              today=(costs.get(day, Decimal(0)), opened.get(day, 0)),
                              history={d: (costs.get(d, Decimal(0)), n) for d, n in opened.items() if d != day}))
    findings.append(cache_streak(day=day, per_day=cache))

    as_of = until - timedelta(microseconds=1)
    prod = budget_v3.forecast(conn, at=as_of)
    findings.append(envelope("production month", projected=prod.projected, cap=settings.monthly_budget,
                             evidence={"spent_month_usd": _usd(prod.spent_before + prod.spent_today),
                                       "unit_cost_usd": _usd(prod.unit_cost), "unit_days": prod.unit_days}))
    lab = budget_v3.lab_day(conn, at=as_of, settings=settings)
    lab_projected = lab_projection(spent_month=lab.spent_month, typical_day=lab.typical_day, day=day)
    findings.append(envelope("LAB month", projected=lab_projected, cap=lab.allocation,
                             evidence={"lab": lab.as_json(), "envelope_usd": _usd(settings.lab_monthly_budget)}))
    findings.append(envelope("production + LAB month (joint ceiling)", projected=prod.projected + lab_projected,
                             cap=settings.joint_ceiling, evidence={"production_projected_usd": _usd(prod.projected),
                                                                   "lab_projected_usd": _usd(lab_projected)}))
    return CostReport(day, at, tuple(findings), tuple(adays))
