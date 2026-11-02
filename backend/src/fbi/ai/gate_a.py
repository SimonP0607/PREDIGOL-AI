"""Gate A of Plan Maestro IA (section 24): EFFICIENCY AND STABILITY, the end of phase 0.

«Un gate no se aprueba por esta frase»: it passes only on what the ledger shows over SEVEN COMPLETE DAYS of the real system, run in
ONE configuration. Nothing is simulated and nothing is assumed to have happened: with fewer complete days the verdict is
``PENDIENTE POR TIEMPO REAL``; with the manual actions or the LAB evidence missing it is ``PENDIENTE POR ACCIONES MANUALES``; only
a complete case is ``PASA`` or ``NO PASA`` - and only those two are recorded (``ai.feature_gates``, gate ``gate_a``, append-only,
with the evidence's hash so the report can be reproduced from the database).

THE WINDOW. The seven Bogotá days that ended yesterday, all after the ANCHOR: the day after the latest of (a) the first day the
phase-0 code wrote the ledger (a row with a workspace), (b) the last change of an optimisation gate (``batch``, ``native_schema``,
``cache_layout``: a newer row that turns it on or off), (c) a change of configuration DECLARED by whoever deployed it (``changes``: a
deploy that altered what the layer does leaves no row of its own; declaring it can only delay the gate), (d) a change of the owner's
WORDS - a switch, the mode, research v2, a model, an envelope - that the worker recorded (``gates.record_switches``: an environment
variable changed by hand now leaves its trace; the first row is the baseline and is not a change). A day on which the configuration
changed is not part of the measure. A switch turned off by hand before the worker kept that ledger left no trace of its own, so the
days must also SHOW the optimisations in the ledger (the cache check).

THE CHECKS (each with its figures; an unjudgeable one is ``None`` and makes the verdict pending, never a pass):

    plans               every day of the window has its opened plan
    cost_production     monthly projection of production <= 185:  unit cost of the window (US$ per match with a market, the analyst's
                        runs included) x the month's matches with a market - the real ones for the days gone, the calendar's for the
                        days to come (``budget_v3.expected_loads``), weighted as that month is
    cost_joint          that projection + the shadow at 30 % of a normal month (US$ 51, cost model v6) <= 190
    cost_heavy          a heavy month (+25 %): production alone still <= 185; the LAB yields what is over 190 (reported)
    coverage            «los mismos partidos informados y los mismos candidatos revisados», each at most ``COVERAGE_TOLERANCE`` (2
                        points: my engineering reading of «misma») below the baseline's, both computed here with the same definitions
                        (the baseline over its days of ``scripts/ia_baseline.sql``): of the matches with a market in each day's OPENED
                        plan (the late additions of a day do not move it), the share informed (a pass that ended ok or partial with a
                        brief) and the shares with their first / pre / final pass ok; of the candidates (the selections that got a
                        review), the share with a model review
    final_t15           the final verdict before T-15 in >= 99 % of the final passes (the service objective of section 32)
    verdict_equivalence for each optimisation IN FORCE, its evidence on file (the owner's decision A of 27 Oct 2026, ~00:37 UTC): ``batch``
                        has its probe; ``native_schema`` and ``cache_layout`` changed no more verdicts than repeating the same call, over
                        >= 200 stored packets - RECOMPUTED here from the letters stored in the evidence. One in force whose newest evidence
                        says NO PASA, or whose letters do not reproduce its assessment, fails the check (its switch is rolled back, corrected
                        and measured again); one in force without enough evidence leaves it pending. One that is OFF - rejected by its own
                        evidence, never measured, or rolled back - changes nothing the window measures: it is REPORTED (``not_in_force``),
                        never judged, and it is judged the day it is switched on. No threshold moved: only which optimisations are judged.
                        IN FORCE is what the ledger of the owner's words says the worker ran with in the window OR what the evaluating
                        process holds now (review M5): switching an optimisation off in the environment right before the verdict does not
                        take it out of the judgement, and the change itself is a day the configuration changed
    cache_visible       reads of the cache on at least 6 of the 7 days and, in real time, >= 40 % of the cacheable input read (the
                        threshold of the alarm of section 28)
    batch_lost          0 results of a production batch lost (a finished or expired batch with an item neither resolved nor recorded),
                        and <= 1 % of the requests expired; batch ON and not a single request in the window is a failure
    manual_actions      actions 3, 5 and 7, by DATA: the LAB workspace answered with its own key, and the server holds the LAB key and
                        the budgets (185 / 15 / 35). Not done is PENDING (it is the owner's to do), never a failure of the system

Everything here reads: the only thing written is the gate's own row, by ``record``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai import budget_v3, gates, lab
from fbi.ai.calendar import day_start, local_day, month_start
from fbi.ai.config import AiSettings
from fbi.ai.usage import _money

GATE = "gate_a"
PASS, FAIL = "PASA", "NO PASA"
PENDING_TIME, PENDING_ACTIONS = "PENDIENTE POR TIEMPO REAL", "PENDIENTE POR ACCIONES MANUALES"
WINDOW_DAYS = 7
OPTIMISATIONS = ("batch", "native_schema", "cache_layout")

PRODUCTION_CEILING = Decimal(185)
JOINT_CEILING = Decimal(190)
SHADOW_NORMAL_MONTH_USD = Decimal(51)
"""The shadow at 30 % in a normal month, as the cost model v6 prices it (the LAB's envelope in phases 3-8 is 55)."""
HEAVY_MONTH_FACTOR = Decimal("1.25")
COVERAGE_TOLERANCE = Decimal("0.02")
FINAL_BEFORE_T15_MIN = Decimal("0.99")
CACHE_HIT_MIN = Decimal("0.40")
CACHE_DAYS_MIN = 6
BATCH_EXPIRED_MAX = Decimal("0.01")
MIN_EQUIVALENCE_INPUTS = lab.MIN_INPUTS

EXPECTED_ENV: dict[str, Decimal] = {"FBI_AI_MONTHLY_BUDGET_USD": Decimal(185), "FBI_AI_LAB_MONTHLY_BUDGET_USD": Decimal(15),
                                    "FBI_AI_EXA_MONTHLY_BUDGET_USD": Decimal(35)}
"""Action 7 of the owner's list: the budgets of phase 0 (production, LAB, Exa)."""

BASELINE_COVERAGE_DAYS = (date(2026, 10, 9), date(2026, 10, 24))
"""The 16 complete Bogotá days of ``docs/owner/IA_BASELINE_F0.md``: the coverage reference."""
BASELINE_UNIT_DAYS = (date(2026, 10, 18), date(2026, 10, 24))
"""Its last 7 complete days: the cost reference (5.17 USD a day of Claude)."""


def _rate(num: int | Decimal, den: int | Decimal) -> Decimal | None:
    return None if not den else (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"))


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else f"{value * 100:.2f}"


# ── what a check says ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    ok: bool | None
    """True / False; None = it cannot be judged yet (evidence or a manual action is missing): the verdict is then pending."""
    detail: dict[str, Any]
    revert: str | None = None
    """The switch to roll back when this check fails («se revierte el interruptor que falle»), or None when it is not one."""

    @property
    def mark(self) -> str:
        return {True: "SÍ", False: "NO", None: "PENDIENTE"}[self.ok]

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "ok": self.ok, "detail": self.detail, "revert": self.revert}


@dataclass(frozen=True)
class Window:
    first: date
    last: date
    anchor: date | None
    anchored_by: str | None
    stable_days: int
    eligible_on: date | None

    @property
    def complete(self) -> bool:
        return self.anchor is not None and self.first >= self.anchor

    def as_json(self) -> dict[str, Any]:
        return {"first": self.first.isoformat(), "last": self.last.isoformat(), "days": WINDOW_DAYS,
                "anchor": None if self.anchor is None else self.anchor.isoformat(), "anchored_by": self.anchored_by,
                "stable_complete_days": self.stable_days,
                "eligible_on": None if self.eligible_on is None else self.eligible_on.isoformat(), "complete": self.complete}


@dataclass(frozen=True)
class GateReport:
    verdict: str
    at: datetime
    window: Window
    checks: tuple[Check, ...] = ()
    pending: tuple[str, ...] = ()
    consequence: str | None = None
    preview: dict[str, Any] = field(default_factory=dict)

    @property
    def recordable(self) -> bool:
        return self.verdict in (PASS, FAIL)

    def as_json(self) -> dict[str, Any]:
        return {"gate": GATE, "verdict": self.verdict, "at": self.at.isoformat(), "window": self.window.as_json(),
                "checks": [c.as_json() for c in self.checks], "pending": list(self.pending), "consequence": self.consequence,
                "preview": self.preview, "recorded_only_if": "PASA or NO PASA"}

    def lines(self) -> list[str]:
        out = [f"GATE A · {self.verdict}", f"Ventana: {self.window.first} a {self.window.last} (7 días completos, hora de Bogotá)"]
        if self.window.anchor is not None:
            out.append(f"Configuración estable desde {self.window.anchor} ({self.window.anchored_by}); "
                       f"{self.window.stable_days} día(s) completo(s) de 7")
        out += [f"  [{c.mark}] {c.title}" for c in self.checks]
        out += [f"  Falta: {p}" for p in self.pending]
        if self.consequence:
            out.append(f"Consecuencia: {self.consequence}")
        return out


# ── the window ──────────────────────────────────────────────────────────────────────────────────────────────────

DEPLOY_SQL = "SELECT min((at AT TIME ZONE 'America/Bogota')::date) FROM ai.usage WHERE workspace IS NOT NULL"
FLIPS_SQL = ("SELECT gate, at, passed FROM ai.feature_gates WHERE gate = ANY(%(gates)s) ORDER BY gate, at, id")


def flips(conn: psycopg.Connection[Any]) -> list[tuple[date, str]]:
    """The days an optimisation was turned on or off by its gate: the first row that passes (off -> on) and every later row that
    changes the answer. A row that repeats the answer changes nothing."""
    out: list[tuple[date, str]] = []
    state: dict[str, bool] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(FLIPS_SQL, {"gates": list(OPTIMISATIONS)})
        for gate, at, passed in cur.fetchall():
            if bool(passed) != state.get(gate, False):
                out.append((local_day(at), f"{gate} {'on' if passed else 'off'}"))
            state[gate] = bool(passed)
    return out


def switch_changes(conn: psycopg.Connection[Any]) -> list[tuple[date, str]]:
    """The days the owner's words changed, from the ledger the worker keeps (``gates.record_switches``): every row after the first whose
    words differ from the row before. The first row is the baseline - the words the worker held when it began to keep the ledger - and is
    not a change."""
    out: list[tuple[date, str]] = []
    previous: dict[str, Any] | None = None
    for _row, at, words in gates.switch_ledger(conn):
        if previous is not None and words != previous:
            out.append((local_day(at), f"the owner's words changed ({'; '.join(gates.words_diff(previous, words))[:160]})"))
        previous = words
    return out


def window_of(conn: psycopg.Connection[Any], *, at: datetime, through: date | None = None,
              changes: Sequence[date] = ()) -> Window:
    today = local_day(at)
    last = through or today - timedelta(days=1)
    if last >= today:
        raise ValueError(f"{last} is not a complete day yet (today is {today}): the gate measures complete days only")
    first = last - timedelta(days=WINDOW_DAYS - 1)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(DEPLOY_SQL)
        row = cur.fetchone()
    deploy = None if row is None else row[0]
    events = [(deploy, "the phase-0 code's first ledger row")] if deploy is not None else []
    events += flips(conn)
    events += switch_changes(conn)
    events += [(d, "a change of configuration declared by whoever deployed it") for d in changes]
    if deploy is None:
        return Window(first, last, None, None, 0, None)
    day, why = max(events, key=lambda e: e[0])
    anchor = day + timedelta(days=1)
    return Window(first, last, anchor, f"{why}, {day}", max(0, (last - anchor).days + 1), anchor + timedelta(days=WINDOW_DAYS))


# ── the figures ─────────────────────────────────────────────────────────────────────────────────────────────────

COVERAGE_SQL = """
WITH opened AS (
  SELECT d.day, (u ->> 'fixture_id')::bigint AS fixture_id
    FROM ai.day_plans d CROSS JOIN LATERAL jsonb_array_elements(d.universe) u
   WHERE d.stage = 'opened' AND d.day BETWEEN %(first)s AND %(last)s AND COALESCE((u ->> 'has_market')::boolean, false)
), per AS (
  SELECT o.day, o.fixture_id,
         COALESCE(bool_or(p.status IN ('ok', 'partial') AND p.brief_id IS NOT NULL), false) AS informed,
         COALESCE(bool_or(p.pass = 'first' AND p.status = 'ok'), false) AS first_ok,
         COALESCE(bool_or(p.pass = 'pre' AND p.status = 'ok'), false) AS pre_ok,
         COALESCE(bool_or(p.pass = 'final' AND p.status = 'ok'), false) AS final_ok
    FROM opened o LEFT JOIN ai.fixture_passes p ON p.fixture_id = o.fixture_id AND p.day = o.day
   GROUP BY o.day, o.fixture_id
)
SELECT count(*) AS opened, count(*) FILTER (WHERE informed) AS informed, count(*) FILTER (WHERE first_ok) AS first_ok,
       count(*) FILTER (WHERE pre_ok) AS pre_ok, count(*) FILTER (WHERE final_ok) AS final_ok
  FROM per
"""
FINAL_SQL = """
SELECT count(*) AS final_done, count(*) FILTER (WHERE kickoff_at - finished_at >= interval '15 minutes') AS final_before_t15
  FROM ai.fixture_passes WHERE pass = 'final' AND status IN ('ok', 'partial') AND day BETWEEN %(first)s AND %(last)s
"""
CANDIDATES_SQL = """
WITH per AS (
  SELECT fixture_id, market_key, selection, line, bool_or(engine = 'llm') AS llm
    FROM ai.pick_reviews WHERE reviewed_at >= %(since)s AND reviewed_at < %(until)s GROUP BY 1, 2, 3, 4)
SELECT count(*) AS selections, count(*) FILTER (WHERE llm) AS selections_llm FROM per
"""
PLAN_DAYS_SQL = ("SELECT count(DISTINCT day) FROM ai.day_plans WHERE stage = 'opened' AND day BETWEEN %(first)s AND %(last)s")
TRACKED_SQL = """
SELECT (f.kickoff_at AT TIME ZONE 'America/Bogota')::date AS day, count(*) AS n
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s GROUP BY 1
"""
CACHE_SQL = """
SELECT (at AT TIME ZONE 'America/Bogota')::date AS day, COALESCE(sum(cached_tokens), 0) AS reads,
       COALESCE(sum(cache_write_tokens), 0) AS writes, COALESCE(sum(input_tokens), 0) AS input
  FROM ai.usage_scoped
 WHERE scope = 'production' AND provider = 'anthropic' AND batch_id IS NULL AND status = 'ok'
   AND at >= %(since)s AND at < %(until)s
 GROUP BY 1
"""
BATCH_SQL = """
SELECT i.status AS item, b.status AS batch, (b.processed_at IS NOT NULL) AS processed,
       (b.expires_at IS NOT NULL AND b.expires_at < %(at)s) AS past_expiry, (i.usage_id IS NOT NULL) AS has_usage, count(*) AS n
  FROM ai.batch_items i JOIN ai.batches b ON b.id = i.batch_id
 WHERE b.kind = 'production' AND i.created_at >= %(since)s AND i.created_at < %(until)s
 GROUP BY 1, 2, 3, 4, 5
"""
LAB_CALL_SQL = ("SELECT count(*), min(at) FROM ai.usage WHERE workspace = %(workspace)s AND key_label = %(key)s AND status = 'ok' "
                "AND provider = 'anthropic'")
GATE_ROW_SQL = ("SELECT id, at, passed, evidence, evidence_hash FROM ai.feature_gates WHERE gate = %s ORDER BY at DESC, id DESC LIMIT 1")


@dataclass(frozen=True)
class Coverage:
    first: date
    last: date
    opened: int
    informed: int
    first_ok: int
    pre_ok: int
    final_ok: int
    final_done: int
    final_before_t15: int
    selections: int
    selections_llm: int

    @property
    def rates(self) -> dict[str, Decimal | None]:
        return {"informed": _rate(self.informed, self.opened), "first_ok": _rate(self.first_ok, self.opened),
                "pre_ok": _rate(self.pre_ok, self.opened), "final_ok": _rate(self.final_ok, self.opened),
                "candidates_reviewed": _rate(self.selections_llm, self.selections)}

    def as_json(self) -> dict[str, Any]:
        return {"days": [self.first.isoformat(), self.last.isoformat()], "matches_with_market": self.opened,
                "matches_informed": self.informed, "first_ok": self.first_ok, "pre_ok": self.pre_ok, "final_ok": self.final_ok,
                "final_done": self.final_done, "final_before_t15": self.final_before_t15,
                "candidates": self.selections, "candidates_with_model_review": self.selections_llm,
                "rates_pct": {k: _pct(v) for k, v in self.rates.items()}}


def coverage(conn: psycopg.Connection[Any], first: date, last: date) -> Coverage:
    """The coverage figures of a run of Bogotá days - the SAME definitions for the baseline and for the window."""
    since, until = day_start(first), day_start(last + timedelta(days=1))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COVERAGE_SQL, {"first": first, "last": last})
        row = cur.fetchone()
        cur.execute(FINAL_SQL, {"first": first, "last": last})
        fin = cur.fetchone()
        cur.execute(CANDIDATES_SQL, {"since": since, "until": until})
        cand = cur.fetchone()
    assert row is not None and fin is not None and cand is not None
    return Coverage(first, last, int(row["opened"]), int(row["informed"]), int(row["first_ok"]), int(row["pre_ok"]),
                    int(row["final_ok"]), int(fin["final_done"]), int(fin["final_before_t15"]), int(cand["selections"]),
                    int(cand["selections_llm"]))


