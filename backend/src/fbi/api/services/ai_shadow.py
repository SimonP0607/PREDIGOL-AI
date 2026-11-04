"""The shadow of phase 3, read for the Admin Console (plan IA, sections 22-24 and 33): the seven arms, the contradictions, the runs of the agents and
the file of a match. Never a model call and never a write: everything here is what the orchestrator (``fbi.ai.orchestrator``) wrote - the shadow row of
``ai.match_runs``, ``ai.agent_tasks`` and ``ai.agent_runs``, the reviews of ``ai.pick_reviews`` with the engines ``ma-v1``, ``ma-v1-h`` and ``cs-v1``,
``ai.shadow_assignments`` - and the ledger (``ai.usage_scoped``, scope lab).

Three rules hold the page honest:

* NO FREE TEXT, NO ADDRESS. A model's output is shown as the codes of its closed vocabularies (``fbi.ai.contracts.base``), each value checked against
  its vocabulary before it is shown; a reference is shown only if it is a typed reference (``E:12``, ``P:path``, ``A:label``). What a production
  reviewer wrote in words is not shown at all.
* NO INVENTED METRIC. Counts, rates of counts, sums of the ledger and what ``fbi.ai.shadow`` already computed. The plan's thresholds are reported as
  counts and days against their numbers; a verdict of a gate is never produced here ("nunca forzar PASS").
* NO PRODUCTION FIGURE MOVES. Every read of ``ai.pick_reviews`` names its engines - production's or the shadow's, never both in one statement
  (``tests/unit/test_engine_filter_guard.py``).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal, cast, get_args

from fbi.ai import arms, router
from fbi.ai import shadow as evaluation
from fbi.ai.agents.common import assessment_label
from fbi.ai.calendar import DAY_TZ, day_bounds, local_day
from fbi.ai.config import ORCHESTRATOR_AGENTS, SHADOW_ENGINES, AiSettings
from fbi.ai.contracts.base import (
    CANDIDATE,
    REF,
    RISK_CODES,
    SIGNAL_CODES,
    Direction,
    Level,
    Quality,
    Stance,
)
from fbi.api.contracts.ai_layer import CycleRow
from fbi.api.contracts.ai_shadow import (
    AgentRunItem,
    AgentRuns,
    ArmRow,
    ArmSettled,
    Assignments,
    Cell,
    ContraCandidate,
    ContraCount,
    Contradictions,
    ContraItem,
    Decisions,
    Enough,
    FileArm,
    FileAssessment,
    FileAssignment,
    FileCandidate,
    FileContradiction,
    FilePass,
    FileSignal,
    FileStance,
    FileVerdicts,
    LabSpend,
    OpusDay,
    ShadowArms,
    ShadowFile,
    ShadowSwitches,
    SwitchWord,
    Treatment,
)
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now

WINDOW_DAYS: Final = 30
"""The window of the arms: the 30 days the plan asks for before it compares anything."""
CONTRA_CODES: Final = ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08")
CONTRA_ROWS: Final = 3000
"""The most shadow states with a contradiction the page reads: the counts are over these, so a window that holds more says so by being cut."""
ARM_ORDER: Final = ("model", "rules", "gap", "llm", "council_solo", "ma-v1", "ma-v1-h")
"""The seven arms in the order of the plan's table (section 22)."""
ARM_ENGINE: Final[dict[str, str | None]] = {
    "model": None, "rules": "rules", "gap": None, "llm": "llm", "council_solo": "cs-v1", "ma-v1": "ma-v1", "ma-v1-h": "ma-v1-h"}
PRODUCTION_ENGINES: Final = ("rules", "llm")
SHADOW_ARMS: Final = ("ma-v1", "ma-v1-h", "cs-v1")
assert set(SHADOW_ARMS) == set(SHADOW_ENGINES)
DECISION_COLUMN: Final = {"APPROVE": "approved", "DOWNGRADE": "downgraded", "REJECT": "rejected", "ABSTAIN": "abstained"}
FILE_ENGINES: Final = ("rules", "llm", "combined", *SHADOW_ARMS)
"""The columns of the match file: production's three reviewers, then the shadow's three engines."""
PAUSE_PREFIX: Final = "paused:"
ESCALATION_RULES: Final = frozenset({"E1", "E2", "E3", "E4", "E5", "E6", "E7"})
CODE: Final = re.compile(r"^[A-Za-z0-9_:.,\-]{1,160}$")
"""What a code the orchestrator wrote looks like. Anything else (a sentence, an address) is not shown."""
STATUSES: Final = ("ok", "fallback", "invalid_output", "failed", "over_budget")

# ── small pure helpers ─────────────────────────────────────────────────────────────────────────────────────────────

SIGNALS: Final = frozenset(SIGNAL_CODES)
RISKS: Final = frozenset(RISK_CODES)
DIRECTIONS: Final = frozenset(get_args(Direction))
LEVELS: Final = frozenset(get_args(Level))
QUALITIES: Final = frozenset(get_args(Quality))
STANCES: Final = frozenset(get_args(Stance))


def code(x: Any, *, limit: int = 160) -> str | None:
    """A code as the orchestrator writes them, or None: a text that is not one is never passed on."""
    if not isinstance(x, str) or len(x) > limit or CODE.fullmatch(x) is None:
        return None
    return x


def words(x: Any, vocabulary: frozenset[str]) -> list[str]:
    """The items of a list that are in the closed vocabulary, in order. A list that is not one is empty."""
    return [v for v in x if isinstance(v, str) and v in vocabulary] if isinstance(x, list) else []


def refs(x: Any) -> list[str]:
    """The typed references of a list (``E:12``, ``P:shared.absences``, ``A:match_evaluation``); nothing else."""
    return [v for v in x if isinstance(v, str) and REF.match(v) is not None] if isinstance(x, list) else []


def level_of(x: Any, vocabulary: frozenset[str]) -> str | None:
    return x if isinstance(x, str) and x in vocabulary else None


