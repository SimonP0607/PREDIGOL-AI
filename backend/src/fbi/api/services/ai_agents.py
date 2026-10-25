"""The agents of PrediGol Intelligence, read for the Admin Console (plan IA, phase 1). Never a model call and never a write: the registry is the
code's own (``fbi.ai.agents.registry``), the engine of each family is the newest promotion row (``intel.agent_champion``), the states of the matches
are what the package job stored (``ai.match_runs``; ``fbi.ai.match_runs``), the queue is the Orchestrator's tables (empty until phase 2) and the audit
is the nightly one (``fbi.intel.leakage``).

What the page may say it knows is what is here: the owner reads in it whether the registry agrees with the code, which engine each family reads, how
big the slices an agent would read are against their cap, and whether the audit found a state that knew more than its moment.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fbi.ai import match_runs as state_job
from fbi.ai import package as mcp_package
from fbi.ai.agents.registry import REGISTRY, RegistryError, parse_promotion_name
from fbi.ai.config import AiSettings
from fbi.ai.contracts.base import FAMILIES
from fbi.api.contracts.ai_agents import (
    AgentRunRow,
    AgentsOverview,
    AgentTaskRow,
    AgentView,
    AuditDay,
    AuditRule,
    FamilyEngine,
    MatchState,
    MatchStateRow,
    PackageCycles,
    PackageDay,
    PackageStats,
    PromotionRow,
    QueueStats,
    RegistryProblem,
    SliceStat,
    StateSlice,
    Timing,
)
from fbi.api.contracts.ai_layer import CycleRow
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now
from fbi.intel import leakage
from fbi.picks.daily import DAY_TZ

DAYS: Final = 7
"""The window of the figures: a week, the days Gate A asks for."""
TASK_STATES: Final = ("planned", "queued", "running", "done", "failed", "skipped", "expired")
OPEN_STATES: Final = ("planned", "queued", "running")
RUN_STATUSES: Final = ("ok", "invalid", "timeout", "abstain", "skipped", "expired", "budget_skip")
PLAN_AUDIT_RULES: Final = ("slice_known", "agent_known", "review_known", "shadow_review_known", "memory_known")
"""The rules of the nightly audit that concern what an agent may know (plan, section 31), in the order the plan lists them."""
AUDIT_RULES: Final = tuple(r for r in PLAN_AUDIT_RULES if r in leakage.RULE_NAMES)
"""Those of them the audit has so far: a rule appears here when the code that audits it does."""
HISTORY: Final = 50
"""The most states, tasks and attempts of one match the match file lists."""
DECISIONS: Final = 10

# -- the registry, the engines -------------------------------------------------------------------------------------------------------------


def registry() -> tuple[list[AgentView], list[RegistryProblem]]:
    """The registry as the code has it, and every way it disagrees with the code or with itself. A registry that cannot be read is one problem."""
    try:
        views = [AgentView.model_validate(row) for row in REGISTRY.snapshot()]
        problems = [RegistryProblem(code=p.code, subject=p.subject, text=p.text) for p in REGISTRY.problems()]
    except Exception as exc:  # the page that tells the owner the registry is wrong must not be the page that breaks because of it
        return [], [RegistryProblem(code="unreadable", subject="registry", text=f"{type(exc).__name__}: {exc}"[:300])]
    return views, problems


FAMILIES_SQL = """
SELECT f.family, c.model_name, c.since, c.promotion_id
  FROM unnest(%(families)s::text[]) AS f(family)
  LEFT JOIN LATERAL intel.agent_champion(f.family) c ON true
"""
"""One row per family, with nothing in the other columns when it has no champion: the join is a LEFT one so that no family is missing."""

DECISIONS_SQL = """
SELECT id, at, market_key AS family, model_name AS promotion, from_role, to_role, decided_by, gate_version, reason
  FROM intel.promotions WHERE entity = 'agent' ORDER BY at DESC, id DESC LIMIT %(limit)s