def unit_cost(conn: psycopg.Connection[Any], first: date, last: date) -> tuple[Decimal | None, Decimal, int]:
    """US$ of production per match with a market over the days (the days with matches), its total, and the matches."""
    costs = budget_v3.costs_by_day(conn, "production", day_start(first), day_start(last + timedelta(days=1)))
    opened = budget_v3.plans(conn, first, last).opened
    days = [d for d, n in opened.items() if first <= d <= last and n > 0]
    matches = sum(opened[d] for d in days)
    total = sum((costs.get(d, Decimal(0)) for d in days), Decimal(0))
    return (None if matches == 0 else total / matches), total, matches


def month_matches(conn: psycopg.Connection[Any], today: date) -> tuple[float, dict[str, Any]]:
    """The matches with a market of the month of ``today``: the days gone as the opened plans counted them (the tracked fixtures
    times the share that ends up with a market where a day has no plan), the days to come from the calendar and the weekdays
    (``budget_v3.expected_loads``) - the month weighted by its own calendar."""
    first = month_start(today)
    p = budget_v3.plans(conn, min(first, today - timedelta(days=7 * budget_v3.WEEKDAY_WEEKS)), today + timedelta(days=budget_v3.CALENDAR_DAYS))
    share = budget_v3.market_share(p, today)
    start, end = day_start(first), day_start(today)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(TRACKED_SQL, {"start": start, "end": end})
        tracked = {r[0]: int(r[1]) for r in cur.fetchall()}
    gone = 0.0
    without_plan = 0
    for k in range((today - first).days):
        d = first + timedelta(days=k)
        if d in p.opened:
            gone += p.opened[d]
        else:
            gone += tracked.get(d, 0) * share
            without_plan += 1
    to_come = sum(budget_v3.expected_loads(conn, today, p).values())
    return gone + to_come, {"days_gone": (today - first).days, "matches_gone": round(gone, 1), "days_gone_without_plan": without_plan,
                            "matches_to_come": round(to_come, 1), "market_share": round(share, 4)}