def treatment_of(verdict: Any) -> Treatment:
    """What a verdict token of the shadow row (``APPROVE:MEDIUM``) means for a candidate a contradiction touches."""
    head = verdict.split(":", 1)[0] if isinstance(verdict, str) else ""
    if head == "APPROVE":
        return "kept"
    if head in ("DOWNGRADE", "REJECT"):
        return "lowered"
    if head == "ABSTAIN":
        return "abstained"
    return "none"


def treatments(engines: Any, touched: Sequence[str]) -> dict[str, dict[str, Treatment]]:
    """Per engine of the pass, per touched candidate, what the Council did with it (read from ``final.engines[engine].verdicts``). An engine with no
    verdict for a candidate - paused, failed, over budget, not asked - is ``none``."""
    out: dict[str, dict[str, Treatment]] = {}
    if not isinstance(engines, dict):
        return out
    for engine, state in sorted(engines.items()):
        verdicts = state.get("verdicts") if isinstance(state, dict) else None
        verdicts = verdicts if isinstance(verdicts, dict) else {}
        out[str(engine)] = {k: treatment_of(verdicts.get(k)) for k in touched}
    return out


def decimal(x: Any) -> Decimal | None:
    try:
        return None if x is None else Decimal(str(x))
    except InvalidOperation:
        return None


def text(x: Any) -> str | None:
    return None if x is None else str(x)


def count_decisions(rows: Iterable[tuple[str, int]]) -> Decisions:
    d = dict.fromkeys(DECISION_COLUMN.values(), 0)
    for decision, n in rows:
        if decision in DECISION_COLUMN:
            d[DECISION_COLUMN[decision]] += n
    return Decisions(**d)


def switches(settings: AiSettings | None = None) -> ShadowSwitches:
    """The three words of the shadow (and the mode of the layer): what each says by itself, and whether together they let the Orchestrator run."""
    s = settings or AiSettings.from_env()
    return ShadowSwitches(
        mode=s.mode, orchestrate=s.orchestrate, engines=list(s.engines), shadow_engines=list(s.shadow_engines),
        shadow_sample=format(s.shadow_sample.normalize(), "f"), agents=list(s.agents),
        words=[
            SwitchWord(name="FBI_AI_ENGINES", value=",".join(s.engines), on=bool(s.shadow_engines)),
            SwitchWord(name="FBI_AI_SHADOW_SAMPLE", value=format(s.shadow_sample.normalize(), "f"), on=s.shadow_sample > 0),
            SwitchWord(name="FBI_AI_AGENTS", value=",".join(s.agents), on=all(a in s.agents for a in ORCHESTRATOR_AGENTS)),
        ])


# ── the arms ───────────────────────────────────────────────────────────────────────────────────────────────────────

PRODUCTION_SQL = """
WITH sample AS (
    SELECT DISTINCT fixture_id, market_key, selection, line FROM ai.pick_reviews
     WHERE engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND mode = 'shadow' AND reviewed_at >= %(since)s)
SELECT r.engine, (s.fixture_id IS NOT NULL) AS on_sample, r.decision, r.status,
       CASE WHEN r.p_market IS NULL THEN 'none' WHEN abs(r.p_model - r.p_market) > %(gap)s THEN 'rejected' ELSE 'kept' END AS gap,
       count(*) AS n, COALESCE(sum(r.cost_usd), 0) AS cost
  FROM ai.pick_reviews r
  LEFT JOIN sample s ON s.fixture_id = r.fixture_id AND s.market_key = r.market_key AND s.selection = r.selection AND s.line = r.line
 WHERE r.engine IN ('rules', 'llm') AND r.reviewed_at >= %(since)s
 GROUP BY 1, 2, 3, 4, 5
"""
"""Today's reviewers (``rules``, ``llm``) over the window, split by whether the selection is one the shadow also reviewed, by decision and status, and by
what the gap filter of the plan (the model and the market differ by more than 0.20) would have done with it."""

PRODUCTION_SELECTIONS_SQL = """
WITH sample AS (
    SELECT DISTINCT fixture_id, market_key, selection, line FROM ai.pick_reviews
     WHERE engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND mode = 'shadow' AND reviewed_at >= %(since)s)
SELECT r.engine, (s.fixture_id IS NOT NULL) AS on_sample, count(DISTINCT (r.fixture_id, r.market_key, r.selection, r.line)) AS n
  FROM ai.pick_reviews r
  LEFT JOIN sample s ON s.fixture_id = r.fixture_id AND s.market_key = r.market_key AND s.selection = r.selection AND s.line = r.line
 WHERE r.engine IN ('rules', 'llm') AND r.reviewed_at >= %(since)s
 GROUP BY 1, 2
"""