"""


def families(conn: Conn) -> list[FamilyEngine]:
    """The engine of each family: the champion agent of the newest promotion, or ``llm`` when no agent was ever promoted (or the last one was ended)."""
    rows = {r["family"]: r for r in fetch_all(conn, FAMILIES_SQL, {"families": list(FAMILIES)})}
    out: list[FamilyEngine] = []
    for family in FAMILIES:
        row = rows[family]
        name = row["model_name"]
        if name is None:
            out.append(FamilyEngine(family=family, engine="llm"))
            continue
        try:
            parsed = parse_promotion_name(name)
            agent, version, upstream = parsed.agent, parsed.version, list(parsed.upstream)
        except RegistryError:  # a row the owner signed with a name this code does not read: shown whole, not guessed at
            agent, version, upstream = None, None, []
        out.append(FamilyEngine(family=family, engine="agent", promotion=name, agent=agent, version=version, upstream=upstream, since=row["since"],
                                promotion_id=row["promotion_id"]))
    return out


def decisions(conn: Conn) -> list[PromotionRow]:
    return [PromotionRow.model_validate(r) for r in fetch_all(conn, DECISIONS_SQL, {"limit": DECISIONS})]


# -- the states of the matches ---------------------------------------------------------------------------------------------------------------

TOTALS_SQL = """
SELECT count(*) AS states, count(DISTINCT fixture_id) AS matches,
       count(*) FILTER (WHERE cardinality(blocking) > 0) AS blocked,
       count(*) FILTER (WHERE cardinality(flags) > 0) AS flagged,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY elapsed_ms) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY elapsed_ms) AS p95,
       max(elapsed_ms) AS max
  FROM ai.match_runs WHERE run_kind = 'live' AND created_at >= %(since)s
"""

BY_PASS_SQL = """
SELECT pass_kind, count(*) AS n FROM ai.match_runs WHERE run_kind = 'live' AND created_at >= %(since)s GROUP BY pass_kind
"""

SLICES_SQL = """
SELECT s->>'name' AS name, count(*) AS states,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (s->>'tokens')::float8) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY (s->>'tokens')::float8) AS p95,
       max((s->>'tokens')::float8) AS max,
       (array_agg((s->>'cap')::float8 ORDER BY r.created_at DESC, r.id DESC))[1] AS cap,
       count(*) FILTER (WHERE jsonb_typeof(s->'trimmed') = 'array' AND jsonb_array_length(s->'trimmed') > 0) AS trimmed,
       count(*) FILTER (WHERE NOT (s->>'fits')::boolean) AS over_cap
  FROM ai.match_runs r CROSS JOIN LATERAL jsonb_array_elements(r.slices) s
 WHERE r.run_kind = 'live' AND r.created_at >= %(since)s AND jsonb_typeof(s->'name') = 'string'
   AND jsonb_typeof(s->'tokens') = 'number' AND jsonb_typeof(s->'cap') = 'number' AND jsonb_typeof(s->'fits') = 'boolean'
 GROUP BY 1 ORDER BY 1
"""
"""A slice that is not what the writer writes (a row put in by hand) is left out of the figures, not allowed to break them. ``->`` of a key on
anything that is not an object is null, so the test of the name also leaves out an element that is a text, a number or a list. The cap shown is
the newest state's: the one the code applies now, and not the largest that was ever in force in the window."""

PER_DAY_SQL = """
SELECT (created_at AT TIME ZONE %(tz)s)::date AS day, count(*) AS states, count(DISTINCT fixture_id) AS matches,
       count(*) FILTER (WHERE cardinality(blocking) > 0) AS blocked, count(*) FILTER (WHERE cardinality(flags) > 0) AS flagged
  FROM ai.match_runs WHERE run_kind = 'live' AND created_at >= %(since)s GROUP BY 1 ORDER BY 1 DESC
"""

CYCLE_STATUS_SQL = """
SELECT status, count(*) AS n FROM ai.cycles WHERE kind = %(kind)s AND started_at >= %(since)s GROUP BY status
"""

LAST_CYCLE_SQL = """
SELECT id, kind, started_at, finished_at, status, mode, budget_state, counts, cost_usd, error
  FROM ai.cycles WHERE kind = %(kind)s ORDER BY started_at DESC, id DESC LIMIT 1
"""


def _whole(x: Any) -> int:
    """A figure of the database (a percentile, a maximum) as the whole number the page shows: rounded, not cut."""
    return round(float(x))


def _whole_or_none(x: Any) -> int | None:
    """The same for a figure that is missing when there is nothing to measure (the percentiles of no rows)."""
    return None if x is None else _whole(x)