# ── the checks ──────────────────────────────────────────────────────────────────────────────────────────────────


def check_plans(conn: psycopg.Connection[Any], w: Window) -> Check:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PLAN_DAYS_SQL, {"first": w.first, "last": w.last})
        row = cur.fetchone()
    have = 0 if row is None else int(row[0])
    return Check("plans", "Cada día de la ventana tiene su plan abierto", have == WINDOW_DAYS, {"days_with_plan": have, "of": WINDOW_DAYS})


def check_costs(conn: psycopg.Connection[Any], w: Window, *, at: datetime, baseline_unit: tuple[date, date]) -> list[Check]:
    unit, spent, matches = unit_cost(conn, w.first, w.last)
    base_unit, base_spent, base_matches = unit_cost(conn, *baseline_unit)
    today = local_day(at)
    if unit is None:
        why = {"matches_with_market": 0, "note": "no match with a market in the window: no unit cost can be measured"}
        return [Check(i, t, None, why) for i, t in (("cost_production", "Proyección mensual de producción ≤ 185 USD"),
                                                    ("cost_joint", "Con la sombra al 30 %, ≤ 190 USD"),
                                                    ("cost_heavy", "Mes pesado: producción sola ≤ 185 USD"))]
    month, how = month_matches(conn, today)
    projection = _money(unit * Decimal(str(round(month, 4))))
    heavy = _money(projection * HEAVY_MONTH_FACTOR)
    joint = projection + SHADOW_NORMAL_MONTH_USD
    base = {"window_usd": str(_money(spent)), "window_matches": matches, "unit_usd_per_match": str(unit.quantize(Decimal("0.0001"))),
            "month_matches": round(month, 1), **how, "baseline_unit_usd_per_match":
            None if base_unit is None else str(base_unit.quantize(Decimal("0.0001"))), "baseline_window_usd": str(_money(base_spent)),
            "baseline_matches": base_matches,
            "saving_vs_baseline_pct": None if base_unit in (None, 0) else _pct(Decimal(1) - unit / base_unit)}
    window_days = Decimal(WINDOW_DAYS)
    base["claude_usd_per_day"] = str(_money(spent / window_days))
    prod = Check("cost_production", "Proyección mensual de producción ≤ 185 USD", projection <= PRODUCTION_CEILING,
                 base | {"projection_usd": str(projection), "ceiling_usd": str(PRODUCTION_CEILING)})
    shadow_fit = max(Decimal(0), (JOINT_CEILING - projection) / SHADOW_NORMAL_MONTH_USD * Decimal("0.30"))
    jointc = Check("cost_joint", "Con la sombra al 30 %, ≤ 190 USD", joint <= JOINT_CEILING,
                   {"production_usd": str(projection), "shadow_normal_month_usd": str(SHADOW_NORMAL_MONTH_USD),
                    "total_usd": str(joint), "ceiling_usd": str(JOINT_CEILING),
                    "shadow_share_that_fits_pct": _pct(min(shadow_fit, Decimal("0.30"))),
                    "if_it_fails": "the shadow is planned with a smaller sample, never below the one that gives 300 selections in "
                                   "30 days"})
    heavyc = Check("cost_heavy", "Mes pesado: producción sola ≤ 185 USD (el LAB cede lo que pase de 190)", heavy <= PRODUCTION_CEILING,
                   {"production_heavy_usd": str(heavy), "factor": str(HEAVY_MONTH_FACTOR),
                    "lab_yields_usd": str(max(Decimal(0), heavy + SHADOW_NORMAL_MONTH_USD - JOINT_CEILING))})
    return [prod, jointc, heavyc]


