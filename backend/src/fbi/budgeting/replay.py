"""The replay of a Bogota day under ``voi-v1``: what the policy would have given each selection against what the orchestrator spent on it, and
the cost of a useful signal by depth. READ-ONLY: it reads ``ai.pick_reviews``, ``ai.match_runs``, ``ai.agent_runs``, ``ai.usage``,
``core.fixtures`` and ``intel.agent_attributions``; it writes nothing, calls nothing and changes nothing anybody decides or shows.

THE CANDIDATES. The matches whose kick-off falls on the day; their selections are the ones production's rules reviewer reviewed
(``ai.pick_reviews``, engine ``rules``) - the orchestrator's own candidates - each from its NEWEST review before the moment and as of that review when
no moment is given (the last knowledge before the kick-off), or as of ``at`` (and only the selections reviewed by then). From the review: ``ev`` (or p_model x
odds - 1), the edge, ``p_low`` (the interval, symmetric around p_model); from ``stake-v1`` the potential stake; from the newest ``ai.match_runs``
row of the match known by the moment, the contradictions touching the selection (``material``: C06, C07, a confirmed C01/C02, or C03 with the
official line-up). A highlighted pick is not known before the day's set is frozen: the replay counts none (``assumptions``).

THE ACTUAL SPEND. ``ai.agent_runs`` (``live`` and ``shadow``) of the day's matches, ``cost_usd`` of each. A run names the selections it asked
about by the labels of its pass (``c1``...); the pass's ``ai.match_runs`` row (same match, run kind, pass and moment) says which selection each
label was. A run with labels is split equally among them; a run with none (a match-level task) among every named selection of its pass; a run
whose pass row cannot be found is ``unattributed`` - counted, never guessed. ``ai.usage`` of the same matches is given beside it as the
ledger's total (and its part with no agent run: the old route, per match, never per selection).

THE COST OF A USEFUL SIGNAL by depth: ``eval-bench-v1``'s definition (``fbi.ai.eval_bench.signals``) over the code rows of
``intel.agent_attributions`` (``attr-v1``) of each selection, against the actual spend of the selections at that depth. No attribution: omitted.

THE BUDGET. Budget v3's figures are the caller's (``fbi.ai.budget_v3.budget`` at ``budget_moment``): the replay itself never reads a clock."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import router
from fbi.ai.agents.attribution import VERSION as ATTRIBUTION_VERSION
from fbi.ai.calendar import day_bounds, day_start
from fbi.ai.eval_bench import Signals, signals
from fbi.ai.usage import Budget
from fbi.budgeting import tiers
from fbi.budgeting.allocation import Allocation, Candidate, allocate
from fbi.budgeting.tiers import TIERS, Tier, VoiInputs

METHOD: Final = "voi-replay-v1"
RUN_KINDS: Final = ("live", "shadow")
MATERIAL_CODES: Final = ("C06", "C07")
LINE_Q: Final = Decimal("0.01")
MICRO: Final = Decimal("0.000001")

FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at FROM core.fixtures f WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s ORDER BY f.id
"""
REVIEWS_SQL: Final = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
       r.fixture_id, r.market_key, r.selection, r.line, r.odds, r.p_model, r.p_low, r.edge, r.ev, r.reviewed_at, f.kickoff_at
  FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.fixture_id = ANY(%(fixtures)s) AND r.engine = 'rules' AND r.reviewed_at < f.kickoff_at
   AND (%(at)s::timestamptz IS NULL OR r.reviewed_at <= %(at)s::timestamptz)
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""
MATCH_RUNS_SQL: Final = """
SELECT m.id, m.fixture_id, m.run_kind, m.pass_kind, m.known_at, m.candidates, m.contradictions
  FROM ai.match_runs m WHERE m.fixture_id = ANY(%(fixtures)s) AND m.run_kind = ANY(%(kinds)s)
 ORDER BY m.fixture_id, m.known_at, m.id
"""
AGENT_RUNS_SQL: Final = """
SELECT r.id, r.fixture_id, r.run_kind, r.pass_kind, r.known_at, r.candidates, r.cost_usd
  FROM ai.agent_runs r WHERE r.fixture_id = ANY(%(fixtures)s) AND r.run_kind = ANY(%(kinds)s)
 ORDER BY r.id
"""
USAGE_SQL: Final = """
SELECT COALESCE(sum(u.cost_usd), 0) AS total, COALESCE(sum(u.cost_usd) FILTER (WHERE u.run_id IS NULL), 0) AS without_run
  FROM ai.usage u WHERE u.fixture_id = ANY(%(fixtures)s)
"""
ATTRIBUTIONS_SQL: Final = """
SELECT a.fixture_id, a.market_key, a.selection, a.line, a.signal = 'VERDICT' AS verdict, a.outcome, count(*) AS n
  FROM intel.agent_attributions a
 WHERE a.fixture_id = ANY(%(fixtures)s) AND a.classified_by = 'code' AND a.attribution_version = %(attr)s
 GROUP BY 1, 2, 3, 4, 5, 6
"""