def package_stats(conn: Conn, *, at: datetime, days: int = DAYS) -> PackageStats:
    """What the package job wrote in the last ``days``: how many states, how big the slices, how long they took, and how the job itself fared."""
    since = at - timedelta(days=days)
    params = {"since": since, "tz": DAY_TZ.key, "kind": state_job.CYCLE_KIND}
    totals = fetch_one(conn, TOTALS_SQL, params) or {}
    slices = [SliceStat(name=r["name"], states=int(r["states"]), tokens_p50=_whole(r["p50"]), tokens_p95=_whole(r["p95"]),
                        tokens_max=_whole(r["max"]), cap=_whole(r["cap"]), trimmed=int(r["trimmed"]), over_cap=int(r["over_cap"]))
              for r in fetch_all(conn, SLICES_SQL, params)]
    by_status = {r["status"]: int(r["n"]) for r in fetch_all(conn, CYCLE_STATUS_SQL, params)}
    last = fetch_one(conn, LAST_CYCLE_SQL, params)
    return PackageStats(
        days=days, since=since, states=int(totals.get("states") or 0), matches=int(totals.get("matches") or 0),
        by_pass={r["pass_kind"]: int(r["n"]) for r in fetch_all(conn, BY_PASS_SQL, params)},
        blocked=int(totals.get("blocked") or 0), flagged=int(totals.get("flagged") or 0), slices=slices,
        build_ms=Timing(p50=_whole_or_none(totals.get("p50")), p95=_whole_or_none(totals.get("p95")), max=_whole_or_none(totals.get("max"))),
        per_day=[PackageDay(day=r["day"], states=int(r["states"]), matches=int(r["matches"]), blocked=int(r["blocked"]), flagged=int(r["flagged"]))
                 for r in fetch_all(conn, PER_DAY_SQL, params)],
        cycles=PackageCycles(total=sum(by_status.values()), ok=by_status.get("ok", 0), partial=by_status.get("partial", 0),
                             failed=by_status.get("failed", 0), running=by_status.get("running", 0),
                             last=CycleRow.model_validate(last) if last is not None else None),
        rule={"state_version": state_job.STATE_VERSION, "package_version": mcp_package.VERSION, "window_days": state_job.WINDOW.days,
              "limit": state_job.LIMIT, "max_seconds": state_job.MAX_SECONDS})


# -- the queue -------------------------------------------------------------------------------------------------------------------------------

TASKS_SQL = "SELECT state, count(*) AS n FROM ai.agent_tasks WHERE created_at >= %(since)s GROUP BY state"
RUNS_SQL = "SELECT status, count(*) AS n FROM ai.agent_runs WHERE started_at >= %(since)s GROUP BY status"
OPEN_SQL = """
SELECT count(*) AS open, COALESCE(sum(reserved_usd), 0) AS reserved FROM ai.agent_tasks WHERE state = ANY(%(open)s)
"""


def queue_stats(conn: Conn, *, at: datetime, days: int = DAYS) -> QueueStats:
    since = at - timedelta(days=days)
    tasks = dict.fromkeys(TASK_STATES, 0) | {r["state"]: int(r["n"]) for r in fetch_all(conn, TASKS_SQL, {"since": since})}
    runs = dict.fromkeys(RUN_STATUSES, 0) | {r["status"]: int(r["n"]) for r in fetch_all(conn, RUNS_SQL, {"since": since})}
    opened = fetch_one(conn, OPEN_SQL, {"open": list(OPEN_STATES)}) or {}
    return QueueStats(days=days, tasks=tasks, runs=runs, open=int(opened.get("open") or 0), reserved_usd=Decimal(opened.get("reserved") or 0))


# -- the audit -------------------------------------------------------------------------------------------------------------------------------

AUDIT_SQL = """
SELECT DISTINCT ON (day, rule) day, rule, checked_at, version, n_checked, n_violations, examples
  FROM intel.audit_checks WHERE rule = ANY(%(rules)s) AND day >= %(first)s ORDER BY day, rule, checked_at DESC
"""


def audit(conn: Conn, *, at: datetime, days: int = DAYS) -> list[AuditRule]:
    """Each rule of the audit that concerns the agents, its latest verdict of each day of the window (newest day first) and the totals. A rule
    the audit has not run yet has no days: it is shown as such, never as a clean record."""
    first = at.astimezone(DAY_TZ).date() - timedelta(days=days - 1)
    rows = fetch_all(conn, AUDIT_SQL, {"rules": list(AUDIT_RULES), "first": first})
    out: list[AuditRule] = []
    for rule in AUDIT_RULES:
        mine = sorted((r for r in rows if r["rule"] == rule), key=lambda r: r["day"], reverse=True)
        out.append(AuditRule(rule=rule, days=[AuditDay.model_validate(r) for r in mine], days_audited=len(mine),
                             checked=sum(int(r["n_checked"]) for r in mine), violations=sum(int(r["n_violations"]) for r in mine)))
    return out


# -- the page --------------------------------------------------------------------------------------------------------------------------------

def overview(conn: Conn, *, at: datetime | None = None, days: int = DAYS) -> Envelope[AgentsOverview]:
    at = at or now()
    settings = AiSettings.from_env()
    views, problems = registry()
    return ok(AgentsOverview(
        registry=views, problems=problems, families=families(conn), decisions=decisions(conn), package=package_stats(conn, at=at, days=days),
        queue=queue_stats(conn, at=at, days=days), audit=audit(conn, at=at, days=days),
        settings={"mode": settings.mode, "package": settings.package}))


# -- the file of a match ---------------------------------------------------------------------------------------------------------------------