def check_coverage(conn: psycopg.Connection[Any], w: Window, baseline_days: tuple[date, date]) -> tuple[Check, Check]:
    mine = coverage(conn, w.first, w.last)
    base = coverage(conn, *baseline_days)
    titles = {"informed": "partidos informados", "first_ok": "pasadas first hechas", "pre_ok": "pasadas pre hechas",
              "final_ok": "pasadas final hechas", "candidates_reviewed": "candidatos con revisión de modelo"}
    rows: dict[str, Any] = {}
    verdicts: list[bool | None] = []
    for key, label in titles.items():
        a, b = mine.rates[key], base.rates[key]
        if a is None or b is None:
            rows[key] = {"label": label, "window_pct": _pct(a), "baseline_pct": _pct(b), "ok": None}
            verdicts.append(None)
            continue
        ok = a >= b - COVERAGE_TOLERANCE
        rows[key] = {"label": label, "window_pct": _pct(a), "baseline_pct": _pct(b), "ok": ok}
        verdicts.append(ok)
    ok_all: bool | None = None if None in verdicts else all(verdicts)
    if False in verdicts:
        ok_all = False
    cov = Check("coverage", "Misma cobertura que la línea base (partidos informados, pasadas, candidatos revisados)", ok_all,
                {"tolerance_points": str(COVERAGE_TOLERANCE * 100), "metrics": rows, "window": mine.as_json(),
                 "baseline": base.as_json()}, revert="FBI_AI_BRIEF_MATERIAL / FBI_AI_BATCH")
    t15 = _rate(mine.final_before_t15, mine.final_done)
    final = Check("final_t15", "Veredicto final antes de T-15 en ≥ 99 % de las pasadas final",
                  None if t15 is None else t15 >= FINAL_BEFORE_T15_MIN,
                  {"final_passes": mine.final_done, "before_t15": mine.final_before_t15, "rate_pct": _pct(t15),
                   "minimum_pct": _pct(FINAL_BEFORE_T15_MIN)}, revert="FBI_AI_BATCH")
    return cov, final