SHADOW_SQL = """
SELECT engine, decision, status, count(*) AS n, COALESCE(sum(cost_usd), 0) AS cost
  FROM ai.pick_reviews
 WHERE engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND mode = 'shadow' AND reviewed_at >= %(since)s
 GROUP BY 1, 2, 3
"""
SHADOW_SELECTIONS_SQL = """
SELECT engine, count(DISTINCT (fixture_id, market_key, selection, line)) AS n
  FROM ai.pick_reviews
 WHERE engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND mode = 'shadow' AND reviewed_at >= %(since)s
 GROUP BY 1
"""
FOOTPRINT_SQL = """
SELECT d.engine, count(*) AS calls, COALESCE(sum(d.cost_usd), 0) AS cost, count(d.latency_ms) AS latency_n,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY d.latency_ms) AS p95
  FROM (SELECT DISTINCT r.engine, u.id, u.cost_usd, u.latency_ms
          FROM ai.pick_reviews r
          CROSS JOIN LATERAL unnest(r.usage_ids) AS x(id)
          JOIN ai.usage_scoped u ON u.id = x.id
         WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND r.mode = 'shadow' AND r.reviewed_at >= %(since)s AND u.scope = 'lab') d
 GROUP BY d.engine
"""
"""The calls each engine's reviews stand on, each once per engine: a call shared by the two arms of the multi-agent is in both."""
SHADOW_USAGE_SQL = """
SELECT count(*) AS calls, COALESCE(sum(d.cost_usd), 0) AS cost
  FROM (SELECT DISTINCT u.id, u.cost_usd
          FROM ai.pick_reviews r
          CROSS JOIN LATERAL unnest(r.usage_ids) AS x(id)
          JOIN ai.usage_scoped u ON u.id = x.id
         WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND r.mode = 'shadow' AND r.reviewed_at >= %(since)s AND u.scope = 'lab') d
"""
LAB_SQL = "SELECT COALESCE(sum(cost_usd), 0) AS cost, count(*) AS calls FROM ai.usage_scoped WHERE scope = 'lab' AND at >= %(since)s"
ENGINE_STATES_SQL = """
SELECT e.key AS engine, e.value -> 'paused' AS paused, e.value ->> 'status' AS status, e.value ->> 'reason' AS reason
  FROM ai.match_runs r
 CROSS JOIN LATERAL jsonb_each(CASE WHEN jsonb_typeof(r.final -> 'engines') = 'object' THEN r.final -> 'engines' ELSE '{}'::jsonb END) e
 WHERE r.run_kind = 'shadow' AND r.created_at >= %(since)s
"""
ASSIGNMENTS_SQL = """
SELECT share, count(*) AS assigned, count(*) FILTER (WHERE sampled) AS sampled, count(*) FILTER (WHERE council_solo) AS solo,
       min(assigned_at) AS first, max(assigned_at) AS last
  FROM ai.shadow_assignments WHERE experiment = %(experiment)s GROUP BY share ORDER BY share
"""
DAYS_SQL = """
SELECT count(DISTINCT (reviewed_at AT TIME ZONE 'America/Bogota')::date) AS days, min(reviewed_at) AS since
  FROM ai.pick_reviews WHERE engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND mode = 'shadow'
"""
BOTH_SQL = """
WITH shadow AS (
    SELECT DISTINCT fixture_id, market_key, selection, line FROM ai.pick_reviews WHERE engine = 'ma-v1' AND mode = 'shadow' AND status = 'ok'),
current AS (
    SELECT DISTINCT fixture_id, market_key, selection, line FROM ai.pick_reviews WHERE engine = 'llm' AND status = 'ok')
SELECT count(*) AS n FROM shadow JOIN current USING (fixture_id, market_key, selection, line)
"""
"""Selections reviewed (status ``ok``: a real answer, not a fallback) by the multi-agent and by today's AI: the plan's "reviewed by both engines"."""
LAST_CYCLE_SQL = """
SELECT id, kind, started_at, finished_at, status, mode, budget_state, counts, cost_usd, error
  FROM ai.cycles WHERE kind = 'orchestrate' ORDER BY started_at DESC, id DESC LIMIT 1
"""


def settled_of(row: Mapping[str, Any] | None) -> ArmSettled | None:
    """The latest stored report of an engine (``fbi.ai.shadow.latest``) as counts and measures: its arms, never its gate."""
    if row is None:
        return None
    arms_ = row.get("arms")
    if not isinstance(arms_, dict):
        return None

    def n_of(name: str) -> int:
        a = arms_.get(name)
        return int(a.get("n", 0)) if isinstance(a, dict) and isinstance(a.get("n", 0), int | float) else 0

    def measure(name: str, key: str) -> float | None:
        a = arms_.get(name)
        v = a.get(key) if isinstance(a, dict) else None
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    return ArmSettled(
        report_at=row["created_at"], window_from=_midnight(row.get("window_from")), window_to=_midnight(row.get("window_to")),
        selections=n_of("model"), kept=n_of("model_ai"), rejected=n_of("rejected"),
        clv_kept=measure("model_ai", "clv"), clv_rejected=measure("rejected", "clv"),
        roi_kept=measure("model_ai", "roi"), roi_rejected=measure("rejected", "roi"))


def _midnight(d: Any) -> datetime | None:
    return datetime.combine(d, datetime.min.time(), tzinfo=DAY_TZ) if isinstance(d, date) and not isinstance(d, datetime) else d