RUN_COLUMNS = """r.id, r.fixture_id, r.run_kind, r.pass_kind, r.known_at, r.created_at, r.state_version, r.package_version, r.package_hash,
       r.packet_id, r.elapsed_ms, r.slices, r.blocking, r.flags, r.model_status, r.agents, r.contradictions, r.candidates, r.risks, r.final"""

HISTORY_SQL = f"""
SELECT {RUN_COLUMNS} FROM ai.match_runs r WHERE r.fixture_id = %(fixture)s ORDER BY r.known_at DESC, r.id DESC LIMIT %(limit)s
"""

CURRENT_SQL = """
SELECT match_run_id FROM ai.match_state WHERE fixture_id = %(fixture)s
"""

TASKS_OF_SQL = """
SELECT id, agent, agent_version, task_kind, pass_kind, state, run_kind, priority, est_cost_usd, attempts, reason, created_at, deadline_at
  FROM ai.agent_tasks WHERE fixture_id = %(fixture)s ORDER BY created_at DESC, id DESC LIMIT %(limit)s
"""

RUNS_OF_SQL = """
SELECT id, agent, agent_version, task_kind, pass_kind, run_kind, status, model, verdict, started_at, finished_at, cost_usd, reason
  FROM ai.agent_runs WHERE fixture_id = %(fixture)s ORDER BY started_at DESC, id DESC LIMIT %(limit)s
"""


def _names(x: Any) -> list[str]:
    return [str(n) for n in x] if isinstance(x, list) else []


def _number(x: Any) -> int:
    return int(x) if isinstance(x, int | float) and not isinstance(x, bool) else 0


def _slice(s: dict[str, Any]) -> StateSlice:
    """A slice as ``Slice.measures()`` wrote it, read without trusting it: the page that shows a state must not fail on a row it was not written by."""
    return StateSlice(name=str(s.get("name", "")), hash=str(s.get("hash", "")), tokens=_number(s.get("tokens")), cap=_number(s.get("cap")),
                      fits=s.get("fits") is True, trimmed=_names(s.get("trimmed")), blocks=_names(s.get("blocks")))


def state_row(r: dict[str, Any]) -> MatchStateRow:
    """One row of ``ai.match_runs`` as the file of a match shows it: the measures of each slice, never its content (the table keeps none). The
    table checks that its lists are lists and its statuses objects, so those are read as they are; only what the writer puts inside a slice, which
    nothing checks, is read without trusting it."""
    code = r["model_status"].get("code")  # the table checks that model_status is an object; what is inside it is the writer's
    return MatchStateRow(
        id=r["id"], fixture_id=r["fixture_id"], run_kind=r["run_kind"], pass_kind=r["pass_kind"], known_at=r["known_at"], created_at=r["created_at"],
        state_version=r["state_version"], package_version=r["package_version"], package_hash=r["package_hash"], packet_id=r["packet_id"],
        elapsed_ms=r["elapsed_ms"], slices=[_slice(s) for s in r["slices"] if isinstance(s, dict)],
        blocking=list(r["blocking"]), flags=list(r["flags"]), code=code if isinstance(code, str) else None, agents=len(r["agents"]),
        contradictions=len(r["contradictions"]), candidates=len(r["candidates"]), risks=len(r["risks"]), final=bool(r["final"]))


def match_state(conn: Conn, fixture_id: int) -> Envelope[MatchState]:
    """The state of a match - the newest live row, which is what ``ai.match_state`` says - with every state it went through, newest first, and the
    tasks and attempts of the agents on it (none until phase 2)."""
    rows = fetch_all(conn, HISTORY_SQL, {"fixture": fixture_id, "limit": HISTORY})
    history = [state_row(r) for r in rows]
    current_id = fetch_one(conn, CURRENT_SQL, {"fixture": fixture_id})
    current = next((s for s in history if current_id is not None and s.id == current_id["match_run_id"]), None)
    if current is None and current_id is not None:  # older than the list: read it on its own
        one = fetch_one(conn, f"SELECT {RUN_COLUMNS} FROM ai.match_runs r WHERE r.id = %(id)s", {"id": current_id["match_run_id"]})
        current = state_row(one) if one is not None else None
    state = MatchState(
        fixture_id=fixture_id, current=current, history=history,
        tasks=[AgentTaskRow.model_validate(r) for r in fetch_all(conn, TASKS_OF_SQL, {"fixture": fixture_id, "limit": HISTORY})],
        runs=[AgentRunRow.model_validate(r) for r in fetch_all(conn, RUNS_OF_SQL, {"fixture": fixture_id, "limit": HISTORY})])
    if current is None:
        return unavailable(state, "no_live_state_yet", status=DataStatus.EMPTY)
    return ok(state)