def selection_key(fixture_id: int, market: str, selection: str, line: Any) -> str:
    return f"{fixture_id}:{market}:{selection}:{Decimal(str(line)).quantize(LINE_Q)}"


def budget_moment(day: date, at: datetime | None = None) -> datetime:
    """The moment budget v3 is read at for a replay: ``at``, or the start of the Bogota day (the day's allocation before it spent)."""
    return at if at is not None else day_start(day)


def _dec(x: Any) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def _q(x: Decimal) -> str:
    return str(x.quantize(MICRO))


@dataclass(frozen=True, slots=True)
class MatchRun:
    id: int
    fixture_id: int
    run_kind: str
    pass_kind: str
    known_at: datetime
    labels: Mapping[str, str]
    """Label (``c1``) -> selection key."""
    contradictions: tuple[Mapping[str, Any], ...]


def _labels(fixture_id: int, rows: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in rows or []:
        if isinstance(c, dict) and c.get("candidate") and c.get("market") and c.get("selection") is not None and c.get("line") is not None:
            out[str(c["candidate"])] = selection_key(fixture_id, str(c["market"]), str(c["selection"]), c["line"])
    return out


def is_material(c: Mapping[str, Any]) -> bool:
    return str(c.get("code")) in MATERIAL_CODES or bool(c.get("confirmed")) or bool(c.get("official_lineup"))


def contradictions_of(run: MatchRun | None, key: str) -> tuple[int, bool]:
    """(open contradictions touching the selection, whether one is material) in a pass row."""
    if run is None:
        return 0, False
    labels = {lab for lab, k in run.labels.items() if k == key}
    touching = [c for c in run.contradictions if labels & {str(x) for x in c.get("candidates") or []}]
    return len(touching), any(is_material(c) for c in touching)


def newest_before(runs: Sequence[MatchRun], moment: datetime) -> MatchRun | None:
    best: MatchRun | None = None
    for r in runs:
        if r.known_at <= moment and (best is None or (r.known_at, r.id) > (best.known_at, best.id)):
            best = r
    return best


@dataclass(frozen=True, slots=True)
class Selection:
    key: str
    fixture_id: int
    as_of: datetime
    inputs: VoiInputs


def build_inputs(row: Mapping[str, Any], *, moment: datetime, run: MatchRun | None) -> Selection:
    """One reviewed selection as the policy would have seen it at ``moment``."""
    fixture = int(row["fixture_id"])
    key = selection_key(fixture, str(row["market_key"]), str(row["selection"]), row["line"])
    odds, p_model, p_low = _dec(row["odds"]), _dec(row["p_model"]), _dec(row["p_low"])
    ev = _dec(row["ev"])
    if ev is None:
        ev = tiers.expected_value(p_model, odds)
    open_n, material = contradictions_of(run, key)
    hours = Decimal((row["kickoff_at"] - moment).total_seconds()) / 3600
    inputs = VoiInputs(ev=ev, stake_units=tiers.potential_stake(p_model, odds),
                       p_publish=tiers.publish_proxy(ev=ev, edge=_dec(row["edge"]), ev_low=tiers.expected_value(p_low, odds)),
                       interval_width=tiers.interval_width(p_model, p_low), hours_to_kickoff=hours, open_contradictions=open_n,
                       material_contradiction=material)
    return Selection(key, fixture, moment, inputs)


def split_runs(runs: Iterable[Mapping[str, Any]], passes: Mapping[tuple[int, str, str, datetime], MatchRun]) -> tuple[
        dict[str, Decimal], dict[str, int], Decimal, int]:
    """(spend per selection, runs per selection, unattributed spend, unattributed runs)."""
    spend: dict[str, Decimal] = defaultdict(Decimal)
    count: dict[str, int] = defaultdict(int)
    lost, lost_n = Decimal(0), 0
    for r in runs:
        cost = Decimal(str(r["cost_usd"] or 0))
        p = passes.get((int(r["fixture_id"]), str(r["run_kind"]), str(r["pass_kind"]), r["known_at"])) if r["known_at"] else None
        labels = [str(x) for x in r["candidates"] or []]
        keys = sorted({p.labels[lab] for lab in labels if lab in p.labels}) if p is not None and labels else (
            sorted(set(p.labels.values())) if p is not None else [])
        if not keys:
            lost += cost
            lost_n += 1
            continue
        for k in keys:
            spend[k] += cost / len(keys)
            count[k] += 1
    return dict(spend), dict(count), lost, lost_n


@dataclass(frozen=True)
class Row:
    key: str
    fixture_id: int
    as_of: datetime | None
    inputs: VoiInputs | None
    natural: str | None
    tier: Tier | None
    policy_usd: Decimal
    actual_usd: Decimal
    runs: int

    def as_json(self) -> dict[str, Any]:
        x = self.inputs
        return {"key": self.key, "fixture_id": self.fixture_id, "as_of": None if self.as_of is None else self.as_of.isoformat(),
                "in_policy": x is not None, "natural": self.natural, "tier": self.tier,
                "inputs": None if x is None else {
                    "ev": None if x.ev is None else _q(x.ev), "stake_units": str(x.stake_units), "p_publish": str(x.p_publish),
                    "interval_width": None if x.interval_width is None else _q(x.interval_width),
                    "hours_to_kickoff": None if x.hours_to_kickoff is None else str(x.hours_to_kickoff.quantize(LINE_Q)),
                    "open_contradictions": x.open_contradictions, "material_contradiction": x.material_contradiction},
                "policy_usd": _q(self.policy_usd), "actual_usd": _q(self.actual_usd),
                "delta_usd": _q(self.policy_usd - self.actual_usd), "runs": self.runs}


@dataclass(frozen=True)
class DayReplay:
    day: date
    at: datetime | None
    allocation: Allocation
    budget: Budget
    rows: tuple[Row, ...]
    unattributed_usd: Decimal
    unattributed_runs: int
    usage_total_usd: Decimal
    usage_without_run_usd: Decimal
    signals_by_tier: Mapping[Tier, Signals]

    def by_tier(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for t in TIERS:
            rows = [r for r in self.rows if r.tier == t]
            actual = sum((r.actual_usd for r in rows), Decimal(0))
            spent = [r for r in rows if r.runs]
            cell: dict[str, Any] = {"selections": len(rows), "policy_usd": _q(sum((r.policy_usd for r in rows), Decimal(0))),
                                    "actual_usd": _q(actual),
                                    "actual_mean_per_selection_usd": _q(actual / len(spent)) if spent else None}
            if t in self.signals_by_tier:
                cell["attribution"] = self.signals_by_tier[t].as_json(actual)
            out[t] = cell
        return out

    @property
    def omitted(self) -> list[str]:
        out: list[str] = []
        if not self.signals_by_tier:
            out.append("cost per useful signal: no code row of intel.agent_attributions for the selections of the day")
        if not any(r.runs for r in self.rows) and not self.unattributed_runs:
            out.append("actual spend: no agent run (live or shadow) on the matches of the day")
        return out

    def as_json(self) -> dict[str, Any]:
        outside = [r for r in self.rows if r.inputs is None]
        return {
            "method": METHOD, "policy": tiers.VERSION, "day": self.day.isoformat(), "at": None if self.at is None else self.at.isoformat(),
            "params": tiers.PARAMS, "router": router.VERSION, "budget_v3": self.budget.as_json(), "allocation": {
                k: v for k, v in self.allocation.as_json().items() if k != "shares"},
            "totals": {"policy_usd": _q(sum((r.policy_usd for r in self.rows), Decimal(0))),
                       "actual_usd": _q(sum((r.actual_usd for r in self.rows), Decimal(0))),
                       "actual_outside_policy_usd": _q(sum((r.actual_usd for r in outside), Decimal(0))),
                       "unattributed_usd": _q(self.unattributed_usd), "unattributed_runs": self.unattributed_runs,
                       "usage_total_usd": _q(self.usage_total_usd), "usage_without_run_usd": _q(self.usage_without_run_usd)},
            "by_tier": self.by_tier(), "selections": [r.as_json() for r in self.rows], "omitted": self.omitted,
            "assumptions": ["the probability of being published is voi-v1's proxy over the decision thresholds, not a measured frequency",
                            "no selection is counted highlighted (the day's set is frozen after the moments replayed)",
                            "a run's cost is split equally among the selections it asked about (all of its pass when it names none)"]}

    def lines(self) -> list[str]:
        t = self.as_json()["totals"]
        a = self.allocation
        out = [f"PRESUPUESTO POR VALOR DE LA INFORMACIÓN · {tiers.VERSION} · {self.day} (día de Bogotá) · en sombra",
               f"budget v3: {self.budget.state} · límite {a.limit_usd} USD · checkpoint {a.checkpoint}: {a.pass_room_usd} USD · reserva "
               f"checkpoints siguientes {a.reserve_later_usd} · reserva escaladas {a.reserve_escalations_usd} · profundidad máx. {a.max_tier}",
               f"política {t['policy_usd']} USD · gastado {t['actual_usd']} USD (fuera de la política {t['actual_outside_policy_usd']}, "
               f"sin atribuir {t['unattributed_usd']} en {t['unattributed_runs']} runs) · ai.usage {t['usage_total_usd']} USD"]
        for tier, cell in self.by_tier().items():
            per = (cell.get("attribution") or {}).get("cost_per_useful_signal_usd")
            out.append(f"  {tier}: {cell['selections']} selecciones · política {cell['policy_usd']} · gastado {cell['actual_usd']}"
                       + (f" · coste por señal útil {per}" if per else ""))
        for r in self.rows:
            out.append(f"  {r.key} {r.tier or '-'}: política {_q(r.policy_usd)} · gastado {_q(r.actual_usd)} ({r.runs} runs)")
        out += [f"Omitido: {o}" for o in self.omitted]
        return out


def replay_day(conn: psycopg.Connection[Any], *, day: date, budget: Budget, at: datetime | None = None, checkpoint: str = "pre",
               scope: router.Scope = "production") -> DayReplay:
    """The replay of one Bogota day (see the module's docstring). Reads only; the same rows and arguments give the same report."""
    since, until = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"since": since, "until": until})
        fixtures = [int(r["id"]) for r in cur.fetchall()]
        params: dict[str, Any] = {"fixtures": fixtures, "at": at, "kinds": list(RUN_KINDS), "attr": ATTRIBUTION_VERSION}
        cur.execute(REVIEWS_SQL, params)
        reviews = cur.fetchall()
        cur.execute(MATCH_RUNS_SQL, params)
        match_runs = [MatchRun(int(r["id"]), int(r["fixture_id"]), str(r["run_kind"]), str(r["pass_kind"]), r["known_at"],
                               _labels(int(r["fixture_id"]), r["candidates"]),
                               tuple(c for c in r["contradictions"] or [] if isinstance(c, dict))) for r in cur.fetchall()]
        cur.execute(AGENT_RUNS_SQL, params)
        agent_runs = cur.fetchall()
        cur.execute(USAGE_SQL, params)
        usage = cur.fetchone() or {"total": 0, "without_run": 0}
        cur.execute(ATTRIBUTIONS_SQL, params)
        attributions = cur.fetchall()

    by_fixture: dict[int, list[MatchRun]] = defaultdict(list)
    for m in match_runs:
        by_fixture[m.fixture_id].append(m)
    selections: list[Selection] = []
    for r in reviews:
        moment = at if at is not None else r["reviewed_at"]
        selections.append(build_inputs(r, moment=moment, run=newest_before(by_fixture[int(r["fixture_id"])], moment)))
    selections.sort(key=lambda s: s.key)
    allocation = allocate([Candidate(s.key, s.inputs) for s in selections], budget, checkpoint=checkpoint, scope=scope)
    shares = {s.key: s for s in allocation.shares}

    passes = {(m.fixture_id, m.run_kind, m.pass_kind, m.known_at): m for m in match_runs}
    spend, count, lost, lost_n = split_runs(agent_runs, passes)

    rows: list[Row] = []
    for s in selections:
        sh = shares[s.key]
        rows.append(Row(s.key, s.fixture_id, s.as_of, s.inputs, sh.natural.tier, sh.tier, sh.budget_usd, spend.get(s.key, Decimal(0)),
                        count.get(s.key, 0)))
    known = {s.key for s in selections}
    for k in sorted(set(spend) - known):
        rows.append(Row(k, int(k.split(":", 1)[0]), None, None, None, None, Decimal(0), spend[k], count.get(k, 0)))

    tier_of = {r.key: r.tier for r in rows if r.tier is not None}
    sig_rows: dict[Tier, list[tuple[bool, str, int]]] = defaultdict(list)
    for a in attributions:
        t = tier_of.get(selection_key(int(a["fixture_id"]), str(a["market_key"]), str(a["selection"]), a["line"]))
        if t is not None:
            sig_rows[t].append((bool(a["verdict"]), str(a["outcome"]), int(a["n"])))
    by_tier = {t: signals(sig_rows[t]) for t in TIERS if t in sig_rows}
    return DayReplay(day, at, allocation, budget, tuple(rows), lost, lost_n, Decimal(str(usage["total"])),
                     Decimal(str(usage["without_run"])), by_tier)