def tally_states(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """From the engine states of the shadow rows: per engine, the passes it did not run by pause reason, and the passes it ran without a verdict by the
    code that says why (``reason``, the part before the first colon). A paused arm is counted once per reason, not again as a failure."""
    paused: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    silent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        engine = str(r["engine"])
        why = r.get("paused")
        if isinstance(why, list) and why:
            for reason in why:
                if (c := code(reason)) is not None:
                    paused[engine][c] += 1
            continue
        if r.get("status") in (None, "ok"):
            continue
        reason = r.get("reason")
        head = code(reason.split(":", 1)[0]) if isinstance(reason, str) else None
        silent[engine][head or str(r.get("status"))] += 1
    return {k: dict(v) for k, v in paused.items()}, {k: dict(v) for k, v in silent.items()}


def arm_rows(conn: Conn, since: datetime) -> list[ArmRow]:
    """The seven arms, with their counts over the window."""
    gap = Decimal(str(router.PARAMS["e6_gap"]))
    params = {"since": since, "gap": gap}
    prod: dict[str, dict[bool, dict[str, Any]]] = {}
    for r in fetch_all(conn, PRODUCTION_SQL, params):
        cell = prod.setdefault(r["engine"], {}).setdefault(bool(r["on_sample"]), {"decisions": [], "statuses": defaultdict(int), "gap": defaultdict(int), "cost": Decimal(0), "n": 0})
        n = int(r["n"])
        cell["n"] += n
        cell["decisions"].append((r["decision"], n))
        cell["statuses"][r["status"]] += n
        cell["gap"][r["gap"]] += n
        cell["cost"] += Decimal(r["cost"])
    sel_prod: dict[str, dict[bool, int]] = {}
    for r in fetch_all(conn, PRODUCTION_SELECTIONS_SQL, params):
        sel_prod.setdefault(r["engine"], {})[bool(r["on_sample"])] = int(r["n"])
    shadow_cells: dict[str, dict[str, Any]] = {}
    for r in fetch_all(conn, SHADOW_SQL, params):
        cell = shadow_cells.setdefault(r["engine"], {"decisions": [], "statuses": defaultdict(int), "cost": Decimal(0), "n": 0})
        n = int(r["n"])
        cell["n"] += n
        cell["decisions"].append((r["decision"], n))
        cell["statuses"][r["status"]] += n
        cell["cost"] += Decimal(r["cost"])
    sel_shadow = {r["engine"]: int(r["n"]) for r in fetch_all(conn, SHADOW_SELECTIONS_SQL, params)}
    foot = {r["engine"]: r for r in fetch_all(conn, FOOTPRINT_SQL, params)}
    paused, silent = tally_states(fetch_all(conn, ENGINE_STATES_SQL, params))
    reports = {r["engine"]: r for r in evaluation.latest(conn)}

    def production(engine: str, arm: str) -> ArmRow:
        by = prod.get(engine, {})
        everything = [x for cell in by.values() for x in cell["decisions"]]
        on = by.get(True)
        statuses: dict[str, int] = defaultdict(int)
        for cell in by.values():
            for k, v in cell["statuses"].items():
                statuses[k] += v
        return ArmRow(
            arm=arm, engine=engine, kind="production", scope="production",  # type: ignore[arg-type]
            reviews=sum(c["n"] for c in by.values()), selections=sum(sel_prod.get(engine, {}).values()),
            decisions=count_decisions(everything), statuses=dict(statuses), invalid=statuses.get("invalid_output", 0),
            on_sample=on["n"] if on else 0, selections_on_sample=sel_prod.get(engine, {}).get(True, 0),
            decisions_on_sample=count_decisions(on["decisions"]) if on else Decisions(),
            cost_usd=sum((c["cost"] for c in by.values()), Decimal(0)), settled=settled_of(reports.get(engine)))

    def shadow_arm(engine: str, arm: str) -> ArmRow:
        cell = shadow_cells.get(engine)
        f = foot.get(engine)
        d = count_decisions(cell["decisions"]) if cell else Decisions()
        return ArmRow(
            arm=arm, engine=engine, kind="shadow", scope="lab",  # type: ignore[arg-type]
            reviews=cell["n"] if cell else 0, selections=sel_shadow.get(engine, 0), decisions=d,
            statuses=dict(cell["statuses"]) if cell else {}, invalid=cell["statuses"].get("invalid_output", 0) if cell else 0,
            on_sample=cell["n"] if cell else 0, selections_on_sample=sel_shadow.get(engine, 0), decisions_on_sample=d,
            cost_usd=cell["cost"] if cell else Decimal(0), ledger_usd=Decimal(f["cost"]) if f else Decimal(0),
            calls=int(f["calls"]) if f else 0, latency_p95_ms=round(float(f["p95"])) if f and f["p95"] is not None else None,
            latency_n=int(f["latency_n"]) if f else 0, paused=paused.get(engine, {}), not_answered=silent.get(engine, {}),
            settled=settled_of(reports.get(engine)))

    rules = production("rules", "rules")
    rules_cells = prod.get("rules", {})

    def gap_decisions(only_sample: bool) -> Decisions:
        """The gap filter by the plan's definition: it rejects when the model and the market differ by more than 0.20; with no market there is no gap
        to measure and the selection is abstained, the rest are kept."""
        g: dict[str, int] = defaultdict(int)
        for on, cell in rules_cells.items():
            if only_sample and not on:
                continue
            for k, v in cell["gap"].items():
                g[k] += v
        return Decisions(approved=g["kept"], rejected=g["rejected"], abstained=g["none"])

    out: list[ArmRow] = []
    for arm in ARM_ORDER:
        if arm == "model":
            out.append(ArmRow(
                arm="model", kind="derived", reviews=rules.reviews, selections=rules.selections, on_sample=rules.on_sample,
                selections_on_sample=rules.selections_on_sample))
        elif arm == "gap":
            out.append(ArmRow(
                arm="gap", kind="derived", reviews=rules.reviews, selections=rules.selections, decisions=gap_decisions(False),
                on_sample=rules.on_sample, selections_on_sample=rules.selections_on_sample, decisions_on_sample=gap_decisions(True)))
        elif arm == "rules":
            out.append(rules)
        elif arm == "llm":
            out.append(production("llm", "llm"))
        else:
            out.append(shadow_arm(cast(str, ARM_ENGINE[arm]), arm))
    return out


def assignments(conn: Conn) -> Assignments:
    rows = fetch_all(conn, ASSIGNMENTS_SQL, {"experiment": arms.SALT})
    assigned = sum(int(r["assigned"]) for r in rows)
    sampled = sum(int(r["sampled"]) for r in rows)
    return Assignments(
        experiment=arms.SALT, arms_version=arms.ARMS_VERSION, assigned=assigned, sampled=sampled, unsampled=assigned - sampled,
        council_solo=sum(int(r["solo"]) for r in rows), sampled_share=round(sampled / assigned, 4) if assigned else None,
        by_share=[{"share": format(Decimal(r["share"]).normalize(), "f"), "assigned": int(r["assigned"]), "sampled": int(r["sampled"]),
                   "council_solo": int(r["solo"])} for r in rows],
        first_assigned_at=min((r["first"] for r in rows), default=None), last_assigned_at=max((r["last"] for r in rows), default=None))


def enough(conn: Conn, at: datetime) -> Enough:
    """The plan's thresholds (``ai-gate-v2``: 30 days, 300 selections) as counts and days. Reaching them says there is enough to look; it is not a pass."""
    d = fetch_one(conn, DAYS_SQL) or {}
    both = int((fetch_one(conn, BOTH_SQL) or {}).get("n", 0))
    days = int(d.get("days") or 0)
    since = d.get("since")
    running = max(0, (at - since).days) if since is not None else 0
    return Enough(
        days=days, days_need=evaluation.MIN_DAYS, days_reached=running >= evaluation.MIN_DAYS and days > 0, since=since, days_running=running,
        selections=both, selections_need=evaluation.MIN_SELECTIONS, selections_reached=both >= evaluation.MIN_SELECTIONS)


def shadow_arms(conn: Conn, *, days: int = WINDOW_DAYS, at: datetime | None = None) -> Envelope[ShadowArms]:
    """The seven arms side by side over the last ``days`` days, who is assigned to what, what the shadow cost the LAB and whether there is enough data
    to compare. Empty (with the switches' names) when the shadow has written nothing."""
    at = at or now()
    since = at - timedelta(days=days)
    usage = fetch_one(conn, SHADOW_USAGE_SQL, {"since": since}) or {}
    lab = fetch_one(conn, LAB_SQL, {"since": since}) or {}
    last = fetch_one(conn, LAST_CYCLE_SQL)
    data = ShadowArms(
        days=days, since=since, switches=switches(), assignments=assignments(conn), arms=arm_rows(conn, since), enough=enough(conn, at),
        lab=LabSpend(window_usd=Decimal(lab.get("cost") or 0), shadow_usd=Decimal(usage.get("cost") or 0), calls=int(lab.get("calls") or 0)),
        last_cycle=CycleRow.model_validate(last) if last is not None else None)
    if not any(a.kind == "shadow" and a.reviews for a in data.arms) and data.assignments.assigned == 0:
        return unavailable(data, "shadow_off" if not data.switches.orchestrate else "shadow_no_rows", status=DataStatus.EMPTY)
    return ok(data)


# ── the contradictions ─────────────────────────────────────────────────────────────────────────────────────────────

STATES_SQL = "SELECT count(*) AS n FROM ai.match_runs WHERE run_kind = 'shadow' AND created_at >= %(since)s"
CONTRA_SQL = """
SELECT r.id, r.fixture_id, r.pass_kind, r.known_at, r.created_at, r.contradictions, r.candidates, r.final -> 'engines' AS engines,
       th.name || ' - ' || ta.name AS match, f.kickoff_at
  FROM ai.match_runs r
  LEFT JOIN core.fixtures f ON f.id = r.fixture_id
  LEFT JOIN core.teams th ON th.id = f.home_team_id
  LEFT JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE r.run_kind = 'shadow' AND r.created_at >= %(since)s AND jsonb_array_length(r.contradictions) > 0
 ORDER BY r.created_at DESC, r.id DESC LIMIT %(limit)s
"""


def named_candidates(candidates: Any) -> dict[str, ContraCandidate]:
    """The ``c<n>`` names of a state's candidates and the selection each stands for."""
    out: dict[str, ContraCandidate] = {}
    for c in candidates if isinstance(candidates, list) else []:
        if isinstance(c, dict) and isinstance(c.get("candidate"), str) and CANDIDATE.match(c["candidate"]):
            out[c["candidate"]] = ContraCandidate(key=c["candidate"], market=code(c.get("market")), selection=code(c.get("selection")),
                                                  line=code(c.get("line")))
    return out


def contradiction_items(rows: Iterable[Mapping[str, Any]]) -> list[ContraItem]:
    """One item per contradiction of each shadow state, in the order of the rows, with what each engine's Council did with the candidates it touches."""
    items: list[ContraItem] = []
    for r in rows:
        names = named_candidates(r["candidates"])
        for c in r["contradictions"]:
            if not isinstance(c, dict) or c.get("code") not in CONTRA_CODES:
                continue
            touched = [k for k in c.get("candidates", []) if isinstance(k, str) and CANDIDATE.match(k)]
            items.append(ContraItem(
                code=c["code"], fixture_id=r["fixture_id"], match=r["match"], kickoff_at=r["kickoff_at"], pass_kind=r["pass_kind"],
                known_at=r["known_at"], created_at=r["created_at"], subject=code(c.get("subject")) or "match",
                candidates=[names.get(k, ContraCandidate(key=k)) for k in touched], refs=refs(c.get("refs")),
                confirmed=c.get("confirmed") is True, official_lineup=c.get("official_lineup") is True,
                starters_out=c["starters_out"] if isinstance(c.get("starters_out"), int) and not isinstance(c.get("starters_out"), bool) else 0,
                gap=code(c.get("gap")), requires=code(c.get("requires")), treatment=treatments(r["engines"], touched)))
    return items


def contradiction_counts(items: Sequence[ContraItem], run_of: Sequence[int]) -> list[ContraCount]:
    """The eight codes, always all of them, with how many were written, in how many passes and matches, and how each engine's Council treated what they
    touch. ``run_of[i]`` is the shadow state item ``i`` came from."""
    out: list[ContraCount] = []
    for c in CONTRA_CODES:
        mine = [(i, x) for i, x in enumerate(items) if x.code == c]
        treat: dict[str, dict[str, int]] = {}
        for _, x in mine:
            for engine, per in x.treatment.items():
                bucket = treat.setdefault(engine, dict.fromkeys(("kept", "lowered", "abstained", "none"), 0))
                for t in per.values():
                    bucket[t] += 1
        out.append(ContraCount(
            code=c, n=len(mine), passes=len({run_of[i] for i, _ in mine}), matches=len({x.fixture_id for _, x in mine}),
            confirmed=sum(1 for _, x in mine if x.confirmed), treatment=treat))
    return out


def contradictions(conn: Conn, *, days: int = 7, code_: str | None = None, limit: int = 50, at: datetime | None = None) -> Envelope[Contradictions]:
    """C01-C08 of the shadow: how many in the window and what the Council did with what they touch, and the most recent ones with their candidates."""
    at = at or now()
    since = at - timedelta(days=days)
    rows = fetch_all(conn, CONTRA_SQL, {"since": since, "limit": CONTRA_ROWS})
    items = contradiction_items(rows)
    run_of = [r["id"] for r in rows for c in r["contradictions"] if isinstance(c, dict) and c.get("code") in CONTRA_CODES]
    passes = int((fetch_one(conn, STATES_SQL, {"since": since}) or {}).get("n", 0))
    recent = [x for x in items if code_ is None or x.code == code_][:limit]
    data = Contradictions(days=days, since=since, switches=switches(), passes=passes, with_contradictions=len(rows), total=len(items),
                          counts=contradiction_counts(items, run_of), recent=recent)
    if passes == 0:
        return unavailable(data, "shadow_off" if not data.switches.orchestrate else "shadow_no_rows", status=DataStatus.EMPTY)
    return ok(data)


# ── the runs of the agents ─────────────────────────────────────────────────────────────────────────────────────────

RUN_COLUMNS = """r.id, r.run_kind, r.started_at, r.fixture_id, th.name || ' - ' || ta.name AS match, r.pass_kind, r.agent, r.agent_version, r.task_kind,
       r.model, r.effort, r.status, r.verdict, r.input_tokens, r.output_tokens, r.cached_tokens, r.cost_usd, r.latency_ms,
       t.route ->> 'escalation' AS escalation, t.route -> 'fired' AS fired, left(r.error, 160) AS error, left(r.idem_key, 12) AS idem,
       r.workspace, r.parent_run_id"""
RUN_FROM = """
  FROM ai.agent_runs r
  LEFT JOIN ai.agent_tasks t ON t.idem_key = r.idem_key
  LEFT JOIN core.fixtures f ON f.id = r.fixture_id
  LEFT JOIN core.teams th ON th.id = f.home_team_id
  LEFT JOIN core.teams ta ON ta.id = f.away_team_id
"""
RUNS_WHERE = """
 WHERE r.started_at >= %(since)s AND r.started_at < %(until)s
   AND (%(agent)s::text IS NULL OR r.agent = %(agent)s) AND (%(task)s::text IS NULL OR r.task_kind = %(task)s)
   AND (%(status)s::text IS NULL OR r.status = %(status)s) AND (%(model)s::text IS NULL OR r.model = %(model)s)
   AND (%(kind)s::text IS NULL OR r.run_kind = %(kind)s) AND (%(fixture)s::bigint IS NULL OR r.fixture_id = %(fixture)s)
"""
RUNS_SQL = f"SELECT {RUN_COLUMNS}{RUN_FROM}{RUNS_WHERE} ORDER BY r.started_at DESC, r.id DESC LIMIT %(limit)s"
RUN_TOTALS_SQL = f"SELECT r.status, count(*) AS n, COALESCE(sum(r.cost_usd), 0) AS cost{RUN_FROM}{RUNS_WHERE} GROUP BY r.status"
OPUS_SQL = """
SELECT count(*) FILTER (WHERE status IN ('ok', 'invalid', 'abstain')) AS calls,
       count(*) FILTER (WHERE status IN ('skipped', 'budget_skip')) AS skipped,
       COALESCE(sum(cost_usd), 0) AS cost
  FROM ai.agent_runs
 WHERE run_kind = 'shadow' AND task_kind = 'escalation' AND started_at >= %(since)s AND started_at < %(until)s
"""


def run_item(r: Mapping[str, Any]) -> AgentRunItem:
    fired = r.get("fired")
    return AgentRunItem(
        id=r["id"], run_kind=r["run_kind"], started_at=r["started_at"], fixture_id=r["fixture_id"], match=r["match"], pass_kind=r["pass_kind"],
        agent=r["agent"], agent_version=r["agent_version"], task_kind=r["task_kind"], model=r["model"], effort=r["effort"], status=r["status"],
        verdict=code(r["verdict"], limit=64), input_tokens=r["input_tokens"], output_tokens=r["output_tokens"], cached_tokens=r["cached_tokens"],
        cost_usd=r["cost_usd"], latency_ms=r["latency_ms"], escalation=level_of(r["escalation"], ESCALATION_RULES),
        fired=[x for x in fired if x in ESCALATION_RULES] if isinstance(fired, list) else [], error=code(r["error"]) if r["error"] else None,
        idem=r["idem"], workspace=r["workspace"], parent_run_id=r["parent_run_id"])


def opus_day(conn: Conn, day: date) -> OpusDay:
    since, until = day_bounds(day)
    row = fetch_one(conn, OPUS_SQL, {"since": since, "until": until}) or {}
    cap = int(router.PARAMS["opus_calls"]["shadow"])
    calls = int(row.get("calls") or 0)
    return OpusDay(day=day.isoformat(), calls=calls, cap=cap, remaining=max(0, cap - calls), skipped=int(row.get("skipped") or 0),
                   cost_usd=Decimal(row.get("cost") or 0))


def agent_runs(conn: Conn, *, day: date | None = None, agent: str | None = None, task_kind: str | None = None, status: str | None = None,
               model: str | None = None, run_kind: str | None = "shadow", fixture_id: int | None = None, limit: int = 100) -> Envelope[AgentRuns]:
    """The attempts of the agents on a Bogotá day (default today), newest first, with the filters of the page, and the day's Opus calls against the cap
    of the shadow. ``run_kind`` defaults to the shadow's own."""
    d = day or local_day(now())
    since, until = day_bounds(d)
    params = {"since": since, "until": until, "agent": agent, "task": task_kind, "status": status, "model": model, "kind": run_kind,
              "fixture": fixture_id, "limit": limit}
    rows = fetch_all(conn, RUNS_SQL, params)
    totals = fetch_all(conn, RUN_TOTALS_SQL, params)
    data = AgentRuns(
        day=d.isoformat(), switches=switches(), opus=opus_day(conn, d), total=sum(int(t["n"]) for t in totals),
        cost_usd=sum((Decimal(t["cost"]) for t in totals), Decimal(0)), by_status={t["status"]: int(t["n"]) for t in totals},
        runs=[run_item(r) for r in rows])
    if not rows:
        return unavailable(data, "no_runs", status=DataStatus.EMPTY)
    return ok(data)


# ── the file of a match ────────────────────────────────────────────────────────────────────────────────────────────

HEADER_SQL = """
SELECT f.id, th.name || ' - ' || ta.name AS match, f.kickoff_at, c.name AS competition
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(fixture)s
"""
ASSIGNMENT_SQL = """
SELECT experiment, bucket, sampled, council_solo, share, assigned_at
  FROM ai.shadow_assignments WHERE experiment = %(experiment)s AND fixture_id = %(fixture)s
"""
PASSES_SQL = """
SELECT id, pass_kind, known_at, created_at, packet_id, elapsed_ms, final ->> 'status' AS status, final ->> 'reason' AS reason
  FROM ai.match_runs WHERE fixture_id = %(fixture)s AND run_kind = 'shadow' ORDER BY known_at DESC, id DESC
"""
STATE_SQL = """
SELECT id, package_hash, candidates, contradictions, final FROM ai.match_runs WHERE id = %(id)s
"""
SHADOW_REVIEWS_SQL = """
SELECT id, engine, market_key, selection, line, decision, confidence, status, model, output, cost_usd, evidence_ids
  FROM ai.pick_reviews
 WHERE fixture_id = %(fixture)s AND packet_id = %(packet)s AND engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND mode = 'shadow'
 ORDER BY reviewed_at DESC, id DESC
"""
PRODUCTION_REVIEWS_SQL = """
SELECT id, engine, market_key, selection, line, decision, confidence, status, model, cost_usd
  FROM ai.pick_reviews
 WHERE fixture_id = %(fixture)s AND packet_id = %(packet)s AND engine IN ('rules', 'llm', 'combined')
 ORDER BY reviewed_at DESC, id DESC
"""
FILE_RUNS_SQL = f"""
SELECT {RUN_COLUMNS}, r.output, r.evidence_ids
{RUN_FROM}
 WHERE r.fixture_id = %(fixture)s AND r.run_kind = 'shadow' AND r.pass_kind = %(pass_kind)s
   AND (%(hash)s::text IS NULL OR r.package_hash = %(hash)s)
 ORDER BY r.started_at, r.id
"""


def selection_key(market: Any, selection: Any, line: Any) -> tuple[str, str, Decimal] | None:
    value = decimal(line)
    return None if value is None else (str(market), str(selection), value)


def file_candidates(candidates: Any) -> list[FileCandidate]:
    """The state's candidates as they were written - the server's names and numbers - and the selections left out, with the code that says why."""
    out: list[FileCandidate] = []
    for c in candidates if isinstance(candidates, list) else []:
        if not isinstance(c, dict):
            continue
        key = c.get("candidate")
        out.append(FileCandidate(
            key=key if isinstance(key, str) and CANDIDATE.match(key) else None, family=code(c.get("family"), limit=16),
            market=code(c.get("market")) or "", selection=code(c.get("selection")) or "", line=code(c.get("line")) or "0",
            odds=text(decimal(c.get("odds"))), p_model=text(decimal(c.get("p_model"))), p_market=text(decimal(c.get("p_market"))),
            edge=text(decimal(c.get("edge"))), ev=text(decimal(c.get("ev"))), left_out=code(c.get("left_out"))))
    return out


def file_contradictions(items: Any) -> list[FileContradiction]:
    out: list[FileContradiction] = []
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict) or c.get("code") not in CONTRA_CODES:
            continue
        detail = c.get("detail")
        out.append(FileContradiction(
            code=c["code"], subject=code(c.get("subject")) or "match", candidates=[k for k in c.get("candidates", []) if isinstance(k, str) and CANDIDATE.match(k)],
            refs=refs(c.get("refs")), confirmed=c.get("confirmed") is True,
            detail={str(k): v for k, v in detail.items() if code(str(k)) and code(v)} if isinstance(detail, dict) else {}))
    return out