def stored_rows(evidence: Mapping[str, Any], variant: str) -> dict[str, dict[str, str | None]]:
    """The verdicts of every input as the evidence stores them (a letter per ask, ``-`` = invalid): what ``lab.assess`` reads."""
    key = lab.VARIANT_KEY[variant]
    rows: dict[str, dict[str, str | None]] = {}
    for ref, letters in dict(evidence.get("inputs") or {}).items():
        cells = [None if c == "-" else c for c in str(letters)]
        if len(cells) == len((*lab.BASELINES, key)):
            rows[str(ref)] = dict(zip((*lab.BASELINES, key), cells, strict=True))
    return rows


def equivalence_of(conn: psycopg.Connection[Any], gate: str) -> dict[str, Any]:
    """What the newest evidence of an optimisation's gate says, and whether it holds when recomputed from the stored letters."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(GATE_ROW_SQL, (gate,))
        row = cur.fetchone()
    if row is None:
        return {"gate": gate, "state": "missing"}
    base: dict[str, Any] = {"gate": gate, "state": "failed" if not row["passed"] else "passed", "at": row["at"].isoformat(),
                            "evidence_hash": row["evidence_hash"]}
    evidence = row["evidence"] if isinstance(row["evidence"], dict) else {}
    if gate == "batch":
        return base | {"probe_passed": bool(row["passed"])}
    variant = next(v for v, g in lab.GATE_OF_VARIANT.items() if g == gate)
    stored = dict(evidence.get("assessment") or {})
    again = lab.assess(stored_rows(evidence, variant), variant, min_inputs=int(evidence.get("min_inputs") or MIN_EQUIVALENCE_INPUTS))
    n = int(again["complete_inputs"])
    base |= {"complete_inputs": n, "changed_repeat": again["changed_repeat"], "changed_variant": again["changed_variant"],
             "stored_complete_inputs": stored.get("complete_inputs"), "models": evidence.get("models")}
    if n < MIN_EQUIVALENCE_INPUTS:
        return base | {"state": "insufficient", "needed": MIN_EQUIVALENCE_INPUTS}
    if stored.get("complete_inputs") != n or stored.get("changed_repeat") != again["changed_repeat"] \
            or stored.get("changed_variant") != again["changed_variant"]:
        return base | {"state": "not_reproducible"}
    if bool(again["passed"]) is False and bool(row["passed"]) is True:
        return base | {"state": "not_reproducible"}
    return base


SWITCH_OF: dict[str, str] = {"batch": "FBI_AI_BATCH", "native_schema": "FBI_AI_NATIVE_SCHEMA",
                             "cache_layout": "the shared layout (ia_gate revert cache_layout)"}
"""What to roll back when the optimisation in force is the one that fails."""


def in_force_by_ledger(conn: psycopg.Connection[Any]) -> tuple[dict[str, bool] | None, dict[str, Any]]:
    """Which optimisations the worker ran with, read from the newest row of the ledger of the owner's words and the newest evidence of each
    gate - the same rule as ``gates.describe``, applied to the words the worker held and not to the ones of whoever evaluates. In a COMPLETE
    window nothing changed inside it (a change of the words, of a gate or a declared one is a day the configuration changed, and the window
    starts after the latest), so the newest row says what the whole window ran with. None when the worker has not written the ledger yet."""
    rows = gates.switch_ledger(conn)
    if not rows:
        return None, {"rows": 0, "note": "the worker has not written the ledger of the owner's words yet: only this process's words are read"}
    row, at, words = rows[-1]
    mode = dict(words.get("switches") or {})
    passed = {g: gates.gate_state(conn, g).passed for g in OPTIMISATIONS}

    def running(switch: str, gate: str) -> bool:
        return mode.get(switch) == "on" or (mode.get(switch, "auto") == "auto" and passed[gate])

    on = {"batch": running("batch", "batch"), "native_schema": running("native_schema", "native_schema"),
          "cache_layout": mode.get("cache", "auto") != "off" and passed["cache_layout"]}
    return on, {"rows": len(rows), "first_at": rows[0][1].isoformat(), "newest_row": row, "newest_at": at.isoformat(), "words": words}


def optimisations_in_force(conn: psycopg.Connection[Any], settings: AiSettings) -> dict[str, Any]:
    """The optimisations to JUDGE: what the worker ran with according to its ledger, or what this process holds now (review M5). Taking only the
    process that evaluates let a switch forced on during the window - against its own failing evidence - be put back to ``auto`` in the
    environment right before ``--record`` and leave the judgement without it; the union takes nobody's word for the days that went."""
    described = gates.describe(conn, settings)
    now = {g: bool(described.get(g, {}).get("on")) for g in OPTIMISATIONS}
    ledger, meta = in_force_by_ledger(conn)
    on = {g: now[g] or bool(ledger and ledger[g]) for g in OPTIMISATIONS}
    return {"on": on, "now": now, "ledger": ledger, "switch_ledger": meta,
            "disagree": [g for g in OPTIMISATIONS if ledger is not None and ledger[g] != now[g]]}


