"""Gate B of the Plan Maestro IA (section 24): FUNCTIONAL SHADOW, the end of phases 3-5, after 14 days - ``gate-b-v1``.

«Un gate no se aprueba por esta frase»: it passes only on what the database shows over FOURTEEN COMPLETE Bogotá days of the real shadow, run in
ONE configuration. Nothing is simulated and nothing is assumed to have happened: with fewer complete days, or with a figure that has no sample
yet, the verdict is ``PENDIENTE POR TIEMPO REAL``; with evidence that someone has to produce or a figure that is stored nowhere, it is
``PENDIENTE POR ACCIONES MANUALES``; only a complete case is ``PASA`` or ``NO PASA``. The verdict of the report is the worst of its checks, in
this order: NO PASA > PENDIENTE POR ACCIONES MANUALES > PENDIENTE POR TIEMPO REAL > PASA. A pending check is never read as a pass.

NOT RECORDED. ``ai.feature_gates.gate`` is held by a CHECK (``feature_gates_gate_check``, last widened by migration 0116: ``batch``,
``native_schema``, ``cache_layout``, ``gate_a``, ``battery``, ``research_v2``, ``switches``) that does not know ``gate_b``, and phase P0 ships with
no migration. So this module only READS: there is no ``record``, and writing the verdict of Gate B needs a migration that widens that CHECK in a
later PR. Nothing here writes, switches, publishes or changes what production decides.

THE WINDOW. The fourteen Bogotá days that ended yesterday (or ``through``), all after the ANCHOR: the day after the latest of (a) the first day
the Orchestrator wrote a run of the shadow (``ai.agent_runs``, ``run_kind = 'shadow'``), (b) a change of an optimisation gate
(``gate_a.flips``: the Batch calendar of the shadow rides on ``batch``), (c) a change of the owner's words recorded by the worker
(``gate_a.switch_changes``: the engines, the sample, the agents, the envelopes), (d) the first day a NEW version of an agent - its
``agent_version``, ``prompt_version`` or ``schema_version`` - ran in the shadow (a deploy of a new prompt leaves no row of its own, but its runs
say so; the plan: «una versión que cambia es otro agente»), (e) a change DECLARED by whoever deployed it (``changes``). Each can only delay the
gate. While the window is not complete the verdict is ``PENDIENTE POR TIEMPO REAL`` and the checks are shown as a preview over the would-be
window - not evidence, but a failure seen early is a failure to correct early («la sombra sigue y se corrige»).

THE CHECKS (each with its figures, its threshold and its own verdict):

    final_deadline      0 ``final`` passes of the shadow ended out of time: the shadow row of the pass (``ai.match_runs``, ``final``) is
                        written strictly before kick-off minus 15 minutes (``runtime.FINAL_MARGIN``), and every call of a ``final`` pass
                        that reached the model (``ok``, ``invalid``, ``abstain``, ``timeout``) finished strictly before its deadline - the
                        task's ``deadline_at`` (which ``orchestrator_store.write_task`` raises to the start of a task started late, so a
                        late start is late), or kick-off minus 15 minutes for a run with no task. The passes the guard did NOT start
                        (``too_late`` of the cycles' reports) are reported: they are the guard working, not a pass out of time. A run
                        whose deadline cannot be read at all is PENDIENTE POR ACCIONES MANUALES (someone has to look at it); no final
                        pass in the window is PENDIENTE POR TIEMPO REAL
    invalid_outputs     <= 3 % invalid outputs per agent AND agent version (``ai.agent_runs`` of the shadow, ``invalid`` over the runs
                        that got an answer: ``ok`` + ``invalid`` + ``abstain``), with the invalid ones by error code. Over 3 % fails
                        whatever the sample; a version with fewer than ``MIN_RUNS_PER_AGENT`` answers is PENDIENTE POR TIEMPO REAL
    duplicate_payments  0 idempotency keys with two paid runs (``ok``, ``invalid``, ``abstain``): the unique index
                        ``ai_agent_runs_paid_once`` forbids it, and it is counted all the same - an index can be dropped, a count cannot lie
    lab_envelope        the LAB's spend of every month the window touches, up to the window's last day, within the LAB envelope the worker
                        ran with (the newest ``budgets_usd.lab`` of the ledger of the owner's words, else this process's
                        ``FBI_AI_LAB_MONTHLY_BUDGET_USD``), AND the days excluded (a day an orchestrate cycle reported a ``budget_stop``
                        or an arm ``paused``) not more than the ones planned at the start. The planned number is STORED NOWHERE (no table,
                        no gate row, no setting): this part is PENDIENTE POR ACCIONES MANUALES until the owner's plan is written where the
                        code can read it; it is never invented. A month over its envelope fails all the same
    attribution         ``intel.agent_attributions`` for >= 95 % of the settled matches with runs: the matches played to a result
                        (``status_group = 'finished'``) with kick-off in the window and at least one ``ok`` run of the shadow. Read it after
                        the daily ``ai_learn`` (07:35 Bogotá), which attributes the day before. No such match is PENDIENTE POR TIEMPO REAL
    leak_audit          0 violations of ``slice_known``, ``agent_known``, ``review_known`` and ``shadow_review_known`` every night of the
                        window, and ``shadow_review_known`` with n > 0 (``leakage.passes_gate``), from the newest row of each rule and night
                        of ``intel.audit_checks`` (an earlier row of the same night that saw violations is reported). A night not audited is
                        PENDIENTE POR ACCIONES MANUALES: the audit of that day has to be run
    battery             the newest ``battery`` gate row before the end of the window was written inside the window and PASA, and the
                        battery covers every agent that answered in the shadow in the window: a target named as the agent, or a target
                        whose prompt is one the agent ran with (read from the evidence, so a target added later is seen without a change
                        here). An agent with no target is NO PASA («battery does not cover <agent>»); no measurement in the window, or one
                        that no longer speaks for the corpus in force (``battery.run.stale``), is PENDIENTE POR ACCIONES MANUALES
    research_v2         the newest ``research_v2`` gate row says PASA (the 95 % of v1's evidences is that gate's own check,
                        ``fbi.ai.gate_research``); never evaluated is PENDIENTE POR TIEMPO REAL

Everything here reads; nothing is written."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai import budget_v3, gate_a, gates, runtime
from fbi.ai.battery import run as battery_run
from fbi.ai.calendar import day_start, local_day, month_start, next_month
from fbi.ai.config import AiSettings
from fbi.intel import leakage

METHOD: Final = "gate-b-v1"
"""The rule of this module. Any change to a check, a threshold or a window is a new version, never an edit."""
GATE: Final = "gate_b"
"""The name the gate would have in ``ai.feature_gates`` - which does not accept it without a migration (see the module's docstring)."""
PASS: Final = "PASA"
FAIL: Final = "NO PASA"
PENDING_TIME: Final = "PENDIENTE POR TIEMPO REAL"
PENDING_ACTIONS: Final = "PENDIENTE POR ACCIONES MANUALES"
SEVERITY: Final[dict[str, int]] = {PASS: 0, PENDING_TIME: 1, PENDING_ACTIONS: 2, FAIL: 3}
"""The order of the verdicts: the report says the worst of its checks."""

WINDOW_DAYS: Final = 14
INVALID_MAX: Final = Decimal("0.03")
"""Plan, section 24: «≤ 3 % de salidas inválidas por agente» (the same 3 % as the arm pause of section 23)."""
MIN_RUNS_PER_AGENT: Final = 100
"""Engineering minimum, not the plan's: a version of an agent with fewer than this many answers (``ok`` + ``invalid`` + ``abstain``) in the window
cannot show a rate of 3 % with any meaning (one invalid in 30 is already 3.3 %), so its check is PENDIENTE POR TIEMPO REAL. It only DELAYS a pass:
a rate over 3 % fails whatever the sample, and no sample, however large, relaxes the 3 %."""
ATTRIBUTION_MIN: Final = Decimal("0.95")
AUDIT_RULES: Final = ("slice_known", "agent_known", "review_known", "shadow_review_known")
PAID: Final = ("ok", "invalid", "abstain")
"""``orchestrator_store.PAID_STATUSES``: a run that holds a model's answer, paid."""
CALLED: Final = (*PAID, "timeout")
"""A run that reached the model (a timeout was a call made); ``skipped``, ``budget_skip`` and ``expired`` were not."""
EXAMPLES: Final = 5


def _rate(num: int | Decimal, den: int | Decimal) -> Decimal | None:
    return None if not den else (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"))


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else f"{value * 100:.2f}"


def worst(verdicts: Iterable[str]) -> str:
    """The verdict that wins: NO PASA > PENDIENTE POR ACCIONES MANUALES > PENDIENTE POR TIEMPO REAL > PASA. Nothing to judge is PASA only
    vacuously, so a caller never passes an empty list for a real check."""
    return max(verdicts, key=lambda v: SEVERITY[v], default=PASS)


# ── what a check says ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    verdict: str
    """PASA, NO PASA or one of the two pending verdicts: the check's own, judged on its figures."""
    detail: dict[str, Any]
    reasons: tuple[str, ...] = ()
    """Why it is not PASA, in words (empty for a pass)."""

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "verdict": self.verdict, "reasons": list(self.reasons), "detail": self.detail}


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
    preview: bool = False
    """True when the window is not complete: the checks are what the would-be window shows, NOT evidence of the gate."""

    def as_json(self) -> dict[str, Any]:
        return {"gate": GATE, "method": METHOD, "verdict": self.verdict, "at": self.at.isoformat(), "window": self.window.as_json(),
                "checks": [c.as_json() for c in self.checks], "pending": list(self.pending), "preview": self.preview,
                "failing_now": [c.id for c in self.checks if c.verdict == FAIL],
                "recorded": False, "recorded_note": "ai.feature_gates does not accept gate_b without a migration: nothing is written"}

    def lines(self) -> list[str]:
        w = self.window
        out = [f"GATE B · {self.verdict}", f"Ventana: {w.first} a {w.last} ({WINDOW_DAYS} días completos, hora de Bogotá)"]
        if w.anchor is not None:
            out.append(f"Configuración estable desde {w.anchor} ({w.anchored_by}); {w.stable_days} día(s) completo(s) de {WINDOW_DAYS}")
        if self.preview:
            out.append("Vista previa (NO es evidencia del gate): la ventana aún no está completa")
        out += [f"  [{c.verdict}] {c.title}" + (f" — {'; '.join(c.reasons)}" if c.reasons else "") for c in self.checks]
        out += [f"  Falta: {p}" for p in self.pending]
        return out


def check(id_: str, title: str, verdicts: Sequence[tuple[str, str]], detail: dict[str, Any]) -> Check:
    """A check from its findings, each a (verdict, reason): the worst finding decides, and every reason that is not a pass is kept."""
    verdict = worst(v for v, _ in verdicts) if verdicts else PASS
    return Check(id_, title, verdict, detail, tuple(r for v, r in verdicts if v != PASS))


# ── the window ──────────────────────────────────────────────────────────────────────────────────────────────────

FIRST_SHADOW_SQL: Final = "SELECT min((started_at AT TIME ZONE 'America/Bogota')::date) FROM ai.agent_runs WHERE run_kind = 'shadow'"
VERSIONS_SEEN_SQL: Final = """
SELECT agent, agent_version, prompt_version, schema_version, min((started_at AT TIME ZONE 'America/Bogota')::date) AS first_day
  FROM ai.agent_runs WHERE run_kind = 'shadow' GROUP BY 1, 2, 3, 4
"""


def version_changes(rows: Iterable[tuple[str, str, str, str, date]], first_day: date) -> list[tuple[date, str]]:
    """The days a new version of an agent (its version, prompt or schema) first ran in the shadow AFTER the shadow's first day: each is a day the
    configuration changed. What ran on the first day is the baseline."""
    return [(d, f"{agent} {version} ({prompt}, {schema}) first ran") for agent, version, prompt, schema, d in rows if d > first_day]


def window_from(*, today: date, through: date | None, first_shadow: date | None, events: Sequence[tuple[date, str]]) -> Window:
    """The fourteen complete days that end on ``through`` (yesterday by default), anchored on the day after the latest event."""
    last = through or today - timedelta(days=1)
    if last >= today:
        raise ValueError(f"{last} is not a complete day yet (today is {today}): the gate measures complete days only")
    first = last - timedelta(days=WINDOW_DAYS - 1)
    if first_shadow is None:
        return Window(first, last, None, None, 0, None)
    day, why = max([(first_shadow, "the shadow's first run"), *events], key=lambda e: e[0])
    anchor = day + timedelta(days=1)
    return Window(first, last, anchor, f"{why}, {day}", max(0, (last - anchor).days + 1), anchor + timedelta(days=WINDOW_DAYS))


def window_of(conn: psycopg.Connection[Any], *, at: datetime, through: date | None = None, changes: Sequence[date] = ()) -> Window:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(FIRST_SHADOW_SQL)
        row = cur.fetchone()
        first_shadow = None if row is None else row[0]
        cur.execute(VERSIONS_SEEN_SQL)
        seen = [(str(a), str(v), str(p), str(s), d) for a, v, p, s, d in cur.fetchall()]
    events: list[tuple[date, str]] = []
    if first_shadow is not None:
        events += gate_a.flips(conn)
        events += gate_a.switch_changes(conn)
        events += version_changes(seen, first_shadow)
        events += [(d, "a change of configuration declared by whoever deployed it") for d in changes]
    return window_from(today=local_day(at), through=through, first_shadow=first_shadow, events=events)


def _bounds(w: Window) -> dict[str, datetime]:
    return {"since": day_start(w.first), "until": day_start(w.last + timedelta(days=1))}


# ── 1. final passes out of time ─────────────────────────────────────────────────────────────────────────────────

FINAL_PASSES_SQL: Final = """
SELECT count(*) AS passes, count(*) FILTER (WHERE m.created_at >= f.kickoff_at - %(margin)s) AS late,
       (array_agg(m.id ORDER BY m.id) FILTER (WHERE m.created_at >= f.kickoff_at - %(margin)s))[1:5] AS examples
  FROM ai.match_runs m JOIN core.fixtures f ON f.id = m.fixture_id
 WHERE m.run_kind = 'shadow' AND m.pass_kind = 'final' AND m.created_at >= %(since)s AND m.created_at < %(until)s
"""
FINAL_CALLS_SQL: Final = """
SELECT count(*) AS calls, count(*) FILTER (WHERE d.deadline IS NULL) AS undated,
       count(*) FILTER (WHERE r.finished_at >= d.deadline) AS late,
       (array_agg(r.id ORDER BY r.id) FILTER (WHERE r.finished_at >= d.deadline OR d.deadline IS NULL))[1:5] AS examples
  FROM ai.agent_runs r
  LEFT JOIN ai.agent_tasks t ON t.idem_key = r.idem_key
  LEFT JOIN core.fixtures f ON f.id = r.fixture_id
  CROSS JOIN LATERAL (SELECT COALESCE(t.deadline_at, f.kickoff_at - %(margin)s) AS deadline) d
 WHERE r.run_kind = 'shadow' AND r.pass_kind = 'final' AND r.status = ANY(%(called)s)
   AND r.started_at >= %(since)s AND r.started_at < %(until)s
"""
CYCLES_SQL: Final = """
SELECT started_at, counts FROM ai.cycles WHERE kind = 'orchestrate' AND started_at >= %(since)s AND started_at < %(until)s ORDER BY started_at, id
"""


@dataclass(frozen=True)
class FinalTimes:
    passes: int
    late_passes: int
    calls: int
    late_calls: int
    undated_calls: int
    skipped_too_late: int
    """The passes the guard did not start (``too_late`` of the orchestrate cycles): reported, not judged."""
    examples: dict[str, list[int]] = field(default_factory=dict)


def judge_final(f: FinalTimes) -> Check:
    findings: list[tuple[str, str]] = []
    if f.late_passes:
        findings.append((FAIL, f"{f.late_passes} final pass(es) of the shadow written at or after T-15"))
    if f.late_calls:
        findings.append((FAIL, f"{f.late_calls} call(s) of a final pass finished at or after their deadline"))
    if f.undated_calls:
        findings.append((PENDING_ACTIONS, f"{f.undated_calls} call(s) of a final pass with no deadline to read (no task, no kick-off)"))
    if f.passes == 0 and f.calls == 0:
        findings.append((PENDING_TIME, "no final pass of the shadow in the window"))
    return check("final_deadline", "0 pasadas final fuera de plazo por el Orchestrator (antes de T-15)", findings,
                 {"final_passes": f.passes, "late_passes": f.late_passes, "final_calls": f.calls, "late_calls": f.late_calls,
                  "calls_without_deadline": f.undated_calls, "passes_not_started_too_late": f.skipped_too_late,
                  "margin_minutes": int(runtime.FINAL_MARGIN.total_seconds() // 60), "maximum_late": 0, "examples": f.examples})


def cycle_reports(conn: psycopg.Connection[Any], w: Window) -> list[tuple[date, dict[str, Any]]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CYCLES_SQL, _bounds(w))
        return [(local_day(at), counts if isinstance(counts, dict) else {}) for at, counts in cur.fetchall()]


def final_times(conn: psycopg.Connection[Any], w: Window, cycles: Sequence[tuple[date, Mapping[str, Any]]]) -> FinalTimes:
    params: dict[str, Any] = _bounds(w) | {"margin": runtime.FINAL_MARGIN, "called": list(CALLED)}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FINAL_PASSES_SQL, params)
        p = cur.fetchone()
        cur.execute(FINAL_CALLS_SQL, params)
        c = cur.fetchone()
    assert p is not None and c is not None
    too_late = sum(int(r.get("too_late") or 0) for _, r in cycles if isinstance(r.get("too_late"), int))
    return FinalTimes(int(p["passes"]), int(p["late"]), int(c["calls"]), int(c["late"]), int(c["undated"]), too_late,
                      {"late_passes_match_runs": list(p["examples"] or []), "late_or_undated_calls_agent_runs": list(c["examples"] or [])})


# ── 2. invalid outputs per agent and version ────────────────────────────────────────────────────────────────────

STATUS_SQL: Final = """
SELECT agent, agent_version, status, CASE WHEN status = 'invalid' THEN split_part(coalesce(error, ''), ':', 1) END AS head, count(*) AS n
  FROM ai.agent_runs WHERE run_kind = 'shadow' AND started_at >= %(since)s AND started_at < %(until)s
 GROUP BY 1, 2, 3, 4
"""


def error_codes(head: str | None) -> list[str]:
    """The codes of an invalid run's ``error``: the part before the first colon, split on commas (``orchestrator`` writes the problems of a
    reading joined by commas, and ``code: detail`` for the others). A run with several problems counts under each of them."""
    codes = [c.strip()[:64] for c in (head or "").split(",") if c.strip()]
    return codes or ["unknown"]


@dataclass(frozen=True)
class AgentTally:
    agent: str
    version: str
    by_status: dict[str, int]
    invalid_by_code: dict[str, int]

    @property
    def answered(self) -> int:
        return sum(self.by_status.get(s, 0) for s in PAID)

    @property
    def invalid(self) -> int:
        return self.by_status.get("invalid", 0)

    @property
    def rate(self) -> Decimal | None:
        return _rate(self.invalid, self.answered)

    def as_json(self) -> dict[str, Any]:
        return {"agent": self.agent, "agent_version": self.version, "runs": sum(self.by_status.values()), "n": self.answered,
                "invalid": self.invalid, "rate_pct": _pct(self.rate), "by_status": dict(sorted(self.by_status.items())),
                "invalid_by_code": dict(sorted(self.invalid_by_code.items()))}


def tallies(rows: Iterable[tuple[str, str, str, str | None, int]]) -> list[AgentTally]:
    """(agent, version, status, error head, n) rows into one tally per agent and version."""
    status: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    codes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for agent, version, st, head, n in rows:
        status[(agent, version)][st] += n
        if st == "invalid":
            for code in error_codes(head):
                codes[(agent, version)][code] += n
    return [AgentTally(a, v, dict(status[(a, v)]), dict(codes.get((a, v), {}))) for a, v in sorted(status)]


def judge_invalid(ts: Sequence[AgentTally]) -> Check:
    findings: list[tuple[str, str]] = []
    if not ts:
        findings.append((PENDING_TIME, "no agent ran in the shadow in the window"))
    for t in ts:
        rate = t.rate
        if rate is not None and rate > INVALID_MAX:
            findings.append((FAIL, f"{t.agent} {t.version}: {t.invalid} invalid of {t.answered} ({_pct(rate)} %)"))
        elif t.answered < MIN_RUNS_PER_AGENT:
            findings.append((PENDING_TIME, f"{t.agent} {t.version}: {t.answered} answers, fewer than {MIN_RUNS_PER_AGENT}"))
    return check("invalid_outputs", "≤ 3 % de salidas inválidas por agente y versión", findings,
                 {"maximum_pct": _pct(INVALID_MAX), "minimum_answers": MIN_RUNS_PER_AGENT, "agents": [t.as_json() for t in ts]})


def agent_tallies(conn: psycopg.Connection[Any], w: Window) -> list[AgentTally]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(STATUS_SQL, _bounds(w))
        rows = [(str(a), str(v), str(s), h, int(n)) for a, v, s, h, n in cur.fetchall()]
    return tallies(rows)


# ── 3. duplicate payments ───────────────────────────────────────────────────────────────────────────────────────

PAID_SQL: Final = ("SELECT count(*) FROM ai.agent_runs WHERE status = ANY(%(paid)s) AND started_at >= %(since)s AND started_at < %(until)s")
DUPLICATES_SQL: Final = """
SELECT idem_key, count(*) AS n, array_agg(id ORDER BY id) AS runs
  FROM ai.agent_runs
 WHERE status = ANY(%(paid)s)
   AND idem_key IN (SELECT idem_key FROM ai.agent_runs WHERE started_at >= %(since)s AND started_at < %(until)s)
 GROUP BY idem_key HAVING count(*) > 1
 ORDER BY idem_key
"""


def judge_duplicates(paid: int, duplicates: Sequence[tuple[str, int, list[int]]]) -> Check:
    findings: list[tuple[str, str]] = []
    if duplicates:
        findings.append((FAIL, f"{len(duplicates)} idempotency key(s) paid more than once"))
    elif paid == 0:
        findings.append((PENDING_TIME, "no paid run in the window"))
    return check("duplicate_payments", "0 pagos duplicados (misma idem_key)", findings,
                 {"paid_runs": paid, "keys_paid_twice": len(duplicates), "maximum": 0,
                  "examples": [{"idem_key": k, "paid_runs": n, "run_ids": ids[:EXAMPLES]} for k, n, ids in duplicates[:EXAMPLES]]})


def duplicates_of(conn: psycopg.Connection[Any], w: Window) -> tuple[int, list[tuple[str, int, list[int]]]]:
    params: dict[str, Any] = _bounds(w) | {"paid": list(PAID)}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PAID_SQL, params)
        row = cur.fetchone()
        cur.execute(DUPLICATES_SQL, params)
        dups = [(str(k), int(n), [int(i) for i in ids]) for k, n, ids in cur.fetchall()]
    return (0 if row is None else int(row[0])), dups


# ── 4. the LAB within its envelope ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LabMonth:
    month: date
    through: date
    spent: Decimal
    envelope: Decimal

    def as_json(self) -> dict[str, Any]:
        return {"month": self.month.isoformat(), "through": self.through.isoformat(), "spent_usd": str(self.spent.quantize(Decimal("0.01"))),
                "envelope_usd": str(self.envelope)}


def excluded_days(cycles: Iterable[tuple[date, Mapping[str, Any]]]) -> dict[date, list[str]]:
    """The days the LAB, or an arm of it, did not run whole: an orchestrate cycle that day reported a ``budget_stop`` (the LAB yielded, or its
    money ran out) or an arm ``paused`` (``<engine>:<reason>``). Conservative: any stop of the day counts the day, so it can only raise the count."""
    out: dict[date, set[str]] = defaultdict(set)
    for day, counts in cycles:
        stop = counts.get("budget_stop")
        if isinstance(stop, str) and stop:
            out[day].add(f"budget_stop:{stop}")
        for p in counts.get("paused") or []:
            if isinstance(p, str) and p:
                out[day].add(f"paused:{p}")
    return {d: sorted(v) for d, v in sorted(out.items())}


def judge_lab(months: Sequence[LabMonth], excluded: Mapping[date, Sequence[str]], *, planned: int | None, cycles: int,
              envelope_source: str) -> Check:
    findings: list[tuple[str, str]] = []
    for m in months:
        if m.spent > m.envelope:
            findings.append((FAIL, f"the LAB spent {m.spent.quantize(Decimal('0.01'))} USD in {m.month:%Y-%m}, over its envelope of {m.envelope}"))
    if planned is None:
        findings.append((PENDING_ACTIONS, "the number of excluded days planned at the start of the shadow is not stored anywhere the code can "
                                          "read: it must be written down by the owner before this part can be judged"))
    elif len(excluded) > planned:
        findings.append((FAIL, f"{len(excluded)} day(s) excluded, more than the {planned} planned"))
    if cycles == 0:
        findings.append((PENDING_TIME, "no orchestrate cycle in the window: the excluded days cannot be read"))
    return check("lab_envelope", "LAB dentro de su sobre, con los días excluidos ≤ los previstos al arrancar", findings,
                 {"months": [m.as_json() for m in months], "envelope_source": envelope_source, "orchestrate_cycles": cycles,
                  "excluded_days": len(excluded), "planned_excluded_days": planned,
                  "excluded": {d.isoformat(): list(v) for d, v in excluded.items()}})


def lab_envelope(conn: psycopg.Connection[Any], settings: AiSettings, w: Window) -> tuple[Decimal, str]:
    """The LAB envelope the worker ran with in the window: the newest ``budgets_usd.lab`` the ledger of the owner's words holds by the window's
    end; without a ledger, this process's ``FBI_AI_LAB_MONTHLY_BUDGET_USD`` (said so in the report)."""
    until = day_start(w.last + timedelta(days=1))
    for _row, at, words in reversed(gates.switch_ledger(conn)):
        lab_words = (words.get("budgets_usd") or {}).get("lab") if isinstance(words.get("budgets_usd"), dict) else None
        if at < until and lab_words is not None:
            return Decimal(str(lab_words)), "the ledger of the owner's words"
    return settings.lab_monthly_budget, "this process's FBI_AI_LAB_MONTHLY_BUDGET_USD (no ledger row)"


def lab_months(conn: psycopg.Connection[Any], w: Window, envelope: Decimal) -> list[LabMonth]:
    out: list[LabMonth] = []
    m = month_start(w.first)
    while m <= w.last:
        through = min(w.last, next_month(m) - timedelta(days=1))
        costs = budget_v3.costs_by_day(conn, "lab", day_start(m), day_start(through + timedelta(days=1)))
        out.append(LabMonth(m, through, sum(costs.values(), Decimal(0)), envelope))
        m = next_month(m)
    return out


# ── 5. attribution ──────────────────────────────────────────────────────────────────────────────────────────────

ATTRIBUTION_SQL: Final = """
SELECT f.id, EXISTS (SELECT 1 FROM intel.agent_attributions a WHERE a.fixture_id = f.id) AS attributed
  FROM core.fixtures f
 WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND EXISTS (SELECT 1 FROM ai.agent_runs r WHERE r.fixture_id = f.id AND r.run_kind = 'shadow' AND r.status = 'ok')
 ORDER BY f.id
"""


def judge_attribution(settled: int, attributed: int, missing: Sequence[int]) -> Check:
    rate = _rate(attributed, settled)
    findings: list[tuple[str, str]] = []
    if rate is None:
        findings.append((PENDING_TIME, "no settled match with runs of the shadow in the window"))
    elif rate < ATTRIBUTION_MIN:
        findings.append((FAIL, f"attribution in {_pct(rate)} % of {settled} settled matches with runs"))
    return check("attribution", "Atribución en ≥ 95 % de los partidos liquidados con ejecuciones", findings,
                 {"settled_with_runs": settled, "attributed": attributed, "rate_pct": _pct(rate), "minimum_pct": _pct(ATTRIBUTION_MIN),
                  "missing_examples": list(missing[:EXAMPLES])})


def attribution_of(conn: psycopg.Connection[Any], w: Window) -> tuple[int, int, list[int]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(ATTRIBUTION_SQL, _bounds(w))
        rows = [(int(i), bool(a)) for i, a in cur.fetchall()]
    return len(rows), sum(1 for _, a in rows if a), [i for i, a in rows if not a]


# ── 6. the leak audit ───────────────────────────────────────────────────────────────────────────────────────────

AUDIT_SQL: Final = """
SELECT day, rule, version, n_checked, n_violations FROM intel.audit_checks
 WHERE rule = ANY(%(rules)s) AND day BETWEEN %(first)s AND %(last)s ORDER BY day, rule, checked_at DESC, id DESC
"""


def judge_audit(days: Sequence[date], rows: Iterable[tuple[date, str, str, int, int]]) -> Check:
    """``rows`` NEWEST FIRST within each (day, rule): the first row of a night decides (``leakage.passes_gate``); an earlier one that saw
    violations is reported as superseded."""
    newest: dict[tuple[date, str], tuple[str, int, int]] = {}
    superseded: list[dict[str, Any]] = []
    for day, rule, version, n, bad in rows:
        if (day, rule) not in newest:
            newest[(day, rule)] = (version, n, bad)
        elif bad > 0:
            superseded.append({"day": day.isoformat(), "rule": rule, "version": version, "violations": bad})
    missing = [f"{d.isoformat()} {r}" for d in days for r in AUDIT_RULES if (d, r) not in newest]
    dirty = [f"{d.isoformat()} {r}" for (d, r), (_v, n, bad) in sorted(newest.items()) if bad > 0]
    empty = [f"{d.isoformat()} {r}" for (d, r), (_v, n, bad) in sorted(newest.items())
             if bad == 0 and not leakage.passes_gate(r, n, bad)]
    findings: list[tuple[str, str]] = []
    if dirty:
        findings.append((FAIL, f"violations on {len(dirty)} night-rule(s): {', '.join(dirty[:EXAMPLES])}"))
    if empty:
        findings.append((FAIL, f"shadow_review_known read no row on {len(empty)} night(s): {', '.join(empty[:EXAMPLES])}"))
    if missing:
        findings.append((PENDING_ACTIONS, f"{len(missing)} night-rule(s) not audited: {', '.join(missing[:EXAMPLES])}"))
    per_rule = {r: {"nights": sum(1 for (_d, rr) in newest if rr == r),
                    "checked": sum(n for (_d, rr), (_v, n, _b) in newest.items() if rr == r),
                    "violations": sum(b for (_d, rr), (_v, _n, b) in newest.items() if rr == r)} for r in AUDIT_RULES}
    return check("leak_audit", "0 violaciones en slice_known, agent_known, review_known y shadow_review_known (esta con n > 0), cada noche",
                 findings, {"rules": per_rule, "nights": len(days), "violations": dirty, "shadow_review_known_empty": empty,
                            "not_audited": missing, "superseded_with_violations": superseded,
                            "versions": sorted({v for v, _n, _b in newest.values()})})


def audit_rows(conn: psycopg.Connection[Any], w: Window) -> list[tuple[date, str, str, int, int]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(AUDIT_SQL, {"rules": list(AUDIT_RULES), "first": w.first, "last": w.last})
        return [(d, str(r), str(v), int(n), int(b)) for d, r, v, n, b in cur.fetchall()]


# ── 7. the adversarial battery ──────────────────────────────────────────────────────────────────────────────────

BATTERY_SQL: Final = ("SELECT id, at, passed, evidence FROM ai.feature_gates WHERE gate = 'battery' AND at < %(until)s "
                      "ORDER BY at DESC, id DESC LIMIT 1")
RUNNING_SQL: Final = """
SELECT agent, array_agg(DISTINCT prompt_version ORDER BY prompt_version) AS prompts
  FROM ai.agent_runs WHERE run_kind = 'shadow' AND status = ANY(%(paid)s) AND started_at >= %(since)s AND started_at < %(until)s
 GROUP BY agent ORDER BY agent
"""


@dataclass(frozen=True)
class BatteryRow:
    id: int
    at: datetime
    passed: bool
    evidence: Mapping[str, Any]

    def targets(self) -> dict[str, Mapping[str, Any]]:
        t = self.evidence.get("targets")
        return {str(k): v for k, v in t.items() if isinstance(v, Mapping)} if isinstance(t, Mapping) else {}


def covered_by(agent: str, prompts: Iterable[str], targets: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The battery's targets that speak for an agent: one named as the agent (or whose evidence names it), or one whose prompt is a prompt the
    agent ran with. Generic on purpose: a target added to the battery is read from its evidence, not from a list kept here."""
    ps = set(prompts)
    return sorted(name for name, t in targets.items()
                  if name == agent or t.get("agent") == agent or t.get("prompt") in ps or bool(ps & set(t.get("prompts") or ())))


def judge_battery(row: BatteryRow | None, *, since: datetime, running: Mapping[str, Sequence[str]], stale: Sequence[str]) -> Check:
    findings: list[tuple[str, str]] = []
    coverage: dict[str, list[str]] = {}
    if row is None:
        findings.append((PENDING_ACTIONS, "the battery has never been measured (python -m scripts.ia_battery submit / collect)"))
    else:
        if not row.passed:
            findings.append((FAIL, "the newest battery measurement says NO PASA"))
        if row.at < since:
            findings.append((PENDING_ACTIONS, f"the newest battery measurement ({row.at.isoformat()}) is older than the window"))
        coverage = {a: covered_by(a, ps, row.targets()) for a, ps in running.items()}
        findings += [(FAIL, f"battery does not cover {a}") for a, ts in sorted(coverage.items()) if not ts]
        if stale:
            findings.append((PENDING_ACTIONS, "the measurement no longer speaks for the battery in force: " + "; ".join(stale)))
    if not running:
        findings.append((PENDING_TIME, "no agent answered in the shadow in the window: the coverage cannot be judged"))
    return check("battery", "Batería adversaria en verde y cubriendo cada agente que corrió", findings,
                 {"row": None if row is None else {"id": row.id, "at": row.at.isoformat(), "passed": row.passed,
                                                   "battery": row.evidence.get("battery"), "targets": sorted(row.targets())},
                  "agents_that_ran": {a: list(ps) for a, ps in running.items()}, "covered_by": coverage, "stale": list(stale)})


def battery_of(conn: psycopg.Connection[Any], w: Window) -> tuple[BatteryRow | None, dict[str, list[str]]]:
    params: dict[str, Any] = _bounds(w) | {"paid": list(PAID)}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(BATTERY_SQL, params)
        r = cur.fetchone()
        cur.execute(RUNNING_SQL, params)
        running = {str(x["agent"]): [str(p) for p in x["prompts"] or []] for x in cur.fetchall()}
    row = None if r is None else BatteryRow(int(r["id"]), r["at"], bool(r["passed"]), r["evidence"] if isinstance(r["evidence"], dict) else {})
    return row, running


# ── 8. research v2 ──────────────────────────────────────────────────────────────────────────────────────────────

RESEARCH_SQL: Final = ("SELECT id, at, passed, evidence FROM ai.feature_gates WHERE gate = 'research_v2' AND at <= %(at)s "
                       "ORDER BY at DESC, id DESC LIMIT 1")


def research_coverage(evidence: Mapping[str, Any]) -> str | None:
    """The coverage of v1's evidences the research gate measured (its check ``coverage``), when its evidence carries it."""
    for c in evidence.get("checks") or []:
        if isinstance(c, Mapping) and c.get("id") == "coverage" and isinstance(c.get("detail"), Mapping):
            value = c["detail"].get("coverage_pct")
            return None if value is None else str(value)
    return None


def judge_research(row: Mapping[str, Any] | None) -> Check:
    findings: list[tuple[str, str]] = []
    detail: dict[str, Any] = {"gate": "research_v2", "row": None, "minimum_coverage_pct": "95.00"}
    if row is None:
        findings.append((PENDING_TIME, "the research_v2 gate has never been evaluated (python -m scripts.ia_research_gate)"))
    else:
        evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
        detail["row"] = {"id": row["id"], "at": row["at"].isoformat(), "passed": bool(row["passed"]),
                         "coverage_pct": research_coverage(evidence or {})}
        if not row["passed"]:
            findings.append((FAIL, "the newest research_v2 gate row says NO PASA"))
    return check("research_v2", "Research v2 con ≥ 95 % de las evidencias de v1 (gate research_v2 en PASA)", findings, detail)


def research_row(conn: psycopg.Connection[Any], at: datetime) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RESEARCH_SQL, {"at": at})
        r = cur.fetchone()
    return None if r is None else dict(r)


# ── the gate ────────────────────────────────────────────────────────────────────────────────────────────────────


def days_of(w: Window) -> list[date]:
    return [w.first + timedelta(days=k) for k in range((w.last - w.first).days + 1)]


def verdict_of(window: Window, checks: Sequence[Check]) -> str:
    """The report's verdict: PENDIENTE POR TIEMPO REAL while the window is not complete (the checks are a preview); otherwise the worst check."""
    if not window.complete:
        return PENDING_TIME
    return worst(c.verdict for c in checks) if checks else PENDING_TIME


def evaluate(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, through: date | None = None,
             changes: Sequence[date] = (), planned_excluded_days: int | None = None) -> GateReport:
    """Gate B over the window that ends yesterday (or ``through``). ``planned_excluded_days`` exists for the day the owner's plan is stored
    somewhere the code reads; until then the caller passes nothing and that part is PENDIENTE POR ACCIONES MANUALES."""
    w = window_of(conn, at=at, through=through, changes=changes)
    if w.anchor is None:
        return GateReport(PENDING_TIME, at, w, pending=("the Orchestrator has not written a run of the shadow yet: nothing to measure",))
    cycles = cycle_reports(conn, w)
    paid, dups = duplicates_of(conn, w)
    settled, attributed, missing = attribution_of(conn, w)
    envelope, source = lab_envelope(conn, settings, w)
    battery, running = battery_of(conn, w)
    checks = (
        judge_final(final_times(conn, w, cycles)),
        judge_invalid(agent_tallies(conn, w)),
        judge_duplicates(paid, dups),
        judge_lab(lab_months(conn, w, envelope), excluded_days(cycles), planned=planned_excluded_days, cycles=len(cycles),
                  envelope_source=source),
        judge_attribution(settled, attributed, missing),
        judge_audit(days_of(w), audit_rows(conn, w)),
        judge_battery(battery, since=day_start(w.first), running=running,
                      stale=[] if battery is None else battery_run.stale(battery.evidence)),
        judge_research(research_row(conn, at)),
    )
    pending: list[str] = []
    if not w.complete:
        pending.append(f"{w.stable_days} de {WINDOW_DAYS} días completos con la configuración estable desde {w.anchor}; "
                       f"el primer día evaluable es {w.eligible_on}")
    pending += [f"{c.title}: {'; '.join(c.reasons)}" for c in checks if c.verdict in (PENDING_TIME, PENDING_ACTIONS)]
    return GateReport(verdict_of(w, checks), at, w, checks, tuple(pending), preview=not w.complete)