def file_assessment(r: Mapping[str, Any]) -> FileAssessment | None:
    """The Match Agent's answer of one run in codes. Every value is checked against its closed vocabulary; what is not in it is dropped, and a run with
    no answer is shown as what it was (its status), not as an empty assessment."""
    out = r.get("output")
    mode = out.get("mode") if isinstance(out, dict) else None
    if not isinstance(out, dict) or mode not in ("CONTEXT", "EVALUATION"):
        fallback: Literal["CONTEXT", "EVALUATION"] = "EVALUATION" if r["task_kind"] == "evaluation" else "CONTEXT"
        return FileAssessment(label=assessment_label("match", fallback), mode=fallback, model=r["model"], status=r["status"])
    signals = [FileSignal(code=s["code"], direction=s["direction"], strength=s["strength"], refs=refs(s.get("refs")))
               for s in out.get("signals", []) if isinstance(s, dict) and s.get("code") in SIGNALS and s.get("direction") in DIRECTIONS
               and s.get("strength") in LEVELS]
    stances = [FileStance(candidate=c["candidate"], stance=c["stance"], drivers=words(c.get("drivers"), SIGNALS), risks=words(c.get("risks"), RISKS),
                          refs=refs(c.get("refs")))
               for c in out.get("candidates", []) if isinstance(c, dict) and isinstance(c.get("candidate"), str) and CANDIDATE.match(c["candidate"])
               and c.get("stance") in STANCES]
    return FileAssessment(label=assessment_label("match", mode), mode=mode, model=r["model"], status=r["status"],
                          quality=level_of(out.get("data_quality"), QUALITIES), signals=signals, candidates=stances)