def check_equivalence(conn: psycopg.Connection[Any], settings: AiSettings) -> Check:
    """The evidence of the optimisations that are IN FORCE (``optimisations_in_force``: the switch on, or ``auto`` with its gate passing, in
    the words the worker ran with in the window or in the ones of this process).

    The owner's decision A (27 Oct 2026, ~00:37 UTC), taken when the first experiment left ``native_schema`` INSUFICIENTE and ``cache_layout``
    NO PASA and both switches off: requiring favourable evidence of an optimisation that is not running could only be met by switching it on, and
    one that is off changes no verdict the window measures. So only what is in force is judged - it needs its probe (``batch``) or no more
    verdicts changed than repeating the call, over >= 200 packets, RECOMPUTED from the letters (the others); an optimisation that is off is
    listed in ``not_in_force`` with the state of its evidence and never blocks. Thresholds, the 200 packets and the recomputation are as they were."""
    states = {g: equivalence_of(conn, g) for g in OPTIMISATIONS}
    force = optimisations_in_force(conn, settings)
    on: dict[str, bool] = force["on"]
    judged = [g for g in OPTIMISATIONS if on[g]]
    off = [g for g in OPTIMISATIONS if not on[g]]
    missing = [g for g in judged if states[g]["state"] in ("missing", "insufficient")]
    not_reproducible = [g for g in judged if states[g]["state"] == "not_reproducible"]
    failed = [g for g in judged if states[g]["state"] == "failed"]  # in force although its newest evidence says NO PASA (forced on by hand)
    ok: bool | None
    if not_reproducible or failed:
        ok = False
    elif missing:
        ok = None
    else:
        ok = True
    model = None if (tm := settings.tier("analysis")) is None else tm.model
    covered = {g: (None if model is None or s["state"] == "missing" else model in (s.get("models") or [model]))
               for g, s in states.items()}
    note = ("no optimisation is in force: there is nothing to compare" if not judged
            else f"judged: {', '.join(judged)}" + (f"; reported, not judged (off): {', '.join(off)}" if off else ""))
    if force["disagree"]:
        note += f"; the ledger of the worker's words and this process disagree on: {', '.join(force['disagree'])} (both are judged)"
    return Check("verdict_equivalence", "Cambio de veredicto con las optimizaciones en vigor ≤ el de repetir la misma llamada (≥ 200 paquetes)",
                 ok, {"optimisations": states, "in_force": on, "in_force_now": force["now"], "in_force_by_ledger": force["ledger"],
                      "switch_ledger": force["switch_ledger"], "ledger_and_process_disagree": force["disagree"], "judged": judged,
                      "not_in_force": {g: states[g]["state"] for g in off},
                      "rolled_back": [g for g in off if states[g]["state"] == "failed"],
                      "unmeasured": [g for g in off if states[g]["state"] in ("missing", "insufficient")],
                      "missing": missing, "failed": failed, "not_reproducible": not_reproducible,
                      "minimum_inputs": MIN_EQUIVALENCE_INPUTS, "analysis_model": model, "analysis_model_covered": covered,
                      "note": note},
                 revert=" / ".join(SWITCH_OF[g] for g in (*failed, *not_reproducible)) or "FBI_AI_NATIVE_SCHEMA / the shared layout")