def shadow_cell(row: Mapping[str, Any]) -> Cell:
    """A review of a shadow engine as a cell: the verdict and the codes under it. The text fields of the stored output are not read."""
    out = row["output"] if isinstance(row["output"], dict) else {}
    esc = out.get("escalation")
    escalation: dict[str, Any] | None = None
    if isinstance(esc, dict):
        escalation = {"rule": level_of(esc.get("rule"), ESCALATION_RULES), "replaced": esc.get("replaced") is True,
                      "skipped": code(esc.get("skipped")) if esc.get("skipped") else None, "model": code(esc.get("model"))}
    assessment = out.get("assessment")
    stances = {str(k): v for k, v in assessment.items() if isinstance(v, str) and v in STANCES and code(str(k))} if isinstance(assessment, dict) else {}
    return Cell(
        engine=row["engine"], decision=row["decision"], confidence=text(row["confidence"]), level=level_of(out.get("confidence_level"), LEVELS),
        status=row["status"], model=code(row["model"]), drivers=words(out.get("drivers"), SIGNALS), risks=words(out.get("risks"), RISKS),
        refs=refs(out.get("refs")), contradictions=[c for c in out.get("contradictions", []) if c in CONTRA_CODES] if isinstance(out.get("contradictions"), list) else [],
        stances=stances, escalation=escalation, reason=code(out.get("reason")), cost_usd=row["cost_usd"], review_id=row["id"])


def production_cell(row: Mapping[str, Any]) -> Cell:
    """A review of today's reviewers as a cell: the verdict, the confidence and the status. What the reviewer wrote in words is not shown."""
    return Cell(engine=row["engine"], decision=row["decision"], confidence=text(row["confidence"]), status=row["status"], model=code(row["model"]),
                cost_usd=row["cost_usd"], review_id=row["id"])


def code_pairs(v: Any) -> dict[str, str]:
    """A mapping of codes to codes (a candidate and the rule that escalated it); a pair with anything else in it is left out."""
    return {k: x for k, x in v.items() if code(k) and code(x)} if isinstance(v, dict) else {}


def file_arms(final: Any) -> list[FileArm]:
    engines = final.get("engines") if isinstance(final, dict) else None
    out: list[FileArm] = []
    for engine in SHADOW_ARMS:
        state = engines.get(engine) if isinstance(engines, dict) else None
        if not isinstance(state, dict):
            continue
        view = state.get("view")
        measures: dict[str, Any] | None = None
        if isinstance(view, dict):
            measures = {k: view[k] for k in ("version", "tokens", "cap", "fits") if k in view and isinstance(view[k], str | int | bool)}
            for field in ("trimmed", "assessments"):
                listed = view.get(field)
                measures[field] = [x for x in listed if isinstance(x, str) and code(x)] if isinstance(listed, list) else []
        out.append(FileArm(
            engine=engine, status=code(state.get("status")), reason=code(state.get("reason")),
            paused=[p for p in state.get("paused", []) if code(p)] if isinstance(state.get("paused"), list) else [],
            escalated=code_pairs(state.get("escalated")), escalation_skipped=code_pairs(state.get("escalation_skipped")), view=measures))
    return out