def check_cache(conn: psycopg.Connection[Any], w: Window) -> Check:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CACHE_SQL, {"since": day_start(w.first), "until": day_start(w.last + timedelta(days=1))})
        per_day = {r[0]: (int(r[1]), int(r[2]), int(r[3])) for r in cur.fetchall()}
    reads = sum(r for r, _, _ in per_day.values())
    writes = sum(x for _, x, _ in per_day.values())
    total_input = sum(i for _, _, i in per_day.values())
    days_reading = sum(1 for r, _, _ in per_day.values() if r > 0)
    hit = _rate(reads, reads + writes)
    ok = hit is not None and hit >= CACHE_HIT_MIN and days_reading >= CACHE_DAYS_MIN
    return Check("cache_visible", "Caché visible: lecturas casi cada día y ≥ 40 % de la entrada cacheable leída", bool(ok),
                 {"read_tokens": reads, "written_tokens": writes, "input_tokens": total_input, "hit_rate_pct": _pct(hit),
                  "read_share_of_input_pct": _pct(_rate(reads, total_input)), "days_reading": days_reading,
                  "days_needed": CACHE_DAYS_MIN, "minimum_hit_rate_pct": _pct(CACHE_HIT_MIN),
                  "per_day": {d.isoformat(): {"read": r, "written": x} for d, (r, x, _) in sorted(per_day.items())}},
                 revert="FBI_AI_CACHE")


def check_batch(conn: psycopg.Connection[Any], settings: AiSettings, w: Window, *, at: datetime) -> Check:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(BATCH_SQL, {"at": at, "since": day_start(w.first), "until": day_start(w.last + timedelta(days=1))})
        rows = cur.fetchall()
    total = sum(int(r["n"]) for r in rows)
    by_item: dict[str, int] = {}
    lost = 0
    for r in rows:
        n = int(r["n"])
        by_item[r["item"]] = by_item.get(r["item"], 0) + n
        stuck = r["item"] in ("submitting", "submitted") and (r["processed"] or r["past_expiry"] or r["batch"] in ("failed", "abandoned"))
        unrecorded = r["item"] not in ("submitting", "submitted", "abandoned") and not r["has_usage"]
        if stuck or unrecorded:
            lost += n
    expired = by_item.get("expired", 0)
    on = bool(optimisations_in_force(conn, settings)["on"]["batch"])
    share = _rate(expired, total)
    detail: dict[str, Any] = {"batch_on": on, "requests": total, "by_status": dict(sorted(by_item.items())), "lost": lost,
                              "expired": expired, "expired_pct": _pct(share), "maximum_expired_pct": _pct(BATCH_EXPIRED_MAX)}
    if total == 0:
        ok = not on
        detail["note"] = "Batch is off and nothing went through it" if ok else "Batch is ON and not one request went through it"
    else:
        ok = lost == 0 and (share is None or share <= BATCH_EXPIRED_MAX)
    return Check("batch_lost", "0 resultados de lote perdidos (y ≤ 1 % de peticiones caducadas)", ok, detail, revert="FBI_AI_BATCH")


def check_actions(conn: psycopg.Connection[Any], settings: AiSettings) -> Check:
    """Owner actions 3, 5 and 7 by DATA - names and numbers, never a key."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LAB_CALL_SQL, {"workspace": settings.workspace_lab, "key": settings.key_label_lab})
        row = cur.fetchone()
    calls = 0 if row is None else int(row[0])
    lab_key = "anthropic" in settings.lab_keys
    differs = lab_key and settings.lab_keys.get("anthropic") != settings.keys.get("anthropic")
    figures = {"FBI_AI_MONTHLY_BUDGET_USD": settings.monthly_budget, "FBI_AI_LAB_MONTHLY_BUDGET_USD": settings.lab_monthly_budget,
               "FBI_AI_EXA_MONTHLY_BUDGET_USD": settings.exa_monthly_budget}
    wrong = {name: {"is": str(figures[name]), "should_be": str(want)} for name, want in EXPECTED_ENV.items()
             if figures[name] != want}
    a35 = calls > 0 and differs
    a7 = lab_key and bool(differs) and not wrong
    detail: dict[str, Any] = {
        "action_3_and_5": {"done": a35, "evidence": f"{calls} successful call(s) of the LAB workspace {settings.workspace_lab!r} with "
                           f"its own key {settings.key_label_lab!r} in the ledger", "lab_key_differs_from_production": differs},
        "action_7": {"done": a7, "FBI_AI_KEY_ANTHROPIC_LAB_present": lab_key, "budgets_wrong": wrong}}
    done = a35 and a7
    return Check("manual_actions", "Acciones manuales 3, 5 y 7 hechas (comprobadas con datos)", True if done else None, detail)


# ── the gate ────────────────────────────────────────────────────────────────────────────────────────────────────


def evaluate(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, through: date | None = None,
             changes: Sequence[date] = (), baseline_coverage: tuple[date, date] = BASELINE_COVERAGE_DAYS,
             baseline_unit: tuple[date, date] = BASELINE_UNIT_DAYS) -> GateReport:
    w = window_of(conn, at=at, through=through, changes=changes)
    if not w.complete:
        if w.anchor is None:
            need = "the phase-0 code has not written the ledger yet: nothing to measure"
        else:
            need = (f"{w.stable_days} de {WINDOW_DAYS} días completos con la configuración estable desde {w.anchor}; "
                    f"el primer día evaluable es {w.eligible_on}")
        return GateReport(PENDING_TIME, at, w, pending=(need,), preview={
            "note": "NOT evidence of the gate: only what the days gone show",
            "stable_complete_days": w.stable_days})
    checks: list[Check] = [Check("window", "7 días completos con la configuración estable", True, w.as_json()),
                           check_plans(conn, w)]
    checks += check_costs(conn, w, at=at, baseline_unit=baseline_unit)
    cov, final = check_coverage(conn, w, baseline_coverage)
    checks += [cov, final, check_equivalence(conn, settings), check_cache(conn, w), check_batch(conn, settings, w, at=at),
               check_actions(conn, settings)]
    pending = tuple(f"{c.title}: {_waiting_for(c)}" for c in checks if c.ok is None)
    if pending:
        return GateReport(PENDING_ACTIONS, at, w, tuple(checks), pending, preview={
            "failing_now": [c.id for c in checks if c.ok is False],
            "note": "NOT a verdict: the evidence it needs is missing, and a failure seen now may change with it"})
    failed = [c for c in checks if c.ok is False]
    if not failed:
        return GateReport(PASS, at, w, tuple(checks))
    return GateReport(FAIL, at, w, tuple(checks), consequence=consequence(failed))


def _waiting_for(c: Check) -> str:
    if c.id == "manual_actions":
        return "acciones 3, 5 y 7 del propietario (docs/owner/IA_ACCIONES_MANUALES.md)"
    if c.id == "verdict_equivalence":
        missing = ", ".join(c.detail.get("missing") or [])
        return (f"pruebas del LAB de lo que está en vigor{f' ({missing})' if missing else ''}: python -m scripts.ia_probe y "
                "python -m scripts.ia_equivalence (necesitan las acciones 3, 5 y 7)")
    return "no hay datos para juzgarlo"


def consequence(failed: list[Check]) -> str:
    """What the plan says to do (section 24, "Si no pasa"): roll back the switch that fails; if only the cost fails, plan the shadow
    with a smaller sample - never below the one that gives 300 selections in 30 days."""
    ids = {c.id for c in failed}
    if ids <= {"cost_joint"}:
        return ("solo falla el coste con la sombra: la sombra se planifica con menos muestra, nunca por debajo de la que da 300 "
                "selecciones en 30 días")
    reverts = sorted({c.revert for c in failed if c.revert})
    base = "se revierte el interruptor que falle: " + (", ".join(reverts) if reverts else "ninguno aplica") + "; se corrige y se repite la medición"
    return base


def record(conn: psycopg.Connection[Any], report: GateReport, *, code_version: str | None = None) -> int | None:
    """Append the gate's row - ``PASA`` or ``NO PASA`` only; a pending report is not evidence and writes nothing. The caller commits.
    Returns the row's id, None when nothing was written."""
    if not report.recordable:
        return None
    return gates.record_gate(conn, gate=GATE, passed=report.verdict == PASS, evidence=report.as_json(), at=report.at,
                             decided_by="script", code_version=code_version)


def revert(conn: psycopg.Connection[Any], gate: str, *, reason: str, at: datetime, code_version: str | None = None) -> int:
    """Switch an ``auto`` optimisation off the way the plan says («se revierte el interruptor que falle»): a newer row of its gate
    that does not pass. The earlier evidence stays; a later passing run turns it on again. The caller commits."""
    if gate not in OPTIMISATIONS:
        raise ValueError(f"only {', '.join(OPTIMISATIONS)} can be reverted this way, not {gate!r}")
    evidence = {"reverted_by": "scripts.ia_gate", "reason": reason[:300], "previous": gates.gate_state(conn, gate).as_json()}
    return gates.record_gate(conn, gate=gate, passed=False, evidence=evidence, at=at, decided_by="script", code_version=code_version)