def newest(rows: Iterable[Mapping[str, Any]], names: Mapping[tuple[str, str, Decimal], str]) -> dict[str, dict[str, Mapping[str, Any]]]:
    """Per candidate name, per engine, the newest review (the rows come newest first)."""
    out: dict[str, dict[str, Mapping[str, Any]]] = {}
    for r in rows:
        key = selection_key(r["market_key"], r["selection"], r["line"])
        name = names.get(key) if key is not None else None
        if name is not None:
            out.setdefault(name, {}).setdefault(r["engine"], r)
    return out


def shadow_file(conn: Conn, fixture_id: int, *, pass_kind: str | None = None) -> Envelope[ShadowFile]:
    """The file of a match for the shadow: its assignment, the pass chosen (default the newest), the candidates the server named, the Match Agent's
    assessments in codes, the contradictions, the verdict of every engine on every candidate side by side with today's reviewers, the evidence ids the
    shadow cited and the calls it made with what they cost."""
    header = fetch_one(conn, HEADER_SQL, {"fixture": fixture_id})
    if header is None:
        raise ApiError(404, "not_found", "no such match")
    a = fetch_one(conn, ASSIGNMENT_SQL, {"experiment": arms.SALT, "fixture": fixture_id})
    assignment = None
    if a is not None:
        engines = [*arms.SAMPLE_ENGINES, arms.COUNCIL_SOLO] if a["council_solo"] else list(arms.SAMPLE_ENGINES)
        assignment = FileAssignment(
            experiment=a["experiment"], bucket=a["bucket"], sampled=a["sampled"], council_solo=a["council_solo"],
            share=format(Decimal(a["share"]).normalize(), "f"), assigned_at=a["assigned_at"], engines=engines if a["sampled"] else [])
    passes = [FilePass(id=p["id"], pass_kind=p["pass_kind"], known_at=p["known_at"], created_at=p["created_at"], packet_id=p["packet_id"],
                       status="not_run" if p["status"] == "not_run" else "ran", reason=code(p["reason"]), elapsed_ms=p["elapsed_ms"])
              for p in fetch_all(conn, PASSES_SQL, {"fixture": fixture_id})]
    chosen = next((p for p in passes if pass_kind is None or p.pass_kind == pass_kind), None)
    data = ShadowFile(fixture_id=fixture_id, match=header["match"], kickoff_at=header["kickoff_at"], competition=header["competition"],
                      switches=switches(), assignment=assignment, passes=passes, selected=chosen)
    if chosen is None:
        return unavailable(data, "shadow_off" if not data.switches.orchestrate else "no_shadow_pass", status=DataStatus.EMPTY)
    state = fetch_one(conn, STATE_SQL, {"id": chosen.id}) or {}
    candidates = file_candidates(state.get("candidates"))
    names = {k: c.key for c in candidates if c.key is not None and (k := selection_key(c.market, c.selection, c.line)) is not None}
    shadow_rows = fetch_all(conn, SHADOW_REVIEWS_SQL, {"fixture": fixture_id, "packet": chosen.packet_id}) if chosen.packet_id else []
    production_rows = fetch_all(conn, PRODUCTION_REVIEWS_SQL, {"fixture": fixture_id, "packet": chosen.packet_id}) if chosen.packet_id else []
    by_shadow, by_production = newest(shadow_rows, names), newest(production_rows, names)
    verdicts: list[FileVerdicts] = []
    for c in candidates:
        if c.key is None:
            continue
        cells = [production_cell(by_production[c.key][e]) if e in by_production.get(c.key, {}) else Cell(engine=e)
                 for e in ("rules", "llm", "combined")]
        cells += [shadow_cell(by_shadow[c.key][e]) if e in by_shadow.get(c.key, {}) else Cell(engine=e) for e in SHADOW_ARMS]
        verdicts.append(FileVerdicts(candidate=c.key, cells=cells))
    runs = fetch_all(conn, FILE_RUNS_SQL, {"fixture": fixture_id, "pass_kind": chosen.pass_kind, "hash": state.get("package_hash")})
    evidence = {int(i) for r in shadow_rows for i in r["evidence_ids"] or []} | {int(i) for r in runs for i in r["evidence_ids"] or []}
    data = data.model_copy(update={
        "candidates": candidates, "contradictions": file_contradictions(state.get("contradictions")), "arms": file_arms(state.get("final")),
        "assessments": [x for r in runs if r["agent"] == "match" and (x := file_assessment(r)) is not None], "verdicts": verdicts,
        "evidence_ids": sorted(evidence), "calls": [run_item(r) for r in runs],
        "cost_usd": sum((Decimal(r["cost_usd"]) for r in runs), Decimal(0))})
    return ok(data)
